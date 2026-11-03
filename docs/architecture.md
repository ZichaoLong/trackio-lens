# 任务导航与事实来源

行为目标见 [产品约定](product.md)，开发流程见 [开发规范](development.md)，实例操作见 [operations](operations.md)。本表指向实现，不重复定义配置默认值。

| 常见任务 | 事实来源和负责入口 | 影响范围 / 验证 |
| --- | --- | --- |
| 修改会话有效期、Cookie、监听地址 | [Config](../trackio_lens/config.py)；实例 JSON（仓库外） | [Auth.session](../trackio_lens/auth.py) 同时约束已有会话；[认证测试](../tests/test_auth.py)，运行服务重启与会话验证 |
| 登录、退出、撤销、程序认证 | [Auth](../trackio_lens/auth.py)、[LensApp.route](../trackio_lens/app.py)、[CLI](../trackio_lens/cli.py)、[LensAuth](../trackio_lens/client.py) | 全路由认证、CSRF、密码和 token 边界在 [test_auth](../tests/test_auth.py)；浏览器入口 [lens.js](../frontend/src/lib/lens.js) |
| 安装、服务启停、自动启动、记录目的地 | [install](../scripts/install.py)、[management](../trackio_lens/management.py)、[CLI](../trackio_lens/cli.py)；实例 `management.json` 是安装信息源 | [test_management](../tests/test_management.py)、[verify_install](../scripts/verify_install.py)；[账户设置](../frontend/src/components/AccountSettings.svelte) 调用浏览器专用账户 API |
| Python / C++ 训练记录与重放 | [recording](recording.md)、[recorder](../trackio_lens/recorder.py)、[C++ writer](../examples/cpp/metrics_jsonl_writer.hpp)；事件 schema 位于 examples | [test_recorder](../tests/test_recorder.py) 编译真实 C++ 并核对 SDK 落盘、完整行跟随和失败边界；训练 skill 差异在 integrations |
| 增加/适配上游接口 | [upstream.build_backend](../trackio_lens/upstream.py)，官方包 `trackio.server` 和 `trackio.asgi_app` | [source.json](../upstream/source.json) 定位正式 tag；前端 [api.js](../frontend/src/lib/api.js) 是直接消费者；发布副本验证会运行真实后端 |
| 修改图表排列、加载和平滑 | [Metrics](../frontend/src/pages/Metrics.svelte)、[plotLayout](../frontend/src/lib/plotLayout.js)、[LinePlot](../frontend/src/components/LinePlot.svelte) | [chartLifecycle](../frontend/src/lib/chartLifecycle.js) 负责可视范围/内存；[dataProcessing](../frontend/src/lib/dataProcessing.js) 及相邻 `.test.js` 负责缺失值和平滑；[ChartReadout](../frontend/src/components/ChartReadout.svelte) / [chartReadout.test](../frontend/src/lib/chartReadout.test.js) 保证触控读原始值；`npm --prefix frontend test` |
| 中英文界面与登录翻译 | [i18n](../frontend/src/lib/i18n.js)、[中文消息](../frontend/src/lib/zh.json)，[Settings](../frontend/src/pages/Settings.svelte) 管理语言；[build](../scripts/build.py) 将同一词典用于 [登录页](../trackio_lens/login.html) | [i18n.test](../frontend/src/lib/i18n.test.js)、中英文 [浏览器检查](../scripts/browser_check.py)；只翻译界面消息，不处理用户记录文本 |
| 手机侧栏、导航、长报告 | [App](../frontend/src/App.svelte)、[SidebarShell](../frontend/src/components/SidebarShell.svelte)、[Navbar](../frontend/src/components/Navbar.svelte)、[Reports](../frontend/src/pages/Reports.svelte) | [viewport](../frontend/src/lib/viewport.js)、[router.test](../frontend/src/lib/router.test.js)；合成数据浏览器验证，区别真机 |
| 实验筛选与比较 | [runFilters](../frontend/src/lib/runFilters.js)、[Runs](../frontend/src/pages/Runs.svelte)、[RunComparer](../frontend/src/components/RunComparer.svelte) | 相邻单元/组件测试；配置筛选与 URL 恢复 |
| 媒体、文件、产物、深链接 | [Media](../frontend/src/pages/Media.svelte)、[Files](../frontend/src/pages/Files.svelte)、[ArtifactsDetail](../frontend/src/pages/ArtifactsDetail.svelte) | 文件 API 仍由官方后端裁定路径；[LensApp](../trackio_lens/app.py) 精确区分 `/files` 页面与 `/file` API |
| 升级上游 | [sync_upstream](../scripts/sync_upstream.py)、[source.json](../upstream/source.json)、[pyproject](../pyproject.toml)、[requirements.lock](../requirements.lock) | [test_sync](../tests/test_sync.py)，[升级步骤](upstream.md)；冲突时不改工作区 |
| 网页 / CLI 检查 main、固定提交更新 | [updates](../trackio_lens/updates.py)、[独立任务](../trackio_lens/update_worker.py)、[UpdateSettings](../frontend/src/components/UpdateSettings.svelte)；仓库配置来自私有 management.json | [test_updates](../tests/test_updates.py)、[test_auth](../tests/test_auth.py)、[更新操作](updates.md)；共用 release.publish，恢复先验证实际 HTTP 和数据副本 |
| 构建、缓存、发布与恢复 | [build](../scripts/build.py)、[read_build](../trackio_lens/upstream.py)、[release](../scripts/release.py) | [test_release](../tests/test_release.py)、真实副本预检、部署后匿名/会话/资源哈希核验；运行身份来自认证后的 `/__lens/build` |
| 备份与历史兼容 | [backup](../scripts/backup.py)、[check_compatibility](../scripts/check_compatibility.py)，[compatibility_fixture](../scripts/compatibility_fixture.py)、官方 `SQLiteStorage.migrate_all_projects` | SQLite online backup + integrity check；[release.compatibility_gate](../scripts/release.py) 在后端变更时强制运行已声明 SDK 矩阵；覆盖原表摘要、严格续写、新建、并发和媒体/产物读回 |

前端目录保留上游组织方式。原样导入提交为 `68afeeb`；本地认证和部署代码不进入官方包目录，不修改 site-packages，不启动额外的裸后端。登录页由外层 ASGI 提供，前端挂载前取得会话与 CSRF；所有官方路由仍经过外层认证。

会话 SQLite、凭据文件、真实实验数据库属于实例；不可从 Git HEAD 推断实例版本。构建身份由提交、上游记录和实际文件哈希生成；运行进程固定解析后的发布目录，切换链接不会让旧进程混用新资源。无 service worker。

[check_demo](../scripts/check_demo.py) 是桌面/手机回归入口，[browser_check](../scripts/browser_check.py) 连接页面、接口和行为断言；[CI](../.github/workflows/checks.yml) 运行相同公开样例。导航抽查：会话有效期从 `Config.session_ttl_seconds` 到 `Auth.session` 和 `test_shortened_ttl_applies_to_existing_sessions`；图表排列从 `Metrics` 到 `plotLayout` 和手机单列断言；上游升级从 `source.json` 到 `sync_upstream` 和 `test_sync`。不需要读取整个应用来完成这些任务。

刷新周期统一由 [hostPolling.LIVE_POLL_INTERVAL_MS](../frontend/src/lib/hostPolling.js) 定义，不随访问域名变化；应用与曲线任务避免重叠，隐藏标签暂停数据轮询，图表延续上游按视口建立/释放 Vega view。批量曲线请求的数量和点数上限由官方 `get_logs_batch` 定义，本地不修改原数据或维护第二套数据库。
