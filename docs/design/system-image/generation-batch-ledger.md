# 原生生成分包账本与私有回执

状态：0063-0065，2026-10-03。完整调用预算、逐批认领、原生回复、v3 aggregate result 与原子草稿提交已有专项验证；0065 增加独立终态恢复的 v4 原子结果及追加式权威关联，并接入共享 canonical/worker/Portal 路径。公共恢复及真实 Temporal 专项已通过；exweb 新 PG/MinIO 恢复、独立映射及最新完整 E2E 仍待终态，完整 P5 未完成。验证范围与失败记录见[实施进度](./implementation-progress.md)。

## 依赖与权威

`GenerationBatchReceiptApplicationService` 依赖固定[分包准备](./test-design-generation.md#模型分包与完整归并的准备契约)、当前管理员/来源权限、可信模型和 operator policy，以及[0062 worker 租约](./generation-jobs.md#跨进程-worker-租约0062)。通过 application port 调用 PG repository 和私有工件 adapter，领域层不访问 ORM、对象存储或 Provider。

`batch_execution_request` 将完整计划转换为精确 consent DTO，但不授予出网权限；只读 `query.quality.test_design_batches` 返回无正文的完整计划预览。PG 仍要求对应的 canonical `quality.test_design.generate` 命令为 running、真实确认账号和参数一致，以及当前租约 owner/epoch/input digest。相同生成入口按 exact planning digest 选择已确认路径，不增加绕过 ToolRuntime 的写接口；现有单次 consent 与恢复契约保持不变。

## 完整预算预留

- `nasus.test-design-batch-reservation.v1` 固定 project、invocation、actor、context/scope/input、模型配置摘要、全部来源绑定和 scope digest、operator policy、完整计划摘要及有序的逐批消息摘要。
- 最多 64 批，sequence 必须是从 0 开始的严格整数连续序列，batch digest 唯一；逐批容量、调用数、累计 token/费用 envelope 重新计算，不能只预留首批预算。
- 首次预留检查 PG 时钟下 15 分钟以内的确认；随后原 running 活动的回读不要求过去的确认永远未过期，但始终复核当前账号、角色、来源、模型和依据。
- 模型凭据、system/content 正文、oracle、支持证据正文不进入预算记录。模型消息 hash 固定完整 framing/schema/content；不能以摘要代替实际模型输入。
- 同一 invocation 的单次预留与分包预留互斥，在相同项目锁内检查，不能用旧执行器再次消耗已预留的分包命令。

## 逐批认领与归档

0063 新增三个追加式表：`quality_test_design_batch_reservations`、`quality_test_design_batch_calls`、`quality_test_design_batch_replies`。预算固定 scope，claim 固定 budget、sequence、batch digest 和 call ID，reply 同时绑定 claim 与该次真实调用的 LLM audit。已有记录时禁止破坏性 downgrade。

认领按序串行：前一批有已提交回复才能认领下一批。每批最多获得一次发送权；再次认领一律拒绝，不把“相同请求”当成重新发送许可。认领已落库但回复未落库时，调用结果为 unknown，不能跳批、重发或退款。

回复仅由可信内部 executor 的返回值归档；没有用户导入 JSON 或上传模型回复的接口。当前应用服务本身不发送 Provider 请求。校验 exact request/plan/batch/messages/call pins、非空且不超过 1 MiB 的正文、原生 provider usage 及逐批 token/费用上限，再写内容寻址的私有 MinIO 工件。

PG 再次检查当前依赖及同事务的租约 fence，将 reply metadata、独立 LLMCall、业务审计和无正文 Outbox 一起提交。MinIO 写入成功而 PG 提交失败不构成已归档回复；私有未引用对象需要后续 GC，不推断分布式事务成功。

每个 batch 有自己的 call ID、完整消息 request hash、response hash、Provider usage 和 `model_calls=1`，prompt version 为 `batch-v1`。不能合并成一条虚构的“单次模型调用”。Outbox 不保存回复正文或对象存储地址。

## 恢复与未知调用

内部 read 必须拥有当前 running 命令的精确租约。它重新授权并验证预算/claim/reply/hash/LLM audit，然后回读全部已归档私有正文、核对摘要和使用量，才返回完整有序 responses 给后续归并器。这是活动内回放，不是终态历史正文 API，也没有继承单次恢复命令的出网许可。

失去租约的 worker 不能提交可用回复或推进批次；它只能报告已经预留的自己那次失败调用审计。失败审计不能覆盖已存在的成功审计，已有终态失败审计也不能后来改成成功回复。源码 ACL、模型配置或 scope 变化阻止下一批，历史预算和调用事实仍保留。

budget view 分别报告 reserved、claimed、archived、unknown、已知原生 input/output token 和按 operator rate 计算的已知费用。未知调用保持预留；`reservation_released=false`、`invoice_verified=false`，不把 fixture usage 或 operator ceiling 视为真实账单。

### 独立终态恢复（0065）

`nasus.test-design-batch-recovery.v1` 固定原 invocation/request/reservation/plan、完整 replies digest 和每次调用的 sequence/batch/call/request/response/artifact/usage/audit 摘要。不含正文、私有地址或授权字段；缺批、重复、乱序或 unknown 不能生成完整有效回执。回执仍须从权威 PG 原记录重新推导，不接受请求自身的自洽摘要作为证据。

`GenerationBatchRecoveryRepository.load_for_recovery` 在同一项目/来源权限事务锁内校验原命令 failed、独立新命令 running、相同确认管理员、固定 scope 与模型记录、PG 时钟下未过期的新确认，以及新 worker 的 owner/epoch/canonical input digest。它拒绝其他已提交结果或混入单次预留，回读完整原生审计/回复 metadata，前后调用当前依赖授权检查。相同新命令只允许重放其已有 v4 结果；另一恢复命令不能替换它。底层 lease-state fence 共用，但不能代替完整 batch command 校验。

`prepare_archived_batch_recovery` 在每次私有工件读取前后重新检查独立租约及当前依据；逐批复核正文、usage/hash 和原始 oracle，再归并完整分母。`GenerationBatchRecoveryApplicationService` 不具有 Provider 调用端口，复用完整原生归并验证。私有结果先写内容寻址工件，再在一个 PG 事务写 draft cases、coverage、原生调用 FK、审计、Outbox 和 `quality_test_design_batch_recovery_results`。v4 保留原 invocation/全部 call IDs，另存独立 recovery invocation/request。Outbox 失败全部回滚；原失败命令不重开，不退款、重发或发布部分结果。

共享 `quality.test_design.recover` 通过 schema discriminator 严格接受旧单次或新版完整多批请求；未知 schema、混合字段和不完整回执拒绝。任务查询仅在原 actor 当前有管理员及所有来源权限、原命令 failed、无结果且全部回复已归档时提供完整 metadata-only offer。派发重新检查 PG 回执、相同 actor、独立确认及原 scope；claim/renew/finish 使用完整新请求摘要，Temporal 复用已有活动，不增加第二套生命周期。竞争恢复不能借另一个命令的结果被标为 completed。

Portal 使用整个 offer 作为确认键，刷新、改选或重新读取发生变化即失效。新确认文案明确恢复完整批次、无新模型请求；partial/unknown/未开始批次不展示恢复入口。历史 v4 view 严格校验所有可见原生 pins，私有 replies digest 由后端回读校验，不声称浏览器可验证被隐藏的存储引用。历史不要求旧 lease/模型/确认 TTL 仍有效，但读者当前 ACL 必须成立。公共链路和真实 Temporal 的终态证据以实施记录为准。

## 验证边界

纯测试覆盖完整预算/消息 pin、错项目/模型/策略、漏批/重复序列、篡改 envelope、非法 usage、外部字段和独立审计。PG 测试使用实际三条来源 AC 强制三个完整批次，但 tokenizer counter 和回复明确为夹具；覆盖并发认领、三种 Outbox 回滚、丢失租约、工件损坏、撤权、追加式表和旧执行器互斥。不能把这些测试记为外部模型准确率、账单或目标运行证明。

exweb 回放使用固定 commit、真实来源、真实 tokenizer、隔离 PG 与 MinIO；该示例当前范围只有一批。回复和 usage 是明确的契约夹具，不调用外部模型，不运行 exweb，不增加目标通过计数。多批行为由独立的三 AC PG 测试证明，不能冒称 exweb 已验证多次模型出网。

## 内部原生采集执行器

`GenerationBatchExecutorApplicationService.collect` 由共享生成任务维护原 canonical lease，先预留完整预算，再按序回读/认领每批；发送前重新核验完整计划和测试通过的精确模型配置，通过已有 `GenerationNativeModelPort` 使用原生 Provider adapter，无框架 ToolNode、fallback、重定向或自动重发。

已归档批次逐项重新校验 JSON schema、batch/input digest、原义务、事实及 oracle，再继续未认领的后续批次。unknown claim 阻断后续出口。新回复先归档其真实调用及 usage，再严格校验；坏回复保留计费事实，但立即停止，不再消耗下一批，也不让重试把坏回复换成另一模型。

原生 Provider port 已开始之后的失败、取消、无 usage 或迟到提交保留精确调用预留和独立失败 audit；发送前模型校验拒绝只保留 claim，不伪造已尝试的 LLMCall。取消不会重新认领已发生的调用。全部原回复通过后重新核验完整分母，返回私有 validated proposal 和 budget，`aggregate_result_committed=false`。此返回不是业务 result、不生成 completed 命令、不批准断言映射，也不授权执行目标。

单元端口是明确夹具；新增三 AC 的 PG + 原生 HTTP transport 专项验证三批完整采集及第 0/1 批断线后的前缀回放和 unknown 阻断。后者的实际终态以实施记录为准，不用单元结果代替集成通过。exweb 新回放在此执行器新增前启动，只证明独立 receipt 层，不证明此 native collector。

## 版本化完整结果（0064）

`GenerationBatchResultApplicationService.commit` 只供可信内部 executor 调用，不提供上传模型 JSON 的接口。它重新检查完整确认计划、当前管理员/来源/模型和精确 worker lease，回读每一份私有原生回复；逐批严格 DTO 校验后按原分母完整归并，固定全局规则、observable oracle 与本地 case/gap 到 Nasus ID 的 lineage。

`nasus.test-design-result.v3` 与旧 v1/v2 分开：归档完整 reservation、batch plan、逐调用 claim/reply/audit、完整草稿与 CoverageMatrix、ID provenance 和合并内容 hash；不伪造单条 aggregate LLMCall，不把多批 usage 填进旧单次调用。原生回复正文保留在各自的私有归档中，历史读取必须重新取得并验证全部回复。

现有 `quality_test_design_results` 增加 `provenance_kind=single|batch`，旧数据默认 single 且继续要求非空 call_id；batch 强制 call_id 为空。新增追加式 `quality_test_design_result_batch_calls` 将每个 generation/sequence 精确 FK 到原 invocation/sequence/native reply call。全部案例、完整 coverage、逐调用 provenance、业务审计与无正文 Outbox 同一 PG 事务提交；缺批、未知回复、失去租约、依据变化或事件写失败时没有部分业务结果。重试验证原工件，不重写归档、不再次发送 Provider 请求。已有多批结果禁止破坏性 downgrade。

每个 Provider 的原生输出仍严格限制 512 cases / 512 gaps / 1 MiB；仅内部 v3 合并 DTO 允许最多 64 批的 32768 cases / gaps 和 64 MiB 合并内容。私有 v3 结果工件上限 160 MiB，旧单次写入仍保留原 8 MiB 上限。任何超限都明确失败，不截断或缩小 AC/义务分母。大规模独立审阅的页面与容量治理仍需交付。

历史读取不要求旧模型仍可用或旧生成账号仍具出网权，但始终检查当前读者对固定 scope/context 全部来源的权限、归档 hash、原 canonical request、逐调用 audit 和 PG 投影。HTTP v3 使用独立 `nasus.test-design-result-view.v3` / `view_hash`，不暴露私有 native `artifact_ref`；它不是可直接按旧私有 artifact_hash 验证的完整归档。内部映射审阅读取完整已验证工件，业务草稿仍为 pending independent review，automated/executed/passed 不增加。

native executor 的 `execute` 全批采集后调用原子结果 port；已提交结果回放绕过重新预留/出口。生命周期由现有 canonical job/Temporal 负责，结果提交自身不创建第二套任务或擅自修改终态。已 composition 原执行器、相同 Tool handler、Agent 工具发现、共享 heartbeat/取消与 Portal v3/v4 客户端；0065 接入独立终态恢复，当前公共后端与真实 Temporal 验证仍以实施记录为准。框架截止窗口的 version patch 与安全边界见[持久任务](./generation-jobs.md)。

exweb 扩充 fixture 用固定 SHA、真实 tokenizer/PG/MinIO，验证一批 v3 归档、逐调用关系、幂等、终态历史回读及新发布头后的 stale；原生回复和 usage 仍为显式夹具，未调用外部 Provider 或执行目标。该回放的终态以实施记录为准，0063 已通过报告不能替代 0064 验证。

## 继续交付

0064 aggregate result 及 canonical 生成/任务已有专项证明；0065 私有原子恢复、公共 canonical 恢复和真实 Temporal 重试/history 回放已有实际终态证据。下一步继续验证固定 exweb PG/MinIO、独立断言映射、最新完整链与容量/性能门禁。不得将内部提交测试或协议浏览器夹具作为外部模型准确率、账单或目标执行证明。

归并仍保持每批严格 DTO 校验；旧 v1/v2 的容量和单次语义不静默改变。五用途 ContextPack、旧链 cutover、脚本/RunPlan、真实目标运行与证据反馈、Provider 完整生命周期/gold/性能和最终 V1 门禁均继续属于原完整目标。
