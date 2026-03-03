# AutoTest Platform Frontend (kun-frontend)

本目录是前端主工程目录，采用 MPA（多页面）+ 原生 JavaScript，统一运行时在 `shared/` 中。

## 1. 前端结构

页面入口：

- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/index.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/pages/login.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/pages/us-management.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/pages/test-cases.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/pages/script-studio.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/pages/execution-hub.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/pages/reports.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/pages/settings.html`

共享运行时：

- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/shared/app-runtime.js`
- `/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/shared/app-pages.js`

## 2. 页面能力矩阵

- 仪表盘：统计卡片、趋势图、状态分布、活动流。
- US 管理：新增、编辑、删除、搜索、状态筛选、AI 分析、AI 生成测试用例、导入。
- 测试用例：CRUD、步骤维护、多条件筛选、按 US 生成、脚本生成入口。
- 脚本工作室：视觉流程与代码同步、AI 生成、保存、删除、运行。
- 执行中心：创建执行、启动/停止、进度、日志、瀑布图、截图。
- 报告中心：列表筛选、统计汇总、详情查看、下载 JSON。
- 设置中心：通用、集成、API 安全、通知、执行默认配置、账户管理（管理员）。

## 3. 前端与后端 API 映射

- 仪表盘：`/api/dashboard`
- 认证：`/api/auth/login` `/api/auth/me` `/api/auth/refresh`
- US：`/api/user-stories*`
- 用例：`/api/test-cases*`
- 脚本：`/api/test-scripts*`
- 执行：`/api/executions*`
- 用户管理：`/api/users*`
- 设置：`/api/settings`

## 4. 构建与运行

- Dockerfile：`/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/Dockerfile`
- Nginx 配置：`/Users/uben/project/project/test-auto/test-auto-pro/kun-frontend/nginx.conf`
- 关键环境变量：
  - `API_PROXY_TARGET`：后端根地址（例如 `http://backend-java:8080`）
  - `PORT`：容器监听端口（默认 `80`）

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro
docker compose up -d --build frontend
```

## 5. 验证

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro/kun-frontend
npm test
```

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro
./scripts/health-check.sh --skip-up
```
