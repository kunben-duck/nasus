# 显式 Git 分支与标签来源

更新：2026-10-09（Asia/Shanghai）。0093 为代码来源增加可选 `tracked_ref`，保持旧来源身份、历史清单和公开工具兼容。它补齐来源选择基础，不等于自动维护、完整增量构建或 P0-P6 验收完成。

## 注册与身份

沿用 canonical `system_image.sources.register`，代码 source spec 可显式指定完整 Git ref：

```json
{
  "project_id": "project-id",
  "source_specs": [
    {
      "source_type": "code",
      "source_uri": "https://github.com/kunben-duck/exweb.git",
      "tracked_ref": "refs/heads/main",
      "source_label": "Main branch"
    }
  ]
}
```

示例 ref 仅说明请求格式，不表示该仓库当前存在或应使用此分支。实际采集必须验证目标 ref；不存在时失败，不改用默认分支。

只允许 `refs/heads/name` 或 `refs/tags/name`，按 Git ref 字符规则校验，UTF-8 最多 255 字节。不接收短分支、HEAD、commit/revspec、命令选项、空字符串或不合法路径段；需求文档和测试资产不能设置该字段。Portal 的空字段会省略，不将空字符串送到后端，也不猜测分支。

新 binding 身份由 source kind、规范化 URI 和 nullable tracked ref 共同决定。同仓库不同分支／标签各自登记，重复同一身份只更新兼容的标签／凭据引用，不改绑旧来源或自动采集。旧 null ref 使用原身份摘要，迁移不推测历史跟踪分支。

`source_bindings` 与兼容 `raw_assets` 都保存该字段；已有 binding 的 ref 不允许 UPDATE 改写。换分支需要新登记，旧 SourceRevision、manifest、画像和证据保持原值。该 UPDATE 约束不是全部 binding 的删除保护，不能因此声明来源表已经全量 append-only。

## 采集与回放

Git connector 使用已校验的 URI 与显式 ref 创建独立缓存。首次采集和后续 refresh 都 fetch 确切 ref，解析为 commit 后 detached checkout；缓存 key 包含 ref，不共用另一分支的 HEAD。missing ref、不可用 connector 或不支持的 URI 不回落本地工作树、默认分支或 synthetic source。

生产默认仍支持 `git`、`https`、`ssh`；`file` 仅在显式允许的受控验证中使用，并核验允许根目录。本地普通目录设置 ref 后不能按普通文件夹采集；必须提供由 Git connector 支持的 URI。原 URL、凭据、host policy 和快照污染检查继续生效。

SourceRevision 固定实际 commit 与采集文件摘要，而不是跟踪分支当前 head。`refresh=false` 的历史恢复优先使用原 commit；即使 ref 已移动，也不能把当前内容替代旧修订。已归档字节仍由来源快照存储回放。force-push 导致远端不再提供旧 commit 时应明确失败，不伪造历史；完整保留／回收和断电恢复协议仍待交付。

`system_image.sources.ingest` 的[显式选择刷新](./source-refresh.md)保持旧清单预条件，只重采选中绑定。采集不自动执行结构构建、语义审阅、批准、失效或发布。

## 引导与聊天入口

Project Overview 的代码来源输入增加可选 Git branch/tag 字段，浅深色使用现有主题 token。缺码恢复的 canonical register payload 和有界中英文构建请求传递同一显式 ref；文档／测试来源不接收它。已有代码绑定的 ref 可作为引导默认值，无 ref 的历史来源不生成默认分支。

原 Goal 补源、结构预算和治理确认保持独立。保存 ref 或采集成功不等于 Goal ready、模型出网授权或目标代码执行许可。

## 迁移兼容

新增 nullable 字段时，0069 代码别名与 0070 对象来源回填不能读取尚未存在的 0093 列。两份冻结 projector 改为选择各自原版本需要的 binding 列，不改变旧身份、摘要、审计或来源协议。

空数据库全链升级、真实有数据的 pre-0093 列模拟、旧 alias／provenance 完整性分别验证。0093 降级在存在非 null ref 时拒绝，不能丢弃已登记身份。开发数据库未在专项测试中升级或改写；部署／本地启动仍需运行正式迁移流程。

## 实际证据与边界

- `test_source_tracking.py`、`test_system_image_concurrency.py` 与 Git connector 测试覆盖纯验证、不同 ref 身份、实际 fetch、缺 ref 拒绝和历史恢复。
- `test_source_tracked_ref_api.py` 通过实际 canonical Runtime、隔离 PostgreSQL 和私有 MinIO 验证多绑定、错 ref、历史回放及固定 exweb。
- exweb 原 commit 为 `fe5827f6b76f77ef34918d8b452ee823142332dc`，126 个文件、tree hash `sha256:abf1d4753fc5d15e596f9f232bead49e428d4392673c24a921aa67b25fadda8e`。受控私有 origin 由该仓库真实 Git blob 建立，README 追加是明确验证夹具，不是上游新提交。实际 Git 分支采集后，全部历史文件与原 blob 逐项比较；受控新分支只改一个文件，其余 125 个不变。其他绑定和旧 MinIO 字节仍固定。
- `tests/e2e/source-tracked-ref.spec.ts` 使用仅 loopback 的实际 Git daemon，验证非默认 release 分支的 Portal 输入、原 Goal 补源和独立结构预算。light/en、dark/zh 390px 检查主题、字段布局及无横向溢出；不是浏览器采集上游远端 exweb。

专项通过不代表 webhook 验签／持久 inbox、周期 reconcile、自动 delta DAG、overlay/tombstone、三方合并、全计划多能力预算或真实目标业务执行已经完成。批次终态、历史失败和完整门禁状态见[实施记录](./implementation-progress.md)。
