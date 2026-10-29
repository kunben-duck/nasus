# 三项候选创新的技术实施方案

> 2026年10月29日，内部技术设计。对应[整体闭环方案](./closed-loop-invention-design-2026-10-29.md)中的三个机制。本文描述新增实现契约及其与现有代码的接点，不表示这些新增模块已实现或已通过产品测试。
>
> 本轮基于当前 `2026/nasus_art_v2` 工作树再次核对模块和数据约束；产品基线仍以整体方案记录的 `nasus_snapshot_v1@38e123c` 为准。

## 1. 实现架构和边界

本设计以最终态能力组织，不以当前已完成组件限定发明方案。系统画像必须支持函数变更到测试的影响传播、跨服务业务路径重建、关键路径验证缺口识别及有版本边界的高效召回；本节后续的现有代码接点只说明可复用基础。正式存储采用 PostgreSQL，完整证据使用既有 MinIO/S3；图数据库是可替换查询投影，并非实现这些能力的前提。

复用现有 PostgreSQL/SQLAlchemy 事实存储、对象工件归档、代码解析/检索、AgentGoal、工具运行时和 RunPlan 执行器。新增三个相互衔接的应用服务：

| 服务 | 输入 | 输出 | 所属域 |
| --- | --- | --- | --- |
| `VerifiabilityService` | 固定画像、批准验收条件、候选关系 | 关系验证规范、可验证性缺口 | system_image |
| `IterationCoordinator` 与 `EvidenceQualificationService` | 缺口、完整义务、工具能力、原始执行观察 | 行动、逐义务判定、准入评估 | agent / quality_loop |
| `ImagePatchService` | 来源差异、运行观察及判定、依赖图 | 画像补丁、新画像、失效/补验任务 | system_image，经端口调用 quality_loop |

前两者使画像和测试双向推进，第三者把本轮成果带入下一轮。模型只能通过受约束的工具协议提交候选；正式状态由领域规则和已批准策略处理。旧画像及旧 RunPlan 工件保持原格式和含义。

跨域通过 application port 和版本化事件交互，领域对象不直接读写另一个域的 repository。生命周期由现有 AgentGoal/工作流维护，新增契约是业务输入，不建立另一套竞争的任务主控制器。

## 2. 共用的数据契约

所有 pin 均至少包含项目、对象 ID、修订和工件摘要。完整 JSON 工件不可变归档，PostgreSQL 保存可索引字段、依赖、状态迁移和当前 head。哈希使用现有规范化摘要机制；摘要一致只证明绑定一致，不证明业务含义正确。

| 拟新增对象 | 最小字段 | 必须保持的约束 |
| --- | --- | --- |
| `RelationValidationSpec` | `spec_id, revision, spec_digest, claim_pin, endpoint_pins, relation_type, scope, required_observations, correlation_groups, support_condition, refute_condition, authority_pin, evaluator_version, approval_pin, review_state` | 模型提出的支持/反证条件不自动成为业务预期；批准绑定完整规范，条件在动作前固定 |
| `EvidenceGap` | `gap_lineage, revision, image_pin, contract_pin?, obligation_refs, claim_refs, missing_slots, closure_spec_pin, evidence_refs, state` | 缺少 contract 时可启动基础画像调查；需要正式执行时必须补齐契约 |
| `IterationContract` | `iteration_id, revision, image_pin, manifest_pin, scope_pin, obligation_set_digest, target_build_pin, environment_contract_pin, policy_pin, parent_contract_pin?` | 冻结后不可变；预算归原 Goal/iteration，契约修订不重置预算 |
| `ObligationBinding` | `lineage_id, obligation_revision, source_row_pin, authority_pin, oracle_pin, mandatory, weight, execution_requirement_tree` | 当前 row ID 含 scope 修订；lineage 是新增沿革映射，不授予跨版本通过资格 |
| `ActionProposal` | `action_id, kind, gap_refs, input_pins, tool_id, args, completion_spec, predicted_outcomes?, budget, risk_class, idempotency_key` | `completion_spec` 随动作类型校验，不能只写自然语言“完成分析” |
| `VerificationVerdict` | `verdict_id, contract_pin, obligation_revision, requirement_tree_digest, build_pin, execution_inventory_pin, inventory_epoch, observation_pins, exclusions, pending_attempts, evaluator_version, leaf_results, result, qualification_dependencies` | 从服务端完整执行库存和原始观察重算，不能由 Runner/模型直接提交 passed |
| `ImagePatch` | `patch_id, mode, base_image_pin, source_delta_pins, observation_pins, claim_changes, impact_snapshot, obligation_changes, qualification_revocations, dependency_projection_before, dependency_projection_after, required_checks, expected_head, digest, state` | 知识变化与结论适用性变化共同校验和提交；仅相关执行前提变化请求新契约 |

存储规则：

- 不复制现有来源、实体、用例和 RunPlan 为另一份可变主数据，只存它们的确切引用。
- 规范、契约、判定和补丁采用追加修订；可变 head 只在数据库条件事务中推进。
- 项目字段参与复合外键，阻止跨项目 pin 拼接。幂等键绑定原输入摘要；相同键不同请求直接拒绝。
- 义务权重必须为有限正数；必验性、表达式树和判据来自批准规范/范围，不能由模型执行后修改。
- 工件先归档并回读校验，再在数据库事务中保存事实、依赖登记和 Outbox；未引用工件后续按保留策略清理，不把对象存储写入当成业务提交。

