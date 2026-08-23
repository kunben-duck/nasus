# Nasus 认证与授权设计

## 1. 文档定位

本文定义 Nasus 的认证、会话、Token、API 鉴权中间件与 RBAC 模型，作为后端身份体系和前端登录流程的实现依据。

优先级关系：

- 角色定义以 [最终特性说明书](../../final-feature-spec.md) 为准。
- 对象模型以 [../backend/domain-model.md](../backend/domain-model.md) 为准。
- 本文定义认证协议、授权决策链和持久化结构。

## 2. 设计目标

- Web、CLI/API 入口共用同一身份体系。
- 鉴权与治理解耦：认证先确认“你是谁”，授权再判断“你能做什么”。
- 所有写操作都要同时通过 `identity + RBAC + policy` 三层校验。
- Agent 可以代替用户发起工具调用，但不能拥有超出用户身份的权限。

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
- `Delegated Agent Actor`
  - 代表当前登录用户发起动作的中心或边缘 Agent

约束：

- `Delegated Agent Actor` 没有独立权限集合，只能继承当前用户和当前空间的权限。

## 4. 认证协议

### 4.1 用户认证

默认采用 `OIDC / OAuth 2.1`：

- `Web Portal`
  - Authorization Code + PKCE
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
强制规则：

- 所有 token 都必须带 `sub / aud / exp / iat / scope / session_id`
- refresh token 只能单次使用，rotation 后旧 token 立即失效

### 4.3 V1 生产门禁过渡方案

完整企业认证仍以 `OIDC / OAuth 2.1 + RBAC + PolicySnapshot` 为目标；在该能力完全落地前，V1 允许使用一个受限的 Bearer Token 边界作为生产最低门禁。

当前 V1 同时提供 PostgreSQL 持久化的本地账号与随机访问会话，供首个 Web
Portal 生产基线和私有部署使用。它不是未来企业 IdP 的替代品，但必须满足：

- 密码只保存 PBKDF2 派生摘要，不保存明文。
- 访问 token 只保存 SHA-256 摘要，客户端仅在创建会话时获得原 token。
- 登录时同时校验账号状态和会话状态；停用账号立即撤销全部活动会话。
- 普通用户只能查看和撤销自己的会话；平台管理员可管理全部账号和会话。
- 自注册账号默认全局角色为 `qa_lead`，创建项目后获得该项目的 `project_admin` 绑定，不自动获得 `platform_admin`。
- 平台管理员不能撤销自己的当前平台管理权限，也不能移除数据库中的最后一个活动平台管理员。

实现要求：

- `NASUS_AUTH_MODE=dev|disabled|off` 仅允许本地开发，使用固定开发用户。
- `NASUS_AUTH_MODE=required|prod|production` 必须要求所有非公开 API 携带 `Authorization: Bearer <token>`。
- `NASUS_AUTH_BEARER_TOKEN` 必须由部署环境注入，禁止提交到代码仓库。
- `/healthz` 和 `OPTIONS` 预检请求保持公开。
- `GET /v1/conversations/{id}/events` 等浏览器 `EventSource` 链路可临时使用 `?access_token=`，因为原生 EventSource 不能设置自定义 header。
- Query token 只作为 V1 兼容方案；正式企业认证落地后应迁移到受保护 cookie、短期 SSE token 或支持 header 的 streaming transport。

限制：

- Bearer Token 门禁只能证明 API 不是裸奔，不能替代角色授权。
- V1 必须至少在 `ToolInvocationRuntime` 内执行工具级 RBAC；写操作不能只依赖前端隐藏按钮。
- `RoleBinding`、`PolicySnapshot` 和企业 OIDC 仍是正式企业版目标，V1 工具级 RBAC 是最低可生产安全边界。
- 生产部署若未配置 token，服务必须返回 `auth_not_configured`，不能静默降级为开发用户。

## 5. 授权模型

### 5.1 授权决策链

每次写操作必须按顺序经过：

1. `Identity Check`
2. `Session Check`
3. `ProjectMembership Check`
4. `RoleBinding / RBAC Check`
5. `PolicySnapshot Check`
任何一层失败都不得进入工具执行。

### 5.2 角色矩阵

