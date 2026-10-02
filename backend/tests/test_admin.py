"""Phase 11: self-test, bug tracking, the approval system (Admin panel + LOGS.md), error handling, daily summary."""

import asyncio
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from conftest import FakeDesktop, build_client
from nova.admin import docs

LOGS = """# NOVA Development Logs

## 2026-10-02

### Task: Phase 7 — Permission Engine

Status: Complete

Kaam:
- Ijazat ka nizam.

Test:
- 10/10 pass.

Admin Test:
Complete

Admin Approval:
Approved (2026-10-02, admin ne chat mein approve kiya)

---

### Task: Phase 8C — System settings + Communication Agent + Design Agent

Status: Complete — admin test ka intezar

Kaam:
- Settings, messages, design.

Test:
- 474/474 pass.

Admin Test:
Pending

Admin Approval:
Pending
"""

README = """# NOVA

## Admin manual test (Phase 8C)

1. `npm start`.
2. **Settings:** `volume 30 kar do`
   — fauran.
3. Approve karein.

## Admin manual test (Phase 7, approved)

1. Kuch bhi.
"""


def cmd(client, text):
    return client.post("/api/command", json={"text": text}).json()


def events(client, kind):
    return [e for e in client.app.state.bus.history() if e.type.value == kind]


@pytest.fixture
def env(tmp_path):
    logs, readme = tmp_path / "LOGS.md", tmp_path / "README.md"
    logs.write_text(LOGS, encoding="utf-8")
    readme.write_text(README, encoding="utf-8")
    desktop = FakeDesktop()
    with build_client(tmp_path, desktop=desktop, logs_path=logs, readme_path=readme, permission_timeout_s=10) as c:
        yield SimpleNamespace(client=c, logs=logs, desktop=desktop)


# ------------------------------------------------------------------ LOGS.md / README.md


def test_logs_md_is_read_and_only_the_admin_lines_change():
    tasks = docs.parse_tasks(LOGS)
    assert [(t.phase, t.approved, t.has_test) for t in tasks] == [("7", True, True), ("8C", False, True)]
    text = docs.set_admin(LOGS, "8C", admin_test="Complete", admin_approval="Approved (x)")
    text = docs.set_bug(text, "8C", 3, "(khula) volume nahi badla")
    text = docs.set_bug(text, "8C", 3, "(band) volume nahi badla")
    task = docs.find(text, "8C")
    assert task.approved and task.bugs == ["#3 (band) volume nahi badla"]
    assert docs.find(text, "7").admin_approval.startswith("Approved (2026-10-02, admin ne chat")
    assert text.replace("Admin bugs:\n- #3 (band) volume nahi badla\n\n", "").replace(
        "Complete\n\nAdmin Approval:\nApproved (x)", "Pending\n\nAdmin Approval:\nPending") == LOGS
    with pytest.raises(KeyError):
        docs.set_admin(LOGS, "99", admin_test="x")
    steps = docs.readme_steps(README)
    assert steps["8C"] == ["`npm start`.", "**Settings:** `volume 30 kar do` — fauran.", "Approve karein."]
    assert steps["7"] == ["Kuch bhi."]


def test_daily_summary_lines_are_added_once():
    text = docs.upsert_summary(LOGS, "2026-10-01", "3 commands.")
    text = docs.upsert_summary(text, "2026-10-01", "changed")
    text = docs.upsert_summary(text, "2026-10-02", "5 commands.")
    assert text.endswith("## System activity (rozana khulasa)\n\n- 2026-10-01: 3 commands.\n- 2026-10-02: 5 commands.\n")
    assert docs.summary_dates(text) == {"2026-10-01", "2026-10-02"}
    assert len(docs.parse_tasks(text)) == 2  # the section is not part of the last task


# ------------------------------------------------------------------ self-test


