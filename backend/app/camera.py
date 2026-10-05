"""The camera a photo was taken with, read from its EXIF data with the known traps checked.

The renderer needs the lens's focal length in pixels: it sets how strongly a surface
recedes, which the reflections use. A phone's EXIF usually says it, as a
35 mm-equivalent focal length, with three traps (research, Oct 2026):

- Apple writes the 35 mm-equivalent with digital zoom already included; Samsung and
  others do not, so their DigitalZoomRatio has to be applied.
- Some capture apps write nonsense (177 mm on an iPhone 8 main camera), so anything
  outside 12-120 mm is ignored.
- A cropped photo keeps the camera's EXIF but not its centre or its field of view, so a
  photo whose shape no longer matches the EXIF pixel size falls back to the default.

The default is a 26 mm-equivalent main camera. Lengths are never taken from the photo;
this only decides how the finish is drawn.
"""

from __future__ import annotations

import io
import math

from PIL import Image

DIAGONAL_35MM = 43.27  # mm, the diagonal of a 36 x 24 mm frame
DEFAULT_FOCAL_35MM = 26.0
EXIF_IFD = 0x8769
MAKE, MODEL, ORIENTATION = 0x010F, 0x0110, 0x0112
FOCAL_35MM, DIGITAL_ZOOM, PIXEL_X, PIXEL_Y, LENS_MODEL = 0xA405, 0xA404, 0xA002, 0xA003, 0xA434


def focal_px_from_35mm(focal_35mm: float, width: int, height: int) -> float:
    """35 mm-equivalent focal length to pixels, by the diagonal (true for any aspect ratio)."""
    return focal_35mm / DIAGONAL_35MM * math.hypot(width, height)


def _num(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def camera_from_exif(raw: bytes, width: int, height: int) -> dict:
    """What we know about the camera of a photo stored at width x height (after any resizing)."""
    out = {"focal_px": round(focal_px_from_35mm(DEFAULT_FOCAL_35MM, width, height)),
           "focal_35mm": DEFAULT_FOCAL_35MM, "source": "default", "lens": "main"}
    try:
        exif = Image.open(io.BytesIO(raw)).getexif()
        ifd = exif.get_ifd(EXIF_IFD)
    except Exception:
        out["reason"] = "no readable camera data"
        return out
    make = str(exif.get(MAKE) or "").strip().strip("\x00")
    model = str(exif.get(MODEL) or "").strip().strip("\x00")
    if make:
        out["make"] = make
    if model:
        out["model"] = model
    f35 = _num(ifd.get(FOCAL_35MM))
    if f35 is None:
        out["reason"] = "no 35 mm-equivalent focal length"
        return out
    zoom = _num(ifd.get(DIGITAL_ZOOM))
    if zoom and zoom > 1.05 and not make.lower().startswith("apple"):
        f35 *= zoom
    if not 12.0 <= f35 <= 120.0:
        out["reason"] = f"implausible focal length {f35:g} mm"
        return out
    px, py = _num(ifd.get(PIXEL_X)), _num(ifd.get(PIXEL_Y))
    if px and py:
        if exif.get(ORIENTATION) in (5, 6, 7, 8):  # rotated on decode: compare the turned frame
            px, py = py, px
        if abs(math.log((px / py) / (width / height))) > 0.02:
            out["reason"] = "photo was cropped"
            return out
    out.update(focal_35mm=round(f35, 1), focal_px=round(focal_px_from_35mm(f35, width, height)), source="exif",
               lens="ultra-wide" if f35 < 20 else "main" if f35 < 35 else "tele")
    lens = str(ifd.get(LENS_MODEL) or "").strip().strip("\x00")
    if lens:
        out["lens_model"] = lens[:80]
    return out
