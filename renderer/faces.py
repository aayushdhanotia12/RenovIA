"""The countertop as a slab: its front edge and visible ends drawn as their own faces.

The top is drawn through the plane homography of its four corners. A real countertop
also shows a front face (the profile's 2-6 cm thickness) and, where a run ends in the
open, an end face. Drawn through the top's homography those pixels read as more flat
top, so the new countertop looked paper-thin and kept no edge.

Faces are found inside the product mask. The one exception is an outline the customer
drew by hand, which has no detected mask: there the front band is predicted below the
near edge from the profile thickness, because otherwise the old edge stays visible
under the new top. Either way the face pixels are part of the product mask that
`assert_outside_unchanged` checks.

For each face pixel we work out
  - texture coordinates: the finish wraps over the edge, as a postformed or mitred
    edge does (front: on down from the top's front edge; ends: on out past the end);
  - where on the top, just inside the edge, its light is sampled; and
  - a shading factor: a vertical face gets less of the overhead light than the top,
    and the profile's shape decides the highlight where the top turns into the face.
No camera model is needed: the band's own height in the mask gives the scale, and the
direction of "down" comes from the backsplash's vertical sides when there is one.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

Point = tuple[float, float]

FRONT_LIGHT = 0.62   # a vertical face's share of the overhead light that reaches the top
END_LIGHT = 0.55
ROUNDED_CURVE = 0.45  # fraction of the thickness over which a rounded nose turns from top to face


@dataclass
class FaceMap:
    """Per-pixel description of the countertop's front and end faces (image-sized arrays)."""

    mask: np.ndarray       # uint8, 255 on face pixels
    added: np.ndarray      # uint8, 255 on face pixels that were outside the given mask (predicted band)
    map_u: np.ndarray      # float32 texture x, in texture pixels
    map_v: np.ndarray      # float32 texture y
    sample_x: np.ndarray   # float32 image point on the top whose light the face pixel takes
    sample_y: np.ndarray
    shade: np.ndarray      # float32 multiplier on that light (face orientation and profile)
    kind: str              # "band" (found in the mask), "inward" (quad included the band) or "predicted"

    def count(self) -> int:
        return int(np.count_nonzero(self.mask))


def _homography(quad: list[Point], width_mm: float, height_mm: float) -> np.ndarray:
    src = np.float32([[0, 0], [width_mm, 0], [width_mm, height_mm], [0, height_mm]])
    return cv2.getPerspectiveTransform(src, np.float32(quad)).astype(np.float64)


