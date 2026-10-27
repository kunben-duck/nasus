# 自主构建与持续演进的系统画像

状态：目标设计，2026-09-09；已开始渐进实施，已验证部分与未完成范围见[实施记录](./implementation-progress.md)。设计条目本身不是实现完成证据。

本文是系统画像下一阶段开发的主设计。它补充现有产品需求，不表示下列能力已经上线。现状核查基于本地 `111644b` 加当前工作区；不把未提交代码、已有测试或供应商宣传当作完成证明。

## 1. 决策摘要

系统画像不是仓库摘要，也不是无限增长的聊天记忆。它是**按版本可重放、带证据与权限的系统认知和质量约束模型**：回答系统现在如何工作、业务期望是什么、哪些行为已被验证、哪里未知，以及下一步应该验证什么。

- 代码必须，需求与历史测试可选；多仓库、多文档、多测试集合是一等输入。
- 引导式入口、自然语言入口和迭代事件共用一个可恢复的构建目标，不各自实现流水线。
- Agent 可以自主发现、规划、调查、关联、校验、补齐和更新候选画像，但不能自行授权、把推测升级为业务规则或绕过正式基线审批。
- 复用开源代码知识服务，不再建设一套通用代码索引引擎。Nasus 自有部分是跨源语义、版本治理、证据关联和质量上下文。
- Codebase Memory 是首个生产候选适配器，CodeGraph 是同契约替换候选；本轮不依据宣传指标决定生产切换。现有 Tree-sitter 保留为过渡校验/降级路径，不继续扩建成完整竞争产品。
- PostgreSQL 保存正式事实、修订、关系、审批、任务和 Outbox；MinIO 保存不可变原始快照和产物。外部代码图、全文、向量、摘要均为可重建投影。
- 输出不是一个通用大 prompt，而是按用途编译的 `USDesignContext`、`TestDesignContext`、`AutomationContext`、`ExecutionContext` 和 `ReleaseContext`。

配套文档：

- [知识、版本与上下文契约](./knowledge-contracts.md)
- [开发顺序与验收方案](./delivery-and-evaluation.md)
- [开源能力评估与决策依据](./technology-evaluation.md)
- [CodeGraph 公开 SDK 防腐适配与 exweb 同源对照](./codegraph-provider-comparison.md)
- [既有质量闭环说明](./quality-closure-enablement.md)
- [固定画像的证据调查修订](./evidence-investigation-revisions.md)
- [同目标的补源计划修订](./build-plan-revisions.md)
- [原目标的追加式构建阶段](./image-plan-phases.md)
- [固定来源的构建入口与缺码恢复](./source-pinned-build-entries.md)
- [来源清单作为冻结画像的根](./manifest-rooted-projections.md)

## 2. 现状与必须解决的差距

以下是代码观察，不是完整功能或性能验收：

| 当前证据 | 已有基础 | 本次目标差距 |
| --- | --- | --- |
| `application/system_image/source_ingestion.py::_register_sources` | source 权限、原料引用、摄入状态 | 以 source_type 匹配并覆盖，需改为多 binding、多 revision，不能登记新源就清空整个项目派生事实 |
| `application/system_image/source_ports.py::CodeIntelligencePort` | provider-neutral 候选对象端口 | 目前只有 analyze，缺少 snapshot、分页、索引生命周期和能力声明 |
| `infrastructure/system_image/codebase_memory_code_intelligence.py` | 公开 CLI 调用及实体/边映射 | 关系分数固定为 0.88，部分定位为 approximate；不得用于证明精确覆盖 |
| `application/system_image/context_extraction.py::extract` | 对象、关系、指标物化 | ID seed 可能含 provider_node_id，供应商替换/行号变化的身份稳定性未获保证 |
| `domain/system_image/entity_resolution.py::CrossSourceEntityResolver` | 确定性三源关联 | 英文 token 标签相似度、每对象最多三条；不具备语义证据裁决，中英文不对称 |
| `application/system_image/service.py::_materialize_context` | PG 工作区、快照回滚、派生上下文 | 整体 replace，默认取第一个版本/基线；不是不可变多版本画像 |
| `application/system_image/quality_contexts.py::_context_projection` | 检索追踪和证据引用 | 兜底前若干项、按 ID 截断不能保证关键风险和验收标准必选 |
| `application/agent/plans.py::_compile_system_image_plan_for_project` | 按状态注册、摄入、物化、初始化 | 缺少基于知识缺口的调查任务、预算内重规划和质量完成门禁 |
| `application/system_image/system_image_models.py` | Baseline、Overlay、TaskContext、QualityProfile | 要补修订/来源清单、结构化证据、断言状态、用途 readiness；保持旧 DTO 兼容 |

