# RunPlan 原用例执行核心与持久派发账本

更新：2026-10-13。属于完整 P5 执行链，已接入公共 RunPlan 命令；这不代表完整闭环已上线。
完整目标仍按[交付要求](./delivery-and-evaluation.md)验收，不能以本模块替代 P0-P6。

同日后续已新增[原输入 producer 与内部组装](./run-plan-case-inputs.md)：完整原记录
及当前健康核验、精确原 setup 派发与完整清理库存、私有 MinIO case archive 和 async
取消 join。后续 [0120 生命周期](./run-plan-case-jobs.md) 已接通 Tool/HTTP/Temporal/
Portal。实际隔离 PG/MinIO 与真实 Temporal 已有专项终态；原 owned exweb 全链在
静态定位处失败，新显式策略正在独立重跑。正式 coverage/release、unknown 独立
恢复及完整 P0-P6 仍未交付，不能用协议或部分执行结果宣称完成。

## 输入与独立权限

`RunPlanCaseScope` 固定原项目、命令、run ID、RunPlan 工件和计划摘要、画像/来源清单、
执行账号及来源权限摘要、目标产物/环境 inventory、超时及完整独立请求。请求必须包含
原构建绑定、环境记录、locator 记录和每个原用例的 setup 命令 ID，不能只提交
`fixtures_verified=true`，也不能省略部分用例。输入 pins 是检查依据，不是完成证明。

业务执行预留使用 `quality.run_plan.execute_http`；取消预留使用
`quality.run_plan.cancel_http`。现已注册到 Tool Catalog 和 Temporal composition，
只读 HTTP 与 Portal 暴露原命令及历史。正式执行必须经 ToolInvocationRuntime
独立确认，再由 application producer 核验完整原 native
build/environment/locator/fixture 原账本、当前上下文/审阅和来源权限，构造 scope。
生产 producer 已组装，不允许直接把客户端 JSON 当成 scope 或提供空授权回调。

PG adapter 检查原命令的 tool、运行状态、完整请求、确认账号和原 input digest；使用
PG 时间检验带时区的 15 分钟确认。fixture 执行/准备许可不能授权业务请求，租约也
不能代替确认。历史命令允许终态读取，读取不授予派发或重新确认。未完成的公共
unknown 处置/原结果恢复、明确续授权及完整生产生命周期验收必须继续交付。

## 执行与恢复

应用服务从原 v1/v2/v3 RunPlan 重建完整 HTTP 命令清单，保留所有 case/step/oracle；
capture/fixture import 保持动作身份，不冒充断言。浏览器脚本的目标执行尚需独立交付。
原计划超过限制或无法完整核验时拒绝，不缩小为 GET-only 或截断清单。

每个 `(project_id, run_id, case_id)` 只能有一个原派发槽位，槽位 ID 不含 scope
digest；改变账号、命令、目标或计划不能产生同一 attempt 的另一槽位。必须先在
PG 提交 claim、审计和 Outbox，才调用 `OwnedTargetHttpRunnerPort`。这是保守的
at-most-one dispatch 规则，不声明外部请求 exactly-once。

原生 wire、typed result 与响应工件经现有物理 verifier 校验，再按原计划生成
逐动作/断言观察。完整 request/result bytes、结果和观察写入私有工件，回读重验后
在同一 PG 事务保存 outcome、审计和 Outbox。业务断言失败不删除后续用例，结果
保留 failed/error/timed_out；只有可核验的 native 输出才能登记 outcome。

claim 之后传输断开、响应证明错误、归档/提交失败或取消时，不合成 Runner 成功/
失败结果，也不重发。`outcome_unknown` 优先于 cancelled，其他未派发用例仍留在
原清单。归档可能产生未引用对象，不能声称 MinIO/PG 已实现分布式原子提交；GC、
独立 unknown 处置和原证据恢复仍需交付。

已提交 outcome 读取时完整回放原响应与 oracle，不仅信任状态/摘要。Worker 重启
只跳过已核验结果；发现原 claim 无结果则停止整个 attempt，不自动继续余下请求。
历史读取前后重新授权；库存读取期间变化时要求重读同一 run，不创建替代命令。

## PostgreSQL 0118

新增五张表：固定完整 scope/roster 的 work、90 秒 PG-clock lease、追加式 claim、
outcome 和 cancellation。work 使用原 RunPlan 完整复合 FK 与原 ToolInvocation FK；
claim/outcome/cancellation 连接原 work/claim/control，保留全部原始 ancestry。

只有 lease 可变。DDL 拒绝其他事实 UPDATE/DELETE；租约不能改 work/project、回退
epoch、偷取活跃 owner、用相同 epoch 改 owner 或复活过期 lease。新 epoch 只能加一，
续约保留恰好 90 秒期限。已有 work 缺 lease、历史 claim 使用未来 epoch 时拒绝，
不借恢复补造原历史。取消与派发/提交使用相同项目/原命令锁，旧 owner 不能迟到
覆盖结果。异步取消会等待本人同步线程结束；这不证明目标副作用已停止或回滚。

work、claim、outcome、取消事实与各自审计/Outbox 同事务。共享事件只有原命令 ID、
项目及通用状态，不包含请求、fixture pins、wire、存储引用或确认恢复键。

初始核心阶段只有离线 DDL/ORM 与无连接检查；后续随机隔离 PG/MinIO 已实际运行
账本、prepare、job、完整 scope 与故障回归，具体终态见实施记录。开发 migration
本轮未应用。完整真实竞争、进程崩溃恢复、容量与生产试点仍是验收必需项。

## 验证与剩余范围

2026-10-13 新增显式 fixture-bound scope 和 work v2：每个原 job 的摘要绑定完整
fixture input，Worker 在 lease/claim 前物理验证原 setup 字节，再创建独立
`FixtureBoundHttpCommand`。私有 native archive v2 保存全部 fixture input 与业务
request/result，历史回放比较 producer 重读的原输入；observation/state v2 暴露
有序元数据 pins，仍不授予 target/business authority。旧 v1/v2 job 不增加空字段，
旧 scope/work/archive/observation/state 不重算。PG 原 JSON 表可承接新显式版本，
不回填或放宽 append-only/复合 FK/lease 规则；同一 claim 的 unknown 仍不重发。
新协议实证和完整剩余范围见 [Fixture 资源绑定](./run-plan-fixture-bindings.md)。

测试使用明确的内存 journal、私有工件和 native wire protocol specimens；它们不是
真实 PG/MinIO、operator target、独立需求 gold 或 exweb 业务执行。原固定 exweb
缓存 HEAD 与无修改状态单独核验，不把该检查当作新 Runner 目标证明。

具体命令、失败记录、终态和计数见[实施记录](./implementation-progress.md)。原核心阶段没有
改前端、重启开发服务/依赖、启动目标镜像、调用外部模型或以 SQLite 执行数据库测试。
所有正式 automated/executed_on_target/passed 计数仍为零；内部观察不能自己授予覆盖。

下一步继续验证已组装的原 producer、独立确认的公共 Tool/Temporal/Portal、全部
fixture 与目标健康核验及取消，补齐独立未知恢复，再在真实 PG/MinIO/Temporal 与固定 exweb
上取证到 case/step/oracle、正式 coverage 和 release。五用途上下文、旧链切换及
完整 P0-P6 安全/版本/容量/试点退出条件不因此缩减。
