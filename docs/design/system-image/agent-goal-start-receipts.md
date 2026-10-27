# Agent 构建目标的持久启动回执

更新：2026-10-08。0088 将 Temporal 工作流、原始构建请求和创建的 AgentGoal 固定到一条不可变回执，防止创建竞争与 Activity 重试覆盖 controller 或释放独立确认。它是[自主系统画像](./autonomous-system-image-design.md)的恢复基础，不替代完整 P0-P6 验收。验证终态见[实施记录](./implementation-progress.md)。

## 启动身份与事务

Temporal Activity wrapper 使用实际 `activity.info().workflow_id` 校验载荷，不能仅信任请求中声称的工作流 ID。应用层重新读取会话、来源与原保存计划，编译工具步骤，再对 bound proposal、完整初始创建 DTO 和 graph kind 计算规范 SHA-256。摘要包含目标、预算与编译输出，JSON 字段排序不影响摘要。

`AgentGoalStartIdentity` 是纯领域值对象，不依赖 Temporal、ORM 或供应商。公开 `AgentGoalCreateRequest` 没有增加可由用户覆盖 controller 的字段；启动身份只通过内部 application port 传递。

`agent_goal_start_receipts` 保存 workflow ID、goal ID、conversation/project、request digest、schema 与 receipt hash，不保存原文、私有工具正文、模型密钥或确认凭证。workflow ID 为主键，goal ID 唯一。复合外键固定原目标、会话与 controller，后续投影不能改绑工作流。UPDATE/DELETE 由 PG trigger 拒绝；有数据时禁止破坏性降级。旧目标不补造回执。

创建事务锁定已有 Conversation 行，验证项目与活跃 controller，然后提交完整 Goal 和回执。回执失败时完整 Goal 同样回滚；无目标的空会话也受锁保护。另一个 workflow 的创建竞争返回原目标 ID，不保存失败者回执、不启动第二个图。生命周期重新授权原保存意图，不能把竞争者的另一计划复用到原目标。

## 重试语义

| 原始事实 | 同一工作流和请求的重放 | 不允许的副作用 |
| --- | --- | --- |
| 没有回执和目标 | 正式创建并启动图 | 不得绕过来源、目标或预算检查 |
| 已有 paused/blocked 目标 | 回读原状态 | 不再次创建、发布 proposed、调用图或确认 gate |
| 已有 completed/failed/cancelled 目标 | 回读原终态 | 不另建新目标或重开终态 |
| 已有 draft/pending/running 目标 | `agent_start_recovery_required` | 不凭启动回执重新执行可能已发生的工具 |
| 同 workflow、不同请求摘要或 scope | `agent_start_scope_changed` | 不换预算、来源、计划或 controller |
| 另一 workflow 创建同一活跃会话 | `active_agent_goal_exists` | 不将原目标 workflow ID 改为失败者 |

重放先重新编译、授权原输入，历史回执不绕过当前 ACL 或目标漂移检查。启动恢复与五字段 resume checkpoint 是不同契约：前者只证明原创建身份，后者才能消费已展示的特定确认。重放原 start 不能替代新构建阶段、调查或发布的确认。

Worker 将已知创建冲突与恢复需求返回成 `_start_error` 元数据，而不是无限重试该 Activity。失败者 Workflow 不进入 resume 等待；Gateway 立即还原类型化冲突，由 application 验证原目标，不把错误 cursor 当 Goal 投影写回 PG。未知基础设施故障继续使用 Temporal 重试策略。

## 当前边界

Goal 与回执同事务；创建后的审计、消息和 Outbox 还没有全部合并到同一事务。本回执不是公开 HTTP 请求的持久 Idempotency-Key，也不是 dispatch outbox 或执行 owner lease。同一 Temporal workflow 的已落定状态重试已有只读恢复；API 在首次 workflow 启动后失联、不同请求重放、pending/running 图内崩溃、超时旧 Activity 的 fencing、显式接管与完整自动 reconciliation 仍需独立交付。

Legacy 内存适配器只提供单进程规则，不声明持久化或跨进程保证。数据库验证只迁移隔离 PostgreSQL，不修改开发业务库。

固定 exweb 验证继续使用批准的干净代码快照及明确标记的需求/测试伴随资料。原生代码索引、三源结构成员、持久化启动重放和新阶段独立授权是不同断言；这些资料不是维护者业务规范，也不证明语义准确率、已执行覆盖或目标程序通过。完整 Provider 对照/gold、动态调查、多能力预算、增量演进、五用途 ContextPack、旧链切换和真实运行反馈继续保留。
