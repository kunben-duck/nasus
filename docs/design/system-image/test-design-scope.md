# 固定测试设计范围审阅

状态：0057 后端领域、application port、PG/MinIO 和 canonical Tool/HTTP 接入，2026-09-20。属于完整 P5 的必要依赖，不代表正式生成、CoverageMatrix、执行或上线验收完成。遵守[用途契约](./knowledge-contracts.md#5-用途上下文包)。

## 权威与输入

quality_loop 拥有独立的 `TestDesignScopeRevision`，通过 `ScopeContextPort` 读取 system_image 的归档上下文，不访问对方 repository。输入固定 `project_id / context_id / context_artifact_hash`，审阅按这个 context 独立建链；新 context 不继承旧批准。

批准要求归档来自 v4/v5 已发布画像、全部来源 AC/业务规则有独立批准的 observable oracle，且归档的当前依赖尚未失效。来源代码、模型回答和历史用例不能代替用户确认。`authority_basis=user_confirmed_test_design_scope` 与原来源 AC/规则批准分开保存；这里只批准审阅者填写的测试设计义务，不更改原规则的期望。

`contract` 必须包括：

- `risks`：风险边界及四项 oracle。
- `permissions`：actor、operation、resource、allowed/denied 和 oracle。
- `transitions`：from_state、event、to_state 和 oracle。
- `invariants`：历史不变量和 oracle。
- 上述每类都需 `applicability=applicable|not_applicable`、非空 `rationale` 与 `items`。applicable 必须有条目，not_applicable 必须没有条目，不以空数组默认为已检查。每个条目有全范围唯一的 obligation_id、原约束 constraint_ids、已固定的 evidence_ids；用户独立确认的新义务可以没有额外代码证据，但必须引用原要求。
- `examples` 恰好覆盖全部 AC 和全部业务规则。每项有正例 oracle；负例必须提供 oracle、明确不适用理由或 `negative_gap_id` 三者之一。待确认负例只能引用覆盖相同约束的实际 gap，不能使用“不适用”隐藏未知。
- `reused_case_ids / reuse_assessment`：只能选归档中 asserts 召回的测试候选，必须说明复用判断。它仍是候选引用，不授予正式用例批准或覆盖率。
- `conflicts / conflict_assessment`：每项固定关联约束、说明和 resolution。未解决项的 resolution 为 null；即使没有发现冲突，也必须提供审阅说明。
- `gaps`：固定约束和说明；所有显式 gap、未解决冲突进入 blockers，不因记录了 approved revision 就算作范围完整。

数量上限为每个维度 256 条、例子 256 条；文本字段最多 2000 字符，整个私有工件最多 1 MiB。超限拒绝，不截断强制范围，也不把这个字节上限称为模型 token 预算。

## 命令与查询

写动作仅走 `quality.test_design_scope.review`，必须另行用户确认，项目角色为 qa_lead、project_admin 或 platform_admin。输入包括上述 context pin、`expected_previous_revision_id`（首个必须显式 null）、`decision=approve|withdraw`、`contract`、`reason` 和 `policy_revision=nasus.test-design-scope.v1`。withdraw 的 contract 必须为 null，且当前 head 必须 approved。撤回允许原 context 已 stale，但仍须读取原工件并满足当前 ACL。

只读入口：

- `GET /v1/projects/{project_id}/quality/test-design-scopes?context_id=...`：当前头、历史元数据和经过验证的当前内容。
- `GET /v1/projects/{project_id}/quality/test-design-scopes/{revision_id}`：原审阅内容、固定 context pin、assessment 及单独计算的 current_use。
- `query.quality.test_design_scope`：只给 Agent 固定 ID/hash/status、当前适用性及 blocker 数量的 receipt，不在 Planner 持久观察中复制来源正文。观察在使用时重新验证；即使 scope head 不变，原 oracle 或画像发布 head 改变也使旧当前适用性回执失效，需重新查询。

HTTP 响应均 private/no-store，没有额外 HTTP 写入旁路。新增两个工具保留原 Tool Catalog ID 和治理；中英文范围审阅意图可发现它们。普通生成/执行意图不应被审阅工具长说明中的禁止条款挤出既有工具。

## Portal 审阅

已归档上下文内提供“检查测试设计范围”，不是从未保存的 preview 创建权威。`domains/quality-loop` 拥有 DTO、固定 pin 校验、草稿校验和查询/确认命令，知识路由的 `scope` 小组件只渲染表单。沿用现有深浅色 token 和移动端布局。

各维度初始没有适用性结论；必须填写理由，并添加有固定约束引用和独立 oracle 的义务，或明确评估不适用。正例预填原已批准 oracle，提示仍须独立审阅；负例初始未评估，只能填写 oracle、明确不适用理由，或关联覆盖同一约束的显式 gap。不能删除某个 AC/规则的例子来缩小分母；删除被引用 gap 后必须重新评估负例。提供用例候选选择、复用说明、冲突及解决说明、gap 表单，不使用 JSON 编辑器替代这些字段。

保存通过 `quality.test_design_scope.review` 创建 waiting_confirmation invocation，再确认原 invocation。客户端按完整草稿、理由、context pin、scope head 和查询更新时间绑定勾选确认；修改或刷新会清除确认，没有自动重试写操作。未知结果提示先重新读历史，不推断“未保存”。已停用权限/失效上下文的最终裁定仍在后端事务内。

显示当前适用性、显式 blocker 数、审阅者、时间和 invocation。可读取旧版本和撤回当前 head；旧内容不改写，不把 approved 标签等同于完整性或生成许可。读取使用 abort signal、no-store、零闲置查询缓存；加载时隐藏旧内容，pin/assessment 不匹配或授权读失败使父检查器清屏，需显式重载。浏览器专项结果见实施记录，不能以构建通过替代交互验证。

## 一致性与恢复

PostgreSQL `quality_test_design_scope_revisions` 保存摘要、链、确认人、invocation 和私有工件引用。状态 approved/withdrawn 通过追加新版本表达；触发器禁止 UPDATE/DELETE，有记录时拒绝破坏性 downgrade。首版本、sequence、previous_revision_id、invocation 各有唯一性约束，应用层校验完整链，最多 1000 个历史版本。

MinIO namespace 为 `quality/test-design-scopes/<project-hash>/<content-hash>.json`。工件包含完整请求、原 context/image/input pin、范围校验结果及审阅者/invocation/时间；读取校验 namespace、字节 hash、schema、请求摘要、元数据、完整历史 context 和逐项范围推导。

提交按固定顺序取得项目快照锁和来源 ACL 锁，锁定实际账号、项目角色及 canonical ToolInvocation，校验确认人和完整请求。范围 CAS、当前 context/head/oracle/检索/ACL 复查后，版本、业务审计和 Outbox 在同一事务提交。停用账号、撤销角色、旧 head 竞争、预写工件后改变依据或 Outbox 失败都不提交版本。ToolInvocation 的通用投影由原 runtime 负责，不能把业务事务和 MinIO 预写声称为跨服务 exactly-once。

同一 invocation 恢复只返回原版本，并重新验证当前访问权、固定请求和历史工件；之后撤回不被恢复重置为 approved。历史内容不被新的 authority/head 改写，但 `current_use.scope_current` 会变为 false。缺权限或原证据/工件损坏则拒绝返回，而不是降级暴露旧内容。

`resolve(project_id, revision_id, artifact_hash)` 是下游 application port：核验精确版本与当前适用性。它不是生成许可；消费者还必须检查 `scope_complete`、全部 blockers 和自己的费用/模型/执行门禁，并在正式提交时再次核验。旧 ContextPack 的 readiness 和 `generation_authorized=false` 保持原样，不改写历史以制造“ready”。

## 验证与剩余工作

纯领域测试覆盖完整分母、未知引用、重复项、明确不适用、负例 gap 与阻断；隔离 PG/HTTP 测试覆盖确认、权限、CAS、撤回、回执、恢复、事务回滚、不可变表和迁移保护。exweb 的三源 PG/MinIO 验证新增固定 v5 context 的独立范围工件、风险/权限 oracle、显式负例 gap 及旧依赖失效检查；所有审阅都是明确的测试夹具，不是 exweb 维护者批准。没有执行目标仓库/Maven 或调用真实外部语义模型。

本能力不取代完整 BehaviorSpec、自动冲突发现、正式 US authoring、多用途 ContextPack、费用/模型预算、生成工件/coverage 的原子提交、脚本与 RunPlan、真实受控运行和反馈。[生成契约预检查](./test-design-generation.md) 已通过 application port 消费固定范围并校验候选输出、推导 planned coverage；正式模型调用和持久化生成仍未接入，不能用现有可变 TaskContext 生成链声称闭环完成。
