# 固定来源的构建完成条件评估

状态：2026-10-08 已实现只读评估、实际结构构建来源回执、独立缺口责任登记、固定责任修订的 v3 评估及重新授权的历史重放。完整候选交付、累计费用账本及 Goal 完成事务仍待实现，主验收范围保持[自主画像构建方案](./autonomous-system-image-design.md)不变。

## 输入与调用契约

`query.system_image.build_completion.read` 通过 ToolInvocationRuntime 执行，不直接完成 Goal、批准业务期望、分配缺口负责人或发布画像。输入固定项目、原调查修订及其摘要、完整已结算 Goal 检查点，以及每个代码来源的可选分析 ID 和报告摘要。重复来源、未知字段、错项目、错误摘要或变化的当前检查点拒绝产生成功回执。

新入口设置 `analysis_policy="committed_build"`，不必提交分析 ID：服务端从原 plan/image 的结构提交回执发现实际分析。若同时传入 `analyses`，必须与完整实际集合一致；另一份有效的同来源分析也不能替代。未带该字段的旧请求保留 v1 诊断语义和原 request hash，不把历史任意分析升级为构建证明。

首次查询和返回前均核对原 Goal 当前数据库检查点。完成审阅是等待，不是新执行：处于 `build_completion_review` 的普通继续操作保留全部步骤、已消耗主动运行时间和原检查点，不重启计时或产生新工件。错误用户检查点仍拒绝，独立发布或后续确认不被普通继续替代。

ToolResult 只保留类型化 `build_completion` 回执，包含 project、调查修订、request/report hash。完整报告经私有、无缓存接口展开：

```text
GET /v1/projects/{project_id}/system-image/build-completions/{invocation_id}
```

历史读取验证原命令、回执和固定事实，使用已保存的原 Goal 快照，不以后来 Goal 或 source head 改写历史。每次重放重新检查当前来源访问权；撤权后旧回执不能继续读取正文。SSE 广播隐藏输入、结果和幂等元数据；正文及对象存储地址不进入成功 ToolResult。

## 完整来源与成员核验

评估读取原计划的全部 captured SourceRevision，而不是“最新来源”。每个来源验证数据库 pin、私有 manifest、inventory、纳入文件集合及计数。随后逐个读取原始文件，包括空文件和没有代码成员证据的文件，核对原始字节数、文件 SHA256 和按原清单顺序计算的聚合来源摘要。

每个原文件读取前和最终返回前检查来源访问权。不依赖当前 checkout、临时物化副本、解析后的文本或一次旧的成功结果；损坏和存储不可用拒绝整份评估。报告只记录验证方法、数量、字节数及验证摘要，不包含文件正文或存储引用。普通 source-delta 仍仅验证清单，保持 `file_bodies_verified=false`，不能借本能力提升自己的保证。

全部画像 code/document member 的精确 evidence 引用按 512 条批次回读，而不是复用调查中的 8 条样本。完整选择集上限 50000 条；全部来源文件合计上限 5000 个、100 MiB。任一上限超出即拒绝，不截断后宣称完整。分析报告按全部文件分页回读，核对固定来源的完整 path/hash/bytes 和每种解析状态计数；旧 v1 请求只选择一个分析报告仍不证明它就是原构建的实际 Provider 输出。

### 实时授权的操作级连接复用

完成评估 application 在一次同步操作内复用专用 PostgreSQL 只读连接，嵌套的 v3 原报告重放共用该连接。这里只复用数据库传输，不保存授权结果或原文：每次 `scope/require_current` 仍执行原单条 MVCC SQL，重新读取项目成员、完整来源 inventory、policy head 和 ACL epoch。`READ COMMITTED` 保证下一次 SQL 能观察期间已经提交的撤权、项目角色变更或新来源；不能改为画像工件使用的 `REPEATABLE READ` 快照，也不能降低逐文件及返回前的检查频率。

该连接池与业务池、不可变画像快照池分离，固定 4 个连接、无 overflow、获取等待最多 5 秒。建立 `READ ONLY` 事务后才暴露操作上下文；正常或异常结束均 reset、rollback、close，不 commit。池耗尽映射为脱敏 503，不返回旧成功报告、部分正文或数据库错误详情。单独权限读取和旧 port 的行为保持兼容，不使用跨请求缓存；调用前后的既有平台授权仍独立执行。

