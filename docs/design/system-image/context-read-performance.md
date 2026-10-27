# 固定上下文读取测量

更新：2026-10-13。本测量用于定位 P6 读取成本，不替代完整性能门禁或 P5 业务闭环。

## 用例准入的完整父输入复用

当前脚本归档读取通过 application 准入端口消费已经完整核验的历史/当前
输入，不重复编译相同父链。端口仍展开所有批准前驱，核验原 archive、
映射、生成、上下文与 source authority；末尾独立重读并校验审批头和实时
权限。头变更时旧内容仍可按权限检查，但不返回可用于当前操作的输入。
没有跨操作输入/ACL/head 缓存，公开响应、旧摘要及 legacy 行为不变。

同一个既有隔离 PG/私有 MinIO recipe 的诊断对照禁止所有写入和目标请求，
原完整响应 hash 相同。完整输入编译 9 -> 6，ContextPack read 18 -> 12，
SQLAlchemy execute 9407 -> 6376。原样本总读取 13.078 秒，加入父复用的
早期样本 8.535 秒，最终含末尾审批头复查的样本 12.964 秒。并发负载与
profiler 开销影响耗时，不据此声明稳定延迟降低或达到 p95/容量门禁。
日志为 `fixture-current-original-read-{baseline,admission-parents,admission-final}-20261013.log`。
这份 recipe 是明确协议材料，不是真实 exweb 业务覆盖或独立 gold。

最新纯应用/生命周期/边界回归 493 passed；实际隔离 PG/MinIO 的读取期间
canonical 撤回测试 1 passed，历史完整但 current=false。固定 exweb 原完整
来源/用例的 read-only archive/响应/读取次数对照和实际来源撤权专项仍在
运行，原生 build/owned target/Temporal 全链也新开独立验证；尚未取得终态。
各批句柄、加载版本和验证边界见实施记录，不把进度点或旧失败重分类为通过。

## 完整来源库存的选择读取

用例生成、脚本生成和 RunPlan 的来源读取改用 application 的完整来源成员
选择器。选择前仍核验全部原画像、对象成员、归档字节、实时权限和来源 scope；
向外返回的整个 source_members 深拷贝，包含 failed/pending/legacy 状态。原
完整 snapshot 和 RunPlan list 响应不变，没有内容/权限跨操作缓存。

固定原 exweb 的隔离 PG/私有 MinIO 对照包含原 126 blobs、725 个代码成员，
所有 Engine 事务 READ ONLY。原完整响应及所有对象字节 hash、SQL 和对象
读取次数一致，整个画像复制 6 -> 2；只有内存分配减少，不能声称 SQL 已减少。
普通来源/文档对照及实际同快照撤权验证也保留原断言。首次新测试在错误的
归档字段假设处失败，修正为原 source_revision_id 外键关系后当前批
3 passed / 63.64 秒，日志 `image-source-inventory-current-exweb-final-postgres-20261013.log`。
该验证不执行目标或外部模型，协议资料不是独立业务 gold；未测 p95/容量。
最新原生全链、旧失败复验及完整门禁状态见[实施记录](./implementation-progress.md)。

## Fixture 阶段的拥有作用域

Lifecycle 现在通过 journal 的可选 `verified_read_session` port 包围一个完整
setup 或 cleanup 阶段，而不是只在每次 journal 方法中独立打开证明作用域。
所有原 live guard／Runner／oracle／写事务仍逐次执行，完整来源与工件校验不减少。
该作用域只复用已经完整验证的不可变画像证明，不缓存计划当前可用性、权限、
规范批准／审阅／发布头、grant、lease 或目标健康。每阶段退出即清除；续租线程
不能继承 dispatch 线程所有权，取消仍等待原线程清理后返回。

红测为 8 failed，扩大原作用域／生命周期／执行／取消／DDD 回归为 620 passed，
作用域和 transport 为明确协议样本，不是目标执行或 p95。实际 PG 时钟／账号／
事件联合验证及原固定 exweb 全链的句柄与终态见[实施记录](./implementation-progress.md)。
原失败 exweb 不重发；新隔离验证没有扩大 90 秒租约、许可或等待时限，尚不能据此
声明租约失败已经修复、容量达标或完整 P5/P6 完成。