def test_self_test_checks_the_parts_and_records_the_run(env):
    c = env.client
    run = c.post("/api/admin/selftest", json={"scope": "startup"}).json()
    by_id = {r["id"]: r for r in run["results"]}
    assert by_id["database"]["status"] == "pass" and by_id["rules_brain"]["status"] == "pass"
    assert by_id["permissions"]["status"] == "pass" and by_id["redaction"]["status"] == "pass"
    assert by_id["windows_settings"]["detail"] == "volume parha: 40%" and by_id["logs_md"]["status"] == "pass"
    assert by_id["behavior"]["status"] == "pass" and by_id["design"]["status"] == "pass"
    assert "local_ai_answer" not in by_id  # slow checks only in the full test
    assert run["failed"] == 0 and c.get("/api/admin/selftest/last").json()["id"] == run["id"]
    row = c.get("/api/activity?kind=tests").json()[0]
    assert row["task_name"] == "self_test" and row["test_status"] == "passed"
    assert events(c, "SELF_TEST")[-1].message.startswith("Self-test (startup)")
    phase = c.post("/api/admin/features/8C/test").json()
    assert {r["phase"] for r in phase["results"]} == {"8C"} and phase["scope"] == "8C"


def test_a_failing_check_becomes_a_bug_once(env):
    c = env.client

    def broken():
        raise OSError("audio device gone")

    c.app.state.windows_settings.volume = broken
    for _ in range(2):
        run = c.post("/api/admin/features/8C/test").json()
    assert run["failed"] == 1
    bugs = c.get("/api/admin/bugs?status=active").json()
    assert len(bugs) == 1 and bugs[0]["source"] == "self_test" and bugs[0]["occurrences"] == 2
    assert bugs[0]["phase"] == "8C" and "audio device gone" in bugs[0]["details"]


# ------------------------------------------------------------------ approval system


def test_problem_fix_retest_approve(env):
    c = env.client
    features = {f["phase"]: f for f in c.get("/api/admin/features").json()}
    assert features["7"]["stage"] == "approved" and features["8C"]["stage"] in ("automated_test", "verified")
    assert features["8C"]["steps"][1].startswith("**Settings:**")
    # Problem -> bug log
    bug = c.post("/api/admin/features/8C/problem", json={"title": "Volume 30 nahi hua", "details": "40 hi raha"}).json()
    assert bug["status"] == "open" and bug["source"] == "admin"
    task = docs.find(env.logs.read_text(encoding="utf-8"), "8C")
    assert task.bugs == [f"#{bug['id']} (khula, {datetime.now():%Y-%m-%d}) Volume 30 nahi hua"]
    assert task.admin_test.startswith("Problem report hua") and task.admin_approval == "Pending"
    assert {f["phase"]: f for f in c.get("/api/admin/features").json()}["8C"]["stage"] == "problem"
    # Approval is refused while the bug is not closed
    r = c.post("/api/admin/features/8C/approve", json={"confirm": True})
    assert r.status_code == 409 and "band nahi" in r.json()["detail"]
    # Fix -> retest -> close
    c.put(f"/api/admin/bugs/{bug['id']}", json={"status": "fixed", "note": "volume ka bug theek"})
    assert c.post("/api/admin/features/8C/retest").json()["scope"] == "8C"
    assert c.post("/api/admin/features/8C/approve", json={"confirm": True}).status_code == 409  # fixed is not closed
    closed = c.put(f"/api/admin/bugs/{bug['id']}", json={"status": "closed"}).json()
    assert [h["status"] for h in closed["history"]] == ["open", "fixed", "closed"]
    # Admin approval: only with the admin's confirmation
    assert c.post("/api/admin/features/8C/approve", json={"confirm": False}).status_code == 422
    ok = c.post("/api/admin/features/8C/approve", json={"confirm": True, "note": "sab theek"}).json()
    assert "admin ne NOVA Admin panel se approve kiya" in ok["admin_approval"]
    task = docs.find(env.logs.read_text(encoding="utf-8"), "8C")
    assert task.approved and task.admin_test == "Complete" and "(band," in task.bugs[0]
    assert c.post("/api/admin/features/8C/approve", json={"confirm": True}).status_code == 409  # already approved
    assert c.post("/api/admin/features/99/approve", json={"confirm": True}).status_code == 409
    decisions = [a["decision"] for a in c.app.state.db.list_approvals("8C")]
    assert decisions == ["approved", "retest", "problem"]
    admin_rows = c.get("/api/activity?kind=admin").json()
    assert {"admin_approve", "admin_report_problem"} <= {r["task_name"] for r in admin_rows}
    assert events(c, "ADMIN_DECISION")[-1].data == {"phase": "8C", "decision": "approved"}


