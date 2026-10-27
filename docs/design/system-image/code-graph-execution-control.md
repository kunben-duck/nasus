# 代码图执行控制与完整性边界

更新：2026-10-08。此契约说明现有 CBM 适配器的受控执行、快照隔离、关系读取及证据准入。它是 Provider v2 的实施基础，不替代[完整 P0-P6 退出条件](./delivery-and-evaluation.md)。

## 业务权威与进程控制

`ControlledCodeIntelligencePort` 扩展原 `analyze`，由 application 传入 `check_current`。结构构建继续以原 ToolInvocation、AgentGoal、固定来源范围及确认预算为权威；供应商不创建另一套业务状态。

应用在来源读取及各分析阶段复核，CLI transport 每约 250ms 复核当前来源策略、取消和 wall budget。复制/校验文件的运行期轮询按同样间隔合并，阶段前后仍强制复核。轮询间隔不是事务锁，也不保证权限变更零延迟；后续提交仍经过既有应用事务校验。

`CodeGraphProcessRunner` 使用私有进程组、有限 stdout/stderr、单次有限 wall timeout；普通 CLI 使用无输入管道，0080 的 MCP 协商使用有界非阻塞输入。两条输出管道关闭后仍检查未退出进程。正常结束、供应商错误、应用控制异常和 `KeyboardInterrupt` 都关闭管道并终止、回收所属进程组。应用控制异常原样传播，不被 optional enrichment 当作可忽略的供应商故障。

该控制仅针对所属进程组。逃逸进程组的 detached 子进程、独立服务账号、禁网、CPU/内存限制和内核不可中断任务的有界回收仍需完整 Worker 隔离方案。当前 `process.wait()` 的最终回收不是这些要求的完成证明。

## 已准备的 Worker 索引会话

`PreparedCodeIndexFactoryPort.open_index` 返回 `PreparedCodeIndexPort`，当前 CBM 实现的生命周期明确为 `worker_owned_session`。它与永久业务任务、PG 分析报告 ID 和持久原生 index handle 不同。固定批准文件列表、原始 hash/byte count 产生 snapshot hash；随机 `cidx_*` 仅标识本次会话，不是 Nasus 代码实体身份或访问授权。

会话先处于 pending，`prepare_index` 真正创建私有来源/缓存并调用原生 `index_repository`，随后 ready/degraded。重复 prepare 只校验原输入与私有快照，不重复建索引；失败、取消或 closed 不允许重开。尚未读取结果时计数为 null，不能把“准备好了”表述为图已完整或实体数为零。closed 释放来源、原生缓存和已读取的内存投影；上下文失败和 KeyboardInterrupt 同样清理。Worker 崩溃后的恢复和清扫仍需持久登记与受隔离 Worker，当前会话不能跨重启恢复。

首次结果读取调用同一个真实原生索引，之后各页复用冻结的规范化候选集合，不伪称每页都执行供应商分页。`entities/relations` 返回有界页、normalized_count、原读取完整性和全部 typed gap；游标以会话密钥绑定 index ID、集合和全量规范化 digest，跨会话、跨集合及篡改游标拒绝，错误范围在原生查询前拒绝。单页最多 min(1000, provider page_size) 项、256 KiB；该数量只描述已读取候选，不是未知的原生全量计数。

`locate` 保留 exact/approximate，不新增精确性保证。`impact` 是 Nasus 对这些候选的保守静态遍历，不冒充原生 impact：归属边的 member -> owner 方向与调用/依赖/暴露边分别处理，固定 seed、hops 和数量上限；保留所有原读取 gap，始终 `complete=false`，超过层数或数量另标 truncated。返回 candidate IDs，不能被 Agent 当作已登记的 `CODE-<entity_id>` 或正式变更范围。

`cancel` 有独立线程安全信号，准备或读取中的检查进入原 CLI runner，并终止所属进程组；排队等待 Provider 锁时也检查。取消返回 cancellation_requested，运行方确认后 cancelled；它不绕开原 ToolInvocation/AgentGoal 取消权威，也不代表跨 Worker 持久取消。每次状态/能力/读/取消都复查 application callback，缓存不能代替即时授权；close 的清理不依赖已经撤销的权限。

原 `analyze/analyze_controlled` 已通过此真实会话执行再关闭，公开 API/Tool 与冻结工件契约不变。原适配器能力仍只声明三个兼容操作；上述八个操作仅由实际 PreparedCodeIndexPort 声明，不把声明当作原生功能协商。后续 0080 的实际原生契约探测独立记录，范围如下。

## PG 持久登记与重建恢复（0079）

