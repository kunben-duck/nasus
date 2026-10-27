# 固定源码中的 HTTP 请求定位

更新：2026-10-13。本增量推进 P5 的代码到脚本定位证据，不替代完整 P0-P6 交付或真实目标执行。验证结果见[实施记录](./implementation-progress.md)。

## 原输入与防腐边界

`RunPlanLocatorApplicationService` 只消费原计划读取、来源授权和 `HttpLocatorInventoryPort`。领域匹配器不依赖 ORM、FastAPI、S3、Tree-sitter、Docker 或供应商 SDK。现有 `FrozenHttpLocatorInventory` 是可替换的基础设施适配器，复用原生构建来源 application port，从原画像、完整 code binding roster 和 source revision 读取已归档私有字节，不读取工作区或今天的最新代码报告。

全部文件摘要及完整来源 pin 保留。每份来源固定 project/image/artifact/manifest/binding/revision、外部 revision、源码内容及 snapshot manifest hash。严格 UTF-8 解码失败或语法不支持明确保留状态。解析按当前显式策略从原字节派生，不冒称这是原结构构建时已归档的报告。

新 Java 规则为 `java.import-resolved-http-locators.v1`，旧 `java.import-resolved-annotations.v1` 默认行为不变。已解析 import/FQN、Controller、类级和方法级 mapping 形成静态路径证据；方法及 supporting spans 保留精确行号、原文件与片段 hash。params/headers/consumes/produces/version、无法解析的表达式或注解条件均不作为完整匹配。此版本保守传播未解决的路由条件，不用已知候选掩盖其他无法排除的声明。

### 新 v3 计划的有界不确定性

新检查使用显式 `nasus.frozen-http-route-inventory.v2`、
`java.import-resolved-http-locators.v2`、`nasus.run-plan-http-locators.v2` 和
`nasus.http-locator-static-match.v2`。旧报告仍按原 v1 策略回放，包括既有 v3
计划下的旧报告；不能补造字段、重算历史或把旧全局 unknown 升级为新匹配。

严格解析仍保留所有条件路由为 unresolved。适配器对同一固定字节作第二次 AST
观察，只固定其可能的 method/path 集合：`unresolved_match_scope` 为 1-64 个有序、
去重的精确二字段 pair；原表达式不能完整解析时为 null，保持全局不确定性。
只有方法或确定路径段能证明不重合时才排除该声明。HEAD/OPTIONS、同路径条件、
未知表达式、regex/glob、失败 Java 文件仍保守阻断。`{{binding}}` 可能与静态
字面值路径重合，也不能据此声称唯一匹配。完整源码/路由清单和原动作分母不变。

Portal 独立重推导同一规则，拒绝混合版本、缺少/重复/无序/越界 scope、额外字段
和观察路由注入 scope；排序按 Python Unicode code point 而非 UTF-16/locale。
新独立归档使用原登记协议，历史只核验原 scope/hash/字节，不重新执行解析器。
这仍是静态证据，所有 runtime/fixture/execution/business 权威和覆盖计数不变。

## 匹配语义与原清单

- HTTP 只逐项匹配原 request；capture/oracle 不增加定位分母。保留 case、action index/digest、原 source step indices、request ID、method 与原路径。浏览器动作明确 unsupported，不能从代码路径推造 DOM 定位。
- 匹配按完整路径段进行。静态 Spring `{id}` 可以匹配具体段或显式 HTTP v2 `{{binding}}` 段；不猜 URL 解码、矩阵参数、glob/regex、HEAD/OPTIONS 隐式行为。查询参数不用于证明完整路由，只观察 method/path。
- 状态为 static_match、ambiguous、unresolved、not_found 或 unsupported。not_found 不证明接口不存在；static_match 不证明运行时 dispatch、鉴权、业务结果或测试通过。
- 输出固定完整原计划、script/source pins、全部 source/file/route inventory、逐动作结果和摘要。完整报告不超过 4 MiB；超限拒绝，不截断后声称已检查全部输入。执行、fixture、业务覆盖权威均 false，automated/executed/passed 为零。

## 私有查询与历史

`GET /v1/projects/{project_id}/quality/run-plans/{run_plan_id}/http-locators?run_plan_artifact_hash=...` 是重新授权的 private/no-store 检查，不创建执行事实、不访问模型、不启动 Runner 或构建。固定 hash 不一致时拒绝；读前后核验完整来源权限。

只读 canonical tool `query.quality.run_plan_locators` 保存完整原观察到受保护的 ToolResult，按既有命令/审计链追溯。历史读取只核验原计划、原存储 inventory、确定性派生及当前 ACL，不重新解析最新源码。Agent describe、SSE 和广播只含有界元数据回执，不含路径、完整 inventory 或源码；缺少适用回执策略时拒绝。

以上普通查询不是独立追加式 locator 事实；原 `durable_locator_evidence_verified=false` 保持不变。ToolResult 哈希和历史重推导不能替代独立存储证明、实际运行 dispatch 或执行授权。下面的独立登记是另一条确认式 canonical 写入，普通查询不会静默升级权威。

## 独立登记与原始字节重验（0107）

