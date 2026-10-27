# 原始 fixture 执行命令关联

更新：2026-10-13。0114 增加原命令事务防线，0115 后续接线正式 fixture Tool、
Temporal 任务和追加式取消/投递事实，0116 增加原命令准备回执与绑定前恢复，
0117 增加绑定前的授权只读观察与独立持久取消，
属于 P5 的实现增量。当前契约测试与离线 DDL
已验证，真实 PG/MinIO/Temporal 和 exweb 公共端到端链尚未验证，执行 Portal 尚未交付。
不能据此宣称完整 canonical RunPlan 执行、独立未知结果恢复或业务覆盖已交付。

## 领域、输入与生命周期

- `ToolInvocation` 仍是命令状态权威，不另建 fixture job 状态机。
- `HttpFixtureExecutionSelection` 固定 project、原 native grant ID/digest 和单一
  setup/cleanup；不接受 URL、worker 身份、超时覆盖、结果或权限字段。
- `HttpFixtureCommandAuthority` 只固定原 invocation ID 与完整
  `tool_id + input_payload` 摘要。正式 job 从原 canonical 命令计算，不能
  从 Portal 或 Agent 的声明取得执行权威。
- 命令必须独立确认，确认人等于原 grant actor，当前状态为 running，完整输入不变。
  确认人必须是非空、有界且无控制字符的原身份；双方同为 null／非法身份不算一致。
  确认时间要求 timezone，并以 PG clock 检查 15 分钟；确认不能早于原许可。
  当前项目管理员、全部来源访问权、native target/健康、原许可及租约检查均保留。
- 历史关联允许命令已完成、失败或取消；保留原确认和结果，不续期、不创建 lease、
  不访问目标，也不把历史读取等同恢复执行。

## 持久化与同事务防线

`quality_http_fixture_commands` 保存不可变原命令、grant、actor、完整 scope、
RunPlan/native environment pins、source fingerprint 与 work identity。原 grant 和
work identity 分别唯一：同一操作不能被第二个命令接管。绑定前已有私有派发或未知
效果时拒绝新增绑定；同命令重复绑定核验原记录，不延长许可或修复历史。

`quality_http_fixture_dispatch_commands` 将每个实际 claim 连接到确切原命令和 intent
摘要；FK 同时固定项目、journal 与命令。两表追加式、拒绝 UPDATE/DELETE；有数据时
不能 downgrade。没有从旧私有 journal 回填或推导“已确认”命令。

显式命令分支使用 `nasus.http-fixture-dispatch.v4`，保留原 worker ownership 与
operation consent，另保存 `canonical_command` pin。journal 的 claim、complete 和
最终提交复核在原 PG 事务内对原 ToolInvocation `FOR UPDATE`，核验 running 和完整
输入。取消/终态写入必须竞争同一行锁；先成功提交的原事实保留，取消后旧 worker
不能提交新结果。外部 HTTP 已发生而未提交的效果保持 unknown，取消不是业务回滚。

历史读取同时校验原 command、grant、worker 和全部原字节。删除 v4 标记也不能降级：
原 work 已绑定时，丢失 dispatch command 仍报错；同一 project lock 序列化绑定与
私有 claim，绑定后的工作不能退回私有派发。cleanup 可读取独立 setup 的可信资源，
但不能把 setup 当成自己的派发或复制它的许可。

绑定事实、脱敏审计与 Outbox 同事务提交。原派发/结果审计关联原 invocation；绑定
事件固定原会话/Goal、时间及无正文 query key，重放只校验、不执行或补登记。

Outbox 在写入中以数据库 sequence 分配 `entity_version`，不能要求绑定事件在事实
校验时仍等于初始值 0。绑定事实接受非负、严格整数版本；持久化与重放仍由统一
Outbox 校验版本与原 row/sequence 精确一致且 sequence 为正。原 intent、项目、
会话/Goal、时间、query key、patch 和空 payload 校验保持不变，不以合法序号授予
派发或业务覆盖。新增 PG 测试检查非法 coverage patch 的整事务回滚、合法序号
绑定与重放，以及序号/patch 篡改拒绝；实际终态见实施记录。

## 公共任务与持久取消接线（0115）

- `quality.http_fixture.execute` 独立确认，管理员/source scope 和原许可确认人复核后，
  先绑定原 intent，再启动 `nasus-http-fixture:{invocation_id}`。任务 ID 不由客户端提供，
  不生成第二个命令或新 attempt。未知启动回执保留原命令，由同 ID 投递器重查。
- `query.quality.http_fixture_execution` 与
  `GET /v1/projects/{project_id}/quality/http-fixture-executions/{invocation_id}` 只读原账本。
  返回每阶段 `not_dispatched / outcome_unknown / observed` 和原状态；不创建 lease、
  不刷新健康、不读取任意 URL 或输出私有原字节。成功和分类错误均保持 private/no-store。
  来源快照变化保持 409，归档损坏为 502，不能由通用 ValueError 分支混淆。
