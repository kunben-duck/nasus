# 业务规则独立批准

状态：0052，2026-09-19。补齐 P3 中显式来源业务规则的批准入口，供 P5 固定上下文消费；不代替完整 BehaviorSpec、风险/权限矩阵、正式画像发布或质量生成链。

## 边界与语义

- system_image 拥有来源 `business_rule` 投影、父需求版本和证据。来源文字、接受的关联及代码推断均不自动成为正式规则。
- quality_loop 拥有独立 `BusinessRuleRevision`，标识为 `rule_id`，存入 `quality_business_rule_revisions`。不会把规则伪装成 AC，旧 AC 表、命令、工件和 hash 不变。
- 来源必须是冻结画像里的显式业务规则子对象，全部字段有确切原文证据。AC、测试、普通需求段落、未冻结对象不能替代规则来源。
- 批准者必须是当前项目 `qa_lead / project_admin / platform_admin`，明确确认 `user_confirmed_business_rule` 及完整 `preconditions / action / observation / expected_result`。该动作是用户的独立规范确认，不是平台证明规则正确或目标代码已经满足规则。
- 批准只适用于确切 image/source/document 修订。修订、撤回均追加历史，不能跨画像继承。当前尚无批准的局部适用范围，因此上下文保守继承全部规则，不基于候选排名删减。

## 写入与读取

命令 `quality.business_rule.review` 必须经过 ToolInvocationRuntime 与独立确认。参数与 AC 批准的固定依据/CAS 形式一致，但策略为 `nasus.business-rule-authority.v1`，批准依据为 `user_confirmed_business_rule`。撤回只允许当前 approved 头，oracle 和 authority_basis 必须为 null。

查询 `query.quality.business_rule` 只返回 `business_rule_authority` 元数据；Agent 使用前重新检查作用域和工件，不将该查询时观察作为永久授权票据。

HTTP 只读入口：

- `GET /v1/projects/{project_id}/quality/business-rules?image_revision_id=...&image_artifact_hash=...&object_id=...`
- `GET /v1/projects/{project_id}/quality/business-rules/{revision_id}`

两者均重新检查当前来源权限，返回 `private, no-store`。Portal 在冻结业务规则的原文面板展示独立批准表单；输入修改、重读与重试后必须重新勾选确认。审批与撤回使用同一 canonical 命令链，无 HTTP 写旁路。

## 一致性

AC 与规则共用固定来源批准协议的实现，不共用身份、策略或业务事实。可观察 oracle 的字段校验复用领域值对象。数据库依然仅使用 PostgreSQL；领域层不依赖 ORM。

业务规则批准正文存于私有 MinIO `quality/business-rule-specifications/<project-hash>/<payload-hash>.json`，最大 48 KiB。源依据不超过 24 KiB，超限拒绝而非截断。PG 只存无正文的固定修订摘要、对象引用和摘要 hash。

项目锁下重新检查 running canonical invocation、完整 confirmed payload、项目/会话/goal 绑定、确切冻结成员和 document kind、expected previous revision、当前来源权限；修订记录与 Outbox 同事务。唯一约束和不可变触发器禁止改写历史。同命令恢复校验原工件完整请求，复用原时间/hash，不重复事件，也不重新激活后来撤回的规则。

MinIO 与 PG 不是分布式事务，失败预写可能留下孤立对象；GC/保留/恢复门禁仍属于 P6，不能以成功写入伪称 exactly-once。

## ContextPack v3

Portal 新请求显式使用 `nasus.test-design-context.v3`：每条 AC 和每条规则均固定独立 authority pin 与可观察 oracle，所有规则完整继承到每个子包。未批准/撤回规则仍保留为 mandatory gap。提交前重验批准及 ACL，撤回或修正规则导致原包的当前使用状态 stale，但历史正文保持不变。

v1/v2 的 replay 不升级：它们原本把来源规则视为未批准，仍保持原来的内容及派生 hash，新增规则批准不改变这些策略的历史结果。API 未指定 policy 仍默认 v1。读取端同时验证 v1/v2/v3。

即使全部 AC/规则获批，当前上下文最多 `partial`，仍明确 `generation_authorized=false`；正式风险/冲突、模型预算、发布 head 与生成 UoW 不能由这个批准动作代替。

## 验证

专项覆盖真实 PG 的独立确认、类型/角色/伪造输入拒绝、追加式历史、并发 CAS、Worker 恢复、Outbox 回滚、来源撤权、跨画像不继承、v3 提交期间规则撤回、历史固定回放及 v2 兼容。浏览器沿用 light/dark、移动端检查，并通过真实确认接口进行批准/撤回。

exweb 固定 `fe5827f6b76f77ef34918d8b452ee823142332dc`，只静态读取。需求/规则/测试文档为明确标识的配套验证夹具，测试审阅者不是 exweb 维护者；MinIO 回放、规则批准成功不代表真实业务验收、目标执行或独立 gold 已完成。实际测试结果记录在 implementation-progress，不将未完成的测试写成通过。
