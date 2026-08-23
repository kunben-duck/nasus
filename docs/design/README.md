# Nasus 设计文档总览

## 1. 说明

`docs/design/` 是 Nasus 的统一设计文档区。

过去分散在旧 `modules/`、`implementation/`、`spaces/` 目录下的设计文档已经收敛到这里，避免同一主题同时散落在产品模块目录、技术实现目录和空间目录中。

根目录文档负责回答“为什么、做什么、总体怎么做”；本目录负责回答“各主题具体如何设计和落地”。

入口文档：

- [实现总览](../implementation-overview.md)
- [技术方案设计基线](../technical-solution-baseline.md)
- [产品模块地图](./product-modules.md)

## 2. 产品模块设计

- [系统画像构建](./system-image/README.md)
- [Agent 主体](./agent/README.md)
- [质量闭环主体](./quality-loop/README.md)

## 3. 工程实现设计

### 3.1 前端

- [Portal 前端架构](./frontend/portal-architecture.md)
- [前端视觉与交互规范](./frontend/visual-style.md)

### 3.2 后端

- [后端总设计](./backend/system-design.md)
- [后端代码架构与 DDD 分层](./backend/code-architecture.md)
- [后端领域模型](./backend/domain-model.md)
- [后端运行时与工具协议](./backend/runtime-and-tool-protocol.md)
- [后端 API 与事件契约](./backend/api-and-events.md)
- [后端执行与治理](./backend/execution-governance.md)
- [后端运维与测试基线](./backend/ops-and-test-baseline.md)
- [备份与恢复运行手册](./backend/backup-and-recovery-runbook.md)
- [端到端数据流示例](./backend/end-to-end-flow-examples.md)

### 3.3 平台能力

- [平台能力总览](./platform/README.md)
- [认证与授权设计](./platform/auth-and-access-design.md)
- [MCP 集成设计](./platform/mcp-integration-design.md)

## 4. 空间与页面承载面

- [空间总览](./spaces/README.md)
- [Studio Entry](./spaces/studio-entry.md)
- [Project Foundation](./spaces/project-foundation.md)