`CodeIndexGenerationApplicationService` 现以 PG `cgen_*` 固定 project/binding/SourceRevision、来源 manifest、文本单元 snapshot hash、实际原生可执行文件/适配实现/grammar 版本/投影策略摘要及原 canonical invocation。它不是分析报告 ID，也不把原生 SQLite 上传为业务数据库。`code_index_generations`、`code_index_worker_attempts` 和首次 `code_index_projection_pins` 追加式保存；可变租约单独存于 `code_index_worker_leases`，所有状态回执与相应写入在同一 PG/Outbox 事务中。

租约由 PG 时钟判断，生产有效期 45 秒，每次执行 callback 复查并续约。claim 使用行锁并递增 epoch，活跃 owner 不允许另一 Worker 抢占；过期后新 owner 可恢复，旧 epoch 不得查询、登记结果或释放新租约。取消请求写入 PG，所属原生进程的 callback 会收到 `CodeIndexCancelled` 并回收进程组；正常 close 将 lease 回到 idle，明确取消为 cancelled。查询参数/旧游标错误不把正常 native cache 误报 failed，真实 Provider/投影/授权控制错误继续阻断。

恢复先重新授权，回读固定来源记录，从原归档恢复字节并核对 snapshot hash，再以固定 generation namespace 构建新的私有原生索引。原 `cidx_*`、分页密钥和游标不能跨 epoch 复用，客户端必须重新分页。首次完整规范化候选及 Provider 观察摘要在 PG 固定；重建后 hash、数量或版本不同就拒绝返回，不能在同一 `cgen_*` 下替换结果。原生可执行文件必须已安装：已知 Python 下载启动器被解析为其现有原生文件直接执行，缺文件不自动联网下载。

该路径已注入带 invocation 和实时 `check_phase` 的确认式 `system_image.build.structure`，保留原 ToolInvocation、确认、来源 ACL、目标、预算及 candidate commit 校验。兼容 materialize/initialize 中没有实时 callback 的旧入口仍使用原会话，不给它们补造持久授权。0079 初始只提供内部 `reopen/cancel`；同日新增的公开发现/状态/取消见下节。公开 reopen 和 Temporal/Agent 自动发现并接续所有失联索引仍未交付。

真实恢复暴露 Provider 搜索顺序和 Java `IMPORTS` 误映射：现固定实体顺序；同 qualified-name/file 对应多个不同候选时不再选择最后一项，端点保持 ambiguous/gap。持久原生候选在首读时消费已有语法 import/package/声明复核，避免库函数同名误映射随索引顺序改变。它仍是 partial 的候选投影，不是业务知识批准或独立定位 gold。

当前测试包括真实 PG 并发 claim、过期 fencing、跨实例取消及实际协议子进程回收、实际 OS Worker kill 后新进程恢复、投影分歧拒绝、原子回执与真实 HTTP 确认式构建。OS kill 专项使用三秒测试租约，生产仍为 45 秒；该协议夹具不等于真实 CBM 进程中断 gold。固定 exweb 原生恢复使用同一 PG generation、两个不同恢复目录、两次实际 index_repository，完整投影相等并拒绝旧游标；具体计数/摘要和各批终态见[实施记录](./implementation-progress.md)。

尚未完成：强杀遗留临时目录/逃逸子进程的可靠清扫、完整业务 Workflow 自动恢复与公开 reopen、跨主机完整 Provider/build 依赖锁定、原生语言/结果完整性验证、账号/禁网/CPU/内存隔离、大规模/性能与独立 gold。这里完成的是持久 projection 身份与重建/fencing 底座，不是完整 P0 或 P0-P6 交付。

## Worker 可执行文件固定

仅在命令前后读取安装文件摘要，不能证明命令实际执行了相同字节：安装文件可能在两次检查之间更新，再恢复原样。持久会话现在接收原 PG generation 的 `provider_fingerprint`，在启动任何原生命令前，将已安装原生文件复制到 Worker 私有 `nasus-cbm-exec-*` 目录，核验副本的完整投影指纹。版本探测、MCP 协商、建索引及所有后续查询使用同一副本；不能在会话中回到安装路径。副本不匹配时拒绝执行，不登记协议或投影结果。恢复仍重新授权，并验证原 generation、协议和投影，不借新副本更换旧输入。

