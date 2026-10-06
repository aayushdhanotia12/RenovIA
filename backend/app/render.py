"""Render a design: every countertop and backsplash surface gets its real Kober finish.

Output is the rendered image, one mask PNG per surface, and the layer manifest the
web app draws its clickable overlay from. A tap resolves to a finish id with no
inference, because we drew every product pixel ourselves.

Countertops are drawn as slabs: the top, plus the front edge and any visible end at
the thickness of the chosen Kober profile (renderer/faces.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from renderer.composite import V3, RenderOptions, Surface, assert_outside_unchanged, composite_surface
from renderer.faces import countertop_faces, vertical_vanishing_point
from renderer.texture import finish_texture

from .catalogue import Catalogue, Finish
from .geometry import centroid, mask_polygon

RENDERER_VERSION = "composite-v3"
MM_PER_SWATCH_PX = 1.5  # assumed physical scale of the PDF swatches until Kober sends full-slab scans
PX_PER_MM = 0.67        # texture resolution
CANONICAL_MM = (4200, 1200)  # one synthesized texture per finish, cropped to each surface
FACE_PAD_MM = 80             # texture margin around a countertop so its faces continue the pattern

# How each profile's front edge is shaped, for the render only (price comes from the profile id).
# Assumed from the catalogue's descriptions ("Original: rounded front corners", "Original Q: square
# front edge"); a profile in products.json may set "edge_shape" to override.
EDGE_SHAPE = {"original": "rounded", "basik": "rounded"}
DEFAULT_PROFILE = {"id": "original_q", "thickness_mm": 40}

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
    detected: bool = True   # mask from the detector; False for an outline drawn by hand (mask = quad)


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


def edge_point(face_mask: np.ndarray) -> list[int]:
    """Where the edge pointer sits: on the countertop's front edge, a little right of its middle."""
    ys, xs = np.nonzero(face_mask)
    x0 = float(np.percentile(xs, 60))
    near = np.abs(xs - x0) < 4
    if not near.any():
        return centroid(face_mask)
    return [int(round(x0)), int(np.median(ys[near]))]


def edge_shape(profile: dict) -> str:
    return profile.get("edge_shape") or EDGE_SHAPE.get(profile.get("id", ""), "square")


def render_design(photo_bgr: np.ndarray, plans: list[SurfacePlan], countertop: Finish, splash: Finish | None,
                  cache_dir: Path, options: RenderOptions = V3, profile: dict | None = None,
                  focal_px: float | None = None, light: np.ndarray | None = None,
                  ) -> tuple[np.ndarray, list[dict], dict[str, np.ndarray]]:
    """`light`: the photo's diffuse shading from a lighting model, at the photo's size
    (renderer.composite.light_from_model); without it the light is estimated from the photo."""
    profile = profile or DEFAULT_PROFILE
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
            glossy=style["glossy"], shading_sigma=style["shading_sigma"], focal_px=focal_px,
        )
        faces = None
        if plan.surface_class == "countertop":
            surface.gloss = gloss_for(finish)
            wall = next((w for w in walls if w.run_id == plan.run_id), walls[0] if walls else None)
            if wall is not None:
                surface.mirror_wall = ([tuple(p) for p in wall.quad], wall.width_mm, wall.height_mm)
            pad = FACE_PAD_MM
            tex = texture_for(finish, plan.width_mm + 2 * pad, plan.height_mm + 2 * pad, cache_dir)
            if options.slab_faces:
                faces = countertop_faces(
                    photo_bgr.shape[:2], [tuple(p) for p in plan.quad], plan.width_mm, plan.height_mm, plan.mask,
                    thickness_mm=int(profile.get("thickness_mm", 40)), edge_shape=edge_shape(profile),
                    gloss=surface.gloss, tex_px_per_mm=PX_PER_MM, tex_origin_mm=(pad, pad),
                    vertical_vp=vertical_vanishing_point([tuple(p) for p in wall.quad]) if wall is not None else None,
                    predict_band=not plan.detected,
                    photo_lum=cv2.cvtColor(photo_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32))
            out, mask = composite_surface(out, surface, tex, mask=plan.mask, options=options, original_bgr=photo_bgr,
                                          tex_px_per_mm=PX_PER_MM, tex_origin_mm=(pad, pad), faces=faces,
                                          light=light)
        else:
            surface.glare_cap = 1.5  # walls: light pools under the cabinets are real light, keep them
            tex = texture_for(finish, plan.width_mm, plan.height_mm, cache_dir)
            out, mask = composite_surface(out, surface, tex, mask=plan.mask, options=options, original_bgr=photo_bgr,
                                          light=light)
        masks[plan.surface_id] = mask
        claimed |= mask > 0
        layer_faces = {}
        if faces is not None and faces.count():
            layer_faces = {"edge_polygon": mask_polygon(faces.mask), "edge_kind": faces.kind,
                           "edge_point": edge_point(faces.mask)}
        layers.append({
            "surface_id": plan.surface_id, "surface_class": plan.surface_class, "run_id": plan.run_id,
            "finish_id": finish.id, "finish_name": finish.name,
            "polygon": mask_polygon(mask), "centroid": centroid(mask),
            "area_mm2": int(plan.width_mm) * int(plan.height_mm), "confidence": round(float(plan.confidence), 3),
            **layer_faces,
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
