# 系统画像构建：知识摄入管线

## 1. 文档定位

本文聚焦系统画像构建模块中的“原料如何进入系统”这一条主线。

它不替代 Context Engine 总设计，而是专门回答：

- Git、文档、UX、OpenAPI、历史测试资产如何进入系统
- 摄入任务如何编排、失败、重试和审计
- 原料如何从 `RawAssetRecord` 演进为 `ContextObject`

## 2. 摄入目标

首个生产版本中，摄入管线必须优先支持三类一等 source：

- Git 仓库
- US 文档
- 历史测试用例和自动化脚本

增强 source 可后续接入：

- UX / 设计资料
- OpenAPI / 接口描述
- 历史缺陷与执行证据

摄入结果不直接等于正式系统画像，而是：

`RawAssetRecord -> RawAssetChunk -> EmbeddingRecord / RetrievalRun -> 结构候选 -> ContextObject -> Baseline`

## 3. 处理阶段

### 3.1 接入

- 连接外部源
- 校验凭据与权限
- 建立 `ConnectorBinding`

### 3.2 拉取

- 抓取原始内容
- 写入 `RawAssetRecord`
- 记录 `ConnectorRun`

### 3.3 解析

- 代码解析
- US 文档切块与验收标准抽取
- 测试用例、测试脚本、断言、测试数据和覆盖对象抽取
- UX / OpenAPI 结构提取（增强 source）
- 所有可检索文本原料必须先形成 `RawAssetChunk`。chunk 内容写入对象存储，PostgreSQL 只保存引用、hash、section path、token 估算和 embedding 关联。

### 3.4 关联

- Anchor Extraction
- Entity Resolution
- 生成 `ContextRelationship`
- 建立三类核心关系：
  - `US -> impacted code objects`
  - `TestCase / Script -> verifies US / AcceptanceCriteria`
  - `AutomationScript -> covers API / Page / Module`

### 3.5 入基线

- 形成 `Historical System Baseline`
- 审核后写入 `Official Baseline`

## 4. 关键要求

- 摄入必须 append-only，可回放
- 每次摄入都必须可审计
- 部分失败不能污染正式基线
- 必须支持增量重跑与重建
- 代码、US、测试资产三类 source 必须都能增量更新，并产生版本工作画像 overlay
- 每次摄入后必须能计算或刷新质量指标快照
- 三类一等 source 都拥有独立 slot，但只有代码是 Official Baseline 的必选输入；历史 US 和测试资产是可选增强输入。
- 代码 source 没有真实绑定时，不得静默使用默认占位 URI 完成摄入、画像物化或基线初始化。
- 可选 source 的默认占位 URI 不参与摄入，也不得被标记为 `indexed` 或写入伪造 evidence。
- Agent 可先创建 source slots；缺少代码时 `ToolResult.requires_followup=true` 并暂停 AgentGoal，引导用户补充代码路径或 Git URI。缺少 US / 测试资产只记录 coverage gap，不暂停基线构建。
- 用户在同一会话补充代码绑定后，Agent 才能恢复 `system_image.sources.register -> system_image.sources.ingest -> system_image.context.materialize -> system_image.baseline.initialize` 后续链路。

### 4.1 Source 审计字段

`RawAssetRecord` 不是单纯的 URI 保存对象，首版实现必须持久化以下审计字段：

- `source_label`：用户或 Agent 为 source 绑定提供的可读标签。
- `registered_at`、`registered_by_actor`、`registered_from_invocation_id`：记录 source 由谁、何时、通过哪个 `ToolInvocation` 绑定。
- `credential_ref`：只保存凭据引用，不保存明文 token / password / API key。
- `permission_status`、`permission_checked_at`：记录摄入前权限校验结果。
- `ingest_started_at`、`last_ingested_at`：记录摄入开始与完成/失败时间。
- `failure_reason`：记录安全裁剪后的失败原因，用于前端展示、Agent 追问和审计。
- `file_count`、`byte_count`：记录本次摄入实际处理规模，支持容量治理和异常排查。

