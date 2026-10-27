# 发布绑定的版本化检索

`0054_frozen_retrieval_index` 是渐进迁移中的正式检索底座，不替代完整 P0-P6，也不把向量相似度当作关联、oracle 或覆盖率。

## 生命周期

- `query.system_image.index.preview` 读取指定 publication 的全部冻结代码/需求/测试来源证据。只允许项目管理员和已经测试成功的已保存 embedding 配置；不从可变 active route 猜测模型。
- 预览返回输入摘要、publication pin、模型配置摘要、HTTPS 目的地、来源集合、文档数、字节数及调用上限。该确认也明确授权后续项目检索查询发送到同一固定模型，不授权额外 rerank 出口。
- `system_image.index.build` 仍经 canonical ToolInvocationRuntime 和用户确认。确认有效期 15 分钟；启动前验证完整输入。数据库先追加式预留 invocation，未知、失败或取消结果不自动重发模型请求。
- 输入方案 `nasus.frozen-evidence-index.v1` 完整读取每条精确证据，不静默嵌入被截断的片段。按 UTF-8 边界拆为最多 4096 字节的片段，最多 4096 个、4 MiB 来源文本，每批 32 个、单次 60 秒。超限在预览时拒绝，不伪称完整索引。预算是字节而非模型 tokenizer 或费用估计。
- 目前支持 native OpenAI/OpenAI-compatible embedding 协议；其他 provider 明确不支持。无重试、重定向、环境代理和 mock fallback。每批按 provider index 重排，拒绝缺项、重复、零向量、非有限值及跨批维度变化，记录脱敏 LLMCall。
- 所有批次完成后，将来源片段、模型/publication pin 及向量摘要写入私有 MinIO 工件；PG 在同一事务追加完整 generation、documents、Outbox。每批调用前后及最终项目锁内重验 ACL、发布头、模型配置和 canonical 命令运行状态。任何失败均不能留下可检索的半成品。
- 同一 invocation 已提交而回执丢失时，重读原工件，既不调用模型，也不把旧 publication 重新激活。未完成的预留需要显式新命令/新确认；这不是自动恢复所有已完成批次或费用账本的完整实现。

## 查询与防腐层

应用层依赖 `IndexEmbeddingPort`、`FrozenIndexRepositoryPort`、`FrozenIndexArtifactPort`；native HTTP、SQLAlchemy/pgvector 和 MinIO 只在 infrastructure。领域层仅实现分片、向量验证和确定性 RRF。

Agent 对已发布画像先选择同一 publication 下完整提交的 generation，不复用相同 object ID 的旧向量，也不沿用另一个分支/Official 的索引。索引模型配置改变时必须重新确认构建，不能把新查询向量放入旧向量空间。

PG 在 source binding 过滤之后执行 FTS + pgvector 精确扫描，采用 0.7/0.3、k=60 的确定性 RRF。当前有界实现校验整个 generation 的文档/向量摘要，尚不声称大规模 ANN 性能达标。返回冻结 image-qualified object ref 与 evidence ID；同一对象的多个分片去重。不调用未经此次确认的 rerank 模型。

Agent 接收 generation/evidence/source revision/chunk/hash 定位，不直接接收索引中的源码正文。embedding 的确认不等于授权向当前聊天模型发送源码；正文进入后续模型上下文仍需要独立模型出口策略，不能以本索引建设隐式授权。

正常路径策略为 `published_hybrid_rrf_rerank_withheld`。临时 embedding provider 失败时，只查同一 generation 的 FTS，并明确返回 `published_lexical_embedding_unavailable`，审计失败且 trace 标记原因；不造 hash 向量。不存在此 publication 的 generation 时保持先前明确标识的词法过渡路径，不把它算作完成的语义索引。

模型返回后和结果返回前重新校验发布/ACL/配置；源撤权或 head 变化拒绝返回。`trace=true` 时，私有工件固定查询、query-vector hash、publication/index/model pins、ACL fingerprint、候选及返回项；PG 追加式保存元数据。这里只是派生检索审计，不改变业务事实或审批权威。

## 读取接口

