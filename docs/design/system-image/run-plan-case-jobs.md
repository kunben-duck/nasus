# RunPlan 业务执行任务生命周期

更新：2026-10-13。本增量连接原 0118 执行核心、0119 原命令认领与公共 canonical
任务入口；不是完整 P5 验收、正式业务覆盖或发布许可。真实 PG/MinIO/Temporal 和
固定 exweb 公共目标执行链仍需完成。隔离 PG/MinIO journal/完整 case 专项及真实
Temporal retry/cancel/replay 专项已有终态；来源、模型或目标使用显式协议样本的
范围仍保留，不将其当作固定 exweb 完整业务证明。owned exweb 原批定位失败，
新版本已越过该点、正在独立全链验证。Portal 已接入完整引用、独立确认和原命令
历史面板，新旧 RunPlan 四场景的隔离 PG/MinIO 浏览器重跑也已通过，UI transport
仍是显式样本。最新批次、失败和未完成项见[实施记录](./implementation-progress.md)。

## 命令与查询

- `quality.run_plan.execute_http`：高风险、独立 user confirmation；输入必须包含原
  RunPlan、build binding、environment、locator 和完整有序 case/setup selection。
- `quality.run_plan.cancel_http`：高风险、另一条独立 user confirmation；固定原
  project/invocation。不能借原执行确认授权取消，也不声称目标回滚或 cleanup。
- `query.quality.run_plan_case_execution`：只读、重新授权的任务元数据。不返回原文、
  native request/response、归档地址或执行/coverage authority。

写动作仅通过 `ToolInvocationRuntime`。初始公共角色保持 project/platform admin，
与既有 fixture 私有历史一致；QA 端到端消费需要另行完善政策，不能绕过既有 ACL。
`GET /v1/projects/{project_id}/quality/run-plan-case-executions/{invocation_id}` 通过同一
application port 返回完整私有历史，响应和错误均使用 private/no-store。没有新增
可绕过 canonical surface 的 HTTP 写接口。

## 原命令调度

认领事务仍写 0119 preparation；handler 只调度原 invocation 的任务，不等待全部
业务 HTTP 返回、不提前将原命令改成 completed。未知启动 RPC 保留原 running 状态。
reconciler 从有界持久 ID 页重新检查原 actor、来源权限、完整命令和 15 分钟确认窗，
重投同一个 workflow ID，不续期确认、不建立新的业务尝试。

Temporal ID 为 `nasus-run-plan-cases:{invocation_id}`，task queue 为配置队列后缀
`-run-plan-cases`，使用 REJECT_DUPLICATE。已经结束的同 ID 任务不重开；Activity 的
重试先读原持久 work/claim/outcome。观察齐全、未知效果或取消先进入终态处理，
不能为了处理未知结果而重新取得租约或重发 HTTP。Worker 心跳、取消等待原工作
线程退出；调度和活动并发不替代 0118 PG lease/owner/epoch fencing。

Activity 区分原权限拒绝与临时基础设施故障：PermissionError、来源 scope 失效及
平台 403 返回不含原文的 `RunPlanCaseAuthorityDenied`，标记 non-retryable，
不靠重试延续原授权。fixture 使用相同分类和 `HttpFixtureAuthorityDenied`。
原命令进入现有终态 Activity；它仍核验 PG lease，不抢占活跃 worker，租约尚未
释放时终态处理本身可以重试。其他临时故障保留原 InfrastructureFailure 重试，
每次先读取原 claim/outcome，未知效果仍不得重发；取消继续等待原线程退出。
实际 Temporal 专项核验拒绝只调用一次、终态路径和原历史 replay，应用／账本
使用显式替身，不以此证明原 exweb 业务执行或 PG 终态事务。

原 confirmation TTL、12 分钟 Activity 和完整多 case 的执行预算之间尚需专项容量
设计和真实验证；不得通过截断原 case 或自动续期使大计划看似完成。

### 工作事务与非重入授权

