# 模块设计：quality-workspace

## 1. 模块目标

`quality-workspace` 是 Nasus 的核心业务模块，负责单个 US 的完整质量闭环工作台。

## 2. 模块边界

负责：

- `Personal Workspace`
- `TaskContext`
- `QualityProfile`
- `QualityAssetPack`
- `AgentGoal`

不负责：

- 项目级基线接入
- 版本级组合管理
- 放行审批最终裁决

## 3. 前端组成

- `PersonalWorkspacePage`
- `ChatTimeline`
- `QualityAssetPackPanel`
- `AgentGoalCard`
- `ActionComposer`
- `ToolInvocationTimeline`

## 4. 后端组成

### 4.1 主要对象

- `Task`
- `TaskContext`
- `QualityProfile`
- `QualityAssetPack`
- `AgentGoal`
- `ToolInvocation`

### 4.2 主要工具

- `quality.scope.generate`
- `quality.scenario.generate`
- `quality.plan.generate`
- `quality.case.generate`
- `automation.generate`
- `performance.generate`
- `quality.change-doc.generate`

## 5. 开发指导

- `Personal Workspace` 必须保持 `agent-first`，中间主画布优先展示会话和 Agent Goal，不得退化为表单页。
- 质量资产必须以 `QualityAssetPack` 为统一聚合，不允许每类资产散落在无关联对象中。
- 资产重生成必须支持局部重生成和 revision 语义。

## 6. 验收标准

- 单个 US 能在一个工作空间内完成：分析、场景、计划、用例、自动化、变更文档与总结。
- Agent Goal 的思考、行动、观察、决策过程可见且可打断/恢复。
