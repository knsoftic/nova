"""Fetch public web pages safely.

Web pages and search results are untrusted. A link must never make NOVA reach into the local
machine or network (NOVA's own API on 127.0.0.1:8765, Ollama, the router, LAN devices), so every
URL - including every redirect hop - must resolve only to public addresses.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NOVA-personal-assistant/0.1"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
TIMEOUT_S = 15.0
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class UnsafeUrlError(ValueError):
    pass


@dataclass
class FetchedPage:
    url: str
    status: int
    content_type: str
    text: str


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified)


async def check_url(url: str, resolver=None) -> list[str]:
    """Raise UnsafeUrlError unless url is http(s) on a host that resolves only to public IPs.
    Returns the checked IPs, so the connection can be pinned to them."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrlError("sirf http/https web pages")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL mein login details allowed nahi")
    host = parsed.hostname
    try:
        ips = [host.strip("[]")] if _looks_like_ip(host) else await (resolver or _resolve)(host, parsed.port or 443)
    except OSError as exc:
        raise UnsafeUrlError(f"host nahi mila: {host}") from exc
    if not ips or not all(_is_public(ip) for ip in ips):
        raise UnsafeUrlError("ye address is PC ya local network ka hai — NOVA wahan nahi jata")
    return ips


def _pinned(url: str, ip: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Connect to the already-checked IP (no second DNS lookup an attacker could change), while keeping
    the real hostname for the Host header and for TLS certificate verification (SNI)."""
    parsed = urlparse(url)
    ip_part = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_part}:{parsed.port}" if parsed.port else ip_part
    host_header = parsed.netloc.rsplit("@", 1)[-1]
    extensions = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
    return parsed._replace(netloc=netloc).geturl(), {"Host": host_header}, extensions


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


async def fetch(url: str, transport: httpx.AsyncBaseTransport | None = None, resolver=None) -> FetchedPage:
    """GET a public page with manual redirect handling (each hop re-checked), size and type limits."""
    async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S, follow_redirects=False,
                                 headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            ips = await check_url(url, resolver)
            pinned_url, headers, extensions = _pinned(url, ips[0])
            async with client.stream("GET", pinned_url, headers=headers, extensions=extensions) as resp:
                if resp.is_redirect and (location := resp.headers.get("location")):
                    url = urljoin(url, location)
                    continue
                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if resp.status_code >= 400:
                    return FetchedPage(url, resp.status_code, content_type, "")
                if content_type and not content_type.startswith(ALLOWED_TYPES):
                    raise UnsafeUrlError(f"ye web page nahi ({content_type})")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                encoding = resp.encoding or "utf-8"
                return FetchedPage(url, resp.status_code, content_type,
                                   bytes(body[:MAX_BYTES]).decode(encoding, errors="replace"))
        raise UnsafeUrlError("bohat zyada redirects")
