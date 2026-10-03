"""Multi-PC Agent (this PC sends): "Office PC par Chrome kholo", "Laptop ka haal batao", "mere PCs dikhao".

A command is for another PC only when it names a PAIRED PC ("<name> par ..."); this is decided before the AI brain,
so a command meant for another PC can never run here by mistake. The other PC understands the command itself and
says what it would do; anything that needs permission is asked HERE (the user is here), then it runs THERE.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

from ..agents.computer import ControlOutcome
from ..agents.prepared import Prepared, Reply
from ..ai.base import Intent, Understanding
from ..language import detect_language
from .link import LinkError
from .service import MultiPcService

MULTIPC_INTENTS = {"remote_command", "pc_status"}
Progress = Callable[[str], Awaitable[None]]

_PLACE = r"(?:par|pe|pr|mein|me|main|on)"
_PC_WORD = r"(?:pc|computer|laptop)"
LIST_PCS = re.compile(
    r"^(?:mere|meray|sab|saare|tamam|my)?\s*(?:jure\s+hue\s+)?(?:pcs|computers|laptops)\s+(?:ka\s+haal\s+|ki\s+list\s+)?"
    r"(?:dikhao|batao)$|^kaun\s+se\s+(?:pcs?|computers?)\s+(?:jure|connected|online)\s+(?:hain|hai)$"
    r"|^sab\s+(?:pcs?|computers?)\s+ka\s+haal\s+batao$|^(?:show|list)\s+(?:my\s+)?(?:pcs|computers)$", re.IGNORECASE)
OTHER_PC = re.compile(rf"^(?:doosre|dusre|dosre|doosra|dusra|other)\s+{_PC_WORD}\s+{_PLACE}\s+(?P<cmd>.+)$",
                      re.IGNORECASE)
# "<some name> PC par ..." for a PC that is NOT paired: answered with "not paired", never run here by a near match.
UNKNOWN_PC = re.compile(r"^(?:mere\s+|meray\s+|my\s+)?(?P<pc>[A-Za-z0-9][\w.'-]*(?:\s+[\w.'-]+){0,2}?)\s+(?:pc|computer)\s+"
                        r"(?:par|pe|pr)\s+(?P<cmd>.+)$", re.IGNORECASE)
NOT_A_NAME = {"is", "isi", "us", "ye", "yeh", "wo", "woh", "mere", "meray", "my", "apne", "apna", "this", "that", "kya",
              "kis", "kaunse", "konse", "kaun", "har", "sab", "new", "naye"}
STATUS_WORDS = re.compile(r"^(?:haal|hal|halat|status)\s+(?:batao|dikhao|kya\s+hai|kaisa\s+hai)$", re.IGNORECASE)
# A PC called "Desktop" or "Chrome" must not turn "Desktop par folder banao" into a remote command: such names need
# the word "PC" ("Desktop PC par ...").
LOCAL_WORDS = {"desktop", "documents", "document", "downloads", "download", "pictures", "music", "videos", "drive",
               "folder", "screen", "window", "browser", "chrome", "google", "youtube", "whatsapp", "is", "us", "yahan",
               "wahan", "isi", "ye", "yeh", "project", "file", "website", "internet", "web"}


def _flex(name: str) -> str:
    return r"\s+".join(re.escape(part) for part in name.split())


def _speakable(name: str) -> list[tuple[str, bool]]:
    """Ways to say a PC's name -> (name, needs the word PC). "Office PC" may be said "Office" too."""
    forms = [name]
    short = re.sub(r"\s+(?:pc|computer|laptop)$", "", name, flags=re.IGNORECASE).strip()
    if short and short.lower() != name.lower() and len(short) >= 2:
        forms.append(short)
    return [(f, f.lower() in LOCAL_WORDS) for f in forms]


def gb(n: int | float) -> str:
    return f"{n / 1024 ** 3:.0f} GB"


