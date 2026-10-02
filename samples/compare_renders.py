"""Before/after of renderer changes on the Kober p7 kitchen, through the app's own path.

    python samples/compare_renders.py            # v1 vs v2 for each finish pair
    python samples/compare_renders.py --steps    # add each v2 step one at a time

Writes JPEGs to samples/out/compare/.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.catalogue import get_catalogue  # noqa: E402
from backend.app.render import render_design  # noqa: E402
from backend.tests.test_render_and_models import plans_for  # noqa: E402
from renderer.composite import RenderOptions  # noqa: E402

PHOTO = ROOT / "samples/kober_photos/p7_0_1920x1200.jpg"
OUT = ROOT / "samples/out/compare"
PAIRS = {
    "caracatta": ("estilo-caracatta", "estilo-caracatta"),
    "rovere_gesso": ("estilo-rovere-slavonia", "estilo-porfido-gesso"),
    "calcutta_kandia": ("diseno-calcutta-marble", "estilo-black-kandia"),
    "nero_caracatta": ("estilo-porfido-nero", "estilo-caracatta"),
}
STEPS = ["fill_specks", "clean_shading", "light_tint", "reflections", "contact_shadows", "soft_edges", "grain", "supersample"]
CROP = (slice(560, 1040), slice(150, 1150))  # counter with hob, bottles and the plant's pot edge


def label(img: np.ndarray, text: str) -> np.ndarray:
    out = img.copy()
    cv2.rectangle(out, (0, 0), (18 + 15 * len(text), 44), (20, 20, 20), -1)
    cv2.putText(out, text, (10, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cat = get_catalogue()
    img = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
    plans = plans_for(img)
    cache = Path(tempfile.mkdtemp())
    for name, (top_id, splash_id) in PAIRS.items():
        top, splash = cat.finish(top_id), cat.finish(splash_id)
        v1, _, _ = render_design(img, plans, top, splash, cache, RenderOptions.v1())
        v2, _, _ = render_design(img, plans, top, splash, cache, RenderOptions())
        full = np.hstack([label(v1, "before"), label(v2, "after")])
        cv2.imwrite(str(OUT / f"{name}_full.jpg"), cv2.resize(full, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
        crop = np.vstack([label(v1[CROP], "before"), label(v2[CROP], "after")])
        cv2.imwrite(str(OUT / f"{name}_zoom.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if "--steps" in sys.argv:
            opts = RenderOptions.v1()
            tiles = [label(v1[CROP], "v1")]
            for step in STEPS:
                opts = replace(opts, **{step: True})
                out, _, _ = render_design(img, plans, top, splash, cache, opts)
                tiles.append(label(out[CROP], f"+ {step}"))
            grid = [np.hstack(tiles[i:i + 2]) if i + 1 < len(tiles) else np.hstack([tiles[i], np.zeros_like(tiles[i])])
                    for i in range(0, len(tiles), 2)]
            cv2.imwrite(str(OUT / f"{name}_steps.jpg"), cv2.resize(np.vstack(grid), None, fx=0.6, fy=0.6),
                        [cv2.IMWRITE_JPEG_QUALITY, 88])
        print("wrote", name)


if __name__ == "__main__":
    main()
