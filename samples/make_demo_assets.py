"""Build the landing page's live demo: one kitchen photo rendered in the four styles.

    python samples/make_demo_assets.py

Writes web/public/demo/{before,minimalista,calido,contraste,creativo}.jpg and demo.json
(finish details plus the clickable outlines, in the demo images' pixel space). The
finishes are the offline suggester's first pick per style, so the landing page shows
exactly what the style board would render for this photo.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.ai.mock import MockDetector, STYLE_SETS  # noqa: E402
from backend.app.catalogue import get_catalogue  # noqa: E402
from backend.app.render import SurfacePlan, render_design  # noqa: E402
from backend.app.styles import STYLE_IDS, STYLES  # noqa: E402

PHOTO = ROOT / "samples/kober_photos/p7_0_1920x1200.jpg"
OUT = ROOT / "web/public/demo"
WIDTH = 1600


def finish_json(f) -> dict:
    return {"id": f.id, "name": f.name, "line": f.line, "code": f.code,
            "swatch_url": f"/catalog/{f.swatch_path.relative_to(ROOT / 'catalog/kober').as_posix()}"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cat = get_catalogue()
    img = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
    scale = WIDTH / img.shape[1]
    small = lambda im: cv2.resize(im, (WIDTH, round(im.shape[0] * scale)), interpolation=cv2.INTER_AREA)  # noqa: E731
    plans = [SurfacePlan(f"{d.surface_class}_1", d.surface_class, "A" if d.surface_class == "countertop" else "S1",
                         d.quad, d.mask, 3600 if d.surface_class == "countertop" else 3000,
                         645 if d.surface_class == "countertop" else 600, d.score)
             for d in MockDetector().detect(img) if d.surface_class != "object"]
    cv2.imwrite(str(OUT / "before.jpg"), small(img), [cv2.IMWRITE_JPEG_QUALITY, 86])
    styles = []
    with tempfile.TemporaryDirectory() as cache:
        for sid in STYLE_IDS:
            top_id, profile_id, splash_id = STYLE_SETS[sid][0]
            top, splash = cat.finish(top_id), (cat.finish(splash_id) if splash_id != "none" else None)
            out, layers, _ = render_design(img, plans, top, splash, Path(cache), profile=cat.profile(profile_id))
            cv2.imwrite(str(OUT / f"{sid}.jpg"), small(out), [cv2.IMWRITE_JPEG_QUALITY, 86])
            styles.append({
                "id": sid, "name": {"es": STYLES[sid]["es"], "en": STYLES[sid]["en"]},
                "image": f"/demo/{sid}.jpg", "profile": cat.profile(profile_id)["name"],
                "countertop": finish_json(top), "backsplash": finish_json(splash) if splash else None,
                "layers": [{"surface_class": layer["surface_class"],
                            "polygon": [[round(x * scale), round(y * scale)] for x, y in layer["polygon"]],
                            "centroid": [round(v * scale) for v in layer["centroid"]]} for layer in layers],
            })
            print("rendered", sid)
    h = round(img.shape[0] * scale)
    (OUT / "demo.json").write_text(json.dumps({"width": WIDTH, "height": h, "before": "/demo/before.jpg",
                                               "styles": styles}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
