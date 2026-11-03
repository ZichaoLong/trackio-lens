"""Accept a committed update and exercise recovery on an ISOLATED managed instance.

Requires a fresh --bootstrap-account installation with service, data and auth
directories under --output. Restarts only that verified instance. Never point
this at a normal deployment. Passwords/cookies and evidence stay in --output.
"""

import argparse
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release import activate, read_build  # noqa: E402

from trackio_lens import skills  # noqa: E402
from trackio_lens.auth import COOKIE  # noqa: E402
from trackio_lens.config import private_json, private_path  # noqa: E402
from trackio_lens.management import read_instance, read_management  # noqa: E402


def sign_in(page, base, credentials):
    page.goto(base + "/settings")
    page.get_by_label("Username", exact=True).fill(credentials["username"])
    page.get_by_label("Password", exact=True).fill(credentials["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()


def verify_skill(root, output, commit):
    preference = skills.settings(root)
    if not preference or not preference["destination"]:
        raise ValueError("Acceptance requires an installed integration skill")
    entry = Path(preference["destination"])
    # Resolve the parent, not the entry (which deliberately follows current).
    if not entry.parent.resolve().is_relative_to(output):
        raise ValueError("Acceptance skill must be installed under --output")
    assert not preference.get("retired")
    assert entry.is_symlink() and entry.readlink() == skills.link_target(root)
    selected = (root / "current").resolve()
    assert entry.resolve() == selected / "source" / skills.PACKAGE
    assert skills.validate_release(selected) == commit


def verify(config, output, commit):
    instance, management = read_instance(config), read_management(config)
    root, data, state = (
        Path(management["root"]),
        Path(instance["data_dir"]),
        Path(instance["state_dir"]),
    )
    output = output.resolve()
    private_path(output, directory=True)
    if not all(p.resolve().is_relative_to(output) for p in (root, data, state)):
        raise ValueError(
            "Acceptance requires all instance state under the isolated output directory"
        )
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Select an exact committed source")
    if instance.get("host") != "127.0.0.1" or instance.get("port") == 7860:
        raise ValueError("Acceptance requires a separate loopback port")
    unit = Path.home() / ".config/systemd/user" / management["service"]
    private_path(unit)
    if str(root / "current/venv/bin/trackio-lens") not in unit.read_text():
        raise ValueError("Acceptance service ownership mismatch")
    if not (state / "initial-access.json").exists():
        raise ValueError("Use a fresh bootstrap instance for this acceptance")
    initial = json.loads((state / "initial-access.json").read_text())
    base = f"http://127.0.0.1:{instance['port']}"
    before = read_build(root / "current/source/frontend/dist")["source_commit"]
    verify_skill(root, output, before)
    if before == commit:
        raise ValueError(
            "Install the previous committed release before testing a new update"
        )
    owner = {"username": "acceptance-owner", "password": secrets.token_urlsafe(24)}
    viewer = {"username": "acceptance-viewer", "password": secrets.token_urlsafe(24)}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chromium", headless=True)
        admin = browser.new_context(viewport={"width": 1440, "height": 900})
        page = admin.new_page()
        sign_in(page, base, initial)
        expect(page.locator(".setup")).to_be_visible()
        page.get_by_label("Username", exact=True).fill(owner["username"])
        page.get_by_label("Current password", exact=True).fill(initial["password"])
        page.get_by_label("New password or passphrase", exact=True).fill(
            owner["password"]
        )
        page.get_by_label("Repeat new password", exact=True).fill(owner["password"])
        page.get_by_role("button", name="Save account", exact=True).click()
        expect(page.locator(".users")).to_be_visible()
        private_json(output / "owner.json", owner)
        owner_session = admin.request.get(base + "/__lens/session").json()
        created = admin.request.post(
            base + "/__lens/users",
            headers={"X-Trackio-Lens-CSRF": owner_session["csrf"]},
            data={"action": "create", **viewer, "current_password": owner["password"]},
        )
        assert created.ok
        viewer_context = browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        viewer_page = viewer_context.new_page()
        sign_in(viewer_page, base, viewer)
        expect(viewer_page.locator(".setup")).to_be_visible()
        temporary = viewer["password"]
        viewer["password"] = secrets.token_urlsafe(24)
        viewer_page.get_by_label("Current password", exact=True).fill(temporary)
        viewer_page.get_by_label("New password or passphrase", exact=True).fill(
            viewer["password"]
        )
        viewer_page.get_by_label("Repeat new password", exact=True).fill(
            viewer["password"]
        )
        viewer_page.get_by_role("button", name="Save account", exact=True).click()
        # AccountSettings is also present in the setup screen. Wait for the
        # completed setup navigation before saving the replacement cookie.
        expect(viewer_page.locator(".setup")).not_to_be_visible()
        expect(viewer_page.locator(".account")).to_be_visible()
        assert viewer_page.locator(".users").count() == 0
        private_json(output / "viewer.json", viewer)
        admin_storage, viewer_storage = (
            admin.storage_state(),
            viewer_context.storage_state(),
        )
        private_json(output / "admin-storage.json", admin_storage)
        private_json(output / "viewer-storage.json", viewer_storage)
        assert not viewer_context.request.get(base + "/__lens/session").json()[
            "needs_setup"
        ]
        owner_cookie = next(
            c["value"] for c in admin_storage["cookies"] if c["name"] == COOKIE
        )
        viewer_cookie = next(
            c["value"] for c in viewer_storage["cookies"] if c["name"] == COOKIE
        )
        updates = page.locator(".updates")
        updates.get_by_role("button", name="Check main for updates", exact=True).click()
        # The server gives the remote Git read 30 seconds; the ordinary DOM
        # assertion timeout can expire while that successful read is pending.
        expect(updates).to_contain_text(commit, timeout=40_000)
        updates.get_by_role(
            "button", name=re.compile("Install selected commit")
        ).click()
        expect(updates.locator(".progress")).to_be_visible()
        # Neither open page nor browser process is required for publication.
        browser.close()
        with httpx.Client(
            base_url=base, timeout=15, trust_env=False, cookies={COOKIE: owner_cookie}
        ) as client:
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                try:
                    response = client.get("/__lens/updates")
                    if response.status_code == 200:
                        operation = response.json().get("operation")
                        if operation and operation["phase"] == "complete":
                            assert operation["result"]["source_commit"] == commit
                            break
                        if operation and operation["phase"] in {
                            "failed",
                            "interrupted",
                        }:
                            raise RuntimeError(
                                "Acceptance update failed; inspect the private update operation"
                            )
                except httpx.HTTPError:
                    pass  # Short restart while the complete artifact switches.
                time.sleep(2)
            else:
                raise TimeoutError("Acceptance publication deadline exceeded")
            assert client.get("/__lens/session").json()["role"] == "admin"
            assert client.get("/__lens/build").json()["source_commit"] == commit
        verify_skill(root, output, commit)
        browser = playwright.chromium.launch(channel="chromium", headless=True)
        for storage, role, width in (
            (admin_storage, "admin", 1440),
            (viewer_storage, "viewer", 390),
        ):
            context = browser.new_context(
                storage_state=storage, viewport={"width": width, "height": 844}
            )
            page = context.new_page()
            page.goto(base + "/runs?project=lens-demo")
            expect(page.locator(".runs-table")).to_be_visible()
            page.reload()
            expect(page.locator(".runs-table")).to_be_visible()
            page.goto(base + "/settings")
            expect(page.locator(".account")).to_be_visible()
            assert context.request.get(base + "/__lens/session").json()["role"] == role
            assert (
                context.request.get(base + "/__lens/build").json()["source_commit"]
                == commit
            )
            if role == "admin":
                expect(page.locator(".updates")).to_contain_text(commit[:12])
            else:
                assert page.locator(".updates").count() == 0
            page.screenshot(path=str(output / (role + "-after-update.png")))
            context.close()
        browser.close()
    private_json(
        output / "cookies.json", {"admin": owner_cookie, "viewer": viewer_cookie}
    )
    previous = (root / "current").resolve()
    failed = root / "acceptance-failed-candidate"
    (failed / "venv/bin").mkdir(parents=True, mode=0o700)
    executable = failed / "venv/bin/trackio-lens"
    executable.write_text(
        "#!/bin/sh\n# Controlled failure before opening any data.\nexit 42\n"
    )
    executable.chmod(0o700)
    (failed / "source").symlink_to(previous / "source", target_is_directory=True)
    program = json.loads((state / "api-access.json").read_text())
    # Only this isolated, previously verified unit is restarted by activate().
    try:
        activate(root, failed, previous, management["service"], base, program)
    except RuntimeError as error:
        assert "restored the verified authenticated" in str(error)
    else:
        raise AssertionError("Controlled startup failure unexpectedly passed")
    with httpx.Client(base_url=base, trust_env=False) as client:
        assert client.get("/version").status_code == 401
        for cookie, role in ((owner_cookie, "admin"), (viewer_cookie, "viewer")):
            response = client.get(
                "/__lens/session", headers={"Cookie": COOKIE + "=" + cookie}
            )
            assert response.status_code == 200 and response.json()["role"] == role
            projects = client.post(
                "/api/get_all_projects",
                headers={
                    "Cookie": COOKIE + "=" + cookie,
                    "X-Trackio-Lens-CSRF": response.json()["csrf"],
                },
                json={},
            )
            assert (
                projects.status_code == 200 and "lens-demo" in projects.json()["data"]
            )
    assert (root / "current").resolve() == previous
    verify_skill(root, output, commit)
    result = {
        "from_commit": before,
        "to_commit": commit,
        "browser_closed_during_update": True,
        "administrator_session_preserved": True,
        "viewer_session_preserved": True,
        "frontend_refresh_verified": True,
        "failed_start_restored": True,
        "anonymous_denied_after_recovery": True,
        "synthetic_instance_only": True,
        "integration_skill_install_update_recovery": True,
    }
    private_json(output / "acceptance.json", result)
    return result


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.config, args.output, args.commit)))
