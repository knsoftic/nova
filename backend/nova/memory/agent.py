"""Memory Agent: long-term memory, conversation history and workflow memory - kept on this PC, under the user's control.

- NOVA remembers a fact only when the user says "yaad rakho ke ...", or says "haan" when NOVA asks after a personal
  statement ("mera naam Ahmed hai" -> "Ye yaad rakhoon?"). Never silently; passwords/PINs/card numbers never.
- Forgetting memories and deleting history are permanent, so they are always asked first (all of it: high risk).
- Workflows are learned by asking once ("Kaun se applications open karoon?") and then run as normal commands.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from ..agents.computer import ControlOutcome
from ..agents.prepared import Prepared, Reply
from ..ai.base import Intent
from ..db import Database
from ..permissions.engine import parse_answer
from . import facts as F
from .history import LABELS, period_of, period_range, record, search_terms, line
from .short_term import ShortTermMemory
from .workflows import MAX_STEPS, StepResolver, WorkflowStep, merge, numbered, split_items, workflow_key

NAME = "Memory Agent"
MEMORY_INTENTS = {"remember_fact", "recall_memory", "forget_memory", "search_history", "clear_history",
                  "save_workflow", "list_workflows", "delete_workflow", "run_workflow", "repeat_last"}
Progress = Callable[[str], Awaitable[None]]
Notify = Callable[[dict[str, Any]], Awaitable[None]]

PRONOUN_FACTS = {"ye", "yeh", "ye baat", "yeh baat", "isko", "is ko", "is baat ko", "wo", "woh", "wo baat", "this",
                 "that", "it", "is"}
ALL_WORDS = re.compile(r"^(?:sab|sab\s+kuch|saari|everything|all|mere\s+(?:baare|bare)\s+mein|about\s+me)$", re.IGNORECASE)
YES_MORE = re.compile(r"^(?:(?:haan|han|ji|jee)\s+)?(?:yaad\s+(?:rakho|rakh\s+lo|rakhna|kar\s+lo)|rakh\s+lo|save\s+(?:karo|"
                      r"kar\s+lo)|zaroor(?:\s+rakho)?|remember\s+it)[\s.!۔]*$", re.IGNORECASE)
NO_MORE = re.compile(r"^(?:(?:nahi|nahin|no)\s+)?(?:yaad\s+)?(?:mat\s+rakho|zaroorat\s+nahi|rehne\s+do|chhoro|chhor\s+do|"
                     r"cancel|don'?t)[\s.!۔]*$", re.IGNORECASE)
# A reply to "Kaun se applications open karoon?" is a list of names; anything with these words is a new command.
OPEN_VERBS = re.compile(r"\b(?:open\s+kar\s+do|open\s+karo|khol\s+do|kholo|chala\s+do|chalao|start\s+karo|launch\s+karo|"
                        r"open|launch)\b", re.IGNORECASE)
COMMAND_WORDS = re.compile(r"\?|\b(?:karo|kar\s+do|kardo|batao|bata\s+do|dikhao|bhejo|likho|band|delete|mitao|kya|kaise|"
                           r"kitna|kitni|kyun|search|dhoondo|dhundo|what|how|why)\b", re.IGNORECASE)
PURGE_EVERY_S = 3600
HABIT_WORDS = re.compile(r"\b(?:aadat\w*|adat\w*|habits?|patterns?)\b", re.IGNORECASE)


@dataclass
class FollowUp:
    """How NOVA's open question was answered: a plain reply, or commands to run (e.g. save + run a workflow)."""

    reply: str | None = None
    intents: list[Intent] = field(default_factory=list)
    workflow: str | None = None


def yes_no(text: str) -> bool | None:
    if NO_MORE.match(text):
        return False
    if YES_MORE.match(text):
        return True
    return parse_answer(text)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