- `GET /v1/projects/{project_id}/system-image/indexes?publication_id=...`：只检查指定的当前发布头，返回 `not_built / ready / rebuild_required`、当前完整 generation 元数据与 `can_build`。无模型出口；旧 publication 不能冒充当前状态。模型配置变化保留历史索引，但明确需要重新确认构建；此状态不代表实时 provider 连通性。
- `GET /v1/projects/{project_id}/system-image/indexes/{generation_id}`：当前来源权限下的历史索引元数据；不返回密钥、内部存储地址或全部片段正文。
- `GET /v1/projects/{project_id}/system-image/retrievals/{retrieval_id}?offset=0&limit=25`：历史 trace 的有界元数据分页，最多 50 项、64 KiB；正文留在现有 evidence 接口。查询文本仅对原查询者或项目管理员可见，同时仍要求当前来源权限。
- 所有响应 `private, no-store`；历史读取验证原 publication，不因新 head 出现改写旧工件。历史 trace 不是当前生成授权。

## Portal 入口

知识页只在存在真实 publication pin 时显示检索索引入口；默认收起，按需读取状态。项目管理员可显式选择已测试、非 legacy 的 OpenAI-compatible embedding 配置；系统默认不自动成为出口。普通项目成员可在来源权限下查看索引状态，不显示构建操作。

预览由 canonical query tool 产生，显示固定来源集合、输入字节/分片、调用上限、目的地与模型摘要。单独勾选授权同时涵盖此批来源正文和后续该模型的检索查询，不扩张为 rerank/chat/测试生成授权。切换模型、刷新、后台重新验证或 publication 切换后，旧确认不能复用。

构建先创建 `waiting_confirmation` invocation，核对相同请求后才发送 confirm；前端不直接制造 `confirmed_by_user`。运行时禁止重复提交和改模型，失败/未知回执不自动重试，提示先检查状态。成功后读取完整 generation；刷新可恢复已完成状态。错 scope、缺失 pin、权限/工件校验错误隐藏旧内容。沿用共享细边框、深浅色与移动布局，中英文文案同源。

当前界面不是完整后台任务历史：未完成预留的列表、SSE 批次进度、页面刷新后恢复运行中命令、费用和租约仍需交付，不能把 `not_built` 解读为不存在未完成或未知调用。

## AC 查询计划预览

`query.system_image.context.retrieval_preview` 和只读
`GET /v1/projects/{project_id}/system-image/indexes/{generation_id}/context-query-plan?publication_id=...`
复用同一个 application use case。管理员显式选择完整索引和当前 publication；计划方法为
`nasus.context-retrieval-plan.v1`，不根据可变 active route 重新选模型。

- 完整枚举固定画像中的每条来源 AC，查询仅包含它自身的 AC 字段及确切父需求的 description。不会把兄弟 AC、当前批准 oracle、模型解释或测试期望混入查询。
- 每个字段必须有固定原文证据，且对应 document revision / source revision / binding / evidence 已包含在所选索引的原始出口授权中。读取前后重新验证发布头、当前来源权限和模型配置；历史 preview 回执由 Agent 重新计算后才能消费。
- 原始字段按完整 UTF-8 字节计量，每条最多 4096 字节，总计最多 256 条 / 1 MiB；AC 加业务规则总数仍受 ContextPack 的 256 项限制。超限明确返回 `context_retrieval_over_budget`，没有删 AC 或截短字段。无 AC 返回 `missing_requirements` 与零查询、零调用预算，不伪造查询。
- 预算使用每批 32 条、单次 60 秒的 native embedding 上限，不是 tokenizer / 费用估计。预览只读取来源和索引，不调用 provider、不创建 retrieval trace 或 ContextPack 绑定、不增加正式 authority。
- 对外只有固定版本、输入摘要、数量/字节、目的地/模型摘要和权限标记，不含查询正文、原文或存储地址；GET 为 `private, no-store`。`plan_digest` 固定整份计划，`queries_digest` 固定每条 query 的 AC/parent/source/evidence 和文本。

预览仍为 `model_calls_made=0`，`execution_available=true` 表示支持下述独立确认式执行，不意味着已经调用模型。计划还固定当前 `scope_fingerprint` 和 `acl_epoch`，权限变化后不能复用旧确认。

## AC 查询持久执行

