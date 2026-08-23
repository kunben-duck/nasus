# Nasus Model Provider 与推理运行时设计

## 1. 文档定位

本文定义 Nasus 如何接入底层模型 Provider，覆盖 Chat LLM、Embedding 和 Rerank 三类模型能力，并定义 Prompt 管理、上下文裁剪、token 计量、模型路由和降级策略。

## 2. 设计目标

- Provider 可替换，不把 Agent、系统画像检索或质量生成绑定到单一模型厂商。
- Prompt 可版本化、可评审、可回滚。
- 推理预算可观测、可限额、可按项目/版本/任务追踪。
- 长上下文优先通过结构化上下文裁剪解决，而不是盲目堆 token。
- 模型故障或预算耗尽时必须可降级。
- Chat LLM、Embedding、Rerank 必须能独立配置、独立测试、独立审计，不能共用一个含义模糊的“模型配置”。

## 3. 总体结构

`Conversation Orchestrator / Agent Service / Agent Graph / Skills`
-> `Agent Memory Manager`
-> `Model Gateway`
-> `Provider Adapters`
-> `Model Runtime`

组成：

- `Model Gateway`
  - 统一模型调用入口
  - 负责 Chat LLM、Embedding、Rerank 的路由、预算控制、重试、降级
- `Prompt Registry`
  - 管理系统 prompt、tool selection prompt、merge prompt、failure analysis prompt 等模板
- `Context Packaging`
  - 由 `Agent Memory Manager` 负责，把 `Working Memory / Conversation Memory / Project Long-term Memory / Candidate Memory / TaskContext / QualityProfile / Evidence / Baseline` 组装成模型输入
- `Token Metering`
  - 负责 token 统计、预算和告警
- `Provider Adapters`
  - OpenAI / Anthropic / Gemini / OpenAI-compatible / 私有模型等适配层

## 3.1 系统模型配置路由

系统设置中必须提供三条独立模型 route：

| route | 用途 | 主要调用方 | 是否允许 fallback |
| --- | --- | --- | --- |
| `chat` | 主会话、Conversation Orchestrator、Agent Loop THINK、质量生成 Skill | Agent Service / Tool Runtime / Skill Runtime | 允许 fallback 到 deterministic response，但必须标记 `runtime_mode=fallback`；staging/prod 的自由文本写规划必须 fail closed |
| `embedding` | RawAssetChunk、ContextObject 摘要、测试资产、失败模式的向量化 | System Image / UCE / Retrieval Pipeline | 允许任务排队或降级到 keyword-only，但必须标记 embedding stale/excluded |
| `rerank` | hybrid retrieval 候选重排、上下文组装候选排序 | Retrieval Pipeline / Context Assembler | 允许降级到 rule-based fusion，但必须写入 RetrievalRun |

每条 route 的配置模型固定为：

- `model_route=chat|embedding|rerank`
- `model_preset=system_default|custom`
- `custom_provider_kind=openai_compatible|openai|gemini|anthropic`
- `custom_base_url`
- `custom_model_name`
- `custom_api_key`
- `runtime_mode=live|fallback`
- `active_provider_status`

规则：

- API key 必须加密持久化，任何 read API 不得返回明文。
- `system_default` 来自部署环境变量或平台托管配置；`custom` 来自用户在 Settings 中保存的配置。
- 顶层兼容字段 `model_provider / model_name / custom_model` 只代表 `chat` route，不能被 Embedding 或 Rerank 复用。
- Agent 主会话只读取 `chat` route；系统画像向量化只读取 `embedding` route；hybrid retrieval 重排只读取 `rerank` route。
- 修改 `embedding` route 后，相关 `EmbeddingRecord` 必须按 `embedding_model + embedding_version + embedding_dimension` 标记 stale 并进入重建流程。
- 修改 `rerank` route 不改变正式事实对象，但会影响后续 `RetrievalRun` 的候选排序和 `RerankRecord`。

### 3.1.1 system_default 环境变量

首个正式版本必须支持部署级 `system_default` route，不允许把组织级 Provider 密钥写入代码或作为默认种子数据落库。

