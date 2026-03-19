# Nasus Assurance Studio

## 项目简介
Nasus Assurance Studio 是针对 AI 助手参与开发后留下的质量风险而设计的**质量保障与上线防护工作台**。它的核心任务不是生成代码，而是围绕一次变更完成变更理解、影响识别、验证组织、证据收敛、结果归因、放行建议和质量知识沉淀。

当前仓库处于方案设计阶段，核心内容以架构设计、部署设计和前后端方案文档为主，目标是在正式开工前先把系统边界、实现路径和技术选型讲清楚。

## 核心价值与边界
- **质量保障优先于测试生成**：平台聚焦变更认知和决策，Agent 可以原生触发检索与执行能力，但所有高风险行为都必须受策略、审计与回放约束。
- **统一上下文+双基线**：通过 Raw Assets、Context Objects、Task Context Workspace 等对象层与 `Official / Version Shared / Session-only / Candidate` 知识分级，保证会话噪音不会污染官方基线。
- **治理与审批闭环**：Project/Version/Session/Baseline 四层治理对象+Approval Control 推进 Candidate Knowledge 的晋级，确保可追溯、可审计。
- **双端 Agent 协作**：采用 `Central Agent + Edge Agent + Skills + Workers + Deterministic Execution` 的混合形态，Web 端与 Desktop 端都可参与任务推理与执行。
- **不是代码生成器**：所有输出都服务于上线准备度建议和质量判断，执行层由 Playwright 资产在 runner 端完成，平台只提供调度与证据汇总。

## 用户旅程
1. 管理员在 `Settings` 中初始化项目，导入 Git、文档、历史验证资产，系统完成原料索引与初版 `Historical System Baseline`。
2. 创建版本时从 `Official Baseline` fork 出 `Version Working Baseline`，并导入本版本 US、设计与 OpenAPI 变更，建立版本级 Change Set 与初步风险视图。
3. 授权用户在 `Home/Tasks` 启动会话，上传材料并在 `Tasks` 中查看 `Task Context Workspace`，系统用历史画像、实时证据与策略规则产生 `Quality Assurance Profile`。
4. 普通用户在 `Tasks` 多轮审核溯源材料、触发 impact.analyze、verification.plan、scenario.generate 等 Skill 推出验证方案；Skill 是产品一等对象，但是否可执行由 `RBAC + policy + capability grant` 控制，过程中 `Knowledge` 提供证据与 Feature Graph/Change Graph 支撑协作。
5. `Runs` 页面展示 automation.generate 产出的 Playwright 资产、执行结果、失败分析与 patch 建议；Desktop 端也可在本地完成受控执行，两端都可独立推理和执行，但都只能先提交候选结果。
6. Release Advice/Approval Control 输出上线准备度建议；当中心端与桌面端结论冲突时，任务进入 `pending_merge`，由 `Merge/Score + Approval Control` 形成正式结论。`Candidate Knowledge` 默认先晋级到 `Version Shared Knowledge`，版本收口并审批通过后再回写 `Official Baseline`，形成质量沉淀。

## 简版整体架构
1. **Experience Layer**：Web Portal/Desktop Client/CLI/API/Nasus Assistant 为入口。
2. **Intelligence Orchestration Layer**：`Central Agent + Edge Agent + Skills + Workers + Deterministic Execution` 负责规划各阶段、路由 Skill、调度 Worker、合并结果、推动审批。
3. **Domain Intelligence Layer**：Baseline、Impact、Verification Planning、Scenario、Case、Automation、Failure Analysis、Healing、Release Advice 九大服务构成业务面。
4. **Unified Context Engine**：Source Connectors + Code Intelligence + Knowledge Intelligence + Anchor Extraction + Entity Resolution + Context Assembler + Context Object Store，产出 `Historical Baseline / Task Context / Quality Profile`。
5. **Integration Fabric**：隔离 Git/Docs/OpenAPI、执行器、存储与策略，为上层提供统一能力。
6. **Infrastructure Providers**：PostgreSQL、MinIO、OpenGrok、Tree-sitter、Playwright、Queue/Scheduler 等底层组件。

## 简版部署架构
- `portal`：React/TypeScript 前端应用，负责 Home/Tasks/Knowledge/Runs/Settings 五个核心工作区。
- `api/orchestrator`：Python + FastAPI + durable workflow（默认 Temporal）+ LangGraph，承载中心侧 Agent 编排、Skill Registry、Worker Scheduler、Merge/Score、Approval Control 与领域服务。
- `worker-runtime`：并行运行 context/impact/scenario/failure 等 worker，异步消费任务队列并产出质量方案与验证资产。
- `runner`：Node.js/TypeScript + Playwright Test 的隔离执行层，执行 automation.generate 并回写执行证据。
- `desktop-client`：Electron + React + TypeScript + local-agent-runtime 的本地执行端，承接 Edge Agent、本地权限动作、离线队列和同步回传。
- `storage`：PostgreSQL 用于对象模型和治理状态，MinIO 存 Raw Assets、执行产物；OpenGrok + Tree-sitter 负责代码索引与解析。
- `queue/scheduler`：承接 `worker-runtime` 的调度与 `runner` 任务触发。具体产品选型尚未在计划书中写死，但运行模型已明确要求异步调度和确定性执行；正式结论仍走中心端 merge/approval 主线。

## 文档导航
- [项目计划书](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md)：原始实施版计划书，包含对象模型、治理规则、阶段规划和产品形态。
- [最终特性说明书](/Users/uben/project/project/Nasus/docs/final-feature-spec.md)：定义最终产品能力、角色旅程、默认规则和治理要求，是当前产品行为的最高优先级文档。
- [系统架构与部署设计](/Users/uben/project/project/Nasus/docs/system-architecture.md)：详细说明整体架构、数据流、协作模型、部署单元和演进路径。
- [前后端方案设计](/Users/uben/project/project/Nasus/docs/frontend-backend-design.md)：详细说明技术栈选型、页面职责、后端分层、执行层和阶段实施建议。
- [ux/index.html](/Users/uben/project/project/Nasus/ux/index.html)、[ux/styles.css](/Users/uben/project/project/Nasus/ux/styles.css)、[ux/app.js](/Users/uben/project/project/Nasus/ux/app.js)：当前前端 demo 与后续正式开发的样式、布局和交互基线。
- [前端视觉与交互规范](/Users/uben/project/project/Nasus/docs/frontend-visual-style.md)：高层视觉说明文档，作为 `ux/` 原型的补充，不替代 `ux/` 目录的实现基线。
