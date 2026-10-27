# 语义关联的固定证据输入与结果准入

状态：2026-09-17。已实现固定证据输入、typed 结果准入、显式确认的一次模型调用、原生 HTTP 防腐适配器及 PG/私有对象存储归档。0048 增加 typed assertion 和追加式人工决定，0049 将选定决定冻结为 v3 候选成员，Knowledge 接入审阅、单独冻结确认及历史查看。跨修订适用性、按登记身份自动发现的模型入口拒绝拦截和[版本化召回过滤](./semantic-link-recall.md)已接入；**完整负向覆盖治理和正式发布仍未实现**。测试通过模拟 HTTP transport 验证供应商协议，未将外部真实模型判定或语义准确率视为已验收。

## 输入边界

`SemanticLinkInputApplicationService.prepare` 固定 project、image revision/hash、独立 AC/规则和显式选中的候选。只接受已在版本化召回页中的对象，不接受调用者拼出的引用、正文、当前 head 或 provider 私有 ID。每批 1–30 个主体；召回页可显式扩大到 100，再分批调查。记录原召回方法、结果摘要及截断状态，不修改既有 lexical v1 的排序。

新 Portal 请求携带 `recall_invocation_id`，经 observation 应用端口完整核验 v2 回执后使用筛选结果，不再因旧 raw top-N 缺少替补候选而拒绝。归档输入绑定整个回执摘要；历史读取只核验 canonical 元数据和固定原文，避免递归展开“审阅 -> 旧评估 -> 旧召回 -> 更早审阅”。新调用仍独立核验当前 review scope；旧回执从不成为绕过新拒绝的凭证。省略新增字段的旧请求序列化不插入 null，旧输入 hash 保持兼容。

- `implements` 为固定 code revision → AC/rule revision；`asserts` 为固定 test-case revision → AC revision。没有预期字段的用例不能由标题/需求引用补成 oracle。
- 来源读取复用完整画像、文档工件和归档证据校验。分页连续性、文件/snippet/页摘要、确切源修订和当前权限必须成立；结束前重新核对来源 scope。完整源码跨度大于 64 KiB、证据超过 128 项或实际模型输入超过 256 KiB 时失败，不静默发送首段或丢弃主体。文档元数据分页同样有预算。
- 代码引用基于 `source_excerpt`，文本必须等于已验证原文。AC、规则和预期引用基于 `projected_field`，文本取已验证文档投影的确切字段，固定字段序号及原始行范围，同时携带 raw snippet hash 与字段 text hash。CSV 整行含有 US 编号并不使该编号成为 expected-result 引用；解析后的转义字段也不假装是原始字节片段。
- 输入 hash 包含选中端点、双方源修订、证据、字段、方法和召回结果。span ID 由服务器从定位、源/字段摘要计算，不依赖模型。名称、源码和原文不通过回执、SSE 或 LLM 审计持久化；含引用的结果只能经重新授权的私有工件读取。
- 读取权限不是模型出口许可。返回对象含受保护原文，只能在当前授权操作内使用；它不是持久访问令牌，也不可因为存在 `model_payload()` 就交给现有默认 Planner。当前仅支持下述项目管理员的显式单次确认，不授予自主 Agent 的通用模型出口权限、累计费用额度或任意来源发送能力。

## 结果准入

`SemanticModelOutput` 提供严格 JSON Schema；`validate_semantic_output` 与纯领域 `validate_judgments` 联合校验：

1. 必须是单个 JSON object，不接收 Markdown 包裹、恢复子串、重复 key、NaN/Infinity、隐式类型转换或额外属性。结构错误不将模型正文回显到错误消息。
2. `input_digest` 精确一致。每个选中主体必须且只能出现一次，relation、主体与目标 ID/revision 不可变；缺项使整批失败，不默默当作不相关。
3. 保留 `supports / contradicts / unrelated / unknown`、reason、反证及未知项。非 unknown 判断需要双方引用；supports 需要双方正向证据；contradicts 必须有原文反证；unknown 必须说明缺少什么。不凭空改成人工 reject 或新事实。
4. 引用只能落在当前这对端点的 span，使用 `excerpt.text` 的 Unicode code-point 半开区间，不是 UTF-8 byte offsets；quote 必须完全一致。quote hash 由服务器计算并再次验证，不要求语言模型计算密码学摘要。文档引用不得从同一 CSV 原始行的其他列借证据。
5. asserts 的 supports 必须明确选择主体自己的 expected-result span，并携带与该字段完全一致的 expected value。不能根据代码、其他用例或目标 AC 发明 oracle。是否具有真正可检查的语义仍需模型与 reviewer 判断；schema/原文匹配不是业务正确性的证明。
6. `authority_ref` 的对象/修订来自输入目标，来源类别为 `source_projection`、状态固定 `pending_confirmation`。模型不可设置批准状态、accepted、覆盖率或 calibrated probability。整个结果固定 `proposed / inferred`，概率 null，适用范围只限所选画像，不代表运行验证。
7. 服务器另记录 `evidence_strength`（双方引用/引用不足）、`localization_quality`、同画像的 `version_compatibility`、待审/未解决 ambiguity 和反证存在性。这些是可核验的证据属性，不是模型自报置信度，也没有自动接受阈值。

