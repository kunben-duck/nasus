# Nasus 后端执行与治理

## 1. 执行模型

当前阶段范围说明：

- 当前阶段以中心端 `Agent Loop Runtime` 与 Web Runner 为主。
- 本文仅定义当前 Web-first 阶段的执行、失败、自愈、审批与基线治理规则。

### 1.1 Web Runner

- 接收 `Run` 创建请求和执行配置
- 执行 `automation.generate` 产出的 Playwright 资产
- 产出：
  - `ExecutionEvidence`
  - `trace`
  - `screenshots`
  - `logs`
  - `environment snapshot`
- 不负责推理和正式结论写入

### 1.2 ExecutionEvidence

必须包含：

- `evidence_id`
- `run_id`
- `kind`
- `storage_ref`
- `hash`
- `captured_at`
- `source_channel`
- `tool_invocation_id`

## 2. Failure / Healing / Release 链路

- `Run` 完成后，Failure Analysis 消费统一 evidence。
- Failure Analysis 输出：
  - `failure_kind`
  - `failure_summary`
  - `suspected_causes`
  - `evidence_refs`
- Healing 输出：
  - `patch proposal`
  - `retry recommendation`
  - `confidence`
- Release Advice 只产生候选结论，正式放行仍需经过 merge/approval。

### 2.1 Failure / Healing 防护规则

- 默认引入 `Max Healing Depth`
  - 首发建议默认值：每个 `Task` 最多 `2` 次自动自愈闭环
  - 超过阈值后，系统必须切换为 `fallback_to_human`
- 默认引入 `Failure Fingerprint`
  - 由 `failure_kind + failing_step + locator/assertion/env signature + key stack digest` 组成
  - 相同 `failure_fingerprint` 在冷却窗口内不得重复触发同类自动修复
- 默认引入 `Healing Cooldown`
  - 同一 `Run` 或同一 `Task` 的同类失败，在 `cooldown_until` 之前只能人工确认后重试
- 默认引入 `Rate Limiting`
  - 限制单位时间内的 `healing.propose` 次数
  - 限制同一会话对同一任务的自动修复预算
- 满足以下任一条件时，必须停止自动链路并转人工：
  - `healing_depth >= max_healing_depth`
  - 连续出现相同 `failure_fingerprint`
  - 最近一次 patch 导致失败类型升级
  - 策略判定风险超阈值
  - 用户显式关闭自动修复

## 3. 治理与审批

### 3.1 高风险动作 gate 规则

| 风险级别 | 默认 gate |
| --- | --- |
| `low` | 无确认 |
| `medium` | 可策略放行，必要时用户确认 |
| `high` | 用户确认 |
| `critical` | 审批 + 用户确认 |

### 3.2 Candidate 晋级路径

固定链路：

`Candidate Knowledge -> Version Shared -> Official Baseline`

规则：

- `Version Shared` 需版本级审批
- `Official Baseline` 需版本收口后正式审批
- 所有晋级动作都要写审计事件

### 3.3 正式结论规则

- `AgentDecision` 不是正式结论
- `ToolResult` 不是正式结论
- `MergedResolution` 才是正式结论载体
- 审批完成后才能推进：
  - 任务完成
  - 放行通过
  - 基线写回

## 4. 策略约束

### 4.1 PolicySnapshot

每次高风险工具调用都必须绑定：

- `policy_snapshot_id`
- `policy_version`
- `evaluated_rules`
- `decision`

## 5. 审计要求

以下动作必须写审计：

- 会话触发工具
- 高风险动作进入 gate
- 冲突合并
- 审批完成
- 基线写回