| 角色 | Project Space | Version Space | Personal Workspace | Governance |
| --- | --- | --- | --- | --- |
| 平台管理员 | 创建项目、导入原料、配置策略 | 只读或按需参与 | 可查看 | 可管理正式基线 |
| 版本负责人 | 只读项目级正式知识 | 创建版本、导入版本输入、分配 US | 可查看自身任务 | 可发起版本级治理动作 |
| 质量负责人 | 只读项目级正式知识 | 审核 US 质量闭环、确认方案 | 可参与分析与复核 | 可发起放行建议 |
| 质量参与者 | 受限读取 | 读取被分配内容 | 处理被分配 US 与任务 | 不可直接做治理写入 |
| 审批者 / 发布负责人 | 可查看治理对象 | 审批放行和知识晋级 | 通常只读 | 可审批但不默认执行任务 |

### 5.2.1 V1 工具级 RBAC 最小矩阵

V1 在完整 `RoleBinding` 落库前，先使用认证主体上的 `role` 执行工具级授权。该检查必须发生在 `ToolInvocationRuntime` 内，并且早于 confirmation / approval gate 和具体 handler 执行。

| 工具类型 / 风险 | 最小角色 | 说明 |
| --- | --- | --- |
| `query` 工具、低风险只读工具 | `viewer` | 所有认证用户可查询自己可见范围内的状态 |
| `analysis` / `execution` / `us` / `sync` | `tester` | 可生成质量资产、执行 run、分析失败，但不能直接做治理写入 |
| `project` / `version` 写动作 | `qa_lead` | 可创建项目、接入原料、创建版本和导入 US |
| `governance` 或 `high` 风险工具 | `qa_lead` | 仍必须继续经过 `user_confirm` 或 `approval_required` gate |
| `critical`、`release.decision.submit`、`baseline.promote` | `project_admin` | 正式放行决策和官方基线回写不得由普通参与者直接触发 |
| 全局平台动作 | `platform_admin` | 拥有所有 V1 工具权限 |

授权失败要求：

- `ToolInvocation.status=failed`
- `ToolResult.followup_reason=authorization_denied`
- 记录 `tool.invocation.authorization_denied` 审计事件
- 不得进入 `tool.invocation.executing`
- 不得进入 confirmation / approval gate，避免把无权限动作伪装成“待确认”

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
- 项目成员列表只返回 `version_id/session_id` 均为空的项目级活动绑定。
- 项目角色只能是 `viewer / tester / qa_lead / project_admin`，全局 `platform_admin` 不写入项目角色字段。
- 项目管理员可以变更成员角色；撤销或降级最后一个项目管理员必须失败，除非动作由全局平台管理员执行。

## 6. API 鉴权中间件

所有 API 请求进入后统一经过 `AuthMiddleware` 与 `AccessMiddleware`：

### 6.1 `AuthMiddleware`

负责：

- 校验 token 签名
- 校验 `aud / exp / iss`
- 解析 `user_id / service_principal_id`
- 绑定 `access_session_id`
- 写入 `request_id`

V1 Bearer Token 模式下，`AuthMiddleware` 至少要：

- 在 required 模式拒绝缺失或错误 token 的请求。
- 把通过验证的主体写入 `request.state.user`。
- 对前端请求和 SSE query token 使用同一套 token 校验逻辑。

### 6.2 `AccessMiddleware`

负责：

- 加载 `ProjectMembership`
- 加载 `RoleBinding`
- 对读请求做资源级可见性判断
- 对写请求做工具级授权判断

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
  - `Approval Gate`
- 高风险工具即使由 Agent 发起，也必须进入 `waiting_confirmation` 或 `waiting_approval`。

## 8. 认证接口基线

首发至少提供：

- `GET /v1/auth/me`
- `POST /v1/auth/device-code`
- `POST /v1/auth/token`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`

服务间不走用户 token，走服务身份凭证。

## 9. 审计要求

以下动作必须写审计：

- 登录成功/失败
- refresh token rotation
- logout
- 角色绑定创建/修改/撤销
- 高风险工具授权失败

## 11. 实现默认值

- 用户认证默认采用企业 OIDC
- 后端默认采用 JWT access token + rotating refresh token
- Web 统一走 PKCE
- RBAC 是第一层授权，策略是附加门槛
- 本文定义的身份对象和授权对象必须落到 PostgreSQL 中
- V1 过渡期允许 Bearer Token 门禁，但生产环境必须显式启用 `NASUS_AUTH_MODE=required` 并配置强 token
