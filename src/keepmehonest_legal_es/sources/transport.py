"""Bounded, allowlisted HTTPS retrieval. No client text ever becomes a URL.

This module deliberately forbids redirects and nonofficial hosts rather than
silently following a potentially unsafe destination.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler
import ssl
import re


class FetchError(RuntimeError):
    """HTTP, response-shape, or provenance validation failure."""


class SourceUnavailable(FetchError):
    """Source blocked or cannot be reached. Must not be interpreted as no authority."""


@dataclass(frozen=True)
class Retrieved:
    url: str
    body: bytes
    content_type: str
    sha256: str
    retrieved_at: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise SourceUnavailable("HTTP redirect refused; inspect source endpoint manually")


class SecureHTTP:
    """No arbitrary destinations: exactly BOE API or HJ JSON resolution exports."""

    _HOSTS = {"www.boe.es", "hj.tribunalconstitucional.es"}

    def __init__(self, timeout: float = 12.0, max_bytes: int = 4_000_000):
        if not 0 < timeout <= 60 or not 1000 <= max_bytes <= 16_000_000:
            raise ValueError("timeout/max_bytes out of permitted range")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())

    @classmethod
    def check_url(cls, url: str) -> None:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname not in cls._HOSTS or p.port is not None or
                p.username or p.password or p.query or p.fragment):
            raise FetchError("URL rejected (scheme, host or parameters)")
        if p.hostname == "www.boe.es":
            if not p.path.startswith("/datosabiertos/api/legislacion-consolidada/id/"):
                raise FetchError("Only specified BOE legislation endpoints permitted")
        else:
            if not re.fullmatch(r"/HJ/Resolucion/Api/json/[1-9][0-9]{0,8}", p.path):
                raise FetchError("Only explicit Tribunal Constitucional JSON resolution IDs permitted")

    def get(self, url: str, *, accept: str) -> Retrieved:
        self.check_url(url)
        if accept not in ("application/xml", "application/json"):
            raise ValueError("unsupported content negotiation")
        req = Request(url, headers={"Accept": accept, "User-Agent": "KeepMeHonest-Research/0.2 (read-only; contact: nicholasspoel@gmail.com)"}, method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                if resp.status != 200 or resp.geturl() != url:
                    raise SourceUnavailable("unexpected source response/redirect")
                ctype = resp.headers.get("Content-Type", "").lower().split(";")[0].strip()
                if not (ctype in ("application/xml", "text/xml") if accept == "application/xml" else ctype == "application/json"):
                    raise SourceUnavailable(f"unexpected content type {ctype!r}")
                body = resp.read(self.max_bytes + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SourceUnavailable(f"source unavailable ({type(exc).__name__}); no negative conclusion") from exc
        if len(body) > self.max_bytes or not body:
            raise SourceUnavailable("source response empty or exceeds size limit")
        return Retrieved(url, body, ctype, sha256(body).hexdigest(), datetime.now(timezone.utc).isoformat(timespec="seconds"))