## 画像选择读取的内存复制

画像端口仍先完整核验归档、来源成员和实时权限。分页、文档成员选择、原文定位
及证据集合核验现在可在拥有的操作内只读使用已核验画像，不为每次选择深拷贝
全部代码和文档。向外返回的页面及文档成员单独深拷贝；`frozen_snapshot` 和私有
完整读取的默认隔离契约不变。没有扩大两份画像缓存、作用域、线程/task 所有权，
也没有移除 generation 再读取、当前规范、审阅头、ACL 或原始来源字节核验。

新选择契约先复现 8 failed / 15 passed，随后包含原复制上下文和页面预算等回归的
选择集为 104 passed。扩大 DDD/来源/规范/用例准入边界后 244 passed，与前者重叠。
实际隔离 PG/私有 MinIO 的完整页、文档和证据对照及原读取回归为 38 passed，日志
`output/image-selection-copies-postgres-20261013.log`。对照的完整响应、所有原对象
字节 hash、SQL 和对象次数一致，仅完整 payload 复制次数减少；同一快照内实际
撤权仍拒绝。资料是明确的协议样本，不是 exweb 业务 gold；未采集 p95 或容量证据。

## 映射生成父对象的操作内复用

映射服务原本已经回读完整生成结果、原文/工件、scope 和审阅历史；automation
随后再次读取同一个生成结果。内部 `read_with_result/resolve_with_result` 现在
返回这次已核验的完整父对象，普通公开读取保持原响应。仅在当前编译中复用，
不缓存 mutable head/ACL，也不移除独立 generation 输入校验和第二轮编译。

普通/分包及 prepare/replay 的实际隔离 PG/MinIO 对照已通过：完整响应、原对象
集合和每份原字节 hash 相同，全部业务事务 READ ONLY；每轮 result read 2 -> 1，
generation 调用不减，SQL/对象调用减少。真实来源撤权发生在父对象读取之后时
仍拒绝完整预览。专项 20 passed/309.66 秒，
`output/automation-mapping-parent-postgres-green-20261013.log`；内容为 protocol
specimens，不是独立业务 gold、exweb 原生执行或正式性能负载。

原 exweb recipe 的本轮受限 baseline 为 30.581 秒累计 profiler 时间、177839363
调用、result 6 次及 ContextPack 9 次，响应 hash 与前轮相同；日志/报告为
`output/exweb-fixed-fixture-mapping-parent-baseline-20261013.{log,prof}`。原任务
随后失败退出并清理临时库，不把新实现的理论读取次数当作同库实测。另一个
固定 exweb 全输入专项已终态 21 passed/481.06 秒，原 126 blob、完整输入及
所有归档字节一致；该专项原四用例、一个约束/四个义务保持不变。SQL 2856 ->
1908，对象 read 462 -> 308、result read 4 -> 2，独立 generation 检查仍两次。
报告为 `output/automation-mapping-parent-exweb-original-20261013.json`。内容
包含明确的协议用例/期望，不是 maintainer 的需求或独立业务 gold，也不与原生
全链的执行证据混算；详细终态见[实施记录](./implementation-progress.md)。
以上单次 profile/调用计数不证明 p95、目标机器容量或完整闭环。

## 原归档只读采样与脚本父链复用

`scripts/profile-fixed-fixture-read.py` 只接受已有本地隔离 PG 和原私有测试 bucket。
强制数据库 READ ONLY，S3 仅允许 Get/Head/必要只读枚举；未知或修改操作拒绝。
采样使用 recipe 原作者的实时权限，不创建事实、重发模型或派发目标请求。
日志只有函数位置/耗时、响应 hash 和失败类/SQLSTATE，不包含 SQL 参数或原文。