已有 LangGraph/Temporal、ToolInvocationRuntime、审计、权限、SSE 和设置路由继续复用。设计不要求先重写 Agent 或 DDD 框架。

## 3. 画像需要表达什么

### 3.1 六类视图，共用一套事实

| 视图 | 核心内容 | 直接消费者 |
| --- | --- | --- |
| 系统结构 | 仓库、模块、符号、接口、依赖、部署边界 | 影响分析、开发定位 |
| 业务行为 | 角色、能力、流程、状态机、规则、不变量、失败与补偿路径 | US 与验收标准设计 |
| 数据与交互 | 数据实体、API 契约、事件、权限边界、外部依赖 | 边界/契约/集成测试 |
| 质量资产 | 测试点、场景、用例、脚本、fixture、断言、运行约束 | 用例复用、自动化生成 |
| 验证证据 | 构建版本、运行环境、结果、覆盖、失败、人工验证 | 回归与放行 |
| 认知缺口 | 不支持语言、未映射规则、冲突、低置信关联、过期证据 | Agent 下一步计划 |

模块聚类只能建议业务能力，不能直接等同 DDD bounded context。业务名词来自批准需求、明确的用户确认或带来源的候选推断；保留别名而非强行统一命名。

### 3.2 三种语义不能混淆

- `observed`：代码或运行中观察到的行为，允许它本身有 bug。
- `expected`：批准需求、契约或用户确认的预期行为，是测试 oracle 来源。
- `hypothesized`：模型提出的解释、规则或关联，必须带待确认状态。

没有需求时，允许从代码生成 characterization tests 和待确认的 US/规则草案；不得称为业务验收覆盖。代码与批准需求冲突时，保留两条断言和冲突对象，不让模型择一覆盖。

### 3.3 Readiness 是向量，不是一个分数

每个范围分别记录 `structure / behavior / traceability / automation / execution`，各自为 `ready | partial | blocked | unknown`，并附分母、缺口、证据和评估策略版本。单一 confidence 或对象数量不能替代门禁。

代码-only 可以完成结构基线，同时显示需求缺失、验收依据不足、未执行。缺少关键 oracle 不阻止结构画像发布，但阻止相应业务验收结论；缺少 fixture/环境不阻止用例草案，但阻止自动运行。

## 4. 用户体验与自主程度

### 4.1 三个入口，一种目标

1. **引导构建**：Build/Project Overview 选择项目与版本，添加至少一个代码来源，Agent 探测语言/规模/入口，展示建议范围和成本；需求/测试明确标注可跳过。
2. **自然语言发起**：“分析支付服务并建立画像”“补充这份退款 US”“更新到 v2.3”。Agent 先解析目标和已有 binding，能查得的信息不反复追问；歧义仓库、分支、业务规则才追问。
3. **持续维护**：用户启用项目维护策略后，Git/文档/测试事件触发差异评估及候选更新。事件不是审批，不直接推进正式基线。

一次交互只解决一个关键歧义。询问包含原因、候选选择、影响范围和跳过后能力缺口。例如“缺少退款时间窗的期望规则，可继续结构画像；生成验收用例前需确认”。凭据只通过专用安全 UI 登记引用，不让用户把 token 发到会话里。

### 4.2 授权边界

| 策略 | 可自主执行 | 必须停下 |
| --- | --- | --- |
| Guided，默认 | 已授权 source 的只读探测、计划建议 | 开始有成本的构建前确认范围与预算 |
| Autonomous build | 批准范围内摄入、索引、调查、候选关联、验证、自动重试 | 新源/新权限、预算追加、重大语义冲突、正式发布 |
| Continuous maintenance，显式开启 | 跟踪指定 refs、合并变更、候选修订、影响通知 | scope 扩张、规则变更、晋级审批、环境执行授权 |

