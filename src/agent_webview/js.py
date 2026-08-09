from __future__ import annotations

import json
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


TRANSPORT_HELPERS = r"""
const __agentSnapshot = (element) => {
  if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  const attributes = {};
  for (const item of Array.from(element.attributes || [])) {
    attributes[item.name] = item.value;
  }
  return {
    tag: element.tagName.toLowerCase(),
    id: element.id || null,
    classes: Array.from(element.classList || []),
    text: (element.innerText ?? element.textContent ?? "").slice(0, 4000),
    value: "value" in element ? element.value : null,
    checked: "checked" in element ? Boolean(element.checked) : null,
    disabled: "disabled" in element ? Boolean(element.disabled) : null,
    attributes,
    visible: Boolean(
      rect.width || rect.height || element.getClientRects().length
    ) && style.visibility !== "hidden" && style.display !== "none",
    rect: {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      left: rect.left
    }
  };
};

const __agentTransport = (value, depth = 0, seen = new WeakSet()) => {
  if (value === undefined) return {__type: "undefined"};
  if (value === null || typeof value === "string" ||
      typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "bigint") return {__type: "bigint", value: String(value)};
  if (typeof value === "function") return {__type: "function", name: value.name || null};
  if (value instanceof Element) return {__type: "element", value: __agentSnapshot(value)};
  if (value instanceof Error) {
    return {__type: "error", name: value.name, message: value.message, stack: value.stack || null};
  }
  if (value instanceof Date) return {__type: "date", value: value.toISOString()};
  if (value instanceof Headers) return Object.fromEntries(value.entries());
  if (value instanceof URL) return String(value);
  if (depth >= 6) return {__type: "truncated", reason: "max-depth"};
  if (typeof value === "object") {
    if (seen.has(value)) return {__type: "circular"};
    seen.add(value);
  }
  if (Array.isArray(value)) {
    return value.slice(0, 500).map((item) => __agentTransport(item, depth + 1, seen));
  }
  if (value instanceof Map) {
    return Object.fromEntries(
      Array.from(value.entries()).slice(0, 500).map(
        ([key, item]) => [String(key), __agentTransport(item, depth + 1, seen)]
      )
    );
  }
  if (value instanceof Set) {
    return Array.from(value.values()).slice(0, 500).map(
      (item) => __agentTransport(item, depth + 1, seen)
    );
  }
  const result = {};
  for (const key of Object.keys(value).slice(0, 500)) {
    try {
      result[key] = __agentTransport(value[key], depth + 1, seen);
    } catch (error) {
      result[key] = {__type: "unreadable", message: String(error)};
    }
  }
  return result;
};
"""


def command_script(request_id: str, code: str, *, expression: bool) -> str:
    operation = f"const __agentValue = await ({code});" if expression else f"{code}\nconst __agentValue = null;"
    return f"""
(async () => {{
  const __agentRequestId = {_json(request_id)};
  const __agentWaitForBridge = async () => {{
    if (window.pywebview?.api?.agent_result) return;
    await new Promise((resolve, reject) => {{
      const timeout = setTimeout(
        () => reject(new Error("pywebview 桥接未就绪")),
        5000
      );
      document.addEventListener("pywebviewready", () => {{
        clearTimeout(timeout);
        resolve();
      }}, {{once: true}});
    }});
  }};
  {TRANSPORT_HELPERS}
  try {{
    {operation}
    await __agentWaitForBridge();
    await window.pywebview.api.agent_result(__agentRequestId, {{
      ok: true,
      value: __agentTransport(__agentValue)
    }});
  }} catch (error) {{
    try {{
      await __agentWaitForBridge();
      await window.pywebview.api.agent_result(__agentRequestId, {{
        ok: false,
        error: {{
          name: error?.name || "Error",
          message: error?.message || String(error),
          stack: error?.stack || null
        }}
      }});
    }} catch (_) {{}}
  }}
}})();
"""


