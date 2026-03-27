# Nasus LLM Provider 与推理运行时设计

## 1. 文档定位

本文定义 Nasus 如何接入底层大模型 Provider、如何管理 Prompt、如何做上下文裁剪、token 计量、模型路由和降级策略。

## 2. 设计目标

- Provider 可替换，不把 Agent 绑定到单一模型厂商。
- Prompt 可版本化、可评审、可回滚。
- 推理预算可观测、可限额、可按项目/版本/任务追踪。
- 长上下文优先通过结构化上下文裁剪解决，而不是盲目堆 token。
- 模型故障或预算耗尽时必须可降级。

## 3. 总体结构

`Conversation Orchestrator / Agent Graph / Skills`
-> `LLM Gateway`
-> `Provider Adapters`
-> `Model Runtime`

组成：

- `LLM Gateway`
  - 统一调用入口
  - 负责模型路由、预算控制、重试、降级
- `Prompt Registry`
  - 管理系统 prompt、tool selection prompt、merge prompt、failure analysis prompt 等模板
- `Context Packaging`
  - 负责把 `TaskContext / QualityProfile / Evidence / Baseline` 组装成模型输入
- `Token Metering`
  - 负责 token 统计、预算和告警
- `Provider Adapters`
  - OpenAI / Anthropic / Gemini / 私有模型等适配层

## 4. Provider 抽象

最小接口：

- `list_models()`
- `invoke_chat()`
- `invoke_json()`
- `count_tokens()`
- `supports_tool_calling()`
- `supports_reasoning()`
- `supports_streaming()`

Provider 不能直接暴露给业务层；业务层只依赖 `LLM Gateway`。

## 5. 模型分层

建议把模型按能力用途分成 4 类：

- `planner`
  - 用于 Conversation Orchestrator 和 Agent 规划
- `structured`
  - 用于稳定输出 JSON / ToolInvocationPlan
- `extractor`
  - 用于长文本归纳、证据摘要、结构抽取
- `fallback`
  - 用于预算不足或主模型失败时的降级路径

规则：

- Tool 规划优先用结构化输出更稳定的模型
- Failure/Healing 等高风险判断必须优先选择稳定性高于创意性的模型
- 不允许把最昂贵模型默认用于所有任务

## 6. Prompt 管理

Prompt 不是硬编码字符串，必须进入 `Prompt Registry`。

每个 Prompt 模板至少包含：

- `prompt_id`
- `name`
- `version`
- `purpose`
- `input_schema_ref`
- `output_schema_ref`
- `safety_rules_ref`
- `rollback_to`

Prompt 分类至少包括：

- conversation intent parsing
- tool selection
- clarification asking
- task context summarization
- impact analysis
- scenario generation
- failure analysis
- healing proposal
- release advice
- merge assistance

## 7. 上下文窗口管理

默认策略：

- 不直接把完整会话、完整系统画像、完整执行日志塞给模型
- 优先使用 `TaskContext`、`QualityProfile`、`ContextObject`、`Evidence Summary` 这些结构化对象
- 超长上下文先摘要再进入主模型

Context Packaging 步骤固定为：

1. 绑定空间上下文：`project/version/session/us/task`
2. 绑定当前工具上下文：`tool_id / required_context`
3. 提取相关系统画像片段
4. 提取最近执行与证据摘要
5. 计算 token 预算
6. 超预算时执行裁剪：
   - 保留最新和最高置信度证据
   - 对长文档和长日志先生成 summary
   - 对不影响当前工具的上下文做裁剪

## 8. Token 计量与预算

Token 统计维度至少包括：

- `conversation_id`
- `tool_invocation_id`
- `task_id`
- `version_id`
- `project_id`
- `provider`
- `model`

预算层级：

- 项目级预算
- 版本级预算
- 会话级预算
- 单次工具调用预算

超过预算时的默认策略：

1. 压缩上下文
2. 切换更低成本模型
3. 切换为 retrieval-only / summary-only 模式
4. 明确告知用户需要缩小问题范围

## 9. 降级与容错

默认降级顺序：

1. 同 Provider 内降级到更轻模型
2. 切换备用 Provider
3. 关闭非关键 reasoning，只保留结构化工具选择
4. 回退到 read-only 建议，不执行高风险生成

以下情况必须触发降级或阻断：

- Provider 429 / 5xx 持续失败
- token budget 超限
- structured output 连续不符合 schema
- 延迟超阈值

## 10. 推理审计与可观测性

每次模型调用至少记录：

- `llm_call_id`
- `provider`
- `model`
- `prompt_id`
- `prompt_version`
- `input_token_count`
- `output_token_count`
- `latency_ms`
- `tool_invocation_id`
- `task_id`
- `outcome`

敏感内容默认不完整落日志；原始 prompt 和原始输出应按策略分级存储。

## 11. 工程默认值

- 所有模型调用必须经过 `LLM Gateway`
- Prompt 必须版本化
- 工具规划优先使用结构化输出链路
- token 预算必须先于模型调用检查
- Provider 故障不能直接让主工作流失控，必须走降级路径

## 12. 首发模型路由建议

首发建议至少准备以下模型槽位：

- `planner.primary`
  - 用于 `Conversation Orchestrator` 的意图分类、多步计划和工具排序
- `structured.primary`
  - 用于稳定输出 `ToolInvocationPlan`、Skill 结构化结果、冲突 payload
- `analysis.primary`
  - 用于 `failure.analyze`、`release.advice`、高风险摘要
- `fallback.primary`
  - 用于预算不足、主模型失败时的降级

默认路由：

- `Conversation Orchestrator`
  - 先走 `structured.primary`
- `Agent Loop THINK`
  - 走 `planner.primary`
- `quality.scope/scenario/case/change-doc`
  - 走 `structured.primary`，必要时由 `planner.primary` 辅助
- `failure.analyze / healing.propose / release.advice`
  - 走 `analysis.primary`

首发不要求锁死单一厂商，但必须先在 `Prompt Registry` 中为以上槽位配置明确的主模型和 fallback 模型。
