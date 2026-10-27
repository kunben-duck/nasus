# 固定检索的来源依赖登记

`0078_retrieval_provenance` 连接原生索引预留、完整索引 generation、检索 trace 和 v5 ContextPack 的元数据依赖。它是完整系统画像更新 DAG 的一部分，不替代原文、权限、模型出口或语义相关性检查。

## 固定依赖

- 预留固定原 canonical 命令的请求、完整 preview、publication pin、模型配置摘要和原生元数据摘要，并连接 `0077` 的确切 publication registration hash。
- generation 固定原预留 registration hash、原生 generation 元数据和全部文档的排序摘要。每个文档连接 `0070` 中同一画像的确切成员 registration hash；没有只登记最终 top-N 或成功命中的对象。
- trace 固定原生查询摘要、actor、scope fingerprint、私有工件摘要以及同一 generation 的 registration hash，不追随新的 publication 或 active 模型。
- v5 ContextPack 固定每条来源 AC 对应的 trace registration hash，以及原 context/request 摘要。绑定目标必须是所选画像的完整来源 AC 集合，代码对象、测试用例和业务规则不能冒充 AC。
- v1-v4 没有这类检索绑定，校验其依赖集合为空，不改变原 schema、请求摘要或业务语义。规则、批准与 publication 的依赖仍由各自既有登记核验。

登记本身不存查询正文、源码、向量、oracle 或执行授权。文档原生元数据摘要覆盖 text 和 vector hash；实际向量重新按原维度和 float32 策略核验。完整成员依赖包括其固定证据祖先，但本增量不是每个 chunk 到独立 evidence/revision/ordinal 的新外键：原 chunk 定位与 MinIO 内容仍由原 application verifier 核验。

## 持久化与事务

新增三张 PostgreSQL 追加式表：

- `image_retrieval_provenance`：reservation/generation/retrieval 登记及确切父 hash；同项目原生事实、publication 与父登记使用复合外键。
- `image_index_document_dependencies`：全部原生文档到原 generation 和 image member 的 hash 外键；反向索引用于后续更新影响分析。
- `context_retrieval_dependencies`：context/AC 到原 trace 的 hash 外键；不能依赖查询时可变的“最新检索”。

新预留、generation 与文档登记在原索引事务中提交；既有单查询 trace 和 canonical 全 AC 查询结果两条路径均在原 trace 事务登记。新 ContextPack 在原归档事务内登记。Outbox 只读校验，失败时原事实、依赖登记和事件一并回滚，不制造第二套业务生命周期。

领域使用 `nasus.retrieval-provenance.v1` 和显式摘要字段集合，不把当前 ORM 的全列枚举直接当作未来版本的摘要公式。应用层仍通过既有 repository/artifact/embedding ports；该元数据 projector 不调用 S3、provider、FastAPI、Temporal，也不读取可变批准头。

## 历史与失败策略

迁移按原生事实依赖顺序、64 条 keyset 批次进行事务回填；先核验原 publication 和完整成员祖先，再登记子节点。原事实和私有工件不改写，旧 hash 不变，重复回填须精确匹配。已有登记缺失子边、原生元数据损坏或父 hash 不匹配均拒绝，不以新的查询/写入自动修复历史。

普通索引读取、trace 回放、ContextPack 读取/列表/命令恢复和事件重放只校验，不创建登记。当前 ACL、模型配置和 publication head 的新鲜性继续在应用层独立重验；历史登记通过不等于当前可用、模型出口已授权或已验证覆盖。

迁移在原生事实损坏时整体回滚，包括 DDL；已有登记时拒绝 destructive downgrade。开发业务库不会由测试运行器自动迁移，验证只在 `nasus_test_*` 隔离 PostgreSQL 内执行。

## 验证与剩余范围

专项覆盖原子回滚、全部成员依赖、确切 hash 外键、缺失依赖拒绝读取/恢复、非 AC 目标拒绝、追加式保护、旧上下文兼容、真实历史迁移与幂等回填。实际 exweb 双提交、PG/MinIO 证据与每批加载版本见[实施记录](./implementation-progress.md)，不能累加重叠选择集为项目测试总数。

尚未交付统一 query-plan/call/batch/LLMCall 来源依赖、独立 chunk 外键、脚本/RunPlan pin、完整原子项目 delta、自动维护/增量索引、overlay/三方合并、五用途上下文和旧链切换、真实执行反馈、Provider v2/对照/gold/隔离及完整 P0-P6/V1 门禁。该登记不把协议模型响应当作语义 gold，不把索引完备性当作查询召回完备性。
