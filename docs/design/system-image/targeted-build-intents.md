# 固定目标的构建意图

状态：2026-10-08 已接入 v3 计划、canonical 保存、结构授权与执行、补源阶段及 Portal。已保存意图的 UI／显式聊天入口使用同一 Agent 编译器；完整引导、自然语言、维护事件三入口尚未统一。完整范围仍以[主方案](./autonomous-system-image-design.md)和[交付门禁](./delivery-and-evaluation.md)为准，验证记录见[实施进展](./implementation-progress.md)。

## 意图与目标

`nasus.image-investigation-plan.v3` 在原来源清单、目标描述、initialize/enrich/refresh/repair 模式、structure/behavior/traceability 用途和建议预算之外，保存以下不可变字段：

| 字段 | 含义 |
| --- | --- |
| `target.project_id` | 与计划相同的项目 |
| `target.target_baseline_id` | 保存前明确选定的基线，执行时不能替换 |
| `target.target_version_id` | 基线所属版本；无版本时必须显式为 null |
| `target.expected_head_id` | 选定基线当时的知识发布头；没有发布时显式为 null |
| `target.expected_head_hash` | 原发布的 image artifact SHA-256；与 head ID 同时存在或同时为 null，不是 publication payload 摘要 |
| `scope_binding_ids` | 固定 manifest 的全部 binding，与 `sources` 一一对应、顺序一致，不是当前可变来源列表 |
| `expected_head_status` | 固定为 resolved；不把未检查的 null 当作“确认没有发布头” |

标识拒绝空值、控制字符和超长输入；摘要只接受规范 SHA-256。原 v1/v2 序列化和 digest 保留，不追加目标字段或重写历史计划。旧 canonical 客户端仍可保存 v2；当前 Portal 新建计划必须显式选择并核验目标后保存 v3。autonomy policy 仍为 guided，目标固定不授予自主模型出口或执行权限。

## 来源与授权

代码是结构构建的必需来源，需求和历史测试是可选来源。缺失、失败和未采集来源继续形成显式 gap，不伪造已关联、批准或覆盖。保存计划只提出预算和工作，不运行 Provider、模型或目标代码。

`system_image.build.plan` 仍是唯一 canonical 保存入口。事务内校验原命令的 objective、mode、purpose、预算、manifest 和完整 target，拒绝把合法命令用于保存另一份意图。目标查询和保存均检查当前项目与来源权限；有发布头时还检查原发布画像的完整来源权限，即使计划本身只选择了代码来源。

结构执行授权仍需独立确认，绑定原 goal、plan digest、来源、目标和预算。首次授权、工作预留、结构提交都检查保存目标的 baseline/version/head。目标版本改变、原来空的发布头被推进或其他基线被替换时，必须重新准备计划，不能自动改绑旧意图或复用旧授权。

## 查询与历史

`GET /v1/projects/{project_id}/system-image/build-targets/{baseline_id}` 返回当前经过验证的目标，使用 `private, no-store`。显式 nullable 字段不可省略。基线引用不存在或跨项目的版本时拒绝返回可用目标；发布头损坏返回脱敏 502，发布竞争返回脱敏 409。

历史计划仍固定原 target：当前 head 或 baseline version 推进不会改写旧计划。读取带 head 的历史意图重新验证原 publication ID/hash 及当前权限，不要求历史 head 仍为当前 head；执行才要求目标未漂移。历史可读不等于可继续执行。

只读目标范围校验不申请行锁，避免在保存事务的最终权限回调中通过第二条连接等待自己的基线锁。写入路径在项目 mutation lock 下锁定并重新验证 baseline、version 和 publication head；发布内容同时使用原生 publication 完整性与来源登记校验。

## 补源与原目标恢复

[补源修订](./build-plan-revisions.md)继承 v3 原 target、head、objective、purpose 和建议预算，只扩展已采集来源 scope。它不自动改目标、不复制旧执行许可，也不因加入需求或用例改变用途。

[追加阶段](./image-plan-phases.md)仍在原 AgentGoal 上保存完整历史 prefix，阶段确认、显式继续和新预算确认相互独立。新的结构阶段消费新计划，不以旧快照释放新许可。Local、LangGraph PG 和真实 Temporal 的验证范围分别记录；Worker 更换和 Activity 重试不等于 OS 强杀或所有能力恢复。

## Portal 行为

新建表单先显示空目标选择，没有默认替用户选择。目标查询成功后才允许保存；失败隐藏可用 pin、保留不可提交状态，用户明确重读后才恢复。建议预算仍需独立授权。

