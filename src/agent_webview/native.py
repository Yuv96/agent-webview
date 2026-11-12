from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_webview.proxy import ProxyConfigurationError
from agent_webview.storage import storage_restore_script


def configure_native(renderer: str, storage: dict[str, dict[str, str]], ca_file: Path | None) -> None:
    if not storage and ca_file is None:
        return
    script = storage_restore_script(storage) if storage else None
    if renderer == "cocoa":
        renderer = "wkwebview"
    if renderer == "wkwebview":
        _configure_cocoa(script, ca_file)
    elif renderer == "edgechromium":
        _configure_edge(script, ca_file)
    else:
        raise ProxyConfigurationError("localStorage 快照恢复和资源缓存目前支持 WKWebView / WebView2")


def _configure_cocoa(script: str | None, ca_file: Path | None) -> None:
    import AppKit
    import Security
    import WebKit
    from webview.platforms.cocoa import BrowserView

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
