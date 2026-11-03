"""Public local management entry point; credentials never appear in argv."""

import getpass
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .auth import Auth, initialize
from .cli_text import COMMANDS, Parser, choose, configure, tr
from .config import Config, private_path
from .management import (
    default_config,
    read_instance,
    recording_info,
    service_action,
    service_state,
)


def ask_password():
    value = getpass.getpass(tr("New password/passphrase (14–256 characters): "))
    if value != getpass.getpass(tr("Repeat password: ")):
        raise ValueError("Passwords differ")
    return value


def build_parser():
    parser = Parser(description="Trackio Lens installation and instance management")
    commands = parser.add_subparsers(dest="command", required=True)
    original_add = commands.add_parser

    def add_command(name, **kwargs):
        kwargs["help"] = choose(*COMMANDS[name])
        kwargs["description"] = kwargs["help"]
        return original_add(name, **kwargs)

    commands.add_parser = add_command
    config_default = Path(os.environ.get("TRACKIO_LENS_CONFIG", default_config()))
    for name in ("init", "revoke-sessions", "reset-password", "rotate-api-token"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", type=Path)
        command.add_argument("--config", type=Path, default=config_default)
        if name == "init":
            command.add_argument("--username")
            mode = command.add_mutually_exclusive_group()
            mode.add_argument(
                "--bootstrap-account",
                action="store_true",
                help=choose(
                    "Generate private first-login credentials", "生成私有首次登录凭据"
                ),
            )
            mode.add_argument(
                "--set-password",
                action="store_true",
                help=tr("Set a personal password interactively"),
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
    completion = commands.add_parser("completion")
    completion.add_argument("kind", choices=("bash", "zsh", "fish", "install"))
    completion.add_argument("--shell", choices=("bash", "zsh", "fish"))
    completion.add_argument("--config", type=Path, default=config_default)
    writer = commands.add_parser("check-writer")
    writer.add_argument("--config", type=Path, default=config_default)
    writer.add_argument("--python", type=Path, required=True)
    writer.add_argument("--force", action="store_true")
    registration = writer.add_mutually_exclusive_group()
    registration.add_argument(
        "--register",
        action="store_true",
        help=choose(
            "Register this writer for upgrades", "登记此记录环境，供后端升级检查"
        ),
    )
    registration.add_argument(
        "--unregister",
        action="store_true",
        help=choose("Remove this writer registration", "移除此记录环境的登记"),
    )
    writer.add_argument(
        "--sample",
        type=Path,
        help=choose(
            "Project sample script accepting write/verify",
            "接受 write/verify 参数的项目样例脚本",
        ),
    )
    return parser


def execute(args):
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
            if (state / "credentials.json").exists():
                raise ValueError(
                    "Credentials already exist; use reset-password to rotate"
                )
            username = args.username or (
                "admin"
                if args.bootstrap_account
                else input(tr("Account name: ")).strip()
            )
            initialize(
                state, username, None if args.bootstrap_account else ask_password()
            )
            print(
                choose(
                    "Account initialized. Private program credential: ",
                    "账户已初始化，私有程序凭据：",
                )
                + str(state / "api-access.json")
            )
            if args.bootstrap_account:
                print(
                    choose(
                        "Initial sign-in credentials (choose your own password in Settings): ",
                        "初始登录凭据（请在设置中选择个人密码）：",
                    )
                    + str(state / "initial-access.json")
                )
            return
        auth = Auth(state, 1)
        if args.command == "reset-password":
            auth.change_account(
                args.username or auth.account()["username"], ask_password()
            )
            print(
                tr(
                    "Administrator password changed. Administrator sessions revoked. Program token retained."
                )
            )
        elif args.command == "rotate-api-token":
            auth.rotate_api_token()
            print(
                choose(
                    "Program token rotated. Read it locally from ",
                    "程序 token 已轮换，请在本机读取：",
                )
                + str(state / "api-access.json")
            )
        else:
            auth.revoke()
            print(tr("All browser sessions revoked."))
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
    elif args.command == "completion":
        from .completion import install, script
        from .management import read_management

        if args.kind == "install":
            management = read_management(args.config)
            result = install(
                management.get("command", str(Path.home() / ".local/bin/trackio-lens")),
                args.shell,
            )
            print(json.dumps(result, ensure_ascii=False))
            print(
                choose(
                    "Completion installed; open a new shell to activate.",
                    "补全已安装，打开新终端后生效。",
                ),
                file=sys.stderr,
            )
        else:
            print(script(args.kind), end="")
    elif args.command == "check-writer":
        from .writers import check

        result = check(
            args.config,
            args.python,
            args.force,
            args.register,
            args.unregister,
            args.sample,
        )
        print(json.dumps(result, ensure_ascii=False))
        if result["status"] == "failed":
            print(
                choose(
                    "Writer check failed; inspect the private report.",
                    "记录环境检查未通过，请查看私有报告。",
                ),
                file=sys.stderr,
            )
            raise SystemExit(2)
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


def main(argv=None):
    os.umask(0o077)
    argv = list(sys.argv[1:] if argv is None else argv)
    completing = bool(argv and argv[0] == "__complete")
    configure([] if completing else argv)
    parser = build_parser()
    if completing:
        from .completion import candidates

        print("\n".join(candidates(parser, argv[1:])))
        return
    args = parser.parse_args(argv)
    try:
        execute(args)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(
            choose("Operation failed: ", "操作失败：") + tr(str(error)), file=sys.stderr
        )
        raise SystemExit(2) from None
    except (KeyboardInterrupt, EOFError):
        print(choose("Cancelled.", "已取消。"), file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