def _apply(H: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    den = H[2, 0] * xs + H[2, 1] * ys + H[2, 2]
    safe = np.where(np.abs(den) < 1e-12, 1e-12, den)
    return (H[0, 0] * xs + H[0, 1] * ys + H[0, 2]) / safe, (H[1, 0] * xs + H[1, 1] * ys + H[1, 2]) / safe, den


def vertical_vanishing_point(wall_quad: list[Point] | None) -> np.ndarray | None:
    """Where the backsplash's left and right sides meet (homogeneous), i.e. the image of 'vertical'."""
    if wall_quad is None or len(wall_quad) != 4:
        return None
    p = [np.array([x, y, 1.0]) for x, y in wall_quad]
    left, right = np.cross(p[0], p[3]), np.cross(p[1], p[2])
    vp = np.cross(left, right)
    if not np.all(np.isfinite(vp)) or np.linalg.norm(vp) < 1e-12:
        return None
    return vp / np.linalg.norm(vp)


def _down(xs: np.ndarray, ys: np.ndarray, vp: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """Unit image direction of 'down' at each point."""
    if vp is None:
        return np.zeros_like(xs), np.ones_like(ys)
    if abs(vp[2]) < 1e-9:  # verticals are parallel in the image
        dx, dy = np.full_like(xs, vp[0]), np.full_like(ys, vp[1])
    else:
        dx, dy = vp[0] / vp[2] - xs, vp[1] / vp[2] - ys
    n = np.sqrt(dx * dx + dy * dy) + 1e-9
    dx, dy = dx / n, dy / n
    flip = dy < 0
    dx, dy = np.where(flip, -dx, dx), np.where(flip, -dy, dy)
    # Guard against a wild vanishing point: never further than ~25 degrees from the image vertical.
    bad = dy < 0.9
    return np.where(bad, 0.0, dx), np.where(bad, 1.0, dy)


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _line_coords(xs, ys, a: np.ndarray, b: np.ndarray, dx, dy):
    """For points p: t = how far below line a->b along 'down' (px), and the foot point on the line."""
    lx, ly = b[0] - a[0], b[1] - a[1]
    den = _cross(dx, dy, lx, ly)
    den = np.where(np.abs(den) < 1e-9, 1e-9, den)
    t = _cross(xs - a[0], ys - a[1], lx, ly) / den
    return t, xs - t * dx, ys - t * dy


def _vertical_px_per_mm(H: np.ndarray, X: np.ndarray, Y: float) -> np.ndarray:
    """Image size of 1 mm, taken as the plane's least-foreshortened direction at (X, Y), a little
    reduced because the face is seen from above."""
    e = 1.0
    out = np.empty_like(X)
    for i, x in enumerate(X):
        px, py, _ = _apply(H, np.array([x - e, x + e, x, x]), np.array([Y, Y, Y - e, Y + e]))
        J = np.array([[(px[1] - px[0]) / (2 * e), (px[3] - px[2]) / (2 * e)],
                      [(py[1] - py[0]) / (2 * e), (py[3] - py[2]) / (2 * e)]])
        out[i] = np.linalg.svd(J, compute_uv=False)[0] * 0.9
    return out


def profile_shade(x: np.ndarray, face_light: float, shape: str, gloss: float) -> np.ndarray:
    """Light on the face as a function of x = depth into the face (0 at the top edge, 1 at the bottom)."""
    x = np.clip(x, 0.0, 1.0)
    if shape == "rounded":
        r = ROUNDED_CURVE
        w = np.where(x < r, 0.5 * (1.0 + np.cos(np.pi * x / r)), 0.0)
        shade = face_light + (1.0 - face_light) * w
        shade = shade + gloss * 0.55 * np.exp(-((x - 0.12 * r / 0.45) / 0.07) ** 2)
        bottom = 0.25
    else:  # square edge: a crisp arris catches the light, the face below is flat
        shade = np.where(x < 0.05, 1.0 + 0.3 * gloss, face_light)
        bottom = 0.15
    return (shade * (1.0 - bottom * np.clip((x - 0.88) / 0.12, 0.0, 1.0))).astype(np.float32)


def snap_band(gray: np.ndarray, a: np.ndarray, b: np.ndarray, vp: np.ndarray | None, pred: np.ndarray,
              direction: float = 1.0, samples: int = 64, found: list | None = None) -> np.ndarray:
    """Band height (px) along the edge a->b, snapped to the photo.

    The old countertop's edge has its own colour, and it ends where the cabinet or rail below
    begins. Along each of `samples` lines going `direction` x 'down' from the edge, the band's
    colour is read just past the edge, and the band ends at the first point beyond half the
    predicted height where the brightness clearly and lastingly leaves that colour. Where no
    such point exists (an edge the same colour as what is below) the prediction stays. `pred`
    holds the predicted height at the same samples. Returns heights at the samples (a to b);
    the share of samples where the photo showed the band's end is appended to `found`.
    """
    h, w = gray.shape
    s = (np.arange(samples) + 0.5) / samples
    px, py = a[0] + s * (b[0] - a[0]), a[1] + s * (b[1] - a[1])
    dx, dy = _down(px, py, vp)
    out = np.full(samples, np.nan)
    valid = np.zeros(samples, bool)
    smooth = cv2.GaussianBlur(gray, (0, 0), 1.0)
    for i in range(samples):
        p = float(pred[i])
        if p < 3:
            continue
        ts = np.arange(0.0, 2.0 * p + 3, 0.5)
        xs, ys = px[i] + direction * ts * dx[i], py[i] + direction * ts * dy[i]
        ok = (xs >= 0) & (xs < w - 1) & (ys >= 0) & (ys < h - 1)
        if ok.sum() < len(ts) * 0.8:
            continue
        valid[i] = True
        vals = cv2.remap(smooth, xs.astype(np.float32)[None, :], ys.astype(np.float32)[None, :],
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]
        ref = float(np.median(vals[(ts >= 0.15 * p) & (ts <= 0.45 * p)]))
        win = (ts >= 0.55 * p) & (ts <= 1.8 * p)
        if not win.any():
            continue
        span = float(vals[win].max() - vals[win].min())
        thr = max(18.0, 0.35 * span)
        away = np.abs(vals - ref) > thr
        for j in np.flatnonzero(win):
            if away[j:j + 4].all():
                out[i] = ts[j]
                break
    good = np.isfinite(out)
    if found is not None:  # share of the samples inside the photo where the band's end showed
        found.append(float(good.sum() / max(valid.sum(), 1)) if valid.sum() >= 4 else 0.0)
    if good.sum() < max(4, samples // 4):
        return pred.astype(np.float64)
    idx = np.arange(samples)
    out = np.interp(idx, idx[good], out[good])
    k = 9
    padded = np.pad(out, k // 2, mode="edge")
    out = np.array([np.median(padded[i:i + k]) for i in range(samples)])
    # The band's height changes smoothly with perspective: fit a straight line to the ratio.
    ratio = out / np.maximum(pred, 1e-6)
    fit = np.polyval(np.polyfit(idx, ratio, 1), idx)
    return np.clip(fit, 0.6, 1.8) * pred


def q_near_point(quad: list[Point], s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Points at fractions s along the near edge, front-left (quad[3]) to front-right (quad[2])."""
    (ax, ay), (bx, by) = quad[3], quad[2]
    return ax + s * (bx - ax), ay + s * (by - ay)


def Hinv_of(H: np.ndarray) -> np.ndarray:
    return np.linalg.inv(H)


def _band_profile(s: np.ndarray, t: np.ndarray, bins: int = 160) -> np.ndarray:
    """Band height (px) as a function of position s along the edge, from the pixels found below it."""
    idx = np.clip(((s + 0.1) / 1.2 * bins).astype(int), 0, bins - 1)
    height = np.full(bins, np.nan)
    for b in np.unique(idx):
        vals = t[idx == b]
        if len(vals) >= 3:
            height[b] = np.percentile(vals, 95)
    ok = np.isfinite(height)
    if ok.sum() < 3:
        return np.full(bins, np.nan)
    xs = np.arange(bins)
    height = np.interp(xs, xs[ok], height[ok])
    k = 7
    padded = np.pad(height, k // 2, mode="edge")
    return np.array([np.median(padded[i:i + k]) for i in range(bins)])


def _band_lookup(profile: np.ndarray, s: np.ndarray) -> np.ndarray:
    bins = len(profile)
    pos = np.clip((s + 0.1) / 1.2 * bins - 0.5, 0, bins - 1)
    return np.interp(pos, np.arange(bins), profile)


def countertop_faces(shape: tuple[int, int], quad: list[Point], width_mm: int, height_mm: int, mask: np.ndarray,
                     thickness_mm: int, edge_shape: str = "square", gloss: float = 0.3,
                     tex_px_per_mm: float = 1.0, tex_origin_mm: tuple[float, float] = (0.0, 0.0),
                     vertical_vp: np.ndarray | None = None, predict_band: bool = False,
                     photo_lum: np.ndarray | None = None) -> FaceMap | None:
    """Find the front and end faces of a countertop whose top is `quad` (back-left, back-right,
    front-right, front-left) spanning width_mm x height_mm. Returns None when there is no face."""
    h, w = shape
    L, D, T = float(width_mm), float(height_mm), float(max(thickness_mm, 1))
    H = _homography(quad, L, D)
    Hinv = np.linalg.inv(H)
    q = [np.array(p, np.float64) for p in quad]

    # Predicted band height (px) at evenly spaced points along the front edge in the image, used
    # when the mask has no band of its own: from the top's scale, then snapped to the photo.
    s_samples = (np.arange(64) + 0.5) / 64
    ex_s, ey_s = q_near_point(quad, s_samples)
    pred_px = _vertical_px_per_mm(H, _apply(Hinv_of(H), ex_s, ey_s)[0], D) * T

    # Work in the bounding box of the mask plus room below the near edge for a predicted band.
    m = mask > 0
    ys_m, xs_m = np.nonzero(m)
    if len(xs_m) == 0:
        return None
    pad = int(np.ceil(pred_px.max() * 2.6)) + 4
    x0, x1 = max(0, int(xs_m.min()) - pad), min(w, int(xs_m.max()) + pad + 1)
    y0, y1 = max(0, int(ys_m.min()) - pad), min(h, int(ys_m.max()) + pad + 1)
    gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float64)
    gx += 0.5
    gy += 0.5
    inside = m[y0:y1, x0:x1]
    dx, dy = _down(gx, gy, vertical_vp)

    # Distance below the front edge (q3 -> q2) along 'down', and the edge point above each pixel.
    t_front, ex, ey = _line_coords(gx, gy, q[3], q[2], dx, dy)
    lx, ly = q[2] - q[3]
    s_front = ((ex - q[3][0]) * lx + (ey - q[3][1]) * ly) / (lx * lx + ly * ly)

    face = np.zeros_like(inside)
    depth = np.zeros_like(gx)          # x in [0, 1]: how far down the face
    u_mm = np.zeros_like(gx)
    v_mm = np.zeros_like(gx)
    smp_x = np.zeros_like(gx)
    smp_y = np.zeros_like(gy)
    light = np.zeros_like(gx)

    along = (s_front > -0.05) & (s_front < 1.05)
    below = inside & along & (t_front > 0.75)
    pred = np.interp(np.clip(s_front, 0, 1), s_samples, pred_px)
    band_px = None
    prof = None
    kind = "band"
    if below.sum() >= 0.25 * float(np.mean(pred_px)) * np.hypot(lx, ly):
        prof = _band_profile(s_front[below], t_front[below])
        if np.all(np.isfinite(prof)):
            band_px = np.maximum(_band_lookup(prof, s_front), 2.0)
            sel = below & (t_front <= band_px * 1.15 + 2)
            frac = np.clip(t_front / band_px, 0.0, 1.0)
        else:
            prof = None
    if band_px is None:
        if predict_band:
            kind = "predicted"
            if photo_lum is not None:
                pred = np.interp(np.clip(s_front, 0, 1), s_samples,
                                 snap_band(photo_lum, q[3], q[2], vertical_vp, pred_px, +1.0))
            sel = along & (t_front > 0) & (t_front <= pred) & (s_front >= 0) & (s_front <= 1)
            frac = np.clip(t_front / pred, 0.0, 1.0)
        else:
            # Does the detected outline end exactly at the near edge? Then the quad already includes
            # the band: the edge is the strip just above the near edge.
            samples = np.linspace(0.05, 0.95, 40)
            hug = 0
            for s in samples:
                bx, by = q[3] + s * (q[2] - q[3])
                ddx, ddy = _down(np.array([bx]), np.array([by]), vertical_vp)
                ax, ay = int(bx - 3 * ddx[0]), int(by - 3 * ddy[0])
                cx, cy = int(bx + 3 * ddx[0]), int(by + 3 * ddy[0])
                if 0 <= ax < w and 0 <= ay < h and 0 <= cx < w and 0 <= cy < h and m[ay, ax] and not m[cy, cx]:
                    hug += 1
            if hug < 0.6 * len(samples):
                return None
            kind = "inward"
            if photo_lum is not None:
                pred = np.interp(np.clip(s_front, 0, 1), s_samples,
                                 snap_band(photo_lum, q[3], q[2], vertical_vp, pred_px, -1.0))
            sel = inside & along & (t_front <= 0) & (t_front > -pred)
            frac = np.clip(1.0 + t_front / pred, 0.0, 1.0)
    front = sel & (inside | (kind == "predicted"))
    if kind == "predicted":
        front &= (gx >= 0) & (gx < w) & (gy >= 0) & (gy < h)

    if front.any():
        # The top edge of the face: the near edge itself, or (when the quad already included the
        # band) the line one band-height above it. The finish continues down from there.
        lift = pred[front] if kind == "inward" else 0.0
        topx, topy = ex[front] - lift * dx[front], ey[front] - lift * dy[front]
        X_top, Y_top, _ = _apply(Hinv, topx, topy)
        face[front] = True
        depth[front] = frac[front]
        u_mm[front] = X_top
        v_mm[front] = Y_top + T * frac[front]
        smp_x[front] = topx - 3.0 * dx[front]
        smp_y[front] = topy - 3.0 * dy[front]
        light[front] = FRONT_LIGHT

    # End faces: below the end edges (q1 -> q2 on the right, q0 -> q3 on the left), only where the
    # mask itself shows them, and no deeper than the front band is tall at that corner.
    if kind == "band" and prof is not None:
        for a, b, at_end, X_end in ((q[1], q[2], 1.0, L), (q[0], q[3], 0.0, 0.0)):
            t_end, fx, fy = _line_coords(gx, gy, a, b, dx, dy)
            ex2, ey2 = b - a
            s_end = ((fx - a[0]) * ex2 + (fy - a[1]) * ey2) / (ex2 * ex2 + ey2 * ey2)
            corner_px = float(_band_lookup(prof, np.array([at_end]))[0])
            # A pixel is on this end face if it lies beyond the end in plane coordinates.
            Xp, Yp, den = _apply(Hinv, gx, gy)
            beyond = (Xp > L) if X_end == L else (Xp < 0)
            sel_e = (inside & ~face & beyond & (t_end > 0.5) & (t_end <= corner_px * 1.15 + 2)
                     & (s_end > -0.02) & (s_end < 1.02) & (den > 0))
            if not sel_e.any():
                continue
            frac_e = np.clip(t_end / max(corner_px, 2.0), 0.0, 1.0)
            Y_e = _apply(Hinv, fx[sel_e], fy[sel_e])[1]
            face[sel_e] = True
            depth[sel_e] = frac_e[sel_e]
            u_mm[sel_e] = (X_end + T * frac_e[sel_e]) if X_end == L else (X_end - T * frac_e[sel_e])
            v_mm[sel_e] = Y_e
            smp_x[sel_e] = fx[sel_e] - 3.0 * dx[sel_e]
            smp_y[sel_e] = fy[sel_e] - 3.0 * dy[sel_e]
            light[sel_e] = END_LIGHT

    # A hand-drawn outline: an end face only where the photo clearly shows the old one.
    if kind == "predicted" and photo_lum is not None and front.any():
        for a, b, at_end, X_end in ((q[2], q[1], 1.0, L), (q[3], q[0], 0.0, 0.0)):
            corner = float(np.interp(at_end, s_samples, pred_px))
            n = 24
            seen: list[float] = []
            heights = snap_band(photo_lum, a, b, vertical_vp, np.full(n, corner), +1.0, samples=n, found=seen)
            if not seen or seen[0] < 0.5:
                continue
            t_end, fx, fy = _line_coords(gx, gy, a, b, dx, dy)
            ex2, ey2 = b - a
            s_end = ((fx - a[0]) * ex2 + (fy - a[1]) * ey2) / (ex2 * ex2 + ey2 * ey2)
            hgt = np.interp(np.clip(s_end, 0, 1), (np.arange(n) + 0.5) / n, heights)
            Xp, _, den = _apply(Hinv, gx, gy)
            beyond = (Xp > L) if X_end == L else (Xp < 0)
            sel_e = (~face & beyond & (t_end > 0) & (t_end <= hgt) & (s_end >= 0) & (s_end <= 1) & (den > 0)
                     & (gx >= 0) & (gx < w) & (gy >= 0) & (gy < h))
            if not sel_e.any():
                continue
            frac_e = np.clip(t_end / np.maximum(hgt, 2.0), 0.0, 1.0)
            Y_e = _apply(Hinv, fx[sel_e], fy[sel_e])[1]
            face[sel_e] = True
            depth[sel_e] = frac_e[sel_e]
            u_mm[sel_e] = (X_end + T * frac_e[sel_e]) if X_end == L else (X_end - T * frac_e[sel_e])
            v_mm[sel_e] = Y_e
            smp_x[sel_e] = fx[sel_e] - 3.0 * dx[sel_e]
            smp_y[sel_e] = fy[sel_e] - 3.0 * dy[sel_e]
            light[sel_e] = END_LIGHT

    if not face.any():
        return None

    shade = np.zeros_like(gx, dtype=np.float32)
    for lvl in (FRONT_LIGHT, END_LIGHT):
        k = face & (light == lvl)
        if k.any():
            shade[k] = profile_shade(depth[k], lvl, edge_shape, gloss)

    # Light pools and shadows along the old edge carry over, gently (the old edge's own colour does not).
    if photo_lum is not None and kind == "band":
        lum = photo_lum[y0:y1, x0:x1]
        bins = 48
        sb = np.clip(((s_front + 0.1) / 1.2 * bins).astype(int), 0, bins - 1)
        f = face & (light == FRONT_LIGHT)
        if f.sum() > 50:
            med = np.full(bins, np.nan)
            for b in np.unique(sb[f]):
                vals = lum[f & (sb == b)]
                if len(vals) >= 5:
                    med[b] = np.median(vals)
            ok = np.isfinite(med)
            if ok.sum() >= 3:
                med = np.interp(np.arange(bins), np.arange(bins)[ok], med[ok])
                ratio = np.clip(med / max(float(np.median(med)), 1e-6), 0.7, 1.3)
                shade[f] *= (1.0 + 0.5 * (ratio[sb[f]] - 1.0)).astype(np.float32)

    def full(a: np.ndarray, fill: float = 0.0) -> np.ndarray:
        out = np.full((h, w), fill, np.float32)
        out[y0:y1, x0:x1] = a
        return out

    ox, oy = tex_origin_mm
    face_u8 = np.zeros((h, w), np.uint8)
    face_u8[y0:y1, x0:x1][face] = 255
    added = face_u8.copy()
    added[m] = 0
    return FaceMap(
        mask=face_u8, added=added,
        map_u=full(np.where(face, (u_mm + ox) * tex_px_per_mm, 0.0)),
        map_v=full(np.where(face, (v_mm + oy) * tex_px_per_mm, 0.0)),
        sample_x=full(np.where(face, smp_x, 0.0)), sample_y=full(np.where(face, smp_y, 0.0)),
        shade=full(shade, 1.0), kind=kind,
    )