传输 scope 另固定所属线程／async task，并在退出前标记关闭。同执行上下文内同步嵌套可以复用；复制到兄弟任务、其他线程或操作结束后的 ContextVar 不能复用原 Session。新操作必须重新获取连接并设置只读事务；不能依赖 `Session.close()` 自身，因为 SQLAlchemy 默认允许关闭的 Session 再开事务。

`completion_read_metrics.py` 对同一个已提交报告执行旧逐次事务方式和新方式的完整 GET 回放：必须报告字节相同、授权 SQL 数量相同、每个对象的实际读取次数和返回字节数相同，且新方式只借出一次专用连接。统计另外区分既有 token 最后访问时间／限流记账和画像、Goal、Tool 等业务事实写入，不把认证记账称作业务变更或关闭认证以获得零写入。耗时仅是有限样本，不代替容量、p95、完整 P6 或 V1 门禁。实际 PG、原生 exweb 及浏览器结果见实施记录。

## 实际结构构建回执

0090 新增追加式 `image_structure_build_lineages`，按原 canonical 结构 invocation 固定 plan/target/image/manifest 摘要，以及每个 captured 代码来源实际返回的 analysis、完整观察归档和合并投影摘要。真正参与合并的原生结果另外固定 PG generation、规范投影和 MCP 协议 receipt 摘要；失败后未消费的原生尝试仅列入 `unused_native_generations`，不能声称它们贡献了画像。

原生 execution pin 是内部瞬时回执，不进入规范投影或已有观察 result；不会改变旧 generation 的规范摘要或伪造历史分析。结构候选、结构工件、lineage 和完成 Outbox 在同一 PG 事务提交；其中任一失败整体回滚。MinIO 观察归档仍是先存对象后提交引用，不假设跨存储事务。

新结构工件设置不可变的 `lineage_required=true`。迁移保留旧工件的 false 值且不回填回执；新工件缺少回执、或旧 marker 下出现新回执时拒绝读取，不在重放中重新索引或补造历史。存在任何新 marker 或回执时禁止降级。完成后的结构读取同样验证原回执，而不是重新获取 Provider 输出。

读取要求完整 envelope、全部 captured 代码来源及准确 scope/digest，最多 64 个构建回执、每个最多 64 个代码来源、256 KiB。服务端重新校验实际 PG generation/协议/投影 pin，并读取完整私有观察归档核验规范结果，不只比较分析表标题。同一来源存在不同实际分析的歧义时拒绝，不选最新报告。损坏、未知字段、遗漏或超限拒绝整份评估；读取结束重新检查来源权限。公开 ToolResult/SSE 只保留原小回执，lineage 正文仅在重新授权的私有报告里展开。

## 报告语义与未完成条件

`nasus.image-build-completion.v1` 包含固定 plan/image/manifest/调查摘要、原 Goal 检查点、来源扫描和字节核验、显式分析 pin、必选工件、五维 readiness、已知 Goal 计数、缺口与精确阻断原因。完整响应限制 64 KiB，拒绝静默截断。

`committed_build` 返回 `nasus.image-build-completion.v2`，另包含 `build_lineages`，已逐项验证的 `code_analyses` 标记 `build_lineage_verified=true`。只有完整实际集合通过时才消除 `analysis_build_lineage_unverified`；旧工件缺少来源回执时该阻断仍然保留。

当前报告 `delivery_kind=candidate_only`，但 `state=blocked`、`candidate_ready=false`、`goal_completed=false`；它不是已交付候选。已经核验的来源正文不再报告 `full_source_bytes_unverified`，仍可能存在下列独立缺口：

- 未使用已验证实际回执的旧评估仍缺少构建 lineage；即使 v2 lineage 通过，partial 或 unknown 的投影也不能算完整结构。
- 其他必选能力的结果没有完整交付凭证，结构授权不得转移给语义模型调用或生成。
- 已知 steps/model/thinking/active-runtime 计数不等于全阶段、全部能力和重试的累计费用账本；费用未知保持 null。
- 关键冲突没有完整、固定的处理结果；未知数量保持 null，不伪造“零冲突”。
- 原 v1/v2 报告不会因为后来登记负责人而改写。0091 可独立确认责任，v3 新评估显式消费一份确切责任修订，只消除“尚未分配责任”的合成阻断；候选交付门禁仍待实现，只读查询不能替用户分配或解决缺口。

