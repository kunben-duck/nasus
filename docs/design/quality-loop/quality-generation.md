# Nasus Skill 与质量生成设计

## 1. 文档定位

本文合并原“Skill 实现模式设计”和“质量资产生成策略设计”，统一定义：

- Skill 的代码实现模式、协议与版本管理
- 质量资产生成链路的策略、输出结构和回写规则
- `Tool -> Skill -> Worker -> QualityAssetPack` 的完整闭环

优先级关系：

- 产品规则以 [最终特性说明书](../../final-feature-spec.md) 为准。
- 工具协议以 [../backend/runtime-and-tool-protocol.md](../backend/runtime-and-tool-protocol.md) 为准。
- 模型路由与 Prompt 管理以 [LLM 运行时设计](../agent/llm-runtime.md) 为准。

## 2. Skill 的角色定位

- Tool 是产品级动作
- Skill 是 Tool 背后的内部能力组件
- Worker 是 Skill 的执行单元

Skill 是 Agent 的“手”，质量生成策略是 Agent 的“生成大脑”。

## 3. Skill 分类

首发 Skill 分为 4 类：

- `deterministic`
- `llm_assisted`
- `hybrid`
- `supporting`

首发关键 Skill：

- `baseline.build`
- `context.enrich`
- `impact.analyze`
- `verification.plan`
- `scenario.generate`
- `case.generate`
- `automation.generate`
- `performance.generate`
- `failure.analyze`
- `healing.propose`
- `release.assess`

## 4. 实现骨架

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class SkillContext:
    tool_invocation_id: str
    task_id: str | None
    task_context_id: str | None
    quality_profile_id: str | None
    policy_snapshot_id: str
    evidence_refs: list[str]
    actor_ref: str

@dataclass
class SkillResult:
    status: str
    summary: str
    structured_output: dict[str, Any]
    object_refs: list[str]
    evidence_refs: list[str]
    next_worker_jobs: list[dict[str, Any]]

class SkillExecutor:
    skill_id: str
    skill_type: str
    input_schema_ref: str
    output_schema_ref: str

    def validate_input(self, payload: dict[str, Any]) -> None:
        ...

    def run(self, ctx: SkillContext, payload: dict[str, Any]) -> SkillResult:
        ...
