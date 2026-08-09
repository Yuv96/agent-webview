# Agent Webview

一个面向 Agent 的本地网页调试服务。控制器通过 HTTP 管理多个独立的
pywebview worker 进程，每个调试会话都使用全新的无痕浏览器进程。

## 核心行为

- 控制器本身不创建可见窗口。
- `POST /v1/sessions` 每次创建一个新的 worker 进程和无痕窗口。
- 新窗口默认隐藏，设置 `visible: true` 才会显示。
- 每个会话返回 `session_id`、`window_id`、`native_window_id` 和 `pid`。
- 多个 Agent 可以创建多个会话并行调试，彼此不共享进程内 Cookie。
- 会话内的后续 HTTP 操作复用该窗口，直到删除会话。
- Cookie 快照保存为 JSON，可在新会话中尽力恢复。
- `/docs` 和 `/openapi.json` 可供 Agent 自动发现接口。

## 安装

需要 Python 3.10 或更高版本。

```bash
python -m pip install agent-webview
```

项目的 `requirements.txt` 建议固定在同一次版本系列：

```text
agent-webview~=0.1.0
```

正式发布前也可以固定到独立仓库的不可变提交：

```text
agent-webview @ git+https://github.com/Yuv96/agent-webview.git@COMMIT_SHA
```

发行包名、Python 模块名和命令名分别是：

- `pip install agent-webview`
- `import agent_webview`
- `agent-webview`

平台说明：

- Windows 使用 WebView2，需要已安装 WebView2 Runtime；现代 Windows 通常已自带。
- macOS 使用系统 WebKit。
- Linux 需要自行选择 pywebview 后端，例如
  `pip install "agent-webview[linux-gtk]"` 或
  `pip install "agent-webview[linux-qt]"`。

## 启动

```powershell
agent-webview
```

默认监听 `http://127.0.0.1:8765`。服务会生成包含地址、进程号和 Bearer Token
的运行信息文件。默认文件位于操作系统的
当前用户运行目录，不会写入业务项目。可用下面的命令查询路径：

```powershell
agent-webview --print-runtime-file
```

需要项目自定义路径时显式传入：

```powershell
agent-webview --runtime-file .agent-webview-runtime.json
```

不要把服务直接暴露到不可信网络。调试接口允许执行任意页面 JavaScript，
Cookie 快照也可能包含敏感信息。默认只允许监听本机地址；监听其他地址必须同时
传入 `--allow-remote`。固定令牌时优先使用 `AGENT_WEBVIEW_TOKEN` 环境变量，
避免令牌出现在命令历史和进程参数中。

## Agent 快速流程

以下 PowerShell 示例先读取运行信息：

```powershell
$runtimeFile = agent-webview --print-runtime-file
$runtime = Get-Content $runtimeFile | ConvertFrom-Json
$headers = @{ Authorization = "Bearer $($runtime.token)" }
$base = $runtime.base_url
```

### 1. 创建隐藏的隔离会话

```powershell
$session = Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body (@{
    url = "https://example.com"
    visible = $false
  } | ConvertTo-Json)

$sid = $session.session_id
```

响应包含：

```json
{
  "session_id": "会话标识",
  "window_id": "稳定窗口标识",
  "pid": 12345,
  "launcher_pid": 12340,
  "state": "running",
  "window": {
    "native_window_id": 67890,
    "ready": true,
    "visible": false,
    "url": "https://example.com/"
  }
}
```

`pid` 是实际 pywebview worker 进程。Windows 虚拟环境启动器产生额外进程时，
`launcher_pid` 会返回启动器进程号，否则为 `null`。

创建响应中的 `window` 可能暂时为 `null`。轮询
`GET /v1/sessions/{session_id}`，直到 `window.ready` 为 `true`。

### 2. 查询 DOM

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions/$sid/dom/query" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"selector":"a","limit":20}'
```

### 3. 模拟输入和点击

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions/$sid/dom/input" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"selector":"input[name=q]","value":"pywebview"}'

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions/$sid/dom/click" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"selector":"button[type=submit]"}'
```

输入操作会设置元素值，并触发冒泡的 `input` 和 `change` 事件。点击操作使用
DOM `click()`，不等同于操作系统级鼠标事件。

### 4. 注入 JavaScript

返回表达式结果：

