# 系统画像构建模块

## 1. 模块目标

系统画像构建模块负责存量系统接入、原料索引、系统画像构建和上下文组装，是 Agent 的“眼睛”。

V1 不是 demo 型知识库。系统画像从第一个正式版本开始就按长期架构设计，只允许分阶段启用能力，不允许先做不可演进的临时数据结构。

首个正式版本的一等 source 固定为三类：

- 代码
- 历史 US 文档
- 历史测试用例和自动化脚本

OpenAPI、UX、缺陷系统和运行日志可以作为增强 source 接入，但不得稀释首版主线。系统画像首先要把“代码 -> US -> 测试资产”三者之间的质量关系建起来。

正式需求、V1 输入范围、生命周期、对象关系和验收标准以 [产品需求基线：系统画像构建模块需求](../../product-requirements.md#5-系统画像构建模块需求) 为准。

系统画像如何支撑新增特性的验证点识别、测试用例构建、自动化蓝图、运行回归、上线判断和历史功能保护，以 [长期质量闭环支撑方案](./quality-closure-enablement.md) 为准。

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

- [Context Engine 设计](./context-engine.md)
- [知识摄入管线](./ingestion-pipeline.md)
- [基线与分支规则](./baseline-and-branching.md)
- [长期质量闭环支撑方案](./quality-closure-enablement.md)

## 6. 开发指导

- UCE 对上层暴露统一上下文能力，不允许业务层直接依赖底层 `search_code/search_docs`。
- 存储方案从 V1 起采用长期逻辑架构：
  - PostgreSQL 作为 canonical source of truth，保存对象、关系、基线、overlay、质量指标和审计。
  - MinIO / S3 作为 raw assets、测试脚本、截图、trace、报告等大对象存储。
  - OpenGrok + Tree-sitter 作为代码理解与代码导航后端。
  - PostgreSQL FTS + pgvector 作为 V1 hybrid retrieval 默认实现。
  - RerankService adapter 作为 V1 标准检索阶段；provider 不可用时降级到 rule-based fusion。
  - Search / Vector / Rerank / Graph 都作为 projection 或 index，不作为正式事实源。
- 首发可以先用 PostgreSQL 邻接表承担 graph query，但 schema 与服务接口必须按可投影到图查询引擎的方式设计。
- 首发必须有 embedding 与 rerank 的模型配置、版本记录、调用审计和重建机制；不能把向量检索与重排推迟到后续版本才设计。
- embedding 与 rerank 的模型配置必须使用平台 Settings 中独立的 `model_profiles.embedding` 和 `model_profiles.rerank`，不能复用主会话 `chat` route。
- 版本基线遵循 `overlay first, parent fallback`，overlay 必须是长期模型，不是临时 diff。
- 系统画像必须同时支撑代码质量、US 完成质量和测试质量三类判断。

## 7. 验收标准

- 代码、历史 US 文档、历史测试用例和自动化脚本能够进入同一系统画像主线。
- 代码、历史 US、历史测试用例和脚本能够形成可追溯的对象关系。
- `TaskContext` 和 `QualityProfile` 可以稳定从系统画像派生出来。
- 相似 US、相似测试资产、相似失败模式可以通过 hybrid retrieval 召回，并经过 rerank 或 fallback fusion 进入上下文组装。
- 输入一个 US 后，系统能返回相关代码对象、历史相似 US、相关测试资产、覆盖缺口和质量风险。
- source 内容变化或 embedding 模型版本变化后，相关 embedding 会标记 stale 并可重建。
- rerank provider 不可用时，系统可降级并保留检索运行记录。
- 无真实三源绑定时，系统只能创建 source slots 和追问，不得初始化正式基线。
