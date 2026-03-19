# Nasus Assurance Studio 实施版项目计划书

## 1. 项目定义

### 1.1 项目名称
**Nasus Assurance Studio**

### 1.2 一句话定义
**通用 coding agents 帮你写代码，Nasus 帮你决定这次变更是否真的准备好上线。**

### 1.3 产品愿景
**在 agent 大规模参与研发之后，重建软件交付的质量边界。**

### 1.4 产品定位
Nasus Assurance Studio 是一个面向 AI 代码开发时代的 **质量保障与上线防护工作台**。

它的核心职责不是生成代码，而是围绕一次变更完成：
- 变更理解
- 影响识别
- 验证组织
- 证据收敛
- 结果归因
- 放行建议
- 质量知识沉淀

---

## 2. 项目目标

### 2.1 业务目标
- 降低存量系统变更的理解成本
- 提升验证方案生成质量和覆盖度
- 提高自动化资产生成与维护效率
- 为 AI 生成代码建立可验证、可审计、可放行的质量机制
- 沉淀组织级质量记忆，提升后续版本交付信心

### 2.2 技术目标
- 构建一个以 **统一上下文引擎（Unified Context Engine）** 为核心的质量保障平台
- 把代码、文档、需求、UX、历史验证资产和执行反馈统一为同一上下文系统
- 建立三层上下文体系支撑变更理解和放行决策
- 采用 **Universal Assurance Agent + Skills + Parallel Workers + Deterministic Core** 架构
- 通过明确的对象层、候选层、审批层和双基线机制避免系统画像被污染

### 2.3 MVP 目标
在 1 个存量系统、2~3 个核心模块上跑通以下闭环：
1. 项目初始化接入
2. 历史系统画像构建
3. 新版本创建与版本工作基线生成
4. 围绕需求生成验证方案
5. 多轮审核与局部重生成
6. 自动化执行与失败分析
7. 版本完成后更新官方系统基线
8. 输出上线准备度建议

---

## 3. 核心设计原则

1. **质量保障优先于测试生成**
2. **统一上下文优先于双检索暴露**
3. **系统画像是独立对象层，不等于知识原料**
4. **版本期间更新工作基线，不直接污染官方基线**
5. **会话知识默认私有，可经审批提升**
6. **可解释、可追溯、可审计优先于一次性全自动**
7. **Agent 负责规划与收敛，执行层保持确定性**

---

## 4. 核心对象模型

## 4.1 知识原料层（Raw Assets）
原料层只负责保存和索引原始输入，不直接等于系统画像。

包含：
- Git 代码仓 / 分支 / 提交范围
- US / PRD / 设计方案文档
- UX 设计图 / 原型说明
- OpenAPI / 接口文档
- 历史验证资产（用例、测试点、脑图、自动化脚本）
- 历史缺陷 / PR / Issue / MR / 执行报告
- 会话中上传的临时材料

## 4.2 系统画像对象层（Context Objects）
系统画像是独立的结构化对象层，是从原料加工后得到的认知对象。

核心实体：
- System
- Module
- Feature
- Page
- API
- CodeSymbol
- Requirement
- UXArtifact
- TestAsset
- RiskPattern
- ExternalDependency
- Role
- State

核心关系：
- contains
- implements
- described_by
- validated_by
- depends_on
- impacts
- related_to
- transitions_to

## 4.3 工作对象层（Workspaces）
围绕版本和任务派生的动态对象层。

包含：
- Version Working Baseline
- Task Context Workspace
- Quality Assurance Profile
- Session Context
- Candidate Knowledge

---

## 5. 三层上下文体系

## 5.1 历史系统画像（Historical System Baseline）
定义：
针对存量系统长期沉淀形成的、可版本化的、结构化的系统基线认知。

内容：
- 模块、特性、页面、API、服务、角色、状态
- 外部依赖
- 历史风险热点
- 历史验证资产关联
- 历史演进轨迹

作用：
- 为新任务提供长期基线
- 作为后续一切版本工作的起点

## 5.2 当前任务上下文（Task Context Workspace）
定义：
围绕某次需求或变更动态构造的有效工作区。

