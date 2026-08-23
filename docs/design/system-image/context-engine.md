# Nasus Unified Context Engine 设计

## 1. 文档定位

本文定义 `Unified Context Engine`（UCE）的实现设计，覆盖 Source Connector、原料摄入、代码/文档理解、锚点抽取、实体归并、上下文组装与 ContextObject 存储。

UCE 是 Agent 的“眼睛”。它负责把存量系统原料加工成结构化上下文，供 `Conversation Orchestrator`、`Tool Runtime`、`Agent Loop` 和质量生成工具直接消费。

长期设计原则：

- 系统画像不是代码搜索库，也不是一次性知识库。
- 系统画像必须长期维护“代码、US、测试资产”之间的质量关系。
- PostgreSQL 可以作为正式事实源，但 UCE 必须从第一版开始按多索引、多投影架构设计，避免后续从 demo 数据结构迁移。

## 2. 对外能力

UCE 对上层统一暴露 4 个能力：

- `get_feature_context(feature_ref, scope_ref)`
- `build_task_context(task_id)`
- `build_quality_profile(task_context_id)`
- `assess_release_readiness(version_id)`

约束：

- 上层不直接依赖底层 `search_code/search_docs`。
- 所有结果必须可回溯到 `RawAsset`、`ContextObject`、`Evidence`。

## 3. 内部模块

UCE 固定由 7 个内部模块组成：

1. `Source Connectors`
2. `Raw Asset Ingestion`
3. `Code Intelligence`
4. `Knowledge Intelligence`
5. `Anchor Extraction`
6. `Entity Resolution`
7. `Context Assembler`

配套存储：

- `Raw Asset Store`
- `Context Object Store`
- `Relationship Store`
- `Index / Search Views`

## 4. Connector 契约

### 4.1 SourceConnector 接口

每个 connector 至少实现：

- `healthcheck()`
- `discover_sources()`
- `pull_full()`
- `pull_delta(checkpoint_ref)`
- `normalize_asset(raw_input) -> RawAssetRecord`
- `emit_checkpoint()`

代码实现采用两级契约：

- `SourceIngestionPort`：application 层使用的稳定端口，负责规范化 source、摄入快照和读取文本单元。
- `SourceConnector`：infrastructure connector 防腐层，负责判断是否支持某个 source，并将外部源物化为 `MaterializedSource(local_path, connector_kind, source_ref, revision, evidence_refs)`。

首版 `GitSourceConnector` 已覆盖受控 clone/fetch、host/scheme allowlist、credential reference、托管缓存、并发锁、超时和 commit revision 证据。上面的 `healthcheck/discover/pull_delta/checkpoint` 是后续 Connector Runtime 的完整目标；在形成对应持久化对象前，不得伪造这些状态。

### 4.2 统一输入类型

V1 一等 source：

- `git_repository`
- `document_bundle`
  - 历史 US 文档
- `historical_quality_asset`
  - 历史测试用例、测试脚本、自动化资产

Baseline 输入策略：

- `git_repository` 是 Official System Image 初始化的必选 source。
- `document_bundle` 与 `historical_quality_asset` 是可选增强 source；缺失时记录 coverage gap 和较低 context confidence，不阻塞代码基线。
- 默认 source slot 只是交互占位，不是已绑定事实，不参与摄入、embedding、Entity Resolution 或 baseline 统计。

增强 source：

- `openapi_spec`
- `ux_asset`
- `defect_record`
- `execution_log`

### 4.3 Connector 运行记录

建议对象：

- `ConnectorDefinition`
- `ConnectorBinding`
- `ConnectorRun`
- `ConnectorCheckpoint`

每次 run 必须记录：

- `connector_type`
- `project_id`
- `trigger_kind=manual|scheduled|webhook|rebaseline`
- `input_snapshot_ref`
- `status`
- `started_at`
- `completed_at`
- `checkpoint_ref`

## 5. Raw Asset Ingestion

### 5.1 RawAssetRecord

最小字段：

- `raw_asset_id`
- `project_id`
- `version_id` 可空
- `source_type`
- `connector_run_id`
- `canonical_uri`
- `content_ref`
- `content_hash`
- `mime_type`
- `metadata`
- `extracted_at`

### 5.2 存储策略

- 原始内容写 MinIO。
- PostgreSQL 存 `RawAssetRecord`、元数据、解析状态与索引字段。
- 大文本切块后写：
  - `raw_asset_chunks`
  - `content_ref`
  - `content_hash`
  - `chunk_embedding_ref`
  - `chunk_metadata`
