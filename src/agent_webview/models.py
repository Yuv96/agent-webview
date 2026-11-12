from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_webview.proxy import normalize_proxy_url


class ApiResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiResponse):
    ok: bool


class WindowBounds(ApiResponse):
    x: int | float | None
    y: int | float | None
    width: int | float | None
    height: int | float | None


class ProxyStatus(ApiResponse):
    enabled: bool
    scope: Literal["global", "window"] | None
    server: str | None
    state: Literal["disabled", "checking", "active", "unavailable"]
    ip: str | None
    location: str | None
    revision: int = 0
    mutable: bool = False
    authenticated: bool = False


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
    proxy: ProxyStatus
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
    local_storage: dict[str, dict[str, str]] = Field(default_factory=dict)
    schema_version: int = 1


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


class ProxyCredentials(BaseModel):
    proxy_username: str | None = Field(default=None, min_length=1, max_length=512, repr=False)
    proxy_password: str | None = Field(default=None, min_length=1, max_length=512, repr=False)

    @model_validator(mode="after")
    def validate_credentials(self):
        if (self.proxy_username is None) != (self.proxy_password is None):
            raise ValueError("代理用户名和密码必须同时提供")
        if self.proxy_username and ":" in self.proxy_username:
            raise ValueError("代理用户名不能包含冒号")
        return self


class ProxyUpdateRequest(ProxyCredentials):
    model_config = ConfigDict(extra="forbid")
    proxy: str
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, value: str) -> str:
        return normalize_proxy_url(value)


class ResourceCacheOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    extensions: list[str] = Field(default_factory=lambda: [".js", ".css"], max_length=50)
    max_age_seconds: int = Field(default=604800, ge=1, le=31536000)
    max_resource_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    max_total_bytes: int = Field(default=512 * 1024 * 1024, ge=1, le=10 * 1024**3)

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, values: list[str]) -> list[str]:
        result = []
        for value in values:
            extension = "." + value.strip().lower().lstrip(".")
            if not re.fullmatch(r"\.[a-z0-9]+", extension):
                raise ValueError("缓存后缀必须为扩展名，例如 .js 或 .css")
            if extension not in result:
                result.append(extension)
        if not result:
            raise ValueError("缓存后缀不能为空")
        return result


class StorageStateResponse(CookiesResponse):
    local_storage: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("local_storage")
    @classmethod
    def validate_origins(cls, values: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        for origin in values:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.path or parsed.query or parsed.fragment
                    or parsed.username is not None or parsed.password is not None):
                raise ValueError("localStorage 必须以 HTTP(S) origin 为键")
        return values


class SessionCreateRequest(ProxyCredentials):
    url: str | None = None
    title: str = "Agent Webview"
    width: int = Field(default=1280, ge=320, le=8192)
    height: int = Field(default=900, ge=240, le=8192)
    visible: bool = False
    user_agent: str | None = None
    private_mode: bool = True
    resource_cache: ResourceCacheOptions = Field(default_factory=ResourceCacheOptions)
    snapshot_id: str | None = None
    cookies: list[CookieRecord] = Field(default_factory=list)
    remote_debugging_port: int | None = Field(default=None, ge=1024, le=65535)
    gui: str | None = None
    proxy: str | None = None

    @model_validator(mode="after")
    def credentials_require_proxy(self):
        if self.proxy_username is not None and self.proxy is None:
            raise ValueError("代理认证需要提供窗口代理地址")
        return self

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = ("http://", "https://", "about:")
        if not value.startswith(allowed):
            raise ValueError("URL 仅支持 http、https 或 about")
        return value

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, value: str | None) -> str | None:
        return normalize_proxy_url(value) if value is not None else None


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
