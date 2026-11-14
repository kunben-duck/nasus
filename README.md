# Nasus Assurance Studio

## README 定位

本 README 作为仓库首页版的项目计划说明，主要回答：

- Nasus 是什么
- 为什么这个项目有意义
- 当前阶段做什么、不做什么
- 当前有哪些核心模块
- 后续应该去哪里看更详细的产品、架构与开发文档

详细的产品特性、系统架构和开发指导已经拆分到 `docs/` 中维护，README 不再承载详细技术方案。

## RealWorld 首个真实迭代闭环

当前已实现 **M0 运行环境与失败回放、M1 对话建项目与画像绑定迭代**，不是 M2–M5 完整业务闭环交付。

- 被测代码固定为 `c4ffein/realworld-django-ninja@87dd078c883a046f5ff20269df2fb004d8b5f83f`；规格固定为 `realworld-apps/realworld@25588846c314b15a5e427ffe816e6b4af7be68c7`。
- 已注册 Python 3.12 / Django / zipapp 构建和 PG-only 环境规格，保留原 Java / Maven / PG+Redis 路径。正式构建仍经过原 ToolInvocation 确认、工作租约、私有归档和 Outbox；新增格式不会获得执行或发布授权。
- `scripts/verify-realworld-loop.py --phase runtime` 独立验证原始、人工缺陷、修复三个提交。每版使用独立 PG 和内部网络，验证镜像 ID、源码与产物摘要、进程身份、真实 HTTP 断言和资源清理。报告包含固定规格文件、请求响应（密钥脱敏）、逐例断言和现有 Runner 的实际探测回执。
- 真实回放结果：原始版 6/6 通过，缺陷版仅越权修改失败，修复版 6/6 通过。原始接口与规格若出现差异会报 `contract_mismatch`，不会降低断言。
- `business_loop_verified` 始终为 `false`：M0 使用人工编写的诊断用例，不声称已经完成模型需求评审、独立人工审批、正式 RunPlan 逐例派发或缺陷关单。Hurl 仅作为规格来源归档，不作为脚本执行器。
- M1 复用现有 Version：对话收集项目名、代码仓库与固定提交，可跳过需求文档及历史测试；采集、结构候选、人工审核和正式发布分别展示。创建迭代必须明确选择发布记录并确认，原始基线不随项目后续发布变化。聊天和按钮均走 `version.create`，支持刷新、原命令重试和按迭代查看绑定。
- M2 需求修订评审、M3 正式链路适配、M4 缺陷生命周期、M5 版本门禁与完成事务尚待实现。Python 路由证据适配也需要在 M3 补齐，不能借用 Java 路由证据。默认 `--phase full` 明确返回未实现，不以诊断回放替代最终验收。

### 复现 M1

准备好下节的 RealWorld 代码仓库，以及本机开发使用的 PostgreSQL、MinIO 后运行：

```bash
npm run verify:realworld-m1
```

此命令通过真实消息 Turn、LangGraph PostgreSQL checkpoint 和正式工具调用，回放固定提交的代码采集、结构候选、独立审核账号批准、画像发布和对话创建迭代。验证普通问题不会丢失提案、刷新可恢复、重复确认不重复创建，并回读数据库中的画像摘要与代码 SHA；同时通过画像证据接口核对文章更新函数、作者权限校验与 Article 数据模型，记录来源修订、代码行号和片段摘要。使用一次性数据库和私有 MinIO bucket，结束后清理，不改动开发业务数据。

报告位于 `output/realworld/m1-<时间>/report.json`，同时保存测试日志和 JUnit 结果。已在真实 RealWorld 代码上验证通过；这里的“真实”指代码、存储、解析和正式命令，不包含 live 模型语义评审、Temporal Worker 重启验收或完整质量闭环，报告明确保留 `live_model_verified=false` 和 `business_loop_verified=false`。

开发页面从 Build 对话开始，发布审核仍在现有系统画像面板独立完成；发布后可回复 `创建迭代 Sprint 1，使用画像发布 <发布ID>`，核对后回复 `确认创建迭代`。迭代页也提供同一命令的图形入口。新建时需要当前发布头，历史读取则坚持原始绑定，不自动选择 `versions[0]`。首次绑定原子启用该项目的新链路，旧未绑定版本不自动补写画像。详细接口与事务边界见 [版本交付设计](docs/design/quality-loop/version-delivery.md)。

