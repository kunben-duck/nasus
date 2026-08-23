# Nasus 后端运维与测试基线

## 1. 环境基线

| 环境 | 默认组成 | 目标 |
| --- | --- | --- |
| `local` | 宿主机直启 `api/orchestrator` `portal` `workflow-service` `runner`；Docker/托管服务提供 `PostgreSQL` `MinIO` `OpenGrok` | 单开发者调试与联调 |
| `dev` | 应用进程直启或同构部署 + 容器化外部组件 + 共享索引 | 多人共享开发 |
| `staging` | 完整中心端 + 审计与策略 | 预发布验证 |
| `prod` | 私有化部署 + 隔离执行网络 + 全量监控备份 | 正式运行 |

## 2. 部署与发布

- `local/dev` 开发调试默认直接启动 API、Portal、workflow worker 和 runner；Docker Compose 只负责 PostgreSQL、MinIO、Temporal、索引等外部组件。候选发布和生产拓扑验证仍必须使用容器镜像。
- `local/dev/staging/prod` 的外部组件必须容器化或由等价托管服务提供，不允许把数据库、对象存储、索引服务作为宿主机裸进程写入正式部署说明。
- V1 本地基础设施以仓库根目录 `docker-compose.yml` 为准，至少包含：
  - `postgres`：PostgreSQL 16 + pgvector，作为正式事实源、FTS 与 V1 向量检索投影。
  - `minio`：S3 兼容对象存储，保存 raw assets、执行证据、trace、截图和报告。
  - `minio-init`：初始化默认 bucket 并开启版本控制。
  - `runner`：独立 Node.js + Playwright 执行服务；只在 `app` profile 或等价生产部署中启动，不与 API 进程共址。
- API 必须通过 `ObjectStorage` adapter 访问对象存储；本地测试允许 `local-object://` fallback，Docker/staging/prod 必须使用 `NASUS_S3_ENDPOINT / NASUS_S3_BUCKET / NASUS_S3_ACCESS_KEY / NASUS_S3_SECRET_KEY` 写入 MinIO/S3。
- API 探针必须区分存活和就绪：`GET /healthz` 只表示进程存活；`GET /readyz` 必须真实执行 PostgreSQL `SELECT 1`、MinIO/S3 bucket 检查、Git executable/托管 cache 可写检查和 Runner `/readyz` 检查，任一生产强依赖不可用时返回 `503`。容器编排和流量入口只能使用 `/readyz` 判定是否接收业务流量。
- `/readyz` 的 `code_intelligence` 检查必须执行一次真实 Tree-sitter smoke parse，并返回 provider、版本、原生语言范围和 fallback policy；仅能 import 包但无法解析 grammar 时视为 unavailable。
- 正式环境的系统画像 embedding 与 rerank 必须 fail-closed。即使启动时
  `/readyz` 为 `ready`，单次 Provider 超时、5xx、无效响应或运行期降级也必须
  终止本次画像物化；禁止持久化 `mock-hash-embedding`、`rule-based-fusion`
  或 `mode=fallback` 结果。失败后保留已索引的 RawAsset，但画像对象、关系、
  指标、US、向量索引、TaskContext 和 QualityProfile 必须原子恢复。
- Compose service 禁止声明全局固定 `container_name`。开发栈、CI 栈和发布验收栈必须依赖 Compose project name 隔离，允许在同一宿主机并行运行。
- `staging/prod` 推荐使用 k8s 或企业内部等价编排
- 数据库迁移默认采用 `SQLAlchemy 2 + Alembic`
- Agent runtime 默认本地 fallback 仅用于开发和测试；正式环境必须显式启用耐久 workflow 与 graph runtime：
  - `NASUS_ENV=staging|production`
  - `NASUS_SEED_DEMO_DATA=false`
  - `NASUS_AGENT_WORKFLOW_RUNTIME=temporal`
  - `NASUS_AGENT_GRAPH_RUNTIME=langgraph`
  - `NASUS_TEMPORAL_ADDRESS`
  - `NASUS_TEMPORAL_NAMESPACE`
  - `NASUS_TEMPORAL_TASK_QUEUE`
  - `NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW`
  - `NASUS_TEMPORAL_CURRENT_GOAL_QUERY`
  - `NASUS_TEMPORAL_RESUME_SIGNAL`
  - `NASUS_LANGGRAPH_AGENT_LOOP_GRAPH`
  - `NASUS_LANGGRAPH_CHECKPOINT_BACKEND=postgres`
