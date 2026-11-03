"""Exercise only the synthetic fixture; screenshots and logs stay private.

Run against an authenticated demo instance seeded with scripts/seed_demo.py.
This is simulated viewport coverage, not physical-device acceptance.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def check(base, credentials_path, output, strict=False):
    credentials = json.loads(credentials_path.read_text())
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chromium", headless=True)
        for width in (1440, 360, 390, 430):
            context = browser.new_context(
                viewport={"width": width, "height": 900 if width > 800 else 844},
                is_mobile=width < 800,
                has_touch=width < 800,
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/files?project=lens-demo")
            expect(page.get_by_role("heading", name="Trackio Lens")).to_be_visible()
            page.get_by_label("Username").fill(credentials["username"])
            page.get_by_label("Password", exact=True).fill("wrong-password")
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text("Invalid")
            page.get_by_label("Password", exact=True).fill(credentials["password"])
            page.get_by_role("button", name="Sign in", exact=True).click()
            if width == 1440 and credentials_path.name == "initial-access.json":
                expect(page.locator(".setup")).to_be_visible()
                session = context.request.get(base + "/__lens/session").json()
                assert (
                    context.request.post(
                        base + "/api/get_all_projects",
                        headers={"X-Trackio-Lens-CSRF": session["csrf"]},
                        data={},
                    ).status
                    == 403
                )
                page.get_by_label("Username", exact=True).fill("demo-owner")
                page.get_by_label("Current password", exact=True).fill(
                    credentials["password"]
                )
                page.get_by_label("New password or passphrase", exact=True).fill("p")
                page.get_by_label("Repeat new password", exact=True).fill("p")
                page.get_by_role("button", name="Save account", exact=True).click()
                credentials.update(username="demo-owner", password="p")
            expect(page.locator(".files-page")).to_be_visible()
            assert page.url.endswith("/files?project=lens-demo")
            for route, selector in (
                ("/", ".plot-container"),
                ("/runs", ".runs-table"),
                ("/system", ".system-page .plot-container"),
                ("/reports", ".report-card"),
                ("/media", ".media-page"),
                ("/files", ".file-list"),
                ("/artifacts", ".page-content"),
            ):
                page.goto(base + route + "?project=lens-demo")
                expect(page.locator(selector).first).to_be_visible(timeout=15000)
                page.wait_for_timeout(350)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                ), (width, route)
                if route == "/":
                    assert page.locator("canvas").count() > 0
                elif route == "/runs":
                    expect(
                        page.get_by_text(
                            "experiment-0-long-name-learning-rate-comparison",
                            exact=True,
                        ).last
                    ).to_be_visible()
                elif route == "/reports":
                    assert page.locator(".report-card").count() == 3
                    if strict:
                        assert page.locator(".reports-page").evaluate(
                            "e=>e.scrollWidth <= e.clientWidth + 1"
                        )
                elif route == "/media":
                    expect(page.locator(".media-page img").first).to_be_visible()
                    assert page.locator(".media-page img").first.evaluate(
                        "e=>e.complete && e.naturalWidth > 0"
                    )
                elif route == "/files":
                    if strict:
                        assert page.locator(".files-page").evaluate(
                            "e=>e.scrollWidth <= e.clientWidth + 1"
                        )
                    page.locator(".file-name").first.click()
                    expect(page.locator(".preview-code")).to_contain_text("synthetic")
                    response = context.request.get(
                        base + page.locator(".download-btn").first.get_attribute("href")
                    )
                    assert response.ok and "synthetic" in response.text()
                elif route == "/artifacts":
                    expect(
                        page.get_by_text("evaluation-config", exact=True).last
                    ).to_be_visible()
                    artifact = page.locator("a.file-entry").first
                    expect(artifact).to_be_visible()
                    response = context.request.get(
                        base + artifact.get_attribute("href")
                    )
                    assert response.ok and "synthetic" in response.text()
                page.reload()
                expect(page.locator(selector).first).to_be_visible(timeout=15000)
                if width in (1440, 390):
                    page.screenshot(
                        path=str(
                            output / f"{width}-{route.strip('/') or 'metrics'}.png"
                        )
                    )
                results.append(
                    {"width": width, "route": route, "deep_link_reload": "passed"}
                )
            page.goto(base + "/?project=lens-demo&plots_per_row=6")
            expect(page.locator("canvas").first).to_be_visible(timeout=15000)
            if width < 800:
                if strict:
                    assert (
                        page.locator(".plot-grid").first.evaluate(
                            "e=>getComputedStyle(e).gridTemplateColumns.split(' ').length"
                        )
                        == 1
                    )
                before = page.locator(".main").evaluate("e=>e.clientWidth")
                page.get_by_title("Expand sidebar", exact=True).click()
                assert page.locator(".main").evaluate("e=>e.clientWidth") == before
                expect(
                    page.get_by_title("Collapse sidebar", exact=True)
                ).to_be_visible()
            page.get_by_label("Show run comparer", exact=True).check()
            if width < 800:
                page.get_by_title("Collapse sidebar", exact=True).click()
            expect(page.locator(".run-comparer")).to_be_visible()
            expect(page.locator(".comparer-table")).to_contain_text("learning_rate")
            full_value = page.locator(".full-value").first
            full_value.locator("summary").click()
            expect(full_value.locator("pre")).to_contain_text(
                "A reproducible example with long configuration text"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if strict:
                plot = page.locator(".plot-container").first
                plot.scroll_into_view_if_needed()
                if width < 800:
                    plot.locator("canvas").tap(position={"x": 120, "y": 90})
                else:
                    plot.hover()
                    plot.get_by_role("button", name="Read values", exact=True).click()
                expect(plot.locator(".chart-readout")).to_be_visible()
                assert plot.locator(".chart-readout dd").count() == 3
                plot.locator(".chart-readout input").focus()
                plot.locator(".chart-readout input").press("ArrowRight")
                plot.locator(".chart-readout input").press("Home")
                assert sorted(
                    float(value)
                    for value in plot.locator(".chart-readout dd").all_text_contents()
                ) == [0.0, 1.0, 2.0]
            page.goto(base + "/runs?project=lens-demo")
            page.locator(".runs-table .link-btn").first.click()
            expect(page).to_have_url(__import__("re").compile(r"/run\?.*selected_run"))
            page.reload()
            expect(page.locator(".run-detail-page")).to_be_visible()
            page.go_back()
            expect(page.locator(".runs-table")).to_be_visible()
            page.goto(base + "/runs?project=lens-demo&run_filter=experiment-1")
            expect(page.locator(".runs-table tbody tr")).to_have_count(1)
            page.reload()
            expect(page.locator(".runs-table tbody tr")).to_have_count(1)
            page.goto(base + "/?project=empty-demo")
            expect(page.get_by_role("heading", name="No run selected")).to_be_visible()
            page.goto(base + "/runs?project=lens-demo")
            # A real failed data request must be visible, not mistaken for empty data.
            page.route(
                "**/api/get_all_projects",
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"error":"synthetic outage"}',
                ),
            )
            page.reload()
            expect(page.get_by_role("alert")).to_contain_text("Data request failed")
            page.unroute("**/api/get_all_projects")
            page.reload()
            expect(page.locator(".runs-table")).to_be_visible()
            assert not errors, errors
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(
                page.get_by_role("button", name="Sign in", exact=True)
            ).to_be_visible()
            page.go_back()
            expect(
                page.get_by_role("button", name="Sign in", exact=True)
            ).to_be_visible()
            assert (
                context.request.post(base + "/api/get_all_projects", data={}).status
                == 401
            )
            context.close()
        for width in (1440, 390):
            context = browser.new_context(viewport={"width": width, "height": 844})
            page = context.new_page()
            page.goto(base + "/settings")
            page.get_by_label("Username", exact=True).fill(credentials["username"])
            page.get_by_label("Password", exact=True).fill(credentials["password"])
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.locator(".account")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            old_cookie = next(
                c["value"]
                for c in context.cookies()
                if c["name"] == "trackio_lens_session"
            )
            page.get_by_label("Current password", exact=True).fill("wrong-password")
            page.get_by_label("New password or passphrase", exact=True).fill(
                "synthetic personal phrase 2026"
            )
            page.get_by_label("Repeat new password", exact=True).fill(
                "synthetic personal phrase 2026"
            )
            page.get_by_role("button", name="Save account", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text(
                "Current password is incorrect"
            )
            page.get_by_label("Current password", exact=True).fill(
                credentials["password"]
            )
            page.get_by_role("button", name="Save account", exact=True).click()
            expect(page.locator(".account").get_by_role("status")).to_contain_text(
                "Account saved"
            )
            credentials["password"] = "synthetic personal phrase 2026"
            assert context.request.get(base + "/__lens/session").ok
            assert (
                context.request.get(
                    base + "/__lens/session",
                    headers={"Cookie": "trackio_lens_session=" + old_cookie},
                ).status
                == 401
            )
            page.reload()
            expect(page.locator(".account")).to_be_visible()
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(
                page.get_by_role("button", name="Sign in", exact=True)
            ).to_be_visible()
            page.get_by_label("Username", exact=True).fill(credentials["username"])
            page.get_by_label("Password", exact=True).fill(credentials["password"])
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(
                page.get_by_role("button", name="Sign out", exact=True)
            ).to_be_visible()
            page.goto(base + "/settings")
            expect(page.locator(".account")).to_be_visible()
            context.close()
        check_accounts(browser, base, credentials, credentials_path.parent, output)
        check_run_management(browser, base, credentials, output)
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 844}, locale="zh-CN"
            )
            page = context.new_page()
            page.goto(base + "/runs?project=lens-demo")
            page.get_by_label("用户名", exact=True).fill(credentials["username"])
            page.get_by_label("密码", exact=True).fill(credentials["password"])
            page.get_by_role("button", name="登录", exact=True).click()
            expect(page.locator(".runs-table")).to_be_visible()
            expect(page.get_by_role("button", name="指标", exact=True)).to_be_visible()
            expect(page.locator(".runs-table")).to_contain_text(
                "experiment-0-long-name-learning-rate-comparison"
            )
            for route, selector in (
                ("/", ".plot-container"),
                ("/reports", ".report-card"),
                ("/media", ".media-page"),
                ("/files", ".file-list"),
                ("/settings", ".account"),
            ):
                page.goto(base + route + "?project=lens-demo")
                expect(page.locator(selector).first).to_be_visible(timeout=15000)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                ), ("zh-CN", width, route)
                if route == "/settings":
                    expect(page.get_by_role("button", name="保存账户")).to_be_visible()
                    page.locator("#lens-language").select_option("en")
                    expect(
                        page.get_by_role("button", name="Save account")
                    ).to_be_visible()
                    page.reload()
                    expect(
                        page.get_by_role("button", name="Save account")
                    ).to_be_visible()
                    page.locator("#lens-language").select_option("zh-CN")
                    page.reload()
                    expect(page.get_by_role("button", name="保存账户")).to_be_visible()
                if route == "/reports":
                    expect(page.locator(".report-card").first).to_contain_text(
                        "Synthetic evaluation report"
                    )
                page.screenshot(
                    path=str(output / f"zh-{width}-{route.strip('/') or 'metrics'}.png")
                )
            context.close()
        browser.close()
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        f"Browser flows passed: {len(results)} route/viewport combinations, login failure/success/logout, deep links and reload, media and file reads, administrator run rename/delete."
    )


def check_run_management(browser, base, owner, output):
    """Exercise real backend mutations on separate synthetic projects only."""
    for width, language in ((1440, "en"), (390, "zh-CN")):
        chinese = language == "zh-CN"
        context = browser.new_context(
            viewport={"width": width, "height": 844},
            locale=language,
            is_mobile=width < 800,
            has_touch=width < 800,
        )
        page = context.new_page()
        page.goto(base + "/runs")
        page.get_by_label("用户名" if chinese else "Username", exact=True).fill(
            owner["username"]
        )
        page.get_by_label("密码" if chinese else "Password", exact=True).fill(
            owner["password"]
        )
        page.get_by_role(
            "button", name="登录" if chinese else "Sign in", exact=True
        ).click()
        expect(
            page.get_by_role(
                "button", name="退出登录" if chinese else "Sign out", exact=True
            )
        ).to_be_visible()
        session = context.request.get(base + "/__lens/session").json()
        headers = {"X-Trackio-Lens-CSRF": session["csrf"]}

        def api(name, params):
            response = context.request.post(
                base + "/api/" + name, headers=headers, data=params
            )
            assert response.ok, (name, response.status)
            result = response.json()
            assert "error" not in result, name
            return result["data"]

        assert api("get_run_mutation_status", {}) == {
            "spaces": False,
            "allowed": True,
            "auth": "admin",
        }
        project = f"lens-mutation-demo-{width}"
        names = ("rename-me", "delete-me", "batch-me", "keep-me")
        for name in names:
            api(
                "log",
                {
                    "project": project,
                    "run": name,
                    "metrics": {"synthetic/loss": 0.25},
                    "step": 0,
                    "hf_token": None,
                },
            )

        calls = []

        def observe(request):
            if request.url.endswith(("/api/delete_run", "/api/rename_run")):
                assert "x-trackio-write-token" not in request.headers
                assert "x-trackio-lens-csrf" in request.headers
                calls.append(request.url.rsplit("/", 1)[-1])

        page.on("request", observe)
        page.goto(base + "/runs?project=" + project)
        rows = page.locator(".runs-table tbody tr")
        expect(rows).to_have_count(4)

        def row(name):
            return rows.filter(has=page.get_by_role("button", name=name, exact=True))

        rename = row("rename-me")
        rename.get_by_title("重命名" if chinese else "Rename", exact=True).click()
        page.locator(".rename-input").fill("renamed-run")
        page.locator(".rename-input").press("Enter")
        expect(row("renamed-run")).to_have_count(1)
        expect(page.locator(".runs-page [role='alert']")).to_have_count(0)
        page.reload()
        expect(row("renamed-run")).to_have_count(1)

        def confirmation(dialog, targets, accept):
            assert project in dialog.message
            assert all(name in dialog.message for name in targets)
            assert ("无法撤销" if chinese else "cannot be undone") in dialog.message
            dialog.accept() if accept else dialog.dismiss()

        page.once("dialog", lambda dialog: confirmation(dialog, ["delete-me"], False))
        row("delete-me").get_by_title(
            "删除" if chinese else "Delete", exact=True
        ).click()
        expect(row("delete-me")).to_have_count(1)
        assert "delete_run" not in calls
        page.once("dialog", lambda dialog: confirmation(dialog, ["delete-me"], True))
        row("delete-me").get_by_title(
            "删除" if chinese else "Delete", exact=True
        ).click()
        expect(rows).to_have_count(3)
        targets = ["renamed-run", "batch-me"]
        for name in targets:
            row(name).get_by_role("checkbox").check()
        page.once("dialog", lambda dialog: confirmation(dialog, targets, True))
        page.locator(".bulk-delete").click()
        expect(rows).to_have_count(1)
        expect(row("keep-me")).to_be_visible()
        expect(page.locator(".runs-page [role='alert']")).to_have_count(0)
        page.reload()
        expect(rows).to_have_count(1)
        remaining = api("get_runs_for_project", {"project": project})
        assert [run["name"] for run in remaining] == ["keep-me"]
        logs = api("get_logs", {"project": project, "run": "keep-me"})
        assert len(logs) == 1 and logs[0]["synthetic/loss"] == 0.25
        assert calls.count("delete_run") == 3 and "rename_run" in calls
        assert all(
            cookie["name"] != "trackio_write_token" for cookie in context.cookies()
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / f"{width}-administrator-runs.png"))
        context.close()


def check_accounts(browser, base, owner, state, output):
    """Real browser roles, bootstrap, scoped revocation and hostile API requests."""

    def sign_in(page, username, password):
        expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()

    for width in (1440, 390):
        admin = browser.new_context(viewport={"width": width, "height": 844})
        reader = browser.new_context(
            viewport={"width": width, "height": 844},
            is_mobile=width < 800,
            has_touch=width < 800,
        )
        page, view = admin.new_page(), reader.new_page()
        page.goto(base + "/settings")
        sign_in(page, owner["username"], owner["password"])
        users = page.locator(".users")
        expect(users).to_be_visible()
        account = page.locator(".account")
        new_password = account.get_by_label("New password or passphrase", exact=True)
        assert new_password.get_attribute("minlength") is None
        assert new_password.get_attribute("maxlength") is None
        password = "p" if width == 1440 else "密码" * 150
        account.get_by_label("Current password", exact=True).fill(owner["password"])
        new_password.fill(password)
        account.get_by_label("Repeat new password", exact=True).fill(password)
        account.get_by_role("button", name="Save account", exact=True).click()
        expect(account.get_by_role("status")).to_contain_text("Account saved")
        owner["password"] = password
        page.get_by_role("button", name="Sign out", exact=True).click()
        sign_in(page, owner["username"], password)
        expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible()
        page.goto(base + "/settings")
        expect(users).to_be_visible()
        # Only rename: omit the new password and prove the login password survives.
        renamed = "owner-" + str(width)
        account.get_by_label("Username", exact=True).fill(renamed)
        account.get_by_label("Current password", exact=True).fill(owner["password"])
        account.get_by_role("button", name="Save account", exact=True).click()
        expect(account.get_by_role("status")).to_contain_text("Account saved")
        owner["username"] = renamed
        username = "reader-" + str(width)
        viewer_temporary = "v" if width == 1440 else "初始" * 150
        viewer_personal = "x" if width == 1440 else "个人" * 150
        viewer_reset = "r" if width == 1440 else "重置" * 150
        users.get_by_label("Administrator current password").fill(owner["password"])
        users.get_by_label("New username", exact=True).fill(username)
        temporary_field = users.get_by_label("Temporary password", exact=True)
        assert temporary_field.get_attribute("minlength") is None
        assert temporary_field.get_attribute("maxlength") is None
        temporary_field.fill(viewer_temporary)
        users.get_by_role("button", name="Create viewer", exact=True).click()
        expect(users.get_by_role("status")).to_contain_text("Account saved")
        view.goto(base + "/files?project=lens-demo")
        sign_in(view, username, viewer_temporary)
        expect(view.locator(".setup")).to_be_visible()
        assert view.get_by_label("Username", exact=True).evaluate("e => e.readOnly")
        viewer_password = view.get_by_label("New password or passphrase", exact=True)
        assert viewer_password.get_attribute("minlength") is None
        assert viewer_password.get_attribute("maxlength") is None
        view.get_by_label("Current password", exact=True).fill(viewer_temporary)
        viewer_password.fill(viewer_personal)
        view.get_by_label("Repeat new password", exact=True).fill(viewer_personal)
        view.screenshot(path=str(output / f"{width}-viewer-first-setup.png"))
        view.get_by_role("button", name="Save account", exact=True).click()
        expect(view.locator(".files-page")).to_be_visible()
        for route, selector in (
            ("/runs", ".runs-table"),
            ("/", ".plot-container"),
            ("/reports", ".report-card"),
            ("/media", ".media-page img"),
            ("/files", ".file-list"),
        ):
            view.goto(base + route + "?project=lens-demo")
            expect(view.locator(selector).first).to_be_visible(timeout=15000)
            if route == "/runs":
                expect(view.locator(".delete-btn").first).to_be_disabled()
                expect(
                    view.get_by_title(
                        "Administrator access is required to rename runs"
                    ).first
                ).to_be_disabled()
            view.reload()
            expect(view.locator(selector).first).to_be_visible(timeout=15000)
            assert view.evaluate("document.documentElement.scrollWidth <= innerWidth")
        view.goto(base + "/settings")
        expect(view.locator(".account")).to_be_visible()
        assert (
            view.locator(".users").count() == 0
            and view.locator(".updates").count() == 0
        )
        session = reader.request.get(base + "/__lens/session").json()
        headers = {"X-Trackio-Lens-CSRF": session["csrf"]}
        status = reader.request.post(
            base + "/api/get_run_mutation_status",
            headers={
                **headers,
                "X-Trackio-Write-Token": (state / "write-token").read_text().strip(),
            },
            data={},
        )
        assert status.ok and status.json()["data"]["allowed"] is False
        for path in ("/__lens/users", "/__lens/updates/apply"):
            assert (
                reader.request.post(base + path, headers=headers, data={}).status == 403
            )
        assert (
            reader.request.post(
                base + "/api/delete_run",
                headers={
                    **headers,
                    "X-Trackio-Write-Token": (state / "write-token")
                    .read_text()
                    .strip(),
                },
                data={
                    "project": "lens-demo",
                    "run": "experiment-0-long-name-learning-rate-comparison",
                },
            ).status
            == 403
        )
        assert reader.request.post(
            base + "/api/query_project",
            headers=headers,
            data={"project": "lens-demo", "query": "SELECT 1 AS proof"},
        ).ok
        assert not reader.request.post(
            base + "/api/query_project",
            headers=headers,
            data={"project": "lens-demo", "query": "DELETE FROM runs"},
        ).ok
        row = users.locator("li").filter(has_text=username)
        users.get_by_label("Administrator current password").fill(owner["password"])
        row.get_by_role("button", name="Disable account", exact=True).click()
        expect(row).to_contain_text("Disabled")
        assert reader.request.get(base + "/__lens/session").status == 401
        users.get_by_label("Administrator current password").fill(owner["password"])
        row.get_by_role("button", name="Enable account", exact=True).click()
        expect(row).to_contain_text("Enabled")
        users.get_by_label("Administrator current password").fill(owner["password"])
        row.get_by_role("button", name="Reset password", exact=True).click()
        expect(row).to_contain_text("Reset password for " + username)
        reset_field = row.get_by_label("New temporary password")
        assert reset_field.get_attribute("minlength") is None
        assert reset_field.get_attribute("maxlength") is None
        reset_field.fill(viewer_reset)
        row.get_by_role("button", name="Reset viewer password", exact=True).click()
        expect(users.get_by_role("status")).to_contain_text("Account saved")
        view.reload()
        expect(view.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
        sign_in(view, username, viewer_reset)
        expect(view.locator(".setup")).to_be_visible()
        assert (
            users.locator("li")
            .filter(has_text=owner["username"])
            .get_by_role("button", name="Delete account", exact=True)
            .count()
            == 0
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / f"{width}-account-management.png"))
        users.get_by_label("Administrator current password").fill(owner["password"])

        def cancel_deletion(dialog):
            assert (
                username in dialog.message
                and "Experiment data will be kept" in dialog.message
            )
            dialog.dismiss()

        page.once("dialog", cancel_deletion)
        row.get_by_role("button", name="Delete account", exact=True).click()
        expect(row).to_be_visible()
        assert reader.request.get(base + "/__lens/session").status == 200
        page.once("dialog", lambda dialog: dialog.accept())
        row.get_by_role("button", name="Delete account", exact=True).click()
        expect(row).to_have_count(0)
        expect(users.get_by_role("status")).to_contain_text("Viewer deleted")
        assert reader.request.get(base + "/__lens/session").status == 401
        view.reload()
        expect(view.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
        sign_in(view, username, viewer_reset)
        expect(view.locator('[role="alert"]')).to_contain_text(
            "Invalid username or password"
        )
        page.reload()
        expect(users).to_be_visible()
        expect(row).to_have_count(0)
        reader.close()
        admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    check(args.base, args.credentials, args.output, args.strict)
