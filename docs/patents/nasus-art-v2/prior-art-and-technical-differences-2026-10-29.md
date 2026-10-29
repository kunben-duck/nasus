# 动态系统画像测试生成与软件验证的现有技术及技术区别评估报告

**发明名称：一种基于动态系统画像的测试用例生成与软件验证方法**  
**资料截止：2026年10月29日，Asia/Shanghai**  
**评估对象：当前最终态技术方案，包括尚未贯通的设计，不将其全部表述为已实现能力。**

本报告按“接近的现有技术、可执行区别、效果因果关系、常规改动与创造性风险”四步展开。结论是：**多源图谱、增量更新、影响选测、缺口补测、执行反馈和版本门禁均已有接近公开；此前三个高层创新点不能直接作为已经确认的独有贡献。** 仍可继续具体比较的对象，是独立验证义务、画像依赖、完整执行库存和证据资格之间的连续约束，但其创造性尚未得到证明。

当前最接近整体链路的专利起点为 **CN121935166A**；若把“函数变化沿调用、数据与业务关系指导集成测试”作为独立方案中心，**CN122045051A** 是必须并列审视的竞争性起点。名称可以保留，技术区别需要收窄。

本报告未获得实际申请日或优先权日，资料截止日不替代法律判断的关键日期。专利日期使用所引文本的公开日；A/B文本不重复计算为独立技术来源；当前网页、Git提交时间和历史公开时间分别处理。以下是有定位的技术评估，不是穷尽检索、授权结论或自由实施分析。

## 一 最接近的现有技术

### 1.1 检索方式和同义词

将“系统画像”拆成结构模型、依赖图、知识图谱和软件数字孪生等检索方向，将“验证”拆成测试生成、回归选择、需求覆盖、判据、证据接纳及发布门禁。数字孪生用于扩大检索范围，不预设本方案具有仿真孪生的全部能力。

| 切入点 | 中文检索式实例 | 英文检索式实例 |
| --- | --- | --- |
| 变更后影响和漏测 | `专利 动态 知识图谱 测试用例 增量 更新 反例 验证` | `patent regression test selection dependency graph coverage new code test generation` |
| 缺少测试点和验收条件 | `专利 测试用例 需求 预期 生成 完整性 校验 版本 图谱` | `patent "test generation" "knowledge graph" "missing" requirements` |
| 版本证据与准入 | `专利 测试 验收约束 完整性 分包 版本 证据 准入` | `patent "test results" "deployment" "version" "invalidate"` |
| 反馈驱动模型完善 | `"测试需求" "测试模型" "自动生成" 论文 需求 关联 图谱` | `counterexample guided abstraction refinement model based testing test generation paper` |
| 空结果及范围依赖 | `增量构建 目录 glob 新增文件 依赖 Skyframe` | `patent "query" "empty result" dependency invalidation` |
| 核心代码结构 | `测试 需求 覆盖 停止条件 GraphWalker` | `DirectoryListingValue GlobFunction`；`RequirementCoverage`；`def in_toto_verify` |
| 名称之外的扩展 | `"需求覆盖" "测试生成" "知识图谱" "增量"` | `software "digital twin" "test generation" incremental`；`"software verification" "test obligations" "evidence" build` |

检索覆盖公开专利全文、论文原文及作者/会议页面、官方产品文档、固定版本公开代码。专利对照读取相关权利要求与实施方式；没有把摘要缺少某个词当作未披露的证明。未覆盖全部同族、引证链和审查档案，结果不能解释为不存在其他更接近文献。

### 1.2 关键专利及实际披露

表中“位置”用于直接复核，技术内容为概括，不等同于该文献的完整权利范围。

