# Agent 工具目录的无损预算编码

更新：2026-10-11。该内部协议支持不断增长的系统画像、测试设计、RunPlan 与原环境工具，不修改公开 Tool Catalog、Tool ID、RBAC、确认或执行入口。

## 问题与边界

2026-10-10 的 canonical registry 有 141 项工具，2026-10-11 实际 core + system_image 定义已增至 146 项。原 Planner 提示同时重复完整 ID 清单和 12 项详细契约；在 6999 UTF-8 字节预算内，重复前缀使高优先级工具被低成本填充项挤掉。不能通过删除 ID、缩短必填输入、省略风险/确认模式或扩大原预算掩盖问题。

`application/agent/tool_catalog_encoding.py` 只压缩内部目录的字符串表示。历史 v2 以点分前缀形成字典；新 v3 同样合并有序后缀组，但也可提取反复出现的下划线分隔前缀，例如 `query.quality.run_plan_`。只有仍有非空后缀时才分解，完整 canonical ID 可以合法地以下划线结尾。新版片段：

```json
{
  "schema": "nasus.agent-tool-catalog.v3",
  "available_count": 3,
  "tool_id_prefixes": ["query.sample.item_"],
  "available_tool_ids": [[0, ["first", "second", "third"]]],
  "relevant_tools": []
}
```

这个片段只演示 registry 编码，不是完整生产目录。依次展开每组，再拼接 `tool_id_prefixes[index] + suffix`，即可还原所有 canonical ID 及原顺序。新格式只有比未编码 registry 更小时才使用；小目录和历史未编码快照仍保持字符串列表。历史 v2 继续按原点分前缀规则读取，不自动重写或接受 v3 的部分 token 前缀。未知 schema、错误索引、bool 伪装整数、重复完整 ID（包括不同前缀拼接碰撞）、坏前缀、空组或计数不一致均拒绝。

本次完整 backend 诊断发现 50 项同族增长使旧 v2 的原 top-12 最小正文达到 7120 字节，环境核验工具被较便宜条目替代。新 v3 复用同一解码语义和 DTO，压缩重复 `run_plan_` / `test_design_` / `item_`；不修改排序、12 项数目、6999 字节上限或完整治理字段。实际验证及原失败日志见实施记录，这不是任意增长下保持固定预算的承诺。

## Planner 与正式治理

- 初始 Planner 和 Replanner 都附加固定解码说明，不依赖某个可编辑 prompt template 恰好包含说明。模型输出必须仍为完整 canonical Tool ID，不能输出后缀或索引组。
- `relevant_tools` 始终包含完整 ID、风险、确认模式及全部必填输入；只允许缩短展示 label/description。12 项明细与原 6999 字节门禁不变，超限仍明确失败，不隐式删减 registry。
- 原生构建、RunPlan 原环境与原观察登记的中英文意图选择保留对应的读取、预览和独立确认工具。工具可发现不等于已有参数、资源权限、来源出口许可、确认、部署或执行授权。
- Planner 输出依旧经过 canonical registry 校验和 `AgentPlanPolicy`。缺必填输入或跨项目请求被拒绝；伪造确认字段被移除，写计划转为受治理 Goal，正式执行仍经过 ToolInvocationRuntime。
- 公开目录和原 ToolDefinition 不使用内部编码，不减少外部工具数量或改变既有 JSON 类型。API DTO、历史 ToolInvocation、审计和 SSE 不因此重写。

## 验证范围

契约测试核对真实目录所有 ID 的有序无损回读、原公开定义不变、随机顺序、确定性、50 项同族工具增长后完整高优先级契约仍在原预算内，以及无法表示的较大目录明确失败。两类 Planner 的实际 application 调用使用显式 LLM transport specimen，验证完整 ID、必填输入、跨作用域拒绝和独立写治理。

这些测试不是外部真实模型对编码的理解质量、自动完成率或累计 token/费用的证明；也不说明任何模型能在任意增长下保持固定预算。生产超过门禁仍需显式扩展目录发现/分页协议，而不是截断工具。具体批次与原生 PG/MinIO 终态见[实施记录](./implementation-progress.md)，完整 P0-P6 目标不因这项内部修复完成。