所有模式都可以由用户主动发起；“自主”不等于每一步点确认。低风险重复步骤在授权 envelope 内免打扰执行。角色权限、预算、允许的 source/ref/数据出口由平台发放，模型无权修改。默认不运行未知仓库代码、安装仓库依赖或访问部署环境。

### 4.3 用户能看见的内容

复用当前 AI Studio 风格 shell、composer、设置弹层，不重新设计视觉语言。Project Overview 展示目标、计划修订、source revision、阶段、成果和缺口；Knowledge 展示能力/流程/关联/证据，不要求用户理解整个底层图。

进度来自已完成 work item / 已发现 work item，不用固定百分比伪装准确进度。新调查导致分母增长时说明“新增发现”；展示精简决策依据，不输出私有思维链。暂停、继续、取消、重试失败项复用同一个 goal，刷新后由持久化快照恢复。

## 5. Agent 构建闭环

### 5.1 编排

```text
Conversation / Guided UI / Authorized change event
  -> AgentGoal + BuildIntent
  -> inspect existing image and sources
  -> propose InvestigationPlan -> policy validation
  -> execute ready work items through ToolInvocationRuntime
  -> observe artifacts and check evidence
  -> evaluate gaps and contradictions
  -> continue / ask / replan / pause
  -> validate candidate -> human review -> publish immutable revision
```

Temporal 管生命周期、重试/取消和长任务；LangGraph 管有限状态下的规划和观察。复用现有 AgentGoal，不增加互相竞争的第二个主控制器。模型提出 schema 化计划，确定性策略验证器批准执行；checkpoint 只存控制游标，不是业务事实源。

### 5.2 计划契约

`BuildIntent`：project、目标 baseline/version、模式 initialize/enrich/refresh/repair、用户目标、source bindings、scope、autonomy_policy、预算、验收目的、expected_head。

`InvestigationPlan`：plan_id/revision、goal_id、source_manifest_id、work_items、accepted_gaps、预算分配、完成标准、decision_summary。每项 work item 必须包含：

- 要回答的问题和原因，不能只写“深入分析”。
- 输入对象/来源修订、依赖项、工具 ID 与白名单参数。
- 输出 artifact 类型和确定性验收条件。
- 允许重试次数、模型/时间/费用额度、风险级别。
- 成功时消除哪些 Gap；失败的替代路径或澄清请求。

默认 DAG 模板是起点而不是全部智能：source probe、snapshot、index、入口/依赖提取、业务候选、三源关联、缺口验证、上下文试编译、review。Agent 依据仓库结果扩展分支，例如发现消息消费者就补幂等/重试调查，发现权限中间件就补角色矩阵，发现历史支付用例就优先复用 fixture。不得离开批准范围自行遍历组织全部仓库。

### 5.3 自主调查和停止标准

下一问题候选来自未解析依赖、关键入口无流程、规则无实现、测试无 oracle、失败无关联、上下文消费者报告缺口。优先级由策略排序：发布阻断项、关键风险、受变更对象、预期消除缺口量/成本；模型解释排序，但不能删除强制项。

一次 observe 验证证据可定位、来源同 revision、类型匹配、是否重复、是否消除原问题，再决定 continue/replan。低分关系不是“必须找一个匹配”的理由；允许 no-match/unknown。

完成需要：必需代码快照成功；批准范围扫描清单完整（不支持项显式列出）；所要求的必选工件存在；关键冲突已处理或阻断；用途 readiness 有依据；剩余非阻断缺口有负责人/建议；预算内完成报告。审阅前标记 `candidate_ready`，不写“正式画像完成”。

### 5.4 预算与恢复默认值

以下是初始配置值，不是现有效能：每目标 80 个工具 work item、30 次规划/语义模型调用、20 分钟主动分析预算；索引另设文件/字节/运行上限。费用上限由管理员提供，未设置时禁止无限自主循环。达到任一上限暂停，不丢弃已验证工件。

