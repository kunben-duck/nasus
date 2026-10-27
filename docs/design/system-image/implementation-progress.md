# 系统画像实施与验证记录

更新：2026-10-13（Asia/Shanghai）。本记录跟踪完整 P0-P6 目标，不以当前已完成部分替代验收范围。主方案与 [交付门禁](./delivery-and-evaluation.md) 仍是最终完成依据。

历史段落中的运行中状态仅记录当时观察；70630 和 30410 均已失败退出。最新恢复契约、补源草稿与同目标执行阶段证据见下文 0085-0087。旧加载完整门禁批 72444 已退出 1：8 failed / 3420 passed / 35 skipped / 1 warning，10685.91 秒（`investigation-minio-current-v1-release-20261007.log`）；不把历史观察继续当作 live，也没有最新完整 V1 全绿证据。

## 用例准入父输入复用与读取期间撤回（2026-10-13）

上一轮只读解释数据关系，没有改实现。本轮先通过原句柄重新确认 41062 和
55494 仍在运行，不因观察等待重启。现有隔离库中的原 recipe 使用当前代码
只读剖析，定位到脚本读取和准入读取重复展开完整输入；诊断禁止 PG 写入和
S3 修改，不创建事实、模型出口或目标请求。

新增 application `read_with_inputs` 返回完整核验的准入记录、历史输入和
可用的当前输入。公开 `read` 响应结构不变；脚本读取复用该内部父端口，并
独立核对项目、映射 revision/hash、完整用例选择、basis 和 oracle 摘要。
原 archive、所有批准前驱、原生回复、完整脚本、来源权限及末尾当前使用
复查保留。末尾开启新的准入读取，不借早期输入复用动态 authority；旧端口
和 legacy draft 的完整读取兼容保留，缺少准入不自动晋级。

同时红测复现读取期间撤回准入仍返回 current 的时序问题。当前输入完成后
再次核验完整持久审批历史；发生 head 变化则保留原历史，但清除 live input，
不授予当前使用权。未缓存 ACL、审批头、执行许可或 worker lease，没有改
900 秒 grant、90 秒 lease、原等待期限、用例数量、oracle 或覆盖分母。

初始父读取红测为 14 failed / 2 passed / 0.71 秒，首批相关回归 137 passed。
后续 head 红测 1 failed / 17 passed / 0.74 秒；修复后相关回归 139 passed /
1.52 秒。扩大回归当前退出 0：493 passed / 12.33 秒，日志
`admission-parent-current-final-unit-boundaries-20261013.log`，覆盖原用例准入、
脚本、Fixture 生命周期/权限/停止/未知效果及 DDD。前述 137/139/491 项重叠，
不累计为验收数量。一次错误测试文件名导致退出 4/no tests ran，日志
`admission-parent-current-unit-boundaries-20261013.log`，不算验证。

实际隔离 PG/私有 MinIO 的新增 head 竞争测试 85810 已退出 0：1 passed /
1 deselected / 115.85 秒，日志 `admission-parent-current-head-postgres-20261013.log`。
它通过原 canonical 撤回命令在完整输入读取期间追加新审批头，原 revision/
basis/完整用例仍相同，但 current=false 且不返回 live input。资料是协议
样本，不是独立业务 gold 或目标执行覆盖。

同一个现有隔离库、同原 recipe 的 read-only profile：完整输入编译 9 -> 6，
ContextPack 读取 18 -> 12，SQLAlchemy execute 9407 -> 6376；原响应 hash
始终为 `sha256:7a19d094b4959541d5d41df726c6653e53d801bcd44ffc9ef87bd1231606bb4f`。
最新样本含末尾 head 复查，日志 `fixture-current-original-read-admission-final-20261013.log`，
总读取 12.964 秒；早期不含该复查的样本为 8.535 秒，原对照为 13.078 秒。
本地并发负载和 profiler 开销使耗时波动；只证明相同响应下的重复工作减少，
不声明稳定提速、p95/容量达标或原生权限失败修复。这是已有协议 recipe，
不是实际 exweb 目标请求。

固定原 exweb 两项原准入/脚本专项保留 126 blobs / 725 代码成员、完整四个
协议用例和所有原断言，并增加全部 Engine READ ONLY、S3 只读、原 archive
hash/完整响应对照。63469 尚在运行，日志
`admission-parent-current-exweb-postgres-20261013.log`；它还包含读取期间实际
来源撤权回归。该批加载父输入复用、早于新增末尾 head 复查；上述 85810
独立验证最新 head 改动。进度点不当作最终通过数量。

Portal build/lint 均已退出 0，日志 `admission-parent-current-portal-{build,lint}-20261013.log`，
大 chunk 警告仍存在。70583 隔离 smoke 已退出 0，日志
`admission-parent-current-smoke-20261013.log`，原完整 journey 与 smoke: success
均存在；没有运行最新完整浏览器 E2E 或完整 V1 门禁。

75296 使用最新代码、新的隔离 PG/MinIO、原生 Maven build、独立 owned 目标
及真实 Temporal 启动原完整 exweb handoff 验证，当前句柄确认仍在运行，日志
`admission-parent-current-owned-exweb-temporal-20261013.log`。这是独立新验证，
不是重启 19446、重发原失败/unknown 命令或复用其授权。原 source HEAD 仍为
fe5827f6b76f77ef34918d8b452ee823142332dc，porcelain 为空，原镜像 IDs 已再次
核验。当前不得声明原生 setup/业务执行/清理完成。41062、55494 原复验也仍
有当前 live 句柄；41062 已有五个失败进度，尚无终态，不提前诊断。

五用途、旧链切换、自动 delta DAG、真实覆盖/放行、独立 gold、安全/容量/DR/
p95/试点与最新完整 V1 门禁仍按原 P0-P6 退出条件交付，完整目标保持 active。

## 完整来源选择与固定 exweb 对照（2026-10-13）

上一轮按用户问题只读解释数据关系，没有改实现；本轮重新通过原句柄确认
41062 和 19446 当时仍在运行，没有重启或重发旧命令。后续 19446 已确认
失败退出，具体证据见本节末尾；41062 仍在运行，日志已有四个失败进度，
尚未输出终态，不能把进度当作最终数量或诊断。

新增 `frozen_source_members` application 读取端口：先执行原完整画像、来源、
归档和当前权限核验，再深拷贝全部固定来源成员。用例生成、脚本生成和
RunPlan 来源库存现在消费该端口，不再为只取清单复制整幅画像。完整 snapshot
默认隔离不变，RunPlan 的 list 返回结构不变；原 manifest/hash 校验保留，并
明确检查项目与画像 scope。失败、待采集和 legacy 来源仍完整保留，不过滤为
成功清单；只有原模型出网 binding 选择继续遵循原 captured 规则。没有扩大
两份证明缓存、线程/task 所有权、租约、许可或等待时限，也没有缓存 live ACL。

新契约首先复现 18 failed / 28 passed / 0.81 秒。原所有权、完整性、生成、
脚本、RunPlan、fixture 和 DDD 扩大回归先为 545 passed，加入选择期间撤权
拒绝后当前终态为 546 passed / 8.31 秒，日志
`image-source-inventory-final-unit-boundaries-20261013.log`；首批 126 项与这些
回归重叠，不累计为验收总数。一次混合收集在原 PostgreSQL ARRAY 模型的
默认 SQLite 编译处退出 2，没有运行测试；该原 API 组已转到隔离 PG/MinIO
联合回归 55494，日志 `image-source-inventory-current-parent-postgres-20261013.log`，
尚在运行，不更改类型或跳过原断言。

第一轮实际 PG/MinIO 退出 1：2 passed / 1 failed / 62.14 秒。失败来自新增
exweb 测试误读归档成员的 binding_id；按原归档 source_revision_id 连接来源
后，新的隔离批 41368 已退出 0：3 passed / 63.64 秒，日志
`image-source-inventory-current-exweb-final-postgres-20261013.log`。固定原 exweb
126 blobs / 725 代码成员、全部来源和完整画像响应不变；对照在所有 Engine
事务强制 READ ONLY，SQL/对象读取次数和所有原字节 hash 一致，完整画像复制
6 -> 2。同一实际 PG 快照中撤权仍阻断新选择器及三个下游库存入口。
资料仍是明确协议需求/用例，没有运行目标或外部模型，不是业务 gold、
正式 p95/容量或真实覆盖证明。

Portal build/lint 均已退出 0，日志 `image-source-inventory-portal-{build,lint}-20261013.log`，
大 chunk 警告仍存在。原 smoke 使用自己的 PG/私有 MinIO/API/Portal 资源，
43609 已退出 0，日志 `image-source-inventory-current-smoke-20261013.log`，
原完整 journey 与 `smoke: success` 均存在；它不替代原生目标或完整浏览器 E2E。
原 exweb HEAD 为 fe5827f6b76f77ef34918d8b452ee823142332dc，porcelain 为空。
五用途、旧链切换、自动 delta DAG、真实覆盖/放行、独立 gold、安全/容量/DR/
p95/试点与最新完整 V1 仍未满足全部退出条件；完整目标保持 active。

19446 原生全链后来已退出 1：1 failed / 2345.50 秒，日志
`fixture-phase-current-owned-exweb-temporal-20261013.log`。失败在原 setup workflow
返回 failed 而非 completed；execution_operation 报 PermissionError / 584367 ms，
worker_execute 报同类错误 / 685905 ms，Activity 标为 non-retryable
HttpFixtureAuthorityDenied。终态处理三次报告 HttpFixtureTerminationFailure；
不能解释为业务用例执行完成、目标已回滚或未知效果可以重发。该批加载阶段
作用域改动，早于本节来源选择和运行期诊断；不能用于断言最新读取性能。
现有 PermissionError 合并了许可期限、完整性和 scope 条件，没有确切证据
区分原因，不把“耗时较长”推断为已证明到期。

运行期 current fence 新增原 require_live 调用边界的脱敏诊断，使用原
grant_live_permission 阶段；不重排 callback/source/grant/source/callback，
历史读取不查 live grant，异常对象和外部行为不变。原 900 秒 grant、90 秒
lease 和等待不改，日志没有输入、异常消息或 traceback。新红测 2 failed /
6 deselected；当前生命周期/停止/未知/权限分类/DDD 回归 432 passed /
7.68 秒，日志 `image-source-inventory-runtime-diagnostics-final-20261013.log`，
与 546 项重叠，不累计；一次错误文件名导致退出 4/no tests ran，不算验证。
这只是更准确的失败定位，不宣称原生许可失败已修复，也未重启原失败请求。

## Fixture 阶段读取与迁移隔离（2026-10-13）

上一轮仅解释当前数据关系，没有改实现。本轮重新通过原句柄确认 41062 仍在
运行，未因等待时间重启。该批加载早于本轮阶段作用域改动，原八项仍须确认
实际终态，不能从日志进度推断全绿。

Fixture lifecycle 的每个原 setup／cleanup 阶段现在通过 journal application
port 开启拥有的只读证明作用域。原 require_work、inspect、claim、Runner、
oracle 核验、complete 及末尾检查的顺序和次数不变；只在同线程、同阶段复用
完整核验后的不可变画像证明。每个清理阶段及续租线程独立拥有作用域，复制
ContextVar 不转移所有权。错误、未知效果与取消均关闭作用域；取消仍 join
原 worker，reserved／unknown 的原请求不重发。ACL、批准／发布头、独立 grant、
worker lease 和原实例健康结果不缓存；90 秒租约及原工作流等待均未扩大。

阶段所有权红测为 8 failed／5.23 秒。原协议 Runner 的成功路径仍有九次实时
回调；撤权注入持续拒绝，并保留 Runner 异常后的再次检查，不把一次性的故障
替身当作持续撤权。首批生命周期／租约／取消／DDD 回归退出 0：272 passed／
4.07 秒；加入实际适配器接线和扩大原边界后退出 0：620 passed／17.71 秒，日志
`fixture-phase-current-boundaries-20261013.log`。两批重叠，不累计为验收总数。
这些作用域测试使用明确的 journal／target 协议样本，不是真实目标执行证明。

0103 迁移检查原本只确认当前项目的新表为空，却对共享测试库执行降级；
其他项目已有历史时生产保护会正确拒绝。现在在独立临时 schema 中运行实际
0101／0102 前驱 DDL，复制原完整父事实及保留全部 FK，再检查 0103 升级、空表
降级和再升级。public 父事实／绑定历史及所有 FK 不修改；原 populated downgrade
拒绝断言保留，并增加已绑定同项目历史下再次演练及原回执不变的断言。新增
具名 schema FK 清单回归在实际隔离 PG 退出 0：5 passed／1.99 秒，日志
`migration-named-schema-contract-postgres-20261013.log`。完整父链／MinIO 的原
canonical 测试所在 8312 已退出 0：5 passed／5 deselected／740.99 秒，日志
`run-plan-build-current-isolation-postgres-20261013.log`；其中四项原 rehearsal
与前述五项清单组重叠，不累计。原 canonical 的完整父事实／FK／归档／历史／
撤回／ACL 断言及 populated downgrade 拒绝均保留；未选择的其余五项不算通过。

18955 为当前阶段作用域、实际 PG 时钟／原账号／原事件的隔离 PG／MinIO 联合
回归，日志 `fixture-phase-current-contract-postgres-20261013.log`，现已退出 0：
72 passed／745.31 秒。该批包括显式 parent／target 样本，不替代原生 exweb 执行。
19446 为加载本轮实现的新隔离 exweb 全链，日志
`fixture-phase-current-owned-exweb-temporal-20261013.log`，仍在运行：原提交、
126 blobs、完整原用例／oracle 和等待时限不变，使用原离线 Maven 缓存及已核验
本地 image ID；它创建自己的测试资源和独立许可，不恢复上一轮失败／unknown。
模型及配套需求／用例仍是显式协议样本，不作为独立业务 gold。

Portal build／lint 已退出 0，日志 `fixture-phase-portal-{build,lint}-20261013.log`；
大 chunk 警告仍存在。随后原 smoke journey 使用自己的隔离 PG／私有 MinIO 及
独立 API／Portal 端口执行，2988 已退出 0，日志
`fixture-phase-current-smoke-20261013.log`，完整原检查及 `smoke: success` 均存在。
该流程不执行 exweb 目标或外部模型，不替代真实业务闭环或完整浏览器 E2E。
本轮原 exweb HEAD 为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain 为空。最新完整 V1、
五用途／旧链切换、自动 delta DAG、真实覆盖到 release、独立 gold、安全／容量／
DR／p95／试点等完整 P0-P6 条件继续保留；目标尚未完成。

## 画像选择读取与原 exweb 对照（2026-10-13）

本轮重新确认原句柄 20453、68136、84823 live，不因观察等待重启。
画像分页、文档成员和证据校验改为操作内只读选择，返回的选中记录仍是独立
深拷贝，完整 snapshot 默认隔离不变；原全图、来源字节和实时权限校验不减少。
新红测为 8 failed / 15 passed；原作用域/预算等回归为 104 passed，扩大边界为
244 passed / 4.77 秒，两者重叠。实际 PG/MinIO 回归现已退出 0：38 passed /
132.63 秒，完整响应、对象 hash、SQL/对象次数一致，只减少整幅画像复制。
日志为 `image-selection-copies-{red,green,final-boundaries,postgres}-20261013.log`。
Portal build/lint 均退出 0，大 chunk 警告仍存在。具体契约见[读取测量](./context-read-performance.md)。

固定原 exweb 浏览器首批 48454 已退出 1：9 passed / 1 failed / 4.9 分钟。
失败在历史画像测试准备阶段：临时源码修改后只做物化，没有显式采集新修订。
原第二幅画像、导航和历史不变断言保留；准备增加“未采集前画像不变”的断言，
再调用原 canonical ingest/materialize。使用新隔离 PG/MinIO、同原 exweb 和
独立端口的 28580 已退出 0：10 passed / 5.1 分钟，日志
`image-selection-copies-exweb-browser-final-20261013.log`。该批包含原仓库的
深浅色来源文档检查；目标应用和外部模型不执行，不把配套协议资料当作业务 gold。
`image-selection-copies-smoke-20261013.log` 记录原开发 smoke 全部检查及
`smoke: success`；其进程已不存在，但未取得原 shell 句柄的退出码，不能补造退出码。

68136 原 owned target 已退出 1，失败于 setup workflow 返回 failed 而非
completed。日志记录第一、二次 Activity 的 work_require/work_renew 因
HttpFixtureWorkLost 失败，第三次 grant_live_permission 因 PermissionError
被标记 AuthorityDenied；不能把它解读为目标用例已经通过或未知效果可以重发。
84823 旧加载完整 V1 已退出 1：8 failed / 7998 passed / 92 skipped /
3 warnings / 44119.98 秒，日志 `run-plan-case-v1-release-20261013.log`。
七项 fixture 执行/历史与一项 RunPlan 迁移检查失败，尚无最新完整门禁通过。
新隔离 PG/MinIO 复验原八项，句柄 41062，日志
`image-current-original-failures-postgres-20261013.log`；未扩大租约、grant 或超时，
也不恢复或重发旧 unknown 请求。五用途、旧链切换、自动 delta DAG、真实覆盖
到 release、独立 gold、安全/容量/DR/试点等完整 P0-P6 退出条件仍未满足。

## 原权限拒绝与规范来源证明复用（2026-10-13）

上一轮按用户问题解释数据关系，没有改实现。本轮重新确认原运行句柄和日志，
继续完整 P0-P6 目标，不改变原 exweb、oracle、分母、执行时限或许可期限。
之前代码增量的专项现已终态：

- `execution-activity-authority-red-20261013.log` 为 8 failed / 10 passed；
  原 fixture/case Activity 把权限拒绝也包装成可重试基础设施故障。
  当前共享分类器将权限拒绝／scope 失效／平台 403 标为 AuthorityDenied、
  non-retryable；取消原样传播，临时故障仍重试，终态仍受原活跃 lease 限制。
- `execution-activity-authority-green-boundaries-20261013.log` 已退出 0：
  378 passed / 126.66 秒，含原生命周期、未知派发与 DDD 边界。
- `execution-activity-authority-temporal-20261013.log` 已退出 0：
  8 passed / 57.43 秒。实际 Temporal 验证六种拒绝只调用一次及原历史 replay，
  并验证原两个归档后重试／取消 join 场景。新拒绝测试的 application/ledger
  使用显式替身，原 handoff 的 target 也为协议样本，不是真实 exweb 业务 gold。

已有 exweb 剖析显示一次完整原定义读取的 46 次对象来源图核验中，规范历史
的 36 次 facts 调用重复展开固定图。本轮实际 PG 红测
`authority-image-proof-red-postgres-20261013.log` 为 2 failed / 10 deselected /
18.77 秒：AC 与规则的四次只读 history/get 均额外重复完整画像核验。
现仅在只读入口复用拥有的完整画像对象／关系证明，并比较全部新鲜画像列；
完整规范历史、前驱、登记、原文工件和即时权限仍重新读取。写入、恢复、事件、
回填默认不启用；只打开 scope 或部分对象核验不产生完整证明缓存。

已确认终态：

- `authority-image-proof-ownership-final-postgres-20261013.log`：
  36 passed / 160.18 秒，实际 PG/私有 MinIO，包括全部画像字段错配、
  实时撤回／登记损坏、写入不复用、未核验作用域、thread/task/结束边界。
  前一探针批 1 failed / 23 passed / 12 deselected 是主键错配触发 ORM
  自动刷新；最终探针用 no_autoflush 保持只读，全部字段拒绝断言未减少。
- `authority-image-proof-boundaries-20261013.log`：175 passed / 2.49 秒。
  与前述 378 项有重叠，不累计为完整门禁数量。
- Portal build/lint 原句柄均已退出 0，日志
  `authority-image-proof-portal-{build,lint}-20261013.log`；大 chunk 警告仍存在。

6517 的规范／上下文来源联合 PG 回归已确认退出 0：93 passed /
940.58 秒，日志 `authority-image-proof-green-postgres-20261013.log`。
它加载早于下述异常清理修复；与 36 项有重叠，不累计。

扩大边界选择集 `authority-image-proof-final-boundaries-20261013.log`
退出 1：3 failed / 207 passed / 3.35 秒，发现之前缓存退出代码在访问
`Session.info` 出错时跳过 rollback/close，掩盖原设置／业务异常。
现用外层 finally 保证即使缓存清理失败也 rollback 并 close；无缓存元数据的
连接适配器不假造缓存。原三项配置测试不修改，并新增缓存清理失败／rollback
失败与成功清除的三项资源契约。当前
`authority-image-proof-final-cleanup-boundaries-20261013.log` 已退出 0：
213 passed / 3.26 秒。54669 是加载该修复的真实 PG 完整画像／所有字段／
复制上下文与有限连接池回归，现已退出 0：38 passed / 19.50 秒，日志
`authority-image-proof-current-cleanup-postgres-20261013.log`。它与 36 项有重叠，
不累计为完整验收数量；资源契约证明不是完整容量／p95 验收。

首次完整 exweb 对照 98043 已退出 0，但实际为 1 skipped / 2 deselected：
未提供显式原仓库执行开关，不是 exweb 验证成功。重新以原固定 126 blobs、
离线 Maven 镜像与依赖缓存运行原完整 journal 对照，句柄 20453，日志
`authority-image-proof-full-original-exweb-enabled-postgres-20261013.log`；
现已确认退出 0：1 passed / 2 deselected / 1694.84 秒。全部连接池计数
control SQL 35027（主池 13658 / 其他 21369）、production 34867（主池
13658 / 其他 21209），对象 4467 -> 4465，150 个唯一原对象 hash 与完整
输入一致，两侧 scope/plan/environment 各三次。仅证明这次原完整只读对照，
`target_executed=false`、`business_gold=false`、`capacity_or_p95_acceptance=false`。
并以当前代码运行原 owned exweb 公共 PG/MinIO/Temporal 全链，句柄 68136，
日志 `authority-image-proof-owned-exweb-temporal-20261013.log`，后续已退出 1，
失败详情见最新段落。
两批均加载早于最后异常清理和选择复制修复，不重启原已认领执行。
未扩大原 900 秒等待、grant、lease 或改变原 case/oracle。
84823 的旧加载完整 V1 后续已退出 1，具体数量及原失败复验见最新段落。

本轮原 exweb HEAD 仍为 fe5827f6b76f77ef34918d8b452ee823142332dc，
porcelain 为空。规范证明复用不等于性能达标或真实目标执行通过；五种用途、
旧链切换、自动 delta DAG、真实覆盖／release、独立 gold、容量／DR／试点和
最新完整 V1 仍未满足完整退出条件，目标保持 active。

## 独立审阅的当前账号与原命令读取（2026-10-13）

上一轮只读解释数据关联，本轮按原 P0-P6 目标继续实现。
开始经原运行句柄确认 73883、58750、51029、84823 均仍 live，
未因观察超时重启，也没有改变 exweb 输入、原 oracle 或性能断言。
随后 73883 已确认退出 0：94 passed / 1113.84 秒，日志
`context-proof-snapshot-complete-regression-postgres-20261013.log`。
该联合 PG/MinIO 回归没有此前的迁移选择排除，但加载早于最后只读
opt-in 收紧及本轮权限修复，不能作为当前完整 V1 通过证据。

本轮发现范围审阅、画像发布与上下文失效的 `SELECT FOR UPDATE`
不会自动刷新 Session 已保留的账号/角色对象。实际 READ COMMITTED
会话先保留对象，再由第二个 PG 连接提交禁用或降权，旧审阅 guard
可能继续使用旧身份事实。`image-reviewer-freshness-red-postgres-20261013.log`
已确认退出 1：9 failed / 3 passed / 29 deselected / 2.64 秒；
项目角色直接撤销被原查询条件阻断，但账号禁用、角色降权和平台
管理员降权的三个政策均暴露问题。

三个仓储的账号和角色锁查询现显式 `populate_existing=True`；
不去掉 `FOR UPDATE`，不改变独立项目审阅、发布仅管理员、scope/
invalidation 可 qa_lead 的原政策。范围审阅的原 canonical 命令也
发现同样问题：取消、改 tool、改确认人或改 request 后，锁查询仍
可返回旧对象。真实 PG 红测为 4 failed / 42 deselected / 2.43 秒，
日志 `image-scope-command-freshness-red-postgres-20261013.log`。
原命令锁查询现也强制刷新；不新建命令，不延长许可或修改工件。

最新专项 `image-reviewer-and-command-current-postgres-20261013.log`
已确认退出 0：32 passed / 14 deselected / 3.56 秒，验证上述实时
拒绝、原账号/角色/命令 NOWAIT 行锁及事务释放、原管理员正向政策
和发布与 qa_lead 的区别。测试直接检查独立私有 PG guard；无真实
画像批准、目标执行、业务 gold 或覆盖放行声明。
较早加载的 `image-reviewer-freshness-green-postgres-20261013.log`
退出 0：64 passed / 347.35 秒，含原 fixture/native actor 专项和
脚本默认 PG 回归；启动早于随后原 canonical 修复与新增五项测试，
不与 32 项累计。当前领域/DDD/来源/authority/准入/容器边界日志
`image-reviewer-current-boundaries-20261013.log` 为 234 passed / 3.73 秒。
Portal build 与 lint 的原句柄均已退出 0，日志
`image-reviewer-portal-{build,lint}-20261013.log`；大 chunk 警告仍存在。
本轮未改 UI，也没有新增完整浏览器 E2E/smoke 全绿声明。
最后文档更新后的边界选择集退出 0：163 passed / 2.04 秒，日志
`image-reviewer-final-doc-boundaries-20261013.log`；与 234 项重叠，不累计。

21208 是当前代码的范围审阅、发布、回滚、上下文失效、独立用例
准入和新 reviewer 测试完整 PG 回归，日志
`image-reviewer-current-authority-regression-postgres-20261013.log`；
后续已确认退出 0：107 passed / 1 skipped / 1786.85 秒。该批加载早于
上述 Activity 分类和规范证明复用，不是最新完整 V1；skip 原因未从该
日志确认，不将其计入通过。58750 后续已确认退出 0：1 passed /
16 deselected / 2519.93 秒，完整原 journal 对照 SQL 为 43451/43291、
对象为 4467/4465；三次 scope/plan/environment 及完整输入 hash 一致，
只读、无目标执行，未声明 p95 达标。该批同样早于本轮规范证明复用。
51029 的旧加载 owned target 后续退出 1：1 failed / 14 passed /
4703.66 秒，原 handle.result 的 900 秒等待超时。它曾记录一次
`work_final_authority` PermissionError、`work_renew` 119570 ms 和
`worker_execute` 401280 ms 的 Activity 失败；此前 acquire 已通过。
不能断言具体是角色、时限或其他权限原因，也不因 Activity 重试推定
恢复成功。84823 旧 V1 的后续状态见最新段落。

本轮核验原 exweb HEAD 仍为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain 为空。
修复推进独立 authority/current ACL 的安全边界，不替代正式五用途
消费者、旧链切换、自动 delta DAG、真实 coverage/release、安全/
容量/DR/独立 gold/性能/试点与最新完整 V1 的原要求；目标保持 active。

## 固定上下文证明与全连接池计量（2026-10-13）

上轮仅核查数据关联；本轮继续原 P0-P6 实现与原 exweb 验证。
开始时经原句柄确认 51029、84823 仍 live，未因观察时间届满重启。
上一轮文档最后的边界选择集已确认 166 passed / 1.79 秒，日志
`fixture-worker-actor-final-boundaries-20261013.log`，与原选择集有重叠。

2965 已确认退出 1：1 failed / 16 deselected / 2625.83 秒，日志
`fixture-journal-operation-original-exweb-postgres-20261013.log`。
原 exweb 126 blobs／725 成员、完整私有对象摘要和三次原 scope/plan/
环境输入对照未改变，失败发生在 SQL 减少断言。旧计量为主池
26240/26240 SQL、4467/4465 对象读取；不能声明该批性能通过。
本轮发现 listener 只挂主 engine，未统计独立画像快照池；这些 SQL
数字不是全连接池总量。现有三个完整原输入对照均改为监听全部
SQLAlchemy Engine 的执行事件，同时区分主池／其他池。原完整输入、
原读端口次数、对象 hash、禁止写入和 SQL/对象减少要求均保留。

生产增量将 ContextPack 的完整来源/关系锚点核验接入当前拥有的
只读 MVCC 快照，最多两个成功 context 证明；退出清除，失败不缓存。
新鲜元数据与固定证明全字段比较，快照建立后提交的新 context
另做完整新鲜核验，不缓存缺失。当前 ACL、authority、审阅/发布头、
stale、lease、grant 和原计划 DTO 不缓存；原文与 MinIO 工件照常核验。
只读上下文发布依赖显式复用同一完整画像来源证明，原 canonical
compile/publication/review 命令及依赖链仍每次在新鲜会话校验。
转交默认关闭，写 context、事实登记和 backfill 不启用，不延伸到确认
或提交；thread/task/结束边界沿用现有 OperationReadScope。

已确认的测试终态（重叠选择集不累计）：

- 实际 PG 红测 `context-proof-snapshot-red-postgres-20261013.log`：
  1 failed / 15 deselected / 11.43 秒，两次读取四次来源证明，预期复用
  失败；初版绿测为 2 passed / 14 deselected / 20.15 秒。
- `context-proof-snapshot-final-postgres-20261013.log`：56 passed /
  2 deselected / 629.93 秒。包括原生 context/图锚点、失败、损坏、
  bounded cache、复制 task/thread、画像快照及实时 AC/ACL 检查。
  该批加载早于后续跨会话画像复用，排除了两项 populated migration
  选择；不能作为最新完整迁移或 V1 通过。
- 实际 PG 原画像跨会话红测为 1 failed / 27 deselected / 2.60 秒；
  `image-proof-cross-session-green-postgres-20261013.log` 为 4 passed /
  24 deselected / 3.75 秒，检查完整证明复用和错误项目/画像/manifest
  元数据拒绝，加载早于后续显式只读 opt-in 收紧。
- `context-proof-original-commands-and-sql-postgres-20261013.log`：
  4 passed / 27 deselected / 53.67 秒。实际全部连接池 SQL 对照保持
  context 元数据输入一致，并验证缓存已建立后修改原 compile、
  publication 或 review 命令仍拒绝。小文档是明确协议 specimen，
  不代表原 exweb 延迟、容量或业务 gold。
- 当前 `context-proof-snapshot-current-unit-20261013.log`：635 passed /
  16.18 秒，包含 fixture/worker/runtime/命令/取消、NativeBuild、
  操作生命周期及 DDD/来源/容器边界。较早的 161 和 473 项重叠，
  不加总。首次 unit 命令因错误文件名退出 4、没有运行测试，保留
  `context-proof-snapshot-final-unit-20261013.log`，不记为测试通过。
- 最后文档更新后的来源/DDD/fixture/容器边界：
  `context-proof-snapshot-final-doc-boundaries-20261013.log` 为 182 passed /
  2.26 秒；与上面的选择集重叠，不累计。
- Portal build/lint 原句柄均退出 0，日志
  `context-proof-snapshot-portal-{build,lint}-20261013.log`；大 chunk
  警告仍存在。本次没有 UI 改动或最新完整 E2E/smoke 通过声明。

73883 为无上述迁移排除的 PG/MinIO context、publication、retrieval 与
画像快照联合回归，日志
`context-proof-snapshot-complete-regression-postgres-20261013.log`。
30906 的最终只读 opt-in、普通事务、write-context 和后提交新事实专项
已确认退出 0：8 passed / 41 deselected / 46.68 秒，日志
`context-proof-snapshot-write-and-new-fact-postgres-20261013.log`。
73883 终态待确认，启动早于最后 write opt-in 收紧，不能独自证明
当前全部代码已验收。
最后显式只读 opt-in 下的原 command 和全部连接池计量再次确认退出 0：
`context-proof-snapshot-final-live-command-postgres-20261013.log` 为
5 passed / 29 deselected / 53.99 秒；此前 4 项选择集重叠，不相加。

58750 为新的全部连接池完整原 exweb journal 对照，日志
`fixture-journal-operation-all-pools-original-exweb-postgres-20261013.log`。
加载固定 context 和跨会话画像只读证明，早于最后写分支 opt-in 收紧；
尚无终态，不声明全量 I/O、p95 或真实执行通过。51029 的原 owned
target 与 84823 的旧 V1 仍按原句柄推进，后者已有失败，均不重启或
改写历史。原 exweb HEAD 不变且 porcelain 为空。

正式五用途/消费者、自动增量 DAG、真实业务覆盖至 release、安全/
容量/DR/独立 gold/性能/试点及最新完整 V1 仍按原范围交付。
本轮为 progress，目标保持 active，专项不替代完整退出条件。

## Worker 新鲜权限与原生租约失败分段（2026-10-13）

上轮普通问答只核查数据关联，没有实现变化；本次继续原 P0-P6 目标。
先经原句柄确认 87001、14506、84823、2965 live，未因观察时间届满
重启。35663 句柄已不存在，原日志确认 172 passed / 14 deselected /
1 warning / 458.41 秒；这是上一轮加载的 API、runtime config 与容器
契约，不是本次最终权限代码或完整 V1 验收。

14506 随后经原句柄确认退出 1：1 failed / 14 passed / 4712.96 秒，
日志 `run-plan-fixture-handoff-owned-exweb-worker-phase-20261013.log`。
首个失败为 `runtime_acquire / PermissionError / 97005 ms`；后续尝试
在 `grant_live_permission` 被拒，之后原 command 失效，最终 workflow
返回 failed 而非 completed。首个失败尚不能细分到具体权限守卫，也
没有将后续过期或本次 ORM 修复倒推为它的已证根因。原权限时限、
90 秒租约、用例、oracle 和 unknown 不重发规则保持不变。

实际隔离 PG 复现同会话 ORM 身份陈旧：
`fixture-worker-actor-freshness-red-postgres-20261013.log` 为 3 failed /
1 passed / 21 deselected / 2.18 秒。保持账号／角色对象的强引用后，
另一连接提交账号停用、项目角色降级或平台角色降级，旧 Worker
fence 没有拒绝；角色撤销负向对照原本拒绝。
`fixture-native-actor-freshness-red-postgres-20261013.log` 又确认加锁
查询也有相同问题：3 failed / 5 passed / 25 deselected / 2.46 秒。
不能把 `FOR UPDATE` 当作刷新已加载 SQLAlchemy identity 的保证。

现在 Worker 的账号/项目角色、NativeBuild 的只读/加锁账号和角色
均使用 `populate_existing=True`，写分支仍保留原行锁。额外 acquire /
require / renew 诊断仅将原代码分为固定守卫阶段，不改变授权、锁、
调用次数、TTL、原异常或 rollback；无异常正文、traceback、来源、SQL
或凭据输出，不增加重试和副作用派发。

本次最终已确认终态（重叠选择集不累计）：

- `fixture-worker-native-actor-lock-contract-postgres-20261013.log`：
  48 passed / 14 deselected / 9.89 秒。含同会话撤权、只读并发读取、
  PG 慢守卫/过期与回滚、15 个诊断失败边界，以及真实第二连接的
  `FOR UPDATE NOWAIT`：写分支锁账号/角色，只读分支不加锁，事务结束
  释放锁。parent/角色是明确协议 specimen，不是原生 RunPlan/业务 gold。
- `fixture-worker-actor-final-unit-20261013.log`：673 passed / 19.97 秒。
  覆盖 fixture 原命令/异步生命周期/原生许可/完整父端口、取消、
  Scope thread/task 隔离、NativeBuild 与 DDD/容器边界。
- Portal build/lint 均经原句柄确认退出 0，日志
  `fixture-worker-actor-portal-{build,lint}-20261013.log`；大 chunk 警告
  仍存在。本次无 UI 变更，不声明最新完整 E2E/smoke/V1 通过。
- 87001 也已确认退出 0：18 passed / 14 deselected / 1802.20 秒，
  `fixture-operation-read-scope-journal-final-postgres-20261013.log`。
  这是上一轮新 journal scope 和只读历史权限的 PG/MinIO durability
  加 actor/clock 回归，保留原失败、unknown 防重及原子事实事件；
  不是加载本次最终权限刷新代码的实际目标验收。

旧 owned target 终态后启动独立批 51029，日志
`run-plan-fixture-handoff-owned-exweb-scoped-worker-20261013.log`。
它加载新的 parent pair、journal operation scope、只读历史锁修复及
Worker 刷新/阶段诊断，启动早于本次 NativeBuild 写锁字段刷新；
终态尚未确认，不把它当作最新全部修改或覆盖/release 已通过。
该段记录时 2965 完整原 exweb journal 操作只读对照和 84823 旧加载
V1 均 live；2965 后续失败终态与计量缺口已记录在上方最新段落。
旧 V1 已有失败，不停止原任务或把点数当绿色结果。

原 exweb HEAD 再次确认为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，
porcelain 为空。正式五用途 ContextPack/消费者、自动增量 DAG、
真实业务覆盖至 release、安全容量/DR/独立 gold/性能/试点及最新
完整 V1 继续按原范围交付。本次为 progress，目标保持 active，
不标记 complete/blocked，不用权限专项替代完整退出条件。

## 原 journal 作用域与只读历史写锁修复（2026-10-13）

上轮普通问答只解释当前数据关联，不改变实现。本次目标推进开始时经原句柄
确认 7759、14506、84823 仍 live，未因观察超时重启。7759 后续终态见
本节收尾记录；真实 owned target 批现已推进到 runtime binding 与
command fence，尚无执行终态；旧 V1 批仍已有失败，不能
作为包含最新代码的完整绿色门禁。

本轮实现 `HttpFixtureSavedPlanAccessPort.verified_read_session`：journal
inspect/claim/complete 和 worker acquire/require/renew 在一次同步操作内
共享原 RunPlan port 的不可变证据作用域。每次原 parent/scope/command
校验仍完整调用读端口；权限、审批头、原 live grant、目标健康和 PG
owner/epoch/clock 均不缓存。生命周期、线程及 asyncio task 边界沿用
`OperationReadScope`，操作结束关闭，子任务和 to_thread 不继承父证明；
没有改变原事实、wire/hash、90 秒租约、15 分钟许可或 unknown 防重。

同时复现 journal `read_only=True` 仍对当前账号／角色执行 `FOR UPDATE`：
实际隔离 PG 红测试为 4 failed / 14 deselected / 2.95 秒，均为
`ReadOnlySqlTransaction`，日志 `fixture-readonly-actor-lock-red-postgres-20261013.log`。
只读分支现使用无写锁且 `populate_existing=True` 的新鲜角色查询；原生
构建和 journal 写分支仍默认加锁。空库存、未完成原 dispatch 和完整
结果返回前均再核验账号／角色，未完成 dispatch 另复核原来源 scope。
没有把读取他人历史变成当前确认或执行权。

本轮已确认的终态：

- `fixture-operation-read-scope-final-unit-20261013.log`：549 passed /
  10 skipped / 15.25 秒，覆盖实际作用域接线、所有原读取阶段失败、
  线程/task 隔离、旧 port、租约／取消／诊断、原生构建和 DDD 边界。
  十个 skip 明确是没有配置隔离 PG 的 image snapshot 测试，不算通过。
  早期 342 项与该选择集重叠，不相加。
- 已单独在实际隔离 PG 补跑该十项：
  `fixture-operation-image-read-snapshot-postgres-20261013.log` 为
  10 passed / 14 deselected / 8.38 秒。
- `fixture-operation-actor-clock-final-postgres-20261013.log` 为
  17 passed / 14 deselected / 8.81 秒。实际持有另一连接的账号／角色
  写锁时，READ ONLY 历史检查可完成；账号停用、角色撤销／降级在
  新事务及本次原记录读取后均拒绝。PG acquire/renew 的所有慢守卫、
  最后撤权回滚、原 parent 改变及过期 owner 不复活仍通过。
  这组 actor/parent 是明确协议 specimen，不是原生 RunPlan 或业务 gold。
- Portal build/lint 均退出 0，日志
  `fixture-operation-read-scope-portal-{build,lint}-20261013.log`；大 chunk
  警告保留。没有本轮 UI 变更或最新完整 E2E/smoke/V1 通过声明。
- 文档更新后边界／容器契约选择集再次确认退出 0：
  `fixture-operation-final-boundaries-20261013.log` 为 166 passed / 2.11 秒；
  与上述边界选择集有重叠，不累计为总测试数量。

35663 已启动实际隔离 PG/MinIO 的 `test_api.py`、`test_runtime_config.py`
及 `test_docker_stack_contract.py` 基础回归，日志
`fixture-operation-api-runtime-stack-postgres-20261013.log`。同句柄仍 live，
尚无终态，不以进行中的选择集替代最新完整 V1 或 E2E/smoke。

87001 的 PG/MinIO 原 journal durability 与上述 actor/clock 联合回归
已启动，日志 `fixture-operation-read-scope-journal-final-postgres-20261013.log`；
终态尚未确认，不把已打印的点当作整个选择集通过。

2965 是加载新作用域和只读权限修复的完整原 exweb journal operation
对照，日志 `fixture-journal-operation-original-exweb-postgres-20261013.log`。
新测试在 READ ONLY 事务执行真实 journal.inspect，比较全部原计划
返回摘要、三个原 scope/plan/环境读回及每个私有原对象的 hash；要求
不减少原读端口调用而减少 SQL/对象重复 I/O，不调用 Runner／新模型。
启动时确认 live，尚无结果，不声明性能／p95 或业务覆盖通过。7759
只验证上一版 parent pair，14506 加载早于本轮修复；都不能代替该新
操作对照或最新目标执行验证，也没有停止仍在运行的原任务。

本轮收尾经原句柄确认 7759 退出 0：1 passed / 15 deselected /
2477.97 秒，日志 `fixture-journal-parent-original-exweb-postgres-20261013.log`。
原 exweb 126 blobs／725 成员、PG／MinIO、reviewed offline build 下，
两模式完整输入 digest 均为
`sha256:588e1b4c9a1caf9ff5940ef64074d2c49f52c496362fb5425a097657617e51dd`，
全部 150 个唯一原工件的 hash 一致。control/production SQL 为
17311/8732，对象读取 2845/1489，plan 读回 2/1，环境均一次。
这是此前成对父端口的实际只读验证，不是新同步 operation 作用域的
性能结果；未派发目标，Provider/业务 oracle 为明确协议 specimen，
不作为 business gold、容量/p95 或完整 V1 验收。

原 exweb HEAD 仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，
porcelain 为空；不修改原 source、case、oracle 或分母。正式五用途
ContextPack／消费者、自动增量 DAG、真实业务覆盖至 release，以及
安全容量／DR／独立 gold／性能／试点和最新完整 V1 继续待交付。
本轮是 progress，不缩小完整 P0-P6 目标，不标记 complete 或 blocked。

## 新脚本消费独立用例准入与 Worker 实际失败定位（2026-10-13）

上一次目标推进已交付准入消费、PG 0122 与 Portal，属于 progress；随后一次
普通问答仅解释当前数据关联，没有改动实现。本轮先复核终态，不把历史 live
描述继续当作进程证据，也未因观察超时重新启动原任务。

0122 给 `quality_automation_call_reservations` 增加成对的独立 case approval
revision/hash 和同项目、同 generation 的复合 FK。新脚本预览与调用必须通过
`AutomationCaseAdmissionPort` 检查完整原 case/oracle/context/scope/generation/
mapping/input/cohort basis；模型调用前、回执和结果提交前重新检查当前批准。
call plan v2 固定准入 pin，改变准入须重新确认。迁移不 UPDATE 旧事实，不自动
给旧 draft 添加批准；旧请求仍按原 wire/hash 序列化，历史缺准入只能只读，
`current_use.input_current=false`，不能进入新生成、审阅或 RunPlan。

Portal 回读独立当前审批头且比对完整 prepared input；缺批准、已撤回或字段
不一致时不预览预算、不调用模型。确认绑定准确审批头，变化后失效。受控
`quality.test_design_cases.reviewed` SSE 刷新脚本/审阅/RunPlan 查询，保留去重、
合并和当前项目检查，不在客户端补造批准或自动重发写入。

已复核上一批终态：

- `automation-case-admission-boundaries-20261013.log`：281 passed，3.68 秒。
  domain/application/旧脚本和 DDD 边界选择集，不是完整 API。
- `automation-case-admission-portal-events-final-20261013.log`：100 passed，
  448.51ms；包括增量事件刷新、重复事件、权限/导航隔离和旧归档只读校验。
- Portal build/lint 已退出 0，日志 `automation-case-admission-portal-{build,lint}-final-20261013.log`；
  chunk 警告未消除。
- 实际隔离 PG/MinIO 普通专项先因测试读取错误的 HTTP error key 失败：
  1 failed / 41 deselected / 78.48 秒。正确契约为 `detail.error.code`，只修正
  测试后 `automation-case-admission-current-postgres-rerun-20261013.log`
  为 1 passed / 41 deselected / 257.00 秒；包含真实复合 FK 拒绝、canonical
  准入/生成/撤回及历史内容不改写。Provider transport 为协议夹具。
- `automation-case-admission-browser-all-current-20261013.log`：4 passed，
  2.0 分钟；两种主题、两种语言、无准入禁用及撤回后确认失效。该命令的
  Playwright runner 使用隔离 PG/文件对象存储，不是 MinIO；模型和审批响应
  为明确协议夹具，不是业务 gold、外部模型或真实网络 SSE。

原始 exweb 准入专项 9706 已退出 1：1 failed / 42 deselected / 255.68 秒，
日志 `automation-case-admission-original-exweb-postgres-20261013.log`。
失败在测试 `verify_fixed_exweb_archive(v)` 漏传完整输入，而不是业务放行。
现从原脚本 input port 读取完整 prepared 后传入；不修改任何原 case、oracle、
源文件或分母。65350 是修复后新专项，日志
`automation-case-admission-original-exweb-postgres-rerun-20261013.log`，已退出 0：
1 passed / 42 deselected / 726.05 秒。完整原来源及固定画像成员、PG typed FK、
新脚本准入消费、撤回阻断新命令和原私有草稿不改写通过；模型仍是协议夹具，
没有派发目标，也不把该单项作为独立业务 gold 或完整 V1 通过。

父对象对照 56722 已退出 0：1 passed / 14 deselected / 1093.31 秒，日志
`fixture-grant-parent-original-exweb-postgres-20261013.log`。两模式完整输入均为
`sha256:8e96d568073f10a094de7fb6ed5b489b24c7259e6829481e03d7b2704137c82d`，
全部 150 个唯一原对象一致。历史 control/production SQL 为 15463/6251，
对象读取 2538/1042；live 为 28187/12724、4620/2083，PG live gate 均一次。
这是实际 PG/MinIO、原 exweb/离线构建的只读对照，不是 target execution、
business gold、容量或 p95 验收。

81830 已退出 1：1 failed / 14 passed / 2241.71 秒，日志
`run-plan-fixture-handoff-owned-exweb-event-version-current-20261013.log`。
原 event sequence 冲突后已进入 Worker，但基础设施异常被安全脱敏，原日志
无法定位最初失败；第四次已经是 live permission 过期，不能将它认定为前三次
的根因。没有延长许可、替换用例或自动重新授权。

本轮在 application 的 command/access/execute/archive/commit，以及 worker
runtime 的输入、binding、fence、acquire 和最终授权添加固定白名单 phase。
日志只含固定阶段、固定异常类型和耗时；未知类名归为 other，无异常正文、
堆栈、SQL、原文或秘密，不改变异常传播、取消或未知副作用不重发语义。
新增故障测试先 10 failed / 36 deselected / 1.14 秒
(`fixture-worker-phase-red-20261013.log`)，修复后相关合并选择集 283 passed /
6.08 秒 (`fixture-worker-phase-unit-20261013.log`)。14506 在旧批终态后加载
新诊断重验原始完整 owned exweb/PG/MinIO/Temporal，日志
`run-plan-fixture-handoff-owned-exweb-worker-phase-20261013.log`；尚无通过声明。

继续发现私有 Fixture journal 在环境档案已经核验完整父 RunPlan 后，又单独
展开同一个计划。新增 `HttpFixtureEnvironmentReadPort.read_with_plan`，实际
environment use case 返回本次读取已经完整验证的档案和深拷贝 parent；
Scope 校验继续检查全部 project/id/hash/manifest/plan body/native inventory
pins。每次操作重新读取完整父链及当前 ACL，不跨操作缓存，不查询 latest，
不延长 lease/grant；成对端口损坏或失败直接拒绝，不静默切回另一个 reader。
旧 read 的 JSON/hash 和没有此端口的旧完整读取算法保持不变，未修改 ORM。

新 parent 端口测试先 8 failed / 66 deselected / 1.32 秒
(`fixture-journal-parent-port-red-20261013.log`)。中间 372/481 项选择集与最终
批重叠，不相加；最新 port/取消/租约/安全诊断/原命令/用例准入/DDD 合并为
484 passed / 11.97 秒，日志
`fixture-journal-parent-and-admission-final-unit-fenced-20261013.log`。
Portal build/lint 均退出 0，日志 `fixture-journal-parent-portal-{build,lint}-20261013.log`，
大 chunk 警告仍存在。未重复做本轮浏览器、smoke 或最新完整 V1。

7759 是新 parent 对照的实际隔离 PG/MinIO、完整原 exweb/离线构建专项，日志
`fixture-journal-parent-original-exweb-postgres-20261013.log`。对照分别展开旧算法
和新端口，在 READ ONLY 事务中比较完整返回内容、全部原对象 hash 和读取量，
不调用 Runner、不新增模型调用、不修改原规范或执行事实。进程已启动，终态
未确认。14506 加载的是此前阶段诊断，不包含这个后续 parent 优化；没有停止
该仍 live 的验证来伪称重测新代码，两个批次不能互相充当终态或性能证明。

再次检查原 exweb HEAD 为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，
`git status --porcelain` 为空。84823 原完整 V1 批仍经原句柄确认 live，已有
失败，且不包含全部后续代码；不能声称最新完整 V1 全绿。0122 是正式
automation 的必要准入消费，不是五用途 ContextPack、完整自动 DAG、业务
覆盖/release、安全容量/DR/性能/独立 gold/试点完成；完整 P0-P6 目标保持 active。

## 原生绑定事件序号冲突与完整许可父对象复用（2026-10-13）

上一轮只按用户请求解释数据关联，属于 no progress。本轮按同一句柄继续验证，
未因观察超时或耗时重启任务。72683 已退出 0：3 passed / 15 deselected /
713.58 秒，日志 `output/fixture-grant-late-clock-current-postgres-20261013.log`；
覆盖两个完整原来源校验后的确认过期阶段及原 recipe/grant PG 回归。
76790 已退出 0：2 passed / 14 deselected / 700.77 秒，日志
`output/environment-binding-parent-exweb-final-acl-postgres-20261013.log`；完整
响应、全部原对象 hash、固定 exweb 126 blobs/725 成员及最终真实撤权保护均通过。
该对照不是目标执行、gold 或 p95 门禁。

89077 已退出 1：1 failed / 14 passed / 1456.60 秒，日志
`output/run-plan-fixture-handoff-owned-exweb-binding-phases-20261013.log`。
完整 input、PG live permission、preparation、intent 写入/核验通过，固定诊断明确
失败发生在 `bind_event_persistence`。检查统一 Outbox 发现写入时先把版本置为 PG
sequence，而 fixture fact verifier 仍要求版本等于 0。新正序号 specimens 首先
退出 1：3 failed / 3 passed / 71 deselected / 1.03 秒，日志
`output/fixture-command-event-version-red-contracts-20261013.log`。
现按统一序号契约接纳非负严格整数版本；Outbox 持久行/正 sequence 一致性、原
intent、归属、确认和事件内容检查均不删减。未记录异常正文，未改原 exweb 源码、
oracle、用例、fixture 或许可窗口。

同时确认 worker 原算法重复展开许可/定义/环境。新增 parent specimens 首批
3 failed / 3 passed / 1.12 秒，日志
`output/fixture-grant-parent-reads-red-contracts-20261013.log`。现在在一次完整
校验内保留已核验父对象；live 输入仍有两次独立完整 current 读取与 PG live gate，
历史解析一次且不执行 live gate。现有单操作配对计数改为一次完整读取，并额外
确认下一操作仍重新读当前计划；不改业务计数或期望结果。初次合并 2 failed /
130 passed / 5.00 秒：一个是 Python 3.9 Counter 缺省零键比较，一个是旧重复
读取计数；日志 `output/fixture-grant-parent-current-contracts-20261013.log`。
修正后 544 passed / 14.15 秒，日志
`output/fixture-grant-parent-current-boundaries-rerun-20261013.log`；前一次路径
写错退出 4 且没有执行测试，`fixture-grant-parent-current-boundaries-20261013.log`。

本轮最终 parent/event/clock/原 fixture/Outbox/DDD 合并批退出 0：803 passed /
26.00 秒，日志 `output/fixture-parent-event-final-contracts-20261013.log`；早先
463 passed / 13.72 秒的 event 合并批与之重叠，不相加。Portal build/lint 退出 0，
日志 `output/fixture-parent-event-portal-{build,lint}-20261013.log`，大 chunk 警告
仍存在。没有本轮浏览器/E2E/smoke 证据，静态通过不替代这些门禁。

新增完整 PG/MinIO 原输入对照 56722 使用固定原 exweb 和原离线构建，日志
`output/fixture-grant-parent-original-exweb-postgres-20261013.log`，经原句柄确认
live；模型/目标 transports 明确是协议夹具，不作原生执行或业务 gold。普通
无 PG 环境下 collection 退出 2（ARRAY 不支持 SQLite），没有执行测试；保留
`output/fixture-grant-parent-pg-collection-20261013.log`，不改成 SQLite 降级。
新增实际 canonical/PG/MinIO event 49822 已退出 0，日志
`output/fixture-command-event-version-current-postgres-20261013.log`，唯一选中的
新测试通过。双 quiet 没有打印时长/统计摘要，不补造耗时。该测试验证非法 coverage
patch 的 intent/preparation binding/审计/Outbox 整事务回滚、合法正 sequence 的
canonical running 绑定及持久化重放，以及真实 PG savepoint 内序号/patch 篡改的
拒绝与回滚。workflow ACK 和 target/model transports 为明确协议夹具，未派发
HTTP，不把合法事件序号视为真实目标执行或覆盖。
原生失败批 terminal 且其 owned 容器已退出后，81830 使用原完整 exweb、PG/MinIO/
Temporal/owned Docker 加载当前修复复验，日志
`output/run-plan-fixture-handoff-owned-exweb-event-version-current-20261013.log`；
仍运行，不声称根故障的目标全链已经修复。84823 原完整 V1 批仍 live，已有失败，
不是当前代码完整全绿证据；没有因耗时重启。

五类正式用途包及消费者、自动增量 DAG、真实业务覆盖到 release、安全容量/DR、
完整 Provider/gold/校准、浏览器/真实试点和最新完整 V1 仍按原 P0-P6 目标验收。
以上专项没有替代这些要求；目标保持 active。

## 限时许可提交窗口与父计划实际对照（2026-10-13）

上一轮按用户请求解释数据关联，没有改变实现；本轮继续推进原完整 P0-P6 目标。
相同句柄 29067 与 84823 已重新确认 live，没有因观察耗时重启。99488 已退出 1：
2 failed / 14 deselected / 565.51 秒，日志
`output/environment-binding-parent-exweb-prepared-postgres-20261013.log`。原准备
helper 已完成，但新测试错误地从写回执读取只在查询回执出现的 `run_plan_build`，
因此尚未执行 READ ONLY 对照。现按原 API 契约从对象引用取得 binding ID，再
授权回读完整原绑定；不新增写回执正文、不减少校验。89502 重新运行两个对照，
日志 `output/environment-binding-parent-exweb-readback-postgres-20261013.log`，
经句柄确认 live，仍不能声明实际性能改善或全链通过。

检查 `HttpFixtureGrantRepository.issue` 发现独立确认只在事务开始时用 PG 时钟
校验，完整来源校验和 Outbox 写入后没有再次检查。慢校验可跨越确认窗口，但这
只是已定位的提交不变量缺口，不是旧 exweb 执行失败的已证实根因。新签发现于
第一条写入前、最终权限校验与 flush 后再次核验同一原 canonical 命令及 PG 时钟。
过期整事务拒绝；原有效期、签发字节、权限范围和历史恢复分支不变，不续期、
不自动重发、不把历史许可升级成执行覆盖。

新增事务／时钟 specimens 首先退出 1：2 failed / 2 passed / 1.04 秒，日志
`output/fixture-grant-late-clock-red-contracts-20261013.log`，两个预期过期分支
均未抛错。修复后的许可／原生许可／诊断／父对象／handler 合并契约集退出 0：
262 passed / 11.17 秒，日志
`output/fixture-grant-late-clock-current-contracts-rerun-20261013.log`。
DDD／fixture／plan／build 边界集退出 0：155 passed / 2.21 秒，日志
`output/fixture-grant-late-clock-current-boundaries-20261013.log`。最初合并命令
引用了错误的边界文件路径，退出 4 且没有执行测试，日志
`output/fixture-grant-late-clock-current-contracts-20261013.log`，不计为通过。

新增实际 PG/MinIO 验证通过完整原 canonical 来源／context／scope／生成／映射／
脚本／RunPlan／recipe 链准备数据，只在原完整来源检查之后推进本 repository
的 SQL clock 表达式，不改 PG 时钟、confirmation 字节或旧许可。原代码红批
65992 使用两个阶段：第一条写入前与已 flush 审计／Outbox 后；日志
`output/fixture-grant-late-clock-red-postgres-20261013.log`，现已退出 1：
2 failed / 14 deselected / 324.53 秒。两个失败都在独立确认返回 completed、
而测试预期 failed 的断言处，实际复现了提交缺口，不是前置数据准备失败。
修复后 72683 检验这两个实际回滚阶段及原完整 recipe/grant 审阅／权限／历史
回归，日志 `output/fixture-grant-late-clock-current-postgres-20261013.log`；经原
句柄核实 live，尚不能计为实际 PG 修复全部通过。

父计划实际对照 89502 已完成普通样本的完整响应与原对象字节 hash 等价检查，
记录原算法 plans=2 / objects=628 / SQL=4394，新算法 plans=1 / objects=318 /
SQL=2231，unique objects=24。固定 exweb 的完整原响应及对象摘要同样等价，原
算法 plans=2 / objects=1040 / SQL=5906，新算法 plans=1 / objects=586 /
SQL=2987，unique objects=148；原 126 blob、725 代码成员完整核验未减少。
该批现已退出 1：2 failed / 14 deselected / 694.79 秒。两个失败都为最终来源
撤权时原应用抛出 `StaleSourceAccessScope`，而新测试错误预期 SourceAccessDenied；
最终保护没有返回数据，不是撤权被绕过。现在明确检查该精确 stale 异常，再
恢复原完整 read port，并检查新读取抛 SourceAccessDenied；不删除撤权测试或
放宽生产授权。76790 使用原相同数据完整复验，日志
`output/environment-binding-parent-exweb-final-acl-postgres-20261013.log`，仍 live。
没有整批通过前不能计为完整 actual 对照已通过；查询次数不是 p95 性能、目标
执行或完整安全门禁。安全诊断白名单也补入实际 StaleSourceAccessScope，消息
仍不记录，未登记的类型仍为 other。

带诊断原生批 29067 已退出 1：1 failed / 14 passed / 1748.51 秒，日志
`output/run-plan-fixture-handoff-owned-exweb-boundary-diagnostics-20261013.log`。
原 `grant_live_permission` 通过，`prepare_inputs` 完成后在 `prepare_binding`
抛出 HttpFixtureInvalid；不支持“许可到期导致这次失败”的断言。临时资源已由
原 runner 清理，不能猜测原异常消息。命令绑定现增加独立的固定观测边界，涵盖
原 canonical、实时许可、preparation、原派发防重、写入、binding、原 intent
核验、事实事件及当前权限；不减少任何原校验或记录异常正文／traceback。

新绑定故障／准备／许可／诊断／DDD 合并专项退出 0：316 passed / 7.42 秒，
日志 `output/fixture-binding-current-diagnostics-contracts-20261013.log`。
每个注入错误仍为同一异常，日志只含固定阶段、类型和耗时，不产生事实事件。
后续原生 89077 使用原完整 exweb、PG/MinIO/Temporal/owned Docker 链及最新
父对象复用和提交窗口校验，日志
`output/run-plan-fixture-handoff-owned-exweb-binding-phases-20261013.log`；
经句柄核实 live，实时输出固定阶段以便继续定位，不与仍 live 的完整 V1 批
84823 混淆。原 29067 已明确 terminal 后才启动该新诊断批，没有重发旧命令。

最新合并 clock／binding／parent／原许可／handler／DDD 边界批退出 0：
556 passed / 17.83 秒，日志
`output/fixture-clock-binding-parent-final-contracts-20261013.log`；集合与前批
重叠，不相加。本轮 Portal build/lint 均退出 0，日志
`output/fixture-clock-binding-portal-{build,lint}-20261013.log`，大 chunk 警告
仍存在。未运行本轮浏览器、E2E 或 smoke，不以静态契约替代这些门禁。

原固定 exweb HEAD 仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，原仓库
porcelain 为空。未修改业务 oracle、原源码、用例或义务。五用途包及消费者、
自动增量 DAG、真实覆盖到 release、Provider/gold、容量／DR／安全／性能／试点
和最新完整 V1 门禁仍未验收完成；目标保持 active。

## 环境父计划复用与原生失败边界诊断（2026-10-13）

上一轮仅解释当前数据关联，属于 no progress。本轮继续核验相同运行句柄，未因
观察耗时重启任务。29928 已退出 0：2 passed / 25 deselected / 328.93 秒，日志
`output/case-approvals-events-and-exweb-portal-20261013.log`。该专项消费当前三个
拒绝协调字段修正，验证实际 PG/MinIO 来源撤权及新事件授权，并将原固定 exweb
API 输出交给当前 Portal 校验器；不是浏览器渲染、真实业务 gold 或目标执行。
31315 已退出 1：1 failed / 26 passed / 886.45 秒，日志
`output/case-approvals-final-exweb-postgres-20261013.log`；失败为较早加载的拒绝
回执策略，不能把其余通过项当作最新完整门禁。最新完整准入批 25641 已退出 0：
27 passed / 999.23 秒，日志 `output/case-approvals-current-full-postgres-20261013.log`。
它覆盖本轮完整准入 API 及原 journal 回归、原固定 exweb 和 API→Portal 契约；
不是最新完整 V1、浏览器或目标执行门禁。

原生全链前次在 fixture setup 确认失败，原临时库已经清理；仅凭耗时不能推定
许可到期、权限变化或存储故障。本轮新增固定阶段/错误类别/耗时的应用层诊断，
覆盖权限、原命令、完整输入、绑定、最终授权和原 Temporal 投递；grant 的原
recipe/环境读取及实时许可检查另有独立阶段。日志不包含异常消息、traceback、
正文、对象地址、SQL 参数或凭据；异常和取消原样传播，不重写任何事实、延长
确认时限、授予执行权或重发未知效果。

同时确认环境检查旧算法先读取完整 RunPlan，再经构建绑定重复读取同一父计划。
`RunPlanBuildApplicationService.read_with_plan` 现在返回本次完整历史/归档校验后
的绑定和原父计划；公开 `read` 响应不变。环境应用服务消费该明确端口，仍核对
项目、原 plan/binding/image/manifest/target 摘要、当前状态和最终来源权限。
只有旧端口缺少该能力时保留原算法；能力存在但读取失败时不降级或换头。
没有跨请求缓存，构建和 source/archive 校验没有删减。

当前终态专项（集合重叠不相加）：

- 诊断首批 349 passed / 8 errors / 8.85 秒，错误均为新测试遗漏显式 `spec`
  fixture 依赖；保留 `output/fixture-boundary-diagnostics-contracts-20261013.log`。
  修正后的诊断/许可/任务/取消/DDD 合并批 357 passed / 9.06 秒，日志
  `output/fixture-boundary-diagnostics-contracts-current-20261013.log`。
- 新父对象契约先 22 failed / 2 passed / 1.51 秒，日志
  `output/environment-binding-parent-contracts-red-20261013.log`；实现后完整
  parent/build/environment/记录/诊断/DDD 合并批 391 passed / 9.34 秒，日志
  `output/environment-binding-parent-contracts-current-20261013.log`。
- 新父对象/诊断/DDD/handler 边界批 193 passed / 7.66 秒，日志
  `output/environment-fixture-current-boundaries-20261013.log`。它们为显式完整
  port specimens，不冒充实际 PG、原生性能或业务执行。

实际 PG/MinIO 对照批 34644 已退出 1：2 failed / 14 passed / 277.95 秒，日志
`output/environment-binding-parent-exweb-postgres-20261013.log`。两个新验证遗漏
`prepared_binding` 准备 helper，因 binding_preview / script_sent 尚未准备而失败，
未运行到父计划 READ ONLY 对照，不计为优化已验证。现明确依赖完整原构建准备，
并使用实际 schema 的零计数及原注册 source URI。中间批 78326 已退出 1：
14 passed / 2 errors / 113.11 秒，日志
`output/environment-binding-parent-exweb-current-postgres-20261013.log`；该 helper
不是 fixture，错误的参数注入仍使对照未执行。现明确调用原准备 helper，批次
99488 使用相同隔离 runner，仅选择两个新父计划对照测试（既有 journal 集合
已在前两批单独通过），日志
`output/environment-binding-parent-exweb-prepared-postgres-20261013.log`，经原句柄
核实仍 live。不改变原源码、用例、oracle、义务或业务预期。
原生 Docker/PG/MinIO/Temporal 带诊断全链为 29067，日志
`output/run-plan-fixture-handoff-owned-exweb-boundary-diagnostics-20261013.log`，
经原句柄核实仍 live。它在环境父计划复用之前加载，属于诊断基线，不是最新
优化后全链通过证据。原完整 V1 84823 仍 live，已打印失败，不另开替代任务。

本轮 Portal build/lint/i18n 均退出 0，日志为
`output/environment-parent-portal-{build,lint,i18n}-20261013.log`；build 的大 chunk
警告仍存在。不把这些静态门禁当作浏览器渲染、E2E/smoke 或性能验收。

五类正式用途包/消费者、自动增量 DAG、真实覆盖至 release、安全容量/DR、
完整 Provider/gold/校准、浏览器和真实试点继续按原 P0-P6 目标验收。
本轮只推进已定位的读取重复与失败可诊断性，不声明故障修复或完整目标完成。

## 独立用例准入及正式 automation 前置环节（2026-10-13）

上一轮数据关联答复只作说明，不是实现进展。本轮继续保持完整 P0-P6 目标，确认
映射审阅明确不等于用例已获准用于自动化。新增独立 case admission 的 domain、
application、PG 追加式两表、私有 MinIO 工件、canonical handler、资源权限策略、
只读 API 与 Portal 知识页入口；0121 不回填批准或改写原草稿/coverage。

批准固定原 context/scope/generation/mapping、完整 case/oracle/input 摘要；确认
使用 PG 时钟、当前 reviewer/source 权限和 cohort head CAS。撤回追加独立事实，
提交前再核验全部输入；同命令恢复在原输入已失效时仍只能返回原事实。历史及当前
读取核验完整审批链和全部私有归档，不把历史对象或 accepted mapping 当作当前
模型调用、执行、通过或业务覆盖许可。预览保留完整用例和义务，超预算拒绝。

初次实际 PG/MinIO 批次 `case-approvals-postgres-20261013.log` 已退出 1：
1 failed / 25 passed / 604.78 秒。失败不是角色绕过，而是新资源策略将 canonical
拒绝附加的三个运行时字段当作业务字段，导致本人拒绝回执也被隐藏。第一次修正
仅处理 denial marker，后续事件专项仍 1 failed / 26 deselected / 37.43 秒，说明
修正不完整。现在仅对已失败且结果为 authorization_denied 的原回执移除这三个
协调字段，仍核验完整来源；pending/completed 不能借 marker 绕过严格 DTO。

同时补齐该类事实的 SSE 消费/重放前授权：原事实、canonical 会话/Goal、patch、
查询键及来源权限重新核验。当前撤权只跳过不可访问的事实；损坏或核验服务失败
不能降级为空结果。这仅覆盖新增 case admission 事件，不声称其余事件族的完整
安全 cutover 已交付。

目前终态证据（重叠集合不相加）：

- 最新领域/应用/资源/事件/DDD 合并专项 188 passed / 5.96 秒，日志
  `output/case-approvals-final-contracts-with-events-20261013.log`。
- Portal 完整契约集 1486 passed / 20547.39 ms，日志
  `output/case-approvals-all-portal-contracts-20261013.log`；新增 15 项包含完整
  输入篡改、Unicode cohort 跨 Python/JS 一致性、取消读取、唯一 pending/confirm
  与固定回执回读。它们是明确 protocol specimens，不替代实际浏览器或业务 gold。
- Portal build/lint/i18n 退出 0，日志为 `case-approvals-{final-portal-build,
  portal-lint,portal-i18n}-20261013.log`；大 chunk 警告仍存在。

最终普通/固定 exweb PG/MinIO 批次使用原 handle 31315，日志
`output/case-approvals-final-exweb-postgres-20261013.log`；该进程在最终三个拒绝
字段修正及事件授权接入之前加载，现已退出 1，不能当作最新全部代码的门禁。
最新来源撤权/事件授权与固定 exweb API→Portal 跨运行时专项为 handle 29928，日志
`output/case-approvals-events-and-exweb-portal-20261013.log`，现已退出 0：
2 passed / 25 deselected / 328.93 秒。原 exweb 仓库无修改；专项保留 126 原 blob、725 原代码成员及原协议
用例/义务，不删除失败预期、不把独立准入算作目标业务通过。

原生 exweb 全链 51313 已退出 1：1 failed / 14 passed / 1667.22 秒，日志
`output/run-plan-fixture-handoff-owned-exweb-verified-parents-20261013.log`。仍失败
在 fixture setup 确认，不是已完成业务执行或闭环。完整 V1 handle 84823 在本轮
通过同 handle 确认 live，已经打印失败，未重启；它在新增准入之前加载。

正式五用途 ContextPack 及消费者、自动增量 DAG、真实业务覆盖至 release、
安全容量/DR、独立 gold/校准和真实试点继续是原完整目标。新增准入只是正式
automation 的必要前置，尚未接通其消费者；浏览器/E2E/smoke 和最新完整 V1
也不能用上述有限专项替代。没有完整验收依据，不标记目标完成。

## 固定映射父对象复用与原 exweb 继续验证（2026-10-13）

上一目标轮新增纯契约及实际 PG 红测试，并完成原归档受限采样，属于 progress；
之后的数据关联说明只作答复，不替代实现。本轮首先通过原 handle 确认终态：
76584 已退出 1，`output/run-plan-fixture-handoff-owned-exweb-scoped-locators-20261013.log`
为 1 failed / 14 passed / 6430.34 秒。失败在公共 fixture setup 确认返回 failed，
不是完整用例执行或业务覆盖通过；环境、静态定位、定义登记及许可签发已完成。
原日志未提供可独立核验的具体异常原因，不将到期推测写作已证实根因。

新增 `test_automation_mapping_parent_read.py` 在生产修改前为 21 failed；实际
`test_automation_mapping_parent_postgres.py` 的普通/分包、prepare/replay 四组合
为 4 failed / 16 deselected / 131.30 秒。它们确认映射读取已经核验完整生成父
对象，但 automation 编译随后又读取同一个父对象。现有映射服务新增内部
`read_with_result/resolve_with_result`，返回该次完整核验的视图与父对象；公开
`read/resolve` 仍只返回原视图。automation 仅复用该父对象，不接受外部传入，
旧只读端口保持兼容，异常不降级。

独立 generation prepare/replay、prepare 的第二轮完整编译、当前 scope/mapping
头和最终 ACL 全部保留。不存在跨请求缓存，不将历史读取变成生成或执行许可。
实际 PG/MinIO 四组合逐项比对完整输入和全部原对象字节 hash，事务强制 READ
ONLY；result read 每轮 2 -> 1，独立 generation 校验次数不减，SQL/对象读取
减少。父对象读完后实际撤回 qa_lead 的来源权限仍拒绝全部预览，计数仍为零。

本轮已完成的终态证据（重叠集合不相加）：

- 初次纯契约：44 passed / 0.54 秒，`output/automation-mapping-parent-unit-green-20261013.log`。
- 实际 PG/MinIO：20 passed / 309.66 秒，`output/automation-mapping-parent-postgres-green-20261013.log`；来源及模型内容为显式 protocol specimens，不是业务 gold。
- 固定 exweb 与最新父链 PG 对照：21 passed / 481.06 秒，`output/automation-mapping-parent-exweb-original-20261013.log`；全部 126 原 blob 一致，详见下述报告。
- API/历史读锁/完整 RunPlan 父链回归：28 passed / 1 skipped / 608.47 秒，`output/automation-mapping-parent-api-postgres-20261013.log`。未启用的固定 exweb 项另在显式来源批次执行，不将 skip 算作通过。
- 最新契约/边界合并组：564 passed / 7.20 秒，`output/automation-mapping-parent-final-contracts-20261013.log`，包括历史失败不降级、第二轮撤权和原 writer 锁回归。
- Portal build/lint/i18n 均退出 0，日志为 `output/automation-mapping-parent-portal-{build,lint,i18n}-20261013.log`；build 仍有大 chunk 警告，不以此声明性能门禁完成。

原 exweb recipe 在旧临时库清理前完成本轮 baseline：177839363 调用、recipe
累计 profiler 时间 30.581 秒、result 6 次及 ContextPack 9 次，完整响应 hash
仍为 `sha256:a30fa27506f47278ca079afc1afcce811827cd1d360c391151599252f47f9715`。
日志/报告为 `output/exweb-fixed-fixture-mapping-parent-baseline-20261013.{log,prof}`。
临时库随原失败任务清理，不伪造清理后对同库的新采样；不是 p95/容量验收。

固定 exweb 输入专项已完成相同原输入的 READ ONLY 前后比较，完整响应和全部
原对象字节一致，并逐 blob 核验原 126 文件。固定画像包含 725 个 exweb 代码
成员；该专项原四个用例、一个约束/四个义务均未删减，语义/模型内容仍为显式
protocol specimens，不与原生全链或独立业务 gold 混算。对照 SQL 2856 -> 1908，
对象 read 462 -> 308、result read 4 -> 2，独立 generation 检查仍两次。
报告为 `output/automation-mapping-parent-exweb-original-20261013.json`，明确
`target_execution_verified/full_quality_closure_verified=false`。原生全链也已用
当前父链实现新开隔离批次，日志为
`output/run-plan-fixture-handoff-owned-exweb-verified-parents-20261013.log`。
该验证将 setup 许可移到每个操作执行之前分别申请，不提前把后续许可消耗在
前一个串行任务；未延长 900 秒 TTL、重开失败命令、改原文件、缩减用例或改变
业务失败预期。写入本段时原生全链 51313 通过其原 handle 确认 live，未有终态；
原完整 V1 84823 同样仍 live，已经打印失败，不能称为绿色。
该 V1 批次在本轮父链实现之前加载，不是最新代码的完整验证；等待原终态后
仍需分析失败并执行当前实现的完整门禁，不因观察超时重启原任务。

五类正式 ContextPack、自动增量 DAG、真实业务覆盖至 release、安全容量/DR、
独立 gold/校准和真实试点仍是完整 P0-P6 目标。本轮父链复用和有限专项通过
不替代其中任何退出条件。

## 固定父链只读修复与脚本父对象复用（2026-10-13）

前一目标轮的受限诊断新增了测试及实际 PG 证据，属于 progress：原历史 recipe
读取在 mapping repository 的 `SELECT FOR UPDATE` 上触发 SQLSTATE 25006，改变了
下一步修复方向。用户随后提出的数据关联问题只作代码说明，不代替目标实现。
本轮修复普通及分包映射的历史读取，`historical` 与写入锁独立；`get` 明确不加
写锁，但使用 `populate_existing` 重新核验原 canonical actor、request 和项目。
`record/committed` 包括失败终态后的已提交重放继续默认加锁，原 head CAS、确认、
角色、Outbox 和不可变历史校验不删减。

只读诊断只接受已有本地 `nasus_test_*` PG 及原私有 `nasus-test-*` bucket。
数据库连接强制 READ ONLY，S3 client 拒绝所有修改和未知 operation；使用原 recipe
actor 的实时权限，不发送模型或目标请求，不输出 SQL 参数、正文或凭据。原两次
0.233/0.250 秒诊断均失败，不是完整读取或性能基线。修复后原 exweb recipe 的
完整受限读取成功，profiler 显示 RunPlan 在同一操作中完整展开相同脚本两次。

脚本审阅服务现在提供内部 `read_with_script`，返回该次读取已经核验的完整父
对象；普通 `read` 的公开响应不变。RunPlan 编译和原命令输入授权消费该对象，
仍核对全部选定 pins、完整历史、当前输入/审阅头、来源范围及最终 ACL。
旧 read-only port 保留原两次读取兼容，不在异常时降级或返回部分内容。没有
跨请求父对象缓存，不以历史父链授予目标健康、fixture 或执行许可。

当前终态证据（选择集重叠，不累加）：

- SQL 形状专项先 **8 failed / 4 passed / 0.64 秒**，增加 staged part 后
  **12 failed / 6 passed / 0.74 秒**；保留 `mapping-read-locks-unit*-red` 日志。
  只读诊断保护及完整 SQL 形状专项 **37 passed / 0.62 秒**，
  `output/mapping-read-locks-unit-green-20261013.log`。
- 实际隔离 PG/MinIO 普通与分包历史读取红测 **2 failed / 56.57 秒**，
  `output/mapping-read-locks-postgres-red-20261013.log`，实际服务器拒绝只读
  `FOR UPDATE`。修复后的普通/分包/staged part、identity-map 并发修改和
  writer lock 检查加既有 journal 回归 **20 passed / 352.74 秒**，
  `output/mapping-read-locks-postgres-green-20261013.log`。
- 父对象复用新专项先 **25 failed / 1.01 秒**，
  `output/run-plan-review-parent-unit-red-20261013.log`；应用、原审阅/RunPlan/
  scope/receipt 与只读保护合并 **177 passed / 4.03 秒**，
  `output/run-plan-review-parent-unit-green-20261013.log`。均为明确 port specimens，
  不充当实际目标业务证据。
- 最新相关 DDD/RunPlan 边界 **140 passed / 2.10 秒**，
  `output/run-plan-review-parent-boundaries-20261013.log`。
- 父链首批隔离 PG/MinIO 对照、撤权及只读/journal 合并 **21 passed /
  462.90 秒**，`output/run-plan-review-parent-postgres-20261013.log`。
  首批启动后将对照扩展为完整编译 tuple，因此另外用最终代码重跑该项：
  **1 passed / 14 deselected / 144.02 秒**，
  `output/run-plan-review-complete-parent-postgres-20261013.log`。实际 READ ONLY
  PG 下完整 plan/draft/review 不变，原对象集合及每份原字节 hash 相同；脚本
  read 2 -> 1，SQL/对象读取减少。父对象核验后实际撤回来源权限仍拒绝，
  原脚本模型调用仍只有一次，没有派发目标或增加已执行覆盖。来源/模型
  transport 是明确 protocol specimens，不当作 exweb 业务 gold。
- writer/CAS/确认窗口、取消、Outbox 回滚专项 **18 passed / 40 deselected /
  470.42 秒**，`output/mapping-read-locks-writer-regression-20261013.log`。
  实际隔离 PG 验证没有因 read lock 修复弱化正式写入及重放边界。
- 明确 application review port 后的最终契约/边界合并 **317 passed /
  6.08 秒**，`output/run-plan-review-parent-final-contracts-20261013.log`。
  包含前述 177 与 140，选择集不累加；`git diff --check` 退出 0。

原同一 exweb recipe 的受限 baseline/reused profiler 均退出 0，完整响应 hash
同为 `sha256:a30fa27506f47278ca079afc1afcce811827cd1d360c391151599252f47f9715`。
脚本 read **2 -> 1**、ContextPack read **18 -> 9**；recipe read 累计 profiler
时间 **61.884 -> 30.196 秒**，总调用 **352714193 -> 177839357**。报告为
`output/exweb-fixed-fixture-read-parent-{baseline,reused}-20261013.{prof,log}`。
这是单次本机、已有归档、并行负载及 profiler 开销下的观察，不是 p95、容量或
Linux 性能门禁，也不能将更早失败的诊断当 baseline。实际 PG/MinIO 对照及
并发专项现已终态，证据与样本边界见上文；不把单次 profile 当完整性能验收。

原 owned exweb 76584 与完整 V1 84823 也经原 handle 重新确认 live，没有重启；
二者早于这些修复加载，不证明本轮最新实现全绿。原仓库 Git HEAD 仍为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain 为空。后续须继续其余
重复父链、安全/恢复与完整性能验证、真实业务派发，以及五用途、自动增量、
正式覆盖/放行、独立 gold、容量/DR/试点和最新 V1 门禁；完整 P0-P6 范围不变。
最新只读 PG 观察原 exweb 项目已有四份 fixture register/authorize completed，
尚无 case outcome。V1 在约 40% 的日志出现 `F`，仍无终态总数；不能声明通过。

## 原命令末尾核验与 exweb 推进（2026-10-13）

上一轮只说明当前数据关联，没有新增实现；本轮重新轮询原 handle，再按真实
读取/派发边界补齐确认窗口竞态，不缩减完整 P0-P6 目标。原完整 V1 84823 和
owned exweb 76584 仍经原 handle 确认 live，不因观察等待而重启。

case input producer 在完整 source/build/environment/locator/fixture/health 核验
后重新读取原 canonical 命令及 PG clock，核验原 actor、selection、command
digest 和原 15 分钟确认窗。过期、取消、改请求、续写确认、坏快照均拒绝返回
准备结果；不延长 TTL，不产生 work/claim，不将 prepared input 变成派发许可。
历史仍不要求旧确认新鲜或目标存活，但末尾必须保持原命令摘要。PG 写入的既有
租约/epoch/取消防线不变；此前缺口是准备结果可过期，不声称已有未授权派发。

实际 PG 专项另复现读取端口的四项竞态：最后一次 `require_current` 之后仍
返回此前 command/time；取消、缺失、改项目和 clock 顺序均红。端口现在在最后
授权/账号检查后重新查询 `populate_existing` command、验证原 preparation，
最后采样 PG clock。没有缓存实时授权或允许变更原认领历史。

本轮终态（选择集重叠，不累加）：

- producer 初次红测 **34 failed / 5.22 秒**，
  `output/run-plan-case-command-fence-red-20261013.log`；异常快照补强后的
  producer/read-scope 专项 **51 passed / 7.26 秒**，
  `output/run-plan-case-command-fence-focused-20261013.log`。为明确协议样本，
  不替代真实数据库或业务目标。
- 首次扩大选择集因默认 SQLite 启动，**3 failed / 114 passed / 48.43 秒**，
  `output/run-plan-case-command-fence-green-20261013.log`；三项既有 journal
  检查拒绝 SQLite。使用隔离 PG/MinIO 入口重跑已退出 0：**147 passed /
  245.42 秒**，`output/run-plan-case-command-fence-pg-minio-20261013.log`。
  该批已加载 producer 修复，但早于后续 command reader 修复。
- actual PG reader 红测 **4 failed / 1.20 秒**，
  `output/run-plan-case-command-reader-pg-red-20261013.log`；最新 reader、producer、
  真实 PG clock/取消/撤权及 read-scope 选择集 **63 passed / 20.75 秒**，
  `output/run-plan-case-command-reader-pg-green-20261013.log`。确认跨窗由实际
  `clock_timestamp()` 和 `pg_sleep(6)` 观测，不替换服务器时钟、不修改 TTL。
  来源及目标仍是协议样本，不当作 exweb 原生副作用证明。
  最新 reader/producer 与既有实际 PG/MinIO journal/执行及协议回归的合并批
  13876 也已退出 0：**151 passed / 256.84 秒**，
  `output/run-plan-case-command-fences-combined-pg-minio-20261013.log`，包含前述
  新专项；各选择集不累加。
- producer 修复后的相关 DDD/RunPlan 边界 **140 passed / 2.13 秒**，
  `output/run-plan-case-command-fence-boundaries-20261013.log`。最新 reader 边界
  重跑也已退出 0：**140 passed / 1.97 秒**，
  `output/run-plan-case-command-reader-boundaries-20261013.log`，不累加旧批数量。
- 最新 Portal contracts **1471 passed / 22584.469458 ms**，
  `output/run-plan-case-command-fences-portal-contracts-20261013.log`；Portal 边界
  **25 passed / 0.38 秒**，`output/run-plan-case-command-fences-portal-boundaries-20261013.log`。
  build、lint、i18n 均退出 0，对应同名前缀的 `portal-build`、`portal-lint` 和
  `i18n` 日志；大 chunk 告警保留。隔离 PG/MinIO smoke 批 78452 已退出 0、
  `smoke: success`，日志 `output/run-plan-case-command-fences-smoke-pg-minio-20261013.log`。
  验证 Build/项目/来源/画像 Agent/结构预算与候选/索引/查询/质量面板，Runner/model
  保持 smoke 明确的协议模式，不是固定 exweb 原生业务闭环或完整 V1 通过证据。

exweb 76584 对应的隔离 PG 原环境和定位命令均已 completed，保存的定位摘要
为 **4/4 static_match**；fixture register/authorize 已开始，原七用例/126 文件、
业务断言和预期失败未修改。该批仍未终态，尚不证明业务派发、恢复、coverage 或
release；且进程加载早于本轮命令末尾核验修复。原 Git HEAD 再核验为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain 为空。

修正浏览器模板后的独立批 42095 已退出 0：**4 passed / 12.7 分钟**，
`output/run-plan-v2-scoped-locator-exweb-browser-template-fixed-20261013.log`；
覆盖 v1/light/en、v2/dark/zh、v3/light/zh、v3/dark/en。实际隔离 PG/MinIO 和
固定 exweb 来源与显式 UI transport specimens 分开，不能当原生目标业务覆盖。
旧 36178 失败仍保留。完整五用途、自动增量、独立 unknown 恢复、正式覆盖/
放行、容量/性能/试点与最新完整 V1 全绿仍未完成。

## exweb 定位阻断修复与新版报告（2026-10-13）

原 owned exweb 批 25144 已退出 1：**1 failed / 14 passed / 2143.76 秒**，
`output/run-plan-fixture-handoff-owned-exweb-temporal-20261013.log`。原 126 文件的
native build、原 JAR 部署和真实环境归档已完成；定位摘要为 0/4，断言失败在
fixture 许可/setup、业务派发和 Temporal 执行之前，不能当作全链成功。
环境确认耗时 720026.173 ms、定位确认 375577.006 ms，性能门禁未达成。

完整原 AST 保留 exweb 六条有媒体类型条件的 unresolved 路由。旧 v1 策略将
任意条件传播为全局 unknown，阻断了原会话查询。新 v3 检查使用显式 v2 inventory/
rule/report/policy；同字节 AST 只证明可能的 method/path 范围，不批准条件。
已证明不相关的条件不再阻断，同路径、动态/正则、解析失败、隐式 HEAD/OPTIONS
和可能命中字面值的 fixture 变量仍保守拒绝。旧报告按原规则重放，不重写历史。
实现与防腐/权威边界见 [HTTP 定位](./http-locator-evidence.md)。

完整 case input producer 同时打开 operation-local 只读 session，原 plan/build/
environment/locator/全部 fixture 在一次同步操作内复用固定画像元数据；每个
prepare/fence/history 独立新读，ACL/批准头/健康/cleanup/lease 不缓存。九项专项
已通过，`output/run-plan-case-read-scope-20261013.log`；这是正确性回归，不是 p95。

本轮终态证据（选择集重叠，不累加）：

- 后端定位红测 **6 failed / 6 passed**，
  `output/exweb-locator-uncertainty-red-20261013.log`；原 126 文件和七完整用例保留。
  修复及格式/历史/权限/读 scope 扩展回归 **113 passed / 6.82 秒**，
  `output/exweb-locator-uncertainty-expanded-20261013.log`。无数据库 I/O，不以
  PostgreSQL dialect 当持久化证明；固定 exweb 源码实际从原 Git blobs 读取。
- Portal 独立 Python 报告红测 **8 failed / 36 passed**，
  `output/exweb-locator-portal-v2-red-20261013.log`。新版报告、归档与 Unicode
  code-point 排序专项 **73 passed / 12336.152041 ms**，
  `output/exweb-locator-portal-v2-archive-20261013.log`；全部 Portal contracts
  **1469 passed / 19927.100208 ms**，
  `output/exweb-locator-v2-all-portal-contracts-20261013.log`，已包含专项，不另加。
  补充既有 v3 计划的原 v1 报告重放后，全量 **1470 passed / 22736.282875 ms**，
  `output/exweb-locator-v2-all-portal-contracts-legacy-20261013.log`。
  浏览器夹具新增 Python 字符串的初次转义错误已被实际浏览器揭示；已修正，并新增
  直接执行其 TypeScript 模板中原 Python 的编译检查。补强定位/归档专项终态
  **75 passed / 18000.189416 ms**，
  `output/exweb-locator-portal-v2-browser-template-20261013.log`，不是浏览器通过证据。
  纳入该编译检查的最新全量 Portal contracts **1471 passed / 22356.712834 ms**，
  `output/exweb-locator-v2-all-portal-contracts-template-20261013.log`；与前述批次重叠，
  不累加为独立项目用例数量。
- Portal build/lint 均退出 0，`output/exweb-locator-v2-portal-build-20261013.log`
  和 `output/exweb-locator-v2-portal-lint-20261013.log`；大 chunk 告警未隐藏。
  相关 DDD/Portal/locator/RunPlan/fixture 边界 **188 passed / 2.09 秒**，
  `output/exweb-locator-v2-boundaries-20261013.log`。

76584 的独立 owned exweb/PG/MinIO/Temporal 重跑已启动并经同 handle 确认 live，
日志 `output/run-plan-fixture-handoff-owned-exweb-scoped-locators-20261013.log`，
尚无终态。原仓、需求/用例/预期失败及业务分母不修改；模型/业务 oracle 仍是
明确协议样本，不是独立 gold。36178 的原新版浏览器四场景现已退出 1：
**4 failed**，日志 `output/run-plan-v2-scoped-locator-exweb-browser-20261013.log`；
均为已修正的夹具字符串转义 SyntaxError，不视为生产或业务通过。等待原 handle
终态后才启动独立 42095，新四场景已 **4 passed / 12.7 分钟**，日志
`output/run-plan-v2-scoped-locator-exweb-browser-template-fixed-20261013.log`。
真实隔离 PG/MinIO 来源与显式 UI transport specimens 分开记录，不能把历史八项
成功代替新报告或将新四项成功当原生目标执行。
原完整 V1 84823 仍经 handle 确认 live，无终态且不覆盖本轮新代码。完整 P0-P6、
五用途、自动增量、unknown 独立恢复、正式覆盖/放行及性能/试点继续待交付。

## 公共 v3、原始 setup handoff 与生命周期实证（2026-10-13）

上一轮仅核对并说明当前数据关系，没有新增实现。本轮重新轮询原运行 handle，
不因等待较久而重启。以下记录覆盖此前公共 v3 和主 handoff 接线，并补充当前
生命周期／真实 Temporal 检查；完整 P0-P6 目标、独立 gold、五用途及正式覆盖／
放行仍不缩减。

公共模型入口显式选择 HTTP v3，生成完整 `use_fixture_binding` action，独立审阅
保留所有原 action/step/oracle，RunPlan 与 build 编译使用新显式 v3。旧请求、
工件、分母和摘要不补空字段或重算。真实隔离 PG/MinIO 扩展选择集已终态：
**523 passed / 241.06 秒**，`output/http-fixture-v3-public-expanded-pg-minio-20261013.log`。
它不等于固定 exweb 的新公共业务执行。后者原批 21681 已退出 1：**1 failed /
14 passed / 885.60 秒**，`output/http-fixture-v3-public-pg-minio-20261013.log`；
确认为 RunPlan 私有存储仍只允许 v1/v2，已为新 v3 增加显式存储版本。固定 exweb
原专项 43910 已退出 1：**1 failed / 14 passed / 1049.98 秒**，日志
`output/http-fixture-v3-public-pg-minio-storage-fixed-20261013.log`。v3 草稿／独立审阅／
RunPlan 保存和完整回读已成功，测试计数辅助函数错误地假定 ToolInvocation 有
project_id。改为通过原项目会话统计，保留全部无副作用断言；83360 是独立重跑，
日志 `output/http-fixture-v3-public-pg-minio-tool-count-fixed-20261013.log`，现已退出 0：
**15 passed / 1253.47 秒**。实际固定 exweb 来源及公共保存链通过，不含真实目标业务执行。

主 input producer 新增 `OriginalCaseFixtureWire`，通过原 canonical setup 历史、
全部 cleanup slots、ACL 和物理 verifier 读取确切 bytes。旧 proof 九字段不变。
新 prepared 类型包含完整原用例的 fixture inputs，新 scope/work/native archive/
state/observation 显式版本绑定完整有序 pins，current/history 均重构核验。PG
scope 不保存响应正文或资源值，私有 MinIO archive 保存原 setup 和业务原 wire。
仅有 v3 template 仍在 acquire/claim 前拒绝；独立确认、lease/epoch、unknown
不重发和原 formal coverage 零计数规则保留。细节见
[Fixture 业务资源绑定](./run-plan-fixture-bindings.md)。

接线后的终态结果（选择集重叠，不累加）：

- 原 208 项加新 16 项 Python 契约 **224 passed / 52.31 秒**，
  `output/run-plan-fixture-handoff-contracts-20261013.log`；这是无数据库 I/O 的
  PostgreSQL dialect 纯协议检查，不当作实际持久化。
- 隔离 PG/MinIO 的既有 journal、接线契约与边界选择集 **263 passed /
  211.39 秒**，`output/run-plan-fixture-handoff-pg-minio-20261013.log`；其中新
  v3 transport/setup 是明确协议替身，尚不证明新 scope 的真实 PG 重放。
- Portal 完整 contracts **1446 passed / 23785.878542 ms**，
  `output/run-plan-fixture-handoff-all-portal-contracts-final-20261013.log`；新历史
  scope/state/observation pins 由共享验证器核验。独立 case 文件 78 项已包含在
  1446 中，不另加。build/lint 均退出 0，原大 chunk 告警未隐藏。
- 既有 scripts/RunPlan E2E **4 passed / 3.0 分钟**，
  `output/run-plan-fixture-handoff-existing-e2e-20261013.log`；覆盖旧 v1/v2
  browser protocol specimens，不当作公共 v3 或 actual owned target。
- smoke 终态 `smoke: success`，`output/run-plan-fixture-handoff-smoke-20261013.log`。
  DDD 边界 **41 passed / 0.47 秒**，
  `output/run-plan-fixture-handoff-boundaries-20261013.log`。

新 v3 scope/work/archive 的独立真实 PG/MinIO 批 89515 已退出 1：**1 failed /
14 passed / 401.19 秒**，`output/run-plan-fixture-handoff-new-pg-minio-20261013.log`。
原测试计划默认声明 19876，但原 setup 固定受控 namespace origin 8080，被原字节
校验正确拒绝；没有放宽生产校验或修改已保存工件。新测试计划在保存前显式声明
local/8080，79989 已退出 0：**15 passed / 385.74 秒**，日志
`output/run-plan-fixture-handoff-new-pg-minio-fixed-origin-20261013.log`。实际 PG 保存并
JSON 重建完整 v2 work/scope，MinIO 保存／回放整个原 setup 与业务 wire；新会话
只读恢复、原 Outbox 失败的 unknown 不重发保持通过。目标/model/setup
仍是明确协议替身，不将 canonical 父链和真实存储等同 actual exweb 行为。

新增共享 job fixture 工厂复用原生命周期，而非复制一个 v3 调度器。新专项检查
完整原生字节到 canonical lifecycle 的终态回读、claim 后断线不重发、cleanup 后
历史不探测健康、资源／pin 损坏不完成、撤权及 public receipt 不暴露资源或夸大
覆盖。13232 已退出 1：**3 failed / 39 passed / 245.13 秒**，测试将 outcomes list
误用为 dict；11717 修正后重跑又退出 1：**3 failed / 41 passed / 288.81 秒**，测试
继续误用 private archive URL 而非其 hash 索引。两批原日志均保留。修正后的损坏
专项 94715 已退出 0：**3 passed / 10 deselected / 36.78 秒**，日志
`output/run-plan-fixture-handoff-corruption-fixed-20261013.log`。新完整生命周期／
真实 Temporal 重跑 5559 已退出 0：**44 passed / 301.86 秒**，日志
`output/run-plan-fixture-handoff-lifecycle-archive-key-fixed-20261013.log`。覆盖完整原
生命周期及两项真实 Workflow/Activity 重试与取消；这些选择集重叠，不累计为
独立项目用例数，也不作为真实 exweb 或 PG 进程崩溃恢复证明。

本轮核查实际 composition 发现生产接线遗漏：应用层会传 fixture_inputs，但
`ConfiguredRunPlanCaseWorker` 的 execute/read 仍是旧签名，直接核心 worker 的
测试没有覆盖这个入口。现已将完整输入传给两条实际配置边界，旧调用不增加空
字段，历史读取不创建 Runner。新专项 76119 已退出 0：**5 passed / 14.19 秒**，
`output/run-plan-fixture-handoff-configured-runtime-20261013.log`。包含完整七用例的
实际适配器转发／回读、原失败 oracle、缺失／伪造字节 pre-claim 拒绝及旧签名
兼容；target/journal 为明确协议替身。扩展回归 66156 已退出 0：**311 passed /
66.24 秒**，日志 `output/run-plan-fixture-handoff-runtime-regression-20261013.log`，
覆盖原 execution/input/persistence/archive、完整 handoff、实际配置适配器和 DDD
边界，选择集重叠，不与上述 5／15 项累加成独立项目数量。

接线专项补强了历史读取约束：原执行完成后清空配置中的 Node executable，并把
Runner 构造替换为显式拒绝；历史完整回读仍相同。补强批已终态 **5 passed /
14.50 秒**，日志 `output/run-plan-fixture-handoff-configured-runtime-history-20261013.log`。
这五项包含原接线专项，不相加为十项。

新增公共 v3 浏览器场景保留原 v1/light/en 与 v2/dark/zh，额外增加 v3/light/zh
及 v3/dark/en。模型返回的完整资源 import action 与原 oracle 分开，独立审阅
逐 action/oracle 保持同一输入，RunPlan 保存和刷新保持显式 v3 而不降级。新场景
使用真实隔离 PG/MinIO 的原来源／发布／context/scope，以及明确的 model/script/
review/plan/environment browser transport specimens；不作为目标执行证明。首次
启动因手写测试连接的密码不匹配退出 1，日志
`output/run-plan-public-v3-exweb-browser-20261013.log` 保留。改为读取原共享私有运行
环境后，29752 使用独立 8099/4189 端口、原固定 exweb cache、随机 test DB/bucket
运行全部八场景，日志 `output/run-plan-public-v3-exweb-browser-runtime-20261013.log`。
现已退出 0：**8 passed / 20.3 分钟**，包含四个 scripts 与四个 RunPlan 场景。
这是当批真实来源/存储和 UI transport 检查，不代表实际目标或本轮新定位策略。
Portal build/lint 各自已退出 0，日志
`output/run-plan-public-v3-portal-build-20261013.log` 和
`output/run-plan-public-v3-portal-lint-20261013.log`；大 chunk 告警保持可见。

新增 opt-in 的固定 exweb 公共 v3 全链测试，使用独立账号／审阅、原 126 文件的
离线 native build、真实私有 namespace 的 PG/Redis/原 jar、原环境／locator／recipe／
grant／setup command，以及实际 PG/MinIO producer、Configured Worker 和两个真实
Temporal Workflow/Activity。模型/业务 oracle 是显式协议样本，没有外部模型、
独立业务 gold 或正式 coverage authority。25144 已启动，日志
`output/run-plan-fixture-handoff-owned-exweb-temporal-20261013.log`；现已退出 1，
定位前后的准确失败点与新重跑见本页最新段落，不能以测试定义、迁移日志或旧
私有 probe 代替通过证据。每批只清理自己拥有的数据库、
bucket、工作队列与 Docker 资源，不改示例仓、历史 case/oracle 或业务分母。

真实现有 Temporal 服务的 19833 已退出 0：**2 passed / 47.05 秒**，
`output/run-plan-fixture-handoff-real-temporal-20261013.log`。实际 Worker 执行生产
Workflow/Activity、完整七 case 的 Node/物理 verifier handoff；注入完整 archive 后
终态 ACK 失败，实际 Activity 重试只回读原输出、不新增 claim/request，终态同 ID
不重开，真实 history replay 通过。另验证准备线程中的实际取消，等待 guard 退出，
无资源请求或 case claim。source/setup/journal/target 是明确内存协议替身，数据库
未连接；不把这两项当作 PG crash recovery、原目标 Docker 或 exweb 业务 gold。

原完整 V1 84823 仍经 handle 确认 live，后端回归尚无终态；它在本批接线前收集，不能
证明本轮新文件，也没有最新全绿终态。已有 PG/MinIO/Temporal/UI 容器保持运行，
没有启动开发前后端、应用开发迁移、改用 SQLite 或调用外部模型。固定 exweb
再次核验 HEAD `fe5827f6b76f77ef34918d8b452ee823142332dc`、porcelain 空，原仓库/
gold/需求/用例/预期失败没有修改。仍需新版定位浏览器、实际 owned exweb 的
Tool/PG/MinIO/Temporal 全链、独立 unknown 处置、formal coverage/release，以及全部
P0-P6 其余退出条件。

## Fixture 捕获输入与私有原生绑定协议（2026-10-13）

上一轮目标开发新增完整捕获投影及测试，属于实现进展；其后数据关系说明没有
新增代码。本轮确认扩展捕获回归 34564 已退出 0：**459 passed / 112.39 秒**，
`output/run-plan-fixture-capture-regression-final-20261013.log`。包含前一批 425 和
新增 34 项，不相加为另一组独立测试。最初两个测试替身错误及物理 verifier
提前拒绝的测试断言位置已经修正，34 项专项及最终 459 项均有终态。

捕获投影固定每个原用例、原 setup/history、完整 parent/target/environment/manifest、
原 wire 和 response/value hash；输入 producer 与 current 重构开始保留并比较
整个不可变集合。没有替换旧脚本路径或把捕获值变成 oracle。详细边界见
[Fixture 业务资源绑定](./run-plan-fixture-bindings.md)。

新增私有 HTTP v3、独立 `FixtureBoundHttpCommand`、显式 import action 和完整 source
request/result bytes。Python/Node 都从原 setup 响应物理重取资源值并校验全部 source
steps/requests/captures/oracles，业务回执绑定 input/capsule/import、declared/resolved
路径及原请求摘要。公共 Runner endpoint 拒绝新协议，私有 Worker/CLI 核对原环境、
target artifact、inventory 和 operator policy。旧 command archive 不增加空字段，
v1/v2 字段和摘要保持不变。协议不授予来源、执行、目标或业务覆盖 authority。

已终态验证（选择集重叠，不累加为项目独立用例数）：

- 原 v1/v2 Runner 选择集 **73 passed / 2309.21025 ms**，
  `output/http-fixture-v3-legacy-runner-20261013.log`。
- 原 Python 协议、捕获和 DDD 选择集 **293 passed / 5.37 秒**，
  `output/http-fixture-v3-legacy-python-20261013.log`。
- 初始 v3 Node 专项 **20 passed / 56.510584 ms**，
  `output/http-fixture-v3-native-runner-20261013.log`；包含真实本地 HTTP 的独立 setup
  和业务请求，不是 registry-owned Docker 目标或 exweb gold。
- 初次跨语言批退出 1：**18 failed / 2 passed / 2.66 秒**，
  `output/http-fixture-v3-cross-language-20261013.log`。确认原断言解析器把协议
  DTO 整数也转成 Decimal，导致合法输入拒绝及测试重算失败；已分开协议整数
  与 oracle 精确数字语义。修正后 **20 passed / 2.89 秒**，
  `output/http-fixture-v3-cross-language-final-20261013.log`。business transport 与
  setup 历史为明确替身，实际调用 Node executor 与物理 Python verifier。
- 最新全部 Runner **155 passed / 2374.896209 ms**，
  `output/http-fixture-v3-all-runner-verified-20261013.log`。新增动态 ID、原预期
  不插值、超限整包拒绝与公共 endpoint 拒绝；本地目标和子服务均由测试清理。

最新扩展 Python/DDD 25876 已退出 0：**763 passed / 120.54 秒**，
`output/http-fixture-v3-expanded-python-final-20261013.log`。包含上述契约、原业务
执行/任务与 fixture archive/history，以及四项私有 Worker target epoch 拒绝。

继续补强 source setup 的结构约束：POST 后立即捕获、capture 只能来自 POST、
每个 setup request 必须有 status oracle；与原 fixture manifest 的约束保持一致。
增加重算 request/result/capsule 摘要但 setup 断言仍被实际响应否定的负向测试。
最终 Runner 2887 退出 0：**156 passed / 2407.811833 ms**，
`output/http-fixture-v3-all-runner-final-guarded-20261013.log`。对应完整同一 Python
扩展选择集 71599 退出 0：**764 passed / 119.30 秒**，
`output/http-fixture-v3-expanded-python-final-guarded-20261013.log`。包含最终 25 项跨语言/
私有 Worker/旧 shape 专项；此前 763 和当前 764 是重叠重跑，不累加。

真实隔离 PG/MinIO 19063 退出 0：**14 passed / 169.69 秒**，
`output/http-fixture-v3-pg-minio-regression-20261013.log`。完整 0001-0120 迁移、原父链、
物理归档、旧 journal 并发/撤权/Outbox/unknown 回归保持通过；资源由隔离 runner
清理，没有应用开发迁移或改用 SQLite。该批只回归既有 archive/journal 边界，
不当作新公共 v3、实际 owned Docker 目标或 exweb 业务执行证明。

Portal build / lint / 全 contracts 均退出 0，日志为
`output/http-fixture-v3-portal-build-20261013.log`、
`output/http-fixture-v3-portal-lint-20261013.log`、
`output/http-fixture-v3-portal-contracts-20261013.log`；contracts **1412 passed / 11611.99325 ms**。
前端未修改，主 chunk 仍为 1,331.57 kB，500 kB 告警未隐藏。这不是实际服务 E2E 或新 v3 UI 验收。
Python 编译、tracked diff --check 均通过；新文件 no-index --check 没有空白错误输出，
新文件差异的正常 exit 1 不误报为检查失败或 exit 0。

原完整 V1 84823 仍确认 live，在后端阶段；它启动于捕获/v3 修改之前，不能
声称覆盖本轮代码，也没有最新全绿证据。最新依赖检查只见现有 PostgreSQL、MinIO、
Temporal/UI 容器，没有启动开发前后端、使用 SQLite 或调用外部模型。
固定 exweb 再核验 HEAD fe5827f6b76f77ef34918d8b452ee823142332dc、porcelain 空；
示例仓、gold、业务分母和预期失败未修改。

完整 P0-P6 保持 active。当前新协议还没有接入公共脚本生成、独立审阅、RunPlan、
完整字节 handoff 和持久恢复；实际 exweb/Temporal、正式 coverage/release、五用途、
旧链切换、独立 gold、安全、容量/性能、DR 和试点均未因上述底座完成而缩小。

## RunPlan 真实 PG 事务边界修复（2026-10-13）

上一轮仅说明数据关联，没有推进实现。本轮确认 Docker 已恢复，现有 PostgreSQL、
MinIO、Temporal 容器就绪；仅使用隔离测试数据库和私有测试 bucket，没有启动
开发前后端、应用开发迁移、使用 SQLite 或执行外部模型/实际 exweb 目标。

新增 `scripts/test-run-plan-cases-postgres.sh`，复用隔离 runner 完整执行 0001-0120
迁移。此前底座专项终态为 **13 passed / 1.58 秒**，日志
`output/run-plan-case-actual-postgres-20261013.log`；测试 bucket 创建与清理本身
不证明业务 case 归档已读写，不能扩大其验证范围。

新增完整父链的真实 PG/MinIO case 集成专项，原来源、上下文、生成、独立映射、
脚本审阅与 RunPlan 经既有 canonical 入口归档，不删外键或伪造父表。case command
使用明确的原认领 journal 样本，模型/Runner transport 使用协议替身，不代表公共
native build/environment/fixture 授权或 exweb 业务 gold。各故障场景有独立命令、
run、lease 和归档作用域，只复用已完整核验的不可变父计划。

真实复现批 23601 退出 1：**2 failed / 24 deselected / 426.93 秒**，
`output/run-plan-case-pg-reproduction-20261013.log`。分别确认工作回调回入同项目
事务触发 PG advisory lock timeout，以及 flush 后撤销来源仍被提交的缺口。
已分离外层工作租约检查与事务内 ancestry guard，并在 acquire/renew/claim/outcome
flush 后复核原 live fence；账号与角色强制读取当前 PG 值。并发、未知不重发、
身份缓存后的撤权、Outbox 回滚、不可变事实和物理 MinIO 损坏进入同一专项。

非重入对照测试修正了初版替身把 journal 内部合法调用也视为递归的错误，旧模式
明确失败、新模式通过。扩大离线契约/DDD 重跑 38979 退出 0：
**425 passed / 69.85 秒**，`output/run-plan-case-transaction-unit-final-20261013.log`。
真实修复后 PG/MinIO 批 93350 退出 0：**14 passed / 185.58 秒**，
`output/run-plan-case-pg-minio-final-20261013.log`。其中集成测试验证完整 case
原生 wire 样本的物理 MinIO 写入/重读、PG 不可变触发器和活租约防抢占、未知结果
保留完整分母且不重发、并发唯一 work/owner，以及三个写阶段的来源检查撤权、
身份缓存后禁用账号和 Outbox 失败的真实事务回滚。底座 13 项包含在本次 14 项内，
不能把两个批次相加为独立测试总数。完整父链验证耗时仍不证明查询性能达标。

完整 V1 批 84823 已启动，`output/run-plan-case-v1-release-20261013.log`。
已完成 hygiene、Portal lint/boundary/i18n、**1412 项 Portal contracts**、Portal build
和 **132 项 Runner tests**；主 chunk 仍有 500 kB 告警。记录时正在运行隔离 PG/MinIO
全后端阶段，完整门禁没有终态，不当作 V1 全绿；下一轮须重读同一 handle 和日志，
不能因观察超时重启任务。release Compose 使用独立项目，不影响现有依赖容器。

固定 exweb cache 再次核验 HEAD 为 fe5827f6b76f77ef34918d8b452ee823142332dc，
porcelain 为空，没有修改示例仓、gold、原用例分母或预期失败。

完整 P0-P6 继续 active。原 fixture 捕获值到业务资源的原生绑定、跨会话/QA 消费、
unknown 恢复、实际 Temporal/exweb 公共执行链、正式 coverage/release、五用途
上下文、旧链切换，以及独立 gold、安全、容量/性能、DR、试点与最终 V1 门禁
均未因本专项完成而缩小；父链回读耗时较长也不能视为性能门禁已通过。

## RunPlan 业务执行 Portal 与隔离浏览器验证（2026-10-13）

上一轮仅说明数据关联，没有继续实现。本轮接续已有 Portal 草稿，补齐完整原引用
准备、原命令只读恢复和独立取消契约；完整 P0-P6 目标继续 active，不将离线 UI
验证等同于真实目标执行、正式 coverage/release 或上线门禁。

HTTP RunPlan 已挂载领域化业务执行面板。全部 case 的 setup 引用必须一致读回，
未填齐不能发起核验；创建前保存完整幂等输入，ACK 后仅确认同一 ID。刷新只读，
取消独立确认，unknown 不重发；历史完整分母、步骤/oracle 和观察 hash 逐条核验，
403/协议错误隐藏受保护结果。补齐两列/手机单列及现有 token 按钮样式，中文状态
走共享 i18n，明确 completed 不等于所有测试通过、正式执行/通过计数仍为零。
旧构建审阅读取器同步 canonical `case_claim_protocol` 元数据字段，不扩大业务字段
集合或忽略未知字段。细节见 [RunPlan 业务任务](./run-plan-case-jobs.md)。

已终态证据（选择集重叠，不累加为项目独立测试总数）：

- Portal build / lint 退出 0，分别见
  `output/run-plan-case-portal-build-final-20261013.log` 和
  `output/run-plan-case-portal-lint-final-20261013.log`。主 chunk 1,331.57 kB，
  仍有 500 kB 告警，没有通过提高阈值隐藏。
- 全 Portal contracts 退出 0：**1412 passed / 10230.654875 ms**，无 skipped，
  `output/run-plan-case-portal-all-contracts-final-20261013.log`。含本专项 62 项；
  Python 原编译/物理 verifier 使用明确协议替身，不是实际 PG 或 exweb 运行。
- 首次扩大回归退出 1：1 failed / 1469 passed / 119.84 秒；旧 handoff 协调字段
  缺项已修正，单独 Portal boundary 重跑 **25 passed / 0.15 秒**。
- 修正后重新执行完整同一扩大选择集，32005 退出 0：
  **1470 passed / 126.04 秒**，`output/run-plan-case-portal-backend-final-20261013.log`。
  包含 API application/DDD/fixture/目录及 Portal 边界；明确使用非连接 PG URL、
  auto-create=false、transport/session/storage doubles 和离线 DDL，不是实际 PG 证据。
- 本专项单独重跑 47492 退出 0：**62 passed / 1375.149167 ms**，
  `output/run-plan-case-portal-contract-final-20261013.log`；包含在 1412 中，不另行累加。
- 隔离 Playwright CLI 浏览器验证原确认、七 case 历史、刷新零新增写、独立取消、
  unknown 完整分母、403 隐藏、历史计划只读及中英文/desktop-dark/mobile-light。
  `output/playwright/run-plan-case-*-20261013.log` 与截图保留；响应均为显式替身。
  初次探针受 Vite allow-list 拒绝后改用仅隔离 Portal 内的生成样本，不放宽生产
  Vite 配置；临时页面、样本文件、专属浏览器与 5189 服务已移除/停止。

Docker info 退出 1，socket 缺失。未启动实际依赖/开发服务/外部模型或目标，未应用
开发迁移、未用 SQLite；没有本轮实际 PG/MinIO/Temporal、E2E、smoke 或完整 V1
绿色证据。固定 exweb cache HEAD 仍为 fe5827f6b76f77ef34918d8b452ee823142332dc，
porcelain 为空，没有改示例仓、gold、用例分母或预期失败。

仍需跨会话发现、QA 消费政策、fixture 捕获值的原生业务资源绑定、独立 unknown
恢复、真实 exweb/PG/MinIO/Temporal、正式 coverage/release/GC、五用途上下文和
旧链切换，以及 P0-P6 全部独立 gold、安全、容量/性能、DR 和试点验收。

## RunPlan 原业务任务生命周期与回归（2026-10-13）

上一轮问答只核查了关联链路，没有继续实现。本轮接续已有未完成的 0120 任务代码，
确认原专项 37303 已退出 1（3 failed / 106 passed / 14.55 秒），修正新增测试对
异常类型及 cleanup 字段的错误假设，并处理实际工具发现/目录字节预算回归。
完整 P0-P6 目标仍为 active，不以本增量缩小验收范围。

公共 execute/cancel/query 已连接 canonical ToolRuntime、独立 confirmation、当前
admin/source ACL、原命令 Temporal 同 ID 调度/取消及只读 private/no-store 历史。
固定 migration 0120 保存 append-only 取消和 delivery 记录；prebinding 取消、终态
回读、未知结果不续 lease/不重发、当前读者历史权限与原执行者身份分离已有契约。
新增 delivery 并发锁及元数据回执完整分母/状态一致性检查。完整契约与剩余项见
[RunPlan 业务任务](./run-plan-case-jobs.md)。

Planner v3 继续无损保留全部 ID、原顺序、完整治理字段及 6999 字节预算；prefix
coalescing 和频繁分组索引压缩避免目录增长测试替换原排名。新执行工具仅在对应
任务意图中提高排名，不挤占旧生成/准备；中英文/明确 Tool ID 的独立确认测试保留。

最终终态证据（选择集有重叠，不累加为独立项目测试总数）：

- 90559 退出 0：扩大后端/DDD/fixture/目录回归 **1445 passed / 123.98 秒**，
  `output/run-plan-case-jobs-regression-20261013.log`。显式 PG URL、auto-create=false；
  session/journal/HTTP/storage/Temporal transport doubles 与 PostgreSQL 离线 DDL，
  包含新鲜进程模块导入；不等于实际 PG 或目标执行。
- 76230 Portal build 退出 0；仍有 1,304.28 kB / 500 kB chunk warning，
  `output/run-plan-case-jobs-portal-build-20261013.log`。本轮无视觉样式修改。
- 95557 Portal lint 退出 0；91138 Portal contracts 退出 0，
  **1350 passed / 9713.973583 ms**，无 skipped，分别见
  `output/run-plan-case-jobs-portal-lint-20261013.log` 与
  `output/run-plan-case-jobs-portal-contracts-20261013.log`。
- 0120 生产模块、worker/container/router、migration 及新增实际 PG 测试语法编译
  通过。真实 PG 专项文件仅编译，未收集或执行，不把离线替身当成事务证明。

Docker info 再次退出 1，socket 不存在。未启动外部依赖/开发服务/目标/外部模型，
未应用开发 migration，未使用 SQLite；没有新 E2E、smoke 或完整 V1 绿色证据。
固定 exweb cache HEAD 再核对为 fe5827f6b76f77ef34918d8b452ee823142332dc，
porcelain 为空；没有改外部仓、gold、原用例分母或预期失败。

仍需 Portal、QA 消费政策、fixture 捕获值到业务资源的原生绑定、独立 unknown 原
结果恢复、真实 PG/MinIO/Temporal/exweb、coverage/release/GC、五用途上下文与旧链
切换，以及完整 P0-P6 独立 gold、安全、容量/性能、DR 和试点验收。

## RunPlan 独立业务命令持久认领（2026-10-13）

上一回合补齐原执行输入 producer 与内部组装，属于实际进展。本轮继续 P5 的
公共任务前置基础，不把内部入口误报为完整生命周期。Docker info 再次退出 1：
socket 不存在；未启动依赖/开发服务/目标镜像/外部模型，未应用开发 migration，
未使用 SQLite。完整 P0-P6 目标保持 active。

新增纯领域完整 selection 规则、独立 preparation/binding 规则、两张 PG append-only
receipt 表及固定 `0119_run_plan_case_preparations` migration。原 `ToolInvocation`
认领进入 running 的同一事务写 receipt，固定完整请求/命令 digest、确认人、原
确认/PG 认领时间。server-owned `case_claim_protocol` 拒绝客户端伪造，规范化
selection 时移除，但完整命令 hash 不移除。严格保留全部七 case/setup pins。

首次 case work/lease 同事务写 preparation/work binding；之后原命令输入读取和
每次执行命令 fence 都复验原 receipt、work、binding 链。丢失/修改/降级不能重建
历史，旧终态只读不续期、不转为新执行许可；新 project/run 的准备槽唯一性阻止
两个不同命令同时认领同一次原尝试。`ToolClaimJournal` 组合原 fixture 与新 case
hook，未替换已有 fixture 账本。认领及绑定的 execution/coverage/commit authority
均为 false，不写伪造结果。

新增内部、限页、只读 preparation discovery/delivery 端口，尚未注册实际 Temporal
调度器，也没有添加公共 Catalog/HTTP/Portal 执行入口。不可将此元数据发现端口
当成公开历史或完整任务恢复。源码契约与缺口见
[独立业务命令认领](./run-plan-case-preparation.md)。

本轮终态证据（选择集重叠，不累加为独立测试总数）：

- 41844 退出 0，专项 **194 passed / 12.89 秒**，
  `output/run-plan-case-preparation-initial-20261013.log`。
- 75574 退出 0，扩大后端/DDD/fixture 回归 **1210 passed / 40.46 秒**，
  `output/run-plan-case-preparation-regression-20261013.log`。显式 PG URL 与
  auto-create=false；新事务验证采用明确的 session doubles，DDL 为 PostgreSQL
  离线编译，无实际 PG/MinIO/Temporal/exweb target 运行。覆盖原完整清单、marker
  防伪、确认期限、缺失/损坏记录拒绝、原 work 绑定、组合 hook 保留旧 fixture、
  固定 DDL/unique/FK/trigger/降级保护、无连接模块导入。
- 16900 Portal build 退出 0，仍有 1,304.28kB / 500kB chunk warning；
  `output/run-plan-case-preparation-portal-build-20261013.log`。本轮无前端样式修改。
- 89966 Portal lint 退出 0；57511 Portal contracts 退出 0，
  **1350 passed / 8322.360333ms**，无 skipped，
  `output/run-plan-case-preparation-portal-lint-20261013.log` 与
  `output/run-plan-case-preparation-portal-contracts-20261013.log`。不是浏览器
  HTTP/PG/Temporal E2E。production、新 migration 与 PG 测试文件 py_compile 退出 0；
  tracked diff --check 退出 0，新文件局部空白检查无命中。
- 新真实 PG 测试已写入 `test_run_plan_case_preparation_postgres.py`，覆盖原命令
  并发、不同命令同 project/run 竞争、异常回滚、不可变 trigger、已有记录拒绝降级
  和独立空 schema migration roundtrip。本轮仅编译，未收集/执行，不称为 passed。
- 文档边界更新后 18528 退出 0，**169 passed / 5.56 秒**，
  `output/run-plan-case-preparation-boundary-final-20261013.log`。与扩大组有重叠，
  不累加；之后只有此进度记录更新，没有代码或测试变更。
- 固定 exweb cache HEAD 仍是 `fe5827f6b76f77ef34918d8b452ee823142332dc`，
  porcelain 空；不改变示例源、原 oracle、外部 gold 或验收分母。

继续交付公共命令/Catalog/RBAC、Temporal 取消/重试/恢复、完整当前 ACL 下的私有
历史读取、Portal、fixture 到业务资源绑定和独立 unknown 处置。实际 PG/MinIO/
Temporal/exweb case-to-coverage/release 验证、五用途、旧链切换与 P0-P6 的全部
安全/版本/gold/性能/试点条件仍必需。没有最新完整 V1/E2E/smoke 全绿证据，不以
本轮契约检查代替最终验收。

## RunPlan 原业务执行输入核验与内部组装（2026-10-13）

上一回合只解释数据关联，未改变实现，属于 no progress。本轮复查现有端口后继续
原 P5 执行链；Docker info 仍退出 1，socket 不存在，不能验证实际 PG/MinIO/Temporal。
完整目标仍 active，不启动依赖/目标/模型，不应用开发 migration 或使用 SQLite。

新增严格的完整 execution selection、原命令/PG 时间读取端口、原输入 producer 和
fixture 原阶段核验服务。独立命令先于私有输入读取，完整 plan/build/environment/
locator、每个 case 的原 manifest/setup、当前 actor/source fingerprint、实际 target
epoch/原生健康逐项复查；不借用 fixture 许可或客户端 verified 标签。每条 setup
额外核对确切原 invocation/request 与原 v4 dispatch，并回读全部 cleanup slots。
缺少/未知 setup 或任意已派发清理均拒绝，不截断原 case/step/oracle 清单。

组装到 RuntimeAssembly/ApplicationContainer 的 `run_plan_cases` 内部入口，producer
是 mandatory guard；既有 owned Runner + PG case journal + 物理 verifier + 独立私有
MinIO archive 完整连接。同步核验转入受监督线程，取消 join 后不进入执行。可选
Node 配置在执行时、租约/claim 前检查，不阻止无关 API startup。case archive 拒绝
local/public/foreign namespace、损坏/不完整字节、歧义 JSON 与非 JSON 常量。

发现并修正跨 session 重取项目写锁的潜在等待：原 command 和 fixture history
核验使用显式只读路径，递归 setup 也保持只读；原派发/提交/取消写锁不改变。
SQL/事务替身证明没有读回调重新申请写锁，但真实 PG 竞争、原生资源互斥及 P6
时延/容量没有验收。现有 fixture 私有历史管理员政策未放宽，QA 完整消费仍需
独立权限交付。公共 Tool/HTTP/Temporal/Portal 和正式 coverage/release 不因此完成。

测试证据与终态：

- 首个新 specimen 错把完整准备清单当作一条：96041 退出 1，102 passed /
  35 setup errors / 5.55 秒（终端输出）。修正 specimen 保留全部七 case，未修改
  生产分母、原业务 oracle 或外部 gold；90964 退出 0，35 passed / 2.27 秒，
  `output/run-plan-case-inputs-initial-20261013.log`。
- 63545 退出 0，专项组合 200 passed / 12.62 秒，
  `output/run-plan-case-inputs-composed-20261013.log`。
- 26699 退出 0，扩大后端/DDD/fixture 组 1141 passed / 39.12 秒，
  `output/run-plan-case-inputs-regression-20261013.log`。随后增加严格 ID、无连接新
  模块/container import、受监督 preparation 取消和完整清单测试；79195 退出 0，
  **1148 passed / 40.37 秒**，`output/run-plan-case-inputs-final-20261013.log`。
  全部明确配置 PG URL、auto-create=false；journal/storage/健康是显式 doubles，
  没有实际 PG、MinIO、Temporal 或目标 HTTP。完整 producer/worker/archive 组合
  保留七 case，正式 automation/execution/pass 计数仍为 0。
- 70324 Portal build 退出 0，仍有 1,304.28kB / 500kB chunk warning；
  `output/run-plan-case-inputs-portal-build-20261013.log`。本轮没有前端样式修改。
- 97230 Portal lint 退出 0；65868 Portal contracts 退出 0，
  **1350 passed / 8313.738625ms**，无 skipped，
  `output/run-plan-case-inputs-portal-lint-20261013.log` 与
  `output/run-plan-case-inputs-portal-contracts-20261013.log`。这不是实际浏览器或
  HTTP/PG/Temporal E2E。修改模块 py_compile 退出 0；tracked diff --check
  退出 0，新增文件另做局部空白检查无命中，不忽略未 tracked 文件。
- 更新边界文档后 6650 再次退出 0，原 case persistence/fresh import 与 DDD
  专项 **154 passed / 3.16 秒**；`output/run-plan-case-inputs-boundary-final-20261013.log`。
  与上面的扩大组有重叠，不相加为新的独立测试总数；之后只有此记录更新。
- 固定 exweb cache HEAD 再次核验为
  `fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain 空。不是新 exweb 业务执行。

契约见[原业务执行输入核验](./run-plan-case-inputs.md)。真实 PG/MinIO/Temporal/exweb、
公共执行/取消/恢复、fixture 到业务资源绑定、独立 unknown 处置、真实 coverage/
release/GC、五用途、旧链切换及 P0-P6 所有安全/版本/gold/性能/试点条件继续必需。
最新完整 V1/E2E/smoke 未通过或未运行，不以契约测试数量认定目标完成。

## RunPlan 原用例执行核心与 PG 派发账本（2026-10-13）

上一用户回合解释关联，没有新增实现或改变下一实现动作，按 no progress 复核。
Docker socket仍不存在，docker info退出1；固定exweb缓存HEAD仍为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain空。继续P5实际缺少的用例
执行链，完整P0-P6目标保持active，不启动依赖/开发服务、目标镜像、外部模型或
应用开发migration，不以SQLite替代真实PG验证。

新增domain/application原case执行核心、PG持久适配器与固定0118 migration。
完整原RunPlan的v1/v2 HTTP清单保留每个case/step/oracle；独立原命令guard拒绝
fixture许可、字段/账号改变和过期确认。完整请求固定原构建、环境、locator和
所有setup命令pins；pins不是证明，实际原输入producer仍需交付。

PG work/lease与原RunPlan和ToolInvocation连接；claim按project/run/case唯一，
先提交再请求，租约以PG时间、owner/epoch和90秒期限隔离。完整native wire/response
工件重验后私有归档、回读，再同事务提交outcome/审计/Outbox。缺结果的原claim保持
unknown，不重发剩余清单；失败case不丢弃其他case。取消与原派发共享锁，旧owner
不能迟到提交，异步取消等待本人线程结束。完整观察先于迟到cancel，unknown仍先于
cancel；不声称目标已回滚。历史读取复验完整原字节/动作/oracle和最终库存/权限。

此阶段是实际可调用内部Worker及持久适配器，不是公共production入口：预留的
execute/cancel Tool IDs尚未加入Catalog/HTTP/Temporal/composition，完整原输入
producer、native fixture/runtime核验和Portal也尚未组装。不得从客户端JSON构造scope
或在production使用空授权回调。所有正式automation/execution/pass计数仍为0，
不得从内部观察自行晋级业务coverage。契约见[原用例执行核心](./run-plan-case-execution.md)。

失败证据保留：首批36562退出1，initial日志**10failed/63passed/2.69秒**；测试
替身将asdict的tuple传入原生wire解析，生产正确拒绝缺少JSON数组工件。修正替身
经JSON roundtrip后94646退出0，**73passed/2.73秒**，未放宽生产校验。

后续终态证据：

- 87939退出0，扩大offline组**116passed/4.31秒**；
  `output/run-plan-case-work-expanded-20261013.log`。
- 89485退出0，扩大后端/DDD/原fixtures组**1029passed/31.71秒**；
  `output/run-plan-case-work-combined-20261013.log`。
- 80761退出0，显式PG URL、auto-create=false的offline专项
  **242passed/12.67秒**；`output/run-plan-case-work-final-specialist-20261013.log`。
  含fresh import拒绝任何Engine.connect、固定DDL/ORM字段/FK一致性和v2完整清单。
- 28437退出0，显式PG配置的扩大offline组**1066passed/31.82秒**；
  `output/run-plan-case-work-final-combined-pg-configured-20261013.log`。
  随后补迟到取消保留全部观察、畸形原命令拒绝；最终同范围77425退出0，
  **1067passed/31.68秒**，`output/run-plan-case-work-permission-and-cancellation-final-20261013.log`。
  这些是显式PG配置的offline契约，不是真实PG执行结果。
- 78994退出0，完整Portal contracts **1350passed/8821.566584ms**，无skip；
  `output/run-plan-case-work-portal-contracts-20261013.log`。
- 45621 build退出0，仍有约1.304MB/500kB chunk warning；33664 lint退出0。
  `output/run-plan-case-work-portal-build-20261013.log`与
  `output/run-plan-case-work-portal-lint-20261013.log`。本轮没有前端样式变更。
- 新随机PG schema空表roundtrip定义只py_compile退出0，未导入/收集/运行。
  所有上述offline组使用明确journal/工件/wire doubles，不是PG事务、MinIO、
  Temporal、operator target、独立业务gold或exweb执行。git diff --check退出0只
  覆盖tracked，新文件另做局部空白检查，无命中；不以tracked空diff证明新文件。

完整原输入/授权/公共Tool/Temporal/Portal、真实PG锁/事务/触发器/重启、独立unknown
恢复、真实目标case/step/oracle到coverage/release和GC仍需交付。五用途及旧链切换、
P0多语言独立gold、P1身份/证据、P2全计划预算/生命周期、P3正式规范关联、P4自动
增量DAG、P6安全/容量/性能/灾备试点和最新完整V1/E2E/smoke继续必需。
35058原owned DB/bucket待依赖恢复后清理，98424旧V1无终态摘要，不作为live或绿色。

## 独立原操作阶段核验与查询包循环导入修复（2026-10-13）

上一用户回合只解释数据关联，没有新增实现或改变下一实现动作，按 no progress
复核。Docker socket仍不存在，docker info退出1；原固定exweb缓存HEAD仍为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain空。继续P5实际缺少的跨浏览器
原操作阶段读取，保持完整P0-P6目标active，不启动开发服务/依赖、应用开发migration、
调用外部模型或目标。上一组最终日志保留459passed/11.01秒，没有重启原停止的长测。

新增domain/application原阶段服务、typed GET response与canonical只读tool。原ID
重新经过完整recipe/grant/RunPlan/native environment ancestry，调用现有jobs.read
原preparation/intent/全部阶段port；cleanup库存包含每个原capture binding，claim
按原project/attempt/case/phase推导。grant和待确认执行仍没有journal，不合成派发。
unknown优先于failed/cancelled，observed保留原结果状态，不晋级coverage/rollback。
末尾重新核验选定命令、原execute和当前ACL；状态/request变化返回409，旧query回执
阶段变动也返回409。私有no-store与共享通用SSE隐藏沿用原receipt protection。
新tool角色仍project_admin/platform_admin，旧Tool IDs没有删除，无新migration。

生产Knowledge历史面板另加显式原阶段核验，project/actor/request/status/source scope
query隔离，retry=false/gcTime=0/AbortSignal。读取中隐藏旧元数据，错误隐藏队列/
观察，刷新可重新发现，不依赖或写sessionStorage；没有确认、取消、重发和新attempt
按钮。局部按钮用shared tokens细边框，窄屏阶段/ID分行，未改全局样式和图标。
完整契约见[原阶段核验](./http-fixture-original-observations.md)。

本轮额外发现真实fresh-import错误：直接导入history会经query_input触发tool_handlers
包的eager registry，再回读尚未初始化的history。改为lazy具名/星号兼容导出，查询
辅助不加载全部context，新增6个fresh-interpreter入口与完整export检查，未通过
更换测试导入顺序规避。这个修复仍在application层，不把ORM/供应商引入domain。

失败记录保留：88822退出1，initial日志38failed/93passed，明确job port specimen
误将JobTarget和HistoryTarget两个不同Pydantic类型直接比较。修正为精确wire比较，
未改变生产验证；64798退出0，131passed/6.47秒。首次Portal build79141退出2，TS
assertion过度收窄phase数组，改先分类再校验completed必须observed，未放宽unknown。
fresh browser specimen首次命令退出1，记录循环导入；随后同入口退出0，使用
`fixture-original-observation-browser-specimen-verified-20261013.json`，失败的空输出
不作为gold。原Vite验证启动有esbuild unresolved-import warning，但进程ready，未
新增/安装依赖。各日志保持原样。

本轮终态证据：

- 后端扩大组58976退出0：158passed/8.22秒；combined55868退出0：534passed/
  16.58秒。修复import后552passed/17.76秒，28838退出0；再补独立管理员不继承许可、
  reader拒绝及混合回执拒绝，最终30233退出0：**556passed/17.80秒**；
  `output/fixture-original-observation-permission-verified-combined-20261013.log`，含fixture/
  history/observation、delivery/preparation/native grants、runtime ports及DDD/Portal boundaries。
- fresh import/runtime专项31213退出0：18passed/2.69秒，
  `output/fixture-original-observation-import-boundaries-20261013.log`。
- Portal新/旧历史专项54321退出0：123passed/1354.322541ms；
  `output/fixture-original-observation-portal-contracts-20261013.log`。
- 全部Portal contracts34463退出0：1350passed/8768.553ms，无skip；
  `output/fixture-original-observation-all-portal-contracts-20261013.log`。
- 最终Portal build87685退出0，主chunk约1.304MB/500kB warning保留，
  `output/fixture-original-observation-final-portal-build-20261013.log`；lint72366退出0，
  `output/fixture-original-observation-final-portal-lint-20261013.log`；i18n退出0。
- 真实Chromium组件组33975退出0；截图回读发现局部按钮原生样式和状态/ID相邻难读，
  改局部CSS后最终45989退出0。light/en1280刷新独立读取、dark/zh390取消仍unknown、
  light/zh390污染与撤权隐藏均通过，读取中旧metadata隐藏，sessionStorage空。
  write/unknown API/egress/pageerror均空，无横向溢出；最终日志
  `output/fixture-original-observation-browser-verified-20261013.log`及
  `output/playwright/fixture-history-browser-contract-20261013.json`。
  所有API被拦截、身份为明确UI specimen；不是正式路由、真实ACL/认证/PG/Temporal/
  exweb或业务gold。只启动本人无API proxy的4207验证surface，不重启开发服务；
  结束后核验65744为原config/4207 Node进程，再只向它发送TERM；40549退出143，
  lsof4207无listener，不将该正常测试清理当作开发服务失败。
- 已在原隔离PG/MinIO集成定义补pending与cancel→原阶段GET及无新dispatch/runner
  断言；仅py_compile退出0，未导入app.main、采集或运行，不把定义当实际PG证明。

独立unknown效果审阅/处置与恢复、真实case/step/oracle到coverage/release、五用途及
旧链切换、原生exweb、P0多语言独立gold、P1证据身份、P2完整预算/生命周期、P3正式
规范关联、P4自动增量DAG、P6安全/性能/灾备试点和最新完整V1/E2E/smoke仍必需。
本轮是实际进展但目标未完成，不把只读阶段查询当作未知效果已恢复或范围缩小。
35058原owned DB/bucket仍待依赖恢复后清理，98424旧V1无终态摘要，不当作live或绿色。

## 项目级原测试数据命令发现与只读 Portal（2026-10-13）

上一回合解释了数据关系，没有新增实现，按 no progress 重新核对当前代码和依赖。
Docker socket 仍不存在，`docker info` 退出1。继续可安全推进的 P5 项目级历史发现，
保持完整 P0-P6 goal active，不启动依赖/开发服务、执行开发 migration、外部模型、
目标镜像或采用SQLite替代PG。

新增 `http_fixture_history` domain/application/persistence，复用现有 ToolInvocation、
grant/recipe/manifest，不增加 migration。全部项目的原 grant/execute/cancel 生命周期
都从原命令发现，不依赖 sessionStorage、不限制创建者、不只查已绑定 intent。
SQL先过滤全部来源权限再计数分页，一条statement保留total与look-ahead；应用层回读
原完整配方/许可并最终重验ACL。无法解析的原 ancestry 拒绝完整库存，不用零掩盖损坏；
PG outage 有独立脱敏503，来源权限及归档错误保留403/409/404/502。

新增两个private,no-store GET及canonical query tools，复用原handler、RBAC和receipt
access。只返回原ID/hash/stage/status/op，不泄露正文、target、密钥或idempotency key，
四项authority均false；共享SSE/会话仍只广播通用状态，不返回input/result。瞬时query
回执在使用时完整重查，新命令或状态/ACL变化不能沿用旧页操作。

生产Knowledge接入默认折叠的独立历史面板，点击后查询，显式翻页/刷新/原命令明细；
完整页count/scope/cursor/重复ID校验，project/actor隔离，retry=false/gcTime=0。
读取中、签出、切换、权限/状态或完整性错误隐藏受保护视图。只读入口没有确认/取消/
重执行按钮，不把发现原ID当作独立unknown恢复完成。实现契约见
[操作历史](./http-fixture-operation-history.md)。

保留原失败记录：首批61契约通过；扩大组15147退出1：429passed/1failed，发现新query
tools在通用RBAC被当成viewer查询。已在原角色策略补project_admin/platform_admin，
未放宽原门禁；随后19316退出0：430passed/10.82秒。前端初次lint8784退出1是控制字符
正则规则，改逐字符校验后通过；错误npm脚本`test:portal:contracts`退出1且未运行测试，
后续使用实际`test:portal-contracts`完整运行。各失败log保持原样。

本轮当前最终可核验结果：

- 77360退出0：**459passed / 11.42秒**，原fixture任务/取消/准备/原生许可及新的history/
  HTTP错误契约，加DDD、fixture和Portal boundaries；
  `output/fixture-project-history-storage-verified-combined-20261013.log`。
- 95064退出0：**1286 Portal contracts passed / 10305.939375ms**，无skip；
  `output/fixture-project-history-all-portal-verified-contracts-20261013.log`。
- 新前端history专项退出0：**59passed / 1097.753417ms**；
  `output/fixture-project-history-portal-verified-contracts-20261013.log`。
- 最终Portal build67238退出0，保留主chunk约1.297MB和500kB警告；
  `output/fixture-project-history-final-portal-build-20261013.log`。
- Portal lint62999退出0，`fixture-project-history-portal-verified-lint-20261013.log`；
  `npm run test:i18n`退出0，`fixture-project-history-i18n-20261013.log`。
- 已补原API文件中的真实隔离PG/MinIO历史发现/取消/SQL过滤验证，**只py_compile通过，
  未导入app.main、采集或运行**，不能把定义当作实际数据库证明。
- `git diff --check`退出0仅覆盖trackeddiff；新history文件为untracked，另做局部空白检查。
  固定exweb缓存HEAD仍`fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain空。

没有本轮正式路由browser/E2E、实际PG/MinIO/Temporal或原生exweb执行结果。依赖恢复后
仍须完成原history真实集成、独立unknown处理/恢复、完整RunPlan逐case/step/oracle到
coverage/release、五用途及旧链切换，并继续P0多语言独立gold、P1身份证据、P2完整预算/
生命周期、P3规范关联、P4自动增量DAG、P6安全性能/灾备试点及完整V1门禁；范围不缩小。
35058的原owned DB/bucket待依赖恢复后清理，历史完整V198424停止/缺终态摘要，均不当作
当前live或绿色证据。本轮没有重启这些进程。

## 真实浏览器组件验证与取消输入竞态修复（2026-10-13）

上一用户回合仅解释数据关联，没有新增实现或验收，按 no progress 复核；此前 Portal
接线阶段的真实进展仍保留。本轮重新检查生产代码和 Docker，socket 仍不存在，
`docker info` 退出1。正式 Playwright 配置明确要求隔离 PG，不能冒称完整 E2E 已运行。
继续选择可安全推进的 P5 工作，目标保持完整 P0-P6 active，不启动依赖、开发服务、
开发 migration、外部模型或目标镜像，也不以 SQLite 替代 PG。

新增 `tests/browser/http-fixture` 的独立组件浏览器契约。只启动本人拥有的无 API proxy
Vite 验证进程，端口4197；真实 Chromium 挂载生产操作面板、React Query、StrictMode、
现有 CSS 和中英文翻译。Python 生产领域编译器及明确 inspector doubles 构造协议样本，
全部 API 被拦截，未知 API 拒绝，非本人 loopback origin 的 egress 阻断并检查为空。
这个隔离 surface **不是完整生产路由、真实 ACL/RBAC/PG/Temporal/exweb 或业务 gold**。
浏览器 CLI VM 不能加载本地模块，改用仓库已安装的 Playwright engine；未新增依赖。

实际发现恢复执行后取消写入前异常：pending 停用敏感查询并改变 execution query key，
Mutation 再读取 `execution.data.command` 时为 undefined，取消命令根本未发出。
现在在点击时固定完整已核验 input 与操作范围为 Mutation variables，不从消失的
query data 回取。写入前仍读取实际 session 的原 command ID；异步 hash 完成后再读
session 做同步 CAS，不通过旧缓存替换原命令、权限或确认。新增 grant/execute/cancel
三项真实 hook 事件回归，模拟 pending 后查询数据消失并替换 Mutation options。

失败证据保留：

- 初轮浏览器 **26361退出1**，`fixture-operation-browser-initial-20261013.log`：明确夹具
  从 native pin 误读 environment_id；修正为原 plan declaration，未修改生产校验/oracle。
- 第二轮 **84786退出1**，`fixture-operation-browser-second-20261013.log`：取消没有发出，
  保留 `output/playwright/fixture-operation-light-en-1280-FAILED.txt` 与 second 标记截图。
- 第三轮 **18492退出1**，`fixture-operation-browser-third-20261013.log`：MutationCache
  错误栈确认生产取消 Mutation 的 undefined 读取，third 标记文本保存完整原因。
- 修复后两场景 **62805退出0**，`fixture-operation-browser-fourth-20261013.log`。
- 扩大 verifier 初次命令退出1，`fixture-operation-browser-fifth-20261013.log`：新增分支
  的脚本语法错误，已修正，不改变业务规则。随后三场景 **87730退出0**，第六轮日志。

当前终态证据：

- 最终真实浏览器组件契约 **52897退出0**，
  `fixture-operation-browser-seventh-20261013.log`，三场景报告
  `output/playwright/fixture-operation-browser-contract-20261013.json`。轻色英文1280桌面：
  grant→execute→cancel 各一次，新勾选分离；lost invoke/confirm ACK 只读恢复；双击和
  刷新不产生第二次执行；取消待投递不显示新操作捷径。深色中文390窄屏：v1 已观察的
  failed 不晋级 coverage，同 attempt 的 cleanup 仍独立准备且不自动写；无水平溢出，
  撤权后父级隐藏。浅色中文390窄屏：unknown 无重发/新操作捷径，污染业务 authority
  的观察拒绝并隐藏。未知 API、外部 egress、pageerror 均为空；只有明确模拟的两次
  lost ACK 允许 Mutation 错误。截图已回读窄屏布局，不作为完整 UI/可访问性验收。
- Portal 原操作专项 **29198退出0：66 passed / 2482.41175ms**，
  `fixture-operation-query-snapshot-contracts-20261013.log`，无 skip。
- 完整 Portal contracts **5365退出0：1227 passed / 7995.05575ms**，
  `fixture-operation-query-snapshot-all-contracts-20261013.log`，无 skip。
- Portal build **35600退出0**、lint **94012退出0**，分别为
  `fixture-operation-query-snapshot-build-20261013.log` / `...-lint-20261013.log`。
  500kB chunk warning 保留，不宣称 bundle 性能达标。
- 最终 fixture/Portal/DDD/model registration 边界 **89954退出0：172 passed / 2.44秒**，
  `fixture-operation-query-snapshot-verified-boundaries-20261013.log`，无 skip；新增边界
  要求 Mutation 消费输入快照，不重新读取 prepared/query data，session 读取晚于 hash。
- `npm run test:i18n` 退出0，`fixture-operation-query-snapshot-i18n-20261013.log`。
  `git diff --check` 退出0；另对本轮未跟踪代码执行 trailing-blank 搜索，无匹配，
  不把 tracked diff 的空输出当作未跟踪文件已覆盖的证明。
- 固定 exweb 缓存 HEAD 仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain 空。
  原源码、预期、失败和分母没有改动。

本轮没有后端 schema 变更或真实 PG/RPC 验收。验证进程/浏览器只为本人临时创建，
结束后只清理本人进程，不重启用户开发服务。完整正式页面路由、PG 事务/锁竞争、
Temporal 重启/取消、公共 canonical exweb 原生业务、项目级操作历史发现、独立 unknown
恢复、逐step/case/oracle到coverage/release、五用途/旧链切换、完整自动增量、Provider
多语言独立 gold、安全/容量/灾备/性能与试点、最新 V1/E2E/smoke 门禁均仍必需。
此前35058拥有的 DB/bucket 待依赖恢复后清理；不把它们或旧进程状态当作当前 live。

## 原 fixture Portal 许可、执行、观察与取消（2026-10-13）

上一轮用户问题仅解释几类数据的关联，没有新增实现或改变下一实现动作，按
no progress 复核。本轮重新检查生产组件、应用/领域协议、设计和 Docker；socket 仍
不存在，`docker info` 退出1。没有重启服务、应用开发 migration、发送模型请求或
启动目标镜像。实际完成 P5 原 fixture 操作的 Portal 接线和回归，属于 progress；
完整 P0-P6 目标保持 active，不以当前切片替代原始完成定义。

已核验 definition 后新增折叠的操作面板：输入原环境登记命令，GET 回读原 native build
命令、全部源码构建成员、完整 binding 与环境库存；只核验历史，不启动环境或刷新
健康。显式 v2 grant 固定原 recipe/attempt/operation/timeout、实际 inventory 与 operator
policy 的不同摘要。许可、执行、取消分别经 canonical ToolRuntime 与新的用户确认；
许可不自动执行，取消投递不证明目标停止、资源清理或业务回滚。

浏览器验证 command 全业务字段、原 request key/hash、确认账号和时间、UUIDv5 grant
身份、完整 scope/request/native pin 摘要、15分钟期限、v1/v2 job 及确定性 phase claim。
绑定前状态无 intent 或 target observation；completed 要求全部 phase observed，但仍可
记录 failed，不晋级业务 coverage。原 command 与 job 的 GET 终态竞争只读重查同 ID。

session 恢复仅固定 ID/hash 与有界操作范围，不存正文、环境 inventory、URL 或凭据。
先写 request key、ACK，再确认；未知 ACK 只 GET 原命令，不重新 invoke 或自动确认。
恢复后的原 waiting_confirmation 从存储回读已核验的原 ID，需要新勾选才能确认。
新操作、字段/输入/head/证据刷新和环境缓存范围变化都会使原勾选失效；读取损坏/撤权
隐藏父级受保护内容。unknown/failed/cancelled 不显示新操作捷径；完整 observed 的
completed setup 只能显式准备同 attempt 的 cleanup，新授权/执行仍必须独立确认。

原失败证据保留，未覆盖日志：

- 初始 Portal build **95577退出2**，
  `fixture-operation-portal-build-20261013.log`：未使用类型及翻译 key 类型错误，已修正。
- 初始专项退出1，**47 passed / 3 failed / 1096.772583ms**，
  `fixture-operation-portal-initial-contracts-20261013.log`：Python port specimen 的计划 wrapper
  缺 invocation metadata；补齐明确契约夹具，未放宽生产校验、修改 oracle 或宣称原生构建。
- 后续专项 **65818退出1：53 passed / 1 failed / 1197.892458ms**，
  `fixture-operation-portal-expanded-contracts-20261013.log`：VM harness 缺 client override、
  加载到 import.meta；补齐 transport double，未修改生产请求以迎合测试。

当前可核验终态：

- 原 fixture Portal 专项 **8464退出0：63 passed / 2095.445375ms**，
  `fixture-operation-portal-scope-contracts-20261013.log`。
  使用真实 Python 领域/应用编译与明确 inspector port specimen 核验跨语言完整 metadata；
  原生父链/ACK transport、React/TanStack 调度为 doubles，SSR 不是真实浏览器或业务 gold。
  五项真实 hook 事件检查不同确认、重复点击、写失联、丢失 invoke ACK 后确认原 ID、
  scope 刷新、未知/取消阻断和 completed setup 保留 attempt 的清理准备。
- 当前完整 Portal contracts **94182退出0：1224 passed / 9206.664625ms**，
  `fixture-operation-portal-verified-all-contracts-20261013.log`，无 skip；不是 E2E 或 smoke。
- 当前 Portal build **62482退出0**，
  `fixture-operation-portal-verified-build-20261013.log`；500kB chunk warning 保留。
- 当前 Portal lint **49208退出0**，
  `fixture-operation-portal-verified-lint-20261013.log`。
- 后端 fixture/准备/取消/权限/原生父链与 DDD/Portal/model registration 组
  **77053退出0：871 passed / 22.60秒**，
  `fixture-operation-backend-boundaries-20261013.log`，无 skip；未运行全 API、PG migration、
  真实 PG/RPC 或 exweb canonical 目标业务。
- 固定 exweb 缓存 HEAD 仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，
  porcelain 空；原代码、oracle、失败和分母未改动。

当前实现说明见[原 Portal 操作](./http-fixture-portal-operations.md)。本轮没有数据库迁移。
前批35058的 owned DB/bucket 清理和最新全 V1/E2E/smoke 仍待依赖恢复；未将旧进程
或旧成功计数当作当前 live。完整 browser/轻深移动可访问性、公共 PG/RPC/exweb、
Temporal 重启/取消和独立 unknown 恢复未验证，项目级操作历史发现仍待交付。
逐step/case/oracle到coverage/release、五用途、旧链切换、自动增量、多 Provider/语言
独立 gold、安全/容量/灾备/性能与真实试点均保持原完整 P0-P6 范围，没有最新
`verify:v1-release` 全绿证明。

## 绑定前观察、独立取消与时间损坏拒绝（2026-10-13）

上一轮仅说明数据关联，未新增实现或改变下一实现动作，按 no progress 复核。本轮
重新检查代码、日志与 Docker socket：前批取消专项进程已不在，原日志记录
`232 passed / 7.15秒`，退出码不可核验，不继续声称运行中。Docker 仍退出1、socket
不存在；未启动依赖／开发服务、应用开发 migration、发送模型请求或运行目标镜像。
本轮实际推进 P5 的公开任务协议、异常拒绝和验证，属于 progress，完整 P0-P6 目标
保持 active，不以本切片替代最终验收。

0117 新增原准备取消与取消投递两张追加式 PG 表，固定原准备／命令／独立 control
hash、确认 actor 与 PG 时间。取消在原项目和 Tool 行锁下重新选择分支，已绑定仍走
0115，未绑定不补造 intent。原 cancelled、结果、审计和 Outbox 同事务；随后才投递
原 ID Temporal cancel，临时失联保留请求，reconciler 合并旧／新 keyset 并先取消。
同一请求重放不改输入、不续期、不重复写事件；迟到失败、bind/start 不覆盖终态。
FK、immutable trigger、非空 downgrade 拒绝及无 legacy 回填保留原历史。

只读 HTTP／canonical query 在原管理员和全部来源重新授权后识别新准备，返回 v2
metadata：原 selection/request/preparation digest、准备阶段及 cancellation flags，
明确 `intent_digest=null / phases=[] / target_observation_verified=false`。不创建 intent、
租约、许可或事件，不打开目标历史，也不刷新健康；绑定若先完成返回旧 v1 原 archive
路径。分支混入、丢失准备／取消、orphan delivery、删除 marker 或伪造 intent 拒绝。
取消事件不接受私有 payload 或虚构 Run/step。取消投递不等于目标停止、业务回滚、
清理或 baseline 恢复；所有业务／执行 authority 仍 false。

新增故障测试实际复现请求／投递记录中的非法和无时区时间直接抛出 TypeError／
ValueError。**26391退出1：8 failed / 33 deselected / 1.06秒**，日志
`fixture-preparation-cancel-corrupt-time-baseline-20261013.log` 保留。现统一转为受控
`HttpFixtureInvalid`，旧绑定分支也加入8项同等检查，不修补原历史或放宽原确认。

当前可核验终态：

- 修复专项 **66910退出0：240 passed / 7.41秒**，
  `fixture-preparation-cancel-fixed-contracts-20261013.log`；不含随后追加的旧分支8项。
- 当前 fixture／worker／权限／原生构建／生成恢复／Tool／预算／DDD／Portal 边界
  扩大组 **47019退出0：1232 passed / 4 skipped / 26.78秒**，
  `fixture-preparation-cancel-expanded-contracts-20261013.log`。跳过项不计为通过；
  此组不是全 API、真实 PG/RPC、exweb 原生业务或 V1 门禁。
- Portal build **57816退出0**、lint **42917退出0**，
  `fixture-preparation-cancel-portal-build-20261013.log` / `fixture-preparation-cancel-portal-lint-20261013.log`。
  500kB chunk warning 保留，本轮未新增执行 UI 或修改页面视觉。
- 完整 Portal contracts **7314退出0：1161 passed / 7635.99725ms**，
  `fixture-preparation-cancel-portal-contracts-20261013.log`；不是 E2E／smoke／视觉证明。
- 0117 Alembic PostgreSQL 离线 DDL **退出0**，
  `fixture-preparation-cancel-offline-ddl-20261013.log`；实际生成两表／FK／trigger 与版本
  SQL，但未连接 PG 或应用 migration。
- 原准备 PG 专项、新取消 PG 专项及0116/0117独立 migration **收集退出0：6 collected /
  0.65秒**，`fixture-preparation-cancel-pg-collection-20261013.log`；**不是执行通过**。
- 新 API／PG／migration／repository 语法检查、`git diff --check` 退出0。

新独立 PG 测试强制 `nasus_test_*` 数据库，实际原 claim、角色／控制记录、取消与失败
行锁竞争、第二条 Outbox 已写后的异常回滚、重复 delivery、immutable UPDATE/DELETE
及非空 downgrade；不使用 Runner 或 Temporal。migration 使用随机 owned schema
up/down/up，核对完整列、FK、trigger与空库存，无 legacy backfill。以上尚未执行。

公共 PG/MinIO 父链用例新增绑定前授权只读、不读目标 archive、独立 canonical 取消、
取消 RPC 失联后实际 reconciler 的原 ID 投递、原输入／准备不可变及零 intent／派发／
结果。投递发现限于本测试的原任务，PG 查询与写入仍实际执行；Runner/build/health/
Temporal transports 明确为 doubles。API 当前仅语法检查，未实跑或进行无 PG 的
app.main collection；不把这些用例描述为真实 exweb、Temporal 或完整权限验收。

固定 exweb 缓存再次核对 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain
空，没有修改上游、oracle、原失败或分母。前批35058的精确 owned DB/bucket 仍待依赖
恢复后清理，原失败证据保留；没有启动新的全 V1／E2E／smoke。

专用执行 Portal、真实 PG绑定／取消锁竞争与 Temporal 重启／取消、独立 unknown
恢复、逐step/case/oracle到coverage/release、五用途与旧链切换继续待交付。自动增量、
多 Provider／多语言独立 gold、安全／容量／灾备／性能和真实试点仍保持原完整 P0-P6
范围；没有最新 `verify:v1-release` 全绿证明。协议见[原命令关联](./http-fixture-command-provenance.md)。

## 原命令准备回执与绑定前恢复（2026-10-13）

上一轮用户问题只解释数据关联，没有新增实现或改变下一实现动作，按 no progress
复核。本轮重新检查 worktree 与 Docker socket，`docker info` 退出 1，仍未运行；
未自动重启、执行开发 migration、发送模型请求或拉取／启动目标镜像。实际补齐此前
未绑定 intent 的准备恢复缺口，属于 progress，完整 P0-P6 目标保持 active。

0116 `fixture_preparations` 新增原 claim 与 intent binding 两张追加式表，生产
ConversationRepository 由 composition 注入 claim journal，原 running、确认元数据、
server-only 协议标记与准备回执同 PG 事务。记录固定完整输入摘要、原 actor／project、
原确认及 PG 记录时间，不授予目标权限。绑定在原 intent 事务追加原准备／intent hash，
重复只校验，不修复缺失历史或回填旧未绑定任务。精确 FK／immutable trigger／非空
downgrade 拒绝保留历史。业务 DTO 清除协调标记，原 authority 摘要仍固定全部输入。

恢复扫描现发现新准备及原 bound intent，application 以原 actor、原确认／grant／work
重新准备，先绑定再同 ID 启动，启动前回读取消／终态。无效／过期且原准备可核验的
未绑定命令可在原锁下静态 failed，不因非法 execution DTO 永远卡住；原事实、审计与
Outbox 原子提交，不能覆盖取消，绑定若先获锁还要复查原 live lease。临时故障和未知
Temporal ACK 保留原状态，只能同 ID 投递，不新增 attempt、不续确认或自动重发 unknown
HTTP 阶段。标记删除、准备缺失、已绑定但原 binding／intent 丢失均拒绝，不能降级为
legacy 或重绑。原执行／业务覆盖／基线恢复 authority 全部保持 false。

新增契约使用明确 session／transport specimens，覆盖完整输入／actor／PG时间、缺失
记录、原标记防伪、重复绑定、非法 selection、安全失败、取消／终态、绑定／lease
交错、同 actor 恢复及临时失联。它们不是实际 PG 锁竞争或 Temporal RPC 证明。
初次专项 **72948退出1：1 failed / 179 passed / 6.02秒**，SQLAlchemy 自动参数名被
测试误写为固定名称；改为核验实际 limit 表达式，保留严格分页断言。新增启动前复核后
另一专项 **62821退出1：1 failed / 180 passed / 5.82秒**，测试 transport specimen
仍固定返回 unbound；修正为实际 bind 后状态，不放宽启动前必须 bound 的生产检查。
两份原失败日志保留。修正专项 **35668退出0：181 passed / 5.78秒**，日志
`fixture-preparation-final-contracts-20261013.log`。

扩大组 **17119退出1：1 failed / 957 passed / 19.93秒**，发现前后端协调 envelope
枚举不一致，日志 `fixture-preparation-expanded-contracts-20261013.log`。现同步
BuildReviewHandoff 的 server-only 标记清除规则，不改变页面样式、私有授权或未知业务
字段检查，新增三项锁交错／其他 Tool 不受影响／不能伪造完成的契约。当前终态：

- 扩大 fixture／原命令／权限／worker／生成／ToolRuntime／DDD／Portal 边界组
  **9087退出0：961 passed / 24.77秒**，
  `fixture-preparation-expanded-fixed-contracts-20261013.log`。不是全 API、实际 PG／RPC、
  原生 exweb 或 V1 门禁。
- Portal build **29626退出0**、lint **56860退出0**，
  `fixture-preparation-portal-build-20261013.log` / `fixture-preparation-portal-lint-20261013.log`；
  500kB chunk warning 保留，未新增任务 UI 或浏览器视觉证明。
- 完整 Portal contracts **11967退出0：1161 passed / 9091.726417ms**，
  `fixture-preparation-portal-contracts-20261013.log`；不替代 E2E／smoke。
- 0116 PostgreSQL 离线 DDL **退出0**，
  `fixture-preparation-offline-ddl-20261013.log`。实际 Alembic 生成两表／FK／trigger SQL，
  revision `0116_fixture_preparations`，未连接 PG 或应用 migration。
- 新独立 PG 专项／migration collection **退出0：3 collected / 0.64秒**，
  `fixture-preparation-pg-collection-20261013.log`；不是实跑。
- 公共 PG/MinIO 原父链测试新增准备／绑定摘要、不可变记录及绑定前临时故障后同 ID
  恢复路径；PG专项／API测试／迁移语法检查退出0，**未运行实际集成**。

后续确认新协调标记不改变原 Agent 步骤的预算 work key，但仍计入完整输入摘要；
未知业务字段不因加入协调名单而被接受。原 command 校验同时收紧为空／布尔／控制
字符／过长确认人，双方同为非法值也不能取得 authority，追加五项原历史兼容拒绝契约。
补充预算查询最初误引用不存在的 `test_query_tools.py`，退出4、no tests ran，日志
`fixture-preparation-coordination-regression-20261013.log` 保留，不当作成功回归；正确
预算专项退出0：10 passed / 0.59秒，`fixture-preparation-build-budget-regression-20261013.log`。
包含上述最终变更、原扩大组及预算专项的当前最终组合 **83558退出0：978 passed /
19.90秒**，`fixture-preparation-current-final-contracts-20261013.log`。原961组保留为
前批证据，最终978同样不替代实际 PG／RPC、原生 exweb 或完整 V1。

新 PG 专项只在 owned `nasus_test_*` 数据库运行：并发独立 confirmation claim 只有一份
原准备、flush 后异常回滚 running／标记／回执、失败 Outbox 异常回滚 Tool／审计、
原准备 UPDATE／DELETE 及非空降级拒绝。新增公共链仍有明确 Runner／build／health／
Temporal 传输 doubles，不声称原生 exweb、真实权限批准、真实 Temporal 或性能门禁。

固定 exweb 缓存 HEAD 再核对为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，
porcelain 空，未更改原仓库、oracle、失败记录或分母。前次 35058 的 PG／MinIO 原集成
在准备阶段失败，精确 owned 资源仍待依赖恢复后清理，下节保留原证据。没有启动新的
全 V1／E2E／smoke，也没有最新 `verify:v1-release` 全绿证明。

绑定前授权只读／独立取消完整链、执行 Portal、真实 PG／Temporal 重启与取消、独立
unknown 恢复、step／case／oracle 到 coverage／release、五用途和旧链切换继续待交付。
自动增量、多 Provider／多语言独立 gold、安全／容量／灾备／性能和真实试点仍保留
完整 P0-P6 范围；本增量不定义为全目标完成。实际协议见[原命令关联](./http-fixture-command-provenance.md)。

## 公共 fixture 任务接线与终态竞态修复（2026-10-13）

上一解释回合核对数据关联，没有新增实现或改变下一实现动作，按 no progress 复核。
本轮基于实际 worktree 修复公开任务、planner 发现及 HTTP 错误分类，并补充契约与
待执行集成用例，属于 progress；完整 P0-P6 目标继续 active，不缩减为 fixture 专项。
Docker 当前 socket 不存在，`docker info` 退出 1；没有自动重启、执行开发 migration、
发送新模型请求或拉取/运行目标镜像。原大型验证进程检查未找到 live handle。

前一增量的 0114 原命令 fence 与 0115 追加式取消记录，现已从实际容器接线
`quality.http_fixture.execute / query.quality.http_fixture_execution / quality.http_fixture.cancel`、
原 ID Temporal workflow/activities/reconciler 与私有/no-store HTTP 只读入口。
精确原 grant、scope、actor、command/worker/consent pins 保留，先绑定再启动，取消先
写原 PG 事实再 RPC。reconciler 先投递取消，未知启动回执只重查同 ID，不新建 attempt。
完成必须重读完整原 archive，未知阶段不能 completed；所有原业务/基线 authority
仍 false。具体边界见[原命令契约](./http-fixture-command-provenance.md)。这不证明公共
原生链、真实 Temporal 重启/取消或完整 RunPlan 执行已经验收，执行 Portal 尚未交付。

扩大组原日志 `fixture-public-jobs-expanded-regression-20261013.log` 终态为
**1 failed / 879 passed / 17.64秒**，原 handle 丢失，不推断退出码。新 fixture 合同
在普通测试执行意图挤掉 `run.start`；现仅在明确 fixture/test-data 意图优先选择该组，
普通生成/执行/放行保持原合同，全量 ID、治理字段和 6999 字节限制未放宽。中英文
fixture 发现新增验证全部定义/许可/执行/读取/取消及独立确认字段。

新代码检查还发现 handler 收尾失败后会落入通用 failed 状态写入，可能覆盖已持久取消；
起始 running 通知同样是不必要的无锁写入。执行 handler 现只依赖 runtime 的原持久
claim，并调用原 repository 行锁终止；live lease/临时故障只能保留原命令，不退回
通用状态更新。测试覆盖取消中准备失败、终止故障、未知 Temporal ACK、权限拒绝与
静态脱敏日志。另拒绝 orphan dispatch binding 被解释为未派发，取消时间缺失/非法
统一 typed rejection，不补造确认或历史。

HTTP 只读专项初批 **68394退出1：7 failed / 179 passed / 3.44秒**，测试误把既有
`detail.error.code` envelope 写成 `detail.code`；日志
`fixture-job-delivery-http-regression-20261013.log` 保留。修正 envelope 后
**88539退出1：1 failed / 185 passed / 3.33秒**，真实复现
`StaleSourceAccessScope` 被通用 ValueError 转为 502，日志
`fixture-job-delivery-http-fixed-regression-20261013.log` 保留。现显式向外保留来源快照
变化，由原授权 mapper 返回 409；403/404/409/502/503 与 no-store/正文脱敏断言不改。

当前可核验终态：

- handler/planner/runtime/边界组 **88623退出0：345 passed / 3.81秒**，
  `fixture-job-handler-planner-regression-20261013.log`。
- 当前 fixture job/delivery/HTTP/原命令发现组 **71690退出0：186 passed / 3.36秒**，
  `fixture-job-delivery-http-final-regression-20261013.log`。
- 原命令/worker/consent/lease/原字节/权限/生成线程/Tool runtime/DDD/Portal 扩大组
  **50654退出0：917 passed / 18.18秒**，
  `fixture-public-jobs-current-final-regression-20261013.log`。这是完整所列契约组，不是
  全部 API、实际 PG/RPC、exweb 原生执行或完整 V1 门禁。
- Portal build **8890退出0**、lint **99203退出0**，
  `fixture-public-jobs-portal-build-20261013.log` / `fixture-public-jobs-portal-lint-20261013.log`；
  500kB chunk warning 保留，本轮未改页面视觉或增加执行 UI。
- 当前完整 Portal contracts **6681退出0：1161 passed / 7696.658ms**，
  `fixture-public-jobs-current-portal-contracts-20261013.log`；不替代浏览器视觉、实际
  公共 fixture UI 或 E2E/smoke。
- 0115 离线 PostgreSQL DDL 见 `fixture-job-cancellation-offline-ddl-20261013.log`，
  仅静态 SQL，不连接 PG、不执行 trigger。新增独立 migration collection **退出0：
  1 collected / 0.49秒**，`fixture-job-0115-collection-20261013.log`；仍未实跑 migration。

`test_http_fixture_execution_api.py` 已抽共享的完整 canonical 父链准备 fixture，在
保留原三条私有/原命令/取消测试断言之外，新增两条公共 ToolRuntime→真实 PG/MinIO
用例：确认前不派发、同请求不重发、原 grant/work 不得接管、原失败 oracle 保留、
独立 cleanup、持久取消/迟到失败不覆盖、取消表 UPDATE/DELETE 和非空降级拒绝。
它们仍使用明确 Runner/build/health/Temporal 传输 doubles，不是 exweb 或真实
Temporal 证据；当前仅语法检查通过，**未执行**。新增 0115 独立 schema up/down/up
与精确 FK/trigger/空库存测试同样未执行。前次 0114/API collection **23985退出2**，
默认 SQLite 遇 PG ARRAY 在导入 app.main 时失败，日志
`fixture-command-provenance-pg-collection-20261013.log`；不是收集成功、PG 执行证据或
SQLite 支持承诺，没有为绕过依赖改写数据库约定。待依赖恢复，用随机 owned
PostgreSQL/MinIO wrapper 实跑，不使用开发数据。

后续还需收敛未绑定 intent 的准备故障：当前失去可核验 selection/确认或 DB 时，
handler 只保留原状态而不无锁改写，pending 投递器只选已有 intent。格式非法或绑定
前的未知准备不能据此声称已自动完成/恢复；需要独立的原命令事务终止/准备投递协议，
仍不得借失败处理接管旧 work、补造 intent 或重发 unknown 目标请求。

前轮待核验结果也已读到终态：**90314退出0：1161 Portal contracts / 8439.365ms**，
`fixture-runtime-portal-all-fixed-contracts-20261013.log`；**91136退出0：108 passed /
13.08秒**，`worker-thread-generation-regression-contracts-20261013.log`。新增公开接线前
的原命令扩大组 **1140退出0：654 passed / 15.54秒**，
`fixture-command-current-regression-20261013.log`，不拿它们替代本轮公共链/端到端验证。

固定 exweb 当前 SHA 仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，porcelain 空；
未修改原仓库、业务 oracle 或失败分母。原 **35058退出1** 的 PG/MinIO 组装集成停于
binding 准备，尚未到 worker；其精确 owned DB/bucket 待依赖恢复后清理，见下节。
执行 Portal、真实 PG 锁竞争和 Temporal 重启、独立 unknown 恢复、真实 step/case/oracle
到 coverage/release、五用途与旧链切换、自动增量、多 Provider/多语言独立 gold、安全/
容量/灾备/性能和真实试点仍保留原完整范围；没有最新 `verify:v1-release` 全绿证明。

## 私有 fixture 执行组装与线程收尾（2026-10-13）

本节保留当时私有阶段的实现与验证；后续公开任务接线及最新边界见上节，不把当时
“无公开入口”作为当前代码结论，也不把后续契约通过倒写为本节真实集成成功。

本轮实际代码与测试推进 P5，完整 P0-P6 目标保持 active。原全量 98424 handle 已丢失，
原 shell37761/wrapper38151/backend38154 均不在进程表；原日志停在约37%且没有最终
summary，标记 stopped/incomplete，不继续宣称 live、退出码或完整 V1 绿色。

`HttpFixtureExecutionApplicationService` 现从原 native grant 解析固定 RunPlan、定义、
环境记录、操作和当前 actor/source scope，通过实际 infrastructure factory 连接原 PG
lease/ownership/consent、健康预检、MinIO 与 owned Runner。输入／创建／派发离开 event
loop，取消等待 owned thread 收尾；历史分支不申请新许可、不创建 lease 或 Runner。
服务已由生产 application container 组装，但没有公开执行 Tool/HTTP/Temporal/Portal，
所有 canonical/business-coverage/baseline authority 保持原 false。

组装专项原批 **283 passed/1 failed/24.62秒**，失败为前轮会话发送防竞态修复使 hook
超出已有分层约束。保留校验并抽成 `conversationMessageSender`，未放宽门禁或更改样式；
修复后 **41026退出0：284 passed/8.24秒**，
`http-fixture-worker-runtime-fixed-contracts-20261013.log`。8项原发送测试保持通过。

新检查发现共享 lease heartbeat/初始检查只取消 to_thread coroutine，可能在 lifecycle
返回后继续执行。有效复现 **47710退出1：6 failed/2.31秒**，
`worker-thread-lifecycle-valid-baseline-20261013.log`；更早测试错误地在 event loop 内
构造 fixture 的失败日志保留，不能当作有效生产复现。现统一 `run_worker_thread`，
重复取消仍等待线程结束；不延长租约、缓存权限或取消 PG fence。修复相关组
**76272退出0：78 passed/12.89秒**；实际 factory/严格环境 pin/来源撤回/只读历史/
DDD/Portal 扩大组 **80254退出0：355 passed/8.57秒**，
`http-fixture-runtime-thread-final-contracts-20261013.log`。这些是明确的 scheduling/port
specimens，不代替实际 PG、Temporal 或 exweb 目标证据。

新增 `test_http_fixture_execution_api.py` 消费完整 canonical 原父链和实际 container
服务，不替换父读取器，也不延长 PG lease。**35058退出1：1 failed/94.78秒**，
`http-fixture-composed-runtime-baseline-pg-20261013.log`；PostgreSQL 连接关闭、MinIO
拒绝连接、Docker socket 消失，测试停在 build binding 准备（63行），未到新 worker。
数据库/bucket 清理也因依赖停止失败，待恢复后仅清理本批所有的
`nasus_test_00d46e9e4af9415abdb087ed03602886` 与
`nasus-test-823f65894f5a489ead08998fbd48d7b2`，不触碰开发数据或其他测试 namespace。
尚未自动重启 Docker，不能以纯契约通过替代这批集成结果。

Portal build **16010退出0**、lint **85942退出0**，500kB chunk warning 保留；
当前5文件真实 hook/查询/只读入口/原 goal replay 组 **19745退出0：101 passed/2086.99ms**，
`conversation-sender-verified-broad-contracts-20261013.log`。前一错误地列出不存在文件的
Node 命令只实际执行8项，不能计为扩大组；日志保留。新的完整 Portal/生成回归结果待
同 handle 核验。本轮重新检查固定 exweb SHA 为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，检出干净；未修改原代码/oracle/失败证据。

前轮 audit read-model 与原回执错误分类修复，最终 PG 专项日志已记录
**25 passed/103.34秒**，`tool-receipt-audit-scope-current-fixed-pg-20261013.log`；
失去原 handle，未推断退出码。原8项失败的批次保留，不改写。浏览器原来源与保存入口
组 **70786退出0：16 passed/2.0分钟**，`tool-receipt-send-scope-current-browser-20261013.log`，
加载早于本轮 sender 抽取，不替代新 E2E。公开执行、实际覆盖回流到 release、五用途及
旧链切换、自动增量、Provider/多语言/gold、安全/容量/DR/性能和试点范围仍全部保留。

## 原构建回执的故障与拒绝分离（2026-10-13）

前一解释回合没有扩大实现；原完整验证 handle 98424 再次核验仍 live，属于 verified wait。
本轮对实际回执查询的修复和新增测试属于 progress，完整系统画像 P0-P6 保持 active。

工具／审计列表原本仅传播 502，其余校验异常可能变成 200 空列表或部分历史。
现在只有明确 403 可以过滤，409／422／500／502／503／504 继续中止整批。
原状态不可变、最后的新鲜来源 cohort 校验及权限撤回语义不变；不执行工具或修复历史。
20项 application specimens 的有效基线为 **16 failed/4 passed/0.37秒**，
`tool-receipt-list-failure-baseline-20261013.log`；最初扩大组89项通过记录保留。
真实 PG／私有 MinIO 的列表故障、缺失授权 reader、恢复及既有撤权／请求解析组
**92242退出0：40 passed/161.41秒**，`tool-receipt-list-failure-current-pg-20261013.log`。
其中新增8项注入 verifier 故障，不将其当作原生 Provider 或 exweb 执行。

七个画像权限预过滤器还会吞掉异常，早于最终校验就把记录隐藏。现在复用 application
错误分类：明确撤权／未建立可读范围仍不可见；损坏的已完成合同返回脱敏502，服务不可用
返回脱敏503，明确平台冲突继续传播。补源修订和阶段回执必须保留唯一原 ledger、检查点、
来源／前驱及完整结果引用，缺失、重复或替换均拒绝，不能借另一个有效记录回放。
63项最初调度契约基线 **42 failed/21 passed/0.56秒**，
`invocation-resource-policy-failure-baseline-20261013.log`；初次错误分类遗漏
`BuildPlanIntegrityError` 的 RuntimeError 基类导致7项失败，已明确分类，未降低预期。
新增 malformed-attempt 和22项原 ledger／结果篡改检查后，完整纯 application／DDD／边界组
**40717退出0：464 passed/4.61秒**，`tool-receipt-faults-final-reviewed-contracts-20261013.log`。
这些使用严格 DTO 和显式 port doubles，不代替真实 PG、Temporal 或原生执行证据。

早于上述预过滤器修改加载的真实构建入口组 **11499退出0：33 passed/270.70秒**，
`image-build-entry-receipts-current-pg-20261013.log`；真实 Temporal 原目标恢复组
**62032退出0：4 passed/199.66秒**，`image-build-entry-receipts-temporal-20261013.log`。
它们核验同目标、来源、独立确认及 Worker/Activity 恢复，不证明新错误分类已在 Temporal
全链复核。新加载 PG／HTTP 的预过滤、入口、补源和阶段回归仍在运行且已有失败，
`image-receipt-prefilter-current-pg-20261013.log`；最终明细待核验，不写全绿。

Portal build **29597退出0**、lint **57674退出0**，对应
`tool-receipt-reviewed-portal-build-20261013.log`、`tool-receipt-reviewed-portal-lint-20261013.log`。
大于500kB chunk warning 保留，未改前端样式，不代替浏览器验收。固定 exweb HEAD 再核对为
`fe5827f6b76f77ef34918d8b452ee823142332dc` 且干净；未改原代码、oracle、失败记录、
开发库或服务。正式 fixture Tool/Temporal/Portal、真实覆盖／release、五用途与旧链切换、
自动增量、多 Provider/语言与独立 gold、安全／容量／DR／性能和试点仍需完成。

## 画像读取作用域的任务与线程隔离（2026-10-13）

前轮原 handle 仍 live；本轮先恢复 **26661退出0：1 passed/1237.31秒**，
`http-fixture-work-clock-original-journal-pg-20261012.log`。它验证真实 PG/私有 MinIO、
完整 canonical 原父链与 journal 原失败/未知效果/事务约束，Runner 与 worker frozen reader
仍是显式 specimens，不宣称 exweb 业务执行。随后代码修复属于 progress，完整目标保持 active。

检查 Worker 接线时发现画像 MVCC/provenance snapshot、画像原字节校验缓存与 evidence
manifest 缓存原先只靠 `ContextVar` 标记，可被子 task/线程复制或在作用域结束后继续使用。
SQLAlchemy `Session.close()` 不能阻止旧 Session 重新开启事务。新增 application 级
`OperationReadScope`，已经接入上述实际读取路径：仅原 task/thread 且未关闭时可使用；
仓储另要求当前全局 snapshot 与本仓储原 Session 相同。子任务必须独立读取，取消只关闭
自己的资源，PG snapshot 关闭标记先于 rollback/close，嵌套 scope 退出恢复原父 scope。
仍逐次检查当前来源权限/authority/head；不增加跨操作 proof/ACL cache、不延长 lease，
也未用该安全修复宣称解决原父链39秒读取或正式执行的性能缺口。

调度回归有效基线 **72159退出1：10 failed/1 passed/0.93秒**，
`image-read-execution-scope-baseline-20261012.log`。新增18项 scheduling specimens 覆盖
线程/task/延迟 context、局部复用与原字节副本、撤权、归档缺失及子任务取消；manifest
transport 为显式 double。扩大 application/provenance/DDD 组最终复核
**97076退出0：206 passed/3.02秒**，`image-read-execution-scope-final-reviewed-contracts-20261013.log`。
此前99038同范围206 passed/2.83秒的日志保留。真实 PG snapshot/pool 组
**3104退出0：14 passed/5.31秒**，`image-read-execution-scope-pg-20261012.log`，包含4项
新增真实任务/线程/关闭/取消场景，核验独立 backend/session、READ ONLY/REPEATABLE READ。

PG/HTTP 原证据、实时 AC/来源撤回、当前 publication 与 canonical 构建回放组最初
**98381退出1：1 failed/19 passed/51.33秒**；旧测试误将独立撤回 HTTP 命令的 artifact
读取算进父 compiler cache。现断言父操作读取1次、独立 HTTP 命令另读1次、下一独立操作
再读1次，同时保留 oracle 撤回、blocked 与事实写入0要求，不放宽生产权限。
修正后 **68772退出0：20 passed/50.06秒**，
`image-read-execution-scope-canonical-fixed-pg-20261012.log`。完整 context/publication/image
query HTTP 组 **51531退出0：24 passed/205.95秒**，
`image-read-execution-scope-context-http-pg-20261012.log`，包括失效/撤权、原归档、幂等保存、
Outbox 回滚、publication 动态 head、追加式历史和安全 query receipt。
真实 Temporal/PG/私有 MinIO 原结果提交后重试组 **18988退出0：1 passed/27.67秒**，
`image-read-execution-scope-temporal-pg-20261012.log`；Builder 为 ProtocolBuilder，非真实 Java。

Portal build **29859退出0**、lint **29047退出0**，大于500kB chunk warning 保留；smoke
**71895退出0：success**。浏览器原证据/来源受限/深浅主题组 **13149退出0：7 passed/26.7秒**，
`image-read-execution-scope-evidence-browser-20261012.log`，实际来源采集/HTTP/DOM，不当作
exweb native 执行。日志名20261012保留跨午夜开始时的标记。本轮固定 exweb SHA 再核对为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，原检出干净；未修改原代码/oracle/失败记录。
未改开发库、重启服务、commit/push。全量 **98424** 经原 handle 再核对仍 live、后端约29%，
已有失败标记且无最终明细；该批加载早于本轮修复，不宣称完整 V1 绿色。
正式 fixture Tool/Temporal/Portal、实际覆盖到 release、五用途与旧链切换、增量、多语言
Provider 对照、独立 gold、安全/容量/DR/性能与试点仍在原完整 P0-P6 范围内。

## 原生执行租约与异步检查修复（2026-10-12）

本轮 revalidate 原全量门禁后修复实际 worker 生命周期，属于 progress；完整 P0-P6
仍 active，不以本轮专项替代 canonical fixture 派发或系统画像完整验收。

`PostgresHttpFixtureWorkRepository.acquire` 原先在末次完整输入/权限检查之前记录
PG 时间，慢校验可使返回的租约已到期；`renew` 同样过早记时，且未检查原期限是否在
慢校验期间到期。现在先完成原锁事务内的完整校验，类型敏感比对两次 parent pin，
再读取 PG clock 写入租约；续租在慢检查后重验原 owner/epoch/期限，拒绝复活过期 owner。
90秒 lease、15秒 heartbeat、原 ACL/父链/许可/事务 fence 不变，无权限缓存或未知效果重发。

真实 PG 时钟回归基线 **7 failed/2 passed/6.85秒**，
`http-fixture-work-clock-baseline-pg-20261012.log`；修复后的时钟/worker/空迁移组
**50379退出0：43 passed/7.59秒**，`http-fixture-work-clock-fixed-pg-20261012.log`。
新增9项使用隔离 `nasus_test_*` 私有 schema、实际 PG clock/pg_sleep/事务/0109 trigger/FK，
覆盖慢校验、到期续租、撤权回滚与 parent 换绑。最小 parent/ACL 明确是 specimens，
不证明完整原 RunPlan、source ACL、exweb native 运行或业务覆盖。最初未设置测试 URL 的
启动在迁移前安全退出，`http-fixture-work-clock-before-20261012.log` 不是测试结果。

原生构建 async application/Job 原本在 event loop 直接执行同步 scope、lease/authority、
policy、来源与 JAR 摘要，可能拖延 Temporal heartbeat/取消。现用 `asyncio.to_thread`，
保留 ContextVar 身份、校验顺序和同事务 commit fence；原结果只回读、未知 reservation
不重建、builder 取消必须等待 owned cleanup 的约束不变。新 scheduling specimen 最初
缺少角色字段（保留 `native-build-async-guards-before-20261012.log`），修正替身后、未改
生产代码前的有效基线 **8 failed/2 passed/0.88秒**，
`native-build-async-guards-baseline-20261012.log`。最终 application/child-process/边界组
**45564退出0：257 passed/5.16秒**，`native-build-async-guards-final-contracts-20261012.log`。
新增14项验证慢 guard、线程身份、取消/撤权不进入下一副作用与不重建，不冒充 PG/Java 验收。

真实 PG/私有 MinIO canonical 构建/未知效果组 **71806退出0：2 passed/14.20秒**，
`native-build-async-guards-canonical-pg-20261012.log`；真实 Temporal 重试和 PG 取消/晚撤权/
已归档恢复组 **14605退出0：4 passed/47.76秒**，
`native-build-async-guards-temporal-cancellation-pg-20261012.log`。后者实际回放 Temporal
history，原结果提交后重试不再构建。Builder 仍为明确 ProtocolBuilder，不当成 exweb
Java 编译或业务通过。完整原父链/PG journal 组 **26661** 已启动，
`http-fixture-work-clock-original-journal-pg-20261012.log`，终态待核验，不写通过。

Portal build **31855退出0**、lint **31982退出0**，日志分别为
`native-worker-lifecycle-portal-build-20261012.log`、`native-worker-lifecycle-portal-lint-20261012.log`。
保留大于500kB的 chunk warning；未改前端样式，不把构建/lint 当作浏览器或完整发布验收。

全量 **98424** 的 shell37761/backend wrapper38151 仍实际 live，
`system-image-audit-preflight-full-v1-20261012.log` 后端约12%已出现至少一项失败，
最终明细未输出，不重启或宣称绿色。该进程在本轮代码/测试之前加载，不能替代本轮专项。
exweb HEAD 仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc` 且干净；未改原仓/计划/oracle/
失败记录、开发数据库或外部组件，未重启开发服务、commit/push。正式 fixture Tool/Temporal/
Portal、真实覆盖到 release、五用途/旧链切换、自动增量、独立 gold、多 Provider/语言、
安全/容量/DR/性能及试点仍未全部交付。

## 原生派发前检查与审计兼容修复（2026-10-12）

上一轮已推进原生 preflight 与读取契约，属于 progress。本轮首先恢复原 handle 的
终态及实际报告，再修复 PG 回归失败；完整 P0-P6 保持 active，不缩减为测试夹具交付。

**56577 退出0：1 passed/4908.31 秒（81分48秒）**，
`exweb-native-fixture-live-preflight-pg-20261012.log`。报告
`output/exweb-native-fixture-live-preflight-20261012.json` 实际核验固定提交
`fe5827f6b76f77ef34918d8b452ee823142332dc` 的全部126个原 blob、原构建 JAR、实际
隔离 PG/Redis/目标容器与私有 MinIO。当前健康实例可通过派发前检查；停止原 Redis、
重启同一容器后旧 inventory 均被拒绝；worker callback 失效先于 Docker；历史回读不做
live probe，journal 数为0，owned 资源清理后剩余为0。重启测试没有等待新实例完全健康，
不能单凭它声称已经单独证明“健康新 epoch”的拒绝分支，纯 identity 契约另行覆盖。
`fixture_commands_executed=0`，模型/调度/业务 oracle/worker fence 均有明确 specimen 边界，
`execution_authorized/business_coverage_verified/full_quality_closure_verified=false`；
不能将健康、预检或这项测试的 passed 当作 exweb 业务用例执行通过。

原 **10868 退出0：1 passed/1718.03 秒**，
`http-fixture-native-live-preflight-pg-20261012.log`；真实 PG/MinIO 与完整 canonical
父链，code/build/model/Docker 仍为 protocol specimens。缺失/不健康 health port 先于
PG claim 拒绝，不能替代上面的实际原生验证或正式 Tool/Temporal 派发。

正式 `NativeSavedRunPlanHttpFixtureAccess.require_dispatch` 在 journal 写事务前验证
完整原计划、当前输入、原 completed 环境记录、确切 JAR/inventory、当前健康及 worker
callback；缺少 health port 拒绝。使用现有 application health port、防腐 DTO 与
type-sensitive hash；前后重新校验原父链及权限，不缓存 ACL。历史 inspect/complete 不因
依赖停机而发起 Docker 检查。journal 仍另行核验原 manifest steps、原许可与同事务
worker/PG 时限；preflight 本身既不是授权，也不代替 Runner 请求前后的实际检查。

原 **27019 退出0：1 passed/3287.17 秒**，原父链读取报告已核验：同完整响应与
24个不同原对象/字节摘要，业务事实写入0；77.237082秒 → 38.991646秒，2714 → 1358
次对象读取，19,598,257 → 10,601,711 字节，14,834 → 7,462 条 business SQL。
重复展开中的授权查询随之减少，各次实际检查仍重新执行；每侧 live connection 借还1次、
rollback1次、commit0次。详见[测量记录](./context-read-performance.md)。只有一对本机
control→production，不是p95/Linux/容量验收，39秒仍明显不合格。

旧完整 V1 **83865 退出1：50 failed/6467 passed/88 skipped/3 warnings/34114.67秒**，
`agent-catalog-v3-release-guidance-full-v1-20261011.log`。原失败报告保留。新加载旧失败
第一组 **2 failed/113 passed/1 warning/509.90秒**，两项为语义输入测试仍假定嵌套
snapshot；生产 reader 已按操作复用不可变证明。测试改为核验共同 scope、每份 excerpt
的实时授权、错误路径退出与下一操作重新验证，不改生产权限策略；纯专项 **47 passed/
0.97秒**，扩大 preflight/health/DDD 组 **266 passed/4.49秒**。

**57586 退出1：8 failed/10 passed/1 skipped/1590.62秒**，
`system-image-full-v1-failure-rechecks-pg-20261012.log`。原因逐项保留：旧迁移回放受
新增环境/自动化 provenance 外键约束；审计 DTO 未接受 RunPlan `prepared` 等实际事实
状态；两项测试还要求泄露已损坏/不完整父链的原 receipt。生产 AuditEvent 明确接受
reviewed/prepared/build_attested/recorded/issued/reserved 及 Runner passed/error/timed_out
状态，保留原历史值、严格 Literal 与零授权 metadata，不将事实状态归一为 completed。
新增未知/非字符串拒绝与真实 PG 持久化回读测试。旧迁移回放只在 rollback-only 隔离 PG
事务中显式拆后续 FK，回滚后要求完整 FK inventory 恢复；不改生产 FK、trigger 或 downgrade
guard。损坏父链 direct read 仍抛 domain integrity，平台 receipt 返回安全502，缺失代码来源
不得保存绑定或写工件。generation reconcile 测试补105条显式 transport pending 记录，
要求全部稳定分页、不跳过第100条后的原任务；生产分页逻辑未改。

本轮纯契约 **1371 退出0：204 passed/4.32秒**，
`system-image-audit-preflight-final-contracts-20261012.log`。build **64847 退出0**（chunk
warning 保留）、lint **34753 退出0**；smoke **54109 退出0：smoke success**。RunPlan
浏览器 **69969 退出0：2 passed/1.8分钟**，
`system-image-audit-preflight-runplan-browser-20261012.log`，来源实际采集、深浅主题／原完整
计划／失联回读／刷新 pin 不变；其他模型/登记 transport 为显式 fixture，不是原生执行。
新加载 PG **53034 退出1：1 failed/22 passed/1 skipped/2539.36秒（42分19秒）**，
`system-image-audit-migration-build-rechecks-pg-20261012.log`。审计事实状态、完整历史原外键、
RunPlan 绑定正常/过期/Outbox故障/撤回及损坏原构建拒绝、三项迁移、mapping/scope审计均通过。
唯一失败为本轮缺来源拒绝测试误读平台统一错误包的 `detail`：全局 handler 实际返回根级
`error`（502），不是 HTTPException 的 detail。修正为确切根级 code/request_id 和无正文
泄漏断言，再单独复验；不修改生产 handler 或放宽原来源完整性。
该专项新加载 **38177 退出0：1 passed/435.76秒（7分15秒）**，
`system-image-multisource-original-build-binding-final-pg-20261012.log`。确切502、完整原代码来源
必要性、失败零工件/绑定/成员、正常请求成功保存两个原 source/build pins 均通过；构建器
是明确 ProtocolBuilder，不是实际 exweb JAR 或目标执行。
独立迁移复验 **14025 退出0：7 passed/47.60秒**，
`system-image-original-provenance-migration-rechecks-pg-20261012.log`，包含 populated
0067→0068、0071完整回填、坏 query scope 的原子回滚及 rehearsal 的实际 PG FK 恢复。
它不证明仍在执行的原构建绑定组合或完整 V1 全绿。
迁移 helper 后续增加 DDL 前的隔离库检查，明确拒绝非 PG/无事务/非 `nasus_test_*`，
不触及开发库。新纯 guard/status 组 **22 passed/0.30秒**，
`system-image-audit-migration-guard-contracts-20261012.log`；新加载实际 PG helper
**36855 退出0：4 passed/1.38秒**，`system-image-isolated-migration-rehearsal-guard-pg-20261012.log`。
53034/14025 在此 guard 修改前已加载 helper，不用它们替代新增 guard 的测试证据。
Portal contract **68691 退出0：1153 passed/9.14秒**；Portal boundary **25 passed/0.23秒**，
i18n gate 退出0，分别见 `system-image-audit-preflight-portal-contracts-20261012.log`、
`system-image-audit-preflight-portal-boundaries-20261012.log`、`system-image-audit-preflight-portal-i18n-20261012.log`。
tracked 与本轮修改的 untracked 测试 whitespace 检查均无错误。

在上述原失败专项取得终态后，新加载完整 `npm run verify:v1-release` **98424** 已启动，
`system-image-audit-preflight-full-v1-20261012.log`。最新原 handle still running，实际
shell37761／backend wrapper38151 已确认 live，已进入隔离 PG/MinIO 后端组；此前门禁步骤
未阻断。旧83865失败不抹除，新全量结束前不写“V1通过”。不得只因观察超时重启该批。

exweb 原检出 HEAD/干净状态重新核验；未改原仓、旧计划、原 oracle 或失败报告，未迁移
开发库、未手动重启开发服务、未 commit/push。尚无当前完整 V1 全绿证据。正式 Tool/Temporal
派发/取消/未知恢复、真实 case-step-oracle 到 release、五用途/旧链切换、自动 delta/overlay/
CAS merge、多语言 Provider 与独立 gold、安全容量/DR/性能及授权试点仍在完整目标内。

## 原父链读取优化与原生环境篡改复验（2026-10-12）

上一轮数据关系回答是只读说明，属于 no progress。本轮恢复原 live handles，继续交付
完整 P0-P6，属于 progress；不以关联契约或测试夹具替代实际系统画像／exweb 业务验收。

原原生专项 **90758 已退出1：1 failed/1472.50 秒**，
`http-fixture-native-grants-explicit-protocol-pg-20261012.log`。missing-result 反例已返回502，
bool→int 反例却返回200：ORM 以 Python JSON 相等判定 True 与1，没有实际执行更新。
改为显式 SQL UPDATE，并从新的 PG session 核对持久摘要／整数类型；恢复同样显式 SQL，
回读原 bool／摘要。生产 completed 环境回执 gate 不放宽，原工件／oracle／v1 bytes 不改写。

正式 reader 消除一处重复原 RunPlan 展开：fixture `read_with_plan` 返回本次完整验证的原父
对象，grant 再核对其原项目／ID／hash；普通接口不扩充返回字段。RunPlan 完整读取／编译复用
已有 live read-only connection，grant `require_operation` 将全部当前输入、原许可和最终 ACL
检查置于操作级作用域。只复用连接及原有操作内不可变证明，不缓存权限、review/publication
head 或跨请求内容，不延长900秒许可。详细约束见[固定读取测量](./context-read-performance.md)。

基础新测试 **16572 退出0：294 passed/6.88 秒**；增加完整 RunPlan 作用域与错误路径后
**21964 退出0：303 passed/6.84 秒**。扩大 fixture／RunPlan／环境／索引读取／DDD 回归
**14378 退出0：600 passed/13.91 秒**，`http-fixture-parent-reuse-expanded-contracts-20261012.log`。
这些是 domain/application/transport specimens，不替代真实 PG。诊断纯测试初批 **59547
退出2：collection error**，helper 的 eager main import 触发旧默认 SQLite 初始化。改为仅
真实 opt-in 测量时解析 app，纯测试显式注入 service port；没有将 SQLite 作为有效验证库。
复验直接完成 **退出0：37 passed/0.64 秒**，
`http-fixture-parent-probe-lazy-port-contracts-20261012.log`，仅测试诊断 control-flow／统计契约，
不是实际读取对照。
包含该诊断的最终扩大契约 **82197 退出0：605 passed/12.59 秒**，
`http-fixture-parent-reuse-final-contracts-20261012.log`。tracked whitespace 退出0；本轮涉及的
继承 untracked application／诊断模块另用 no-index check 核验，无 whitespace 输出，不能
从 tracked 空 diffstat 推断本轮没有实现。

新加载隔离 PG／MinIO **44317 退出0：179 passed/1 warning/461.50 秒**，
`http-fixture-parent-reuse-runtime-acl-pg-20261012.log`，包括 API/runtime/Compose 和实际读取中
来源／角色撤回、live connection pool 的配置／延迟／跨线程行为。Portal build **28479 退出0**
（>500KB chunk warning 保留）、lint **45367 退出0**；未修改生产 Portal。
固定 exweb source 的 RunPlan 深浅色浏览器 **99154 退出0：2 passed/5.9m**，
`http-fixture-parent-reuse-runplan-browser-20261012.log`。其中来源采集实际，计划/脚本/登记等
浏览器 transport 是明确 fixture，不是原生业务执行。隔离 smoke **83855 退出0：smoke success**，
`http-fixture-parent-reuse-smoke-20261012.log`；没有手动重启或迁移开发服务。

原源派发许可 **52919 已退出0：1 passed/2764.99 秒**，
`exweb-http-fixture-dispatch-consent-fresh-phase-pg-20261012.log`，加载于本轮 reader 优化之前。
真实原126 blob／PG／MinIO以及独立许可／worker／journal事务校验保留；phase 使用 frozen plan
reader 和 protocol Runner，不是当前 production Tool/Temporal 派发、实际目标通过或性能门禁。
原源历史／时限复验 **35635 已退出0：1 passed/4919.11 秒**，
`exweb-http-fixture-grants-history-expiry-pg-20261012.log`，加载于 reader 优化之前。其正向
live interval／完整历史／PG clock 分支实际通过；82分钟总耗时不作为可接受开发／生产性能。

原生环境关联新批 **67137 已退出0：1 passed/1285.53 秒**，
`http-fixture-native-parent-reuse-pg-20261012.log`，加载当前 production reader 和显式 SQL
篡改／恢复，四类原 completed environment result 损坏均被拒绝，原 immutable FK／trigger／
事务 fault rollback 保留。code/model/build/Docker 仍为明确 protocol specimen，不是实际
exweb 业务。诊断输出环境变量最初使用 `NASUS_` 前缀，被隔离 wrapper 过滤；没有测量报告，
不把该批耗时变化或纯计数当成对照结果。

在35635确认为终态后，新加载当前 reader 的固定 exweb 原源对照 **27019** 已启动，
`exweb-http-fixture-original-parent-read-comparison-pg-20261012.log`。使用未被过滤的
`FIXTURE_PARENT_READ_REPORT`，预期报告为
`output/exweb-http-fixture-original-parent-read-comparison-20261012.json`。必须核验实际报告和
原 handle 的终态后才登记数值；这仍是一对本机历史 HTTP 读取，不能替代p95／Linux容量门禁。
最新原 handle 仍 running，wrapper17996／pytest18005 已确认 live，约8分钟；未因观察超时
重启或提前计为通过。旧完整V1 wrapper81668／pytest81670同样仍 live，约8小时，原失败
标记保留；没有当前完整门禁终态。

旧完整 V1 **83865** 仍 live、有失败标记，加载早于0110-0113和本轮优化，没有最新完整 V1
全绿证据。原 exweb clone HEAD 仍 `fe5827f6b76f77ef34918d8b452ee823142332dc`、工作树干净；
未改 exweb、native 失败报告或业务 oracle，未 commit/push。当前 progress 不消除 production
Tool/Temporal 真派发／实时preflight／取消／未知恢复、真实逐case/step/oracle覆盖到release、
五用途／旧链切换、自动delta／overlay／合并、多语言Provider／独立gold、安全容量／DR／性能
及授权试点的剩余要求。goal 仍 active，完整目标不缩减。

## HTTP fixture 原生实例关联与派发契约复核（2026-10-12）

上一轮数据关系答复是只读说明，未改变交付状态；本轮重新核验原进程并继续实现，
属于 progress。0112 的[派发许可消费](./http-fixture-dispatch-consents.md)保留独立
worker/claim/PG 时限、严格类型和原项目/原 scope 的事务约束。现新增 0113 的
[显式原生环境关联](./http-fixture-native-targets.md)：operator policy 与 actual instance
inventory 分离，原 completed 环境记录/hash、完整回执、原计划/画像/清单/JAR 和
五字段复合 FK 固定。grant/关联/审计/Outbox 同事务，旧 v1 字节与已保存计划不改写。
原生 SavedPlan access 回读原环境记录编译 scope；它不是实时 preflight 或新生产派发。

恢复上一批终态：`http-fixture-dispatch-consent-migration-regression-fixed-20261012.log`
显示 **174 passed/1 warning/381.95 秒**，原 **77415** handle 已不可用且进程不在；
这里只记日志终态，不编造 tool exit code。**11693 退出0：368 passed/7.76 秒**，
`http-fixture-dispatch-consent-orphan-final-contracts-20261012.log`。
原 **77735 已退出0：1 passed/1451.83 秒**，
`http-fixture-grants-owned-parent-pg-final-20261012.log`；原 **5465 已退出0：2 passed/
6.8m**，`http-fixture-grants-runplan-browser-20261012.log`。下面历史段落记载的 live
状态不再作为这两批当前状态。这些批分别加载 0111/0112，不能证明 0113 原生目标。

0113 初纯检查 **30334 退出0：321 passed/8.62 秒**。扩大 repository 覆盖的
**46729 退出1：7 failed/486 passed/12.94 秒**，七项均来自旧显式 Session double
未识别新增关联表；只补充 legacy 查询返回 None，不移除 production 降级检查。
新增注册测试后的 `http-fixture-native-grants-repository-contracts-20261012.log`
终态 **9 failed/493 passed/13.36 秒**：撤权断言被错误放进已有 grant 的注册测试。
移回独立撤权测试，**85526 退出0：502 passed/12.22 秒**。之后新增原环境 completed
回执的 type-sensitive 校验与缺失/改写反例，**8497 退出0：512 passed/12.37 秒**。
工具目录说明显式 v2 输入且不增加/减少 Tool ID；追加计划/catalog 回归的
**65771 退出0：587 passed/16.25 秒**，
`http-fixture-native-grants-final-contracts-20261012.log`。这些是纯契约，SQL/原环境
parent verifier doubles 不能算真实 PG 或原生 Docker。

隔离 PG/MinIO 初原生关联专项 **49480 退出1：1 failed/144.83 秒**：新测试错误
假定只有一个 fixture，而原审阅实际有四个 case。helper 保存前为所有原 case 生成
各自 manifest/hash，不删减用例。复验 **36505 退出1：1 failed/151.54 秒**：测试
选择 v2 HTTP 脚本却声明 v1 RunPlan，生产校验正确返回409。专项在保存前显式声明
v2，保留全部原 case/步骤/oracle 和原生产策略；没有改写已有记录。
当前专项 **90758**（`http-fixture-native-grants-explicit-protocol-pg-20261012.log`）
已启动并确认 live，尚无终态；含原环境回执 SQL 篡改/恢复、late Outbox rollback、
private bytes/原五字段 FK/trigger/populated downgrade 及独立 cleanup。模型/构建/
Docker 仍是明确 protocol specimen，不是 exweb 原生业务。

原生迁移/API/runtime/Compose 初批 **85910 退出1：1 failed/173 passed/1 warning/
420.81 秒**：empty migration test 的 search_path 使0105重放给公共父表重复添加
约束。0113 fresh head 迁移成功；修复仅为临时 schema 复制环境父表列/checks，再
迁移新 fixture 链，不修改公共或开发父表。复验 **32156 退出0：174 passed/1 warning/
433.80 秒**，`http-fixture-native-grants-migration-regression-fixed-20261012.log`。
它在新增原 completed 环境回执检查前已加载，不将其当成该 gate 的验证。

本轮 Portal build **80070 退出0**（1.259MB/>500KB 告警保留）、lint **85892 退出0**，
`http-fixture-native-grants-portal-{build,lint}-20261012.log`。Portal contracts **48731
退出0：1153 passed/10.92 秒**，boundaries **52448 退出0：25 passed/0.59 秒**；
隔离 smoke **92249 退出0：smoke success**，对应
`http-fixture-native-grants-{portal-contracts,portal-boundaries,smoke}-20261012.log`。
本轮未修改生产 Portal；没有新的完整 E2E 终态，不以纯/UI smoke 替代原生业务。

固定 exweb 原源许可 **50342 已退出1：1 failed/4467.08 秒**，
`exweb-http-fixture-grants-canonical-pg-20261012.log`：正向 live 检查已通过，后续
大量历史/Agent回读及 SQL 篡改恢复后却再次断言原许可仍未到期。把 PG 原时间区间
断言移到原正向 live 检查旁，保留完整历史/过期/损坏检查，不续期、不删除原断言。
复验 **35635**（`exweb-http-fixture-grants-history-expiry-pg-20261012.log`）已启动；
终态待原 handle 核验，不能提前称通过。

原 scope 消费 **98438 已退出1：1 failed/2047.09 秒**，
`exweb-http-fixture-dispatch-consent-pg-20261012.log`：提前签发 setup/cleanup，再
完整原源回读使 setup 在派发前已过期，生产 gate 正确拒绝。测试移到签发前核验
完整原源、将 cleanup 独立确认放到准备完成后清理前；仍使用 PG 当前原时钟/900 秒，
无延长或 frozen clock。复验 **52919**
（`exweb-http-fixture-dispatch-consent-fresh-phase-pg-20261012.log`）已启动，终态待核验。
原批加载0111/0112，复验加载当前0113；都保留126个真实 Git blob/PG/MinIO完整
父链和明确 frozen reader/protocol Runner，不是当前原生目标业务派发或性能验收。
原回读40–86秒、canonical确认500余秒和整批34/74分钟暴露实际延迟，完整性能门禁
未达成；不能通过改测试时限或“只执行必需 gate”声称性能已达标。

旧完整 V1 **83865** 仍 live，最新约69%并有失败标记，加载早于0110-0113；无最新
完整 V1 全绿证据，也没有重启该批。

原 clone HEAD 仍 `fe5827f6b76f77ef34918d8b452ee823142332dc`，工作树干净；未修改
exweb、native失败报告、业务 oracle、开发数据库或手动重启服务；未 commit/push。
tracked whitespace check 退出0，新增 untracked 模块另行核验，不从空 diffstat 推断
未实现。goal 仍 active：production Tool/Temporal真派发/实时preflight/取消/未知恢复、
实际逐 case/step/oracle 覆盖到release、五用途/旧链切换、自动delta/overlay/合并、
多语言Provider/gold、完整安全容量/DR/性能/试点和全部P0-P6要求不缩减。

## HTTP fixture 独立操作许可（2026-10-12）

上一 goal turn 为 progress：登记 Portal 与原 PG/MinIO 父链已有终态证据。本轮推进
P5 的[独立准备/清理许可](./http-fixture-grants.md)，不是将登记/管理员/worker 租约
升级为派发批准。0111 固定原定义/attempt/case/计划/target/build/inventory/timeout 与
确认人，setup 和 cleanup 单独 canonical user_confirm；只允许当前项目管理员。
PG 原时钟签发 900 秒，原命令重放不续期，同 attempt 不换输入/确认人；许可、审计和
不透明 Outbox 同事务，复合 FK 与不可变触发器/拒绝 populated downgrade 保留历史。
原私有定义重新核验、历史 HTTP/query/Agent、receipt access 和脱敏 SSE 已接线。
completed 原命令的确切回执损坏或 bool/int 替换不能被 live 检查接受；该 gate 不代替
实时原目标、worker fence 和 journal claim，尚未在 production 派发事务中消费。

初纯测试 **43538 退出1：33 passed/1 failed**，digest 异常未转为本域错误；转换后
**81305 退出0：292 passed/6.14 秒**。补充完整 scope 重算篡改、源撤权、非 owned 地址、
completed 回执、半开时间区间后 **32185 退出0：316 passed/5.78 秒**。
最后修正每 attempt 上限的新增边界（已有 128 条不能再新增第 129 条）并复验，
**22548 退出0：316 passed/6.15 秒**，
`http-fixture-grants-final-budget-contracts-20261012.log`。其中 repository clock/session
是明确 double，不将其当成真实 PG 或实际等待 15 分钟。

隔离 PG/MinIO 的 0111 empty migration 往返、API/runtime/Compose 回归 **88764 退出0：
173 passed/1 warning/351.93 秒**，`http-fixture-grants-api-migration-regression-20261012.log`；
没有迁移开发库。Portal build **20949 退出0**（1.26MB/>500KB 告警保留）、lint
**5998 退出0**；全部 Portal contracts **85220 退出0：1153 passed/9.59 秒**。
当前 smoke **77734 退出0：smoke success**，`http-fixture-grants-smoke-20261012.log`，
使用临时 PG/MinIO/本机 API 和 Portal，清理私有服务；不代表独立授权 UI 或真实目标执行。

完整原 canonical PG/MinIO 许可首批 **40320 退出1：1 failed/351.23 秒**，
`http-fixture-grants-real-parent-pg-20261012.log`。新专项沿用了旧 protocol plan 的
19876 端口声明，而受控 fixture 仅接受原保存计划的 127.0.0.1:8080，故确认回执
正确地拒绝，未到 late Outbox fault。新测试计划创建前显式声明 owned protocol 地址，
保留 unverified target、原业务 oracle、失败返回与生产限制，并新增四类其他地址拒绝
测试；不重写任何旧已保存计划。独立复验 **77735** 正在执行
`http-fixture-grants-owned-parent-pg-final-20261012.log`，其进程/handle 已确认 live，
尚无终态，不能计为通过。该批加载了 completed 原回执/SQL clock expiry 检查；之后的
128 条新增边界收紧未在该已加载进程里重新加载，其普通两许可路径不验证耗尽上限。

另启动固定 exweb 源专项 **50342**，
`exweb-http-fixture-grants-canonical-pg-20261012.log`：真实 126 Git blob/PG/MinIO 原父链
及完整原字节核验，LLM transport 和业务 oracle 仍是明确 protocol specimen，未启动
exweb HTTP/Runner。进程已确认 live、尚无终态；新增例子不是原生业务 gold。现有原
RunPlan 浏览器回归 **5465**（API18090/Portal14180、固定 exweb source）也 live，
`http-fixture-grants-runplan-browser-20261012.log`；未新增授权 UI，不把协议回归算为
公开执行入口。各批后续终态必须按原 handle 继续核实，不因等待超时另启同一批。

原 clone HEAD/clean 再次核验，未修改 exweb、native 报告、失败 oracle 或业务结果。
tracked whitespace check 退出0；这些新增模块多为继承 untracked tree 中的文件，
不能从空 git diff/stat 推断没有实现。未执行 commit/push 或开发服务迁移/手工重启。

旧加载完整 V1 **83865** 仍 live（最近约 47%，已有失败标记），未重启，也不是当前
0111 完整门禁。独立许可本轮是 progress，goal 仍 active：执行 Portal、事务内许可/
worker/journal 绑定、Tool/Temporal 真派发/取消/未知恢复、真实覆盖/放行、五用途、旧链
切换、独立 gold 和 P0-P6 安全性能/试点要求继续保留完整范围。

## HTTP fixture 登记 Portal 与真实父链验收（2026-10-12）

本轮承接完整 P0-P6 目标，先重新核验原 handles：83430 已终态退出1，不能继续记为 live；
83865 仍是旧加载完整 V1，约 43% 且有失败标记。随后新增登记 Portal 的默认折叠入口、
完整 JSON/重复 keys/数值/限额检查、原 case/前置条件/setup/cleanup/hash 核验、独立
canonical 确认和严格父链/归档/metadata 校验。字段修改包括空白立即取消预览与确认；
刷新/失联只 GET 原命令与私有归档，sessionStorage 仅保存 actor/plan/request IDs 和
hash，不保存定义/资源正文。损坏与撤权隐藏父链，登记仍不运行 HTTP/Runner 或批准覆盖。
复用原 HTTP binding action 校验、UUIDv5 与有界 recovery，旧脚本 source indices 契约保留。
没有重启/迁移开发服务、改写原 exweb 或 oracle。

真实 PG/MinIO 批 **83430 退出1：1 failed/446.11 秒**，原因是 `reviewed_plan_inputs`
的独立脚本 reviewer 已是 qa_lead，测试却把它当无 reviewer 权限账号并期待 403。
测试显式设为 viewer 并通过真实 source authorization port 核实角色，保留原 403、
重新授予 qa_lead 后 200 和来源撤权先于 private bytes 的拒绝要求；生产权限规则未放宽。
修正后 **91182 退出0：1 passed/443.41 秒**，
`http-fixture-recipes-pg-role-explicit-20261012.log`。此链保留完整 canonical 真实父链，
验证事务回滚、独立确认、私有 S3、原命令/Agent/SSE、immutable FK/trigger/downgrade、
真实 SQL bool→int 篡改、物理对象删除恢复和当前角色/source ACL；没有 frozen-reader
代替正式路径，也未执行 exweb 业务。后续将测试的 bool 恢复也改为显式 SQL，并确认
真实字段类型；该微调复验 **81480 退出0：1 passed/511.99 秒**，
`http-fixture-recipes-pg-role-restoration-20261012.log`。这仍只验证输入登记与当前完整
父链/权限，不将慢速专项称为查询性能、实际 fixture 或业务闭环验收。

Portal 初批纯检查 **12888 退出1**（新 Python specimen 解包数量错误），lint **16529
退出1**（control-regex 风格检查）；修正夹具读取和显式 codepoint 检查后 **24813
退出0：118 passed/1.59 秒**。全部 Portal contract **78677 退出0：1151 passed/
8.98 秒**。随后收紧完整原计划 wrapper 的 project/命令/画像/清单与 artifact hash，
**39273 退出1：1149 passed/3 failed**：原 private-access unit specimen 是省略父 metadata
的最小 port，不符合新 Portal 要求。独立补齐明确协议父 wrapper 并经原 Python 领域核验，
不放宽 production 校验；**31677 退出0：1152 passed/11.83 秒**，
`http-fixture-recipes-all-portal-contracts-parent-fixed-20261012.log`。这些都是协议/纯测试，
不是实际 PG 权限或原目标通过证据。

最后补充所有 cleanup group 的完整总步数门禁和 16/17 资源边界，不截断输入来通过。
全部 Portal contract 最新 **92872 退出0：1153 passed/8.56 秒**，
`http-fixture-recipes-all-portal-contracts-budget-final-20261012.log`；生产 UI 未再修改。

最终 Portal build **12823 退出0**、lint **75413 退出0**，
`http-fixture-recipes-portal-input-{build,lint}-final-20261012.log`；main 1.26MB/>500KB 告警
保留。浏览器在独立 PG/MinIO/API 18090/Portal 14180 使用固定 exweb 来源及明确
script/fixture transport specimen，原 RunPlan 专项 **11454 退出0：2 passed/6.5m**，
`http-fixture-recipes-portal-input-browser-20261012.log`。覆盖原定义被改/确认失效、完整
请求、两阶段丢失 acknowledgement、只读恢复、刷新不重发、历史输入失效、归档 rehash
篡改/403、父内容隐藏和 light/dark/390px。实际查看当前两张
`fixture-recipe-{light,dark}-mobile.png`：无水平溢出，中文和细边框沿用原样式；既有
fixed banner 的顶端裁切仍存在，不宣称全部视觉/a11y 已验收。浏览器只登记定义，不发送
目标请求；它不是外部模型、实际 fixture 准备/清理、真实业务或 PG canonical 的替代证据。

clone HEAD 当前仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc` 且干净。本轮是
progress，不是完整闭环完成；独立执行/清理批准、runtime locator、production Tool/Temporal
dispatch/cancel/unknown recovery、覆盖/放行、五用途、旧链切换、独立业务 gold 与完整
P0-P6/V1 安全性能门禁继续保持原要求，goal active。

tracked diff check 退出0；七个新 Portal/协议文件 no-index whitespace 检查均无诊断，
exit1 仅表示新文件差异。旧加载完整 V1 **83865** 仍 live，最近约 45% 并有失败标记；
没有重启该进程，也不将新专项通过当作完整 V1 全绿。

## HTTP fixture 正式输入登记（2026-10-12）

0110 新增[固定定义登记](./http-fixture-recipes.md)：完整 manifest 与原 RunPlan 声明/hash
绑定，独立 canonical 确认，私有 S3 原字节和追加式 PG metadata/FK，事实、审计、Outbox
同事务；重新授权的 HTTP、metadata-only query/Agent observation 和脱敏 SSE 已组装。
只登记输入，不启动私有 lifecycle；fixture、执行授权、业务覆盖和基线恢复仍为 false。
原计划、source、exweb 和 oracle 未改，开发 DB/服务未迁移或重启。

最初纯检查 **64257 退出1：267 passed/2 failed**，原因是 digest 异常未转换到本域错误和
测试 ToolInvocation 缺少必填 status；修正后 **83493 退出1：268 passed/1 failed**，测试
错误地将合法 `data_manifest_hash` 字段也视为正文。确切检查正文后 **80738 退出0：
269 passed/4.99 秒**。完整 HTTP/RunPlan/DDD/ORM 回归 **5009 退出0：399 passed/
4 skipped/5.92 秒**，`http-fixture-recipes-regression-current-20261012.log`；最后收紧事实
广播只含不透明 ID/状态、不含 case ID/定义 hash 后，**19798 退出0：400 passed/4 skipped/
5.93 秒**，`http-fixture-recipes-regression-final-20261012.log`。四项 skip 不是原生目标
执行证据。父 hash 专项 **3304 退出0：45 passed/1.84 秒**。

首批真实 PG/MinIO **88749 退出1：1 failed/217.06 秒**，暴露旧 RunPlan metadata 没有
image_artifact_hash/manifest_hash。新 repository 改为核验不可变 FK 父记录取得，不给旧
记录补造字段；测试保留真实历史形状。随后 **61160 退出1：1 failed/263.61 秒**：登记、
S3 和故障事务已成功，但测试错误地要求认证调用者的完整 command input 也不含其提交
的 manifest。改为检查 metadata-only result，并继续严格检查 SSE 的 input/result 脱敏；
没有删除合法原输入或降低广播约束。两份失败日志保留。

第三批 **90324 退出1：1 failed/406.76 秒**，已通过登记、回滚、历史、Agent、SSE、
完整 FK/trigger/downgrade，但篡改测试没有真正将 true 改为 1：SQLAlchemy JSON 的
Python equality 把两者视为相等，普通赋值未写回 PG。改用显式 SQL update 并独立确认
原始字段确实为 int，再要求接口返回 502；不放宽拒绝断言。这一批加载于事实广播最后
收紧前，不能当作当前完整代码通过。

当时完整 canonical/原父链/真实 PG-MinIO/当前 source ACL 重验 **83430** 现已退出1，
`http-fixture-recipes-pg-integration-final-20261012.log`；角色夹具原因和最新通过批见上节。
不以此前部分检查声明失败批通过，也不用 frozen-parent double 替换正式路径。
全部前序失败日志保留。

API/runtime/Compose 与 0110 隔离 schema roundtrip **75262 退出0：173 passed/1 warning/
350.75 秒**，`http-fixture-recipes-api-contract-20261012.log`。该批加载于父 hash 修正前，
验证原 API 兼容和完整新表/非空/FK/trigger 的空演练，没有执行新登记路径；不能替代
最新正式专项。只在 nasus_test_ 的随机 schema 演练，没有降级 public 或开发库历史。
Portal build **40211 退出0**、lint **94649 退出0**，>500KB 告警保留；
smoke **49130 退出0：success**。浏览器原 RunPlan light/dark/390px 专项 **88622 退出0：
2 passed/2.4m**，实际查看本批两张 mobile 图：无水平溢出，原固定顶栏裁切问题仍在；
当批新登记 Portal 表单尚未交付；后续登记 UI 与专项目测见上节，不能把兼容页面检查
当作它的 UI 或全视觉验收。

原 exweb 六 fixture phase 到私有 MinIO 的 readonly 回放 **56255 退出0：1 passed/
1.13 秒**，`exweb-http-fixture-recipes-minio-replay-20261012.log`，原 13 断言仍 11 passed/
2 failed。未重新执行目标、修改原报告/预期或提升 PG/canonical/业务 false。
tracked diff check/新增模块 compile 退出0；12 个新文件的 no-index whitespace 检查无
诊断，exit1 是新文件差异，不误记为 exit0。

上轮 private worker 的原 handle 已取得终态：**61273 退出0：1 passed/1367.66 秒**。
该批完整父链后的明确 frozen-reader/Runner specimen 只证明私有 PG ownership/接管，
不证明真实 exweb canonical 执行。原 clone 当前 HEAD 仍为
`fe5827f6b76f77ef34918d8b452ee823142332dc`，status 干净。
旧加载 V1 **83865** 仍 live，约 40% 且已有失败标记；不是新代码全量绿色证据。

本轮实现和终态取证是 progress。完整 P0-P6、执行/清理批准、Portal、Temporal、取消与
未知效果恢复、真实覆盖到放行、五用途、旧链切换、独立业务 gold 和安全性能仍是原目标，
保持 active，不缩减验收。

## HTTP fixture 私有持久 worker fencing（2026-10-12）

上一问答轮只解释数据关联，没有改变实现，属于 no progress。本轮重新核验原 live
handles，并增加 0109：原 project/attempt/case 的 setup/cleanup 独立租约，完整 scope、
原 RunPlan/画像/manifest 和 actor pins，PG 时钟、过期接管与递增 epoch。数据库触发器
拒绝改绑原 pins、活跃 owner 或跳 epoch；所有权事实追加式，populated downgrade
不丢弃历史。没有修改原 exweb、oracle 或既有来源工件，也没有重启/迁移开发服务。

journal v2 将 owner/epoch 固定在原 dispatch，所有权与派发/审计/Outbox 同事务；
写入前后在原项目事务中重新检查租约。缺失所有权不能降级为 v1，旧 worker 不能在
接管后提交，新 worker 不能采用旧派发未知效果或重发 POST。复用原异步心跳生命周期；
线程的实际 Runner 回调和 PG 提交仍需 fence，不能仅靠 coroutine cancellation。
完整原命令在事务前核验，事务内不重入另一连接的 cleanup setup/actor 写锁。

修正边界测试原来检查不存在的 infrastructure/bootstrap 目录，现核对实际 bootstrap、
composition 和兼容 store。新能力仍未挂 production，租约及管理员不是执行批准。
独立执行/清理批准、canonical/Temporal、取消/原未知结果恢复和正式覆盖回流仍待交付。

纯专项 **45284 退出0：110 passed /1.91 秒**；完整当前 fixture/binding/DDD/ORM 注册/
Compose 边界 **78321 退出0：320 passed /4.09 秒**，日志分别为
`http-fixture-work-unit-20261012.log`、`http-fixture-work-boundary-current-v2-20261012.log`。
首次两项心跳测试因在 asyncio loop 内构造含 asyncio.run 的测试输入而失败，已将输入
构造移到 loop 外；没有改生产生命周期。另一初始边界批选错不存在的测试路径退出4，
`http-fixture-work-boundary-current-20261012.log` 保留，不把无测试当通过。

原 0108 PG/MinIO 专项现已结束：**50211 退出0，1 passed /1641.73 秒；74640 退出0，
1 passed /1583.80 秒**。它们加载于 0109 前，且都早于最后的 valid foreign-wrapper
scope guard，不冒充当前代码全量验证。原大回归 **17633 退出0：545 passed /2 skipped
/4270.25 秒**，同样没有收集本轮新 worker 模块。

新完整 PG/MinIO journal/ownership 专项 **61273 已退出0：1 passed/1367.66 秒**：
`http-fixture-work-pg-integration-sealed-20261012.log`。它先核验完整原 parent，再用
明确的 frozen parent-reader 和 Runner specimen 隔离 PG 所有权、并发、时钟及恢复；
不是真实 exweb canonical 执行、当前 source ACL 或业务覆盖证明。首批 **42059 退出241**：
确认已加载的测试 specimen 错将原 negative-control 断言标 passed 后，显式终止自己的
过期 pytest，再开修正批；不是因为日志安静、观察超时或锁文件猜测任务停止。
原 oracle 未改，终止批 `http-fixture-work-pg-integration-20261012.log` 保留。
当前 API/runtime/Compose 专项 **44203 退出0：172 passed /1 warning /385.15 秒**，
`http-fixture-work-api-contract-20261012.log`，私有 DB 已升级至 0109。

0109 空表 migration roundtrip **74664 退出0：1 passed /0.65 秒**。随后将演练隔离到
同一 disposable DB 的随机 schema，避免完整 suite 已有原 journal 数据时误降级历史；
当前版本 **77722 退出0：1 passed /0.67 秒**，
`http-fixture-work-migration-isolated-20261012.log`。验证表字段、非空、完整 FK 和两条
保护 trigger，并要求 nasus_test_ 数据库，结束删除自己的 schema；不代表 populated
worker takeover 的结论；后者由 61273 的完整专项另行取证，终态见上段。

Portal build **77407 退出0**、lint **1861 退出0**；主包 >500KB 告警仍保留。
浏览器 **3216 退出0：2 passed /2.7m**（18090/14180、light/dark/390px），实际查看
当前两张 mobile 截图：原声明与零执行覆盖可读，无水平溢出，固定顶栏遮挡仍存在。
smoke **64587 退出0：success**，release hygiene、tracked diff check 与新增模块 compile
退出0。浏览器/模型/Runner 协议 specimens 不替代原生业务验收。

原 exweb 六 phase 原字节到私有 MinIO 再次验证 **13387 退出0：1 passed /1.64 秒**，
`exweb-http-fixture-work-minio-replay-20261012.log`。13 原断言仍 11 passed/2 failed，
未重执行目标或改写旧报告的 PG/canonical/业务 false。原 clone status 干净。
旧加载完整 V1 **83865** 仍 live，已有失败标记、截至本轮观察约38%，不能报告全绿。

本轮是 progress；全 P0-P6、安全性能、五用途、旧链切换、独立业务 gold 和真实覆盖
到放行仍是原目标，保持 active，不以这些专项成功声明完成。

## HTTP fixture 私有 PG journal 与 MinIO 原字节归档（2026-10-12）

上一问答轮只核对数据关联，没有新增目标实现；相对目标属于 no progress。本轮先重新
核验 83865/17633 两个原 handle live，再实施 PG durability，不因日志安静重启任务。
新增 0108 两张追加式表，以原 project/attempt/case/phase 唯一，结果 FK 连接原预留，
完整 FK 固定原 RunPlan、画像和 manifest。新 application access port 回读原 plan 全部
工件及来源权限，校验 recipe、project/digest、原 owned loopback、环境/inventory/build。
事务内重验实际管理员、父记录和显式 caller fence；没有 durable lease 或独立执行批准。

MinIO 新 codec 保留完整原 request/result bytes，拒绝截断、换 scope/parent/command、
私有项目命名空间错配、缺失及篡改，并重验 native receipt/capture/失败断言。后端不允许
SQLite 或 local-object 降级。预留/结果各与脱敏审计和 Outbox 同事务提交；原结果提交
失败仍保持预留，服务重建不重发 POST。S3 预写可能留 orphan，不声明分布式事务或 GC。
实现及剩余边界见 [HTTP fixture 生命周期](./http-fixture-lifecycle.md)。

当前代码纯 application/fixture/codec/DDD/Compose 契约 **225 passed /2.64 秒**
（`http-fixture-pg-journal-unit-current-20261012.log`），含完整有效 plan 的错误 endpoint
负向控制、有效 plan 被另项目 envelope 包装的拒绝。不能用坏 hash 的早期拒绝替代这些
独立范围检查。此前 204/223/224 项日志保留，最终以 current 批为准。

原 exweb fixture 原输出到 disposable 私有 MinIO 往返 **session91868 退出0：1 passed
/1.24 秒**（`exweb-http-fixture-minio-replay-20261012.log`）：先完整只读重放原三个
fixture，再逐字节回读全部 6 phase、13 断言（11 passed/2 failed）。目标未重执行，
旧报告未改写，其 PG/canonical/业务覆盖 false 仍保留。这是新 codec 的真实原输出
验证，不把它与独立 PG canonical-parent 夹具拼成真实 exweb 正式执行。

完整 PG/MinIO parent/journal 故障与恢复专项 **50211 和 74640 尚 live**：
`http-fixture-pg-journal-integration-v2-20261012.log` 与
`http-fixture-pg-journal-integration-sealed-20261012.log`。旧 v2 批加载早于 endpoint
与最终 project/body guard；新 sealed 批已固定正确原 endpoint，最后只增加有效外包
项目错误的严格检查与纯负向测试，尚无 PG 整体终态。本轮原 handle/CPU 与
只读私有测试 PG 查询证明仍在工作：已有持久 setup failed、cleanup passed 原结果，
另一批已保存 setup failed；不能把部分行存在当成全部 restart/Outbox/故障测试通过。
初始批 35693 因未导入 fixture 依赖退出1，54195 因测试选择漏填 v2 plan 策略退出1，
日志保留；修复夹具后另开新批，不放宽生产校验或改原 oracle。

独立 API/runtime/Compose 契约 **session87275 退出0：172 passed /1 warning /413.09 秒**
（`http-fixture-pg-journal-api-contract-20261012.log`），私有 PG/MinIO 已迁移到 0108。
原 RunPlan 浏览器 **session20417 退出0：2 passed /2.9m**
（`http-fixture-pg-journal-browser-20261012.log`），18090/14180、浅深色与 390px。
00:41/00:42 两张 mobile 原截图已实际查看：完整声明与零覆盖提示可读，无水平溢出；
原固定顶栏遮挡仍存在，不声明全面视觉验收。Portal build **31124 退出0**、lint
**57875 退出0**，主包 >500KB 告警保留。私有 PG/MinIO smoke **11579 退出0：success**。
release hygiene 和 tracked diff check 退出0；新增文件 no-index check 退出1 表示有新增
内容、没有 whitespace 诊断，不错误报告它们退出0，也不声明审计全部既有 dirty tree。

原大回归 **17633** 与旧加载完整 V1 **83865** 仍 live；截至 00:52 分别约 52% 与35%，
后者已有失败标记，且未收集本轮新模块，不能声称当前完整 V1 全绿。原 exweb clone
工作区无改动，未迁移/重启开发 DB/API/Portal；没有残留 exweb 临时 Docker cohort。

新 journal **未挂生产 composition/HTTP/Tool/Temporal**，不冒用原准备命令作为执行
授权；独立执行/清理批准、持久 owner/lease、原未知效果恢复、正式执行与 coverage/
release 回流、完整五用途/旧链切换、P0-P6、安全性能和独立业务 gold 仍需全部交付。
本轮是 progress，完整目标保持 active；后续继续原 live handles，不能以专项成功替代
完整完成审计。

## HTTP fixture 原响应绑定与实际清理（2026-10-12）

上一目标轮的读取作用域接入、真实 exweb/PG/MinIO 对照及迁移演练修复是 progress。
本轮重新核验原完整门禁 **session83865** 与 81264/81668/81670 实际进程仍 live，
截至 00:13 已推进约 30%；首个历史迁移演练失败保留，尚无整体终态。
该进程收集早于本轮新 fixture 模块，也不能作为新代码全绿证据；没有因安静日志重启。

新增[HTTP fixture 生命周期](./http-fixture-lifecycle.md)领域 manifest、原 RunPlan 声明
连接 helper、application 分阶段执行及原字节核验 adapter。准备创建先从原 2xx JSON
capture 资源 ID，再观察断言；失败准备的已知资源仍独立清理，未知资源不猜测 ID。
全部清理组保持原 body/header/oracle，已知组失败不能省略其他组；没有可信原输出的
派发不自动重试。同 project/attempt/case/phase 唯一，不能通过改 scope digest、环境、
构建、manifest 或 timeout 逃避原未知 POST 的 fence。回放重新授权并核验原输出。

模块目前**不挂生产 composition/Tool/HTTP**；派发 journal 只有明确 port 契约。
单元内存 double 和开发探针文件 fence 均非正式 PG 业务账本，不能声称 durable owner、
Temporal 取消/恢复、执行批准或业务覆盖完成。没有改旧计划/脚本摘要、原 oracle、
开发数据库或 exweb 源码；正式 PG/MinIO/Outbox/批准/执行接入仍按完整 P5 交付。

固定 exweb 最终原生批 **session68522 退出1**
（`exweb-http-fixture-lifecycle-final-20261012.log/json`）：stage=observed/error=null，
全部 126 原 Git blob、离线原构建、同一 owned target/PG/Redis cohort。新增 3 fixture
共 6 个 native phase、7 HTTP 请求、3 capture，**13 断言 /11 passed /2 failed**：
正常准备/关闭成功；明确 setup 负向控制失败后仍清理成功；关闭后读取原 404 oracle
实际返回 500，cleanup_verified=false。协议 checks 符合不等于这些断言全部通过。
原七个 Runner job 与其失败结果未变，整体 **17/24 checks**，原 7 项失败保留。
owned 临时资源 cleanup verified=true/remaining=[]；这是资源 teardown，不是业务基线恢复。

最终 fixture 只读回放退出0
（`exweb-http-fixture-lifecycle-final-replay-20261012.log/json`），核验原 manifest/scope/
claim/wire/result/执行器 source hash，目标未重执行。原七任务完整只读回放 **session54137
退出0**（`exweb-http-fixture-original-seven-replay-20261012.log`）：126 blobs、7 jobs、
37 断言 /35 passed /2 failed、12 requests/2 bindings；formal_coverage_verified=false。
首批原生与回放报告保留，最终源码调整后另跑新批，不覆盖旧证据或拼接不同批 JAR。

纯 fixture/探针/边界最后 **86 passed /0.68 秒**
（`http-fixture-unit-probe-sealed-20261012.log`），涵盖部分多资源、失败清理、未知写入、
并发 claim、证据提交失败、撤权、原 wire/output 与 scope 篡改、原 manifest/plan 连接
及同尝试改输入拒绝。这些是 protocol specimens，不声称真实 PG journal 或业务 gold。

独立 disposable PG/私有 MinIO 的原 API/runtime/Compose 契约 **session16910 退出0：
172 passed /1 warning /381.96 秒**（`http-fixture-api-runtime-contract-20261012.log`）。
fixture/HTTP/owned port/RunPlan/归档/DDD 等较大回归 **session17633 当前仍 live**
（`http-fixture-run-plan-regression-final-20261012.log`），尚无终态，须继续观察原 handle。
首个包装批 session30485 退出4，因路径误写 `test_run_plan_api.py` 未收集任何测试；
现用实际 `test_run_plans_api.py` 新批，不将旧批算作通过。

独立浏览器 **session37264 退出0：2 passed /2.7m**
（`http-fixture-run-plan-browser-20261012.log`），实际 PG/MinIO、新 private 18089/14179，
原 RunPlan 声明/丢失回执/刷新恢复、构建/定位/环境记录、浅深色及 390px；模型/生成
是既有明确协议夹具，不执行 exweb。00:07-00:08 的浅深色 mobile 原截图已实际查看，
声明和零覆盖提示可读，无水平溢出；原固定顶栏窄屏遮挡仍存在，未声称全面视觉验收。

Runner **session35811 退出0：132 passed /0 failed**；Portal build **session67887 退出0**，
lint **session89968 退出0**，保留主包 1240.98KB/gzip335.62KB 和 >500KB 告警。
私有 PG/MinIO smoke **session48993 退出0：success**，release hygiene 和 tracked diff
检查通过；新增代码也独立无 whitespace 诊断，不据此声称整个大 dirty tree 已完成审计。

下一步仍需原 fixture 的正式 PG journal/MinIO/审计/Outbox、独立当前执行/清理权限与
owner/lease、canonical Tool/Temporal 派发、取消/未知效果恢复、完整 case/step/oracle
证据到 coverage/release，以及完整 P0-P6、多语言/身份/browser/远程 fixture、五用途、
旧链切换、独立 gold/安全性能与最终 V1 门禁。不能以本批私有运行替代完整验收。

## 最新 schema 的历史迁移演练兼容（2026-10-11）

前一目标轮完成了真实 exweb 读取测量及连接-only 对照，属于 progress；期间没有修改生产
application。完整门禁原 session83865 重新核验仍 live，81264/81668/81670 实际进程存在，
后端已推进约 14%，出现首个失败，但尚无整体终态。继续观察原 handle，不因超时重启。

首个失败为 `test_native_script_review_withdrawal_and_explicit_backfill_preserve_original_derivations`。
独立 disposable PG/私有 MinIO 复现 session44532 已退出1：**1 failed /184.62 秒**
（`context-read-full-gate-first-failure-20261011.log`）。原 traceback 明确为
`DependentObjectsStillExist`：旧 0100 演练删除 `quality_run_plans`，0103-0107 的构建、
观察、环境、健康和定位表仍有外键引用。不是模型、MinIO、业务 oracle 或来源缺失错误。

现使用[回滚演练约束](./automation-provenance.md#历史迁移)：只在测试回滚事务临时解除
指向待重建表的直接外键，不删除后续表/数据、不用 CASCADE。原 DDL、原全部派生摘要、
坏事实拒绝与正常读取不修补历史的断言保留，并在两种演练回滚后比较全库外键清单。
新增已填充子表/孙表、无关外键保留、非法引用实际拒绝、无事务/无效目标拒绝的辅助验证，
真实隔离 PG/MinIO **session14965 退出0：4 passed /1.32 秒**
（`migration-rehearsal-helper-20261011.log`）。纯读取统计和独立授权池配置另为
**32 passed /0.55 秒**，不相加为完整门禁覆盖。

脚本追溯 API/领域/repository、辅助演练、DDD 与 Compose 的新加载复验 **session89542
退出0：202 passed /363.09 秒**（`automation-provenance-migration-rehearsal-final-20261011.log`）。
原完整门禁收集早于本轮测试修改，不把其结果当作修订测试通过证明。该迁移演练修复本身不改
生产逻辑/schema、开发库、exweb 源码和 oracle；后续正式读取优化另列下节，完整 P0-P6 不缩减。

## 正式上下文读取的操作级连接作用域（2026-10-11）

根据前一轮实际对照，将[连接-only 复用](./context-read-performance.md#连接复用对照与正式读取)
接入 `ContextPackApplicationService.read()` 的 application authorization port。原读算法和
全部实时授权、原字节、authority/publication/index、持久失效校验保持不变；只复用独立
READ COMMITTED／READ ONLY 连接，异常也 rollback/close，不加入跨请求权限或内容缓存。
预览、保存和其他入口未借本次优化改变授权、公开 API、工件摘要或 oracle。

新 application control-flow 专项及统计／授权池配置 **43 passed /0.59 秒**，其中 11 项新增
覆盖 scope 内全部原阶段、每阶段失败清理、下次独立、撤权拒绝及历史过期／失效理由保留。
这些明确使用 port doubles，不单独证明真实 PG 或对象回放。

实际生产路径的固定 exweb v2 对照 **session10533 退出0：1 passed /73.85 秒**
（`exweb-context-production-connection-comparison-20261011.log`），原 JSON 已回读。固定全部
126 Git blob、同一 context；每对原完整响应、286 次实时授权查询、69 GET／15 原对象／
3670655 字节及原清单摘要一致，事实写入 0。原算法的 340 次 business 借还降为正式读取
**54 business +1 live**；每请求 live 一次 read-only setup／rollback、无 commit，成功和
撤权／损坏拒绝路径全部归还。control p50 **2.079942 秒**、production p50 **1.818643 秒**，
p95 **2.781256／2.089031 秒**。对照只在测试 baseline 暂时去掉外层连接作用域，production
走公共原方法；v1 旧实验 JSON 不改写。样本为本机预热五对且其他验证负载未受控，p95 仍超过
两秒，不是 Linux 8CPU/16GB、容量或完整性能验收。合成 Search 需求／用例及 Orders 哨兵、
未批准 AC、blocked context、无外部模型／目标执行／正式覆盖的边界保持原样。

Portal build/lint 已核验终态退出0（`context-read-scope-portal-{build,lint}-20261011.log`），
主包 **1240.98kB /gzip335.62kB** 的 >500kB 警告保留。新加载 PG/私有 MinIO 的 context
v1-v5、authority/publication/model 变更、ACL／损坏、池隔离及 DDD 回归 **session19926
退出0：214 passed /335.02 秒**（`context-production-read-scope-regression-20261011.log`）。
浏览器 context/published 专项 **session34481 退出0：4 passed /4.9m**
（`context-production-read-scope-browser-20261011.log`）：context 用固定 exweb 原提交及明确
伴随验证资料，published 用独立结构夹具；两者 canonical PG/MinIO 写入和历史回读真实，
末尾响应篡改为明确的防护测试，不是模型质量／业务 gold 或正式覆盖验收。浅色 context 和
深色 published 的 390px 截图已实际回读，原历史文本与 stale/blocked、预算、子包仍可见，
无横向溢出断言通过。私有 PG/MinIO **session64566 退出0：smoke success**
（`context-production-read-scope-smoke-20261011.log`），测试 wrapper 的独立资源清理已结束。
这些选择集有重叠，不相加为项目总数或完整门禁。

原完整门禁 session83865 加载早于本次 production read 修改，最后 handle 已重新核验 live，
后端推进约 15%，仍有原已复现首个失败／尚无终态；继续原任务，不将其视作新代码全量通过，
也不因观察超时重启。新迁移演练 202 项和上述 214 项分别是明确加载范围的独立成功证据。
未迁移开发库、重启开发服务或 commit/push；P5 执行授权/fixtures/真实覆盖到放行、五用途切换、
自动 delta/merge、独立 gold 与 Linux 性能/容量/恢复/试点及完整 P0-P6 仍未完成。

## 固定 exweb 上下文读取实测（2026-10-11）

新增[独立读取测量](./context-read-performance.md)，在原 canonical 来源／画像／上下文路径上使用 disposable PG 与私有 MinIO，固定新提交全部 **126 Git blob** 和 tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`。合成 Search 需求／历史用例和 Orders 哨兵明确标注，未批准 AC、context blocked、目标未执行、无外部模型。测量不是 exweb 业务 gold，也不替代 P0-P6。

统计契约最后 **23 passed /0.09 秒**。真实测量 **session17032 退出0：1 passed /62.12 秒**（`exweb-context-read-measurement-final-20261011.log`），原 JSON 已实际回读：5 次独立读取的 **p50 1.888131 秒 /nearest-rank p95 1.998291 秒**。每次均为 **340 次 business checkout／begin／commit、417 条 SQL、286 次实时授权查询、69 次对象读取／15 个不同对象／3670655 字节**，完整响应和原读取清单一致，事实写入 0；另有 1 次认证 bookkeeping。源权限在读取中撤回返回 409 `source_access_changed`，后续成员访问 403；损坏 context 字节返回 502，不泄漏正文／私有地址；管理员原归档响应不变。

该批为 Darwin arm64／10CPU 本机 TestClient、setup 预热、串行 5 样本，其他验证负载未受控，`capacity_or_p95_acceptance=false`。不能以 p95 数值接近两秒声明 Linux 8CPU／16GB、并发容量或完整用途上下文的性能门禁通过。重复连接和重复对象读取的实际成本为后续优化依据，不能用删除授权查询／原字节验证换取性能。

首批 **session94172 退出1：1 error /3.93 秒**，复用增量 fixture 误依赖浅克隆中不存在的旧 commit；现只导出本测量所需固定新 commit，不 fetch／改写源仓库。次批 **session68342 退出1：1 failed /57.80 秒**，五次读取已完成但新测试误要求读取中撤权返回 403，实际现有接口明确为 409；现校验确切错误 code，之后仍要求 403，未放宽生产权限或成功条件。两个原日志保留，最后成功批才是完整测量证据。

隔离连接-only 对照 **session53757 退出0：1 passed /70.07 秒**（`exweb-context-read-connection-reuse-20261011.log`），原 JSON 已回读。五对 control → experiment 的完整响应、**286 次实时授权查询**、对象清单／次数／字节完全一致；原 **340** 次 business 连接借还变为 **54 business +1 live**，独立 live 连接 READ COMMITTED／READ ONLY、每请求一次 rollback／无 commit，所有正常／拒绝路径均归还。control p50 **1.937298 秒**，experiment p50 **1.653630 秒**，p95 分别 **1.971656／1.768602 秒**；不作为正式性能或 20% 效率验收。实验 reader 中撤权／损坏仍拒绝、原业务事实与 oracle 不改写，随后生产方法还原。该批只改变测试进程中的连接作用域，不修改运行中完整门禁的 production application；后续正式接入须独立重新验证。

完整门禁仍是原 **session83865**，最新 handle 与 81264／81668／81670 实际进程已核验 live，后端已推进约 13%，暂无终态，不因安静日志／观察超时重启。此运行启动和收集早于本轮新增测量文件；不能将它后来的结果当作已覆盖新测量。没有修改正在验证的生产逻辑、数据库 schema、开发数据库或服务。

## 发布阶段一致性与完整门禁端口隔离（2026-10-11）

[发布证据门禁](./release-evidence-gates.md)修复真实状态冲突：旧发布阶段只看硬 blocker，会将低分、审批未解决或明确 unknown 的评估推进为 release_ready；工作区则拒绝。两处现共用纯领域门禁，保留原 score、evidence、approval、version 及失败原因，不制造规范或执行事实。旧生成链的场景/用例仍为待审阅；审批授予操作权限而非质量证明。

旧七项 API journey 已校正为独立负向契约，保留完整八工具顺序、生成内容与调用来源、原存储工件、最新 US、失败分析/人工接管及重启恢复。新增未知库存不晋级 baseline、高分不掩盖 unknown、未批准资产和双 blocker 检查。它们不能替代原正向真实业务闭环、独立 oracle 或 P5/P6 的放行验收。首次专项 **4 failed /3 passed /53.21 秒**、修正草稿契约后的 **1 failed /6 passed /50.95 秒**保留；最后一项是测试错误地要求通用 lane summary 包含每条 blocker，改为核对完整 blockers 列表，未放宽生产判断。

本轮已核验终态（选择集重叠，不相加为总数）：

- 领域/工作区/发布/DDD 选择集 **238 passed /2.26 秒**（`release-review-threshold-domain-20261011.log`）。
- 标准 API/runtime/Compose/DDD/Portal 与发布、原实例端口/归档选择集 **session61038 退出0：480 passed /1 warning /350.66 秒**（`release-review-standard-explicit-private-minio-20261011.log`），真实 disposable PG/私有 MinIO。初次缺显式 MinIO endpoint 的启动退出1且未执行测试，原日志保留。LangGraph pending-deprecation warning 保留。
- 固定 exweb 来源的导航/未知质量浏览器 **session88780 退出0：11 passed /1.5m**（`release-review-exweb-browser-pg-minio-20261011.log`）。真实 PG/MinIO、固定原 commit 和三源归档；生成使用明确 fallback，历史 ready 是仅写入 disposable PG 的负向攻击夹具。验证待审阅、blocked、null unknown、刷新/390px及零隐式写入，不证明目标运行或模型质量。桌面浅色和移动中文深色截图已实际回读。
- 私有 PG/MinIO smoke **session87445 退出0、success**（`release-review-smoke-pg-minio-20261011.log`）；Portal build/lint 终态日志无错误，主包 **1240.98kB /gzip335.62kB** 的 >500kB 警告仍在。
- 新只读原生 exweb 回放退出0（`exweb-owned-http-release-review-readonly-20261011.log`），126 blobs、七原任务、全部原 wire/response/oracle 与清理完整性复核；原5通过/2失败、37断言/12请求/2绑定不改写，target_reexecuted=false/formal_coverage_verified=false。

实际运行 `npm run verify:v1-release` 发现脚本前置错误：为最后 Compose 阶段选定的 POSTGRES/MINIO 端口提前改变了 host gate 的 runtime 默认，后端连接未启动的 55473 端口而退出1。原日志 `release-review-full-v1-20261011.log` 保留；此前 Portal contracts **1116 passed /7309.164166ms**、Runner **132 passed /2405.044541ms** 和 build/lint/i18n/Portal boundaries 通过，不把前置通过等同完整验收。

现将计划栈端口独立为 RELEASE_* 变量，仅在 Compose 启动/清理时显式映射。真实 shell 函数回归覆盖 host 默认与自定义端口、显式测试 PG/私有 S3 优先级及确切清理端口；与 Compose 契约最后 **21 passed /0.82 秒**（`release-gate-port-isolation-contract-current-20261011.log`）。首批 cleanup 测试误读被生产脚本重定向的 stdout，次批旧命令字符串遗漏新增回归文件，各 **1 failed /20 passed**，均保留日志；修正仅涉及测试观察与完整命令契约，不删除门禁。`bash -n` 通过。新增回归纳入完整 backend gate。

修正后完整门禁 **session15836**（`release-review-full-v1-port-fixed-20261011.log`）已通过前置 Portal contracts **1116 passed /7168.041667ms**、Runner **132 passed /2368.615875ms**，真正进入 disposable PG 全后端选择。沿调用链另发现应用层低分/审批未解决时对话提示仍声称可审阅，因此有意中断该批再修复，原 handle 终态退出1、相关进程已退出。日志保留部分失败标记以及 KeyboardInterrupt/tmp_path teardown 错误，没有完整后端总结，不能归为通过或用其推断全部失败原因。

应用层现直接消费原领域 plan 的 blocked 状态，原评估只调用一次；不再用单独 blocker/unknown 布尔值生成相反提示。新应用回归含七个阻断原因和 80/100 合格路径，核对工具推荐、lane/asset/US、原分数/证据及零模型调用，属于明确 port doubles。与领域/工作区/DDD/Compose/shell 隔离组合 **session39317 退出0：252 passed /3.35 秒**（`release-guidance-domain-application-pg-20261011.log`）。完整 backend 选择的 fail-fast 诊断 **session26919 终态退出1：1 failed /103 passed /1 warning /125.32 秒**（`release-guidance-full-backend-diagnostic-20261011.log`）；其明确失败为 `test_future_registry_growth_keeps_ranked_contracts_and_all_ids_in_the_original_budget`，而非上述应用回归。

该诊断暴露完整目录已达146项，再加50项同族增长夹具后，v2 原 top-12 的最小展示仍需7120字节，环境核验工具被低成本条目挤掉。[内部目录 v3](./agent-tool-catalog.md)现进一步无损提取下划线分隔前缀，原风险/确认/必填输入、排序、12项和6999字节不变；旧 v2 按原验证规则可回读，小目录保持未编码格式。当前196项（含50项协议夹具）的实际结果 **6999字节，top-12最小6783字节，完整有序ID及原top-12均保留**，不把夹具计入公开目录，也不宣称任意增长都可容纳。首次新专项 **1 failed /352 passed /3.75 秒**仅因测试误将原合法的 `_.inspect` 标为非法；保留原 canonical ID 语法，将合法性与无效前缀分别测试，没有放宽生产校验。

新加载 Agent目录/发现、应用提示、发布/工作区、DDD/Compose及shell隔离组合 **session57364 退出0：355 passed /3.71 秒**（`agent-catalog-v3-release-guidance-final-pg-20261011.log`）。覆盖v2历史、v3无损/后缀非空/不同前缀重建ID碰撞/未知schema与原完整治理，不是外部模型理解质量或原生执行证明。完整 `npm run verify:v1-release` 已基于这份代码重新启动（`agent-catalog-v3-release-guidance-full-v1-20261011.log`），尚无终态，仍没有完整 V1 全绿证据；后续真实结果必须另行核验，不能用本选择集替代。

完整 RunPlan fixture/runtime locator/执行授权与生命周期、真实覆盖到放行、五用途和旧链切换、自动项目增量/merge、独立 gold/Provider/隔离/性能/试点及原 P0-P6 退出条件仍是必须交付的范围。未迁移开发库、重启开发服务或 commit/push。

## 原实例 HTTP 执行端口与归档回放（2026-10-11）

[原实例执行端口](./owned-target-http-execution.md)已在 quality_loop application 定义，基础设施通过运维私有 registry 选择完整 target/PG/Redis/internal network/JAR，不接受公开请求中的容器 ID 或 registry 路径。Node 私有 worker 在每次 HTTP 请求前后重验完整原 cohort，包含 image、StartedAt、资源及挂载政策；更换实例、撤销权限、取消或原请求/结果摘要不符拒绝。原 wire/result 字节完整保留，不重试未知业务出口，也不在部分失败后拼接另一模型或另一个目标的结果。原有 public Runner 不开放 owned Docker transport。

原 registry/端口/结果/取消、HTTP observation/binding、RunPlan 和领域组合 **401 passed /4.54 秒**（`owned-target-http-port-domain-paths-fixed-20261011.log`）；Runner 最后批 **132 passed /2373.500334ms**（`owned-target-http-runner-cli-final-20261011.log`）；DDD/端口边界 **134 passed /1.77 秒**（`owned-target-http-boundaries-20261011.log`）。错误文件名首批退出4且没有测试，日志保留。新增清理后归档回放的完整源码/原请求/原结果/全任务与故障注入，连同端口/取消选择集已结束，日志 **58 passed /2.84 秒**（`owned-target-http-replay-current-20261011.log`），相关进程不存在。各选择集重叠，不相加为项目总数；协议 doubles 不冒充原生目标运行。

Portal build/lint 均退出0，PG/私有 MinIO smoke success，导航/RunPlan 浏览器 **11 passed /2.9m**（`owned-target-http-{portal-build,portal-lint,smoke,e2e}-20261011.log`）。UI 原生来源底座与模型/审阅/transport specimens 分开；主包 **1240.98kB /gzip335.62kB** 的 >500kB 警告仍保留。该批标准 API/runtime/Compose/DDD/Portal 为 **7 failed /352 passed /1 warning /236.14 秒**（`owned-target-http-standard-20261011.log`），保留完整历史失败；其发布、未知质量、失败 blocker 和资产持久化契约的后续核对见下一阶段记录。

固定 exweb 通过生产端口实际执行两批；两批均终态退出1、stage=observed/error=null，**21 项检查中14通过、7失败**。最后报告 `exweb-configured-owned-http-port-final-20261011.json` 固定原126 Git blob、JAR `sha256:98d7a454c5672ef6c7207ab6f05bb3ea8df0eefd15cff010051a2406c342d8dd` 和 inventory `sha256:8b4f3d8e39e77e0b13f47624988b37d96401f9b31c0d746ed30d5df3277aa342`。七个 HTTP 任务5通过/2失败，37项原断言35通过/2失败，12次真实请求、2个响应绑定。closed-read 返回500而非原 oracle 的404，跨用户/租户拒绝状态同样500，会话未落 PG 且重启丢失；这些失败未改源码或 oracle 消除。该批未开启 isolation canaries，分母21不能与此前24项混用。两批 cleanup verified=true/remaining=[]，最后 owner label 的容器和网络实际列表为空；不同批 JAR hash 不声明可重现构建。

首次只读重验错误地将三个 Git identity 字段与增加了 content_hash 的报告对象整体比较，退出1，原日志保留。持久只读 verifier 现分开验证 identity 和全部原 Git blob，再校验完整库存、七任务、请求/响应 bytes、oracle、执行器源码及清理状态。真实重验退出0（`exweb-configured-owned-http-port-replay-fixed-20261011.log`），126 blobs/7 jobs/37 assertions 全部按原归档核验，target_reexecuted=false/formal_coverage_verified=false；后续专门负例验证漏任务、重复任务、错摘要、错误 flags、坏原文与伪造授权均拒绝。

该端口目前供实际开发验证调用，尚未接入独立持久 RunPlan 执行授权及 Tool/Temporal dispatch/cancel/recovery。开发 oracle 不是维护者批准的业务 gold，真实 native HTTP 观察不能升级旧协议用例的正式 coverage。fixture/runtime locator、完整覆盖回流和真实放行、五用途/旧链切换、Provider/gold/隔离、自动 delta/overlay/merge、完整预算恢复及 P0-P6/V1 门禁仍是本目标必需范围。未迁移开发库、重启开发服务或 commit/push。

## 独立 HTTP 定位归档与原字节重验（0107，2026-10-11）

新增[独立定位登记](./http-locator-evidence.md#独立登记与原始字节重验0107)：原计划三字段输入经独立 canonical 确认、确认账号/十五分钟 TTL 和实时来源校验后，完整静态 report 写入私有 MinIO，追加式 PG 记录以复合 FK 连接原计划/画像/manifest，事实、审计及 metadata-only Outbox 同事务。独立历史 GET/query、已有命令重入和 Agent 回执核验完整原来源文件及确切 supporting spans，不重新解析、不查 latest、不重调模型。旧只读查询的 durable flag 保持 false；新记录 source bytes/durable verified=true 仅表示完整性与持久追溯，runtime/fixture/execution/business 权威仍 false，自动化/执行/通过仍零。

Portal 已增加单独折叠的登记/恢复面板，明确显示全部原请求动作分母、缺口及静态权威。新写入需要当前原输入和此次独立确认；sessionStorage 只存账号/项目/原计划/hash/request/command 的不透明标识。失联及刷新只 GET 原命令和历史，待确认恢复须重新勾选，不自动重发或解析；私有字节读取前核对 canonical 原参数/确认/result/object refs，再验证完整归档与原回执一致。新原输入已撤回时只读历史，撤权或坏归档隐藏受保护父链。完整 archive 延迟到显式展开后渲染，保留现有深浅色、中文和窄屏 tokens。

真实 JSON 往返暴露解析器 rules 元组被存储为数组：原提交前 Python 对象比较误判合法归档变化。改为规范 JSON 摘要比较，仍完整回读原字节、pin 与权限，严格区分 false/0 和 true/1。新增实际序列化往返回归，而非放宽故障注入或移除原字节校验。原生首次失败 **1 failed /424.33 秒**、诊断批 **1 failed /336.76 秒**（`http-locator-record-native[-diagnostic]-20261011.log`）保留；诊断确切显示 `locator original archive changed before commit`，尚未进入晚期账本故障。旧加载固定 exweb 批 **1 failed /1127.29 秒**（`exweb-http-locator-record-20261011.log`）在独立确认处失败，生产错误保持脱敏，不以诊断推测当作这批的独立成功证据。

新工具仍在完整 canonical catalog。通用原计划阶段保留原环境/健康/构建十二个详细契约；三种 locator 工具在明确源码/接口定位意图或确切 tool ID 下优先进入同一十二项有界提示，不减少 catalog 或核心 tool ID。旧泛化测试将十五个工具全部要求进入十二项详细预算而失败；现分别验证两种阶段，真实 canonical confirmation/risk/context 契约保持不变。

本次已核验终态（选择集重叠，不相加为项目总数）：

- JSON 往返/原字节/解析兼容、应用端口、Agent 分阶段选择、DDD/ORM 接线选择集 **358 passed /6.50 秒**（`http-locator-record-json-fixed-domain-paths-20261011.log`），disposable PG；前一 Agent 专项 **292 passed /5.18 秒** 未含最后的 JSON 回归。错误文件名的两次启动退出4且没有执行测试，失败日志保留，不计为通过。
- 独立面板契约 **25 passed /1518.121625ms**（`http-locator-record-panel-unit-20261011.log`）；完整 Portal contracts **1116 passed /13531.279792ms**（`http-locator-record-panel-contracts-20261011.log`）。完整 Python archive 的哈希、全部 request/父输入、authority/count 严格类型、错 pin/roster/actor/time、只存标识和丢失 ACK 后只 GET、私有历史前置核验及默认折叠/延迟渲染均覆盖；这些是协议/纯领域 specimens，不是原生 exweb 业务 gold。
- Portal build/lint/i18n、tracked release hygiene 与 diff check 退出0，独立 PG/私有 MinIO smoke success（`http-locator-record-panel-{import-final-build,import-final-lint,i18n,hygiene,smoke}-20261011.log`）；主包 **1240.98kB /gzip335.62kB** 的 >500kB 警告保留。
- 新浏览器首批终态退出1：**2 failed /9 passed /1.9m**（`http-locator-record-panel-e2e-20261011.log`）。失败是明确 Python 3.9 协议 fixture 中的 `Z` 时间后缀，不改生产归档校验；修正为生产使用的带时区偏移 ISO 格式后另起独立批，原失败/trace 保留。
- 修正时间格式后的导航/RunPlan 浏览器批 **session19756 已终态退出0：11 passed /3.4m**（`http-locator-record-panel-e2e-time-fixed-20261011.log`）。覆盖独立登记默认折叠、创建 ACK 丢失/查找暂不可用、显式重新确认、确认 ACK 丢失后的只读恢复、刷新、旧上游只读、归档篡改/撤权隐藏和零重复写入；英文浅色与中文深色的桌面/390px 四张截图已实际回读，未新增横向溢出。真实隔离 PG/MinIO 提供来源/上下文底座，模型、计划、审阅、原生构建/环境/locator transport 仍明确为 UI protocol fixtures，不证明原生 exweb 目标执行。
- JSON 修正后的 canonical PG/私有 MinIO 原生专项 **session26792 已终态退出0：1 passed /1110.12 秒**（`http-locator-record-native-json-fixed-20261011.log`），wrapper67829/pytest67837 已退出。真实 TTL 拒绝、完整原来源解析/归档、晚期 Record/Audit/Outbox 同事务故障回滚、独立历史/Agent/SSE 回执、原命令重入不再解析、实际 FK/append-only/非空降级、损坏拒绝和撤权先于私有读取均验证；上游模型/业务 oracle 是明确协议 specimens，不是外部模型质量或 exweb 原生运行。
- 新加载标准 API/runtime/Compose/DDD/Portal 集 **session51850 已终态退出1：7 failed /320 passed /1 warning /283.13 秒**（`http-locator-record-panel-standard-20261011.log`）。七个失败 ID 与前 `http-locator-record-standard-20261011.log` 完全一致，仍是发布/旧闭环/最新 US 选择/失败 blocker/资产恢复，不减少 blocker、恢复虚构分数或放宽测试来标绿。隔离 browser/smoke 四个端口已无 LISTEN，测试临时资源由原 harness 清理。

固定 exweb **session37906（wrapper67843/pytest67900）** 已结束，日志确认 **1 passed /2496.74 秒**，相关进程不存在。独占报告 `exweb-http-locator-record-json-fixed-20261011-v2.json` 已实际回读：commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`、126完整原 Git/私有 MinIO blob、725冻结代码成员及7条 observed 静态 route。独立记录 `c2cd2add-970e-5d55-ba2a-51b548ef2132` 的 artifact/report/inventory 分别为 `sha256:05572134a553600246270624dd0e7e88856f00f64321450c0bfbfbd005b22433`、`sha256:30671570b7fa06888d713792931cdfe26344c2015ea3d2fde632ddd23f80c979`、`sha256:19be566478ff5c72c140d4fe54c06a41190276c77c214569635c64579da8d188`，新记录 source bytes/durable verified=true，历史不再解析。原4用例/4 capture/8 request 全部保留，8 request 仍 unresolved/static_match=0；旧查询 durable=false，新旧 runtime/fixture/execution/business 权威仍 false，正式计数仍零。上游模型/业务 oracle/reviewer 是协议 specimens，不是原生 exweb 目标执行或业务 gold。

运行时/DOM locator、fixture setup/cleanup、独立执行授权、durable dispatch/cancel/recovery、真实逐用例覆盖到放行仍未全部贯通。五用途/旧链切换、自动项目 delta/overlay/merge、完整预算/owner 恢复、独立 gold、多语言/Provider 生命周期、安全/容量/恢复/性能/试点与完整 P0-P6/V1 门禁保持原必需范围；标准旧七项失败尚未解决。未迁移开发库、重启开发服务、commit/push，Goal active。

## 固定源码 HTTP 定位与 Portal（2026-10-11）

新增[原请求与冻结源码定位](./http-locator-evidence.md)：版本化 Java 静态 mapping 规则、替换式来源/解析 port、纯领域的完整 method/path 匹配、私有 HTTP/canonical query、原存储观察回放及元数据 Agent/SSE 保护。全部原 code binding/revision、文件与 supporting spans 保留；条件不明、语法失败、重复声明和 browser DOM 不强行当作匹配。新查询不调用模型、构建、Docker 或 Runner；所有 runtime/fixture/execution/business 权威 false，正式覆盖计数零。完整 ToolResult 观察不是独立追加式 locator 事实，`durable_locator_evidence_verified=false` 未升级。

Portal 在已保存计划下新增折叠入口，显式点击后才读取；逐用例/原 request 显示静态状态及源码/Controller/类级证据。完整计划、inventory/report 摘要与全动作清单及派生候选独立核验。验证完整结果后每页展示20项，不删除原分母；无可见滚动条、窄屏折行，完整 inventory 延迟渲染。重新读取、撤权或完整性失败隐藏旧敏感父链，不触发写入/确认/重建，不写 sessionStorage。实际深色390px与浅色桌面截图已回读。

当前终态证据（选择集重叠，不相加为项目总数）：

- 领域/应用/旧分析兼容/DDD及容器接线 **205 passed /4.68 秒**（`http-locator-unit-wiring-20261011.log`），disposable PG；前一批204项未包含HTTP容器接线测试。
- 真实 canonical HTTP/PG/私有 MinIO、v2 原计划定位/只读历史/Agent元数据/事件脱敏/篡改拒绝/来源撤权专项 **1 passed /490.78 秒**（`http-locator-native-api-wiring-20261011.log`）。源码底座、原上游事实和权限真实，模型/业务oracle是明确协议夹具，不执行目标。较长运行不是 p95 门禁通过。
- 全部 Portal contracts **1091 passed /10354.780833ms**（`http-locator-portal-contracts-full-final-20261011.log`），其中25项新增定位协议/渲染测试：原生 Python parser/matcher生成独立协议specimen，v1/v2、request conditions/browser gap、重哈希篡改、完整分母、20项DOM和私有GET/abort。前一22项及1088全量批加载早于最后三个渲染测试。
- 浏览器 **2 passed /2.8m**（`http-locator-portal-e2e-20261011.log`）：真实隔离PG/MinIO来源及上下文为底座，计划/模型/审阅/locator transport 为明确协议specimens；验证英文/中文、深浅色/390px、默认折叠、Controller支持位置、只读重载、坏摘要/撤权清除父链。没有将协议源码当作exweb运行定位。
- Portal build/lint/i18n、release hygiene、diff check退出0；Portal边界 **25 passed /0.16 秒**；smoke成功（`http-locator-smoke-20261011.log`）。主包 **1227.40kB /gzip332.74kB** 的 >500kB 警告保留，hygiene仅覆盖tracked文件；测试独占端口已无LISTEN，开发服务和数据库未迁移/重启。
- 标准API/runtime/Compose **7 failed /165 passed /1 warning /242.06 秒**（`http-locator-standard-gates-20261011.log`），七个失败ID与`http-binding-formal-standard-20261011.log`完全一致；旧闭环/资产等待、最新US选择、失败blocker与放行证据仍未修复，完整V1不绿。

原两项原生/固定exweb专项分别在229.47秒和761.11秒退出失败：应用容器遗漏`run_plan_locators`，导致服务虽已组装但HTTP依赖无属性；原日志保留。现补齐容器类型/factory及独立接线检查，两项已重新通过，没有删除失败或把模型夹具当作修复。

固定exweb修复后同选择专项 **session19024** 已通过原handle回读终态退出0：**1 passed /816.85 秒**（`exweb-http-locator-formal-plan-wiring-20261011.log`）。独占报告`exweb-http-locator-formal-plan-wiring-20261011-v2.json`已回读：固定commit `fe5827f6b76f77ef34918d8b452ee823142332dc`与tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`，全部126原Git blob/私有MinIO文件与定位inventory摘要一致，725固定代码成员、7条observed静态route。原4个用例/4个capture及全部原step/oracle/source pins保留，8个request全部unresolved、static_match=0；report hash为`sha256:b1269f953c0d2df3cb7b6f101702624751e9d2fc9111c79d2160d073ebe0a5ec`。真实源码与PG/MinIO链已验证，伴随第二代码源/需求/用例、模型、reviewer及oracle仍是明确protocol specimens；没有外部模型、目标执行或独立business gold。该测试证明原完整字节的定位链与缺口保留，不证明8个请求已匹配或完整P5/真实业务闭环。

真实exweb会话路径是`/api/v1/finance/chat/sessions`，不是协议脚本`/sessions`；produces条件保持未解决。独立locator登记、运行时/DOM定位、fixture、执行授权、owner/lease/取消恢复及真实覆盖到放行继续交付。五用途/旧链切换、自动项目delta/overlay/merge、独立gold、多语言/Provider、安全恢复/容量/性能/试点和完整P0-P6/V1门禁保留原目标，Goal active，无commit/push。

## 显式 HTTP v2 正式脚本与计划消费（2026-10-11）

将[响应绑定](./http-response-bindings.md)从执行器扩展到正式脚本预算/确认、原生输出准入、独立逐动作/oracle 审阅、RunPlan 编译/归档、构建 pin、命令派生及私有观察回放。Portal 默认 v1，只有明确选择 v2 才发送新协议字段；变化使旧前端确认及后端模型消息/预算摘要失效。v1 请求没有新增 null/default，旧 envelope/原工件不重写。v2 proposal、RunPlan 和 artifact 均明确版本，不能从不可信结果自动升级或重哈希后降级。capture 只作为独立审阅的 action，不新增 oracle、规范批准、执行授权或覆盖计数。

前端 v2 JSON 参数曾只使用 `JSON.parse`，与后端/Runner 拒绝重复键、不安全数字和超深容器的规则不一致。现复用共享严格解析器，显式 HTTP 限制不改变原健康 JSON 默认契约；body/headers/oracle 和原生模型回复的重复解码键均不能通过。原数值字符串保留，不能用 JavaScript 舍入后的数字替换独立 oracle。新负例同步重算 raw/response/archive 全部摘要，仍拒绝；v1 command 的 capture 降级也在发送前拒绝，不等网络返回才发现。

固定 exweb 新专项 `exweb-http-binding-formal-plan-20261011.log` 已终态退出 **0：1 passed /7 deselected /714.40 秒**。独占报告 `exweb-http-binding-formal-plan-20261011-v2.json` 已回读：commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`，全部 **126 Git blob** 与私有 MinIO 归档一致，**725 个固定代码成员**。正式 v2 计划含 **4 个用例/4 个 capture 动作**，保留原 case/step/oracle/proposal 和完整来源 pins，独立 reviewer 与生成账号不同；一条脚本模型调用、一个计划，第二次 GET 不重发。真实 Git/PG/MinIO 与伴随需求/用例、模型、预期结果的显式 protocol specimens 分开：没有外部模型、真实目标执行或业务 gold，执行/通过计数仍 0。它不能与另一批实际 exweb JAR 开发探针拼成同一次正式执行。

本增量已回读终态的选择集（相互重叠，不相加为项目总数）：

- 严格 JSON 加固后，领域/应用/脚本/RunPlan/观察与 DDD 边界 **555 passed /9.56 秒**（`http-binding-formal-strict-json-domain-final-20261011.log`），disposable PG；前一加载批 551 项未含最终 headers/oracle 负例。
- 最新全部 Portal contracts **1066 passed /5637.143916ms**（`http-binding-formal-strict-json-all-portal-final-20261011.log`），保留 v1 与原健康 JSON 兼容；原 1062 批未含最后四项负例。
- 新版本必须重新精确确认的真实 HTTP/PG/私有 MinIO 专项 **1 passed /26 deselected /127.92 秒**（`http-binding-formal-confirmation-api-20261011.log`），旧确认在模型/预留之前拒绝，另行预览才允许一次生成；model transport 是明确协议 fixture。
- Runner **106 passed /4044.506709ms**（`http-binding-formal-runner-20261011.log`）；本轮之后未改 Runner 源码。前一前端加载批四项深浅色/移动端、协议确认失效与只读恢复浏览器专项 **4 passed /2.3m**（`http-binding-formal-e2e-20261011.log`），加载早于严格 JSON 修改，不冒充最终浏览器批。
- 最新 Portal build/lint/i18n、release hygiene、diff check 退出0，边界 **25 passed /0.15 秒**，严格解析后的 smoke success（`http-binding-formal-strict-json-*20261011.log`）。主包 **1214.13kB /gzip329.13kB** 的 >500kB 警告保留；hygiene 只检查 tracked 文件。
- 标准 API/runtime/Compose **7 failed /165 passed /1 warning /247.90 秒**（`http-binding-formal-standard-20261011.log`），与上一批七个失败 ID 完全一致。发布证据不足、旧闭环/最新 US/资产等待超时和 blocker 数量差异未解决，没有降低断言、恢复虚构分数或删失败来标绿；完整 V1 仍失败。

严格解析后的最终浏览器批 **session78172 已终态退出0：4 passed /2.7m**（`http-binding-formal-strict-json-e2e-20261011.log`）。覆盖 v1/v2、英文/中文、深浅色/移动端、协议变化清除确认、独立 capture 审阅、计划/build/environment/health 祖先和失联后只读恢复。实际 PG 与来源采集是底座，模型/审阅/计划/构建 transport 是显式协议 fixtures，不证明外部模型质量或真实目标业务。smoke 独立批也已退出0，均未使用开发库/服务端口。

原生 Node/PG/私有 MinIO、v1/v2 保存计划观察与晚期事务故障组合 **session4872** 已通过原确切 handle 回读终态退出0：**54 passed /3 skipped /11700.58 秒**（`http-binding-formal-native-api-20261011.log`）。该批加载早于最终严格 JSON 负例与本轮 locator 接线，不能证明新变更。前一领域批曾暴露 v1 capture 未在 transport 前拒绝及旧测试错误顺序，失败日志保留；修正 wire 和独立 receipt 断言后最终领域批才全绿。没有开发库迁移、开发服务重启或 commit/push。

独立 fixture/locator、执行授权、owner/lease/取消恢复及真实逐用例覆盖到放行仍未全部贯通；五用途/旧链切换、自动项目 delta/overlay/merge、独立 gold、多语言/Provider 生命周期、安全/恢复/容量/性能/试点与完整 P0-P6/V1 门禁保持原必需范围，Goal active。

## 单任务 HTTP 响应绑定与实际 exweb 验证（2026-10-11）

新增[显式 HTTP v2 响应绑定](./http-response-bindings.md)。原 static-path Runner 需要外部创建资源并把 session ID 填回后续 job，现在同一任务可从原 2xx 严格 JSON 提取 ASCII 资源 ID，只用于后续完整路径段；无前向引用/重赋值/动态 origin、query、header、body 或 oracle。capture 为 action，不增加 assertion/正式覆盖。回执固定原模板 hash、解析路径/input hash、binding/source response/value hash；API 从完整原响应重新提取，不接受同步改写所有派生摘要的伪造 ID。服务认证、固定 host/DNS、无代理/重定向/自动重试、原预算和截止时间保留。v1/browser wire/hash/工件不变，正式 script proposal/RunPlan v1 明确拒绝新动作，不隐式改写旧批准。

实际固定 exweb 最终批 `exweb-native-http-bindings-final-20261011.json/log` 已终态退出 **1**：commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、全部 **126 Git blob**、JAR `sha256:53e844acb746bca6e88d23e2d70beae334a5c75bfd46495e9a6c235b57e5bd84`。三项有界 canary 和七个生产 HTTP engine 任务均获得原响应，整体 **17/24 通过、7 项失败**。v2 单任务 create/read/close 有一个原响应 binding、三个实际请求和 **11 个通过的开发断言**，不需要外部 fixture ID；v2 闭环再读取有 12 个观察断言，11 passed/1 failed，实际关闭后读取仍 500。原跨用户/租户错误状态、关闭状态、PG 未持久化及重启丢失失败未改源码或断言来消除。

首批误填 Redis 镜像 ID 被 image inspect 拒绝，source_verification 阶段 **0/0** 检查、尚无目标部署，失败 JSON/log 保留。修正使用实际本地不可变 image ID 后的 current 批也是真实 17/24；随后只修正 v1 单任务是否依赖外部 fixture 的报告元信息再独立加载 final。current JAR 为 `sha256:160fd86843843c21e1f7c2d17336bf1317723fa38b38afd940d5e0ce99f7dfa2`，不同批不是同一次原工件，不合并结果或宣称可重现构建。

清理后独立只读 `exweb-http-binding-replay-20261011.log` 重验完整原请求/result 字节摘要、source inventory 摘要、固定 JAR metadata、七任务全部响应/manifest/binding/oracle，`runner_redispatched=false`。final owner prefix `nasus-exweb-f39e8e3ce3904e0c` 的 cleanup verified=true/remaining=[]，实际 Docker name/owner 容器及网络列表均为空。该本地开发报告不是 canonical 执行或永久私有 MinIO 业务证据，target_build/business_coverage/execution/release authority 仍 false。

新加载终态验证分别为：

- 领域/脚本兼容/原 RunPlan/归档/探针/DDD 选择集 **544 passed /8.69 秒**（`http-binding-domain-final-20261011.log`），disposable PG；纯模型/协议 specimens 不当作业务 gold。
- 实际认证 Node Runner `/v1/jobs` + 私有 MinIO 联测 **16 passed /22.42 秒**（`http-binding-native-final-20261011.log`），包括随机资源同任务链、失败/截止时间、原 command/result 新实例重验及认证/版本拒绝；目标为明确本地 HTTP fixture，不是 exweb。
- Runner 完整选择集 **106 passed /2389.411958ms**（`http-binding-runner-final-20261011.log`），包括真实 HTTP binding 流及全部原 browser/HTTP/auth/取消回归。
- 标准 API/runtime/Compose 集 **7 failed /165 passed /1 warning /247.79 秒**（`http-binding-standard-20261011.log`）。失败 ID 与前 `original-health-record-standard-verified-paths` 七项一致；发布证据不足、ready 仍 blocked、两个 blocker 数量与旧预期不符、质量闭环/资产恢复等待超时未解决。未放宽测试、恢复虚构分数或减少 blocker，标准门禁仍失败。
- 浏览器导航/RunPlan **11 passed /1.7m**（`http-binding-portal-e2e-20261011.log`），smoke success（`http-binding-smoke-20261011.log`）；Portal build/lint、release hygiene 和 diff check 退出0。主包 **1209.84kB /gzip327.65kB** 警告保留。前端未改，浏览器协议 fixtures 不证明新的 HTTP v2 正式 UI/RunPlan 已接通；范围重叠不相加为项目测试总数。

所有本批进程已终态，隔离浏览器/smoke 端口无 LISTEN。没有开发库迁移、开发服务重启、commit/push。下一步继续显式版本化 script/mapping/review/RunPlan 消费链、独立执行授权与 owner/lease/取消恢复；fixture/locator 和真实逐用例覆盖到放行未全部交付。原 P0-P6 的五用途/旧链切换、自动增量/overlay/merge、独立 gold、多语言/Provider 生命周期、安全/恢复/性能/容量/试点和完整 V1 绿色门禁保持必需，Goal active。

## 实际隔离对照与 canonical 健康终态（2026-10-11）

新增[有界隔离 canary](./native-isolation-canaries.md)，显式开发 opt-in 在实际固定 exweb 目标上比较 fresh 正向 HTTP/宿主文件对照、原目标拒绝及 socket 不可见。完整原实例/JAR、对照启动 epoch/网络成员和源码前后固定，七份原响应保留字节/hash；任何正向失联、坏类型、部分响应或换 epoch 不算隔离成功。新资源在创建前记入清理名单，额外网络独立删除；不访问互联网、开发服务、真实开发文件或 socket，不自动授予正式执行或改旧 0105/0106 记录。

实际 `exweb-native-isolation-canaries-20261011.json/log` 已终态退出 **1**：固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`、126 个 Git blob、原 JAR `sha256:0541660ded51b8d1b9cc60fda708e5abf5d1c711871c53c35124cbd80f9f4cea`。三项 canary 通过，网络正向前后各 64 字节且同 marker，目标 curl7/0 字节；host marker 对照同字节，目标 absent20 字节、socket absent27 字节。独立只读重算七份完整响应 hash、原 JAR/环境摘要和 cleanup 成功；cleanup verified=true/remaining=[]，owner 容器列表为空。整体 **12/17 通过、5 项失败**，保持 exweb 权限/关闭错误状态及 PG 持久化/重启丢失缺陷，不改源码或断言来标绿。仅这三个有界观察，全部出口/宿主接口隔离准入、canonical 持久观察和正式执行消费仍待交付。

协议/原脚本/边界新加载批 `exweb-isolation-canary-contracts-configured-20261011.log` 为 **69 passed / 0.34 秒**，在 disposable PG 上执行，非 Docker 或业务 gold。首次未配置 test PG 的启动拒绝保留日志，未进入测试。py_compile、release hygiene 和 diff check 退出0，前端未改；最新健康 Portal pinned-read smoke 已回读 success、导航/RunPlan 11 passed /1.7m，不将重叠选择集相加成总用例数。

原 native canonical health **session5491 已终态退出0：1 passed / 4017.41 秒**（`exweb-canonical-health-record-current-20261011.log`），wrapper32239/pytest32261 均不再运行，独占 JSON 已实际回读。固定 commit/tree/126文件，原 MinIO JAR `sha256:6b6471b6f181809fd26376b5cfd073f9231a8276893ca011fbb81f2040f91f36`，实际自有 Java/PG/Redis 经独立新确认得到0106健康记录 `081a923d-46b0-51ac-a73b-93569ba3a979`、health hash `sha256:d57d5cd195628fe3298180897727ffc5682094e7b1f75bf16bfd402313b396c6`。三项响应2/5/19字节，健康true，原0105 dependency flag保持false。清理后原私有 GET/query 未再次 Docker；cleanup verified=true/remaining=[]、原代码导出删除、实际 owner 容器列表为空。该批真实 PG/MinIO/构建/目标与模型/调度/业务 oracle specimens 分开，external_model_called=false、正式执行/通过0、full_quality_closure_verified=false。

上述 canonical 批没有本轮 canary，JAR也不同；不能拼接两批工件为同一次正式执行或可重现构建。完整 P0-P6/V1 保持未完成：五用途/旧链切换、自动增量/overlay/merge、独立 gold、多语言/Provider生命周期、fixture/定位、独立执行授权/持久生命周期、真实覆盖到放行、安全/性能/试点仍待交付。标准门禁原七项失败未降低要求。未迁移开发库、重启服务或提交/push，Goal active。

## 原实例健康终态与独立健康登记（0106，2026-10-11）

后续已重新核验独立 canonical PG/私有 MinIO 批终态 **1 passed / 1229.70 秒**（`original-health-record-canonical-pg-20261011.log`，退出 0），原 wrapper 31961/pytest 31979 已退出。该批覆盖原确认 TTL、晚期事实/审计/Outbox 整事务回滚、私有历史及 Agent 回执、实际 FK/append-only/非空降级、损坏和撤权；builder/model/Docker response 明确为 protocol specimens，不能替代真实 exweb 健康归档。

纠正文件路径后的标准集也已终态 **7 failed / 184 passed / 1 warning / 254.53 秒**（`original-health-record-standard-verified-paths-20261011.log`，退出 1），原 32992/33014 不再运行。失败 ID 和原因仍为原 release/quality loop/最新 US workspace/failure/资产恢复七项，没有新 health composition 失败；未恢复虚构分数、减少 blocker 或降低旧断言来获得全绿。该结果不证明完整 V1。

本轮接入[Portal 独立健康审阅](./native-target-health.md#portal-独立审阅)：环境与健康共享 canonical 恢复实现，但原命令/确认、tool/UUID/receipt、query key 和 sessionStorage 各自隔离。原始 inventory/响应默认折叠，前端核验全部原 hash、实例、字节及严格 JSON 后派生三项结果；有效 DOWN 如实异常，记录不授予执行许可。丢失回复/刷新只读回原命令，上游失效不新增探针，撤权或坏归档隐藏父计划及私有内容；存储只含原账号/项目/父输入 ID/hash，不是全量历史库。

新前端/兼容专项 **92 passed / 1516.567834ms**（`health-record-portal-contracts-20261011.log`），全 Portal contracts **1036 passed / 5546.605167ms**（`health-record-portal-all-contracts-20261011.log`），边界 **159 passed / 3.69 秒**（`health-record-portal-boundaries-20261011.log`）。浏览器导航/RunPlan **11 passed / 1.7 分钟**（`health-record-portal-e2e-20261011.log`），包括深浅色健康异常、独立确认/失联恢复、撤权及移动宽度；四张健康截图已实际查看，响应折叠且无新增横向溢出。smoke success（`health-record-portal-smoke-20261011.log`），build/lint/i18n 退出 0（`health-record-portal-build-fixed/portal-lint/portal-i18n-20261011.log`）；初次 build 的实例索引 TS 类型错误保留在失败日志，修正后重新构建，主包 1209.56 kB / gzip 327.59 kB 警告仍在。范围重叠，不相加为项目测试总数。浏览器 transport 仍是明确协议 fixture，实际 PG/MinIO 与原生 exweb 另取证。

后续加强 direct archive read：即使调用方未先恢复，原字节 GET 前仍核对 canonical tool、真实确认布尔值、原全部父请求/hash、result invocation/object refs；错工具、换父请求或借环境 receipt 冒充健康记录先拒绝，无私有 GET。最终新加载完整 contracts **1036 passed / 6078.851958ms**、导航/RunPlan **11 passed / 1.7 分钟**，build/lint 退出 0（`health-record-portal-{all-contracts,build,lint,e2e}-pinned-read-20261011.log`），主包 1209.84 kB / gzip 327.65 kB。前述旧批不替代新 read 边界验证；初次类型失败和包警告保留，完整 P0-P6/V1 未完成。

新 native exweb canonical health session5491 后续已终态退出0，实际 **1 passed /4017.41 秒**，原32239/32261已退出，详见顶部独占 JSON/清理/原健康证据。以下运行中描述仅保留之前观察，不能继续作为 live。没有开发库迁移、开发服务重启或提交/push。

原内部健康专项已确认 **1 passed / 2590.25 秒**（`exweb-canonical-original-health-current-20261011.log`），wrapper 29952/pytest 29977 均已退出，原 JSON 已实际回读。固定 exweb commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 和完整 126 个 Git blob 经实际原生构建、MinIO JAR 回读、自有 Java/PG/Redis 与生产 registry/inspector 运行三项固定健康探针。原 JAR 为 `sha256:ebfb0f316c6a9068b7c6682c308e83fff8147d97839ec4c737285efca7b490ea`，health hash `sha256:afff3a8831d7d8e686a95ae413bca642256580b855ac7b8d7c6b286bee4ad3d0`。SQL/PING/actuator 响应 byte count 分别 2/5/19，原 0105 环境记录不变；清理报告 verified=true/remaining=[]、registry/原导出删除，实际 owner 容器列表为空。模型/调度/业务 oracle 是 protocol specimens，正式 executed/passed 为零，业务覆盖和完整闭环为 false；不同批 JAR hash 不同，未证明可重现性。

该成功批加载早于 0106，明确 `health_is_internal_not_independently_registered=true`，不能用于证明新健康登记已通过。本轮新增 [独立健康归档](./native-target-health.md)：`quality.run_plan.record_health` / `query.quality.run_plan_health_record`、private/no-store 原历史 GET、私有 MinIO 完整响应归档、PG 原 Plan/build 复合外键和独立 command/actor、审计/脱敏 Outbox 原子登记。追加式新表不回填或改写 0105；无 inventory/响应 JSON 导入。未确认/过期/撤权/换原输入拒绝，真实有效 DOWN 可如实归档；历史/同命令回读不重做探针，Agent 再次消费 metadata 回执需重新授权。

最新纯领域/应用/原实例/registry/DDD/ORM 注册选择集 **394 passed / 6.82 秒**（`original-health-record-agent-current-20261011.log`）。初期测试 specimen 遗漏必填 summary 导致 **1 failed / 148 passed**，补足原 DTO 后通过，未放宽生产校验；264 项前批加载早于 Agent 查询接入，不相加为总量。Portal build/lint 已确认退出 0（`original-health-record-portal-build-20261011.log`、`original-health-record-portal-lint-20261011.log`），主包 1197.91 kB 的警告保留；`git diff --check` 通过。新的实际 canonical PG/private MinIO 事务/历史/撤权批 `original-health-record-canonical-pg-20261011.log` 已启动，最近核验 wrapper 31961/pytest 31979 实际存活，尚无终态，不能记为通过。专项迁移仅在 disposable PG，不修改开发库或重启服务。

本轮追加的 Agent/原 receipt 选择集 **218 passed / 2.62 秒**（`original-health-record-agent-receipts-20261011.log`）；显式新 health 表名/字段/完整 FK、独立 PostgreSQL DDL 注册和新原生边界 **5 passed / 1.15 秒**（`original-health-record-orm-current-20261011.log`）。范围重叠，不加成项目用例总数。浏览器导航/RunPlan 为 **11 passed / 1.8 分钟**（`original-health-record-portal-e2e-20261011.log`），Portal contracts **983 passed / 6276.242125ms**，Runner **69 passed / 3270.023291ms**，smoke success；各日志前缀为 `original-health-record-`。正式 `npm run test:i18n` 已退出 0（`original-health-record-i18n-verified-20261011.log`）；此前不存在的 `i18n:check` 和错误 `test_release_readiness_port.py` 文件导致命令失败，日志保留，标准集未执行不能称通过。纠正实际 `test_release_readiness_application.py` 后的标准集 `original-health-record-standard-verified-paths-20261011.log` 已重载运行，wrapper 32992/pytest 33014 核验存活；尚待终态，不用前批门禁替代新加载结果。

新版原生 exweb 连续测试已加入独立 canonical health pending/confirmation、实际原探针再归档、PG/MinIO 完整新记录与 0105 不变、清理后无 Docker 的 GET/query 历史。新批 `exweb-canonical-health-record-current-20261011.log` / 同名独占 JSON 使用 0106 disposable PG；wrapper 32239/pytest 32261 已核验实际运行，尚无终态。不得重启或以旧内部观察报告冒充新链通过。

0106 独立健康 Portal 审阅和实际 canonical 原生登记已取得各自证据；本轮三项有界 canary 另取证。完整物理出口/宿主隔离准入、fixture/locator、执行 owner/lease/取消恢复、真实逐用例覆盖回流和旧链切换继续交付。前批标准门禁仍有同一七项质量闭环/放行失败，完整 P0-P6 与 V1 未完成，Goal active。

## 原环境 Portal、原生登记终态与 exweb 连续验证（2026-10-11）

原 RunPlan 构建关联面板已接入[独立环境审阅](./native-environment-records.md#portal-独立审阅)：原 local/8080 计划与关联的 current 输入、新独立勾选、严格归档和 parent hash 核验、默认收起的私有 inventory、上游变化和撤权时隐藏旧内容。创建或确认丢失回复后仅 GET 原命令，不重发写入；sessionStorage 不保存 inventory、URL 或凭据。配置观察仍是历史，正式执行/覆盖均为 false/零。

已重新核验终态的选择集（范围重叠，不相加为项目总量）：

- 0105 实际 canonical PG/private MinIO 登记 **1 passed / 1199.01 秒**（`environment-observation-records-native-acl-final-20261010.log`）。包括确认 TTL 在原生工作前拒绝、晚期 Outbox 故障整事务回滚、完整原归档/脱敏事件重放、实际 FK/append-only/非空降级拒绝，以及来源撤权先于私有字节。builder/model/Docker metadata 是明确 protocol specimens，不是 exweb 部署或业务 gold。此前 1574.32 秒的 keyword-only 参数错误和 1857.96 秒的策略 helper 错误均为失败终态，不再记作运行中。
- 领域/应用/边界组合 **521 passed / 6.64 秒**（`environment-record-combined-domain-final-20261010.log`）；Portal contracts **983 passed / 5090.053625ms**，Runner **69 passed / 2518.404125ms**，PG/private MinIO smoke success（`environment-record-portal-all-contracts-20261010.log`、`environment-record-runner-20261010.log`、`environment-record-portal-smoke-20261010.log`）。新 ORM 注册测试从 fresh subprocess 解析完整 FK，并编译 PostgreSQL DDL，避免依赖测试的偶然导入顺序。
- 环境/RunPlan/导航浏览器最终 **11 passed / 2.1 分钟**（`environment-record-portal-e2e-original-review-20261011.log`）。前两批各 **2 failed / 9 passed**：第一批未显式选择 local 环境，第二批在撤回审阅后误从当前头重新准备计划。测试改为显式 local/8080 和原 review ID，没有放宽生产 gate。light/dark desktop/mobile 四张截图已实际视觉检查，私有清单默认折叠、内容可换行且无新增横向溢出；浏览器 transport 仍是协议 fixture。
- 旧标准集新增的第八项失败来自测试假设完整 tool_id 在 Planner 内部字串中直接出现。改为实际 decoder 校验完整 ordered IDs 与公开 catalog 严格相等、以及编码说明存在；专项 **1 passed / 1 warning / 3.53 秒**（`environment-record-planner-memory-decoded-20261010.log`）。206.32 秒批及最新 projection 加固后的标准 API/runtime/Compose 均 **7 failed / 165 passed / 1 warning**，最新 **280.78 秒**（`workspace-release-projection-standard-current-20261011.log`），仍是原 release/quality loop/failure/资产状态 journey。未恢复推算分数、删掉失败或绕过正式证据；完整 V1 未全绿。
- 原 JAR 读取/拒绝替换、显式 native opt-in、ORM 注册和 DDD/Portal 边界 **181 passed / 2.53 秒**（`exweb-original-deployment-boundaries-20261011.log`）。这些是无 Docker 的协议/边界测试，不能替代下面的真实专项。

固定 exweb 的真实 canonical 连续专项已确认 **1 passed / 2283.28 秒**（`exweb-canonical-original-environment-record-imports-20261011.log`）：从原 MinIO 构建结果回读 JAR，启动自有 Java/PG/Redis 内部网络，生产 registry/inspector 验证后独立登记完整原环境；清理实际资源及 registry 后原历史仍可重新授权回读，无 Docker 重查。源 commit 为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`、全部 126 个 Git blob，原 JAR 为 `sha256:4339de4b44e78eb834be248a32fed98eb9412bb010959bc2ab3331e6f856888d`。原 JSON 已实际回读，cleanup verified=true/remaining_owned_resources=[]；原导出 checkout 删除，环境与 native build owner label 的容器列表为空，27157/27187 均已退出。首批缺少 `os` 导入的 **1 failed / 132.05 秒** 保留，不覆盖失败日志。实际构建、PG、MinIO 和 Docker 环境与模型/调度/业务 oracle 的 protocol specimens 分开；不同批 JAR 摘要不同，不声明可重现性或业务 gold。

另修正 Workspace 的真实放行展示漏洞：六条资产 lane 完成不能绕过缺失、错版本、低于 80 分、不合格状态或有 blocker 的原 release assessment。新门禁保留原记录/分数，未评估的部分工作仍 in_progress；只是阻止错误的 ready_for_release 投影，不补造规范、执行覆盖或发布批准。隔离 PG 的 workspace/release/DDD/Portal 选择集 **174 passed / 2.39 秒**（`workspace-release-assessment-projection-pg-20261011.log`）。前两次命令分别是错误文件名和未经 PG wrapper 启动，后者 **171 passed / 3 errors**，由 PG guard 在 SQLite 写入前拒绝；没有修改开发库。新阻断原因已补中文。最新 build/lint/i18n 日志见 `workspace-release-projection-*20261011.log`，主包 **1197.91 kB / gzip 325.18 kB** 的 >500 kB 警告仍保留。

新增[原实例健康检查端口](./native-target-health.md)：复用原计划/构建/source ACL 与私有 registry，实际固定 SQL/PING/应用本地健康响应，完整响应 hash 和确切 container/image/StartedAt，前后重新检查 JAR 与环境。当前 internal use case 已组装，不新增公开执行入口，不改写旧 0105 权威或授予执行权限。最后加载的协议/registry/应用/边界选择集 **364 passed / 4.45 秒**（`original-target-health-registry-boundaries-20261011.log`）；早期 330/351 项加载早于 registry 和 SQL 标识负例，不相加为总数。包含新健康端口的真实 exweb 批 `exweb-canonical-original-health-current-20261011.log` 已启动，最近核验 wrapper PID 29952/pytest PID 29977 实际存活，尚无终态；运行中不能称健康检查已经通过。新 canonical 健康登记、持久派发/取消/恢复和真实覆盖回流仍待交付。

健康服务组装后重新加载的 API/runtime/workspace/release/Compose 门禁为 **7 failed / 184 passed / 1 warning / 207.96 秒**（`original-target-health-composed-standard-20261011.log`，退出 1），仍是同一七项旧闭环失败，未降低要求。本轮 Portal build/lint/i18n 均已确认退出 0（`original-target-health-portal-build-20261011.log`、`original-target-health-portal-lint-20261011.log`、`original-target-health-i18n-20261011.log`）；主包警告保留。`git diff --check` 和新生产/测试文件 py_compile 通过，无新开发库迁移或服务重启。

当前没有真实业务覆盖/放行、完整五用途与旧链切换、自动项目 delta/overlay/merge、独立 gold、全预算/交付恢复、安全容量/性能或试点完成证明。开发库未迁移、开发服务未重启，完整 P0-P6 目标保持 active。

## 独立原环境登记与 Agent 目录预算（2026-10-10）

0105 新增[独立原环境登记](./native-environment-records.md)：单独确认的 canonical 命令通过生产 inspection port 获取完整原 inventory，私有 MinIO 保存固定原请求、原计划/构建/画像/清单/JAR/政策 pin，PG 追加事实与同事务审计/Outbox。历史读和 Agent 回执先重验完整原来源权限，再回读原归档，不再次操作 Docker；普通原 v1 查询仍不产生独立事实。新登记只声明持久原观察，正式执行与覆盖仍为 false/零，不把开发探针 JSON 导入为正式环境证据。

新增工具后发现 Agent 旧目录容量回归：全工具 ID 的重复前缀挤掉高优先级的发布、映射与 RunPlan 工具。初批 `environment-observation-records-agent-event-regression-20261010.log` 为 **4 failed / 135 passed / 1.18 秒**。现使用[Planner 内部无损编码](./agent-tool-catalog.md)，完整 canonical registry、12 项治理契约和原 6999 字节预算不变，公开目录不改类型、不删工具。完整必填字段、确认与作用域校验保留。

当前已确认的选择集（重叠，不相加为项目总量）：

- 原环境/登记/领域与 DDD/Portal 边界 **438 passed / 5.44 秒**（`environment-observation-records-reloaded-final-20261010.log`）。该批加载早于本段目录编码修改，不作为新 Planner 协议证据。
- 目录/Agent/事件初次修复 **158 passed / 1.38 秒**。新增增长和真实 application 调用 specimen 曾为 **2 failed / 195 passed / 1.32 秒**：增长暴露连续同族 ID 仍需分组；写计划 specimen 误用了与真实契约不同的 hash 字段名。修正无损连续分组及 specimen 原字段后，最新 **200 passed / 1.38 秒**（`environment-observation-records-agent-catalog-current-20261010.log`），涵盖完整 ID、坏编码、原预算下 50 项增长、缺参、跨项目与伪造确认拒绝，不代表外部模型理解质量。
- Portal build/lint/i18n、release hygiene 退出 0；contracts **944 passed / 4287.939625ms**，Runner **69 passed / 3078.0125ms**，导航/RunPlan 浏览器 **11 passed / 1.4 分钟**，PG/私有 MinIO smoke success（`environment-observation-records-*20261010.log`）。这些加载早于目录编码；无新环境 UI。主包 **1180.38 kB / gzip 321.48 kB** 的 >500 kB 警告保留，hygiene 只检查 tracked 文件。
- 标准 API/runtime/Compose 本批 **7 failed / 165 passed / 1 warning / 220.54 秒**（`environment-observation-records-standard-gates-20261010.log`），仍是旧闭环/放行、最新 US、失败治理和资产状态七项。没有删除失败、放宽正式证据或恢复推算质量分数，完整 V1 未全绿。

原生 PG/private MinIO/canonical 0105 批 `environment-observation-records-native-pg-minio-20261010.log` 已确认退出 1：**1 failed / 1574.32 秒**。原事实、确认先于 inspector、晚期 Outbox 回滚、完整私有读取和幂等无 Docker 历史已运行，但测试调用 `list_after` 错用了位置参数，在剩余事件/数据库约束/撤权分支前中断，不能称整项通过。修正为真实接口的 keyword-only stream 参数后，最新重载批 `environment-observation-records-native-current-pg-minio-20261010.log` 已迁移隔离库至 0105，正在运行，终态尚未验证；没有重复启动尚存活的旧进程。

先前 0104 原父观察/晚期故障专项 `run-plan-observation-ledger-fault-hit-native-pg-minio-20261010.log` 已确认 **2 passed / 3 deselected / 3100.42 秒**。它加载早于本段 0105，不能作为新环境事实验证。固定 exweb 缓存本轮只读重验原 commit、126 个 Git 文件、两份真实归档 inventory 的当前领域 schema 和原 JAR；没有新目标执行或 canonical 环境事实。已有原生探针仍 **13/19 通过、6 项失败**，未转成正式业务覆盖。

模型/builder/Docker transport 在 0105 专项是明确 protocol specimens；PG/MinIO、canonical 来源链、ACL、审计及 Outbox 为真实组件。它们不证明真实部署、物理出网/宿主拒绝、依赖健康、fixture/locator、独立执行授权或 business gold。完整执行派发/取消/恢复、正式覆盖/放行、五用途/旧链切换、自动增量与 P0-P6 全部退出条件继续保留。开发库未迁移，开发服务未重启，目标仍 active。

## 原运行环境核验与历史回执完整性

2026-10-10 将独立 exweb 探针中的资源检查抽为生产 infrastructure port，并接入 canonical `query.quality.run_plan_environment`。运维私有 registry 固定项目/环境及确切资源；application 经原 RunPlan/构建读取端口核验祖先、JAR、当前输入与权限，公开请求不能选择 URL、容器、路径或内联证明。目标非 root、实际挂载 JAR、capability/rootfs/资源限制、tmpfs 与网络成员均检查。Config.Env/JVM 尾随参数不进入 metadata；读取不是部署或 Runner 派发。契约见[原目标环境](./native-target-environment.md)。

普通回执 GET、列表及 Agent describe 现共同校验严格字段、完成状态、原调用归属和原计划/构建 pin，历史读取不再次操作 Docker。原生 registry 删除后历史仍可授权回读；实时撤权或损坏原输入拒绝。完成回执的权威/计数、目标摘要、政策摘要或 query 被改写均不能返回；批次最后重新核对当前来源范围。工具/审计列表不再吞掉完整性 502 后展示空历史，403 隐藏不可见记录的既有约定保留。共享会话及持久 Outbox 只展示生命周期，不包含原 query 或环境回执。

这仍是历史工具观察，不是完整 inventory 的独立 PG/私有归档环境事实。`durable_native_observation_verified / environment_fully_verified / execution_authorized / fixtures_verified / locators_verified / business_coverage_verified` 等保持 false，正式 automated/executed/passed 为零。物理出网/宿主拒绝、依赖健康、fixture、独立执行授权、持久派发/取消/恢复及正式覆盖回流没有因该查询获得通过。

已确认的实际测试（选择集重叠，不相加为项目总量）：

- inspector/registry/application/exweb 脚本/原回执/Agent/DDD 重叠边界选择 **370 passed / 4.69 秒**（`native-environment-historical-receipts-boundaries-20261010.log`）；历史工具/审计完整性新增后另跑 **339 passed / 4.56 秒**（`native-environment-history-integrity-domain-20261010.log`）。前一批不包含后加的两条平台列表断言。
- 隔离 PostgreSQL + private MinIO + HTTP/canonical/实际 ACL 专项 **3 passed / 9.25 秒**（`native-environment-canonical-api-revocation-20261010.log`）：真实 SQL 结果被篡改时 GET/list 502、持久 Outbox 脱敏、历史不再次查 registry/Docker、QA 降级，以及核验途中真实来源策略/成员变更后零成功回执。原计划读取与 Docker metadata 是明确 protocol specimens，不证明实际 canonical 部署。
- Node Runner **69 passed / 2959.838875ms**；Portal contracts **944 passed / 4026.411834ms**；Portal boundary **25 passed / 0.16 秒**。导航/RunPlan 浏览器回归 **11 passed / 1.4 分钟**，smoke success（`native-environment-history-*` 日志）。build/lint/i18n 和 release hygiene 退出 0；主包 **1180.38 kB / gzip 321.48 kB** 的 >500 kB 警告保留，hygiene 仍仅检查 tracked 文件，不是完整安全审计。
- 当前标准 API/runtime/Compose 门禁退出 1：**7 failed / 165 passed / 1 warning / 219.27 秒**（`native-environment-history-standard-gates-20261010.log`）。仍为旧放行链、最新 US、失败治理与资产状态七项，不删除失败或恢复推算质量分数，完整 V1 未通过。

原 inspector 最初未加载验证时发现语法缺括号；修正后专项发现 SourceAccessDenied（PermissionError/OSError 子类）被包装成 Docker 故障，现取消/撤权 callback 异常保留。首次新增 API 收集错误来自导入不存在的 fixture，下一次来自 fixture 引用了 container 未暴露的 source_access 属性；改用已注入的实际 authorization service，不改生产权限。加固测试随后发现列表原先会吞掉完整性错误，补齐传播后取得上述 3 项通过，没有放宽断言。

固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 Docker 批保留在 `exweb-owned-native-environment-tmpfs-20261010.json`：之前两批构建成功但环境检查拒绝，没有进入业务检查；实际 Docker 将 `--tmpfs` 记录在 HostConfig.Tmpfs 而非保证在 Mounts 中。按原始 metadata 修正后生产 inspector 在实际业务检查前后均通过。原 JAR `sha256:71363df935c54bcddb2931121fcd424a51822b0d862a48b84647c3a69eb1b63a` 保持不变；显式重启使前后 inventory hash 不同。该批仍退出非零，**13/19 通过、6 失败**，cleanup verified=true/remaining_owned_resources=[]；它是独立开发探针，不是维护者业务 gold 或 canonical 执行覆盖。

上一批原父观察 PG/MinIO 联测已经退出 0：**2 passed / 3 deselected / 3390.84 秒**（`run-plan-observation-ledger-native-pg-minio-20261010.log`），它加载早于事件重放修正，不用于证明新增重放。已进一步加强 late-fault：明确验证原事实、全部成员、审计和 Outbox 已在当前事务写入后才触发异常，再检查整体回滚；成功登记另核验实际 Outbox 重放。重新加载的同一批 `run-plan-observation-ledger-fault-hit-native-pg-minio-20261010.log` 已出现一项参数通过，但仍无整组终态，最近已核实 wrapper PID 11618/pytest PID 11625 实际运行，未因静默或观察超时重启。该长测加载于本次环境历史回执加固之前；完整原父组合回归、性能和 P0-P6 退出条件仍待证明。

本批未迁移开发库、重启开发服务、调用外部模型或再次改写第三方 exweb 源码。完整部署/fixture/执行生命周期、五用途、自动增量/overlay/merge、开源 provider 生命周期对照、独立 gold、安全/容量/恢复和试点继续按完整目标交付，Goal active。

## RunPlan 事实事件的只读重放核验

2026-10-10 修复 Outbox 重放原先只从 JSON 构建事件、未核对登记事实的缺口。新的读取在原会话内严格验证 SQL envelope/sequence 与 payload，RunPlan 准备、构建关联和观察登记事件重新核对原 PG 事实/完整祖先、原命令归属和 metadata-only envelope。整页成功才返回；损坏拒绝，不执行写侧 projector/backfill 或补造事实。外部 stream 游标不能跳过当前 stream 的历史。契约见[执行观察](./runner-execution-observations.md#事件重放的只读核验)。它不是目标执行授权、物理响应读取、所有领域 SSE 验证或性能达标的替代品。

当前实际证据：隔离 PostgreSQL 重放专项 **15 passed / 0.92 秒**（`run-plan-event-replay-postgres-20261010.log`），包括正常三个 stream、游标、持久错绑、严格类型、整页拒绝和没有原事实时拒绝且不补写。领域/应用/观察/RunPlan/DDD 重叠选择集 **363 passed / 9.08 秒**（`run-plan-event-replay-domain-20261010.log`），该批加载早于随后增加的一项只读 AST 边界断言；后者及重叠纯 envelope 专项 **37 passed / 0.82 秒**（`run-plan-event-replay-readonly-boundary-20261010.log`）。导航与 RunPlan 浏览器回归 **11 passed / 1.4 分钟**（`run-plan-event-replay-navigation-e2e-20261010.log`）；build/lint/i18n、release hygiene 和 py_compile 退出 0，smoke success（`run-plan-event-replay-smoke-20261010.log`），主包 **1180.38 kB / gzip 321.48 kB** 警告保留。专项数量重叠，不相加为项目测试总量。

正式保存父计划的 PG/private MinIO 重放专项第一次因新测试未导入 `mapping` 等完整夹具链而 **1 error / 1.48 秒**（`run-plan-event-replay-saved-parent-20261010.log`）。修正夹具后，第二次启动的环境变量映射笔误导致隔离 bucket 创建失败（`run-plan-event-replay-saved-parent-fixtures-20261010.log`）；未进入功能测试，不是产品失败或通过。纠正映射后的批次已退出 0：**1 passed / 251.59 秒**（`run-plan-event-replay-saved-parent-verified-fixtures-20261010.log`），包含固定 exweb 原码归档及已保存 canonical RunPlan，但模型、业务 oracle 和环境为明确 specimens，不证明真实部署或业务 gold。事件 JSON 与 SQL selector 同时改变时仍由原事实/命令拒绝，缺失父事实拒绝而不补造，原计划/模型调用数保持不变；总 suite 时长不是单请求性能。标准 API/runtime/Compose 重跑已退出 1：**7 failed / 165 passed / 1 warning / 232.81 秒**（`run-plan-event-replay-standard-gates-20261010.log`），仍是旧闭环/放行、最新 US、失败治理及资产状态七项，没有新增失败或最新完整 V1 通过证据。

本节记录时原父观察联测仍在运行；现已获得 2 项整组通过，终态和重新加载 late-fault 的新批次见顶部记录。原批加载早于本节重放实现，不能证明新增事件核验通过。本节对应批未重新运行 exweb 原服务、未迁移开发库或重启开发服务。canonical 环境/fixture/执行生命周期、真实覆盖回流、五用途、增量/overlay/merge、独立 gold、安全/容量/性能和真实试点仍按完整 P0-P6 继续交付，Goal active。

## 原用例观察的 PG 登记、审计与事件（0104）

2026-10-10 新增 canonical `quality.run_plan.record_observations` 和 metadata-only `query.quality.run_plan_observations`，以及重新授权的私有原归档 GET。登记通过现有已保存 RunPlan application port 和实际 HTTP response verifier 回读全部原输入，完整 case/action/source-step/oracle 成员与主记录、审计、Outbox 同 PG 事务保存。复合外键固定原父 ID/hash/digest/image/manifest，一次原 attempt 不可改绑；相同命令回读不重发 Runner 或模型，不转移原准备/构建的确认。新表追加式，非空降级拒绝丢弃历史。公开输入不接受任意 URL、内联结果或权威字段，shared Conversation/SSE 脱敏，Agent 回执需重新授权。

新登记保留 `execution_authorized=false / target_build_verified=false / business_coverage_verified=false / canonical_execution_committed=false` 和正式 automated/executed/passed 为零，原观察通过/失败、未知与无结果各自计数。0104 不修改 v1/v2 私有工件。它补齐观察持久化，不代替完整执行授权、环境/fixture/部署构建核验、durable dispatch/cancel/recovery、真实覆盖及放行回流、旧链切换或完整 P0-P6。

当前已确认：领域/应用/原观察/RunPlan/DDD 边界选择集 **267 passed / 7.76 秒**（`run-plan-observation-ledger-domain-verified-20261010.log`）；Node 全执行器 **66 passed / 2539.951792ms**；Portal contracts **944 passed / 3409.332ms**；导航和 RunPlan 浏览器回归 **11 passed / 1.3 分钟**；build/lint/i18n、release hygiene 退出 0，smoke success（同前缀各专项日志）。主包 **1180.38 kB / gzip 321.48 kB** 的 >500 kB 警告保留，hygiene 仅检查 tracked 文件，不冒充完整安全扫描。

最初纯测试把既有完整 7-case 夹具误写成 2，产生 **3 failed / 115 passed / 4.64 秒**；按实际原 roster 修正，不减少输入或放宽生产约束。追加迁移边界后，测试自身目录向上一级错误产生 **1 failed / 266 passed / 7.91 秒**（`run-plan-observation-ledger-domain-final-20261010.log`）；修正文件定位后获得上面的 267 通过。`check:release-hygiene` 不存在，错误日志保留；使用实际 `verify:release-hygiene` 后退出 0，没有把未执行检查当作通过。

标准 API/runtime/Compose 本批已退出 1：**7 failed / 165 passed / 1 warning / 217.86 秒**（`run-plan-observation-ledger-standard-gates-20261010.log`），仍是旧闭环/放行、最新 US、失败治理及资产状态七项；没有恢复推算分数或删除/放宽旧断言。完整 V1 尚未获通过。

disposable PG/private MinIO/真实 Node 的两项原父观察联测正在运行（`run-plan-observation-ledger-native-pg-minio-20261010.log`），隔离库已迁移到 0104，目前不能把运行中进程记为通过。执行期间的实际 PG 只读检查已看到一份 completed 登记命令、1 个 recorded 主记录、4 个原用例成员、1 条独立审计和 1 条 Outbox；主记录 case_count/observed_case_count 均为 4，unknown/no_result 为 0，execution_authorized=false、passed_count=0。回执查询与撤权分支仍待终态，不以这些中间数据证明整组联测通过。目标是本地协议用例，不是 exweb 业务 gold。本轮重新核对缓存原仓库的 commit `fe5827f6b76f77ef34918d8b452ee823142332dc` 与 126 个 Git 文件，但未重新执行 exweb 原服务，也没有开发库迁移或服务重启。以下归档段落记录上一批实现与验证范围，其未交付项不被本次局部登记重新定义为完成。

## 原用例观察归档与未知结果

原 RunPlan 观察已保存完整 case、动作、source step、row/oracle 和 context/scope/generation/mapping/script/review pins，并从实际 HTTP 响应字节重新核验断言。私有 MinIO 归档固定确切已保存计划的 ID、归档 hash 和 plan digest，不重发模型或 Runner。读取前后通过原计划 application port 验证全部来源访问权；同内容的另一份计划不能替换原父工件。完整输入超限或物理证据不匹配整批拒绝，不截断或接受自报 passed。

无 receipt 且没有工件的 native error/timed_out 另存为 `outcome_unknown`，不推断目标没有收到请求，也不当作业务失败。新 v2 集合区分未知结果和没有提交结果的 `not_observed`，保留同批已核验观察；正常原生归档仍保持 v1 字节及摘要。畸形回执、部分工件和伪造 passed 不能降级到未知分支；真实超时的完整回执仍保留 interrupted/not_executed。重放或恢复不得自动重发可能已有副作用的请求。契约见[执行观察归档](./runner-execution-observations.md#原用例与断言观察归档)。

一次归档现在通过原计划端口复用操作内核验过的不可变来源元数据；写后验证不另开重复作用域。嵌套上下文来源和候选召回也显式复用外层，否则它们会丢弃已有核验。四次原访问检查、全部原计划回读及物理响应核验不减少，独立回读另开作用域，失败同样关闭。当前 ACL、角色、AC 批准和审阅头仍实时检查；账号变化独立核验原画像字节。不能据此声称 p95、容量或吞吐门禁通过。

已确认的选择集相互重叠，不累加为项目总量：

- 最新领域、应用、HTTP oracle、RunPlan、读取作用域与 DDD 边界选择集 **360 passed / 6.53 秒**（`run-plan-observation-shared-scope-current-domain-20261010.log`）。包括原 v1 内容契约、v2 未知分离、整批预检查、重新计算外层 hash 后的篡改拒绝、独立读取作用域及四个撤权时点。此前更大且重叠的选择集为 **418 passed / 7.59 秒**（`run-plan-observation-read-scope-nested-domain-20261010.log`），两批范围不同。前批追加预检查时误移动了原测试的局部断言，产生 **3 failed / 386 passed**；恢复其原位置后通过，失败日志 `run-plan-observation-unknown-domain-final-20261010.log` 保留，未放宽生产行为或断言。
- 重新加载的真实 PG 上下文／关联 API **17 passed / 87.42 秒**（`run-plan-observation-shared-scope-live-authority-api-20261010.log`）。新增两项在同一外层会话中撤回 AC、撤销来源访问并切换账号，证明不可变画像复用不会保留批准或授权；独立下一次操作重新读取画像。该批对象存储为隔离本地适配器，不冒充 MinIO。此前未加入这两项的批次为 **15 passed / 66.71 秒**（`run-plan-observation-read-scope-context-link-api-20261010.log`）。
- 实际 Node HTTP／private MinIO 专项 **12 passed / 16.86 秒**（`run-plan-observation-nested-native-http-20261010.log`）。真实 TCP 连接接收确切请求后丢失回复时保留未知结果，重放不再次发送；有完整回执的实际超时仍走物理验证。Node 全执行器 **66 passed / 2312.356417ms**（`run-plan-observation-nested-node-verified-20261010.log`）。目标为本地协议夹具，不是 exweb 维护者业务 gold。
- 重新加载的正式已保存 PG 父工件／真实 Node／private MinIO 两项专项 **2 passed / 3 deselected / 969.54 秒**（`run-plan-observation-read-scope-nested-saved-parent-native-20261010.log`），测试与隔离 harness 进程均已结束。普通及缺失回执均从真实 canonical prepared plan 读取，核验每次归档和独立回读恰好一次原画像工件读取、作用域关闭及原来源在归档前和读取期间撤权。第一版只复用外层时，实际读取仍为 **433 次**，产生 **2 failed / 3 deselected / 690.62 秒**（`run-plan-observation-read-scope-saved-parent-native-20261010.log`）；修正嵌套读取而非放宽一次读取的断言。更早没有该断言的 **2 passed / 1044.38 秒**不能替代新版证据。这些总时长不是单请求性能或 p95。
- 最新 Portal build/lint、i18n 和 release hygiene 退出 0（`run-plan-observation-nested-{portal-build,portal-lint,i18n-verified,hygiene}-20261010.log`），主包 **1180.38 kB / gzip 321.48 kB** 的 >500 kB 警告保留。导航与 RunPlan 浏览器回归 **11 passed / 1.4 分钟**，smoke success（同前缀 navigation-e2e/smoke 日志）。最初 Node glob 路径和 `check:i18n` 脚本名错误未执行相关检查，使用实际 `npm run test:runner` 与 `npm run test:i18n` 后取得上述证据；没有把命令错误计为测试通过。这些页面回归不验证新 canonical 目标执行或外部模型质量。

重新加载嵌套修正后的标准 API/runtime/Compose 门禁已退出 1：**7 failed / 165 passed / 1 warning / 226.74 秒**（`run-plan-observation-nested-standard-gates-20261010.log`）。先前外层修正批同样 **7 failed / 165 passed / 203.51 秒**（`run-plan-observation-read-scope-standard-gates-20261010.log`）。失败仍涉及旧闭环／放行、最新 US 工作区、失败治理与资产状态；没有恢复推算质量分数、删除或放宽旧测试。完整 V1 未获通过。

本批 pytest、隔离 harness 和浏览器进程均已结束，18080/14173/18082/14175 无 LISTEN；`nasus-exweb-` 容器/网络及 `nasus.native-build-owner` 容器检查为空。PG 仍有两份无连接的 `nasus_test_*` 数据库，归属未核验，因此未删除，也不把这些检查当作全部历史测试资源清理完成。

当前归档是内部观察能力，正式 automated/executed/passed 仍为零。canonical 执行授权、环境／fixture 核验、PG 观察事实及审计/Outbox、持久派发／取消／恢复和孤儿工件清理未接通，旧 `run.start` 未切换。固定 exweb 的原生运行是独立开发验证，不与本地协议用例拼接为正式覆盖；五用途、自动 delta/overlay/merge、独立 gold、性能安全容量和试点继续按完整 P0-P6 交付。开发库未迁移、服务未重启，Goal active。

## HTTP 执行器与原响应断言核验

HTTP DSL 草稿原先只能生成和审阅，Runner 只实现浏览器动作。现已加入真正的 HTTP 执行器和独立 `nasus.runner-http-execution.v1`，应用端口显式选择 kind，旧浏览器字节不变。完整输入预检查、operator 确切 host、一次 DNS pin、禁止重定向/代理/自动重试和统一取消/截止时间约束目标请求。实际响应体和 status/headers metadata 各有私有工件及 hash；API 从原字节复核每个已观察 oracle，严格类型、精确小数、重复 key 和缺失 pointer 反例避免自洽假通过。详见[执行观察契约](./runner-execution-observations.md#http-动作与原响应核验)。

第一批 Node 专项 **17 passed / 18 failed**，18 项均是测试误将既有 executeJob 的错误回执契约写成抛异常；已保留底层 validator 抛异常、外层 status=error/无执行回执和零请求三项检查后重跑。第一批原生归档 **7 failed / 12 passed / 20.23 秒**：六项调用 ObjectStorage 时误用了 media_type 参数，POST 夹具没有处理 Node 的默认 chunked body。归档测试改用现有 content_type 端口，生产传输显式设置原 UTF-8 字节的 Content-Length；未降低断言、改为 stub 或跳过失败。

当前已核验、相互重叠的范围如下，不累加为项目测试总量：

- Node 全执行器及真实服务回归 **50 passed / 2313.853666ms**（`http-runner-all-node-verified-20261010.log`）：含原 Chromium 协议、真实 HTTP、四类 oracle、Unicode 请求、零字节、完整字节预算、状态失败、超时、调用方断开、重复 wire key 和 metadata 地址拒绝，已包含 UTF-8 入站解析与 Decimal 无舍入边界修正。后续追加完整观察归档的范围单列，不改写该批数量。
- 领域、应用兼容、脚本审阅与 DDD/RunPlan 边界 **322 passed / 2.68 秒**（`http-runner-domain-boundaries-verified-20261010.log`）。协议响应、篡改、精确 oracle 和工件 roster 检查属于这个选择集，不冒称实际目标运行。
- 全新迁移到 0103 的隔离 PG/private MinIO 原生批 **19 passed / 20.12 秒**（`http-runner-native-private-minio-current-20261010.log`）：8 项 HTTP adapter/私有工件检查，11 项原有浏览器 Run/evidence 持久化及回滚检查。HTTP 用例经过真实 Node 服务与 Python transport，再从 MinIO 回读原响应/metadata/manifest；HTTP 部分尚未写入 canonical RunPlan 执行事实。目标是明确本地夹具，不是固定 exweb 服务或维护者批准的 oracle。

旧 RunOrchestrator 仍默认浏览器，正式 HTTP RunPlan 派发、环境/fixture 核验、独立执行授权、持久任务幂等/取消/恢复及逐 case/oracle 的真实覆盖回流尚未交付。完整五用途、自动增量/失效 DAG、独立 gold、多语言、安全/性能/容量与试点仍属于原 P0-P6 目标，不把执行器绿测替代这些退出条件。开发数据库未迁移、服务未重启，Goal active。

## 原生构建取消面板与独立重试

生产 Portal 已提供独立确认的 canonical `quality.native_build.cancel`，原目标和取消命令分别校验。回执丢失后只按原账号、项目、tool 与 request key 查询，不自动重发或确认；原构建的成功产物不因取消竞争被删除。已完整核验失败或 cancelled 的控制命令、且原目标仍活动时，用户可以显式准备另一次取消；清除的只是确切 sessionStorage 恢复指针，原 PG 历史保留，新 UUID 和重新勾选确认才可发送。未知回执、查询故障或撤权不提供替代写入，重试不启动构建，也不声称物理 cleanup 已完成。

刷新、未知回执和已知失败后的独立重试在 light/dark 下 **6 passed / 2.9 分钟**（`native-build-cancellation-exweb-browser-retry-20261010.log`）；固定 exweb 的真实源码归档与画像使用 PG/MinIO，native builder 和投递回执明确为协议 specimens，不证明 Java 编译或业务执行。原命令 API 专项 **16 passed / 4 deselected / 97.99 秒**（`native-build-cancellation-public-api-current-20261010.log`）；导航/RunPlan 浏览器回归 **11 passed / 4.8 分钟**（`native-build-cancellation-navigation-run-plan-20261010.log`）。前端 contracts **944 passed / 3726.176458ms**，其中取消专项 50 项不另计；只读边界 **94 passed / 1.15 秒**。Portal build/lint/i18n 和 smoke 退出 0；主包 **1180.38 kB / gzip 321.48 kB** 的 >500 kB 警告保留。

首次 lint 的 render ref 读取和 i18n 路径字面量负例已修正，未放宽 gate。已查看两种主题的 390px 截图，目标与原命令 ID 换行、局部滚动正常；这不是完整可访问性审计。取消、原 RunPlan、原生构建与关联表单现已交付，因此下文 0103 中 Portal 待交付仅描述当时批次状态；环境、fixture、真实执行、完整取消恢复与 P0-P6 的剩余范围仍不变。

## 原执行计划与完整原生构建关联（2026-10-10）

0103 新增[固定构建关联](./run-plan-build-bindings.md)。三个 canonical 工具分别预览、独立确认绑定和重新授权回读；原 RunPlan、所有原生构建和全部代码来源通过确切 image/manifest/binding/revision 与归档/receipt 摘要连接。主 JAR、根 pom 和工具链必须匹配原声明。独立追加式主表及完整成员、审计和 Outbox 同事务保存，历史撤回不改写原计划或关联，但阻断当前使用。正常读取和事件核验不修补损坏历史。原生构建授权不继承为关联确认，更不授予目标执行权。

第一批实际 exweb 关联专项失败于测试把底层 `OfflineMavenNativeBuild` 直接接到要求 `policy()` 的应用端口，尚未执行源码构建。改用生产 `ConfiguredNativeBuild` 及显式 operator image/cache 后重跑，未绕过政策、源码或确认校验。失败日志 `exweb-run-plan-build-binding-current-20261010.log` 保留；重跑成功不覆盖该历史。更早两项协议 API 检查为 **2 passed / 887.25 秒**（`run-plan-build-bindings-protocol-20261010.log`），加载早于后来新增的撤回、损坏归档和完整确认时效反例，不能作为这些新检查的通过证据。

当前已实际确认的选择集如下，重叠结果不累加为项目测试总数：

- 最后重新加载的纯领域/application、RunPlan/native build/中断、Agent 目录及 DDD 边界 **211 passed / 4.62 秒**（`run-plan-build-bindings-final-check-20261010.log`）。前批同选择集为 211 passed / 5.25 秒（`run-plan-build-bindings-domain-reloaded-20261010.log`），不重复累计。覆盖完整多源、严格布尔与零覆盖、确切原摘要、剩余门禁和当前使用状态的 Agent 回执指纹；协议 JAR 不作为原生编译证明。
- 重新加载的完整四项 canonical PG/private MinIO 关联专项 **4 passed / 1 deselected / 1745.40 秒**（`run-plan-build-bindings-protocol-final-20261010.log`，句柄 42330 退出 0）。覆盖 populated 父行迁移兼容、实际 schema/FK、不可变和降级保护、原确认及全部时效反例、查询重新授权、历史撤回、归档期间审阅撤回、晚期 Outbox 回滚，以及原构建损坏时拒绝关联正文读取和 Agent 观察。该批加载早于后来双来源夹具的一般化，生产实现相同，新增双来源另取证；不将两个选择集冒称一次完整 suite。
- 双代码来源的真实 PG/private MinIO 专项 **1 passed / 5 deselected / 379.32 秒**（`run-plan-build-bindings-multi-source-20261010.log`）。两个自有 checkout 删除后仍从原归档读取；缺一原构建的预览和 canonical 写入均拒绝且零关联归档，完整绑定保存两份确切来源/构建成员，原计划不变。Builder 明确是协议 specimen，不声称完成真实多仓库编译或目标执行。
- 固定 exweb 实际编译与关联 **1 passed / 4 deselected / 1193.47 秒**（`exweb-run-plan-build-binding-configured-20261010.log`）。测试加载早于双来源夹具的一般化，生产实现相同；使用正式配置适配器、实际无网络 Docker Maven、PG 和私有 MinIO，模型/调度 transport 及业务 oracle 仍为明确 specimens。它不是本轮 Temporal 重放、外部真实模型语义质量或维护者业务 gold 证据。
- 标准 API/runtime/native delivery/DDD/Compose 回归 **7 failed / 296 passed / 1 warning / 370.06 秒**（`run-plan-build-bindings-standard-current-corrected-20261010.log`）。仍是 governance/release、project quality loop、latest US workspace、failure/healing blocker 及 release lane 的七项旧闭环 journey，未删除或放宽测试，未恢复推算质量分数。该门禁是失败状态；没有新的完整 V1 全绿证据。
- 浏览器导航、来源证据及脚本审阅回归 **18 passed / 2.3 分钟**（`run-plan-build-bindings-browser-20261010.log`），smoke success（`run-plan-build-bindings-smoke-20261010.log`）。Portal build/lint 退出 0；边界 **25 passed / 0.14 秒**、contracts **848 passed / 2807.914709ms**，release hygiene 和 git diff --check 退出 0（同前缀日志）。主包 **1100.35 kB / gzip 302.22 kB** 的 >500 kB 警告保留。浏览器没有新绑定表单；hygiene 仅检查 tracked 工件/环境/密钥，不冒充完整安全扫描。

`exweb-run-plan-build-binding-configured-20261010.json` 已实际回读：commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 和全部 **126 个 blob** 核验，JAR **81,124,984 字节**、SHA `sha256:46060f43b4990b9765c18b6f927ee736ba8e5fc85ae9c63067e0fdcd5d39aa5e`。原 MinIO 构建重新核验、独立 canonical 确认、实际 PG 主表/成员及原计划不变均为 true。隔离对象随 suite 清理，JSON 不是永久生产工件。JAR 摘要再次与前批不同，不能声称可重现性或供应链已核验。

0103 不改写旧迁移和父行；已通过的兼容测试在 rollback-only 事务中保留原计划/构建并往返执行固定 DDL，比较全部原父行，随后重新读取原 PG/MinIO 工件。最终 PID 检查确认三个新关联专项进程均已退出，三份自有测试数据库均已删除；`nasus.native-build-owner` 容器列表为空，浏览器/smoke 的 18084/14177/18082/14175 端口无 LISTEN。专项总时长不是单请求或索引的性能基准，不据此声明 p95、容量或性能门禁达标。

绑定的 `native_build_source_attested=true` 不改变原 v1 RunPlan 声明态；execution/通过计数仍为零，source file modes、reproducibility、supply chain、environment、fixtures、execution authority 和 full quality closure 仍未核验。生产 Portal 绑定/RunPlan 表单、旧消费者切换、目标环境与逐 case/step/oracle 运行，以及原 P0-P6 的 gold、多语言、自动增量、全五用途、预算/交付恢复、安全、性能、容量和试点保持完整待交付范围。开发数据库未迁移、开发服务未重启，Goal active。

## 正式原生构建任务与目录预算回归（2026-10-10）

0102 将[原生构建](./native-target-build.md)接入生产组合、canonical ToolRuntime、独立确认、专用 Temporal Worker 和有界 reconcile。新增预览/准备/原结果查询/取消四个工具，原公开 ID 不移除。PG 唯一预留固定原 image/manifest/binding/revision、命令、确认账号、政策和 worker owner/epoch；预留、原结果各与其 Audit/Outbox 同事务，append-only/FK 和 populated downgrade guard 拒绝重写历史。结果已提交时 Worker 恢复只完整回读原产物；仅有预留时不自动重建。独立取消持久化并阻断原 owner 提交，RPC delivered 不是资源清理证明，公开结果保持 `cleanup_confirmed=false`。结果事务与 ToolInvocation 终态目前分离，SIGKILL 孤儿容器恢复仍未接通。

第一批 canonical API 夹具错误使用来源权限 DTO 上不存在的 `source_uri`；修正为 SourceSnapshotRepository 的确切物化 source/binding 对照。下一批降低项目最后管理员被现有安全规则拒绝，测试先授予另一位真实项目管理员再验证降权，未放宽生产规则。最后新增 preview 负测误期望 HTTP 403，实际 canonical Runtime 正确返回持久化的 failed invocation 与 `authorization_denied`、required roles，并未读取预览或构建源码；测试改为核验这个现有契约和零预留/零结果/零 builder 调用。对应中间失败日志保留，不将其报告为构建权限绕过。

标准回归发现新增目录后的两个真实 Agent 预算 API 500，根因是完整目录与 12 个详情的最小元数据超过既定 6999 字节，而非预算持久化失败。原生构建/RunPlan 增加意图相关性，详细契约改为在原排名下选择能容纳全部剩余详情的完整契约；所有注册 ID、必需字段、风险和确认模式不丢失，字节预算和详情数量不扩大。第一轮只调相关性仍留下七个 Knowledge 等选择场景超限；完成字节约束选择后全部相同负例通过，并补充大型填充契约替换及不可能预算的拒绝反例。

当前已实际确认的选择集范围如下，重叠结果不累加为项目测试总数：

- 最新原生构建/中断/RunPlan/Agent 目录/证据与 DDD 边界选择集 **324 passed / 5.30 秒**（`native-build-canonical-domain-final-budgeted-20261010.log`）。更早修复首批 **255 passed / 1.96 秒**，早于最后两个预算反例；它们不是 Java 编译或业务 gold 验收。
- 两个真实 Agent 预算 API 回归及原生构建晚期撤权/取消送达失败，disposable PG/private MinIO **4 passed / 12.84 秒**（`native-build-canonical-faults-budgeted-20261010.log`）。未删除、跳过或降低原预算 API 断言，正式 Runtime 拒绝契约得到独立核验。
- 最终 canonical jobs/delivery/source 专项启用实际 exweb、Temporal、Docker 和私有 MinIO，**25 passed / 278.56 秒**（`native-build-canonical-budgeted-current-20261010.log`，句柄 44262 已退出 0）。覆盖确认/TTL/篡改/权限、PG schema/FK/append-only/downgrade、预留及结果 Outbox 回滚、owner fencing、原产物恢复、独立取消重送、真实 Temporal 终态重试与 history replay，以及实际完整编译和运行中中断。
- 重新加载的标准 API/runtime/job-delivery/DDD/native/RunPlan/Compose 门禁 **7 failed / 304 passed / 1 warning / 340.17 秒**（`native-build-standard-budgeted-current-20261010.log`，句柄 71692 退出 1）。两个新增 Agent 预算 500 已消除；七项仍为先前 release/governance、project quality loop、latest US workspace、failure/healing blocker 和 release lane 持久化 journey，未删除测试、放宽预期或恢复无依据的质量分数。这是失败门禁，不以专项通过替代。
- disposable PG/private MinIO 浏览器导航/来源证据回归 **16 passed / 41.5 秒**（`native-build-browser-budgeted-current-20261010.log`，句柄 61700 退出 0）；light/dark、来源撤权与导航覆盖，不代表新原生构建 UI 或完整 E2E 已完成。当前 smoke **success**（`native-build-smoke-budgeted-current-20261010.log`），Portal build/lint 退出 0（`native-build-portal-{build,lint}-budgeted-20261010.log`）；主包 **1100.35 kB / gzip 302.22 kB** 的 >500 kB 警告保留。release hygiene 和 git diff --check 退出 0，hygiene 仅检查 tracked 工件/环境/密钥，不冒称完整安全审计。

三份 `exweb-canonical-native-{build,cancel,revoke}-budgeted-20261010.json` 已实际回读。固定 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 和全部 **126 个归档 blob** 经正式来源/画像固定，测试自有 checkout 删除后仍完整核验；实际无网络 Docker Maven 产物 **81,124,984 字节、109 个内嵌依赖库、121 个应用类**，SHA `sha256:acdb0a7e5d6dfea1637d90bf434a25868338a2fa31dab9f0a8f4aba42f819e99`，PG 登记与原私有结果回读一致，真实 Temporal history 可重放。运行中中断先确认 compile 容器 Running，再分别执行 canonical 取消或真实成员 DELETE；均只保留预留、没有成功结果，Workflow 终态前拥有的资源已移除。单次取消 **0.895 秒**、撤权 **0.217 秒**，不声明 p95 性能达标。

测试对象随隔离 PG/private bucket 清理，JSON 不冒充永久生产工件。原 build 与本批同源码的 JAR 摘要不同，可重现性/依赖供应链/文件模式仍未核验；报告明确 native target execution/full quality closure=false、execution_authorized=false，执行/通过计数为零。没有把内部协议 builder specimens 当作真实编译，也没有将开发环境默认选为源码执行目标。

最终 Docker list 按实际 label `nasus.native-build-owner` 确认没有残留；测试使用的 18080/14173/18082/14175 端口均无 LISTEN。开发服务不在这些测试端口，也未为验证重启。旧完整 V1 批的终态仍为 **16 failed / 5077 passed / 73 skipped / 3 warnings / 20013.45 秒**，加载早于当前代码；本轮没有重新执行或声称通过完整 `verify:v1-release`。

RunPlan 的精确原构建引用、目标环境/定位、fixture setup/cleanup、独立执行授权与 canonical 逐 case/step/oracle 执行回流继续交付；旧 `run.start` 未切换，本轮没有新正式构建 UI。五用途 ContextPack/旧消费者切换、完整自主预算/交付、自动 delta/overlay/merge、独立 gold、多语言、安全容量/性能/恢复/试点和完整 P0-P6 目标保留。开发库未迁移、开发服务未重启，Goal active；当前没有完整 V1 全绿证据。

## 固定画像源码的原生构建适配（2026-10-10）

新增[原生目标构建适配器](./native-target-build.md)。source application port 固定原 image/manifest/binding/revision，实时 ACL 检查包围全部私有来源字节核验；共享纯 DTO 与质量域构建端口隔离，禁止直接使用开发 checkout 或最新分支。Docker adapter 核验完整 image ID 与实际 Java 21/Maven 3.9.11，在无网络、受限资源、独立临时源码及只读 cache 中实际执行 verify，复核原源码未改变。私有存储保存实际 JAR、日志和完整 ZIP 成员摘要，回读重新核验全部字节。当前只是内部适配链，没有新增公开执行入口或改变 run.start。

第一批纯域/安全/DDD/RunPlan 回归 **184 passed / 2.46 秒**；新增读取顺序和摘要检查后初批为 **1 failed / 184 passed / 2.42 秒**（`native-build-domain-boundaries-current-20261010.log`），负测误期望 ValueError，而已有 canonical digest 契约返回 ImageRevisionIntegrityError。修正为确切异常类型，不改变生产拒绝行为。最终重新加载并加入旧 exweb CLI 回归，句柄 34253 已退出 0：**206 passed / 2.49 秒**（`native-build-domain-boundaries-final-20261010.log`）。选择集重叠，不累加为项目测试总量。

原生初批误期望错误 source pin 返回 ValueError，实际为 ImageRevisionIntegrityError，**1 failed / 4.04 秒**（`exweb-native-build-private-archive-20261010.log`）。修正测试契约后，disposable PG/private MinIO 专项句柄 57333 已退出 0：**3 passed / 38.11 秒**（`exweb-native-build-private-archive-current-20261010.log`）。最后读取顺序、工具链输出和进程清理 guard 后重新加载，句柄 88766 已退出 0：**3 passed / 38.20 秒**（`exweb-native-build-private-archive-final-20261010.log`）。最终报告 `exweb-native-build-private-archive-final-20261010.json` 已实际回读：固定 commit/tree、全部 126 个归档 blob、删除 fixture 自有 checkout 后完整来源读取、实际无网络 Docker 编译及私有 MinIO 完整回读均成立；JAR **81,124,984 字节**，**109 个内嵌依赖库、121 个应用类、336 个完整文件成员**。最终 Docker list 已确认无本 adapter 容器残留。

native_build_verified=true，但 nasus_canonical_build_command/native_target_execution/maintainer_business_gold/full_quality_closure 均 false，execution_authorized=false，执行/通过计数为零。原生测试 bucket 和对象按隔离测试约定清理，本地报告不冒充永久生产工件。来源文件模式、依赖供应链和可重现构建未获得证明；两个原生构建源码相同而 JAR 摘要不同，恢复必须回读原产物，不能重建冒称原工件。

追加既有来源归档/repository/证据/画像 API 的 disposable PG/private MinIO 回归，句柄 70733 已退出 0：**29 passed / 47.22 秒**（`native-build-source-image-regression-final-20261010.log`）。Portal build/lint/i18n、release hygiene 退出 0，contracts **848 passed / 2278.333208ms**（`native-build-portal-*20261010.log`、`native-build-release-hygiene-20261010.log`），主包 **1100.35 kB / gzip 302.22 kB** 的 >500kB 警告保留；hygiene 不代表完整安全扫描。当前未新增 UI，既有 RunPlan 标准门禁的七项 legacy 闭环失败仍保留，没有最新完整 V1 全绿证据。

正式独立确认、PG 构建预留/结果与审计/Outbox、Temporal 任务/恢复/取消、RunPlan 回执绑定、环境/定位/fixture 与真实目标执行继续待交付。全五用途、旧链切换、项目自动 delta/overlay/merge、完整自主预算/交付、独立 gold、多语言、安全、容量/性能及试点保留原 P0-P6 范围；开发库未迁移、开发服务未重启，Goal active。

### 原生构建中断与线程清理

构建端口新增 `require_work`，执行等待、源码复核、ZIP 成员核验和成功返回前均检查，停止清理阶段不受撤销回调阻断。新增 application supervisor 在异步取消时通知原线程并等待进程组/容器清理，重复取消不留下脱离任务的构建；清理错误不冒充取消成功。首进程退出但子进程仍持有管道的失败路径改为终止完整拥有的进程组。当前还没有 PG 构建 lease 或公开任务入口，不能把内部回调等同于持久化执行权。

首批收集因 Python 3.9 下新 Protocol 的 union 注解缺少 postponed annotations 而失败；补齐 future import，没有升级运行环境或放宽端口。重新加载 native build、中断、DDD 与边界选择集，句柄 69612 退出 0：**169 passed / 4.13 秒**。协议容器是明确 double，管道、超时、子进程退出与线程取消使用真实主机进程；不以此证明原生目标编译。

disposable PG/private MinIO 的四项来源/完整编译/运行中取消专项句柄 44321 退出 0：**4 passed / 63.86 秒**（`exweb-native-build-supervision-20261010-v1.log`）。两个报告已实际回读：`exweb-native-build-supervised-20261010-v1.json` 再次验证固定 Git commit/tree 与全部 126 个 blob、实际 Docker 构建和私有产物回读，JAR **81,124,984 字节、109 个依赖库、121 个应用类**；`exweb-native-build-cancellation-20261010-v1.json` 先确认另一次 compile 容器实际 Running，再取消，**0.117 秒**后返回，两个本次容器均已移除，无成功产物返回。最终 Docker list 没有本 adapter 残留。报告明确 canonical build/durable cancellation/native target execution/full closure 为 false；单次延迟不宣称性能门禁达标。

追加清理期间失去执行权的拒绝检查后，最终 native build/中断/DDD/RunPlan/旧 exweb CLI 组合句柄 95457 退出 0：**220 passed / 4.70 秒**（`native-build-supervision-domain-complete-20261010.log`）；前批 88510 的 **219 passed / 4.45 秒**早于该追加。重新加载的原生五项专项句柄 77128 退出 0：**5 passed / 92.23 秒**（`exweb-native-build-supervision-final-20261010.log`）。最终成功构建经同一异步 supervisor 完成并私有回读。取消与撤权两条运行中路径接入真实来源授权回调；撤权通过真实项目成员 DELETE 接口，确认正在运行的 compile 容器停止后没有成功产物返回。三个 `exweb-native-build-{supervised,cancellation,revocation}-final-20261010.json` 均已回读：全量原源码不变，取消 **0.110 秒**、撤权 **0.172 秒**，两个任务的全部自有容器在返回前已清理，最终 Docker list 为空。报告没有声明 PG 构建登记、持久取消或 canonical 工具任务已交付；五项是本轮专项，不累加为项目测试总数。

## 固定审阅输入的执行计划准备（2026-10-10）

0101 新增[执行计划准备](./run-plan-preparation.md)。canonical 预览/独立确认保存完整原脚本、审阅、用例/步骤/oracle 与目标 build/environment/fixture 声明；PG 元数据连接原 context/image/manifest 及 0100 精确登记 hash，计划/审计/Outbox 同事务。原请求先由 canonical command 恢复，全部原来源授权和上游历史验证先于计划正文读取。历史撤回不改写原工件，普通读和事件不修补坏历史。当前 target_verification=declared_not_native_verified、execution_authorized=false，覆盖及通过均为零，旧 run.start 未切换。

新增严格的确认准入：新保存在 MinIO 归档前与 PG 提交内检查 running 命令、完整请求、相同确认账号、时区及 15 分钟时限；未来/过期/缺时间或 completed 但缺原事实拒绝。已提交原命令重放保留原计划，不因为确认过期而改绑新输入。补充真实 FK 反例、归档期间独立撤回和晚期 Outbox 回滚检查；0100 populated migration 的 rollback-only probe 先移除 0101 下游表，生产外键不放宽。

已确认终态的选择集范围如下，重叠检查不累加为项目测试总数：

- 最新纯领域/application/脚本兼容/DDD/Portal 边界 **313 passed / 3.99 秒**（`run-plan-final-domain-boundaries-20261010.log`），包含严格审阅 bool 的追加反例。更早初批为 115 passed，单独 RunPlan/边界为 29 passed；后者加载早于严格 bool 追加，不冒称最终相同代码。
- Portal build/lint/i18n、release hygiene 退出 0，contracts **848 passed / 3137.829458ms**，主包 **1100.35 kB / gzip 302.22 kB** 的 >500kB 警告保留（`run-plan-portal-*20261010.log`）。hygiene 仅检查 tracked 工件/环境/密钥，不是完整安全扫描。无新增 UI；既有输入/脚本 light/dark 浏览器回归 **4 passed / 3.2 分钟**（`run-plan-browser-regression-20261010.log`），PG/private MinIO smoke success（`run-plan-smoke-regression-20261010.log`）。18105/14195/18082/14175 已实际确认无 LISTEN。浏览器不是新 RunPlan UI、原生模型或目标执行验收。
- 标准 API/runtime/DDD/Compose **7 failed / 298 passed / 1 warning / 392.69 秒**（`run-plan-standard-gates-20261010.log`），句柄 59568 退出 1。仍为相同七项 legacy quality-loop/release journey，不删除或放宽测试，不恢复推算分数；该批加载早于最后确认准入修改，没有最新完整 V1 全绿证据。

原生 RunPlan 初批句柄 31361 已确认退出 0：**2 passed / 1 deselected / 786.36 秒**（`run-plan-native-pg-minio-20261010.log`），覆盖当时的 canonical 保存、历史/权限、实际列/FK 对照、晚期 Outbox 回滚与损坏拒绝。该批加载早于最后确认准入、原来源授权先于计划正文和新增故障检查，不称最终相同代码通过。

实际 0100/0101 populated migration 兼容批句柄 40779 已确认退出 0：**1 passed / 1 deselected / 249.28 秒**（`run-plan-provenance-migration-compatibility-20261010.log`），在包含 0101 的实际数据库中覆盖原脚本/审阅、rollback-only DDL/完整回填、列/FK/索引对照和坏事实回滚；未放宽生产外键或删除旧事实。

早加载固定 exweb 一项句柄 38864 已确认退出 0：**1 passed / 2 deselected / 823.45 秒**（`exweb-run-plan-preparation-20261010.log`）。已回读 `exweb-run-plan-preparation-20261010.json`：原 commit/tree、126 个归档 blob 全部相等、725 个代码成员、4 个原用例/步骤/oracle/动作、独立 reviewer 和 canonical prepared plan 来源一致；target_verification=declared_not_native_verified，执行授权 false、三项覆盖计数为零。native_build_attestation/native_target_execution/external_model/business_gold/full_quality_closure/unified_project_delta_dag 明确 false。该批加载早于最后确认准入和故障追加，不代替最终代码验证。

最终实现的两项故障复验句柄 77014 已确认退出 0：**2 passed / 1 deselected / 681.42 秒**（`run-plan-final-native-faults-20261010.log`），包含最后确认准入、来源授权优先读取、operation-local cache、严格 bool、FK/TTL/race 反例。最终固定 exweb 专项句柄 62665 已确认退出 0：**1 passed / 2 deselected / 760.62 秒**（`exweb-run-plan-preparation-current-20261010.log`）。新报告 `exweb-run-plan-preparation-current-20261010.json` 已回读：原 commit/tree、126 blob/725 代码成员、4 个完整原用例与独立审阅一致，canonical preparation=true；native build/target execution/external model/business gold/full closure/unified project delta 均 false，prepared 不声明实际构建/目标执行通过。

本计划尚未接入 canonical 原生构建/来源 attestation、环境/fixture/定位核验、独立执行授权、canonical 目标执行及真实业务覆盖，也没有 Portal 计划表单或旧链 cutover；后续内部构建适配链的实际验证见前段，不自动改变原计划。完整五用途、自动项目 delta/overlay/merge、全计划预算与交付、独立 gold、多语言、安全、容量/性能及试点仍按原 P0-P6 目标验收。开发库未迁移，开发服务未重启，Goal active。

## 脚本与审阅的固定依赖追溯（2026-10-10）

0100 新增[脚本和审阅追溯](./automation-provenance.md)。脚本固定原 context/scope/generation/coverage/mapping 和全部选中 case 的工件及登记摘要，独立审阅固定原脚本与确切前驱。新事实、登记、审计和 Outbox 同事务，历史读取、原命令恢复和事件只核验，缺项不修补；旧 v1 图、工件摘要和执行授权不变。迁移明确固定 DDL，避免以后 ORM 字段扩展改变旧建表过程。

当前证据来自独立且重叠的选择集，不累加为项目测试总量：

- 纯领域、兼容和 DDD 初批 **268 passed / 2.62 秒**，固定 DDL 后 **269 passed / 2.93 秒**。新增 517 父项批量读取、末项缺失/错误摘要/外域/错误父项及 Portal 边界的最终组合 **307 passed / 3.49 秒**（`automation-provenance-batched-parent-boundaries-20261010.log`）。两个元数据批量查询不是真实 PG 容量或端到端 p95 证明。
- 原生 PG/私有 MinIO 初批因撤回 specimen 错传空 actions/assertions 而 **1 failed / 146.90 秒**；修正为现有契约要求的 null，没有放宽正式输入。后续 **2 passed / 427.05 秒**（`automation-provenance-native-final-20261010.log`），覆盖 canonical 生成/另一 reviewer 审阅撤回、旧事件前缀重放、不可变与精确父 hash FK、缺边 GET/真实 Outbox 拒绝修补、事务回滚及显式 populated backfill/迁移。该批测试加载早于新增列/FK/索引对照，不能用它证明该追加检查。
- 早加载的固定 exweb 追溯专项 **1 passed / 25 deselected / 695.38 秒**（`exweb-script-registered-provenance-20261010.log`）。实际报告核验原 commit/tree、全部 126 个 Git blob、725 个固定代码成员、全部选中 case 的原登记摘要、脚本与独立审阅 ancestry；接受 8 个动作和 4 个 oracle 后执行计数仍为零。该批加载早于批量读取优化，不作为最终代码全部范围；需求/oracle 和模型 HTTP 仍是明确的协议 specimens，external_model/target_execution/full_quality_closure/unified_project_delta_dag/nasus_run_plan 均为 false。
- 当前 Portal build/lint/i18n、release hygiene 退出 0，contracts **848 passed / 3082.374625ms**；主包 **1100.35 kB / gzip 302.22 kB** 的 >500kB 警告保留（`automation-provenance-portal-*20261010.log`）。实际 PG/私有 MinIO 浏览器 **4 passed / 2.9 分钟**，smoke **success**。已实际查看最新两种主题的 390px 截图；理由控件至少 220px、顶部动作高度不超过 36px，通过范围不是完整移动可访问性。18104/14194/18082/14175 已确认无 LISTEN。
- 前一批标准 API/runtime/DDD/Compose 实际终态 **7 failed / 295 passed / 1 warning / 333.67 秒**（`system-image-current-standard-gates-20261010.log`），没有包含先前的 12 项脚本测试。当前重新加载至 0100 的标准门禁句柄 34542 已退出 1：**7 failed / 295 passed / 1 warning / 330.77 秒**（`automation-provenance-standard-gates-current-20261010.log`）。七项仍是相同的 legacy quality-loop/release journey，缺证据返回 blocked/needs additional evidence，阻断数增加或旧完成条件超时；没有删除测试、降低预期或恢复推算质量分数，不宣称完整门禁绿色。

最新 `automation-provenance-native-exweb-current-20261010.log` 已确认句柄 38406 退出 0：**3 passed / 25 deselected / 1123.97 秒**，包含固定 DDL、列/FK/索引对照及批量读取的两项原生追溯和固定 exweb 一项。报告 `exweb-script-registered-provenance-current-20261010.json` 核验原 commit/tree、全部 126 个 blob、725 个代码成员、原脚本与独立审阅 ancestry；12 项决定为 8 个动作和 4 个 oracle，执行计数仍为零。该批加载的 schema 截至 0100，不替代新增 0101 下游外键后的迁移复验或完整业务闭环。

前一轮显式采集测试适配的终态另已核对：**62 passed / 1 skipped / 256.75 秒**（`system-image-explicit-capture-regression-20261010.log`），固定 exweb **1 passed / 24.93 秒**（`exweb-explicit-capture-materialization-20261010.log`）。后者原 commit/tree/126 文件、导出删除后零 connector 和归档全部字节不变，跳过项不称执行；没有修改生产采集门禁。手机宽度红测 146px、先前四项绿测 6.9 分钟与本轮四项检查重叠，不累加。

本阶段仍未交付统一项目 delta DAG 和自动失效/重建、automation ContextPack、正式 RunPlan/真实业务覆盖、五用途/旧链切换、完整自主预算/交付，以及独立 gold、多语言、安全、容量/性能和试点。原 P0-P6 范围全部保留；开发库未迁移、开发服务未重启，Goal active。

## 脚本界面与固定命令历史（2026-10-10）

新增默认折叠的脚本预算确认、原命令分页历史、DSL 草稿和逐动作/oracle 独立审阅。预算或理由变化使确认失效；失联只查原历史，不重发写入。canonical `query.quality.automation_history` 与 HTTP 复用固定 mapping/hash、完整原输入、实时 ACL 和归档重验，旧 Agent 回执遇到历史变化拒绝。原覆盖及执行授权保持零/false，详见[脚本契约](./automation-script-drafts.md)。

首轮浏览器 `automation-script-ui-exweb-pg-minio-20261010.log` 已确认句柄 32268 退出 1，四项全部失败：两项旧输入测试的动态翻译表导入报 ES module `exports` 错误，两项脚本测试的精确标签选择器找不到已经渲染的模型下拉框。修复为静态 registry 导入和实际 combobox role，不放宽交互、权限、预算或失联断言。另修复关闭的脚本面板监听相邻输入缓存错误、隐藏父级草稿的问题，并使用现有 `--surface-2` 替代不存在的样式 token。

重新加载的 Portal build/lint/i18n、release hygiene 与 git diff --check 退出 0；前端 contracts **841 passed / 4040.509209ms**，领域/application/DDD/Portal 组合 **372 passed / 3.84 秒**。专项 32 项是这 841 项的子集，不累加。主包 **1099.90 kB / gzip 302.10 kB** 的 >500kB 警告保留。日志为 `automation-script-ui-{build,lint,contracts,i18n,release-hygiene}-regression-20261010.log` 和 `automation-script-current-domain-boundaries-20261010.log`。

固定 exweb 的原生 HTTP/Agent 历史及另一 qa_lead 审阅批已退出 0：**2 passed / 24 deselected / 1053.70 秒**（`exweb-native-script-history-review-pg-minio-20261010.log`）。报告 `exweb-native-script-history-review-20261010.json` 核验原 commit、126 个文件、725 个固定代码成员、不同于生成者的实际 reviewer、重新授权的 HTTP/Agent 历史和原脚本不变。接受 8 个动作及 4 个 oracle 后，automated/executed_on_target/passed 仍为 0。模型传输和需求/用例为显式协议 specimens，不是外部模型或 exweb 目标执行。

重新加载的四项浏览器批 `automation-script-ui-exweb-pg-minio-regression-20261010.log` 已退出 1：**2 passed / 2 failed / 7.5 分钟**。两种主题的只读输入通过；脚本审阅在填写理由后，`getByLabel` 因标签同时包含 textarea 的内容而改变匹配集合，导致后续 `nth` 指向错误。改用实际 textbox role，保留逐项暂缓/空理由检查，并新增理由控件数等于全部动作/oracle 决定数加总理由的断言。后续 `automation-script-event-ui-exweb-20261010.log` 已退出 0：**4 passed / 7.4 分钟**。实际 PG/MinIO 的来源、发布、上下文与范围固定；生成/映射/脚本审阅传输为显式协议 specimens，不能据此声称真实模型、目标运行或完整移动可用性。

原完整门禁 `materialization-input-private-minio-v1-release-20261010.log` 已退出 1：**16 failed / 5077 passed / 73 skipped / 3 warnings / 20013.45 秒**。该进程装载早于 0097 和 Runner 后续修改；当前全新迁移至 0099 的隔离复验 `system-image-prior-v1-failures-current-20261010.log` 仍为 **10 failed / 8 passed / 98.35 秒**。进程级原输入、数据库 nullable 分数及 Runner 边界场景通过，但旧画像差异/清单测试在变更文件或新增来源后没有另走正式采集命令，因此没有新来源修订或新画像。不能把这些失败全部归因于旧 schema，也没有完整 V1 全绿证据。

另补齐脚本事件刷新：Portal 监听原生 `quality.automation.call_reserved / reply_archived / draft_saved / script_reviewed`，前三种不依赖额外 `snapshot_hint`。沿用 event ID/version 去重、200ms 合并、当前工作区和既有查询限制。上下文失效与映射审阅的项目级查询键包含脚本输入、历史与审阅，避免上游撤回后继续显示旧可用状态。行为负测分别为 **7 failed** 与 **3 failed / 23 passed / 0.43 秒**；修复后 Portal contracts **848 passed / 3477.381416ms**，领域/application/DDD/Portal 组合 **412 passed / 3.51 秒**，专项不累加。原生 canonical 脚本提交/独立审阅 **2 passed / 58 deselected / 463.48 秒**，原生上游失效/映射提交 **2 passed / 32 deselected / 125.03 秒**。对应 `automation-script-event-*20261010.log` 和 `automation-script-upstream-event-native-20261010.log`；浏览器协议测试不是原生网络 SSE 验收。

该版本 Portal build/lint/i18n、release hygiene 和 PG/private MinIO smoke 均退出 0；主包 **1100.30 kB / gzip 302.20 kB** 的 >500kB 警告保留。18082/14175/18101/14191 已确认无 LISTEN。随后截图检查发现 390px 手机端多层容器严重挤窄表单，宽度负测与显式采集回归另行验证；四项通过不能代替这项实际布局修复。

此进展不完成正式 RunPlan 或真实业务覆盖。五用途 ContextPack/旧链切换、case/step/oracle/script/build/environment/fixtures 的执行计划与 canonical 目标证据回流、完整自主预算/交付、自动 delta/overlay/merge、独立 gold、多语言、安全容量/性能/恢复/试点及原 P0-P6 退出条件全部保留，Goal active。

## 固定 exweb 的原生构建与业务观察（2026-10-10）

新增显式 CLI `scripts/verify-exweb-runtime.py`，仅执行已检查的 exweb origin/commit，不进入知识摄入。固定 `fe5827f6b76f77ef34918d8b452ee823142332dc` 的 **126 个 Git blob** 全部核验；通过离线 Java 21/Maven 3.9.11 构建真实 JAR，未修改源码、没有跳过测试参数。原仓库没有 test sources，Maven 的 BUILD SUCCESS 只证明编译/打包，不是业务测试通过。详见[原生目标验证](./exweb-native-runtime-validation.md)。

最终句柄 **64522 已退出 1**，报告 `exweb-native-runtime-final-verified-20261010.json` 为 observed/failed，不是启动失败：JAR **81,124,984 bytes**，hash `sha256:cb63e3becba932374e320e35ebd19058db07bbf8db5d19ab4ece801862efed4d`，包含 **109 个运行库、121 个编译类**，各包含成员有摘要。实际挂载 JAR 在业务观察后未变化。Java、临时 PG/Redis 位于独立 internal network；HTTP 在目标容器 loopback 内执行，没有宿主端口、开发数据库或模型出口。最终真实检查 **9 passed / 5 failed，共 14 项**，cleanup 通过且无剩余本轮资源。

五项失败分别为跨用户读取、跨租户读取、关闭后读取返回 **500**，以及会话在实际 PostgreSQL 查询为 **0 行**、Java 重启后会话消失。前三项虽然没有返回会话正文，仍未满足开发检查的错误状态契约；后两项与固定源码的 InMemorySessionRepository 一致。创建、本人读取/列表、不同身份空列表、内容拒绝和关闭的其余观察通过。没有修改外部源码来隐藏缺口，也不把本轮代码派生开发 oracle 当作维护者批准规范或独立 gold；报告保持 nasus_runplan_verified/llm_verified/release_authorized=false。

保留早期脚本故障，不当成产品红测或重复成功：初次私有组件移除全部 capabilities 后启动失败，33802 已退出 1；修正为镜像实际非 root UID/GID 后，79917 因读取 internal network 的空宿主端口映射产生 IndexError，退出 1，未产出完整 JSON，但临时资源已清理。随后改为目标内真实 curl HTTP；85872 已退出 1，实际 9/14 与五项原生失败一致。85537 已退出 1，新增 JAR 清单/原字节复查后仍 observed/failed；最终 64522 增加严格资源不存在判据。没有因观察超时重开仍 live 的进程。

脚本协议、路径/hash/凭据隔离、只读/离线、历史不覆盖、JAR inventory 和资源缺失检查使用独立 specimens，最终 **20 passed / 0.04 秒**（`exweb-native-runtime-probe-contracts-final-20261010-verified.log`）；这些不是 20 项 exweb 业务任务。最初计数断言错误为 **1 failed / 9 passed / 0.05 秒**，实际 checks 为 12，不是 11，已修正数量且所有行为断言保留。中间 12/18 项批次范围更小，不累加。

本轮当前 Nasus 回归，选择集重叠、不汇总为项目总测试量：

- PG/private MinIO 标准 API/runtime/DDD/Compose 与当时 12 项脚本检查，句柄 **10223 退出 1：7 failed / 307 passed / 1 warning / 334.53 秒**（`exweb-native-runtime-standard-gates-current-20261010.log`）。七项仍为原 legacy 闭环/放行 journey；该批收集早于后续八项脚本检查。没有删除、跳过、降低预期或恢复虚构质量分数。
- Portal build/lint/i18n 退出 0，contracts **832 passed / 3040.714542ms**，边界 **25 passed / 0.16 秒**。主包 **1063.43 kB / gzip 293.93 kB** 的 >500kB 警告保留（`exweb-native-runtime-portal-*20261010.log`）。无前端样式改动。
- 实际 PG/private MinIO smoke，句柄 **51434 退出 0/success**（`exweb-native-runtime-smoke-current-20261010.log`），18082/14175 已确认无 LISTEN。release hygiene 与 git diff --check 退出 0；hygiene 不是完整供应链或安全审计。

原完整门禁 **87589** 当时确认 live，后续已退出 1：**16 failed / 5077 passed / 73 skipped / 3 warnings / 20013.45 秒**（`materialization-input-private-minio-v1-release-20261010.log`）。加载早于 0097/Runner/本段，未因观察等待终止或重开，不能作为当前完整 V1 全绿证明。开发服务未重启，开发库未迁移。

本轮真正新增的是固定第三方代码的可重复运行验证及原生失败证据，不是正式质量闭环实现完成。临时 JAR/数据库清理，本地报告不冒充永久 MinIO 归档或 canonical ToolInvocation/Run。完整脚本预算/独立审阅、case/step/oracle/build/environment/fixtures RunPlan、实际目标证据回流、五用途/旧链切换、退款示例、完整自主预算/交付、自动 delta/overlay/merge、独立 gold、多语言与安全容量/恢复/试点及原 P0-P6 范围继续保留，Goal active。

## Runner 实际观察、原输入与原子事实提交（2026-10-10）

原 HTTP adapter 接受无回执的 passed、错 job 和自授 business/build authority。行为负测 `runner-receipt-unbound-status-red-20261010.log` 为 **3 failed / 0.12 秒**。现在原生 Node Runner 返回逐步骤及断言观察，并对实际 HTTP bytes 计算 hash；API 纯领域校验 job/project/US、完整原步骤、顺序、结果/count 和禁止 authority。截止后封存，迟到回调不更新结果或继续下一步骤；原物理操作和完整任务取消仍另有要求。通用证据不再伪造 `case_set:current`，business/build verified=false。详见[执行观察契约](./runner-execution-observations.md)。

实际 Native HTTP/Chromium/PG/私有 MinIO 复验发现旧 replace_runs/replace_failure_analysis 漏写执行计划、目标、脚本和重试字段，`runner-receipt-native-pg-minio-current-20261010.log` **4 failed / 170 passed / 6.92 秒**；现在复用完整 mapper。扩展选择集 `runner-receipt-native-pg-minio-verified-20261010.log` **191 passed / 14.32 秒**；最终 deadline guard 后 `runner-receipt-native-final-pg-minio-20261010.log` **8 passed / 13.65 秒**，句柄 48090 已确认退出 0。这些目标是显式本地 HTML 夹具，不是 exweb 业务服务。

随后真实故障注入证明正式/兼容路径都在 Run 保存失败后留下 **5 条**可见 evidence。`runner-atomic-commit-native-red-20261010.log` **2 failed / 8 deselected / 2.59 秒**，不是模拟 HTTP 状态。新 commit_run_execution 将完整 Run 和 evidence 元数据放进同一 PG 事务，兼容投影仅在成功后更新；不全量改写 peers。完全相同结果可重试，变更步骤/oracle、证据 hash 或项目拒绝；较晚 evidence insert 主键冲突时，即使 Run 已 flush 也回滚。旧历史不倒推修补。

另一个实际原生反例：派发时为 original Context，保存 Run 时却选择 later Context。`runner-atomic-context-native-red-20261010.log` **1 failed / 2 passed / 30 deselected / 3.62 秒**；该命令的 -k 也筛掉了原子持久化文件，不冒称它执行了这些测试。Run 现在保留 command 原 TaskContext ID，私有报告增加完整 actual request 与 exact hash，回读后能与 receipt 核对；不是完整固定 ContextPack 或 RunPlan。

当前终态证据，各选择集重叠、不累计为项目总数：

- 初次扩展命令误用不存在的 `test_quality_loop_workspace_adapters.py`，退出 4/no tests ran（`runner-atomic-execution-pg-minio-current-20261010.log`）；改为真实单数文件后 **22 failed / 236 passed / 17.85 秒**（`runner-atomic-execution-pg-minio-verified-20261010.log`）。22 项均在夹具创建时缺 RunDetail 必填 failure_summary/healing_status，未到产品事务；补全夹具，不改生产 schema 或断言。
- 重新加载的完整相同组合 `runner-atomic-execution-pg-minio-final-20261010.log` 已确认句柄 37362 **退出 0：258 passed / 16.10 秒**。含新原子 commit 22 项、原生观察/故障/上下文 11 项、HTTP/domain、原 Run/failure/application、正式/兼容 workspace、DDD/Portal/Compose；真实数据库为 disposable PG，存储为 private MinIO。
- 最新 Node 专项 **11 passed / 2097.581583ms**，句柄 90405 退出 0（`runner-atomic-native-node-current-20261010.log`）。release hygiene 退出 0，git diff --check 退出 0；hygiene 只检查 tracked 工件/环境/密钥，不作为完整安全扫描。
- 更早标准 API/runtime/quality/Runner/DDD/Portal/Compose 批 `runner-receipt-standard-gates-current-20261010.log` 已确认句柄 86852 **退出 1：7 failed / 375 passed / 1 warning / 394.13 秒**。七个 legacy journey 与 0097 相同，仍期待静态生成/fixture run 后 ready/autoapproval 或只计一个 blocker。它加载早于本段原子提交；没有删除/跳过、改预期或恢复虚构质量分数。
- 原子提交后的标准重新加载批 `runner-atomic-execution-standard-current-20261010.log` 已确认句柄 24832 **退出 1：7 failed / 400 passed / 1 warning / 347.11 秒**。相同七个 legacy journey 仍未满足完整闭环；该批加载早于最后默认 timeline 调整，不能称当前所有范围全绿。首个私有 MinIO smoke `runner-atomic-execution-smoke-current-20261010.log` 已确认 20394 退出 0/success，后续最终 smoke 另记。

最后复查发现默认 timeline 会无依据补写“由已批准用例生成自动化”。现在只说明实际 Runner 返回/归档，通过时明确业务覆盖未验证；原外部 timeline 和历史不改写。新增两项纯检查后，最终相同选择集 `runner-atomic-timeline-pg-minio-final-20261010.log` 已确认句柄 8669 **退出 0：260 passed / 18.10 秒**。最新 Node 11 项仍覆盖未变化的 Node 实现，不与这 260 项累加为覆盖率。

最终 Portal contracts **832 passed / 3311.63175ms**，build/lint/i18n 全部退出 0，主包仍 **1063.43 kB / gzip 293.93 kB** 警告保留（`runner-atomic-portal-{contracts,build,lint,i18n}-final-20261010.log`）。最终实际 PG/private MinIO smoke `runner-atomic-timeline-smoke-final-20261010.log` **success**，句柄 16554 退出 0；18091/14182/18082/14175 均确认无 LISTEN。没有重启开发服务或迁移开发库，新事务能力无需新增 schema。

Run/evidence 事务不包含 MinIO：失败后私有未引用物理对象仍需受控 GC/恢复。旧独立物化、healing 等入口仍能修改兼容事实，canonical 审计/Outbox/终态原子链、跨进程 owner/idempotent dispatch、完整 case/step/oracle/script/build/environment/fixture RunPlan 及真正业务覆盖尚未交付。完整五用途、旧消费者切换、真实 exweb 服务/外部模型/gold、自动 delta/overlay/merge、安全容量/性能与原 P0-P6 退出条件保持不变，Goal active。

## 固定审阅用例的自动化输入与事件刷新（2026-10-10）

新增 application-port-only 编译与只读 GET，固定原 context/scope/generation/current mapping、明确 case IDs、每个原步骤/oracle 和全部强制义务，遗漏分母或篡改拒绝；当前 ACL/authority/失效及归档完整性两次复查。Portal 默认不读取，点击后展开，错误/撤权不显示旧正文；新映射和上下文失效按项目 query prefix 刷新，不误把 generation 放到 session 缓存位置。返回五项待补条件及自动化/执行/通过零计数，不授予模型或 Runner 权限。详见[自动化输入契约](./automation-input-preview.md)。

当前已确认终态，选择集重叠，不拼成全量 V1：

- 固定 exweb、实际 PG/私有 MinIO 的输入衔接批 **8 passed / 410.98 秒**，句柄 71259 退出 0；事件/Outbox/当前 query-key 复验 `automation-input-current-events-pg-20261010.log` **8 passed / 382.90 秒**，句柄 85590 退出 0。纯领域/application/DDD/Portal 边界 **202 passed / 1.99 秒**（`automation-input-current-boundaries-20261010.log`）。
- 最终 Portal contracts **832 passed / 2762.911917ms**，build/lint/实际 i18n 退出 0；主包 **1063.43 kB / gzip 293.93 kB** 的 >500 kB 警告保留。对应 `automation-input-portal-{contracts-events,build-events,lint-events}-final-20261010.log`，不冒称 UI 性能达标。
- 实际 PG/私有 MinIO 浏览器 `automation-input-browser-events-current-20261010.log` **5 passed / 7.9 分钟**，句柄 75525 已确认退出 0，启用真实 exweb 工作树。来源、publication/context/scope 为真实持久化，generation/mapping/automation reply 为明确 transport specimens；不是原生模型或目标运行。已实际查看本批 light/en、dark/zh 的 390px 移动自动化面板截图，保留原 shared shell、长 hash 换行、局部无滚动条滚动和零执行/写入入口；不以两截图称完整视觉验收。

报告 `exweb-automation-input-members-verified-20261010.json` 已回读：固定 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`、**126 个归档 blob 全部等于 Git 原字节**，**725 个真实固定代码成员**。保留 context/scope/generation/mapping pins、1 项来源约束/4 项义务/4 个选择用例；另有显式 Orders 代码夹具，需求/oracle/模型回复不是 exweb 维护者 gold 或原生 Provider。脚本/目标运行、外部模型、五用途和完整闭环明确 false。

本段不替换 legacy automation.generate，不把已接受断言映射变成正式业务批准或已执行覆盖。87589 的旧完整 V1 装载早于 0097/本段/Runner，后续已失败退出，完整终态见本记录开头；没有因等待超时终止/重开，也没有当前完整 V1 全绿证明。完整原目标继续 active。

## 0097 未评估质量与当前放行证据（2026-10-10）

新冻结 metrics 已是准入对象清单，但兼容 QualityProfile/TaskContext 仍把它们代入缺省评分公式。实际 PG 负测 `unknown-quality-profile-postgres-red-20261010.log` 为 **3 failed / 10.75 秒**。0097 将标记为未评估 inventory 的风险、覆盖、自动化可行性、放行分数及 confidence 保存为 null；混合旧数值不能覆盖 unknown。PG 六列允许 null 且移除数值默认值，迁移不重算历史，降级遇到未知分数拒绝而不补 0。未标记的旧历史公式仍是兼容路径，不据此声称所有旧消费者完成切换。

release.assess 保留可观察的运行事实，但把未知质量列为 blocker，不再完成 Release Assessment 或推荐申请放行，US 与资产包保持 blocked。另有实际 canonical 审批后的两项负测 `unknown-quality-governance-api-red-20261010.log`，**2 failed / 8.57 秒**，证明旧 ready ReleaseDecision 可绕过当前未知证据重提放行或晋级基线。平台 application 现在经治理 workspace port 复核当前已保存的 readiness 和 execution evidence；旧决定不能覆盖 blocked/needs_evidence，未知标记也不能被数值 90 隐藏。无执行证据时不允许仅凭 score/approval 得到 conditional。它不是原子 ReleaseContext、目标 build/oracle 闭包或完整 P5。

Portal Release Readiness 改为呈现当前 readiness，不从历史 ready 决定复制状态、90 分或 rationale；尚未评估显示 Unknown 而非 0。中文 unknown blocker 已本地化。未改 shared shell、图标、流光或布局 tokens。

已确认终态的选择集相互重叠，不累加成项目测试总量：

- PG/私有 MinIO、固定 exweb/原输入恢复、未知持久化/迁移、canonical 审批负测及边界组合 `unknown-quality-governance-postgres-exweb-current-20261010.log`：**301 passed / 176.19 秒**，句柄 53258 退出 0。后续仅将 helper 重命名以满足既有 DDD 禁止旧 store 调用的规则，未放宽边界；最终纯领域/DDD/Compose 组合 **222 passed / 1.61 秒**（`unknown-quality-governance-domain-verified-20261010.log`）。
- 最终 Portal contracts **803 passed / 2507.15ms**（`unknown-quality-release-portal-contracts-verified-20261010.log`）；build、lint、实际 i18n 门禁退出 0。主包 **1048.61 kB / gzip 290.15 kB** 警告保留。新 UI 测试首次缺 approvals 数组导致 harness TypeError，并非行为红测；补全后四项当前/历史展示检查通过。
- 实际 PG/私有 MinIO 浏览器 navigation 与固定 exweb 的未知放行展示 **11 passed / 1.4 分钟**（`unknown-quality-release-browser-current-20261010.log`），句柄 77688 退出 0。覆盖 light/en、dark/zh、刷新与 390×844，当前 blocked/20 分不被明确负向夹具旧 ready/90 分覆盖，自动写入数为 0。两张移动截图已实际查看；只证明这些展示与交互，不是完整视觉、目标执行或业务 gold。最新 smoke **success**（`unknown-quality-governance-smoke-current-20261010.log`），句柄 89707 退出 0；相关测试端口已无 LISTEN。
- 最终标准 API/runtime/quality/DDD/Portal/Compose 批 `unknown-quality-governance-standard-current-20261010.log` 已确认句柄 74371 **退出 1：7 failed / 349 passed / 1 warning / 333.28 秒**。七个旧 journey 仍期待静态物化和生成/fixture run 后放行，或只计算运行失败而忽略未知质量 blocker；没有删除、跳过或恢复虚构数值来让它们绿色。更早标准批 `unknown-quality-standard-gates-verified-20261010.log` 同样 **7 failed / 314 passed / 351.78 秒**，不能用最新专项覆盖这些未交付的真实闭环要求。

固定 exweb 报告 `exweb-unknown-quality-governance-current-20261010.json` 与 `exweb-unknown-quality-governance-process-current-20261010.json` 已回读：commit `fe5827f6b76f77ef34918d8b452ee823142332dc`，tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`，126 blob。删除导出后 fresh cache 零重采集、全部归档文件字节相同，原 canonical/source pin 不变，质量分数未知。进程报告为实际 SIGKILL PID **46180** 后新 PID **46185**；自动恢复、lease/cancel、原子终态、原生 Provider/外部模型/目标运行及完整闭环均明确未验证。

原完整 V1 87589 当时确认 live，后续已失败退出，完整终态见本记录开头。它装载早于 0097 和治理/Portal 修复，不是当前完整 V1 证明；没有因观察超时终止或重开。本目标仍需全旧链切换、五用途/脚本/RunPlan/真实执行反馈、全计划费用/原子交付、自动 delta/overlay/merge、Provider 对照/gold/安全容量/性能及完整 P0-P6 门禁，Goal 保持 active。

## 0096 原物化输入、进程恢复与补偿保护（2026-10-10）

原 running materialization 在提取前中断，再由另一个 canonical acquisition 推进来源清单后，会静默改用 latest。真实负测 **1 failed / 5.18 秒**（`materialization-command-original-input-red-20261010.log`）复现；不是模拟新错误码。0096 将原 invocation/project/执行账号/command digest/manifest ID 与 hash、ToolInvocation 消费标记及 metadata-only Outbox 同 PG 事务保存。表与非空消费 pin 不可改写，恢复先回读原清单，再核验当前完整 source roster/head、账号、角色及 ACL。丢失原历史不借 SSE 或新来源修补；迁移登记旧命令，不推断原输入，旧 completed canonical 历史不变。生产直接无命令物化拒绝，`us.task.start` 不再隐藏第二次无 canonical 构建。详见[原输入契约](./frozen-materialization-inputs.md)。

新冻结提取只接入真实代码结构观察；名称/标签型 resolver 仅留在无 manifest 的 legacy 显示路径。references 与有原文证据的 implements/asserts 仍独立提案/审阅/冻结，不能为满足图数量补业务边。冻结指标明确是对象清单及 `coverage_status=unknown`，区分需求/AC/规则/用例/脚本，合法零边候选也能保存。详见[清单根及语义边界](./manifest-rooted-projections.md)。

随后真实 HTTP/PG/MinIO 负测发现：embedding 返回后另一个 canonical 命令新增并采集代码，原 scope 失效触发旧回滚，覆盖新 RawAsset/chunks。负测批 **1 failed / 2 passed / 11.87 秒**（`materialization-late-rollback-red-20261010.log`）；修复为补偿前核验原完整 source head/roster，变化或读不可用不恢复旧 snapshot，未放宽来源权限。当前权限变化和 Provider 异常两分支、实际旧 schema 迁移、US 入口及候选提交后变化组合 **6 passed / 22.77 秒**（`materialization-late-rollback-current-20261010.log`），句柄 63496 已退出 0。

新增两个真实 Python OS 进程：分别在原来源输入事务提交后和候选事务提交后通知父进程，由父进程发送实际 SIGKILL 并确认负信号退出；新 PID、独立缓存从生产 application/container 恢复。原 ToolInvocation 保持 running，不篡改终态，不共享旧内存，也不在异常 finally 中补救。当前撤权和另一命令推进 head 拒绝，重新授权后原输入不变。组合 **5 passed / 51.02 秒**（`materialization-process-input-current-20261010.log`），句柄 76525 已退出 0。

其中 `exweb-materialization-process-input-current-20261010.json` 固定真实 `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`、126 Git blob，实际 killed PID **40004**、new PID **40005**。全部导出目录删除，恢复零 connector，MinIO 全部原文件字节一致，原 command/source pin、manifest/source facts 不变。显式内部恢复不是自动调度、Temporal lease/取消、稳定输出或 canonical 终态原子提交；report 对这些能力以及原生 Provider/外部模型/目标运行/完整质量闭环均明确 false。

以下独立选择集均有对应日志，互相重叠，不累计为项目测试总数：

- 初始 pin 单位组合 **156 passed / 9.49 秒**；该加载早于 legacy roster、消费列及 US 入口调整，不作为最终全部范围。纯领域/application 后续修正两项 digest 异常类型假设及旧 DDD 片段后 **208 passed / 3.04 秒**（`materialization-command-input-unit-verified-20261010.log`）。
- 首批实际 API/DDD 组合 **1 failed / 190 passed / 1 skipped / 96.76 秒**，唯一失败为已移除的 hidden-materialize DDD 文本要求。之后 exweb/画像/引用/结构组合 **1 failed / 246 passed / 217.04 秒**（`materialization-command-input-exweb-current-20261010.log`），新增 binding 正确令权限 fingerprint 失效，旧测试却只接受来源版本变化英文文案。改为分支专用结构化 reason code，仍检查失败、原画像不变与当前来源范围变化，没有把失效权限当作普通 gap。
- 原迁移/US 专项 **1 passed / 1 error / 1.65 秒**；迁移通过，US 测试漏导入 fixture。导入后上述 6 项专项全部通过。首次标准组合 **463 passed / 2 skipped / 1 warning / 1 error / 555.14 秒**同属 fixture 缺失（`materialization-command-input-standard-20261010.log`）。
- 修正后的标准 API/runtime/原输入/来源恢复/工作区/application/DDD/Portal/Compose/隔离组合，实际终态为 **1 failed / 465 passed / 2 skipped / 1 warning / 683.10 秒**（`materialization-command-input-standard-verified-20261010.log`）。唯一失败为运行中修改发布脚本后，早已加载的旧 Compose 断言仍要求无 `--minio`；不将该批称为全绿。当前重新加载的边界/application 组合 **199 passed / 2.44 秒**（`materialization-input-boundary-current-20261010.log`），原失败节点另 **1 passed / 0.01 秒**（`materialization-private-minio-release-contract-verified-20261010.log`）。标准批两项 skip 未冒称执行，LangGraph 警告保留。
- 当前 Portal 实际 PG/私有 MinIO 的 refresh/evidence/tracked-ref/guided-entry/semantic/context/publication/index 组合 **33 passed / 12.0 分钟**（`materialization-command-input-browser-current-20261010.log`），句柄 54830 已退出 0；该批显式启用 exweb。`exweb-materialization-input-browser-current-20261010.json` 保留真实固定 126 文件、只改变选中代码而不改 optional 与旧画像的范围，不代表物化自动恢复或业务 gold。已实际查看最新 dark/zh 来源恢复及 light/en 移动上下文截图，保持长 ID 换行、无滚动条滚动；测试 18090/14181 已无 LISTEN。
- 当前 PG/私有 MinIO smoke **success**（`materialization-input-private-minio-smoke-20261010.log`），句柄 57229 已退出 0，18082/14175 无 LISTEN。

完整 `verify:v1-release` 现在在后端 gate 显式通过临时私有 MinIO bucket 执行，不再让实际进程恢复测试落到 local-storage；仍覆盖完整 `apps/api/tests` 及原 Compose/DDD/隔离门禁，没有删掉 legacy journey 或原生 Provider/备份/浏览器/Runner/Temporal 门禁。独立批 87589 后续已失败退出（`materialization-input-private-minio-v1-release-20261010.log`），完整终态见本记录开头；前置 hygiene/lint/i18n/Portal boundary、799 Portal contracts、build 和 5 Runner tests 的完成不能证明整个 V1 已通过。Portal 主包体积警告保留。另 exweb/原输入/画像/引用/结构/DDD/Compose 组合 64417 已确认退出 0：**251 passed / 258.16 秒**（`materialization-command-input-exweb-verified-20261010.log`）。报告 `exweb-materialization-source-input-verified-20261010.json` 保留上述固定 commit/tree/126 文件，导出删除及 fresh cache 后零重新采集、全部归档字节一致；这批早于后续质量分数语义改动，不证明该改动或完整 P0-P6。

本轮 pin 只覆盖来源，未固定全部 baseline/version/name/兼容模型配置，尚无物化 owner lease、稳定输出及跨域 projection/ToolInvocation 终态的一致交付。进一步代码核验确认 legacy `QualityProfile` 仍从缺省风险、缺失覆盖和资料数量推导分数，旧 `TaskContext` readiness 也不是规范/生成/执行授权；不能把冻结 inventory 的 unknown 误解为这条旧消费者已经清理。正式 ContextPack 仍明确缺口及独立 authority/预算。完整旧质量消费者切换、全计划费用、自动 source dispatch/delta/invalidation/overlay/merge、五用途/脚本/RunPlan、真实 oracle/目标执行反馈、gold/安全/容量/性能及完整 V1 继续作为 P0-P6 必须交付项。未迁移开发库或重启开发服务，Goal 保持 active。

## 0095 后续：批量读取与独立 OS 进程恢复（2026-10-09）

原结果重放逐条 session.get，12 来源实际读取重复触发 36 次 SourceRevision 查询。新增完整 roster 检查先 **1 failed / 20 deselected / 7.10 秒**（`source-acquisition-batch-read-red-20261009.log`）；生产 repository 改为事务内完整 ID 批量加载 RawAsset、revision、inventory 和 manifest binding，仍逐项验证全部 scope/hash/计数，不跳过末项、不缓存权限、不截断。新结果数量不得超过原选中集合，inventory 额外检查 project/source/binding。修复后 **1 passed / 20 deselected / 6.60 秒**（`source-acquisition-batch-read-current-20261009.log`），含末项 inventory 真实损坏后再次拒绝。此项只消除这条读取的 N+1；新增结果事务仍重验完整原 ledger，不声明全链复杂度、1000 来源容量或 p95 达标。

新增独立 Python 进程从真实 production container/application 执行原 canonical running 命令；事务提交后父进程发送实际 SIGKILL，并确认负信号退出。另一 PID 使用独立 snapshot/source cache 恢复，PG/MinIO 和原命令相同，不共享内存、异常补救或篡改命令终态。selected/whole 的 capture/manifest 两窗口、完整重放、他命令推进 head 及当前 ACL 拒绝组合 **7 passed / 47.99 秒**，句柄 28513 已退出 0（`source-acquisition-process-recovery-current-20261009.log`）。

其中固定 exweb 报告 `exweb-acquisition-process-recovery-current-20261009.json` 使用真实 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、原 tree 和 126 个 blob，实际 killed PID **24442**、new PID **24443**；受控 README 改写及 pom 删除后零重新采集，归档全部文件字节一致。报告分别声明 `independent_native_process_restart_verified=true`、`automatic_dispatch_verified=false`、`temporal_lease_cancellation_verified=false`、`external_model_or_target_execution_verified=false`。显式内部恢复不等于生产自动扫描/调度或 canonical 终态原子提交，不替代 P0-P6 生命周期、旧链切换和完整 V1。

批量读取后的各独立批均已确认终态：results/intent/exweb/边界组合 **211 passed / 142.98 秒**（`source-acquisition-batch-read-exweb-gates-current-20261009.log`）；标准 API/runtime/来源权限/refresh/acquisition/results、DDD/Portal/Compose/隔离组合 **439 passed / 1 skipped / 1 warning / 456.18 秒**（`source-acquisition-process-standard-gates-current-20261009.log`）。标准批未启用 exweb opt-in，不能把该 skip 称为执行；exweb 另由上面的独立批与进程批验证。LangGraph 警告保留。

浏览器 refresh/evidence/tracked-ref/guided-entry 本批明确启用 exweb，**24 passed / 4.4 分钟**（`source-acquisition-process-browser-current-20261009.log`），报告 `exweb-acquisition-process-browser-current-20261009.json` 保持固定原 126 文件，只有选中代码修订变化，optional 与旧画像不变。PG/私有 MinIO smoke **success**；Portal contracts **799 passed / 2871.270541ms**，build/lint/i18n 退出 0，主包 **1048.12 kB / gzip 290.00 kB** 警告保留。实际查看最新 dark/zh 移动结构 gate 与来源刷新恢复弹层，保持边缘流光、无滚动条滚动与长 ID 换行。测试端口均无 LISTEN；未迁移开发库或重启开发服务。这些重叠选择集不累计为项目总数，也不替代完整 V1。

## 0095 逐来源结果与原清单消费（2026-10-09）

0095 在真实 canonical running 命令下固定每个来源的 captured / legacy_unverified / failed 结果。inventory、SourceRevision、结果、进度摘要和 metadata-only Outbox 同 PG 事务提交；清单成员、head、完整结果消费回执、进度消费 pin 和 Outbox 在另一事务原子保存。恢复先重新授权并完整核验原结果，只采集尚无结果的来源；已提交失败必须独立新命令重试。selected 从原 origin 替换选中成员，不继承未选中来源的最新 mutable 状态。其他命令推进 head、损坏或缺失历史均拒绝，不借 SSE 保留期修补。详见[采集结果契约](./source-acquisition.md)。

兼容工作区与 chunks 仍在上述事务之外；当前恢复测试使用事务后 BaseException 和新 application/connector/repository，不冒充 OS 强杀、自动 Temporal 重启、lease 或取消。0094 旧 running intent 不补造新 progress，原 completed 回放不变。完整 P0-P6 不缩减。

已核对当前进程终态及对应日志，重叠选择集不累计为项目测试总量：

- 纯领域/application、DDD/Compose **210 passed / 1.29 秒**（`source-acquisition-results-unit-current-20261009.log`）。初批两项旧 fake port 未实现新增方法，修正测试替身，不恢复生产旁路。
- 初始真实 PG/私有 MinIO 恢复批 **10 failed / 6 passed**，错误来自测试读取不存在的 SSE ORM 字段；改为实际 entity ID 后 **16 passed / 51.36 秒**（`source-acquisition-results-recovery-current-20261009.log`）。后续 progress/无变化清单缺记录负测另入最终批，不把早批当作最终全部覆盖。
- 当前完整 results/intent/exweb 组合 **47 passed / 144.27 秒**，句柄 3419 已确认退出 0（`source-acquisition-results-ledger-exweb-verified-20261009.log`）。前批 **1 failed / 46 passed / 146.08 秒** 是 exweb 测试漏传归档读取上限，修正后独立重跑；没有放宽文件字节验证。报告 `exweb-source-acquisition-results-verified-20261009.json` 固定原 `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 和 126 个 Git blob，清单消费后受控修改 README/删除 pom，fresh 服务恢复零 connector，全部原 MinIO 字节一致。报告明确独立 OS 重启、Temporal lease/取消及目标运行均未验证。
- 标准 API/runtime/来源权限/refresh/acquisition、DDD/Portal/Compose/隔离组合第一次 **2 failed / 417 passed / 1 warning / 399.81 秒**（`source-acquisition-results-standard-gates-current-20261009.log`），两项仍要求原始 connector 错误文案。新 canonical 路径只存固定脱敏 reason code；更新文案断言并保留失败状态、权限、计数断言，额外检查失败没有 content_ref。独立重跑 **419 passed / 1 warning / 396.86 秒**，句柄 27178 已退出 0（`source-acquisition-results-standard-gates-verified-20261009.log`）。LangGraph 警告保留。
- 真实浏览器 refresh/evidence/tracked-ref/guided-entry **23 passed / 1 skipped / 4.0 分钟**（`source-acquisition-results-browser-current-20261009.log`），句柄 56299 已退出 0；该 skip 为未启用的 exweb 浏览器范围，不称已执行。PG/私有 MinIO smoke **success**，句柄 3496 退出 0（`source-acquisition-results-smoke-current-20261009.log`）。
- Portal contracts **799 passed / 2463.244ms**（`source-acquisition-results-portal-contracts-verified-20261009.log`），build/lint/i18n 退出 0，主包 **1048.12 kB / gzip 290.00 kB** 警告保留。误写 `test:portal:contracts` 的一次退出 1 为不存在 npm script，不是测试结果，随后执行实际 `test:portal-contracts`。

这些证据不替代此前未通过的完整 V1 门禁。仍需采集持久任务/owner/epoch/取消和真实自动恢复、全计划预算、自动 delta/失效/overlay/合并、五用途上下文及旧链切换、真实语义 gold/目标执行、安全容量/性能。未重启开发服务或迁移开发库，Goal 保持 active。

## 0094 准入、分页读取寿命与配置账号核验（2026-10-09）

0094 固定 connector 前的 canonical invocation、执行账号、来源身份及 origin manifest，并与 metadata-only Outbox 同 PG 事务保存。来源身份按原 tracked_ref 算法重算，清单核验完整排序成员及来源类型；损坏历史在 connector 和 mutable 工作区变更前拒绝，不借普通写入修补。详见[采集准入](./source-acquisition.md)。这不是 lease、逐来源结果消费、采集 Temporal 或崩溃恢复的完成证据。

原冻结分页在历史 SSE 回放中出现实际未取消的 `25 → 12 → 6 → 3` 双重请求链。调度原先在 200ms flush 时判断整个 prefix 是否 fetching，把事件后才挂载的私有页面也加入 follow-up。现改为事件到达时固定确切 query 和实际 fetch promise，只对仍在读取事件前快照的 query 二次核验；实时消息更新不会误判该 fetch 已结束。没有关闭 StrictMode／focus／权限重读，也没有把重复已完成请求排除出测试。真实归档证据与显式 legacy DTO transport fixture 分开；后者不在生产画像中制造无来源占位成员。

启动配置账号补齐了旧 dev/static profile 与 PG 准入之间的不一致。启动只登记缺失的本地／显式静态身份，碰撞拒绝，不覆盖管理员修改，也不提供密码登录。后续实际 HTTP 负测进一步确认，环境变量角色仍使已停用／降权配置账号获准；新增独立只读 verifier 在受保护请求中使用当前 PG 状态及角色，不在读取或采集时重建账号。真实登录会话保持原路径。账号核验不是运行中任务取消或全程长连接权限保证。

阶段证据均已核对对应日志，选择集重叠，不累加成项目测试数量：

- 来源元数据负测先 **6 failed**，完整性修复后 **26 passed / 64.99 秒**（`source-acquisition-integrity-green-20261009.log`）。损坏备份测试只在 `nasus_test_*` 中运行；曾误构造违反 FK 的夹具，修正夹具而非关闭生产约束。
- 事件寿命初始负测 **3 failed / 13 passed**；实时消息计数竞争补测 **2 failed / 18 passed**。最终 **20 passed / 190.235ms**（`image-read-event-promise-green-20261009.log`），包括实际已安装 QueryClient／QueryObserver，不只用 fake client。Portal contracts **799 passed / 3056.629ms**（`image-read-event-promise-contracts-20261009.log`）；build/lint/i18n 退出 0，约 1048.12 kB 主包警告保留。
- PG／私有 MinIO 的初始标准兼容批 **44 failed / 329 passed / 1 warning / 247.70 秒**（`source-acquisition-event-standard-gates-current-20261009.log`），43 项来自配置账号缺少持久身份，1 项是旧 Portal 文本边界断言。修复后原 API／runtime／Compose、配置账号、准入／回执和边界组合 **382 passed / 1 warning / 493.42 秒**，句柄 1608 已确认退出 0（`source-acquisition-event-standard-gates-verified-20261009.log`）。该批装载早于本轮 HTTP 当前角色 verifier，不作为后者的完整兼容证据。
- 配置账号启动专项 **38 passed / 136 deselected / 88.22 秒**（`source-acquisition-operator-bootstrap-current-20261009.log`）。本轮实际 HTTP 停用／降权／身份缺失负测 **8 failed / 9 deselected / 2.31 秒**（`source-operator-http-revocation-red-20261009.log`）；修复首批 **2 failed / 28 passed / 3.33 秒**，两失败来自旧夹具使用非正式 `disabled` 状态污染管理员列表，改为正式 `suspended`，不接受非法生产状态。当前账号／HTTP／纯验证器和原 auth／RBAC 专项 **35 passed / 139 deselected / 3.74 秒**（`source-operator-http-revocation-current-20261009.log`）；DDD／Portal／隔离 **163 passed / 1.34 秒**。
- 配置账号启动修复后的独立 exweb／准入／回执组合 **55 passed / 193.29 秒**（`source-acquisition-exweb-operator-current-20261009.log`），报告 `exweb-acquisition-operator-integrity-20261009.json` 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 和 126 个真实 Git blob。核验准入在 connector 前、拒绝时零 connector、命名 reader、整批撤权 403／恢复原历史、仅 README 受控修改以及旧 MinIO 原文回放；不是上游新提交、业务 gold、原生远端重采或目标运行。
- 同一版本的 Portal 组合 **34 passed / 2.5 分钟**（`image-read-operator-browser-current-20261009.log`）及 PG／私有 MinIO smoke **success**（`source-acquisition-event-smoke-current-20261009.log`），均退出 0。34 项中有纯 read-pair 契约，其他 UI 场景为真实 PG／MinIO；不声称全部 34 项都是实际浏览器三源业务试点。

HTTP verifier 扩大兼容批第一次误写不存在的 `test_identity_administration_api.py`，runner 退出 4、**no tests ran**（`source-operator-http-standard-gates-current-20261009.log`）；已改为实际文件 `test_identity_administration.py`，独立批 81628 已确认退出 0：**412 passed / 1 warning / 498.13 秒**（`source-operator-http-standard-gates-verified-20261009.log`）。范围为原 API／runtime／HTTP 控制／身份管理、配置账号及纯验证器、准入／整批回执、Compose／DDD／Portal／隔离，LangGraph `allowed_objects` 警告保留；不是全量 V1。最新 exweb 28690 已退出 0：**69 passed / 146.30 秒**（`source-operator-http-exweb-current-20261009.log`），包含当前 verifier／准入／整批读取与真实 exweb；报告 `exweb-operator-http-current-20261009.json` 保持原 126 文件、固定 commit/tree、拒绝零 connector 和旧归档回放的范围。浏览器 16405 已退出 0：**34 passed / 2.5 分钟**（`source-operator-http-browser-current-20261009.log`），不把先前 34 项累加。Portal contracts **799 passed / 2393.717ms**，build/lint/i18n 退出 0，主包 **1048.12 kB / gzip 290.00 kB** 警告保留；PG／私有 MinIO smoke **success**，句柄 25542 已退出 0。对应 `source-operator-http-{ui-contracts,build,lint,i18n,smoke}-current-20261009.log`。已实际查看最新 light/en 移动证据弹层和 dark/zh 移动结构继续 gate，保留证据滚动、文字换行与边缘流光。测试端口 18090／14181／18082／14175 已确认无 LISTEN，未重启开发服务或迁移开发库。

历史完整门禁现已确认终态：`system-image-source-receipt-acl-v1-release-20261009.log` **1 failed / 4800 passed / 70 skipped / 1 warning / 10369.78 秒**，原生 hash fault 场景在注入前因依赖摘要变化失败；后来独立 native **37 passed / 1 skipped** 不替代完整门禁。`system-image-tracked-ref-v1-release-20261009.log` 后端 **4737 passed / 70 skipped / 1 warning / 10688.46 秒**，浏览器 **4 failed / 2 skipped / 246 passed / 34.1 分钟**，失败为旧官方画像一键旅程、重复预算页链和 light/dark legacy 证据假设。后两类有上述专项修复，旧旅程独立复验仍 **1 failed**（`source-acquisition-legacy-journey-current-20261009.log`）；它仍期待采集后自动 official／ready，与固定来源、独立预算、审阅及发布审批不一致。不恢复错误自动发布，也不通过删除门禁宣称全绿。

完整 P0-P6 保留：采集 lease／逐来源结果／取消和崩溃恢复、自然语言与维护事件全入口、全计划预算、自动 delta／失效／调查／overlay／三方合并、五用途上下文及旧链 cutover、真实语义 gold／目标执行、安全容量／性能、完整 `verify:v1-release` 均尚无全部退出证据。`full_plan_accounting_verified=false`，Goal 继续 active。

## 采集回执列表的整批权限一致性（2026-10-09）

逐条检查仍有跨记录窗口：较早的代码回执获准后，在较晚的需求回执检查前／后真实撤销代码权限，列表和审计仍返回较早记录。新增实际 HTTP／PG／私有 MinIO 的四项负测全部失败（`source-receipt-batch-acl-red-20261009.log`，**4 failed / 19.35 秒**），不注入假 403，也不把要求缩小成只隐藏最后一条记录。

平台 application 现在在筛选、逐条鉴权、历史排序后执行资源端口的整批检查。来源 application 合并最终可见回执的项目与原选择，旧无选择记录要求全部当前来源可读；独立 READ COMMITTED 会话的一条 PostgreSQL `UNION ALL` 语句校验所有相关项目的成员、inventory、policy／epoch 和 scope fingerprint。中途撤权、成员删除或角色变化拒绝整份响应，缺端口／存储不可用及超过 128 项目拒绝为脱敏 503，不截断检查。原 API 路径、历史排序和业务事实不改变。详见[来源刷新授权契约](./source-refresh.md#回执的即时来源授权)。

当前已确认阶段终态，各选择集合重叠，不累计为项目测试总量：

- 纯来源／回执／application ports、DDD／Portal／隔离组合 **226 passed / 1.66 秒**（`source-receipt-batch-acl-ports-20261009.log`）。首次实际 API 批在 collection 阶段因新 helper 缺少 Python 3.9 的 postponed annotations 退出 2；补齐 future import 后，实际 PG／私有 MinIO 的初始回归 **47 passed / 79.67 秒**（`source-receipt-batch-acl-api-current-20261009.log`）。collection 错误不作为产品权限负测。
- 扩大的实际 PG／私有 MinIO 组合 **1 failed / 71 passed / 204.49 秒**（`source-receipt-batch-acl-exweb-api-current-20261009.log`）：12 项真实列表／审计负测和多项目校验均通过；唯一失败是新增 exweb 夹具把内部枚举误当时间顺序。改为至少两条实际 completed 回执通过后撤权，仍要求较早获准记录不能返回；没有修改生产排序或放宽权限断言。修正后的独立 exweb 组合已启动，终态另行记录，不能以 71 项通过替代。
- 修正后的独立组合 **96 passed / 164.02 秒**，runner 退出 0（`source-receipt-batch-acl-exweb-api-verified-20261009.log`）。选择集额外包含纯回执测试，不称为上一批相同数量的重跑。报告 `exweb-source-receipt-batch-acl-verified-20261009.json` 核验真实 126 文件、写前零 connector 拒绝、命名 reader 后独立采集、两条已获准 completed 回执之后撤权的整批 403、恢复后的原历史一致，以及 1 modified / 125 unchanged 与旧 MinIO 原文回放。受控 README 和 optional 资料为协议夹具，不是上游提交或业务 gold；未执行目标、外部模型或自动更新。
- 原刷新、同标签恢复、引导和真实非默认 Git 分支浏览器 **17 passed / 4.7 分钟**，隔离 runner 退出 0（`source-receipt-batch-acl-browser-current-20261009.log`）。报告 `exweb-source-receipt-batch-acl-browser-20261009.json` 固定 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 与真实 126 文件，只有代码修订变化，optional 和旧画像不变。已实际查看本轮 dark/zh 短屏恢复及 light/en exweb 结果截图，ID 换行、保留无滚动条滚动。浏览器是原功能兼容门禁，新增撤权负测由实际 API 测试验证。
- Portal contracts **792 passed / 0 failed / 3336.796ms**，build/lint/实际 i18n 门禁退出 0（`source-receipt-batch-acl-{ui-contracts,build,lint,i18n}-current-20261009.log`）；主包 **1047.80 kB / gzip 289.85 kB** 警告保留。PG／私有 MinIO smoke **success**，runner 退出 0（`source-receipt-batch-acl-smoke-current-20261009.log`）。误用不存在的 `tests/unit/*.test.cjs` glob 未运行测试，已改用正式 `test:portal-contracts`，不把命令错误算成功或产品失败。

更新代码的首批标准兼容门禁已确认退出 1：**1 failed / 543 passed / 1 warning / 627.88 秒**（`source-receipt-batch-acl-standard-gates-current-20261009.log`，句柄 **38339**）。唯一失败是 `after_later_check-tool-invocations` 夹具假设无序 PG scan 必然先返回较早命令；它在执行策略撤权之前触发自己的顺序断言，不是产品返回了错误状态。修正为在测试 state 端口明确安排真实 PG 回执／审计行的检查顺序，不伪造记录、鉴权或 403，仍要求较早代码回执已实际获准且较晚需求回执真实检查前／后才撤权。生产查询／排序不改动。单独 12 项权限负测和完整 544 项兼容集已重新启动，终态另记，不把前一批 543 项与专项拼成全绿。

修正后的两个独立批均已确认退出 0：真实 HTTP／PG／私有 MinIO 权限负测 **12 passed / 64.41 秒**（`source-receipt-batch-acl-negative-verified-20261009.log`，句柄 **72708**），完整相同 544 项兼容选择集 **544 passed / 1 warning / 565.99 秒**（`source-receipt-batch-acl-standard-gates-verified-20261009.log`，句柄 **89836**）。该集包含原 API／runtime／Compose、来源权限／回执／采集／并发、DDD／Portal／隔离检查；LangGraph `allowed_objects` 弃用警告保留。没有在这两个批次启动后修改生产代码，后续只更新验证记录；专项、96 项 exweb 和 17 项浏览器不相加为全项目数量，也不替代完整 `verify:v1-release`。

旧完整 V1 句柄 **68103** 和 **11719** 本轮再次轮询确认 live，装载早于本节补丁，不用它们证明当前完整 V1；没有因观察超时终止或重开。全部专项使用独立测试 PG 库与私有 MinIO 桶，不迁移开发数据库或重启开发服务。浏览器／smoke 测试端口 18090、14181、18082、14175 已确认无 LISTEN。

最后一条 SQL 只证明该次返回前的统一授权观察，不锁定后续 HTTP 序列化／网络发送期间的权限，也不补造旧回执原历史成员闭包。其余来源注册／读写／模型出口、采集 intent／lease 与崩溃恢复、自动维护／全项目 delta／overlay／合并、全计划费用、五用途与旧链 cutover、真实业务 gold／目标执行、安全容量和完整发布门禁仍保留原验收要求。`full_plan_accounting_verified=false`，Goal 继续 active。

## 原命令精确恢复与采集回执权限（2026-10-09）

未知 command ID 的 Portal 恢复改为 actor/project/canonical tool/request key 的 PG 精确 resolver，再读取并核验确切 command。不扫描列表、审计或 latest，不受原 256 条窗口限制，不发送第二条写入。实际 API 测试插入 260 条噪声历史并禁止 load/list 扫描，仍恢复原回执；项目、账号与 conversation 范围不能互换。

采集详情、resolver、列表、关联审计、幂等 POST 命中及确认均重新检查项目和来源权限。按来源刷新要求原选择可读并复查 fingerprint；旧整批回执要求当前全部注册来源可读，不能通过旧无选择命令泄露已撤权来源。共享 Conversation／新旧 Outbox 只返回脱敏生命周期，包括外层 patch；原数据库历史不改写。Runtime 使用 application port，不引入 ORM 或来源 Provider。该关口不是原历史清单闭包核验，也不代表所有首次写动作、生成消息和模型出口已完成来源授权。

当前已确认终态，选择集合有重叠，不能累加成项目测试总量：

- 精确恢复与按来源读权限的纯端口／DDD／Portal／隔离检查 **213 passed / 1.73 秒**（`source-refresh-receipt-access-pure-current-20261009.log`）；实际 PG／私有 MinIO、代码索引 lifecycle 兼容与同类边界 **245 passed / 227.26 秒**（`source-refresh-receipt-access-api-current-20261009.log`）。这批装载早于后续 replay 和旧整批补齐，不作为它们的验证证据。
- 精确恢复后的 Portal contracts **792 passed / 0 failed / 2472.421625ms**（`source-refresh-exact-resolution-all-ui-20261009.log`）。明确 exweb opt-in 的恢复／原引导／实际非默认 Git 分支浏览器 **17 passed / 4.0 分钟**（`source-refresh-exact-resolution-browser-20261009.log`），报告 `exweb-source-refresh-exact-resolution-browser-20261009.json` 核验原 commit/tree、126 个文件、仅代码来源修订变化、optional 与旧画像不变。
- 实际审计权限负测先 **1 failed / 8 deselected / 4.03 秒**（`source-refresh-receipt-audit-acl-red-20261009.log`），暴露源撤权后仍能读关联审计；修复为按原 invocation 再检查资源权限。幂等 POST／重复确认负测 **2 failed / 1 passed / 9 deselected / 8.70 秒**（`source-refresh-receipt-replay-acl-red-20261009.log`），真实 tester 仍拥有工具 RBAC，但失去来源权限后返回旧结果；新增 Runtime 端口复查修复该旁路。
- 完整读取期间撤权首批 **1 failed / 17 passed / 45.89 秒**（`source-refresh-receipt-inflight-acl-20261009.log`），揭示目标回执已隐藏但列表仍有旧整批回执。没有把断言缩小为只隐藏新命令；补齐旧回执的完整当前来源检查及共享 patch 脱敏。
- 最新纯端口／来源权限／事件／DDD／Portal／隔离组合 **248 passed / 2.18 秒**（`source-receipt-complete-acl-ports-20261009.log`），实际 PG／私有 MinIO、六条读取中撤权、旧整批、授权恢复和来源选择兼容 **281 passed / 86.13 秒**（`source-receipt-complete-acl-api-20261009.log`），两批 runner 均已确认退出 0。Outbox 专项直接消费应用层 SSE stream 并使用实际 PG 历史，HTTP Conversation 快照另行验证；不冒充真实网络 SSE 流验收。

新增纯回执 fixture 首次遗漏 ToolResult 的 invocation_id/status 导致 **20 failed**；确认 fixture 后续遗漏 conversation 时断言了不存在的消息，出现 **1 failed / 221 passed** 及旧装载组合 **1 failed / 242 passed**。修正夹具字段与会话 pin，没有降低原消息、事件及 claim 断言，之后端口组合 **222 passed / 2.02 秒**。原日志保留，不把这些夹具失败说成产品功能回归。误用不存在的 npm `verify:i18n` 命令也保留失败记录，实际门禁命令为 `npm run test:i18n`。

上述回执补丁的兼容门禁已确认退出 0：**449 passed / 1 warning / 454.95 秒**（`source-receipt-complete-acl-standard-gates-20261009.log`），LangGraph `allowed_objects` 警告保留。明确 opt-in 的 exweb 浏览器 **17 passed / 4.4 分钟**、smoke **success**，对应 `source-receipt-complete-acl-browser-20261009.log` 和 `source-receipt-complete-acl-smoke-20261009.log`。Portal contracts **792 passed / 0 failed / 2984.408708ms**，build/lint/实际 i18n 门禁退出 0，主包 **1047.80 kB / gzip 289.85 kB** 警告不放宽。短屏 dark/zh、light/en 和 exweb 滚动截图已实际查看，长 SHA-256 换行，无横向溢出。浏览器报告 `exweb-source-receipt-complete-acl-browser-20261009.json` 固定原 commit/tree 与 126 个文件，只有选中代码来源修订变化，optional 与旧画像不变；不是上游新提交、业务 gold、原生远端重采或目标执行。

完整批 `system-image-source-receipt-acl-v1-release-20261009.log` 的句柄 **68103** 本轮再次实际轮询确认 live，旧加载的 **11719** 同样 live；两批均早于下节采集写侧补丁装载，不能当作该补丁的完整门禁。没有因观察超时终止／替换旧任务，未知终态不能记绿色。所有专项仅使用新建测试 PG 库与私有 MinIO 桶，未迁移开发数据库或重启开发业务服务。

P0-P6 全范围保持不变：首次写动作与其他读取的完整来源授权、采集意图/lease 和崩溃恢复、自动维护／delta／overlay／合并、全计划费用、五用途／旧链 cutover、真实语义 gold 与目标执行、安全容量／性能和完整发布门禁仍未全部完成。`full_plan_accounting_verified=false`，Goal 继续 active。

## 采集写侧与完成回执的来源权限（2026-10-09）

重新检查首次写路径发现，旧回执虽然已检查 ACL，但 `sources.ingest` 的初次 connector 仍只依赖工具 RBAC／项目角色。真实 tester 无来源权限仍 completed，真实采集后撤权也仍接纳新修订。修复将授权放进采集 application use case，production 显式装配 SourceScope 端口；选择模式与旧整批均在写前、各 connector 前后及接纳／派生关口复核原 scope，缺端口和策略不可用拒绝，错项目／重复来源 projection 拒绝。详情见[来源刷新](./source-refresh.md#采集写侧的即时来源授权)。

同时发现业务已经完成、POST 返回之前的另一个撤权窗口，两个真实 PG 负测都返回了 completed 正文。平台 application 在 create／confirm 的完成结果返回前复用资源授权端口；撤权隐藏 HTTP 回执但保持合法已完成事实，恢复权限只读取原回执。它不重新 dispatch、不撤销合法采集，也不把客户端失联当作执行失败。

已确认的阶段证据，选择集重叠，不累计为项目测试总量：

- 第一批新夹具误用 `tester` 被 pytest 作为测试收集，且在来源筛选视图取全局 manifest，出现 **4 failed / 1 error / 10.86 秒**（`source-ingestion-live-acl-red-20261009.log`）。改为明确 helper、策略变更前固定请求、用实际 PG project snapshot 核验事实，不降低“无 connector／无修订／无分块变化”要求。
- 修正夹具后的真实写侧负测 **4 failed / 11.91 秒**（`source-ingestion-live-acl-red-verified-20261009.log`），实际证明首次受限来源和 connector 返回后撤权的两类旁路。修复后的纯端口／DDD 组合 **228 passed / 2.27 秒**，实际 PG／私有 MinIO HTTP 回归 **37 passed / 100.95 秒**；这两批早于后续身份一致性和最终回执检查。
- 补齐整批 projection 唯一／同项目检查后，纯端口／DDD／Portal／隔离组合 **268 passed / 2.28 秒**（`source-ingestion-live-acl-ports-current-20261009.log`），固定 exweb 与实际 PG／私有 MinIO 组合 **38 passed / 117.33 秒**（`source-ingestion-live-acl-exweb-api-current-20261009.log`），runner 退出 0。报告 `exweb-source-ingestion-live-acl-20261009.json` 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`、126 个文件、无权时零 connector 调用及命名 reader 后成功，1 modified / 125 unchanged，未选中来源与原归档不变。源为已审查 Git blob 的本地导出，不冒称原生远端 Git、外部模型或 exweb 业务执行。
- 完成后返回前的真实撤权负测 **2 failed / 36 deselected / 7.15 秒**（`source-ingestion-response-acl-red-20261009.log`），直接使用实际完成事件与 PG 策略变化，不注入假 403。最终端口／exweb API／兼容门禁已按更新代码独立启动，终态另行追加；先前完整批不能作为新补丁验证。

最终阶段已确认终态，各集合仍有重叠，不相加：

- 全部采集／回执端口、DDD／Portal／隔离组合 **300 passed / 2.25 秒**（`source-ingestion-response-acl-ports-current-20261009.log`）。真实 PG／私有 MinIO／固定 exweb 的 HTTP 组合 **72 passed / 133.66 秒**（`source-ingestion-response-acl-exweb-api-current-20261009.log`）；补充“需求可读但未选中代码受限且物理文件已删除”后，同一组合 **73 passed / 133.90 秒**（`source-ingestion-response-acl-exweb-api-expanded-20261009.log`）。所有 runner 退出 0；实际仅读取选中需求，原代码事实／分块不变，整批请求拒绝，不以纯端口替代此权限差异证据。
- 固定 exweb 的最新独立 API 报告 `exweb-source-ingestion-response-acl-expanded-20261009.json` 再核验原 commit/tree 与 126 个文件、真实来源拒绝／命名 reader 授权、只有选中代码变更及历史回放。实际 canonical Invocation、PG snapshot、私有 MinIO 工件和文件 delta 均参与验证；没有执行 exweb、安装目标依赖或调用外部模型。可选需求与用例仍是显式协议夹具，不是业务 gold。
- 采集写侧早期兼容门禁 **425 passed / 1 warning / 483.24 秒**（`source-ingestion-live-acl-standard-gates-current-20261009.log`），它在最终 POST 返回复查前加载，不替代后续批。最终更新代码的 API／runtime／Compose／采集与回执／DDD／Portal／隔离兼容门禁 **459 passed / 1 warning / 529.59 秒**（`source-ingestion-response-acl-standard-gates-current-20261009.log`），runner 退出 0。额外的需求单选权限差异测试加入晚于该批 collection，由上述 73 项独立批验证；生产代码没有在最终门禁启动后改动。LangGraph `allowed_objects` 弃用警告保留。
- 明确 exweb opt-in 的实际浏览器原刷新／只读恢复／原引导／非默认 Git 分支 **17 passed / 4.6 分钟**（`source-ingestion-response-acl-browser-current-20261009.log`），runner 退出 0。报告 `exweb-source-ingestion-response-acl-browser-20261009.json` 固定 126 个文件，只有代码修订变化，optional 和旧画像不变；这是实际 canonical 采集，不是原生 Provider／远端 Git／目标运行证明。dark/zh 390×568 的只读恢复滚动及 light/en exweb 结果截图已实际查看，仍使用共享视觉，不显示滚动条或横向溢出。
- Portal contracts **792 passed / 0 failed / 3619.813666ms**，build/lint/实际 i18n 门禁退出 0（`source-ingestion-response-acl-{ui-contracts,build,lint,i18n}-current-20261009.log`），主包 **1047.80 kB / gzip 289.85 kB** 警告保留。实际 PG／私有 MinIO smoke **success**（`source-ingestion-response-acl-smoke-current-20261009.log`），runner 退出 0；本轮临时浏览器／smoke 端口 18090、14181、18082、14175 已确认无监听。未迁移开发数据库、重启开发服务或写开发项目。

先前完整 V1 的 **68103** 与 **11719** 收尾再次轮询确认仍 live，没有因观察超时终止或重开。两批装载早于本节生产改动，完整目标与当前工作区完整门禁仍未证明；本节的 459／17／73 不能拼接成 `verify:v1-release` 全绿。

上述阶段检查不是采集事务或崩溃恢复。connector 可能已有私有物理工件，较早已合法接纳的修订不回滚；中途失去权限的 ingest 开始标记仍需正式 intent／lease 处理。列表跨记录期间的晚撤权窗口随后由上面的“整批权限一致性”切片补齐；来源注册与其他写动作、完整历史成员闭包、共享消息与模型出口仍需验收，不能以本轮阶段负测声明完整安全零泄漏。P0-P6、全计划费用和五用途／旧链切换、真实 gold／目标执行与完整 V1 均保留原要求，`full_plan_accounting_verified=false`，Goal 继续 active。

## 显式跟踪分支与历史迁移兼容（2026-10-09）

0093 新增 nullable `tracked_ref`，代码来源只接受完整 heads/tags ref。同 URI 的不同 ref 保持独立 binding；旧 null 身份摘要不变，已有 ref 不可 UPDATE 改写。实际 Git fetch 固定 ref 后解析 commit，缺 ref 不回落默认分支或普通工作树；历史恢复仍固定原 commit。原 Goal 的代码补源字段与 canonical 注册共用同一显式值，optional 占位仍未注册，结构预算独立。详见[来源跟踪契约](./source-tracking.md)。

当前已确认终态，各集合重叠，不累加为项目测试总量：

- 纯 domain／Git／并发和冻结 projector 组合 **90 passed / 6.62 秒**（`source-tracked-ref-projection-domain-current-20261009.log`）；DDD／Portal／identity／provenance／隔离组合 **233 passed / 2.06 秒**（`source-tracked-ref-boundaries-current-20261009.log`）。
- 空 PG 全链升级和真实 PG／私有 MinIO 的来源、跟踪 API、旧 lifecycle、访问策略及两个来源 projector 组合 **70 passed / 202.96 秒**（`source-tracked-ref-pg-minio-current-20261009.log`）。另外实际有数据的 pre-0093 列模拟及 alias／object provenance repository **27 passed / 9.57 秒**（`source-tracked-ref-historical-schema-current-20261009.log`）。这不是开发数据库升级；所有数据库和桶均为测试私有资源。
- 当前 API／runtime／Compose／DDD／隔离门禁 **311 passed / 1 warning / 338.51 秒**（`source-tracked-ref-api-gates-current-20261009.log`），隔离 runner 退出 0。原 LangGraph `allowed_objects` 弃用警告保留，不以静音代替修复。
- 固定 exweb 的实际 Git／PG／MinIO API 复验 **7 passed / 22.88 秒**（`source-tracked-ref-exweb-all-blobs-20261009.log`）。独立报告 `exweb-tracked-ref-all-blobs-20261009.json` 核验真实 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`、tree hash `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e` 和全部 126 个历史 Git blob 的逐项字节比较；受控新分支为 **1 modified / 125 unchanged**，其他 ref 和旧 MinIO 归档不变。私有 origin 是真实 Git，但没有重新访问上游远端，也未运行 exweb、安装目标依赖或调用外部模型。
- 主题修复后的两个原引导和两个非默认分支浏览器 **4 passed / 38.5 秒**（`source-tracked-ref-browser-theme-final-20261009.log`），实际 loopback Git daemon、PG 和私有 MinIO，覆盖 light/en、dark/zh 390px、原 Goal 与预算 gate。代码字段由硬编码暗背景改为 `var(--bg)`，branch label 改为独立 grid；浏览器核验背景／字体与主题相同。前端 build/lint/i18n 退出 0，原大包警告保留。
- 标准隔离 PG／私有 MinIO smoke **success**（`source-tracked-ref-smoke-current-20261009.log`），runner 退出 0；它不是完整 V1 或原生业务试点。

早期 `source-tracked-ref-pg-minio-20261009.log` 在 0069 升级时失败：冻结回填错误读取尚未存在的 0093 列。修复为只选择各自历史版本需要的 binding 字段，不改变旧 digest／审计。0093 的不可变 ref 触发器明确使用 `23514`，保持 IntegrityError 契约。另有初次 i18n 未登记 placeholder，以及两批新浏览器 **2 failed / 2 passed**：分别是新夹具在 Turn 完成前读取 Goal、和误把两个 optional pending 占位算成已注册代码。修复为等待实际 Turn 终态、分开核验 code 和未注册占位，不删占位或降低独立预算门禁。日志原样保留。

旧完整批 `system-image-reference-pins-v1-release-20261008.log` 的句柄 **73920** 已确认退出 1：**3 failed / 4569 passed / 66 skipped / 1 warning / 12266.65 秒**。失败分别为旧 lifecycle gate 断言、孤立项目 Conversation 列表和 DDD 旧 facade 参数断言；当前专项已覆盖对应修复，不将旧批宣称绿色。新原始 `npm run verify:v1-release` 批 `system-image-tracked-ref-v1-release-20261009.log`、句柄 **11719** 已实际启动并确认仍 live，正运行完整后端集合。其前端装载早于下节恢复指针修改，不能据此认定最新工作区完整全绿；未因观察超时重启／终止，终态另行追加。

## 同标签页来源刷新恢复指针（2026-10-09）

按当前账号／项目保存原 request key、完整选择和旧 manifest pin，原 POST 前写入并回读核验。重载／重新打开／跨路由只恢复指针、锁定新选择，显式查询才用当前权限 GET 原命令；已知 command ID 直接读取，不再扫描 latest。错误或不可用存储不自动丢弃，账号／项目切换重建内部组件，不保存 token、URI、正文、结果或确认权。终态后仍由用户显式清除确切原指针并重新选择，不能继承旧选择授权。服务端事实／采集租约／跨存储崩溃恢复没有因此补齐。详见[来源刷新](./source-refresh.md#portal-操作与失联恢复)。

首次 23 项纯测试因新模块尚未创建而失败（`source-refresh-recovery-red-20261009.log`），这是实现前缺失证据，不冒充既有逻辑的行为回归。实现后的 pointer／API 组合 **70 passed**（`source-refresh-recovery-pure-ui-current-20261009.log`）；全 Portal contracts **786 passed / 0 failed / 2412.019ms**（`source-refresh-recovery-all-contracts-current-20261009.log`），DDD／Portal／隔离 **163 passed / 1.35 秒**（`source-refresh-recovery-boundaries-current-20261009.log`）。build/lint/i18n 退出 0，主包 **1047.90 kB** 警告保留。

初次真实 PG／私有 MinIO 浏览器组合 **13 passed / 1 skipped / 2.6 分钟**（`source-refresh-recovery-browser-current-20261009.log`）：原刷新、恢复、损坏／不可用存储、原引导和非默认 Git 分支均通过；未设置 exweb opt-in 的一项 skip 不计通过。扩大后的 quota／真实账号切换与明确 opt-in exweb 已有后续 **17 passed** 的终态，见上节精确恢复批；不把原 skip 算作通过。当前未重启开发业务服务或迁移开发库。

完整目标保持 P0-P6 原范围：webhook/reconcile、自动项目 delta、overlay/tombstone／合并、全计划多能力预算、五用途上下文／旧链切换、真实目标执行与业务 gold、安全容量／性能仍未全部交付。`full_plan_accounting_verified=false` 和独立门禁不放宽，Goal 继续 active。

## 按来源刷新 Portal 与当前兼容门禁（2026-10-09）

本节记录持久恢复指针前的历史批次。来源刷新已经接入 Knowledge 的独立弹层。当前项目 working manifest/hash 与完整注册范围固定，默认无选择，1–100 项显式 canonical 提交；多代码 binding 不按类型合并。读取失败/错 scope 隐藏旧内容，相同 frozen scope 的 SSE/焦点重读不清空选择，变化后不恢复旧同意。丢失回执保留原 request/input，只 GET 唯一原命令；无自动重发、latest 回落、结构构建、物化、审阅或发布。关闭只取消恢复读，不取消已经提交的写动作。共享证据弹层的 token/焦点/隐藏滚动条和移动尺寸保留；同标签页持久指针及未知 ID 的精确恢复已由上节后续交付。详见[来源刷新契约](./source-refresh.md)。

当前已确认终态，选择集有重叠，不累加为全项目测试数量：

- 更新旧生命周期测试后，真实 PG/私有 MinIO 的来源选择、原 Goal 引用关口及继续组合 **17 passed / 1 warning / 237.10 秒**（`source-refresh-lifecycle-current-20261008.log`）。测试现在实际经过 structural candidate、独立调查、reference candidate review，再完整读取候选/gaps 到 completion review；核验原 Goal、proposed 证据、检查点回放和审计，不创建决定/成员/发布或假 ready。独立调查确认仍要求实际 actor，不用过时流程跳过新 gate。
- 原 API/runtime/compose 与固定 exweb 选择门禁 **173 passed / 1 warning / 374.12 秒**，隔离 runner 退出 0（`source-refresh-api-gates-current-20261009.log`）。报告 `exweb-source-refresh-lifecycle-20261009.json` 核验固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`、126 个真实 Git blob、**1 modified / 125 unchanged**、3 个未选中来源其中 2 个可选资料不变及旧归档完整回放；没有原生远程 Git 重采、外部模型、目标执行、业务 gold 或自动维护。早期误名字段报告原样保留。
- 新取消负测先 **1 failed / 44 passed**（`source-refresh-ui-cancellation-red-20261009.log`），证实 discovery 后取消仍会发起详情读；新增取消检查及弹层 cleanup Abort 后 **45 passed / 183.24ms**（`source-refresh-ui-cancellation-green-20261009.log`）。全 Portal contracts **753 passed / 0 failed / 3524.64ms**（`source-refresh-ui-all-contracts-cancellation-20261009.log`）；domain/Git/DDD/Portal/identity/delta 组合 **206 passed / 8.25 秒**（`source-refresh-ui-boundaries-verified-20261009.log`）。build/lint/i18n 退出 0，现存约 **1042.53 kB** 主包警告保留，不提高阈值。
- 六项来源刷新实际 PG/MinIO 浏览器 **6 passed / 2.2 分钟**，runner 退出 0（`source-refresh-ui-browser-verified-20261009.log`）。覆盖 light/en、dark/zh 390px、同 scope 重读后保留选择、唯一 POST、原写成功但响应丢失后的 GET-only 恢复、实际新 manifest 推进后的旧请求拒绝、坏客户端 scope 隐藏及完整 exweb Git 导出。客户端错 scope 是明确协议注入，不冒充实际后端 ACL 证明。`exweb-source-refresh-browser-verified-20261009.json` 固定真实 126 文件与前后清单；伴随文档/用例及 README 修改是明确协议夹具。未选中 optional 文件已删除仍未重读，原画像对象不变，不执行目标或模型。
- 原引导构建浏览器 **2 passed / 35.4 秒**（`source-refresh-ui-guided-build-verified-20261009.log`），隔离 PG/MinIO 标准 smoke **success**，runner 退出 0（`source-refresh-ui-smoke-verified-20261009.log`）。它们不是完整 V1、原生 Provider 或真实业务运行门禁。

初次 Portal build/lint 分别因未登记 `Tool invocation` 文案及控制字符正则失败；修复为登记译文及逐字符校验，未关闭规则。首次六项浏览器 **5 failed / 1 passed / 4.4 分钟**（`source-refresh-ui-browser-20261009.log`）暴露 UI 选择被只读更新时间清空，以及四项夹具未设置浏览器 locale。scope 校验修复后的第二批 **4 failed / 2 passed / 4.1 分钟**（`source-refresh-ui-browser-current-20261009.log`）四项均停在英文按钮查找；生产 locale 独立于全局 settings。测试显式设置本地语言后才有上述六项通过，不修改产品语言策略或放宽 selector。旧日志保留。

扩大后的实际 PG/MinIO 浏览器 **7 passed / 2.1 分钟**，runner 退出 0（`source-refresh-ui-browser-scroll-cancel-20261009.log`）。新增关闭场景先让原 canonical POST 真正完成，再故意丢失响应并挂起恢复 GET；关闭后实际观察 `net::ERR_ABORTED`、零详情 GET、仅一条原 POST，并以独立 API 读取确认原命令仍 completed，没有伪装采集取消。正常深浅色/移动场景校验弹层不超出 viewport、body 无横向溢出、标准和 WebKit 滚动条隐藏。exweb 完成区域确有 overflow，滚动到实际 maximum 后截图显示完整原 command 和结果；完整七项重新执行，不以此前六项通过替代。

最终独立报告 `exweb-source-refresh-browser-scroll-cancel-20261009.json` 核验同一固定 commit/tree hash 和真实 126 文件，只有选中代码 source revision 改变；optional pins 与旧画像保持不变。已查看最新 `output/playwright/source-refresh-light-en.png`、`source-refresh-dark-zh.png` 和 `source-refresh-exweb.png`，长 ID 换行，结果区域可见且保留无滚动条滚动。18086/14179、18087/14180、18082/14175 在测试 terminal 后均无 LISTEN，未重启开发业务服务或写开发数据库。

当时观察的完整旧批句柄 **73920** 已有失败终态，详见上面的 0093 记录，不再把 94% 历史观察当成 live。这轮收集/装载早于来源刷新及后续兼容修复，不证明当前全量 V1。完整 P0-P6 保持原退出条件，自动维护/全项目 delta/overlay/合并、全计划多能力预算、五用途上下文与真实运行反馈仍待交付，Goal 未标完成。

## 按来源刷新与快照污染检查（2026-10-08）

`system_image.sources.ingest` 新增可选 `source_ids + expected_manifest_id/hash`；原整批输入保持兼容。项目锁内核验清单和注册 ID，错范围在采集/状态写入前失败；只重采选中来源、只重建其分片，最后冻结完整来源清单。未选中的来源/分片/时间和旧画像不修改。可选失败留下 gap、旧 PG revision/manifest 保留但不作为当前批准事实；第二份健康代码不能掩盖所选必需代码失败。已完成 canonical 幂等命令不再次采集；后续建议走独立固定输入结构入口，不自动整批物化或发布。Git revision cache 同时拒绝 ignored 文件、assume-unchanged/skip-worktree 和符号链接 `.git` 污染。详见[契约与边界](./source-refresh.md)。

纯选择 **30 passed / 0.13 秒**，Git connector **19 passed / 4.85 秒**。首轮 DDD 组合 **1 failed / 160 passed / 1.64 秒**（`source-refresh-boundaries-20261008.log`）为旧文本断言只识别无 selection 的 facade 转发；更新为明确检查新增参数转发，未放宽分层要求。当前 domain/DDD/identity/delta/Git 组合 **180 passed / 7.39 秒**（`source-refresh-contracts-current-20261008.log`）。

隔离 PG/私有 MinIO 的第一组 HTTP/原多来源/inventory **10 passed / 33.83 秒**（`source-refresh-api-20261008.log`）。扩大必需失败及真实 exweb 后首轮 **1 failed / 11 passed / 47.33 秒**（`source-refresh-exweb-api-20261008.log`）：新夹具误把旧 owner `legacy_draft` 视图当成 published/source-filtered 的脱敏视图；没有改变生产脱敏逻辑或以此宣称旧链切换。修正为核验实际 legacy 作用域并独立要求新成功回执不含路径/存储 URL，组合 **12 passed / 47.70 秒**（`source-refresh-exweb-api-verified-20261008.log`）。

报告 `exweb-source-refresh-verified-20261008.json` 使用真实固定 Git blob 导出、正式工具采集、PG/MinIO 和完整 126 文件。受控 README 修改只推进所选代码来源；另一个代码 sentinel、US 和历史用例仍固定，即使伴随文件已移除也不重读。源差异 **1 modified / 125 unchanged**，旧全文仍从归档回放。该早期报告的 `unchanged_optional_sources=3` 实际包含未选中代码 sentinel，字段命名已在测试中修正为区分 unselected/optional，最终报告和组合门禁终态另行记录；不编辑旧报告伪装原批证据。没有原生远程 Git 采集、业务 gold、目标执行、模型调用、自动失效或完整 P4 验收。

Portal build/lint 退出 0（`source-refresh-portal-build-20261008.log`、`source-refresh-portal-lint-20261008.log`），原大包警告保留。专项引导浏览器、标准 smoke 和当前 API/runtime/compose/exweb 门禁已独立运行，结果待以下追加记录；它们不替代完整 V1。旧全量句柄 73920 仍已确认 live，模块装载早于本切片，不用它证明新增选择分支。

## 阶段状态

| 阶段 | 当前证据 | 尚未完成 |
| --- | --- | --- |
| P0 Provider 契约 | CBM 0.8.1 真实 CLI；长项目标识兼容；精确行号核验；受控进程组/最小环境、批准文件的私有临时快照与索引；公开关系分区与查询/边数预算、截断；本地类型化能力声明与 v2 分析报告/Portal 的具体缺口；真实 exweb 三次一致性及未验证观察 gap；0079 PG generation/投影 pin/epoch fencing/原生重建及确认式结构入口；0080 实际 MCP 握手与持久原生工具 schema pin；0081 同命令/来源不得在重试中替换 Provider 或修订；公开索引发现/状态/确认式取消、当前来源权限与私有回放及 Portal 入口；CodeGraph 1.6.2 公开 SDK 防腐／私有完整资产副本、同 exweb 三次结构对照、实际两项目身份隔离／取消及两个真实文档提交的 PG／MinIO 历史证据；SDK 显式 factory、持久 generation/真实契约回执、完整有界分页与新实例重建；真实 Temporal 结构任务更换 Worker 对象后的原命令重试；三源 SDK 原 AgentGoal、独立调查及引用审阅的原生 PG／MinIO／Temporal 证据 | CodeIntelligencePort v2 完整业务 Workflow 自动恢复/公开 reopen 与原生语言/结果完整性验证；SDK Agent 的跨进程强杀／跨主机恢复；强杀遗留资源清扫；实际代码变化／四语言的完整 Provider 对照；独立账号/禁网/CPU/内存隔离；完整定位 gold、大规模分页及性能门禁；跨平台 release/transitive digest 与供应链锁定 |
| P1 多源不可变底座 | 多代码/多文档登记不覆盖；MinIO 原文/清单；PG 不可变来源与代码身份登记；0069 新物化公开代码 ID 切换、已有 Provider mapping 审计回填及固定画像别名查询；0070 完整对象来源子图及原生元数据核验；0093 显式 heads/tags 身份、实际 Git 分支采集和固定 exweb 全字节历史回放；代码 Evidence 与来源权限检查；ACL 策略历史、CAS epoch、检索、Agent 上下文及画像/知识只读查询；采集 inventory、逐文件解析诊断与 Java 注解结构观察；来源受控的修订/报告选择、筛选和分页 UI；真实 exweb 双适配器身份、546 条原文、13 条注解路由及受控报告回放；固定 manifest/代码修订/证据集合的静态画像候选；0042 新增需求/用例/静态 Python 脚本投影、字段证据、MinIO 正文及冻结文档成员 | 完整来源注册表切换、未登记历史来源恢复、rename/move/split/merge lineage；二进制文档和其他脚本语言原生证据适配；多语言/框架完整结构 inventory、配置与动态/继承入口解析；其余读取路径与派生来源证明、模型出口；其余 assertion/decision 类型、通用 parent/overlay、正式消费者切到 0053 publication head。source head 与 publication head 保持独立 |
| P2 自主结构画像 | 复用现有 AgentGoal/ToolRuntime；固定画像与计划查询、重新授权 receipt；来源固定的调查计划；确认的单项结构执行、目标基线绑定、候选/计划工件同事务及知识页操作；显式 AgentGoal 计划读取/确认/恢复、LangGraph PG checkpoint 和固定输入防回退；0041 将结构执行授权与 goal/manifest/target/version/预算持久绑定，并原子预留一次 work item；0053 独立确认式发布审阅；代码索引持久取消与候选提交互斥；0082 结构任务 Temporal/PG intent/epoch 恢复、Agent 等待真实任务、Portal 当前账号命令发现/刷新恢复及原生 exweb 两入口验证；0083 独立确认式结构停止、排队取消、Worker 清理后确认及候选提交竞争；0084 固定证据调查追加修订、三轮无新增暂停、原结构 goal 继续至独立调查确认、持久查询任务与完成审阅；Portal SSE 重放不再回退控制快照；0085 原展示 pin 贯穿 Temporal、结构继续消费回执、公共聊天确认，以及显式无调用预算/补源准备的条件写入；0086 补源草稿与 0087 同目标追加阶段、新计划独立授权、Local/LangGraph PG/真实 Temporal 恢复和 Portal 显式继续 | 完整 BuildIntent/引导与其余补源恢复分支、全计划多能力授权与累计费用账本、其余能力的租约/取消、旧 inline 崩溃恢复、完整动态/反证调查与重规划、其余恢复/治理分支的原子 checkpoint 与 owner fencing、完整引导/聊天 UI、其余 Temporal 工件恢复和构建完成到发布审阅的完整引导 |
| P3 语义关联 | 明确标签的测试前置条件、步骤、预期、需求引用已有原文证据；0046 独立来源 AC/规则；固定 AC 的代码/测试召回、canonical 回执与 UI 原文调查；0047 确认式一次模型评估、HTTP adapter、PG 预留/私有工件归档；0048 typed assertion 与追加式人工裁决；0049 v3 语义成员冻结及独立确认；0043-0045 references 候选/裁决/子成员；跨修订显式适用性及历史头自动发现、模型入口拒绝拦截；reviewed v2 在 top-N 前过滤、固定头回放与 Portal/Agent 接入；0050 固定来源 AC 的独立批准、observable oracle、撤回、审计和同命令恢复 | 完整正式 US/AC authoring、BehaviorSpec 与字段级 authority、完整多格式抽取、结构/向量召回及通用模型出口策略、受控外部真实模型语义验证、可扩展负向索引与完整跨版本重审覆盖治理、冲突、readiness 向量及置信度校准 |
| P4 持续更新 | 来源快照已隔离，可保留两个修订；0045 审阅候选固定父修订/hash；0053 独立、不可变的画像发布审阅/记录及 PG CAS head，同事务审计/Outbox，Portal 与 Agent 命令入口；画像/知识查询及 Agent 画像上下文开始按 publication pin 读取；0054 固定 publication/model 的有界 PG 混合检索、私有 trace、确认式索引构建及 Portal 状态入口；同 binding 文件差异与固定 context/scope/generation/case/coverage/mapping 的有界只读影响预览；0067 独立确认的持久 DAG 失效事实，阻断同一精确画像下新旧上下文的当前使用，保留历史及其他画像；0068 当前测试设计链的完整派生/来源范围登记，0070 对象来源祖先子图；0076 独立政策/批准的历史知识画像回滚、不可变新发布及 CAS，当前验证范围见下文 | 其余正式语义消费者和下游生成切换、真实模型/gold 与大规模检索性能、webhook/reconciliation、其余全项目 Derivation/query-scope 索引与完整 delta DAG、自动增量调查/重建、通用 overlay/tombstone、分支三方合并、索引增量与批次恢复 |
| P5 下游闭环 | 0051 固定 test_design ContextPack，强制 AC/规则及批准 oracle、负向筛选、PG/MinIO 回放与 Portal；v2 按 AC 拆包、v4 publication、v5 trace；0055-0056 确认式 AC 检索、Temporal 恢复与持久取消；0057 独立范围审阅及显式义务/gap；0058-0060 草稿/planned coverage 原子归档、原生单次预算与调用回执、Temporal/Portal 生命周期及单次终态恢复；0061 独立断言映射及 reviewer/Agent 发现；0062 PG worker fencing；0063 完整累计预算、逐批 claim/reply/audit；0064 v3 aggregate/逐调用 provenance/完整草稿原子归并；0065 独立新命令的完整多批恢复及共享 Tool/Temporal/Portal 接入，具体证据见下文；旧生成链未迁移 | 容量与性能完整门禁、其余用途和 provider/build/index 租约、调查全计划累计预算、自动冲突、Agent 动态编排、脚本/RunPlan pin、真实受控运行和反馈 |
| P6 加固试点 | 新增 PG 隔离测试运行器和若干安全负测 | 全量权限/模型出口/取消/容量/恢复测试、gold 对照评估、完整 V1 门禁及真实业务试点 |

## 实现边界

- 0053 已提供独立发布 head，替代“只有 source head”的状态；它只批准固定知识快照，不批准业务期望、覆盖率或发布质量。新 ContextPack v4 已绑定 publication；旧 v1-v3 保持原契约，原有生成路径尚未切换，不能把新增 head 视为完整 cutover 或 P4/P5 完成。

- P1/P3 的 assertion/decision membership 已包括 0045 references 与 0049 implements/asserts 子候选；其他关系类型、完整跨版本重审/lineage、正式批准版本及通用 overlay 仍属于未完成范围。

- `0031_source_snapshots` 是 additive migration，不删除或重写旧业务表。无原文快照的旧来源不伪造 verified 修订，在清单中标为 `legacy_unverified`。
- 新 `source_bindings` 使用 UUID，通过 `legacy_source_id` 对接兼容 DTO；这不是代码符号身份注册表，不能据此宣称 provider 替换时实体身份已经稳定。
- 历史来源修订和清单追加式保存；当前 captured 输入有单独 head。重新选用旧清单不依赖时间排序，不改写旧清单。
- MinIO 文件按内容哈希寻址，清单包含全部本次纳入文件的引用。新增 v2 快照同时固定采集 inventory 和报告哈希，旧 v1 快照保留原样，不伪造历史扫描记录。具体保证与剩余范围见“原文采集 inventory”一节。
- 原始快照捕获不执行目标仓库脚本或安装目标依赖。CBM 自有索引仍是可重建缓存，不是 Nasus 业务事实数据库。
- 现有 `SystemImageService` 仍有整批可变上下文/基线投影，不能把本轮来源不可变误报为画像版本治理已完成。新源登记和摄入时，旧上下文不会被展示成新输入已物化。
- 知识对象已增加只读证据检查面板和候选修订选择，沿用现有深浅色视觉 token；这不是多源构建引导、正式批准版本选择或证据审批，后者仍待交付。

## 固定画像代码成员比较（2026-10-08）

新增[固定代码成员比较契约](./code-member-deltas.md)，实现领域完整并集、application 固定双端读取、HTTP/canonical Tool 与重新授权回执。匹配 Nasus 注册身份而非 Provider ID，完整分类/计数/分页，不把来源修订变化解释为业务变化，不推断删除或转移 rename/批准/覆盖。该能力是 P4 基础，不是完整自动增量链。

当前独立终态（选择集有重叠，不累计为全项目测试数量）：

- 领域、回执、Provider 元数据、身份和 DDD 组合 **229 passed / 2.00 秒**（`code-member-delta-contracts-verified-20261008.log`）。首轮命令误写不存在的测试文件，退出 4、未执行测试，保留 `code-member-delta-contracts-20261008.log`；上面的正确选择集已完整执行。
- 实际隔离 PostgreSQL／私有 MinIO 的 HTTP/canonical Tool、持久 Outbox、分页/筛选和权限竞争 **11 passed / 44.00 秒**（`code-member-delta-api-final-20261008.log`）。旧回执在第三次采集和原文件删除后仍绑定原双端，不获取未来画像。初两轮分别 **1 failed / 10 passed / 39.51 秒**和 **1 failed / 10 passed / 39.39 秒**：测试列表误修改原首页、禁正文检查误命中 `tool.invocation.updated` 事件名。修正夹具，未放宽生产分页、完整性或权限限制，原日志保留。
- exweb 固定 `fe5827f6...` 与明确受控修订、实际 CBM 0.8.1／CodeGraph SDK 1.6.2、PG／MinIO **1 passed / 128.94 秒**，runner 退出 0（`exweb-code-member-delta-native-final-20261008.log`）。报告 `exweb-code-member-delta-native-final-20261008.json` 记录 CBM **5 added / 5 removed / 533 revision_changed**，SDK **5 added / 6 removed / 373 revision_changed**，各自完整 hash/方向和旧改名方法移出、新方法加入。来源修订变化会产生新实体修订，不能把这些计数当作修改的方法数量或影响完整性。两侧比较画像为测试中真实 MinIO 归档工件，使用实际 PG 注册实体及证据，但不是公开 `image_revisions` 行；不冒称原生 Provider 与公共物化/HTTP 的联合全链。所有 1459 处实际历史证据的原文/摘要校验仍执行，目标仓库未运行、未安装目标依赖、外部模型调用零。首轮 **1 failed / 17.00 秒**（`exweb-code-member-delta-native-20261008.log`）暴露 fixture 采集修订后未冻结清单，已使用真实 `freeze_manifest` 固定清单后复验，没有补造历史或改换示例。
- Portal 增加默认收起的版本比较入口、显式起点选择、完整计数/分类、固定摘要与 offset 栈。专用读取契约 **47 passed / 303.116ms**（`code-member-delta-ui-contracts-20261008.log`），Portal 全契约 **708 passed / 0 failed / 3812.81ms**（`code-member-delta-ui-all-contracts-20261008.log`）；DDD/Portal/身份边界 **152 passed / 2.41 秒**（`code-member-delta-ui-boundaries-20261008.log`）。选择集不相加。build/i18n 退出 0，lint 首轮控制字符正则违反既有规则后改为逐字符校验，当前退出 0；没有关闭规则。主包 **1032.49 kB** 警告保留，没有提高门槛。

Portal 浏览器首轮 **2 failed / 3 passed**（`code-member-delta-ui-e2e-20261008.log`）：正常场景的 413 夹具没有使用正式 `detail.error` envelope，客户端正确不缩页并停止显示；错画像 hash、分页比较摘要变化和拒绝访问三个分支通过。修正 envelope 后第二轮仍 **2 failed / 3 passed / 1.0 分钟**（`code-member-delta-ui-e2e-verified-20261008.log`）：正常结果已展示，测试将 StrictMode 已取消的首次挂载请求误计入缩页序列。依据浏览器真正的 `net::ERR_ABORTED` 过滤取消项后，独立 PG／MinIO 最终 **5 passed / 1.1 分钟**（`code-member-delta-ui-e2e-final-20261008.log`），完整验证双端 hash、20→10 实际缩页、分页返回、分类、只读、错误后隐藏和关闭清空；没有放宽重试或摘要校验。UI 大小错误/403 为明确传输注入，不冒称真实来源撤权或 exweb 原生运行；真正的读取期间撤权由上面的 API 专项验证。深浅色与 390px 实际截图 `output/playwright/code-member-delta-{theme}[-mobile].png` 已查看，无横向溢出和可见滚动条。原生/HTTP/浏览器证据仍是不同范围，不相互替代。

隔离 PostgreSQL／私有 MinIO smoke **success**、runner 退出 0（`code-member-delta-ui-smoke-20261008.log`），仅是既有关键旅程，不代表完整 V1。最终文案将 revision_changed 明确为实体修订，不必然是来源、方法体或业务变化。完整门禁句柄 73920 本轮再次确认仍 live，原批此前已有失败标记且不包含当前补丁的完整加载；最终当前实现全量门禁继续待验证。

最后文案调整后的当前加载复验：Portal 全契约 **708 passed / 0 failed / 2032.459ms**（`code-member-delta-ui-all-contracts-current-20261008.log`）；相同五项实际 PG／MinIO 浏览器 **5 passed / 1.0 分钟**（`code-member-delta-ui-e2e-current-20261008.log`）。当前 build/lint/i18n 均退出 0（`code-member-delta-ui-{build,lint,i18n}-current-20261008.log`），主包 **1032.51 kB** 警告保留。最终移动端截图已复看，“实体修订变化”的英文标签正确。没有把前面通过批当作后面改动的加载证明；上述选择集仍不代替完整门禁。本轮收尾实际轮询确认 73920 仍运行，日志位于 48%，不因为运行时间或观察超时重开。

尚缺来源事件和自动 delta、全项目派生索引、lineage、overlay/merge、自主调查与全计划费用、完整三源语义质量/五用途/真实运行反馈和 P6 门禁。没有修改 `full_plan_accounting_verified=false`、构建 blocked 状态或 Goal 完成条件。验证不写开发数据库、不启动业务服务；只使用本轮私有临时资源。

## 原目标的三源引用调查与审阅恢复（2026-10-08）

新根调查策略 `nasus.image-investigation-revision.v2` 在代码、已捕获 US 和测试来源并存时，通过 application port 消费固定文档证据，追加 canonical 显式引用候选任务。旧 v1 及其子链仍按原策略回放，原 hash 不变。Proposal 先停在 `reference_candidate_review`；用户继续才核验原调用、调查/Goal/阶段、画像 hash 和当前来源权限，并追加候选及 gap 的全部分页。零项区段也保留查询，不把有界结构/文档采样说成完整语义调查。

原 blocked proposal 的消费、全部新步骤和用户 checkpoint 回执由现有 PG 条件事务一起保存；并发中断/撤权不推进，提交后失联重建 Local/LangGraph PG 可恢复，旧 pin 重试不重提 proposal。每个实际查询和 proposal 计入同一原 Goal 工具账本，原 step ceiling 和预算不因新阶段重置。查看后仍停在完成审阅；没有自动 accept、oracle 批准、冻结、发布、目标执行或 Goal 交付。

当前已核验的独立终态（选择集有重叠，不累计为全项目数量）：

- 领域/application、DDD/Portal 与来源/关联事实边界 **209 passed / 3.39 秒**（`agent-reference-layer-boundaries-20261008.log`）。覆盖新策略、旧 digest、未知/链内策略变化、无可选输入、完整分页、错 Goal/会话/端点/报告、原预算不足及结构授权不能单独释放引用任务。
- 首轮修正后的隔离 PG／私有 MinIO 扩大组合 **61 passed / 1 warning / 384.57 秒**（`agent-reference-continuation-postgres-verified-20261008.log`），覆盖原引用关口、旧 v1 调查父链、Local／LangGraph PG、并发中断、撤权、消费后丢失回执及原累计预算。这一批加载于后续字节分页调整之前，不冒称为该调整的数据库验证。
- Portal 全契约 **623 passed / 0 failed / 1816.18ms**（`agent-reference-portal-contracts-full-20261008.log`）；局部 100 项已包括原 checkpoint 重新 GET、重复点击保护、受阻辅助面板不阻塞权威刷新和引用关口不是高风险确认。build/lint/i18n 已退出 0（`agent-reference-portal-build-20261008.log`、`agent-reference-portal-lint-20261008.log`、`agent-reference-i18n-20261008.log`），既有主包 chunk 警告保留。这不是新增关口的浏览器视觉证明。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、实际 CodeGraph SDK 1.6.2、隔离 PG/私有 MinIO、**真实 Temporal AgentGoal 与结构 Workflow**及 LangGraph PG **1 passed / 1 warning / 253.24 秒**（`codegraph-three-source-agent-references-verified-20261008.log`）。报告 `exweb-codegraph-three-source-agent-references-verified-20261008.json` 核验四个来源涵盖三类、**732 个全部画像成员／764 处归档证据**、五次 graceful Goal Worker 对象重建，以及结构 Activity 1→2 的四次实际 native prepare。原 SDK generation/projection 摘要不变，确认后来源 head 变化及文件删除不替换输入；Goal/结构 history replay 和完成审阅重读零新增 Provider。
- 同一原 Goal 实际调用 canonical proposal，取得 **1 条 `TC-EXWEB-CHAT references US-EXWEB-CHAT` 候选、0 个引用匹配 gap**，然后完整查询 assertions/gaps；13 项原累计工具工作无重复预留。报告明确 `proposed / not_in_image_membership`、`candidate_delivered=false / publication_created=false`。伴随需求与用例是显式 synthetic contract fixtures，**不是业务 gold**；没有外部模型或目标执行。零引用 gap 不消除语义、oracle、结构解析和执行缺口。

真实失败不抹去：新引用领域红测 **3 failed / 10 passed**，application 初版不接受新 port 导致 **1 failed / 19 errors**；Python 3.9 在缺少 future annotations 时另有 **2 collection errors**。修复后最小组合 **52 passed / 1.65 秒**，再有上面的 209 项边界终态。首个引用 PG 组合 **1 failed / 53 passed / 332.71 秒**（`agent-reference-continuation-postgres-20261008.log`），失败为旧测试仍跳过新候选审阅；更新为严格检查原 Goal、独立关口、真实 proposed 候选和全部区段后，取得上面的 61 项扩大复验终态。

后续检查发现固定 50 条的计划不能保证满足 64 KiB 页面上限。新增缩页／连续游标／报告不变／原预算测试的实现前红测 **9 failed / 20 passed / 0.34 秒**（`agent-reference-page-byte-budget-red-20261008.log`）。Application 现在预检完整报告，只有有类型的页面过大错误可缩小条数，单条仍超限拒绝；任何摘要、计数或游标不一致也拒绝，原 Goal 不提前改变。调整后的纯领域／application 和 DDD／Portal／来源关联边界 **218 passed / 2.81 秒**（`agent-reference-page-byte-budget-green-20261008.log`）。这不是实际大报告的 PG／MinIO 或 SDK 证据，后续独立批另记结果，不替代完整 V1 门禁。

新增真实长报告用例使用 51 份归档用例、每份 30 个明确引用字段，全部经原结构 Goal、独立调查和 canonical proposal 派生。优化前首轮 **1 failed / 6 deselected / 645.83 秒**（`agent-reference-real-byte-pages-20261008.log`）：已经验证 51 条 proposed 候选及实际 413，但新断言错误地从顶层读取错误码；现已改为既有 `detail.error` 契约，不修改 HTTP 响应。这批尚未执行后续完整页恢复，不能算通过。日志中的调查／派生 resume 为 **619180.124ms**；运行进程及私有 PG 状态证实命令在实际派生，而非 Temporal 等待。原始采样日志保留，不凭 native Python 栈采样声称已定位每个 Python 函数。

代码检查发现 proposal 每个字段会重新核验画像，未使用既有操作级只读会话。新增会话／失败清理／写入前实时权限测试先取得 **3 failed / 0.11 秒**（`reference-derivation-read-session-red-20261008.log`），派生现在复用一次 verified read session，关闭后才执行 PG record 与 scope 回调。当前纯引用、分页、调查与架构边界 **231 passed / 3.03 秒**（`reference-derivation-read-session-green-20261008.log`）。写入、返回及每次画像／证据查询的当前 ACL 检查不删除，不缓存角色或批准头；不用这组三项 seam 测试冒充权限集成或性能验收。

修正断言并加载会话优化后的真实长报告复验 **1 passed / 6 deselected / 81.06 秒**（`agent-reference-real-byte-pages-verified-20261008.log`）。51 条候选全部保留各自 30 项引用证据；HTTP 的 50 条页仍实际返回 413，原 Goal 缩为 25 条连续读取三页及空 gaps 区段，逐条 ID 与 PG 全记录一致，无重复／遗漏。全部 canonical query 计入原账本，同 checkpoint 重放不增加工作，报告／proposed 状态及原 Goal 不被批准或交付。此次同夹具的调查／派生 resume 为 **37236.893ms**，续接完整查询为 **13143.683ms**；这是两次局部观测，不是并发容量、p95 或完整性能基准。

加载当前缩页和派生会话实现后的 PG／私有 MinIO 兼容、权限、并发恢复及实际 SDK／Temporal 组合 **62 passed / 1 deselected / 1 warning / 620.84 秒**（`agent-reference-byte-pages-postgres-sdk-current-20261008.log`）；已独立通过的长报告用例明确 deselect，不把它再计入组合。新原生报告 `exweb-codegraph-byte-pages-current-20261008.json` 再次核验固定 exweb、完整 SDK runtime pin、732 个成员／764 处归档证据、四个来源涵盖三类、真实 Temporal Goal/结构和 LangGraph PG；canonical proposal 的命令读取使用原 owner actor，而非测试默认管理员。五次 graceful Worker 对象重建、结构 Activity 1→2、四次 native prepare、13 项原工具账本及 history replay 保持既定边界，仍无外部模型、目标运行、自动接受、发布或 Goal 交付。组合仅一个现存 LangGraph serializer 弃用警告，不代表强杀恢复或完整 V1 门禁。

进一步发现 Portal 候选读取固定 20 条、上一页直接减 20 的行为不适用于字节受限报告。接口契约新增红测 **19 failed / 5 passed / 177.01ms**（`reference-page-ui-red-20261008.log`）。领域 API 现只对明确页面超限缩小只读窗口，校验完整行数、固定身份／方法、proposed/observed 及证据；独立候选组件按真实游标回退，等待或错误隐藏旧内容，不发送审阅写入。新读取与组件 seam **29 passed / 242.54ms**（`reference-page-ui-seams-20261008.log`）；全 Portal contracts **652 passed / 2029.18ms**、DDD／Portal 边界 **149 passed / 1.44 秒**，build/lint/i18n 和 diff check 退出 0（`reference-page-current-*`）。既有约 1019.67 kB 主包警告保留。这些不是浏览器或真实超大候选报告的界面证明，CLI 实验单独记结果。

CLI 首轮使用私有 PG／MinIO 和真实静态 exweb、26 份各含 80 个明确引用字段的合成用例，原输入文件在调查前全部删除。原 proposal 与审阅关口已提交，但临时脚本错误匹配 `reference_proposal:` 而非现有 `image_reference_proposal:`，退出 1（`reference-page-cli-fixture-20261008.log`）；私有业务服务、库、bucket 已清理，不算浏览器通过。

修正后的独立 Playwright CLI 实验已正常退出 0（`reference-page-cli-fixture-verified-20261008.log`）。固定同一干净 exweb commit，使用真实 `tree_sitter_static`、Local Goal、隔离 PG 和私有 MinIO；这不是上面 CodeGraph SDK／Temporal 的浏览器证明。沿原 Goal 继续查看 canonical 引用报告后停在 `build_completion_review`，再由原固定回执进入 Knowledge。实际浏览器第一请求 20 条返回 typed 413，缩为 10 条；下一页 16 条、上一页恢复原 10 条。26 个断言 ID 和顺序与 PG 全记录一致，每条保留 80 处主体证据；空 gaps 不展示旧表单。打开一个断言时，历史为零、默认 defer、理由为空且提交禁用；82 个证据选项包含 80 处主体证据、需求证据和占位项，显式选择才展开归档原文。

检查中发现 Portal 只校验摘要格式，没有绑定所选报告摘要与已核验画像 hash。新增实现前红测 **8 failed / 24 passed / 276.67ms**（`reference-page-fixed-pins-red-20261008.log`）；现在 page/history 和 query key 都消费明确选择的原 pin，合法但不同的摘要也拒绝，不能用返回值重新绑定审阅输入。首轮 green 的 **2 failed / 35 passed** 为组件夹具尚未传入新增必需 pin，修正夹具而不弱化生产校验后，读取／导航 **38 passed / 275.51ms**。当前全 Portal contracts **661 passed / 1962.14ms**、DDD／Portal 边界 **149 passed / 1.29 秒**；build/lint/i18n 退出 0，主包 **1020.11 kB** 警告保留（`reference-page-fixed-pins-*`）。隔离 PG／私有 MinIO 标准 smoke 已独立退出 0（`reference-page-fixed-pins-smoke-20261008.log`）；这些不替代完整 V1 门禁。

真实浏览器 protocol fault injection 将下一页响应改为格式合法但不匹配的报告摘要，界面拒绝并隐藏旧候选与审阅表单；这是客户端错配验证，不是实际后端损坏或撤权证明。断网翻页同样隐藏旧内容，显示权限核验等待而不是伪造错误；重连重读固定回执，需重新选择报告。Light／Dark、390px／1440px 已检查，390px 无横向溢出、面板保留滚动且滚动条隐藏。视觉证据为 `output/playwright/reference-page-cli-light-mobile-viewport-20261008.png`、`reference-page-cli-dark-mobile-20261008.png` 和 `reference-page-cli-dark-desktop-20261008.png`。独立前后比对 `reference-page-cli-database-before/after-20261008.json` 核验审阅路线没有写请求、原 Goal 完整摘要及 12 项工具消费不变，决定／发布仍为零。此前 Goal 继续中的写请求不冒称只读。`reference-page-cli-cleanup-20261008.json` 独立核验私有库已删除、18084／14177 端口关闭、测试凭据文件移除；harness 已完成私有 bucket 清理。没有外部模型、exweb 执行、自动接受、冻结、发布或 Goal 交付。

真实 Temporal 早期三源批 **1 failed / 813.43 秒**（`codegraph-three-source-agent-temporal-recovery-20261008.log`）：完成审阅无操作继续等待不存在的状态变化，达到 600 秒超时。Gateway 已在 pin/scope/replay 验证后对该非执行关口直接返回持久 aggregate，不发送 signal；**82 项回归通过**（`temporal-completion-review-noop-green-20261008.log`），并由上面实际 SDK/Temporal 正向链再次验证。第一次接入引用的 native 批 **1 failed / 225.31 秒**（`codegraph-three-source-agent-references-20261008.log`）在 proposal 提交后由测试调用不存在的 workflow-state 读取方法失败；改为既有授权 application port 后才有上述通过证据。

完整 `verify:v1-release` 批 `system-image-sdk-current-v1-release-20261008.log` 的句柄/进程已不在，日志停在 36%，实际有 **5 个失败标记**，没有完整终态，不计通过。前四项旧观察归档故障注入已由后续有序专项验证；第五项生命周期广播单项重跑通过，但尚未证明组合时序问题已解决。最早完整红批仍是 8 failed / 3420 passed / 35 skipped，不能以本切片替代全量门禁。

已确认旧批不再 live 后，启动新的完整原命令 `npm run verify:v1-release`，日志 `system-image-reference-pins-v1-release-20261008.log`。2026-10-08 本次观察句柄 **73920** 和 verifier／隔离 PG runner 进程仍 live，后端进度到 18%，已有 **1 个失败标记**，尚无完整 traceback／终态；不宣称绿色，不因观察超时重启或杀掉原批。门禁开始后未修改业务实现；下面新增的代码变化测试不在它已收集的后端集合中，不借这轮门禁认定新原生测试已通过。

重新核验 exweb 远程 HEAD 仍为原固定 commit，可用历史仍只有初始化与文档更新。为后续代码变化契约增加明确、可重复的[受控变化样本](./codegraph-provider-comparison.md#受控代码变化夹具)，不伪造上游提交。首次纯夹具 collection error 修正后 **7 passed / 0.04 秒**；包含真实固定 Git 对象的完整静态解析及精确方法／路由／调用检查 **8 passed / 2.21 秒**（`exweb-controlled-code-change-real-syntax-report-20261008.log`）。报告 `exweb-controlled-code-change-syntax-20261008.json` 保留完整来源摘要、126／126 文件、180868／178750 字节及精确跨度，原 Git status 不变，无目标／模型执行；静态证据与下面原生执行结果分开，不替代自动 delta、独立 gold 或 P0 完整验收。

之后对一个双原生用例使用 `nice -n 10`、独立 PG 测试库与私有 MinIO bucket 执行，不启动第二批全量／浏览器任务。首次 **1 failed / 26.93 秒**，两次保留断言的诊断复验 **1 failed / 28.65 秒**及 **1 failed / 28.84 秒**（`exweb-controlled-code-change-native-*`）；原生八列证据确认 CBM 已返回新增 `health -> value CALLS / lsp_type_dispatch / candidates=1`，只是 Nasus 旧白名单漏项。上游固定 v0.8.1 Java 类型派发与调用管线已核对，不改样本、不伪造边或将语法边当成 CBM 原生成功。新增测试实现前 **1 failed / 11 passed / 13 deselected / 4.24 秒**；明确准入该策略后，关系契约 **50 passed / 5.73 秒**，依赖指纹／元数据／DDD **191 passed / 2.05 秒**。多候选、缺元数据与未知 `lsp_*` 仍拒绝，原生分数保持未校准。

加载修复后的实际 CBM 0.8.1／CodeGraph SDK 1.6.2、PG／私有 MinIO 复验 **1 passed / 124.28 秒**，runner 退出 0（`exweb-controlled-code-change-native-verified-20261008.log`）。报告 `exweb-controlled-code-change-native-verified-20261008.json` 固定原 exweb 和明确受控修订、两个各 126 文件的完整字节集合及已审查 SDK runtime hash。语法身份集合 **716 个共享键**稳定、实体修订不同，两个 Provider 的改名方法 Nasus ID 一致而新旧 ID 不同；旧删除实体只保留在旧修订，不自动识别 rename。两 Provider 的新增调用、原精确跨度，以及 **1,459 处**双修订 PG 证据的 MinIO 文件／snippet 摘要全部校验；来源 HEAD/status 不变、SDK 缓存为空、runner 的临时库／bucket 清理正常返回。原生观察仍保留未验证解析等具体 gap，不宣称上游真实业务变更、gold、四语言、自动 delta 或 P0-P6 完成。

同次最终观察仍确认全量句柄 **73920** live，后端约 37%，至少 **2 个失败标记**、尚无完整终态。该批在本次策略修复前已收集并装载模块，不能证明新兼容分支或新增原生用例；上面专项单独加载当前实现，最终全量当前实现门禁仍需在原批终态后重新验证。不因观察超时重启或抹掉原批记录。

完整跨进程/强杀 fencing、SDK/CBM 多语言及代码变更/gold/隔离/性能、来源 cutover/lineage、多能力费用与动态反证调查、候选交付及原 Goal 原子完成、语义 authority 与真实模型、自动 delta/overlay/合并、五用途 ContextPack/旧链/脚本/RunPlan/真实运行反馈及 P6 完整门禁仍保留原范围。开发业务服务未启动，开发数据库未迁移/写入；验证仅使用私有临时资源。

## CodeGraph 持久代际与真实 Temporal 重建（2026-10-08）

SDK 现经显式 factory 接到 canonical 结构构建、共享 PG generation 和首次投影／契约 pin，不再仅是一次性对照适配器。`nasus.code-provider-sdk-contract.v1` 是公开 SDK 回执；原 MCP schema/hash 不改写，Portal 以严格判别联合兼容两者。公开入口不接收 runtime 路径或摘要，默认仍为 CBM，详见[Provider 契约](./codegraph-provider-comparison.md#持久-sdk-代际与契约回执)。

当前已确认终态分别记录，选择集重叠，不累加为全项目测试数量：

- 固定完整 exweb、实际私有 SDK、独立 PG／MinIO 的关闭／新实例重建与公开 canonical 构建 **2 passed / 90.73 秒**（`codegraph-durable-sdk-exweb-native-verified-20261008.log`）。新报告 `exweb-codegraph-durable-sdk-verified-20261008.json` 与 `exweb-codegraph-public-sdk-verified-20261008.json` 固定 **126 文件／180868 字节**和同一完整 vendor runtime pin。所有实体／关系按 100 条页完整遍历，与完整投影逐项摘要相等，自有投影为 **526／580**；旧会话游标与旧 worker lease 不可用于重建。状态／私有回放／提交后取消不启动 Provider，无权／非成员 GET 拒绝。
- 真实 Temporal 结构任务更换 Worker 对象后 **1 passed / 140.89 秒**（`codegraph-durable-sdk-temporal-verified-20261008.log`）。`exweb-codegraph-temporal-sdk-verified-20261008.json` 记录 Activity **1、2**，两个来源共 **4 次**成功原生 prepare、原 generation/projection 不变及 epoch 2；原确认后的来源 head 已改变、原输入文件已删除，仍读取原 MinIO manifest。全部 **728 个画像成员／754 处证据**完整回读，归档 SDK envelope 保留原生 **1440 节点／1962 边**。候选／完成审计／Outbox 仅一次，Temporal history replay 和已提交命令恢复零新增 Provider。范围明确为 graceful Worker 对象与 SDK adapter 重建，不是 OS 进程强杀、原生 DB resume、跨主机或 SDK Agent 入口。
- 自然语言 Turn／原 AgentGoal 的实际 SDK 专项 **1 passed / 181.29 秒**（`codegraph-durable-sdk-natural-agent-verified-20261008.log`），报告 `exweb-codegraph-temporal-sdk-agent-verified-20261008-natural-agent.json`。实际聊天 POST 保存原计划，LangGraph PG 恢复同 Goal，结构任务使用真实 Temporal，随后独立确认调查并停在 `build_completion_review`；原累计工具账本为 6 项，结构重试不重复扣减，普通完成审阅重放不改变检查点，也不发布。此项 Goal workflow 仍为 local，不是 Temporal AgentGoal；虽然输入文案提到三类资料，实际来源只有 exweb 与代码夹具，不能据此声称三源构建或语义关联已验证。
- 当前代际／生命周期／结构 API／运行配置与 DDD/Portal 回归 **244 passed / 2 skipped / 424.27 秒**（`codegraph-durable-sdk-regression-current-20261008.log`）；两个原生 opt-in skip 不计作通过。标准 API／运行配置／Compose／DDD／Portal **321 passed / 1 warning / 316.47 秒**（`codegraph-durable-sdk-standard-current-20261008.log`），既有 LangGraph allowed_objects 弃用警告保留。SDK/session/对照脚本纯测试 **64 passed / 0.79 秒**（`codegraph-durable-sdk-pure-verified-20261008.log`）。
- Portal build/lint/i18n/hygiene 均退出 0，contracts **608 passed / 2297.95ms**（`codegraph-durable-sdk-portal-*-verified-20261008.log`、`codegraph-durable-sdk-i18n-verified-20261008.log`、`codegraph-durable-sdk-hygiene-verified-20261008.log`）。原 **1016.82 kB** 主包警告保留，没有提高 chunk 门槛。
- SDK receipt 深浅色和原生命周期浏览器 **6 passed / 45.4 秒**（`codegraph-durable-sdk-browser-20261008.log`），390px 两张实际截图已检查，无横向溢出或可见滚动条。SDK 两场景明确使用 PG 协议状态夹具和空投影，**不是浏览器启动真实 SDK／exweb**。独立 PG／MinIO smoke **success**（`codegraph-durable-sdk-smoke-20261008.log`），不是完整 V1。
- 历史门禁的身份管理、Compose 和 DDD 失败项专项 **146 passed / 2 skipped / 3.45 秒**（`codegraph-sdk-agent-full-gate-redcases-current-20261008.log`）；两个未开启的原生 Temporal skip 不计通过。完整 `verify:v1-release` 批 `system-image-sdk-current-v1-release-20261008.log` 已没有可验证的运行句柄/进程，日志停在 36% 且有 5 个失败标记，无完整终态；具体后续范围见上节，不能用这些选择集替代完整门禁。

失败原样保留：旧扩大批 **5 failed / 239 passed / 2 skipped / 407.58 秒**（`codegraph-durable-sdk-regression-pg-20261008.log`），包括静态指纹函数默认参数捕获旧 ENTRYPOINTS 和验证期间源码变更；已改为调用时解析根清单，不关闭依赖核验。原生首批 **2 failed / 67.27 秒**（`codegraph-durable-sdk-exweb-native-final-20261008.log`）暴露测试把 500 条大对象页误认为应超过既有 256 KiB 上限，以及 Python tuple 与 HTTP JSON list 直接比较；改为完整小页遍历及传输规范化，未放宽上限、完整性或权限。Temporal 首批 **1 failed / 144.81 秒**（`codegraph-durable-sdk-temporal-first-20261008.log`）已完成真实恢复与证据回读，报告 helper 错从 payload 取 `analysis_id`；改用持久 header ID 后上面的最终复验通过。

验证只使用独立临时 PG 和私有 MinIO；开发库不迁移／写入，业务服务未启动。exweb 未执行、目标依赖未安装、外部模型调用为零。SDK 自有投影仍 partial，不以完整分页或重试成功证明业务正确性。完整 SDK Agent 入口、OS 强杀／资源与网络隔离、实际代码变更／四语言 gold、供应链／性能／完整 V1 及 P1-P6 退出条件全部保留。

## CodeGraph 公开 SDK、私有资产与真实修订对照（2026-10-08，早期阶段）

新增[CodeGraph 防腐与对照契约](./codegraph-provider-comparison.md)，SDK 固定 1.6.2、研究 release commit 和已审查的完整运行资产摘要。自有端口异常支持 optional 明确降级／required 拒绝，取消和权限异常继续传播；生产 composition 未改选 SDK。桥接仅调用公开 SDK，完整枚举原生节点／边，保留未知观察、真实调用位置及具体部分投影 gap；未校准概率不伪造。输入来源和运行包均复制到私有会话，资产读／复制／执行后核验，拒绝符号链接、特殊文件、路径冲突、schema 漂移与超限；公开 SDK 加载仍经过原 npm scoped module 布局，不绕过入口或使用安装目录／用户缓存。

各终态证据分别记录，不相加为全项目用例数：

- 布局回归先 **1 failed / 0.60 秒**（`codegraph-sdk-private-layout-red-20261008.log`）；修复后的 SDK／脚本契约 **42 passed / 0.59 秒**，当前 Provider／进程／来源副本／身份／DDD／Portal 扩大纯测试 **431 passed / 56.05 秒**（`codegraph-sdk-private-layout-green-20261008.log`、`codegraph-sdk-private-layout-pure-final-20261008.log`）。这些夹具不代替原生执行。
- 固定干净 exweb `fe5827f6...`、真正私有 bundled Node／SDK、独立 PG／MinIO 的两个项目身份替换和活跃子进程取消 **2 passed / 127.45 秒**（`codegraph-sdk-private-runtime-native-final-20261008.log`）。`exweb-codegraph-sdk-private-runtime-final-20261008.json` 固定 **126 文件／180868 字节**、三次 SDK 投影相等、两个项目 UUID 无交集及 **1464 处证据**全部回读；取消另存 `...-final-cancel-20261008.json`，核验已观察活跃进程、wait／进程组不存在和私有会话清理。不是 Temporal 重启、强杀 GC 或 OS 禁网。
- 两个 Provider 的独立比较脚本同时归档 raw/admitted 投影及完整原生查询。早期两轮退出 1，CBM import 误目标随重复运行变化，已有生产 Java import 准入排除误边；原失败保留。布局修复后的 `exweb-provider-private-runtime-final-comparison-20261008/comparison.json` 两 Provider 各三次 raw/admitted 相等、退出 0，仍不消除早期反例。实际 SDK 图 **1440 节点／1962 边／122 索引文件**；部分自有投影 **526／580**、规范身份 **379**；CBM 自有 **755／1542**、准入关系 **1425**、规范身份 **538**。这些是观察计数，不是质量／覆盖率 gold。
- 真实相邻提交 `cd919569...` → `fe5827f6...` 的原生双 Provider／PG／MinIO **1 passed / 133.43 秒**（`codegraph-sdk-two-revisions-native-final-20261008.log`）。完整 Git 对象归档 **125／167083 字节**和 **126／180868 字节**，**724 个共有规范键**复用实体 UUID但 source/entity revision 分离；**1463 处历史证据**完整回读。SDK 各有一处原生定位修订不同于语法观察，正确另存同 ID 下的修订；旧内容不改写。报告 `exweb-codegraph-sdk-two-revisions-final-20261008.json` 明确每 Provider／修订仅运行一次。这两提交仅改文档，不证明代码变更 lineage、rename/delete 或动态调用。
- 共用 Git tree reader 的既有 source-delta HTTP／canonical Tool／Outbox 原生回归 **1 passed / 1 warning / 6.43 秒**（`codegraph-shared-tree-source-delta-pg-minio-20261008.log`），使用隔离 runner 的私有 bucket。当前身份登记／来源差异／API／DDD／Portal 组 **208 passed / 29.12 秒**（`codegraph-sdk-revisions-registry-delta-pg-minio-20261008.log`），选择集与纯组重叠。
- 较早标准 API／运行配置／Compose／DDD **366 passed / 1 skipped / 1 warning / 560.01 秒**（`codegraph-sdk-standard-pg-minio-20261008.log`），加载于私有布局最后修复前，原生 opt-in 缺失的 skip 不算通过。Portal build/lint 成功，contracts **598 passed / 2259ms**；i18n/hygiene 成功，既有 **1016.00 kB** chunk 警告保留（`codegraph-sdk-portal-*`、`codegraph-sdk-i18n-current-*`、`codegraph-sdk-hygiene-current-*`）。现有分析 UI 的 PG／MinIO 浏览器 **5 passed / 45.0 秒**和 smoke **success**（`codegraph-sdk-analysis-browser-current-20261008.log`、`codegraph-sdk-smoke-current-20261008.log`）；浏览器是 27 文件静态夹具，不冒称原生 SDK／exweb 页面或完整 E2E。
- 两修订专项之后再次执行 Portal build/lint 和 hygiene，均退出 0；contracts **598 passed / 0 failed / 1938.66ms**（`codegraph-sdk-revisions-portal-*-final-20261008.log`、`codegraph-sdk-revisions-hygiene-final-20261008.log`）。主包大小与既有告警不变；未修改 UI／CSS／路由，没有以构建成功替代完整浏览器或 V1 验收。

真实失败保留：私有副本初版丢失 npm module 层级，原生 **1 failed / 1 passed / 19.28 秒**（`codegraph-sdk-private-runtime-native-current-20261008.log`），不能用其取消通过冒充可正常索引。第一两修订测试 **1 failed / 34.36 秒**（`codegraph-sdk-two-revisions-native-20261008.log`）误要求所有 Provider 返回相同完整 RegisteredCodeEntity；修正为固定业务 UUID／来源修订、独立定位修订和全部历史回读，不改生产定位或身份规则。直接 collection 旧 API 测试触发默认 SQLite 的 ARRAY 初始化失败、退出 2（终端输出）；后续 API 验证均经隔离 PG runner，不为了 collection 放宽 PG 类型。更早路径红测及原生重复位置丢失失败同样保留，不被最终通过改写。

业务服务保持停止，验证不迁移／写入开发 PG，MinIO 为私有临时 bucket；exweb 未执行、目标依赖未安装、外部模型调用为 0。该早期批次 SDK 尚未接入 composition／durable generation／Workflow；后续接入与独立终态见上节，不回写早期批次范围。完整代码变更／多语言对照、独立 gold、供应链、账号／网络／资源隔离、强杀 GC 和性能仍未验收。P1-P6 的三源语义、来源 cutover／lineage、全计划预算与动态调查、自动 delta／overlay／合并、五用途／旧链切换、脚本／RunPlan 和真实运行反馈以及最新完整 V1 继续保留原目标范围。

## 构建评估的实时授权传输与生命周期（2026-10-08）

[完成评估契约](./build-completion-assessments.md#实时授权的操作级连接复用)现在将同步评估及 v3 嵌套重放的权限 SQL 放到独立的 PostgreSQL `READ COMMITTED / READ ONLY` 操作级连接。每次检查仍执行完整原 SQL，不缓存项目成员、来源 inventory、ACL 或原文，也不减少逐文件和返回前的检查。专用池 4 个连接、无 overflow、等待最多 5 秒；耗尽拒绝为脱敏 503，业务池仍可用。只复用当前线程／async task 的活跃传输，退出前关闭 scope，复制到延迟、其他线程或兄弟 task 的上下文不得复活旧 Session。没有新增迁移、Tool ID、API 字段或 UI 样式变化。

最终已确认的选择集分别记录，不累加成全项目测试总数：

- 领域/application、连接配置与关闭上下文、DDD／Portal **170 passed / 1.95 秒**（`build-completion-live-access-owner-pure-final-20261008.log`）。复制关闭上下文／兄弟 task 的红测曾 **2 failed / 7 passed / 0.60 秒**（`build-completion-live-access-owner-red-20261008.log`）；修复使用活跃 scope 和执行身份，不仅调用 `Session.close()`。
- 真实隔离 PG／私有 MinIO、完整来源、实时授权、v1/v2/v3 lineage 与 HTTP 回放 **81 passed / 313.68 秒**（`build-completion-live-access-owner-focused-final-20261008.log`）。一条只读连接中的七次权限 SQL 确实观察已提交的项目角色变更、ACL 撤权、epoch 不变的新来源及成员撤销；另外验证只读事务不能写、异线程／延迟上下文新建只读事务、池耗尽后业务读取及报告恢复。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、真实 CBM CLI/MCP、LangGraph PG 与私有 MinIO 的直接调查及原授权结构 Goal **2 passed / 1 warning / 311.27 秒**（`exweb-build-completion-live-access-owner-native-final-20261008.log`）。两份 `exweb-build-completion-live-access-owner-final-20261008[-original-goal].json` 每入口仍核验 **127 文件／180930 字节／754 处成员证据**，各实际 index/MCP 两次，历史重放零新增 Provider／模型调用；原累计工具工作分别 2／4，Goal 及 v2/v3 评估仍 blocked、full_plan_accounting_verified=false。
- 最终标准 API／运行配置、Compose／DDD／Portal **321 passed / 1 warning / 357.72 秒**（`build-completion-live-access-owner-standard-final-20261008.log`）。该选择集与专项重叠，不相加为测试总数；LangGraph serializer 的既有 deprecation 告警保留。
- 最终固定 exweb 深浅色完成评估／责任修订／刷新及丢失回执恢复、夹具丢失完成回应 **3 passed / 5.4 分钟**（`build-completion-live-access-owner-browser-final-20261008.log`）。前两项使用同一实际 exweb 导出的来源及静态适配器，不冒称 CBM 浏览器或真实外部模型；第三项是协议夹具。另存并回读 `exweb-build-completion-live-access-owner-browser-final-20261008-{light,dark}.json`，已检查两个主题的 390px 责任评估截图，无横向溢出。请求仍显式创建，刷新只 GET，原 Goal 不变，blocked 和预算未知提示保留。

上述最终原生测试对每入口的原 v2／固定责任 v3 各做一次旧逐次事务与新传输的完整 GET 对照：

| 入口／报告 | 实时授权 SQL（旧／新） | 业务连接借出（旧／新） | 实际耗时秒（旧／新） |
| --- | --- | --- | --- |
| 直接调查 v2 | 719／719 | 808／91 | 3.957206／2.820423 |
| 直接调查 v3 | 727／727 | 836／111 | 4.098959／2.853862 |
| 原结构 Goal v2 | 717／717 | 806／91 | 3.426538／2.557053 |
| 原结构 Goal v3 | 725／725 | 834／111 | 3.736358／2.542984 |

新方式每项专用连接借出／BEGIN／READ ONLY／ROLLBACK 各一次，零 COMMIT。每对完整 HTTP 报告字节及对象读取 inventory 完全相同：直接入口各 372 次对象 GET／10011561 字节，原 Goal 入口各 371 次／9990697 字节。这是重复归档读取总量，不是来源文件净大小。画像、Goal、Tool 等业务事实写入为 0；既有认证 last-seen 单独计为平台记账，没有关闭认证。样本在本机隔离验证期间取得，未控制完整基准负载、重复分布或 p95；`capacity_or_p95_acceptance=false`，不宣称完整性能门禁通过。

早期测量把 token 的 last-seen UPDATE 误算为业务事实写入，HTTP **1 failed / 1 passed / 10.18 秒**、原生两入口 **2 failed / 1 warning / 304.16 秒**（`build-completion-live-access-http-20261008.log`、`exweb-build-completion-live-access-native-20261008.log`）。仅修正观测分类并保留实际平台写计数；修正后 HTTP **2 passed / 11.62 秒**，原生 **2 passed / 1 warning / 280.63 秒**。这两批早于执行身份加固，不代替上面的最终复验。

执行身份加固前的扩大 API／运行配置／结构授权／固定计划／兼容与边界批 **417 passed / 1 warning / 723.93 秒**（`build-completion-live-access-regression-20261008.log`），九项固定 exweb 审阅浏览器 **9 passed / 7.1 分钟**（`build-completion-live-access-browser-20261008.log`）。它们不被混称为后来执行身份加固的当前源码结果。Portal contracts **598 passed / 0 failed / 1.85 秒**；build/lint/i18n/hygiene 退出 0，主包 **1016.00 kB** chunk 告警保留（`build-completion-live-access-portal-*`；i18n/hygiene 为终端输出）。最终执行身份版本的独立 PG／私有 MinIO smoke **success**（`build-completion-live-access-owner-smoke-final-20261008.log`）。

全部使用临时测试 PG 和私有 MinIO bucket，不迁移／写入开发业务库，不启动四项开发服务，不执行 exweb 或调用外部语义模型。此次改进只是 P6 中当前评估链的安全与开销增量；其余 Provider 隔离／对照／gold、完整全计划费用与动态调查、候选交付／冲突治理、自动增量、五用途／脚本／RunPlan／真实反馈，以及最新完整 V1 和 P0-P6 验收仍未完成。

## 同目标累计工具工作账本（0092，2026-10-08）

新增 DDD 领域预算对象、application 预留 port 与 PG repository，canonical `ToolInvocationRuntime` 在 handler 前调用。新构建目标创建时固定原计划／源意图的 limit、project/conversation/workflow 和摘要；Goal 隐藏 pin 与 `image_build_tool_budgets` 同事务，`image_build_tool_consumptions` 以原 Goal 行锁串行预留，完整校验前驱、命令输入和实际阶段／step／attempt。每项预留、脱敏审计及 Outbox 同事务；重复 command 不再消费，另一 command 不能复用 work identity。0092 为两表和已设置的 pin 添加不可变保护，已有历史时拒绝有损降级；不倒推旧 Goal 的消耗，已标记 Goal 丢账本则拒绝而非重建。

同目标的新补源计划和独立阶段不替换原上限；实际 plan read／authorize 也算工具工作，不只统计 structure/investigate。耗尽或不可验证在 `build_tool_budget_review` 暂停，不执行被拒绝的 handler，保留原工件及已消费记录。结构授权依旧独立，提案 limit 不授予模型出口、业务 authority、发布或执行权。当前顺序允许独立结构 grant 已预留后被工具总上限拒绝，不借此返还或扩大授权。

该增量不完成全计划预算：原生 retry 同 canonical command 是一项 work，但可能有多次 Provider 调用；预 Goal 规划、embedding/rerank、未关联 Goal 的工具及模型费用尚未统一核算。没有新增公开预算接口或 Portal 预算 UI；私有 inspect 仅为验证，不承担用户读取授权。完成报告仍保持 `full_plan_accounting_verified=false`／全预算阻断，其他候选交付条件和 P0-P6 验收范围不缩小。

已取得的终态证据分别记录，不累计为全项目测试总数：

- 首领域 collection 因 Python 3.9 缺少延迟类型注解退出 2；补齐 future annotations 后领域和 canonical runtime ports **15 passed / 0.52 秒**。首 PG／迁移／结构授权／Goal 创建组 **37 passed / 1 warning / 43.99 秒**，覆盖同槽并发、Outbox 失败回滚、追加式约束、旧记录不回填、重放去重和有数据降级保护。这两批为终端输出，未将其伪称另有日志工件。
- 第一轮扩大的 API／补源／调查／边界组 **2 failed / 175 passed / 1 warning / 284.22 秒**（`build-tool-budget-api-20261008.log`）。两个新断言漏算原流程的 plan read，实际初始消费 3 而非 2；改为核验所有实际 canonical acting IDs 和原账本前缀，不改生产计数规则或去掉控制调用。
- 修正后的当前标准 API／运行配置、结构授权、Goal 创建、补源、调查与 Compose／DDD／Portal 扩大组 **421 passed / 1 warning / 687.30 秒**（`build-tool-budget-current-regression-20261008.log`）。后来补充的重复 work identity、显式新 attempt、损坏／丢失账本和迁移保护同当前补源 API、领域/runtime、DDD／Portal 的专项 **201 passed / 1 warning / 183.08 秒**（`build-tool-budget-final-focused-20261008.log`）；两批选择集重叠，不相加为测试总数。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、真实 CBM CLI/MCP、LangGraph PG／私有 MinIO 的两个调查入口 **2 passed / 1 warning / 278.97 秒**（`build-tool-budget-native-exweb-20261008.log`）。`exweb-tool-budget-20261008.json` 的直接调查 Goal 实际 **2 项工具工作**，`exweb-tool-budget-20261008-original-goal.json` 的原结构 Goal 实际 **4 项**，各共用原 80 上限；原 v2/v3 报告及 Goal 仍 blocked，重放不新增调用。此处不使用 Temporal、不执行目标代码、不调用外部模型，需求／用例夹具不冒称业务 gold。
- 同一固定 exweb 的缺代码等待、自然聊天补齐来源、原 Goal 构建及后续补源阶段 **1 passed / 1 warning / 85.63 秒**（`build-tool-budget-waiting-exweb-20261008.log`）。`exweb-tool-budget-phase-20261008-waiting.json` 核验 **8 项工具工作**共用原 source-intent 80 上限，没有因补源、阶段或 LangGraph 重放重置；原目标／旧步骤／独立结构确认保留。它不是所有入口或 Temporal 全分支恢复证明。
- Portal contracts **583 passed / 0 failed / 1.81 秒**（`build-tool-budget-portal-contracts-20261008.log`）；build/lint/i18n 退出 0，主包 **1014.82 kB** 的 chunk 告警保留。三个既有计划／修订／审阅浏览器文件 **19 passed / 4.7 分钟**（`build-tool-budget-browser-20261008.log`）；独立 PG／私有 MinIO smoke **success**（`build-tool-budget-smoke-20261008.log`）。本次没有改变 UI 风格，这些不代表完整 V1 通过。

真实 Temporal 的首批 **3 failed / 2 passed / 1 warning / 289.23 秒**（`build-tool-budget-temporal-20261008.log`）：新测试只统计 completed AgentStep，但 canonical structure 已 completed、步骤仍为等待独立审阅的 blocked，因而漏算一次实际工作。独立 legacy 复现 **1 failed / 2 deselected / 1 warning / 16.76 秒**（`build-tool-budget-temporal-phase-diagnostic-20261008.log`）确认这一断言问题。改为比较全部实际 command ID，并独立核验 PG canonical 状态为 completed，不删减预留或放宽步骤／结构授权。首次批里的直接 Tool／Agent 原生 exweb 重试均通过，Agent 账本保留原 plan read／structure 两项，即使实际有两次 Temporal attempt 和四次 index／MCP；但这不把首批三个失败拼成整批绿色。

修正后的完整真实 Temporal 批 **5 passed / 1 warning / 384.94 秒**（`build-tool-budget-temporal-fixed-20261008.log`），包含 legacy／targeted／shared-entry 三种原 Goal 阶段恢复，注入 phase resume 已消费后的 Activity 失败、替换 Worker、重复旧 signal 和 history replay；原预算与原消费前缀保持，新阶段实际工作继续扣原额度。两个固定 exweb Tool／Agent 入口也重新完整执行真实结构重试，而非拼接首批通过项。

`exweb-tool-budget-temporal-fixed-20261008-{tool,agent}.json` 每个入口固定相同干净 commit、两次 Temporal attempt、最终 epoch 2、四次实际 index 与四次 MCP，canonical 命令／确认／投影不变，重放不调用 Provider。两个入口各核验 **725 个 exweb 代码成员、751 处归档证据跨度**和私有 MinIO；直接 Tool 没有原 Goal，明确记录 `cumulative_tool_work=null` 而非假造全计划账本。Agent 的原上限 80 和 plan read／structure **2 项工作**在 queued、重试完成及历史重放后完全相同，不能将原生四次 index 误记为两次 Provider 调用。目标代码执行、外部模型和 business gold 仍为 false。

旧完整 V1 的八个失败点另外按当前源码复验：先保存真实调查历史，再执行账号／角色与两项注册/隔离用例，以及 Compose／DDD 边界，**162 passed / 72.37 秒**（`build-tool-budget-v1-prior-failures-20261008.log`）。这证明当前测试夹具不再通过删除被追加式历史引用的用户重置环境，不放宽生产 FK 或历史不可变规则；不是重新执行完整 V1。Runner **5 passed / 0 failed / 1.04 秒**（`build-tool-budget-runner-20261008.log`），release hygiene 终端退出 0。

随后固定 exweb 全七入口独立批已终态退出 0：**7 passed / 1 warning / 765.53 秒**（`build-tool-budget-all-native-phases-20261008.log`）。实际回读 `exweb-tool-budget-all-phases-20261008-{legacy,targeted,guided,chat,durable,natural,waiting}.json`：前五入口各 6 项、自然入口 7 项、缺码等待入口 8 项，分别共用原 80 上限；同 Goal、新阶段、原步骤和计划保持，重放 Provider 调用为 0。每个入口核验 725 个代码成员、751 处归档跨度及私有 MinIO，模型调用、目标执行、business gold 均为 false。这一批早于下面手动控制接入，不能当作新计数的证明。

验证仅使用独立临时 PostgreSQL 和私有 MinIO，不迁移或写入开发业务库，不启动开发服务；`npm run dev:status` 当前确认四个业务开发服务 stopped。完整手动控制工具覆盖、多能力/模型费用、动态调查、冲突/候选/Goal 交付事务，以及其余 P0-P6 退出条件仍未完成。

### 同目标手动补源控制接入（2026-10-08）

`system_image.build.plan.revise` 与 `system_image.build.plan.activate_revision` 现在也由原 Goal 的同一累计账本预留，不再因入口是手动按钮而漏计。沿用现有 Tool ID、独立确认、两表及原预算 schema，无新授权或历史回填。运行时只对这两个明确带 goal_id 的控制命令扩展解析；普通查询、源采集及停止／取消不会被任意 goal_id 隐式纳入。当前确认账号、会话、完整原 checkpoint、根计划、当前修订和阶段 head 均在原 Goal 锁下核验后才预留；旧快照或另一目标不能消耗额度。

等待确认不消费，同 canonical command 的响应／Worker 恢复不重复消费；耗尽时不 dispatch 保存修订或激活阶段的 handler，已保存计划、候选、历史授权及旧步骤保留。实际 dispatch 后业务事务失败仍保留这项工具工作，不把工具预留与业务成功混为一谈；预算事务和修订／阶段事实事务仍独立，完整事实交付原子化未完成。

当前已有终态证据按实际选择集分别记录，重叠项不相加为总数：

- 领域／PG 账本、真实 HTTP 限额 2/3/4、补源／阶段 API 及 DDD 首批 **196 passed / 1 warning / 293.49 秒**（`build-tool-budget-manual-controls-focused-20261008.log`）。耗尽前保存/激活 application spy 的调用数分别为 0，原 Goal、修订和历史候选保留；实际手动命令 ID 纳入原账本。
- 后续新增旧快照/错误修订头不消费及激活后已提交预留恢复断言，最新独立专项 **167 passed / 123.07 秒**（`build-tool-budget-manual-controls-final-20261008.log`）。包含 stale checkpoint、根计划、会话、确认账号、过期确认及矛盾 goal alias，不用重新生成当前快照使测试通过。
- 真实 Temporal legacy／targeted／shared-entry 阶段恢复 **3 passed / 1 warning / 155.19 秒**（`build-tool-budget-manual-controls-temporal-20261008.log`）：阶段准备后的消费精确包含补源修订、激活命令和新 plan read；Activity 故障、Worker 替换、重复旧 signal 和 history replay 保留同一原预算／前缀，最终账本逐项核验全部实际 canonical command。
- Portal build/lint/i18n 退出 0，contracts **583 passed / 0 failed / 3.23 秒**（`build-tool-budget-manual-controls-portal-contracts-20261008.log`）。主包 1014.82 kB 的既有 chunk 告警保留；没有样式或生产路由变更。独立 PG／私有 MinIO smoke success（`build-tool-budget-manual-controls-smoke-20261008.log`）。
- 当前手动控制计数后的固定 exweb 七入口 **7 passed / 1 warning / 784.04 秒**（`build-tool-budget-manual-controls-native-phases-20261008.log`）。实际回读 `exweb-manual-controls-phases-20261008-{legacy,targeted,guided,chat,durable,natural,waiting}.json`：前五入口各 **8 项**、自然入口 **9 项**、缺码等待入口 **10 项**，均包含原修订和激活 canonical ID，共用原 80 上限。同 Goal、新阶段、原步骤及原计划保留，重放 Provider 调用为 0；每个入口均核验 725 个代码成员、751 处归档跨度及私有 MinIO。无外部模型、目标执行或 business gold，full_plan_accounting_verified 仍为 false。
- 当前标准 API／运行配置、领域／PG 账本、补源／阶段 API、原目标调查、结构授权及 Compose／DDD／Portal 扩大组 **413 passed / 1 warning / 710.11 秒**（`build-tool-budget-manual-controls-regression-20261008.log`）。它加载于下方 Portal 请求生命周期修复之前，不混称为该修复或完整 V1 的验证。

三文件首批浏览器已终态失败：**1 failed / 18 passed / 5.4 分钟**（`build-tool-budget-manual-controls-browser-20261008.log`）。浅色原 Goal 到知识审阅导航记录到一条不应发生的整幅画像 GET，trace 的 Referer 和时序均位于审阅 URL，不能沿用此前“click 前请求”的解释。失败日志及零整图读取断言保留，后续修复／复验见下节。模型／Provider 调用次数、费用、预 Goal 规划及其余手动能力仍不具全计划核算证明，完成报告的 full_plan_accounting_verified=false 不变；P0-P6 原范围继续有效。

### 审阅导航的请求生命周期修复（2026-10-08）

补 fetch 发起栈诊断后，未改生产逻辑的普通导航重复 **3 passed / 52.3 秒**（`build-review-navigation-initiator-20261008.log`），不据此排除竞态。随后在浏览器 history 已切换、旧 React 观察器未卸载时明确触发 visibilitychange，红测 **1 failed / 8.3 秒**（`build-review-navigation-focus-red-20261008.log`）：原会话 ensure 发出了审阅 URL 下的 POST。该定点测试证明 render-time enabled 门禁有窗口，不将它伪称为首轮整图请求唯一发起栈证明。

路由层现在注入当前项目／非审阅范围的 canReadWorkspace，领域查询在 transport 前及返回前核验，AbortSignal 贯穿整图、release、会话 ensure、解释／记忆／Swarm。SSE 延迟派发及已有读取后的再次刷新都检查范围；只读审阅不触发领域查询失效，但 Conversation 快照与即时 token reducer 保留。没有改变 CSS、图标、生产路径、Tool/SSE 契约或后端权限。普通工作区仍使用原 API，旧响应离开范围后不进入其查询结果。

- 同一焦点竞态的修复后专项 **1 passed / 19.7 秒**（`build-review-navigation-scope-green-20261008.log`），全导航写入及审阅整图／运行详情读取仍严格为 0。
- 新 TS 实际执行专项 **68 passed / 216ms**（`build-review-navigation-scope-final-focused-contracts-20261008.log`）：请求前后／取消／手动 refetch、错误项目／空审阅参数、旧 ensure 禁写、SSE 延迟／二次刷新及普通工作区。首批 **3 failed / 65 passed** 因新增 React useCallback 的 VM mock 接错上下文，修正测试依赖后通过；不放宽任何读取或写入断言。
- 后续把 SSE 生命周期判断留在原事件 hook，避免扩大 Conversation controller；当前完整 Portal contracts **598 passed / 0 failed / 2.22 秒**（`build-review-navigation-scope-current-portal-contracts-20261008.log`），DDD／Portal 边界 **149 passed / 1.64 秒**（`build-review-navigation-scope-final-boundaries-20261008.log`）。初版 lint 的 React Compiler 依赖不匹配及旧边界的 **2 failed / 146 passed** 已保留日志；没有提高 controller 行数上限，边界改为强制 scope predicate 和请求前后检查。
- 三个既有浏览器文件完整回归 **19 passed / 4.9 分钟**（`build-review-navigation-scope-final-browser-20261008.log`），包含 light/dark 焦点竞态、原补源和独立发布／撤权／错误 pin／失联回读。该批运行途中进行了等价 SSE 参数简化，不能冒称为最终稳定源码＋exweb 的单次验收。

最新稳定代码的固定 exweb／隔离 PG／私有 MinIO 三文件批已终态退出 0：**19 passed / 11.7 分钟**（`build-review-navigation-scope-exweb-current-browser-20261008.log`）。其中八个审阅场景使用固定 exweb 导出，计划／修订回归及失联交付回执仍使用各自明确的夹具，不把全部 19 项说成原生 CBM 或真实业务测试。

实际回读并另存 `exweb-build-review-scope-current-20261008-{light,dark,audit}.json`，均固定干净 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`；两个主题各核验 **725 个代码成员**，导航写入、审阅整图／运行详情读取、旧工作区额外整图读取均为 **0**。审计场景的 1 条模型审计／7 条工具记录前后完全相同，不把审计数量解释为真实外部模型调用。两份 `exweb-build-completion-scope-current-20261008-{light,dark}.json` 核验 v2/v3 原评估、独立责任确认及刷新／丢失回执恢复：实际写入分别为评估 1 次、责任准备＋确认 2 次、固定责任评估 1 次，原 Goal 不变、重放模型调用为 0。报告仍 blocked、full_plan_accounting_verified=false，未执行目标代码且不是 business gold。

当前 Portal build/lint/i18n、release hygiene 均退出 0；独立 PG／私有 MinIO smoke 为 **success**（`build-review-navigation-scope-final-portal-{build,lint}-20261008.log`、`build-review-navigation-scope-current-{i18n,hygiene}-20261008.log`、`build-review-navigation-scope-final-smoke-20261008.log`）。主包 **1016.00 kB** 的 chunk 告警保留。此修复不完成全部 Portal 容量／恢复或后端全量 V1，P0-P6 未完成项继续保留。

## 固定已确认责任修订的完成评估（v3，2026-10-08）

新增[固定责任修订评估](./build-completion-assessments.md#固定责任修订的-v3-评估)，沿用原 canonical 查询及私有历史接口，不新增工具、迁移或权限。请求固定原 v2 完成 invocation/report hash、独立确认的责任 revision/hash 和完整原 Goal，application 通过 port 核验原报告、全部来源及历史 canonical 回执。新评估要求所选负责人当前有效，拒绝 v3 作为下一层责任根；旧无 pin 请求和 v1/v2 摘要保持不变。

新报告原样保留来源、实际分析、lineage、工件、readiness、预算、冲突和 Goal，只增加固定责任 pins 和每项真实缺口的负责人，移除 `gap_ownership_unassigned` 合成阻断。全部真实缺口仍 unresolved，其他阻断不得省略，candidate/Goal/publication/execution flags 仍为 false。后来改派、停用成员或改变 Goal 不重写历史 v3；当前来源 ACL 仍实时核验。确认事实不是当前成员可用性保证，更不是交付授权。

Portal 在已确认责任下增加独立评估入口，先回读责任与 Goal，再提交一次固定查询；回应丢失只 GET 恢复原 key/ID，刷新或重新核验不重发。前端验证原命令、完整输入、确切旧修订、回执和整个派生报告，不以重新计算一个成功 hash 放过丢失阻断或伪造 authority。核验中及失败隐藏旧内容，离开审阅清除新导航参数，保留既有细边框、深浅色、中文及无滚动条样式。

已确认的终态证据分批记录，不累计为全项目测试总数：

- 最后领域／application、旧评估兼容、责任规则、Agent 工具上下文、DDD／Portal／Compose 边界 **292 passed / 1.95 秒**（`owned-build-completion-pure-final-20261008.log`）。含原报告不变、完整固定 proof、错误 scope／checkpoint／摘要／旧 schema、责任不能替代交付门禁及 64 KiB 非截断界限。
- 当前标准 API、运行配置、v1/v2/v3 完成评估、责任／构建 lineage、0091 空／有数据迁移及 Compose／DDD／Portal 边界的隔离 PG／私有 MinIO 扩大回归 **387 passed / 1 warning / 757.13 秒**（`owned-build-completion-current-regression-pg-minio-20261008.log`）。覆盖新评估当前成员门禁、改派／停用后的原历史、错误 pins、来源撤权、责任回执损坏、原 v2／Goal 不变及小 ToolResult／SSE 不泄漏；这是选定集合，不是完整 V1。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 CBM CLI/MCP、LangGraph PG、私有 MinIO 双入口 **2 passed / 1 warning / 305.52 秒**（`owned-build-completion-exweb-native-pg-minio-20261008.log`）。两份 `exweb-owned-build-completion-20261008-native[-original-goal].json` 每份核验 **127 文件／180930 字节／754 处成员证据**、两个实际原生代码来源，初始 index/MCP 各 2 次；重放、责任登记及新评估零新增 Provider／模型调用。v3 的 9 项真实缺口全部有负责人且 unresolved，partial 分析、关键冲突和完整预算仍阻断，原 v2／Goal 完全不变。此批不是 Temporal、外部语义模型、业务 gold 或 exweb 应用执行。
- Portal build/lint/i18n 退出 0，contracts **583 passed / 0 failed / 3.13 秒**（`owned-build-completion-portal-contracts-20261008.log`），其中新协议 **21 项**覆盖报告重新哈希后的字段／阻断／权威篡改、撤权、错 Goal、失联 GET-only 恢复、历史改派／停用及无明确 pin 不选 latest。既存主包 **1014.82 kB** chunk 告警保留，没有提高门限。
- 现有构建审阅浏览器的新增 v3 深浅色专项 **2 passed / 5.7 分钟**（`owned-build-completion-exweb-browser-first-20261008.log`）。浅色丢失新评估回应后 GET-only 恢复、深色正常响应；两场景均每条命令只 POST 一次、刷新／重核验零追加写入、模型不新增、原报告和 Goal 不变，并覆盖来源撤权隐藏。已检查两张 390px 责任评估截图，无横向溢出。浏览器使用静态适配器，其 exweb 来源 **126 文件／180868 字节／751 处证据**，不能冒称原生 CBM 或与双来源数量混用。
- 当前同一构建审阅浏览器完整文件 **9 passed / 7.6 分钟**（`owned-build-completion-exweb-browser-full-20261008.log`），包含原调查审阅／独立知识发布、错命令／画像／目标拒绝、权限错误隐藏、中文、原审计不变、v3 深浅色及旧查询失联恢复。使用固定干净 exweb 和静态适配器；不是项目全部 E2E、真实 Temporal 或完整 V1 门禁。最新 390px 截图与 `output/playwright/exweb-build-completion-panel-{light,dark}.json` 保存每场景原报告、确切责任／v3 pins 和一次查询／两次责任写入／一次 v3 查询的证据。
- 独立 PG／私有 MinIO smoke **success**（`owned-build-completion-smoke-pg-minio-20261008.log`），覆盖既有画像 Agent、结构预算／候选及质量闭环入口，不代表候选交付事务或真实目标执行验收。

失败日志保留：新 API 文件第一轮 collection 退出 2 是测试字典括号漏写，未执行测试。修正后专项 **1 failed / 46 passed / 302.64 秒**（`owned-build-completion-syntax-fixed-pg-minio-20261008.log`），唯一失败为测试把授权当前用户可读的原命令输入误当作广播泄漏；断言改为核验小 ToolResult 与实际 SSE，不改变权限或脱敏实现。新前端协议首轮 **1 failed / 20 passed** 是 Node VM 跨 realm 对象原型导致 deepEqual 失败；测试规范化 JSON 后完整 583 项通过，未放宽任何字段核验。

本轮仅将固定责任事实接入新评估，不解决缺口、不完成 Goal。完整全计划多能力费用账本、关键冲突与用途 readiness、候选交付的事实／Goal／审计／Outbox 原子事务、动态反证及完整 P0-P6／V1 门禁仍待交付。验证只使用隔离 PG 数据库和私有 MinIO bucket，开发业务库未迁移或写入，开发服务保持停止。

## 独立构建缺口责任登记（0091，2026-10-08）

新增[独立缺口责任登记](./build-completion-assessments.md#独立缺口责任登记)：`system_image.build.gaps.assign` 固定原完成评估／报告摘要、完整原 Goal 和全部真实缺口，需当前 reviewer 独立确认；追加式 PG 修订、前驱 CAS、成员与确认有效性复查，责任／审计／Outbox 同事务。每次私有读取完整重验原报告、历史、原会话 canonical 命令及准确回执。旧改派回执展开确切历史修订；停用成员显示不可用，不改写原责任。旧 v2 报告和 Goal 不变，所有缺口仍 unresolved，不授予执行或发布权限。

Portal 在原构建完成面板下增加全量责任表单、有效项目成员选择、独立确认及改派历史。准备／确认回应丢失后显式 GET-only 按原 key/ID 恢复，刷新不重复提交或确认。一次观察共用完整已核验历史，正常准备回应不再重复拉取命令和报告；确认后回读已提交修订。浅／深色、中文及 390px 使用现有弹层和细边框，不新增可见滚动条。

当前已确认终态证据分别记录，不累计为项目测试总数：

- 纯领域、Agent 工具上下文、完成评估、完整来源字节及 DDD／Portal／Compose 边界 **285 passed / 2.24 秒**（`build-gap-ownership-pure-final-20261008.log`）。增加第 121 个工具后，目录在 6999 字符预算下不删除工具 ID、权限、确认或必需上下文；仅有界缩短说明／展示标签，明确责任请求仍保留精确工具信息。
- 最后 canonical 历史回执补强前的 PG／私有 MinIO、0091 空／有数据迁移和真实 exweb 组合 **24 passed / 1 warning / 452.63 秒**（`build-gap-ownership-full-pg-native-minio-20261008.log`）。包含并发确认同前驱仅一个提交、完整库存、独立确认、成员失效、Goal 改变、撤权、确认过期／未来、审计／事件回滚、不可变历史和保护性降级。更早扩展专项 **19 passed / 119.72 秒** 不替代该批。
- 上述组合的 exweb 两入口各核验 **127 文件／180930 字节／754 处成员证据**，两个实际代码来源各有原生 CBM CLI/MCP pin；初始索引／握手各 2 次，完成重放与责任登记新增 Provider／模型调用为零。两份 `exweb-build-gap-ownership-20261008-native[-original-goal].json` 保存确切责任回执；全部 9 项真实缺口已分配但未解决，原报告仍 blocked，Goal 仍 `build_completion_review`。最后 canonical 补强后的原生双入口另有 **2 passed / 1 warning / 285.49 秒**（`build-gap-ownership-exweb-native-canonical-pg-minio-20261008.log`），工件为 `exweb-build-gap-ownership-canonical-20261008-native[-original-goal].json`。没有外部语义模型、目标应用执行、独立业务 gold 或真实 Temporal 验收。
- Portal build/lint/i18n 退出 0；contracts **562 passed / 0 failed / 1.87 秒**（`build-gap-ownership-portal-contracts-final-20261008.log`），其中责任协议 **29 项**，含一次观察只读一个完整历史、正常确认前后各一个历史读取、原回应损坏及无重复 POST。既存主包 **1004.71 kB** 告警保留，没有提高大小门限。
- 固定干净 exweb 的浅／深色责任浏览器专项 **2 passed / 3.9 分钟**（`build-gap-ownership-exweb-browser-shared-observation-20261008.log`）。浅色丢失准备回应、深色丢失确认回应，均 GET-only 恢复原 ID；准备时零责任历史，确认后仅一条，刷新不增加写入、模型或改变原报告／Goal。已查看两张 390px 最新责任截图，长缺口 ID 换行、不横向溢出。浏览器使用静态适配器，126 个 exweb 文件／180868 字节／751 处成员证据，不能与上述两来源原生数量混用。
- 当前 PG／私有 MinIO smoke **success**（`build-gap-ownership-smoke-pg-minio-20261008.log`），验证原系统画像 Agent 入口、独立结构预算、候选和质量闭环入口；不是新增完成交付或真实测试运行验收。

canonical 历史补强的最后 API／0091 迁移专项 **24 passed / 177.30 秒**（`build-gap-ownership-canonical-final-pg-minio-20261008.log`）。扩大批 **1 failed / 150 passed / 440.40 秒** 保留：既有会话复用夹具复用了已存在的 knowledge scope，没有产生原断言要求的新事件；测试改为另一真实 scope，针对性复验通过，没有改动会话幂等实现。最后现有构建审阅浏览器完整文件 **9 passed / 7.0 分钟**（`build-gap-ownership-exweb-browser-full-current-20261008.log`），不以专项或夹具复验拼成扩大批全绿，也不代替最新完整 V1。

失败日志保留：最初 Agent catalog **1 failed / 73 passed** 暴露第 121 个工具在 6999 字符限制下的说明下限溢出，已保留治理字段并压缩展示文字。首两批浏览器各 **2 failed**，第一批错误使用夹具 `owner.id`（实际 `userId`），第二批暴露重复私有核验及尚未等实际 POST 结束就断言界面；修复复用一次观察并等待原请求结束，未提高断言或总测试超时。最后历史回执补强首批 **3 failed / 21 passed / 163.11 秒** 是测试误期待完整性失败为 409（现有契约为 502）及会话夹具缺少必填 `space_type/space_id`；修正预期后仍要求准确错误 code 且无私有 gaps，不放宽实现。

0091 仅完成责任分配和历史，不实现缺口解决；随后消费固定责任修订的 v3 评估见独立章节。完整全计划预算／关键冲突、candidate-only 交付及原 Goal 完成事务、其他 P0-P6 门禁继续保留。验证使用隔离 PG／私有 MinIO，开发数据库未迁移或写入，正常开发业务服务未启动。

## 实际结构构建来源回执（2026-10-08）

0090 新增[实际构建 lineage](./build-completion-assessments.md#实际结构构建回执)：每个 captured 代码来源实际返回的分析、完整观察归档和合并投影，与真正参与合并的原生 generation/projection/MCP 协议 pin 一起固定到结构提交。候选、结构工件、回执和完成 Outbox 共用 PG 事务；可选原生失败后的尝试单独保存，不当作已消费输出。瞬时 execution pin 不改变已有规范投影/观察摘要。

新评估使用 `analysis_policy=committed_build` 返回 v2，从原 plan/image 的实际提交发现完整分析集合；同来源另一份有效报告不能替代。缺少回执、marker 不一致、scope/hash/原生 pin 或完整私有观察损坏拒绝整份读取，不选择最新记录、不修复历史、不重新索引。0090 不补造旧工件回执，已存在新 marker/回执时禁止降级。旧请求保留 v1 诊断语义和 request hash。

当前已确认的终态证据分批记录，不累计为项目测试总数：

- 纯逻辑、观察归档和 DDD/代码身份边界 **237 passed / 5.39 秒**（`build-lineage-pure-final-fixed-20261008.log`）。新 receipt 不改变旧投影和观察摘要，完整 envelope、未知字段、控制字符、重复来源及 native/unused 形状均有拒绝用例。
- marker 一致性补强前的 PG/私有 MinIO 组 **46 passed / 165.42 秒**（`build-lineage-expanded-validated-pg-minio-20261008.log`），含来源替换、缺失/损坏、私有归档完整读取、读取中撤权、原子候选/回执/Outbox 回滚、旧 schema 不回填及保护性降级。原生已消费与可选失败未消费的受控协议场景另有 **2 passed / 15 deselected / 26.20 秒**（`build-lineage-native-fallback-pg-minio-20261008.log`），重放不启动 Provider；它们不是外部 CBM 的真实代码语义验收。
- 同版固定 exweb 两个真实 CLI/MCP、LangGraph PG、MinIO 入口 **2 passed / 1 warning / 128.91 秒**（`exweb-build-lineage-final-pg-minio-20261008.log`）。`exweb-build-lineage-final-20261008[-original-goal].json` 每个入口核验 **127 文件／180930 字节／754 处成员证据**；实际两代码来源的原生 pin 与 PG 记录一致，索引/MCP 各 2 次，重放零新增 Provider/模型调用。仅消除实际构建 lineage 阻断，`code_analysis_partial`、关键冲突、累计预算和缺口负责人继续阻断；不是 Temporal、外部语义模型、独立业务 gold 或目标执行。
- Portal build/lint/i18n 退出 0，contracts **488 passed / 0 failed / 1.64 秒**（`build-lineage-portal-*`），既存 **972.53 kB** 主包告警保留。固定 exweb 的审阅 UI **6 passed / 2.2 分钟**（`build-lineage-review-browser-pg-minio-20261008.log`），覆盖深浅色/390px/中文/错目标和独立发布；PG/私有 MinIO smoke **success**（`build-lineage-smoke-pg-minio-20261008.log`）。这批浏览器使用静态适配器，源码加载于后续 marker 一致性补强前，不冒充 CBM 或新增完成评估面板。

marker 一致性补强后的 PG/私有 MinIO 组终态 **49 passed / 194.78 秒**（`build-lineage-expanded-marker-fixed-pg-minio-20261008.log`），包含两个原生消费／失败降级场景和“旧 marker 下出现新回执”的拒绝读取。对应真实 exweb 双入口终态 **2 passed / 1 warning / 117.71 秒**（`exweb-build-lineage-marker-fixed-pg-minio-20261008.log`），两份 `exweb-build-lineage-marker-fixed-20261008[-original-goal].json` 继续完整核验原 127 文件、180930 来源字节、754 处成员证据和实际两个原生 pin；仍保留 partial／冲突／费用／负责人的四项阻断，不新增 Provider 或外部模型重放。

扩大回归 **457 passed / 1 skipped / 1 warning / 1067.04 秒**（`build-lineage-current-regression-pg-minio-20261008.log`），进程与原监督 handle 已核验退出 0。该批在最后 marker 检查和三个专项用例之前加载，因此是当版扩大证据，不代替上述最新 49 项；不是最新完整 V1 或 P0-P6 验收。

失败日志真实保留：第一 pure 批 **2 failed / 215 passed** 是新增测试误期待 ValueError，实际 digest 校验抛出严格的 ImageRevisionIntegrityError；随后 **1 failed / 236 passed** 暴露 nested identity 的异常未统一为 schema 完整性错误，已修正错误映射且不放宽校验。第一扩大 PG 批 **5 failed / 36 passed** 因旧手工迁移夹具未加载 0090；补齐夹具迁移后上述 46 项通过。错误文件名和早期 Python 3.9 类型启动失败的日志保留，不计作通过。

完整 candidate-only 交付与 Goal 原子完成、全计划多能力预算/动态反证/缺口治理、完整来源 cutover/lineage/多格式、自动 delta/overlay/合并、五用途/旧链/脚本/RunPlan/真实执行以及 Provider 对照/gold/隔离/性能和最终 V1/P6 均保留原范围。正常开发库未迁移，业务服务未启动，验证使用独立 PG 数据库与私有 MinIO bucket。

## 构建完成条件评估与审阅等待修复（2026-10-08）

新增[固定来源完成条件评估](./build-completion-assessments.md)，通过 canonical `query.system_image.build_completion.read` 和私有历史展开接口读取。报告固定原调查、计划、画像、完整已结算 Goal 检查点及显式分析摘要；所有 captured 来源的原始文件字节、文件/聚合 hash、完整画像成员证据和分析文件清单重新核验。普通 source-delta 的清单读取保证不被提升，SSE 广播和 ToolResult 不携带报告正文或私有对象引用。当前报告仍为 blocked，实际构建 lineage、多能力累计预算、关键冲突、负责人、完整 Goal 原子交付及 Portal 引导待交付。

首轮真实 exweb 两入口终态 **2 failed / 1 warning / 93.83 秒**（`exweb-build-completion-assessment-pg-minio-20261008.log`）。重复恢复完成审阅错误地执行 start/decide，让已结算 `active_runtime_ms` 增加 28ms，原检查点随之失效；直接调查的完成查询也因同一无效恢复失去固定检查点。修复在校验用户检查点后直接保留等待状态，不提高预算、不忽略计时字段、不放宽重复恢复的完整相等断言。

本轮已确认终态证据分别记录，不累加为全项目测试数量：

- 领域/application、完整原文、manifest、差异、Agent 图与运行计时组 **119 passed / 1.97 秒**（`build-completion-body-pure-final-20261008.log`）。另有完整来源 5000 文件／100 MiB 的准确边界及超限拒绝 **4 passed / 0.27 秒**，测试预算分支在读取正文前拒绝，没有分配大原文或截断返回。完成审阅 Local 八变体三次重复恢复均保持完整 Goal、零写入/事件/调用；错误计时检查点仍拒绝。
- 固定干净 exweb、真实 CBM CLI/MCP、LangGraph PG 与私有 MinIO 的直接调查和原授权结构 Goal 两入口 **2 passed / 1 warning / 109.12 秒**（`exweb-build-completion-body-fixed-pg-minio-20261008.log`）。两份 `exweb-build-completion-body-fixed-20261008[-original-goal].json` 每个入口核验 **127 个原文件／180930 字节／754 处成员证据**，其中 exweb 126 个、既存代码夹具 1 个。初始索引/MCP 各 2 次，重放新增 Provider 和模型调用为零；完整字节缺口消除，原调查仍只有 8 条样本，分析仍 partial，预算、冲突、负责人和构建 lineage 仍为明确阻断。这里不是 Temporal、真实语义模型、业务 gold 或目标应用运行。
- Portal build/lint 退出 0；contracts **488 passed / 0 failed / 2.06 秒**（`build-completion-body-portal-*`）。既存 **972.53 kB** chunk 告警保留，没有前端样式或结构改动。
- 实际固定 exweb 的浏览器审阅/发布入口回归 **6 passed / 2.1 分钟**（`build-completion-body-review-browser-pg-minio-20261008.log`）：深浅色、390px、中文、私有报告/目标错配、重放无新增模型和工具写入，仍独立确认发布。light-mobile 与 dark 截图已检查。这验证现有审阅 UI，不冒充尚未增加的完成评估 Portal 面板，也不冒充原生 CBM 浏览器入口。
- 独立 PG/私有 MinIO smoke **success**（`build-completion-body-smoke-pg-minio-20261008.log`）。该版较大范围 API/运行配置/Compose/DDD/身份及调查/差异/恢复组已终态退出 0：**358 passed / 1 warning / 554.71 秒**（`build-completion-body-fixed-regression-pg-minio-20261008.log`）。这批加载于 0090 实际构建回执之前，不代替后续版本的复验。

早期 API 批的 **1 failed / 163 passed / 141.30 秒**（`build-completion-assessment-pg-minio-fixed-20261008.log`）保留：测试误把正常 Goal 推理中的普通单词 `original` 当成源码泄漏。改为检查实际源码片段、路径、存储 URL 与报告 JSON 字段，未改变脱敏实现；原完成回执/历史 API 组 **10 passed / 46.63 秒**（`build-completion-assessment-api-current-20261008.log`）。本轮随后新增字节损坏/失联、读取中撤权及分析完整性失败分类，较大批验证新实现。错误测试文件名退出 4、未执行测试的旧日志同样保留，不作为通过证据。

验证仅使用独立临时 PG 数据库和私有 MinIO bucket，开发库不迁移或写入、开发服务未启动、exweb 未执行；没有外部语义模型调用。完整 P0-P6 与最新完整 V1 门禁仍未完成，不能把只读 blocked 报告作为候选交付或缩小全目标。

## 来源清单根与原生身份准入（2026-10-08）

[来源清单根](./manifest-rooted-projections.md)将确切 SourceManifest 传入新冻结抽取和 baseline 初始化，不再创建没有实体修订的 Project Core 或补出它的显示关系。画像已有 0070 对象来源 DAG 的根恰好依赖 manifest 和全部真实 member。领域校验要求至少一个来源固定的代码对象，允许合法零边画像；关系端点、project/baseline、指标和证据必须一致。旧工件和 legacy 直接抽取的哈希、内容、引用及历史显示保持兼容，不把兼容 ready 提升为正式 publication。

真实原生复验曾在初始结构准备失败，异常为 `ImageRevisionIntegrityError: Frozen objects require unique source-pinned identities.`，不是服务未启动或传输超时。Provider 返回的未唯一对齐节点正确地没有被注册，但抽取器把它们也作为冻结对象输出。修复保留分析 inventory 记录和计数式 unresolved/ambiguous 缺口，仅让已注册实体与封闭关系进入新成员；缺少注册端口或需要排除观察却没有分析持久回执时拒绝准备。不伪造身份，也不将 partial 结果标为完整。这里保存的是分析记录及投影元数据，不声称永久归档了全部原始 Provider 节点正文。

当前独立终态证据分别记录，不累加为全项目测试总数：

- 原生身份准入红测 **6 failed / 31 passed / 0.58 秒**（`frozen-provider-admission-red-20261008.log`）。其中一个断言漏写夹具的合法 Provider evidence，补全预期而不是删除证据；其余失败覆盖无注册端口/无 inventory 和 unresolved、ambiguous、重复身份缺口。修复后的抽取、Provider、符号/结构身份、冻结规则及 DDD/Portal 边界组 **271 passed / 5.41 秒**（`frozen-provider-admission-pure-final-20261008.log`），另含空/缺失 inventory 回执、缺口计数幂等、其他缺口保留与精确身份不虚构 gap。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、真实 CBM CLI/MCP、LangGraph PG 与私有 MinIO 的自然聊天及原 Goal 补源 **1 passed / 6 deselected / 1 warning / 292.95 秒**（`exweb-manifest-root-native-fixed-pg-minio-20261008.log`）。`exweb-manifest-root-native-fixed-20261008-natural.json` 核验最终 **732 个全部来源固定成员、4 个 captured sources、0 个 legacy members、2212 个持久 provenance nodes**；其中固定 exweb **725 个规范代码成员、751 处归档证据跨度**全部回读。原生观察仍为 **755 entities / 1425 relationships**，持久分析报告保留 **217 个 unresolved_symbol_identity** 并标 partial。该数量属于原生 Provider，不与语法适配器合并后的成员数量直接相减。
- 同一原生场景初始/补源各 **2 index / 2 MCP**，四份执行副本核验并清理；原 Goal/根计划/旧步骤不变，历史重放新增 Provider 调用 **0**、模型调用 **0**。MinIO 独立回读 **134 次 / 2,340,647 字节**，包含 4 manifests、129 source files 和 1 frozen image。这里是 Local 生命周期与 LangGraph PG，不声称该场景使用 Temporal、目标应用执行、真实语义模型或业务 gold；需求和用例仍为显式夹具。
- 标准 API、运行配置、Compose 和 DDD 门禁 **297 passed / 1 warning / 299.59 秒**（`system-image-manifest-root-standard-api-fixed-pg-minio-20261008.log`）。此前标准批 **2 failed / 295 passed / 312.13 秒** 保留：旧测试要求虚构 Core 的 impacts/implements 边。新断言核验真实四种关系、端点封闭及不存在虚构 System/无关需求实现，没有恢复假边或放宽权限。
- 当前冻结根、抽取、分析 repository/HTTP、结构构建和画像修订组 **46 passed / 99.30 秒**（`frozen-provider-admission-api-pg-minio-20261008.log`）。四个根场景重新核验真实成员及持久 DAG、合法单对象零边、旧工件完整 header/ref/读取不变、独立确认式初始化且没有 publication head；不以单项通过代替整个批次。
- Portal contracts **481 passed / 0 failed / 1.69 秒**；build/lint/i18n 退出 0（`frozen-provider-admission-portal-*`），主包 **969.28 kB** 的 chunk 告警保留。独立 PG/私有 MinIO smoke **success**（`frozen-provider-admission-smoke-pg-minio-20261008.log`）。这些不是完整 E2E 或 V1 门禁。
- 随后冻结身份准入的当前源码浏览器专项 **11 passed / 8.6 分钟**（`frozen-provider-admission-browser-pg-minio-20261008.log`），覆盖构建审阅六场景、固定 exweb 分析、深浅色发布和需求/测试原文两场景。使用 Tree-sitter 静态适配器，不冒称原生 CBM、外部真实模型或完整 V1。
- 同批真实 Temporal/原生 exweb 终态 **3 failed / 2 passed / 1 warning / 541.19 秒**（`exweb-manifest-root-temporal-pg-minio-20261008.log`）：tool 重试达到原 180 秒观察时限；agent 重试在原预算内返回 failed；native-session 未在原 30 秒内进入；排队停止和已提交候选竞争通过。agent 日志只记录注入的 `OSError`，不能以该名称断言后续失败原因。后续修复/复验见下节，不把这一批改写为绿色。

早期根改动的独立 HTTP 四场景 **4 passed / 15.17 秒**、边界 **193 passed / 1.61 秒**、静态 exweb 浏览器 **11 passed / 8.6 分钟**仅证明各自加载的源码和范围，不能代替上面后来新增的原生身份准入复验。原生根改动的三份失败日志 `exweb-manifest-root-natural-phase-pg-minio-20261008.log`、`exweb-manifest-root-natural-phase-diagnostic-pg-minio-20261008.log`、`exweb-manifest-root-native-exception-pg-minio-20261008.log` 均保留，不改写为绿色。

完整 candidate-only 完成报告及 Goal 交付事务、动态调查/反证与累计预算、原始观察工件及完整多格式/lineage/cutover、自动 delta/overlay/合并、五用途/脚本/RunPlan/真实执行反馈、Provider 对照/隔离/gold/性能和最终 V1/P6 继续保持原验收范围。开发业务库没有在验证中迁移或写入，测试数据库和私有 bucket 为独立临时资源。

## 完整收到投影与原生查询观察归档（2026-10-08）

[观察归档契约](./code-observation-archives.md)将身份准入前的完整 received 投影、unresolved/ambiguous 身份和解析声明保存到私有 MinIO，原追加式 PG 分析表新增 v3 envelope，不增加迁移或改写旧报告。公开实体/关系分页有完整工件核验、当前来源 ACL、筛选及无私有引用的响应；Portal 增加两页签，matched 不表示已准入，关系分数未校准且不代表业务覆盖。v1/v2 旧报告保留能力状态，不伪造观察正文。

第一批 received 投影归档的终态证据分别记录，不累计为全项目测试总数：

- 解析/归档/分层组 **220 passed / 2.60 秒**（`code-observation-archive-pure-20261008.log`）；实际 PG/私有 MinIO 的分析、Evidence、结构构建及 generation 组 **50 passed / 90.26 秒**（`code-observation-archive-api-pg-minio-20261008.log`）。包含旧报告不回填、实体/关系筛选、来源更新/删除后的历史读取、损坏拒绝、读取中撤权及拒绝后零归档读取。
- 固定干净 exweb、真实 CBM CLI/MCP、Temporal Tool/Agent 的原命令重试与回放 **2 passed / 1 warning / 248.15 秒**（`exweb-observation-archive-temporal-pg-minio-20261008.log`）。两份 `exweb-observation-archive-temporal-20261008-{tool,agent}.json` 独立核验 **942 收到实体 / 2346 规范关系 / 725 exact / 217 unresolved**，正式代码成员 **725**、原文跨度 **751**，各自 epoch 1/2、4 次 index 与 4 次 MCP，历史 Provider 及模型调用零新增。
- Portal contracts **488 passed / 0 failed / 1.43 秒**；build/lint/i18n 退出 0，主包 **972.53 kB** chunk 告警保留。此前 `verify:portal-i18n` 命令不存在、退出 1，改用实际 `test:i18n` 退出 0（`code-observation-archive-portal-i18n-fixed-20261008.log`），不把错误命令称作产品测试失败或绿灯。
- 深浅色/390px 浏览器、历史报告、权限及损坏专项 **5 passed / 44.4 秒**（`code-observation-archive-browser-pg-minio-20261008.log`）；移动实体页截图已检查，独立 PG/私有 MinIO smoke **success**（`code-observation-archive-smoke-pg-minio-20261008.log`）。浏览器使用静态适配器，不冒称 CBM 或外部语义模型。

随后补齐原生转换前的解码查询响应：`nasus.code-observation-archive.v2` 在相同 result 之外保存不可变 query envelope，保留未知类型、端点、原生属性和被拆分父分区的 LIMIT 探针。16 MiB/4096 查询及 32 MiB 全工件边界拒绝超限；重复 JSON key、NaN、非对象和错误 Provider pin 均拒绝。供应商格式只在基础设施解释，application/domain 作为不透明观察留存。完整字节 wire/stdout/stderr、未请求属性及原生全库导出不在此保证范围。

规范 generation 的九字段投影摘要显式排除查询 envelope，原临时项目名或探针响应顺序变化不会造成假冲突；实体、关系、证据与声明仍全部比较。新 CodeIntelligenceResult 的事实相等判断同样排除这些私有观察。不同原生响应产生不同的追加式分析工件，不覆盖原记录，正式冻结成员和引用契约不变。

当前原生查询归档源码已核验的终态：

- 首新增测试 collection 因尚无实现退出 2；第一轮 **8 failed / 76 passed / 4.80 秒** 是测试把 CBM transcript 挂到 Tree-sitter 声明后，被真实 Provider pin 校验拒绝。修正夹具 Provider，不放宽校验，纯组 **237 passed / 6.13 秒**；扩大的最终解析/Provider/归档/DDD/Portal 组 **287 passed / 5.98 秒**（`code-native-query-archive-pure-final-20261008.log`）。
- 当前 PG/私有 MinIO 的分析、规范 generation、跨进程恢复、结构任务及取消专项 **100 passed / 421.28 秒**（`code-native-query-archive-api-pg-minio-fixed-20261008.log`）。首命令误写两个测试文件名，exit 4、未执行任何测试（同前缀非 fixed 日志），不把迁移成功当作测试通过。新公开读取测试确认原生请求/正文不出现在任何 section，原报告 v1/v2/v3 共存且不回填。
- 固定 exweb 两个真实 Temporal 入口 **2 passed / 1 warning / 227.20 秒**（`exweb-native-query-archive-temporal-pg-minio-20261008.log`）。`exweb-native-query-archive-temporal-20261008-{tool,agent}.json` 每个入口保留故障前后两份完整观察报告，每份 **25 次原生查询（3 search / 22 query）**，包含 **10 种原生关系类型**，含未规范映射的 INHERITS/WRITES。原始计数包含父分区探针，不是去重图边数；个别探针结果变化真实保留，而每个 generation 规范投影重试保持一致。正式成员、原文及 DAG 继续逐项回读；各入口原 180 秒观察预算未提高，原 canonical invocation/确认不变，重放不重新调用 Provider，Agent 仍保留构建审阅 gate。
- Portal contracts **488 passed / 0 failed / 1.81 秒**；build/lint/i18n 退出 0（`code-native-query-archive-portal-*`），主包 **972.53 kB** 告警保留。该版本的独立浏览器 **5 passed / 43.3 秒**、PG/私有 MinIO smoke **success**（`code-native-query-archive-{browser,smoke}-pg-minio-20261008.log`），标准 API/运行配置/Compose/DDD **297 passed / 1 warning / 323.80 秒**（`code-native-query-archive-standard-api-pg-minio-20261008.log`）。这些结果属于下述严格首次解码修复之前的源码，不代替修复后的复验。

随后复核发现首次 CLI JSON 解码会覆盖重复字段，归档阶段无法再发现原响应的歧义；另一个分支把“有声明但全部 unavailable”误当成“历史无声明”，允许借顶层 Provider 接纳原生观察。确定性红测 **9 failed / 1 passed / 12 deselected / 0.57 秒**（`code-native-query-decode-red-20261008.log`）复现两处生产缺陷。CLI 外层和 MCP text 内层改用严格解码，拒绝 duplicate key、NaN/Infinity、1e999 溢出和非对象；Provider 兼容只用于没有声明的历史投影。没有放宽归档、身份、权限或 generation 摘要规则。

修复后的归档专项 **32 passed / 1.76 秒**（`code-native-query-decode-fixed-20261008.log`），另含合法 Unicode 的直接/包裹响应、无效/错误 envelope 和无声明历史兼容。扩大 PG/私有 MinIO/真实 Temporal 组终态 **1 failed / 899 passed / 1 warning / 1369.84 秒**（`code-native-query-decode-fixed-full-pg-minio-temporal-20261008.log`）；唯一失败为下述已在该批加载之后修正的旧夹具，不把 899 项通过改写为整批绿色。

扩大选择集另发现旧的实时检查转发测试把 legacy 展示对象交给冻结准备，因缺少来源身份被现行准入规则拒绝。独立复现 **1 failed / 0.52 秒**（`code-control-preparation-current-red-20261008.log`）。测试改用已有真实抽取逻辑的来源固定协议夹具，保留三次 check 与 callback 身份断言，另验证无登记对象在 freeze 前被拒绝；没有修改生产冻结规则或伪造 Core 关系。当前执行控制、冻结抽取、准入及归档组合 **91 passed / 3.93 秒**（`code-control-preparation-current-fixed-20261008.log`）。扩大批已在修改前加载旧测试，不把此复验拼接成该批全部绿色。

该扩大批实际完成当前首次解码修复后的 exweb 原生重建、两个真实 Temporal 重试及三种停止：`exweb-native-query-decode-fixed-index-20261008.json` 的同一 generation/原生投影重启一致、epoch 1/2、两次索引/MCP、旧游标拒绝；CLI 0.8.1 与 MCP server 0.10.0 的不一致仍作为明确 gap，不宣称原生协议或运行完整。`exweb-native-query-decode-fixed-temporal-20261008-{tool,agent,stop-queued,stop-native-session,stop-candidate-committed}.json` 已逐份核验，两个重试各保留故障前后两份 25-query 工件、942/2346 received 投影、725 canonical 代码成员和 751 处真实证据。Agent 等待真实任务并保留审阅 gate；排队/活跃会话停止为 cancelled，提交后竞争为 already_committed，原候选保留。历史重放不再调用 Provider；这是协作停止，不是 OS 强杀或孤立对象清扫验收。

首次解码修复后的 Portal contracts **488 passed / 0 failed / 1.55 秒**、Portal boundaries **23 passed / 0.12 秒**，build/lint/i18n 退出 0（`code-native-query-decode-fixed-portal-*`）；主包 **972.53 kB** 告警保留。独立浏览器 **5 passed / 44.6 秒**（`code-native-query-decode-fixed-browser-pg-minio-20261008.log`），已检查本批更新的 390px 深浅色实体页截图；独立 PG/私有 MinIO smoke **success**（`code-native-query-decode-fixed-smoke-pg-minio-20261008.log`）。浏览器使用 Tree-sitter，不冒充原生 CBM/Temporal 或真实语义判断。

旧夹具修正后的执行控制、归档、HTTP/冻结规则、标准 API/运行配置/Compose/DDD/代码身份组合终态 **407 passed / 1 warning / 373.98 秒**（`code-native-query-decode-fixed-current-regression-pg-minio-20261008.log`）。没有将专项结果拼成最新全量 V1，完整候选交付和 Goal 交付事务仍未实现；后续只读完成条件评估见本记录相应章节。

验证只使用独立临时 PostgreSQL 数据库和私有 MinIO bucket，未迁移/写入开发业务库、未启动开发服务或执行 exweb，也未调用 Nasus 外部语义模型。上述原生观察留存推进 P1，但不替代完整原生图属性/导出、候选完成报告及 Goal 交付事务、动态调查/反证与累计预算、多格式/lineage/cutover、自动 delta/overlay/合并、五用途/脚本/RunPlan/真实运行、Provider 对照/隔离/gold/性能和最终 V1/P6。全目标继续保持开放。

## 原生执行文件校验的调度与完整性（2026-10-08）

真实 Temporal tool 的独立剖析保留原 180 秒观察时限，终态 **1 failed / 1 deselected / 188.71 秒**（`exweb-structure-profile-temporal-pg-minio-20261008.log`）。`exweb-structure-profile-20261008-tool-1.txt` 记录实际执行线程：整轮约 178 秒中，12 次执行文件读取累计约 125 秒，3589 次 `check_phase` 累计约 112 秒，SQLAlchemy connection 执行约 103448 次；终止栈确在执行文件读取的权威 callback。剖析本身有开销，不作为吞吐或 p95 门禁，也不把该取消栈当作首批 agent 返回 failed 的精确原因。

新读取调度按 50ms 合并重复权威检查，开始和结束仍强制调用；全部字节继续 hash，不缓存指纹、权限、目标、generation 或 worker epoch。结束时新增 fd 与当前路径完整签名复核，拒绝同长度改写和 inode 替换。没有提高结构预算、Worker 超时或测试进入时限，原 canonical 命令/提交/重试的权限和证据检查保持不变。实际合同见[执行文件固定](./code-graph-execution-control.md#worker-可执行文件固定)。

新增确定性红测 **5 failed / 1 passed / 34 deselected / 0.54 秒**（`executable-authority-coalescing-red-20261008.log`），复现逐块 callback 放大及两种文件变化未拒绝；结束撤权测试还明确核验短操作的最终 fence。修复后执行文件、依赖字节、会话/契约和 DDD/身份边界组 **255 passed / 43.89 秒**（`executable-authority-coalescing-pure-fixed-20261008.log`）。首次直接组合测试误纳入需要 PG 的 generation 文件，collection 因 SQLite 无法编译 ARRAY 退出 2（`executable-authority-coalescing-pure-20261008.log`）；PG 文件转到隔离 PG/MinIO 运行，不启用 SQLite 或跳过其断言。

真实 Temporal、原生 exweb、generation/租约/公开 API 与结构任务/停止的扩大组终态 **106 passed / 1 warning / 675.63 秒**（`executable-authority-temporal-api-pg-minio-20261008.log`）。这包含原来失败的全部五个 exweb 变体，未放大 180 秒任务观察或 30 秒 native-session 进入时限。该总时长覆盖全部 106 项，不能与原五项批次时长直接作为性能比。

`exweb-executable-authority-temporal-20261008-{tool,agent,stop-queued,stop-native-session,stop-candidate-committed}.json` 已逐份检查。两个重试入口各有 2 次 Temporal 尝试、最后 Worker epoch 2、4 次实际 index 和 4 次 MCP；原命令/确认/来源 pin 及两份投影摘要在重试后不变，history replay 和完成重读新增 Provider 调用为 0。两个重试和已提交停止候选均核验 **728 个真实成员、2 个 captured sources、0 个 legacy members、2194 个持久 provenance nodes**，其中固定 exweb **725 个代码成员、13 条路由及 751 处归档跨度**回读成功。来源 head 在 Worker 启动前移动、原工作区文件删除后，仍只使用原 plan 的归档输入。

排队停止没有 Provider 调用；native-session 等待 Worker 清理后确认 cancelled；提交后停止返回 already_committed，候选保留。这里验证的是真实原生会话返回后的协作停止，不是 CBM 进程 SIGKILL 或逃逸资源清扫。存储为独立 PG/私有 MinIO，目标代码执行、外部模型、业务 gold 和运行时依赖解析均为 false；这五个场景也不能代替需求/用例的真实业务语义验收。

本轮 Portal build/lint/i18n 退出 0（`executable-authority-portal-{build,lint,i18n}-20261008.log`），contracts **481 passed / 0 failed / 1.37 秒**，主包 **969.28 kB** chunk 告警仍在；独立 PG/私有 MinIO smoke **success**（`executable-authority-smoke-pg-minio-20261008.log`）。标准 API/运行配置/Compose/DDD 门禁终态 **297 passed / 1 warning / 303.51 秒**（`executable-authority-standard-api-pg-minio-20261008.log`）。

同场景修复后剖析终态 **1 passed / 1 deselected / 135.04 秒**（`exweb-structure-profile-fixed-temporal-pg-minio-20261008.log`），保留原 180 秒时限。`exweb-structure-profile-fixed-20261008-tool-{1,2}.txt` 中两次实际执行约 **47.67 / 45.37 秒**；首轮实际到达完整投影后的注入归档异常，再次执行完成。首轮 `check_phase` 为 **855 次 / 13.96 秒**，connection 执行为 **31001 次**；与旧同一剖析的 3589 次 / 112 秒、103448 次相比，确认重复权威查询放大已减少，但两次报告的调用构成不同，且 cProfile 自身有开销，不据此宣称 p95 或系统吞吐通过。

原生执行文件调度是 P0/P2 的具体修复，不替代完整隔离、性能、gold、动态调查、完成报告或 P0-P6 验收；开发业务库不迁移或写入。

## 原构建成果的只读审阅与独立发布入口（2026-10-08）

新增[原调查成果的审阅入口](./source-pinned-build-entries.md#原调查成果的只读审阅入口)：从原 `build_completion_review` Goal 打开确切调查命令保存的报告和画像。七次私有 GET 核验原 checkpoint、命令、报告、计划、最小画像页及原目标后再次比较 Goal；没有按“最新候选”回退。取消整图、release、解释、记忆和 Swarm 读取并隐藏旧缓存，已有会话只读，不隐式创建或重发写入。当前权限/摘要/目标 version 错配隐藏结果。

发布仅提供原计划目标，独立确认审阅和 CAS 发布。发布后可以重读原历史调查，原 Goal 和完整步骤保持不变；它仍停在完成审阅，不把知识发布等同于构建 Goal 交付、业务批准、质量生成或真实执行。SSE reducer 即时处理消息，而关联查询使用 200ms 首事件窗口、single-flight 和 `cancelRefetch=false`，避免历史事件反复取消读取。没有改全局 CSS、token、图标或 Canonical Tool/SSE 契约。

已核验的独立终态证据，不累加为项目总数或完整门禁：

- Portal contracts **457 passed / 0 failed / 1.42 秒**（`system-image-build-review-direct-contracts-20261008.log`），包含实际 TS 的七项固定读取、错误目标/摘要、撤权、历史 head 改变、审阅缓存隔离、普通工作区不变、GET-only 会话及 SSE 合并/清理。DDD/Portal 边界 **147 passed / 1.33 秒**（同前缀 `-boundaries` 日志）。
- Portal build/lint/i18n 退出 0（`system-image-build-review-direct-{build,lint,i18n}-20261008.log`），主包 **968.13 kB** 的 chunk 告警保留。隔离 PG/私有 MinIO smoke **success**（`system-image-build-review-direct-smoke-20261008.log`）。
- 原目标继续/调查权限与发布的后端 PG/私有 MinIO组 **37 passed / 1 warning / 244.98 秒**（`system-image-build-review-api-pg-minio-20261008.log`）。此批早于轻量前端读取及后加浏览器审计，不作为这些改动的验证。
- 原生固定 exweb 的只读审阅审计 **1 passed / 47.5 秒**（`exweb-build-review-read-only-audit-20261008.log`），报告 `output/playwright/exweb-build-review-read-only-audit.json`。实际 PG 的项目 LLMCall 全记录与原会话 ToolInvocation 全记录在打开、页面刷新和显式重新加载前后完全一致：**1 条模型审计、8 条工具记录**，新增模型调用、模型审计和工具命令均为 0。浏览器写入、审阅页整图与运行详情读取亦为 0；原 Goal 完整快照不变。固定干净 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc`、Tree-sitter 静态适配器、**546 个代码成员**，原导出在调查前已移除；不代表执行过目标程序、真实语义模型或 business gold。审计拒绝达到 500 条上限的截断结果，不用硬编码的计数代替服务器证据。

首轮轻量读取浏览器 **1 failed / 4 passed / 2.4 分钟**（`system-image-build-review-direct-exweb-browser-20261008.log`）。唯一失败是旧工作区在 Playwright 滚动链接时发出的整图 SSE 刷新被错误计入审阅页：trace 中请求发生于实际 click 前约 5ms。按请求发起时的原/审阅路由分别记录，不取消合法旧请求；审阅页零整图/运行详情读取及整个导航零写入仍严格断言。该轮其余四项包括 exweb 深色独立发布、实际撤权、中文和错误 pin 拒绝；后续当前代码的终态另行记录。

稳定源码的完整构建审阅专项 **6 passed / 3.7 分钟**（`system-image-build-review-direct-final-browser-20261008.log`），重新加载了持久审计及真实导航计数，包含 exweb light/dark 的独立发布、持久审计、实际来源撤权、中文及命令/画像/目标 version 错配拒绝。`output/playwright/exweb-build-review-handoff-{light,dark}.json` 只记录实际导航写入/读取计数，已去掉硬编码的模型调用字段；模型零新增由上述独立 PG 审计证明。已检查 390px 深浅色与中文截图。此批早于下节记录位置跳转，不冒充后续代码的复验。

较大的稳定浏览器选择集 **2 failed / 12 passed / 12.5 分钟**（`system-image-build-review-direct-current-browser-20261008.log`）：语言、五项构建审阅和六项原 Goal 继续场景通过；两项 exweb 语义用例均在后续独立重读时达到原 240 秒总时限。light trace 中完整对象/成员窗口 0–725 被逐页重复遍历 4–5 次，失败栈在坏结果 `revision/evidence` 的重新打开入口，不是页内无限重试或 HMR。下一节改用实际固定记录跳转减少重复遍历，仍保留首次全分页、所有安全场景及原 5 秒页读取/240 秒总上限；原失败终态不改写为绿色。

更早的浏览器失败保留于 `system-image-build-review-exweb-browser-20261008.log` 与 `system-image-build-review-exweb-sse-browser-20261008.log`：初版全量工作区读取/重放取消导致回读超时；一轮浅色 trace 证实测试期间的 HMR 卸载了 i18n provider，深色仍遇发布后整图读取超时。当前轻量入口在稳定生产源码下单独验证，不延长原断言或将旧失败批改写为全绿。

这推进 P2 的成果到知识审阅链路，但没有交付明确的 candidate-only Goal 完成事务、全计划多能力预算/动态反证、完整旧质量旅程切换或 P0-P6 全部退出条件。正常开发业务库未迁移；测试只使用临时 PG/私有 MinIO。

## 固定画像记录的直接定位（2026-10-08）

[冻结画像记录](./frozen-review-membership.md#读取与界面)新增从 1 开始的记录位置输入、范围显示及只读跳转。校验 position/total 的安全整数及范围，在原 image/session/section 的页面加载器中改变 offset，不增加 API、Provider 或写命令。继续核验整个工件和即时来源权限，objects/members 必须配对；读取/错配失败隐藏内容。实际页栈、section 重置、413 同窗口缩页和原深浅色/无滚动条风格保持不变。

当前纯门禁 **481 Portal contracts / 0 failed / 1.33 秒**，新增 24 项实际 TS 位置校验；分层边界 **148 passed / 1.33 秒**，新增界面不绕过原读取 transport 的约束。Portal build/lint/i18n 均退出 0，主包 **969.26 kB** 的 chunk 告警保留，日志前缀 `image-record-navigation-*`。固定 exweb 浏览器专项的最终结果独立记录，不以纯测试替代私有读取、撤权、语义模型或完整 P2/P6 门禁。

该代码的固定 exweb 浏览器组合已终态 **10 passed / 10.5 分钟**（`image-record-navigation-final-browser-20261008.log`）：包含 light/dark 原成果审阅、审计、来源撤权、中文、错误 pin、记录跳转及两种主题的完整语义场景。重复 sibling key 修复与 console 断言一起加载，原页读取 5 秒与语义总时限 240 秒未增加。此批早于下节新结构身份观察，不将旧 546 代码成员的验证冒充新 725 成员的完整复验；外部语义模型仍为明确协议夹具。

## 静态结构身份与多处原文证据（2026-10-08）

[结构身份契约](./code-object-identities.md#静态路由与导入观察)新增唯一 Java handler 路由、静态导入和无损 unsupported 文件 module 的 canonical 登记。路由保留主定位及两处注解支持证据，新观察 v3 追加保存，旧修订/hash 不改写。静态导入、unsupported 文件身份及精确源跨度不等于依赖解析、语言支持、业务覆盖或真实目标运行。

已结束的终态证据分开记录，不累加为项目总数：

- 纯解析、身份、结构构建、画像、调查及 DDD/Portal 边界 **241 passed / 1.87 秒**（`code-structural-identity-pure-20261008.log`），包含新 10 类身份/支持跨度正负场景。
- 真实 PG 的身份、证据及别名 **46 passed / 5.46 秒**（`code-structural-identity-pg-final-20261008.log`）。新增路由三处原文、移行/Provider 替换、删除源文件后历史回读、Outbox 故障全事务回滚；该 fixture 使用本地隔离 archive，不冒称 S3。首运行器文件列表写错、**未运行任何测试**的 exit 4 日志保留于 `code-structural-identity-pg-20261008.log`。
- 真实 PG 的 source-scoped 画像/记忆/Agent 上下文、结构/解析/别名/画像 API **58 passed / 82.40 秒**（`code-structural-identity-api-20261008.log`）；归档同样是隔离本地适配器。
- 固定干净 exweb、真实 CBM CLI/MCP、LangGraph PG、独立 PG/私有 MinIO 的自然聊天与补源阶段 **1 passed / 6 deselected / 1 warning / 189.84 秒**（`code-structural-identity-exweb-phase-20261008.log`）。`exweb-code-structural-identity-20261008-natural.json` 实际回读 **725 canonical members / 751 archive spans**，含 **13 路由 / 26 支持跨度 / 160 静态导入 / 6 unsupported 文件身份**。原生观察仍为 **755 entities / 1425 relationships**；初始和补源各 2 index/2 MCP，原 Goal/根计划/旧步骤不变，四份核验执行副本均清理，回放新增 Provider/模型调用 0。配套资料是 fixture，target executed 与 business coverage 均 false。
- PG generation 的协议/fencing/取消/恢复组 **33 passed / 1 skipped / 26.76 秒**（`code-structural-identity-native-pg-20261008.log`）。该批未配置独立 native exweb 输入，因此该项明确 skipped；不声称此次再次验证两 epoch 的实际 exweb 重建。
- Portal build/lint/i18n 退出 0，contracts **481 passed / 0 failed / 1.78 秒**（`code-structural-identity-portal-*`），主包 **969.28 kB** 告警保留；独立 PG/私有 MinIO smoke **success**（`code-structural-identity-smoke-20261008.log`）。新成员浏览器组合已终态 **2 failed / 9 passed / 14.4 分钟**（`code-structural-identity-browser-20261008.log`）：构建审阅、原生注解 inspector 与发布通过，两种主题的文档场景因遍历 725 代码成员在原 180 秒上限超时。改为实际固定记录跳转后 **1 failed / 1 passed / 6.0 分钟**（`code-projection-dependencies-documents-browser-20261008.log`），深色通过，浅色走到最后的历史冻结回读时总时限耗尽；没有延长原 5 秒断言或 180 秒总上限。归档 transport 热点优化及最新复验另见下节，不把旧失败改写为绿色。

该批次新归档的 synthetic System 根仍为 legacy observation；后来来源清单根的修复及独立复验见上文，不倒推改变这批旧工件或结果。candidate-only Goal 完成事务仍未交付。完整动态调查、语义 gold、多格式/lineage/cutover、自动更新、五用途/脚本/RunPlan/真实运行、隔离/性能和最终 P0-P6 门禁继续保持原范围。

## 投影依赖字节指纹与归档连接作用域（2026-10-08）

[投影依赖指纹](./code-graph-execution-control.md#投影源码与已安装依赖字节指纹)替代固定源码名单和仅 grammar 版本号的摘要：静态 import closure、父包 initializer、实际安装 distribution 文件字节及适用的传递依赖纳入 `nasus.code-index-generation.v2`。扫描不执行源码；权限、取消和预算 callback 显式贯穿首次登记、恢复和准备，metadata IO 不吞掉控制异常。PG generation/投影、旧命令和冻结画像不改写，同版本源码或 grammar 字节变化必须用新的独立确认命令。它不是完整 hermetic runtime、签名 release 或目标仓库依赖解析。

指纹改造、归档作用域改造前的已核验终态分别保留：

- 纯依赖/适配器/执行文件/会话/控制组 **122 passed / 51.53 秒**（`code-projection-dependencies-pure-final-20261008.log`）；metadata 中 PermissionError、取消和 KeyboardInterrupt 原样传播。同版本 transitive Python 和 synthetic grammar 字节变化测试使用私有夹具，不修改开发 `.venv`。
- 隔离 PG 的同版本变更拒绝及新命令 **2 passed / 34 deselected / 4.02 秒**（`code-projection-dependencies-pg-new-20261008.log`）；后来新增的首次登记控制异常 **2 passed / 36 deselected / 1.47 秒**（`code-projection-dependencies-pg-authority-20261008.log`）。原完整 PG/native 组 **36 passed / 266.38 秒**（`code-projection-dependencies-pg-native-20261008.log`），加载早于后加的两项控制场景，不合并计数冒称一次 38 项。
- DDD/Portal/Compose 边界 **165 passed / 1.29 秒**；Portal contracts **481 passed / 0 failed / 1.70 秒**，build/lint/i18n 退出 0（`code-projection-dependencies-*`），主包 **969.28 kB** 告警保留。该批不作为下述 transport 修改的验证。

[归档连接作用域](./archive-transport-sessions.md)进一步处理实际吞吐热点。旧快照 16 文件及清单/报告创建 18 个 SDK 客户端；新的独立 read/write scope 只在单次 owned 操作内复用 transport，仍执行每个 PUT/GET、内容 hash 和实时权限检查。原文 capture、cold materialization 和全部 chunks 写入已接入，application 只依赖 workspace 端口。异常/取消/配置变化/fork/关闭 context 拒绝与最后 active lease 清理都有回归，既有只读 scope 不兼作写 transport，不缓存来源正文或批准。

当前源码的已核验专项，不累计为全项目测试数量：

- 新作用域红测 **8 failed / 0.62 秒**（`system-image-archive-write-scopes-red-20261008.log`）保留；基础组 **45 passed / 0.71 秒**，补全线程/进程/清理异常与边界后 **195 passed / 1 skipped / 1.85 秒**（`system-image-archive-scopes-pure-boundaries-20261008.log`）。skip 是需独立私有 MinIO 的匿名下载负测，不是 exweb 实际归档跳过；下列独立 PG/MinIO 组已执行该场景。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、独立私有 MinIO **1 passed / 2.28 秒**（`exweb-archive-scopes-pg-minio-20261008.log`）。`exweb-archive-scopes-20261008.json` 验证 **126 文件 / 135 chunks**，inventory/完整快照分别 1/127 次 PUT、各自一个客户端；cold 和全新 materializer 各 127 次 GET，chunk 写入 135 PUT、回读 135 GET，各在独立作用域中且全部关闭。单轮采样 capture **0.503 秒**、cold read **0.251 秒**、chunk materialization **0.483 秒**，不是 p95 或负载门禁。未执行 exweb 或目标依赖，不是业务 gold。
- Portal contracts **481 passed / 0 failed / 2.15 秒**，build/lint/i18n 退出 0，主包 **969.28 kB** 告警保留（`system-image-archive-scopes-portal-*`）；独立 PG/私有 MinIO smoke **success**（`system-image-archive-scopes-smoke-pg-minio-20261008.log`）。
- 实际原生投影与 API 扩展组 **201 passed / 1 skipped / 1 warning / 604.78 秒**（`system-image-archive-scopes-api-native-pg-minio-20261008.log`），其中 native generation 组使用固定 exweb。skip 为旧 `test_real_exweb_provider_identity_replay` 所需的独立 `EXWEB_PROBE_REPORT` 未提供，不能用 native generation 通过代替旧 probe replay。
- 实际自然聊天入口、原 Goal 补源阶段、LangGraph PG 与私有 MinIO **1 passed / 6 deselected / 1 warning / 332.11 秒**（`exweb-archive-scopes-natural-phase-pg-minio-20261008.log`）；报告 `exweb-archive-scopes-natural-phase-20261008-natural.json` 核验原生 **755 entities / 1425 relationships**、**725** 个规范代码成员、**751** 处归档跨度、原计划及步骤不变。这里使用 Local 生命周期与 LangGraph PG，不声称实际 Temporal Worker 或外部模型验证。
- 文档浏览器 **2 passed / 3.8 分钟**（`system-image-archive-scopes-documents-browser-20261008.log`），固定 exweb 三源、原文/冻结历史/引用审阅、浅深色与 390px 检查均保持原超时；移动截图已检查。它不是外部模型语义判断或目标用例执行验证。

本轮首纯命令写错 executable 测试文件路径，exit 4、**没有执行任何测试**（`system-image-archive-scopes-projection-pure-20261008.log`）。修正后 **112 passed / 8 skipped / 57.10 秒**（`system-image-archive-scopes-projection-pure-final-20261008.log`），八项 registry 测试要求独立 PG；另用真实 PG/私有 MinIO 执行 registry、private storage、归档作用域组 **30 passed / 1 warning / 2.05 秒**，匿名下载确实返回 403，SDK 的 Python 3.9 支持告警保留。这些批次早于下述 manifest 根改动，不作为其原生或浏览器复验，也不拼接为完整 V1 全绿。完整 candidate-only 完成事务、动态三源/反证、独立语义 gold、多格式/lineage、自动 delta/overlay/合并、五用途/RunPlan/真实执行、Provider 对照/隔离/完整性能和最终 V1/P6 验收继续保留原范围。正常开发服务未启动，业务库未迁移。

## 原生执行文件与持久指纹一致性（2026-10-08）

[Worker 可执行文件固定](./code-graph-execution-control.md#worker-可执行文件固定)补齐安装文件在两次检查之间变化的窗口。实际 PG generation 指纹传入会话，版本探测、MCP、索引和后续查询只执行核验过的私有字节副本；复制期间检查权限和取消，正常、失败及中断清理所属目录，不使用硬链接或自动下载。指纹不匹配在任何原生命令前拒绝；旧 generation/hash 不改写，不能借重试切换策略。兼容非 durable 会话未切换，也未完成独立账号、禁网、资源隔离、传递依赖锁定或强杀遗留清扫。

当前终态证据按实际范围分别记录，不累加为项目测试总数：

- 纯适配器、文件策略、会话、控制及 DDD/Portal 边界 **245 passed / 16.01 秒**（`code-graph-executable-snapshot-pure-final4-20261008.log`）。包括复制窗口的授权撤销、四执行阶段的 Provider 错误/取消/撤权/KeyboardInterrupt、目录/FIFO/符号链接/空文件/超界/不可执行拒绝、fd 检查失败关闭以及安装文件变化前拒绝和执行中固定副本。这些故障注入使用实际协议子进程夹具，不冒充原生语义 gold。
- 真实 PG generation 专项 **34 passed / 38.76 秒**（`code-graph-executable-snapshot-pg-final3-20261008.log`）。复制时暂时替换安装文件后恢复，仍在任何原生命令前拒绝且不登记协议/投影；跨实例取消实际协议子进程并清理执行副本。该组的 storage fixture 显式使用本地归档，不能因为运行器带 `--minio` 就声称测试本身使用了 S3。
- 同一 PG 组包含固定干净 exweb 的两次真实 CLI/MCP 索引与 epoch 1→2 重建。`exweb-executable-snapshot-rebuild-final3-20261008.json` 核验每会话同一执行副本、两次副本不同且均与原 generation 指纹一致、两次原生 **755 entities / 1425 relationships** 与全量规范化投影相同、旧游标拒绝及副本清理。协议仍保留 CLI 0.8.1/MCP 0.10.0 的实际差异和 gap；不改写为完整能力验证。
- 独立 PG/私有 MinIO、实际 CBM CLI/MCP 和 LangGraph PG 的 exweb 自然语言构建与补源阶段 **1 passed / 6 deselected / 1 warning / 189.99 秒**（`code-graph-executable-snapshot-exweb-phase-20261008.log`）。`exweb-executable-snapshot-phase-20261008-natural.json` 核验同一原 Goal/根计划/旧步骤、独立新阶段预算，初始和补源各 **2 index / 2 MCP**，四份执行副本均核验并清理，历史重放新增 Provider/模型调用为 0。私有 MinIO 独立 hash 回读 **134 次 / 3,515,208 字节**，覆盖 4 manifests、129 来源文件和 1 frozen image；源码 SHA 为 `fe5827f6b76f77ef34918d8b452ee823142332dc`。这是本地 LangGraph 构建，不冒称该场景经过 Temporal；伴随需求/测试为 fixture，未执行 exweb、目标依赖或外部语义模型，不是业务 gold。
- 当前 Portal contracts **481 passed / 0 failed / 2.03 秒**；build/lint/i18n 退出 0，隔离 PG/私有 MinIO smoke **success**（`executable-snapshot-record-navigation-*` 日志）。主包 **969.28 kB** 的 chunk 告警保留。专项不替代完整 E2E、V1 门禁、旧链 cutover 或全计划验收。

保留失败历史：最初缺少执行文件 pin 的测试 **8 failed**；扩大纯组先有 callback 的 PermissionError 被错误转成 transport 异常，修复后 **1 failed / 225 passed** 又暴露 macOS 在 fd 类型检查前创建目录流及可能泄漏 fd，改为先检查并在交接流前的任何失败关闭 fd。首 PG 原生组 **1 failed / 33 passed** 为初始 128 MiB 文件策略小于实际 269,460,400 字节安装文件，原生命令尚未启动；按真实二进制大小设定有界 512 MiB 文件上限并保留超界拒绝测试，没有提高原进程 timeout、画像页 5 秒或语义场景 240 秒限制。各原失败日志保留于 `code-graph-executable-snapshot-*`，不改写为绿色。

该增量推进 P0 的实际执行身份与取消完整性。P2 的明确 candidate-only Goal 交付事务、完整动态/反证与累计预算，P3 真实语义/业务 gold、P4 自动增量/overlay/合并、P5 五用途/旧链/RunPlan 与真实执行、P6 全量 V1/灾备/试点继续保留原目标。

## 来源类别请求与构建状态说明（2026-10-08）

当前[固定来源入口](./source-pinned-build-entries.md)支持完整中英文来源类别请求，不再只接受短别名。类别只描述当前完整 captured manifest，不选择新来源或过滤 binding；新路径／URL、多动作、重复类别和版本会话的 official 歧义仍澄清。原 Goal、完整 target、原查询与独立预算保持固定，不恢复旧可变初始化或自动发布。

解释接口区分补源、候选、新阶段和完成审阅，并让实际运行态／终态优先于历史暂停原因与旧命令 gate。取消保留已保存候选和历史，不提示确认；追加阶段不展示旧阶段 pending/running 步骤。失败后的说明不建议恢复终态 Goal。这是只读引导修复，不是完整停止／重试／接管实现。

当前终态证据分别记录，不累加为项目总测试数：

- 自然请求与缺码矩阵真实 PG／私有 MinIO **55 passed / 1 warning / 438.93 秒**（`system-image-source-language-pg-minio-final-20261008.log`），包含 Local/LangGraph PG、完整类别请求、同 Goal、独立预算、错误请求和等待恢复。首轮 **4 failed / 51 passed** 为新项目 fixture 沿用了旧项目 manifest；改为回读新项目画像，未放宽生产来源校验。
- 旧 API 的 13 项画像旅程按新固定来源契约迁移后 **13 passed / 126 deselected / 1 warning / 70.85 秒**（`system-image-source-language-legacy-final-20261008.log`）。状态查询仍 completed，Goal 等待补源；旧预算快照重放拒绝，结构候选不自动变 ready。审计旅程使用实际注册账号并核对调查确认者；开发虚拟用户不具备可核验数据库身份，未放宽调查许可。旧路径文本只澄清，显式 legacy swarm 的持久化测试单独保留，不声称旧链 cutover 完成。
- 扩大 API／runtime config／身份管理／Compose／DDD 的真实 PG／私有 MinIO **301 passed / 1 warning / 362.30 秒**（`system-image-source-language-current-compatibility-20261008.log`）。该批加载早于本节后续解释运行态／终态修复，不冒称它验证了这些后加分支。
- 真正 Temporal／PG／私有 MinIO 四变体 **4 passed / 1 warning / 194.99 秒**（`system-image-source-language-temporal-20261008.log`）：已有输入用完整英文类别请求，缺码用完整中文请求，分别检查 Worker 更换和启动 Activity 重试、原工作流、独立预算／调查及 history replay。不是 OS 强杀或全部生命周期恢复。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的完整英文自然请求 **1 passed / 6 deselected / 1 warning / 90.54 秒**（`exweb-source-language-pg-minio-20261008.log`）。实际 CBM CLI/MCP、LangGraph PG、隔离 PG／MinIO；`exweb-source-language-20261008-natural.json` 核验原 Goal／根计划／旧步骤不变，新补源阶段独立执行，**755 entities / 1425 relationships**，初始和新阶段各 **2 index / 2 MCP**，回放新增 Provider／模型调用 0。4 manifests／129 文件／1 image 独立远程 hash 回读 **134 次 / 3,515,442 字节**；主动毫秒 **21,017 → 42,604**、等待结算和首次起点保留。这不是缺码 exweb 变体本身、真实 Temporal、业务 gold、外部语义模型或目标程序执行证明；伴随需求／测试仍为 fixture。
- 当前两文件真实 PG／私有 MinIO 浏览器 **10 passed / 2.2 分钟**（`system-image-source-language-browser-20261008.log`）。浅色完整英文和深色完整中文的消息没有 `canonical_action_id`，验证实际自然聊天入口；引导／保存入口仍复用原 Goal、独立确认和刷新恢复。两张 390px 候选卡截图已目视检查，没有改 CSS／token／图标。
- 解释状态红测 **46 failed / 24 passed / 0.31 秒**（`system-image-explanation-state-red-20261008.log`）复现运行／取消／失败态使用历史 gate；追加阶段红测 **3 failed / 1 passed / 70 deselected / 0.25 秒**（`system-image-explanation-phase-red-20261008.log`）复现指向历史步骤。修复后纯入口／计划／说明／DDD／Portal／Compose 组 **369 passed / 1.48 秒**（`system-image-explanation-state-final-pure-20261008.log`）。
- 后续解释权限／原目标调查／结构停止的真实 PG／私有 MinIO组 **30 passed / 1 warning / 105.38 秒**（`system-image-explanation-state-api-20261008.log`）。新 HTTP 例使用真实账号、真实已保存候选及原调查 gate，经状态机与 PG 恢复 cancelled 投影，核对无恢复／确认提示、原工件／命令不变和非成员拒绝；该例不冒称自己执行了结构停止命令，停止 API 另由同组专项检查。
- Portal build／lint／i18n 退出 0，contracts **370 passed / 0 failed / 1.23 秒**（`system-image-source-language-{build,lint,i18n,contracts}-20261008.log`）；主包 **949.53 kB** 告警保留。独立 PG／私有 MinIO smoke **success**（`system-image-source-language-smoke-20261008.log`）。

全量 PG／私有 MinIO 浏览器批 `system-image-source-language-current-full-browser-20261008.log` 已退出 1：**3 failed / 215 passed / 1 skipped / 1.1 小时**，共 219 项、单 Worker。语言用例加载了旧构建标题；旧完整质量旅程仍要求自动完成/发布，尚未迁移，不能仅改标题或恢复隐式发布使其通过。深色语义用例的 offset=100 两请求被取消，trace 同时记录 KnowledgeSection/ImageRevisionInspector 的 Vite HMR，不能据此改大分页超时；稳定源码专项需要重新验证。exweb opt-in 场景因该批未配置来源目录而跳过。后续专项不替代这份全量终态或完整 V1 结果。正常开发服务没有启动，业务库未迁移；浏览器服务仅用于隔离验证。

完整 BuildIntent／维护事件、创建／审计／Outbox 原子链与其他生命周期 owner fencing、全计划多能力授权／累计费用、动态三源语义与反证、来源 cutover／lineage／多格式、Provider 对照／gold／隔离／性能、自动 delta／overlay／合并、五用途／旧链切换／脚本／RunPlan／真实执行反馈以及 P6 和完整 V1 门禁继续保留原验收范围。

## 主动运行预算与原目标恢复（2026-10-08）

0089 增加[持久主动运行计时](./agent-active-runtime.md)，修正新目标把缺码、确认和审阅等待计入 runtime 的问题。新 Goal 累计运行态毫秒，暂停和终态结算，恢复及追加阶段不清空消耗；首次启动时间保持。旧记录不猜测回填、旧 JSON/v1 digest 不改写，新 v2 checkpoint 将计时纳入完整条件恢复。该增量不是全计划多能力费用账本、全局 owner fencing 或完整 P2。

当前独立终态，不累加为项目总数或完整门禁：

- 红测 **18 failed / 1 passed / 0.28 秒**（`agent-active-runtime-red-20261008.log`）复现暂停仍耗时、区间不累计和字段未校验；首修组 **1 failed / 75 passed / 0.62 秒**，唯一失败为原 AST 测试仍假定事务里内联 steps 赋值。边界断言更新为同事务 lock/compare 后调用完整 aggregate helper，并核对 steps、计时和 scope 字段，没有放宽 CAS 要求。
- 最终纯策略/application/旧摘要及 DDD/Portal/阶段边界组 **338 passed / 3.27 秒**（`agent-active-runtime-final-pure-boundaries-20261008.log`）。包含毫秒累计、全部暂停/终态出口、用户中断先持久化后发布、运行态重建不重置、坏字段/无时区拒绝和旧 v1 摘要。
- 真实 PG/私有 MinIO 迁移、计时、完整等待矩阵、预算恢复和条件消费组 **63 passed / 1 warning / 242.59 秒**（`agent-active-runtime-pg-minio-20261008.log`）。Local/LangGraph PG 验证长时间等待后仍可补源、已耗尽 runtime 不被恢复清零、独立提高上限后才推进、旧 pin 不确认下一 gate；加性迁移不填造历史、存在新计数时降级拒绝。
- 真实 Temporal/PG/私有 MinIO 的 captured/waiting × Worker 更换/启动 Activity 重试四变体 **4 passed / 1 warning / 205.17 秒**（`agent-active-runtime-temporal-pg-minio-20261008.log`），计时跨 Worker 和独立预算/调查累计，所有等待区间结算，原起点/命令和 history replay 保留。不是 OS 强杀或所有分支接管。
- 固定干净 exweb 缺码入口和补源追加阶段 **1 passed / 6 deselected / 1 warning / 94.18 秒**（`exweb-active-runtime-pg-minio-20261008.log`），实际 CBM CLI/MCP、LangGraph PG、PG/MinIO。报告 `exweb-active-runtime-20261008-waiting.json` 为 **755 entities / 1425 relationships**，初始/补源各 1 index/1 MCP、重放和模型调用 0；累计运行从 **20,812 ms** 到 **36,130 ms**，等待已结算、首次起点保留。132 个远程 hash 回读 **3,620,502 字节**，3 manifests/128 文件/1 frozen image。不同归档元数据会改变总字节，不复用前批计数；伴随需求/测试仍非 business gold、目标仓库未执行。
- 浏览器首轮 **1 failed / 1 passed / 45.7 秒**（`agent-active-runtime-browser-pg-minio-20261008.log`）：浅色结构恢复 POST 实际约 4.8 秒并返回 200/候选，原 5 秒断言和异步快照存在等待竞争。改为先核验该原响应，再检查界面；未改业务状态、确认要求或通过计数。最终两文件 **10 passed / 2.1 分钟**（`agent-active-runtime-final-browser-pg-minio-20261008.log`），实际引导/保存入口、原 Goal、独立确认、字段累计、错配/刷新恢复和深浅色/390px 均检查；两张移动截图已目视复核。不是性能门禁通过。
- explanation 权限/API 契约 **1 passed / 7.92 秒**（`agent-active-runtime-explanation-pg-minio-20261008.log`）；私有 MinIO smoke **success**（`agent-active-runtime-smoke-pg-minio-20261008.log`）。Portal contracts **370 passed / 0 failed / 1.07 秒**，build/lint/i18n 退出 0；主包 **949.53 kB** 的 chunk 告警保留。日志均使用 `agent-active-runtime-*` 前缀。
- 最后一组入口／补源／阶段／启动回执兼容测试已结束：**113 passed / 1 warning / 542.04 秒**（`agent-active-runtime-entry-phase-compat-pg-minio-20261008.log`）。原运行 handle 已不存在，日志有完整 pytest 终态；不是仍运行或完整 V1 门禁结果。

正常开发业务库未执行 0089，API/Portal/Runner/Worker 未启动。最新完整 V1 全绿证据仍缺失；完整三入口/旧 API cutover、创建/审计/Outbox 原子链、其余 owner fencing、全计划授权/费用、动态三源语义/反证、来源 lineage/多格式、自动增量/overlay/合并、五用途/旧生成切换/脚本/RunPlan/真实执行反馈及 Provider 对照、独立 gold、隔离和性能仍须继续交付。

## 固定来源准备与缺码目标恢复（2026-10-08）

新增[固定来源的构建入口与缺码恢复](./source-pinned-build-entries.md)。有界的中英文直接请求与 Project Overview 引导共用 application 编译器，在当前会话的唯一获授权目标上固定 v3 target 和已采集 manifest；保存 canonical plan 后才追加原计划查询、独立结构预算和结构执行，不进入旧可变物化/自动发布路径。任意自然语言、新 URL/另一版本与维护事件仍未统一。

缺少代码时保留原 target/objective/mode、等待 digest 和唯一 `query.system_image.status`，该特定查询只用本地摘要、无模型出口。补源后的显式 checkpoint 继续或同一有界消息复用原 Goal/workflow，回读原状态命令后追加固定 plan；输入仍不足不消费 checkpoint，成功后的旧 pin 重放不释放独立结构预算。前端验证原状态和原计划 canonical 回执，等待阶段不展示确认按钮，沿用原深浅色、窄屏与无滚动条样式。

已有终态分别记录，不累加为项目总测试数：

- 直接请求/准备与等待纯测试 **53 passed / 0.33 秒**；包含原目标、完整 request/receipt、错误 scope、额外工具、权限和缺码时不消费/不确认。application、DDD/Portal 和活跃 controller 边界组 **250 passed / 2.30 秒**（`source-build-wait-unit-boundaries-20261008.log`）。
- 真实 PG/私有 MinIO 的自然准备与首次等待恢复 **17 passed / 1 warning / 169.56 秒**（`source-build-wait-api-pg-minio-20261008.log`）。Local/LangGraph PG 两种图，显式 resume/引导聊天两种补源渠道；原 Goal/工作流/查询输入与 invocation 不变，移除原文件后仍从归档构建，旧等待 pin 不能确认预算。
- 真实 Temporal/PG/私有 MinIO 的四变体 **4 passed / 1 warning / 195.49 秒**（`source-build-wait-temporal-pg-minio-20261008.log`），分别覆盖已有 captured 输入与 missing-input Goal 的 Worker 更换、启动 Activity 返回后故障重试、独立预算/调查以及 history replay。不是 OS 强杀或所有能力自动接管。
- 当前真实 PG/MinIO 浏览器两文件 **10 passed / 1.9 分钟**（`source-build-wait-browser-pg-minio-20261008.log`），引导来源绑定前后保留同一个 Goal、原查询回执与七项固定引用，独立预算后结构候选保存，重复操作不重采集；同时复验已保存入口错配/刷新恢复。浅色英文、深色中文及 390px 截图已查看，无横向溢出，不改全局 CSS/token。
- 固定干净 exweb 缺码入口 **1 passed / 6 deselected / 1 warning / 80.53 秒**（`exweb-source-build-wait-pg-minio-20261008.log`），真实 CBM CLI/MCP、LangGraph PG、PG 和 MinIO。`exweb-source-build-wait-20261008-waiting.json` 核验原 Goal 延续、新补源阶段独立执行、旧步骤/根计划不变，**755 entities / 1425 relationships**；初始与补源各 **1 index / 1 MCP**，重放 Provider 和模型调用 0。独立远程 hash 回读 **132 次 / 3,620,523 字节**，覆盖 3 manifests、128 文件和 1 frozen image。这个新项目没有原 Orders 代码 fixture，不能沿用此前每阶段两次索引的计数。需求/测试为伴随验证资料，target_repository_executed=false、business_gold=false；此 exweb 场景本身不是 Temporal 证明。
- Portal contracts **370 passed / 0 failed / 1.04 秒**（`source-build-wait-contracts-20261008.log`），含原状态 receipt 恢复和十二类篡改拒绝；build/lint/i18n 退出 0。主包 **949.53 kB** 的 chunk 告警保留（`source-build-wait-build-20261008.log`）。

扩大自然入口批 `natural-build-preparation-expanded-fixed-pg-minio-20261008.log` 已终态退出 1：**14 failed / 410 passed / 1 warning / 804.30 秒**。主要为旧 API 自然请求/绑定及可变初始化旅程尚未切换，另有旧 DDD 英文文案断言；后者在上述边界批复验通过。缺码生命周期由新专项证明，不以此宣称原失败集合全部已修复。没有恢复自动发布来使旧测试通过，也没有最新完整 V1 全绿证据。

本轮新增 PG 拒绝/并发回归首批 **2 failed / 16 passed / 1 warning / 118.76 秒**（`source-build-wait-guards-pg-minio-20261008.log`）：目标漂移已正确返回 409，两项失败为测试将外层统一错误码写成内层 waiting 错误码。仅修精确断言；同时保留原 Goal、零 plan/grant、零 checkpoint consumption 的检查。实际并发 Local/LangGraph PG 已各有一个 200/一个 409，不把首批失败改写为全绿。

计时改造前的扩大兼容批终态为 **104 passed / 1 warning / 450.55 秒**（`source-build-wait-final-compatibility-pg-minio-20261008.log`），覆盖准备/保存入口、目标与旧恢复检查点。随后补充 failed-code/failed-optionals/only-optionals × 两种图矩阵 **6 passed / 20 deselected / 1 warning / 31.67 秒**（`source-build-wait-source-matrix-pg-minio-20261008.log`）；这六变体已在上方 0089 的 63 项组内再验。旧批不冒充新计时或完整 V1 证明。

开发业务库未迁移，正常 API/Portal/Runner/Worker 未启动。完整三入口、创建/审计/Outbox 全事务、其余 owner fencing、全计划多能力预算、动态语义/反证、来源 cutover/lineage、多格式、自动 delta/overlay/合并、五用途/旧链切换/脚本/RunPlan/真实执行反馈，以及 P0/P6 的 Provider 对照、独立 gold、隔离、性能和最终门禁仍待交付。

## 已保存意图的共享 Agent 入口（2026-10-08）

[固定 BuildIntent 契约](./targeted-build-intents.md#已保存意图的共享-agent-入口)新增 UI／显式聊天共用 application 编译 port。Planner、Goal compiler 和生命周期复用同一个实例，固定 project/plan/digest、完整来源、原目标及一次结构 work item；不接受调用方步骤。编译原计划查询、独立结构预算确认与结构执行，后续调查／补源沿同一 Goal 的现有门禁。已有目标复用重新检查原来源与目标，不允许换计划。创建互斥的后续交付见下节；共享入口仍不代表完整自然语言／维护事件统一或持久启动幂等恢复。

Knowledge 默认折叠入口，提交前写入当前账号／项目／计划／digest 的只读恢复标记。未知回执、错配和刷新后只重新授权原计划并 GET 原会话，不自动重发 POST；严格核验恰好三项引用、原三步 prefix 和预算，允许原目标后续追加步骤。沿用现有深浅色、弹层、移动布局，不改全局视觉 token。摘要错误、空 ID、多余指令等显式命令只澄清，不进入模型或旧可变流程；引用、问题和文档文字不是此执行入口。

已结束的验证分别记录，不累加为全项目测试数量：

- 原入口／调查回读／目标契约的真实 PG、私有 MinIO 专项 **41 passed / 1 warning / 150.40 秒**（`saved-build-entries-api-fixed-pg-minio-20261007.log`），包含 Local、LangGraph PG、实际聊天 POST 202／Turn 委派、原目标调查、错误计划／摘要／步骤／会话、目标漂移和非管理员来源撤权。首轮夹具的步骤 DTO 与另计划去重问题曾 **2 failed / 12 passed**，修正后扩大范围验证；不是最新完整 V1 门禁。
- 实际 Temporal／PG／MinIO 的共享入口专项 **1 passed / 2 deselected / 1 warning / 53.66 秒**（`saved-build-entries-temporal-pg-minio-20261007.log`）：共享 compiler 生成原三步，Worker 更换、阶段提交后的 Activity 故障重试、旧 pin 重放、独立新预算及后续调查／history replay。其他两个既有变体本批未执行，不冒充三项或 OS 强杀演练。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、真实 CBM CLI/MCP、LangGraph PG、独立 PG／私有 MinIO 的引导和实际聊天两入口 **2 passed / 2 deselected / 1 warning / 173.70 秒**（`exweb-saved-build-entries-pg-minio-20261007.log`）。两个 JSON 分开保存为 `exweb-saved-build-entries-20261007-{guided,chat}.json`，各核验原 goal／步骤／根计划不变、新补源阶段独立执行、**755 entities / 1425 relationships**；初始和补源各 2 index／2 MCP，历史重放 Provider 调用 0。分别独立远程回读 134 次／3,515,442 和 3,515,434 字节，覆盖 4 manifests、129 文件、1 frozen image。投影 hash 分别保存在报告，不声称跨随机 binding 的摘要相同；伴随资料不是维护者规范，model calls 0、target_repository_executed=false、business_gold=false。
- 首轮共享入口、计划／补源阶段与调查继续浏览器 **19 passed / 4.8 分钟**（`saved-build-entries-browser-pg-minio-20261007.log`）。调查夹具取消不相关的旧可变物化，生产回读移除重复 plan read，保留真实来源／构建／恢复和全部断言，未延长超时。当前真实 PG／MinIO 加显式 exweb inspector **4 passed / 1.9 分钟**（`saved-build-entries-exweb-browser-pg-minio-20261008.log`），覆盖 13 条精确注解路由、`ChatController.java:20-45` 归档原文、固定候选／计划及共享入口；浏览器使用 Tree-sitter 静态适配，不冒称 CBM/MCP。新增传输回执扩张／重复引用的两项负测后，共享入口文件 **5 passed / 49.3 秒**（`saved-build-entries-final-browser-pg-minio-20261008.log`），仍只发一次 POST，GET 恢复原持久目标且授权／工件为空。
- 错误命令纯负测先 **13 failed / 26 passed**，前端错配回执先 **2 failed / 15 passed**，分别确证 Planner 回落和多余引用被接受。修复后纯 Python 组 **99 passed / 0.35 秒**（`saved-build-entries-command-pure-20261008.log`），入口 Node **17 passed**，全部 Portal contracts **322 passed / 0 failed / 1.08 秒**；DDD／Portal／Compose／隔离存储边界 **176 passed / 1.21 秒**（`saved-build-entries-boundaries-20261008.log`）。
- 实际错误聊天负测先错误地要求准备工具为空，诊断批 **1 failed / 11 deselected / 3.81 秒**；改为比较前后完整工具记录后，又发现读取旧 `content` 而非消息 `blocks` 的夹具错误，入口批 **3 failed / 11 passed / 40.51 秒**。两处夹具修正后这三项 **3 passed / 11 deselected / 1 warning / 9.30 秒**（`saved-build-entries-malformed-final-pg-minio-20261008.log`），实际 Turn 仅澄清、无 Goal／新工具／授权，未调用模型。扩大数据库批的终态另列，不以专项拼接声明全量通过。
- 修正两处夹具前的扩大批 **3 failed / 122 passed / 1 warning / 563.95 秒**（`saved-build-entries-expanded-pg-minio-20261008.log`）；同一十文件范围的最终 PG／私有 MinIO 批 **125 passed / 1 warning / 550.55 秒**（`saved-build-entries-final-expanded-pg-minio-20261008.log`），包括三个错误聊天、调查回读、目标契约、计划／授权／结构／补源阶段及原目标继续。它加载早于下节创建互斥改动，不作为该改动的验证或完整 V1 门禁。
- 当前三种真实 Temporal 变体 **3 passed / 1 warning / 161.49 秒**（`saved-build-entries-current-temporal-pg-minio-20261008.log`）；同一次独立 exweb 原生四变体 **4 passed / 1 warning / 343.69 秒**（`exweb-saved-build-entries-current-pg-minio-20261008.log`）。四份 `exweb-saved-build-entries-current-20261008-{legacy,targeted,guided,chat}.json` 均逐份检查：固定原 commit、同 Goal／旧步骤／根计划不变、独立新阶段、755/1425、初始与新阶段各 2 index／2 MCP、重放 0；每份核验 4 manifests、129 文件、1 image、134 远程回读，字节数分别 3,515,208／3,515,453／3,515,442／3,515,310。随机 binding 的投影 hash 不要求相同；model 0、target false、business_gold false。它们同样早于后续创建互斥修改，最新改动需另批验证。
- Portal build／lint／i18n 退出 0（`saved-build-entries-{build,lint,i18n}-20261008.log`），主包 **944.01 kB** 的 chunk 告警保留；独立 PG／私有 MinIO smoke **success**（`saved-build-entries-smoke-pg-minio-20261008.log`）。深浅色及 390px 入口截图已查看。正常开发服务未启动，业务数据库未迁移。

完整 BuildIntent 的自然语言初始化／维护事件、全计划多能力预算、创建幂等与其他生命周期 owner fencing、动态调查／反证、完成到发布的引导仍未完成；P0 Provider 对照／独立 gold／隔离／性能、P1 来源 cutover／lineage／多格式、P3 规范创作与语义验收、P4 自动 delta／overlay／合并、P5 五用途／旧链／脚本／RunPlan／真实执行反馈和 P6 完整门禁／灾备／安全／业务试点保留原验收范围。最新完整 V1 仍无全绿证据。

## AgentGoal 并发创建保护（2026-10-08）

正式生命周期的 create 与 upsert 分开。SQLAlchemy 创建 port 在同一 PG 事务锁定 Conversation 行，核对原项目及 pending/running/paused/blocked controller 后插入完整 Goal；无 Goal 的空会话也受锁保护。竞争者得到原 Goal ID，application 回读并重新授权原固定 plan/digest，不发布 proposed 事件、不再次启动图。不同保存计划、原目标漂移、来源撤权以及已有引用的扩张／重复均拒绝复用。多个旧 controller 不按顺序猜测，不自动删除旧事实。纯兼容适配保持同样的单进程规则，不冒称跨进程数据库锁。

首轮新增原目标引用负测 **2 failed / 39 passed**（`saved-build-claim-scope-red-20261008.log`），确证旧集合比较忽略多余／重复引用。首轮创建冲突纯测试 **10 failed / 56 passed**（`saved-build-claim-pure-20261008.log`）为新增 fixture 缺必需 status/steps，补齐后 **84 passed / 1.72 秒**；最新纯 application／适配器与 DDD／Portal／Compose／隔离存储组 **261 passed / 3.08 秒**（`saved-build-claim-final-pure-boundaries-20261008.log`）。

真实 PG／私有 MinIO 首轮创建和入口专项 **30 passed / 1 warning / 51.14 秒**（`saved-build-claim-first-pg-minio-20261008.log`）：两个独立 OS 子进程、独立 engine/session 对空会话竞争，三次均恰好一个 created 和一个 existing；四类活跃状态、三个终态释放、错误项目／缺会话、多旧 controller 以及 flush 故障回滚核验通过。公开 HTTP 两请求在同步 precheck 之后竞争：同一保存意图返回同一目标，不同意图恰好一个成功与一个 400；只有一条原计划查询和一条独立预算 gate，执行授权和结构工件仍为空。该批早于后续 precheck 歧义保护，扩大组、浏览器、Temporal 与原生 exweb 当前验证另列终态。

当前改动的专项终态如下，不累加为项目总数：

- 两个实际 HTTP 竞争场景增加原 `graph.start` spy 后 **2 passed / 14 deselected / 8.69 秒**（`saved-build-claim-graph-start-pg-minio-20261008.log`），每场景真实图启动严格一次，不以工具命令幂等回执代替 dispatch 次数。扩大组启动时尚未加载这条新增断言，两批范围分别保留。
- 原扩大 PG／私有 MinIO 回归已终态 0 退出，**303 passed / 1 warning / 761.57 秒**（`saved-build-claim-final-expanded-pg-minio-20261008.log`）；该批包含创建、保存意图、原目标/阶段/补源、API/config，加载早于后续 graph spy 和 0088，不冒称新启动回执已经被这一批验证。
- 真实 Temporal／PG／私有 MinIO 三变体 **3 passed / 1 warning / 163.65 秒**（`saved-build-claim-current-temporal-pg-minio-20261008.log`），现行创建 port 下 Worker 更换、Activity 重试、旧 pin 重放、独立预算和原目标调查／history replay 不回退；不是 OS 强杀或启动前 crash 恢复。
- 真实 PG／MinIO 浏览器三文件 **16 passed / 4.4 分钟**（`saved-build-claim-browser-pg-minio-20261008.log`），新增双标签页同时点击只得到同一持久目标、两个面板均保留独立执行确认，计划零授权／零工件；同时保留错配回执、刷新、补源阶段及 light/dark/390px 断言。当前两种主题移动截图已查看，无横向溢出，未修改全局 CSS／图标／token。
- Portal build／lint／i18n 退出 0，contracts **322 passed / 0 failed / 1.60 秒**（`saved-build-claim-{build,lint,i18n,contracts}-20261008.log`）；主包 **944.01 kB** 告警保留。独立 PG／私有 MinIO smoke **success**（`saved-build-claim-smoke-pg-minio-20261008.log`），该兼容旅程不能证明旧画像／生成链已经切换。
- 固定干净 exweb 四入口已终态 0 退出，**4 passed / 1 warning / 370.02 秒**（`exweb-saved-build-claim-current-pg-minio-20261008.log`）。同前缀 legacy/targeted/guided/chat JSON 已逐份核验同一原 Goal、新阶段独立授权、旧步骤与根计划不变，原生 **755 entities / 1425 relationships**；各入口初始与新阶段均 **2 index / 2 MCP**，重放额外 Provider 和模型调用均为 0。私有远程回读各 **134 次**，分别 **3,515,434／3,515,442／3,515,442／3,515,177 字节**，覆盖 4 manifests、129 文件和 1 image。不是维护者 business gold、真实语义模型或目标执行证明，加载早于 0088。

这是活跃 controller 的创建互斥，不是完整持久启动幂等键、创建＋审计／Outbox 全事务、dispatch 恢复或 owner lease。创建后、图启动前进程崩溃仍是待交付项；不能以三个过程竞争样例证明全部高并发／容量／故障恢复。完整 P0-P6、旧链 cutover 和最新完整 V1 门禁继续保留。

## 持久启动回执与 Temporal 创建冲突（0088，2026-10-08）

新增[启动回执契约](./agent-goal-start-receipts.md)。原 PG 创建互斥保护 Goal，但 Temporal 初始 Activity 尚会无限重试 typed conflict，且旧 Activity 在返回后才覆盖 workflow ID。同一 start 在已创建/暂停后重试不能识别原请求。0088 固定实际 Activity workflow ID、bound proposal/编译请求摘要、原 Goal 与 scope；回执和完整 Goal 同一 PG 事务、追加式保存，复合外键禁止后续投影改绑 controller。不补造旧记录。

同工作流的 paused/blocked 或终态重放重新授权原请求后只回读，不重复图、审计、proposed/kickoff 或确认。pending/running 重放显式要求执行恢复，不凭启动身份重发工具。Worker 对已知冲突返回 metadata-only `_start_error`，Gateway 还原 application 类型化结果，失败者 Workflow 不接受 resume。API 并发失联、公开请求幂等、dispatch outbox、创建/审计/Outbox 全事务和图内崩溃/owner fencing 继续待交付，原完整 P0-P6 目标不缩减。

已结束的当前证据：新增冲突复现 **3 failed / 0.49 秒**（`agent-start-receipts-red-20261008.log`）；首纯组 **23 passed / 1.43 秒**。扩大纯组 **2 failed / 174 passed / 2.86 秒**，两项为旧 DDD 文本要求随机 workflow ID 和事后投影；改为内部持久身份与禁止改绑后 **176 passed / 3.01 秒**。组合层发现未透传内部 keyword 后修复 callback，补完整应用链专项；当前纯 application／适配器与 DDD／Portal／Compose／隔离存储 **286 passed / 3.91 秒**（`agent-start-receipts-current-pure-boundaries-20261008.log`）。

真实 PG／私有 MinIO 首轮专项 **37 passed / 145 deselected / 1 warning / 28.16 秒**（`agent-start-receipts-pg-first-20261008.log`），包含回执只追加、七类原状态、改变摘要、失败者无回执、事务回滚、controller FK 与原公开竞争场景，但早于组合 callback 透传修复。当前完整接线专项 **14 passed / 6.59 秒**（`agent-start-receipts-composition-pg-minio-20261008.log`），验证真实保存意图创建、只读重放和变预算拒绝，原 Goal/回执不变。各批范围独立，不累加为项目总数。

当前真实 PG／私有 MinIO 回执及迁移专项 **16 passed / 5.85 秒**（`agent-start-receipts-migration-final-pg-minio-20261008.log`），含完整组合接线、真实 0088 空表升降级、旧 Goal 不补造回执及有回执时拒绝降级。只迁移隔离测试数据库。

实际 Temporal／PG／私有 MinIO 专项 **9 passed / 1 warning / 225.82 秒**（`agent-start-receipts-temporal-final-20261008.log`）。新增五项覆盖相同/不同保存计划的并发创建、暂停后 Activity 故障重试、图启动前故障的显式恢复要求、伪造 workflow ID 拒绝及真实 history replay；另四项复验原 resume/追加阶段。失败者 Workflow 已完成，服务端拒绝其后续 signal，不进入 resume 等待；pending/running 恢复仍不是自动执行接管。

固定干净 exweb 的当前持久启动入口 **1 passed / 4 deselected / 1 warning / 96.82 秒**（`exweb-agent-start-receipts-wired-pg-minio-20261008.log`）。对应 `exweb-agent-start-receipts-wired-20261008-durable.json` 核验原 Goal、新阶段独立确认、旧步骤/根计划不变及两次启动只读重放；原生 **755 entities / 1425 relationships**，初始与补源阶段各 **2 index / 2 MCP**，重放新增 Provider/模型调用为 0。私有 MinIO 独立 hash 回读 **134 次 / 3,515,434 字节**，覆盖 4 manifests、129 文件和 1 frozen image。该入口使用真实本地 LangGraph/PG，不冒称此 exweb 场景本身经过 Temporal；Temporal 恢复由上一专项验证。需求/测试仍是伴随 fixture，不是业务 gold，也没有目标程序执行。

保留失败历史：首实际 Temporal 批 **8 failed / 388.49 秒**（`agent-start-receipts-temporal-first-20261008.log`）定位到组合 callback 不接受 `start_identity` keyword；修复透传并增加完整组合测试。随后 `-x` 批 **1 failed / 1 warning / 8.35 秒**（`agent-start-receipts-temporal-wired-20261008.log`）是测试误认为已完成 Workflow 仍接受 signal，按实际 SDK 的 completed RPC 拒绝修正断言。修复前已加载的 exweb 五入口批 **1 failed / 4 passed / 1 warning / 406.52 秒**（`exweb-agent-start-receipts-pg-minio-20261008.log`），持久入口因同一 callback 错误失败；上面的当前单入口复验不将该失败批改写为五项全绿。

Portal build/lint/i18n 退出 0，contracts **322 passed / 0 failed / 1.15 秒**（`agent-start-receipts-{build,lint,i18n,contracts}-20261008.log`），主包 **944.01 kB** 告警保留。独立 PG／私有 MinIO smoke **success**（`agent-start-receipts-smoke-20261008.log`）。浏览器 **16 passed / 4.3 分钟**（`agent-start-receipts-browser-20261008.log`），覆盖保存意图、构建计划和补源修订；移动端浅/深色截图已查看，无样式改动或横向溢出。浏览器批加载早于 callback 修复，其本地入口不验证新的 Temporal 启动身份。

扩大数据库批 `agent-start-receipts-expanded-pg-minio-20261008.log` 已终态退出 0：**336 passed / 1 warning / 767.29 秒**；加载早于 callback 修复和后加的迁移测试，不声明该批验证了这两项后续改动。以上分组范围独立、不累加为项目总数；兼容回归不证明旧画像生成链 cutover、完整性能/容量或最新完整 V1 已绿色。完整 P0-P6 继续保留。

## 同目标追加构建阶段（0087，2026-10-07）

新增[原目标的追加式构建阶段](./image-plan-phases.md)：0086 已确认补源修订可以独立准备并确认到原 AgentGoal；原根计划、历史步骤、工件和授权不覆盖。追加式 PG ledger 固定 root/revision/manifest/parent phase 的 ID/hash、原完整 checkpoint、旧步骤 prefix、目标 baseline/version 和本阶段工作合同。确认阶段仅停在 `build_plan_phase_prepared`；显式继续准备新的预算 gate，用户另行确认后才授予新计划一次结构构建许可。旧授权和旧快照不能确认或消费新许可。

阶段、完整 goal 更新、审计及 Outbox 同事务，重验当前权限、原结构已完成命令与不可变工件；不能用仍 blocked 的历史审阅步骤否定已保存的工件，也不能改目标版本来绕过原 pin。完成回执恢复须再次匹配原输入/结果。只读历史 `private, no-store`，最多 80 阶段/512 步，断链、超界、篡改与当前撤权均拒绝；不补造历史阶段。

Portal 保留草稿、准备阶段、显式继续及预算确认四个不同动作。修复阶段刷新导致子组件卸载丢失展开状态，以及 Overview handler 只接受 `waiting_confirmation`、忽略 `build_plan_phase_prepared` 的实际空操作；仍传原展示完整 goal，不自动确认下一 gate。控制区失联隐藏旧操作，只有经核验回读才能恢复。没有改全局 CSS、token 或图标。

终态证据如下；选择集重叠，不累加为项目总测试数：

- 后端真实 PG/私有 MinIO 扩大回归 **358 passed / 1 warning / 709.75 秒**（`image-plan-phases-final-regression-pg-minio-20261007.log`），覆盖阶段/修订/原目标恢复、认证、身份管理、API/config、DDD 与 Compose。另有纯阶段/修订/边界组 **170 passed / 1.46 秒**（`image-plan-phases-final-pure-20261007.log`）。开发业务库未迁移。
- 新增阶段与既有原目标的真实 Temporal/PG/MinIO 专项 **2 passed / 1 warning / 82.28 秒**（`image-plan-phases-real-temporal-current-pg-minio-20261007.log`）：Worker 停止后新 Worker 接管、阶段消费事务成功后注入 Activity 故障并重试、真实 workflow 收到重复旧 pin、预算 gate 前零新授权/工件、独立确认后恰好一项授权/工件、同 goal/旧步骤与根计划不变、独立调查至完成审阅、Workflow history replay。这是受控 Worker stop/recreate 和 Activity 故障，不是 OS SIGKILL、跨主机或全部 P2 恢复分支演练。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、实际 CBM CLI/MCP、LangGraph PG、独立 PG/私有 MinIO **1 passed / 1 warning / 89.11 秒**（`exweb-image-plan-phases-final-pg-minio-20261007.log`）。同前缀 JSON 核验同一原 goal 执行新阶段且历史不变，原生 **755 entities / 1425 relationships**；初始两个代码 binding **2 index / 2 MCP**，新阶段再次 **2 index / 2 MCP**，历史回读额外 Provider 调用 **0**。独立远程 hash 回读 **134 次 / 3,515,357 字节**，覆盖 4 manifests、129 文件和 1 frozen image。伴随需求/测试是明确测试样例，不是维护者规范或业务 gold；模型调用 0，未执行 exweb、Maven 或目标依赖。
- 最终真实 PG/MinIO 浏览器 **12 passed / 0 skipped / 4.0 分钟**（`image-plan-phases-source-pinned-browser-pg-minio-20261007.log`）：新阶段 light/dark/390px、阶段与草稿回执丢失、原目标独立调查及聊天确认、辅助刷新阻塞、POST 前检查点竞争。新阶段夹具不调用旧可变上下文物化，但保留真实来源采集、构建与全部断言；其余兼容场景仍保留旧物化。移动端预算 gate 两种主题截图已查看，明确展示四项限制。
- 实际 handler 补 **12 项**：准备阶段的已核验回读、失联单 POST、权限/错误 scope、辅助缓存阻塞及三类错误暂停状态拒绝。当前 Portal contracts **286 passed / 0 skipped**（`image-plan-phases-current-portal-contracts-20261007.log`）；build/lint 退出 0（`image-plan-phases-current-portal-{build,lint}-20261007.log`），i18n 通过。主包 **933.11 kB** 告警保留。
- 单独重复旧调查回执丢失场景 **3 passed / 1.1 分钟**（`image-plan-phases-lost-ack-repeat-pg-minio-20261007.log`）；没有修改该场景、放宽超时或自动重试写入。当前 DDD/Portal 边界 **145 passed / 1.33 秒**（`image-plan-phases-current-boundaries-20261007.log`），隔离 PG/私有 MinIO smoke **success**（`image-plan-phases-current-smoke-pg-minio-20261007.log`）。八份主要方案/记录的 184 个本地链接与锚点、代码围栏和 `git diff --check` 通过。

保留失败历史，不把重跑当作完整门禁：最初结构 target guard 用了步骤 completed，专项 **16 failed / 6 passed**，改为核验完成命令/不可变工件；prepared 审计 status 不在 DTO 枚举中导致读取 500，改为实际 paused 并补回读断言。首轮浏览器 **3 failed / 9 passed**，后续两批各 **2 failed / 10 passed**，包含刷新卸载、handler 空操作、最终响应刚好超过 30 秒，以及一次旧调查回执丢失后的按钮回读超时。新阶段取消约 7 秒的无关旧物化，未延长超时或删除断言；本次 12 项通过不抹去该偶发回读记录。首次 Temporal **1 failed / 1 passed / 63.12 秒** 为测试选到了末尾 pending step 而非阶段内 blocked 授权，修正选择和实际字段名后复验通过，未放宽生产预算门禁。

旧 V1 的 6 项身份管理失败涉及测试全局删除用户，与不可变 actor 外键冲突；已取消夹具全局删库，扩大 358 项组包含该测试。另两项旧失败涉及 verifier/边界断言修正。分组复验不能替代新的 `verify:v1-release` 全量终态。重复三次通过也不证明偶发回读超时的根因已确定，尚未完成的容量/高并发 SSE 恢复门禁仍保留。全部本轮测试进程已终态退出，测试运行器清理各自临时 PG/私有 MinIO；`dev:status` 显示正常 Portal/API/Runner/Worker 均 stopped，开发业务库未迁移。

全计划多能力费用/授权、完整 BuildIntent/动态调查/反证、其余 owner fencing/恢复、P0 Provider 对照/gold/隔离/性能、P1 lineage/多格式/cutover、P3 authority/语义 gold、P4 全量 delta/overlay/合并、P5 五用途/旧链/RunPlan/真实运行反馈及 P6 灾备/安全/试点继续保留原验收范围。

## 同目标补源计划草稿（0086，2026-10-07）

新增[补源计划修订契约](./build-plan-revisions.md)：原暂停 AgentGoal、根计划、父修订、原展示完整 goal 快照和明确 source manifest 共同固定新的 enrich 提案。保留已采集修订，新增来源必须 captured；不改 objective/purpose/预算，不替换已固定代码。PG 追加式修订、计划、自有审计和 Outbox 同事务，完整 checkpoint/父节点条件写及确认期限阻止旧快照、并发 fork 和旧授权复用；当前来源撤权拒绝私有回读，完成命令必须匹配原修订 pin/结果。

Portal 在现有计划弹层中提供折叠的补源草稿入口，通过领域命令接口准备和独立确认；列表重新读取原目标，显示同目标修订。补源控件默认未勾选，失联隐藏旧内容，不自动确认或重发。目标发现当前最多 20 条且无分页，历史链最多 80 条完整返回，不把有界查询称为全项目覆盖。

0086 增量只保存草稿：新计划无 execution/publication grant；原 goal、steps、候选工件和授权保持不变。当时未交付的同目标执行阶段与独立重新授权由后续 0087 接入，见上节；完整恢复策略和 P2 验收仍未完成。

本轮独立终态证据，选择集重叠，不累加为项目总测试数：

- 纯领域与真实 PG/MinIO API 最终专项 **17 passed / 53.84 秒**（`build-plan-revisions-final-contract-pg-minio-20261007.log`）：连续两条修订、原 goal 不变、未转移授权、幂等回执、过时预算/步骤/状态、提交前撤权与事务回滚、实时历史 ACL、并发 fork 拒绝、提交后回执恢复、UPDATE/DELETE 拒绝、空/非空迁移保护和完成命令 source/parent/result 错配拒绝。迁移只在独立测试库/schema执行。
- 原扩大 PG/兼容组 **377 passed / 2 failed / 1 warning / 506.80 秒**（`build-plan-revisions-expanded-pg-minio-20261007.log`）。两项失败均为新增 route 直接调用 platform 确认 API，已将操作迁入领域命令接口，原测试未放宽；独立 DDD/Portal 边界复验 **145 passed / 1.66 秒**（`build-plan-revisions-final-boundaries-20261007.log`）。扩大组加载在后来新增并发/迁移/回执负测前，不将分组结果拼接为同一完整门禁全绿。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、真实 CBM CLI/MCP、LangGraph PG、独立 PG 与私有 MinIO 最终复验 **1 passed / 1 warning / 96.36 秒**（`exweb-build-plan-revisions-resource-policy-pg-minio-20261007.log`）。同前缀 JSON 核验原 goal 连续两条需求/测试补源修订、原步骤/授权不变；exweb 原生投影 **755 entities / 1425 relationships**，初始两个代码 binding 合计 **2 index / 2 MCP**，补源及历史回读额外原生调用 **0**。独立远程 hash 回读 **134 次 / 3,412,419 字节**，覆盖 4 manifests、129 source files 和 1 frozen image。伴随文档是明确测试样例，不是 exweb 维护者的规范或业务 gold；未调用外部模型、执行 exweb 或新计划。
- Portal 实际 TypeScript API 契约增加 **33 项**，当前整组 **240 passed / 0 skipped**（`build-plan-revisions-domain-command-contracts-20261007.log`），覆盖无缓存回读、根/父计划与 digest、重复/断链/超界、改变的目标、错误确认回执及失联不重发。i18n 通过（同前缀 `-i18n-20261007.log`）。
- 最终真实 PG/MinIO 浏览器批 **5 passed / 0 skipped / 2.0 分钟**（`build-plan-revisions-domain-command-browser-pg-minio-20261007.log`），包含原计划两种主题和新修订深浅色/390px、16px checkbox、无横向溢出/隐藏滚动条、确认前禁用、刷新保留历史、确认已提交但回执丢失时隐藏旧控件且零自动重试。移动端截图已查看；未改全局 CSS/token。
- Portal build/lint 均退出 0（`build-plan-revisions-domain-command-{build,lint}-20261007.log`），保留 **923.36 kB** 主包告警。隔离 smoke **success**（`build-plan-revisions-domain-command-smoke-pg-minio-20261007.log`）。

保留本轮失败证据：首两次 API collection 为 Python 3.9 union annotation 与 Optional 导入位置错误；修正后初批 **13 passed**，后续增加并发/迁移/回执负测再到最终 17 项。Portal 首 build 为可选 `target_refs` 类型错误，修正后通过；控制字符正则触发 lint，改为字符码检查保留原拒绝条件，不禁用规则。最初 exweb 报告错误使用 `index` 计数键导致报告零值，功能断言已通过但该计数不可靠；最终两轮改为真实 `index_repository` 并核对持久投影，初始报告和日志保留，不拿旧计数作性能证明。

开发业务库未迁移，正常 API/Portal/Runner/Worker 最后检查均 stopped。当时旧加载完整 V1 72444 曾观察到 91%；它后来已失败退出，终态见本文开头，不再称 live。0086 自身不覆盖完整 BuildIntent、同目标新执行阶段、全计划费用/授权/动态调查；后续 0087 的有界接入不缩减 P0-P6 剩余范围和原验收标准。

## 原用户快照、消费回执与聊天确认（0085，2026-10-07）

公开恢复 API 新增完整 `expected_goal` v1，固定画像缺失预条件返回 428、过时/非法快照返回无私有详情的 409。Portal 的预读取不替换原展示预算/工具输入；原快照规范化为五字段 scope/hash，贯穿 Local、LangGraph PG、Temporal signal 和 Activity。生产 Loop 拒绝固定画像的 bodyless 信号，队列严格 schema；旧错误投影不阻止新有效请求，当前请求错误仍明确拒绝。

新增 append-only `agent_resume_consumptions`：原结构继续的完整步骤条件写与 digest 消费同一 PG 行锁事务，防止并发重复和恢复旧 paused 快照后的 ABA；记录只有 scope/hash，不复制私有 DTO、不补造历史消费。已消费快照重放可以恢复已提交 running 步骤，但不能确认独立调查 gate。真实 Temporal 使用 PG 业务状态作为返回权威，不将旧 Workflow cursor 覆盖回数据库。

补齐聊天入口兼容：原聊天“确认”会调用新的固定画像 Loop 拒绝的旧 bodyless driver。现在通过明确 application port 回读 goal，核对当前会话/项目、唯一 blocked acting step、工具和 invocation，固定计划捕获检查点后经同一恢复 port 传递。错误/过时工具不替换成新确认；无 goal 的独立工具和非固定旧计划仍走既有 canonical/恢复入口。聊天 pin 是服务器解析确切当前命令后的快照，不能冒称用户已提交原展示完整 DTO。

已核验的独立终态批次，范围重叠、不累加为全项目测试数：

- 接入固定画像 Worker bodyless 拒绝后的真实 Temporal/PG/迁移/HTTP/Local/LangGraph/认证/API/config/Compose/DDD 扩大组 **342 passed / 1 warning / 307.13 秒**（`agent-resume-user-pin-worker-final-pg-20261007.log`），加载于聊天修复前。真实 Worker A 停止、B 接管、结构提交后注入故障导致 Activity 重试，恢复同一 goal/回执；重复、排队后预算变化、bodyless signal 拒绝、新有效 pin 和 Workflow history replay 均有断言。Worker stop/recreate 不是 OS SIGKILL 或跨主机演练。
- 固定干净 exweb + 实际 CBM CLI/MCP + PG/LangGraph PG + 私有 MinIO 两入口 **2 passed / 1 warning / 140.15 秒**（`exweb-investigation-resume-worker-final-minio-20261007.log`）。同前缀两份 JSON 新增实际消费回执及独立确认前、完成后旧快照重放断言；仍为 755 entities/1425 relationships、每入口 2 index/2 MCP、130 个独立远程 hash 核验，不重启 Provider。
- 聊天修复后纯消息/adapter/状态摘要/Worker/DDD 组 **231 passed / 2.93 秒**（`agent-resume-chat-unit-20261007.log`），含错误 goal/会话/项目、旧 invocation、错误工具、多 blocked、错误暂停原因、预算并发、legacy 与独立 canonical 兼容。首批公共 HTTP/原目标组 **19 passed / 1 warning / 59.76 秒**（`agent-resume-chat-http-pg-20261007.log`），覆盖 Local/LangGraph PG 真实异步消息 POST/Turn 完成、非成员 403、原 goal/工具不变；加载于新增公共聊天预算竞争测试前。
- 聊天修复的原生 exweb/私有 MinIO 复验 **2 passed / 1 warning / 142.03 秒**（`exweb-investigation-resume-chat-minio-20261007.log`）。同前缀 `-original-goal.json` 明确 `independent_confirmation_channel=chat_public_turn`，实际 HTTP 消息 POST/Turn 查询确认原调查命令；直接调查入口保持显式 resume。消费回执、旧快照重放、130 个远程核验和 Provider 调用计数不变，仍有代码-only/业务 oracle/执行/发布缺口，停在 `build_completion_review`，未调用外部模型、执行 exweb 或建立业务 gold。
- 当前 Portal contracts **186 passed**、边界 **20 passed**、i18n 通过（`agent-resume-chat-final-{contracts,portal-boundaries,i18n}-20261007.log`）；隔离 smoke **success**（`agent-resume-chat-final-smoke-20261007.log`）。聊天修复后的原六项浏览器范围 **6 passed / 1 skipped / 1.2 分钟**（`agent-resume-chat-final-e2e-20261007.log`），含 light/dark/390px、GET/POST 竞争、失联只读恢复；未设置原生 exweb 浏览器环境的那一项明确 skipped，另由上述实际原生测试验证，不冒充同一浏览器批通过。
- 最终扩大 PG 复验 **346 passed / 1 warning / 334.18 秒**（`agent-resume-chat-final-pg-20261007.log`），包含新增的 Local/LangGraph PG 公共聊天预算竞争：实际消息 POST 已接受，但 driver 前检查点变化使 Turn 失败，保留新预算与原待确认命令，不创建调查事实。新增真实浏览器聊天入口后 **7 passed / 1 skipped / 1.3 分钟**（`agent-resume-chat-browser-final-20261007.log`）；页面发送确切命令的确认消息，POST 返回 202，同一原 goal 到完成审阅，刷新保持，浏览器未旁路发送 resume。移动端深浅色截图已查看；该批 exweb inspector 仍是显式 skipped。
- 当前 Portal build/lint 均退出 0（`agent-resume-chat-final-{build,lint}-20261007.log`），主包 **915.53 kB** 告警保留；未修改全局 UI/CSS/token。

真实 Temporal 首版和第一修复批各 **1 failed**（`agent-resume-user-pin-real-temporal-20261007.log` 和 `-repair1-20261007.log`），分别为测试 assembly 使用不存在的 projector、proposal 缺必需 description；仅修 fixture，不弱化生产校验。第二修复及后续 342 项组通过，失败日志保留。原 Portal contract 对旧 one-arg helper 的断言也曾失败；改为验证真实 GET+显式快照 POST 后 186 项通过，没有删除旧兼容测试。

本轮仅隔离测试库迁移到 0085，开发业务数据库未迁移，正常 API/Portal/Runner/Worker 保持 stopped。范围仍只是结构继续条件消费、检查点传递和特定恢复/聊天入口；普通 goal 写入、治理 admission/dispatch、所有恢复分支尚无统一 CAS/owner fencing，goal 事实/审计/Outbox 未全部同事务。扩大 PG 和新增实际浏览器聊天批已确认终态成功；完整旧加载 V1 72444 本轮再次核验仍 live，到 41% 后继续输出，保留到真实结束，专项不替代完整门禁。

完整 P0-P6 继续保持：Provider 隔离/对照/gold/性能、来源 cutover/lineage/多格式、BuildIntent/补源同目标/全计划预算/动态与反证调查、全链原子恢复、自动 delta/overlay/合并、五用途/旧链切换/脚本/RunPlan/真实执行反馈及业务试点均未按本增量收缩。

### 非确认恢复与 exweb 浏览器复验（2026-10-07）

新的真实 PG 负测先复现 **12 failed / 2 passed / 0.90 秒**（`agent-nonconfirm-resume-red-20261007.log`）：显式检查点通过后，无调用预算释放和补源重试仍普通覆盖 goal；并发预算、步骤输入、中断或 workflow 变化可能丢失，且没有消费回执。现将预算释放完整状态经条件 port 提交；补源重试把 running 转换、原 invocation 清理和 attempt 递增合并到一次条件提交，不先写 running 再写步骤。CAS 失败不写恢复步骤事件；条件提交后失联从原回执恢复，不重复递增或确认下一 gate。

- 首批分支/PG CAS/迁移 **32 passed / 1.11 秒**（`agent-nonconfirm-resume-first-pg-20261007.log`），包括并发拒绝、重建 repository/graph、提交后故障和 unpinned legacy 兼容。直接 PG 准备测试使用可控事件端口，不冒充公共 HTTP 或完整事件事务。
- 自然耗尽步骤预算的固定画像公开 API，经实际 budget PATCH、显式 resume、Local/LangGraph PG 到独立结构确认，首批 **8 passed / 1 warning / 13.49 秒**（`agent-budget-resume-http-first-20261007.log`）。重放原预算快照不确认下一命令；提交前并发变化返回 409，保留当前状态及命令数量。新增提交后故障恢复和非法 attempt 的最终批继续独立核验。
- 当前消息/adapter/checkpoint/Worker/DDL 边界纯组 **224 passed / 1.99 秒**（`agent-nonconfirm-resume-boundaries-20261007.log`），含明确要求两个分支传递原 pin、补源只能一次状态提交的 AST 检查；不是全项目测试数。
- 此前 skipped 的固定 exweb inspector 本轮显式启用，独立 PG + 随机私有 MinIO 桶 **1 passed / 1.7 分钟**（`exweb-current-inspector-browser-minio-20261007.log`）。确认干净 `fe5827f6b76f77ef34918d8b452ee823142332dc`，静态归档 126 文件（120 parsed/6 unsupported）、13 条精确注解路由、726 对象/546 代码成员/1944 推断关系；真实浏览器展开 `ChatController.java:20-45` 的归档字节、确认固定结构并恢复授权详情。截图已查看。该批明确 `NASUS_CODE_GRAPH_MODE=disabled`，使用 Tree-sitter 静态解析，不冒充实际 CBM/MCP；原生 CBM 两入口证据在上文单列，也不据此宣称业务 gold 或执行覆盖。
- 当时 Portal build/lint/i18n 和 **186** contracts 已通过（`agent-nonconfirm-current-{build,lint,i18n,contracts}-20261007.log`）；真实 PG/私有 MinIO smoke 已终态 success。新增故障恢复/非法 attempt 后的扩大 PG 批 **370 passed / 1 warning / 351.56 秒**（`agent-nonconfirm-resume-final-pg-20261007.log`）。读取性能与后续浏览器复验见下节，不把当时批次冒充最新完整门禁。开发业务库未迁移，没有启动正常开发服务或执行目标仓库依赖。

这不是完整原子恢复或 BuildIntent 补源业务实现。无 blocked step、治理确认及 admission/dispatch、其他失败/耗尽分支、全部事件与事实同事务、全局 write epoch/owner fencing 尚未接齐；完整 P0-P6 和旧全量 V1 原进程保持，不以新专项范围替换验收。

### 调查回读、范围查询与前端确认锁（2026-10-07）

调查历史回读接入一次 operation 的固定元数据复用，原文/hash 与实时 ACL 不缓存；首轮相同三文件 PG/私有 MinIO 浏览器 **8 passed / 4.4 分钟**（`investigation-replay-io-combined-browser-minio-20261007.log`），扩大回读/原目标/非确认恢复 PG 批 **73 passed / 1 warning / 272.06 秒**（`investigation-replay-io-expanded-pg-minio-20261007.log`）。随后发现 goal explanation 的调用/审计查询先授权所有全局历史，再做目标过滤。新增负测先 **8 failed / 7 passed**，现改为先按既有 scope 条件筛选，选中记录继续原实时授权，创建时间只读一次审计列表；不改公开 API、排序语义或无筛选入口。纯查询/访问测试 **33 passed**（`goal-query-scope-{red,unit}-20261007.log`）。全局元数据扫描仍在，不能据此声明 SQL 分页或容量/p95 完成。

- 实际 PG/MinIO HTTP fixture 先因同一活跃会话不能新建平行 goal 两次失败（首批 **1 failed / 19 passed**、第二批 **1 failed**），改为另一真实项目/会话/goal，未更改生产单活跃目标约束。最终 **1 passed / 9.82 秒**（`goal-query-scope-http-pg-minio-repaired-20261007.log`），目标 explanation 仅授权自己的 3 个回执/21 个审计，非成员和来源撤权仍 403、重新授权后可读；0.267 秒只是一次记录，不是 p95。
- 范围修复后加载的 API/config/HTTP scope/恢复/调查/证据/访问/DDD/Compose 扩大 PG/私有 MinIO 批终态 **390 passed / 1 warning / 590.39 秒**（`goal-query-scope-expanded-pg-minio-20261007.log`），保留 LangGraph serializer 告警。各批范围重叠，不相加为全项目数量。
- 固定干净 exweb、实际 CBM CLI/MCP/PG/LangGraph PG/私有 MinIO 两入口 **2 passed / 1 warning / 117.41 秒**（`exweb-investigation-scoped-read-minio-20261007.log`）。同前缀两份 JSON 保留 `fe5827f6b76f77ef34918d8b452ee823142332dc`、755/1425、每入口 2 index/2 MCP、130 个独立远程 hash/3,408,896 字节核验；原目标入口实际走 `chat_public_turn`。重放不重启 Provider、旧 pin 不确认新 gate，仍停在 `build_completion_review`，无外部模型、目标执行或 business gold。
- 同三文件实际浏览器随后 **7 passed / 1 failed / 4.4 分钟**（`goal-query-scope-browser-minio-20261007.log`）。Trace 证明丢失继续回执时 resume 约 0.89 秒已提交、会话已读到新 waiting_confirmation，但 project 辅助 GET 挂起使 action lock 仍等待整页刷新。未放宽 5 秒断言，改为先严格回读当前会话/原 goal scope，再后台刷新辅助面板；读取失败隐藏旧控制快照，原展示 pin 和独立确认协议不变。
- 新前端单位 fixture 首版故意持有无 resolver 的辅助 promise，两个确切测试进程被终止，不记为成功；有界 red 批 **2 failed / 12 cancelled**，新增缓存失败负测另 **1 failed / 20 passed**。当前真实 handler/hook 单位测试 **21 passed**（`goal-checkpoint-refresh-final-unit-20261007.log`），覆盖两入口、失联单 POST、挂起/失败辅助查询、读取拒绝、错误项目/会话/goal 和缓存失效。首次 Portal build 因旧 TS 会话类型漏后端已有 project_id 失败，补齐 nullable 字段后最新 build/lint 退出 0、contracts **207 passed**、i18n 通过；主包 **915.89 kB** 告警保留，未改全局样式/视觉 token。
- 首轮仅调查继续文件的 PG/MinIO 浏览器 **6 passed / 2.2 分钟**（`goal-checkpoint-refresh-browser-minio-20261007.log`），新增实际挂起 project GET 且丢失回执的回归：下一独立确认与完成审阅都不等辅助面板，仍只发两次用户显式 POST。该批第二选择模式无匹配，不冒称预算浏览器覆盖。最新 build-plans/exweb-analysis/investigation-continuation 三文件批终态 **9 passed / 4.3 分钟**（`goal-checkpoint-refresh-final-browser-minio-20261007.log`，5970 退出 0），实际启用固定干净 exweb，没有 skipped 或加长既有断言超时。13 条精确注解路由、归档原文及固定候选/授权读取通过；此浏览器使用 Tree-sitter 静态适配器，不冒称 CBM/MCP，两入口原生证据在上文单列。最新 light/dark/390px gate 与 exweb inspector 截图均已查看，无布局回退。
- 当前 DDD/Portal/Compose/隔离存储边界 **176 passed / 1.20 秒**（`goal-checkpoint-refresh-boundaries-20261007.log`）；最新 PG/私有 MinIO smoke 已终态 **success**（`goal-checkpoint-refresh-final-smoke-minio-20261007.log`）。测试使用随机私有桶和一次性 PG，开发数据库未迁移；dev:status 仍显示 Portal/API/Runner/Worker stopped。

旧完整 V1 72444 再次核验仍 live，到 62% 后继续输出，旧 6% 与 47% 失败保留在原批；加载早于当前生产修复，不因观察超时重启、不宣称当前完整 V1 绿色。完整 P0-P6 的 Provider 隔离/对照/gold/性能、来源 cutover/lineage、BuildIntent/补源/全计划预算/动态调查、全链原子恢复、自动 delta/overlay/合并、五用途/旧链切换/脚本/RunPlan/真实运行及业务试点仍未完成。

## 固定证据调查与原目标继续（0084，2026-10-07）

新增 append-only `image_investigation_revisions`，固定原 plan/goal/image/hash、父修订 CAS 和实际证据 pins；每轮最多 8 项、每项最多 20 行，保留有界样本与明确缺口。三轮无新增画像或证据后暂停，不用旧证据重排/子集制造进展，不生成假覆盖率或业务批准。原结构候选 goal 显式继续后完成旧 blocked 步骤并追加调查步骤，保留原 goal/invocation；调查仍须自己的 canonical 确认。独立确认后回读工件，按完整参数去重追加只读任务，结束于 `build_completion_review`，不完成或发布。完整契约见[调查修订](./evidence-investigation-revisions.md)。

Portal 首次继续前重读原 goal，控制状态不符则禁写；响应丢失后仅重新读取，不自动重发。浏览器回归暴露历史 SSE 会将最新 goal 或 step 覆盖为旧结构 gate，造成控件重建和错误检查失败。现在 goal/step 状态只来自最新查询，文字 delta 只延长已有展示字段，不能修改状态、工具输入或确认引用；正常消息 token 仍流式追加。纯 reducer 另拆专用模块，保留原主 reducer 的 80 行边界。局部确认卡片已验证 dark/light 和 390px，无全局视觉 token 重设计。客户端校验尚不等于服务端跨客户端条件恢复 CAS。

已核验的独立批次：

- 原目标/调查、权限/错误 pins、父 CAS/无进展、终态 fence、迁移/原子回滚及结构/DDD 扩大 PG 组 **249 passed / 1 warning / 177.63 秒**（`investigation-original-goal-final-pg-20261007.log`）。API/config/固定 Agent 计划/Compose 兼容另批 **172 passed / 1 warning / 180.96 秒**（`investigation-continuation-final-compatibility-20261007.log`）；保留 LangGraph serializer 告警，两批不累加成全项目测试总数。
- 固定干净 exweb + 实际 CBM + PG/LangGraph PG 两入口 **2 passed / 1 warning / 59.86 秒**（`investigation-continuation-final-native-20261007.log`），保留 755 个实体/1425 条关系、每入口 2 次 index/2 次 MCP、实际 8 项证据，最终仍待审阅。报告明确 local object adapter、无外部模型/目标执行、非 business gold。
- SSE 回归先出现 **2 failed / 9 passed** 的浏览器批；只修 goal 重放后仍 **1 failed / 8 passed / 1.2 分钟**（`investigation-replay-fixed-browser-20261007.log`）。继续查明旧 step 更新覆盖了 blocked 工具后，完整相关浏览器 **11 passed / 1.5 分钟**（`investigation-checkpoint-replay-final-browser-20261007.log`）。最终专用 reducer 拆分后的同三文件复验 **11 passed / 1.3 分钟**（`investigation-checkpoint-modular-browser-20261007.log`），含 light/dark/移动端、原 goal/invocation 保留、独立确认、刷新、丢失继续回执、结构任务恢复/停止。已查看移动端继续和完成审阅截图，没有降低断言或加长超时。
- 最终 Portal contracts **185 passed**（`investigation-checkpoint-modular-contracts-20261007.log`），含新增 10 项历史 goal/step 重放测试；边界 **145 passed / 2.10 秒**（`investigation-checkpoint-replay-modular-boundaries-20261007.log`）；build/lint 通过，主包 **915.45 kB** 告警保留（`investigation-checkpoint-modular-build-20261007.log`）。独立 PG smoke **success**（`investigation-checkpoint-replay-final-smoke-20261007.log`）加载于专用 helper 拆分前，不冒充整个最新 V1 批。

此前完整 V1 `structure-discovery-current-v1-release-20261007.log`（30410）已终态退出 1：**7 failed / 3349 passed / 30 skipped / 1 warning / 13368.67 秒**，后端加载早于 0083/0084。未继续执行后续 Provider、备份、完整 E2E 或 Docker 门禁。当前复验旧失败五文件为 **1 failed / 32 passed**，唯一剩余是非成员访问的旧 200 断言；生产拒绝仍为 403。按原负测/发布回填顺序重现 **1 failed / 1 passed**，根因是负测篡改已归档 Tool 输入后未恢复，污染同库全局 provenance 回填。仅修测试契约及 finally 恢复，保留生产 fail-closed 与原负测；当前同顺序扩大六文件 **42 passed / 273.82 秒**（`context-command-order-final-20261007.log`），不等于最新全量门禁已通过。

新增测试运行器显式 `--minio`，随机私有测试桶与开发工件隔离，端点/凭据必须单独声明，成功创建的桶才可清理；无效端点、隐式开发凭据、创建失败、测试异常与分页清理的 **14 项单测通过**（`isolated-minio-harness-unit-20261007.log`）。实际 PG/MinIO/CBM/LangGraph PG 的原生 exweb 两入口批 `exweb-investigation-minio-20261007.log`（80937）已终态退出 0，**2 passed / 1 warning / 122.26 秒**；每入口独立 S3 核验 **2 清单、127 文件（126 个 exweb 文件及 1 个原 fixture 文件）、1 画像、130 个唯一远程引用**。对应 JSON 与 `-original-goal.json` 保存真实 storage backend/hash 结果，755/1425、2 index/2 MCP 和原目标/缺口/不发布不变；仍无外部模型、真实 Temporal Goal 重启或目标执行，不冒充完整业务试点或性能 gold。测试桶退出清理成功。

真实 MinIO 来源/权限批先 **5 passed / 14.54 秒**（`source-evidence-real-minio-20261007.log`），增加匿名 SDK 读取负测后 **6 passed / 1 warning / 15.50 秒**（`source-evidence-private-minio-20261007.log`）。同一私有桶对象经认证读取正确，匿名 SDK 读取返回 403/AccessDenied；HTTP 成员撤权、错误修订及原文篡改拒绝仍保留。保留 Boto3/Python 3.9 告警；不是全量 ACL 或模型出口测试。

新完整批中两个旧认证测试清空全库用户，触发新增不可变调查记录的 actor FK。精确原顺序重现 **2 failed / 10 passed / 34.18 秒**（`auth-append-only-order-red-20261007.log`）；仅改为独立随机账号，保留真实外键/历史，不弱化删除约束。新增历史保留回归首版使用错误 PK 字段，批次 **1 failed / 12 passed / 36.83 秒**（`auth-append-only-order-fixed-20261007.log`）；修为实际 session_id/binding_id 后 **13 passed / 1 warning / 42.98 秒**（`auth-append-only-order-final-20261007.log`），核验原身份、会话/角色、私有调查与原 hash 不被新注册测试破坏。扩大兼容批 **1 failed / 209 passed / 217.07 秒**（`auth-history-current-compatibility-20261007.log`），仅验收脚本测试仍匹配旧参数；加入实际 MinIO 隔离单测后更新精确参数断言，未移除任何门禁，脚本契约/隔离测试 **31 passed**。

完整 V1 `investigation-minio-current-v1-release-20261007.log`（72444）本轮再次确认 live，后端到 29% 后仍有进展，6% 的旧失败仍在原批日志中。它加载早于上述认证/契约修复和下面的条件继续提交增量；保留同一进程直至真实终态，不用新专项覆盖其失败或宣称完整 V1 绿色。所有 Provider、备份、完整 E2E/smoke/Docker 门禁保持。

### 条件继续提交增量（2026-10-07）

新增固定 AgentGoal v1 摘要与独立 application commit port，生产 PG 条件写入在同一 row lock 事务内比较完整状态并保存全部步骤；不能将检查点写到其他 goal/project/conversation/workflow，不能重新创建已删除目标，不接受不消费 paused 状态的写入。原结构候选的继续先捕获摘要再准备后续步骤，实际提交使用条件 port，不再普通 upsert；缺配置拒绝。失败在 HTTP 转为无私有详情的 409，不创建下一调查调用。具体边界见[条件继续提交](./evidence-investigation-revisions.md#结构继续提交的条件写入)。

- 初版摘要/PG/跨 repository 组 **60 passed / 0.81 秒**（`agent-resume-checkpoint-pg-20261007.log`），含真正并发的一个成功/一个 stale、全步骤回滚与保留原检查点。接入原 Local/LangGraph PG、原目标/崩溃恢复/权限和 Agent/DDD 后 **252 passed / 1 warning / 39.79 秒**（`agent-resume-checkpoint-integrated-pg-20261007.log`）。
- 实际 HTTP 在编译完成与提交之间并发改变预算、输入、invocation 和 interrupt，Local/LangGraph PG 共 **8 passed / 1 warning / 19.58 秒**（`agent-resume-continuation-races-20261007.log`）；新状态保持、未新增调查 canonical 命令。完整摘要字段/规范 SHA-256/JSON 预算/缺 port 拒绝及代码边界最新 **207 passed / 1.88 秒**（`agent-resume-checkpoint-current-boundaries-20261007.log`），不是全项目总数。
- 当前最终扩大 PG 兼容批 **283 passed / 1 warning / 242.69 秒**（`agent-resume-checkpoint-current-compatibility-20261007.log`），覆盖新增摘要/条件 repository/HTTP 竞争/边界、原目标恢复、认证历史、API/config/Agent 计划及 Compose 契约。前一扩大批的旧验收参数失败已在此批复验，保留原失败日志，不混同于完整 V1。
- 当前真实 exweb + MinIO/PG/CBM/LangGraph PG 两入口 **2 passed / 1 warning / 128.09 秒**（`exweb-investigation-checkpoint-cas-minio-20261007.log`）；同前缀 JSON 和 `-original-goal.json` 均固定干净 `fe5827f...`，755 entities/1425 relationships、2 index/2 MCP、130 个独立远程 hash 核验，仍停在 `build_completion_review`，历史重放不重启 Provider。没有外部模型、目标执行或业务 gold，不能用此结果宣称全部自主构建已完成。
- 本轮 Portal build/lint 均退出 0，contracts **185 passed**（`agent-resume-checkpoint-portal-{build,lint,contracts}-20261007.log`），主包 **915.45 kB** 告警保留。未修改前端样式；最新浏览器三文件 11 项是上方已记录的 helper 拆分后批，不伪称为本轮重新运行的 E2E。

本增量只完成结构后续准备的原子状态提交，尚无公开 expected-checkpoint DTO、跨 Temporal signal/activity 和治理确认的完整预条件、持久恢复回执/去重，普通 goal 写入尚非全局 CAS，goal 事实与后续 audit/Outbox 仍分事务。服务端旧页面确认下一 gate 的窗口、所有恢复分支、完整事务事件与本目标 P0-P6 全部要求继续保留。专项不能代替仍在运行的旧加载完整 V1 批，更不能代替修复后完整门禁。

仅隔离测试库迁移到 0084，正常开发 API/Portal/Runner/Worker 仍 stopped，开发业务库未迁移。完整 P0-P6，尤其 Provider 隔离/对照/gold/性能、来源 cutover/lineage、多格式、完整动态调查和全计划预算、原子恢复确认、自动 delta/overlay/合并、五用途/旧链切换/脚本/RunPlan/真实执行反馈及真实业务试点继续待交付。

## 独立结构停止与私有状态（0083，2026-10-07）

新增独立 `system_image.build.structure.cancel` 和 append-only `image_structure_cancellations`；不沿用原结构命令的确认，固定原 invocation/plan/digest/target 和 command hash，重新核验当前 reviewer 与来源范围。排队或待确认取消无需已有 native generation；活跃 Worker 收到意图后先退出线程再落终态，已提交候选优先返回 `already_committed`，不删除事实。取消意图/原命令终态/审计/Outbox 同事务，候选提交读取相同锁及意图。完整契约见[独立结构停止](./code-graph-execution-control.md#独立结构停止0083)。

只读 status GET 不调度/claim/续租，`private, no-store`；保存的停止 Tool、审计与幂等回放仍要求当前完整来源权限，共享广播删除 input/result/幂等字段。Portal 增加明确停止勾选和操作，刷新不保留勾选，变化/错误禁写；丢失停止回执只重读原状态，不自动重复 prepare/confirm。重核验保留控件但禁用操作，沿用既有主题与弹层；仅为新 checkbox 补局部 16px/flex 样式，避免继承输入框的全宽规则，不改全局 token/生产路由。

已核验的终态证据：

- 首批扩大 PG 组 **4 failed / 175 passed / 127.18 秒**（`structure-cancellation-complete-pg-20261007.log`），保留实际失败。诊断复验 **179 passed / 124.44 秒**，未稳定复现这四项。随后消除 canonical API 确认时间与 PG 租约时钟混用的风险，加入 60 秒时钟差与过期/未来确认负测；不将该风险未经证明地认作四项失败的唯一根因。
- 当前加载最终代码的 PG 组 **195 passed / 200.68 秒**（`structure-cancellation-clock-final-pg-20261007.log`），覆盖停止 API、当前私有状态、权限/伪确认/错误 pins、重放、活跃清理顺序、过期 owner、提交竞争、晚期 scope 失败事务回滚、0083 空/有历史迁移，以及原 job/结构/发现/lifecycle/DDD 回归。之前 **194 passed / 187.02 秒** 是时钟同源修复前的批次，不混用加载版本。
- 当前真实 Temporal + 固定干净 exweb **3 passed / 55.43 秒**（`structure-cancellation-clock-native-temporal-20261007.log`）。Git 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`；排队取消 **0 次** native index/MCP，活跃 session 和提交后停止各 **2 次**真实 native index/**2 次** MCP。原输入不变、单一原终态审计、replay/终态重读不调用 Provider；活跃 session 等待清理后 cancelled，提交后仍 completed 且候选保留。三份 `exweb-structure-cancellation-clock-temporal-20261007-stop-*.json` 明确标注 local object adapter、未运行 exweb/外部模型、非 business gold、未证明真实 CBM 子进程强杀。
- 最后 PG 浏览器 **8 passed / 57.0 秒**（`structure-cancellation-consent-final-browser-20261007.log`），含原 build-plan/结构恢复回归、停止权限读取失败、显式刷新、独立确认/原 ID 与 key、刷新清除勾选、停止确认回执丢失只读恢复，light/dark 与 390px。加入 checkbox 16px 几何断言，已查看操作前后的 light/dark mobile 截图，无横向溢出。前一批失联修复验证 **8 passed / 1.1 分钟**；首次误选不存在的 plan spec 时只运行匹配的 **6 passed**，随后改为实际 `build-plans.spec.ts` 完整取证，不补造首批范围。
- 当前 API/config/Agent 固定计划/Compose 兼容 **177 passed / 1 warning / 204.81 秒**（`structure-cancellation-current-compatibility-pg-20261007.log`），保留 LangGraph serializer deprecation 告警。这与 195 项是独立、重叠范围，不累加成项目总测试数。
- Portal build/lint/i18n、完整 contracts **156 passed**、Portal 边界 **20 passed** 均通过；最后 build 保留 **911.50 kB** 主包告警。时钟同源和回执失联重读修复后的隔离 smoke **success**（`structure-cancellation-ack-final-smoke-20261007.log`）；最后 checkbox 局部排版由上述浏览器批验证，不将各批拼成一次全量 V1 验收。

此阶段曾观察完整 V1 `structure-discovery-current-v1-release-20261007.log`（30410）运行到后端 38%；该进程之后已失败终止，准确终态、根因复验和新完整批见上方 0084 记录。它加载于 0083 新增前，专项不能代替完整门禁，当前 V1 未声明通过。

仅隔离测试库迁移到 0083，开发业务数据库和正常开发服务未修改/启动。本轮不完成旧 inline 进程崩溃后的终态恢复、真实 native SIGKILL/遗留资源清扫、孤立物理对象 GC、其他能力取消/租约或整个 AgentGoal 恢复。完整 P0-P6、Provider 隔离/对照/gold/性能、来源 cutover/lineage、动态全计划预算、统一脚本/RunPlan DAG、自动 delta/overlay/合并、五用途/旧链切换和真实目标运行反馈继续保留。

## 结构任务持久调度与页面恢复（0082，2026-10-07）

0082 将固定结构任务接到真实 Temporal Workflow/Activity。原 canonical confirmation 返回 `200 / status=running`；在调度前先以 PG 事务登记原命令、confirmer、完整请求和 command hash。调度回执丢失不重发业务命令，由 reconciliation 继续交付同一 Workflow。结构 Activity 独立队列，避免等待中的 Agent Activity 占满 Worker；PG 时钟租约、owner/epoch 和候选提交 fence 阻止旧 Worker 迟到写入。

每次尝试回读原计划、来源、目标、确认时间及当前账号/ACL，不重置原 wall budget。原 work item 的一次业务授权与 Temporal 基础设施重试区分；已提交候选决定 completed，消息确认失败不能重跑 Provider。取消 Activity 先停止并等待所属线程，再交还租约；这不等于已实现独立业务 stop 或强杀资源清扫。具体契约见[结构任务恢复](./code-graph-execution-control.md#结构任务调度与恢复0082)。

Portal 修复了只向 input 传幂等键、未向 canonical Runtime 传顶层键导致的重复命令。现在丢失回执后重试原键/原输入，pending/running 轮询 PG，不把排队当作失败；读取失败停止写动作，须显式刷新。新增 `/build-plans/{plan_id}/structure-commands` 有界只读分页，仅发现当前账号发起的手动命令；固定 plan digest、完整来源权限，按创建审计过滤后再分页，不调用全局 invocation 列表、不 dispatch/claim/续租。刷新/重新打开恢复原 target、input key 和 invocation，详情重新核验后才可确认；多命令由用户选择，不自动确认。旧无键命令只按原 ID 恢复，不能补造新幂等键或新授权。

已核验的终态证据：

- 真实 Temporal + exweb 的直接 Tool 和 AgentGoal 两入口 **2 passed / 1 warning / 120.36 秒**（`structure-jobs-agent-temporal-20261007.log`）。固定 Git `fe5827f6b76f77ef34918d8b452ee823142332dc`，各入口实际输出 **755 entities / 1425 relationships**；工件写入后注入一次 OSError，真实 attempts/epochs **1→2**，各 **4 次原生 index / 4 次 MCP 协商**，重试投影相等、原确认不变、单一 canonical 命令/候选/完成审计/Outbox，历史重放不调用 Provider。Agent 使用真实 LangGraph PG checkpoint，在排队期保持 running，终态停在 `structural_candidate_review`；不是整个 AgentGoal Temporal Workflow 的进程重启测试。
- 上述两个报告 `exweb-structure-jobs-agent-temporal-20261007-tool.json` 和 `-agent.json` 明确标注隔离本地 object adapter、未运行目标、未调用外部模型、非 business gold。两种入口的 projection hash 分别固定，不要求跨项目 ID/hash 相同；本轮不把原生 partial/gap 清成 complete。
- 结构任务/迁移/生命周期/ReleaseReadiness 当前组合 **42 passed / 79.33 秒**（`structure-jobs-complete-repaired-pg-20261007.log`）；平台/API/Agent/发布迁移/DDD/Compose **307 passed / 1 warning / 205.17 秒**（`structure-jobs-current-platform-agent-pg-20261007.log`）；当前来源追溯专项 **52 passed / 463.41 秒**（`structure-jobs-current-provenance-pg-20261007.log`）。各批独立取证，不累加重叠测试为全量通过。
- 初版发现/结构任务/固定计划/DDD 组合 **158 passed / 68.76 秒**（`structure-discovery-pg-20261007.log`）。新增 top-level-only 键测试初跑 **1 failed / 24 passed**，实际 Runtime 已规范化键到保存的 input，修正测试为精确原键核验；最新同范围加迁移、真实 queued 只读保护的完整批 **162 passed / 71.51 秒**（`structure-discovery-final-pg-20261007.log`），包含 11 项发现 API 测试。
- 当前浏览器初批 **6 passed / 52.1 秒**（`structure-discovery-complete-browser-20261007.log`），含真实 PG 重新加载原命令、零自动确认/零重复写、未知状态显式刷新、两命令选择和 light/dark；补 390px 后完整同组 **6 passed / 47.7 秒**（`structure-discovery-mobile-browser-20261007.log`），已查看 light/dark 移动截图、检查弹层边界，无横向溢出。queued 表现是浏览器交付控制；真实 Temporal 另由上述原生测试证明。
- Portal build/lint/i18n、**125 项**完整 Portal 契约、**20 项** Portal 边界及隔离 smoke **success**（`structure-discovery-smoke-20261007.log`）均通过。prepare/read/confirm 的 20 项和 discovery 的 14 项契约分别覆盖原 pin、缺键拒绝、旧无键确认和分页/游标/跨范围拒绝；它们已计入 125 项，不重复累加。保留约 **905 kB** 主包告警。

旧完整 V1 批 70630 已经 **1 退出**：**14 failed / 3007 passed / 25 skipped / 1 warning / 10871.06 秒**（`retrieval-provenance-current-v1-release-20261007.log`），不再是运行中。它加载的是先前版本；后端非零阻断后续 Provider/恢复/全量浏览器/Docker 门禁，不能用上述专项拼成 V1 全绿。最新 `structure-discovery-current-v1-release-20261007.log` 已启动，进程 30410 的当前结果仍需核验；运行中不等于通过。

仅隔离测试库迁移到 0082，发现接口无需新 DDL；开发业务库和正常开发服务未修改/停止。完整 P0-P6 保持原范围：其余能力的恢复/业务取消、完整动态调查及全计划预算、Provider 隔离/强杀清扫/CodeGraph 对照/gold/性能、来源 cutover/lineage、统一脚本/RunPlan DAG、自动更新/overlay/合并、五用途/旧生成链切换以及真实目标运行反馈仍待交付。

## 公开代码索引生命周期与 Portal（2026-10-07）

新增[公开生命周期契约](./code-graph-execution-control.md#公开生命周期与当前来源权限)：三个 canonical Tool 提供来源范围的 generation 发现、当前状态和独立确认式取消；两个 GET 只读 PG 元数据，不启动 Provider、重建索引或续租。状态区分原命令、原生会话和 Worker 租约；未知计数保持 null。当前 reviewer 的 `can_cancel` 只提示界面能力，写动作仍重新授权、核对 generation hash，并通过 ToolInvocationRuntime。

取消与结构候选提交共享项目/原命令锁：运行中请求由 Worker 确认，owner 缺失或过期可落到 cancelled；已提交返回 `already_committed`，不删除画像事实。发现/状态/取消的原 Tool、审计及幂等回放重新核验当前来源权限；项目共享 Conversation/Outbox 仅广播脱敏状态，不暴露来源 pins、完整输入和结果。历史广播读取不重写已存事件。

实际负测发现，无权确认的用户会先 claim 别人的待确认命令，使其失败。Runtime 改为 claim 前授权与回放权限检查，执行阶段仍保留再次检查。红测 `code-index-confirmation-preservation-red-20261007.log` **1 failed** 后，PG viewer/tester 负测验证原待确认命令逐字段不变，owner 仍能独立确认。

Portal 在来源分析面板按需展开索引历史，十项分页、固定 generation 状态、刷新与确认式取消；刷新期间隐藏详情但保留选择，撤权清空旧内容和写控件。确认绑定完整 pin、epoch 和本次查询结果，重核验或变更后清除；取消不自动重试。沿用既有深浅色 token、细边框和隐藏滚动条，未改 CSS/生产路由。旧状态回执缺少 `can_cancel` 时默认 false，不能把历史读取当作当前取消权。

- 当前 API/索引/来源/结构/读模型及固定 exweb 隔离 PG `code-index-ui-final-api-pg-20261007.log` **71 passed**（103.62 秒）；平台/API/runtime/Compose/DDD `code-index-ui-final-platform-pg-20261007.log` **297 passed / 1 warning**（167.39 秒）。后者加载于 legacy `can_cancel=False` 默认值补充之前；该最后兼容调整由下面纯契约覆盖，不能将它混成同一加载版本的 PG 全量验收。
- 最终纯契约/权限/Runtime/事件/Agent/DDD/Portal `code-index-ui-final-pure-20261007.log` **266 passed**（2.51 秒），含旧回执读取不授予取消权。此前纯测试选择误把 SQL adapter 测试放到无 PG 环境、旧 spy 仍期望一次权限检查，记录 **2 failed / 234 passed**；实际 SQL 测试改用隔离 PG，spy 按新增前后检查修正，没有改业务数据库类型或削弱权限负测。
- legacy 默认值补充后的当前 `code-index-ui-legacy-current-pg-20261007.log` **53 passed**（33.78 秒），实际隔离 PG 覆盖 lifecycle domain/API、私有回执和 SQL project-access adapter。它补充最后兼容调整的证据，不与早批 297 项拼成一次当前全量运行。
- Portal contracts `code-index-ui-final-contracts-20261007.log` **91 passed**，涵盖错误来源/hash/游标、状态/协议/计数自相矛盾、当前权限与 epoch 漂移、canonical 确认及终态竞争。首批 **1 failed / 88 passed** 是 mock 返回对象与请求共用引用，负测修改结果也改了预期；返回真实 JSON transport 等价副本后通过，生产校验未放宽。
- 当前 PG 浏览器 `code-index-ui-final-browser-20261007.log` **9 passed**（41.3 秒），含新索引入口与原来源分析、light/dark/390px、held-request 详情隐藏与选择保留、viewer 控件隔离及来源撤权。两张 `output/playwright/code-index-{light,dark}-mobile-20261007.png` 已目视核对，无横向溢出。新索引生命周期夹具明确使用生产 PG repository 登记的协议状态，不执行 native Provider；不冒充实际 exweb 原生浏览器验收。
- 实际 canonical HTTP 构建报告 `exweb-code-index-ui-final-api-20261007.json` 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 和两个代码来源，**2 次实际原生协商 / 2 次索引调用，755 实体 / 1425 关系**。snapshot 为 `sha256:8bfd773e13d8f322b1e765e94785e77b3e0a64393285f3ef171a81fba9709bb8`，本批 exweb projection 为 `sha256:39ddbf91e675524b3e0d5c80a4544845f331876375b2bf1da6106bdf987ab5f4`；元数据查询不启动 Provider，提交后取消保留事实。独立恢复报告 `exweb-code-index-ui-final-recovery-20261007.json` 验证 epoch 1→2、两次重建完整投影相等及旧游标拒绝；该批 projection 为 `sha256:fdf48a8501f1f65571230da29d33b3f4a3a11fc5198348064d58a8f64af1a24c`，不混用两批 UUID/hash。
- 两份实际 native 报告均使用 local object adapter，无外部模型或 exweb 执行/business gold；结果仍 partial，CLI 0.8.1 / MCP 0.10.0 和工具声明缺口保留。Portal build/lint/i18n 已 0 退出，主包 **899.60 kB** chunk 告警保留；最终隔离 smoke **success**。各选择集重叠，不相加为项目总测试数。

本增量无需新的 DDL，仅测试库迁移到 0081；开发业务库及正常开发服务保持未修改/停止。当时旧加载完整 V1 进程 70630 到 **92%** 且已有失败；现已 **1 退出 / 14 failed / 3007 passed / 25 skipped**，完整终态及新批见上文，不再报告为 live。公开 reopen、其余业务 Workflow 恢复、强杀清扫/隔离、原生完整能力与对照/gold/性能，以及完整 P0-P6 其余范围仍待交付。

本节同步的三份进度/执行控制/交付文档检查通过：**82 个本地链接**（含章节锚点）、代码围栏和行尾空白；`git diff --check` 无错误。专项浏览器/smoke 临时服务端口已关闭，未启动正常开发服务。

## 原生契约与命令固定（0080-0081，2026-10-07）

新增[实际 MCP 协商与命令固定](./code-graph-execution-control.md)：0080 在真实索引之前执行有界 initialize/initialized/tools-list 对话，并将消费字段 schema 和原生回执固定到 PG；不把声明或成功握手当作语言/结果完整性证明。实际 CLI 0.8.1 与 MCP server 0.10.0 不一致、namespace/query format 未声明均保留明确 gap。0081 修复正常 open/register 重试可绕开 reopen 检查的问题，同 invocation/binding 唯一约束与命令锁禁止 Provider/source 替换；独立确认的新命令和同命令多来源仍允许。历史歧义拒绝迁移，不删除或重写原事实。

- 最终索引/来源/结构 PG 专项 `code-index-command-pin-complete-pg-20261007.log` 已 0 退出，**50 passed**（54.12 秒）。覆盖实际并发、正常命令重试、源修订/Provider 替换拒绝、同命令不同来源、数据库约束及有数据/歧义迁移；早期真实失败和夹具修正日志保留。
- 同批固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`，报告 `exweb-code-index-command-pin-complete-20261007.json`：**2 次实际协商、2 次原生重建、755 实体/1425 关系、partial**；两目录/epoch 1→2，完整投影相等，旧游标拒绝。原文 hash `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`，本批投影 hash `sha256:f436475c1d94a5449bebfff9e8e7d9a964b25f24536393a5175c1311fefc74b3`。使用 local object adapter；未调用外部模型、执行目标或获得业务 gold。
- 纯契约选择集 `code-index-command-pin-pure-20261007.log` **374 passed**（14.34 秒）；加载 0081 的平台/API/runtime/Compose/DDD `code-index-command-pin-final-platform-pg-20261007.log` **297 passed / 1 warning**（164.92 秒）。独立 native gate `code-index-command-pin-final-provider-gate-20261007.log` **7 实体/8 关系、passed**，不是大规模或完整能力门禁。
- Portal refetch 曾卸载 report selector，丢失历史报告选择并取消详情请求。修复只在相同键下保留实例，重新授权期间隐藏内容，失败或范围变化仍清空。最终浏览器 `code-index-command-pin-final-source-e2e-20261007.log` **10 passed**（41.6 秒），含实际 held-request 重核验/选择保留、来源/项目撤权、深浅色与 mobile；未改 CSS/token/路由。
- Portal build/lint/i18n 通过，保留 **887.59 kB** 主包告警；Portal 边界 **20 passed**，既有 contracts **54 passed**，最终 smoke **success**。这些选择集重叠，不相加为项目总数。

只迁移隔离测试库到 0081，开发业务库和正常开发服务未修改。完整 V1 同一进程 70630 核验时仍 live，后端显示到 66% 且有失败，不能声称全绿，也未因观察超时重启。原完整 P0-P6 范围继续保留。

## PG 持久代码索引与重建（0079，2026-10-07）

新增[持久代码索引契约](./code-graph-execution-control.md#pg-持久登记与重建恢复0079)：PG 固定 source binding/revision、manifest、批准字节快照、实际 native executable/adapter/grammar-policy 指纹和 canonical invocation。独立可变租约以 PG 服务器时钟、45 秒续约和递增 epoch 阻止双 Worker 或旧 owner 提交；generation、attempts 和首次完整候选投影摘要追加式保存，事实与 Outbox 同事务。确认式 `system_image.build.structure` 已消费这一实现；内部 reopen 从确切归档重建，不依赖原 mutable 目录或旧原生缓存，不复用旧会话游标。

- 首批 PG `code-index-generation-first-pg-20261007.log` 为 **1 failed / 6 passed / 1 skipped**（4.75 秒），暴露被拒绝的旧游标误把正常租约标为 failed；修正参数错误与真实 Provider/控制错误的状态区分。首批纯契约 **167 passed**（5.46 秒），不是后续完整投影 pin 的证明。
- 固定 exweb 第一批原生恢复 **1 failed / 7 passed**（8.70 秒），诊断及排序后的复验仍失败。完整 equality 断言发现 Provider 返回顺序变化及 Java 库函数 IMPORTS 误映射；修正稳定顺序、同名端点 ambiguity，并在持久原生候选读取中消费原有语法 import/package/声明核验，而不是放宽到只比较数量。修正后的早期专项 **8 passed**（9.19 秒）。
- 增加首次投影 pin、原子 Outbox 回滚、实际 OS Worker kill/新进程恢复和真实 HTTP 确认式结构构建后，最终隔离 PG `code-index-generation-final-pg-20261007.log`（92857）已 0 退出，**44 passed**（58.48 秒）。OS kill 使用三秒测试租约，生产仍为 45 秒；原生投影改变、来源撤权、Provider policy 改变和跨项目访问均拒绝，旧 epoch 不能清掉新 owner 的租约。
- 同批固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 报告 `exweb-code-index-generation-final-20261007.json` 核验同一 PG generation、两个不同归档恢复目录及 **2 次**实际 CBM `index_repository`，完整结果相等，旧游标拒绝。候选为 **755 实体 / 1425 条原文复核后的关系**，仍为 **partial**；不是前批未经 Java 复核的 1542，也不是组合分析的 2346。投影 hash 为 `sha256:c21a2eb203ea626357925583840401d0de7d46d32d1f53e8160dac6d311664ac`。使用 local object adapter；没有调用外部模型、运行 exweb 或得到独立业务 gold。
- 当前 domain/session/Provider/来源/结构/上下文及边界选择集 `code-index-generation-final-pure-20261007.log`（95843）已 0 退出，**350 passed**（14.61 秒）。平台/API/runtime/Compose 兼容 `code-index-generation-platform-pg-20261007.log` 终态 **172 passed / 1 warning**（153.86 秒），保留 LangGraph serializer 告警。独立原生 Provider gate 为 **7 entities / 8 relationships、passed**，仅证明该双文件探针。
- Portal build（36801）/lint（85467）已 0 退出，保留 **887.34 kB** 主包告警，未改 CSS/token/路由。来源分析/证据 PG 浏览器专项（18510）**10 passed**（40.8 秒），不是完整 durable-native UI 验收；独立 smoke（20976）为 **success**。选择集重叠，不累加为项目总测试数。

只迁移独立测试库到 0079，开发业务库与正常开发服务不修改。完整 V1 同一进程 70630 本轮仍 live，后端已到 44% 并保留旧加载失败，不重启、不以专项拼接声称全绿。待交付的业务 Workflow 自动恢复、强杀目录/逃逸子进程清扫、公开生命周期、跨主机完整依赖锁定/账号禁网资源隔离/原生协商、两 Provider/gold/性能，以及来源 cutover/lineage、动态调查/累计预算、delta/overlay/合并、五用途/旧链切换、脚本/RunPlan/实际运行反馈全部保持原范围。

## Worker-owned 原生索引会话（2026-10-07）

原分析入口已切到实际 `PreparedCodeIndexPort`：先构建一次私有原生索引，独立读取固定候选页、定位和保守影响，最后释放资源。状态区分 pending/preparing/ready/degraded、取消请求/确认、failed/closed，尚未读取时数量为 null；游标绑定会话/集合/digest 并在错误范围触发原生查询前拒绝。每个操作保留当前来源/预算 callback，取消信号进入所属进程组，包括等待 Provider 锁的情况。候选 ID 不冒充 Nasus 稳定实体，影响始终 incomplete；完整说明见[执行边界](./code-graph-execution-control.md)。

- 首批兼容回归 `code-index-session-first-compat-20261007.log`（53459）为 **2 failed / 95 passed**，重复规范化路径的新错误类型误变成 ValueError，已保留旧 CodebaseMemoryError 契约。首批会话专项（93779）为 **2 failed / 10 passed**：closed 被误判取消，且归属边与依赖边按统一方向遍历。修正 closed 状态和关系语义后同相关组（39651）**109 passed**（10.42 秒），未降低影响断言或放宽旧验证。
- 后续首次扩大命令误写不存在的测试文件，`code-index-session-final-contracts-20261007.log` 记录 **no tests ran / exit 4**；修正实际文件选择后才执行。最终同批会话/domain、Provider/进程/定位/快照/结构/上下文与 DDD/身份/Compose 组 `code-index-session-verified-pure-20261007.log`（51677）已 0 退出，**335 passed**（12.55 秒）。覆盖 scope/计数/生命周期负测、双集合分页/游标隔离、原文变更、实时撤权、原生 degraded、待准备/排队及真实协议子进程取消、KeyboardInterrupt 和资源清理。
- 扩大 API/runtime/结构/证据/Compose 的实际隔离 PG 组 `code-index-session-api-pg-20261007.log`（51451）已 0 退出，**199 passed / 1 warning**（203.43 秒）；它启动早于游标范围和候选 ID 的最终收紧，保留 LangGraph serializer 告警。收紧后的当前结构构建/来源证据/分析 API 组 `code-index-session-final-pg-20261007.log`（88734）已 0 退出，**27 passed**（34.41 秒），不把两批拼成一次全量新版验收。
- 固定 exweb 原生 `codebase-memory-mcp 0.8.1` 的最终探针 `exweb-code-index-session-verified-20261007.log`（89396）已 0 退出，**1 passed**（8.78 秒）。同名 JSON 固定原提交和 126 单元/原始内容 hash；三次组合分析仍为 **942 实体/2346 关系、13 条语法路由**。另一个真实已准备的原生索引只建立 **1 次**，**755 个候选实体/1542 条候选关系** 分别读 **8/16 页**，ChatController 保留 exact 定位，保守影响 **3 个候选、complete=false**；显式取消阻断后续读取，全部四组私有根/缓存清理。
- 上述原生会话数量在组合 Java import 校验之前，1542 不冒充已准入的 1425 条 CBM 关系，更不是独立语义 gold、覆盖率或目标执行。report 的 `native_candidates_before_composite_validation_not_accepted_knowledge` 和 `worker_owned_session` 明确限定范围。探针使用归档恢复输入及本地 object adapter/180 秒预算，没有外部模型、PG 用户批准或运行 exweb 应用；单次耗时不是 p95。
- 当前 Portal build（99546）/lint（82787）与国际化校验均 0 退出，保留 **887.34 kB** 主包提示。来源分析/证据实际 PG 浏览器专项 `code-index-session-e2e-20261007.log`（9380）**10 passed**（41.7 秒），保留原 light/dark/390px、授权/XSS/分页与展开完整性测试；已查看移动端展开截图，未改 CSS/token/路由。隔离 smoke（44315）为 **success**；原双文件 native Provider gate 0 退出、**7 实体/8 关系**，不是 exweb 全链路验收。

无需新增 DB migration 或公开写入口/Tool ID，开发业务库与正常开发服务不修改。这个已接入的 Worker 会话是持久 v2 的实现基础，不替代 PG 持久 handle、跨重启/Worker 租约与取消、原生功能协商、独立账号/禁网/资源限制、两 Provider/gold 对照或性能门禁。完整 P0-P6、来源 cutover/lineage、动态调查/全计划预算、项目 delta/维护/overlay/合并、五用途/旧链切换、脚本/RunPlan 和真实运行反馈全部保持。

本轮复核原完整 V1 进程 70630 仍 live，后端输出到 **37%** 后有新进度且已有旧加载失败。没有因观察等待而重启、终止或将专项拼成 V1 成功；最终门禁仍未通过。

## 代码能力与完整性报告（2026-10-07）

能力与结果元数据现在独立于自由文本 evidence：语法/CBM/组合适配器只声明实际 Nasus 操作及真实限制，未知能力不补造；禁用、未配置、optional 失败和解析失败后的跳过保持可见。新 `nasus.code-analysis.v2` 报告与旧 v1 共同追加保存，PG FK/hash 和即时来源授权不变；Portal 按需显示读取、定位和具体缺口，沿用原样式。契约见[代码图执行边界](./code-graph-execution-control.md)。本轮无需迁移开发业务库，不新增 Tool ID、Provider 任务权威或业务规范批准。

- 首轮相关回归（42151）终态 **15 failed / 72 passed**，共同原因是新版本字段误用纯标识符约束，拒绝合法 `codebase-memory-mcp 9.9.9`；已改为有界、无控制字符的版本元数据并保留恶意字段负测。首轮 PG 日志 `code-provider-metadata-pg-20261007.log` 在收集阶段有 **3 errors**，FastAPI/Pydantic 在 Python 3.9 无法解析新 `dict | None`，改为既有 `Optional` 写法，没有安装额外依赖。首版 Portal build 因新增重复 `Unavailable` 翻译键失败，移除本轮重复项、保留已有翻译。
- 扩大后最终纯契约、结构/Provider、进程/快照、DDD/身份/Portal/Compose 组 `code-provider-metadata-final-pure-20261007.log`（33662）已 0 退出，**314 passed**（10.19 秒），包括未知/近似/截断不能伪造 complete、能力不触发 probe、预算 gap、上限边界、缺 Provider 的空能力、新旧报告和严格元数据负测。
- 真实隔离 PG 结构构建/来源证据/分析 API 专项 `code-provider-metadata-pg-compatible-20261007.log`（15555）已 0 退出，**27 passed**（37.15 秒）。新报告实际由原 canonical materialize 产生；验证分页/header 保存类型化 metadata、旧 v1/hash 与新 v2 共存、同内容幂等以及伪造完整状态拒绝。后续扩大 API/runtime/Compose 与最新小修复另行复验，不拼接为同一批。
- 原生 exweb 首次 metadata 探针（28366）已 0 退出，三次 **942 实体/2346 关系、13 语法路由、14 关系查询** 一致，新投影整体为 partial。报告 `exweb-code-provider-metadata-20261007.json` 记录语法 **6 个不支持 grammar 的输入**，CBM **9 合成路由/365 调用/117 Java import 排除项**及 **662 个未解析端点行**。这些是本次读取缺口计数，不是独立关系 gold、业务正确率或已修复目标仓库。原始内容 hash 仍为 `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`；归一化 Provider ID/digest 只验证同一恢复根三次分析，不能冒充跨环境的 Nasus 稳定身份。使用本地 object adapter/探针预算，无外部模型或目标执行。
- Portal build（12817）和 lint（2467）已 0 退出；build 保留既有大 chunk 提示。首次更新后的真实来源分析/证据浏览器专项 `code-provider-metadata-e2e-20261007.log`（85312）已 0 退出，**10 passed**（37.8 秒），包含新 partial/能力/gap 展开与原深浅色、移动端、分页、原文 XSS 和撤权。实际 PG、语法解析/归档与报告读取，不是原生 CBM 浏览器或完整 E2E。新增展开状态移动端检查和扩大门禁的终态另记。
- 后续扩大 metadata API/runtime/Compose PG 组 `code-provider-metadata-final-api-pg-20261007.log`（17289）已 0 退出，**199 passed / 1 warning**（201.22 秒）。展开状态移动端的当前同批浏览器（39033）**10 passed**（39.9 秒）；原生 exweb metadata（16136）**1 passed**（6.86 秒），三次报告完整 metadata 一致。Provider gate（45972）0 退出、7/8，隔离 smoke（27243）success。上述皆早于后续 Worker 会话实现，保留各批真实范围，不与新结果混为一次运行。

完整 V1 原进程 70630 仍确认 live，日志在 35% 后有新输出且含旧加载版本失败；不因观察等待而重启，也不能声称当前 V1 已通过。Provider v2 持久生命周期/定位/影响/独立取消、原生协商/对照/gold/账号资源隔离、来源 cutover/lineage、动态调查与全计划预算、统一派生/原子项目 delta/自动维护/overlay/合并、五用途/旧链切换、脚本/RunPlan 及真实执行反馈均继续保留为完整目标。

## 代码图受控执行与关系读取（2026-10-07）

新增[代码图执行控制与完整性边界](./code-graph-execution-control.md)。沿用原 Tool/AgentGoal/来源策略权威，传递运行期检查到现有语法/组合/CBM 适配器；受控进程组与输出/time bounds、只含批准原始字节的短路径临时快照、独立私有索引及异常清理均已落地。复制期检查合并到约 250ms，阶段前后强制复核，不缓存跨操作 ACL。

真实 CBM 重复分析暴露合成 Java 路由归属、模糊 `Arrays.stream` 调用目标与 Java import 误关联；现有适配器又丢失合并边的部分原始种类。现在保留全部 raw evidence、读取原生调用 score/strategy/candidates 并隔离未验证观察，Java import 以现有语法观察复核。未验证不是 accepted，也不授予业务/执行 authority。

进一步确认 raw LIMIT 与规范化边数不同：排除模糊行后，旧查询可以漏读后续有效关系却没有截断标记。新增独立 `CodeGraphRelationshipScanner`，使用公开文件/符号谓词递归分区，不发明 offset；饱和父前缀不提交，query budget、最细分区饱和及边数超限明确 partial。完整 v2 capabilities、持久生命周期及独立账号/禁网/CPU/内存仍未交付。

- 快照输入首批负测为 **2 failed / 16 passed**；扩大私有缓存/hash/symlink/race 后为 **11 failed / 13 passed**，部分是协议夹具未声明新缓存要求，不解释为 11 个独立生产漏洞。当前快照和控制测试覆盖原始 CRLF/Unicode 字节、规范化重复、逐 unit 根、文件/目录符号链接及 open-time 替换、success/error/cancel/KeyboardInterrupt 清理、私有索引不删其他缓存和排队取消。
- 关系分区首批 `code-graph-relationship-scan-red-20261007.log` 为 **3 failed / 9 passed**：两个实际漏读场景及尚无 query-budget 配置。首次扩大运行 **27 failed / 52 passed**，确认新模块缺 Python 3.9 的 future annotations，已修正；不把这批解释为原控制失效。协议夹具追加原始行时同步正确返回 `total`，并独立增加坏 count/boolean/schema/row-size 的拒绝测试，不放宽生产检查。
- Python 3.9 兼容修复后控制/观察/分区组 **79 passed**（11.48 秒）；扩大到定位、结构/上下文、DDD/代码身份/Compose 的当前同批 `code-graph-partitions-final-pure-20261007.log`（59175）已 0 退出，**248 passed**（9.82 秒）。原实际 PG 构建授权/取消/策略变化 `code-graph-control-observations-current-canonical-pg-20261007.log`（29679）已 0 退出，**24 passed / 1 warning**（39.80 秒），该批早于分区改动；当前扩大 API/PG 和浏览器门禁另记，不拼接为同一结果。
- 真实 exweb 复验发现共享目录的 Git 工作树含全部 126 文件删除，clean HEAD 断言正确拒绝；未重置该目录或停止其余验证。另建独立固定提交副本后，`exweb-code-graph-partitions-three-analyses-20261007.log`（29839）已 0 退出，**1 passed**（5.71 秒）：126 归档/恢复单元、**942 实体/2346 关系、13 条语法验证路由、每次 14 次关系查询**，三次不同私有根/缓存结果一致且全部清理。仍明确排除 **9 合成路由/365 未验证调用/117 未验证 import**，不靠降低一致性断言通过。
- 同名 JSON 固定 exweb `fe5827f...` 及原始内容 hash `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`。归一化 digest `sha256:8946dff614a67f7b16082d670af06090c7dea8ea42044ed92eb2f77691206941` 只用于本次同来源命名空间重复检查，不是跨隔离环境 gold ID。使用本地 object adapter/探针预算，无外部模型、目标执行或完整 PG/MinIO 用户试点。
- 当前 `verify:code-graph-provider` 已 0 退出（`code-graph-partitions-current-native-provider-20261007.log`），CBM **0.8.1、7 实体/8 关系**，只证明原双文件协议仓库。完整 V1 仍保留原 70630 运行进程和已观察到的失败，不因观察超时重启；这些专项不能替代它的终态或最新版完整门禁。
- 当前扩大 API/runtime/构建授权/Compose PG 组 `code-graph-partitions-final-api-pg-20261007.log`（90871）已 0 退出，**196 passed / 1 warning**（208.73 秒）。这批加载分区实现、早于随后端点收紧；保留 LangGraph serializer 告警，不混成端点修复后的全量结果。
- 端点负测 `code-graph-endpoint-path-red-20261007.log` 为 **1 failed / 1 passed**，确认错误路径被唯一同名符号兜底。移除该兜底，仅匹配根内归一化路径+原生名称；合法私有根内绝对路径保持兼容。最终同范围纯测试 `code-graph-partitions-exact-endpoints-pure-20261007.log`（54993）已 0 退出，**250 passed**（10.20 秒）。收紧后实际 exweb（83530）再次三次一致，**1 passed**、942/2346/13/14，报告 `exweb-code-graph-partitions-exact-endpoints-20261007.json` 固定归一化 digest `sha256:c3410885e3507dd563a3cb6d7e5679ba13cb1fb06efa51e3a05a5cf5b180ca1f`，同样不是跨环境 gold ID。当前原生双文件 gate 再次 0 退出，7/8 不变。
- Portal build（24780）/lint（74146）均 0 退出，保留 **884.59 KiB** chunk 提示；smoke（87044）为 **success**。来源分析/证据分页、恶意标记转义、实时来源策略与成员撤销、深浅色/390px 布局 E2E（65756）**10 passed**（39.5 秒），已查看 mobile light/dark 截图，无横向溢出。浏览器使用既有语法/协议输入及 disabled CBM 隔离配置，不是原生 CBM 端到端或完整浏览器门禁。
- 端点修复后的最新完整结构构建/授权 PG 选择集 `code-graph-partitions-exact-endpoints-pg-20261007.log`（54863）已 0 退出，**24 passed / 1 warning**（39.92 秒）；保留 LangGraph serializer 告警。新查询配置仅增加兼容字段，没有新增 DB migration、公开 Tool ID 或改写已有知识工件。

开发服务保持停止，未迁移开发业务库、未改 UI/CSS/token/生产路由。P0-P6、旧链切换、动态调查/累计预算、统一脚本/RunPlan 依赖、完整项目 delta/自动维护/overlay/合并、五用途、真实运行反馈、CodeGraph 对照/gold/账号与资源隔离及最终 V1 保持原验收范围。

## 固定检索来源依赖登记（0078，2026-10-07）

新增[固定检索来源依赖契约](./retrieval-provenance.md)：三个追加式 PG 表连接原 reservation、完整 generation/documents、trace 与 v5 ContextPack 到确切 publication/成员/父 registration hash；两条原 trace 写路径和新 context 原事务均登记，普通读/恢复/事件只校验、不补造祖先。不修改原 hash、oracle、权限或执行权威。

- 初版领域 **13 passed**；专项 PG **6 passed**（52.77 秒），`retrieval-provenance-first-api-pg-20261007.log`（6931）已 0 退出。原生索引/v5/查询预览兼容 **33 passed**（207.89 秒），`retrieval-provenance-first-compat-pg-20261007.log`（53376）已 0 退出。历史迁移/DDL/坏向量整体回滚 **4 passed**（18.93 秒），`retrieval-provenance-first-migration-pg-20261007.log`（63772）已 0 退出；均早于本轮旧上下文和目标类型加固，不作为最终完整验证。
- 初版实际 exweb 双提交/PG/MinIO `exweb-retrieval-provenance-current-pg-20261007.log`（99404）已 0 退出，**1 passed / 1 warning**（285.11 秒）。报告固定 `cd919569... -> fe5827f...`、Git 原文 **125→126 文件**、**571 条完整索引文档依赖、3 条原生登记、1 条 context/trace 依赖**；来源更新后旧索引/trace/context 和登记摘要保持，旧 context stale，回填幂等。伴随需求/测试和 Orders sentinel 是明确协议资料，native HTTP constant embedding 不是语义 gold；没有外部模型或执行目标。保留 Boto3/Python 3.9 告警；该批早于后续加固。
- 扩大输入负测后 `retrieval-provenance-invalid-input-red-20261007.log` 为 **6 failed / 13 passed**，暴露异常类型和空/超长文档 ID；修正后领域 **19 passed**。旧 v1 归档真实 PG 负测（40138）为 **1 failed / 8 deselected**，确认初版把 `retrieval_bindings=None` 当作 v5 的兼容缺陷；已明确保留 v1-v4 空检索依赖，并增加完整 AC 目标、原事件元数据及命令恢复检查。
- 领域及 DDD/Portal/来源图边界 **190 passed**（1.25 秒），`retrieval-provenance-final-boundaries-20261007.log`（14364）已 0 退出。Portal build（66241）/lint（1560）、国际化与 **54 项** Portal 契约均通过；未改 UI/CSS/token/路由，保留 **884.59 KiB** 主包 chunk 提示。当前 PG/浏览器结果需以最终日志终态为准。
- 扩大归档检查的旧加载批 `retrieval-provenance-final-context-pg-20261007.log`（67060）终态 **19 failed / 36 passed / 2 skipped**（354.55 秒），浏览器（4329）为 **2 failed / 2 passed**。确认事件版本误校验：Outbox 实际在投影前把 `entity_version` 设为持久 sequence，不能固定要求 1。改为核对同一 `event_id` 的原生 Outbox sequence，并保留精确 patch、mutation 和 correlation；不是删除版本检查。修正后专项 PG（24844）**21 passed**（135.00 秒），新增三种事件篡改的整事务回滚（49459）**3 passed / 8 deselected**（23.70 秒），当前边界/领域/Compose（65276）**207 passed**（1.25 秒）。
- 最终相同生产版本兼容组 `retrieval-provenance-current-complete-compat-pg-20261007.log`（27850）已 0 退出，**40 passed / 2 skipped**（302.53 秒），包括旧 v1/v4/v5 归档的实际历史迁移。两项跳过依赖显式 Temporal；随后唯一队列的真实 SDK/Worker 补验 `retrieval-provenance-native-temporal-current-20261007.log`（4533）已 0 退出，**2 passed / 20 deselected**（25.74 秒），验证 dispatch/heartbeat/幂等 workflow 与取消。供应商是明确的 HTTP/停顿协议夹具，不把 SDK 取消当作外部真实模型退款或底层 HTTP 即时取消证明。
- 最终真实 exweb `exweb-retrieval-provenance-final-pg-20261007.log`（54652）已 0 退出，**1 passed / 1 warning**（306.21 秒）；报告 `exweb-retrieval-provenance-final-20261007.json` 核验相同双提交、125→126 Git 文件、**571 条完整文档依赖、3 条原生登记、1 条 context/trace 依赖**，原事实 hash 不变、历史上下文失效和回填幂等。原生索引/已发布上下文浏览器 `retrieval-provenance-event-fixed-native-e2e-20261007.log`（48108）已 0 退出，**4 passed**（1.3 分钟），已查看 390px light/dark 截图，无横向溢出；隔离 smoke（89209）为 **success**。这些专项不是完整浏览器/V1 或语义 gold。
- 原子回滚、AC 类型、完整成员、只读拒绝/恢复、v1/v4/v5 迁移、DDL/hash 外键与边界的当前完整专项 `retrieval-provenance-final-all-pg-20261007.log`（77703）已 0 退出，**20 passed**（108.36 秒）；其中 11 项 API、6 项迁移和 3 项边界，同库同顺序，不拼接早期小组为此结果。
- 平台/API/runtime/SSE 批 `retrieval-provenance-final-platform-pg-20261007.log`（53638）已 1 退出，**193 passed / 1 failed / 1 warning**（185.71 秒）：该进程先加载了要求 bare pytest 的旧静态断言，后来脚本已经改为隔离 PG 运行器。保留此加载时差，不当作当前平台全绿；最新版 gate 断言在下述 95 项 PG 组中通过。脚本在子 shell 读取运行环境，优先使用 `NASUS_RELEASE_TEST_DATABASE_URL`，保留完整原 backend 选择集，由测试运行器创建/迁移/删除 `nasus_test_*`，不迁移开发业务库。

## Agent 工具目录字节预算（2026-10-07）

完整 `npm run verify:v1-release` 批（70630，`retrieval-provenance-current-v1-release-20261007.log`）已实际通过 hygiene、Portal lint/boundary/i18n/contracts/build 和 Runner 测试，并进入完整隔离 PG 后端选择集。该批先加载旧版 Agent 提示；首项失败经独立 PG 复现为工具目录从 111 项扩展后达到 **7007 UTF-8 字节**，超过已有 `<7000` 门禁，不是业务关系丢失。

`compact_tool_catalog_json` 现在按序列化后的实际 UTF-8 字节预算缩短说明，保留全部工具 ID、12 项选择/顺序、label、risk、confirmation 和 required_context。不提高门禁或删工具；如果必需元数据本身也无法容纳，明确拒绝，不静默缩小 command surface。中文、引号及反斜线仍是完整合法 JSON，不截断字节。

- 首次新增负测 `agent-image-tool-byte-budget-red-20261007.log` 为 **10 failed / 62 passed**；修复后 Tool/Agent 图/证据/计划/记忆和 DDD/Compose **259 passed**（1.62 秒，38746）。
- 最新隔离 PG 的 Agent 固定构建计划、local/LangGraph checkpoint、工具预算、canonical runtime 和 Compose gate 组（25567，`agent-image-tool-byte-budget-current-pg-20261007.log`）已 0 退出，**95 passed / 1 warning**（11.07 秒）。保留 LangGraph serializer 告警；不把其中固定结构计划视为完整动态调查。
- 补充相关工具选择顺序与未压缩结果一致的断言后，最终同范围纯测试 `agent-image-tool-byte-budget-final-20261007.log`（42013）为 **259 passed**（1.61 秒），未改变生产排序或授权语义。
- 单独原生 `verify:code-graph-provider` 已 0 退出：CBM **0.8.1、7 entities / 9 relationships**（`agent-image-budget-native-provider-20261007.log`），只证明该双文件静态协议仓库，不是 exweb/gold/生命周期对照。`verify:production-compose` 和 `verify:backup-restore` 也各 0 退出（同前缀日志）；后者使用独立 Compose 项目、PG probe 与 MinIO **3 个版本 / 1 个删除标记**，核对恢复点后变更被撤销。报告为 `.nasus/restore-reports/backup-restore-verification-20261007T031626Z.json`；不是完整系统画像事实/工件的灾难恢复或目标执行证据，保留 Boto3/Python 3.9 告警。
- 70630 全量后端已经 **1 退出 / 14 failed / 3007 passed / 25 skipped / 1 warning / 10871.06 秒**，后续原生 Provider、备份恢复、完整浏览器与 Docker 持久性步骤被阻断。最新完整批见上文结构任务恢复记录；不能把单项门禁或另批结果拼成一次完整绿灯。

开发服务保持停止、开发业务库未迁移。统一 query-plan/call/batch/LLMCall、脚本/RunPlan、完整项目 delta/自动维护/overlay/合并、动态 Agent/全计划预算、五用途/旧链切换、真实执行反馈、Provider v2/对照/gold/隔离及完整 P0-P6/V1 未完成。

## 发布与上下文依赖登记（0077，2026-10-07）

新增[发布与上下文依赖契约](./publication-provenance.md)：原生 publication/review、精确批准与前驱、回滚源连接原 image/manifest 及对象/关联来源根；v4/v5 ContextPack 固定原 publication registration hash。三表、同项目/基线/hash 外键、追加式保护、原事务登记及历史回填不修改旧事实或授予业务/执行权威。普通读取、恢复与事件重放只校验、不补造缺失祖先。

- 初版专项 `publication-provenance-final-complete-pg-20261007.log`（47118）已 0 退出，**54 passed**（288.37 秒）。初版真实 exweb 双提交/PG/MinIO `exweb-publication-provenance-pg-20261007.log`（79716）已 0 退出，**1 passed / 1 warning**（328.78 秒），其证据不代替后来的读取优化复验。
- 发布 preview/history/pin 已加入操作级只读元数据会话，同一个 image 的完整对象/关联审计最多复用一次，下一请求仍重新检查。初版复用后发现 current head 也必须保持独立实时读取；新增同一 MVCC 会话期间启用头变化负测，并改为显式传入 project ID，避免读取 `PublishedImagePin` 不存在的字段。载入修正前代码的 `publication-read-reuse-final-complete-pg-20261007.log`（80473）终态 **11 failed / 61 passed**（274.00 秒），包含该字段错误和两个旧私有 schema 快照夹具问题；同批 exweb（32099）为 **1 failed / 1 warning**，浏览器（51706）为 **4 failed**。保留失败证据，不当作当前绿灯。
- 批量证据改为按完整固定文件/归档 pins 分组读取，所有片段仍单独核验，保留每文件前后和整批权限检查。先增加回归测试复现重复读取，`evidence-file-batch-red-20261007.log` 为 **2 failed / 50 passed**；修改后相关纯测试 **70 passed**（0.57 秒）。原撤权测试改用 20 个不同文件，仍严格检查在第 1/2/16/17/20 次文件读取立即停止，不把多个同文件片段伪装成 20 个文件。
- 完整纯契约/DDD/Portal 选择集首次 **2 failed / 252 passed**，旧静态断言仍要求 ORM repository 直接包含已经移到共享 verifier/snapshot 的代码。修正为核验实际调用链、两类完整图审计、精确会话身份和 readonly 初始化顺序后，`publication-file-batch-final-corrected-boundaries-20261007.log`（43037）已 0 退出，**254 passed**（2.13 秒），未关闭原边界。PG 私有 schema 夹具也开始使用生产只读初始化；专项（15181）为 **1 failed / 18 passed**（49.93 秒），实际撤权已正确抛出 403，但新测试误期望 Python PermissionError，已改为检查真实 PlatformApplicationError 的 code/status。
- 操作复用和逐文件分组后的 `publication-file-batch-current-pg-20261007.log`（76249）终态 **2 failed / 86 passed**（248.53 秒），只剩该进程早于修正加载的两项快照夹具断言。最新完整同顺序 `publication-file-batch-final-complete-pg-20261007.log`（37294）已 0 退出，**90 passed**（254.11 秒）；原生发布与已发布上下文深浅色浏览器（21997）已 0 退出，**4 passed**（1.4 分钟），原五秒断言未放宽，已核对 390px 截图。
- 当前真实 exweb 双提交/PG/MinIO `exweb-publication-file-batch-current-pg-20261007.log`（73403）已 0 退出，**1 passed / 1 warning**（236.89 秒）。报告 `exweb-publication-file-batch-current-20261007.json` 固定 `cd9195691f2205d671fe61ba14e47744b5187ad6 -> fe5827f6b76f77ef34918d8b452ee823142332dc`、125→126 文件和原 tree hash；**6 个发布/审阅节点、9 条父依赖、1 条上下文发布依赖**，旧事实和登记 hash 不变、回滚父 hash 正确、原 context 保持历史 pin/stale、回填幂等。最终登记 hash 为 `sha256:2627b35ee2f5ad7b681bf6284fd81c3ed18440003d0bc98c8c7986b1f1acbd61`。配套文档/reviewer 是明确协议资料，不是 business gold；没有外部模型调用或执行 exweb，`complete_delta_dag=false`。保留 Boto3/Python 3.9 告警，该单次耗时不是 p95 验收。
- 当前 Portal build（95405）/lint（69727）已 0 退出，国际化与 **54 项** Portal 契约通过；对应 `publication-file-batch-final-*` 日志。未改 CSS/token/生产路由，仍保留主包 chunk 告警。读取分组前的平台/API/runtime/Compose/SSE/stream-batching（45533）为 **192 passed / 1 warning**（219.29 秒），隔离 smoke（17899）为 **success**。分组后同范围 `publication-file-batch-final-platform-pg-20261007.log`（16994）已 0 退出，**192 passed / 1 warning**（175.55 秒），保留 LangGraph serializer 提示；当前 smoke（92886）亦已 0 退出，**success**，批次不混用。
- 旧加载版本的完整 185 项浏览器 `publication-stream-current-full-e2e-20261007.log`（65761）已 1 退出，**3 failed / 182 passed**（1.1 小时），包含 context-invalidation dark、context-packs light 和 source-revocation。source-revocation 子进程载入编辑中的新 projector，trace 显示 SyntaxError，不作为当前权限漏洞的证据。0077 后续同场景专项 `publication-file-batch-old-failures-current-e2e-20261007.log`（64359）已 0 退出，**5 passed**（6.1 分钟），包括两个 context 场景 light/dark；这不是当前完整 185 项或后续 0078 的绿灯。

0077 完成该类依赖登记，不代表检索/脚本/RunPlan 的完整 DAG、项目原子 delta、自动增量、动态调查/全计划预算、overlay/合并、五用途与旧链切换、真实目标执行/反馈、Provider 生命周期/对照/gold/隔离或完整 P0-P6/V1 已完成。开发监督服务保持停止、开发业务库未迁移，验证仅使用隔离 PostgreSQL 与本批私有工件；选择集重叠不累加为项目总数。

## 历史知识画像回滚（0076，2026-10-07）

新增[历史知识画像回滚契约](./image-rollback.md)：同项目/基线的历史 publication、原 image/hash/manifest 和当前 expected head；独立回滚审阅/政策/批准，重新核验归档证据与实时来源权限。新 publication 保留回滚源和前驱，以 CAS、审计/Outbox 原子提交；原事实不改写，source head/工作草稿/业务 authority 不回退。Portal 初始折叠，历史分页、审阅和恢复分别确认，Agent 使用严格有类型的受控回执。

- 初版真实 PG `image-rollback-first-pg-20261007.log`（67235）已 1 退出，**4 failed / 19 passed**：旧回执变化抛出未转换的领域异常；另两项负测误写 Runtime 拒绝状态、成员夹具调用了不存在参数。生产 observer 增加明确 409/stale 映射；测试按实际 waiting_approval 和真实项目成员 API 修正，未放宽批准/角色门禁。复验 `image-rollback-corrected-pg-20261007.log`（45953）已 0 退出，**32 passed**（128.83 秒），覆盖回滚/正常发布/已发布读取、并发 CAS、错误 pins、证据损坏、批准隔离和 Outbox 回滚。
- 首版 build 的两项 TS 类型/i18n 缺键错误已修正；`image-rollback-final-build-20261007.log`（95893）已 0 退出，主 chunk **884.50 KiB**，保留告警。领域/DDD/Portal `image-rollback-final-pure-20261007.log`（9947）已 0 退出，**138 passed**（1.64 秒）。增加严格重复历史项/游标和前端 canonical 负测后，Portal 契约 **54 passed**，`image-rollback-portal-contracts-20261007.log`；本次新增回滚契约 35 项。当前 build（71384）/lint（14776）已 0 退出，i18n 通过，不累加重叠集合。
- 迁移首批 `image-rollback-migration-pg-20261007.log`（34620）已 1 退出，**1 failed / 3 passed**（16.84 秒），误要求历史 0053 的物理列顺序与 ORM 完全相同；改为完整列集合、类型/可空性和新增列追加检查，不改变生产 DDL/FK。新增过期批准/来源 scope 和新 head 后原命令恢复测试后，`image-rollback-final-pg-20261007.log`（45448）终态 **1 failed / 37 passed**（182.26 秒）：测试误期望过期批准为 waiting_approval，实际正确 failed。
- 扩大复验 `image-rollback-current-complete-pg-20261007.log`（99115）已 1 退出，**2 failed / 36 passed**（166.05 秒）。一项误读错误回执层级；另一项在已含其他测试回滚记录的库执行旧 schema 降级，被生产保护正确拒绝。旧升级演练改为事务隔离 schema，使用实际 0053 migration 和本次正常发布记录，执行 0076 升/降/升并回滚整个 schema；public 原事实保持，不绕过降级门禁。最终同顺序整组 `image-rollback-final-complete-pg-20261007.log`（92010）已 0 退出，**38 passed**（133.17 秒），含四项迁移、并发 CAS、错误 pins、证据损坏、过期批准、ACL epoch、恢复不移动更新头、正常发布和已发布读取。
- 固定 exweb 双提交、真实 PG/MinIO 的 CLI 验证 `image-rollback-browser-20261007.log`（72450，端口 18687/14687）已 0 退出，**1 passed / 3 warnings**（873.65 秒，包含人工 CLI 等待，不是性能样本）。报告 `image-rollback-browser-report-20261007.json` 固定 `cd919569... -> fe5827f...`、125→126 文件和原 tree hash；界面独立确认审阅与恢复后生成 sequence 3，精确恢复原 image/hash/manifest，旧 publication/review、source head 和工作草稿保持，审计/Outbox 各一项。额外 Orders 哨兵及 reviewer 是明确协议夹具，非业务 gold，没有外部模型或目标执行。
- CLI 实际检查理由变更清除确认、审阅不授权恢复、刷新保持发布头、viewer 无写控件、读取失败隐藏旧内容及显式 reload 恢复。首次故障检查误要求关闭整个 dialog，实际正确保留错误提示并清空旧内容；修正观察断言后通过，没有修改生产行为。已目视核对 `output/playwright/image-rollback-dark-mobile-20261007.png` 和 `image-rollback-light-mobile-20261007.png`，390px 无横向溢出，隐藏滚动条沿用原样式。完成后测试浏览器凭据、临时 state、两个服务端口及隔离 PG/本次 MinIO 对象已清理。
- 最新 build（91155）、lint（16217）、i18n、Portal 契约 **54 passed** 均已 0 退出，日志 `rollback-stream-final-*`；主 chunk **884.50 KiB** 告警保留。领域/DDD/Portal/流式选择集 `rollback-stream-current-boundaries-corrected-20261007.log`（36088）**170 passed**（2.33 秒）；前一命令误写测试文件名，exit 4/no tests，不计通过。最新隔离 PG smoke `rollback-stream-final-smoke-20261007.log`（79191）**smoke: success**；各重叠集合不累加为项目总用例数。

### 流式取消的持久化确认边界

平台首个命令（65032）误用了不存在的 SSE 文件，exit 4/no tests。正确的 `image-rollback-platform-current-pg-20261007.log`（96085）终态 **1 failed / 178 passed / 1 warning**（197.81 秒），真实 HTTP 取消后同一 partial 文本重复。这不是回滚批准失败，也不能通过削弱文本断言掩盖。

调查确认：flush 在持久化 await 前递增 sequence；数据库已提交但确认尚未返回时取消，异常处理会用下一序号追加同一 pending delta。现在只有 append 返回后才推进本地 sequence 和清空 pending，提交前/后中断均重用原 `(stream_id, sequence)`，由现有 writer 幂等检查去重，不提前丢弃未确认文本。

- 八项确定性提交前/后、中断/异常及已有 sequence 恢复的负测先 **8 failed / 5 passed**（0.44 秒），`stream-flush-ack-red-20261007.log`。实现后同组 **13 passed**（0.27 秒），`stream-flush-ack-green-20261007.log`，正文及终态事件必须各一次，producer 必须关闭。
- 最新真实 PG API/runtime/Compose/SSE/batching `stream-flush-ack-platform-pg-20261007.log`（35352）已 0 退出，**192 passed / 1 warning**（186.05 秒）。独立单项 HTTP 取消已通过；将相同 pytest node 传五次实际只收集一次，未伪称重复五次。独立参数化执行同一原 HTTP 契约 `stream-flush-ack-cancel-five-pg-20261007.log`（42492）已 0 退出，**5 passed**（2.29 秒）。保留 LangGraph serializer 弃用提示，未改模型协议、SSE delta 或前端打字节奏。

完整 P0-P6 仍未完成：Provider 生命周期/对照/gold/隔离、全来源 cutover/lineage、动态调查/全计划预算、统一全部派生图与原子项目 delta、自动维护/增量、overlay/三方合并、五用途与旧链切换、真实目标执行反馈、容量/性能及完整 V1 均保留。开发监督进程仍停止、开发业务库未迁移；0076 仅加载到隔离验证环境。

## 发布证据读取与 SSE 空闲刷新（2026-10-07）

固定 exweb 发布预览曾超过原五秒 UI 断言。移除每项 EvidenceQuery 中已由 JointSourceAccess 执行的重复项目访问查询；联合项目/来源 ACL 每个证据分页的读前/读后复核保留，不缓存授权。单次 profile 从 10.642 秒/3333 SQL 变为 2.652 秒/1161 SQL，仍执行 1086 联合检查；仅诊断样本，不是 p95 性能验收。

- 联合权限的三种分页中途撤权/降权和 evidence 兼容 `publication-joint-access-final-pg-20261007.log`（30276）已 0 退出，**58 passed**（39.69 秒）。固定干净 exweb、原五秒断言不变的 publication light/dark 和两项 guards `publication-fixed-exweb-optimized-e2e-20261007.log`（56277）已 0 退出，**4 passed**（1.4 分钟）。已目视核对 publication/已发布知识读取的四张深浅色 390px 截图，保留固定 pin 和草稿区分；页面通过不等于真实目标执行或业务批准。
- SSE 广播不再依赖跨 loop 的 asyncio queue；回放/实时读取以 durable Outbox 为准。HTTP idle flush 的首个错误 key 及后续真实 ReadTimeout 复现保留，修复后 `sse-idle-flush-evidence-http-final-20261007.log`（31879）已 0 退出，**15 passed**（25.99 秒），含真实 HTTP/PG、无新业务消息的刷新和重连。旧 API queue 私有断言改为实际 Outbox 检查，不削弱事件语义。
- SSE/平台/API/runtime/Compose `sse-idle-flush-platform-final-20261007.log`（83983）已 0 退出，**189 passed / 1 warning**（177.01 秒）；纯领域/分层 **210 passed**（1.96 秒），`publication-stream-boundaries-final-20261007.log`（38077）。保留 LangGraph serializer 弃用提示，集合不累加。
- 全量既有 `npm run test:e2e`（65761，端口 18685/14685）仍是同一存活进程，加载 0075 和上述发布/SSE 修复，早于 0076；不因观察等待重启，也不把过程计数算整组或 0076 通过。

## 对象来源依赖与编译只读快照（0070，2026-10-07）

新增[对象来源依赖契约](./object-provenance.md)：manifest、全部 captured source、代码/文档修订、冻结证据、成员及 image_objects 根组成完整对象来源子图。failed/pending/legacy 来源保留负向状态，不伪造证据；代码使用 Nasus 身份，AC/规则含同来源父需求，成员只依赖自身冻结证据。项目、内容、元数据、来源 pins 与全部父集合参与登记 hash。原事实、审计、Outbox、节点/边/根同事务；历史回填异常连同 DDL 回滚，登记追加式，有数据时拒绝破坏性降级。

正常读取及重复冻结均核验原生事实与登记，不以 artifact hash 相同跳过损坏检查。此子图不拥有模型或原文读取端口，也不替代应用层 MinIO 校验。0068 和 0070 当前通过固定 image ID/hash 及读取校验衔接，不是已经贯通语义 assertion/review、authority、检索、脚本和 RunPlan 的统一完整 DAG。

浏览器负测暴露重复审计开销：根 hash 随每条父边重算导致平方级成本；改为每节点只计算一次。一次上下文编译使用独立 PG `REPEATABLE READ / READ ONLY` 快照，至多复用两个已完整核验的画像，嵌套退出恢复外层、失败不缓存、下一轮重新核验。独立池每进程四连接、无溢出、五秒超时；不会占住实时 ACL/authority 主池。权限与批准头仍实时复查，提交/历史读取不能复用先前授权。

- 初版实际 PG **1 failed / 70 passed**（219.99 秒），`object-provenance-final-pg-20261007.log`（62655）已 1 退出：批量夹具误用 `registered` ingestion 状态，按正式枚举改为 `pending`，未放宽生产校验。修正后的原领域/仓储/API/兼容选择集 **71 passed**（204.40 秒），`object-provenance-current-pg-20261007.log`（23239）已 0 退出，早于编译快照改造。最终授权优先专项 **13 passed**（61.64 秒），`object-provenance-authorization-final-20261007.log`（80126）已 0 退出，亦早于快照。
- 原浏览器四项首跑 **2 failed / 2 passed**（4.2 分钟），`object-provenance-e2e-20261007.log`（75342）；context preview 实测 110505 ms，另有语义 UI 五秒等待失败。只修哈希后复验仍 **2 failed / 2 passed**（7.1 分钟），`object-provenance-e2e-current-20261007.log`（37115），preview 38062 ms；故继续修复同编译重复读取，没有扩大等待、隐藏损坏或移除权限检查。
- 编译快照首批实际 PG **26 passed**（47.13 秒），`object-provenance-snapshot-pg-20261007.log`（75544）；增加独立有限池后 **43 passed**（96.00 秒），`object-provenance-snapshot-final-pg-20261007.log`（42168）已 0 退出，包含原生迁移/回滚、API/来源权限、分区/context/evidence 兼容。最新池/快照专项 **7 passed**（3.27 秒），`object-provenance-snapshot-capacity-verified-20261007.log`（88206）；核验实际 PG 隔离与只读、异常复位、两画像缓存上限、跨线程池满拒绝/主池可用以及下一轮重新发现损坏。小容量夹具不代替全系统并发验收。
- 最新纯契约/应用/DDD 选择集 **173 passed**（1.84 秒），`object-provenance-snapshot-verified-pure-20261007.log`（10347）已 0 退出。随后补充 rollback 失败仍 close 与编译异常不 commit，配置/边界 **8 passed**（0.46 秒），`object-provenance-snapshot-config-verified-20261007.log`。另固定 v1 证据身份的十二字段公式，禁止未来 ORM 新列改变历史 digest；逐字段仍参与校验及新增列不改公式的专项 **21 passed**（0.49 秒），`object-provenance-frozen-contract-20261007.log`。各选择集重叠，不累加为项目总用例数。
- 固定摘要后联合仓储/API/exweb 首跑 **1 failed / 16 passed**（21.02 秒），`object-provenance-frozen-contract-pg-20261007.log`（35590）已 1 退出：exweb 自身冻结/读回均通过，但全库 backfill 正确拒绝前一 API 安全负测留下的故意缺边。负测改为 `try/finally` 恢复原始测试边，保持实际 502/401/403 和恢复后 200；生产回填仍检查全部项目。完整同批复验 **17 passed / 1 warning**（21.21 秒），`object-provenance-frozen-contract-verified-pg-20261007.log`（75639）已 0 退出。最新独立报告 `exweb-object-provenance-frozen-contract-verified-20261007.json` 仍为 1833/2940 的完整子图，三读 309.88 ms；新 UUID 和原生内容导致登记 hash 不同，不把不同批次 hash 冒充相同工件。
- 真实固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、PG/MinIO **1 passed / 1 warning**（7.05 秒），`exweb-object-provenance-pooled-snapshot-20261007.log`（81168）已 0 退出。独立报告 `exweb-object-provenance-pooled-snapshot-20261007.json`：126 个代码文件、三个 captured 来源、546 个代码修订、四个文档修订、548 个唯一 evidence、730 个成员，共 **1833 节点 / 2940 边**；根登记 hash `4b08455ec813a8c0aa8091d79532614ed9858938cc8737f4b8cbe7fd8dea9216`，图摘要 `b0763c840a886682806c5e80a27bb5fcff5979a36e22a687a16cd96cde052e0e`。证据按完整冻结去重集合校验，不猜测数量；同编译三读只审计一次，下一轮重新审计，三读 239.979 ms 不是 ContextPack p95。需求/用例为明确 companion fixtures，不是维护者 business gold；未调用外部模型、未执行 exweb/Maven，只清理验证新建对象和隔离 DB。保留既有 Boto3/Python 3.9 警告。
- 最新平台/API/runtime/Compose **172 passed / 1 warning**（165.12 秒），`object-provenance-snapshot-platform-20261007.log`（54823）已 0 退出，保留 LangGraph serializer 弃用提示。Portal build/lint/i18n 已通过，`object-provenance-snapshot-portal-build-20261007.log`（59783）/`object-provenance-snapshot-portal-lint-20261007.log`（68909）及 i18n 日志；未改 CSS/token/路由，保留 864.16 KiB chunk 提示。独立 PG smoke **success**，`object-provenance-snapshot-smoke-20261007.log`（19632）已 0 退出。
- 隔离 PG、固定干净 exweb 的来源/语义/context 九项浏览器复验 `object-provenance-snapshot-e2e-20261007.log`（83902）已 1 退出，**2 failed / 7 passed**（11.8 分钟）。深浅色 ContextPack 两项通过（1.6/1.5 分钟），来源五项也通过；preview 5953-6669 ms、confirm 11897 ms、历史 read 11607 ms，仅为本批单次测量，不是 p95。两项语义用例分别在反复打开/分页过程中达到 4.1 分钟，追踪显示旧内容区卸载导致每页重新请求引用面板，最终停在核验状态；未扩大等待或改断言为接受未核验内容。下方开始修复同画像分页连续性。

分页复用仅限严格相同的 project/read session/image 五段查询键，旧数据在新页实际 HTTP 核验期间不显示，失败仍清空整个候选；不增加授权缓存、`staleTime` 或查询重试。维持画像级面板实例，避免每页卸载/重新请求；旧行与分页控件在 fetching/placeholder 阶段移出 DOM，不能把旧分区的详情当作新页。新增两项 TS 范围正反例 **2 passed**（2.7 秒），`image-page-reuse-contract-20261007.log`（77248）已 0 退出；它们是纯函数契约，不是浏览器安全验证。

- 初版七项浏览器专项 **2 failed / 5 passed**（31.2 秒），`image-page-continuity-e2e-20261007.log`（76647）已 1 退出。新夹具误把开发 StrictMode 的初始两次挂载设为一次；改为记录初始实际请求数并严格要求之后分页不增加。该单项实际回归 **1 passed**（6.2 秒），`image-page-continuity-verified-e2e-20261007.log`（75922）已 0 退出。另一失败是真实回归：旧行保留在隐藏 DOM 导致分区切换时仍匹配旧详情；已按上方策略移除，未改原历史/分区断言。已通过的五项含实际来源/项目撤权、坏 membership 和关闭后迟到响应；它们加载早于最终移除旧行，不代替最终整批。
- 最终 Portal build/lint/i18n 通过（主包 864.48 KiB，保留旧告警），`image-page-continuity-final-build-20261007.log`（79303）/`image-page-continuity-final-lint-20261007.log`（82652）；未改 CSS/token/路由。最终领域/配置/DDD/Portal **184 passed**（1.55 秒），`object-provenance-page-final-pure-20261007.log`（97293）已 0 退出。隔离 PG、干净固定 exweb 的来源/语义/context/画像历史/分页契约专项 `object-provenance-page-final-e2e-20261007.log`（83002）已 1 退出，**2 failed / 16 passed**（12.3 分钟）。画像历史/分页和来源/context 已通过，两项语义 UI 仍达到 240 秒：追踪含 192 次 objects 与 185 次 members 串行读取，多次重新打开同一真实画像，不是可以跳过完整性校验的理由。
- 最终代码下隔离 PG smoke **success**，`object-provenance-page-final-smoke-20261007.log`（29942）已 0 退出，覆盖静态摄入、画像、Agent 查询和质量面板，不是 exweb 实际业务测试执行。文档 77 个本地相对链接及代码围栏校验、`git diff --check` 通过。加载固定 v1 摘要公式后的平台/API/runtime/Compose 复验 `object-provenance-page-platform-final-20261007.log`（38913）已退出，**172 passed / 1 warning**（158.83 秒），仍保留既有 LangGraph serializer 弃用提示。

后续审计改为 SQL 列映射，避免为完整节点/边比较分配 ORM 实例；保留每批 256 项、所有字段、hash/pin 和完整父集合校验。Portal 对同 offset/limit 的 objects/members 并发读取，两者 settle 后才可合并或降载；撤权/来源变化和非容量错误优先，关闭后迟到结果仍拒绝。`ApiRequestError` 移入纯共享模块并由原 client 同身份 re-export，不改 HTTP 或授权行为。

- 最初 TS helper 测试因导入 client 的 `import.meta.env` 无法收集，`image-read-pair-contract-20261007.log`（22249）已 1 退出；抽取纯错误模块后 **11 passed**（2.8 秒），`image-read-pair-contract-verified-20261007.log`（93963）已 0 退出，覆盖双读同步启动、部分结果不可见、容量错误不遮蔽撤权/损坏、失败排空以及关闭/迟到。静态边界首跑 **1 failed / 164 passed**（1.64 秒），因为容量谓词移到 helper；更新为校验 helper 的相同严格谓词及原调用链后 **165 passed**（1.68 秒），`image-read-pair-boundaries-verified-20261007.log`（51268）已 0 退出，未放宽错误分类。
- 列映射后的实际 PG／API／快照／exweb **25 passed / 1 warning**（20.36 秒），`image-read-column-audit-final-pg-20261007.log`（27079）已 0 退出。随后加强测试，以 SQLAlchemy load event 证明核验未创建节点/边 ORM 对象；专项 **24 passed**（17.51 秒），`image-read-column-audit-events-verified-pg-20261007.log`（36180）已 0 退出。报告 `exweb-image-read-column-audit-20261007.json` 仍是 **1833 节点 / 2940 边**，三读一次审计 284.993 ms，不是 p95。cProfile 总耗时 434→444 ms 受并发及 profiler 开销影响，不能据此声称整体提速或性能验收。
- 当前 Portal build/lint/i18n 通过，`image-read-pair-portal-build-20261007.log`（52700）/`image-read-pair-portal-lint-20261007.log`（14973），主包 **865.22 KiB**，保留 chunk 告警，CSS/token/路由不变。平台/API/runtime/Compose **172 passed / 1 warning**（164.38 秒），`image-read-pair-platform-final-20261007.log`（54283）已 0 退出；独立 PG smoke **success**，`image-read-pair-smoke-final-20261007.log`（51976）已 0 退出。完整 40 项浏览器专项 `image-read-pair-full-e2e-20261007.log`（3101）已 1 退出，**2 failed / 38 passed**（12.5 分钟）：分页安全、容量、并发、历史及来源/context 已通过，两项语义长流程仍达 240 秒。它加载列映射、并发双读与 DOM 隐藏，早于下述语义输入快照扩展，不当作后者验证。

候选召回与语义输入准备进一步接入同步步骤局部只读快照；原始召回嵌套时独立核验并恢复外层，模型出口、确认、写入与之后历史读取不持有旧快照。原 span/字段/来源/hash、预算和实时 ACL 检查全部保留。批量原文每文件前后检查来源权限，撤权后立即停止，不继续读取下一项。节点 v1 摘要显式固定原七字段及策略，去掉不可变字段的递归复制；未来 dataclass 字段不改变历史公式。

- 四项新增释放/错误/撤权/再读契约连同原纯测试 **51 passed**（0.57 秒），`semantic-input-snapshot-pure-20261007.log`；扩大兼容 **202 passed**（1.94 秒），`semantic-input-snapshot-compatibility-20261007.log`，均已 0 退出。HTTP 首批 **2 failed / 40 passed**（152.05 秒），`semantic-input-snapshot-api-20261007.log`：两个负测仍拦截单读接口，但生产批读走 reader；修正到真实原文读取点并加强每文件撤权后，专项 **9 passed**（25.38 秒），`semantic-input-file-acl-api-20261007.log`，完整 HTTP 选择集 **42 passed**（168.41 秒），`semantic-input-file-acl-api-full-20261007.log`（51956）均已 0 退出。
- fixture 的不完整 Scope 改为真实 SourceAccessScope 后，纯测试 **253 passed**（2.02 秒），`semantic-input-file-acl-verified-pure-20261007.log`。新增所有节点类型、730 父根、Unicode 定位及真正 dataclass 新字段的 v1 摘要等价测试后 **285 passed**（2.58 秒），`semantic-input-v1-digest-verified-pure-20261007.log`（27748）已 0 退出。未放宽生产 scope 检查或摘要公式。
- 最新原生 PG／API／快照／exweb **25 passed / 1 warning**（38.40 秒），`semantic-input-v1-digest-pg-20261007.log`（49557）已 0 退出。报告 `exweb-semantic-v1-digest-20261007.json` 仍完整登记 **1833 节点 / 2940 边**；implements/asserts 的原始召回各一轮原生核验，输入准备各两轮嵌套核验，下一次准备重新核验并释放快照后才允许模型出口。三读 206.498 ms 和 cProfile 417 ms 均为单次诊断，不是 p95；没有调用外部模型或执行目标。
- 平台/API/runtime/Compose **172 passed / 1 warning**（187.26 秒），`semantic-input-final-platform-20261007.log`（54400）已 0 退出；独立 PG smoke **success**，`semantic-input-final-smoke-20261007.log`（27078）已 0 退出。上述批次早于下方原生完整列读取优化。

原生核验进一步改用完整 ORM 列表达式读取 manifest、来源、代码身份/修订、文档、证据及成员，保留 autoflush 和全部批次/字段比较，避免每页分配大量实体实例。没有扩大超时、截断依赖或使用跨请求授权缓存。

- 纯契约/DDD/Portal 首批 **189 passed**（1.41 秒），`image-native-column-audit-pure-20261007.log`（1726）已 0 退出；扩大到画像、页预算、证据、语义及 ContextPack 的最终选择集 **347 passed**（2.11 秒），`image-native-column-final-verified-pure-20261007.log`（67558）已 0 退出。两个命令曾因错误测试文件路径未收集用例，已更正；不将未收集日志计为通过。
- 原生 PG 首批 **33 passed**（18.70 秒），`image-native-column-audit-verified-pg-20261007.log`（99412）已 0 退出。随后强化 pending corruption 测试，确保是列查询而非事先 Session.get 触发 autoflush；最终仓储专项 **17 passed**（8.40 秒），`image-native-column-autoflush-verified-pg-20261007.log`（46124）已 0 退出。原生 metadata 的 load event 为零，待写 payload/symbol/object_ref 损坏仍被发现，rollback 后原画像可读。
- 实际 exweb／PG／MinIO／HTTP **21 passed / 1 warning**（70.10 秒），`exweb-image-native-column-audit-20261007.log`（80422）已 0 退出。之后对完整 exweb 加强 Session load event，独立 **1 passed / 1 warning**（16.32 秒），`exweb-image-native-column-allocations-20261007.log`（7507）已 0 退出。最终报告 `exweb-image-native-column-allocations-20261007.json` 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`：126 文件、546 代码修订、四个文档、548 evidence、730 成员，仍为 **1833 节点 / 2940 边**，原生 metadata ORM 分配为零；三读 271.601 ms 和 cProfile 373 ms 只是诊断，不能宣称 p95 达标。companion 文档/用例不是业务 gold；未调用外部模型、未执行 exweb，隔离 DB 和本次新增 MinIO 对象已清理。
- 最新 Portal build/lint/i18n 已 0 退出，`image-native-column-final-build-20261007.log`（22479）、`image-native-column-final-lint-20261007.log`（66493）及 i18n 日志；未改 CSS/token/路由，保留 chunk 告警。最新独立 PG smoke **success**，`image-native-column-final-smoke-20261007.log`（92662）已 0 退出。平台/API/runtime/Compose **172 passed / 1 warning**（162.84 秒），`image-native-column-final-platform-20261007.log`（54183）已 0 退出。固定干净 exweb 的九项浏览器 `image-native-column-semantic-e2e-20261007.log`（34674）已 1 退出，**2 failed / 7 passed**（12.9 分钟）；深浅色 ContextPack 和来源五项通过，两项语义长流程仍耗尽 240 秒。浅色已走过 203 次翻页及七次重新打开，停在最后冻结修订选择；深色停在最后一次候选列表核验，不当作成功。

Trace 进一步显示，重复分页的 `expect(...).toBeVisible()` 退避使约 430 ms 的请求在约 850 ms 后才被观察到。先用元素可见性等待再执行原断言的复验已终态 **40 passed**（13.2 分钟），`image-native-column-raf-full-e2e-20261007.log`（11682）已 0 退出，固定干净 exweb、独立端口 18651/14651。深浅色语义长流程各 3.9 分钟，仍接近 240 秒；这不是性能达标。该批加载全部原生列读取优化，早于下述 v1 公式保护，不作为扩展字段回填的证明。已目视核对本批深浅色 390px 审阅截图，人工拒绝保持、无横向溢出、过期确认禁用；同批 ContextPack mobile 截图也保持既有 token 和布局。

随后核对当前安装的 Playwright 实现，元素 `waitFor` 同样会退避到 500 ms，并非 RAF；日志名称不代表轮询机制。改为点击前注册确切 project/image/section/offset/limit 的两个 GET 响应监听，等待两侧 200 和完整响应后执行原可见性断言。保留全部真实分页、重开、负测、每次 5 秒和整体 240 秒限制，没有为轮询新增接口、跳过画像校验或修改生产超时。加载最终 v1 投影的固定干净 exweb 三项复验 `derivation-v1-current-event-paging-e2e-20261007.log`（68220）已 0 退出，**3 passed**（5.6 分钟）；包含挂起一侧时旧记录隐藏，以及深浅色语义长流程各 2.7 分钟。测试观察开销减少，不是生产性能达标；该批早于下述 S3 连接复用。

继续核对版本契约后，将 0068 派生登记、影响图及完整来源查询范围的 v1 摘要固定为原字段集合；保持历史字节等价，新增 dataclass 字段不会隐式改变原摘要，实际节点、来源、项目、上下文或 invocation 变化仍被检测。未增加表或迁移，也没有增加语义/批准/执行权威。

- 新增真实 dataclass 扩展的复现 **11 failed / 63 passed**（0.31 秒），`derivation-v1-digest-red-20261007.log`，证明原自动序列化会改变登记、图和来源成员摘要。固定公式后兼容/边界 **296 passed**（1.72 秒），`derivation-v1-digest-green-20261007.log`（68071）已 0 退出。
- 再增加各 v1 节点字段和 context ID 仍参与摘要的负测，扩大领域/登记/影响/失效/来源/画像/DDD/Portal 选择集 **373 passed**（2.10 秒），`derivation-v1-digest-final-pure-20261007.log`（99593）已 0 退出。隔离 PG API、原子提交和迁移回填 **26 passed**（717.05 秒），`derivation-v1-digest-current-api-20261007.log`（18105）已 0 退出；它加载固定摘要公式、早于下一项来源序列化修复，普通 v1 输入不变，不替代实际扩展字段测试。
- 实际 PG 扩展类回填复现 **1 failed**（28.63 秒），`derivation-v1-digest-backfill-red-20261007.log`（37626）：原 projector 将新增的 `future_metadata` 当作不存在的 SQL 列。比较和首次插入均使用明确四字段来源集合后，**1 passed**（38.12 秒），`derivation-v1-digest-backfill-green-20261007.log`（4352）已 0 退出；逐节点核对原摘要、完整四表内容不变、已有 backfill/API 回执一致、扩展类首次上下文登记及再次回填幂等。最终投影的相同纯选择集 **373 passed**（2.40 秒），`derivation-v1-digest-projection-final-pure-20261007.log`（6939）已 0 退出。
- 增强真实 exweb 检查，在额外归档前注入三种实际 dataclass 扩展，核对原摘要公式及所有来源指纹，回填前后比较四表全部列。首轮 `exweb-derivation-v1-digest-20261007.log`（61821）已 1 退出，**1 passed / 1 error / 2 warnings**（30.02 秒）：所选单提交浅克隆缺少 BEFORE Git 对象，exweb 未完成、未生成成功报告。同批普通 PG 兼容用例通过，不把它算作 exweb 通过。已分别核对保留完整 Git 对象的 `exweb-delta-source-20261007` 中两个固定提交及 HEAD；该目录是既有 no-checkout 验证库，不使用工作树的删除状态推导文件差异。改用 Git blob 导出后，`exweb-derivation-v1-digest-verified-20261007.log`（95368）已 0 退出，**2 passed / 6 warnings**（402.87 秒）。报告 `exweb-derivation-v1-digest-verified-20261007.json` 保留 125→126 文件、三根上下文、11 节点/8 边及 12 来源成员；原公式等价、两项扩展类新上下文登记和四表全部列回填前后不变均通过。仍是明确的协议伴随资料，不是业务 gold 或完整项目 delta DAG，未调用外部模型或执行 exweb。
- 最终投影的 Portal build/lint/i18n 和隔离 PG smoke 均已 0 退出：`derivation-v1-digest-current-build-20261007.log`（29975）、`derivation-v1-digest-current-lint-20261007.log`（33926）、i18n 日志、`derivation-v1-digest-final-smoke-20261007.log`（25164，**success**）。保留既有 chunk 告警，未改 CSS/token/路由。

各选择集重叠，不累加为项目总测试数。

### 原文读取连接生命周期

检查发现 MinIO 原文每次 GET 都新建 SDK 客户端；在一轮编译中增加[局部传输复用](./object-provenance.md#编译局部对象存储连接)，不缓存 raw bytes/权限/批准，不改变摘要或迁移。独立线程、跨进程、已关闭上下文、配置变更、并发 lease 退出和清理异常均有失败边界，写入连接保持独立。

- 新行为首跑 **10 failed**（0.11 秒），`object-storage-read-session-red-20261007.log`，明确复现缺少读取会话；实现后的扩展纯契约、来源归档、证据、语义输入及 DDD/Portal **238 passed**（1.71 秒），`object-storage-read-session-green-20261007.log`（18163）已 0 退出，早于 SDK 显式 Session 与持锁 PID 负测加强。
- 当前来源证据仓储、来源 ACL、画像证据/完整性及来源快照 PG 专项 **47 passed**（21.97 秒），`read-transport-evidence-acl-pg-20261007.log`（47842）已 0 退出；仍保留真实撤权与原文损坏拒绝，不把局部连接复用视作授权缓存。
- 加强 SDK 显式 Session 与持锁 PID 负测后，同纯契约选择集 **239 passed**（1.69 秒），`read-transport-final-contract-20261007.log`（69627）已 0 退出。平台/API/runtime/Compose **172 passed / 1 warning**（176.76 秒），`read-transport-platform-20261007.log`（1846）已 0 退出；Portal build/lint/i18n 通过，仍有 865.22 KiB chunk 告警，独立 PG smoke **success**（`read-transport-smoke-20261007.log`，42893）。未改 CSS/token/生产路由。
- 新真实 exweb/PG/MinIO 复验 `exweb-read-transport-20261007.log`（33577）已 0 退出，**3 passed / 2 warnings**（505.41 秒），早于 0071。报告记录 implements 召回/输入分别 37/44 GET、asserts 分别 11/19 GET，各轮只建一个只读客户端，独立新轮重新 GET。一次诊断时延约 659.698/933.643/490.950/911.485 ms，不是 p95 门禁。同一证据会话的 1 次 manifest + 3 次 raw GET 在损坏后拒绝、恢复后成功；只修改本批新 companion 原文，未触碰共享 exweb 归档。双提交派生/v1 兼容亦同批通过，未调用外部模型或执行目标。
- 固定干净 exweb 的相同四十项浏览器选择集 `read-transport-current-e2e-20261007.log`（32653）已 0 退出，**40 passed**（11.0 分钟），独立 PG 和端口 18655/14655，加载连接改造、早于 0071。深浅色语义流程各约 2.7 分钟；已目视核对本批 390px 深浅色审阅截图，人工拒绝保持、无横向溢出、过期确认禁用。浏览器正文使用隔离 local adapter，实际 MinIO 由前一项验证，不据此声明生产性能达标。文档同步纠正旧 references/ContextPack 章节的过期待实现表述，已实现的语义审阅和草稿/planned coverage 与尚未交付的完整执行闭环保持区分。

0070 推进对象来源登记和编译读取性能，不缩减完整 P0-P6：Provider 生命周期/对照/gold/隔离、全来源注册表与 lineage、动态调查/预算、其余完整 Derivation DAG/原子 delta、overlay/merge/回滚/重建、五用途及旧链切换、真实目标执行反馈与完整 V1 仍未完成。开发监督进程保持停止、开发数据库未迁移；仅隔离验证进程加载 0070。

## 未选定关联事实的来源登记（0073，2026-10-07）

扩展[关联来源追溯](./relation-provenance.md)：复用 0072 的 v1 节点／边和固定摘要，提前在原 references／semantic 事实及 Outbox 事务登记全部已提交候选、评估、已保存断言和审阅决定，不依赖是否已选入画像。正常历史读取、列表、选择、已有提交恢复核验登记；后续审阅先核验原前驱，缺项不通过新写入自动修复。完整原生对象来源和冻结画像仍验证，未完成模型出口保持 incomplete，不读取私有正文、不增加批准或执行权限。

- 空库升级至 0073 和已有评估／引用审阅专项 `relation-facts-first-pg-20261007.log`（45972）已 0 退出，**2 passed**（14.04 秒）。新未冻结登记／负向历史／缺项 502、401、403／登记失败原事务回滚／populated backfill 与禁止降级专项 `relation-facts-api-20261007.log`（80384）已 0 退出，**10 passed**（63.22 秒）。扩大引用候选、摘要篡改、本页列表和重复命令负测后 **16 passed**（68.94 秒），`relation-facts-integrity-expanded-20261007.log`（5334）已 0 退出。纯边界首批 **6 passed**（0.02 秒）；扩大 DDD／Portal／既有图及领域选择集 **181 passed**（1.15 秒），`relation-facts-boundaries-20261007.log`（78483）已 0 退出。
- 追加引用事实已提交而 canonical 仍 running 的恢复负测，`relation-facts-replay-diagnostic-20261007.log`（8647）已 1 退出，**1 failed**（4.38 秒）：原 `record` 幂等返回跳过了登记核验。生产恢复路径增加 `write=False` 后，专项及引用兼容 `relation-facts-replay-fixed-pg-20261007.log`（53341）已 0 退出，**24 passed**（103.44 秒）。增加正常恢复不新增事件及 missing／metadata_hash 两类损坏后，`relation-facts-replay-current-pg-20261007.log`（74732）已 0 退出，**25 passed**（140.67 秒）；当前纯边界 `relation-facts-replay-boundaries-current-20261007.log`（2630）已 0 退出，**176 passed**（1.30 秒）。这些批次早于下一节事件保留期修复。
- 实际双提交 exweb／PG／MinIO `exweb-relation-facts-20261007.log`（46020）已 0 退出，**1 passed / 1 warning**（215.56 秒）。报告 `exweb-relation-facts-20261007.json` 固定 `cd919569...` 与 `fe5827f...`，Git blob 导出 **125／126 文件**；使用真实代码成员和原文，未选定关联登记 **25 节点／26 边**，含两次语义评估、三项语义决定和一项引用决定，selected relation members 为零。来源更新后负向／暂缓历史、原摘要和登记 inventory 保持，回填幂等；图摘要 `aa8cf144eb699dac340d21197569b594d055c5f97a988d582604776935aae40b`。需求／测试和 unknown HTTP 模型响应仍是明确协议夹具，不是维护者 business gold；未调用外部模型或执行 exweb，未自动失效，也未完成项目 delta DAG。保留 Boto3／Python 3.9 警告，本批早于上述恢复修复。
- 恢复修复后的实际双提交 exweb／PG／MinIO `exweb-relation-facts-replay-final-20261007.log`（43733）已 0 退出，**1 passed / 1 warning**（246.23 秒）。新报告保留 125／126 文件、25 节点／26 边、负向历史与原摘要，以及原生代码／证据；登记摘要 `7d9eb7f51f9ce88a4ecaafe71382b28051a8367fbbd54f8b0bd4a5a8efeeda16`。UUID 和隔离工件属于本批，不要求跨批摘要相同；仍是协议伴随资料，无外部模型、业务 gold、目标执行或自动项目 delta。
- 关联兼容 `relation-facts-compat-20261007.log`（64589）已 0 退出，**56 passed**（311.17 秒）；平台/API/runtime/Compose `relation-facts-platform-20261007.log`（14810）已 0 退出，**172 passed / 1 warning**（198.58 秒），二者早于恢复修复。修复后独立关联兼容 `relation-facts-replay-compat-final-20261007.log`（49045）已 0 退出，**49 passed**（327.02 秒），引用七项由前述专项覆盖；平台 `relation-facts-replay-platform-final-20261007.log`（1653）已 0 退出，**172 passed / 1 warning**（237.85 秒），保留 LangGraph serializer 提示。
- 初版 0073 的十六项浏览器 `relation-facts-e2e-20261007.log`（8605）已 0 退出，**16 passed**（10.9 分钟），包含 ContextPack 和语义审阅深浅色／390px、分页及配对读取；已目视核对本批四张移动端截图，无横向溢出，过期确认禁用、拒绝历史保留。正文使用隔离 local adapter，真实 MinIO 由独立 exweb 专项覆盖。本批早于恢复与保留期修复，不作为后续改造的完整 E2E 证明。恢复修复后的完整 `npm run test:e2e`（13321，端口 18673／14673）现已 1 退出，**2 failed / 183 passed**（1.3 小时）：两项 publication light/dark 原五秒断言超时，后续证据读取优化及固定 exweb 四项复验见前文。原 API 早于保留期、0076 及流式确认修复，不作为最新整组证明；当前全量为独立 65761。
- 初版独立 PG smoke `relation-facts-smoke-20261007.log`（31243）已 0 退出，**smoke:success**。恢复修复后 `relation-facts-replay-smoke-final-20261007.log`（19364）亦 **smoke:success**；Portal build（17835）、lint（82809）和 i18n 已 0 退出。未改 UI/CSS/token/路由，保留 **865.22 KiB** chunk 提示；本节既有通过记录不替代下一节保留期修复后的复验。

### 事件清理后的候选复用

旧实现依赖保留的 `references.proposed` Outbox 事件判断复用。首个仅删除父节点的负测 **3 passed**（10.30 秒），`relation-facts-retention-red-20261007.log`（23256）：剩余子节点的父集合校验已阻断，但不能证明整块投影丢失也拒绝。扩大为删除候选及全部引用断言后，首跑（59981）**1 failed / 2 passed**（10.53 秒），清理恢复又遇到自动补造后的重复主键，保留该诊断。加强精确恢复清理后，`relation-facts-retention-red-verified-20261007.log`（55977）已 1 退出，**1 failed / 2 passed**（10.63 秒）：真实 canonical 命令错误地 `completed`，确认存在普通复用自动修复坏历史的漏洞。

仓储现在根据查询得到的已有候选事实，在新 invocation 和原 invocation 恢复两种路径都只读核验。事件投影改用持久候选命令关联，不依赖 SSE 保留期；正常复用仍追加一项命令事件，原候选／断言／审阅及登记摘要不变。负测覆盖 retained／pruned、完整投影丢失、摘要损坏、失败命令不提交新关联或事件；追加原仓储核验后、事件投影前损坏的故障注入，要求整个事务回滚。

- 当前纯 DDD／Portal／图边界 **177 passed**（1.20 秒），`relation-facts-retention-boundaries-20261007.log`（62730）已 0 退出。首轮 PG **28 passed**（118.73 秒），故障注入选择集 **5 passed / 18 deselected**（23.71 秒）；最终全部关联专项与引用兼容 **30 passed**（143.88 秒），`relation-facts-retention-final-pg-20261007.log`（19066）已 0 退出，不累加重叠选择集。
- 实际双提交 exweb／PG／MinIO `exweb-relation-facts-retention-20261007.log`（86742）已 0 退出，**1 passed / 1 warning**（239.97 秒）。报告固定 125／126 文件、25 节点／26 边、两项语义评估及负向／暂缓历史；SSE 清理后的新 canonical 复用仍只追加一项新事件，原登记、引用候选和审阅摘要保持。图摘要 `04b75bb018341465e2ec354f2de1c861e536025f941301e572bf4a446ca616f8`。保留 Python 3.9／Boto3 警告，没有外部模型、目标执行或业务 gold。
- 关联兼容 `relation-facts-retention-compat-20261007.log`（31963）已 0 退出，**49 passed**（329.75 秒）；平台/API/runtime/Compose `relation-facts-retention-platform-20261007.log`（12409）已 0 退出，**172 passed / 1 warning**（222.98 秒），保留既有 LangGraph serializer 提示。
- 保留期修复后 Portal build（54540）、lint（55177）及 i18n 均已 0 退出，保留 **865.22 KiB** chunk 警告；独立 PG smoke（88253）已 0 退出，**smoke: success**。完整 185 项 E2E 仍使用上一节的同一进程和较早加载版本，不能作为 0074 的验证结果。

本增量不把未保存的私有模型判断伪造成 typed assertion，也未登记所有未完成出口。AC／规则 authority、publication、检索 generation／trace、脚本／RunPlan 及完整项目原子 delta／自动维护、overlay／合并／回滚、五用途／旧链切换、真实执行反馈、Provider 对照／gold／隔离和完整 P0-P6／V1 继续待交付。开发监督进程未启动，开发库未迁移；只在隔离 PG 加载 0073。相同选择集不累加为项目独立用例总数。

## 规范批准的来源追溯（0074，2026-10-07）

新增[规范批准来源追溯](./authority-provenance.md)：AC 和业务规则的批准、撤回及重新批准修订固定原画像／成员／文档来源节点摘要和完整前驱，独立追加式 PG 表与复合 FK 不改写旧规范、画像、ContextPack 或各来源图的摘要。新原生规范事实、登记及事件处于原事务；仅新当前修订可以首次登记，旧前驱不得借新写入补造。事件追加只读核验完整历史，读取、恢复及上下文 authority port 同样核验。

- 首轮空库迁移和原批准入口兼容 **15 passed**（61.29 秒），`authority-provenance-first-pg-20261007.log`（55158）已 0 退出；早于事件 guard 改为全量只读的最终实现。
- 领域及新边界 **15 passed**（0.04 秒）。首轮新增 API/上下文/规则选集 **2 failed / 28 passed**（133.46 秒），`authority-provenance-api-20261007.log`（85439）已 1 退出：两项业务规则负测请求沿用不消费规则 authority 的 v1 策略。已明确改用 v3，保留旧 v1/v2 契约，不把该失败解释为业务规则批准已泄漏。
- 最终规范专项及原 AC／规则／上下文兼容 **43 passed**（266.63 秒），`authority-provenance-atomic-pg-20261007.log`（24920）已 0 退出；新增故障注入覆盖登记后、事件核验前丢失当前记录或前驱摘要受损，要求原规范、登记和事件一并回滚。对象／DDL 选择集 **30 passed**（15.30 秒），`authority-provenance-object-ddl-20261007.log`（1762）已 0 退出；来源／关系／派生图迁移整组 **61 passed**（777.63 秒），`authority-provenance-graphs-pg-20261007.log`（11911）已 0 退出。
- 平台 API/runtime/Compose **172 passed / 1 warning**（242.48 秒），`authority-provenance-platform-20261007.log`（86314）已 0 退出。实际双提交 exweb／PG／MinIO **1 passed / 1 warning**（340.17 秒），`exweb-authority-provenance-20261007.log`（22955）已 0 退出；报告固定 125→126 文件、4 条 AC／规则规范登记，撤回后旧 ContextPack／来源历史保持且新画像不继承批准。registry digest 为 `sha256:8ed26b30e030170b5a90c94dde7c9147771ddd7d38e0d0c7f5a699813c77e67d`，UUID 属于销毁的隔离验证环境；没有外部模型、维护者 business gold、目标执行或自动项目 delta。
- 原生 AC／业务规则 light/dark／390px 浏览器 **4 passed**（4.8 分钟），`authority-provenance-e2e-20261007.log`（23344）已 0 退出。已查看浅色 AC 和深色规则移动截图，oracle 字段与批准状态保持，无横向溢出；当前 0075 浏览器复验另行计量。此节门禁加载 0074，不代替后续 ContextPack 类型化依赖登记。

0074 连接规范事实到对象来源图；下一节 0075 进一步登记私有 ContextPack 的具体 authority pins。完整统一 publication／检索／脚本／RunPlan DAG、自动原子 delta、全 Provider 生命周期／对照／gold、动态 Agent 调查／预算、overlay／合并／回滚、五用途及旧链切换、真实执行反馈和完整 V1 继续待交付。开发业务库未迁移，开发监督进程未启动；本节仅隔离测试迁移到 0074。

## 上下文到规范版本的类型化依赖（0075，2026-10-07）

新增[上下文规范依赖登记](./context-authority-dependencies.md)：新 ContextPack 在原事实事务内保存完整原始 AC／规则 pins、规范 registration hash、画像成员 hash 和独立 root，包括 unapproved 的负向依赖。迁移不从当前头猜旧 pins，只登记精确旧元数据／工件的待处理清单；reviewer 经 canonical 独立确认、来源 ACL 锁内回读原 archive 后才能补登记。旧 context／oracle／image／规范及既有摘要不改写；事件只核验，不自动补造损坏登记。

- 领域／初版边界 **26 passed**（0.06 秒），扩大 DDD／Portal／原图与领域 **341 passed**（1.59 秒），`context-authority-boundaries-20261007.log`（93825）已 0 退出。首轮 PG 新表／固定 pins／显式回填／失败回滚／不可变及迁移 **17 passed**（161.70 秒），`context-authority-api-20261007.log`（74057）已 0 退出。增加待处理发现、原 archive／权限负测后，新 API／规则／拆包选择集 **31 passed**（235.14 秒），`context-authority-complete-pg-20261007.log`（42594）已 0 退出；早于下一项命令核验加固。
- 首轮旧 authority／ContextPack 兼容 **4 failed / 24 passed**（137.82 秒），`context-authority-first-pg-20261007.log`（64820）：旧迁移演练直接删除被 0075 引用的 0074 表，被新 FK 正确拒绝。只调整隔离回滚 DDL 演练的后续表删除顺序，保留生产 FK／trigger；修正后 **28 passed**（139.92 秒），`context-authority-compat-pg-20261007.log`（14277）已 0 退出。一轮扩大命令误写不存在的测试路径（26310）退出 4、未收集测试，不记通过。
- 初版真实 exweb／PG／MinIO **1 passed / 1 warning**（301.15 秒），`exweb-context-authorities-20261007.log`（54448）已 0 退出。报告固定 Git 双提交 `cd919569... -> fe5827f...`、125→126 文件、4 条规范历史及固定 ContextPack 的 **2 条**类型化依赖；root hash `sha256:b9a97b12930009bd104686f7310b64e92c4d13a21f74fbcc07d258492dfefc66`。来源更新／批准撤回／SSE 清理后原 pin 和旧包保持；伴随文档／oracle 为合成协议资料，不是维护者 business gold，没有外部模型或目标执行。这批早于命令和完整事件摘要加固，最终实际复验另行记录。
- 命令加固后 **324 passed**（1.27 秒），`context-authority-current-pure-20261007.log`（31400）已 0 退出；独立 23 项领域／边界同样通过。两个固定 v1 golden digest 保护节点／root 的原字段集合。正常读核验登记工具、原请求、actor、项目／会话／goal；不把历史确认 TTL 或命令终态当作读取权限。补登记事件核对全部 count／hash／command，历史列表与详情统一返回明确 409。
- 命令／事件故障注入与旧 ContextPack 选择集 **32 passed**（355.07 秒），`context-authority-command-final-pg-20261007.log`（2307）已 0 退出。此批在新增两个确认负测收集前启动，不冒充全部 25 项新 API 的整组证明。新增提交前精确 actor／目标／时间负测首跑 **2 failed / 23 deselected**（20.46 秒），夹具误读 owner 的 `user_id`；改为实际 `id`，未更改生产门禁。正确加载新夹具的同组 **2 passed / 23 deselected**（32.74 秒），`context-authority-confirmation-corrected-pg-20261007.log`（68023）已 0 退出。
- 对象／上下文／关系／派生登记的实际 PG 选择集 **54 passed**（590.70 秒），`context-authority-graphs-final-pg-20261007.log`（9697）已 0 退出；平台 API/runtime/Compose **172 passed / 1 warning**（271.19 秒），`context-authority-platform-final-20261007.log`（92779）已 0 退出。两组加载命令加固，早于下面的规范详情读取优化。
- 命令和事件完整摘要加固后的真实 exweb／PG／MinIO **1 passed / 1 warning**（381.33 秒），`exweb-context-authorities-final-20261007.log`（10590）已 0 退出。报告 `exweb-context-authorities-final-20261007.json` 固定原双提交及两份 tree hash，仍为 4 条规范历史和 **2 条**完整 ContextPack 规范依赖；新 root hash 为 `sha256:bd93cbca8dc1be6b253925a378aefee85e73d04b9230a6a74e5ac5e0266a9f56`。UUID 属于已销毁的隔离环境，报告仍明确 `target_executed=false / complete_context_authority_dag_registered=false / automatic_project_delta_implemented=false`。
- 当时 Portal build（4668）、lint（71757）和 i18n 均已 0 退出，主包 **865.22 KiB** 警告保留，没有修改 UI/CSS/token/生产路由。隔离 PG smoke **success**，`context-authority-smoke-final-20261007.log`（57064）已 0 退出。下游 scope／generation／mapping／indexed context／source roots 选择集（72001）现已 0 退出，**62 passed**（1422.04 秒），`context-authority-downstream-final-pg-20261007.log`；此批加载命令加固、早于规范读取优化和下面的新发现工具。

原生六项浏览器复验 `context-authority-current-e2e-20261007.log`（10976）已 1 退出，**1 failed / 5 passed**（11.0 分钟）：深色 AC 撤回后的五秒断言超时。trace 显示确认提交约 2.5 秒，随后完整详情 GET 尚未结束；最终错误快照已经展示 Withdrawn requirement。没有放宽等待或移除状态断言，也不能仅凭其他并行验证解释为无须修复的波动。

调查发现规范来源检查连续三次核验同一画像，详情中的 current 又独立重读同一来源。改为仅在单次规范读取内复用固定画像；在 ContextPack 编译内显式加入已有会话，默认嵌套编译仍独立。current 通过原完整历史与相同 basis 校验私有规范工件，不再重复调用来源端口；实时 ACL／批准头及下一请求完整核验保持。新增操作级作用域、异常退出与 AC／规则实际 HTTP 负测，不修改 UI/CSS 或批准语义。

- 新操作级纯测试及原 AC／规则 **13 passed**（0.59 秒）；扩大 DDD／Portal／规范／上下文／快照配置 **175 passed**（2.68 秒），`authority-read-session-boundaries-20261007.log`（27155）已 0 退出。补充不一致规范 head 在读取私有工件前拒绝的负测后，同组 **176 passed**（2.52 秒），`authority-read-session-boundaries-final-20261007.log`（24002）已 0 退出。实际 PG 两类规范专项 **2 passed / 19 deselected**（11.95 秒），`authority-read-session-pg-20261007.log`（66764）已 0 退出：每次详情只读一次来源／画像元数据，下一请求重新读取，归档篡改后 502，恢复后原正文不变。该计数不是延迟或 p95 验收。
- 读取优化后的规范／ContextPack／0075／只读快照和池兼容（79487）已 0 退出，**77 passed**（580.23 秒），`authority-read-session-compatible-pg-20261007.log`。固定 exweb 干净工作树、独立端口 18677/14677 的原六项浏览器选择集（77274）已 0 退出，**6 passed**（10.2 分钟），`authority-read-session-native-e2e-20261007.log`；批准／撤回深浅色四项及两项 ContextPack 回放全部终态，原五秒断言和 timeout 未放宽。已查看浅色 AC、深色规则 390px 截图，无横向溢出；单个 context 读取约 21 秒仍不能视为容量／p95 已验收。此批早于新历史队列，不替代队列交互验证。最终 Portal build（82636）／lint（49592）已 0 退出，i18n 通过；隔离 PG smoke（73319）报告 **success**。
- 读取优化后的双提交 exweb／真实 PG／MinIO（45313）已 0 退出，**1 passed / 1 warning**（384.75 秒），`exweb-authority-read-session-20261007.log` 和同名 JSON。仍固定 125→126 文件、4 条 AC／规则规范历史及 **2 条**原 context 依赖；registry digest 为 `sha256:3cb9260d49b098d2dd6f7f8ba5e1b963afba78a8813572d1324607344fe59f0d`，context root 为 `sha256:5822da279938ecf05b7e6045797ddd61a55af205f5d7072904047060531fe499`。批准撤回／SSE 保留期／来源刷新后旧包不变，新画像不继承 authority；伴随 oracle 是合成协议资料，仍非 business gold、完整 DAG 或目标运行。平台 API/runtime/Compose（71192）已 0 退出，**172 passed / 1 warning**（246.95 秒），`authority-read-session-platform-final-20261007.log`。各批次独立保存，选择集不累加为项目总数。

### 历史队列与 Agent 发现

新增 canonical `query.system_image.context.authority_backfill` 与独立 Portal 队列。query 只返回 strict typed 有界元数据页，不包含 oracle／原文／执行权威；Agent 观察重新检查当前 reviewer、原游标、整页和 look-ahead 原归档，页变化拒绝旧回执。队列默认收起，逐项选择／勾选／重新读取／canonical 独立确认，错误隐藏记录、禁止自动写重试，保存不改变原包／authority／stale。

- 新纯应用／Agent intent／DDD／Portal 边界 **240 passed**（1.60 秒），`context-authority-queue-boundaries-verified-final-20261007.log`。初次边界测试误要求通用 observer 直接引用 input 类，**1 failed / 239 passed**，改为核验共享 typed dispatch 和只读分支；不修改生产边界。前端契约单测隔离环境缺少 URLSearchParams 的初跑为 **8 failed / 11 passed**；修正测试 VM 后 **19 passed**，`context-authority-portal-contracts-final-20261007.log`，覆盖 malformed／跨项目／乱序／多余正文／授权篡改、选择变化、独立确认和最终回执拒绝。
- 新真实 PG/API 首跑 **2 failed / 2 passed**（37.66 秒），`context-authority-queue-pg-20261007.log`：测试访问容器不存在的 tool_invocations 属性；改为解析真实 HTTP 持久命令 DTO 后 **4 passed**（35.89 秒），`context-authority-discovery-final-pg-20261007.log`。增加当前普通成员不能通过 HTTP／canonical 发现 ID 的负测后 **6 passed**（52.25 秒），`context-authority-discovery-roles-final-pg-20261007.log`；原游标与 look-ahead 损坏均整页拒绝，普通读取不修复，登记后原上下文不变且旧 canonical 页失效。
- Portal build（19520）／lint（54923）已 0 退出，`context-authority-queue-portal-build-verified-20261007.log`／同前缀 lint 日志；国际化检查通过。初跑缺 Image revision 文案键和 control-regex lint 已修正，不关闭规则。保留 **873.48 KiB** chunk 告警。新增 `npm run test:portal-contracts` 并接入 V1 verifier，同时增加国际化门禁；gate 契约 **22 passed**（0.10 秒），`context-authority-gates-final-20261007.log`。这不代表完整 verifier 已通过。

真实固定 exweb／PG／MinIO 的 CLI 浏览器验证 `context-authority-browser-20261007.log`（75991）已 0 退出，**1 passed / 3 warnings**（657.11 秒）：四个历史上下文、一次界面独立登记、原文/oracle/pins 不变、撤回保持 stale、旧查询回执失效、viewer 403、网络错误/刷新及深浅色 390px 已验证。报告 `context-authority-browser-report-20261007.json` 保留固定 125 文件的 BEFORE 提交及明确协议伴随资料，不是业务 gold 或实际执行。平台/API/runtime/Compose `context-authority-discovery-platform-final-20261007.log`（60553）已 0 退出，**172 passed / 1 warning**（179.66 秒）；`context-authority-discovery-smoke-final-20261007.log`（29756）已 0 退出，**smoke: success**。开发监督服务保持停止，开发业务库未迁移。

完整 publication／检索／脚本／RunPlan 依赖与统一项目 delta／自动维护、动态调查／预算、overlay／合并／回滚、五用途与旧链切换、真实目标执行反馈、Provider 生命周期／对照／gold／隔离及完整 P0-P6／V1 仍未完成。完整目标保持 active，不以此增量替代全目标完成。

## 冻结关联来源追溯（0072，2026-10-07）

新增[冻结关联与上下文来源追溯](./relation-provenance.md)。原画像冻结／上下文归档事务登记 references、implements、asserts 的选定成员、双方精确对象／证据、原评估和完整决定前驱，保留 reject／defer。新四表、复合 hash FK、追加式 trigger、历史回填及非空降级保护不改变 0068／0070／0071 摘要或业务 authority。正常画像读取、重复冻结及 ContextPack port 消费开始核验登记。

- 首批领域与新边界 **24 passed**；初版真实 PG 关联／迁移专项 **9 passed**（64.15 秒），`relation-provenance-api-20261007.log`（51655）已 0 退出。原语义成员／引用成员／ContextPack 回归 **21 passed**（132.39 秒），`relation-provenance-first-pg-20261007.log`（23664）已 0 退出；早于后来加强的外键负测和历史夹具修正。
- 旧夹具专项 `relation-provenance-compat-red-20261007.log`（18816）已 1 退出，**4 failed / 7 passed**（52.35 秒）：image-only schema 缺少新表，旧回填／损坏测试删除父表被新外键拦截。夹具增加真实上下文 FK 的空表和正式 0072 迁移；迁移重放在回滚事务内先移除后续依赖，损坏／外键测试只在自己的事务或恢复范围内移除子锚点。没有关闭生产校验或外键。
- 修正后纯契约／DDD／Portal 边界 **293 passed**（1.46 秒），`relation-provenance-boundaries-20261007.log`（63033）已 0 退出。Portal build/lint 均已 0 退出，`relation-provenance-portal-build-20261007.log`（80261）／`relation-provenance-portal-lint-20261007.log`（27590）；保留 865.22 KiB chunk 提示，未改 CSS/token/路由。
- 修正后 image／object／context／derivation／relation PG 整组兼容 **47 passed**（324.52 秒），`relation-provenance-compat-current-20261007.log`（56130）已 0 退出。进一步补上下文关联锚点缺失／摘要损坏、401／403 与恢复后的真实 API 专项 **11 passed**（98.54 秒），`relation-provenance-api-final-20261007.log`（22080）已 0 退出；包括精确原生对象 key 的跨项目／错 hash／缺 endpoint 外键负测，不以 duplicate PK 或 append-only 错误冒充 FK 证明。
- 平台/API/runtime/Compose **172 passed / 1 warning**（212.08 秒），`relation-provenance-platform-20261007.log`（23347）已 0 退出，保留 LangGraph serializer 提示。隔离 PG smoke `relation-provenance-smoke-20261007.log`（90641）已 0 退出，**success**；i18n 单独通过。
- 固定 exweb `cd9195691f2205d671fe61ba14e47744b5187ad6` 的 125 文件 Git blob 导出、真实 PG／MinIO **1 passed / 1 warning**（330.94 秒），`exweb-relation-provenance-20261007.log`（29566）已 0 退出。报告 `exweb-relation-provenance-20261007.json`：canonical 确认／评估／人工拒绝与后续暂缓、两类语义冻结和混合 references 共 **28 节点／32 边／3 个关系成员／3 个 context 锚点**；混合图摘要 `213ec3e631e2d65f7b0296b94fcf3d8a8f26d2fb556f67b379a90a9f47bf76ff`。implements 的主体确属 exweb binding，模型请求包含实际归档 source_excerpt；历史画像／上下文不追随新 head，回填幂等。需求／用例和两次原生 HTTP unknown 回复是明确协议夹具，不是业务 gold，不调用外部模型或执行目标。只清理本批写入的私有对象和隔离 DB，保留 Boto3/Python 3.9 警告。
- 固定 exweb 深浅色语义／ContextPack 和分页／配对读取 `relation-provenance-e2e-20261007.log`（14914）已 0 退出，**16 passed**（10.5 分钟），加载 0072。已目视检查本批 390px 深浅色 ContextPack 与语义审阅截图：有界滚动、无横向裁切，保留 stale／未授权生成和独立确认提示、固定人工拒绝，过期审阅不能提交。正文是明确 local adapter，模型答复是协议夹具，不代替真实 MinIO、外部模型质量或业务 gold；也不代替后续 0073 的运行验证。
- 一次直接执行、未设置 PG 环境的辅助 collection 在旧 SQLite 默认初始化处因 PostgreSQL ARRAY 类型失败，`exweb-relation-provenance-collection-20261007.log`（36195，exit 2），不计为功能门禁。改用正式隔离 PG runner 后 `exweb-relation-provenance-native-collection-20261007.log`（24716）已 0 退出，**1 test collected**；实际执行证明是上方真实 PG／MinIO 批次，未把 SQLite 作为验证后端。旧默认路径的启动配置仍需单独收敛为明确 PG 前提。

本增量仅覆盖冻结关联及选定审阅祖先。未冻结关联／authority／publication／检索／脚本／RunPlan 的完整统一登记、项目原子 delta、自动增量、overlay／合并／回滚、五用途与旧链切换、真实执行反馈和完整 P0-P6／V1 继续待交付。开发监督进程停止、开发数据库未迁移；仅隔离测试进程加载 0072。选择集重叠，不累加为项目总用例数。

## 上下文对象来源锚点（0071，2026-10-07）

新增[上下文来源锚点](./context-provenance.md)。在原 context、派生/query scope 和 Outbox 事务内保存原 registration hash 与 image_objects root hash、image/manifest/input/完整 query-scope pins；复合 FK、追加式 trigger 和 populated downgrade 保护均为独立增量，不改变旧两图摘要、人工决定、oracle 或执行权威。历史回填按固定画像审计全部对象来源祖先，正常 ContextPack compile/恢复/历史与列表通过 port 核验锚点；不缓存 ACL、原文或批准头。

- 领域契约首批 **41 passed**（0.04 秒）；联合 DDD/Portal/登记/对象来源边界 **195 passed**（1.13 秒），`context-provenance-pure-20261007.log`（64456）已 0 退出。Portal build/lint/i18n 通过，保留原 chunk 告警；未改 CSS/token/路由。
- 首次空库升级 `context-provenance-first-pg-20261007.log`（12728）已 1 退出，尚未执行 pytest：0068 用当前 ORM 建表，提前创建 0071 的新 unique pin，导致重复约束。将 0068 DDL 固定为原 v1 显式结构，新约束仅在 0071 建立；没有放宽旧数据或缺项检查。
- 修正后的首组 `context-provenance-current-pg-20261007.log`（50318）已 1 退出，**1 failed / 24 passed**（305.89 秒）：测试误读不存在的 SSE ORM `correlation_id` 字段。按真实 event_payload JSON 路径修正、固定历史 DDL 物理列顺序后，`context-provenance-final-api-20261007.log`（41449）已 0 退出，**10 passed**（54.35 秒）；独立上下文／v1 扩展回填兼容 `context-provenance-final-compat-20261007.log`（80445）已 0 退出，**16 passed**（210.83 秒）。
- 真实双提交 exweb/PG/MinIO `exweb-context-provenance-20261007.log`（44325）已 0 退出，**1 passed / 1 warning**（471.37 秒）。报告 `exweb-context-provenance-20261007.json` 记录 125→126 文件、三个 context、11 个派生节点／8 边、12 个 query-source 成员及三个原生对象来源锚点，回填不改变旧四表 inventory。伴随需求／用例为协议资料，不是 business gold；未调用外部模型或执行 exweb，保留 Boto3/Python 3.9 警告。
- 平台/API/runtime/Compose `context-provenance-platform-20261007.log`（88735）已 0 退出，**172 passed / 1 warning**（209.53 秒），保留 LangGraph serializer 提示。固定干净 exweb 的 ContextPack 深浅色、连续分页和配对读取 `context-provenance-e2e-20261007.log`（82586，隔离端口 18080/14173）已 0 退出，**14 passed**（4.9 分钟）；浏览器正文使用明确 local adapter，不以此替代实际 MinIO 测试。独立 PG smoke `context-provenance-smoke-20261007.log`（25162）已 0 退出，**success**。这些批次加载 0071，不代替后续 0072。

此锚点只连接当前两类固定子图，不缩减完整 P0-P6：全部语义/authority/检索/脚本/RunPlan 依赖、原子项目 delta 与自动增量、overlay/合并/回滚、五用途与旧链切换、真实执行反馈及完整 V1 继续待交付。开发监督进程停止、开发数据库未迁移；本轮只在隔离 PG 升级至 0071。

## 公开代码身份切换与历史别名（0069，2026-10-07）

新增[稳定代码身份契约](./code-object-identities.md)。新物化的已登记代码对象和关系端点使用 `CODE-<entity_id>`，未唯一匹配者不伪造正式身份；旧画像及派生工件不改写。0069 为已有 Provider mapping 完整审计回填不可变别名，双复合 FK 同时固定 Provider mapping 和实体修订；损坏回填连同 DDL 原子回滚，非空表禁止破坏性降级。新登记的别名/审计/Outbox 同事务。

固定画像 HTTP 和 `query.system_image.revisions.resolve_code_object` 只返回身份元数据；原图 membership 优先，歧义拒绝，回执固定别名登记哈希并重新授权。证据列表与受限来源只读投影均兼容新旧 ID，保持源码/entity revision pins；受限投影不再因规范 ID 丢失可读代码对象，也不复用跨源派生标签。

- 首批纯契约 **51 passed**（0.54 秒），早于最终 FK/消费者修正。新增边界首跑 **1 failed / 74 passed**（0.67 秒），是断言写错实际变量名；按真实 canonical 调用修正后 **75 passed**（0.85 秒），`code-alias-pure-final-corrected-20261007.log`（75892）已 0 退出。扩大 DDD/Portal/回执选择集 **197 passed**（2.08 秒），`code-alias-boundaries-final-20261007.log`（70157）已 0 退出；最终消费者补齐后的同组复验 **197 passed**（2.37 秒），`code-alias-final-boundaries-verified-20261007.log`（37101）已 0 退出。选择集重叠，不累加为总用例数。
- 初版实际 PG **6 failed / 20 passed**（4.46 秒），`code-alias-registry-pg-20261007.log`（88146）：JSON 回读将 tuple 规范化为 list，直接字典比较误判；改为规范哈希比较后 **26 passed**（5.38 秒），`code-alias-registry-pg-final-20261007.log`（47475）已 0 退出。初版 HTTP **21 passed**（47.96 秒），`code-alias-http-20261007.log`（39319）已 0 退出；二者早于最终七字段 FK，不代替最终验证。
- 最终七字段 FK/迁移原子回滚同组第一轮 **1 failed / 47 passed**（65.83 秒），`code-alias-final-combined-20261007.log`（5943）已 1 退出：损坏别名的证据列表漏了完整性错误映射，返回 500。保留实际损坏检查并补脱敏 502；扩大至受限画像/知识、Agent 上下文、检索兼容后 **70 passed**（105.24 秒），`code-alias-cutover-pg-final-20261007.log`（80783）已 0 退出。显式 SQL left-side 和两项损坏投影负测后的消费者整组复验 **24 passed**（45.62 秒），`code-alias-projection-final-20261007.log`（53088）已 0 退出，包含实际账号/来源 ACL，不以测试授权替身替代。
- 补充 Provider-only 别名写入失败的实际事务回滚后，身份仓储完整八项 **8 passed**（2.64 秒），`code-alias-atomic-final-20261007.log`（12670）已 0 退出；原身份/修订/别名均保留，新 Provider mapping 和别名一起回滚，恢复 Outbox 后重试不新增代码修订。迁移回填失败连同 DDL 回滚、历史画像定位和复合 FK 同批复验，不替代全部系统故障恢复门禁。
- 新代码 ID 浏览器专项初跑 **2 failed / 3 passed**（26.1 秒），`code-alias-evidence-e2e-20261007.log`（33239）：受限投影仍只识别旧 CTX，代码卡片被错误隐藏。切到审计别名表并保持快照原 ID 后 **5 passed**（19.8 秒），`code-alias-evidence-e2e-corrected-20261007.log`（3681）已 0 退出；包括规范身份 HTTP、源码分页/HTML 字面量、深浅色/390px 和撤权/恢复，没有放宽可读代码断言。
- 真实 exweb 固定 `fe5827f...`、126 个 MinIO 归档文件、PG 双适配器身份回放 **1 passed / 1 warning**（18.63 秒），`exweb-code-aliases-final-20261007.log`（62151）已 0 退出。报告 `exweb-code-aliases-final-20261007.json` 记录 Tree-sitter **546**、已归档真实 CBM 0.8.1 图 **538**、合计 **1084** 个审计别名；三个示例类/服务的规范 ID 相同，各自历史 ID 只在固定画像/source/entity revision 内解析。别名集合 SHA-256 为 `afee5382d197e32f3590ac56e8d4ee9d322cd75fc639932c6df4394bb5f57191`。CBM 是既有真实图回放，不是本轮重新运行 CLI；项目授权使用明确只读测试端口，真实 HTTP RBAC 另行覆盖。工件与 UUID 来自已清理的隔离验证环境，不是开发业务事实；未调用外部模型或执行 exweb/Maven。保留 Boto3/Python 3.9 警告。
- Portal build/lint 已 0 退出，`code-alias-portal-build-20261007.log`（19506）/`code-alias-portal-lint-20261007.log`（53841）；保留 864.16 KiB chunk 警告，未修改 CSS/token/生产路由。隔离 PG smoke **success**，`code-alias-smoke-20261007.log`（94392）已 0 退出。
- 平台/API/运行配置/Compose 回归 **172 passed / 1 warning**（172.58 秒），`code-alias-platform-20261007.log`（54159）已 0 退出，保留既有 LangGraph serializer 弃用提示。加载最终 0069 消费者的干净固定 exweb 语义关联/ContextPack light 浏览器回归 **2 passed**（4.3 分钟），`code-alias-exweb-semantic-context-e2e-20261007.log`（10925）已 0 退出；包含拒绝关系保持、冻结语义会员、原文、非法结果隐藏及批准撤回后 ContextPack stale 历史。模型答复是受控协议 fixture，不能作为外部真实模型质量或维护者 business gold。原 0068 完整 170 项 E2E（80396）已终态 **2 failed / 168 passed**（47.3 分钟）：API 在 0069 前加载，测试文件中途更新后要求新 `CODE-` 身份，两个 source-evidence 用例因此失败。保留新身份断言，不用旧 API 批次替代本轮验证。

本增量仅切换新代码对象公开身份和明确消费者。完整 source registry cutover、未登记历史来源恢复、rename/move/split/merge lineage、全部 Derivation DAG、自动增量重建、五用途 ContextPack、旧生成链切换、实际 target/反馈及 V1 安全/容量门禁仍未完成。开发监督服务仍停止，开发数据库未迁移；当前实现只加载到隔离测试进程。完整 P0-P6 目标保持 active。

## 派生登记和冻结查询范围（0068，2026-10-07）

新增[派生依赖登记](./derivation-registry.md)：当前新测试设计链的 context/scope/generation/case/coverage/mapping、完整父边及全部来源查询范围在事实/审计/Outbox 同事务登记。0068 回填已有固定元数据，拒绝坏 pin、缺父、漏用例或 coverage；节点及来源表追加式，存在数据时拒绝破坏性降级。用例以 256 项分批，不复用只读影响预览的 128 节点上限。来源根和质量 anchor inventory 开始消费登记表，并同 SQL 快照检查原始事实与索引完整计数，缺项不返回完整子集。

- 首轮纯选择集 **1 failed / 157 passed**（1.04 秒）：AST 把字典 `update` 误判为数据库更新，已限定 Session 调用而保留禁止事务控制/业务修改的边界。修正后 **158 passed**（1.07 秒），`derivation-registry-pure-20261007.log`（6827）已 0 退出。扩大当前选择集 **402 passed**（2.39 秒），`derivation-registry-current-pure-20261007.log`（54223）；补 SQL 总数选择与 root/input pins 后 **402 passed**（2.56 秒），`derivation-registry-current-pure-final-20261007.log`（24320）已 0 退出，集合重叠不累加。
- 新表／迁移和初版提交链的实际 PG 小切片 **1 passed / 4 deselected**（39.16 秒），`derivation-registry-pg-first-20261007.log`（53266）已 0 退出，加载早于批量登记与来源消费者最终修正。随后整组 **13 failed / 5 passed**（399.97 秒），`derivation-registry-pg-20261007.log`（93202）已 1 退出：SQL 计算校验总数却未选择该列，来源反查 AttributeError。独立诊断 **1 failed / 5 deselected**（23.24 秒），`derivation-registry-pg-diagnostic-20261007.log`（46458）确认相同原因；生产查询已修正，不关闭缺项校验。
- 修正后整组复验 **1 failed / 18 passed**（543.84 秒），`derivation-registry-pg-corrected-20261007.log`（78026）已 1 退出：缺项负测误把脱敏提示中的 dependencies 单词当成正文。安全专项 **1 failed / 2 passed / 3 deselected**（84.68 秒），`derivation-registry-pg-safety-diagnostic-20261007.log`（51024）已 1 退出；两接口实际均正确返回脱敏 502。已改为完整结构化错误 envelope 和无业务字段检查；最终六项实际 PG 复验 **6 passed**（165.04 秒），`derivation-registry-pg-final-20261007.log`（66361）已 0 退出，含真实不同 context 端点 FK、回填和 540 节点回滚容量夹具。540 项是回滚的元数据夹具，不是正式生成容量验收。重新加载最终断言的三组整体复验 `derivation-registry-pg-combined-final-20261007.log`（17350）已 0 退出，**19 passed**（457.64 秒），加载 0068，不代替随后 0069 的代码身份切换复验。
- 当前 Portal build/lint 均已 0 退出，`derivation-registry-portal-build-20261007.log`（90059）/`derivation-registry-portal-lint-20261007.log`（46488）；i18n 单独通过。保留既有 chunk 提示，未改 CSS、token 或路由。当前隔离 PG smoke **success**，`derivation-registry-smoke-20261007.log`（66136）已 0 退出。
- 当前平台／运行时／Compose／失效回归 **179 passed / 1 warning**（537.87 秒），`derivation-registry-platform-invalidation-20261007.log`（88782）已 0 退出；warning 是既有 LangGraph serializer 默认值弃用提示，不是完整 V1 门禁。完整三批原生归并及 v4 恢复后独立映射 `derivation-registry-native-batch-compat-20261007.log`（1432）已 0 退出，**3 passed / 5 deselected**（693.77 秒），加载 0068，不代替新代码身份切换下的原生链回归。
- 实际相邻 exweb／PG／MinIO **1 passed / 6 warnings**（286.24 秒），`exweb-derivation-registry-20261007.log`（21436）已 0 退出。报告 `exweb-derivation-registry-20261007.json` 的 `verified_at=2026-10-06T20:54:08.687910+00:00`，对应 Asia/Shanghai 10 月 7 日；实际 commit 为 `cd9195691f2205d671fe61ba14e47744b5187ad6` → `fe5827f6b76f77ef34918d8b452ee823142332dc`，导出 125 → 126 文件。真实归档登记 **3 个 context、11 个节点、8 条边、12 个完整来源成员**；哈希、原影响图一致性及回填幂等均验证。来源/预期仍是明确合成协议资料，不是 exweb 业务 gold；没有外部模型、目标/Maven 执行、全项目失效或自动重建。
- 完整 E2E `derivation-registry-current-full-e2e-20261007.log`（80396）已 1 退出，独立端口 18388/14388、隔离 PG 和干净固定 exweb，**2 failed / 168 passed**（47.3 分钟）。API 加载 0068，source-evidence 测试文件运行前已更新为 0069 的规范 `CODE-` 断言，实际仍为旧 `CTX-`，造成两个深浅色用例失败。不得改为兼容旧 ID 而绕过新身份门禁，也不把其余 168 项当作随后 0069/0070 的验证。各批 trace 由隔离 DB 标识分目录保留在 `output/playwright/runs`。

这是当前链的项目级索引底座，不是全部实体／断言／authority／检索／脚本／RunPlan DAG 或原子项目增量计划。五用途、旧链切换、动态调查／预算、overlay／merge／回滚、Provider 生命周期／对照／gold／隔离、真实目标运行／反馈与完整 V1 保持完整 P0-P6 范围。开发监督进程仍停止，开发数据库未迁移；仅隔离验证进程加载 0068。旧完整 E2E（13526）的 API 在新增来源反查／0068 前加载，不当作新索引证明。

## 来源修订反查多个上下文根（2026-10-07）

新增[来源修订反查](./source-context-roots.md)领域 pins、application inventory port、实际 PG source/image/context FK 查询和只读 HTTP/canonical/Agent 入口。不依赖调用者先知道 Context ID，不按召回 hits 排除阻断上下文。共享回执 HTTP 直接使用 application observation union，避免再次遗漏新响应类型。SQL 总数与有界页同快照，计数前排除任何来源成员无权的画像；回执固定当时页/计数和来源权限 fingerprint，权限变化连空页也拒绝回放，未来上下文不混入旧回执。

- 首轮实际 PG **3 failed**（50.76 秒），`source-context-roots-pg-first-20261007.log`：两项失败来自共享 HTTP union 缺新类型，另一项负测修改追加式表被正确拒绝。复用共享 observation 类型，并用真实元数据读取/工件端口注入损坏，保留数据库 append-only 拒绝断言与生产 502 校验。修正后含两画像真实冻结/归档的四项 **4 passed**（79.98 秒），`source-context-roots-pg-corrected-20261007.log`（73149）已 0 退出；这批加载早于分页权限补齐，不代替当前权限复验。
- 首轮 Python 3.9 类型注解和误插入既有测试断言已修正；修正选择集 **285 passed**（1.44 秒），`source-context-roots-pure-verified-20261007.log`，早于权限补齐。权限补齐后的选择集首次因错文件名未收集，`source-context-roots-acl-pure-20261007.log`，不记绿；纠正后 **318 passed**（1.52 秒），`source-context-roots-acl-pure-verified-20261007.log`（75666）已 0 退出。扩至原失效/回执与 Portal/DDD 边界 **372 passed**（2.15 秒），`source-context-roots-current-compatibility-20261007.log`（91297）已 0 退出。选择集重叠不累加。
- 实际 PG 新旧查询兼容与隐藏来源分页专项 **17 passed**（261.38 秒），`source-context-roots-acl-pg-20261007.log`（7961）已 0 退出，加载五项根查询和原来源差异/上下文图测试。随后补真实无需求/无召回的代码画像、混合可读/受限画像以及读取中撤权/私有诊断覆盖，专项 **3 passed / 5 deselected**（41.11 秒），`source-context-roots-empty-race-pg-20261007.log`（84818）已 0 退出；不把选择集相加为项目总数。
- exweb 双 Git 导出/真实 PG/MinIO 专项 **1 passed / 6 warnings**（237.27 秒），`exweb-source-context-roots-20261007.log`（63576）已 0 退出。独立报告 `exweb-source-context-roots-20261007.json` 固定 `cd919569... -> fe5827f...`、125→126 文件、两个画像/两个归档根，分别独立验证 1/9 节点图；新增第三份上下文后旧回执仍保持原页，新的 source revision 不错误关联旧根。合成需求/用例/草稿明确不等于维护者业务 gold，不发外部模型、不执行 exweb/Maven；保留 Python 3.9/Boto3 警告。测试 UUID 来自已销毁的隔离数据库，不当作开发项目中的示例记录。
- 当前 Portal build/lint 均已 0 退出，`source-context-roots-portal-build-20261007.log`（74912）/`source-context-roots-portal-lint-20261007.log`（43842）；i18n 通过，保留 864.16 KiB chunk 提示。本轮没有改视觉 token/CSS 或生产路由。最新隔离 PG smoke **success**，`source-context-roots-smoke-20261007.log`（16953）已 0 退出；不当作完整 V1 或真实目标运行证明。

返回仍是 impact_complete=false，不写失效、批准、生成或执行事实。该入口不是全项目 Derivation/query-scope 索引、原子项目变更计划或自动增量重建；完整 P0-P6 保持原范围。开发监督服务仍停止，本轮只使用隔离验证进程。

## 持久上下文失效与实时读取（0067，2026-10-07）

新增独立 `system_image.context.invalidate` application service、canonical reviewer 确认、追加式 PG 主记录/完整有界节点/依赖边及同事务审计/Outbox。固定原 context、image、双来源和预览完整 inventory hash；新工件竞争、撤权、坏确认、过期或未来确认均拒绝。门禁作用于精确画像的当前使用，重新归档同画像的新 Context ID 不能绕过，另一新画像不继承；不改原 context、草稿、coverage 或批准。详见[失效契约](./context-invalidation.md)。

Portal 校验失效原因/UUID/stale 一致性，显示原因和记录 ID，保留深浅色与移动端历史原文。补齐发起会话/goal 的持久 SSE 路由和 canonical 完成刷新键；下游缓存改为项目前缀，仍包含各自账号隔离项。事件只通知重新授权读取，不授予生成或执行许可，也不是跨会话项目广播。

- 纯领域/应用/质量端口/原差异/Agent/DDD/Portal **408 passed**（1.80 秒），`context-invalidation-image-scope-pure-20261007.log`；它早于实时事件修复。补 handler 成功/失败及项目缓存边界后 **170 passed**（1.20 秒），`context-invalidation-sse-pure-20261007.log`。首次将三个异步测试写成未配置的 `pytest.mark.asyncio` 导致 **167 passed / 3 skipped**；已按项目惯例改用 `asyncio.run`，未安装插件或保留跳过。选择集重叠，不累加为项目总数。
- 实际 PG/canonical 第一批 **1 failed / 15 passed**（373.58 秒），`context-invalidation-pg-verified-20261007.log`：回滚断言误统计其他项目的节点，已改为项目关联查询。随后 **1 failed / 16 passed**（499.52 秒），`context-invalidation-image-scope-pg-20261007.log`（42030）已 1 退出：损坏负测把 classmethod patch 在实例，未真正注入损坏。改为类级 patch，保留生产 502 校验；含 SSE replay/终态刷新键的完整同批复验 **17 passed**（435.09 秒），`context-invalidation-final-pg-20261007.log`（74954）已 0 退出。
- SSE 修复前，实际 PG 的深浅色/390px 当前历史、刷新恢复及四类非法响应专项 **4 passed / 1.5 分钟**，`context-invalidation-final-portal-e2e-20261007.log`（13993）已 0 退出；已显示失效 ID。增加真实 SSE 已打开面板自动更新后的当前复验 **4 passed / 1.4 分钟**，`context-invalidation-sse-e2e-20261007.log`（47040）已 0 退出。
- 实际 exweb 相邻 Git 对象导出、PG/MinIO/完整九节点/当前生成拒绝 **1 passed / 6 warnings**（217.71 秒），`exweb-context-invalidation-image-scope-20261007.log`（94375）已 0 退出；独立报告固定 `cd919569... -> fe5827f...`、125→126 文件。增加持久会话 replay 后的当前复验 **1 passed / 6 warnings**（218.13 秒），`exweb-context-invalidation-sse-20261007.log`（25107）已 0 退出，独立报告为 `exweb-context-invalidation-sse-20261007.json`。资料、业务批准和模型 reply 为显式协议夹具，不是维护者 business gold；不发外部模型、不执行 exweb/Maven。
- 平台 API/runtime/Compose/ContextPack 兼容 **188 passed / 1 warning**（249.42 秒），`context-invalidation-platform-context-regression-20261007.log`（8660）已 0 退出；保留 LangGraph serde 提示。该批早于 SSE 路由补齐，不代替当前事件专项。独立 PG smoke **success**，`context-invalidation-smoke-20261007.log`（2343）已 0 退出，同样按加载边界计量。
- SSE 修复后的 Portal build/lint 均已 0 退出，`context-invalidation-sse-portal-build-20261007.log`（39916）/`context-invalidation-sse-portal-lint-20261007.log`（56715）；i18n 通过。保留 **864.16 KiB** 主包提示，没有调整设计 token/CSS。开发监督服务仍停止，仅运行独立验证数据库及临时测试服务器，不声明开发服务已加载 0067。
- SSE 修复后当前纯兼容 **415 passed**（2.54 秒），`context-invalidation-current-pure-compatibility-20261007.log`（53611）已 0 退出；当前隔离 PG smoke **success**，`context-invalidation-sse-smoke-20261007.log`（26056）已 0 退出。两批均早于新增来源反查。最新完整 E2E 收集 170 项，`context-invalidation-current-full-e2e-20261007.log`（13526）仍运行；其 API 加载早于本轮反查，不提前记全绿或当作新接口验证。

`impact_complete=false` 始终保留。当前是固定根 DAG 的持久门禁，不是全项目 Derivation 索引、全项目自动失效/增量编译或完整 P4。Provider 生命周期/对照/gold/隔离、正式来源与身份注册表切换、动态调查/预算、overlay/merge/回滚、五用途及旧链切换、脚本/RunPlan/真实反馈和最终 V1 仍按完整 P0-P6 交付。

## 完整多批终态恢复（0065，2026-10-03）

新增无 Provider 依赖的恢复 application service、独立新确认、完整原生回执/私有正文/usage/oracle 回读、v4 结果及 PG 追加式恢复 provenance。复用 v3 的草稿/coverage/原生调用 FK 投影，在同事务提交审计/Outbox；原 failed invocation 保留，只有确切新恢复权威可幂等重放该结果。历史读取不要求旧模型、租约或确认 TTL 仍有效，但即时来源 ACL 必须通过。0065 拒绝有数据时破坏性降级。详见[多批契约](./generation-batch-ledger.md)。

后续已把版本化完整回执接入共享 canonical 恢复 handler、job parser、claim/renew/finish、Temporal 活动派发及 Portal 独立确认。仅原 actor 的完整 failed/no-result 调用集可获得 metadata offer；unknown/partial 不提供恢复，另一新命令不能借已提交结果冒领 completed。公共 API/真实 Temporal 与公开恢复 UI 专项已终态通过，范围见下文；exweb 首轮失败已修正验证夹具并重跑，最新完整 E2E 仍待终态，旧链切换、完整 P0-P6 与 V1 门禁仍开放。本机已重载至 0065，不将服务健康视为完整功能验收。

- 私有 PG 回执/原子结果专项 **7 passed**（579.87 秒），`generation-batch-recovery-v4-pg-first.log`（77499）已 0 退出；独立数据库迁移至 0065。覆盖三批原生 FK、Outbox 回滚、幂等、另一权威拒绝、追加式保护、迁移降级保护、TTL/模型不参与历史读取、撤权和写工件后的 lease/ACL/cancel/model 竞争。新确认/worker 在此批为明确 seeded fixture，不是公共派发或 Temporal 证明。
- v4 只读公开 view 的纯校验及 reviewer 深浅色/390px 浏览器 **19 passed / 1.2 分钟**，`generation-batch-recovery-v4-e2e-first.log`（52407）已 0 退出；暗色移动截图已检查。来源/账号/context/scope 为真实隔离 PG，结果与审阅 transport 为显式 protocol fixture，不是公共恢复写入、MinIO 浏览器或目标执行证明。
- 私有阶段纯测首轮 **1 failed / 254 passed**（8.40 秒），`generation-batch-recovery-v4-pure-first.log`：测试用不含 digest 的 SimpleNamespace 替换 planning fixture。保留生产完整性要求，改用 dataclass replace 后 **255 passed**（8.42 秒），`generation-batch-recovery-v4-pure-verified.log`。
- canonical 扩展首轮纯测 **2 failed / 254 passed**（8.19 秒），`generation-batch-recovery-canonical-pure-first.log`：拆分 metadata offer 时丢失外层异常类型转换；恢复 fail-closed 的本契约异常映射后 **256 passed**（9.87 秒）。增加旧单次/新批次严格 parser 和 metadata offer 负测后 **267 passed**（10.09 秒），`generation-batch-recovery-canonical-pure-final.log`。这些集合重叠，不累加。
- Portal build/lint 已 0 退出，`generation-batch-recovery-canonical-build.log` / `generation-batch-recovery-canonical-lint.log`；保留约 833 KiB chunk 提示。公共 API 首轮 **3 errors**（454.46 秒），`generation-batch-recovery-canonical-api-first.log`（85284）已 1 退出，均在原失败任务查询的 fixture 准备阶段。恢复 offer 错误引用非本仓储的方法，已改用原 ledger 校验，不放宽回执或授权。修正后 **3 passed**（577.72 秒），`generation-batch-recovery-canonical-api-verified.log`（41208）已 0 退出：真实 PG/canonical 独立确认与恢复、重试后原 failed 保留、竞争命令不能冒领完成、坏 pins 与取消零新增出口；真实独立 Temporal 队列的两次事务尝试及当前 history Replayer 通过，原生 HTTP fixture 只请求三次，没有恢复重发。它不是外部模型、目标执行或容量门禁证明。
- 固定干净 exweb SHA 的公开恢复 UI 协议及严格回执校验 **17 passed / 5.4 分钟**，`generation-batch-recovery-canonical-e2e-first.log`（70655）已 0 退出。实际 PG 的三来源/context/scope 编译为两批协议工件；恢复 pending/confirm/result transport 为显式 fixture，不是后端恢复或 Temporal 证明。验证坏 offer 隐藏、刷新后重新确认、单次写入、v4 历史、撤权隐藏及深色 390px 无溢出；已查看浅色桌面与深色移动截图。
- 单次/v3 兼容 PG **5 passed / 26 deselected**（429.98 秒），`generation-batch-recovery-compatibility.log`（87280）已 0 退出；隔离 smoke **success**，`generation-batch-recovery-canonical-smoke.log`（32984）已 0 退出。原完整 E2E **121 passed / 39.5 分钟**，`generation-batch-current-full-e2e.log`（68138）已 0 退出；其 API 在早先 0064 加载，不将此批归为 0065 最终验证。
- exweb 首轮实际 PG/MinIO 恢复长测 **1 failed / 1 warning**（1347.74 秒），`generation-batch-recovery-exweb-minio.log`（7744）已 1 退出。失败在验证夹具误读不存在的顶层 `artifact_hash`，不是生产拒绝回读；已改为精确校验仓储 metadata 和 MinIO 完整 result，而非降低断言。重新运行 `generation-batch-recovery-exweb-mapping-verified.log`（23776），含游标发现及 v4 独立映射扩展，尚待终态。伴随资料编译为一批，回复/usage/确认/原 failed 为明确内部夹具，没有公共 Tool 派发、真实 Temporal、外部模型或目标执行。
- 当前纯领域/恢复/结果/账本/任务/DDD/Portal **267 passed**（10.57 秒），`generation-batch-recovery-current-pure.log`，i18n 校验通过。补充平台 API/runtime/Compose **172 passed / 1 warning**（201.85 秒），`generation-batch-recovery-platform-regression.log`（64738）已 0 退出；保留既有 LangGraph serde 提示，不累加重叠测试为项目总数。
- v4 恢复结果的实际三批/PG/canonical 独立 QA 映射专项 **2 passed**（571.69 秒），`generation-batch-recovery-mapping-api-first.log`（84223）已 0 退出：新恢复与独立 QA 自有会话确认、完整 context/scope/oracle pin、映射审计/Outbox、oracle 篡改拒绝、Outbox 故障全部回滚再新确认成功，原 failed 和 draft 不改写，原三次 HTTP fixture 没有新增出口。未经隔离环境的初次 collect 在 SQLite ARRAY 编译阶段失败，未执行测试；实际运行仅临时 PG，不改开发数据。该批在下方分片读取/共享归约改动前加载，当前兼容复验另记。
- 0065 最新完整 E2E 已启动，`generation-batch-recovery-current-full-e2e.log`（25575），实际收集 **157 项**、固定干净 exweb SHA、独立 PG/端口，待终态。121 项旧批次不替代这批；浏览器中的生成/恢复协议 fixture 仍不代表真实模型或目标执行。
- 本机 `dev:foreground`（91057）已监督启动四个 host 服务，实际 PG `alembic_version=0065_generation_batch_recovery`；`dev:status` 全部 ready、Portal/API/Runner HTTP 200。Docker 仅承载 PG/MinIO/Temporal；保留现有模型设置及 Embedding/Rerank development fallback，没有注入出网同意或 operator 价格策略。日志 `generation-batch-recovery-dev-runtime.log`。
- 最新 Portal build/lint 均已 0 退出，`generation-batch-recovery-current-build.log` / `generation-batch-recovery-current-lint.log`，保留 832.63 KiB 主包提示。DDD/Portal **141 passed**（1.82 秒），`generation-batch-recovery-mapping-boundaries.log`；实际 i18n 脚本通过，`generation-batch-recovery-mapping-i18n-verified.log`。首个命令错误使用不存在的 npm script，保留失败日志，不修改检查规则。
- exweb fixture 新增恢复 v4 的独立映射及 head/authority 变化后不可用检查，尚未在新长测验证。发现原 helper 只看第一页，新增第四份草稿后可能受随机 generation ID 排序影响；改为最多八页、每页三条的严格递增游标查找，并保留完整 receipt 验证。纯分页正反例 **8 passed**（0.74 秒），`generation-batch-recovery-exweb-pagination.log`：后页发现、重复/倒序/错项目/错误游标/缺目标/超页拒绝。这是夹具可靠性证明，不代替真实 exweb/PG/MinIO 结果。
- 最新隔离 PG/端口 smoke **success**，`generation-batch-recovery-current-smoke.log`（2495）已 0 退出；它早于下方分片查询改动，不证明新增端点。
- 已确认端到端容量缺口：内部 v3/v4 合并允许最多 32768 cases，而 v1 `MappingReviewInput` 和 `MappingReceipt` 仍限定 8192 条断言。下方开始交付独立分片协议，不扩大 v1 上限、不裁剪分母；正式保存/最终提交和完整容量门禁仍未交付。

## 完整断言的分片协议底座（2026-10-03）

该底座批次新增确定性 128 对断言分片、完整 generation/context/scope/前驱绑定和顺序 hash commitment；只读计划/片 API 要求即时 reviewer/原来源权限及 head 复核。领域按序消费完整分片后才归并 assessment，复用原覆盖归约器，保留分母、gap 和零自动化/目标执行/通过。详见[分片契约](./mapping-partitions.md)。此批当时没有分片保存或正式最终批准入口；下方 0066 后续增加私有暂存，没有改变 v1 canonical 写入/历史工件，也没有新增模型调用。

- 首轮分片领域和 v1 映射 **43 passed**（2.60 秒），`mapping-partitions-domain-first.log`（14893）已 0 退出。扩展应用/DDD/Portal **192 passed**（3.60 秒），`mapping-partitions-pure-boundaries-first.log`（64284）已 0 退出。最后加入末片失败及完整 generation batch 纯测后 **242 passed**（5.78 秒），`mapping-partitions-pure-boundaries-final.log`（30543）已 0 退出；集合有重叠，不累加。
- 领域验证 9000 条断言全量分片/归并、32768 个案例的完整布局和有界末页；绑定项目/模型结果/context/scope/input/前驱，缺片/重片/乱序/坏摘要/改 oracle/额外权威/最后一片遗漏全部拒绝，draft 不变。32768 布局测试不是全部案例各 256 断言的压力测试，更不是 64 批原生模型/PG 最终批准或性能门禁。
- 实际 PG 新计划/页查询及 v1/v4 兼容专项 **6 passed / 25 deselected**（676.96 秒），`mapping-partitions-pg-api-first.log`（38719）已 0 退出，覆盖完整共享归约器和新增读 API，不证明下方 0066 暂存。来源撤权专项 **1 passed**（21.73 秒），`mapping-partitions-source-acl-api.log`（19819）已 0 退出：先有 qa 角色与旧计划，撤原代码来源后计划/片整页 403，管理员按自身权限可读，零 mapping 写入。这是隔离 PG 与本地私有工件 adapter，不是 MinIO/最终批准证明。
- 当前完整 E2E（25575）和 exweb/MinIO（23776）均在这次分片源文件改动前加载；它们可以证明自己的 0065 及 exweb 验证范围，但不能证明新增查询或归约器。前端未增加分片编辑入口；最新完整 V1、五用途、动态构建、delta/overlay、脚本/RunPlan/真实反馈仍按原 P0-P6 范围保留。
- 分片查询后本机监督服务（74694）已实际加载新读 API，OpenAPI/readyz 验证通过，Docker 仍只承载基础组件；它早于下方 0066 暂存。日志 `mapping-partitions-dev-runtime.log`。Portal build/lint/i18n 通过，`mapping-partitions-current-build.log` / `mapping-partitions-current-lint.log` / `mapping-partitions-current-i18n.log`；独立 PG smoke **success**，`mapping-partitions-current-smoke.log`（63886）已 0 退出。服务健康和 smoke 不等于完整 P0-P6 验收。

## 私有断言分片持久暂存（0066，2026-10-03）

新增独立 application use case、PG repository/追加式表、私有工件 adapter 与 canonical 确认工具 `quality.test_design_mapping.stage_part`。每片完整有序决定固定 plan/part/generation/context/scope/oracle/映射前驱，并按认证 reviewer 独立追加编辑。项目锁内重验当前账号/成员/全部来源/scope、映射 head 和片 head，分片/审计/Outbox 原子提交；相同命令回读原工件后幂等恢复。历史头及固定修订只读 API 支持刷新后发现原提交、原文/工件完整性复核和动态撤权。详见[分片契约](./mapping-partitions.md)。暂存不等于最终批准，不修改原 draft，不增加执行或通过覆盖。

- 首轮纯应用/领域/DDD **202 passed**（3.77 秒），`mapping-part-staging-pure-first.log`（89976）已 0 退出；加入头查询及 generation/Portal 边界后 **265 passed**（5.10 秒），`mapping-part-staging-pure-final.log`（70031）已 0 退出。两集合重叠，不累加。
- 实际隔离 PG/canonical 首轮 **4 passed**（114.72 秒），`mapping-part-staging-pg-first.log`（30778）已 0 退出：用户确认、完整决定私有回读、原草稿不改、两前驱追加/CAS、相同/不同命令并发、最终 v1 审阅后历史暂存不再 current、确认 actor/TTL、原来源撤权、Outbox 失败分片/审计全部回滚再精确重试。该批早于新增头查询和后三项故障/MinIO 用例；不冒充最终复验。
- 0066 暂存 API/MinIO 专项 **8 passed / 1 warning**（234.71 秒），`mapping-part-staging-pg-minio-final.log`（39803）已 0 退出；加入终态 ack 丢失恢复后，最终暂存与旧 v1 兼容复验 **11 passed / 1 warning**（242.87 秒），`mapping-part-staging-final-contracts.log`（37653）已 0 退出。显式 MinIO opt-in，只清理该运行写入的对象，不重开 failed 命令。平台 API/runtime/Compose **172 passed / 1 warning**（228.18 秒），`mapping-part-staging-platform-regression.log`（48147）已 0 退出；隔离 smoke success，`mapping-part-staging-smoke.log`（55600）已 0 退出。以上均早于下方 v2 最终集合实现。
- 新增固定 exweb 的私有分片保存/MinIO/幂等/头查询和后续审阅失效验证 helper。当前 exweb 长测（23776）在 helper 改动前已加载，不能证明新暂存；固定输入 SHA 重新核验仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc` 且工作树干净。当前已有需求/用例/确认/原生模型内容仍是明确 fixture，不是其维护者批准、外部模型或目标运行。
- 最终完整分片集合确认、v2 mapping/回执/撤回兼容、Portal 分片编辑和完整容量/查询性能仍须继续交付；旧 v1 8192 上限保持不变。没有把此阶段视为 P5 或完整 P0-P6 完成。

### 后续结果与加载边界

- 0065 代码加载的完整 E2E **157 passed / 45.4 分钟**，`generation-batch-recovery-current-full-e2e.log`（25575）已 0 退出；它早于分片读取、0066 和最终 v2，不能证明新链。0066 暂存后加载的完整 E2E `mapping-part-staging-full-e2e.log`（旧 80389）已终态 **1 failed / 156 passed / 50.1 分钟**：运行中增补前端触发 Vite import 错误遮罩，dark recovery 点击被遮挡直至 420 秒超时；并行专项共享 trace 目录又使失败 network copy 丢失。保留红记录，2026-10-07 另起固定源码和独立 trace 目录的当前全量复验，不将旧批次记绿。
- 旧 exweb 完整 PG/MinIO v4 恢复和独立 v1 映射 **1 passed / 1 warning**（2128.76 秒），`generation-batch-recovery-exweb-mapping-verified.log`（23776）已 0 退出。该进程加载于 0066/helper 改动前，不能证明新暂存；随后完整 exweb/0066/helper 复验 `mapping-part-staging-exweb-current.log`（旧 8167）终态 **1 passed / 1 warning**（2287.11 秒），证明原生和 v4 草稿的私有分片、MinIO、幂等、个人头/历史和 v1 审阅后失效；该进程在新 v2 helper 前加载，不证明最终集合。固定原生模型内容/确认/需求/测试为明确 fixture，没有外部模型、维护者批准或 exweb 目标执行。
- 暂存最终纯应用/边界 **265 passed**（4.80 秒），`mapping-part-staging-current-pure.log`（25868）已 0 退出。Portal build/lint/i18n 已通过，`mapping-part-staging-build.log` / `mapping-part-staging-lint.log` / `mapping-part-staging-i18n.log`，保留既有大 chunk 提示。原 native supervisor（16796）实际加载 0066 暂存，但早于终态 ack 修复和下方 v2；不得据健康接口声称已加载最终代码。

## 完整分片集合的最终审阅实现（v2，2026-10-03）

新增全量成员摘要承诺、仅 metadata 的完整集合预览、独立 canonical `quality.test_design_mapping.finalize`、v2 工件与 receipt、原历史链上的撤回兼容。全量原分片/来源/plan/scope/oracle 与 signer 重验，项目锁内全部片 head 检查，最终事实/审计/Outbox 原子提交；同命令只恢复原权威。另一 reviewer 仅可通过 exact persisted final authority 内部复核绑定原片，不开放私有暂存正文。详见[分片契约](./mapping-partitions.md)。Portal v2 读取已验证，后续分片操作状态见下一节，不将这些专项当作完整 P5 交付。

- 首轮纯测 **204 passed / 18 errors**（5.14 秒），`mapping-finalization-pure-first.log`（11575）已 1 退出，全部 error 是新 Parts fixture 的同名闭包变量初始化错误，尚未进入该夹具的业务断言。修正夹具而不放宽生产校验后 **222 passed**（6.88 秒），`mapping-finalization-pure-verified.log`（70093）已 0 退出。包括实际全部 65536 个 synthetic metadata 成员的常量大小摘要/最后成员变更拒绝，不是实际 PG/MinIO 容量证明。
- 实际隔离 PG/canonical 首轮 **2 failed / 7 passed**（314.58 秒），`mapping-finalization-pg-canonical-first.log`（79487）已 1 退出；独立诊断 **1 failed**（49.45 秒），`mapping-finalization-pg-debug-first.log`（92346）已 1 退出。一个 fixture 使用了错误成员登记签名；另一个把项目管理员当作会因 restricted source 而被拒绝的普通 QA。修正为独立 QA、自有会话及精确成员 API，不放宽生产权限。
- 修正后的整批 **1 failed / 9 passed**（233.20 秒），`mapping-finalization-pg-minio-current.log`（97625）已 1 退出：撤权正确拒绝，但测试错误期待后置 scope-change 异常而非前置 `SourceAccessDenied`。按实际拒绝阶段使用明确异常及消息后，完整复验 **10 passed / 1 warning**（229.17 秒），`mapping-finalization-pg-minio-verified.log`（80547）已 0 退出。包含 canonical 分片/独立最终确认、当前 signer/所有来源、前驱和片 head 竞争、故障原子回滚、另 QA 可读最终但不可读私有片、旧 v1/withdraw 兼容，以及实际 MinIO 原片与最终工件回读。没有外部模型或目标执行；保留 Python 3.9/Boto3 提示。
- 平台 API/runtime/Compose **172 passed / 1 warning**（189.72 秒），`mapping-finalization-platform-regression.log`（65965）已 0 退出。纯领域/分层批次 **263 passed**（6.61 秒），最终 v2 reader/共享归约批次 **238 passed**（6.08 秒），`mapping-finalization-v2-reader-pure-final.log`（95988）已 0 退出；这些集合重叠，不累加。
- Portal v2 严格读取、混合历史/撤回和 Python/TS 完整 hash commitment 专项 **5 passed / 1.9 分钟**，`mapping-finalization-v2-reader-exweb-e2e.log`（16419）已 0 退出。9000 对/71 片仍完整校验、v1 限额不放宽；恶意重签的缺片/外来 case/oracle/authority/执行字段仍拒绝。固定 exweb 浏览器三来源/上下文/范围为实际隔离 PG，v2 最终历史 transport 为明确协议 fixture，不是浏览器真实写链。目视检查发现旧 locator 全高截图被固定工具栏和滚动祖先裁剪，不将其算作完整视觉验收。
- v2 reader Portal build/lint/i18n 通过；第一次 build 因引用不存在的 coverage `oracle` 字段失败，已改为与实际原断言 oracle 的 hash 和 coverage digest 双校验，不放宽数据验证。新 exweb helper 已接入原生和 v4 恢复的完整分片/MinIO 最终归档，但旧会话 8167 在 helper 改动前加载，新的实际长测仍须另跑，不能用旧报告证明 v2。
- 完整目标保持 P0-P6：供应商生命周期、gold/对照/隔离、正式 cutover/lineage、动态调查/累计预算、delta/overlay、五用途、旧链切换、脚本/RunPlan、真实受控执行/反馈及完整 V1 仍未完成。

## Portal 分片编辑与完整集合确认（2026-10-03）

新增 quality-loop 类型/纯校验/API 与独立 hooks，路由组件只消费状态和回调。显式打开后才读计划/当前自己的片；每片最多 128 对、展示八对一页，原片完整决定均提交。个人历史重新授权及完整 hash 校验，重新读取/意见修改使确认失效；未知 ack 禁止自动再写。最终预览只校验固定大小承诺，完整私有内容由后端验证；全部齐备后独立说明/确认，再走 `quality.test_design_mapping.finalize`。分片操作使旧集合确认失效。新读失败向上隐藏受保护草稿，旧 v1 撤回保持兼容。

- Portal build 0 退出，`mapping-staging-ui-build-verified.log`（95539），约 863 KiB chunk 提示仍保留。首轮 lint 控制字符正则规则失败，改用明确 code-point 检查后 lint 0 退出，`mapping-staging-ui-lint-verified.log`（15211）；i18n 门禁通过。纯领域/应用/DDD/Portal **216 passed**（6.15 秒），`mapping-staging-ui-pure.log`（46148）已 0 退出，不与前述集合累加。
- 固定 exweb 新增分片浏览器首批 **5 passed / 3.2 分钟**，`mapping-staging-ui-exweb-e2e-first.log`（旧 95745）；增补独立 QA 私有编辑/确认、编辑使旧最终确认失效、自引用链拒绝并联跑 v2 reader 后 **11 passed / 5.6 分钟**，`mapping-staging-ui-exweb-e2e-final.log`（旧 73183）。浅色完整单片和深色 132 对/两片验证保存、历史编辑、未知 ack 只读恢复及最终独立确认；首批移动编辑截图已目视检查。生成、分片和最终写 transport 为显式协议 fixture，实际后端提交已有前述 10 项另行证明，仍非全链浏览器真实批准。最终 reader 移动 viewport 截图仍未完整展示顶部标题，不把它记为全部视觉验收通过。
- 最终 UI build/lint 日志 `mapping-staging-ui-build-final.log` / `mapping-staging-ui-lint-final.log` 有成功终态；纯领域/应用/边界 **216 passed**（5.89 秒），`mapping-staging-ui-pure-final.log`。隔离 smoke success，`mapping-staging-ui-smoke.log`。2026-10-07 已确认旧会话 handle 均不存在、无遗留应用进程，历史运行状态不能当作当前服务仍 ready。
- 重载前开发库 running tools/turns 均 0。精确结束旧 supervisor 16796 的 `dev-up.sh` owner，等 cleanup 完成后本机 API/Worker/Runner/Portal 重新启动；新监督会话 23303 实际加载最终 v2，`mapping-staging-ui-dev-runtime.log`，`dev:status` 全 ready、Portal/API/Runner HTTP 200、OpenAPI 含 finalization 和 private revision endpoints。Docker 仅保留 PG/MinIO/Temporal 等基础设施；未更改用户模型或添加伪造出口/费用策略。运行健康不代替功能验收。

完整 P0-P6 与原交付门禁不变，分片界面接入不是完整系统画像或真实业务测试闭环完成。

## 固定上下文变更影响预览（2026-10-07）

新增纯领域派生 DAG 验证、quality_loop 完整工件读取端口、单 SQL 的项目/context inventory、system_image application service、HTTP 和 canonical `query.system_image.context.change_impact`；无新增迁移。契约见[上下文变更影响](./context-change-impact.md)。固定原 context/image/source 和全部已有 scope/generation/mapping，展开 case/coverage；新增文件、空查询/top-k 范围同样保守触发重新调查。回执只存 IDs/hash/计数，旧回放不纳入后来工件；每次完整回读重新授权。不写 stale、不改批准或 coverage；`impact_complete=false / invalidation_applied=false`，128 节点预算不等于完整大规模 P4。

- 首轮纯领域/质量端口/原差异/DDD **202 passed**（1.76 秒）；补 typed parent/cycle/schema 负测、中英文 Agent 发现及 Portal 边界后 **286 passed**（1.83 秒），`context-change-impact-pure-final-20261007.log`（87451）已 0 退出。两次扩大命令误指定不存在的测试路径，分别保留 `context-change-impact-pure-first-20261007.log` 和 `context-change-impact-pure-verified-20261007.log` 的 exit 4/no tests，不当作测试通过。
- 补 inventory 报错后原 scope 重验、每个完整读取后重验及严格节点/inventory shape 后 **292 passed**（2.00 秒），`context-change-impact-current-pure-20261007.log`（32510）已 0 退出；扩至旧 image-query receipts、ContextPack、scope/生成/映射纯契约后 **381 passed**（2.20 秒），`context-change-impact-current-compatibility-pure-20261007.log`（8100）已 0 退出。选择集重叠不累加。含两个 inventory 撤权竞争负测的完整实际 PG 复验 **20 passed**（193.26 秒），`context-change-impact-current-pg-20261007.log`（72260）已 0 退出。
- 实际 PG/canonical 首批 **15 passed / 3 errors**（72.31 秒），`context-change-impact-pg-first-20261007.log`（96042）已 1 退出；三项均在 fixture 用旧画像 manifest 当成新采集版本时失败。改为核验实际采集 registry，不物化新画像或降低版本断言后，同一完整批次 **18 passed**（120.74 秒），`context-change-impact-pg-verified-20261007.log`（29472）已 0 退出。覆盖六类完整依赖、零业务写入/零模型调用、固定旧 inventory 与新映射追加、无正文 Outbox、Agent 重新授权、来源撤权、损坏工件、413 和无变化输入。
- Portal build/lint 已 0 退出，`context-change-impact-build-20261007.log`（99295）和 `context-change-impact-lint-20261007.log`（59987）；i18n 通过。保留 863.33 KiB 主包提示，未改 Portal 生产样式或 Vite 基线；尚无影响预览面板。
- 新 exweb Git 导出/实际 PG/MinIO 的 context 派生专项 **1 passed / 6 warnings**（163.85 秒），`exweb-context-change-impact-20261007.log`（17134）已 0 退出。独立报告 `exweb-context-change-impact-20261007.json`：125→126 文件、1 added/1 modified/124 unchanged、9 个完整依赖节点、canonical replay/Agent 重新授权通过；只清理本轮 MinIO keys。保留 Boto3/Python 3.9 提示；配套 Search 需求/生成/批准及 Orders sentinel 为明确协议夹具，不是维护者业务规范，无外部模型或目标执行。最后 inventory 报错撤权检查加载后，最终复验 **1 passed / 6 warnings**（172.73 秒），`exweb-context-change-impact-current-20261007.log`（36625）已 0 退出，使用独立 report。
- 原 exweb v2 finalization（71490）终态 **1 passed / 1 warning**（2961.83 秒）；完整 E2E（28958）终态 **168 passed / 55.3 分钟**，均已回收 handle。它们加载时间早于影响查询和 0067，不替代新增功能验证。开发监督服务仍停止。
- 当前隔离 smoke **success**，`context-change-impact-smoke-20261007.log`（95995）已 0 退出；其 API 在最后错误诊断前撤权检查之前加载。平台扩大命令错误指定不存在的 `test_image_revisions_api.py`，`context-change-impact-platform-20261007.log`（90638）已 exit 4/no tests；正确路径复验 **180 passed / 1 warning**（220.98 秒），`context-change-impact-platform-verified-20261007.log`（62212）已 0 退出，但加载早于最后错误诊断顺序修复。最终旧 canonical image-query 兼容 **5 passed**（23.85 秒），`context-change-impact-current-image-query-pg-20261007.log`（61086）已 0 退出。

完整 P0-P6 仍未完成：本节只读预览之后，0067 已新增独立确认的有界持久失效和消费者阻断，具体见上节；全项目反向依赖、实体 lineage、增量重建/overlay/merge/回滚、Provider 全生命周期/对照/gold、旧链切换、其余用途、脚本/RunPlan/真实执行反馈及最终 V1 门禁保持原目标。

## 固定来源修订差异与 canonical 观察（2026-10-07）

开始推进 P4 文件差异基础：领域比较、application 查询端口、只读 PG 修订读取、归档 manifest 防腐适配器、HTTP 和共享 canonical `query.system_image.sources.delta` 已实现；无新增迁移。完整契约见[固定来源差异](./source-deltas.md)。固定同 binding 双修订，全部路径计算后分页；旧/不完整 inventory、排除/未读范围和单文件采集不伪造增删；唯一同内容 rename 仅为未继承身份的候选。ToolResult/Outbox/审计只保存 request、hash、计数和游标，Agent/HTTP 展开重新鉴权与核验；不把文件比较标为完整影响、实体 lineage、批准或发布。

- 首轮 HTTP/exweb 选择集在 Python 3.9/Pydantic dataclass schema 收集阶段失败，`source-delta-http-pg-first-20261007.log` / `exweb-source-delta-pg-minio-20261007.log`；将公开 DTO 的 union 改为兼容的 Optional/Union，不升级依赖或跳过测试。修正后的 HTTP **3 failed / 4 passed**（13.01 秒），`source-delta-http-pg-python39-20261007.log`：平台权限错误继承 ValueError，被 route 错映射 400；恢复原平台状态后 **7 passed**（12.73 秒），`source-delta-http-pg-authorization-20261007.log`（87558）已 0 退出，没有把 400 接受为权限契约。
- canonical 初版领域/应用/回执/工具发现/DDD **227 passed**（3.34 秒），`source-delta-tool-pure-20261007.log`；补只读层边界、PG 查询中撤权与过大页面诊断前重验后，含 Portal 边界的集合 **249 passed**（3.44 秒），`source-delta-final-pure-boundaries-20261007.log`。最终代码复验 **249 passed**（1.99 秒），`source-delta-current-pure-boundaries-20261007.log`（25664）已 0 退出。选择集重叠不累加。
- 真实 HTTP/PG/canonical/原 image-query 兼容专项 **19 passed**（90.80 秒），`source-delta-canonical-pg-20261007.log`（40095）已 0 退出。覆盖当前 viewer/source ACL、跨项目与错误 pins、严格输入、真实持久回执/Outbox、幂等、固定旧 revision、工作区移除、坏回执、502/503/413 脱敏与 Agent 重新核验。该批 API 在最后两处新增撤权检查前加载；包含新增 PG 查询期间撤权参数的完整当前复验 **20 passed**（77.37 秒），`source-delta-canonical-current-pg-20261007.log`（9433）已 0 退出。
- exweb 两个实际相邻提交、真实独立 PG/MinIO/HTTP 首版 **1 passed**（14.04 秒），`exweb-source-delta-pg-minio-python39-20261007.log`（40585）已 0 退出。canonical 扩展 **1 passed / 2 warnings**（13.59 秒），`exweb-source-delta-canonical-pg-minio-20261007.log`（55090）已 0 退出；最终撤权检查加载后 **1 passed / 2 warnings**（16.96 秒），`exweb-source-delta-current-pg-minio-20261007.log`（82104）已 0 退出。当前独立报告 `exweb-source-delta-current-report-20261007.json` 固定 `cd919569... -> fe5827f...`，125→126 文件、1 added/1 modified/124 unchanged、无删除或 unresolved；Tool/PG/metadata-only Outbox/重新授权 Agent observation 回读均验证。binding 登记为明确 persistence fixture，真实 Git 对象只读归档，不运行 exweb/Maven、不调用外部模型/provider、不证明业务影响或维护者 gold。只清理本轮 MinIO keys，保留原共享 exweb report 的独占 writer；Boto3/Python 3.9 提示保留。
- Portal build/lint 已 0 退出，`source-delta-canonical-portal-build-20261007.log`（99748）/`source-delta-canonical-portal-lint-20261007.log`（29475），保留既有约 863 KiB chunk 提示；i18n 通过。未修改 Portal 生产代码，避免破坏仍运行的原全量 E2E 的 Vite 基线；当前无独立差异面板。
- 当前独立 PG smoke **success**，`source-delta-current-smoke-20261007.log`（35685）已 0 退出，API 加载本轮 canonical 实现；新平台 API/runtime/Compose **172 passed / 1 warning**（192.40 秒），`source-delta-platform-current-20261007.log`（16041）已 0 退出，保留 LangGraph serializer 警告。该完整新批次不抹去原平台红批次，也未放宽兼容等待门槛。原 168 项完整 E2E 与 exweb v2 finalization 的 exact handle 仍经核验存活；不重启、不提前记通过，也不把它们加载的旧 API 当作本轮差异工具验收。

完整 P4/P0-P6 仍开放：delta DAG/Derivation 反向闭包、query-scope 失效、跨域 stale、空源/全部删除、实体 lineage、overlay/tombstone、merge/回滚及持续自主调查都没有由这个只读比较入口替代。Provider 全生命周期/对照/gold/隔离、旧链 cutover、五用途、脚本/RunPlan/真实反馈及最终 V1 门禁继续保留。开发监督服务仍停止，本轮只启动隔离验证服务器，不把测试健康声称为开发服务已启动。

## 长校验下的 worker 续租修复与当前复验（2026-10-07）

上次继续执行被用户中断，未产生新工作。本次先核验旧 handle 和 OS 进程，确认不再运行后读取真正终态，没有把静默或观察超时当作失败并重启任务。

- 新 v2 exweb helper 长测 `mapping-finalization-exweb-current.log`（旧 69985）终态 **1 failed / 1 warning**（1943.19 秒），在恢复源批次的 claim 前 `GenerationLeaseLost`，没有走到新最终集合验收，不能用旧报告宣称 v2 成功。生产续租同时等待项目锁与命令行锁，而批次事务在这些锁内完整回读上下文，自身续租被阻塞；原 90 秒所有权检查正确拒绝过期 worker。
- 修复续租只锁精确 lease 行，使用 PG 时钟及原 project/invocation/owner/epoch/canonical digest/status 检查，仍拒绝过期或取消的工作；提交仍保留项目锁和全量权限/依据复核。事务 fence 从 PG 刷新 lease，不使用 identity map 中旧有效期。没有延长 90 秒租约、放宽 ACL、重新发送未知调用或伪造 fixture 同意。
- 增加实际 PG 中分别持有项目锁、命令行锁及两者时续租必须完成、同事务旧副本刷新，以及外来 owner/取消后不能续租的回归。当前 PG 专项 **11 passed**（158.43 秒），`generation-heartbeat-locks-pg-first.log`（5389）已 0 退出；仍不替代实际 exweb 长校验重跑。
- Portal 新分片私有读取、纯校验、来源/signer/head pin、独立 final consent、canonical 写路径与路由无 transport 的边界保护已补齐。纯领域/应用/分层/容器契约 **248 passed**（7.25 秒），`generation-heartbeat-pure-guards.log`；最后追加 trace 目录断言后边界/容器 **34 passed**（0.23 秒）。Portal build/lint/i18n 通过，`system-image-20261007-build.log` / `system-image-20261007-lint.log`，约 863 KiB chunk 提示仍保留。
- 每个隔离 PG browser run 获得独立 `output/playwright/runs/nasus_test_<uuid>`，失败 trace 不随临时 DB 清理删除，也不与其他 Playwright 进程共用输出目录。全量浏览器 **168 passed / 55.3 分钟**，`system-image-current-full-e2e-20261007.log`（28958）已 0 退出，固定干净 exweb SHA、隔离 PG/18152/14252。它加载早于后续影响查询和 0067，不证明新增端点；旧红批次、11 项协议专项和本批不混称通过。
- 固定 exweb v2 helper、真实 PG/MinIO 全链复验 **1 passed / 1 warning**（2961.83 秒），`system-image-exweb-finalization-20261007.log`（71490）已 0 退出，原 report 独占 writer 已结束。明确内部模型协议、资料与批准 fixture，不执行 exweb/Maven，不发外部模型；加载早于后续影响查询和 0067。
- 独立映射/原链兼容与实际 MinIO 专项 **44 passed / 2 warnings**（1388.17 秒），`system-image-mapping-pg-minio-20261007.log`（83411）已 0 退出；私有分片及最终工件实际 MinIO 回读已覆盖，不是目标执行、真实模型或性能验收。
- 原平台 API/runtime/Compose **3 failed / 169 passed / 1 warning**（301.72 秒），`system-image-platform-20261007.log`（37276）已 1 退出，三个质量闭环消息测试在既有 10 秒兼容等待内未结束。精确三项隔离复验 **3 passed / 136 deselected / 1 warning**（34.44 秒），`system-image-platform-turn-timeout-recheck-20261007.log`（98265）已 0 退出；这说明未单独复现，但不替代完整红批次，没有延长等待门槛或改为假回复。含本轮新增工具的当前全批另外运行，终态另记。
- 原独立 PG smoke **success**，`system-image-smoke-20261007.log`（38151）已 0 退出；差异工具基线的 smoke 另在上节记录。完整 E2E 与 exweb v2 helper 已终态通过各自范围，不声明新增 0067 或完整 V1 全绿。

当前完整 P0-P6 和最终 `verify:v1-release` 仍未完成；新长测结果、真实业务 gold/目标执行、容量/性能及原全部剩余范围继续保留。

## 独立断言映射与审阅草稿发现（0061，2026-10-03）

新增固定草稿 generation/context/scope 和每个 case/row/step/oracle 的独立映射审阅，保留 accept/reject/defer 和非空理由。PG 前驱/CAS/追加式历史、canonical 确认 actor/TTL、来源及依据复核、私有 MinIO、审计/Outbox 已接通。原 draft 和 planned CoverageMatrix 不改写；接受映射不批准 AC/规则，不增加 automated/executed/passed，不授权目标执行。独立知识页 reviewer 队列已接入项目草稿发现 API，不再依赖管理员生成历史、模型配置或 job 权限；原入口保持兼容。详见[映射契约](./test-design-mapping.md)。

- 映射领域/Agent/DDD/Portal 边界 **195 passed**（1.42 秒），`mapping-review-boundaries-final.log`；Portal build/lint/i18n 通过，保留既有大 chunk 提示。这是独立发现队列接入之前的批次。
- 两项纠正后的 API 契约 **2 passed**（54.93 秒），`mapping-review-contract-verified.log`；Agent receipt 另行 **1 passed**（23.07 秒），`mapping-review-receipt-debug.log`。旧三套 quality API 联跑终态 **1 failed / 54 passed**（781.30 秒），`mapping-review-quality-api-final.log`：502 拒绝正确，但测试把响应任何 `99` 当成篡改内容泄漏，随机 request_id 恰含 `99`。改为检查完整无敏感字段的错误结构，不放宽生产校验；该篡改/伪造 actor 专项修正后 **1 passed**（16.33 秒），`mapping-review-corrupt-verified.log`。包含新发现接口的整体复验另记，不能用单项替代全批。
- 平台 API/runtime/Compose **172 passed / 1 warning**（188.75 秒），`mapping-review-platform-regression.log`；隔离 smoke success，`mapping-review-smoke.log`。这些不是完整 V1 门禁。
- 原映射浏览器纯校验/浅色/深色 **3 passed**（1.0 分钟），`mapping-review-e2e-first.log`；固定 exweb 浅色另行 **1 passed**（56.8 秒），`mapping-review-exweb-e2e.log`。之后原全量批次 **75 passed / 23.9 分钟**，`mapping-review-full-e2e.log`，会话 53674 已 0 退出。此批早于独立 reviewer 队列与共享草稿组件抽取，不当作新增队列最终全回归。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` + 实际 PG/MinIO **1 passed / 1 warning**（790.30 秒），`mapping-review-exweb-first.log`。报告 `verified_at=2026-10-03T04:50:47.669666+00:00` 是运行开始时间：546 代码成员、三来源、8 草稿、2 约束/8 义务；独立混合 6 accept/1 reject/1 defer，再追加全部接受，MinIO/PG 回读、幂等、原草稿不变、历史不改写与 stale 拒绝均验证。来源权限和 reviewer 是明确 fixture，不是维护者业务批准；模型 transport 为协议夹具，未调用外部模型、运行 exweb 或安装 Maven/目标依赖，自动化/目标执行/通过均为零。此批不验证 Temporal，后续扩充真实发现 API 的 exweb 复验另记。
- 新草稿发现纯应用测试 **18 passed**（0.08 秒）；实际隔离 PG/API **4 passed**（73.64 秒），`review-discovery-api-first.log`：默认/最大页面、keyset、模型零调用、qa_lead 独立权限、撤回后的历史、look-ahead 损坏整页拒绝及读取中角色降级。带新 Portal 边界联跑 **159 passed**（1.23 秒），`review-discovery-boundaries.log`。
- 独立队列接入后的映射/结果/范围/发现 PG 整体复验 **59 passed**（835.81 秒），`review-discovery-quality-api-final.log`，会话 42399 已 0 退出；没有用单项修正冒充全批。纯应用/边界 **173 passed**（1.38 秒），`review-discovery-final-pure.log`；Portal build/lint/i18n 通过，隔离 smoke success，`review-discovery-smoke.log`。
- 扩展发现验证的固定 exweb + 实际隔离 PG/MinIO **1 passed / 1 warning**（820.98 秒），`review-discovery-exweb.log`，会话 96036 已 0 退出。报告 `verified_at=2026-10-03T05:23:43.785745+00:00` 仍是开始时间；三来源、546 代码成员、8 draft、2 原约束/8 义务，以及两条草稿发现、历史 scope 失效后仍可发现但不可执行均验证。原生协议请求仍只有一次，9823 为本地估算 token；临时对象清理为 true。没有外部模型、Temporal 或 exweb 目标执行，不能当作这些链路的新证明。
- 独立 reviewer 浏览器首批 **2 failed / 1 passed**，`review-discovery-e2e-first.log`：刷新后原 context/scope 串行验证超过测试默认 5 秒，页面仍处于明确 loading，未暴露未校验草稿。改为同一受保护读取链的 60 秒有界等待，不修改业务权限/完整性断言。复验 **3 passed / 2.8 分钟**，`review-discovery-e2e-verified.log`，会话 20587 已 0 退出：真实 PG 身份/qa 角色/三源/发布/context/scope，显式目录分页、确认重置、独立映射写入、零生成调用、错误 pin/hash/撤权隐藏和 390px 无溢出。catalog/result/review transport 是明确协议夹具，不是外部模型或目标执行。
- 人工查看上述移动截图发现独立队列失去父容器按钮 CSS，显示浏览器默认按钮；新增队列容器、复用既有知识面板主题/边框/按钮规则并增加计算样式断言，不另建重复视觉系统。修复后的专项 **3 passed / 2.7 分钟**，`review-drafts-agent-ui.log`，会话 49923 已 0 退出；重新目视检查浅色/深色移动截图，按钮主题/圆角恢复，不把旧截图当作样式验收。
- canonical Agent 发现查询已接入 ToolRuntime、typed ToolResult、当前 qa 角色门禁、12 项有界中英文工具发现和 observation fingerprint。回执只含分页 ID/digest；再次消费完整重验页、context/scope pins、原来源访问权及角色。新纯领域/handler/回执/RBAC/Agent/DDD/Portal **247 passed**（1.22 秒），`review-drafts-agent-pure.log`；实际隔离 PG/API **8 passed**（144.67 秒），`review-drafts-agent-api.log`，会话 73576 已 0 退出：viewer 拒绝、qa 自有会话、持久回执/幂等、零模型、新草稿使旧回执失效、撤权与降级拒绝。Portal build/lint/i18n 通过，`review-drafts-agent-build.log` / `review-drafts-agent-lint.log`，保留既有约 814 KiB chunk 提示。新平台/完整 E2E/exweb 回执扩展的终态另记，不用旧批次替代。

完整 P0-P6 保持原范围：供应商全生命周期/对照/gold/隔离、正式 source cutover 与 lineage、动态计划与累计预算、delta/overlay、五类 ContextPack、生成分包/多响应合并/租约、旧链切换、脚本/RunPlan、真实受控运行反馈和完整 V1 尚未完成。独立映射不再是“完全不存在”，但不能据此标 P5 或整个系统画像完成。

## 多批 canonical 入口与生命周期（0064 后续，2026-10-03）

新增只读 `query.quality.test_design_batches`，按全部固定义务预览 exact planning digest、测试模型/来源/operator policy 与完整累计预算，不发送来源。composition 将 native batch executor 接入相同 `quality.test_design.generate`、PG worker fencing、Temporal 活动、取消及历史；已经预留的 batch 不允许回落到旧单次路径。job 只返回预算/各批 presence/已知 usage，无正文；部分 archived 与 unknown 分开，未全部提交时无业务草稿。Portal 默认仍为一次调用，显式增加调用上限才预览多批；确认后使用同一 canonical 写链，v3 历史读取及独立映射不赋予运行权威。

- 真实 PG/ToolRuntime/三 AC/原生 HTTP 协议专项 **3 passed**（367.84 秒），`generation-batch-jobs-api-first.log`（70937）已 0 退出：全三批后原子完成、重复 worker 零新增出口、第二批断线后一次 archived/一次 unknown/一次 unstarted 且没有 partial draft、首批前确认取消零出口。该批 workflow dispatch 是明确 mock，不当作真实 Temporal 证明。
- 路由/旧 consent/账本/结果/租约/Agent/DDD/Portal 纯回归曾分别 **254 passed**（3.62 秒）、**246 passed**（3.37 秒）；预览 helper 最后重构的小集 **44 passed**（1.83 秒）。本轮加入 workflow patch、真实 Python 预览夹具及严格进度校验后，当前纯后端/DDD/Portal 集 **191 passed**（3.20 秒）。选择集重叠，不累加为测试总数。
- 跨语言检查发现 Portal 错把 9 字段预算要求为 10 字段，会拒绝合法 batch job；已修正，并禁止部分回复标 completed、超出已归档批次数量的 usage、释放预留和虚构 invoice。生产序列化 preview/digest/累计预算/状态篡改和临时三 AC 代码夹具的 Portal 联跑 **27 passed / 3.9 分钟**，`generation-batch-portal-lifecycle-first.log`（10792）已 0 退出。此批并非实际 exweb，也没有检查面板最小可用宽度，不能据此声明后续移动布局修复已验证。
- 原 Temporal 10 分钟窗口不能承载 64 次各 120 秒调用。新增 version patch：新活动 138 分钟、三尝试总调度 444 分钟、heartbeat 15 秒，旧 history 保留原 10/30 分钟；不改变实际 call/token/spend envelope。首轮真实独立队列 **1 failed / 4 passed**（573.60 秒），`generation-batch-jobs-temporal-verified.log`（86368）：重试故障注入错误挂在未使用的旧 `record` 方法，工作流完成但不能证明事务重试。改为 `record_batch` 后完整五项 **5 passed**（623.86 秒），`generation-batch-jobs-temporal-corrected.log`（32480）已 0 退出；该批尚未加载新增的当前 history Replayer 断言。随后该重试场景含当前 history 回放另行 **1 passed / 4 deselected**（229.36 秒），`generation-batch-current-history-replay.log`（87998）已 0 退出。两批不累加为测试总数，也不是多批终态独立恢复证明。
- 实际 Temporal 的旧契约 history 回放 **2 passed**（2.36 秒），`generation-batch-history-replay.log`：通过独立 UUID 队列生成原 10/30 分钟且无 patch marker 的 completed/failed fixture 历史，再用当前 workflow Replayer 验证；不执行回放活动或发模型请求。这不是用户旧生产历史或全部取消/恢复证明。当前 workflow/DDD/Portal 边界 **143 passed**（1.39 秒），`generation-batch-mobile-boundaries.log`。
- 实际干净 exweb 三 AC/一全局规则的浏览器复验先因硬编码三批失败 **4 failed**，`generation-batch-mobile-exweb-verified.log`（22739）已 1 退出。真实预算计划是两批，不通过改变拆包规则或删除 AC 迁就断言；测试现校验实际调用数及全部三个 AC。随后复验 **2 failed / 2 passed / 6.7 分钟**，`generation-batch-mobile-exweb-corrected.log`（52842）已 1 退出：light/dark 面板宽度仅 218px，知识页 className 缺少空格导致 scoped 去重 padding 未生效。修复类名并增加独立类名断言后全四项 **4 passed / 7.9 分钟**，`generation-batch-mobile-exweb-final.log`（9165）已 0 退出；保留面板 >=240px、输入 >=220px、单列和无横向溢出断言，已目视检查 light preview/dark result 移动截图。生成/生命周期 transport 仍为明确协议夹具，实际来源/身份/context/scope 为 PG，不是外部模型、后端 MinIO/Temporal 或 exweb 目标运行证明。
- Portal build/lint/i18n 通过，`generation-batch-lifecycle-build.log` / `generation-batch-lifecycle-lint.log`，保留约 829 KiB chunk 提示；移动修复基线另经 `generation-batch-current-build.log` / `generation-batch-current-lint.log` 0 退出。当前平台 API/runtime/Compose **172 passed / 1 warning**（159.39 秒），`generation-batch-current-platform.log`；隔离 smoke success，`generation-batch-current-smoke.log`；Runner **5 passed**，`generation-batch-current-runner.log`。不是完整 V1 门禁。移动专项结束后新全量 E2E 收集 **121 项**，`generation-batch-current-full-e2e.log`（68138）正在运行，使用隔离 PG/端口和干净固定 exweb，不提前记绿。
- 已安全终结旧开发监督会话 9960，确认 cleanup 后通过 `dev:foreground` 重载至 0064；新会话 19957，`generation-batch-current-dev-runtime.log`。Portal/API/Runner/Worker 与 PG/MinIO/Temporal 均 ready，三个 HTTP 检查 200。模型为 development fallback，不改用户模型设置、不注入虚构价格或模型出口。

多批终态独立恢复仍缺少版本化原结果/新恢复命令契约，因此 batch job 暂不提供 recovery_request，未知调用绝不重发。完整 P0-P6、旧链切换、其他用途、真实目标运行/反馈与最终 V1 保持原范围。

### 多批恢复的完整回执契约

新增内部 `nasus.test-design-batch-recovery.v1` DTO 和重新推导校验，固定原命令/request/reservation/plan 与完整逐调用 sequence、call ID、请求/响应/工件/usage/audit 摘要；不会把多批响应压成一条 synthetic call。请求不含正文、私有地址、凭据、批准或执行字段；缺批、未知回复、重复/乱序调用、错误 pin、篡改 usage/虚构账单及额外字段拒绝。恢复请求本身不是授权，也不能证明工件正文完整。私有 preparation 已要求独立新命令租约、每次原生工件读取前后重新授权、逐批摘要/usage 复核和完整原义务重新归并；不提交业务结果，不重发 Provider。

- 新恢复契约与原账本/结果联跑 **79 passed**（4.92 秒），`generation-batch-recovery-contract.log`（53027）已 0 退出。这是纯契约测试，没有 PG/MinIO、模型、ToolRuntime 或 Temporal 恢复调用。
- 扩展私有正文验证首批 **1 failed / 91 passed**（4.97 秒），`generation-batch-recovery-preparation.log`：测试正文和回执 usage 共享同一可变 dict，篡改正文时提前改变回执。改为隔离 deepcopy，并让错误 oracle 场景重新计算全部请求/工件/审计摘要后真正进入正文归并校验，没有降低任何完整性要求。一次复验因错误文件名未收集测试，`generation-batch-recovery-preparation-verified.log`，不是通过或业务失败。纠正选择集后 **235 passed**（7.23 秒），`generation-batch-recovery-preparation-current.log`（12037）已 0 退出。
- 新增 `GenerationBatchRecoveryPort` 与私有 PG preflight：项目/ACL 事务锁内检查原 failed、新 running 恢复命令、同一 active administrator、固定 request/scope/model row、PG 时钟 15 分钟新确认和独立租约 owner/epoch/request digest；从全部原 reply/audit 重新推导恢复 pins。旧原命令确认时间不继承为新授权，也不强制历史确认永久有效。共用 lease-state 检查，原公开单次 parser/路径不改变；尚未 composition/注册新的多批恢复输入，也不写 result/provenance/终态。
- 新私有 PG 首轮 **1 failed**（100.84 秒），`generation-batch-recovery-persistence-current.log`（42733）已 1 退出：测试授权回调未带原 actor_scope，被真实来源 fingerprint 校验拒绝。修正测试身份上下文而非权限规则；增加自洽伪造审计 pins 和未知回复负测。两项隔离 PG 复验 **2 passed**（141.40 秒），`generation-batch-recovery-persistence-verified.log`（92205）已 0 退出：真实 PG 校验、三份私有归档回读/完整归并、过期/错误确认、角色降级/账号禁用/丢失 owner/epoch/digest/租约、伪造审计及无归档回复拒绝；不产生 result、不重开原 failed、不发新模型调用。命令/租约与回复为明确 seeded fixture，工件为隔离运行器的本地私有 storage adapter，不当作公共 ToolRuntime/Temporal 恢复、实际 MinIO 或外部 Provider 证明。第一次启动缺失测试 PG 环境而未执行，`generation-batch-recovery-persistence-first.log`，亦不记绿。
- 新 private repository 加入后的纯边界集 **235 passed**（5.94 秒），`generation-batch-recovery-persistence-boundaries.log`（24123）已 0 退出；最新 fixture 后纯复验 **235 passed**（10.22 秒），`generation-batch-recovery-persistence-final-pure.log`（79442）已 0 退出。租约/恢复纯集另行 **61 passed**（3.85 秒），`generation-batch-recovery-lease-unit.log`（13511），选择集重叠不累加。共享 fence 的原单次恢复/租约 PG 兼容专项 **4 passed / 29 deselected**（58.65 秒），`generation-batch-recovery-single-compat.log`（70071）已 0 退出：公开旧单次恢复经过真实 canonical 确认，另有独占租约和修改命令/项目拒绝；不把旧单次链证明当作新多批 dispatch。尚未接通新 canonical dispatch、独立 lease claim/renew、原 failed 与恢复命令的原子 provenance、版本化恢复结果/历史回读或 Portal。现有 batch `recovery_request=null` 保持；完整多批终态恢复仍未交付。

## 版本化多批结果与原子草稿提交（0064，2026-10-03）

新增内部 `GenerationBatchResultApplicationService`、v3 私有归档/重新授权历史回读和 PG 逐调用 provenance。旧 result 增加 single/batch 显式类型，batch 不制造单条 call_id；原生 replies/LLM audit 保留，各批严格复核后按完整原义务归并，cases/coverage/逐调用关联/审计/Outbox 同事务。内部 native executor 可以 collect 后 commit 或直接回放已提交结果，不负责擅自结束 canonical 生命周期。v1/v2 保持旧单次容量，v3 是单独有界契约。详见[完整结果契约](./generation-batch-ledger.md#版本化完整结果0064)。

- 新纯格式/分母/lineage/540-case 不截断测试、原生采集/账本/预算/tokenizer/Provider/租约/范围/映射/审阅及 DDD/Portal **447 passed**（8.91 秒），`generation-batch-results-final-pure.log`；之前收敛选择集 **237 passed**（7.41 秒），`generation-batch-results-pure.log`，不累加计数。私有证据损坏、缺批、伪造调用/hash、额外 secret、布尔 usage、改变 oracle、虚构通过率或执行权威均拒绝。
- 三 AC/PG/原生 HTTP 首轮 **1 failed / 4 passed**（679.84 秒），`generation-batch-results-api-first.log`（40601）：新测试错误捕获 ValueError，而实际租约失效是 GenerationLeaseLost/RuntimeError；保留生产 fence，修正异常断言后全批 **6 passed**（546.77 秒），`generation-batch-results-api-verified.log`（41735）已 0 退出。覆盖完整 execute、Outbox 回滚后零额外出口、幂等、逐调用 FK/追加式表/安全 downgrade、缺回复、写工件后丢租约/ACL 变化和历史读取模型独立/撤权。
- 0064 迁移兼容、旧结果 API 与平台 **183 passed / 1 warning**（564.65 秒），`generation-batch-results-compatibility.log`（86645）已 0 退出。Portal v3 独立 view schema/hash、完整三原生调用/分母及篡改拒绝、qa reviewer 无管理员模型/任务读取专项 **16 passed**（59.7 秒），`generation-batch-results-portal.log`（7267）已 0 退出；实际 PG 身份/context/scope，生成/映射 transport 明确为协议夹具，不冒充 Temporal 或外部模型。
- 固定 exweb SHA/真实隔离 PG/MinIO **1 passed / 1 warning**（1624.89 秒），`generation-batch-results-exweb.log`（74654）已 0 退出。报告 `verified_at=2026-10-03T07:01:54.088561+00:00` 为开始时间：546 代码成员、三来源、一批 v3/8 draft/2 约束/8 义务，MinIO aggregate/native reply 回放、逐调用 audit/FK、幂等及新 head 后历史不变/current_use=false。batch native requests=0（直接内部 receipt 夹具），旧单次 HTTP fixture 仍 1；没有付费 Provider、目标运行、Temporal 或维护者业务批准。临时产物清理 true；保留 Python 3.9/Boto3 警告，不据此声称后续 formal batch 已被 exweb 后端全链验证。

五用途、动态调查/delta/overlay、Provider 完整生命周期和对照/gold、源注册正式切换、旧生成链 cutover、脚本/RunPlan、真实目标运行/反馈与最终 V1 仍属于原完整目标，未标为完成或上线。

## 完整分包预算与逐批回执（0063，2026-10-03）

新增内部 `GenerationBatchReceiptApplicationService`、严格完整预算 DTO、三个追加式 PG 表和私有 MinIO reply adapter。每批独立 claim/call/audit，完整确认参数和当前租约/来源/模型 fence；预留但无回复保持 unknown，禁止重发或退款。旧单次预留与分包互斥，全部原响应回读核验后才能供归并器使用。此层尚未 composition 到 Provider/Tool/Temporal/UI，也未交付版本化 aggregate result 和原子多批草稿提交。详见[分包账本契约](./generation-batch-ledger.md)。

- 首轮纯测试 **26 failed / 187 passed**（3.75 秒），`generation-batch-ledger-pure-first.log`：新 fixture 使用多 AC input，却仍填旧 scope hash；修正输入 pin，不放宽生产约束。复验 **213 passed**（3.57 秒），`generation-batch-ledger-pure-verified.log`；扩至范围/候选/预算/tokenizer/Provider/job delivery/DDD/Portal **327 passed**（4.63 秒），`generation-batch-ledger-pure-full.log`，会话 57396 已 0 退出。选择集重叠，不累加为项目测试总数。
- 首轮真实隔离 PG **4 failed / 6 passed**（325.01 秒），`generation-batch-ledger-api-first.log`，会话 2625 已 1 退出。三项 Outbox 回滚夹具错误按 project_id 查询无该字段的 AuditEvent；改为精确 invocation/entity 统计。另一项旧执行器测试错误调用不适用的假 tokenizer shape，改为在相同 canonical request 上直接核验预留互斥且出口 callback 不运行。修正后全批 **10 passed**（382.20 秒），`generation-batch-ledger-api-verified.log`，会话 32263 已 0 退出；不是以前六项替代全批。
- Portal build/lint/i18n 通过，`generation-batch-ledger-build.log` / `generation-batch-ledger-lint.log`，约 814 KiB 的既有 chunk 提示未消失。平台 **172 passed / 1 warning**（214.69 秒），`generation-batch-ledger-platform.log`，会话 93854 已 0 退出；隔离 smoke success，`generation-batch-ledger-smoke.log`，会话 38877 已 0 退出。扩充的 exweb PG/MinIO 回放 **1 passed / 1 warning**（1342.43 秒），`generation-batch-ledger-exweb.log`（71926）已 0 退出。
- exweb 新 helper 在已有单次失败/独立恢复与两条历史断言之后，追加精确 batch command/lease、整包预算、逐批私有归档/独立 audit/重复认领拒绝及原分母归并检查。只有一批，reply/usage 明确为夹具，不调用外部模型、Temporal 或 exweb 目标。该 receipt-only 命令没有 aggregate result，显式保留 failed，不伪造 completed。旧两条历史报告范围保持原样；临时私有对象纳入原清理清单。
- 随后新增内部 native collector，复用原生 Provider port，按精确确认计划逐批认领/发送/归档/校验，未知调用阻断下一批，坏回复不再消耗后续预算，所有原响应归并仍无 aggregate result 或 completed 命令。纯单元+分包/账本 **80 passed**（3.23 秒），`generation-batch-executor-pure-first.log`，会话 7473 已 0 退出。扩大联跑曾指定不存在的测试文件，`generation-batch-executor-pure-full.log`，exit 4/no tests；更正后扩大选择集 **428 passed**（5.62 秒），`generation-batch-executor-final-pure.log`。真实三 AC/PG/原生 HTTP 协议夹具的完整三批、第 0/1 批断线及回放 **3 passed**（488.99 秒），`generation-batch-executor-api-first.log`（34139）已 0 退出；批次在后续发送前拒绝不伪造 LLMCall 的收紧之前加载，收紧由最新纯测试/当前 API 复验。上述平台、smoke、exweb 批次在 collector 新增前加载，不冒称覆盖该模块。
- 0063 报告 `verified_at=2026-10-03T06:36:54.693071+00:00`：固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`，三来源、546 代码成员、2 约束/8 义务，batch ledger 一批、本地估算 8757 token，MinIO 私有 reply/独立 call audit/重复 claim 拒绝/完整原义务通过。`aggregate_result_committed=false`、该 ledger native request 为 0，旧单次 HTTP fixture 仍一次；`target_executed=false`，临时对象清理 true。不能当作随后 0064 或外部模型/账单/业务 gold 证明。
- 含真实 Temporal 的 0063 quality/租约/单次兼容/分包 ledger/native collector 扩大回归 **92 passed**（2712.82 秒），`generation-batch-executor-quality-regression.log`（18299）已 0 退出；它在 0064 前加载，不冒称新多批结果验证。同期完整 Portal **76 passed / 2 failed**（31.7 分钟），`generation-batch-ledger-full-e2e.log`（68474）已 1 退出：reviewer 两项要求真实 origin，但运行参数指向无 origin 的快照目录。保留断言和红记录；已核验实际干净 exweb Git 缓存 origin 与固定 SHA，使用它复验 **3 passed / 3.2 分钟**，`generation-batch-review-exweb-corrected.log`（46493）已 0 退出，不将专项或环境解释当作全量通过。
- 原监督会话 97570 经精确 PID TERM 后 143 退出并完成 cleanup；新 `dev:foreground` 会话 9960，`generation-batch-ledger-dev-runtime.log`，已迁移至 `0063_generation_batch_ledger (head)`。Portal/API/Runner HTTP 200、`dev:status` 全 ready；Docker 仍只承载外部 PG/MinIO/Temporal。collector 未 composition，不改变当前正式单次生成入口，不修改用户模型配置或设置虚构价格/出网策略。

完整多批原生执行和结果提交、五用途、动态调查/delta/overlay、Provider 完整生命周期和对照/gold、源注册正式切换、旧生成链 cutover、脚本/RunPlan、真实目标运行/反馈与最终 V1 仍开放。0063 是完整目标的持久化前置，不是完成或上线声明。

## 分包准备与生成 worker fencing（0062，2026-10-03）

先增加完整分包/归并准备契约，再为现有 canonical 生成和独立恢复接入 PG worker 租约，不把多个 model reply 伪造为单次调用。分包基于全部固定 AC/规则、连通的风险义务、全局约束及原支持证据，按可信 tokenizer/policy 预留整个调用 envelope；严格逐批校验并重新核对原分母。该内部准备服务仍无模型出网、HTTP/Tool/UI 入口及持久多批结果；v1 聚合上限未绕过。详见[生成契约](./test-design-generation.md#模型分包与完整归并的准备契约)。

0062 新增 `quality_test_design_work_leases`：PG 时钟 90 秒租约、15 秒续租、精确 canonical digest、随机 owner/递增 epoch、项目锁内 claim 与提交 fence。重复活动不能将仍在生成的任务提前失败；失去租约取消 adapter，并在回复及结果事务中拒绝迟到写入；取消使租约失效，旧 worker 不能释放接替者。未知预留不退款或重发，已归档回复可由新 owner 继续校验提交。不是新任务生命周期或多批费用权威。详见[任务契约](./generation-jobs.md#跨进程-worker-租约0062)。

- 上轮 canonical reviewer 回归：平台 **172 passed / 1 warning**（155.61 秒），`review-drafts-agent-platform.log`；隔离 smoke success，`review-drafts-agent-smoke.log`。固定 exweb 的三源/546 代码成员/8 draft/独立映射及发现回执回放 **1 passed / 1 warning**（900.72 秒），`review-drafts-agent-exweb.log`，会话 86167 已 0 退出；报告开始时间为 `2026-10-03T05:51:28.226591+00:00`，9778 是本地估算 token，原生 fixture 请求仍一次、临时对象清理 true。它不覆盖随后分包与 0062。
- 分包纯领域、真实固定 tiktoken、operator policy、Provider 协议及 DDD/Portal **286 passed**（3.13 秒），`generation-batches-pure-verified.log`。首轮分包 PG 只读断言失败，`generation-batches-api-diagnostic.log` **1 failed**（17.01 秒）：错误把建画像已有的 6 次模型调用当成预览新增调用，改为比较前后调用数，保留零预留/回复/结果与零 native 请求。没有改变生产行为或放宽必选来源。
- 新租约纯测试首轮 **1 failed / 219 passed**（3.54 秒），`generation-leases-pure-first.log`：digest 验证误使用画像异常类型；改为此租约契约自己的 ValueError。扩大到分包、tokenizer、原生 Provider、job delivery 和分层边界复验 **301 passed**（3.36 秒），`generation-leases-pure-verified.log`，会话 25126 已 0 退出。Portal build/lint/i18n 通过，`generation-leases-build.log` / `generation-leases-lint.log`，保留约 814 KiB chunk 提示。
- 新 PG fencing 首批 **1 failed / 9 passed**（168.54 秒），`generation-leases-api-first.log`：第二项误查询不存在的单项 job HTTP 路由，已改为现有 canonical job query；复验 **10 passed**（196.52 秒），`generation-leases-api-verified.log`，会话 79250 已 0 退出。平台 **172 passed / 1 warning**（232.04 秒），`generation-leases-platform.log`，会话 62281 已 0 退出；隔离 smoke success，`generation-leases-smoke.log`。包含真实 Temporal 的全量 quality/租约回归 **79 passed**（1463.14 秒），`generation-leases-api-regression.log`，会话 64713 已 0 退出；其加载的 schema/source 早于 0063，不当作分包账本最终全回归。
- 0062 固定 exweb + 隔离 PG/MinIO **1 passed / 1 warning**（1059.19 秒），`generation-leases-exweb.log`，会话 45698 已 0 退出。报告开始时间 `2026-10-03T06:13:25.748868+00:00`：546 个代码成员、三源、8 草稿、2 约束/8 义务；单次估算输入 9838 token，分包准备估算 8896 token，只形成一批。单次 MinIO 响应恢复不重发及完整准备分母通过；`multi_call_execution_enabled=false`，未证明随后 0063。伴随文档/审批/模型为明确夹具，不经 Temporal、不调用外部模型或执行 exweb，临时对象清理 true。
- 生成/映射/reviewer Portal 专项 **10 passed / 9.6 分钟**，`generation-leases-ui.log`，会话 18891 已 0 退出。此前同一前端的全量浏览器 **78 passed / 28.6 分钟**，`review-drafts-agent-full-e2e.log`，会话 3819 已 0 退出；其 API 在 0062 前加载，不混称为 0062/0063 原生执行证明。旧分包 API 批次 **1 failed / 63 passed / 2 skipped**（1198.50 秒），`generation-batches-api.log`，会话 37626 已 1 退出；只读调用计数 fixture 错误已修正，由上述当前全量复验重新验证，不将旧批次记绿。

完整模型多批执行/原生回执/版本化归并提交/累计预算、其他 provider/build/index 路径的租约、旧链 cutover、五种用途、脚本/RunPlan、真实目标运行和反馈及原 P0-P6 其余要求仍未完成。0062 只推进真实生成活动的跨进程恢复安全，不缩小完整目标或标为上线验收通过。

## 生成任务、取消与终态恢复（0060，2026-10-03）

canonical 生成确认改为持久派发后返回 running，Temporal 活动承担原生生成、heartbeat 和有界重试；原生预留与归档回复保证重试不重发。新增 job 元数据查询、独立确认式取消与原 actor 的精确恢复命令。failed 源命令保持原样，恢复只处理已有私有回复，v2 草稿记录独立恢复权威。当前管理员可以停止停用账号的任务，不能继承其 egress consent。取消投递有 PG receipt 和游标分页 reconciler，已经提交的草稿不能被迟到取消抹掉。契约见[持久生成任务](./generation-jobs.md)。

- 首轮显式终态恢复失败，`generation-jobs-first-api.log`（1 failed / 1 passed）和 `generation-jobs-recovery-debug.log`（1 failed）：共享 MinIO adapter 原来只接受 v1，而新恢复结果为 v2。修正为本结果 adapter 显式允许 v1/v2，其他工件仍维持原单版本边界；未放宽 canonical authority 或让未知调用重发。
- 修复后显式恢复与真实 Temporal retry 专项 **2 passed / 19 deselected**（60.82 秒），`generation-jobs-recovery-verified.log`。真实 Temporal 活动两次尝试仅发生一次 native HTTP fixture 请求；异常敏感文本没有进入 history。此批早于管理员接管取消的最后改动，最终生命周期批次另记。
- 纯领域/executor/operator policy/分层及分页投递复验 **206 passed**（3.17 秒），`generation-jobs-final-pure.log`；包含 105 项分页和单项 poisoned delivery 不阻断后页。Portal build/lint 通过，`generation-jobs-portal-build.log` / `generation-jobs-portal-lint.log`，保留既有大 chunk 提示。
- 最终隔离 PG 生命周期专项 **23 passed**（490.70 秒），`generation-jobs-final-api.log`，显式启用真实 Temporal，执行进程已以 0 退出。覆盖活动重试、生成中取消、确认 TTL、来源/账号/模型/范围竞争、未知预留禁止重发、独立终态恢复和管理员接管取消。Provider 使用明确 HTTP 协议夹具，不是外部真实模型或业务准确率证明。修复前联跑 `generation-jobs-api.log` 终态 **1 failed / 20 passed**（477.33 秒），v2 storage 拒绝保留在记录中。
- 首轮跨模块回归 **27 failed / 159 passed / 1 warning**（475.95 秒），`generation-jobs-regression.log`，不是测试等待：范围/画像批准写入的 `approved` 审计状态不被平台 `AuditEvent` DTO 接受，导致全局审计读取和 Agent 观察失败。只为审计 DTO 显式补充 `approved/rejected/withdrawn`，不改变 ToolInvocation 状态或放宽为任意字符串。新增实际范围批准/撤回后的 HTTP 审计读取和 PG 不可变状态测试，专项 **5 passed / 11 deselected**（13.90 秒），`generation-audit-contract.log`。
- 同一生成结果/预检查/API/runtime/Compose 联跑修复后 **186 passed / 1 warning**（376.98 秒），`generation-jobs-regression-verified.log`，执行进程已以 0 退出。保留既有 LangGraph serde 提示；此选择集不是完整 V1 门禁。
- 0060 固定 exweb + 隔离 PG/MinIO **1 passed / 1 warning**（744.75 秒），`generation-jobs-exweb.log`，进程已以 0 退出。报告 `verified_at=2026-10-03T03:36:36.974523+00:00`：546 个代码成员、三来源、8 个草稿、2 原约束/8 义务；原命令真实保留 failed，通过独立新 canonical command 恢复 v2 归档，原生 HTTP fixture 请求总计 1 次，没有重发。9845 是本地 tokenizer 估计，不是 Provider 计费。此 exweb fixture 不经 Temporal；Temporal 由前面的 API 专项验证。
- exweb 伴随需求、审批和模型响应仍是明确合成验证资料，不是维护者业务批准或 gold；未执行 exweb/Maven/目标依赖、未调用外部付费模型。独立映射/目标执行/通过均为零，临时 PG/MinIO 产物清理，保留 Boto3/Python 3.9 提示。
- Portal 固定预算、独立确认、生命周期读取、取消、新命令归档恢复及草稿检查专项 **3 passed / 1.7 分钟**，`generation-ui-e2e-verified.log`，执行进程已 0 退出。首批 **2 failed / 1 passed**，`generation-ui-e2e.log`：英文状态标签实际为 `cancelled`，测试错误匹配 `Cancelled`，修正大小写，未修改业务取消语义。当前 scope 变更和完整性/来源访问失败隐藏保护内容；终态同步历史，避免原 running 状态永久阻止下一次确认；轮询同一状态不抹掉精确取消确认。
- 固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的浅色同流程复验 **1 passed / 1.2 分钟**，`generation-ui-exweb.log`，执行进程已 0 退出。扩大截图视口后完整桌面入口不再被 sticky toolbar 裁剪，390px 移动端无横向溢出；已人工检查浅色桌面/移动端截图。旧深色桌面截图仍存在顶部截图裁剪，新的完整 E2E 将使用修正后的视口再取证。
- 浏览器使用真实隔离 PG 的身份/三源采集/画像发布/上下文与范围；生成、模型和生命周期 transport 是明确 UI protocol fixture。原生 HTTP/Temporal/MinIO 由前面的独立专项覆盖，不把组合夹具当成浏览器已执行真实模型或目标代码。范围审阅者和业务期望仍不是 exweb 维护者 gold。
- 最新 Portal build/lint/i18n 通过；DDD/Portal 检查 **140 passed**，`generation-ui-boundaries-final.log`，保留 >500 KiB bundle 提示。隔离 smoke **success**，`generation-ui-smoke.log`。含新 3 项的完整浏览器批次 `generation-ui-full-e2e.log`，会话 50548 已以 0 退出，**69 passed / 21.8 分钟**；已检查修正后的深色桌面/移动截图。本批前端尚未切换分页、API 在新增历史 Tool ID 前加载，不混称为后续分页版本已完成全回归。
- 开发服务已经 `dev:foreground` 从 0059 重载至 `0060_generation_jobs (head)`，监督会话 98077；Portal/API/Runner HTTP 200、`dev:status` 全部 ready，`nasus-agent-goals-test-design-generation` 的 workflow/activity poller 各 1。Docker 仍仅承载 PG/MinIO/Temporal，未改用户模型设置或注入虚构出网/价格策略。
- 后续范围查询优化消除 inspect -> read 的重复 ContextPack 重建；旧代码单次 exweb inspect 约 7.15 秒，不能将重复调用减少当成 p95 <=2 秒已达标。首批 API **1 failed / 16 passed**（156.29 秒），`scope-single-context-api.log`：撤权已返回 409，但新断言错误读取错误 envelope，改为实际 `detail.error.code=source_access_changed`，未放宽来源权限。新分页生成历史 API 与范围复验正在运行，结果另记。完整分包归并、独立 mapping、旧链切换及完整 P0-P6 仍开放。

## 生成历史容量与查询复验（2026-10-03）

新增按项目、固定 scope revision/hash 的只读分页 API，默认 20、最多 50，PG 筛选 canonical 生成/恢复命令；不读取全站审计或返回完整 input payload。`has_running` 检查整个匹配范围，不把第一页没有 running 当成可再次生成。补齐 `query.quality.test_design_jobs` 和 Agent 查询观察重验，保留独立生成/取消/恢复确认。持久命令 DTO 损坏统一返回脱敏完整性错误。完整语义见[任务历史契约](./generation-jobs.md#有界历史读取)。

- 分页/范围专项首轮 **1 failed / 20 passed**（221.23 秒），`generation-history-scope-api.log`；两个测试使用相同固定 fixture command ID，产生 PG 主键冲突。改为项目隔离 ID，未更改唯一性约束。复验 **21 passed**（216.90 秒），`generation-history-scope-api-verified.log`，进程已 0 退出；同时证明 scope inspect 的四种状态只读取一次 ContextPack，返回前撤权仍返回 409。
- canonical 分页查询、Agent 回执状态变化重验及既有分页权限/损坏命令 **5 passed**（77.18 秒），`generation-history-agent-api.log`，进程已 0 退出。无模型调用，已排队命令未被再次派发。
- Provider/任务生命周期回归 **23 passed**（407.53 秒），`generation-history-lifecycle-regression.log`，显式真实 Temporal、无 skip；原生请求仍是明确 HTTP fixture。本批在新增历史 Tool ID 前加载 API，不能证明新工具集成，由上面的 5 项另行证明。
- Agent 工具发现、分层、Portal 和分页投递 **179 passed**（1.64 秒），`generation-history-agent-boundaries.log`；工具发现继续保持 12 项上限，中英文历史查询可发现，不挤出普通生成或 run 操作。
- 前端分页 DTO 校验专项 **2 passed**（2.8 秒），`generation-history-protocol-e2e-verified.log`，仅协议函数检查，不能当作分页页面已交付。第一次启动使用了完整批次占用的端口，`generation-history-protocol-e2e.log`，未执行测试；该失败进程终结后在独立端口复验，没有停止或复用其他批次的测试数据库。
- 平台 API/runtime/Compose **172 passed / 1 warning**（156.58 秒），`generation-history-platform-regression.log`，会话 29778 已 0 退出；覆盖最新历史 Tool 集成，保留既有 LangGraph serde 提示。
- 固定干净 exweb SHA `fe5827f6b76f77ef34918d8b452ee823142332dc` 的 PG/MinIO 分页回放 **1 passed / 1 warning**（707.92 秒），`generation-history-exweb-verified.log`，会话 69700 已 0 退出。报告 `verified_at=2026-10-03T04:18:31.000310+00:00`：546 代码成员、3 来源、8 draft cases、2 原约束/8 义务，按 limit=1 游标读出原失败与独立恢复两条命令，`bounded_generation_history_verified=true`；原生 HTTP fixture 仍只调用 1 次，MinIO 回读通过。9737 是本地 tokenizer 估计而非实际账单；不经 Temporal、不调用外部模型、不执行目标仓库，映射/运行/通过数仍为 0。首次指向错误 probe 路径，`generation-history-exweb.log`，**1 failed**（0.69 秒）；修正路径才复验。临时 PG/MinIO 产物清理，保留 Boto3/Python 3.9 提示。
- 既有 69 项完整 E2E 终态后才切换 Portal `useInfiniteQuery`，移除全站 invocation 读取；默认 20 条和显式下一页，未加载运行任务阻止重复生成，新确认命令在第一页之外也能保持选中。新 Portal build/lint/i18n 通过，`generation-history-ui-build.log` / `generation-history-ui-lint.log`；Agent/DDD/Portal/分页投递 **179 passed**（1.31 秒），`generation-history-ui-boundaries.log`。
- 分页 Portal 专项 **6 passed / 1.8 分钟**，`generation-history-ui-e2e.log`，会话 31134 已 0 退出：原 3 项、协议 2 项与新增分页页面 1 项。覆盖 35 条分页、不自动请求后页、后页运行标记阻断新生成、独立取消、刷新后只加载第一页、新确认任务在首屏外仍选中、坏下一游标/撤权隐藏全部缓存和草稿；全站旧历史读取次数为 0。390px 深色无横向溢出；仍为明确生成 transport fixture，不能当真实模型/业务 gold。隔离 smoke **success**，`generation-history-ui-smoke.log`，会话 43115 已 0 退出。
- 同一分页前端基线的固定 exweb 浅色专项 **1 passed / 1.2 分钟**，`generation-history-ui-exweb.log`，会话 87991 已 0 退出。已检查完整桌面和 390px 分页移动截图，沿用现有细边框/主题；没有把 UI fixture 草稿当作 exweb 真实生成或测试结果。最新完整 E2E 已收集 **72 项**，`generation-history-ui-full-e2e.log`，会话 67389 当前经精确句柄确认仍在运行，尚未宣布通过。
- 等旧监督会话 98077 真正终结和 cleanup trap 完成后，本机 `dev:foreground` 重载到同一 `0060_generation_jobs (head)`，新监督会话 85120 持续运行，`generation-history-dev-runtime.log`。Portal/API/Runner HTTP 200、`dev:status` 全 ready，OpenAPI 含 scoped history API，实时 Tool Catalog 含 `query.quality.test_design_jobs`。新 Worker 的生成队列 workflow/activity poller 均有当前轮询；DescribeTaskQueue 同时保留旧已停止 Worker 的历史条目，不将它算作第二个活进程。全新 CLI 浏览器实际渲染登录页，console errors/warnings 为 0，已关闭该测试浏览器；旧热更新日志的 I18nProvider 错误不当成新运行时已复现。Docker 仍仅 PG/MinIO/Temporal/UI，未修改用户模型配置或注入出口/价格策略；chat 仍为 live deepseek，embedding/rerank 为开发 fallback，并未用实时路由发起模型调用。

完整 P0-P6 不变：此切片不交付多响应分包、独立映射批准、旧链切换、真实业务 gold、五种用途、脚本/RunPlan 或目标执行反馈，也未证明非模型查询的 p95 性能门禁。

## 原生生成预算与响应恢复（0059，2026-10-03）

新增 `query.quality.test_design_execution` 预算预览和确认式 `quality.test_design.generate`，供 canonical ToolRuntime/Agent 使用。固定已归档 context/scope、测试通过的保存模型、全部 manifest 来源及当前 ACL、管理员 tokenizer/价格策略、完整 prompt 摘要和费用 envelope；不使用 active route、假价格、fallback 或为了容量丢掉必选内容。0059 追加 PG 调用预留与私有原生响应回执，接入 0058 草稿用例/覆盖原子提交。响应已归档但草稿事务失败时仅恢复原响应；未确定的调用不重发、不释放预留。完整契约见[生成契约](./test-design-generation.md)。

此交付当前只执行一份完整模型输入，**不是完整 P5**。超过 tokenizer/capacity/wire 预算时明确阻断，尚需完整模型分包、多响应归并、Portal 专用生成入口、Temporal 生成任务/租约/取消恢复和旧生成链切换。独立映射审阅、五类 ContextPack、脚本/RunPlan pin、真实目标执行及反馈仍是原目标，不因新增 Tool ID 或计划覆盖数而完成。

- 安全负测先复现 **7 failed / 11 passed**，`generation-execution-authorization-red-final.log`：返回后/工件写入后的撤权、恢复读取前来源检查、usage 回执错配，以及非法计数导致失败审计异常。真实 PG 红测 **1 failed**（15.94 秒），`generation-execution-receipt-red.log`，确认账号禁用后草稿虽被拦，成功响应回执却已落库。修复将当前检查前移至私有写入前并加入 PG 提交锁内，不放宽审批、source ACL 或结果不确定性要求。
- 修复后纯领域、四类 Provider 协议、固定 tokenizer 策略、历史输入、Agent 工具发现与 DDD/Portal 边界 **237 passed**（1.96 秒），`generation-execution-pure-final.log`。Provider 使用 HTTP transport 夹具，无真实外部生成消费。Portal build/lint 和 i18n 通过；既有 >500 KiB chunk 提示仍保留。隔离 PG/端口 smoke **success**，`generation-execution-smoke.log`。
- 平台 API/runtime/Compose 修复后回归 **172 passed / 1 warning**（204.56 秒），`generation-execution-platform-final.log`，保留 LangGraph 既有 serde 提示。早期生成/结果/预检查 PG 联跑 **19 passed**（303.38 秒），`generation-execution-final-api.log`，在上述权限加固之前，不能作为最后竞争场景已验证的证明。新增账号/模型/来源/范围的两阶段竞争场景正在扩展复验，以终态另记；初版来源夹具误调用 `snapshot`，已改为真实 `load_snapshot`，没有修改生产授权端口绕过检查。
- 首轮 exweb + 隔离 PG/MinIO **1 passed / 1 warning**（701.41 秒），`generation-execution-exweb.log`。固定 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc` 和 546 代码成员；报告 `verified_at=2026-10-03T02:59:58.378474+00:00` 新增 `native_test_design_generation`：三来源、真实固定 tiktoken 资产与 9708 本地估计输入 token、一次原生 HTTP 协议请求、MinIO 原始响应回读、8 草稿案例、2 原约束/8 义务、新 head 后历史不变及 current_use=false。已独立映射、目标执行、通过仍为零。此批在权限加固前启动；最终代码另跑 `generation-execution-exweb-final.log`，不提前将未结束批次计为通过。
- exweb 伴随需求、范围批准、模型响应和 Provider usage 均为明确测试夹具，9708 是本地 tokenizer 计数而非发票/Provider 实际消费。没有调用外部付费模型、执行 exweb 或获得维护者业务批准；测试清理临时 PG/MinIO 产物，报告对象不是开发库常驻项目。保留 Python 3.9/Boto3 弃用提示。
- 0059 最终 exweb + 隔离 PG/MinIO **1 passed / 1 warning**（888.29 秒），`generation-execution-exweb-final.log`；报告 `verified_at=2026-10-03T03:12:19.805610+00:00`。仍是三来源、546 代码成员、一次 native 协议 fixture、9708 本地估计输入 token 和 8 draft cases，映射/目标执行/通过均为零；这批不覆盖随后 0060 终态恢复。
- 0059 完整浏览器回归 **66 passed**（23.8 分钟），`generation-execution-full-e2e.log`，独立 PG/端口和干净固定 exweb，进程已以 0 退出。不能以该批证明随后 0060 或完整 V1 门禁通过。
- 0059 原始响应恢复端口要求原 invocation 仍为 running，原同步 handler 失败后不会因再次 confirm 重启。此历史限制已由上方 0060 独立恢复命令推进；原 failed 历史依旧不可改写，未知回复依旧不能重发。
- 开发服务已经 `dev:foreground` 重新加载 0059（监督会话 10234），Portal/API/Runner `/readyz` HTTP 200、`dev:status` 全 ready，实时 Tool Catalog 包含预算预览及 `user_confirm` 生成命令。Docker 仍只承载 PostgreSQL/MinIO/Temporal，模型路由保持 development_fallback，不向开发配置注入虚构价格或出网许可。
- 权限加固后的扩展 PG 批次终态 **25 passed / 2 failed**（607.16 秒），`generation-execution-secured-api.log`：两个来源场景因上述夹具调用不存在的 `snapshot` 而失败，不记为绿色。修正夹具后生成执行专项 **13 passed**（358.57 秒），`generation-execution-final-verified-api.log`，包括来源/账号/模型/范围两阶段竞争、确认 TTL、预留防重发、Outbox 回滚和 0059 破坏性降级保护。追加真实 canonical 终态恢复限制专项 **1 passed**（28.96 秒），`generation-execution-terminal-recovery.log`：保留原生响应，但失败命令重确认或直接内部调用均不重启/重发。两个专项分开记录，不将内部恢复误报为正式任务恢复。

## 生成结果与覆盖原子归档（0058，2026-09-20）

新增可信执行器内部提交端口、私有内容寻址结果工件、PG 草稿用例与 CoverageMatrix、同事务审计/会话 Outbox，以及重新授权的只读结果 API。严格绑定已确认 canonical actor/request、测试模型 config digest 和成功原生调用审计的请求/响应 hash；事务内重新验证来源、独立期望、scope/publication、账号及模型。三表不可变；重复结果不重写、不同结果不覆盖；gap 原样保留，不把生成数量当成已验证覆盖。历史输入重放与当前生成授权分开，撤回后仍可读取原结果但不得当前使用。详见[生成契约](./test-design-generation.md)。

0058 交付时没有公开 generation Tool handler 或 POST import 入口。0059 后续已接入确认式 canonical handler、预算与持久调用预留，仍没有任意结果 JSON import 入口；完整模型分包、Temporal 生成任务和旧链迁移仍属于完整目标。当前只支持一个完整响应对应一个调用事实，禁止为了适配该端口删减上下文。

- 最终纯领域/历史输入契约/Agent 工具发现/DDD/Portal 边界 **240 passed**（1.59 秒），`test-design-results-final-pure.log`；较早 205 项为其子集，不累加。Portal build/lint/i18n 通过；保留既有 >500 KiB chunk 提示。独立 PG smoke success，`test-design-results-smoke.log`。
- 完整结果/预检查/范围 PG/API 复验 **25 passed**（440.76 秒），`test-design-results-api-verified.log`，会话 63289 已 0 退出。覆盖原子提交、幂等竞争、撤回回放、原生调用精确绑定、Outbox/当前依据/模型/账号竞争回滚、ACL、私有工件篡改、gap 保留和破坏性降级保护。首轮 **7 failed / 3 passed**（193.12 秒），`test-design-results-api.log`，七项均为新测试错误读取不存在的 `SSEEventOutboxRecord.correlation_id` 列；真实字段在 `event_payload` JSON。修正测试查询后通过，未放宽事务回滚或权限断言。
- 新 exweb PG/MinIO 回放 **1 passed / 1 warning**（703.94 秒），`test-design-results-exweb.log`，会话 39209 已 0 退出。固定 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc`，报告 `verified_at=2026-09-19T17:36:53.271247+00:00`；结果 hash `sha256:4ce4c502d4ab387628505b71bd2349a27cfa27d721b5653e22342638833cec46`。归档 8 个草稿用例，保留 2 项原约束/8 项义务的 planned 分母；独立映射、目标执行和通过数仍为 0。真实 MinIO 回放和 PG 投影一致，同 invocation 恢复幂等，新 publication 后历史正文不变且 current_use 失效。伴随要求、审阅、模型响应及 native-success 审计均为明确合成协议夹具，usage 数不是外部实际消费；没有调用真实生成 Provider 或运行目标仓库。临时 PG/MinIO 产物已由测试清理，报告 ID 不是开发库常驻对象；保留 Boto3/Python 3.9 警告。
- 平台 API/runtime/Compose **172 passed / 1 warning**（236.35 秒），`test-design-results-platform.log`，会话 15770 已 0 退出。上轮完整 E2E **57 passed / 21.9 分钟**，`test-design-generation-full-e2e.log`，52535 已 0 退出，不把该旧进程当作包含 0058 的新测试。当前代码新完整 E2E 是 `test-design-results-full-e2e.log`，会话 85669，已启动待终态。
- 本机通过 `dev:foreground` 重启到 0058 head（监督会话 14819），API OpenAPI 已含新结果读取路径；Portal/API/Runner HTTP 200，Worker/PG/MinIO/Temporal 就绪。Docker 只承载基础组件，未向开发业务库注入测试资料；Embedding/Rerank 仍为开发 fallback。

## 测试生成输入与覆盖契约（2026-09-20）

新增 quality_loop 生成预检查 use case，通过 `resolve_inputs` 同一次验证固定 scope/context，而非可变 TaskContext。完整保留原 AC/规则 oracle、额外风险/权限/状态/不变量及正反例；模型 DTO 必须逐项映射或声明 gap，每个候选继承全部 global rule，禁止改写 oracle、越界引用和伪造执行/批准字段。CoverageMatrix 单独保留原约束和扩展义务分母，重复用例不增加覆盖数；目前仅为 planned 与待独立审阅映射，执行/通过始终为零。参见[生成契约](./test-design-generation.md)。

新增 private/no-store HTTP generation-preview 和 canonical `query.quality.test_design_generation`，只暴露 ID/hash/数量回执，Agent 再次消费时重验来源访问权及当前依据。预检查不发模型请求、不持久化案例；后续内部归档实现见 0058 一节，预算化正式执行和用户入口仍待实现。

- 最后纯领域、Agent 工具发现、DDD/Portal 边界 **234 passed**（1.77 秒），`test-design-generation-final-pure.log`。覆盖全部义务、独立期望、未知缺口、引用/重复/JSON 篡改、global rule 继承、只计计划不计运行、回执更改以及中英文预检查发现。早期重复集合不累加。
- 隔离 PG/API **14 passed**（196.55 秒），`test-design-generation-api-verified.log`：canonical 查询与回执、归档来源、withdraw、gap、错误 hash、ACL 和 publication/head 变化。第一批 **1 failed / 13 passed** 是新测试错误地读取 `error` 而不是既有 FastAPI `detail.error`；409 行为正确，修正断言后通过。最后增加每案例 global 继承字段后的 API 复验 **3 passed**（63.55 秒），`test-design-generation-final-api.log`。
- Portal build/lint/i18n 均通过；隔离 smoke success，`test-design-generation-smoke.log`。保留现有构建 chunk 提示，不是完整 V1 发布门禁。
- 上一轮范围 UI 完整固定 exweb E2E **57 passed**（20.9 分钟），`test-design-scope-portal-full-e2e.log`，会话 69109 已 0 退出；深浅色完整风险表单截图已检查，之前的视口裁剪问题未再出现。这个批次在本轮后端生成契约之前启动。后端契约稳定后的完整 E2E **57 passed / 21.9 分钟**，`test-design-generation-full-e2e.log`，会话 52535 已 0 退出；这是 0058 之前的批次。
- 固定 exweb 的 PG/MinIO 新回放 **1 passed / 1 warning**（594.22 秒），`test-design-generation-exweb.log`，会话 33258 已 0 退出。报告 `verified_at=2026-09-19T17:15:39.397954+00:00`，`test_design_generation_contract.input_digest=sha256:0ce26a9b7e5e0d41b6665383f0de2391aae1d88c6eb0bb0310ff3e3dc2e743cc`。原 gap 阻断、独立追加明确负例夹具、原 gap 历史不变、2 项原始约束/8 项义务、篡改 oracle 拒绝及新 head 后不能再使用均已核对。该长测在最后的逐案例 global 引用字段增强前启动；该字段由后面的纯测试/API 复验覆盖，不冒称该长测包含最后所有字段。测试不运行目标代码或真实模型，不把候选协议夹具称为正式生成；保留 Boto3/Python 3.9 警告，临时 PG/MinIO 工件清理。
- 平台 API/runtime/Compose 回归 **172 passed / 1 warning**（180.10 秒），`test-design-generation-platform.log`，会话 53319 已 0 退出，保留 LangGraph 既有弃用提示。本机 `dev:foreground` 已重载，会话 27087 保持运行；Portal/API/Runner HTTP 200，PG/MinIO/Temporal 全部 ready，实时 OpenAPI 已确认新 generation-preview 路由。没有新数据库迁移，仍为 0057。

## 测试设计范围审阅（0057，2026-09-20）

新增独立 quality_loop scope revision，固定已归档发布 context，保存风险、权限、状态转换、历史不变量、完整 AC/规则正反例及显式冲突/gap。不可变 PG 链、私有 MinIO 工件、CAS、审计/Outbox、确认式 ToolRuntime 和重新授权 HTTP/Agent receipt 已接入；当前账号及项目角色在提交锁内重新校验。参见[契约](./test-design-scope.md)。不重写原 ContextPack，不授予 generation/coverage/execution 权限；下游正式生成消费仍未接入。

- 首轮隔离 PG/API **8 passed**（94.22 秒），`test-design-scope-api.log`；后续范围/上下文/已发布上下文联跑 **26 passed**（205.15 秒），`test-design-scope-final-api.log`。最后范围专项 **11 passed**（153.37 秒），`test-design-scope-receipts-api.log`，包括确认、恢复、撤回、CAS、Outbox 失败回滚、角色/账号撤销、篡改工件、负例 gap、破坏性降级保护，以及 scope head 未变化但原 AC 撤回时旧 Agent receipt 失效。这些集合有重叠，不累加。
- 工具发现第一次回归 **1 failed / 179 passed**，`test-design-scope-boundaries.log`：新工具长说明中的禁止生成/执行用语挤出了正常 `run.start`。没有扩大 12 项预算或移除断言，改为仅在明确范围审阅意图时优先，普通动作不因禁止条款增加排名。最后纯领域/Agent/DDD/Portal 边界 **203 passed**（2.10 秒），`test-design-scope-final-boundaries.log`。
- 固定 exweb 三源 PG/MinIO **1 passed / 1 warning**（521.53 秒），`test-design-scope-exweb-final.log`。报告 `verified_at=2026-09-19T16:39:59.239544+00:00` 新增 `reviewed_test_design_scope`：独立 v5 范围工件、完整约束分母、风险/权限 oracle、负例 gap、同 invocation 恢复，以及旧依据/发布 head 变化后历史不变且拒绝当前使用。第一次失败是原夹具先撤回业务规则，又用缺少批准 oracle 的上下文创建范围；保留拒绝，在夹具追加明确的新批准并重新编译上下文后复验，未复用撤回前批准。
- exweb 审阅者、需求和测试资料均为明确的伴随验证夹具，不是仓库维护者批准；原生 HTTP 常量向量不是外部真实模型。目标代码没有被运行，不执行 Maven/安装依赖。保留现有 Boto3 Python 3.9 生命周期警告。临时 PG/MinIO 产物在验证后清理，报告对象不代表开发库常驻项目。
- 平台 API/runtime/Compose **172 passed / 1 warning**（212.15 秒），`test-design-scope-platform.log`；后端基线 Portal build/lint、隔离 smoke success。后端阶段完整 E2E **55 passed**（17.6 分钟），`test-design-scope-full-e2e.log`，会话 6796 已 0 退出；它在新范围 UI 之前启动，不覆盖随后新增的页面流程。
- 本机应用经 `dev:foreground` 重载，数据库已到 `0057_test_design_scope (head)`；Portal/API/Runner HTTP 200，PG/MinIO/Temporal 在 Docker。Embedding/Rerank 为开发 fallback，不视为语义性能验证。

Portal 新增独立领域草稿/纯校验器/HTTP adapter/hook，以及小型风险、权限、转换、不变量、正反例、复用、冲突/gap 组件。在归档上下文内审阅、查看历史和撤回；原文固定引用、修改和重查清确认、未知结果先查历史、响应 pin/assessment 异常清屏。

- 浅色/深色真实 PG 浏览器专项 **2 passed**（1.5 分钟），`test-design-scope-portal-e2e-verified.log`：用户填写四种 typed obligation、完整 AC/规则分母、显式 gap 和未解决冲突，严格两次确认写入（批准、撤回），刷新/历史回读、修改后确认失效、损坏 pin 清屏。纯校验附加断言拒绝丢失例子、空理由、失效 gap、越界测试/证据及伪造 generation_authorized。
- 同一流程使用固定 exweb 快照另跑浅色 **1 passed**（1.7 分钟），`test-design-scope-portal-exweb.log`，含伴随 1 AC/1 规则和测试资料。这个浏览器批次用临时 PG/本地私有工件，不冒称 MinIO 浏览器验证；MinIO 是上面的独立 exweb 后端回放。没有运行目标代码或真实模型。
- 新增边界检查后 **138 passed**（1.02 秒），`test-design-scope-portal-boundaries.log`；最终范围领域/工具发现/DDD/Portal 联跑 **185 passed**（1.29 秒），`test-design-scope-portal-pure.log`。Portal build/lint/i18n 通过，保留既有 >500 KiB chunk 提示。新隔离 smoke success，`test-design-scope-portal-smoke.log`。
- 首批浏览器 **2 failed**：撤回确认和随后历史回读两个请求错误共用 5 秒断言窗口；分别等待真实响应后通过。增加纯校验断言曾因间接导入浏览器 transport 而无法收集，已把 oracle 类型/常量与纯校验器从 HTTP adapter 拆开，不给 Node 测试伪造 `import.meta.env`。两份失败日志保留，未移除原断言。
- 390px 深浅色截图已检查，无横向溢出；桌面表单截图首次被滚动容器裁剪，已在测试中扩大截图视口并细化约束选择（权限关联规则，其余风险/转换关联 AC、不变量关联全部）。最后这些测试精化随新完整 E2E 复验，不能将首次裁剪截图当成完整表单截图。
- exweb 测得单次范围历史读取约 7–10 秒，未满足非模型查询 p95 <=2 秒目标；当前 inspect 会重复验证 context，后续需在保持授权/版本/hash 校验的前提下优化，不能靠缓存旧权限绕过。
- 包含新范围页面的完整 E2E 已完成，会话 **69109** 已 0 退出、日志 `test-design-scope-portal-full-e2e.log`：显式固定 exweb，**57 passed / 20.9 分钟**。与前面的 55 项旧批次区分；不能据此声称后续生成契约或完整 V1 已通过。

仍保留完整目标：自动冲突/BehaviorSpec、费用与模型输入预算、正式生成/coverage 原子提交、其他用途、Provider 完整生命周期、动态调查/delta DAG、gold、真实受控运行和最终 V1 门禁未完成。

## AC 检索持久执行与恢复（0055/0056，2026-09-20）

新增独立 application executor、repository/workflow ports、私有批次工件、canonical retrieve/cancel/read 工具及 Temporal workflow/heartbeat/reconciler。完整 AC 查询按 32 条原生批次执行；确认固定 actor、ACL、publication、索引与模型。PG 预留在出口之前，已完成批次恢复不重发，未知出口只等待/失败，不自动重试计费调用。全部 trace、完整 AC 映射、工具终态、审计/Outbox 同事务提交。Portal 提供预览确认、轮询恢复、取消和成功后的 v5 上下文入口；沿用共享深浅色布局。

0056 补齐两项实际恢复缺口：取消 RPC 失败后没有重试、running 扫描固定 100 条导致后续任务可能饥饿。取消意图现在同终态落库，Worker 分页投递，单项失败不阻断后续；停用原确认账号不阻止另一个当前管理员取消，执行前发现账号停用则失败。投递成功不宣称能撤销远端已收到的字节或费用。契约见[AC 查询持久执行](./versioned-retrieval.md#ac-查询持久执行)。

已核实的 0055 证据（有重叠，不累加为测试总数）：

- 查询执行/计划 API **21 passed**（120.61 秒），`context-retrieval-final-api.log`，包括 33 条真实来源 AC 的 32+1 批次、崩溃后不重发、双 Worker 单次出口、未知预留、取消/账号/模型/发布头竞争及原子映射。增加 Agent receipt 后专项 **3 passed / 12 deselected**（21.27 秒），`context-retrieval-agent-temporal.log`，包含真实 Temporal 的丢失派发恢复及唯一 workflow；模型传输仍是明确夹具。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 完整 PG/MinIO 回放 **1 passed / 1 warning**（413.58 秒），`context-retrieval-exweb.log`。报告 `verified_at=2026-09-19T15:49:00.571242+00:00`：546 代码对象、3 个来源、569 索引分片；伴随 AC 自动查询 1 批次、完整映射接入 v5，回执丢失恢复不重复出口/归档，MinIO 与历史新 head 检查通过。
- exweb 测试使用固定 canonical actor 夹具及 native HTTP 常量向量，不经 Temporal (`temporal_execution=false`)，不冒充真实模型相关性、业务批准或业务 gold；Temporal 由上面的独立 PG/API 测试证明。没有执行 exweb/Maven/安装目标依赖。临时 PG/MinIO 工件清理，报告 ID 不是开发库常驻对象。
- Portal light/dark 专项 **4 passed**（43.4 秒），`context-retrieval-e2e.log`：独立确认、刷新 running、取消、完整映射 v5 和非法权威/权限清屏。浏览器异步模型/索引是明确协议夹具；390px 截图已检查，无横向溢出。Portal build/lint/i18n 通过，保留已有 >500 KiB chunk 提示。
- API/runtime/Compose **172 passed / 1 warning**（166.00 秒），`context-retrieval-platform-regression.log`；领域/边界 **158 passed**（1.14 秒），`context-retrieval-boundaries.log`；隔离 smoke success，`context-retrieval-smoke.log`。这些不是完整 V1 门禁。

0056 最终验证：

- 恢复/执行/查询计划 **29 passed**（211.86 秒），`context-retrieval-recovery-verified.log`，显式真实 Temporal 且无 skip/警告。覆盖请求取消后 RPC 失败的恢复、活动中断、未提交批次不发布、事务回滚、原确认账号停用、管理员取消，以及超过 100 个取消/派发任务的分页和单项故障隔离。
- 旧取消记录迁移、保留投递意图及禁止破坏性降级专项 **1 passed / 6 deselected**（8.36 秒），`context-retrieval-cancel-migration.log`，也包含在上面的 29 项中。
- 首轮 **2 failed / 4 passed**（46.16 秒），`context-retrieval-recovery.log`，两项失败为测试用了不存在的 `admin` 角色（422），改为既有 `project_admin`，未降低权限要求。随后联跑发现分页夹具任务被另一临时 Temporal 队列接收；已限定真实测试的 dispatch 范围、清理该夹具命名空间，并以上面的无警告终态复验，未删除开发任务。
- 补齐 Agent 工具发现：中文“执行全部 AC 上下文检索”和“停止上下文检索”此前未保留新的执行/取消契约。中英文、三个空间的完整链及既有 Agent/DDD/Portal 边界 **179 passed**（1.58 秒），`context-retrieval-agent-discovery.log`；仍保留 12 条详细工具/240 字符说明上限及原有确认要求。不是完整模型驱动 AgentGoal 验收。
- API/runtime/Compose **172 passed / 1 warning**（208.99 秒），`context-retrieval-recovery-platform.log`；Portal build/lint/i18n、27 个本地文档链接与 diff 检查通过，隔离 smoke success。保留既有 bundle 大小及 LangGraph serde 提示。
- 本机应用已重载，`0056_context_retrieval_cancel` 已迁移，`dev:foreground` 会话 20690 持续监督，Portal/API/Runner HTTP 200、`dev:status` 全 ready；真实 Temporal 查询队列的 workflow/activity poller 各 1。Docker 仍只运行基础组件。
- 最新 exweb PG/MinIO 回放 **1 passed / 1 warning**（456.87 秒），`context-retrieval-recovery-exweb.log`，会话 99977 已 0 退出。报告 `verified_at=2026-09-19T16:05:39.872453+00:00` 包含新 `scope_fingerprint`/`acl_epoch`、1 个 AC 查询批次与自动完整映射、v5 和 MinIO 回放；原语料/静态执行限制不变。Python 3.9/Boto3 警告仍需后续环境升级处理。
- 完整 E2E 会话 97674（`context-retrieval-full-e2e.log`，显式 exweb）已确认 0 退出，**55 passed**（16.5 分钟）。该批次在工具排序的最后小修改前启动；排序行为另由上述专项/API 验证，不据此混称全部源码为同一基线，也不覆盖随后新增的 0057。

以上推进 P4/P5/P6 的一部分，不改变完整范围：索引构建自身的批次恢复、生成/coverage 原子提交、其余用途、动态调查与 delta DAG、Provider 完整生命周期及对照、独立 gold、真实受控运行和最终 V1 门禁仍需交付。

## 完整 AC 检索查询计划（2026-09-19，历史准备阶段）

新增独立领域预算规则和 application 输入编译器，向 canonical query tool、只读 HTTP 与 Portal 索引面板提供同一份 `nasus.context-retrieval-plan.v1`。每条冻结来源 AC 都生成查询，仅使用自身字段与确切父需求的描述；验证原文证据及其在已确认索引内的成员资格，不引用可变批准 oracle、不混入兄弟 AC。计划固定 publication / generation / model / source / evidence 和字节预算。所有输入完整保留；单项 4096 字节、最多 256 项和 1 MiB 总上限，超限返回明确不删减 AC 的错误。

本次交付是自动检索的准备阶段，**不是批量执行**：预览不调用模型、不创建 trace 或 AC-to-retrieval 绑定、不改变 ContextPack 默认 v4，不授权生成。界面只在当前索引和管理员权限均验证后提供“预览 AC 查询预算”，显示目的地、完整查询数/字节与原生批次上限；刷新、重取失败、错 pin 或迟到响应隐藏旧内容。没有新增迁移，数据库仍为 0054。完整契约见 [版本化检索](./versioned-retrieval.md#ac-查询计划预览)。

已验证范围（选择集有重叠，不累加）：

- 领域、输入编译及分层/Portal 边界 **158 passed**（1.52 秒），`context-query-plan-pure-final.log`：完整 AC 集合、父文档缓存/分页、UTF-8 字节预算、缺少固定证据或未授权索引成员拒绝、兄弟 AC/可变 oracle 不进入查询、空需求不制造查询。
- 新接口、固定索引及 v5 兼容 **32 passed**（191.18 秒），`context-query-plan-api-final.log`。最终 HTTP 专项 **7 passed**（34.63 秒），`context-query-plan-contract-verified.log`，覆盖 canonical receipt / Agent 重新核验、无模型调用/无正文泄露、当前 publication 与模型及 ACL 竞争、跨发布索引和明确 413。首次最终专项 **1 failed / 6 passed**，原因是新测试把 FastAPI `detail.error` envelope 误写成顶层 `error`；只修正断言路径，错误码与拒绝行为不变。
- Portal build/lint/i18n 和 diff 检查通过，保留已有 >500 KiB 主 chunk 告警。新面板/已发布上下文 light/dark 专项 **4 passed**（35.4 秒），`context-query-plan-e2e.log`：按需预览、坏 scope/预算/authority 清屏、零需求、刷新中迟到回执不重开、模型变更收起入口。390px 深色截图已检查，细边框和既有主题保持，无横向溢出；浏览器模型/索引/计划是显式协议夹具，来源摄入/发布使用真实 exweb 与 PG，实际查询计划逻辑由下述 PG/MinIO 验证证明。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的 PG/MinIO 全回放 **1 passed / 1 warning**（450.16 秒），`context-query-plan-exweb.log`。报告 `exweb-source-documents-report.json` 的 `verified_at=2026-09-19T15:14:23.388173+00:00` 新增 `frozen_retrieval_index.context_query_plan`：1 条伴随来源 AC 查询、479 UTF-8 字节、最多 1 个 native 批次，实际预览模型调用为 0。546 个代码成员、3 个来源、569 个索引分片及 v5 固定回放继续通过。伴随资料/常量向量仍是明确夹具，不是业务 gold 或真实模型验收；未运行 exweb、Maven 或安装目标依赖，临时 PG/MinIO 工件已清理。
- 最终领域/边界复验 **158 passed**（1.02 秒），`context-query-plan-delivery-boundaries.log`；隔离 PG smoke success，`context-query-plan-smoke.log`。API/runtime/Compose 扩展回归 **172 passed / 1 warning**（184.19 秒），`context-query-plan-regression.log`，保留既有 LangGraph serde 提示；不是完整 V1 发布门禁。
- 本机应用已重载，新 `dev:foreground` 持续监督，Portal/API/Runner HTTP 200，`dev:status` 全 ready，OpenAPI 包含 `context-query-plan`。Docker 仍只负责外部组件；未写开发项目/来源资料，未将模型 fallback 算作真实语义验证。
- 该准备阶段完整 E2E 最终 **55 passed**（16.0 分钟），`context-query-plan-full-e2e.log`，显式固定 exweb；本结果已核实，仍不替代后续 0055/0056 改动的验证。

本阶段当时未交付的持久查询执行和 v5 接入已由上方 0055/0056 切片推进；本节仅保留准备阶段记录。其余五类上下文、正式生成/coverage、完整 P0-P6 和 V1 门禁继续保留，不能用预览或批次执行替代它们。

## ContextPack 固定索引消费（v5，2026-09-19）

新增 `nasus.test-design-context.v5`，不新增数据库迁移。通过 `ContextRetrievalReplayPort` 验证已归档的 trace/index/model/publication pins，显式 AC-to-retrieval 映射覆盖全部来源 AC；有界候选池与 AC 词法/显式引用合并后执行全部负向审阅筛选，再选择支持事实。trace 绑定、排名与结果摘要、完整审阅头写入既有 ContextPack Derivation。编译、事务复核、恢复和历史 GET 均不调用模型；模型变化拒绝新使用，旧包经完整性/当前 ACL 校验后仍可回放并标 stale。v1-v4 不新增序列化字段或重写历史。

这不将检索排名等同语义正确性。没有图扩展、rerank、真实 gold 或正式生成授权；保守报告 trace 池截断/原 FTS fallback。用户显式选中的查询不自动视为相关性证明。Portal 支持混合策略历史和新失效原因/中英文说明，但默认发布预览仍为 v4，自动查询、预算与选择 UI 仍待完成。完整契约见[上下文包 v5](./context-packs.md#v5-固定检索回放)。

当前验证记录（选择集有重叠，不累加为项目测试总数）：

- 隔离 PG 新消费/旧发布包/索引回归 **32 passed**（155.03 秒），`indexed-context-api-final.log`：真实 canonical 预览/确认/归档、历史无 provider 出口、模型变化/提交竞争、私有 trace actor、完整 AC 映射、跨 publication 拒绝、坏工件不因 stale 放行、新人工否定阻断当前候选且旧包不变。首轮 **1 failed / 30 passed**，`indexed-context-api.log`：恢复夹具没有将已完成命令改回正在恢复的 running；修正夹具后通过，未改变生产确认和状态校验。
- 原 trace 查询者在来源撤权后不能读取历史包，隔离 PG **1 passed**（9.94 秒），`indexed-context-privacy.log`。编译者是项目管理员，不绕过读取者的来源 ACL。
- 领域/召回/分层 **165 passed**（1.11 秒），`indexed-context-pure-final.log`。包括没有标签匹配的 40 个纯 trace 候选、top-1 前排除 39 个负例、固定审阅头回放、篡改修订/证据/binding 拒绝、v1-v4 旧请求字节不变；分层单独批次 **137 passed**（0.91 秒），不重复计数。
- 深浅色真实 API/PG 浏览器检查 **2 passed**（17.6 秒），`indexed-context-e2e.log`：v4 与空需求 v5 混合历史、刷新/发布头失效、schema 与错误 pin 清屏、390px 不横向溢出。空需求只接受空映射且 blocked，不能冒充非空检索端到端；非空消费由 PG 与 exweb 验证负责。已查看深色移动截图，沿用既有视觉。
- Portal build/lint/i18n、diff 检查通过，日志 `indexed-context-build-final.log` / `indexed-context-lint-final.log`；现有大 chunk 提示保留。隔离 smoke success，`indexed-context-smoke.log`。
- API/runtime/Compose/旧 ContextPack 扩展回归 **185 passed / 1 warning**（228.21 秒），`indexed-context-regression.log`，保留既有 LangGraph serde 提示。与其他选择集不累加，不能替代完整 V1 门禁。
- 本机 `dev:foreground` 重载完成，数据库仍为 0054；Portal/API/Runner HTTP 200，Worker 存活，`dev:status` 全 ready。Docker 仍仅基础组件，embedding/rerank 仍是开发 fallback，不是外部模型验证。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的完整 PG/MinIO 回放 **1 passed / 1 warning**（397.67 秒），`indexed-context-exweb.log`。报告 `exweb-source-documents-report.json` 的 `verified_at=2026-09-19T14:57:25.458850+00:00` 新增 `indexed_context`：546 代码对象、3 来源、569 索引分片、354701 字节、18 native 批次；v5 保留全部 2 项强制约束、固定 trace derivation、MinIO 回读、禁止编译/恢复/历史模型调用，新 publication 后原包字节不变且 stale，同命令恢复不重复归档。
- exweb 配套需求/测试/reviewer 和 embedding 常量向量是显式夹具，不是外部真实模型、语义 gold 或作者业务批准；没有运行目标代码/Maven/安装依赖。样例规则已在前置撤回用例中撤回，因此 v5 正确保持 blocked、`generation_authorized=false`。临时 PG/本次 MinIO 写入已清理，报告 UUID 不是开发库常驻演示对象。保留 Python 3.9/Boto3 警告。
- 显式启用固定 exweb 的完整 E2E 最终 **55 passed**（16.3 分钟），`indexed-context-full-e2e.log`，执行会话 71229 以 0 退出。此基线在 AC 查询计划新面板接入前完成，不替代后续新面板专项。

本切片推进 P4/P5，不代表 P0-P6 完成。正式 quality generation 仍未切换；全部五用途、动态调查/维护、注册表 cutover、provider 生命周期/对照、独立 gold、真实运行反馈和最终 V1 门禁仍未完成。

## 发布绑定检索索引与构建入口（0054，2026-09-19）

新增 `nasus.frozen-evidence-index.v1`。完整冻结证据按 UTF-8 字节分片，确认固定 publication、输入、已保存 embedding 模型及后续查询出口；canonical invocation 先预留，全部批次成功后才原子提交 generation/documents/Outbox。MinIO 保存可校验私有工件，PG 保存向量与 FTS；没有删除旧投影或改变质量权威。详见[版本化检索契约](./versioned-retrieval.md)。

Agent 现在可以读取同 publication 的完整 generation，使用真实 pgvector + FTS 确定性 RRF；模型变更拒绝串向量空间，provider 临时失败明确退为同 generation 的 FTS。结果为固定证据定位而非向聊天模型自动发送源码。查询 trace 固定查询/index/model/ACL/候选与选择，分页读取不暴露正文和内部存储地址。无 generation 仍保留明确标识的旧词法过渡路径，不能将其算作新检索或受控 rerank 完成。

Portal 知识页新增按需展开入口、经过测试的 embedding 模型选择、出口/预算/证据输入预览、显式确认和状态刷新。后台重新验证、切换模型或版本后旧确认失效；未知回执不自动重试。状态接口重验当前 head/ACL，无模型调用；源撤权或返回错 pin 时隐藏旧内容。未完成命令历史/SSE 进度/跨刷新恢复仍未完成。

已核实证据，重叠选择集不累加为测试总数：

- 索引 PG/API 和竞态最终 **18 passed**（91.43 秒），`frozen-index-ui-api.log`。包括原子提交、取消/跨批维度异常、同 invocation 竞争、未知结果不重发、发布变化、模型变化、源撤权、元数据状态与状态读取期间的 head 竞争。此前核心链 **16 passed**（87.27 秒），`frozen-index-observation-api.log`；最终源码出口/Agent 回执专项 **2 passed**（12.10 秒），`frozen-index-egress-verified.log`。
- 领域/native 协议/模型/边界 **209 passed**（1.30 秒），`frozen-index-pure-final.log`；Agent 观察和调查回归 **46 passed**（0.71 秒），`frozen-index-agent-unit.log`；新增 UI 后 DDD/Portal 边界 **137 passed**（0.97 秒），`frozen-index-ui-boundaries.log`。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 静态回放 **1 passed**（424.19 秒），`frozen-index-exweb-final.log`。报告 `exweb-source-documents-report.json` 的 `verified_at=2026-09-19T13:52:49.649472+00:00`：546 个代码对象、3 个来源、569 分片、354701 字节、18 个 native 协议批次，MinIO 回读与 PG 向量/FTS/trace 验证通过；原提交恢复不重复出口，新 publication 不复用旧向量、旧工件保持不变。原失败 `frozen-index-exweb.log` 为长测期间模块迁移导致惰性 import 混用新旧符号；稳定代码并提前导入 fixture 后通过，未削减代码范围或字节预算。
- exweb 的需求/测试/审阅身份为明确伴随夹具，embedding 是 native HTTP 的显式常量向量 transport fixture；不是外部真实模型、语义 gold 或作者业务验收，不执行目标代码/Maven/安装依赖。临时 PG 与本次 MinIO 写入由测试清理，报告 ID 不是开发库常驻演示对象。
- 0054 后端基线完整 E2E **53 passed**（16.7 分钟），`frozen-index-full-e2e.log`，显式启用固定 exweb，无 skip，进程 59834 已 0 退出。这批在新增索引 UI 前启动，不替代后续 UI 专项。基线 API/runtime/Compose **172 passed**（181.32 秒），`frozen-index-api-gate.log`，隔离 smoke success `frozen-index-smoke.log`。
- 新入口初步深浅色 **2 passed**（22.5 秒），`frozen-index-ui-e2e.log`：真实 exweb 摄入、发布与空索引状态；模型/索引输出为明确浏览器协议夹具，实际 native/PG 构建由 API 专项证明。覆盖条件展示、模型过滤、未确认禁用、改模型/刷新清除确认、单次提交、完成后刷新恢复、配置变更、错误 pin 清屏与失败不自动重试。截图检查发现共享按钮样式和选择框窄屏宽度问题，已修复并增加几何/CSS 断言，最终复验另记。
- Portal build/lint/i18n 与 diff 检查通过；首次 build 发现翻译键重复，复用已有 `Destination` 后通过。保留已有大 chunk、Python 3.9/Boto3、LangGraph serde 提示。0054 已在开发 PG 应用，应用由 `dev:foreground` 本机监督、外部组件仍在 Docker；新状态接口的运行时重载另记。
- 样式修正后的索引/已发布上下文深浅色专项 **4 passed**（35.2 秒），`frozen-index-ui-final-e2e.log`，已检查两张 390px 截图：按钮使用 1px/9px 共享边框和圆角，选择框处于面板内，没有页面横向溢出。索引测试使用固定 exweb 摄入/发布，模型输出保持协议夹具。
- 新状态接口后 API/runtime/Compose **172 passed**（181.06 秒），`frozen-index-ui-regression.log`；最终 Portal build/lint/i18n 通过，`frozen-index-ui-delivery-build.log` / `frozen-index-ui-final-lint.log`。隔离 smoke success，`frozen-index-ui-smoke-final.log`；首次 smoke 因与专项 E2E 争用 18082/14175 端口而退出，等待该浏览器批次正常结束后再运行，未杀其他进程或改用开发库。
- 开发服务已重新加载新索引状态接口，OpenAPI 包含必填 `publication_id`，Portal/API/Runner HTTP 200、`dev:status` ready；Worker 43284 在 AgentGoal/ConversationTurn 的 workflow/activity 四类队列均有 poller。`dev:foreground` 监督仍在运行。模型路由 development_fallback 不等于真实模型门禁通过。
- 最终索引 PG/API **19 passed**（85.82 秒），`frozen-index-ui-api-verified.log`，补齐与 Portal 一致的不绑定会话命令、明确确认、幂等重放及真实状态读取。初次扩充测试误认为 `input_payload` 只含业务字段，实际 canonical runtime 会附加 `idempotency_key`；修正测试期望与浏览器夹具以匹配真实协议，未放宽生产字段校验或确认门禁。更新夹具后的深浅色索引浏览器复验 **2 passed**（23.9 秒），`frozen-index-ui-verified-e2e.log`。之前 4 项联动批次和 53 项基线保持各自范围，不合并宣称最终全量 E2E/V1 发布门禁通过。

此交付不等于完整 P0-P6：其余 ContextPack 用途、质量生成 UoW/覆盖矩阵、受控 rerank/图扩展、增量版本/恢复、真实模型与独立 gold、容量/最终 V1 门禁仍是未完成的原目标。

## 已发布画像上下文绑定（2026-09-19）

新增显式 `nasus.test-design-context.v4 / publication_id`，完整契约见[上下文包](./context-packs.md#v4-发布绑定)。新画像源、子包和 provenance 一起绑定发布记录；预览前后及提交锁内验证对应 baseline 的 head。历史包按原 publication 重放，更新 head 后只改变当前适用性，不改原文、不自动授权生成。没有新迁移、不改变旧工件 hash，也不减少 Tool ID。

Portal 知识页新增独立已发布上下文入口，工作草稿仍保留 v3 调查入口。前端核对请求、根/子包 publication pin、manifest 和 authority=false；不一致或撤权隐藏旧内容。

- 初步 PG/API 与分包回归 **27 passed**（61.39 秒），`published-context-first.log`：旧序列化兼容、真实发布/归档/历史回放、同画像重发失效、artifact 写后 head 竞争、查询期间 head 变化、损坏和来源撤权。后续扩大验证另记，不累加重叠用例。
- Portal build/lint/i18n 与 DDD/Portal 边界 **137 passed** 已验证。保留已有大 chunk 提示。
- 扩大上下文/发布/读取/工件回归 **48 passed**（145.44 秒），`published-context-regression.log`；最终发布上下文专项 **7 passed**（44.82 秒），`published-context-final-api.log`，包含 version-working 不跟随 Official 更新。API/runtime/Compose **172 passed**（223.48 秒），`published-context-api-gate.log`。这些选择集有重叠，不累加为测试总数。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` + PG + MinIO **1 passed**（356.96 秒），`published-context-exweb.log`。546 代码成员、两项伴随强制约束；v4 根/子包均固定 publication，真实发布下一候选后旧预览拒绝、旧包字节保持且标 stale，同 invocation 恢复原包。报告 `exweb-source-documents-report.json` 新增 `published_context`。依然只有静态解析和明确伴随资料/审阅夹具，不是维护者验收、真实外部模型或目标运行证明。隔离 PG 和本次临时 MinIO 工件已清理，保留 Python 3.9/Boto3 提示。
- 新入口 light/dark 专项 **2 passed**（22.0 秒），`published-context-e2e.log`，覆盖真实 canonical 发布/归档、刷新历史、重发失效和错误 pin 清屏。查看 390px 截图后补齐页内按钮对共享 evidence 样式的继承；最终样式复验结果另记。代码稳定后的完整 E2E 以 `published-context-full-e2e.log` 最终结果为准，尚不声称该套件全绿。
- 按钮样式最终复验 **2 passed**（13.9 秒），`published-context-final-ui.log`；已查看更新后的深色 390px 截图，按钮保持细边框/圆角与共享 token，无横向溢出。完整套件继续运行，未因观察等待超时重启。
- 上述完整套件最终 **53 passed**（16.7 分钟），`published-context-full-e2e.log`，已明确启用固定 exweb 结构检查，无 skip；持续进程 53549 已以 0 退出。这验证 v4 上下文基线，不替代其后 0054 索引新增链路的专项验证。
- Portal 最终 build/lint/i18n、边界 **137 passed**（0.84 秒）与隔离 smoke success；开发应用已重载，API OpenAPI 含 v4 和 publication_id，0053 无新迁移，Portal/API/Runner 200，Worker 20377 在四类 Temporal 队列均有近期 poller。Docker 仍只运行外部组件，开发模型 fallback 不计为真实模型门禁。

本轮仍未完成五种上下文用途、真实版本化混合检索、生成 UoW、CoverageMatrix、目标运行和完整 P0-P6。不能将知识 publication 当作业务 oracle 或 V1 上线证据。

## 发布读取与工作草稿隔离（2026-09-19）

正式 GET system-image、knowledge 列表/详情和 Agent 画像上下文接入同一个 published read application service。已采用发布 head 的项目不再用可变投影拼装当前画像：固定 publication/image/hash/manifest/sequence，并在返回前复查 head 与来源权限。项目会话选择唯一 Official；版本会话只选择该版本的 working head，不动态继承 Official。缺少 head 明确为 unpublished；冲突、撤权、工件不可用或哈希失败不回退到草稿。

- `?view=working` 显式提供继续构建所需的当前 manifest 与基线。知识页展示已发布 pin，调查计划/画像修订弹层单独读取工作草稿。未固定的指标和 chunk 不展示为 0。没有发布 head 的旧项目继续标为 legacy_draft，不称为已批准画像。
- 发布读取只加载项目身份，不为获取项目名重新读取完整旧画像。发布后重新摄入、生成另一个候选，不改变已发布对象与来源；再次批准并发布后才切换。Agent 检索和上下文组装之间的 head 变化返回冲突，HTTP 记忆结果包含相同 pin 与检索策略。
- 旧 pgvector/FTS 向量及长期记忆没有 image revision 绑定，不能靠相同 object ID 混入正式读取。当前已发布检索仅对冻结成员执行 lexical + 已配置 rerank，返回 image-qualified 引用，并明确报告 `published_lexical_rerank_unversioned_index_withheld`。这是防止串版本的过渡保护，**不是完成版本化 hybrid 检索、检索审计或长期记忆来源治理**；这些仍是原目标必需工作。
- Portal 后台重新授权保留已挂载详情、分页和发布面板状态，验证期间隐藏内容，失败仍清屏。首轮发布后刷新会卸载详情导致面板折叠，已修正，未放宽 5 秒断言。首轮权限回归受新增测试恢复实例绑定方法影响，已改为类级补丁隔离；实际权限检查未削弱。
- 发布/权限读取专项 **17 passed**（39.36 秒），`published-read-scope-recheck.log`；exweb 发布、权限防护、调查计划 light/dark 专项 **6 passed**（49.8 秒），`published-read-exweb-final-e2e.log`。
- 后续 API/runtime/Compose 与读取回归 **213 passed**（256.02 秒），`published-read-final-regression.log`；Agent HTTP pin/strategy 专项 **1 passed**（3.76 秒），`published-read-agent-http.log`；边界 **137 passed**、Portal build/lint/i18n 和隔离 PG smoke success。上述完整浏览器套件仍须以代码稳定后的最终结果为准，不能用专项代替。
- 首轮完整 E2E 最终 **50 passed / 1 failed**（16.2 分钟），`published-read-full-e2e.log`。浅色发布测试执行期间，后续开发修改 i18n 模块触发 HMR，日志出现 `useI18n must be used within I18nProvider` 并卸载页面，发布面板断言失败。不改超时或跳过断言，代码稳定后重新运行完整套件；这一次失败不记为通过。
- 真实 exweb + PG + MinIO 三源验证 **1 passed**（242.16 秒），`published-read-exweb-minio.log`。固定 546 个代码成员；需求来源更新后 published reader 对象/来源与 pin 均不变。`exweb-source-documents-report.json` 记录该断言。仅静态代码、明确伴随需求/测试夹具和测试审阅身份，不运行 exweb、不调用外部语义模型、不视为维护者验收。

仍待完成：其余共享摘要与正式语义成员消费者、版本化向量/图检索和 trace、五类 ContextPack 与原子生成、历史会话来源治理，以及 P0-P6 表中的其他要求。旧 ContextPack 的历史 `image_not_published` 不被回写，也不因知识发布自动获得生成/上线授权。

## 固定画像发布与 exweb 性能验证（0053，2026-09-19）

契约见[固定画像发布](./image-publication.md)。发布必须经过精确输入预览、显式确认的管理员审阅和 `baseline.promote` 的审批门禁。审阅固定 image/hash/manifest、target baseline、原 head、preview digest、policy 和当前来源 ACL；30 分钟失效。发布记录、head、AuditEvent 和 Outbox 同事务提交；恢复同 invocation 只返回原记录，不回退新 head。旧投影更新保留被引用的 baseline 身份和只读审批镜像，不删除新历史。

- 补齐 `query.system_image.publication.head` 的 runtime handler、metadata-only 回执和受控展开。Agent 可以先读取目标 head，再预览/审阅/发布，不需要调用 UI 私有 HTTP；中文/英文发布意图均保留四个详细工具契约。旧空 head 回执在发布后拒绝当作当前事实展开。
- API/runtime/Compose、工具发现、来源证据及发布联合回归 **259 passed**（216.56 秒），`image-publication-final-regression.log`。前一轮 **196 passed / 1 failed** 是测试忘记确认普通 `approval.request`；修正夹具走实际确认链，没有放宽 runtime 的审批要求。
- 新 Portal 浏览器专项 **4 passed**（20.7 秒），`image-publication-guards-e2e.log`：独立 review/publish consent、并发 reject 后必须 reload 并重新确认、403 清除原画像内容、刷新恢复 head、浅色/深色/390px 无横向溢出；已查看深色移动端截图。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、546 个代码成员的浏览器验证 **2 passed**（28.5 秒），`image-publication-exweb-batch-e2e.log`。未放宽 5 秒页面断言。首轮逐项读取预览约 16.6 秒，清单会话内复用后仍约 12.9 秒；改为有界证据元数据 join 后，一次记录为 0.47 秒。此为本机单次观测，不是 P6 的 p95 容量门禁。
- 优化不缓存授权或原文文件：每批最多 512 个证据，读取前核对完整 project/revision 成员，全部原文件和 snippet 哈希仍校验，前后及每 16 项复查权限，外围画像 scope 返回/提交前也需当前有效。只在一次上下文中复用最多四个已校验来源 manifest。
- 真实 exweb + PG + MinIO 三源验证 **1 passed**（280.21 秒），`image-publication-exweb-minio.log`。伴随需求变更后，新发布预览拒绝旧 manifest，已发布 head 和候选 MinIO 工件不变；丢失完成响应恢复同一 publication，不重复推进。报告 `exweb-source-documents-report.json` 新增 `knowledge_publication`。546 个代码成员；仅静态分析，未运行目标代码、未调用外部模型；审阅身份为明确测试夹具，不是 exweb 维护者或业务验收。
- ContextPack、历史画像、权限和分页消费者回归最终 **85 passed**（72.08 秒），`image-publication-consumer-final.log`。首轮 **83 passed / 2 failed** 是分页夹具只模拟了 binding_ids，缺少既有缓存键要求的 actor/epoch/fingerprint；已改用正式 SourceAccessScope，保留 64 KiB 和分页回放断言。新增 batch 读取后的撤权与错误 binding 检查等 **7 passed**（16.37 秒），`image-publication-batch-scope.log`。
- DDD/Portal 边界 **137 passed**（0.79 秒）；Portal build/lint、i18n 和隔离 PG smoke 通过。完整 E2E **50 passed / 1 skipped**（6.8 分钟），`image-publication-full-e2e.log`；跳过项为需显式 exweb 路径的 opt-in analysis，用例没有删除。本轮单独运行了上述固定 exweb 发布浏览器及三源 PG/MinIO 验证。保留既有大 chunk、LangGraph 和 Python 3.9/Boto3 弃用提示；未声称完整 `verify:v1-release` 通过。
- 随后显式提供固定 exweb 路径补跑 opt-in analysis 及两个发布主题用例，最终 **3 passed**（59.0 秒），`image-publication-exweb-final-e2e.log`：13 条注解路由/精确行号、冻结原文、调查计划、确认式结构构建及 Agent 计划授权/恢复均保留，发布流程刷新后仍能恢复同一 head。没有用跳过结果替代这一项验证。
- 开发服务已用 `dev:foreground` 重新启动，数据库迁移为 **0053_image_publication (head)**；Portal/API/Runner 200，Worker 3116 的 AgentGoal/ConversationTurn workflow/activity 四类队列均有新 poller，`dev:status` 全 ready，运行中 Tool Catalog 已包含 head/preview/review 三个 publication 工具。仅基础组件使用 Docker；模型仍为 development_fallback。

发布保留候选工件原始状态/哈希，不改写历史 `image_not_published` readiness，也不让来源投影变成 approved oracle。完整正式消费者切换、增量 DAG、合并/回滚、五类 ContextPack 与受控运行仍按原 P0-P6 目标继续。

## 冻结画像读取与 Agent 工具发现回归（2026-09-19）

冻结修订选择器原先在列表 `isFetching` 时提前返回，导致权限刷新卸载分页组件、取消进行中的 objects/members 联合读取，并从初始 25 条窗口重试。现在初次加载仍显示等待，重新授权期间用 `hidden` 隐藏已挂载内容，成功后保留所选修订/分页；拒绝或完整性失败仍卸载并清屏。没有关闭焦点授权刷新、缓存过期或错误处理，也没有放宽 64 KiB 上限和严格请求序列断言。

- 首次模拟没有把 visibilitychange 送到 TanStack 监听的 window，因等待响应超时而失败，不能作为生产缺陷证明。修正事件目标后，未改生产代码的红测稳定捕获重复 `[25, 25, 12, 25, 12, 6, 3]`，`image-page-focus-red.log`；修复后原 9 项通过，加入第 2 页保持/刷新期间隐藏/403 撤权清屏后最终 **10 passed**（27.0 秒），`image-page-focus-final.log`。
- 0052 后扩展 API 回归首次 **200 passed / 1 failed**（176.62 秒），`business-rule-regression.log`：工具目录增大挤出了源证据 list/read 的详细契约。现对明确原文/证据调查意图提高这两个 query 的相关性，保留全 Tool ID、12 条详细契约上限、240 字说明截断以及原有 RBAC/确认规则。项目/知识库/工作区的中英文回归和原证据回执检查 **29 passed**（0.31 秒），`image-discovery-regression-final.log`。
- 领域、Agent、DDD、Portal、Compose 合并专项 **179 passed**（1.36 秒），`image-page-boundaries.log`；Portal build/lint/i18n 和 diff 检查通过，保留既有大 chunk 提示。隔离 PG/端口 smoke **success**，`image-page-smoke.log`。这些选集有重叠，不相加为独立测试总数。
- 扩展隔离 PG/API 回归 **210 passed**（167.74 秒），`image-discovery-api-final.log`，保留既有 LangGraph serde 提示。默认完整 E2E 最终 **46 passed / 1 skipped**（5.6 分钟），`image-page-e2e-full.log`；skip 是要求显式 exweb checkout 的结构检查，不计为通过。
- 随后显式使用干净的 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 补跑结构浏览器 **1 passed**（39.9 秒），`image-page-exweb-final.log`。验证 13 条 Java 注解路由、546 代码成员、原文证据、冻结画像分页及 AgentGoal 的确认式结构构建；不执行目标仓库/Maven，不把结构观察当业务正确性或正式发布批准。该专项与默认批次分别记录，不抹去默认 skip。
- 已查看本轮轻色移动端规则批准截图及固定 exweb 冻结证据截图；没有新增 UI 文案或视觉 token。开发服务经 `dev:foreground` 重启加载最新工具发现实现，仍是 host 应用 + Docker 依赖，0052 无新增迁移，`dev:status` 全 ready、Portal/API/Runner HTTP 200。Embedding/Rerank 仍是开发 fallback，不算真实语义检索门禁。

完整 P0-P6、真实外部模型与独立 gold、正式画像发布、五类上下文消费/生成 UoW 和受控执行闭环仍未完成。本轮只关闭上述查询生命周期和工具发现回归，不降低完整目标。

## 业务规则独立批准（0052，2026-09-19）

已接入独立规则版本/私有工件、canonical 批准与撤回、查询时元数据 receipt、Portal 冻结规则批准入口及 ContextPack v3。AC 与规则复用来源校验/CAS/恢复协议，但保持不同身份、策略和表；旧 AC/v1/v2 工件不改写。规则批准不再永久缺失，但完整风险/权限/冲突、正式 head 和生成 UoW 仍开放。契约见[业务规则批准](./business-rule-authority.md)。

- 纯领域/Agent discovery/DDD/Portal/Compose 最终专项 **181 passed**（1.67 秒），`business-rule-boundaries-final.log`；Portal build、lint、i18n 已通过，保留现有 chunk 告警。
- 首轮 PG/API **23 passed / 1 failed**（148.67 秒）：新增撤权测试错误调用不存在的 `append_rule`，已改为真实内部 `set_policy`，没有修改生产权限逻辑绕过检查。最终扩展到规则/AC/ContextPack/v2 分包回归 **28 passed**（142.36 秒），`business-rule-api-final.log`。
- 固定 exweb 的 AC/规则/ContextPack 两主题浏览器 **6 passed**（6.4 分钟），`business-rule-exweb-e2e.log`；真实 PG/MinIO **1 passed**（293.07 秒，保留 Python 3.9/Boto3 弃用提示），`business-rule-exweb-minio.log`。已核对 `exweb-source-documents-report.json` 的固定 commit、v3 规则 oracle pin、撤回后旧包保持原文、新画像不继承批准、v2 不变及 `target_executed=false`。所有批准都是配套测试夹具，不是 exweb 作者批准。
- 独立 PG/端口的默认 smoke 成功，`business-rule-smoke.log`。开发服务已经 `dev:foreground` 重载，数据库到 0052，Portal/API/Runner HTTP 200，运行中 OpenAPI 已包含业务规则查询与 v1/v2/v3 策略；默认 API 策略仍 v1。模型仍为 development fallback。
- 收尾上一轮 Context scope 默认 E2E 得到 **42 passed / 1 failed / 1 skipped**（5.1 分钟），失败为 `image-page-budget.spec.ts` 收到额外的 `[25, 12]` 请求前缀，不记为全绿；后续复现与修复见上方“冻结画像读取与 Agent 工具发现回归”。修正边界命令中的文件名后 **189 passed**（1.06 秒），`context-scope-final-boundaries.log`。

## ContextPack 强制约束拆包（2026-09-19）

新增 `nasus.test-design-context.v2`，保留旧 v1 请求默认和工件回放。全部强制约束在 bundle 根清单保留，完整 AC 按预算分组，每个子包完整继承所有来源业务规则；缺批准仍 blocked，不能用拆包产生 generation 授权。Portal 切换到显式 v2，显示各子包计数、hash 和字节预算，并核对约束并集/全局继承。没有新数据库迁移。完整契约见[固定上下文包](./context-packs.md)。

本轮先完成拆包逻辑，再用 6 AC/2 全局规则复现出既有重复读取的性能问题。新召回一次返回内容+回执，历史仍独立回放；一次编译内最多复用两份已验证画像字节，逐次重验成员和 ACL，跨 actor/epoch/画像不能命中，返回副本避免调用方修改。提交前重新开启读取会话，不能把预览时缓存当作提交准入。

拆包与首次去重后的验证记录（选集重叠，不累加）：API 专项 **13 passed**（203.24 秒），`context-partitions-api-final.log`；权限/查询扩展专项 **35 passed**（401.02 秒），`context-partitions-guards.log`；API/runtime/Compose **171 passed**（206.25 秒），`context-partitions-regression.log`；纯逻辑、回执、Agent 与 DDD/Portal **167 passed**（1.53 秒），`context-partitions-pure-final.log`。固定 exweb 两主题 **2 passed**（6.4 分钟），`context-partitions-e2e-final.log`，真实 6 AC/2 规则保留、分为多个子包、历史不改写及子包漏规则隐藏；已检查 390px 截图。

前两次浏览器尝试分别因在确认请求前启动历史读取超时、冗余遍历而失败；中间一批在新实现准备好后显式中断，不能算作通过。最终等待的是各自真实 HTTP 请求，而非调高整体超时。首次真实 MinIO 批次因运行中修改延迟 import 产生新旧接口混用；下一批 **1 passed**（251.80 秒），`context-partitions-exweb-final.log`。其 MinIO 夹具为 1 AC/1 规则，因此只证明 v1/v2 原文归档和回放，不冒充多子包 MinIO 验证。

### 即时授权查询优化与开发隔离

使用同一小型 PG 上下文夹具分析 5 次 prepare，授权 scope 仍为 **573 次**，SQLAlchemy `_execute_internal` 从 **3636 次降为 1344 次**；采样总耗时约 5.81 秒与 3.06 秒。证据为 `context-prepare-profile.pstats`、`context-prepare-after.pstats`。改为一条 MVCC 查询读取项目/当前成员/来源/权限，不缓存授权，也不删除提交或返回前检查。时间是在本机并发验证期间采样，不是正式性能门禁或生产承诺。

- 新增/旧有 ACL、持久化、Agent 检索与 ContextPack 专项 **35 passed**（107.58 秒），`context-scope-api.log`；来源权限、DDD/Portal/Compose 纯检查 **172 passed**（0.80 秒），`context-scope-pure-final.log`。
- API/runtime/项目权限/Agent 上下文回归 **188 passed**（204.63 秒），`context-scope-regression.log`，包括原文读取期间撤销成员或降为 viewer 后不返回正文。歧义成员记录失败而非挑选任意角色，版本/会话权限不提升为项目权限。
- 优化后的固定 exweb 两主题 **2 passed**（4.3 分钟），`context-scope-exweb-e2e.log`。6 AC/2 规则、每子包全局规则继承、预算、原文证据、撤回失效、刷新恢复和移动端继续通过。默认全量 E2E 终态继续收集。
- 最新真实 PG/MinIO 回放 **1 passed**（243.15 秒），`context-scope-exweb-minio-final.log`；报告 `verified_at=2026-09-19T08:21:35.889576+00:00`，v1/v2 归档、完整历史、批准撤回与恢复均通过，仍是 1 AC/1 规则的单子包工件。
- exweb 代码身份与 build/image 仓储专项 **11 passed**（66.65 秒），`context-scope-exweb-identity-final.log`。报告 `verified_at=2026-09-19T08:24:22.190260+00:00`，Tree-sitter 注册 546、CBM 注册 538，匹配实体身份一致；实际 PG 成员和来源 ACL 回放通过。没有执行 exweb/Maven，也没有扩大这些样本到多语言 gold 或供应商进程隔离验收。
- 开发应用已用 foreground 监督重新加载，无新迁移，仍为 0051；OpenAPI 同时保留 v1/v2，Portal/API/Runner HTTP 200，`dev:status` 全 ready。Portal build/lint/i18n 通过，保留既有大 chunk 警告。

早先两次直接运行旧 `npm run test:smoke` 错误复用了开发 API，在创建项目跳转处超时。这两次不算隔离验证，可能留下测试账号、会话及构建请求，未盲目删除开发数据。默认入口已改走现有一次性 PG 运行器，独立 API/Portal 端口及状态目录，并加入口回归检查；运行器直接调用 Node 脚本避免递归。修复后 `context-partitions-smoke-isolated.log` 与 `context-scope-smoke.log` 均 **smoke: success**。

新的真实 MinIO 批次发现旧适配器夹具只有内存角色、没有项目记录，现补真实 PG 项目/成员，不增加生产授权降级。代码身份夹具还暴露了两个 fixture 重复创建 `tool_invocations` 的历史问题：现在由 image fixture 创建完整表并负责销毁，build fixture 只消费它；未删除迁移或业务约束。

本轮并未迁移旧生成器、完成正式风险矩阵或 provider tokenizer，也未完成其余四类 ContextPack、P0-P6 或最终 V1 门禁。`exweb-context-requirements.md` 明确是验证夹具，不是维护者批准或生产运行结果。

## 测试设计 ContextPack 归档（0051，2026-09-19）

契约见[固定上下文包](./context-packs.md)。本次连接画像、独立需求批准和审阅筛选召回，不再把“当前可变 TaskContext”误认为固定可审计输入。正式归档经 `system_image.context.compile` 确认，读取可用 preview/list/read 三个 query tools；不向 Planner receipt 或 SSE 写入来源正文，不调用模型。

- 强制来源 AC/规则全部先入预算，approved oracle 固定确切 revision；没有批准的约束仍留在包里并阻断。词法支持候选保持 not_coverage，不继承业务批准。PG 摘要与 Outbox 同事务，私有 MinIO 存正文/Derivation，画像/authority/检索 receipts/证据可回放。
- 提交时在项目锁内检查 canonical request、当前批准/负向决定与 ACL；并发同 invocation 只提交一份工件和事件。历史读取另附失效状态，撤回需求或当前 oracle 超预算不改写旧包；权限/完整性错误不得降级返回旧内容。
- Knowledge → Image revisions 新增按需预览、明确确认归档、分页历史、原文证据展开和刷新后恢复。更改预算取消旧确认，写入不自动重试，错 scope/撤权隐藏整个敏感视图。沿用深浅色和移动端样式。
- Agent 工具发现同时覆盖中英文 ContextPack 请求。回归发现冗长描述中的连接词曾将 `run.start` 挤出 12 项详情，现排除英语虚词；没有增加工具数预算、删除旧工具或放宽执行权限。

已核验专项证据（选集重叠，不累加为独立总数）：

- 早期后端专项 **10 passed**（66.23 秒），`context-packs-second.log`；随后新增历史/大 oracle 用例初次 1 项失败，原因是测试遗漏 canonical query 必填 project_id，已修正请求，未放宽后端 schema。最终 API 专项 **9 passed**（116.59 秒），`context-packs-api-verified.log`，包含 HTTP purpose/policy 拒绝和有数据禁止迁移降级。
- 同 invocation 双 worker 竞争与禁止改绑定 **1 passed / 7 deselected**（12.08 秒），`context-packs-concurrency.log`。真实 PG 只产生一个 ContextPack 与一个业务 Outbox 事件。
- domain、Agent 工具发现与 DDD/Portal 边界 **145 passed**（1.27 秒），`context-packs-pure-final.log`；新原文工件适配器专项另行补跑。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 回放 **1 passed**（241.64 秒），`context-packs-exweb.log`。报告 `verified_at=2026-09-19T07:44:49.026071+00:00` 新增 `test_design_context`：两项强制来源约束全部保留、批准 oracle 固定、已拒绝测试候选排除、原文 S3 回读、撤回后 stale 及恢复不重复写入。画像 730 对象/546 代码；代码未执行。
- 固定 exweb 深浅色浏览器专项 **2 passed**（3.3 分钟），`context-packs-e2e-second.log`。真实 canonical 确认、PG 持久化、刷新后恢复、批准撤回和历史内容不变；仅末尾错误 scope 检查使用响应篡改 fixture。首轮 5 秒 UI 断言早于真实预览校验完成，改为等待该请求完成再断言；没有放宽生产边界。已检查 390px 两种主题截图，无横向溢出。
- 最终 API/runtime/Compose 回归 **192 passed**（327.70 秒），`context-packs-regression.log`；含工件专项的纯逻辑/边界 **146 passed**（1.44 秒），`context-packs-pure-verified.log`。隔离 PG smoke **success**，`context-packs-smoke.log`。
- 默认完整 E2E **43 passed / 1 skipped**（6.5 分钟），`context-packs-e2e-full.log`；跳过项为需要显式启用的 exweb 结构专项，不能算作通过。固定 exweb ContextPack 两主题已由上述专项单独验证。
- Portal build/lint/i18n 和 diff 检查通过；开发应用重载至 0051，Portal/API/Runner HTTP 200、Worker 四类队列有 poller，Docker 仅基础组件。保留已有大 chunk、LangGraph serde 与 Python 3.9/Boto3 警告，模型路由为开发 fallback，不算真实模型验收。

当前固定 exweb 包为 blocked（配套业务规则尚未独立批准）；`generation_authorized=false` 是明确限制，不是 P5 完成。公开预算测量为 UTF-8 字节，不冒充实际 tokenizer；自动拆包在上方 v2 节后续交付，正式生成 UoW/coverage matrix、其余四种用途、风险/BehaviorSpec、正式 head、真实模型/gold、P0-P6 和最终 V1 门禁仍未完成。此批临时 PG/MinIO 测试数据已清理，报告 UUID 不是开发库常驻演示对象。0051 单 AC 浏览器样本预览约 5–6 秒、归档约 14–17 秒、历史展开约 8–10 秒；不将这些样本冒充性能验收。

## 来源 AC 独立批准与恢复（0050，2026-09-19）

`quality_loop` 现在拥有独立的 AcceptanceRevision，通过 `quality.acceptance_specification.review` 的 reviewer 权限和确认门禁，批准或撤回冻结来源 AC 上的可观察 oracle。原文、理由、oracle 在私有对象存储；PG 追加式元数据、canonical invocation、CAS 和 Outbox 绑定确切画像/hash/来源修订。来源投影和 `implements/asserts` 的语义不变，不会因为批准就增加业务覆盖或发布画像。完整契约见[正式 AC 与独立需求批准](./acceptance-authority.md)。

Knowledge 的冻结 AC 详情新增按需展开的批准面板；编辑字段/理由或重新读取状态清除原确认。成功后可以显式重载再撤回；错 scope 或撤权隐藏旧内容。Planner 的 `query.quality.acceptance_specification` 只接收经当前权限重验的查询时元数据，不把历史 receipt 当作当前 oracle 准入。

本轮补齐了业务事务成功、工具完成回执丢失后的 application 恢复：同 invocation 在当前权限下重验 canonical input 与原私有工件，返回原修订/时间/hash；并发重试只提交一次修订和事件。其他命令已经撤回后仍可恢复原审计结果，但不会重新激活，`resolve_oracle` 继续拒绝新使用。oracle 或理由连同命令表一起被篡改也无法伪装成原结果。该测试不等价于完整 Temporal kill-worker 故障注入门禁。

已核实的证据（选集有重叠，不累加为独立用例总数）：

- 新增及既有 AC API/PG/domain/Agent 专项 **12 passed**（38.05 秒），`acceptance-authority-recovery-api.log`。覆盖独立确认、错误来源/角色/证据、CAS、来源更新不继承、撤回与历史、提交回滚、权限撤回、恢复与同命令并发。
- API/runtime/Compose 与 AC 回归 **183 passed**（214.64 秒），`acceptance-authority-regression-final.log`；不是整个 API 测试集，保留 LangGraph serde 提示。
- DDD/Portal 分层及 Agent 观察 **159 passed**（1.41 秒），`acceptance-authority-boundaries-final.log`。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 回放 **1 passed**（159.84 秒），`acceptance-authority-exweb-final.log`。730 对象、546 代码成员；批准私有工件可读，配套需求变化后的新画像保持 unapproved，撤回阻断新消费，旧回执恢复不写新对象、不改变撤回后的头。报告 `.nasus/validation/exweb-source-documents-report.json` 的 `verified_at=2026-09-19T07:21:31.854506+00:00`，新增恢复证据字段。保留 Boto3/Python 3.9 警告。
- 上述 exweb 的需求、用例、模型 native transport 和审阅身份均明确标为验证夹具；没有外部模型调用、目标代码/Maven 执行或 exweb 作者的正式业务批准，不是独立 gold。临时 PG/MinIO 数据已清理，报告中的 UUID 不是开发库常驻演示对象。
- 固定 exweb 的真实创建/确认/持久化/撤回/历史读取 E2E **2 passed**（1.3 分钟），`acceptance-authority-e2e-final.log`。原失败是已填值 textarea 的嵌套 label 精确定位失效，改用 textbox 可访问名称，并增加持久化最终修改值的断言；没有放宽确认逻辑或延长超时。同步修复批准/关联候选两个兄弟面板的重复 React key，测试显式拒绝重复 key 与页面异常。
- 已查看深浅色 390px 截图 `output/playwright/acceptance-authority-{light,dark}-mobile.png`，无横向溢出；沿用原 UI 和滚动容器。最后错 scope 检查使用显式坏响应 fixture，其余批准与撤回均为真实 API/隔离 PG。
- 默认完整 E2E **41 passed / 1 skipped**（5.0 分钟），`acceptance-authority-e2e-full.log`。跳过项是要求显式 `EXWEB_FIXTURE_ROOT` 的真实 exweb 结构检查，不将 skip 算作通过；AC 的真实 exweb 深浅色链已由上述单独专项验证。
- 随后显式启用同一固定 exweb checkout 补跑结构浏览器检查，**1 passed**（25.8 秒），`acceptance-authority-exweb-structure-e2e.log`。验证 13 条注解路由及其原文行号、代码候选/归档证据、canonical 查询和构建调查入口；这是单独补跑记录，不改写默认全量批次的 skip 计数。
- Portal build/lint/i18n、diff 检查通过，隔离 PG smoke **success**，`acceptance-authority-smoke-final.log`。保留已有大 chunk 提示。
- 本机应用经 `dev:foreground` 重载最新实现，0050 已应用，Portal/API/Runner HTTP 200、`dev:status` 全 ready；Worker 51905 在 AgentGoal/ConversationTurn 的 workflow/activity 四类队列均有 poller。Docker 仍只运行外部组件；Embedding/Rerank 的开发 fallback 不计真实检索验收。

0050 不代表正式 US/AC 从零编写、BehaviorSpec、画像发布或 ContextPack 已完成。下一步下游编译必须引用确切 approved revision，在提交边界重验 authority 与 ACL，不能复用旧 receipt，也不能把来源 AC 的已接受关联直接算成人工修改后 oracle 的覆盖。完整 P0-P6、独立 gold、真实模型和最终 V1 门禁仍未完成。

## 审阅筛选召回与有界历史重放（2026-09-17）

新增 `query.system_image.links.screened_candidates` / `nasus.link-recall.reviewed.v2`，完整有界匹配集先筛选适用负例，再截取前 N 项；相同修订 reject 不会占据名额而漏掉后续可用项。固定查询时全部命中头（包括空集合）、选择 pins 和结果摘要；原始 v1、旧模型输入 hash 不变。Portal 显示排除数、来源变更待重验及历史审阅不继承批准，重新查找才刷新头。

模型预览/评估新增可选 `recall_invocation_id`，经 observation port 验证 canonical v2 回执后接受替补候选，独立复核当前审阅头。归档输入绑定完整回执 digest，历史读取重验固定原文，但不递归展开更早的审阅/模型/召回链。首次准入仍完整展开；修改回执元数据后旧评估校验失败。详见[召回协议](./semantic-link-recall.md)。没有新增数据库迁移或减少旧 Tool ID。

- 单元、Agent 发现及 DDD/Portal 分层：**211 passed**，`screened-recall-pure-final.log`。包含 40 个匹配主体在 top-1 前排除 39 个、stale/拒绝优先级、最终授权重验与旧 v1 结果不变。
- 隔离 PG canonical 召回/筛选/模型评估：**31 passed**（272.11 秒），`screened-recall-api-final.log`。包括两次拒绝、原 claim defer 后重新出现、旧空/非空回执重放、超出原 raw top-1 的候选评估、历史验证无递归、元数据篡改、来源变化和模型入口竞争。首次新增测试预期把完整性失败写成 409，核对既有接口为 502 后修正，未改变生产错误契约。
- API/runtime/Compose 回归：**171 passed**（170.87 秒），`screened-recall-regression.log`。与专项选择集不累加为独立测试总数；不是全部 API 或完整 V1 发布门禁。
- exweb 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 回放：**1 passed**（166.07 秒），`screened-recall-exweb-final.log`。730 对象/546 代码成员；asserts 的唯一候选因原拒绝从 1 变为 0，配套 AC 更新后恢复为 1 且标记待重验，implements 的已审阅代码也标为 stale；旧回执不变。报告 `verified_at=2026-09-16T23:28:00.427321+00:00`，新增 `review_screened_recall / review_screened_receipts / reingested_screened_recall`。第一次请求 100 条超出既有 64 KiB 上限，最终用默认 30 条验证，未放宽上限。
- 上述 exweb 配套需求/用例、模型 native transport 是明确夹具；不调用真实外部模型、不执行目标代码/Maven，不将 546 个字面匹配当成实现关系或语义准确率。临时 PG/MinIO 写入已清理。
- 固定 exweb 的文档/语义交互深浅色 E2E：**4 passed**（7.8 分钟），`screened-recall-e2e.log`。真实来源摄入和 canonical v2 召回；模型/审阅交互仍是协议 fixture，持久化与筛选的真实性由 PG 专项证明。
- 新筛选 UI 专项最终 **2 passed**（28.7 秒），`screened-recall-ui-verified.log`：旧回执的 focus 重放不自动发现新头、重新查找刷新、排除计数、stale/已审阅未批准提示、深浅色 390px、错误 scope 整个画像清屏。来源及 canonical 查询是真实 API，审阅状态是显式 transport fixture；已查看深色移动端截图 `output/playwright/screened-recall-dark-mobile.png`。首次测试未翻页定位 AC，第二次误期望局部错误而非既有整页清屏；修正测试定位与断言后通过，没有放宽生产校验。
- Portal build/lint/i18n、diff 检查通过，隔离 PG smoke success；保留大 chunk、Python 3.9/Boto3 与 LangGraph 提示。本轮完整 E2E 和 `verify:v1-release` 未运行，不作全部门禁完成声明。
- 本机应用已通过 `dev:foreground` 重载，Worker PID 67126 在 AgentGoal/ConversationTurn 的 workflow/activity 四类队列都有近期 poller。Portal/API/Runner 200、开发依赖 ready，数据库仍 0049；Docker 仍仅运行外部组件，embedding/rerank 开发 fallback 不计为真实检索验收。

这推进 P3，不替代 P0-P6。后续继续通用生命周期/隔离、注册表正式切换、动态调查授权与恢复、正式 AC/oracle、重审覆盖/冲突、结构与向量召回、真实 gold、P4 更新治理、P5 五类 ContextPack 以及 P6 全量门禁与业务试点。

## 历史审阅自动发现与模型入口拦截（2026-09-17，上阶段记录）

在上一阶段显式查询之上，新增 `SemanticScreeningApplicationService` 和登记身份查询端口。生产 preview/evaluate 自动查找所有匹配 claim 的当前头，不依赖调用者选择旧 decision；每条匹配再验证原归档评估、不可变端点、完整历史和当前来源 ACL。范围固定为 project/predicate/双方 binding/entity/kind，最大 30 个主体/64 个匹配头，超预算失败而不截掉负例。

相同修订任一 reject 阻止新的模型请求；新的 image/claim 或另一 claim 的接受不能清除该拒绝。原 claim 的人工复审可解除拦截，但必须重新预览确认。稳定实体的新修订显示 stale、允许受控重新评估，不转移 approval。Knowledge 预览展示命中头、拒绝/变更提示和审阅摘要，并在拒绝时禁用确认按钮。

新增 `review_scope_digest` 固定空历史及完整匹配头。PG 预留和提交在与审阅相同的项目锁下复核，模型发送前/返回后也重新检查；变更不自动重试或准入结果。旧已归档请求缺少该字段仍可读取/幂等重放，旧未执行请求必须重新预览。原 lexical recall v1 及历史输入 digest 保持原样；**候选列表的固定范围过滤仍须独立版本化交付**。网络发送后的审阅变更不能撤销远端请求，但不能提交为新评估。

已确认测试（不同批次可能重叠，不相加为独立用例总数）：

- PG 模型/人工审阅/适用性联合 **24 passed**（175.88 秒），`semantic-screening-api.log`；新增自动匹配和四个竞争边界 **7 passed**（69.60 秒），`semantic-screening-guard.log`。
- 纯领域/应用、供应商协议、Agent 观察及 DDD/Portal 分层最终 **326 passed**（2.57 秒），`semantic-screening-pure-final.log`。包括原始请求兼容、guard 缺失失败、多个 claim 拒绝优先、完整头预算和空历史摘要。
- API/runtime/Compose、成员冻结/历史查询/image-query 回归 **186 passed**（449.99 秒），`semantic-screening-regression.log`。保留已有 LangGraph 弃用提示。
- exweb 真实 PG/MinIO 最终 **1 passed**（128.54 秒），`semantic-screening-exweb-final.log`。固定提交仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，730 对象/546 代码成员；自动发现 asserts 拒绝并阻止新模型调用，配套 AC 新修订使两个关系通道都 stale。报告新增 `semantic_automatic_screening` / `reingested_semantic_screening`，`verified_at=2026-09-16T23:02:54.907512+00:00`。目标代码未执行，模型仍是显式 HTTP fixture，不是业务 gold；本次隔离数据及私有夹具对象已清理。
- Portal build/lint/i18n、隔离 PG smoke 和 diff 检查通过。首次 build 的未登记翻译键已复用既有键修正；首次 exweb 测试因局部 pytest 导入遮蔽而失败，移除多余导入后重跑通过。保留既有大 chunk 和 Python 3.9/Boto3 告警。
- 完整 E2E **38 passed**（10.5 分钟），`semantic-screening-e2e.log`。包含深浅色拒绝时禁用确认、原 claim 明确复审后重新预览、旧判断/冻结历史不重写、移动端布局及撤权/错配清屏。已查看新增 blocked 深浅色截图。语义输出/审阅依旧是浏览器协议 fixture，真实确认、竞争和持久化由上面的 PG 测试验证。
- 本机 `dev:foreground` 已重载，迁移仍为 0049，`dev:status` 全 ready；Portal/API/Runner 均 HTTP 200。Worker PID 58284 在 AgentGoal/ConversationTurn 的 workflow/activity 四类队列均有 90 秒内 poller。Docker 仍仅基础组件；开发 embedding/rerank fallback 不计为真实检索验收。

这推进 P3 的实际推断入口，不代表原始 P0-P6 完成。版本化召回/负向索引、原始资料到正式 AC/BehaviorSpec 的批准、跨版本重审及发布 CAS、真实模型与 gold、P4 演进和 P5 五种 ContextPack 仍须交付；完整 `verify:v1-release` 尚未验收。

## 跨修订审阅适用性检查（2026-09-17，上阶段记录）

新增 `query.system_image.links.decision_applicability`，对旧人工审阅与显式选定的新画像端点做只读比较。使用冻结成员及文档的登记身份，不使用名称相似度；相同修订的 reject 返回排除候选动作，身份保持但修订变化返回 stale/revalidate，匿名/歧义身份不隐式跨版本匹配。所有路径均不继承 approval。具体契约见[跨修订适用性](./semantic-decision-applicability.md)。

新工具接入 canonical ToolRuntime、回执授权展开和 Agent 工具发现；回执仅包含 pins、hash 和枚举状态，重新规划不隐式携带原因或原文。固定 claim head 可历史回放；原 claim 后续重新审阅不改写旧回执，撤权仍立即失效。不增加迁移，不改写任何旧 assertion/decision，也不更改旧召回输入摘要。

这推进了 P3 的跨修订检查，但**尚不是完整负向决定闭环**：全项目自动发现/匹配、召回与评估入口强制过滤、跨修订重审 UI、负向覆盖策略、发布时 CAS 和通用 lineage 仍待实现。P0-P6 原有范围与最终门禁保持不变。

- 领域、Agent metadata 观察/发现、DDD 与 Portal 边界联合 **202 passed**（1.89 秒），`semantic-applicability-pure.log`。最终 HTTP 专项 **3 passed**（55.31 秒），`semantic-applicability-final.log`：真实重新摄入、同 entity 新 revision、旧回执重放、旧 reject 后改为 accept、不转移批准、幂等、损坏与错请求、读取中撤权。
- API/runtime/compose、画像回执、文档持久化及代码身份登记回归 **194 passed**（222.50 秒），`semantic-applicability-regression.log`。
- 新旧语义查询、人工审阅、冻结、模型评估与 image-query HTTP 联合 **39 passed**（439.19 秒），`semantic-applicability-guards.log`。包含原 canonical 命令确认、CAS、幂等、权限和不可变成员保护，未减少旧工具。
- exweb 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 检查 **1 passed**（110.83 秒），`semantic-applicability-exweb-final.log`。730 个冻结对象/546 个代码成员；同一端点修订的 asserts reject 仍返回排除候选动作；配套 AC 更新后 implements/asserts 都返回 stale，旧冻结成员不变。需求夹具复制到临时目录后修改，不编辑示例仓库或执行目标代码。报告 `verified_at=2026-09-16T22:29:15.213432+00:00`；它不是实际模型语义准确率、独立 oracle 或业务发布验收。
- Portal build/lint、i18n、隔离 PG smoke 与 diff 检查通过。仍有既有大 chunk、Python 3.9/Boto3 和 LangGraph 弃用提示；未运行完整 `verify:v1-release`，不作上线完成声明。
- 首次 HTTP 专项 **5 passed / 1 failed**：撤权注入测试使用了不存在的 container 属性，修正为 `tool_images.images` 后最终专项全部通过；首次扩展 Agent 测试错误复用了旧列表回执的 `decision_ids` 断言，改为验证新回执的固定 head/动作/approval=false 后通过。一次 guards 命令误写测试文件名、未执行测试，已纠正路径重跑，未放宽生产校验。
- 首轮完整 E2E **37 passed / 1 failed**（10.6 分钟）：深色来源权限用例切换 offline 的瞬间打断画像请求，trace 为 `ERR_INTERNET_DISCONNECTED`，测试未等到目标 403；失败快照中旧知识及弹窗已隐藏。测试改为 visibilitychange 触发现有真实 focus-refetch，保持页面/弹窗状态、不 mock 响应、不删除权限断言。该文件三次连续复跑 **15 passed**（51.1 秒），`semantic-applicability-source-e2e.log`；完整套件另行复跑，以最终结果为准。
- 修正上述测试触发竞态后，最终完整 E2E **38 passed**（9.3 分钟），`semantic-applicability-e2e-final.log`。没有跳过失败用例；浅色/深色语义评估、移动端、历史画像、来源权限撤销与恢复全部保留。本轮所有验证进程已终态，只有开发服务监督进程继续运行。
- 开发服务已用 `dev:foreground` 更新，Worker PID `45359` 的 AgentGoal/ConversationTurn workflow/activity 四类 poller 均已检查；Portal/API/Runner 200，新 `SemanticDecisionApplicability` 已出现在运行中 API 的响应 schema。持久层仍为 PG，外部依赖仍用 Docker；模型 Embedding/Rerank 的开发 fallback 状态未改变。

## 语义审阅查询与有界分页（2026-09-17）

新增 `query.system_image.links.semantic_decisions`，经现有 ToolRuntime 查询未冻结的人工审阅历史。回执固定空/非空历史头以及 image/evaluation/assertion/evidence 摘要，持久化仅包含元信息；受控展开重新检查 canonical request、完整证据、当前来源与项目权限和结果摘要。Agent 重规划不隐式接收审阅正文，不新增模型调用、自动裁决或发布。

冻结记录的前端读取新增有界缩页：只对明确的页面超限响应缩小条数，保留后端 64 KiB 限制和旧回执计算。对象及成员页使用相同窗口；上一页按真实 offset 栈返回；异常游标、权限/完整性失败和单条超限继续隐藏旧内容，不将错误当作可重试写操作。

- 25 条含长中文/emoji 的合法冻结语义成员复现了默认页超限；缩页读取与 body-free 回执重放 **2 passed**。领域、Agent 观察/工具发现、DDD/Portal 分层联合 **166 passed**（1.60 秒），`semantic-history-pure.log`。
- 分页浏览器专项及既有画像 UI **15 passed**（51.6 秒），`image-page-budget-e2e.log`。验证成员页超限时连同对象页重新缩页、3/6/1 条变长页前后翻页、切换 section 重置、单条超限停止、五类不可缩页错误和错误游标。未改变深浅色或滚动条样式。
- 新历史查询首轮 **20 passed / 1 failed**（36.29 秒）。失败测试未将查询绑定到 Conversation，因此没有会话 SSE Outbox；测试已改为实际 Agent 会话调用，不修改无会话事件语义。修正后的扩大 PG 回归、真实 exweb 和完整 E2E 结果见下。
- Portal build/lint/i18n、`git diff --check` 通过。保留既有大于 500 kB 的前端 bundle 告警。本轮不新增迁移，仍为 0049。
- 真实 exweb + PostgreSQL + MinIO **1 passed**（77.10 秒），`semantic-history-query-exweb.log`。固定 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc`、546 个代码成员/730 个对象，implements/asserts 两条历史均生成 metadata-only 回执；空历史及改判前回执继续回放原结果。最新 v3 候选 hash `sha256:206900d9b74ac31264298e6d462504fca985d454242cc6f9047c2d8f64e5aa61`，报告新增 `semantic_history_receipts`。仍使用明确的伴随 US/用例与 synthetic native transport，不执行目标代码、不调用外部模型、不宣称真实语义正确率；临时测试库/工件已清理。
- 扩大查询/审阅/冻结/回执、Agent 与分层检查 **193 passed**（291.07 秒），`semantic-history-query-guards.log`；API/runtime/Compose 回归 **171 passed**（194.11 秒），`semantic-history-query-regression.log`。批次存在重叠，不累加为独立用例数。隔离 PG smoke **success**，`semantic-history-smoke.log`。
- 本机应用已重新启动为 foreground 监督进程，新 Worker 37618 的 AgentGoal/ConversationTurn workflow/activity 队列均有近期 poller；Portal/API/Runner HTTP 200，`dev:status` 全 ready，OpenAPI 已包含 `SemanticDecisionPage`，数据库当前 **0049_semantic_membership (head)**。基础组件继续使用 Docker，Embedding/Rerank 仍为开发 fallback。
- 最终完整 E2E **38 passed**（10.1 分钟），`semantic-history-page-full-e2e.log`。包含固定 exweb 代码与伴随资料、语义审阅/冻结协议、深浅色/移动端和新增分页保护；已查看更新后的深色移动端截图，保持无横向溢出和无可见滚动条。最终 `git diff --check` 通过。

本轮没有完成跨来源修订负向决定适用性、独立 authority/oracle/gold、完整构建授权、增量更新/发布治理、ContextPack、真实业务试点或 `verify:v1-release`。这些仍按原 P0-P6 目标继续交付。

## 语义成员冻结（0049，2026-09-17）

契约见[固定审阅成员](./frozen-review-membership.md)。`system_image.revisions.freeze_semantic` 将精确的 assertion/人工 decision 固定为 v3 候选，保留父对象、证据及 references。并发改判需要重新确认，未选择的已有成员不会追随 latest head。支持同 invocation 提交后恢复、PG/MinIO 完整性校验、metadata-only 查询回执及现时来源授权；不能把新来源修订或重复端点的 claim 用于绕过旧负向决定。

- Knowledge 增加独立冻结确认与固定语义审阅页签，不自动发布或批准业务 oracle/覆盖。冻结成功仅标记修订列表待更新，用户重开/重载时重新授权，避免立即刷新父选择器导致成功回执被卸载。失败不自动重试。
- exweb 固定提交 `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 验证通过：546 个代码成员、730 个对象；v3 固定 1 个 references 与 2 个 implements/asserts 决定，语义改判后旧快照不变，更新 references 时继续保留语义历史。v3 工件摘要 `sha256:4d069e0d17273b3c517768efb1fd1ec5525c9ca411671d99b989bacf181f0754`。报告 `.nasus/validation/exweb-source-documents-report.json`，测试 **1 passed**（50.94 秒），日志 `semantic-membership-exweb.log`。
- 该验证使用显式伴随需求/用例资料和 native HTTP transport fixture，两个语义关系仍为 unknown/defer；没有调用外部模型、运行 exweb/Maven 或批准来源 authority。测试库和本次临时 MinIO 工件随后清理，报告 ID 不是开发库永久对象。
- 首批冻结领域/API 和 references 回归 **22 passed**（63.60 秒），`semantic-membership-first.log`。后续扩展检查首轮 **200 passed / 1 failed**：新增恢复测试错误地尝试 HTTP confirm 一个 running invocation；该接口按既有契约不重新执行，测试改为绑定实际 actor 的 worker application 恢复入口。没有更改 Runtime 确认契约。
- Portal build/lint/i18n 通过。浏览器测试发现成功提示被父列表刷新卸载的问题已修复；随后定位到新增冻结错误与模型错误同时存在时测试选择器不唯一，已改为精确检查模型错误，不隐藏实际错误信息。最终全量回归结果另记于本节下方。
- 最终冻结链、审阅、权限与分层检查 **201 passed**（238.73 秒），`semantic-membership-final-guards.log`；API/runtime、真实 PG 仓储迁移与 Compose 回归 **176 passed**（175.09 秒），`semantic-membership-regression-final.log`。早先仓储夹具缺少 0047–0049 迁移导致的三项失败已修复后重跑，不对生产代码增加缺表降级。
- 完整 E2E **29 passed**（9.6 分钟），`semantic-membership-e2e-full.log`；隔离 PG smoke **success**，`semantic-membership-smoke.log`。已查看 `output/playwright/exweb-frozen-semantic-light-mobile.png` 和 `exweb-frozen-semantic-dark.png`，未见横向溢出；深浅色及移动端检查均通过。
- 开发应用保持 foreground 监督、本机运行，Docker 仅基础组件。Portal/API/Runner HTTP 200、`dev:status` 全 ready；Worker 30665 的 AgentGoal/ConversationTurn workflow/activity 四类队列均有近期 poller。0049 已迁移；Embedding/Rerank 仍为开发 fallback。

未完成范围仍包括跨来源修订负向适用性、独立 authority/oracle/gold、readiness/conflict、完整更新/批准 head/ContextPack、P0-P6 和 `verify:v1-release`。本轮没有将“冻结候选”替代正式版本治理。

## 语义断言与人工审阅（0048，2026-09-17）

契约见[语义判定与执行](./semantic-link-judgment.md)。本轮将归档评估接入 typed assertion/decision 和 Knowledge 人工审阅，不改写原 references 的语义、端点约束或 hash，也不把接受关联当作正式业务规范、覆盖率或发布。

- 新断言固定 evaluation/image/input/evidence/oracle 摘要及双方 object/revision。同一画像及同一端点对的重复模型评估共享 claim 的人工决定链，不能靠重新推断消除 reject。accept 要求 supports，asserts 还要求已有预期字段；unknown/contradicts/unrelated 仅可 reject/defer。来源 authority 仍 pending，跨修订继承仍待实现。
- `system_image.links.review_semantic` 走现有 ToolRuntime 确认和 reviewer RBAC。PG 追加式表、复合 FK、项目锁及 CAS 固定前驱，断言/决定与无正文 Outbox 同事务；提交前重验 canonical payload、固定评估/成员及 ACL。支持同 invocation 幂等，已有数据阻止降级；损坏持久化 payload 返回完整性错误。
- 前端按需展开审阅，显示当前决定所对应的 evaluation ID、理由及历史。输入或历史改变清除确认；并发改判、未知提交结果不自动重试，需重读后明确确认。历史可 pin head 分页；撤权或 scope 错配隐藏旧视图。沿用深浅色/移动端/隐藏滚动条及领域 API/hook 边界。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 回放，已在 chatStream→AC 和伴随用例→AC 两个通道记录 defer，验证重新读取、相同 invocation 回放及 unknown 禁止接受，审阅无额外模型调用。当前报告候选 hash `sha256:b9d8bfcd2a7289055ea746efe86df0cc11426472e76e445ff6562947850b8133`，546 个代码成员、730 个总对象；原 2012 条兼容关系仍不算已接受语义边。响应是显式 native transport fixture，`external_model_called=false`，没有执行 exweb/Maven，也不是独立业务 gold。

已核实证据（批次重叠，不累加为独立用例数）：

- 首批纯测试/DDD **130 passed**，API 审阅 **4 passed**（33.34 秒）；`semantic-review-unit.log`、`semantic-review-api-first.log`。
- 真实 exweb/PG/MinIO、审阅及 DDD/Portal 联合验证 **147 passed**（74.36 秒）；`semantic-review-exweb.log`。保留 Boto3/Python 3.9 弃用警告。
- 新审阅、既有评估/引用/冻结及分层保护 **177 passed**（154.12 秒）；`semantic-review-guards.log`，包含 canonical payload 被改、提交时撤权、Outbox 回滚及迁移不能丢数据。
- Portal build/lint/i18n 通过。React lint 曾指出 render 读取 ref，已改用 mutation 状态驱动按钮，只在点击处理器读同步重复提交锁。浏览器首轮原生 option 的 `toBeDisabled` 判定不适用，已改查原生 disabled 属性，不放宽生产准入规则。
- 最终审阅/迁移/权限与分层 **154 passed**（58.17 秒），`semantic-review-final-guards.log`；覆盖 qa_lead 可以决定、待确认后降级不能继续确认，以及项目级缓存失效键。此前最后一批审阅专项 **16 passed**（67.45 秒），`semantic-review-final-api.log`；单独角色测试 **1 passed**，`semantic-review-role.log`。选集重叠，不求和。
- API/runtime、引用、召回、固定证据和 Compose 回归 **189 passed**（232.16 秒），`semantic-review-regression.log`；保留既有 LangGraph serde 警告。深浅色专项 **2 passed**（5.5 分钟），`semantic-review-e2e-final.log`；最终完整 E2E **29 passed**（8.8 分钟），`semantic-review-e2e-full.log`。包含重复评估仍保留人工否定、只有 supports 能接受、接受后来源 authority 不变、旧 unknown 查看同 claim 的后续决定、明确改判、撤权及坏 scope 清屏。浏览器模型/语义命令/审阅使用显式协议 fixture，真实 PG 确认及 CAS 由 API 集成测试验证，不冒充外部模型实测。
- 最终 Portal build 为 547 模块、主包 626.09 kB，仍有既有 chunk 大小告警；lint/i18n 与 `git diff --check` 通过。隔离 PG smoke **success**，`semantic-review-smoke.log`。已查看浅色移动端、暗色桌面审阅截图并修正子标题的继承字号/边距；无横向溢出，保持隐藏滚动条滚动。
- 本机 `dev:foreground` 已重新加载至 **0048_semantic_reviews**，OpenAPI 含新审阅 GET；Portal/API/Runner HTTP 200、`dev:status` 全 ready。新 Worker PID 22415 在 AgentGoal/ConversationTurn 的 workflow/activity 四类队列都有近期 poller。Docker 仍仅 PG/MinIO/Temporal 等基础组件；Embedding/Rerank development fallback 不计入真实检索验收。

当前语义决定明确标为 `not_in_image_membership`；下一阶段必须接入版本化画像成员及受控 Agent 查询，不能将旁路审阅表当作完整 P3。完整 P0-P6、跨修订负向适用性、真实模型/gold 和 `verify:v1-release` 仍开放。本次未执行目标仓库或安装其依赖，报告中的测试 UUID 属于已清理的隔离库，不是开发库永久演示数据。

## Knowledge 语义评估确认、引用与历史（2026-09-17）

本轮延续 0047，不增加数据库迁移。前端候选勾选和模型选择、目的地/输入范围预览、单次发送确认、proposed 结果及引用定位已接入既有 Knowledge/Image revisions。API/hook 在领域模块，route 组件不直接调用后端；仍经过 canonical ToolInvocation，未加入自动模型出口或自动接受关系。

- 改变候选/模型清除旧确认；测试通过且非 legacy 的自定义 chat 模型才可选。确认按钮检查当前模型是否可用，避免界面可点而 hook 静默拒绝。调用期间不改变输入；失败不自动重试，并引导先检查历史。离开视图不取消已确认调用，限制明确展示。
- 结果 GET 增加固定 request 和无全文的 span 定位；新增固定画像/目标/relation 的历史分页 GET。后端复核完整来源权限及返回前 ACL，前端核对请求/画像 hash、修订、source/evidence、引用区间和 oracle 所属。历史或结果读取错误时，父视图隐藏原先的敏感内容。
- 引用区分解析字段与原文，展示路径、行号、Unicode 半开区间，点击后经原有授权接口读归档。保留深浅色/移动端/无可见滚动条，使用 React 文本渲染；没有 Accept/Reject 或官方发布按钮，不将模型推断标作业务覆盖。
- exweb 仍固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`。新浏览器测试使用真实三源摄入/候选/归档证据与隔离 PG，**仅模型选择与语义命令/结果接口使用显式 protocol fixture**；后端真实确认、原生 HTTP transport 和 PG/MinIO 分别由集成测试验证。不把浏览器协议模拟宣称为真实外部模型判断。

已取得的证据（批次重叠，不累加为独立用例数）：

- 历史分页、scope/ACL 中途撤回、结果定位 DTO 和分层检查 **157 passed**（61.43 秒），`semantic-ui-api.log`。最初深浅色专项 **2 passed**（1.7 分钟），`semantic-ui-e2e-first.log`；随后补充更换候选、错修订/错证据/伪 oracle/非法引用区间的浏览器负测。
- 真实 PostgreSQL + MinIO 的 exweb 回放、语义/HTTP/分层选集 **281 passed**（86.36 秒），`semantic-ui-exweb.log`。报告 `exweb-source-documents-report.json` 当前候选 hash 为 `sha256:ad832d91546e3ac316870a21d00b53a9d223ff7f18cba11a0cd2a08e1b3c9530`；两个通道仍各一次 transport 调用、私有工件 roundtrip、重放无额外调用、`external_model_called=false`。未执行 exweb/依赖脚本；隔离库及本次临时对象已清理。
- 候选变更和四类错配负测专项 **2 passed**（3.3 分钟），`semantic-ui-e2e-guards.log`。API/runtime、既有引用/裁决/成员、召回/证据及 Compose 回归 **199 passed**（255.96 秒），`semantic-ui-regression.log`；保留 LangGraph serde 警告。
- 最终完整 E2E **29 passed**（6.8 分钟），`semantic-ui-e2e-full.log`，包含 exweb 两种主题的确认、引用、历史恢复、失败不自动重试、撤权/错配隐藏和移动端滚动检查。补齐新子目录递归及语义 API 的 route 边界保护后，DDD/Portal 边界 **137 passed**（0.83 秒），`semantic-ui-boundaries.log`。
- Portal build/lint/i18n 通过；544 模块、主包 614.00 kB，保留既有 chunk 告警。隔离 PG smoke **success**，`semantic-ui-smoke.log`。已查看浅色桌面与移动端确认面板、引用结果及暗色移动端截图；长地址与摘要换行，无横向溢出。
- 本机 `dev:foreground` 已重新加载，迁移仍为 **0047_semantic_evaluations**；OpenAPI 包含新历史接口，Portal/API/Runner 均 200，`dev:status` 全 ready。当前 Worker PID 4784 在 AgentGoal/ConversationTurn workflow/activity 四个队列均有近期 poller；Docker 仍仅基础组件，development fallback 不算真实语义验收。

完整 P0-P6、语义裁决与成员冻结、受控真实模型/gold 和 `verify:v1-release` 继续开放。这里交付的是完整语义审阅链的确认与结果查看阶段，不将旁路评估归档作为最终事实层。

## 显式确认的单次语义评估（0047，2026-09-17）

契约见[语义判定与执行](./semantic-link-judgment.md)。本阶段补齐真实可调用的网络适配器及确认/持久化链，仍不把归档评估当作 accepted assertion、覆盖率或完整 P3。

- `query.system_image.links.evaluation_preview` 返回固定输入/模型摘要、HTTPS 目的地、来源 binding 和一次调用限制；`system_image.links.evaluate` 必须由项目管理员经 canonical user confirmation 执行。新增 GET 私有结果读取。没有使用可变 active route，也没有向默认 Planner 增加原文。
- 模型配置与加密凭据一次性读取快照。未测试、legacy 或不安全 URL 被拒绝；预留后发送前再核对 binding。发现并修复真实确认元字段被严格业务 schema 误拒的问题，不放宽用户输入 schema 或治理检查。
- native HTTP 适配 OpenAI/compatible、Anthropic、Gemini，拒绝重定向、截断、工具输出、网络失败、自动重试、fallback 和 JSON 修补。请求/响应/结果有字节上限，60 秒/8192 output tokens/一次调用为硬上限，费用未知明确标记；这不是累计货币预算。
- 两张 append-only PG 表记录确认、单次调用预留和完成工件；Outbox 同事务。失败、取消或未知网络结局不再使用原调用重发；完成后重试读取相同工件。来源在关键边界重新授权，LLM 审计只有摘要/usage/latency；引用只在私有对象存储中，GET 重验原输入、输出及当前权限。
- 固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 报告新增 `semantic_evaluations`。两个关系通道各经过一次 native MockTransport、PG reservation、S3 工件回读，再验证重放不发请求。候选 hash `sha256:6242bf81eb4c77a42a0ebcd6aa4eaf40e6f10bf96af4dc612b09209ab6ee0377`。报告明确 `external_model_called=false`，结果仍为 unknown/proposed；不是外部模型实测、语义准确率、独立业务 gold 或运行覆盖。没有执行 exweb 或 Maven；测试库及本次临时工件已清理。

已确认的检查（选集重叠，不累加为独立用例数）：

- Native provider/配置专项 **50 passed**；随后纯语义与 DDD/Portal 边界 **260 passed**。application 取消/预留恢复专项最初 2 项错误地预期 `ValueError`，实际为专用 `ImageRevisionIntegrityError`；修正测试类型后 **6 passed**，没有放宽生产错误检查。
- 新 PG HTTP 专项首轮 **12 passed**（48.22 秒），`semantic-evaluations-api.log`，覆盖真实确认、并发去重、配置变化、ACL 撤回、结果回放、正文隔离及 Outbox 回滚。
- 实际 exweb/PG/MinIO、HTTP、语义与边界联合检查 **279 passed**（81.56 秒），`semantic-evaluations-exweb.log`；保留 Boto3/Python 3.9 弃用警告。
- 增加 repository 层确认 TTL、canonical payload、goal scope、running 状态复核后 **194 passed**（59.40 秒），`semantic-evaluations-final-guards.log`。随后工件读错误映射、未预留 FK、数据库降级保护及 TTL 专项 **8 passed**（19.93 秒），`semantic-evaluations-migration-guards.log`。
- Portal build/lint/i18n 通过，539 模块、主包 593.45 kB，保留已有 chunk 告警；`git diff --check` 通过。
- API/runtime、既有 references/决定/冻结和 Compose 回归 **188 passed**（235.27 秒），`semantic-evaluations-regression.log`；保留 LangGraph serde 警告。完整 E2E **27 passed**（4.1 分钟），`semantic-evaluations-e2e.log`，覆盖既有 exweb 深浅色/移动端流程，不是未交付的语义审阅 UI 验收。隔离 PG smoke **success**，`semantic-evaluations-smoke.log`。
- 最终代码已通过本机 `dev:foreground` 重新加载，迁移为 **0047_semantic_evaluations**；Portal/API/Runner 均为 200，`dev:status` ready，AgentGoal 与 ConversationTurn 的 workflow/activity 队列均有 poller。Docker 仍仅基础组件。Embedding/Rerank 的 development fallback 不计为语义能力验收。

后续确认/结果查看 UI 已在上节补齐；仍须交付语义接受/否定审阅、typed proposal/decision 和画像成员准入，而不是长期保留一个旁路评估库。完整 source/model-egress 策略、自主多项/多调用授权、累计费用、租约与取消恢复，结构/向量召回、authority/gold/readiness、P4/P5/P6 和完整 `verify:v1-release` 继续开放。

## 语义判定输入与结果准入（前置阶段，2026-09-17）

实际契约见[语义关联的固定证据输入与结果准入](./semantic-link-judgment.md)。本阶段新增内部 application/domain 模块，没有新增 HTTP/Tool ID、网络模型调用或语义数据库记录；不是完整 implements/asserts 功能上线。

- 从选定 image/hash、AC/规则和显式召回候选构建不可变证据包。code 与测试端点各固定 entity/document/source revision；通过既有归档查询核验完整分页及原文摘要，末尾再次检查来源权限。证据包上限 256 KiB，单跨度 64 KiB，超限要求减小显式选择，不静默截断。
- 明确区分代码原文与文档解析字段，保留双方摘要及字段序号。模型不能借 CSV 同一行其他列的 US 引用冒充 expected-result；中文/emoji 引用按 Unicode code point 定位，quote 摘要由服务器计算。
- 严格 JSON、全量主体、精确端点/修订/引用、asserts oracle、反证和 unknown 校验；拒绝重复 key、浮点/布尔偏移、伪造/跨候选/省略证据、模型自报 authority/status/概率。派生结果仅 `proposed / inferred`、待确认 source authority 与 null 概率，记录定位、证据充分性、版本兼容及 ambiguity，不代表正确实现或运行覆盖。
- 真实 PG/MinIO 的 exweb 验证读取 chatStream、独立 AC 和来源用例的证据。伴随 fixture 没有提供独立批准的具体 response content type，因此测试构造的响应保留 unknown；没有向外部模型发送仓库、执行目标代码或把该响应当作语义质量验收。报告增加 `semantic_link_inputs` 元信息。

已确认的阶段验证（选集有交集，不求和）：

- 初次收集遇到当前 Python 3.9 对 Pydantic union annotation 的限制，改为 `Optional` 后首批 **67 passed**。首轮真实归档/API 联合检查 **73 passed / 1 failed**，失败为测试误用 `ChatController.chatStream` 而真实显示名为 `chatStream (…/ChatController.java)`；改为确切符号/路径组合后 **74 passed**（42.43 秒），`semantic-link-inputs-exweb-fixed.log`。
- 纯输入/准入、查询/证据、DDD/Portal 边界首轮 **243 passed**（1.17 秒）；增加文档页完整性、同一原文行多字段、输入 envelope 预算及非法 Unicode 后 **249 passed**（1.47 秒）。
- 最终真实 PG/MinIO、召回 HTTP、语义输入/准入及分层联合复验 **256 passed**（47.50 秒），`semantic-link-inputs-final-guards.log`；其中新增语义专项单独复验 **73 passed**（0.15 秒）。保留 Boto3/Python 3.9 弃用提示。最终 exweb 候选 hash `sha256:dd59c4f0d49601e24f4e84f1202a7b877eed4b99c6fabdb1cf1ab9af829ff3f3`，两个通道各有 2 个验证跨度；结果明确 `unknown / proposed / pending_confirmation`、`external_model_called=false`。报告 ID 来自已清理的隔离测试库，不是开发库永久对象。
- API/runtime、既有 references 审阅/冻结及 Compose 回归 **188 passed**（222.64 秒），`semantic-link-inputs-regression.log`；保留 LangGraph serde 弃用提示。
- 完整 E2E **27 passed**（4.1 分钟），`semantic-link-inputs-e2e.log`，含固定 exweb 深浅色及移动端既有流程。这是兼容回归，不是尚未提供的语义 UI 验收。
- Portal build/lint/i18n、`git diff --check` 通过；539 模块、主包 593.45 kB，保留既有 500 kB chunk 告警。隔离 PG smoke **success**，`semantic-link-inputs-smoke.log`。

持久化模型出口授权、固定模型/预算的真实生成、语义 proposal/人工负向裁决及审阅冻结仍需继续实现，不能把读取 permission 当作 egress consent。完整 P0-P6、gold 和 `verify:v1-release` 尚未完成。服务保持前轮的本机 foreground 监督运行、Docker 仅基础组件；本次没有生产路由或迁移变更，未为纯新增内部模块重启应用。

## 固定 AC 的关联候选召回（2026-09-17）

实际契约见[关联候选召回](./semantic-link-recall.md)。这一步交付语义判定所需的固定输入调查能力，不把字面匹配改名为 implements/asserts 已接受关系，也不替代完整 P3。

- 新 `query.system_image.links.candidates` 经现有 ToolRuntime/RBAC/审计，以确切 image/AC 修订召回代码或有预期字段证据的测试用例。业务规则仅支持代码调查。默认 30、最大 100，输入/文档/证据/响应预算均有上限；缺预期结果的测试列为缺口，匹配不足不补造。
- 回执只保存固定 ID/hash/方法/选择；原文和名称不进入 Outbox 或默认 Planner。展开重新检查整个画像的来源权限、原文 hash 和结果摘要；历史文件改变/删除不改变回执。批量核验一次读取画像，每条证据仍校验当前权限与固定范围。
- Knowledge 的 AC/规则详情新增相关代码/测试按钮、召回范围与截断提示、双方原文分页。沿用原有深浅色/移动端/无可见滚动条，已检查浅色桌面、390px 手机和暗色桌面截图。
- 固定 exweb SHA `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 PG/MinIO 报告增加 `link_candidate_recall`。当前候选 hash `sha256:dfae08b25b477115dff5041949270ad3f362961c381c0ef220f3f0778b8fd7fe`，546 个代码成员/730 个总对象/4 个来源文档。代码通道因共同路径词匹配 546 项、返回 30 项并标截断，其中包含 ChatController；测试通道返回 1 个未执行 fixture 用例。概率为 null、authority 待确认，没有新增 assertion 或覆盖率。仍不执行目标代码/Maven。测试 UUID 属于已清理的隔离库，不是开发库永久业务对象。

已确认的阶段验证（选集有交集，不求和）：

- 首轮纯检查 **164 passed**。首轮 API/既有画像查询 **10 passed / 1 failed**，失败为测试使用旧对象类型名，修正后真实 PG/MinIO/Agent 联合检查 **37 passed**（51.32 秒），`link-candidates-exweb.log`。
- 新批量核验、领域/查询/Agent/receipt/架构检查 **198 passed**（1.49 秒）。最终 HTTP/历史重放/权限撤回/损坏/原文范围/真实 MinIO/分层联合检查 **215 passed**（96.32 秒），`link-candidates-final-guards.log`；保留 Boto3/Python 3.9 弃用提示。
- 扩大 API/runtime、文档/引用/审阅/冻结成员、查询/Agent 与 DDD/Portal/Compose 回归 **386 passed**（472.05 秒），`link-candidates-regression.log`，保留既有 LangGraph serde 弃用提示。此进程在批量核验优化前启动，该优化另由上述最终 215 项验证覆盖。
- 初次 exweb 浏览器专项因代码召回核验超过默认 5 秒而失败。消除逐条重复验证整份画像工件，并将有界来源调查的断言等待设为 30 秒；修正后专项 **2 passed**（1.8 分钟），`link-candidates-e2e-fixed.log`，真实按钮调用 canonical 工具并展开 fixture 预期原文。
- 最终完整 E2E **27 passed**（3.9 分钟），`link-candidates-e2e-full.log`；包含实际 exweb 的浅/深色代码召回、测试召回、body-free 回执、原文展开及移动端检查。
- Portal build/lint/i18n 通过；539 模块，主包 593.45 kB，仍有既有 500 kB chunk 告警。隔离 PG smoke **success**，`link-candidates-smoke.log`。
- 开发服务已重新以 `dev:foreground` 监督启动，仍是本机应用 + Docker PG/MinIO/Temporal。Portal/API/Runner HTTP 200，`dev:status` 全 ready，新 Worker 的 AgentGoal/ConversationTurn workflow/activity 队列均有近期 poller。本次未新增数据库迁移，仍为 0046。

完整 `verify:v1-release` 尚未运行。正式语义 candidate/authority/反证与审阅冻结、hybrid recall/gold 校准、P4 持续更新、P5 ContextPack 和完整 P0-P6 验收继续开放。

## AC 与业务规则来源实体（0046，2026-09-17）

实际契约见[验收条件与业务规则来源对象](./requirement-components.md)。本阶段补齐 P3 的独立来源实体基础，不批准规范、不增加已验证覆盖，也不建立另一套 quality_loop 需求主表。

- 明确标注的 AC/业务规则具有独立 Nasus 身份、修订、归档正文和证据；身份限定在父需求之下。续行与明确子标题保留原文范围，重复编号/无编号/父身份不唯一保留缺口，复合 CSV 不伪造语义拆分。现有单文件/批次对象预算包含子项。
- `0046_requirement_components` 以同项目/binding/source 修订复合 FK 固定父需求。子 payload 固定父 identity/payload hash 和字段索引；仓储重建校验，画像要求父成员闭包，查询重新验证父工件与当前来源权限。旧 v1 payload、画像、回执不修改；有子修订时降级被拒绝。
- Knowledge 文档检查增加来源需求、固定父修订与待确认状态。AC/业务规则使用可读名称，沿用原深浅色、移动端和隐藏滚动条。最终已查看浅色移动端及暗色桌面截图，调整元信息与正文的段间距。

本阶段证据（批次有交集，不求和）：

- 首批领域/查询/分层 **195 passed**（1.05 秒）；API/引用/冻结成员/PG 迁移往返 **23 passed**（75.37 秒），`requirement-components-api-first.log`。
- 新 HTTP/历史 v1 回执/父工件损坏与撤权/迁移降级保护等专项 **157 passed**（11.60 秒），`requirement-components-guards.log`。开发中遇到 Python 3.9 ORM union annotation 不支持和新测试 fixture 依赖未显式导入，均修正后重跑，没有跳过用例。
- 扩大 API/runtime、文档/画像/引用审阅/冻结成员/PG、Agent 回执、DDD/Portal 与 Compose 回归 **466 passed**（414.06 秒），`requirement-components-regression.log`；保留已有 LangGraph serde 弃用提示。运行后补充的画像读取端闭包保护由下述最终 PG/纯检查覆盖。
- 真实 exweb + PG/MinIO 初次回放 **1 passed**（8.36 秒）；最终同真实回放、领域/HTTP/迁移/回执/分层联合检查 **197 passed**（41.89 秒），`requirement-components-final-guards.log`。其后补充画像读取端父成员闭包负测，纯检查 **199 passed**（1.60 秒）。
- 固定 exweb 浏览器专项 **2 passed**（1.5 分钟），`requirement-components-e2e.log`；最终完整 E2E **27 passed**（3.7 分钟），`requirement-components-e2e-full.log`，包含四类文档成员、canonical document receipt、审阅冻结、深浅色与 390px 移动端检查。隔离 PostgreSQL smoke **success**，`requirement-components-smoke.log`。
- Portal build/lint/i18n、`git diff --check` 通过。536 模块、主包 587.03 kB，保留已有超过 500 kB 的 chunk 告警；真实 MinIO 测试保留 Boto3/Python 3.9 弃用提示。本阶段未运行完整 `verify:v1-release`。
- 开发服务已重启并迁移到 **0046_requirement_components**：Portal/API/Runner HTTP 200，`dev:status` 全 ready，新 Worker 在 AgentGoal 与 ConversationTurn 的 workflow/activity 队列均有近期 poller。应用仍运行本机，Docker 仅承载基础服务；Embedding/Rerank 仍为开发 fallback。

固定 exweb SHA 仍为 `fe5827f6b76f77ef34918d8b452ee823142332dc`。真实 MinIO 报告 `exweb-source-documents-report.json` 当前候选 hash 为 `sha256:6a0a36fa363f98fe31c632b5427bd94a3b1f56f277321e2a9b90bf693595cf3b`，包含 **546 个代码成员、四个文档成员、730 个总对象**；其中 AC 和规则都固定到同一确切父需求修订，原文行分别为 5 和 7。2012 条兼容关系仍为未批准推断，不冒充正式语义断言。后续 references 审阅子候选 hash 为 `sha256:93fc10d55da338f0812841640194208985fd91240d998ca9e63065a8ec8e09b8`。伴随 US/测试资料是明确的验证 fixture，非 exweb 作者规范；未运行 exweb/Maven/依赖脚本。报告 UUID 来自已清理的隔离测试库，不是开发库中的永久示例项目。

正式规范批准/authority、完整 BehaviorSpec 与多格式语义抽取、implements/asserts/exercises、五类 ContextPack、持续更新/官方版本治理及 P0-P6 其他缺口继续保持开放。独立 AC 来源对象不等于质量闭环验收完成。

## 固定审阅成员的子候选（0045，2026-09-17）

契约见 [固定审阅成员](./frozen-review-membership.md)。此阶段将 references 的 assertion/decision membership 写入真实 ImageRevision，不建立另一个游离的“已审阅快照”体系，也不批准发布。

- 新 canonical `system_image.revisions.freeze_links` 要求 reviewer、明确确认、父修订/hash、proposal/hash 和确切 decision IDs。复制父对象/证据，固定断言及具体决定；reject/defer 同样保留。PG 提交时复验 decision head，归档期间改判或撤权不提交新候选。原 invocation 已提交后重试可以恢复旧输出，不随后来决定改变。
- 新 `nasus.image-candidate.v2`、父修订外键和 `image_assertion_members` 追加式表；成员与 revision/Outbox 同事务，完整 PG/MinIO 摘要核验。v1 工件不迁移重写，v1 query receipt 保留旧 header hash 规则。`assertion_members` HTTP/canonical 查询和 Knowledge `Frozen reviews` 页签读取固定状态，不拼 latest review。
- 浏览器增加独立冻结确认和父修订 provenance，保留深浅色/移动端/无可见滚动条；已目视检查浅色移动端与暗色桌面截图。这里只包含 references 成员准入和自包含子候选，没有实现通用 overlay/tombstone、三方合并或 official head。

本阶段已完成的验证（选择集重叠，不相加为独立测试数）：

- 初批新 HTTP、既有审阅和 DDD/Portal 边界 **146 passed**，41.55 秒；`image-membership-first.log`。
- 领域、工件、v1 回执兼容和边界 **180 passed**，1.19 秒。
- 实际 exweb + PG/MinIO、HTTP、既有画像/Agent 回执专项 **27 passed**，76.26 秒；`image-membership-exweb-api.log`。固定提交、546 个代码成员与两份明确验证资料，形成一条 defer 成员；后来 reject 不改变原候选，提交后恢复返回同一候选。适配器测试仍使用明确 actor/confirmed invocation double，真实确认与权限另由 HTTP/E2E 验证；不执行目标仓库。
- 固定 exweb 浏览器专项 **2 passed**，包括拒绝后冻结、再暂缓、刷新后旧候选仍为拒绝，深浅色/移动端截图。`image-membership-e2e.log`。随后完整 E2E **27 passed**（3.5 分钟），`image-membership-e2e-full.log`；扩大 API/runtime/仓储/边界回归 **406 passed**（363.34 秒），`image-membership-regression.log`。
- 最终 PG/真实 MinIO/迁移往返/非法语义与重复端点/降级保护专项 **191 passed**（32.20 秒），`image-membership-final-guards.log`；之后中英文 Agent 工具发现及相关纯检查 **190 passed**（1.29 秒）。新工具仍要求 user_confirm，没有扩大既有 12 项 Planner 提示词预算或结构构建授权。验证批次有重叠，不求和。
- 最终真实 exweb 报告 `exweb-source-documents-report.json` 的 reviewed candidate hash 为 `sha256:8281d822cf01b3e5192745954961077b58316093392050ef9d5b212980f63099`，固定 546 个代码成员和一条 defer 断言/决定成员；后来的 reject 不回写它。报告中的 UUID 属于已清理的测试数据库，不冒充开发库现存演示项目。未运行 exweb/Maven/依赖脚本。
- Portal build/lint/i18n、`git diff --check` 均通过；536 模块，主包 585.39 kB，保留既有 500 kB chunk 告警。隔离 PG smoke **success**，`image-membership-smoke.log`。Python 3.9/Boto3 和 LangGraph serde 弃用提示保留。本阶段未运行完整 `verify:v1-release`。
- 最终代码加载后重新启动本机 `dev:foreground`，开发库迁移至 **0045_image_review_membership**。Portal/API/Runner 均返回 200，`dev:status` 全 ready；通过 DescribeTaskQueue 验证新 Worker 在 AgentGoal 和 ConversationTurn 队列的 workflow/activity poller 均活跃。Docker 仅承载 PG/MinIO/Temporal 等基础服务。Embedding/Rerank 仍为开发 fallback，不作为语义检索验收证据。

完整 P0-P6 尚未完成，顶部剩余范围继续有效；其中 references 的成员固定已交付，但不能推广为全部语义准入或版本治理完成。

## 引用审阅决定与界面（0044，2026-09-17）

实现契约见 [引用关联审阅](./reference-review-decisions.md)。此阶段推进 P3，不将接受引用等同于覆盖、业务 oracle 或正式画像。

- 增加 `system_image.links.review`，由 qa_lead 及以上项目角色经 canonical ToolRuntime 显式确认，固定候选/断言/证据摘要、策略和前次决定 ID。审阅人取当前认证主体；角色和来源权限在提交前重新验证。`accept / reject / defer` 均追加保存，修订变化不继承旧批准。
- `0044_link_decisions` 增加 PG 追加式决定链、复合 FK、首决定唯一、前驱唯一、序号唯一与 invocation 唯一；项目锁内 CAS，并发只能一个成功。决定与 metadata-only Outbox 同事务，失败回滚，降级迁移不能丢弃已保存决定。旧候选及 frozen image 内容/hash 不改写。
- 新增分页 HTTP 与 `query.system_image.links.decisions`。查询回执固定当时 head（包括空历史），后续决定不改写旧回执；展开重新授权。Planner 仍只接收无正文/理由的 metadata，新增审阅意图排序保持相关目录 12 项预算。
- Knowledge → Image revisions 可以选择/派生引用候选、查看 gap、读取双方归档证据、分页查看决定，并以理由和确认勾选提交。复用现有 light/dark/mobile 弹层及隐藏滚动条样式；数据读取留在 domain hooks，不让 route 直接操作 API。当前只适用于 references，不声称完整语义审阅 UI。

本轮已核实的验证（批次有重叠，不累计为独立测试数）：

- 首批 **147 passed / 1 failed**：测试把幂等键放入 input，而 Runtime 契约为请求顶层。修正新测试和新前端调用，并为共享 invokeTool 类型补顶层字段，没有放宽幂等断言。下一批 **164 passed / 1 failed**：新证据组件直接调用 API 违反前端分层门禁，已移动到 domain hook。后续纯测试、Agent 回执/相关工具发现及 DDD/Portal 边界 **156 passed**，1.39 秒。
- 最终新审阅 HTTP 与真实 exweb PG/MinIO 专项 **6 passed**，28.72 秒，`link-decisions-exweb-minio.log`。固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`、546 个代码成员与两份明确验证资料，在一条引用上记录 defer；同 invocation 回放不重复，重新派生不覆盖决定。报告 `exweb-source-documents-report.json` 的决定摘要 `sha256:a7d1d06cb0a245e3384c8c487ccecc3c232b13893ca18324f21c77ad78307058`。该 MinIO 适配器测试使用 actor/confirmed invocation double；真实 RBAC/确认另由 HTTP/E2E 验证，不执行目标仓库。
- 首轮 exweb 浏览器专项 **1 passed / 1 failed**：浅色场景在派生尚未完成时打开审阅，随后列表刷新卸载面板。派生期间现在隐藏可操作旧列表，直到写入与刷新结束。后续完整 E2E **27 passed**（4.0 分钟），最终固定 exweb 专项 **2 passed**（1.6 分钟）；`link-decisions-e2e.log`、`link-decisions-e2e-final.log`。扩大 API 回归 **368 passed**（422.70 秒），最终保护检查 **164 passed**（20.59 秒），纯检查 **159 passed**（1.55 秒），smoke success；日志 `link-decisions-final-api.log`、`link-decisions-final-guards.log`、`link-decisions-smoke.log`。
- Portal build/lint/i18n 通过，535 模块、主包 581.66 kB，保留既有 500 kB 告警；已查看暗色移动端审阅截图，历史与表单无横向溢出。`git diff --check` 通过。Boto3/Python 3.9 弃用提示保留。
- 通过原 foreground session 安全停止旧本机服务后重启，迁移至 **0044_link_decisions**，Portal/API/Runner/Worker 均由新 foreground 进程监督；`dev:status` 全部 ready。Docker 仍仅用于 PG/MinIO/Temporal 等基础组件。

完整 P0-P6 仍未完成：上述 reviewer 决定不是正式 assertion/decision membership 或发布，不替代 AC/规则修订、语义 links、持续演进、ContextPack、完整安全/恢复/性能门禁及业务试点。

## 固定画像的显式引用候选（0043，2026-09-17）

本阶段推进 P3 的确定性候选，不将 US 字符串引用改名成测试覆盖。实现说明见 [显式引用候选](./explicit-reference-candidates.md)。

- `system_image.links.propose_references` 经 canonical ToolRuntime/RBAC 读取整个固定画像的文档成员，只分析显式引用字段，并回读 MinIO 原文校验双方 Evidence。唯一目标生成 `references / observed / proposed`；缺失目标、跨 binding 重复 ID、主语身份歧义、自引用、缺证据生成 gap，不任取一个目标。不调用模型，不运行目标仓库。
- `0043_reference_links` 保存独立候选、关系与 invocation 绑定。双方 document revision 必须匹配冻结成员；项目/画像/报告采用复合 FK，证据在同一事务中核验成员归属。内容摘要幂等、PG 项目锁、追加式约束及同事务 Outbox 保留历史；需求修订变化产生新候选，不把旧决定或原文移到新端点。降级迁移遇到已存在的报告会拒绝丢弃。
- 新 HTTP 分页和 `query.system_image.references.read` 提供 assertions/gaps；工具回执只有不透明 ID、摘要与游标。展开时重新核验画像全部来源权限，Planner 仅收到重新授权的 metadata receipt。响应明确为 `not_in_image_membership`，旧 frozen image hash 和旧兼容关系均不改写。
- 预算为 1000 文档、10000 引用及 4 MiB 候选；64 KiB 查询页超限明确失败，不截断成“完整”结果。当前没有正式审阅决定、候选界面和 assertion membership，因此不能用于 approved oracle 或覆盖门禁。

已完成的验证批次（有重叠，不相加为独立用例总数）：

- 首轮 HTTP/文档/DDD **136 passed**，30.92 秒，`reference-links-api.log`。随后的扩大选集 **187 passed / 1 failed**：新工具挤掉了 Planner 12 项相关目录中的原文档查询工具。修复固定修订调查的排序优先级，不删断言、不扩大提示词预算。
- 修复后的 API/runtime、引用、文档、画像、Agent 查询、构建授权、PG 仓储和 DDD/Portal/Compose 选集 **372 passed**，265.46 秒，`reference-links-regression.log`；最终纯测试/相关工具发现/DDD/Portal **158 passed**，1.01 秒。覆盖事务失败回滚、端点 FK、禁止修改、来源撤权、写角色执行中撤销、缺失/歧义、旧画像回放及 no implicit model egress。较晚补充的报告 ID 一致性校验另由最终引用接口选集复验，不以早批日志单独证明最终代码。
- 最终引用 HTTP 与真实 exweb PG/MinIO 合并选集 **8 passed**，42.21 秒，`reference-links-exweb-minio.log`。固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`：728 对象候选含 546 个代码成员和 2 个文档成员，生成 1 条 `US-EXWEB-CHAT` 的 proposed references，0 个引用 gap。2008 条旧兼容关系仍是 inferred，不与新引用数量混淆。新报告摘要 `sha256:6cb95ca2bbe4dc5c65c619a44b87a23d1444e236c6095d581f5f73415a4b9106`，记录于 `exweb-source-documents-report.json`；隔离测试库与本次新写 MinIO 对象已清理，输入归档未改变。该适配器验证显式准备 running invocation/actor double，真实 RBAC/ToolRuntime 另由 HTTP 和浏览器覆盖，不宣称模型语义或目标业务运行验收。
- 完整隔离 PG Playwright **27 passed**，3.2 分钟，`reference-links-e2e.log`。启用固定 exweb，两个主题均核对干净工作树/HEAD，并通过真实 HTTP ToolRuntime 派生引用、展开不含正文的回执，再检查来源文档 light/dark/mobile 视图；这不是尚未实现的引用审阅 UI 验收。已查看最新浅色桌面与暗色移动端布局。未启用 exweb 的临时源码 fixture 在 afterEach 中清理，不删除真实仓库。
- Portal build/lint/i18n 通过（530 模块、主包 570.45 kB，保留既有 500 kB 告警）；隔离 PG smoke **success**，`reference-links-smoke.log`；`git diff --check` 通过。Boto3/Python 3.9 与 LangGraph serde 弃用警告仍在，未执行完整 `verify:v1-release`。
- 安全结束旧 foreground 监督进程后重启本机 Portal/API/Runner/Workflow Worker，应用迁移至 **0043_reference_links (head)**。`dev:status` 全部 ready，三个 HTTP 探针均为 200；运行中 OpenAPI 有 reference proposal 读取路径和展开页 schema，Tool Catalog 有两个引用工具及原文档工具。Temporal DescribeTaskQueue 进一步核对当前 worker PID 的最新 poller，AgentGoal 和 Conversation Turn 的 workflow/activity 四项都在轮询；不是只检查进程存在。PG/MinIO/Temporal 仍由 Docker 提供，模型路由仍是 development_fallback。

完整 P0-P6 仍未完成：一等 AC 修订、implements/asserts 等语义关联、人工负向决定、正式成员/发布、持续演进、五类 ContextPack 和真实业务试点不在本阶段冒充已交付。

## 需求与测试的不可变来源投影（0042，2026-09-17）

实现契约见 [需求与测试来源投影](./document-source-projections.md)。三源现在可以一起冻结并查看字段及原文证据，但尚不代表已经形成可审阅的正式语义关联。

- Markdown/text/CSV 抽取显式需求、用例和中英文字段；Python AST 定位测试函数，不执行脚本。无显式 ID 保留通用文档，重复 ID 全部标记 ambiguous，不按同名强行合并。复杂代码围栏与缩进代码中的示例不能成为需求或验收字段；缺预期、未知格式、失败或未分析文件都显式留痕。
- 迁移增加文档身份、文档修订、证据关联和逐文件抽取报告四个 PG 表；正文/报告在 MinIO。精确字段跨度、文件/snippet/payload hash 固定到 source revision，追加式约束和复合 FK 防止跨项目、跨修订拼接。登记记录与 Outbox 同事务，Outbox 失败不留下已提交的文档记录或新画像。
- 画像增加 `source_document` 成员，固定 document/source revision 和当次证据集合；仍完整验证全部候选输入权限。旧代码候选与持久化查询回执不额外序列化空 document 字段，保留历史 v1 hash。受限 Knowledge 视图只从授权文档的 canonical 源内字段重建，不复用带跨源关系名称的可变对象。
- 增加文档/抽取报告的分页 HTTP 查询与冻结画像内字段查询。`query.system_image.revisions.document` 沿用 canonical ToolInvocation、审计、幂等和 observation port；回执仅含 ID、摘要、证据与分页，原文不进入 SSE/审计或隐式发送给 Planner。展开时重新授权，读取后的 ACL 变化仍拒绝返回旧内容。
- Image revisions 的文档成员检查区显示字段、行号和缺口，可继续读归档证据；保留分页、无可见滚动条和 React 文本渲染，明确提示引用不是覆盖/验收。服务端按 64 KiB 字节预算自动缩小字段页，下一页继续返回完整字段；单字段采用 JSON 编码后大小限制，避免大量转义字符让已接受字段永远不可读。

验证事实（批次存在重叠，不累计为独立测试数）：

- 初轮选集出现 Python 测试脚本兼容性与旧 receipt 空字段形状的失败；已补静态脚本适配和兼容序列化。另一项失败来自测试按对象数量选中了旧候选，现按来源 manifest 精确选择，浏览器验证同步移除该猜测。
- 新 canonical 文档工具与 HTTP/Agent/回执专项 **22 passed**，44.16 秒，`source-documents-query-tools.log`；之后补充围栏与 Planner 文档回执负测的纯测试/DDD/Portal 边界 **166 passed**，1.42 秒。覆盖字段范围、修改正文/证据导致回执拒绝、撤权不读取工件、无隐式模型正文出口及历史回放。
- API/runtime、文档、画像、来源、构建计划/授权/结构、Agent 观察及 DDD/Portal/Compose 回归 **679 passed**，485.77 秒，`source-documents-regression-final.log`。该批启动后又补了围栏、来源过滤和长字段分页；最终代码的文档 HTTP/工具/Agent/来源视图及边界选集另跑 **187 passed**，53.67 秒，`source-documents-final-guards.log`，不把较早批次独自当作最终代码的完整证明。
- 真实 PostgreSQL + MinIO 的固定 exweb 三源验证 **1 passed**，6.18 秒，`source-documents-exweb-minio.log`。546 个代码成员及 2 个文档成员进入 728 对象的候选，需求 6 个去重证据范围、CSV 用例 1 个原始行范围，逐项核对归档/snippet 摘要。`exweb-source-documents-report.json` 记录候选和范围；临时对象已清理，原始 exweb 归档未改写。两份资料是显式验证 fixture，不是 exweb 作者需求或业务 gold；未执行目标仓库。
- 后续完整 Playwright 首次 27 passed，但截图检查发现两个 worker 争用全局 theme，名为 light 的截图实际是 dark，因此该结果不作为浅色证明。改为默认单 worker，各主题测试断言真实 DOM theme；标准 `npm run test:e2e` 改用隔离 PG，拒绝 SQLite 和非 `nasus_test_` 数据库。修复后 **27 passed**，3.3 分钟，`source-documents-e2e-serial.log`；已查看真正的浅色桌面和移动端截图。该批还没有 0043 引用工具断言。
- 0042 最终纯测试/DDD/Portal/测试入口约束 **183 passed**，1.84 秒；Portal build/lint/i18n 通过。隔离 PG smoke 日志已确认 `smoke: success`，`source-documents-smoke.log`。最终 exweb MinIO 复验 **1 passed**，4.78 秒，`source-documents-exweb-minio-final.log`。保留主包超过 500 kB 及 Python 3.9/Boto3 弃用提示。

开发数据库已于本轮通过 `dev:foreground` 迁移到 `0042_source_documents`。该阶段不是全 P0-P6 完成：AC/规则实体、typed link/负向裁决、官方 revision 发布、持续更新、五类 ContextPack、模型出口与业务 gold/真实受控运行仍为完整目标的待交付项。

## 持久化结构执行授权（0041，2026-09-17）

- 新增 `system_image.build.authorize`，必须作为现有 `system_image_build / system_image_investigation` AgentGoal 的显式步骤，并通过 canonical ToolInvocation 的用户确认。保存不可变授权：goal/conversation、plan/digest、manifest/hash、目标 baseline/version、确认人/时间及明确预算。不是创建第二套构建控制器，也不是用客户端传入的 confirmed 字段充当授权。
- `0041_build_authorizations` 新增 `image_build_authorizations` 和 `image_build_work_reservations`。同一个 goal 只能绑定一个授权；同一授权的一个 work item 只能被一个 invocation 预留。事务级项目锁、唯一约束及 append-only trigger 保证并发请求不能重复消费唯一尝试；授权/预留与各自不含源码的 Outbox 事件一起提交。
- Agent 的“authorize → structure”链路只需确认授权步骤。后续结构工具仍进入 ToolInvocationRuntime，重新检查 RBAC、来源权限、实际 goal/步骤、plan/target/version 和预算，再预留执行额度；不伪造 `confirmed_by_user`，不绕过 handler 或候选提交核验。失效/过期/耗尽授权拒绝当前 invocation，并将 goal 暂停为 `build_execution_authorization_review`；不回落成一次新确认以绕过已经批准的限制。重复 resume 不追加额度或重新执行。
- 目标基线当前关联的 version 与授权时不同，或者执行已被另一个 invocation 预留，均拒绝执行。额度一旦预留不自动返还；失败重试/追加额度需后续授权修订与 attempt 机制，本轮不伪装已经支持。已提交同 invocation 工件仍可恢复而不重抽取。
- 当前明确开放的 capability 只有 `immutable_structure_extraction`，对应 `structure` work item 一次、零模型调用、零模型费用；语义/模型出口、review report 与 publication 没有获批。授权计划禁止混入其他执行工具，并跳过模型 replanner。`max_tool_calls` 是授权 work item 的额度，不包括独立的计划读取和确认控制命令；当前时间限制为确认后的保守墙钟上限（包含暂停），不是完整的累计 active-time/费用账本。
- 已有 plan HTTP 详情增加 `execution_authorizations`：显示 goal/target/预算、已批准/已预留/未批准任务；原始 proposal 仍为不可变 draft，旧 receipt/digest 不改写。前端调查计划面板增加同样的只读授权记录，包含确认时间及使用前重新核验的说明，沿用既有深浅色与弹层滚动样式。完整 UI 构建引导接入、动态授权扩展、父修订/expected head、lease/fencing、即时 provider 取消和发布决策仍待完成。

本轮验证（选集有重叠，不累计为独立用例总数）：

- 首轮 **38 passed / 1 failed**：目标变更已被拦截，失败是断言未限定当前授权，误计入其他测试记录。修正测试作用域后，下一轮 **227 passed / 5 failed** 均来自独立 repository fixture 尚未应用新增 0041 表；补齐 fixture 的升级/降级验证，没有放宽业务校验。
- API/runtime/授权/计划/结构/Agent/DDD/Portal/Compose 回归选集 **407 passed**，309.19 秒，`build-authorization-final-api.log`。随后复验预算暂停与恢复逻辑的 API/Agent/边界选集 **207 passed**，84.91 秒，`build-authorization-review-api.log`。覆盖真实 PG 并发唯一预留、源 ACL 撤回导致事务回滚、预留后撤销写角色、目标版本变化、假 goal/确认、超额预算、LangGraph PG checkpoint 重建以及重放不重抽取。
- 最终授权/Agent/Runtime 纯测试及架构边界 **177 passed**，1.27 秒；包含提取期间超时的复核信号与零模型授权不调用 replanner。新增面板后的 Portal 边界另跑 **12 passed**；Portal build/lint/i18n 通过，528 模块，主包 566.80 kB，保留既有 500 kB 告警。
- 完整 Playwright **25 passed**，1.9 分钟，`build-authorization-e2e.log`。exweb 通过真实 HTTP 执行“读计划 → 确认授权 → 预留结构任务 → 候选审阅”，结构 invocation 不带伪造的 confirmed 标志。刷新页面后能查看 goal、固定 target、零模型预算与预留任务；已检查 `output/playwright/exweb-build-authorization.png`，布局与滚动正常。
- exweb 真实 PostgreSQL + MinIO **1 passed**，56.22 秒，`build-authorization-exweb-minio.log`。固定 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc`，候选 hash `sha256:370008ed1fb3c9dece6d908232a5e41976f805302e6f02f12644befa0126b489`，546 个代码成员，同调用不重抽取，publication blocked。报告 `identity-registry.json` 新增授权 digest、goal/target/预算/预留项。此适配器测试显式准备 canonical command/goal 行，真实确认/RBAC 由前述 HTTP/E2E 覆盖；CBM 使用已保存的真实 0.8.1 probe 回放，Tree-sitter 与 MinIO 重建本轮真实执行，不冒充本轮重新运行 CBM CLI。测试 schema 已清理，不是开发库里的业务对象。
- 隔离 PostgreSQL smoke **success**，`build-authorization-smoke.log`；`git diff --check` 通过。保留既有 LangGraph serde 与 Boto3/Python 3.9 弃用警告。
- 本机数据库已升级至 **0041_build_authorizations**；安全结束旧监督进程后，以 `npm run dev:foreground` 重启 Portal/API/Runner/Workflow Worker。`dev:status` 全部 ready，Portal `/build`、API `/readyz`、Runner `/readyz` 均为 200，运行中 OpenAPI 已包含 `execution_authorizations` 响应字段。PG/MinIO/Temporal 仍由 Docker 提供，业务测试未使用开发库。

本轮不执行 exweb、Maven 或目标依赖。以上仅推进 P2，不替代完整 P0-P6、生产发布或 `verify:v1-release` 总验收。

## 固定计划接入 AgentGoal（2026-09-17）

- 新增 `query.system_image.build_plans.read`，通过 ToolInvocation 返回固定 plan digest、manifest/hash 和 policy version 的 typed receipt。规划草稿工具推荐此读取工具，不再只给 Agent 一个无法展开的 ID。每次 Agent 展开都核验 invocation/request、项目权限、来源 ACL 和历史计划 hash；后续追加结构工件不改变旧 receipt。进入模型的观察仅包含来源 ID、任务依赖/能力、提议预算和 gap code，不隐式发送用户 objective、代码正文、文件路径或存储地址。
- 统一过滤 AgentGoal 添加的 `goal_template / goal_description / tool_plan_index / tool_plan_reason` 协调元数据，再执行工具的严格输入校验。实际 AgentGoal 可以完成“读计划 → 等待确认 → 从归档构建候选 → 等待候选审阅”，不是只在 UI 直接调用工具时可用。
- `image_plan_policy` 在初始编译、已持久化步骤执行和替换计划时防止固定输入退回旧的 source register/ingest、materialize、baseline initialize/promote。显式 project/plan/digest/manifest/target 与 goal target refs 必须一致；固定引用但没有显式工具步骤时拒绝使用可变状态编译器。该策略不等同于持久化 authorization envelope，不能据此宣称所有重规划范围已获授权。
- 固定构建目标不能仅因查完数据或 DAG 耗尽就进入 completed；进入 `build_completion_review`。已完成的结构任务继续保留 `structural_candidate_review`。单纯查看计划的 query goal 仍可完成，不将候选称为 official。完整 completion report 与审阅决策推进尚未实现。
- 进展判断纳入 typed receipt 的内容摘要哈希。相同摘要但不同画像页/原文行页可计为进展；相同结果即使换 invocation ID 也仍为重复。当前仍是相邻观察比较，不是完整历史 evidence-signature 去重账本。

本轮验证（选集有重叠，不作为项目总用例数相加）：

- 上次中断后的回归日志已核验完成：**360 passed**，235.99 秒，`agent-build-plan-regression.log`。包含真实 ToolRuntime、PostgreSQL、LangGraph PostgreSQL checkpoint 重新创建 gateway 后恢复、旧输入在工作区变化后的构建、重复 resume 不重复产出、源撤权、拒绝可变回退，以及既有 API/runtime/boundary/compose 合约。此批在最后的 receipt 进展判断补充前启动，不将它单独视为最终代码全量证明。
- 最新 Agent 观察、计划、预算、graph 与 DDD/Portal 边界单测：**164 passed**，1.31 秒。真实画像查询服务生成不同页 receipt，原文读取服务生成不同 excerpt receipt，再进入 graph 进展判断；不是仅比较两段文字。
- 最终代码的 Agent/计划/结构/画像查询 API、观察进展与架构边界选集：**202 passed**，98.00 秒，`agent-build-plan-final-check.log`。覆盖 PostgreSQL checkpoint、实际 Actor/ToolRuntime 与固定候选构建；保留既有 LangGraph serde 弃用警告。
- exweb 与计划面板定向浏览器验证：**3 passed**，44.1 秒，`agent-build-plan-exweb-e2e.log`。exweb 实际通过 HTTP 创建两步 AgentGoal，确认后以固定 manifest 生成 546 个代码成员的 candidate，读取恢复后的 goal 仍为候选审阅状态。已检查 `output/playwright/exweb-structure-build.png`，沿用原有弹层视觉与滚动布局。后续完整 Playwright **25 passed**，1.9 分钟，`agent-build-plan-e2e-full.log`，包含同一 exweb 链路和既有 dark/light/mobile 基础回归。
- exweb 真实 PostgreSQL + MinIO 归档回放：**1 passed**，62.04 秒，`agent-build-plan-exweb-minio.log`。固定仓库 commit `fe5827f6b76f77ef34918d8b452ee823142332dc`；`identity-registry.json` 新增 `investigation_plan_query`，证明工件提交后旧 receipt 不变及撤权拒绝展开。本次候选 hash 为 `sha256:ca03ef0b1471dd78169a58278651471533dda38f7e2dd62b20820771f183c498`，保持 546 个代码成员、同调用免重抽取与 publication blocked。UUID 属于已清理的隔离 schema，不能拿作开发库业务对象。
- Portal build/lint 通过，527 个模块，主包 564.44 kB；保留既有超过 500 kB 的拆包警告。
- 隔离 PostgreSQL smoke：**success**，`agent-build-plan-smoke.log`；`git diff --check` 通过。开发服务已以 foreground 监督方式恢复，Portal/API/Runner 分别返回 200，Worker、PG、MinIO、Temporal 与 PG checkpoint 均就绪。

本轮没有执行 exweb/Maven/目标依赖，未增加 ORM 到领域层，也未新增第二套 Agent 控制器。完整 P0-P6、全计划授权和费用账本、work lease/fencing、动态调查、文档/用例语义关联、目标修订 CAS 与正式审批仍保持未完成；上述门禁不替代完整 `verify:v1-release`。

## 已确认的固定输入结构任务（0040）

- 新增 canonical 工具 `system_image.build.structure`。显式输入 `project_id / plan_id / plan_digest / target_baseline_id`，沿用 RBAC 和 `user_confirm`；客户端伪造 `confirmed_by_user` 不会跳过确认。仅执行计划中 `structure` work item，零模型调用、不运行仓库、不写兼容画像投影、不推进来源或正式画像 head。
- `StructureBuildApplicationService` 读取计划指定的 SourceManifest，经现有不可变来源恢复/抽取/候选归档端口生成工件。历史 manifest 不会被当前 head 替换；旧 `system_image.context.materialize` 仍保留原有 head 校验。所选代码必须全部 captured；缺失或失败的可选文档/用例仍固定在清单中且保留 gap，不补造内容，也不阻断代码结构候选。
- `image_structure_build_artifacts` 为追加式 PostgreSQL 表，关联实际 ToolInvocation、plan digest、目标基线/版本、executor version、确认时间和 ImageRevision。候选、membership、调用关联、工件和脱敏 Outbox 同事务；已有调用工件优先读取，不重复抽取。目标必须是同项目现存基线，不因名为 official 就赋予发布权。新计划策略 v2 指向新工具并标记 requires_confirmation；v1 草稿及其原 hash 继续可读，不原地重写历史。
- 提交持有来源项目 advisory lock，并检查/锁定运行中的已确认 invocation、目标项目/基线及可选 version/AgentGoal。来源授权和时间预算在各阶段及事务提交前复查；解析过程中取消后不提交新候选，原文归档可能留下未引用内容寻址对象。已有候选不会因后续失败删除。当前时间上限从确认时计算，是保守墙钟上限，不是完整累计主动时间账本。
- 前端领域 Hook 承载命令调用，route 仅渲染“选目标 → 准备 → 确认”。计划详情返回最近 20 个来源受控的结构工件；刷新后仍可见候选引用。继续沿用深浅色、移动端、焦点管理和隐藏滚动条，不把单项完成显示成整个计划完成或正式发布。
- **仍未完成**：本次确认不是整个自主计划的 authorization envelope；不含目标 official image head CAS、全计划费用/重试账本、worker lease/fencing、运行中 provider 立即终止、动态任务/replan、正式三源语义关联及发布审批。当前 ToolRuntime 的整体终态并发写入与 ACL/成员资格强 fencing 也未由本次单项提交锁替代，仍纳入 P2/P6。

验证记录（各批存在重叠，不相加为项目总用例数）：

- API、runtime config、结构构建、计划、画像、ToolRuntime、DDD/Portal boundary 和 Docker 契约选集：**388 passed**，258.04 秒；`.nasus/validation/structure-build-final-regression.log`。保留既有 LangGraph serde 弃用警告。
- 最终领域执行规则、v1/v2 草稿兼容、结构 API、PG 计划工件及边界补充校验：**191 passed**，22.44 秒；`structure-build-final-guards.log`。覆盖字段/目标串改、可选输入失败、取消/过期提交、事务回滚、恢复不重新解析、不可变关联等；不代表 provider 即时取消或完整 lease fencing 已验收。
- Portal build/lint/i18n 与 `git diff --check` 通过。527 个模块，主包 564.44 kB，保留既有超过 500 kB 的拆包警告。
- 完整 Playwright：**25 passed**，1.5 分钟；`structure-build-e2e-final.log`。包含真实 exweb 浏览器构建、light/dark/mobile、固定输入、刷新保留工件与确认状态、来源撤权后隐藏内容。已目视检查 `output/playwright/exweb-structure-build.png` 与移动端截图。
- 隔离数据库 smoke：**success**；`structure-build-smoke.log`。开发进程已重启，迁移为 `0040_structure_build_artifacts`，Portal/API/Runner 均返回 200，Worker 与 PG/MinIO/Temporal/checkpoint 就绪。

exweb 实际恢复 MinIO 归档生成 546 个代码成员并验证同调用不重新解析，未运行 exweb/Maven/依赖脚本。最终真实 PG + MinIO 回放 **1 passed**（61.00 秒），日志 `structure-build-exweb-final.log`；`identity-registry.json` 的 `confirmed_structural_work` 记录候选 hash、来源清单和无重抽取恢复证据。保留 Boto3 对 Python 3.9 的弃用警告。这些证据仅覆盖已交付链路，完整 P0-P6 目标仍保持开放；本轮未运行完整 `verify:v1-release`。

## 来源固定的调查计划草稿（0039，初始交付）

- `system_image.build.plan` 通过现有 ToolInvocationRuntime 创建草稿；角色至少为 tester，读取要求当前项目成员和所有输入来源可见。工具输入显式指定项目、SourceManifest、目标、模式、用途与预算。严格字段/数值校验，未知授权字段不能进入计划；代码缺失阻断结构要求，可选需求/测试缺失分别记录业务验收/测试复用缺口，不冒充完整三源关联。
- 领域对象记录来源清单及 hash、问题/原因、依赖 DAG、建议能力/工具、输出类型、验收条件、失败动作和预算建议。计划不调用 LLM、不执行目标代码、不自动确认权限，也不创建第二套 Agent 控制器。`guided`、`draft`、`not_granted` 和 `execution_ready=false` 是当前草稿契约，不是完整自主构建状态机。现有物化工具会重采当前输入，必须先接入固定输入执行器，不能直接将草稿中的建议工具当作已经绑定的执行步骤。
- PostgreSQL `image_build_plans` 与 `image_build_plan_invocations` 为追加式记录。相同项目/计划 hash 幂等复用；不同调用各有实际 ToolInvocation 外键。项目锁防止并发重复提交，计划、关联和不含目标文本/源码的 Outbox 同事务保存。运行中的调用必须匹配项目；带会话/goal 时进一步验证对应业务记录的项目/会话。读回校验完整 payload hash 和来源 membership，拒绝损坏、越界或伪造的授权状态；单份草稿上限 64 KiB。
- 历史清单可以用于提出新草稿；不会用当前 head 覆盖旧输入。执行前的 expected image head、完整授权 envelope、ACL 变更与提交之间的强 fencing、工件重试/取消仍需后续生命周期实现，不能把本次事务内权限复查称作完整并发授权隔离。
- `GET /v1/projects/{project_id}/system-image/build-plans` 与 `.../{plan_id}` 每次重新检查授权，返回 `private, no-store`。列表在 SQL 分页前排除含隐藏来源的整个计划；返回最小摘要，不在列表暴露目标文本。没有独立 HTTP 写旁路，工具结果只提供 `build_plan:<id>` 引用和需要审阅的提示，不把未实施的执行工具推荐为下一步。
- Knowledge 新增 `Investigation plans`：初始列表，点击 `Propose investigation` 后填写目标、模式、用途、调用/时间及可选费用预算，保存后查看固定输入、任务、验收条件及缺口。表单保留打开时的 manifest ID，不跟随后台刷新悄悄替换输入。所有写操作仍走 ToolInvocation，正文为 React 文本；读取失败后隐藏旧内容，沿用现有深浅色、对话框尺寸、键盘焦点和无滚动条滚动。当前是草稿创建/检查界面，不等同完整初始化向导或正式发布审批界面。
- **完整目标未收缩**：调查计划 revision、accepted gaps、AgentGoal/目标 baseline/version/expected_head 绑定、管理员费用/出口授权、动态调查分支、工件/租约、停止/恢复及批准发布仍待实现；三源语义、持续更新与五类 ContextPack 仍属于 P3-P6 的必交范围。既有四步兼容构建暂未替换为此草稿执行，不宣称自主构建已完成。

验证记录（选择集存在重叠，不相加为独立用例总数）：

- API 主流程、runtime config、计划/画像接口、Agent 计划策略、ToolRuntime 与 DDD/Portal/Docker 契约的完整选定回归最终为 366 passed（343.24 秒），日志 `.nasus/validation/build-plans-regression-final.log`。前一轮 361 passed / 1 项工具拒绝契约断言失败，修正后全量复跑通过；没有跳过该用例或放宽业务权限断言。
- 领域/PG/HTTP/DDD/Portal 边界最终专项 176 passed（25.11 秒），日志 `.nasus/validation/build-plans-final-guards.log`。覆盖严格预算、依赖/工具/来源范围、不可变记录、迁移往返、并发幂等、Outbox/授权失败回滚、损坏拒绝、历史输入、来源分页过滤及 viewer 写拒绝。早期测试发现并修正读取权限异常误转 400；另一项测试将正式工具拒绝错误期待为 HTTP 403，现按现有 HTTP 200 + failed/authorization_denied 审计契约验证，并检查数据库无新增，不改变运行时拒绝行为。
- 完整浏览器回归 25 passed（1.3 分钟），日志 `build-plans-e2e-final.log`；smoke success，日志 `build-plans-smoke.log`，均位于 `.nasus/validation/`。包含深浅色、移动端、文字注入只作文本、费用输入、真实 ToolInvocation 保存、重开读取及撤权隐藏；没有旁路伪造成功响应。
- exweb 固定 SHA 的浏览器实测从真实采集/静态候选创建计划，校验来源 manifest 和 source revision，输出 `output/playwright/exweb-build-plan.png`。真实 PG 独立 schema + MinIO 原文回放最终复验 1 passed（48.92 秒），日志 `build-plans-exweb-final.log`，报告 `identity-registry.json` 新增 `investigation_draft` 的固定输入与撤权验证。浏览器临时对象存储不冒充 MinIO；不执行 exweb、Maven、hook 或目标依赖。
- Portal build、lint、i18n 和 diff 检查通过；保留已有约 559 KiB 主 chunk 告警及 Python 3.9/Boto3、LangGraph 弃用提示。2026-09-14 开发进程按 `dev:foreground` 重启后，Portal/API/Runner 均为 200，新路由与计划 schema 在运行中的 OpenAPI 可见。尚未执行完整 `verify:v1-release`，不将专项通过视为全部 P0-P6 完成。

## 冻结的静态画像候选（0038）

- 新增 `image_revisions`、`image_object_members`、`image_revision_invocations`，以项目、来源 manifest 和产物哈希标识候选。对象逐项固定 hash；有规范代码身份的对象固定 entity/source revision 与当次 evidence IDs。之后新增的证据不会自动进入旧候选，重新冻结产生另一候选。三个表拒绝 UPDATE/DELETE，复合 FK 防止跨项目、跨 manifest、错误实体修订组合；额外插入导致的 membership hash 不一致在读取时拒绝。
- `ImageCandidatePreparation` 只读取固定 SourceManifest 对应的 PG 记录和归档原文，不从工作区的当前来源字段拼装历史输入。静态解析、身份/报告登记和候选归档在保留调用上下文的线程中运行，不占用 HTTP 事件循环，也不在线程内修改兼容工作区。正式生命周期、取消、预算与跨进程租约仍属于 P2，不以线程卸载替代 Temporal/AgentGoal 设计。
- MinIO/S3 按项目命名空间和内容 hash 保存 canonical JSON，固定来源组合、对象及闭合关系集合；单份上限 16 MiB。写后回读校验；读时验证存储 namespace、完整字节 hash、schema、manifest hash、对象与成员对应关系及数量，而不只检查请求的页。`freshness` 是可变展示字段，不进入冻结对象。
- 候选提交与 invocation 关联及 `system_image.candidate.frozen` Outbox 在同一 PG 事务。使用来源捕获相同的项目 advisory lock，在提交时检查原 manifest 仍为输入 head；在异步准备结束、应用兼容投影前再次检查 manifest 和 baseline。来源变化不恢复旧 snapshot 覆盖新输入。相同输入和相同输出的重试复用候选，可追加另一 invocation 关联。
- 生产入口仍为 `system_image.context.materialize` / `system_image.baseline.initialize`，由 ToolInvocationRuntime 进入。ToolResult 增加不透明 `image_revision:<id>` 引用。候选在后续 embedding/retrieval 之前提交；后续失败时候选和真实 invocation 关联保留，但旧兼容投影按原失败恢复逻辑处理。这不是完整质量上下文已构建的成功标记，也不是跨 S3/PG 的分布式事务；无引用工件 GC、全流程并发 fencing/崩溃恢复仍待完成。
- 新增只读 `GET /v1/projects/{project_id}/system-image/revisions` 与 `.../revisions/{image_revision_id}`。列表按 ID cursor；详情按 `objects / relationships / members / source_members` 分页，最多 100 条且 64 KiB。查询只接受固定 revision ID，不通过“最新对象”拼装历史。所有输入来源必须可见，SQL 在分页前排除包含隐藏来源的整个候选，读存储前后重验来源权限。均为 `private, no-store`，不向响应暴露候选存储地址。
- **能力与切换边界**：本轮冻结的是兼容抽取器的静态结构产物，schema 为 `nasus.image-candidate.v1`。无规范身份的对象标为 `legacy_observation`；推断关系、旧 `Official` 展示标签和 confidence 均不是 approved assertions/oracles。状态只允许 `candidate`，明确返回 `publication=blocked_pending_revision_governance`。没有实现正式 head、parent/overlay/tombstone、审批/CAS、readiness 或五类 ContextPack；旧 V1 基线 API 也没有因此升级成新发布治理。旧源无法证明 captured 时不补造候选，旧投影仍为兼容路径。候选修订的前端历史检查和 canonical 查询工具见后续章节；Agent 自主调查仍待完成。
- exweb 固定 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc` 已经真实解析/归档/分页回放：726 个静态对象、1,944 条关系，其中 546 个代码对象固定实体修订和真实 MinIO 证据；其余 180 个对象为非批准观察，不算语义覆盖率。三源关联、人工 gold、真实目标运行与 P2-P6 全部退出条件仍是完整目标。

验证记录（测试选择集可能重叠，不累加为独立用例总数）：

- 初始候选领域/PG/HTTP 专项 22 passed；增加双源 ACL、失败工件、迁移往返及异步准备后，专项和 DDD/Portal 边界 166 passed。真实项目 RBAC 由 HTTP fixture 覆盖，PG fixture 的空证据不冒充已归档原文。
- 真实 exweb + MinIO + PostgreSQL 独立 schema：1 passed，40.84 秒。日志 `.nasus/validation/image-candidates-exweb-minio.log`；`identity-registry.json` 增加 `frozen_image_candidate` 校验结果。包括全部四类分页回放、重复冻结幂等、546 个固定证据成员和撤权后拒绝读取；不执行 exweb、Maven 或仓库 hook。
- 首轮并行运行多个大型验证任务时，API 选择集 341 passed / 3 次等待超时，E2E 15 passed / 2 failed。三个 API 失败用例单独重跑全部通过，未放宽断言。浏览器暴露静态物化阻塞注册请求的问题后，新增不可变输入准备服务并移出事件循环。最终串行 API 347 passed（208.37 秒），最后输入清单保护补测 169 passed；完整 E2E 含 exweb 17 passed（1.2 分钟），smoke success。日志分别为 `image-candidates-regression-final.log`、`image-candidates-final-guards.log`、`image-candidates-e2e-final.log`、`image-candidates-smoke.log`，均在 `.nasus/validation/`。2026-09-10 开发库已迁移至 0038，服务重启后健康检查通过；不将历史运行状态当作当前服务在线证明。

## 候选修订检查与固定证据展开

- Knowledge 新增 `Image revisions` 只读入口。用户显式选择候选，按对象、成员、关系、输入来源分页；展示冻结时间、manifest、artifact/membership hash。对象行与同修订的成员页按 hash、数量和有序 ID 验证对应，不从当前 workspace 或 alias 列表补历史证据。没有新增写入口，既有 ToolInvocation 写链保持不变。
- 候选页面明确显示“未审批”，不将旧 `Official`、confidence 或推断关系作为已确认业务规则。历史证据列表只含该次冻结的 evidence IDs，旧候选不会因后续注册证据而改变。新增 `GET .../revisions/{image_revision_id}/objects/{object_id}/evidence/{evidence_id}`，先验证完整候选及对象成员，再委派已有受控原文读取端口；返回前复核全部输入来源 scope、证据 ID、source revision 和 binding。任一输入不可见都拒绝整个候选的证据展开。
- 查询携带取消信号、`no-store`、零保留缓存和独立打开会话标识；翻页/重验时隐藏旧内容，任一次读取失败后隐藏整个修订面板内容，必须手动重载后重新选择。关闭、刷新和跨项目导航不自动恢复旧敏感内容。沿用当前 dialog 的深浅色 token、键盘关闭/焦点返回和无滚动条滚动；原文只作为文本渲染。
- 首轮接口专项暴露 `StaleSourceAccessScope` 被通用行号错误误捕获的问题，已修正为交给来源权限处理；修正后的接口专项 15 passed。浏览器首轮 exweb、历史及两类撤权通过，两项布局测试因测试 locator 错误超时，修正相对定位后 5 项页面测试全部通过（22.0 秒），未放宽等待或业务断言。完整浏览器回归随后暴露同名构造器选择、末尾空源码行比较、StrictMode 第二次请求绕过迟到响应拦截三个测试问题；分别改为显式 CodeClass 类型、保留固定行范围和拦截全部对应请求。页面同步展示对象类型，不混淆同名对象。
- 最终 API/领域/PG/接口/边界选择集 351 passed（257.90 秒），完整 E2E 23 passed（1.2 分钟），smoke success；Portal build、lint、i18n 和 diff 检查通过。日志为 `.nasus/validation/image-inspector-regression.log`、`image-inspector-e2e-verified.log`、`image-inspector-smoke.log`。真实 exweb + PG/MinIO 1 passed（51.59 秒），三个 CodeClass 的修订成员证据通过受控入口展开，撤权后均拒绝；日志 `image-inspector-exweb-minio.log`。保留已有 LangGraph/Python 3.9 弃用提示和前端 chunk 大小告警，未执行最终全量 `verify:v1-release`，不将这些选择集当作全目标完成证明。
- exweb 页面以固定提交为输入，生产采集/静态解析/冻结接口生成 726 个对象、546 个代码实体和 1,944 条关系；实际在新面板展开 `interfaces/chat/ChatController.java:20-45`，与归档固定 source revision 一致。截图 `output/playwright/exweb-image-revision-evidence.png`。浏览器夹具使用隔离 PG 与临时对象存储；真实 MinIO 校验单独运行，不把浏览器临时存储冒充 MinIO。
- 此切片没有完成正式批准版本选择、三源语义审阅、修订差异/合并、来源权限管理入口、Agent 调查/取消或下游 ContextPack。完整 P0-P6 范围仍按顶部阶段表继续实现。

## Canonical 候选修订查询工具

- 新增 `query.system_image.revisions.list/read/evidence`，exact handler 优先于旧通用 query 摘要。三个入口均通过 ToolInvocationRuntime 的 RBAC、幂等、审计、事件链，application port 委派现有冻结修订查询，不直接访问 ORM 或供应商图数据库。
- 严格输入固定 project/image revision、对象与 evidence ID；分页仅接受整数且有界，拒绝文件路径、provider ID 冒充成员、未知参数和跨项目会话。evidence 只接受该次冻结 membership 中的证据，不改用当前 alias 列表。
- `ToolResult.image_query` 是 `nasus.image-query.v1` receipt，仅持久化查询参数、不透明 ID、结果 hash、固定来源修订和分页信息，不保存对象描述、路径或源码。成员页保留该次固定的 entity/source/evidence IDs，供后续精确证据查询；receipt 单独限制为 64 KiB。空列表和末页不推荐无效的后续查询。`GET /v1/tool-invocations/{id}/image-query` 每次重新授权、读取归档并核对整个结果摘要；响应 `private, no-store`。列表回放检查原先选中的修订，不重新执行 mutable list，也不自动补入后续候选。
- Agent 现有 replanner observation port 接入新的 receipt：使用前重新验证完整来源 scope 和工件，失败不把内容交给模型。暂时只向 planner 提供 receipt，不隐式发送原文；这不是完成了模型出口授权或可执行的 InvestigationPlan。正式上下文编译、受控内容进入模型、预算/租约、动态缺口调查、发布治理仍按 P2-P6 实施。
- 初始专项 135 passed / 2 failed：新测试未给查询绑定会话，却要求会话 Outbox；另一个跨项目展开已正确返回 403，测试却期待未完成状态的 409。修正夹具会话与错误优先级断言后 139 passed（26.62 秒）。未通过放宽授权或删除审计断言来绕过失败。
- API/运行配置/领域/PG/接口/DDD/Portal/Docker 兼容选择集 357 passed（350.96 秒），日志 `.nasus/validation/image-query-tools-regression.log`。其后补充固定成员句柄、receipt 大小限制及画像页错误分类，最终接口/receipt/Agent/边界专项 167 passed（58.43 秒），日志 `image-query-tools-final-guards.log`。这些选择集有重叠，不累加为独立用例总数。
- 完整 E2E 23 passed（1.1 分钟），日志 `image-query-tools-e2e.log`；exweb 用例在真实 ToolInvocation 链中查询/展开候选列表、对象页、固定成员及 ChatController 原文，再与浏览器面板核对。截图 `output/playwright/exweb-image-revision-evidence.png` 已人工查看。smoke success，日志 `image-query-tools-smoke.log`；Portal build、lint、i18n 均通过。
- 最终真实 exweb + PG/MinIO 1 passed（59.53 秒），日志 `image-query-tools-exweb-final.log`。固定 SHA `fe5827f6b76f77ef34918d8b452ee823142332dc`，139 页候选数据经新 application port 的 receipt 与展开比对；726 个对象、546 个代码成员、1,944 条关系保持一致，三个指定 CodeClass 的证据 receipt 原文回放及撤权拒绝通过。`identity-registry.json` 增加 `canonical_query_pages_verified`、`canonical_evidence_receipts_verified` 和每个指定类的 `tool_receipt`。不将浏览器临时对象存储冒充 MinIO，不将独立 schema 当作开发库项目，也不执行目标仓库代码。
- 2026-09-14 安全结束旧前台监督进程后，使用 `npm run dev:foreground` 重新启动；本机 Portal/API/Runner/Worker 与 PG/MinIO/Temporal 依赖均 ready，三个 HTTP 检查均 200，OpenAPI 的新 observation 路径和三种响应 DTO 已核验。数据库仍为 0038，无新增迁移。模型路由为 development fallback；保留已有 Python 3.9 弃用与前端大 chunk 告警。完整 `verify:v1-release`、真实模型调查及 P0-P6 退出条件仍未全部执行或完成。

## 原文采集 inventory（0036）

- `SourceTreeScanner` 在原文采集时生成有界、按相对路径排序的观察记录，区分 `included / enumerated / excluded / unsupported / failed`。纳入的原文件记录大小与 SHA-256；空目录也留痕。二进制文件的原字节可以被纳入，但不能据此宣称解析器支持该格式。
- 排除项在来源根目录内部计算，修复了祖先目录名为 `build/dist` 时错误排除整个绑定的问题。排除目录只记录为剪枝边界，不扫描其后代，也不编造被排除的文件数量。来源可批准范围的结构/语言解析 inventory 仍待实现。
- 文件数、总字节、单文件字节、目录深度、记录数及元数据大小均有限制。记录数默认 20,000（`NASUS_SOURCE_MAX_INVENTORY_ENTRIES`），最大 50,000，元数据估算硬上限 8 MiB，目录深度 128。超过任何限制都会留下失败原因；枚举被截断时 `enumeration_complete=false`，不能参与完整差异或删除推断。
- 父目录与后代通过已经打开的目录描述符读取，禁止跟随符号链接；特殊文件不打开。读取前后检查文件身份/大小/时间元数据，目录枚举异常、权限错误、路径替换、非法路径均显式失败。该采集账本不是可变本地文件系统的全局原子快照，也不是解析成功、业务语义完整或发布就绪证明。
- `0036_source_inventories` 新增不可变 `source_acquisition_inventories`：按项目/绑定保存 MinIO 报告引用与哈希、扫描状态和计数。同一绑定/报告重复登记幂等，报告与 receipt Outbox 同 PG 事务；数据库拒绝 UPDATE/DELETE。SSE 仅包含不透明记录 ID，不包含文件路径、源正文或存储地址。
- `system_image.sources.ingest` 仍由 ToolInvocationRuntime 进入 application service，成功与失败扫描均登记报告。失败扫描不生成 SourceRevision；旧成功修订和历史 SourceManifest 不改写。v2 成功 manifest 中的纳入文件必须与 inventory 一致，并固定同一报告哈希，重放时再次验证。旧 v1 继续可读，但不证明有完整扫描清单。
- **状态边界**：inventory 的 `complete` 仅表示此次原字节读取和枚举完成，不表示文件已全部写入对象存储，更不表示画像完成。之后归档失败时仍可保存已完成的扫描报告，但不产生成功快照/修订。MinIO 写入与 PG 不假定分布式事务；无 PG 引用对象的延迟 GC 仍属于 P6。授权拒绝、连接器失败等发生在扫描之前时，不伪造逐路径 inventory。
- 采集报告仍供受控后端与验证工具使用，尚未开放采集报告 HTTP/前端入口。下节新增的是逐文件解析/结构报告查询，不是采集失败报告的替代入口；完整结构 inventory、取消与 tracked-ref 增量/删除判断仍未交付，不能用采集级清单替代完整 P1/P2/P4 验收。

## 解析与结构观察 inventory（0037）

- `CodeFileAnalysis` 分开记录 `parsed / unsupported / failed`，保留语言、解析器/grammar 版本、规则和错误原因。报告以已经验证的原文 manifest 为全集，没有进入文本解析的文件仍记录为 `not_analyzed`，不得隐式视为成功。旧 provider 没有诊断时标记 `provider_not_reported`；旧 v1 原文仍可分析，但 `raw_inventory_available=false`，不补造历史采集证明。
- Tree-sitter 文件级暂存成功后才合入候选图；语法树有错误或读取时发生有损 UTF-8 解码时，不生成该文件正式符号。原始 bytes 仍保留在 MinIO，非 UTF-8 的支持属于待实现的显式 decoder，不以替换字符后的代码冒充原文。主解析失败时不继续调用 CBM，保证 required enhancer 的失败不会遮盖已经获得的逐文件诊断；合并器和代码注册器也拒绝重新引入失败文件。
- `CodeStructureFact` 当前包含文件模块、包声明以及 Java/Spring 白名单注解观察：service、应用入口、Controller 路由、事件监听、Repository/Entity/Mapper 边界、测试注解。这里的 `module` 是文件模块，包声明计数不等于独立包数量；数据库边界不代表已经解析 SQL 或验证数据库行为。配置文件名、测试文件名匹配仅为 `path_hint`，不冒充语义解析。
- Java 路由由 AST 与明确 import/FQN 解析，不再从注释/字符串正则制造路由。类级路径与方法级路径组合，支持静态 path/value 数组、无路径的 marker annotation 和显式 HTTP method。方法条件按 Spring 的并集规则组合（[Spring 6.1 API](https://docs.spring.io/spring-framework/docs/6.1.18/javadoc-api/org/springframework/web/servlet/mvc/condition/RequestMethodsRequestCondition.html)）；多 wildcard import、同名本地类型、动态表达式、冲突注解、通配前缀等不强行推断。保留方法 locator 与 Controller/类级 mapping 支持位置，固定文件 hash 和片段 hash。
- **能力边界**：这些是静态观察，不是 approved 业务行为、完整可达路由表或运行验收。自定义/meta annotation、继承 Controller、函数式 WebSocket、完整配置条件/媒体类型/安全过滤链以及其他语言的框架结构仍未覆盖。既有非 Java 路由 regex 尚未全面迁移，不把它们列为本轮精确结构报告成果。Annotation 规则也不等价于完整 Java 类型检查或编译。
- `0037_code_analysis` 新增 PG JSONB `source_code_analyses`，以 project/binding/SourceRevision 复合 FK 固定输入，`report_hash` 固定内容；相同修订/报告幂等，不同解析结果并存，数据库拒绝 UPDATE/DELETE。报告与只含不透明 ID 的 Outbox 事件同事务。原始源码仍在 MinIO，报告不是 CBM 缓存，也不是正式 ImageRevision。
- 生产接入仍经 `system_image.context.materialize` ToolInvocation。报告先独立提交，再检查解析失败；失败会阻止本批物化和失败代码登记，但诊断报告保留，旧报告/原文/已登记修订不改写。多源调查、部分成功的 review 状态与正式发布仍需接入 P2/P4，不把当前兼容物化状态当作完整自主构建实现。
- 新增只读 `GET /v1/projects/{project_id}/system-image/source-analyses` 和 `.../source-analyses/{analysis_id}`，必须携带 `source_revision_id`。列表按 ID cursor 分页，详情按 immutable report 的 `files/facts` offset 分页，单页最多 100 条且 64 KiB；单份持久化报告上限 16 MiB。列表不读取文件/事实正文，详情重验 report hash。来源授权先于 SQL 查询，并在返回前重验项目成员与 ACL fingerprint；策略变化 409、来源/成员拒绝 403、错误修订或项目 404，成功响应 `private, no-store`。不返回对象存储 URL 或源文件正文。
- 新报告 HTTP 已具备真实权限测试；**尚未新增前端报告面板和 Agent 结构调查工具**。不能因此声明 P1/P2 可见成果已经全部交付，也未开放来源 ACL 管理写入口。

### exweb 结构样例

- 使用固定提交 `fe5827f6b76f77ef34918d8b452ee823142332dc`，仅静态 fetch/归档/索引，不运行 Maven、目标应用或仓库脚本。
- 原文 126 文件 / 180,868 bytes 全部有解析状态：120 个 Java 文件 parsed，6 个 unsupported（README/设计 Markdown、XML、YAML、SQL、无后缀文件），0 failed。unsupported 不是没有内容，也不代表文档/配置已经理解。
- 272 条结构观察：120 文件模块、120 包声明、13 路由、8 service、8 数据库边界、1 应用入口、2 配置 path hint。没有事件/测试观察不等于已经证明系统无事件或测试。
- `tests/fixtures/system-image/exweb-controller-routes.json` 固定 6 个 Controller 的 13 个 HTTP method/path/行号和类级支持位置。该样例由本轮逐项检查源码得到，范围仅注解入口；不冒充双人业务标注、全语言 gold 或完整运行入口。WebSocket 函数式注册明确排除且仍待支持。
- 本轮产物独立保存到 `.nasus/validation/system-image-structure/reports/f2b0904fe8a9fa56eeed/fe5827f6b76f77ef34918d8b452ee823142332dc/`：`probe.json`、`normalized-graph.json`、`code-analysis.json`、`identity-registry.json`。没有覆盖之前 v1 和采集 inventory 验证目录。
- 解析报告 hash `sha256:97db70cdd1fa80612d0000aaa55b2b365430208c70e8c8c17e332b1b1e5a1f2a`；真实 MinIO 原文重建、PG 幂等登记、所有 files/facts 分页和 snippet hash 检查通过。结构查询撤权后拒绝，已有 546 条代码 Evidence 回读仍通过；本轮合并图 951 实体与 546 已登记身份，旧版本计数保留在各自报告，不作为质量提升百分比。

### 本轮验证

- 新报告 PostgreSQL/HTTP/AST 专项：23 passed，`.nasus/validation/code-analysis-pg-r3.log`。覆盖失败报告保留、历史固定、不可变/FK/Outbox、权限与读中撤权、内容篡改、响应上限。初跑发现 Python 3.9 的反射类型兼容问题，以及新错误映射把权限错误转成 400，均已修正，未放宽权限断言。
- 解析/身份/DDD/Portal 选择集 191 passed；最后补充有损解码与 required enhancer 的失败保留后，相关单元与边界选择集 164 passed，日志分别 `code-analysis-boundaries.log`、`code-analysis-final-unit.log`。计数有重叠，不累加为独立测试数。
- exweb 固定提交 + 实际 MinIO/PG schema 回放 1 passed，最终代码再次回放 1 passed，日志 `.nasus/validation/code-analysis-exweb-replay.log`、`code-analysis-exweb-final.log`；保留 Python 3.9/Boto3 弃用提示。schema 中的 UUID 仅属于隔离验证，不导入开发项目。
- Portal build/lint 通过，保留既存 >500 KiB chunk 警告。独立 PG 的现有 E2E 11 passed（39.3s）、smoke success，日志 `code-analysis-e2e.log`、`code-analysis-smoke.log`。本轮没有新增前端界面，不把回归通过冒充报告 UI 验收。
- 较大范围 API/运行配置/多源/权限/容器契约回归 190 passed（215.96s），`.nasus/validation/code-analysis-api-regression.log`，保留 LangGraph serializer 弃用提示。最终补充 decoder 与 enhancer 失败处理后，PG/HTTP/解析/身份/采集专项 34 passed，`.nasus/validation/code-analysis-focused-final.log`；包含跨项目读取拒绝和多结果列表 cursor。完整 `verify:v1-release`、完整 provider gold、ImageRevision 治理、自主调查和 P2-P6 全链路仍未验收。
- 本机 `dev:foreground` 已重载，数据库 head 为 `0037_code_analysis`；运行中的 OpenAPI 包含两个 source-analyses 只读接口，Portal/API/Runner 返回 200，Worker 与外部依赖 ready。Docker 仍只负责基础组件，没有把测试项目或 restricted policy 写入开发业务库；没有提交或推送代码。

## 来源受控解析报告界面

- 知识页新增“解析报告”入口，先显式选择可访问的源码修订，再选择不可变报告，不自动把最近报告当成已批准画像。无报告、解析失败、unsupported、未分析及空筛选均有明确状态；语法通过和静态注解观察不冒充业务正确性或运行验收。
- 新 `GET /v1/projects/{project_id}/system-image/code-source-revisions` 使用调用者当前来源范围在 PG 排序与分页之前过滤，仅返回允许的文件/仓库末级名称、修订与采集元数据，不返回凭据、父目录或归档地址。分页默认 20，最大 100；按采集时间和修订 ID 确定顺序，游标也必须属于当前授权范围。查询之后再次核验 scope epoch。
- 报告详情增加 files/status 与 facts/kind 过滤，先校验不可变报告哈希，再对过滤后的集合计算页边界和总数。页面每页 25 条，协议最多 100 条且限制 64 KiB；错误过滤、越界和完整性失败不静默返回成功空页。
- UI 查询由 `domains/system-image` 管理；结果列表消费路由展示模型，不直接依赖供应商或 API DTO。原文衍生名称、路径及哈希只作为 React 文本展示，不运行 HTML，也不翻译原始标识与哈希。详细规则、控制器/类映射支持行号、片段与报告哈希可展开检查。
- 报告无持久缓存；切换项目、关闭、刷新或主动重载不恢复旧选择。任一读取失败即隐藏旧列表和修订选择，权限恢复也不自动重开旧报告。原生 dialog 支持 ESC/关闭后恢复焦点；共享现有深浅色 token，窄屏保留上下滚动但不显示滚动条。截图检查后压缩顶部说明，将完整修订 ID 收入溯源详情，避免首条结果被元数据挤出桌面首屏。
- 边界：这不是完整 SourceManifest/ImageRevision 浏览器、构建引导、语义审阅或权限管理界面。解析报告依旧由正式 ToolRuntime 的 context materialization 生成；失败报告可检查，但不将失败物化发布为成功画像。

2026-09-10 本轮验证（选择集重叠，不累加为独立用例数）：

- PG/HTTP 修订选择与报告专项 12 passed，`.nasus/validation/analysis-ui-api.log`。覆盖过滤前授权、隐藏来源不占可见页、私有游标拒绝、读取中撤权、报告筛选及旧契约兼容。
- 较大范围 API、运行配置、报告仓储与 Docker 契约回归 182 passed，`.nasus/validation/analysis-ui-api-regression.log`；保留现有 LangGraph serializer 提示。没有使用开发业务库或 SQLite，不等于所有 API tests 或 V1 验收。
- 专项浏览器 6 passed，`.nasus/validation/analysis-ui-e2e-r3.log`：真实 HTTP/PG/ToolRuntime 采集、按修订选择报告、过滤与分页、失败解析不覆盖历史、HTML 字面量不执行、深浅色/390px、实际来源和项目撤权后 403 与正文清除。最初两轮分别修正了测试对原生选择框及分页按钮名称的错误定位；没有修改接口响应或放宽权限断言。
- 隔离 PostgreSQL 的完整浏览器回归 17 passed，`.nasus/validation/analysis-ui-e2e-final.log`；另补充了移动端实际滚动和切换空项目/返回原项目不复用旧报告的检查。独立 PG smoke success，`.nasus/validation/analysis-ui-smoke.log`。最终展示模型分层调整后，全部 6 项报告专项再次通过（33.3s，`analysis-ui-e2e-presenter-final.log`）；DDD/Portal 边界 136 passed（`analysis-ui-boundaries-presenter-final.log`），增加结果列表禁止直接导入领域/传输契约的检查。
- exweb 浏览器测试显式设置 `EXWEB_FIXTURE_ROOT`，验证工作树洁净、HEAD 为 `fe5827f6b76f77ef34918d8b452ee823142332dc` 后，通过真实 ToolRuntime 只读采集本地固定源码。UI 展示 126 个原文件、120 parsed/6 unsupported，13 条 Spring 注解路由逐条匹配人工回读的控制器、类映射及方法行号。浏览器测试使用隔离 PG 和测试对象存储，不冒充 Git 拉取或 MinIO E2E；未设置该变量时此测试明确 opt-in 跳过。
- 同一 exweb 的实际 MinIO/PG 身份、原文、结构与 ACL 回放另行 1 passed（30.70s），`.nasus/validation/analysis-ui-exweb-minio.log`，继续验证 546 条精确证据和 13 条注解路由。未运行目标应用、Maven 或仓库 hook，仍不是完整框架入口、语义 gold 或目标业务运行验收。
- Portal build/lint/i18n 通过；既存约 533 KiB 主包告警保留。截图位于 `output/playwright/analysis-{light,dark}.png`、对应 `-mobile.png`、`-mobile-observations.png` 和 `exweb-analysis.png`。源码修订选择、分析报告选择与布局只读化没有新增写动作旁路。
- 开发进程已通过 `dev:foreground` 重载，运行中的 OpenAPI 包含修订列表和两个报告接口；Portal/API/Runner 均返回 200，Worker 与全部依赖 ready。PG 仍为 0037，Docker 仅负责基础组件；模型仍为 development fallback，未宣称真实模型语义闭环已经通过。完整 P0-P6 目标继续保持未完成。

## 代码身份影子注册（0032）

- `CodeSymbolKey` 是同一 binding 内的匹配键，不是业务 ID。包含大小写敏感的相对路径、语言、类型、嵌套作用域和参数签名，不含 provider、绝对 checkout 路径、行号、源修订。Java 参数变量重命名、代码体或行号变化不会改变已验证签名键；跨文件移动/重命名暂不自动承诺身份连续。
- 继续复用现有 Tree-sitter 做语法元数据校验，CBM 通过防腐适配器映射，不使用它的 qualified-name 命名规则充当业务身份。重复定义及其子作用域、无法区分的同一行重载、缺失精确定位的重载都保留 ambiguous/unresolved，不强行合并。
- 修复原合并器忽略大小写、按同名近似行号合并、供应商节点 ID 冲突可能改写主图边的问题。同一行的多个声明不再相互覆盖。纯名称调用解析不再从多个同名目标中任取第一个。
- `location_precision` 与 `identity_status` 独立：匹配键唯一不代表供应商位置精确；合并近似证据不会降级主解析器的精确 locator。近似位置不生成精确片段 hash。
- `0032_code_entity_registry` 新增 `code_entity_identities`、`code_entity_revisions`、`code_entity_provider_bindings`。UUID 身份、绑定到 SourceRevision 的修订与旧 `CTX-*` 映射追加式持久化；项目/来源复合 FK、PG advisory lock、不可变触发器、同事务 Outbox。相同来源/内容重复抽取幂等，provider 替换不改变可唯一匹配的 UUID。
- 正式 ToolRuntime 的 `system_image.context.materialize` 已接入影子写入；前端及旧知识对象 ID **尚未切换**。未归档旧源、无法唯一匹配的节点不伪造正式身份。独立代码 Evidence 的增量实现见下节，不以观察 payload 自身充当授权原文证明。
- `extraction_digest` 用来区分本轮适配器结果，不冒充完整 provider index generation 生命周期；invocation/goal provenance、ACL 撤销、historical alias backfill、切换审计仍待后续实现。

## 代码证据与检查入口（0033 / 0034）

- `0033_source_evidence` 添加不可变 `source_evidence`、`code_entity_evidence`。代码身份修订、证据、映射及 Outbox 在同一 PG 事务追加；覆盖回滚、重复登记、跨项目 FK、禁止 UPDATE/DELETE 的测试。
- `nasus.code-entity-observation.v2` 固定 UTF-8 replacement + LF 行坐标，不把字符串中的 Unicode 分隔符算作源码换行。v1 观察不改写；近似 locator 不生成精确片段哈希。供应商唯一名称与位置可信度分别校验：与同源语法范围不一致时保留 disputed/approximate，不伪造精确原文。
- `GET /v1/projects/{project_id}/system-image/evidence` 必须指定 `source_revision_id`、`object_id`，可再指定 `entity_revision_id` 精确筛选。详情通过 `/evidence/{evidence_id}` 读取，分页最多 200 行且不超过 64 KiB，不切断 UTF-8 或源码行。
- 原文每次从受限项目/来源命名空间的归档读取，校验固定 manifest、文件和完整片段哈希，不信任可变 checkout 或旧本地缓存；DTO 不暴露对象存储地址。项目成员权限在读取前后重新校验，撤销测试包括读取进行中。缺失、近似、损坏、不可用分别明确失败；权限拒绝保持 403，不被通用 ValueError 转为 400。
- `0034_knowledge_code_reference` 为旧知识对象投影添加可空引用，保存 entity/source revision pin。已有对象保留 null，不从当前 head 猜测历史修订；新物化对象通过 PG 持久化引用，仍保留旧 CTX ID 兼容。
- 前端知识卡片的“查看证据”提供固定修订、行号、分页及哈希详情；原文作为 React 文本而非 HTML/Markdown 执行。近似/未登记对象明确显示缺口。正文不持久缓存；读取或翻页失败后隐藏旧正文；关闭/ESC 恢复焦点。桌面、390px 移动端和 light/dark 使用同一组件与 token。
- **尚未完成**：来源级 ACL/epoch、文档/测试/运行 Evidence、旧对象回填、画像修订及审阅批准。Agent 查询 Tool 的新增实现见下节，不能据此宣称自主调查已完成。当前项目权限不是完整来源访问策略，浏览器也不能撤回用户已复制的原文。

## Canonical 证据查询工具

- 新增 `query.system_image.evidence.list/read`，exact handler 优先于通用 query 摘要 handler；不调用 LLM，不修改源事实，沿用 ToolInvocationRuntime 的权限、幂等、审计与事件持久化。
- 严格输入要求显式项目/来源修订；拒绝未知文件路径字段、布尔值/浮点数/字符串数字页参数。read 的证据与来源修订不匹配时在访问归档前失败；list 可指定实体修订。同一项目会话不能承载另一个项目的证据，即使发起人同时有两个项目的权限。
- `ToolResult.evidence_query` 保存版本化 receipt。源码正文和对象存储地址不进入结果、审计或 SSE；只保留证据 ID、定位、分页、哈希。失败信息不复制供应商/存储异常的原始文本。
- `ToolEvidenceObservationApplicationService.expand` 和对应只读 HTTP 入口每次重新授权并读取归档，重新校验 receipt 的元数据与片段哈希，拒绝损坏、撤权和跨项目展开。读取前后的授权保留，阻塞存储 IO 在异步工具 handler 中交由保留请求 actor context 的线程执行。
- Agent 的系统画像上下文现在为新对象提供 source/entity revision pin；旧无 pin 对象不猜测 head。Agent observe 节点将实际 invocation ID 传给 replanner，replanner 通过授权 describe 端口读取 receipt，不再只有摘要文本。证据元数据明确视为不可信数据，不是批准后的业务 oracle。
- 原文展开 application port 已可供后续调查 use case 使用，但没有在来源/模型出口策略尚不完整时自动把源码发送给 replanner。自动语义调查、模型出口授权、预算和工作工件仍保留在 P1/P2/P3 交付范围。
- 修复 ToolRuntime 幂等命中时绕过当前授权的问题：正常重复请求仍返回原调用；成员被撤销后拒绝重放，不修改历史结果。

## 来源权限与只读检索基础（0035）

- 领域策略区分 `project` 与 `restricted`，显式 reader 必须同时具有当前项目成员资格；项目/平台管理员保留管理读取权。角色由项目授权 application port 提供，不接收请求中的角色声明。未知 binding、空来源链和不完整派生来源不能作为授权依据。
- `0035_source_access` 添加项目 ACL epoch、追加式 policy revision、可变 policy head。PostgreSQL advisory transaction lock + expected epoch CAS 防止并发覆盖；策略、head、epoch 和脱敏 Outbox 在同一事务提交。策略历史禁止 UPDATE/DELETE，epoch 禁止删除和倒退；复合 FK 限制跨项目/来源引用。
- 一条 SQL 读取 epoch、全部已登记 binding 与策略 head，避免多个 SELECT 混用不同版本。只读 scope fingerprint 包含当前 actor/有效角色、epoch、binding 映射与策略；新增来源即使没有策略更新，也会使旧 fingerprint 失效。`require_current` 再查项目成员身份及当前 scope，不把缓存或历史 context 当永久授权。
- 原文 Evidence 服务现在必须注入来源授权端口，没有省略参数即绕过的默认路径。list 在按 alias 查找前后验证固定 SourceRevision 的来源访问权；read 在 MinIO IO 前后检查 binding 权限。Agent 的历史 receipt describe/expand 同样重新授权；无权返回明确拒绝，不返回文件路径或源码正文。
- `AuthorizedRetrievalSubjects` 只编译完整且所有来源均可读的候选。pgvector 与 FTS 适配器可接收该作用域，在排序和 limit **之前**用 SQL 排除候选；按 chunk/object/source 的实际引用优先级过滤，防止受限 chunk 借用同一行的公开 source_ref 绕过。空授权候选返回空集，项目不匹配拒绝查询。
- **接入边界**：生产 `SQLAlchemySystemImageRetriever`、Agent 画像上下文、画像 GET 和知识列表/详情已接入来源读取投影，具体实现及临时限制见下节。项目/workspace/portfolio 查询、写动作响应、历史 ToolInvocation/SSE、组合/跨项目记忆仍需完整派生来源、revision membership 和重新授权，不能宣称全部读取已隔离。不得在可变 workspace 上过滤再整批写回，否则可能误删不可见数据。
- 策略 repository 的写端口当前仅用于内部测试，没有注册生产 API、Tool Catalog 或前端设置入口，也未修改开发项目的实际权限。所有读路径接齐后，权限管理必须接入正式 ToolInvocationRuntime、管理员/读者成员校验和治理，不能直接暴露 repository 方法。模型出口许可、失效传播、缓存与旧事实全面隔离仍属于 P1/P2/P6 目标。

## 来源受控检索与 Agent 上下文

- `SQLAlchemySourceReadProjection` 对数据库快照创建独立只读副本，不修改 materialization workspace。受限项目只保留可读 raw asset/chunk；代码对象必须通过 PG 不可变实体修订与 alias 的项目/来源联合映射，且匹配 entity/source revision pin。名称和路径由源内 symbol 重建，不沿用可能含跨源内容的可变 name/evidence/relations。
- 正式 `SQLAlchemySystemImageRetriever` 必须注入来源授权服务。可读 chunk/source 集合在 pgvector/FTS 排序和 limit 之前过滤；旧对象 embedding 含关系名称，缺少完整派生来源时排除。重排只接收过滤后的候选，异常适配器返回集合外引用时拒绝。权限在 embedding/rerank 等待期间变化时，中止本次读取，不发布旧结果。
- Agent 的直接画像读取改为 `SystemImageContextReadPort`，由独立 PG reader 实现，application 层不再读取可变 workspace。上下文文本和长期引用列表均重新授权；受限项目不返回未证明来源的基线统计、指标、历史会话摘要/引用、长期记忆和运行/版本摘要，文本中明确标示 withheld。当前已授权的源内代码和固定证据引用仍可用。
- 查询语句生成前的 scope 贯穿 Agent 与检索 adapter；生成后再次检查，并在检索的 embedding/rerank 调用前核验 expected scope，避免权限收紧后将旧历史拼成的 query 发送给检索模型。兼容 lexical adapter 无法重新授权时明确拒绝携带 scope 的调用，不忽略该参数。生产 adapter 即使没有 caller scope，也会自行获取当前权限。Context 返回之后、最终 Chat/Planner 调用之前的出口授权尚需携带 scope 的 ContextPack 契约，不能把本次检索检查当成完整出口许可。
- `/v1/agent-memory/context` 返回 `private, no-store`；读取期间权限变化返回 `409 source_scope_changed`，不返回部分旧上下文。实际成员撤销在快照读取前后检查。旧共享 retrieval trace 在受限项目暂不写入，避免通过尚未隔离的 trace 查询泄露引用。
- **临时兼容策略，不是最终完成定义**：没有 restricted policy 的项目仍保留旧 V1 投影，但读取前后校验当前成员和完整 scope。上述 withheld/不写旧 trace 仅防止缺少证明的旧数据继续流出；必须补齐每条派生事实/记忆/trace 的完整来源和 ImageRevision membership，再恢复按权限使用，而不是永久关闭历史记忆或退回无语义检索。画像构建本身的模型出口、其余 API/SSE、跨项目历史仍未全部接齐，因此来源权限管理入口仍不开放。

## 来源受控画像与知识查询

- `SystemImageReadPort` 是独立只读 application port；`SQLAlchemySystemImageSnapshotReader` 对 PG 快照做副本投影，画像 query 不再依赖可变 operations/workspace。知识列表和详情通过同一 snapshot use case 读取，不再绕回原 workspace；DDD 边界检查固定依赖方向。
- `/v1/projects/{id}/system-image`、`/knowledge`、`/knowledge/{object_id}` 均在读取前后校验当前来源 scope，成功响应 `private, no-store`。读取期间策略变更返回 409，成员撤销返回 403；不可见知识详情返回 404，不携带旧对象。未受限项目的旧响应保持兼容。
- 受限画像增加 `visibility.mode=source_filtered` 和 `withheld_sections`。项目只保留 id/name/code，整体进度等派生字段为 null；`build_state.status=visibility_limited` 且 stage_index 为 null，不用 0 或“完成”伪造整体状态。关系、指标、基线等无完整来源证明的数据暂不返回；raw asset/chunk 去掉归档地址、凭据、invocation 和不明派生元数据。Evidence 原文仍走单独、每次重新授权的接口。
- 知识页和项目总览明确标示受限视图，区分可见对象数量与未知关系/指标；不展示完整构建阶段。读取失败后隐藏旧知识卡片和证据弹窗，权限恢复不会自动重新打开旧弹窗。共用统计卡和提示组件，保留深浅色 token 与无横向溢出的手机布局。
- `knowledge_status_summary/system_image_status_summary` 的新摘要不再附加未证明来源的旧长期记忆。此改动不等于历史 ToolResult/SSE 已隔离，也不证明摘要返回后到最终模型调用之间的出口已授权。
- **仍是渐进兼容层**：来源绑定编辑在受限视图中暂不展示，后台构建和其他项目入口未因此全部隔离。需要完成派生事实来源、ImageRevision membership、其余 API/历史及模型出口接入后，再开放正式权限管理和受限多源编辑。不能把暂时 withheld 当成永久删除知识或最终设计。

## exweb 真实验证

- 授权仓库：`https://github.com/kunben-duck/exweb.git`。
- 固定提交：`fe5827f6b76f77ef34918d8b452ee823142332dc`。
- 实际链路：Git 捕获 -> MinIO 原文件/manifest -> 哈希校验恢复 -> CBM CLI -> Nasus 规范化图。
- 126 个文本文件、180,868 字节，764 个实体、1,912 条规范化关系；507 个实体补取有效行号，257 个仍为 approximate（248 个 module、9 个 route）。这不是经 gold 标注证明的全局定位准确率。
- 已人工回读并核对 `ChatController` 类 20-45 行；另两个类的供应商定位为 `DocumentUploadController` 20-41、`ToolGatewayApplicationService` 25-60，三者通过 probe 的精确定位检查。
- Provider `codebase-memory-mcp 0.8.1`；launcher SHA-256 `825debfb83b2055888d3fbd1ff7be79169be30fd39c33e1e0485370f71e125bb`，不代表已固定所有传递运行资产。
- MinIO manifest SHA-256：`1b31965ff31703b7019194ec5f6639b33879f5db65d7798b58982ec63b2c2f8a`。
- 生成报告：`.nasus/validation/system-image/reports/f2b0904fe8a9fa56eeed/fe5827f6b76f77ef34918d8b452ee823142332dc/probe.json`，同目录保留规范化图。
- 仅验证结构集成，未宣称业务画像、三源语义关联、Agent 自主闭环或目标应用运行验收通过；没有启动 exweb 应用或运行 Maven。
- 新一轮真实 CLI/MinIO probe：764 个 CBM 节点中 538 个获得规范化匹配键，226 个 unresolved；这与 507 个精确位置是两个不同维度，不将任一个比例当作 gold 准确率。
- 将相同 MinIO 快照恢复后，在独立 PostgreSQL schema 中登记 Tree-sitter 与 CBM 结果：Tree-sitter 546 个可登记身份，CBM 538 个，重合符号复用 UUID，重复登记不新增修订；三处控制器/服务示例均通过。报告 `identity-registry.json` 与 `probe.json` 同目录，测试 UUID 不写入开发业务库，schema 验证后删除。
- 新报告在同一真实 MinIO 快照上逐条回读 546 条已注册精确证据，文件/片段哈希一致；三个示例类的原文声明和行号均通过。语法范围交叉校验后 CBM 仍有 507 个 exact、0 个已匹配符号的 disputed locator。该结果是归档/定位回放，不是全局语义 gold、来源 ACL 或业务正确性验证。
- 0035 增量报告增加 `source_access_checks`：上述三个真实类均验证无来源权限时在 MinIO 读取前拒绝、授权 reader 可重新读取、撤销后旧 receipt 不可展开，旧 scope 被判失效。使用实际 PG 策略和真实 MinIO 原文，项目 actor 是明确的测试替身；真实账号/项目成员与 HTTP 权限由独立 API 测试覆盖，不把这份报告冒充完整 ACL/业务验收。
- 2026-09-10 回放增加 `source_context_checks`：相同源下 546 个登记对象均从 PG 修订重建为可读上下文，无来源权限时为 0；固定引用保留，故意污染的旧派生标签被排除，原 DTO 未被改写。该回放使用真实 MinIO/PG 身份与策略，输入 DTO 和项目 actor 明确为测试替身，不是完整 Agent 自主构建或语义 gold 验收。真实账号、HTTP 和模型输入过滤由上下文专项测试另行覆盖。
- 同日增加 `source_image_query_checks`：通过画像与知识 application query 回放 546/0 授权对象，列表、详情及固定实体修订一致；来源撤销后详情不可读取；整体统计为未知且归档地址不公开。保持真实 MinIO/PG 身份/策略与明确的 DTO/项目 actor 替身边界；原 DTO 未被改写，不将本次查询回放冒充完整 exweb 自主业务画像验收。

## 已执行测试

### 2026-09-10 采集 inventory 增量

- 扫描/原文快照/Git 适配器专项：43 passed；覆盖排除边界、二进制原字节、祖先目录名称、权限失败、特殊文件、符号链接替换、读取时修改、非法路径、目录枚举错误、深度/数量/字节限制、归档失败以及 v1/v2 重放。S3 SDK 写异常归一化为安全失败，已读完但未归档成功的扫描不会变成 SourceRevision；报告本身未写成功时不伪造 durable artifact。
- 新报告 repository / ToolRuntime / 多源 / 快照 PG 专项：11 passed，使用一次性 PG 数据库及独立 schema；验证报告不可变、幂等、Outbox 失败回滚、失败扫描不生成成功修订、旧修订仍可回读。
- API/runtime config/inventory/多源/来源受控画像与 Evidence/Docker contract 广覆盖回归：206 passed（`source-inventory-api-final.log`）。随后 S3 SDK 失败补丁的 repository/多源/真实 ToolRuntime 补测 5 passed（`source-inventory-pg-final.log`），验证来源与调用结果均不泄露原始存储错误。
- DDD/Portal 边界：135 passed；Portal build/lint 通过，构建仍有现存约 519 kB 主包告警。隔离 PG 的全量浏览器回归 11 passed，smoke success。日志前缀 `.nasus/validation/source-inventory-*`，未将测试项目写入开发业务库。
- 新 exweb CLI probe 使用独立验证目录 `system-image-inventory`，没有覆盖历史 v1 报告。固定同一提交，126 个原文件 / 180,868 字节；48 个枚举目录、1 个排除边界，共 175 条记录，无扫描失败。v2 manifest `e636dc061057b363c2c9e11bddc16ffd92b484e7d02fa3d7c42b37c4645a7971`，inventory `76fc6466e6ff241c21e318c4c002751016cc41f82800813f9a11d8d165d6f12e`，均为 SHA-256。
- 对新 MinIO 工件执行真实 PG 身份/证据/权限/画像查询回放：1 passed。175 条扫描记录的哈希与作用域一致，报告登记幂等；546 条精确原文证据回读通过。此次新 provider 索引为 764 个实体 / 1,912 条关系，538 个 canonical 匹配，631 个有效 exact locator；这与历史缓存报告的 507 个 exact 不同，保留各自工件，不将其当成 gold 准确率或生命周期稳定性验收。实际目标应用与 Maven 均未运行。
- 旧 exweb v1 MinIO 工件另行回放 1 passed（`source-inventory-exweb-legacy-replay.log`），不补造历史 inventory。开发 PG 已迁移到 `0036_source_inventories`；本机 Portal/API/Runner/Workflow Worker 已重新加载，持续监督进程保持运行，Portal/API/Runner 均返回 200。PG/MinIO/Temporal 继续使用 Docker；模型仍为开发回退模式，未据此宣称真实模型质量闭环通过。

### 前序回归记录

- Git/CodeGraph/定位/原文快照/来源上传/登记并发/领域测试：63 passed。
- PostgreSQL 独立 schema：6 passed，覆盖迁移升降级、多源/多修订、同哈希幂等、跨项目 FK、Outbox 回滚和禁止 UPDATE/DELETE 历史。
- PostgreSQL 独立测试数据库：40 passed（system_image/source/snapshot API 子集，100 deselected）。包含正式 ToolRuntime 的多源登记、摄入、旧原文恢复及单个必需代码失败检查。
- `npm run verify:code-graph-provider`：真实 CBM 最小图通过。
- `npm run build:portal` 与 `npm run lint:portal`：通过；构建有既存大 chunk 提示。
- DDD + 登记并发检查：127 passed，1 failed。失败为 `useBuildRouteModel.ts` 62 行超过 `<60` 静态门槛，涉及非本轮改动；尚未解决，不标记完整 DDD 门禁绿色。
- 完整 API、E2E、smoke、灾备恢复、质量对照和 `verify:v1-release` 本阶段尚未完成。

API 子集使用 `scripts/test-api-postgres.py` 新建并清理随机命名 PostgreSQL 测试库，先执行全部 Alembic 迁移，不使用开发业务库或 SQLite。真实 provider/MinIO probe 与 mock 模型的 API 回归分开记录，禁止将后者当作真实模型语义验收。

本轮增量验证（不能与上面重叠测试简单相加）：

- 代码身份/解析/合并/定位/上下文/领域回归：65 passed。
- PG 来源与代码身份仓储：14 passed，包含并发幂等、跨项目 FK、provider 替换、旧引用映射、Outbox 失败回滚与历史不可变。
- 完整迁移到 0032 后的独立测试库：32 passed（正式多来源 ToolRuntime + 身份仓储 + 匹配测试）；另有 system_image/source/snapshot API 子集 40 passed。
- 真实 exweb + MinIO 原文恢复 + PostgreSQL 隔离身份登记测试通过。仍不是代码/需求/用例的语义 gold 验收。
- Portal build/lint 再次通过，保留既存大 chunk 警告；DDD 边界仍有前述 Build 62 行门槛失败，不宣称全量门禁绿色。
- 开发 PostgreSQL 已迁移到 0034；通过 `dev:foreground` 重启并加载当前实现，Portal/API/Runner 返回 200、Worker 与全部依赖就绪。Docker 仍只承载外部依赖。旧知识投影不自动回填，新物化对象才具有代码修订 pin。

本轮 Evidence 增量验证（以下与历史测试有重叠，不累计成独立用例数）：

- 领域/语法身份/定位/归档/PG 仓储：89 passed。
- 从空 PG 数据库迁移到 0034，相关 API 与多源回归：43 passed、100 deselected。使用真实注册、项目成员管理和 ToolRuntime 摄入，不写开发业务库。
- exweb + MinIO + PG 独立 schema：1 passed，包含 546 条精确片段回读。Boto3 对 Python 3.9 有弃用提示，运行时升级仍待单独处理。
- Portal build/lint/i18n 通过；保留既存 >500 KiB chunk 警告。边界检查 134 passed、1 failed，仍为非本轮 Build route model 的 62 行门槛；没有放宽该门槛。
- 新增 `scripts/test-api-postgres.py --playwright ...`，浏览器测试复用临时 PostgreSQL 数据库，不使用默认 SQLite，也不占用开发端口。小型源码 fixture 用于浏览器交互，真实 exweb/MinIO 验证独立记录。
- 最终证据浏览器测试 3 passed：真实 HTTP/PG 摄入与读取、深浅色/移动端、100 行分页、源码 HTML 字面量不执行、旧对象缺口、关闭/ESC 焦点恢复、撤销权限后禁止继续读取并隐藏正文。修复了窄屏知识卡片三列挤压导致按钮互相遮挡的问题。
- 截图已人工检查：`output/playwright/evidence-light.png`、`evidence-dark.png` 及对应 `-mobile.png`。完整 E2E/smoke、来源 ACL、真实目标应用执行和 V1 发布门禁仍未完成。

## 下一步

本轮 canonical Evidence 工具验证（与历史测试有重叠，不累加计数）：

- Evidence 领域/application/handler、Agent receipt 重规划与真实 invocation 引用、工具上下文、权限及 Runtime 端口回归：56 passed。
- PostgreSQL 正式工具/API/多源/幂等/重规划选择集：51 passed、97 deselected；另跑完整 `test_api.py`、运行配置、证据工具 API、PG ToolRuntime 与 Docker 契约文件：175 passed。不是全部 `apps/api/tests` 或完整 V1 release 验收。
- 全量上述 API 文件初跑发现两个旧测试依赖 SQLite `nasus.db` 文件；改为读取实际模型配置表，校验密文非明文、配置行无原始密钥、重新加载可解密后，重跑通过。没有回退到 SQLite 或跳过加密断言。
- exweb/MinIO/PG 验证 1 passed，继续校验 546 条精确原文。三个示例类另外通过固定 entity/source revision 的 list/read/expand，`identity-registry.json` 新增 `evidence_tool_receipts`。该真实仓库测试验证 application tool use case，不将隔离 schema 的测试授权替身冒充真实项目 RBAC；项目 RBAC 由独立 HTTP 测试覆盖。
- DDD + Portal boundaries：135 passed。Build 的已选卡片映射移入 `useBuildSkillSelection`，路由只消费 view model；边界断言随职责位置更新并禁止路由再做映射，保留 `<60` 限制，解决此前的 62 行失败。
- Portal build/lint/i18n 通过；完整现有浏览器 E2E：9 passed；独立 PG smoke：success。新增 `test-api-postgres.py --smoke`，使用临时数据库、独立端口及直接持有的服务进程，结束后清理，不使用开发业务库或 SQLite。
- 仍保留大 chunk、LangGraph serializer 与 Python 3.9/Boto3 弃用提示；未声称恢复演练、provider 全量 gold、目标应用执行或 `verify:v1-release` 完成。
- `dev:foreground` 已重启，API/Worker 加载新实现；在线 Catalog 包含两个 evidence 工具、OpenAPI 包含 receipt 展开入口；Portal/API/Runner 返回 200，全部开发依赖 ready。

本轮来源权限基础验证（与以上计数重叠，不累加）：

- 领域规则、Evidence/Agent receipt 与 DDD/Portal 边界：193 passed。
- PostgreSQL 来源权限、证据仓储/HTTP/工具专项最终重跑：30 passed。包含独立 schema 升降级、并发 CAS、Outbox 回滚、历史不可变、完整来源集合过滤、真实 pgvector/FTS 排序前过滤、读取进行中撤权。日志 `.nasus/validation/source-access-focused.log`。
- 较大范围 `test_api.py`、运行配置、来源权限、Evidence API、ToolRuntime、Docker 契约回归：208 passed。不是全部 API tests 或完整 V1 门禁。日志 `.nasus/validation/source-access-api.log`。
- exweb/MinIO/PG：1 passed，546 条原文继续校验，新增三类来源策略正反例；日志 `.nasus/validation/source-access-exweb.log` 与原 `identity-registry.json`。保留 Python 3.9/Boto3 提示。
- Portal build/lint 通过，保留 >500 KiB chunk 警告；独立 PG smoke success。完整当前 E2E **8 passed、1 failed**：注册进入 Build 后设置异步回填将界面从中文切为英文，中文澄清断言失败；`useStudioSettings` 会用服务端 language 覆盖本地 locale。本轮未修改该前端路径，也未放宽断言，不宣称 E2E 或 V1 全绿。日志 `.nasus/validation/source-access-e2e.log`。
- 开发库迁移到 `0035_source_access`，重新启动 `dev:foreground`，API/Worker 已加载权限读取实现；没有创建任何开发项目的 restricted 策略，Docker 仍只负责外部依赖。前端、API、Runner 就绪。

2026-09-10 来源受控上下文验证（以下选择集重叠，不累加为独立测试数）：

- Agent/application、Evidence 观察、来源领域规则、workspace adapter 与 DDD/Portal 边界：163 passed。边界要求注入只读 ContextReadPort，禁止 Agent 重新依赖画像 workspace；兼容 lexical adapter 不能静默忽略 caller scope。
- 独立 PG 的 Agent 上下文/真实成员/HTTP 与 SQL 预过滤专项最终重跑：8 passed，日志 `.nasus/validation/source-context-focused.log`。覆盖 query 形成后收紧权限、Provider await 中变更、跨项目 scope、成员撤销、固定证据引用和 no-store。首次新增错误响应断言误用 `detail.error`，核对统一 PlatformApplicationError envelope 后改为 `error` 并重跑；未改变产品错误契约。
- 较大范围完整 API 文件、运行配置、受限上下文/检索、多源 API、PG ToolRuntime 与 Docker 契约最终重跑：186 passed，日志 `.nasus/validation/source-context-api-final.log`。初跑唯一失败为上述新增断言格式，修正后在全新 PG 库完整重跑通过；保留 LangGraph serializer 弃用提示。这不是全部 API 测试或 V1 发布门禁。
- 首轮受限检索/上下文与原 memory retriever 兼容选择集：13 passed，日志 `.nasus/validation/source-scoped-agent-context.log`。嵌入与重排使用记录型测试适配器检查输入，不能据此声称真实模型的语义效果已验收。
- exweb + 真实 MinIO/PG 隔离 schema：1 passed；包含 546 条原文回读及新增 546/0 来源上下文检查，日志 `.nasus/validation/source-context-exweb.log`。保持固定 SHA，不运行 exweb 应用、Maven 或仓库 hook。
- Portal build/lint 通过，保留 >500 KiB chunk 提示；独立 PG smoke success。当前完整 E2E 仍 **8 passed、1 failed**，日志 `.nasus/validation/source-context-e2e.log`：本次在注册后的中文 Build 标题断言失败（`app.spec.ts:85`），仍为设置回填将中文变为英文的旧路径。未放宽断言，未宣称 E2E/V1 全绿。
- 开发进程已通过 `dev:foreground` 重启并加载本轮代码；API、Portal、Runner 返回 200，Worker/PG/MinIO/Temporal ready。未给开发项目新增 restricted policy，仍只在隔离测试中写入策略；实际开发 Embedding/Rerank 仍是 fallback。

2026-09-10 来源受控画像查询与 UI 验证（选择集重叠，不累加）：

- 领域与 DDD/Portal boundaries：151 passed；Portal build/lint/i18n 均通过，保留既存 >500 KiB chunk 提示。只读画像 port 为必须依赖，知识 query 不再导入 workspace。
- 独立 PostgreSQL 画像/知识/Agent/Evidence 专项：18 passed，日志 `.nasus/validation/source-image-queries.log`；较大范围 API、运行配置、多源、来源受控查询与 Docker 契约文件：186 passed，日志 `.nasus/validation/source-image-api.log`。覆盖三条读取路径一致性、无权对象 404、读取中策略/成员变化、归档地址移除及原始快照不被改写；不是所有 API tests 或完整发布门禁。
- exweb + MinIO/PG 回放：1 passed，日志 `.nasus/validation/source-image-exweb.log`；546 条原文校验继续通过，新增 546/0 画像列表和详情正反例。使用固定提交、真实 PG 身份与 ACL，DTO 和项目 actor 明确为测试替身，不执行目标应用。
- 专项浏览器检查 5 passed，日志 `.nasus/validation/source-image-e2e-final.log`：真实 HTTP/PG 来源摄入、权限撤销/恢复、失效弹窗不重开、失败读取隐藏旧内容、未知指标不冒充零，以及 light/dark/390px 布局。原分页测试假定撤权后旧弹窗仍在，现用网络拦截控制撤权时机、向真实 API 转发请求和原样响应，核验实际 403 和正文清除，不伪造响应内容。
- 截图发现的整段权限说明被当作知识标题、窄屏标题/统计溢出已修复；统计卡和权限提示为共享 UI。产物 `output/playwright/source-filtered-{light,dark}[-mobile].png`、`source-overview-{light,dark}[-mobile].png`。这不代表其他项目面板的来源授权或全部移动端交互均已验收。
- 默认并行（2 workers）的完整现有 E2E 最终 **11 passed**，日志 `.nasus/validation/source-image-full-e2e-final.log`。先复现注册/语言测试失败，再修复 `useStudioSettings` 用全局 language 覆盖本机 locale 的问题：界面和菜单使用浏览器持久化偏好，旧 PATCH 保存接口兼容；不宣称跨设备账号偏好同步已实现。测试增加真实远端语言修改后重取设置/刷新/路由跳转仍保留本地选择，测试初始化不再每次刷新覆盖已选语言；未放宽中文断言。
- 独立 PG smoke 最终 success，日志 `.nasus/validation/source-image-smoke-final.log`。新 `dev:foreground` 已加载本轮后端，Portal/API/Runner 返回 200，Worker 和外部依赖 ready；前端更新由 Vite 加载。开发库仍为 0035，未向开发项目写 restricted policy。

继续 P0/P1：补全 provider 生命周期和隔离；把来源 ACL 接入项目/workspace/portfolio、写动作响应、历史调用/SSE、组合与跨项目记忆；为本轮暂时 withheld 的派生上下文和 trace 补齐完整来源证明与 revision membership，补模型出口策略，再开放经过 ToolRuntime 的权限管理。继续文档/测试证据、身份 lineage/历史回填与影子切换审计。随后将不可变 SourceManifest 接入 ImageRevision 和自主调查工件，让按需证据展开真正参与受控语义调查。代码/需求/测试的正式关联、五类下游上下文、质量闭环与 P2-P6 全部验收仍是完整目标，不以本轮只读权限接入替代。当前测试门禁通过不代表 provider 生命周期、灾备恢复、语义 gold、真实目标运行或 `verify:v1-release` 已完成。