| route | provider env | base URL env | model env | API key env |
| --- | --- | --- | --- | --- |
| `chat` | `NASUS_DEFAULT_PROVIDER` | `NASUS_DEFAULT_BASE_URL` | `NASUS_DEFAULT_MODEL` | `NASUS_DEFAULT_API_KEY` |
| `embedding` | `NASUS_EMBEDDING_PROVIDER` | `NASUS_EMBEDDING_BASE_URL` | `NASUS_EMBEDDING_MODEL` | `NASUS_EMBEDDING_API_KEY` |
| `rerank` | `NASUS_RERANK_PROVIDER` | `NASUS_RERANK_BASE_URL` | `NASUS_RERANK_MODEL` | `NASUS_RERANK_API_KEY` |

OpenAI-compatible provider 允许使用共享 fallback：

- `NASUS_OPENAI_COMPATIBLE_BASE_URL`
- `NASUS_OPENAI_COMPATIBLE_API_KEY`

解析规则：

- route-specific env 优先于共享 OpenAI-compatible env。
- `chat` route 服务主会话和 Agent Loop，不得复用 `embedding` 或 `rerank` route 的模型。
- `embedding` 和 `rerank` route 的 provider 状态必须独立暴露给 Settings UI。
- 缺少任一必需值时，该 route 必须进入 `runtime_mode=fallback`，并在 `active_provider_status.reason` 中说明缺失项。
- `.env.example` 只能使用占位符，真实 API key 只能通过本地 `.env`、部署 Secret 或 Settings 自定义配置注入。

## 4. Provider 抽象

最小接口：

- `list_models()`
- `invoke_chat()`
- `invoke_json()`
- `count_tokens()`
- `supports_tool_calling()`
- `supports_reasoning()`
- `supports_streaming()`

Provider 不能直接暴露给业务层；业务层只依赖 `Model Gateway`。业务代码不得绕过 route 配置直接读取 API key 或拼接 provider URL。

Embedding adapter 至少需要支持：

- `embed_texts(texts, model, dimensions?)`
- `embed_query(query, model, dimensions?)`
- `dimension(model)`

Rerank adapter 至少需要支持：

- `rerank(query, candidates, model, top_k)`
- `supports_explain_reason()`
- `fallback_score(query, candidates)`

## 5. Chat LLM 模型分层

`chat` route 内部建议继续按能力用途分成 4 类：

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

正式实现使用两张 PostgreSQL 表：

- `prompt_definitions`：以 `prompt_id + version` 为不可变主键，保存模板、schema 引用、
  安全规则引用和内容哈希。同版本内容哈希发生变化时启动失败，必须发布新版本。
- `prompt_selections`：独立保存每个 `prompt_id` 的 active version，用于灰度切换和回滚，
  不通过覆盖历史模板完成切换。

启动时允许幂等注册受版本控制的内置模板；这属于运行时契约初始化，不属于 demo 数据
seed。Agent runtime guardrail、Conversation Reply、Query Tool Reply、Planner、Replanner 和
质量资产生成必须在每次调用前读取 active definition，并将实际 `prompt_id + version`
写入 `LLMCall`。业务服务不得用硬编码 Prompt 冒充某个已登记版本。

V1 首批注册：

- `agent_runtime_guardrails`
- `agent_conversation_reply`
- `platform_query_tool_reply`
- `agent_loop_planner`
- `agent_loop_replanner`
- `quality.scope.generate`
- `quality.scenario.generate`
- `quality.case.generate`
- `automation.generate`

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
- 所有上下文窗口必须由 `Agent Memory Manager` 统一组装，业务服务不得自行拼接 prompt
- `LLM Structured Planner` 必须直接消费 `AgentMemoryContext`，而不是单独构造 planner-only prompt 上下文。
- 结构化 Planner 的 system prompt 可以追加 planner 专用约束，但必须保留 `AgentMemoryContext.system_prompt` 中的 agent-first、工具边界和治理边界。