class MultiPcAgent:
    def __init__(self, service: MultiPcService) -> None:
        self.service = service

    # ------------------------------------------------------------------ understanding (before the AI brain)

    def understand(self, cleaned: str) -> Understanding | None:
        text = " ".join(cleaned.split())
        if not text:
            return None
        if LIST_PCS.search(text):
            return self._make(text, "pc_status", pc="")
        peers = self.service.db.list_peers()
        if m := OTHER_PC.search(text):
            only = peers[0] if len(peers) == 1 else None
            return self._make(text, "remote_command", pc=only["name"] if only else "", pc_id=only["id"] if only else "",
                              command=m.group("cmd").strip())
        for peer in sorted(peers, key=lambda p: -len(p["name"])):
            for form, needs_word in _speakable(peer["name"]):
                word = rf"\s+{_PC_WORD}" if needs_word else rf"(?:\s+{_PC_WORD})?"
                head = rf"^(?:mere\s+|meray\s+|my\s+)?{_flex(form)}{word}(?:\s+(?:wale|wala|wali))?"
                if m := re.match(head + rf"\s+{_PLACE}\s+(?P<cmd>.+)$", text, re.IGNORECASE):
                    return self._make(text, "remote_command", pc=peer["name"], pc_id=peer["id"],
                                      command=m.group("cmd").strip())
                if re.match(head + r"\s+(?:online|on|chal\s+raha)\s+hai\??$", text, re.IGNORECASE):
                    return self._make(text, "pc_status", pc=peer["name"], pc_id=peer["id"])
                if m := re.match(head + r"\s+(?:ka|ki|ke)\s+(?P<cmd>.+)$", text, re.IGNORECASE):
                    cmd = m.group("cmd").strip()
                    if STATUS_WORDS.match(cmd):
                        return self._make(text, "pc_status", pc=peer["name"], pc_id=peer["id"])
                    return self._make(text, "remote_command", pc=peer["name"], pc_id=peer["id"], command=cmd)
        if (m := UNKNOWN_PC.match(text)) and m.group("pc").split()[0].lower() not in NOT_A_NAME:
            return self._make(text, "remote_command", pc=m.group("pc"), pc_id="", command=m.group("cmd").strip())
        return None

    @staticmethod
    def _make(text: str, name: str, **entities: Any) -> Understanding:
        intent = Intent(name=name, confidence=0.95, language=detect_language(text), entities=entities,
                        provider="rule_based")
        return Understanding(intents=[intent], provider="rule_based")

    def _peer(self, intent: Intent) -> dict[str, Any] | None:
        pc_id = str(intent.entities.get("pc_id") or "")
        return self.service.db.get_peer(pc_id) if pc_id else None

    def _names(self) -> str:
        return ", ".join(p["name"] for p in self.service.db.list_peers())

    # ------------------------------------------------------------------ prepared-agent protocol

    async def prepare(self, intent: Intent, progress: Progress) -> Prepared | Reply:
        if intent.name == "pc_status":
            return Prepared(summary="PCs ka haal", scope_key="pc_status")
        peer = self._peer(intent)
        if peer is None:
            names, asked = self._names(), str(intent.entities.get("pc") or "")
            head = f"'{asked}' naam ka koi PC jura hua nahi. " if asked else "Kaun se PC par? "
            return Reply(head + (f"Jure hue PCs: {names}. Maslan: \"{names.split(', ')[0]} par Chrome kholo\"."
                                 if names else "Abhi koi PC jura hua nahi. NOVA → PCs tab se doosra PC jorein."))
        if not self.service.running:
            return Reply(f"Multi-PC abhi chal nahi raha: {self.service.reason}")
        command = str(intent.entities.get("command") or "")
        await progress(f"{peer['name']} se poochh raha hai: \"{command[:80]}\"")
        try:
            reply = await self.service.request(peer["id"], {"type": "plan", "text": command}, timeout=90)
        except LinkError as exc:
            return Reply(f"{peer['name']} se raabta nahi ho saka: {exc}.")
        if not reply.get("ok"):
            return Reply(str(reply.get("refused") or reply.get("error") or "Doosre PC ne mana kar diya"), refused=True)
        steps = [s for s in reply.get("steps", []) if isinstance(s, dict)]
        usable = [s for s in steps if s.get("status") != "refused"]
        if not usable:
            reasons = "; ".join(f"{s.get('description')} — {s.get('result')}" for s in steps)
            return Reply(f"{peer['name']}: {reasons or 'kuch karne ko nahi mila'}.", refused=True)
        ask = [s for s in usable if s.get("status") == "ask"]
        preview = "\n".join(
            f"{n}. {s.get('description')}" + {"ask": " (ijazat)", "refused": f" — nahi hoga: {s.get('result')}"}.get(
                str(s.get("status")), "") for n, s in enumerate(steps, start=1))
        reasons = [f"Ye kaam doosre PC ({peer['name']}) par hoga"]
        reasons += [str(r) for s in ask for r in s.get("reasons", [])][:3]
        return Prepared(summary=f"{peer['name']} par: " + "; ".join(str(s.get("description")) for s in usable)[:300],
                        scope_key=f"remote@{peer['id']}", preview=preview, always_ask=bool(ask),
                        min_risk="medium" if ask else "low", reasons=reasons,
                        data={"peer_id": peer["id"], "peer_name": peer["name"], "plan_id": reply.get("plan_id")})

    async def run(self, intent: Intent, prepared: Prepared, approved: bool, progress: Progress) -> ControlOutcome:
        if intent.name == "pc_status":
            return ControlOutcome(await self.describe(str(intent.entities.get("pc_id") or "")), "pc_status", True,
                                  "not_applicable")
        name = prepared.data["peer_name"]
        await progress(f"{name} par kaam ho raha hai...")
        try:
            reply = await self.service.request(prepared.data["peer_id"], {
                "type": "run", "plan_id": prepared.data["plan_id"], "approved": approved}, timeout=180)
        except LinkError as exc:
            return ControlOutcome(f"{name} se raabta toot gaya ({exc}). Wahan kaam hua ya nahi, {name} par dekh lein.",
                                  "remote_command", False, "unverified")
        if not reply.get("ok"):
            return ControlOutcome(f"{name}: {reply.get('refused') or reply.get('error')}", "remote_command", False,
                                  "not_applicable")
        verification = reply.get("verification")
        return ControlOutcome(f"{name}: {reply.get('response')}", "remote_command", reply.get("executed") is True,
                              verification if verification in ("passed", "failed", "unverified") else "not_applicable",
                              detail=name)

    # ------------------------------------------------------------------ "PCs ka haal"

    async def describe(self, peer_id: str = "") -> str:
        peers = [p for p in self.service.db.list_peers() if not peer_id or p["id"] == peer_id]
        if not peers:
            return "Abhi koi PC jura hua nahi. NOVA → PCs tab se doosra PC jorein."
        if not self.service.running:
            return f"Multi-PC abhi chal nahi raha: {self.service.reason}"
        lines = await asyncio.gather(*(self._line(p) for p in peers))
        return "\n".join(lines) if len(lines) > 1 else lines[0]

    async def _line(self, peer: dict[str, Any]) -> str:
        try:
            reply = await self.service.request(peer["id"], {"type": "status"}, timeout=8)
        except LinkError:
            return f"{peer['name']}: raabta nahi (band hai ya network par nahi)"
        info = reply.get("info")
        if not reply.get("ok") or not isinstance(info, dict):
            return f"{peer['name']}: online — maloomat ki ijazat nahi ({peer['name']} par \"Remote kaam\" off hai)"
        parts = [f"CPU {info.get('cpu_percent', 0):.0f}%",
                 f"RAM {gb(info.get('ram_free', 0))} free / {gb(info.get('ram_total', 0))}"]
        if info.get("disk_total"):
            parts.append(f"C: {gb(info.get('disk_free', 0))} free")
        if info.get("battery") is not None:
            parts.append(f"battery {info['battery']:.0f}%" + (" (charge ho rahi hai)" if info.get("plugged") else ""))
        return f"{peer['name']}: online — " + ", ".join(parts)
