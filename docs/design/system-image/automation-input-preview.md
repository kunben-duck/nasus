# 固定审阅用例的自动化输入衔接

更新：2026-10-10。这是 P5 自动化消费的输入边界，已实现只读编译与 Portal 检查，**不是完整 automation ContextPack、RunPlan 或执行交付**。后续 0098/0099 的[脚本草稿与独立审阅后端](./automation-script-drafts.md)消费此固定输入；该增量没有接入本面板的生成/审阅 UI，也不授予目标执行权限。[开发验收方案](./delivery-and-evaluation.md)的五用途、真实目标运行和 P0-P6 退出条件全部保留。

## 固定输入与关联

`AutomationInputSelection` 要求明确 project、mapping revision/hash 和去重的 case IDs，不接受 latest、隐式选中或调用者提供的执行权威。应用层通过三个端口回读映射审阅、原生成工件和原 context/scope 的完整生成输入，不读取旧可变 TaskContext、QualityProfile 或资产包。

编译结果使用 `nasus.automation-input-preview.v1`，固定以下依赖：

| Pin | 必须保持的内容 |
| --- | --- |
| context | 原 context ID/hash/input digest 及 image revision/hash |
| scope | 原测试设计范围 revision/hash/request hash |
| generation | 原 generation ID/hash、context/scope pins、input digest 和完整 proposal hash |
| mapping | 当前独立审阅 revision/hash/request hash，不沿用历史或已撤回 head |

原草稿仍为 draft，独立映射接受不改写原用例，不成为正式来源规范批准。选择的每个用例须有已接受断言；所有强制 AC、业务规则、风险、权限、状态、不变量及正反例义务必须保留。若子集遗漏一项义务、仍有 gap、oracle 摘要不一致或原断言不一致，整个请求拒绝，不用 top-k 或裁剪使其成功。

返回完整用例步骤、原独立 expected oracle、来源约束、范围合同和 supporting facts。每行连接实际选定 case IDs，分母由原固定输入推导，不因生成更多重复用例而增长。大小上限为 256 KiB、512 个显式用例，超过上限拒绝而非静默截断；后续完整自动化分包需要另行保存全量合同，不能将该读取上限当作丢弃义务的许可。

## 读取、权限与事件

只读接口：

`GET /v1/projects/{project_id}/quality/test-design-mapping-reviews/{revision_id}/automation-input-preview?artifact_hash=...&case_ids=...`

`case_ids` 可重复参数，但值必须互不重复。GET 不创建 ToolInvocation、不解析模型配置、不调用 Provider 或 Runner。既有映射和归档读取端口重新核验当前项目角色、全部原始来源访问权、规范 authority、归档完整性和当前 context/scope/head。应用编译两次并比较完整 digest，最后再次检查访问范围；这只验证本次预览，不构成后续调用的授权 lease。

响应为 `Cache-Control: private, no-store`，不返回 MinIO 私有 ref、原始模型回复或密钥。范围或映射变化返回结构化 409；完整性错误保持原 502 契约，当前访问拒绝保持 403。错误转换放在最内层，避免外层通用 ValueError 守卫错误返回 400 或泄露私有异常正文。

上下文失效及新映射决定刷新项目级消费者；不把 generation ID 放在 session ID 的缓存位置。新映射事件的 snapshot hint、canonical 终态刷新与 Portal 监听共同连接只读重新核验。旧事件与历史工件不改写，失败命令不发送成功刷新。

## Portal 行为

当前生成工件的独立映射审阅面板新增“检查自动化输入”。仅当前 head、非历史选择、非编辑状态提供入口；完整独立审阅及不超过 512 个 accepted cases 才可读取。初始不请求，用户点击后明确选择全部已接受用例，不将其伪装为已执行覆盖。

领域层拆为纯校验、传输和查询 hook，页面只呈现 view model。纯校验核对原 context/scope/generation/mapping、完整 case 内容、每行 oracle、来源 expected oracle、分母和禁止权威字段，并校验 canonical digest。查询带当前 session、固定版本、AbortSignal，禁用缓存保留及失败自动重试；重新检查、错误或取消时不显示旧私有正文。映射/上下文变化、焦点恢复时重新核验，不沿用失效预览。

页面显示用例数、完整义务数、来源约束数、input digest、可展开步骤/断言和五项待补条件，支持英文/中文、light/dark 与移动端。没有生成或运行按钮，也没有新增 HTML 拼接、私有 URL 展开或自动写入。

## 必须继续接通的消费链

本轮返回 readiness=blocked，generation_authorized=false、execution_authorized=false，以及 automated/executed_on_target/passed 全部为 0。待补项不是可永久接受的最终状态：

1. 绑定目标 build/commit、环境版本和允许网络目标，不能只保存可变 URL。
2. 提供来自固定来源的 API/DOM locator 证据及工具链/框架，不从标题猜定位器。
3. 固定 fixture/schema、setup/cleanup、隔离和等待/时间控制，秘密只使用授权引用。
4. 通过 canonical 命令选择模型、确认全量 token/费用预算，保存原输入、逐调用回执和恢复契约。
5. 保存脚本修订，独立校验 AST/编译/collect 与全部 oracle；再经固定 RunPlan、Runner 真实目标断言结果回流到覆盖和发布判断。

上述链路完成后才能替换旧 `automation.generate` 的可变 TaskContext/资产包输入。当前预览不能作为旧链已经切换、已批准正式用例、五用途全部实现或完整质量闭环的证明。

## 验证边界

领域/application 测试检查原输入不变、显式 case 选择、强制项不丢、错误 oracle/分母/版本、当前访问复查和大小上限。实际 PG/私有 MinIO API 测试检查读取无写入/模型调用、权限、撤回、损坏归档和 HTTP 契约。

固定 exweb 验证在画像冻结前接入真实 126 个 Git blob，回读 PG 成员和 MinIO 每个文件，分别保存原 source/context/scope/generation/mapping pins。配套需求/原生模型回复仍是协议夹具，另外保留 Orders 代码夹具；不是 exweb 维护者批准、原生 Provider/gold 或实际目标测试。

浏览器使用真实 PG/私有 MinIO 的来源、发布、context 和 scope，生成、映射及自动化回复为明确 transport specimens。它验证展示、篡改拒绝、撤权隐藏、只读、取消和移动样式，不冒充真实模型、脚本或目标运行。各批终态及失败记录见[实施进展](./implementation-progress.md)，不能累计重叠选择集宣称总覆盖率。
