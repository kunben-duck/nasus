# 原操作历史浏览器契约

生产 HistoryPanel 与真实 React Query/StrictMode、主题和翻译。Python 生产 DTO 编译
使用明确 archive/inspector doubles，全部 API 拦截，非本人 loopback origin 的 egress
阻断。不是正式路由、真实认证、PG/MinIO/Temporal、exweb 或独立业务 gold 验证。

在本人拥有且空闲的4207端口启动无 API proxy 的验证 surface，再执行：

```sh
VITE_NASUS_API_TOKEN='' apps/portal/node_modules/.bin/vite --config tests/browser/http-fixture/vite.config.mjs --port 4207
node tests/browser/http-fixture-history/verify.cjs
```

这里只是测试 surface，不启动开发服务、依赖或目标。结束后只清理本人进程。
可用 `NASUS_BROWSER_CONTRACT_ORIGIN=http://127.0.0.1:<owned-port>` 指定另一个已核验端口。
沿用仓库现有 Playwright engine verifier，不增加 @playwright/test 或依赖。

验证折叠时不读、显式元数据/阶段核验、读取中隐藏、无浏览器恢复键的刷新重读、
取消仍未知、撤权/篡改隐藏、桌面/390主题和无横向溢出。报告与截图在
`output/playwright/fixture-history-*`。私有端口和当前角色的真实权限另由集成门禁证明。
