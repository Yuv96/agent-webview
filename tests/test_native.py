from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_webview.native import _configure_cocoa_proxy, configure_native
from agent_webview.proxy import ProxyConfigurationError


@pytest.mark.parametrize("private_mode", [True, False])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_cocoa_configures_proxy_before_webview_and_keeps_cookie_store(monkeypatch, private_mode, scheme):
    settings = Mock()
    settings.init.return_value = settings
    settings.initNonPersistentConfiguration.return_value = settings
    configuration_type = Mock()
    configuration_type.alloc.return_value = settings
    store = object()

    class Configuration:
        def init(self):
            return self

        def setWebsiteDataStore_(self, value):
            self.store = value

    class BrowserView:
        pass

    store_type = Mock()
    store_type.alloc.return_value._initWithConfiguration_.return_value = store
    webkit = SimpleNamespace(WKWebViewConfiguration=Configuration, WKWebsiteDataStore=store_type)
    monkeypatch.setitem(sys.modules, "WebKit", webkit)
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(NSURL=SimpleNamespace(URLWithString_=lambda url: url)))
    monkeypatch.setitem(sys.modules, "objc", SimpleNamespace(lookUpClass=lambda name: configuration_type, super=super))
    monkeypatch.setitem(sys.modules, "webview.platforms.cocoa", SimpleNamespace(BrowserView=BrowserView))

    url = f"{scheme}://127.0.0.1:12345"
    _configure_cocoa_proxy(url, private_mode)
    (settings.initNonPersistentConfiguration if private_mode else settings.init).assert_called_once()
    settings.setHTTPProxy_.assert_called_once_with(url)
    settings.setHTTPSProxy_.assert_called_once_with(url)
    settings.setRequiresSecureHTTPSProxyConnection_.assert_called_once_with(scheme == "https")
    # WKWebView 构造前已经选定存储；pywebview 后续默认存储赋值不会改走其他存储。
    configured = webkit.WKWebViewConfiguration().init()
    assert configured.store is store
    browser = BrowserView()
    browser.webview = SimpleNamespace(configuration=lambda: SimpleNamespace(websiteDataStore=lambda: store))
    browser.datastore = object()
    assert browser.datastore is store
    store_type.defaultDataStore.assert_not_called()


def test_missing_native_proxy_api_fails_instead_of_loading_directly(monkeypatch):
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "WebKit", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "objc", SimpleNamespace(lookUpClass=Mock(side_effect=AttributeError), super=super))
    monkeypatch.setitem(sys.modules, "webview.platforms.cocoa", SimpleNamespace(BrowserView=SimpleNamespace()))
    with pytest.raises(ProxyConfigurationError, match="无法配置独立代理"):
        _configure_cocoa_proxy("http://127.0.0.1:12345", True)


def test_non_cocoa_proxy_without_storage_does_not_require_native_storage_support():
    configure_native("gtk", {}, None, browser_proxy="http://127.0.0.1:12345")
