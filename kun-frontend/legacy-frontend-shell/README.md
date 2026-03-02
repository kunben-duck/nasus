# AutoTest Platform Frontend

本目录文档描述前端页面实现与接口联动策略。当前前端采用 MPA（多页面）+ 原生 JavaScript，统一运行时在 `shared/` 中。

## 1. 前端结构

页面入口：

- `/Users/uben/project/project/test-auto/test-auto-pro/index.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/pages/login.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/pages/us-management.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/pages/test-cases.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/pages/script-studio.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/pages/execution-hub.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/pages/reports.html`
- `/Users/uben/project/project/test-auto/test-auto-pro/pages/settings.html`

共享运行时：

- `/Users/uben/project/project/test-auto/test-auto-pro/shared/app-runtime.js`
  - JWT 登录、token 刷新、统一 API 请求、toast、格式化。
- `/Users/uben/project/project/test-auto/test-auto-pro/shared/app-pages.js`
  - 各页面初始化逻辑、DOM 渲染、按钮事件、业务流编排。

## 2. 页面能力矩阵

- 仪表盘
  - 统计卡片、趋势图、状态分布、活动流。
- US 管理
  - 新建、编辑、删除、搜索、状态筛选、AI 分析、AI 生成测试用例、导入。
- 测试用例
  - 用例 CRUD、步骤维护、多条件筛选、按 US 生成、脚本生成入口。
- 脚本工作室
  - 视觉流程与代码双向同步、AI 生成、保存、删除、运行。
- 执行中心
  - 创建执行、启动/停止、进度、日志、瀑布图、截图。
- 报告中心
  - 列表筛选、统计汇总、详情查看、下载 JSON。
- 设置中心
  - 通用、集成、API 安全、通知、执行默认配置、账户管理（管理员）。
- 登录页
  - 账号密码登录、错误提示、回跳。

## 3. 前端与后端 API 映射

- 仪表盘：`/api/dashboard`
- 认证：`/api/auth/login` `/api/auth/me` `/api/auth/refresh`
- US：`/api/user-stories*`
- 用例：`/api/test-cases*`
- 脚本：`/api/test-scripts*`
- 执行：`/api/executions*`
- 用户管理：`/api/users*`

统一请求通过 `AppRuntime.api()` 发送，默认自动附带 JWT，并处理 401 刷新。

## 4. 状态管理策略

- 页面状态：各页面在 `app-pages.js` 内部 `state` 对象维护。
- 认证状态：`localStorage` + `/auth/me` 校验。
- 设置状态：本地缓存 + 后端持久化接口（以接口为准，本地为兜底）。

## 5. 样式与交互约束

- 保持现有视觉语言：暗色玻璃态、青紫渐变、粒子背景。
- 不改动页面导航信息架构，优先增强功能，不破坏既有 UI 风格。
- 所有关键操作必须给出 toast 反馈（成功/失败/警告）。

## 6. 构建与运行

前端镜像通过 Nginx 提供静态资源：

- Dockerfile：`/Users/uben/project/project/test-auto/test-auto-pro/frontend/Dockerfile`
- Nginx 配置：`/Users/uben/project/project/test-auto/test-auto-pro/frontend/nginx.conf`

运行：

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro
docker compose up -d --build frontend
```

## 7. 验证方案

自动化验证：

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro
npm test
```

联调验证：

```bash
cd /Users/uben/project/project/test-auto/test-auto-pro
./scripts/health-check.sh --skip-up
```

人工验证（浏览器逐页）：

- 登录 -> 仪表盘 -> US -> 用例 -> 脚本 -> 执行 -> 报告 -> 设置
- 验证每页主按钮均可触发真实后端行为并有反馈。
