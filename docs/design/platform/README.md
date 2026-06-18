# 平台能力总览

## 1. 模块目标

平台能力提供横切的技术底座，是所有产品模块共同依赖的基础设施。

## 2. 边界

负责：

- 认证与授权
- Model provider 配置
- MCP 外部工具接入
- Audit / Observability / Migration / 配置管理

## 3. 前端组成

- `Settings`
- Provider 配置
  - `Chat LLM`
  - `Embedding`
  - `Rerank`
- 主题 / 语言切换
- MCP / Connector 管理入口

## 4. 后端组成

### 4.1 主要对象

- `UserIdentity`
- `ProjectMembership`
- `RoleBinding`
- `PolicySnapshot`
- `MCPServerDefinition`
- `AuditEvent`

### 4.2 子文档

- [认证与授权设计](./auth-and-access-design.md)
- [MCP 集成设计](./mcp-integration-design.md)
- [LLM 运行时设计](../agent/llm-runtime.md)
- [后端运维与测试基线](../backend/ops-and-test-baseline.md)

## 5. 开发指导

- API key、provider 配置必须持久化并加密存储。
- 模型配置必须拆成 `chat / embedding / rerank` 三条独立 route；每条 route 都要支持 `system_default` 和 `custom`。
- `chat` route 服务主会话、Agent Loop 和质量生成；`embedding` route 服务系统画像向量化；`rerank` route 服务 hybrid retrieval 候选重排。
- 设置页必须显示每条 route 的 `live/fallback` 状态，并提供独立的保存和连接测试动作。
- 认证、RBAC、policy gate 不能晚于主业务实现补；它们是 agent-first 的治理前提。
- 统一错误响应体、统一配置入口、统一审计链必须先行落地。

## 6. 验收标准

- 用户身份、角色、三路模型配置和审计链可稳定工作。
- 所有业务模块都通过同一套认证、策略和观测基线运行。