### 4.2 摄入安全边界

首版实现必须包含基础 guardrail，后续再扩展成完整 Connector 沙箱：

- 本地路径摄入必须支持 `NASUS_SOURCE_ALLOWED_LOCAL_ROOTS` 白名单；开发环境可以为空，生产环境必须配置。
- 外部 URI 只允许白名单 scheme，默认包括 `git/http/https/ssh/s3/gs/docs/tests`。
- 摄入必须限制最大文件数、最大总字节数和最大单文件字节数。
- 触发限制、路径越权、scheme 不允许或文件不存在时，source 进入 `failed` 并记录 `failure_reason`。
- 必选代码 source 失败时，系统画像构建状态进入 `failed|partially_failed`，不得继续物化正式上下文或初始化基线。
- 可选 US / 测试 source 失败时，ToolInvocation 以 `completed + requires_followup(optional_source_gap)` 返回；系统保留失败 source、审计证据和覆盖缺口，但允许基于已索引代码继续物化与初始化低置信基线。
- 远程 `code` source 不允许再以“URI 哈希即已摄入”的方式进入 `indexed`。它必须由 Git connector 物化为本地受控 checkout，成功解析 commit revision 和文件内容后才能写入 `content_hash`、chunk 和上下文对象。
- Git connector 必须经 `SourceConnector` / `SourceIngestionPort` 防腐层接入。application service 不得直接执行 `git` 命令，也不得依赖某个代码知识库产品的私有模型。
- Git checkout 使用 `NASUS_SOURCE_CACHE_DIR` 托管，按无凭据 canonical URI 计算 cache key，通过跨进程锁避免并发 clone/fetch 互相覆盖，并以 `git:revision:{commit}` 写入证据链。
- 生产环境必须配置 `NASUS_GIT_ALLOWED_HOSTS` 和 `NASUS_GIT_ALLOWED_SCHEMES`。HTTP(S) URI 禁止内嵌用户名、token 或 password；私有仓库只保存 `credential_ref`，首版环境解析格式为 `env:VARIABLE`，后续可替换为 Vault/KMS resolver。
- Git clone/fetch 必须禁用交互提示、设置超时，并继续受最大文件数、总字节数和单文件字节数限制。拉取失败时保留旧 cache 但本次 source 状态必须为 `failed`，不得使用旧 revision 冒充本次成功。

### 4.3 浏览器文件上传与托管 source

- Web Portal 可以通过 `POST /v1/projects/{projectId}/source-files` 上传 `us_doc` 或 `test_asset`；代码 source 仍必须使用 Git URI 或受控服务端路径。
- 接口必须在读取 multipart 内容前校验项目存在性和访问权限，并限制文件数、单文件大小和总字节数。
- 上传文件按内容指纹打包为不可变 ZIP，生产环境写入 MinIO/S3，返回 `s3://` 托管 URI；本地测试允许 `local-object://`。
- 托管对象由 `ObjectStorageSourceConnector` 经 `SourceIngestionPort` 防腐层读取。解包必须拒绝路径穿越、绝对路径、超量文件和超量解压内容，并使用内容寻址缓存与跨进程锁避免并发覆盖。
- 文件上传只创建暂存对象和上传证据，不创建 `RawAssetRecord`，因此不能绕过 Agent-first 命令面。Portal 必须把返回 URI 交给 `system_image.sources.register`，后续注册、摄入、物化和基线初始化继续生成 `ToolInvocation` 与审计事件。
- 同一上传包的 `source_uri -> object revision -> RawAssetRecord -> RawAssetChunk -> ContextObject` 必须保持可追溯，原始对象不得被就地覆盖。

### 4.4 Chunk 与检索投影

