# 系统画像开发顺序与验收方案

状态：2026-09-09 开发设计。以下测试、迁移和性能门禁是**待实施要求**，不是本轮执行结果。主方案见[自主构建](./autonomous-system-image-design.md)，字段语义见[知识契约](./knowledge-contracts.md)，选择依据见[开源评估](./technology-evaluation.md)。

## 1. 交付原则

按能被用户体验的垂直切片实施，不按“先搬完所有文件、最后联调”组织。保留现有公开 API/Tool ID，所有正式写动作仍经 ToolInvocationRuntime，UI 仍使用既有 shared shell/composer/popover。禁止为门禁改成假的 source、mock 图或完整响应拆 token。

每阶段结束提交设计差异、迁移脚本、实现、回归证据和真实 fixture 产物；后续阶段不能用文档中的 planned 替代前置完成证据。

## 2. 阶段与完成定义

| 阶段 | 交付内容 | 依赖/主负责边界 | 可见成果与退出条件 |
| --- | --- | --- | --- |
| P0 契约和 provider PoC | 固定 release/digest、CodeIntelligencePort v2、CBM/CodeGraph 同语料试验、身份与精确定位 spike | system_image + infrastructure | 一仓库两修订的规范化实体/边报告；两项目隔离、取消、分页/截断测试；选定可上线 provider 或明确 gap，不直接升级现网 |
| P1 不可变三源底座 | 多 binding、SourceRevision/Manifest、ID registry、Evidence、影子迁移、旧 DTO 兼容 | system_image + persistence/platform | 两代码仓库+两文档不互相覆盖，旧画像可重放，新源登记不清空旧 official；真实证据点击定位 |
| P2 自主结构画像 | BuildIntent/InvestigationPlan、引导与自然语言入口、授权预算、持久化工件、缺口调查与 review | agent 调度 + system_image 能力 + frontend | 代码-only 自主构建完成结构候选；补源恢复同 goal；stop/retry/restart 正确；发布需审批 |
| P3 业务关联与语义审阅 | AC/规则/测试结构化、typed link、负向决策、冲突、readiness 向量 | system_image + quality_loop ports | 代码+US+测试可解释关联，中文用例可用；错误关联可否定；推测不混入 approved oracle |
| P4 版本持续更新 | webhook/定期核对、delta DAG、依赖失效、overlay tombstone、三方合并/CAS、回滚 | system_image + governance/workflow | 第二迭代无需重建无关事实；并行版本不串数据；发布竞争/迟到证据/删除失效测试通过 |
| P5 下游闭环 | 五类 ContextPack、mandatory AC/风险约束、US 草案、用例/脚本/RunPlan/证据回流 | quality_loop 消费，system_image 提供上下文 | 退款示例完整走到目标 build 的真实测试证据与放行判断；上下文缺口确实阻断错误结论 |
| P6 加固与试点 | 跨项目安全、容量/恢复/灾难演练、运维、可访问性和质量对照评估 | 平台 + QA + 运维 | 达到下表门禁并通过真实试点；不得仅凭测试数量认定 V1 就绪 |

P0 应同时交付最小数据/边界 contract tests，避免 provider 适配与 P1 schema 脱节。P2 可以先输出结构认知和缺口；P3/P4/P5 不能永久留为“后续增强”，它们都是本目标的一部分。

2026-10-13 当前状态：以下各增量段落保留其初始阶段边界，不将“当时未接线”
当作今天的状态。原 case producer、公共执行/取消/查询 Tool、只读 HTTP、Temporal
和 Portal 已接通；隔离 PG/MinIO、新 scope 与真实 Temporal 专项已有终态。原
owned exweb 全链在静态定位处失败，新显式 scoped locator 策略及 Portal 回归已
修复并独立重跑，尚无新真实全链或完整 V1 全绿终态。最新失败点、证据和运行
handle 见 [实施记录](./implementation-progress.md)；本表所有退出条件不缩减。

2026-10-13 的 0118 增加[RunPlan 原用例执行核心与 PG 派发账本](./run-plan-case-execution.md)：
完整原 HTTP v1/v2 清单、独立命令 guard、PG-clock lease、先 claim 后请求、原 wire/
动作/oracle 私有归档及追加式 outcome/cancellation。不使用 fixture 许可授权业务请求，
unknown 不重发或晋级覆盖。初始阶段是内部 Worker/持久适配器，公共 Tool/Temporal/
Portal 与 producer 当时未组装，PG 迁移和真实验证当时未运行；当前证据见上述更新。以上全部
P0-P6 退出条件及真实覆盖/放行、五用途和旧链切换仍然必需。

同日后续[原输入 producer](./run-plan-case-inputs.md)已实现并内部组装到
`ApplicationContainer.run_plan_cases`，回读完整原 build/environment/locator/setup，
重验 actor/来源权限和实际 target health，拒绝未知或已清理资源；同步核验线程受
监督取消，私有 case archive 禁止 local fallback。公共 Tool/HTTP/Temporal/Portal
后续已接通；完整真实 PG 竞争和 exweb 目标 case/step/oracle 到 coverage/release 仍未验收；
本表 P0-P6、五用途、旧链切换及容量/性能/业务 gold 退出条件保持不变。

2026-10-13 的 0114/0115 已为[原 fixture 命令](./http-fixture-command-provenance.md)接线
独立确认的执行/查询/取消 Tool、同 ID Temporal 编排、原账本只读接口和追加式取消/
投递事实；迟到 handler 不得无锁重写终态，unknown 不得 completed 或自动重发。
这是代码/契约验证增量，以下私有模块段落保留各历史阶段边界，不代表当前完全未接线。
初始阶段 Docker 停止，后续真实 PG/MinIO/Temporal 已分别验证，owned exweb 公共链
的新全链终态尚未通过；执行 Portal 已接通，独立 unknown
恢复、真实 coverage/release、五用途和本表完整 P0-P6 退出条件仍全部必需。

