import argparse
import json
import os
import secrets
from pathlib import Path

from .auth import Auth, initialize, password_hash
from .config import Config


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Trackio Lens instance management")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "revoke-sessions", "reset-password"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", type=Path, required=True)
        if name == "init":
            command.add_argument("--username", default="admin")
    serve = commands.add_parser("serve")
    serve.add_argument("--config", type=Path, required=True)
    serve.add_argument("--frontend", type=Path)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.state_dir, args.username)
        print(
            f"Initial credentials saved privately in {args.state_dir / 'initial-access.json'}"
        )
    elif args.command in {"revoke-sessions", "reset-password"}:
        auth = Auth(args.state_dir, 1)
        if args.command == "reset-password":
            import getpass

            password = getpass.getpass("New password (at least 14 characters): ")
            if len(password) < 14 or password != getpass.getpass("Repeat password: "):
                raise ValueError("Passwords differ or are too short")
            credentials = auth.credentials()
            credentials["salt"] = secrets.token_hex(16)
            credentials["password_hash"] = password_hash(password, credentials["salt"])
            temporary = args.state_dir / "credentials.tmp"
            temporary.write_text(json.dumps(credentials) + "\n")
            temporary.chmod(0o600)
            temporary.replace(auth.credentials_path)
            (args.state_dir / "initial-access.json").unlink(missing_ok=True)
        auth.revoke()
        print("All browser sessions revoked.")
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
