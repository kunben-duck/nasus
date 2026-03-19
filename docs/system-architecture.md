# 整体架构与部署设计

## 0 文档优先级说明

- 本文用于说明 Nasus 的系统分层、部署单元和实现约束。
- 若本文与 [docs/final-feature-spec.md](/Users/uben/project/project/Nasus/docs/final-feature-spec.md) 存在冲突，以最终特性说明书定义的产品能力和默认规则为准。
- 尤其在 Agent 能力边界上，本文保留当前实现语义中的分层约束；最终产品能力以“Agent 可原生触发检索与执行，但必须受策略、审计和回放约束”为准。

## 1 设计目标与边界
- 目标：构建一个**质量保障与上线防护平台**，采用“中心控制面 + 桌面执行端”的混合架构，用统一上下文加治理机制替代传统的测试生成器，确保每次变更都能被理解、验证、执行、归因并给出放行建议。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L14)
- 技术边界：核心能力是上下文建模、领域服务编排与治理，执行层（Playwright）和原料（Git/docs/UX）通过防腐层隔离接入，避免将执行细节耦合在决策路径。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L346)
- 质量原则：统一上下文、物化系统画像、版本期间只更新工作基线、会话知识默认私有，追求可解释、可追溯、可审计。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L57)
- 形态原则：Web 端是集中式控制面和协作面，Desktop Client 是个人设备上的执行面和本地权限面；两端共享同一任务、证据和审计模型，但本地私有数据默认不上传，上传和同步必须受策略与用户授权控制。

## 2 核心对象模型
- Raw Assets（原料层）保存 Git、文档、UX、OpenAPI、历史验证资产、缺陷等输入，强调 append-only 和证据化。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L69)
- Context Objects 是可推理的系统画像（System/Module/Feature/Page/API/CodeSymbol/Requirement/UXArtifact/TestAsset/RiskPattern/ExternalDependency/Role/State），带关系（contains/implements/depends_on/impacts 等）与证据。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L83)
- Workspaces（版本工作基线、Task Context Workspace、Quality Assurance Profile、Session Context、Candidate Knowledge）将版本、任务与会话捆绑，为每次变更构建“动态上下文”。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L111)
- 治理对象分四层：Project/Version/Session/Baseline，知识分级为 Official/Version Shared/Session-only/Candidate，确保变更期间只更新工作基线，版本完成后经审批回写官方基线。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L189)
- 设备对象补充为 `Device`、`Desktop Client`、`Local Session`、`Local Capability`、`Sync Cursor`，用于描述个人终端、设备信任、桌面权限和同步状态。

## 3 七层系统架构
1. Experience Layer：Web Portal、Desktop Client、CLI、API、Nasus Assistant 作为人机入口。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L346)
2. Intelligence Orchestration Layer：`Central Orchestrator Agent`、`Edge Desktop Agent`、Skill Registry、Workflow、Worker Scheduler、Merge/Score Engine、Approval Control 负责规划、路由、并发和审批。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L348)
3. Domain Intelligence Layer：Baseline/Impact/Verification Planning/Scenario/Case/Automation/Failure/Healing/Release Advice 等领域服务产出决策。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L370)
4. Unified Context Engine：Source Connectors、Code/Knowledge Intelligence、Anchor Extraction、Entity Resolution、Context Assembler、Context Object Store，统一加工上下文对象并对上只暴露 `get_feature_context`、`build_task_context`、`build_quality_profile`、`assess_release_readiness`。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L267)
5. Three-Layer Context System：Historical System Baseline、Task Context Workspace、Quality Assurance Profile 支撑任务理解与质量画像。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L123)
6. Integration Fabric（防腐层）：Asset Ingestion、Execution、Storage、Review/Policy、Provider Contracts、Adapter Registry，隔离具体 Git、文档系统和执行器差异。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L393)
7. Infrastructure Providers：Git、Docs、OpenAPI、OpenGrok、Object Store、PostgreSQL、Playwright、Queue、Scheduler 等外部能力。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L403)

## 4 逻辑架构与运行平面

