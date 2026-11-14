# Podman 本地开发启动指南

本文是 [现有开发启动方式](../../../README.md) 的 Podman 替代操作说明：**PostgreSQL、MinIO、Temporal 运行在 Podman 中；Portal、API、Runner 和 Workflow Worker 运行在本机。** 不需要启动 Docker Desktop，也不将应用改成容器运行。

> 验证状态：命令与当前仓库配置进行了静态核对，但编写环境未安装 Podman，尚未完成 Podman 实机启动验收。本文不代表整个 Nasus 执行链已经兼容 Podman。

## 1. 适用范围与现有脚本限制

- 以 macOS 为主，补充 Linux rootless 用法；所有命令使用 Bash，Windows 原生 PowerShell 不在本文范围内。
- 复用根目录 `docker-compose.yml`，只启动 `postgres`、`minio`、`minio-init`、`temporal`、`temporal-ui`。基础开发启动不需要 Redis。
- 本文固定 Compose 项目名为 `nasus-podman`，后续检查、停止、重启必须使用同一名称。
- **不要使用 `npm run dev:up`、`npm run dev:foreground`、`npm run dev:down -- --infra` 启动或管理本指南的环境**：这些脚本仍写死了 `docker compose`。不要用 `alias docker=podman` 掩盖差异，非交互脚本也不保证读取该别名。
- 手动启动不创建 `.nasus/dev/pids/` 中的监督进程记录。`dev:status` 的 `stopped` 不代表手动进程未启动，`dev:down` 也不会管理这些手动进程；应按本文的健康检查和 Ctrl+C 停止流程操作。
- RealWorld 受控目标构建/执行、`verify:docker-stack`、`verify:production-compose`、`verify:v1-release` 以及现有备份/恢复脚本仍有 Docker 依赖，不因开发基础设施可以启动就视为通过 Podman 验收。

## 2. 准备工具和依赖

### 2.1 Podman 与 Compose provider

