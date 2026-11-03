import hashlib
import json

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from trackio_lens.app import LensApp
from trackio_lens.auth import initialize
from trackio_lens.config import Config


@pytest.fixture
def instance(tmp_path):
    state, data, frontend = (tmp_path / part for part in ("state", "data", "frontend"))
    state.mkdir(mode=0o700)
    data.mkdir(mode=0o700)
    frontend.mkdir()
    initialize(state, "owner", "synthetic administrator password")
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
    credentials = {"username": "owner", "password": "synthetic administrator password"}
    credentials.update(json.loads((state / "api-access.json").read_text()))
    return app, credentials
