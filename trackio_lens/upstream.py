"""The only backend coupling: official ASGI factory and its write API registry."""

import hmac
import importlib.metadata
import json
import os

from .config import Config, private_path

# Reviewed read operations for the pinned official backend. Unknown new APIs
# stay closed until explicitly classified during an upstream adaptation.
READ_APIS = frozenset(
    {
        "get_run_mutation_status",
        "check_artifact_blobs",
        "get_artifact_manifest",
        "get_artifacts",
        "list_artifacts",
        "get_run_artifacts",
        "get_run_artifact_counts",
        "get_artifact_consumers",
        "get_artifact_lineage",
        "get_alerts",
        "get_metric_values",
        "get_runs_for_project",
        "get_run_configs",
        "get_metrics_for_run",
        "get_all_projects",
        "get_project_summary",
        "get_run_summary",
        "get_console_output",
        "get_system_metrics_for_run",
        "get_system_logs",
        "get_system_logs_batch",
        "get_snapshot",
        "get_logs",
        "get_logs_batch",
        "get_traces",
        "get_trace_steps",
        "query_project",
        "get_settings",
        "get_registry_buckets",
        "get_registries",
        "get_registry_details",
        "get_project_files",
        "get_tab_availability",
    }
)


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
        allowed = request.scope.get("lens_role") != "viewer" and hmac.compare_digest(
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
