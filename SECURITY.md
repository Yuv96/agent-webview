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
