from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from agent_webview.cookies import SnapshotStore
from agent_webview.models import CookieSnapshot, StorageStateResponse
from agent_webview.storage import storage_capture_expression, storage_restore_script


def test_snapshot_preserves_storage_and_old_format(tmp_path):
    store = SnapshotStore(tmp_path)
    values = {"https://example.test": {"token": "中文\n😀", "__proto__": "value", "empty": "", "reserved": "__MARKER__ __STATE__"}}
    saved = store.save(session_id="s", url="https://example.test/page", cookies=[], name=None, local_storage=values)
    assert store.get(saved["snapshot_id"])["local_storage"] == values
    saved.pop("local_storage")
    saved.pop("schema_version")
    assert CookieSnapshot.model_validate(saved).local_storage == {}


def test_origin_validation():
    for origin in ["https://example.test/path", "https://example.test/", "file://host", "https://user@host", "null"]:
        with pytest.raises(ValueError):
            StorageStateResponse(url=None, cookies=[], local_storage={origin: {}})


@pytest.mark.skipif(shutil.which("node") is None, reason="需要 Node 验证真实 JavaScript 行为")
def test_restore_origin_replacement_unicode_and_once_only():
    state = {"https://example.test": {"token": "中文\n😀", "__proto__": "literal", "empty": "", "reserved": "__MARKER__ __STATE__"}}
    script = storage_restore_script(state)
    # VM 模拟不同 origin 导航；真实 WebView 时序由 smoke_storage_cache 验证。
    program = """
    const vm = require('node:vm');
    const assert = require('node:assert/strict');
    class Storage {
      constructor() { this.values = new Map([['stale', 'value']]); }
      get length() { return this.values.size; }
      key(i) { return [...this.values.keys()][i]; }
      getItem(k) { return this.values.get(k) ?? null; }
      setItem(k, v) { this.values.set(k, v); }
      clear() { this.values.clear(); }
    }
    const ctx = vm.createContext({localStorage: new Storage(), sessionStorage: new Storage(),
      location: {origin: 'https://other.test', href: 'https://other.test/', protocol: 'https:'}});
    const script = SCRIPT;
    vm.runInContext(script, ctx);
    assert.equal(ctx.localStorage.getItem('stale'), 'value');
    ctx.location.origin = 'https://example.test';
    vm.runInContext(script, ctx);
    assert.equal(ctx.localStorage.getItem('stale'), null);
    assert.equal(ctx.localStorage.getItem('__proto__'), 'literal');
    assert.equal(ctx.localStorage.getItem('reserved'), '__MARKER__ __STATE__');
    assert.equal(ctx.localStorage.getItem('token'), '中文\\n😀');
    const captured = JSON.parse(vm.runInContext(CAPTURE, ctx));
    assert.equal(captured.local_storage['https://example.test']['__proto__'], 'literal');
    ctx.localStorage.setItem('token', 'changed');
    vm.runInContext(script, ctx);
    assert.equal(ctx.localStorage.getItem('token'), 'changed');
    """.replace("SCRIPT", json.dumps(script)).replace("CAPTURE", json.dumps(storage_capture_expression()))
    subprocess.run(["node", "-e", program], check=True, capture_output=True)
