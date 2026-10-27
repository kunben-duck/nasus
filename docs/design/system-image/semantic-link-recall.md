# 固定 AC 的关联候选召回

状态：2026-09-17 已实现字面/显式引用召回、版本化历史审阅筛选与证据检查入口。此能力是 P3 语义流水线的输入，不是完整语义判定、向量检索、批准规范或覆盖率计算的替代。

## 审阅筛选 v2

新工作使用 `query.system_image.links.screened_candidates`，固定方法 `nasus.link-recall.reviewed.v2`。Portal 和 Agent 工具发现已接入；原始 `query.system_image.links.candidates` / lexical v1 保留原排序、结果与历史摘要，供兼容回放和原始诊断使用。

- 在完整的有界 lexical 匹配集上按 project/predicate/binding/entity/kind 查询历史 claim 头，核验其固定证据和适用性，然后排除相同修订的 reject、未解决身份及端点不匹配，最后才取前 N 条。不能先取 N 条再排除而漏掉后续候选。最多 10,000 个匹配主体、64 个命中头；超限失败，不能丢弃负向头后继续。
- 来源修订改变的稳定身份保留为 `requires_revalidation`；旧 accept/defer 为 `reviewed_not_approved`；无历史为 `unreviewed`。任一适用拒绝优先于其它 claim 的接受。三个状态均不是批准、覆盖率或 oracle 验证。
- `eligible_count` 是满足来源字段条件的端点数；`pre_review_matched_count` 是筛选前 lexical 匹配数；`matched_count` 是筛选后数量；`excluded.historical_review` 为被排除的唯一主体数，不是头数。`truncated` 仅表示筛选后的结果超过 limit。沿用原证据和响应预算，不伪造向量/结构召回。
- 回执固定全部命中头 ID/digest（包括未进入前 N 的主体）、review scope digest、目标/返回候选 pins、排除数及结果 hash，不含正文。`review_scope=pinned_query_heads_not_live`：空头也明确固定为空；回放不发现后来新增的头。新查询会获取最新头，前端明确提示重新查找以刷新。当前项目/来源权限和完整性仍需验证。

## 筛选结果进入模型

`SemanticSelection.recall_invocation_id` 可指向 canonical v2 完成回执。新预览/评估先展开核验回执，再核对 project/image/hash/target/relation/limit 和选中主体归属；由此允许选择原始前 N 之外、筛选后补入的候选。缺少此字段的旧请求继续使用 v1，并不获得绕过模型入口审阅检查的权限。

输入摘要固定完整回执的规范化 JSON 摘要，而非只绑定返回 ID 或活动头。模型入口另查当前头并固定独立 `review_scope_digest`，因此历史召回仍可显示原候选，但不能用它绕过后来新增的拒绝。所有新评估仍需原权限、单次出口预览与显式确认。

归档评估读取校验 canonical 调用/请求/完成状态、整个回执摘要，以及选中端点的完整原文与输入摘要，不再递归展开该召回的历史头。否则每个头会递归读取旧评估和更早的召回，形成不断增长的历史依赖链。首次模型准入已完整验证回执；归档不可变输入 digest 绑定其全部元数据，篡改任一字段仍会导致旧评估校验失败。此路径仅重建归档输入，不授权新的模型调用，也不返回未经展开的历史审阅正文。

## 契约

- Canonical 工具 `query.system_image.links.candidates` 使用现有 ToolInvocationRuntime、RBAC、审计和来源权限。输入固定 `project_id / image_revision_id / target_object_id / relation`，`limit` 默认 30、最多 100；方法固定为 `nasus.link-recall.lexical.v1`。没有当前 head、provider 节点 ID 或任意路径入口。
- `implements` 查询目标必须是独立的 source AC 或业务规则修订，候选是同画像的 code entity；`asserts` 查询目标仅限独立 AC，候选仅限有非空 `expected_result` 字段及固定证据的来源测试用例。缺少预期字段的用例计入 `missing_expected_result`，不通过标题/引用补造 oracle。
- 目标 AC/规则固定父需求修订，查询使用自己的字段及父需求 description 作为消歧上下文，不用其他兄弟 AC 的文本替它作证。当前 source specification 一律 `pending_confirmation`；历史导入不等于质量闭环正式规范。
- 字面通道采用 NFKC、CamelCase 拆分、英文停用词和 CJK 双字片段，匹配词按语料文档频率加权。US/REQ/AC/BR/RULE/TC 标识不作为普通语义词，父需求显式引用是独立的召回信号。只读冻结符号/路径标签和文档字段，不调用 provider、LLM 或执行目标代码。候选只因引用召回也是允许的，但不是语义判断。
- `retrieval_score` 是相对检索分数，不是关联可信概率。`calibrated_probability=null`、`status=retrieved_not_asserted`；不会写 Assertion/Decision/ImageRevision 或更新覆盖指标。无匹配保持空结果，不凑足 K 条，也不宣称实现/测试不存在。

