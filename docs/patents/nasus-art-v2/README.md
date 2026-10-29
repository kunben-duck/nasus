# Nasus 专利 V2：讨论结论与实现基线

> 实现快照固定日期：2026年10月27日；最新方案与远程核查日期：2026年10月29日（Asia/Shanghai）
>
> 专利分支：`2026/nasus_art_v2`

当前整体方案见[系统画像与集成验证共同演进的自驱闭环方案（2026年10月29日）](./closed-loop-invention-design-2026-10-29.md)。该方案将多源画像、大模型自主行动、完整验证义务、自动执行、评分准入及增量回流作为一个发明主题，并明确当前实现与新增设计的接点。

具体数据契约、模块接口、判据执行、Agent调度、双增量提交及落地顺序见[三项候选创新的技术实施方案](./technical-implementation-2026-10-29.md)。该文件是实施设计，不代表新增产品能力已经交付。

其中第3.5—3.10节补充最终态系统画像设计：函数变更沿调用、字段数据依赖和需求关联传播到测试；跨服务业务路径及验证缺口编译；完整义务与辅助材料的双通道召回。PostgreSQL 可作为完整实现基础，图数据库作为经工作负载验证后可增加的查询投影。

当前评审演示文稿：[9页专利申请评审 PPT（2026年10月29日）](./presentation/Nasus_专利申请评审_9页_20261029_v2.pptx)。覆盖背景、现有技术、总体方案、三个候选保护点、技术效果及四组相似专利对照。第4—6页详细说明关系字段、建图与影响传播、完整义务分包、缺口调度、目标证据接纳、准入与双增量更新算法；第7页以两轮退款及修复构建展示义务、观察和判定；第8页列出效果机制、指标定义和实现边界；第9页合并检索情况与专利对照。备注保留补充技术说明及来源，构造推演不代表实测收益。

核心候选组合为：**由版本化验证义务共同驱动画像完善、测试行动和准入判断，通过带验证条件的画像补丁联动更新关系、义务及证据适用性，形成下一轮画像。** 三个相互配合的机制是验证目标反向驱动画像构建、未兑现义务驱动自主行动、画像变更与验证结论同步演进。

[讨论结论汇总（2026年10月28日）](./conclusions-2026-10-28.md)保留为前一轮研究记录。其中两项候选方向继续作为整体方案的基础：

1. **系统画像的有效构建**：基于版本化证据和关系审阅适用性的多源系统画像构建与更新。
2. **系统画像的有效使用**：基于完整验证义务编译的测试生成、校验及版本适用性管理。

上述整体组合包含已有实现和新增可实施设计，不表示已经确认新颖性、创造性或可授权性。现有专利正文仍保留 V2.1 内部 Idea 评审版；历史正文、PDF、附图和 PPT 不因本次方案更新而自动成为最新版本。

## 实现来源

| 项目 | 固定值 |
| --- | --- |
| 来源分支 | `nasus_snapshot_v1` |
| 来源分支最新正式提交（2026年10月29日远程核对） | `38e123c89fdb1dc8602a10f56f45fbdfdeb86e86` |
| 正式提交时间 | 2026年10月27日 21:06:26 +08:00 |
| 初次固定快照时的来源父提交 | `111644be71709cc7856acef854ce00f59ec448b9` |
| 实现快照提交 | `50e82a95ce1ef975862dbe8038a98d307490d831` |
| 实现内容树 | `de4c1ca2dcd27546807dac78865ae351c265c990` |
| 既有专利资料来源 | `2026/nasus_art_v1`，提交 `76f5dc538cb9931ee0f607e732b00e837374dc62` |

初次固定时，最新实现位于来源分支的暂存区，共 2,210 个文件变更（316 个修改、1,894 个新增）。实现快照以当时的来源提交为父提交保存完整内容；该次固定没有修改来源工作区。随后来源分支形成正式提交 `38e123c`，其完整内容树与快照 `50e82a9` 相同。2026年10月28日再次核对远程来源分支仍指向该正式提交；专利分支的产品代码和设计目录与来源分支一致，差异限于专利资料。

原专利分支的四次文档提交按顺序带入新分支，并在提交说明中保留原提交引用。已有资料入口：

- [专利 Wiki：V2.1 内部 Idea 评审版](../nasus-art-v1/README.md)
- [该版本 PDF](../nasus-art-v1/nasus-patent-v2.1.pdf)
- [原五张附图](../nasus-art-v1/assets/)

上述正文、PDF 和附图保留原版本日期，尚未按照最新讨论结论重新修订。当前整体方案以2026年10月29日的闭环设计为准，基础构建细节和此前研究沿革见2026年10月28日结论汇总。

## 当前实现与讨论边界

