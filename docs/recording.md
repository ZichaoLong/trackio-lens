# 训练记录与独立记录器

训练项目的原始记录与退出状态是事实来源。Trackio 是经用户明确授权后启用的查看副本；Lens 安装和服务启动不自动授权记录。安装官方 Trackio skills 也不是前提。

## Python 直接记录

在项目自己的环境里安装或保留兼容的 Trackio SDK；不要向训练环境安装 Lens。在导入 Trackio 前，从 `trackio-lens recording-info --json` 获取目的地，把返回的环境变量只传给这次任务。已有项目目的地应保留，冲突时先明确选择。实例查询在查看服务停止时也可使用。

```sh
# 明确授权记录后，在任务的子 shell 中设置目的地。
# 若命令不在 PATH，使用安装器打印的绝对命令路径。
(
  eval "$(trackio-lens recording-info --shell)"
  /path/to/training/python examples/python/record_metrics.py
)
```

[Python 样例](../examples/python/record_metrics.py) 只写合成标量。真实项目应复用已有配置、名称和全局步数。多个训练环境可直接写同一本机目录，无需 7860 在线；这不是共享 Python 进程，也不意味着任意 SDK 版本都兼容。分布式任务通常仅由 rank zero 记录，独立运行使用不同身份。不要在 NPU 热路径里额外同步设备只为画图。

## C++ / LibTorch

[C++17 头文件](../examples/cpp/metrics_jsonl_writer.hpp) 将小批量标量写入项目自己的 JSONL。[示例](../examples/cpp/record_metrics.cpp) 无需 Torch、Python、Rust 或网络依赖；在 LibTorch 程序已有的标量输出边界调用同一个 `Write` 即可。

```sh
c++ -std=c++17 examples/cpp/record_metrics.cpp -o /tmp/lens-metrics-example
/tmp/lens-metrics-example /private/new-example
trackio-lens record \
  --events /private/new-example/metrics.jsonl \
  --manifest /private/new-example/manifest.json \
  --report /private/new-import-result.json
```

`record` 在 Lens 的独立解释器中调用官方 SDK，默认写入安装实例发现的目录。可用 `--data-dir` 显式指定合成测试目录。也可在只有官方 SDK 的独立环境，用项目源码的 `python -m trackio_lens.recorder` 加 `--data-dir` 运行；无需查看服务。不要从已安装 skill 目录导入生产代码。

实时跟随加 `--follow --done-file /private/new-example/completed.json`。生产者在最后一行完整写出并 flush 后创建完成标记；该标记仅表示生产者结束，训练成功仍以项目结果和退出码为准。不传完成标记时可用 Ctrl+C 停止跟随，报告记为 interrupted，已投影数据保留。

## 事件与恢复语义

事件契约见 [schema](../examples/metrics-event.schema.json)，实现与校验见 [recorder](../trackio_lens/recorder.py)。manifest 包含 `run_id`、`project`、`name`，可带 `config`。复用现有实验 schema 时可以传含这些字段的 `run.json`，不必重写实验记录。

- 每行一个完整 UTF-8 JSON 对象，最大 64 KiB；同一文件只有一个写入者。
- `sequence` 从 0 连续递增，`step` 非负且不下降，允许多个事件处于同一步；数值必须有限。`step` 和 `timestamp` 是 SDK 保留字段，指标使用有意义的独立名称。
- 原始时间、上下文和事件序号保留在 JSONL；当前 SDK 的 `log` 接口不接受原始时间戳，因此网页时间是导入时间。报告和运行配置明确标识这一点。
- 离线导入先验证完整文件；实时导入等完整行，并拒绝文件被替换或截断。C++ 适配器 flush 每行，但不承诺突然断电后的 fsync 持久性；需要时由项目在检查点协调持久化。
- 每次调用创建一个新的、可识别的投影运行，绝不猜测游标后续写。已开始导入的失败会保留原始文件、部分投影及报告；离线预校验失败时还没有投影或报告。重试须选择新的报告路径。重复导入会产生另一个运行，不会静默追加到旧投影。
- 完成后用官方读取接口核对步数、标量值、事件数量和顺序。`verified` 表示此次读回一致；日志和进度计数不构成 exactly-once 保证。警告或不匹配记为 uncertain，命令返回非零。