- **控制面（Control Plane）**：Web Portal + API Gateway + Policy/Approval Service，负责角色验证、资源授权、任务划分、组织治理和统一监控，构成 `settings` + `approval` 中央治理层。
- **智能面（Intelligence Plane）**：Unified Context Engine + Domain Intelligence Services + `Central Orchestrator Agent` + `Skill Registry` + `Merge/Score`，负责构建 `Task Context` + `Quality Profile`，并为 Web 与桌面端提供可直接消费的编排能力。
- **执行面（Execution Plane）**：Web Execution Fabric + Runner + Failure/Healing + Execution Evidence Store，负责网页端工具、Playwright/MCP 调用、确定性执行、失败归因和 patch 建议。
- **边缘/桌面面（Edge/Desktop Plane）**：Desktop Client + `Edge Desktop Agent` + Local Capability Gateway + Local Cache + Sync Pipeline，负责本地权限执行、本地资源访问、桌面动作、浏览器/应用控制、离线缓存与回传同步。
- **数据面（Data Plane）**：PostgreSQL + MinIO + OpenGrok + Tree-sitter + Audit/Event Store，提供事实源、证据归档和检索能力。

运行平面说明：

- `Control Plane` 为最终特性说明书定义的“Agent 可触发”能力提供治理和策略入口。
- `Intelligence Plane` 内部分为两层：`Durable Workflow Runtime` 负责长生命周期任务、审批等待、重试和恢复；`Agent Graph Runtime` 负责单个任务内部的阶段推进、Skill 路由、人机节点和局部并行。
- `Execution Plane` 负责承接 Web 触发的网页端工具、Playwright 和 MCP 请求。
- `Edge/Desktop Plane` 负责承接经授权的本地桌面动作和本地推理。
- `Data Plane` 对所有行为提供事实源、审计与证据保留。

所有平面最终共享统一任务模型、统一 `Run` 模型和统一 `evidence` 模型。

## 5 核心组件职责矩阵

| 组件 | 主要职责 | 依赖 |
| --- | --- | --- |
| Central Orchestrator Agent | 接收任务、规划阶段、路由中心侧或边缘侧 Skill、调度 Worker、提交候选结论 | Skill Registry、Durable Workflow Runtime、Agent Graph Runtime、Approval Control |
| Edge Desktop Agent | 在桌面端执行本地上下文感知、本地 Skill 编排、本地证据增强和本地候选判断生成 | Local Capability Gateway、Sync Pipeline、Policy Service |
| Durable Workflow Runtime | 承接长生命周期任务、审批等待、超时、重试、恢复与跨端同步编排 | API/Orchestrator、Queue、Approval Control |
| Agent Graph Runtime | 在单个任务内部执行阶段规划、Skill 路由、并行 Worker 编排和人机节点控制 | Skill Registry、Worker Runtime、Merge/Score |
| Skill Registry | 管理 `SkillDefinition`、标记 `scope=central|edge|either`、声明风险等级和确认要求 | Policy Service、Worker Runtime、Context Assembler |
| Worker Runtime | 调度 Context/Impact/Scenario/Failure 等 Worker，收集 partial result 并提交 Merge/Score | Context Assembler、Domain Services、Execution Fabric |
| Unified Context Engine | 统一感知 Raw Assets、上下文对象、Evidence，提供 `get_feature_context`、`build_task_context`、`build_quality_profile` | Source Connectors、Code/Knowledge Intelligence、Entity Resolution、Context Object Store |
| Merge/Score + Conflict Resolver | 合并中心端与桌面端 `AgentDecision`、识别冲突、输出 `MergedResolution` 建议 | Agent Graph Runtime、Approval Control、Execution Evidence |
| Approval Control & Release Advice | 评估证据、驱动 Candidate 晋级、提供放行建议、记录审批链、确认正式结论 | Quality Profile、Execution Evidence、Policy Service、Merge/Score |
| Automation Service & Runner | 转换验证方案->Playwright 资产、调度 Runner、采集 Logs/Screenshots，承接 Web 端 Playwright/MCP 执行 | Workflow Runtime、Queue/Scheduler、Failure Analysis |
| Desktop Client | 承载本地任务视图、权限弹窗、离线队列、同步状态和本地 Skill 面板 | Edge Desktop Agent、Local Capability Gateway、Sync Pipeline |
| Local Capability Gateway | 暴露本地受控能力，执行前检查授权、策略、设备状态和敏感操作边界 | Desktop Client、Policy Service、Credential Vault |
| Sync Pipeline | 同步本地任务、证据、审计、设备状态和缓存补传 | Desktop Client、Sync Cursor、Policy Service、Event Store |

