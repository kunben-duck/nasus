# Nasus 后端运维与测试基线

## 1. 环境基线

| 环境 | 默认组成 | 目标 |
| --- | --- | --- |
| `local` | `api/orchestrator` `workflow-service` `worker-runtime` `runner` `PostgreSQL` `MinIO` `OpenGrok` | 单开发者联调 |
| `dev` | 本地同构 + 共享索引 | 多人共享开发 |
| `staging` | 完整中心端 + 审计与策略 | 预发布验证 |
| `prod` | 私有化部署 + 隔离执行网络 + 全量监控备份 | 正式运行 |

## 2. 部署与发布

- `local/dev` 默认使用 Docker Compose 或等价方案
- `staging/prod` 推荐使用 k8s 或企业内部等价编排
- 数据库迁移默认采用 `SQLAlchemy 2 + Alembic`
- Agent runtime 默认本地 fallback 仅用于开发和测试；正式环境必须显式启用耐久 workflow 与 graph runtime：
  - `NASUS_AGENT_WORKFLOW_RUNTIME=temporal`
  - `NASUS_AGENT_GRAPH_RUNTIME=langgraph`
  - `NASUS_TEMPORAL_ADDRESS`
  - `NASUS_TEMPORAL_NAMESPACE`
  - `NASUS_TEMPORAL_TASK_QUEUE`
  - `NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW`
  - `NASUS_TEMPORAL_CURRENT_GOAL_QUERY`
  - `NASUS_TEMPORAL_RESUME_SIGNAL`
  - `NASUS_LANGGRAPH_AGENT_LOOP_GRAPH`
- Temporal worker 契约固定为：启动 `NasusAgentGoalWorkflow`，接收 `{conversation_id, proposal, workflow_id}`，暴露 `current_goal` query，接收 `resume_goal` signal，并把 `AgentGoal`、`AgentStep`、`ToolInvocation` 和 `AuditEvent` 写入同一领域存储。
- 当前 `workflow-service` 启动入口：
  - `python -m apps.api.app.agent_goal_workflow_worker`
  - 该 worker 注册 `NasusAgentGoalWorkflow`
  - 注册 activities：`start_agent_goal`、`resume_agent_goal`
  - activity 只调用 `AgentLoopRuntime`，不得调用 `AgentService` 再次启动 workflow，避免递归调度。
- LangGraph worker/节点契约固定为：外层 graph 只承接 `think -> act -> observe -> decide` 路由，所有业务动作仍必须经 `ToolInvocationRuntime`，不允许直接写正式领域对象。
- 发布顺序：
  1. schema / shared contracts
  2. api/orchestrator
  3. workflow-service
  4. worker-runtime
  5. runner
- 长 workflow 相关变更必须保证前后版本兼容
- 事件 schema 演进必须版本化

### 2.1 DB 迁移策略

- 所有结构化 schema 变更都必须提交 Alembic migration，不允许手工改库作为正式流程。
- migration 文件命名应包含：
  - 时间戳
  - 变更摘要
  - 关联模块
- 共享环境默认采用 forward-only 策略：
  - `dev / staging / prod` 不依赖 downgrade 回滚
  - 出现问题时通过新 migration 修正
- breaking schema 变更必须采用 expand-contract：
  1. 先加新列/新表/新索引
  2. 双写或兼容读
  3. 完成数据回填
  4. 再删除旧结构
- Workflow 和事件 schema 的版本兼容性必须先于 DB migration 检查，避免长流程在迁移中断裂。

## 3. 安全与密钥

- 服务间调用必须带服务身份
- Runner 使用短期凭证，不与控制面共享高权限密钥
- 敏感配置统一走密钥管理，不允许写死在代码或镜像里

## 4. 可观测性

### 4.1 统一关联 ID

日志、指标、trace 至少关联：

- `conversation_id`
- `tool_invocation_id`
- `task_id`
- `run_id`
- `approval_id`
- `request_id`

### 4.2 指标基线

- conversation throughput
- tool invocation success rate
- tool waiting_confirmation count
- tool waiting_approval count
- workflow retry count
- worker queue latency
- run success/failure rate
- healing depth exhaustion count
- repeated failure fingerprint count
- pending_merge backlog
- approval lead time

