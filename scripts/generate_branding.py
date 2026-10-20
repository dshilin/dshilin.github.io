"""Generate website branding from the supplied artwork (requires Pillow)."""

from pathlib import Path
import json

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
IMAGES = STATIC / "images"
IMAGES.mkdir(parents=True, exist_ok=True)

with Image.open(ROOT / "assets/branding/logo-source.jpg") as source:
    # Remove the original's wide empty margins without altering the artwork.
    logo = source.convert("RGB").crop((224, 220, 784, 780))

logo.save(IMAGES / "logo.png", optimize=True)
logo.save(IMAGES / "logo.webp", lossless=True, method=6)

for filename, size in {
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "favicon-48x48.png": 48,
    "apple-touch-icon.png": 180,
    "android-chrome-192x192.png": 192,
    "android-chrome-512x512.png": 512,
}.items():
    logo.resize((size, size), Image.Resampling.LANCZOS).save(
        STATIC / filename, optimize=True
    )

logo.save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

# Relative icon URLs also work when the site is hosted under a subdirectory.
manifest = {
    "name": "Рефакторинг жизни",
    "short_name": "Рефакторинг жизни",
    "lang": "ru",
    "icons": [
        {
            "src": f"android-chrome-{size}x{size}.png",
            "sizes": f"{size}x{size}",
            "type": "image/png",
            "purpose": "any",
        }
        for size in (192, 512)
    ],
    "theme_color": "#ffffff",
    "background_color": "#ffffff",
    "display": "standalone",
    "start_url": "./",
    "scope": "./",
}
(STATIC / "site.webmanifest").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
