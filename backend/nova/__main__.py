"""Run the backend: python -m nova

    python -m nova --check   import every part NOVA needs (used by the installer build to verify its runtime)
"""

import importlib
import logging
import sys

import uvicorn

from .config import load_settings

# Native/heavy packages an installed NOVA must be able to load.
RUNTIME_MODULES = ("nova.main", "numpy", "PIL", "faster_whisper", "ctranslate2", "onnxruntime", "piper", "playwright",
                   "mss", "uiautomation", "comtypes", "pycaw", "winrt.windows.media.ocr", "winrt.windows.devices.radios",
                   "trafilatura", "pypdf", "docx", "openpyxl", "psutil", "httpx", "uvicorn", "fastapi")


def check() -> int:
    failed = []
    for name in RUNTIME_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # report every missing piece, not only the first
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    print(f"python {sys.version.split()[0]} at {sys.executable}")
    if failed:
        print("MISSING:\n  " + "\n  ".join(failed))
        return 1
    print(f"OK: {len(RUNTIME_MODULES)} modules")
    return 0


def main() -> None:
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    uvicorn.run("nova.main:app", host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
