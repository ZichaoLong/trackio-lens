---
name: develop-trackio-lens
description: Develop, review, sync upstream versions, or deploy Trackio Lens using its repository-owned navigation, contracts, and verification workflow. Use for work in the Trackio Lens repository.
---

# Develop Trackio Lens

从 Trackio Lens 仓库根目录工作。此 skill 是执行入口，规范以仓库文档为准。
根据当前任务及已有授权选择检查、修改、同步或部署，不把只读检查扩展为修改。

1. 读适用的 AGENTS.md，核对 Git 状态。接续工作时读
   [当前状态](../../../docs/status.md)，并核实与任务有关的记录。
2. 按 [开发规范](../../../docs/development.md) 定位事实来源、实现和测试。
   先限定读取与修改范围，只有调用关系、共享状态或失败证据需要时才扩展。
3. 按任务读取 [产品约定](../../../docs/product.md) 的相关部分：
   - 页面和交互：查看体验与数据语义；
   - 后端适配或登录：访问隔离与程序接入；
   - 上游同步：版本来源与兼容；
   - 部署：运行入口、缓存、会话和恢复。
4. 在定位出的范围内完成工作，保持行为约定、实现、相关测试与导航引用一致。
   导航缺失时从真实代码窄搜索；仓库尚未实现的模块不能写成已存在能力。
5. 运行相关检查，按开发规范记录结果；在授权范围内提交、推送和部署。
   核对实际交付状态并更新接续记录，报告具体未完成项。

初始化项目时先建立真实代码入口和可运行检查，再补对应的任务导航。
已有公开约定不等于已实现；本地检查通过也不等于已推送或已部署。
