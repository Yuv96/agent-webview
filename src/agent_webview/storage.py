from __future__ import annotations

import json
from uuid import uuid4


def storage_capture_expression() -> str:
    # 由浏览器返回 origin，不从可能已经跳转的请求 URL 推导。
    return """(() => {
        const state = {url: location.href, local_storage: {}};
        if (!/^https?:$/.test(location.protocol)) return JSON.stringify(state);
        const entries = Object.create(null);
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            entries[key] = localStorage.getItem(key);
        }
        state.local_storage[location.origin] = entries;
        return JSON.stringify(state);
    })()"""


def storage_restore_script(state: dict[str, dict[str, str]]) -> str:
    payload = json.dumps(state, ensure_ascii=True)
    marker = json.dumps("__agent_webview_restore_" + uuid4().hex)
    return """(() => {
        const state = JSON.parse(__STATE__);
        const marker = __MARKER__;
        if (!Object.prototype.hasOwnProperty.call(state, location.origin)) return;
        if (sessionStorage.getItem(marker)) return;
        const entries = state[location.origin];
        localStorage.clear();
        for (const [key, value] of Object.entries(entries)) localStorage.setItem(key, value);
        sessionStorage.setItem(marker, '1');
    })();""".replace("__MARKER__", marker, 1).replace("__STATE__", json.dumps(payload), 1)
