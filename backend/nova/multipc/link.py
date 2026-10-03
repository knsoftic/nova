"""The encrypted PC-to-PC link: TLS 1.3 with a pre-shared key per pair of PCs (Python's own ssl, no certificates).

- Pairing: the PC being joined shows a one-time code (12 characters, ~60 bits) that is typed on the other PC. Both
  derive the same pairing key from it (PBKDF2, slow on purpose). That key opens exactly one TLS session, inside which
  the joined PC hands over a fresh random 32-byte link key. The code itself never travels over the network.
- Every later connection uses the link key: a PC that does not know it cannot even finish the TLS handshake.
- Inside the session both sides also prove which PC they are (HMAC over fresh nonces from both sides), and the
  client sends its request only after the other PC has proven it knows the key. A server that answers with a
  certificate instead of the pre-shared key is refused.
- Messages are single JSON lines of at most 64 KB.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import ssl
from typing import Any, Callable

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U (easy to read out and type)
CODE_LENGTH = 12
PAIR_SALT = b"nova-multipc-pair-v1"
PBKDF2_ROUNDS = 200_000
MAX_MESSAGE = 64 * 1024
PAIR_PREFIX = "pair:"
TIMEOUT_S = 10.0
PC_ID = re.compile(r"^[0-9a-f]{16}$")


class LinkError(Exception):
    """The other PC could not be reached, refused us, or broke the protocol (message is Roman Urdu)."""


def new_pc_id() -> str:
    return secrets.token_hex(8)


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, CODE_LENGTH, 4))


def normalize_code(code: str) -> str | None:
    """What the user typed -> the code, or None. Spaces/dashes and look-alike letters (O/0, I/L/1) are forgiven."""
    value = code.upper().translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    value = "".join(ch for ch in value if ch not in " -_")
    if len(value) != CODE_LENGTH or any(ch not in ALPHABET for ch in value):
        return None
    return value


def pairing_key(normalized_code: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", normalized_code.encode("ascii"), PAIR_SALT, PBKDF2_ROUNDS, 32)


def new_link_key() -> bytes:
    return secrets.token_bytes(32)


def proof(key: bytes, role: str, client_nonce: str, server_nonce: str, client_id: str, server_id: str) -> str:
    text = f"nova-multipc-v1|{role}|{client_nonce}|{server_nonce}|{client_id}|{server_id}"
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()


def proof_ok(given: Any, key: bytes, role: str, client_nonce: str, server_nonce: str, client_id: str,
             server_id: str) -> bool:
    return isinstance(given, str) and hmac.compare_digest(
        proof(key, role, client_nonce, server_nonce, client_id, server_id), given)


def server_context(lookup: Callable[[str], bytes | None]) -> ssl.SSLContext:
    """`lookup(identity)` -> the key for that PSK identity, or None (unknown: the handshake fails)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3

    def callback(identity: str | None) -> bytes:
        return (lookup(identity) if identity else None) or b""

    ctx.set_psk_server_callback(callback)
    return ctx


def client_context(identity: str, key: bytes) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the pre-shared key authenticates the other PC; certificates are refused below
    ctx.set_psk_client_callback(lambda hint: (identity, key))
    return ctx


def used_certificate(writer: asyncio.StreamWriter) -> bool:
    """A real pre-shared-key handshake has no server certificate; one means someone else answered."""
    obj = writer.get_extra_info("ssl_object")
    return obj is None or bool(obj.getpeercert(binary_form=True))


async def send(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > MAX_MESSAGE:
        raise LinkError("Message bohat bara hai")
    writer.write(data)
    await writer.drain()


async def receive(reader: asyncio.StreamReader, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    try:
        line = await asyncio.wait_for(reader.readuntil(b"\n"), timeout)
        message = json.loads(line)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError) as exc:
        raise LinkError("Doosre PC ka jawab sahi nahi") from exc
    except asyncio.TimeoutError as exc:
        raise LinkError("Doosre PC ne waqt par jawab nahi diya") from exc
    if not isinstance(message, dict):
        raise LinkError("Doosre PC ka jawab sahi nahi")
    return message


async def close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 2)
    except (OSError, ssl.SSLError, asyncio.TimeoutError):
        pass


async def loopback_selftest() -> bool:
    """Self-test: a TLS-PSK round trip on 127.0.0.1 with a throwaway key (proves this Python's OpenSSL can do it)."""
    key, ident = new_link_key(), "selftest"

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await send(writer, {"echo": (await receive(reader, 5)).get("ping")})
        except (LinkError, OSError, ssl.SSLError):
            pass
        finally:
            await close(writer)

    server = await asyncio.start_server(echo, "127.0.0.1", 0, ssl=server_context(lambda i: key if i == ident else None),
                                        limit=MAX_MESSAGE, ssl_handshake_timeout=5)
    try:
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            "127.0.0.1", port, ssl=client_context(ident, key), server_hostname=None, limit=MAX_MESSAGE), 5)
        try:
            if used_certificate(writer):
                return False
            await send(writer, {"ping": "ok"})
            return (await receive(reader, 5)).get("echo") == "ok"
        finally:
            await close(writer)
    except (OSError, ssl.SSLError, LinkError, asyncio.TimeoutError):
        return False
    finally:
        server.close()
