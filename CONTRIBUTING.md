# 参与开发

需要 Python 3.10 以上版本和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev
uv run ruff check src tests
uv run mypy
uv run pytest
python scripts/release_check.py
uv run python scripts/smoke_service.py
```

代码注释、日志、调试输出和用户可见错误使用简短中文。浏览器页面规则、账号流程
和具体平台业务不得进入本包。

提交前请确认没有加入 Cookie、Token、Storage State、HAR、请求日志、运行信息文件
或真实业务域名。
