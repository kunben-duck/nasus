# 固定审阅成员的候选修订

状态：2026-09-17，0045 已实现 references 的 assertion/decision membership，0049 新增 implements/asserts 的 v3 语义成员。它不是正式发布、业务覆盖批准或通用 overlay/tombstone。

## 语义成员（0049）

`system_image.revisions.freeze_semantic` 输入固定 project、parent revision/hash 和 1–100 个不同 decision ID；同样要求 reviewer RBAC 与单独 user confirmation。新 `nasus.image-candidate.v3` 保留父对象/关系/来源/证据及 references，将 `semantic_assertion_members` 固定为完整 typed assertion + 完整人工 decision 快照，包括 evaluation/input/evidence/oracle 摘要、端点修订、理由、审阅人和前驱。新增 `image_semantic_members`，不挪用 references 表；v1/v2 字节形状、摘要规则和旧查询回执保持兼容。

同一 claim 的后续显式选择替换该子候选中的决定，未选择的成员原样保留，不连接 latest review。合并成员总量最多 1000。语义评估的来源画像必须在父链中且保留同项目、manifest/hash、baseline；父对象逐项相等，语义端点/证据必须属于该快照。新来源修订需要重新审阅，不能借用旧决定；新 image claim 也不能以同端点重复成员绕过已有负向决定。该规则只是未改变来源的审阅子链，不是跨版本 applicability 或通用三方合并。

application 重读私有评估、固定原文证据及当前来源权限；MinIO 归档后，在 PG 项目锁内复核 canonical command、父成员、选定 assertion 和当前 decision head。stale head 返回 `stale_semantic_decision`，Outbox 与候选/成员/invocation 同事务。v3 的 references 更新必须原样保留语义成员，反向亦然。已提交 invocation 恢复其原输出，不因后续改判而重建。

HTTP `section=semantic_assertion_members` 与 `query.system_image.revisions.read` 共用验证和当前授权。回执仅固定 ID/hash，展开才返回私有理由和快照；读取不依赖可变审阅 head。Knowledge 增加单独冻结确认、明确的待处理/失败/成功反馈和固定语义审阅页签。冻结未知提交不自动重试；显式重读后再确认。冻结不会批准 source authority、oracle、运行覆盖或 official head。

## 写入契约

`system_image.revisions.freeze_links` 由 qa_lead / project_admin / platform_admin 经 canonical ToolRuntime 和 `user_confirm` 执行。输入固定 `project_id`、`parent_revision_id`、`parent_artifact_hash`、`proposal_id`、`proposal_digest` 和非空 `decision_ids`（最多 1000 个）。原 UI 审阅操作不自动冻结，冻结有单独确认。

新候选使用 `nasus.image-candidate.v2`，父修订和 hash 必须精确匹配。父对象、关系、来源清单、证据成员保持原样；新增 `assertion_members` 固定 assertion/proposal/decision ID 与摘要、双方文档修订和证据摘要。原始 v1 工件及 membership hash 不变。reject/defer 也作为确切历史决定保存，不能被解释为已接受关系；accept references 仍不等于 asserts/implements、oracle 或覆盖。

首次纳入的断言必须来自该父修订的 proposal。更新已纳入的断言可以沿用原 proposal，但仅替换调用显式选择的决定；其他父成员原样保留，不连接当前 latest review。新 proposal 不能以不同 assertion ID 对相同修订端点重复准入，绕过已有的拒绝决定；必须审阅原断言。端点或文档修订变化不能借用原决定。当前采用完整复制的自包含子候选，不依赖动态 parent 查询，也没有实现任意三方合并或关系删除。

## 原子性与恢复

MinIO 先归档有界工件并回读校验，PG 项目锁内再检查 running/confirmed invocation、原请求、conversation/goal 范围、父成员、proposal、当前 decision head 和来源/角色权限。并发改判返回 `stale_link_decision`，不无条件覆盖。新 revision、对象成员、审阅成员、invocation 关联和 metadata-only Outbox 同事务。

`0045_image_review_membership` 新增父修订字段和 `image_assertion_members`。复合 FK 约束 project/revision/proposal/assertion/decision，数据库禁止修改或删除成员。读取同时核对 PG 成员摘要和整个 MinIO 工件，不能仅凭 HTTP 页或 hash 格式宣称完整。降级遇到已冻结审阅成员拒绝丢弃。

相同内容可复用同一候选，新的 invocation 各自建立关联。原 invocation 在提交后丢失终态时，恢复读取已提交候选，不因后来改判而重新生成或改变该输出。一个新 invocation 请求过时的决定仍失败。未提交的内容寻址对象可能留在 MinIO，统一引用 GC 仍待完整生命周期实现。

## 读取与界面

- 现有 revision HTTP 查询新增 `section=assertion_members`；既有 `query.system_image.revisions.read` 使用同一 section 返回 metadata-only 回执，受控展开取得确切成员。
- 每次读取重新验证整个画像的来源权限，历史不可变不替代即时授权。旧 v1 回执计算保留原 header 形状，新增字段不会使旧回执摘要失效。
- Knowledge → Image revisions 的审阅历史可以单独确认“冻结为新候选”。重新打开修订列表后，`Frozen reviews` 展示固定的 accept/reject/defer，provenance 展示父修订/hash。历史审阅页仍展示可追加的决定链，二者不混用。
- 页面保持当前深浅色、移动端、键盘和无可见滚动条样式。冻结失败不自动重试写入；需重新加载核对最新决定。
- 冻结记录读取保留后端 64 KiB 上限及原分页/回执摘要规则。前端仅遇到 HTTP 413 且 `code=image_page_too_large` 时，在同 offset 以 25/12/6/3/1 条有界缩页；objects 与 members 必须以同一窗口重读并核对。其他错误、取消或单条仍超限时立即终止，隐藏旧内容，不截断原文、不自动重试写操作。上一页使用实际访问 offset 栈，校验 next_offset 连续、total 和条数，切换 section 重置页栈。
- 2026-10-08 新增固定画像内的记录位置跳转。用户输入从 1 开始的位置，必须为不超过已核验 total 的整数；不接受小数、指数、负数或不安全整数。同一位置和无效输入不能提交，零/单条记录不显示跳转表单。跳转只改变原私有查询的 offset，保留相同 image/session/section 和对象、成员成对验证、取消及 413 缩页规则；不会读最新画像、另调 Provider 或提交工具写入。显示实际记录范围而非用历史页栈猜测绝对页数，返回上一页使用实际访问栈，切换 section 或重新打开时不继承旧位置。深浅色、键盘提交、窄屏换行和无可见滚动条延续现有样式。

## 验证与剩余范围

HTTP 测试覆盖确认、RBAC、精确 pins、旧来源 head、并发改判、事务失败、角色/来源撤销、幂等、负向决定及历史回执。纯测试覆盖非法端点/证据、摘要、数量/顺序、语义越级及 v1 回执兼容。PG 仓储夹具包含真实 0038/0042–0045 迁移往返；exweb 固定提交与显式验证资料覆盖真实 MinIO 存取、冻结后的改判/恢复与 light/dark/mobile 页面。

具体实测结果见 [实施记录](./implementation-progress.md)。完整目标仍包括 AC/规则修订、implements/asserts/exercises、语义冲突与校准、批准/CAS official head、持续更新、用途 ContextPack 和完整安全/恢复/性能门禁。此次没有把冻结引用候选当作这些工作已完成。
