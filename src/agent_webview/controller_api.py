from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from agent_webview import __version__
from agent_webview.auth import bearer_auth
from agent_webview.http_errors import install_validation_handler
from agent_webview.models import (
    CookieRestoreRequest,
    CookieSnapshot,
    CookieSnapshotCreateRequest,
    CookieSnapshotDeleteResponse,
    CookieSnapshotListResponse,
    DomClickRequest,
    DomDispatchRequest,
    DomInputRequest,
    DomListenerRequest,
    DomQueryRequest,
    HealthResponse,
    InstrumentationRequest,
    JavaScriptRequest,
    NavigateRequest,
    SessionCreateRequest,
    SessionDescription,
    SessionDestroyResponse,
    SessionListResponse,
    WindowStatus,
)
from agent_webview.sessions import SessionManager, WorkerResponseError

log = structlog.get_logger(__name__)


def create_controller_app(manager: SessionManager, token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.close()

    app = FastAPI(
        title="Agent Webview",
        version=__version__,
        description="为 Agent 提供隔离的 pywebview 调试会话。",
        lifespan=lifespan,
    )
    install_validation_handler(app)
    router = APIRouter(prefix="/v1", dependencies=[Depends(bearer_auth(token))])

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.exception_handler(KeyError)
    async def missing_handler(_, __: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "会话不存在"})

    @app.exception_handler(FileNotFoundError)
    async def snapshot_handler(_, __: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "快照不存在"})

    @app.exception_handler(ProcessLookupError)
    async def process_handler(_, error: ProcessLookupError) -> JSONResponse:
        return JSONResponse(status_code=410, content={"detail": str(error)})

    @app.exception_handler(WorkerResponseError)
    async def worker_handler(_, error: WorkerResponseError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content=error.detail)

    @app.exception_handler(httpx.HTTPError)
    async def network_handler(_, __: httpx.HTTPError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": "子进程接口不可用"})

    @app.exception_handler(Exception)
    async def unknown_handler(_, error: Exception) -> JSONResponse:
        log.error("接口执行失败", error_type=type(error).__name__)
        return JSONResponse(status_code=500, content={"detail": "接口执行失败"})

    def call(
        session_id: str,
        method: str,
        path: str,
        *,
        params: Any = None,
        body: Any = None,
        timeout: float | None = None,
    ) -> Any:
        return manager.request(
            manager.get(session_id),
            method,
            path,
            params=params,
            json_body=body,
            timeout=timeout,
        )

    @router.get("/sessions", response_model=SessionListResponse)
    def list_sessions() -> dict[str, Any]:
        return {"sessions": manager.list()}

    @router.post("/sessions", status_code=201, response_model=SessionDescription)
    def create_session(request: SessionCreateRequest) -> dict[str, Any]:
        return manager.create(request)

    @router.get("/sessions/{session_id}", response_model=SessionDescription)
    def get_session(session_id: str) -> dict[str, Any]:
        return manager.describe(manager.get(session_id))

    @router.delete("/sessions/{session_id}", response_model=SessionDestroyResponse)
    def destroy_session(session_id: str) -> dict[str, Any]:
        return manager.destroy(session_id)

    @router.post("/sessions/{session_id}/window/show", response_model=WindowStatus)
    def show_window(session_id: str) -> dict[str, Any]:
        return call(session_id, "POST", "/v1/window/show")

    @router.post("/sessions/{session_id}/window/hide", response_model=WindowStatus)
    def hide_window(session_id: str) -> dict[str, Any]:
        return call(session_id, "POST", "/v1/window/hide")

    @router.post("/sessions/{session_id}/navigate")
    def navigate(session_id: str, request: NavigateRequest) -> dict[str, Any]:
        return call(session_id, "POST", "/v1/navigate", body=request.model_dump())

    @router.post("/sessions/{session_id}/javascript/evaluate")
    def evaluate(
        session_id: str,
        request: JavaScriptRequest,
    ) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/javascript/evaluate",
            body=request.model_dump(),
            timeout=request.timeout + 5,
        )

    @router.post("/sessions/{session_id}/javascript/execute")
    def execute(
        session_id: str,
        request: JavaScriptRequest,
    ) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/javascript/execute",
            body=request.model_dump(),
            timeout=request.timeout + 5,
        )

    @router.post("/sessions/{session_id}/dom/query")
    def dom_query(session_id: str, request: DomQueryRequest) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/dom/query",
            body=request.model_dump(),
        )

    @router.post("/sessions/{session_id}/dom/click")
    def dom_click(session_id: str, request: DomClickRequest) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/dom/click",
            body=request.model_dump(),
            timeout=request.timeout + 5,
        )

    @router.post("/sessions/{session_id}/dom/input")
    def dom_input(session_id: str, request: DomInputRequest) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/dom/input",
            body=request.model_dump(),
            timeout=request.timeout + 5,
        )

    @router.post("/sessions/{session_id}/dom/dispatch")
    def dom_dispatch(
        session_id: str,
        request: DomDispatchRequest,
    ) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/dom/dispatch",
            body=request.model_dump(),
            timeout=request.timeout + 5,
        )

    @router.post("/sessions/{session_id}/dom/listeners")
    def add_listener(
        session_id: str,
        request: DomListenerRequest,
    ) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/dom/listeners",
            body=request.model_dump(),
        )

    @router.delete("/sessions/{session_id}/dom/listeners/{listener_id}")
    def remove_listener(session_id: str, listener_id: str) -> dict[str, Any]:
        return call(
            session_id,
            "DELETE",
            f"/v1/dom/listeners/{listener_id}",
        )

    @router.put("/sessions/{session_id}/instrumentation")
    def instrumentation(
        session_id: str,
        request: InstrumentationRequest,
    ) -> dict[str, Any]:
        return call(
            session_id,
            "PUT",
            "/v1/instrumentation",
            body=request.model_dump(),
        )

    @router.get("/sessions/{session_id}/events")
    def events(
        session_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
        kinds: str | None = None,
        timeout: float = Query(default=0, ge=0, le=30),
    ) -> dict[str, Any]:
        return call(
            session_id,
            "GET",
            "/v1/events",
            params={
                "after": after,
                "limit": limit,
                "kinds": kinds,
                "timeout": timeout,
            },
            timeout=timeout + 5,
        )

    @router.delete("/sessions/{session_id}/events")
    def clear_events(session_id: str) -> dict[str, Any]:
        return call(session_id, "DELETE", "/v1/events")

    @router.get("/sessions/{session_id}/cookies")
    def get_cookies(session_id: str) -> dict[str, Any]:
        return call(session_id, "GET", "/v1/cookies")

    @router.delete("/sessions/{session_id}/cookies")
    def clear_cookies(session_id: str) -> dict[str, Any]:
        return call(session_id, "DELETE", "/v1/cookies")

    @router.post("/sessions/{session_id}/cookies/restore")
    def restore_cookies(
        session_id: str,
        request: CookieRestoreRequest,
    ) -> dict[str, Any]:
        return call(
            session_id,
            "POST",
            "/v1/cookies/restore",
            body=request.model_dump(),
            timeout=request.timeout + 5,
        )

    @router.post(
        "/sessions/{session_id}/cookie-snapshots",
        status_code=201,
        response_model=CookieSnapshot,
    )
    def create_snapshot(
        session_id: str,
        request: CookieSnapshotCreateRequest,
    ) -> dict[str, Any]:
        result = call(session_id, "GET", "/v1/cookies")
        return manager.snapshot_store.save(
            session_id=session_id,
            url=result.get("url"),
            cookies=result.get("cookies", []),
            name=request.name,
        )

    @router.get("/cookie-snapshots", response_model=CookieSnapshotListResponse)
    def list_snapshots() -> dict[str, Any]:
        return {"snapshots": manager.snapshot_store.list()}

    @router.get(
        "/cookie-snapshots/{snapshot_id}",
        response_model=CookieSnapshot,
    )
    def get_snapshot(snapshot_id: str) -> dict[str, Any]:
        try:
            return manager.snapshot_store.get(snapshot_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="快照不存在") from error

    @router.delete(
        "/cookie-snapshots/{snapshot_id}",
        response_model=CookieSnapshotDeleteResponse,
    )
    def delete_snapshot(snapshot_id: str) -> dict[str, Any]:
        try:
            manager.snapshot_store.delete(snapshot_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="快照不存在") from error
        return {"deleted": True, "snapshot_id": snapshot_id}

    app.include_router(router)
    return app
