# Nasus Unified Context Engine 设计

## 1. 文档定位

本文定义 `Unified Context Engine`（UCE）的实现设计，覆盖 Source Connector、原料摄入、代码/文档理解、锚点抽取、实体归并、上下文组装与 ContextObject 存储。

UCE 是 Agent 的“眼睛”。它负责把存量系统原料加工成结构化上下文，供 `Conversation Orchestrator`、`Tool Runtime`、`Agent Loop` 和质量生成工具直接消费。

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

### 4.2 统一输入类型

首发支持：

- `git_repository`
- `document_bundle`
- `openapi_spec`
- `ux_asset`
- `historical_quality_asset`

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
  - `chunk_embedding_ref` 可空
  - `chunk_metadata`

## 6. 知识摄入管线

### 6.1 Git 仓库

`clone/fetch -> snapshot -> OpenGrok indexing -> Tree-sitter parse -> symbol/reference extract -> anchor extract -> entity resolution -> ContextObject write`

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

### 7.1 OpenGrok

职责：

- 全文搜索
- 定义 / 引用 / 路径导航
- 跨文件符号定位

### 7.2 Tree-sitter

职责：

- 代码结构解析
- 函数/类/接口/路由/依赖提取
- 增量解析受影响文件

### 7.3 代码结构产物

建议表：

- `code_file_snapshots`
- `code_symbols`
- `code_references`
- `code_routes`
- `code_modules`

这些产物不是最终系统画像，而是 `Entity Resolution` 的输入。

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

### 10.3 归并结果

- `auto_merged`
- `needs_review`
- `rejected_merge`

每次归并都要保存：

- `resolution_reason`
- `confidence`
- `source_refs`
- `review_required`

## 11. ContextObject 存储

### 11.1 存储模型

首发采用关系型主存储，不上图数据库：

- `context_objects`
- `context_relationships`
- `context_object_sources`
- `context_object_overlays`

关系存储采用“对象表 + 邻接边表 + JSONB properties”。

### 11.2 查询策略

- 主查询按 `project_id / version_id / baseline_id / type / status`
- 图谱查询按 `root_id + depth + relationship_types`
- 高频详情页可用物化视图或缓存 summary 加速

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

### 12.2 build_quality_profile

输入：

- `task_context_id`

组装步骤：

1. 识别风险类型
2. 识别验证边界和优先级
3. 识别已有历史失败和测试资产
4. 产出 `risk_rating + verification_strategy + coverage hints`

## 13. 性能与一致性

- Connector run、entity resolution、context assembly 都必须幂等。
- 每个 `ContextObject` 必须保留 `source_refs` 与 `freshness_at`。
- 版本基线采用 `copy-on-write + overlay`，UCE 查询时遵循“overlay first, parent fallback”。
- 大规模图查询优先走分页、depth limit 和 typed path summary，不直接全图拉取。

## 14. 实现默认值

- 原始内容在 MinIO，元数据和对象在 PostgreSQL。
- OpenGrok 负责检索与导航，Tree-sitter 负责结构解析。
- 图谱首发采用邻接表 + JSONB，不引入专门图数据库。
- UCE 的所有输出都必须带 `source_refs`、`confidence`、`freshness_at`。