0089 已增加新 AgentGoal 的[持久主动运行计时](./agent-active-runtime.md)：暂停输入/确认不耗时，同目标恢复保留累计预算；旧记录和 v1 检查点不倒推改写。它不代表全计划多能力费用账本、所有恢复的 owner fencing 或本节全部默认值已完成。

0092 已为新 `system_image_build`／`system_image_investigation` Goal 增加[累计工具工作约束](./knowledge-contracts.md)：原 limit 默认 80，保存计划或固定源意图可指定更小上限。实际 canonical 控制及业务工具执行前在 PG 原子预留，确认等待及同命令重放不重复扣减，独立新 attempt 消耗原额度，补源阶段不能重新领额度。超过上限或历史不可核验即暂停；旧 Goal 不伪造历史计量。一次 canonical 工作可以包含多次原生 Worker 尝试，因此该计数不证明模型次数、全部费用或独立能力授权；这些仍是本节未完成范围，不能据此将 blocked 评估晋级为 candidate_ready。

最多 3 次无新增证据且未消除 Gap 的循环后暂停；同 revision 同问题重复调用按 evidence signature 去重。指数退避重试仅覆盖暂时性 I/O，权限错误不重试，解析不支持变为 Gap，输入过大需用户缩小范围或追加预算。LLM 不可用时继续确定性索引，语义调查暂停，禁止 mock 推断混入正式画像。

工件按 `goal/work_item/input_manifest/algorithm_version` 幂等。完成检查先读业务工件，恢复不重复制造对象或重复执行副作用；租约和 fencing token 阻止旧 worker 在接管后提交。取消停止新 work item，取消正在执行的 provider 操作，已提交候选保留且不发布。外部服务不承诺 exactly-once；以至少一次调用、幂等提交和显式补偿收敛。

### 5.5 从代码结构提升到业务认知

这一步不能只把整个仓库喂给 LLM 生成 wiki，也不能只依赖名称相似度：

1. **确定性 inventory**：发现语言、包/服务、公开入口、路由、事件消费者、数据库访问、测试入口和配置边界；保存成功、排除、不支持和失败文件清单。
2. **划定调查单元**：按用户范围、入口、目录和依赖社区提出模块候选。已有架构文档可提供边界依据；聚类结果只作建议，不自动改用户的领域定义。
3. **入口驱动流程重建**：围绕一个业务目标读取入口及有证据的调用/数据/权限路径，定位条件分支、状态变更、失败返回、重试/补偿。跨服务跳转需接口/事件契约证据，图中不存在的调用不能由模型补边。
4. **形成 BehaviorSpec 候选**：输出 actor、trigger、preconditions、inputs、steps、state transitions、outputs、error paths、invariants、external dependencies、source evidence 和 unresolved points。每个字段独立标 observed/expected/hypothesized，不能给整篇摘要笼统打一个置信度。
5. **三源对齐**：需求转换为带版本/权威引用的 AC，测试转换为步骤/断言/fixture；将实现、预期和验证结果并排比较，得到支持/冲突/缺证据的可审阅结果。
6. **反向检查**：对每条关键行为尝试查找反例和缺失边界，再试编译下游上下文；若无法回答“如何触发、期望什么、怎样观察、怎么隔离测试”，新建对应 Gap，而非继续润色摘要。

示例工件：`BehaviorSpec(refund@C1)` 的 steps 引用入口和服务函数，invariant“同一业务退款只能成功一次”必须引用批准 AC；如果只有代码中的去重分支，标为 observed 去重逻辑，提出幂等规则确认问题。生成 US 草案时明确哪些规则继承、哪些是新增产品决策。

文档/表格解析结果还要经过 schema 校验和原文定位，不因 OCR 生成了文本就认为规则可靠；关键信息识别不确定时要求审阅。测试静态抽取不能导入并执行项目模块，未知 fixture 副作用单列为运行风险。源码解析、行为候选与业务批准分别计量成本和成果。

### 5.6 生命周期的可观察状态

