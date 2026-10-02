"""First render spike on Kober's own kitchen photo (catalogue page 7).

Surfaces are marked by hand here; in the prototype SAM 3 proposes them and the user
nudges the corners. Run from the repo root:

    python samples/spike_kober_p7.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from renderer.composite import Surface, assert_outside_unchanged, composite_surface, mask_polygon  # noqa: E402
from renderer.texture import finish_texture  # noqa: E402

PHOTO = ROOT / "samples/kober_photos/p7_0_1920x1200.jpg"
OUT = ROOT / "samples/out"
FINISHES = {f["id"]: f for f in json.loads((ROOT / "catalog/kober/data/finishes.json").read_text())}

# Objects in front of the countertop and backsplash that must stay as photographed.
PLANT = [(1435, 612), (1642, 612), (1642, 772), (1435, 772)]
POT = [(1465, 766), (1602, 766), (1597, 822), (1589, 868), (1561, 879), (1505, 879), (1479, 868), (1470, 822)]
BOTTLES = [(462, 598), (547, 598), (547, 724), (462, 724)]
PAN = [(572, 645), (698, 645), (698, 742), (572, 742)]
TAP = [(270, 562), (334, 562), (334, 716), (270, 716)]
HOB = [(316, 761), (412, 718), (748, 719), (798, 769), (506, 808)]
SINK = [(40, 703), (322, 697), (334, 744), (48, 750)]

# Geometry measured on the photo (see notes): lines along the counter meet at a
# vanishing point near (-600, 607); the counter ends at x~1580 where its side face
# turns towards the wall. Physical sizes: Kober depth 645 mm (600 mm of flat top),
# Original profile edge 40 mm; the visible run length is assumed to be 3.6 m.
SURFACES = [
    Surface(
        surface_id="s_countertop", surface_class="countertop",
        quad=[(186, 667.5), (2248, 829), (1580, 985), (0, 711)], width_mm=3600, height_mm=600,
        region=[(0, 653), (1866, 799), (1866, 918), (1580, 985), (0, 711)],
        exclude_tight=[POT, HOB, SINK], exclude_loose=[PLANT, BOTTLES, PAN, TAP], max_gray=130,
        glossy=True,
    ),
    Surface(
        surface_id="s_countertop_edge", surface_class="countertop",
        quad=[(0, 711), (1580, 985), (1580, 1042), (0, 727)], width_mm=3600, height_mm=40,
        region=[(0, 711), (1580, 985), (1580, 1043), (0, 728)],
        max_gray=170, glossy=True, shading_sigma=6.0,
    ),
    Surface(
        surface_id="s_countertop_side", surface_class="countertop",
        quad=[(1580, 985), (1866, 918), (1866, 956), (1580, 1042)], width_mm=350, height_mm=40,
        region=[(1580, 985), (1866, 918), (1866, 957), (1580, 1043)],
        max_gray=170, glossy=True, shading_sigma=6.0,
    ),
    Surface(
        surface_id="s_backsplash", surface_class="backsplash",
        quad=[(295, 499), (1866, 343), (1866, 799), (295, 676)], width_mm=3000, height_mm=600,
        region=[(295, 499), (1866, 343), (1866, 799), (295, 676)],
        exclude_loose=[PLANT, BOTTLES, PAN, TAP], shading_sigma=30.0,
    ),
]

VARIANTS = {
    "a_caracatta": {"countertop": "estilo-caracatta", "backsplash": "estilo-caracatta"},
    "b_rovere_slavonia_porfido_gesso": {"countertop": "estilo-rovere-slavonia", "backsplash": "estilo-porfido-gesso"},
    "c_calcutta_marble_black_kandia": {"countertop": "diseno-calcutta-marble", "backsplash": "estilo-black-kandia"},
}

MM_PER_SWATCH_PX = 1.5  # assumption until Kober supplies full-slab images with their real size
PX_PER_MM = 0.67        # texture resolution; ~1 texture px per image px on the near end of the counter


def render_variant(photo: np.ndarray, choice: dict[str, str]) -> tuple[np.ndarray, list[dict], list[np.ndarray]]:
    out = photo.copy()
    layers, masks = [], []
    for s in SURFACES:
        finish = FINISHES[choice[s.surface_class]]
        texture = finish_texture(ROOT / "catalog/kober" / finish["swatch"], finish["id"], s.width_mm, s.height_mm,
                                 MM_PER_SWATCH_PX, PX_PER_MM, cache_dir=ROOT / ".cache/textures")
        out, mask = composite_surface(out, s, texture, exposure=0.92)
        masks.append(mask)
        layers.append({
            "surface_id": s.surface_id, "surface_class": s.surface_class, "finish_id": finish["id"],
            "finish_name": finish["name"], "polygon": mask_polygon(mask),
        })
    assert_outside_unchanged(photo, out, masks)
    return out, layers, masks


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    photo = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
    cv2.imwrite(str(OUT / "p7_before.jpg"), photo, [cv2.IMWRITE_JPEG_QUALITY, 90])
    for name, choice in VARIANTS.items():
        img, layers, masks = render_variant(photo, choice)
        cv2.imwrite(str(OUT / f"p7_{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        manifest = {"image": {"width": photo.shape[1], "height": photo.shape[0]}, "layers": layers}
        (OUT / f"p7_{name}.manifest.json").write_text(json.dumps(manifest, indent=1))
        overlay = img.copy()
        for m in masks:
            contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(overlay, contours, -1, (51, 90, 200), 2)
        cv2.imwrite(str(OUT / f"p7_{name}_hotspots.jpg"), overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print("rendered", name)


if __name__ == "__main__":
    main()