文件通过 `O_NOFOLLOW / O_NONBLOCK` 打开，先检查 fd 对应普通文件、可执行权限及非空有界大小，再创建字节流；目录、FIFO、符号链接和不可执行文件拒绝。摘要与复制仍逐个 1 MiB 分块读取、完整计算所有字节的 SHA-256；授权、取消和预算在开始/结束强制复核，读取中按 50ms 调度间隔复核，而不是每块触发整套 PG 查询。每次读取有自己的调度器，不复用旧授权或缓存指纹；检查延迟包含当前分块 IO 和检查本身耗时，不承诺零延迟撤权。控制异常原样传播。

结束授权检查后核对原 fd 的 device/inode/mode/size/mtime/ctime，并用安装路径 `lstat` 核对同一签名；同长度改写或路径替换亦拒绝。私有目标以独占创建方式写入，完整复制并核验后才设置 `0500`，不使用硬链接；成功、错误、取消及上下文中断均由会话清理所属副本。尚未创建流时的文件检查失败也关闭 fd。文件上限为 512 MiB，当前已安装原生文件实测 269,460,400 字节；超界拒绝，不自动下载或换版本。此核验不是同账号攻击者或完整 OS 隔离保证。

`code_graph_executable.py` 纳入既有投影策略摘要，实际代码变更会使旧指纹不再匹配。旧 generation、协议记录和已冻结画像不迁移或改写；不匹配的旧执行命令不能重试成新策略，需新的独立确认。未带 durable namespace 的兼容会话仍未接入这一固定契约，不能将新保障宣称为旧链全部切换。

这固定的是执行文件身份，不是签名 release、完整传递依赖锁定、独立账号、内核禁网或 CPU/内存隔离。同账号仍有篡改风险，进程强杀后的孤立目录清扫也尚未完成；P0 的完整隔离、gold、Provider 对照与性能门禁继续保留。协议子进程故障测试、真实 PG 重建和私有 MinIO 构建验证各自的范围见[实施记录](./implementation-progress.md)。

## 投影源码与已安装依赖字节指纹

2026-10-08 的新指纹输入采用 `nasus.code-index-generation.v2`，不修改 PG generation 记录的原结构或历史 hash。除了实际原生执行文件和投影配置，还纳入 `nasus.code-projection-dependencies.v1`：从原生适配器、组合/语法适配器及身份登记入口，静态遍历本地 Python import 和父包 initializer，计算每份源码内容摘要。函数内 import 同样遍历；扫描不 import 或执行这些文件，也不执行目标仓库代码。

外部模块通过已安装 distribution 的文件清单确定唯一所有者，递归解析当前环境适用的 `Requires-Dist`、版本约束及 extras。清单文件使用实际字节 hash，而不是只相信版本号或 RECORD 内声明的 hash；同版本 grammar/native extension 内容变化也改变指纹。相同模块的多所有者、缺失依赖/清单文件、非法路径、符号链接、非普通文件、超界或读取期间变更都拒绝。未由本适配器执行的外部 console entrypoint 明确排除并计数；原生可执行文件继续使用上一节的独立固定策略。

每份依赖文件最多 64 MiB，本地源码解析最多 2 MiB，完整读取最多 512 MiB/65536 个文件；本地模块最多 2048 个，选择的传递 distribution 最多 256 个，全部 metadata 探索同样有独立上限。读取以 1 MiB 分块，最后复查已打开文件的 inode/size/mtime/ctime；不完整时不返回可用指纹。依赖扫描约每 50ms 检查当前 application 权限、取消及预算，阶段结束强制复查；控制异常原样传播，不能被 metadata IO 错误包装成 optional Provider 降级。

Application 的首次登记、恢复及 leased 准备/首次读取显式传入实时 callback。实际执行副本仍核验完整指纹；同命令不能因依赖更新而替换原 generation，需要新的独立确认。旧画像、协议、投影和原归档只读保持不变，不因新版本自动回填或重授业务批准。

该清单的范围仅为静态源码 import 闭包和已安装清单声明的适用传递依赖。未声明文件、计算式动态 import、已加载 Python 对象、stdlib 字节、OS/shared-library loader、签名 release 及整个可执行环境并未固定，不能把它称为 hermetic runtime 或完整 P0 依赖锁定。它也不解析 exweb 的运行时依赖；完整隔离、跨主机重现、Provider 对照、独立 gold 与性能验收继续属于原目标。

## 公开生命周期与当前来源权限

`CodeIndexLifecycleApplicationService` 通过持久 repository port 提供三个自有工具，不直接访问原生索引：