## 3. 技术方案一：验证目标反向驱动画像构建

### 3.1 采集、解析与候选关联

1. 固定代码、需求、接口、测试资产的来源清单和修订；保存成功、失败、排除及不支持范围。
2. 代码通过现有结构分析器形成实体及调用/依赖候选；需求和测试保持原文定位。接口材料在现有文档来源绑定下增加 OpenAPI/事件契约格式适配器，不能只在提示词里假定已经支持接口语义解析。
3. 候选召回联合使用显式 ID、路由/事件/数据键、全文/向量和结构邻接。记录检索谓词、来源范围、索引/抽取器版本及空结果。
4. 调用现有语义评估服务，在固定端点范围内输出 `supports / contradicts / unrelated / unknown` 和双端引用。应用端核对引用与归档原文，保留候选状态。
5. 对关键关系编译验证规范，再检查能否服务于目标测试；缺槽产生 Gap。

现有语义评估入口只支持 `implements/asserts`，不能将新增类型塞入旧 schema。显式 `references` 继续复用原路径；`observed_interaction` 使用新增观察关系协议，并明确构建、输入和时间范围。

### 3.2 关系类型决定证据要求

| 关系 | 接纳所需证据 | 不允许推导的结论 |
| --- | --- | --- |
| `references` | 原文存在明确 ID 引用，目标身份唯一 | 不直接证明实现或验证覆盖 |
| `implements` | 两端原文、代码行为路径与验收条件的映射，必要独立审阅 | 不直接证明目标构建已经运行通过 |
| `asserts` | 已有独立预期、步骤/观察对象/断言映射 | 用例标题和需求文字相似不足以成立 |
| `observed_interaction` | 来自固定构建、隔离输入和完整观察窗口的请求/事件/trace | 一次观察不证明所有输入下必然发生 |

历史决定先按身份及端点/来源修订判断适用性，再进行候选截取。同修订否定继续排除，相关修订变化重新评估，身份歧义先解决。不得靠更换模型 invocation 或 context ID 绕过原决定。

### 3.3 将关系转换为可验证槽位

`assess_verifiability(image_pin, obligation_pins)` 对每个目标行为检查：

```text
trigger       触发动作、身份、输入及前置状态
expectation   独立批准预期及明确适用范围
observation   可读取对象、相关业务键、时间窗口和完整性条件
isolation     环境、fixture、清理及副作用边界
```

缺少预期形成 `missing_oracle`，需要权威输入；缺少观察路径形成 `missing_observation_path`，可由模型调查；缺少 fixture 形成 `missing_fixture`，可由工具补齐。类型/字段检查通过不意味着业务预期已经批准。

模型生成 `RelationValidationSpec` 候选，诊断条件和正式验收条件分别标记。正式条件必须能够追溯到批准预期及映射审阅；诊断条件只用于区分解释，不能直接作为通过标准。

映射批准绑定完整 `spec_digest`，包括权威修订、表达式树、观察字段、单位、窗口、关联分组、evaluator 版本及适用范围。`review_state` 由该批准记录派生，不接受模型或客户端直接设置。实质字段变化产生新规范修订并重新检查批准；诊断规范可按已批准诊断策略自动使用，但不能进入正式通过计算。

### 3.4 受限判据表达式

拟增加不执行任意代码的表达式解释器，支持 `all_of / any_of / eq / lte / count / sum / unique / eventually` 等注册操作符。操作数只能是批准字面量、固定 fixture 参数或允许的观察字段。金额使用最小货币单位或 Decimal，固定时区、比较规则和单位。不同语义版本使用不同 evaluator version。

编译时拒绝空的 `all_of/any_of`、未绑定叶子、单位不匹配及非法数值。`correlation_groups` 固定必须来自同一 fixture、业务键、执行批次和观察窗口的联合叶子，禁止拼接不同尝试的局部成功来满足一个整体判据。

例如批准的“同一退款事件重复回调，只记账一次”可转换为以下**示意性、待映射审阅**表达式：

```json
{
  "schema": "nasus.oracle-expression.v1",
  "authority_pin": "AC-refund-idempotency@D2",
  "scope": "both callback attempts completed for the isolated event",
  "op": "all_of",
  "children": [
    {"op": "eq", "left": {"count": "ledger_rows_for_event"}, "right": 1},
    {"op": "eq", "left": {"sum": "ledger_rows_for_event.amount_minor"}, "right_ref": "fixture.refund_amount_minor"}
  ],
  "required_observations": ["callback_completion_receipts", "complete_ledger_query"],
  "on_incomplete_observation": "unknown"
}
```

`ledger_rows_for_event` 必须来自固定业务键、完整分页、确定的事务/水位范围；不能仅凭查询空数组判零条。只有两个回调完成且账本观察有效时才能判断上述结果。观察范围之外的未来行为不由该测试证明。完整观察证实超过批准截止时间仍未满足条件时判失败；无法确认完成情况、观察服务失联或数据不完整时保持未知。

### 3.5 最终态：面向验证路径的多源关联模型

统一画像中的关系按语义分组，查询时使用有类型的传播规则，而不是无差别遍历所有连线：

