"""Public local management entry point; credentials never appear in argv."""

import argparse
import getpass
import json
import os
import shlex
from pathlib import Path

from .auth import Auth, initialize
from .config import Config, private_path
from .management import (
    default_config,
    read_instance,
    recording_info,
    service_action,
    service_state,
)


def ask_password():
    value = getpass.getpass("New password/passphrase (14–256 characters): ")
    if value != getpass.getpass("Repeat password: "):
        raise ValueError("Passwords differ")
    return value


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Trackio Lens installation and instance management"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    config_default = Path(os.environ.get("TRACKIO_LENS_CONFIG", default_config()))
    for name in ("init", "revoke-sessions", "reset-password", "rotate-api-token"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", type=Path)
        command.add_argument("--config", type=Path, default=config_default)
        if name == "init":
            command.add_argument("--username", default="admin")
            command.add_argument(
                "--set-password",
                action="store_true",
                help="Set a personal password interactively",
            )
        if name == "reset-password":
            command.add_argument(
                "--username", help="Optionally change the account name"
            )
    for name in (
        "start",
        "stop",
        "restart",
        "status",
        "enable",
        "disable",
        "recording-info",
    ):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=config_default)
        if name in {"status", "recording-info"}:
            command.add_argument(
                "--json",
                action="store_true",
                help="Machine-readable output (also the default)",
            )
        if name == "recording-info":
            command.add_argument(
                "--shell",
                action="store_true",
                help="Print only scoped recording environment assignments",
            )
    serve = commands.add_parser("serve")
    serve.add_argument("--config", type=Path, default=config_default)
    serve.add_argument("--frontend", type=Path)
    for name in (
        "check-updates",
        "update-status",
        "update",
        "recover-update",
        "update-repository",
    ):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=config_default)
        if name == "update":
            command.add_argument(
                "--commit",
                required=True,
                help="Exact main commit returned by check-updates",
            )
        if name == "update-repository":
            command.add_argument("repository")
    from .recorder import add_arguments

    recorder = commands.add_parser(
        "record", help="Import or follow an authorized project JSONL record"
    )
    recorder.add_argument("--config", type=Path, default=config_default)
    add_arguments(recorder)
    api = commands.add_parser(
        "api", help="Call the official HTTP API with private credential files"
    )
    api.add_argument("--url", required=True)
    api.add_argument("--credentials", type=Path, required=True)
    api.add_argument("--api", required=True)
    api.add_argument("--params-file", type=Path)
    api.add_argument("--write-token-file", type=Path)
    args = parser.parse_args()
    if args.command in {
        "init",
        "revoke-sessions",
        "reset-password",
        "rotate-api-token",
    }:
        state = args.state_dir or (
            Path(read_instance(args.config)["state_dir"])
            if args.config.exists()
            else args.config.parent
        )
        if args.command == "init":
            initialize(
                state, args.username, ask_password() if args.set_password else None
            )
            print(
                f"Account initialized. Private program credential: {state / 'api-access.json'}"
            )
            if not args.set_password:
                print(
                    f"Initial sign-in credentials: {state / 'initial-access.json'}; choose your own password in Settings."
                )
            return
        auth = Auth(state, 1)
        if args.command == "reset-password":
            auth.change_account(
                args.username or auth.account()["username"], ask_password()
            )
            print(
                "Password changed. All browser sessions revoked. Program token retained."
            )
        elif args.command == "rotate-api-token":
            auth.rotate_api_token()
            print(
                f"Program token rotated. Read it locally from {state / 'api-access.json'}"
            )
        else:
            auth.revoke()
            print("All browser sessions revoked.")
    elif args.command in {"start", "stop", "restart", "enable", "disable"}:
        service_action(args.config, args.command)
        print(json.dumps(service_state(args.config), indent=2, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(service_state(args.config), indent=2, ensure_ascii=False))
    elif args.command == "recording-info":
        info = recording_info(args.config)
        if args.shell:
            for key, value in info["environment"].items():
                print(f"export {key}={shlex.quote(value)}")
        else:
            print(json.dumps(info, indent=2, ensure_ascii=False))
    elif args.command in {
        "check-updates",
        "update-status",
        "update",
        "recover-update",
        "update-repository",
    }:
        from . import updates

        if args.command == "check-updates":
            result = updates.check(args.config)
        elif args.command == "update":
            result = updates.start(args.config, args.commit)
        elif args.command == "recover-update":
            result = updates.start(args.config, None, "recover")
        elif args.command == "update-repository":
            result = updates.set_repository(args.config, args.repository)
        else:
            result = updates.status(args.config)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "record":
        from .recorder import record

        destination = args.data_dir or Path(recording_info(args.config)["data_dir"])
        result = record(
            args.events,
            args.manifest,
            destination,
            args.report,
            args.follow,
            args.done_file,
        )
        print(json.dumps(result, ensure_ascii=False))
        if result["status"] != "verified":
            raise SystemExit(2)
    elif args.command == "api":
        from .client import remote_client

        private_path(args.credentials)
        credentials = json.loads(args.credentials.read_text())
        write_token = None
        if args.write_token_file:
            private_path(args.write_token_file)
            write_token = args.write_token_file.read_text().strip()
        params = json.loads(args.params_file.read_text()) if args.params_file else {}
        client = remote_client(args.url, credentials["api_token"], write_token)
        print(
            json.dumps(client.predict(api_name=args.api, **params), ensure_ascii=False)
        )
    else:
        import uvicorn
        from starlette.middleware.gzip import GZipMiddleware

        from .app import LensApp

        config = Config.read(args.config, args.frontend)
        app = GZipMiddleware(LensApp(config), minimum_size=1024, compresslevel=5)
        uvicorn.run(
            app,
            host=config.host,
            port=config.port,
            proxy_headers=False,
            access_log=False,
            ssl_certfile=config.ssl_certfile,
            ssl_keyfile=config.ssl_keyfile,
        )


if __name__ == "__main__":
    main()
