# Nasus 后端执行、同步与治理

## 1. 执行模型

首发范围说明：

- 首发 Demo 以中心端 `Agent Loop Runtime` 为主。
- Desktop 端首发只承接：
  - 本地受控动作执行
  - 本地产物采集
  - 同步补传
  - 本地确认与授权
- Desktop 独立的长生命周期 Agent Loop 不作为首发要求，归入 `Phase 2+` 演进范围。

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

### 1.2 Desktop Local Capability Host

- 接收经授权的本地工具动作
- 支持：
  - 文件/目录
  - 浏览器
  - 桌面应用
  - 剪贴板
  - 下载目录
  - 本地脚本
- 产出统一 canonical `Run(execution_channel=desktop_local)` 和 `LocalRunArtifact`

### 1.3 本地执行安全沙箱

本地执行不允许把 Agent 生成内容直接交给宿主机任意 shell。默认采用三层隔离：

- `Structured Capability Adapters`
  - 文件创建、目录管理、浏览器控制、桌面应用控制优先走结构化适配器
  - 适配器只暴露显式参数，不接受自由拼接 shell 命令
- `Sandboxed Script Runtime`
  - 默认脚本运行时采用 `Deno` 或等价权限沙箱
  - 脚本默认只允许访问 task-scoped 临时目录
  - 默认关闭网络、环境变量、任意子进程与全盘文件访问
  - 只有经 `CapabilityGrant + PolicySnapshot` 明确授权后，才可按最小范围追加权限
- `Isolated Native Executor`
  - 对必须执行 Python/系统命令/原生程序的场景，不直接在主桌面进程内执行
  - 首发要求使用隔离 sidecar 或一次性子进程执行，并限制工作目录、参数模板和可执行白名单
  - 任意自由 shell/任意脚本执行默认关闭，不作为首发能力

强制规则：

- 主 UI 进程与 `Local Capability Host` 分离
- 所有本地执行都必须带 `task_id`、`tool_invocation_id`、`policy_snapshot_id`
- 所有写文件动作都必须限制到策略允许的目录范围
- 所有执行产物都必须生成 `LocalRunArtifact` 和审计记录

### 1.4 ExecutionEvidence

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

## 3. 本地同步协议

### 3.1 SyncEnvelope

最小字段：

- `sync_event_id`
- `device_session_id`
- `cursor`
- `payload_kind`
- `object_refs`
- `evidence_refs`
- `artifact_refs`
- `conflict_markers`
- `policy_snapshot_id`

### 3.2 同步规则

- 离线允许缓存 `ToolInvocation` 结果、`Run` 进度、`ExecutionEvidence`、`LocalRunArtifact`
- 在线后按 `cursor` 顺序补传
- 幂等去重基于：
  - `sync_event_id`
  - `artifact hash`
  - `tool_invocation_id`
- 本地私有数据默认不上送
- 只有显式策略或用户动作允许的内容才可同步到中心端
- 同步回放不得绕过本地沙箱和中心端策略校验；补传只回放结果与证据，不重放原始高风险执行动作。

### 3.3 远程任务与本地确认

- 中心端可以下发本地工具动作
- 但执行前必须满足其一：
  - `user_confirm`
  - `approval_required` 已完成
  - `policy_only` 且策略允许
- 未授权动作不得执行

## 4. 治理与审批

### 4.1 高风险动作 gate 规则

| 风险级别 | 默认 gate |
| --- | --- |
| `low` | 无确认 |
| `medium` | 可策略放行，必要时用户确认 |
| `high` | 用户确认 |
| `critical` | 审批 + 用户确认 |

### 4.2 Candidate 晋级路径

固定链路：

`Candidate Knowledge -> Version Shared -> Official Baseline`

规则：

- `Version Shared` 需版本级审批
- `Official Baseline` 需版本收口后正式审批
- 所有晋级动作都要写审计事件

### 4.3 正式结论规则

- `AgentDecision` 不是正式结论
- `ToolResult` 不是正式结论
- `MergedResolution` 才是正式结论载体
- 审批完成后才能推进：
  - 任务完成
  - 放行通过
  - 基线写回

## 5. 策略与能力授权

### 5.1 CapabilityGrant

最小授权上下文：

- `user`
- `device`
- `project`
- `task`

不使用全局无限授权。

### 5.2 PolicySnapshot

每次高风险工具调用都必须绑定：

- `policy_snapshot_id`
- `policy_version`
- `evaluated_rules`
- `decision`

## 6. 审计要求

以下动作必须写审计：

- 会话触发工具
- 高风险动作进入 gate
- 本地能力授权与撤销
- 本地动作执行
- 同步补传
- 冲突合并
- 审批完成
- 基线写回
