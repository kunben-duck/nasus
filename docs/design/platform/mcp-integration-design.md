# Nasus MCP 集成设计

## 1. 文档定位

本文定义 Nasus 如何集成外部 `MCP`（Model Context Protocol）Server，使 Agent 可以像 Claude Code/Codex 一样调用外部工具与资源，同时仍然受 Nasus 自身的 Tool、Policy、Approval 和 Audit 体系约束。

## 2. 设计原则

- MCP 是外部能力协议，不替代 Nasus 内部 `Tool/Skill/Worker` 体系。
- Agent 调用 MCP 能力时，仍必须经过 Nasus 的 `ToolInvocation Runtime`。
- 外部能力可以被“投影”为 Nasus Tool，但不能绕过 gate、审计和证据落点。
- 资源访问与工具执行分开治理。

## 3. 核心组件

- `MCP Server Registry`
  - 配置和管理外部 MCP Server
- `MCP Transport Adapter`
  - 负责 stdio / http / websocket 等传输
- `MCP Capability Proxy`
  - 把外部 MCP tool/resource/prompt 投影到 Nasus 内部能力模型
- `MCP Policy Adapter`
  - 把 MCP 调用接入 `PolicySnapshot / Approval Gate`
- `MCP Resource Cache`
  - 缓存高频只读资源，避免重复拉取

## 4. MCP 与 Nasus Tool 的关系

首发采用两种模式：

### 4.1 Domain-Wrapped 模式

外部 MCP 能力由 Nasus 自己的 Tool 包装后暴露。

示例：

- `run.start` 内部可调用 Playwright MCP
- `system-image.inspect` 内部可调用 Git/File MCP

优点：

- 产品语义稳定
- 易于治理

### 4.2 Registered External Tool 模式

允许把已批准的 MCP tool 投影为特殊 `ToolDefinition`：

- `tool_origin=mcp`
- `tool_id=mcp.<server_name>.<tool_name>`

限制：

- 仅允许出现在高级工具面板或策略允许的会话中
- 默认不可见，需项目/管理员开启

## 5. MCP Resource 访问

Agent 可通过 MCP 访问：

- 文件系统资源
- Git 资源
- 浏览器资源
- 其他外部上下文资源

但访问方式仍需先通过 Nasus：

1. `Conversation Orchestrator` 规划需要外部资源
2. 生成对应 `ToolInvocation`
3. Tool Runtime 检查是否需要 MCP
4. `MCP Capability Proxy` 调用外部 resource/tool
5. 结果标准化后回写 `ToolResult / Evidence`

## 6. MCP Prompt 集成

首发不把 MCP Prompt 当成主执行面。

规则：

- MCP prompt 仅作为补充上下文模板使用
- 不能绕过 Nasus 自己的 Prompt Registry
- 若 MCP prompt 被采用，必须记录：
  - `mcp_server`
  - `prompt_name`
  - `prompt_version` 可空

## 7. Server 配置管理

建议对象：

- `MCPServerDefinition`
- `MCPServerBinding`
- `MCPServerHealth`

每个 server 至少保存：

- `server_id`
- `name`
- `transport_kind`
- `endpoint_or_command_ref`
- `credential_ref`
- `status`
- `allowed_tools`
- `allowed_resources`
- `policy_profile_id`

## 8. 安全边界

### 8.1 基本规则

- MCP 调用不等于自动可信。
- 所有 MCP tool/resource 都必须受策略限制。
- 高风险 MCP tool 必须进入确认或审批。

### 8.2 当前阶段约束

- 当前阶段只支持中心端 MCP 调用
- 所有 MCP 调用统一受中心端 `PolicySnapshot` 约束

### 8.3 审计

每次 MCP 调用都必须写：

- `tool_invocation_id`
- `mcp_server_id`
- `mcp_tool_name` 或 `resource_uri`
- `actor_ref`
- `policy_snapshot_id`
- `result_summary`

## 9. 首发建议

- 先接入 Playwright / browser 类 MCP
- 其次接文件/Git 类 MCP
- 其它外部 server 通过 allowlist 方式逐步开放

## 10. 实现默认值

- MCP 不单独成为业务主入口。
- 主入口仍是 `Conversation + ToolInvocation`。
- 首发优先使用 Domain-Wrapped 模式，少量已批准工具再投影为 `mcp.*` 外部工具。
