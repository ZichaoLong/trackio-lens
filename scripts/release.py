"""Build committed code, test against a database copy, switch a user service.

The release root and config are instance-owned paths outside the repository.
Only the explicitly named systemd user service is ever stopped or restarted.
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup import backup  # noqa: E402

from trackio_lens.auth import COOKIE, Auth  # noqa: E402
from trackio_lens.config import Config, private_path  # noqa: E402
from trackio_lens.upstream import read_build  # noqa: E402


def run(command, *, cwd=None, log=None):
    return subprocess.run(command, cwd=cwd, check=True, stdout=log, stderr=log)


def private_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")
    path.chmod(0o600)


def probe(url, manifest, session, *, timeout=40, process=None):
    deadline = time.monotonic() + timeout
    while True:
        if process and process.poll() is not None:
            raise RuntimeError(
                "Candidate process exited; inspect the private validation log"
            )
        try:
            response = httpx.get(url + "/healthz", timeout=2, trust_env=False)
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Service health deadline exceeded")
        time.sleep(0.25)
    with httpx.Client(base_url=url, timeout=20, trust_env=False) as client:
        for path in (
            "/",
            "/api/get_all_projects",
            "/version",
            "/file?path=/etc/passwd",
            "/artifact_blob/missing/abc",
            "/gradio_api/info",
            "/__lens/build",
        ):
            assert client.get(path).status_code == 401, (
                f"Anonymous resource accessible: {path}"
            )
        assert client.post("/api/get_all_projects").status_code == 401
        assert (
            client.get(
                "/version", headers={"X-Trackio-Lens-Token": "wrong"}
            ).status_code
            == 401
        )
        token, csrf, _ = session
        client.cookies.set(COOKIE, token)
        client.headers["X-Trackio-Lens-CSRF"] = csrf
        identity = client.get("/__lens/build").json()
        assert identity["source_commit"] == manifest["source_commit"], (
            "Service loaded a different release"
        )
        assert client.get("/version").json()["version"] == manifest["backend_version"]
        index = client.get("/runs")
        assert index.status_code == 200 and index.headers["cache-control"] == "no-store"
        assert (
            hashlib.sha256(index.content).hexdigest()
            == manifest["assets"]["index.html"]
        )
        main = next(
            name
            for name in manifest["assets"]
            if name.startswith("assets/index-") and name.endswith(".js")
        )
        assert (
            hashlib.sha256(client.get("/" + main).content).hexdigest()
            == manifest["assets"][main]
        )
        response = client.post("/api/get_all_projects", json={})
        assert response.status_code == 200 and "error" not in response.json()
        projects = response.json()["data"]
        if projects:
            runs = client.post(
                "/api/get_runs_for_project", json={"project": projects[0]}
            )
            assert runs.status_code == 200 and "error" not in runs.json()
            if runs.json()["data"]:
                record = runs.json()["data"][0]
                logs = client.post(
                    "/api/get_logs",
                    json={
                        "project": projects[0],
                        "run": record["name"],
                        "run_id": record["id"],
                        "scalar_only": True,
                    },
                )
                assert logs.status_code == 200 and "error" not in logs.json()
        return {
            "health": True,
            "anonymous_denied": True,
            "wrong_token_denied": True,
            "session_valid": True,
            "authenticated_data": True,
            "frontend_asset_hash": True,
            "source_commit": identity["source_commit"],
            "backend_version": identity["backend_version"],
        }


def check_candidate(candidate, instance, data_copy, log, session):
    manifest = read_build(candidate / "source/frontend/dist")
    if manifest.get("development_build"):
        raise ValueError("Cannot deploy a development build")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = {
        **instance,
        "host": "127.0.0.1",
        "port": port,
        "data_dir": str(data_copy),
        "frontend_dir": str(candidate / "source/frontend/dist"),
        "cookie_secure": False,
        "ssl_certfile": None,
        "ssl_keyfile": None,
    }
    path = data_copy.parent / (candidate.name + "-validation.json")
    private_json(path, config)
    process = subprocess.Popen(
        [str(candidate / "venv/bin/trackio-lens"), "serve", "--config", str(path)],
        stdout=log,
        stderr=log,
    )
    try:
        return probe(f"http://127.0.0.1:{port}", manifest, session, process=process)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()  # Only the child we just created, never a port owner.
            process.wait()


def systemctl(*args):
    run(["systemctl", "--user", *args])


def switch(root, candidate):
    link = root / "current.next"
    link.unlink(missing_ok=True)
    link.symlink_to(candidate)
    link.replace(root / "current")


def activate(root, candidate, previous, service, url, session):
    switch(root, candidate)
    try:
        systemctl("restart", service)
        return probe(url, read_build(candidate / "source/frontend/dist"), session)
    except Exception as error:
        systemctl("stop", service)
        if previous and (previous / "verified.json").is_file():
            switch(root, previous)
            systemctl("start", service)
            probe(url, read_build(previous / "source/frontend/dist"), session)
            raise RuntimeError(
                "Release failed; restored the verified authenticated release"
            ) from error
        raise RuntimeError(
            "First activation failed; service stopped. The old anonymous service was NOT restored. Inspect private release logs, fix and redeploy."
        ) from error


def unit_text(root, config):
    # Quote paths for systemd, which does not run ExecStart through a shell.
    def quoted(path):
        return (
            '"'
            + str(path).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
            + '"'
        )

    return f"""[Unit]