| 关系组 | 实体与关系 | 证据和用途 |
| --- | --- | --- |
| 结构与调用 | 服务、模块、函数；`CONTAINS / CALLS`，保留 callsite | 解析器、符号解析及调用观察；定位调用者和被调用者 |
| 契约与跨服务交互 | 端点、接口契约、事件；`IMPLEMENTS_CONTRACT / CALLS_API / PUBLISHES / SUBSCRIBES` | 客户端代码、服务端声明、路由配置及 OpenAPI/事件 Schema；建立跨仓库边界 |
| 数据与状态 | 逻辑数据对象、字段、状态；`READS / WRITES / MAPS_FIELD / TRANSITIONS` | SQL/ORM/参数映射、数据流和运行观察；区分读、写、字段及状态条件 |
| 需求与验证 | 业务行为、验收条件、验证义务、用例、脚本、观察点；`REALIZES / ASSERTS / EXECUTES / OBSERVES` | 独立需求、步骤及断言映射；决定如何验证，关系存在不等于已通过 |

上述为目标协议中的逻辑关系，落地时版本化扩展当前 schema。业务关联和执行观察分别保存，不能把一次 trace 直接升级为无条件结构事实。

实体身份包含项目、来源绑定、命名空间及符号/契约标识。数据字段进一步绑定数据库/schema/表或消息类型及字段路径；接口包含服务身份、协议、方法、路由和契约修订。跨系统同名字段不能直接合并；rename/split/merge 使用显式沿革记录。

每条关系固定端点修订、来源修订、关系类型、方向、字段/调用点、前置条件、支持/反证证据和适用状态。大模型负责提出异名关联、字段映射和业务解释，结构及契约检查负责排除不成立的连接。纯语义候选用于调查和保守扩围，不能用于证明无影响或测试覆盖已完整。

### 3.6 PostgreSQL 存储与查询实现

以下是逻辑表族；适配器复用已有实体、画像和关系主记录，不另建重复的可变业务事实源：

| 表族 | 关键内容 |
| --- | --- |
| `entity_identity / entity_revision` | 稳定身份、来源修订、内容摘要和类型属性 |
| `edge_revision / edge_evidence` | 固定端点、谓词、条件、状态及依据 |
| `image_node_member / image_edge_member` | 某一画像采用哪些确切实体/关系修订 |
| `snapshot_edge` | 可重建的邻接查询投影，保留 `project, image, src, predicate, dst, edge_revision, applicability` |
| `query_scope / scope_dependency` | 查询定义、范围成员清单、索引代际及空召回依赖 |
| `behavior_path / path_obligation / case_obligation_binding` | 路径模板、分支及不变量、义务、资产和判据映射 |

