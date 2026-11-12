# 固定 exweb 的真实运行验证

更新：2026-10-11。`scripts/verify-exweb-runtime.py` 将先前的静态 exweb 取证推进到实际 Java 构建和原生 HTTP 行为验证。它是显式运行的开发验证工具，不是知识摄入的一部分，也不能替代 ContextPack、独立用例/脚本审阅、RunPlan 或发布批准。后续的 canonical 原构建/原环境连续专项与该独立探针分开，不能混合两批工件推导业务覆盖。

## 固定输入与隔离

当前只允许 `https://github.com/kunben-duck/exweb.git` 的提交 `fe5827f6b76f77ef34918d8b452ee823142332dc`。脚本核验 origin、完整 Git blob 清单及导出字节；不执行 checkout 的 hooks、不读取工作区修改，也不修改原仓库。符号链接、子模块、路径逃逸、清单遗漏和重复成员拒绝。

构建使用本地缓存的 Maven 3.9.11 / Java 21 镜像。镜像先解析为不可变 image ID，后续启动不再使用可能漂移的 tag；构建禁止网络和自动 pull，Maven repository 只读，没有跳过测试的参数。JAR、全部包含的运行依赖和编译工件保存字节摘要；执行结束前再次检查挂载 JAR 未改变。该清单不是签名 SBOM、完整构建插件供应链证明或可重复构建精度门禁。

每次运行创建独立 internal Docker network、临时 PostgreSQL/Redis 和目标 Java 容器。PG/Redis 使用镜像内实际非 root UID/GID，全部容器移除 capabilities，目标根文件系统和 JAR 只读。HTTP 在目标容器内访问自身 loopback，不发布宿主端口；不连接开发 PostgreSQL、Redis、MinIO、API 或模型服务。目标模型 URL 固定为不可用 loopback 地址，不能借本轮验证获得模型出网权。

Docker 只用于隔离被测 exweb 及其临时组件，不改变 Nasus 前后端直接本地启动的开发约定。子进程不继承开发数据库和模型密钥；日志对本轮临时数据库密码脱敏。结束时删除并检查本轮拥有的容器、匿名卷和网络，不清理其他任务的资源。

## 实际检查与证据边界

exweb 是 FinanceEXChatService，不是退款/Orders 业务。原生检查使用固定提交中的 SessionApplicationService、ChatSessionController、FrontChatSessionDto 和 InMemorySessionRepository，记录这些文件的 Git/blob/内容摘要。

检查包括创建与精确身份/标题/ACTIVE 状态、本人读取和列表、不同用户/租户列表与读取、关闭与关闭后读取、实际 PostgreSQL 行及目标重启后的数据保留。HTTP 响应字节、状态、请求、身份和实际数据库计数分别保存，不能只凭 HTTP 200 或数据库 health=UP 宣称业务正确或已持久化。

权限拒绝与错误状态分开：返回 500 即使没有返回会话正文，也不能作为合格的授权响应；开发检查要求 403/404。关闭后的读取允许 404/409/410，不将 500 当成正常终态。这些是显式开发检查，并非维护者批准的需求或双人标注 gold，报告始终标记 `oracle_authority=developer_probe_not_approved_specification`。

报告至少区分 source、build、deployment、checks、逐请求 evidence 和 cleanup。业务检查失败返回非零退出码，但继续保留其余观察。构建、启动或协议失败同样不能返回通过；旧报告或旁边日志存在时拒绝覆盖，新的运行必须使用新路径。

当前目标代码使用内存会话存储；真实运行观察也发现会话没有进入 PostgreSQL、重启后消失，权限/关闭读取返回 500。失败是 exweb 被测行为，不改写为 passed，也不修改第三方固定源码来让 Nasus 门禁绿色。各批次终态、摘要和脚本故障的修复记录见[实施进展](./implementation-progress.md)。

## 生产 HTTP 执行器验证

显式 `--http-runner` 通过现有 Node 22+ 运行时调用生产 `executeHttpJob`，现经[原实例 HTTP application port](./owned-target-http-execution.md)及私有 operator registry 选择确切目标，不再由探针直接把 Docker ID 传入 CLI。公开 Runner HTTP API 和 job payload 不能选择该 transport。原 target/PG/Redis/network 启动实例、只读 JAR、权限、资源/mount 及无宿主端口在每次请求前后完整复核；原 wire/result 保留，执行器不产生授权或业务覆盖。

请求通过目标容器内的 curl 访问 `127.0.0.1:8080`，不使用宿主代理、curl 配置、重定向或自动重试。原 JSON POST 字节不重序列化，响应体、状态及 headers 交给生产 oracle engine；Python 生产防腐适配器再次核验原请求 wire、每个响应体/metadata/manifest 和原断言。Docker 客户端取消不等于远端 curl 已即时退出；curl 有独立 5 秒上限，本轮拥有的容器随后清理，未知写操作不自动重试。

原额外五项为实际健康检查、匿名创建、本人读取、关闭和关闭后读取。HTTP v2 另增两个任务：原响应绑定后单任务创建/读取/关闭，以及同任务关闭后读取。后二者不需要外部创建/提取 ID，独立预期不会由绑定值替代。租户/用户请求头不能借草稿 DSL 注入，原有多身份授权检查保持独立。开发 oracle 不是已批准的业务规范，也不绑定已保存 Nasus RunPlan。报告保存完整 request/result 本地工件及执行器来源文件摘要（原七个，v2 加入 http-bindings.mjs），工件目录新建为仅本账号可访问；后续新进程可以在不启动目标的情况下重新验证原响应，不将历史回放算作新的执行。

固定提交的实际追加批共 19 项检查，13 项通过、6 项失败；其中生产 HTTP engine 的五项是 4 项通过、关闭后读取因实际返回 500 失败。首次追加批被原 session ID 校验误拒绝，尚未进入生产 engine；按实际 `session_...` 格式修正后独立重跑，旧失败报告保留。目标容器/网络已清理，这些结果仍不授予 release authority。

后续显式 v2 + canary 最终批 `output/exweb-native-http-bindings-final-20261011.json` 为 **17/24 通过、7 项失败**，JAR `sha256:53e844acb746bca6e88d23e2d70beae334a5c75bfd46495e9a6c235b57e5bd84`。单任务创建/读取/关闭有 1 个原响应绑定、3 个请求和 11 个通过的开发断言；同任务关闭后读取仍 500，11 个断言 passed/1 failed，未改 oracle。其他原权限状态和 PG/重启失败保持。cleanup verified=true/remaining=[]，actual Docker 容器/网络为空；独立 `exweb-http-binding-replay-20261011.log` 在清理后重验七个任务原 request/result 和全部物理响应，没有再次派发。首批错误 Redis image ID 的 0-check 拒绝和 current 批也保留，不覆盖历史。完整正式脚本/RunPlan v1 尚不接受 capture，具体版本边界见[响应绑定设计](./http-response-bindings.md)。

新 private port 两批 `exweb-configured-owned-http-port[-final]-20261011.json` 实际退出1，均为 **14/21 通过、7 项失败**。本批未附加三项 canary，所以不与24项分母混称。最终 JAR `sha256:98d7a454c5672ef6c7207ab6f05bb3ea8df0eefd15cff010051a2406c342d8dd`：七个任务、十二个请求、两个响应绑定，37个实际 oracle 中35 passed/2 failed。两项关闭后读取仍返回500，其余原权限状态和PG/重启失败未改变。完整原实例/JAR及所有响应核验后，资源清理成功；本批仍无正式 RunPlan/执行/发布批准，不与旧 JAR/canonical 批拼接。

清理后可显式只读回放：

```bash
./.venv/bin/python scripts/verify-exweb-owned-http-archives.py \
  --report output/exweb-configured-owned-http-port-final-20261011.json \
  --repository .nasus/validation/source-cache/git/cee4bb1027919d9cfe32b341e94fdab57cac1a0bd7901495aaab8a5564763b7f
```

回放只核验完整固定来源与原 archive，不启动 Docker，不把 failed 断言改成 passed；最新回放终态见实施记录。

对本轮独立 27 项报告 `output/exweb-pinned-health-native.json`，当前工作树的
`owned_target_http.py` 已不同，默认回放按原摘要拒绝。用 `--executor-source-blob`
显式提供 `apps/api/app/infrastructure/runner/owned_target_http.py=5db881127698aac931a41563650b76459c17dce6`
后，从本地 Nasus Git 对象库读取已找回的原字节，仍验证报告原 SHA-256；不 checkout、不执行旧代码。
本地 Git 对象必须仍可用，不能用当前文件或修改报告来补齐。报告生成和回放共用完整的执行器
源文件清单，缺项、重复项或不同字节均拒绝。独立回执 `output/exweb-pinned-health-native-original-replay.json`
验证了 126 个 exweb Git blob、10 份执行器源文件、7 个原任务和 12 个物理 HTTP 响应；
5 个任务通过、2 个失败，37 条断言中 35 条通过、2 条失败。范围仅为 27 项报告的 HTTP Runner
子集，没有重发请求或授予业务覆盖；原 20/27 结果不变。三个验证入口回归共 77 项通过。

