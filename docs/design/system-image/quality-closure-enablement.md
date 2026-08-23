# 系统画像长期方案：支撑质量闭环

## 1. 文档定位

本文定义系统画像如何长期服务 Nasus 的质量闭环。

它补充回答一个关键问题：

> 系统画像如何真实帮助新增特性的验证点识别、测试用例构建、自动化脚本构建、运行回归和上线质量判断，并保证历史功能不受影响。

本文不替代 [Context Engine 设计](./context-engine.md)、[知识摄入管线](./ingestion-pipeline.md) 和 [基线与分支规则](./baseline-and-branching.md)。它在这些设计之上，定义系统画像到质量闭环的转换层。

## 2. 核心结论

系统画像不能只做代码分析，也不能只做知识检索。

长期方案必须把系统画像建设成质量上下文控制层，持续维护以下关系：

```text
业务需求 / US
  -> 验收标准 / 业务流程 / 角色权限
  -> 模块 / 页面 / API / 数据对象 / 外部依赖
  -> 历史测试场景 / 用例 / 自动化脚本 / 执行证据
  -> 历史失败 / 风险模式 / 放行规则
```

只有这条链路稳定存在，系统画像才能支撑后续质量闭环：

- 识别新增特性需要验证什么
- 判断哪些历史功能可能被影响
- 生成覆盖风险的测试场景和用例
- 生成可维护的自动化脚本
- 选择最小但足够的回归集
- 汇总执行证据并形成上线建议
- 把本次版本产生的新知识沉淀回长期基线

## 3. 长期能力分层

系统画像长期分为 6 层。

### 3.1 Source Layer

负责接入原始事实来源。

V1 一等 source：

- 代码仓库
- 历史 US 文档
- 历史测试用例和自动化脚本

长期增强 source：

- OpenAPI / 接口描述
- UX / 设计稿 / 页面截图
- 缺陷记录
- 执行日志
- 线上监控与告警
- 发布记录和回滚记录

要求：

- source 必须 append-only，可回放。
- 每次 source 变化必须形成 checkpoint。
- source 本身不是系统画像，只是画像的证据来源。

### 3.2 Intelligence Layer

负责从 source 中抽取结构化候选。

代码理解：

- 文件、模块、包、服务
- 类、函数、方法、组件
- API route、页面 route、事件处理器
- import、call、dependency、external service
- selector、fixture、test helper、page object

需求理解：

- US 编号、标题、描述
- 验收标准
- 主流程、异常流程、权限路径
- 业务实体、角色、数据状态
- 风险词和边界条件

测试资产理解：

- 测试场景
- 测试用例
- 自动化脚本入口
- 断言
- 测试数据
- 依赖环境
- 覆盖对象
- 历史执行结果

执行证据理解：

- Run 状态
- 失败类型
- 日志、截图、trace、视频
- failure fingerprint
- flaky 迹象
- 修复建议和人工结论

### 3.3 Entity Resolution Layer

负责把跨 source 的候选实体归并成正式或候选系统对象。

输入：

- code symbol anchor
- requirement anchor
- test asset anchor
- API / page / flow anchor
- historical failure anchor

归并信号：

- 名称、路径、路由、接口、schema 的强匹配
- US 文本、用例标题、模块名的语义匹配
- 历史人工确认
- 执行证据中的共同失败对象
- 测试脚本中的页面/API 调用

输出：

- 高置信度对象进入 `ContextObject`
- 中低置信度对象进入 candidate
- 冲突对象进入 `pending_merge`

### 3.4 Context Graph Layer

负责维护正式系统画像图谱。

核心对象：

- `ContextObject`
- `ContextRelationship`
- `ContextObjectOverlay`
- `QualityMetricSnapshot`
- `Baseline`

关键关系：

- `US -> impacts -> Module / API / Page`
- `AcceptanceCriteria -> verifies -> TestCase`
- `AutomationScript -> covers -> API / Page / Module`
- `CodeObject -> depends_on / calls -> CodeObject`
- `Run -> evidenced_by -> ExecutionEvidence`
- `FailureReport -> points_to -> CodeObject / TestCase / Environment`
- `RiskPattern -> applies_to -> US / Module / Flow`

约束：

- 每个对象和关系都必须带 `source_refs`、`confidence`、`freshness_at`、`baseline_id`。
- 正式图谱不能直接由 Agent 文本输出写入。
- 版本期间只写 overlay，不直接污染 Official Baseline。

### 3.5 Quality Context Layer

负责把系统画像转成质量闭环可直接消费的上下文。

主要产物：

- `FeatureContext`
- `ChangeImpactContext`
- `TaskContext`
- `QualityProfile`
- `RegressionProfile`
- `CoverageMatrix`

