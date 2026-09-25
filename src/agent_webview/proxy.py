from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

IP_LOOKUP_URL = "https://ipwho.is/?lang=zh-CN"


class ProxyConfigurationError(RuntimeError):
    """当前平台无法可靠应用请求的浏览器代理。"""


@dataclass(frozen=True)
class ProxyIdentity:
    ip: str
    location: str


def normalize_proxy_url(value: str) -> str:
    """校验并规范化 HTTP(S) 代理地址。"""
    candidate = value.strip()
    if not candidate:
        raise ValueError("代理地址不能为空")
    if any(character.isspace() for character in candidate):
        raise ValueError("代理地址不能包含空白字符")

    try:
        parsed = urlsplit(candidate)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as error:
        raise ValueError("代理地址格式无效") from error

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("代理仅支持 http 或 https 协议")
    if not hostname:
        raise ValueError("代理地址必须包含主机名")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("暂不支持带用户名或密码的代理地址")
    if port == 0:
        raise ValueError("代理端口必须在 1 到 65535 之间")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("代理地址不能包含路径、查询参数或片段")

    try:
        ascii_hostname = (
            hostname if ":" in hostname else hostname.encode("idna").decode("ascii")
        )
    except UnicodeError as error:
        raise ValueError("代理主机名无效") from error
    normalized_port = port or (443 if scheme == "https" else 80)
    formatted_host = (
        f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname.lower()
    )
    return urlunsplit((scheme, f"{formatted_host}:{normalized_port}", "", "", ""))


def parse_ip_lookup_document(document: Any) -> ProxyIdentity:
    """解析 ipwho.is 返回的 JSON 文档。"""
    if isinstance(document, str):
        try:
            payload = json.loads(document.strip())
        except json.JSONDecodeError as error:
            raise ValueError("IP 查询服务未返回 JSON") from error
    elif isinstance(document, dict):
        payload = document
    else:
        raise ValueError("IP 查询服务返回格式无效")

    if payload.get("success") is False:
        raise ValueError("IP 查询服务拒绝了请求")
    raw_ip = str(payload.get("ip") or "").strip()
    try:
        normalized_ip = str(ip_address(raw_ip))
    except ValueError as error:
        raise ValueError("IP 查询结果缺少有效地址") from error

    location = str(payload.get("city") or "").strip() or "未知归属地"
    return ProxyIdentity(ip=normalized_ip, location=location)


def lookup_proxy_identity(proxy_url: str, *, timeout: float = 8) -> ProxyIdentity:
    """通过固定的第三方服务查询代理出口，供后台线程调用。"""
    with httpx.Client(
        proxy=proxy_url,
        timeout=timeout,
        trust_env=False,
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": "agent-webview"},
    ) as client:
        response = client.get(IP_LOOKUP_URL)
        response.raise_for_status()
    return parse_ip_lookup_document(response.text)


def format_proxy_title(
    base_title: str,
    *,
    state: str,
    ip: str | None = None,
    location: str | None = None,
) -> str:
    if state == "active" and ip:
        suffix = f" · {location}" if location and location != "未知归属地" else ""
        return f"[{ip}{suffix}] {base_title}"
    if state in {"checking", "unavailable"}:
        return f"[代理模式] {base_title}"
    return base_title


def configure_browser_proxy(proxy_url: str) -> None:
    """在 pywebview 选择并初始化浏览器内核前应用代理。"""
    normalized = normalize_proxy_url(proxy_url)
    parsed = urlsplit(normalized)
    system = platform.system()

    _set_process_proxy_environment(normalized)
    chromium_flags = (
        f"--proxy-server={normalized}",
        "--proxy-bypass-list=<-loopback>",
    )
    for flag in chromium_flags:
        _append_environment_flag("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", flag)
        _append_environment_flag("QTWEBENGINE_CHROMIUM_FLAGS", flag)

    if system == "Darwin":
        _configure_macos_proxy(
            hostname=parsed.hostname or "",
            port=parsed.port or (443 if parsed.scheme == "https" else 80),
            tls=parsed.scheme == "https",
        )
    elif system not in {"Windows", "Linux", "OpenBSD"}:
        raise ProxyConfigurationError(f"当前平台不支持浏览器代理：{system}")


def _set_process_proxy_environment(proxy_url: str) -> None:
    for name in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        os.environ[name] = proxy_url
    os.environ["no_proxy"] = ""
    os.environ["NO_PROXY"] = ""


def _append_environment_flag(name: str, flag: str) -> None:
    current = os.environ.get(name, "").strip()
    os.environ[name] = f"{current} {flag}".strip()


_MACOS_PROXY_REFERENCES: list[Any] = []


def _configure_macos_proxy(*, hostname: str, port: int, tls: bool) -> None:
    version = platform.mac_ver()[0]
    try:
        major = int(version.split(".", 1)[0])
    except (TypeError, ValueError):
        major = 0
    if major < 14:
        raise ProxyConfigurationError("WKWebView 代理需要 macOS 14 或更高版本")

    try:
        import Network
        import WebKit
    except ImportError as error:
        raise ProxyConfigurationError("macOS 代理组件未安装") from error

    try:
        endpoint = Network.nw_endpoint_create_host(
            hostname.encode("idna"),
            str(port).encode("ascii"),
        )
        tls_options = Network.nw_tls_create_options() if tls else None
        proxy = Network.nw_proxy_config_create_http_connect(endpoint, tls_options)
        Network.nw_proxy_config_set_failover_allowed(proxy, False)
        data_store = WebKit.WKWebsiteDataStore.defaultDataStore()
        data_store.setProxyConfigurations_([proxy])
    except Exception as error:
        raise ProxyConfigurationError("无法配置 WKWebView 代理") from error

    # Network.framework 对象由 Objective-C 管理；保留 Python 引用直至 worker 退出。
    _MACOS_PROXY_REFERENCES.extend(
        item for item in (endpoint, tls_options, proxy, data_store) if item is not None
    )
