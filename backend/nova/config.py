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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nova.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"


def load_settings() -> Settings:
    extra_origins = tuple(
        o.strip() for o in os.environ.get("NOVA_EXTRA_ORIGINS", "").split(",") if o.strip()
    )
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
    )
