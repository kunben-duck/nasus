# 引用关联审阅

状态：2026-09-17，推进 P3。实现显式引用候选的人工决定，不等同于完整语义关联、正式画像成员或发布。

## 审阅契约

`system_image.links.review` 通过 canonical ToolInvocation 执行，要求项目有效角色为 `qa_lead / project_admin / platform_admin`，并经过 `user_confirm`。客户端不能通过传入确认标志绕过 Runtime。审阅人来自当前认证及项目作用域，不接受客户端 reviewer 字段。

输入固定 `project_id / proposal_id / assertion_id / proposal_digest / evidence_digest / policy_revision`，另带 `decision=accept|reject|defer`、非空理由（最多 2000 字符）和必填的 `expected_previous_decision_id`。首次决定显式传 null；后续决定必须携带当前 head。策略为 `nasus.explicit-reference-review.v1`。

- 接受仅表示认可这两个固定文档修订之间的 `references`，不表示 implements/asserts、测试覆盖、批准业务预期或画像发布。
- 决定记录包含原画像、候选与断言摘要、双方修订/证据摘要、reviewer、理由、时间、策略和 invocation。断言本身仍为不可变 proposed，不就地改写。
- 拒绝和暂缓也是持久事实。相同输入自动重建仍复用原候选/断言，不删除或覆盖决定。修订变化产生新候选，不继承旧批准；跨修订沿用/失效分析留给后续 lineage 和 overlay。
- 全画像来源 ACL 和当前项目角色在读取、提交及事务提交前重新检查。曾经能审阅不意味着撤权后仍能读取历史理由或原文。

## PostgreSQL 事务

迁移 `0044_link_decisions` 增加 `image_link_decisions`。记录与前置决定采用同项目/同断言复合 FK，每个 invocation 最多一个决定，每个断言只有一个首决定，每个前置决定只有一个后继，序号唯一。数据库禁止 UPDATE/DELETE；降级迁移遇到已有决定拒绝丢弃。

Repository 在项目事务锁内检查 running canonical invocation、确认状态、请求精确一致、conversation/goal 范围、冻结候选及证据，随后 CAS head。并发提交只能有一个成功；另一个返回 failed ToolInvocation，`followup_reason=stale_link_decision`，要求重新加载，不能无条件覆盖。决定和只含不透明 ID 的 Outbox 同事务提交。理由不进入该 Outbox 或结果回执。

理由是 reviewer 输入的有界文本，不复制代码/需求正文。原文仍由 MinIO 归档读取。最多 1000 次决定/断言，超限失败，不丢弃历史。

## 查询与界面

- `GET /v1/projects/{project_id}/system-image/revisions/{image_revision_id}/reference-proposals`：授权后的候选列表，keyset 分页。
- `GET /v1/projects/{project_id}/system-image/reference-proposals/{proposal_id}/assertions/{assertion_id}/decisions`：按序分页，`through_decision_id` 可固定历史 head，空字符串代表空历史，省略表示查询当前 head。每页最多 50 条，在 64 KiB 预算内自动缩小完整条目数并返回实际游标，不截断理由；单条超限明确失败。
- `query.system_image.links.decisions`：生成不含理由或源码的 `image_query` 回执，固定查询时 head，包括空历史。后续决定不改写旧回执；展开和 Planner 观察重新授权，Planner 默认只获得 metadata。
- Knowledge → Image revisions 内可以派生/选择引用候选、查看缺口、读取双方归档证据、分页审阅历史并填写决定。表单要求非空理由和明确勾选确认，随后调用统一 ToolRuntime 创建并确认。保存后重新读取决定；网络/权限/CAS 失败要求重新加载，不自动重试写入。保留既有 light/dark、移动端和无可见滚动条样式。

已有冻结画像、候选报告和历史 query receipt 的摘要保持不变。独立审阅响应继续声明 `not_in_image_membership`；0045 的单独 [冻结命令](./frozen-review-membership.md) 可在新的子候选 pin assertion/decision ID，不就地改写原画像。禁止用查询时 latest review 代替 frozen membership；正式发布治理仍未完成。

## 验证范围

自动测试覆盖确认、RBAC、幂等、并发 CAS、负向历史、Outbox 回滚、追加式约束、源/角色撤销、历史回执、空历史回执、修订变化不继承以及 Agent 不隐式发送正文。浏览器用固定 exweb 与显式验证资料检查审阅、刷新恢复和深浅色/移动端。

真实 exweb PG/MinIO 适配器测试使用显式 actor/confirmed invocation double；真实确认与 RBAC 由 HTTP 和浏览器另行验证。验证资料不是仓库作者的批准需求，不执行目标代码。具体批次、失败与复验结果见 [实施记录](./implementation-progress.md)。

完整 P0-P6 继续保留：一等 AC/BehaviorSpec、implements/asserts/exercises、语义反证与校准、其他断言类型准入、发布治理、增量演进和五类 ContextPack 均未由本功能替代。
