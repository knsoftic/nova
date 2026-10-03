"""Phase 13: Multi-PC - PC identity, pairing with a one-time code, the encrypted link, remote tasks, discovery.

The two-PC tests run two complete NOVA backends that talk over real TLS 1.3 (pre-shared key) on 127.0.0.1.
"""

import asyncio
import json
import socket
import threading
import time

import pytest

from conftest import FakeDesktop, build_client
from nova.db import Database
from nova.multipc import beacon, link, policy
from nova.multipc.agent import MultiPcAgent
from nova.multipc.netinfo import NetInfo
from nova.multipc.service import MultiPcService

LOOPBACK = {"peer_loopback": True, "peer_port": 0, "beacon_port": None}


def cmd(client, text):
    return client.post("/api/command", json={"text": text}).json()


def events(client, kind):
    return [e for e in client.app.state.bus.history() if e.type.value == kind]


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met")


def enable(client, name):
    client.put("/api/settings", json={"multi_pc": True, "pc_name": name})
    wait_for(lambda: client.get("/api/pcs").json()["running"])
    return client.get("/api/pcs").json()


def run_asking(client, text, approve, timeout=20.0):
    """Send a command; when NOVA asks permission, answer it. Returns (reply, the question)."""
    results, asked = [], []
    t = threading.Thread(target=lambda: results.append(cmd(client, text)))
    t.start()
    deadline = time.monotonic() + timeout
    while t.is_alive() and time.monotonic() < deadline:
        pending = client.get("/api/permissions/pending").json()
        if pending:
            asked.append(pending[0])
            client.post(f"/api/permissions/{pending[0]['id']}/decision", json={"approved": approve})
            break
        time.sleep(0.05)
    t.join(timeout)
    return results[0], (asked[0] if asked else None)


# ------------------------------------------------------------------ the pieces


def test_pairing_codes():
    code = link.new_code()
    assert len(code) == 14 and code.count("-") == 2 and link.normalize_code(code) == code.replace("-", "")
    assert link.normalize_code("k7qf m2xa 9tpw") == "K7QFM2XA9TPW"
    assert link.normalize_code("O1IL-0000-0000") == "0111" + "0" * 8  # look-alike letters forgiven
    assert link.normalize_code("K7QF-M2XA") is None and link.normalize_code("K7QF-M2XA-9TPU") is None  # no U
    key = link.pairing_key("K7QFM2XA9TPW")
    assert len(key) == 32 and key == link.pairing_key("K7QFM2XA9TPW") != link.pairing_key("K7QFM2XA9TPX")
    nonce = "a" * 32
    p = link.proof(key, "server", nonce, nonce, "1" * 16, "2" * 16)
    assert link.proof_ok(p, key, "server", nonce, nonce, "1" * 16, "2" * 16)
    assert not link.proof_ok(p, key, "client", nonce, nonce, "1" * 16, "2" * 16)  # roles cannot be swapped
    assert not link.proof_ok(None, key, "server", nonce, nonce, "1" * 16, "2" * 16)


def test_the_encrypted_link_works_here():
    assert asyncio.run(link.loopback_selftest())


def test_beacon_messages_are_checked():
    good = {"nova": beacon.MARKER, "type": "here", "id": "0123456789abcdef", "name": "Office\x00 PC<script>",
            "port": 8770, "version": "0.13.0", "pairing": True}
    msg = beacon.parse(json.dumps(good).encode())
    assert msg == {"type": "here", "id": "0123456789abcdef", "name": "Office PCscript", "port": 8770,
                   "version": "0.13.0", "pairing": True}
    for bad in ({**good, "id": "nope"}, {**good, "port": 70000}, {**good, "nova": "other"}, {**good, "type": "x"}):
        assert beacon.parse(json.dumps(bad).encode()) is None
    assert beacon.parse(b"x" * 2000) is None and beacon.parse(b"not json") is None
    assert beacon.parse(json.dumps({"nova": beacon.MARKER, "type": "query"}).encode()) == {"type": "query"}
    assert beacon.clean_name("") == "PC"


