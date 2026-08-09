class BrowserNotReadyError(RuntimeError):
    """页面尚未就绪。"""


class BrowserCommandError(RuntimeError):
    """页面脚本执行失败。"""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class BrowserCommandTimeoutError(TimeoutError):
    """页面脚本执行超时。"""