| 编号及所引文本公开日 | 文献和核读位置 | 已公开机制及对本方案的影响 |
| --- | --- | --- |
| P1，2026-04-28 | [CN121935166A 动态知识图谱测试生成](https://patents.google.com/patent/CN121935166A/zh)，权1—8及对应实施方式；[B文本](https://patents.google.com/patent/CN121935166B/zh)于2026-07-21公告 | 多源图谱随版本变化增量更新，结合影响、路径和风险生成测试，再利用执行反馈调整图谱。A权6明确按未覆盖路径的原因补充关联或调整遍历。因此，缺口反向完善画像的概括已有直接重合。 |
| P2，2026-05-15 | [CN122045051A 智能体多维测试样例生成](https://patents.google.com/patent/CN122045051A/zh)，权3—5、9，实施方式2.1—2.4及3.1 | 融合调用图、数据流图与模型推理的业务图，传播变化并生成场景、数据和用例，按权重划分强制及可选回归。直接压缩“调用、数据、业务关联指导测试”的宽泛区别。 |
| P3，2026-04-10 | [CN121833530A 测试用例优化](https://patents.google.com/patent/CN121833530A/zh)，权1、5—6及缺失测试点诊断 | 质量图谱关联需求、代码、缺陷和用例，比较应测点与实际点，反向追溯缺失原因并回写优化用例。缺口识别和资产补全已有先例。 |
| P4，2026-04-10 | [CN121833513A 软件自动化测试](https://patents.google.com/patent/CN121833513A/zh)，权1—6，实施例一至三 | 使用完整测试基线，将局部变化与已有知识融合，增量推理影响并接收执行反馈。“完整基线防遗漏”不能笼统作为区别。 |
| P5，2023-11-28 | [CN117130938A 知识图谱测试案例生成](https://patents.google.com/patent/CN117130938A/zh)，权1—7及对应说明 | 处理全部结构化需求，复用或更新已有测试点，对缺失点生成并回写图谱。全部需求、复用及缺项补生成并非新提出。 |
| P6，2026-05-08 | [CN121996618A 软件V字流程RAG检索](https://patents.google.com/patent/CN121996618A/en)，权1—2及版本、检索实施方式 | 多源文档、版本基线和图关系参与混合检索，证据包约束生成。版本化图谱与RAG组合已有公开。 |
| P7，2023-11-01 | [EP4270179A1 Managing deployment of versioned services](https://patents.google.com/patent/EP4270179A1/en)，权1、3—7，图2及过程400/500/600 | 关联服务调用拓扑、环境版本与测试记录，比较测试环境和目标环境的依赖版本以形成部署判断。仅增加目标版本核对不足以区分。 |
| P8，2026-05-15 | [CN122044758A 交付事件管理](https://patents.google.com/patent/CN122044758A/en)，权1、4—10 | 按交付事件组织门禁和测试，保存环境快照，阈值判断及失败后重测。执行与门禁衔接已有明确机制。 |
| P9，2020-03-17 | [CN110888808A 知识图谱Web测试](https://patents.google.com/patent/CN110888808A/zh)，权1、3、5—6、9—10 | 本体、图谱质量检查、测试推理和执行，以及版本或操作触发的图谱更新。引入本体或图数据库不能单独提供有力区别。 |
| P10，2003-07-08 | [US6591266B1 缓存与刷新](https://patents.google.com/patent/US6591266B1/en)，权1—6，图11—15及带查询变量的条件选择部分 | 保存查询条件和实例，将新增/删除数据与谓词匹配，再使依赖结果失效。其对象是网页缓存，但已说明不能只依赖旧命中项判断失效。 |
| P11，2026-03-12 | [US20260072811A1 依赖图选择性回归](https://patents.google.com/patent/US20260072811A1/en)，权147—159及覆盖映射实施方式 | 代码差异、结构依赖、影响元素和历史覆盖映射共同选测。函数影响传播和少量回归选择已有直接公开。 |

### 1.3 论文反证

| 编号及时间边界 | 原文定位 | 对创新表述的约束 |
| --- | --- | --- |
| L1，arXiv v1为2026-07-10 | [TestAgent全文](https://arxiv.org/html/2607.09101v1)，III-B—E、IV-A.5、V-B | 测试专用图谱、多Agent规划/生成/审阅、执行反馈与结果回流已连成闭环，也保留有效缺陷失败。实验截取前5项要求只说明该实验设置，不能推断方法永远只能处理5项。 |
| L2，arXiv v1为2026-07-14，另有CVPR 2026版 | [EvoGraph-R1](https://arxiv.org/html/2607.12764v1)，3.3—3.5 | 任务状态驱动检索、补证和图谱编辑已有先例。该文面向检索问答，不直接等同软件测试，但削弱通用“任务反馈完善图谱”的独特性；arXiv日期不作全球最早公开日。 |
| L3，ISSTA 2015 | [Ekstazi作者全文](https://users.ece.utexas.edu/~gligoric/papers/GligoricETAL15Ekstazi.pdf)，2、3.1、3.3—3.5 | 按测试记录文件依赖和校验和，甚至跟踪尝试访问但不存在的文件，以处理其随后新增的影响。“不存在依赖也跟踪”已有直接测试领域先例。 |
| L4，首次出版2014-11-19，期刊卷期2015 | [The Oracle Problem in Software Testing](https://discovery.ucl.ac.uk/id/eprint/1471263/1/06963470.pdf)，2、4.1、4.3.1、5 | 规格、前后置条件、观察与具体输出映射是既有测试问题。独立预期和观察点本身不能单列为创新；综述提供设计背景，不替代每项原始技术的逐项披露证明。 |
| L5，CAV 2000会议版 | [Counterexample-Guided Abstraction Refinement](https://web.stanford.edu/class/cs357/cegar.pdf)，1、3—4 | 验证反例可驱动抽象模型细化。它处理真实反例与伪反例的区分，不等于把实际软件失败改成通过；也不能单篇覆盖生成式测试画像。 |

### 1.4 产品文档与公开代码

下面核读了实际函数或分支，并非仅浏览项目介绍。代码未在本轮执行，公开版本日期是证据时间线索，不是对历史网页的公证。

| 编号 | 官方文档及固定源码 | 具体实现与区别边界 |
| --- | --- | --- |
| C1，Bazel 7.0.0，2023-12-11发布 | [Skyframe文档](https://bazel.build/reference/skyframe)；[GlobFunction.compute，提交d798ebd](https://github.com/bazelbuild/bazel/blob/d798ebde6c6394203a87b5f1a6b62ecfc3880991/src/main/java/com/google/devtools/build/lib/skyframe/GlobFunction.java#L60) | 通配查询读取DirectoryListingValue，结果为空也保留目录依赖；配合反向依赖失效和未变值剪枝。由此推断，范围依赖迁移到画像缓存有明显工程基础，仍须说明测试义务和证据资格的特殊联动。 |
| C2，GraphWalker 4.3.3，2024-09-26发布 | [生成器与停止条件](https://github.com/GraphWalker/graphwalker-project/wiki/Generators-and-stop-conditions)；[RequirementCoverage，提交1c28d9c](https://github.com/GraphWalker/graphwalker-project/blob/1c28d9c4171b8bda24d01f3268ddc6765b3a2e81/graphwalker-core/src/main/java/org/graphwalker/core/condition/RequirementCoverage.java#L46)；[同提交StopConditionBase](https://github.com/GraphWalker/graphwalker-project/blob/1c28d9c4171b8bda24d01f3268ddc6765b3a2e81/graphwalker-core/src/main/java/org/graphwalker/core/condition/StopConditionBase.java) | 需求覆盖用模型需求总数作分母，已通过和已失败都算已执行覆盖；需求为空时完成度返回1.0，最终停止还要求当前元素为顶点。这不是把失败算业务成功。需求分母和未覆盖目标驱动生成已有代码依据。 |
| C3，in-toto v3.0.0，2024-05-14发布 | [验证API](https://in-toto.readthedocs.io/en/latest/api.html)；[verifylib.py，提交659942b](https://github.com/in-toto/in-toto/blob/659942bde1cd732b0b9449445f9769b2def6aeb1/in_toto/verifylib.py#L1502) | 验证布局签名、过期、阈值、材料/产物规则及检查命令；所需链接缺失可以失败。命令不一致的一部分检查仅告警，不能概括为全部硬拒绝。自定义检查可扩展，默认未有某检查不代表不能实现。 |
| C4，TestAgent固定提交feb88ab | [Planner.py](https://github.com/iSEngLab/TestAgent-VSCode-Extension/blob/feb88abc9ab40256b635b64bc580280e5ab0c7cd/backend/Planner.py#L109)；[Generator.py](https://github.com/iSEngLab/TestAgent-VSCode-Extension/blob/feb88abc9ab40256b635b64bc580280e5ab0c7cd/backend/Generator.py#L318) | 该版本规划输出使用test_points[:5]；生成器有method_bug/find_bug分支并将要求、测试及分析回写图谱。可与不可裁剪义务作具体对照，但提交时间2026-01-28不证明仓库当日已公开。 |

C1—C3的发布日分别核对[7.0.0发布](https://github.com/bazelbuild/bazel/releases/tag/7.0.0)、[4.3.3发布](https://github.com/GraphWalker/graphwalker-project/releases/tag/4.3.3)、[v3.0.0发布](https://github.com/in-toto/in-toto/releases/tag/v3.0.0)元数据。C4另有[FSE 2026工具演示页面](https://conf.researchr.org/details/fse-2026/fse-2026-demonstrations/30/TestAgent-A-Multi-Agent-LLM-Framework-for-Repository-Level-Unit-Test-Generation)，与L1为相关但题名不同的公开材料，不混用发布日期。

此外，[Sigstore Policy Controller](https://docs.sigstore.dev/policy-controller/overview/)公开镜像解析、证明内容策略和准入，[Launchable](https://help.launchableinc.com/features/predictive-test-selection/how-launchable-selects-tests/)公开由变化、环境和历史执行信息选择测试子集。当前页面未取得精确首次发布日期，只作为截至检索日的工程对照，不据此倒推更早关键日之前的全部内容。

### 1.5 最接近技术的选择

以当前完整处理链为对象，P1比单纯RAG或缓存技术更适合作为主要起点，因为它与本方案处于同一测试问题域，连接了变化、图谱、生成及反馈；选择依据包含技术问题和用途，不只是共有特征数量。P2则更直接对应跨服务关系指导测试，应作为竞争性起点。若权利要求转向发布证据资格，P7是该子主题的重要起点。

新颖性必须围绕一项明确技术方案分别比较，不能将P1、P2、C1、C3拼成一篇文献来否定新颖性。创造性则需要审视它们之间的结合动机与技术启示。当前尚未形成正式权利要求，本报告只识别候选区别，不能作“已经证明新颖”的结论。

## 二 将候选区别写成可执行机制

### 2.1 评估对象的收窄

以下可作为一个整体方案继续比较：

> 在固定来源和目标构建下，从独立验收依据建立完整义务清单；画像中的关系及查询范围决定该清单的映射、调查和证据依赖；各生成分包、执行尝试和判据结果沿用该清单及修订；来源或运行证据变化时，联动更新画像、义务适用性和验证结论，禁止缺失义务或过时证据支持通过。

这一表述是待评估的联合约束，不将“图谱”“全部需求”“缺证据阻断”“版本号”分别宣称为新技术。发布准入是正式验证结论的使用环节，名称仍采用已确定的“测试用例生成与软件验证方法”。

为避免把所有实施细节堆在一起寻找差异，本轮把被比较的**候选组合K**限定为以下五项共同约束：

1. **K1 固定义务与目标。** 从独立批准依据形成M，用不可变契约绑定画像、适用范围、判据修订和目标构建。
2. **K2 缺口保留与定向补图。** 画像不能提供触发、预期、观察或隔离条件时，保存绑定义务及固定关闭条件的缺口；调查不能删除该义务或从运行行为改写预期。
3. **K3 跨阶段保持清单。** 生成分包、模型输出和执行映射均沿用M及其修订；预算超限或资产淘汰只改变动作与缺口，不静默缩小M。
4. **K4 完整尝试决定证据资格。** 服务端按目标及完整判据枚举执行库存，从适用原观察重算判据，保留未知和有效反例，不能以调用者选择的成功集替代。
5. **K5 依赖变化约束结论使用。** 来源、批准、查询范围或执行库存变化沿已登记依赖影响资格；结论提交和使用核验相同相关代际，区分仅追加观察与改变当前语义前提，后者才重建当前契约。

下文算法解释如何实现K。数据库产品、具体操作符名称、评分公式、分包数量及遍历上限不作为K的必要限定，也不凭这些可选细节支撑新颖性。可选实施方式和从属权项同样属于现有技术披露，不能因其在文献中不是必要特征而排除。

### 2.2 数据、模块输入输出和触发条件

| 模块及对象 | 关键字段与信息交换 | 触发和硬约束 |
| --- | --- | --- |
| 来源采集及画像构建 | SourceSnapshot保存binding、revision、inventory_digest、completeness；Image固定实体及关系修订 | 接纳新来源修订后比较双版本；采集不完整时只记未观察到，不能将其当真实删除 |
| 关系及影响分析 | Edge保存端点修订、类型、字段/调用点、条件及证据；QueryScope保存谓词、来源范围、过滤规则和代际 | 端点、命中证据或查询范围变化触发重评；输出ImpactScope、解释路径和未处理边界 |
| 义务编译及缺口服务 | Obligation保存沿革、修订、独立判据和依赖；Gap保存missing_slots、closure_spec、evidence_refs | 缺触发、判据、观察或隔离条件时输出类型化Gap；缺业务判据等待权威输入，观察路径缺失才触发定向调查 |
| 生成与校验 | GenerationEnvelope传递完整清单M及摘要、不可分条件单元、全局规则、适用资产和预算 | 辅助检索排序不改变M；模型输出逐义务用例/断言映射或显式缺口，校验器拒绝遗漏和预期替换 |
| 执行及资格判定 | RunPlan绑定画像、M、脚本、构建、环境、数据、批次；服务端枚举run/attempt/claim/outcome并归档原观察 | 派发、完成、迟到结果都改变库存代际；客户端提供的成功记录不限定服务端核验范围 |
| 更新及正式结论 | ImagePatch保存父画像、来源/观察增量、语义依赖差异和资格撤销；Verdict保存原观察、判据结果及依赖代际 | 原子检查相关来源、批准、库存和失效屏障；改变正式依赖才形成新契约，纯日志不自动重建整轮计划 |

模块之间交换固定对象引用和摘要，不由模型直接写正式通过状态。摘要仅证明引用内容未变，不能证明关系语义成立或业务预期正确。

### 2.3 算法A 按类型传播与查询范围失效

```text
input: before_image, after_image, source_delta, approved_scope, policy
validate_same_source_binding_and_capture_completeness()
seeds = changed_entities_in_each_image + changed_query_scope_roots
for image in [before_image, after_image]:
    queue = typed_states(image, seeds, changed_fields)
    visited = empty_set()
    while queue:
        batch = pop_batch(queue)
        active = remove_visited_states(batch, visited)
        visited.add(keys(active, image, entity_revision, rule_state, field_scope))
        edges = read_adjacencies_for_pinned_image(active)
        next_states = apply_call_field_and_contract_rules(active, edges)
        queue.extend(unvisited_and_not_queued(next_states))
        if unknown_boundary_or_limit_reached:
            preserve_frontier_and_expand_validation_or_block()
            return incomplete
merge_impacted_identities_by_explicit_lineage()
return impact_scope, per_image_explanation_paths, unresolved_gaps
```

调用变化沿相应方向找到消费者；字段变化经写入、转换和读取关系传播；接口/事件变化经过契约和发布订阅关系。前后画像各自遍历，身份沿革只用于合并影响集合，不拼接跨版本解释路径。

一次语义查询即使没有命中也保存其范围。新文件能否影响旧查询，先按来源、目录、实体类型和可安全判断的过滤条件匹配；无法证明无关时保守扩大。涉及语义相似性或解析器升级时重新召回，不用词法谓词冒充完整的语义判定。分析完成只表示已登记范围处理完毕，不证明现实系统全部依赖已知。

**区别压力：**范围依赖和增量失效在P10、L3、C1已有先例；本算法单独不构成强区别。需要比较其结果怎样实际控制义务、缺口和证据资格，以及这种联动是否超出常规依赖登记。

### 2.4 算法B 完整义务、分包与缺口行动

先固定适用范围，定义：

- `M = ApprovedAcceptance ∪ MandatoryRiskRules ∪ ApplicableRegressionGuards ∪ GlobalRules`。
- M采用身份和修订去重；不是从模型本轮愿意生成多少用例反推分母。
- 范围适用性不明时扩大范围或阻断；移除原义务需要新的批准依据。

```text
M = compile_from_pinned_authorities_and_scope()
U = connected_components_of_joint_constraint_dependencies(M)
for unit in U:
    packet = unit + all_global_rules + required_oracles_and_evidence
    if mandatory_packet_exceeds_hard_budget(packet): return blocked_with_gap
    add_optional_support_material_within_remaining_budget(packet)
    result = generate_cases(packet)
    verify_original_oracles_references_steps_and_obligation_mapping(result)
merge_results_and_require_each_m_in_M_has_case_or_explicit_gap()
choose_next_typed_action_from_remaining_gaps()
```

联合条件通过条件依赖连通分量形成不可分单元。局部义务在分包计划中只有一个归属，全局规则在每包可见但在总分母中只计一次。用例可替换或淘汰，原义务继续保留。

预算分别校验：当前字节约束按规范化序列化长度计算；模型输入按实际模型分词器计算`tokens(packet + prompt)`，并预留输出预算及服务约定开销，总量不得超过配置上限。必需内容超限时返回缺口/阻断，不静默删除条件。Agent的工具调用、模型调用共用原目标累计预算，换契约不重置预算。动作只有满足Gap的固定关闭条件才构成进展。

**区别压力：**P2已有强制/可选回归，P4/P5已有完整基线或全部需求，C2已有覆盖分母。候选区别在同一义务清单跨分包、模型输出校验和执行接纳的连续约束；单纯取消Top-K限制、增加token或复制全局提示不够。

### 2.5 算法C 完整执行库存、目标证据与更新事务

```text
inventory, inventory_digest, inventory_epoch = read_consistent_snapshot_and_enumerate(
    all_applicable_attempts(target, criterion_scope))
require_inventory_enumeration_complete()
for obligation in fixed_contract:
    verify_actual_build_environment_fixture_and_original_observations()
    evaluate_approved_predicate_tree_on_correlated_complete_observations()
    preserve_missing_unknown_stale_and_valid_counterexamples()
quality_ok = mandatory_all_qualified_pass and no_pending_or_critical_conflict
quality_ok &= release_risks_classified and fixed_policy_score_satisfied
on_source_or_authority_change: synchronously_raise_scope_barrier_then_expand_closure()
on_new_observation: update_inventory_and_requalify_relevant_verdicts()
commit_or_consume_result_only_if_relevant_heads_epochs_and_authority_still_match()
```

库存、摘要和代际必须来自同一一致性快照，分页也固定该快照。若存储不提供跨页快照，则在枚举前读取代际，枚举后再次核验未变，否则丢弃该清单并重试。禁止先读取旧清单再读取新代际；清单固定后发生的新派发或结果仍需通过提交时的代际重验识别。

同一联合判据的叶子绑定同一fixture、业务键、适用批次和观察窗口。完整观察证明截止违约时判失败，观察不完整时保持未知。`any_of`仅用于批准的替代证据组；某个可替代分支失败与同一完整判据已经出现有效反例，是不同情况。同构建的有效反例不能被后到的一次成功或新建上下文ID隐藏。

若使用证据满足度评分，令执行前固定集合为`U = 必验项M ∪ 政策可选项O`，权重为有限正数：`Q = 100 × Σ(w_i × qualified_pass_i) / Σ(w_i)`。阈值、权重和必验性随政策固定，Q不解释为软件无缺陷概率，不能抵消必验失败、未知或缺证据。无有效分母时不能默认通过。

ImagePatch按实际依赖投影区分无变化、仅追加观察、仅影响后续画像和改变当前依赖。当前依赖变化才请求新契约；追加观察仍可能撤销旧判定。来源头变动与屏障建立同步提交，异步失效闭包未完成时保持屏障。判定提交及许可消费核验同一相关代际，竞争失败则重新评估，不能把旧输入换上新代际继续使用。

**区别压力：**P7/P8、C3及Sigstore提供了版本、证据与门禁基础；事务和CAS也是成熟手段。候选贡献只能落在具体依赖集合、完整库存与状态转换的相互约束，而不能以“加一个版本字段或发布前校验”概括。

## 三 区别为什么可能产生技术效果

### 3.1 机制、因果关系及代价

以下是设计机制推导的效果，不是本项目实测结果。

| 机制 | 成立条件及因果关系 | 可观察效果 | 同时报告的代价或反效果 |
| --- | --- | --- | --- |
| 范围依赖与类型化影响 | 依赖登记覆盖实际读取范围，新增匹配成员使相关派生对象失效；按类型限制扩展 | 新增消费者漏标减少，局部重分析量可下降 | 动态边界导致扩围、误选及更多重算 |
| 前后画像分离传播 | 每条解释路径只使用一个固定版本 | 减少跨修订拼成不存在路径的错误解释 | 双版本存储、比较和沿革维护成本 |
| 验证缺口驱动补全 | 缺口关闭条件指向具体观察映射或执行准备 | 减少无依据断言，调查围绕实际阻塞项推进 | 调查次数可能增加，独立预期缺失仍需外部输入 |
| 清单完整分包及归并 | M独立固定，原子条件不截断，归并校验覆盖全部ID | 静默遗漏转为显式缺口，避免分母随生成缩小 | 更多分包、重复全局上下文、更高tokens或阻断率 |
| 全部尝试及原观察重算 | 运行登记可信且完整，实际目标可确认，观察满足完整性条件 | 控制选择性送审、跨业务键拼接及旧证据误接纳 | 观察适配器、归档和判据重算成本 |
| 失效屏障及使用前重验 | 所有登记、判定和使用路径检查同一相关guard | 控制批准撤回、迟到失败及发布竞争造成的过时结论使用 | 暂时阻断、竞争重试和锁开销 |
| 按语义依赖分型回流 | 能区分只追加观察与改变当前契约前提 | 避免每条日志都重建契约或全量重测 | 分型本身的计算及错误分类风险 |

这些效果在常规实现中也可能出现。只有对照结果说明本方案的特定协作关系解决了强基线仍存在的问题，才有助于解释技术贡献；“只重算受影响部分更快”通常是增量计算本身的可预期效果。

### 3.2 构造例 退款回调变更

以下均为构造输入与规则预期，不是实际运行记录。

初始批准判据为：隔离退款60元，同一退款事件重复回调后，账本只出现一次记账，金额合计6000分。最初查询没有找到异步消费者，但保存了查询范围依赖。

| 事件 | 本方案必须形成的可核结果 | 对照所检验的机制 |
| --- | --- | --- |
| 新增回调文件 | 旧空查询范围重评，找到相关订单、账本和对账路径；映射未知则保留缺口 | 只依赖旧命中文件的实现会漏报；具备范围依赖的常规实现也应通过该项 |
| 接口返回成功，但账本业务键未知 | “重复回调一次记账”义务保留，派发观察映射调查，不记录业务通过 | 检验缺图是否导致义务消失或生成不可执行断言 |
| 固定预算放不下联合条件 | 返回显式超限/缺口；禁止只保留接口成功断言 | 检验条件分包与跨批归并，而非比较谁生成用例更多 |
| B2两次回调完成后，完整账本查询得到两笔各6000分 | 原始观察为count=2、sum=12000；完整判据失败，同构建一次后续成功不能覆盖 | 检验完整尝试集合、有效反例和判据资格 |
| 修复为B3 | 复用适用资产，取得B3新计划和新证据后重新判断，B2失败历史保留 | 检验资产复用与通过结论复用的分离 |
| 判定后、使用前撤回相关批准 | 相关guard变化，旧结论/许可不能继续消费 | 检验时序竞争，不能仅证明计划创建时校验过 |

如果常规技术组合也能得到上述结果，该案例本身不证明创造性。它首先提供可重复验证的行为规范，再用于比较更细的开销、误判和状态一致性差异。

### 3.3 指标和公平对照

用独立审阅的适用义务、受影响集合和受控缺陷作为参照，不能用系统自己的图谱或模型自评作真值。

| 指标 | 定义或记录方式 |
| --- | --- |
| 必验遗漏率 | 被清单静默遗漏的适用必验项 / 全部适用必验项；与“清单中存在但尚未满足”分开 |
| 影响漏选率及过度选测 | 漏选的应验项 / 全部应验项；额外选测项单独统计 |
| 无效证据接纳率 | 被接纳的无效证据 / 送入评估的无效证据，区分错构建、错业务键、不完整观察等原因 |
| 错误准入与错误阻断 | 错误放行轮次 / 应阻断轮次；错误阻断轮次 / 应通过轮次 |
| 有效完成率与未知比例 | 在给定资源内正确完成判断的轮次，以及因未知而未完成的比例，防止靠全部阻断得到零错误放行 |
| 性能及资源 | 变更到有效判断的p50/p95、重新解析对象数、访问边数、查询次数、模型tokens、峰值内存及证据存储增量 |
| 历史复核 | 固定原依赖复算结果的一致性，与当前适用性判断分别记录 |

所有比率在分母为0时记为不适用，不填0%。比较对象包括：全量回归、常规影响选测、动态图谱测试与覆盖管理及证据门禁组成的强基线、本方案，以及分别去掉范围依赖、义务归并、完整尝试核验和使用前重验的消融版本。

各组使用相同来源修订、批准预期、初始资产、目标构建和环境。全量回归也不自动成为业务真值，因为已有测试可能缺少新行为断言。性能在相同质量要求下比较，同时记录阻断与重试；测试预算不足时不得通过少测得到更低延迟。当前没有这些端到端实测数据，不填写收益比例，也不能将其他文献的数字移作本项目效果。

## 四 是否属于容易想到的常规改动

### 4.1 判断口径

中国专利法要求发明具备新颖性、创造性和实用性。新颖性与创造性的比较方式不同：一项明确方案是否已被单独公开，与在既有技术启示下是否容易得到该方案，是两个问题。[《专利法》第二十二条](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html)

创造性分析依次确定最接近技术、区别及其实际技术效果，再判断解决该技术问题是否存在结合启示。实际问题不能写成“如何增加本方案的某字段/步骤”，否则把答案带入问题。这里可检验的问题是：**在来源、生成资产及执行结果持续变化且分析存在不完整状态时，如何保持测试责任和目标版本判定的一致性，并控制重复计算。**[国家知识产权局三步法解读](https://www.cnipa.gov.cn/art/2024/1/18/art_2199_189864.html)

自2026年1月1日起施行的指南修改进一步强调，应评价权利要求限定的整体方案；对技术问题没有贡献的附加特征通常不能带来创造性。因此，数据库类型、通用Agent数量、名称和无关字段不能靠堆叠形成贡献。[国家知识产权局第84号令，第六项及相关算法审查修改](https://www.cnipa.gov.cn/art/2025/11/14/art_99_202568.html)

### 4.2 有明确动机的常规组合

以下“风险”是技术评估，不是授权概率，也不是已完成法律结论。

| 可能的组合起点 | 为什么本领域人员有动机组合 | 本案仍须证明的具体联系 | 当前风险 |
| --- | --- | --- | --- |
| P1/P2 + P6或L1 | 测试图谱需要可追溯上下文，模型生成需要代码与需求材料 | 相同义务清单如何约束召回、分包和生成拒收，且不能由排序缩小 | 宽泛RAG加动态图谱重合高 |
| P1/P3/P4/P5 + C2 | 路径覆盖和需求覆盖互补，缺项直接触发补生成 | 缺图、用例淘汰及预算变化叠加时，独立义务及原预期怎样仍保持有效 | 单纯完整覆盖或缺口补图重合高 |
| L3/C1/P10 + 动态画像 | 增量系统需要知道未命中范围是否新增内容 | 语义查询范围、关系决定、义务和证据资格如何共享精确失效规则 | 单纯空召回依赖很容易被已有机制解释 |
| P2/P7/P8 + C3/Sigstore | 测试执行产生结果，部署需要目标工件与验证依据 | 服务端完整库存、联合原观察、失败保留和结论消费怎样共同防止过时通过 | 版本匹配及证据门禁的拼接风险高 |
| 已有依赖系统 + CAS/事务 | 读取后发生变化会导致过时状态提交 | 哪些依赖共用guard、何时设屏障、如何处理分页失效及迟到结果 | 加时间戳或普通重验属于常规设计倾向 |
| L1/L2/L5 + 测试工具调用 | 任务发现知识不足，自然需要调查或细化模型 | 真实业务反例、测试故障和画像缺口如何分流，补证不改写独立预期 | 通用反馈闭环不能独立支撑创造性 |

“组合可实现”不自动等于法律上显而易见；但“同一篇没有同时出现全部模块”也不能反向证明创造性。需要考察这些机制是否彼此产生必要的功能联系，还是分别发挥各自已知作用。

### 4.3 当前能够支持的判断

| 评估项 | 当前证据能支持什么 | 当前不能支持什么 |
| --- | --- | --- |
| 宽泛创新主张 | 多源动态画像、影响选测、缺口补全和执行反馈有直接重合 | 不能将此前三个高层概括认定为已确认独有 |
| 收窄组合的新颖性 | 针对2.1所列候选组合K，本轮尚未识别出同一篇文献中同一技术方案直接、无歧义地披露K1—K5全部组合特征 | 没有正式权利要求和穷尽检索，不能作肯定新颖性结论 |
| 收窄组合的创造性 | 可以围绕分母保持、完整证据接纳与失效竞态提出具体反例和因果验证 | 各部件已有强先例，当前无证据证明组合超出常规工程整合 |
| 可实施性及效果 | 已有数据契约、模块接点和可执行算法描述，部分组件存在源码 | 完整链未贯通，不能宣称端到端收益或把源码存在等同法律上的实用性已获确认 |

当前较值得继续围绕的技术限定是：**同一组带批准修订的义务，在画像缺口、上下文分包、执行尝试及证据接纳中保持可追踪且不可静默缩减；相关来源、批准或执行库存变化时，使依赖结论失效，并在正式使用时核验这一变化。**

其说明必须给出明确对象、状态转换和失败分支。若常规强基线采用需求清单、依赖缓存和证明门禁后已能同等处理这些情况，或者各机制删除后其余部分仍独立获得同样效果，就需要进一步收窄，不能仅通过重新命名为“画像共同演进”解决创造性问题。

## 附录 当前实现依据与事实边界

当前专利工作树提交为`3b932f6`。2026年10月29日核对远程`nasus_snapshot_v1`仍为`38e123c89fdb1dc8602a10f56f45fbdfdeb86e86`，提交时间2026年10月27日21:06:26 +08:00；当前产品及设计目录与该来源提交无差异。

| 源码接点 | 本轮可确认的能力 | 尚不能扩大解释的部分 |
| --- | --- | --- |
| [semantic_applicability.py](../../../apps/api/app/domain/system_image/semantic_applicability.py)，assess_semantic_decision | 身份、端点及来源修订变化使原决定需重评，同修订否定保留 | 不代表全部目标关系类型和验证四槽已实现 |
| [code_impact.py](../../../apps/api/app/domain/system_image/code_impact.py)，conservative_code_impact | 有界方向遍历，限制跳数及实体数，并标记截断和动态影响未验证 | 不代表完整跨服务字段级影响或最小回归集合 |
| [derivation_impact.py](../../../apps/api/app/domain/system_image/derivation_impact.py)，assess_derivation_impact | 来源变化考虑query_scope_changed；有界派生图保守失效 | 当前最多128个依赖节点，不能表述成全项目细粒度增量已完成 |
| [generation_batches.py](../../../apps/api/app/domain/quality_loop/generation_batches.py)，constraint_units、verify_batch_plan | 联合条件不可拆、全局规则可见、义务归属及整体完整性核验 | 结构完整性不证明生成步骤的业务语义正确 |
| [test_design_generation.py](../../../apps/api/app/domain/quality_loop/test_design_generation.py)，generation_obligations、_planned_rows | 固定判据和义务行，要求每项映射用例或显式缺口 | 当前行ID包含scope修订，跨轮稳定沿革仍属新增设计 |
| [run_plan_case_execution.py](../../../apps/api/app/domain/quality_loop/run_plan_case_execution.py)，状态返回部分 | 区分未派发、原始观察和未知结果，保留原派发绑定 | 返回business_coverage_verified=false、canonical_execution_committed=false；不能将其记为正式业务通过或发布准入 |

最终态细节见[技术实施方案](./technical-implementation-2026-10-29.md)与[整体闭环方案](./closed-loop-invention-design-2026-10-29.md)。本轮进行了源码和公开文本核读，没有运行产品测试、外部代码或完整对照实验。退款例及指标方案用于说明可验证机制，不作为实验记录。

PostgreSQL、全文/向量索引和可选图数据库是实现载体。它们可以影响查询成本，但不会单独解决关系正确性、义务遗漏或证据适用性，也不在本报告中被认定为独立创新点。
