# Nasus Skill 实现模式设计

## 1. 文档定位

本文定义 Skill 的代码实现模式、输入输出 envelope、与 LLM/Tool/Worker 的关系、版本演进和产物落库规则。

Skill 是 Agent 的“手”。Tool 是产品级动作，Skill 是动作背后的内部能力组件，Worker 是 Skill 的执行单元。

## 2. Skill 分类

首发 Skill 分为 4 类：

- `deterministic`
  - 纯规则、纯聚合、纯格式转换
- `llm_assisted`
  - 依赖 LLM 产出结构化结果
- `hybrid`
  - 先规则提取，再用 LLM 生成/归纳
- `edge_local`
  - 仅在 Desktop / Local Capability Host 执行

## 3. Skill 清单与归属

首发关键 Skill：

- `baseline.build`
- `context.enrich`
- `impact.analyze`
- `verification.plan`
- `scenario.generate`
- `case.generate`
- `automation.generate`
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

- 每个 Skill 必须有固定 `input_schema_ref / output_schema_ref`。
- Skill 不直接写正式事实对象；通过 `Domain Materialization Layer` 落库。
- Skill 输出必须可追溯到 `tool_invocation_id`。

## 5. 输入输出协议

### 5.1 SkillInvocationRequest

最小字段：

- `tool_invocation_id`
- `skill_id`
- `task_context_id`
- `quality_profile_id`
- `input_payload`
- `input_evidence_refs`
- `policy_snapshot_id`
- `resume_payload` 可空

### 5.2 SkillInvocationResult

最小字段：

- `status=succeeded|failed|partial`
- `summary`
- `structured_output`
- `object_refs`
- `evidence_refs`
- `worker_jobs`
- `retryable`
- `error_code`

## 6. Skill 与 LLM 的关系

### 6.1 何时调用 LLM

以下场景优先 `llm_assisted / hybrid`：

- 场景生成
- 用例生成
- 失败日志归纳
- 修复建议
- 放行建议摘要

以下场景优先 `deterministic`：

- 风险规则聚合
- ContextObject 查询与拼装
- evidence 归档
- 结果 schema 校验
- patch/diff 结构化

### 6.2 Prompt 约束

每个使用 LLM 的 Skill 都必须绑定：

- `prompt_id`
- `prompt_version`
- `input_schema_ref`
- `output_schema_ref`
- `fallback_model_class`

## 7. Skill 编排模式

### 7.1 Tool -> Skill

- 一个 Tool 可映射一个或多个 Skill。
- Tool Runtime 只负责决定“是否调用该 Tool”；进入 Tool 后由 `Agent Graph Runtime` 路由 Skill。

### 7.2 Skill -> Worker

典型模式：

- `scenario.generate`
  - `context-enrichment worker`
  - `risk worker`
  - `scenario drafting worker`
- `failure.analyze`
  - `log parser worker`
  - `trace worker`
  - `screenshot summarizer worker`

## 8. 结果落库规则

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
| `failure.analyze` | `FailureReport`、候选 `AgentDecision` |
| `healing.propose` | patch proposal 对象、候选 `AgentDecision` |

## 9. 版本演进

- Skill 自身必须版本化：
  - `skill_id`
  - `implementation_version`
  - `input_schema_version`
  - `output_schema_version`
- breaking output 变更必须采用新 schema ref，不允许覆盖旧含义。
- 同一 Tool 下允许按 `policy/profile/project` 选择不同 Skill 版本，但输出契约必须兼容。

## 10. 测试要求

每个 Skill 至少要有：

- schema 校验测试
- deterministic 单元测试
- prompt snapshot 测试
- worker aggregation 测试
- result materialization 测试

## 11. 实现默认值

- 首发 Skill 默认使用 Python 实现。
- 需要 LLM 的 Skill 统一走 `LLM Gateway`。
- 需要外部能力的 Skill 统一经 Tool Runtime 或 MCP adapter，不直接自行连外部系统。