内容：
- 当前需求/版本/分支信息
- 当前相关特性和模块
- 当前相关代码、文档、UX、验证资产证据
- 当前约束、当前风险、当前审核意见

作用：
- 为当前任务的影响分析和验证设计提供主上下文

## 5.3 质量画像（Quality Assurance Profile）
定义：
围绕某次变更形成的验证语义模型，用于指导测试、自动化、审核和放行判断。

内容：
- 验证范围
- 验证计划
- 场景集
- 用例集
- 前置条件
- 断言目标
- 自动化建议
- 人工探索建议
- 回归范围
- 风险收敛状态
- 放行建议

关系：
```text
历史系统画像
  + 当前任务输入
  + 实时证据
= 当前任务上下文

当前任务上下文
  + 质量策略规则
  + 历史验证资产
  + 风险模型
  + 审核反馈
= 质量画像
```

---

## 6. 基线与治理模型

## 6.1 四层治理对象
### 项目（Project）
代表一个存量系统。
包含：
- 官方系统基线
- 官方知识源
- 版本列表
- 权限体系

### 版本（Version）
代表一次受控变更周期。
包含：
- 版本官方输入
- 版本工作基线
- 版本共享知识
- 版本级任务与会话

### 会话（Session）
代表某个用户围绕某个版本开展的一次具体工作。
包含：
- 会话上下文
- 用户上传材料
- 临时分析结果
- 会话私有知识

### 基线（Baseline）
分为：
- **Official Baseline**：官方系统基线，长期稳定
- **Version Working Baseline**：版本工作基线，版本期间动态更新

## 6.2 知识分级
### 1）官方知识（Official Knowledge）
来源：
- 管理员创建项目时导入的材料
- 管理员创建版本时导入的材料
- 已审批通过的长期知识

可进入：
- Official Baseline

### 2）版本共享知识（Version Shared Knowledge）
来源：
- 当前版本中经确认对所有会话有价值的补充知识

可进入：
- Version Working Baseline

### 3）会话私有知识（Session-only Knowledge）
来源：
- 普通用户在会话中上传或整理的临时材料

默认：
- 只在当前会话可见
- 不直接影响任何基线

### 4）候选知识（Candidate Knowledge）
来源：
- 系统识别到可能有长期价值的会话知识或版本知识

需要：
- 审批后才能进入 Version Shared Knowledge 或 Official Baseline

## 6.3 基线更新规则
### 版本进行中
允许更新：
- Version Working Baseline
- Version Shared Knowledge
- Candidate Knowledge

### 版本完成 / 上线后
经审批后更新：
- Official Baseline

总原则：
**会话知识默认不进官方基线；版本期间更新工作基线；版本完成后更新官方系统基线。**

---

## 7. 统一上下文引擎（Unified Context Engine）

这是 Nasus 的核心技术中枢。

## 7.1 目标
把代码、文档、需求、UX、历史验证资产、执行反馈统一加工成可用的上下文对象，对上只暴露统一上下文能力。

## 7.2 设计原则
- 不把代码检索和知识检索直接暴露给上层
- 不追求一次性生成绝对正确的系统画像
- 采用“原料索引 + 候选对象 + 已确认对象 + 任务实时补证”的模式
- 系统画像对象必须带证据、置信度和状态

## 7.3 内部模块
### 1）Source Connectors
负责接入：
- Git 仓
- 文档系统
- UX 文件
- OpenAPI
- 历史验证资产
- 缺陷 / PR / Issue / MR / 执行报告

### 2）Code Intelligence Backend
负责：
- 代码解析与符号抽取
- 定义 / 引用 / 调用链
- 文件与模块关系
- 变更影响候选

实现建议：
- Tree-sitter：多语言 AST 与增量解析
- OpenGrok / 同类代码导航引擎：源码搜索与交叉引用

### 3）Knowledge Intelligence Backend
负责：
- 文档切块与解析
- 需求、设计、UX、验证资产理解
- 文档级元数据与检索索引

