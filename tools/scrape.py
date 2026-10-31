"""
title: Scrape Website (direct)
version: 0.4.0-chmikiro
requirements: requests, pysocks, beautifulsoup4, markdownify
"""

try:
    from bs4 import BeautifulSoup  # type: ignore
    from markdownify import markdownify  # type: ignore
except ImportError:
    raise ImportError("Install: pip install pysocks beautifulsoup4 markdownify")


import re
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, Field  # type: ignore


class Tools:
    class Valves(BaseModel):
        PROXY: str = Field("", description="e.g. socks5h://user:passwd@127.0.0.1:1080 (empty = direct)")
        TIMEOUT: int = Field(15)
        MAX_BYTES: int = Field(2_000_000)
        MAX_OUTPUT_CHARS: int = Field(60_000)
        USER_AGENT: str = Field("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    def _fetch(self, url: str):
        p = urlparse((url or "").strip())
        if p.scheme not in ("http", "https") or not p.hostname or p.username:
            raise ValueError("Only http(s) URLs without credentials are allowed")
        s = requests.Session()
        s.trust_env = False
        s.headers["User-Agent"] = self.valves.USER_AGENT
        if self.valves.PROXY:
            s.proxies = {"http": self.valves.PROXY, "https": self.valves.PROXY}
        r = s.get(url, timeout=self.valves.TIMEOUT, stream=True)
        ctype = r.headers.get("Content-Type", "").lower()
        if not any(t in ctype for t in ("text/", "html", "xml", "json")):
            r.close()
            raise ValueError(f"Unsupported content type: {ctype or 'unknown'}")
        buf = bytearray()
        for c in r.iter_content(8192):
            buf += c
            if len(buf) > self.valves.MAX_BYTES:
                r.close()
                raise ValueError("Response too large")
        r.close()
        return r.status_code, ctype, bytes(buf).decode(r.encoding or r.apparent_encoding or "utf-8", "replace")

    def _md(self, body: str, ctype: str) -> str:
        if "html" not in ctype:
            return body
        try:
            from bs4 import BeautifulSoup  # type: ignore
            from markdownify import markdownify  # type: ignore

            soup = BeautifulSoup(body, "html.parser")
            for t in soup(["script", "style", "noscript", "iframe", "svg", "form"]):
                t.decompose()
            return re.sub(r"\n{3,}", "\n\n", markdownify(str(soup), heading_style="ATX")).strip()
        except ImportError:
            t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", "", body)
            return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", t)).strip()

    async def scrape_website(
        self, url: str, __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None
    ) -> str:
        """
        Scrape a website and return readable markdown.
        :param url: Full URL, e.g. https://example.com
        :return: Markdown version of the page.
        """
        async def status(m: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": m, "done": done}})

        try:
            await status("Fetching...")
            code, ctype, body = self._fetch(url)
            if code >= 400:
                await status(f"HTTP {code}", True)
                return f"Error: HTTP {code}"
            md = self._md(body, ctype)[: self.valves.MAX_OUTPUT_CHARS]
            await status("Done", True)
            return f'<untrusted_web_content source="{url}">\n{md}\n</untrusted_web_content>'
        except (ValueError, requests.RequestException) as e:
            await status("Failed", True)
            return f"Error: {e if isinstance(e, ValueError) else type(e).__name__}"
