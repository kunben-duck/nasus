# 固定画像的代码成员比较

更新：2026-10-08。该能力是 P4 实体增量维护的读取基础，不能代替完整 delta DAG、自动调查、来源刷新、失效或发布。原目标仍以[自主系统画像方案](./autonomous-system-image-design.md)与[阶段验收](./delivery-and-evaluation.md)为准。

## 固定输入与身份

比较同项目两个明确的 `image_revision_id + artifact_hash`，方向由调用者选择，不按时间推断祖先、最新画像或当前代码目录。每侧完整核验 PG 固定成员和私有画像归档，实体匹配键是 Nasus 的 `binding_id + entity_id`，不是外部 Provider 节点 ID、对象投影别名或代码名称。

实体不能改变 binding；同一个 `entity_revision_id` 不能改变实体或来源修订。重复注册身份、相同画像 ID 的冲突 header、错 hash、跨项目和损坏归档均拒绝。来源权限在固定读取期间实时复查，不能通过旧画像或旧回执绕过。

比较只核验画像归档及成员，不在此查询中重新读取所有代码原文、运行 Provider、调用模型、执行目标仓库或安装依赖。成员集合完整不代表 Provider 解析完整；缺少一个成员也不是缺少源文件的证据。

## 五类结果

| kind | 比较条件 | 语义限制 |
| --- | --- | --- |
| added_member | 只在后侧画像注册成员中存在 | 不是源文件新增证明 |
| removed_member | 只在前侧画像注册成员中存在 | 不是代码已删除证明 |
| revision_changed | 相同注册实体，实体修订不同 | 来源修订变化可以使未改代码也产生新修订，不代表行为或方法体改变 |
| projection_changed | 相同实体修订，投影别名、成员摘要或证据集合不同 | 不改变实体身份，不等同于业务变化 |
| unchanged | 完整成员 pin 相同 | 只说明注册成员相同，不证明运行行为相同 |

完整并集排序、计数和比较摘要在过滤/分页前计算。代码 binding 集合不同显式返回 `source_scope_changed`。方法改名默认是旧成员移出、新成员加入，不自动推断 rename lineage 或继承人工审阅。固定返回 `source_deletions_verified=false / rename_lineage_transferred=false / impact_complete=false / approval_transferred=false / execution_authorized=false`。

## API 与工具

```text
GET /v1/projects/{project_id}/system-image/code-member-delta
  ?before_image_revision_id=...&before_image_hash=sha256:...
  &after_image_revision_id=...&after_image_hash=sha256:...
  &kind=added_member|removed_member|revision_changed|projection_changed|unchanged
  &offset=0&limit=20

query.system_image.revisions.code_delta
GET /v1/tool-invocations/{invocation_id}/image-query
```

不指定 kind 时返回完整并集，包括未变化成员。limit 1–100、offset 0–100000，响应 `private, no-store`，页面最多 64 KiB。超界明确 413，不截断单个成员；损坏/不可用沿用 502/503，权限变化 403/409，不返回部分比较。

HTTP 与 canonical Tool 调用同一 application service。持久回执只有固定双端输入、完整比较 hash、完整计数、范围/限制标记、页面总数/游标和 result hash，不保存成员正文、路径或存储地址。展开和 Agent observation 按当前权限重新读取两侧并验证原回执，不发现未来画像、重新索引或修复历史。

## Portal

Knowledge → Image revisions → 选择目标画像 → `Compare code versions`，默认收起、不发送比较请求。展开后有当前可访问的分页画像列表，明确选择比较起点，再点击比较；不自动取父画像、最新画像或另一基线。允许用户显式比较同项目不同基线，界面不据此推导继承。

领域 feature 分开提供类型、校验、API 与 hook，route 只组织视图。请求固定两侧 ID/hash；页面检查 schema、所有限制标记、完整计数和两侧 code_member_count、分类端点、身份排序/去重和连续游标。当前比较组件首次成功后的 hash 固定用于分类/分页，发现不同结果摘要拒绝展示。请求取消不返回旧内容，筛选后 offset 重置，返回上一页使用实际 offset 栈。

只有正式 `413 image_page_too_large` 才按 20/10/5/2/1 缩页，所有 pin、分类和 offset 不变。单条仍超界、其他失败或撤权立即停止、隐藏旧结果，不自动提交任何写动作。私有查询零缓存回收时间、禁止失败重试、焦点恢复重新授权；切换画像、清空起点或关闭面板清除旧选择。深浅色、窄屏和无可见滚动条延续现有共享样式，不新增图标或另建视觉体系。

## 验证与未完成项

终态日志和真实范围见[实施记录](./implementation-progress.md#固定画像代码成员比较2026-10-08)。领域/HTTP 用例覆盖全部分类、固定版本、筛选/分页、回执、真正的 PG/MinIO、权限竞争和失败。Portal 契约覆盖非法响应、摘要与权限漂移、缩页、取消和完整分页；浏览器专项使用真实隔离 PG/MinIO 的 Java 小仓库，大小错误和撤权响应的 UI 分支通过明确传输注入验证，不冒称浏览器执行原生 Provider 或 exweb。

exweb 原生验证使用固定主提交与明确受控代码变化，通过真实 CBM/CodeGraph、PG 自有身份和私有 MinIO 证据生成比较。两侧比较画像是测试中归档的固定工件，不是公开 PG `image_revisions` 行或完整 canonical 物化链；HTTP/canonical 链由独立小仓库用例验证。来源修订变化导致大批实体修订不同，不能将这些计数作为真实改动方法数、覆盖率或 gold。

下一步仍需文件/章节/实体差异联合证据、rename/move/split/merge lineage、全项目依赖闭包和自动 stale、来源维护事件、overlay/tombstone/合并、自主重规划、旧链切换及最终 P0–P6/V1 门禁。该查询和 Portal 面板不会解除构建完成条件中的预算、冲突或缺口阻断。
