# 代码观察归档与身份准入

更新：2026-10-08。新分析报告将适配器收到的规范化投影私有归档，再进行代码身份准入；原生查询另存转换前的解码响应。这样可以调查未解析实体、被拒绝的调用及未知关系类型，而不把观察提升为正式知识或业务覆盖。该能力属于 P1 底座，完整 P0-P6 验收范围仍以[主方案](./autonomous-system-image-design.md)与[实施记录](./implementation-progress.md)为准。

## 三种数据的边界

| 数据 | 保存内容 | 使用边界 |
| --- | --- | --- |
| 原生查询观察 | 实际 search/query 请求及解码后的完整返回对象，包括查询分区探针、未知类型、未解析端点和原生属性 | 私有诊断证据；不是完整原生数据库导出、字节级 wire log 或已核验事实 |
| 收到的规范化投影 | 完整 CodeIntelligenceResult 的实体、关系、解析诊断和 Provider 声明；包括 unresolved/ambiguous 实体 | 可分页调查，不能凭存在或分数获得 canonical 身份 |
| 冻结画像成员 | 经独立登记的 Nasus 身份、确切来源修订及可回读 Evidence；关系端点封闭 | 画像及关联操作的正式输入，但不自动取得业务规范批准或运行验证结论 |

原生关系转换可能反向、合并或排除。原生 `INHERITS` 不会仅因为被归档就变成正式继承事实；Java import 的反证检查、模糊调用排除和未解析身份限制保持原样。未知观察无需伪造 UUID 才能保存。

## 私有工件与报告固定

`ArchivedCodeAnalysisRecorder` 在身份登记之前保存 `nasus.code-analysis.v3`。PostgreSQL 原追加式分析表只固定报告、摘要和私有工件引用；完整观察位于私有 MinIO 的内容寻址对象，namespace 同时绑定 project/source。

- `nasus.code-observation-archive.v1` 保存完整规范投影。`v2` 在完全相同的 result 之外增加非空 `native_queries`；没有原生响应的 Tree-sitter 分析继续使用 v1，不伪造供应商观察。
- 工件绑定 project、source、source manifest hash、external revision、Provider/version 和内容摘要。先 PUT，再有界 GET 校验原字节及重建摘要，最后提交 PG 报告；归档失败不能产生报告成功回执或冻结候选。
- 规范投影最多 50000 实体、100000 关系，工件最多 32 MiB。原生查询最多 4096 条、16 MiB；超过边界明确拒绝，不静默裁剪。JSON 拒绝重复 key、NaN/Infinity、非对象响应和错误 Provider pin。
- CLI 外层对象及 MCP text 内层对象均在首次解码时严格校验，拒绝重复 key 和溢出为 Infinity 的数值，不先用普通 JSON 解码覆盖重复字段后再归档。错误 envelope 不进入映射或观察集合。
- 有 Provider 声明时，原生响应必须匹配声明中 availability=observed 的 Provider/version；全部 unavailable 不允许回退到 result 的顶层 Provider。仅没有声明的历史规范投影使用旧顶层 pin，不能用兼容路径绕过不可用状态。
- 原生响应作为不可变 JSON 文本保存，application/domain 不解析供应商节点或查询语义。JSON 的空白、key 顺序及数值表示可以规范化，不声称保留原始 stdout 字节、错误 stderr 或完整 MCP envelope。
- 原生查询只覆盖索引读阶段实际执行的 `search_graph`、定位查询及关系查询；MCP 协议协商已有独立 receipt。没有执行的查询、未请求的属性和未扫描范围保持未知，不据此宣称完整原生图。
- PG 与 MinIO 不是分布式事务。报告提交失败或 Worker 中断可能留下私有未引用工件；保留政策、GC、备份恢复和强杀清扫仍属未完成 P6。

同一内容重复归档返回同一引用；重建的原生项目标识、响应顺序或分区 LIMIT 探针可以变化，此时形成新的观察报告，不改写旧记录。`code_projection_payload` 显式排除原生查询 envelope，维持原规范投影的九字段摘要契约；实体、关系、证据和 Provider 声明变化仍会触发 generation 投影冲突。原生观察字段不参与 CodeIntelligenceResult 的规范事实相等判断。

## 读取与界面

原有来源分析接口增加 `section=entities|relationships`，仍要求确切 source revision、当前项目和来源权限。实体可以按 kind 或 exact/ambiguous/unresolved 筛选；关系可以按四种规范类型筛选。每页最多 100 项、64 KiB，先授权、核验完整私有工件，再分页，返回前再次检查权限。

公开响应不包含归档地址、evidence_refs、原生请求/响应或私有 Worker 路径。没有原生查询正文的公开 section，也不自动向模型发送这些原生资料。工件丢失/损坏返回脱敏 502；授权撤回或 scope 改变不返回旧正文。历史分析 v1/v2 没有观察工件时，实体/关系读取返回 404，不以空列表假称已完整检查或自动重跑 Provider。

Portal 来源分析面板的“实体观察”“关系观察”只显示规范投影，沿用深浅色、390px 移动适配和隐藏滚动条。身份 matched 不表示成员已准入；Provider 分数明确未校准，关系不代表实现正确或测试覆盖。

## exweb 验证

固定干净提交 `fe5827f6b76f77ef34918d8b452ee823142332dc` 的真实 CBM CLI/MCP、Temporal、PostgreSQL 和私有 MinIO 在 Tool 与 Agent 两入口各经历一次故障重试：原命令和确认未改变，epoch 从 1 到 2，历史重放不再调用 Provider。每轮规范 Provider 为 755 实体/1425 关系；组合后的 received 投影为 942 实体/2346 关系，725 个 exact 与 217 个 unresolved 身份。正式画像仍只准入 725 个 canonical 代码成员，并独立回读 751 处来源证据跨度。

每份原生观察归档实际保存 25 次查询（3 search、22 query），含 `DEFINES`、`DEFINES_METHOD`、`IMPORTS`、`CALLS`、`HANDLES`、`USAGE`、`INHERITS`、`WRITES`、`SEMANTICALLY_RELATED` 和 `SIMILAR_TO`。原始行计数包含被拆分父分区的探针，不是去重全图边数；观察响应发生变化不影响固定规范投影一致性。故障前后两份报告分别保留，不覆盖或拼成一次调用。

该验证不执行 exweb、不安装目标依赖、不调用 Nasus 外部语义模型，不是运行依赖解析、真实业务语义准确率或独立 gold。全量权限/隔离、完整原生属性和图导出、候选完成交付、动态调查、持续更新、五用途闭环及最终 V1 门禁继续待交付。各验证命令、结果和告警见实施记录。