从原 Git 对象核对后，可用 `--preserve-executor-sources` 单独保存已验证的 10 份执行器原字节。
本轮旁路证据为 `output/exweb-pinned-health-native.runner/executor-sources.json`，权限 0600；
不改报告、请求和响应归档，不覆盖既有旁路证据。随后可省略 Git blob 参数，仍逐份对比
原报告 SHA-256；旁路证据损坏时不回退到工作树。实际再次回放 `output/exweb-pinned-health-native-bundle-replay.json`
确认使用证据包、零执行器 Git 对象、原 12 个响应和 2 条失败断言不变。入口专项 78 项通过。

## 原运行环境的生产核验器

最新独立批 `output/exweb-owned-native-environment-tmpfs-20261010.json` 在实际业务检查前后复用了生产 `OwnedTargetEnvironmentInspector`，不是脚本内仅检查 health=UP。目标实际用户为 65534:65534，PG/Redis 使用实际镜像内非 root UID/GID；原 JAR 为 `sha256:71363df935c54bcddb2931121fcd424a51822b0d862a48b84647c3a69eb1b63a`。运行前、运行后 inventory 都核验成功，因显式重启使 StartedAt 改变，两次 inventory hash 不相同；JAR hash 保持不变。

此前两次批已编译，但在环境检查阶段退出，尚未执行 19 项业务检查。实际 Docker 原始 metadata 表明 `--tmpfs` 在 `HostConfig.Tmpfs`，不保证出现在 `Mounts`；核验器据此同时检查 authoritative tmpfs 配置与允许的 Mounts 表示。没有取消 tmpfs 隔离检查、放宽身份或 JAR hash，也没有把先前失败报告覆盖为成功。

修正后本批终态仍为非零：13/19 项通过，6 项失败仍为跨用户/租户读取错误状态、关闭后读取错误状态、会话未写 PG、重启后丢失，以及 Runner 关闭后读取。cleanup verified=true、remaining_owned_resources=[]。新报告包含原生核验 metadata，但 `nasus_runplan_verified / llm_verified / release_authorized` 仍为 false。

正式只读工具和登记规则见[原目标环境核验](./native-target-environment.md)。本次 native 运行证明生产核验器可以消费实际 Docker，不证明 canonical RunPlan 已与实际部署持久关联，也不宣称 fixture、执行授权或业务 gold 已通过。

## canonical 原构建与原环境连续验证

后续 `test_fixed_exweb_native_environment_record_uses_original_build_and_live_inventory` 已使用全部 126 个固定 Git blob，通过 canonical source、原生构建、已审阅 RunPlan 和原构建关联进入实际 PG/私有 MinIO。部署 helper 只回读保存的原 JAR，不从当前 checkout 再构建；目标仍是本批自有 Java/PG/Redis 与内部网络，模型出网关闭。

`exweb-canonical-original-environment-record-imports-20261011.log` 已确认 **1 passed / 2283.28 秒**。实际生产 registry/inspector 消费原目标，独立 canonical 确认后的 0105 登记保存原完整 inventory。原 JAR 为 `sha256:4339de4b44e78eb834be248a32fed98eb9412bb010959bc2ab3331e6f856888d`；原报告已回读，目标/registry 删除后原 PG/MinIO 历史及原构建仍能重新授权读取，没有再次查 Docker。cleanup verified=true、remaining_owned_resources=[]，原导出 checkout 已删除。

该专项证明原来源、构建、计划和环境登记的连续关联，不复用上文独立业务探针 JSON，也不把开发 oracle 升级为批准规范。模型/调度和业务断言仍是明确 protocol specimens；`execution_authorized / business_coverage_verified / full_quality_closure_verified` 保持 false，正式执行/通过计数为零。测试结束会清理隔离 PG/bucket，报告不是永久生产工件；不同批 JAR 摘要不同，不能声称构建可重现性。

新增[原实例健康端口](./native-target-health.md)的重载专项已确认 **1 passed / 2590.25 秒**（`output/exweb-canonical-original-health-current-20261011.log`）。实际固定 SELECT 1、PING 和应用本地健康响应与原环境 epoch/JAR 绑定，原 JAR 为 `sha256:ebfb0f316c6a9068b7c6682c308e83fff8147d97839ec4c737285efca7b490ea`，原 health hash 为 `sha256:afff3a8831d7d8e686a95ae413bca642256580b855ac7b8d7c6b286bee4ad3d0`。报告实际回读确认 cleanup verified=true、remaining=[]、原代码导出删除；owner 容器列表为空，29952/29977 均已退出。

这次健康观察仍是 internal，未独立持久登记；原 0105 字节/false 权威不变，正式执行/业务覆盖/完整闭环为 false。0106 新增独立健康登记和历史读取，后续独立 PG/MinIO 批已1 passed/1229.70秒；包含真实原生 exweb 的新 canonical 批也已1 passed/4017.41秒，见[健康契约](./native-target-health.md)。不能拿旧加载批证明新入口通过。fixture/locator、持久派发/恢复和逐用例真实覆盖继续交付。

## 有界实际隔离对照

显式附加 `--isolation-canaries` 使用独立 fresh HTTP/宿主文件正向对照、原目标拒绝及 socket 不可见；完整原响应和epoch/source/JAR前后核验、精确资源清理见[有界隔离探针](./native-isolation-canaries.md)。它不访问互联网或开发接口，不把一个curl失败或internal配置当作成功，也不声称全部出口/宿主接口验证。

`output/exweb-native-isolation-canaries-20261011.json` 已实际终态：126固定Git blob、JAR `sha256:0541660ded51b8d1b9cc60fda708e5abf5d1c711871c53c35124cbd80f9f4cea`，三项canary通过、七份完整原响应hash独立重算成功、cleanup verified=true/remaining=[]。整批仍退出1：12/17项通过、5项失败，保留原exweb权限/关闭错误状态与PG/重启持久化问题，未启用本批HTTP Runner。它不是canonical0106那一批、不是正式执行或维护者批准gold，不拼接不同JAR结果。新协议/原脚本/边界批69 passed/0.34秒也不能代替上述实际Docker结果。

## 显式运行

以下命令实际执行被测仓库，因此需要 `--execute-reviewed-target`；仅做画像摄入时禁止调用。镜像与 Maven 依赖必须已经可用，缺失时离线失败，不自动安装。

```bash
./.venv/bin/python scripts/verify-exweb-runtime.py \
  --execute-reviewed-target \
  --http-runner \
  --isolation-canaries \
  --repository .nasus/validation/source-cache/git/cee4bb1027919d9cfe32b341e94fdab57cac1a0bd7901495aaab8a5564763b7f \
  --maven-cache /Users/uben/.m2/repository \
  --report output/exweb-native-runtime-new-run.json
```

`tests/test_verify_exweb_runtime.py` 检查执行显式性、输入/hash/路径边界、离线/只读参数、HTTP 原字节、错误状态、历史不覆盖和凭据隔离。其 HTTP specimens 只验证脚本协议；真实目标结果来自上面的独立进程，二者不混称。

## 仍需连接的正式链路

exweb 原生验证归档仍是本地开发报告；临时 JAR、数据库和容器结束后清理。它没有创建 canonical ToolInvocation/ContextPack/Run，不提供生产证据下载或永久 MinIO 构建归档。报告包含 `nasus_runplan_verified=false / llm_verified=false / release_authorized=false`；调用者不能仅导入这个 JSON 就获得执行或覆盖权威。新的原用例观察 MinIO 接口单独用本地 HTTP 夹具验证，不能把两批工件拼成已完成正式 exweb 执行。

后续必须将已批准 case/step/oracle、独立审阅的脚本修订、可回读的构建工件、部署/environment/fixtures 和原上下文连接到正式不可变 RunPlan，实际执行及证据经治理入口持久提交。完整五用途、旧消费者切换、退款示例、外部模型、独立 gold、多语言、增量/overlay/合并及安全容量/恢复门禁仍按原 P0-P6 范围交付。

## exweb 试用入口与首轮记录

从 Build 点击「导入 Git 仓库」，选择已有项目或创建 `exweb 首轮验证`，填入
`https://github.com/kunben-duck/exweb.git` 和完整提交 SHA
`fe5827f6b76f77ef34918d8b452ee823142332dc`。验证时应核对实际采集的 commit，
不能用后来分支头覆盖历史结果。
需求与测试资产可以分别上传，仓库内的 `exweb-context-requirements.md` 和
`exweb-test-cases.csv` 可用于演示三源接入，但只代表测试样例，不是维护者批准的规范。
用 exweb 自带架构说明和实测结果做用例审阅时，参考[首轮验收基线](./exweb-acceptance-baseline.md)，
其中区分了现有存储行为、开发探针预期和需要另外确认的上线能力。
点击「构建系统画像」，核对捕获的来源并单独确认结构分析预算；候选保存后，按页面提示继续证据调查与引用审阅。
首页的质量闭环、发布质量快捷项分别进入指定项目的版本工作区和发布准备度页面，导航本身不执行工具或批准发布。
在「执行原业务用例」中，可以通过「查找本计划的数据准备命令」选择与当前计划版本及用例匹配的历史 setup 命令，
也可直接填写原命令 ID。选择仅填入引用，不代表准备结果通过；仍须核验环境、接口定位及每条准备引用，再独立确认执行。

