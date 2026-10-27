# 受控 HTTP 测试数据生命周期

更新：2026-10-13。该模块推进 P5 中实际 fixture 准备、资源绑定与清理验证，不代表
正式执行授权、canonical RunPlan 执行或业务覆盖已经完成。0108 新增私有 PostgreSQL
journal 和 MinIO 原字节归档；0109 补充私有持久 worker fencing。后续 0114/0115 已
接线独立确认的公开 Tool 与 Temporal 编排，当前专项验证边界见下文；不把管理员
读权、worker 租约或接线本身当作完整原生业务验收。

0110 新增[固定定义登记](./http-fixture-recipes.md)：独立确认、完整原 RunPlan/hash 绑定、
PG/MinIO 追加式归档和重新授权的私有读取。仅登记输入，不调用私有 lifecycle，也不
给旧 journal、计划或 worker 增加执行权威；公开原生派发端到端验收及完整闭环仍待交付。

0111 新增[独立操作许可](./http-fixture-grants.md)：准备与清理分别 canonical 确认，
限时固定原定义/attempt/环境与确认人。后续私有执行组装消费该 gate，
仍不能仅凭许可、登记或 worker 租约启动公开执行。

0112 后续增加[同事务原许可消费](./http-fixture-dispatch-consents.md)：private journal
v3 把原 completed grant 和 worker ownership 与 claim 原子连接，保存 PG 消费时间，
历史缺项不得降级或重发。现已接入下述私有 application/container 组装，不替代独立执行命令、真实目标
preflight、Temporal 生命周期、取消/未知效果恢复或完整闭环。

## 原生失败的诊断边界

应用层对原准备权限、命令读取、完整输入、绑定、最终授权和同 ID 的 Temporal
投递增加固定阶段与耗时诊断；原 grant 的 recipe/环境读取和实时许可检查另有
阶段。真实原生批次已将一次失败定位到 `prepare_binding`，许可检查在此前通过；
现进一步区分 canonical/actor、原 live grant、已有 intent、原 preparation、既有
派发防重、intent 写入、preparation binding、完整 intent 核验、事实事件及当前
授权。各阶段只是原代码的观测边界，不改变锁、校验顺序、事务或失败结果。
只允许代码内登记的阶段和错误类别，未知错误统一归为 `other`，不记录
异常消息、traceback、原文、私有引用、SQL 参数或凭据。成功阶段是观测，不是
准备/派发事实；异常、取消和未知投递仍原样传播，不产生新的确认或重试。
原生验证的当前终态与加载代码范围见[实施记录](./implementation-progress.md)。

Worker 的 acquire/require/renew 进一步按初始当前授权、原来源 scope、
事务锁、锁内授权、登记父对象、最终 scope／授权及活跃租约分段。
这些边界保留原调用次数、锁、PG 时间与提交顺序，只输出固定阶段、
白名单错误类别和耗时；不记录异常正文、SQL、来源内容或凭据。
失败与取消原样传播，失败租约操作仍回滚，不增加派发或自动恢复。

环境检查可通过构建绑定的 application read port 取得本次完整核验的原 RunPlan，
避免先读计划再经绑定重读同一父对象。全部项目/修订/摘要/当前状态检查与最终
ACL 保留；不是跨请求缓存，不使用损坏父对象、不在读取异常后换成旧算法。
这不能替代实时目标检查、原许可时限或 worker 的提交 fencing。

## 同步 journal 读取作用域与只读权限

`SavedRunPlanHttpFixtureAccess.verified_read_session` 把一次同步 journal
inspect/claim/complete 或 worker acquire/require/renew 的不可变证据读取
放入原 RunPlan application port 的有界作用域。每个原 scope/command/parent
检查仍调用完整读端口；复用的不是返回的计划 DTO、当前权限、审批头、
目标健康、许可或租约结果。源证据的作用域按原 ImageRevision reader
限制在同一 thread/task，结束即关闭；子任务、复制的 ContextVar、
`to_thread` 和下一次操作须重新建立并核验自己的作用域。

journal 的 `read_only=True` 分支只读取当前账号及项目角色，不使用
`SELECT FOR UPDATE`，避免和调用方已经持有的账号／角色写锁互相等待。
原生构建及 journal 写分支仍使用原锁。只读权限查询强制刷新当前 ORM
字段，空记录、已保留但未完成的 dispatch 和完整结果在返回前都重新
核验账号／角色；未知 dispatch 返回前另行复核来源 scope。
Worker 的当前账号与项目角色查询也强制刷新已有 ORM identity；原生
构建及 journal 的加锁权限查询同样刷新，再保留原 `FOR UPDATE`。
行锁本身不保证 SQLAlchemy 刷新已持有对象，不能用会话里的旧账号
状态、项目角色或平台角色覆盖数据库中已经提交的撤权。
这不是授权缓存，也不能据此重新派发未知副作用、续期 grant 或延长
90 秒 PG worker lease。实际 PG、完整 exweb 和加载版本的验证范围见
[实施记录](./implementation-progress.md)，不由专项通过推导完整 P5、
性能或 release 门禁通过。