## 6 关键对象、状态与事件流

| 对象 | 典型状态 | 触发事件 | 下游影响 |
| --- | --- | --- | --- |
| `Project` | 未接入 -> 接入中 -> 待审核 -> 已建档 | Provider 接入、材料完成、管理员确认 | 启动版本建模、提供 Governance |
| `Version` | 草稿 -> 进行中 -> 待收口 -> 已收口 | Fork Official Baseline、提交 Review、审批通过 | 推动 Session、触发 Change Set |
| `Session` | 未开始 -> 进行中 -> 暂停 -> 结束 | 用户创建、任务提交、执行完成 | 驱动 Task Context、Execution Runner |
| `Task Context Workspace` | 构建中 -> 完成 -> 失效 | Agent/Skill 执行、证据补全 | 供 `Quality Profile`、自动化执行使用 |
| `Quality Assurance Profile` | Draft -> Reviewed -> Approved | Verification/Scenario/Case 完成、人工确认 | 触发 automation.run 与 release.assess |
| `AgentDecision` | provisional -> merged -> approved / rejected | Center/Edge 推理完成、Conflict Resolver、Approval Control | 推动正式任务结论、正式放行或知识晋级 |
| `MergedResolution` | pending_merge -> ready_for_approval -> approved / rejected | Merge/Score 完成、Approval Control 决策 | 写入正式任务状态、Release Advice、Knowledge Resolution |
| `Candidate Knowledge` | 待审批 -> 版本共享 -> 官方 | Approval Control 决策 | 修改 Version Shared / Official Baseline |
| `Run` | 待执行 -> 执行中 -> 成功/失败/重试/pending_merge | Automation Service 或 Desktop Trigger 触发 | 归因、Approval、Release Advice |
| `Device` | 未注册 -> 已注册 -> 已信任 -> 已降级/已吊销 | Desktop Client 注册、设备校验、管理员策略更新 | 触发本地能力、约束同步范围、决定是否允许离线缓存补传 |
| `Local Session` | 待同步 -> 本地进行中 -> 已补传 -> 已关闭 | 桌面动作、本地缓存生成、网络恢复 | 进入 Sync Pipeline、回传 evidence/run、更新中心端状态 |
| `Task` | draft -> analyzing -> pending_merge -> ready_for_review -> executing -> ready_for_release -> completed | Skill invoke、AgentDecision 提交、Run 完成、Merge/Approval 完成 | 影响任务 UI、审批流和知识晋级 |

| 事件流 | 描述 |
| --- | --- |
| 项目接入事件 | Provider/Material ingestion -> Raw Assets indexed -> Historical System Baseline snapshot |
| 版本 fork 事件 | `Official Baseline` 被 `Version Working Baseline` fork，`Change Set` 生成并入队 Agent |
| 会话入队事件 | 用户选版本、创建 Session，向 Agent 提供材料 -> `Task Context` 触发 Skill 运行 |
| 执行证据事件 | Runner 完成 `Run` 后推送 Logs/Screenshots -> Failure/Healing/Event Store append |
| 桌面执行事件 | Desktop Client 在授权后执行本地动作 -> Edge Desktop Agent 生成 evidence/run -> Sync Pipeline 补传到中心端 |
| 冲突合并事件 | Center/Edge 产生不同 `AgentDecision` -> Task/Run/Knowledge 进入 `pending_merge` -> Merge/Score 生成 `MergedResolution` |
| 知识晋级事件 | Approval Control 判断 -> Candidate 升级 -> Baseline Service 写回 |