### 4）Anchor Extraction
负责抽取跨源统一锚点：
- 模块名
- 特性名
- 页面名
- API 路径
- 角色、状态、配置项
- 文案关键词

### 5）Entity Resolution & Feature Linking
负责：
- 把来自不同来源的对象归并到统一 Feature / Module / Requirement / TestAsset 上
- 生成候选关系
- 计算置信度

### 6）Context Assembler
负责：
- 组装 Historical System Baseline
- 组装 Task Context Workspace
- 组装 Quality Assurance Profile

### 7）Context Object Store
负责保存：
- Candidate Context Objects
- Trusted Context Objects
- Baseline Snapshots
- Version Working Baselines

## 7.4 对上暴露的能力
对上不再提供 search_code / search_docs，而统一提供：
- get_feature_context(feature_or_requirement)
- build_task_context(task_input)
- build_quality_profile(task_context)
- assess_release_readiness(task_context, quality_profile, execution_evidence)

---

## 8. 总体系统架构

### 8.1 分层架构
1. Experience Layer
2. Intelligence Orchestration Layer
3. Domain Intelligence Layer
4. Unified Context Engine
5. Three-Layer Context System
6. Integration Fabric（防腐层）
7. Infrastructure Providers

### 8.2 架构图
```text
┌──────────────────────────────────────────────────────────────┐
│          Nasus Assurance Studio Experience Layer            │
│       Web Portal | CLI | API | Nasus Assistant             │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│        Intelligence Orchestration Layer                     │
│ Universal Assurance Agent | Skill Registry | Workflow      │
│ Worker Scheduler | Merge/Score Engine | Approval Control   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│             Domain Intelligence Layer                       │
│ Baseline | Impact | Verification Planning | Scenario | Case│
│ Automation | Failure Analysis | Healing | Release Advice   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│               Unified Context Engine                        │
│ Source Connectors | Code Intelligence | Knowledge Intel    │
│ Anchor Extraction | Entity Resolution | Context Assembler  │
│ Context Object Store | Retrieval Planner                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Three-Layer Context System                     │
│ Historical System Baseline                                  │
│ Task Context Workspace                                      │
│ Quality Assurance Profile                                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│             Integration Fabric (IACL)                       │
│ Asset Ingestion | Execution | Storage | Review/Policy      │
│ Provider Contracts | Adapter Registry                      │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│            Infrastructure Providers                         │
│ Git / Docs / OpenAPI / OpenGrok / Object Store / PG /      │
│ Playwright / Queue / Scheduler                             │
└──────────────────────────────────────────────────────────────┘
```

---

## 9. 领域服务设计

## 9.1 Baseline Service
负责：
- 项目初始化基线构建
- 版本工作基线生成
- 官方基线更新

## 9.2 Change Impact Service
负责：
- 识别需求与已有特性的关系
- 分析影响模块、页面、API、外部依赖
- 生成回归影响范围

## 9.3 Verification Planning Service
负责：
- 生成验证计划
- 决定自动化 / 手工 / 联合验证策略
- 推荐优先级和风险收敛路径

## 9.4 Scenario Design Service
负责生成：
- 主流程场景
- 异常场景
- 权限场景
- 边界场景
- 联动场景

## 9.5 Case Design Service
负责生成：
- 结构化用例
- 前置条件
- 测试数据建议
- 断言目标

## 9.6 Automation Service
负责：
- 生成 Playwright 资产
- 组织自动化执行配置

## 9.7 Failure Analysis Service
负责：
- 读取执行证据
- 识别失败类别
- 生成归因结论

## 9.8 Healing Service
负责：
- 生成 patch 建议
- 回放 patch
- 走 patch 审核流

## 9.9 Release Advice Service
负责：
- 结合质量画像、执行结果、审核结论
- 输出上线准备度建议

---

## 10. Agent / Skills / Workers 设计

## 10.1 架构模式
采用：
**Universal Assurance Agent + Skills + Parallel Workers + Deterministic Core**

## 10.2 Universal Assurance Agent
职责：
- 理解用户目标
- 规划阶段与步骤
- 路由 skills
- 调度 workers
- 汇总结果
- 推动审核与放行判断

