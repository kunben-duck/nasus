# 固定清单下的按来源刷新

更新：2026-10-09（Asia/Shanghai）。本切片补齐 P4 的显式按来源采集及 Portal 操作入口，不代表自动维护、完整项目增量图或 P0-P6 验收完成。

## 命令与范围

沿用 canonical `system_image.sources.ingest`。旧输入只包含 `project_id` 时，仍采集全部已注册来源；新增选择模式同时要求以下三个字段：

```json
{
  "project_id": "project-id",
  "source_ids": ["registered-raw-asset-id"],
  "expected_manifest_id": "manifest-id",
  "expected_manifest_hash": "sha256:exact-observed-manifest-hash"
}
```

`source_ids` 是项目注册来源的 RawAsset ID，不是 Provider 私有节点、文档 ID 或任意 URI。必须为 1–100 个唯一字符串；null、空集合、重复、超界和缺字段均失败，不退回整批采集。选择模式要求已经存在来源清单；首次初始化仍使用原整批入口。

application 在原项目 mutation guard 内核验当前 manifest 的 project/ID/hash，再验证选中 ID 全部属于项目的非占位来源。错范围或过期清单在来源采集、项目状态和分片修改之前失败；不回显传入的私有 ID。另一个命令已推进清单时，调用者必须重新读取和决定，不自动换用最新清单。注册来源但尚未采集的新绑定仍会在完整新清单中表现为 pending，不因已有输入清单而被省略。

只对选中来源设置 ingest 状态、运行 connector、登记 inventory/capture。未选中来源的内容摘要、权限观察、时间和修订引用不改变。文本分片只重建选中且成功的来源；未选中分片的 ID、工件引用和时间保留，且不重新读取其原文。最终清单仍包含项目全部已注册来源，不能把一个来源的成功冒充其他来源已刷新。

选中可选来源失败会记录 gap、从当前清单排除失败修订，并删除该来源的当前分片；原 PG SourceRevision 和旧冻结清单不删除、不修改，也不把旧资料冒充新修订的批准 oracle。任何已注册必需代码来源失败仍阻断整体成功，即使另一代码来源健康。尚未实现把旧成功可选修订显式作为带 freshness/gap 的新画像成员消费。

canonical input 固定选择与旧清单；result 引用选中来源及前后 manifest，并只列出来源修订/inventory 的证据 ID。已完成的相同幂等命令回放原结果，不再次连接来源。采集成功不重建、批准或发布画像，也不修改已有 ContextPack、生成结果或审阅事实。后续推荐 `system_image.build.structure`，需独立准备精确 manifest/plan/consent。旧 `context.materialize` 仍整批再采集，不应作为选择模式的自动后续动作。

## Portal 操作与失联恢复

Knowledge / 系统画像知识页提供 `Refresh working sources / 更新工作区来源`。独立弹层重新读取当前项目的 working draft，要求明确的同项目 manifest ID/hash、完整未受来源筛选的注册范围及唯一有效来源 ID；published、legacy、source-filtered、错项目或摘要无效的结果不展示旧选择。初始占位来源不能提交，多个代码 binding 保留为独立选项。

默认不选中任何来源。用户选择 1–100 项后，提交前固定展示过的清单、选中 RawAsset ID 和原 idempotency key，只发送一条 canonical 命令。开始提交后锁定选择，不自动重试、不执行推荐结构/物化/发布工具。同一完整清单及注册范围的只读重载不会清空选择；manifest 或注册范围变化、读取失败会清空选择，旧范围重新出现也不恢复先前同意。读取期间隐藏旧列表并禁用提交。

收到回执后校验原 tool、project、idempotency key、选中数组、前置清单、终态和完整结果引用；选中来源回执不能变成整批结果或新的发布。终态后只使读模型失效，新的刷新需要用户明确重新读取并重新选择。原操作选择和 request/command ID 保留在当前弹层里，不因新的只读清单而重新绑定原请求。

