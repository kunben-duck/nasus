# Nasus 文档总览

## 1. 文档分层原则

Nasus 的文档体系按 4 层组织：

1. **项目级**：解释项目为什么存在、当前范围和产品定位
2. **总览级**：解释产品能力真相、整体架构和实现总蓝图
3. **产品模块级**：按 3 个一级应用模块组织产品能力
4. **技术实现级**：按前端、后端、平台能力组织研发实现细节

补充说明：

- `README.md` 是仓库首页版项目说明，不展开详细技术方案。
- 本目录下的文档是完整文档体系。
- 所有详细设计统一放在 `design/` 下；不再保留独立的 `modules/`、`implementation/`、`spaces/` 旧目录。
- `design/spaces` 描述的是工作空间和页面承载面，不是产品一级模块。

## 2. 项目级文档

- [项目计划书](./nasus_assurance_studio_implementation_plan.md)

## 3. 总览级文档

- [产品需求基线](./product-requirements.md)
- [技术方案设计基线](./technical-solution-baseline.md)
- [最终特性说明书](./final-feature-spec.md)
- [系统架构与部署设计](./system-architecture.md)
- [实现总览](./implementation-overview.md)

这些文档分别回答：

- 首个正式版本具体要交付什么、如何验收
- 当前需求对应的技术方案、生产准入和开发顺序
- 产品应该如何工作
- 系统整体如何设计
- 工程实现应该如何落地

## 4. 产品模块级文档

Nasus 的产品一级模块当前收敛为 3 个：

### 4.1 系统画像构建模块

- [模块总览](./design/system-image/README.md)
- [Context Engine 设计](./design/system-image/context-engine.md)
- [知识摄入管线](./design/system-image/ingestion-pipeline.md)
- [基线与分支规则](./design/system-image/baseline-and-branching.md)
- [长期质量闭环支撑方案](./design/system-image/quality-closure-enablement.md)

### 4.2 Agent 主体模块

- [模块总览](./design/agent/README.md)
- [会话运行时](./design/agent/conversation-runtime.md)
- [Agent Service、记忆与蜂群模式](./design/agent/agent-service-memory-and-swarm.md)
- [Agent Loop Runtime](./design/agent/agent-loop-runtime.md)
- [LLM 运行时](./design/agent/llm-runtime.md)
- [Tool Catalog](./design/agent/tool-catalog.md)

### 4.3 质量闭环主体模块

- [模块总览](./design/quality-loop/README.md)
- [版本交付](./design/quality-loop/version-delivery.md)
- [质量工作台](./design/quality-loop/quality-workspace.md)
- [执行与可观测性](./design/quality-loop/execution-observability.md)
- [治理与放行](./design/quality-loop/governance-release.md)
- [质量生成策略](./design/quality-loop/quality-generation.md)

### 4.4 模块地图

- [模块地图](./design/product-modules.md)

## 5. 空间与页面承载面

- [空间总览](./design/spaces/README.md)
- [Studio Entry](./design/spaces/studio-entry.md)
- [Project Foundation](./design/spaces/project-foundation.md)

## 6. 技术实现级文档

- [实现层总览](./design/README.md)

### 6.1 前端实现

- [Portal 前端架构](./design/frontend/portal-architecture.md)
- [前端视觉与交互规范](./design/frontend/visual-style.md)

### 6.2 后端实现

- [后端总设计](./design/backend/system-design.md)
- [后端领域模型](./design/backend/domain-model.md)
- [后端运行时与工具协议](./design/backend/runtime-and-tool-protocol.md)
- [后端 API 与事件契约](./design/backend/api-and-events.md)
- [后端执行与治理](./design/backend/execution-governance.md)
- [后端运维与测试基线](./design/backend/ops-and-test-baseline.md)
- [端到端数据流示例](./design/backend/end-to-end-flow-examples.md)

### 6.3 平台能力

- [平台能力总览](./design/platform/README.md)
- [认证与授权设计](./design/platform/auth-and-access-design.md)
- [MCP 集成设计](./design/platform/mcp-integration-design.md)

## 7. 原型基线

- [UX 原型 HTML](../ux/index.html)
- [UX 原型样式](../ux/styles.css)
- [UX 原型脚本](../ux/app.js)
