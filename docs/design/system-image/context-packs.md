# 固定测试设计上下文包

更新：2026-10-07。0051 上下文归档、0052 业务规则 authority、v4 发布绑定及 v5 固定检索回放已接入，后续新生成链另行消费固定 context/scope。它是完整 P5 的底座，不是 P5 验收完成，也不取代[用途契约](./knowledge-contracts.md#5-用途上下文包)。

## 输入、权威与预算

`test_design` 编译绑定 `project_id / image_revision_id / image_artifact_hash / policy_revision / max_tokens / candidate_limit`。当前范围是所选画像中的全部来源 AC 与业务规则，不用检索 top-k 决定强制项。来源 AC 通过 quality_loop application port 查询独立批准版本，保留完整源字段、证据引用与四项 observable oracle；v3 也通过独立[业务规则批准](./business-rule-authority.md)端口读取固定批准。未批准或已撤回约束保留为 gap，不从代码补造预期。v1/v2 仍按原契约将规则视为未批准，保持旧 hash 与回放兼容。

每条 AC 的代码与历史用例支持材料来自 `nasus.link-recall.reviewed.v2`，先排除适用的人工否定，再选择候选。候选的 `retrieval_candidate_not_coverage` 标签不可晋级为实现正确、业务批准或测试覆盖。固定完整召回 receipt、审阅头及原文证据集合，以便历史重放。已接受关联也不自动证明它符合后来人工修改的 oracle。

预算首先保留完整强制项，再以整项方式加入可选候选。`max_tokens` 是兼容预留名，**实际测量 canonical JSON 的 UTF-8 字节**，返回 `utf8_bytes_upper_bound_not_provider_token_count`，不是 provider tokenizer。每关系最多 10 个候选，完整私有工件最多 1 MiB；容量超限不提交部分结果。

### v2 强制约束拆包

原 v2 与新 v3 使用相同完整约束分组算法。Portal 现在明确发送 `policy_revision=nasus.test-design-context.v3`。API/Tool 不带策略时仍按 v1 解析，旧 canonical 命令、32 项单包语义和历史 hash 不变，不自动升级旧工件。

- v2 最多 256 项完整约束，返回 `nasus.context-bundle.v1`。根清单包含全部约束和被子包保留的候选，**根清单不是单次模型输入**。预算 `scope=per_part`，`used_upper_bound` 为最大子包字节数，`total_upper_bound` 为子包字节总和，不包含外层索引和模型协议开销。
- 按固定 object ID 顺序贪心分组，完整 AC 恰好进入一个子包。尚无批准的规则局部适用范围，因此保守地把全部来源业务规则复制到每个子包；不会用 top-k 删除规则。v3 只有明确独立批准的规则才有 expected oracle，这仍不构成完整风险矩阵。
- 子包固定画像/manifest/policy、目标 AC 与全局规则 ID、完整原文/authority/oracle、readiness 和支持候选。`part_id` 是子包 canonical JSON hash；字节预算包括 Unicode 和预算字段自身。先保留 mandatory，再加入整项可选证据。
- 单个 AC 加全部全局规则仍超限时，整次预览/归档拒绝并要求提高预算，不返回部分可用包。更改策略/预算改变 input digest，原确认不可复用。空要求仍 blocked。
- 子包与 Derivation 一起保存为一个私有工件，PG 摘要与 Outbox 仍原子提交。历史重放重建全部分组；撤回 authority 不改写旧包。Portal 显示分组和预算，并验证全局规则完整继承、AC 恰好一次、候选并集及预算汇总。

新召回一次返回内容和回执；历史读取仍独立展开固定回执。画像字节只在一次 compilation/recheck/replay 内复用，最多两份、返回副本，每次仍读取 registry/membership 并检查当前 ACL。复用键包含 actor/fingerprint/epoch 与画像元数据；提交复核开启新会话。不缓存权限、批准或审阅决定。

AC／规则原文检查、上下文来源编译和候选召回显式使用 `reuse=True`，复用外层编译已核验的不可变画像，不为每个强制约束或候选重新开启快照。没有外层作用域时仍创建并关闭独立会话；底层不带 `reuse=True` 的显式会话继续独立。异常退出恢复外层，最外层退出关闭自己的只读连接。批准历史、规范工件与实时权限不进入此画像缓存；同一会话中的 AC 撤回、来源撤权及账号切换仍重新检查。

### v4 发布绑定

`nasus.test-design-context.v4` 必须显式携带 `publication_id`，与 image revision/hash 一起成为 canonical 请求和 input digest 的组成部分。不自动选择最新发布、不把 review/approval ID 当成 publication，也不把同一画像在另一个 baseline 的发布混入当前目标。发布记录只经 application port 读取，ContextPack 不直接访问 publication ORM。

- 预览前后及事务提交复核检查该 publication 仍是它所属 baseline 的当前 head，同时核对 image/hash/manifest。Official 更新不会使另一个仍固定旧画像的 version-working 包失效；即使重发同一画像，相同 baseline 的新 publication 也要求重新预览。
- `publication_pin` 固定 publication、baseline、image/hash、manifest/hash 和 sequence，写入根上下文、每个预算子包及 Derivation。子包字节预算包括这些字段，前端校验父子 pin 一致。
- 历史回放验证原不可变 publication，不拿当前 head 替换原输入。head 变更后原包仍可按授权读取，`current_use.stale=true / reason=published_image_head_changed`；同 invocation 恢复返回原包，不重复归档或推进 head。缺失/损坏的原 publication 或撤权仍拒绝返回内容，不能仅标 stale 后放行。
- v4 去掉不真实的 `image_not_published` 缺口，但保留缺 oracle、风险/冲突、真实混合检索、模型预算等限制。知识发布不赋予生成、执行或 release 权限，`generation_authorized` 仍为 false。
- v1-v3 不新增序列化字段，不接受 publication ID，历史 input hash、工件字节与 readiness 不自动升级。工作草稿调查入口继续显式 v3；知识页的已发布上下文入口显式 v4。两个入口共享原有深浅色/移动端组件，错误或 pin 不一致清除旧内容。

来源授权的每次 `scope/require_current` 现在通过一个 PostgreSQL MVCC statement 同时读取项目存在性、当前项目级成员角色、来源 inventory、policy head 和 ACL epoch。角色来自持久成员记录，不来自账号的项目角色标签；版本/会话级成员不能替代项目级成员。管理员身份仍由可信 request/worker actor 提供。每次检查重新查询，跨请求不保留授权结果；项目成员撤回、降权或来源变化仍使旧 scope 失效。

### v5 固定检索回放

`nasus.test-design-context.v5` 显式要求 publication 和 `retrieval_bindings`（来源 AC object ID 到已有 retrieval ID 的映射）。全部来源 AC 恰好各有一个选择，不允许漏掉强制 AC、加入另一个画像的目标，或因 top-k 缩小需求范围。规则继续全局继承，没有 AC 时只接受空映射，且仍保持缺需求 blocked。GET preview 通过 JSON 编码的 `retrieval_bindings` 查询参数传入，重复键/非法值拒绝；canonical query/compile 使用 JSON 对象。其他策略不能携带非空检索映射，不改变 v1-v4 序列化和旧工件。

- 检索先在已有索引查询链独立执行并归档；ContextPack 只经 `ContextRetrievalReplayPort` 消费 trace，不知道 ORM、provider 或对象存储。预览、提交锁内复核、同命令恢复及历史读取均不调用 embedding/rerank/chat，也不自动刷新查询。单次推导内复用同 ID trace，下一次推导重新验证。
- trace 必须属于相同 publication、画像/hash，原 generation、输入、模型、query hash 和工件均重新校验。默认仍仅原查询者或项目管理员可读取 private trace；ContextPack 不绕过该规则。撤权或原始工件损坏拒绝返回，不降级为旧词法结果。
- 使用完整归档的**有界候选池**，而不是 search 返回的最终 top-N。候选逐个核对 code/document revision、source revision、binding 和 evidence membership，然后按关系选择代码或带预期结果的测试。按对象去重，以第二层确定性 RRF（trace 顺序 0.7、AC 词法/显式引用顺序 0.3、k=60）合并，再对合并后的全部候选执行人工否定筛选，最后截取 `candidate_limit`。
- `nasus.link-recall.indexed-reviewed.v3` receipt 固定 trace/index 工件哈希、query/model 摘要、完整排名摘要、结果摘要及审阅头（包括空集合）。历史重放只使用这些头，新否定影响新预览/current_use，不改写旧包。候选始终是 `retrieval_candidate_not_coverage`，不新增 approved oracle、关联或 coverage。
- 当前使用检查固定 embedding 配置是否仍一致；变更或不可用时需重新检索/预览。原包可在授权及完整性验证通过后读取，标记 `retrieval_model_configuration_changed`，不发送请求到替换后的模型。新 publication 仍使用 v4 的 head 失效规则。
- trace 可能未包含整个索引，保守传播 `truncated`；provider 曾回退到 FTS 时保留 `fallback_used=true`，不会把回放变成成功向量调用。显式 AC/query 选择只是调用者选择，不证明查询相关性。未实现图扩展、rerank、完整召回率/gold 和大规模性能，readiness 明示这些限制，仍不得用于正式生成/执行授权。

Portal 可以读取 v5 与旧策略混合的历史列表及新失效原因，沿用共享上下文组件与中英文提示；不带映射的发布预览入口仍显式 v4。索引面板现已支持完整 AC 查询预算预览、独立确认的 Temporal 批次执行、刷新恢复和取消，完成后自动将完整 trace 映射传入共享面板，使用 v5 预览/归档，详见[AC 查询持久执行](./versioned-retrieval.md#ac-查询持久执行)。ContextPack 本身仍不发起模型调用，查询完成也不是正式生成许可。0058–0065 已在独立质量用例中实现固定 context/scope 的草稿与 planned coverage 原子归档、受控原生生成及恢复；五种用途统一编排和旧链切换尚未交付。

## 持久化与一致性

- 0075 的[规范依赖登记](./context-authority-dependencies.md)随新归档保存原 AC／规则版本及画像成员的完整类型化 pins。旧包只登记迁移待处理清单，必须独立确认、重新授权并回读原 archive 才能补登记；缺历史登记返回明确 409，损坏的新登记返回 502，普通读取／事件不能自动修复。原 context 字节、oracle 和摘要保持不变。
- PostgreSQL `system_image_context_packs` 只存摘要、作用域、canonical invocation 与私有工件引用。表为追加式，更新/删除由数据库触发器拒绝；有数据时 migration downgrade 拒绝运行。
- 内容及 Derivation（完整请求、authority pins、检索 receipts、证据选取）按内容 hash 存在私有 MinIO。不能通过任意对象 URL 读取；回读重建固定依赖并核对内容与输入摘要。SSE / ToolResult 不携带来源正文。
- `system_image.context.compile` 必须经过 ToolInvocationRuntime 用户确认。事务再次核对 running canonical payload、actor、会话/goal/project、画像 digest，并在共享项目锁内重验 authority、负向审阅与来源 ACL。元数据和 Outbox 同事务提交。
- 同 invocation 顺序或并发恢复返回同一份原工件，不重复新增业务记录或事件。恢复也要通过当前权限及固定请求校验；归档后撤回 AC 不会让重试重新激活它。
- 首次提交已经在项目锁内重新推导当前输入，返回前校验私有工件的完整派生摘要与该输入，不再第三次遍历来源。恢复和之后的历史 GET 仍独立重放固定依赖，不能用首次提交的内存值替代历史完整性检查。
- 历史读取保留原 oracle，另外计算 `current_use.stale`。当前 oracle 变大以至原预算无法容纳时，仍允许授权用户读取完整历史，但明确 stale；权限或完整性失败不会降级返回旧正文。这里的“输入未变”仅针对固定画像及其依赖，不意味着当前分支已发布、最新来源已同步或生成授权有效。
- 预写 MinIO 与 PG 不构成分布式事务，失败/竞争可能留下未引用工件；保留与 GC 属于尚未完成的 P6，不能假称 exactly-once 对象写入。

## 调用与界面

公开只读入口：

- `GET /v1/projects/{project_id}/system-image/context-packs/preview`：固定画像预览，返回 input digest、强制约束、支持候选及缺口。
- `GET /v1/projects/{project_id}/system-image/context-packs`：固定画像的无正文历史摘要，按 context ID 游标分页，非时间排序或冻结列表快照。
- `GET /v1/projects/{project_id}/system-image/context-packs/{context_id}`：重新授权的历史内容和当前失效提示。

Agent 同样可用 `query.system_image.context.preview/list/read`。观察端口复核 canonical query 和当前权限，只向 Planner 暴露摘要；preview/list 是需重新校验的观察，read 是历史观察，均不是执行许可。正式归档只使用 `system_image.context.compile`，没有旁路 HTTP 写入口。

Portal 入口是项目 Knowledge → Image revisions → Inspect test-design context。领域 API/hook 负责 scope、schema、authority/候选语义及错误检查；route 只渲染。只有预览后才能确认归档，编辑预算或重新读取会使旧确认失效；提交不自动重试，未收到回执时先查历史。刷新页面可按固定画像重新打开归档；来源证据复用原有按需授权阅读器。撤权、错画像或完整性错误隐藏整份旧敏感视图，深浅色、移动端与隐藏滚动条继续沿用共享样式。

## 未完成的闭环

本切片明确返回 `generation_authorized=false` 和 `draft_investigation_only`；缺独立 oracle 为 blocked，其他情况最多 partial。v4 已绑定正式画像 head。0057 新增独立的[测试设计范围审阅](./test-design-scope.md)，固定风险/权限/状态/不变量/正反例及显式冲突/gap；原包保持不变，不把后来审阅状态回写到旧工件。0058–0065 的[新生成链](./test-design-generation.md)已消费固定范围，另行执行模型输入预算、显式授权、原生调用和完整结果提交；不能把 ContextPack 归档或范围审阅本身当成生成许可。完整 BehaviorSpec、自动冲突发现、真实模型/gold 和调查全计划预算仍未齐备。

既有 quality generation 仍读取可变 TaskContext，旧消费者切换未完成。新链已固定 context/scope、模型配置、输入/累计预算，并校验完整用例/计划覆盖，提交前重验 authority/ACL；0058/0064/0065 的结果、用例、coverage 与调用 provenance 在同一 PG 事务归档。0061/0066 的[独立断言映射](./test-design-mapping.md)不改写原草稿，也不把 planned coverage 升级为执行通过；实际容量/性能及完整验证边界见[实施记录](./implementation-progress.md)。其余 `us_design / automation / execution / release` 四种用途、RunPlan 与目标 build pin、真实受控运行及证据反馈仍是本目标必须交付的内容。exweb 只作已授权的静态解析；配套需求/用例与 reviewer 是明确测试夹具，不是其维护者批准、真实执行结果或独立 gold。
