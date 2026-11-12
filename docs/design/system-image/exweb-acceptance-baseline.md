# exweb 首轮验收基线

固定来源：`kunben-duck/exweb` 的 `fe5827f6b76f77ef34918d8b452ee823142332dc`，126 个文件。
这份基线用于 Nasus 试用时的用例设计和结果解读，不是 exweb 的维护者批准规范，也不授予发布或执行权限。

## 首轮执行结果

固定提交的正式批次 `run-96tivyqo` 已退出 0（2 项验证通过）。同一计划记录 12 次原生 Runner
调用和 9 个 Workflow：4 组准备、4 条业务用例、4 组清理；目标移除后业务历史可回读。
四条业务响应都是 HTTP 200，但各自的受控响应体断言未满足，保留为失败。四组清理均通过；
同批拆除后的独立 PostgreSQL／MinIO 回读与拆除前账本逐条一致。

演示使用[本机脱敏报告](../../../output/exweb-first-use-verified.md)，对应正式 `verification.json` 和独立归档回执。
它证明 Nasus 能执行、保留失败并回溯证据；不证明 exweb 的业务验收、覆盖率或 Nasus 已获发布许可。

当前 Build 浏览器复验在隔离 PostgreSQL／私有 MinIO 中 **3 项全部通过**：固定本地检出、
HTTPS 固定 SHA、HTTPS 加需求与测试资料。真实 GitHub 导入核对 126 个文件；三源资料已归档，
结构构建须单独确认，候选不会自动发布。见 `output/exweb-first-use-current-build-browser.log`。

## 来源与结果

以同一 Git 修订中的 `docs/architecture/README.md` 为依据。其 Git blob 为
`fa428f2ae7e7b226a12465e101d61e81813583d0`，内容摘要为
`sha256:3461cd786d1416b60bb8d5099961d38bcb1f9b008ba47ed4f846ce5e434614a0`。
文档说明其内容基于当前实现整理，因此可作为来源证据，但不是独立业务标准。

| 场景 | 固定来源及边界 | 本次实际观察 |
| --- | --- | --- |
| 会话归属与隔离 | 架构目标第 8 行、会话隔离设计第 315 行起。身份来自 Header 或 WebSocket query（第 335 行）；这不是可信登录身份或防冒用的证明。 | 本人读取和列表通过；不同用户／租户列表及读接口未返回原会话。跨用户、跨租户的读请求均返回 HTTP 500；拒绝状态没有满足开发探针的 403/404 预期。 |
| 关闭会话后的读取 | 该文档没有定义关闭后读取的状态码契约。 | 关闭操作通过，关闭后读取返回 HTTP 500，不符合开发探针的 404/409/410 预期，需独立审阅对外契约。 |
| 会话元数据持久化 | 当前存储说明第 246 行写明 `InMemorySessionRepository`，后续演进建议第 375 行提出迁移会话数据；不能把聊天消息的 PostgreSQL 存储当作会话元数据的持久化。 | 目标 PostgreSQL 中对应会话计数为 0；目标重启后原身份列表返回 HTTP 200 和 0 条记录。符合当前内存实现的行为，仍未满足跨重启持久化就绪检查。 |