## 7 核心数据流
1. 项目接入：管理员导入原料（Git/文档/US/设计/UX/OpenAPI/历史验证资产），系统完成索引、结构候选抽取、特性关系关联，输出 Historical System Baseline；管理员审核后形成 Official Baseline v1。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L528)
2. 版本创建：管理员/授权角色导入版本 US/文档/UX/OpenAPI/提交范围，系统从 Official Baseline fork 出 Version Working Baseline，建立 Change Set，并做初步风险识别。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L547)
3. 会话与协作：授权用户在 Web 或 Desktop Client 中开 Session，上传材料；Web 侧侧重协作与网页端工具，Desktop 侧侧重本地权限动作。系统用 Feature Graph/Change Graph 提示相关会话、识别重复和共享风险，并允许合并验证任务。Session-only 知识默认不进基线，可申请晋升为 Candidate。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L558)
4. Task Context 构成：`历史系统画像 + 当前任务输入 + Web/桌面实时证据 + 设备状态`。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L170)
5. Quality Assurance Profile 构成：`当前任务上下文 + 质量策略规则 + 历史验证资产 + 风险模型 + 审核反馈 + 设备/权限约束`，推动影响分析、验证计划、场景、用例、自动化建议。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L177)
6. 执行与归因：Web 端通过 Playwright/MCP 执行网页操作，Desktop Client 通过 Local Capability Gateway 执行本地动作；两者都生成统一 `Run(execution_channel=web_runner|desktop_local)` 和 evidence，Failure Analysis 识别失败类型，Healing 生成 patch，Release Advice 输出上线准备度建议。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L444)
7. 冲突与合并：中心端与桌面端可独立推理并提交 `AgentDecision`，但都只能先写入 `provisional` 结果；若结论冲突，则任务、放行或知识对象进入 `pending_merge`，由 `Merge/Score + Approval Control` 生成正式 `MergedResolution`。
8. 治理闭环：高价值 `Candidate Knowledge` 先经审批进入 `Version Shared Knowledge`，版本完成后再将经过确认的版本知识回写 `Official Baseline`；桌面执行端产生的本地证据按策略回传，不默认进入组织级知识库。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L615)

## 8 Agent / Skill / Worker 协作
- 本节描述当前推荐的系统实现约束，不等同于最终产品能力承诺。若与最终特性说明书冲突，以最终特性说明书为准。
- 架构模式：`Central Orchestrator Agent + 完整 Edge Desktop Agent + Skills + Parallel Workers + Deterministic Core`。中心端负责全局任务规划、跨系统上下文和正式治理流编排；桌面端负责本地上下文感知、本地 Skill 编排和本地证据增强。
- 运行时采用“`外层耐久工作流 + 内层图编排`”：
  - `Durable Workflow Runtime` 负责长任务、审批等待、超时、重试、恢复和跨端同步。
  - `Agent Graph Runtime` 负责阶段推进、Skill 路由、局部并行和人机节点。
- Skill 是一等对象，统一由 `Skill Registry` 管理，并标记：
  - `scope=central`：如 `baseline.build`、`impact.analyze.global`、`verification.plan`、`release.assess`。
  - `scope=edge`：如 `context.local.inspect`、`fs.local`、`browser.local`、`desktop.app`、`artifact.collect`。
  - `scope=either`：如 `failure.analyze`、`healing.propose`、`context.enrich`、`evidence.summarize`。
- Skill 下沉范围默认限定为“本地上下文 + 本地执行”，桌面端不承担组织级审批、正式知识晋级和正式基线回写。
- Workers 仍按 Context（frontend/backend/document/API/historical assets）、Impact（diff/requirement/dependency）、Scenario（mainflow/exception/permission/boundary/integration）、Failure（locator/timing/assertion/env）分池，并行产出局部结果交给 `Merge/Score` 收敛。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L498)
- 中心端与桌面端都可独立推理，但都只能提交 `AgentDecision(status=provisional)`；冲突时统一进入 `pending_merge`，由 `Merge/Score + Approval Control` 产出正式 `MergedResolution`。
- 协作链路：`Workflow` 定阶段 -> `Agent Graph Runtime` 路由 Skill -> `Worker Runtime` 并行任务 -> `Merge/Score` 合并候选结果 -> `Approval Control` 决定是否晋升知识、放行或进入下一阶段，保证执行层确定性与结果可审计。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L474)

## 9 部署架构与运行单元
### 9.1 计划书明确的部署线索
- Experience Layer 对应 `portal`（Web UI/CLI/API）和 `desktop client`，Domain/Orchestration Layer 集中在 `api/orchestrator` 服务，Integration Fabric 封装 Asset/Execution/Storage 接入，Infrastructure Providers 提供 Git/Docs/OpenGrok/PostgreSQL/MinIO/Playwright/Queue。文档本身并未明确拆分服务进容器，只给出分层与所需组件。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L346)
- Storage/Index 明确选 PostgreSQL、MinIO、OpenGrok、Tree-sitter，Execution 明确选 Node.js + Playwright，桌面端则需要本地运行时、设备信任和同步管道，指引部署时优先满足这些单元。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L673)