结构维度仅证明冻结成员和证据可验证，不给出虚构覆盖率。behavior、traceability、automation、execution 保持未验证；没有正式业务批准、自动化或真实目标执行权限。完整 readiness、预算和缺口治理满足后，仍需另外实现原 Goal、交付报告、审计和 Outbox 的原子交付事务及 Portal 引导，不能只把 `blocked` 改成 `ready`。

## 独立缺口责任登记

0091 新增追加式 `image_build_gap_ownership_revisions`，不修改原完成报告或 Goal。每个责任修订固定原完成 invocation/report hash、完整原 Goal checkpoint、精确前驱 revision/hash 和全部缺口的一次性分配。缺口 ID 根据原 `code/blocks/reason/required_action` 计算，不用列表位置或 Provider ID；合并完全相同的缺口，排除“尚未分配责任”这一合成阻断，避免循环要求给分配动作本身指派负责人。

`system_image.build.gaps.assign` 是独立、需确认的 canonical 写命令。至少当前 reviewer 权限；负责人必须是当前有效成员（服务端也允许有效平台管理员），不得借原结构或调查授权自动确认。输入严格限定 1–96 项，每个原缺口恰好一项，附负责人和理由；缺失、重复、外来缺口、变更原摘要或 Goal、过期／未来确认、失效成员均拒绝。确认有效期 15 分钟，在提交边界再验证。

提交使用项目锁、完整 Goal 条件检查、命令／成员行锁和前驱 CAS。责任修订、审计与 Outbox 共用 PG 事务；并发同前驱只允许一个提交，失败不留下半份责任。原命令重放保留同一修订，改派必须提出新命令并固定当前头。历史上限 80，不静默截断；PG trigger 禁止修改或删除，迁移不补造旧责任，存在记录时禁止降级。

ToolResult 仅保留 `build_gap_ownership` 小回执，SSE 广播隐藏完整输入、理由和幂等元数据。私有、无缓存查询入口：

```text
GET /v1/projects/{project_id}/system-image/build-completions/{invocation_id}/gap-ownership
GET /v1/projects/{project_id}/system-image/build-completions/{invocation_id}/gap-owners
```

每次读取重新授权原完成报告的全部私有来源，核验完整历史、原 checkpoint、每个责任 hash 以及原会话已完成命令的准确回执。成员后来停用显示 `owner_unavailable`，不改写历史。Tool evidence observer 可展开确切旧修订，不用最新改派替换旧 receipt；历史不可读、撤权或回执损坏拒绝展示。负责人选择仅返回当前项目有效成员的 ID/display name，要求 reviewer 权限，最多 200 人，不暴露全平台账号或凭证。

Portal 在原评估下展示“构建缺口责任”。用户先填写全部责任，再准备命令，最后独立确认；刷新、重连和重新核验只 GET 原 key/ID，不自动 POST 或确认。准备或确认回应丢失时隐藏旧结果，显式重新核验唯一原命令；缺失、歧义或超限拒绝恢复。一次观察共用完整已核验历史，不重复读同一报告；正常回应直接核验原命令，完成后再读提交历史。会话内缓存不写浏览器持久存储，窗口重新获得焦点和刷新仍重新授权。离开审阅清除责任导航参数。

登记结果始终 `resolution_status=unresolved`、`goal_completed=false`、`execution_authorized=false`、`publication_authorized=false`。负责人已确认不等于缺口解决、已批准业务期望、覆盖成立或可执行测试。原 v2 仍保留其既有阻断；后续完成评估必须显式引用责任修订，不允许以最新责任头悄悄改变旧结论。

## 固定责任修订的 v3 评估

同一个 `query.system_image.build_completion.read` 增加可选 `ownership_pin`，必须同时使用 `analysis_policy="committed_build"`，不得再传替代分析集合。pin 严格包含原 v2 完成 invocation/report hash 和已确认责任 revision/hash 四项，不接受 latest、未知字段或另一份 v3 作为根。未带 pin 的 v1/v2 请求、原 request hash 和报告保持兼容，不增加新的工具或迁移。