- `query.system_image.code_indexes.list`：精确 project/binding 的 generation 列表，有界 keyset 分页；不同来源修订分别保留，不选最新修订覆盖旧 pin。
- `query.system_image.code_indexes.status`：当前 PG 元数据，固定 generation/source/snapshot/provider/原 invocation；独立显示原命令状态、native state、Worker epoch/active/expired 和观察时间。不 claim/续租，不把未知投影计数表示为零，不把 native ready 表示为结构候选已提交。
- `system_image.code_indexes.cancel`：独立 reviewer 命令，须经 Runtime 确认，并携带确切 generation hash；客户端自报确认字段被丢弃。

两个只读 GET 为 `/v1/projects/{project_id}/system-image/code-indexes?binding_id=...` 和其 `/{generation_id}` 状态入口，返回 `Cache-Control: private, no-store`。每次读取复核当前 project/source scope；过期范围、错误 pin、损坏 receipt 或跨项目均拒绝。当前 `can_cancel` 仅用于界面，实际写仍再次校验角色/来源/hash；旧 ToolResult 无此字段时默认 false，不补造过去或当前授权。

取消与结构候选提交共享项目 advisory lock 和原命令行锁。取消命令必须为独立的 running、已确认 canonical invocation；不能用原结构命令或伪造角色来授权。活跃 owner 写入 `cancel_requested`，其回调确认后回收所属进程组并落到 `cancelled`；无 owner 或过期 owner 可直接 cancelled。候选提交在同一锁范围拒绝 cancelled/cancel_requested generation。已提交返回 `already_committed`，原命令已终止返回 `already_terminal`，两者保留原画像/索引事实。取消事实、lease 和 Outbox 同事务，重复取消不重复事件；这不保证脱离进程组的强杀清扫。

来源权限也适用于保存的 lifecycle ToolInvocation、审计、幂等回放和 Agent 读取。平台资源策略按当前 actor 重新授权精确三类工具，不以创建者、项目管理员或旧 role 绕过私有 source ACL。共享 Conversation/Outbox 只投影去除完整输入、result、幂等字段的状态副本；历史事件返回同样脱敏副本，不修改存储事实。Tool 创建/确认在返回前再次检查，不能因为已完成就向已撤权用户返回完整 receipt。

Runtime 在 claim 待确认命令之前做角色与回放权限检查；无权确认返回 403，不消费或改写别人等待中的命令。执行阶段仍再次授权，以阻断检查后降权。取消独立控制索引 Worker，不授予业务语义、发布或测试执行 authority。

Portal 在已有来源分析面板按需展开历史，十项分页和固定 generation 详情，沿用 shared 细边框/主题/隐藏滚动条。刷新隐藏受保护详情但保持选择；授权失败清空旧内容。取消 checkbox 固定 pin/epoch/本次查询结果，刷新和输入变化后失效；发送前重新获取状态，scope/epoch/权限变化禁止发送，canonical 写入和确认不自动重试。`cancel_requested` 只轮询 PG 等待确认；状态查询不触发 Provider。