同日 0116/0117 后续增加原 claim 准备回执、绑定前同 ID 恢复、授权只读准备观察与
独立持久取消。取消在原项目／Tool 行锁下选择原分支，不为取消制造 intent，旧已绑定
协议不改；原事实、审计与 Outbox 同事务，取消投递不是目标停止或业务回滚证明。
当前扩大契约通过、离线 DDL 和 PG 测试收集与实际 PG／RPC／exweb 验证分别记录；
以上完整退出条件不因此缩减，当前仍无最新完整 V1 门禁全绿证据。

同日后续将[原 fixture Portal 操作](./http-fixture-portal-operations.md)接入已核验定义：
完整原生父链只读核验、显式 v2 操作许可、独立执行/取消、原 ACK 恢复和 v1/v2 观察。
契约组、SSR/hook doubles 与构建/lint 不是实际浏览器、PG/RPC 或 exweb 验收；项目历史
发现、独立 unknown 恢复、真实 coverage/release 和上表所有退出条件继续必需。

2026-10-11 将[发布阶段质量门禁](./release-evidence-gates.md)收敛为同一领域判断：来源库存 unknown、低分、审批/合并未解决时，不因工具执行完成或六条资产 lane 完成而标记 US 待发布。旧 API journey 现在明确检验待审阅、未知质量阻断及审批不能晋级 baseline；这是负向契约校正，原正向真实业务闭环、独立质量证据与本表全部 P5/P6 退出条件仍然必需。

2026-10-11 的[原实例 HTTP 执行端口](./owned-target-http-execution.md)将开发探针接入 quality_loop application port，按 private operator registry 固定完整 target/依赖/network/JAR，在每次请求前后拒绝换实例并保留原 wire/result。实际 exweb 七任务和清理后只读回放的证据见实施记录，失败行为不改写。该端口尚未接入独立持久 RunPlan 授权与 Tool/Temporal dispatch，不能以开发 probe、协议回归或 archived result 替代 fixture/runtime locator、真实覆盖到放行或本表完整 P0-P6 退出条件。

2026-10-12 的 0108/0109 将[HTTP fixture 原始账本与私有 worker fencing](./http-fixture-lifecycle.md)落到 PG/MinIO：原 attempt/case/phase 唯一，固定原父链与完整输出，PG 时钟、独立 setup/cleanup 租约、递增 epoch、同事务原派发所有权和拒绝未知效果重发。当前仍是未挂 production 的私有能力，管理员/租约不是独立执行批准；公共 Tool/Temporal、取消/恢复、真实覆盖与放行以及本表全部 P0-P6 退出条件仍必需。

0110 补充[完整 fixture 定义的正式登记](./http-fixture-recipes.md)：独立 canonical 确认、原保存计划的确切声明/hash、追加式 PG/私有 MinIO 和事实/审计/Outbox 原子提交，历史读取和 Agent 回执重新核验当前来源权限与原字节。独立 Portal 输入核验、明确确认和失联后只读恢复已接线；当前实测范围见实施记录。它只固定未来授权的输入，不调用 Runner，不代表准备/清理通过；独立执行批准、执行 Portal、Temporal、覆盖到放行和本表完整 P0-P6 退出条件保持不变。

0111 推进[准备/清理独立许可](./http-fixture-grants.md)：每种操作单独确认，原定义/attempt/target 与确认人固定，PG 时钟限时、追加式 FK、审计/Outbox 原子提交和重新授权的历史/Agent 回执。它只完成权限链的一个 gate，尚未连接 production journal/worker 的派发事务；实际执行、取消/未知效果恢复、覆盖/放行、五用途、安全性能/gold 及本表 P0-P6 全部退出条件继续必需。

0112 后续将原许可与私有 journal/worker 在[同一 PG 派发事务](./http-fixture-dispatch-consents.md)连接：v3 固定 completed grant、worker owner 和 scope，追加式消费记录/复合 FK 与 dispatch/审计/Outbox 一起提交；到期 staging 回滚，缺失历史不能降级或未知效果重发。private fence 尚未 production-composed，测试的 protocol Runner/frozen reader 不代表原生业务覆盖；canonical/Temporal 运行、实时 preflight、取消/恢复、真实放行和本表完整 P0-P6 要求仍必须完成。

0113 增加[原生环境的显式 v2 许可](./http-fixture-native-targets.md)，将原已完成环境记录/hash 与实际 instance inventory 和 operator policy 分开固定；完整五字段复合 FK、原回执和同事务关联拒绝换实例、缺失或降级。旧计划/许可不改写、不自动晋级；原生目标 Tool/Temporal 消费、真实覆盖/放行、独立 gold 和本表全部 P0-P6 退出条件继续必需。

2026-10-12 的 transient preflight 通过 application health port 在私有 journal 写事务前
核验原计划、当前输入/权限、原环境/JAR/inventory、依赖/目标健康与 worker callback；
历史回读不做 live probe，不写可复用授权。固定 exweb 的原126 blob、原 JAR、实际隔离
PG/Redis/目标健康与停止/重启拒绝已取证，fixture命令仍0次，调度/业务oracle/worker为
明确 specimen；具体终态见[实施记录](./implementation-progress.md)。该增量不替代正式
Tool/Temporal 派发、请求前后复验/locator、取消/未知恢复、真实 case-step-oracle 到 release，
也不改变本表完整 P0-P6 和性能/gold 退出条件。

0098/0099 的[固定脚本草稿与独立审阅](./automation-script-drafts.md)消费已审阅用例并保存原生调用和全部动作/oracle 决定，未改变原覆盖或授予执行权限。Portal 已增加预算确认、脚本发现、逐项审阅和失联后只读历史入口，Agent 也有固定映射的历史查询；验证终态见实施记录。原生 PG/MinIO、固定 exweb 来源与协议模型夹具分开验证，不用 UI 协议测试证明模型质量或目标执行。该进展不能替代完整 automation ContextPack、公开任务生命周期/恢复、RunPlan、真实目标执行/放行、五用途切换或本表 P0-P6 退出条件。

0100 的[脚本与审阅派生追溯](./automation-provenance.md)将原事实、完整选中 case/step/oracle 摘要和前驱连接到精确上游登记，在原事务保存并只读核验历史。旧摘要/API 不变，普通读和事件不得补造缺失历史，populated migration 独立验证。该桥接不扩展公开 v1 impact/invalidation 图，不替代统一项目 delta DAG、完整 RunPlan、真实业务覆盖或本表全部 P0-P6 退出条件。

