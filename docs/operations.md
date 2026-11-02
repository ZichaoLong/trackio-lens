# 实例操作

先读 [产品约定](product.md#运行入口缓存与恢复)。以下路径为可替换的通用示例；实例文件均放在仓库外，进程账号拥有目录且 mode 700，私有文件 mode 600。训练与查看使用同一合法账号时，保留该账号访问数据，不改变其他目录或训练环境。

## 创建实例

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

首次密码与程序读取 token 在私有的 `initial-access.json`，仅在实例账号的本地终端读取，不贴到日志/聊天/URL。密码仅以 scrypt 哈希用于认证。初始明文文件转存密码管理器后可删除；`reset-password --state-dir PATH` 交互修改密码并撤销全部浏览器会话。`revoke-sessions --state-dir PATH` 只撤销会话。程序读取 token 是独立凭据，使用后仍需保密；若需轮换，安全地更新 `credentials.json` 的 `api_token_hash`（SHA-256），并更新调用端。密码重置不自动轮换程序 token。

## 构建、发布、恢复

```sh
git push origin main
.venv/bin/python scripts/release.py \
  --root /absolute/private/releases-root \
  --config /absolute/private/instance/instance.json \
  --service trackio.service
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

credentials = json.loads(Path("/private/initial-access.json").read_text())
client = remote_client("http://127.0.0.1:7860", credentials["api_token"])
projects = client.predict(api_name="/get_all_projects")
```

HTTP 写入通过同一适配器传 `write_token=`；直接 HTTP 调用也可同时发送这两个 header。浏览器默认只查看，保留官方写入边界。上游 SDK/CLI 直接指定 `server_url` 不会自动添加 Lens 读取凭据；需要 HTTP 的程序使用该适配器或显式 headers。普通同账号的本地 `trackio.init()` 继续直接记录原数据目录，不需读取 token，不修改训练环境。

匿名仅允许 `/__lens/login` 登录页面/提交和 `/healthz` 最小健康检查；静态资源、版本、API、文件、媒体、产物、兼容入口、WebSocket 均在边界内。目标隔离普通其他系统账号，不承诺隔离 root 或控制实例账号的进程。

## 本地验证

`scripts/seed_demo.py EMPTY_DIRECTORY` 产生合成数据；目标必须为空，不能将它指向正式库。浏览器检查使用 1440px 桌面和 360/390/430px 触控模拟视口；模拟结果不等于真机或外部入口验收。首次升级先在一致性副本上验证旧表数据保持、数据库完整性以及旧 SDK 追加写入。验证记录应放在仓库外，公开状态只保存结论与覆盖范围。
