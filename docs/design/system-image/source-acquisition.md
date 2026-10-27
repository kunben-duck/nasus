# 来源采集的不可变准入与结果消费

更新：2026-10-09（Asia/Shanghai）。0094 固定准入，0095 增加原命令的逐来源结果和清单消费。后续已验证独立 OS 进程被强杀后，由另一个进程显式消费原结果；仍不是自动恢复调度、Temporal 采集任务、lease 或完整生命周期的交付证明。完整范围仍以[主方案](./autonomous-system-image-design.md)和[交付门禁](./delivery-and-evaluation.md)为准。

## 固定输入

canonical `system_image.sources.ingest` 在修改 ingest 标记、持久工作区或运行 connector 之前，经 application port 保存 `SourceAcquisitionIntent`：

- 原 ToolInvocation ID、项目、准入时经过实际来源授权的执行账号。
- canonical 命令摘要，包含原 tool、input、conversation、initiator surface/actor、target scope 和幂等 scope/key/fingerprint。
- `selected` 或 `whole_project`，以及排序后的完整选中 RawAsset ID、binding ID 和来源身份摘要。
- 准入时的来源 manifest ID/hash；首次整批采集还没有清单时明确为 null，不补造历史。

`actor_id` 是本次准入的授权执行账号，不是独立保存并验证的原命令作者声明。ToolInvocation 的 initiator actor 仍是 user/agent/system 分类，不把它当成账号 ID。intent 不是权限票据、审批或 lease，每次调用仍重新检查当前账号、项目成员、来源策略和 ACL epoch。

选中采集仍为 1–100 项且必须携带原清单；整批准入为 1–1000 项，要求等于当前全部非占位注册 binding，超限拒绝，不截断。原 selection API 和 completed ToolInvocation 的回放契约不改变。

## 事务及完整性

独立 persistence repository 在项目来源锁内读取 running canonical command、活跃账号、持久项目角色与当前来源权限。旧调用携带的 scope fingerprint 必须与重新查询一致。来源、命令或账号不匹配时拒绝，不能把另一个项目或新增来源塞进原命令。

选中来源的 mutable RawAsset 类型、URI、tracked ref 必须与不可变 binding 一致。重新验证 tracked ref，并按原绑定算法重算身份 hash；没有 tracked ref 的历史 hash 保持原格式。已有 origin manifest 必须属于原项目，全部排序成员重新计算的 hash 和成员来源类型必须与登记事实一致。损坏备份不因字段恰好满足 SHA-256 格式而获准；拒绝发生在 connector 和工作区修改前，不修补旧事实。这里验证元数据清单，不冒称已验证全部归档文件、来源正文或业务正确性。

同一 invocation 已有 intent 时，全部原 pins 和内容摘要必须精确相同；fresh repository 或并发调用只返回原记录。其他命令更新 manifest、整批范围扩张、执行账号或命令输入变化均拒绝，不覆盖历史。0095 允许清单头仍为原 origin，或经原命令完整消费回执核验的清单；不能无条件跟随最新头。选中模式可以在重新授权后继续核验原选中集合，不因登记了未选中来源而扩张。

`source_acquisition_intents` 和只含不透明 ID 的 `system_image.source_acquisition.admitted` Outbox 同一 PostgreSQL 事务提交。事件不包含 URI、凭据、正文或归档地址。事件写入失败时 intent 回滚，application 尚未触碰工作区。数据库触发器拒绝 UPDATE/DELETE；存在记录时 migration downgrade 拒绝破坏性删除。没有自动回填旧采集意图。

0094 只提供准入记录与事件的原子性。0095 的后续事务如下；外层 ToolInvocation 审计、不同来源、最终兼容 projection 与 MinIO 仍不是一个统一事务。准入后再检查一次即时来源授权，然后保留已有 connector 前后及后续提交阶段检查。撤权可保留已合法提交的事实，但不能把它们用于绕过后续访问拒绝。

## 0095 逐来源结果与清单消费

新准入在原 intent 事务内建立 `source_acquisition_progress`，固定 intent hash、已提交结果集合及清单消费摘要。每次读取重算该摘要并对比完整排序结果，不能用 SSE 事件存在与否推测是否完成。进度不是 lease 或权限票据；身份字段不可改绑、记录不可删除。0094 已有 intent 不补造进度或原结果，新协议拒绝恢复这类缺 pin 的旧 running 命令，要求独立新命令；原 completed ToolInvocation 只读回放不改变。

每个选中来源保存一个追加式 `source_acquisition_results`：原 invocation/project/source/binding/intent、实际 PG 时间、结果摘要、snapshot/inventory 的确切 ID 和元数据摘要、内容引用及计数。成功结果为 captured；旧无真实 snapshot 的兼容引用明确为 legacy_unverified，不因登记了回执而升级成已采集证据。失败仅保存固定 reason code、可选 inventory 及 denied/allowed，不保存 OS 错误中的路径或凭据，也不声称有捕获正文。

