# 系统画像构建模块

## 1. 模块目标

系统画像构建模块负责存量系统接入、原料索引、系统画像构建和上下文组装，是 Agent 的“眼睛”。

2026-09-09 下一阶段设计入口：[自主构建与持续演进的系统画像](./autonomous-system-image-design.md)。它明确 AI 自主规划、引导/自然语言入口、多 source 修订、三源关联、版本持续更新和下游用途上下文。新方案是待实施设计，不代表现有代码已经完成；现状差距和迁移顺序分别在主方案 §2 和[开发验收方案](./delivery-and-evaluation.md)。

V1 不是 demo 型知识库。系统画像从第一个正式版本开始就按长期架构设计，只允许分阶段启用能力，不允许先做不可演进的临时数据结构。

首个正式版本的一等 source 固定为三类：

- 代码
- 历史 US 文档
- 历史测试用例和自动化脚本

OpenAPI、UX、缺陷系统和运行日志可以作为增强 source 接入，但不得稀释首版主线。系统画像首先要把“代码 -> US -> 测试资产”三者之间的质量关系建起来。

正式需求、V1 输入范围、生命周期、对象关系和验收标准以 [产品需求基线：系统画像构建模块需求](../../product-requirements.md#5-系统画像构建模块需求) 为准。

系统画像如何支撑新增特性的验证点识别、测试用例构建、自动化蓝图、运行回归、上线判断和历史功能保护，以 [长期质量闭环支撑方案](./quality-closure-enablement.md) 为准。

质量执行底座的 [项目级测试数据命令发现](./http-fixture-operation-history.md)提供重新授权的只读历史，
可另行[核验原持久阶段](./http-fixture-original-observations.md)；两者不替代实际运行、独立 unknown 处理或发布证据。

[RunPlan 业务任务生命周期](./run-plan-case-jobs.md)连接 canonical 执行/取消/查询、
同原命令 Temporal 调度和重新授权的私有历史，Portal 已接入完整引用、独立确认、
取消和同会话原命令恢复。实际外部依赖及 exweb 执行、跨会话发现与 QA 消费仍需
验证，不授予正式 coverage/release authority。

[RunPlan 原用例执行核心](./run-plan-case-execution.md)增加完整清单的内部 HTTP Worker 和
PG 持久派发账本；后续任务层接入独立公共确认/Temporal adapter，真实目标到覆盖/
放行验证仍需完成。

[原业务执行输入核验](./run-plan-case-inputs.md)已连接原 build/environment/locator/setup、
当前 target health、受监督异步核验和私有 MinIO case archive；Portal 引用核验不替代
后端 live grant，完整 P0-P6 验收仍待完成，不把原 setup 或内部观察当作正式业务覆盖。

[Fixture 捕获值与业务资源绑定](./run-plan-fixture-bindings.md)提供不可变完整输入和
私有 HTTP v3 原生协议；公共脚本生成、独立审阅及 RunPlan/Worker handoff 尚未
切换，不能通过重写旧脚本路径把协议底座当作正式业务覆盖。

## 2. 模块边界

负责：

- Source Connectors
- Raw Asset Ingestion
- Code Intelligence
- Knowledge Intelligence
- Hybrid Retrieval
- Embedding Projection
- Rerank Service
- Anchor Extraction
- Entity Resolution
- Context Assembler

## 3. 前端与空间投影

该模块不直接对应单一页面，但会投影到：

- `Build`
- `Project Overview`
- `Knowledge`
- `Personal Workspace`

## 4. 关键对象与能力

### 4.1 主要对象

- `ConnectorDefinition`
- `ConnectorBinding`
- `ConnectorRun`
- `ConnectorCheckpoint`
- `RawAssetRecord`
- `RawAssetChunk`
- `EmbeddingRecord`
- `RetrievalRun`
- `RerankRecord`
- `ContextObject`
- `ContextRelationship`
- `SystemImageBaseline`
- `VersionImageOverlay`
- `QualityMetricSnapshot`

### 4.2 对外能力

- `get_feature_context`
- `build_task_context`
- `build_quality_profile`
- `build_regression_profile`
- `build_coverage_matrix`
- `retrieve_context`
- `rebuild_embeddings`
- `assess_release_readiness`

## 5. 子文档

- [自主构建与持续演进主方案](./autonomous-system-image-design.md)
- [知识、版本与上下文契约](./knowledge-contracts.md)
- [开发顺序与验收方案](./delivery-and-evaluation.md)
- [实施进度与真实验证记录](./implementation-progress.md)
- [固定画像的代码成员比较](./code-member-deltas.md)
- [固定清单下的按来源刷新](./source-refresh.md)
- [来源采集的不可变准入](./source-acquisition.md)
- [固定来源的兼容上下文构建与工作区隔离](./frozen-materialization-inputs.md)
- [显式 Git 分支与标签来源](./source-tracking.md)
- [来源清单作为冻结画像的根](./manifest-rooted-projections.md)
- [原目标的追加式构建阶段](./image-plan-phases.md)
- [Agent 构建目标的持久启动回执](./agent-goal-start-receipts.md)
- [Agent 主动运行预算与恢复契约](./agent-active-runtime.md)
- [Agent 工具目录的无损预算编码](./agent-tool-catalog.md)
- [固定来源的构建入口与缺码恢复](./source-pinned-build-entries.md)
- [历史知识画像回滚](./image-rollback.md)
- [上下文与画像对象的来源锚点](./context-provenance.md)
- [冻结关联与上下文的来源追溯](./relation-provenance.md)
- [需求与测试来源投影契约](./document-source-projections.md)
- [验收条件与业务规则来源对象](./requirement-components.md)
- [固定 ContextPack 的测试设计范围审阅](./test-design-scope.md)
- [固定测试设计生成与覆盖契约](./test-design-generation.md)
- [生成任务、取消与归档恢复](./generation-jobs.md)
- [完整分包预算、逐调用账本与私有回执](./generation-batch-ledger.md)
- [草稿用例的独立断言映射审阅](./test-design-mapping.md)
- [固定审阅用例的自动化输入衔接](./automation-input-preview.md)
- [Runner 执行观察与原输入关联](./runner-execution-observations.md)
- [固定审阅输入的执行计划准备](./run-plan-preparation.md)
- [固定归档源码的正式原生构建与取消](./native-target-build.md)
- [执行计划与原生构建的固定关联](./run-plan-build-bindings.md)
- [原目标环境与挂载产物的只读核验](./native-target-environment.md)
- [原目标环境观察的独立归档与登记](./native-environment-records.md)
- [固定 exweb 的真实构建与运行验证](./exweb-native-runtime-validation.md)
- [固定 AC 的语义关联候选召回](./semantic-link-recall.md)
- [语义关联固定证据输入与结果准入](./semantic-link-judgment.md)
- [显式引用候选与查询契约](./explicit-reference-candidates.md)
- [引用关联审阅与不可变决定](./reference-review-decisions.md)
- [固定审阅成员的候选修订](./frozen-review-membership.md)
- [开源能力评估与决策依据](./technology-evaluation.md)
- [Context Engine 设计](./context-engine.md)
- [知识摄入管线](./ingestion-pipeline.md)
- [基线与分支规则](./baseline-and-branching.md)
- [长期质量闭环支撑方案](./quality-closure-enablement.md)

## 6. 开发指导

- UCE 对上层暴露统一上下文能力，不允许业务层直接依赖底层 `search_code/search_docs`。
- 存储方案从 V1 起采用长期逻辑架构：
  - PostgreSQL 作为 canonical source of truth，保存对象、关系、基线、overlay、质量指标和审计。
  - MinIO / S3 作为 raw assets、测试脚本、截图、trace、报告等大对象存储。
  - 当前实现以 Tree-sitter 解析并由 Codebase Memory 可选增强。下一阶段目标是优先复用通过实测的开源代码知识 provider，Tree-sitter 保留为过渡校验/降级，不另建通用代码知识库。正式事实由 Nasus 快照/证据验证准入，而非指定某个 parser 为永久真相。Codebase Memory/CodeGraph 的切换门禁见开源评估；provider ID 不进入领域主键和跨域契约。
  - PostgreSQL FTS + pgvector 作为 V1 hybrid retrieval 默认实现。
  - RerankService adapter 作为 V1 标准检索阶段；provider 不可用时降级到 rule-based fusion。
  - Search / Vector / Rerank / Graph 都作为 projection 或 index，不作为正式事实源。
- 首发可以先用 PostgreSQL 邻接表承担 graph query，但 schema 与服务接口必须按可投影到图查询引擎的方式设计。
- 首发必须有 embedding 与 rerank 的模型配置、版本记录、调用审计和重建机制；不能把向量检索与重排推迟到后续版本才设计。
- embedding 与 rerank 的模型配置必须使用平台 Settings 中独立的 `model_profiles.embedding` 和 `model_profiles.rerank`，不能复用主会话 `chat` route。
- 开发环境的 hash vector fallback 必须有显式记录，确保 `EmbeddingRecord -> RetrievalRun -> RerankRecord -> TaskContext` 可追踪，但它不代表真实语义检索。生产 provider 不可用时按用途返回 partial/blocked，可提供记录过的词法/结构降级，不得用 fallback 冒充语义检索 ready。
- 三类 source 摄入后必须物化 `RawAssetChunk`：chunk payload 存入 MinIO/S3 或本地对象存储，领域对象保存 `content_ref / content_hash / section_path / token_estimate / embedding_record_id`。`TaskContext.evidence_refs` 必须能回溯到 `raw_asset_chunk:{id}` 和对应 `content_ref`。
- 版本基线遵循 `overlay first, pinned parent revision fallback`；删除 tombstone 阻止回退复活。审阅状态、版本和 freshness 分离，细则见知识契约 §4。
- 系统画像必须同时支撑代码质量、US 完成质量和测试质量三类判断。
- Code Intelligence readiness 必须执行真实 parser smoke parse；`parser:tree-sitter` 证据只能由 Tree-sitter adapter 的真实解析结果产生。
- 外部代码图谱 readiness 必须单独报告 `graph_mode/graph_status`；`optional` 失败要保留降级证据，`required` 失败必须阻断启动或画像物化。

## 7. 验收标准

- 代码、历史 US 文档、历史测试用例和自动化脚本能够进入同一系统画像主线。
- 代码、历史 US、历史测试用例和脚本能够形成可追溯的对象关系。
- `TaskContext` 和 `QualityProfile` 可以稳定从系统画像派生出来。
- 相似 US、相似测试资产、相似失败模式可以通过 hybrid retrieval 召回，并经过 rerank 或 fallback fusion 进入上下文组装。
- 输入一个 US 后，系统能返回相关代码对象、历史相似 US、相关测试资产、覆盖缺口和质量风险。
- source 内容变化或 embedding 模型版本变化后，相关 embedding 会标记 stale 并可重建。
- rerank provider 不可用时，系统可降级并保留检索运行记录。
- 无真实代码绑定时，系统只能创建 source slots 和追问，不得初始化正式基线。
- 历史 US 和测试资产是可选增强源；缺失时记录 coverage gap 并降低 confidence，不阻断代码基线，后续接入必须增量补齐关系。