def dom_query_expression(selector: str, limit: int) -> str:
    return f"""(() => {{
  const selector = {_json(selector)};
  const limit = {_json(max(1, min(limit, 500)))};
  return Array.from(document.querySelectorAll(selector))
    .slice(0, limit)
    .map((element, index) => ({{index, ...__agentSnapshot(element)}}));
}})()"""


def dom_click_expression(selector: str, index: int, scroll: bool) -> str:
    return f"""(() => {{
  const elements = document.querySelectorAll({_json(selector)});
  const element = elements[{max(0, index)}];
  if (!element) throw new Error("未找到目标元素");
  if ({_json(scroll)}) element.scrollIntoView({{block: "center", inline: "center"}});
  element.focus?.();
  element.click();
  return __agentSnapshot(element);
}})()"""


def dom_input_expression(selector: str, value: str, index: int) -> str:
    return f"""(() => {{
  const elements = document.querySelectorAll({_json(selector)});
  const element = elements[{max(0, index)}];
  if (!element) throw new Error("未找到目标元素");
  if (!("value" in element)) throw new Error("目标元素不支持输入");
  element.focus?.();
  const prototype = Object.getPrototypeOf(element);
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (descriptor?.set) descriptor.set.call(element, {_json(value)});
  else element.value = {_json(value)};
  element.dispatchEvent(new InputEvent("input", {{
    bubbles: true,
    composed: true,
    inputType: "insertText",
    data: {_json(value)}
  }}));
  element.dispatchEvent(new Event("change", {{bubbles: true, composed: true}}));
  return __agentSnapshot(element);
}})()"""


def dom_dispatch_expression(
    selector: str,
    event_type: str,
    index: int,
    detail: Any,
) -> str:
    return f"""(() => {{
  const elements = document.querySelectorAll({_json(selector)});
  const element = elements[{max(0, index)}];
  if (!element) throw new Error("未找到目标元素");
  const event = new CustomEvent({_json(event_type)}, {{
    bubbles: true,
    cancelable: true,
    composed: true,
    detail: {_json(detail)}
  }});
  const accepted = element.dispatchEvent(event);
  return {{accepted, element: __agentSnapshot(element)}};
}})()"""


def dom_listener_script(listener: dict[str, Any]) -> str:
    return f"""
(() => {{
  {TRANSPORT_HELPERS}
  const config = {_json(listener)};
  const state = window.__agentWebview = window.__agentWebview || {{}};
  state.domListeners = state.domListeners || {{}};
  const previous = state.domListeners[config.id];
  if (previous) document.removeEventListener(previous.event, previous.handler, previous.capture);
  let lastSentAt = 0;
  const handler = (event) => {{
    const target = event.target?.closest?.(config.selector);
    if (!target) return;
    const now = Date.now();
    if (config.debounce_ms && now - lastSentAt < config.debounce_ms) return;
    lastSentAt = now;
    const payload = {{
      kind: "dom",
      listener_id: config.id,
      event: config.event,
      url: location.href,
      target: __agentSnapshot(target),
      data: {{
        key: event.key ?? null,
        code: event.code ?? null,
        button: event.button ?? null,
        clientX: event.clientX ?? null,
        clientY: event.clientY ?? null,
        inputType: event.inputType ?? null,
        data: event.data ?? null,
        isTrusted: Boolean(event.isTrusted),
        defaultPrevented: Boolean(event.defaultPrevented)
      }}
    }};
    window.pywebview?.api?.agent_event(payload).catch(() => {{}});
  }};
  document.addEventListener(config.event, handler, config.capture);
  state.domListeners[config.id] = {{
    event: config.event,
    capture: config.capture,
    handler
  }};
}})();
"""


