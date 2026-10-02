"""File operations for the File Agent. Every change is verified afterwards and recorded so it can be undone.

- delete moves the item to the Recycle Bin (never a permanent delete);
- edits keep a backup of the previous version in NOVA's data folder;
- rename/move/organize record every move so "pichla file kaam undo karo" can reverse it.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..agents.computer import ControlOutcome
from ..db import Database
from . import documents as docs
from .finder import Hit, SKIP_DIRS
from .recycle import has_recycle_bin, send_to_recycle_bin
from .scope import FileScope, ScopeError, validate_name

CATEGORIES: dict[str, tuple[str, ...]] = {
    "Images": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic", ".ico", ".tif", ".tiff", ".psd"),
    "Documents": (".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".epub"),
    "Spreadsheets": (".xls", ".xlsx", ".xlsm", ".csv", ".ods"),
    "Presentations": (".ppt", ".pptx", ".odp"),
    "Videos": (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v", ".3gp"),
    "Music": (".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma", ".opus"),
    "Archives": (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"),
    "Installers": (".exe", ".msi", ".msix", ".appx", ".apk", ".iso", ".dmg"),
    "Code": (".py", ".js", ".ts", ".php", ".html", ".css", ".json", ".xml", ".sql", ".java", ".c", ".cpp", ".cs",
             ".go", ".rb", ".sh", ".bat", ".ps1", ".ipynb", ".vue", ".jsx", ".tsx"),
}
OTHER = "Other"
# Never moved by "organize": shortcuts, system files, downloads still in progress.
ORGANIZE_SKIP = {".lnk", ".url", ".ini", ".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload"}
# Opening these runs a program or script: NOVA never does that.
EXECUTABLE_EXTS = {".exe", ".msi", ".msix", ".appx", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
                   ".wsh", ".hta", ".scr", ".com", ".lnk", ".reg", ".jar", ".pif", ".cpl", ".msc", ".py", ".pyw", ".sh"}
RECENT_S = 120  # a file changed this recently may still be in use (e.g. downloading)
MAX_ORGANIZE = 2000
MAX_COPY_BYTES = 5 * 1024**3
MAX_COPY_FILES = 20_000
BIG_DELETE_FILES = 100
BIG_DELETE_BYTES = 1024**3
MAX_LIST = 25


def size_text(n: int) -> str:
    for unit, factor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= factor:
            value = n / factor
            return f"{value:.1f} {unit}" if value < 10 else f"{value:.0f} {unit}"
    return f"{n} bytes"


def ago_text(timestamp: float) -> str:
    seconds = max(0.0, time.time() - timestamp)
    if seconds < 90:
        return "abhi"
    if seconds < 3600:
        return f"{int(seconds // 60)} minute pehle"
    if seconds < 86400:
        return f"{int(seconds // 3600)} ghante pehle"
    if seconds < 86400 * 30:
        return f"{int(seconds // 86400)} din pehle"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_stats(path: Path, limit: int = 200_000) -> tuple[int, int]:
    """(file count, total bytes) of a file or folder; stops counting after `limit` entries."""
    if path.is_file():
        return 1, path.stat().st_size
    files = total = seen = 0
    for root, dirs, names in os.walk(path):
        seen += len(dirs) + len(names)
        for name in names:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
        files += len(names)
        if seen > limit:
            break
    return files, total


def category_of(path: Path) -> str:
    suffix = path.suffix.lower()
    return next((cat for cat, exts in CATEGORIES.items() if suffix in exts), OTHER)


def unique_path(path: Path) -> Path:
    """"report.pdf" -> "report - Copy.pdf" -> "report - Copy (2).pdf" (Windows style)."""
    if not path.exists():
        return path
    stem, suffix = (path.stem, path.suffix) if path.is_file() or path.suffix else (path.name, "")
    candidate = path.with_name(f"{stem} - Copy{suffix}")
    n = 2
    while candidate.exists():
        candidate = path.with_name(f"{stem} - Copy ({n}){suffix}")
        n += 1
    return candidate


def _free_path(path: Path) -> Path:
    """A free name for a moved file: "a.txt" -> "a (2).txt"."""
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem} ({n}){path.suffix}")).exists():
        n += 1
    return candidate


@dataclass
class OrganizePlan:
    folder: Path
    moves: list[tuple[Path, Path]]
    counts: dict[str, int]
    skipped: int


def default_open(path: Path, editor: str | None) -> None:
    if docs.is_text(path):
        # Text and code open in an editor, never through their file association (a .js would run).
        subprocess.Popen([editor or "notepad.exe", str(path)])
    else:
        os.startfile(path)  # noqa: S606 - documents, media and folders, checked against EXECUTABLE_EXTS first


class FileOps:
    def __init__(
        self,
        scope: FileScope,
        db: Database,
        backups_dir: Path,
        reports_dir: Callable[[], Path],
        *,
        trash: Callable[[Path], None] = send_to_recycle_bin,
        can_trash: Callable[[Path], bool] = has_recycle_bin,
        opener: Callable[[Path, str | None], None] = default_open,
        editor: Callable[[], str | None] = lambda: None,
        window_titles: Callable[[], list[str]] | None = None,
        open_wait_s: float = 10.0,
    ) -> None:
        self.scope = scope
        self.db = db
        self.backups_dir = backups_dir
        self.reports_dir = reports_dir
        self._trash = trash
        self._can_trash = can_trash
        self._opener = opener
        self._editor = editor
        self._window_titles = window_titles
        self._open_wait_s = open_wait_s

    def show(self, path: Path) -> str:
        return self.scope.display(path)

    # ------------------------------------------------------------------ create

    def create_folder(self, parent: Path, name: str) -> ControlOutcome:
        target = self.scope.check_new(parent, name)
        target.mkdir()
        ok = target.is_dir()
        if ok:
            self._journal("create", f"folder {target.name} banaya", {"items": [self._item(target)]})
        return ControlOutcome(f"Folder \"{target.name}\" bana diya: {self.show(target)}. (Verify: folder mojood hai.)"
                              if ok else f"Folder \"{target.name}\" nahi ban saka.", "create_folder", ok,
                              "passed" if ok else "failed", str(target))

    def create_file(self, parent: Path, name: str, text: str = "") -> ControlOutcome:
        name = validate_name(name)
        if not Path(name).suffix and not name.startswith("."):
            name += ".txt"  # "notes naam ki file" -> notes.txt
        target = self.scope.check_new(parent, name)
        if target.suffix.lower() == ".docx":
            from docx import Document

            doc = Document()
            for line in text.split("\n") if text else []:
                doc.add_paragraph(line)
            doc.save(str(target))
        elif docs.is_text(target):
            target.write_text(text.rstrip("\n") + "\n" if text else "", encoding="utf-8")
        else:
            raise ScopeError(f"\"{target.suffix}\" qism ki file NOVA khud nahi banata — text, code ya Word (.docx) bana sakta hai.")
        ok = target.is_file() and (not text or text.strip().split("\n")[0] in docs.document_text(target))
        if ok:
            self._journal("create", f"file {target.name} banayi", {"items": [self._item(target)]})
        extra = " aur us mein text likh diya" if text else ""
        return ControlOutcome(f"File \"{target.name}\" bana di{extra}: {self.show(target)}. (Verify: file mojood hai.)"
                              if ok else f"File \"{target.name}\" sahi nahi ban saki.", "create_file", ok,
                              "passed" if ok else "failed", str(target))

    # ------------------------------------------------------------------ rename / move / copy

    def rename_target(self, path: Path, new_name: str) -> Path:
        """Where a rename would put `path` (the extension is kept when the new name has none)."""
        source = self.scope.check_movable(path)
        new_name = validate_name(new_name)
        if source.is_file() and source.suffix and not Path(new_name).suffix:
            new_name += source.suffix
        dest = source.with_name(new_name)
        if dest.exists() and os.path.normcase(str(dest)) != os.path.normcase(str(source)):
            raise ScopeError(f"\"{dest.name}\" naam ki file/folder pehle se mojood hai.")
        self.scope.check(dest, write=True, must_exist=False)
        return dest

    def rename(self, path: Path, new_name: str) -> ControlOutcome:
        source = self.scope.check_movable(path)
        dest = self.rename_target(source, new_name)
        source.rename(dest)
        ok = dest.exists() and (not source.exists() or os.path.normcase(str(dest)) == os.path.normcase(str(source)))
        if ok:
            self._journal("move", f"{source.name} ka naam {dest.name} rakha", {"moves": [[str(source), str(dest)]]})
        return ControlOutcome(f"\"{source.name}\" ka naam \"{dest.name}\" rakh diya. (Verify: nayi file mojood hai.)"
                              if ok else "Naam badalne ki koshish ki, lekin verify nahi ho saka.", "rename_file", ok,
                              "passed" if ok else "failed", str(dest))

    def move_target(self, path: Path, folder: Path) -> Path:
        source = self.scope.check_movable(path)
        dest_dir = self.scope.check(folder, write=True)
        if not dest_dir.is_dir():
            raise ScopeError(f"\"{dest_dir.name}\" folder nahi hai.")
        if dest_dir == source.parent:
            raise ScopeError(f"\"{source.name}\" pehle se {self.show(dest_dir)} mein hai.")
        if source.is_dir() and (dest_dir == source or dest_dir.is_relative_to(source)):
            raise ScopeError("Folder ko uske apne andar move nahi kiya ja sakta.")
        dest = dest_dir / source.name
        if dest.exists():
            raise ScopeError(f"{self.show(dest_dir)} mein \"{source.name}\" pehle se mojood hai.")
        return dest

    def move(self, path: Path, folder: Path) -> ControlOutcome:
        source = self.scope.check_movable(path)
        dest = self.move_target(source, folder)
        shutil.move(str(source), str(dest))
        ok = dest.exists() and not source.exists()
        if ok:
            self._journal("move", f"{source.name} ko {self.show(dest.parent)} mein move kiya",
                          {"moves": [[str(source), str(dest)]]})
        return ControlOutcome(f"\"{source.name}\" ko {self.show(dest.parent)} mein move kar diya. (Verify: nayi jagah par "
                              "hai, purani jagah khaali.)" if ok else "Move ki koshish ki, lekin verify nahi ho saka.",
                              "move_file", ok, "passed" if ok else "failed", str(dest))

    def copy(self, path: Path, folder: Path | None = None) -> ControlOutcome:
        source = self.scope.check(path)
        dest_dir = self.scope.check(folder or source.parent, write=True)
        if not dest_dir.is_dir():
            raise ScopeError(f"\"{dest_dir.name}\" folder nahi hai.")
        if source.is_dir() and (dest_dir == source or dest_dir.is_relative_to(source)):
            raise ScopeError("Folder ko uske apne andar copy nahi kiya ja sakta.")
        files, size = tree_stats(source)
        if size > MAX_COPY_BYTES or files > MAX_COPY_FILES:
            raise ScopeError(f"Ye bohat bara hai ({files} files, {size_text(size)}) — NOVA 5 GB / 20,000 files tak copy karta hai.")
        dest = unique_path(dest_dir / source.name)
        if source.is_dir():
            shutil.copytree(source, dest)
            ok = dest.is_dir() and tree_stats(dest)[0] == files
        else:
            shutil.copy2(source, dest)
            ok = dest.is_file() and dest.stat().st_size == source.stat().st_size
        if ok:
            self._journal("create", f"{source.name} ki copy {dest.name} banayi", {"items": [self._item(dest)]})
        return ControlOutcome(f"\"{source.name}\" ki copy bana di: {self.show(dest)}. (Verify: copy poori hai.)"
                              if ok else "Copy poori verify nahi ho saki.", "copy_file", ok,
                              "passed" if ok else "failed", str(dest))

    # ------------------------------------------------------------------ delete (Recycle Bin)

    def delete_check(self, path: Path) -> tuple[Path, int, int]:
        target = self.scope.check_movable(path)
        if not self._can_trash(target):
            raise ScopeError("Is drive par Recycle Bin nahi — NOVA yahan se delete nahi karta (wapas nahi aa sakta).")
        files, size = tree_stats(target)
        return target, files, size

    def delete(self, path: Path) -> ControlOutcome:
        target, files, _size = self.delete_check(path)
        what = f"folder ({files} files)" if target.is_dir() else "file"
        try:
            self._trash(target)
        except OSError as exc:
            return ControlOutcome(f"\"{target.name}\" Recycle Bin mein nahi gaya: {exc}.", "delete_file", False, "failed")
        ok = not target.exists()
        if ok:
            self._journal("delete", f"{target.name} Recycle Bin mein bheja", {"path": str(target)})
        return ControlOutcome(f"\"{target.name}\" {what} Recycle Bin mein bhej diya — zaroorat ho to wahan se Restore kar "
                              "sakte hain. (Verify: ab yahan mojood nahi.)" if ok else
                              "Delete ki koshish ki, lekin item abhi bhi mojood hai.", "delete_file", ok,
                              "passed" if ok else "failed", str(target))

    # ------------------------------------------------------------------ read / open

    def list_folder(self, folder: Path) -> ControlOutcome:
        folder = self.scope.check(folder)
        entries = []
        with os.scandir(folder) as it:
            for entry in it:
                if entry.name.startswith(".") or entry.name.lower() in ("desktop.ini", "thumbs.db"):
                    continue
                entries.append(entry)
        dirs = sorted((e for e in entries if e.is_dir()), key=lambda e: e.name.lower())
        files = sorted((e for e in entries if not e.is_dir()), key=lambda e: e.stat().st_mtime, reverse=True)
        lines = [f"{self.show(folder)} mein {len(files)} files aur {len(dirs)} folders hain."]
        lines += [f"[folder] {d.name}" for d in dirs[:10]]
        lines += [f"{f.name} ({size_text(f.stat().st_size)}, {ago_text(f.stat().st_mtime)})" for f in files[:MAX_LIST - min(len(dirs), 10)]]
        if len(dirs) + len(files) > MAX_LIST:
            lines.append(f"...aur {len(dirs) + len(files) - MAX_LIST} cheezein.")
        return ControlOutcome("\n".join(lines), "list_folder", True, "not_applicable", str(folder))

    def read(self, path: Path) -> tuple[ControlOutcome, docs.DocContent | None]:
        target = self.scope.check(path)
        if target.is_dir():
            return self.list_folder(target), None
        try:
            content = docs.read_document(target)
        except docs.DocumentError as exc:
            return ControlOutcome(str(exc), "read_file", False, "not_applicable"), None
        shown = content.text[:1800]
        more = " (shuru ka hissa — baqi file mein)" if content.truncated or len(content.text) > 1800 else ""
        body = f"```\n{shown.rstrip()}\n```" if content.kind in ("code", "text") else shown.strip()
        return ControlOutcome(f"\"{target.name}\" ({content.detail}){more}:\n{body}", "read_file", True,
                              "not_applicable", str(target)), content

    def open(self, path: Path) -> ControlOutcome:
        target = self.scope.check(path)
        if target.is_file() and target.suffix.lower() in EXECUTABLE_EXTS and not docs.is_text(target):
            return ControlOutcome(f"\"{target.name}\" program/script hai — NOVA isay nahi chalata. Chalana ho to aap khud "
                                  "double-click karein.", "open_file", False, "not_applicable")
        try:
            self._opener(target, self._editor())
        except OSError as exc:
            return ControlOutcome(f"\"{target.name}\" khul nahi saka: {exc}.", "open_file", False, "failed")
        if self._window_titles is None:
            return ControlOutcome(f"\"{target.name}\" khol diya.", "open_file", True, "unverified", str(target))
        needle = (target.stem if target.is_file() else target.name).lower()
        deadline = time.monotonic() + self._open_wait_s
        while time.monotonic() < deadline:
            if any(needle in t.lower() for t in self._window_titles()):
                return ControlOutcome(f"\"{target.name}\" khul gaya. (Verify: window nazar aayi.)", "open_file", True,
                                      "passed", str(target))
            time.sleep(0.4)
        return ControlOutcome(f"\"{target.name}\" kholne ki command de di, lekin uski window nazar nahi aayi — screen check "
                              "kar lein.", "open_file", True, "unverified", str(target))

    # ------------------------------------------------------------------ edit (with backup)

    def edit_check(self, path: Path) -> Path:
        target = self.scope.check(path, write=True)
        if target.is_dir() or not docs.is_editable(target):
            raise ScopeError(f"\"{target.name}\" ko NOVA edit nahi kar sakta — text, code aur Word (.docx) files edit hoti hain.")
        if not target.suffix.lower() == ".docx":
            docs.read_text_file(target)  # raises if too big, binary or not UTF-8
        return target

    def edit(self, path: Path, action: str, text: str = "", old: str = "", new: str = "") -> ControlOutcome:
        target = self.edit_check(path)
        if action == "replace" and not old:
            return ControlOutcome("Kya badalna hai? Purana aur naya text dono batayein.", "edit_file", False, "not_applicable")
        if action == "append" and not text.strip():
            return ControlOutcome("Kya likhna hai? Text batayein.", "edit_file", False, "not_applicable")
        before = docs.document_text(target)
        if action == "replace" and old not in before:
            return ControlOutcome(f"\"{target.name}\" mein \"{old}\" nahi mila — kuch nahi badla.", "edit_file", False,
                                  "not_applicable")
        backup = self._backup(target)
        if action == "replace":
            count = docs.replace_text(target, old, new)
            after = docs.document_text(target)
            ok = count > 0 and (new in after if new else True) and (old not in after or old in new)
            message = f"\"{target.name}\" mein \"{old}\" ko \"{new}\" se badal diya ({count} jagah)."
        else:
            docs.append_text(target, text)
            after = docs.document_text(target)
            ok = after.rstrip().endswith(text.strip().split("\n")[-1].strip())
            message = f"\"{target.name}\" mein text likh diya (aakhir mein)."
        if ok:
            self._journal("edit", f"{target.name} edit ki", {"path": str(target), "backup": str(backup),
                                                              "after_hash": file_hash(target)})
        return ControlOutcome(f"{message} (Verify: file dobara parh kar check kiya. Purani file ka backup rakha hai.)"
                              if ok else "Edit ki koshish ki, lekin verify nahi ho saka — backup se wapas laane ke liye "
                              "'pichla file kaam undo karo' kahein.", "edit_file", ok, "passed" if ok else "failed",
                              str(target))

    def write_new_content(self, path: Path, content: docs.TextFile, summary: str) -> Path:
        """Used by the Coding Agent: backup, write, journal. Returns the backup path."""
        target = self.edit_check(path)
        backup = self._backup(target)
        docs.write_text_file(target, content)
        self._journal("edit", summary, {"path": str(target), "backup": str(backup), "after_hash": file_hash(target)})
        return backup

    def _backup(self, path: Path) -> Path:
        folder = self.backups_dir / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / path.name
        shutil.copy2(path, dest)
        return dest

    # ------------------------------------------------------------------ organize

    def plan_organize(self, folder: Path) -> OrganizePlan:
        folder = self.scope.check(folder, write=True)
        if not folder.is_dir():
            raise ScopeError(f"\"{folder.name}\" folder nahi hai.")
        root = self.scope.root_of(folder)
        if root is not None and root.kind == "projects":
            raise ScopeError("Project folders organize nahi kiye jate — files hilane se code toot sakta hai.")
        moves: list[tuple[Path, Path]] = []
        counts: dict[str, int] = {}
        skipped = 0
        now = time.time()
        taken: set[str] = set()
        for entry in sorted(os.scandir(folder), key=lambda e: e.name.lower()):
            if entry.is_dir() or entry.name.startswith("."):
                continue
            path = Path(entry.path)
            if path.suffix.lower() in ORGANIZE_SKIP or now - entry.stat().st_mtime < RECENT_S:
                skipped += 1
                continue
            category = category_of(path)
            dest = folder / category / path.name
            n = 2
            while dest.exists() or os.path.normcase(str(dest)) in taken:
                dest = folder / category / f"{path.stem} ({n}){path.suffix}"
                n += 1
            taken.add(os.path.normcase(str(dest)))
            moves.append((path, dest))
            counts[category] = counts.get(category, 0) + 1
            if len(moves) >= MAX_ORGANIZE:
                break
        return OrganizePlan(folder, moves, counts, skipped)

    def organize_preview(self, plan: OrganizePlan) -> str:
        lines = [f"{self.show(plan.folder)}: {len(plan.moves)} files ye folders mein jayengi:"]
        for category, count in sorted(plan.counts.items(), key=lambda kv: -kv[1]):
            examples = [s.name for s, d in plan.moves if d.parent.name == category][:3]
            lines.append(f"  {category}/  ({count})  " + ", ".join(examples) + (" ..." if count > 3 else ""))
        if plan.skipped:
            lines.append(f"  {plan.skipped} files nahi hilengi (shortcuts, adhoori downloads, ya abhi abhi badli hui)")
        return "\n".join(lines)

    def organize(self, plan: OrganizePlan) -> ControlOutcome:
        if not plan.moves:
            return ControlOutcome(f"{self.show(plan.folder)} mein tarteeb dene layak files nahi mili.", "organize_folder",
                                  False, "not_applicable")
        created = []
        done: list[list[str]] = []
        failed = 0
        for source, dest in plan.moves:
            if not dest.parent.exists():
                dest.parent.mkdir()
                created.append(str(dest.parent))
            if not source.exists() or dest.exists():
                failed += 1
                continue
            try:
                shutil.move(str(source), str(dest))
                done.append([str(source), str(dest)])
            except OSError:
                failed += 1
        verified = sum(1 for s, d in done if Path(d).exists() and not Path(s).exists())
        if done:
            self._journal("move", f"{plan.folder.name} organize kiya ({len(done)} files)",
                          {"moves": done, "created_dirs": created})
        ok = verified == len(done) and failed == 0
        summary = ", ".join(f"{c} ({n})" for c, n in sorted(plan.counts.items(), key=lambda kv: -kv[1]))
        message = f"{self.show(plan.folder)} organize ho gaya: {verified} files folders mein — {summary}."
        if failed:
            message += f" {failed} files nahi hil sakin (shayad istemal mein thin)."
        return ControlOutcome(message + " (Verify: har file nayi jagah check ki.) Wapas karna ho to: "
                              "'pichla file kaam undo karo'.", "organize_folder", bool(done),
                              "passed" if ok else "failed", str(plan.folder))

    # ------------------------------------------------------------------ report

    def report(self, folder: Path) -> ControlOutcome:
        folder = self.scope.check(folder)
        if not folder.is_dir():
            raise ScopeError(f"\"{folder.name}\" folder nahi hai.")
        counts: dict[str, list[int]] = {}
        files: list[Hit] = []
        dirs = 0
        deadline = time.monotonic() + 15
        partial = False
        for root, dirnames, names in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            dirs += len(dirnames)
            for name in names:
                p = Path(root) / name
                try:
                    st = p.stat()
                except OSError:
                    continue
                c = counts.setdefault(category_of(p), [0, 0])
                c[0] += 1
                c[1] += st.st_size
                files.append(Hit(p, False, st.st_size, st.st_mtime, 0))
            if time.monotonic() > deadline or len(files) > 200_000:
                partial = True
                break
        total = sum(h.size for h in files)
        now = datetime.now()
        lines = [f"# Folder report: {self.show(folder)}", "", f"*NOVA · {now:%Y-%m-%d %H:%M}*", "",
                 f"- Files: {len(files)}", f"- Folders: {dirs}", f"- Total size: {size_text(total)}", "",
                 "## Qism ke hisaab se", "", "| Qism | Files | Size |", "| --- | ---: | ---: |"]
        lines += [f"| {cat} | {n} | {size_text(sz)} |" for cat, (n, sz) in sorted(counts.items(), key=lambda kv: -kv[1][1])]
        lines += ["", "## Sab se bari files", ""]
        lines += [f"- {self.show(h.path)} — {size_text(h.size)}" for h in sorted(files, key=lambda h: -h.size)[:10]]
        lines += ["", "## Sab se nayi files", ""]
        lines += [f"- {self.show(h.path)} — {ago_text(h.modified)}" for h in sorted(files, key=lambda h: -h.modified)[:10]]
        if partial:
            lines += ["", "> Folder bohat bara tha — report adhoori hai."]
        out_dir = self.reports_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{now:%Y-%m-%d_%H%M}_{folder.name or 'drive'}-report.md"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok = out.is_file() and out.stat().st_size > 0
        top = ", ".join(f"{cat} {n}" for cat, (n, _sz) in sorted(counts.items(), key=lambda kv: -kv[1][0])[:4])
        return ControlOutcome(f"{self.show(folder)}: {len(files)} files, {dirs} folders, {size_text(total)}"
                              + (f" ({top})" if top else "") + f". Report save ho gayi: {out}", "folder_report", ok,
                              "passed" if ok else "failed", str(out))

    # ------------------------------------------------------------------ undo

    def last_op(self) -> dict | None:
        return self.db.last_file_op()

    def undo(self) -> ControlOutcome:
        op = self.db.last_file_op()
        if op is None:
            return ControlOutcome("NOVA ka koi file kaam undo karne ke liye baqi nahi.", "undo_file_op", False,
                                  "not_applicable")
        data, kind = op["data"], op["op"]
        if kind == "delete":
            self.db.mark_file_op_undone(op["id"])
            name = Path(data["path"]).name
            return ControlOutcome(f"\"{name}\" Recycle Bin mein hai: Recycle Bin kholein, us par right-click karke "
                                  "Restore dabayein. NOVA khud Recycle Bin se wapas nahi laata.", "undo_file_op",
                                  False, "not_applicable")
        if kind == "move":
            restored, failed = 0, 0
            for source, dest in reversed(data["moves"]):
                s, d = Path(source), Path(dest)
                if d.exists() and not s.exists():
                    s.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(d), str(s))
                    restored += s.exists() and not d.exists()
                else:
                    failed += 1
            for folder in data.get("created_dirs", []):
                with contextlib.suppress(OSError):
                    Path(folder).rmdir()  # only if empty
            ok = failed == 0
            message = f"Wapas kar diya: {restored} cheezein purani jagah par ({op['summary']})."
            if failed:
                message += f" {failed} cheezein wapas nahi ho sakin (shayad baad mein badal gayin)."
        elif kind == "edit":
            path, backup = Path(data["path"]), Path(data["backup"])
            if not backup.exists() or not path.exists():
                return ControlOutcome("Backup ya file ab mojood nahi — undo nahi ho saka.", "undo_file_op", False, "failed")
            if file_hash(path) != data["after_hash"]:
                return ControlOutcome(f"\"{path.name}\" NOVA ki tabdeeli ke baad phir badli gayi hai — undo karne se wo naya "
                                      "kaam mit jayega, is liye nahi kiya.", "undo_file_op", False, "not_applicable")
            shutil.copy2(backup, path)
            ok = file_hash(path) == file_hash(backup)
            message = f"\"{path.name}\" pehle jaisi kar di (backup se)."
        else:  # create
            removed, kept = 0, []
            for item in data["items"]:
                p = Path(item["path"])
                if not p.exists():
                    continue
                if item["dir"]:
                    if any(p.iterdir()):
                        kept.append(p.name)
                        continue
                    p.rmdir()
                elif p.stat().st_size != item["size"] or abs(p.stat().st_mtime - item["mtime"]) > 2:
                    kept.append(p.name)
                    continue
                else:
                    self._trash(p)
                removed += not p.exists()
            ok = not kept
            message = f"Hata diya: {removed} nayi cheezein jo NOVA ne banayi thin."
            if kept:
                message += f" {', '.join(kept)} mein baad mein kaam hua hai, is liye nahi hataya."
        self.db.mark_file_op_undone(op["id"])
        return ControlOutcome(message + " (Verify: check kiya.)", "undo_file_op", True, "passed" if ok else "failed")

    def undo_preview(self) -> str | None:
        op = self.db.last_file_op()
        return f"{op['summary']} ({op['created_at'].replace('T', ' ')})" if op else None

    # ------------------------------------------------------------------ journal

    def _item(self, path: Path) -> dict:
        st = path.stat()
        return {"path": str(path), "dir": path.is_dir(), "size": 0 if path.is_dir() else st.st_size,
                "mtime": st.st_mtime}

    def _journal(self, op: str, summary: str, data: dict) -> None:
        self.db.add_file_op(op, summary, data)
