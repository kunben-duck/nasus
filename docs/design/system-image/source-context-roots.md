# 来源修订的上下文反查

更新：2026-10-07。P4 新增项目内的来源修订反向发现入口，不再要求调用者提前知道 ContextPack ID。该入口查找当前有权读取的历史画像与上下文根；不等于完整项目业务影响分析，也不执行失效或重建。运行证据见[实施记录](./implementation-progress.md)。

## 来源与上下文关系

反查使用已有不可变关系：SourceRevision → SourceManifestMember → ImageRevision → ContextPack。项目、binding、来源修订和 captured 状态必须精确匹配，不能连接可变 source head 或工作区别名。被阻断或没有召回命中的上下文仍可能依赖原查询范围，不能按 selected hits 排除。

0068 开始消费[冻结查询范围来源索引](./derivation-registry.md)，并在同一 SQL 快照校验原始 FK 根与索引根的完整计数。索引缺项时返回完整性错误，不静默漏掉上下文；该接入不改变分页、授权或原文回读要求。

一次 SQL 从同一快照计算总数和 keyset 页，包括空页的总数。计数前排除包含任何当前无权 binding 的画像；总数只表示当前授权范围的归档根，不透露隐藏画像数量。读取每个选中根时，经 application ports 完整回读 ContextPack 和冻结画像，核验双方工件摘要以及固定来源成员。同一操作内复用已验证的画像；不跨操作缓存授权。

默认每页 20、最多 50 个根，响应与 canonical 回执各最多 64 KiB。每页只验证本页工件，不声称页外档案或所有下游图已通过校验。归档回读和 SQL 的完整容量/性能门禁尚未验收。

## 入口与固定回执

```text
GET /v1/projects/{project_id}/system-image/source-context-roots
    ?before_revision_id=...&after_revision_id=...&after_id=&limit=20

query.system_image.sources.context_roots
```

双修订必须属于同项目、同 binding。before 是要反查的固定来源；after 用于验证差异并给出是否需要重新调查的信号。无变化仍返回 before 的归档根，不伪造变化或执行许可。

canonical 查询复用 ToolInvocationRuntime 的项目权限、审计和 Outbox，不要求写入确认。回执只保存项目、修订、根 ID/hash、总数、游标、差异摘要和来源权限 fingerprint；不保存源码、用例正文、oracle、私有地址或凭据。Agent 沿用既有详细工具预算，旧回执通过共享 image-query observation port 重新授权后展开。

回执固定观察时的这一页与总数；后来新增上下文不会补进旧回执。权限 fingerprint 变化时，连空页旧回执也返回 source_access_changed，不重放以前的隐藏数量。用户可显式发起新查询获得当前可见集合；回执不是长期授权凭证。

来源及工件完整性错误返回脱敏 502，来源撤权/范围变化拒绝整个读取，不返回部分 pins 或诊断正文。HTTP 响应 private/no-store。没有旁路写接口或模型调用。

## 与更新链路衔接

拿到每个根后，可通过[固定上下文影响预览](./context-change-impact.md)独立验证其已有 context/scope/generation/case/coverage/mapping 图，再经[独立确认的失效命令](./context-invalidation.md)提交精确画像门禁。反查本身不自动执行这两个步骤，不把多个页或图当成一个原子项目快照。

结果固定 discovery_scope=authorized_archived_context_roots_at_observation；page_evidence_verified=true 仅指当前返回页。downstream_dependency_graphs_verified、impact_complete、invalidation_applied、generation_authorized 和 execution_authorized 均为 false。

## 验证与完整交付

纯测试覆盖多画像、空页、完整 pins、范围与摘要错配、受控回放、未来根不混入、撤权及无正文回执。PG 专项验证实际 FK joins、追加式历史、canonical/Agent 观察、分页、损坏注入和另一个来源受限时总数不泄露。exweb 专项使用实际相邻 Git 对象导出、隔离 PG/MinIO 与明确标识的合成需求/用例；不运行 exweb/Maven、不调用外部模型，不把合成资料当作维护者业务 gold。

尚需全项目 Derivation/query-scope 索引、实体/断言/摘要/脚本/RunPlan 的反向依赖闭包、原子计划与增量调查/重建、negative scope 更新、overlay/tombstone、merge/回滚、五用途与旧链切换、真实执行反馈、Provider 对照/gold/隔离、性能和最终 V1 门禁。本入口是这些能力的前置，不改变完整 P0-P6 范围。