- Temporal worker 契约固定为：启动 `NasusAgentGoalWorkflow`，接收 `{conversation_id, proposal, workflow_id}`，暴露 `current_goal` query，接收 `resume_goal` signal，并把 `AgentGoal`、`AgentStep`、`ToolInvocation` 和 `AuditEvent` 写入同一领域存储。
- 当前 `workflow-service` 启动入口：
  - `python -m apps.api.app.infrastructure.workflow.agent_goal_workflow_worker`
  - 该 worker 注册 `NasusAgentGoalWorkflow`
  - 注册 activities：`start_agent_goal`、`resume_agent_goal`
  - activity 只调用 `AgentLoopRuntime`，不得调用 `AgentService` 再次启动 workflow，避免递归调度。
- LangGraph worker/节点契约固定为：外层 graph 承接 `prepare -> think -> act -> observe -> decide` 路由，所有业务动作仍必须经 `ToolInvocationRuntime`，不允许直接写正式领域对象。
- `AgentGoal`、`AgentStep`、`ToolInvocation` 是 PostgreSQL 中的业务事实；LangGraph checkpoint 只保存图游标和恢复状态，不能成为领域事实源。
- 正式环境的 LangGraph `thread_id` 固定为 `{graph_name}:{goal_id}`，checkpoint backend 必须是 PostgreSQL；内存 checkpointer 仅允许 local/test。
- API 与 `workflow-service` 必须共享同一个
  `NASUS_SETTINGS_ENCRYPTION_SECRET`。该密钥至少 32 个非占位字符，
  不得写入数据库或镜像；缺失时 staging/production 必须启动失败，
  否则 Worker 无法解密设置页保存的模型 API Key。
- Runner 契约固定为：
  - API 只通过内部 HTTP adapter 提交结构化 Playwright steps，不允许提交或执行任意 JavaScript。
  - `NASUS_RUNNER_SERVICE_TOKEN` 用于服务身份验证；`NASUS_RUNNER_ALLOWED_HOSTS` 是网络访问白名单，目标不在白名单时必须在启动浏览器前拒绝。
  - Runner 返回统一 result envelope；截图、trace 和日志由 API 通过 `ObjectStorage` adapter 持久化到 MinIO/S3，再形成 append-only `ExecutionEvidence`。
  - 容器必须使用只读根文件系统、临时 `/tmp`、丢弃 Linux capabilities、`no-new-privileges`、进程数和并发上限。
- API 启动必须在导入单例 store 前执行 runtime 配置校验；`staging/production` 下发现 SQLite、`NASUS_AUTO_CREATE_TABLES=true`、dev auth、通配或缺失的 CORS trusted origins、缺失 S3、mock 模型、local workflow/graph、demo seed、非 HTTP Runner、缺失 Runner service token 或空目标白名单时必须 fail-fast。
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
- 正式运行必须设置 `NASUS_DATABASE_URL=postgresql+psycopg://...` 并执行 Alembic migration；SQLite `create_all` 仅允许测试和一次性本地调试 fallback。
- 本地启动顺序固定为：
  1. `docker compose --profile app --profile temporal up -d postgres minio minio-init temporal temporal-ui`
  2. `cp .env.example .env` 并填入真实模型密钥
  3. 执行 `npm run dev:up`
  4. `dev:up` 必须让 API、workflow worker 和 runner 读取同一份
     `scripts/dev-runtime-env.sh`，执行 Alembic migration，并启用
     `temporal + langgraph + postgres checkpoint + http runner`
  5. 使用 `npm run dev:status` 检查运行时，使用 `npm run dev:down`
     只关闭宿主机应用进程；只有显式执行
     `npm run dev:down -- --infra` 才停止 Docker 外部组件
  6. Codex、CI 或调试器等会清理后台后代进程的环境使用
     `npm run dev:foreground`，由单一前台监督进程维护 runner、workflow
     worker、API 和 Portal；任一进程退出时必须输出日志并统一回收