| 构建状态 | 进入条件 | 离开条件 |
| --- | --- | --- |
| awaiting_input | 缺少必需代码、目标版本或关键歧义 | 用户补全后更新原 plan revision，不新建平行 goal |
| planned / awaiting_authorization | 计划已校验，尚需范围/预算授权 | 授权 envelope 与当前 plan digest 一致 |
| running | 有可执行 work item 且租约有效 | 所有必选工件满足、遇 gate、取消、预算或不可恢复失败 |
| paused | 需人工决定/权限/预算/消除无进展 | 记录原因和恢复条件；满足后从工件检查点继续 |
| candidate_ready / awaiting_review | 完成报告和 candidate digest 已冻结 | 批准发布、退回产生新 candidate、或取消发布 |
| completed | 指定目标达到：候选构建已交付，或正式发布已提交 | 报告必须区分 candidate_only 与 published，不把前者展示成 official |
| failed / cancelled | 不可恢复错误或取消已确认 | 显式 retry 创建新 attempt，保留原输入与审计 |

这些状态是画像任务 read model，不重新定义 Temporal/AgentGoal 的权威状态机。发布命令已提交后取消不能撤销提交；返回 published 与对应 revision，需独立受治理 rollback。用户在审阅期间编辑 source/范围会生成新 candidate，旧审批不再适用。

## 6. 初始化、增量与版本演进

### 6.1 初始化

建立 source bindings -> 冻结每个代码 commit/文件版本 -> 摄入快照 -> 索引与抽取 -> Nasus 身份映射 -> 断言及三源关联 -> 质量视图 -> 验证 -> 人工审阅 -> 创建不可变 ImageRevision 并原子推进 Official head。

没有测试/US 时只生成能力候选、缺口及 characterization 建议，不编造历史需求/覆盖率。有多份文档时保留各自权威来源与适用版本；上传时间晚不意味着业务权威更高。

### 6.2 增量维护

触发输入包括 Git commit/merge/tag、需求新修订、测试资产变化、环境契约变化、运行结果、人工修正、parser/embedding 升级。webhook 仅当项目开启维护策略才调度；验签并去重，默认 30 秒合并突发事件，5 分钟最长等待；每日 reconciliation 对照绑定 ref 弥补漏事件，周期可配置。

源 revision 变化先生成新 manifest，不覆盖正在运行的快照。按变更文件/章节/测试计算增删改，再沿 typed dependency 使派生断言、链接、摘要和上下文包 stale。重算范围包含依赖者与端点已变化的边，而非只重算修改文件。动态调用、配置/公共契约变化或依赖分析被截断时扩大到所属模块/系统，不能把查不到误判成无影响。

只变 embedding 模型时重建检索投影，不改业务事实；语义抽取策略变更重新生成候选，不静默提升旧推断。运行证据回流按 run_id 去重，只更新相关验证视图，不自动触发无限构建循环。人工否定关系作为受版本约束的负向证据保存，不能下次摄入又自动连回。

可选源刷新失败时保留它上次成功修订及“已知存在新修订但未读取”的 gap；允许代码结构更新，不能拿旧需求冒充新版本批准 oracle。该 gap 若影响当前关键 AC，则阻断对应测试验收/发布结论，而非把整个代码画像标失败。

### 6.3 三个独立轴

- **版本**：某个 immutable manifest 代表的代码/文档/测试组合。
- **审阅状态**：draft/candidate/approved/rejected。
- **时效性**：相对于哪个目标 manifest，哪些实体/关系/产物 stale。

旧正式修订永远可重放；“最新 source 有更新”只标记它不再是当前 head 的完整认知，不破坏旧版本的正确性。Git commit 是祖先偏序，不能用时间戳替代分支关系。多仓库一致性来自组合 manifest + 发布构建标识，不宣称跨仓库有天然原子 commit。

### 6.4 发布、合并与回滚

版本 overlay 绑定固定 parent revision，查询 overlay first、固定 parent fallback；删除 tombstone 阻止被父层复活。版本期间官方 head 变化时旧 overlay 不自动 rebase。合并是三方比较，代码事实取真实 merge commit 重新抽取，语义断言与人工决策逐项审阅；不得字段拼接制造从未存在的代码版本。