def test_what_another_pc_may_do_here():
    assert policy.verdict("open_app", "low") is None and policy.verdict("system_info", "low") is None
    assert policy.verdict("close_app", "medium") is None  # asked on the sending PC
    assert policy.verdict("change_setting", "medium") is None and policy.verdict("rename_file", "medium") is None
    for intent, risk in (("delete_file", "medium"), ("send_message", "low"), ("type_text", "medium"),
                         ("run_command", "low"), ("clear_history", "medium"), ("read_screen", "low"),
                         ("open_website", "medium")):
        assert policy.verdict(intent, risk) == policy.REFUSED, intent
    assert policy.verdict("close_app", "high") == policy.REFUSED_HIGH


def test_public_network_keeps_multi_pc_off(tmp_path):
    settings = type("S", (), {"multi_pc": True, "pc_name": "Home PC"})()

    async def main():
        service = MultiPcService(Database(tmp_path / "a.db"), _Bus(), lambda: settings, "0.13.0",
                                 networks=lambda: [NetInfo("192.168.1.5", 24, "Wi-Fi", "Public", "Cafe WiFi")])
        await service.apply()
        assert not service.running and "Public" in service.reason and "Cafe WiFi" in service.reason
        settings.multi_pc = False
        await service.apply()
        assert service.reason == "Multi-PC band hai"
        assert len(service.id) == 16 and service.id == MultiPcService(service.db, _Bus(), lambda: settings, "x").id

    asyncio.run(main())


class _Bus:
    async def publish(self, event):
        pass


def test_which_commands_are_for_another_pc(tmp_path):
    db = Database(tmp_path / "x.db")
    for pc_id, name in (("a" * 16, "Office PC"), ("b" * 16, "Desktop"), ("c" * 16, "Laptop")):
        db.save_peer(pc_id, name, "127.0.0.1", 8770, "x")
    agent = MultiPcAgent(type("Svc", (), {"db": db})())

    def understood(text):
        u = agent.understand(text)
        return None if u is None else (u.intents[0].name, u.intents[0].entities)

    assert understood("Office PC par Chrome kholo") == ("remote_command", {"pc": "Office PC", "pc_id": "a" * 16,
                                                                           "command": "Chrome kholo"})
    assert understood("office par youtube kholo")[1]["pc_id"] == "a" * 16
    assert understood("Laptop ka RAM batao") == ("remote_command", {"pc": "Laptop", "pc_id": "c" * 16,
                                                                    "command": "RAM batao"})
    assert understood("laptop ka haal batao") == ("pc_status", {"pc": "Laptop", "pc_id": "c" * 16})
    assert understood("Office PC online hai") == ("pc_status", {"pc": "Office PC", "pc_id": "a" * 16})
    assert understood("mere PCs dikhao") == ("pc_status", {"pc": ""})
    # "Desktop" is also a folder: without the word PC it stays a command for THIS PC.
    assert understood("Desktop par Projects folder banao") is None
    assert understood("Desktop PC par Chrome kholo")[1]["pc_id"] == "b" * 16
    assert understood("doosre PC par Chrome kholo")[1] == {"pc": "", "pc_id": "", "command": "Chrome kholo"}
    # A PC that is not paired: answered as "not paired", never run here.
    assert understood("Ghar PC par Chrome kholo") == ("remote_command", {"pc": "Ghar", "pc_id": "",
                                                                         "command": "Chrome kholo"})
    for local in ("Chrome kholo", "is PC par Chrome kholo", "RAM batao", "system ka haal batao"):
        assert understood(local) is None, local


# ------------------------------------------------------------------ two NOVAs on one PC (real encrypted link)