输入及语义结果对象均是不可变值对象，不使用 ORM、S3、FastAPI 或供应商 SDK；application 经端口交给基础设施序列化归档。旧 references proposal/decision/member 的 hash、schema 和数据库约束不变。后续必须版本化地扩展该审阅/冻结链，不能把 semantic relation 强行写为 references，也不能批准来源文档来冒充 quality_loop 的正式规范。

## 确认与执行契约

1. `query.system_image.links.evaluation_preview` 要求 project/platform admin、当前完整来源权限及固定 image/hash、AC/规则、relation、subject IDs、已保存并测试成功的 chat `model_config_id`。返回 `semantic_preview`，含精确 request、input/model digest、HTTPS destination、source binding IDs、实际输入字节数、一次调用/60 秒/8192 output tokens 上限。预览不访问外部模型，也不回传源码或凭据。当前不支持 legacy imported 或环境变量 system-default 伪选项。
2. 将 preview 的完整 request 交给 `system_image.links.evaluate`，经原有 ToolRuntime `user_confirm`。调用方伪造的 confirmed 字段被 Runtime 丢弃；真正确认时才写入确认时间。PG 预留再次检查 running canonical invocation、原始参数、conversation/goal/project、15 分钟确认 TTL、固定画像端点及 evidence membership。读取同一条模型配置/加密凭据快照形成 binding；测试状态、模型、URL、凭据或更新时间改变都会使旧确认摘要失效。
3. `0047_semantic_evaluations` 增加 `image_semantic_call_reservations` 和 `image_semantic_evaluations`，均为 append-only。每个 invocation 只能预留一次；预留及完成各自与无正文 Outbox 同事务，FK 绑定项目/画像/调用，降级不能删除已有预留。预留后、发送前再次检查当前权限和模型 binding。
4. `HTTPSemanticLinkModel` 只消费 application port，支持 OpenAI、OpenAI-compatible、Anthropic、Gemini 原生 HTTP 请求/响应。模型请求固定配置，不随 active selection 改变；禁止代理环境继承、重定向、自动重试、mock/fallback 或 JSON 修补。请求/响应 wire 各不超过 512 KiB；空响应、截断、工具调用、异常和无效语义输出均不提交结果。Provider token usage 缺失时为 `none`，不捏造计费。`cost_estimate_available=false` 明确表示没有货币费用估计；输出 token/一次调用上限不等于完整费用账本。
5. 输出通过原文/端点校验后写入私有对象存储，最多 1 MiB、内容寻址、项目命名空间隔离并回读验 hash。PG 只保存元信息/ref/hash；LLMCall 只保存 input/output hash、实际 usage/latency、固定模型身份和调用关联，不保存 key、源码或引用。权限在模型返回、工件提交前、PG 提交前及返回前复核。
6. `GET /v1/projects/{project_id}/system-image/semantic-evaluations/{invocation_id}` 使用 `private, no-store`。每次读取重新授权、重建固定证据输入、核验工件/原输出/结果 digest，不返回对象存储地址。历史结果不依赖后来 active model 或工作区文件；完整源码权限被撤回后不能回放原结果。
7. 提交后重入读取同一工件，不重复调用模型。失败、取消或进程丢失后只有 reservation、没有 committed result 的调用保持不确定状态，不自动再次发送源码。再次尝试必须是另一个明确确认的 invocation。当前不是 Temporal 驱动的可恢复完整调查流水线，也没有自动恢复、并行额度或累计费用承诺。

结果仍为 `proposed / inferred / pending_confirmation`，不自动创建 accepted relation、oracle、覆盖证据或官方画像 head。该 API 是语义审阅链的执行基础，不是另一套可绕过正式审阅的图谱。

## Knowledge 确认与结果查看