- V1 必须对可检索文本类 chunk 生成 embedding。只有二进制、空内容、解析失败或明确标记 `embedding_excluded=true` 的 chunk 可以暂时不生成 embedding，并必须记录原因。
- `RawAssetChunk` 的 payload 不能只存在数据库 JSON 字段中，必须写对象存储；领域表只保存可审计引用和元数据，避免后续 source 扩大后 PostgreSQL 膨胀。

## 6. 知识摄入管线

### 6.1 Git 仓库

`clone/fetch -> snapshot -> Tree-sitter parse -> symbol/reference extract -> anchor extract -> entity resolution -> ContextObject write -> optional code-search projection`

当前正式结构解析 provider 为 Tree-sitter；Codebase Memory 是 V1 选定的可替换代码图谱增强投影，OpenGrok 保留为未来全文搜索/导航投影。Git clone/fetch、revision snapshot 和 Tree-sitter parse 始终是 canonical fact 阶段；外部图谱只增强符号与关系，不成为领域事实源。任何 provider 不可用或语言不受支持时都必须明确记录实际 parser/index provider 和降级原因，不得冒充真实执行结果。

### 6.2 文档

`upload/import -> normalize -> chunk -> metadata extract -> anchor extract -> entity resolution -> ContextObject write`

### 6.3 OpenAPI

`import -> parse endpoints/schemas/auth -> match code routes -> match feature/module anchors -> ContextObject write`

### 6.4 UX 资产

首发支持：

- Figma metadata / screenshot / export
- 图片或文档式页面说明

处理策略：

- 提取页面名、flow 名、交互节点、文案锚点
- 尝试与 `page/component/flow/us` 关联

### 6.5 增量更新

- Git 优先使用 webhook 或轮询比较 commit range
- 文档使用内容哈希比较
- OpenAPI/UX 使用版本哈希比较
- 增量更新只重跑受影响的 asset、anchor 和 entity resolution，不全量重建

## 7. Code Intelligence

### 7.1 外部代码图谱投影

职责：

- 提供跨文件 `CALLS / IMPORTS / DEFINES / HANDLES` 等结构关系
- 补充 Tree-sitter 单文件解析无法稳定恢复的跨模块路径
- 为 Agent 的代码探索和影响分析提供分页图查询

V1 provider 为 `DeusData/codebase-memory-mcp`，但接入只使用其公开 CLI/MCP tool contract：

- `index_repository`
- `search_graph(format=json)`
- `query_graph(format=json)`

Nasus 禁止直接读取 provider SQLite 文件。`CodebaseMemoryCodeIntelligenceAdapter` 负责把外部 label、edge 和节点 ID 映射为 `CodeEntityCandidate` / `CodeRelationshipCandidate`；`CompositeCodeIntelligenceAdapter` 再与 Tree-sitter 结果合并。OpenGrok 如后续启用，只能实现同一 projection port，不能改变 `ContextObject` 主键或跨域 API。

### 7.2 Tree-sitter

职责：

- 代码结构解析
- 函数/类/接口/路由/依赖提取
- 增量解析受影响文件

当前实现约束：

- application 层只依赖 `CodeIntelligencePort`，不 import Tree-sitter、OpenGrok 或外部 MCP schema。
- infrastructure 默认实现为 `TreeSitterCodeIntelligenceAdapter`。
- 首版原生 grammar 覆盖 Python、JavaScript、TypeScript、TSX、Java、Go。
- 产出 `module / class / interface / enum / function / method / api_route / dependency` 候选实体。
- 产出 `belongs_to / depends_on / calls` 内部关系，并映射为 Nasus `ContextRelationship`。
- 不支持的语言允许进入显式 lexical fallback，但必须写入 `parser:lexical-fallback`、`parser-unsupported:{suffix}`，并降低对象 confidence。
- `/readyz` 必须执行 Tree-sitter smoke parse；解析器或 grammar 不可用时服务不得报告 ready。

### 7.3 代码结构产物

建议表：

- `code_file_snapshots`
- `code_symbols`
- `code_references`
- `code_routes`
- `code_modules`

这些产物不是最终系统画像，而是 `Entity Resolution` 的输入。