- Docker 外部组件验收命令固定为：
  - `npm run verify:docker-stack`
  - 该命令必须验证 PostgreSQL/pgvector、Alembic migration、MinIO
    bucket/versioning、对象写读，以及暂停中的 AgentGoal 在 Temporal Worker
    重启后仍以同一 workflow、checkpoint 和 ToolInvocation 恢复完成。
- 生产化 Compose 拓扑验收命令固定为：
  - `npm run verify:production-compose`
  - 该命令必须验证 `postgres`、`minio`、`minio-init`、`api-migrate`、`api`、`portal`、`runner`、`temporal`、`workflow-service`、`temporal-ui` 服务声明和 profile 拓扑。
  - 校验必须读取 Compose 展开后的 JSON，确认 `workflow-service` 继承 API 的 PostgreSQL、MinIO、模型、Runner 和 Temporal 环境，并覆盖为 `temporal + langgraph + postgres checkpoint`；只检查服务名不构成有效门禁。
  - 如需验证镜像可构建性，必须执行 `NASUS_VERIFY_PRODUCTION_COMPOSE_BUILD=true npm run verify:production-compose`。
  - 该命令只证明生产化部署拓扑和镜像构建契约有效，不替代真实 runtime、备份恢复、权限和故障注入验证。
- V1 候选发布门禁命令固定为：
  - `npm run verify:v1-release`
  - 该命令必须串联仓库发布卫生、`lint:portal`、`build:portal`、隔离 Runner 的真实 Playwright/HTTP 鉴权测试、后端单元/契约测试、浏览器 E2E、Web/API smoke journey、Docker PostgreSQL/MinIO 持久化验证。
  - `verify:release-hygiene` 必须拒绝被 Git 跟踪的运行日志、浏览器快照、私有 `.env`、私钥材料以及 `.env.example` 中的重复变量；示例配置的后定义覆盖不能作为有效配置机制。
  - `verify:v1-release` 是第一个正式版本的候选准入线；它通过只能证明 Web-first 主纵切、工具调用链、Runner 执行契约和 Docker 外部组件基础可用，不能替代 staging/prod 的 Temporal/LangGraph 恢复、Runner 容器联调、备份恢复、安全扫描和故障注入门禁。
- 后端质量闭环测试必须断言 `ExecutionEvidence.storage_ref` 指向 `s3://` 或本地 fallback 的 `local-object://`，禁止只保存 `trace://`、`log://` 等 runner 内部逻辑 URI 作为正式证据地址。
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
- Runner 使用独立服务身份和短期任务凭证，不与控制面共享高权限密钥；服务 token 必须由 secrets manager 注入并支持轮换。
- 敏感配置统一走密钥管理，不允许写死在代码或镜像里
- production/staging 必须设置 `NASUS_RATE_LIMIT_ENABLED=true` 与
  `NASUS_RATE_LIMIT_BACKEND=postgres`。登录/注册、Agent 写请求和普通 API
  使用独立预算；共享计数表保证多 API 副本执行同一限制。
- 限流存储不可用时返回 `503 rate_limiter_unavailable`，超过预算时返回
  `429 rate_limit_exceeded`、`Retry-After` 和 `X-RateLimit-*`，不得静默放行。

## 4. 可观测性

### 4.1 统一关联 ID

日志、指标、trace 至少关联：

