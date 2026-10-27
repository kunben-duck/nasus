# 来源变更后的上下文失效

更新：2026-10-07。0067 为固定来源变更增加独立确认的持久失效事实和下游当前使用门禁。它消费[变更影响预览](./context-change-impact.md)，不改写历史上下文、来源批准或计划覆盖；不是完整项目增量重建。完整目标仍按[交付方案](./delivery-and-evaluation.md)验收，实测范围见[实施记录](./implementation-progress.md)。

## 失效范围

`invalidation_scope=image_current_use` 固定到原 ContextPack 所属的精确画像修订。该画像下的新旧 Context ID 都不能继续作为当前测试设计依据，包括用新预算重新归档的包；新 ID 不使旧来源重新有效。另一画像修订不继承此失效事实。更新来源、构建和发布新画像仍需各自的权限、证据和批准。

影响预览固定一个上下文根下已经存在的完整有界 context/scope/generation/case/coverage/mapping DAG；持久化这些节点和全部依赖边。它不是全项目的反向派生索引，不声称列出了该画像下所有其他上下文的工件。其他同画像上下文通过共享 ContextPack 当前使用端口受到阻断，而不是伪造它们已被逐项展开。

新增、修改、删除、未确认采集范围都可使查询范围需要重新调查。空查询和 top-k 也依赖原完整来源集合，不能因变更文件没有出现在旧 evidence 中忽略它。完整无变化来源不能创建失效事实；闭包超过 128 个节点或 64 KiB 时整体拒绝，不截取部分图。

## 确认和提交

1. 调用 canonical `query.system_image.context.change_impact`，固定 project/context/artifact、before/after 来源修订，并取得回执 `result_hash`。
2. 使用同一组 pins、`expected_impact_hash=result_hash`、非空 `reason`、`policy_revision=nasus.context-invalidation.v1` 和 `invalidation_scope=image_current_use` 调用 `system_image.context.invalidate`。
3. 原 ToolInvocationRuntime 要求独立 `user_confirm`。只有当前 qa_lead/project_admin/platform_admin 可提交，调用者输入的 confirmed 字段不授予许可。
4. 提交在项目来源和 ACL 锁内重验当前账号、角色、canonical running 命令、认证确认者、精确参数、15 分钟且非未来的确认，以及完整最新依赖 inventory。预览后新增 scope/生成/映射改变 digest，必须重新调查并明确确认。
5. 失效主记录、类型化节点、依赖边、审计和 metadata-only Outbox 在同一 PostgreSQL 事务提交。故障全部回滚。同一 invocation 只能恢复原提交，不修改旧记录或重新发模型请求。

0067 新增 `system_image_context_invalidations`、`system_image_context_invalidation_nodes` 和 `system_image_context_invalidation_edges`；复合 FK 固定项目、上下文及同 binding 双来源，节点/边完整性另由领域 DAG 校验。三表追加式，有记录时拒绝破坏性降级。事件和 ToolResult 只包含 ID/hash/计数与状态，不复制源码、oracle、私有存储地址或审阅理由。

## 历史和当前使用

`GET /v1/projects/{project_id}/system-image/context-invalidations/{invalidation_id}` 返回固定历史和完整有界依赖，`private, no-store`。回读重新核验原上下文、来源和质量工件，固定当时 scope/generation/mapping IDs，不纳入后来工件。当前 ACL 撤销或工件损坏仍拒绝读取；历史不是永久访问令牌。

ContextPack 的 `metadata/context/derivation` 不变。其独立 `current_use` 返回 `stale=true`、`reason=source_change_invalidated`、`invalidation_id` 和 `generation_authorized=false`。范围、生成、映射和分片暂存通过 application port 复用当前使用门禁，画像域不直接修改质量域 repository。旧草稿及 accepted 映射仍可按历史查看，但不能成为当前生成或新审阅的依据。

Portal 严格接受该失效状态，仍展示归档内容与不可用于当前生成的提示；缺失/非法失效 ID、失效原因与 stale 不一致、其他原因夹带失效 ID 均隐藏受保护内容。沿用原深浅色、移动和无可见滚动条样式，没有新增独立失效编辑面板。Agent 能发现只读预览和需确认的失效命令，仍受原 12 项详细工具预算约束。

失效 Outbox 绑定发起命令的 conversation/goal，供原会话 SSE 持久回放；`snapshot_hint` 和 project-scoped query keys 刷新上下文、范围、生成、映射及分片审阅缓存。canonical 完成事件携带相同刷新键，失败事件不声称提交成功。前端保留缓存中的账号/会话隔离项，将项目放在可匹配的前缀，不刷新其他项目。已打开面板可在收到事件后重新授权读取失效状态，不必手动刷新页面。该通知不是项目广播订阅，其他会话仍须在后续读取/窗口聚焦时重新验证；服务端当前使用门禁不依赖通知是否收到。

## 保留的完整目标

`invalidation_applied=true` 只证明这一独立失效事实已提交；`impact_complete=false`、`generation_authorized=false`、`execution_authorized=false` 保持。这里不撤回业务批准、不把 planned coverage 变成已执行覆盖、不自动重建或发布、不调用外部模型、不运行目标仓库。

全项目 Derivation/query-scope 索引、实体和断言 lineage、来源刷新/webhook/reconciliation、增量调查、投影更新、overlay/tombstone、分支三方合并/CAS/回滚、自动恢复及容量/性能仍须交付。五种用途、旧生成链切换、脚本/RunPlan/真实执行反馈、Provider 对照/gold/隔离和最终 V1 不因本阶段失效门禁而缩减。
