from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiResponse):
    ok: bool


class WindowBounds(ApiResponse):
    x: int | float | None
    y: int | float | None
    width: int | float | None
    height: int | float | None


class WindowStatus(ApiResponse):
    session_id: str
    window_id: str
    native_window_id: int | str | None
    pid: int
    ready: bool
    closed: bool
    visible: bool
    url: str | None
    title: str | None
    bounds: WindowBounds
    latest_event_sequence: int


class ProcessStatus(ApiResponse):
    pid: int
    status: str
    create_time: float
    num_threads: int
    memory_rss: int


class SessionDescription(ApiResponse):
    session_id: str
    window_id: str
    pid: int
    launcher_pid: int | None
    created_at: str
    requested_url: str
    state: Literal["running", "exited"]
    exit_code: int | None
    process: ProcessStatus | None
    window: WindowStatus | None


class SessionListResponse(ApiResponse):
    sessions: list[SessionDescription]


class SessionDestroyResponse(ApiResponse):
    session_id: str
    pid: int
    exit_code: int | None


class NavigateResponse(ApiResponse):
    accepted: bool
    url: str


class JavaScriptValueResponse(ApiResponse):
    value: Any = None


class EventRecord(ApiResponse):
    sequence: int
    timestamp: str
    kind: str
    payload: Any


class EventListResponse(ApiResponse):
    events: list[EventRecord]
    latest_sequence: int
    oldest_sequence: int
    dropped_before: int | None


class CookiesResponse(ApiResponse):
    url: str | None
    cookies: list[dict[str, Any]]


class CookieSnapshot(ApiResponse):
    snapshot_id: str
    name: str | None
    session_id: str
    url: str | None
    created_at: str
    cookies: list[dict[str, Any]]
    limitations: list[str]


class CookieSnapshotSummary(ApiResponse):
    snapshot_id: str
    name: str | None
    session_id: str
    url: str | None
    created_at: str


class CookieSnapshotListResponse(ApiResponse):
    snapshots: list[CookieSnapshotSummary]


class CookieSnapshotDeleteResponse(ApiResponse):
    deleted: bool
    snapshot_id: str


class CookieRecord(BaseModel):
    name: str
    value: str
    domain: str | None = None
    path: str = "/"
    expires: str | int | float | None = None
    secure: bool = False
    http_only: bool = False
    same_site: Literal["Strict", "Lax", "None"] | None = None


class SessionCreateRequest(BaseModel):
    url: str | None = None
    title: str = "Agent Webview"
    width: int = Field(default=1280, ge=320, le=8192)
    height: int = Field(default=900, ge=240, le=8192)
    visible: bool = False
    user_agent: str | None = None
    snapshot_id: str | None = None
    cookies: list[CookieRecord] = Field(default_factory=list)
    remote_debugging_port: int | None = Field(default=None, ge=1024, le=65535)
    gui: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = ("http://", "https://", "about:")
        if not value.startswith(allowed):
            raise ValueError("URL 仅支持 http、https 或 about")
        return value


class NavigateRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        result = SessionCreateRequest.validate_url(value)
        assert result is not None
        return result


class JavaScriptRequest(BaseModel):
    code: str = Field(min_length=1)
    timeout: float = Field(default=30, gt=0, le=300)


class DomQueryRequest(BaseModel):
    selector: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=500)


class DomClickRequest(BaseModel):
    selector: str = Field(min_length=1)
    index: int = Field(default=0, ge=0)
    scroll: bool = True
    timeout: float = Field(default=30, gt=0, le=300)


class DomInputRequest(BaseModel):
    selector: str = Field(min_length=1)
    value: str
    index: int = Field(default=0, ge=0)
    timeout: float = Field(default=30, gt=0, le=300)


class DomDispatchRequest(BaseModel):
    selector: str = Field(min_length=1)
    event: str = Field(min_length=1)
    index: int = Field(default=0, ge=0)
    detail: Any = None
    timeout: float = Field(default=30, gt=0, le=300)


class DomListenerRequest(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    selector: str = Field(min_length=1)
    event: str = Field(min_length=1)
    capture: bool = True
    debounce_ms: int = Field(default=0, ge=0, le=60000)


class InstrumentationRequest(BaseModel):
    network: bool = True
    mutations: bool = False
    mutation_selector: str | None = None
    capture_request_bodies: bool = False
    capture_response_bodies: bool = False
    max_body_chars: int = Field(default=20000, ge=100, le=1_000_000)


class CookieRestoreRequest(BaseModel):
    cookies: list[CookieRecord]
    reload: bool = True
    timeout: float = Field(default=30, gt=0, le=300)


class CookieSnapshotCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
