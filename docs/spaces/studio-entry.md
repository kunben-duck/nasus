# 模块设计：studio-entry

## 1. 模块目标

`studio-entry` 承担 Nasus 的顶层产品入口，负责让用户进入正确的工作空间，而不是直接落到细节页。

它覆盖：

- `Welcome`
- `Build`
- `Dashboard`
- `Documentation`

## 2. 模块边界

负责：

- 顶层导航与产品入口壳层
- 新项目创建引导
- 全局项目组合视图
- 顶层会话体验
- 文档帮助与模板入口

不负责：

- 项目内质量工作流
- 单个 US 的质量闭环
- 审批、执行、知识细节

## 3. 前端组成

### 3.1 页面

- `WelcomePage`
- `BuildPage`
- `DashboardPage`
- `DocumentationPage`

### 3.2 共享组件

- `GlobalNav`
- `TopLevelStudioShell`
- `ConversationWorkspaceCard`
- `ProjectCard`
- `SummaryStatCard`
- `SuggestionChip`

### 3.3 右栏规范

- `Welcome`：`Activity / Tips / Status`
- `Build`：`Projects / Imports / Health`
- `Dashboard`：`Alerts / Progress / Activity`
- `Documentation`：`Topics / Templates / Updates`

## 4. 后端组成

### 4.1 主要对象

- `Project`
- `ConversationSession`
- `ConversationMessage`
- `ToolInvocation`
- `ConnectorRun`（Build 关注）

### 4.2 主要工具

- `project.create`
- `project.import.git`
- `project.import.us`
- `project.import.ux`
- `project.initialize.system_image`
- `query.portfolio.status`
- `query.project.status`

### 4.3 主要接口

- `GET /v1/welcome`
- `GET /v1/build`
- `GET /v1/dashboard`
- `GET /v1/documentation`
- `POST /v1/conversations/{id}/messages`
- `GET /v1/tools/catalog`

## 5. 开发指导

- `Build` 必须始终以“创建项目”和“导入原料”为主，不得退化成项目列表页。
- `Dashboard` 必须以项目组合视图为中心，点击项目卡后下钻到独立项目空间。
- 会话是主入口，页面 CTA 只是同一工具调用的显式封装。
- 前端视觉与布局必须与 `ux/` 原型对应页面一致。

## 6. 验收标准

- 用户可以在 `Build` 中通过表单或对话完成项目创建和原料导入。
- `Dashboard` 能展示项目组合状态、风险、阻塞项与最近活动。
- 点击项目卡能进入独立 `Project Space`，且左侧导航整体切换。
