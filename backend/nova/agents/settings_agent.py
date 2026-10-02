"""System Agent, Windows settings part: volume/mute, brightness, dark/light mode, Wi-Fi, Bluetooth, and
opening the right Settings page for everything else. Security settings are refused, never changed.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable

from ..ai.base import Intent
from ..control.settings import SETTINGS_PAGES, SettingsError, WindowsSettings
from .computer import ControlOutcome
from .prepared import Prepared, Reply

NAME = "System Agent"
SETTINGS_INTENTS = {"change_setting", "open_settings"}
Progress = Callable[[str], Awaitable[None]]

SETTING_WORDS = [  # checked in order; first match wins
    ("unmute", r"\bunmute\b|awaaz\s+(?:wapas|khol|chalu)|sound\s+on"),
    ("mute", r"\bmute\b|(?:awaaz|aawaz|sound|speaker|volume)\s+band"),
    ("volume", r"\bvolume\b|\bawaaz\b|\baawaz\b|\bsound\b|\bspeaker\b"),
    ("brightness", r"\bbrightness\b|\broshni\b|\bchamak\b"),
    ("theme", r"\bdark\b|\blight\s+mode\b|\btheme\b|\bkala\s+mode\b"),
    ("wifi", r"\bwi-?fi\b"),
    ("bluetooth", r"\bbluetooth\b"),
    ("default_browser", r"default\s+browser|\bbrowser\b.*\bdefault\b|\bdefault\b.*\bbrowser\b"),
]
PAGE_WORDS = [
    ("default_apps", r"default"), ("display", r"display|screen|resolution"), ("sound", r"\bsound\b|awaaz|audio"),
    ("bluetooth", r"bluetooth"), ("wifi", r"wi-?fi"), ("network", r"internet|network"),
    ("update", r"update"), ("night_light", r"night\s*light|raat"), ("colors", r"colou?rs?|\brang\b"),
    ("background", r"wallpaper|background"), ("notifications", r"notification"), ("focus", r"focus|do not disturb"),
    ("power", r"power|sleep"), ("battery", r"battery"), ("storage", r"storage|disk"), ("startup", r"startup"),
    ("apps", r"\bapps?\b|programs?"), ("mouse", r"mouse|touchpad"), ("keyboard", r"keyboard|typing"),
    ("language", r"language|zaban"), ("date_time", r"date|time|waqt|tareekh"), ("microphone", r"\bmic"),
    ("camera", r"camera"), ("privacy", r"privacy"), ("accounts", r"account"), ("printers", r"printer|scanner"),
    ("about", r"\babout\b"), ("security", r"security|defender|antivirus|firewall"),
]
# NOVA never changes these; it can only open Windows Security for the user to look.
SECURITY = re.compile(r"\b(?:defender|anti-?virus|virus|firewall|uac|user account control|bitlocker|smart\s*screen|"
                      r"security|tamper|password|pin\b|sign[\s-]?in|login|admin)", re.IGNORECASE)
UP = {"up", "zyada", "ziada", "barhao", "barha", "tez", "ooncha", "oonchi", "high", "increase", "louder", "plus"}
DOWN = {"down", "kam", "ghatao", "ghata", "dheema", "dheemi", "halka", "halki", "low", "decrease", "minus"}
ON_WORDS = {"on", "chalu", "khol", "kholo", "enable", "start", "shuru", "connect"}
OFF_WORDS = {"off", "band", "disable", "stop", "disconnect"}
DARK_WORDS = {"dark", "kala", "kaala", "andhera", "night", "black"}
LIGHT_WORDS = {"light", "roshan", "safed", "white"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def parse_level(text: str, current: int, step: int) -> int | None:
    """"50", "50%", "aadha", "full", "thora kam", "bohat zyada" -> a 0-100 level."""
    t = text.lower()
    if m := re.search(r"\b(\d{1,3})\b", t):
        return max(0, min(100, int(m.group(1))))
    w = _words(t)
    if w & {"aadha", "aadhi", "half"}:
        return 50
    if w & {"full", "poori", "pura", "poora", "max", "maximum"}:
        return 100
    step *= 2 if "bohat" in w else 1  # "bohat kam" / "bohat zyada": a bigger step
    if w & DOWN:
        return max(0, current - step)
    if w & UP:
        return min(100, current + step)
    return None


class SettingsAgent:
    def __init__(self, settings: WindowsSettings, window_titles: Callable[[], list[str]] | None = None,
                 verify_wait_s: float = 5.0) -> None:
        self.ws = settings
        self._window_titles = window_titles
        self._verify_wait_s = verify_wait_s

    async def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        return await asyncio.to_thread(fn, *args)

    # ------------------------------------------------------------------ prepare

    async def prepare(self, intent: Intent, progress: Progress) -> Prepared | Reply:
        try:
            return await self._prepare(intent)
        except SettingsError as exc:
            return Reply(f"{exc}.")
        except OSError as exc:
            return Reply(f"Windows se setting parhi nahi ja saki ({type(exc).__name__}).")

    def _page(self, text: str) -> str | None:
        for key, pattern in PAGE_WORDS:
            if re.search(pattern, text, re.IGNORECASE):
                return key
        return None

    def _open_page(self, key: str, note: str = "") -> Prepared:
        uri, title = SETTINGS_PAGES[key]
        return Prepared(f"Settings ka \"{title}\" page kholna", f"page:{key}",
                        data={"op": "page", "uri": uri, "title": title, "note": note})

    async def _prepare(self, intent: Intent) -> Prepared | Reply:
        e = intent.entities
        words = " ".join(str(e.get(k) or "") for k in ("setting", "value", "request", "page")).strip()
        if intent.name == "open_settings":
            key = self._page(words) or "home"
            return self._open_page(key)
        setting = str(e.get("setting") or "").lower()
        if setting not in ("volume", "mute", "unmute", "brightness", "theme", "wifi", "bluetooth", "default_browser"):
            setting = next((name for name, pattern in SETTING_WORDS if re.search(pattern, words, re.IGNORECASE)), "")
        value = str(e.get("value") or e.get("request") or "")
        if SECURITY.search(words) and setting not in ("volume", "mute", "unmute", "brightness"):
            return Reply("Security settings (Defender, firewall, UAC, passwords) NOVA kabhi nahi badalta — ye aap khud "
                         "karein. Dekhna ho to kahein \"Windows Security kholo\".", refused=True)

        if setting == "volume":
            current = await self._call(self.ws.volume)
            target = parse_level(value or words, current, 10)
            if target is None:
                return Reply(f"Volume abhi {current}% hai. Kitna karna hai? (maslan \"volume 50 karo\")")
            if target == current:
                return Reply(f"Volume pehle se {current}% hai.")
            return Prepared(f"Volume {current}% se {target}% karna", "volume",
                            data={"op": "volume", "value": target, "before": current})
        if setting in ("mute", "unmute"):
            mute = setting == "mute"
            if await self._call(self.ws.muted) == mute:
                return Reply("Awaaz pehle se band (mute) hai." if mute else "Awaaz pehle se chalu hai.")
            return Prepared("Awaaz band (mute) karna" if mute else "Awaaz wapas chalu (unmute) karna", "mute",
                            data={"op": "mute", "value": mute})
        if setting == "brightness":
            current = await self._call(self.ws.brightness)
            if current is None:
                return Reply("Is screen ki brightness NOVA nahi badal sakta (sirf laptop ki apni screen). Kahein "
                             "\"display settings kholo\".")
            target = parse_level(value or words, current, 20)
            if target is None:
                return Reply(f"Brightness abhi {current}% hai. Kitni karni hai? (maslan \"brightness 60 karo\")")
            if target == current:
                return Reply(f"Brightness pehle se {current}% hai.")
            return Prepared(f"Brightness {current}% se {target}% karna", "brightness",
                            data={"op": "brightness", "value": target, "before": current})
        if setting == "theme":
            w = _words(f"{value} {words}")
            if w & DARK_WORDS:
                target = "light" if w & OFF_WORDS else "dark"  # "dark mode band karo" means light
            elif w & LIGHT_WORDS:
                target = "dark" if w & OFF_WORDS else "light"
            else:
                return Reply("Dark mode karna hai ya light mode?")
            current = await self._call(self.ws.theme)
            if current == target:
                return Reply(f"Pehle se {target} mode hai.")
            return Prepared(f"Windows ko {target} mode karna", "theme", min_risk="medium",
                            reasons=["Windows aur apps ke rang badal jayenge (wapas: \"" +
                                     ("light" if target == "dark" else "dark") + " mode karo\")"],
                            data={"op": "theme", "value": target, "before": current})
        if setting in ("wifi", "bluetooth"):
            w = _words(f"{value} {words}")
            if w & OFF_WORDS:
                on = False
            elif w & ON_WORDS:
                on = True
            else:
                state = await self._call(self.ws.radio, setting)
                return Reply(f"{'Wi-Fi' if setting == 'wifi' else 'Bluetooth'} abhi {state} hai. On karna hai ya off?")
            label = "Wi-Fi" if setting == "wifi" else "Bluetooth"
            current = await self._call(self.ws.radio, setting)
            if current == ("on" if on else "off"):
                return Reply(f"{label} pehle se {current} hai.")
            reasons = []
            if not on:
                reasons.append("Internet band ho jayega — web search aur research nahi chalenge" if setting == "wifi"
                               else "Bluetooth headphones, speaker ya mouse disconnect ho jayenge")
            return Prepared(f"{label} {'on' if on else 'off'} karna", setting, min_risk="low" if on else "medium",
                            reasons=reasons, data={"op": "radio", "kind": setting, "value": on})
        if setting == "default_browser":
            return self._open_page("default_apps", note="Windows default browser khud badalne nahi deta (aap ki "
                                                       "hifazat ke liye) — wahan browser chun kar \"Set default\" dabayein.")
        if key := self._page(words):
            return self._open_page(key, note="Ye setting NOVA khud nahi badalta — wahan aap badal sakte hain.")
        return Reply("Ye setting NOVA nahi badal sakta. Volume, brightness, dark mode, Wi-Fi aur Bluetooth badal sakta "
                     "hoon; baqi ke liye kahein \"<naam> settings kholo\".")

    # ------------------------------------------------------------------ run

    async def run(self, intent: Intent, prepared: Prepared, approved: bool, progress: Progress) -> ControlOutcome:
        d = prepared.data
        if prepared.min_risk != "low" and not approved:
            raise PermissionError(f"{intent.name} requires the user's permission")
        try:
            return await self._run(d)
        except SettingsError as exc:
            return ControlOutcome(f"{exc}.", "change_setting", False, "failed")
        except OSError as exc:
            return ControlOutcome(f"Windows ne ye setting nahi badalne di ({type(exc).__name__}).", "change_setting",
                                  False, "failed")

    async def _run(self, d: dict[str, Any]) -> ControlOutcome:
        op = d["op"]
        if op == "volume":
            await self._call(self.ws.set_volume, d["value"])
            now = await self._call(self.ws.volume)
            ok = abs(now - d["value"]) <= 2
            return ControlOutcome(f"Volume {d['value']}% kar diya. (Verify: ab {now}% hai.)" if ok else
                                  f"Volume badalne ki koshish ki lekin abhi {now}% hai.", "set_volume", True,
                                  "passed" if ok else "failed")
        if op == "mute":
            await self._call(self.ws.set_mute, d["value"])
            ok = await self._call(self.ws.muted) == d["value"]
            text = "Awaaz band (mute) kar di." if d["value"] else "Awaaz wapas chalu kar di."
            return ControlOutcome(text + (" (Verify: check kiya.)" if ok else " Lekin verify nahi ho saka."), "mute",
                                  True, "passed" if ok else "failed")
        if op == "brightness":
            await self._call(self.ws.set_brightness, d["value"])
            now = await self._call(self.ws.brightness)
            ok = now is not None and abs(now - d["value"]) <= 5
            return ControlOutcome(f"Brightness {d['value']}% kar di. (Verify: ab {now}% hai.)" if ok else
                                  f"Brightness badalne ki koshish ki lekin abhi {now}% hai.", "set_brightness", True,
                                  "passed" if ok else "failed")
        if op == "theme":
            await self._call(self.ws.set_theme, d["value"])
            ok = await self._call(self.ws.theme) == d["value"]
            return ControlOutcome(f"Windows {d['value']} mode mein kar diya. (Verify: setting check ki.)" if ok else
                                  "Theme badalne ki koshish ki lekin verify nahi ho saki.", "set_theme", True,
                                  "passed" if ok else "failed")
        if op == "radio":
            label = "Wi-Fi" if d["kind"] == "wifi" else "Bluetooth"
            await self._call(self.ws.set_radio, d["kind"], d["value"])
            want = "on" if d["value"] else "off"
            deadline = time.monotonic() + self._verify_wait_s
            now = await self._call(self.ws.radio, d["kind"])
            while now != want and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                now = await self._call(self.ws.radio, d["kind"])
            ok = now == want
            return ControlOutcome(f"{label} {want} kar diya. (Verify: ab {now} hai.)" if ok else
                                  f"{label} {want} karne ki koshish ki lekin abhi {now} hai.", f"{d['kind']}_{want}", True,
                                  "passed" if ok else "failed")
        # Settings page
        await self._call(self.ws.open_page, d["uri"])
        note = f" {d['note']}" if d.get("note") else ""
        verified = await self._settings_window_seen(d["title"])
        return ControlOutcome(f"Settings ka \"{d['title']}\" page khol diya.{note}" +
                              (" (Verify: Settings window nazar aayi.)" if verified else ""), "open_settings", True,
                              "passed" if verified else "unverified")

    async def _settings_window_seen(self, title: str) -> bool:
        if self._window_titles is None:
            return False
        deadline = time.monotonic() + self._verify_wait_s
        while time.monotonic() < deadline:
            titles = await asyncio.to_thread(self._window_titles)
            if any(t in ("Settings", title, "Windows Security") or t.endswith("Settings") for t in titles):
                return True
            await asyncio.sleep(0.4)
        return False