审批绑定 candidate digest、source manifest、policy version 和 expected Official head，任一变化原审批失效。发布执行 CAS，失败返回冲突需 rebase/review。回滚只原子切换 head 指针，审计和历史上下文不删除；回滚画像不等于回滚应用部署。细则见[版本契约](./knowledge-contracts.md#4-版本解析与一致性)。

## 7. 对下游产生可执行的指导

| 场景 | 画像必须提供 | 下游必须返回 | 阻断或降级 |
| --- | --- | --- | --- |
| US 设计 | 已有行为、角色、术语、能力边界、相似 US、现状/预期差异、影响及待确认点 | US draft、AC 列表、每条来源和变更意图 | 无批准规则时只出待确认草案，不从代码直接判定正确 |
| 测试设计 | AC、状态迁移、边界/异常、权限矩阵、契约、已验证不变量、历史用例与缺口 | 测试点->场景->用例->oracle 的 coverage matrix | 关键 AC 无 oracle 标 unknown，不用相似标题当覆盖 |
| 脚本生成 | 批准用例、端点/locator 证据、fixture、依赖版本、setup/cleanup、等待/隔离策略 | script revision、用例链接、静态检查、收集/编译报告 | 缺少目标入口或环境依赖时出待补 Blueprint，不捏造可运行脚本 |
| 运行/回归 | 固定代码/脚本/构建 revision、依赖影响、强制回归集、环境安全约束 | run evidence、每个断言结果、覆盖与失败映射 | 环境不匹配、凭据无授权、破坏性动作未批则不执行 |
| 放行 | AC 覆盖分母、关键失败、时效性、环境适配、人工豁免及审批 | 有依据的 ReleaseDecision | 未运行不是成功；未知不得计入已覆盖/通过 |

通用检索只是候选召回，必须经过用途约束、版本/ACL 过滤和完整性校验。关键安全规则、AC、未解决冲突优先于相关性排名，不允许被 token 截断丢掉。更详细输入输出及字段定义见[上下文契约](./knowledge-contracts.md#5-用途上下文包)。

## 8. 贯通示例：退款时间窗变更

以下为设计 fixture，不是生产业务事实。

| 阶段 | 行为与工件 |
| --- | --- |
| 首次代码-only | 固定支付仓库 C1，发现 POST /refund、RefundService 和重试逻辑；“24 小时可退”为 observed 候选，向用户确认业务规则；没有 AC 时不声称退款验收已覆盖 |
| 后补文档和测试 | US-17@D1 批准“24 小时内允许，重复请求只退款一次”；TC-9@T1 实际只有成功断言。关联到 AC-1/AC-2，TC-9 仅覆盖成功路径，幂等 gap 保留 |
| v2 新 US | 用户要求改为 48 小时，版本 overlay fork I1。USDesignContext 输出变更范围、旧 24 小时规则及受影响调用方，用户批准 AC 新修订 |
| 测试设计 | TestDesignContext 强制 24/48 小时边界、48 小时外拒绝、时区、重复/并发、超时补偿；每项明确 oracle，未提供的舍入规则追问 |
| 脚本生成 | AutomationContext 提供已发现的时间控制 fixture、退款 API、隔离账户、断言与清理；缺少可控时钟则暂停该边界脚本，不 sleep 两天 |
| 执行 | ExecutionContext 固定 C2、镜像 digest、脚本 S2、配置和测试数据指纹；旧 C1 的 run 只能作为历史参考，不能证明 C2 通过 |
| 失败回流 | 并发退款失败只生成 observed evidence 和 defect candidate，不把“重复扣款”学习成新的正确规则 |
| 发布 | 关键证据补齐后批准 I2，正式 head I1->I2；I1/旧用例/旧 run 保留，另一个版本仍 pin I1，显式 rebase 才变化 |

## 9. 非目标与上线约束

不承诺完整静态分析覆盖任意动态语言，不以代码图替代测试，不自动发布应用，不让 Agent 自动发现的业务规则获得产品批准。C4/架构图、wiki、索引摘要是可再生解释视图，不是第二份事实源。

下一轮实现应按配套[开发验收方案](./delivery-and-evaluation.md)逐阶段交付完整垂直链路，而不是先迁目录或扩大工具数量。每阶段都要看到真实仓库的可追溯工件、失败路径和对下游的增益；未达到评估门禁时继续使用显式受限模式，不把开发 fallback 包装为正式能力。