常用过滤列单独存储，扩展属性采用 JSONB。`snapshot_edge` 分别建立 `(project, image, src, predicate, dst)`、`(project, image, dst, predicate, src)` 两个邻接索引。实体符号、路由、事件类型和数据字段建立精确索引；文本建立 GIN 索引，向量使用 pgvector。索引顺序按实际查询计划验证，不把任一固定索引配置当成性能保证。[PostgreSQL 多列索引](https://www.postgresql.org/docs/18/indexes-multicolumn.html)、[全文索引](https://www.postgresql.org/docs/18/textsearch-indexes.html)

正式修订追加存储并复用未变内容。热画像的邻接和业务摘要是可重建投影，可按项目及活跃版本分区、缓存。大范围遍历采用 frontier 批量查询，避免每个节点单独访问数据库；小范围可使用递归 CTE。只缓存常用服务/行为摘要及影响集合，不物化任意两点的全部路径。[递归查询](https://www.postgresql.org/docs/18/queries-with.html)

每份投影标记来源画像摘要、构建代际和完成状态；仅完整代际可用于声明“未发现关系”。新代际就绪后条件切换，旧版本仍可固定读取。新增索引不改变正式语义，缓存键包含画像、查询范围、策略、索引代际、访问范围，以及规范化 `query_input_digest`（包括 before/after 画像、变化/种子摘要、传播方向和字段范围）。缓存依赖 stamp 还保存来源/查询范围及权威/决定的 epoch；读取时重新授权并核对失效屏障，缓存命中不等于当前可用。

### 3.7 函数变更到测试的影响传播

同时读取变更前后的固定画像，通过身份映射识别新增、删除和修改的实体。删除函数从旧图寻找消费者；新增实体通过新图和查询范围依赖发现影响。不能只查询新图，否则删除的旧关系会丢失。

先从固定业务范围内的批准 AC/契约、风险政策和历史保护项独立枚举义务锚点，再利用图传播确定影响和补充路径场景。某项义务缺少实现/路径映射时产生 Gap；适用范围无法确定时扩大范围或阻断。不能因为关联缺失或新图删除了一条边就删除已有义务，移除义务必须有明确的批准修订依据。

按变化类型应用传播模板：

| 变化 | 传播方式 | 结果 |
| --- | --- | --- |
| 函数签名、返回值、异常或行为改变 | 反向 `CALLS` 到调用者，再沿契约/行为映射传播 | 受影响入口、业务行为及测试 |
| 字段写入、转换或状态迁移改变 | 对应 `WRITES(field)` 到 `READS(field)` 的消费者，保留转换和条件 | 依赖该字段或不变量的业务路径 |
| 接口或事件契约改变 | 客户端/服务端、发布者/订阅者及字段映射传播 | 跨服务兼容、异常、重试及一致性义务 |
| 需求预期、配置或权限改变 | 沿适用范围、正式预期和测试映射传播 | 判据重评、身份/配置场景和证据失效 |

数据读写只能精确到表时，扩大至该表消费者；仅在具备可靠分析依据时才按字段排除影响。反射、动态 SQL、运行配置或模糊身份形成未解析边界，不能被低相似度或缺少 trace 静默排除。

```text
analyze_change(before_image, after_image, change_set, policy):
  seeds = resolve_changed_entities_in_both_images(change_set)
  seeds += affected_query_scope_roots(change_set)
  frontier = typed_states_per_image(seeds, change_kinds, field_scopes)
  while frontier:
    batch = take_frontier_batch()
    neighbors = query_adjacencies_grouped_by_pinned_image(batch)
    transitions = apply_versioned_propagation_rules(neighbors)
    record_reasons_and_enqueue_unvisited_states(transitions)
    if unresolved_boundary_or_budget_exceeded:
      preserve_unfinished_frontier_and_expand_scope_or_block()
      return incomplete_result_with_pending_work()
  behaviors = resolve_impacted_behavior_obligations()
  return impact_set, explanation_paths, completeness_scope, unresolved_items
```

访问状态包含画像修订、实体修订、传播规则状态和字段范围。各画像内分别传播，再通过显式沿革映射合并受影响身份；解释路径保留原画像，不能混接新旧关系伪造一条执行路径。先求受影响集合，再选择有限解释路径展示；展示截取不删受影响对象。循环可用访问集合及强连通分量处理，分量内部的循环、重试和幂等义务仍保留。终止条件是政策限定范围内待处理状态耗尽；超限返回不完整及未处理 frontier，不声明全程序精确分析或最小回归集。

范围内遍历完成仅证明已登记关系在该规则下被处理，不证明真实系统的所有依赖已采集。来源采集完整性、解析覆盖、动态边界和义务来源分别记录；未知关系仍可能导致保守扩围或阻断。

### 3.8 跨服务路径、验证缺口与生成输入

从批准业务行为或受影响入口出发，将服务入口、契约调用、事件传递、数据读写及目标业务状态组成路径模板。静态路径保留分支条件；运行轨迹按构建、服务实例、trace/span、event ID、业务键和时间窗口佐证。时间相邻或名称相似不能单独证明跨服务因果关系；单次运行未经过的路径不能据此删除。

路径模板描述正常、失败补偿、权限、重试、重复/乱序消息、并发和截止条件等有限场景。关键性由批准业务不变量及风险政策决定，不单凭图中心性或模型评分选出。未证明可行或不可行的路径保持待调查，循环使用场景参数表达，不枚举无限执行路径。

每条路径义务固定：`behavior_revision, path_template_revision, branch_conditions, invariant_pin, trigger, observation_points, fixture_requirements, dependency_pins`。与资产映射进行查询后输出不同缺口：

| 条件 | 缺口和后续动作 |
| --- | --- |
| 路径边界、字段映射或观察位置未知 | 画像缺口；调查和补充关系，义务保留 |
| 无批准预期 | 判据缺口；取得权威修订，不能根据代码自造预期 |
| 无适用用例或用例未断言完整不变量 | 设计缺口；生成/修复用例 |
| 有用例但无适用脚本、数据或隔离条件 | 执行准备缺口；补充自动化和 fixture |
| 有运行但无目标构建有效证据 | 验证缺口；执行或补齐正式证据 |

测试生成消费 `GenerationEnvelope`：固定义务集合、路径模板、独立预期、已知输入/状态边界、观察点、可复用步骤及证据。模型需要逐义务返回用例、步骤和断言映射，无法生成则返回结构化缺口；完整性校验和正式判定继续使用本文件第4节。不存在脚本或没有经过某条边，不直接等同业务缺陷；用例名称相似也不等同覆盖。

构造例：退款回调中的 `applyRefund` 改变了金额或幂等写入。路径沿支付回调进入订单状态更新，经账本写入影响余额读取及对账。已有正常退款用例只断言 HTTP 成功时，系统仍保留“同事件单次记账”“累计退款不超过可退金额”“状态与账本一致”等已批准义务。重复回调、并发和乱序场景按政策形成补充用例，独立批准预期不能由这段代码推导。实际写入对象只有表级解析时，余额/对账相关消费者均进入保守影响范围。

### 3.9 同时控制召回成本与遗漏风险

召回由两个协同通道组成：

- **完整义务与依赖通道**：先从批准规范及风险政策独立枚举当前范围的义务，再利用精确身份、适用图成员和传播规则关联路径及影响。访问全部必需邻接或返回不完整；映射缺失作为缺口，不使用向量 Top-K 或相关性分数删除必验项。
- **辅助材料与候选关系通道**：精确符号/路由/字段命中、全文、向量召回及关系扩展合并，先按项目、版本、访问范围、适用状态和历史否定筛选，再融合排序、去重并截取模型上下文。候选关系需要证据核验才能进入正式画像；未探索的范围保留完整性缺口。

文本和向量各保留召回来源，融合排序不解释为关系成立概率。中文文本使用明确的分词/词典版本，并分解 camelCase/snake_case 符号及保留原文位置；不能假定 `simple` 全文配置自动解决中文语义。对跨命名关系，大模型只处理证据支持的候选；对同名误关联，利用服务、类型、契约和字段约束排除。

pgvector 支持精确及近似检索。近似索引以召回损失换速度，带过滤条件时还可能返回不足；可采用迭代扫描、合适分区或在授权且版本固定的候选范围精确检索。返回数量足够不证明相关材料完整，精确向量距离排序也不证明业务语义正确；不得通过取消项目/版本/权限过滤提高召回。[pgvector 检索与过滤说明](https://github.com/pgvector/pgvector#filtering)

效率来源包括变更局部重解析、稳定片段复用 embedding、按批邻接读取、服务/业务摘要缓存和按需加载原文。任何缓存命中均核对依赖、画像和索引代际；召回为空同样记录查询范围，新增文件使相应范围重新评估。计算预算不足时优先保留完整义务并减少可选材料，无法完成关键分析时扩大验证或阻断。

评价同时报告：实体/关系准确率与召回率、受影响测试漏选率、关键路径缺口识别率、无依据断言率、错误版本召回率，以及查询 p50/p95、增量更新时间、扫描边数、模型 tokens、存储/内存和索引维护成本。使用独立标注或受控缺陷/变更作为参照，不以模型自评作 gold；同时报告无影响变化带来的过度选测率。精确词法、纯向量、无版本图、完整方案及机制消融在相同范围对照，不能用隐藏遗漏换取更低耗时。

### 3.10 数据库选择与候选技术保护组合

PostgreSQL 加全文/向量索引可以作为最终态的一种完整实现，并不因使用关系表就缺失图语义。是否达到“快准”需要上述工作负载验证，当前没有端到端数据支持具体延迟、规模上限或准确率承诺。若高扇出混合路径、大量交互式多跳查询在索引、批处理和缓存优化后仍达不到既定目标，再引入图数据库作为按画像版本可重建的查询投影；它不能替代身份解析、关系证据或独立预期。

候选保护组合集中为：**固定多源修订并建立带类型、条件及依据的关系；在变更前后画像及查询范围依赖上按变化类型传播影响；将受影响业务路径编译为带独立预期和观察点的验证义务；由缺口反向补充画像和生成测试；将完整义务与可截取检索材料分离，并按依赖变化联动更新资产和证据适用性。** 数据库产品和通用混合检索是实现手段，不单独宣称创新。该组合须与现有依赖图选测、多源图谱及反馈更新公开方案逐项比较，本文不据此认定已具备可授权性。

例如，[US20260072811A1](https://patents.google.com/patent/US20260072811A1/en)已公开依赖图与历史覆盖映射用于变更选测，[CN121996618A](https://patents.google.com/patent/CN121996618A/en)已公开向量检索、图邻域扩展、版本对齐与证据包生成。本设计的比较对象是上述具体机制如何联合保持验证义务、识别分层缺口及触发后续失效，不能只按功能名称认定差异。

### 3.11 接入位置

复用：[semantic_evaluations.py](../../../apps/api/app/application/system_image/semantic_evaluations.py)、[semantic_links.py](../../../apps/api/app/domain/system_image/semantic_links.py)、[semantic_applicability.py](../../../apps/api/app/domain/system_image/semantic_applicability.py)、[screened_link_candidates.py](../../../apps/api/app/application/system_image/screened_link_candidates.py)。

拟新增：`domain/system_image/relation_validation.py`、`domain/system_image/evidence_gap.py`、`application/system_image/verifiability.py`，以及对应归档、repository 和只读查询接口。现有零模型调查策略保留原行为；新的模型调查能力通过新策略版本及工具注册接入，沿用当前权限/模型出口检查。

## 4. 技术方案二：验证缺口驱动自主行动、执行和准入

### 4.1 持久协调器

复用现有 AgentGoal。Temporal 等工作流组件负责调度、等待和恢复；模型规划在受计量的任务中执行，重放读取既有结果，不在恢复时直接重做模型调用或业务副作用。

建立迭代草稿收集来源、范围和缺口；只有目标构建、完整义务、环境契约和政策等必需字段齐全后才冻结正式 `IterationContract`。草稿可以调查和生成候选，不能进行正式判定。修复构建形成新契约，沿用原 Goal 的累计预算、去重和失败历史。

```text
observe current gap and verdict events
  -> derive unresolved obligations
  -> reserve planner-call budget through the audited model router
  -> propose typed actions with the model
  -> validate policy, fixed inputs and completion conditions
  -> reserve tool budget and original work identity
  -> execute or recover through the tool runtime
  -> verify original outputs
  -> update gaps / qualify verdicts / prepare image patch
  -> continue, create next contract, await external input, or finalize
```

工作项保存 `pending / admitted / running / awaiting_evidence / completed / rejected / paused`，状态更新检查 owner/epoch。工作项完成和业务通过分开：一次完整执行发现缺陷仍是完成的工作项，但义务判定为失败。

模型调用前先预留规划成本，工具派发前另预留执行成本；调用后按可信用量结算。超时且费用未知时保留预算预留，不能按零成本释放并无限重试。

### 4.2 动作选择

| 动作类 | 必需内容 | 完成证据 |
| --- | --- | --- |
| 调查/诊断 | 要区分的解释、各解释对应的可能观察、固定取证范围 | 原文、trace或诊断回执支持某解释，或明确得到未知 |
| 生成/修复资产 | 义务集合、允许证据、原判据、资产校验条件 | 用例/脚本通过结构与映射检查或产生显式缺口 |
| 正式执行 | 固定 RunPlan、目标、fixture、判据、原派发身份 | 完整原始观察及正式资格校验 |
| 代码修复/构建 | 被定位的问题、允许修改范围、验收依据和构建适配器 | 候选提交与确切构建产物，不直接产生通过结论 |
| 外部输入 | 缺少的预期、权限或无法消除的歧义 | 明确的新权威修订或授权；没有输入时保持等待 |

排序首先保证必验/关键阻断项，其次直接变更影响，再次可选探索。同级按作用范围、风险、预计成本和等待时长排序。模型估计可以影响排序，但不能删义务、变更权重或把未知改成通过。

进展签名基于 gap 沿革、相关实质输入、新证据身份和有效状态迁移；不基于任意新建 ID。同证据导致状态来回变化不重复计数。无进展达到策略上限或总预算耗尽时暂停，并保留未完成义务。

### 4.3 生成与执行接续

使用现有 `generation_obligations` 结果作为原始义务行；新增沿革映射只记录新旧业务责任的联系。完整 AC、联合条件和全局规则必须保留，跨条件义务分在同一不可分单元，全局义务每包可见且统一去重计数。

生成的用例、映射和脚本经过现有审阅路径后编译 RunPlan。工具调用复用现有执行任务、fixture、build binding和原派发 claim。结果未知时先恢复原回执；新尝试需要单独身份及重试前提，不重复发送可能产生副作用的请求。

### 4.4 从原始观察生成正式结果

新增接口：

```text
qualify_evidence(contract_pin, run_plan_pin, observation_hints?)
  -> VerificationVerdict[] + qualification_gaps[]
```

服务端按目标构建、义务/完整判据身份及适用范围枚举全部 run、attempt、派发 claim 和 outcome，固定执行库存快照及 epoch。输入提示只定位记录，不限定搜索边界；新建契约不能截断同构建的适用失败历史。判定保存选用观察、未决尝试、排除项及可复核理由。缺失 outcome 的派发保持未知；排除有效反例必须有独立依据，不能只因后一次运行成功。

该服务依次验证：

1. 原执行来自正确的计划和授权，脚本、case、步骤及判据映射未改变。
2. 实际服务于请求的目标与构建匹配。使用可信部署/Runner适配器提供的构建绑定和实例身份；多副本必须覆盖实际服务实例，不能只相信应用自行声明的版本字符串。没有可核验目标依据就保持未知。
3. 环境、配置、依赖服务、测试数据及前置状态符合计划；fixture建立成功不能替代业务前置条件满足。
4. 从原响应字节、事件回执或完整只读查询重新计算判据，核对相关 ID、窗口、顺序、关联分组及观察完整性。
5. 保存每个叶子判据的实测值、来源、比较结果和 evaluator version，再按预先批准的表达式树归并。

现有 [http_runner_oracles.py](../../../apps/api/app/domain/quality_loop/http_runner_oracles.py) 已能重验部分 HTTP 断言，可作为底层适配器。跨服务账本一致性、异步最终状态和并发规则需要新增观察适配器，不能从 HTTP 200 自动推导。

| 归并方式 | 判定规则 |
| --- | --- |
| `all_of` | 全部子项有效通过才通过；任一有效失败则失败；其余未知 |
| `any_of` | 至少一个有效通过即可满足该替代组；全部有效失败才失败；其余未知 |
| 多个必测场景 | 默认 `all_of`；`any_of` 只用于预先批准的替代验证路径 |
| 多次运行 | 不默认使用最新成功；同构建同完整判据的有效反例保持阻断，直至证据明确解释为无效测试，或新构建完成必要验证 |

OR表达式内某个分支失败不一定是整体失败；这与同一完整判据已经出现有效反例是不同情况。案例缺失、过期和不完整观察单独保留，不悄悄从分母删除。

派发登记及观察入库与执行库存 epoch 更新同事务提交；正式资格保存时锁定或条件核验同一库存 guard。出现新失败、未决派发或迟到结果时重新评估相关资格；准入许可签发和消费也检查该库存 epoch，防止使用已经过时的完整性快照。

### 4.5 评分与发布许可

新增准入投影消费本轮全部 `VerificationVerdict`，不沿用旧“最近一条成功+历史通过率”的汇总作为新链事实。

```text
if contract or policy changed: needs_reassessment
else if mandatory failed or critical conflict: blocked
else if mandatory missing/unknown/stale: needs_evidence
else if release-relevant risk is unclassified: needs_evidence
else:
    Q = 100 * weighted qualified passes / fixed total weight
    if Q invalid or below the fixed policy threshold: needs_evidence
    else: eligible_for_release_review
```

模型输出风险解释、分类和评分建议；权重和必验性经政策接纳后固定。Q仅表示证据满足度。`needs_evidence` 回到动作队列，不能因必验已通过而在评分环节反复提前退出。

质量满足后核验操作授权，并在条件事务中重验依赖、目标、执行库存和范围 guard，签发含构建、依赖摘要、库存/范围 epoch、许可 epoch 和有效期的许可。消费和撤回使用同一状态/epoch条件；部署派发有持久幂等记录。派发后失联保留未知，不能重发或声称外部副作用已经撤回。

### 4.6 接入位置

复用：[test_design_generation.py](../../../apps/api/app/domain/quality_loop/test_design_generation.py)、[generation_batches.py](../../../apps/api/app/domain/quality_loop/generation_batches.py)、[test_design_mapping.py](../../../apps/api/app/domain/quality_loop/test_design_mapping.py)、[run_plan_case_execution.py](../../../apps/api/app/application/quality_loop/run_plan_case_execution.py)、[run_plan_observations.py](../../../apps/api/app/domain/quality_loop/run_plan_observations.py)、[nasus_run_plan_case_workflow.py](../../../apps/api/app/infrastructure/workflow/nasus_run_plan_case_workflow.py)。

拟新增：`domain/quality_loop/iteration_contract.py`、`domain/quality_loop/oracle_expression.py`、`domain/quality_loop/verification_verdict.py`、`application/quality_loop/evidence_qualification.py`、`application/quality_loop/iteration_readiness.py`、`application/agent/iteration_coordinator.py`。历史观察继续保持原有非正式通过语义，通过新资格记录建立正式投影，禁止回填伪造历史通过。

## 5. 技术方案三：双增量画像补丁与结论同步更新

### 5.1 事件接入

以下为拟新增的版本化领域事件名称，不是现有工具已提供的能力：

| 事件 | 载荷中的关键固定引用 |
| --- | --- |
| `SourceRevisionCaptured` | binding、before/after修订、完整采集清单及manifest |
| `ExecutionObservationArchived` | 原run、plan、attempt、目标及观察工件 |
| `VerificationVerdictRecorded` | 原contract、义务修订、判定工件及依赖 |
| `AuthorityRevisionChanged` | 预期或审阅决定的原/新修订及适用范围 |
| `ImagePatchCommitted` | 父/新画像、补丁摘要、影响范围及需要的新契约 |

事件通过现有 Outbox 可靠投递。消费者以 `event_id + consumer_version` 去重；同一业务输入用稳定语义键再去重。漏事件通过来源 head 对账发现，但重新发现事件不改写正在执行的 manifest。

### 5.2 完整影响范围

复用现有来源双修订比较。只在完整、可比采集范围内判断增删；纯运行反馈没有来源变化，缺省来源参数不代表删除。

将依赖登记扩展到：

```text
来源内容 / 查询范围 / 批准预期
  -> 实体与关系主张
  -> Context / Scope / 义务
  -> 用例映射 / 脚本 / RunPlan
  -> 正式判定 / 发布许可
```

当前 [derivation_registry.py](../../../apps/api/app/domain/system_image/derivation_registry.py) 及 [derivation_registry_models.py](../../../apps/api/app/infrastructure/persistence/derivation_registry_models.py) 只允许 context/scope/generation/case/coverage/mapping，并以 context 约束父链。完整链需要新的协议版本和数据库约束迁移，不能仅在应用端添加几个 kind。

可建立项目级版本化依赖登记，将现有工件作为引用节点导入；完整业务数据仍由原域持有。反向索引用于从变更根发现派生消费者。业务调用图可以有环，工件版本依赖必须无环，运行反馈只能成为后续修订的输入。

查询开始前取得 `QueryScopeStamp(scope_key, scope_definition, inventory_digest, epoch)`，保存来源范围、匹配规则、过滤条件和分析器版本；空结果同样保留。查询依赖显式绑定来源目录、接口命名空间等范围根；查询“项目全部来源”还绑定来源集合 inventory 根。新增文件或 binding 先改变对应范围根，不能仅从旧命中文件反查消费者。依赖登记与业务工件提交保持原子；查询期间范围变化则重查或标为待重评。新增文件可能改变原空结果或排序时，重新执行对应查询；无法证明范围不相交时采用来源级保守扩展。

### 5.3 防止异步失效期间继续使用旧结论

只有配置的跟踪来源当前头或权威修订被接纳时才启动当前用途失效；采集未采用的实验分支不自动改变当前基线。来源/权威当前头更新与相关范围 `invalidation_epoch` 增加、屏障建立在同一条件事务内完成，不能等 Outbox 消费后才设屏障；随后异步展开依赖闭包。闭包未完成前，相关用途为待重评。

新派生登记、正式判定、许可签发和消费在各自提交事务中锁定或 CAS 同一范围 guard，核验 epoch 及实际来源/查询范围摘要；不能把旧输入重新标记为新 epoch。闭包任务固定登记快照和游标，分页完成后核对完整性；仅在 epoch 仍等于本任务期望值且完整快照已处理时解除这一代屏障，后续变更不能被旧任务解除。任务中断或截断保留屏障，不能将局部结果解释为全项目完成。与本轮无依赖关系的项目范围可以继续运行。

### 5.4 补丁准备、验证和提交

```text
prepare_patch(base_image, event_batch):
  delta = verify_source_deltas_and_original_observations(event_batch)
  mode = classify_delta_against_contract_dependencies(delta)
  if mode == no_op:
    return deduplicated_receipt()
  if mode == journal_only:
    return immutable_journal_append(delta, evidence_inventory_updates)
  impacted = collect_complete_dependency_closure(delta)
  repairs = propose_typed_claim_changes_with_model(impacted)
  candidate = apply_to_isolated_candidate(base_image, repairs)
  validate_endpoints_evidence_review_applicability(candidate)
  projection = compare_contract_dependency_projection(candidate)
  obligations = recompile_if_obligation_inputs_changed(candidate)
  mode = future_image_only if projection.unchanged else current_dependency_changed
  qualification_changes = compare_dependencies_and_verdict_eligibility()
  return immutable_patch(mode, candidate, impacted, obligations,
                         qualification_changes, required_checks)

commit_patch(patch_pin, expected_head):
  verify_patch_archive_and_required_checks()
  with shared_unit_of_work:
    lock_and_recheck_heads_authority_scope_and_inventory_guards()
    persist_journal_or_new_image_and_dependencies_by_mode()
    persist_qualification_invalidations_if_needed()
    if patch.mode == current_dependency_changed:
      persist_next_contract_request()
    compare_and_swap_relevant_heads_if_changed()
    append_outbox_events()
```

同一 PostgreSQL 下通过共享 UnitOfWork 与跨域端口提交逻辑关联；大对象先归档，外部模型/工具调用不放在数据库事务里。若跨域事实拆到不同存储，应保留失效屏障直到各方确认完成，不能假定分布式原子成功。

原始观察等只追加材料先进入 journal，不改变本轮执行前画像；其进入执行库存仍可能使旧资格重新计算。后续知识和资产可形成 `future_image_only` 候选。只有本轮契约实际消费的语义依赖、判据、义务或执行前提投影发生变化，才请求新契约；比较 `contract_dependency_projection_digest`，不以整图 hash 改变作为重测条件。新增观察关系不会自动触发全量重测。`ImagePatchCommitted` 用于通知下游，不再被当成新来源变化自触发。新契约继续用原 Goal 预算推进。已证实失败也能进入历史知识，但不成为软件发布许可。

画像回退若启用，应记录指向旧内容的新状态事件；旧内容恢复不自动恢复旧许可、旧证据资格或清除本轮失败。

### 5.5 接入位置

复用：[source_delta.py](../../../apps/api/app/domain/system_image/source_delta.py)、[derivation_impact.py](../../../apps/api/app/domain/system_image/derivation_impact.py)、[semantic_membership.py](../../../apps/api/app/application/system_image/semantic_membership.py)、[image_candidates.py](../../../apps/api/app/application/system_image/image_candidates.py)、[publications.py](../../../apps/api/app/application/system_image/publications.py)。

拟新增：`domain/system_image/image_patch.py`、`application/system_image/image_patches.py`、版本化项目依赖索引、失效屏障及事件消费者。现有画像记录的 policy/member约束也需明确演进；保留旧 schema 解码和历史读取，不给旧工件补造新验证信息。

## 6. 一次端到端数据流

以下为构造示例：

1. 来源 C2 新增回调文件；事件固定新 manifest，查询范围失效，形成画像候选 I2。
2. 模型提出回调与记账关联；可验证性检查发现缺少 event ID 到账本记录的观察路径，产生 G1。
3. Agent 调查接口和代码取得关联键；核验后关闭 G1，编译包含“重复回调一次记账”的完整义务集合，冻结契约 K2。
4. 复用原退款步骤，补充重复回调用例；生成/审阅脚本，RunPlan R2固定构建 B2和隔离订单。
5. 执行获得原始回执；正式判据重新计算发现同event两笔记账。工作项完成，义务失败，准入阻断。
6. Agent 分析业务重复处理与测试重复派发两个解释；检查原派发和事件回执，证据不足时继续调查，不能直接确认根因。
7. 具备依据后形成修复候选和关系补丁；新构建 B3、新契约 K3、新计划 R3重新验证，保留 K2失败历史和同一Goal累计成本。
8. 必验有效通过且依赖/许可条件满足后形成准入结论；I3吸收经校验关系、资产及反例。下一轮继续从I3及新来源事件开始。

## 7. 实施顺序与验收

| 顺序 | 可交付的完整切片 | 必须证明的结果 |
| --- | --- | --- |
| A 正式结果桥接 | 固定义务、受限判据、目标/观察核验、Verdict及新准入投影 | 同一个真实目标测试中，业务失败、观察未知、有效通过明确区分，旧构建成功不能放行新构建 |
| B 验证反向建图 | RelationValidationSpec、四槽检查、Gap、模型调查工具接入 | 缺少观察路径时自动调查并补齐；无依据关系不被当成已验证事实 |
| C 自主协调 | 原Goal的工作项状态机、动作分类、预算、恢复、评分到补证 | 不依赖逐步人工点击完成已授权动作；失败/未知能推动下一动作，不能无限重试或重置预算 |
| D 双增量联动 | 来源/观察事件、依赖扩展、失效屏障、补丁提交、新契约 | 新文件、预期撤回或反馈修正及时影响义务及许可；失败轮可沉淀知识，下一轮继续验证 |

先完成 A 是因为 B/C/D 都需要真实判定反馈。开发验收使用隔离的退款模拟系统及可控事件/账本观察，再扩展真实项目；通过本地协议夹具不等于生产端到端已完成。

关键验收场景包括：完整分包、用例丢弃但义务保留、空表达式与跨尝试拼证据、all_of/any_of混用、异步提前观察、分页不完整、仅送审成功却存在同构建失败、迟到结果与许可消费竞争、重放不重复副作用、补丁切换预算不重置、纯观察不重建契约、新文件影响空查询、依赖遍历期间并发登记、批准撤回与许可消费竞争，以及B2失败→B3修复→I3更新的完整两轮链。

本轮仅完成技术实施设计和代码接点核查，未新增产品模块、数据库迁移或运行产品测试。实现效果仍需上述验收和整体方案中的对照指标证明。
