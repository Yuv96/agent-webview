from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Any

from agent_webview.files import ensure_private_directory
from agent_webview.models import ResourceCacheOptions
from agent_webview.proxy import ProxyConfigurationError
from agent_webview.resource_cache import CacheAddon, ResourceCache


class CacheProxy:
    """worker 内本地缓存代理；临时 CA 仅由该窗口信任，不修改系统信任库。"""

    def __init__(self, directory: Path, options: ResourceCacheOptions, upstream: str | None) -> None:
        try:
            from mitmproxy import options as mitm_options
            from mitmproxy.tools.dump import DumpMaster
        except ImportError as error:
            raise ProxyConfigurationError("资源缓存需要 Python 3.12+，请安装 agent-webview[cache]") from error
        # mitmproxy 默认连接日志可能包含目标地址，不纳入浏览器调试日志。
        logging.getLogger("mitmproxy").setLevel(logging.CRITICAL)
        self._temporary = TemporaryDirectory(prefix="agent-webview-cache-")
        self.confdir = ensure_private_directory(Path(self._temporary.name))
        self.ca_file = self.confdir / "mitmproxy-ca-cert.pem"
        self._ready = Event()
        self._error = False
        self._master: Any = None
        self._loop: Any = None
        self.url = ""
        cache = ResourceCache(directory, options)
        owner = self

        class ReadyAddon:
            def running(self) -> None:
                addresses = owner._master.addons.get("proxyserver").listen_addrs()
                if addresses:
                    owner.url = f"http://127.0.0.1:{addresses[0][1]}"
                else:
                    owner._error = True
                owner._ready.set()

        async def serve() -> None:
            self._loop = asyncio.get_running_loop()
            settings = mitm_options.Options(
                listen_host="127.0.0.1", listen_port=0, confdir=str(self.confdir),
                mode=[f"upstream:{upstream}" if upstream else "regular"],
            )
            self._master = DumpMaster(settings, with_termlog=False, with_dumper=False)
            # 延迟建立上游连接，缓存命中时不产生 DNS/TLS/网络访问。
            settings.update(connection_strategy="lazy", stream_large_bodies=str(options.max_resource_bytes), onboarding=False)
            self._master.addons.add(CacheAddon(cache), ReadyAddon())
            await self._master.run()

        def run() -> None:
            try:
                asyncio.run(serve())
            except Exception:
                self._error = True
                self._ready.set()

        self._thread = Thread(target=run, daemon=True, name="本地资源缓存")
        self._thread.start()
        if not self._ready.wait(20) or self._error or not self.ca_file.is_file():
            self.close()
            raise ProxyConfigurationError("本地资源缓存代理启动失败")

    def close(self) -> None:
        if self._loop is not None and self._master is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._master.shutdown)
        self._thread.join(timeout=5)
        self._temporary.cleanup()