| 技术环节 | 本次代码核查依据 | 后续讨论的实现口径 |
| --- | --- | --- |
| Agent 结构构建及完成评估 | [结构构建入口](../../../apps/api/app/application/system_image/structure_builds.py)、[实际构建来源追溯](../../../apps/api/app/application/system_image/build_lineage.py)、[完成评估](../../../apps/api/app/domain/system_image/build_completion.py) | 已有固定计划、完整来源及实际分析追溯的受控结构构建；当前结构能力不调用模型。完成评估仍保留 blocked 和真实缺口，不能将结构或证据核验成功解释为自主画像完整交付。 |
| 来源修订与变化识别 | [来源差异算法](../../../apps/api/app/domain/system_image/source_delta.py)、[代码成员比较契约](../../design/system-image/code-member-deltas.md) | 已有同来源双修订比较、完整采集证明及未决项处理；画像成员增减不等于源文件真实增删，不能据此声明完整行为影响分析。 |
| 派生依赖与画像失效 | [冻结查询范围](../../../apps/api/app/domain/system_image/derivation_registry.py)、[保守影响计算](../../../apps/api/app/domain/system_image/derivation_impact.py)、[持久失效入口](../../../apps/api/app/application/system_image/context_invalidations.py) | 已有完整来源范围依赖和有界派生图的保守影响、显式持久失效；当前使用失效与历史内容分离。全项目自动增量、精确影响传播和最小回归集合仍不能作为已实现结论。 |
| 知识画像发布 | [画像发布服务](../../../apps/api/app/application/system_image/publications.py)、[画像发布契约](../../design/system-image/image-publication.md) | 已有独立批准、固定候选及来源、预期发布头比较和原子提交。知识快照发布、Agent 目标交付及业务版本发布准入是不同状态。 |
| 验收条件与测试生成 | [完整条件分包](../../../apps/api/app/domain/system_image/context_partition.py)、[义务与生成校验](../../../apps/api/app/domain/quality_loop/test_design_generation.py)、[测试生成契约](../../design/system-image/test-design-generation.md) | 已有由固定 AC、规则、范围项及正反例生成稳定义务行的组件；输出须逐行映射或列明缺口，原判据正文和摘要须一致。该校验不证明步骤语义正确；来源变化自动编译完整业务必验集合的整体链路仍需独立论证。 |
| 独立用例准入与当前适用性 | [用例准入服务](../../../apps/api/app/application/quality_loop/case_approvals.py)、[知识契约](../../design/system-image/knowledge-contracts.md) | 已有独立批准、撤回、固定输入及读取末尾审批头复查。映射接受不直接等于用例批准，用例批准不直接等于目标执行或验证通过。 |
| 脚本生成及逐动作审阅 | [脚本准入检查](../../../apps/api/app/domain/quality_loop/automation_case_admission.py)、[动作及断言绑定审阅](../../../apps/api/app/domain/quality_loop/automation_script_review.py) | 新脚本生成消费独立用例准入；动作及判据绑定逐项接受、拒绝或暂缓。脚本审阅接受不授予实际目标执行权，也不增加正式验证覆盖。 |
| RunPlan 执行及原始观察 | [执行服务](../../../apps/api/app/application/quality_loop/run_plan_case_execution.py)、[任务生命周期](../../../apps/api/app/application/quality_loop/run_plan_case_jobs.py)、[执行状态](../../../apps/api/app/domain/quality_loop/run_plan_case_execution.py) | 已有公共执行任务、持久派发登记、原始观察归档及未知状态处理基础；任务完成不能直接解释为全部业务断言通过，不能将内部观察直接记为正式验证覆盖。 |
| 正式覆盖、发布准入及反馈 | [执行契约](../../design/system-image/run-plan-case-execution.md)、[任务契约](../../design/system-image/run-plan-case-jobs.md)、[完整交付门禁](../../design/system-image/delivery-and-evaluation.md) | 新执行状态仍返回 `business_coverage_verified=false`、`canonical_execution_committed=false`，正式覆盖计数不因原始观察自动增加。正式义务覆盖、实际目标有效证据、发布准入与自动回流的完整链路仍未全部贯通。 |

本体模型保留为可选的知识表示和约束方式。后续讨论优先分析来源范围依赖、依据失效、必验义务保持及目标证据接纳之间的具体技术联系，不把本体、通用模型或图谱作为已经确认的独立创新。

## 核查与验证口径

- 本次执行源码及契约只读核查、Git 基线和文档一致性检查，没有运行产品测试。
- [实施与验证记录](../../design/system-image/implementation-progress.md)标注的更新日期为 2026年10月13日。其中测试结果属于各自历史批次；“运行中”只表示当时观察，不表示当前仍在运行。
- 没有本次端到端测试结果，也不据此宣称全部 P0—P6 或 V1 发布门禁通过。
- 后续如纳入新的实现，需固定新的提交并更新本页；不能只凭同一分支名称认定实现内容未变。
