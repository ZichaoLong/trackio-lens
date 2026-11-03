"""Authenticated update control. Durable work runs in a separate user service."""

import fcntl
import json
import os
import re
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .config import private_json, private_path
from .management import installed_build, read_instance, read_management

TERMINAL = {"complete", "failed", "interrupted", "recovered"}


def repository_url(value):
    if (
        not isinstance(value, str)
        or len(value) > 500
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise ValueError("Use an HTTPS or SSH Git repository URL without credentials")
    if (
        re.fullmatch(r"git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+", value)
        and ".." not in value
    ):
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "ssh"}
        or not parsed.hostname
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.strip("/")
    ):
        raise ValueError("Use an HTTPS or SSH Git repository URL without credentials")
    if parsed.username and not (parsed.scheme == "ssh" and parsed.username == "git"):
        raise ValueError("Credentials are not allowed in the repository URL")
    return value


def update_dir(config):
    state = Path(read_instance(config)["state_dir"]) / "updates"
    state.mkdir(mode=0o700, exist_ok=True)
    private_path(state, directory=True)
    return state


@contextmanager
def control_lock(config):
    directory = update_dir(config)
    with (directory / ".control.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield directory


def load_json(path):
    if not path.exists():
        return None
    private_path(path)
    return json.loads(path.read_text())


def current_operation(directory):
    pointer = load_json(directory / "current.json")
    return load_json(directory / (pointer["id"] + ".json")) if pointer else None


def save_operation(directory, operation, **values):
    operation.update(**values, updated=time.time())
    private_json(directory / (operation["id"] + ".json"), operation)


def reconcile(directory):
    operation = current_operation(directory)
    if (
        operation
        and operation["phase"] not in TERMINAL
        and time.time() - operation["updated"] > 10
    ):
        state = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                operation["unit"],
                "-p",
                "ActiveState",
                "--value",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if state.returncode == 0 and state.stdout.strip() not in {
            "active",
            "activating",
            "reloading",
        }:
            save_operation(
                directory,
                operation,
                phase="interrupted",
                message="Update worker stopped. Recover before starting another update.",
            )
    return operation


def require_idle(directory):
    operation = reconcile(directory)
    if operation and operation["phase"] not in {"complete", "failed", "recovered"}:
        raise ValueError("An update is running or requires recovery")


def status(config):
    if not (Path(read_instance(config)["state_dir"]) / "management.json").exists():
        return {"available": False}
    management = read_management(config)
    with control_lock(config) as directory:
        operation = reconcile(directory)
        checked = load_json(directory / "checked.json")
    # Private paths and raw logs are deliberately not returned by the browser API.
    public_operation = None
    if operation:
        public_operation = {
            k: operation[k]
            for k in (
                "id",
                "phase",
                "commit",
                "repository",
                "started",
                "updated",
                "message",
                "result",
            )
            if k in operation
        }
    return {
        "available": True,
        "repository": management["repository"],
        "branch": "main",
        "installed_build": installed_build(management["root"]),
        "checked": checked,
        "operation": public_operation,
    }


def check(config):
    management = read_management(config)
    repository = repository_url(management["repository"])
    # No shell and no implicit credentials prompt. Never change the requested ref.
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", repository, "refs/heads/main"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise ValueError(
            "Could not read repository main; check network and repository access"
        )
    fields = result.stdout.strip().split()
    if (
        len(fields) != 2
        or not re.fullmatch(r"[0-9a-f]{40}", fields[0])
        or fields[1] != "refs/heads/main"
    ):
        raise ValueError("Repository did not return one main commit")
    with control_lock(config) as directory:
        require_idle(directory)
        if read_management(config)["repository"] != repository:
            raise ValueError("Repository changed during the check; retry")
        private_json(
            directory / "checked.json",
            {"repository": repository, "commit": fields[0], "checked_at": time.time()},
        )
    return status(config)


def set_repository(config, repository):
    repository = repository_url(repository)
    with control_lock(config) as directory:
        require_idle(directory)
        management = read_management(config)
        management["repository"] = repository
        private_json(
            Path(read_instance(config)["state_dir"]) / "management.json", management
        )
        (directory / "checked.json").unlink(missing_ok=True)
    return status(config)


def start(config, commit, action="update"):
    management = read_management(config)
    root = Path(management["root"])
    with control_lock(config) as directory:
        operation = reconcile(directory)
        if action == "recover":
            if not operation or operation["phase"] != "interrupted":
                raise ValueError("There is no interrupted update to recover")
            previous_operation = operation
            commit = operation["commit"]
        else:
            require_idle(directory)
            checked = load_json(directory / "checked.json")
            if (
                not checked
                or commit != checked["commit"]
                or checked["repository"] != management["repository"]
            ):
                raise ValueError(
                    "Check main and select that exact commit before updating"
                )
        identifier = uuid.uuid4().hex
        operation = {
            "id": identifier,
            "unit": "trackio-lens-update-" + identifier + ".service",
            "phase": "starting",
            "action": action,
            "commit": commit,
            "repository": management["repository"],
            "started": time.time(),
            "previous_release": str((root / "current").resolve()),
        }
        if action == "recover":
            operation["previous_release"] = previous_operation["previous_release"]
        private_json(directory / "current.json", {"id": identifier})
        save_operation(directory, operation)
        executable = (root / "current").resolve() / "venv/bin/python"
        result = subprocess.run(
            [
                "systemd-run",
                "--user",
                "--quiet",
                "--collect",
                "--unit",
                operation["unit"],
                "--property=Type=exec",
                "--property=UMask=0077",
                "--property=NoNewPrivileges=yes",
                str(executable),
                "-m",
                "trackio_lens.update_worker",
                "--config",
                str(Path(config).resolve()),
                "--operation",
                identifier,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            save_operation(
                directory,
                operation,
                phase="failed",
                message="Could not start the independent update service",
            )
            raise ValueError("Could not start the independent update service")
    return status(config)
