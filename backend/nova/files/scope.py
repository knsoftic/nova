"""Where the File and Coding agents may work (the admin chose this scope for Phase 8B).

Allowed: the user's Desktop, Documents, Downloads, Pictures, Music and Videos (their real, possibly
redirected locations) and the project folders from Settings (default C:\\xampp\\htdocs). Paths are fully
resolved (".." and links followed) before they are checked, so nothing can escape. Inside the allowed
folders NOVA still never:
- reads or changes secret files (.env, private keys, credential stores);
- changes anything inside .git, or NOVA's own program folder (its data folder is not even read);
- deletes, renames or moves one of the allowed folders itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

KNOWN_FOLDERS = ("desktop", "documents", "downloads", "pictures", "music", "videos")
KNOWN_LABELS = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads", "pictures": "Pictures",
                "music": "Music", "videos": "Videos"}
# Spoken/typed names for the known folders (Roman Urdu, English, Urdu, Hindi).
FOLDER_WORDS = {
    "desktop": "desktop", "ڈیسک ٹاپ": "desktop", "डेस्कटॉप": "desktop",
    "documents": "documents", "document": "documents", "docs": "documents", "dastavezat": "documents",
    "my documents": "documents", "ڈاکومنٹس": "documents",
    "downloads": "downloads", "download": "downloads", "ڈاؤن لوڈز": "downloads", "डाउनलोड": "downloads",
    "pictures": "pictures", "picture": "pictures", "photos": "pictures", "tasveerein": "pictures",
    "tasveeren": "pictures", "tasveer": "pictures",
    "music": "music", "songs": "music", "gaane": "music",
    "videos": "videos", "video": "videos",
}

# Secret stores: never shown, summarised or edited. Templates such as ".env.example" are fine.
SECRET_FILE = re.compile(
    r"^(?:\.env(?:\.(?!example$|sample$|template$|dist$)[^.]+)?|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|"
    r"credentials(?:\.json)?|\.npmrc|\.pypirc|\.netrc|\.git-credentials|secrets?\.(?:json|ya?ml|toml))$"
    r"|\.(?:pem|key|pfx|p12|kdbx|keystore|jks|ppk)$",
    re.IGNORECASE,
)
_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com\d|lpt\d)(?:\..*)?$", re.IGNORECASE)


class ScopeError(Exception):
    """A path or name NOVA may not use. The message is Roman Urdu and safe to show to the user."""


@dataclass(frozen=True)
class Root:
    name: str  # shown to the user: "Desktop", "Documents", "htdocs"
    path: Path  # resolved
    kind: str  # "folder" (a known user folder) | "projects"


def validate_name(name: str) -> str:
    """A single file/folder name (no path) that Windows accepts."""
    name = name.strip().strip("\"'")
    if not name or name in (".", ".."):
        raise ScopeError("Naam khaali hai — koi naam batayein.")
    if _BAD_NAME_CHARS.search(name):
        raise ScopeError(f"\"{name}\" mein aise nishan hain jo Windows file ke naam mein nahi le sakti (\\ / : * ? \" < > |).")
    if _RESERVED.match(name) or name.endswith((".", " ")) or len(name) > 200:
        raise ScopeError(f"\"{name}\" Windows mein file ka naam nahi ho sakta.")
    return name


class FileScope:
    def __init__(
        self,
        known: Callable[[str], Path],
        project_folders: Callable[[], list[str]],
        protected: list[Path] | None = None,
        private: list[Path] | None = None,
    ) -> None:
        """`protected`: readable but never changed (NOVA's own program). `private`: never read or changed
        (NOVA's data: database, browser profile with cookies, models)."""
        self._known = known
        self._project_folders = project_folders
        self._protected = [p.resolve() for p in protected or []]
        self._private = [p.resolve() for p in private or []]

    # ------------------------------------------------------------------ roots

    def roots(self) -> list[Root]:
        roots: list[Root] = []
        for key in KNOWN_FOLDERS:
            path = self._known(key)
            if path.is_dir():
                roots.append(Root(KNOWN_LABELS[key], path.resolve(), "folder"))
        for folder in self._project_folders():
            path = Path(folder)
            if path.is_dir():
                roots.append(Root(path.name or str(path), path.resolve(), "projects"))
        return roots

    def private_dirs(self) -> frozenset[str]:
        """Normcased folders a search must never enter."""
        return frozenset(os.path.normcase(str(p)) for p in self._private)

    def project_roots(self) -> list[Path]:
        return [r.path for r in self.roots() if r.kind == "projects"]

    def root_of(self, path: Path) -> Root | None:
        """The most specific allowed folder containing `path` (a project folder inside Documents wins)."""
        matches = [r for r in self.roots() if path == r.path or path.is_relative_to(r.path)]
        return max(matches, key=lambda r: len(r.path.parts)) if matches else None

    def is_root(self, path: Path) -> bool:
        return any(path == r.path for r in self.roots())

    def known(self, word: str) -> Path | None:
        """"downloads" / "tasveerein" / "Desktop" -> that folder, if it exists."""
        key = FOLDER_WORDS.get(word.strip().lower())
        if key is None:
            return None
        path = self._known(key)
        return path.resolve() if path.is_dir() else None

    def display(self, path: Path) -> str:
        """Short, readable location: "Desktop\\notes.txt" rather than the full profile path."""
        root = self.root_of(path)
        if root is None:
            return str(path)
        rel = path.relative_to(root.path)
        return root.name if not rel.parts else f"{root.name}\\{rel}"

    # ------------------------------------------------------------------ checks

    def check(self, path: Path | str, *, write: bool = False, must_exist: bool = True) -> Path:
        """Resolve and check a path; raises ScopeError with a Roman Urdu reason."""
        raw = Path(path)
        if not raw.is_absolute():
            raise ScopeError(f"\"{raw}\" poora path nahi hai.")
        resolved = raw.resolve()
        for private in self._private:
            if resolved == private or resolved.is_relative_to(private):
                raise ScopeError("Ye NOVA ka apna data folder hai — NOVA isay na parhta hai na badalta hai.")
        root = self.root_of(resolved)
        if root is None:
            raise ScopeError(f"\"{raw}\" NOVA ki ijazat wale folders se bahar hai (Desktop, Documents, Downloads, "
                             "Pictures, Music, Videos aur project folders).")
        if SECRET_FILE.search(resolved.name):
            raise ScopeError(f"\"{resolved.name}\" mein passwords/keys hoti hain — NOVA isay na kholta hai na badalta hai.")
        if must_exist and not resolved.exists():
            raise ScopeError(f"\"{raw.name}\" nahi mila.")
        if write:
            if ".git" in resolved.relative_to(root.path).parts:
                raise ScopeError(".git folder ke andar NOVA kuch nahi badalta (project ki history kharab ho sakti hai).")
            for protected in self._protected:
                if resolved == protected or resolved.is_relative_to(protected):
                    raise ScopeError("Ye NOVA ki apni files hain — NOVA khud ko nahi badalta.")
        return resolved

    def check_new(self, parent: Path, name: str) -> Path:
        """Where a new file/folder named `name` would go inside `parent`; it must not exist yet."""
        folder = self.check(parent, write=True)
        if not folder.is_dir():
            raise ScopeError(f"\"{folder.name}\" folder nahi hai.")
        target = folder / validate_name(name)
        self.check(target, write=True, must_exist=False)
        if target.exists():
            raise ScopeError(f"\"{target.name}\" pehle se mojood hai ({self.display(folder)}).")
        return target

    def check_movable(self, path: Path) -> Path:
        """A file/folder that may be renamed, moved or deleted (never an allowed root itself)."""
        resolved = self.check(path, write=True)
        if self.is_root(resolved):
            raise ScopeError(f"\"{resolved.name}\" NOVA ke bunyadi folders mein se hai — isay hataya ya badla nahi ja sakta.")
        if resolved.parent == resolved:
            raise ScopeError("Drive ko hataya ya badla nahi ja sakta.")
        return resolved