## 10.3 Skills
建议首版 Skills：
- baseline.build
- baseline.refresh
- impact.analyze
- verification.plan
- scenario.generate
- case.generate
- quality.profile.build
- automation.generate
- execution.run
- failure.analyze
- healing.propose
- release.assess

## 10.4 Workers
### Context Workers
- frontend_context_worker
- backend_context_worker
- document_context_worker
- api_context_worker
- historical_asset_worker

### Impact Workers
- diff_impact_worker
- requirement_impact_worker
- dependency_impact_worker

### Scenario Workers
- mainflow_scenario_worker
- exception_scenario_worker
- permission_scenario_worker
- boundary_scenario_worker
- integration_scenario_worker

### Failure Workers
- locator_failure_worker
- timing_failure_worker
- assertion_failure_worker
- env_failure_worker

---

## 11. 项目、版本、会话与协作设计

## 11.1 项目初始化接入
由管理员创建项目，并导入：
- Git 仓
- 历史文档
- 历史 US
- 设计方案文档
- UX 设计图
- OpenAPI
- 历史验证资产

系统自动完成：
- 原料接入与索引
- 结构候选抽取
- 特性候选关联
- 初版 Historical System Baseline 生成

管理员审核后形成：
- Official Baseline v1

## 11.2 版本创建
由管理员或授权角色创建版本，并导入：
- 本版本官方 US
- 本版本设计文档 / UX
- 分支 / 提交范围 / OpenAPI 变更

系统自动完成：
- 从 Official Baseline fork 出 Version Working Baseline
- 初版版本风险识别
- 版本级 Change Set 建立

## 11.3 会话创建
任意授权用户可在版本下创建会话。

会话特点：
- 会话私有知识默认不进入基线
- 可上传临时文档、补充说明、会议纪要、个人验证思路
- 可请求将高价值内容提升为 Candidate Knowledge

## 11.4 协作与共享
引入两个版本级对象：
### Feature Graph
用于表示长期系统结构和特性关系。

### Change Graph
用于表示当前版本内：
- 多个 US 的关联
- 多个会话的重叠
- 同一特性上的交叉影响
- 共享风险与共享验证任务

系统应支持：
- 自动提示相关会话
- 自动识别同一 Feature 上的重叠工作
- 允许把多个相关会话合并为共享验证任务

---

## 12. 存量系统接入与基线化流程

## 12.1 原则
- 原料是 append-only
- 系统画像是物化对象
- 版本工作基线是动态派生视图
- 官方基线更新受审批控制

## 12.2 流程
### 阶段 1：项目初始化接入
- 导入原料
- 建立索引
- 生成结构候选对象

### 阶段 2：初始基线构建
- 生成模块、页面、API、服务、基础依赖图
- 生成特性候选和关系候选

### 阶段 3：管理员校正
- 修正关键模块/特性划分
- 确认高价值关系
- 标记高优先级风险

### 阶段 4：Official Baseline v1
- 形成第一版官方系统画像

### 阶段 5：版本增量运行
- 版本期间只更新 Version Working Baseline
- 会话知识先留在 Session 或 Candidate 层

### 阶段 6：版本完成后回写
- 审批通过的高价值知识更新回 Official Baseline

---

## 13. 前端产品形态（实施要求）

## 13.1 产品风格
全部采用 **Gemini AI Studio 风格**：
- Prompt-first
- Agent-centered
- Workspace-oriented
- 右侧上下文/控制面板
- 默认 Dark
- 支持 Light / Dark 切换

## 13.2 一级导航
- Home
- Tasks
- Knowledge
- Runs
- Settings

## 13.3 核心页面职责
### Home
发起与继续任务入口。

### Tasks
核心工作区，用于：
- 查看当前任务上下文
- 查看质量方案
- 多轮审核与重生成
- 推进到执行与放行判断

### Knowledge
查看：
- 历史系统画像
- 特性上下文
- 证据来源

### Runs
查看：
- 自动化资产
- 执行结果
- 失败分析
- patch 审核

### Settings
管理：
- 项目初始化
- Provider
- 版本权限
- 主题与策略