原 recipe 两次初始采样均在 mapping repository 的 `FOR UPDATE` 上失败（25006），
0.233/0.250 秒不是成功读取或性能基线。普通/分包/staged mapping 的 `get` 现在
不加写锁，仍重新读取并核验原 command；写入和 committed recovery 默认锁不变。
实际隔离 PG 专项验证 READ ONLY get、另一事务修改后 identity map 重新核验及
writer 继续受只读 PG 拒绝。具体终态和日志见[实施记录](./implementation-progress.md)。

随后原 exweb recipe 的完整采样显示 RunPlan 同时调用 script read 和 review read，
后者又完整回读同一脚本。`AutomationScriptReviewApplicationService.read_with_script`
现返回原完整审阅视图及该次已验证的父对象，RunPlan 消费原对象并检查选定 pins。
普通审阅 HTTP 响应不增加字段；当前输入、最新审阅头、源权限和最后 ACL 仍重查。
没有跨请求缓存，也不接受调用者提供的未核验父对象。

最终完整父链对照另在实际隔离 PG/MinIO 中通过：整个 plan/draft/review tuple、
完整原对象集合和每份原字节 hash 相同；脚本 read 2 -> 1，SQL/对象次数下降。
全部业务事务强制 READ ONLY；父对象返回后实际撤回来源权限仍拒绝。原模型
调用计数不增，执行/通过计数保持零。该单项 1 passed/144.02 秒，
`output/run-plan-review-complete-parent-postgres-20261013.log`；source/model transport
为显式 protocol specimens，不是 exweb 业务 gold 或正式性能负载。

同一已有归档的 baseline/reused 两次受限采样均成功，完整响应 hash 相同。
脚本读取 2 -> 1，ContextPack 读取 18 -> 9，总调用数 352714193 -> 177839357；
recipe read 的累计 profiler 时间为 61.884 -> 30.196 秒。原日志/二进制报告为
`output/exweb-fixed-fixture-read-parent-{baseline,reused}-20261013.{log,prof}`。
没有修改 126 个原 blob、七用例、oracle 或原决定。单对本机预热/profile 观察不能
证明统计显著性、p95、Linux 8CPU/16GB、并发容量或真实业务覆盖；其余重复父链和
完整 P0-P6 验收仍待交付。

## 实际路径

`test_exweb_context_read_measurement.py` 从授权的固定 exweb Git 提交
`fe5827f6b76f77ef34918d8b452ee823142332dc` 导出全部 126 个原始 blob，通过现有 canonical
来源注册、采集和 materialization 创建画像，再通过独立确认归档 `test_design` 上下文。
来源修订为本地 Git 树导出的内容 hash，不伪称采集到了远程分支的实时 head。

测试保留明确的 Orders 哨兵和合成 Search 需求／历史用例，未批准 AC，上下文仍 blocked。
它测量该固定来源画像的读取／历史派生校验，不证明 exweb 需求准确率、语义召回质量、已执行覆盖或发布就绪。

必须使用 `scripts/test-api-postgres.py --minio`：独立 `nasus_test_*` PG 和新建私有
`nasus-test-*` bucket。脚本退出时清理自己创建的资源，不迁移或写入开发库。目标 exweb
仓库只读，导出落在 pytest 临时目录，不启动其应用，也不调用外部模型。

## 观察与安全

- 每次独立 HTTP GET 必须为 200、`private, no-store`，完整响应与原归档读取一致。
- 记录原顺序中的全部耗时、PG 语句／连接／实时 ACL 查询数、MinIO 对象次数和字节数。
  对象清单仅输出 hash；不记录 SQL 参数、凭据、来源正文或私有对象地址。
- SQLAlchemy listeners 和 storage 包装器只观察原调用，不禁用权限／完整性校验、不引入跨请求缓存。
  独立实时授权连接必须归还；业务事实写入必须为零。认证／限流 bookkeeping 单列。
- 测量后实际撤回一项原来源权限。进行中的读取要求 409 `source_access_changed`，之后成员
  读取要求 403；管理员仍能读取完整原响应。不把任何错误码或隐藏部分内容当作成功读取。
- 不改写 MinIO 原对象，使用 transport 故障注入使固定上下文原字节损坏，要求拒绝且不泄漏。
  撤销注入后原响应必须仍一致。

## 重复运行

