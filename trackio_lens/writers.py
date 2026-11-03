"""Explicit SDK admission checks on synthetic storage, never the instance data."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import private_json, private_path
from .management import read_instance, read_management

IDENTITY = """
import json, sys
from importlib.metadata import distributions
print(json.dumps({"python":sys.version, "prefix":sys.prefix,
 "packages":sorted((d.metadata['Name'].lower(), d.version) for d in distributions())}))
"""


def fingerprint(python):
    result = subprocess.run(
        [str(python), "-I", "-c", IDENTITY],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    value = json.loads(result.stdout)
    if not any(name == "trackio" for name, _ in value["packages"]):
        raise ValueError("Recording Python does not have Trackio installed")
    return value


def register(config, python, remove=False):
    from .updates import control_lock, require_idle

    with control_lock(config) as directory:
        require_idle(directory)
        management = read_management(config)
        writers = management.get("writer_pythons", [])
        writers = [p for p in writers if p != str(python)]
        if not remove:
            writers.append(str(python))
        management["writer_pythons"] = writers
        private_json(
            Path(read_instance(config)["state_dir"]) / "management.json", management
        )


def check(
    config, python, force=False, register_writer=False, unregister=False, sample=None
):
    python = Path(python).expanduser().absolute()  # Preserve the venv symlink path.
    if unregister:
        register(config, python, remove=True)
        return {"status": "unregistered", "python": str(python)}
    state = Path(read_instance(config)["state_dir"])
    directory = state / "writer-checks"
    directory.mkdir(mode=0o700, exist_ok=True)
    private_path(directory, directory=True)
    fixture = Path(__file__).with_name("writer_fixture.py")
    sample = Path(sample).expanduser().resolve() if sample else None
    reader_identity = fingerprint(sys.executable)
    reader_identity.pop(
        "prefix"
    )  # A frontend-only release changes its venv path, not SDK compatibility.
    identity = {
        "schema": 1,
        "writer": fingerprint(python),
        "reader": reader_identity,
        "fixture": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "checker": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sample": hashlib.sha256(sample.read_bytes()).hexdigest() if sample else None,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    path = directory / (key + ".json")
    cached = None
    if path.exists():
        private_path(path)
        cached = json.loads(path.read_text())
    if cached and cached["status"] == "passed" and not force:
        report = cached
    else:
        log = directory / (key + ".log")
        if log.exists():
            private_path(log)
        report = {
            "status": "failed",
            "checked_at": time.time(),
            "identity": identity,
            "coverage": [
                "import",
                "new-run",
                "scalar-config-image-report-file-artifact",
                "migration",
                "strict-resume",
                "new-run-after-migration",
                "reader-readback",
            ],
            "storage": "synthetic SQLite only",
            "log": str(log),
        }
        with (
            tempfile.TemporaryDirectory(prefix="sample-", dir=directory) as temporary,
            log.open("w") as output,
        ):
            os.chmod(log, 0o600)
            environment = {
                k: v for k, v in os.environ.items() if not k.startswith("TRACKIO_")
            }
            environment.update(
                TRACKIO_DIR=temporary,
                TRACKIO_STORAGE_MODE="sqlite",
                PYTHONDONTWRITEBYTECODE="1",
            )

            def run(executable, script, *args):
                subprocess.run(
                    [str(executable), str(script), *args],
                    env=environment,
                    cwd=temporary,
                    stdout=output,
                    stderr=output,
                    check=True,
                    timeout=90,
                )

            try:
                project = "lens-writer-check"
                run(python, fixture, "seed", project)
                run(sys.executable, fixture, "migrate", project)
                run(python, fixture, "append", project)
                run(python, fixture, "fresh", project, "new-after-migration")
                for reader in (sys.executable, python):
                    for name in ("writer", "new-after-migration"):
                        run(reader, fixture, "verify", project, name)
                if sample:
                    run(python, sample, "write")
                    run(sys.executable, sample, "verify")
                    report["coverage"].append("project-sample")
                report["status"] = "passed"
            except (subprocess.SubprocessError, OSError) as error:
                report["failure"] = type(error).__name__
        private_json(path, report)
    if register_writer and report["status"] == "passed":
        register(config, python)
    return {
        "status": report["status"],
        "cached": bool(cached and report is cached),
        "writer_version": dict(identity["writer"]["packages"])["trackio"],
        "reader_version": dict(identity["reader"]["packages"])["trackio"],
        "coverage": report["coverage"],
        "report": str(path),
        "registered": bool(register_writer and report["status"] == "passed"),
    }
