# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 和语义化版本。

## [Unreleased]

## [0.1.6] - 2026-11-14

### Fixed

- 修复 macOS 14 中启用资源缓存后 HTTPS 页面停在隐藏窗口并超时的问题。窗口改用独立的 WKWebView 数据存储配置 HTTP/HTTPS 代理，避免 Network.framework CONNECT 通道拒绝已验证的临时缓存证书。
- 在 WKWebView 创建前安装数据存储，并让 Cookie 读取和无痕清理使用同一存储；不修改系统代理或钥匙串，保留上游证书校验和会话隔离。
- 同时修复普通代理会话对仅能通过上游解析的 HTTP 域名加载失败的问题；原生代理配置不可用时明确报错，不回退直连。

### Tests

- 增加原生代理配置时序、Cookie 存储绑定和配置失败测试。
- 扩展真实窗口冒烟测试，覆盖无痕 Cookie/localStorage 隔离及开启缓存时的账密代理切换。

## [0.1.5] - 2026-11-12

### Added

- 登录快照保存当前 origin 的完整 localStorage，原生 document-start 恢复，兼容旧 Cookie 快照。
- 创建会话支持 `private_mode` 和 `resource_cache`，默认缓存 JS/CSS，可配置后缀、保留时间与容量。
- 可选 `cache` 依赖提供跨进程 HTTP/HTTPS 磁盘缓存，支持既有代理，临时 CA 仅在当前窗口受信任。
- 新增存储/缓存单元测试及真实 WebView 冒烟测试；缓存需要 Python 3.12+。

### Security

- 发布检查覆盖 cache extra；记录 Tornado 6.5.10 三项不涉及缓存引擎运行路径的已核查告警，新增禁止加载 Tornado 的隔离测试，详见 SECURITY.md。
- 缓存代理关闭内置 onboarding 页面，HTTPS 上游保持证书验证。

## [0.1.4] - 2026-10-30

### Security

- 用兼容 Python 3.10 的 portalocker 替换存在已知漏洞的 filelock，保留控制器互斥锁；更新锁定的 certifi。

### Added

- 新增 `PUT /v1/sessions/{id}/proxy`，已打开的单窗口代理会话可更换上游，保留窗口、Cookie 和页面状态。
- 单窗口代理支持独立的用户名密码字段和 HTTP Basic 认证。
- 代理状态增加版本、可修改标识和认证标识；可用预期版本防止并发更新覆盖。
- 增加真实窗口切换冒烟测试 `scripts/smoke_proxy_switch.py`。

### Changed

- 单窗口代理经本机转发入口连接上游；切换时断开旧连接，不自动刷新页面或重放请求，不回退直连。
- 后台出口查询丢弃旧版本结果。全局代理仍不可修改，无代理会话保留原行为。

## [0.1.3] - 2026-09-25

### Changed

- 代理查询成功后的窗口标题仅显示出口 IP 和城市，移除“已进入代理模式”提示。
- 归属地仅保留查询结果中的城市；缺少城市时，窗口标题仅显示出口 IP。

## [0.1.2] - 2026-08-15

### Added

- 支持控制器级全局代理和会话级 HTTP/HTTPS 代理。
- 增加异步代理出口 IP/归属地查询、窗口标题标识、代理事件和独立状态接口。

### Changed

- IP 归属地查询使用固定内置服务并在后台静默执行，不再影响窗口加载或操作。
- 暂时将 Hatchling 限制在 `1.32` 以下，确保发布产物可被当前 Twine 校验。

## [0.1.1] - 2026-08-09

### Documentation

- 重构中文 README，并增加内容等价的英文版本。
- 重新划分用户文档、贡献者文档和维护资料的公开边界。

## [0.1.0] - 2026-08-09

### Added

- 首个公开预览版本。
- 增加进程隔离的 pywebview 会话、隐藏窗口和 HTTP 控制接口。
- 增加 DOM 操作、JavaScript 执行、页面事件和 Cookie 快照能力。
- 增加 Windows、macOS、Linux GTK 与 Linux Qt 支持。
- 明确 CLI、运行信息文件和 `/v1` HTTP API 的兼容范围。

### Changed

- 默认数据和运行文件使用操作系统当前用户目录。
- 不接受 pywebview 无法跨平台可靠处理的 `data:` URL 输入。

### Security

- Token、worker 配置和 Cookie 快照在 POSIX 平台使用 `0600` 权限。
- 敏感目录在 POSIX 平台使用 `0700` 权限。
- 监听非本机地址必须显式使用 `--allow-remote`。
- 并发控制器不能再覆盖或删除彼此的运行信息文件。