这些对象不是简单上下文文本，而是结构化质量输入。

它们必须回答：

- 这次 US 涉及哪些系统对象
- 哪些验收标准还没有对应验证
- 哪些历史测试资产可复用
- 哪些历史功能可能被影响
- 哪些风险模式需要额外验证
- 哪些回归测试必须执行
- 哪些证据足以支撑上线判断

### 3.6 Quality Action Layer

负责把质量上下文转成可执行质量动作。

主要产物：

- `VerificationPointSet`
- `ScenarioSet`
- `CaseSet`
- `AutomationBlueprint`
- `RunPlan`
- `RegressionSuite`
- `ReleaseReadinessInput`

这些产物进入质量闭环主体模块，由对应工具生成、审核、执行和沉淀。

## 4. 从新增特性到验证点识别

### 4.1 输入

新增特性验证点识别的输入至少包括：

- `USWorkItem`
- 验收标准
- 版本变更范围
- Git delta
- 相关 `ContextObject`
- 相关历史测试资产
- 历史失败和风险模式
- 版本 overlay

### 4.2 识别逻辑

系统画像应按以下顺序识别验证点：

1. 从 US 验收标准抽取必须验证点。
2. 从变更代码识别受影响模块、API、页面和数据对象。
3. 从依赖图识别间接受影响对象。
4. 从历史测试资产识别已有覆盖和缺口。
5. 从历史失败识别风险热点。
6. 从角色、权限、数据状态和异常流程识别边界验证点。
7. 从外部依赖和接口契约识别集成验证点。

### 4.3 输出

`VerificationPoint` 至少包含：

- `verification_point_id`
- `title`
- `source=acceptance_criteria|code_change|dependency|historical_failure|risk_pattern|manual`
- `linked_us_id`
- `linked_context_object_refs`
- `risk_reason`
- `priority=must|should|optional`
- `verification_type=functional|regression|permission|data|integration|negative|performance`
- `suggested_assertions`
- `evidence_requirement`
- `existing_coverage_refs`
- `coverage_gap`

### 4.4 质量要求

- 每条验收标准至少映射到一个 `must` 验证点。
- 影响核心路径、支付、权限、数据一致性、外部依赖的验证点默认提升优先级。
- 只有文本相似但缺少 source 或证据的验证点必须进入 candidate，不得直接成为正式结论。

## 5. 从验证点到测试用例构建

### 5.1 输入

- `VerificationPointSet`
- `QualityProfile`
- 历史测试用例
- 历史失败模式
- 现有自动化脚本
- 项目测试模板
- 数据和环境约束

### 5.2 生成策略

测试用例生成不能只让 LLM 从 US 文本自由发挥。必须由系统画像约束生成范围。

生成顺序：

1. 按 `must` 验证点生成主流程用例。
2. 按风险点生成异常和边界用例。
3. 按角色权限生成权限用例。
4. 按受影响依赖生成集成用例。
5. 按历史失败生成回归用例。
6. 按已有测试资产识别可复用或需要更新的用例。
7. 按覆盖矩阵补齐缺口。

### 5.3 输出

`TestCase` 至少包含：

- `case_id`
- `verification_point_id`
- `scenario_id`
- `title`
- `preconditions`
- `steps`
- `expected_results`
- `test_data_hint`
- `assertion_type`
- `priority`
- `automation_suitability`
- `linked_context_object_refs`
- `linked_existing_case_refs`
- `evidence_requirement`

### 5.4 覆盖矩阵

系统必须生成 `CoverageMatrix`：

```text
AcceptanceCriteria
  -> VerificationPoint
  -> Scenario
  -> TestCase
  -> AutomationScript
  -> Run
  -> Evidence
```

质量闭环不能只统计用例数量，必须统计覆盖链是否闭合。

## 6. 从测试用例到自动化脚本构建

### 6.1 输入

- `TestCase`
- 相关页面/API/组件 ContextObject
- 现有自动化脚本和测试模板
- selector / route / fixture 信息
- 项目编码规范
- 历史 flaky 信息

### 6.2 自动化蓝图

系统画像应先生成 `AutomationBlueprint`，再生成脚本。

`AutomationBlueprint` 至少包含：

- `target_case_id`
- `recommended_framework`
- `test_file_path`
- `page_objects_or_helpers`
- `fixture_strategy`
- `selector_strategy`
- `api_setup_or_mock_strategy`
- `assertion_plan`
- `cleanup_plan`
- `flaky_risk`
- `reuse_existing_script_refs`

### 6.3 脚本生成约束

自动化脚本生成必须遵循：

