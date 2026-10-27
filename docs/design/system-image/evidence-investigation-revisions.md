# 固定画像的证据调查修订

更新：2026-10-08。0084 新增追加式调查记录和同一 AgentGoal 的结构后续调查，0085 增加用户快照预条件与持久结构继续消费回执；调查策略 v2 增加固定文档的显式引用候选与原目标的独立查看关口。这是完整 P2 的增量，不是自主系统画像、业务准确率或上线验收完成证明。完整范围继续以[主方案](./autonomous-system-image-design.md)和[交付门禁](./delivery-and-evaluation.md)为准，实际批次见[实施记录](./implementation-progress.md)。

## 所有权和固定输入

`system_image` 保存调查工件，`agent` 保存原目标和执行步骤，平台保存 canonical 调用、确认与审计。Agent 通过 application port 读取调查建议，不直接访问画像 repository；纯领域评估不依赖 ORM、LangGraph、Temporal、存储或模型 SDK。

输入必须固定 project、plan ID/digest、原 goal、image revision/hash；可选 parent revision/hash 必须成对提供。画像必须是该计划与目标基线的实际结构工件，或经过最多 16 层同基线父链核验的子候选；同一 manifest 下任意其他候选不够。来源权限、计划归档、画像完整成员和目标会话每次重新核验，不重新采集工作区，不选择可变 latest，不接受 Provider 私有 ID。

调查读取最多 8 项精确 `(object_id, evidence_id)`，每项实际经固定画像证据 use case 展开最多 20 行；保存 source revision 和已校验 result hash。未显式选择时优先文档，再按固定对象 ID 选择。原文仍从不可变私有归档读取；PG 调查工件只保存有界结构和证据 pins，不复制源码或文档正文。

## 调查结果与无进展

结果保留实际 inventory、证据样本、问题、原因、缺口、下一工具及固定参数、验收条件。v1 仅建议 `query.system_image.revisions.read` 和 `query.system_image.revisions.document`；每项最多一次、模型调用为 0，文档建议最多 4 项。采样/分页/更多文档的截断必须显式保留，不能把对象数或第一页报告成完整扫描。

新根调查使用 `nasus.image-investigation-revision.v2`。当原清单同时包含已捕获的 US 与测试来源、画像中存在冻结文档成员时，另建议 canonical `system_image.links.propose_references`：只固定原 project/image，不调用模型、不运行目标代码，不借用结构授权。没有文档成员时保留 `reference_source_projection_missing`，不补造对象；缺可选来源时也不假称完整三源关联。建议受原 ceiling 约束，超限保留缺口。旧 v1 记录、digest 和父链回放不升级；新子修订继承原父策略，未知策略或链内策略变化拒绝。

缺口区分缺少来源证据、legacy 观察、有界样本、缺少可选 US/测试、未审阅文档语义、批准 oracle 未解决、真实运行证据未解决及独立发布审阅。readiness 各维度的 coverage 均为 null；结构成员核验不是结构或业务覆盖率。

每个修订累计保存已观察的单项证据签名和画像 hash。改顺序、子集或在两个旧样本之间交替不会制造新进展；三轮没有新增画像或证据后保存 `paused_no_progress`，只有经验证的新证据才能再次推进。历史回读重新推导规则、父链与原文摘要，不修复或改写历史。

`consumed_review_calls` 统计调查修订数，剩余建议数受原 plan 的工具上限约束，最多 80 个修订。这是调查建议 ceiling，不是全计划、多能力、总时间或费用账本；前面的结构工具、全部后续查询和其他模型成本尚未统一计入这一字段。不得称为完整自主预算。

## canonical 写入与 PostgreSQL

- `system_image.build.investigate` 是独立 `user_confirm` 写动作，不继承结构构建授权。当前要求 reviewer 角色、活跃认证账号和完整来源权限；确认固定原调用/请求/会话/goal，15 分钟有效且非未来。
- `image_investigation_revisions` 为 append-only；复合 FK、唯一 invocation、同 goal/plan 修订号及 parent CAS 防止并发分叉。提交锁定项目与原 goal；终态 goal 拒绝新调查，Agent 发起的调查要求目标仍 running。
- 修订和无正文 Outbox 同一 PG 事务提交，晚期撤权或 Outbox 失败回滚。不可变记录不可 update/delete；存在记录时拒绝破坏性降级。迁移不修改既有结构授权或计划。
- `query.system_image.build_investigations.read` 只保存 revision ID/hash 回执。私有 GET `/v1/projects/{project_id}/system-image/build-investigations/{revision_id}` 每次重新授权与核验，`private, no-store`，不暴露存储地址。读取和刷新不是授权。

## 原目标的继续与恢复