丢失回执时保留原 request 和固定输入，禁止重新提交；显式 `Check original refresh command` 只 GET 原命令。未知 command ID 先使用 `/v1/tool-invocations/resolve?project_id=...&tool_id=system_image.sources.ingest&request_key=...`，再 GET 校验后的确切 command ID。服务端按当前认证账号的 actor scope、canonical tool 和原 key 查询 PG 唯一索引，不扫描列表或审计历史，不受 256 条发现窗口限制。只解析无 conversation 的原 actor-scoped 请求；不能把会话范围 key 当成账号范围 key。未发现返回 null，错参数拒绝；均不能触发新 POST、latest 回落或新 key。关闭弹层会 Abort 这个只读恢复请求，发现返回后再次检查取消状态，避免取消后再读取详情；关闭不取消或撤销已经提交的来源采集。恢复中的 UI 更新受组件存活检查约束。

沿用共享证据弹层的 light/dark token、焦点返回、Escape、移动尺寸和无可见滚动条的滚动体验，长 ID 换行。

2026-10-09 新增同标签页恢复记录：按当前已登录账号和项目的独立 sessionStorage key 保存 schema、原 request key、选中来源 ID 和确切旧清单 ID/hash。原 POST 前写入并回读核验，失败则不发送命令；不保存 token、URI、凭据、正文、结果或授权状态。重新打开、页面刷新和跨路由只恢复指针并锁定新选择，不自动 POST、GET 或确认。用户显式查询时仍由当前账号重新鉴权，完整校验原输入及回执；已知 command ID 直接 GET 原命令，不借 latest／新的来源 head 重新绑定。未知 ID 使用上述精确 resolver；客户端不能通过 actor_id 查询别人的原 key，或通过选中 scope 代替后端授权。

校验通过的 command ID 可追加到同一指针，不能换成另一个命令。终态不自动清除记录；用户显式重新读取来源时先核验并删除确切原记录，再清空选择，下一次采集需要新的选择。账号／项目切换重建组件，不复用其他 scope 的 in-memory attempt。损坏、超大、错 scope 或不可用存储保留阻断，不过期丢弃或静默覆盖；本地指针是可篡改的提示，不是访问授权或服务端执行事实。关闭标签页、清除浏览器存储或跨设备后的 UI 指针恢复尚不保证。

0094 的[不可变采集准入](./source-acquisition.md)已在 canonical connector 前固定命令、来源身份与 origin manifest，并原子保存 intent/Outbox。跨进程 lease、崩溃终态恢复和 PG/对象归档的统一提交仍待交付，不宣称 exactly-once。

## 采集写侧的即时来源授权

`SystemImageSourceIngestionApplicationService` 通过独立的 `SourceScopeAuthorizationPort` 检查当前项目成员与来源策略，不把 canonical 工具角色当作来源读取许可。production composition 显式注入该端口；未装配或策略存储不可用时拒绝采集，不回退为允许。清单／选择格式仍先按原契约校验；来源身份必须唯一且属于原项目，旧整批入口同样不能接纳错项目的 projection。

首次检查在来源 ingest 标记和 connector 之前。选择模式要求全部选中来源可读，不要求读取未选中的受限来源；旧整批模式要求全部实际注册的非占位来源可读。固定同一权限 scope，并在每个 connector 前、返回后、采集失败登记前、capture 接纳前及清单／分块／终态推进关口复查 fingerprint。权限变化停止整条命令，返回脱敏 `source_access_denied`，不误报为缺代码或可选来源 gap；授权端口不可用为 `source_access_unavailable`。

当真实采集返回后撤权，尚未登记的 inventory／SourceRevision 不接纳，不冻结新清单或派生分块。恢复权限后需要独立新命令；旧失败回执不改写。业务完成之后、HTTP POST 回执返回之前还有独立的资源权限复查，确认返回同样适用；此时撤权返回 403，保留先前合法完成的事实，不倒写 completed 为 failed，也不重新执行来源。

这些是明确阶段的实时检查，不是跨存储授权事务或进程恢复协议。connector 在撤权前后可能已经写入私有 MinIO 工件；此前已合法接纳的其他来源修订不会回滚。命令中途拒绝后，已持久的 ingest 开始标记仍需后续 intent／lease 终态恢复处理；不能用本检查宣称整个采集原子化、孤立工件已清理或 exactly-once。下节补齐采集回执列表的返回前整批检查；来源注册 metadata、其他旧读取／物化路径、模型出口和完整读写事务的一致性仍需要各自验收。

## 回执的即时来源授权

