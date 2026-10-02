"""Grow a small catalogue swatch into a large, non-repeating texture.

The PDF swatches are ~250-330 px. Tiling them (even mirrored) makes marble veins
repeat in visible, kaleidoscope-like patterns along a 3.6 m countertop. Image
quilting (Efros & Freeman, 2001) stitches random patches of the swatch together
along minimum-error seams, so the result keeps the finish's look and scale without
an obvious repeat. Orientation is preserved (no rotation), so wood grain and
directional veins stay aligned.

Output is deterministic for a given (finish id, size), so renders are reproducible
and golden-image tests stay stable. Full-slab scans from Kober, when available,
replace this step entirely.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np


def _seed(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "little")


def _min_cut_vertical(err: np.ndarray) -> np.ndarray:
    """Per-row column index of the cheapest top-to-bottom seam through `err` (h x w)."""
    h, w = err.shape
    cost = err.copy()
    for y in range(1, h):
        prev = cost[y - 1]
        left = np.concatenate(([np.inf], prev[:-1]))
        right = np.concatenate((prev[1:], [np.inf]))
        cost[y] += np.minimum(np.minimum(left, prev), right)
    seam = np.empty(h, dtype=np.int32)
    seam[-1] = int(np.argmin(cost[-1]))
    for y in range(h - 2, -1, -1):
        c = seam[y + 1]
        lo, hi = max(c - 1, 0), min(c + 2, w)
        seam[y] = lo + int(np.argmin(cost[y, lo:hi]))
    return seam


def quilt(sample: np.ndarray, out_h: int, out_w: int, key: str,
          patch: int = 96, overlap: int = 24, candidates: int = 500, tolerance: float = 0.15) -> np.ndarray:
    """Synthesize an out_h x out_w texture from `sample` (uint8 HxWx3)."""
    sample_f = sample.astype(np.float32)
    sh, sw = sample.shape[:2]
    patch = min(patch, sh - 1, sw - 1)
    overlap = min(overlap, patch // 3)
    step = patch - overlap
    rows = max(1, -(-(out_h - overlap) // step))
    cols = max(1, -(-(out_w - overlap) // step))
    canvas = np.zeros((rows * step + overlap, cols * step + overlap, 3), np.float32)
    rng = np.random.default_rng(_seed(key))

    ys = rng.integers(0, sh - patch + 1, size=candidates)
    xs = rng.integers(0, sw - patch + 1, size=candidates)
    cands = np.stack([sample_f[y:y + patch, x:x + patch] for y, x in zip(ys, xs)])  # (N, p, p, 3)

    for i in range(rows):
        for j in range(cols):
            y0, x0 = i * step, j * step
            if i == 0 and j == 0:
                canvas[:patch, :patch] = cands[rng.integers(len(cands))]
                continue
            cost = np.zeros(len(cands), np.float32)
            if j > 0:
                ref = canvas[y0:y0 + patch, x0:x0 + overlap]
                cost += ((cands[:, :, :overlap] - ref) ** 2).sum(axis=(1, 2, 3))
            if i > 0:
                ref = canvas[y0:y0 + overlap, x0:x0 + patch]
                cost += ((cands[:, :overlap, :] - ref) ** 2).sum(axis=(1, 2, 3))
            best = cost.min()
            pool = np.flatnonzero(cost <= best * (1 + tolerance) + 1e-6)
            chosen = cands[rng.choice(pool)]

            keep_new = np.ones((patch, patch), bool)
            if j > 0:
                err = ((chosen[:, :overlap] - canvas[y0:y0 + patch, x0:x0 + overlap]) ** 2).sum(axis=2)
                seam = _min_cut_vertical(err)
                keep_new[:, :overlap] &= np.arange(overlap)[None, :] >= seam[:, None]
            if i > 0:
                err = ((chosen[:overlap, :] - canvas[y0:y0 + overlap, x0:x0 + patch]) ** 2).sum(axis=2)
                seam = _min_cut_vertical(err.T)
                keep_new[:overlap, :] &= (np.arange(overlap)[:, None] >= seam[None, :])
            region = canvas[y0:y0 + patch, x0:x0 + patch]
            region[keep_new] = chosen[keep_new]

    return np.clip(canvas[:out_h, :out_w], 0, 255).astype(np.uint8)


def finish_texture(swatch_path: Path, finish_id: str, width_mm: int, height_mm: int,
                   mm_per_swatch_px: float, px_per_mm: float, cache_dir: Path | None = None) -> np.ndarray:
    """Texture covering width_mm x height_mm at px_per_mm, built from the finish swatch.

    The swatch is first scaled so one texture pixel equals 1/px_per_mm mm; quilting
    then runs at that scale, so patterns keep their true physical size.
    """
    out_w, out_h = int(round(width_mm * px_per_mm)), int(round(height_mm * px_per_mm))
    cache = None
    if cache_dir is not None:
        cache = cache_dir / f"{finish_id}_{out_w}x{out_h}_{mm_per_swatch_px:g}_{px_per_mm:g}.png"
        if cache.exists():
            return cv2.imread(str(cache), cv2.IMREAD_COLOR)
    swatch = cv2.imread(str(swatch_path), cv2.IMREAD_COLOR)
    if swatch is None:
        raise FileNotFoundError(f"finish swatch missing: {swatch_path} (run catalog/kober/extract_kober.py)")
    scale = mm_per_swatch_px * px_per_mm
    sample = cv2.resize(swatch, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    if sample.std() < 1.0:  # flat colour: nothing to synthesize
        tex = np.empty((out_h, out_w, 3), np.uint8)
        tex[:] = sample[0, 0]
    else:
        tex = quilt(sample, out_h, out_w, key=f"{finish_id}:{out_w}x{out_h}")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(cache), tex)
    return tex
