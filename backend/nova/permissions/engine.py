"""Permission Engine: risk classification, asking the user, remembered approvals, audit trail.

Rules (spec section 19):
- low risk runs without asking;
- medium risk asks, unless the user earlier chose "don't ask again" for exactly this action;
- high risk always asks, and can never be remembered;
- no answer within the timeout counts as "no". NOVA never bypasses this.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ..db import Database
from ..events import EventBus, EventType, NovaEvent

log = logging.getLogger("nova.permissions")

PERMISSIONS = "Permission Engine"
DEFAULT_TIMEOUT_S = 60.0
Risk = Literal["low", "medium", "high"]
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

# Typing into these runs commands: anything typed there could change or damage the system.
TERMINAL_PROCESSES = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe", "conhost.exe",
                      "bash.exe", "wsl.exe", "mintty.exe", "openconsole.exe"}
# Buttons whose effect is irreversible or reaches other people / money.
DANGEROUS_CLICK = re.compile(
    r"\b(delete|remove|uninstall|format|erase|wipe|reset|send|submit|pay|payment|buy|purchase|checkout|order|"
    r"transfer|confirm|sign\s*out|log\s*out|unsubscribe|publish|post|share|bhejo|mitao|khareedo)\b"
    r"|حذف|بھیجیں|ادائیگی|ڈیلیٹ",
    re.IGNORECASE,
)
CREDENTIAL_TEXT = re.compile(r"\b(password|passwd|pin|otp|cvv|card\s*number|pass\s*code)\b|\b\d{12,19}\b", re.IGNORECASE)
UNSAVED_MARKERS = re.compile(r"^\*|\*\s|●|\bunsaved\b|\buntitled\b", re.IGNORECASE)
BIG_DELETE_FILES = 100
BIG_DELETE_BYTES = 1024**3


@dataclass
class TargetContext:
    """The window (or web page) an action would affect, resolved when the plan is made."""

    title: str | None = None
    process: str | None = None  # e.g. "notepad.exe", or "browser:example.com" for NOVA's browser
    element: str | None = None  # the exact element text on a web page (for clicks)
    executable: bool = False  # a download that is a program/script
    # File/Coding steps (from agents.prepared.Prepared)
    scope_key: str | None = None  # what a remembered approval covers
    preview: str | None = None  # diff, organize plan or command, shown in the dialog
    count: int = 0
    size: int = 0
    executes_code: bool = False
    network: bool = False
    always_ask: bool = False


class PermissionItem(BaseModel):
    step_id: int
    intent: str
    description: str  # Roman Urdu, what will happen
    risk: Risk
    reasons: list[str] = Field(default_factory=list)  # why it is risky (shown to the user)
    target: str | None = None
    scope: str  # what a remembered approval would cover
    rememberable: bool
    preview: str | None = None  # shown (not spoken): the diff, plan or command that will run


class PermissionRequest(BaseModel):
    id: str
    task_id: str
    items: list[PermissionItem]
    max_risk: Risk
    question: str  # Roman Urdu, shown and spoken
    timeout_s: float
    source: str = "text"

    @property
    def rememberable(self) -> bool:
        return all(i.rememberable for i in self.items)


class Decision(BaseModel):
    approved: bool
    decided_by: str  # user_ui | user_text | user_voice | rule | timeout
    remembered: bool = False


def classify(intent: str, entities: dict[str, object], base_risk: Risk, target: TargetContext) -> tuple[Risk, list[str]]:
    """Raise the planner's risk using context: where the action happens and what it does."""
    risk, reasons = base_risk, []
    process = (target.process or "").lower()

    def escalate(new: Risk, reason: str) -> None:
        nonlocal risk
        if RISK_ORDER[new] > RISK_ORDER[risk]:
            risk = new
        reasons.append(reason)

    if intent in ("type_text", "keyboard_shortcut") and process in TERMINAL_PROCESSES:
        escalate("high", "Terminal mein likha gaya text command ban kar chal sakta hai")
    if intent == "type_text" and CREDENTIAL_TEXT.search(str(entities.get("text", ""))):
        escalate("high", "Text mein password/card jaisi maloomat lagti hai")
    if intent == "mouse_click" and DANGEROUS_CLICK.search(str(entities.get("target", ""))):
        escalate("high", "Ye button kuch mita, bhej ya khareed sakta hai — wapas nahi hota")
    if intent == "close_app":
        reasons.append("Agar kaam save nahi hua to app save karne ka poochegi")
        if target.title and UNSAVED_MARKERS.search(target.title):
            reasons.append("Window ke naam se lagta hai kuch unsaved hai")
    if intent == "keyboard_shortcut" and entities.get("keys") in ("save",):
        reasons.append("File save/overwrite ho sakti hai")
    # Browser actions: judged by what is actually on the page (element text), not only the user's words.
    if intent == "browser_click":
        label = f"{entities.get('target', '')} {target.element or ''}"
        if DANGEROUS_CLICK.search(label):
            escalate("high", "Ye button kuch mita, bhej ya khareed sakta hai — wapas nahi hota")
    if intent == "browser_type" and CREDENTIAL_TEXT.search(str(entities.get("text", ""))):
        escalate("high", "Text mein password/card jaisi maloomat lagti hai")
    if intent == "download":
        reasons.append("File Downloads\\NOVA mein save hogi; NOVA use kholega nahi")
        if target.executable:
            escalate("high", "Ye program/script file hai — chalane par computer ko nuqsan pohncha sakti hai")
    # Files and code: judged by what was actually resolved (how many files, what runs).
    if intent == "delete_file":
        reasons.append("Recycle Bin mein jayegi — wahan se Restore ho sakti hai")
        if target.count > BIG_DELETE_FILES or target.size > BIG_DELETE_BYTES:
            escalate("high", f"Bohat bara delete: {target.count} files / {target.size // (1024 * 1024)} MB")
    if intent in ("rename_file", "move_file", "edit_file", "organize_folder", "fix_error", "modify_code"):
        reasons.append("Wapas ho sakta hai: 'pichla file kaam undo karo'")
    if intent in ("fix_error", "modify_code"):
        reasons.insert(0, "Code ki tabdeeli neeche dikhai gayi hai; purani file ka backup rakha jayega")
    if target.executes_code:
        escalate("medium", "Project ka apna code/scripts is PC par chalenge")
    if target.network:
        escalate("medium", "Internet se packages download honge; un ke install scripts bhi chal sakte hain")
    return risk, reasons


