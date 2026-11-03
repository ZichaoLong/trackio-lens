# 检查与更新 Lens

设置页的“应用更新”管理 Lens 自身的代码，默认从安装信息中的 Git 仓库读取 `main`。默认来源的事实源是 [management.DEFAULT_REPOSITORY](../trackio_lens/management.py)。它不会跟随 Trackio 后端的 main，也不会更新训练环境；正式后端由目标提交的版本记录和锁文件决定。

点击“检查 main 更新”后显示固定提交；“安装所选提交”只安装该提交，即使远端 main 随后移动，也不会偷偷换成另一个版本。当前浏览器需要有效会话和 CSRF 校验；程序读取 token 无法执行更新。修改默认仓库需要再次输入当前密码，地址不接受内嵌密码或 query token。更新会执行所选仓库代码，仓库来源属于用户信任配置。

## 与命令行共用流程

```sh
trackio-lens check-updates
trackio-lens update --commit FULL_SHA_FROM_CHECK
trackio-lens update-status
# 仅当状态为 interrupted 时：
trackio-lens recover-update
# 本机账号可改变仓库；网页设置同样持久化到实例。
trackio-lens update-repository https://github.com/OWNER/REPOSITORY.git
```

[updates](../trackio_lens/updates.py) 验证选择和单任务约束，然后启动独立的 systemd 用户服务。[update_worker](../trackio_lens/update_worker.py) 使用已安装的独立 Python 和 Node 工具位置，获取精确提交，再调用与本机发布共用的 [release.publish](../scripts/release.py)。它不依赖查看服务进程或浏览器存活，也不在正在运行的源码目录里 git pull。

阶段状态依次为获取、构建与测试、副本兼容检查、正式备份、切换与核验。候选安装锁定依赖，执行 `pip check`、Python 测试、前端 lint/test/build，再验证真实数据副本和可用恢复版本。后端改变时还须通过 [SDK 兼容矩阵](recording.md#sdk-与数据库兼容)。切换后核对匿名拒绝、有效会话、认证数据、后端版本和 HTML/JS 哈希。

设置页分别显示当前页面和运行服务的源码身份；服务身份来自实际处理 HTTP 请求的进程，已安装目录的清单不会代替它。成功后页面显示“刷新以加载已验证版本”，普通更新保留有效会话和浏览器语言。可以关闭页面，稍后重新进入设置查看状态；重启过程可能短暂无法读取状态，页面会重试。更新不会修改 Caddy、SSH 隧道或域名配置。

## 状态与恢复

仓库设置、检查结果、每次操作的状态和私有日志保存在实例 state 目录，构建和备份仍在发布 root；密钥和会话不会进入构建。网页只返回阶段、提交与验证结论，不返回日志或私有路径。并发发布还受到实例 `.deploy.lock` 的约束。

构建或检查失败不切换服务。普通切换失败由发布器恢复上一个已验证的认证版本，随后更新任务再次核验实际 HTTP 结果。没有安全恢复版本时保持关闭。数据库不会被旧备份覆盖。

若任务被意外终止，状态查询会发现 systemd 任务已退出并标记 interrupted，阻止盲目重试。恢复任务先检查实际服务身份；如当前候选已通过副本验证且运行核验正常，就确认完成。否则用最新数据的新副本验证前版本，再恢复该认证产物。无法证明兼容时保留问题现场并报告，不能用旧数据库覆盖新增实验记录。由未知外部进程占用端口时仍只管理已确认的实例服务。

## 开发导航

改变远端/ref 校验与并发规则：`updates` 和 `test_updates`。改变会话或程序权限：`LensApp.route` 和 `test_auth`。改变构建/回退：`release`、`update_worker.recover` 和 `test_release`。界面与中文消息：`UpdateSettings.svelte` 和 `zh.json`。上游 Trackio 版本同步另见 [upstream](upstream.md)，不要把 Lens main 更新和上游正式发布同步混为一件事。


## 账户与非交互更新

仅已完成首次设置的管理员可检查/发布/恢复更新或更换仓库。普通用户及程序 token 直接调用对应 API 也被拒绝。升级不进入安装器的账户提问流程；账户、密码和角色保留在实例目录，正常升级保留有效会话。

发布预检对数据与账户状态分别创建私有副本，以程序读取凭据验证实际构建和数据；它不替代浏览器会话回归。正式切换前同时保存账户快照。当前多账户格式保留管理员的原有哈希位置，普通用户和新会话独立存储；回退到旧单账户版本只允许管理员重新登录，不会把普通用户认作管理员。恢复使用当前凭据，不恢复可能已撤销的旧会话。
