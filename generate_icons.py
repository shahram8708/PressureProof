import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


BASE_DIR = Path(__file__).resolve().parent
ICONS_DIR = BASE_DIR / "static" / "img" / "icons"
SCREENSHOTS_DIR = BASE_DIR / "static" / "img" / "screenshots"
FONTS_DIR = BASE_DIR / "static" / "fonts"

PRIMARY = "#1E1B4B"
ACCENT = "#F59E0B"
WHITE = "#FFFFFF"

ICON_SIZES = [48, 72, 96, 120, 128, 144, 152, 167, 180, 192, 256, 384, 512]


def load_font(size):
    candidates = [
        FONTS_DIR / "Inter-Bold.woff2",
        FONTS_DIR / "Inter-SemiBold.woff2",
        FONTS_DIR / "Inter-Medium.woff2",
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_icon(size):
    image = Image.new("RGBA", (size, size), PRIMARY)
    draw = ImageDraw.Draw(image)

    safe_padding = int(size * 0.1)
    center = size / 2

    if size >= 192:
        ring_radius = int(size * 0.36)
        ring_width = max(6, int(size * 0.06))
        ring_box = [
            int(center - ring_radius),
            int(center - ring_radius),
            int(center + ring_radius),
            int(center + ring_radius),
        ]
        draw.ellipse(ring_box, outline=ACCENT, width=ring_width)

    font_size = int(size * 0.42)
    font = load_font(font_size)
    text = "PP"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    text_x = center - text_width / 2
    text_y = center - text_height / 2

    text_x = max(safe_padding, text_x)
    text_y = max(safe_padding, text_y)

    draw.text((text_x, text_y), text, font=font, fill=ACCENT)
    return image


def draw_screenshot(size, label):
    width, height = size
    image = Image.new("RGBA", (width, height), PRIMARY)
    draw = ImageDraw.Draw(image)

    font_size = int(height * 0.08)
    font = load_font(font_size)
    text = "PressureProof"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    text_x = (width - text_width) / 2
    text_y = (height - text_height) / 2

    draw.text((text_x, text_y), text, font=font, fill=WHITE)

    subtitle_font = load_font(int(height * 0.03))
    subtitle_text = label
    subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=subtitle_font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    subtitle_height = subtitle_bbox[3] - subtitle_bbox[1]
    subtitle_x = (width - subtitle_width) / 2
    subtitle_y = text_y + text_height + (subtitle_height * 1.4)

    draw.text((subtitle_x, subtitle_y), subtitle_text, font=subtitle_font, fill=ACCENT)
    return image


def ensure_dirs():
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_icons():
    ensure_dirs()
    for size in ICON_SIZES:
        icon = draw_icon(size)
        icon_path = ICONS_DIR / f"icon-{size}.png"
        icon.save(icon_path, format="PNG")


def generate_screenshots():
    ensure_dirs()
    mobile = draw_screenshot((1170, 2532), "Mobile preview")
    desktop = draw_screenshot((1366, 768), "Desktop preview")
    mobile.save(SCREENSHOTS_DIR / "mobile-screenshot.png", format="PNG")
    desktop.save(SCREENSHOTS_DIR / "desktop-screenshot.png", format="PNG")


def main():
    generate_icons()
    generate_screenshots()


if __name__ == "__main__":
    main()
