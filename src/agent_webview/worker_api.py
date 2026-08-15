from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from agent_webview import __version__
from agent_webview.auth import bearer_auth
from agent_webview.errors import (
    BrowserCommandError,
    BrowserCommandTimeoutError,
    BrowserNotReadyError,
)
from agent_webview.http_errors import install_validation_handler
from agent_webview.models import (
    CookieRestoreRequest,
    CookiesResponse,
    DomClickRequest,
    DomDispatchRequest,
    DomInputRequest,
    DomListenerRequest,
    DomQueryRequest,
    EventListResponse,
    HealthResponse,
    InstrumentationRequest,
    JavaScriptRequest,
    JavaScriptValueResponse,
    NavigateRequest,
    NavigateResponse,
    ProxyStatus,
    WindowStatus,
)
from agent_webview.runtime import BrowserRuntime

log = structlog.get_logger(__name__)


def create_worker_app(runtime: BrowserRuntime, token: str) -> FastAPI:
    app = FastAPI(
        title="Agent Webview Worker",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_validation_handler(app)
    router = APIRouter(prefix="/v1", dependencies=[Depends(bearer_auth(token))])

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.exception_handler(BrowserNotReadyError)
    async def not_ready_handler(_, error: BrowserNotReadyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(BrowserCommandTimeoutError)
    async def timeout_handler(_, error: BrowserCommandTimeoutError) -> JSONResponse:
        return JSONResponse(status_code=504, content={"detail": str(error)})

    @app.exception_handler(BrowserCommandError)
    async def command_handler(_, error: BrowserCommandError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": str(error), "error": error.details},
        )

    @app.exception_handler(Exception)
    async def unknown_handler(_, error: Exception) -> JSONResponse:
        log.error("接口执行失败", error_type=type(error).__name__)
        return JSONResponse(status_code=500, content={"detail": "接口执行失败"})

    @router.get("/status", response_model=WindowStatus)
    def status() -> dict:
        return runtime.status()

    @router.get("/proxy", response_model=ProxyStatus)
    def proxy_status(
        timeout: float = Query(default=0, ge=0, le=30),
    ) -> dict:
        return runtime.proxy_status(timeout)

    @router.post("/window/show", response_model=WindowStatus)
    def show() -> dict:
        return runtime.show()

    @router.post("/window/hide", response_model=WindowStatus)
    def hide() -> dict:
        return runtime.hide()

    @router.post("/navigate", response_model=NavigateResponse)
    def navigate(request: NavigateRequest) -> dict:
        return runtime.navigate(request.url)

    @router.post("/javascript/evaluate", response_model=JavaScriptValueResponse)
    def evaluate(request: JavaScriptRequest) -> dict:
        return {"value": runtime.evaluate(request.code, request.timeout)}

    @router.post("/javascript/execute", response_model=JavaScriptValueResponse)
    def execute(request: JavaScriptRequest) -> dict:
        return {"value": runtime.execute(request.code, request.timeout)}

    @router.post("/dom/query")
    def dom_query(request: DomQueryRequest) -> dict:
        return {"elements": runtime.dom_query(request)}

    @router.post("/dom/click")
    def dom_click(request: DomClickRequest) -> dict:
        return {"element": runtime.dom_click(request)}

    @router.post("/dom/input")
    def dom_input(request: DomInputRequest) -> dict:
        return {"element": runtime.dom_input(request)}

    @router.post("/dom/dispatch")
    def dom_dispatch(request: DomDispatchRequest) -> dict:
        return runtime.dom_dispatch(request)

    @router.post("/dom/listeners")
    def add_listener(request: DomListenerRequest) -> dict:
        return runtime.add_dom_listener(request)

    @router.delete("/dom/listeners/{listener_id}")
    def remove_listener(listener_id: str) -> dict:
        return runtime.remove_dom_listener(listener_id)

    @router.put("/instrumentation")
    def instrumentation(request: InstrumentationRequest) -> dict:
        return runtime.set_instrumentation(request)

    @router.get("/events", response_model=EventListResponse)
    def events(
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
        kinds: str | None = None,
        timeout: float = Query(default=0, ge=0, le=30),
    ) -> dict:
        page = runtime.events.get(
            after=after,
            limit=limit,
            kinds=(item.strip() for item in kinds.split(",")) if kinds else None,
            timeout=timeout,
        )
        return {
            "events": page.events,
            "latest_sequence": page.latest_sequence,
            "oldest_sequence": page.oldest_sequence,
            "dropped_before": page.dropped_before,
        }

    @router.delete("/events")
    def clear_events() -> dict:
        runtime.events.clear()
        return {"cleared": True}

    @router.get("/cookies", response_model=CookiesResponse)
    def get_cookies() -> dict:
        return {"url": runtime.status()["url"], "cookies": runtime.get_cookies()}

    @router.delete("/cookies")
    def clear_cookies() -> dict:
        return runtime.clear_cookies()

    @router.post("/cookies/restore")
    def restore_cookies(request: CookieRestoreRequest) -> dict:
        return runtime.restore_cookies(
            request.cookies,
            reload=request.reload,
            timeout=request.timeout,
        )

    @router.post("/destroy")
    def destroy() -> dict:
        runtime.destroy()
        return {"destroying": True}

    app.include_router(router)
    return app
