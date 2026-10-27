# HTTP fixture 的原生环境关联

更新：2026-10-12。0113 修正独立操作许可到原生执行端口之间的实例身份契约。
它推进完整 P5，不把历史环境登记、独立许可或 protocol specimen 当作实际执行、
业务覆盖或放行；完整 [P0-P6 验收](./delivery-and-evaluation.md) 保持不变。

## 策略摘要与实例摘要

原 RunPlan 声明的 `selection.environment.inventory_hash` 在 owned native 协议中
固定 operator registry 的政策摘要。它描述可使用的容器、网络、用户和配置约束，
不是检查时真实实例的 inventory 摘要。环境登记分别保存 `operator_policy_digest`
与 `inventory_hash`；后者包含原容器/镜像/网络身份及实际 JAR 观察。

旧许可直接沿用计划声明，因此不能安全地传给要求实际 inventory hash 的 Runner。
不能把旧字段改成另一个摘要、重写已保存计划或自动把 v1 许可晋级来解决这个问题。

## 显式 v2 操作许可

沿用 `quality.http_fixture.authorize` 和原管理员/RBAC/user_confirm 协议，不新增
绕过治理的 HTTP 写入口。原六个字段继续有效；原生模式必须额外同时声明：

- `policy_revision=nasus.http-fixture-grant.v2`。
- 原 `environment_record_id`。
- 原 `environment_record_artifact_hash`。

缺字段、无原环境读取 port 或版本不匹配拒绝，不回退到最新环境或 v1。
application 重新授权并回读完整原定义、计划、构建及私有环境字节，核验同项目、
原计划/hash、画像/清单、目标 JAR、owned origin 和 operator policy。原环境命令
必须 completed，原回执及对象引用必须与固定事实类型敏感地一致；缺失或改写拒绝。

v2 原 scope 使用实际 `inventory_hash`，`native_environment` 另存 record ID/hash、
inventory hash 和 operator policy digest。同 attempt 的其他 case 可以使用各自定义，
但计划、确认人、目标、时限和原环境记录不得改变；同 case 不能换定义。
setup/cleanup 仍独立确认、PG 原时钟 900 秒，同命令历史重放不续期。

## 追加式 PG 关联与原字节

`quality_http_fixture_native_grants` 连接原 grant 与环境记录；复合 FK 固定
project/record/hash/inventory/policy 的完整五字段环境 pin。原 grant、关联、审计和
Outbox 在同一事务提交，late fault 全部回滚。不可变触发器拒绝更新/删除，已存在
记录时拒绝 downgrade；0113 不 backfill 旧许可、不改写旧 JSON/digest。

正常读取核验原关联及已完成环境回执，v2 丢失关联不能降级；v1 若残留原生关联也
不能伪装成 legacy。旧 v1 serializer 保持原六字段和原 schema，历史不自动读取或
采用原生环境。PG 保存 pins/hash，完整原 inventory 仍来自私有 MinIO，未增加
SQLite、本地正文或供应商节点身份依赖。

## 账本访问与实际派发边界

`NativeSavedRunPlanHttpFixtureAccess` 显式绑定原环境 pin，每次准备/清理命令编译
重新核验完整原计划、定义及环境记录，使用实际实例摘要。原 v1 access 不能接受
这个 scope。cleanup 仍只使用原 setup 的核验 capture，不接受调用者资源 ID。

该 access 的历史 `require_scope` 只核验原输入，不发起 live probe。新增
`require_dispatch` 通过显式 application health port，在 journal 写事务前核验当前
原实例/JAR、完整 inventory、依赖和目标健康、当前输入/权限与 worker callback。
缺少 port 或原 epoch 变化拒绝；前后检查完整原父链，不凭历史 health 记录授予新权限。
它不持有 ORM/SSE/Docker，具体探测仍在基础设施 adapter。

journal 另行核验原 manifest/cleanup steps，worker owner/epoch、独立操作许可和 PG
时限仍须在同一 claim 事务验证，Runner 请求前后仍需检查确切原实例。runtime locator、
正式 Tool/Temporal 生命周期、取消和未知效果恢复尚未因此交付；0112 的消费 gate 与
preflight 都不自动成为生产执行路径。

所有许可继续保留零执行计数，`execution_authorized`、`canonical_execution_committed`、
`fixtures_verified`、`business_coverage_verified`、`baseline_restored` 均为 false。
真实观察、通过或失败不能通过修改这些历史字段补造。

## 验证证据与剩余范围

纯测试明确使用 application/inspector/session transport doubles，检查版本与摘要分离、
原父链/回执、撤权、损坏和降级拒绝。PG/MinIO 专项使用完整 canonical 父链及所有
原用例，但模型、构建和 Docker transport 是明确 protocol specimen；即使通过也
不证明 exweb 原生目标被执行。迁移往返在 disposable `nasus_test_*` schema 进行，
测试复制父表列/检查而不重复修改公共父表；开发库不迁移。

最新终态与各批实际加载范围见 [实施记录](./implementation-progress.md)。原固定
exweb 的实际原 JAR/隔离 PG/Redis/目标健康及停止/重启拒绝已验证，完整原126 blob 与
PG/MinIO 非 specimen；模型/调度/业务 oracle/worker fence 仍明确为 specimen。
这项专项没有发送 fixture 命令（0次）或写 journal，业务覆盖/授权保持false。
原固定
exweb 的历史运行失败/oracle 保留，不拼成新的原生授权或独立业务 gold。接下来仍需
正式执行消费、真实 exweb/逐 case-step-oracle 回流、覆盖到 release、五种 ContextPack、
旧链切换、自动增量、独立 gold、安全/容量/恢复/性能和完整试点。
