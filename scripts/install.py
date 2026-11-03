"""Install committed Lens source in a private environment with a stable command.

The bootstrap needs only Python's standard library. Workload environments are
never installed into or activated. Existing credentials and data are retained.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))

from trackio_lens.auth import Auth, initialize  # noqa: E402
from trackio_lens.config import private_json, private_path  # noqa: E402
from trackio_lens.management import install_command, register_install  # noqa: E402


def run(argv, **kwargs):
    return subprocess.run(list(map(str, argv)), check=True, **kwargs)


def migrate_service(root, config, old, new, bootstrap):
    if old == new:
        return
    # Migration is only permitted after a complete authenticated release passed.
    release = (root / "current").resolve()
    if not (release / "verified.json").is_file():
        raise ValueError("Service migration requires a verified authenticated release")
    unit_dir = Path.home() / ".config/systemd/user"
    old_unit, new_unit = unit_dir / old, unit_dir / new
    private_path(old_unit)
    content = old_unit.read_text()
    if str(root / "current/venv/bin/trackio-lens") not in content:
        raise ValueError("Legacy service ownership mismatch")
    if new_unit.exists() or new_unit.is_symlink():
        raise ValueError("Target service already exists")
    enabled = (
        subprocess.run(
            ["systemctl", "--user", "is-enabled", old], capture_output=True
        ).returncode
        == 0
    )
    new_unit.write_text(content)
    new_unit.chmod(0o600)
    run(["systemd-analyze", "--user", "verify", new_unit])
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "stop", old])
    try:
        run(["systemctl", "--user", "start", new])
        # Probe in a fresh process so migration shares the publication verifier.
        run(
            [
                bootstrap,
                SOURCE / "scripts/verify_install.py",
                "--root",
                root,
                "--config",
                config,
            ]
        )
    except BaseException:
        run(["systemctl", "--user", "stop", new])
        new_unit.unlink()
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "start", old])
        raise
    if enabled:
        run(["systemctl", "--user", "disable", old])
        run(["systemctl", "--user", "enable", new])
    old_unit.unlink()
    run(["systemctl", "--user", "daemon-reload"])


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Stable Python 3.11+ executable; never a training environment",
    )
    parser.add_argument(
        "--root", type=Path, default=Path.home() / ".local/state/trackio-lens/service"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".config/trackio-lens/instance.json",
    )
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--service", default="trackio-lens.service")
    parser.add_argument(
        "--writer-python",
        action="append",
        default=[],
        help="Existing SDK interpreter to validate when adopting nonempty data",
    )
    parser.add_argument(
        "--migrate-service",
        help="Explicitly migrate the previously verified Lens user service",
    )
    parser.add_argument(
        "--command", type=Path, default=Path.home() / ".local/bin/trackio-lens"
    )
    parser.add_argument(
        "--bootstrap-account",
        action="store_true",
        help="Create private initial credentials instead of prompting for a password",
    )
    parser.add_argument("--enable", action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args()
    import re

    for service in (args.service, args.migrate_service):
        if service and not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.@-]*\.service", service
        ):
            parser.error("Invalid user service name")
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    python = Path(shutil.which(args.python) or args.python).resolve()
    run(
        [
            python,
            "-I",
            "-c",
            "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ is required'",
        ]
    )
    node = shutil.which("node")
    if not node:
        parser.error("Node 22.13+ and npm are required for installation from source")
    version = (
        subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    )
    if tuple(int(x) for x in version.split(".")[:2]) < (22, 13) or not shutil.which(
        "npm"
    ):
        parser.error("Node 22.13+ and npm are required")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=SOURCE).strip():
        parser.error(
            "Install from committed source; the checkout has uncommitted changes"
        )
    root, config = args.root.expanduser().resolve(), args.config.expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path(root, directory=True)
    fresh = not config.exists()
    if fresh:
        config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_path(config.parent, directory=True)
        data = (
            (args.data_dir or Path.home() / ".local/share/trackio/data")
            .expanduser()
            .absolute()
        )
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_path(data, directory=True)
        if not (config.parent / "credentials.json").exists():
            if args.bootstrap_account:
                initialize(config.parent)
            else:
                from trackio_lens.cli import ask_password

                username = input("Account name [admin]: ").strip() or "admin"
                initialize(config.parent, username, ask_password())
        private_json(
            config,
            {
                "state_dir": str(config.parent),
                "data_dir": str(data),
                "host": args.host,
                "port": args.port,
            },
        )
    else:
        private_path(config)
        instance = json.loads(config.read_text())
        if (
            args.data_dir
            and args.data_dir.resolve() != Path(instance["data_dir"]).resolve()
        ):
            parser.error(
                "Existing data destination is retained; change instance configuration deliberately"
            )
    bootstrap = root / "installer-venv"
    if not (bootstrap / "bin/python").exists():
        run([python, "-m", "venv", bootstrap])
    boot_python = bootstrap / "bin/python"
    print(f"Preparing installer. Private log: {root / 'install.log'}", flush=True)
    with (root / "install.log").open("a") as log:
        run(
            [boot_python, "-m", "pip", "install", "-r", SOURCE / "requirements.lock"],
            stdout=log,
            stderr=log,
        )
    active_service = args.migrate_service or args.service
    run(
        [
            boot_python,
            SOURCE / "scripts/release.py",
            "--root",
            root,
            "--config",
            config,
            "--service",
            active_service,
            "--python",
            python,
            *[
                item
                for writer in args.writer_python
                for item in ("--writer-python", writer)
            ],
        ]
    )
    if args.migrate_service:
        migrate_service(root, config, args.migrate_service, args.service, boot_python)
    register_install(config, root, args.service, python, Path(node).parent)
    install_command(root, config, args.command)
    if args.enable is True or (fresh and args.enable is None):
        run(["systemctl", "--user", "enable", args.service])
    elif args.enable is False:
        run(["systemctl", "--user", "disable", args.service])
    # Ensure credential handoff migration also completes for existing instances.
    instance = json.loads(config.read_text())
    Auth(Path(instance["state_dir"]), 1)
    print(
        f"Installed command: {args.command}\nService: {args.service}\nConfiguration: {config}"
    )
    if args.command.parent.as_posix() not in os.environ.get("PATH", "").split(
        os.pathsep
    ):
        print(
            f"Use the absolute command path, or add {args.command.parent} to your shell PATH."
        )
    initial = Path(instance["state_dir"]) / "initial-access.json"
    if initial.exists():
        print(
            f"Read initial sign-in credentials privately from {initial}; choose your own password in Settings."
        )


if __name__ == "__main__":
    main()