def remove_dom_listener_script(listener_id: str) -> str:
    return f"""
(() => {{
  const state = window.__agentWebview;
  const listener = state?.domListeners?.[{_json(listener_id)}];
  if (!listener) return;
  document.removeEventListener(listener.event, listener.handler, listener.capture);
  delete state.domListeners[{_json(listener_id)}];
}})();
"""


def cookie_restore_expression(cookies: list[dict[str, Any]]) -> str:
    return f"""(() => {{
  const cookies = {_json(cookies)};
  const restored = [];
  const skipped = [];
  for (const cookie of cookies) {{
    if (cookie.http_only) {{
      skipped.push({{name: cookie.name, reason: "JavaScript 无法设置 HttpOnly"}});
      continue;
    }}
    const parts = [`${{cookie.name}}=${{cookie.value}}`];
    if (cookie.path) parts.push(`Path=${{cookie.path}}`);
    if (cookie.domain) parts.push(`Domain=${{cookie.domain}}`);
    if (cookie.expires) {{
      const expires = typeof cookie.expires === "number"
        ? new Date(cookie.expires * 1000).toUTCString()
        : cookie.expires;
      parts.push(`Expires=${{expires}}`);
    }}
    if (cookie.secure) parts.push("Secure");
    if (cookie.same_site) parts.push(`SameSite=${{cookie.same_site}}`);
    try {{
      document.cookie = parts.join("; ");
      const visible = document.cookie.split(/;\\s*/).some(
        (item) => item.startsWith(`${{cookie.name}}=`)
      );
      if (visible) restored.push(cookie.name);
      else skipped.push({{name: cookie.name, reason: "浏览器拒绝或隐藏了 Cookie"}});
    }} catch (error) {{
      skipped.push({{name: cookie.name, reason: String(error)}});
    }}
  }}
  return {{restored, skipped, document_cookie: document.cookie}};
}})()"""


