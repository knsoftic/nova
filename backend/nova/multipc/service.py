"""Multi-PC (Phase 13): this PC's identity, the encrypted link server, the beacon, pairing, and requests to paired PCs.

Off until the user turns it on, and only on Private (home/office) networks. The link server listens only on those
networks' addresses; the main NOVA API stays on 127.0.0.1. What a paired PC may do here is decided on this PC
(policy.py), and only when the user allowed that PC ("Remote kaam" on).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import socket
import ssl
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..db import Database
from ..events import EventBus, EventType, NovaEvent
from ..secret_store import protect, unprotect
from .beacon import Beacon, clean_name
from .link import (
    MAX_MESSAGE,
    PAIR_PREFIX,
    PC_ID,
    TIMEOUT_S,
    LinkError,
    client_context,
    close,
    new_code,
    new_link_key,
    new_pc_id,
    normalize_code,
    pairing_key,
    proof,
    proof_ok,
    receive,
    send,
    server_context,
    used_certificate,
)
from .netinfo import LOOPBACK, NetInfo, list_networks

log = logging.getLogger("nova.multipc")

NAME = "Multi-PC Agent"
ONLINE_S = 20.0  # seen by its beacon, or answered a request, this recently = online
FOUND_S = 30.0  # unpaired PCs drop off the "found" list after this
PAIRING_S = 300  # the joining code is valid for 5 minutes ...
PAIR_ATTEMPTS = 5  # ... and for this many tries
NET_CACHE_S = 30.0
WATCH_S = 30.0
REQUESTS_PER_MINUTE = 30


def default_pc_name() -> str:
    return clean_name(os.environ.get("COMPUTERNAME") or socket.gethostname())


@dataclass
class Seen:
    id: str
    name: str
    host: str
    port: int
    version: str
    pairing: bool
    at: float


@dataclass
class PairingSession:
    code: str
    key: bytes
    expires: float
    attempts: int = 0


class MultiPcService:
    def __init__(self, db: Database, bus: EventBus, settings: Callable[[], Any], version: str, *,
                 peer_port: int = 8770, beacon_port: int | None = 8771, loopback: bool = False,
                 beacon_targets: tuple[int, ...] = (), networks: Callable[[], list[NetInfo]] = list_networks,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.db, self.bus, self.settings, self.version = db, bus, settings, version
        self.peer_port, self.beacon_port, self.loopback, self.beacon_targets = (peer_port, beacon_port, loopback,
                                                                                beacon_targets)
        self.networks, self.clock = networks, clock
        self.id = self._load_id()
        self.port: int | None = None  # the link port actually listening (peer_port, or the one picked for 0)
        self.reason: str | None = "Multi-PC band hai"
        self.seen: dict[str, Seen] = {}
        self.pairing: PairingSession | None = None
        self._server: asyncio.Server | None = None
        self._beacon: Beacon | None = None
        self._hosts: list[str] = []
        self._nets: list[NetInfo] = []
        self._nets_at = -1e9
        self._keys: dict[str, bytes] = {}
        self._answered: dict[str, float] = {}
        self._rate: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._watch_task: asyncio.Task[None] | None = None
        self._pairing_timer: asyncio.TimerHandle | None = None
        # Set by the app: what this PC does for a paired PC (system info, plan + run of a command).
        self.status_info: Callable[[], Awaitable[dict[str, Any]]] | None = None
        self.plan: Callable[[dict[str, Any], str], Awaitable[dict[str, Any]]] | None = None
        self.run: Callable[[dict[str, Any], str, bool], Awaitable[dict[str, Any]]] | None = None

    # ------------------------------------------------------------------ identity

    def _load_id(self) -> str:
        pc_id = self.db.get_setting("pc_id") or ""
        if not PC_ID.match(pc_id):
            pc_id = new_pc_id()
            self.db.set_setting("pc_id", pc_id)
        return pc_id

    @property
    def name(self) -> str:
        return self.settings().pc_name or default_pc_name()

    @property
    def running(self) -> bool:
        return self._server is not None

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self._watch_task = asyncio.create_task(self._watch())

    async def shutdown(self) -> None:
        if self._watch_task:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task
        await self._stop_listening()

    async def _watch(self) -> None:
        """Follow the setting and the network (switching to a cafe Wi-Fi turns the link off)."""
        while True:
            try:
                await self.apply()
            except Exception:  # never let a network hiccup end the watch
                log.exception("Multi-PC check failed")
            await asyncio.sleep(WATCH_S)

    async def _networks(self, refresh: bool = False) -> list[NetInfo]:
        if self.loopback:
            return [LOOPBACK]
        if refresh or self.clock() - self._nets_at > NET_CACHE_S:
            self._nets = await asyncio.to_thread(self.networks)
            self._nets_at = self.clock()
        return self._nets

    def _private(self) -> list[NetInfo]:
        return [LOOPBACK] if self.loopback else [n for n in self._nets if n.private]

    async def apply(self, refresh_network: bool = False) -> None:
        async with self._lock:
            before = (self.running, self.reason)
            if not self.settings().multi_pc:
                await self._stop_listening()
                self.reason = "Multi-PC band hai"
            else:
                nets = await self._networks(refresh_network)
                private = self._private()
                if not private:
                    await self._stop_listening()
                    public = [n for n in nets if not n.private]
                    self.reason = (f"Network \"{public[0].name or public[0].alias}\" Windows mein Public hai — Multi-PC "
                                   "sirf Private (ghar/office) network par chalta hai. Windows Settings → Network & "
                                   "internet → is network ki Properties → Private network." if public
                                   else "Koi network connected nahi")
                elif not (self.running and sorted(n.ip for n in private) == self._hosts):
                    await self._stop_listening()
                    await self._listen(private)
            if (self.running, self.reason) != before:
                await self._changed("Multi-PC chal raha hai" if self.running else f"Multi-PC ruka: {self.reason}")

    async def _listen(self, private: list[NetInfo]) -> None:
        hosts = sorted(n.ip for n in private)
        try:
            self._server = await asyncio.start_server(self._handle, hosts, self.peer_port, ssl=server_context(self._psk),
                                                      limit=MAX_MESSAGE, ssl_handshake_timeout=TIMEOUT_S)
        except OSError as exc:
            self.reason = f"Port {self.peer_port} istemal nahi ho saka ({exc.strerror or exc})"
            return
        self.port = self._server.sockets[0].getsockname()[1]
        self._hosts, self.reason = hosts, None
        if self.beacon_port:
            beacon = Beacon(self._beacon_payload, self._beacon_targets, self._sender_ok, self._on_seen)
            try:
                await beacon.start("127.0.0.1" if self.loopback else "0.0.0.0", self.beacon_port)
                self._beacon = beacon
            except OSError as exc:  # the link still works; only finding PCs automatically does not
                log.warning("beacon off: %s", exc)

    async def _stop_listening(self) -> None:
        if self._beacon:
            self._beacon.stop()
            self._beacon = None
        if self._server:
            self._server.close()
            self._server = None
        self._hosts, self.port = [], None
        self._end_pairing()

    def _beacon_payload(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "port": self.port, "version": self.version,
                "pairing": self._pairing_open()}

    def _beacon_targets(self) -> list[tuple[str, int]]:
        if self.loopback:
            return [("127.0.0.1", p) for p in self.beacon_targets]
        return [(n.broadcast, self.beacon_port or 0) for n in self._private()]

    def _sender_ok(self, host: str) -> bool:
        if self.loopback:
            return host == "127.0.0.1"
        return any(n.contains(host) for n in self._private())

    def _on_seen(self, msg: dict[str, Any], host: str) -> None:
        if msg["id"] == self.id:
            return
        old = self.seen.get(msg["id"])
        was_online = self.online(msg["id"])
        self.seen[msg["id"]] = Seen(msg["id"], msg["name"], host, msg["port"], msg["version"], msg["pairing"],
                                    self.clock())
        peer = self.db.get_peer(msg["id"])
        if peer is not None and (peer["host"], peer["port"]) != (host, msg["port"]):  # e.g. a new address from DHCP
            self.db.update_peer(msg["id"], host=host, port=msg["port"])
        if old is None or old.pairing != msg["pairing"] or old.name != msg["name"] or not was_online:
            asyncio.get_running_loop().create_task(self._changed())

    async def _changed(self, message: str | None = None) -> None:
        await self.bus.publish(NovaEvent(type=EventType.PEERS_CHANGED, agent=NAME,
                                         message=message or "PCs ki maloomat update hui",
                                         data={"running": self.running, "quiet": message is None}))

    def _log(self, action: str, result: str, permission: str = "user_initiated", status: str = "success") -> None:
        self.db.add_activity(task_id="multipc", task_name=f"multipc:{action}", agent=NAME, action=action,
                             permission_status=permission, execution_status=status, final_result=result)

    # ------------------------------------------------------------------ status for the UI

    def online(self, peer_id: str) -> bool:
        seen = self.seen.get(peer_id)
        last = max(seen.at if seen else -1e9, self._answered.get(peer_id, -1e9))
        return self.clock() - last < ONLINE_S

    def status(self) -> dict[str, Any]:
        peers = self.db.list_peers()
        paired = {p["id"] for p in peers}
        now = self.clock()
        return {
            "this": {"id": self.id, "name": self.name, "version": self.version, "port": self.port},
            "enabled": bool(self.settings().multi_pc),
            "running": self.running,
            "reason": self.reason,
            "networks": [n.to_dict() for n in ([LOOPBACK] if self.loopback else self._nets)],
            "pairing": ({"code": self.pairing.code, "expires_in": max(0, int(self.pairing.expires - now))}
                        if self._pairing_open() and self.pairing else None),
            "found": [{"id": s.id, "name": s.name, "host": s.host, "port": s.port, "version": s.version,
                       "pairing": s.pairing} for s in self.seen.values()
                      if s.id not in paired and now - s.at < FOUND_S],
            "peers": [{"id": p["id"], "name": p["name"], "host": p["host"], "port": p["port"],
                       "online": self.online(p["id"]), "remote_allowed": bool(p["remote_allowed"]),
                       "allows_us": None if p["allows_us"] is None else bool(p["allows_us"]),
                       "paired_at": p["paired_at"], "last_seen": p["last_seen"]} for p in peers],
        }

    # ------------------------------------------------------------------ keys

    def _key(self, peer_id: str) -> bytes | None:
        if peer_id not in self._keys:
            row = self.db.get_peer(peer_id)
            key = unprotect(row["key_enc"]) if row else None
            if key is None or len(key) != 32:
                return None
            self._keys[peer_id] = key
        return self._keys[peer_id]

    def _psk(self, identity: str) -> bytes | None:
        """TLS asks for the key of whoever connects. Unknown -> None -> the handshake fails."""
        if identity.startswith(PAIR_PREFIX):
            session = self.pairing
            if session is None or not self._pairing_open():
                return None
            session.attempts += 1
            if session.attempts > PAIR_ATTEMPTS:
                asyncio.get_running_loop().call_soon(self._too_many_attempts)
                return None
            return session.key
        return self._key(identity)

    # ------------------------------------------------------------------ pairing: this PC is joined

    def _pairing_open(self) -> bool:
        return self.pairing is not None and self.clock() < self.pairing.expires

    async def open_pairing(self) -> dict[str, Any]:
        if not self.running:
            raise LinkError(self.reason or "Multi-PC chal nahi raha")
        code = new_code()
        key = await asyncio.to_thread(pairing_key, normalize_code(code) or "")
        self.pairing = PairingSession(code, key, self.clock() + PAIRING_S)
        if self._pairing_timer:
            self._pairing_timer.cancel()
        self._pairing_timer = asyncio.get_running_loop().call_later(PAIRING_S, self._pairing_expired)
        if self._beacon:
            self._beacon.announce()
        self._log("open_pairing", "jorne ka code banaya (5 minute)")  # never the code itself
        await self._changed("Ye PC jorne ke liye tayyar hai (5 minute)")
        return {"code": code, "expires_in": PAIRING_S}

    async def close_pairing(self) -> None:
        if self.pairing is not None:
            self._end_pairing()
            await self._changed("Jorne ka code band")

    def _end_pairing(self) -> None:
        self.pairing = None
        if self._pairing_timer:
            self._pairing_timer.cancel()
            self._pairing_timer = None

    def _pairing_expired(self) -> None:
        self._end_pairing()
        asyncio.get_running_loop().create_task(self._changed("Jorne ka waqt khatam — code band"))

    def _too_many_attempts(self) -> None:
        if self.pairing is None:
            return
        self._end_pairing()
        self._log("pairing_refused", f"{PAIR_ATTEMPTS} se zyada ghalat koshishein — jorna band", "refused_by_nova",
                  "refused")
        asyncio.get_running_loop().create_task(
            self._changed("Bohat ghalat koshishein — jorne ka code band kar diya (naya code banayein)"))

    async def _accept_pairing(self, client_id: str, request: dict[str, Any], host: str) -> dict[str, Any]:
        port = request.get("port")
        if request.get("type") != "pair" or not isinstance(port, int) or not 0 < port < 65536:
            return {"type": "error", "error": "Jorne ki darkhwast sahi nahi"}
        if client_id == self.id:
            return {"type": "error", "error": "Ye yahi PC hai"}
        name = clean_name(request.get("name"))
        link_key = new_link_key()
        self.db.save_peer(client_id, name, host, port, protect(link_key))
        self._keys[client_id] = link_key
        self._answered[client_id] = self.clock()
        self._end_pairing()  # one code, one PC
        self._log("paired", f"'{name}' is PC se jur gaya")
        await self._changed(f"'{name}' is PC se jur gaya")
        return {"type": "paired", "name": self.name, "key": link_key.hex(), "port": self.port}

    # ------------------------------------------------------------------ pairing: this PC joins another

    async def pair(self, code: str, host: str, port: int) -> dict[str, Any]:
        if not self.running:
            raise LinkError(self.reason or "Multi-PC chal nahi raha")
        normalized = normalize_code(code)
        if normalized is None:
            raise LinkError("Code poora aur sahi likhein — 12 haroof, maslan K7QF-M2XA-9TPW")
        key = await asyncio.to_thread(pairing_key, normalized)
        reply = await self._exchange(host, port, PAIR_PREFIX + self.id, key, {"type": "pair", "name": self.name,
                                                                              "port": self.port}, pair=True)
        try:
            link_key = bytes.fromhex(str(reply.get("key")))
            peer_port = int(reply.get("port") or port)
        except (ValueError, TypeError):
            link_key, peer_port = b"", 0
        if reply.get("type") != "paired" or len(link_key) != 32 or not 0 < peer_port < 65536:
            raise LinkError(str(reply.get("error") or "Jorna mukammal nahi hua"))
        peer_id, name = reply["_server_id"], reply["_server_name"]
        self.db.save_peer(peer_id, name, host, peer_port, protect(link_key))
        self._keys[peer_id] = link_key
        self._answered[peer_id] = self.clock()
        self._log("paired", f"'{name}' se jur gaya")
        await self._changed(f"'{name}' se jur gaya")
        return {"id": peer_id, "name": name}

    # ------------------------------------------------------------------ requests to a paired PC

    async def request(self, peer_id: str, message: dict[str, Any], timeout: float = TIMEOUT_S) -> dict[str, Any]:
        peer = self.db.get_peer(peer_id)
        key = self._key(peer_id) if peer else None
        if peer is None or key is None:
            raise LinkError("Ye PC jura hua nahi (ya us ki key is Windows user ki nahi) — dobara jorein")
        if not self.running:
            raise LinkError(self.reason or "Multi-PC chal nahi raha")
        seen = self.seen.get(peer_id)
        places = [(seen.host, seen.port)] if seen and self.clock() - seen.at < FOUND_S else []
        places += [(peer["host"], peer["port"])]
        error: LinkError | None = None
        for host, port in dict.fromkeys(places):
            try:
                reply = await self._exchange(host, port, self.id, key, message, timeout=timeout, expect_id=peer_id)
            except LinkError as exc:
                error = exc
                continue
            self._answered[peer_id] = self.clock()
            update: dict[str, Any] = {"host": host, "port": port, "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if isinstance(reply.get("allows_you"), bool):
                update["allows_us"] = int(reply["allows_you"])
            if reply["_server_name"] != peer["name"]:
                update["name"] = reply["_server_name"]  # the other PC was renamed
            self.db.update_peer(peer_id, **update)
            return reply
        raise error or LinkError("Raabta nahi ho saka")

    async def _exchange(self, host: str, port: int, identity: str, key: bytes, message: dict[str, Any], *,
                        timeout: float = TIMEOUT_S, pair: bool = False, expect_id: str | None = None) -> dict[str, Any]:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(
                host, port, ssl=client_context(identity, key), server_hostname=None, limit=MAX_MESSAGE,
                ssl_handshake_timeout=TIMEOUT_S), TIMEOUT_S + 1)
        except (ssl.SSLError, ConnectionResetError, ConnectionAbortedError) as exc:  # reached it, but the key did not fit
            raise LinkError("Code ghalat hai, ya waqt khatam ho gaya" if pair else
                            "Doosre PC ne is PC ko nahi pehchana (shayad wahan se hata diya gaya) — dobara jorein") from exc
        except (OSError, asyncio.TimeoutError) as exc:
            raise LinkError("raabta nahi hua (PC band hai, NOVA nahi chal raha, ya network alag hai)") from exc
        try:
            if used_certificate(writer):
                raise LinkError("Kisi aur ne jawab diya — raabta band kar diya")
            client_nonce = secrets.token_hex(16)
            await send(writer, {"type": "hello", "id": self.id, "nonce": client_nonce, "pair": pair})
            hello = await receive(reader)
            server_id, server_nonce = hello.get("id"), hello.get("nonce")
            if not (isinstance(server_id, str) and PC_ID.match(server_id) and isinstance(server_nonce, str)):
                raise LinkError("Doosre PC ka jawab sahi nahi")
            if expect_id and server_id != expect_id:
                raise LinkError("Is pate par ab koi aur PC hai")
            if not proof_ok(hello.get("proof"), key, "server", client_nonce, server_nonce, self.id, server_id):
                raise LinkError("Doosre PC ki pehchan sabit nahi hui")
            await send(writer, {"type": "auth", "request": message,
                                "proof": proof(key, "client", client_nonce, server_nonce, self.id, server_id)})
            reply = await receive(reader, timeout)
        except (OSError, ssl.SSLError) as exc:
            raise LinkError("raabta beech mein toot gaya") from exc
        finally:
            await close(writer)
        reply["_server_id"], reply["_server_name"] = server_id, clean_name(hello.get("name"))
        return reply

    async def ping_all(self) -> None:
        """Check every paired PC now (and look for new ones)."""
        await self.apply(refresh_network=True)
        if self._beacon:
            self._beacon.announce(query=True)
        peers = self.db.list_peers()
        if self.running and peers:
            await asyncio.gather(*(self._ping(p["id"]) for p in peers))
        await self._changed()

    async def _ping(self, peer_id: str) -> None:
        with contextlib.suppress(LinkError):
            await self.request(peer_id, {"type": "ping"}, timeout=4)

    async def unpair(self, peer_id: str) -> bool:
        peer = self.db.get_peer(peer_id)
        if peer is None:
            return False
        with contextlib.suppress(LinkError):  # tell the other PC too (if it is on); either way the key goes here
            await self.request(peer_id, {"type": "unpair"}, timeout=4)
        self.db.delete_peer(peer_id)
        self._keys.pop(peer_id, None)
        self._log("unpaired", f"'{peer['name']}' ko hata diya")
        await self._changed(f"'{peer['name']}' ab jura hua nahi")
        return True

    async def set_remote_allowed(self, peer_id: str, allowed: bool) -> bool:
        peer = self.db.get_peer(peer_id)
        if peer is None:
            return False
        self.db.update_peer(peer_id, remote_allowed=int(allowed))
        self._log("remote_permission", f"'{peer['name']}' ko is PC par kaam karne ki ijazat "
                  + ("di" if allowed else "wapas li"))
        await self._changed(f"'{peer['name']}': remote kaam " + ("on" if allowed else "off"))
        return True

    # ------------------------------------------------------------------ the link server (a paired PC asks)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        host = (writer.get_extra_info("peername") or ("?",))[0]
        try:
            hello = await receive(reader)
            client_id, client_nonce, pairing = hello.get("id"), hello.get("nonce"), hello.get("pair") is True
            if hello.get("type") != "hello" or not (isinstance(client_id, str) and PC_ID.match(client_id)
                                                    and isinstance(client_nonce, str) and len(client_nonce) <= 64):
                return
            key = (self.pairing.key if pairing and self.pairing and self._pairing_open() else
                   None if pairing else self._key(client_id))
            if key is None:
                return
            server_nonce = secrets.token_hex(16)
            await send(writer, {"type": "hello", "id": self.id, "name": self.name, "nonce": server_nonce,
                                "proof": proof(key, "server", client_nonce, server_nonce, client_id, self.id)})
            auth = await receive(reader)
            if not proof_ok(auth.get("proof"), key, "client", client_nonce, server_nonce, client_id, self.id):
                return
            request = auth.get("request") if isinstance(auth.get("request"), dict) else {}
            reply = (await self._accept_pairing(client_id, request, host) if pairing
                     else await self._serve(client_id, request, host))
            await send(writer, reply)
        except (LinkError, OSError, ssl.SSLError):
            pass
        except Exception:  # one bad request must never stop the server
            log.exception("Multi-PC request failed")
        finally:
            await close(writer)

    def _rate_ok(self, peer_id: str) -> bool:
        times = self._rate.setdefault(peer_id, deque())
        now = self.clock()
        while times and now - times[0] > 60:
            times.popleft()
        if len(times) >= REQUESTS_PER_MINUTE:
            return False
        times.append(now)
        return True

    async def _serve(self, peer_id: str, request: dict[str, Any], host: str) -> dict[str, Any]:
        peer = self.db.get_peer(peer_id)
        if peer is None:
            return {"ok": False, "error": "Ye PC jura hua nahi"}
        if not self._rate_ok(peer_id):
            return {"ok": False, "error": "Bohat zyada darkhwastein — thori der baad"}
        self._answered[peer_id] = self.clock()
        self.db.update_peer(peer_id, host=host, last_seen=time.strftime("%Y-%m-%dT%H:%M:%S"))
        kind = request.get("type")
        allowed = bool(peer["remote_allowed"])
        if kind == "ping":
            return {"ok": True, "version": self.version, "allows_you": allowed}
        if kind == "unpair":
            self.db.delete_peer(peer_id)
            self._keys.pop(peer_id, None)
            self._log("unpaired", f"'{peer['name']}' ne jor khatam kiya")
            await self._changed(f"'{peer['name']}' ne jor khatam kar diya")
            return {"ok": True}
        if not allowed:
            self._log("remote_refused", f"'{peer['name']}' ki darkhwast — ijazat nahi (Remote kaam off)",
                      "refused_by_nova", "refused")
            return {"ok": False, "allows_you": False,
                    "refused": f"{self.name} par is PC ko kaam karwane ki ijazat nahi. {self.name} par NOVA → PCs "
                               f"mein '{peer['name']}' ke liye \"Remote kaam\" on karein."}
        if kind == "status" and self.status_info is not None:
            return {"ok": True, "allows_you": True, "info": await self.status_info()}
        if kind == "plan" and self.plan is not None:
            text = " ".join(str(request.get("text") or "").split())[:500]
            if not text:
                return {"ok": False, "error": "Kya karna hai?"}
            return {"ok": True, "allows_you": True, **await self.plan(peer, text)}
        if kind == "run" and self.run is not None:
            return {"ok": True, "allows_you": True,
                    **await self.run(peer, str(request.get("plan_id") or ""), request.get("approved") is True)}
        return {"ok": False, "error": "Ye darkhwast samajh nahi aayi"}
