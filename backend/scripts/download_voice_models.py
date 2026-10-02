"""Download NOVA's offline voice models into data/models (run once per PC).

    .venv\\Scripts\\python.exe scripts\\download_voice_models.py [--whisper small] [--voices fasih aegis]

Whisper (speech-to-text):  Systran/faster-whisper-<size>   (small ~480 MB)
Piper Urdu voices (TTS):    rhasspy/piper-voices ur_PK-*    (~61 MB each)
NOVA itself never downloads anything at runtime.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "models"
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ur/ur_PK"
VOICES = {
    "fasih": "fasih/medium/ur_PK-fasih-medium",
    "aegis": "aegis_female/medium/ur_PK-aegis_female-medium",
}


def download(url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 0:
        print(f"  already there: {target.name}")
        return
    tmp = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(target)
    print(f"  downloaded {target.name} ({target.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper", default="small", choices=["tiny", "base", "small", "medium"])
    parser.add_argument("--voices", nargs="*", default=list(VOICES), choices=list(VOICES))
    args = parser.parse_args()

    piper_dir = DATA / "piper"
    piper_dir.mkdir(parents=True, exist_ok=True)
    for name in args.voices:
        print(f"Piper voice: {name}")
        for ext in (".onnx", ".onnx.json"):
            path = VOICES[name]
            download(f"{PIPER_BASE}/{path}{ext}", piper_dir / (Path(path).name + ext))

    print(f"Whisper: {args.whisper}")
    from faster_whisper import WhisperModel

    WhisperModel(args.whisper, device="cpu", compute_type="int8", download_root=str(DATA / "whisper"))
    print("  ready")


if __name__ == "__main__":
    main()