- `quality.http_fixture.cancel` 单独确认确切目标，当前管理员和全部来源权限重新检查。
  在原项目锁和 ToolInvocation 行锁下，原 cancelled 状态、不可变取消请求、审计和
  Outbox 同事务提交；随后才发 Temporal 取消 RPC。另存追加式投递回执，服务失联
  不撤销取消，reconciler 先重投取消再处理可核验的 running intent／新准备命令。
- `quality_http_fixture_cancellations` 固定独立 control ID/hash、原命令/hash、actor 和
  PG 时间；`quality_http_fixture_cancellation_deliveries` 固定确切请求 hash。复合 FK、
  不可变 trigger 和 populated downgrade 拒绝保留完整历史，不回填私有取消为正式事实。
- Worker 重读原 command/actor 并执行已有 command/consent/owner fences；完成前重新读取
  全部原 archive，再在原行锁下写终态。未知或未派发阶段不能 completed，live lease
  不能被失败收尾越过，迟到失败不能覆盖 cancelled。HTTP 已发生但未提交仍是 unknown。
- 执行 handler 不再使用通用事件状态写入，避免重写已取消的原状态；收尾暂时无法核验
  时保留原命令，不退回无锁 failed。消息日志只含静态故障摘要。
- Agent 回执读取重新授权，query 结果必须与当前原账本一致；状态变化要求显式再查询。
  SSE broadcast 清除输入、结果和幂等字段，不把私有观察或权限带给其他订阅者。

这些接线没有增加专用执行 HTTP 写旁路，也不从定义/许可登记 handler 自动派发。
原全量 Tool ID 保留，普通测试执行意图不被 fixture 明细挤掉；明确 fixture 意图才优先
呈现定义、许可、执行、读取与取消的完整确认合同。planner 排序不是授权。

## 原命令准备回执与绑定前恢复（0116）

生产 `ConversationRepository` 通过 composition 注入 infrastructure claim journal。
新的 `quality.http_fixture.execute` 在原 ToolInvocation 行锁下从待确认进入 running 时，
同一 PG 事务保存 `quality_http_fixture_preparations`。记录只固定原命令／项目／确认人、
完整 `tool_id + input_payload` 摘要、原确认时间与 PG 记录时间；不保存凭据、目标响应、
scope、许可或工作身份。`fixture_claim_protocol` 是 server-owned 协调字段，客户端提交
时清除，业务 DTO 解析时移除，但原完整摘要仍包含它。其他 Tool 的 claim 不写该记录。

初次 intent 绑定在原事务追加 `quality_http_fixture_preparation_bindings`，固定准备与
intent 两个完整 hash。重复绑定只核验，不补登记；新命令缺准备回执、已绑定但缺 intent／
binding、标记被删除或降级、原列或摘要改变均拒绝。两表有精确 FK 和不可变 trigger，
不回填旧未绑定 running 命令，不把私有派发或损坏历史变成待准备工作。

投递扫描按原 ToolInvocation ID keyset 分页，包含已有 intent、新准备记录或新协议标记，
不扫描并自动执行所有旧 running 命令。application delivery 重新取得原确认 actor，
在其 actor scope 内复核当前管理员、来源权限、原许可与未续期的 15 分钟确认，再绑定
原 intent；启动前再次回读原状态和摘要。已知取消／终态不启动，绑定／收尾竞争重新检查
原 intent 与 live lease。Temporal ACK 未知或临时准备故障保留 running，下次仍用原 ID；
没有目标阶段的自动重发、第二个 attempt 或新许可。

只有完整准备回执可核验且没有 intent／绑定历史的新命令，才允许绕过非法 execution DTO
的解析来作静态失败收尾。项目锁、原 ToolInvocation `FOR UPDATE`、原完整摘要重新核验、
终态不覆盖、结果／审计／Outbox 同事务仍强制。过期、非法 selection 或权限撤销可以结束
原准备；丢失／损坏准备历史不能通过失败路径修复。该路径不能完成命令、创建许可或租约，
也不把未经完整原 archive 验证的内容变成观察结果。

0116 本身未包含绑定前观察／取消；后续 0117 的实现见下一节，实际公开 PG/MinIO
验证仍未执行，专用执行 UI 仍待交付。上述准备恢复不等于未知 HTTP 结果恢复、完整
公开任务或实际目标执行验收。0116 revision 为 `0116_fixture_preparations`，DDL 仅离线
验证，未应用开发库。

## 绑定前只读观察与独立取消（0117）

同一只读 HTTP／canonical query 先重新核验当前项目管理员与完整来源访问权，再读取
原 command、准备回执及未续期的原确认。已绑定的原任务继续使用 v1 phase/archive
协议；新未绑定任务返回 `nasus.http-fixture-job.v2`，包含原 selection、request/preparation
digest、原状态与 `preparing / preparation_failed / preparation_cancelled`。它明确返回
`intent_digest=null / phases=[] / target_observation_verified=false`，不是伪造的目标观察。
读取不创建 intent/binding、租约、许可、审计或 Outbox，不打开目标执行归档或查询 live
健康；当前来源权限在返回前再检查。无可核验准备的旧任务不自动晋级。

