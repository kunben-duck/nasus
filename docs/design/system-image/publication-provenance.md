# 画像发布与上下文依赖契约

更新：2026-10-07。0077 将原生画像发布审阅、正式知识发布、历史回滚来源及已绑定发布的 ContextPack 接入追加式依赖登记。它连接已有对象与关联来源子图，不改变旧画像、发布、规范批准或派生摘要。验证批次见[实施记录](./implementation-progress.md)，完整 P0-P6 范围仍以[主方案](./autonomous-system-image-design.md)为准。

## 固定关系

| 关系 | 当前事实到直接父依赖 | 校验 |
| --- | --- | --- |
| previous_review | 审阅到原审阅前驱 | 同项目、基线和 claim，连续审阅 sequence |
| expected_head | 审阅到其请求固定的知识发布 | 不追随今天的可变 head |
| approval | 发布到精确审阅 | 原决定为 approve，image/hash/manifest/preview/policy 及回滚源相同 |
| previous_publication | 发布到被替代发布 | 同项目、基线，连续发布 sequence |
| rollback_source | 回滚审阅或发布到原历史发布 | 精确固定原 image/hash/manifest，不恢复业务 authority |

每个 `nasus.publication-provenance.v1` 锚点固定原事实 ID/hash、canonical request hash、invocation、project/baseline、image/manifest 及两个已有来源根 hash。直接父集合必须完整、有序且无重复；登记摘要显式列举 v1 字段，未来类型或 ORM 字段增加不能改变旧公式。完整祖先按有界非递归遍历核验，循环或超过 1000 个事实拒绝，不截断后声称完整。

对象根和关联根分别连接[画像对象来源](./object-provenance.md)与[关联评估和审阅](./relation-provenance.md)。发布批准仅表示固定知识快照可被选用；它不批准需求期望、测试覆盖、模型生成、目标执行或版本发布质量。

## 持久化与原子性

三张 PostgreSQL 表为 `image_publication_provenance`、`image_publication_dependencies`、`context_publication_dependencies`。依赖两端通过 project、baseline、kind、ID 和登记 hash 的复合外键固定；锚点另外连接原生发布/审阅、manifest 和两个来源根。数据库拒绝 UPDATE/DELETE，有数据时拒绝破坏性 downgrade。

新事实先在原事务内 flush，再登记自己的完整祖先和父集合，最后追加审计与 Outbox；任何缺项或不一致使整个事务回滚。新审阅不得顺便修复损坏的旧前驱。迁移在同一 DDL/回填事务中核验全部既有发布、审阅和上下文，缺失的登记可以首次回填，已经存在但损坏的登记不得覆盖。重复回填保留原事实、旧策略和登记 hash。

普通读取及同命令恢复核验原登记，不创建或修复依赖。Outbox 事件重放只验证已登记的原生事实；patch、时间、project correlation、invocation、entity/mutation 类型及正常发布/回滚事件必须吻合，不把相似事件当成事实写入许可。SSE 清理不影响以持久业务事实为依据的登记。

## 上下文发布绑定

v4/v5 ContextPack 的 canonical 输入固定 publication ID；归档事务保存原 context metadata/request hash、image/hash、baseline、精确 publication registration hash。历史读取保留原 pin，后来发布或回滚不改写旧包。当前用途仍重新检查可变发布头、来源权限、正式规范批准和失效事实。

旧 v1-v3 未声明 publication pin 的上下文不补造发布依赖或偷偷切成新策略。登记不是私有原文副本，也不是缓存的授权票据；原归档内容仍经 application port 回读 MinIO 并校验。

## 操作级读取与权限

单次发布 preview、history 或固定 pin 读取可加入已有 `REPEATABLE READ / READ ONLY` 画像会话，最多复用两个已完整核验的画像来源子图。只有精确活动会话可复用审计，普通写事务、独立会话或下一请求必须重新核验；失败或 metadata hash 改变不复用。固定元数据快照不扩展到模型出口、确认或提交。

上下文的发布依赖只读核验可显式复用同一活动快照里的完整画像证明：
新鲜业务会话仍逐次核验原 compile/publication/review 命令、发布登记和
依赖链，所有画像记录字段须与快照一致。它只转交固定画像来源图的
审计，不转交当前命令或权限结论。该转交默认关闭；`context(write=True)`、
原生事实写入和 backfill 不启用，普通事务仍执行完整原生图校验。
没有当前拥有的快照、跨 task/thread 或操作结束时不复用。

当前启用发布头通过独立实时 PostgreSQL 查询复核，即使外层固定快照已经读过旧 head，后来的启用切换也必须拒绝原 pin 的当前使用。初始写预览和锁内提交复核使用不同的新快照，既有 CAS、即时 ACL 和 authority 校验保留。

批量证据核验按完整 project/binding/source revision、文件路径/hash、私有对象引用、decoder 及 source/manifest pins 分组。每个独立固定文件只读取和解码一次，逐项核验所有片段范围/hash，再按原结果顺序返回无正文元数据；跨版本、来源或归档不共享 bytes。每文件读取前后及整批开始/结束检查实时权限，撤权立即停止，不读取后续文件或返回部分结果。下一批重新读取原文，内存不保留跨请求原文缓存。

## 完整目标的剩余范围

本增量没有完成检索 generation/trace、脚本、RunPlan、目标 build/environment 与反馈的统一依赖 DAG。还需完整项目变更计划、原子失效和自动增量调查/重建、overlay/tombstone、三方合并、五用途 ContextPack、旧链切换、真实受控运行和反馈，以及 Provider 生命周期/对照/gold/隔离、容量/性能和最终 V1 门禁。exweb 固定代码及真实 PG/MinIO 验证与业务 gold、外部模型语义正确性和目标执行是不同证据。