工作线程的 `require_work` 包含单独的 PostgreSQL 租约事务，只能在 journal 写事务
之外调用。claim/outcome 写事务接收不回入 journal 的 `require_current`；repository
自己在同一事务内核验原命令、当前角色、取消事实、PG clock、owner 和 epoch。
禁止持有项目 advisory lock 时通过回调再次申请另一连接上的同一把锁。

acquire、renew、claim 和 outcome 在 flush 后、提交前再次执行完整 live fence。
账号和角色读取使用 `populate_existing`，不能因为 SQLAlchemy identity map 命中
而采纳已撤销的身份。最后撤权或 Outbox 异常回滚本次未提交的 work/lease/binding、
claim 或 outcome 及审计/Outbox；此前已提交的派发保留，仍可能是 outcome_unknown。
这不是目标副作用回滚，也不允许重新派发来消除未知结果。

## 取消与终态事务

固定 migration `0120_run_plan_case_jobs` 增加两张 append-only 表：

- `quality_run_plan_case_job_cancellations`：原 preparation、取消控制命令、确认人、
  完整 command/control digest、PG 时间。同 project/invocation FK 固定原认领。
- `quality_run_plan_case_job_cancel_deliveries`：原取消 digest 和同 ID 调度确认时间。
  不是目标侧 cleanup 或撤销证明。

取消可发生在 work 绑定之前。项目锁、原 Tool 行锁和控制 Tool 行锁内重验当前
角色/来源；原取消事实、Tool 状态、审计及 Outbox 在同事务提交。最后撤权使全部
回滚。Temporal cancel 在事务后执行，未知 RPC 留待 reconciler；delivery 的项目锁
和原 Tool 行锁使重复 ACK 只保存一次。先交付取消，再调度尚未投递的执行。

completed 只能基于完整原生归档重读及 durable roster/claim/outcome 匹配，原 case
执行失败也保留原观察，不将测试失败伪装为 passed。failed 等待活跃 lease 过期，
不能夺走仍在执行的 worker。已经终态的命令不重开。正式业务覆盖、automation、
execution/pass 计数与 canonical execution commit authority 仍为 false/零。

## 历史读取与回执

历史重读保持原 actor/source fingerprint、plan/build/environment/locator、完整七
case/setup pins 和物理归档。它使用当前读取者权限核验固定原始来源，不探测目标
健康、不要求计划仍为当前、不延长执行确认。cleanup 已发生或其结果未知时允许
回看原观察，但同一前提不能再被 live producer 接受。完整读前后核验即时 ACL、
原账本和归档；读取不修复丢失或损坏历史。

SSE/broadcast 只暴露清理后的状态，Agent 展开回执时重新授权。查询回执保留完整
分母、严格整数和互斥状态；部分/未知结果、未绑定状态不能伪装为 completed。
receipt 本身不授予新的执行权。新 canonical 工具仅在对应任务意图中提高发现排名，
不挤占旧生成/准备路径。planner v3 的无损 prefix 编码保留所有 ID、原顺序及治理
字段；字节预算仍为 6999，没有删除工具或扩大提示预算。

## 验证范围与缺口

### Portal 入口与恢复

`RunPlanPanel` 仅为全 HTTP 的原脚本计划挂载 `RunPlanCaseExecutionPanel`；领域 hook、
typed API、固定输入/历史校验和 session recovery 放在 `domains/quality-loop`，页面
不拼写另一套业务协议或直接调用目标。环境与定位记录经既有重新授权读取端口核验，
每个原 case 的 setup 命令都要从 private/no-store 历史读回，禁止省略、重排或重复。
核验只准备完整引用，不把元数据、setup completed 或 static locator 当成 live grant；
公共后端在独立执行确认之后重读原生证据、cleanup、target epoch 和当前来源权限。

创建前先保存完整输入、字段、请求 hash 和幂等 key；核验 ACK 后保存原 command ID，
再确认同一个 ID。ACK 丢失、刷新和重连只解析原 key/ID 并读取历史，不自动确认、
重发或建立替代尝试。取消保存另一份请求和确认，不能继承执行勾选。确认绑定完整
选择和当前核验结果；字段变化或重新核验会清空确认。

