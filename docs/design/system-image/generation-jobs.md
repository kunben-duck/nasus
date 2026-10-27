# 原生测试生成的持久任务与恢复

状态：0060-0065，2026-10-03。实现基于已有 ToolInvocation 和 Temporal；0062 补充 PG worker 租约，0064 接入完整多批执行及元数据进度，0065 接入独立新命令的完整回执恢复。不是第二套生成任务事实源，也不是完整 P5 验收。输入、预算和结果规则仍使用[固定生成契约](./test-design-generation.md)。实现与当前测试终态分开，最终验证范围见[实施记录](./implementation-progress.md)。

## 生命周期与派发

- `quality.test_design.generate` 的确认先持久化 canonical running 命令，再启动固定 ID 的 `NasusTestDesignGenerationWorkflow`；接口不阻塞等待模型完整响应。任务 ID 为 `nasus-test-design-generation:<invocation_id>`，重复派发不能产生第二次 workflow。
- 只允许已配置的 Temporal；没有内联执行或本地无持久化 fallback。Worker 使用现有 task queue 的 `-test-design-generation` 队列。Temporal 管理活动重试、heartbeat 和取消；PG 的 ToolInvocation、原生调用预留、回复及草稿才是业务事实。
- 活动只接收 invocation ID，从 PG 加载固定原请求和原确认账号，再核验当前账号、成员、全部 source ACL、模型、publication、scope 和预算。Temporal history 不存来源正文、凭据或原生响应；基础设施异常转换为脱敏失败信息。
- 新 workflow 用 version patch 允许最多 64 批各自的 120 秒原生截止时间，另留 10 分钟校验/归档窗口，活动上限 138 分钟、最多 3 次活动尝试、总调度窗口 444 分钟。旧 history 重放仍使用原 10/30 分钟设置；heartbeat 超时保持 15 秒。这个外层有界窗口不增加已确认调用数、费用或来源范围，也不是性能达标声明。已有 claim 无已提交回复时结果不确定，绝不重发；已归档回复只能重放严格校验和草稿事务。
- Worker 每 5 秒按 ID 游标扫描未完成派发和取消回执；每页最多 100 项，单项失败不阻断其余项目。派发 acknowledgement 丢失保持 running，由相同 ID 重投；已终结 workflow 不被重开。

## 终态与取消

### 跨进程 worker 租约（0062）

生成和独立恢复活动必须先在项目锁内认领 `quality_test_design_work_leases`。固定 canonical input digest、project、invocation、随机 worker owner 和递增 epoch，使用 PostgreSQL `clock_timestamp()` 设置 90 秒有效期；每 15 秒续租，只锁精确租约行，不等待项目锁或命令行锁。业务事务可能在这些锁内耗时回读全部上下文，续租不能等待自己的业务校验；所有权复核从 PG 刷新租约，不能使用事务 identity map 中旧的有效期。不用本机时钟判断另一进程是否存活，也不将 Temporal heartbeat 当成 PG 独占权。

仍有效的租约使重复活动或未持有租约的 fail/reconciler 返回可重试基础设施错误，不得把正在生成的命令提前标为 failed。过期或已释放后可以认领更高 epoch，但不能改绑原 canonical payload。续租失败取消等待中的 adapter；旧 worker 的释放只匹配原 owner/epoch，不能释放接替者。

当前租约检查贯穿调用预留、模型调用前后、私有回复写入后的 PG receipt 提交和草稿事务。与项目锁内的权限/依据复核同时执行；已经被替换、过期或 canonical 命令已 cancelled 的 worker 不能提交迟到回复或结果。取消原子终结命令并使租约失效。租约是可变执行协调记录，不是新批准、来源权限或费用事实；job API/Agent 回执不暴露 worker owner。

活动退出释放自己的租约，释放失败依赖 PG 过期；取消 `to_thread` 不能停止已运行的线程，因此不能只依靠 task cancellation，事务回调仍检查 fence。原生预留/回复不因租约失效被删除或退款。接替者只有已完整归档回复才能恢复后续提交；有预留但无回复仍是不确定调用，绝不自动重发。

