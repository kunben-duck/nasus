# 固定输入的测试生成契约

状态：2026-10-03，生成预检查、候选输出校验及 planned CoverageMatrix 已实现；0058 增加私有结果原子归档，0059 增加完整单次原生模型调用、预算确认、持久预留和响应归档恢复。0060 接入 [Temporal 生成任务及显式终态恢复](./generation-jobs.md)，Portal 专用预算、确认、取消、历史和归档恢复入口已有专项验证。0061 增加[独立断言映射审阅与 reviewer 发现](./test-design-mapping.md)，追加批准记录但不改写原 planned 结果。完整模型分包及旧链切换未交付；不是 P5 完成声明。依赖[范围审阅](./test-design-scope.md)与[用途契约](./knowledge-contracts.md#5-用途上下文包)。

## 输入与权威

`TestDesignGenerationApplicationService` 属于 quality_loop，通过 `GenerationScopePort.resolve_inputs` 获取同一次归档校验的范围和 ContextPack。此端口保留 source ACL、完整历史工件、当前来源 authority 和 publication/head 的检查，不直接读取 system_image repository，也不读取旧的可变 TaskContext。

请求固定 `project_id / scope_revision_id / scope_artifact_hash`。输入固定 context ID/hash/input digest、image ID/hash、scope revision/hash/request hash，并以 canonical JSON 派生 `input_digest`。撤回、过期、显式 gap、未解决冲突、无独立 oracle 或错误 pin 均拒绝，不切换到新 head 或缩小约束集合。

`nasus.test-design-generation-input.v1` 保留完整原 ContextPack（包含其分包、来源字段、检索事实）、完整审阅合同及以下独立义务行：

- 原 AC 和业务规则：保留来源修订、批准修订/hash 与原 observable oracle。
- 风险、权限、状态转换、不变量：保留 scope 修订/hash、原约束/证据引用和审阅 oracle。
- 每个约束的正例及适用负例：独立行，不能覆盖原 AC/规则的 oracle。负例明确不适用理由仍保留在合同；未知负例仍是阻断 gap。

行身份由 scope 修订、类别和本地标识确定。完整 AC/规则分母与所有业务规则的 global 集合单独保存；新生成案例必须显式继承全部 global rule ID。来源正文是数据而非指令，历史测试仅作审阅选定的复用候选，不能授予正式覆盖或期望权威。

这仍是输入契约，不是一次模型 prompt。归档的分包字节预算不能代替具体 Provider 的 token/framing 预算，也不能把整个 bundle 不加判断地发给模型。

## 候选输出与覆盖

`TestDesignModelOutput` 使用严格 JSON DTO：不接受未知字段、重复 JSON key、NaN、Markdown 围栏或自动修复。输出正文上限 1 MiB，最多 512 个候选用例和 512 个 gap。用例要求 preconditions、inputs、steps，以及指向固定义务行和具体 step 的 assertion；assertion 的 oracle/hash 必须与独立来源完全一致。复用和支持事实只能引用固定输入中允许的对象。

每个义务必须有一个以上候选用例或显式 gap；漏项、越界、重复身份、缺失断言/步骤、改写预期均失败。可同时记录已有候选和剩余 gap，不能以一个候选消除该行的未知。

CoverageMatrix 的原约束分母与扩展义务分母分开计算。重复增加候选用例不增加已规划约束数。生成结果本身只计算 `planned` 和 `proposed_assertion_case_ids`，始终保留 `assertion_mapped=false`、`mapping_status=pending_independent_review`。0061 的独立审阅派生另一份 reviewed assessment，不修改原 draft/planned 工件。两者的 `automated / executed_on_target / passed` 仍为 false，全部行保留运行 unknown。映射批准不能替代真实目标运行或规范批准。

`check_output` 会重新解析当前输入及访问权限并核对原 `input_digest`，再校验响应。它只返回内存候选，不是持久化提交授权；后续提交事务必须再次校验。

## 结果原子提交（0058）

`TestDesignResultApplicationService.commit` 是供可信生成执行器调用的内部端口，不是用户上传任意 JSON 的接口。0058 交付时没有公开生成 handler；0059 已接入下述确认式原生执行器，但仍没有上传任意结果 JSON 的 POST 归档入口。正式执行器必须先完成预算与出网授权、持久调用预留及模型执行，再调用本端口，不能把一次成功调用审计当作出网或费用授权。

提交要求固定 scope/input/model config digest、当前项目管理员，以及同一个经确认且 running 的 canonical invocation。必须存在精确匹配该请求和原始响应 hash 的成功原生 Chat 调用审计（非 fallback、非错误、非估算 usage）；调用和生成一对一绑定。0059 请求另含 execution consent，必须同时匹配持久预算预留和 native response receipt；旧请求省略此字段，历史序列化/hash 不改写。重新解析测试通过的保存模型，不读取可变 active route；修改模型、凭据或测试记录会使原 pin 失效。

先严格校验全部候选与 oracle，再写私有、内容寻址的 MinIO 工件。随后在 PG 项目/ACL/模型锁内重新验证来源、独立批准、publication、scope、账号和成员权限，在同一事务写入：`quality_test_design_results`、`quality_test_design_case_revisions`、`quality_test_design_coverage`、AuditEvent 和 Outbox。Outbox 含会话/Goal 关联及 metadata，不含源码、原始模型文本、对象存储地址或密钥。事务失败不留下任何一半用例/覆盖记录；已经写出的私有未引用对象可能留待回收，不视为已提交结果。

三个新业务表禁止 update/delete。同 invocation 的相同结果幂等返回，不重写工件；不同调用、请求或响应不能覆盖历史。每个案例以 generation ID + model-local case ID 定位，仍是不可变 draft，尚未进入旧用例可变主表或得到独立映射批准。零用例但完整显式 gap 的响应也可以归档，planned 数保持为零。

历史读取重新验证私有 hash、原 ContextPack/scope、原始输出、用例投影和重新推导的 CoverageMatrix。来源访问权始终重新检查。批准撤回、scope 或 publication 变更后仍可回放原结果，但 `current_use.scope_current=false`；不会重用旧审批生成新结果。历史读取不依赖当前模型配置或当前源文件。

## 入口

`GET /v1/projects/{project_id}/quality/test-design-scopes/{revision_id}/generation-preview?artifact_hash=...` 为 private/no-store 只读接口，只返回固定 pin、输入摘要、分类数量和剩余门禁，不返回来源正文，不调用模型。

`query.quality.test_design_generation` 经 canonical ToolRuntime，输入相同；返回 `test_design_generation` metadata receipt。Planner 再次消费时重新验证完整输入和授权，旧回执不能越过撤回或新发布 head。新查询只在明确生成输入/预检查意图时优先，不挤出既有生成、执行命令。Catalog 旧 Tool ID 保持不变。

`GET /v1/projects/{project_id}/quality/test-design-results/{generation_id}` 为重新授权的 private/no-store 历史读取接口。canonical handler 供 Agent 与 Portal 使用；页面不直接导入模型结果，也不绕过确认写入。

## 尚需交付

0059 已推进下方完整单次执行，0060 接入持久派发、活动重试、heartbeat、取消回执与独立恢复命令及 Portal 入口；0061 提供独立断言映射审阅，0062 补充现有任务的 worker fencing。仍需完整模型分包执行和多响应归并提交证明及旧链切换。本契约绝不静默调用旧生成器来绕过门禁。正式结果入口当前只接受一个完整响应和对应单次审计；不能截断输入来适配此端口，也不能把新 Tool ID 宣称为全部 P5 完成。

## 模型分包与完整归并的准备契约

内部 `GenerationBatchPlanningApplicationService` 已接入 generation executor 的同一来源、当前管理员、固定 scope/context、测试通过的模型和可信 operator tokenizer/policy 端口。它只预览和校验 proposal，不调用模型、不认领 worker、不预留持久预算或提交案例；没有 HTTP、Tool 或 Portal 写入口。

- 保留原 generation input digest、全部 AC/规则及义务分母。涉及多个 AC 的同一风险/权限/状态/不变量义务使对应 AC 连成不可拆分单元；每项义务有且只有一个输出所属批次。
- 所有批次继承全局规则的原 oracle 和全部 global obligations；全局义务只由第一批产生断言，不能通过重复生成增加分母。显式选中的支持事实保留，关联或无 scope 的证据不得通过 top-k 静默丢弃。
- 按完整 system/schema/content 和固定 tokenizer/framing 计算每批 token；同时核验全部调用数、容量、累计 token 和费用上限。不可拆单元无法适配时明确阻断，不截断强制项来使单批通过。
- 每批回复必须同时匹配原 input digest 和 batch digest，只可引用本批收到的事实和所属义务，保留精确 step/oracle；缺批、重复批、越界关联、JSON 重复键和伪造 authority 均拒绝。
- 归并为 case/gap ID 增加确定性批次命名空间，保存响应 hash 与原 ID 映射，再按原完整分母重新校验；全批验证成功前没有部分提交。proposal 检查前后重新准备并核验依赖，不能复用撤回 scope 或旧 ACL。

当前归并仍受 v1 聚合 DTO 的 512 cases/512 gaps/1 MiB 上限约束，超出会整体失败而非截断。后续完整多调用结果必须使用显式版本化的存储/预算契约，每批持久原生回执、租约、累计费用和原子归并提交；不能把多响应伪装成一个 native call，不能把此准备阶段当成已启用正式批量生成。

0063 增加独立的[完整预算与逐批私有回执账本](./generation-batch-ledger.md)：精确 confirmed command/worker fence、追加式 claim、每次独立 LLM audit、私有正文和 Outbox 事务。它没有改变本准备服务的只读行为，也未接入正式多批 Provider/Tool/UI 或 aggregate result 提交。现有单次入口不会被静默升级为多次出网。

## 完整单次原生执行（0059）

新增 `query.quality.test_design_execution`（只读预算预览）和 `quality.test_design.generate`（确认式写命令）。每次选择固定 scope/hash、经过测试的保存 Chat 模型和预算，不读取可变 active route。预览仅返回 destination、完整固定 manifest 的来源绑定、ACL fingerprint、operator policy/hash、plan/hash、token/cost envelope 和业务 pin，不返回源码/预期正文、不发送来源。

生成输入是全部 ContextPack（包括所有原分包）、完整 scope 和完整义务集，原全局规则与独立 oracle 不变。当前为一份完整响应；超过本地 tokenizer/模型容量、费用或 wire 限制时拒绝，不减少 AC、规则、事实、风险或负例。多批执行尚未实现，此阻断不算完整容量验收。

项目管理员必须确认上述整个请求，15 分钟内的 canonical confirmation 才能首次预留。`execution` consent 固定模型、实际 tokenizer 资产、价格策略、来源权限和预算。调用前在 PG 项目/ACL/账号/模型锁内重新校验，追加 `quality_test_design_call_reservations`，预留全部配置容量而非乐观估计；并发同 invocation 仅一个调用获准。确认本身不是其他模型或后续源修订的通用出口授权。

OpenAI / compatible / Anthropic / Gemini 使用原生结构化请求，最大 120 秒；不提供工具、不跟随重定向、不重试、不 fallback、不修复输出。Provider usage 必须是正整数且位于确认的 input/output envelope 内；Anthropic cache 输入和 Gemini thought 输出也计入使用数。不将本地估计冒充 usage，也不将 operator rate ceiling 冒充 Provider 发票。

完整响应先进入私有 MinIO 工件，再在同 PG 事务追加 `quality_test_design_native_replies`、LLMCall 和 metadata-only Outbox；两张表禁止 update/delete。随后调用 0058 用例/覆盖原子提交。结果事务失败可以恢复已归档原始响应，不能第二次请求模型。断线、取消、usage 缺失/超限或响应落库失败保留预留与失败审计，结果未知时禁止自动重发；不伪造已完成。原生响应已归档也不意味着输出语义已通过，仍需完整严格 JSON/oracle 校验，生成结果仅为 draft/planned。

模型返回后、私有工件写入前再次检查当前输入、来源权限、账号和模型；回执提交在 PG 项目/ACL/账号/模型锁内再检查。中途撤权或修改依据时不提交成功回执或草稿，保留原预留及失败审计；已写出的未引用私有工件不是业务结果。恢复先检查原确认来源的当前可见性，再读取响应，并按原固定价格策略重算 usage 与回执摘要。负数、布尔值、缺失等非法计数不能使失败审计本身异常；这些计数记为 unavailable，不伪造实际用量或退还预留。

0059 的内部恢复端口只适用于仍为 running 的原 canonical invocation；再次 confirm 不能重开 failed 命令。0060 已通过 Temporal 生命周期及独立 `quality.test_design.recover` 接通有归档回复的终态恢复，固定原请求/响应 hash、当前原 actor 权限及新确认命令。原 failed 命令不改写，未知回复不重发，具体见[任务恢复协议](./generation-jobs.md)。不能把直接调用内部端口或只有预留的夹具当成已完成恢复。

管理员通过 `NASUS_GENERATION_MODEL_POLICIES` 指定可信部署配置文件，根为 `{schema: "nasus.generation-model-policies.v1", profiles: [{policy: ...}]}`，每个 config_id 恰好一个 profile。`GenerationModelPolicy` 要求 policy/revision、固定 provider/base_url/model、context/output token 限额、currency 和每 token 纳币率、framing 以及 tokenizer 身份/hash；这里的纳币是所选币种的十亿分之一。tiktoken 固定 0.8.0 并验证 mergeable ranks digest；`huggingface_json` 固定 tokenizers 0.21.4，并验证管理员本地 tokenizer JSON 的 SHA-256，禁用截断和 padding。HTTP/模型不能传配置文件路径或价格。没有 profile、模型不匹配或 tokenizer 无法验证时阻断，没有默认假价格。`.env.example` 默认空值，开发模型 fallback 不被该执行器接受。

canonical handler 与 Agent 工具发现已接入，消费预览回执时重新检查；0060 Temporal 生成 workflow 已验证。独立 Portal 表单、任务历史、取消和归档恢复经深浅色专项及固定 exweb 浅色复验；0061 reviewer 队列和独立映射审阅另行验证。浏览器生成 transport 为明确协议夹具，完整回归结果见实施记录；真实模型质量、维护者 business oracle 和真实目标执行仍需独立验证。合成 reviewer 的映射决定不冒充真实业务 gold。

exweb 验证中的伴随需求、审阅、候选响应及 0058 原生成功调用审计都是明确测试夹具（合成 token 数，不是实际消费），不是维护者业务批准、真实模型输出或目标运行证据。0058 验证使用真实隔离 PG/MinIO，但不调用外部模型。详细命令结果见[实施记录](./implementation-progress.md)。
