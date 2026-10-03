"""The beacon: "NOVA is here" on the local network (UDP), so paired and new PCs find each other.

It carries only the PC's id, name, link port and whether it is waiting to be joined - nothing secret. Beacons are
untrusted hints: a PC is trusted only through pairing, and every real connection is checked with the link key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
import time
from typing import Any, Callable

from .link import PC_ID

log = logging.getLogger("nova.multipc")

MARKER = "nova-multipc/1"
MAX_DATAGRAM = 1024
ANNOUNCE_EVERY_S = 5.0
MAX_NAME = 40


def _ignore_port_unreachable(sock: socket.socket) -> None:
    """Windows: an ICMP "port unreachable" (a beacon sent where nobody listens yet) makes the next receive fail with
    WinError 10054, and asyncio then stops reading the socket for good. SIO_UDP_CONNRESET = off prevents that."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    ws2 = ctypes.windll.ws2_32
    ws2.WSAIoctl.argtypes = [ctypes.c_size_t, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]
    flag, returned = wintypes.BOOL(False), wintypes.DWORD()
    if ws2.WSAIoctl(sock.fileno(), 0x9800000C, ctypes.byref(flag), ctypes.sizeof(flag), None, 0,
                    ctypes.byref(returned), None, None) != 0:
        log.debug("SIO_UDP_CONNRESET not set")


def clean_name(value: Any) -> str:
    """A name that came over the network: printable, short, no control characters."""
    text = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in " .-_'")
    return " ".join(text.split())[:MAX_NAME] or "PC"


def parse(data: bytes) -> dict[str, Any] | None:
    if len(data) > MAX_DATAGRAM:
        return None
    try:
        msg = json.loads(data)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("nova") != MARKER or msg.get("type") not in ("here", "query"):
        return None
    if msg["type"] == "query":
        return {"type": "query"}
    port = msg.get("port")
    if not (isinstance(msg.get("id"), str) and PC_ID.match(msg["id"]) and isinstance(port, int) and 0 < port < 65536):
        return None
    return {"type": "here", "id": msg["id"], "name": clean_name(msg.get("name")), "port": port,
            "version": str(msg.get("version") or "")[:20], "pairing": msg.get("pairing") is True}


class Beacon(asyncio.DatagramProtocol):
    def __init__(self, payload: Callable[[], dict[str, Any]], targets: Callable[[], list[tuple[str, int]]],
                 sender_ok: Callable[[str], bool], on_seen: Callable[[dict[str, Any], str], None]) -> None:
        self.payload = payload  # id, name, port, version, pairing
        self.targets = targets  # where announcements go (subnet broadcast addresses, or loopback test ports)
        self.sender_ok = sender_ok  # only packets from the Private networks (or loopback in test mode)
        self.on_seen = on_seen
        self.transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_reply = 0.0

    async def start(self, host: str, port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # a second NOVA (test mode) shares the port
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        _ignore_port_unreachable(sock)
        sock.bind((host, port))
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self, sock=sock)
        self._task = asyncio.create_task(self._announce_loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self.transport:
            self.transport.close()
        self.transport = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def _message(self, kind: str) -> bytes:
        body = {"nova": MARKER, "type": kind, **(self.payload() if kind == "here" else {})}
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def announce(self, query: bool = False) -> None:
        """Say "here" (and, for a scan, ask the others to say it right away)."""
        if not self.transport:
            return
        for target in self.targets():
            for kind in (("here", "query") if query else ("here",)):
                try:
                    self.transport.sendto(self._message(kind), target)
                except OSError as exc:  # e.g. the network just went away
                    log.debug("beacon to %s failed: %s", target, exc)

    async def _announce_loop(self) -> None:
        self.announce(query=True)
        while True:
            await asyncio.sleep(ANNOUNCE_EVERY_S)
            self.announce()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        host = addr[0]
        if not self.sender_ok(host) or (msg := parse(data)) is None:
            return
        if msg["type"] == "query":
            now = time.monotonic()
            if self.transport and now - self._last_reply > 1.0:  # at most one reply a second
                self._last_reply = now
                for target in self.targets():  # answer like a normal announcement (the asker hears its subnet)
                    try:
                        self.transport.sendto(self._message("here"), target)
                    except OSError:
                        pass
            return
        self.on_seen(msg, host)

    def error_received(self, exc: Exception) -> None:
        log.debug("beacon error: %s", exc)
