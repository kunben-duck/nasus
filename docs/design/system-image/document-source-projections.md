# 需求与测试来源投影

更新：2026-09-17。本文记录 `0042_source_documents` 的实际契约，不替代完整 P0-P6 方案。该实现提供带证据的来源投影，尚不提供 approved specification、语义关联裁决或有效测试覆盖率。

后续 `0046_requirement_components` 已将明确标注的 AC/业务规则投影为独立来源实体与修订，固定父需求和原文；见[子对象契约](./requirement-components.md)。下文的旧 v1 文档/回执仍保持兼容，新增抽取版本为 v2。

## 输入与语义边界

- 仍通过 `system_image.sources.register / sources.ingest / context.materialize` 等既有 canonical ToolInvocation 入口写入；读取已归档 SourceSnapshot，不重新执行目标仓库。
- `us_doc` 支持 UTF-8、无损解码的 Markdown、文本和 CSV；显式 `US-* / REQ-*` 形成 requirement，未声明身份的内容保留为 requirement_document。
- `test_asset` 支持同样的文本格式；显式 `TC-* / TEST-*` 形成 test_case。Python 脚本只用 AST 定位 `test_*` 函数，不 import、不运行，保留为 test_script 并标记 `script_not_executed / unreviewed_script_oracle`。
- 支持中英文 description、acceptance criteria、preconditions、steps、expected result 和 references 标签。CSV 要求 ID/title 列及一致的行宽；多行单元格固定整个原始行区间，公式只作文本。其他二进制文档、表格和脚本语言明确记录 unsupported，不把转换文本行号冒充 PDF 页码或表格单元格。
- `references` 只是原文明确写出的需求标识，不生成 `implements/asserts`。缺步骤、缺预期、重复 ID 等保留 gap。代码推断关系的旧兼容投影不因新增字段而成为已批准事实。
- 现有兼容 `KnowledgeObject.type=TestCase` 可承接脚本展示；真正种类在不可变文档 payload 中为 `test_script`，不能按兼容类型认定脚本已执行或 oracle 已审阅。

## 分层与身份

`domain/system_image/document_projection.py` 定义纯值对象、身份键、精确范围及内容摘要。`application/system_image/document_projections.py` 通过抽取/登记端口编排；文件解析、MinIO 和 PG 分别位于 infrastructure 适配器，领域不依赖 ORM、S3 或外部代码知识 provider。

- `source_document_identities`：Nasus UUID，唯一范围为 project/binding/identity hash。唯一显式 ID 的身份不含行号、文件路径、供应商 ID 或当前 source revision，因此同绑定移动行号、修正文案仍保留实体身份。
- 同次抽取中重复显式 ID 全部标记 ambiguous，使用来源位置与内容构成 occurrence 身份，不悄悄合并。无显式 ID 的文档/脚本同样只保证来源 occurrence 身份；跨修订 rename/split/merge 仍需正式 lineage 机制。
- `source_document_revisions`：固定 source revision、entity ID、kind/title 和 payload hash/ref。
- `source_document_evidence`：关联已有 SourceEvidence；复合外键固定 project/binding/source revision，禁止拼接另一来源的证据。
- `source_document_extractions`：固定逐文件报告及摘要。文件必须有 parsed、failed、unsupported 或 not_analyzed 状态；有部分成功记录不代表整个来源完整抽取。
- 表均为追加式；实体/修订/证据/报告和不含原文的 Outbox 在同一 PG 事务提交。物化失败可以留下未引用的 S3 对象；这不是 PG/S3 分布式事务，工件 GC 仍待实现。

## 归档和冻结

结构化正文与抽取报告保存为 canonical JSON，MinIO key 为 `system-image/source-documents/<project hash>/<payload hash>.json`；PG 只保存查询所需元数据和引用。写后回读、读取时再次验证 namespace、字节摘要、schema、project 和原文 manifest 摘要。

