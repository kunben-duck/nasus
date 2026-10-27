# 独立 HTTP fixture 操作授权

更新：2026-10-13。0111 推进 P5 的正式权限链：登记定义不等于允许准备或清理，
worker 租约也不是用户同意。本增量记录独立、限时且确切绑定原输入的操作许可；
尚未接通 production 派发，不能把许可历史当成目标已执行、fixture 已通过或覆盖已完成。

后续 0112 新增[派发事务的原许可绑定](./http-fixture-dispatch-consents.md)：私有 journal
v3 在原 PG 事务同时连接 completed grant、worker ownership 和 claim，并保存 PG
消费时间。该 private fence 尚未 production-composed；公开 Tool/Temporal、真实目标
与业务覆盖的完整退出条件不变。

0113 新增[原生环境的显式 v2 关联](./http-fixture-native-targets.md)：独立确认固定原
环境记录/hash，实际 instance inventory 与 operator policy 分开保存；同事务追加式
PG 关联、原已完成环境回执核验，旧 v1 字节和权限范围不晋级。

## 命令与权限

`quality.http_fixture.authorize` 经过原 ToolInvocationRuntime/RBAC，必须是当前
project_admin 或 platform_admin，独立 user_confirm，不继承登记、构建或计划确认。
原输入严格限定为 project_id、recipe_id、recipe_artifact_hash、attempt_id、
operation=setup|cleanup、timeout_ms（1000–120000 的整数）。不能同时批准两种操作，
不接受调用者 URL、资源 ID、inventory、shell、SQL 或结果正文。
原生 v2 额外要求完整的 policy_revision/environment_record_id/
environment_record_artifact_hash，不允许无版本地添加环境字段。

application 回读完整原 [定义归档](./http-fixture-recipes.md) 和保存的 RunPlan，
重新核验当前来源权限，从原计划确定 case/parent、manifest、owned environment、build
和 inventory hash。准备需原脚本/审阅输入仍 current；清理可保留失效计划的原范围，
但不能绕过当前账号/来源权限、原 setup capture、当前原实例、worker 或派发账本。

许可只属于确认人、该 attempt/case 和一种操作。同一 attempt 的其他许可必须沿用同一
原 RunPlan/actor/target/timeout；不同 case 可绑定自己的定义，同 case 不能换定义。
不允许以新摘要换目标。每个 attempt/case 最多保留 128 条
许可，完整检查上限而不截断历史。已保存许可不可更新、删除或续期；再次确认是新的
canonical 命令，不改变任何旧许可或派发结果。

## 持久化与时钟

`quality_http_fixture_grants` 用复合 FK 固定 project/recipe/hash，并关联独立原
ToolInvocation。PG 原时间签发，固定 900 秒有效期；新签发同时检查 PG 时间下确认
不在未来且仍新鲜。project/source/actor 锁内再次核验原权限与输入，许可、审计和
不透明 Outbox 事实同事务。late Outbox 故障必须全部回滚。

新签发不能只在事务开始时判断确认是否过期。完整来源校验后、第一条许可写入前
再次校验原 canonical 命令与 PG 时钟；最终来源校验和 flush 完成后、提交前再校验。
任一阶段超过原确认窗口，整笔许可／原生环境关联／审计／事实 Outbox 一起回滚。
签发时间不重新定位、900 秒有效期不延长，已提交历史的同命令恢复仍走原历史
分支，不因今天到期重写或重新启用旧许可。这不证明旧 exweb 失败就是到期所致。

payload 保存完整原 scope、source access fingerprint、输入摘要及签发/过期时间。
表触发器拒绝修改/删除，populated downgrade 拒绝丢弃历史。迁移不给旧定义或私有
worker backfill 权限。许可无响应/资源秘密，原定义仍由私有 MinIO 提供，未新增本地
或 SQLite 降级。

完成命令的原结果、对象引用和许可 metadata 必须确切一致，bool/int 不能互换。
取消/失败/未完成命令即使留下历史，也不能使用 live permission。

## 历史与派发前检查

`GET /v1/projects/{project_id}/quality/http-fixture-grants/{record_id}` 和
`query.quality.http_fixture_grant` 仅返回重新授权的历史 metadata；private/no-store。
查询不续期、不 inspect native 环境、不启动工作流或 Runner。Agent query 回执和
ToolInvocation 历史重新验证原定义/计划和当前来源权限；SSE 仅包含不透明 ID/状态，
不广播请求、scope、许可正文或资源。

`HttpFixtureGrantApplicationService.require_operation` 是未来派发的一个必要 gate：
确切确认人、scope、operation、source fingerprint、当前权限、completed 原命令和
PG 时间范围均必须满足。setup grant 不能清理，cleanup grant 不能创建，expired grant
不能以历史读成功绕过。它不代替实时原实例/build/inventory 核验、持久 owner/epoch、
原 journal claim、canonical dispatch 与独立取消/未知效果恢复。

一次完整读取现在同时返回已核验的许可、定义、scope 与原生环境；公开历史 DTO 不变。
`require_operation` 在一次完整 current 读取后独立执行原 PG live permission 检查。
`execution_inputs(live=True)` 先完整解析原输入，再由 dispatch consent 独立完整回读
并核对同一操作，保留第二次 current 检查及最终 ACL；历史解析只完整回读一次，
仍不产生 live permission。仅消除单次校验内重复丢弃父对象后的读取，没有跨请求
缓存、减少 archive/source 成员、保存权限或失败时改用旧入口。签发的提交复核仍
独立完整读取，不复用该次解析来延长确认窗口。

所有历史保持 scope_permission_recorded=true，但 execution_authorized、
canonical_execution_committed、fixtures_verified、business_coverage_verified、
baseline_restored=false，三类执行/通过计数为零。只能将独立运行原字节核验结果写入
未来的执行事实，不能更新许可来补造通过。

## 验证与剩余范围

纯测试覆盖单操作、完整 scope、actor/source 不可重用、严格类型、限时历史、失效输入
和未授权角色。PG/MinIO 专项在正式 canonical 完整父链上检验独立确认、事务回滚、
过期确认、setup/cleanup 分离、attempt 不可重绑、原命令/查询/Agent/SSE、复合 FK、
不可变触发器及 populated downgrade；具体运行终态见实施记录。
到期分支的专项把本测试 repository 的 SQL clock 表达式移到未来，不修改 PG 时钟、
许可或开发数据，不能称为实际等待 15 分钟。协议 specimen 不代表 exweb 业务 gold。
新增提交窗口测试分别在真实完整来源校验之后推进 SQL clock，核验第一条写入前
拒绝及已 flush 许可／审计／Outbox 的整事务回滚；当前实际运行终态见实施记录。

剩余：执行 Portal、将新事务 gate 正式组装进受治理执行链、真实环境及
fixture/runtime locator 预检、Tool/Temporal 运行/取消/未知效果恢复，以及逐 case/step/
oracle 的真实覆盖与 release 判断。五用途、旧链切换、独立 gold、安全性能和完整
P0-P6 要求保持不变。
