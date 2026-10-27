# 代码对象稳定身份与历史引用

新物化的已登记代码对象使用 `CODE-<EntityIdentity UUID>`，不再把供应商节点键的哈希作为公开对象身份。历史画像保留原始对象 ID 和工件哈希；读取方通过指定画像解析旧引用，不能跳转到当前源码或改写既有语义关联。

## 身份与修订

| 标识 | 含义 | 变化条件 |
| --- | --- | --- |
| `entity_id` | Nasus 在一个项目与 source binding 内登记的代码符号身份 | 无法唯一匹配时不复用；完整 rename/move/split/merge lineage 尚未实现 |
| `CODE-<entity_id>` | 新物化对象的公开 ID | 唯一匹配符号的供应商替换、行号调整不改变它 |
| `entity_revision_id` | 一次固定符号观察及定位修订 | 源码修订或观察内容变化时产生新修订 |
| `source_revision_id` | 已归档的固定源码快照 | 新源码快照产生新修订，不覆盖旧快照 |
| `image_revision_id` | 冻结知识对象、来源及证据集合 | 新冻结或审阅产生新画像，不延长旧 membership |
| `CTX-*` | 历史供应商节点生成的对象 ID | 仅作为经审计的历史别名，不作为稳定身份依据 |

新冻结路径中，未唯一匹配或 ambiguous 的节点保留在[私有观察归档](./code-observation-archives.md)，不成为正式成员，也不伪造 `code_reference` 或 UUID。旧兼容投影中的未验证对象和历史 hash 保持原样；未归档来源不能冒充已固定代码身份。文档对象继续使用自己的 `DOC-*` 契约。

## 静态路由与导入观察

2026-10-08 新观察使用 `nasus.code-entity-observation.v3`，不改写旧 v2 修订。唯一定位的 Java 注解路由以所属 handler 的限定 scope、路由名称和文件路径登记身份；不同 controller 的相同 URL 不合并。相同行的 handler 或重复 owner 无法唯一定位时仍保持 ambiguous。行号和 Provider 替换不参与稳定身份，路径变更仍需尚未完成的 lineage。

路由主定位和类级路由、方法级路由两处 supporting locator 各有精确原文 hash，实体修订、全部 Evidence、Provider binding、别名与 Outbox 在原 PG 事务中登记。归档读取校验源文件与每处片段，不把三处静态证据当成接口真实可调用或业务行为正确的证明。其他语言的正则路由尚未获得同等身份保证。

静态导入使用 `static_import_not_resolved_runtime_dependency`，名称保留 Java 通配符。共享 dependency 仍按排序后的首个导入文件登记一个节点，不代表每个导入发生点、包解析成功或真实运行依赖。无损读取但不支持语法的文件仅登记 module 身份，标记 `source_file_not_parsed_symbols`；保留 unsupported 诊断，不登记其中未经解析的声明。

新修订的 supporting locators 限定为同一源文件的有界精确跨度；越界、失真文本或非路由对象携带支持跨度均拒绝。已登记代码的受限只读投影同时理解 v2/v3，仍要求不可变别名、来源修订和原归档核验。

## 不可变别名登记

迁移 `0069_code_object_aliases` 建立追加式 PostgreSQL 表。每条记录固定 project、binding、source revision、extraction digest、provider node hash、entity revision、entity UUID、历史对象 ID、规范对象 ID、策略版本及内容哈希。

Provider mapping 与实体修订的复合外键同时约束项目、来源和修订。回填逐条验证原 mapping、规范符号与观察 payload 的哈希，不读取当前工作区或调用外部模型；同一记录重复回填幂等，冲突或缺失出处导致整个迁移失败。已有别名禁止 UPDATE/DELETE，非空表拒绝破坏性降级。

新登记与原实体事实、代码证据、审计及 Outbox 共用现有事务。别名新增产生 `system_image.code_aliases.registered`，正常新代码修订登记使用 canonical mode。供应商替换仅补别名，不凭空增加代码修订。

## 固定画像解析

只读入口：

```text
GET /v1/projects/{project_id}/system-image/revisions/{image_revision_id}/objects/{object_id}/identity
query.system_image.revisions.resolve_code_object
```

解析先授权并验证完整冻结工件，再查询该画像的 code membership。project、binding、source revision、entity revision 和 entity UUID 必须匹配；请求 ID 必须是经审计的历史或规范 ID。若请求正是历史画像的对象 ID，该精确 membership 优先，不因后来新增别名而改指其他对象。

结果只包含固定身份元数据、画像工件哈希和别名登记哈希，不含源码、路径或归档地址。歧义返回 409，缺失返回 404，损坏返回脱敏 502；超出完整验证预算返回 413，不返回看似完整的部分结果。读完再次检查来源和项目权限，响应为 `private, no-store`。

Canonical Tool receipt 固定原输入和别名登记哈希；重放重新授权并验证全部结果，不混入后续登记。返回的 `frozen_object_id` 用于后续该画像的证据或语义操作。解析器不会偷偷把其他写接口输入替换为当前 ID，也不会迁移旧画像、断言、裁决、批准、ContextPack 或生成工件。

## 现有消费者兼容

代码证据列表接受规范与历史对象 ID，但仍要求明确 source revision，并可固定 entity revision；同一别名涉及多个实体修订时拒绝混合原文。

受限来源的只读投影按同一别名表重建 source-local 对象，保留快照中的原始对象 ID。它检查别名和观察 payload 的哈希，继续排除跨源派生标签、关系、未固定 embedding 和不具来源证明的记忆；不会将旧快照改写成新 ID。无权来源仍在查询前排除，读取后由现有 application port 复核权限。

## 与需求及用例的关系

稳定代码身份只解决“哪个符号、哪次观察”的问题。代码到 AC 的 `implements`、用例到 AC 的 `asserts` 仍由独立证据、模型评估和 reviewer 裁决形成，并固定到画像成员；`references` 仅证明提及。别名解析不能把候选提升为已批准要求，更不能把生成草稿或 planned coverage 提升为执行覆盖。

完整来源注册表切换、历史未登记源恢复、rename/move/split/merge lineage、全部派生依赖及自动增量重建仍属于后续 P0-P6 工作，不由本次公开代码 ID 切换替代。
