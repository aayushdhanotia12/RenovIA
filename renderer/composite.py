"""Deterministic compositor: lay a real catalogue finish onto a surface in a photo.

The render is built from the finish image itself, warped onto the surface's plane at
its true physical size, with the room's own lighting kept. No generative model is
involved, so what the customer sees is the product they can buy.

Pipeline per surface (each step after 2 can be switched off with RenderOptions, so a
change can be judged before/after on the same photo):
  1. Build a texture the size of the surface in millimetres (see texture.py).
  2. Warp it through the plane homography (surface quad in the photo <-> mm rectangle),
     supersampled 2x so far-away texture doesn't shimmer. A countertop's front edge and
     visible ends are textured as their own faces, the pattern wrapping over the edge
     (faces.py, v3).
  3. Relight it with the room's lighting only: a robust, edge-preserving shading map
     that drops the old surface's own pattern, logos and specks. Light far above the
     surface's median is the old surface's shine: it is added back as light scaled by
     the new finish's gloss instead of multiplied into the new colour (v3). Faces take
     the light from the top just above them, times their orientation and profile shape.
  4. Tint it with the room's light colour, taken from the photo's near-white pixels.
  5. Glossy finishes reflect the wall behind them, perspective-correct: the wall plane
     mirrored in the counter plane, blurred and faded with distance.
  6. Contact shadows where the surface meets objects and the wall.
  7. Match the camera: add the photo's own sensor grain.
  8. Composite with an edge-aware alpha (guided filter on the photo), inside the mask only.

Pixels outside every surface mask are returned unchanged; `assert_outside_unchanged`
checks that, and the tests call it on every render.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class RenderOptions:
    clean_shading: bool = True
    light_tint: bool = True
    reflections: bool = True
    contact_shadows: bool = True
    soft_edges: bool = True
    grain: bool = True
    supersample: bool = True
    fill_specks: bool = True
    slab_faces: bool = True     # v3: countertop front edge and ends drawn as their own faces
    glare_split: bool = True    # v3: the old surface's shine is not multiplied into the new finish

    @classmethod
    def v1(cls) -> "RenderOptions":
        """The first prototype's renderer, kept for before/after comparisons."""
        return cls(False, False, False, False, False, False, False, False, False, False)

    @classmethod
    def v2(cls) -> "RenderOptions":
        """composite-v2 (29 Sep): v1 plus lighting, reflections, shadows, edges and grain."""
        return cls(slab_faces=False, glare_split=False)


V3 = RenderOptions()
V2 = RenderOptions.v2()


@dataclass
class Surface:
    """A planar surface in a photo, with its physical size.

    quad: image points for the plane's corners, in order far-left, far-right,
          near-right, near-left (countertop: back-left, back-right, front-right,
          front-left; wall: top-left, top-right, bottom-right, bottom-left).
    width_mm, height_mm: the physical size that quad spans.
    region: polygon (image coords) covering everything to repaint on this plane.
    exclude_tight: polygons of objects to keep exactly as drawn.
    exclude_loose: rough polygons around objects; pixels inside them that look like
          the surface are still repainted, so the cut-out follows the object.
    glossy: v1 only: keep the original's specular highlights.
    gloss: 0 (matte) .. 1 (mirror-like) for reflections of the wall (countertops).
    mirror_wall: quad + size of the wall standing on this surface's back edge
          (top-left, top-right, bottom-right, bottom-left; bottom edge on the counter).
          Reflections use it; without it the back edge is mirrored straight up.
    """

    surface_id: str
    surface_class: str
    quad: list[Point]
    width_mm: int
    height_mm: int
    region: list[Point]
    exclude_tight: list[list[Point]] = field(default_factory=list)
    exclude_loose: list[list[Point]] = field(default_factory=list)
    max_gray: int | None = None
    glossy: bool = False
    shading_sigma: float = 22.0
    gloss: float = 0.0
    mirror_wall: tuple[list[Point], int, int] | None = None
    glare_cap: float = 0.3  # v3: light above 1 + cap (relative to the surface median) counts as the old shine
    focal_px: float | None = None  # the camera's focal length when the photo's EXIF gave a trustworthy one