实际 inventory、SourceRevision、逐来源结果、进度更新和 metadata-only Outbox 在同一 PG 事务提交。结果持久化失败中止命令，不能被 connector 的 OSError/RuntimeError 分支吞掉并转换为已完成缺口。新实例恢复先重新授权、核验命令与全部原结果，只对尚无结果的来源调用 connector。已提交失败也作为原结果保留；修复后的来源必须用独立新采集命令处理。事务提交前的 MinIO 写入可能留下孤立对象，尚需保留/GC 协议。

最终 `source_acquisition_manifest_receipts` 固定完整结果集合摘要、原 intent、清单 ID/hash；清单成员、清单头、消费回执、进度消费摘要和 Outbox 同事务保存。whole_project 仅使用全部原选中 binding，selected 从原 origin 成员替换明确选中项，不读取未选中来源的最新状态或纳入后来注册的来源。项目来源锁内重新检查头：其他命令已更新时拒绝，不回退它的新清单。

清单消费后、chunks 或最终工作区提交前中断，原 running 命令能复用原回执并从归档派生，不重新采集。普通重读、损坏备份和事件清理不修补历史：结果缺失、receipt 缺失或摘要不一致，连无内容变化的清单也拒绝。兼容 projection/chunks 仍可重试且不在该 PG 事务内；这不是完整 owner/epoch fencing、自动重启调度、取消或 exactly-once connector 保证。

## 事务内批量元数据核验与显式进程恢复

新恢复读取按完整 roster 一次加载每类 SourceRevision/inventory；准入的 mutable RawAsset 和消费的 binding 也按完整 ID 集合批量加载。每个结果仍校验自身 domain/hash、原 intent、两份重复列、来源项目/binding/source、artifact digest 和计数；缺项不会回落到先前缓存或最新归档。结果数量不能超出原 source selection。批量数据只在当前 PG 事务内使用，不跨请求缓存当前 ACL、权限或历史检查结果。

12 来源的实际 PG 检查先复现单次结果重放的 36 次 SourceRevision 查询，批量化后每类 artifact 查询有固定上限，且末项 inventory 被真实损坏后下一次读取仍拒绝。这是消除该读取 N+1 的证据，不是 1000 来源容量、p95 或整体写入复杂度门禁；每个新增结果事务仍重新核验原 ledger，完整采集性能仍需测量和优化。

独立进程检查先通过真实 ToolRuntime 创建原 running 命令，只延迟 handler，不制造命令/权限记录。测试进程构造 production container/application，在实际 result 或 manifest 事务提交后发出 marker 并等待；父进程确认 PID 后发送 SIGKILL，核对负信号退出，不运行异常/finally 补救。第二个 Python 进程使用新的 connector/cache/repository 和同一原命令，从 PG 与私有 MinIO 恢复；完整结果不重新采集，部分结果只调用未提交来源。两进程不共享内存对象或 snapshot cache。已提交记录、时间、head 和事件不重复，撤权或另一命令推进 head 后拒绝且零 connector。

这是显式调用内部 application 的恢复验证，不是生产重启自动扫描、API accepted/dispatch、Temporal Activity 重试或 worker lease。原命令保持 running，未以该测试证明最终 ToolInvocation 与 projection/chunks 的原子终态。固定 exweb 的 126 个 Git blob 在真实强杀后同样零重新采集、全部 MinIO 文件字节一致；受控 README/pom 修改、单机/同一 PG/MinIO、静态代码均不代表上游变更、跨主机恢复、业务 gold 或目标执行。

## 分层及兼容边界

领域值对象仅校验固定身份、范围、摘要和原输入一致性，不 import ORM、S3、Temporal 或 HTTP。Application 依赖 `SourceAcquisitionIntentPort`；基础设施保存事实，production composition 显式装配，canonical handler 传递实际 invocation ID。缺端口拒绝，不静默走旧 inline 分支。

内部 legacy 直接调用且没有 invocation ID 的路径仍按原接口工作。尤其 `context.materialize` 的旧兼容采集还没有完成此入口切换，不能因此宣称全项目已有单一采集 write authority。repository 的 `get` 是可信内部读，不是公开、已重新授权的用户查询接口。

## 配置账号与当前权限

准入要求实际 PG 活跃账号；不能以环境变量里的 UserProfile 代替账号事实，也不在采集／查询时创建账号。Composition 仅在本地／disabled 模式或显式配置静态 bearer 时执行启动登记；required/session-only 模式不创建默认操作账号。启动登记使用项目无关的 ID／邮箱锁，拒绝接管已有密码账号或冲突邮箱。配置账号使用不可用于密码登录的标记，不签发登录会话；重复启动不覆盖状态、角色、头像或其他资料。