此租约已接入单次生成/恢复、完整多批生成及独立完整多批恢复；所有 provider/index/build 的统一租约仍未交付。

0063 的[分包账本与私有回执](./generation-batch-ledger.md) 复用该 lease port 和同事务 fence，不新增任务生命周期。composition 将 native batch executor 接入相同 Temporal 活动，精确 planning digest 选择单次/多批路径；已经预留的多批命令不得回落到单次执行器。业务完成仍要求实际提交结果，不能仅凭所有 reply 存在将命令标为 completed。0065 的恢复活动从完整版本化请求读取原失败调用集，使用新命令自己的租约，不重开原命令。

`query.quality.test_design_job` 要求当前项目管理员和原请求的全部来源权限。它只返回固定 scope、canonical 状态、预留/回复是否存在、结果 ID 及可用的精确恢复请求，不返回原文或对象 URL。

多批 job 附 `nasus.test-design-batch-progress.v1`：planned/claimed/archived/unknown/unstarted、完整预算及已知原生 usage 的 operator-rate 金额。不暴露正文、凭据或 worker owner。部分已归档且后续未认领不等于 unknown；unknown 只指已认领无已提交回复。只有全部回复已归档、原命令 failed、无结果且原确认管理员当前仍有权限时，才提供 `nasus.test-design-batch-recovery.v1` metadata offer；其他情况 `recovery_request=null`。不借用单次 DTO 或提供未知调用重发按钮。预留不释放，不宣称账单核验。

`quality.test_design.cancel` 是独立 user-confirm 命令。PG 在项目锁内重新验证当前管理权限、cancel payload、会话/goal scope 和目标，先原子记录 cancelled、审计、Outbox 和 `quality_test_design_cancellations`，再发送 Temporal cancel。RPC 失败由 Worker 重投；不会因暂时取消投递失败丢掉用户意图。账号停用后其他当前管理员仍可停止任务，但不能继承该账号的来源出网同意。

属于本命令权威的已提交草稿优先于迟到的取消/失败：ToolInvocation 收敛为 completed，不删除已提交案例或覆盖。独立恢复结果不能让原 failed 命令重开，也不能让另一竞争恢复命令冒领 completed；竞争命令的 job 不返回其他权威的结果 ID。取消不释放已收费或未知的原生调用预留、不将已输出回复换成另一个模型、不自动创建新生成命令。

## 失败命令的显式恢复

自动活动重试仅在原命令 running 期间有效；failed 命令不能通过再次 confirm 或同 workflow ID 重开。只有原 confirming actor 仍具当前管理及来源权限、原生响应已完整归档、原请求/模型/范围/authority 仍有效且没有草稿时，才可独立确认 `quality.test_design.recover`。

旧单次恢复请求固定 project、原 invocation ID、原 request hash、reply artifact hash 和 response hash。新版多批请求另外固定 schema、reservation/plan/replies digest 和完整有序的每次调用摘要，严格拒绝未知 schema、混合 DTO、缺批或私有字段。新的恢复命令需要 15 分钟内真实确认，并校验原会话/goal、新命令作用域和完整 PG 回执。它不调用模型、不修改原 failed 命令、不重写原调用审计。

单次恢复结果使用 `nasus.test-design-result.v2`；完整多批恢复使用 v4，保留原 invocation/全部原生 call/source pins，另外记录 `recovery_invocation_id`、完整恢复请求及 PG 追加式权威关联。旧 v1-v3 历史字节不变，私有存储显式允许对应 schema，不接受任意 JSON。历史读取验证两条 canonical 命令及精确回复证明，但不要求过去的确认永不过期；当前来源 ACL 仍即时生效。未知、取消后未归档、无原生 usage 或范围变化均不能恢复生成。

## 有界历史读取

`GET /v1/projects/{project_id}/quality/test-design-jobs` 固定 `scope_revision_id` 和 `scope_artifact_hash`；`after_id` 为不透明命令 ID 游标，`limit` 默认 20、最大 50。按 ID 稳定排序，不声称是时间顺序或最新任务。服务端只选择该范围内已确认的原生生成命令及其恢复命令，不读取全站审计后交给浏览器筛选。

