# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 和语义化版本。

## [Unreleased]

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