### 4.3 告警基线

- queue backlog 超阈值
- workflow retry 异常增高
- runner failure rate 异常
- healing loop 告警阈值触发
- 审批超时
- 关键服务无心跳

## 5. 备份与恢复

- PostgreSQL 定期备份
- MinIO 开启版本控制
- 关键审计事件与对象存储引用定期一致性校验
- Workflow 状态必须可重入恢复
- 定义最小恢复目标：
  - 关键控制面恢复
  - 执行证据不丢
  - 审批链不断裂

## 6. 测试矩阵

### 6.1 单元测试

- domain model
- policy checks
- gate rules
- tool routing
- worker result parsing

### 6.2 契约测试

- REST schema
- SSE event envelope
- SSE reducer payload compatibility
- ToolInvocation schema
- ExecutionEvidence schema
- conflict payload schema

### 6.3 Workflow 测试

- retry
- timeout
- cancel
- wait for confirmation
- wait for approval
- resume from checkpoint
- graph suspension / temporal resume handoff

### 6.4 集成测试

- conversation -> tool -> task
- tool -> run -> evidence -> failure -> release
- candidate -> approval -> baseline writeback
- baseline fork overlay query + materialized snapshot read

### 6.5 故障注入测试

- worker 崩溃恢复
- runner 超时
- approval 长时间等待
- queue 重投递
- repeated healing failure fingerprint
- unauthorized execution environment access attempt

### 6.6 验收测试

- 用户在主会话发起查询和写动作
- UI 按钮与主会话触发同一动作时产生同类 `ToolInvocation`
- 候选结果冲突进入 `pending_merge`
- 高风险动作进入确认/审批闸口
- 前端可通过 SSE patch/invalidate 正确收敛 `Task -> Run -> MergedResolution` 状态
- 相同失败在超过 `Max Healing Depth` 或命中冷却窗口后自动 fallback-to-human

## 7. CI 准入门槛

- schema / contract 校验必须通过
- workflow 回放测试必须通过
- domain state machine 非法迁移测试必须通过
- 核心集成链路必须通过
- 关键告警和指标埋点必须存在

## 8. 阶段质量门禁

| 阶段 | 必跑内容 | 阻断条件 | 产物 |
| --- | --- | --- | --- |
| PR | typecheck、lint、unit、contract snapshot、Tool Catalog 完整性 | schema 漂移、状态机非法迁移、工具缺 schema | test report、contract diff |
| Integration | FastAPI + PostgreSQL + Alembic、SSE reducer contract、ToolInvocation integration | migration 失败、事件不可合并、幂等失败 | integration report、event trace |
| Staging | Temporal/LangGraph、runner、approval、fault injection、权限负测 | workflow 不可恢复、runner 越权、gate 被绕过 | replay report、audit trace |
| Release | E2E P0 纵切、backup/restore、SLO smoke、security smoke | 无法完成端到端放行、证据丢失、审计链断裂 | release evidence pack |

## 9. P0 自动化验收用例

- 三源缺失时 AgentGoal pause，不能初始化 Official Baseline。
- 三源真实路径齐全时完成 register / ingest / materialize / baseline confirm，并产生完整审计链。
- source 失败时 materialize / baseline 被阻断，修复 source 后恢复同一个 AgentGoal。
- 创建 version、导入 US、生成 TaskContext / QualityProfile；缺失或 stale 时禁止质量生成。
- 生成 scope / scenario / case，CoverageMatrix 闭合到验收标准和系统画像对象。
- 生成 AutomationBlueprint 后 `run.start` 产出 Run 和 append-only Evidence。
- failed Run 生成 FailureReport；重复 fingerprint 或 max healing depth 触发 fallback-to-human。
- `release.advice.get` 聚合 US、资产、Run、Evidence、Approval、pending_merge。
- `approval.request`、`resolution.merge`、`baseline.promote` 必须进入 gate，Agent 不能直接写正式结论。
- SSE 事件序列能被前端 reducer 精确合并；重复、乱序、断线恢复不破坏最终状态。
