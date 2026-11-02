"""The only backend coupling: official ASGI factory and its write API registry."""

import hmac
import importlib.metadata
import json
import os

from .config import Config, private_path


def build_backend(config: Config, manifest: dict):
    expected = manifest["backend_version"]
    if importlib.metadata.version("trackio") != expected:
        raise ValueError("Frontend and Trackio backend versions differ")
    # Must be set before importing Trackio; no modification of site-packages.
    os.environ["TRACKIO_DIR"] = str(config.data_dir)
    os.environ["TRACKIO_STORAGE_MODE"] = "sqlite"
    write_file = config.state_dir / "write-token"
    private_path(write_file)
    write_token = write_file.read_text().strip()
    if not write_token:
        raise ValueError("Empty write token")
    os.environ["TRACKIO_WRITE_TOKEN"] = write_token
    from trackio.server import WRITE_APIS, build_starlette_app_only

    app, _ = build_starlette_app_only(frontend_dir=str(config.frontend_dir))

    def mutation_status(request):
        allowed = hmac.compare_digest(
            request.headers.get("x-trackio-write-token", ""), write_token
        )
        return {"spaces": False, "allowed": allowed, "auth": "write_token"}

    app.state.api_registry["get_run_mutation_status"] = mutation_status
    return app, WRITE_APIS | {"upload"}, write_token


def read_build(frontend_dir):
    import hashlib

    manifest = json.loads((frontend_dir / "lens-build.json").read_text())
    if not manifest.get("source_commit") or not manifest.get("assets"):
        raise ValueError("Incomplete frontend build")
    for name, expected in manifest["assets"].items():
        path = (frontend_dir / name).resolve()
        if (
            not path.is_relative_to(frontend_dir.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"Incomplete or altered frontend asset: {name}")
    if "index.html" not in manifest["assets"] or not any(
        p.endswith(".js") for p in manifest["assets"]
    ):
        raise ValueError("Full compiled frontend is required")
    return manifest