2026-11-09 首轮分开取证：

- 隔离 PostgreSQL 的真实浏览器从空账号创建项目，导入 exweb 远端 Git，上传两类样例并保存结构候选、调查证据与待审阅引用。六项首页操作均到达预期项目入口，没有覆盖当前聊天草稿。构建审阅回读核验了 128 个来源文件（含两类样例各一份）和 770 条成员证据，但仍报告代码分析不完整、关键冲突及全计划预算未核验、缺口责任未分配。没有授权模型调用、目标执行或正式发布。
- 同一 exweb 修订的结构、引导接入和导航专项共 12 项通过。该批使用测试执行器，不代替原生 HTTP 执行。
- 独立原生探针启用 `--http-runner --http-fixtures --isolation-canaries`，通过 20/27 项且清理核验通过，报告为 `output/exweb-native-runtime-20261109.json`。跨用户读取、跨租户读取及关闭后读取返回 HTTP 500，未满足探针预期；未观测到对应 PostgreSQL 会话记录或重启后恢复。保留失败，不将探针报告直接晋级为发布证据。

后续回归继续使用 exweb 的固定修订和明确的断言输入。完整 RunPlan 生命周期、经批准的业务预期、用例运行证据与发布判断仍需独立核验，不能由这三批记录拼接得出通过结论。

### 正式 Temporal 交接的首轮失败

`output/exweb-canonical-handoff-20261109.log`：固定 exweb 原 126 个 Git 文件、实际构建和自有
Java/PG/Redis 目标，经过保存 RunPlan、原构建关联、环境与 locator 登记和 fixture 确认，进入
真实 Temporal setup Activity。终态 **1 failed / 2255.47 秒**；workflow 返回 `failed`，不是业务执行成功。
首次运行在 fixture 健康预检的第一个 Docker inspect 启动前失去有效授权。重复的 Worker 原始范围
读取约 10–15 秒/次，运行中反复续约；第一个 Activity 约 723 秒后取消，重试报告
`HttpFixtureAuthorityDenied`，未进入正式业务用例。该批自有容器已清理，未改写授权时长或原业务响应。

本批先于配对父计划与预检归档去重改动启动。新代码的本地回归覆盖两次独立原环境核验、健康检查、
授权失败与父链一致性，不能用旧批证明修复。继续优化子进程轮询与完整归档核验的边界时，须保留
当前 actor、原命令、授权和 PG 所有权检查，以及实际派发／归档前后的完整核验和失败时的原始证据。

后续将 `ExecutionWorkGuard` 接入 fixture 和 case 的原生 Runner。只读健康探针及已启动
子进程的轮询检查实时 actor、来源权限、原命令、许可和 PG 租约，不重新展开整个 RunPlan。
运行 HTTP 子进程前后仍执行完整校验；派发和结果登记保留原事务围栏。轮询失败回收进程且
不提交结果，已有 claim 仍按原历史回读，不能把未知副作用当作重试许可。业务 case 的轮询
和续约同样检查原命令和 PG 时间，不以完整 MinIO 父链占用轮询；原 claim/complete 使用完整核验。
新正式 exweb 批为 `output/exweb-canonical-handoff-poll-fence-20261109.log`；在取得并核验
真实终态前，不能视为这条运行链已通过。该批先启动以验证 fixture，再补入 case 轮询代码，
因此即使该批走到业务执行，也不替代新 case 轮询路径的独立验证。

该批终态为脚本审阅失败；并行 case PG 专项在用例批准返回 503，均未到原生 Runner。
主机电源日志确认 2026-11-09 01:18 至 18:53 的低电量休眠跨过原确认窗口。
未延长授权或把中断批当成性能结果。新批 `output/exweb-canonical-handoff-evidence-20261109.log`
用新独立确认和同一固定提交重跑。通过 `EXWEB_CANONICAL_HANDOFF_REPORT` 可显式输出仅含摘要、
原始观察状态和 HTTP 状态码的报告；完成全部阶段并在自有目标删除后成功回读同一历史才写入，
不覆盖旧报告，不含响应内容或业务批准。

Portal 在原 RunPlan 的执行面板按原用例显示已保存结果、断言的原预期和匹配的实际 HTTP 状态码。
未发送与效果未知分开列出，不用零正式覆盖计数遮盖真实失败，也不新增执行或重试入口。

有权限的操作者可从项目「执行记录」打开「按命令 ID 查询执行结果」，输入原业务执行命令 ID。
无需原浏览器的计划或执行恢复记录。入口通过现有私有 GET 读取原命令、固定计划和完整观察，
核验项目、计划和工件摘要、执行分母；不确认命令、不发目标请求，也不把历史计划设为当前。
同页也可打开「查找历史测试数据操作」，分别查看准备、清理与取消。打开前不请求历史，展开后
只读原命令和阶段记录；业务结果未登记时，不用测试数据操作的状态代替业务断言结果。
隔离 PG/MinIO 的 case 轮询对照已通过（1 passed / 213.55 秒），确认轮询不拿写锁且可回读
原历史；该批是协议 Runner，不能代替正在运行的固定 exweb 正式批。

### 可复跑的正式验收命令

先启动本地 PostgreSQL、MinIO、Temporal，准备 origin 为 `https://github.com/kunben-duck/exweb.git`
且包含固定提交的本地 Git 仓库、离线 Maven 缓存、已审核并存在于本地的三个 Docker 镜像 ID：

```bash
npm run verify:exweb -- \
  --repository /path/to/exweb \
  --maven-image-id sha256:<reviewed-maven-image> \
  --postgres-image-id sha256:<reviewed-postgres-image> \
  --redis-image-id sha256:<reviewed-redis-image>
```

默认只读预检，不启动目标或拉取镜像。使用同一参数加 `--execute-reviewed-target` 后才运行。
可用 `--maven-cache` 指定非默认离线缓存。正式批次使用独立 PG 库、私有 MinIO 桶、Temporal 队列
及本批 Docker 资源。迁移后先用同一 PostgreSQL 执行历史查询快检，失败则不构建目标。
每次生成新的 `output/exweb-canonical-runs/run-*/pytest.log`，只有 pytest
成功且同批 `verification.json` 通过完整性检查才返回成功；测试 skip、失败或缺少清理后回读均不算通过。

可用已有报告生成便于试用验收的只读摘要，不启动目标、不连接数据库或 Temporal：

```bash
./.venv/bin/python scripts/verify-exweb-canonical.py \
  --native-report output/exweb-pinned-health-native.json \
  --summary output/exweb-review.md
```

正式批次生成完整回执后，可同时传入 `--canonical-report output/exweb-canonical-runs/run-.../verification.json`，
换用新的摘要路径。摘要保留原通过／失败、HTTP 状态和断言计数，不导出响应正文、密钥、环境地址或
调用令牌；独立探针和正式执行分列。未提供正式回执时明确标记证据缺失；摘要不替代正式验证命令的退出状态。
独立探针摘要还展示固定场景的 HTTP 状态、会话数据库行数和重启后列表条数；不会把这些观察混入
正式 RunPlan 的断言结果。正式回执的展示同时列出 Runner 调用和 Workflow 数量，并注明使用的是
受控测试输入和断言，不是独立批准的业务验收条件。

新批次的 v2 回执在目标拆除后，通过原命令历史逐条回读清理观察，保存与原业务用例一一对应的
结果状态和摘要。Workflow 完成仅说明结果已归档，不等于清理断言通过；自有 Docker 资源清理
单独核验。旧 v1 回执缺少逐条清理状态时，可用 `--cleanup-ledger <只读账本.json>` 补充同批
拆除前的 PostgreSQL 观察。计划、工件摘要和用例集合必须完全相等；不把它标为拆除后回读。
如已生成匹配的独立 PostgreSQL／MinIO 拆除后只读归档回执，也可改用
`--cleanup-archive-witness <归档回执.json>`。它与账本选项互斥，不替代 v2 的正式 API 历史，
也不把旧 v1 回执升级为 v2。

`exweb-canonical-handoff-evidence-20261109.log` 已终态失败（2122.73 秒）：首个 fixture
进入预检，第一次 Activity 超时，第二次遇到过期许可，未进入业务用例；自有目标容器已清理。
运行中读取隔离 PG 时，派发、结果及业务 claim 均为 0，不能当成业务失败或测试通过。
随后将独立预检／派发归档核验与续租的实时 actor、命令、授权和所有权复查分离；写入前后
仍校验完整父链，派发事务内另查审阅是否当前。PG 续租时钟及回滚回归 26 项通过。

`output/exweb-canonical-runs/run-70_lykgz/pytest.log` 使用上一轮续租修复后仍失败（2121.93 秒）。
首个 setup Activity 在 720.71 秒被取消，重试报告原授权失效，没有完成正式用例交接。
常规续租约 3 秒，但其中一次仅等待项目事务锁即耗时 58.67 秒。该批专属 Docker 目标已清理。

