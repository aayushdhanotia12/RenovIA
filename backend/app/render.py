"""Render a design: every countertop and backsplash surface gets its real Kober finish.

Output is the rendered image, one mask PNG per surface, and the layer manifest the
web app draws its clickable overlay from. A tap resolves to a finish id with no
inference, because we drew every product pixel ourselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from renderer.composite import V2, RenderOptions, Surface, assert_outside_unchanged, composite_surface
from renderer.texture import finish_texture

from .catalogue import Catalogue, Finish
from .geometry import centroid, mask_polygon

RENDERER_VERSION = "composite-v2"
MM_PER_SWATCH_PX = 1.5  # assumed physical scale of the PDF swatches until Kober sends full-slab scans
PX_PER_MM = 0.67        # texture resolution
CANONICAL_MM = (4200, 1200)  # one synthesized texture per finish, cropped to each surface

SURFACE_STYLE = {
    "countertop": {"glossy": True, "shading_sigma": 22.0},
    "backsplash": {"glossy": False, "shading_sigma": 30.0},
}


@dataclass
class SurfacePlan:
    surface_id: str
    surface_class: str      # countertop | backsplash
    run_id: str
    quad: list[list[int]]   # far-left, far-right, near-right, near-left
    mask: np.ndarray        # uint8, 255 = product pixels to repaint
    width_mm: int           # physical size the quad spans
    height_mm: int
    confidence: float = 1.0


# Gloss by kind of finish until Kober confirms each one (finishes.json may set "gloss").
GLOSS_BY_TAG = (("marble", 0.45), ("granite", 0.35), ("solid", 0.3), ("stone-concrete", 0.3), ("wood", 0.15))


def gloss_for(finish: Finish) -> float:
    if finish.gloss is not None:
        return finish.gloss
    if finish.line == "basik":
        return 0.12  # textured, low-sheen range
    for tag, g in GLOSS_BY_TAG:
        if tag in finish.tags:
            return g
    return 0.25


def texture_for(finish: Finish, width_mm: int, height_mm: int, cache_dir: Path) -> np.ndarray:
    cw, ch = CANONICAL_MM
    if width_mm <= cw and height_mm <= ch:
        tex = finish_texture(finish.swatch_path, finish.id, cw, ch, MM_PER_SWATCH_PX, PX_PER_MM, cache_dir)
        out_w, out_h = int(round(width_mm * PX_PER_MM)), int(round(height_mm * PX_PER_MM))
        return tex[:out_h, :out_w]
    return finish_texture(finish.swatch_path, finish.id, width_mm, height_mm, MM_PER_SWATCH_PX, PX_PER_MM, cache_dir)


def render_design(photo_bgr: np.ndarray, plans: list[SurfacePlan], countertop: Finish, splash: Finish | None,
                  cache_dir: Path, options: RenderOptions = V2) -> tuple[np.ndarray, list[dict], dict[str, np.ndarray]]:
    out = photo_bgr.copy()
    layers: list[dict] = []
    masks: dict[str, np.ndarray] = {}
    claimed = np.zeros(photo_bgr.shape[:2], bool)
    walls = [p for p in plans if p.surface_class == "backsplash"]
    # Backsplash first, countertop last, so the countertop wins where masks overlap.
    for plan in sorted(plans, key=lambda p: 0 if p.surface_class == "backsplash" else 1):
        finish = countertop if plan.surface_class == "countertop" else splash
        if finish is None:
            continue
        style = SURFACE_STYLE[plan.surface_class]
        surface = Surface(
            surface_id=plan.surface_id, surface_class=plan.surface_class, quad=[tuple(p) for p in plan.quad],
            width_mm=plan.width_mm, height_mm=plan.height_mm, region=[tuple(p) for p in plan.quad],
            glossy=style["glossy"], shading_sigma=style["shading_sigma"],
        )
        if plan.surface_class == "countertop":
            surface.gloss = gloss_for(finish)
            wall = next((w for w in walls if w.run_id == plan.run_id), walls[0] if walls else None)
            if wall is not None:
                surface.mirror_wall = ([tuple(p) for p in wall.quad], wall.width_mm, wall.height_mm)
        tex = texture_for(finish, plan.width_mm, plan.height_mm, cache_dir)
        out, mask = composite_surface(out, surface, tex, mask=plan.mask, options=options, original_bgr=photo_bgr)
        masks[plan.surface_id] = mask
        claimed |= mask > 0
        layers.append({
            "surface_id": plan.surface_id, "surface_class": plan.surface_class, "run_id": plan.run_id,
            "finish_id": finish.id, "finish_name": finish.name,
            "polygon": mask_polygon(mask), "centroid": centroid(mask),
            "area_mm2": int(plan.width_mm) * int(plan.height_mm), "confidence": round(float(plan.confidence), 3),
        })
    assert_outside_unchanged(photo_bgr, out, list(masks.values()))
    layers.sort(key=lambda layer: (layer["centroid"][1], layer["centroid"][0]))
    return out, layers, masks


def save_render(out_dir: Path, design_id: str, image: np.ndarray, masks: dict[str, np.ndarray]) -> tuple[Path, dict[str, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / f"{design_id}.jpg"
    cv2.imwrite(str(image_path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    mask_paths = {}
    for sid, m in masks.items():
        path = out_dir / f"{design_id}_{sid}.png"
        cv2.imwrite(str(path), m)
        mask_paths[sid] = path
    return image_path, mask_paths
