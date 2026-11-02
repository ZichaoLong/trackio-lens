import hashlib
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from trackio_lens.app import LensApp
from trackio_lens.auth import COOKIE, initialize
from trackio_lens.config import Config


@pytest.fixture
def instance(tmp_path):
    state, data, frontend = (tmp_path / part for part in ("state", "data", "frontend"))
    state.mkdir(mode=0o700)
    data.mkdir(mode=0o700)
    frontend.mkdir()
    initialize(state)
    (frontend / "index.html").write_text("<!doctype html><p>Complete frontend</p>")
    (frontend / "assets").mkdir()
    (frontend / "assets/app-test.js").write_text("console.log('compiled');")
    assets = {
        str(p.relative_to(frontend)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in frontend.rglob("*")
        if p.is_file()
    }
    (frontend / "lens-build.json").write_text(
        json.dumps(
            {"source_commit": "a" * 40, "backend_version": "0.44.0", "assets": assets}
        )
    )
    config = Config(state, data, frontend)

    async def data_route(request):
        return JSONResponse({"data": "protected"})

    backend = Starlette(
        routes=[Route("/{path:path}", data_route, methods=["GET", "POST", "DELETE"])]
    )
    app = LensApp(config, (backend, {"log", "delete_run", "upload"}, "write-secret"))
    credentials = json.loads((state / "initial-access.json").read_text())
    return app, credentials


def login(client, credentials):
    response = client.post(
        "/__lens/login", json=credentials, headers={"X-Lens-Login": "1"}
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    return {"X-Trackio-Lens-CSRF": response.json()["csrf"]}


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/runs?project=private",
        "/api/get_all_projects",
        "/file?path=/etc/passwd",
        "/artifact_blob/project/abc",
        "/version",
        "/assets/app-test.js",
        "/static/trackio/logo.png",
        "/gradio_api/call/get_all_projects",
        "/mcp",
        "/__trackio/frontend_version",
        "/__lens/build",
        "/%61pi/get_all_projects",
    ],
)
def test_all_data_requires_authentication(instance, path):
    app, _ = instance
    with TestClient(app) as client:
        for method in (client.get, client.post):
            response = method(
                path,
                headers={"X-Forwarded-For": "127.0.0.1", "X-Forwarded-User": "admin"},
            )
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"


def test_login_logout_expiry_and_restart(instance):
    app, credentials = instance
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/__lens/login").status_code == 200
        bad = {**credentials, "password": "wrong"}
        assert (
            client.post(
                "/__lens/login", json=bad, headers={"X-Lens-Login": "1"}
            ).status_code
            == 401
        )
        headers = login(client, credentials)
        cookie = client.cookies.get(COOKIE)
        assert client.post("/api/get_all_projects", headers=headers).status_code == 200
        restarted = LensApp(app.config, (app.backend, app.write_apis, app.write_token))
        assert restarted.auth.session(cookie)
        assert client.post("/__lens/logout", headers=headers).status_code == 200
        assert not restarted.auth.session(cookie)
        client.cookies.clear()
        client.cookies.set(COOKIE, cookie)
        assert client.get("/version").status_code == 401
        headers = login(client, credentials)
        with app.auth.connect() as db:
            db.execute("UPDATE sessions SET expires = ?", (time.time() - 1,))
        assert client.get("/__lens/session").status_code == 401


def test_csrf_program_and_write_boundaries(instance):
    app, credentials = instance
    with TestClient(app) as client:
        assert client.post("/__lens/login", json=credentials).status_code == 403
        assert (
            client.post(
                "/__lens/login",
                json=credentials,
                headers={"X-Lens-Login": "1", "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        headers = login(client, credentials)
        assert client.post("/api/get_all_projects").status_code == 403
        assert (
            client.post(
                "/api/get_all_projects",
                headers={**headers, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/get_all_projects",
                headers={**headers, "Origin": "http://testserver"},
            ).status_code
            == 200
        )
        for api in ("log", "delete_run", "upload"):
            assert client.post("/api/" + api, headers=headers).status_code == 403
        client.cookies.clear()
        assert (
            client.post(
                "/api/get_all_projects",
                headers={"X-Trackio-Write-Token": "write-secret"},
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/version", headers={"X-Trackio-Lens-Token": "wrong"}
            ).status_code
            == 401
        )
        program = {"X-Trackio-Lens-Token": credentials["api_token"]}
        assert client.get("/version", headers=program).status_code == 200
        assert client.post("/api/get_all_projects", headers=program).status_code == 200
        assert client.post("/api/log", headers=program).status_code == 403
        assert (
            client.post(
                "/api/log", headers={**program, "X-Trackio-Write-Token": "write-secret"}
            ).status_code
            == 200
        )


def test_cache_assets_revocation_and_fail_closed_build(instance):
    app, credentials = instance
    with TestClient(app) as client:
        response = client.get(
            "/files?project=example",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/__lens/login?next=")
        login(client, credentials)
        assert "Complete frontend" in client.get("/files?project=example").text
        assert client.get("/runs").headers["cache-control"] == "no-store"
        assert "immutable" in client.get("/assets/app-test.js").headers["cache-control"]
        assert client.get("/assets/removed-build.js").status_code == 404
        assert (
            client.get("/assets/../../state/credentials.json").status_code != 200
            or "password_hash"
            not in client.get("/assets/../../state/credentials.json").text
        )
        app.auth.revoke()
        assert client.get("/version").status_code == 401
    (app.config.frontend_dir / "assets/app-test.js").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        LensApp(app.config, (app.backend, app.write_apis, app.write_token))


def test_login_rate_limit_and_file_permissions(instance):
    app, credentials = instance
    with TestClient(app) as client:
        app.auth.attempts.extend([time.monotonic()] * 20)
        assert (
            client.post(
                "/__lens/login", json=credentials, headers={"X-Lens-Login": "1"}
            ).status_code
            == 429
        )
    for file in app.config.state_dir.iterdir():
        assert file.stat().st_mode & 0o077 == 0
    app.auth.credentials_path.chmod(0o644)
    with pytest.raises(ValueError, match="mode 600"):
        app.auth.credentials()