### 9.2 基于计划书的最小推断
- 推断部署模型：五类中心运行单元 `portal`（React 前端）、`api/orchestrator`（FastAPI）、`workflow-service`（`Durable Workflow Runtime`，默认采用 Temporal 或等价实现）、`worker-runtime`（异步 worker 池）、`runner`（Playwright 执行 job）和 `sync-service`（统一设备/会话同步）；再加一类边缘运行单元 `desktop client`（本地进程、托盘服务或系统服务，内含 `Edge Desktop Agent`）。中心和边缘通过队列、SSE 和同步管道连接；存储层为 PostgreSQL + MinIO，代码索引/解析由 OpenGrok + Tree-sitter 实现。
- 任务流：Web 或 Desktop 发起任务 -> API/Agent 组装统一 Task Context -> `workflow-service` 启动耐久任务 -> `worker-runtime` 生成质量方案和自动化属性 -> Web 触发 Playwright/MCP，Desktop 触发 Local Capability Gateway -> 双端都可提交 `AgentDecision` -> 统一 `Run` 和证据回写 PostgreSQL/MinIO -> 冲突时进入 `pending_merge` -> `Approval Control` 决定基线走向。
- 运行环境建议：中心端先以 Docker 模式部署 4 到 5 个运行单元，再按需求扩展到多 worker 池；桌面端按平台打包分发、设备注册和策略下发，支持离线缓存与补传。若中心检索性能逼近瓶颈，再考虑引入独立检索/向量层。这是受计划书 `infra/` 目录和 Phase 0-5 演进顺序启发的部署建议。

## 10 首轮建设到后续演进

