# 参与开发

需要 Python 3.10 以上版本和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev
uv run ruff check src tests
uv run mypy
uv run pytest
uv run python scripts/smoke_service.py
```

代码注释、日志、调试输出和用户可见错误使用简短中文。提交应保持通用，不加入
特定网站选择器、账号流程或应用专属假设。

提交前请确认没有加入 Cookie、Token、Storage State、HAR、请求日志、运行信息文件
或真实服务域名。