当前实现不直接持久化供应商节点 ID。`provider_node_id` 只用于一次物化过程中的关系映射；Nasus 使用 `project + source + provider node seed` 生成自己的稳定 ContextObject ID。后续替换为 codebase-memory、CodeGraph 或 OpenGrok 时，不改变领域主键和上层 API。

### 7.4 组合、降级与运行配置

组合规则：

- Tree-sitter 是主结果，外部图谱按 `relative_path + entity_kind + line/name` 合并。
- 命中同一实体时保留 Tree-sitter `provider_node_id`，只合并 evidence；外部 ID 不进入持久化主键。
- 外部关系端点先重映射到合并后的候选 ID，再写 `ContextRelationship`。
- 外部图谱返回绝对路径、越界路径、未知 schema 或变化中的 source snapshot 时必须拒绝该投影。

运行模式：

- `NASUS_CODE_GRAPH_MODE=disabled`：仅 Tree-sitter，并记录 `code-graph:disabled`。
- `optional`：外部 provider 失败时继续 canonical parse，并记录 `code-graph:unavailable` 和受控 reason。
- `required`：provider 不可用、版本探测失败或索引失败时 fail closed；staging/production 固定使用该模式并在启动时校验可执行文件。`disabled/optional` 仅用于本地开发、故障诊断和显式兼容验证。

V1 发布门禁必须执行 `npm run verify:code-graph-provider`，对临时真实仓库验证实体、关系、源文件边界和 Provider 身份防泄漏。只通过 fake CLI 单元测试不能证明外部图谱契约可用。

`/readyz` 必须分别报告 `backend/version` 与 `graph_backend/graph_status/graph_mode`。`ready` 不能用于暗示可选 provider 已启用。

## 8. Knowledge Intelligence

### 8.1 文档切块策略

- 先按结构切：标题、章节、表格、代码块
- 再按 token 控制次级切块
- 切块必须保留：
  - `document_title`
  - `section_path`
  - `source_uri`
  - `version_hint`

### 8.2 元数据提取

提取：

- 功能名
- 模块名
- API 名
- 需求编号
- 风险词
- 前后置条件

## 9. Anchor Extraction

Anchor 是跨源关联的桥梁。

首发抽取的 anchor 类型：

- `module_name`
- `service_name`
- `feature_name`
- `api_path`
- `schema_name`
- `page_name`
- `requirement_id`
- `us_id`
- `test_asset_name`

每个 anchor 至少包含：

- `anchor_id`
- `anchor_type`
- `anchor_value`
- `source_ref`
- `confidence`
- `position_ref`

## 10. Entity Resolution

### 10.1 目标

把来自 Git、文档、OpenAPI、UX、历史质量资产的候选实体合并成统一 `ContextObject`。

### 10.2 归并信号

- 同名或近似名
- 同路径 / 同路由 / 同 schema
- 共享 anchor
- 共享上游/下游关系
- 历史人工确认

所有 parser、MCP code graph 或外部代码知识库必须先映射成 provider-neutral 候选契约：

```text
CodeEntityCandidate {
  provider_node_id        # 仅本次 adapter 映射使用
  name / qualified_name
  entity_kind
  relative_path / language / line_range
  evidence_refs[]
}

CodeRelationshipCandidate {
  from_provider_node_id
  relationship_kind
  to_provider_node_id
  confidence
  evidence_refs[]
}
```

外部系统的节点 ID、图 schema、查询协议和存储结构只能保存在 adapter metadata/evidence 中，不得成为 Nasus `ContextObject` 主键或跨域 API 契约。这一防腐层保证后续可以替换 codebase-memory、CodeGraph、OpenGrok、Tree-sitter 或其他实现。

### 10.3 归并结果

- `auto_merged`
- `needs_review`
- `rejected_merge`

每次归并都要保存：

- `resolution_reason`
- `confidence`
- `source_refs`
- `review_required`

增量 source 更新时，只撤销或重算受变更 candidate 影响的自动关系。人工确认关系必须保留 review provenance，不能被下一次自动解析静默覆盖。

## 11. ContextObject 存储

### 11.1 存储模型

系统画像采用长期逻辑存储架构，不能只按单表 demo 设计。

### 11.1.1 Canonical Store

PostgreSQL 是正式事实源，保存：

- `context_objects`
- `context_relationships`
- `context_object_sources`
- `context_object_overlays`
- `baselines`
- `quality_metric_snapshots`
- `entity_resolution_runs`
- `context_assembly_runs`

关系存储采用“对象表 + 邻接边表 + JSONB properties”。

