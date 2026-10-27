# 显式引用候选

更新：2026-10-08。P3 的确定性候选已接入原 AgentGoal 的版本化调查后续；不是完整语义关联、审批或正式画像发布。

## 语义边界

`references` 表示：选定画像中的某份文档，在已归档的显式引用字段里提到了一个 US/REQ ID，该 ID 在同一画像中能唯一定位到一份需求来源投影。

- 同时固定画像 artifact hash、主语/宾语 document revision、双方精确 Evidence 和匹配策略版本。不连接可变工作区或 provider 私有节点。
- `semantic_kind=observed` 仅说明引用文字被观察到；跨源适用性仍待确认，`status=proposed`。不输出 `implements`、`asserts`、业务正确、执行成功或覆盖率。
- 显式字段之外的正文、测试名、同名代码符号不产生关联。大小写规范化沿用现有 US/REQ ID 提取契约；不做模糊匹配、不调用 LLM、不把正文发送到外部模型。
- 缺失目标、重复 ID（包括不同 binding 内的重复）、主语身份不确定、自引用和缺少证据都成为 gap，不任选一个候选。缺失目标表示“此画像中未定位到”，不证明系统没有该需求。
- 只有代码而没有文档时可保存一个零文档、零关系的报告；这不是业务覆盖就绪。来源解析完整性仍应结合逐文件 extraction report 判断。

## 分层与持久化

领域 `reference_links.py` 只负责确定性匹配和边界语义。Application 通过已有画像/文档/证据查询端口读取固定输入，检查原文 token、全候选来源权限和 scope epoch，再调用 repository port。没有 ORM、供应商 API 或网络调用进入领域层。

派生阶段在一次 `verified_read_session` 内复用已核验的不可变画像元数据、成员和归档读取，避免每条引用都重复验证整幅画像；不是跨请求缓存。已有查询端口仍逐次检查实时来源权限，原文仍从归档读取并核验。该只读会话在 repository 写入前关闭，随后重新核验原权限范围，并在提交回调和返回前再次检查。异常退出清除会话，不把部分派生结果持久化；不能用这种复用声明容量或 p95 门禁已经满足。

`0043_reference_links` 增加：

- `image_reference_proposals`：固定输入、方法、内容摘要、操作者、时间及有类型的缺口元数据。
- `image_reference_assertions`：每条候选一个 Nasus UUID；双方 object/document revision、证据 ID、predicate、语义与 proposed 状态独立保存。
- `image_reference_proposal_invocations`：canonical ToolInvocation 与报告的追加式绑定。

全部表禁止 UPDATE/DELETE。项目/报告/画像使用复合 FK；端点 FK 绑定到冻结成员的同一 document revision。证据必须属于对应冻结成员，不能引用后来抽取追加的证据。报告按内容摘要幂等复用；相同输入重复派生不重复生成候选，同一 invocation 不能改绑其他报告。报告、候选、invocation 绑定和只含不透明 ID 的 Outbox 同事务提交。

正文及原文仍在 MinIO；这里不复制文档正文。PG 保存关系元数据和有版本约束的有限 gap JSON。最多处理 1000 份文档、10000 个显式引用，总报告不超过 4 MiB；超限明确失败，不悄悄截断并宣称完整。

## 工具与读取

正式写入口为 `system_image.links.propose_references`，输入 `project_id / image_revision_id`。ToolRuntime 继续执行 RBAC、审计和项目范围检查。该工具只产生静态引用候选，不获得已有结构构建授权中的额外 capability；不能仅凭结构授权把引用任务混入执行。

原 AgentGoal 的新调查策略 v2 可以在结构候选提交及独立调查确认之后，消费已保存的固定文档任务追加本工具。Application port 核对实际调查、原请求/阶段及 canonical invocation，不使用 Planner 生成的任意工具输入作为替代。代码、US、测试来源并存时仍只产生明确编号的文档 references，不推断代码实现、业务正确或覆盖。

提交后 goal 暂停在 `reference_candidate_review`；用户的“查看引用候选”是绑定原 checkpoint 的继续，不是再次确认已完成的 proposal。它完整查询候选与 gap 的所有分页，再进入完成审阅。追加步骤、原 blocked step 消费及 checkpoint 回执由现有 PG CAS 原子保存，所有命令计入原累计工具账本。工作区删除、来源 head 变化或 gateway 重建不替换报告输入，当前 ACL 则每次重新核验。查看不自动执行 `accept/reject/defer`、冻结或发布；超出完整分页预算不能部分查看后称为完整。

