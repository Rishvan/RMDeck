"""
Writes the MSIX logo images (all scale / target-size variants) into <out>/Assets,
drawn from assets/rmdex_icon.png via ui_kit.app_logo. Used by build_msix.ps1.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402
from ui_kit import app_logo  # noqa: E402

SCALES = (100, 125, 150, 200, 400)
TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256)


def square(size, pad=0.0):
    """The logo centred on a transparent square, with `pad` (0..0.5) margin."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = max(1, round(size * (1 - 2 * pad)))
    logo = app_logo(inner)
    canvas.paste(logo, ((size - inner) // 2, (size - inner) // 2), logo)
    return canvas


def wide(w, h):
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    inner = round(h * 0.8)
    logo = app_logo(inner)
    canvas.paste(logo, ((w - inner) // 2, (h - inner) // 2), logo)
    return canvas


def main(out):
    d = os.path.join(out, "Assets")
    os.makedirs(d, exist_ok=True)

    def save(img, name):
        img.save(os.path.join(d, name))

    for s in SCALES:
        k = s / 100
        save(square(round(44 * k)), "Square44x44Logo.scale-%d.png" % s)
        save(square(round(150 * k), pad=0.12), "Square150x150Logo.scale-%d.png" % s)
        save(wide(round(310 * k), round(150 * k)), "Wide310x150Logo.scale-%d.png" % s)
        save(square(round(50 * k)), "StoreLogo.scale-%d.png" % s)
    for t in TARGET_SIZES:
        img = square(t)
        save(img, "Square44x44Logo.targetsize-%d.png" % t)
        # taskbar / Start list use the "unplated" version (no accent-colour plate)
        save(img, "Square44x44Logo.targetsize-%d_altform-unplated.png" % t)
        save(img, "Square44x44Logo.targetsize-%d_altform-lightunplated.png" % t)


if __name__ == "__main__":
    main(sys.argv[1])