- `RawAssetChunk` 是正式可追溯对象，不是临时缓存。
- `RawAssetChunk.content_ref` 必须指向对象存储，允许本地测试使用 `local-object://bucket/key`，部署环境使用 `s3://bucket/key`。
- `EmbeddingRecord.chunk_ref` 必须指向被向量化的 chunk；embedding provider 不可用时仍要生成 fallback record 与本地 hash vector ref。
- `RetrievalRun.result_refs` 可以包含 `raw_asset_chunk:{chunk_id}`、`ContextObject`、`ContextRelationship` 和 `QualityMetricSnapshot`，并通过 `RerankRecord` 记录排序或降级原因。
- `TaskContext.evidence_refs` 必须包含被采用 chunk 的 `raw_asset_chunk:{chunk_id}` 与 `content_ref`，确保后续质量闭环、审批和审计能回放原始证据。

## 5. 三源摄入策略

“三源”表示三种长期一等输入能力，不表示三者都是初始化门槛：

- `code`：必选，决定系统画像能否进入 `indexed / materialized / ready`。
- `us_doc`：可选，补充需求锚点、验收标准和 `implements / validates` 追溯关系。
- `test_asset`：可选，补充用例、脚本、断言和 `covers / validates` 追溯关系。

新增或更新任意可选源后，只重跑受影响 chunk、候选实体、跨源关系、检索投影和质量指标，不要求全量重建代码画像。

### 5.1 代码 source

最低抽取：

- repository / branch / commit
- file / module / package / service
- class / function / method / component
- route / API handler
- import / call / dependency
- changed object range

输出：

- `CodeSymbol`
- `Module`
- `Service`
- `API`
- `ContextRelationship`

首版 Git 物化链路：

`canonical Git URI -> allowlist validation -> clone/fetch managed cache -> detached commit snapshot -> file fingerprint/chunk -> object storage -> embedding/retrieval -> context extraction`

`SourceIngestionPort` 是 application 层读取 source 快照的唯一依赖；当前基础设施实现为 `GitSourceConnector`。代码结构理解通过独立 `CodeIntelligencePort` 接入：`TreeSitterCodeIntelligenceAdapter` 负责 canonical parse，`CodebaseMemoryCodeIntelligenceAdapter` 负责可选 repository graph enrichment，`CompositeCodeIntelligenceAdapter` 负责合并和降级。外部 provider 只通过公开 CLI/MCP tool contract 访问，禁止直接读取其 SQLite；供应商节点 ID、查询协议和存储结构不得成为 Nasus 的领域事实。

每个代码 `SourceTextUnit` 可以携带仅供 infrastructure 使用的 materialized `source_root`。适配器必须验证所有 relative path 仍位于该 root、文件 hash 与已摄入 snapshot 一致，再允许 repository-wide index；这可以阻止 source 在摄入和图谱分析之间变化时生成错误证据。

不受支持的语言不能静默退化为“已完成 Tree-sitter 解析”。允许使用 lexical fallback 维持可见性，但 source/object evidence 必须包含 fallback provider 与不支持的扩展名，且对象置信度必须低于原生 grammar 解析结果。

### 5.2 US source

最低抽取：

- US 编号
- 标题和业务描述
- 验收标准
- 角色 / 权限
- 前置条件 / 后置条件
- 主流程 / 异常流程
- 影响模块或接口的文本锚点

输出：

- `USWorkItem`
- `AcceptanceCriteria`
- `BusinessFlow`
- `RiskHint`

### 5.3 测试资产 source

最低抽取：

- 测试场景
- 测试用例
- 自动化脚本入口
- 断言
- 测试数据
- 依赖环境
- 覆盖对象锚点
- 历史执行结果引用

输出：

- `TestScenario`
- `TestCase`
- `AutomationScript`
- `ExecutionEvidence`
- `CoverageRelationship`

## 6. 对应主文档

- [系统画像构建模块总览](./README.md)
- [Context Engine 设计](./context-engine.md)
- [基线与分支规则](./baseline-and-branching.md)
- [后端总设计](../backend/system-design.md)