```powershell
$body = @{
  code = "({title: document.title, url: location.href})"
  timeout = 30
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions/$sid/javascript/evaluate" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

执行语句：

```powershell
$body = @{
  code = "document.body.dataset.agent = 'ready';"
  timeout = 30
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions/$sid/javascript/execute" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

### 5. 监听 DOM 事件

```powershell
$listener = @{
  id = "submit-watch"
  selector = "form"
  event = "submit"
  capture = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions/$sid/dom/listeners" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $listener
```

### 6. 监听 DOM 变更和页面网络

```powershell
$instrumentation = @{
  network = $true
  mutations = $true
  mutation_selector = "body"
  capture_request_bodies = $false
  capture_response_bodies = $false
  max_body_chars = 20000
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Put `
  -Uri "$base/v1/sessions/$sid/instrumentation" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $instrumentation
```

长轮询事件：

```powershell
$events = Invoke-RestMethod `
  -Method Get `
  -Uri "$base/v1/sessions/$sid/events?after=0&timeout=20" `
  -Headers $headers

$next = $events.latest_sequence
```

下一次使用 `after=$next`。`kinds=dom,network,mutation,lifecycle` 可以过滤类型。

网络探针覆盖页面内的 `fetch`、`XMLHttpRequest`、WebSocket 和
Performance Resource 记录。它不是浏览器底层代理，不能保证拿到
Service Worker、缓存命中、扩展流量或所有响应体。需要完整协议级调试时，创建会话时设置
`remote_debugging_port`，并使用 WebView2 或 Qt 的 DevTools 协议。

### 7. 保存 Cookie 快照

```powershell
$snapshot = Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions/$sid/cookie-snapshots" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"name":"登录后状态"}'
```

快照默认保存在操作系统的当前用户数据目录。也可以通过 `--data-dir` 指定目录。

### 8. 用快照创建新无痕会话

```powershell
$body = @{
  url = "https://example.com/account"
  snapshot_id = $snapshot.snapshot_id
  visible = $false
} | ConvertTo-Json

$restored = Invoke-RestMethod `
  -Method Post `
  -Uri "$base/v1/sessions" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

请求中的 `cookies` 会覆盖快照内同名、同域和同路径的 Cookie。

Cookie 恢复是尽力行为：

- pywebview 可以读取包含 HttpOnly 在内的 Cookie。
- 通用跨后端恢复通过 `document.cookie` 完成，无法恢复 HttpOnly Cookie。
- Domain、SameSite、Secure、过期时间和浏览器策略可能拒绝部分 Cookie。
- 只保存 Cookie，不保存 IndexedDB、Local Storage、Service Worker 或缓存。

### 9. 显示、隐藏和销毁

```powershell
Invoke-RestMethod -Method Post -Uri "$base/v1/sessions/$sid/window/show" -Headers $headers
Invoke-RestMethod -Method Post -Uri "$base/v1/sessions/$sid/window/hide" -Headers $headers
Invoke-RestMethod -Method Delete -Uri "$base/v1/sessions/$sid" -Headers $headers
```

Agent 应在任务结束时删除会话，释放 worker 进程和 WebView2 资源。

## 主要接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/v1/sessions` | 创建独立无痕会话 |
| `GET` | `/v1/sessions` | 列出会话和进程信息 |
| `GET` | `/v1/sessions/{id}` | 获取窗口、句柄和进程状态 |
| `DELETE` | `/v1/sessions/{id}` | 销毁会话 |
| `POST` | `/v1/sessions/{id}/navigate` | 导航 |
| `POST` | `/v1/sessions/{id}/javascript/evaluate` | 执行表达式并返回结果 |
| `POST` | `/v1/sessions/{id}/javascript/execute` | 执行语句 |
| `POST` | `/v1/sessions/{id}/dom/query` | 查询元素 |
| `POST` | `/v1/sessions/{id}/dom/input` | 输入 |
| `POST` | `/v1/sessions/{id}/dom/click` | 点击 |
| `POST` | `/v1/sessions/{id}/dom/listeners` | 添加事件监听 |
| `PUT` | `/v1/sessions/{id}/instrumentation` | 配置网络和 DOM 探针 |
| `GET` | `/v1/sessions/{id}/events` | 获取事件 |
| `GET` | `/v1/sessions/{id}/cookies` | 获取 Cookie |
| `POST` | `/v1/sessions/{id}/cookie-snapshots` | 保存 Cookie 快照 |
| `GET` | `/v1/cookie-snapshots` | 列出 Cookie 快照 |

## 设计边界

- 无痕隔离依靠“一会话一进程”和 `private_mode=True`。
- `window_id` 是服务生成的稳定标识。
- `native_window_id` 依赖 GUI 后端，窗口尚未创建时可能为 `null`。
- 所有 worker 接口仅监听随机本机端口，并使用独立内部令牌。
- 控制器重启不会恢复运行中的 worker 会话。
- 当前不提供截图接口，因为 pywebview 没有统一的跨后端页面截图 API。
- 公共兼容契约是 `agent-webview` CLI、运行信息文件和控制器 `/v1` HTTP API。
- `agent_webview` 包内的其他 Python 模块暂不属于稳定公共 API。

具体兼容策略见
[`docs/api-stability.md`](https://github.com/Yuv96/agent-webview/blob/main/docs/api-stability.md)。

## 本地开发

```bash
uv sync --extra dev
uv run ruff check src tests
uv run mypy
uv run pytest
python scripts/release_check.py
uv run python scripts/smoke_service.py
```

发布流程见
[`RELEASING.md`](https://github.com/Yuv96/agent-webview/blob/main/RELEASING.md)。
