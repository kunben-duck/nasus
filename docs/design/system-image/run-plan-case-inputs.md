# RunPlan 业务执行原始输入核验

更新：2026-10-13。完整 P5 的生产端口实现增量，已接入公共命令和任务生命周期，尚非完整闭环已上线。
完整目标保持[交付要求](./delivery-and-evaluation.md)的 P0-P6，验证终态见[实施记录](./implementation-progress.md)。

## 执行范围只能由原始记录推导

`RunPlanCaseInputApplicationService` 接收完整原 selection 和独立 invocation ID；
先检查当前项目执行角色、原 canonical 命令、确认账号、完整 payload 和 PG 时间。
不是 `quality.run_plan.execute_http`、未运行、未确认、过期、改变原 selection 的命令，
在读取私有构建、环境或 fixture 工件之前拒绝。确认、actor 或 scope 不能由 UI 代造。

`RunPlanEnvironmentApplicationService.original_inputs(current=True)` 回读原计划及独立
native build binding，重验所有 source/build/review pins；不是只比较产物文件名。
原环境 record 必须固定同一个 plan/build 请求、实际 instance inventory 和 operator
policy；metadata 和完整归档重新计算。实际 inventory hash 不等于 policy digest。

定位 record 回读完整 frozen inventory，重建原 action 对应的静态报告；所有定位必须
有原静态匹配，缺失/歧义/不支持不截断为较小计划。静态定位不是 runtime dispatch
或业务覆盖证明；浏览器 DOM 执行及不支持的解析仍必须按完整目标交付。

每个原 case 必须恰好有一个不同的 setup 命令，并保持原 case 顺序。每项固定同一
project/RunPlan/plan digest、case、fixture manifest、native environment record/hash、
target artifact 和实际 inventory。独立业务命令不继承原 fixture 的 setup/cleanup
许可，也不更新原 fixture 许可 TTL。

## 原 setup 与清理库存

`RunPlanCaseFixtureApplicationService` 使用既有 application history/grant/runtime
端口回读原 setup；原命令必须 completed，原生结果必须 passed，所有原 capture
必须存在。私有 journal 再验证 raw request/result bytes、物理响应和原 oracle，
并额外固定所选 setup invocation/request digest 与原 v4 canonical dispatch 的关系。
相同 attempt/case 下另一条命令的结果不能被借用。

历史读取包含所有 cleanup slots。缺 setup、未知 setup、任意 cleanup 已 claimed
或已有结果均阻止开始业务执行；读取本身不 acquire/renew lease、不创建 intent、
不发 HTTP、不重新准备，也不把 unknown 改成成功。读取期间命令或阶段库存变化时，
重新查看同一原操作，不能生成替代 attempt。

这证明的是原 setup 响应和“没有已知清理派发”，不是所有资源仍存活的业务保证；
真实 target/oracle、fixture 到业务 action 的显式资源绑定及执行期间资源隔离仍需
原生验证，不能以本模块声明全面 fixtures/runtime 已验证。

## 当前 guard、事务与异步执行

producer 返回固定 plan/scope 和完整依赖摘要。业务 Worker 的每个 guard 重新读取
原命令、权限、全部来源/审阅、build/environment/locator/fixture，并重新探测目标及
依赖健康。原 actor/source fingerprint、target epoch、原依赖发生变化时停止，不
重绑定原 run。瞬时健康观察时间不写入固定依赖摘要，但实际健康响应和 inventory
必须匹配原实例。

完整输入核验结束后还要重新读取原 canonical command 与 PG clock，检查原
selection、actor、command digest 和未延长的 15 分钟确认窗。核验期间过期、
取消、确认被改写或命令损坏，均拒绝返回 prepared inputs。历史读取不要求旧
确认新鲜，但同样保留末尾原命令摘要核验；准备结果本身不是派发许可。PG command
reader 在最后授权/账号检查后重新查询原 command/preparation，再采样服务器时间，
不返回回调之前的旧状态/时钟。真实 PG 专项及验证范围见实施记录。

