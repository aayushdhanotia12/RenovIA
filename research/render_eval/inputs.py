"""Inputs for the render bake-off: the app's own composite of a kitchen photo with a Kober finish,
plus everything a light-transfer pass needs to keep the product exact.

    python research/render_eval/inputs.py --out research/render_eval/inputs

For each case it writes a folder with:
  photo.jpg       the customer's photo
  composite.jpg   our render today (composite-v3, the app's path)
  swatch.jpg      the countertop finish's catalogue image (a reference for the models)
  mask.png        the product pixels (countertop and backsplash, objects cut out)
  alpha.png       the render's edge blend
  albedo.npz      the product texture as laid on the photo, linear RGB (float16)
  case.json       finishes, profile, and the prompt facts (finish names, gloss)
With FAL_KEY set, the masks come from SAM 3 like the live app; otherwise from the stored fixtures.
Run by .github/workflows/render-eval.yml; the app does not import it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.app.catalogue import get_catalogue  # noqa: E402
from backend.app.geometry import fit_quad, subtract_objects  # noqa: E402
from backend.app.render import SurfacePlan, gloss_for, render_design  # noqa: E402
from backend.tests.test_render_and_models import plans_for  # noqa: E402

PHOTO = REPO / "samples/kober_photos/p7_0_1920x1200.jpg"
CASES = {  # name: countertop, backsplash, profile. Chosen to stress different things.
    "p7_black_kandia": ("estilo-black-kandia", "estilo-caracatta", "original_q"),       # dark gloss: reflections
    "p7_caracatta": ("estilo-caracatta", "estilo-caracatta", "original"),               # white veining: pattern drift
    "p7_rovere": ("estilo-rovere-slavonia", "estilo-porfido-gesso", "original_q"),      # wood grain direction
    "p7_india_white": ("estilo-india-white", None, "slim"),                              # plain light: colour shift
}


SAMPLE_OBJECTS = ["bottle", "cooking pot", "potted plant", "stove knob"]  # what Claude lists on this photo


def live_plans(img: np.ndarray) -> list[SurfacePlan] | None:
    """The app's real path with SAM 3 (tight masks); the stored fixtures' object masks are rough
    hand-drawn shapes that leave seams of the old counter around the cooktop."""
    key = os.environ.get("FAL_KEY")
    if not key:
        return None
    from backend.app.ai.fal_sam3 import FalSam3Detector
    try:
        dets = FalSam3Detector(key).detect(img, objects=SAMPLE_OBJECTS)
    except Exception as e:  # noqa: BLE001
        print("live SAM 3 failed, using the stored fixtures:", e, flush=True)
        return None
    objects = [d.mask for d in dets if d.surface_class == "object"]
    plans = []
    for cls, run, size in (("countertop", "A", (3600, 645)), ("backsplash", "S1", (3000, 600))):
        found = sorted((d for d in dets if d.surface_class == cls), key=lambda d: -int(np.count_nonzero(d.mask)))
        if not found:
            return None
        quad = found[0].quad or fit_quad(found[0].mask)
        if quad is None:
            return None
        plans.append(SurfacePlan(f"{cls}_1", cls, run, quad, subtract_objects(found[0].mask, objects), *size,
                                 found[0].score))
    return plans


def build(out: Path) -> list[str]:
    cat = get_catalogue()
    img = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
    plans = live_plans(img) or plans_for(img)
    cache = Path(tempfile.mkdtemp())
    names = []
    for name, (top_id, splash_id, profile_id) in CASES.items():
        top = cat.finish(top_id)
        splash = cat.finish(splash_id) if splash_id else None
        use = [p for p in plans if splash is not None or p.surface_class == "countertop"]
        layers: dict = {}
        render, manifest, masks = render_design(img, use, top, splash, cache, profile=cat.profile(profile_id),
                                                product_layers=layers)
        union = np.zeros(img.shape[:2], np.uint8)
        for m in masks.values():
            union = np.maximum(union, m)
        d = out / name
        d.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(d / "photo.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(d / "composite.jpg"), render, [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(d / "swatch.jpg"), cv2.imread(str(top.swatch_path), cv2.IMREAD_COLOR), [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(d / "mask.png"), union)
        cv2.imwrite(str(d / "alpha.png"), np.clip(layers["alpha"] * 255, 0, 255).astype(np.uint8))
        np.savez_compressed(d / "albedo.npz", albedo=layers["albedo"].astype(np.float16))
        profile = cat.profile(profile_id)
        (d / "case.json").write_text(json.dumps({
            "countertop": {"id": top.id, "name": top.name, "tags": list(top.tags), "gloss": gloss_for(top)},
            "backsplash": {"id": splash.id, "name": splash.name} if splash else None,
            "profile": {"id": profile_id, "name": profile["name"], "thickness_mm": profile.get("thickness_mm")},
            "placeholder_swatches": cat.placeholder_swatches,
        }, indent=1, ensure_ascii=False))
        names.append(name)
    return names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO / "research/render_eval/inputs")
    args = ap.parse_args()
    print("\n".join(build(args.out)))


if __name__ == "__main__":
    main()