以上观察均来自 `output/exweb-pinned-health-native.json` 的同一实际 Docker 批次；资源清理已核验。
不更改原探针的 **20/27 通过** 或其 7 项失败，不将缺少数据泄漏观察等同于认证／授权已验收。
原始请求、响应和摘要仍在报告中；本页不复用独立探针作为正式 RunPlan 的执行证据。
试用时使用[只读摘要命令](./exweb-native-runtime-validation.md#可复跑的正式验收命令)生成可展示的状态表；
仅在正式批次完整通过并产出回执后添加 `--canonical-report`。不要直接分享含请求／响应正文的原始报告。

## Nasus 试用步骤

1. 从 Build 选择「导入 Git 仓库」，新建试用项目或选择已有项目。仓库填 `https://github.com/kunben-duck/exweb.git`，提交 SHA 填 `fe5827f6b76f77ef34918d8b452ee823142332dc`。离线时也可填写已核对提交的本地 checkout 路径，并留空 Git 引用。将原仓库的 `docs/architecture/README.md` 作为可选文档来源，不要把本页的探针结果作为需求导入。
2. 核对系统画像能回溯 `ChatSessionController`、`SessionApplicationService`、`SessionRepository` 及上述文档锚点。若只找到字符串或调用候选，不标为已验证关系。
3. 以同一会话 ID、本人、同租户其他用户、其他租户构建最小回归。只把隔离意图和真实可观察结果作为来源；拒绝状态、可信身份边界和持久化需求单列待确认，不让用例从实际 500 倒推正确预期。
4. 正式用例仍须按既有审阅和授权流程执行。使用[正式验收命令](./exweb-native-runtime-validation.md#可复跑的正式验收命令)核对实际派发、原响应、资源清理和清理后历史回读；不能用本页替代完成回执。

## 可上传的会话隔离试用资料

- 在「需求文档」上传[会话隔离草稿](../../examples/exweb/session-isolation-draft.md)，在「测试资产」上传[三条用例 CSV](../../examples/exweb/session-isolation-cases.csv)。可同时把固定版本的原架构说明作为背景资料。
- 构建候选后，在「画像版本」选中该候选，再从「引用关联审阅」点击「查找原文引用」。三条用例引用同一条试用需求；代码位置可独立追到 `ChatSessionController`。仅有引用不证明实现正确、断言通过或业务覆盖。
- 草稿分开描述本人、同租户不同用户、不同租户同用户标识的预期。原架构没有批准具体拒绝状态码或可信身份机制；不要用历史返回的 `500` 反向批准断言，也不要用真实用户、会话或生产环境。

隔离 PostgreSQL／私有 MinIO 已验证：固定源码、原架构、草稿和 CSV 同时归档，删除临时副本后可读原文；三个候选均为 `references/proposed`，未纳入正式画像。三条验收条件和一条规则均未批准、没有可执行断言，生成预览仍阻塞。
Build 浏览器专项已验证 GitHub 固定提交 + 页面上传两份试用资料，三类来源均进入候选且需单独确认结构预算。
对应日志为 `output/exweb-session-isolation-draft-browser.log`（1 项）及
`output/exweb-session-isolation-draft-pg-minio-recheck.log`（2 项）。它们都没有执行 exweb。

## Portal 演示路径

在项目「系统画像」进入 `Source analyses`，选择捕获版本及分析报告，切换到 `Structure → Routes`。
再从 `Image revisions` 打开冻结候选、找到 `ChatController` 并点击 `Inspect frozen evidence`，核对源码及行号。
从 `Investigation plans` 可以查看结构构建与授权回执；这只产生结构候选，不代表业务发布或目标执行。

已获授权的真实执行可在同一项目「执行记录」按原业务命令 ID 查询。先区分任务终态与用例结果，
再展开各用例检查原预期和实际 HTTP 状态；查询不会派发或取消请求。该界面已通过 390px 中文
浏览器专项（`output/playwright/runs-fixture-history/original-case-results-zh-390.png`），
截图中的数据是协议样本，不是 exweb 执行。正式批次使用独立数据库，清理后以其经核验的
报告展示实际观察，不把隔离库中的命令 ID 当作开发环境可访问记录。

当前固定源码浏览器专项已通过（`output/exweb-first-use-current-analysis-browser.log`）。归档 126 个文件，
解析 120 个、6 个未支持，核对 13 条路由及原文证据。可展示
[源码分析](../../../output/playwright/exweb-first-use-0123/exweb-analysis.png)和
[冻结原文](../../../output/playwright/exweb-first-use-0123/exweb-image-revision-evidence.png)。该专项使用
隔离 PostgreSQL／MinIO，不启动被测应用；不要将测试项目 ID 作为开发库中的可访问项目链接。
Build 快捷入口也已实测通过
（`output/exweb-build-shortcut-browser.log`）：创建一个项目，自动聚焦代码输入框，导入原始固定
源码后等待单独确认结构预算，确认后生成候选。无需先发送聊天提示，不产生发布授权。两项复跑均需
提供已核对的 checkout：

```bash
EXWEB_FIXTURE_ROOT=/absolute/path/to/exweb npm run test:e2e -- \
  tests/e2e/exweb-build-shortcut.spec.ts tests/e2e/exweb-analysis.spec.ts --workers=1
```

若要测试 HTTPS + 固定提交入口，将 `EXWEB_REMOTE_GIT=1` 传给
`npm run test:e2e -- tests/e2e/exweb-build-shortcut.spec.ts --workers=1`。只读取公开 Git 仓库，
在独立测试库中验证来源和画像候选，不执行 exweb。
该入口已用真实 GitHub、隔离 PostgreSQL 和私有 MinIO 验证
（`output/exweb-fixed-commit-browser-recheck.log`）；试用服务须先应用迁移 0123 并加载新版 API。
使用隔离 PostgreSQL 和私有 MinIO 的 `0122 → 0123` 升级演练已通过：旧库先冻结原分支来源，
并拒绝固定 SHA；迁移后旧绑定 ID、身份摘要和冻结清单不变，新固定来源可独立登记。
从私有桶回读旧、新清单中的源码，每份 126 个文件均与同一提交的 Git 字节一致。
见 `output/exweb-v1-upgrade-0122-0123-rehearsal-final.log`；本机开发库、服务和原验收批次未变更。
受控主分支前移后，固定来源的 126 个原文件仍能从 MinIO 逐项回读
（`output/exweb-fixed-commit-archive-replay.json`），不是业务执行报告。

## 原始文档接入实测

固定 Git 提交的 126 个文件及其原始架构说明通过真实 Nasus HTTP 入口登记、采集并冻结为候选画像。
在隔离 PostgreSQL 和私有 MinIO 中，删除临时导入副本后仍可回读架构文档第 315–335 行和
`ChatSessionController` 源码片段，均与原 Git blob 对应行完全一致。匿名证据读取返回 HTTP 401，
原 exweb Git 工作树未被改动。本次没有导入合成需求或用例。

仅导入该原始文档时，它在画像中仍是来源证据：没有显式验收条件，测试设计预览的强制约束为空且状态为阻塞。
这验证了真实材料的导入、定位和历史回读，不代表正式业务用例执行或已批准的测试预期。

复验为 `1 passed in 29.66s`（`output/exweb-authored-architecture-pilot-recheck.log`）。
沿用正式验收的隔离 PostgreSQL 和 MinIO 测试连接，将 `EXWEB_SOURCE_REFRESH_GIT_ROOT` 指向已核验的
固定 Git checkout，再运行：

```sh
./.venv/bin/python scripts/test-api-postgres.py --minio \
  apps/api/tests/test_exweb_authored_architecture_api.py -q
```
