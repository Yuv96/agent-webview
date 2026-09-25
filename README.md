<div align="center">

# Agent Webview

**面向 AI Agent 的隔离式本地 WebView 调试服务**

通过稳定的 HTTP API 管理隐藏浏览器、检查 DOM、执行 JavaScript，并观察页面事件。

[简体中文](https://github.com/Yuv96/agent-webview/blob/main/README.md) · [English](https://github.com/Yuv96/agent-webview/blob/main/README_EN.md)

[![PyPI](https://img.shields.io/pypi/v/agent-webview?style=flat-square&logo=pypi&logoColor=white)](https://pypi.org/project/agent-webview/)
[![Python](https://img.shields.io/pypi/pyversions/agent-webview?style=flat-square&logo=python&logoColor=white)](https://pypi.org/project/agent-webview/)
[![CI](https://img.shields.io/github/actions/workflow/status/Yuv96/agent-webview/ci.yml?branch=main&style=flat-square&logo=github)](https://github.com/Yuv96/agent-webview/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/Yuv96/agent-webview?style=flat-square)](https://github.com/Yuv96/agent-webview/blob/main/LICENSE)

</div>

> [!NOTE]
> 项目仍处于 `0.x` 预览阶段。CLI、运行信息文件和 `/v1` HTTP API 是当前的
> 公共兼容边界；包内 Python 模块暂不承诺稳定。

## ✨ 核心特性

| 能力 | 说明 |
| --- | --- |
| 进程级隔离 | 每个会话使用独立 pywebview worker 和无痕窗口 |
| Agent 友好 | OpenAPI、结构化 JSON、Bearer Token 和稳定的 `/v1` 接口 |
| 默认隐藏 | 窗口按需显示，适合后台调试和多会话并行 |
| 页面操作 | 支持导航、DOM 查询、输入、点击和 JavaScript 执行 |
| 可观测性 | 支持 DOM 事件、DOM 变更和页面网络活动的长轮询采集 |
| 代理调试 | 支持全局或单窗口 HTTP/HTTPS 代理，并异步查询出口 IP 与归属地 |
| Cookie 快照 | 可保存 Cookie，并在新会话中尽力恢复 |
| 跨平台 | 支持 Windows、macOS 和带 GTK/Qt 后端的 Linux |

## 🧱 工作方式

```text
Agent / Python 脚本
        │
        │ HTTP + Bearer Token
        ▼
agent-webview 控制器
        ├── 独立 worker ── 无痕窗口 A
        ├── 独立 worker ── 无痕窗口 B
        └── 独立 worker ── 无痕窗口 C
```

控制器本身不创建可见窗口。`POST /v1/sessions` 每次启动一个新的 worker
进程；会话内的后续请求复用同一窗口，直到会话被删除。

## 📦 安装

需要 Python 3.10 或更高版本。

```bash
python -m pip install agent-webview
```

在 `requirements.txt` 中建议限制在同一次版本系列：

```text
agent-webview~=0.1.0
```

发行包名、Python 模块名和命令名分别是：

- `pip install agent-webview`
- `import agent_webview`
- `agent-webview`

### 平台依赖

| 平台 | WebView 后端 |
| --- | --- |
| Windows | WebView2；现代 Windows 通常已预装 WebView2 Runtime |
| macOS | 系统 WebKit |
| Linux | 安装 `agent-webview[linux-gtk]` 或 `agent-webview[linux-qt]` |

## 🚀 快速开始

### 1. 启动控制器

```bash
agent-webview
```

默认监听 `http://127.0.0.1:8765`。启动后会生成一份运行信息 JSON，包含服务
地址、进程号、OpenAPI 地址和随机 Bearer Token。查询该文件的位置：

```bash
agent-webview --print-runtime-file
```

默认数据位于操作系统的当前用户数据目录，不会写入当前项目目录。需要自定义位置时：

```bash
agent-webview \
  --data-dir ./webview-data \
  --runtime-file ./agent-webview-runtime.json
```

需要让该控制器创建的所有窗口都使用同一代理时，在启动时声明：

```bash
agent-webview --proxy http://127.0.0.1:7890
```

### 2. 创建并控制会话

下面的 Python 示例读取运行信息、创建隐藏会话、等待窗口就绪，然后读取页面标题：

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
        raise TimeoutError("浏览器窗口未就绪")

    result = client.post(
        f"/v1/sessions/{session_id}/javascript/evaluate",
        json={"code": "document.title", "timeout": 10},
    ).raise_for_status().json()
    print(result["value"])

    client.delete(f"/v1/sessions/{session_id}").raise_for_status()
```

服务启动后也可以直接打开运行信息中的 `docs_url`，或访问 `/docs` 和
`/openapi.json` 查看完整接口定义。

## 🔌 主要接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/v1/sessions` | 创建独立无痕会话 |
| `GET` | `/v1/sessions` | 列出会话和进程信息 |
| `GET` | `/v1/sessions/{id}` | 获取窗口、句柄和进程状态 |
| `GET` | `/v1/sessions/{id}/proxy` | 查询代理配置、出口 IP 和归属地 |
| `DELETE` | `/v1/sessions/{id}` | 销毁会话 |
| `POST` | `/v1/sessions/{id}/navigate` | 导航到新地址 |
| `POST` | `/v1/sessions/{id}/javascript/evaluate` | 执行表达式并返回结果 |
| `POST` | `/v1/sessions/{id}/javascript/execute` | 执行 JavaScript 语句 |
| `POST` | `/v1/sessions/{id}/dom/query` | 查询 DOM 元素 |
| `POST` | `/v1/sessions/{id}/dom/input` | 设置输入值并触发事件 |
| `POST` | `/v1/sessions/{id}/dom/click` | 调用元素的 DOM `click()` |
| `POST` | `/v1/sessions/{id}/dom/listeners` | 添加 DOM 事件监听 |
| `PUT` | `/v1/sessions/{id}/instrumentation` | 配置网络和 DOM 探针 |
| `GET` | `/v1/sessions/{id}/events` | 长轮询获取事件 |
| `GET` | `/v1/sessions/{id}/cookies` | 获取 Cookie |
| `POST` | `/v1/sessions/{id}/cookie-snapshots` | 保存 Cookie 快照 |
| `GET` | `/v1/cookie-snapshots` | 列出 Cookie 快照 |
| `POST` | `/v1/sessions/{id}/window/show` | 显示窗口 |
| `POST` | `/v1/sessions/{id}/window/hide` | 隐藏窗口 |

创建会话后，响应会提供：

- `session_id`：控制器会话标识。
- `window_id`：服务生成的稳定窗口标识。
- `native_window_id`：GUI 后端提供的原生窗口句柄，窗口未创建时可能为 `null`。
- `pid`：实际 pywebview worker 进程号。
- `launcher_pid`：部分 Windows 虚拟环境中的启动器进程号，否则为 `null`。

## 🌐 代理调试

控制器启动时传入 `--proxy` 会设置全局代理，之后创建的所有窗口都会使用它，直到
控制器进程退出。没有全局代理时，可以只为某个窗口在创建请求中传入 `proxy`：

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

全局代理优先于创建请求中的窗口代理，保证该控制器下的所有窗口使用同一代理。
代理地址支持 `http://` 和 `https://`，暂不支持 SOCKS、用户名密码认证、路径或查询
参数。Windows 需要 WebView2；macOS 的原生代理能力需要 macOS 14 或更高版本。

窗口会立即加载目标页面。出口 IP 与归属地由后台线程通过固定的第三方服务查询，
不会等待查询结束才放行 WebView。查询成功后，可见窗口标题会变为类似：

```text
[203.0.113.8 · 上海] Agent Webview
```

归属地仅保留城市；查询结果没有城市时，标题只显示出口 IP。

隐藏窗口或程序化调用应使用独立状态接口：

```python
proxy = client.get(
    f"/v1/sessions/{session_id}/proxy",
    params={"timeout": 10},
).raise_for_status().json()

if proxy["state"] == "active":
    print(proxy["server"], proxy["ip"], proxy["location"])
```

`timeout` 默认为 `0`，此时立即返回；可设置为最多 30 秒，仅让这一次状态请求等待
后台查询，不影响 WebView。响应中的状态含义如下：

- `disabled`：该窗口没有声明代理。
- `checking`：窗口已按代理配置启动，出口信息仍在后台查询。
- `active`：固定查询服务已通过该代理成功返回出口 IP 和归属地。
- `unavailable`：本次查询没有结果；页面继续正常工作，该状态本身不能断定代理失败。

查询完成时也会产生 `proxy` 事件，可通过现有事件长轮询接口监听。查询服务地址固定
在实现内部，不接受 CLI 或 HTTP API 覆盖。

## 🔎 页面观测

通过 `PUT /v1/sessions/{id}/instrumentation` 可以开启：

- `network`：采集页面内的 `fetch`、`XMLHttpRequest`、WebSocket 和
  Performance Resource 记录。
- `mutations`：采集 DOM 变更，可用 `mutation_selector` 缩小范围。
- `capture_request_bodies` / `capture_response_bodies`：按需采集请求或响应体。

随后使用 `GET /v1/sessions/{id}/events?after=0&timeout=20` 长轮询事件，下一次
请求将返回的 `latest_sequence` 作为 `after`。`kinds` 参数可过滤
`dom`、`network`、`mutation`、`lifecycle` 和 `proxy`。

网络探针不是浏览器底层代理，不能保证捕获 Service Worker、缓存命中、扩展流量
或所有响应体。需要协议级调试时，可以在创建会话时设置
`remote_debugging_port`，并使用后端支持的 DevTools 协议。

## 🍪 Cookie 快照

Cookie 快照默认保存在当前用户数据目录，也可以通过 `--data-dir` 指定位置。创建
新会话时传入 `snapshot_id` 即可尝试恢复；请求中显式提供的 `cookies` 会覆盖快照
内同名、同域、同路径的 Cookie。

恢复存在浏览器后端限制：

- pywebview 可以读取包含 HttpOnly 在内的 Cookie。
- 通用跨后端恢复依赖 `document.cookie`，因此无法恢复 HttpOnly Cookie。
- Domain、SameSite、Secure、过期时间和浏览器策略可能拒绝部分 Cookie。
- 快照不包含 IndexedDB、Local Storage、Service Worker 或缓存。

Cookie 快照和运行信息文件都应按敏感数据处理，不应提交到版本控制系统。

## ⚙️ 常用配置

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 控制器监听地址 |
| `--port` | `8765` | 控制器监听端口 |
| `--token` | 随机生成 | 固定 Bearer Token |
| `--data-dir` | 当前用户数据目录 | Cookie 快照目录 |
| `--runtime-dir` | 当前用户运行目录 | worker 运行文件目录 |
| `--runtime-file` | 当前用户运行目录 | 控制器运行信息文件 |
| `--proxy` | 关闭 | 所有新窗口使用的 HTTP/HTTPS 代理 |
| `--allow-remote` | 关闭 | 允许监听非本机地址 |
| `--log-level` | `info` | 日志级别 |
| `--json-logs` | 关闭 | 输出 JSON 日志 |

固定 Token 时优先使用 `AGENT_WEBVIEW_TOKEN` 环境变量，避免令牌出现在命令历史
和进程参数中。全局代理也可以通过 `AGENT_WEBVIEW_PROXY` 设置。

## 🔐 安全说明

本服务允许调用方执行任意页面 JavaScript，并可能读取浏览器 Cookie。请遵守以下
边界：

- 只在可信设备和可信网络中运行。
- 不要共享运行信息文件、Token 或 Cookie 快照。
- 代理窗口会把出口 IP 发送给内置的第三方归属地查询服务。
- 默认只监听本机；非本机地址必须显式传入 `--allow-remote`。
- 任务结束后删除会话，释放 worker 进程和 WebView 资源。
- 安全问题请按照[安全策略](https://github.com/Yuv96/agent-webview/security/policy)私下报告。

## 📐 设计边界

- 无痕隔离依靠“一会话一进程”和 `private_mode=True`。
- 所有 worker 接口只监听随机本机端口，并使用独立内部令牌。
- 控制器重启不会恢复仍在运行的 worker 会话。
- DOM `click()` 不等同于操作系统级鼠标事件。
- 当前不提供截图接口，因为 pywebview 没有统一的跨后端页面截图 API。
- 该项目可以把 WebView 流量转交给已有代理，但本身不是代理服务器，也不是完整的
  浏览器自动化框架。

公共兼容范围和版本规则见
[API 稳定性说明](https://github.com/Yuv96/agent-webview/blob/main/docs/api-stability.md)。

## 🛠️ 参与开发

```bash
git clone https://github.com/Yuv96/agent-webview.git
cd agent-webview
uv sync --extra dev
uv run ruff check src tests scripts
uv run mypy
uv run pytest
uv run python scripts/smoke_service.py
```

提交代码前请阅读
[贡献指南](https://github.com/Yuv96/agent-webview/blob/main/CONTRIBUTING.md)。

## 📄 License

本项目基于 [MIT License](https://github.com/Yuv96/agent-webview/blob/main/LICENSE)
发布。
