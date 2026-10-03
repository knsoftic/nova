"""Runtime configuration. Values come from environment variables with local-first defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "file://",
    "null",  # Electron file:// pages may report a null origin
)


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = PROJECT_ROOT / "data"
    assistant_name: str = "NOVA"
    ollama_url: str = "http://127.0.0.1:11434"
    discovery_on_startup: bool = True
    allowed_origins: tuple[str, ...] = field(default=DEFAULT_ALLOWED_ORIGINS)

    stt_model: str = "small"
    permission_timeout_s: float = 60.0  # no answer = "no"
    reports_dir: Path | None = None  # research reports; default Documents\NOVA\Research
    # The admin's record (Phase 11): approvals and the daily summary go into LOGS.md, test steps come from README.md.
    # None = not used (tests); the real app points them at the project root.
    logs_path: Path | None = None
    readme_path: Path | None = None
    self_test_on_startup: bool = True
    self_test_delay_s: float = 25.0  # let the system scan and the models load first
    # Installed NOVA (Phase 12): voice models ship read-only next to the program; user data lives in LocalAppData.
    models_dir_override: Path | None = None
    packaged: bool = False
    # Multi-PC (Phase 13): encrypted link to paired PCs (TCP) and the "NOVA is here" beacon (UDP), only on Private
    # networks. peer_loopback: a test mode where two NOVAs on ONE PC find each other on 127.0.0.1 (beacon_targets =
    # the other instances' beacon ports). 0 = any free port (tests).
    peer_port: int = 8770
    beacon_port: int | None = 8771
    peer_loopback: bool = False
    beacon_targets: tuple[int, ...] = ()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nova.db"

    @property
    def models_dir(self) -> Path:
        return self.models_dir_override or self.data_dir / "models"


def _path_env(name: str, default: Path | None) -> Path | None:
    """An empty value switches the path off (installed NOVA has no LOGS.md/README.md)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return Path(value) if value.strip() else None


def load_settings() -> Settings:
    extra_origins = tuple(
        o.strip() for o in os.environ.get("NOVA_EXTRA_ORIGINS", "").split(",") if o.strip()
    )
    packaged = os.environ.get("NOVA_PACKAGED", "0").lower() in ("1", "true", "yes")
    return Settings(
        # Bind to loopback only by default; the personal version must not be exposed to the network.
        host=os.environ.get("NOVA_HOST", "127.0.0.1"),
        port=int(os.environ.get("NOVA_PORT", "8765")),
        data_dir=Path(os.environ.get("NOVA_DATA_DIR", PROJECT_ROOT / "data")),
        assistant_name=os.environ.get("NOVA_ASSISTANT_NAME", "NOVA"),
        ollama_url=os.environ.get("NOVA_OLLAMA_URL", "http://127.0.0.1:11434"),
        stt_model=os.environ.get("NOVA_STT_MODEL", "small"),
        discovery_on_startup=os.environ.get("NOVA_DISCOVERY_ON_STARTUP", "1").lower() not in ("0", "false", "no"),
        allowed_origins=DEFAULT_ALLOWED_ORIGINS + extra_origins,
        # The development record lives in the repository; an installed NOVA has none unless pointed at one.
        logs_path=_path_env("NOVA_LOGS_PATH", None if packaged else PROJECT_ROOT / "LOGS.md"),
        readme_path=_path_env("NOVA_README_PATH", None if packaged else PROJECT_ROOT / "README.md"),
        self_test_on_startup=os.environ.get("NOVA_SELF_TEST", "1").lower() not in ("0", "false", "no"),
        models_dir_override=_path_env("NOVA_MODELS_DIR", None),
        packaged=packaged,
        peer_port=int(os.environ.get("NOVA_PEER_PORT", "8770")),
        beacon_port=int(os.environ.get("NOVA_BEACON_PORT", "8771")) or None,
        peer_loopback=os.environ.get("NOVA_PEER_LOOPBACK", "0").lower() in ("1", "true", "yes"),
        beacon_targets=tuple(int(p) for p in os.environ.get("NOVA_BEACON_TARGETS", "").split(",") if p.strip()),
    )