def scope_for(intent: str, entities: dict[str, object], target: TargetContext) -> str:
    """A remembered approval covers the same action in the same app - never anything broader."""
    if target.scope_key:  # File/Coding: same action, same folder/project/command
        return f"{intent}:{target.scope_key}".lower()
    process = (target.process or "unknown").lower()
    match intent:
        case "type_text":
            return f"type@{process}"
        case "keyboard_shortcut":
            return f"{entities.get('keys')}@{process}"
        case "mouse_click":
            return f"click:{str(entities.get('target', '')).lower()}@{process}"
        case "close_app":
            return f"close:{str(entities.get('app') or target.title or '').lower()}"
        case "browser_click":
            return f"click:{str(target.element or entities.get('target', '')).lower()}@{process}"
        case "browser_type":
            return f"type@{process}"
        case "download":
            return f"download@{process}"
    return f"{intent}@{process}"


def build_question(items: list[PermissionItem]) -> str:
    lines = []
    if any(i.risk == "high" for i in items):
        lines.append("Dhyan dein, ye khatarnak kaam ho sakta hai.")
    if len(items) == 1:
        lines.append(f"Ijazat chahiye: {items[0].description}.")
    else:
        lines.append("Ijazat chahiye: " + "; ".join(f"{n}) {i.description}" for n, i in enumerate(items, 1)) + ".")
    for item in items:
        lines += [f"({r})" for r in item.reasons[:2]]
    lines.append("Kya main ye karoon? Haan ya nahi kahein.")
    return " ".join(lines)


# Yes/no answers by text or voice (Roman Urdu, English, Urdu, Hindi).
YES = re.compile(
    r"^(?:haan|han|haa|ha|ji|jee|ji haan|jee haan|yes|yeah|yep|ok|okay|theek hai|thik hai|theek|kar do|karo|"
    r"kardo|ijazat hai|approve|allow|bilkul|zaroor|ہاں|جی|جی ہاں|ٹھیک ہے|کر دو|हाँ|हां|जी|ठीक है|कर दो)"
    r"(?:\s+(?:hai|karo|kar do|ji|please|plz|bhai))*[\s.!۔]*$",
    re.IGNORECASE,
)
NO = re.compile(
    r"^(?:nahi|nahin|nai|na|no|nope|mat karo|mat|ruk jao|ruko|cancel|rehne do|deny|stop|نہیں|نا|مت کرو|رکو|"
    r"नहीं|ना|मत करो|रुको)(?:\s+(?:karo|karna|ji|please|bhai))*[\s.!۔]*$",
    re.IGNORECASE,
)


def parse_answer(text: str) -> bool | None:
    t = text.strip().lower()
    if NO.match(t):
        return False
    if YES.match(t):
        return True
    return None