每个字段固定原文起止行及 snippet hash，整条文档也有 locator/hash。抽取器传回的文本必须与归档文件字节、文件 hash、大小一致。单文件 2 MiB、每条最多 90 个字段、单字段 JSON 编码后 32 KiB、相对路径 1 KiB、单文件 1,000 条、批次 10,000 条；超界或不支持的输入不能伪装成功。字段页按 64 KiB 字节预算自动缩小数量，下一页继续，绝不截断单个字段；证据页只含整条文档与当页字段对应的范围，完整证据集合仍由冻结 member 保存。

`ImageObjectMember.kind=source_document` 固定 document/source revision 和当次 evidence IDs。代码成员仍使用原来的 code entity revision 外键；文档字段不复用代码身份。旧 v1 代码候选在未使用该字段时不序列化 `document_revision_id=null`，因此历史 artifact/receipt 摘要保持兼容。

源文件改变、删除或后续抽取追加证据，均不得修改旧候选。画像内的文档读取必须先验证全部候选输入的当前访问权限，而非只验证正在查看的这一份文档。

## 查询与界面

所有 HTTP 读取为 `private, no-store`，读取归档前后复查来源权限：

- `GET /v1/projects/{project_id}/system-image/source-documents?source_revision_id=...`：来源修订内的文档列表。
- `GET .../source-documents/{document_revision_id}`：按 offset/limit 分页的结构化字段和证据。
- `GET .../source-document-extractions?source_revision_id=...` 和 `GET .../source-document-extractions/{extraction_id}`：报告列表与逐文件分页，不暴露存储 URL。
- `GET .../revisions/{image_revision_id}/objects/{object_id}/document`：严格固定画像成员的字段读取。
- `query.system_image.revisions.document`：同样的固定画像查询，通过 ToolInvocationRuntime 的项目范围、RBAC、审计和 Outbox。输入为 project/image/object ID 以及 offset/limit，不接受文件路径或 provider ID。
- 工具结果只保存文档/来源修订 ID、payload/result hash、证据 ID 和分页；不把正文、字段值、文件路径或 S3 引用复制到工具结果、SSE 和审计。通过既有 `/v1/tool-invocations/{id}/image-query` 或 observation application port 展开，重新鉴权并核对结果摘要。Planner 默认只得到重新核验后的无正文回执；尚未用此功能替代模型出口授权设计。

Knowledge 的 Image revisions 检查面板在文档成员下展示字段、行号、提取缺口及原文证据，固定显示“引用不证明覆盖或验收”的说明。使用既有浅/深色、分页和隐藏滚动条样式；正文为 React 文本，不执行 HTML 或来源指令。

## 验证范围

`test_document_projection.py` 验证字段/跨度/身份/缺口及静态脚本；`test_document_projection_api.py` 使用隔离 PostgreSQL、真实 HTTP/ToolRuntime，覆盖历史回放、权限撤销、事务回滚与只追加约束。该 API fixture 使用临时对象存储，不冒称 MinIO。

`test_exweb_source_documents.py` 是显式 opt-in 的真实 MinIO 测试；以固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 归档生成 546 个代码成员，并加入仓库内两份明确标注的验证用需求/用例资料。验证三源冻结、MinIO payload 回读、字段证据 hash；只清理本轮写入的临时对象，保留原始 exweb 归档。`source-documents.spec.ts` 覆盖页面与相同 canonical 查询工具。

这些伴随资料不是 exweb 原作者的需求，也不是经双人标注的业务 gold。没有执行 exweb/Maven/hook/依赖安装，不宣称真实目标测试通过。实际各批测试结果见 [实施记录](./implementation-progress.md)。

## 仍需交付

PDF/Word/Excel 的原生页码、段落与单元格证据适配，其他测试脚本语言，正式 AC/规则的批准与 authority、完整 typed assertions、跨修订负向决定适用性与冲突审阅、关联置信度校准，以及 P2/P4/P5 的全计划自主执行、官方修订发布、增量更新和五类 ContextPack，仍属于原目标。不能把来源子对象或旧 inferred links 当作三源业务语义关联验收。
