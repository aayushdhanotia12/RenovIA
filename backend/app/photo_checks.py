"""Quick checks on an uploaded photo, run before any model sees it.

A dark or blurry photo is caught here, in a second, instead of after a failed detection.
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image

MIN_BRIGHTNESS = 70     # mean L* x 2.55 on 0-255
MIN_SHARPNESS = 60.0    # variance of the Laplacian on a 1024 px copy


def check_photo(image_bgr: np.ndarray, raw: bytes) -> dict:
    h, w = image_bgr.shape[:2]
    scale = 1024 / max(h, w)
    small = cv2.resize(image_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image_bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    brightness = float(cv2.cvtColor(small, cv2.COLOR_BGR2LAB)[..., 0].mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    try:
        exif = Image.open(io.BytesIO(raw)).getexif()
        has_camera = bool(exif.get(0x010F) or exif.get(0x0110) or exif.get(0x8769))
    except Exception:
        has_camera = False
    return {
        "light": "pass" if brightness >= MIN_BRIGHTNESS else "fail",
        "sharp": "pass" if sharpness >= MIN_SHARPNESS else "fail",
        "camera_info": "pass" if has_camera else "warn",
        "brightness": round(brightness, 1), "sharpness": round(sharpness, 1),
    }