- 优先复用现有测试模板和 helper。
- 优先使用稳定 selector、role、test id 或项目约定。
- 不得硬编码易变文案、随机等待和不稳定时间。
- 每个断言必须能回链到验证点或验收标准。
- 生成脚本必须带可解释的覆盖对象。
- 对高 flaky 风险脚本，默认进入人工审核。

### 6.4 输出

`AutomationAsset` 至少包含：

- `script_ref`
- `case_refs`
- `covered_context_object_refs`
- `framework`
- `entry_command`
- `data_requirements`
- `environment_requirements`
- `assertion_refs`
- `review_status`

## 7. 运行与回归选择

### 7.1 回归目标

回归选择的目标不是“跑越多越好”，而是：

- 新增特性必须充分验证。
- 受影响历史功能必须被保护。
- 高风险历史失败必须被覆盖。
- 执行成本可控。
- 证据足以支持上线判断。

### 7.2 RegressionProfile

系统画像必须根据变更生成 `RegressionProfile`。

输入：

- Git delta
- affected ContextObjects
- dependency graph
- historical failure hotspots
- existing test coverage
- release risk policy

输出：

- `smoke_targets`
- `must_run_regression_targets`
- `should_run_regression_targets`
- `optional_targets`
- `excluded_targets`
- `risk_reason`
- `estimated_runtime`

### 7.3 选择算法

回归选择按以下规则：

1. 所有新增特性 `must` 验证点必须进入执行计划。
2. 直接受影响代码对象覆盖的历史用例必须进入 `must_run`。
3. 间接受影响依赖路径进入 `should_run`。
4. 最近失败、flaky、核心业务链路提升优先级。
5. 无源证据或低置信关系不直接阻断，但必须提示人工确认。
6. 关键路径缺少自动化时，必须生成手工验证建议或阻断项。

### 7.4 RunPlan

`RunPlan` 至少包含：

- `run_scope`
- `target_cases`
- `target_scripts`
- `execution_order`
- `environment`
- `data_setup`
- `risk_coverage_summary`
- `expected_evidence`
- `fallback_manual_checks`

## 8. 保证历史功能不受影响

### 8.1 历史保护对象

系统画像必须识别历史保护对象：

- 核心业务流程
- 高价值页面和 API
- 高风险模块
- 历史失败热点
- 关键权限路径
- 高复用组件
- 外部依赖契约
- 已批准质量规则

### 8.2 历史影响判断

当新增特性进入版本时，系统画像必须回答：

- 哪些历史对象直接被修改
- 哪些历史对象通过依赖关系被间接影响
- 哪些历史测试资产能保护这些对象
- 哪些历史保护对象缺少当前可执行测试
- 哪些历史失败模式可能复现

### 8.3 阻断规则

以下情况应进入 `needs_evidence` 或 `blocked`：

- 新增特性影响核心路径，但无对应测试证据。
- 受影响历史功能无自动化或手工验证建议。
- 历史失败热点被命中但未执行相关回归。
- 关键 API / 页面 / 权限路径缺少断言。
- 失败归因仍为 unknown 且影响高风险对象。
- pending_merge 未解决但影响放行结论。

## 9. 质量指标与上线判断

### 9.1 指标分层

系统画像向质量闭环输出四类指标：

- `change_impact`
- `coverage_quality`
- `execution_health`
- `release_readiness`

### 9.2 change_impact

至少包含：

- changed files
- changed modules
- affected APIs
- affected pages
- affected US
- affected historical tests
- dependency depth
- critical path hit

### 9.3 coverage_quality

至少包含：

- acceptance criteria coverage
- verification point coverage
- scenario coverage
- case coverage
- automation coverage
- regression coverage
- evidence coverage

### 9.4 execution_health

至少包含：

- run success rate
- failure severity
- flaky count
- unresolved failure count
- unknown failure count
- evidence completeness

### 9.5 release_readiness

输出：

- `ready`
- `conditional`
- `needs_evidence`
- `blocked`

判断依据：

- 新增特性验证链是否闭合。
- 受影响历史功能是否有回归证据。
- 失败是否已归因和处理。
- 高风险项是否有审批或人工确认。
- 候选知识和基线回写是否清晰。

## 10. 反馈闭环与知识沉淀

### 10.1 执行结果回流

每次 Run 完成后，系统画像必须吸收：

- 执行状态
- 通过/失败用例
- 失败 fingerprint
- 证据引用
- 人工归因
- 修复建议
- flaky 标记

### 10.2 候选知识

以下内容只能先进入 candidate：

- 新发现的系统关系
- 新风险模式
- 新失败模式
- 新验证策略
- 新稳定 selector 或测试模板
- 新增自动化脚本覆盖关系

### 10.3 基线回写

版本结束后，系统应生成 baseline promotion proposal：

