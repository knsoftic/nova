"""Draw NOVA's icons (Phase 12): the app/installer icon (.ico) and the tray icon (.png), like the avatar orb.

    .venv\\Scripts\\python.exe scripts\\make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent.parent / "desktop" / "build-resources"
CYAN = (56, 189, 248)
NIGHT = (5, 7, 13)


def orb(size: int) -> Image.Image:
    scale = 4  # draw big, shrink smooth
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((s * 0.06, s * 0.06, s * 0.94, s * 0.94), fill=(*CYAN, 150))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s * 0.05)))
    draw = ImageDraw.Draw(img)
    draw.ellipse((s * 0.1, s * 0.1, s * 0.9, s * 0.9), fill=(*NIGHT, 255))
    # soft inner light toward the top-left, kept inside the orb
    light = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(light).ellipse((s * 0.2, s * 0.18, s * 0.66, s * 0.64), fill=(*CYAN, 110))
    light = light.filter(ImageFilter.GaussianBlur(s * 0.09))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse((s * 0.1, s * 0.1, s * 0.9, s * 0.9), fill=255)
    light.putalpha(Image.composite(light.getchannel("A"), Image.new("L", (s, s), 0), mask))
    img.alpha_composite(light)
    draw = ImageDraw.Draw(img)
    draw.ellipse((s * 0.1, s * 0.1, s * 0.9, s * 0.9), outline=(*CYAN, 255), width=max(2, s // 22))
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", int(s * 0.46))
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), "N", font=font)
    draw.text(((s - (box[2] - box[0])) / 2 - box[0], (s - (box[3] - box[1])) / 2 - box[1]), "N", font=font,
              fill=(255, 255, 255, 240))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = orb(256)
    big.save(OUT / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    big.save(OUT / "icon.png")
    orb(32).save(OUT / "tray.png")
    orb(64).save(OUT / "tray@2x.png")
    print("icons ->", OUT)


if __name__ == "__main__":
    main()