def srgb_to_linear(img_u8: np.ndarray) -> np.ndarray:
    x = img_u8.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    y = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return np.clip(np.round(y * 255.0), 0, 255).astype(np.uint8)


def plane_homography(quad: list[Point], tex_w: float, tex_h: float) -> np.ndarray:
    """Homography from texture pixels (or mm) to image pixels."""
    src = np.float32([[0, 0], [tex_w, 0], [tex_w, tex_h], [0, tex_h]])
    return cv2.getPerspectiveTransform(src, np.float32(quad))


def _fill(shape: tuple[int, int], polys: list[list[Point]]) -> np.ndarray:
    m = np.zeros(shape, np.uint8)
    for poly in polys:
        if len(poly) >= 3:
            cv2.fillPoly(m, [np.int32(np.round(poly))], 255)
    return m


def _scale(shape: tuple[int, int]) -> float:
    """Pixel sizes below are tuned on a 1920 px wide photo."""
    return max(shape) / 1920.0


def surface_mask(photo_bgr: np.ndarray, surface: Surface) -> np.ndarray:
    shape = photo_bgr.shape[:2]
    base = _fill(shape, [surface.region])
    if surface.max_gray is not None:
        gray = cv2.cvtColor(photo_bgr, cv2.COLOR_BGR2GRAY)
        base[gray > surface.max_gray] = 0
    base[_fill(shape, surface.exclude_tight) > 0] = 0
    if not surface.exclude_loose:
        return base

    # Rough polygons around objects: repaint the pixels inside them that match the
    # surface right around that object (a local reference copes with light pools).
    certain = (base > 0) & (_fill(shape, surface.exclude_loose) == 0)
    lab = cv2.cvtColor(cv2.GaussianBlur(photo_bgr, (0, 0), 1.2), cv2.COLOR_BGR2LAB).astype(np.float32)
    objects = np.zeros(shape, np.uint8)
    for poly in surface.exclude_loose:
        inside = _fill(shape, [poly]) > 0
        ring = (cv2.dilate(inside.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0) & ~inside & certain
        if not np.any(ring):
            objects[inside & (base > 0)] = 255
            continue
        ref = np.median(lab[ring], axis=0)
        d_ring = lab[ring] - ref
        spread = np.median(np.sqrt((0.5 * d_ring[:, 0]) ** 2 + d_ring[:, 1] ** 2 + d_ring[:, 2] ** 2))
        d = lab - ref
        dist = np.sqrt((0.5 * d[..., 0]) ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)
        candidate = inside & (base > 0)
        objects[candidate & (dist >= max(8.0, 3.0 * spread))] = 255
    objects = cv2.morphologyEx(objects, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    objects = cv2.erode(objects, np.ones((3, 3), np.uint8))  # repaint the mixed edge pixels, no halo
    mask = base.copy()
    mask[objects > 0] = 0
    return mask


def fill_specks(mask: np.ndarray, max_fraction: float = 0.0004) -> np.ndarray:
    """Repaint small holes inside a surface: printed logos, crumbs, reflections the mask
    skipped. Anything bigger (a bottle, the hob, a plant pot) stays as photographed."""
    inv = (mask == 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    h, w = mask.shape
    out = mask.copy()
    limit = max_fraction * h * w
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches_border = x == 0 or y == 0 or x + bw >= w or y + bh >= h
        if area <= limit and not touches_border:
            ring = cv2.dilate((labels == i).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            ring &= labels != i
            if np.all(mask[ring] > 0):  # fully enclosed by the surface
                out[labels == i] = 255
    return out


# --- 3. lighting -------------------------------------------------------------------

def _luminance(lin: np.ndarray) -> np.ndarray:
    return (0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]).astype(np.float32)


def shading_and_highlights(lin: np.ndarray, mask: np.ndarray, sigma: float,
                           glossy: bool) -> tuple[np.ndarray, np.ndarray]:
    """v1: relative shading from a Gaussian blur, plus the old surface's specular residual."""
    lum = _luminance(lin)
    m = (mask > 0).astype(np.float32)
    smooth = cv2.GaussianBlur(lum * m, (0, 0), sigma) / (cv2.GaussianBlur(m, (0, 0), sigma) + 1e-6)
    inside = mask > 0
    ref = float(np.median(smooth[inside])) if np.any(inside) else 1.0
    shading = np.clip(smooth / max(ref, 1e-6), 0.55, 1.8).astype(np.float32)
    if not glossy or not np.any(inside):
        return shading, np.zeros_like(shading)
    fine = cv2.GaussianBlur(lum * m, (0, 0), 1.5) / (cv2.GaussianBlur(m, (0, 0), 1.5) + 1e-6)
    residual = np.clip(fine - smooth, 0, None)
    thresh = np.percentile(residual[inside], 99.5)
    highlights = np.where(residual > thresh, residual, 0.0).astype(np.float32)
    return shading, highlights


def clean_shading(lin: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    """The room's light on this surface, without the old surface's own pattern.

    Works in log luminance at quarter resolution: pixels outside the mask are filled
    from their surroundings, a large median removes logos, veins and specks while
    keeping the edges of light pools, and a light blur smooths what is left.
    """
    h, w = mask.shape
    f = 4
    sw, sh = max(1, w // f), max(1, h // f)
    lum = _luminance(lin)
    loglum = np.log(lum + 1e-3)
    small = cv2.resize(loglum, (sw, sh), interpolation=cv2.INTER_AREA)
    m = (cv2.resize((mask > 0).astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA) > 0.5).astype(np.float32)
    if m.sum() < 4:
        return np.ones((h, w), np.float32)
    # Fill outside the mask by normalised convolution so the median sees only this surface.
    filled = small.copy()
    for s in (3.0, 10.0, 40.0):
        est = cv2.GaussianBlur(small * m, (0, 0), s) / (cv2.GaussianBlur(m, (0, 0), s) + 1e-6)
        known = cv2.GaussianBlur(m, (0, 0), s) > 1e-3
        hole = (m == 0) & (filled == small)
        filled = np.where(hole & known, est, filled)
    filled = np.where(m > 0, small, filled)
    lo, hi = float(filled.min()), float(filled.max())
    u8 = np.clip((filled - lo) / max(hi - lo, 1e-6) * 255.0, 0, 255).astype(np.uint8)
    k = int(max(5, round(15 * _scale(mask.shape)))) | 1
    med = cv2.medianBlur(cv2.medianBlur(u8, k), k).astype(np.float32) / 255.0 * (hi - lo) + lo
    med = cv2.GaussianBlur(med, (0, 0), max(1.0, sigma / (2 * f)))
    ref = float(np.median(med[m > 0]))
    shade_small = np.exp(med - ref)
    shading = cv2.resize(shade_small, (w, h), interpolation=cv2.INTER_CUBIC)
    return np.clip(shading, 0.5, 1.8).astype(np.float32)


def split_glare(shading: np.ndarray, cap: float) -> tuple[np.ndarray, np.ndarray]:
    """Split relative shading into the light a new finish receives and the old surface's shine.

    The shading map is the photo's light on the old surface relative to its median, so on a
    dark, glossy counter the lamps' reflection shows up as shading of 1.5-2.5x. Multiplied into
    a light finish that becomes a milky haze. Up to 1 + cap the light passes as it is; above it
    a soft knee bends it towards 1 + cap, and the rest is returned separately. A specular
    reflection hardly depends on the surface's colour, so the caller adds that rest back as
    light (scaled by the new finish's gloss), not as a multiplier on the new albedo.
    """
    over = np.clip(shading - 1.0, 0.0, None)
    diffuse = np.where(shading > 1.0, 1.0 + cap * np.tanh(over / max(cap, 1e-6)), shading)
    return diffuse.astype(np.float32), (shading - diffuse).astype(np.float32)


def light_tint(lin: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """Colour of the room's light, from its brightest near-neutral pixels (walls, cabinets)."""
    lum = _luminance(lin)
    mx, mn = lin.max(axis=-1), lin.min(axis=-1)
    neutral = (mx - mn) / (mx + 1e-6) < 0.25
    bright = lum > np.percentile(lum, 90)
    pick = neutral & bright & (mx < 0.98)
    if pick.sum() < 200:
        return np.ones(3, np.float32)
    rgb = lin[pick].mean(axis=0)
    tint = rgb / (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] + 1e-6)
    tint = np.clip(tint, 0.85, 1.15)
    return (1.0 + strength * (tint - 1.0)).astype(np.float32)


# --- 5. reflections --------------------------------------------------------------

def _wall_mirror(surface: Surface) -> np.ndarray | None:
    """Image-to-image homography: a counter pixel -> the wall point it reflects.

    A vertical wall reflected in the horizontal counter is the same plane with height
    negated, so a counter pixel, read as a point on the extended wall plane, sits at
    wall height -z; its reflection shows wall height +z.
    """
    if surface.mirror_wall is not None:
        quad, wmm, hmm = surface.mirror_wall
        H = plane_homography(quad, wmm, hmm)
        flip = np.array([[1, 0, 0], [0, -1, 2 * hmm], [0, 0, 1]], np.float64)
        return H @ flip @ np.linalg.inv(H)
    # No wall known: mirror about the counter's back edge, straight up in the image.
    (x0, y0), (x1, y1) = surface.quad[0], surface.quad[1]
    if abs(x1 - x0) < 1e-6:
        return None
    a = (y1 - y0) / (x1 - x0)
    b = y0 - a * x0
    # y' = 2*(a x + b) - y  (vertical mirror about the line y = a x + b)
    return np.array([[1, 0, 0], [2 * a, -1, 2 * b], [0, 0, 1]], np.float64)


def view_cosine(surface: Surface, shape: tuple[int, int]) -> np.ndarray:
    """cos(angle between the view ray and the surface normal) per pixel.

    The focal length comes from the photo's EXIF when it was trustworthy (backend/app/
    camera.py); otherwise it is recovered from the plane homography (square pixels,
    principal point at the centre: the plane's two axes must map to perpendicular
    directions), and when that fails a typical phone focal length is assumed.
    """
    h, w = shape
    H = plane_homography(surface.quad, surface.width_mm, surface.height_mm)
    C = np.array([[1, 0, -w / 2], [0, 1, -h / 2], [0, 0, 1]], np.float64)
    G = C @ H
    h1, h2 = G[:, 0], G[:, 1]
    f2 = None
    den = h1[2] * h2[2]
    if abs(den) > 1e-12:
        v = -(h1[0] * h2[0] + h1[1] * h2[1]) / den
        if v > 0:
            f2 = v
    if surface.focal_px:
        f2 = float(surface.focal_px) ** 2
    if f2 is None or not (0.3 * max(w, h)) ** 2 < f2 < (4.0 * max(w, h)) ** 2:
        f2 = (1.1 * max(w, h)) ** 2
    Kinv = np.diag([1 / np.sqrt(f2), 1 / np.sqrt(f2), 1.0])
    r1, r2 = Kinv @ h1, Kinv @ h2
    n = np.cross(r1, r2)
    n /= np.linalg.norm(n) + 1e-12
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    dx, dy, dz = (xs - w / 2) / np.sqrt(f2), (ys - h / 2) / np.sqrt(f2), np.ones_like(xs)
    cos = np.abs(n[0] * dx + n[1] * dy + n[2] * dz) / np.sqrt(dx * dx + dy * dy + 1.0)
    return np.clip(cos, 0.0, 1.0).astype(np.float32)


def reflection(src_lin: np.ndarray, surface: Surface, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(reflected image, strength 0..1) in linear light, for a glossy horizontal surface."""
    h, w = mask.shape
    M = _wall_mirror(surface)
    if M is None or surface.gloss <= 0:
        return np.zeros_like(src_lin), np.zeros((h, w), np.float32)
    sharp = cv2.warpPerspective(src_lin, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_REPLICATE)
    rough = 1.0 - surface.gloss
    s = _scale(mask.shape)
    near = cv2.GaussianBlur(sharp, (0, 0), (0.8 + 3.0 * rough) * s)
    far = cv2.GaussianBlur(sharp, (0, 0), (4.0 + 14.0 * rough) * s)

    # How far below the counter line each pixel reads, in mm on the wall plane: the
    # reflection blurs and fades with that distance.
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    if surface.mirror_wall is not None:
        quad, wmm, hmm = surface.mirror_wall
        Hinv = np.linalg.inv(plane_homography(quad, wmm, hmm))
        den = Hinv[2, 0] * xs + Hinv[2, 1] * ys + Hinv[2, 2]
        v = (Hinv[1, 0] * xs + Hinv[1, 1] * ys + Hinv[1, 2]) / np.where(np.abs(den) < 1e-9, 1e-9, den)
        depth_mm = np.clip(v - hmm, 0, None)
    else:
        (x0, y0), (x1, y1) = surface.quad[0], surface.quad[1]
        a = (y1 - y0) / (x1 - x0)
        depth_mm = np.clip(ys - (a * xs + y0 - a * x0), 0, None) * (surface.height_mm / max(1.0, h * 0.2))
    t = np.clip(depth_mm / 700.0, 0, 1)[..., None]
    img = near * (1 - t) + far * t
    fade = np.exp(-depth_mm / (250.0 + 450.0 * surface.gloss))
    # Schlick's Fresnel: little reflection looking down on the top, a lot at a glancing angle.
    fresnel = 0.04 + 0.96 * (1.0 - view_cosine(surface, mask.shape)) ** 5
    strength = (0.6 * surface.gloss * fresnel * (0.25 + 0.75 * fade)).astype(np.float32)
    strength[mask == 0] = 0
    return img.astype(np.float32), strength


# --- 6. contact shadows ---------------------------------------------------------

def contact_occlusion(surface: Surface, mask: np.ndarray) -> np.ndarray:
    """Darkening where the surface meets things standing on it and the wall behind it."""
    shape = mask.shape
    s = _scale(shape)
    region = _fill(shape, [surface.quad]) > 0
    inside = mask > 0
    blockers = region & ~inside                        # objects, hob, sink inside the outline
    blockers = cv2.morphologyEx(blockers.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    occ = np.ones(shape, np.float32)
    if blockers.any():
        d = cv2.distanceTransform((~blockers).astype(np.uint8), cv2.DIST_L2, 5)
        occ *= 1.0 - 0.28 * np.exp(-d / (3.0 * s)) - 0.12 * np.exp(-d / (18.0 * s))
    # The back edge (countertop against the wall) or bottom edge (backsplash on the counter).
    edge = (surface.quad[0], surface.quad[1]) if surface.surface_class == "countertop" else (surface.quad[3], surface.quad[2])
    line = np.zeros(shape, np.uint8)
    cv2.line(line, tuple(int(round(v)) for v in edge[0]), tuple(int(round(v)) for v in edge[1]), 255, 1)
    d = cv2.distanceTransform((line == 0).astype(np.uint8), cv2.DIST_L2, 5)
    occ *= 1.0 - 0.18 * np.exp(-d / (5.0 * s)) - 0.06 * np.exp(-d / (30.0 * s))
    return np.clip(occ, 0.5, 1.0).astype(np.float32)


# --- 7./8. camera match and edges -------------------------------------------------

def sensor_noise_sigma(photo_bgr: np.ndarray) -> float:
    """Immerkaer's fast noise estimate, in 8-bit levels, over the whole photo."""
    gray = cv2.cvtColor(photo_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    conv = np.abs(cv2.filter2D(gray, -1, k))
    h, w = gray.shape
    sigma = float(conv[1:-1, 1:-1].sum()) * np.sqrt(0.5 * np.pi) / (6.0 * (w - 2) * (h - 2))
    return float(np.clip(sigma, 0.0, 6.0))


def guided_filter(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """He et al.'s guided filter with a grayscale guide."""
    box = lambda x: cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1))  # noqa: E731
    mean_i, mean_p = box(guide), box(src)
    cov = box(guide * src) - mean_i * mean_p
    var = box(guide * guide) - mean_i * mean_i
    a = cov / (var + eps)
    b = mean_p - a * mean_i
    return box(a) * guide + box(b)


def edge_alpha(photo_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Alpha that follows real edges in the photo (leaves, bottle outlines), never outside the mask."""
    m = (mask > 0).astype(np.float32)
    s = _scale(mask.shape)
    guide = cv2.cvtColor(photo_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    a = guided_filter(guide, m, max(2, int(round(3 * s))), 2e-3)
    soft = cv2.GaussianBlur(m, (0, 0), 0.8)
    alpha = np.clip(np.minimum(a * 1.15, 1.0), 0, 1)
    alpha = np.where(cv2.erode(mask, np.ones((7, 7), np.uint8)) > 0, soft, np.minimum(alpha, soft))
    alpha[mask == 0] = 0.0
    return alpha.astype(np.float32)


def _warp(texture_bgr: np.ndarray, H: np.ndarray, size: tuple[int, int], mask: np.ndarray,
          supersample: bool) -> np.ndarray:
    w, h = size
    if not supersample:
        return cv2.warpPerspective(texture_bgr, H, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    ys, xs = np.nonzero(mask)
    out = np.zeros((h, w, 3), np.uint8)
    if len(xs) == 0:
        return out
    x0, y0 = max(0, xs.min() - 4), max(0, ys.min() - 4)
    x1, y1 = min(w, xs.max() + 5), min(h, ys.max() + 5)
    bw, bh = x1 - x0, y1 - y0
    S = np.array([[2, 0, -2 * x0], [0, 2, -2 * y0], [0, 0, 1]], np.float64)
    big = cv2.warpPerspective(texture_bgr, S @ H, (2 * bw, 2 * bh), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REFLECT)
    out[y0:y1, x0:x1] = cv2.resize(big, (bw, bh), interpolation=cv2.INTER_AREA)
    return out


def _remap_mip(texture_bgr: np.ndarray, map_u: np.ndarray, map_v: np.ndarray, sel: np.ndarray) -> np.ndarray:
    """Sample the texture at (map_u, map_v) for the selected pixels, from a coarser copy where the
    face squeezes many texture pixels into one image pixel (a receding edge), so it doesn't alias."""
    du = np.abs(np.gradient(map_u, axis=1)) + np.abs(np.gradient(map_v, axis=1))
    out = np.zeros(map_u.shape + (3,), np.uint8)
    level_tex, scale = texture_bgr, 1.0
    for level in range(4):
        lo, hi = (0.0 if level == 0 else 2.0 ** level), (2.0 ** (level + 1) if level < 3 else np.inf)
        pick = sel & (du >= lo) & (du < hi)
        if pick.any():
            s = cv2.remap(level_tex, (map_u * scale).astype(np.float32), (map_v * scale).astype(np.float32),
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            out[pick] = s[pick]
        level_tex, scale = cv2.pyrDown(level_tex), scale / 2.0
    return out


def composite_surface(photo_bgr: np.ndarray, surface: Surface, texture_bgr: np.ndarray,
                      exposure: float = 0.92, mask: np.ndarray | None = None,
                      options: RenderOptions = V3, original_bgr: np.ndarray | None = None,
                      tex_px_per_mm: float | None = None, tex_origin_mm: tuple[float, float] = (0.0, 0.0),
                      faces=None) -> tuple[np.ndarray, np.ndarray]:
    """Return (new photo, mask) with one surface replaced by the finish texture.

    `photo_bgr` is the image so far (earlier surfaces already replaced: reflections
    show them). `original_bgr` is the untouched photo, which lighting, noise and edges
    are measured on; it defaults to `photo_bgr`.
    `texture_bgr` covers the surface's width_mm x height_mm at a uniform scale; with
    `tex_px_per_mm` it may be larger, its pixel (0, 0) sitting at `tex_origin_mm` before
    the surface's corner (room for the countertop's faces to continue the pattern).
    `mask`, when given (e.g. from SAM 3 or a user outline), replaces the polygon region.
    `faces` (renderer.faces.FaceMap) marks the countertop's front and end faces; they are
    textured and lit as faces, and any predicted band is added to the returned mask.
    """
    original = photo_bgr if original_bgr is None else original_bgr
    h, w = photo_bgr.shape[:2]
    if mask is None:
        mask = surface_mask(original, surface)
    else:
        mask = np.where(mask > 0, 255, 0).astype(np.uint8)
    if options.fill_specks:
        mask = fill_specks(mask)
    if faces is not None and not options.slab_faces:
        faces = None
    face = faces.mask > 0 if faces is not None else np.zeros((h, w), bool)
    if faces is not None:
        mask = np.where(face, 255, mask).astype(np.uint8)
    top_mask = np.where(face, 0, mask).astype(np.uint8)

    tex_h, tex_w = texture_bgr.shape[:2]
    if tex_px_per_mm is None:
        H = plane_homography(surface.quad, tex_w, tex_h)
    else:
        ox, oy = tex_origin_mm
        A = np.array([[1.0 / tex_px_per_mm, 0, -ox], [0, 1.0 / tex_px_per_mm, -oy], [0, 0, 1]], np.float64)
        H = plane_homography(surface.quad, surface.width_mm, surface.height_mm).astype(np.float64) @ A
    warped = _warp(texture_bgr, H, (w, h), mask, options.supersample)
    if faces is not None and face.any():
        face_tex = _remap_mip(texture_bgr, faces.map_u, faces.map_v, face)
        warped[face] = face_tex[face]

    lin_orig = srgb_to_linear(original[..., ::-1])
    albedo = srgb_to_linear(warped[..., ::-1])
    glare = None
    if options.clean_shading:
        shading = clean_shading(lin_orig, top_mask, surface.shading_sigma)
        highlights = np.zeros_like(shading)
        if options.glare_split:
            shading, excess = split_glare(shading, surface.glare_cap)
            inside = top_mask > 0
            old_level = float(np.median(_luminance(lin_orig)[inside])) if np.any(inside) else 0.0
            keep = min(1.0, max(0.15, surface.gloss / 0.45)) if surface.surface_class == "countertop" else 0.25
            glare = excess * old_level * keep
    else:
        shading, highlights = shading_and_highlights(lin_orig, top_mask, surface.shading_sigma, surface.glossy)
    if options.contact_shadows:
        shading = shading * contact_occlusion(surface, top_mask)
    if faces is not None and face.any():
        light = cv2.remap(shading, faces.sample_x, faces.sample_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        shading = np.where(face, light * faces.shade, shading).astype(np.float32)
        if glare is not None:
            glare = np.where(face, 0.0, glare)
    relit = albedo * shading[..., None] * exposure + highlights[..., None]
    if glare is not None:
        relit = relit + glare[..., None]
    if options.light_tint:
        relit = relit * light_tint(lin_orig)[None, None, :]
    if options.reflections and surface.gloss > 0:
        refl, k = reflection(srgb_to_linear(photo_bgr[..., ::-1]), surface, top_mask)
        relit = relit * (1 - k[..., None]) + refl * k[..., None]
    over = np.clip(relit - 0.8, 0.0, None)
    relit = np.where(relit > 0.8, 0.8 + over / (1.0 + 2.5 * over), relit)  # soft shoulder keeps white finishes textured
    relit_bgr = linear_to_srgb(relit)[..., ::-1].astype(np.float32)

    if options.grain:
        sigma = sensor_noise_sigma(original)
        if sigma > 0.2:
            rng = np.random.default_rng(zlib.crc32(surface.surface_id.encode()))
            noise = rng.normal(0.0, sigma, (h, w)).astype(np.float32)
            relit_bgr = relit_bgr + noise[..., None]

    if options.soft_edges:
        alpha = edge_alpha(original, mask)
    else:
        alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 0.8)
        alpha[mask == 0] = 0.0  # feather inward only: never repaint outside the mask
    out = relit_bgr * alpha[..., None] + photo_bgr.astype(np.float32) * (1 - alpha[..., None])
    return np.clip(np.round(out), 0, 255).astype(np.uint8), mask


def assert_outside_unchanged(before: np.ndarray, after: np.ndarray, masks: list[np.ndarray]) -> None:
    """Every pixel outside the union of product masks must be byte-identical."""
    union = np.zeros(before.shape[:2], bool)
    for m in masks:
        union |= m > 0
    diff = np.any(before != after, axis=-1)
    changed_outside = int(np.count_nonzero(diff & ~union))
    if changed_outside:
        raise AssertionError(f"{changed_outside} pixels changed outside product surfaces")


def mask_polygon(mask: np.ndarray, epsilon_px: float = 2.0) -> list[list[int]]:
    """Largest outer contour of a mask, simplified, for the clickable overlay."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    c = max(contours, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, epsilon_px, True)
    return [[int(p[0][0]), int(p[0][1])] for p in c]


__all__ = ["RenderOptions", "V2", "V3", "Surface", "composite_surface", "assert_outside_unchanged", "mask_polygon",
           "replace"]