1. 原结构命令实际提交候选后，goal 暂停在 `structural_candidate_review`，不是完成或发布。
2. 用户点击“继续证据调查”才核验原结构 canonical 结果、目标/计划/基线及实际归档。完成原 blocked 结构步骤、追加调查 Act/Observe 和控制状态一次持久化，保留原 goal 与所有已执行 invocation。
3. 此次继续只准备 `system_image.build.investigate`，停在自己的 `waiting_confirmation`。原结构 budget/grant 不增加，不为调查创建结构授权预留，不运行模型或仓库。
4. 用户另行“确认证据调查”才保存调查修订。Agent 回读实际工件，将保存的有类型缺口任务扩入原计划；按完整参数去重，不因工具 ID 相同丢弃不同分页或对象。
5. 只有只读任务的原 v1 和缺可选输入的调查，在有界查询结束后停在 `build_completion_review`。v2 的显式引用候选提交后先停在 `reference_candidate_review`；completed ToolInvocation 与 blocked AgentStep 含义不同，不能把查看按钮显示为再次执行高风险确认。
6. 用户点击“查看引用候选”才验证原调查策略、canonical 请求/回执、同 Goal/会话/阶段、固定 image/hash、proposed 报告和当前来源权限。准备阶段实际读取 assertions 与 gaps 的完整分页，每页最多 50 条；遇到 64 KiB 字节上限时逐次缩小条数，单条仍超限则拒绝，不截断证据或丢弃候选。各页必须保持原报告摘要、画像与状态、完整计数及连续游标，零项区段也保留一次查询。只有完整预检通过才追加原计划，canonical 查询执行时重新授权；完整页计划超过原 step ceiling 时拒绝推进，实际每项工具仍经原累计预算 admission。预检读取不是新的业务写入或关系批准，也不代表额外开销已计入完整模型／能力费用账本。
7. 原 blocked 引用步骤的完成、全部追加步骤和用户 checkpoint 消费在同一 PG 条件事务保存。并发中断不被覆盖，提交后失联重建 gateway 从原步骤恢复，重复旧 pin 不再派生报告或确认新 gate。完成全部查询后仍停在 `build_completion_review`，没有接受关系、批准 oracle、冻结、发布或执行。generic LLM replanner 不得用旧可变物化链替代调查。

提交继续 checkpoint 后进程失联时，由已保存的原结构 Observe 和新增步骤恢复，不重跑结构或新建 goal。LangGraph PG checkpoint 只保存游标，业务状态和工件仍是权威；测试会重建 gateway 后核对原命令、候选及修订只有一份。

Portal 每次按钮操作先重新 GET 原 goal，检查 paused 状态、项目/会话、pause reason、唯一 blocked step、工具及 invocation ID；不匹配则不 POST。同步 action lock 防止本页面重复点击。操作 finally 只等待当前会话快照回读，并核对原项目/会话及 goal 成员；辅助 dashboard/project/画像面板异步刷新，不以这些面板的完成作为确认状态权威。会话 refetch 必须抛出错误，失败时隐藏缓存的 goal 控件，不用 Query 缓存旧数据绕过读取失败。回执丢失不自动 resume/confirm；显示新步骤后必须由用户点击新的明确确认按钮。相同失败 gate 禁用，需重新加载验证。该客户端检查不能替代服务端条件写入；0085 将原用户快照继续传入 POST 和 Worker，具体范围及剩余事务窗口见下文。

完成审阅的普通继续是无操作：Temporal gateway 核验权限范围、用户 checkpoint 和消费回执后返回已结算的 PG aggregate，不发送 signal，也不等待一个本来就不应发生的状态变化。没有持久 reader 的 query 路径同样识别完成审阅，旧 pin/错误 scope 仍拒绝。此处不把完成审阅改成 completed，不重置计时，也不授予发布权。

历史调查回读在一次 operation 内复用既有 `verified_read_session(reuse=True)` 的固定元数据，避免每个父修订重新加载整份 provenance；原文仍实际读取并核验 hash，来源 ACL 与项目角色仍实时重新检查，不创建跨请求批准/权限缓存。平台按 conversation/goal/tool/status 先筛选调用和审计历史，再对选中项执行原授权；创建时间排序只扫描一次创建审计历史，仍保留最早创建事件及旧无事件 fallback 顺序。它消除对无关私有归档的验证，不省略目标记录的访问检查；全局元数据列表仍需扫描，未替代完整 SQL 分页/容量或 p95 门禁。

### 结构继续提交的条件写入

2026-10-07 后续新增 `nasus.agent-resume-checkpoint.v1`：显式固定当前 AgentGoal v1 字段、完整步骤与工具输入、目标/会话/workflow、意图及预算；摘要只保留 scope 和 SHA-256，不复制私有正文。输入限 512 步/512 KiB、规范 JSON，不接受缺字段、新增未版本化字段、NaN 或非 JSON。该检查点不是工具确认、来源访问许可或执行授权。