新版 journal 在同一次原始范围校验中编译命令并返回父计划 pin；事务中所有权检查用该 pin
核验 PG 注册、当前操作者、原租约和 PG 时钟，不重新打开同一归档。计划当前性、ACL、
许可和命令围栏仍在写入前后检查，授权和超时不变。Docker 容器快照按原始三容器 ID 批量
读取并逐项核验；健康预检的 Docker 调用从 21 减到 13，保留全部探针、前后快照和 JAR 摘要。
相关协议和边界回归 416 项通过。`output/exweb-batched-preflight-native.json` 的独立 Docker
复验达到观测阶段，仍是 20/27 项通过，7 项失败集合未变，清理已核验；不作为正式 RunPlan 证据。
正式复验单独记录在 `output/exweb-canonical-runs/run-1myvx9bn/pytest.log`，以该批终态和
清理后可回读的 `verification.json` 为准。

后续将内部健康探针与父链读取分离：fixture 自己在探针前后核验原环境归档和计划；业务
用例准备同样保留原计划／构建及命令末次复核。探针消费已核验的类型化实例清单，不再内嵌
两次计划／构建读取；实时 ACL、operator 策略、PG 租约回调和原实例摘要仍复核。对外健康
读取仍独立核验父链。相关 API／边界回归 502 项、真实 PostgreSQL 原命令／租约围栏 38 项
以及开发冒烟测试均通过。
`output/exweb-pinned-health-native.log` 使用开发权限样例和实际固定 exweb Docker 实例：PG、
Redis、应用三项探针通过，完整实例清单与输入相等；同批业务检查仍为 20/27，清理通过。
这不是正式授权或 RunPlan 执行证据；正在运行的 `run-1myvx9bn` 在该改动前加载。

该批首个 Worker 的历史检查耗时约 29 秒，同时一次续租等待项目写锁约 14 秒。新版 Worker
和历史读取共用无写锁的原始记录核验，返回前复查操作者；派发与结果登记仍在原写事务内重验。
真实 PG 回归证明读取不会被另一连接的项目／角色写锁阻塞，且读取期间的撤权仍拒绝返回；
相关真实 PG 共 57 项、后端／边界回归 299 项通过。执行记录的浏览器回归覆盖三种主题／
宽度组合和撤权、取消、篡改，均零写请求；它不是原生 exweb 派发验收。

`run-1myvx9bn` 已以 **1 failed / 2170.59 秒**退出。首个 setup 的健康预检 237.88 秒，
派发预留事务 33.92 秒；隔离 PG 曾实测 1 条 fixture 派发预留、0 条原始结果、0 条业务用例
派发／结果。Activity 达到 12 分钟上限，重试先遇到原 Worker 的租约、再因原授权失效而停止。
Temporal 流程结束时应用结果是 `failed`；本批自有目标清理成功，未生成完成回执。保留原请求
效果未知，不从缺少归档推断“未发出”，也不重放旧预留。

新版保留每次只读轮询的实时来源权限、许可、命令和租约，合并 Worker 命令复查的重复包裹。
fixture 在只读整理／验证阶段使用实时围栏，PG 派发和结果写入仍完整核验原计划，Runner
在实际子进程启动前和返回证据前继续完整校验。追加原目标前置、HTTP 子进程和原目标后置的
脱敏阶段耗时，区分未返回子进程结果和未提交证据。正式新批
`output/exweb-canonical-runs/run-808_h7ts/pytest.log` 使用同一固定提交与新的隔离实例和确认，
不延长许可或 Activity 上限；以该批实际结果和清理后回读为准。

独立耗时对照 `output/exweb-native-http-phase-control.json` 使用同一提交与同一 126 文件清单，
27 项结果与 `exweb-pinned-health-native.json` 完全相同（20 通过、7 失败，清理已核验）。
13 次 Runner 调用的阶段耗时见同名日志：目标前置核验 135–159 ms、HTTP 子进程
927–2209 ms、目标后置核验 140–166 ms。对照包含实际 exweb 请求与 Docker 实例核验，
不含 Nasus 正式授权／租约／归档事务；不能把这些耗时当作正式 RunPlan 的端到端延迟。
可读版为 `output/exweb-first-verification-phase-control.md`，不包含原始响应或执行令牌。

正式用例交接读取固定 setup 及全部 cleanup 槽时，单次历史查询共用已核验的 setup 响应
与 capture；各槽仍核对原命令、PG 派发及已归档的结果。初始和结束重查计划、来源权限及
actor；交接仍执行两次原命令与历史读取并比对结果。单 cleanup 契约样本的前后结果相等，
每次查询完整父计划读取从 8 次降至 3 次、setup 归档从 2 次降至 1 次。后端和边界
395 项通过，实际 PG actor 回归 29 项通过，含已有写锁时只读及读取期间提交撤权；PG
专项的目标响应是协议样本，不替代正式 Docker 执行或 MinIO 归档实跑。此改动晚于
`run-808_h7ts` 加载，不计入该批。

随后仅在默认受控 HTTP transport 且传入类型化工作围栏时，预备检查和子进程返回后的
中间检查走实时围栏。完整校验仍分别在子进程启动前、子进程交回原始字节前及目标实例
复核结束后执行；自定义 transport 和普通回调维持原行为。受控子进程契约对照中完整
校验从 5 次减至 3 次，任何一关撤权都不返回结果，启动前撤权不创建子进程。相关后端
和边界回归 323 项通过；这是协议子进程证据，不是当前正在运行的正式批次或真实目标耗时。
原授权时钟两项回归在独立 PG 和私有 MinIO 上均通过（589.20 秒）；验证写入前过期与
审计／Outbox 已 flush 后过期都不留下已提交许可。此前未启用 MinIO 的批次在 recipe
登记前置步骤失败，不计入授权时钟覆盖，也不改变生产的私有 S3 要求。

Worker 解析原授权时仅读取一次完整 recipe／环境／RunPlan；独立用 PostgreSQL 时钟核验
实时权限，并将返回的授权元数据摘要与本次已核验的归档记录比对。派发和结果登记前的完整
核验未移除。Worker 执行后完成状态及绑定后的历史查询同样只解析一次原授权；仍通过原
journal 核验逐项派发和响应，最后复查当前权限。未绑定／已取消的准备状态不打开目标归档。
相关应用、生命周期、取消和边界回归 629 项通过。真实固定 exweb 的父链等价对照和实际
PG/MinIO public ToolRuntime 归档回读专项分开运行；`run-808_h7ts` 加载早于本次改动，
其进展不能作为此改动实跑证明。

原命令运行轮询在同一只读事务内使用已核验的 intent，不重复验证同一条记录；仍检查
原确认摘要、PG 时钟、运行状态及当前 actor。对 `run-808_h7ts` 正在运行的真实原命令
做旁路只读对照（事务拒绝写入、无 `FOR UPDATE`），单次读取 SQL 709 → 359，
本机单次耗时 561 → 243 ms。这不是 Worker 进程加载新代码或端到端性能验收。默认目标
注册表读取本身已在前后做实时权限检查，类型化 HTTP 轮询不再重复加一次外层检查；
自定义适配器原检查不变。命令、Runner、取消和边界相关 514 项回归通过。
派发后的默认目标复核把原策略摘要传给实例读取端口，策略不符时在任何 Docker 调用前
停止；读取过程仍逐次检查实时权限，并在全部 Docker 读取之后重查原注册表。对照输出
原响应字节和 Docker 调用数不变，减少重复注册表读取；自定义 transport／实例读取端口
仍使用原路径。扩大相关回归共 632 项通过。

`run-808_h7ts` 首个真实 setup 已登记 `passed` 结果。旁路只读对照使用该批 PG 注册与
私有 MinIO 工件，通过原归档读端口验证请求／响应字节及 receipt 摘要；捕获 1 个原响应
绑定，失败断言为 0。该时点隔离 PG 为 1 条 fixture 派发、1 条结果、0 条业务用例派发／
结果。旧代码实测 Runner 原目标前置 45.21 秒、子进程 86.22 秒、原目标后置 172.99 秒、
结果登记 50.18 秒；这些阶段含权限轮询，不是目标 HTTP 延迟。首个 setup 不等于完整用例、
清理后回读或通过验收；正式结论仍以同批终态和完整回执为准。

该批最终 **1 failed / 2087.98 秒**：真实 setup 原结果已落盘，但首个 Temporal Activity
在归档回读阶段触发 12 分钟上限；同一命令重试在进入完成步骤前遇到过期原授权，未
进入业务用例。该批自有目标清理已核验，无完整 `verification.json`。不重发旧请求，
不改写旧终态或将首个 setup 当作业务验收。

新 Worker 仅在原 Temporal Activity 重试时先检查同一已绑定命令是否有归档结果；若有，
以当前权限回读全部原始响应，并由现有状态及终态事务确认所有必需阶段均已观察。此路径
只补写原命令完成状态，不能派发、续签或取得租约，原操作的授权／确认 TTL 不变。证据
缺失、取消、撤权及原命令篡改仍拒绝补写。应用／权限／边界回归 454 项通过。隔离
PG/MinIO/Temporal 的确认丢失专项单独记录于 `output/exweb-fixture-archive-recovery-temporal-minio.log`；
使用最新代码的新固定 exweb 正式批次为 `output/exweb-canonical-runs/run-b8rpzf46/pytest.log`。

