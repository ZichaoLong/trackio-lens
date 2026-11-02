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
            expect(page.locator(".files-page")).to_be_visible()
            assert page.url.endswith("/files?project=lens-demo")
            for route, selector in (
                ("/", ".plot-container"),
                ("/runs", ".runs-table"),
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
                    page.locator(".file-name").first.click()
                    expect(page.locator(".preview-code")).to_contain_text("synthetic")
                    response = context.request.get(
                        base + page.locator(".download-btn").first.get_attribute("href")
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
            assert not errors, errors
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(
                page.get_by_role("button", name="Sign in", exact=True)
            ).to_be_visible()
            assert (
                context.request.post(base + "/api/get_all_projects", data={}).status
                == 401
            )
            context.close()
        browser.close()
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        f"Browser flows passed: {len(results)} route/viewport combinations, login failure/success/logout, deep links and reload, media and file reads."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    check(args.base, args.credentials, args.output, args.strict)
