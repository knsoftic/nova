"""File Agent: search, create, open, read, rename, move, copy, delete (Recycle Bin), edit, organize, report, undo.

Works only inside the allowed folders (see files/scope.py). Names are resolved to real paths before
anything happens; when a name matches several files NOVA lists them and asks which one ("pehli wali").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..ai.base import Intent
from ..files import documents as docs
from ..files.finder import Hit, query_types, search
from ..files.ops import FileOps, ago_text, size_text
from ..files.scope import SECRET_FILE, FileScope, ScopeError
from .computer import ControlOutcome
from .prepared import Prepared, Reply

NAME = "File Agent"
FILE_INTENTS = {"search_files", "create_folder", "create_file", "open_file", "read_file", "rename_file", "move_file",
                "copy_file", "delete_file", "edit_file", "organize_folder", "folder_report", "undo_file_op"}

PRONOUNS = {"isko", "isey", "ise", "isay", "is", "in", "un", "ye", "yeh", "usko", "usey", "use", "usay", "us", "wo", "woh", "it",
            "this", "that", "inko", "unko", "iski", "uski", "is file", "ye file", "yeh file", "wo file", "woh file",
            "us file", "is folder", "ye folder", "wo folder", "us folder", "this file", "that file", "this folder"}
ORDINALS = {"pehli": 0, "pehla": 0, "pehle": 0, "first": 0, "1st": 0, "doosri": 1, "dusri": 1, "doosra": 1,
            "dusra": 1, "second": 1, "2nd": 1, "teesri": 2, "tisri": 2, "teesra": 2, "third": 2, "3rd": 2,
            "chauthi": 3, "chautha": 3, "fourth": 3, "4th": 3, "panchvi": 4, "panchwi": 4, "fifth": 4, "5th": 4}
ORDINAL = re.compile(r"^(?:(?P<word>\w+)|(?:number\s+)?(?P<num>\d+)(?:\s+number)?)(?:\s+(?:wali|wala|wale|file|folder|"
                     r"number|nambar))*$", re.IGNORECASE)
IN_LOCATION = re.compile(r"^(?P<loc>.+?)\s+(?:ki|ke|ka|wali|wala|mein|me|par|pe|se)\s+(?P<name>\S.*)$", re.IGNORECASE)
NAME_SUFFIX = re.compile(r"\s+(?:naam\s+(?:ki|ka|ke)\s+)?(?:wali\s+|wala\s+)?(?:file|folder)$", re.IGNORECASE)
DEFAULT_PARENT = "desktop"


@dataclass
class FileContext:
    last_results: list[Path] = field(default_factory=list)  # numbered list shown to the user
    last_path: Path | None = None  # "isko", "is file"
    last_folder: Path | None = None


class FileAgent:
    def __init__(self, ops: FileOps, scope: FileScope,
                 projects: Callable[[str], Path | list[str] | None] = lambda name: None) -> None:
        """`projects(name)` finds a code project folder by name (from the Coding Agent)."""
        self.ops = ops
        self.scope = scope
        self.projects = projects
        self.ctx = FileContext()

    # ------------------------------------------------------------------ resolving names

    def _ordinal(self, text: str) -> int | None:
        m = ORDINAL.match(text.strip())
        if not m:
            return None
        if m["num"]:
            return int(m["num"]) - 1
        return ORDINALS.get(m["word"].lower())

    def _is_location(self, text: str) -> bool:
        low = text.lower().strip()
        return bool(self.scope.known(re.sub(r"\s+folder$", "", low))) or low.endswith((" project", " folder")) \
            or bool(re.match(r"^[a-z]:\\", low))

    def resolve_folder(self, location: str | None, default: Path | None = None) -> Path | Reply:
        loc = (location or "").strip().strip("\"'")
        if not loc:
            if default is not None:
                return default
            return Reply("Kaun sa folder? (maslan Desktop, Documents, Downloads)")
        bare = re.sub(r"\s+(?:wala\s+|wali\s+)?(?:folder|directory)$", "", loc, flags=re.IGNORECASE).strip()
        low = bare.lower()
        if low in PRONOUNS and self.ctx.last_folder:
            return self.ctx.last_folder
        if known := self.scope.known(low):
            return known
        if re.match(r"^[a-z]:\\", low):
            try:
                path = self.scope.check(Path(loc))
            except ScopeError as exc:
                return Reply(str(exc), refused=True)
            return path if path.is_dir() else Reply(f"\"{path.name}\" folder nahi hai.")
        if m := re.match(r"^(?P<p>.+?)\s+project$", low):
            found = self.projects(m["p"])
            if isinstance(found, Path):
                return found
            if isinstance(found, list):
                return Reply(f"\"{m['p']}\" se kai projects milte hain: {', '.join(found[:6])} — poora naam batayein.")
            return Reply(f"\"{m['p']}\" naam ka project nahi mila.")
        for root in self.scope.roots():
            if root.name.lower() == low:
                return root.path
        if (m := IN_LOCATION.match(bare)) and self._is_location(m["loc"]):  # "desktop ke Projects"
            parent = self.resolve_folder(m["loc"])
            if isinstance(parent, Reply):
                return parent
            return self._pick(m["name"], [parent], want_dir=True, what="folder", exact_only=True)
        # Only the exact folder name: a near match could put a new file into the wrong place without asking.
        # (Projects are found by name only when the user says "... project".)
        return self._pick(bare, [r.path for r in self.scope.roots()], want_dir=True, what="folder", exact_only=True)

    def resolve_target(self, target: str | None, location: str | None = None,
                       want_dir: bool | None = None) -> Path | Reply:
        t = (target or "").strip().strip("\"'").strip()
        low = t.lower()
        if not t or low in PRONOUNS:
            if self.ctx.last_path is not None and self.ctx.last_path.exists():
                return self.ctx.last_path
            return Reply("Kaun si file? Uska naam batayein.")
        index = self._ordinal(low)
        if index is not None:
            if not self.ctx.last_results:
                return Reply("Pehle file dhoondein (maslan \"report files dhoondo\"), phir \"pehli wali\" kahein.")
            if 0 <= index < len(self.ctx.last_results):
                return self.ctx.last_results[index]
            return Reply(f"Pichli list mein sirf {len(self.ctx.last_results)} cheezein thin.")
        if re.match(r"^[a-z]:\\", low):
            try:
                return self.scope.check(Path(t))
            except ScopeError as exc:
                return Reply(str(exc), refused=True)
        if not location and (m := IN_LOCATION.match(t)) and self._is_location(m["loc"]):
            location, t = m["loc"], m["name"]
        if want_dir is None and re.search(r"\bfolder$", t, re.IGNORECASE):
            want_dir = True  # "NOVA-Test folder" means the folder, not files with that name
        name = NAME_SUFFIX.sub("", t).strip()
        if SECRET_FILE.search(name):  # searches hide these; say why instead of "nahi mila"
            return Reply(f"\"{name}\" mein passwords/keys hoti hain — NOVA isay na kholta hai na badalta hai.", refused=True)
        if want_dir is not False and not location and (known := self.scope.known(re.sub(r"\s+folder$", "", name.lower()))):
            return known
        if location:
            folder = self.resolve_folder(location)
            if isinstance(folder, Reply):
                return folder
            roots = [folder]
        else:
            roots = [r.path for r in self.scope.roots()]
        return self._pick(name, roots, want_dir=want_dir, what="folder" if want_dir else "file")

    def _find(self, roots: list[Path], query: str, exts: tuple[str, ...] | None = None, *,
              want_dirs: bool | None = None, limit: int = 10, budget_s: float = 4.0):
        """Search that never enters NOVA's private data and never lists secret files."""
        return search(roots, query, exts, want_dirs=want_dirs, limit=limit, budget_s=budget_s,
                      exclude_dirs=self.scope.private_dirs(), hide=SECRET_FILE)

    def _pick(self, name: str, roots: list[Path], want_dir: bool | None, what: str,
              exact_only: bool = False) -> Path | Reply:
        result = self._find(roots, name, want_dirs=want_dir, limit=8, budget_s=3.0)
        exact = [h for h in result.hits if h.score >= 90]
        if exact_only and not exact and result.hits:
            names = ", ".join(f"\"{h.path.name}\" ({self.ops.show(h.path.parent)})" for h in result.hits[:4])
            return Reply(f"\"{name}\" naam ka {what} nahi mila. Milte julte: {names} — poora naam batayein.")
        candidates = exact or result.hits
        if len(candidates) == 1:
            return candidates[0].path
        if not candidates:
            where = self.ops.show(roots[0]) if len(roots) == 1 else "aap ke folders"
            more = " (search poori nahi ho saki — folder batayein)" if result.truncated else ""
            return Reply(f"{where} mein \"{name}\" naam ka {what} nahi mila{more}.")
        self.ctx.last_results = [h.path for h in candidates[:6]]
        return Reply(f"\"{name}\" naam ki {len(candidates)} cheezein mili — kaun si? (maslan \"pehli wali\")\n"
                     + self._numbered(candidates[:6]))

    def _numbered(self, hits: list[Hit]) -> str:
        lines = []
        for n, h in enumerate(hits, 1):
            info = "folder" if h.is_dir else f"{size_text(h.size)}, {ago_text(h.modified)}"
            lines.append(f"{n}. {h.path.name} — {self.ops.show(h.path.parent)} ({info})")
        return "\n".join(lines)

    # ------------------------------------------------------------------ prepare (before asking)

    def prepare(self, intent: Intent) -> Prepared | Reply:
        try:
            return self._prepare(intent)
        except ScopeError as exc:
            return Reply(str(exc), refused=True)
        except docs.DocumentError as exc:
            return Reply(str(exc))

    def _prepare(self, intent: Intent) -> Prepared | Reply:
        e = intent.entities
        name = intent.name
        if name == "undo_file_op":
            preview = self.ops.undo_preview()
            if preview is None:
                return Reply("NOVA ka koi file kaam undo karne ke liye baqi nahi.")
            return Prepared(f"wapas karna: {preview}", "undo", preview=preview, always_ask=True)

        if name == "search_files":
            folder = self.resolve_folder(e.get("location")) if e.get("location") else None
            if isinstance(folder, Reply):
                return folder
            query, exts = query_types(str(e.get("query") or ""))
            if not query and not exts:
                return Reply("Kya dhoondna hai? File ka naam ya qism batayein (maslan \"pdf files\").")
            return Prepared(f"dhoondna: {e.get('query')}", "search", data={"folder": folder, "query": query, "exts": exts})

        if name in ("create_folder", "create_file"):
            default = self.ctx.last_folder or self.scope.known(DEFAULT_PARENT)
            parent = self.resolve_folder(e.get("location"), default)
            if isinstance(parent, Reply):
                return parent
            new = str(e.get("folder_name" if name == "create_folder" else "file_name") or "").strip()
            if not new:
                return Reply("Kis naam se? (maslan \"Projects naam ka folder banao\")")
            if name == "create_file" and not Path(new).suffix and not new.startswith("."):
                new += ".txt"
            target = self.scope.check_new(parent, new)
            return Prepared(f"\"{target.name}\" banana ({self.ops.show(parent)})", f"create@{parent}",
                            data={"parent": parent, "name": target.name, "text": str(e.get("text") or "")})

        if name in ("open_file", "read_file"):
            path = self.resolve_target(e.get("target"), e.get("location"))
            if isinstance(path, Reply):
                return path
            self.scope.check(path)
            return Prepared(f"\"{path.name}\" ({self.ops.show(path.parent)})", f"{name}@{path.parent}",
                            data={"path": path})

        if name == "copy_file":
            path = self.resolve_target(e.get("target"), e.get("location"))
            if isinstance(path, Reply):
                return path
            dest = self.resolve_folder(e.get("destination"), path.parent) if e.get("destination") else path.parent
            if isinstance(dest, Reply):
                return dest
            return Prepared(f"\"{path.name}\" ki copy {self.ops.show(dest)} mein", f"copy@{dest}",
                            data={"path": path, "dest": dest})

        if name == "rename_file":
            path = self.resolve_target(e.get("target"), e.get("location"))
            if isinstance(path, Reply):
                return path
            new_name = str(e.get("new_name") or "").strip()
            if not new_name:
                return Reply(f"\"{path.name}\" ka naya naam kya rakhna hai?")
            dest = self.ops.rename_target(path, new_name)
            return Prepared(f"\"{path.name}\" ka naam \"{dest.name}\" rakhna ({self.ops.show(path.parent)})",
                            f"rename@{path.parent}", count=1, data={"path": path, "new_name": dest.name})

        if name == "move_file":
            path = self.resolve_target(e.get("target"), e.get("location"))
            if isinstance(path, Reply):
                return path
            if not e.get("destination"):
                return Reply(f"\"{path.name}\" ko kahan le jana hai?")
            dest = self.resolve_folder(e.get("destination"))
            if isinstance(dest, Reply):
                return dest
            final = self.ops.move_target(path, dest)
            return Prepared(f"\"{path.name}\" ko {self.ops.show(path.parent)} se {self.ops.show(dest)} mein le jana",
                            f"move@{dest}", count=1, data={"path": path, "dest": final.parent})

        if name == "delete_file":
            path = self.resolve_target(e.get("target"), e.get("location"))
            if isinstance(path, Reply):
                return path
            target, files, size = self.ops.delete_check(path)
            kind = f"folder: {files} files, {size_text(size)}" if target.is_dir() else size_text(size)
            preview = None
            if target.is_dir():
                names = sorted(p.name for p in list(target.iterdir())[:12])
                preview = "\n".join(names) + ("\n..." if files > 12 else "")
            return Prepared(f"\"{target.name}\" ({kind}) Recycle Bin mein bhejna — {self.ops.show(target.parent)}",
                            f"delete@{target.parent}", preview=preview, count=files, size=size, always_ask=True,
                            data={"path": target})

        if name == "edit_file":
            path = self.resolve_target(e.get("target"), e.get("location"), want_dir=False)
            if isinstance(path, Reply):
                return path
            target = self.ops.edit_check(path)
            action = "replace" if e.get("edit_action") == "replace" or e.get("old_text") else "append"
            if action == "replace":
                old, new = str(e.get("old_text") or ""), str(e.get("new_text") or "")
                if not old:
                    return Reply("Kya badalna hai? Purana text batayein.")
                count = docs.document_text(target).count(old)
                if not count:
                    return Reply(f"\"{target.name}\" mein \"{old}\" nahi mila — kuch nahi badla.")
                summary = f"\"{target.name}\" mein \"{old[:40]}\" ko \"{new[:40]}\" se badalna ({count} jagah)"
                preview = f"- {old}\n+ {new}"
            else:
                text = str(e.get("text") or "")
                if not text.strip():
                    return Reply("Kya likhna hai? Text batayein.")
                summary = f"\"{target.name}\" ke aakhir mein text likhna"
                preview = "\n".join(f"+ {ln}" for ln in text.split("\n"))
            return Prepared(summary, f"edit@{target}", preview=preview, count=1, always_ask=True,
                            data={"path": target, "action": action, "text": str(e.get("text") or ""),
                                  "old": str(e.get("old_text") or ""), "new": str(e.get("new_text") or "")})

        if name == "organize_folder":
            folder = self.resolve_folder(e.get("location") or e.get("target"))
            if isinstance(folder, Reply):
                return folder
            plan = self.ops.plan_organize(folder)
            if not plan.moves:
                return Reply(f"{self.ops.show(folder)} mein tarteeb dene layak files nahi (sirf folders, shortcuts ya "
                             "abhi badli hui files hain).")
            return Prepared(f"{self.ops.show(folder)} ki {len(plan.moves)} files ko qism ke hisaab se folders mein rakhna",
                            f"organize@{folder}", preview=self.ops.organize_preview(plan), count=len(plan.moves),
                            always_ask=True, data={"plan": plan})

        if name == "folder_report":
            folder = self.resolve_folder(e.get("location") or e.get("target"))
            if isinstance(folder, Reply):
                return folder
            return Prepared(f"{self.ops.show(folder)} ki report", f"report@{folder}", data={"folder": folder})

        raise ValueError(f"Not a file intent: {name}")

    # ------------------------------------------------------------------ run (after permission, if needed)

    def run(self, intent: Intent, prepared: Prepared,
            approved: bool = False) -> tuple[ControlOutcome, docs.DocContent | None]:
        name = intent.name
        if name in ("rename_file", "move_file", "delete_file", "edit_file", "organize_folder", "undo_file_op") \
                and not approved:
            raise PermissionError(f"{name} requires the user's permission")
        d = prepared.data
        content = None
        match name:
            case "search_files":
                result = self._search(d["folder"], d["query"], d["exts"])
            case "create_folder":
                result = self.ops.create_folder(d["parent"], d["name"])
            case "create_file":
                result = self.ops.create_file(d["parent"], d["name"], d["text"])
            case "open_file":
                result = self.ops.open(d["path"])
            case "read_file":
                result, content = self.ops.read(d["path"])
            case "copy_file":
                result = self.ops.copy(d["path"], d["dest"])
            case "rename_file":
                result = self.ops.rename(d["path"], d["new_name"])
            case "move_file":
                result = self.ops.move(d["path"], d["dest"])
            case "delete_file":
                result = self.ops.delete(d["path"])
            case "edit_file":
                result = self.ops.edit(d["path"], d["action"], d["text"], d["old"], d["new"])
            case "organize_folder":
                result = self.ops.organize(d["plan"])
            case "folder_report":
                result = self.ops.report(d["folder"])
            case "undo_file_op":
                result = self.ops.undo()
            case _:
                raise ValueError(f"Not a file intent: {name}")
        self._remember(name, result)
        return result, content

    def _remember(self, intent: str, result: ControlOutcome) -> None:
        """Keep "isko"/"is folder" pointing at what the user just worked with."""
        if not result.executed or not result.detail or intent in ("undo_file_op", "folder_report"):
            return
        path = Path(result.detail)
        if intent == "delete_file":
            if self.ctx.last_path == path:
                self.ctx.last_path = None
            return
        if path.exists():
            self.ctx.last_path = path
            self.ctx.last_folder = path if path.is_dir() else path.parent

    def _search(self, folder: Path | None, query: str, exts: tuple[str, ...] | None) -> ControlOutcome:
        roots = [folder] if folder else [r.path for r in self.scope.roots()]
        result = self._find(roots, query, exts, limit=10)
        where = self.ops.show(folder) if folder else "Aap ke folders"
        what = " ".join(filter(None, [query, "/".join(x.lstrip(".") for x in exts or ())]))
        if not result.hits:
            more = " (search poori nahi ho saki — folder bata kar dobara koshish karein)" if result.truncated else ""
            return ControlOutcome(f"{where} mein \"{what}\" se milti koi file nahi mili{more}.", "search_files", True,
                                  "not_applicable")
        self.ctx.last_results = [h.path for h in result.hits]
        if len(result.hits) == 1:
            self.ctx.last_path = result.hits[0].path
        more = "\n(Bohat files thin — search adhoora; folder bata kar dobara dhoondein.)" if result.truncated else ""
        return ControlOutcome(f"{where} mein \"{what}\" se milti {len(result.hits)} cheezein mili:\n"
                              + self._numbered(result.hits) + more, "search_files", True, "not_applicable")
