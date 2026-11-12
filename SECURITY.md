# 安全策略

## 支持范围

当前仅维护最新的 `0.1.x` 版本。安全修复不会回溯到更早的开发快照。

## 报告方式

请通过 GitHub 仓库的 Private vulnerability reporting 或 Security Advisory 私下报告。
不要在公开 Issue 中附带 Cookie、Token、运行信息文件、HAR、请求日志或可复现账号。

报告应包含受影响版本、平台、最小复现步骤和影响范围。确认问题后会尽快给出处理
状态；公开披露时间由报告者和维护者协商。

## 本地安全边界

本工具允许执行任意页面 JavaScript 并读取浏览器 Cookie，只适合在可信本机使用。
不要直接暴露到不可信网络，也不要共享运行信息文件或 Cookie 快照。

代理会话会把出口 IP 发送给内置的第三方归属地查询服务。全局代理地址会记录在权限
受限的运行信息文件中；不要共享该文件。

单窗口代理账密通过受令牌保护的 API 传入，创建时保存在权限受限的 worker 配置中；
后续切换账密只保留在进程内存，不进入状态响应或代理事件。窗口使用随机本机端口
转发到上游，端口不面向外部网络；本机其他进程仍属于可信边界。HTTP Basic 仅编码
认证数据；需要保护到上游的传输时应使用 `https://` 代理，组件会验证其 TLS 证书。

## 可选缓存依赖的已核查告警

核查日期：2026-11-12。`cache` extra 的 mitmproxy 12.3.1 将 Tornado 限定为
`>=6.5.0,<=6.5.10`，目前不能直接安装已经修复的 Tornado 6.6+。
基础安装 `pip install agent-webview` 不引入该依赖。

锁定的 Tornado 6.5.10 有以下已知告警：

- [CVE-2026-116577](https://github.com/tornadoweb/tornado/security/advisories/GHSA-pcg2-g6cj-q92c)：Tornado HTTP 头解析的 CPU 消耗。
- [CVE-2026-115927](https://github.com/tornadoweb/tornado/security/advisories/GHSA-r4j5-9xpp-3985)：Tornado 分块请求体解析的 CPU/内存消耗。
- [CVE-2026-116578](https://github.com/tornadoweb/tornado/security/advisories/GHSA-pw9p-v7r6-gx4p)：Tornado RedirectHandler 的开放重定向。

本组件使用 `mitmproxy.tools.dump.DumpMaster`，通过 mitmproxy 自身的代理协议栈处理
HTTP/HTTPS，不加载 Tornado，也不启动 mitmweb 或 Tornado HTTP 服务；内置 onboarding
页面亦明确关闭。`tests/test_cache_proxy.py` 在隔离子进程中禁止导入 Tornado，再验证
实际缓存请求，防止升级依赖时无意改变这一边界。因此这些告警不涉及本组件当前运行路径。
发布检查仅对上述精确包名、版本、告警编号记录例外，其他发现仍阻止发布。

这不表示 Tornado 6.5.10 本身已修复。不要在同一依赖环境中用该版本启动 Tornado 服务
或 mitmweb；需要这些功能的程序应使用独立环境。上游解除版本限制后应升级并移除此例外。
