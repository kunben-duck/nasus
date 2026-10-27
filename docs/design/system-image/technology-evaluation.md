# 系统画像开源能力评估

研究日期：2026-09-09。原研究是设计选型而非性能实测，当时未安装软件、上传项目代码或更改 Provider。2026-10-08 新增[CodeGraph 1.6.2 公开 SDK 与 exweb 同源对照](./codegraph-provider-comparison.md)，是独立的后续实施证据，不改写原研究快照，也不切换生产默认 Provider。关注代码理解、文档结构化、演进知识与 Agent 编排的代表性方案，不声称列尽所有开源项目。

## 1. 选择方法

选择依据是能否支持 Nasus 的三源关联和版本证据链，而不是 stars、语言数量或供应商自报的 token 降幅。必须分别回答：

- 是否能对固定 commit 提供可定位的实体、关系及完整性信息？
- 是否可通过公开且可测试的 CLI/API/MCP 契约使用，而无需读写内部数据库？
- 自动更新能否受 Nasus manifest 控制，不能后台改变历史基线？
- 多项目隔离、数据出口、资源限制、许可证、升级兼容如何验证？
- 它解决的是结构索引、业务断言、证据治理还是上下文召回？不得将其中一种能力误当完整系统画像。

## 2. 候选与适用边界

| 方案 | 从官方来源核实的能力 | Nasus 选择及理由 |
| --- | --- | --- |
| Codebase Memory MCP | 代码实体/调用/路由图、结构检索、公开 CLI/MCP；CLI 与长期 watcher/daemon 的生命周期不同 | 优先验证的代码结构 adapter，利用已有接入基础；不托管需求权威、测试 oracle 或正式 baseline |
| CodeGraph | 代码图和文件变化同步；公开 query/callers/impact；affected 根据 import 依赖寻找受影响测试文件 | 第二候选。affected 可辅助回归候选，不能替代 AC 覆盖；与 CBM 在同一质量语料比较后才决定替换 |
| SCIP | 定义语言工具互操作的代码索引协议 | 作为精确符号/引用增强输入；不是带摄入、业务关联、治理的完整知识平台 |
| Graphiti | 时间化事实、来源追踪、增量图与历史查询 | 借鉴时态/溯源模型；目前官方部署需额外图后端，暂不引入为 PG 之外第二业务事实源 |
| Microsoft GraphRAG | 基于图和社区摘要的局部/全局等查询模式 | 借鉴分层摘要和全局探索；不把摘要当可执行 oracle，不让批量摘要重算阻塞代码 delta |
| LightRAG | 实体/关系与文本检索结合的 RAG 方案 | 作为后续 RetrievalPort 实现候选；不在当前已有 PG FTS/pgvector 链旁再加一套主索引 |
| Docling | 多格式解析、PDF 布局/表格、OCR、可结构化导出和本地运行 | 复杂 PDF/DOCX 表格摄入候选，接 DocumentUnderstandingPort；简单 Markdown 沿用轻量解析 |
| LangGraph + Temporal | checkpoint/persistence 与持久化任务执行机制 | 继续复用当前组合；Agent 可恢复编排与画像事实分离，不再加第二 Agent 框架 |