每项仅返回 `invocation_id/source_invocation_id/tool_id/status`，另有请求 pin、下一游标和 `has_running`。运行标记针对全部匹配命令，而非当前已加载页；它是本次读取的观察，不是跨语句数据库快照、独占锁或生成许可。并发写入后客户端需要重新读取，真正写动作仍由 canonical use case 的当前权限、版本、预算和事务约束决定。`generation_authorized/execution_authorized` 均为 false。

读取要求当前项目管理权限，验证固定范围、上下文工件及来源权限，返回前再次检查 ACL epoch。每页核验命令 DTO；损坏的持久命令返回脱敏完整性失败，不把模型输入或原文塞入错误信息。`private, no-store`，没有完整源码、token、对象 URL 或模型回复正文。历史范围失效可以调查旧元数据，但不允许沿用旧依据生成。

Agent 可调用 `query.quality.test_design_jobs`，使用同一 application port 和分页规则；回执只存元数据。正式观察消费重新验证项目作用域、当前来源权限和相同页内容，状态变化后旧回执失效。工具无确认要求，不继承任何生成预算或出网同意。

Portal 按固定 scope 和当前登录会话分页，每页 20 条，只有用户点击“加载更多生成记录”才请求下一页，不自动遍历全站历史。页面逐页验证请求回显、严格递增 ID、唯一命令、原命令/恢复命令关系和非授权状态；分页读取失败隐藏此前缓存记录和草稿。存在未加载的 running 命令时也禁止新的预算预览/生成，并提示加载更多；运行观察按 5 秒重取已加载页，不能替代后端写入检查。

新确认命令保持选中，即使其 ID 不在第一页内；只有重新授权的 job 回执通过校验后才作为额外选项显示。不把分页 ID 当作时间戳，不为了定位新命令自动扫全量历史。job 按 3 秒读取，running 到终态的转换只触发一次历史刷新，避免选中未加载终态与其他 running 并存时不断重取。查询、取消和归档恢复仍使用各自原有 canonical 命令。

## 验证与仍需交付

API 使用隔离 PG 与明确 native HTTP transport；真实 Temporal 测试使用独立 task queue，分别验证活动重试不二次调用和 provider await 中取消。exweb 使用固定干净 commit、真实 PG/MinIO 和明确伴随需求/模型响应，示例自身不执行目标代码，也不把 native usage 夹具当成外部账单或业务 gold。

Portal 在归档范围中显式打开生成面板，选择已测试非 legacy 模型并填写 token/费用上限；初始不选模型、不发送源码。预览固定完整来源和配置，用户另行确认后才创建/confirm canonical 命令。变更字段、模型或依据清除确认；忙碌时禁止重发。任务按 3 秒读取，终态刷新历史；同一 job 内容的轮询不抹掉准确取消确认。来源/权限/工件失效隐藏旧正文，历史恢复是新确认命令，未知调用不提供重发入口。草稿只展示 planned，独立映射和执行计数仍为零。

Portal 最大调用数默认 1，保留旧单次 consent；显式设为多次时使用 `query.quality.test_design_batches`，验证完整计划 hash、operator policy 和累计预算后再确认相同 `quality.test_design.generate`。更改调用上限与其他预算字段一样清除确认。多批部分归档不展示部分业务草稿；完成读取 v3 全调用证明，刷新恢复和撤权清屏继续沿用固定 scope。

当前浏览器及 Temporal 专项的实际终态见实施记录；生成 transport 是明确 UI fixture，不能替代原生 Provider、Temporal 或 MinIO 的独立验证。0061 已提供独立断言映射审阅，但不代表真实执行覆盖。0065 完整多批终态恢复的代码已接入，当前公共/Temporal/MinIO 门禁仍按独立结果验收。旧生成链切换、五用途上下文、RunPlan 和真实执行反馈继续属于原目标。单次请求不适配容量时明确失败，禁止删减强制项来换取本切片绿色。临时 MinIO 对象 GC、完整 provider lifecycle/gold 与最终发布门禁仍未完成。
