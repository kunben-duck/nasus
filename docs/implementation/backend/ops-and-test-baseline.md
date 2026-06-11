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