- 建议先跑通 Phase0-3（对象协议、项目/版本初始化、任务上下文、质量方案生成），Phase4 补自动化执行与失败分析，Phase5 加审批与基线回写。[计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md#L764)
- 随着成熟度提升，可把 worker 按 Context/Impact/Scenario/Failure 进一步分池、把 runner 做成隔离 job、把 OpenGrok/Tree-sitter 解析从实时路径剥离、仅在召回质量需要时再引入专用向量/检索层。[文档未明示，此为可演进建议]

## 11 可靠性、审计、权限与可观测性

- **权限管控**：所有 Project/Version/Session/Knowledge/Approval 操作须通过 RBAC，且必须在 `Settings` 模块明确配置。
- **审计事件**：Control Plane、Intelligence Plane、Execution Plane 的关键事件（任务创建、Skill 调度、执行、上下文晋级、审批）必须写入不可修改的 Audit Store。
- **证据保留**：所有 `Run` 的日志、截图、trace、Failure 归因、patch 建议、审批决定永远 append-only，并关联 `Task Context`/`Version`。
- **Skill 可见性与执行权**：Skill 可以在 Web 与 Desktop 中显式展示，但是否可执行必须同时满足 `RBAC + policy + capability grant`。
- **交互通道**：Portal 到 `api/orchestrator` 的写操作采用 REST；任务、执行、审批的长时状态回传采用 SSE；Runner/Worker 与 Orchestrator 之间走队列和内部事件，不直接暴露给前端。Desktop Client 与中心端通过同步管道回传 `Run`、`evidence` 和设备状态。
- **执行隔离**：Runner 运行在隔离环境，依赖 `Environment Manager` 的短期凭证；Desktop Client 只能在本地授权能力范围内执行本地动作，Agent 不能直接绕过 `Local Capability Gateway` 操控本地资源。
- **远程桌面动作**：中心端可下发桌面动作，但必须经用户确认或命中预授权策略；任何未经授权的本地动作不得执行。
- **正式事实来源**：中心端与桌面端都可推理，但都只能提交 `provisional` 候选结果；正式事实必须由 `Merge/Score + Approval Control` 写入。
- **本地数据边界**：本地私有数据默认不上传，桌面端生成的文件、文件夹、截图、应用状态和临时缓存只有在显式策略和用户授权下才允许同步到中心端；管理员可以统一监控任务、设备和会话状态，但不会自动获得本地全量数据访问权。
- **可观测性**：为 Control/Intelligence/Execution 平面提供统一链路追踪、运行指标、队列延迟和失败率；任何 Worker 重启必须能恢复任务状态。
- **数据恢复**：PostgreSQL 级数据采用定期备份，Execution Evidence 通过 MinIO 版本控制；在 worker 异常时，Workflow Runtime 必须可重入。
- **策略与备份**：Promotion Gate、Release Advice Gate、Baseline 回写 Gate 的状态必须持久化，并且有明确回滚/override 流程。

## 12 环境分层与部署建议

| 环境 | 目标 | 默认组成 | 要求 |
| --- | --- | --- | --- |
| `local` | 单开发者调试与联调 | `portal` `desktop client` `api/orchestrator` `worker-runtime` `runner` `PostgreSQL` `MinIO` | 支持最小数据集、假 Provider、低成本重置 |
| `dev` | 多人共享开发环境 | 本地同构部署 + 共享 `OpenGrok` / 文档索引 + 桌面端测试设备 | 支持真实任务流、事件追踪、最小审批流、同步验证 |
| `staging` | 预发布验证 | 完整中心平面 + 桌面同步链路 + 审计/策略/执行网关 | 接近生产配置，验证权限、审批、回放、恢复、设备信任 |
| `prod` | 企业正式运行 | 私有化部署、隔离执行环境、桌面客户端分发、备份与监控全量开启 | 强制审计、强制审批、证据长期保留、设备分级管理 |

部署建议：

- 默认以 Docker Compose 或等价容器编排作为中心端 `local/dev` 基线，桌面端以安装包、签名程序或企业软件分发方式交付。
- `staging/prod` 推荐迁移到 k8s 或企业内部等价编排平台，并将 `worker-runtime`、`runner`、索引服务和 `sync-service` 拆成独立扩缩容单元。
- `prod` 环境中 `runner` 必须使用隔离网络与短期凭证，不得与控制面共享高权限凭据；Desktop Client 需要设备注册、设备信任、远程策略下发和离线补传能力。

## 13 桌面执行与同步

- 桌面客户端分发应支持按操作系统、设备组和组织策略进行安装与升级，设备首次接入必须完成注册、信任和最小权限初始化。
- Edge Desktop Agent 负责本地推理和本地 Skill 编排，Local Capability Gateway 负责在每次本地动作前校验用户授权、策略、设备状态和敏感操作边界。
- Sync Pipeline 负责把本地产生的 `run`、`evidence`、审计事件、设备心跳和缓存补传到中心端；离线时必须允许本地缓存，在线后按同步游标补传。
- 远程策略下发应支持按组织、项目、版本和设备组控制可执行能力，本地动作默认最小权限，敏感权限必须显式授权并可撤销；中心端远程下发的桌面任务必须在桌面端完成确认或命中预授权后执行。
- 桌面端同步回中心的内容应区分 `任务状态`、`执行证据`、`产物引用` 和 `设备元数据`，本地私有内容不应因为同步机制而被自动提升为组织级可见内容。

## 14 开发先后依赖

| 阶段 | 主要交付 | 依赖 | 交付物 |
| --- | --- | --- | --- |
| P0 | 对象/协议固化 | 技术栈选型、final feature spec | Schema、Context API、Baseline Governance |
| P1 | 项目/版本接入能力 | Source Connectors、Context Engine | Asset Ingestion Pipeline、Historical Baseline Generator |
| P2 | 会话/任务/质量方案 | Intelligence Plane + Agent | Session API、Task Context Builder、Verification Plan |
| P3 | 双端执行与失败 | Automation Service、Runner、Desktop Client、Failure Worker | Playwright Runner Jobs、Local Capability Gateway、Run Evidence Store、Failure Reports |
| P4 | 放行与沉淀 | Approval Control、Release Advice、Sync Pipeline | Release Decision UI、Candidate Approval Workflow、Baseline Writer、Desktop Sync Governance |
| P5 | 运维与治理 | Audit Store、Policy Service、Observability | RBAC 配置、审计看板、监控体系 |

- 建议先完成 P0-P3，形成项目接入、任务分析和双端执行闭环；在此基础上再补齐 P4-P5 的审批、沉淀和运维治理能力。
- 随着成熟度提升，可把 worker 按 Context/Impact/Scenario/Failure 进一步分池、把 runner 做成隔离 job、把 OpenGrok/Tree-sitter 解析从实时路径剥离、仅在召回质量需要时再引入专用向量/检索层。[文档未明示，此为可演进建议]

上文内容可直接供设计评审和部署讨论使用，若需要我还能把它转成图示版或工程落地清单。
