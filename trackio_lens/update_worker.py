"""Independent systemd worker; delegates installation to the common publisher."""

import argparse
import contextlib
import importlib.util
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from . import skills
from .config import private_json, private_path
from .management import read_instance, read_management, service_action
from .updates import load_json, repository_url, save_operation, update_dir


def publisher(source):
    scripts = source / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "lens_publisher", scripts / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recover(release, management, operation, log):
    """Reconcile actual HTTP identity, or validate the fallback on a fresh copy."""
    root = Path(management["root"])
    instance = read_instance(management["config"])
    current = (root / "current").resolve()
    previous = Path(operation["previous_release"])
    host = instance.get("host", "127.0.0.1")
    host = "127.0.0.1" if host == "0.0.0.0" else "[::1]" if host == "::" else host
    scheme = "https" if instance.get("ssl_certfile") else "http"
    url = f"{scheme}://{host}:{instance.get('port', 7860)}"
    access = Path(instance["state_dir"]) / "api-access.json"
    private_path(access)
    import json

    session = json.loads(access.read_text())
    try:
        try:
            manifest = release.read_build(current / "source/frontend/dist")
            allowed = (
                current == previous and (current / "verified.json").is_file()
            ) or (
                manifest["source_commit"] == operation["commit"]
                and (current / "validation.json").is_file()
            )
            if allowed:
                result = release.probe(url, manifest, session, timeout=5)
                result["integration_skill"] = skills.sync(root, current)
                private_json(current / "verified.json", {**result, "reconciled": True})
                private_json(
                    root / "deployment.json",
                    {**result, "release": str(current), "reconciled": True},
                )
                return result
        except Exception:
            pass
        if not (previous / "verified.json").is_file():
            service_action(management["config"], "stop")
            skills.withdraw(root)
            raise ValueError("No verified authenticated fallback; service kept closed")
        copy = root / "recovery" / operation["id"] / "data"
        release.backup(Path(instance["data_dir"]), copy)
        # Never restore a database snapshot over records written since an upgrade.
        release.check_candidate(previous, instance, copy, log, session)
        result = release.activate(
            root, previous, None, management["service"], url, session
        )
        private_json(
            root / "deployment.json",
            {
                **result,
                "release": str(previous),
                "recovered": True,
                "validation_copy": str(copy),
            },
        )
        return result
    finally:
        session.clear()


def execute(config, identifier):
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid operation ID")
    management = read_management(config)
    directory = update_dir(config)
    operation = load_json(directory / (identifier + ".json"))
    if not operation or operation["phase"] != "starting":
        raise ValueError("Update operation cannot be started again")
    # Resolve the worker's publisher once; a later switch cannot mix its source.
    installed = (Path(management["root"]) / "current").resolve()
    release = publisher(installed / "source")
    root = Path(management["root"])
    environment = {
        **os.environ,
        "PATH": management["node_bin"]
        + os.pathsep
        + os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_TERMINAL_PROMPT": "0",
    }

    def progress(phase, **details):
        save_operation(directory, operation, phase=phase, **details)

    with (
        (directory / (identifier + ".log")).open("x") as log,
        contextlib.redirect_stdout(log),
        contextlib.redirect_stderr(log),
    ):
        try:
            if operation["action"] == "recover":
                progress("recovering")
                import fcntl

                with (root / ".deploy.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    result = recover(release, management, operation, log)
                progress("recovered", result=result)
                return
            progress("fetching")
            repository = repository_url(operation["repository"])
            checkout = directory / (identifier + "-source")
            checkout.mkdir(mode=0o700)
            for command in (
                ["git", "init", "--quiet"],
                ["git", "remote", "add", "origin", repository],
                ["git", "fetch", "--depth=1", "origin", operation["commit"]],
                ["git", "checkout", "--detach", operation["commit"]],
            ):
                subprocess.run(
                    command,
                    cwd=checkout,
                    env=environment,
                    stdout=log,
                    stderr=log,
                    check=True,
                    timeout=120,
                )
            actual = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
            ).strip()
            if actual != operation["commit"]:
                raise ValueError("Fetched checkout differs from the selected commit")
            os.environ["PATH"] = environment["PATH"]
            args = SimpleNamespace(
                root=root,
                config=Path(config),
                service=management["service"],
                python=management["python"],
                source=checkout,
                writer_python=[],
            )
            result = release.publish(args, progress)
            progress("complete", result=result)
        except BaseException as error:
            # Ordinary activation errors already use the publisher's tested rollback.
            # Unexpected worker termination during switching needs explicit reconciliation.
            if operation["phase"] == "switching":
                try:
                    import fcntl

                    with (root / ".deploy.lock").open("a") as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        result = recover(release, management, operation, log)
                    if result["source_commit"] == operation["commit"]:
                        progress("complete", result=result)
                    else:
                        progress(
                            "failed",
                            result=result,
                            message="Update failed; the verified authenticated release was restored.",
                        )
                except BaseException:
                    progress(
                        "interrupted",
                        message="Update interrupted during activation. Recover to verify the running version.",
                    )
            elif operation["phase"] == "recovering":
                progress(
                    "interrupted",
                    message="Update interrupted during activation. Recover to verify the running version.",
                )
            else:
                progress(
                    "failed",
                    message="Update failed before activation. The running release was not changed.",
                    failure_phase=operation["phase"],
                    error_type=type(error).__name__,
                )
            import traceback

            traceback.print_exc(file=log)
            raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--operation", required=True)
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise InterruptedError("Worker termination requested")

    signal.signal(signal.SIGTERM, interrupted)
    execute(args.config, args.operation)


if __name__ == "__main__":
    main()
