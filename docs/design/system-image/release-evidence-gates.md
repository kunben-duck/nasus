# 画像质量证据与发布阶段门禁

更新：2026-10-11。系统画像的来源、对象及关联库存不是质量测量；模型生成资产、工具完成和人工审批也不能替代执行或规范证据。本文记录已实现的状态一致性规则，不声明完整 P5 或 V1 验收。

## 统一推进条件

`meets_release_review_threshold` 是纯领域判断，发布阶段的 US/资产 lane/asset part、应用层对话提示和项目工作区的 `ready_for_release` 投影共同消费：

- 原评估状态必须为 `Ready for release review`，分数是 80–100 的整数。
- blockers、approvals_open、pending_merge 必须为整数零；布尔值、缺字段及损坏类型不能作为有效计数。
- evidence_summary 中 `quality_assessment_unknown` 必须为整数零；明确 unknown 不会被高分覆盖。旧评估缺该字段保留原已知评估契约，不改写历史工件。
- 工作区另外核对评估的 version_id 是当前工作区版本；全部资产 lane 完成也不能取代评估。

发布阶段曾只检查 `blockers`，因此低分但无硬 blocker 的评估可能将 US 标成 release_ready，与工作区投影冲突。现统一上述判断；不符合条件时 lane/asset part/US 保持 blocked，不推荐 approval.request，原分数、指标及 evidence refs 保留。缺少实际 blocker 文案时仍保留原评估 summary，不制造新的执行或规范事实。

应用层曾另用 blocker/unknown 布尔值选择 assistant follow-up，导致低分但无硬 blocker、未完成审批/合并或状态不合格时，lane 已阻断而回复仍声称可进行发布审阅。现直接使用原领域 plan 的 US 状态，不重复推导或调用另一评估。应用测试覆盖这些负例及 80/100 分的合格路径，核对原 score/evidence、不调用模型、资产/US 更新、推荐工具和对话提示一致；合格路径测试使用明确的端口 double，不是正式运行放行证据。

## 评估、审批与真实放行分开

`release.assess` 完成表示评估工具已经执行，不代表质量通过。Agent 的八步工具链可以完成控制流程，但它产生的用例及场景仍需独立审阅；待审阅资产不能自动变成 approved。来源库存的 risk/coverage/confidence 等 unknown 保持 null，发布评估增加明确的未知质量 blocker。

审批只授予操作权限。已有未知质量时，即使审批被人工批准，release decision 仍 blocked，baseline.promote 拒绝；失败审计记录应存在，原 baseline 不改变。已有失败报告和未知质量是不同 blocker，不能只保留其中一个以满足旧的计数断言。未知质量、待审阅资产和发布阻断在 PG 重启读取后仍需保留。

本次不修改 ReleaseDecision 的既有条件放行政策、不制造正式质量测量、不授予 RunPlan 执行权限，也不升级开发探针的 HTTP 观察为正式 coverage。真实批准规范、版本适用的覆盖矩阵、目标构建及独立执行/fixture/locator 授权、逐用例运行事实到发布判断的链路仍是完整目标。

## 回归契约演进

旧 API 七项回归包含过时假设：生成后自动批准、来源库存有质量分数、审批可推进未知质量，以及失败报告是唯一 blocker。现在改为显式负向契约；保留工具顺序、结构化生成内容、原调用/存储证据、US 选择、失败分析/人工接管和重启恢复检查，增加 blocked、unknown、待审阅及不晋级 baseline 的断言。

原正向真实业务闭环验收没有因此被删除：独立规范和真实目标执行支撑的完整放行仍须交付，不能用新的负向测试通过宣称完成。首次专项暴露单独运行时待审阅资产与通用 summary 的错误测试假设，失败日志保留；最终门禁证据与模型/Runner 协议 specimens 的边界见[实施记录](./implementation-progress.md)。