## 原文与重放

- 候选返回 Nasus object/revision/source revision、内容摘要及固定 evidence IDs。测试侧 evidence IDs 必须定位到预期结果字段，目标侧必须定位到 AC/规则字段；代码侧仅使用该画像已冻结的原文证据。
- 查询核验选中原文文件和 snippet hash。批量核验在一次请求内复用已验证的画像，不跨请求/账号缓存授权或原文；每个原文读取仍校验范围与当前来源权限。撤权、损坏、非冻结证据均失败，不返回部分成功候选。
- POST 的 `image_query` 回执只含 ID、修订、摘要、方法、选择参数和截断状态，不保存名称、匹配词、文档字段、源码或 S3 地址。`GET /v1/tool-invocations/{id}/image-query` 再鉴权并重算结果摘要。后续摄入、工作区文件删除不会改变旧回执；权限撤回会阻止展开。
- Agent 使用相同工具与 observation port。默认 Planner 只收到重新鉴权的无正文回执；不会因召回而隐式向外部模型发送源码。新的召回方法须新增版本并保留旧版本重放，而非更改 v1 的排序规则。

## 预算与页面

- 单次画像最多 10,000 个代码成员、1,000 个文档成员；分页读取文档总计最多 8 MiB。单条排序文本最多 65,536 字符，总排序文本最多 8 Mi 字符；证据核验最多 512 个范围。超限直接失败，不静默漏读输入。
- 返回 `eligible_count / matched_count / excluded / truncated`。候选只按 limit 截断，响应与回执各有 64 KiB 上限；过大需降低 limit。响应明确 `vector_recall_not_run / structural_recall_not_run / semantic_judgment_required / source_specification_not_approved / no_runtime_evidence`。
- Knowledge 固定画像的 AC/规则详情提供“查找相关代码”和 AC 专属“查找相关测试”。通过 canonical 工具获得回执，随后展开；支持扩大至 100 项、双方原文分页查看。只显示“尚未形成语义断言”，不把分数渲染成覆盖率或置信度。
- 前端 session/project/revision/目标修订隔离缓存，敏感读取不持久缓存、焦点恢复重验，失败关闭证据面板；保留既有深浅色、移动端和隐藏滚动条。

## 未完成的 P3 范围

此版本不冒充 hybrid retrieval 或语义知识图谱交付。已接入[固定证据输入、受控模型调用和 typed 结果归档](./semantic-link-judgment.md)、人工审阅与候选成员冻结。仍需结构及向量召回适配、真实模型/gold 验收、正式独立 `authority_ref`、完整冲突/readiness、可扩展的负向索引、跨版本重审和发布并发治理。正式规范归 quality_loop；system_image 保留不可变来源与证据，不另建可变需求主表。

exweb 只按固定 SHA 静态验证，伴随需求/用例是明确的测试 fixture；召回 ChatController 与 fixture 用例不证明业务行为正确，不执行 Maven 或目标依赖。完整 P0-P6 和发布门禁仍以主方案为准。

当前 exweb 字面结果会因共同的包路径词（例如 `finance`、`java`）匹配全部 546 个代码成员，再按分数取 30 个；并非 546 条实现关系。`ChatController.chatStream` 在实际返回中可定位，但共同路径词、fixture 说明文字以及语义歧义仍影响排序。此结果不满足独立 gold 的 recall/precision 门禁，后续召回版本必须用真实标注评估改进，不能将本次静态冒烟当作质量验收。