### 复现 M0

以下目录为独立验收仓库，不改动 Nasus 的业务数据或开发服务。只在首次准备时执行克隆及分支操作；不要在已经有工作的同名目录重复初始化。

```bash
git clone --no-checkout https://github.com/c4ffein/realworld-django-ninja.git .nasus/validation/realworld-django-ninja
git clone --no-checkout https://github.com/realworld-apps/realworld.git .nasus/validation/realworld-spec
git -C .nasus/validation/realworld-django-ninja switch -c codex/nasus-realworld-defect 87dd078c883a046f5ff20269df2fb004d8b5f83f
git -C .nasus/validation/realworld-django-ninja am "$(pwd)/tests/fixtures/realworld/patches/0001-test-inject-article-ownership-defect-for-Nasus-accep.patch"
git -C .nasus/validation/realworld-django-ninja switch -c codex/nasus-realworld-fix
git -C .nasus/validation/realworld-django-ninja am "$(pwd)/tests/fixtures/realworld/patches/0002-fix-restore-ownership-validation-for-Nasus-regressio.patch"
docker build -t nasus-realworld-runtime:local infra/targets/realworld
docker pull postgres:16
npm run verify:realworld-loop -- --phase runtime \
  --image "$(docker image inspect nasus-realworld-runtime:local --format '{{.Id}}')" \
  --pg-image "$(docker image inspect postgres:16 --format '{{.Id}}')"
```

`git am` 需要本地 Git 身份配置；重放补丁的 SHA 可以不同，校验器会核验祖先链、缺陷精确范围以及修复树与原始树一致。验收报告写入 `output/realworld/<时间>/report.json`，任何构建、环境、用例或清理失败均返回非零退出码。

运行镜像使用 `infra/targets/realworld/requirements.lock` 锁定依赖版本；构建阶段不联网安装依赖，只在固定镜像中校验源码语法、Python 版本和已安装依赖。版本锁定不代表已完成供应链审计或跨平台字节级可重现构建，相关标志仍保持未验证。

若要在现有构建面板使用该规格，需要由操作者配置 `NASUS_NATIVE_BUILD_PYTHON_IMAGE_ID` 和 `NASUS_NATIVE_BUILD_PYTHON_LOCK_HASH`（报告中的 `dependency_lock.hash`），产物路径使用 `target/*.pyz`。环境注册使用 `nasus.python312-django-pg.v1`，仍需明确注册当前目标实例及 PG，不自动接管诊断回放中已清理的资源。

## 项目定义

### 一句话定义

**通用 coding agents 帮你写代码，Nasus 帮你决定这次变更是否真的准备好上线。**

### 产品愿景

**在 agent 大规模参与研发之后，重建软件交付的质量边界。**

### 产品定位

Nasus 是一个面向 AI coding 时代的**功能验收与上线决策控制平面**。

它的核心职责不是生成代码，也不是替代整个测试工具链，而是围绕一次变更完成：

- 变更理解
- 影响识别
- 验证组织
- 证据收敛
- 结果归因
- 放行建议
- 质量知识沉淀

它要回答的核心问题只有一个：

> **这次变更是否真的准备好上线。**

## 为什么这个项目有意义

在 AI 大规模参与研发之后，代码产出速度会持续提高，但“上线判断”会变得更困难。

团队真正缺的不是更多生成能力，而是：

- 这次变更到底影响了哪些模块、页面、接口和角色
- 当前版本的功能验收是否完整
- 已生成的验证资产是否真正覆盖了风险
- 执行结果能否支撑上线判断
- 失败到底是脚本问题、环境问题，还是功能问题
- 版本结束后，哪些知识应该成为组织的长期质量记忆

存量系统尤其如此。代码仓库、历史 US、历史测试资产、设计文档、UX 图、接口文档和执行证据通常是分散的，导致每个版本都在重复理解系统、重复组织验证、重复承担上线不确定性。

