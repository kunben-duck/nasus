# 跨修订语义审阅适用性

已实现精确、只读、可回放的适用性检查，并将按登记身份自动发现历史审阅接入模型评估入口。它不替代完整版本化负向索引、自动召回过滤或发布治理。`implements` / `asserts` 的历史 assertion 和 decision 不改写。

## 调用与身份

`query.system_image.links.decision_applicability` 经 ToolRuntime 接收 project、目标 image ID/hash、旧 `source_decision_id`、新画像中的 subject/target object ID，以及可选 `through_decision_id`。不需要新模型评估，不发送源文件到模型。首先验证旧评估及其原文权限，再读取该 claim 的追加式历史头。新旧画像及文档工件、来源绑定和权限分别重新校验。

- 代码使用冻结成员的 `binding_id + entity_id`；entity ID 来自代码身份登记，不使用 provider 节点 ID、名称或行号相似度。
- 文档使用冻结 document revision 对应的登记 entity ID；AC/规则必须携带父需求身份下的明确子项 ID 才具有跨修订稳定身份。匿名/重复来源项仍可检查完全相同修订，但不能据此推断新的 lineage。
- object ID 是选取句柄，不是跨画像身份依据。不同 binding 即使内容和名称相同也不合并；缺失端点失败，不回退到最近版本。
- 新画像的选择是显式的；本接口不进行 rename/move/split/merge 推断，也不自动发现整个项目的历史拒绝。

## 策略结果

| 条件 | status | candidate_action |
| --- | --- | --- |
| 双方登记身份、端点修订及来源修订不变，固定历史头为 reject | rejected_same_revisions | exclude_from_unreviewed_candidates |
| 登记身份不变，但端点或来源修订发生变化 | stale_requires_review | revalidate_before_review |
| 身份基准变化，或匿名/歧义文档跨修订 | identity_unresolved | resolve_identity_before_transfer |
| 任一 binding、entity 或端点种类不同 | different_endpoints | resolve_identity_before_transfer |
| 完全相同修订，固定历史头为 accept/defer | same_revisions_review_required | review_before_acceptance |

所有结果 `approval_transferred=false`。适用性只说明固定历史决定对指定端点对的意义，不能批准 oracle、计入运行覆盖、自动冻结关系或发布画像。现有关系召回仍为独立只读观察；本轮未把可变历史头悄悄加入旧召回 digest，避免旧模型评估和查询回执无法重放。

## 回放与权限

首次未指定 through 时选择当时的 claim head；回执固定 head ID/digest、新旧 image hash、assertion hash、请求以及完整结果 hash，另携带枚举形式的状态/动作供 Agent 使用。持久化回执和默认重规划不包含审阅原因、原文、模型输出、存储位置或密钥。

回放用固定 head，不采用后来追加的决定。该结果是 `pinned_claim_head_not_global_latest`，不是项目级最新生效决定：其它 claim 的新审阅不会被这个历史回执覆盖。若原 claim 从 reject 改为 accept，新查询看到 accept，但旧回执仍能重放 reject；两者都不自动转移批准。当前项目/来源权限始终重新检查，撤权或篡改后拒绝展开。

## 后续完整闭环

固定审阅范围的[召回 v2 及回执重放](./semantic-link-recall.md)已接入。还需要可扩展的版本化负向索引、跨来源版本的重审工作台、冻结/发布时的跨 claim 并发检查，以及 rename/move/split/merge lineage。不能以检查工具或绿色测试宣称这些步骤已完成。

验证包括领域策略矩阵、HTTP canonical 回执/幂等/篡改/撤权、真实 PostgreSQL 重新摄入，以及固定 exweb 代码与可变配套需求夹具的 PostgreSQL/MinIO 验证。配套需求不是 exweb 官方规范，native HTTP 模型回应是显式测试夹具，不构成真实模型准确率或业务验收。

## 自动发现与模型入口拦截

`SemanticScreeningApplicationService` 使用应用端口查询同 project、predicate、双方 binding/entity/kind 的所有 claim 当前头，不依赖调用者提供旧 decision ID，也不按时间取一个“全局最新”。实现通过 PG 冻结成员和文档登记修订联表查询，最多 30 个选中主体、64 个匹配头；超限直接失败，不能截掉拒绝记录后继续推断。每个命中再经原评估、原文工件、历史链和当前 ACL 验证；查询失败、权限不足或索引不完整不是“没有拒绝”。不同绑定即使同名同文也不合并。

- 任一同版本 reject 阻止新模型请求，包括重新建立 image/claim。只能由授权 reviewer 对原 claim 追加明确的 accept/defer 后重新预览；另一 claim 的较新 accept 不覆盖这条 reject。
- 稳定身份而端点/来源修订变化，预览显示 stale，允许明确确认后的新评估，但仍是 proposed，不继承旧批准。匿名/歧义身份或不同端点不自动迁移。
- 预览返回 `review_screening`（无理由、引用和原文）及 `request.review_scope_digest`，固定空历史也有摘要。摘要包括策略版本、目标画像、登记端点/修订和匹配头。前端展示历史审阅提示，并对 blocked 状态禁用确认；后端独立强制执行，不能绕过 UI。
- 预留和提交沿用与人工审阅相同的项目锁，事务提交前重新核对匹配头。发送前、模型返回后和归档边界也复核。发生变化必须新预览；已预留请求不重试。网络发送后的改判不代表远端请求能撤销，但该结果不能作为新的已提交评估准入；可能保留无完成记录的私有工件，仍需统一回收策略。
- 旧已归档请求缺少 review digest 时保持字节字段兼容，可按原始证据读取/重放；缺少 digest 的新调用禁止发送。历史 read 绝不应用当前动态筛选，因此审阅自身不会递归依赖筛选或改写历史输入 hash。

原 lexical recall v1 仍是明确未审阅的只读观察，不被静默改写；新 reviewed v2 在取前 N 之前过滤，使用最多 10,000 个匹配主体及 64 个命中头的同一筛选应用服务。模型显式选择仍最多 30 个主体。当前拦截覆盖 canonical semantic preview/evaluate，不代表通用 Agent/所有模型出口及版本发布都已接入。
