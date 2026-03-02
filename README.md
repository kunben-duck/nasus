# AutoTest Platform

企业级自动化测试平台，覆盖从需求分析到用例生成、脚本生成、执行监控、结果报告和系统管理的完整链路。

## 文档导航

- 总体架构（本文件）：`/Users/uben/project/project/test-auto/test-auto-pro/README.md`
- 后端技术文档：`/Users/uben/project/project/test-auto/test-auto-pro/kun-backend/README.md`
- 前端技术文档：`/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/README.md`

## 总体架构

```text
Browser Pages (kun-frontend/index + kun-frontend/pages/*)
  -> kun-frontend/shared/app-runtime.js (auth/api/runtime)
  -> kun-frontend/shared/app-pages.js (page feature orchestration)
  -> REST API (/api/*)
Java Backend (Spring Boot + Spring Security + Spring Data JPA + Spring AI)
  -> PostgreSQL (domain data)
  -> Redis (cache + execution async queue)
  -> OpenAI Model Provider (via Spring AI)
```

## 功能域与页面映射

- 仪表盘：`/index.html`
  - 统计指标、执行趋势、状态分布、最近活动、快捷入口。
- US 需求管理：`/pages/us-management.html`
  - US CRUD、搜索筛选、AI 分析、AI 生成用例、导入。
- 测试用例：`/pages/test-cases.html`
  - 用例 CRUD、步骤维护、批量筛选、按 US 生成、生成脚本入口。
- 脚本工作室：`/pages/script-studio.html`
  - 可视化步骤编辑、代码同步、AI 生成、保存、运行。
- 执行中心：`/pages/execution-hub.html`
  - 创建执行、开始/停止、进度日志、瀑布图、执行截图。
- 报告中心：`/pages/reports.html`
  - 执行列表筛选、统计汇总、报告详情、JSON 导出。
- 系统设置：`/pages/settings.html`
  - 通用/集成/API/通知/执行设置，系统管理员账户管理。
- 登录页：`/pages/login.html`
  - JWT 登录与回跳。

## 技术栈基线

- 前端
  - HTML + CSS + JavaScript（MPA）
  - 运行时：`kun-frontend/shared/app-runtime.js`、`kun-frontend/shared/app-pages.js`
  - 部署：Nginx（`kun-frontend/Dockerfile`）
- 后端
  - Java 21
  - Spring Boot 3.x
  - Spring Security + JWT
  - Spring Data JPA (Hibernate)
  - Spring AI（OpenAI Provider）
  - Redis + PostgreSQL
- AI 框架
  - Spring AI 使用 GA 版本线（当前工程基线：`1.1.2`）。
- 编排
  - Docker Compose（跨平台统一启动）

## 启动与访问

```bash
cp .env.example .env
docker compose up -d --build
```

- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:8080/api`

默认账号：

- `admin / admin123`
- `manager / manager123`
- `developer / developer123`
- `tester / tester123`

## Render 部署

项目已提供 Render Blueprint：`/Users/uben/project/project/test-auto/test-auto-pro/render.yaml`。

### 1. 部署前准备

1. 代码已推送到 GitHub 仓库默认分支。
2. 准备模型配置：
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL`（可选，默认 `gpt-4o-mini`）

### 2. 一键创建（Blueprint）

1. 登录 Render，选择 New + > Blueprint。
2. 选择本仓库，Render 会自动读取 `render.yaml`。
3. 确认创建资源：
   - `autotest-frontend`（Web Service）
   - `autotest-backend`（Web Service）
   - `autotest-postgres`（PostgreSQL）
   - `autotest-redis`（Redis）
   - 说明：当前蓝图使用 Render 免费计划（free）。
4. 在 `autotest-backend` 环境变量中补齐：
   - `OPENAI_API_KEY`
5. 触发部署，待两个 Web 服务都为 `Live` 后访问前端 URL。

### 3.1 蓝图已处理的关键点

- 前后端改为 Render 私网直连，避免首发时 `RENDER_EXTERNAL_URL` 相互引用导致的循环依赖：
  - 前端 `API_PROXY_TARGET=http://autotest-backend:10000`
  - 后端 `PLATFORM_EXECUTION_LOCALHOST_REWRITE_BASE_URL=http://autotest-frontend:10000`
- 后端在 Render 固定使用 `PORT=10000`，并通过 `/api/actuator/health` 做健康检查。
- Redis 使用私网 `host/port` 注入，并承担缓存与执行队列能力。

### 3. 部署后校验

1. 后端健康检查：`https://<backend-domain>/api/actuator/health`
2. 前端登录页可访问并完成登录。
3. 执行一次 US 分析 / 用例生成 / 执行任务，确认异步任务可完成（验证 Redis 队列链路）。

## 验收与验证标准

通过以下检查后视为“可用”：

1. 后端健康检查为 `UP`：`/api/actuator/health`
2. 全链路接口联调脚本通过：`/Users/uben/project/project/test-auto/test-auto-pro/scripts/health-check.sh`
3. UI 自动化冒烟通过：`cd /Users/uben/project/project/test-auto/test-auto-pro/kun-frontend && npm test`
4. 真实浏览器逐页关键按钮验证通过（登录、US、用例、脚本、执行、报告、设置）

## 常用命令

```bash
# 启动
docker compose up -d --build

# 停止
docker compose down

# 后端与前端联调检查
./scripts/health-check.sh

# 已启动场景，仅检查联调
./scripts/health-check.sh --skip-up

# UI 冒烟
cd kun-frontend && npm test
```
