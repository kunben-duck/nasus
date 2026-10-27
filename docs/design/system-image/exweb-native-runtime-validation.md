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
