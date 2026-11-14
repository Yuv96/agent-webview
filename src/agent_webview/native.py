from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_webview.proxy import ProxyConfigurationError
from agent_webview.storage import storage_restore_script


def configure_native(
    renderer: str, storage: dict[str, dict[str, str]], ca_file: Path | None,
    *, browser_proxy: str | None = None, private_mode: bool = True,
) -> None:
    if not storage and ca_file is None and (not browser_proxy or renderer not in {"cocoa", "wkwebview"}):
        return
    script = storage_restore_script(storage) if storage else None
    if renderer == "cocoa":
        renderer = "wkwebview"
    if renderer == "wkwebview":
        _configure_cocoa(script, ca_file, browser_proxy=browser_proxy, private_mode=private_mode)
    elif renderer == "edgechromium":
        _configure_edge(script, ca_file)
    else:
        raise ProxyConfigurationError("localStorage 快照恢复和资源缓存目前支持 WKWebView / WebView2")


def _configure_cocoa_proxy(proxy_url: str, private_mode: bool) -> None:
    """代理使用独立的 CFNetwork 数据存储，支持窗口级证书校验。"""
    from urllib.parse import urlsplit

    import Foundation
    import objc
    import WebKit
    from objc import super as objc_super
    from webview.platforms.cocoa import BrowserView

    try:
        configuration_type = objc.lookUpClass("_WKWebsiteDataStoreConfiguration")
        configuration = configuration_type.alloc()
        configuration = configuration.initNonPersistentConfiguration() if private_mode else configuration.init()
        endpoint = Foundation.NSURL.URLWithString_(proxy_url)
        configuration.setHTTPProxy_(endpoint)
        configuration.setHTTPSProxy_(endpoint)
        # 缓存/可变代理入口为本地 HTTP；全局 HTTPS 代理保留到代理本身的 TLS。
        configuration.setRequiresSecureHTTPSProxyConnection_(urlsplit(proxy_url).scheme == "https")
        store = WebKit.WKWebsiteDataStore.alloc()._initWithConfiguration_(configuration)
        if store is None:
            raise RuntimeError("无法创建数据存储")

        class ProxyWebViewConfiguration(WebKit.WKWebViewConfiguration):
            def init(self):
                instance = objc_super(ProxyWebViewConfiguration, self).init()
                instance.setWebsiteDataStore_(store)
                return instance

        WebKit.WKWebViewConfiguration = ProxyWebViewConfiguration
        # pywebview 在创建 WKWebView 后才设置数据存储，已经晚于配置复制。
        # 让其 Cookie 读取与无痕清理也指向窗口真实使用的存储，避免触及默认存储。
        BrowserView.datastore = property(
            lambda self: self.webview.configuration().websiteDataStore(),
            lambda self, value: None,
        )
    except Exception as error:
        raise ProxyConfigurationError("当前 WKWebView 无法配置独立代理") from error


def _configure_cocoa(
    script: str | None, ca_file: Path | None,
    *, browser_proxy: str | None = None, private_mode: bool = True,
) -> None:
    import AppKit
    import Security
    import WebKit
    from webview.platforms.cocoa import BrowserView

    if ca_file and not browser_proxy:
        raise ProxyConfigurationError("WKWebView 缓存缺少本地代理入口")
    if browser_proxy:
        _configure_cocoa_proxy(browser_proxy, private_mode)

    if script:
        original_load = BrowserView.load_url

        def load_url(self: Any, url: str) -> Any:
            if not getattr(self, "_agent_storage_installed", False):
                user_script = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
                    script, WebKit.WKUserScriptInjectionTimeAtDocumentStart, False,
                )
                self.webview.configuration().userContentController().addUserScript_(user_script)
                self._agent_storage_installed = True
            return original_load(self, url)

        BrowserView.load_url = load_url  # type: ignore[method-assign]

    if ca_file:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding

        der = x509.load_pem_x509_certificate(ca_file.read_bytes()).public_bytes(Encoding.DER)
        anchor = Security.SecCertificateCreateWithData(None, der)

        class CacheBrowserDelegate(BrowserView.BrowserDelegate):
            def webView_didReceiveAuthenticationChallenge_completionHandler_(self, view, challenge, handler):
                space = challenge.protectionSpace()
                if space.authenticationMethod() == AppKit.NSURLAuthenticationMethodServerTrust:
                    trust = space.serverTrust()
                    Security.SecTrustSetAnchorCertificates(trust, [anchor])
                    Security.SecTrustSetAnchorCertificatesOnly(trust, True)
                    valid, _ = Security.SecTrustEvaluateWithError(trust, None)
                    if valid:
                        credential = AppKit.NSURLCredential.credentialForTrust_(trust)
                        handler(AppKit.NSURLSessionAuthChallengeUseCredential, credential)
                        return
                handler(AppKit.NSURLSessionAuthChallengePerformDefaultHandling, None)

        BrowserView.BrowserDelegate = CacheBrowserDelegate  # type: ignore[misc]


def _configure_edge(script: str | None, ca_file: Path | None) -> None:
    from webview.platforms.edgechromium import EdgeChrome

    # WebView2 原生初始化回调早于首次 Navigate；异步脚本安装完成后才继续导航。
    original_ready = EdgeChrome.on_webview_ready
    anchor = None
    if ca_file:
        from cryptography import x509
        anchor = x509.load_pem_x509_certificate(ca_file.read_bytes())

    def on_ready(self: Any, sender: Any, args: Any) -> None:
        if not args.IsSuccess:
            original_ready(self, sender, args)
            return
        core = sender.CoreWebView2
        if anchor is not None:
            from cryptography import x509
            from cryptography.exceptions import InvalidSignature
            from Microsoft.Web.WebView2.Core import (
                CoreWebView2ServerCertificateErrorAction,
            )

            def on_certificate_error(_: Any, event: Any) -> None:
                try:
                    leaf = x509.load_pem_x509_certificate(str(event.ServerCertificate.ToPemEncoding()).encode())
                    leaf.verify_directly_issued_by(anchor)
                    # 只接受该 worker 的代理签发证书，上游证书由代理正常验证。
                    event.Action = CoreWebView2ServerCertificateErrorAction.AlwaysAllow
                except (ValueError, TypeError, InvalidSignature):
                    pass

            core.ServerCertificateErrorDetected += on_certificate_error
            self._agent_certificate_handler = on_certificate_error
        if script:
            from System import Action, String
            from System.Threading.Tasks import Task

            def installed(task: Any) -> None:
                if task.IsFaulted or task.IsCanceled:
                    self.pywebview_window.destroy()
                    return
                original_ready(self, sender, args)

            core.AddScriptToExecuteOnDocumentCreatedAsync(script).ContinueWith(
                Action[Task[String]](installed), self.syncContextTaskScheduler,
            )
        else:
            original_ready(self, sender, args)

    EdgeChrome.on_webview_ready = on_ready  # type: ignore[method-assign]
