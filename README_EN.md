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
| Cookie snapshots | Save cookies and make a best-effort restore in a new session |
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
`https://`. SOCKS, username/password authentication, paths, and query strings
are not currently supported. Windows requires WebView2, and native proxy
configuration on macOS requires macOS 14 or later.

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

Completion also emits a `proxy` event through the existing event stream. The
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

## 🍪 Cookie snapshots

Cookie snapshots are stored in the per-user data directory by default; use
`--data-dir` to choose another location. Pass a `snapshot_id` when creating a
new session to attempt a restore. Explicit `cookies` in the request override
snapshot cookies with the same name, domain, and path.

Restoration is subject to browser backend limitations:

- pywebview can read cookies, including HttpOnly cookies.
- Generic cross-backend restoration uses `document.cookie`, so it cannot
  restore HttpOnly cookies.
- Domain, SameSite, Secure, expiry, and browser policies may reject individual
  cookies.
- Snapshots do not contain IndexedDB, Local Storage, Service Workers, or cache.

Treat cookie snapshots and runtime files as sensitive data and never commit
them to version control.

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
- This project can route WebView traffic to an existing proxy, but it is not a
  proxy server or a complete browser automation framework.

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