原目标续接在提交步骤前实际预检全部区段。每页最多 50 条，超过 64 KiB 时只缩小条数，不裁剪单条或它的证据。页摘要、画像、状态、总数、条数及下一游标必须与原报告一致；单条超限、分页不连续或缩页后超过原 step ceiling 均拒绝推进。预检通过后，全部固定 offset/limit 仍由 canonical 查询重新授权并执行，不复用预检作为访问令牌。这项调整保持旧报告字节、候选状态与公开查询契约不变。

读取入口：

- `query.system_image.references.read`：`project_id / proposal_id`，可选 `section=assertions|gaps`、`offset`、`limit=1..50`。
- `GET /v1/projects/{project_id}/system-image/reference-proposals/{proposal_id}`：同样的分页，响应 `private, no-store`，最大 64 KiB。
- `GET /v1/tool-invocations/{invocation_id}/image-query`：展开查询回执。

Portal 的候选读取同样遵守字节预算：默认请求 20 条，只在 `413 / image_page_too_large` 时逐步缩小完整行数，单条仍超限直接失败。权限、scope、完整性、网络及取消错误不触发缩页重试。响应必须保持固定报告/画像身份、v1 方法、proposed/observed 语义、双方证据、完整计数与连续游标；不接受把引用升级成实现或覆盖的响应。界面按实际返回游标保存上一页栈，不再减固定 20，也不以 offset/20 计算页码。切换区段或翻页清除旧断言表单，等待/失败时不展示旧候选或审阅内容；这只是读取与导航，不产生审阅决定、画像成员或发布。

读取 pin 必须来自已授权报告列表中的明确选择及已核验画像：`proposalDigest / imageArtifactHash` 贯穿候选 API、query key 和审阅组件，审阅历史也必须匹配原报告摘要。缺失／无效 pin 在发送请求前拒绝；返回值即使是格式合法的 SHA-256，只要不等于所选摘要就失败，不接受用返回值重绑画像或报告。更换报告／画像摘要会重建候选视图并清除旧游标和表单；错配、等待或失败隐藏父视图中的旧敏感内容。该协议核验不代替后端每次实时来源授权，也不是审阅、冻结或发布许可。

工具回执只保存报告/画像 ID、摘要、候选 ID 和游标，不包含引用文字、标题或原文。Agent 展开回执和 Planner 观察时重新授权；Planner 默认仍只收到 metadata receipt，不隐式得到完整关联正文。读取、展开及写入前的撤权均会失败，不返回之前的正文。历史报告保留旧端点和旧证据，不连接“最新审批状态”。

## 与后续交付的关系

候选存储不就地修改原 ImageRevision，读取明确返回 `publication=not_in_image_membership`。0044/0045 已接入独立审阅和新候选修订的 assertion/decision membership 冻结，但不自动把本报告准入画像；画像发布仍走独立治理。这些引用记录不能满足 oracle 或覆盖门禁。

后续 `0044` 已补充 [人工 accept/reject/defer 与候选审阅 UI](./reference-review-decisions.md)，决定独立追加，不改写本报告或画像。0046 的[来源 AC/业务规则子对象](./requirement-components.md)、0047/0048 的 [implements/asserts 证据判断与独立审阅](./semantic-link-judgment.md)、0049 的[语义成员冻结](./frozen-review-membership.md)及[跨修订决定适用性](./semantic-decision-applicability.md)均已有独立契约，不复用 references 作为实现或覆盖证明。独立 AC/规则批准和固定测试设计 ContextPack 也已交付；当前完整状态以[实施记录](./implementation-progress.md)为准。

完整脚本 exercises/automated_by、真实运行证据、跨版本重审覆盖、置信度校准、自动增量链及五用途上下文仍需完成。上述已实现与未完成范围都不能被 references 的显式编号匹配替代。

exweb 验证固定到 `fe5827f6b76f77ef34918d8b452ee823142332dc`。测试使用明确标为验证资料的 `exweb-requirements.md` 与 `exweb-test-cases.csv`，只证明 `TC-EXWEB-CHAT` 对 `US-EXWEB-CHAT` 的显式引用；不声称它们是仓库作者的真实需求，或接口满足这些预期。测试不运行 exweb、Maven、hook 或目标依赖。