约束：

- 所有对象和关系都必须有 `source_refs`、`confidence`、`freshness_at`、`baseline_id`。
- `ContextRelationship` 必须支持 `from_object_id + relationship_type + to_object_id` 的唯一性约束和版本化。
- 正式画像读取必须从 canonical store 或其一致性投影读取，不能直接读解析中间表。

### 11.1.2 Object Store

MinIO / S3 保存：

- 原始代码快照
- 原始 US 文档
- 原始测试用例文件
- 自动化脚本
- 测试报告、截图、trace、执行日志

PostgreSQL 只保存 `content_ref`、hash、metadata 和 evidence refs。

### 11.1.3 Code Intelligence Index

OpenGrok + Tree-sitter 负责代码理解：

- OpenGrok：全文搜索、定义/引用跳转、路径导航
- Tree-sitter：AST、符号、路由、依赖、增量解析

这些结果进入解析中间表，再通过 Entity Resolution 写入 `ContextObject`。

### 11.1.4 Search / Vector Projection

首版必须落地 hybrid retrieval 投影，而不是只预留接口。系统画像从第一个正式版本开始就需要能同时做关键词、语义、结构关系和重排检索。

- 关键词检索：模块名、US 编号、接口路径、测试用例名
- 语义检索：相似 US、相似测试场景、相似失败模式
- 元数据过滤：project/version/baseline/type/status/freshness
- 关系扩展：从命中的 `ContextObject` 扩展一跳或多跳 `ContextRelationship`
- 重排：对候选 chunk/object 做 rerank 后再进入 `Context Assembler`

V1 默认物理实现：

- PostgreSQL Full Text Search 承担关键词检索。
- pgvector 承担 embedding 向量检索。
- PostgreSQL 邻接表承担图谱扩展。
- Rerank Service 承担 topK 候选重排。

V1 可以不引入独立 Weaviate、OpenSearch、Qdrant 或 Milvus 集群；但必须通过 `RetrievalAdapter` 抽象底层实现，确保 V2 可把检索投影迁移到 Weaviate / OpenSearch / Qdrant 等独立服务。无论物理实现如何，上层只能通过 UCE 查询接口访问，不能直接绑定具体引擎。

### 11.1.5 Embedding Projection

Embedding 是系统画像 V1 的必需能力。

必须支持的对象：

- `RawAssetChunk`
- `ContextObject` 的摘要文本
- `TestCase / AutomationScript` 的可检索说明
- `FailurePattern / RiskPattern` 的摘要文本

每条 embedding 记录至少包含：

- `embedding_id`
- `source_ref` 可空
- `object_ref` 可空
- `chunk_ref` 可空
- `project_id`
- `version_id` 可空
- `baseline_id` 可空
- `source_type`
- `content_hash`
- `embedding_model`
- `embedding_dimension`
- `embedding_version`
- `vector_ref`
- `status=pending|ready|stale|failed|excluded`
- `created_at`
- `stale_reason`

约束：

- embedding 模型必须通过配置管理，不能写死到代码。
- 一条 embedding 必须且只能绑定 `source_ref / object_ref / chunk_ref` 中至少一个明确 target；优先对 `RawAssetChunk` 建立 `chunk_ref`。
- `embedding_model + embedding_version + embedding_dimension` 不一致的向量不能混排。
- 源内容 hash 变化后，相关 embedding 必须标记为 `stale` 并进入重建队列。
- embedding 只是检索投影，不是正式事实源；正式事实仍以 `ContextObject / ContextRelationship / Baseline / Evidence` 为准。

### 11.1.6 Rerank Projection

Rerank 是系统画像 V1 的标准检索阶段，但必须支持降级。

标准链路：

`query understanding -> keyword retrieval + vector retrieval + graph expansion -> candidate merge -> rerank -> context assembly`

Rerank 输入：

- 用户查询或 Agent 子目标
- 候选 chunk/object/test/failure/risk
- project/version/baseline 过滤条件
- query intent，例如 `impact_analysis|similar_us|test_reuse|failure_analysis|release_evidence`

Rerank 输出：

- `candidate_id`
- `rank`
- `score`
- `reason`
- `evidence_refs`
- `model_id`
- `model_version`

降级规则：

