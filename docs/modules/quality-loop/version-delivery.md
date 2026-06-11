# 模块设计：version-delivery

## 1. 模块目标

`version-delivery` 负责把项目正式基线分叉成版本工作分支，并围绕版本组织 US、参与者和风险。

## 2. 模块边界

负责：

- `Version Space`
- `Version Create`
- US 导入、分配和版本风险初始化

不负责：

- US 级质量资产生成细节
- 执行、审批和放行细节

## 3. 前端组成

- `VersionSpacePage`
- `VersionCreatePage`
- `USBoard`
- `OwnerAssignmentPanel`
- `VersionRiskPanel`

## 4. 后端组成

### 4.1 主要对象

- `Version`
- `USWorkItem`
- `Task`
- `Baseline overlay`

### 4.2 主要工具

- `version.create`
- `version.import.us`
- `version.assign.owners`
- `version.risk.initialize`
- `query.version.progress`

## 5. 开发指导

- `Version Create` 是 `Version Space` 的详情态，不应脱离父导航上下文。
- `USWorkItem` 与 `Task` 明确为 `1:N`。
- 版本创建必须同时完成：分支建立、US 导入、初始风险种子和责任人分配。

## 6. 验收标准

- 版本可从项目空间创建并落成独立版本分支。
- `Version Space` 能以 board 方式展示 US、负责人、风险和当前进展。
