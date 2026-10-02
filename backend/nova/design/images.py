"""Local image tools for the Design Agent (Pillow). The original is never changed: every result is a new file
(next to the original, or in Pictures\\NOVA\\Designs) and it is opened again to verify its size and format.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}
FORMATS = {"jpg": ("JPEG", ".jpg"), "jpeg": ("JPEG", ".jpg"), "png": ("PNG", ".png"), "webp": ("WEBP", ".webp"),
           "bmp": ("BMP", ".bmp"), "gif": ("GIF", ".gif"), "ico": ("ICO", ".ico"), "pdf": ("PDF", ".pdf"),
           "tif": ("TIFF", ".tif"), "tiff": ("TIFF", ".tif")}
# Common sizes people ask for by name (width, height).
PRESETS: dict[str, tuple[int, int]] = {
    "instagram post": (1080, 1080), "post": (1080, 1080), "square": (1080, 1080),
    "instagram story": (1080, 1920), "story": (1080, 1920), "whatsapp status": (1080, 1920), "status": (1080, 1920),
    "reel": (1080, 1920), "youtube thumbnail": (1280, 720), "thumbnail": (1280, 720),
    "facebook post": (1200, 630), "facebook cover": (820, 312), "linkedin banner": (1584, 396),
    "twitter header": (1500, 500), "banner": (1920, 600), "whatsapp dp": (640, 640), "dp": (640, 640),
    "profile picture": (640, 640), "poster": (1240, 1754), "flyer": (1240, 1754), "a4": (2480, 3508),
    "card": (1050, 600), "visiting card": (1050, 600), "hd": (1920, 1080), "full hd": (1920, 1080),
    "wallpaper": (1920, 1080), "4k": (3840, 2160),
}
COLORS = {
    "laal": "#e53935", "red": "#e53935", "neela": "#1e88e5", "neeli": "#1e88e5", "blue": "#1e88e5",
    "hara": "#2e7d32", "hari": "#2e7d32", "green": "#2e7d32", "peela": "#fbc02d", "peeli": "#fbc02d",
    "yellow": "#fbc02d", "kala": "#111111", "kali": "#111111", "black": "#111111", "safed": "#fafafa",
    "white": "#fafafa", "narangi": "#fb8c00", "orange": "#fb8c00", "jamni": "#7b1fa2", "purple": "#7b1fa2",
    "gulabi": "#ec407a", "pink": "#ec407a", "sunehra": "#c9a227", "sunehri": "#c9a227", "golden": "#c9a227",
    "gold": "#c9a227", "aasmani": "#29b6f6", "sky": "#29b6f6", "bhoora": "#6d4c41", "brown": "#6d4c41",
    "grey": "#616161", "gray": "#616161", "surmai": "#616161", "navy": "#1a237e", "teal": "#00897b",
    "maroon": "#7f0000",
}
PALETTES = [("#1a237e", "#7b1fa2"), ("#0d47a1", "#00897b"), ("#b71c1c", "#ff6f00"), ("#263238", "#455a64")]
URDU_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


class ImageError(Exception):
    """Roman Urdu reason."""


@dataclass
class ImageResult:
    path: Path
    size: tuple[int, int]
    format: str
    bytes: int


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        if (FONT_DIR / name).is_file():
            return ImageFont.truetype(str(FONT_DIR / name), size)
    return ImageFont.load_default(size)


def check_text(text: str) -> None:
    if URDU_SCRIPT.search(text):
        raise ImageError("Urdu script tasveer par abhi sahi nahi likhi ja sakti — Roman Urdu ya English mein likhein")


def open_image(path: Path) -> Image.Image:
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)  # phone photos: apply the camera's rotation first
        img.load()
        return img
    except (OSError, ValueError) as exc:
        raise ImageError(f"\"{path.name}\" tasveer khul nahi saki") from exc


def result_path(src: Path, suffix: str, ext: str | None = None) -> Path:
    """"photo.jpg" -> "photo-1080x1080.jpg"; never an existing file."""
    ext = ext or (src.suffix.lower() if src.suffix.lower() not in (".heic", ".tif", ".tiff") else ".jpg")
    path = src.with_name(f"{src.stem}-{suffix}{ext}")
    n = 2
    while path.exists():
        path = src.with_name(f"{src.stem}-{suffix} ({n}){ext}")
        n += 1
    return path


def _ready_for(img: Image.Image, fmt: str) -> Image.Image:
    if fmt in ("JPEG", "BMP", "PDF") and img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, "white")  # JPEG has no transparency: put it on white
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    if fmt == "GIF" and img.mode not in ("P", "L"):
        return img.convert("P", palette=Image.ADAPTIVE)
    return img


def save(img: Image.Image, path: Path, fmt: str | None = None, quality: int = 90) -> ImageResult:
    fmt = fmt or FORMATS.get(path.suffix.lower().lstrip("."), ("PNG", ".png"))[0]
    img = _ready_for(img, fmt)
    kwargs: dict = {}
    if fmt in ("JPEG", "WEBP"):
        kwargs["quality"] = quality
    if fmt == "JPEG":
        kwargs["optimize"] = True
    if fmt == "PNG":
        kwargs["optimize"] = True
    img.save(path, fmt, **kwargs)
    with Image.open(path) as check:  # verification: the file opens and has the expected size
        size, real = check.size, check.format
    if fmt != "PDF" and size != img.size:
        raise ImageError("Nayi tasveer ka size verify nahi hua")
    return ImageResult(path, size, real or fmt, path.stat().st_size)


# ------------------------------------------------------------------ operations


def fit(img: Image.Image, width: int, height: int) -> Image.Image:
    """Exact size without stretching: scale to cover, then crop the centre."""
    return ImageOps.fit(img, (width, height), Image.LANCZOS, centering=(0.5, 0.45))


def scale(img: Image.Image, percent: int) -> Image.Image:
    w, h = img.size
    factor = max(1, min(400, percent)) / 100
    return img.resize((max(1, int(w * factor)), max(1, int(h * factor))), Image.LANCZOS)


def rotate(img: Image.Image, degrees: int) -> Image.Image:
    return img.rotate(-degrees, expand=True)  # positive = clockwise, as people say it


def mirror(img: Image.Image, vertical: bool = False) -> Image.Image:
    return ImageOps.flip(img) if vertical else ImageOps.mirror(img)


def grayscale(img: Image.Image) -> Image.Image:
    return ImageOps.grayscale(img).convert("RGB")


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, bold: bool = True,
              min_size: int = 14) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, list[str]]:
    """Largest font (from `start` down) at which `text`, wrapped into lines, fits `max_width`."""
    size = start
    while True:
        f = font(size, bold)
        lines: list[str] = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split():
                trial = f"{current} {word}".strip()
                if draw.textlength(trial, font=f) <= max_width or not current:
                    current = trial
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        if all(draw.textlength(ln, font=f) <= max_width for ln in lines) or size <= min_size:
            return f, lines
        size = int(size * 0.9)


def caption(img: Image.Image, text: str) -> Image.Image:
    """A dark band at the bottom with the text in white."""
    check_text(text)
    img = img.convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    f, lines = _fit_font(draw, text, int(w * 0.9), max(18, h // 12))
    size = f.size if hasattr(f, "size") else 18
    top, bottom = draw.textbbox((0, 0), "Ag", font=f)[1::2]  # real glyph height (ascender to descender)
    glyph_h, gap, pad = bottom - top, int(size * 0.2), int(size * 0.45)
    band = glyph_h * len(lines) + gap * (len(lines) - 1) + 2 * pad
    overlay = Image.new("RGBA", (w, band), (0, 0, 0, 150))
    img.paste(overlay, (0, h - band), overlay)
    y = h - band + pad - top  # centred in the band
    for line in lines:
        draw.text(((w - draw.textlength(line, font=f)) / 2, y), line, font=f, fill="white")
        y += glyph_h + gap
    return img


def watermark(img: Image.Image, text: str) -> Image.Image:
    """Semi-transparent text in the bottom-right corner."""
    check_text(text)
    base = img.convert("RGBA")
    w, h = base.size
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    f = font(max(14, min(w, h) // 22))
    tw = draw.textlength(text, font=f)
    margin = max(10, min(w, h) // 40)
    size = f.size if hasattr(f, "size") else 14
    x, y = w - tw - margin, h - size * 1.3 - margin
    # Readable on any photo: dark text where the corner is bright, light text where it is dark.
    corner = base.convert("L").crop((int(x), int(y), w, h))
    bright = ImageStat.Stat(corner).mean[0] > 140
    ink, shadow = ((30, 30, 30, 170), (255, 255, 255, 110)) if bright else ((255, 255, 255, 175), (0, 0, 0, 110))
    draw.text((x + 2, y + 2), text, font=f, fill=shadow)
    draw.text((x, y), text, font=f, fill=ink)
    return Image.alpha_composite(base, layer).convert("RGB")


# ------------------------------------------------------------------ new designs


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _luminance(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def colors_from(words: str, seed: str = "") -> tuple[str, str]:
    found = [COLORS[w] for w in re.findall(r"[a-z]+", words.lower()) if w in COLORS]
    if len(found) >= 2:
        return found[0], found[1]
    if found:
        r, g, b = _hex(found[0])
        darker = "#%02x%02x%02x" % (int(r * 0.55), int(g * 0.55), int(b * 0.55))
        return found[0], darker
    return PALETTES[sum(map(ord, seed)) % len(PALETTES)]


def create_design(size: tuple[int, int], title: str, subtitle: str = "", colors: tuple[str, str] | None = None) -> Image.Image:
    check_text(f"{title} {subtitle}")
    w, h = size
    top, bottom = (_hex(c) for c in (colors or PALETTES[0]))
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):  # vertical gradient
        t = y / max(1, h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    # Soft decorative circles (lighter than the background) for depth.
    deco = Image.new("RGBA", size, (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(deco)
    r = int(min(w, h) * 0.45)
    ddraw.ellipse((w - r, -r // 2, w + r, r * 1.5), fill=(255, 255, 255, 28))
    ddraw.ellipse((-r // 2, h - r, r, h + r // 2), fill=(255, 255, 255, 20))
    img = Image.alpha_composite(img.convert("RGBA"), deco).convert("RGB")
    draw = ImageDraw.Draw(img)
    average = tuple((top[i] + bottom[i]) // 2 for i in range(3))
    light_background = _luminance(average) > 160
    ink = (20, 20, 20) if light_background else (255, 255, 255)
    soft = (60, 60, 60) if light_background else (232, 232, 232)  # subtitle: a little quieter than the title
    max_text_w = int(w * 0.84)
    tf, tlines = _fit_font(draw, title, max_text_w, max(28, int(min(w, h) * 0.13)))
    t_line = int((tf.size if hasattr(tf, "size") else 28) * 1.15)
    blocks_h = t_line * len(tlines)
    sf = slines = None
    s_line = 0
    if subtitle:
        sf, slines = _fit_font(draw, subtitle, max_text_w, max(18, int(min(w, h) * 0.055)), bold=False)
        s_line = int((sf.size if hasattr(sf, "size") else 18) * 1.3)
        blocks_h += s_line * len(slines) + t_line // 2
    y = (h - blocks_h) / 2
    for line in tlines:
        draw.text(((w - draw.textlength(line, font=tf)) / 2, y), line, font=tf, fill=ink)
        y += t_line
    if subtitle and sf is not None and slines:
        y += t_line // 2
        for line in slines:
            draw.text(((w - draw.textlength(line, font=sf)) / 2, y), line, font=sf, fill=soft)
            y += s_line
    # An accent line under the title block.
    accent_w = int(w * 0.12)
    draw.rectangle(((w - accent_w) / 2, y + t_line * 0.2, (w + accent_w) / 2, y + t_line * 0.2 + max(4, h // 180)),
                   fill=ink)
    return img
