"""One ASGI process and one guarded boundary for every Trackio resource."""

import hmac
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from .auth import COOKIE, CSRF_HEADER, TOKEN_HEADER, Auth
from .config import Config, private_path
from .upstream import build_backend, read_build


class LensApp:
    def __init__(self, config: Config, backend=None):
        self.config = config
        self.build = read_build(config.frontend_dir)
        self.auth = Auth(config.state_dir, config.session_ttl_seconds)
        self.backend, self.write_apis, self.write_token = backend or build_backend(
            config, self.build
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.backend(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        request = Request(scope, receive)

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower()
                    not in {b"cache-control", b"x-frame-options", b"referrer-policy"}
                ]
                cache = (
                    b"private, max-age=31536000, immutable"
                    if request.url.path.startswith("/assets/")
                    and message["status"] == 200
                    else b"no-store"
                )
                headers.extend(
                    [
                        (b"cache-control", cache),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"same-origin"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        response = await self.route(request)
        if response is None:
            await self.backend(scope, receive, guarded_send)
        else:
            await response(scope, receive, guarded_send)

    def same_origin(self, request):
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site":
            return False
        if origin:
            parsed = urlsplit(origin)
            return parsed.scheme in {
                "http",
                "https",
            } and parsed.netloc == request.headers.get("host")
        return True

    async def json_body(self, request, limit=8192):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError("Request too large")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    def session_response(self, session):
        token, csrf, expires = session
        response = JSONResponse(
            {"csrf": csrf, "expires": expires, **self.auth.account()}
        )
        response.set_cookie(
            COOKIE,
            token,
            max_age=self.config.session_ttl_seconds,
            httponly=True,
            secure=self.config.cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    async def route(self, request):
        path = request.url.path
        if path == "/healthz" and request.method in {"GET", "HEAD"}:
            return JSONResponse({"status": "ok"})
        if path == "/__lens/login":
            if request.method == "GET":
                translations = self.config.frontend_dir / "lens-locales.json"
                dictionary = (
                    json.loads(translations.read_text())
                    if translations.exists()
                    else {}
                )
                page = (Path(__file__).parent / "login.html").read_text()
                return HTMLResponse(
                    page.replace(
                        "__LENS_TRANSLATIONS__",
                        json.dumps(dictionary, ensure_ascii=False).replace(
                            "<", "\\u003c"
                        ),
                    )
                )
            if request.method != "POST":
                return JSONResponse({"error": "Method not allowed"}, 405)
            if (
                not self.same_origin(request)
                or request.headers.get("x-lens-login") != "1"
            ):
                return JSONResponse({"error": "Invalid request origin"}, 403)
            if self.auth.rate_limited():
                return JSONResponse(
                    {"error": "Too many attempts. Try again in five minutes."}, 429
                )
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 4096:
                    return JSONResponse({"error": "Request too large"}, 413)
            try:
                data = json.loads(body)
                username, password = data["username"], data["password"]
                if not isinstance(username, str) or not isinstance(password, str):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                return JSONResponse({"error": "Invalid credentials"}, 400)
            session = await run_in_threadpool(self.auth.login, username, password)
            if not session:
                return JSONResponse({"error": "Invalid username or password"}, 401)
            return self.session_response(session)

        program = self.auth.check_token(request.headers.get(TOKEN_HEADER, ""))
        session_token = request.cookies.get(COOKIE, "")
        session = self.auth.session(session_token)
        if not program and not session:
            if (
                request.method == "GET"
                and "text/html" in request.headers.get("accept", "")
                and path not in {"/api", "/file", "/version"}
                and not path.startswith(
                    ("/api/", "/artifact_blob/", "/__lens", "/assets/", "/static/")
                )
            ):
                target = path + ("?" + request.url.query if request.url.query else "")
                return RedirectResponse(
                    "/__lens/login?next=" + quote(target, safe=""), 303
                )
            return JSONResponse({"error": "Authentication required"}, 401)

        if request.method not in {"GET", "HEAD", "OPTIONS"} and not program:
            if not self.same_origin(request) or not hmac.compare_digest(
                request.headers.get(CSRF_HEADER, ""), session["csrf"]
            ):
                return JSONResponse({"error": "Invalid CSRF token or origin"}, 403)
        if path == "/__lens/session" and request.method == "GET":
            return JSONResponse({**(session or {}), **self.auth.account()})
        if path.startswith("/__lens/updates"):
            if program or not session:
                return JSONResponse({"error": "A browser login is required"}, 403)
            from . import updates

            management = self.config.state_dir / "management.json"
            if not management.exists():
                if path == "/__lens/updates" and request.method == "GET":
                    return JSONResponse({"available": False})
                return JSONResponse({"error": "Managed installation is required"}, 400)
            private_path(management)
            config_path = Path(json.loads(management.read_text())["config"])
            try:
                if path == "/__lens/updates" and request.method == "GET":
                    return JSONResponse(
                        {
                            **await run_in_threadpool(updates.status, config_path),
                            "running_build": self.build["source_commit"],
                        }
                    )
                if request.method != "POST":
                    return JSONResponse({"error": "Method not allowed"}, 405)
                values = await self.json_body(request)
                if path == "/__lens/updates/check":
                    result = await run_in_threadpool(updates.check, config_path)
                elif path == "/__lens/updates/apply":
                    result = await run_in_threadpool(
                        updates.start, config_path, values.get("commit")
                    )
                elif path == "/__lens/updates/recover":
                    result = await run_in_threadpool(
                        updates.start, config_path, None, "recover"
                    )
                elif path == "/__lens/updates/repository":
                    password = values.get("current_password")
                    if self.auth.rate_limited():
                        return JSONResponse(
                            {"error": "Too many attempts. Try again in five minutes."},
                            429,
                        )
                    if not isinstance(password, str) or not await run_in_threadpool(
                        self.auth.check_password,
                        self.auth.account()["username"],
                        password,
                    ):
                        return JSONResponse(
                            {"error": "Current password is incorrect"}, 403
                        )
                    result = await run_in_threadpool(
                        updates.set_repository, config_path, values.get("repository")
                    )
                else:
                    return JSONResponse({"error": "Not found"}, 404)
                return JSONResponse(result)
            except (ValueError, FileNotFoundError) as error:
                return JSONResponse({"error": str(error)}, 400)
            except Exception:
                return JSONResponse(
                    {
                        "error": "Update service is unavailable. Retry or inspect local status."
                    },
                    503,
                )
        if path in {"/__lens/account", "/__lens/account/revoke"}:
            if program or not session:
                return JSONResponse({"error": "A browser login is required"}, 403)
            if path == "/__lens/account" and request.method == "GET":
                return JSONResponse(self.auth.account())
            if request.method != "POST":
                return JSONResponse({"error": "Method not allowed"}, 405)
            if self.auth.rate_limited():
                return JSONResponse(
                    {"error": "Too many attempts. Try again in five minutes."}, 429
                )
            try:
                values = await self.json_body(request)
                current = values.get("current_password")
                if not isinstance(current, str) or not current:
                    raise ValueError("Enter your current password")
                if path.endswith("/revoke"):
                    if not await run_in_threadpool(
                        self.auth.check_password,
                        self.auth.account()["username"],
                        current,
                    ):
                        raise PermissionError("Current password is incorrect")
                    self.auth.revoke()
                    response = JSONResponse({"ok": True})
                    response.delete_cookie(COOKIE, path="/")
                    return response
                renewed = await run_in_threadpool(
                    self.auth.change_account,
                    values.get("username"),
                    values.get("password"),
                    current,
                    True,
                )
                return self.session_response(renewed)
            except PermissionError as error:
                return JSONResponse({"error": str(error)}, 403)
            except (ValueError, TypeError) as error:
                return JSONResponse({"error": str(error)}, 400)
        if path == "/__lens/logout" and request.method == "POST":
            self.auth.revoke(session_token)
            response = JSONResponse({"ok": True})
            response.delete_cookie(COOKIE, path="/")
            return response
        if path == "/__lens/build" and request.method == "GET":
            return JSONResponse(self.build)
        if path == "/__trackio/frontend_version":
            return JSONResponse({"version": self.build["source_commit"]})
        if path == "/config.json":
            return JSONResponse({"mode": "live"})
        if path.startswith("/api/") and path[5:].rstrip("/") in self.write_apis:
            if not hmac.compare_digest(
                request.headers.get("x-trackio-write-token", ""), self.write_token
            ):
                return JSONResponse(
                    {"error": "A separate Trackio write token is required"}, 403
                )
        if path.startswith(
            ("/api/", "/artifact_blob/", "/static/trackio/")
        ) or path in {"/api", "/file", "/version"}:
            return None
        if path.startswith(("/oauth", "/login", "/mcp", "/gradio_api", "/__lens")):
            return JSONResponse({"error": "Not found"}, 404)
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"error": "Method not allowed"}, 405)
        if path.startswith("/assets/"):
            relative = path.lstrip("/")
            if relative not in self.build["assets"]:
                return JSONResponse(
                    {"error": "Asset not in this build; refresh the page"}, 404
                )
            return FileResponse(self.config.frontend_dir / relative)
        return FileResponse(
            self.config.frontend_dir / "index.html", media_type="text/html"
        )