def test_a_problem_on_an_approved_phase_needs_approval_again(env):
    c = env.client
    c.post("/api/admin/features/7/problem", json={"title": "Dialog nahi khula"})
    assert docs.find(env.logs.read_text(encoding="utf-8"), "7").approved is False


def test_without_logs_md_nothing_is_written(tmp_path):
    with build_client(tmp_path) as c:
        assert c.get("/api/admin/features").json() == []
        assert c.post("/api/admin/features/8C/approve", json={"confirm": True}).status_code == 409
        bug = c.post("/api/admin/bugs", json={"title": "Kuch ajeeb hua", "details": "token: abcdef123456 laga"}).json()
        assert bug["phase"] is None and "abcdef123456" not in bug["details"]  # secrets are hidden
        assert c.put(f"/api/admin/bugs/{bug['id']}", json={"status": "gone"}).status_code == 422
        assert c.put("/api/admin/bugs/999", json={"status": "closed"}).status_code == 404
        assert c.get("/api/admin/bugs?status=nope").status_code == 422


# ------------------------------------------------------------------ automatic bugs and error handling


def test_a_crash_is_logged_as_one_bug(env):
    c = env.client

    async def boom(*args, **kwargs):
        raise ValueError("unexpected brain state")

    c.app.state.providers.understand = boom
    assert cmd(c, "kuch bhi")["status"] == "failed"
    bug = c.get("/api/admin/bugs").json()[0]
    assert bug["source"] == "automatic" and bug["title"] == "Command handle karte waqt crash: ValueError"
    assert bug["signature"].startswith("crash:ValueError:") and bug["task_id"]
    c.put(f"/api/admin/bugs/{bug['id']}", json={"status": "closed"})
    cmd(c, "kuch aur")
    again = c.get("/api/admin/bugs").json()
    assert len(again) == 1 and again[0]["occurrences"] == 2 and again[0]["status"] == "reopened"
    assert events(c, "BUG_LOGGED")


class FlakyDesktop(FakeDesktop):
    """The first launches are not verified (no window), later ones work."""

    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def launch(self, app, **kw):
        if self.failures > 0:
            self.failures -= 1
            self.launch_outcome = "launched_unverified"
        else:
            self.launch_outcome = "opened"
        return super().launch(app, **kw)


def test_a_safe_action_is_retried_once_then_the_user_is_asked(tmp_path):
    desktop = FlakyDesktop(failures=1)
    with build_client(tmp_path, desktop=desktop) as c:
        body = cmd(c, "Chrome kholo")
        assert "dobara karne par ho gaya" in body["response"]
        assert [x for x in desktop.calls if x[0] == "launch"] == [("launch", "Google Chrome")] * 2
        assert events(c, "RETRY")[-1].message.startswith("Verify nahi hua — ek dafa dobara koshish")
    desktop = FlakyDesktop(failures=5)
    with build_client(tmp_path / "b", desktop=desktop) as c:
        body = cmd(c, "Chrome kholo")
        assert "Kya main ek dafa aur koshish karoon?" in body["response"]
        assert len([x for x in desktop.calls if x[0] == "launch"]) == 2  # never a third try on its own
        assert events(c, "NOVA_RESPONSE")[-1].data["quick_replies"] == ["Haan", "Nahi"]
        desktop.failures = 0
        assert "Chrome khul gaya" in cmd(c, "haan")["response"] or "khul gaya" in c.get("/api/activity?limit=1").json()[0]["final_result"]
        assert len([x for x in desktop.calls if x[0] == "launch"]) == 3
        desktop.failures = 2
        assert "koshish karoon" in cmd(c, "Chrome kholo")["response"]  # fails twice again
        assert "dobara koshish nahi ki" in cmd(c, "nahi")["response"]
        assert len([x for x in desktop.calls if x[0] == "launch"]) == 5  # "nahi": nothing more


