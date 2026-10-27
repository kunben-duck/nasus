# 固定画像源码的原生目标构建

更新：2026-10-10。原生构建从固定系统画像读取归档源码，经独立确认的 canonical 命令与 Temporal Worker，在无网络的受限 Docker 容器中执行 Maven，并私有归档实际 JAR、构建日志和完整运行时清单。0102 在 PostgreSQL 登记唯一预留、原结果与任务所有权；0103 新增独立的[执行计划构建关联](./run-plan-build-bindings.md)，固定全部代码来源和确切原产物，不改写 v1 RunPlan，也不能授予目标执行或业务覆盖。各批实际验证范围见实施记录，完整范围仍按 [P0-P6 门禁](./delivery-and-evaluation.md)验收。

## 固定源码读取

`ImageNativeBuildSources` 通过 system_image application port 核验原画像、完整来源清单、选定代码 binding/source revision 及当前来源权限。PG 只读适配器返回确切来源修订，不选择最新来源或工作目录。私有 SourceSnapshotArchive 核验 manifest 摘要和每个文件的长度、路径、内容摘要，以及完整文件集合的来源摘要；返回有界的不可变字节对象，读取后再次检查当前权限。

build source DTO 位于 shared domain，source application 不依赖 quality_loop repository 或执行引擎。质量域的构建请求固定完整输入摘要、适配器和产物路径，可声明确切预期产物摘要。单来源上限为 1000 个文件、32 MiB，单文件 8 MiB。当前第一种适配器只支持根 Maven 项目和 executable Spring Boot JAR，不代表多仓库拓扑、其他语言或其他打包方式已经实现。

原来源归档不保存 Git 文件模式，因此回执明确 `file_mode_attested=false`。构建临时副本仅写入普通文件，不执行源码中的 shell wrapper。原源码字节在实际构建前后完整复核，不能用已改变的输入核验产物。

## 构建隔离与产物

operator 必须提供本地已有的完整 Docker image ID 和独立 Maven repository cache。适配器核验实际 image ID、Maven 3.9.11 和 Java 21，禁止拉取浮动 tag。版本检查与构建均无网络、只读容器根、移除 capabilities、禁止提权，并限制进程数、内存、CPU 与临时空间。唯一挂载是本次拥有的源码副本和只读依赖 cache，不挂载开发数据库、环境文件、主机 Maven settings、模型凭据或 Docker socket。

构建固定执行 `mvn --batch-mode --offline -Duser.home=/tmp -Dmaven.repo.local=/cache verify`，不接收任意 shell 或可变命令。子进程输出与等待时间均有上限，失败、中断或超限时终止本次进程组，包括首进程已经退出但仍持有输出管道的子进程。容器只按随机 owner label 清理，错误 owner 或无法确认资源已移除时拒绝成功回执。失败不会接受已产生但未核验的 JAR。

构建端口的 `require_work` 回调在启动前、执行期间、源码复核、产物清单和返回前检查 PG worker 所有权、实时来源权限及 operator 政策摘要。输出管道关闭之后仍以 100ms 有界等待检查回调，不能因没有新输出而失去中断能力；资源清理不受该回调阻断。应用层 `execute_native_build` 将异步取消转为线程可读的停止信号，等待原线程终止进程并完成容器清理。重复取消不会脱离原线程，清理失败仍作为错误抛出。Worker 每 15 秒续租，租约有效期 90 秒，替换 owner 必须递增 epoch；旧 owner 无法提交新结果。进程强杀后的孤儿容器清理尚未接入，不能把线程取消或 Temporal 重试等同于完整 SIGKILL 恢复。

JAR 上限为 128 MiB，完整 ZIP 清单有条目与展开字节上限。路径穿越、重复成员、加密成员和符号链接拒绝。回执保存每个实际成员的字节长度及摘要，以及应用类和内嵌依赖库数量；私有回读重新计算完整清单，不能用外部声明替代产物字节。若请求声明产物摘要而实际不同，则拒绝，不能修改原 RunPlan 声明适配新产物。

构建成功仅证明本次固定输入在该 adapter 下产生实际产物。依赖 cache 的完整供应链、构建可重现性和业务正确性未获得证明，回执明确保留 false。本轮两个原生构建的源码与产物字节长度相同、JAR 摘要不同；恢复必须回读原归档产物，不能重建后冒称原回执。归档 timestamp 等具体原因仍需独立核验。

2026-10-12 的 worker 修复将 async application/Job 中的同步 scope、实时权限/租约、
operator policy、来源摘要与 JAR receipt 计算移到工作线程。`asyncio.to_thread` 保留
调用者身份，Temporal heartbeat 和取消可在等待这些检查时继续调度；校验顺序和原 PG
commit fence 不变。取消发生在检查期间时，等待中的 async 流程不进入下一次 build、
归档或提交；既有预留不删除，不能因此创建另一原生尝试。线程可继续完成只读检查，
不把 async 取消等同于停止所有底层 I/O。专项终态与 protocol/真实 PG/Temporal 的证据
边界见实施记录，不以此声称 exweb 业务覆盖或 SIGKILL 恢复完成。

