# 原目标的有界隔离对照探针

更新：2026-10-11。推进 P5/P6 的实际隔离验证，不把 Docker `internal` 配置当作物理拒绝证据，也不把三项有界观察替代完整隔离准入。该能力当前是显式 exweb 开发验证，不是 production 部署、canonical 执行授权或可导入的证明。

## 实现与对照

`scripts/verify-exweb-runtime.py --execute-reviewed-target --isolation-canaries` 在实际 exweb 启动并健康后，使用 `scripts/exweb_isolation_probe.py` 执行比较。没有执行 opt-in 则不创建任何目标或 canary；默认未启用这一附加检查。固定源码、离线 Maven、不可变镜像、原 JAR 与环境核验沿用[真实运行契约](./exweb-native-runtime-validation.md)。

每批新建两个非 root、只读根、cap-drop/no-new-privileges、受资源限制的 canary 容器及一个带独立名称和 owner 标签的 bridge。canary 不加入原目标内部网络，也不发布宿主端口；只访问本批 Docker 分配的精确私有 IPv4，不访问互联网、开发服务或真实开发文件。使用同一固定 Java 镜像的本地 `IsolationCanary.java` 启动 HTTP 服务，每次响应新的 64 字节随机 marker，固定保存源码摘要。

1. **网络对照**：对照容器先 GET canary 的唯一固定端点，得到确切 marker；原目标以实际 65534:65534 身份访问同一 numeric endpoint；随后对照再次成功。只有目标 curl 7/28 且无响应字节才记录 `outside_network_canary_denied=true`。DNS、程序缺失、HTTP 错误、部分响应或任一正向对照失败不能算拒绝成功。
2. **宿主文件对照**：本批临时目录创建非敏感 marker 文件，仅只读挂载到对照容器。两次对照 `cat` 必须返回原 marker；原目标只检查对应路径是否存在，绝不读取意外出现文件的正文。确切 absent sentinel 才记录 `unmounted_host_canary_absent=true`。
3. **Docker socket 可见性**：原目标检查固定 `/var/run/docker.sock` 是否存在，不连接或挂载真实 socket。确切 absent sentinel 才记录 `docker_socket_absent=true`，不声称有 socket 的正向对照或所有宿主访问被拒绝。

探针前后由生产 `OwnedTargetEnvironmentInspector` 核验原目标、三实例、内部网络和实际 JAR。canary 的 container/image/StartedAt/地址/完整网络成员及源码摘要也保持不变；改变则拒绝整份比较。所有七份原响应保留 return code、完整 base64、byte count 和 SHA-256，不只保存合成布尔值。

## 生命周期与权威

创建资源前登记清理 intent，客户端超时也不会遗忘可能存在的资源。退出时先清理全部本批容器，再清理额外 bridge 和原目标网络；只有确切 owned 名称的 authoritative not-found 才证明删除，daemon 故障不能冒充清理成功。不删除其他批或开发资源，临时宿主 marker 随原目录清理。canary 日志不混入 PG/Redis 日志槽位。

这证明的是三个确切有界比较，不是全部 IPv4/IPv6、UDP、DNS、代理、metadata、Docker Desktop 宿主接口或任意宿主文件的拒绝。报告明确 `universal_external_egress_denial_verified=false / universal_host_access_denial_verified=false / nasus_runplan_verified=false / execution_authorized=false / release_authorized=false`。旧 0105/0106 工件、原 false 权威及确认保持不变，不能把另一批 canary JSON 与 canonical 记录拼成同一次执行事实。

生产多协议出口政策和物理拒绝、宿主接口/跨项目安全、持久隔离观察及独立执行消费、fixture/setup/cleanup、owner/lease/取消恢复、逐用例真实覆盖、正式发布与完整 P0-P6 继续交付。

## 实际证据

- 配置了 disposable PG 的协议/原探针/边界批 `output/exweb-isolation-canary-contracts-configured-20261011.log`：**69 passed / 0.34 秒**。包含正向对照失败、对照晚期失联/重启、原目标重启、错响应/原字节/源码变化、未授权地址/容器、部分响应、资源创建超时及 cleanup 故障。这些是 protocol specimens，不是实际 Docker 证明。第一次未配置 `NASUS_TEST_DATABASE_URL` 的启动拒绝保留在独立日志，没有进入测试。
- `output/exweb-native-isolation-canaries-20261011.json/log` 为实际固定 exweb commit `fe5827f6b76f77ef34918d8b452ee823142332dc` 的全部 **126 个 Git blob**、实际离线 Maven/Java 21、独立 PG/Redis/Docker。原 JAR `sha256:0541660ded51b8d1b9cc60fda708e5abf5d1c711871c53c35124cbd80f9f4cea`，canary 源码 `sha256:0b04ae0693cf5a2ba52a50138e46898d6b2ca957fdeba2210273c90536bf64d6`。
- 实际三项 canary 均 true；网络正向前后响应为相同 64 字节，目标 curl **7 / 0 字节**。宿主文件对照前后相同 64 字节，目标 absent 响应 20 字节，socket absent 27 字节。另一次独立只读检查重新计算全部七份响应 hash，核对原 JAR、环境摘要与 cleanup；全部通过。
- **整批仍 failed / 退出 1：12/17 项通过、5 项失败**。失败是 exweb 跨用户/租户及关闭后读取的错误状态、会话未进入 PG、重启后丢失；没有启用本批 `--http-runner`，不能用旧 19 项批的六项失败替代。开发 oracle 不是维护者批准规范，未改第三方源码或降低断言。
- cleanup verified=true、remaining_owned_resources=[]，实际本批 owner 容器列表为空。`py_compile`、release hygiene 和 `git diff --check` 通过；前端代码未变动，没有用本批协议测试声称 UI 或完整 V1 全绿。

另一个 canonical 原生 exweb 的 0106 健康归档专项已 **1 passed / 4017.41 秒**，见[健康契约](./native-target-health.md)与实施记录。它的 JAR 为另一份原工件，不包含本批 canary；两个结果不能混同，也没有构建可重现性证据。
