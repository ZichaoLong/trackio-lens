import json
import time

import pytest
from starlette.testclient import TestClient

from trackio_lens.app import LensApp
from trackio_lens.auth import COOKIE, initialize


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
        "/__lens/updates",
        "/__lens/updates/apply",
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
            db.execute("UPDATE user_sessions SET expires = ?", (time.time() - 1,))
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
        app.auth.attempts.extend([time.monotonic()] * 200)
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


def test_shortened_ttl_applies_to_existing_sessions(instance):
    from trackio_lens.auth import Auth

    app, _ = instance
    token, _, _ = app.auth.create_session()
    with app.auth.connect() as db:
        db.execute("UPDATE user_sessions SET created = ?", (time.time() - 10,))
    assert app.auth.session(token)
    assert Auth(app.config.state_dir, ttl=5).session(token) is None


def test_personal_account_revokes_other_devices_but_keeps_program_token(instance):
    app, credentials = instance
    old, _, _ = app.auth.create_session()
    with TestClient(app) as client:
        headers = login(client, credentials)
        values = {
            "username": "researcher",
            "current_password": credentials["password"],
            "password": "a memorable private passphrase",
        }
        assert client.post("/__lens/account", json=values).status_code == 403
        assert (
            client.post(
                "/__lens/account",
                json={**values, "current_password": "wrong"},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/__lens/account",
                json={**values, "password": ["invalid"]},
                headers=headers,
            ).status_code
            == 400
        )
        assert app.auth.session(old)
        response = client.post("/__lens/account", json=values, headers=headers)
        assert response.status_code == 200
        assert response.json()["username"] == "researcher"
        assert not response.json()["needs_setup"]
        assert client.get("/__lens/session").status_code == 200
        assert not app.auth.session(old)
        assert app.auth.check_token(credentials["api_token"])
        assert not (app.config.state_dir / "initial-access.json").exists()
        assert (
            json.loads((app.config.state_dir / "api-access.json").read_text())[
                "api_token"
            ]
            == credentials["api_token"]
        )
        assert app.auth.check_password("researcher", values["password"])
        assert not app.auth.check_password(
            credentials["username"], credentials["password"]
        )


def test_program_credentials_cannot_manage_account(instance):
    app, credentials = instance
    with TestClient(app) as client:
        program = {"X-Trackio-Lens-Token": credentials["api_token"]}
        for path in ("/__lens/account", "/__lens/account/revoke"):
            assert client.get(path, headers=program).status_code == 403
            assert client.post(path, json={}, headers=program).status_code == 403


def test_legacy_handoff_and_session_schema_remain_compatible(instance):
    from trackio_lens.auth import Auth

    app, credentials = instance
    state = app.config.state_dir
    from trackio_lens.config import private_json

    private_json(state / "initial-access.json", credentials)
    (state / "api-access.json").unlink()
    old, _, _ = app.auth.create_session()
    restarted = Auth(state, 3600)
    assert restarted.session(old)
    assert "api_token" not in json.loads((state / "initial-access.json").read_text())
    assert (
        json.loads((state / "api-access.json").read_text())["api_token"]
        == credentials["api_token"]
    )
    # The verified fallback still inserts four values without a column list.
    with restarted.connect() as db:
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?)",
            ("legacy", "csrf", time.time(), time.time() + 60),
        )
        assert len(list(db.execute("PRAGMA table_info(sessions)"))) == 4


def test_personal_password_initialization_has_no_plaintext_password(tmp_path):
    from trackio_lens.auth import Auth

    state = tmp_path / "personal"
    initialize(state, "owner", "a personal private passphrase")
    auth = Auth(state, 3600)
    assert not (state / "initial-access.json").exists()
    assert not auth.account()["needs_setup"]
    assert auth.check_password("owner", "a personal private passphrase")
    for path in state.iterdir():
        if path.suffix == ".json":
            assert "a personal private passphrase" not in path.read_text()


def test_update_management_requires_browser_csrf_and_repository_reauthentication(
    instance, monkeypatch
):
    from trackio_lens import updates
    from trackio_lens.config import private_json
    from trackio_lens.management import register_install

    app, credentials = instance
    config = app.config.state_dir / "instance.json"
    private_json(
        config, {"state_dir": app.config.state_dir, "data_dir": app.config.data_dir}
    )
    root = app.config.state_dir / "releases"
    root.mkdir(mode=0o700)
    register_install(config, root, "lens-test.service", "/usr/bin/python3", "/usr/bin")
    calls = []
    monkeypatch.setattr(
        updates, "start", lambda *args: calls.append(args) or {"ok": True}
    )
    monkeypatch.setattr(
        updates, "set_repository", lambda *args: calls.append(args) or {"ok": True}
    )
    monkeypatch.setattr(
        updates,
        "status",
        lambda _: {"available": True, "installed_build": {"source_commit": "b" * 40}},
    )
    with TestClient(app) as client:
        token = {"X-Trackio-Lens-Token": credentials["api_token"]}
        assert (
            client.post("/__lens/updates/apply", headers=token, json={}).status_code
            == 403
        )
        csrf = login(client, credentials)
        identity = client.get("/__lens/updates").json()
        assert identity["running_build"]["source_commit"] == "a" * 40
        assert identity["installed_build"]["source_commit"] == "b" * 40
        assert client.post("/__lens/updates/apply", json={}).status_code == 403
        assert (
            client.post(
                "/__lens/updates/apply",
                json={},
                headers={**csrf, "Origin": "https://foreign.test"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/__lens/updates/apply", json={}, headers={**csrf, **token}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/__lens/updates/repository",
                json={
                    "repository": "https://github.com/example/repo.git",
                    "current_password": "wrong",
                },
                headers=csrf,
            ).status_code
            == 403
        )
        assert not calls
        assert (
            client.post(
                "/__lens/updates/apply", json={"commit": "a" * 40}, headers=csrf
            ).status_code
            == 200
        )
        assert calls[-1][1] == "a" * 40
        assert (
            client.post(
                "/__lens/updates/repository",
                json={
                    "repository": "https://github.com/example/repo.git",
                    "current_password": credentials["password"],
                },
                headers=csrf,
            ).status_code
            == 200
        )
