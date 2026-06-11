# Nasus 端到端数据流示例

## 1. 文档定位

本文通过几条完整链路说明 Nasus 后端各层如何串联：`Conversation -> Tool -> Workflow -> Skill -> Worker -> Domain Objects -> SSE -> Frontend`。

同时补充首发服务间通信矩阵，减少开发时的理解偏差。

## 2. 服务间通信矩阵

| 来源 | 目标 | 通信方式 | 首发默认值 |
| --- | --- | --- | --- |
| Frontend UI | `api/orchestrator` | REST + SSE | 固定 |
| `api/orchestrator` | `workflow-service` | Temporal Client / Workflow Signal | 固定 |
| `workflow-service` | `worker-runtime` | 队列驱动 WorkerJob 分发 | 协议固定，队列产品未写死 |
| `workflow-service` | `runner` | run queue / command dispatch | 协议固定，传输实现可替换 |
| `worker-runtime` | `llm-gateway` | 内部 SDK / service call | 固定 |
| `workflow-service` | PostgreSQL / MinIO | ORM / object storage client | 固定 |

规则：

- 不允许前端直接调 worker、runner。
- 工作流信号、审批恢复、断点恢复统一经 `workflow-service`。

## 3. 示例一：Build 页创建项目并初始化系统画像

1. 用户在主会话输入：`帮我创建一个新项目`
2. `Conversation Orchestrator` 读取 `Build` 空间上下文，产出 `AgentGoal` 或多步 `ToolInvocationPlan`
3. Agent 追问：
   - Git 仓库
   - US 文档
   - UX 资产
   - 历史测试资产
4. 每次补充信息写入 `ConversationMessage`
5. 当必填信息齐备后，依次触发：
   - `project.create`
   - `project.assets.connect`
   - `baseline.initialize`
6. `baseline.initialize` 进入 `ProjectInitializationWorkflow`
7. Workflow 触发：
   - connector run
   - raw asset ingest
   - UCE 解析与 entity resolution
   - baseline materialization
8. 结果物化：
   - `Project`
   - `Baseline`
   - `ContextObjects`
9. SSE 回传：
   - `tool.invoked`
   - `tool.progress`
   - `tool.completed`
   - `conversation.plan.updated`
10. 前端 Build 页面显示初始化进度卡与项目创建完成卡

## 4. 示例二：Version Space 启动一个 US 质量闭环

1. 用户在 `Version Space` 说：`启动 US-123 的质量分析`
2. `Conversation Orchestrator` 绑定 `project/version/us`
3. 产出工具链：
   - `us.task.start`
   - `quality.scope.generate`
   - `quality.scenario.generate`
   - `quality.plan.generate`
   - `quality.case.generate`
   - `quality.asset-pack.refresh`
4. `TaskWorkflow` 创建：
   - `Task`
   - `TaskContext`
   - `QualityProfile`
5. Tool 内部进入 `LangGraph`
6. Graph 路由：
   - `context.enrich`
   - `impact.analyze`
   - `verification.plan`
   - `scenario.generate`
   - `case.generate`
7. 结果通过 `Domain Materialization Layer` 写入：
   - `TaskContext`
   - `QualityProfile`
   - `QualityAssetPack`
8. SSE 回传：
   - `assistant.block.updated`
   - `task.updated`
   - `tool.completed`
9. 前端 `Personal Workspace` 中间栏看到对话总结，右栏看到 `QualityAssetPack` 更新

## 5. 示例三：执行 -> 失败 -> 修复建议 -> 人工兜底

1. 用户在 `Personal Workspace` 说：`生成自动化并执行`
2. Agent 调用：
   - `automation.generate`
   - `run.start`
3. `run.start` 创建 `Run(execution_channel=web_runner)`
4. `runner` 执行 Playwright 资产并上传：
   - logs
   - screenshots
   - trace
   - environment snapshot
5. 运行失败后触发：
   - `failure.analyze`
   - 若策略允许，再触发 `healing.propose`
6. 若命中：
   - `max_healing_depth`
   - 重复 `failure_fingerprint`
   - 风险超阈值
7. Workflow 直接把状态转为 `fallback_to_human`
8. 前端 `Runs` 页面收到：
   - `run.updated`
   - `tool.failed`
   - `assistant.block.updated`
   - `notification.created`
9. 用户进入 `Run Detail` 查看失败归因和 patch proposal

## 6. 示例四：中心端候选结果冲突

1. 中心端在不同工具链或不同候选分支下对同一 `Task` 产生冲突的 `AgentDecision(status=provisional)`
2. `Merge / Score` 检测冲突
3. 创建 `MergedResolution(status=pending_merge)`
4. SSE 推送：
   - `conflict.detected`
5. 前端 `Governance` 页面显示冲突详情
6. 用户执行：
   - `resolution.merge`
   - 若为高风险，再进入 `approval.request`
7. 审批通过后：
   - `MergedResolution -> approved`
   - `Task -> ready_for_release / completed`

## 7. 示例五：版本收口与基线回写

1. 版本完成后，用户说：`回写这个版本的新增知识到官方基线`
2. Agent 生成：
   - `release.advice.get`
   - `baseline.promote`
3. `baseline.promote` 属于 `critical`
4. 先进入：
   - `waiting_confirmation`
   - `waiting_approval`
5. 审批通过后，`RebaselineWorkflow` 执行：
   - 从 version overlay 读取增量对象
   - 应用到 official baseline
   - 生成新 `materialized_snapshot_ref`
6. 审计写入：
   - `approval.completed`
   - `resolution.merged`
   - `baseline.writeback.completed` 可作为内部事件

## 8. 开发者实现顺序建议

1. Build 项目创建链路
2. Version/US 质量闭环链路
3. Run/Failure/Healing 链路
4. Governance/Merge/Approval 链路
5. Rebaseline 链路

这样可以先跑通最小 Web 主链路，再逐步增加治理深度。
