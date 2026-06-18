# 质量闭环主体模块

## 1. 模块定位

质量闭环主体模块是 Nasus 的业务价值主线。

它负责把一次变更从“理解”推进到“是否准备好上线”的判断，最终形成：

- 可审计的验证资产
- 可追溯的执行证据
- 可治理的放行建议
- 可沉淀的质量知识

正式需求、版本/US、TaskContext、QualityProfile、QualityAssetPack、Run、Evidence、FailureReport、Release Readiness 和验收标准以 [产品需求基线：质量闭环主体模块需求](../../product-requirements.md#7-质量闭环主体模块需求) 为准。

质量闭环中的验证点、测试用例、自动化蓝图、回归范围和历史功能保护，必须消费 [系统画像长期质量闭环支撑方案](../system-image/quality-closure-enablement.md) 定义的上下文与覆盖链路，不允许只基于 US 文本自由生成。

## 2. 模块职责

它回答的问题是：

- 当前 US / 版本的功能验收是否完整
- 验证资产是否覆盖风险
- 执行结果是否足以支撑上线判断
- 哪些知识应该沉淀回基线

它承载的关键能力包括：

- 版本创建与 US 导入
- 围绕 US 的质量分析
- 测试范围、场景、计划、用例与自动化建议
- 执行证据、失败归因与修复建议
- 审批、冲突处理、放行建议与基线回写

## 3. 子文档

- [版本交付](./version-delivery.md)
- [质量工作台](./quality-workspace.md)
- [执行与可观测性](./execution-observability.md)
- [治理与放行](./governance-release.md)
- [质量生成策略](./quality-generation.md)

## 4. 边界说明

不负责：

- 存量系统原料接入与系统画像初始化
- 通用主会话编排与 LLM 运行时本身

这些分别由：

- [系统画像构建模块](../system-image/README.md)
- [Agent 主体模块](../agent/README.md)

承担。

## 5. 验收标准

- 一个版本可以从正式基线创建工作基线，导入 US，完成 owner 分配和初始风险视图。
- 单个 US 必须先生成 `TaskContext` 和 `QualityProfile`，再进入质量资产生成。
- 验证点、测试用例、自动化蓝图和回归范围必须能回溯到系统画像对象、历史测试资产、CoverageMatrix 和执行证据。
- `QualityAssetPack` 必须支持结构化 part、局部重生成、review、revision 和 `pending_merge`。
- 每次正式执行生成 canonical `Run` 和 append-only `ExecutionEvidence`。
- Release Readiness 必须基于所有 US、资产、执行、失败、审批和未闭环项聚合。
- 正式放行、知识晋级和基线回写必须可追溯、可审批、可审计。