def test_two_pcs_pair_and_work_together(tmp_path):
    office_desktop = FakeDesktop()
    with build_client(tmp_path / "home", multipc=LOOPBACK) as home, \
            build_client(tmp_path / "office", desktop=office_desktop, multipc=LOOPBACK,
                         permission_timeout_s=10) as office:
        home_status = enable(home, "Home Laptop")
        office_status = enable(office, "Office PC")
        assert home_status["this"]["id"] != office_status["this"]["id"]
        port = office_status["this"]["port"]

        # The office PC shows a code; the home PC types it.
        code = office.post("/api/pcs/pairing").json()["code"]
        assert office.get("/api/pcs").json()["pairing"]["code"] == code
        assert all(code not in (e.message or "") + json.dumps(e.data) for e in office.app.state.bus.history())
        paired = home.post("/api/pcs/pair", json={"host": "127.0.0.1", "port": port, "code": code.lower()}).json()
        assert paired == {"id": office_status["this"]["id"], "name": "Office PC"}
        assert office.get("/api/pcs").json()["pairing"] is None  # one code, one PC
        office_peers = office.get("/api/pcs").json()["peers"]
        assert [(p["name"], p["remote_allowed"]) for p in office_peers] == [("Home Laptop", False)]
        home_id = office_peers[0]["id"]
        stored = office.app.state.db.get_peer(home_id)["key_enc"]
        assert len(stored) > 60 and "key" not in stored  # the link key is stored encrypted (DPAPI)

        # Remote work is off until the office PC allows it.
        reply = cmd(home, "Office PC par Chrome kholo")
        assert "ijazat nahi" in reply["response"] and not [c for c in office_desktop.calls if c[0] == "launch"]
        assert home.get("/api/pcs").json()["peers"][0]["allows_us"] is False
        status = cmd(home, "Office PC ka haal batao")["response"]
        assert status.startswith("Office PC: online") and "ijazat nahi" in status

        office.put(f"/api/pcs/{home_id}", json={"remote_allowed": True})
        reply = cmd(home, "Hey NOVA, Office PC par Chrome kholo")
        assert reply["response"].startswith("Office PC: ") and reply["executed"]
        assert ("launch", "Google Chrome") in office_desktop.calls
        assert reply["plan"][0]["intent"] == "remote_command"
        remote = events(office, "REMOTE_TASK")
        assert remote[0].message.startswith("Home Laptop ne kaha: \"Chrome kholo\"")
        assert remote[-1].data["stage"] == "done"
        assert office.app.state.db.list_conversations(1)[0]["source"] == "remote"

        status = cmd(home, "Office PC ka haal batao")["response"]
        assert "online — CPU" in status and "RAM" in status

        # Needs permission there -> asked HERE, then done there.
        reply, asked = run_asking(home, "Office PC par Notepad band karo", approve=True)
        assert asked is not None and "Office PC par" in asked["question"] and asked["max_risk"] == "medium"
        assert not asked["items"][0]["rememberable"]  # remote approvals are never remembered
        assert ("close", 102) in office_desktop.calls and reply["executed"]
        approvals = office.get("/api/activity?q=close_app").json()
        assert any(r["permission_status"] == "approved_by_remote_user" for r in approvals)
        assert not office.get("/api/permissions/pending").json()  # nothing was asked on the office PC

        reply, asked = run_asking(home, "Office PC par Notepad band karo", approve=False)
        assert asked is not None and len([c for c in office_desktop.calls if c[0] == "close"]) == 1

        # Never from another PC: deleting, messages, typing.
        for text in ("Office PC par notes.txt delete karo", "Office PC par Ali ko whatsapp par likho ke salam",
                     "Office PC par likho: hello"):
            reply = cmd(home, text)
            assert "doosre PC se nahi hota" in reply["response"] and not reply["executed"], text
        assert not [c for c in office_desktop.calls if c[0] == "type"]
        refused = office.get("/api/activity?q=remote_refused").json()  # the office PC keeps its own record
        assert {r["task_name"] for r in refused} >= {"command:delete_file", "command:send_message", "command:type_text"}
        assert events(office, "REMOTE_TASK")[-1].data["stage"] == "refused"

        # The office PC removes the home PC: the home PC can no longer get in.
        assert office.delete(f"/api/pcs/{home_id}").status_code == 200
        assert office.get("/api/pcs").json()["peers"] == []
        wait_for(lambda: home.get("/api/pcs").json()["peers"] == [])  # it was told
        reply = cmd(home, "Office PC par Chrome kholo")
        assert "jura hua nahi" in reply["response"] and not reply["executed"]


