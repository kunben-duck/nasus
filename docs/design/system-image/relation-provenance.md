# 冻结关联与上下文的来源追溯

更新：2026-10-07。0072 在既有对象来源图和上下文派生图之间增加冻结关联依赖，固定 references、implements、asserts 的证据与选定审阅历史。0073 将登记提前到关联事实提交时，纳入未被画像选定的引用候选、已归档语义评估和审阅决定。两者不修改原画像、业务规范或旧摘要，也不代表完整项目增量依赖图已经完成。验证批次见[实施记录](./implementation-progress.md)。

## 固定的数据链

```text
context -> context relation anchor -> image_relations
  -> relation_member -> selected decision -> predecessor decisions
  -> reference_assertion -> reference_proposal
  -> semantic_assertion -> semantic_evaluation
  -> exact object_pin -> native image member / evidence / image_objects
  -> source manifest / source revision / code or document revision
```

references 只证明原文引用；implements 是代码到来源 AC／规则的实现推断；asserts 是历史用例到来源 AC 的断言推断。新增登记不把引用升级为语义，不把 supports 或人工接受升级为规范批准或执行覆盖。拒绝和暂缓决定同样是依赖，不能只登记正向关联。

`nasus.image-relation-provenance.v1` 的节点固定项目、种类、工件 ID／hash、元数据 hash、完整直接父集合及可选原生对象节点 pin。摘要显式枚举 v1 字段，后续类型扩展不能改变已有登记。object_pin 通过同项目、精确 node key 和 content hash 连接 0070，不复制旧图或正文。关联断言直接依赖双方冻结成员和确切证据，不以当前 evidence 索引重新构造历史。

每个画像固定当时选定的 decision ID 和完整前驱链，不查询今天的最新审阅头。一个语义 claim 的前驱可以来自不同评估；每个决定分别连接它自己的断言与评估，不能借用最后一次模型输出。画像 ancestry 同时校验 project、baseline、manifest、父修订 ID／hash，损坏或不匹配时拒绝读取。

## 原子保存与历史兼容

0072 新增四张 PG 表：`image_relation_provenance_nodes`、`image_relation_provenance_edges`、`image_relation_provenance_roots` 和 `system_image_context_relation_anchors`。节点、边及根的复合外键固定同项目和端点 hash；上下文锚点连接已有 0071 锚点与精确画像关联根。数据库拒绝 UPDATE／DELETE，非空登记禁止破坏性降级。

画像冻结的事实／审计／Outbox 事务先登记原对象图，再登记关联图；上下文归档的同一事务固定来源锚点与关联根 hash。任一登记失败回滚业务事实、所有新登记与事实 Outbox，不另开事务，不跨域更新质量事实。迁移按有界游标先回填全部画像、再回填上下文；旧数据不完整或摘要不一致时整批 DDL 和回填失败，不跳过坏记录。

新图是独立增量，不修改 0068 派生节点的父集合、0070 对象根、0071 锚点或旧 ContextPack／画像工件。正常画像读取和重复冻结核验完整关系登记；ContextPack 仍先经 application 的来源、原文、权限及批准验证，再通过 repository port 校验锚点。列表检查选中画像及本页全部锚点。元数据投影本身不读取 MinIO 正文，不缓存访问权或批准头，不创建模型调用，也不授予执行许可。

## 验证与未覆盖范围

### 未选定的关联事实

0073 复用 0072 的节点、边、类型和显式 v1 摘要，不增加另一套事实表。references proposal、全部引用断言、已提交的 semantic evaluation、已保存语义断言和所有 accept／reject／defer 决定，在原事实／Outbox 事务内登记；决定分别连接自己的原评估与前驱。语义评估尚未审阅时也固定原生画像的完整来源范围和预留记录摘要，包含准确选择与模型配置 pin，不把私有回复正文复制进索引。

正常评估／候选／审阅的读取、列表、选择和已有命令恢复重新验证登记。同一引用命令在事实已提交、canonical 终态尚未写入时恢复，也必须独立只读核验原登记；不能因为不再产生 Outbox 事件而跳过。新的引用命令复用已有候选同样先只读核验，不以旧事件仍然保留为判断依据。事件投影使用追加式候选命令关联区分首次登记和复用；即使旧 SSE 事件已清理，损坏或整块丢失的原登记也不能由普通写入重新补造。核验失败时新命令关联及事实事件一起回滚，完整原登记的正常复用不改变候选和审阅历史。新增审阅必须先验证原决定登记，不能用后续写入修复损坏或重新制造被删除的前驱。没有结果的调用预留仍保持 incomplete，不伪造完成的评估或自动重试未知出口。

迁移完整遍历已有 proposal、evaluation、assertion 和 review 库存，核验原生对象来源与冻结画像根，再补缺失登记；不从正向关系或当前 membership 筛选历史。重复回填不得改变节点、父集合、画像根和上下文锚点。损坏原始事实或旧登记使整批事务失败；有关系登记时拒绝降级。原 0072 只登记冻结成员的历史迁移仍保持原契约，由后续 0073 独立扩展。

契约测试覆盖显式摘要、父集合约束、原生对象 pin、追加式数据库限制、跨项目与端点 hash 外键、正常读取损坏拒绝、事务回滚和 populated migration 原子性。历史迁移测试在回滚事务内暂时移除后续依赖，再重放原迁移；生产外键和完整性校验不因此放宽。

固定 exweb 的代码由 Git blob 导出，再通过 canonical source 注册、采集和物化进入真实 PG／MinIO。伴随需求和历史用例明确是协议验证资料，原生 HTTP 模型响应是 unknown 的测试夹具；不能用于支持语义准确率、业务 gold、oracle 正确性或真实执行覆盖。报告与批次终态单独记录，不能用空库迁移或协议夹具替代完整验收。

0072 保持冻结成员的历史图，0073 补充已提交但未选定的关联事实。尚未保存为 typed assertion 的私有模型判断不凭空物化；未完成调用预留、AC／规则 authority、publication、索引 generation／retrieval trace、脚本和 RunPlan 仍需纳入统一依赖。项目级原子 delta、自动失效／调查／重建、overlay／tombstone、三方合并与回滚、五用途及旧链切换、真实目标执行反馈、Provider 生命周期／对照／gold／隔离和完整 V1 门禁仍保留原范围。