原授权解析的固定 exweb 只读 PG／MinIO 对照已通过（1034.25 秒），两侧完整输入摘要和
151 份原对象字节摘要一致。实时解析的完整 RunPlan 读取为历史控制 9 次、新版 1 次，
独立 PG 权限核验保持 1 次；SQL 71252 → 8425。该对照不执行目标 HTTP，不是端到端
耗时或业务准确率验收。真实 Temporal 重试策略 7 项通过（33.21 秒），包括同 ID 第二次
Activity 的恢复参数与历史重放。

真实公开 ToolRuntime／隔离 PostgreSQL／私有 MinIO 的回读专项通过（1416.69 秒，
`output/exweb-single-fixture-history-public-minio.log`）。同一原 setup 命令执行和历史回读
均只解析一次原授权，用同一幂等键重提不会再次派发；独立清理请求仍使用原响应捕获。该专项的
目标 HTTP 和 Temporal 为测试替身，不是 exweb 目标运行。

真实 Temporal／隔离 PostgreSQL／私有 MinIO 的归档恢复专项通过（766.98 秒，
`output/exweb-fixture-archive-recovery-temporal-minio.log`）。首个 Activity 在原响应落盘后
故意丢失确认，将原 grant 时钟推进一小时后，同一 Workflow 的第二次 Activity 完成原命令。
原派发、结果、租约和命令归属未变，Runner 只收到一次请求；公开历史保留原失败断言，
Temporal 历史重放通过。目标响应是显式测试样本，不是正式 exweb 用例执行。

正式验收工具独立固定本轮 4 条用例：即使较小报告同时缩减 setup、cleanup、Runner 和
Workflow 计数，也不得视为完整回执或生成正式汇总。新增三项负例先复现旧行为，修复后
验收工具和架构边界回归共 180 项通过。已在运行的 `run-b8rpzf46` 不重启，生成的报告
仍须由新版工具复验。

配方登记将实时 ACL 检查与完整归档重验分开：暂存记录前核验 ACL，最后在同一事务内
回读私有归档、完整计划并复查 ACL。配方、审计和 Outbox 不会在最终核验前提交。
应用对照中新登记的完整计划读取从 3 次降到 2 次，私有配方归档回读从 2 次降到 1 次；
这是应用提交核验次数，不含存储适配器始终执行的写入校验回读。原命令重放只读取一次原计划，
撤权后不再进行提交核验读取。相关回归 246 项通过。固定 exweb 的真实 PG／MinIO 专项首跑
因测试漏算写入校验回读而失败；区分两类读取后重跑通过（`1 passed / 597.57 秒`，
`output/exweb-recipe-atomic-archive-minio-recheck.log`）。专项验证原计划和配方归档及提交回滚，
不执行 exweb 业务 HTTP，也不替代正式执行回执。
运行中的 `run-b8rpzf46` 在改动前加载，不能用于推断本次耗时改善。该批首个 setup 授权
阶段实测另有 6 次完整父链读取，各约 10–15 秒，是 Nasus 归档与权限核验，不是 exweb HTTP 响应耗时。

授权签发同样拆开即时 ACL 检查和完整父链重验。锁内暂存前仍复查 ACL 与 PostgreSQL
确认时钟；暂存 grant／审计／Outbox 后完整重验父链，再检查原确认时钟才提交。返回前仍
做完整复核，历史授权不会续期，原 15 分钟 TTL 不变。应用对照的完整父链读取由 4 次
降为 3 次，迟到的审阅变更仍拒绝签发；授权／时钟／边界回归 293 项通过。
真实 PostgreSQL 与 MinIO 的两处确认超时回滚均通过（`2 passed / 604.80 秒`，
`output/exweb-grant-clock-split-minio.log`）：暂存前及 Outbox 暂存后过期均不提交授权、
审计或事件。不把此改动算进已运行批次的耗时。

`run-b8rpzf46` 的首个真实 setup 已完成。执行 Activity 的 worker 执行、归档回读和终态提交
分别为 391.37、37.29、1.50 秒；Temporal workflow 已结束，未重复此前的归档超时。独立
只读 PG／MinIO 回读通过（`output/exweb-run-b8rpzf46-first-setup-readback.log`）：原请求 1530
字节，原结果 5851 字节，1 个捕获，归档与回执摘要一致，结果为 `passed`，未重新派发。
这只验证该批 1／4 个 setup，不是业务用例结果或完整验收回执。

该批首个派发的 health preflight 耗时 92.59 秒。新代码把紧邻探测前的重复计划读取合并，
从探测前两次、探测后一次改为前后各一次；事务锁内复核不变。setup 仍与原配方完全匹配，
cleanup 仍先从原归档绑定真实捕获，伪造命令在 Docker 探测之前拒绝。两条负例先复现多读，
修复后预检、原归档和架构边界共 300 项回归通过。该改动未加载到正在执行的正式批次。

业务用例的输入解析和历史回读现在经环境记录端口一次读取同一观察、原计划和原构建绑定，
不再为环境记录单独重读相同父链。原环境请求与预期绑定不匹配时，不访问私有归档；正式
执行仍检查原审批是否当前，并在所有定位、fixture 和健康核验之后重读完整父链。
应用对照中两条路径的完整计划／构建读取均由 3 次降至 2 次，返回内容与旧路径一致。
用例输入、环境、授权和架构边界回归 315 项通过，后续环境专项 28 项通过（含错绑定及
过期输入在归档前拒绝）。当前正式批次未加载此改动，不将它视为业务执行耗时验收。

原测试数据执行／取消历史从一次完整历史授权读取取得原请求、配方和计划定位，不重复打开
同一配方。业务 setup 交接可复用这一读取的确切输入，结尾仍独立重查原命令与物理阶段。
应用对照中一次执行历史的配方读取从 3 次降为 1 次，环境父链读取从 2 次降为 1 次；
读取前后命令不一致仍拒绝，页面 DTO 不增加授权、正文或秘密。相关回归 483 项通过，
不把该对照当成正式业务用例耗时或覆盖验收。

业务用例派发和结果写入使用两级检查：数据库事务先校验原命令、当前执行权限与租约，
再暂存记录和 Outbox；提交前完整复核一次原输入，随后仍重查命令、账号和 PostgreSQL
租约时钟。每次写入持锁期间的完整核验由 4 次降为 1 次，普通回调路径不变。
私有结果归档仍在写前完整复核、读回时核对原始证据；写后及回读结束只检查实时权限、
取消和所有权，最终事务仍复核完整输入。针对性回归证明撤权会阻止回读、输入变更会
拒绝提交，原派发不会被重发。用例执行、输入、历史及边界回归 331 项通过。真实
PostgreSQL／MinIO 写入专项通过（`1 passed / 241.20 秒`，
`output/exweb-case-transaction-guard-minio.log`）：派发与结果均在 Outbox 暂存后只调用一次
完整核验；该核验拒绝时，记录、审计和事件一并回滚。专项使用 Runner 响应样本，不执行
目标 HTTP。正在运行的 `run-b8rpzf46` 未加载这些改动，不能用于测量新路径耗时或证明新版
正式交接完成。

`run-b8rpzf46` 已核对 4／4 个 exweb 原生 setup：四个原始结果均 `passed`，四个原命令均
`completed`，完成标记均在对应 Temporal 工作流返回后记录。单独的业务执行命令已进入
`running`，随后 `NasusRunPlanCaseWorkflow` 在第一次业务派发前失败。终态为 `1 failed / 3857.67 秒`，
本批目标资源清理已核验。无业务用例结果、逐组 fixture 清理回执或清理后业务回读，不生成
完整验收回执。

用例执行器的真实 PostgreSQL／MinIO 集成回归通过（`1 passed / 228.45 秒`，
`output/exweb-case-executor-live-fence-minio.log`）。Runner 等待中的权限和租约轮询只执行
只读 SQL、不重跑完整核验；正式结果写入后可回读原观察。该专项使用 Runner 响应样本，
不计为目标 exweb HTTP 执行或覆盖。

业务接力和历史回读从已验证的原 setup 响应捕获推导原清理命令，不再为这一步第三次
读取同一计划及环境。每组保留首次和末次完整核验，读取记录后、打开物理归档前也
检查当前权限。仍拒绝替换命令、篡改的响应、父计划变更以及已派发清理的实时业务输入。
应用和边界回归 366 项通过；真实 PostgreSQL 检查 30 项通过，其中新增用另一连接实际撤回
角色，验证原 setup 归档读取未发生。该 PG 专项使用归档替身，不计为实际 MinIO 读回；
`run-b8rpzf46` 没有加载本改动。