macOS 推荐从 [Podman 官方安装说明](https://podman.io/docs/installation) 使用安装包安装 Podman。macOS 容器运行在 Podman machine 虚拟机中；先查看是否已经存在 machine：

```bash
podman machine list
```

仅首次使用且没有现成 machine 时初始化；已有 machine 时跳过 `init`。启动已选择的 machine，已经运行时不必再次启动：

```bash
podman machine init
podman machine start
podman info
```

多个 machine 时，为 `start` 指定 `machine list` 中的名称，并用 `podman system connection list` 核对当前连接；不要为了重试删除或重置 machine。

`podman compose` 本身只是外部 provider 的入口，默认还可能优先选择 `docker-compose`。本文显式使用 `podman-compose`，详见 [Podman Compose 官方说明](https://docs.podman.io/en/latest/markdown/podman-compose.1.html)。macOS 已安装 Homebrew 时可安装 provider：

```bash
brew install podman-compose
```

Linux 不需要 machine，使用发行版提供的 Podman 和 provider。例如 Debian/Ubuntu：

```bash
sudo apt-get update
sudo apt-get install podman podman-compose
```

Fedora 使用 `sudo dnf install podman podman-compose`。其他安装方式见 [podman-compose 安装说明](https://github.com/containers/podman-compose#installation)。容器管理统一使用普通用户执行，不要混用 `sudo podman` 和 rootless Podman，否则会看到不同的容器与数据卷。

检查工具并选择 provider；**后续每个管理基础设施的新终端都需要重新设置这个环境变量**：

```bash
command -v podman
command -v podman-compose
export PODMAN_COMPOSE_PROVIDER="$(command -v podman-compose)"
podman --version
podman compose version
podman info
```

任一工具缺失或 `podman info` 失败，先修复安装、PATH 或 machine 连接，不继续启动。记录实际 Podman/provider 版本，尤其不要将较旧发行版 provider 的行为视为已验证兼容。

### 2.2 本机开发依赖

安装 Python 3.12、Node.js 22 的当前维护版本（至少 22.12）、npm、Git、curl 和 Bash。进入本机 **Nasus 仓库根目录** 后打开 Bash；本文其余步骤都从该目录执行：

```bash
bash
pwd
python3.12 --version
node --version
npm --version
```

首次创建虚拟环境并安装锁定的前端/Runner 依赖：

```bash
if [[ ! -d .venv ]]; then
  python3.12 -m venv .venv
fi
./.venv/bin/python --version
./.venv/bin/python -m pip install -r apps/api/requirements.txt
npm ci
npm --prefix apps/portal ci
npm --prefix apps/runner ci
./apps/runner/node_modules/.bin/playwright install chromium
```

如果已有 `.venv` 不是 Python 3.12，先安排虚拟环境迁移，不直接覆盖正在使用的环境。Linux 上 Chromium 缺少系统库时，按 Playwright 提示安装依赖，可使用 `./apps/runner/node_modules/.bin/playwright install --with-deps chromium`；该命令可能请求系统包安装权限。Runner 的 `/readyz` 会检查浏览器，不能仅安装根目录 E2E 使用的另一版本 Chromium。

### 2.3 配置 `.env`

只在不存在时复制模板，避免覆盖已有模型密钥和数据库配置：

```bash
if [[ ! -e .env ]]; then
  cp .env.example .env
  chmod 600 .env
else
  printf '%s\n' 'Keep existing .env; review its values before continuing.'
fi
```

编辑 `.env` 时重点核对以下内容。文件会被 shell `source`，只加载自己维护的可信配置；含特殊字符的值应正确引用，真实密钥不得提交到 Git。

| 配置 | 本机开发要求 |
| --- | --- |
| PostgreSQL | `POSTGRES_*` 与 `NASUS_DATABASE_URL` 中的账号、密码、端口、数据库一致；URL 主机使用 `127.0.0.1`，不是容器内的 `postgres`。密码含 URL 特殊字符时需编码 URL 中的密码。 |
| MinIO | `MINIO_ROOT_*` 与 `NASUS_S3_ACCESS_KEY`、`NASUS_S3_SECRET_KEY` 一致；`NASUS_S3_ENDPOINT` 使用 `http://127.0.0.1:9000` 或修改后的宿主机端口。 |
| Temporal | `NASUS_TEMPORAL_ADDRESS=127.0.0.1:7233`，`NASUS_TEMPORAL_NAMESPACE=default`。改动 `TEMPORAL_PORT` 时必须同步修改地址。 |
| 模型 | 填写真实 chat/embedding/rerank 配置，或启动后按产品支持的流程配置模型；模板中的示例地址和占位密钥不可用于真实任务。显式 mock/fallback 仅能验证基础启动，不能作为 live Agent 验收。 |
| 共享密钥 | 首次初始化时为 `NASUS_SETTINGS_ENCRYPTION_SECRET` 和 `NASUS_RUNNER_SERVICE_TOKEN` 设置独立随机值；API 与 Worker 必须共享设置密钥，API 与 Runner 必须共享服务 token。保留已有环境的值，不随重启更换。 |
| 登录 | 保留 `NASUS_AUTH_MODE=required` 时，填写有效的 `NASUS_AUTH_BEARER_TOKEN`。使用页面注册/登录会话时清空 `VITE_NASUS_API_TOKEN`，避免模板占位值优先覆盖用户登录 token；显式测试静态 bearer 模式时两端 token 必须匹配。 |
| 运行时 | 保持 `NASUS_ENV=local`。共享开发环境脚本会选择 Temporal、LangGraph、PostgreSQL checkpoint 和 HTTP Runner，不要配置 `NASUS_DEV_*` 为 local/mock 来绕过依赖失败。 |

生成新的本地随机密钥可使用 `openssl rand -hex 32`，每个用途单独生成。修改 `.env` 后必须重启所有相关应用进程；同一个值不会自动同步到已运行的进程。

推荐首次使用默认端口：PostgreSQL `5432`、MinIO `9000/9001`、Temporal `7233/8088`、Runner `8090`、API `8000`、Portal `5173`。如果其他 Docker/本机服务已占用这些端口，先确认归属，再正常停止旧服务，或者同时调整映射及客户端地址。**不能让旧 Docker 数据库在原端口继续运行，却误以为应用已经连接到新 Podman 数据库。**

Docker 与 Podman 的数据卷不共享；本文默认创建独立开发环境，不导入旧账号、模型配置和业务数据。需要保留原环境时先另行制定并验证数据库及对象存储迁移方案，不复制底层数据库卷目录，也不直接运行 Docker 专用恢复脚本。

## 3. 启动并检查基础设施

在仓库根目录的管理终端加载环境，定义一个仅在当前 shell 生效的便捷函数。它不修改仓库脚本：

```bash
source .venv/bin/activate
source scripts/dev-runtime-env.sh
export PODMAN_COMPOSE_PROVIDER="$(command -v podman-compose)"

nasus_infra() {
  podman compose -p nasus-podman \
    -f "$NASUS_DEV_ROOT/docker-compose.yml" \
    --profile app --profile temporal "$@"
}
```

每次重新打开管理终端都要执行上面这段初始化。各应用终端的初始化见下一节。

先解析配置，再仅启动指定的基础设施服务：

```bash
nasus_infra config >/dev/null
nasus_infra up -d postgres minio minio-init temporal temporal-ui
nasus_infra ps -a
```

`config` 可能展开敏感配置，不要把完整输出粘贴到工单或提交到仓库。配置校验需要同时启用 `app` 和 `temporal` profile，才能解析其中 Worker 对应用服务的依赖；实际 `up` 通过显式列表只启动基础设施及其依赖。**不要省略 `up` 后的服务列表**，否则可能启动容器版应用。

镜像短名称提示、SELinux 挂载错误或依赖条件不被 provider 支持时，按第 6 节排查。`up -d` 返回不代表初始化已完成；以下检查全部成功后再执行迁移。

### PostgreSQL 与 MinIO

```bash
nasus_infra exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"
nasus_infra logs minio-init
curl --fail --silent --show-error "${NASUS_S3_ENDPOINT}/minio/health/ready"
nasus_infra run --rm --no-deps --entrypoint /bin/sh minio-init -ec '
  mc alias set nasus http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  mc stat "nasus/$NASUS_S3_BUCKET"
  mc version info "nasus/$NASUS_S3_BUCKET"
'
```

确认 PostgreSQL 显示 accepting connections，`minio-init` 正常退出且日志没有错误，bucket 可访问，版本控制为 enabled。最后一个命令使用临时 `mc` 容器只检查 bucket，不删除对象；它的成功不能代替核对初始化任务结果。

### Temporal namespace

下面的检查只读查询 `default`（或显式配置的 namespace），最多等待 120 秒，不创建业务 workflow：

```bash
./.venv/bin/python - <<'PY'
import asyncio
import os

from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client


async def check():
    namespace = os.environ["NASUS_TEMPORAL_NAMESPACE"]
    while True:
        try:
            client = await Client.connect(os.environ["NASUS_TEMPORAL_ADDRESS"])
            result = await client.service_client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=namespace)
            )
            if result.namespace_info.name != namespace:
                raise RuntimeError("Unexpected Temporal namespace")
            print(f"Temporal namespace ready: {namespace}")
            return
        except Exception as exc:
            print(f"Waiting for Temporal: {type(exc).__name__}")
            await asyncio.sleep(1)


async def main():
    await asyncio.wait_for(check(), timeout=120)


asyncio.run(main())
PY
```

超时应检查 `nasus_infra logs temporal postgres`；不要通过关闭 Temporal 或使用本地内存 runtime 规避错误。

### 数据库迁移

只在确认连接的是目标 Podman 数据库后执行：

```bash
./.venv/bin/alembic -c apps/api/alembic.ini upgrade head
./.venv/bin/alembic -c apps/api/alembic.ini current
./.venv/bin/alembic -c apps/api/alembic.ini heads
```

当前 revision 集合必须与代码中的 heads 一致。迁移失败就停止后续启动；不要使用 `create_all`、SQLite 或手工改版本号绕过失败。

## 4. 分别启动本机应用

按下面的顺序打开 **四个终端**，每个终端都进入同一个 Nasus 仓库根目录并使用 Bash。激活虚拟环境使 `.env` 中的 `codebase-memory-mcp` 能从 `.venv/bin` 找到；加载共享环境确保模型加密密钥、任务队列和运行模式一致。

### 终端 A：Runner

```bash
source .venv/bin/activate
source scripts/dev-runtime-env.sh
NASUS_RUNNER_HOST=127.0.0.1 npm --prefix apps/runner start
```

在管理终端检查 `curl --fail --silent --show-error "${NASUS_RUNNER_ENDPOINT}/readyz"` 返回 HTTP 200 且浏览器就绪，再继续。

### 终端 B：Workflow Worker

```bash
source .venv/bin/activate
source scripts/dev-runtime-env.sh
./.venv/bin/python -m apps.api.app.infrastructure.workflow.agent_goal_workflow_worker
```

保持终端开启，确认没有连接、迁移或解密错误。该进程承接对话及相关长任务；只启动 API 而没有 Worker，会导致已接受的任务一直等待执行。

### 终端 C：API

```bash
source .venv/bin/activate
source scripts/dev-runtime-env.sh
./.venv/bin/python -m uvicorn apps.api.app.main:app \
  --app-dir . --host 127.0.0.1 --port "$NASUS_API_PORT" --reload
```

### 终端 D：Portal

```bash
source .venv/bin/activate
source scripts/dev-runtime-env.sh
NASUS_PORTAL_API_PROXY="http://127.0.0.1:${NASUS_API_PORT}" \
  npm --prefix apps/portal run dev -- \
  --host 127.0.0.1 --port "$NASUS_PORTAL_PORT" --strictPort
```

显式设置 API proxy 避免改动 API 端口后仍指向默认 `8000`；`--strictPort` 避免端口冲突时 Vite 静默换端口。更改 Portal 端口时，同步更新 `.env` 的 `NASUS_CORS_ALLOW_ORIGINS`。

本方式应用日志直接显示在四个终端，不自动写入 `.nasus/dev/logs/`；该目录中的旧日志不代表当前手动进程状态。仅绑定本机回环地址；Compose 基础设施端口仍按原配置发布，应在可信开发机器上使用，不暴露到公网。

## 5. 就绪验证、停止与再次启动

在管理终端执行，遇到非 200 或连接失败时查看对应终端日志：

```bash
curl --fail --silent --show-error "http://127.0.0.1:${NASUS_API_PORT}/readyz"
curl --fail --silent --show-error "${NASUS_RUNNER_ENDPOINT}/readyz"
curl --fail --silent --show-error --output /dev/null \
  --write-out 'Portal HTTP %{http_code}\n' "http://127.0.0.1:${NASUS_PORTAL_PORT}/build"
curl --fail --silent --show-error --output /dev/null \
  --write-out 'Temporal UI HTTP %{http_code}\n' "http://127.0.0.1:${TEMPORAL_UI_PORT}"
nasus_infra ps -a
```

API 的 `/readyz` 应返回 200，并检查响应中的 database、object_storage、automation_runner、agent_workflow 和 agent_checkpoint 等状态；模型处于 fallback 不等于真实模型任务可用。Worker 没有独立 HTTP 健康端点，还应在 Temporal UI 检查配置的 namespace 和任务队列是否有 Worker poller，不能只看 API 已连接 Temporal 就推断 Worker 正常。

默认入口：

| 服务 | 地址 |
| --- | --- |
| Portal | <http://localhost:5173/build>，未登录时按页面引导注册/登录 |
| API 就绪 | <http://localhost:8000/readyz> |
| Runner 就绪 | <http://localhost:8090/readyz> |
| MinIO Console | <http://localhost:9001>，使用 `.env` 配置的 MinIO 账号 |
| Temporal UI | <http://localhost:8088> |

首次环境默认不灌入演示业务数据，没有项目不是启动失败。需要测试真实 Agent 时，另行配置并验证 live 模型，然后通过页面发起一轮明确的测试对话，核对 Worker 执行和前端回复；基础健康检查不是完整业务闭环验收。

**停止应用**：先停止新任务提交；在 Portal、API、Worker、Runner 对应终端依次 Ctrl+C，等待进程退出。运行中的任务有实际副作用，停止前确认其状态，不用系统级批量 kill 命令。只停止应用时，基础设施可继续运行。

**停止基础设施且保留数据**：

```bash
nasus_infra stop temporal-ui temporal minio postgres
```

`minio-init` 正常情况下已经退出；如果初始化仍在运行，应先排查并显式停止该任务。macOS 仅在确定该 machine 内没有其他需要运行的容器时，才执行 `podman machine stop`（多 machine 时指定名称）。停止不删除数据卷。

**再次启动**：macOS 先启动原 machine；管理终端重新加载第 3 节环境和函数，执行相同 `nasus_infra up -d ...`，重做基础设施检查和数据库迁移，再启动四个应用终端。同一 Podman 用户、machine 和 Compose 项目名会继续使用原有卷。不要重复创建 `.env`、换加密密钥、执行删卷或 machine reset 来解决普通启动失败。

## 6. 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| provider 缺失或意外运行 docker-compose | 检查 `command -v podman-compose` 和 `PODMAN_COMPOSE_PROVIDER`；在当前管理终端重新显式设置，不能只在另一终端设置。 |
| 短镜像名无法解析或要求选择 registry | 原 Compose 使用短名称。先在可信交互终端拉取并确认使用 Docker Hub（`docker.io`），不要选择不明镜像源；无人值守环境使用下面的本地覆盖示例固定完整镜像名。 |
| `condition`、profile、`run --no-deps` 或配置解析不被支持 | 先确认使用了本文完整的两个 profile 和显式服务列表；记录 Podman/provider 版本，升级到支持这些能力的稳定版本后重新检查，不要删除依赖条件或省略服务列表来绕过。 |
| Temporal 无法解析 postgres，MinIO 初始化无法解析 minio | 检查 `nasus_infra logs temporal minio-init` 和 Podman 网络 DNS；Linux provider 依赖可用的容器 DNS，如 netavark/aardvark-dns，不能用宿主机 `localhost` 替代容器间服务名。 |
| PostgreSQL 初始化挂载 Permission denied | 核对仓库目录是否可读；macOS 检查 machine 是否共享该目录，必要时将仓库置于受支持的共享目录；Linux SELinux 参考下面的私有重标记覆盖示例。不要使用 `chmod -R 777` 或关闭 SELinux。 |
| 端口已占用、错误连接到旧数据库 | 检查 Podman 的 `ps`、原 Docker 环境和本机监听端口；只停止确认属于旧 Nasus 的服务。修改端口后同步数据库 URL、S3 endpoint、Temporal 地址、Runner endpoint、Portal proxy/CORS。 |
| MinIO ready 但对象存储不可用 | 检查 bucket、版本控制、初始化任务，以及 `NASUS_S3_*` 与容器账号是否一致；HTTP 就绪不证明应用有 bucket 权限。 |
| Runner `/readyz` 返回 503 | 使用 `apps/runner/node_modules/.bin/playwright` 安装匹配的 Chromium；Linux 核对浏览器系统依赖和当前用户的浏览器缓存。 |
| 对话 accepted 后没有回复 | 检查 Worker 终端，API 与 Worker 是否读取同一 `.env`、Temporal namespace、任务队列和设置加密密钥；检查 live 模型连通性，不只检查 Portal 页面。 |
| 登录后仍 401 | 检查 `VITE_NASUS_API_TOKEN` 是否仍为模板值或旧静态 token；页面登录模式应留空并重启 Portal，静态 token 模式则应与 API 匹配。 |
| `dev:status` 显示 stopped 或查看不到新日志 | 本文不是 PID 监督启动，改用各终端和第 5 节检查；`dev:status` 的迁移/依赖查询可作辅助，不以其进程记录作为结论。 |

### 可选：只在本机使用的 Compose 覆盖

如遇到短镜像名解析问题，可在已被 Git 忽略的 `.nasus/` 目录创建 `podman.compose.override.yml`，内容如下，不修改根 Compose 文件：

```yaml
services:
  postgres:
    image: docker.io/pgvector/pgvector:pg16
  minio:
    image: docker.io/minio/minio:latest
  minio-init:
    image: docker.io/minio/mc:latest
  temporal:
    image: docker.io/temporalio/auto-setup:1.25
  temporal-ui:
    image: docker.io/temporalio/ui:2.31.2
```

仅在 Linux SELinux 确认阻止 PostgreSQL 初始化目录访问时，在**同一文件已有的 `postgres` 条目**下增加以下 `volumes` 字段，不另写重复的 `postgres` 键：

```yaml
    volumes:
      - ./infra/docker/postgres/init:/docker-entrypoint-initdb.d:ro,Z
```

`:Z` 会对这个挂载目录做私有 SELinux 重标记，仅适用于该专用目录；不要用于整个 home、系统目录或与其他容器共享的目录。合并后应仍保留原有 PostgreSQL 数据卷挂载；检查不符合预期时停止，不继续启动。挂载路径按第一个 Compose 文件所在的仓库根目录解析。相关行为参见 [Podman volume 挂载说明](https://docs.podman.io/en/latest/markdown/podman-run.1.html#volume-v-source-volume-host-dir-container-dir-options)。

在管理终端替换便捷函数，让后续所有命令都包含覆盖文件：

```bash
nasus_infra() {
  podman compose -p nasus-podman \
    -f "$NASUS_DEV_ROOT/docker-compose.yml" \
    -f "$NASUS_DEV_ROOT/.nasus/podman.compose.override.yml" \
    --profile app --profile temporal "$@"
}
nasus_infra config >/dev/null
```

本地检查合并配置时不要对外暴露其中的密钥。上述覆盖仅是文档中的可选排查方案，不包含生产镜像固定、安全审计或跨架构兼容承诺。

## 7. 验收清单与兼容声明

- Podman/provider 版本、操作系统和 CPU 架构已记录，`podman info` 正常。
- 只有指定基础设施服务启动，没有意外启动容器版 API、Portal、Runner 或 Worker。
- PostgreSQL 可连接且 Alembic 到达当前 heads；MinIO 初始化成功，bucket 存在且版本控制开启；Temporal namespace 可查询。
- 四个本机应用进程正常运行，API、Runner、Portal 返回 200，Temporal 队列有 Worker；无 live 模型时明确标记业务验证未完成。
- 正常停止并按同一配置重启后，数据卷仍在，迁移状态一致，不需要清空数据。

本文已核对服务名、端口、模块入口及脚本边界，并检查 shell/Python 示例语法和本地文档链接；使用 Docker Compose 的纯配置解析验证了基础配置、完整镜像名覆盖及 SELinux 覆盖后的依赖与数据卷保留，不涉及启动容器。**尚未在 Podman 上完成以上实机清单**；配置解析不等于 Podman provider 兼容或实机启动通过。后续验证应记录实际版本、检查结果与失败项，不以 Docker 环境的通过结果替代。更完整的环境原则和迁移约束见 [后端运维与测试基线](./ops-and-test-baseline.md)。
