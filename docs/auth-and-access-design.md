# Nasus 认证与授权设计

## 1. 文档定位

本文定义 Nasus 的认证、会话、Token、API 鉴权中间件、RBAC 与设备授权模型，作为后端身份体系和前端登录流程的实现依据。

优先级关系：

- 角色定义以 [docs/final-feature-spec.md](/Users/uben/project/project/Nasus/docs/final-feature-spec.md) 为准。
- 对象模型以 [docs/backend-domain-model.md](/Users/uben/project/project/Nasus/docs/backend-domain-model.md) 为准。
- 本文定义认证协议、授权决策链和持久化结构。

## 2. 设计目标

- Web、Desktop、API 三类入口共用同一身份体系。
- 鉴权与治理解耦：认证先确认“你是谁”，授权再判断“你能做什么”。
- 所有写操作都要同时通过 `identity + RBAC + policy + capability grant` 四层校验。
- Agent 可以代替用户发起工具调用，但不能拥有超出用户身份的权限。
- 设备权限不是角色，`Desktop Client` 只是一种受控执行端。

## 3. 身份主体

Nasus 定义 4 类身份主体：

- `Human User`
  - 平台管理员
  - 版本负责人
  - 质量负责人
  - 质量参与者
  - 审批者 / 发布负责人
- `Service Principal`
  - `api/orchestrator`
  - `workflow-service`
  - `worker-runtime`
  - `runner`
  - `sync-service`
- `Device`
  - 已注册 Desktop 设备
- `Delegated Agent Actor`
  - 代表当前登录用户发起动作的中心或边缘 Agent

约束：

- `Delegated Agent Actor` 没有独立权限集合，只能继承当前用户和当前空间的权限。
- `Device` 不独立拥有业务权限，只能在 `CapabilityGrant` 范围内执行本地动作。

## 4. 认证协议

### 4.1 用户认证

默认采用 `OIDC / OAuth 2.1`：

- `Web Portal`
  - Authorization Code + PKCE
- `Desktop Client`
  - Authorization Code + PKCE
  - 通过系统浏览器完成登录
- `CLI / API`
  - Device Code 或 Personal Access Token

首发要求：

- 支持企业 IdP 接入
- 支持最小本地开发模式
- 不自建用户名密码体系作为主认证方案

### 4.2 Token 策略

- `access token`
  - 默认有效期：15 分钟
  - 用于所有 API 调用
- `refresh token`
  - 默认有效期：30 天
  - 仅保存在受保护存储
  - 必须启用 rotation
- `service token`
  - 服务间短期 JWT
  - 默认有效期：5 分钟
- `device session token`
  - 绑定 `device_session_id`
  - 仅用于 Desktop 在线期和同步链路

强制规则：

- 所有 token 都必须带 `sub / aud / exp / iat / scope / session_id`
- refresh token 只能单次使用，rotation 后旧 token 立即失效
- Desktop 端 refresh token 必须保存到系统安全存储，不得保存在明文文件中

## 5. 授权模型

### 5.1 授权决策链

每次写操作必须按顺序经过：

1. `Identity Check`
2. `Session Check`
3. `ProjectMembership Check`
4. `RoleBinding / RBAC Check`
5. `PolicySnapshot Check`
6. `CapabilityGrant Check`（仅本地高权限动作）

任何一层失败都不得进入工具执行。

### 5.2 角色矩阵

| 角色 | Project Space | Version Space | Personal Workspace | Governance |
| --- | --- | --- | --- | --- |
| 平台管理员 | 创建项目、导入原料、配置策略 | 只读或按需参与 | 可查看 | 可管理正式基线 |
| 版本负责人 | 只读项目级正式知识 | 创建版本、导入版本输入、分配 US | 可查看自身任务 | 可发起版本级治理动作 |
| 质量负责人 | 只读项目级正式知识 | 审核 US 质量闭环、确认方案 | 可参与分析与复核 | 可发起放行建议 |
| 质量参与者 | 受限读取 | 读取被分配内容 | 处理被分配 US 与任务 | 不可直接做治理写入 |
| 审批者 / 发布负责人 | 可查看治理对象 | 审批放行和知识晋级 | 通常只读 | 可审批但不默认执行任务 |

### 5.3 RoleBinding 结构

最小表结构：

- `binding_id`
- `project_id`
- `version_id` 可空
- `session_id` 可空
- `user_id`
- `role`
- `scope_ref`
- `effective_policy_ref`
- `status`

规则：

- `Project` 级绑定控制长期治理权限
- `Version` 级绑定控制版本协作权限
- `Session` 级绑定控制局部会话参与权限
- 更细粒度的动作由 `PolicySnapshot` 与 `ToolDefinition` 决定，不在角色表里硬编码

## 6. API 鉴权中间件

所有 API 请求进入后统一经过 `AuthMiddleware` 与 `AccessMiddleware`：

### 6.1 `AuthMiddleware`

负责：

- 校验 token 签名
- 校验 `aud / exp / iss`
- 解析 `user_id / service_principal_id / device_session_id`
- 绑定 `access_session_id`
- 写入 `request_id`

### 6.2 `AccessMiddleware`

负责：

- 加载 `ProjectMembership`
- 加载 `RoleBinding`
- 对读请求做资源级可见性判断
- 对写请求做工具级授权判断
- 对本地动作附加 `CapabilityGrant` 检查

请求上下文至少要绑定：

- `actor_ref`
- `actor_type`
- `project_id`
- `version_id`
- `session_id`
- `role_set`
- `policy_snapshot_id`

## 7. Agent 与权限

- 主 Agent 发起动作时，`initiator_actor=agent`，但 `effective_actor` 仍然是当前用户。
- Agent 不允许绕过：
  - `RBAC`
  - `PolicySnapshot`
  - `CapabilityGrant`
  - `Approval Gate`
- 高风险工具即使由 Agent 发起，也必须进入 `waiting_confirmation` 或 `waiting_approval`。

## 8. Desktop 端权限

Desktop 端额外要求：

- 每个设备先注册为 `DeviceProfile`
- 在线工作前必须创建 `DeviceSession`
- 本地高权限动作必须绑定：
  - `user_id`
  - `device_id`
  - `project_id`
  - `task_id`
  - `capability_set`
- `CapabilityGrant` 默认短期有效，不做无限长期授权

## 9. 认证接口基线

首发至少提供：

- `GET /v1/auth/me`
- `POST /v1/auth/device-code`
- `POST /v1/auth/token`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`

服务间不走用户 token，走服务身份凭证。

## 10. 审计要求

以下动作必须写审计：

- 登录成功/失败
- refresh token rotation
- logout
- 角色绑定创建/修改/撤销
- capability grant 发放/撤销
- 高风险工具授权失败

## 11. 实现默认值

- 用户认证默认采用企业 OIDC
- 后端默认采用 JWT access token + rotating refresh token
- Web 与 Desktop 统一走 PKCE
- RBAC 是第一层授权，策略和设备能力是附加门槛
- 本文定义的身份对象和授权对象必须落到 PostgreSQL 中