## 私有归档与权限边界

`NativeBuildArtifacts` 在 project/build 命名空间中保存内容寻址的 JAR、日志和 JSON 回执。正式 application 读取先检查当前项目和来源权限，完整回读原源码并核对请求摘要，之后才读取并重新核验实际 JAR 和日志字节。此 adapter 是内部存储端口，不是授权接口。0102 的 build ID 由原 invocation 确定，在 PG 预留及结果中唯一；私有存储写入本身不等于已登记业务结果。

没有绕过 ToolRuntime 的直接 HTTP 构建写入口，也没有改变旧 `run.start`。新能力使用既有 tool-invocations API；0103 对原生构建回执的精确引用使用另一次独立确认，不能继承构建许可。目标环境、fixture、执行授权和逐用例运行仍需独立交付。

`GET /v1/projects/{project_id}/quality/native-builds/{invocation_id}` 只回读原 canonical 构建；有原结果时完整核验原源码和私有产物，无结果时返回原预留/worker 状态，不 dispatch、重建或补造清理证明。读取不要求今天的 operator 配置仍可用，但当前项目、完整原来源和归档完整性仍必须通过检查。来源拒绝保留 `403`；错误消息脱敏，成功及 handler 错误均使用 `private, no-store`。

prepare/preview/query/cancel 四类工具的单项、列表、resolve 和 Agent 回执读取均执行独立的原输入授权。来源撤权时先拒绝，再读取私有产物；缺少守卫端口时失败关闭。会话发现、搜索和三种 SSE 流只保留原命令的 ID、工具及状态，不公开输入、源码、日志、政策或产物正文。历史事件投影不改写旧归档，也不以最新来源重构原输入。

## Portal 构建入口

固定画像详情提供默认折叠的原生构建面板。用户显式展开后读取完整 `source_members`，选择确切已采集的代码 binding/revision，并填写 `target/*.jar` 和可选预期 SHA。分页不完整、重复 binding、错画像或错清单均拒绝；不默认选择源码，不扫描本地 checkout 或自动推测产物路径。

预览核验 canonical request、原 image/manifest/source pins、源码计数和完整离线政策摘要。表单变更或重新查询使确认失效；独立勾选只允许本次 Java 21/Maven 3.9.11 离线构建，不批准需求、用例、目标执行或发布。正式写入继续经过 `quality.native_build.prepare` 和 Runtime 确认。

提交前在 sessionStorage 保存同账号、项目、画像和摘要范围内的 ID/hash 恢复指针，不保存源码、日志或凭据。丢失创建/确认回执、刷新或重新展开后仅 GET 原命令和原归档，不自动构建或确认。恢复的待确认命令必须主动重新预览原政策、核验请求完全相同，再重新勾选确认；不能仅凭命令摘要启动源码执行。路由卸载阻断后续隐式确认，但保留已收到的原命令 ID。

有结果时显示原 build ID、JAR 路径/摘要、字节数和完整来源/工具链回执；源码与产物是否物理匹配仍由后端逐字节核验，浏览器不冒称独立检查 JAR 字节。预留后未知输出阻断另一次构建，已知终态才允许显式准备另一次独立确认。重新核验期间隐藏旧结果，来源撤权或原工件错误隐藏父级画像内容。管理员按既有规则可读取 restricted 来源，普通审阅者须在当前允许名单中；浏览器专项先通过真实成员接口降权，再撤销来源权限。

运行中的原命令提供独立取消面板，固定原 build invocation ID，不删除已保存产物、不授权另一份构建。用户重新勾选后才创建和确认 canonical 取消命令；取消恢复指针按原构建、账号、项目和画像隔离，仍只保存元数据。创建或确认回执丢失、页面刷新及显式重新核验只 GET 原取消命令，不自动重发或确认。恢复到 waiting_confirmation 时必须重新勾选。面板区分目标已经终态与取消请求已记录；后者保持 `cleanup_confirmed=false`，不能把 RPC 送达当作容器清理证明。

取消入口的协议浏览器检查不替代实际 Worker 清理。只有完整回读了 failed／cancelled 的原取消命令、原构建仍在运行且来源权限核验有效时，用户才能显式准备另一份取消请求。该操作仅清除确切旧恢复指针，不删除 PG 历史、不发送写入；新的请求仍须重新勾选确认，原构建不重新启动。回执未知时不提供此入口，未知 reservation 后仍禁止另一份构建。公开清理证明、SIGKILL 孤儿资源恢复及完整 UI 生命周期仍需继续交付。

## 正式命令与任务恢复