完整 prepare、每个独立 guard 和历史回读各自打开一次 operation-local verified
read session；原 plan/build/environment/locator/全部 fixture 的固定画像元数据在
同一次同步读取中复用。下一次 fence 必须重新读取，不能缓存当前 ACL、批准头、
目标健康、cleanup 库存或 lease。缺少可复用端口的兼容调用保留原行为；异常、
跨线程/任务或延迟回调不得借用已结束的 scope。该优化不是容量或 p95 验收。

业务账本持有项目写锁时，核验回调不能在另一个 session 再取同一把写锁。因此新增
明确 readonly fixture history 模式；包含递归 setup 读取，不使用 live worker fences，
不变事实、原命令 ancestry、角色和原字节仍完整核验。派发/提交/取消的原写锁不变。
实际跨会话竞争与事务故障仍需 PostgreSQL 验证，不以 SQL/mock 契约代替。

同步 PG/MinIO/健康核验在受监督线程执行，避免阻塞 async Worker 的心跳。取消设置
本人的停止信号并 join 原线程，核验完成后也不能继续进入 case Worker。目标 Node
配置延迟到执行时检查，缺配置在租约/claim 前失败，不阻止无关 API 启动。

`RuntimeAssembly` 和 `ApplicationContainer.run_plan_cases` 已组装 producer、既有
owned Runner、PG case journal、物理 verifier 与独立私有 MinIO archive。内部入口
必须先 producer，再使用其 guard，不能把客户端 scope 或空回调交给 Worker。
私有 case archive 禁止 local fallback、public URL、其他项目/bucket、不完整字节、
歧义 JSON 或非 JSON 常量；完整回读后才提交结果。结果仍使用原 case/step/oracle，
本链路的正式 automated/executed_on_target/passed 计数仍为零。

## 未完成的交付和验证

2026-10-13 新增显式 v3 原始字节 handoff：旧 proof 字段不变，独立 `read_native`
类型返回完整 setup request/result；producer 为全部原用例生成 capsule/input，并
在新 scope 固定有序 capture/input digests。原 base scope 先固定，避免摘要循环。
current/historical 都重新验证全套原来源，scope 反序列化保留新类型和全部 pins。
主 application 仅对新 prepared 类型传递 fixture inputs，旧 Worker 入口和摘要保持
兼容。具体字段、版本及验证边界见 [Fixture 资源绑定](./run-plan-fixture-bindings.md)。
真实新 PG/MinIO、公共 v3/Temporal/owned exweb 和正式 coverage 以实施记录为准，
不得用内部 protocol specimens 替代。

同日后续的 [0120 任务生命周期](./run-plan-case-jobs.md) 已接入 execute/cancel/query
Tool Catalog、只读 HTTP 历史、Temporal adapter 及 Portal 独立确认/只读恢复。隔离
PG/MinIO 的完整新 scope 已有终态，真实 Temporal 专项也已通过；真实 owned exweb
全链原批在静态定位处失败，新 scoped locator 版本已修正并独立重跑，终态见实施
记录。独立 unknown 处置/原结果恢复、正式 coverage/release 与 GC 仍需交付；未对
开发数据库执行本轮迁移。既有 fixture 私有历史仍要求 administrator；QA 角色的完整
消费权限政策不能通过复用旧 fixture 许可或放宽历史读直接绕过，需要独立交付。

原核心契约使用明确的协议 specimens 和内存 journal/storage/原生健康响应替身；
后续真实 PG/MinIO、Temporal 与 owned target 验证单独记录，不与协议测试混为一谈。
测试保留完整原 case roster，不缩小
原计划/断言。没有修改外部仓库、gold、需求、用例分母或预期失败。容量/p95 尚未
测量；重复完整核验可能昂贵，后续优化必须保留原字节、即时 ACL 和持久事实完整性。
