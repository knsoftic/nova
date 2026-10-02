"""Design Agent: edit pictures (size, format, compress, crop presets, rotate, black & white, caption, watermark),
make simple designs from a template (post, story, banner, thumbnail, poster...), and open a file in a design app.

Everything stays on this PC. Originals are never changed; every result is a new file that is opened again to
verify it. Created designs go to Pictures\\NOVA\\Designs.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
import winreg
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..agents.computer import ControlOutcome
from ..agents.prepared import Prepared, Reply
from ..ai.base import Intent
from ..files.ops import EXECUTABLE_EXTS, size_text
from ..files.scope import FileScope, ScopeError
from . import images as im

NAME = "Design Agent"
DESIGN_INTENTS = {"edit_image", "create_design", "open_with"}
Progress = Callable[[str], Awaitable[None]]

# Apps a file can be opened in: (App Paths name, label). Paths come from Windows' own registry, never from the user.
APPS = {
    "photoshop": ("Photoshop.exe", "Photoshop"), "paint": ("mspaint.exe", "Paint"),
    "illustrator": ("Illustrator.exe", "Illustrator"), "gimp": ("gimp-2.10.exe", "GIMP"),
    "word": ("WINWORD.EXE", "Word"), "excel": ("EXCEL.EXE", "Excel"), "powerpoint": ("POWERPNT.EXE", "PowerPoint"),
    "notepad": ("notepad.exe", "Notepad"),
}
APP_WORDS = {"photoshop": "photoshop", "ps": "photoshop", "paint": "paint", "mspaint": "paint",
             "illustrator": "illustrator", "gimp": "gimp", "word": "word", "excel": "excel",
             "powerpoint": "powerpoint", "notepad": "notepad", "vs code": "vscode", "vscode": "vscode", "code": "vscode"}
OPERATIONS = ("resize", "fit", "convert", "compress", "rotate", "flip", "grayscale", "caption", "watermark")


def app_path(exe: str) -> str | None:
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                value, _ = winreg.QueryValueEx(key, "")
                value = os.path.expandvars(value.strip('"'))
                if os.path.isfile(value):
                    return value
        except OSError:
            continue
    return None


def parse_operation(text: str) -> tuple[str, Any] | None:
    """User words -> (operation, value). Value: (w, h) | percent | format | degrees | bool | text."""
    t = text.lower()
    if m := re.search(r"['\"“”‘’](?P<q>.+?)['\"“”‘’]\s*(?:ka\s+)?watermark|watermark\s+['\"“”‘’](?P<q2>.+?)['\"“”‘’]", text,
                      re.IGNORECASE):
        return "watermark", (m.group("q") or m.group("q2")).strip()
    if m := re.search(r"['\"“”‘’](?P<q>.+?)['\"“”‘’]\s*(?:likho|likh do|lagao|caption)", text, re.IGNORECASE):
        return "caption", m.group("q").strip()
    if m := re.search(r"(\d{2,5})\s*[x×*]\s*(\d{2,5})", t):
        return "fit", (int(m.group(1)), int(m.group(2)))
    for name in sorted(im.PRESETS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", t):
            return "fit", im.PRESETS[name]
    if m := re.search(r"(\d{1,3})\s*(?:%|percent|fisad)", t):
        return "resize", int(m.group(1))
    if m := re.search(r"\b(png|jpe?g|webp|bmp|gif|ico|pdf|tiff?)\b", t):
        return "convert", m.group(1)
    if re.search(r"compress|halki|halka|size\s+kam|chhoti\s+file|kam\s+size", t):
        return "compress", 75
    if re.search(r"ghum|rotate|seedha|seedhi|degree|darje", t):
        m = re.search(r"\b(90|180|270)\b", t)
        degrees = int(m.group(1)) if m else 90
        if re.search(r"ulta|anti|left|baayen|baen", t):
            degrees = -degrees
        return "rotate", degrees
    if re.search(r"flip|mirror|ulti|ulta", t):
        return "flip", bool(re.search(r"upar\s+neeche|vertical", t))
    if re.search(r"black\s*(?:and|&)\s*white|grayscale|greyscale|be\s*rang|bina\s+rang|sada", t):
        return "grayscale", True
    if re.search(r"chhot|half|aadh", t):
        return "resize", 50
    return None


class DesignAgent:
    def __init__(
        self,
        scope: FileScope,
        designs_dir: Callable[[], Path],
        resolve_file: Callable[[str], Path | Any],
        remember: Callable[[Path], None] = lambda path: None,
        *,
        opener: Callable[[Path], None] = lambda path: os.startfile(path),  # noqa: S606 - a verified image file
        launcher: Callable[[str, Path], None] = lambda exe, path: subprocess.Popen([exe, str(path)]),
        app_lookup: Callable[[str], str | None] = app_path,
        code_exe: Callable[[], str | None] = lambda: None,
        window_titles: Callable[[], list[str]] | None = None,
        open_wait_s: float = 20.0,
    ) -> None:
        self.scope = scope
        self.designs_dir = designs_dir
        self.resolve_file = resolve_file
        self.remember = remember
        self._open = opener
        self._launch = launcher
        self._app_lookup = app_lookup
        self._code_exe = code_exe
        self._window_titles = window_titles
        self._open_wait_s = open_wait_s

    def _image(self, target: str) -> Path | Reply:
        path = self.resolve_file(target)
        if not isinstance(path, Path):
            return path if isinstance(path, Reply) else Reply(f"\"{target}\" nahi mili.")
        if path.suffix.lower() not in im.IMAGE_EXTS:
            return Reply(f"\"{path.name}\" tasveer nahi (jpg, png, webp...).")
        return path

    # ------------------------------------------------------------------ prepare

    async def prepare(self, intent: Intent, progress: Progress) -> Prepared | Reply:
        try:
            return await asyncio.to_thread(self._prepare, intent)
        except (ScopeError, im.ImageError) as exc:
            return Reply(str(exc) if str(exc).endswith(".") else f"{exc}.")

    def _prepare(self, intent: Intent) -> Prepared | Reply:
        e = intent.entities
        if intent.name == "create_design":
            return self._prepare_design(e)
        if intent.name == "open_with":
            return self._prepare_open_with(e)
        path = self._image(str(e.get("target") or ""))
        if isinstance(path, Reply):
            return path
        self.scope.check(path.parent, write=True)  # the new file goes next to the original
        op = str(e.get("operation") or "")
        value: Any = e.get("value")
        if op not in OPERATIONS or value in (None, ""):
            parsed = parse_operation(f"{op} {value or ''} {e.get('request') or ''}")
            if parsed is None:
                return Reply(f"\"{path.name}\" ke sath kya karna hai? (maslan \"1080x1080 karo\", \"png mein badlo\", "
                             "\"compress karo\", \"90 degree ghumao\", \"black and white karo\")")
            op, value = parsed
        with im.Image.open(path) as probe:
            before = probe.size
        what, ext = self._describe(op, value, path)
        target = im.result_path(path, what.replace(" ", "-"), ext)
        return Prepared(f"\"{path.name}\" ({before[0]}x{before[1]}) → {what}: \"{target.name}\"", f"image:{op}",
                        data={"op": op, "value": value, "path": path, "out": target})

    @staticmethod
    def _describe(op: str, value: Any, path: Path) -> tuple[str, str | None]:
        if op == "fit":
            return f"{value[0]}x{value[1]}", None
        if op == "resize":
            return f"{value}%", None
        if op == "convert":
            if str(value).lower() not in im.FORMATS:
                raise im.ImageError(f"\"{value}\" format NOVA nahi banata")
            return str(value).lower(), im.FORMATS[str(value).lower()][1]
        if op == "compress":
            return "compressed", ".jpg" if path.suffix.lower() in (".png", ".bmp", ".tif", ".tiff") else None
        if op == "rotate":
            return f"rotated {value}", None
        if op == "flip":
            return "flipped", None
        if op == "grayscale":
            return "bw", None
        if op in ("caption", "watermark"):
            im.check_text(str(value))
            return op, None
        raise im.ImageError("Ye kaam NOVA tasveer par nahi kar sakta")

    def _prepare_design(self, e: dict[str, Any]) -> Prepared | Reply:
        kind = str(e.get("kind") or "post").lower().strip()
        size = im.PRESETS.get(kind) or next((s for name, s in im.PRESETS.items() if name in kind), (1080, 1080))
        title = " ".join(str(e.get("text") or "").split()).strip("\"'“”")
        if not title:
            return Reply("Design par kya likhna hai? (maslan \"Instagram post banao jis par 'Grand Sale' likha ho\")")
        subtitle = " ".join(str(e.get("subtitle") or "").split()).strip("\"'“”")
        im.check_text(f"{title} {subtitle}")
        colors = im.colors_from(f"{e.get('style') or ''} {e.get('colors') or ''}", seed=title)
        folder = self.designs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self.scope.check(folder, write=True)
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "design"
        out = folder / f"{datetime.now():%Y-%m-%d_%H%M%S}_{kind.replace(' ', '-')}_{slug}.png"
        return Prepared(f"{kind} ({size[0]}x{size[1]}) banana: \"{title}\"", "design",
                        data={"size": size, "title": title, "subtitle": subtitle, "colors": colors, "out": out,
                              "kind": kind})

    def _prepare_open_with(self, e: dict[str, Any]) -> Prepared | Reply:
        target = str(e.get("target") or "")
        path = self.resolve_file(target)
        if not isinstance(path, Path):
            return path if isinstance(path, Reply) else Reply(f"\"{target}\" nahi mili.")
        if path.suffix.lower() in EXECUTABLE_EXTS - {".js", ".py", ".sh", ".ps1", ".bat", ".cmd"}:
            return Reply(f"\"{path.name}\" program hai — NOVA isay kisi app mein nahi kholta.", refused=True)
        key = APP_WORDS.get(str(e.get("app") or "").lower().strip())
        if key is None:
            return Reply(f"\"{e.get('app')}\" app NOVA ki list mein nahi (Photoshop, Paint, Word, Excel, PowerPoint, "
                         "Notepad, VS Code).")
        if key == "vscode":
            exe, label = self._code_exe(), "VS Code"
        else:
            exe, label = self._app_lookup(APPS[key][0]), APPS[key][1]
        if not exe:
            return Reply(f"{label} is PC par nahi mila.")
        return Prepared(f"\"{path.name}\" ko {label} mein kholna", f"open_with:{key}",
                        data={"path": path, "exe": exe, "label": label})

    # ------------------------------------------------------------------ run

    async def run(self, intent: Intent, prepared: Prepared, approved: bool, progress: Progress) -> ControlOutcome:
        d = prepared.data
        try:
            if intent.name == "create_design":
                await progress("Design bana raha hai...")
                result = await asyncio.to_thread(self._create, d)
            elif intent.name == "open_with":
                result = await asyncio.to_thread(self._open_with, d)
            else:
                result = await asyncio.to_thread(self._edit, d)
        except (im.ImageError, OSError) as exc:
            return ControlOutcome(f"{exc}.", intent.name, False, "failed")
        if result.executed and result.detail:
            self.remember(Path(result.detail))
        return result

    def _edit(self, d: dict[str, Any]) -> ControlOutcome:
        src: Path = d["path"]
        img = im.open_image(src)
        op, value, out = d["op"], d["value"], d["out"]
        fmt = None
        quality = 90
        if op == "fit":
            img = im.fit(img, *value)
        elif op == "resize":
            img = im.scale(img, int(value))
        elif op == "convert":
            fmt = im.FORMATS[str(value).lower()][0]
        elif op == "compress":
            quality = int(value) if str(value).isdigit() else 75
            fmt = "WEBP" if out.suffix.lower() == ".webp" else "JPEG"
            w, h = img.size
            if max(w, h) > 2560:  # very large photos: also scale down to a sensible size
                img = im.scale(img, int(2560 * 100 / max(w, h)))
        elif op == "rotate":
            img = im.rotate(img, int(value))
        elif op == "flip":
            img = im.mirror(img, bool(value))
        elif op == "grayscale":
            img = im.grayscale(img)
        elif op == "caption":
            img = im.caption(img, str(value))
        elif op == "watermark":
            img = im.watermark(img, str(value))
        result = im.save(img, out, fmt, quality)
        before = src.stat().st_size
        extra = f", {size_text(before)} → {size_text(result.bytes)}" if op in ("compress", "convert", "resize") else ""
        return ControlOutcome(f"Nayi tasveer bana di: \"{out.name}\" ({result.size[0]}x{result.size[1]}{extra}). Original "
                              f"\"{src.name}\" waisi hi hai. (Verify: nayi file khol kar size/format check kiya.)",
                              "edit_image", True, "passed", str(out))

    def _create(self, d: dict[str, Any]) -> ControlOutcome:
        img = im.create_design(d["size"], d["title"], d["subtitle"], d["colors"])
        result = im.save(img, d["out"], "PNG")
        try:
            self._open(result.path)
            shown = " aur khol di"
        except OSError:
            shown = ""
        return ControlOutcome(f"{d['kind'].title()} design bana di{shown}: {result.path.name} ({result.size[0]}x"
                              f"{result.size[1]}) — Pictures\\NOVA\\Designs mein. (Verify: file khol kar size check kiya.)",
                              "create_design", True, "passed", str(result.path))

    def _open_with(self, d: dict[str, Any]) -> ControlOutcome:
        path: Path = d["path"]
        self._launch(d["exe"], path)
        if self._window_titles is None:
            return ControlOutcome(f"\"{path.name}\" {d['label']} mein khol di.", "open_with", True, "unverified", str(path))
        deadline = time.monotonic() + self._open_wait_s
        needle = path.stem.lower()
        while time.monotonic() < deadline:
            if any(needle in t.lower() for t in self._window_titles()):
                return ControlOutcome(f"\"{path.name}\" {d['label']} mein khul gayi. (Verify: window nazar aayi.)",
                                      "open_with", True, "passed", str(path))
            time.sleep(0.5)
        return ControlOutcome(f"{d['label']} ko \"{path.name}\" kholne ki command de di — {d['label']} bari app hai, khulne "
                              "mein waqt lag sakta hai.", "open_with", True, "unverified", str(path))