当前工作树的 Portal build、Lint 和 1507 项 Portal 契约测试通过。独立 PostgreSQL 和端口的
`npm run test:smoke` 也通过（`output/exweb-current-worktree-smoke.log`），检查项目创建、来源
索引、画像候选保存、Agent 查询和质量闭环入口。Smoke 使用协议替身，不证明正式目标执行。

旧批业务命令仍在运行时，通过只读 PostgreSQL 和禁止写入的 MinIO 客户端复现了原输入故障：
setup 历史的 `UNION ALL` 前两支裸 `NULL` 被 PostgreSQL 推断为 `text`，无法与取消支的 `json`
合并（SQLSTATE `42804`，`output/exweb-case-run-b8rpzf46-history-sqlstate.log`）。显式转换为
原命令载荷的 SQL 类型后，又定位到组合仓库同名 `_row` 指向写入构造器；改为专用历史解码。
查询的项目、来源可见性和只读边界未变。用修复后的生产组合仓库读回旧批一条真实的 completed
setup（`output/exweb-case-run-b8rpzf46-history-fixed.log`）；未派发请求。旧批随后销毁，不能
用这条只读结果替代全链路验证。历史/架构专项 258 项通过，业务输入与交接回归 295 项通过。

单次业务结果读取前后两次核验共用不可变源码证明，不共用权限、原计划、定位或物理 fixture
读回的结果。对照仍观察到原输入两次重验；中途撤权或替换定位归档均拒绝，后续读不复用前一
读取作用域。修复后的独立正式批次为 `run-bh5xllxe`，预检通过，使用同一固定 exweb 提交和
镜像；未复用任何旧批 setup 或业务结果。

正式入口增加真实 PostgreSQL 历史查询快检，失败时由 `pytest -x` 阻止后续构建。
同一连接上的事务临时表使用实际迁移列类型，三个命令类型经过生产组合仓库验证：首尾分页、
取消命令关联原执行、缺少来源权限不可见、跨项目引用使查询失败而非返回部分历史。临时样本
不登记业务记录或派发请求。真实 PG 快检、CLI 和边界共 181 项通过（`output/exweb-history-pg-early-canary-final.log`）。
已启动的 `run-bh5xllxe` 包含历史查询修复，但早于快检接线；不为新增检查重启该批次。

Worker 为原业务用例和 fixture Activity 增加内部故障日志，记录受限异常类型与合法的五位
SQLSTATE，不记录异常正文、堆栈、SQL 参数或请求载荷。Temporal 和 API 的公开错误及
重试策略不变；拒权仍不重试，临时失败仍沿用原命令身份。诊断、实际 Temporal 复验和
相关边界共 178 项通过（`output/exweb-case-worker-diagnostics-temporal.log`）。正在运行的
正式批次未加载这项诊断改动。

真实 PostgreSQL／MinIO 公共历史专项已读到待确认、取消后列表／详情和原操作观察，Runner
没有派发；终态仍为失败，因为取消后的两次审计快照比较不一致（`1 failed / 611.44 秒`，
`output/exweb-fixture-composed-history-pg-minio.log`）。原快照未指定排序，不能从该差异
单独判断数据发生了写入。复验按主键比较完整快照，仍检查 Runner 无派发，未排除或忽略
任何审计字段。首版全局 PostgreSQL 只读保护在进入历史用例前拦住了认证的会话心跳更新
（`output/exweb-fixture-composed-history-readonly-pg-minio.log`），并未验证业务查询。新版
仅在三个历史用例内施加真实只读事务，仍使用正常认证。只读作用域、历史投影、观察和
验收入口回归 138 项通过（`output/exweb-history-scoped-readonly-regression.log`），完整接口
专项为 `output/exweb-fixture-composed-history-scoped-readonly-pg-minio.log`。

结果页直接打开执行记录时，所选命令本身就是原执行；读取账本前后各完整查询该命令
一次，不再在同一边界重复读取。取消记录与原执行不同，仍各自独立核对；权限、账本及
晚到状态变更继续复查。对照中执行历史查询从 4 次降为 2 次，观察、历史、用例和边界
回归共 424 项通过；不将查询次数视为原生端到端耗时。`run-bh5xllxe` 已核验环境和定位，
尚未派发业务用例。

新版正式批次的 4 组测试数据配方均已登记。第一组原生准备 `passed` 已写入 PostgreSQL，
Temporal 工作流在归档回读后 `completed`；第二组已获授权并运行。尚无业务用例结果。
派发预约与原响应提交之间，通过禁止 PostgreSQL 和 MinIO 写入的独立生产观察读取，真实
返回 `running / outcome_unknown`，耗时 80.64 秒（`output/exweb-run-bh5xllxe-first-fixture-observation.log`）。
探针不调用 Runner；不把预约当成已知结果，也不把单次耗时当成端到端性能对照。

阶段清单改为消费同次历史读取已核验的类型化原执行输入，避免另读同一授权与配方。
独立账本读取和最后的历史／权限复核不变；原执行与取消各有负向重复读对照。
观察、历史、用例与边界回归共 426 项通过。运行中的正式批次不重启加载这项优化。
使用新读取路径，独立只读回查同一命令终态为 `completed / observed / passed`，耗时 69.83 秒
（`output/exweb-run-bh5xllxe-first-fixture-completed-observation.log`），未重发请求。
终态有原归档、前次只有派发预约，两次耗时不构成同状态性能对照。

同一条已完成的真实 setup、相同 `completed / observed / passed` 状态做了独立只读对照。
历史查询的类型化输入在核对当前权限、原命令摘要、状态和选择后交给账本读取，省掉一次
完整授权归档解析；账本仍独立读取，结束前仍重新核验历史与权限。两次耗时为
70.71 秒和 60.55 秒，移除的单次归档解析耗时 11.44 秒；后一次的账本读取仍约 35.85 秒。
对照不调用 Runner 或写入 PostgreSQL／MinIO，只是同一命令的单组样本，不是生产性能指标。
日志为 `output/exweb-run-bh5xllxe-completed-observation-profile-before.log` 与
`output/exweb-run-bh5xllxe-completed-observation-profile-after.log`；相关回归 431 项通过。
同命令细分测量为总计 57.63 秒，账本 33.64 秒。其中原计划和环境的三次读取分别为
10.97、10.85、11.19 秒，账本记录 SQL 0.58 秒，原结果归档读回在当前采样精度下不足
0.01 秒。日志 `output/exweb-run-bh5xllxe-completed-observation-journal-profile.log`；
这次只加探针，没有缩减权限、原计划或物理证据验证。

真实历史接口的 scoped PostgreSQL 只读复验仍在取消后审计快照比较失败（666.63 秒）。
根因是测试按 SQL 列名 `metadata` 读取 ORM 属性，取到了声明式 `MetaData`，不是数据库
里的 `event_metadata` JSON。独立 PostgreSQL 临时表复现了 `MetaData() != JSON`；修正为
按主键排序的 SQL 列映射后，确认相同审计行相等、修改 JSON 能被检测到，连同历史查询
快检 2 项通过（`output/exweb-fixture-audit-snapshot-fixed.log`）。没有忽略任何审计字段或
更改业务代码。完整 PostgreSQL／MinIO 复验单独运行，日志为
`output/exweb-fixture-composed-history-core-snapshot-pg-minio.log`。

`run-bh5xllxe` 的第二组原生准备也已写入 `passed`，两条原执行均为 `completed`；第三组
开始授权。两组准备不计作业务用例通过，最终仍以实际业务请求、清理和清理后历史回读为准。

只读单阶段账本现在先核验完整原计划和原环境，再读取账本和原响应，返回前重新核验
完整父链；空账本也执行末次核验。生产读取在查询账本和下载归档之前仍即时重查来源权限，
原项目角色前后分别核对。工作流内的检查和写入租约未改。新增空／预约／已观察三态
及查询中撤权负例；读回、交接、隔离与架构回归 410 项通过，实际 PostgreSQL 33 项通过
（`output/exweb-fixture-journal-read-boundary-pg.log`）。

原运行同一 `completed / observed / passed` setup 只读复测，原计划／环境核验从三次降为
两次（11.19、11.16 秒），账本 33.64 -> 23.10 秒，整次读回 57.63 -> 49.48 秒。
`output/exweb-run-bh5xllxe-completed-observation-journal-two-checks-profile.log` 保留分段数据；
无 Runner 请求或 PG／MinIO 写入。结果为同命令单样本对照，不是总体性能指标。

审计快照修正后的 PostgreSQL／MinIO 历史接口复验终态 `1 passed / 605.72 秒`，见
`output/exweb-fixture-composed-history-core-snapshot-pg-minio.log`。正常认证后的只读
事务覆盖分页、待确认和取消原命令、详情与观察；非授权成员返回 403。完整账本、审计和
Outbox 快照未变，Runner 未派发；Workflow 交付仍为该专项的显式替身，不能算正式批次证据。
正式 `run-bh5xllxe` 已归档三组原生准备，第四组授权已完成并存在派发预约，尚不计为
第四组已知结果，也没有正式业务用例通过结论。

