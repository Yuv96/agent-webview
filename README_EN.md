<div align="center">

# Agent Webview

**An isolated local WebView debugging service for AI agents**

Manage hidden browser sessions, inspect the DOM, execute JavaScript, and observe page events through a stable HTTP API.

[简体中文](https://github.com/Yuv96/agent-webview/blob/main/README.md) · [English](https://github.com/Yuv96/agent-webview/blob/main/README_EN.md)

[![PyPI](https://img.shields.io/pypi/v/agent-webview?style=flat-square&logo=pypi&logoColor=white)](https://pypi.org/project/agent-webview/)
[![Python](https://img.shields.io/pypi/pyversions/agent-webview?style=flat-square&logo=python&logoColor=white)](https://pypi.org/project/agent-webview/)
[![CI](https://img.shields.io/github/actions/workflow/status/Yuv96/agent-webview/ci.yml?branch=main&style=flat-square&logo=github)](https://github.com/Yuv96/agent-webview/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/Yuv96/agent-webview?style=flat-square)](https://github.com/Yuv96/agent-webview/blob/main/LICENSE)

</div>

> [!NOTE]
> This project is still in the `0.x` preview stage. The CLI, runtime information
> file, and `/v1` HTTP API form the current compatibility boundary. Internal
> Python modules are not yet considered stable public APIs.

## ✨ Features

| Capability | Description |
| --- | --- |
| Process isolation | Every session runs in a separate pywebview worker and private window |
| Agent-friendly API | OpenAPI, structured JSON, Bearer authentication, and stable `/v1` endpoints |
| Hidden by default | Show windows only when needed and run multiple sessions in parallel |
| Page interaction | Navigate, query the DOM, enter text, click elements, and execute JavaScript |
| Observability | Long-poll DOM events, DOM mutations, and page-level network activity |
| Proxy debugging | Apply a global or per-window HTTP(S) proxy and resolve its exit IP and location asynchronously |
| Login snapshots | Save cookies and current-origin localStorage for new sessions |
| Resource cache | Optional persistent JS/CSS cache with extension allowlists |
| Cross-platform | Windows, macOS, and Linux with a GTK or Qt backend |

## 🧱 Architecture

```text
AI agent / Python script
          │
          │ HTTP + Bearer token
          ▼
agent-webview controller
          ├── isolated worker ── private window A
          ├── isolated worker ── private window B
          └── isolated worker ── private window C
```

The controller does not create a visible window itself. Every
`POST /v1/sessions` request starts a new worker process. Later requests in that
session reuse the same window until the session is deleted.

## 📦 Installation

Python 3.10 or later is required.

```bash
python -m pip install agent-webview
```

For `requirements.txt`, keep dependencies within the same minor release line:

```text
agent-webview~=0.1.0
```

The distribution, import package, and command names are:

- `pip install agent-webview`
- `import agent_webview`
- `agent-webview`

### Platform dependencies

| Platform | WebView backend |
| --- | --- |
| Windows | WebView2; modern Windows versions usually include the WebView2 Runtime |
| macOS | System WebKit |
| Linux | Install `agent-webview[linux-gtk]` or `agent-webview[linux-qt]` |

## 🚀 Quick start

### 1. Start the controller

```bash
agent-webview
```

The default address is `http://127.0.0.1:8765`. On startup, the controller
writes a runtime JSON file containing its address, process ID, OpenAPI URL, and
a random Bearer token. Print the file location with:

```bash
agent-webview --print-runtime-file
```

Data is stored in the operating system's per-user directories by default and
does not modify the current project directory. To choose explicit locations:

```bash
agent-webview \
  --data-dir ./webview-data \
  --runtime-file ./agent-webview-runtime.json
```

To route every window created by this controller through the same proxy, set it
when the controller starts:

```bash
agent-webview --proxy http://127.0.0.1:7890
```

### 2. Create and control a session

This Python example reads the runtime information, creates a hidden session,
waits for its window, and reads the page title:

```python
import json
import subprocess
import time
from pathlib import Path

import httpx

runtime_path = Path(
    subprocess.check_output(
        ["agent-webview", "--print-runtime-file"],
        text=True,
    ).strip()
)
runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
headers = {"Authorization": f"Bearer {runtime['token']}"}

with httpx.Client(
    base_url=runtime["base_url"],
    headers=headers,
    timeout=30,
) as client:
    session = client.post(
        "/v1/sessions",
        json={"url": "https://example.com", "visible": False},
    ).raise_for_status().json()
    session_id = session["session_id"]

    for _ in range(100):
        state = client.get(f"/v1/sessions/{session_id}").raise_for_status().json()
        if (state.get("window") or {}).get("ready"):
            break
        time.sleep(0.1)
    else:
        raise TimeoutError("Browser window did not become ready")

    result = client.post(
        f"/v1/sessions/{session_id}/javascript/evaluate",
        json={"code": "document.title", "timeout": 10},
    ).raise_for_status().json()
    print(result["value"])

    client.delete(f"/v1/sessions/{session_id}").raise_for_status()
```

Once the service is running, open the `docs_url` from the runtime file or visit
`/docs` and `/openapi.json` for the complete API schema.

## 🔌 Main endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/sessions` | Create an isolated private session |
| `GET` | `/v1/sessions` | List sessions and process information |
| `GET` | `/v1/sessions/{id}` | Read window, handle, and process state |
| `GET` | `/v1/sessions/{id}/proxy` | Read proxy configuration, exit IP, and location |
| `PUT` | `/v1/sessions/{id}/proxy` | Change the upstream proxy for an open per-window proxy session |
| `DELETE` | `/v1/sessions/{id}` | Destroy a session |
| `POST` | `/v1/sessions/{id}/navigate` | Navigate to another URL |
| `POST` | `/v1/sessions/{id}/javascript/evaluate` | Evaluate an expression and return its value |
| `POST` | `/v1/sessions/{id}/javascript/execute` | Execute JavaScript statements |
| `POST` | `/v1/sessions/{id}/dom/query` | Query DOM elements |
| `POST` | `/v1/sessions/{id}/dom/input` | Set a value and dispatch input events |
| `POST` | `/v1/sessions/{id}/dom/click` | Call an element's DOM `click()` method |
| `POST` | `/v1/sessions/{id}/dom/listeners` | Register a DOM event listener |
| `PUT` | `/v1/sessions/{id}/instrumentation` | Configure network and DOM instrumentation |
| `GET` | `/v1/sessions/{id}/events` | Long-poll collected events |
| `GET` | `/v1/sessions/{id}/cookies` | Read cookies |
| `POST` | `/v1/sessions/{id}/cookie-snapshots` | Save a cookie snapshot |
| `GET` | `/v1/cookie-snapshots` | List cookie snapshots |
| `POST` | `/v1/sessions/{id}/window/show` | Show a window |
| `POST` | `/v1/sessions/{id}/window/hide` | Hide a window |

A newly created session includes:

- `session_id`: the controller session identifier.
- `window_id`: a stable identifier generated by the service.
- `native_window_id`: the native GUI handle, which may be `null` before the
  window exists.
- `pid`: the actual pywebview worker process ID.
- `launcher_pid`: a launcher process ID in some Windows virtual environments,
  otherwise `null`.

## 🌐 Proxy debugging

Passing `--proxy` at controller startup sets an immutable global proxy for all
windows created until that controller process exits. Without a global proxy,
set `proxy` on an individual session request:

```python
session = client.post(
    "/v1/sessions",
    json={
        "url": "https://example.com",
        "visible": False,
        "proxy": "http://127.0.0.1:7890",
    },
).raise_for_status().json()
```

The global proxy takes precedence over a per-window value so that every window
under that controller uses the same route. Proxy URLs may use `http://` or
`https://`. SOCKS, paths, and query strings are not supported. Per-window proxies
support HTTP Basic credentials: supply both `proxy_username` and `proxy_password`
on creation, rather than embedding credentials in the URL. Windows requires
WebView2; macOS requires macOS 14 or later.

### Change an open window's proxy

Sessions created with a per-window `proxy` can switch upstreams while preserving
the window, cookies, JavaScript state, and unfinished inputs. No page reload occurs:

```python
current = client.get(f"/v1/sessions/{session_id}/proxy").raise_for_status().json()
changed = client.put(
    f"/v1/sessions/{session_id}/proxy",
    json={
        "proxy": "http://127.0.0.1:7891",
        "proxy_username": proxy_username,
        "proxy_password": proxy_password,
        "expected_revision": current["revision"],
    },
).raise_for_status().json()
```

Omit both credential fields for an unauthenticated upstream; omission clears
previous credentials. Optional `expected_revision` rejects concurrent changes
with `409` when the revision differs. `proxy` is required and cannot be `null`;
the operation never implicitly enables a direct connection.

`ProxyStatus` adds `revision` (starting at 0), `mutable`, and `authenticated`.
A successful update means the upstream was replaced; `state=checking` while
exit lookup runs asynchronously. It does not guarantee upstream connectivity.
Unconfigured, globally proxied, or closed windows return `409`. Global proxies
remain immutable. Status, titles, and proxy events never return credentials.

Each per-window proxy uses a fixed loopback relay bound to `127.0.0.1`. Switching
closes every old HTTP connection and CONNECT tunnel, including WebSockets and
in-flight requests. New requests use the new upstream. Interrupted submissions
are not automatically retried, and authentication/connection failure never falls
back to direct networking. Switch after critical submissions finish. Preserved
cookies do not guarantee that a website accepts a changed login IP. The component
does not purchase, extract, or automatically renew proxy IPs.

The target page starts loading immediately. A background thread queries a
fixed third-party service through the proxy for its exit IP and location; page
loading never waits for this lookup. After success, a visible window title
looks like:

```text
[203.0.113.8 · Shanghai] Agent Webview
```

Only the city is retained as the location. If no city is returned, the title
shows only the exit IP.

For hidden windows and programmatic callers, use the dedicated status endpoint:

```python
proxy = client.get(
    f"/v1/sessions/{session_id}/proxy",
    params={"timeout": 10},
).raise_for_status().json()

if proxy["state"] == "active":
    print(proxy["server"], proxy["ip"], proxy["location"])
```

`timeout` defaults to `0` for an immediate response. A value up to 30 seconds
waits only on that status request, never on the WebView. States mean:

- `disabled`: this window has no configured proxy.
- `checking`: the window started with the proxy while exit information is
  still being resolved in the background.
- `active`: the fixed lookup service successfully returned an exit IP and
  location through the proxy.
- `unavailable`: this lookup produced no result. The page continues normally,
  and this state alone does not prove the proxy failed.

Applying a switch emits a `changed` proxy event with `revision` and a credential-free
`server`. Stale lookups cannot overwrite the current revision. Completion also
emits a `proxy` event through the existing event stream. The
lookup service URL is fixed internally and cannot be overridden through the
CLI or HTTP API.

## 🔎 Page instrumentation

Use `PUT /v1/sessions/{id}/instrumentation` to enable:

- `network`: page-level `fetch`, `XMLHttpRequest`, WebSocket, and Performance
  Resource records.
- `mutations`: DOM mutation records, optionally scoped by `mutation_selector`.
- `capture_request_bodies` / `capture_response_bodies`: optional request and
  response body capture.

Long-poll events with `GET /v1/sessions/{id}/events?after=0&timeout=20`, then
pass the returned `latest_sequence` as the next `after` value. The `kinds`
parameter can filter `dom`, `network`, `mutation`, and `lifecycle` events.
The `proxy` kind reports completion of the asynchronous exit lookup.

The network probe is not a browser-level proxy. It cannot guarantee visibility
into Service Workers, cache hits, extension traffic, or every response body.
For protocol-level debugging, set `remote_debugging_port` when creating a
session and use a DevTools protocol supported by the selected backend.

## 🍪 Login snapshots (cookies + localStorage)

Cookie snapshots are stored in the per-user data directory by default; use
`--data-dir` to choose another location. Pass a `snapshot_id` when creating a
new session to attempt a restore. Explicit `cookies` in the request override
snapshot cookies with the same name, domain, and path. The `/cookie-snapshots` routes
remain compatible. New snapshots include `schema_version: 2` and `local_storage`, an
origin-to-string-map dictionary. All keys are preserved, including Unicode, empty
values, special names, and stores with more than 500 keys.

On WKWebView and WebView2, a native document-start script replaces localStorage
before website scripts run, once per matching origin in that session. Subsequent
navigation does not overwrite new values, and unrelated origins receive no data.
Older cookie-only snapshots still load.

Restoration is subject to browser backend limitations:

- pywebview can read cookies, including HttpOnly cookies.
- Generic cross-backend restoration uses `document.cookie`, so it cannot
  restore HttpOnly cookies.
- Domain, SameSite, Secure, expiry, and browser policies may reject individual
  cookies.
- localStorage covers only the current top-level origin at snapshot time, excluding
  other origins, cross-origin frames, sessionStorage, IndexedDB, and Service Workers.
- Resource cache is stored independently and is not part of a login snapshot.

Treat cookie snapshots and runtime files as sensitive data and never commit
them to version control.

## 📦 Persistent resource cache

Install `pip install 'agent-webview[cache]'` with Python 3.12+ (base functionality
still supports 3.10+), or `uv sync --extra dev --extra cache` from source. Create a session:

```json
{
  "url": "https://example.com/",
  "private_mode": true,
  "resource_cache": {
    "enabled": true,
    "extensions": [".js", ".css"],
    "max_age_seconds": 604800,
    "max_resource_bytes": 20971520,
    "max_total_bytes": 536870912
  }
}
```

Caching is disabled by default. Both private and non-private sessions support it;
`private_mode` defaults to `true`. API sessions still use separate processes. Shared resources survive workers and controller restarts in
`<data-dir>/resource-cache/resources.sqlite3`.

Cache hits bypass the network; misses are fetched and saved. Full URLs (including
query, scheme and port) and Vary-selected request headers form the key. Credentials,
Origin and content encoding negotiation are always separated; unrelated headers such
as Referer do not prevent reuse unless named in Vary. CDN resources use their own domains. Only path extensions
`.js` and `.css` are enabled by default. Supply a complete allowlist to include
`.mjs`, `.svg`, `.png` or `.html`; extension matching ignores query strings and case.

This opt-in cache-first policy reuses entries for `max_age_seconds` without server
max-age revalidation. Change versioned URLs, shorten the retention period, or stop
sessions and delete the database to refresh. Only complete GET/200 responses qualify.
Range requests, upgrades, `no-store`, `private`, `Vary: *`, `Set-Cookie`, and oversized
responses are excluded. Defaults are 20 MiB per resource and 512 MiB total entity
bytes; oldest entries are evicted when full. Requests intercepted by a page or
Service Worker do not reach this cache.

A worker-local proxy supports HTTP/HTTPS and existing upstream proxies. Upstream TLS
certificates are still verified; only the current window trusts the temporary CA,
without changes to system trust. Supported backends: macOS 14+ WKWebView and Windows
WebView2. Other backends fail explicitly. Browsers may bypass proxies for loopback
addresses, so localhost caching is not guaranteed. Sites depending on TLS fingerprints
or client certificates may be incompatible with this proxy mode.

Run `uv run --extra cache python scripts/smoke_storage_cache.py` for native smoke checks.

## ⚙️ Configuration

| Option | Default | Description |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Controller bind address |
| `--port` | `8765` | Controller port |
| `--token` | Random | Fixed Bearer token |
| `--data-dir` | Per-user data directory | Cookie snapshot directory |
| `--runtime-dir` | Per-user runtime directory | Worker runtime files |
| `--runtime-file` | Per-user runtime directory | Controller runtime information |
| `--proxy` | Disabled | HTTP(S) proxy for all newly created windows |
| `--allow-remote` | Disabled | Permit binding to a non-loopback address |
| `--log-level` | `info` | Log level |
| `--json-logs` | Disabled | Emit JSON logs |

For a fixed token, prefer the `AGENT_WEBVIEW_TOKEN` environment variable so the
secret does not appear in shell history or process arguments. The global proxy
can also be set with `AGENT_WEBVIEW_PROXY`.

## 🔐 Security

This service lets callers execute arbitrary page JavaScript and may expose
browser cookies. Keep it within these boundaries:

- Run it only on trusted devices and networks.
- Never share runtime files, tokens, or cookie snapshots.
- Proxy sessions send their exit IP to the built-in third-party geolocation
  service.
- The controller binds to loopback by default; non-loopback addresses require
  the explicit `--allow-remote` option.
- Delete sessions when work is complete to release worker processes and WebView
  resources.
- Report vulnerabilities privately according to the
  [security policy](https://github.com/Yuv96/agent-webview/security/policy).

## 📐 Design boundaries

- Private isolation uses one process per session and `private_mode=True`.
- Worker APIs listen only on random loopback ports and use separate internal
  tokens.
- Restarting the controller does not recover running worker sessions.
- DOM `click()` is not equivalent to an operating-system mouse event.
- Screenshots are not currently exposed because pywebview has no uniform
  cross-backend page screenshot API.
- Per-window proxies include a local relay for that session only. This project
  does not provide a public proxy service, proxy IP inventory, or a complete
  browser automation framework.

See the
[API stability policy](https://github.com/Yuv96/agent-webview/blob/main/docs/api-stability.md)
for the compatibility scope and versioning rules.

## 🛠️ Contributing

```bash
git clone https://github.com/Yuv96/agent-webview.git
cd agent-webview
uv sync --extra dev
uv run ruff check src tests scripts
uv run mypy
uv run pytest
uv run python scripts/smoke_service.py
```

Read the
[contribution guide](https://github.com/Yuv96/agent-webview/blob/main/CONTRIBUTING.md)
before submitting a change.

## 📄 License

Agent Webview is released under the
[MIT License](https://github.com/Yuv96/agent-webview/blob/main/LICENSE).
