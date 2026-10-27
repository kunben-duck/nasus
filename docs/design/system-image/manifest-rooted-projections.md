# 来源清单作为冻结画像的根

更新：2026-10-10。新冻结画像使用已有 SourceManifest 和 ImageRevision 作为真实输入与成果根，不再补出没有实体修订的 Project Core 对象。该调整修正对象来源语义，不改变正式发布、需求批准或执行覆盖门禁。

## 输入与对象

- ImageCandidatePreparation 将确切 manifest 传给抽取器。每个代码对象必须固定 entity、entity revision、source revision；文档必须固定 document revision、source revision，且来源种类匹配。
- 全部选定代码必须 captured；可选文档或测试采集失败继续保留在 manifest 中，不伪造对象来补齐它们。
- 对象唯一、关系端点封闭在同一画像，关系和指标属于同一 project/baseline，并携带非合成来源引用。至少有一个真实代码对象及代码质量观察；合法的单文件画像可以只有一个对象和零条依赖边。
- 成员准入不是完整扫描、精确运行依赖解析或业务正确性判定。范围完整性、unsupported/failed 清单、证据跨度和下游 readiness 仍分别核验，不能仅根据数量宣布 ready。

## Provider 观察与成员准入

原生 Provider 可以返回无法唯一对齐到语法身份的节点。身份归一化保留这些观察，不伪造 symbol key；对应 Provider 的投影报告追加计数式 `unresolved_symbol_identity` / `ambiguous_symbol_identity` 缺口。重复归一化重新计算这些计数，不累计旧计数，已有其他缺口和 Provider 观察总数保持原含义；含缺口的报告不能标为 complete。

新冻结抽取必须接入 Nasus 实体注册端口。抽取器先向既有分析 inventory 提交未经成员过滤的结果，再只准入已注册的实体；关系只保留两端都已准入的边，画像指标统计准入对象，而不是拿 Provider 原始数量冒充正式成员数量。若需要排除未注册观察但没有持久分析回执，整个冻结准备失败，不悄悄丢弃，也不使用 legacy ID 补齐。

这里持久保存的是已有分析报告中的逐文件/结构观察、Provider 元数据和缺口；原生 generation 另有投影 hash/数量固定。不能把这些回执称为全部原始 Provider 节点及边的永久归档，或完整结构理解。身份不确定项的后续调查、完整观察工件和用途 readiness 仍按主方案推进。无 manifest 的旧直接抽取保持历史展示行为，不因此获得冻结成员或业务权威。

## 追溯与历史

复用 0070 已有的对象来源 DAG：image_objects 的父节点恰好是一个 manifest 和全部 member；manifest 固定纳入的来源修订，member 指向自己的 code/document 与 evidence。不引入另一套 System 节点、重复 schema 或新迁移。

冻结工件只保存真实对象及其既有关系；去掉合成根也去掉对象到该根的展示边。implements/asserts、人工审阅、独立需求 oracle 和执行证据继续使用各自契约，不把普通图边提升为已批准语义关系。

后续清理了冻结路径里残留的 `CrossSourceEntityResolver` 名称/标签推断：它只保留在无 manifest 的 legacy 显示抽取，新冻结画像只接入实际代码结构观察，不能因三源同名制造 `implements/covers/validates`。显式 references 与有双方原文的 implements/asserts 继续走独立提案、审阅和冻结成员契约；没有跨源关联也能保存合法零边结构候选，不伪造边满足数量门禁。

冻结指标现在是准入对象清单：代码、结构关系、需求、AC、业务规则、历史用例和脚本分别计数，标记 `measurement_basis=admitted_projection_inventory_not_quality_assessment` 与 `coverage_status=unknown`。不从数量或同名匹配推导业务覆盖率、关键路径、风险、失败运行或已验证质量分数。TaskContext、Agent/Build readiness 接受真实零边输入，但仍保留缺口，不把它晋级为完整质量评估。

0097 将该未评估标记传递到兼容 `QualityProfile` 和 `TaskContext.confidence`，对应风险/覆盖/自动化/放行分数及 confidence 为 null，不用缺省值或旧数值覆盖 unknown。PG nullable 迁移不重算历史，不能降级时补造 0。放行评估将未知质量列为 blocker，US/资产包保持 blocked；平台治理检查当前已保存的 readiness 与运行证据，旧 ready 决定和审批不能覆盖它。该检查不是原子 ReleaseContext 或目标 build/oracle 的完整一致性证明。

未标记的历史评分公式仍保留，旧生成流程和运行资产消费者的完整切换尚未交付。`TaskContext.readiness` 不代表独立业务 oracle、生成或执行许可；正式新链使用独立批准与固定 ContextPack。不能把本项修复扩大为所有启发式、五用途与真实闭环已完成，旧链 cutover 仍属 P3/P5 交付要求。

后续生成步骤也不再把“生成成功”直接写成已验证质量或自动批准：范围、场景、用例及自动化等生成工件保持需要独立审阅，不能用生成数量填充执行覆盖。新[自动化输入检查](./automation-input-preview.md)消费固定 ContextPack/范围/草稿/独立映射，保留原 oracle 和强制分母；它只推进新消费边界，尚未替换旧 TaskContext 驱动的脚本、固定目标执行及发布证据链。

原 v1/v2/v3 序列化、画像哈希、审阅成员和历史读取保持不变。有合成根的旧工件仍可以在重新授权及完整性验证后读取，不重算或改写其内容。直接 legacy 抽取接口保留旧显示契约，但新冻结准备与 baseline 初始化使用 manifest 校验；兼容工作区的 ready 字段不等于正式 publication head。

## 验证范围

纯领域回归覆盖零边、可选失败、不完整身份、错来源种类、跨项目/基线关系和指标、重复成员、合成证据以及坏清单摘要。抽取回归另验证未注册节点不变为正式成员、缺失注册端口/分析回执拒绝、legacy 路径不变及缺口归一化幂等。隔离 PG/MinIO 的 HTTP 回归独立检查新成员、持久 DAG、旧工件字节/引用不变和确认式初始化不自动发布。

固定 exweb 验证须核对全部画像成员都固定真实来源，持久 DAG 与重新推导结果一致，并逐一回读规范代码成员的归档跨度。原生 Provider、自然聊天/同目标补源、浏览器与纯测试分别记录证据，不互相代替；各批实际终态见[实施记录](./implementation-progress.md)。配套需求和用例为显式验证夹具，不是 exweb 维护者批准或真实执行结果。

## 仍需交付

候选交付的原子完成报告和 Goal 终态、完整动态调查/反证与预算、来源 cutover/lineage、多格式、自动 delta/overlay/合并、五用途上下文、RunPlan 与真实执行反馈、Provider 对照/隔离/gold/性能和完整 V1/P6 门禁继续按原 P0-P6 方案实施。删除合成根本身不代表系统画像模块完成。