- `query.quality.native_build_preview` 仅核验归档输入和明确的 operator 配置，返回固定 request、源码计数及政策摘要，不执行源码、不公开文件正文或存储地址。operator 必须配置 `NASUS_NATIVE_BUILD_IMAGE_ID`、`NASUS_NATIVE_BUILD_MAVEN_CACHE` 和有界的可选 timeout；服务启动不会自行选择开发 cache、拉取 tag 或运行构建。
- `quality.native_build.prepare` 要求当前 project/platform admin 和独立 `user_confirm`。PG 再次校验完整 canonical input、相同确认账号、项目/会话、时区、15 分钟 TTL、源码/画像/清单和当前权限 fingerprint。伪造 confirmed 字段不能代替 Runtime 确认，改字段、改政策、过期或未来确认均拒绝。确认只许可这次受限源码构建，不继承运行测试的许可。
- HTTP handler 只 dispatch 原 invocation；Temporal workflow ID 固定为 `nasus-native-build:{invocation_id}`，专用队列使用配置队列加 `-native-build` 后缀。Worker 和有界 reconcile 扫描接入生产组合，不创建新的请求或 build ID。Activity heartbeat 与 PG lease 各自生效，二者不充当源码授权。
- 一个 invocation 只能预留一次原生尝试。预留和结果分别与各自 Audit/Outbox 在同一 PG 事务提交，表具有原画像/来源 FK 和 append-only trigger，降级不能抹掉已有历史。私有 JAR 已写入但 PG 结果事务失败时，仍没有成功结果；恢复报告不确定并失败关闭，不自动重建或把新产物冒充原产物。
- 结果已提交而 Worker 尚未保存终态时，替换 Worker 重新授权并完整回读原结果，再提交终态。重放不需要当前 operator 政策仍相同，也不执行 builder；仍要求当前来源访问权限和原输入完整性。结果提交和 ToolInvocation 终态目前是两个事务，不能声明统一原子交付。
- `query.quality.native_build` 只返回当前授权下的原任务元数据，ToolResult 不保存完整 ZIP 清单、源码、日志或对象存储地址。无结果时区分是否预留、当前 worker 是否仍有效和 outcome_unknown；历史不被当作最新目标。
- `quality.native_build.cancel` 同样要求独立确认和当前管理员权限，固定目标 invocation，持久记录取消并使其 worker 失去提交权。Temporal 取消 RPC 的 delivered 回执只表示已送达，不证明清理完成；公开取消结果明确 `cleanup_confirmed=false`。本轮运行中专项另等待实际 Worker/Workflow 终态，再核验拥有的容器已移除。已提交的原结果优先保留，取消不能删除它或重新构建。

回执明确 `native_build_verified=true`、`execution_authorized=false`，executed_on_target/passed 均为 0。环境、定位、测试数据、独立执行授权和逐 case/step/oracle 的原生证据是后续独立要求。[执行计划准备](./run-plan-preparation.md)仍保持声明态，不能因本适配器存在自动成为已核验计划。

## 验证范围

纯测试使用明确的协议 JAR 和命令适配器，覆盖来源/产物摘要、隔离参数、错误工具链、路径、源码改写、符号链接、超时与日志上限、清理 owner 和私有读取顺序；它们不证明真实编译。中断测试另执行真实主机子进程，验证无输出或主动关闭 stdout 时仍可中断、首进程退出后子进程不继续写入、异步重复取消等待清理以及清理错误不伪装取消成功。原生测试单独使用 disposable PostgreSQL 和私有 MinIO，覆盖删除 checkout 后仍回读原源码，以及读取前/后的来源撤权。

exweb 专项必须显式开启 `EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD=1`，输入为独立核验的 Git commit `fe5827f6b76f77ef34918d8b452ee823142332dc` 全部 126 个 blob。测试通过正式来源注册、采集和画像物化固定导出文件，删除仅属于本测试的工作目录，再从私有归档读全部原字节并实际执行离线 Docker 构建、MinIO 保存和完整回读。导出目录的来源 external revision 保留实际采集内容摘要，不把它篡改成 Git commit；Git commit 与全量 blob 一致性由专项独立记录。

原生测试对象在隔离 suite 结束后清理，本地 JSON 保存核验报告，不冒充永久生产工件。实际终态、选择集和剩余门禁见[实施记录](./implementation-progress.md)。测试成功不替代维护者业务 gold、外部模型质量、真实目标执行、完整质量闭环或 P5 完成。

早期内部中断专项分别取消应用层任务或撤销真实项目成员访问，单次约 0.11 秒和 0.17 秒；这些报告的 `durable_cancellation_verified=false` 保留，不被追认成正式任务证据。

后续正式专项使用同一固定 exweb 全部 126 个归档 blob，经实际 HTTP 预览/独立确认、真实 Temporal 专用 Worker、离线 Docker Maven 和私有 MinIO 结果回读，实际产物为 81,124,984 字节、109 个内嵌依赖库、121 个应用类。另一份相同源码构建的产物摘要仍不同，不能声明可重现性。Workflow history 可重放且不含源码、日志或私有路径。

正式运行中中断的两项专项先 inspect 确认 compile 容器 Running，再分别通过 canonical cancel 命令或真实项目成员 DELETE 撤权。PG 均只留下原预留，没有成功结果；实际 Worker/Workflow 终态之后检查两个拥有的容器均已移除。此次取消约 0.86 秒、撤权约 0.22 秒，是单次试验而非 p95 门禁。报告明确原生目标执行和完整质量闭环为 false；当前验证范围、后续重新加载批次及失败门禁见[实施记录](./implementation-progress.md)。
