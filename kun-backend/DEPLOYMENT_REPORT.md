# AutoTest Platform - Java Spring Boot 后端部署报告

## 项目概述

已成功创建企业级自动化测试平台后端服务，基于 **Spring Boot 3.x** 技术栈。

## 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | Spring Boot 3.2.5 (Java 17) |
| 数据库 | H2 (开发) / MySQL 8.0 / PostgreSQL (生产) |
| ORM | Spring Data JPA (Hibernate) |
| 缓存 | Redis |
| 消息队列 | RabbitMQ |
| AI服务 | OpenAI API |
| 认证 | JWT (JSON Web Token) |
| 实时通信 | WebSocket (STOMP) |
| 构建工具 | Maven |

## 项目结构

```
backend-java/
├── src/main/java/com/autotest/platform/
│   ├── AutoTestPlatformApplication.java    # 主应用入口
│   ├── ai/
│   │   └── OpenAIService.java              # AI服务集成
│   ├── config/
│   │   ├── DataInitializer.java            # 数据初始化
│   │   ├── GlobalExceptionHandler.java     # 全局异常处理
│   │   ├── RabbitMQConfig.java             # RabbitMQ配置
│   │   ├── RedisConfig.java                # Redis配置
│   │   └── WebSocketConfig.java            # WebSocket配置
│   ├── controller/
│   │   ├── AuthController.java             # 认证接口
│   │   ├── DashboardController.java        # 仪表盘接口
│   │   ├── TestCaseController.java         # 测试用例接口
│   │   ├── TestExecutionController.java    # 测试执行接口
│   │   ├── TestScriptController.java       # 测试脚本接口
│   │   ├── UserController.java             # 用户管理接口
│   │   └── UserStoryController.java        # US需求接口
│   ├── dto/                                 # 数据传输对象
│   │   ├── ApiResponse.java
│   │   ├── DashboardDTO.java
│   │   ├── LoginRequest.java
│   │   ├── LoginResponse.java
│   │   ├── PageResponse.java
│   │   ├── TestCaseDTO.java
│   │   ├── TestExecutionDTO.java
│   │   ├── TestScriptDTO.java
│   │   ├── UserDTO.java
│   │   └── UserStoryDTO.java
│   ├── entity/                              # JPA实体类
│   │   ├── ExecutionScreenshot.java
│   │   ├── ExecutionTimeline.java
│   │   ├── TestCase.java
│   │   ├── TestExecution.java
│   │   ├── TestScript.java
│   │   ├── TestStep.java
│   │   ├── User.java
│   │   ├── UserStory.java
│   │   └── ValidationPoint.java
│   ├── listener/
│   │   └── TestExecutionListener.java       # 消息队列监听器
│   ├── repository/                          # 数据访问层
│   │   ├── TestCaseRepository.java
│   │   ├── TestExecutionRepository.java
│   │   ├── TestScriptRepository.java
│   │   ├── UserRepository.java
│   │   └── UserStoryRepository.java
│   ├── security/                            # 安全配置
│   │   ├── CustomUserDetailsService.java
│   │   ├── JwtAuthenticationFilter.java
│   │   ├── JwtTokenProvider.java
│   │   └── SecurityConfig.java
│   ├── service/                             # 业务逻辑层
│   │   ├── DashboardService.java
│   │   ├── TestCaseService.java
│   │   ├── TestExecutionService.java
│   │   ├── TestScriptService.java
│   │   ├── UserService.java
│   │   └── UserStoryService.java
│   └── websocket/
│       └── ExecutionWebSocketController.java # WebSocket控制器
├── src/main/resources/
│   └── application.yml                      # 应用配置
├── Dockerfile                               # Docker构建文件
├── docker-compose.yml                       # Docker Compose配置
├── .dockerignore                            # Docker忽略文件
├── README.md                                # 项目说明
├── start.sh                                 # 启动脚本
├── verify.sh                                # 验证脚本
└── pom.xml                                  # Maven配置
```

## API 端点列表

### 公共接口 (无需认证)

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/actuator/health | 健康检查 |
| POST | /api/auth/login | 用户登录 |
| POST | /api/auth/register | 用户注册 |
| POST | /api/auth/refresh | 刷新Token |
| GET | /api/dashboard | 仪表盘数据 |
| GET | /api/dashboard/statistics | 统计数据 |
| GET | /api/dashboard/charts | 图表数据 |
| GET | /api/dashboard/recent-activities | 最近活动 |
| GET | /api/dashboard/system-status | 系统状态 |

### 认证接口 (需要JWT Token)

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/auth/me | 获取当前用户 |
| GET | /api/users | 获取所有用户 |
| GET | /api/users/{id} | 获取用户详情 |
| GET | /api/users/search | 搜索用户 |
| PUT | /api/users/{id} | 更新用户 |
| DELETE | /api/users/{id} | 删除用户 |

### US需求管理接口

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/user-stories | 获取所有US |
| GET | /api/user-stories/{id} | 获取US详情 |
| GET | /api/user-stories/number/{usNumber} | 按编号获取US |
| GET | /api/user-stories/search | 搜索US |
| GET | /api/user-stories/status/{status} | 按状态获取US |
| GET | /api/user-stories/sprint/{sprint} | 按Sprint获取US |
| POST | /api/user-stories | 创建US |
| PUT | /api/user-stories/{id} | 更新US |
| DELETE | /api/user-stories/{id} | 删除US |
| POST | /api/user-stories/{id}/analyze | AI分析US |