- AC/规则的召回列表可以显式勾选至多 30 个候选，并选择保存且测试成功、非 legacy 的 chat 模型。初始不选择模型、不发送源码。更换模型或候选会清除旧 preview 和勾选确认；忙碌时禁止改变输入。
- Preview 显示固定目的地、provider/model、source bindings、输入大小和一次调用限制；摘要可展开核对。只有用户勾选此次发送许可后才允许执行。按钮经过同一个 `ToolInvocationRuntime` 的创建与 confirm 接口，不调用绕过治理的写 API；重复点击不重复提交，失败不自动创建新调用。离开页面不会取消已确认的调用，UI 明确说明此限制。
- `GET /v1/projects/{project_id}/system-image/revisions/{image_revision_id}/semantic-evaluations` 按固定 target/relation 分页返回历史元信息。读取完整画像和当前来源权限，返回前复核 ACL；`private, no-store`，不带正文或存储地址。历史 `incomplete` 仅表示没有已提交结果，可能仍运行或已中断，不擅自解释成失败并重试。新预览是另一次显式许可，不补发原 invocation。
- 结果 GET 增加原始 request 和不含全文的 span 定位元信息。前端核对 image/hash、请求、目标/修订、推断/authority 状态、引用所属端点及原文/字段类型；当前召回页内的端点再核对 source revision 与 evidence ID。历史批次不必与当前候选勾选一致，但始终受原固定请求和后端完整重验约束。
- 引用显示路径、原始行范围和 Unicode 字符半开区间，并区分解析字段与原文片段。继续点击才读取既有归档 evidence 接口，再次授权。正文使用 React 文本节点，不拼 HTML；失败、撤权或 scope 不符时隐藏已显示内容。
- 所有业务调用封装在 `domains/system-image` API/hook，route 组件只消费 view model。保留现有深浅色 token、移动端宽度及无可见滚动条的滚动体验。关联审阅是下面的独立操作；展示或接受 proposed expected result 的关联，不使该结果成为已批准业务 oracle。

## 固定语义断言与人工裁决（0048）

- 不修改既有 references 的表、hash、断言 ID 或端点约束。`SemanticAssertion` 从重新验证过的 committed evaluation 和固定 span 派生，支持 `implements` 和 `asserts`，保留双方实体修订、画像/hash、评估/hash、输入/证据/oracle digest 及 assessment。PG 只保存这些元信息，不复制来源全文、模型理由或引用。
- 断言 ID 来自完整 payload hash；`claim_id` 由 project、image revision/hash、两端 object/revision 和 predicate 计算。同一固定关系的不同评估具有不同断言，但共享人工决定链，重复推断不能绕过已有 reject。换画像或端点修订会产生新 claim；现有[适用性检查与自动发现](./semantic-decision-applicability.md)可比较新旧端点，并接入模型入口和召回筛选。完整重审覆盖规则仍未完成，不能据此宣称已解决更新时的完整继承。
- `system_image.links.review_semantic` 需要 qa_lead/project_admin/platform_admin、完整来源权限以及 ToolRuntime 的 `user_confirm`。严格输入要求 `evaluation_id`、`subject_object_id`、`assertion_id`、`assertion_digest`、`evidence_digest`、`policy_revision=nasus.semantic-link-review.v1`、显式 nullable `expected_previous_decision_id`、`decision` 和非空 `reason`。reviewer 从认证主体取得，不能伪造。
- `accept` 只适用于 assessment=supports，asserts 还必须已有主体自己的 expected-result oracle。unknown/contradicts/unrelated 可 reject/defer，不可凭接受按钮升级。接受的是当前证据下的推断关联；来源仍为 `pending_confirmation`，不授予规范 authority、执行覆盖、正式发布或画像成员资格。
- `image_semantic_assertions` 与 `image_semantic_decisions` 均 append-only。第一次人工记录时才把派生断言登记到 PG；未审阅的 typed view 仍可从归档评估确定性重建。复合 FK 固定同项目 evaluation/image、冻结 code/document endpoints 和同 claim 前驱；首决定、sequence、前驱及 invocation 唯一。项目锁内 CAS，未重读当前 head 的并发改判失败。提交前复验 canonical running invocation/confirmation/input/scope、评估预留、固定成员和 ACL。
- 一次决定与 metadata-only Outbox 同事务；异常或撤权回滚断言和决定。相同 invocation 重入返回原决定，无新模型调用。存在审阅数据时降级被拒绝；损坏 payload 映射为完整性错误，不回显原文。
- GET `/v1/projects/{project_id}/system-image/semantic-evaluations/{evaluation_id}/subjects/{subject_object_id}/reviews` 重验来源、固定输入和原评估，返回 typed assertion、同 claim 的 head/history，最大 64 KiB。`offset/limit` 有界，可用 `through_decision_id` 固定分页历史；空字符串固定空历史。响应为 `private, no-store`，返回前再次核对权限。
- Knowledge 在点击 `Review relation` 后加载，不自动为整批评估展开所有历史。理由、decision 或历史版本改变会使确认失效；提交经过 canonical invocation+confirm，重复点击有同步保护。失败/改判需手动刷新并重新确认，不自动重试。历史和断言 scope 不符或来源撤权时，父视图隐藏旧内容。显示当前决定对应的 evaluation ID，避免把另一轮 supports 的人工接受误认为旧 unknown 已被改写。

