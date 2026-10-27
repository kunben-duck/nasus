# HTTP fixture 派发事务的原许可绑定

更新：2026-10-12。0112 将 0111 的独立操作许可与私有 PG journal/worker 所有权
放进同一派发事务，推进完整 P5 执行链。它不是公开 canonical 执行交付，不把许可、
资源准备或协议 specimen 升级为真实业务覆盖；完整 P0-P6 退出条件保持不变。

## 原输入与独立 gate

application 的 `HttpFixtureDispatchConsent` 只固定原 grant ID/hash、确认账号、完整
scope、单一 setup/cleanup 操作和来源权限 fingerprint。它不持有 ORM、Runner、
工作流或任何 execution_authorized 字段。`dispatch_consent` 必须先通过现有完整
定义/RunPlan 私有回读、当前来源与审阅检查、原 completed 命令和 PG 时限。

0113 的[原生 v2 许可](./http-fixture-native-targets.md)将同一 consent 的 scope 固定
到原环境记录的实际 inventory，而不是 operator policy。旧 v1 不自动转换；私有
dispatch 读取原 grant 时也要核验完整追加式环境关联和原 completed 回执。

准备许可不能用于清理，清理许可不能创建；每个 cleanup group 仍从原 setup capture
确定资源，不接受调用者资源 ID。worker owner/epoch 与许可是两条独立约束，传入
consent fence 而没有 worker fence 会在 journal 构造时拒绝。

## 同一 PostgreSQL 事务

新 journal dispatch v3 保留原 request/scope/父计划及 worker pin，并追加确切
`operation_consent` pin。原记录/原结果不改写，旧 v1/v2 不 backfill 许可。

`PostgresHttpFixtureConsentFence.require` 使用 caller 的现有 SQLAlchemy session，
不另开许可事务：原 completed grant、确认账号/当前管理员角色、单一操作、完整 scope、
source fingerprint 和 PG 半开时间区间都要匹配。原 scope metadata 与命令 metadata
用类型敏感摘要比较。调用者仍必须实时检查完整计划/来源权限和实际原目标。

在原 project/actor/worker 锁事务内，dispatch、审计、Outbox、原 worker ownership 与
`quality_http_fixture_dispatch_consents` 一起提交。消费记录通过 project/claim 复合 FK
同时连接原 dispatch 和原 ownership，通过 project/grant 复合 FK 连接原独立许可。
记录固定原 scope、操作、两个摘要和 PG `consumed_at`；历史核验要求实际消费时间
仍处于原许可有效期，不以主机 journal timestamp 替代 PostgreSQL 时间。

flush 后再次检查 live permission。许可在 staging 后到期、权限撤销、ownership 或
Outbox 出错，不能留下部分 claim/consumption。已领取 worker lease 不因此消失，但
未提交派发前不得 Runner。MinIO/PG 仍不宣称分布式事务或 exactly-once。

worker 租约的 PG 起始时间在完整原 scope 和实时权限校验之后取得，避免慢校验耗尽
尚未交给 worker 的租约。续租须在末次检查后再次确认旧租约仍有效；到期 owner 不能
通过提前开始续租来复活。两次 parent pin 必须类型敏感一致，TTL 不延长，许可仍须在
实际 dispatch 事务中独立核验。时钟专项的最小 parent/ACL specimens 不代替原父链验证。

原生 access 新增写事务前的 transient preflight：完整原计划/当前输入、原环境记录与
确切 JAR/inventory、当前依赖/目标健康、worker callback 都必须一致；缺失 health port
拒绝。不在写事务持锁期间执行 Docker 探测，也不写入一张可复用的“预检授权”记录。
历史 inspect/complete 无 live probe，未知效果仍保留而不是重发。

## 历史、原结果与未知效果

历史回读完整核验原 completed grant/recipe/计划、scope/phase、原 owner 及许可消费。
到期只阻断新的使用，不能删除已保存原结果或续期许可。缺失 v3 consent/ownership
不能降级为 legacy；保留 ownership/consent 而丢失 dispatch 同样不能当作空白新请求。
严格类型检查拒绝 bool/int epoch、添加权威字段或重新 hash 后的换项目/目标/操作。

结果提交必须带原 worker 与确切原许可，不能由新确认替代已有 claim 的许可或采用
另一 worker 的未知效果。已有 claim 而没有完整可信输出仍返回 outcome unknown，
不可自动重发创建/清理请求。私有输出可回读，不能更新旧失败 oracle 或改为 passed。

所有原 grant、ownership、consumption 与 journal 继续保留
`execution_authorized/canonical_execution_committed/business_coverage_verified/baseline_restored=false`。
许可的同事务必要约束与 transient preflight 不等于已完成 Tool/Temporal 的正式执行命令、
取消、部分输出恢复、真实覆盖或放行。table trigger 禁止更新/删除；populated downgrade
拒绝丢弃，迁移无历史授权 backfill。

## 验证范围与后续

纯测试使用显式 session/clock/parent/ownership doubles，验证边界、原 pin、同 session
调用、到期历史、严格类型、缺失记录与 rehash 篡改，不当成真实 PG 或业务证据。

新增固定 exweb 专项构建正式 canonical 原父链，完整核验 126 Git blob/私有 MinIO
和原 grant，再以明确 frozen plan reader 与 protocol Runner 隔离 PG transaction 故障。
它检查 post-staging expiry rollback、原 failed oracle、独立 cleanup、未知结果不重发、
immutable trigger/downgrade；即使通过也不证明实时审阅变化、原生目标执行或业务 gold。
当前终态和加载范围见[实施记录](./implementation-progress.md)。

该 private fence 尚未 production-composed。还需交付 canonical/Temporal 的真正派发、
执行 Portal、Runner 请求前后原环境/build/inventory 复验与 runtime locator preflight、心跳/取消/未知
效果恢复、实际 case/step/oracle 的观察消费与 release 判定。五用途、旧链切换、自动
增量/统一 DAG、多语言 Provider 对照、独立 gold、安全容量/性能/试点仍在完整目标内。