实际 PG/HTTP、原生 exweb 和浏览器协议状态测试分开记录于[实施进度](./implementation-progress.md#公开代码索引生命周期与-portal2026-10-07)。浏览器 fixture 的 native-not-executed 状态不充当原生索引验证。公开 reopen、Temporal/Agent 全业务恢复、原生完整性/隔离/对照/gold 与性能仍需完成。

## 原生工具契约协商（0080）

持久索引在实际 `index_repository` 之前执行一次原生 MCP `initialize`，收到响应后才发送 `notifications/initialized` 与 `tools/list`，按原生 cursor 读取工具清单。不执行供应商工具、安装/更新或服务器返回的说明。最多八页、128 个工具、64 条日志通知；输入累计 128 KiB，stdout 512 KiB、stderr 64 KiB，wall timeout 不超过五秒，沿用实时授权/取消/预算 callback 和进程组回收。重复 JSON key、错误 ID、非有限数字、重复名称/cursor、提前 EOF、不支持的协议或消费字段 schema 均拒绝。

探测的 HOME、cwd、缓存和 TMPDIR 是独立空目录，PATH 指向空 helpers 目录，只复制 LANG/LC_ALL，不传原仓库、开发者配置、代理或应用凭据。供应商初始化本身可能包含自动探测/更新逻辑，因此不能在原项目目录或用户 HOME 做握手。此配置减少可见输入及 helper 能力，不是内核禁网、独立服务账号或完整沙箱。[CBM v0.8.1 初始化实现](https://github.com/DeusData/codebase-memory-mcp/blob/v0.8.1/src/mcp/mcp.c)

防腐层仅校验当前消费的 `index_repository / search_graph / query_graph` 输入契约，规范化 schema 摘要忽略营销描述，但保留字段名和 literal enum/default 值。`CodeProviderProtocolReceipt` 是 Nasus 自有 DTO；`verified_operations` 仅表示相应工具声明可兼容当前输入，不证明 Provider 真正支持所有语言、精确定位或完整关系。额外工具不增加 Nasus 权限或公开 Tool Catalog。

真实已安装文件的 CLI 报告 `codebase-memory-mcp 0.8.1`，初始化却报告 `0.10.0`；两者分别保留，并记录 `cli_mcp_version_mismatch`，不以其中一个覆盖另一个或推断已经升级。实际原生文件摘要仍在 generation 指纹中。原生 schema 未声明目前 CLI 使用的 namespace `name` 和 query `format`，分别保留 gap；若供应商显式禁止这些字段则拒绝，不伪装完整契约已验证。

`code_index_protocol_pins` 将 schema hash、版本、工具数量和明确 gaps 追加式固定在 PG，与 Outbox 同事务。ready/degraded 必须先有真实 receipt；正常 cached read 也核验它。重建协商不同、receipt 缺失/损坏或投影已有而 receipt 不存在时拒绝，不用新握手补造历史。0080 不给 0079 的历史记录回填虚构协议；历史无 receipt 的完整投影需要独立处理，不能静默视为 verified。

固定 exweb 的两次实际原生协商与两次原生重建、PG 迁移/不可变/原子/损坏拒绝及兼容结果见[实施记录](./implementation-progress.md)。这不是完整语言能力、原生结果 completeness、公开 reopen、自动 Workflow 恢复或最终 V1 验收。

## 命令级输入固定（0081）

正常结构构建重试走 `open_index`，不能只靠显式 `reopen` 防止漂移。0081 将同一 canonical invocation 与 source binding 限定为一个 generation，保持来源修订、snapshot 和 Provider/build/policy 指纹不变；合法重试恢复原 generation 并递增 Worker epoch。Provider 或来源变化必须通过新的独立确认命令，不能在旧命令下换一个 generation 绕过原 pin。

PG 唯一约束与已有命令级 advisory lock 同时保护并发登记；不同 source binding 仍可属于一个多源构建命令。升级保留原记录/hash，发现历史同命令/来源有多个 generation 时拒绝迁移，要求独立审阅，不删除或选择“最新”来伪造唯一历史。有记录时禁止撤销此约束。开发业务库未自动迁移。

## 结构任务调度与恢复（0082）

`Conversation/Agent` 仍通过原 `system_image.build.structure` 和 ToolInvocationRuntime 确认；Temporal 开启时 HTTP 返回 canonical DTO `200 / running`，不是完成候选也不是新业务授权。0082 的 PG dispatch intent 固定 invocation、project、plan/digest、target、完整 canonical request、confirmer 与确认时间；intent 先提交，随后交付同一 workflow ID。丢失调度回执保留 running intent，reconciliation 重送同一 workflow，不替换 input 或生成新 canonical command。

生产结构队列与等待结构结果的 Agent 队列分离。Activity 以 PG 时钟 claim owner/epoch，45 秒租约、10 秒续租；每次执行重新加载 current actor、来源 ACL 和原计划/目标。候选事务同时核对 command hash、owner/epoch、确认及取消状态。活跃 owner 不被抢占，过期 owner 的迟到提交/释放被拒绝；原任务预算从原 confirmed_at 计算，基础设施重试不重置预算、不变成第二个 work item。

Activity 对临时基础设施异常向 Temporal 抛出，由相同 Workflow 最多三次尝试；已知授权、完整性和预算错误终止原命令。已归档候选优先确定 completed，重复 Activity/confirm/reconciliation 不调用 Provider 或产生第二份完成审计/Outbox。Activity 取消先撤销回调并等待 `to_thread` 工作停止，最后释放所属 lease；这只证明正常可中断执行，不能冒充 OS kill、逃逸进程或内核不可中断任务的有界清扫。0083 补充下述独立结构 stop，其余任务入口仍需分别接入。

Agent 图对 pending/running 等待并重查自身 budget/cancellation，恢复节点复用保存的 invocation ID，不将 running ToolResult 缺失判为失败；最终仍进入结构候选审阅而非自动发布。真实 exweb + Temporal + LangGraph PG 专项包含尝试重建、原来源移动/删除、投影一致与历史 replay，不等于整个 AgentGoal Temporal Workflow 重启或动态全计划调查。

Portal prepare 在顶层和 input 传同一幂等键，失联后只重试原输入。状态只读失败停止轮询及写动作，显式刷新核验后再操作。`GET /v1/projects/{project_id}/system-image/build-plans/{plan_id}/structure-commands` 以完整当前来源权限和精确 plan digest 发现该账号手动发起的未完成命令；创建审计的 actor/种类在 SQL 中过滤，keyset 单页 1-50 项，不读取全局命令列表。GET 不 claim/dispatch/续租，也不授予 confirmer 权限；确认继续走 Runtime。响应只含原命令 ID、target、status 和原 input key，私有原文/路径/工件不返回，`Cache-Control: private, no-store`。

刷新/重开仅恢复选择和原 invocation，详情再次核验 project/plan/digest/target/key/ID 后才展示确认动作；单个命令自动选中但不自动确认，多项必须手动选择并可继续分页。读取失败不保留可操作旧状态。旧输入无键时按确切 command ID 读取/确认，不伪造新键。此发现端点不是所有人的任务监控、Agent conversation 恢复、取消或公开 native reopen。测试终态与明确缺口见[实施记录](./implementation-progress.md#结构任务持久调度与页面恢复00822026-10-07)。

## 独立结构停止（0083）

`system_image.build.structure.cancel` 是独立的 medium/user-confirm canonical Tool，不复用原结构命令的确认。请求固定 `project_id / original_invocation_id / plan_id / plan_digest / target_baseline_id`；当前 qa_lead/project_admin/platform_admin 及完整来源范围重新核验后，才能消费这次停止确认。前端的 `can_cancel` 和 checkbox 都不是后端授权，客户端伪造 confirmed 字段被 Runtime 丢弃。确认需有时区、不得来自未来且不超过 900 秒；它与 API 生成的 canonical confirmed_at 使用同一时钟，PG 时钟仍负责租约及 intent 时间。

`image_structure_cancellations` 追加式保存原命令 hash、独立停止 invocation、actor 和完整 pins。原命令输入、原确认、预算与 job intent 不修改。升级不伪造历史停止；有记录时拒绝 downgrade。读取同时核验原命令和独立确认命令，不能将损坏的历史视为有效停止。

停止事务与候选提交使用相同项目锁和原 ToolInvocation 行锁。尚无活跃 owner 的排队/待确认任务可原子落到 cancelled，意图、原命令终态、审计和 Outbox 一起提交，后续 Worker 不再进入 Provider。活跃 owner 只收到 `cancel_requested`，原命令仍为 running；工作阶段/续租发现意图后停止，并先等待原线程退出，再确认 cancelled。重复停止可返回 `already_requested`，不插入第二条意图。过期 owner 不能续租或迟到提交。

已提交候选始终优先：停止返回 `already_committed`，不插入停止意图、不删除工件或改写已提交画像；原命令其他终态返回 `already_terminal`。回执是请求时的观察，不替代原 canonical 当前状态。已提交物理对象而 PG 候选尚未提交时，停止阻止候选提交；孤立内容寻址对象的 GC 不属于本轮完成范围。

`GET /v1/projects/{project_id}/system-image/build-plans/{plan_id}/structure-commands/{invocation_id}/status` 只读当前 PG 状态和停止能力，需精确 digest/target 及当前来源权限，返回 `private, no-store`。它不 dispatch/claim/续租。原停止 Tool 的读、确认、审计和幂等回放同样重新授权；共享 Conversation/Outbox 去掉完整 input/result/幂等字段，不暴露来源 pins。

Portal 在恢复的结构命令下按需展示停止区。重核验时保留控件但禁用操作；勾选绑定本次状态，刷新不保留勾选，不自动创建或确认停止。实际写入前再次只读核验，然后以独立 key prepare/confirm。回执丢失只重读原任务和发现页，不重发写命令；状态不明须显式刷新。沿用既有 deep/light token、弹层与滚动，仅为新 checkbox 覆盖表单全宽输入规则，不改全局 token 或生产路由。

当前原生验证在真实 Temporal 中运行固定 exweb 的排队、原生 session 停止和候选提交竞争，历史 replay 不调用 Provider；session 测试暂停在原生 index 返回后，不能冒充真实 CBM 子进程 SIGKILL。旧 inline 工作可观察意图并停止，但 API 进程崩溃后的 inline 终态恢复仍待实现。OS 强杀清扫、不可中断任务、其余能力租约/取消、完整 AgentGoal 恢复/动态调查及 P0-P6 退出条件不缩减。各批终态见[实施记录](./implementation-progress.md)。

## 已授权原文与私有缓存

每次分析只复制本次批准的文件到短路径临时根，不把原仓库、`.git`、未选中配置或开发者目录交给 index 调用。复制保留原始字节，文件只读；相对路径、去重、完整 byte count 和 SHA-256 在复制前及返回前核验。文件读取使用目录 fd 和 `O_NOFOLLOW`，拒绝读时替换的符号链接、非普通文件及越界路径。

供应商查询使用该临时根和本次独立 `CBM_CACHE_DIR`。结果归一化仍使用原来源命名空间，不把随机临时路径作为 Nasus 对象身份。供应商自己的 project name 只作为查询参数，不能成为公开 ID 或业务事实。

临时来源和私有索引在成功、失败及取消时移除，不清理其他分析的缓存。环境只传递必要的 `PATH/HOME/LANG/LC_ALL/TMPDIR` 和受控 CBM 根/缓存，不继承应用密钥、代理和其他 CBM 配置。`HOME` 仍为当前账号；更换缓存目录不能冒充账号、租户或网络隔离。原 MinIO 快照和 PG 事实不随临时目录清理删除。

CBM 的 `persistence=false` 仅关闭写入仓库的压缩分享工件，不能据此声称没有供应商 SQLite 索引；其索引是可删除投影，业务事实仍在 PG。[CBM v0.8.1 接口实现](https://github.com/DeusData/codebase-memory-mcp/blob/v0.8.1/src/mcp/mcp.c)

## 关系查询与完整性

公开 `query_graph` 没有独立关系 offset 参数，且 `total` 是本次返回行数，不是 LIMIT 前全量关系数。适配器不根据这个数字编造游标或全量计数。[CBM v0.8.1 查询实现](https://github.com/DeusData/codebase-memory-mcp/blob/v0.8.1/src/mcp/mcp.c)

`CodeGraphRelationshipScanner` 通过文件和已映射符号分区读取：先按来源文件分组；原始返回达到 probe 上限时递归拆分来源文件、来源符号、目标文件和目标符号。饱和父查询的任意前缀被丢弃，不作为一页提交或重复计数；不依赖关系顺序，也不使用供应商私有数据库。

每个原始页包含固定八列，保留调用解析的原生 score、strategy、candidates。字段/行形状、返回数量和输出大小异常明确失败。单次页有界；`NASUS_CODE_GRAPH_MAX_RELATIONSHIP_QUERIES` 默认 4096，另有原 `MAX_RELATIONSHIPS` 规范化边数上限。模糊/重复/被排除行不能耗尽 LIMIT 后使后续有效边静默漏读。

关系端点必须同时匹配本次映射的 qualified name 与固定文件路径。绝对路径只在私有快照根内归一化，不允许因为名字唯一而忽略错误、缺失或越界路径；未解析端点另计 gap，不补造关系。

预算耗尽、最细分区仍触及原始行上限、规范化边超上限时标记 `code-graph-relationships:truncated` 并保存具体 gap。扫描完整只表示当前已映射节点集合下的有界查询完成，不是供应商所有语言、标签、动态调用或业务关系完整。下述类型化声明、上述 Worker 会话及 0079-0081 持久登记/原生契约已交付；完整业务生命周期/自动恢复及原生语言/结果完整性验证仍需交付。

## 能力声明与版本化报告

`DeclaredCodeIntelligencePort.capabilities()` 返回 Nasus 自有的不可变能力声明，不启动进程、探测网络或创建索引。语法、CBM 和组合适配器的兼容入口仅声明已存在的 `capabilities / analyze / analyze_controlled`；实际 Worker 会话按上节单独声明操作和 lifetime，不把 CLI 功能冒充持久 Nasus 端口。未配置或没有声明的旧适配器保持空操作集合。

语法适配器声明实际装载的六种 grammar；CBM 的语言覆盖保持 `unknown`，不把后缀映射或开源宣传的语言数量视为已验证支持。CBM 声明当前实体、关系、查询次数、页大小和单命令 timeout 限制；这些不是整个 Agent 计划的累计预算。

每次结果携带独立 Provider 观察：可用/不可用/未运行、实体及关系读取状态、返回数量、精确/近似定位数量和有类型的 gap。语法解析可穷尽已批准输入，但静态动态调用覆盖仍为 unknown；CBM 实体分页完整性尚未证明，关系 complete 只表示当前已映射端点范围的查询结束。达到实体/边数上限保守标 partial；查询预算、被排除观察和错误端点另记缺口。未配置、optional 故障、禁用或原文解析失败而跳过 enhancer 也保留观察，不消失为零条成功关系。

各 Provider 的数量属于合并前/准入后各自结果，不能相加当作最终去重图。Java import 复核更新 CBM 关系数量及具体排除计数。未校准 score、未知语义或近似定位不能通过 `status=complete` 的标签被抹去；领域重建状态并拒绝数量、能力、scope、schema 或状态自相矛盾的元数据。报告仍不授予业务规范、覆盖或执行 authority。

新报告使用 `nasus.code-analysis.v2`，在既有 PG 分析记录中保存 `nasus.code-provider-projection.v1` 元数据，与原 source revision/report hash 一起固定。无需 DDL 或历史回填；旧 v1 原文/hash 不变，查询返回 `projection=null`，页面明确提示未记录完整性。读取和列表继续即时复核来源权限，完整读取同时校验摘要、版本与 header；这是分析结果状态，不是持久原生索引 handle。

来源分析面板按需展开“代码图完整性”，显示各 Provider、读取状态、定位、操作和缺口，沿用既有主题、细边框与隐藏滚动条。字段通过 React 文本节点显示，不拼 HTML。API 路径、Tool ID、模型出口、发布和业务批准规则不变。

## 原生观察与准入限制

- CBM v0.8.1 的 `__route__<method>__<path>` 全局键会合并不同 Java controller 的 handler；未验证的合成路由及其边不晋级为代码事实，保留明确 gap。现有语法适配器已验证的路由保留，不能把这些结果归功于供应商路由完整性。[原生路由与调用属性](https://github.com/DeusData/codebase-memory-mcp/blob/v0.8.1/src/pipeline/pass_parallel.c)
- `CALLS` 仅保留单一候选及明确解析策略；suffix/name-only、field hint 或缺元数据保持 unverified。保留原生 score 并标 `uncalibrated-provider-score`，不是校准概率或实现正确性的证据。其他旧关系仍有兼容 `.88` 字段，完整 typed reliability 尚未切换。
- 2026-10-08 的实际受控 exweb 代码变化发现，CBM 返回 `lsp_type_dispatch / candidates=1` 的新调用，但旧白名单只识别 `lsp_override`，导致有效原生边被排除。现明确兼容 `lsp_type_dispatch`，不接受任意 `lsp_*` 前缀；候选数不是 1、元数据缺失或未审查策略仍是 gap。[固定 v0.8.1 Java 类型派发](https://github.com/DeusData/codebase-memory-mcp/blob/v0.8.1/internal/cbm/lsp/java_lsp.c#L1817)按当前类型、方法名和参数数量查找目标，[调用管线](https://github.com/DeusData/codebase-memory-mcp/blob/v0.8.1/src/pipeline/pass_parallel.c#L1662)保留策略并记录单一候选。本次只修复适配器兼容，不声明继承、接口、动态派发或语言准确率完整；新源代码摘要进入既有 projection dependency pin，历史索引/报告不改写。红测、负测及原生复验结果见实施记录。
- Java `IMPORTS` 通过现有语法观察的精确 import、package 和声明核对目标，不新增另一套自建代码知识库。错误 import 证据被移除，同一边的其他原始关系证据保留。静态导入、wildcard、嵌套类型等未验证情形仍是 gap，不宣称完整类型解析。
- 多种原生关系归一化成同一边时合并全部 evidence，不能只保留首先出现的 raw kind。校验器不把代码事实升级为正式需求、用例 oracle、已执行覆盖或放行结论。

## 当前验证范围

实际 exweb 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`，先通过已有摄入器归档并恢复 **126 文件/文本单元**，再调用真实 CBM **0.8.1**。同一恢复快照三次分析各用独立临时来源/索引，实体与边全量归一化结果一致，临时文件均移除：**942 实体、2346 关系、13 条语法验证路由，每次 14 次关系查询**。

原生观察明确排除 **9 个合成路由、365 条未验证调用、117 项未验证 Java import**。这些是缺口计数，不是修复了目标仓库或校准精度。原文内容 hash 为 `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`；报告中的 UUID/manifest 与归一化 provider namespace 属于本次临时环境，不作为跨环境 gold ID。

收紧端点后的报告 `exweb-code-graph-partitions-exact-endpoints-20261007.json` 和同名日志保存在 `.nasus/validation`。本探针使用本地 object-storage adapter、180 秒探针预算，没有外部模型或目标执行；不冒充完整 canonical 授权、PG/MinIO 业务试点、独立 gold、CodeGraph 同语料对照或 p95 门禁。实际 PG 的取消/策略变化另由结构构建 API 测试验证，不能把两项范围混成一次端到端证明。

完整账号/资源隔离、原生语言/结果验证与业务生命周期、跨仓库对照、独立 gold、动态 Agent/全计划预算、来源 cutover/lineage、项目 delta/overlay/合并、五用途/旧链切换、脚本/RunPlan 与真实执行反馈以及完整 V1 继续保留为原目标。
