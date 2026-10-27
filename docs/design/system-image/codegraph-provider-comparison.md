# CodeGraph 防腐适配与同源对照

更新：2026-10-08。此切片实现第二代码 Provider 的公开 SDK 适配、显式 composition 选择、PG 持久代际与重建、固定 exweb 的结构对照，以及真实 PostgreSQL 身份／MinIO 证据验证。**不切换生产默认 Provider，不宣称结构或语义质量 gold、完整 P0 或 P0-P6 验收通过。** 完整退出条件仍见[交付门禁](./delivery-and-evaluation.md)。

## 公开契约与业务权威

固定 `@colbymchenry/codegraph@1.6.2` 及匹配平台包，而非 main 分支或运行时下载。研究源码为 tag `v1.6.2` 的 `6560052a6f856855d3f71eee838fd66ccfa4285d`；只通过[公开 SDK](https://github.com/colbymchenry/codegraph/blob/6560052a6f856855d3f71eee838fd66ccfa4285d/README.md#programmatic-sdk) 的 `CodeGraph.init(root, {index:false}) / indexAll / getStats / getFiles / getNodesInFile / getOutgoingEdges / getIndexState / getPendingReferenceCount / close` 使用。没有读写 CodeGraph 内部数据库，没有假造 MCP 工具或使用后台 watcher/sync。

`CodeGraphSDKCodeIntelligenceAdapter` 实现已有 `CodeIntelligencePort / ControlledCodeIntelligencePort`。SDK 名称、节点 ID 和未识别原生观察只属于基础设施；领域对象、正式画像、语义关联、批准和发布头仍归 Nasus。`CodeIntelligenceUnavailable` 是自有端口异常：optional 模式可明确报告不可用，required 模式拒绝；应用权限／取消异常不被吞成 Provider fallback。

桥接保留原生节点的名称、类型、文件与定位，及关系的 `source / target / kind / provenance / line / column / metadata`。剔除节点扫描时间等瞬时字段，但不删除未知类型的原始记录。原生统计须与公开完整枚举及逐文件节点数相等；端点未闭合、重复精确边、错误 schema、重复 JSON key、非有限值、越界定位或容量超限整体拒绝，不把有限前缀标成完整图。

当前自有类型仅接入 file/module/class/interface/enum/function/method/route；contains 反向映射为 belongs_to，calls 为 calls，imports/extends/implements 为 depends_on，exports 为 exposes。其余节点/关系、未准入端点、解析错误和未解析引用均保留原生观察并计数为 gap。SDK 返回的 complete 只描述其自身索引，不能使 Nasus 的部分投影晋级 complete。

同一对符号的多个调用位置不是重复边。原生定位与 metadata 完整归档，规范关系聚合时保留各原生边的摘要引用，另报聚合计数；完全相同端点／类型／位置的重复边仍拒绝。SDK provenance 不包含校准概率，数值占位为 0 且明确标注 `codegraph-native-confidence:unknown`，不能据此算业务可信度。

规范身份沿用已有语法校验、`CodeSymbolKey` 和 PostgreSQL UUID registry。匹配不到或冲突保持 unresolved/ambiguous，不以 Provider node ID、临时目录或名字相似强行创建对应关系。跨项目／binding 的实体 ID 独立；rename/move/split/merge 仍需 lineage 决策。

## 私有输入和实际执行字节

输入是 application 已选定的 `SourceTextUnit`，不是原仓库根目录。副本逐文件校验 UTF-8 无损性、精确 byte count 和 hash；路径必须规范且不能逃逸，任何层级的 `.git / .codegraph`、重复文件和文件／目录冲突均拒绝。文件只读，临时 HOME、来源和索引在本次私有会话内；不执行目标程序或安装目标依赖。

操作者须提供已经审查的 `expected_runtime_hash`。指纹覆盖实际安装的 SDK 与平台包中全部文件，包括 bundled Node、grammar 和随包依赖；上限 1 GiB / 30000 文件。文件以 `O_NOFOLLOW / O_NONBLOCK` 打开，普通文件、fd 与路径签名、字节计数和读取期间变更均核验；符号链接、FIFO 等特殊文件拒绝。控制 callback 在遍历及逐 MiB 读取中保持有效。

执行前将两个包逐文件复制到 Worker 私有的 `runtime/node_modules/@colbymchenry/`，保留 `codegraph` 与匹配平台包的 npm 兄弟布局，复制摘要和完整副本摘要都必须等于原 pin。公开 SDK 通过 Node module resolution 加载平台包，不能只把两个裸目录放在 runtime 下，也不能绕过公开入口直接加载平台内部文件。随后实际运行副本的 bundled Node 和公开 SDK，绝不回到可变安装目录加载供应商文件；副本只读，前后重新核验。安装文件在两个 parent 检查之间改动再恢复，也不能改变已经复制的执行资产。

Nasus 桥接同样复制为私有只读执行文件，原桥接读前／执行后校验，摘要纳入 generation policy。该 policy 还固定 SDK adapter/session、composite、Tree-sitter 与身份登记根的静态 Python import／已安装依赖清单、实际解释器版本和容量策略。完整 vendor runtime hash 与自有 policy hash 是不同概念；Python／stdlib、OS loader、共享库和同账号攻击者仍不构成 hermetic runtime。

运行资产的全部文件和逐 MiB 字节核验不减少。遍历内的当前权限／租约 callback 与既有依赖指纹采用相同的 50ms 合并节奏，入口和出口强制即时核验，避免 1,586 个小资产各触发多次 PG fencing 事务。该节奏不缓存跨操作权限，不改变取消处理或摘要。

最小环境不继承 `NODE_OPTIONS`、代理或应用凭据；显式关闭 telemetry、更新检查和 daemon，HOME 为空，匹配平台包已经存在，不触发 bootstrap 下载。使用已有 `CodeGraphProcessRunner`，有限 stdout/stderr、单次 wall timeout、约 250ms callback、独立所属进程组及 finally 回收。成功、错误、权限／取消均清理私有副本；安装资产变更和任何投影错误不提交可用结果。

以上不是独立服务账号、内核禁网、CPU／内存配额，也不证明强杀后的 orphan GC 或逃逸子进程清扫。完整 Worker 隔离仍未交付。SDK 已通过同一 application factory 接入显式 composition 与持久结构索引；公开 HTTP 不新增执行式 reopen，完整 Workflow／强杀与跨进程恢复证据仍须分别核验，不能从本地重建推断。

## 持久 SDK 代际与契约回执

`CodeGraphSDKIndexSession` 在一次公开 SDK 调用结束并 `graph.close()` 后保留有界自有投影，提供 prepare/status、实体／关系分页、定位和保守 impact。它不是保持原生数据库进程，也不是原生 DB resume。关闭后只能由 PG generation application service 从原 MinIO 来源重新准备；新会话有独立 HMAC 游标，原游标不可沿用。

公开桥接结果采用 `nasus.codegraph-sdk-projection.v2`，包含严格的公开 API shape；成功 close 后才输出完整 envelope。领域回执 `nasus.code-provider-sdk-contract.v1` 保存 package/version、公开入口、操作集合、contract/runtime hash 和明确 gaps。它不含伪造的 MCP protocol/server/tools 字段。原 `nasus.code-provider-protocol.v1` MCP 回执、digest 和表结构不改写；既有 receipt JSON 接受版本化联合类型，无新增迁移或历史回填。

复用 `0079–0081` 的原始 canonical invocation、完整来源 pin、generation、PG owner/epoch、实时租约、独立取消、不可变回执和首次 projection hash。重建的 policy、回执或完整投影不同则拒绝，不能改写旧历史。缓存关闭或重新建立 application instance 不会释放取消，也不能用新 generation 绕过同命令的原 Provider pin。每页仍有 256 KiB 字节上限；请求条数超限时要求更小页，测试完整遍历而不是增加上限或截断。

共享 composition 的默认值仍为 `codebase-memory`。只有操作者明确设置以下字段才选择 SDK，不从客户端 request 接收运行目录／摘要，也不下载、安装或自动切换 Provider：

```text
NASUS_CODE_GRAPH_PROVIDER=codegraph
NASUS_CODE_GRAPH_MODE=required
NASUS_CODEGRAPH_SDK_PACKAGE_PATH=<reviewed SDK package>
NASUS_CODEGRAPH_SDK_PLATFORM_PATH=<matching reviewed platform package>
NASUS_CODEGRAPH_SDK_RUNTIME_HASH=<reviewed full asset sha256>
```

固定 exweb、实际 SDK、隔离 PG／私有 MinIO 的代际关闭／新实例重建与公开 canonical 构建两项专项已通过，完整枚举自有 526／580，旧游标／旧 lease 拒绝，原回执和投影不变；公开无权／非成员读取拒绝，重放／状态读取／提交后取消零追加 Provider 调用。浏览器深浅色／390px 的 SDK receipt 使用明确 PG 协议夹具，空投影不冒称真实 SDK；真实 native 验证另有报告。具体红测与终态见实施记录。

另有真实 Temporal 结构任务：原 SDK 完整投影归档后注入确认丢失，第一 Worker 对象退出，再由新 Worker 对象／SDK adapter 重建同一 generation，Activity 1→2、epoch 2、投影摘要不变；原确认后的来源 head 改变及输入文件删除不影响原来源回读。固定候选的 754 处全部证据与完整原生观察归档已核验，history replay／已提交命令不再调用 Provider。此验证明确是 graceful Worker 对象替换，不是两个 OS 进程、强杀 GC、原生 DB resume 或 SDK AgentGoal 完整恢复。

自然语言 Turn 的原生 SDK 专项另外验证了实际 POST、同一 AgentGoal 的 LangGraph PG 恢复、独立结构预算和调查确认：结构任务在真实 Temporal 重试后，Goal 停在完成审阅而不自动交付／发布，原累计工具账本不因重试再次消费。报告 `exweb-codegraph-temporal-sdk-agent-verified-20261008-natural-agent.json` 明确 Goal workflow 为 local，实际输入是两个代码来源，没有需求／用例；这不能代替真实 Temporal AgentGoal、三源联合构建或业务语义 gold。

后续 `exweb-codegraph-three-source-agent-references-verified-20261008.json` 已独立通过实际 SDK、真实 Temporal AgentGoal/结构 Workflow、LangGraph PG、私有 MinIO 的三源链。同 Goal 的结构候选、独立调查确认、v2 显式引用 proposal 和全部候选/gap 查询保留原输入、阶段及累计工具账本；完成审阅普通继续为无操作，两个 Workflow history replay 零新增 Provider。四个来源含固定 exweb、代码夹具和合成需求/用例，732 个成员与 764 处归档证据完整回读；五个 Worker 对象在确认关口间 graceful 重建，结构 Activity 1→2。该报告不是两个 OS 进程、强杀清扫、业务 gold、语义准确率或真实执行验证，references 候选也没有自动准入画像/发布。

## exweb 的实际观察

固定干净仓库 `https://github.com/kunben-duck/exweb.git` 的 `fe5827f6b76f77ef34918d8b452ee823142332dc`，同一来源快照 **126 文件 / 180868 字节**。没有安装 exweb 依赖、运行 Maven／目标应用或调用外部语义模型。

macOS arm64 已安装 SDK＋平台资产完整指纹为 `sha256:43fbd5114fe4d222424174b9607f953ee10a219a208d8926505e76a58e1c9d3b`。npm 主包 integrity 为 `sha512-hODH/mGnCf3IUMs6rzktv/zbecJIKJfdZAYHZ9mqecb0G7ZkHaA8CZafDVnswANFEL1YFcG+lfAwc5SIXzUH6Q==`；其他平台必须独立核验资产，不能复用此指纹。根许可证不替代传递资产／NOTICE 和 release 供应链审查。

| 观察项 | CBM 0.8.1 | CodeGraph SDK 1.6.2 |
| --- | --- | --- |
| 原始自有类型投影 | 755 节点 / 1542 关系 | 526 节点 / 580 关系 |
| 语法确认规范身份 | 538 | 379 |
| 未解析身份 | 217 | 147 |
| 对照中的 Java import 准入后关系 | 1425 | 580；当前 CBM 校验器不评价 SDK imports |
| 三次原始投影相等 | 早期批次否；最新私有运行包批次是，原误目标变化仍保留 | 是 |
| 三次既有准入后投影相等 | 是 | 是 |

CodeGraph 原生公开图为 1440 节点／1962 边／122 个已索引文件，不能拿 526／580 当作原生全量。914 个未映射节点、260 个未映射关系、1106 条未准入端点关系及 16 条聚合但保留定位的原生边明确计入 gap；另有未校准概率和规范身份缺口。源文件没有被偷偷缩减为 122 个，未索引文件继续报告 unsupported。

359 个规范键由两 Provider 同时观测，CodeGraph-only 20，CBM-only 179。该交集仅用于观察差异，不是独立定位或关联 gold，也不证明 20 个多出的符号正确或 179 个未观测符号不存在。

真实隔离 PG／私有 MinIO 验证中，两个 Provider 在同项目复用原 Nasus UUID，重复登记幂等；同一 exweb 另登记到第二项目，其业务实体 ID 无交集。逐条回读两个项目的 1464 处保存证据，核验原文件 hash 和精确片段 hash。真实取消测试由父进程观察 SDK 子进程仍活跃后触发应用取消，验证子进程已 wait、所属进程组消失、会话删除、安装资产与原 checkout 不变。这是本机所属进程组取消，不是 Temporal 重启或强杀 GC 验收。

另有两个真实相邻修订 `cd9195691f2205d671fe61ba14e47744b5187ad6` → `fe5827f6b76f77ef34918d8b452ee823142332dc` 的独立 PG／MinIO 原生验证。直接读取已审查 Git 对象，不 checkout、不执行目标；完整归档 **125 文件／167083 字节**与 **126 文件／180868 字节**。后者全部文件摘要与已批准干净快照相等，两个 Provider 各对每个修订实际分析一次，报告记录原始与准入投影摘要、计数及具体 gap。

两个来源修订的 **724 个共有语法规范键**复用业务 UUID，但各有独立的 source/entity revision；旧修订不改写，两个修订的 **1463 处全部保存证据**回读核验。SDK 每修订有一处定位观察与语法投影不同，保存为同业务 ID 下的独立观察修订，而非要求 Provider 返回相同完整 revision。共享 Git tree helper 同时经既有文件差异 HTTP／canonical Tool 回归验证。这两次提交只新增／修改文档，**不是代码 rename/delete、动态调用、自动 delta 或多修订稳定性验收**；每修订一次分析不能冒称三次重复。

早期原始 CBM 的不稳定关系涉及 `HeaderAuthContextProvider.java` 的 import 被映射到不同类中的 `stream` 方法。已有生产 composite／durable 原生路径消费语法 import/package/declaration 校验而排除该误观察。对照脚本同时归档原始、准入投影和完整查询记录；早期 `exweb-provider-admission-comparison-20261008/comparison.json` **因原始投影不稳定返回 1**，不能排序、丢掉失败轮次或用准入后稳定性改写原始门禁。布局修复后的 `exweb-provider-private-runtime-final-comparison-20261008/comparison.json` 两 Provider 各三次原始／准入投影均相等、退出 0，但这不反证早期误观察，也不表示 CBM 的原生不稳定性或质量问题已修复。

## 复现入口

SDK 安装只发生在独立验证目录，不进入 API／Portal 的生产依赖：

```sh
npm install --prefix .nasus/validation/providers/codegraph-runtime-1.6.2 \
  --ignore-scripts --no-audit --no-fund --save-exact @colbymchenry/codegraph@1.6.2
```

安装后检查对应平台包、发布来源和实际资产指纹；已有版本不同或缺包时拒绝验证，不自动升级。`scripts/compare-code-providers.py` 要求 `--source-root / --repository / --revision` 对应同一干净、带正确 origin 的 checkout。Nasus 私有 detached snapshot 不带 origin，不能伪造 origin 通过检查；可使用对应的已验证 managed Git checkout。输出必须是新目录且在目标代码之外，不能覆盖历史报告。

```sh
./.venv/bin/python scripts/compare-code-providers.py \
  --source-root "$EXWEB_CHECKOUT" \
  --repository https://github.com/kunben-duck/exweb.git \
  --revision fe5827f6b76f77ef34918d8b452ee823142332dc \
  --sdk-package "$SDK_RUNTIME/node_modules/@colbymchenry/codegraph" \
  --platform-package "$SDK_RUNTIME/node_modules/@colbymchenry/codegraph-darwin-arm64" \
  --runtime-hash "$SDK_HASH" --output "$NEW_REPORT_DIRECTORY" --repetitions 3
```

此脚本使用独立本地对象目录，明确 `persisted_identity_verified=false`；真实 PG／MinIO 验证另行运行，不把本地文件系统报告当作数据库验收。测试 runner 清除父进程 NASUS 开发配置，SDK opt-in 参数使用 `EXWEB_*`，不要改弱隔离规则：

```sh
env NASUS_TEST_DATABASE_URL="$PG_TEST_URL" \
  NASUS_TEST_S3_ENDPOINT="$LOCAL_MINIO_ENDPOINT" \
  NASUS_TEST_S3_ACCESS_KEY="$LOCAL_MINIO_ACCESS_KEY" \
  NASUS_TEST_S3_SECRET_KEY="$LOCAL_MINIO_SECRET_KEY" \
  EXWEB_CODE_CONTROL_SOURCE="$EXWEB_FIXED_SNAPSHOT" \
  EXWEB_CODEGRAPH_RUNTIME="$SDK_RUNTIME" \
  EXWEB_CODEGRAPH_RUNTIME_HASH="$SDK_HASH" \
  EXWEB_CODEGRAPH_REPORT="$NEW_IDENTITY_REPORT" \
  EXWEB_CODEGRAPH_CANCEL_REPORT="$NEW_CANCEL_REPORT" \
  ./.venv/bin/python scripts/test-api-postgres.py --minio \
    apps/api/tests/test_codegraph_exweb.py -q
```

未设置 opt-in 或未验证 runtime hash 时测试跳过，不计作原生通过。具体日志、加载版本、红测及回归终态见[实施记录](./implementation-progress.md)。

同一隔离环境可运行 `apps/api/tests/test_codegraph_index_generations.py` 的 native exweb case 与 `apps/api/tests/test_codegraph_lifecycle_exweb.py`；分别用新的 `EXWEB_CODEGRAPH_DURABLE_REPORT / EXWEB_CODEGRAPH_PUBLIC_REPORT` 路径保存回执，不覆盖原日志。新增 `apps/api/tests/test_codegraph_structure_temporal.py` 另需显式 `TEST_TEMPORAL_ADDRESS`，可保存 `EXWEB_CODEGRAPH_TEMPORAL_REPORT`；没有 Temporal 或原生 opt-in 的 skip 不是恢复通过。它验证的是归档确认丢失后更换 Worker 对象与 SDK adapter 的实际重试，不冒称 OS 进程强杀或原生 DB resume。

三源原 AgentGoal 入口为 `apps/api/tests/test_codegraph_agent_temporal.py`，沿用 SDK/PG/MinIO opt-in，另显式提供 `TEST_TEMPORAL_ADDRESS`；可用全新的 `EXWEB_CODEGRAPH_AGENT_TEMPORAL_REPORT` 路径保存报告。fixture 不安装/执行 exweb，不使用开发库/桶；graceful 重建、原步骤/预算、结构重试、引用关口及 history replay 的实际范围如上，不扩大为完整自主语义构建。

两个真实修订另要求 `EXWEB_CODEGRAPH_HISTORY_SOURCE` 指向含上述完整两个 commit 的已审查 Git 对象目录，可用 `EXWEB_CODEGRAPH_HISTORY_REPORT` 保存新报告。沿用上面的隔离 PG／MinIO 与三项 SDK opt-in 环境，运行 `apps/api/tests/test_codegraph_exweb_revisions.py`。缺少历史 opt-in 时明确跳过，不 fetch、伪造 commit 或修改来源 checkout。旧 source-delta 测试使用 `EXWEB_DELTA_GIT_ROOT`；通过 `--minio` runner 执行时使用其私有 bucket，不复用开发 bucket。

## 受控代码变化夹具

2026-10-08 重新读取公开远程 HEAD，仍为原固定 `fe5827f6...`；已审查对象库只有初始化和文档变更这两个提交，不伪造新的上游代码提交。`exweb_code_changes.py` 对完整已批准来源字节构造明确的 `nasus.exweb-controlled-code-change.v1` 测试修订：`chatStream` 改名 `streamChat`、静态路由 `/stream` 改为 `/stream-v2`、修改保持原签名的 `chatSse` 方法体、删除 `DocumentUploadController.java`，以及新增明确标注为验证资料的 `NasusChangeFixture.health -> value` 调用。只在内存中生成新文件集合，不 checkout、提交、运行 exweb 或安装其依赖。

原始与变化后都为 126 个文件，但内容为 180868／178750 字节，完整来源摘要不同；文件数相同不能证明来源不变。修改锚点必须恰好一次，源文件丢失、重复、已有新路径或锚点漂移均拒绝，不静默改变样本。新修订身份使用明确 fixture policy 与内容摘要，不把它冒充真实 Git commit。方法改名得到不同规范键，不自动推断 rename lineage；共享签名和旧证据的数据库行为须由下面原生测试独立验证。

固定 Git 对象的完整静态解析 **8 passed / 2.21 秒**，核验方法原行号 38–44／新行号 40–46、路由修改／删除及新增方法 5–7／9–11 和调用边，原 Git status 不变。报告为 `exweb-controlled-code-change-syntax-20261008.json`，明确 `native_providers_verified=false / persistence_verified=false`，不是 CBM／SDK、PG／MinIO、自动 delta 或业务 gold 证明。首次纯夹具测试有一个字符串引号错误导致 collection error；修正后的 7 项纯契约和上述 8 项真实静态组合分别独立通过。

新增 `test_codegraph_exweb_code_changes.py` 接到现有实际双 Provider／隔离 PG／私有 MinIO 夹具，核验精确定位、共享 UUID、改名不误继承、删除的旧修订／证据保留、新调用及完整证据回读，结果报告保持原始／准入摘要分离。最初只完成 collection；之后在全量门禁仍运行时，以 `nice -n 10` 执行一个独立测试库／bucket 的原生用例，不启动另一批全量或浏览器任务。两批范围与结果分开记录，不将并发专项冒充该门禁的新加载结果。

首次原生执行 **1 failed / 26.93 秒**（`exweb-controlled-code-change-native-20261008.log`），停在新增调用的断言，没有完成后续 SDK 变化修订与完整证据回读。补 Provider 诊断后的 **1 failed / 28.65 秒**及原生八列查询诊断 **1 failed / 28.84 秒**明确定位为 CBM 映射漏项：原生 `health -> value` 是 `CALLS / 0.95 / lsp_type_dispatch / 1`，不是缺失原生边；旧白名单过滤这个策略。保留精确调用断言，未改名样本、补造 Provider 边或用语法边替代原生边。

新增单一／多候选、缺元数据与未知 `lsp_*` 契约先取得 **1 failed / 11 passed / 13 deselected / 4.24 秒**；只准入上游已核验的 `lsp_type_dispatch` 后，关系专项 **50 passed / 5.73 秒**、依赖／元数据／DDD 边界 **191 passed / 2.05 秒**。本组是契约和边界证据，不是原生修复通过；实际双 Provider 复验终态另记于实施记录。复现沿用前述三个已审查 SDK opt-in 和 MinIO 参数，另使用全新的 `EXWEB_CODEGRAPH_CODE_CHANGE_REPORT`：

```sh
./.venv/bin/python scripts/test-api-postgres.py --minio \
  apps/api/tests/test_codegraph_exweb_code_changes.py -q
```

缺 opt-in 时跳过不计通过。本次受控变化通过的证明范围只限测试字节和当前 Provider 契约，不替代上游实际业务变更、独立 gold、四语言、自动增量维护或完整 P0-P6。

加载兼容修复后的原生复验已独立退出 0，**1 passed / 124.28 秒**（`exweb-controlled-code-change-native-verified-20261008.log`）；新报告 `exweb-controlled-code-change-native-verified-20261008.json` 保留原始／准入摘要、Provider 观察、完整 vendor runtime pin 和两个明确来源修订。语法身份集合的 **716 个共享规范键**复用原 UUID、实体修订保持不同；两个 Provider 对改名方法映射到相同 Nasus ID，新旧方法 ID 不同，不推断 rename lineage。新增 `health -> value` 原生调用在 CBM 与 CodeGraph 的准入投影均存在，原精确方法跨度不放宽；删除的类只在旧来源修订中保留。**1,459 处**两修订 PG 登记证据全部从私有 MinIO 回读，核验文件与 exact snippet hash；批准来源的 Git HEAD/status 不变，SDK 私有缓存已清空，隔离 runner 的库／bucket 清理正常返回。

CBM 两修订规范化原始投影分别为 **755／1617**和 **755／1629** 个实体／关系，规范身份登记均为 538；SDK 为 **526／580**和 **525／580**，登记 379／378。它们不是原生全图总数或准确率。新增已核验策略后 CBM 仍有 290／288 条未验证调用解析、217 个未解析身份等明确 gap；SDK 也保留未映射类型／端点等缺口，不将本次通过冒充 complete graph、业务 gold 或动态派发正确率。固定历史报告的旧计数、摘要与 generation policy 不回填，后续原生任务使用新实现指纹。

## 尚未完成

同语料结构协议对照只推进 P0 的一个垂直切片。实际代码变化的多修订／分支语料、四语言／多仓库、rename/delete/动态调用、独立 gold／结构与关联准确率、受控真实模型、跨主机供应链锁、资源／网络／账号隔离、真实 Workflow 生命周期和完整性能／V1 门禁仍需完成。两次文档提交的规范身份和证据复用不能替代这些项，也不能替代 P1-P6 的三源语义、自动 delta、完整上下文用途、脚本／RunPlan 与真实执行反馈。
