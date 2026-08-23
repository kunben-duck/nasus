# 模块设计：governance-release

## 1. 模块目标

`governance-release` 负责审批、冲突合并、放行建议和基线晋级，是正式结论的唯一出口。

## 2. 模块边界

负责：

- `Governance`
- `Approval Detail`
- `Release Readiness`
- `MergedResolution`

不负责：

- 原料接入
- 单个资产生成
- 原始执行动作

## 3. 前端组成

- `GovernancePage`
- `ApprovalDetailPage`
- `ReleaseReadinessPage`
- `DiffViewer`
- `ConflictPanel`

## 4. 后端组成

### 4.1 主要对象

- `ApprovalRecord`
- `AgentDecision`
- `MergedResolution`
- `CandidateKnowledge`
- `ReleaseDecision`

### 4.2 主要工具

- `approval.request`
- `approval.decide`
- `resolution.merge`
- `release.advice.get`
- `release.decision.submit`
- `baseline.promote`

## 5. 开发指导

- 当前阶段所有候选结论都由中心侧 `AgentDecision(status=provisional)` 提交，正式结论必须经 `Merge/Score + Approval Control` 形成。
- `pending_merge` 必须作为标准冲突状态出现在任务、执行和知识流中。
- 放行建议必须带阻断项、条件风险和推荐动作。
- `release.assess` 只能输出 `ReleaseReadiness`、质量指标和 release assessment 资产，不允许直接创建正式 `ReleaseDecision`。
- `ReleaseDecision` 只能由 `release.decision.submit` 在已批准 `ApprovalRecord` 通过 `approval_required` gate 后创建或更新。
- `ReleaseDecision.status` 固定为 `ready|conditional|blocked|needs_evidence`：
  - `ready`：分数、证据、阻断项和审批状态均满足放行条件。
  - `conditional`：存在非阻断风险、待合并项或非关键审批。
  - `blocked`：存在阻断项、失败证据或策略拒绝。
  - `needs_evidence`：缺少足以支持放行判断的执行证据。
- `ReleaseDecision` 必须包含 `score`、`rationale`、`evidence_refs` 和 `approval_ref`，后续 `baseline.promote` 只能消费该对象。
- `approval.request -> approval.decide -> release.decision.submit -> baseline.promote` 是 V1 最小治理闭环：
  - `approval.request` 只能创建等待审批对象。
  - `approval.decide` 必须经过用户确认。
  - `release.decision.submit` 和 `baseline.promote` 必须验证同项目下的已批准 `ApprovalRecord`。
- `resolution.merge` 必须接收 `base + left + right` 并执行后端 3-Way Merge；首次写入
  `MergedResolution`，只在全部字段冲突被显式裁决后进入 `ready_for_approval`。
- 对 `MergedResolution` 发起 `approval.request` 后必须写入 `approval_ref`；对应
  `approval.decide` 只能把该对象迁移为 `approved` 或 `rejected`，不得用普通
  `ApprovalRecord` 伪装合并事实。
- `pending_merge` 计数只能随所属项目和版本的单个 `MergedResolution` 状态迁移增减，
  禁止扫描并修改其他项目或版本的 readiness。

### 5.1 ReleaseReadiness 证据评分

`ReleaseReadiness` 必须由持久化事实确定性计算，禁止使用 LLM 直接给出分数。V1 评分总分 100：

- 执行证据 35 分：最近一次执行通过 20 分、历史通过率 10 分、证据类型完整度 5 分。
- 质量资产 25 分：`scenario_set`、`case_set`、`automation_blueprint` 按已批准或已完成比例计分。
- 系统上下文 20 分：TaskContext readiness 7 分、TaskContext confidence 5 分、QualityProfile coverage 5 分、QualityProfile confidence 3 分。
- 治理状态 20 分：未关闭 FailureReport、待审批和 `pending_merge` 分别扣分。
- fallback 生成和缺失上下文属于额外负分，并必须在 `score_breakdown` 中可解释。

以下硬闸口优先于加权分数：

- 存在未关闭 FailureReport 时最高 59 分；进入 `fallback_to_human` 时最高 39 分。
- 缺少必需质量资产、通过的自动化执行、执行证据或存在 `pending_merge` 时最高 69 分。
- TaskContext 不是 `ready` 时最高 59 分。
- 存在待审批项时最高 79 分。
- 存在 fallback 生成资产时最高 84 分。

只有无阻断项且最终分数不低于 80，状态才能进入 `Ready for release review`。该状态仍不是正式放行，必须继续进入 `release.decision.submit`。

## 6. 验收标准

- 审批、冲突解决和放行建议可以在同一治理域中完成。
- `Candidate -> Version Shared -> Official Baseline` 晋级链路可追溯、可审批、可审计。
- 所有发布决策提交和基线提升都能追溯到 `ToolInvocation -> ApprovalRecord -> ReleaseDecision -> Baseline`。
- `ReleaseReadiness.score` 等于 `score_breakdown` 各项之和，且 `evidence_summary` 能追溯到 Run、ExecutionEvidence、QualityAssetPack、TaskContext、QualityProfile 和 ApprovalRecord。