---

## 14. MVP 技术栈与工程结构

## 14.1 推荐技术栈
### 后端
- Python
- FastAPI
- Workflow Runtime（LangGraph 风格）

### 前端
- React
- TypeScript
- Tailwind
- Zustand / Redux Toolkit
- TanStack Query

### 执行层
- Node.js / TypeScript
- Playwright Test

### 存储
- PostgreSQL
- MinIO

### 索引与解析
- OpenGrok（代码搜索/交叉引用）
- Tree-sitter（AST / 增量解析）

## 14.2 目录结构建议
```text
nasus/
  apps/
    portal/
    api/
    runner/

  core/
    orchestrator/
    skills/
    workflow/
    worker_runtime/
    merge_engine/

  domain/
    baseline/
    task_context/
    quality_profile/
    impact/
    verification_planning/
    scenario/
    case/
    automation/
    failure_analysis/
    healing/
    release_advice/

  context_engine/
    connectors/
    code_intel/
    knowledge_intel/
    anchor_extraction/
    entity_resolution/
    context_assembler/
    object_store/

  governance/
    baseline_governance/
    candidate_knowledge/
    approvals/

  fabric/
    asset_ingestion/
    execution/
    storage/
    review_policy/
    provider_registry/

  schemas/
    raw_assets/
    baseline/
    task_context/
    quality_profile/
    candidate/
    run_result/
    patch/

  infra/
    docker/
    k8s/
    observability/
```

---

## 15. 研发阶段规划（精简版）

## Phase 0：对象与协议固化
- 定义 Raw Assets / Context Objects / Workspaces schema
- 定义 Official Baseline / Version Working Baseline / Candidate Knowledge 模型
- 定义 Unified Context Engine 接口

## Phase 1：项目初始化接入
- 实现原料接入
- 实现代码与文档索引
- 实现初始基线构建
- 实现管理员审核基线

## Phase 2：版本与会话机制
- 实现版本创建
- 实现 Version Working Baseline
- 实现 Session-only / Version Shared / Candidate Knowledge 流转
- 实现 Change Graph 与 Feature Graph

## Phase 3：质量方案生成
- 实现影响分析
- 实现验证计划
- 实现场景和用例生成
- 实现 Draft / Refined / Validated

## Phase 4：执行与放行建议
- 实现自动化资产生成
- 实现执行结果采集
- 实现失败分析与 patch 建议
- 实现 release.assess

## Phase 5：治理与沉淀
- 实现基线回写
- 实现审批流
- 实现版本完成后的 Official Baseline 更新

---

## 16. 用户旅程（精简版）

1. 用户进入 Nasus，选择项目与版本
2. 用户输入需求或上传材料，创建任务
3. 系统基于历史系统画像和当前输入构建任务上下文
4. 系统生成质量方案（影响分析、验证计划、场景、用例、自动化建议）
5. 用户多轮审核并补充意见，系统局部重生成并收敛
6. 系统执行自动化并分析失败
7. 系统给出上线准备度建议
8. 高价值知识经过审批沉淀回版本工作基线或官方系统基线

---

## 17. 成功指标

### 产品指标
- 项目初始化接入时间
- 质量方案采纳率
- 自动化候选采纳率
- 失败归因准确率
- 上线准备度建议可信度

### 平台指标
- Official Baseline 稳定性
- Version Working Baseline 收敛效率
- Candidate Knowledge 审批通过率
- Unified Context Engine 证据召回质量
- 多会话协作关联准确率

---

## 18. 最终定版

Nasus Assurance Studio 的当前实施版本应被定义为：

**一个面向 AI 代码开发时代的质量保障与上线防护工作台。它通过统一上下文引擎、三层上下文体系、双基线治理机制和多轮审核收敛机制，把原始知识原料加工为可验证、可审计、可放行的质量行动与质量判断。**

其核心口号是：

> **通用 coding agents 帮你写代码，Nasus 帮你决定这次变更是否真的准备好上线。**

其核心愿景是：

> **在 agent 大规模参与研发之后，重建软件交付的质量边界。**

