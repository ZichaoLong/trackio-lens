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