```

规则：

- 每个 Skill 必须有固定 `input_schema_ref / output_schema_ref`
- Skill 不直接写正式事实对象，只能通过物化层回写
- 输出必须可追溯到 `tool_invocation_id`

## 5. Skill 协议

### 5.1 SkillInvocationRequest

- `tool_invocation_id`
- `skill_id`
- `task_context_id`
- `quality_profile_id`
- `input_payload`
- `input_evidence_refs`
- `policy_snapshot_id`
- `resume_payload` 可空

### 5.2 SkillInvocationResult

- `status=succeeded|failed|partial`
- `summary`
- `structured_output`
- `object_refs`
- `evidence_refs`
- `worker_jobs`
- `retryable`
- `error_code`

## 6. Skill 与 LLM

### 6.1 何时调用 LLM

优先 `llm_assisted / hybrid`：

- 场景生成
- 用例生成
- 失败归因摘要
- 修复建议
- 放行建议摘要

优先 `deterministic`：

- 风险规则聚合
- ContextObject 查询与拼装
- evidence 归档
- schema 校验
- patch/diff 结构化

### 6.2 Prompt 约束

每个使用 LLM 的 Skill 都必须绑定：

- `prompt_id`
- `prompt_version`
- `input_schema_ref`
- `output_schema_ref`
- `fallback_model_class`

## 7. Tool、Skill、Worker 的关系

### 7.1 Tool -> Skill

- 一个 Tool 可映射一个或多个 Skill
- Tool Runtime 决定“是否调用该 Tool”
- 进入 Tool 后，由 Agent Graph Runtime 路由 Skill

### 7.2 Skill -> Worker

示例：

- `scenario.generate`
  - `context-enrichment worker`
  - `risk worker`
  - `scenario drafting worker`
- `failure.analyze`
  - `log parser worker`
  - `trace worker`
  - `screenshot summarizer worker`

## 8. 质量资产生成链路

所有生成工具默认使用：

- `USWorkItem`
- `TaskContext`
- `QualityProfile`
- `Version baseline overlay`
- `related ContextObjects`
- `historical failures / historical assets`
- `policy snapshot`

统一约束：

- 没有 `TaskContext + QualityProfile` 不进入生成阶段
- 输出必须是结构化对象
- 产物必须写回 `QualityAssetPack` 明确字段
- `quality.scenario.generate`、`quality.case.generate`、`automation.generate`、`release.assess` 都必须通过 `ToolInvocationRuntime` 物化领域对象，不能只更新 UI lane 或返回自然语言摘要。
- 首版最小物化对象：
  - `QualityAssetPack`：US 级 1:1 current pack，包含 scenario / case / automation / release 四类 part、revision、source refs 和 evidence refs。
  - `ExecutionEvidence`：append-only 证据对象，保存 storage ref、hash、producer、captured_at、run/case 关联。
  - `ReleaseReadiness`：由 `release.assess` 阶段生成，保存 score、blockers、execution_health 和 evidence refs。
- `ReleaseDecision` 不是质量生成阶段产物，只能由治理链路 `approval.request -> approval.decide -> release.decision.submit` 生成。
- `AssetLane` 只是工作台展示层状态，不是正式质量资产事实源。

### 8.0 V1 运行时契约

V1 的 `quality.scope.generate`、`quality.scenario.generate`、`quality.case.generate` 必须通过
`QualityGenerationPort` 调用当前激活的 chat 模型，并遵守以下顺序：

1. 从 `TaskContext`、`QualityProfile`、当前 `QualityAssetPack` 和 Tool input 组装不可变请求快照。
2. 使用 Prompt Registry 中的版本化 Prompt 请求 JSON structured output。
3. 服务端按对应 Pydantic schema 校验完整输出。
4. 校验通过后，才一次性更新 AssetLane、US 状态、质量指标和 QualityAssetPack part。
5. 生成失败、provider fallback 或 schema 校验失败时不得写入半完成资产。

Prompt Registry 首版种子：

| Tool | prompt_id | prompt_version | output_schema_ref |
| --- | --- | --- | --- |
| `quality.scope.generate` | `quality.scope.generate` | `1.0.0` | `quality-scope-output/v1` |
| `quality.scenario.generate` | `quality.scenario.generate` | `1.0.0` | `quality-scenario-output/v1` |
| `quality.case.generate` | `quality.case.generate` | `1.0.0` | `quality-case-output/v1` |

每个 QualityAssetPack part 必须持久化：

- `structured_content`：经过 schema 校验的正式结构化产物
- `generation.prompt_id / prompt_version`
- `generation.provider / model_name / mode / reason`
- `generation.input_context_hash / generated_at`

运行策略：

- `production/staging`：模型不可用、返回 fallback、JSON 非法或 schema 不通过时 fail-closed，ToolInvocation 进入 `failed`。
- `local/test`：允许确定性 fallback 以支持离线开发，但必须写入 `mode=fallback` 和明确原因，不能伪装成 live 模型产物。
- fallback 只用于可恢复的草稿生成；任何 release decision、审批和正式证据仍必须经过独立治理链路。

### 8.1 `quality.scope.generate`

输出：

- `in_scope`
- `out_of_scope`
- `regression_targets`
- `risk_targets`

写入：

- `QualityAssetPack.coverage_scope_ref`

### 8.2 `quality.scenario.generate`

场景分类至少包括：

- 主流程
- 关键分支
- 错误路径
- 权限路径
- 兼容性 / 回归路径
- 边界与异常数据路径

每条场景必须带：

- `scenario_id`
- `title`
- `objective`
- `preconditions`
- `linked_context_objects`
- `risk_reason`

写入：

- `QualityAssetPack.scenario_set_ref`

### 8.3 `quality.plan.generate`

输出：

- 验证优先级
- 环境要求
- 数据要求
- 手工/自动化划分
- 性能验证要求
- 审批点

写入：

- `QualityAssetPack.verification_plan_ref`

### 8.4 `quality.case.generate`

每条用例至少包含：

- `case_id`
- `scenario_id`
- `title`
- `steps`
- `expected_results`
- `test_data_hint`
- `assertion_type`
- `priority`

写入：

- `QualityAssetPack.case_set_ref`

### 8.5 `automation.generate`

默认策略：

1. 先筛选适合自动化的用例
2. 生成 test file skeleton、fixture/data hint、selector strategy、assertion plan
3. 统一收敛到项目测试模板

约束：

- 不直接从自然语言跳脚本，必须基于 case set
- selector 优先使用稳定属性和业务锚点
- 脚本必须带 `linked_case_ids`
- 输出必须符合 `automation-blueprint-output/v1`，Runner action 只允许 `goto / click / fill / press / assert_text / assert_visible / assert_url / wait_for`
- `automation.generate` 只生成和版本化资产，不得创建 `Run` 或执行浏览器
- 生成结果以 `QualityAssetPack.automation_blueprint` part 保存，`revision`、Prompt 版本、模型、输入上下文 hash 和结构化脚本必须可追溯
- `run.start` 必须从当前 automation part 选择脚本并显式提供目标 `base_url`，禁止客户端绕过已保存资产直接注入执行 steps
- 执行成功或失败后新增 automation part revision，保留生成内容并附加 `Run`、`ExecutionEvidence` 和可选 `FailureReport`

写入：

- `QualityAssetPack.automation_asset_ref`

### 8.6 `performance.generate`

仅在 `QualityProfile` 或 `coverage_scope` 存在性能关注点时生成。

写入：

- `QualityAssetPack.performance_asset_ref`

### 8.7 `quality.change-doc.generate`

信息来源：

- US 描述
- git delta
- scope/scenario/case 摘要
- 风险项
- 历史画像差异

写入：

- `QualityAssetPack.change_doc_ref`

### 8.8 `failure.analyze`

输入：

- logs
- trace
- screenshots
- DOM snapshot
- environment snapshot
- historical failure fingerprints

输出：

- `failure_kind`
- `suspected_causes`
- `confidence`
- `evidence_refs`
- `matching_historical_fingerprints`

V1 落地要求：

- 必须通过 `ToolInvocation` 调用，不能由 Run Detail 页面直接写失败结论。
- 必须生成正式 `FailureReport`，并关联 `run_id`、`us_id`、`failure_fingerprint`、`evidence_refs`。
- 如果 Run 只有原始 trace/log/screenshot ref，服务端必须先物化为 `ExecutionEvidence`，再由 `FailureReport.evidence_refs` 引用。

### 8.9 `healing.propose`

patch proposal 必须带：

- `target_files`
- `patch_summary`
- `risk_note`
- `retry_recommendation`

V1 落地要求：

- `healing.propose` 只生成候选修复/处置建议，不直接修改代码、不直接重跑高风险动作。
- 每次同一 `failure_fingerprint` 的自动自愈尝试必须累计 `healing_attempt_count`。
- 达到 `Max Healing Depth` 后，`FailureReport.status` 必须转为 `fallback_to_human`，Run 的 `healing_status` 也必须同步为 `fallback_to_human`。

命中以下条件必须 `fallback_to_human`：

- `Max Healing Depth`
- 重复 `failure_fingerprint`
- 风险超阈值

### 8.10 `release.advice.get`

输出：

- `readiness_status`
- `blocking_issues`
- `conditional_risks`
- `recommended_actions`

## 9. 结果落库规则

Skill 输出只能通过 `Domain Materialization Layer` 写入：

- `TaskContext`
- `QualityProfile`
- `QualityAssetPack`
- `AgentDecision`
- `Run` 相关补充对象

典型映射：

| Skill | 默认落点 |
| --- | --- |
| `impact.analyze` | `TaskContext.related_feature_refs`、风险对象 |
| `verification.plan` | `QualityProfile.verification_strategy` |
| `scenario.generate` | `QualityAssetPack.scenario_set_ref` |
| `case.generate` | `QualityAssetPack.case_set_ref` |
| `automation.generate` | `QualityAssetPack.automation_asset_ref` |
| `performance.generate` | `QualityAssetPack.performance_asset_ref` |
| `failure.analyze` | `FailureReport`、候选 `AgentDecision` |
| `healing.propose` | patch proposal 对象、候选 `AgentDecision` |

## 10. 多轮审核与 QualityAssetPack 协作

### 10.1 审核原则

- 审核是资产级，不是整包推倒重来
- `scope / scenario / case / automation / change_doc` 可分别批准或拒绝

### 10.2 局部重生成

必须指定：

- `target_asset_part`
- `reason`
- `preserve_refs`
- `regenerate_scope=replace|append|refine`

默认规则：

- 已批准部分默认冻结
- 只重生成被拒绝或过期部分

### 10.3 Revision 与并发

- `QualityAssetPack.current_revision` 每次关键资产变更递增
- 每个资产部分保留 `part_revision`
- 新 revision 不覆盖旧 revision，只更新 current pointer
- 多 Task 并行写同一 pack 时，采用：
  - `asset_part` 级乐观锁
  - `expected_revision`
  - 冲突进入 `pending_merge`

### 10.4 导出

首发支持：

- `markdown`
- `json`
- `csv/xlsx`（case set 与 summary 视图）

## 11. 版本演进与测试

### 11.1 版本演进

- Skill 必须版本化：
  - `skill_id`
  - `implementation_version`
  - `input_schema_version`
  - `output_schema_version`
- breaking 变更必须使用新 schema ref

### 11.2 测试要求

每个 Skill 至少要有：

- schema 校验测试
- deterministic 单元测试
- prompt snapshot 测试
- worker aggregation 测试
- result materialization 测试

## 12. 实现默认值

- 首发 Skill 默认使用 Python
- 所有模型调用统一走 [LLM 运行时设计](../agent/llm-runtime.md)
- 所有外部能力统一经 Tool Runtime 或 MCP adapter，不直接自行连外部系统
