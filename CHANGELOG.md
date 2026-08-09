# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 和语义化版本。

## [Unreleased]

## [0.1.0] - 2026-08-09

### Added

- 增加公共 API 兼容策略、发布检查和跨平台持续集成。
- 增加发布前依赖漏洞审计和干净环境安装验证。
- 增加源码敏感信息扫描。
- 增加静态类型检查门禁。
- 为控制器核心接口增加明确的响应模型。
- 增加 Linux GTK 与 Qt 可选依赖。

### Changed

- 默认数据和运行文件迁移到操作系统当前用户目录。
- 版本号改为单一来源。
- 移除 pywebview 无法跨平台可靠处理的 `data:` URL 输入。

### Security

- Token、worker 配置和 Cookie 快照在 POSIX 平台使用 `0600` 权限。
- 敏感目录在 POSIX 平台使用 `0700` 权限。
- 监听非本机地址必须显式使用 `--allow-remote`。
- 并发控制器不能再覆盖或删除彼此的运行信息文件。