- `conversation_id`
- `tool_invocation_id`
- `task_id`
- `run_id`
- `approval_id`
- `request_id`

所有 HTTP 响应必须包含 `X-Request-ID`。合法的客户端关联 ID 可透传，非法或
超长值必须替换为服务端生成的 ID。错误响应、ActorContext、结构化日志和
Temporal 启动/恢复输入必须使用同一个 ID。

### 4.2 指标基线

V1 API 通过受认证的 `GET /metrics` 暴露以下 Prometheus 指标：

- `nasus_http_requests_total{method,route,status}`
- `nasus_http_request_duration_seconds{method,route}`
- `nasus_http_requests_in_progress`
- `nasus_rate_limit_rejections_total{scope}`
- `nasus_operational_snapshot_up`
- `nasus_operational_snapshot_duration_seconds`
- `nasus_conversations{status}`
- `nasus_conversation_messages{role,status}`
- `nasus_agent_goals{status}`
- `nasus_agent_swarm_runs{status}`
- `nasus_tool_invocations{status}`
- `nasus_quality_runs{status}`
- `nasus_approvals{status}`
- `nasus_merge_resolutions{status}`
- `nasus_raw_assets{source_type,status}`
- `nasus_failure_reports{status,fallback_to_human}`
- `nasus_release_readiness{status}`
- `nasus_llm_calls{route,outcome,runtime_mode}`
- `nasus_llm_tokens{route,direction}`
- `nasus_agent_goal_budget_exhaustions`
- `nasus_repeated_failure_fingerprints`

`route` 必须使用 FastAPI route template，未匹配或认证前拒绝的路径统一标记为
`unmatched`，禁止把原始 ID 路径写成指标 label 造成高基数。

业务运行指标必须从 PostgreSQL 持久事实生成，而不是使用 API 进程内计数器。
这样 API/Worker 横向扩展、Temporal 恢复和实例重启后仍保持一致。所有 label 只能
使用平台控制的状态、路由和来源枚举，禁止暴露项目 ID、工具 ID、模型名或原始错误。

独立 Runner 通过带 `NASUS_RUNNER_SERVICE_TOKEN` 的 `GET /metrics` 暴露
`nasus_runner_active_jobs`、`nasus_runner_max_concurrency`、
`nasus_runner_browser_ready`、`nasus_runner_jobs_total{status}`、
`nasus_runner_rejections_total{reason}` 和
`nasus_runner_job_duration_seconds`。API 必须把当前 `X-Request-ID` 透传给
Runner，Runner 响应和结构化完成日志必须使用同一关联 ID。

- conversation throughput
- tool invocation success rate
- tool waiting_confirmation count
- tool waiting_approval count
- workflow retry count
- worker queue latency
- run success/failure rate
- runner readiness / request latency / rejected target count
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

- PostgreSQL 控制面生产目标 `RPO <= 15 min`，必须使用托管 PITR/WAL
  archive；此外每 6 小时执行一次可移植的 custom-format 逻辑备份。
- MinIO/S3 生产目标 `RPO <= 15 min`，必须启用 bucket versioning 与跨站复制
  或等价对象锁；此外每天执行一次包含所有对象版本和删除标记的逻辑快照。
- 平台整体目标 `RTO <= 4 h`，每个 release 运行隔离恢复演练，生产环境至少每
  季度执行一次完整恢复。
- `npm run backup:data` 先写 `.partial` 恢复点；只有 PostgreSQL dump、所有
  S3 version payload、SHA-256 和 manifest HMAC 全部验证后才原子发布目录。
- `npm run restore:data -- <backup-directory>` 必须提供精确 backup ID、停止写
  流量并明确授权替换目标 bucket；恢复后校验对象 hash、版本数和删除标记。
- `npm run verify:backup-restore` 必须通过“备份 -> 后置变更 -> 恢复 -> 精确状态
  对比”，并纳入 `verify:v1-release`。
