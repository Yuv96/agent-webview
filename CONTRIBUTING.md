# 参与开发

基础开发需要 Python 3.10 以上版本和 [uv](https://docs.astral.sh/uv/)。
资源缓存测试需要 Python 3.12+ 及 `cache` extra。

```bash
uv sync --extra dev --extra cache
uv run --extra dev --extra cache ruff check src tests
uv run --extra dev --extra cache mypy
uv run --extra dev --extra cache pytest
uv run python scripts/smoke_service.py
uv run --extra cache python scripts/smoke_proxy_switch.py
uv run --extra cache python scripts/smoke_proxy_switch.py --cache
uv run --extra cache python scripts/smoke_storage_cache.py
```

代码注释、日志、调试输出和用户可见错误使用简短中文。提交应保持通用，不加入
特定网站选择器、账号流程或应用专属假设。

代理切换冒烟测试使用两个本机模拟代理和虚构域名，不需要真实代理账密或付费资源。
应分别在支持的原生 WebView 平台验证窗口状态保留；仅单元测试通过不能证明原生路由生效。

提交前请确认没有加入 Cookie、Token、Storage State、HAR、请求日志、运行信息文件
或真实服务域名。