`quality.run_plan.record_locators` 接受确切 project/run-plan ID 和原 artifact hash，不接受调用方提供的 inventory、报告、源码路径或 URL。qa_lead/project_admin/platform_admin 独立确认后，PG 先核验 canonical command、确认 actor、原参数、项目和十五分钟 TTL，再调用可替换解析 port。完整原来源、文件、静态路由、所有请求动作/步骤及缺口写入私有 MinIO；追加式 PG 事实以复合 FK 连接原计划、画像和 manifest，与审计/无正文 Outbox 同事务。提交前回读归档、完整源码和实时权限，不能用新记录修补坏历史。

新表 `quality_run_plan_locator_records` 只保存原命令/账号/父事实和摘要元信息，归档命名空间为 `quality/run-plan-locators`。迁移不修改旧查询、原计划或原工件；PG 触发器禁止更新/删除，有记录时禁止破坏性降级。私有对象写入后 PG 失败可能留下不可公开读取的孤立对象，不能据此宣称事实已提交；对象保留/回收仍遵循现有私有存储政策。

`GET /v1/projects/{project_id}/quality/run-plan-locators/{record_id}` 和 `query.quality.run_plan_locator_record` 每次重新授权，核对原计划、独立 PG 元数据与 MinIO 原归档，重新读取全部原来源字节及确切片段/类级支持跨度。历史不重新解析，不跟随工作区/latest 或新解析器版本；缺文件、错 pin/hash、撤权、坏归档或 ToolResult 中自洽的替换回执均拒绝。比较使用规范 JSON 摘要，`false/0`、`true/1` 不视为相同。已提交原命令重入只读原记录，不再解析或追加。

只有独立登记的元数据声明 `source_bytes_verified=true / durable_locator_evidence_verified=true`；这表示原静态观察的完整性和持久追溯，不是解析器语义正确性或运行时路由证明。其余 runtime/fixture/execution/business 权威仍 false、覆盖计数仍零。Agent 使用查询回执必须重新授权；SSE/广播隐藏参数、完整报告和路径，只提供生命周期或独立事实 ID/hash。

Portal 的普通检查仍沿用下面的折叠只读入口。独立登记使用另一套确认/恢复面板，不将旧查询界面或旧回执升级为持久证据；各批终态与实际覆盖范围见实施记录。

## Portal

原计划详情新增折叠入口，点击后才读取。按原动作展示请求及静态匹配状态，显式展开才显示源码位置、Controller/类级支持跨度和完整私有清单。浏览器校验原计划 digest、完整代码 roster、inventory/report hash、所有动作及重新计算的候选/状态/分母，不能仅信任响应计数。

完整结果验证后本地每页显示 20 项，不裁剪原结果；列表可滚动但不展示滚动条，延迟渲染完整 inventory。英文/中文、深浅色、窄屏沿用 shared tokens。缓存按账号/项目/计划/hash 隔离且不写本地存储；重新读取期间隐藏旧内容，撤权、坏 hash 或错误 pin 清除受保护父链。刷新必须重新授权读取，不提交或确认任何写命令。

### 独立归档面板

已保存原计划下的独立登记默认折叠，不提前发起归档或读取私有报告。展开后显示确切三字段请求与独立确认，当前上游输入有效且此次确认未变化时才允许 canonical 创建/确认。完整原请求动作分母和所有缺口保留，不将 source bytes verified 展示成运行或通过；完整归档仅在显式展开后渲染。

创建前先持久保存账号/项目/原计划/hash、request key/hash；创建回执核对 tool、全部父输入与幂等键后，再保存原 command ID 并确认。丢失创建/确认回复或刷新后只 GET 原命令及私有历史，不重新提交、不重新解析、不自动确认。原待确认命令需要刷新后重新勾选；输入过期禁止新登记/确认，已保存历史仍按原版本重新授权读取。sessionStorage 仅保存不透明 ID/hash，不存正文、inventory、路径或回执；存储不可验证时拒绝新的写入。

私有历史读取前核对原 canonical command、真实确认布尔值、原参数、result invocation/object ref 与 UUID5 record identity。完整归档重新核验原计划、全来源 roster、原 action/step、静态候选及状态、全部摘要、actor/time 与严格布尔/数值语义；返回元数据必须逐项匹配 command receipt。重新读取期间隐藏旧内容，撤权或归档损坏隐藏私有父链；按账号/项目/计划/hash 隔离查询、禁用自动重试并传递取消信号。浏览器协议核验不替代后端的实际原字节/ACL 重验，也不提供运行时 locator 或执行许可。

## exweb 验证范围

固定 `fe5827f6b76f77ef34918d8b452ee823142332dc` 的实际 Git blobs 经真实 PG、canonical source/画像链和私有 MinIO 进入检查，逐文件比较全部 126 个文件。真实会话路由前缀为 `/api/v1/finance/chat/sessions`，不是协议脚本的 `/sessions`；流式 chat 声明的 produces 条件也保留 unresolved。伴随需求/用例、模型和业务预期仍为明确协议夹具，不能将它们或另批实际 JAR 探针拼成正式 exweb 测试覆盖。

0107 的固定 exweb 专项新增独立 canonical 确认、PG/私有 MinIO 登记及全部原字节重验的无解析历史。该批必须取得自身终态才算验证通过；原先的只读专项不能代替新事实验证，当前状态见实施记录。专用登记 UI 的真实浏览器检查与模型/计划/源码定位 transport fixtures 分开记录，不与原生 exweb 结果拼接。运行时/DOM locator、fixture setup/cleanup、独立执行许可、durable dispatch/cancel/recovery、真实覆盖到放行和完整五用途/旧链切换继续按原交付要求推进，不将本增量定义为完整 P5。
