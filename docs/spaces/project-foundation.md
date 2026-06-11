# 模块设计：project-foundation

## 1. 模块目标

`project-foundation` 负责项目空间的长期资产与正式基线，是版本工作的源头。

## 2. 模块边界

负责：

- `Project Overview`
- 项目级原料接入状态
- `Official System Image Branch`
- 项目级风险和连接源状态

不负责：

- 版本级增量任务
- 单个 US 的质量资产生成

## 3. 前端组成

- `ProjectOverviewPage`
- `ConnectedSourcesPanel`
- `SystemImagePanel`
- `VersionCardList`
- `RiskSignalPanel`

## 4. 后端组成

### 4.1 主要对象

- `Project`
- `Baseline`
- `RawAssetRecord`
- `ContextObject`
- `ConnectorBinding`
- `ConnectorRun`

### 4.2 主要工具

- `project.refresh.system_image`
- `project.inspect.baseline`
- `query.project.status`
- `query.project.risk`

## 5. 开发指导

- 项目空间是“长期资产空间”，任何版本工作都不能直接污染 `Official Baseline`。
- 项目页必须展示已接入原料、系统画像状态、活跃版本和最近风险信号。
- 所有“刷新系统画像”动作必须通过工具调用驱动，并写审计。

## 6. 验收标准

- 页面能稳定展示项目摘要、连接源、系统画像状态和活跃版本。
- `Official Baseline` 状态与最近一次接入任务可追溯。
