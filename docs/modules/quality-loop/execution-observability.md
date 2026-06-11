# 模块设计：execution-observability

## 1. 模块目标

`execution-observability` 负责执行、证据、失败归因和修复建议，是质量闭环的执行与反馈面。

## 2. 模块边界

负责：

- `Runs`
- `Run Detail`
- `Evidence`
- `Failure Analysis`
- `Healing`

不负责：

- 版本创建和 US 分配
- 审批与正式放行裁决

## 3. 前端组成

- `RunsPage`
- `RunDetailPage`
- `EvidenceTimeline`
- `FailureTimelineCard`
- `HealingProposalPanel`

## 4. 后端组成

### 4.1 主要对象

- `Run`
- `ExecutionEvidence`
- `FailureReport`
- `HealingProposal`

### 4.2 主要工具

- `run.start`
- `run.retry`
- `failure.analyze`
- `healing.propose`
- `query.run.status`

## 5. 开发指导

- `Run` 是唯一正式执行对象，当前阶段固定以 `execution_channel=web_runner` 交付。
- `Run Detail` 的证据、失败、healing 不能只靠文本拼装，必须消费统一对象模型。
- 所有执行产物统一落 MinIO，并以 `evidence_ref` 回链。

## 6. 验收标准

- 用户可以查看运行列表、单次运行详情、证据时间线、失败分析和修复建议。
- Web runner 的证据、失败归因和修复建议必须形成统一的可审计对象链路。