原结构候选继续在编译新步骤前捕获摘要，准备完成后经 application port 提交。生产 PG adapter 在同一事务锁定原 goal 行、重新加载完整 aggregate 并比较摘要，再保存旧步骤消费与新增步骤；不存在的目标不能被恢复动作重新创建。条件写入要求从 paused/blocked 消费到 running，不允许用无变化写入假装消费检查点；同一检查点两个并行条件提交只有一个成功。变更被发现时 HTTP 返回 `agent_checkpoint_changed` 409，保留已经提交的新状态，不回退预算、输入、调用引用或暂停原因，不创建调查调用。缺少条件写入适配器时拒绝，不回退到普通投影写入。Local 和 LangGraph PG 委派均经过此路径。

0085 之前的条件提交只保护服务端“编译结构后续步骤 → 保存继续状态”窗口，未提供用户快照 DTO、Temporal 贯穿或持久消费去重。0085 补齐下列部分，但普通 goal 写入尚非全局 revision CAS；goal 事实和后续 audit/Outbox 仍不是同一事务。治理确认及其余生命周期提交窗口仍须继续补齐，不能称为完整原子恢复确认。

### 用户快照与持久消费回执（0085）

- `POST /v1/agent-goals/{goal_id}/resume` 接收 `{expected_goal: <用户所见完整 AgentGoal v1>}`。当前权限检查先于预条件处理；固定画像计划缺少快照返回 `428 / agent_checkpoint_required`，字段、预算、完整步骤或暂停状态变化返回无私有详情的 `409`。非固定画像的旧 bodyless API 保持兼容，不用此兼容绕过固定画像策略。
- Portal 重新 GET 只做提前检查，POST 仍发送原展示快照，不用新读取的预算或输入替换用户所见值。没有显式快照的旧前端调用先 GET 再明确发送。服务端规范化为五字段 scope/hash，完整私有 DTO 不进入 Temporal signal 或消费表。
- checkpoint 贯穿 application port、Local/LangGraph PG、Temporal signal/activity。生产 AgentLoop 同样拒绝固定画像目标的不带 pin 信号；队列 schema 严格校验。过时、缺失或非法预条件由 Activity 返回有类型拒绝，不无限重试、不确认工具；瞬时基础设施失败仍按 Temporal 策略重试。
- 聊天确认通过明确的 goal 查询 port 读取当前 aggregate，核对会话/项目、唯一 blocked acting step、工具和待确认 invocation。固定画像目标随后捕获检查点并经同一恢复 port 传递，不能使用旧 bodyless driver；明确指定的旧工具 ID 不选择新的待确认工具。独立无 goal 工具及非固定旧计划保留 canonical/旧恢复兼容。聊天 pin 是服务器解析当前确切命令后的状态，不冒充前端用户所见完整 DTO；这条路径仍不替代下述治理事务/CAS。
- `agent_resume_consumptions` 记录已条件消费的原 goal/digest、会话/项目/workflow、transition digest 和 receipt hash。结构继续首先接入；后续非确认分支增量也将显式检查点的无调用预算释放与补源重试接入同一 row-lock 事务。原 goal 全步骤与消费记录一起提交，PG 禁止 UPDATE/DELETE；不回填伪造旧消费历史，有记录时禁止破坏性 downgrade。同一 digest 已有回执时拒绝再次提交，即使旧 paused 快照被其他路径恢复，也不能发生 ABA 再消费。
- 结构继续重试先检查不可变消费回执及当前 scope。已经到达下一确认或终态只返回当前状态；仍 running 时可以沿已保存步骤恢复，不确认新 gate、不重新编译结构步骤。回执不是新工具的确认、执行许可或来源授权。
- Temporal cursor 不再经旧 sink 覆盖 PG aggregate；生产 Gateway 返回重新读取的业务事实。Workflow 保留已处理的 pin，重复旧信号不能变成下一 gate 的确认。上一请求的冲突 projection 不阻止新有效 pin，但当前请求自己的拒绝仍返回错误。实际 Worker 更换、提交后故障重试、排队后状态变化及 Workflow history replay 的证据见实施记录。

### 非确认恢复分支增量

无 tool invocation 的 `budget_exhausted` 分支，在清理 blocked step 后，传递原 `expected_resume` 做完整条件提交；`missing_source_binding` 分支把原调用引用清理、pending 状态和 attempt 递增合并到同一次提交，不先普通写 running 再写重试步骤。显式检查点冲突时保留当前预算、输入、workflow 与中断状态，不发恢复步骤事件，不消费摘要。已提交后失联可用原检查点回读已保存步骤，不再次递增 attempt，也不确认随后到达的 gate。非固定旧计划没有显式检查点时保留既有恢复接口，不将兼容写入伪记为条件消费。