- Workflow 状态必须可重入恢复；关键审计事件、审批链和对象存储引用必须在恢复
  后进行一致性抽样校验。
- 详细操作步骤、密钥要求、恢复顺序和流量重开检查见
  [Backup And Recovery Runbook](./backup-and-recovery-runbook.md)。

## 6. 测试矩阵

### 6.1 单元测试

- domain model
- policy checks
- gate rules
- tool routing
- worker result parsing
- runner command validation、host allowlist、result envelope parsing

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
- API -> authenticated Runner -> MinIO Evidence
- candidate -> approval -> baseline writeback
- baseline fork overlay query + materialized snapshot read

### 6.5 故障注入测试

- worker 崩溃恢复
- runner 超时
- approval 长时间等待
- queue 重投递
- repeated healing failure fingerprint
- unauthorized execution environment access attempt
- embedding Provider 在首批向量或查询向量阶段超时
- rerank Provider 在部分上下文已经计算后返回 5xx
- 上述模型故障后 PostgreSQL 与进程投影均恢复到物化前快照

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
| Staging | Temporal/LangGraph、runner、approval、fault injection、权限负测 | workflow 不可恢复、runner 越权、gate 被绕过、跨项目访问未阻断 | replay report、audit trace |
| V1 Candidate | `npm run verify:v1-release` | Web 主链路失败、Docker PostgreSQL/MinIO 验证失败、工具/审计链断裂 | candidate evidence pack |
| Release | production-like Docker 拓扑、真实或协议级 stub LLM/embedding/rerank、Temporal worker、真实 runner、E2E P0 纵切、backup/restore、SLO smoke、security smoke | 无法完成端到端放行、证据丢失、审计链断裂、生产 runtime fallback 未治理、RBAC/OIDC 缺口未关闭 | release evidence pack |

## 9. P0 自动化验收用例

- 代码 source 缺失时 AgentGoal pause，不能初始化 Official Baseline。
- 只有真实代码路径时可生成低置信 baseline；US / 测试资产齐全时必须额外验证跨源关系，并产生完整审计链。
- 远程 Git source 必须真实 clone/fetch 到托管 cache，记录 commit revision，并从该 revision 生成 chunk 和 ContextObject；host 越权、URI 内嵌凭据、超时和 clone 失败必须阻断画像物化。
- 必选代码 source 失败时 materialize / baseline 被阻断，修复后恢复同一个 AgentGoal；可选 US / 测试 source 失败只形成可审计 coverage gap。
- 创建 version、导入 US、生成 TaskContext / QualityProfile；缺失或 stale 时禁止质量生成。
- 生成 scope / scenario / case，CoverageMatrix 闭合到验收标准和系统画像对象。
- 生成 AutomationBlueprint 后 `run.start` 产出 Run 和 append-only Evidence。
- failed Run 生成 FailureReport；重复 fingerprint 或 max healing depth 触发 fallback-to-human。
- `release.advice.get` 聚合 US、资产、Run、Evidence、Approval、pending_merge。
- `release.assess` 只能生成 `ReleaseReadiness`，不能直接创建正式 `ReleaseDecision`。
- `approval.request`、`approval.decide`、`release.decision.submit`、`resolution.merge`、`baseline.promote` 必须进入 gate，Agent 不能直接写正式结论。
- SSE 事件序列能被前端 reducer 精确合并；重复、乱序、断线恢复不破坏最终状态。
### Code graph provider contract

- V1 staging/production 必须配置 `NASUS_CODE_GRAPH_MODE=required`。
- `npm run verify:code-graph-provider` 必须调用镜像中固定版本的真实 Codebase Memory 二进制，而不是 fake CLI。
- 门禁至少证明：索引成功、实体非空、关系非空、结果不越过已摄入源文件集合、Nasus 领域 QName 不包含 Provider 工作区身份。
- Provider 升级必须先通过该门禁和系统画像摄入回归，禁止仅根据 `--version` 或 `/readyz` 探测结果升级。
