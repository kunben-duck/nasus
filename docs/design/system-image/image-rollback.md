# 历史知识画像回滚

更新：2026-10-07。0076 在既有不可变发布链上增加独立回滚审阅、CAS 提交和 Portal 入口。它恢复知识快照，不回滚部署、来源仓库或业务批准；不代表 P4 的自动增量、overlay 和三方合并已完成。

## 输入和权限

`RollbackTarget` 固定 project、目标 baseline、历史 publication、image revision/hash 和当前 expected head，策略为 `nasus.image-rollback.v1`。历史记录必须属于相同项目和 baseline，sequence 小于当前 head，且指向不同画像；不允许无 head、当前快照、跨基线或仅凭 image ID 的回滚。

历史 publication 的 image/hash/manifest 必须与冻结画像完全一致。预览、审阅和提交仍核验归档原文、完整成员证据及当前来源权限。回滚有意读取历史 manifest，不要求它是最新 source head；这项例外仅用于严格的 RollbackTarget，普通发布仍要求最新来源清单。

只有当前 project_admin/platform_admin 可以审阅和提交。canonical Runtime、认证 actor、项目/会话/goal 范围和审计不变。只读权限不能变成回滚权限。

## 独立审阅与命令

- `GET /v1/projects/{project_id}/system-image/publications/rollback-preview` 和 `query.system_image.publication.rollback` 只读，返回固定目标、当前 head、历史源、预览摘要及当前回滚审阅。
- `system_image.revisions.review_rollback` 独立 user_confirm；输入包含完整 target、expected preview、expected review 前驱、approve/reject 和非空理由。参数伪造 confirmed 不替代 Runtime 确认。
- `baseline.rollback` 需要这一次回滚的有效批准。原 publication/release/generic approval 不可复用；回滚批准不能授权普通发布或 release。批准维持既有 30 分钟 TTL、当前 reviewer 角色及精确 claim 检查。
- 历史 review/头变更、来源 ACL epoch 变化或证据损坏使旧预览失效。失败不自动创建新命令，需重新读取并确认。

Agent 查询回执保留有类型的 RollbackTarget 和固定摘要，不降级成普通 PublicationTarget。再次观察时重新授权和核验；head 或 review 变化返回明确的 stale 错误，不让旧回执成为许可。

## 不可变历史与事务

回滚追加一条新 publication，sequence 为当前值加一，previous_publication_id 指向被替换的 head，rollback_publication_id 指向历史恢复源。image/hash/manifest 来自该原始记录。旧 publication、review、画像和 source revision 的 payload/hash 不改写。

0076 只为 reviews/publications 增加 nullable rollback source 列及同项目/基线复合 FK。普通历史行仍为 null，原 JSON 和 hash 不补字段。存在任何回滚 pin 时拒绝破坏性 downgrade。

提交复用原发布仓储的项目/来源锁、CAS、running canonical 检查。新记录、head、审计和 `system_image.publication.rolled_back` Outbox 同一个 PostgreSQL 事务；Outbox 失败不留下新 head 或部分记录。相同 invocation 恢复原提交，不再次推进 head，更不能将后来发布的 head 拉回旧值。

知识读取使用新 publication pin。即使恢复的是旧 image，新 publication ID 仍是新的依赖版本；旧索引/trace/ContextPack 不能仅因 image 相同自动成为当前有效输入。已撤回 AC/规则、人工否定及持久 context invalidation 不因回滚复活。source head 和可变工作草稿保留当前状态，继续与已发布知识头分离。

## Portal

Knowledge 的 Image revisions 中增加初始折叠的独立回滚面板。显式展开并选择 baseline 后才读取历史，按 sequence 每页 10 项；选历史 publication 后才核验归档证据和预览。

理由/决定、历史选择、head、重新读取或分页变化会清除确认。审阅和恢复有两个独立复选框；批准后先重新核验，再允许用户确认恢复。同步提交保护和无自动 mutation 重试沿用正式发布链。页面隐藏 fetching/错误的旧历史及正文，撤权或完整性失败关闭受保护视图。

页面仅说明知识恢复，不把按钮命名为部署恢复。沿用共享细边框、主题 token、移动端布局和隐藏滚动条，不引入第二套视觉样式。前端核验历史范围/顺序/重复项、源 publication、双方 image/hash、政策和 authority=false，canonical 回执必须匹配原命令和输入。

## 验证边界

测试范围与终态见[实施记录](./implementation-progress.md)。exweb 使用固定相邻 Git 提交导出的真实原文、隔离 PostgreSQL 和私有 MinIO；额外 Orders 哨兵及 reviewer 明确为协议夹具，不是维护者批准或 business gold。验证不调用外部模型、不安装目标依赖、不执行 exweb/Maven。

当前数据库专项 38 项通过，CLI 真实界面确认后独立 PG/MinIO 核验旧记录、原 manifest、工作草稿及原子审计/Outbox；刷新、viewer、失败隐藏及深浅色 390px 已实际检查。迁移兼容演练在事务隔离 schema 执行实际旧 DDL，不因其他测试已有回滚事实而绕过生产降级保护。完整 185 项 E2E 使用另一个较早加载版本，不能把专项通过写成 V1 验收完成。

这项回滚不完成 Provider 生命周期/对照、自动维护、统一全部 Derivation DAG、overlay/merge、五用途、旧链迁移或真实执行反馈；原 P0-P6 完整退出条件继续有效。