`run-bh5xllxe` 的四组准备均已实际落库 `passed`，四个原命令与 Workflow 均已完成。正式
业务命令 `tool_aae0d56c57` 状态 `running`，Temporal `run_original_run_plan_cases` Activity
已启动，attempt 1。用只读 PostgreSQL 独立验证它选定的四个原 setup 均能由生产组合仓库
回读，空来源可见范围全部拒绝；见 `output/exweb-run-bh5xllxe-four-setup-roster.log`，
不派发目标请求。此时正式用例账本仍无结果，等待实际响应、清理和清理后历史回读。
隔离本机 `npm run test:smoke` 也通过，范围为项目创建、系统画像候选、Agent 查询和质量闭环
入口，不代替原生 exweb 业务执行。

正式业务 Activity 首次尝试先完成 8 次准备账本核验（每个原 setup 两次），然后在
派发前开始下一轮完整输入校验。到原命令确认后 535 秒，PostgreSQL 业务 work、claim
和 outcome 仍均为零。当前批次未加载以下改动，不重启、不延长确认窗口，不把输入核验当派发。

业务用例读取每条原 setup 时，现在只展开一次完整账本父链；核验原命令后，用新的
PostgreSQL 会话重新读取同一组 setup／cleanup 记录，并重新读回原响应字节作精确比较。
前后权限、父链及所有清理槽仍核验，晚到清理、记录／归档变化和撤权均拒绝。
原 exweb `tool_9dd123dcce` 在真实 PostgreSQL／MinIO 下按同一权限读回，旧路径 60.82 秒、
新路径 40.95 秒，完整交接证据摘要相同，两次均无目标请求或写入。日志
`output/exweb-run-bh5xllxe-case-handoff-legacy.log` 和 `output/exweb-run-bh5xllxe-case-handoff-stable.log`。
343 项回归和 35 项真实 PostgreSQL 专项通过（`output/exweb-case-handoff-stable-cohort-pg.log`）。
此对照是单个原 setup，不是整个 RunPlan 完成证明。

`run-bh5xllxe` 的原业务 Activity 首次尝试触发 Temporal `START_TO_CLOSE`（12 分钟）；
旧进程堆栈停在生产 `ConfiguredRunPlanCaseWorker` 的 Runner 装配阶段。该阶段仅检查本机
执行器，却在初次准备之后再次完整读取四组输入；当时没有原业务 work、claim 或 outcome。
Temporal 用同一命令安排第 2 次尝试。原确认后 926 秒复核三类账本仍均为零，确认时限没有
延长；该批仍待原工作流收尾和资源清理，不记作业务用例执行。

新版生产适配器把本次已完整核验的 `PreparedRunPlanCaseInputs` 交给 Worker 装配和工作
绑定，只实时复核原命令、当前权限和 PostgreSQL 所有权，不在初始化重复展开全部准备档案。
已绑定工作不授权派发；派发和提交仍要求完整重验，原租约和 Temporal 时限不变。新增受限
阶段计时区分准备、绑定、派发预约和提交。内层改动回归 453 项通过；包含最终生产 Runner
装配、撤权和边界的回归 234 项通过。隔离 PostgreSQL／MinIO 绑定专项单独运行，见
`output/exweb-case-prepared-binding-pg-minio.log`。正在运行的正式批次没有加载这些改动。

`run-bh5xllxe` 最终以 `1 failed / 4248.26 秒` 结束：四组原生准备完成，业务 Workflow
返回 `failed` 而非 `completed`，没有业务派发或可交付业务结果报告。测试末尾确认本批
自有目标资源清理，独立查询确认临时 PostgreSQL 数据库已删除。旧进程把确认过期归为
可重试基础设施错误；新版明确区分 `RunPlanCaseConsentExpired`，Temporal 只执行一次并
走原失败收尾，历史仍可读，900 秒授权窗不变。实际 Temporal 和相关回归 186 项通过。

绑定阶段的真实 PostgreSQL／MinIO 专项 `1 passed / 211.41 秒`（Runner 为协议替身）。
预约和结果事务仍持项目 mutation fence 进行完整证据核验，但先核验、再锁原命令／租约行；
续租在其独立事务校验原工作、命令、取消、actor 和 PG 时钟，不等项目证据锁。写入后仍
重查实时权限和租约。准备后的启动轮询、派发预约前、私有结果暂存只使用即时活性检查，
物理 Runner 与提交边界仍完整核验。相关回归 320 项通过；真实并发与晚撤权回滚专项
`1 passed / 273.52 秒`（`output/exweb-case-lease-concurrent-pg-minio.log`），确认预约与提交
核验暂停时仍可续租，写入后的撤权可回滚。固定 exweb、离线镜像与本地依赖的只读预检
再次通过，未启动新目标，仍需完整新批验证，不能把协议 Runner 结果当成 exweb 的业务通过。

同一次业务输入核验内，环境记录服务用 task／thread 所有的有界 read scope 复用一份已完整
验证的原 RunPlan／构建父链。各条原 fixture 仍独立读取授权、配方、环境登记和 MinIO 原始
环境字节、账本和响应；只复用完全相同的项目、记录及当前访问范围。退出前独立重读并比较
整份计划／构建／环境，随后再次核对 PG 确认窗口。失败时关闭 scope，不延用到其他任务、
线程或下一次执行边界。历史读取、晚到清理及审批状态校验规则不变。

撤权、损坏、来源父链变化、跨任务／线程及末次核验后授权到期回归 349 项通过。独立
PostgreSQL／MinIO 对照 `output/exweb-case-common-parent-fixed-source-pg-minio.log` 使用的是协议
源码夹具（`fixed_exweb_source=false`），没有执行目标。两条原授权和对应账本的读回结果相等，
公共父链 6→2 次、原环境归档仍各读 6 次，单次观测 38.93→13.70 秒。日志原样保留。
新入口 `test_fixed_exweb_case_shared_parent_reads_every_original_fixture_archive` 必须显式启用真实
离线构建，且在计时前核对私有 MinIO 原始 126 个文件；旧结果不作为固定 exweb 性能或业务通过证据。

业务预约后交给 Runner 前仅实时复查权限、取消、原命令和租约；生产 owned HTTP 仍在真实
子进程创建前和返回已复核目标身份的结果前完整重验。子进程退出时使用即时检查，事务预约和
结果提交保留独立完整核验。非默认传输保留原完整检查，原确认窗口、租约、断言和清理要求不变。
新增派发和结果两个独立阶段计时，真实子进程负例及相关回归 481 项通过。

正式新批次 `output/exweb-canonical-runs/run-8s5yoeki/pytest.log` 已使用固定 126 文件与原镜像
启动，独立 PostgreSQL 历史查询预检通过。其终态与 `verification.json` 另行核对，不能以启动或
预检代替业务派发、清理或可交付演示结果。

后续将定位档案纳入同一业务输入的有界父链核验。仅在完全相同项目、计划、工件摘要和访问范围内
借用已验证的计划；定位记录、定位归档和原始源码核验独立执行，结束时仍独立重读完整父链并核对
PG 确认窗口。公开的定位历史路径不变。篡改、撤权、跨线程与跨任务等 351 项回归通过；正在运行
的 `run-8s5yoeki` 未加载此改动，不以该批结果证明定位复用。

固定 exweb 的专项 `output/exweb-case-locator-parents-actual-pg-minio.log` 已独立退出 0，
`1 passed in 980.91s`。在真实 PostgreSQL／私有 MinIO 核对固定提交的 126 个归档文件，并比较
同一定位记录、两条原授权及对应账本父链；两条路径完整返回值一致。单次测量 86.44→23.57 秒，
公共父链读取 6→2 次，定位独立计划读取 2→0 次；环境归档仍各读 6 次、定位归档仍各读 1 次。
专项未向目标发请求，不代表整轮耗时、p95、业务验收或发布结论。

`run-8s5yoeki` 已完成四条原生 setup Workflow 并进入业务执行。首个业务用例通过准备、派发及
结果核验，结果事务已提交（隔离 PG 只读查询确认 `failed=1`，并非未执行或基础设施超时）。
同批诊断：输入准备 70.70 秒，首条派发预约 70.38 秒，派发前复核 70.85 秒，结果后置复核
66.24 秒，结果提交 73.24 秒。该阶段观察只证明首条结果已入库，不代替完整业务回执、清理
或清理后的历史回读；执行所用测试预期仍不是独立业务标准。

`run-8s5yoeki` 最终 `1 failed, 1 passed / 3976.43 秒`。四组原生 setup 完成，两个业务结果
已提交，第三个业务用例留下原派发预约，真实 Runner 子进程结束，但后置复核报
`RunPlanCaseWorkLost` 且 Activity 取消，未观察到第三条业务结果提交。正式 Workflow 返回
`failed`，未产生 `verification.json`；没有重发不确定请求。测试末尾确认本批自有目标清理，
另用 Docker 和 PostgreSQL 分别复核本批容器及临时数据库不存在；这不等于四条 canonical
cleanup Workflow 完成，也不是发布证据。

