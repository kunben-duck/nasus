# Nasus 产品模块地图

## 1. 说明

本文只描述 **产品一级模块**，不再混入前端、后端、平台底座这类技术实现维度。

当前 Nasus 的产品一级模块固定为 3 个：

1. **系统画像构建模块**
2. **Agent 主体模块**
3. **质量闭环主体模块**

三大模块的正式需求、V1 范围、输入输出和验收口径以 [产品需求基线](../product-requirements.md) 为准；本文件负责承接模块级设计入口。

这 3 个模块的关系是：

`系统画像构建 -> Agent 主体 -> 质量闭环主体`

也就是：

- 系统画像构建，为后续工作提供统一上下文
- Agent 主体，作为系统级 Agent Service，负责理解目标、管理记忆、规划步骤、调用工具、并行调度子 Agent 和驱动推进
- 质量闭环主体，负责形成可审计的功能验收结果和上线判断

## 2. 三大模块总览

| 一级模块 | 核心问题 | 主要职责 | 主要承载面 |
| --- | --- | --- | --- |
| 系统画像构建模块 | 当前系统到底是什么、这次变更影响了什么 | 原料接入、系统画像初始化、基线与分支、上下文组装 | `Build` `Project Space` `Knowledge` |
| Agent 主体模块 | 用户当前要完成什么、下一步该做什么 | 主会话、短期/长期记忆、自主规划、Tool 调用、Goal 推进、Agent Swarm | 所有主会话入口 |
| 质量闭环主体模块 | 这次变更是否真的准备好上线 | 版本创建、US 质量分析、资产生成、执行证据、治理与放行 | `Version Space` `Personal Workspace` `Runs` `Governance` |

## 3. 模块文档

### 3.1 系统画像构建模块

- [模块总览](./system-image/README.md)
- [Context Engine 设计](./system-image/context-engine.md)
- [知识摄入管线](./system-image/ingestion-pipeline.md)
- [基线与分支规则](./system-image/baseline-and-branching.md)
- [长期质量闭环支撑方案](./system-image/quality-closure-enablement.md)

### 3.2 Agent 主体模块

- [模块总览](./agent/README.md)
- [会话运行时](./agent/conversation-runtime.md)
- [Agent Service、记忆与蜂群模式](./agent/agent-service-memory-and-swarm.md)
- [Agent Loop Runtime](./agent/agent-loop-runtime.md)
- [LLM 运行时](./agent/llm-runtime.md)
- [Tool Catalog](./agent/tool-catalog.md)

### 3.3 质量闭环主体模块

- [模块总览](./quality-loop/README.md)
- [版本交付](./quality-loop/version-delivery.md)
- [质量工作台](./quality-loop/quality-workspace.md)
- [执行与可观测性](./quality-loop/execution-observability.md)
- [治理与放行](./quality-loop/governance-release.md)
- [质量生成策略](./quality-loop/quality-generation.md)

## 4. 与其他目录的关系

- `./spaces/`：描述工作空间与页面承载面
- `./frontend/`、`./backend/`、`./platform/`：描述工程实现细节

也就是说：

- `product-modules.md` 回答“产品由哪些一级能力构成”
- `design/spaces` 回答“这些能力落在哪些工作空间里”
- `frontend / backend / platform` 回答“这些能力如何被实现”
