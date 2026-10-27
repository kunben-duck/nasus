# 原目标的追加式构建阶段

状态：0087 已接入同目标补源执行与独立授权；专项结果见[实施记录](./implementation-progress.md)。它承接 [0086 补源草稿](./build-plan-revisions.md)，不把本阶段等同完整 P2 或 P0-P6 验收。

## 输入与持久事实

原目标在 `structural_candidate_review` 或 `build_completion_review` 暂停时，用户可以选择最新已确认补源修订，独立确认 `system_image.build.plan.activate_revision`。输入固定 project/goal/root、revision ID/hash、parent phase ID/hash、完整 `expected_goal` 和本阶段预算。第一阶段的 parent 为 null；后续必须承接已激活计划，不能跳过中间补源修订。

```text
原 AgentGoal + 根计划 + 历史步骤/工件/授权
  -> 0086 补源草稿（不执行）
  -> 0087 阶段确认（仍暂停，不授予执行许可）
  -> 显式继续 -> 新计划独立预算确认
  -> 读取新计划 -> 授权结构构建 -> 构建候选 -> 结构审阅
  -> 显式继续 -> 独立证据调查确认 -> 调查修订 -> 完成审阅
```

`agent_image_plan_phases` 是不可 UPDATE/DELETE 的追加式 ledger，保存原目标/root、补源修订、新计划与 manifest 的 ID/hash、目标 baseline/version、父阶段 ID/hash、序号、旧步骤 prefix hash、初始工作合同、原快照 digest、预算和 canonical invocation。

每阶段固定三项 acting work：计划读取、`system_image.build.authorize`、`system_image.build.structure`，各有独立 observe，最后有 decide。阶段 marker 和七个初始步骤原子追加；不得覆盖历史步骤或更改原预算/开始时间/模型用量。当前只支持一次结构构建、零模型调用和零模型费用；它不是多能力共享累计费用账本。

## 权威与调度

仅凭 marker、客户端 target refs 或 LangGraph checkpoint 不能认定阶段有效。Agent compiler 从 application port 核验 PG 完整阶段链、0086 修订链、计划 digest、manifest hash 和当前来源权限；领域策略检查全历史 prefix、工作合同、唯一顺序和当前阶段 head。旧 blocked 审阅步骤保留，但不参与新阶段调度、聊天确认或 Portal 的活动 gate 选择。

初始阶段对照原结构工具的已完成命令和不可变工件 target，不以步骤是否 completed 判断工件：结构审阅时步骤可能仍为 blocked。后续阶段固定父阶段 target；准备阶段后目标 version 改变，也不能在授权时重新指向另一个版本。

迁移将执行授权唯一键从 goal 改为 `(goal_id, plan_id)`。每阶段必须另行确认执行授权，旧授权与 work reservation 不复制。缺少新授权时不能回退到普通结构确认或消耗旧计划额度；新命令仍通过 ToolInvocationRuntime、项目权限、审计和治理。

0092 的原 Goal 累计工具账本也计入手动阶段准备命令，不仅统计新增 acting steps。等待确认不消费；确认后在原 Goal 锁下核验展示 checkpoint、确认账号/时限、根计划、确切修订和阶段 head，再预留一项。它共用原上限，不因新阶段重置；耗尽不 dispatch 激活 handler，原修订和旧步骤保留。同 canonical command 重放不重复计量，实际 handler 失败仍记录一次工作；它不授予执行许可，也不核算原生 Provider 次数或模型费用。

## 原子性与恢复

激活事务使用项目 mutation lock、原 goal 行锁和命令行锁，重验原快照、最新补源修订、父阶段、确认账号/15 分钟时限、原结构 target 和实时来源权限。阶段 ledger、完整追加步骤、active ref、暂停原因、AuditEvent 和 Outbox 在同一 PG 事务提交。并发旧 checkpoint 最多成功一次，不自动换父阶段或原快照。

同 invocation 已提交事实可恢复原回执，不再追加阶段。ToolRuntime 的终态回执和业务事实仍不是统一事务；前端失联隐藏旧控件，不自动重试写入。prepared-phase 继续使用既有原快照消费协议：提交 running 后失联可恢复，但旧快照不能确认之后新出现的预算 gate。

Temporal 仍是生命周期权威，LangGraph 只管理节点游标。阶段专项另行使用真实 Temporal、PG/MinIO 和 LangGraph PG：Worker stop/recreate、阶段消费事务成功后 Activity 故障/重试、重复旧 pin、独立预算确认、完成调查和 Workflow history replay。具体终态与失败历史见实施记录；受控 Worker 替换不冒充 OS SIGKILL、跨主机或所有业务恢复分支验收。

## 只读与界面

`GET /v1/projects/{project_id}/system-image/build-plans/{root_plan_id}/phases?goal_id=...` 返回最多 80 条完整同目标阶段链，响应 `private, no-store`。读取必须验证历史和新来源的当前权限与完整摘要；超界、缺项、断链拒绝，不截断后声称完整。

Knowledge 计划弹层保留三个独立动作：保存补源草稿、准备并确认新阶段、到 Project Overview 显式继续及确认执行预算。准备完成后目标仍暂停；继续不等于预算确认。确认页展示实际结构次数、模型次数、执行时限和费用上限。改变提议时限清除旧勾选，失联或核验失败隐藏旧操作，用户须重新读取。保留现有 AI Studio token、深浅色、16px checkbox 与无滚动条滚动体验。

## 迁移与尚未完成

0087 不回填虚构阶段，不改写旧授权内容。空阶段表且每目标只有一项授权时可以安全回退到旧唯一键；存在阶段或同目标多计划独立授权时 downgrade 拒绝，不能删除新事实以凑旧 schema。

本阶段证明补源后的结构与只读调查可以保留原 goal，但没有自动完成跨源语义关联、规范批准或正式画像发布。全计划多能力授权、累计模型费用、完整 BuildIntent/引导、动态调查/反证、其余 checkpoint 原子化与 Worker 恢复、自动增量、五用途 ContextPack、脚本/RunPlan、真实执行反馈和完整 P0-P6 门禁继续按原方案交付。
