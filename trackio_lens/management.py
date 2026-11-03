"""Local service ownership and non-secret recording discovery, independent of HTTP."""

import json
import re
import shlex
import subprocess
from pathlib import Path

from .config import private_json, private_path

DEFAULT_REPOSITORY = "https://github.com/ZichaoLong/trackio-lens.git"


def default_config():
    return Path.home() / ".config/trackio-lens/instance.json"


def read_instance(path):
    path = Path(path).expanduser().absolute()
    private_path(path)
    value = json.loads(path.read_text())
    for field in ("state_dir", "data_dir"):
        private_path(Path(value[field]), directory=True)
    return value


def read_management(config):
    instance = read_instance(config)
    path = Path(instance["state_dir"]) / "management.json"
    private_path(path)
    value = json.loads(path.read_text())
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*\.service", value["service"]):
        raise ValueError("Invalid managed service name")
    root = Path(value["root"])
    if not root.is_absolute():
        raise ValueError("Release root must be absolute")
    private_path(root, directory=True)
    return value


def installed_build(root):
    path = Path(root) / "current/source/frontend/dist/lens-build.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text())
    return {
        k: value[k]
        for k in ("source_commit", "backend_version", "upstream_tag")
        if k in value
    }


def recording_info(config):
    instance = read_instance(config)
    management = Path(instance["state_dir"]) / "management.json"
    installed = read_management(config) if management.exists() else None
    build = installed_build(installed["root"]) if installed else None
    resources = {}
    if installed:
        source = (Path(installed["root"]) / "current/source").resolve()
        for name, relative in {
            "recording_guide": "docs/recording.md",
            "python_example": "examples/python/record_metrics.py",
            "writer_sample": "examples/python/writer_sample.py",
            "cpp_example": "examples/cpp/record_metrics.cpp",
            "viewer_check": "scripts/check_viewer.py",
        }.items():
            if (source / relative).is_file():
                resources[name] = str(source / relative)
    return {
        "destination_kind": "local",
        "data_dir": str(Path(instance["data_dir"]).resolve()),
        "storage_mode": "sqlite",
        "viewer": build,
        "resources": resources,
        "explicit_recording_authorization_required": True,
        "environment": {
            "TRACKIO_DIR": str(Path(instance["data_dir"]).resolve()),
            "TRACKIO_STORAGE_MODE": "sqlite",
        },
    }


def service_state(config):
    management = read_management(config)
    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            management["service"],
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "UnitFileState",
            "-p",
            "MainPID",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "service": management["service"],
        "systemd": dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        ),
        "release_root": management["root"],
        "config": str(Path(config).absolute()),
        "python": str(Path(management["root"]) / "current/venv/bin/python"),
        "installed_build": installed_build(management["root"]),
        "recording": recording_info(config),
    }


def service_action(config, action):
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        raise ValueError("Unsupported service action")
    management = read_management(config)
    unit = Path.home() / ".config/systemd/user" / management["service"]
    private_path(unit)
    expected = str(Path(management["root"]) / "current/venv/bin/trackio-lens")
    if expected not in unit.read_text():
        raise ValueError(
            "Service ownership mismatch; refusing to manage another service"
        )
    subprocess.run(["systemctl", "--user", action, management["service"]], check=True)


def register_install(
    config, root, service, python, node_bin, repository=DEFAULT_REPOSITORY
):
    instance = read_instance(config)
    path = Path(instance["state_dir"]) / "management.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    private_json(
        path,
        {
            **previous,
            "root": str(Path(root).resolve()),
            "service": service,
            "config": str(Path(config).resolve()),
            "python": str(Path(python).resolve()),
            "node_bin": str(Path(node_bin).resolve()),
            "repository": previous.get("repository", repository),
        },
    )


def install_command(root, config, destination):
    """A fixed launcher uses the selected release, never the caller's Python env."""
    destination = Path(destination).expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    executable = Path(root).resolve() / "current/venv/bin/trackio-lens"
    text = (
        "#!/bin/sh\n# Managed by Trackio Lens\nexport TRACKIO_LENS_CONFIG="
        + shlex.quote(str(Path(config).resolve()))
        + "\nexec "
        + shlex.quote(str(executable))
        + ' "$@"\n'
    )
    if destination.exists() or destination.is_symlink():
        if (
            destination.is_symlink()
            or "# Managed by Trackio Lens" not in destination.read_text()
        ):
            raise ValueError("Refusing to overwrite an unrelated command")
    temporary = destination.with_name(destination.name + ".new")
    with temporary.open("x") as out:
        out.write(text)
    temporary.chmod(0o700)
    temporary.replace(destination)