## SDK 与数据库兼容

独立环境隔离 Python 依赖，但新查看端仍可能迁移共享 SQLite。依赖导入、旧 SDK 写入新 schema、媒体/产物路径，以及恢复后旧查看端读取，是不同检查。

本仓库 [兼容检查](../scripts/check_compatibility.py) 只操作在线备份副本。它核对历史原表/原列摘要，并运行旧 SDK 新建、迁移后新建、严格续写、错误续写拒绝、两个独立进程并发、图片/报告/文件/产物、新旧读取及再次打开。严格续写传回原配置，不能假定所有 SDK 都会保留省略的配置。

`release.py` 在后端版本改变时强制运行检查，包括上一已验证发布的 SDK 和私有 `management.json` 的 `writer_pythons`，也可追加 `--writer-python`。首次接入非空数据、又没有可验证的前版本时，必须声明旧写入解释器。检查失败不切换服务。训练项目有新的 SDK 组合时须加入矩阵；这个矩阵不自动发现或升级训练环境。

0.35 测试环境的已验证依赖组合在 [测试锁文件](../tests/fixtures/trackio-0.35.lock)。实测 0.35 配上解析得到的 huggingface-hub 1.33.0 会在导入时找不到 `CommitOperationAdd`；仅 `pip check` 不能发现此类 API 不兼容。测试环境固定为 1.16.4 后再做实际记录检查。该测试锁文件不是对训练环境的升级指令。正式 Lens 依赖仍由根目录 `requirements.lock` 管理。

## 训练 skill 接入

已更新的 `run-ml-experiments` 将 Trackio 设为明确授权的可选适配器，Python 模板默认 `off`，通过实例命令发现目的地，并支持认证后的只读 HTTP 检查。可公开的差异保存在 [集成补丁](../integrations/run-ml-experiments.patch)；安装 Lens 不会自动安装或覆盖用户 skills。补丁面向已有 skill，应用前应先用 `git apply --check` 或等价工具检查版本差异。

## 明确接入与轻量检查

只有用户明确要求接入 Lens 时才使用本节；否则保留项目已有 SDK、记录格式和目的地，不增加 Lens 检查或隐式迁移。已有会话授权不需要逐个运行重复询问。

- 已有独立 Trackio 项目可继续独立记录，迁移另行处理。
- 简单标量及 C++ 可复用 JSONL 和 `trackio-lens record`，由 Lens 环境承担 SDK；不要求既有项目重写记录系统。
- 使用项目 SDK 直接写 Lens 目录前，运行 `trackio-lens check-writer --python /project/venv/bin/python`。这仅创建私有临时合成存储，不读写正式实验目录，也不安装包或启动查看服务。

检查覆盖导入、新建、配置、标量、图片、报告、文件、产物、迁移后严格续写、新建和双方读取。它是接入检查，不替代后端升级时的历史数据副本检查。结果与依赖版本、Python 环境、查看端依赖及检查代码对应；组合相同可复用缓存，`--force` 重跑。成功返回 `passed`，失败返回 `failed` 和退出码 2；日志与结果位于实例私有 `writer-checks` 目录。

通过后可加 `--register`，将此解释器显式登记为后端升级检查对象；不用时用 `--unregister` 移除。部署者只检查显式登记的环境和上一发布 SDK，不扫描所有训练任务。环境移动或删除前应取消登记。解释器登记不授予其系统权限，也不升级该环境。

特殊记录功能可复制 [最小项目样例](../examples/python/writer_sample.py)，实现 `write` 和 `verify` 两阶段，再传 `--sample /project/tests/lens_sample.py`：前者由训练解释器运行，后者由 Lens 解释器读回并断言。样例必须使用工具提供的 `TRACKIO_DIR`，不能硬编码正式目的地；它是用户选择执行的本机代码，不是沙箱。样例文件哈希进入缓存身份，样例导入的项目代码改变后应使用 `--force`。登记只把解释器加入通用升级矩阵，自定义功能仍由项目维护验证。

公共训练 skill 负责如何选择记录方式、调用检查和保留原始结果；本仓库负责命令、场景、缓存及升级检查。可选展示失败时应单独报告，遵循项目的 `required` / `best-effort` 策略，不让研究任务无限扩展为追踪工具开发。