class MemoryAgent:
    def __init__(
        self,
        db: Database,
        short_term: ShortTermMemory,
        resolver: StepResolver,
        *,
        ensure_profile: Callable[[], Awaitable[Any]] | None = None,
        history_days: Callable[[], int] = lambda: 90,
        notify: Notify | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.db = db
        self.short_term = short_term
        self.resolver = resolver
        self.ensure_profile = ensure_profile
        self.history_days = history_days
        self.notify = notify
        self.now = now
        self._last_purge = 0.0

    # ------------------------------------------------------------------ used by the orchestrator

    def user_name(self) -> str | None:
        row = self.db.memory_for_slot("name")
        return row["value"] if row else None

    def context_for(self, text: str, limit: int = 5) -> list[str]:
        """Memories related to what the user just said, for the AI brain (only those, to keep prompts short)."""
        return [m["text"] for m in F.rank(text, self.db.list_memories(), limit)]

    def workflow(self, name: str) -> tuple[dict[str, Any], list[WorkflowStep]] | None:
        row = self.db.get_workflow(workflow_key(name)) if name else None
        if row is None:
            return None
        return row, [WorkflowStep.from_dict(d) for d in row["steps"]]

    def history(self, query: str = "", period: str = "", limit: int = 20, raw: bool = False) -> list[dict[str, Any]]:
        start, end = period_range(period, self.now())
        terms = [w for w in query.lower().split() if len(w) >= 2][:5] if raw else search_terms(query)
        # Earlier history answers repeat other records; they only show up in the plain (unfiltered) list.
        rows = self.db.search_conversations(terms, _iso(start), _iso(end), limit,
                                            exclude_intents=("search_history",) if terms or not raw else ())
        steps = self.db.activity_for_tasks([r["task_id"] for r in rows])
        return [record(r, steps[r["task_id"]]) for r in rows]

    def purge(self, force: bool = False) -> int:
        """Delete history older than the user's chosen number of days (0 = keep). At most once an hour."""
        if not force and time.monotonic() - self._last_purge < PURGE_EVERY_S:
            return 0
        self._last_purge = time.monotonic()
        days = self.history_days()
        if not days:
            return 0
        return self.db.delete_history(None, _iso(self.now() - timedelta(days=days)))

    async def changed(self, what: str, **data: Any) -> None:
        if self.notify is not None:
            await self.notify({"what": what, **data})

    # ------------------------------------------------------------------ follow-up answers

    async def answer(self, text: str, language: str = "unknown") -> FollowUp | None:
        """If NOVA asked something, read `text` as the answer. None: not an answer - handle it as a new command."""
        pending = self.short_term.take_pending()
        if pending is None:
            return None
        t = F.clean(text)
        if pending.kind == "remember":
            verdict = yes_no(t)
            if verdict is True:
                return FollowUp(intents=[Intent(name="remember_fact", confidence=1.0, language=language, provider="memory",
                                                entities={"fact": pending.data["fact"], "explicit": True})])
            if verdict is False:
                self.short_term.declined.add(F.norm(pending.data["fact"]))
                return FollowUp(reply="Theek hai, ye baat yaad nahi rakhi.")
            return None
        if pending.kind == "routine":  # "Inka workflow bana doon?" after NOVA noticed a habit
            verdict = yes_no(t)
            if verdict is True:
                return FollowUp(intents=[Intent(name="save_workflow", confidence=1.0, language=language,
                                                provider="memory", entities={"workflow": pending.data["name"],
                                                                             "steps": pending.data["steps"]})])
            if verdict is False:
                self.db.decline_routine(pending.data["key"])
                return FollowUp(reply="Theek hai, ye tajweez dobara nahi doonga.")
            return None
        if pending.kind == "workflow_steps":
            name, run = pending.data["name"], bool(pending.data.get("run"))
            if yes_no(t) is False:
                return FollowUp(reply="Theek hai, workflow nahi banaya.")
            if COMMAND_WORDS.search(OPEN_VERBS.sub(" ", t)):
                return None  # "RAM batao": the user moved on
            if self.ensure_profile is not None:
                await self.ensure_profile()
            steps, problems = await asyncio.to_thread(self.resolver.resolve_all, t)
            if not steps:
                if pending.attempts >= 1:
                    return FollowUp(reply="Workflow nahi bana — " + "; ".join(problems) + ".")
                question = "In mein se kuch nahi mila: " + "; ".join(problems) + ". Dobara batayein (maslan: Chrome, VS Code)."
                self.short_term.ask(pending.kind, question, pending.data, pending.ttl_s, pending.attempts + 1)
                return FollowUp(reply=question)
            save = Intent(name="save_workflow", confidence=1.0, language=language, provider="memory",
                          entities={"workflow": name, "steps": t, "then_run": run})
            return FollowUp(intents=[save] + ([s.intent(language) for s in steps] if run else []),
                            workflow=name if run else None)
        return None

    # ------------------------------------------------------------------ prepare

    async def prepare(self, intent: Intent, progress: Progress) -> Prepared | Reply:
        e = intent.entities
        match intent.name:
            case "remember_fact":
                return self._prepare_remember(e)
            case "recall_memory":
                return Prepared("Yaadein dekhna", "memory:recall", data={"query": F.clean(e.get("query") or "")})
            case "forget_memory":
                return self._prepare_forget(e)
            case "search_history":
                query = F.clean(e.get("query") or "")
                return Prepared("History mein dhoondna", "history:search",
                                data={"query": query, "period": e.get("period") or period_of(query)})
            case "clear_history":
                return self._prepare_clear(str(e.get("period") or ""))
            case "save_workflow":
                return await self._prepare_save_workflow(e)
            case "list_workflows":
                return Prepared("Workflows ki list", "workflow:list")
            case "delete_workflow":
                found = self.workflow(str(e.get("workflow") or ""))
                if found is None:
                    return Reply(f"\"{e.get('workflow') or ''}\" naam ka workflow nahi mila. Kahein \"mere workflows dikhao\".")
                row, steps = found
                return Prepared(f"'{row['name']}' workflow mitana", f"workflow:{row['name']}", preview=numbered(steps),
                                count=1, always_ask=True, min_risk="medium",
                                reasons=["Mitane ke baad dobara banana parega"], data={"id": row["id"], "name": row["name"]})
            case "run_workflow":  # only reached when the workflow does not exist yet: learn it
                name = workflow_key(str(e.get("workflow") or "")) or "work"
                question = (f"Aap ka '{name}' workflow abhi save nahi. Kaun se applications open karoon? (maslan: Chrome, "
                            f"VS Code, WhatsApp — main ye yaad rakh lunga, agli dafa \"{name} start karo\" par khud khol "
                            "dunga)")
                self.short_term.ask("workflow_steps", question, {"name": name, "run": True}, ttl_s=300)
                return Reply(question)
            case "repeat_last":
                if e.get("what") == "response":  # "kya kaha?" - say the last reply again
                    return Reply(self.short_term.last_response or "Abhi tak maine kuch nahi kaha.")
                return Reply("Dobara karne ke liye abhi koi pichla kaam yaad nahi (short-term memory 30 minute baad saaf "
                             "ho jati hai).")
        return Reply("Ye memory ka kaam samajh nahi aaya.")

    def find_same(self, fact: F.Fact) -> dict[str, Any] | None:
        key = F.norm(fact.text)
        for m in self.db.list_memories():
            if F.norm(m["text"]) == key or (fact.slot and m["slot"] == fact.slot and
                                             F.norm(m["value"] or "") == F.norm(fact.value or "")):
                return m
        return None

    def _prepare_remember(self, e: dict[str, Any]) -> Prepared | Reply:
        text = F.clean(e.get("fact") or "")
        explicit = e.get("explicit", True) is not False
        if not text or text.lower() in PRONOUN_FACTS:
            # "ye yaad rakho": what the user said just before (not an earlier "yaad rakho" itself)
            said = [t for t in self.short_term.user_texts() if not F.REMEMBER_REQUEST.search(t)]
            text = F.clean(said[0] if said else "")
            if not text:
                return Reply("Kya yaad rakhoon? Kahein: \"yaad rakho ke ...\"")
        if F.REMINDER.search(text):
            return Reply("Waqt par yaad dilana (reminder) NOVA abhi nahi karta. Baat yaad rakhni ho to kahein: "
                         "\"yaad rakho ke ...\"")
        if why := F.problem(text):
            return Reply(why, refused=bool(F.SECRET_TEXT.search(text)))
        fact = F.to_fact(text) if explicit else (F.detect_fact(text) or F.Fact(text))
        if same := self.find_same(fact):
            if fact.slot == "name" and not explicit:
                return Reply(f"Ji {fact.value}, mujhe yaad hai.")
            return Reply(f"Ye mujhe pehle se yaad hai: “{same['text']}”.")
        if not explicit:
            if F.norm(fact.text) in self.short_term.declined:
                return Reply(f"Theek hai, {fact.value}." if fact.slot == "name" else "Achha, samajh gaya.")
            question = (f"Aap se mil kar khushi hui, {fact.value}! Kya main aap ka naam yaad rakhoon? (haan/nahi)"
                        if fact.slot == "name" else f"Achha! Kya main ye baat yaad rakhoon: “{fact.text}”? (haan/nahi)")
            self.short_term.ask("remember", question, {"fact": fact.text})
            return Reply(question)
        old = self.db.memory_for_slot(fact.slot) if fact.slot else None
        return Prepared(f"Yaad rakhna: “{fact.text}”", "memory:remember", data={"fact": fact, "old": old})

    def _prepare_forget(self, e: dict[str, Any]) -> Prepared | Reply:
        if e.get("scope") == "conversation":
            return Prepared("Is conversation ki pichli baatein chhorna", "memory:context", data={"op": "context"})
        if e.get("scope") == "patterns" or HABIT_WORDS.search(str(e.get("query") or "")):
            n = len(self.db.list_usage())
            if not n:
                return Reply("Abhi koi aadat record nahi.")
            return Prepared(f"Aadatein ({n} records) hamesha ke liye mitana", "memory:patterns", count=n,
                            always_ask=True, min_risk="medium",
                            reasons=["NOVA phir se shuru se seekhega; workflows aur yaadein nahi mitengi"],
                            data={"op": "patterns"})
        memories = self.db.list_memories()
        if e.get("all"):
            if not memories:
                return Reply("Mujhe pehle se aap ke baare mein kuch yaad nahi.")
            return Prepared(f"Saari {len(memories)} yaadein hamesha ke liye mitana", "memory:forget",
                            preview="\n".join(f"- {m['text']}" for m in memories[:20]), count=len(memories),
                            always_ask=True, min_risk="high", reasons=["Mitane ke baad wapas nahi aati"],
                            data={"ids": [m["id"] for m in memories]})
        query = F.clean(e.get("query") or "")
        if not query or query.lower() in PRONOUN_FACTS:
            last = self.db.get_memory(self.short_term.last_memory_id) if self.short_term.last_memory_id else None
            if last is None:
                return Reply("Kaun si baat bhool jaoon? (maslan \"mera naam bhool jao\")")
            found = [last]
        else:
            slot = F.slot_of(query)
            slot_row = self.db.memory_for_slot(slot) if slot else None
            found = [slot_row] if slot_row else F.rank(query, memories)
            if not found:
                return Reply(f"“{query}” ke baare mein mujhe kuch yaad hi nahi tha.")
        n = len(found)
        return Prepared(f"{n} yaad hamesha ke liye mitana" if n == 1 else f"{n} yaadein hamesha ke liye mitana",
                        "memory:forget", preview="\n".join(f"- {m['text']}" for m in found), count=n, always_ask=True,
                        min_risk="medium", reasons=["Mitane ke baad ye baat NOVA ko yaad nahi rahegi"],
                        data={"ids": [m["id"] for m in found]})

    def _prepare_clear(self, period: str) -> Prepared | Reply:
        start, end = period_range(period, self.now())
        n = self.db.count_history(_iso(start), _iso(end))
        label = LABELS.get(period, "")
        if n == 0:
            return Reply(f"{label.capitalize() + ' ki ' if label else ''}history pehle se khaali hai.")
        what = f"{label.capitalize()} ki history" if label else "Saari history"
        oldest, newest = self.db.history_span(_iso(start), _iso(end))
        span = (f"{n} baatein: {F.short_date(oldest)} {oldest[11:16]} se {F.short_date(newest)} {newest[11:16]} tak, "
                "un ka activity log aur ijazat ke records") if oldest and newest else f"{n} baatein"
        return Prepared(f"{what} mitana ({n} baatein)", "history:clear", preview=span, count=n, always_ask=True,
                        min_risk="high",
                        reasons=["Mitane ke baad wapas nahi aati", "In baaton ka activity log bhi mit jayega"],
                        data={"start": _iso(start), "end": _iso(end), "all": not label})

    async def _prepare_save_workflow(self, e: dict[str, Any]) -> Prepared | Reply:
        name = workflow_key(str(e.get("workflow") or ""))
        if not name:
            return Reply("Workflow ka naam batayein (maslan \"study workflow banao: YouTube aur Notion\").")
        steps_text = F.clean(e.get("steps") or "")
        action = str(e.get("edit_action") or "replace")
        found = self.workflow(name)
        current = found[1] if found else []
        if not steps_text:
            question = (f"'{name}' workflow mein kya kya kholoon? Apps, websites, projects ya folders batayein (maslan: "
                        "Chrome, VS Code, github.com, nova project).")
            self.short_term.ask("workflow_steps", question, {"name": name, "run": False}, ttl_s=300)
            return Reply(question)
        problems: list[str] = []
        if action == "remove":
            if found is None:
                return Reply(f"'{name}' naam ka workflow nahi mila.")
            items = [i.lower() for i in split_items(steps_text)]
            gone = [s for s in current if any(i in s.label.lower() or i in s.value.lower() for i in items)]
            if not gone:
                return Reply(f"'{name}' workflow mein ye nahi: {', '.join(items)}. Is mein hain: "
                             f"{', '.join(s.label for s in current)}.")
            steps = [s for s in current if s not in gone]
        else:
            if self.ensure_profile is not None:
                await self.ensure_profile()
            resolved, problems = await asyncio.to_thread(self.resolver.resolve_all, steps_text)
            if not resolved:
                return Reply("Workflow mein kuch nahi daal saka: " + "; ".join(problems) + ".")
            steps = merge(current, resolved, action)
        if not steps:
            return Reply(f"Is tarah workflow khaali ho jayega. Poora hatana ho to kahein: \"{name} workflow delete karo\".")
        if len(steps) > MAX_STEPS:
            return Reply(f"Ek workflow mein {MAX_STEPS} cheezon tak ho sakti hain.")
        return Prepared(f"'{name}' workflow save karna ({len(steps)} cheezein)", f"workflow:{name}",
                        preview=numbered(steps),
                        data={"name": name, "steps": steps, "problems": problems, "then_run": bool(e.get("then_run"))})

    # ------------------------------------------------------------------ run

    async def run(self, intent: Intent, prepared: Prepared, approved: bool, progress: Progress) -> ControlOutcome:
        d = prepared.data
        match intent.name:
            case "remember_fact":
                return await self._run_remember(d)
            case "recall_memory":
                return self._recall(d["query"])
            case "forget_memory":
                if d.get("op") == "context":
                    self.short_term.clear()
                    return ControlOutcome("Theek hai, pichli baatein chhor di — ab naye sire se baat karte hain.",
                                          "clear_context", True, "not_applicable")
                if not approved:
                    raise PermissionError("forgetting memories requires the user's permission")
                if d.get("op") == "patterns":
                    removed = self.db.delete_usage()
                    left = len(self.db.list_usage())
                    await self.changed("patterns")
                    return ControlOutcome(f"Aadatein bhool gaya ({removed} records)." +
                                          (" (Verify: ab koi record nahi.)" if not left else ""), "forget_patterns",
                                          True, "passed" if not left else "failed")
                return await self._run_forget(d["ids"])
            case "search_history":
                return self._search(d["query"], d["period"])
            case "clear_history":
                if not approved:
                    raise PermissionError("deleting history requires the user's permission")
                return await self._run_clear(d)
            case "save_workflow":
                return await self._run_save_workflow(d)
            case "list_workflows":
                return self._list_workflows()
            case "delete_workflow":
                if not approved:
                    raise PermissionError("deleting a workflow requires the user's permission")
                ok = self.db.delete_workflow(d["id"])
                gone = self.db.get_workflow(d["name"]) is None
                await self.changed("workflows")
                return ControlOutcome(f"'{d['name']}' workflow mita diya." + (" (Verify: list mein nahi raha.)" if gone else ""),
                                      "delete_workflow", ok, "passed" if ok and gone else "failed")
        return ControlOutcome("Ye memory ka kaam samajh nahi aaya.", intent.name, False, "not_applicable")

    async def _run_remember(self, d: dict[str, Any]) -> ControlOutcome:
        fact: F.Fact = d["fact"]
        row = self.db.add_memory(fact.text, "user_command", fact.slot, fact.value)
        saved = self.db.get_memory(row.get("id", 0))
        ok = saved is not None and saved["text"] == fact.text
        if ok:
            self.short_term.last_memory_id = saved["id"]
        await self.changed("facts")
        response = f"Yaad kar liya: “{fact.text}”."
        old = d.get("old")
        if old and F.norm(old["text"]) != F.norm(fact.text):
            response += f" Pehle wali baat (“{old['text']}”) is ki jagah hata di."
        if fact.slot == "name":
            response += f" Ab main aap ko {fact.value} kahunga."
        response += " (Verify: memory mein save hai.)" if ok else " Lekin save verify nahi ho saka."
        return ControlOutcome(response, "remember_fact", ok, "passed" if ok else "failed")

    def _recall(self, query: str) -> ControlOutcome:
        memories = self.db.list_memories()
        if not memories:
            return ControlOutcome("Abhi mujhe aap ke baare mein kuch yaad nahi. Kahein \"yaad rakho ke ...\" — main sirf aap "
                                  "ke kehne par yaad rakhta hoon.", "recall_memory", True, "not_applicable")
        if not query or ALL_WORDS.match(query):
            lines = [f"- {m['text']} ({F.short_date(m['updated_at'])})" for m in memories[:15]]
            more = f"\n(aur {len(memories) - 15} — Memory tab mein dekhein)" if len(memories) > 15 else ""
            self.db.touch_memories([m["id"] for m in memories[:15]])
            return ControlOutcome(f"Mujhe ye baatein yaad hain ({len(memories)}):\n" + "\n".join(lines) + more,
                                  "recall_memory", True, "not_applicable")
        slot = F.slot_of(query)
        slot_row = self.db.memory_for_slot(slot) if slot else None
        if slot_row:
            self.db.touch_memories([slot_row["id"]])
            response = (f"Aap ka naam {slot_row['value']} hai." if slot == "name"
                        else f"Aap ne bataya tha: “{slot_row['text']}”.")
            return ControlOutcome(response, "recall_memory", True, "not_applicable")
        found = F.rank(query, memories)
        if not found:
            return ControlOutcome(f"“{query}” ke baare mein mujhe kuch yaad nahi. Aap \"yaad rakho ke ...\" keh kar bata "
                                  "sakte hain.", "recall_memory", True, "not_applicable")
        self.db.touch_memories([m["id"] for m in found])
        if len(found) == 1:
            return ControlOutcome(f"Aap ne bataya tha ({F.short_date(found[0]['updated_at'])}): “{found[0]['text']}”.",
                                  "recall_memory", True, "not_applicable")
        return ControlOutcome("Mujhe ye yaad hai:\n" + "\n".join(f"- {m['text']}" for m in found), "recall_memory", True,
                              "not_applicable")

    async def _run_forget(self, ids: list[int]) -> ControlOutcome:
        rows = [m for m in (self.db.get_memory(i) for i in ids) if m]
        removed = self.db.delete_memories(ids)
        left = [i for i in ids if self.db.get_memory(i)]
        if self.short_term.last_memory_id in ids:
            self.short_term.last_memory_id = None
        await self.changed("facts")
        if len(rows) == 1:
            response = f"Theek hai, bhool gaya: “{rows[0]['text']}”."
        else:
            response = f"{removed} yaadein mita di."
        return ControlOutcome(response + (" (Verify: memory mein nahi rahi.)" if not left else ""), "forget_memory",
                              removed > 0, "passed" if not left else "failed")

    def _search(self, query: str, period: str) -> ControlOutcome:
        records = self.history(query, period, limit=11)
        terms = " ".join(search_terms(query))
        label = LABELS.get(period, "")
        where = f"{label.capitalize()} ki history" if label else "History"
        about = f" (“{terms}”)" if terms else ""
        if not records:
            return ControlOutcome(f"{where}{about} mein kuch nahi mila.", "search_history", True, "not_applicable")
        shown = records[:10]
        more = "\n(aur bhi hain — Memory tab mein History dekhein)" if len(records) > 10 else ""
        return ControlOutcome(f"{where}{about} — {len(shown)} baatein:\n" + "\n".join(line(r) for r in shown) + more,
                              "search_history", True, "not_applicable")

    async def _run_clear(self, d: dict[str, Any]) -> ControlOutcome:
        removed = self.db.delete_history(d["start"], d["end"])
        left = self.db.count_history(d["start"], d["end"])
        self.short_term.clear()
        await self.changed("history", cleared=True, all=d["all"])
        return ControlOutcome(f"History mita di ({removed} baatein)." + (" (Verify: ab koi baqi nahi.)" if not left else ""),
                              "clear_history", True, "passed" if not left else "failed")

    async def _run_save_workflow(self, d: dict[str, Any]) -> ControlOutcome:
        steps: list[WorkflowStep] = d["steps"]
        wanted = [s.to_dict() for s in steps]
        row = self.db.save_workflow(d["name"], wanted)
        ok = row.get("steps") == wanted
        if ok and d["then_run"]:  # the first "work start karo" also opens everything right away
            self.db.mark_workflow_run(row["id"])
        await self.changed("workflows")
        name = d["name"]
        response = f"'{name}' workflow save ho gaya ({len(steps)} cheezein):\n{numbered(steps)}"
        if d["problems"]:
            response += "\nYe nahi daal saka: " + "; ".join(d["problems"]) + "."
        response += (f"\nAgli dafa bas \"{name} start karo\" kahein. Ab khol raha hoon:" if d["then_run"]
                     else f"\nChalane ke liye kahein: \"{name} start karo\".")
        if not ok:
            response += " (Save verify nahi ho saka.)"
        return ControlOutcome(response, "save_workflow", ok, "passed" if ok else "failed")

    def _list_workflows(self) -> ControlOutcome:
        rows = self.db.list_workflows()
        if not rows:
            return ControlOutcome("Abhi koi workflow save nahi. Kahein \"work start karo\" — main pooch kar bana dunga.",
                                  "list_workflows", True, "not_applicable")
        lines = []
        for row in rows:
            labels = ", ".join(WorkflowStep.from_dict(s).label for s in row["steps"])
            runs = f" ({row['runs']} dafa chala)" if row["runs"] else ""
            lines.append(f"- {row['name']}: {labels}{runs}")
        return ControlOutcome(f"Aap ke {len(rows)} workflows:\n" + "\n".join(lines), "list_workflows", True, "not_applicable")
