from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def install_validation_handler(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(item) for item in detail["loc"]),
                "type": detail["type"],
            }
            for detail in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": "请求参数无效", "errors": errors},
        )