使用显式本地测试 PG／S3 连接配置，设置 `EXWEB_DELTA_GIT_ROOT` 为该固定提交的干净检出，
`EXWEB_CONTEXT_READ_REPORT` 为新的输出 JSON 路径，再运行：

```sh
./.venv/bin/python scripts/test-api-postgres.py --minio apps/api/tests/test_exweb_context_read_measurement.py -q
```

`EXWEB_CONTEXT_READ_SAMPLES` 默认为 5，可显式选择 5 至 30；超限拒绝、不截断。
统计保留原顺序，p50／p95 使用 nearest-rank，五个样本的 p95 就是最大值。
报告 `capacity_or_p95_acceptance=false`，不能只看数值就宣布验收。

这里的耗时覆盖 ASGI TestClient 调用、应用读取／派生和序列化，不包含网络链路。
来源采集、画像构建和上下文保存不在读耗时内；setup 已读过相同上下文，操作系统／数据库可能预热。
本机和其他验证任务的负载未受控，不是 Linux 8CPU／16GB 基线，也不是并发容量验证。
正式 P6 仍需目标机器、预注册负载、足够样本与完整来源／权限／恢复场景，并继续满足原 P0-P6 全范围要求。

## 连接复用对照与正式读取

最初 v1 是明确的隔离实验，不修改生产 application；仅在测试 reader 外层开启现有
`authorization.live_read_session()`。原 `exweb-context-read-connection-reuse-20261011.json`
保留这次实验的事实，不因后续实现改写为上线证据。

现正式 `ContextPackApplicationService.read()` 通过 application authorization port 开启
操作级连接作用域，再执行原完整读算法。复用 READ COMMITTED／READ ONLY 连接，不新增内容、
权限或业务事实缓存；画像、原归档、当前 authority／publication／retrieval 和最终 ACL 校验不变。
所有成功、过期、撤权与完整性错误路径均退出作用域，独立业务池不借给实时授权长读。

当前 `test_exweb_context_read_connection_reuse.py` 输出 v2 对照报告：每一对按 control →
production 执行。control 明确在测试中调用不带外层连接 scope 的同一原算法，随后还原正式方法，
production 使用真实公共 read；不把测试 baseline 当作新的公开绕过入口。模型和目标执行仍为零。

每对要求完整响应 hash、实时授权查询次数、对象清单 hash、读取次数及原字节数量完全一致。
正式 reader 中每请求只借还一个独立实时授权连接，必须一次 rollback、无 commit；business pool
借还次数必须减少。它不通过删除授权检查、缩小来源范围、跳过归档回放或更改 oracle 换取性能。
正式 reader 下再次实际执行读取中撤权、撤权后拒绝和损坏归档检查，每条异常也要归还连接。

另设 `EXWEB_CONTEXT_READ_CONNECTION_REPORT` 为新的实验 JSON 路径；仍使用上面的隔离 PG／MinIO
连接和固定 Git 根，运行同一 wrapper，pytest 文件改为 `test_exweb_context_read_connection_reuse.py`。
该 fixture 同样要求设置 `EXWEB_CONTEXT_READ_REPORT` 作为明确 opt-in，但只写独立 comparison report。

2026-10-11 的独立批 **1 passed /70.07 秒**，五对实际原始回放保持 **286 次实时 ACL 查询、69 次对象读取、
3670655 字节**不变；连接借还从 **340** 降至 **54 business +1 live**。control p50 **1.937298 秒**，
experiment p50 **1.653630 秒**。这是少量本机样本下的观察，不是统计显著性、正式性能验收或已上线优化。
此句描述 v1 实验时的状态；正式接入不能以该旧实验替代新加载回归。

正式 read scope 的 v2 固定 exweb 对照 **1 passed /73.85 秒**，五对仍保持 **286 次实时 ACL 查询、
69 次原对象读取／15 个不同对象／3670655 字节**及完整响应一致，事实写入 0。连接从 **340**
降为 **54 business +1 live**；control p50 **2.079942 秒**，production p50 **1.818643 秒**，
p95 分别 **2.781256／2.089031 秒**。原报告为
`output/exweb-context-production-connection-comparison-20261011.json`，读取中撤权／之后拒绝、
损坏归档拒绝及每条路径连接归还均实际通过。五个本机预热样本、并行验证负载未受控，p95 仍超过
两秒；不能据此宣布原 Linux 容量、性能门禁或完整 P6 通过。