保存后的计划展示固定 baseline/version/head，结构目标选择锁定为原基线；旧 v1/v2 计划继续保留原兼容行为。前端验证 v3 policy、resolved head、完整 source scope 和 canonical 回执的原目标，不自动重试写入或回读新头来替换用户展示的目标。继续沿用 shared 深浅色、弹层和无滚动条滚动布局。

## 已保存意图的共享 Agent 入口

`AgentBuildIntentEntryApplicationService` 把已保存 v3 意图规范化成同一个 `system_image_build` Goal proposal。Knowledge 中的 `Build with the agent` 默认折叠，显式点击后提交项目、计划与摘要三项固定引用，不提交调用方步骤或确认。聊天支持完整独立命令，例如 `start build_plan:<id> digest:sha256:<64 hex>` 或 `执行构建计划 build_plan:<id> 摘要:sha256:<64 hex>`。省略摘要时从经过授权的保存记录取得；已有摘要不能被替换。这不是完整自然语言目标解析或维护策略。

两个 Planner 在模型与旧可变编译器之前调用此 application port。识别到显式命令前缀但 ID、摘要或尾部指令非法时只返回澄清，不落回 LLM／旧流程；引用、文档说明和问题不作为此执行入口。有效请求重新核验项目、来源权限、v3 digest、当前原目标、完整 immutable manifest 和结构 work item。已有活跃 Goal 的复用也重新核验原输入并拒绝另一计划；调用方不能绕过编译器增加工具步骤。

服务端创建使用独立 persistence port：在同一 PG 事务锁定已有 Conversation 行，核对项目及全部活跃 controller，再插入完整 Goal。空会话也有可锁行，两个 API／Worker 进程不能同时通过“无活跃 Goal”检查；竞争失败返回原 controller 的 ID，不启动第二个图。application 重新读取该目标并核验原保存意图，另一计划或多余／重复 target refs 拒绝复用。多个旧 controller 是显式冲突，不能按时间任选一个。正式创建与更新分开，更新／恢复仍沿原规则；没有修改历史 Goal 或补造并发记录。

后续 0088 的[持久启动回执](./agent-goal-start-receipts.md)将 Temporal controller、原始请求摘要和 Goal 同事务固定；同 workflow 的已暂停／终态重试只读原目标，失败者返回类型化 ID 冲突，不改绑 controller。真实 Activity ID 不能被载荷中的 workflow ID 替代。pending/running 的重放明确要求执行恢复，不盲目重跑图。

这一创建互斥和内部启动回执仍不是公开请求的持久幂等键，也不是完整 dispatch outbox／owner lease：创建提交后、审计或图内崩溃的完整恢复、API 首次启动失联及不同请求终态重放仍需独立交付。不会为竞争或重试请求自动确认预算、继续暂停目标或发布画像。

编译出的初始步骤固定为 `query.system_image.build_plans.read → system_image.build.authorize → system_image.build.structure`。第二步仍是独立 canonical 确认，预算仅一次结构工作、零模型调用、零模型费用及不超过原计划／Goal 的主动时间。入口本身不创建执行授权，不重新采集来源，不发布画像。结构后的证据调查、补源阶段与新预算继续沿原 Goal 的既有独立门禁，不由入口释放。

前端严格检查回执的原会话／项目、恰好三项 target refs、原三步 prefix、目标与结构预算。允许原 Goal 后续追加步骤，不允许扩张初始引用。提交前保存按当前账号／项目／计划／digest 隔离的 sessionStorage 恢复标记；丢失回执或错配后只能重新授权原计划并 GET 原会话，刷新也不重发 POST。存储不可写则不提交 Goal。该标记是 UI 的只读恢复线索，不是权限凭证、跨标签页幂等键或服务端并发创建 fence。

Local、LangGraph PG、公共聊天 Turn、真实 Temporal Worker 更换／重试和固定 exweb CBM/MCP 均有分开的验证证据，见实施记录。浏览器的改写回执负测只改传输响应，仍核验真实 PG Goal 与零执行授权，不能冒称服务端生成了错误 Goal。

## 尚未完成

有界的当前项目请求和引导入口已接入[固定来源准备及缺码恢复](./source-pinned-build-entries.md)，普通准备和补源等待恢复分别核验六项和七项固定引用；上文三项引用只适用于已保存计划的直接入口。缺少代码时继续原 Goal，不自动确认后续预算。这一增量不等于任意自然语言、另一版本选择或维护事件统一。

这一契约不能替代完整三入口统一、来源注册表 cutover、代码刷新及 lineage、全计划多能力预算、动态反证调查、完成到发布的完整引导。自动 delta/overlay/合并、五类 ContextPack、脚本与 RunPlan pin、受控真实运行、Provider 对照与独立 gold/性能及 P6 试点均继续保留。exweb 的结构投影与补源执行证据不声明业务规则正确或已验证测试覆盖。
