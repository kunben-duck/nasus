# 派生依赖登记与冻结查询范围

更新：2026-10-07。0068 将当前新测试设计链的派生依赖登记到 PostgreSQL，并记录上下文所依赖的完整来源组合。它推进 P4 的项目级索引底座，不替代完整变更计划、自动失效或增量重建；实际验证结果见[实施记录](./implementation-progress.md)。

## 登记范围

`nasus.derivation-registry.v1` 登记以下已有不可变业务工件，固定 project、context、canonical invocation、工件 hash 和完整直接父依赖：

```text
context
  └─ scope revision（另含 previous scope）
       └─ generation
            ├─ case
            ├─ planned coverage
            └─ mapping revision（另含 previous mapping）
```

case、coverage 和 mapping 均直接依赖 generation；mapping 的断言对还在原业务工件内固定具体 case/row/step/oracle，不能将图示误读为 coverage 批准后才生成 mapping，也不能凭父边授予映射或执行权威。

节点、父边及查询范围分别保存到 `system_image_derivations`、`system_image_derivation_edges`、`system_image_context_query_scopes`、`system_image_context_query_sources`。边的复合外键要求两端属于同一项目和上下文；重放核对原 hash、invocation 和父集合，不通过忽略冲突掩盖不同输入。数据库拒绝更新与删除，登记不会修改原 context、draft、coverage、审阅或批准。

0068 本身没有登记全部代码实体、证据、语义断言、authority、索引 generation、脚本和 RunPlan 的细粒度依赖。0070 后续增加独立的[画像对象来源子图](./object-provenance.md)，固定被准入成员的 source/code/document/evidence 祖先并在画像读取时核验；它不改写 v1 登记 hash，也未将全部语义、批准、检索和执行依赖接入统一图。不能因为所有当前 ContextPack 都已登记，就声称完整项目 delta DAG 已实现。

0071 增加[上下文来源锚点](./context-provenance.md)，在原 context/Outbox 事务内固定 registration hash 与 image_objects root hash、manifest/input/query-scope pins，回填并核对历史记录。它提供两个既有子图的持久连接，不改变 v1 父集合或摘要，仍不代表上述所有依赖或完整项目 delta DAG 已接通。

0072 新增[冻结关联子图及上下文锚点](./relation-provenance.md)，固定被画像选定的引用／语义成员、确切证据和完整审阅前驱，不追随当前 head。0068 的原父集合与摘要不变，未冻结关联和其余批准／检索／执行依赖仍待完整统一。

## 完整查询范围

上下文登记固定 image revision/hash、manifest ID/hash、input digest、全部来源成员及其 captured/failed/pending/legacy 状态。指纹与既有固定上下文影响契约一致：

```text
hash(input_digest + image_artifact_hash + complete source_members)
```

不只记录 selected hits。空召回、阻断上下文和当时未成功采集的可选来源仍有范围依赖；新增文件可能改变原本没有命中的查询。来源组合变更不会就地重写旧查询范围。

此登记校验的是已有 PG 元数据和固定关系，不是新的原文或业务语义批准。工件使用者仍须经 application ports 回读 MinIO 原文、验证完整 hash/证据、检查当前权限和用途门禁。PG 中存在一个节点不能代替这些校验。

## 原子提交和回填

四类事实事件在原业务/审计/Outbox 事务内触发基础设施投影：`system_image.context.compiled`、`quality.test_design_scope.reviewed`、`quality.test_design.generated`、`quality.test_design_mapping.reviewed`。事实先 flush，再读取同一事务中的固定元数据并登记；任一缺父、hash 冲突、漏用例或缺 coverage 都使整个提交回滚。投影不启动自己的事务、不调用 LLM、不读取私有正文、不跨域改写 repository。

登记依据是持久业务事实，未依赖 SSE 保留期或把 event replay 当作唯一恢复来源。0068 在同一迁移事务中按 context → scope history → generation → mapping history 回填；源数据损坏则迁移失败，不伪造关联。v1 投影与表定义是迁移兼容契约，后续扩展需新增版本，不能任意改变旧 hash 或 backfill 行为。有登记数据时拒绝破坏性 downgrade。

0071 实施时将 0068 DDL 固定为原字段、约束和索引的显式定义，防止当前 ORM 的新增约束提前出现在历史建表步骤。新增 hash 唯一约束只由 0071 建立，旧四表数据、摘要和回填行为不因此改写。

v1 摘要显式固定字段，不再自动序列化整个 dataclass：登记包含 policy、project、context、invocation 和节点的 kind/artifact ID/hash/完整 dependencies；影响图摘要使用同样的四个节点字段；查询范围的来源成员仅包含原 binding/type/revision/status。回填比较和首次插入也使用这四个来源字段，避免新增 dataclass 字段被当作数据库列。这些公式与原 v1 字节等价，真实字段变化仍改变摘要，未来新增 dataclass 字段不会隐式改写旧登记或回执的摘要语义。此保护不新增节点类型、改变权限、扩大影响闭包或替代后续版本迁移。

回填按有界游标批量读取；用例每批 256 项登记，节点总数不使用原影响预览的 128 节点限制，也不截断到前 N 项。该实现不代表 32768-case 端到端容量或 p95 性能门禁已经通过。

## 查询接入和错误保护

[来源上下文反查](./source-context-roots.md)开始消费 query-scope 来源索引；[质量派生图](./context-change-impact.md)的 scope/generation/mapping inventory 开始消费登记表。两者均在一次 SQL 快照中核对索引与原始固定事实的完整计数，缺项或不同 pin 不返回一个看似完整的子集。

计数前仍过滤完整画像来源的当前访问权；无权画像不会进入校验总数。canonical 回执契约不变，旧页不混入未来工件，权限变化仍拒绝回放。完整原文验证继续留在 application service，不在 SQL 索引中缓存授权或敏感正文。

固定影响查询仍保留 128 节点／64 KiB 上限，超界拒绝，不把登记容量与该公开契约混为一谈。没有新增旁路写 API、自动批准、生成或执行许可。

## 后续完整交付

继续将实体／断言／authority／检索／脚本／RunPlan 纳入反向依赖，构建固定项目输入的完整变更计划与原子失效、动态增量调查及重建。还需 overlay/tombstone、三方合并和回滚、webhook/reconciliation、五用途与旧链切换、真实目标运行反馈、Provider 生命周期／对照／gold／隔离，以及完整容量、恢复、安全和 V1 门禁。完整 P0-P6 范围保持不变。