详情、精确 resolver、命令列表和关联审计都先检查当前项目权限，再通过 application 资源端口检查来源权限。按来源刷新核验原选择、清单 pin 格式及选中 RawAsset ID 的当前范围；返回前重查权限 fingerprint。缺字段/错格式返回 409，撤权/未知来源返回不含私有 ID 的 403，资源授权端口缺失时读入口返回 503。列表及审计在排序前排除无权或不可核验的记录；孤立审计不能作为另一条读取旁路。

命令列表与关联审计完成查询筛选、逐条鉴权及历史排序后，还必须通过 `require_batch_access`。仅对最终可见的采集回执解析原选择并按项目合并，旧整批记录要求该项目当前全部注册来源可读。随后 `SourceScopeAuthorizationPort.require_current_many` 使用独立 READ COMMITTED 读取会话，通过一条 PostgreSQL `UNION ALL` 语句同时观察全部相关项目的存在性、当前成员角色、来源 inventory、策略和 ACL epoch，并核验固定 scope 的 fingerprint 及前后 actor 身份。不把逐项目重复检查冒充整批同一快照。

较早记录已获准、但读取后续记录或历史排序期间发生来源撤权、成员删除或角色变化时，拒绝整份响应并返回脱敏 403，不返回先前接纳的部分列表。第一次逐条检查即无权的记录仍按原契约排除；端口不可用或最终可见项目超过 128 时返回脱敏 503，不截断权限检查。空列表或没有采集回执的列表不触发此关口。恢复授权后的独立读取返回原历史，原命令、来源事实和修订不改写。

此保证止于 application 返回前的最后一次 SQL 授权观察，不锁定未来的权限变更，也不保证随后 HTTP 序列化／网络发送期间的权限原子性。它只覆盖采集回执和相关审计，不证明所有 Tool、原历史 manifest 成员闭包、模型出口或全部读写路径已完成权限治理；128 项有界拒绝也不是完整分页和容量验收。

旧整批 `sources.ingest` 回执没有明确选择，因而要求当前项目全部已注册 binding 可读，不能只检查项目成员身份、一个允许来源或当前页面筛选结果。命名 reader 可在拥有全部来源权限时读回原结果；管理员仍按可信的当前项目角色授权。检查 inventory 后再次复核 scope，防止期间降权或策略变更。该兼容关口不补造旧 manifest pin，也不是完整原历史来源成员闭包的证明。

canonical Runtime 的幂等请求命中、PG 唯一插入竞争返回旧命令及确认入口复用同一个资源权限端口；已经 completed 的命令也必须复查，waiting_confirmation 的撤权不能消费 claim 或追加确认审计。恢复权限只返回原历史，不重新执行 connector、不推进清单、不改写旧回执。运行时依赖端口，不直接访问来源 ORM。

共享 Conversation 快照和新/旧 Outbox 事件只展示采集命令的生命周期：清除 input、result、内部幂等字段，将摘要替换为固定状态文字，事件外层 patch 同样只保留 status/tool_id/脱敏摘要。敏感详情需要独立重新授权读取。历史 Outbox 的持久字节不改写，重放时生成脱敏副本。此范围仅为采集回执，不声明所有工具、生成消息、首次写动作的来源权限或模型出口已完成。

## Git 快照污染检查

revision-specific cache 继续拒绝错 HEAD、修改和新增普通文件；额外拒绝被 `.gitignore`／`.git/info/exclude` 隐藏的文件、assume-unchanged／skip-worktree 索引标志及符号链接 `.git` 元数据。发现污染时失败，不删除文件、清理用户内容或静默重建同名快照。下游归档字节/hash/证据验证保持不变。

这不是 Git 对象库、全部本地配置或操作系统隔离的完整安全证明；原 Provider/来源进程隔离与供应链验收范围不缩小。

## 验证及后续

