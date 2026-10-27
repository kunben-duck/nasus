# 验收条件与业务规则来源对象

更新：2026-09-17。此契约实现 P3 的来源投影基础，不替代完整系统画像验收。正式 US/AC 与测试创作仍属于 quality_loop；system_image 不建立第二套可变需求主表。

## 来源与身份

- `us_doc` 的明确 requirement 内，标注的 Acceptance criteria/验收条件/验收标准、Business rules/业务规则可生成独立 `acceptance_criterion / business_rule` 来源对象。仍走 canonical 摄入和物化工具，不新增直接 HTTP 写入口，也不执行目标仓库。
- 支持现有无损 Markdown、文本与 CSV。列表项、`AC-* / BR-* / RULE-*` 和 AC/规则章节内的同类子标题划分条目；相邻续行保留同一条。其他章节、代码块、匿名文档、测试预期不会被提升为需求规范。复合多行 CSV 单元格保留为一个有缺口的来源条目，不假装已完成语义拆分。
- 实体 UUID 复用现有来源身份注册表。唯一显式子编号的身份键包含父需求 identity hash，因此不同需求下的 `AC-1` 不会合并；同父需求、同编号的移动行号与文字更正保留实体身份，生成新修订。
- 无子编号、重复子编号、父需求身份不唯一分别记录 gap，使用 occurrence 身份而非虚假的稳定标识。跨绑定、重命名、拆分/合并 lineage 不在本阶段实现。

## 修订与证据

- 抽取器版本为 `nasus.explicit-document.v2`；父文档仍用 `nasus.source-document.v1`，新子项使用 `nasus.source-document-component.v1`。新抽取不重写旧 payload、旧修订或旧查询回执。
- 子 payload 固定父 identity hash、父 payload hash、父字段索引、原始文件/片段 hash 和精确行号。父子关系是 `source_contains`，只表示原文结构，不是 implements、asserts 或业务覆盖。
- `0046_requirement_components` 增加 `parent_document_revision_id`。复合 FK 限制同项目、同 binding、同 source revision；check 禁止缺父、自指和普通文档冒充子项。已有追加式触发器继续有效，存在子修订时禁止破坏性降级。
- 父与子必须在同一次抽取事务中登记。仓储从父字段重建子投影，拒绝错误父、范围、身份或语义状态；登记、证据、报告及 metadata-only Outbox 同事务。MinIO/PG 仍非分布式事务，失败遗留的未引用对象 GC 未完成。
- 候选画像必须同时包含准确的父需求修订，不能只冻结子项后用当前父 head 补齐。更改或删除源文件后，旧子对象及其父修订仍按原 hash 回放。
- 单文件 1,000 / 批次 10,000 的对象预算现在包含子项。逐文件报告的 entity_count 也包含子项，不只统计父文档。

## 查询与展示

沿用来源文档、画像对象文档和 canonical document query 接口。子项查询除自身摘要外还核验固定父工件及证据集合，读取前后复查 ACL。旧父文档响应不增加空 parent 字段，保持 v1 receipt result hash；新子项响应增加父修订 ID 与来源结构信息。

Knowledge → Image revisions 展示可独立检查证据的 AC/业务规则对象、来源需求、固定父修订及待确认状态。沿用 light/dark/mobile、无可见滚动条和原有视觉 token；正文为文本，不执行来源中的 HTML、公式或指令。

所有这些对象固定 `source_projection_not_approved_specification` 与 `authority_status=pending_confirmation`。有原文只能证明原文这样写，不能证明需求已获批准、实现满足它或测试已经验证它。现有显式 references 候选不会因为存在 AC 子对象自动升级为 asserts。

## 验证与剩余范围

- `test_document_components.py`：父限定身份、续行/子标题、中文标签、重复编号、匿名条目、复合 CSV、大小限制与伪造状态拒绝。
- `test_document_components_api.py`：真实 PostgreSQL/HTTP/ToolRuntime、独立证据、修订变更、删除源文件后的回放、父成员闭包、数据库约束、禁止破坏性降级、旧 v1 工件/回执兼容、父工件损坏和读取中撤权。
- `test_exweb_source_documents.py`：固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc`、真实 PG/MinIO、546 个代码成员和两份明确标识的验证用资料，生成需求/测试用例/AC/规则四个文档成员并核验父 hash 与原文。验证资料不是 exweb 作者的正式规范，不运行 exweb/Maven/目标依赖。
- `source-documents.spec.ts`：同一固定仓库、真实 API 调用、文档 query receipt 展开、四类成员的 light/dark/mobile 展示与后续引用审阅冻结回归。

正式规范批准及 authority 引用、完整多格式语义抽取、BehaviorSpec、implements/asserts/exercises、关联冲突/置信度/readiness、五类 ContextPack、持续更新与发布治理仍属于完整 P0-P6 目标，尚未交付。各批实测结果见实施记录，不用本阶段绿灯代表总目标完成。
