# Nasus 首发 Tool Catalog（V1）

## 1. 文档定位

本文定义 Nasus 首发必须实现的工具目录，作为 `Tool Registry`、`Conversation Orchestrator`、前端 `Tool Palette` 和后端 `Tool Invocation Runtime` 的开发基线。

## 2. 设计原则

- 工具命名采用 `domain.action` 形式
- 工具必须先有 `ToolDefinition`，再允许被 Agent、UI 或外部 API 触发
- 首发工具目录优先覆盖“项目接入 -> 版本创建 -> US 闭环 -> 执行 -> 放行”主链路
- 未进入 V1 catalog 的能力不得被实现成隐式按钮逻辑
- Agent Swarm 中的子 Agent 也只能通过 catalog 中的工具执行动作，不能绕过工具目录直接调用领域服务

## 3. V1 首发工具清单

### 3.1 Project Tools

| tool_id | 用途 | 默认 scope | 风险 |
| --- | --- | --- | --- |
| `project.create` | 创建项目空间 | `central` | `medium` |
| `project.assets.connect` | 连接 Git、US、UX、OpenAPI 等原料 | `central` | `medium` |
| `baseline.initialize` | 初始化 Historical / Official Baseline | `central` | `high` |
| `project.status.get` | 查询项目接入状态与画像状态 | `central` | `low` |

### 3.2 Version Tools

| tool_id | 用途 | 默认 scope | 风险 |
| --- | --- | --- | --- |
| `version.create` | 创建版本分支 | `central` | `medium` |
| `version.inputs.import` | 导入版本级 US / 文档 / OpenAPI / 设计输入 | `central` | `medium` |
| `version.branch.bind` | 绑定 Git 开发分支 / 变更范围 | `central` | `medium` |
| `version.progress.get` | 查询版本质量进度与风险摘要 | `central` | `low` |
| `version.participants.assign` | 分配版本参与者与 US 负责人 | `central` | `medium` |

### 3.3 US / Task Tools

| tool_id | 用途 | 默认 scope | 风险 |
| --- | --- | --- | --- |
| `us.task.start` | 启动某个 US 的质量闭环 | `central` | `low` |
| `quality.scope.generate` | 生成测试范围 | `central` | `low` |
| `quality.scenario.generate` | 生成测试场景 | `central` | `low` |
| `quality.plan.generate` | 生成验证计划 | `central` | `low` |
| `quality.case.generate` | 生成测试用例 | `central` | `low` |
| `quality.change-doc.generate` | 生成变更文档 / 变更方案 | `central` | `low` |
| `quality.asset-pack.refresh` | 汇总并刷新 `QualityAssetPack` | `central` | `medium` |
| `us.status.get` | 查询某个 US 的闭环状态 | `central` | `low` |

### 3.4 Execution Tools

| tool_id | 用途 | 默认 scope | 风险 |
| --- | --- | --- | --- |
| `automation.generate` | 生成自动化资产 | `central` | `medium` |
| `run.start` | 触发执行 | `central` | `medium` |
| `run.progress.get` | 查询执行进度与证据摘要 | `central` | `low` |
| `failure.analyze` | 分析失败原因 | `central` | `low` |
| `healing.propose` | 生成修复建议 | `central` | `medium` |

### 3.5 Governance Tools

| tool_id | 用途 | 默认 scope | 风险 |
| --- | --- | --- | --- |
| `approval.request` | 发起审批 | `central` | `high` |
| `resolution.merge` | 处理 `pending_merge` 冲突 | `central` | `high` |
| `baseline.promote` | 推进基线晋级 / 回写 | `central` | `critical` |
| `release.advice.get` | 查询放行建议 | `central` | `low` |

### 3.6 Query / Insight Tools

| tool_id | 用途 | 默认 scope | 风险 |
| --- | --- | --- | --- |
| `progress.get` | 查看当前测试进度 | `central` | `low` |
| `risk.summary.get` | 查看当前版本风险摘要 | `central` | `low` |
| `system-image.inspect` | 查看系统画像片段与关联关系 | `central` | `low` |
| `conflicts.get` | 查看当前冲突项 | `central` | `low` |

## 4. V1 首个生产切片的最小子集

为了启动首个可生产部署版本，至少先实现以下工具。它们不是演示按钮，而是 Agent、UI 和 API 共用的 canonical action surface：

- `project.create`
- `project.assets.connect`
- `baseline.initialize`
- `version.create`
- `version.inputs.import`
- `us.task.start`
- `progress.get`
- `quality.scope.generate`
- `quality.scenario.generate`
- `quality.case.generate`
- `automation.generate`
- `run.start`
- `run.progress.get`
- `failure.analyze`
- `approval.request`

## 5. 工具实现默认值

- 所有首发工具都必须进入 `GET /v1/tools/catalog`
- 所有写工具都必须通过 `POST /v1/tool-invocations`
- 高风险工具默认进入 `waiting_confirmation` 或 `waiting_approval`
- 前端工具面板只展示已注册到 catalog 的工具