def instrumentation_script(config: dict[str, Any]) -> str:
    return f"""
(() => {{
  {TRANSPORT_HELPERS}
  const config = {_json(config)};
  const state = window.__agentWebview = window.__agentWebview || {{}};
  state.instrumentation = state.instrumentation || {{}};
  state.instrumentation.config = config;
  const emit = (payload) => {{
    window.pywebview?.api?.agent_event(payload).catch(() => {{}});
  }};
  const truncate = (value) => {{
    if (value == null) return null;
    const text = String(value);
    return text.length > config.max_body_chars
      ? text.slice(0, config.max_body_chars) + "...[truncated]"
      : text;
  }};
  const headersObject = (headers) => {{
    try {{ return Object.fromEntries(new Headers(headers || {{}}).entries()); }}
    catch (_) {{ return {{}}; }}
  }};

  if (!state.instrumentation.fetchInstalled && window.fetch) {{
    state.instrumentation.fetchInstalled = true;
    const originalFetch = window.fetch.bind(window);
    state.instrumentation.originalFetch = originalFetch;
    window.fetch = async function(input, init = undefined) {{
      const current = state.instrumentation.config;
      if (!current.network) return originalFetch(input, init);
      const requestId = crypto.randomUUID?.() || Math.random().toString(36).slice(2);
      const started = performance.now();
      const url = typeof input === "string" ? input : input?.url || String(input);
      const method = init?.method || input?.method || "GET";
      emit({{
        kind: "network",
        phase: "request",
        transport: "fetch",
        request_id: requestId,
        url,
        method,
        headers: headersObject(init?.headers || input?.headers),
        body: current.capture_request_bodies ? truncate(init?.body) : null,
        timestamp: Date.now()
      }});
      try {{
        const response = await originalFetch(input, init);
        emit({{
          kind: "network",
          phase: "response",
          transport: "fetch",
          request_id: requestId,
          url: response.url || url,
          method,
          status: response.status,
          ok: response.ok,
          redirected: response.redirected,
          headers: headersObject(response.headers),
          duration_ms: performance.now() - started,
          timestamp: Date.now()
        }});
        if (current.capture_response_bodies) {{
          response.clone().text().then((body) => emit({{
            kind: "network",
            phase: "response-body",
            transport: "fetch",
            request_id: requestId,
            url: response.url || url,
            body: truncate(body),
            timestamp: Date.now()
          }})).catch(() => {{}});
        }}
        return response;
      }} catch (error) {{
        emit({{
          kind: "network",
          phase: "error",
          transport: "fetch",
          request_id: requestId,
          url,
          method,
          error: String(error),
          duration_ms: performance.now() - started,
          timestamp: Date.now()
        }});
        throw error;
      }}
    }};
  }}

  if (!state.instrumentation.xhrInstalled && window.XMLHttpRequest) {{
    state.instrumentation.xhrInstalled = true;
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {{
      this.__agentMeta = {{
        request_id: crypto.randomUUID?.() || Math.random().toString(36).slice(2),
        method,
        url: String(url),
        headers: {{}}
      }};
      return originalOpen.call(this, method, url, ...rest);
    }};
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {{
      if (this.__agentMeta) this.__agentMeta.headers[name] = value;
      return originalSetRequestHeader.call(this, name, value);
    }};
    XMLHttpRequest.prototype.send = function(body) {{
      const current = state.instrumentation.config;
      const meta = this.__agentMeta || {{
        request_id: Math.random().toString(36).slice(2),
        method: "GET",
        url: "",
        headers: {{}}
      }};
      if (current.network) {{
        meta.started = performance.now();
        emit({{
          kind: "network",
          phase: "request",
          transport: "xhr",
          request_id: meta.request_id,
          url: meta.url,
          method: meta.method,
          headers: meta.headers,
          body: current.capture_request_bodies ? truncate(body) : null,
          timestamp: Date.now()
        }});
        this.addEventListener("loadend", () => {{
          let responseHeaders = {{}};
          try {{
            for (const line of this.getAllResponseHeaders().trim().split(/[\\r\\n]+/)) {{
              if (!line) continue;
              const index = line.indexOf(":");
              responseHeaders[line.slice(0, index).trim()] = line.slice(index + 1).trim();
            }}
          }} catch (_) {{}}
          emit({{
            kind: "network",
            phase: "response",
            transport: "xhr",
            request_id: meta.request_id,
            url: this.responseURL || meta.url,
            method: meta.method,
            status: this.status,
            headers: responseHeaders,
            body: current.capture_response_bodies && typeof this.responseText === "string"
              ? truncate(this.responseText)
              : null,
            duration_ms: performance.now() - meta.started,
            timestamp: Date.now()
          }});
        }}, {{once: true}});
      }}
      return originalSend.call(this, body);
    }};
  }}

  if (!state.instrumentation.webSocketInstalled && window.WebSocket) {{
    state.instrumentation.webSocketInstalled = true;
    const OriginalWebSocket = window.WebSocket;
    const WrappedWebSocket = function(url, protocols) {{
      const socket = protocols === undefined
        ? new OriginalWebSocket(url)
        : new OriginalWebSocket(url, protocols);
      const requestId = crypto.randomUUID?.() || Math.random().toString(36).slice(2);
      const currentConfig = () => state.instrumentation.config;
      emit({{
        kind: "network",
        phase: "connect",
        transport: "websocket",
        request_id: requestId,
        url: String(url),
        protocols: protocols || null,
        timestamp: Date.now()
      }});
      socket.addEventListener("open", () => {{
        if (!currentConfig().network) return;
        emit({{
          kind: "network",
          phase: "open",
          transport: "websocket",
          request_id: requestId,
          url: socket.url,
          protocol: socket.protocol || null,
          timestamp: Date.now()
        }});
      }});
      socket.addEventListener("message", (event) => {{
        const current = currentConfig();
        if (!current.network) return;
        emit({{
          kind: "network",
          phase: "message",
          direction: "received",
          transport: "websocket",
          request_id: requestId,
          url: socket.url,
          body: current.capture_response_bodies ? truncate(event.data) : null,
          timestamp: Date.now()
        }});
      }});
      socket.addEventListener("error", () => {{
        if (!currentConfig().network) return;
        emit({{
          kind: "network",
          phase: "error",
          transport: "websocket",
          request_id: requestId,
          url: socket.url,
          timestamp: Date.now()
        }});
      }});
      socket.addEventListener("close", (event) => {{
        if (!currentConfig().network) return;
        emit({{
          kind: "network",
          phase: "close",
          transport: "websocket",
          request_id: requestId,
          url: socket.url,
          code: event.code,
          reason: event.reason || null,
          clean: event.wasClean,
          timestamp: Date.now()
        }});
      }});
      const originalSend = socket.send.bind(socket);
      socket.send = (data) => {{
        const current = currentConfig();
        if (current.network) {{
          emit({{
            kind: "network",
            phase: "message",
            direction: "sent",
            transport: "websocket",
            request_id: requestId,
            url: socket.url,
            body: current.capture_request_bodies ? truncate(data) : null,
            timestamp: Date.now()
          }});
        }}
        return originalSend(data);
      }};
      return socket;
    }};
    WrappedWebSocket.prototype = OriginalWebSocket.prototype;
    Object.setPrototypeOf(WrappedWebSocket, OriginalWebSocket);
    window.WebSocket = WrappedWebSocket;
  }}

  if (!state.instrumentation.resourceObserver && window.PerformanceObserver) {{
    try {{
      const observer = new PerformanceObserver((list) => {{
        const current = state.instrumentation.config;
        if (!current.network) return;
        for (const entry of list.getEntries()) {{
          emit({{
            kind: "network",
            phase: "resource",
            transport: entry.initiatorType || "resource",
            url: entry.name,
            duration_ms: entry.duration,
            transfer_size: entry.transferSize ?? null,
            encoded_body_size: entry.encodedBodySize ?? null,
            decoded_body_size: entry.decodedBodySize ?? null,
            timestamp: Date.now()
          }});
        }}
      }});
      observer.observe({{type: "resource", buffered: true}});
      state.instrumentation.resourceObserver = observer;
    }} catch (_) {{}}
  }}

  if (state.instrumentation.mutationObserver) {{
    state.instrumentation.mutationObserver.disconnect();
    state.instrumentation.mutationObserver = null;
  }}
  if (config.mutations && document.documentElement) {{
    const observer = new MutationObserver((records) => {{
      const items = records.slice(0, 100).map((record) => ({{
        type: record.type,
        target: __agentSnapshot(
          record.target.nodeType === Node.ELEMENT_NODE
            ? record.target
            : record.target.parentElement
        ),
        attribute_name: record.attributeName || null,
        old_value: record.oldValue || null,
        added: Array.from(record.addedNodes).slice(0, 20).map(
          (node) => node.nodeType === Node.ELEMENT_NODE
            ? __agentSnapshot(node)
            : {{node_type: node.nodeType, text: (node.textContent || "").slice(0, 1000)}}
        ),
        removed: Array.from(record.removedNodes).slice(0, 20).map(
          (node) => node.nodeType === Node.ELEMENT_NODE
            ? __agentSnapshot(node)
            : {{node_type: node.nodeType, text: (node.textContent || "").slice(0, 1000)}}
        )
      }}));
      emit({{
        kind: "mutation",
        url: location.href,
        records: items,
        truncated: records.length > items.length,
        timestamp: Date.now()
      }});
    }});
    const target = config.mutation_selector
      ? document.querySelector(config.mutation_selector)
      : document.documentElement;
    if (!target) throw new Error("变更监听选择器未命中元素");
    observer.observe(target, {{
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
      attributeOldValue: true,
      characterDataOldValue: true
    }});
    state.instrumentation.mutationObserver = observer;
  }}
}})();
"""