- rerank provider 不可用时，系统必须回退到 rule-based fusion score，不得中断系统画像构建和质量闭环。
- 降级必须写入 `AuditEvent` 或检索运行记录，供后续排查召回质量。
- LLM 可以用于 query rewrite 和少量候选解释，但不能替代权限过滤、版本过滤、baseline 过滤或证据约束。

### 11.1.7 Graph Projection

首版 canonical graph 存在 PostgreSQL 邻接表中。若后续引入 Neo4j、AGE、Neptune 或其他图引擎，只作为 projection，不替代 PostgreSQL 正式事实源。

这意味着 V1 schema 必须已经支持：

- path query
- typed relationship
- relationship confidence
- baseline / overlay aware traversal
- object source traceability

### 11.2 查询策略

- 主查询按 `project_id / version_id / baseline_id / type / status`
- 图谱查询按 `root_id + depth + relationship_types`
- 检索查询必须先做结构过滤，再做 keyword/vector 召回，最后做 candidate merge 与 rerank
- 高频详情页可用物化视图或缓存 summary 加速
- 质量闭环查询必须支持三类路径：
  - `US -> impacted code objects`
  - `US -> acceptance criteria -> test cases/scripts`
  - `code change -> impacted US -> required tests`

## 12. Context Assembler

### 12.1 build_task_context

输入：

- `task_id`
- `us_id`
- `version_id`
- `git_delta`
- `related_raw_assets`

组装步骤：

1. 解析当前 US 和版本范围
2. 提取变更集和相关代码对象
3. 拉取相关文档、OpenAPI、UX、历史质量资产
4. 合并成 `TaskContext`
5. 写出 evidence refs 和 context slices
6. 计算代码影响、US 完成度和测试覆盖缺口

### 12.2 build_quality_profile

输入：

- `task_context_id`

组装步骤：

1. 识别风险类型
2. 识别验证边界和优先级
3. 识别已有历史失败和测试资产
4. 产出 `risk_rating + verification_strategy + coverage hints`

### 12.3 质量指标快照

系统画像必须为质量闭环产出可计算指标，而不是只返回上下文文本。

首发指标分三组：

- 代码质量风险：
  - 变更模块数
  - 变更文件数
  - 影响 API / 页面 / 服务数
  - 历史失败热点命中
  - 高复杂度或高耦合对象命中
- US 完成质量：
  - 是否有验收标准
  - 是否映射到系统对象
  - 是否存在测试场景
  - 是否存在测试用例或脚本
  - 是否有执行证据
- 测试质量：
  - 主流程覆盖
  - 异常/边界/权限覆盖
  - 自动化覆盖
  - 脚本稳定性
  - 历史失败闭环状态

指标写入 `QualityMetricSnapshot`，并关联 `baseline_id / version_id / us_id / task_id`。

## 13. 性能与一致性

- Connector run、entity resolution、context assembly 都必须幂等。
- 每个 `ContextObject` 必须保留 `source_refs` 与 `freshness_at`。
- 版本基线采用 `copy-on-write + overlay`，UCE 查询时遵循“overlay first, parent fallback”。
- 大规模图查询优先走分页、depth limit 和 typed path summary，不直接全图拉取。

## 14. 实现默认值

- 原始内容在 MinIO / S3，元数据、对象、关系、基线、overlay 和指标在 PostgreSQL。
- Tree-sitter 负责 canonical 结构解析；Codebase Memory 通过防腐层提供 V1 可选代码图谱增强，OpenGrok 仅作为未来可替换全文搜索/导航投影。
- 图谱首发采用 PostgreSQL 邻接表 + JSONB properties，但必须通过 graph query adapter 暴露，允许后续接入图投影。
- Search / Vector / Rerank 从 V1 起作为长期架构的一部分落地。默认实现为 PostgreSQL FTS + pgvector + RerankService adapter；独立 Weaviate / OpenSearch / Qdrant / Milvus 只能作为后续检索投影替换，不改变 UCE 对上接口。
- EmbeddingProvider 和 RerankProvider 必须通过系统 Settings 的 `model_profiles.embedding` 与 `model_profiles.rerank` 读取配置；`system_default` 可以来自 env 或平台托管配置，`custom` 来自用户保存的 provider/base URL/model/API key。
- Embedding/Rerank route 必须支持独立连接测试、独立调用审计、模型版本记录、token/调用成本统计和降级状态。摄入任务、检索任务、Context Assembler 不得自行写死 provider 或直接读取 API key。
- UCE 的所有输出都必须带 `source_refs`、`confidence`、`freshness_at`。
