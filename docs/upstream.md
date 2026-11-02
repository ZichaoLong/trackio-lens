# 跟进上游正式发布

[upstream/source.json](../upstream/source.json) 保存正式发布 tag、解析后的提交、对应后端版本和原始文件 SHA-256；[前端锁文件](../frontend/package-lock.json) 与 [Python 锁文件](../requirements.lock) 固定依赖。原始基线独立提交，保留 MIT 许可和完整前端测试。

```sh
.venv/bin/python scripts/sync_upstream.py --check
.venv/bin/python scripts/sync_upstream.py --clone ../trackio --tag trackio@VERSION
```

更新要求工作区干净。入口从 GitHub 正式 release 核实 tag，fetch 该 tag，以记录的原始提交、当前源码、新 tag 做三方合并；不是用 main 的版本字段判断。全文件合并成功后才写回；冲突时工作区保持不变，临时合并树和 `conflicts.json` 供人工处理。保留本地新增文件，删除/二进制冲突需明确处理。不要用新上游目录覆盖 Lens 工作区。

随后审阅 [上游适配](../trackio_lens/upstream.py) 和官方 ASGI/存储变更，在干净隔离环境重新解析 `pyproject.toml` 的依赖并更新 `requirements.lock`（包括当前已锁定的构建工具）；`test_sync.py` 会检查后端 pin 与来源一致。运行 README 中测试、lint、build；以 [合成样例](../scripts/seed_demo.py) 和历史数据副本做桌面/手机、读写边界、记录端和迁移兼容验证。行为或路径变化同步 [架构导航](architecture.md) 和相关测试。

提交、推送后按 [部署流程](operations.md) 发布完整产物，核对运行实例身份并更新 [当前状态](status.md)。更新入口不会自动修改训练环境、推送上游 PR 或跳过兼容检查。
