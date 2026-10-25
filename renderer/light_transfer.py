"""Take the light from a generated photo and keep the product's own pattern.

An image model asked to "photograph" our composite returns a picture (G) whose shine,
reflections, contact shadows and edge look real, but whose countertop pattern may have
drifted from the product. Inside each product mask we rebuild the pixels from the product's
own albedo and G's light:

    pixel = product albedo x diffuse shading(G) + non-diffuse residual(G)

G is split into albedo, shading and residual by an intrinsic model (Marigold-IID-Lighting,
which our worker already runs). Outside the masks the customer's photo is kept as it is.

Hosted models redraw the whole frame and can shift or rescale it by a few pixels, so G is
first aligned to the photo on everything outside the product masks. Two numbers then decide
whether the result may be shown:
  - `alignment`: how well the warped G matches the photo outside the product masks;
  - `drift`: how far G's own albedo strayed from the product inside them (pattern
    correlation and colour difference). A model that re-imagined the stone has lit a
    different stone, so above the limit we fall back to our own render.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .composite import linear_to_srgb, srgb_to_linear

ALIGN_MIN = 0.90          # correlation outside the product masks after warping
PATTERN_MIN = 0.55        # band-pass correlation of G's albedo with the product's
COLOUR_MAX_DE = 6.0       # mean colour difference (CIE76) of G's albedo from the product's


@dataclass
class Alignment:
    warped: np.ndarray    # G warped onto the photo's pixel grid (uint8 BGR)
    homography: np.ndarray
    score: float          # zero-mean correlation with the photo outside the product masks


@dataclass
class Drift:
    pattern: float        # band-pass correlation of G's albedo with the product albedo, 1 = same pattern
    colour_de: float      # CIE76 difference of the mean colours

    def ok(self) -> bool:
        return self.pattern >= PATTERN_MIN and self.colour_de <= COLOUR_MAX_DE


def _gray(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0


def _ncc(a: np.ndarray, b: np.ndarray, sel: np.ndarray) -> float:
    if sel.sum() < 16:
        return 0.0
    x, y = a[sel].astype(np.float64), b[sel].astype(np.float64)
    x, y = x - x.mean(), y - y.mean()
    den = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / den) if den > 1e-12 else 0.0


def _warp_to(gen: np.ndarray, H: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.warpPerspective(gen, H, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def align_generated(gen_bgr: np.ndarray, photo_bgr: np.ndarray, trust: np.ndarray, max_side: int = 1024) -> Alignment:
    """Warp G onto the photo. `trust` marks pixels G should not have changed (outside the products).

    Edit models shift, rescale or slightly rotate the frame; they don't change the perspective,
    so the warp is affine, found by ECC coarse to fine on the trusted pixels (a margin around
    the products is left out, since G's edges there move with the new surface). The warp is
    kept only if it matches the photo better than no warp at all."""
    h, w = photo_bgr.shape[:2]
    gen = cv2.resize(gen_bgr, (w, h), interpolation=cv2.INTER_AREA) if gen_bgr.shape[:2] != (h, w) else gen_bgr
    ref_g, gen_g = _gray(photo_bgr), _gray(gen)
    k = max(3, int(0.03 * max(h, w)) | 1)
    sel = cv2.erode((trust > 0).astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    warp = np.array([[1, 0, 0], [0, 1, 0]], np.float32)   # photo coords -> G coords
    top = min(1.0, max_side / max(h, w))
    for s in (top / 8, top / 4, top / 2, top):
        size = (max(16, round(w * s)), max(16, round(h * s)))
        r = cv2.resize(ref_g, size, interpolation=cv2.INTER_AREA)
        g = cv2.resize(gen_g, size, interpolation=cv2.INTER_AREA)
        m = (cv2.resize(sel.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0).astype(np.uint8)
        ws = warp.copy()
        ws[:, 2] *= s
        try:
            _, ws = cv2.findTransformECC(r, g, ws, cv2.MOTION_AFFINE,
                                         (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6), m, 3)
        except cv2.error:
            continue  # this level didn't converge; the next one starts from the last good warp
        warp = ws.copy()
        warp[:, 2] /= s
    best = None
    for H in (np.vstack([warp, [0, 0, 1]]).astype(np.float64), np.eye(3)):
        warped = _warp_to(gen, H, (w, h))
        score = _ncc(_gray(warped), ref_g, trust > 0)
        if best is None or score > best.score:
            best = Alignment(warped, H, score)
    return best


def _band(lum: np.ndarray, lo: float = 1.2, hi: float = 10.0) -> np.ndarray:
    return cv2.GaussianBlur(lum, (0, 0), lo) - cv2.GaussianBlur(lum, (0, 0), hi)


def _mean_lab(lin: np.ndarray, sel: np.ndarray) -> np.ndarray:
    rgb = linear_to_srgb(lin[sel].mean(axis=0, keepdims=True)[None]).astype(np.float32) / 255.0
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2Lab)[0, 0]


def albedo_drift(gen_albedo_lin: np.ndarray, product_albedo_lin: np.ndarray, mask: np.ndarray) -> Drift:
    """How far the generated image's own albedo strayed from the product inside `mask`."""
    sel = mask > 0
    inner = cv2.erode(sel.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0  # skip the blurred rim
    lg, lp = gen_albedo_lin.mean(axis=2), product_albedo_lin.mean(axis=2)
    pattern = _ncc(_band(np.log(lg + 1e-3)), _band(np.log(lp + 1e-3)), inner if inner.any() else sel)
    de = float(np.linalg.norm(_mean_lab(gen_albedo_lin, sel) - _mean_lab(product_albedo_lin, sel)))
    return Drift(pattern, de)


def transfer_light(product_albedo_lin: np.ndarray, shading_lin: np.ndarray, residual_lin: np.ndarray,
                   mask: np.ndarray) -> np.ndarray:
    """Linear RGB inside `mask`: the product's albedo lit by G's shading, plus G's reflections."""
    out = product_albedo_lin * shading_lin + np.clip(residual_lin, 0.0, None)
    return np.where((mask > 0)[..., None], out, 0.0).astype(np.float32)


def finish_with_generated(photo_bgr: np.ndarray, product_albedo_lin: np.ndarray, alpha: np.ndarray,
                          mask: np.ndarray, aligned_gen_bgr: np.ndarray, intrinsics) -> tuple[np.ndarray, Drift]:
    """Our render's product pixels relit by an aligned generated image.

    `product_albedo_lin` is the product texture as laid on the photo (linear RGB, photo-sized),
    `alpha` the render's edge blend (0..1, zero outside the product masks), `intrinsics(bgr)`
    returns (albedo, shading, residual) as linear RGB arrays the photo's size.
    The pixels outside the product masks are the photo's own, byte for byte."""
    albedo_g, shading_g, residual_g = intrinsics(aligned_gen_bgr)
    drift = albedo_drift(albedo_g, product_albedo_lin, mask)
    lin = transfer_light(product_albedo_lin, shading_g, residual_g, mask)
    relit = linear_to_srgb(lin)[..., ::-1].astype(np.float32)
    a = np.where(mask > 0, alpha, 0.0).astype(np.float32)[..., None]
    out = relit * a + photo_bgr.astype(np.float32) * (1 - a)
    out = np.clip(np.round(out), 0, 255).astype(np.uint8)
    out[mask == 0] = photo_bgr[mask == 0]
    return out, drift


__all__ = ["Alignment", "Drift", "align_generated", "albedo_drift", "transfer_light", "finish_with_generated",
           "srgb_to_linear"]
