# 正式 AC 与独立需求批准

状态：0050，2026-09-19。推进主方案 P3 的需求批准入口；不等价于完整 BehaviorSpec、画像发布或 P5 ContextPack 验收。

## 所有权与语义

- `system_image` 继续拥有不可变的需求来源投影、来源 AC 子对象及代码/测试关联。导入文档、模型判定或接受关联均不改变 `source_projection_not_approved_specification`。
- `quality_loop` 拥有新的 `AcceptanceRevision`。项目审阅者通过单独确认，把来源 AC 的确切修订及自己独立确认的可观察 oracle 记录为正式需求批准。此批准不是系统自动证明了需求正确，也不是 exweb 作者的授权声明。
- oracle 必须分别包含 `preconditions`、`action`、`observation`、`expected_result`；每项非空且最多 2000 字符。不能用模型置信度、代码行为、已接受关联或测试通过替代 `user_confirmed_requirement`。
- 审阅理由与 oracle 在确认前可编辑；每次修改或重新读取批准状态都会使前端勾选失效。仅 `qa_lead`、`project_admin`、`platform_admin` 可写，普通项目成员可以在来源 ACL 允许时读取。

当前支持从已冻结的 `acceptance_criterion` 来源子对象批准正式 AC。无代码画像、用例、代码节点、普通需求段落、业务规则均不能冒充此来源类型。尚未实现从零编写正式 US/AC、BehaviorSpec 字段级批准或权威来源目录，这些不是由当前导入入口替代的需求。

## 修订与证据

`ac_id` 绑定 `project_id + image_revision_id + object_id`，不绑定动态 source/baseline head。不同画像即使来源文字相同也不会继承批准；后续跨版本适用性治理必须另行显式实现，不能直接改变这一语义。

每次批准、修正批准或撤回均追加 `quality_acceptance_revisions` 记录，固定：

- 画像 ID/hash、来源 binding/revision、来源 AC document revision、父需求修订和精确 evidence IDs。
- 来源完整字段及其定位/内容摘要组成的 `basis_digest`。
- 上一正式修订 ID、递增序列、批准者、ToolInvocation、UTC 记录时间及策略版本。
- 私有对象存储中的完整批准工件引用/hash。PG 元数据和 Outbox 不含原文、oracle 或审阅理由正文。

画像读取服务首先验证完整 manifest/membership；来源文档服务复核父子投影；随后每个 AC 字段必须拥有已冻结的精确证据。证据服务验证归档文件和原文片段的完整 hash，不以只返回的一行替代全片段验证。缺证据、错画像/hash、不同来源、截断字段和归档损坏均失败。

批准工件位于私有 MinIO `quality/acceptance-specifications/<project-hash>/<payload-hash>.json`，最大 48 KiB；来源批准输入最大 24 KiB。不截断批准依据。先写并校验对象，再提交 PG 记录及同事务 Outbox；提交失败不产生正式批准，但可能留下未引用对象，清理仍属于 P6 保留/GC 工作。

数据库禁止 UPDATE/DELETE；同一 AC 的首修订、序列、前驱、invocation 均有唯一约束；复合 FK 绑定项目、冻结成员和确切 document revision。记录时在项目锁下重验 canonical running invocation、用户确认、完整输入一致性及 expected previous revision；并发批准只允许一个成功，另一方必须重新读取。提交前再检查角色/来源 ACL。完整历史链读取时校验序列、前驱与元数据摘要。

同一已确认命令的 Worker 重试可以恢复已提交的修订，覆盖业务事务成功而 ToolInvocation 完成回执丢失的窗口。恢复仍要求当前 reviewer/来源权限和 canonical running input 匹配，再校验原私有工件内的完整 request（含 oracle 和理由）、actor、invocation、来源与历史链；不能只凭 invocation ID 或当前命令表中的输入返回成功。原时间/hash/修订保持不变，不再次写 Outbox；顺序恢复不重新写对象。两个同时开始的同命令尝试在项目锁下收敛为同一结果，竞争失败的预写对象仍受上述 GC 边界约束。后续撤回或修正批准不阻止审计结果回放，但回放不会恢复旧批准的当前效力，`resolve_oracle` 仍拒绝旧修订。

## 命令与查询

- `quality.acceptance_specification.review`：`decision=approve|withdraw`；写入只能经 ToolInvocationRuntime 和显式确认。批准包含独立需求确认和 oracle；撤回要求 oracle/authority_basis 为 null，且当前头确为 approved。用户不能在 input 中伪造 reviewer。
- `query.quality.acceptance_specification`：返回无正文 `acceptance_authority`，包括固定画像、basis digest、查询时 head/status；标记 `query_time_not_live`。Planner 在当前权限下重验来源及固定头后只消费元数据。
- `GET /v1/projects/{project_id}/quality/acceptance-specifications?image_revision_id=...&image_artifact_hash=...&object_id=...`：批准面板的完整授权读模型，返回来源、查询时当前批准工件及审阅权限。
- `GET /v1/projects/{project_id}/quality/acceptance-specifications/{revision_id}`：固定历史工件，`historical_not_live=true`，可沿 previous_revision_id 审计；不把旧 approved 记录当作当前授权。

GET 均 `private, no-store`，每次读取仍检查当前项目/全部画像输入来源 ACL。前端对画像、对象、document/source revision、binding、evidence、basis 和批准头做一致性检查，任何错误隐藏此前的画像敏感内容。生产路由在 Knowledge 的冻结 AC 证据详情提供独立“需求批准状态”面板，沿用现有主题和滚动容器。

## 下游准入

应用端口 `resolve_oracle(project_id, image_revision_id, object_id, revision_id, artifact_hash)` 不接受自由文字或可变 head：重验完整来源和批准工件，并确认所选修订仍是当前 approved 头。撤回或新修订使旧修订不能再用于新消费，历史 GET 仍保持原内容。

该返回值是读取时核验，不是可永久复用的授权票据。后续 ContextPack/生成/运行提交需要在其事务边界重新检查权威修订和 ACL，并记录派生依赖；本轮没有把旧兼容生成链伪装成已完成此迁移。

现有 `implements/asserts` 指向来源 AC 而非新正式 AC revision。批准不会自动把这些关联转成已批准 oracle 的覆盖：后续编译器需验证正式预期与关联证据的匹配，不能因为 source object 相同就忽略人工填写的新预期。计划覆盖与真实运行验证覆盖仍严格分离。

## 验证边界

API/PG 测试覆盖独立确认、错误类型/角色/证据、并发 CAS、幂等 ToolInvocation、来源更新不继承、撤回阻断新消费、历史不改写、canonical 输入篡改、Outbox/提交权限回滚、归档篡改及读取期间 ACL 撤回。新增业务提交后回执丢失、同命令并发重试、原命令 oracle/理由被篡改和撤回后恢复不重新激活的测试。浏览器使用真实 canonical 写链和 PG 验证批准/撤回、修改后重新勾选、深浅色移动端与非法响应隐藏，并检查新增面板不产生重复 React key 或页面异常。

exweb 仍固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`；真实 PG/MinIO 验证使用明确标识的伴随文档和测试夹具。测试内的人工身份适配器仅验证批准工件协议，不声称获得 exweb 作者批准、运行过该项目或完成独立业务 gold 验收。
