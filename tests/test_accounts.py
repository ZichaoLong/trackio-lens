import json
import time

import pytest
from starlette.testclient import TestClient
from test_auth import login

from trackio_lens.auth import COOKIE, Auth, digest, initialize
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


@pytest.mark.parametrize("password", ["p", "密码" * 150], ids=["short", "long"])
def test_administrator_initialization_has_no_password_length_policy(tmp_path, password):
    state = tmp_path / "auth"
    initialize(state, "owner", password)
    auth = Auth(state, 3600)
    assert auth.login("owner", password)
    assert not auth.login("owner", password + "wrong")


def test_administrator_password_is_still_required(tmp_path):
    with pytest.raises(ValueError, match="Enter a password"):
        initialize(tmp_path / "auth", "owner", "")


@pytest.mark.parametrize("password", ["p", "密码" * 150], ids=["short", "long"])
def test_administrator_can_change_and_authenticate_with_any_password_length(
    instance, password
):
    app, owner = instance
    with TestClient(app) as admin:
        csrf = login(admin, owner)
        old_cookie = admin.cookies.get(COOKIE)
        response = admin.post(
            "/__lens/account",
            headers=csrf,
            json={"current_password": owner["password"], "password": password},
        )
        assert response.status_code == 200
        assert not app.auth.session(old_cookie)
        owner = {**owner, "password": password}
        admin.cookies.clear()
        csrf = login(admin, owner)
        assert admin.get("/__lens/session").json()["role"] == "admin"
        # Management's current-password verification must accept the same value.
        create_viewer(admin, csrf, owner)


@pytest.mark.parametrize("password", ["p", "密码" * 150], ids=["short", "long"])
def test_viewer_password_policy_applies_to_create_reset_and_own_change(
    instance, password
):
    app, owner = instance
    with TestClient(app) as admin, TestClient(app) as viewer:
        csrf = login(admin, owner)
        assert (
            admin.post(
                "/__lens/users",
                headers=csrf,
                json={
                    "action": "create",
                    "username": "reader",
                    "password": password,
                    "current_password": owner["password"],
                },
            ).status_code
            == 400
        )
        user = create_viewer(admin, csrf, owner)
        assert (
            admin.post(
                "/__lens/users",
                headers=csrf,
                json={
                    "action": "reset-password",
                    "user_id": user["user_id"],
                    "password": password,
                    "current_password": owner["password"],
                },
            ).status_code
            == 400
        )
        csrf = setup_viewer(viewer)
        assert (
            viewer.post(
                "/__lens/account",
                headers=csrf,
                json={
                    "current_password": "personal viewer password",
                    "password": password,
                    "role": "admin",
                },
            ).status_code
            == 400
        )


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
                "password": "p",
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


@pytest.mark.parametrize("enabled", [True, False], ids=["enabled", "disabled"])
def test_delete_viewer_revokes_sessions_and_recreation_is_a_new_identity(
    instance, enabled
):
    app, owner = instance
    with TestClient(app) as admin, TestClient(app) as viewer:
        csrf = login(admin, owner)
        record = create_viewer(admin, csrf, owner)
        setup_viewer(viewer)
        cookie = viewer.cookies.get(COOKIE)
        if not enabled:
            app.auth.manage_viewer(
                {
                    "action": "set-enabled",
                    "user_id": record["user_id"],
                    "enabled": False,
                },
                owner["password"],
            )
        response = admin.post(
            "/__lens/users",
            headers=csrf,
            json={
                "action": "delete",
                "user_id": record["user_id"],
                "current_password": owner["password"],
            },
        )
        assert response.status_code == 200
        assert response.json()["user"] == {
            "user_id": record["user_id"],
            "deleted": True,
        }
        assert record["user_id"] not in app.auth.credentials()["viewers"]
        assert viewer.get("/__lens/session").status_code == 401
        assert viewer.post("/api/get_all_projects", json={}).status_code == 401
        restarted = Auth(app.config.state_dir, 3600)
        assert not restarted.login("reader", "personal viewer password")
        assert not restarted.session(cookie)
        with app.auth.connect() as db:
            assert not db.execute(
                "SELECT 1 FROM user_sessions WHERE user_id = ?", (record["user_id"],)
            ).fetchone()
        assert admin.get("/__lens/session").status_code == 200
        assert (
            admin.post("/api/get_all_projects", headers=csrf, json={}).status_code
            == 200
        )
        replacement = create_viewer(admin, csrf, owner)
        assert replacement["user_id"] != record["user_id"]
        assert not app.auth.session(cookie)
        login(viewer, {"username": "reader", "password": "temporary viewer password"})
        assert viewer.get("/__lens/session").json()["user_id"] == replacement["user_id"]


def test_deleting_viewer_requires_administrator_password_csrf_and_viewer_target(
    instance,
):
    app, owner = instance
    with (
        TestClient(app) as admin,
        TestClient(app) as viewer,
        TestClient(app) as anonymous,
    ):
        csrf = login(admin, owner)
        record = create_viewer(admin, csrf, owner)
        viewer_csrf = setup_viewer(viewer)
        action = {
            "action": "delete",
            "user_id": record["user_id"],
            "current_password": owner["password"],
        }
        assert anonymous.post("/__lens/users", json=action).status_code == 401
        assert (
            viewer.post("/__lens/users", headers=viewer_csrf, json=action).status_code
            == 403
        )
        assert admin.post("/__lens/users", json=action).status_code == 403
        assert (
            admin.post(
                "/__lens/users",
                headers={**csrf, "X-Trackio-Lens-Token": owner["api_token"]},
                json=action,
            ).status_code
            == 403
        )
        for invalid_password in ("", "wrong", None):
            assert (
                admin.post(
                    "/__lens/users",
                    headers=csrf,
                    json={**action, "current_password": invalid_password},
                ).status_code
                == 403
            )
        for invalid_id in ("owner", "missing", None):
            assert (
                admin.post(
                    "/__lens/users",
                    headers=csrf,
                    json={**action, "user_id": invalid_id},
                ).status_code
                == 400
            )
        assert viewer.get("/__lens/session").status_code == 200
        assert admin.get("/__lens/session").status_code == 200
        assert app.auth.check_password(owner["username"], owner["password"])
        assert len(app.auth.list_users()) == 2


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
