# 系统画像构建：知识摄入管线

## 1. 文档定位

本文聚焦系统画像构建模块中的“原料如何进入系统”这一条主线。

它不替代 Context Engine 总设计，而是专门回答：

- Git、文档、UX、OpenAPI、历史测试资产如何进入系统
- 摄入任务如何编排、失败、重试和审计
- 原料如何从 `RawAssetRecord` 演进为 `ContextObject`

## 2. 摄入目标

首个生产版本中，摄入管线必须优先支持三类一等 source：

- Git 仓库
- US 文档
- 历史测试用例和自动化脚本

增强 source 可后续接入：

- UX / 设计资料
- OpenAPI / 接口描述
- 历史缺陷与执行证据

摄入结果不直接等于正式系统画像，而是：

`Raw Assets -> 结构候选 -> ContextObject -> Baseline`

## 3. 处理阶段

### 3.1 接入

- 连接外部源
- 校验凭据与权限
- 建立 `ConnectorBinding`

### 3.2 拉取

- 抓取原始内容
- 写入 `RawAssetRecord`
- 记录 `ConnectorRun`

### 3.3 解析

- 代码解析
- US 文档切块与验收标准抽取
- 测试用例、测试脚本、断言、测试数据和覆盖对象抽取
- UX / OpenAPI 结构提取（增强 source）

### 3.4 关联

- Anchor Extraction
- Entity Resolution
- 生成 `ContextRelationship`
- 建立三类核心关系：
  - `US -> impacted code objects`
  - `TestCase / Script -> verifies US / AcceptanceCriteria`
  - `AutomationScript -> covers API / Page / Module`

### 3.5 入基线

- 形成 `Historical System Baseline`
- 审核后写入 `Official Baseline`

## 4. 关键要求

- 摄入必须 append-only，可回放
- 每次摄入都必须可审计
- 部分失败不能污染正式基线
- 必须支持增量重跑与重建
- 代码、US、测试资产三类 source 必须都能增量更新，并产生版本工作画像 overlay
- 每次摄入后必须能计算或刷新质量指标快照
- 三类一等 source 没有真实绑定时，不得静默使用默认占位 URI 完成摄入、画像物化或基线初始化。
- Agent 可先创建 source slots，但 `ToolResult.requires_followup=true` 时必须暂停 AgentGoal，并引导用户补充 code / US docs / test assets 的真实路径或外部 URI。
- 用户在同一会话补充 source 绑定后，Agent 才能恢复 `system_image.sources.register -> system_image.sources.ingest -> system_image.context.materialize -> system_image.baseline.initialize` 后续链路。

## 5. 三源摄入策略

### 5.1 代码 source

最低抽取：

- repository / branch / commit
- file / module / package / service
- class / function / method / component
- route / API handler
- import / call / dependency
- changed object range

输出：

- `CodeSymbol`
- `Module`
- `Service`
- `API`
- `ContextRelationship`

### 5.2 US source

最低抽取：

- US 编号
- 标题和业务描述
- 验收标准
- 角色 / 权限
- 前置条件 / 后置条件
- 主流程 / 异常流程
- 影响模块或接口的文本锚点

输出：

- `USWorkItem`
- `AcceptanceCriteria`
- `BusinessFlow`
- `RiskHint`

### 5.3 测试资产 source

最低抽取：

- 测试场景
- 测试用例
- 自动化脚本入口
- 断言
- 测试数据
- 依赖环境
- 覆盖对象锚点
- 历史执行结果引用

输出：

- `TestScenario`
- `TestCase`
- `AutomationScript`
- `ExecutionEvidence`
- `CoverageRelationship`

## 6. 对应主文档

- [系统画像构建模块总览](./README.md)
- [Context Engine 设计](./context-engine.md)
- [基线与分支规则](./baseline-and-branching.md)
- [后端总设计](../backend/system-design.md)