`0055_context_retrieval_batches` 新增追加式 plan/call/batch/result 表。`system_image.context.retrieve` 必须走 canonical 确认，固定当前 preview 的 `expected_plan_digest`；确认 actor 由后端保存，不信任客户端伪造字段。ToolRuntime 返回 running，不等待 embedding 批次完成。Temporal workflow ID 由 invocation 唯一确定，拒绝重复运行已关闭的 ID；PG running 命令是丢失派发回执后恢复的持久依据。

- 执行计划和当前账号、来源 ACL、publication、模型配置在每次出口与提交前重新验证。原生批次最多 32 个查询，call ordinal 全局唯一且受完整计划预算限制。预留先提交；worker 竞争不会重复发送同一个批次。
- 已完成批次的向量写入私有 MinIO，再追加 PG batch receipt。Worker 崩溃后复用已验证的批次工件，不重复模型调用。没有持久结果的预留最多等待 120 秒；过期明确失败，要求新预览和确认，不猜测 provider 是否计费后自动重发。
- provider 明确不可用时允许同 generation 的 FTS 降级，批次与 trace 标记 fallback；不是切换模型、伪造向量或声明语义验证成功。
- 所有 AC 均产生固定 trace 后，在一个 PG 事务内提交全部 trace、完整 AC-to-retrieval 映射、结果、ToolInvocation 完成状态、审计和 Outbox。取消、撤权、发布头或模型变化不能提交部分映射。MinIO 中未提交的私有临时工件不具有业务效力；通用 orphan GC 仍待实现。
- `GET /v1/projects/{project_id}/system-image/context-retrievals/{invocation_id}` 只返回已提交映射的元数据，`private, no-store`；验证原私有工件、所有 trace pin 和当前来源权限。历史读取不调用模型。Agent 使用 `query.system_image.context.retrieval` 获取并重新核验 receipt，当前使用还需重新验证 publication/model。

`0056_context_retrieval_cancel` 将取消投递单独保存。`system_image.context.cancel_retrieval` 要求当前项目管理员，但不依赖原确认账号仍启用。任务 cancelled、取消请求及 Outbox 同事务落库，随后发送 Temporal cancel；RPC 或回执保存失败时保持待投递，Worker 重试同一 workflow ID。迁移回填旧 cancelled 命令，已有取消记录禁止 destructive downgrade。账号在执行前停用时任务直接失败，不反复重试模型。

恢复扫描按 invocation keyset 分页，每页最多 100 条，单条故障不阻塞后续任务；取消先于派发。Temporal RPC 有 10 秒上限，活动持续 heartbeat，workflow 等待活动取消完成。投递回执只证明取消请求已送达（或目标不存在），不代表已发送到 provider 的字节被撤回、立即停止远端计算或退费；即使延迟派发在取消之后到达，活动也会先读 PG 终态，不能产生新出口。已完成结果不被取消覆盖。

Portal 先预览完整 AC 预算，再独立确认执行；刷新从 canonical 命令历史恢复 running/completed 状态，支持取消。成功且所有 pin/authority 校验通过后，将完整映射交给共享 ContextPack 面板，以 v5 预览/归档。坏回执、权限错误、重取中的旧结果均隐藏；未完成映射不能使用。界面目前采用轮询，没有宣称 SSE 批次进度、费用账本或完整索引构建恢复已完成。

ContextPack `test_design` v5 已通过 application replay port 消费固定 trace：不读取最终 top-N 作为完整池、不在预览/提交/历史读取时重复调用 provider，组合 AC 词法/显式引用后先筛人工否定再截取。每条 AC 显式绑定已有 trace，历史保留固定审阅头与模型/index/query 摘要；模型变化使当前使用失效而不改写旧包。接口不暴露源码正文和内部存储地址。详见[上下文 v5](./context-packs.md#v5-固定检索回放)。这只是已有有界池的回放，不等于全部索引的完备召回或五种用途统一接入。

## 未完成范围

Agent 全计划费用预算/自动调查调度、更多 embedding provider、受控 rerank、图扩展、跨版本负向关系检索、ContextPack 其余用途、增量索引/GC/索引构建批次恢复、完整索引任务界面、独立真实模型 gold 和容量性能验收仍待实现。当前没有把旧索引删除，没有将来源 AC、测试预期或代码行为自动提升为正式 oracle。AC 查询批次恢复不等于全部 provider 生命周期、索引重建或系统画像更新 DAG 已完成。