Nasus 的意义，就是在 AI coding 时代，为组织补上一层专门面向**功能验收与上线判断**的控制系统。

## 当前阶段的范围

### 当前阶段做什么

当前阶段聚焦以下主线：

1. 项目创建与存量系统知识接入
2. 系统画像初始化与正式基线建立
3. 版本分支创建与版本级 US 导入
4. 围绕 US 的质量闭环
5. Agent 驱动的验证规划、资产生成与执行组织
6. 执行证据收敛、失败归因与放行建议
7. 高价值知识沉淀与正式基线回写

### 当前阶段不做什么

为避免范围膨胀，以下内容不属于当前阶段目标：

- 不做通用代码生成平台
- 不做通用聊天型 Agent 平台
- 不做全面替代现有测试管理系统的平台
- 不以“生成更多测试用例”作为核心价值目标
- 不优先做 Desktop / Edge 本地执行体系
- 不优先做公网 SaaS 多租户平台
- 不把所有研发运维场景都纳入首发交付

### 当前阶段交付边界

当前阶段默认：

- 以 **Web Portal** 作为正式工作入口
- 以 **agent-first** 作为主交互原则
- 以 **功能验收与上线判断闭环** 作为交付主线
- 以 **Docker 化外部组件** 作为开发与迁移部署基线，数据库、S3/Object Store、索引服务等外部依赖不作为宿主机裸进程交付；具体启动方式见 [后端运维与测试基线](./docs/design/backend/ops-and-test-baseline.md)

本地基础设施验收入口：

```bash
npm run verify:docker-stack
```

日常开发使用宿主机应用进程和 Docker 外部组件：

```bash
npm run dev:up
npm run dev:status
npm run dev:down
```

`dev:up` 会在 Docker 中启动 PostgreSQL、MinIO 和 Temporal，执行
Alembic migration，然后在宿主机启动 Playwright Runner、Temporal
workflow worker、API 和 Portal。运行日志位于 `.nasus/dev/logs/`。
`dev:status` 单独报告 `database_schema`；数据库可连接不代表已迁移到当前代码所需的版本。
对于 Codex、CI 或需要单一终端持续监督全部宿主进程的调试会话，使用
`npm run dev:foreground`；任一子进程退出时会输出日志并统一回收。
单独调试 API 时使用 `npm run dev:api`，该命令同样加载统一开发环境并
连接 PostgreSQL；不支持绕过 migration 继续写入历史 SQLite 状态文件。

使用 Podman 替代 Docker 运行外部组件时，见 [Podman 本地开发启动指南](./docs/design/backend/podman-development.md)。
该指南采用应用本机分终端启动；现有 `dev:up` / `dev:foreground` 仍依赖 Docker，不能直接套用。
Podman 路径尚未完成实机启动验收，具体限制和验证步骤见指南。

### 使用 exweb 试用