资料：[CBM](https://github.com/DeusData/codebase-memory-mcp)、[CodeGraph](https://github.com/colbymchenry/codegraph)、[SCIP](https://github.com/scip-code/scip)、[Graphiti](https://github.com/getzep/graphiti)、[GraphRAG 查询概览](https://microsoft.github.io/graphrag/query/overview/)、[LightRAG](https://github.com/HKUDS/LightRAG)、[Docling](https://github.com/docling-project/docling)、[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)。上表“Nasus 选择”是本方案判断，不是供应商承诺。

证据记录另外借鉴 W3C PROV 的 Entity/Activity/Agent 及派生关系思想，但使用 PG 类型化模型，不因此引入 RDF/SPARQL 服务。[PROV-O](https://www.w3.org/TR/prov-o/)

## 3. Codebase Memory 与 CodeGraph 的具体决策

### 3.1 研究快照

GitHub API 在本次研究时返回的 main commit：

- CBM：`161df2bdb1f4e28734f326a73f6e7989418f1288`，2026-09-08。[固定 README](https://github.com/DeusData/codebase-memory-mcp/blob/161df2bdb1f4e28734f326a73f6e7989418f1288/README.md)
- CodeGraph：`8c047342cdcb86e0ad4793b3d503eba19793cb02`，2026-09-08。[固定 README](https://github.com/colbymchenry/codegraph/blob/8c047342cdcb86e0ad4793b3d503eba19793cb02/README.md)

这两个 SHA 是可复查的研究依据，**不是经过 Nasus 验证的发布版本**。实施 P0 应选择与之对应或更新的正式 release，记录版本、制品 digest、协议版本和兼容报告。不得在设计文档里凭空指定未经运行验证的二进制为稳定版本。

### 3.2 运维约束影响设计

CBM README 描述账户级 exact-build/cache 协调约束以及独立的一次性 CLI。Nasus 应把它放在隔离 Worker 中、显式驱动索引，不能把不同缓存目录视为完整租户隔离，也不能让默认 watcher 决定业务版本。[固定 README 的运行约定](https://github.com/DeusData/codebase-memory-mcp/blob/161df2bdb1f4e28734f326a73f6e7989418f1288/README.md#session-coordination-daemon)

CodeGraph 官方提供关闭 telemetry 和更新检查的设置。生产候选配置必须禁用这两类后台出口，并通过网络隔离测试，而非仅依赖 README 的“local”措辞。[固定 Telemetry 文档](https://github.com/colbymchenry/codegraph/blob/8c047342cdcb86e0ad4793b3d503eba19793cb02/TELEMETRY.md)

两个项目根 LICENSE 均为 MIT，本次已通过固定 commit 的 GitHub Contents API 核对。发布前仍要审查制品内的第三方 grammar、模型、runtime 和 NOTICE；根许可证不代表所有附带资产适用同一条款。[CBM LICENSE](https://github.com/DeusData/codebase-memory-mcp/blob/161df2bdb1f4e28734f326a73f6e7989418f1288/LICENSE)、[CodeGraph LICENSE](https://github.com/colbymchenry/codegraph/blob/8c047342cdcb86e0ad4793b3d503eba19793cb02/LICENSE)

### 3.3 默认方案不是永久绑定

首选 CBM 的原因是本地已有 `CodebaseMemoryCodeIntelligenceAdapter`、公开 CLI 接入与 contract gate，迁移成本更低；不是已经证明其准确性优于 CodeGraph。保留 CodeGraph 的评估通道，必要时整个项目按 provider policy 切换，而非同一修订随机混合两个图。

业务身份、来源快照、三源关联、审阅、上下文契约均由 Nasus 定义；替换只改 adapter + mapping + 重建投影。验证替换成功必须比较同一代码 snapshot 的 Nasus ID、证据可定位率、typed relation、下游回归集合，不以“API 返回 200”验收。

2026-10-08 的公开 SDK 适配已在固定 exweb 语料验证规范 UUID 复用、两个项目身份隔离、真实 PG/MinIO 证据与本机所属进程组取消。原始 CBM 投影仍发现 Java import 目标非确定性，既有生产准入后稳定；原始失败保留，不用筛选后的稳定性宣称 Provider 全绿。节点交集和数量不是质量 gold，完整多修订／语言、准确率、资源隔离与下游收益仍未验收。

开源 provider 必须通过三层门禁：协议兼容、实际语言/仓库的结构质量、多版本与隔离。任一关键门禁失败就不能晋级。当前 Tree-sitter 路径可继续服务已支持语言的结构模式，但显式标记能力缺口，不以静默 fallback 宣称完成自主业务画像。

## 4. 不引入完整 Graphiti/GraphRAG 平台的理由

Nasus 的关键问题是“哪个批准 AC 在哪个代码版本被哪条断言验证”，而非仅回答语义问题。时间图和图检索有帮助，却不能自动获得产品批准、环境安全策略和测试 oracle。叠加完整框架容易形成双重对象身份、双重失效机制和多个事实源。

因此先使用这些方案中经过验证的**模式**：时间/来源维度、实体解析、分层摘要、混合检索；只有 P0/P5 评估表明现有投影不足且适配器成本可接受，才引入具体引擎。此判断由 Nasus 约束推导，不是对这些项目通用能力的否定。

若日后引入 Graphiti，仅作为候选语义事实生成器或索引 adapter，输出仍需经过 Nasus Assertion/LinkDecision 门禁，不能接管 Official head。若引入 GraphRAG/LightRAG，摘要和索引必须 pin ImageRevision，必须支持删除和权限失效传播。

## 5. 复用范围与禁止重复建设

| 直接复用/适配 | Nasus 必须拥有 | 暂不建设 |
| --- | --- | --- |
| 代码 parser、符号/调用图、代码搜索 | SourceManifest、ID registry、三源质量语义与证据 | 新的通用代码搜索平台 |
| 成熟文档转换、OCR 和结构导出 | AC/规则抽取 schema、原文定位校验、审批 | 自研 PDF/OCR 引擎 |
| PG/pgvector、已有 rerank route | 上下文用途约束、分母、强制规则、版本/ACL | 同时引入多个生产图/向量数据库 |
| 已有 LangGraph/Temporal runtime | BuildIntent/InvestigationPlan、预算和完成门禁 | 第二套 Agent orchestrator |

Graphiti/Docling 等当前文档存在 Python >=3.10 的运行要求；本地 API 依赖仍固定 `langgraph==0.6.11` 和 checkpoint 2.0.25。可选处理器采用独立版本化 worker，或另立 Python 升级任务，不能为了方案引用顺带破坏现有依赖环境。[Graphiti 安装要求](https://github.com/getzep/graphiti#installation)、[Docling 安装要求](https://github.com/docling-project/docling#quickstart)

## 6. 尚须实测的决策门

- CBM/CodeGraph 固定发布版本在 Python/TS/Java/Go 真实 fixture 上的实体、调用、动态 dispatch、API 定位准确率。
- 增删、rename、branch 切换、force-push、截断和权限撤销是否产生正确失效结果。
- 两项目/两 revision 并发、进程取消/重试、缓存损坏后的隔离与恢复。
- 中文 US、表格用例、无显式 ID 的关联质量，不能从代码语言覆盖推断文档理解质量。
- 端到端相比当前名称关联/检索基线，是否减少漏掉的关键 AC、幻觉 oracle 和不可运行脚本。

这些仍是完整实现/PoC 的交付门禁。原研究只有设计证据；后续单语料 SDK 试验见上述独立记录，不虚构 benchmark 分数或宣称全部门禁完成。具体语料、指标和通过条件见[开发与验收方案](./delivery-and-evaluation.md)。