def test_actions_that_needed_permission_are_never_retried(tmp_path):
    desktop = FakeDesktop()
    desktop.close_works = False  # the window does not close: verification fails
    with build_client(tmp_path, desktop=desktop, permission_timeout_s=10) as c:
        results = []
        t = threading.Thread(target=lambda: results.append(cmd(c, "Notepad band karo")))
        t.start()
        for _ in range(100):
            pending = c.get("/api/permissions/pending").json()
            if pending:
                c.post(f"/api/permissions/{pending[0]['id']}/decision", json={"approved": True})
                break
            time.sleep(0.05)
        t.join()
        assert len([x for x in desktop.calls if x[0] == "close"]) == 1 and not events(c, "RETRY")
        assert "koshish karoon" not in results[0]["response"]


# ------------------------------------------------------------------ daily summary, activity filters


def test_daily_summary_goes_to_logs_md_with_counts_only(env):
    c = env.client
    db = c.app.state.db
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    db._execute("INSERT INTO conversations(task_id, created_at, source, user_text, response, status) VALUES "
                "('t1', ?, 'voice', 'mera secret plan Chrome kholo', 'ok', 'understood')", (f"{yesterday}T10:00:00",))
    db._execute("INSERT INTO activity_log(date, time, task_id, task_name, agent, action, permission_status, "
                "execution_status, test_status, verification_status, admin_status) VALUES (?, '10:00:01', 't1', "
                "'command:open_app', 'System Agent', 'launch_app', 'not_required', 'success', 'not_run', 'passed', "
                "'not_required')", (yesterday,))
    cmd(c, "RAM batao")  # today: not written until tomorrow
    assert c.app.state.admin.write_daily_summaries() == [yesterday]
    text = env.logs.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith(f"- {yesterday}:"))
    assert line == f"- {yesterday}: 1 commands (1 awaaz se), 1 kaam hue, 0 nakaam/verify nahi, 0 dafa ijazat poochi (0 nahi)."
    assert "secret" not in text and "Chrome" not in line
    assert c.app.state.admin.write_daily_summaries() == []  # once per day
    summary = c.get("/api/admin/summary").json()
    assert summary["counts"]["commands"] >= 1 and summary["logs_md"] is True


def test_activity_log_filters(env):
    c = env.client
    c.app.state.windows_settings.volume = lambda: (_ for _ in ()).throw(OSError("x"))
    c.post("/api/admin/features/8C/test")
    cmd(c, "RAM batao")
    assert all(r["test_status"] != "not_run" or r["task_name"] == "self_test" for r in c.get("/api/activity?kind=tests").json())
    rows = c.get("/api/activity?agent=System%20Agent").json()
    assert rows and {r["agent"] for r in rows} == {"System Agent"}
    assert c.get("/api/activity?q=read_system_info").json()
    assert c.get("/api/activity?kind=bogus").status_code == 200  # unknown filter: everything


def test_startup_self_test_is_quiet_unless_something_is_wrong(tmp_path):
    from nova.admin.selftest import Check, SelfTest
    from nova.admin.service import AdminService
    from nova.admin.docs import DocFile
    from nova.db import Database
    from nova.events import EventBus

    db, bus = Database(tmp_path / "x.db"), EventBus()
    ok = AdminService(db, bus, DocFile(None), DocFile(None), SelfTest([Check("a", "1", "A", lambda: ("pass", ""))]))
    asyncio.run(ok.run_tests("startup", quiet=True))
    assert not [e for e in bus.history() if e.type.value == "SELF_TEST"]
    bad = AdminService(db, bus, DocFile(None), DocFile(None),
                       SelfTest([Check("b", "1", "B", lambda: ("warn", "kam jagah")),
                                 Check("c", "1", "C", lambda: 1 / 0)]))
    run = asyncio.run(bad.run_tests("startup", quiet=True))
    assert run["warned"] == 1 and run["failed"] == 1
    assert "ZeroDivisionError" in run["results"][1]["detail"]
    assert [e.message for e in bus.history() if e.type.value == "SELF_TEST"] == [
        "Self-test (startup): 2 masle — B, C. Admin tab dekhein."]
