# 实例操作

先读 [产品约定](product.md#运行入口缓存与恢复)。以下路径为可替换的通用示例；实例文件均放在仓库外，进程账号拥有目录且 mode 700，私有文件 mode 600。训练与查看使用同一合法账号时，保留该账号访问数据，不改变其他目录或训练环境。

## 创建实例

独立安装优先使用仓库的 `./install.sh --python /absolute/stable/python3`（Python 3.11+，Node 22.13+ 和 npm）。安装器只接受已提交源码，在私有发布目录构建完整前端、安装锁定依赖、验证数据副本并发布。它不把 Lens 装进调用者的 Python 或训练环境。新实例交互设置账户，自动化安装可明确传 `--bootstrap-account` 生成私有首次登录文件。

默认命令位于 `~/.local/bin/trackio-lens`，可从任意工作目录执行。将该目录加入个人 PATH 后使用 `trackio-lens start`、`stop`、`restart`、`status`、`enable`、`disable`。`enable/disable` 只改变自动启动，`start/stop` 只改变当前运行。新实例默认 enable；Linux 用户服务随用户管理器启动，脱离登录运行需本站已启用 linger。`status` 区分 systemd 状态与已安装构建，不把目录身份当成实际 HTTP 核验。

可配置 `--root`、`--config`、`--data-dir`、`--host`、`--port`、`--service` 和 `--command`；已有实例保留数据及账户。迁移已验证的旧 Lens 单元时明确传 `--migrate-service OLD.service --service trackio-lens.service`，仅停止检查过归属的单元，新单元实际 HTTP 验证失败则恢复旧单元。新安装不会接管无关服务。安装器的完整帮助为 `./install.sh --help`。

以下为不安装 systemd 的手工创建方式：

```sh
umask 077
mkdir -p "$HOME/.config/trackio-lens" "$HOME/.local/share/trackio-lens/data"
.venv/bin/trackio-lens init --state-dir "$HOME/.config/trackio-lens"
```

在该配置目录创建 `instance.json`，将示例路径替换为绝对路径。已有数据实例的 `data_dir` 指向其原目录；先运行备份并用数据副本验证兼容。

```json
{
  "state_dir": "/absolute/private/instance",
  "data_dir": "/absolute/private/data",
  "host": "127.0.0.1",
  "port": 7860,
  "cookie_secure": false
}
```

未列出的默认值只在 [Config](../trackio_lens/config.py) 维护。端口被占用会失败，绝不自动换端口。直接 HTTPS 可配置 `ssl_certfile`、`ssl_keyfile`，并启用 `cookie_secure`。经 HTTPS 反向代理也可启用该选项；监听 HTTP 的 IP＋端口实例需要关闭它。不会信任 `X-Forwarded-*` 来豁免认证。对外传输密码时使用 HTTPS；loopback HTTP 可用于本机或已有安全隧道。

首次密码在私有的 `initial-access.json`，程序读取 token 单独保存在 `api-access.json`。仅在实例账号的本地终端读取，不贴到日志/聊天/URL。服务使用 `credentials.json` 中的 scrypt 哈希认证，修改初始交付文件不改变密码。旧实例首次加载新版时分离交付文件，但不轮换密码、token 或会话。

设置页可用当前密码修改账户名和密码（支持密码管理器与口令短语）；改密撤销其他设备会话，当前设备取得新会话，初始明文交付文件删除。`trackio-lens reset-password` 提供本机交互恢复并撤销全部浏览器会话；`revoke-sessions` 只撤销会话。`rotate-api-token` 将新程序凭据保存到 `api-access.json`，旧 token 即失效。密码重置不轮换程序 token。管理命令使用安装器配置的实例，可用 `--config` 或 `--state-dir` 明确选择其他实例。

## 构建、发布、恢复

```sh
git push origin main
.venv/bin/python scripts/release.py \
  --root /absolute/private/releases-root \
  --config /absolute/private/instance/instance.json \
  --service trackio-lens.service
```

这是部署授权下的操作，会替换指定的 **systemd user** 服务。首次执行前核实该服务确实拥有预期端口；脚本只管理指定服务，不终止未知端口占用者。Node/npm 必须在 PATH 中。

脚本克隆提交、安装锁定依赖、构建、运行 Python 测试，在独立 TCP 端口用受认证保护的候选实例读取数据库副本，再测试上一安全版本读取同一迁移后副本。候选退出后，对正式数据做新的在线备份，写服务单元、原子切换完整产物并重启。会话在切换前创建，切换后必须仍然有效；核验匿名拒绝、认证读取、后端版本和实际 HTML/JS 哈希。核验结果和日志写入实例发布根目录，`deployment.json` 是部署记录，实际 HTTP 身份才是当前运行证据。

失败自动恢复已验证的认证版本；首次失败保持关闭，绝不恢复旧匿名服务。备份是逐数据库事务一致的快照，数据库间没有跨库事务，媒体在数据库后复制。恢复程序不覆盖正在被训练写入的数据。跨上游版本迁移必须额外确认旧记录端与新 schema 兼容；副本上启动旧查看版本只能证明读取/启动兼容，不能代替记录端验证。必要的数据恢复应先协调写入端并在新目录恢复，核对迁移后新增记录后切换，不能直接用旧备份覆盖正式库。

完整前端缺失或哈希不符时启动失败；不会回退 starter 模板。HTML/API/媒体/文件使用 `no-store`；认证后的内容哈希静态资源可私有长期缓存。页面显示源码短提交，检测新版本时提示刷新。刷新后取得同一新构建；正常发布保留会话，过期/退出后跳回登录并保留安全的站内深链接。首次应用认证需登录一次。

## 程序访问与写入

读取需要 `X-Trackio-Lens-Token`，写入还需要独立的 `X-Trackio-Write-Token`。write token 保存在实例 `write-token` 文件，不授予读取权限，也不出现在 URL。示例从私有文件取读取 token：

```python
import json
from pathlib import Path
from trackio_lens.client import remote_client

credentials = json.loads(Path("/private/api-access.json").read_text())
client = remote_client("http://127.0.0.1:7860", credentials["api_token"])
projects = client.predict(api_name="/get_all_projects")
```

HTTP 写入通过同一适配器传 `write_token=`；直接 HTTP 调用也可同时发送这两个 header。浏览器默认只查看，保留官方写入边界。上游 SDK/CLI 直接指定 `server_url` 不会自动添加 Lens 读取凭据；需要 HTTP 的程序使用该适配器或显式 headers。普通同账号的本地 `trackio.init()` 继续直接记录原数据目录，不需读取 token，不修改训练环境。

CLI 可用 `trackio-lens api --url URL --credentials /private/api-access.json --api get_all_projects`，参数从 `--params-file FILE` 读取；写入另传 `--write-token-file FILE`。凭据内容不进入命令行参数或 URL。

明确授权记录后，训练启动器从 `trackio-lens recording-info --json` 读取实例的非秘密目的地，将返回的 `TRACKIO_DIR` 和 `TRACKIO_STORAGE_MODE` 只设置给这次任务，并在导入 Trackio 前生效。`--shell` 可输出经过 shell 转义的环境赋值，不修改 shell 初始化文件。该查询不依赖查看服务正在运行。项目仍使用自己的 SDK 和原始记录，不自动安装 Lens 或改写已有目的地。

匿名仅允许 `/__lens/login` 登录页面/提交和 `/healthz` 最小健康检查；静态资源、版本、API、文件、媒体、产物、兼容入口、WebSocket 均在边界内。目标隔离普通其他系统账号，不承诺隔离 root 或控制实例账号的进程。

## 本地验证

`scripts/seed_demo.py EMPTY_DIRECTORY` 产生合成数据；目标必须为空，不能将它指向正式库。浏览器检查使用 1440px 桌面和 360/390/430px 触控模拟视口；模拟结果不等于真机或外部入口验收。首次升级先在一致性副本上验证旧表数据保持、数据库完整性以及旧 SDK 追加写入。验证记录应放在仓库外，公开状态只保存结论与覆盖范围。

安装 Playwright Chromium 后运行 `.venv/bin/python scripts/check_demo.py --output /private/new-demo-directory`，自动创建合成实例并运行 [browser_check](../scripts/browser_check.py)。目录必须尚不存在；进程与端口随检查结束退出。该入口也用于 [CI](../.github/workflows/checks.yml)。

历史兼容可重复运行 `scripts/check_compatibility.py --source /private/data --output /private/new-check --old-python /old/environment/bin/python`。它在线备份源库，核对新版本迁移前后的所有原表原列数据摘要，再用旧 SDK 在副本追加并由新版本读取。仅写入新建的副本目录；原数据和旧环境不修改。

训练接入、独立 C++ 记录器和 SDK 矩阵的操作见 [记录指南](recording.md)。后端改变时发布器自动检查上一发布的 SDK，加上私有 `management.json` 中的 `writer_pythons` 解释器列表；首次采用非空存储时安装器支持重复 `--writer-python PATH`。这些解释器只在数据副本中运行，不升级它们。

设置页和 CLI 现在可以检查固定仓库 main 并更新到明确提交，操作和恢复流程见 [应用更新](updates.md)。管理命令路径、服务名称和发布根目录由安装信息记录，更新任务独立于查看服务。