Context Packaging 步骤固定为：

1. 绑定空间上下文：`project/version/session/us/task`
2. 绑定当前 `AgentGoal / AgentStep / ToolInvocation`
3. 绑定当前工具上下文：`tool_id / required_context`
4. 读取 working memory 和最近消息
5. 读取 conversation summary checkpoint
6. 提取相关系统画像片段和长期记忆
7. 提取最近执行与证据摘要
8. 注入候选记忆和治理约束
9. 计算 token 预算
10. 超预算时执行裁剪：
   - 保留最新和最高置信度证据
   - 对长文档和长日志先生成 summary
   - 对不影响当前工具的上下文做裁剪
   - 永远保留高风险工具 gate / policy 约束

## 8. Token 计量与预算

Token 统计维度至少包括：

- `conversation_id`
- `tool_invocation_id`
- `agent_goal_id`
- `agent_step_id`
- `swarm_run_id`
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

`chat` route 的确定性降级必须区分请求来源和副作用：

- 本地开发与测试环境允许使用确定性 Planner 验证完整工具链。
- staging/prod 中，主会话的自由文本只允许降级为直接回答、澄清或只读查询计划。
- 若自由文本原本会产生任意写工具或 `AgentGoal`，Provider 不可用、超时、输出非法或 schema 校验失败时必须返回 `planner_provider_unavailable`，不得创建领域事实或工具调用。
- 用户已在 UI 中明确点击、携带受支持的 `canonical_action_id`、且消息内容匹配固定版本 Tool Contract 的 canonical action 可以走确定性入口；不得仅凭自然语言文案猜测来源。该入口仍必须经过 RBAC、confirmation、approval 和 policy gate。
- 已经持久化并通过策略校验的 `AgentGoal` 在 Replanner 暂时不可用时可以保留原计划，但不得凭降级逻辑追加新的写步骤。

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

正式 V1 采用独立 `llm_calls` 事实表，而不是把调用详情塞入通用 JSON 日志。
`chat / embedding / rerank` 三条 route 均由 `Model Gateway` 在返回结果前写入
审计记录，并补充：

- `purpose`、`route`、`runtime_mode`、`reason`
- `project_id / version_id / conversation_id / agent_goal_id / tool_invocation_id`
- `task_id`、`model_calls`、`usage_source`
- `selected_provider / selected_model_name`，用于区分目标路由与实际 fallback
- `input_item_count / output_item_count`
- `request_hash / response_hash`，用于去重和排障但不泄露正文

原始 Prompt、原始模型输出和 API key 不进入 `llm_calls`。Prompt 正文由版本化
Prompt Registry 管理；业务产出进入各自领域对象和 Evidence，只有在独立的数据分级
策略允许时才可持久化原文。平台管理员可通过 `GET /v1/llm-calls` 按 route 和关联
事实查询脱敏记录。

敏感内容默认不完整落日志；原始 prompt 和原始输出应按策略分级存储。

## 11. 工程默认值

- 所有模型调用必须经过 `Model Gateway`
- 所有模型调用前必须经过 `Agent Memory Manager` 的上下文组装
- Prompt 必须版本化
- 工具规划优先使用结构化输出链路
- token 预算必须先于模型调用检查
- Provider 故障不能直接让主工作流失控，必须走降级路径
- Settings 必须能独立保存并测试 `chat / embedding / rerank` 三条 route。
- `chat` route 连接测试必须真实调用目标模型的轻量 prompt。
- `embedding` route 连接测试必须优先执行 provider adapter 轻量向量化探测；若 provider 暂无 adapter，只能返回配置级状态并明确说明。
- `rerank` route 连接测试必须优先执行 provider adapter 样例重排探测；若 provider 暂无统一接口，返回配置级状态并把真实探测交给 retrieval job。
- 自定义 active route 的 `live` 状态必须来自已保存模型的最近一次真实连接测试；连接
  失败需回写 `last_test_result` 并立即将 route 标记为 `fallback`。仅配置了 base URL、
  model 和 API key 不得作为 live 证据。

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