application 通过责任读取 port 展开原 canonical 命令及其完整历史，重新核验原来源正文、完整成员证据、实际构建 lineage、报告摘要、原 Goal checkpoint、全部缺口与责任命令回执。缺失、损坏、越界或来源撤权拒绝整份读取，不重新索引、不补造历史。新评估还要求原 Goal 当前检查点不变、所选修订的全部负责人当前有效；返回前再次检查项目授权和 Goal。

`nasus.image-build-completion.v3` 保留原 v2 的来源、实际分析、lineage、工件、readiness、预算、关键冲突及 Goal 字段，另记录明确的 `ownership` pin。每项真实缺口增加固定 `gap_id`、负责人、`ownership_status=confirmed` 和 `resolution_status=unresolved`，完全重复的缺口保持原展示顺序。只移除 `gap_ownership_unassigned`，其余阻断全部保留；不能仅因该合成阻断消失就推导 candidate readiness。报告仍限制 64 KiB，超限拒绝而非截断。

这是另一条只读评估命令和小回执，不修改原报告、责任修订或 Goal，不赋予交付、发布、执行或业务规范 authority。历史 v3 使用原命令固定的确切旧责任修订，后来改派、成员停用或 Goal 改变不重写历史摘要；当前来源访问权仍实时检查。历史 `confirmed` 表示当时确认的记录，不保证负责人现在可用，未来当前使用／交付门禁必须另行核验。

Portal 仅在已有责任历史后提供“按这份责任记录重新评估”，创建前回读完整责任及 Goal，确认展示的 revision/hash 未变化且负责人有效。请求 key 先保存在审阅 URL，回应丢失只 GET 恢复唯一原命令，不再次 POST。刷新和“重新核验原责任评估”核对原输入、回执、精确旧修订及完整派生报告；重算期或任何失败隐藏旧成功内容，离开审阅清除两项新导航参数。界面始终显示候选交付仍受阻，不把职责登记当作解决结果。

## 验证范围

### Portal 原目标评估入口

原构建审阅页提供“核验交付条件”，不在进入页面时自动创建评估。按钮通过 canonical `query.system_image.build_completion.read` 固定原调查及完整已结算 Goal，使用 `committed_build`，不允许用户挑选替代分析。界面展示归档文件／字节／成员证据数量、实际分析和索引消费／未消费尝试、剩余阻断与缺口；未知费用和冲突不显示为零，也不把知识发布当作候选交付。

请求前将不含正文的随机 request key 保存到原审阅 URL；成功后保存确切 invocation ID。回应丢失时通过私有 GET 按原会话／tool／key 查找唯一命令，最多完整读取 256 条；缺失、歧义或超限拒绝，不选择最新命令，不重发 POST。刷新和重新核验仅查询原命令及私有报告。离开审阅清除两项评估导航参数，不将 Goal 正文写进 URL 或浏览器持久存储。

前端核对原请求／报告摘要、画像／manifest／调查 scope、完整 Goal checkpoint 和终态 flags，最终再读当前 Goal。查询中隐藏旧内容；撤权、摘要变化、目标变化或无回应均不显示先前成功结果。失败原命令不自动重启。只读评估本身不完成 Goal、不分配负责人、不消除预算或冲突阻断；下方责任登记是另一条独立确认的命令。完整候选交付事务仍待实现，具体浏览器及 exweb 证据见实施记录。

`test_source_body_verification.py` 覆盖三类来源、空文件、无工作树重放、无成员引用的原文件损坏、存储不可用、读取中和最后一文件后的撤权、聚合摘要及无效计数。HTTP 测试验证 PG ToolResult、MinIO 回读、固定 pin、旧来源/Goal 变化后的原报告、摘要损坏、权限变化和无私有内容错误响应。

固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 CBM CLI/MCP、LangGraph PG 与 MinIO 专项验证直接调查和原授权结构 Goal 两个入口。每个入口核验全部 127 个归档文件（exweb 126 个及既存代码夹具 1 个）、754 处成员证据，重放不新增索引或模型调用。v2 评估从原结构 invocation 自动发现两个代码来源，原生 generation/projection 与 PG 记录逐项比较；不再由调用者选择第一页分析。调查仍只有原 8 条样本，实际分析仍为 partial，两者没有被冒充完整业务覆盖。原生结果及当前回归证据见[实施记录](./implementation-progress.md)。