此阶段没有新增 Agent 自动接受策略，也没有把语义关系塞进旧 references 成员表。0049 的版本化准入见[固定审阅成员](./frozen-review-membership.md)：canonical `system_image.revisions.freeze_semantic` 固定 assertion 与 decision 全快照，现有画像查询回执支持 `semantic_assertion_members`。未冻结的人工审阅历史也提供下述受控查询回执；跨来源修订决定适用性和正式版本治理继续开放。

## Agent 审阅历史查询

- `query.system_image.links.semantic_decisions` 复用 ToolRuntime、项目权限、审计和现有 image-query observation port。输入固定 `project_id/evaluation_id/subject_object_id`，可选 `through_decision_id`、`offset`（0–1000）与 `limit`（1–50）；不接受源码路径、Provider ID 或宽泛 latest 查询。只读不要求写入确认，不调用模型。
- 回执 operation 为 `semantic_decisions`，保存画像/评估/断言/证据摘要、claim、当时 head、该页 decision IDs、total/next_offset 和整个结果摘要。不保存审阅理由、原文、模型回复、私有存储地址或 key。空历史用 null head 记录，重放时转换为空字符串的显式空历史 pin；后续新增或改判不改变旧回执。
- `GET /v1/tool-invocations/{id}/image-query` 验证 canonical invocation 与回执 request 一致，按固定 head 重读原评估和证据，核对完整结果摘要后返回历史。项目或任一来源撤权、工件损坏、scope/payload 错配均失败，不能因历史不可变跳过即时授权。
- Agent 重规划使用同一受控 describe，重新验证读取后只获得 metadata 回执；审阅理由和原文不隐式进入模型上下文。中英文审阅历史意图保留该工具于原有 12 个详细工具预算，不扩大模型工具提示。审阅写入完成后推荐该查询，但不自动接受、冻结或发布。

## 验证边界

纯测试覆盖中文/emoji 字符偏移、同 CSV 行字段混淆、伪造 oracle、错修订、重复/漏项、跨候选引用、反证与 unknown、预算、坏页/截断、权限撤回和 schema 错误不泄露原文。

固定 exweb `fe5827f6b76f77ef34918d8b452ee823142332dc` 通过真实 PostgreSQL + MinIO 重建三源画像后，读取 chatStream 与 AC、伴随用例与 AC 的固定证据包。现已验证两条 native HTTP transport → PG reservation → 私有 MinIO result → 重放不重发的链路；固定配置和确认 actor 在适配器测试中使用明确的 double，真实 RBAC/确认另由 HTTP tests 验证。报告记录输入/结果 digest、span IDs 与 `external_model_called=false`，不增加源正文。响应明确是测试构造的 contract fixture，**没有调用外部模型或执行 exweb**。该 fixture 未提供独立批准的具体 response content type，因此保留 unknown，不能当作语义准确率、可执行 oracle、业务 gold 或覆盖验收。

0048 在这两条链之后验证 typed assertion、defer 决定的真实 PG 持久化与幂等回读，unknown 接受被拒绝，审阅不会新增模型调用。HTTP 集成测试另外覆盖支持性结果的接受、并发 CAS、跨评估不重置人工否定、qa_lead 与降级、历史 pin、Outbox/ACL 回滚、append-only 和降级保护。浏览器使用真实 exweb 三源采集与归档证据，但模型评估/审阅命令是显式 protocol fixture；验证深浅色/移动端、确认失效、不自动重试、跨评估历史及撤权/错配隐藏。此组合证明当前执行/审阅契约，不证明真实语义判断质量或完整版本治理。批次结果见[实施记录](./implementation-progress.md)。

## 继续交付

typed assertion/decision 已有固定画像成员、受控查询回执和跨修订适用性检查；preview/evaluate 现已自动发现登记端点上的历史头，固定 review_scope_digest，并在预留/发送/提交边界强制拦截同版本拒绝。具体规则见[适用性与拦截](./semantic-decision-applicability.md)。固定审阅范围的召回新版本已接通；下一步继续跨版本重审覆盖治理，并执行受控外部真实模型验证。还需扩展项目 source/model-egress 策略、自主构建授权、累计费用/租约/即时取消与恢复。结构/向量召回、独立 authority、语义冲突、校准/gold/readiness、P4 演进与 P5 ContextPack 全部保留为完整目标，不因本阶段校验通过而消失。