应用 control-flow 专项另覆盖初始授权、原归档校验、当前输入、持久失效及最终授权均在 scope 内，
每条异常后下次读取独立，旧过期理由／原 context bytes 不变；它是 port double 测试，不替代
真实 PG／MinIO／浏览器撤权与历史回放。完整新加载回归和 V1 门禁仍须另行验证。

## 原 RunPlan 与 fixture 父链读取

2026-10-12 的原生环境关联专项暴露完整父链回读的较高成本。原 fixture recipe reader 已经
完整验证原 RunPlan、来源、审阅及归档，grant reader 随后却再次读取同一个原计划。
现在 `read_with_plan` 返回这次读取实际核验的完整父对象，grant 仍核对原项目／计划／工件摘要，
再验证 native environment 的独立原记录。普通 recipe HTTP 响应和旧 v1 工件不增加字段。
这里仅消除重复展开，不保存可变 head 或跨请求完整计划缓存。

`RunPlanApplicationService.verified_read_session()` 在完整 public read 和 compile 中开启
已有的 READ COMMITTED／READ ONLY 授权连接作用域；嵌套调用复用连接，每次授权语句仍重新
执行。固定来源证明只在原操作内复用。grant 的 `require_operation` 将历史读取、独立当前
输入复查、PG live consent 时钟及最终来源授权包在同一作用域，错误路径退出，下一次调用独立。
不能用历史父链、实时连接或 `current_use` 代替实际目标 preflight／worker／journal。

诊断 helper `fixture_parent_read_probe.py` 仅在显式 `FIXTURE_PARENT_READ_REPORT` 路径下运行。
通过隔离 PG／MinIO wrapper 执行原 fixture 测试：control 使用同一完整 reader，但丢弃其已核验
父对象并再次回读；production 使用该对象。两次 HTTP 响应及完整不同对象的原字节摘要必须
一致，production 需减少重复读取／字节／SQL，同时归还独立 live 连接，不写业务事实。
输出只有摘要、计数和耗时，无 SQL 参数、私有地址或源码。

这是一次 control → production 配对，不提供 p95、统计显著性或 Linux 负载验收。固定 exweb
专项保留原 126 个 Git blob，但伴随需求／模型／执行 transport 仍须按各测试的 specimen 边界
说明；原生环境专项的 code source 本身也是 protocol specimen。诊断不得把两者混为实际
exweb 业务通过。当前已启动的原生专项最初使用了会被隔离脚本过滤的 `NASUS_` 前缀输出变量，
因此不能把它当作已产出读取对照；正式诊断变量已改为上面的非过滤名字，后续须核验实际报告。
最新终态、诊断结果和剩余完整 P0-P6 门禁见[实施记录](./implementation-progress.md)。

固定 exweb 原126 blob 的实际报告
`output/exweb-http-fixture-original-parent-read-comparison-20261012.json` 已核验，专项
1 passed/3287.17秒。control→production 保持完整响应hash、1874响应字节、完整契约hash、
24个不同对象及各自原字节hash完全一致，业务事实写入0。耗时77.237082→38.991646秒，
对象读取2714→1358次、返回对象字节19,598,257→10,601,711、business SQL14,834→7,462，
business checkout/begin/commit2370→1187。每侧 live checkout/begin/rollback均1次、
commit0次。live ACL查询12,250→6,128是重复完整父链展开消除后的结果，每次实际授权仍
fresh；报告明确无ACL缓存或跨请求缓存，不能据此删去任何实际检查。

只有一对、顺序固定且本机负载未受控；模型/目标执行transport不作为业务gold。报告
`target_executed=false`、`capacity_or_p95_acceptance=false`。39秒仍远高于可接受读取
延迟，不是P6通过；不能将整个测试setup的54分47秒或这个单对变化当作p95/容量验收。