0101 的[执行计划准备](./run-plan-preparation.md)固定完整原脚本/审阅及 target build/environment/fixture 声明，canonical 确认、精确来源 FK 和计划/审计/Outbox 同事务保存。声明不能代替原生目标证据，prepared 仍零执行覆盖；完整 attestation、独立授权、canonical Runner、逐 case/oracle 证据、Portal 和旧链切换仍需完成，本表 P0-P6 退出条件不变。

后续 Portal 已接入完整原审阅的执行计划声明、原生构建及完整来源关联表单、确切回执回读和失联后的只读恢复。专用命令回执重新核验全部原来源，会话搜索与各类事件流只展示脱敏生命周期；实际浏览器、PG/MinIO、exweb 与协议 specimen 的验证范围分别见实施记录。原生构建面板已提供独立确认式取消，丢失回执只回读原取消命令，不自动重发；公开结果仍明确清理未核验。表单和取消入口不替代目标环境及 fixture 核验、独立执行授权、逐 case/step/oracle 运行、旧链切换、孤儿资源恢复、完整 UI 生命周期或上述 P0-P6 退出条件。

HTTP 脚本的执行器已补齐实际请求、四类 oracle、原响应字节与 metadata 工件，以及 API 的逐项重新核验。浏览器原协议保持兼容，超时或调用方断开不补造后续执行；精确小数和严格类型避免假通过。该增量的原生目标是显式本地 HTTP 夹具，不是 exweb 业务 gold，也没有替代正式 RunPlan 派发、持久执行生命周期、目标环境/fixture 核验或真实覆盖。具体契约见[Runner 执行观察](./runner-execution-observations.md#http-动作与原响应核验)，本表 P0-P6 全部退出条件不变。

后续原用例观察接口保留完整 case/step/oracle 和上游 pins，批量核验原实际 HTTP 响应，并将确切已保存 RunPlan 父工件与完整观察存入私有 MinIO。回读通过现有 application 计划读取端口重新检查原来源权限，不触发 Runner 或模型。固定 exweb 独立运行也已执行生产 HTTP oracle engine，失败状态如实保留；它的开发 oracle 和本地协议用例不能拼为正式覆盖。canonical 执行授权、环境/fixture、PG 观察事实/审计/Outbox、持久派发与完整 P0-P6 退出条件继续待交付，不把这个接口声明为完整 P5。

2026-10-10 的[真实 exweb 运行验证](./exweb-native-runtime-validation.md)开始执行固定原仓库：无网络 Maven/Java 21 构建，独立 PG/Redis/内部网络，以及实际会话 HTTP 与重启观察。它发现错误状态和内存持久化缺口，报告不能视为正式批准或通过覆盖；没有将前述 Orders/HTML 夹具拼成 exweb 业务。正式脚本/RunPlan/构建永久归档、canonical 执行与证据回流、退款示例、完整五用途和本表 P0-P6 退出条件不缩减。

2026-10-10 的[自动化输入衔接](./automation-input-preview.md)已保留当前审阅的原 context/scope/generation/mapping、全部义务和 oracle，HTTP/Portal 仍只读且不授予执行权限。同日[Runner 实际观察](./runner-execution-observations.md)将完整实际请求/摘要和逐步骤结果保存为私有归档，Run 与 evidence 元数据同 PG 事务、失败回滚且不改 peers；不在执行返回后改用 latest TaskContext。后者的原生 HTTP/Chromium 目标是显式 HTML 夹具，前者的真实 exweb 静态来源另取证；不能把两者拼成已执行 exweb。完整 automation ContextPack、预算化脚本/审阅、case/oracle/build/environment/fixture 的 RunPlan、原子 canonical 交付与真实覆盖/放行、五用途及本表完整 P0-P6 退出条件继续待实现。

2026-10-07 的[固定目标构建意图](./targeted-build-intents.md)新增 v3 baseline/version/head/source scope，当前 Portal 保存前核验并锁定执行目标；原 canonical、结构授权、同目标补源和追加阶段消费原 pin。旧 v1/v2 不改写。这推进 P2 的统一意图基础，但自然语言/维护事件入口、完整自主调查和本表全部退出条件仍未完成。

2026-10-08 已保存 v3 意图的 UI 和显式聊天请求通过同一 application port 规范化为原计划 Goal，由服务器编译固定 read/authorize/structure 三步。错误命令不回落模型或旧可变流程；独立结构预算不随入口自动确认，丢失回执仅重新授权并回读原会话。真实 PG、Temporal、exweb 原生索引与浏览器证据分别记录在实施进展；不是完整三入口、维护事件、全计划预算或 P2 退出条件的完成证明。

0087 的[原目标追加式阶段](./image-plan-phases.md)补齐 0086 草稿之后的结构执行入口：保留历史步骤/工件及目标 version，独立确认阶段和新计划预算，Local/LangGraph PG 恢复与原生 exweb 验证分开取证。它推进 P2 的补源同目标链路，但完整动态调查、多能力授权/累计费用、Temporal 全分支恢复、引导到正式发布以及本表全部退出条件仍未完成。

0094 的[采集准入](./source-acquisition.md)将 canonical 原命令、授权执行账号、来源身份与 origin manifest 固定在 connector 前，并与 metadata-only Outbox 同 PG 事务保存。损坏身份/清单拒绝、当前权限与并发重入有独立专项；它不是 lease、逐来源结果消费、Temporal 采集/取消、崩溃恢复或旧链切换的完成证据。原 P1/P2/P4 生命周期、性能、安全及本表 P0-P6 退出条件全部保留，exweb 的静态资料验证不代替目标运行/gold。

0095 后续增加原命令的逐来源结果、持久 progress roster 和完整 manifest 消费。结果/inventory/revision/Outbox 与清单/head/receipt/Outbox 各自在同一 PG 事务保存；新实例消费原结果，缺失历史不借事件或最新来源补造。失败原因脱敏，不将 PG 故障吞为 connector gap。当前事务后中断/fresh 服务及固定 exweb 126 文件归档专项已经通过；另有实际 SIGKILL 后独立 PID/缓存的显式内部恢复、撤权及 head 竞争验证，具体终态见[实施记录](./implementation-progress.md)。批量元数据读取消除一条 N+1，不声明容量或 p95 达标。这尚不是 OS 强杀后自动调度、Temporal/lease/取消、兼容 projection/chunks 与任务终态一致交付或对象 GC，原 P0-P6 全部退出条件保持不变。

后续[固定来源 materialize 与工作区隔离](./frozen-materialization-inputs.md)移除兼容构建中的隐式重采集、可选失败时的 mutable 提取回退和来源证据反写；每个实际 canonical handler 的独立 staging 防止继承旧 US 或覆盖新的 TaskContext。固定 exweb 归档删除原目录后零 connector 与完整文件字节验证另取证。该切换仍只是 P1 的一部分，不证明 materialization 命令持久原输入、并发 owner/CAS、兼容 baseline 的治理切换、正式质量入口或全部 P0-P6 退出条件已完成。

0096 后续已将物化命令的原来源清单、执行账号和 command digest 持久化，并与消费 pin/Outbox 同事务提交；旧命令只登记缺失原输入，不倒推回填。新增实际 SIGKILL/新 PID 与私有缓存的两窗口恢复，固定 exweb 删除导出目录仍验证全部 126 blob；当前权限和 head 变化拒绝，不重采或重绑。它推进 P1 的原输入恢复，但不固定全部目标/模型输入、不证明 stable output、并发 owner/CAS、自动调度/取消、兼容投影与 canonical 终态一致交付；本表 P0-P6 退出条件保持完整。

2026-10-07 的[代码能力与完整性报告](./code-graph-execution-control.md)新增本地能力声明、具体缺口及新旧分析报告兼容，不以此取代 P0 的原生功能协商、持久 index handle、完整生命周期、CodeGraph 对照、隔离/gold 或性能退出条件。

后续同日新增真实 `worker_owned_session` 索引会话并接入原 canonical 分析路径：原生一次建索引后支持固定候选分页、定位和保守影响，取消信号进入所属进程组。其寿命限定在 Worker 会话，状态/游标不是 PG 持久 index handle，影响明确 incomplete；本表的跨重启/两项目隔离、原生协商、完整取消、独立 gold、Provider 对照与 P0 退出条件全部保留。

0079 增加 PG 持久 generation、原始来源和首次输出摘要、epoch fencing、跨实例取消及重建恢复，已接入带实时 callback 的确认式结构构建。固定 exweb 与实际 OS 协议 Worker kill/reopen 的证据见实施记录，范围不是完整业务 Workflow 自动恢复、强杀清扫、跨主机、账号/网络/资源隔离、原生协商、CodeGraph/gold 或容量/性能；本表 P0-P6 的完整交付要求不缩减。

0080 后续增加实际原生 MCP 初始化/工具 schema 协商和不可变 PG receipt；0081 防止普通命令重试通过新 generation 替换 Provider 或来源修订。固定 exweb 的两个协商/重建及并发、原子、迁移、损坏拒绝专项见实施记录。原生 schema 与 CLI/server 版本分别保存，不等于全部语言/结果 completeness；空私有探测目录不等于独立账号或禁网。自动业务 Workflow、强杀清扫、完整依赖锁定、Provider 对照/gold/性能和本表 P0-P6 退出条件继续保持原范围。

同日新增[公开索引生命周期](./code-graph-execution-control.md#公开生命周期与当前来源权限)：来源范围发现/状态和独立确认式取消，已接入 canonical Tool、只读 GET、当前私有来源权限与 Portal。查询不启动 Provider/续租，取消与候选提交共享锁并保留已提交事实；无权确认不再消费他人的待确认命令。实际 exweb HTTP/native 验证与浏览器 PG 状态 fixture 分开取证，完整结果见[实施记录](./implementation-progress.md)。公开 reopen、自动业务 Workflow、完整隔离/能力/性能/gold 及本表 P0-P6 验收仍未完成；专项通过不代表完整 V1 通过。

0082 将原确认式结构命令接到持久 Temporal 调度、PG intent/owner/epoch fence，保留原 plan/source/target/confirmation/budget，已通过真实 exweb 的直接 Tool 与 AgentGoal 两入口重试/投影重建验证。Portal 新增当前账号固定计划的有界未完成命令发现与刷新恢复，不自动重写或确认；其余能力恢复、完整引导与动态调查仍待实现。上述[结构任务契约](./code-graph-execution-control.md#结构任务调度与恢复0082)是 P0/P2 的增量，不替代 OS 强杀清扫/完整隔离、Provider 对照/gold/性能、五用途/旧链切换、真实目标测试及本表全部退出条件。完整 V1 门禁状态以实施记录中的各批终态为准，不用专项拼接宣称通过。

0083 新增[独立结构停止](./code-graph-execution-control.md#独立结构停止0083)：停止有单独 canonical 确认和不可变 PG 意图，支持未创建 native generation 的排队任务、活跃 Worker 清理后确认及候选提交竞争；Portal 勾选不跨刷新保留，失联仅重读状态。真实 exweb/Temporal 的三场景和浏览器状态/移动检查分开取证，不冒充同一个 PG+MinIO 原生业务试点。旧 inline 进程崩溃恢复、OS 强杀/孤立物理对象 GC、其余任务取消、完整动态调查/全计划预算及本表 P0-P6 全部退出条件继续待交付。

0084 新增[固定画像的证据调查修订](./evidence-investigation-revisions.md)：实际归档样本、追加式问题/缺口任务、单项证据历史去重、三次无进展与独立确认；原结构 AgentGoal 经显式继续准备调查，再独立确认和执行保存的有界只读任务，不新建平行 goal 或继承结构 grant。Portal 区分继续/确认/审阅，刷新和丢失回执不授权下一步骤。真实 exweb 两入口和当前 PG/浏览器证据见实施记录；有界采样不证明覆盖，尚无完整动态语义调查、全计划预算、补源 plan revision、原子 checkpoint 恢复确认或完成到发布的全引导。本表全部 P0-P6 退出条件保持不变。

同日后续[结构继续条件写入](./evidence-investigation-revisions.md#结构继续提交的条件写入)在服务端编译前固定完整检查点，并在 PG 行锁事务内比较/保存全部步骤；HTTP 竞争与实际 exweb/MinIO 复验见实施记录。它不等于用户所见快照的公开预条件、Temporal/治理确认全链或事实/事件同事务，也没有持久恢复命令回执。完整原子恢复和本表全部 P0-P6 要求继续保留。

0085 后续增加[用户快照与持久结构继续消费回执](./evidence-investigation-revisions.md#用户快照与持久消费回执0085)：原展示 DTO 贯穿 HTTP/Local/LangGraph/Temporal，固定画像的不带 pin 信号拒绝，原结构继续与 append-only 消费回执同一 PG 条件事务；旧请求重放不确认下一 gate。实际 Worker 更换、提交后重试、队列竞争、浏览器 GET/POST 竞争与固定 exweb/MinIO 的分开证据见实施记录。它不替代所有生命周期的 CAS/owner fencing、治理 admission/dispatch、事实/审计/Outbox 同事务、OS 强杀或本表 P0-P6 完整退出条件。

同一增量补齐聊天确认的明确 goal 查询和恢复 port：服务器先固定确切待确认 invocation/blocked step 与当前 scope，再传递五字段检查点；错目标、过时工具或驱动前预算变化拒绝。真实公共 Turn 与 exweb 原目标聊天确认的证据见实施记录。这不是用户所见 DTO 的聊天协议切换、全治理事务或完整自然语言引导，不能以旧 bodyless 兼容绕过固定画像入口。

2026-10-07 的[固定来源文件差异](./source-deltas.md)开始推进 P4：同 binding 双修订、采集范围证明、完整 hash/分页和重新授权 canonical 观察已实现；实际 exweb 相邻提交用于验证。delta DAG、跨域失效、实体 lineage、overlay/合并与本表退出条件仍未完成，不以文件比较替代完整增量维护。

2026-10-08 新增[固定画像代码成员比较](./code-member-deltas.md)，在完整固定成员上按 Nasus 身份匹配五类变化，并接入 HTTP、canonical 回执和显式 Portal 版本比较。实际 exweb 两 Provider 的受控代码变化有独立 PG/MinIO 验证；公开 HTTP/Tool 与浏览器使用不同范围的静态仓库夹具。画像成员移出不是代码删除、实体修订不同不是业务行为改变；该基础不执行自动失效、重建或发布，不替代完整 P4 退出条件与本目标的全量验证。

随后新增[固定上下文影响预览](./context-change-impact.md)，读取质量域验证后的 context 派生依赖图，固定 canonical 查询 inventory 并保守考虑新增文件对空查询的影响。它仅完成已有工件的有界追溯，不写跨域 stale，不替代 P4 的完整 delta DAG、持久失效、增量重建或容量/性能门禁。

0067 增加独立确认的[持久上下文失效](./context-invalidation.md)，保存完整有界节点/边并阻断该精确画像下新旧上下文的当前使用；其他画像不继承，历史工件和批准不改写。它是 P4 的持久门禁进展，不替代全项目 Derivation 索引、自动刷新、增量重建、overlay/合并与本表完整退出条件。

[来源修订反查](./source-context-roots.md)补齐 source → 多画像 ContextPack 的发现入口，计数前过滤完整来源访问权，回执固定原页及权限范围。该分页查询不等于原子项目快照或完整派生图；继续要求全项目 negative/query-scope 依赖、增量更新、容量/性能和本表 P4 退出条件，不以单项 exweb 反查通过替代。

0068 的[派生依赖登记](./derivation-registry.md)将现有新测试设计事实及完整来源查询范围持久化，并接入两个 inventory 的缺项检查。迁移回填和事务登记属于项目级索引底座；完整实体／断言／authority／脚本／RunPlan DAG、原子项目失效、自动增量和本表 P4 退出条件继续保留。

0070 的[画像对象来源子图](./object-provenance.md)补齐被准入对象的来源、实体、文档父子和冻结证据祖先，并提供原子回填及读取验证。它与 0068 通过固定 image ID/hash 衔接，不替代完整统一派生图；编译局部只读快照及池隔离的专项也不能作为 p95、容量或本表 P4/P6 退出证明。

0071 新增[上下文来源锚点](./context-provenance.md)，将 context registration 与 image_objects 根及完整 query scope 以固定 hash 同事务连接。既有两类 v1 登记不改写；完整语义、authority、检索、脚本/RunPlan 依赖及本表 P4/P6 退出条件继续待交付。

0072 的[冻结关联来源追溯](./relation-provenance.md)将已选定的 references／semantic 成员、双方证据、原评估和完整决定前驱接入独立来源子图及 ContextPack 锚点，不重写旧登记。未冻结关系、authority、publication、检索和执行依赖仍未完整登记；本表 P0-P6 退出条件不缩减。

0073 进一步登记未被画像选定的已提交候选、语义评估和完整审阅历史。候选复用及已提交命令恢复先核验原登记，事件投影以持久命令关联而非 SSE 保留期判断复用，不能借普通新写入补造坏历史。完整统一 authority／publication／检索／执行依赖和自动项目 delta 继续待交付；本表 P0-P6 退出条件不因该完整性修复缩减。

0074 连接规范事实到固定对象来源，0075 的[上下文规范依赖](./context-authority-dependencies.md)进一步登记新归档的确切 AC／规则 pins。旧归档需要独立授权回读后登记，不以当前批准头补造历史。该增量仍不替代统一 publication／检索／脚本／RunPlan DAG、完整原子 delta、自动维护或本表 P0-P6 退出条件。

0076 增加[历史知识画像回滚](./image-rollback.md)：同项目/基线的历史 publication 固定 pin、独立确认与批准、当前 head CAS 和追加式审计/Outbox。它只恢复知识读取头，source/工作草稿和业务批准不回退；自动维护、统一派生图、overlay/三方合并及本表 P0-P6 完整退出条件继续保留。

0077 增加[发布与上下文依赖登记](./publication-provenance.md)，将原生发布/审阅/前驱/回滚源和 v4/v5 ContextPack 以确切 hash 连接对象与关联来源根。原事务登记、历史回填及只读核验不改写旧事实；操作级快照不缓存当前启用头或权限。完整检索/脚本/RunPlan 依赖、统一项目 delta、自动维护和本表 P0-P6 退出条件不因该增量缩减。

0078 的[固定检索来源依赖](./retrieval-provenance.md)登记完整索引成员和确切 trace/context 绑定，并覆盖普通读取、恢复和两条原生 trace 事务。它不替代独立 chunk、query-plan/call/batch/LLMCall、脚本/RunPlan 的完整来源链；原子项目 delta、自动更新、五用途/旧链切换、真实执行与本表全部退出条件继续保留。

2026-10-08 的[CodeGraph 公开 SDK 对照](./codegraph-provider-comparison.md)补充固定 1.6.2／完整运行资产 pin、私有 npm 布局副本、两个原生 Provider 的同源结构报告，以及实际两项目隔离／取消和两文档提交的 PG／MinIO 历史证据。后续 SDK session／版本化真实 SDK receipt 已接入显式 composition、共享 PG durable generation 和 canonical 结构构建；完整分页、新实例重建、公开私有权限与浏览器协议兼容分开验证，默认 Provider 不变。原始 CBM import 不稳定反例仍保留；两个真实提交不含代码 rename/delete，具体 Workflow 证据见实施记录，不能从关闭重建推断完整进程恢复。该增量推进 P0，但不替代独立 gold、多语言／代码变更语料、强隔离／供应链／性能、可上线选型或本表全部 P0-P6 退出条件。

2026-10-10 的[原目标环境只读核验](./native-target-environment.md)接入原 RunPlan/构建 application ports 和运维私有登记，实际检查容器身份、原 JAR、非 root 用户、挂载、选定隔离配置及网络成员。固定 exweb 的真实 Docker 运行复用生产 inspector；普通回执和 Agent 历史读取重新授权但不重新操作 Docker，损坏的已授权历史不能伪装为空列表。它仍不是独立持久环境事实、物理出网/宿主拒绝、fixture/locator、独立执行许可或真实业务覆盖的完成证明；五用途、旧链切换以及本表 P0-P6 退出条件保持完整。

0105 另增[原目标环境的独立归档登记](./native-environment-records.md)，通过单独确认的 canonical command 从生产原生 port 获取完整 inventory，固定原计划/构建/画像/清单祖先，追加 PG 事实及同事务审计/Outbox。私有历史读取先重新授权，再核验完整原工件；原查询不静默写入或升级权威。该阶段的持久观察不替代实际部署、物理拒绝、依赖健康、fixture/locator、执行授权、durable dispatch/cancel/recovery 或正式覆盖回流，完整验收范围不缩减。

## 3. 代码落点与拆分范围

2026-10-11 的[固定源码 HTTP 定位](./http-locator-evidence.md)将原计划完整 request 清单与确切归档字节、方法/类级路由证据连接。只读 HTTP/canonical query、元数据 Agent/SSE、原存储观察回放及 Portal 折叠检查已接线；实际 PG/MinIO、固定 exweb 与 UI 协议夹具分开取证，终态见实施记录。它不新增独立 locator 事实，不验证运行时 dispatch/DOM、fixture、执行授权或真实覆盖，完整 P0-P6 退出条件保持不变。

0107 后续增加独立确认的 locator 归档：追加式 PG/私有 MinIO、原计划复合外键、事实/审计/Outbox 同事务和完整原来源字节/跨度重验。旧查询/计划不升级，历史不再解析；canonical 工具、私有 HTTP 与默认折叠的独立登记 Portal 已组装。面板校验确切原命令/请求/完整归档，失联与刷新只读恢复，不自动重发/确认，撤权或损坏隐藏父链；原生存储、固定 exweb 和浏览器协议夹具的终态分别见实施记录。这个持久静态证据增量不验证 runtime/DOM、fixture、执行授权或业务覆盖，也不替代本表完整 P0-P6 与 V1 门禁。

2026-10-09 的[显式 Git 分支／标签绑定](./source-tracking.md)补齐 P1 中 nullable tracked_ref 身份，0093、实际 Git fetch 和固定 exweb 全量字节回放分别取证；缺 ref 不回落默认分支，历史版本不按最新 head 改写。同日[来源刷新恢复指针](./source-refresh.md#portal-操作与失联恢复)保存同账号／项目的原请求，不自动重发，终态后仍显式重新选择。它们不替代跨进程采集 lease/intent、webhook/reconcile、自动 delta/overlay/合并、全计划预算、五用途上下文或本表完整 P0-P6 退出条件。

建议沿现有 DDD 目录新增小型 use cases，不再在 `SystemImageService` 添加所有逻辑：

| 位置 | 责任 |
| --- | --- |
| application/system_image/source_snapshots | capture/diff/manifest，多来源与幂等 |
| application/system_image/builds | 调用 Agent goal 的 build facade、工件与缺口评估 |
| application/system_image/assertions | 候选抽取、关联裁决、人工纠正 |
| application/system_image/revisions | overlay 解析、晋级、失效事件 |
| application/system_image/context_packs | 按用途编译和校验；不生成质量域正式用例 |
| domain/system_image | identity、assertion、readiness、revision/merge 和 scope policy |
| infrastructure/system_image | 已有 CBM/Tree-sitter/composite 适配器演进，另加 document/test adapter |
| infrastructure/persistence | 独立 repository + UoW，PG 约束、Outbox 和读模型 |
| domains/system-image + routes/knowledge/project-overview | 构建引导/进度、证据检查、gap 和修订比较；消费 view model |

保留 `application/agent/plans.py` 作为通用调度契约消费者，画像领域规则不继续堆入 Agent graph。`SystemImageService` 在迁移期只委派，最终旧模型作为兼容 DTO，不能再成为跨领域主状态容器。

## 4. 迁移与回退

1. **Expand**：新增表和 nullable revision 引用，不删除旧字段；给现有 source 分配 binding。旧记录有可靠 commit/hash 才生成 verified revision，否则 `legacy_unverified`，禁止伪造准确版本。
2. **Backfill**：基于保留的原料重建 SourceManifest/实体映射，提供 old_id->new_id alias；迁移不重写已存消息/ToolInvocation/Run 的证据，旧引用仍能解析或明确标 legacy。
3. **Shadow**：同源同 revision 运行新模型并比较对象、关系、ACL、旧 API 形状和上下文；只读影子结果，不让新旧管线同时推进 official head。
4. **Cutover**：按项目 feature flag 切换新事实源、冻结该项目旧写路径；兼容 façade 输出旧 read model。不能让 `register_sources`/materialize 的全量清除作用在新历史修订表。
5. **Contract**：真实试点、回滚演练和兼容期完成后才移除无调用方旧逻辑。旧 ID alias 和审计链接按保留策略保留，不为“代码干净”破坏回放。

迁移后只有一个 write authority。回退 provider 可以重建投影，不回退画像 schema；若需回退业务读路径只能回到经过验证的旧快照并禁止旧写破坏新事实。不能把新多源/多版本数据压回旧的“每类型一个 source”后继续双向写。发布前做 PG + MinIO 一致性备份和恢复 rehearsal。

## 5. 评估语料与实验方法

建立版本化 `system-image-eval` fixture，至少覆盖：

- Python API、TypeScript 前端、Java/Go 服务四类实际语言；关键能力对不支持语言必须报告 unsupported，而非默默输出空图。
- 小型可人工穷举仓库、多仓库支付链、含动态路由/消息/权限的中等仓库、历史脚本/fixture/表格测试数据。
- 至少三个 commit：原始、rename/delete/规则变更、并行分支合并；包含 force-push、迟到文档、重复 webhook、权限撤销。
- code-only、code+US、code+test、三源齐全、可选源失败、必需代码失败六类接入组合。
- 至少 300 条人工标注跨源候选对，其中至少 100 条是同名不同义、相似但不相关、中文/英文别名、无 oracle、过期版本等负例。
- 至少 30 个真实目标问题和 20 个 US 变更任务；其中至少 10 个涉及关键权限/幂等/时间边界。样本量不足的指标只能报告探索结果。

由业务/QA 与开发双人独立标注实体定位、implements/asserts、必测风险和预期断言，分歧仲裁并保留理由。按仓库和时间切分 calibration/test，禁止同一 US 的轻微改写同时出现在训练和验收集合。语料需获授权且脱敏。

对照组：当前名称相似度 + 当前检索；候选 A：新上下文契约 + CBM；候选 B：同契约 + CodeGraph。固定模型配置、token/time budget、工具白名单和源 revision，每题至少三次，报告分布、错误案例和成本；不只选最佳一轮。无需把全部 fixture 代码发给第三方模型，遵守项目数据出口策略。

## 6. 质量与性能门禁

下面数值是待验证的初始验收目标，不是已测性能；变更必须附依据及审批，不能测试失败后为通过而静默降低。

| 指标 | 目标 | 测量方式 |
| --- | --- | --- |
| 引用正确率 | 准入事实/规则的证据可定位且 hash 匹配 100% | 对每条 accepted 边和 mandatory constraint 回读固定快照 |
| 结构定位 | 支持语言关键入口精确定位 100%，普通符号 >=98% | gold symbol/route spans；approximate 不计精确命中 |
| 跨源 accepted 精度 | 自动接受关系的 95% 置信区间下界 >=0.95；独立测试 accepted 样本至少 200 | 关系类型分别统计，不足样本则只人工审阅，不允许宣称校准完成 |
| 关键关系召回 | 关键 AC 的相关代码/有效用例候选 recall@30 >=0.95 | gold edges；明确报告 unsupported 和 no-match |
| 下游完备性 | mandatory AC/风险包含率 100%，错误 oracle 晋级数 0 | 对 ContextPack 与生成工件做引用和规则核对 |
| 脚本质量 | 至少 20 个任务的适用脚本在授权环境 collect/编译 100%；目标断言执行成功率 >=90% | 编译/收集不算测试通过；业务真缺陷单独分类，不能删掉失败样本 |
| 变更保护 | gold impact 集中的关键回归漏选数 0 | 变更 oracle 与选中 TestCase 集合比对，不只看测试文件 |
| 权限/版本隔离 | 跨项目/不可见/错误 revision 泄漏数 0 | 向量/图/缓存/模型输入/对象下载五层负测 |
| Agent 完成诚实性 | 必需证据缺失却标完成数 0；无进展能在三次内暂停 | 注入缺源、工具空结果、重复调查、provider 错误 |
| 复用价值 | 在相同预算下，不劣于对照的关键召回/漏测指标，且审阅修正量或无关上下文 token 至少改善 20% | 预注册指标，三次重复和置信区间；样本不足不做优势结论 |

性能建议基准环境：8 vCPU/16GB RAM 的 Linux worker，PostgreSQL/MinIO 同区；冷/热缓存分开，供应商/模型/数据尺寸固定。建议中型 10k 文件仓库结构候选 <=5 分钟，1% 文件变化更新 <=60 秒；模型业务认知单独报告费用和 wall time，不能计入“毫秒索引”宣传。

非模型 context query（含授权与索引）p95 <=2 秒，模型 rerank/语义编译端到端 p95 另报；构建 POST p95 <1 秒返回 accepted，进度事件提交后 p95 <2 秒可见。每 worker 默认同时一个索引任务、语义子任务最多三路，项目限额/排队透明；超内存/超输出退出为失败或 partial，不把数据截断标 completed。

## 7. 关键自动化测试矩阵

| 层级 | 必测情形 |
| --- | --- |
| Domain | ID rename/split/merge、重复名、typed edge、observed/expected 冲突、tombstone、readiness 与未校准分数 |
| Application | code-only、可选失败不阻断结构基线、多 source、目标暂停/恢复、调查新增/收敛、预算、三次无进展、计划越权 |
| Infrastructure | 真实 provider/PG/MinIO，分页边界/空页/schema 改变、approximate 定位、不同 revision 缓存、解析器失败/取消、输出上限 |
| Persistence | 同 key 重试、过期 worker fencing、事务后 Outbox 失败恢复、S3 成功 PG 失败 orphan GC、重复事件、并发 CAS |
| Versioning | 固定父基线、关系删除、人工否定保留、两版本同时更新、force-push/漏 webhook、语义/向量模型升级、迟到 run |
| Context | mandatory 项超预算、空召回/新增节点、候选不充当 oracle、负向边、失效包、环境不匹配、ACL epoch、token 拆包 |
| End-to-end | 引导/聊天/事件入口统一 ToolInvocation；补源恢复同 goal；点击证据；审阅发布；退款三源全流程；失败阻断放行 |
| UI | Light/Dark/Mobile、原 shared composer/sidebar/settings 不回退；SSE 重连/刷新恢复；进度分母增长有说明；键盘审阅和错误态 |

故障注入至少在 snapshot、index、semantic link、candidate commit、publish 后五个点 kill worker，恢复不得重复发布/丢掉已验证工件。跑完测试要核查持久化记录和最终可读状态，不能只断言 HTTP 200。

## 8. 回归命令与试点

每阶段在隔离测试 PG/S3 namespace 下执行既有门禁（实际脚本版本以工作区为准）：

```bash
npm run build:portal
npm run lint:portal
npm run test:portal-boundaries
./.venv/bin/python -m pytest apps/api/tests/test_api.py apps/api/tests/test_runtime_config.py tests/test_docker_stack_contract.py tests/test_ddd_boundaries.py -q
npm run test:e2e
npm run test:smoke
```

P0/P1 追加真实 `npm run verify:code-graph-provider` 与新增 contract 测试；最终执行 `npm run verify:v1-release`，不能用单元测试替代真实 provider 或备份恢复验证。测试记录隔离资源配置、commit、依赖版本和工件 digest，不污染用户项目/模型设置。

真实试点必须由用户授权一个仓库和测试环境，选择一个实际版本变更：引导/自然语言建画像 -> 补需求/测试 -> 人工校正关系 -> 生成 US/AC 和用例 -> 可审阅脚本 -> 受控执行 -> 失败或成功有证据 -> 新 revision 晋级 -> 下一迭代增量更新。涉及生产环境或数据写入仍独立审批，设计完成不等于获得执行授权。

## 9. 运维与安全完成条件

日志/指标按 project/build/work_item/manifest/invocation 可串联；展示 freshness lag、待索引数、stale context 数、link 审阅数、重复/无进展率、模型成本、provider 失败/截断、Outbox 延迟。严重错误通知管理员，持续维护无变化时不通知用户。

安全用例覆盖仓库 prompt injection、恶意文档/压缩炸弹、symlink/路径逃逸、凭据出现在 URI、SSRF/重定向/DNS 重绑定、仓库 hooks/依赖安装、私有 source ACL 变化、模型出网、巨型 provider 输出。只解析已获授权的快照，不为了代码知识检索启动未知项目服务。

灾难演练从 PG+MinIO 备份重建 code/vector/summary 投影，恢复历史 ContextPack 和 Official head；provider 不可用时仍能看已准入事实/证据和明确降级状态。旧 snapshot 的证据被保留政策删除时必须显示缺失，不能继续宣称可审计完整。

## 10. 本轮设计完成审计

本节审核的是用户要求的**开发方案是否具备指导性**，不是上述实施阶段已经完成。所有运行/精度门禁仍需后续实现取证。

| 用户要求 | 设计证据 | 验证方式 |
| --- | --- | --- |
| 先完善方案，不急实现 | 四份设计文档；本轮只修改文档 | 检查本轮 diff，不改业务源代码/配置 |
| AI 自主规划构建 | 主方案 §4-5，BuildIntent/InvestigationPlan、动态调查、预算、恢复和停止门禁 | 对照 code-only 与退款示例，不是仅固定注册/摄入四步 |
| 引导式或用户自主发起 | 主方案 §4 三入口、澄清与授权 envelope | 引导/聊天同 goal，同 ToolRuntime，缺失信息有补充路径 |
| 随迭代版本丰富/滚动升级 | 主方案 §6；知识契约 §4 | 初始化、补源、delta、并行分支、合并/删除/回滚均定义 |
| 指导 US 设计 | 主方案 §7-8；契约 §5 us_design | 现状与期望分开、AC 来源、未知规则需确认 |
| 指导测试用例设计 | 契约 §3、§5 test_design/CoverageMatrix | oracle、强制风险、断言映射和分母明确 |
| 指导脚本编写与运行 | 契约 §5 automation/execution；本文件 §7-8 | 真实入口/fixture、版本/环境 pin、运行安全及证据回流 |
| 参考合适 Agent 增强方案 | 开源评估 §2-6 | 第一方资料、固定研究 commit、适用性/限制和 PoC 门禁 |
| 复用开源且保留防腐层 | 契约 §3.1、§6；开源评估 §3、§5 | 自有身份/证据不依赖供应商 DB，替换需实测身份/关联稳定 |
| 代码必需、需求/测试可选且可关联 | 主方案 §3、§6；契约 §2-3 | 多 binding、code-only 不编造 oracle、后补关系不覆盖历史 |
| 可落地、高质量 | 本文件 §2-9 | 有代码落点、迁移/回退、gold 语料、指标、失败路径、试点闭环 |

不阻塞设计的后续参数：真实试点仓库及语言规模、质量负责人、允许的数据出口、每项目费用预算、保留周期和正式 provider release。默认值和权限边界已给出；拿到这些参数后校准计划与容量，不重新定义系统画像的核心语义。

### 本轮校验记录

2026-09-09：逐项阅读并核对上表要求与设计正文；一次性 Node 校验覆盖本目录与入口/产品需求共 12 份文档的 122 个本地链接（含章节锚点）、1 个 JSON 示例及代码围栏，未发现错误；新增文档无行尾空格，`git diff --check -- docs` 通过。外部选型依据来自官方页面及固定 commit 的 README/LICENSE/Telemetry 文件。

本轮仅完成设计交付与文档一致性校验，未运行业务回归、provider benchmark、数据迁移或真实试点；不能据此宣布新系统画像功能或上线门禁已完成。
