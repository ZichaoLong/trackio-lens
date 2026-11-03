"""Human CLI language; command spellings and machine output stay stable."""

import argparse
import os
import sys

LANG = "zh"

MESSAGES = {
    "Trackio Lens installation and instance management": "Trackio Lens 安装与实例管理",
    "usage: ": "用法：",
    "positional arguments": "位置参数",
    "options": "选项",
    "show this help message and exit": "显示帮助并退出",
    "the following arguments are required: %s": "缺少必需参数：%s",
    "unrecognized arguments: %s": "无法识别的参数：%s",
    "argument %(argument_name)s: %(message)s": "参数 %(argument_name)s：%(message)s",
    "invalid choice: %(value)r (choose from %(choices)s)": "无效选项：%(value)r（可选：%(choices)s）",
    "expected one argument": "需要一个参数值",
    "%(prog)s: error: %(message)s\n": "%(prog)s：错误：%(message)s\n",
    "New password/passphrase (14–256 characters): ": "新密码或口令短语（14–256 个字符）：",
    "Repeat password: ": "再次输入密码：",
    "Passwords differ": "两次密码不一致",
    "Account name: ": "管理员用户名：",
    "Set a personal password interactively": "交互式设置个人密码",
    "Optionally change the account name": "同时修改管理员用户名（可选）",
    "Machine-readable output (also the default)": "输出机器可读 JSON（也是默认格式）",
    "Print only scoped recording environment assignments": "仅输出供本次任务使用的记录环境变量",
    "Exact main commit returned by check-updates": "check-updates 返回的完整 main 提交号",
    "New private result file; never overwrites an attempt": "新的私有结果文件，不覆盖已有尝试",
    "Follow complete lines until --done-file exists or interrupted": "持续读取完整行，直到完成标记出现或被中断",
    "Administrator password changed. Administrator sessions revoked. Program token retained.": "密码已修改，管理员浏览器会话已撤销，程序 token 保留。",
    "All browser sessions revoked.": "所有浏览器会话已撤销。",
    "Use a password or passphrase of 14 to 256 characters": "请使用 14–256 个字符的密码或口令短语",
    "Username must contain between 1 and 80 characters": "用户名须为 1–80 个字符",
    "Credentials already exist; use reset-password to rotate": "账户已经初始化，请使用 reset-password 重置",
    "Current password is incorrect": "当前密码不正确",
    "Service ownership mismatch; refusing to manage another service": "服务归属不匹配，无法管理其他服务",
    "An update is running or requires recovery": "更新正在运行或需要先恢复",
    "Check main and select that exact commit before updating": "请先检查 main，再使用返回的完整提交号更新",
    "There is no interrupted update to recover": "没有需要恢复的中断更新",
    "Could not read repository main; check network and repository access": "无法读取仓库 main，请检查网络和仓库访问权限",
    "Use an HTTPS or SSH Git repository URL without credentials": "请使用不含凭据的 HTTPS 或 SSH Git 仓库地址",
    "Credentials are not allowed in the repository URL": "仓库地址不得包含凭据",
    "Could not start the independent update service": "无法启动独立更新服务",
    "Stable Python 3.11+ executable; never a training environment": "独立的 Python 3.11+ 可执行文件，不使用训练环境",
    "Existing SDK interpreter to validate when adopting nonempty data": "接入已有数据时要验证的 SDK 解释器",
    "Explicitly migrate the previously verified Lens user service": "显式迁移已验证的 Lens 用户服务",
    "Create private initial credentials instead of prompting for a password": "生成私有初始凭据，供无人值守安装使用",
    "Recording Python does not have Trackio installed": "指定的记录环境尚未安装 Trackio",
    "Unsupported completion shell": "此 Shell 尚不支持自动安装补全，请选择 bash、zsh 或 fish",
    "Invalid port": "端口无效",
    "Invalid user service name": "用户服务名称无效",
    "Node 22.13+ and npm are required for installation from source": "从源码安装需要 Node 22.13+ 和 npm",
    "Install from committed source; the checkout has uncommitted changes": "请从已提交源码安装，当前工作区存在未提交修改",
    "Existing data destination is retained; change instance configuration deliberately": "保留已有数据目录，请通过明确修改实例配置来迁移目的地",
}

MESSAGES.update(
    {
        "Account is unavailable": "账户不可用",
        "Only the administrator can change their username": "仅管理员可修改自己的用户名",
        "Set a new personal password before continuing": "请先设置新的个人密码",
        "Choose a different password from the temporary password": "新密码不能与临时密码相同",
        "Choose your own administrator username": "请选择不同于初始值的个人管理员用户名",
        "Username is already in use": "用户名已被使用",
        "No account changes": "账户没有修改",
        "Account limit reached": "账户数量已达上限",
        "Select an existing viewer account": "请选择已有普通用户",
        "Unsupported account action": "不支持此账户操作",
        "Administrator access is required": "此操作需要管理员权限",
    }
)

