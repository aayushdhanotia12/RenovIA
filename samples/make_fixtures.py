"""Build offline fixtures: surface masks and plane corners for sample photos.

In mock mode the detector returns these instead of calling SAM 3, so the whole flow
(and the tests) run without API keys. Run from the repo root:

    python samples/make_fixtures.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.ai.mock import FIXTURES, photo_key  # noqa: E402
from renderer.composite import surface_mask  # noqa: E402

spec = importlib.util.spec_from_file_location("spike", ROOT / "samples" / "spike_kober_p7.py")
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    photo = cv2.imread(str(spike.PHOTO), cv2.IMREAD_COLOR)
    h, w = photo.shape[:2]
    counter = np.zeros((h, w), np.uint8)
    splash = np.zeros((h, w), np.uint8)
    for s in spike.SURFACES:
        m = surface_mask(photo, s)
        target = counter if s.surface_class == "countertop" else splash
        target[m > 0] = 255
    splash[counter > 0] = 0
    cv2.imwrite(str(FIXTURES / "kober_p7_countertop.png"), counter)
    cv2.imwrite(str(FIXTURES / "kober_p7_backsplash.png"), splash)
    top = next(s for s in spike.SURFACES if s.surface_id == "s_countertop")
    back = next(s for s in spike.SURFACES if s.surface_class == "backsplash")
    index = {
        photo_key(photo): {
            "name": "Kober catalogue p7 kitchen", "width": w, "height": h,
            "surfaces": [
                {"surface_class": "countertop", "mask": "kober_p7_countertop.png", "score": 0.93,
                 "quad": [[round(x), round(y)] for x, y in top.quad]},
                {"surface_class": "backsplash", "mask": "kober_p7_backsplash.png", "score": 0.9,
                 "quad": [[round(x), round(y)] for x, y in back.quad]},
            ],
        }
    }
    (FIXTURES / "index.json").write_text(json.dumps(index, indent=1))
    print("fixtures written for", list(index))


if __name__ == "__main__":
    main()
