"""Render the RetLens icon (packaging/retlens_icon.svg) to the files the program uses.

    python tools/make_icon.py

    packaging/retlens.ico    the exe's icon (16-256 px, PyInstaller)
    retlens/app/icon.png   the window / taskbar icon at run time (256 px)

Each size is rendered from the vector source (Qt's SVG renderer), not scaled down from one
bitmap, so the small sizes stay sharp.
"""

import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SVG = os.path.join(ROOT, "packaging", "retlens_icon.svg")
ICO = os.path.join(ROOT, "packaging", "retlens.ico")
PNG = os.path.join(ROOT, "retlens", "app", "icon.png")
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size: int):
    """The SVG at size x size, as a Pillow RGBA image."""
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(SVG).render(p)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(data))).convert("RGBA")


def main() -> int:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv[:1])  # noqa: F841 (QImage/QPainter want an application)
    images = {s: render(s) for s in SIZES}
    images[256].save(PNG)
    images[256].save(ICO, sizes=[(s, s) for s in SIZES], append_images=[images[s] for s in SIZES if s != 256])
    print(f"wrote {ICO} ({os.path.getsize(ICO)} bytes, {len(SIZES)} sizes) and {PNG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
