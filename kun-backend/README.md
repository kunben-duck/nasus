# AutoTest Platform Backend (kun-backend, Java)

本目录是测试平台后端实现，负责认证授权、业务数据管理、AI 生成能力、执行调度和报告数据提供。

## 1. 技术基线

- Java 21
- Spring Boot 3.x
- Spring Security + JWT
- Spring Data JPA + Hibernate
- Spring AI（OpenAI Provider）
- Redis（缓存）
- RabbitMQ（执行异步任务）
- MySQL（生产）/ H2（开发）

## 2. Spring AI 方案

- AI 框架：Spring AI
- 当前 GA 版本基线：`1.1.2`
- 依赖位置：`/Users/uben/project/project/test-auto/test-auto-pro/kun-backend/pom.xml`
- 核心服务：`/Users/uben/project/project/test-auto/test-auto-pro/kun-backend/src/main/java/com/autotest/platform/ai/OpenAIService.java`
- 主要能力：
  - US 分析（结构化 JSON 输出）
  - 测试用例生成（数组 JSON 输出）
  - 脚本生成（多框架代码输出）

降级策略：

- 当未配置真实 API Key 时，后端返回 mock/fallback，保证页面链路可用。

## 3. 架构与分层

```text
Controller
  -> Service
    -> Repository
      -> Entity (MySQL)
  -> AI Service (Spring AI ChatClient)
  -> RabbitMQ Listener (execution async)
  -> WebSocket Push (execution status/timeline/screenshot)
```

目录：

```text
kun-backend/src/main/java/com/autotest/platform/
  ai/            AI 封装
  config/        全局配置、初始化、中间件配置
  controller/    REST API
  dto/           请求/响应模型
  entity/        领域实体
  listener/      MQ 消费者
  repository/    数据访问
  security/      JWT 与鉴权
  service/       业务逻辑
  websocket/     执行消息推送
```

## 4. 领域模型

- 用户与权限：`User`
  - 角色：`SYSTEM_ADMIN`、`TEST_MANAGER`、`TEST_DEVELOPER`、`QA`
  - 系统管理员可管理账号与角色权限。
- 需求域：`UserStory`
  - 支持 AI 分析与 AI 用例生成。
- 用例域：`TestCase` + `TestStep`
  - 支持 CRUD、步骤维护、关联 US。
- 脚本域：`TestScript`
  - 支持 CRUD、AI 生成并入库。
- 执行域：`TestExecution`
  - 支持创建/开始/完成/失败/取消。
  - 含 `ExecutionTimeline`、`ExecutionScreenshot`。

## 5. 核心 API 分组

认证：

- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /api/auth/me`

US：

- `GET /api/user-stories`
- `POST /api/user-stories`
- `PUT /api/user-stories/{id}`
- `DELETE /api/user-stories/{id}`
- `POST /api/user-stories/{id}/analyze`
- `POST /api/user-stories/{id}/generate-test-cases`

用例：

- `GET /api/test-cases`
- `POST /api/test-cases`
- `PUT /api/test-cases/{id}`
- `DELETE /api/test-cases/{id}`

脚本：

- `GET /api/test-scripts`
- `POST /api/test-scripts`
- `PUT /api/test-scripts/{id}`
- `DELETE /api/test-scripts/{id}`
- `POST /api/test-scripts/generate`

执行与报告：

- `GET /api/executions`
- `POST /api/executions`
- `POST /api/executions/{id}/start`
- `POST /api/executions/{id}/complete`
- `POST /api/executions/{id}/fail`
- `POST /api/executions/{id}/cancel`

系统：

- `GET /api/dashboard`
- `GET /api/users`（管理员）
- `POST /api/users`（管理员）
- `PUT /api/users/{id}`（管理员）
- `DELETE /api/users/{id}`（管理员）

## 6. 鉴权策略

- HTTP Header：`Authorization: Bearer <token>`
- 默认放行：
  - `/auth/**`
  - `/dashboard/**`（只读看板）
  - `/actuator/**`
- 账户管理接口需系统管理员角色。

## 7. 环境变量

- `SPRING_PROFILES_ACTIVE`：`prod`/`dev`
- `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_DB` / `MYSQL_USER` / `MYSQL_PASSWORD`
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD`
- `RABBITMQ_HOST` / `RABBITMQ_PORT` / `RABBITMQ_USER` / `RABBITMQ_PASS`
- `JWT_SECRET`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_TEMPERATURE`

## 8. 运行方式

推荐在项目根目录统一启动：

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro
docker compose up -d --build
```

仅后端本地调试：

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro/kun-backend
mvn spring-boot:run
```

## 9. 验证命令

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro
./scripts/health-check.sh --skip-up
```

## 10. 默认账号

- `admin / admin123`（系统管理员）
- `manager / manager123`（测试经理）
- `developer / developer123`（测试开发）
- `tester / tester123`（QA）
