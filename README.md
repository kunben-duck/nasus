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
  -> Redis (cache/runtime state)
  -> RabbitMQ (execution async queue)
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
  - RabbitMQ + Redis + PostgreSQL
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
- RabbitMQ 管理台：`http://localhost:15672`

默认账号：

- `admin / admin123`
- `manager / manager123`
- `developer / developer123`
- `tester / tester123`

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
