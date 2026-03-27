# Nasus 质量资产生成策略设计

## 1. 文档定位

本文定义 Nasus 如何生成测试范围、测试场景、测试计划、测试用例、自动化脚本、变更文档，以及如何做失败分析、修复建议和多轮审核收敛。

这部分决定 Agent 产出的质量，是质量闭环的核心“大脑”设计。

## 2. 统一输入与约束

所有质量生成工具默认使用：

- `USWorkItem`
- `TaskContext`
- `QualityProfile`
- `Version baseline overlay`
- `related ContextObjects`
- `historical failures / historical assets`
- `policy snapshot`

统一约束：

- 没有 `TaskContext + QualityProfile` 不进入生成阶段。
- 输出必须是结构化对象，不允许只给自由文本。
- 产物必须写回 `QualityAssetPack` 的明确字段。

## 3. 质量范围生成

### 3.1 `quality.scope.generate`

目标：

- 明确本次变更应覆盖的功能边界、接口边界、回归边界和排除项。

策略：

1. 读取 `git delta + US + system image slices`
2. 识别受影响模块、页面、接口、依赖
3. 识别高风险路径与历史失败热点
4. 输出：
   - `in_scope`
   - `out_of_scope`
   - `regression_targets`
   - `risk_targets`

写入：

- `QualityAssetPack.coverage_scope_ref`

## 4. 场景生成

### 4.1 `quality.scenario.generate`

目标：

- 产出场景级测试集合，而不是直接跳到用例细节。

场景分类至少包括：

- 主流程
- 关键分支
- 错误路径
- 权限路径
- 兼容性 / 回归路径
- 边界与异常数据路径

策略：

1. 先根据 `coverage_scope` 分桶
2. 再按风险等级排序
3. 对每个风险桶生成场景
4. 场景必须带：
   - `scenario_id`
   - `title`
   - `objective`
   - `preconditions`
   - `linked_context_objects`
   - `risk_reason`

写入：

- `QualityAssetPack.scenario_set_ref`

## 5. 验证计划生成

### 5.1 `quality.plan.generate`

目标：

- 把场景转成验证策略、环境、数据和执行安排。

输出：

- 验证优先级
- 环境要求
- 数据要求
- 手工/自动化划分
- 是否需要性能验证
- 是否需要审批点

写入：

- `QualityAssetPack.verification_plan_ref`

## 6. 测试用例生成

### 6.1 `quality.case.generate`

目标：

- 产出可执行、可审阅、可回写的测试用例结构。

每条用例至少包含：

- `case_id`
- `scenario_id`
- `title`
- `steps`
- `expected_results`
- `test_data_hint`
- `assertion_type`
- `priority`

策略：

- 一条场景可展开多条用例
- 用例粒度以“可独立执行和归因”为准
- 断言优先引用系统可观察对象，不写模糊文案

写入：

- `QualityAssetPack.case_set_ref`

## 7. 自动化脚本生成

### 7.1 `automation.generate`

目标：

- 基于已批准或 review-ready 的用例生成 Playwright 资产。

默认策略：

1. 先筛选适合自动化的用例
2. 为每条自动化用例生成：
   - test file skeleton
   - fixture / data hint
   - selector strategy
   - assertion plan
3. 统一收敛到项目测试模板

脚本生成约束：

- 不直接从自然语言跳脚本，必须基于 case set
- selector 策略优先使用稳定属性与业务锚点
- 脚本必须带 `linked_case_ids`

写入：

- `QualityAssetPack.automation_asset_ref`

## 8. 性能资产生成

### 8.1 `performance.generate`

目标：

- 仅在 `QualityProfile` 或 `coverage_scope` 标识出性能关注点时生成。

输出：

- 负载模型
- 关键指标
- 采样点
- 简化性能脚本或性能验证说明

写入：

- `QualityAssetPack.performance_asset_ref`

## 9. 变更文档生成

### 9.1 `quality.change-doc.generate`

目标：

- 产出版本或 US 级变更说明，服务于沟通、审核和上线判断。

信息来源：

- US 描述
- git delta
- scope/scenario/case 摘要
- 风险项
- 历史画像差异

写入：

- `QualityAssetPack.change_doc_ref`

## 10. 失败分析

### 10.1 `failure.analyze`

输入：

- logs
- trace
- screenshots
- DOM snapshot
- environment snapshot
- historical failure fingerprints

策略：

1. 先做确定性解析
2. 再用 LLM 做归因摘要
3. 产出：
   - `failure_kind`
   - `suspected_causes`
   - `confidence`
   - `evidence_refs`
   - `matching_historical_fingerprints`

## 11. 修复建议

### 11.1 `healing.propose`

策略：

- 仅在 `failure.analyze` 已有稳定归因时触发
- patch proposal 必须带：
  - `target_files`
  - `patch_summary`
  - `risk_note`
  - `retry_recommendation`

限制：

- 命中 `Max Healing Depth`
- 命中重复 `failure_fingerprint`
- 风险等级超阈值

则必须 fallback-to-human。

## 12. 放行建议

### 12.1 `release.advice.get`

输入：

- 版本级质量资产摘要
- 执行结果摘要
- 未闭环项
- 审批状态
- baseline promotion 状态

输出：

- `readiness_status`
- `blocking_issues`
- `conditional_risks`
- `recommended_actions`

## 13. 多轮审核与局部重生成

### 13.1 审核原则

- 审核是资产级，不是整包推倒重来。
- 用户可以对 `scope/scenario/case/automation/change_doc` 分别批准或拒绝。

### 13.2 局部重生成

局部重生成必须指定：

- `target_asset_part`
- `reason`
- `preserve_refs`
- `regenerate_scope=replace|append|refine`

默认规则：

- 已批准部分默认冻结，不参与下轮重生成
- 只重生成被拒绝或过期部分

## 14. QualityAssetPack 协作与版本

### 14.1 Revision 规则

- `QualityAssetPack.current_revision` 每次关键资产变更递增
- 每个资产部分都保留 `part_revision`
- 生成新 revision 时，不覆盖旧 revision，只更新 current pointer

### 14.2 并发写规则

- 多 Task 并行写同一 pack 时，采用：
  - `asset_part` 级乐观锁
  - `expected_revision`
  - 冲突进入 `pending_merge`

### 14.3 导出

首发支持：

- `markdown`
- `json`
- `csv/xlsx` 仅针对 case set 和 summary 视图

## 15. 首发默认模型路线

- `scope/scenario/case/change-doc`：`structured + planner` 组合
- `automation.generate`：`structured` 优先，必要时加代码生成模板
- `failure.analyze / healing.propose / release.advice`：稳定性优先的高质量模型

模型路由细节以 [docs/llm-provider-and-runtime-design.md](/Users/uben/project/project/Nasus/docs/llm-provider-and-runtime-design.md) 为准。