- 哪些 ContextObject 新增或变更
- 哪些 ContextRelationship 新增或变更
- 哪些测试资产成为长期资产
- 哪些风险模式应沉淀
- 哪些历史功能保护规则应更新

只有审批通过后，candidate 才能进入 Official Baseline。

## 11. Agent 如何使用系统画像

### 11.1 Agent 输入

Agent 不能直接读取全部图谱。Agent Memory Manager 应按目标组装：

- 当前 US 摘要
- 相关 ContextObject
- 相关关系路径
- 相关历史测试资产
- 风险指标摘要
- 覆盖缺口
- 推荐工具
- 高风险 gate 提示

### 11.2 Agent 输出

Agent 输出必须落到结构化对象：

- VerificationPoint
- Scenario
- TestCase
- AutomationBlueprint
- RunPlan
- FailureReport
- ReleaseAdvice
- CandidateKnowledge

Agent 不得直接写 Official Baseline，也不得直接输出正式上线结论。

### 11.3 Agent 追问

当系统画像无法支撑质量闭环时，Agent 应追问：

- 缺少哪个 source
- 哪个 US 验收标准不明确
- 哪个受影响对象缺少历史测试
- 哪个自动化脚本缺少运行环境
- 哪个失败缺少证据

追问结果仍应通过工具写入候选对象或上下文，而不是停留在聊天文本。

## 12. 长期技术栈

长期技术栈固定为多投影架构：

- PostgreSQL：正式事实源，保存对象、关系、基线、overlay、指标和审计。
- MinIO / S3：保存原始 source、测试资产、截图、trace、报告和大对象证据。
- Tree-sitter：结构化代码解析，抽取符号、路由、依赖和测试声明。
- OpenGrok：代码检索、定义/引用跳转和源码导航。
- PostgreSQL FTS / pgvector：关键词与语义检索投影。
- Temporal：摄入、解析、归并、上下文组装、回写等长任务编排。
- LangGraph：单个 AgentGoal 或 Skill 内的局部规划和工具路由。

原则：

- Projection 可以替换，但 canonical store 不能替换。
- LLM 只做候选抽取、解释和低置信裁决，不直接写正式画像。
- 图谱引擎可以后续接入，但只能作为 projection，不替代 PostgreSQL 正式事实源。

## 13. 分阶段落地

### 13.1 Phase A：必需代码与可选质量源可信接入

目标：

- 真实代码必须进入 RawAsset；历史 US、测试资产在提供时进入同一 RawAsset 主线。
- 禁止占位 source 初始化正式画像。
- 建立 source 状态、失败和审计。

验收：

- 代码缺失时 Agent 追问并阻断 baseline。
- 只有代码时可生成低置信 source checkpoint；三源齐全时生成跨源增强 checkpoint。
- 失败 source 不污染基线。

### 13.2 Phase B：系统画像图谱

目标：

- 生成 ContextObject、ContextRelationship 和 QualityMetricSnapshot。
- 支持 `US -> code -> tests` 路径查询。

验收：

- 输入 US 能返回影响对象、历史测试和覆盖缺口。
- 每个对象和关系有 source refs、confidence、freshness。

### 13.3 Phase C：质量上下文组装

目标：

- 构建 TaskContext、QualityProfile、RegressionProfile 和 CoverageMatrix。

验收：

- 没有 TaskContext + QualityProfile 不进入质量生成。
- 变更后相关上下文会 stale。

### 13.4 Phase D：质量动作生成

目标：

- 基于系统画像生成 VerificationPoint、TestCase、AutomationBlueprint、RunPlan。

验收：

- 每个验收标准至少映射验证点。
- 每个 must 验证点至少映射用例。
- 自动化脚本可追溯到验证点和系统对象。

### 13.5 Phase E：执行回归与放行

目标：

- 生成 impact-based regression suite。
- Run 结果和 Evidence 回流画像。
- Release Readiness 可解释。

验收：

- 受影响历史功能有回归证据或阻断项。
- 失败归因进入 candidate knowledge。
- 版本收口可生成 baseline promotion proposal。

## 14. 完整验收标准

长期系统画像方案完成后，应满足：

- 系统能从真实代码、US 和测试资产构建 Official Baseline。
- 系统能从新增 US 和 Git delta 识别新增特性的验证点。
- 系统能基于验证点和历史资产生成高质量测试用例。
- 系统能生成可维护的自动化蓝图和脚本建议。
- 系统能选择受影响历史功能的回归范围。
- 系统能把 Run 和 Evidence 回流为质量指标和候选知识。
- 系统能判断新增功能验证是否充分。
- 系统能判断历史功能是否受影响且有证据保护。
- 系统能给出可解释的 ready / conditional / needs_evidence / blocked 放行建议。
- 系统能在版本结束后通过审批把高价值知识沉淀回 Official Baseline。
