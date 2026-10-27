# 同目标的补源计划修订

状态：0086 已实现追加式补源草稿、canonical 确认和历史回读；0087 后续增加[原目标的独立构建阶段](./image-plan-phases.md)。保存草稿本身仍不执行，也不等同于自主构建完成。验收记录见[实施进展](./implementation-progress.md)。

## 适用范围

原构建或调查目标处于 `structural_candidate_review` 或 `build_completion_review` 时，可以为同一目标准备新的 `enrich` 计划。原目标必须属于当前项目及会话，且 `target_refs` 包含根计划。不新建替代目标，不修改已执行步骤、候选画像或旧授权。

用户先采集新增来源，再选择原计划和原暂停目标。修订继承原计划的 objective、purpose 和预算，固定用户明确选定的 source manifest，不在保存时隐式使用最新来源头。purpose 不因新增需求或测试而自动升级。

原计划为[固定目标 v3](./targeted-build-intents.md)时，还继承完整 target 和已解析 publication head，并按新 manifest 扩展 source binding scope。目标变化不能通过保存补源修订悄悄改绑；v1/v2 原摘要与序列化保持不变。

当前允许两种增量：新增已采集 binding，或将原来未采集的 binding 补成 captured。已有 captured 来源必须保留完全相同的修订，不允许替换、移除、重复 binding 或提交未采集占位来源。至少一个 captured 代码来源始终必需。代码刷新/替换、范围或预算扩张不属于这一命令。

## 持久事实

```text
AgentGoal（原 goal，不改步骤和授权）
  -> root InvestigationPlan
  -> BuildPlanRevision #1 -> 新 InvestigationPlan + SourceManifest
  -> BuildPlanRevision #2 -> 新 InvestigationPlan + SourceManifest
```

`image_build_plan_revisions` 保存 revision ID、project/goal/root、from/new plan ID 与 digest、source manifest ID/hash、parent revision ID/hash、连续序号、原 goal checkpoint、canonical invocation ID、创建时间和政策版本。checkpoint 只包含 scope/hash，不另存完整私有 goal DTO。

`execution_authorized=false`、`publication_authorized=false` 是固定契约，不是可编辑开关。新计划本身仍为 `draft/not_granted`；旧 execution authorization 和 work reservation 不复制到新计划。不可变计划可以按 digest 复用，但每次确认有独立修订回执。

迁移 0086 不回填或伪造历史修订。PostgreSQL 拒绝已保存修订的 UPDATE/DELETE；包含记录时 downgrade 明确拒绝。

## 命令与查询

唯一正式写入口是 `system_image.build.plan.revise`，通过 `ToolInvocationRuntime`，风险 medium、独立 `user_confirm`。输入包括：

- `project_id / goal_id / root_plan_id`。
- `from_plan_id / from_plan_digest`。
- `source_manifest_id`。
- `parent_revision_id / parent_revision_hash`；第一条为 null，后续必须等于当前末条。
- `expected_goal`：页面原展示的完整 goal 快照，不在确认时悄悄换成新快照。

准备命令不会写修订；确认后保存草稿。历史来源权限、当前 actor、项目和会话范围都需验证。确认有效期为 15 分钟，必须属于同一个 canonical invocation 和确认账号。

新构建 Goal 的 0092 累计工具账本同时计入这个手动控制命令：等待确认不预留，确认后在 handler 前按原 Goal 上限预留一项，并校验原展示 checkpoint、根计划和当前修订头。同 command 恢复不重复扣减，额度耗尽不写新计划或修订，原目标/候选不改写。实际 dispatch 后修订事务失败仍计入这次工作；工具预算不是模型费用、执行授权，也不是与业务事实的统一交付事务。旧未计量 Goal 不倒推历史。

只读 HTTP 接口使用 `private, no-store`：

- `GET /v1/projects/{project_id}/system-image/build-plans/{root_plan_id}/revision-goals`：最多前 20 个符合条件的目标，当前无分页，不代表项目全部目标。
- `GET /v1/projects/{project_id}/system-image/build-plans/{root_plan_id}/revisions?goal_id=...`：完整、连续、最多 80 条同目标修订。超过上限拒绝新修订，不静默截断或丢弃旧记录。

回读逐条校验链、计划 digest、manifest hash 和基于原计划重新计算的补源提案，同时验证所有历史和新增来源的当前权限。已完成 ToolInvocation 的回读还核对确切 checkpoint、from/source/parent pin 和两个结果引用；错配命令不能借用合法修订回执。

## 原子性与恢复

保存使用项目 mutation lock、原目标行锁和命令行锁。事务内重新比较完整 goal checkpoint、当前末条修订和独立确认，保存新计划、修订、自有 AuditEvent 和 Outbox。最后再次检查来源权限；失败则全部回滚。

同一个 canonical invocation 重试复用原事实。两个独立命令同时提交同一父修订时，最多一个能成功，另一个必须重新读取并由用户确认，不能自动改父节点。原目标预算、步骤、状态或 workflow 已变化时拒绝保存旧快照。

ToolRuntime 完成回执与业务事实不是一个统一事务；若 PG 事实已经提交但回执丢失，恢复可复用原事实。浏览器不自动重发写入，只隐藏旧控件并允许用户显式重新读取。补源修订自身不触发 Provider 索引、外部模型调用、目标仓库运行或原目标恢复。

## 前端边界

Knowledge 的原有计划弹层增加折叠的补源入口，沿用现有 shared token、深浅色和无滚动条滚动布局。选定原目标并完成无缓存权限回读后，用户勾选“仅保存草稿”，先准备命令，再单独确认。

页面通过 system-image 领域命令接口写入，不直接调用平台确认 API。前端拒绝范围错配、断链、重复 revision/plan、无效 hash、序号错误、授权标志变化和超过 80 条的响应。发送固定原快照，不将刷新结果悄悄代替用户展示的数据；读取失败、回执错配或失联都隐藏旧操作，禁止自动写重试。

## 尚未完成

0086 只追加修订事实。后续 0087 在保留旧步骤的前提下，以持久阶段合同分隔固定 plan/source，显式确认后追加原目标的结构阶段，独立重新授权再执行；具体边界见[阶段契约](./image-plan-phases.md)。它仍不提供全计划多能力授权、累计费用账本、所有分支跨计划恢复或完整自动重规划。

不能把新 plan ID 直接写入旧步骤或沿用旧确认。新增文档还需独立的抽取、关联、裁决和上下文流程，保存补源计划并不等于已建立代码—需求—测试关联。完整 P0-P6、Provider 隔离/gold/性能、自动增量更新、真实运行闭环和业务试点范围保持不变。