受保护 HTTP 请求通过独立只读 adapter 重新核验该确切 ID／邮箱／账号类型及 active 状态，使用 PG 当前角色和资料，不使用启动时角色缓存。停用、缺失或身份被替换返回 401，缺少 verifier 或 verifier 失败返回脱敏 503；不存在的身份不由请求重新登记。真实登录会话仍走原 session adapter，不替换成配置账号。健康、登录和注册等公开路由不要求配置账号有效。此修复不代表已实现所有运行中任务的强制取消、长连接全程账号核验或跨域治理事务。

## 历史事件与固定页面重读

Conversation SSE 刷新调度在事件到达时记录匹配 query 的实际 fetch promise。200ms 合并窗口内，只有该次早于事件的读取仍在进行时才安排针对确切 query 的第二次核验；事件后才挂载的私有分页组件不进行 prefix-wide 二次读取。实时消息的 setQueryData 会改变数据计数但不表示原快照请求已完成，因此不用数据更新时间推断请求寿命。失败 query 不被这次 follow-up 自动重试，后续独立事件仍可要求重新授权读取；关闭、路由范围 guard、focus revalidation、StrictMode 和 `cancelRefetch:false` 保持原契约。该调度不缓存访问权，不改变服务端证据页的字节预算或历史页大小。

## 仍需完成

intent/结果消费不保证连接器 exactly-once。0095 提供原 running 命令结果消费与兼容工作区重做底座，已有显式新 OS 进程恢复专项，尚无生产重启后自动调度或独立进程 lease 恢复验收。还需实现以下原要求：

- 持久 owner/epoch lease、heartbeat、取消和 Temporal admission/dispatch，API accepted 的实际延迟门禁。
- 将逐来源结果/manifest 消费接入持久任务生命周期、真实进程故障及自动恢复；兼容工作区/chunks 与任务终态仍需一致提交协议。
- 原输入/事实/审计/Outbox 的一致性、对象归档与 PG 失败窗口、孤立对象保留及 GC。
- maintenance policy、webhook inbox 的验签/去重/合并、周期 reconcile，以及自动 delta/失效/调查/重建。
- 完整旧链切换、版本 overlay/合并、全计划费用与取消、五用途上下文、真实目标执行、Provider 对照/gold/容量及 P6 门禁。

## 验证范围

`test_source_acquisition.py` 验证纯领域与 application 的顺序、错误脱敏、缺端口和准入后撤权。`test_source_acquisition_intents_api.py` 通过真实 canonical HTTP、隔离 PG 和私有 MinIO 验证连接器前的 intent、并发重入、范围变化、当前权限、Outbox 回滚、数据库不可变性和损坏元数据拒绝；deliberate damaged-restore fixture 仅允许在 `nasus_test_*` 库中运行，正常生产触发器仍保留。

`test_source_acquisition_results_api.py` 验证提交后中断的 fresh application/connector/repository 消费、部分来源恢复、结果与 inventory/revision 的 Outbox 原子回滚、清单头/receipt 原子回滚、其他命令推进后拒绝、失败结果不重试、当前 ACL、历史不可变和事件清理后的缺历史拒绝。中断由明确 BaseException 夹具施加于真实事务之后，不冒充真实操作系统进程 kill 或 Temporal 故障。opt-in exweb 验证 126 个实际 blob 的原 MinIO 文件字节及零重新采集；受控 README/pom 变化不是上游新提交、业务 gold 或目标执行。

`test_source_acquisition_processes_api.py` 另行验证实际 SIGKILL、独立新进程、selected/whole 的两处提交窗口、重复恢复、即时撤权及其他命令竞争。`source_acquisition_process_probe.py` 只允许 disposable `nasus_test_*` PG 与 `nasus-test-*` 私有 MinIO bucket，不启动/迁移开发服务。opt-in exweb 进程报告与原 BaseException 报告分开，明确 `automatic_dispatch_verified=false / temporal_lease_cancellation_verified=false`。

`test_source_refresh_exweb.py` 使用获准的固定 exweb commit `fe5827f6b76f77ef34918d8b452ee823142332dc` 的 126 个 Git blob 导出，通过正式注册/采集命令核验准入、命名 reader、按来源刷新和旧归档回放。受控 README 变化及伴随 US/测试是明确验证夹具，不是上游新提交、真实业务 gold、原生远程 Git 采集或目标执行。报告明确 `acquisition_lease_or_crash_recovery_verified=false`。

Portal 的真实代码证据测试不再假设会生成无来源占位对象；旧无 pin 观察通过独立、明确的 legacy DTO transport fixture 验证提示、零证据请求和焦点恢复，不增加生产画像成员。冻结读缩页测试只排除实际观测到的 `net::ERR_ABORTED` 请求；未取消的重复读取仍受精确序列断言约束，不关闭 focus revalidation 或 StrictMode。

每批实际终态及失败历史见[实施记录](./implementation-progress.md)。专项通过不替代完整 V1 门禁或原 P0-P6 目标。