取消仍只走 `quality.http_fixture.cancel` 的独立确认。项目锁和原 ToolInvocation 行锁
内重新确定是否已有 intent：绑定先完成则沿用 0115，取消先完成则追加
`quality_http_fixture_preparation_cancellations`，固定原准备完整 hash、独立 control/hash、
原命令/hash、actor 与 PG 时间。取消事实、原 terminal result、审计及两条 metadata-only
Outbox 同事务；不得为了取消补造 intent。旧 worker 的失败收尾或再次投递不能覆盖
cancelled，后续 bind/start 拒绝，原输入和准备回执不改变。

Temporal 取消 RPC 只发生在持久事实之后。成功或原 workflow 不存在的确认另存
`quality_http_fixture_preparation_cancel_deliveries`；临时失联只留下 undelivered 请求。
reconciler 将旧／新取消记录合并为全局 ID keyset 分页，先取消后准备投递，不新建
attempt 或续确认。同一 control／delivery 重放核验原 hash，不重复审计／事件。
两表有精确父 FK、不可变 trigger 和有数据时的 downgrade 拒绝，不从旧取消回填。

损坏／丢失原准备、原 command/control、错误分支、orphan delivery 或擅自插入的 intent
均拒绝，正常查询、重放及事件读取不能修复。请求和投递的非法／无时区时间统一返回
`HttpFixtureInvalid`，而不是任意 TypeError/ValueError；旧已绑定取消使用同一拒绝规则。
事件重放只接受确切无正文 metadata，不接受私有 payload 或虚构 Run/step 权威。

`cancellation_delivered` 只描述原取消 RPC 的投递，不代表目标已停止、HTTP 效果撤销、
fixture 已清理或 baseline 已恢复。准备状态及已有四项 authority 全部保持 false；
已发生但未提交的外部效果仍是 unknown，不能借取消或恢复自动重发。

0117 revision 为 `0117_fixture_preparation_cancel`，只生成离线 PostgreSQL DDL。
独立 PG 测试覆盖原 cancel/failure 行锁竞争、部分 Outbox 失败的事务回滚、幂等投递、
不可变 trigger 与非空 downgrade；独立 schema up/down/up 核对精确列／FK／trigger。
公共 PG/MinIO 用例新增准备只读、独立取消和暂时失联后的同 ID 投递，不读取目标历史
或补造派发。它们目前仅收集／语法检查，不是实跑证据。Runner/build/health/Temporal
transports 仍明确为 doubles，执行 Portal、真实 RPC／重启和完整业务闭环保持待交付。

## Portal 原始操作入口

2026-10-13 新增[独立 Portal 操作链](./http-fixture-portal-operations.md)：已核验 definition
之后回读原环境/native build 父链，保存显式 v2 许可，再分别确认原执行与取消。ACK 失联
只查询原命令，绑定前观察不制造 intent；unknown、failed、cancelled 无下一操作捷径。
该 UI 及协议契约接线不等于真实 PG、Temporal、浏览器 E2E、exweb 或完整业务闭环验证。

## 权威与验证边界

所有既有 `execution_authorized / canonical_execution_committed /
business_coverage_verified / baseline_restored` 仍为 false，旧工件与 hash 不修改。
命令关联并不批准 AC、证明 oracle 正确、增加执行覆盖或允许 release。

纯 domain/application/adapter/session specimens 覆盖取消、原输入及协调字段变更、
许可/work 重复绑定、旧阶段接管、重算 hash、标记删除、事件篡改与独立 gates；它们
不证明实际 PG 锁竞争。DDL 与模型注册可离线检查，不能代替 migration 实跑。

已补真实 PG/MinIO 测试的私有、原命令、派发后取消三条路径，以及独立 schema
up/down/up；后续增加公共 ToolRuntime/原 grant 防接管/持久取消、不可变取消表与非空
降级拒绝用例。Runner/build/health 和 Temporal 传输明确为 doubles，不是 exweb 原生
HTTP 或真实 Temporal 重启证明。Docker 停止，以上集成未执行到新任务。前次不带 PG
环境的 API collection 退出 2，不能写为收集成功；新增 0115 独立 migration 用例可离线
收集，仍未执行。后续必须完成真实 Tool/Temporal 验证、执行 Portal、独立 unknown 恢复、
真实覆盖回流及完整 P0-P6 验收；测试终态以[实施记录](./implementation-progress.md)为准。

0116 新增独立 PG claim 并发、flush 后异常回滚、失败收尾 Outbox 回滚、准备记录不可变
与非空降级拒绝测试，以及独立 schema up/down/up。三项可离线收集但尚未实跑。原公共
PG/MinIO 测试新增准备／绑定原 hash 断言和绑定前临时失联后同 ID 恢复，保留独立失败
oracle；仅语法检查通过，不作为 PG、Temporal 或 exweb 原生验证证据。