class PermissionEngine:
    def __init__(self, db: Database, bus: EventBus, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.db = db
        self.bus = bus
        self.timeout_s = timeout_s
        self._pending: dict[str, tuple[PermissionRequest, asyncio.Future[Decision]]] = {}

    def make_item(self, step_id: int, intent: str, entities: dict[str, object], description: str,
                  base_risk: Risk, target: TargetContext) -> PermissionItem:
        risk, reasons = classify(intent, entities, base_risk, target)
        detail = {
            "type_text": f": \"{str(entities.get('text', ''))[:60]}\"",
            "mouse_click": f": \"{entities.get('target', '')}\"",
            "keyboard_shortcut": f": {entities.get('keys', '')}",
            "close_app": f": {entities.get('app') or target.title or ''}",
            "browser_click": f": \"{target.element or entities.get('target', '')}\"",
            "browser_type": f": \"{str(entities.get('text', ''))[:60]}\""
                            + (f", \"{target.element}\" khane mein" if target.element else ""),
            "download": f": \"{target.element or entities.get('target', '')}\"",
        }.get(intent, "")
        where = f" ({target.title})" if target.title and intent != "close_app" else ""
        if target.scope_key:  # File/Coding: the agent's own summary already names the exact target
            detail, where = f": {target.title}", ""
        return PermissionItem(step_id=step_id, intent=intent, description=f"{description}{detail}{where}",
                              risk=risk, reasons=reasons, target=target.title,
                              scope=scope_for(intent, entities, target),
                              rememberable=risk == "medium" and not target.always_ask, preview=target.preview)

    # ------------------------------------------------------------------ requests

    @property
    def pending(self) -> list[PermissionRequest]:
        return [req for req, _ in self._pending.values()]

    def covered_by_rule(self, item: PermissionItem) -> dict | None:
        if item.risk != "medium":
            return None  # high risk is always asked
        return self.db.find_permission_rule(item.intent, item.scope)

    async def request(self, task_id: str, items: list[PermissionItem], source: str = "text") -> dict[int, Decision]:
        """Returns a decision per step. Steps covered by a remembered approval are not asked again."""
        decisions: dict[int, Decision] = {}
        to_ask: list[PermissionItem] = []
        for item in items:
            if rule := self.covered_by_rule(item):
                self.db.touch_permission_rule(rule["id"])
                decisions[item.step_id] = Decision(approved=True, decided_by="rule")
            else:
                to_ask.append(item)
        if not to_ask:
            return decisions

        max_risk: Risk = max((i.risk for i in to_ask), key=lambda r: RISK_ORDER[r])
        req = PermissionRequest(id=uuid.uuid4().hex[:12], task_id=task_id, items=to_ask, max_risk=max_risk,
                                question=build_question(to_ask), timeout_s=self.timeout_s, source=source)
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        self._pending[req.id] = (req, future)
        self.db.add_permission_request(req.id, task_id, json.dumps([i.model_dump() for i in to_ask],
                                                                   ensure_ascii=False), max_risk)
        await self.bus.publish(NovaEvent(type=EventType.PERMISSION_REQUIRED, task_id=task_id, agent=PERMISSIONS,
                                         message=req.question,
                                         data={**req.model_dump(), "rememberable": req.rememberable}))
        try:
            decision = await asyncio.wait_for(asyncio.shield(future), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            decision = Decision(approved=False, decided_by="timeout")
            await self._record(req, decision)
        finally:
            self._pending.pop(req.id, None)
        for item in to_ask:
            decisions[item.step_id] = decision
        return decisions

    async def decide(self, request_id: str, approved: bool, decided_by: str, remember: bool = False) -> bool:
        entry = self._pending.get(request_id)
        if entry is None or entry[1].done():
            return False
        req, future = entry
        remember = remember and approved and req.rememberable
        decision = Decision(approved=approved, decided_by=decided_by, remembered=remember)
        if remember:
            for item in req.items:
                self.db.add_permission_rule(item.intent, item.scope, item.description)
        await self._record(req, decision)
        future.set_result(decision)
        return True

    async def answer_latest(self, text: str, decided_by: str) -> bool | None:
        """Treat a typed/spoken "haan"/"nahi" as the answer to the newest open request."""
        if not self._pending or (answer := parse_answer(text)) is None:
            return None
        latest = list(self._pending)[-1]
        await self.decide(latest, answer, decided_by)
        return answer

    async def _record(self, req: PermissionRequest, decision: Decision) -> None:
        status = "approved" if decision.approved else ("timeout" if decision.decided_by == "timeout" else "denied")
        self.db.decide_permission_request(req.id, status, decision.decided_by, decision.remembered)
        self.db.add_activity(
            task_id=req.task_id, task_name="permission_request", agent=PERMISSIONS, action="ask_user",
            permission_status=status, execution_status="decided", verification_status="not_applicable",
            final_result=f"{status} by {decision.decided_by}" + (" (yaad rakha)" if decision.remembered else "")
                         + f" · risk {req.max_risk} · " + "; ".join(i.description for i in req.items),
        )
        message = {"approved": "Ijazat mil gayi", "denied": "Ijazat nahi mili", "timeout": "Jawab nahi aaya — kaam nahi kiya"}
        await self.bus.publish(NovaEvent(type=EventType.PERMISSION_DECIDED, task_id=req.task_id, agent=PERMISSIONS,
                                         message=message[status] + (" (aage se nahi poochenge)" if decision.remembered else ""),
                                         data={"request_id": req.id, "status": status, "decided_by": decision.decided_by,
                                               "remembered": decision.remembered}))
