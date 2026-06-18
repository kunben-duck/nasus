# 系统画像构建：基线与分支规则

## 1. 文档定位

本文聚焦系统画像构建模块中的基线与分支规则。

它回答：

- 正式系统基线是什么
- 版本工作基线如何从正式基线派生
- 版本知识如何回写正式基线

## 2. 基线层级

- `Historical System Baseline`
  - 摄入后的原始结构化候选快照
- `Official Baseline`
  - 当前正式系统画像分支
- `Version Working Baseline`
  - 某次版本的工作分支

## 3. 分支原则

- 所有版本都从 `Official Baseline` 派生
- 版本期间只能更新工作基线
- 不允许直接污染正式基线
- 版本结束后，经治理和审批才能回写正式基线
- 每个版本新增或变更的代码、US、测试用例和脚本都写入 `Version Working Baseline Overlay`
- overlay 是长期模型，不是临时 patch；必须能被查询、审计、合并和回放

## 4. 合并原则

- 高价值知识先进入 `Candidate`
- 经审批后进入 `Version Shared`
- 最终再合并进入 `Official Baseline`
- 合并对象必须保留：
  - source refs
  - evidence refs
  - approval refs
  - conflict payload
  - merge rationale

## 5. 实现约束

- 首发采用 `overlay first, parent fallback`
- 所有 merge 都必须保留来源、证据和审批记录
- 冲突必须进入标准治理流，而不是直接覆盖
- 查询实现必须支持 baseline-aware traversal：
  - 先查当前版本 overlay
  - overlay 未命中则回退 official baseline
  - 对同一对象字段冲突返回 conflict payload
- 质量指标也必须分层：
  - official baseline metric
  - version overlay metric
  - task / US metric snapshot

## 6. 长期存储约束

V1 必须按长期基线架构建模：

- `Baseline` 保存基线元信息
- `ContextObject` 保存对象事实
- `ContextRelationship` 保存对象关系
- `ContextObjectOverlay` 保存版本级增量
- `QualityMetricSnapshot` 保存质量指标快照
- `ApprovalRecord` 保存晋级和回写审批

禁止把版本画像实现成不可追踪的 JSON 大字段或临时缓存。

## 7. 对应主文档

- [系统画像构建模块总览](./README.md)
- [Context Engine 设计](./context-engine.md)
- [系统架构与部署设计](../../system-architecture.md)
- [后端领域模型](../backend/domain-model.md)
