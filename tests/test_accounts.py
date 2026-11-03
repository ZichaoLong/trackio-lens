import json
import time

import pytest
from starlette.testclient import TestClient
from test_auth import login

from trackio_lens.auth import COOKIE, Auth, digest
from trackio_lens.config import private_json


def create_viewer(client, csrf, owner, username="reader"):
    response = client.post(
        "/__lens/users",
        headers=csrf,
        json={
            "action": "create",
            "username": username,
            "password": "temporary viewer password",
            "current_password": owner["password"],
            "role": "admin",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == "viewer"
    return response.json()["user"]


def setup_viewer(client):
    credentials = {"username": "reader", "password": "temporary viewer password"}
    csrf = login(client, credentials)
    response = client.post(
        "/__lens/account",
        headers=csrf,
        json={
            "current_password": credentials["password"],
            "password": "personal viewer password",
        },
    )
    assert response.status_code == 200
    assert response.json()["role"] == "viewer" and not response.json()["needs_setup"]
    return {"X-Trackio-Lens-CSRF": response.json()["csrf"]}


def test_bootstrap_cannot_read_or_manage_until_personal_setup(instance):
    app, owner = instance
    value = app.auth.credentials()
    value["needs_setup"] = True
    private_json(app.auth.credentials_path, value)
    private_json(app.config.state_dir / "initial-access.json", owner)
    with TestClient(app) as client:
        csrf = login(client, owner)
        for path in (
            "/api/get_all_projects",
            "/__lens/users",
            "/__lens/updates/check",
            "/api/upload",
        ):
            assert client.post(path, headers=csrf, json={}).status_code == 403
        for path in (
            "/version",
            "/file?path=/etc/passwd",
            "/artifact_blob/project/abc",
            "/static/trackio/logo.png",
        ):
            assert client.get(path).status_code == 403
        assert client.get("/settings").status_code == 200
        assert client.get("/assets/app-test.js").status_code == 200
        assert (
            client.get(
                "/runs", headers={"Accept": "text/html"}, follow_redirects=False
            ).headers["location"]
            == "/settings"
        )
        assert (
            client.post(
                "/__lens/account",
                headers=csrf,
                json={"username": "new-owner", "current_password": owner["password"]},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/__lens/account",
                headers=csrf,
                json={
                    "username": "new-owner",
                    "password": owner["password"],
                    "current_password": owner["password"],
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/__lens/account",
                headers=csrf,
                json={
                    "username": owner["username"],
                    "password": "new personal owner password",
                    "current_password": owner["password"],
                },
            ).status_code
            == 400
        )
        response = client.post(
            "/__lens/account",
            headers=csrf,
            json={
                "username": "new-owner",
                "password": "new personal owner password",
                "current_password": owner["password"],
            },
        )
        assert response.status_code == 200 and not response.json()["needs_setup"]
        assert not (app.config.state_dir / "initial-access.json").exists()
        assert (
            client.post(
                "/api/get_all_projects",
                headers={"X-Trackio-Lens-CSRF": response.json()["csrf"]},
            ).status_code
            == 200
        )


def test_viewer_read_only_own_password_and_unknown_api_boundary(instance):
    app, owner = instance
    with TestClient(app) as admin, TestClient(app) as viewer:
        admin_csrf = login(admin, owner)
        create_viewer(admin, admin_csrf, owner)
        viewer_csrf = login(
            viewer, {"username": "reader", "password": "temporary viewer password"}
        )
        assert (
            viewer.post("/api/get_all_projects", headers=viewer_csrf).status_code == 403
        )
        viewer_csrf = setup_viewer(viewer)
        for path in (
            "/runs",
            "/reports",
            "/file?path=public",
            "/artifact_blob/project/abc",
        ):
            assert viewer.get(path).status_code == 200
        assert (
            viewer.post("/api/get_all_projects", headers=viewer_csrf).status_code == 200
        )
        for path in (
            "/__lens/users",
            "/__lens/updates",
            "/__lens/updates/check",
            "/__lens/updates/apply",
            "/__lens/updates/repository",
            "/__lens/updates/recover",
        ):
            assert viewer.get(path).status_code == 403
            assert viewer.post(path, headers=viewer_csrf, json={}).status_code == 403
        for api in ("log", "upload", "delete_run", "unknown_future_operation"):
            assert (
                viewer.post(
                    "/api/" + api,
                    headers={**viewer_csrf, "X-Trackio-Write-Token": "write-secret"},
                    json={},
                ).status_code
                == 403
            )
        assert (
            admin.post("/api/unknown_future_operation", headers=admin_csrf).status_code
            == 403
        )
        assert (
            viewer.post(
                "/__lens/account",
                headers=viewer_csrf,
                json={
                    "username": "owner",
                    "current_password": "personal viewer password",
                    "password": "another viewer password",
                },
            ).status_code
            == 403
        )
        response = viewer.post(
            "/__lens/account",
            headers=viewer_csrf,
            json={
                "user_id": "owner",
                "role": "admin",
                "current_password": "personal viewer password",
                "password": "another viewer password",
            },
        )
        assert response.status_code == 200 and response.json()["role"] == "viewer"
        assert app.auth.check_password(owner["username"], owner["password"])
        assert admin.get("/__lens/session").status_code == 200
        assert viewer.get("/__lens/users").status_code == 403
        assert "password_hash" not in admin.get("/__lens/users").text
        assert "api_token" not in admin.get("/__lens/users").text


def test_account_disable_reset_and_rename_are_scoped(instance):
    app, owner = instance
    with TestClient(app) as admin, TestClient(app) as viewer, TestClient(app) as other:
        admin_csrf = login(admin, owner)
        record = create_viewer(admin, admin_csrf, owner)
        setup_viewer(viewer)
        viewer_cookie = viewer.cookies.get(COOKIE)
        login(other, owner)
        response = admin.post(
            "/__lens/account",
            headers=admin_csrf,
            json={"username": "my-name", "current_password": owner["password"]},
        )
        assert response.status_code == 200
        assert app.auth.check_password("my-name", owner["password"])
        assert other.get("/__lens/session").status_code == 401
        assert viewer.get("/__lens/session").status_code == 200
        admin_csrf = {"X-Trackio-Lens-CSRF": response.json()["csrf"]}
        assert (
            admin.post(
                "/__lens/users",
                headers=admin_csrf,
                json={
                    "action": "create",
                    "username": "READER",
                    "password": "valid synthetic password",
                    "current_password": owner["password"],
                },
            ).status_code
            == 400
        )
        for enabled in (False, True):
            response = admin.post(
                "/__lens/users",
                headers=admin_csrf,
                json={
                    "action": "set-enabled",
                    "user_id": record["user_id"],
                    "enabled": enabled,
                    "current_password": owner["password"],
                },
            )
            assert response.status_code == 200
            assert viewer.get("/__lens/session").status_code == 401
        viewer_csrf = login(
            viewer, {"username": "reader", "password": "personal viewer password"}
        )
        response = admin.post(
            "/__lens/users",
            headers=admin_csrf,
            json={
                "action": "reset-password",
                "user_id": record["user_id"],
                "password": "reset temporary password",
                "current_password": owner["password"],
            },
        )
        assert response.status_code == 200
        assert (
            viewer.post("/api/get_all_projects", headers=viewer_csrf).status_code == 401
        )
        assert not app.auth.session(viewer_cookie)
        login(viewer, {"username": "reader", "password": "reset temporary password"})
        assert viewer.get("/__lens/session").json()["needs_setup"]
        # Browser identity, not a body parameter, determines whose sessions to revoke.
        response = admin.post(
            "/__lens/account/revoke",
            headers=admin_csrf,
            json={"current_password": owner["password"], "user_id": record["user_id"]},
        )
        assert response.status_code == 200
        assert viewer.get("/__lens/session").status_code == 200


def test_old_sessions_never_become_viewer_or_admin_sessions(instance):
    app, owner = instance
    with app.auth.connect() as db:
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?)",
            (digest("old-cookie"), "csrf", time.time(), time.time() + 60),
        )
    assert app.auth.session("old-cookie") is None
    cookie, _, _ = app.auth.login(owner["username"], owner["password"])
    assert Auth(app.config.state_dir, 3600).session(cookie)["role"] == "admin"
    with app.auth.connect() as db:
        assert not db.execute(
            "SELECT * FROM sessions WHERE id = ?", (digest(cookie),)
        ).fetchone()


def test_missing_admin_refuses_startup_and_program_token_cannot_manage_users(
    instance, tmp_path
):
    app, owner = instance
    uninitialized = tmp_path / "uninitialized"
    uninitialized.mkdir(mode=0o700)
    with pytest.raises(FileNotFoundError):
        Auth(uninitialized, 3600)
    with TestClient(app) as client:
        csrf = login(client, owner)
        program = {**csrf, "X-Trackio-Lens-Token": owner["api_token"]}
        assert client.get("/__lens/users", headers=program).status_code == 403
        assert client.post("/__lens/users", headers=program, json={}).status_code == 403
    serialized = json.dumps(app.auth.list_users())
    assert owner["password"] not in serialized


def test_authentication_limits_count_failures_per_account(instance):
    app, owner = instance
    with TestClient(app) as client:
        # Successful activity must not exhaust the failure budget.
        for _ in range(22):
            login(client, owner)
        assert not app.auth.attempts
        for _ in range(20):
            response = client.post(
                "/__lens/login",
                headers={"X-Lens-Login": "1"},
                json={**owner, "password": "wrong"},
            )
            assert response.status_code == 401
        assert (
            client.post(
                "/__lens/login", headers={"X-Lens-Login": "1"}, json=owner
            ).status_code
            == 429
        )
        assert app.auth.rate_limited(owner["username"].upper())
        assert not app.auth.rate_limited("another-account")
