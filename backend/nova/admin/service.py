"""Admin service (Phase 11): feature lifecycle, the approval system, bug tracking, self-test runs, daily summary.

Feature lifecycle (spec): Implemented -> Automated test -> Verified -> Admin test -> Admin approved.
Problem flow: Problem -> Bug log -> Fix -> Retest -> Admin approval.
Only the admin's own click in the Admin panel (or their word in chat) approves anything - NOVA never does.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Callable

from ..db import Database
from ..events import EventBus, EventType, NovaEvent
from . import docs
from .docs import DocFile
from .selftest import SelfTest

NAME = "Admin"
BUG_STATUSES = ("open", "fixed", "closed", "reopened")
ACTIVE_BUGS = ("open", "reopened", "fixed")
STATUS_WORDS = {"open": "khula", "fixed": "fix ho gaya, retest baqi", "closed": "band", "reopened": "dobara khula"}


class AdminError(Exception):
    """A request the admin panel must refuse (shown to the admin)."""


class AdminService:
    def __init__(self, db: Database, bus: EventBus, logs: DocFile, readme: DocFile, selftest: SelfTest,
                 now: Callable[[], datetime] = datetime.now) -> None:
        self.db = db
        self.bus = bus
        self.logs = logs
        self.readme = readme
        self.selftest = selftest
        self.now = now

    def _today(self) -> str:
        return self.now().strftime("%Y-%m-%d")

    async def _event(self, kind: EventType, message: str, **data: Any) -> None:
        await self.bus.publish(NovaEvent(type=kind, agent=NAME, message=message, data=data))

    def _log(self, action: str, result: str, *, admin_status: str = "not_required", test_status: str = "not_run",
             execution: str = "success", task_id: str = "admin") -> None:
        self.db.add_activity(task_id=task_id, task_name=action, agent=NAME, action=action,
                             permission_status="user_initiated", execution_status=execution, test_status=test_status,
                             admin_status=admin_status, final_result=result)

    # ------------------------------------------------------------------ features

    def features(self) -> list[dict[str, Any]]:
        tasks = docs.parse_tasks(self.logs.read())
        steps = docs.readme_steps(self.readme.read())
        last_full = self.db.last_test_run("full")
        out = []
        for t in tasks:
            bugs = self.db.list_bugs(phase=t.phase)
            run = self.db.last_test_run(t.phase)
            results = (run or {}).get("results") or [r for r in (last_full or {}).get("results", [])
                                                      if r["phase"].lower() == t.phase.lower()]
            checks_ok = bool(results) and not any(r["status"] == "fail" for r in results)
            active = [b for b in bugs if b["status"] in ACTIVE_BUGS]
            out.append({
                "phase": t.phase, "title": t.title, "status": t.status, "admin_test": t.admin_test,
                "admin_approval": t.admin_approval, "approved": t.approved, "automated_test": t.has_test,
                "self_test": {"ran": bool(results), "ok": checks_ok,
                              "failed": sum(r["status"] == "fail" for r in results), "results": results},
                "steps": steps.get(t.phase, []), "bugs_active": len(active), "bugs_total": len(bugs),
                "stage": self._stage(t, bool(active), checks_ok if results else None),
            })
        return out

    @staticmethod
    def _stage(t: docs.LogTask, has_bugs: bool, checks_ok: bool | None) -> str:
        """Where the feature is in its lifecycle (spec section 28)."""
        if has_bugs:
            return "problem"
        if t.approved:
            return "approved"
        if t.admin_test.lower().startswith("complete"):
            return "admin_tested"
        if checks_ok is False:
            return "implemented"
        if t.has_test:
            return "verified" if checks_ok else "automated_test"
        return "implemented"

    def _task(self, phase: str) -> docs.LogTask:
        task = docs.find(self.logs.read(), phase) if self.logs.available else None
        if task is None:
            raise AdminError(f"LOGS.md mein Phase {phase} nahi mili")
        return task

    async def approve(self, phase: str, note: str = "") -> dict[str, Any]:
        task = self._task(phase)
        if task.approved:
            raise AdminError(f"Phase {phase} pehle se approved hai")
        active = [b for b in self.db.list_bugs(phase=task.phase) if b["status"] in ACTIVE_BUGS]
        if active:
            raise AdminError(f"Phase {phase} ke {len(active)} bug abhi band nahi (" +
                             ", ".join(f"#{b['id']} {STATUS_WORDS[b['status']]}" for b in active) +
                             ") — pehle retest kar ke band karein")
        line = f"Approved ({self._today()}, admin ne NOVA Admin panel se approve kiya)"
        self.logs.update(lambda text: docs.set_admin(text, task.phase, admin_test="Complete", admin_approval=line))
        self.db.add_approval(task.phase, "approved", note, "admin_panel")
        self._log("admin_approve", f"Phase {task.phase} approved", admin_status="approved")
        await self._event(EventType.ADMIN_DECISION, f"Admin ne Phase {task.phase} approve kiya",
                          phase=task.phase, decision="approved")
        return {"phase": task.phase, "admin_approval": line}

    async def report_problem(self, phase: str | None, title: str, details: str = "") -> dict[str, Any]:
        task = self._task(phase) if phase else None
        bug = self.db.add_bug(title, "admin", phase=task.phase if task else None, details=details)
        if task is not None:
            date = self._today()
            self.logs.update(lambda text: docs.set_admin(
                docs.set_bug(text, task.phase, bug["id"], f"({STATUS_WORDS['open']}, {date}) {bug['title']}"),
                task.phase, admin_test=f"Problem report hua ({date}, bug #{bug['id']})",
                admin_approval="Pending" if not task.approved else f"Pending (pehle approved tha; problem bug "
                                                                     f"#{bug['id']})"))
            self.db.add_approval(task.phase, "problem", title, "admin_panel")
        self._log("admin_report_problem", f"bug #{bug['id']}" + (f" (Phase {task.phase})" if task else ""),
                  admin_status="problem")
        await self._event(EventType.BUG_LOGGED, f"Bug #{bug['id']} log hua: {bug['title']}", bug=bug)
        return bug

    async def retest(self, phase: str) -> dict[str, Any]:
        task = self._task(phase)
        run = await self.run_tests(task.phase)
        self.db.add_approval(task.phase, "retest", f"{run['failed']} masle", "admin_panel")
        return run

    async def set_bug_status(self, bug_id: int, status: str, note: str = "", by: str = "admin") -> dict[str, Any]:
        if status not in BUG_STATUSES:
            raise AdminError("Status sahi nahi")
        bug = self.db.set_bug_status(bug_id, status, by, note)
        if bug is None:
            raise AdminError("Bug nahi mila")
        if bug["phase"] and self.logs.available and docs.find(self.logs.read(), bug["phase"]):
            self.logs.update(lambda text: docs.set_bug(
                text, bug["phase"], bug_id, f"({STATUS_WORDS[status]}, {self._today()}) {bug['title']}"))
        self._log("bug_status", f"bug #{bug_id}: {status}", admin_status="problem" if status in ACTIVE_BUGS else
                  "not_required")
        await self._event(EventType.BUG_LOGGED, f"Bug #{bug_id}: {STATUS_WORDS[status]}", bug=bug)
        return bug

    # ------------------------------------------------------------------ automatic bugs

    async def report_crash(self, exc: BaseException, task_id: str) -> dict[str, Any]:
        """A command crashed: one bug per distinct place in the code (repeats count up, closed ones reopen)."""
        frames = traceback.extract_tb(exc.__traceback__)
        where = next((f for f in reversed(frames) if "nova" in f.filename.replace("\\", "/")), frames[-1] if frames
                     else None)
        place = f"{where.filename.replace(chr(92), '/').split('/nova/')[-1]}:{where.lineno}" if where else "?"
        bug = self.db.add_bug(f"Command handle karte waqt crash: {type(exc).__name__}", "automatic",
                              details=f"{type(exc).__name__} at {place}: {str(exc)[:300]}",
                              signature=f"crash:{type(exc).__name__}:{place}", task_id=task_id)
        await self._event(EventType.BUG_LOGGED, f"Bug #{bug['id']} khud log hua (crash, {bug['occurrences']} dafa)",
                          bug=bug)
        return bug

    # ------------------------------------------------------------------ self-test

    async def run_tests(self, scope: str, quiet: bool = False) -> dict[str, Any]:
        results = await self.selftest.run(scope)
        run = self.db.add_test_run(scope, results)
        problems = [r for r in results if r["status"] in ("warn", "fail")]
        for r in results:
            if r["status"] == "fail":
                self.db.add_bug(f"Self-test nakaam: {r['name']}", "self_test", phase=r["phase"], details=r["detail"],
                                signature=f"selftest:{r['id']}")
        self._log("self_test", f"{scope}: {run['passed']} theek, {run['warned']} kami, {run['failed']} nakaam",
                  test_status="failed" if run["failed"] else "passed")
        if not quiet or problems:
            names = ", ".join(r["name"] for r in problems[:3])
            message = (f"Self-test ({scope}): sab theek ({run['passed']})" if not problems else
                       f"Self-test ({scope}): {len(problems)} masle — {names}. Admin tab dekhein.")
            await self._event(EventType.SELF_TEST, message, scope=scope, passed=run["passed"], warned=run["warned"],
                              failed=run["failed"])
        return run

    # ------------------------------------------------------------------ daily summary in LOGS.md (counts only)

    def summary_line(self, day: str) -> str:
        c = self.db.day_counts(day)
        parts = [f"{c['commands']} commands ({c['voice']} awaaz se)", f"{c['done']} kaam hue",
                 f"{c['failed']} nakaam/verify nahi", f"{c['asked']} dafa ijazat poochi ({c['denied']} nahi)"]
        if c["bugs"]:
            parts.append(f"{c['bugs']} naye bug")
        if c["tests"]:
            parts.append(f"{c['tests']} self-test ({c['test_failures']} nakaam checks)")
        return ", ".join(parts) + "."

    def write_daily_summaries(self) -> list[str]:
        """Finished days that are not in LOGS.md yet get one line each. Today is added tomorrow."""
        if not self.logs.available:
            return []
        today = self._today()
        written = docs.summary_dates(self.logs.read())
        days = [d for d in self.db.activity_days() if d < today and d not in written]
        for day in days:
            line = self.summary_line(day)
            self.logs.update(lambda text, day=day, line=line: docs.upsert_summary(text, day, line))
        return days
