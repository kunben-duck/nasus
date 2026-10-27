# 固定来源修订差异

更新：2026-10-07。这是 P4 增量维护的文件差异基础，不代表 delta DAG、实体 lineage、派生失效、overlay 或完整持续更新已交付。主要求仍以[知识契约](./knowledge-contracts.md#4-版本解析与一致性)和[阶段验收](./delivery-and-evaluation.md)为准。

## 输入与证据

`SourceDeltaQueryApplicationService` 比较同一 project/binding/type 的两个明确 `SourceRevision`，不解析可变 head、工作区目录或 provider 当前索引。调用者指定比较方向；接口不根据日期猜测 Git 祖先关系，也不把不同 binding 的同名文件合并。

- PG 按当前可见 binding 集合过滤两条来源修订，缺失、跨项目或不可见端点不返回部分比较。
- 读取私有归档 manifest，验证 project/source 命名空间、manifest/content digest、外部修订、schema 和 PG 中的文件数/字节数；v2 同时核验原采集 inventory。
- 不重新扫描工作区、不调用代码 provider/模型、不执行目标仓库。当前比较只验证 manifest，不在每次查询时回读所有文件正文，因此固定 `file_bodies_verified=false`。
- 查询前、PG 查询后、每个 manifest 读取前、比较后及返回前重新检查来源权限。已撤权不能通过历史回执读取；页面过大等诊断也不能绕过读取期间撤权。

## 差异语义

结果完整计算所有已归档路径，再按 `section/kind/offset/limit` 分页，不通过首 N 个文件推断整个仓库。

| kind | 证明条件 |
| --- | --- |
| unchanged | 两边同路径，归档内容 digest 相同 |
| modified | 两边同路径，归档内容 digest 不同 |
| added | 后侧有文件，前侧同采集范围的完整目录 inventory 能证明原先不存在 |
| deleted | 前侧有文件，后侧同采集范围的完整目录 inventory 能证明现在不存在 |
| unresolved | 缺少 inventory、采集不完整、排除范围变化，或缺失路径/祖先被排除、未读、失败等，不能证明新增或删除 |

完整单文件采集不能证明目录内其他路径不存在。旧 v1 manifest 不补造 inventory；共同路径仍可比较内容，缺失一侧保持 unresolved。`complete` 只指本次采集范围内的文件差异，不代表代码结构、业务关联或影响分析完整。

唯一删除/新增对且内容 digest 在两个完整文件集合内都唯一时，输出 `rename_candidates`；重复/复制内容保留歧义计数。候选不改变 added/deleted 计数，固定 `identity_preserved=false`，不能继承实体身份或旧人工批准。

结果 hash 覆盖双端 pin、完整差异、rename 候选、缺口和策略；过滤或分页不改变 `content_hash`。采集缺口、范围变化或 unresolved 要求完整校验；变更路径占并集路径超过 20% 时也设置 `full_validation_required`。这不是自动重建或回归执行命令。

## 正式查询入口

```text
GET /v1/projects/{project_id}/system-image/source-delta
  ?before_revision_id=...&after_revision_id=...
  &section=files|rename_candidates&kind=added|modified|deleted|unchanged|unresolved
  &offset=0&limit=50

query.system_image.sources.delta
GET /v1/tool-invocations/{invocation_id}/image-query
```

Tool 输入为 strict DTO，拒绝额外路径、来源 URL、provider ID、批准或执行字段；limit 1–100，offset 0–100000，rename section 不接受 file kind filter。HTTP 与 Tool 的真实业务读取复用同一 application service。

HTTP 页面 `private, no-store`，最多 64 KiB；超界明确返回 413，要求减小 limit，不截断单条路径或伪造完整计数。损坏归档返回 502，不可用返回 503，错误不回显存储地址或异常正文。平台权限错误保留原状态，不能被 `ValueError` 参数处理改成 400。

canonical Tool 复用现有 Runtime/项目范围/RBAC/审计/Outbox 和 image-query observation。`ImageSourceDeltaReceipt` 持久化 request、全量 delta hash、页面 result hash、双端 manifest hash、计数、完整性/校验标记和游标；不保存文件路径、正文、manifest ref 或对象地址。展开重新读取两个固定修订、重新授权并比较完整回执，篡改或归档变化失败。Planner 经同一 observation 重新验证，只得到无正文回执。中英文工具发现仍受原 12 项详细契约预算约束。

固定 `impact_complete=false / publication_authorized=false`；没有可据此跳过准入审阅、授权模型出口或目标执行的字段。当前无独立 Portal 差异面板，前端既有页面不改变。

## 验证范围

纯领域/应用/回执测试覆盖完整计数与分页、1200 路径末尾变更、旧 inventory、排除/失败/不支持祖先、单文件范围、重复内容 rename、同修订冲突、strict 输入、坏回执、权限竞争和 64 KiB 预算。HTTP/PG 使用真实账号、项目、canonical 登记/摄入和独立数据库；这些小型 fixture 的归档使用隔离本地 storage，不冒称 MinIO。

exweb 单独验证真实相邻提交 `cd9195691f2205d671fe61ba14e47744b5187ad6` 和 `fe5827f6b76f77ef34918d8b452ee823142332dc`：125→126 个文件，新增 `docs/architecture/README.md`、修改 `README.md`、124 个不变。Git 对象只读归档进实际 MinIO，实际 PG pin 与 HTTP/canonical Tool、Outbox 和 Agent observation 回读均验证。来源 binding 为明确 persistence fixture，不把它声称为真实外部来源登记全链。测试不 checkout/运行 exweb、不安装目标依赖、不调用外部模型或 provider；只清理本轮私有临时对象。终态批次、报告与保留警告见[实施记录](./implementation-progress.md)。

## 尚未交付

2026-10-08 新增[固定画像代码成员比较](./code-member-deltas.md)：通过 Nasus 注册身份比较两个不可变画像，提供五类成员变化、canonical 回执和 Portal 分类/分页。它不是源文件差异的替代，也不能将成员移出解释为代码删除或把来源修订变化当作行为变化。两条查询仍不自动提交 stale、重建或发布；完整实体 lineage 与下面的持续更新要求继续保留。

0067 的[持久上下文失效](./context-invalidation.md)已消费固定差异，独立确认后为精确画像的当前使用提交 stale 事实、有界完整节点/边和跨域事件，保守考虑新增文件对空查询的影响。它不是完整 source refresh/webhook 去重与祖先核验、空来源/全部删除修订、章节与实体级差异、rename/split/merge lineage、全项目 delta DAG/Derivation 反向依赖索引、overlay/tombstone/三方 merge 或自主增量调查，这些仍需实施。后续必须消费固定差异及正式证据，而非另起一条可变目录比较链。五类 ContextPack、真实运行反馈、provider 对照/gold/隔离及最终 V1 门禁继续保留，文件查询和有界失效通过不是完整 P4/P0–P6 验收。