- `test_source_refresh.py`：纯选择输入、清单范围和写前拦截，含旧整批调用兼容。
- `test_source_refresh_api.py`：实际 HTTP/canonical Runtime、PG/MinIO、未选中来源与分片不变、已完成命令幂等、真实清单推进后的旧请求拒绝、可选/必需来源失败及历史修订保留。
- `test_source_ingestion_access.py`、`test_source_ingestion_access_api.py`：缺端口／错范围／策略不可用时写前拒绝，真实 PG 的首次来源撤权、connector 返回后撤权及完成后回执返回前撤权；授权恢复不改写原失败／完成事实。实际 PG 还验证可读需求的单选更新，即使未选中代码来源受限且物理文件已删除也不读取它；整批入口仍拒绝，没有降低完整范围权限要求。
- `test_tool_invocation_resolution_api.py`：真实 PG 的 260 条噪声历史后精确恢复、账号/项目/会话范围、来源撤权/恢复、读取进行中真实 PG 策略变化、旧整批回执、共享 Conversation 和应用层 SSE 的原 Outbox 重放；该 SSE 检查不是实际 HTTP 网络流测试。
- `test_source_refresh_receipt_access.py`、`test_source_access.py`、`test_tool_invocation_runtime_ports.py`：选择格式、完整来源权限、检查中撤权、缺端口拒绝、共享副本脱敏、确认 claim 保护及唯一插入竞争重放。
- `test_source_receipt_batch_access_api.py`：真实 HTTP、PG 策略与私有 MinIO，覆盖较晚记录检查前后撤权、全部逐条检查结束后的策略／成员／角色变化，以及两个真实项目的同批校验。跨记录用例在测试 state 端口明确安排真实 PG 行的检查顺序，不依赖无序 scan 的物理顺序；不伪造事实、鉴权或 403。授权恢复后原列表、命令和来源事实不变。
- `test_source_access_repository.py`：实际 PG 验证多项目授权只执行一条 SQL，涵盖策略变化、成员删除、空项目和缺失项目；无效 cohort 在连接数据库前拒绝。纯端口测试另外验证 actor 改变、错项目、重复／超界 scope 和缺批次端口。
- `test_source_refresh_exweb.py`：明确 opt-in 的固定 exweb Git blob 导出，经正式注册/采集工具进入隔离 PG/私有 MinIO。原 commit 为 `fe5827f6b76f77ef34918d8b452ee823142332dc`、126 个文件；新增 README 验证文本是受控夹具，不是上游新提交或业务变更。伴随 US/用例也是明确协议夹具。真实 tester 在代码来源受限时零 connector 调用、PG 来源事实不变，增加命名 reader 后独立新命令才成功。只有选中代码修订变化，文件差异为 1 modified / 125 unchanged，旧代码归档仍完整回放。整批权限用例在至少两条 completed 采集回执分别获准后才撤权，验证整份列表拒绝、恢复后历史一致，不假设内部枚举顺序等于响应时间顺序。
- `test_git_source_connector.py`：实际临时 Git 仓库，验证忽略规则、索引绕过和符号链接元数据污染，保留原双修订与旧修订恢复测试。
- `tests/unit/source-refresh.cjs`：固定选择/清单、回执校验、只读原命令恢复、取消与拒绝错误 scope，不发送自动后续写入。
- `tests/unit/source-refresh-recovery.cjs`：同账号／项目指针、严格字段与范围、存储前置检查、损坏保留、command ID 不替换和显式清除；这些纯测试不替代后端 ACL 验证。
- `tests/e2e/source-refresh.spec.ts`：隔离 PG/私有 MinIO 的真实 canonical 提交、未选中来源及旧画像不变、同 scope 重读、失联 GET 恢复、实际 head 变化拒绝、客户端坏 scope 隐藏和深浅色/中文移动端。固定 exweb Git 导出有明确 opt-in，所有 126 个文件经正式采集；受控 README 文本不是上游提交。滚动与关闭取消的实际批次终态单独记录。

0093 后续新增[显式 Git 分支与标签来源](./source-tracking.md)，ref 属于不可替换的 binding 身份，选择刷新继续固定原 binding，不改用另一分支。0094 新增独立的 canonical 准入 intent，但没有 Temporal 采集调度/lease、维护 policy/webhook inbox、验签/去重/合并窗口或周期 reconcile。采集 inventory、SourceRevision、清单与兼容 projection 仍不是一个跨存储原子事务；进程在终态前中断后的完整恢复尚待实现，不能承诺 connector exactly-once。全项目 delta DAG 的自动失效/调查/重建、overlay/tombstone/三方 merge、全计划预算、五用途上下文及真实目标执行与最终门禁继续保留原目标。

实际批次结果和失败历史见[实施记录](./implementation-progress.md)。本功能的手动有界入口不能替代持续更新的完整交付。