Description=Trackio Lens authenticated experiment viewer
After=network.target

[Service]
Type=exec
WorkingDirectory={str(root / "current/source").replace("%", "%%")}
ExecStart={quoted(root / "current/venv/bin/trackio-lens")} serve --config {quoted(config)} --frontend {quoted(root / "current/source/frontend/dist")}
Environment=PYTHONUNBUFFERED=1
UMask=0077
NoNewPrivileges=true
Restart=on-failure
RestartSec=3
TimeoutStopSec=30

[Install]
WantedBy=default.target
"""


def deploy(args):
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path(root, directory=True)
    config_path = args.config.resolve()
    private_path(config_path)
    instance = json.loads(config_path.read_text())
    state = Path(instance["state_dir"])
    data = Path(instance["data_dir"])
    private_path(data, directory=True)
    auth = Auth(
        state,
        instance.get(
            "session_ttl_seconds",
            Config.__dataclass_fields__["session_ttl_seconds"].default,
        ),
    )
    session = auth.create_session()
    previous = (root / "current").resolve() if (root / "current").is_symlink() else None
    source = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = root / "releases" / (stamp + "-" + commit[:12])
    candidate.mkdir(parents=True)
    try:
        with (candidate / "build.log").open("w") as log:
            run(
                [
                    "git",
                    "clone",
                    "--no-hardlinks",
                    str(source),
                    str(candidate / "source"),
                ],
                log=log,
            )
            run(
                ["git", "checkout", "--detach", commit],
                cwd=candidate / "source",
                log=log,
            )
            run([sys.executable, "-m", "venv", str(candidate / "venv")], log=log)
            python = candidate / "venv/bin/python"
            run(
                [str(python), "-m", "pip", "install", "-r", "requirements.lock"],
                cwd=candidate / "source",
                log=log,
            )
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--no-build-isolation",
                    "--no-deps",
                    ".",
                ],
                cwd=candidate / "source",
                log=log,
            )
            run([str(python), "scripts/build.py"], cwd=candidate / "source", log=log)
            run([str(python), "-m", "pytest", "-q"], cwd=candidate / "source", log=log)
            print("Committed release built:", commit, flush=True)
            copy = root / "validation" / stamp / "data"
            backup(data, copy)
            validation = check_candidate(candidate, instance, copy, log, session)
            if previous:
                # Test the actual fallback against the candidate-migrated COPY.
                # A failure here stops deployment before the production DB changes.
                check_candidate(previous, instance, copy, log, session)
            private_json(candidate / "validation.json", validation)
            shutil.rmtree(copy)
        backup_dir = root / "backups" / stamp
        backup(data, backup_dir / "data")
        shutil.copy2(config_path, backup_dir / "instance.json")
        unit = Path.home() / ".config/systemd/user" / args.service
        if unit.exists():
            shutil.copy2(unit, backup_dir / "previous.service")
        unit.parent.mkdir(parents=True, exist_ok=True)
        text = unit_text(root, config_path)
        validation_unit = candidate / args.service
        validation_unit.write_text(text.replace(str(root / "current"), str(candidate)))
        run(["systemd-analyze", "--user", "verify", str(validation_unit)])
        unit.write_text(text)
        unit.chmod(0o600)
        systemctl("daemon-reload")
        scheme = "https" if instance.get("ssl_certfile") else "http"
        host = instance.get("host", "127.0.0.1")
        probe_host = (
            "127.0.0.1" if host == "0.0.0.0" else "[::1]" if host == "::" else host
        )
        url = f"{scheme}://{probe_host}:{instance.get('port', 7860)}"
        result = activate(root, candidate, previous, args.service, url, session)
        private_json(
            candidate / "verified.json",
            {
                **result,
                "deployed_utc": stamp,
                "previous_release": str(previous) if previous else None,
            },
        )
        private_json(
            root / "deployment.json",
            {
                **result,
                "release": str(candidate),
                "backup": str(backup_dir),
                "deployed_utc": stamp,
            },
        )
        print(json.dumps(result))
    finally:
        auth.revoke(session[0])


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--service", required=True)
    args = parser.parse_args()
    if not args.service.endswith(".service") or "/" in args.service:
        parser.error("Specify one systemd user .service name")
    args.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path(args.root, directory=True)
    with (args.root / ".deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another publication is already running for this instance")
        deploy(args)
