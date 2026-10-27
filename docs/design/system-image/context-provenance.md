# 上下文与画像对象的来源锚点

更新：2026-10-07。0071 将 0068 的上下文派生根与 0070 的画像对象来源根连接为独立、追加式的 PG 记录，不改变两个既有 v1 图的摘要。它是完整增量依赖图的一步，不是完整 P4 交付；实际验证状态见[实施记录](./implementation-progress.md)。

## 固定的连接

```text
scope / generation / case / coverage / mapping
    -> context registration
    -> ContextProvenanceAnchor
    -> image_objects root
    -> manifest / member
    -> source / code / document / evidence
```

`nasus.context-provenance-anchor.v1` 固定 project、context、context registration hash、image revision/artifact/provenance hash、manifest ID/hash、input digest 和完整 query-scope fingerprint。指纹包含全部 captured/failed/pending/legacy 来源，不仅是检索命中；空召回仍有来源范围依赖。

摘要显式固定原十个字段及 policy，不自动序列化未来 dataclass 扩展。context 和 image 的节点键从固定 ID 推导。连接不读取原文、不包含 oracle、凭据或对象 URL，不授予模型出口、生成、映射批准或执行许可。

## 原子登记和历史回填

`system_image.context.compiled` 的原事实、审计、Outbox 事务先登记 0068 的 context/query scope，再登记锚点。复合 FK 固定同项目/上下文的原 registration hash、同项目的 image_objects node/hash、画像对象根及 query-scope manifest。任一错误使 context、两类登记和事实 Outbox 一起回滚，不另启事务或跨域写质量事实。

0071 新增 `system_image_context_provenance_anchors`、按画像反查索引及 registration hash 唯一约束。数据库拒绝 UPDATE/DELETE；有锚点时拒绝破坏性 downgrade。历史回填按项目、画像、context 顺序有界读取，核对每条 context 的原 metadata、registration、完整来源范围和对象根，每个不同画像另做完整原生对象来源审计。损坏不跳过，DDL 与回填一起失败。它不回填或重写原文、审阅决定、业务期望和旧工件正文。

首次空库迁移暴露旧 0068 按当前 ORM 建表的版本漂移。0068 改为显式原 v1 DDL，不再提前创建 0071 的新约束；旧四表字段、原摘要和回填语义保持不变。实际 populated replay 与扩展 dataclass 回填需要独立验证，不能只凭空库升级成功宣布兼容。

## 正常消费者

ContextPack compile 后校验、恢复及历史回读通过 application repository port 验证锚点；验证在画像/来源读取后执行，不在领域层引入 ORM。列表先检查选中画像的访问权再核对本页全部锚点。来源反查及质量派生消费者通过原 ContextPack application port 继承校验，不增加绕过 ToolRuntime 的写 API。

锚点验证仍只证明两个固定元数据子图的连接。它不能代替完整 image native ancestry、MinIO body/hash、当前来源 ACL、批准头或 publication/model pins 的 application 校验。不得把有锚点当作原文已可读、业务规则已批准、coverage 已执行或整体依赖完整。

### 同步操作内的固定证明复用

2026-10-13 的历史读取将来源锚点和关系锚点的完整核验接入已有
`REPEATABLE READ / READ ONLY` 画像快照。仅当前 thread/task 拥有的
开放快照可保存成功证明，按 project/context 和全部原记录字段摘要
固定，最多两个 context；退出或异常清除，失败不缓存。下一操作、
复制的 ContextVar、子任务和其他线程重新建立自己的证明。

发布及检索依赖仍在新的业务会话中完整核验原 canonical 输入，
当前来源 ACL、authority、审阅头和 stale 状态不进入这个缓存。
新鲜 context 元数据须与固定证明逐字段一致。快照建立后才提交的
新 context 无旧证明，必须在新鲜会话完整检查，不缓存旧视图里的缺失。
私有归档、完整来源字节和原计划读端口不因元数据复用而跳过。
这不修改原锚点、摘要或历史，也不是当前许可、执行覆盖或 p95 的证明。

## 仍需完整交付

0072 后续增加[冻结关联来源追溯](./relation-provenance.md)，固定已选定 references／semantic 成员及证据、评估和审阅前驱，并另存上下文关系锚点。0071 的原字段和摘要不变，未冻结关联及其余 authority／publication／检索／执行依赖仍不完整。

继续将所有语义 assertion/decision、AC/业务规则 authority、publication、检索 generation/trace、脚本和 RunPlan 纳入统一反向依赖，并交付项目级原子 delta、自动失效/调查/重建、overlay/tombstone、合并与回滚。五用途、旧链切换、真实目标执行反馈、Provider 生命周期/对照/gold/隔离和完整容量/性能/安全/V1 门禁保持原范围，不能以锚点替代这些退出条件。