## 原始数据与领域边界

0114 新增[原始执行命令关联](./http-fixture-command-provenance.md)：明确可信命令 pin
时，v4 journal 在原写事务锁定并复核 ToolInvocation，将命令、许可与 worker 原子连接。
不可将旧私有/未知阶段接管为新命令，绑定后也不能退回私有派发。0115 后续在容器与
Worker 接线公开 job/Tool/Temporal 和不可变取消/投递事实，具体见[原命令契约](./http-fixture-command-provenance.md#公共任务与持久取消接线0115)。
当前是契约验证的实现增量，尚未通过真实 PG/Temporal/exweb 公共链验收，执行 Portal
尚未交付，所有原 authority flags 保持 false。

`nasus.http-fixture-manifest.v1` 固定 case ID、原前置条件摘要、原 setup/cleanup 描述、
完整 HTTP 准备步骤和按资源分组的清理步骤。描述仍是数据，不解释为 shell、SQL 或代码。
manifest 通过独立 `data_manifest_hash` 与既有 RunPlan 声明连接；
`bind_run_plan_fixture` 完整验证原 plan，再要求原 case、前置条件、描述和 manifest hash
全部一致，不修改旧计划或脚本、步骤、oracle 与批准记录。

模板不含计划摘要，避免 RunPlan 包含 manifest hash、manifest 又包含 RunPlan hash 的循环。
实际执行另固定 project/attempt/case、parent digest、manifest hash、环境 ID、构建与
inventory hash、timeout。该 scope 是输入，不是执行许可。正式调用者仍必须通过现有
application 读端口固定原 RunPlan，独立验证批准、角色、来源访问权和 owner/lease。

领域模块无 ORM、Runner、网络、存储或工作流依赖；application 只消费
`OwnedTargetHttpRunnerPort`、原始结果核验 port 和显式派发 journal port。
没有增加公开 HTTP 执行写旁路或旧链 cutover；公开执行只经独立的
`quality.http_fixture.execute`。执行服务已在 application container 挂载，但不能由
定义／许可登记 handler 自动触发。

## 私有执行服务组装

`HttpFixtureExecutionSelection` 只接受 project、原 grant ID/digest 和单一 setup/cleanup
操作，不接受 URL、Docker 资源、worker 身份或调用方 authority。执行前通过 grant
application 重新读取完整原定义、RunPlan、确切环境记录与当前来源权限，并核验原
completed 操作许可；环境记录、instance inventory 和 operator policy 的 pins 均严格类型化。
历史读采用另一条只读解析分支，保留原确认者，不要求未过期许可，也不能续期。

`OwnedHttpFixtureRuntimeFactory` 组装真实 PG lease、原 owner/epoch fence、原许可事务
fence、native saved-plan access、实时原实例健康 gate、MinIO 原字节归档和 owned Runner。
原始输出和失败 oracle 保持不变，不把它们晋级为正式业务覆盖。Node 执行路径只能由
operator 的 `NASUS_HTTP_FIXTURE_NODE` 显式给出绝对路径，缺配置在创建租约前拒绝，
不从 PATH 或仓库文本猜测。S3 必须在选择执行／历史读取时可用；未配置能力不阻断
其他服务组装，但 actual fixture 工件不允许本地文件降级。

输入解析、租约创建和同步 lifecycle 均在 owned thread 中执行；取消先通知该工作 fence，
随后等待线程退出，重复取消也不能遗弃它。共享 generation lease 的初始检查及每次
heartbeat 采用同一 joined-thread helper，成功或取消返回后不留下继续续租的线程。
这不替代 PG 事务内的原 owner/epoch、当前角色、来源 ACL 和许可到期复查；取消不是
回滚已经发生的 HTTP 效果，未提交结果仍保留 unknown，不能重发。

历史读取只重新授权并 inspect 原 setup/cleanup phases，不创建 Runner、lease 或新
grant。当前私有组装契约已验证，完整原父链的真实 PG/MinIO 新集成批在构建关联准备
阶段遇到 PostgreSQL/MinIO 和 Docker 停止，未执行到新 worker，不能写为通过。
日志和所有未完成门禁见[实施记录](./implementation-progress.md)。公开 canonical job、
Temporal 和持久取消代码已接线，但实际 PG 事务/Worker 重试与重启/原生 exweb 验证
未完成；执行 Portal、独立未知结果恢复及真实覆盖／release 继续待交付。

## 准备、资源与清理

- 准备只允许 GET/HEAD 和显式创建 POST。每个创建之后必须立即 capture，先固定原
  2xx JSON 响应的资源 ID，再执行期望断言；每个请求都有显式 status oracle。
- 每个 capture 唯一，最多 16 个资源。清理组与全部 capture 恰好对应，组内只能绑定
  自己的资源，不接受猜测 ID、其他组 ID、query/body 插值、任意凭据、shell 或数据库操作。
- 每组独立编译和派发。仅完整路径段可替换为本次准备返回的有界资源 ID，body、headers
  与全部原 oracle 保持不变；每个清理请求都有 status 断言，并至少有一次资源写操作。
- `OwnedHttpFixtureObservationVerifier` 对比原 canonical request bytes、原结果 JSON 与
  反序列化结果，再完整核验 native receipt、每个原响应和 capture 值。环境 ID/hash 必须
  一致；不能仅信任 passed、binding 字段或新算的摘要。
- 准备断言失败时，已可信捕获的资源仍可清理。多资源准备中尚未获取 ID 的组保留
  unresolved，已知组独立清理；任一未知组、未知派发或失败清理使整体 cleanup_verified=false。
- 清理的 original failed 结果保留。关闭资源成功不等于删除资源、恢复整个数据库基线、
  用例通过或 release 可放行，因此 baseline_restored/business_coverage_verified/
  execution_authorized 始终 false。

## 派发与未知结果

执行前先 claim，原输出核验后才 complete。journal 的唯一键必须是
`project_id + attempt_id + case_id + phase`，不能用可变化的 scope digest 做命名空间。
同一键的原 scope/command 不可重绑；同时抢占只能一个成功。

已保存的原始输出可重新授权后回放，不再次 Runner。已有 claim 而没有完整可信输出时
返回 outcome unknown，不能自动重发创建或清理 POST，也不能用另一个环境、manifest、
parent/build/inventory hash 或 timeout 绕过原 claim。原证据提交失败同样保留不可重试状态。
权限/owner 回调在读取、派发、核验和完成前后重新检查；失效时不继续新的清理操作。

0108 的 `quality_http_fixture_dispatches/results` 是追加式私有执行器账本，触发器拒绝
更新/删除，有历史时 downgrade 拒绝丢弃。预留以原 project/attempt/case/phase 唯一，
结果独立 FK 连接原预留；另以完整 FK 固定原 RunPlan、画像及 manifest。原 plan 通过
既有 application read port 回读全部私有工件与来源权限，并验证 fixture 声明、环境 ID、
inventory、原 owned loopback endpoint 和 build hash。每次事务在项目锁中复查实际注册
管理员、父记录和调用者 fence。
这不是新的执行授权 port；独立批准、canonical/Temporal 与持久 owner/lease 的正式
组装仍需接入。0109 的私有租约实现见下节，不自动授予任何现有命令执行权限。

原请求/结果 bytes 完整 base64 封装后按内容 hash 保存在私有 MinIO；PG 不保存响应正文。
回读同时核验完整 envelope、原 command/wire、native receipt 和每项 capture/断言，
保留失败状态，不能只信任 PG 的 passed 或摘要。后端不允许 SQLite 或本地文件降级。
预留/结果分别与其脱敏审计和 Outbox 同事务写入，不冒用准备 RunPlan 的 ToolInvocation
作为派发批准，`canonical_execution_committed/execution_authorized/business_coverage_verified/
baseline_restored` 均为 false。完整输出提交失败仍保留原预留，服务重建不重新 Runner。

MinIO 预写与 PG 不是分布式事务，回滚可能留下未引用工件，不声明 exactly-once 或 GC
完成。协议测试中的内存 double 和 exweb 探针 O_EXCL 文件 fence 仍不是正式生产账本；
旧 exweb 报告的 durable_postgresql_journal_verified=false 不改写。新 PG/MinIO 专项
和原 exweb bytes 的 MinIO 往返是不同证据，不拼接为真实 exweb canonical 执行。
独立清理权限、部分输出持久恢复、工作流与 Tool 接入仍必须完成后才能启用公共执行链。

## 私有持久 worker fencing

0109 增加 `quality_http_fixture_work_leases` 和
`quality_http_fixture_dispatch_ownership`。租约按原 project/attempt/case/operation 唯一，
setup 与 cleanup 独立，固定完整 scope、原计划/画像/manifest、管理员及请求摘要。
使用 PG `clock_timestamp()`，只允许过期后接管并递增 epoch；同 owner 活跃重入也不能
再次 claim。renewal 只延长原 owner/epoch，不改变输入或释放另一个操作。

数据库触发器保护固定 pins、活跃 owner 和递增 epoch；所有权事实追加式、禁止改写或
删除，populated downgrade 拒绝丢弃。派发 journal v2 在原 payload 固定 owner/epoch，
所有权与原 dispatch/审计/Outbox 在同一事务保存。缺失所有权不降级成 v1，也不在正常
读取中补造历史。旧 v1 不推导 owner，更不补造执行许可。

`PostgresHttpFixtureWorkFence` 在 journal 项目锁内核对活跃租约，派发与结果提交前后
均重新验证。完整命令在事务前编译；事务内不重入另一连接的 cleanup 原 setup 读取，
避免同一 actor 锁自锁。外部 read-only worker callback 同样不重新加 actor 写锁。
结果提交必须属于原派发 owner/epoch；过期后新 worker 可读取原结果，但不能采用旧
worker 未提交的效果、重发 POST 或将未知状态标为成功。

`run_with_http_fixture_work` 复用现有异步心跳/取消生命周期，不增加编排框架。丢失
租约时取消适配器；线程不能仅靠 coroutine cancellation 停止，因此实际 Runner 回调
和 PG 提交仍必须检查同一 fence。尚无公共执行、取消或独立未知结果恢复入口。

纯测试覆盖 scope/phase/epoch、历史所有权缺失与篡改、旧 owner 历史与异步心跳；真实
PG/MinIO 专项另检验事务、并发、过期接管及原失败断言。专项在完整原 parent 核验后，
用明确标识的 frozen reader/Runner specimen 隔离租约语义；它不证明当前来源 ACL、
真实 exweb canonical 运行或业务覆盖。各批终态见[实施记录](./implementation-progress.md)。

## 真实 exweb 验证

固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`，导出全部 126 原 Git blob，使用已有
离线 Maven cache 构建未经修改的目标。PG/Redis/目标均为原 owned inspector 核验的临时
独占内部网络资源，不使用开发数据库、开发 API/Portal、外部模型或 host ports。

执行器新增显式 `--http-fixtures`，必须同时选择 `--execute-reviewed-target --http-runner`。
原七个 HTTP 任务及其失败断言保持不变，fixture 结果另存独立 section/分母：

1. 正常创建/绑定及关闭：准备和清理都 passed。
2. 明确的 setup negative control：原期望故意不匹配，setup failed，已捕获资源清理 passed。
3. 原关闭后读取 404 oracle：目标实际返回 500，cleanup failed，不能标为清理核验成功。

三个 fixture 共 6 个 native phase job、7 个 HTTP 请求、3 个资源 capture、13 项已观察
断言，11 passed /2 failed。一个失败是明确的负向控制，另一个为原目标的关闭后读取差异；
不能把协议预期符合的 checks 当成全部断言通过或业务 gold。

最终 `exweb-http-fixture-lifecycle-final-20261012.json` stage=observed/error=null，
整体退出1：17/24 checks 符合，其余原 7 项失败保留。临时资源全部清理，remaining=[]。
该批 JAR `sha256:24f653c88014a930cd2628ee099ad9b74b38b1898ba62046147a445e5d81d500`
是该批实际构建，不与旧批 JAR 拼接为同一次执行；未声明 Maven 构建字节确定性。

`verify-exweb-http-fixtures.py` 在资源销毁后按原 scope/manifest/派发 claim/完整输出/执行器
源文件 hash 只读回放全部 fixture，拒绝缺项和篡改；不执行 Git/Docker/HTTP。
原 `verify-exweb-owned-http-archives.py` 独立验证完整 126 blobs 和原七个任务。
两类回放均不重新执行目标、不授予覆盖；具体终态见[实施记录](./implementation-progress.md)。

## 剩余完整范围

原 PG/MinIO journal 已接线独立许可与 canonical 执行命令，仍需真实验证完整 RunPlan 当前
依赖、受控 fixture/locator 预检、公共 Tool/Temporal dispatch、持久取消及独立未知效果
恢复、逐 case/step/oracle 到真实覆盖/放行的反馈。用户/租户身份、浏览器、远程目标、其他
语言与数据库 fixture 需要独立适配，不静默放宽现有匿名 owned HTTP 协议。
五用途 ContextPack、旧链切换、完整 P0-P6、安全性能与独立业务 gold 仍保留原要求。