COMMANDS = {
    "init": ("Initialize the administrator", "初始化管理员"),
    "serve": ("Run the authenticated web service", "运行受认证保护的网页服务"),
    "start": ("Start the managed service", "启动服务"),
    "stop": ("Stop the managed service", "停止服务"),
    "restart": ("Restart the managed service", "重启服务"),
    "status": ("Inspect the service and build", "查看服务状态和构建信息"),
    "enable": ("Enable automatic service startup", "启用服务自动启动"),
    "disable": (
        "Disable automatic startup (does not stop the service)",
        "禁用自动启动（不停止当前服务）",
    ),
    "recording-info": (
        "Discover the local recording destination",
        "查询本地记录目的地",
    ),
    "reset-password": (
        "Reset the administrator password locally",
        "在本机重置管理员密码",
    ),
    "revoke-sessions": ("Sign out all browser sessions", "撤销所有浏览器会话"),
    "rotate-api-token": ("Rotate the private program credential", "轮换私有程序凭据"),
    "api": (
        "Call the official API using credential files",
        "使用私有凭据文件调用官方 API",
    ),
    "record": (
        "Import or follow an authorized project JSONL record",
        "导入或跟随已授权的项目 JSONL 记录",
    ),
    "check-updates": ("Check the configured repository main", "检查所配置仓库的 main"),
    "update-status": ("Inspect update progress", "查看更新进度"),
    "update": ("Publish a checked main commit", "发布已检查的 main 提交"),
    "recover-update": ("Recover an interrupted update", "恢复中断的更新"),
    "update-repository": ("Set the trusted update repository", "设置可信更新仓库"),
    "completion": ("Print or install shell completion", "输出或安装 Shell 自动补全"),
    "check-writer": (
        "Check a recording SDK in disposable storage",
        "在临时存储中检查记录 SDK 兼容性",
    ),
}

ARGUMENTS = {
    "root": ("Private release directory", "私有发布目录"),
    "host": ("Listening address (default: loopback)", "监听地址（默认 loopback）"),
    "port": ("Listening port", "监听端口"),
    "service": ("Managed systemd user service", "受管理的 systemd 用户服务名"),
    "command": ("Installed command path", "安装后的管理命令路径"),
    "enable": ("Enable automatic startup", "启用自动启动"),
    "config": ("Private instance configuration", "私有实例配置文件"),
    "state-dir": ("Private account state directory", "私有账户状态目录"),
    "username": ("Administrator username", "管理员用户名"),
    "frontend": ("Complete compiled frontend directory", "完整前端构建目录"),
    "events": ("Project metric JSONL file", "项目指标 JSONL 文件"),
    "manifest": ("Project run manifest", "项目运行清单"),
    "data-dir": ("Explicit local recording destination", "显式指定本地记录目录"),
    "done-file": ("Producer completion marker", "记录生产者的完成标记文件"),
    "url": ("Service base URL without credentials", "不含凭据的服务地址"),
    "credentials": ("Private program credential file", "私有程序凭据文件"),
    "api": ("Official API name", "官方 API 名称"),
    "params-file": ("JSON request parameters", "请求参数 JSON 文件"),
    "write-token-file": ("Private write credential file", "私有写入凭据文件"),
    "repository": ("Trusted HTTPS or SSH Git URL", "可信 HTTPS 或 SSH Git 地址"),
    "python": (
        "Recording environment Python executable",
        "记录环境的 Python 可执行文件",
    ),
    "force": ("Repeat the check even when cached", "忽略缓存并重新检查"),
    "register": (
        "Register a passed writer for backend upgrades",
        "将通过检查的环境登记到后端升级检查中",
    ),
    "shell": (
        "Shell to configure; default is the login shell",
        "要配置的 Shell，默认使用登录 Shell",
    ),
    "kind": (
        "Shell script, or install for this user",
        "选择 Shell 脚本，或 install 安装到当前用户",
    ),
    "bootstrap-account": (
        "Generate private first-login credentials",
        "生成私有首次登录凭据",
    ),
}


def choose(english, chinese):
    return chinese if LANG == "zh" else english


def tr(value):
    return MESSAGES.get(value, value) if LANG == "zh" else value


def configure(argv=None):
    global LANG
    LANG = "en" if os.environ.get("TRACKIO_LENS_LANG") == "en" else "zh"
    argparse._ = tr
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--lang", default=os.environ.get("TRACKIO_LENS_LANG", "zh"))
    options, _ = pre.parse_known_args(sys.argv[1:] if argv is None else argv)
    LANG = options.lang if options.lang in {"zh", "en"} else "zh"
    argparse._ = tr
    if options.lang not in {"zh", "en"}:
        pre.error(
            tr("--lang must be zh or en") if LANG == "en" else "--lang 须为 zh 或 en"
        )


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        if "description" in kwargs:
            kwargs["description"] = tr(kwargs["description"])
        super().__init__(*args, **kwargs)
        self.add_argument(
            "--lang",
            choices=("zh", "en"),
            default=argparse.SUPPRESS,
            help=choose(
                "Human language (default: zh; TRACKIO_LENS_LANG)",
                "提示语言（默认 zh；可设 TRACKIO_LENS_LANG）",
            ),
        )

    def add_argument(self, *args, **kwargs):
        key = args[0].lstrip("-") if args else ""
        if kwargs.get("help"):
            kwargs["help"] = tr(kwargs["help"])
        elif key in ARGUMENTS:
            kwargs["help"] = choose(*ARGUMENTS[key])
        return super().add_argument(*args, **kwargs)