### 测试用例接口

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/test-cases | 获取所有用例 |
| GET | /api/test-cases/{id} | 获取用例详情 |
| GET | /api/test-cases/number/{caseNumber} | 按编号获取用例 |
| GET | /api/test-cases/search | 搜索用例 |
| GET | /api/test-cases/user-story/{usId} | 按US获取用例 |
| GET | /api/test-cases/status/{status} | 按状态获取用例 |
| POST | /api/test-cases | 创建用例 |
| PUT | /api/test-cases/{id} | 更新用例 |
| DELETE | /api/test-cases/{id} | 删除用例 |
| GET | /api/test-cases/stats | 用例统计 |

### 测试脚本接口

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/test-scripts | 获取所有脚本 |
| GET | /api/test-scripts/{id} | 获取脚本详情 |
| GET | /api/test-scripts/test-case/{testCaseId} | 按用例获取脚本 |
| GET | /api/test-scripts/type/{type} | 按类型获取脚本 |
| POST | /api/test-scripts | 创建脚本 |
| PUT | /api/test-scripts/{id} | 更新脚本 |
| DELETE | /api/test-scripts/{id} | 删除脚本 |
| POST | /api/test-scripts/generate | AI生成脚本 |
| GET | /api/test-scripts/stats | 脚本统计 |

### 测试执行接口

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/executions | 获取所有执行 |
| GET | /api/executions/{id} | 获取执行详情 |
| GET | /api/executions/execution-id/{executionId} | 按ID获取执行 |
| GET | /api/executions/test-case/{testCaseId} | 按用例获取执行 |
| GET | /api/executions/status/{status} | 按状态获取执行 |
| GET | /api/executions/recent | 获取最近执行 |
| POST | /api/executions | 创建执行 |
| POST | /api/executions/{id}/start | 开始执行 |
| POST | /api/executions/{id}/complete | 完成执行 |
| POST | /api/executions/{id}/fail | 标记执行失败 |
| POST | /api/executions/{id}/cancel | 取消执行 |
| GET | /api/executions/stats | 执行统计 |

## 默认用户

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | ADMIN |
| tester | tester123 | USER |

## 部署方式

### 方式一：本地开发环境

```bash
cd /mnt/okcomputer/output/backend-java

# 使用Maven运行
mvn spring-boot:run

# 或使用启动脚本
./start.sh
```

### 方式二：Docker部署

```bash
cd /mnt/okcomputer/output/backend-java

# 启动所有服务（应用 + MySQL + Redis + RabbitMQ）
docker-compose up -d

# 查看日志
docker-compose logs -f autotest-platform

# 停止服务
docker-compose down
```

### 方式三：生产环境

```bash
# 构建JAR包
mvn clean package -DskipTests

# 运行JAR包
java -jar target/autotest-platform-1.0.0.jar
```

## 访问地址

- **API地址**: http://localhost:8080/api
- **H2 Console**: http://localhost:8080/api/h2-console
  - JDBC URL: `jdbc:h2:mem:testdb`
  - Username: `sa`
  - Password: (空)
- **Health Check**: http://localhost:8080/api/actuator/health
- **RabbitMQ管理**: http://localhost:15672 (guest/guest)

## 环境变量

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| SPRING_PROFILES_ACTIVE | 激活的配置文件 | dev |
| MYSQL_HOST | MySQL主机 | localhost |
| MYSQL_PORT | MySQL端口 | 3306 |
| MYSQL_DB | MySQL数据库名 | autotest |
| MYSQL_USER | MySQL用户名 | root |
| MYSQL_PASSWORD | MySQL密码 | - |
| REDIS_HOST | Redis主机 | localhost |
| REDIS_PORT | Redis端口 | 6379 |
| RABBITMQ_HOST | RabbitMQ主机 | localhost |
| RABBITMQ_PORT | RabbitMQ端口 | 5672 |
| RABBITMQ_USER | RabbitMQ用户名 | guest |
| RABBITMQ_PASS | RabbitMQ密码 | guest |
| JWT_SECRET | JWT密钥 | AutoTestPlatformSecretKey2024... |
| OPENAI_API_KEY | OpenAI API密钥 | - |

## WebSocket 实时通信

连接地址: `ws://localhost:8080/api/ws`

订阅主题:
- `/topic/executions` - 执行状态更新
- `/topic/executions/{executionId}` - 特定执行更新
- `/topic/executions/{executionId}/timeline` - 执行时间线
- `/topic/executions/{executionId}/screenshots` - 执行截图

## 验证API

```bash
# 使用验证脚本
./verify.sh

# 或手动测试
# 1. 登录获取Token
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 2. 访问受保护接口
curl http://localhost:8080/api/user-stories \
  -H "Authorization: Bearer <TOKEN>"
```

## 项目统计

- **Java文件**: 50个
- **实体类**: 8个
- **Repository**: 5个
- **Service**: 6个
- **Controller**: 7个
- **DTO**: 10个
- **配置类**: 7个
- **API端点**: 60+

## 总结

✅ 已完成的企业级Java Spring Boot后端：
- 完整的RESTful API设计
- JWT认证和授权
- 数据库实体和关系设计
- Redis缓存集成
- RabbitMQ消息队列
- WebSocket实时通信
- OpenAI AI服务集成
- Docker容器化支持
- 全局异常处理
- 数据初始化

项目已准备就绪，可以构建和部署！