该增量不实现 BuildIntent 补源计划修订或来源重新绑定的完整业务引导，不代表新固定画像计划已经支持所有补源场景；测试区分直接 PG 准备分支与 Local/LangGraph PG 公共预算 API 链。治理确认分支、无 blocked step 的恢复、失败/预算仍耗尽路径和其他生命周期写入尚未统一到相同 CAS/事务。

范围限制：消费回执不是所有恢复命令的统一账本；无全局 goal write epoch/owner fencing，普通状态写、治理确认与工具 admission/dispatch 尚未统一到相同 CAS/事务。并行 driver、所有生命周期事件和事实/审计/Outbox 原子提交仍待交付。真实测试的 Worker 停止/重建及 Activity 重试不等于 OS SIGKILL、跨主机或全部恢复分支验证。

SSE 的历史 goal/step 状态不再覆盖最新 GET 快照：旧 `agent.goal.updated` 与 `agent.step.updated` 触发重新读取，不安装历史状态、工具输入或确认引用。thinking/observation/decision delta 只允许在已有步骤上延长对应展示文字，不改变步骤控制状态；消息 token 仍按原流式 reducer 渲染。该修复防止重放重新显示已消费的结构确认，不能代替上述服务端 CAS。

沿用 AI Studio 风格和共享主题，仅确认卡片增加局部窄屏纵向布局和桌面按钮单行规则；没有重新设计 sidebar、composer 或全局 token。

## exweb 证据与剩余范围

真实测试固定干净 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`，通过真实 CBM CLI/MCP、PG、LangGraph PG gateway 执行两种入口：直接调查，以及原授权结构 goal 的继续/独立确认/缺口任务。两者均保留原始 native partial/gap；每入口 2 次 index/2 次 MCP，755 entities/1425 relationships。调查及后续历史回放不重启 Provider，模型调用为 0，最终仍暂停审阅。

最新原生报告为 `.nasus/validation/exweb-investigation-continuation-final-20261007.json` 和 `-original-goal.json`，明确 local isolated object adapter、未外呼真实模型、未执行 exweb、非 business gold及有界采样不证明覆盖。PG/MinIO 原生业务试点、独立语义 gold、容量和性能不能由这两个协议专项替代。

测试运行器新增显式 `--minio` 模式：必须单独提供本地测试 endpoint/凭据，创建随机私有 `nasus-test-*` 桶，不接受开发桶名称、不复用未声明的开发凭据。仅清理实际创建成功的桶，失败创建不删已有桶；测试失败也执行有界清理和关闭客户端。默认 PG 测试仍使用原隔离本地对象适配器。原生 exweb 专项现在可独立通过新 ObjectStorage 实例回读全部来源清单/文件和冻结画像，逐项验证实际 S3 引用及 SHA-256；报告区分 `minio_s3` 和 `local_isolated_adapter`，不以环境标签或 API 成功响应代替远程正文核验。`exweb-investigation-minio-20261007.json` 和 `-original-goal.json` 对应两项实际通过的 PG/MinIO/CBM/LangGraph PG 测试，每入口独立核验 130 个唯一远程引用；此验证不是完整业务试点，确切批次及剩余门禁见实施记录。

接入条件继续提交后，当前 `exweb-investigation-checkpoint-cas-minio-20261007.json` 和 `-original-goal.json` 两入口复验再次通过；原 goal、独立调查确认、等待审阅、130 个远程 hash 核验及 Provider 重放边界保持。HTTP 竞争与数据库并发专项分别证明准备期间变更被拒绝和同检查点只有一个条件提交成功；原生 exweb 正向复验不单独证明并发、旧页面预条件或真实 Temporal 恢复。

0085 后的原生 MinIO 报告新增消费回执 scope/digest/hash，以及在独立确认前、调查完成后重放同一旧用户快照的实际断言。聊天复验报告另记录 `independent_confirmation_channel=chat_public_turn`，由真实消息 POST/Turn 查询完成原 goal 的独立调查确认，而非直接调用私有 service。最新报告与终态批次见实施记录，仍不包含外部真实模型、目标执行或语义 gold。

还须继续完整 BuildIntent/plan revision、补源恢复同目标、动态行为/三源语义与反证调查、全计划授权/成本/时间账本、所有任务租约/取消/恢复、其余 Temporal AgentGoal 恢复分支与进程强杀、全链原子 checkpoint 恢复确认、调查成果详情与完整发布引导。完整 P0/P1 来源切换和 Provider 隔离/对照，P3 authority/gold，P4 自动增量/overlay/合并，P5 五用途/旧链切换/脚本/RunPlan/真实运行反馈，P6 最终门禁全部保留。