最新 Worker 的 v3 业务结果先进入私有暂存：Runner 仍核验原派发、实际请求/响应、目标环境及
实时权限，结果只有在账本事务独立重验来源和归档后才可见。撤权或归档损坏不提交观察，原派发
保留为不确定，不补发。协议 Runner 配合真实 PostgreSQL／MinIO 专项通过
（`output/exweb-case-private-staging-pg-minio.log`，218.35 秒），未向 exweb 发送请求。

任务收尾使用同一原工作范围内的 Worker 回执，不在应用层重复多次完整历史读取；事务仍核对
原命令、账本和结果摘要，并在状态、审计、Outbox 提交前独立读回原输入和私有结果档案、实时
复查权限。不改变公开历史的前后两次完整输入核验，不改变授权窗口、业务范围或结果标准。
收尾、交接、读取和边界回归 226 项通过，新增同范围及错误范围两个用例另行通过。
上述私有暂存、收尾及定位父链复用不在 `run-8s5yoeki` 的已加载版本内，需完整复验。

真实 PostgreSQL／私有 MinIO 收尾回归 `1 passed / 298.19 秒`（协议 Runner，
`output/exweb-case-finalization-pg-minio.log`）：收尾事务内的档案核验失败时，原状态、revision、
审计和 Outbox 全部不变；核验通过后只追加一次终态，同命令重入不再读取归档。原始 HTTP 归档
回放和正式报告校验 59 项通过。收尾与事务内档案核验增加有界耗时诊断，不记录请求或归档正文。

已用最新代码启动固定 exweb 完整批次 `run-96tivyqo`，日志在对应 `pytest.log`。前置独立 PG
历史和权限用例通过；业务执行、四组清理、资源清除后原始历史回读和最终 `verification.json`
仍待核验。本轮不缩减业务范围、不延长授权或 Temporal 期限，不以协议专项结果替代正式批次。

只读摘要校验按原 Runner 断言状态区分失败、中断和未执行。用例通过时所有断言必须通过；
失败用例须有原始 HTTP 响应和唯一失败断言。重复断言 ID、未知 HTTP 方法、重复 JSON 字段
及非有限常量拒绝生成报告。101 项校验／归档回放回归通过；用真实独立 Docker 报告生成的
新摘要与旧摘要字节一致。此项只更改报告读取，不改变正在运行的批次、原始输出或发布权限。

`run-96tivyqo` 的第一组原生 setup 已实际归档 `passed`，原命令与 Temporal Workflow 均完成。
独立 PostgreSQL 只读检查确认结果来自该批原派发；它不计为业务用例。当前工作树另通过迁移
0123 后的 `npm run test:smoke`（`output/exweb-current-worktree-smoke-0123.log`），范围是项目、
画像候选、Agent 查询和质量闭环入口，未向 exweb 派发请求。

`run-96tivyqo` 的前三组原生 setup 均已在隔离 PostgreSQL 归档为 `passed`，原 Temporal
Workflow 均已完成。第三组原 Runner 子进程、结果后置复核、账本事务和 Worker 提交均有独立
计时。此检查点业务派发预约及业务结果仍为 0，不表示四组准备、业务、清理或历史回读已通过。

首次 `npm run verify:v1-release` 的后端阶段暴露工具目录扩充后的压缩排序回归。修复保留
6,999 字节、全部 canonical ID 和原始顺序，先为相关工具保留完整治理契约，再压缩展示文案。
在隔离 PostgreSQL／MinIO 的目录、Planner、公开 API 和 DDD 边界复验 289 项通过
（`output/exweb-v1-planner-catalog-recheck-final.log`）。原全量门禁仍使用修复前已加载
的代码，不以专项通过替代最新工作树的全量验收。

`run-96tivyqo` 四组原生 setup 的原 Workflow 均完成。隔离 PostgreSQL 确认四条业务预约
各有一条原结果，均为 `failed`，说明真实目标响应未满足本轮受控断言，不是执行基础设施
未派发。第三、第四条均完成私有暂存及结果事务；本检查点未确认业务 Workflow 和四组清理
全部完成，也未产出清理后的正式报告。

独立 V1 检查中，真实 Codebase Memory 契约、Compose 拓扑和隔离备份恢复均通过。更新后的
`verify-docker-stack.sh` 完整通过（`output/exweb-v1-durable-runtime-governance.log`）：
在真实 PG／MinIO／Temporal 上恢复 Worker，固定三源生成候选但不发布；显式构建新版本 US
上下文后执行真实 Runner，通过模型协议夹具的 chat／embedding／rerank 三路各七次。由于
缺独立质量评估和资产审阅，审批只允许提交 blocked 决策，晋级请求失败且原基线不变。
API 重启后回读候选、任务、决策和执行证据；独立 Compose 容器、卷和网络已清理。该运行栈
使用协议模型和自有 Runner 目标夹具，不是 exweb 业务执行，也不代替完整 `verify:v1-release`。

首条原生 cleanup 在 `run-96tivyqo` 中已实际归档 `passed`，原命令完成。该条 Runner
子进程用时 28.75 秒，归档历史回读用时 92.93 秒。后续将清理历史的 setup 和全部原 cleanup
槽位放在同一次只读父链校验内，末次使用新事务比较每条原账本和归档；授权、派发及实时围栏
不变。隔离 PostgreSQL 夹具的原父计划读取 6→2，setup 归档仍回读两次。真实私有 MinIO
对照验证新旧路径逐字节相等，篡改归档和晚到结果仍拒绝，156 项回归通过
（`output/exweb-cleanup-cohort-pg-minio-verified.log`）。这不是原生 exweb 耗时复验；
运行中的批次未加载此改动。

独立公开接口专项通过（`output/exweb-canonical-cleanup-archive-recheck.log`）：真实 PostgreSQL
和私有 MinIO 回读原清理命令，公开接口返回 `observed / passed`；原 setup 断言失败仍保留，
清理仍只使用该次 setup 捕获的会话标识。专项使用 Temporal 和目标传输替身，不计入
exweb 的四组原生清理或清理后的历史回读。

旧版独立浏览器全量回归结束为 266 通过、6 失败、5 跳过。修复后的当前批次已通过上述
6 项（Build 原 Goal 到结构候选、5 项代码差异的精确比较与权限回归）；见
`output/exweb-v1-portal-e2e-current-0123.log`。该批最终 272 通过、1 失败、5 跳过。新增失败
发生在项目撤权的浏览器用例：服务端证据请求和并行引用请求均返回 403，界面已隐藏内容；
测试读取原证据请求状态早于拦截回调结束。修复仅等待该 403，仍检查全部内容隐藏；来源和
项目撤权各五轮无重试通过（`output/exweb-v1-image-revocation-race-recheck.log`）。
修复后的独立 `npm run test:e2e` 已退出 0：**273 通过、5 跳过、0 失败 / 40.3 分钟**
（`output/exweb-v1-portal-e2e-after-revocation-fix.log`）。原项目撤权用例在全量批次通过。
5 项固定 exweb 用例需显式启用，已分别通过固定源码检查、三条 Build 导入和来源刷新专项
（`output/exweb-first-use-current-analysis-browser.log`、`output/exweb-first-use-current-build-browser.log`、
`output/exweb-first-use-current-refresh-browser.log`）。不把不同批次合计为一次零跳过全量，
也不以浏览器回归替代完整 V1 门禁。

`run-96tivyqo` 已正式结束：pytest **2 passed / 6971.73 秒**，原启动命令退出 0。
原 v1 `verification.json` 确认 4 条业务观察、4 组准备、4 组清理、12 次原生 Runner 调用、
9 个 Workflow，以及自有资源移除后的业务历史复核。4 条业务用例保留为 `failed`；
它们没有获得独立业务验收，且报告没有授权发布。

同目录 `fixture-cleanup-ledger-readonly.json` 与 `external-post-teardown-archive-witness.json`
的计划、工件摘要、四个用例状态与回执摘要完全相等。后者从 PostgreSQL／私有 MinIO 核验
原 4 组准备和 4 组清理的完整归档字节，读前读后均确认原目标资源已移除；这是独立回读，
没有改写原 v1 或冒称正式 v2 清理 API 历史。脱敏演示摘要为 `output/exweb-first-use-verified.md`。
完整当前 V1 门禁另行运行，不用这次目标验证替代。

完整门禁的第二个后端分片记录了两条文档成员范围用例失败：旧测试替身未接收
`copy_payload`，因此在验证父文档是否属于同一冻结画像前抛出 `TypeError`。修复只对齐
测试替身签名，未改生产逻辑、授权或断言。隔离 PostgreSQL／私有 MinIO 复验
**27 passed / 77.16 秒**（`output/exweb-v1-document-query-signature-recheck.log`），
包含原两个场景、文档 API、别名及冻结读取对照。旧分片继续检查其他回归后主动中断，原门禁
退出 1，保留两个原始失败和中断记录（`output/exweb-v1-release-current-sharded-0123.log`）。
修复后的完整门禁已启动（`output/exweb-v1-release-current-corrected-four-shards-0123.log`），
使用四个独立 PostgreSQL／MinIO 分片。与旧批次逐项核对，收集到的 9,082 个测试 ID 完全一致；
尚未获得终态，专项与独立浏览器结果都不能替代完整门禁。