历史校验逐条保留原 roster、编译 job hash、claim ID、observation hash、步骤和 oracle
映射。页面明确区分已观察、尚未派发、效果尚未确认；completed 不是全通过，正式
执行/通过计数仍为零。读取错误或撤权隐藏受保护结果，不提供 unknown 重跑按钮。
中文状态通过共享 i18n 渲染，ID/Tool ID/JSON 保留原文。布局沿用既有 token、轻边框
和按钮样式；手机单列保留全部 case，没有缩短分母或横向截断。

`tests/unit/run-plan-case-jobs.cjs` 使用独立 Python 编译/物理 verifier 的协议替身，
覆盖七个原 case、完整引用准备、错误端点/阶段/权限标志、只读状态竞争、丢失 ACK、
独立取消、session 身份隔离、不可替代 ACK、共享中文及无 HTML 注入。隔离 Playwright
CLI 探针覆盖确认后全量历史、刷新只读、独立取消、unknown 不重发、403 隐藏、历史
计划只读和 desktop-dark/mobile-light。浏览器响应为显式替身；临时页面和服务已移除，
仅保留 `output/playwright/run-plan-case-*20261013.*` 证据，不把它计为真实 E2E。

当前恢复仍是同浏览器会话的原命令恢复；项目级跨会话任务发现、完整页面与真实
服务联调、QA 角色消费及 512-case 容量验证没有完成。上述契约不授予正式业务覆盖。

### 后端与实际依赖

离线测试使用明确的 session/journal/storage/transport doubles 和物理 verifier，
覆盖原有序用例、断线未知、重试不重发、独立取消、权限撤销、原始历史、no-store、
Temporal 传输契约、迁移 DDL 与新鲜进程导入。它们不是实际 PG/目标/Temporal 证据。
`test_run_plan_case_job_postgres.py` 为隔离 PG 准备了取消事务回滚、并发取消、并发
delivery、不可变 trigger、终态控制历史和独立空 schema roundtrip；Docker 不可用
时仅编译、不收集执行，不改用 SQLite。

2026-10-13 Docker 恢复后，`bash scripts/test-run-plan-cases-postgres.sh` 在隔离 PG 和
私有 MinIO bucket 执行完整迁移及底座/集成专项，**14 passed / 185.58 秒**。集成
专项经真实 canonical 父链创建原 RunPlan，再以明确的 case claim 和 Runner wire
样本验证真实归档回读、并发唯一所有者、unknown 不重发、最后撤权/Outbox 回滚
及物理归档损坏拒读。它不是公共 native target grant 或 exweb 业务执行验证；
完整生命周期中的正式 coverage/release 计数仍为零。详细终态见实施记录。

新增[完整捕获输入与私有 HTTP v3 原生绑定协议](./run-plan-fixture-bindings.md)，
已扩展公共 v3 草稿生成、独立 action 审阅及 RunPlan／build 编译，并接通原 setup
字节到主业务 Worker 的 handoff。仅有 v3 template 仍在 lease／claim／dispatch 前
拒绝；完整原始来源必须由 producer 物理回读并以新 work/archive/state pins 固定。
历史重读和 canonical/Temporal 共享同一 application 入口。当前真实新 PG/MinIO
专项尚在核验，不能当作真实 Temporal、公共 v3 浏览器或 owned exweb 全链已通过。
旧脚本路径和摘要保持不变，不能以 capsule/hash 自行授予 dispatch 或正式 coverage。

仍需交付：Portal 跨会话发现及真实联调、fixture 原生绑定协议的完整公共业务接入、独立 unknown 原结果
恢复、真实 exweb/PG/MinIO/Temporal 链路、正式 coverage/release、GC、QA 角色消费、
五用途上下文及旧链切换。P0-P6 的独立 gold、安全、性能、容量和试点门禁不缩小。