def test_wrong_codes_and_strangers_are_refused(tmp_path):
    with build_client(tmp_path / "a", multipc=LOOPBACK) as a, build_client(tmp_path / "b", multipc=LOOPBACK) as b:
        enable(a, "PC A")
        port = enable(b, "PC B")["this"]["port"]
        right = b.post("/api/pcs/pairing").json()["code"]
        wrong = "0000-0000-0000" if right != "0000-0000-0000" else "1111-1111-1111"
        for _ in range(5):
            r = a.post("/api/pcs/pair", json={"host": "127.0.0.1", "port": port, "code": wrong})
            assert r.status_code == 409 and "Code ghalat" in r.json()["detail"]
        r = a.post("/api/pcs/pair", json={"host": "127.0.0.1", "port": port, "code": right})
        assert r.status_code == 409  # the 6th try: the code was closed after too many wrong ones
        wait_for(lambda: b.get("/api/pcs").json()["pairing"] is None)
        assert b.get("/api/pcs").json()["peers"] == [] and a.get("/api/pcs").json()["peers"] == []
        assert a.post("/api/pcs/pair", json={"host": "127.0.0.1", "port": port, "code": "short"}).status_code == 422

        # A PC with a made-up key never gets past the TLS handshake; plain TCP gets nothing either.
        service = a.app.state.multipc

        async def stranger():
            with pytest.raises(link.LinkError):
                await service._exchange("127.0.0.1", port, service.id, link.new_link_key(), {"type": "ping"})

        a.portal.call(stranger)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(b'{"type":"hello"}\n')
            s.settimeout(5)
            try:
                data = s.recv(100)
            except OSError:
                data = b""
        assert b"hello" not in data


def test_beacon_finds_nova_on_the_network(tmp_path):
    def free_udp_port():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    p1, p2 = free_udp_port(), free_udp_port()
    settings = type("S", (), {"multi_pc": True, "pc_name": ""})

    async def main():
        a = MultiPcService(Database(tmp_path / "a.db"), _Bus(), lambda: type("A", (settings,), {"pc_name": "PC A"}),
                           "0.13.0", peer_port=0, beacon_port=p1, loopback=True, beacon_targets=(p2,))
        b = MultiPcService(Database(tmp_path / "b.db"), _Bus(), lambda: type("B", (settings,), {"pc_name": "PC B"}),
                           "0.13.0", peer_port=0, beacon_port=p2, loopback=True, beacon_targets=(p1,))
        await a.apply()
        await b.apply()
        try:
            for _ in range(100):
                if b.id in a.seen and a.id in b.seen:
                    break
                await asyncio.sleep(0.05)
            assert a.seen[b.id].name == "PC B" and a.seen[b.id].port == b.port
            await b.open_pairing()
            b._beacon.announce()
            for _ in range(100):
                if a.seen[b.id].pairing:
                    break
                await asyncio.sleep(0.05)
            assert [f["name"] for f in a.status()["found"] if f["pairing"]] == ["PC B"]
        finally:
            await a.shutdown()
            await b.shutdown()

    asyncio.run(main())


def test_multi_pc_self_test(tmp_path):
    with build_client(tmp_path, multipc=LOOPBACK) as c:
        result = c.post("/api/admin/selftest", json={"scope": "13"}).json()["results"]
        assert [(r["id"], r["status"]) for r in result] == [("multi_pc", "info")]
        enable(c, "Test PC")
        result = c.post("/api/admin/selftest", json={"scope": "13"}).json()["results"][0]
        assert result["status"] == "pass" and result["detail"].startswith("0 PC jure")
