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

### 4.2 主要工具

- `approval.request`
- `resolution.merge`
- `release.advice.get`
- `release.decision.submit`
- `baseline.promote`

## 5. 开发指导

- 当前阶段所有候选结论都由中心侧 `AgentDecision(status=provisional)` 提交，正式结论必须经 `Merge/Score + Approval Control` 形成。
- `pending_merge` 必须作为标准冲突状态出现在任务、执行和知识流中。
- 放行建议必须带阻断项、条件风险和推荐动作。

## 6. 验收标准

- 审批、冲突解决和放行建议可以在同一治理域中完成。
- `Candidate -> Version Shared -> Official Baseline` 晋级链路可追溯、可审批、可审计。