在 `npm run dev:status` 确认 `database_schema: current` 后，打开
[Build](http://localhost:5173/build)，选择「导入 Git 仓库」。使用
`https://github.com/kunben-duck/exweb.git` 和固定提交
`fe5827f6b76f77ef34918d8b452ee823142332dc`，避免分支更新改变试用输入。
[试用与验收指南](./docs/design/system-image/exweb-acceptance-baseline.md)提供可选需求、用例和画像证据查看步骤。
试用资料是草稿；正式执行和清理结果以[验收报告](./docs/design/system-image/exweb-native-runtime-validation.md#可复跑的正式验收命令)为准。

浏览器回归使用同一 PostgreSQL 服务上的一次性测试数据库：

```bash
npm run test:e2e
npm run test:e2e -- tests/e2e/source-documents.spec.ts
```

该入口加载开发连接配置，由 `scripts/test-api-postgres.py` 创建随机
`nasus_test_*` 数据库、执行迁移、启动独立测试 API/Portal，并在退出时清理。
业务测试不写入开发库，也不回退到 SQLite；可用 `NASUS_TEST_DATABASE_URL`
指定另一台本机 PostgreSQL 服务，连接角色需要创建数据库的权限。
测试 API 的 Studio settings 当前是共享设置，浏览器回归默认单 worker，
避免并发切换主题/语言导致样式断言和截图失真。

需要验证真实 MinIO 归档时，可在已显式设置 `NASUS_TEST_DATABASE_URL`、
`NASUS_TEST_S3_ENDPOINT`、`NASUS_TEST_S3_ACCESS_KEY` 和
`NASUS_TEST_S3_SECRET_KEY` 后运行：

```bash
./.venv/bin/python scripts/test-api-postgres.py --minio apps/api/tests/test_source_evidence_api.py apps/api/tests/test_private_object_storage.py -q
```

`--minio` 只允许本地 S3 服务，创建随机私有 `nasus-test-*` 桶并在退出时清理；
不会使用开发桶。默认不加此选项时仍使用隔离的本地对象适配器，不代表验证过 MinIO。

生产化 Compose 拓扑验收入口：

```bash
npm run verify:production-compose
NASUS_VERIFY_PRODUCTION_COMPOSE_BUILD=true npm run verify:production-compose
```

V1 候选完整验收入口：

```bash
npm run verify:v1-release
```

本机资源充足时可用 `NASUS_RELEASE_BACKEND_WORKERS=3 npm run verify:v1-release`。
只并行后端 pytest；各片独立使用 PostgreSQL 和 MinIO，并核对完整收集清单与结果。
其他门禁不变，默认仍为串行。

## 核心产品原则

1. **质量保障优先于测试生成**
2. **功能验收与上线判断优先于资产数量**
3. **统一上下文优先于离散检索**
4. **系统画像是长期资产，不是一次性导入结果**
5. **版本期间更新工作基线，不直接污染正式基线**
6. **会话知识默认私有，可经治理提升**
7. **Agent-first，但不能绕过治理**
8. **Agent 负责规划与收敛，执行保持确定性**
9. **证据、审计、审批优先于一次性全自动**

## 核心工作空间

- **Build**：项目创建与原料接入入口
- **Dashboard**：项目组合与全局进展仪表盘
- **Documentation**：说明、指南、模板与方法论入口
- **Project Space**：项目级长期空间
- **Version Space**：版本级协作与收敛空间
- **Personal Workspace**：围绕单个 US 的质量主工作区

## 当前阶段的核心应用模块

README 里的“模块”只指产品应用架构模块，不把前端、后端、平台底座这类技术拆分当成产品一级模块。

### 1. 系统画像构建模块

这是 Nasus 的系统理解基础层，负责把分散的存量系统知识转成可持续使用的系统画像。

它回答的问题是：

- 当前系统到底由哪些模块、页面、接口、依赖和历史资产组成
- 当前版本变更影响了哪些对象
- Agent 和质量闭环应该基于什么上下文开展工作

它承载的关键能力包括：

- 代码、历史 US 文档、历史测试用例和自动化脚本三类一等 source 接入
- UX、OpenAPI、缺陷和执行日志等增强 source 接入
- 系统画像初始化
- 正式系统基线建立与维护
- 版本工作基线与正式基线的关系管理
- 为后续分析、生成、执行和放行提供统一上下文

### 2. Agent 主体模块

这是 Nasus 的主驱动主体，负责把用户目标转成可持续推进的工作过程。它不是“页面里的聊天助手”，而是贯穿整个系统的 `Agent Service`。

它回答的问题是：

- 用户当前真正想完成的任务是什么
- 下一步应该做什么
- 需要调用哪些工具、追问哪些信息、如何推进闭环

它承载的关键能力包括：

- 主会话作为第一操作入口
- 短期工作记忆、会话记忆和项目长期记忆管理
- 自主规划与目标推进
- Tool 调用与结果收敛
- 多 Agent 并行协作与蜂群式任务拆分
- 结果总结、建议与下一步引导

### 3. 质量闭环主体模块

这是 Nasus 的业务价值主线，负责把一次变更从“理解”推进到“是否准备好上线”的判断。

它回答的问题是：

- 当前 US / 版本的功能验收是否完整
- 验证资产是否覆盖风险
- 执行结果是否足以支撑上线判断
- 哪些知识应该沉淀回基线

它承载的关键能力包括：

- 版本创建与 US 导入
- 围绕 US 的质量分析
- 测试范围、场景、计划、用例与自动化建议
- 执行证据、失败归因与修复建议
- 审批、冲突处理、放行建议与基线回写

### 三个模块的关系

Nasus 当前阶段的产品主线可以收敛成：

`系统画像构建 -> Agent 主体 -> 质量闭环主体`

也就是：

- 系统画像构建，为 Agent 和质量工作提供统一上下文
- Agent 主体，负责理解目标、管理记忆、规划步骤、调度工具和并行 Agent
- 质量闭环主体，负责形成可审计的功能验收结果和上线判断

## Agent-first 要求

Nasus 不是“页面里加一个聊天框”，而是一个 **agent-first** 产品。

这意味着：

- 主会话是第一操作入口
- 用户应该可以通过自然语言驱动关键工作
- 按钮、表单、快捷操作只是同一工具体系的可视化封装
- Agent 可以主动追问缺失信息、规划下一步、组织质量闭环
- 系统内部所有核心业务能力都应注册为工具，让 Agent 可以原生调用
- Agent Service 必须管理短期记忆、会话记忆、长期系统画像记忆和候选知识
- 复杂任务可以由 Agent 拆分为多个并行子 Agent 协作完成，再由合并与治理链路收敛

同时，agent-first 不等于 uncontrolled agent：

- Agent 不能绕过治理、审批和正式结论链路
- Agent 不能直接污染正式基线
- Agent 不能把一次性输出直接当成正式事实
- 并行子 Agent 只能提交候选结果，不能直接写正式领域对象

## 关键用户旅程

1. 用户在 `Build` 创建项目并导入存量系统知识
2. 系统初始化系统画像并形成正式系统基线
3. 用户创建版本并导入版本级 US / 分支信息
4. 用户围绕 US 启动质量闭环，Agent 生成验证方案
5. 用户多轮审核并补充意见，系统局部重生成并收敛
6. 系统执行自动化并分析失败
7. 系统给出上线准备度建议
8. 高价值知识经过审批沉淀回版本工作基线或正式系统基线

## 当前阶段目标

### 业务目标

- 降低存量系统版本变更的理解成本
- 提升功能验收设计质量与覆盖度
- 提高验证资产生成与维护效率
- 为 AI 生成代码建立可验证、可审计、可放行的质量机制
- 让团队对“是否可以上线”形成更稳定的证据与决策基础
- 沉淀组织级质量记忆，提升后续版本交付信心

### 成功标准

当前阶段的成功，不是“功能很多”，而是“完整跑通一条可上线判断的闭环”。

也就是：

- 在 1 个存量系统上完成初始化接入
- 在 1 条真实版本链路上完成 US 质量闭环
- 能输出可追溯的执行证据与放行建议
- 能在版本结束后完成一次正式知识沉淀

## 文档导航

### 外层总览

- [项目计划书](./docs/nasus_assurance_studio_implementation_plan.md)
- [文档总览](./docs/README.md)
- [产品需求基线](./docs/product-requirements.md)
- [最终特性说明书](./docs/final-feature-spec.md)
- [系统架构与部署设计](./docs/system-architecture.md)
- [实现总览](./docs/implementation-overview.md)
- [统一设计文档总览](./docs/design/README.md)

### 产品模块与空间承载面

以下文档分别回答：

- 产品一级模块由哪些能力组成
- 这些能力落在哪些工作空间里
- 研发实现如何分层落地

- [模块地图](./docs/design/product-modules.md)
- [系统画像构建模块](./docs/design/system-image/README.md)
- [Agent 主体模块](./docs/design/agent/README.md)
- [质量闭环主体模块](./docs/design/quality-loop/README.md)
- [Studio Entry 空间](./docs/design/spaces/studio-entry.md)
- [Project Foundation 空间](./docs/design/spaces/project-foundation.md)
- [平台能力总览](./docs/design/platform/README.md)

### 原型基线

- [UX 原型 HTML](./ux/index.html)
- [UX 原型样式](./ux/styles.css)
- [UX 原型脚本](./ux/app.js)
