"""Surface geometry: masks, polygons, and the four-corner plane each surface is drawn on."""

from __future__ import annotations

import cv2
import numpy as np

Point = list[int]


def order_quad(points: np.ndarray) -> list[Point]:
    """Order four points as far-left, far-right, near-right, near-left.

    'Far' is the upper edge in the photo (the back of a countertop, the top of a wall).
    """
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    by_y = pts[np.argsort(pts[:, 1])]
    top = by_y[:2][np.argsort(by_y[:2, 0])]
    bottom = by_y[2:][np.argsort(by_y[2:, 0])]
    return [[int(round(x)), int(round(y))] for x, y in (top[0], top[1], bottom[1], bottom[0])]


def largest_contour(mask: np.ndarray) -> np.ndarray | None:
    contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def fit_quad(mask: np.ndarray) -> list[Point] | None:
    """Four-corner outline of a surface mask, as a starting point the user can adjust."""
    contour = largest_contour(mask)
    if contour is None or cv2.contourArea(contour) < 400:
        return None
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    for frac in np.linspace(0.01, 0.2, 40):
        approx = cv2.approxPolyDP(hull, frac * perimeter, True)
        if len(approx) == 4:
            return order_quad(approx.reshape(4, 2))
        if len(approx) < 4:
            break
    return order_quad(cv2.boxPoints(cv2.minAreaRect(contour)))


def mask_polygon(mask: np.ndarray, epsilon_px: float = 2.0) -> list[Point]:
    contour = largest_contour(mask)
    if contour is None:
        return []
    approx = cv2.approxPolyDP(contour, epsilon_px, True)
    return [[int(p[0][0]), int(p[0][1])] for p in approx]


def polygon_mask(polygon: list[Point], shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    if len(polygon) >= 3:
        cv2.fillPoly(mask, [np.int32(polygon)], 255)
    return mask


def centroid(mask: np.ndarray) -> list[int]:
    m = cv2.moments((mask > 0).astype(np.uint8))
    if m["m00"] == 0:
        return [0, 0]
    return [int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"])]


def valid_quad(quad: list[Point], width: int, height: int) -> bool:
    """Four distinct points, a non-degenerate, non-self-intersecting outline near the image."""
    if len(quad) != 4:
        return False
    pts = np.asarray(quad, dtype=np.float32)
    if np.any(pts[:, 0] < -width) or np.any(pts[:, 0] > 2 * width) or np.any(pts[:, 1] < -height) or np.any(pts[:, 1] > 2 * height):
        return False
    area = cv2.contourArea(pts)
    return area > 400 and cv2.isContourConvex(pts.reshape(-1, 1, 2))


def default_focal_px(width: int, height: int) -> float:
    """Focal length of a typical phone main camera (26 mm equivalent) in pixels."""
    return 26.0 / 36.0 * max(width, height)


def rectangle_aspect(quad: list[Point], width: int, height: int, focal_px: float | None = None) -> float:
    """True width/height ratio of the rectangle a perspective quad shows.

    Zhang & He's whiteboard method with the principal point at the image centre and a
    known focal length (solving for the focal length too is unstable on long counters).
    Quad order: far-left, far-right, near-right, near-left; "width" runs far-left to
    far-right (the counter's length), "height" far-left to near-left (its depth).
    """
    f = focal_px or default_focal_px(width, height)
    u0, v0 = width / 2.0, height / 2.0
    q = [np.array([p[0], p[1], 1.0]) for p in quad]
    m1, m2, m4, m3 = q[0], q[1], q[2], q[3]
    d2 = float(np.dot(np.cross(m2, m4), m3))
    d3 = float(np.dot(np.cross(m3, m4), m2))
    if abs(d2) < 1e-9 or abs(d3) < 1e-9:
        raise ValueError("degenerate quad")
    k2 = float(np.dot(np.cross(m1, m4), m3)) / d2
    k3 = float(np.dot(np.cross(m1, m4), m2)) / d3
    n2, n3 = k2 * m2 - m1, k3 * m3 - m1
    a_inv = np.linalg.inv(np.array([[f, 0, u0], [0, f, v0], [0, 0, 1.0]]))
    a2, a3 = a_inv @ n2, a_inv @ n3
    return float(np.sqrt((a2 @ a2) / (a3 @ a3)))


def subtract_objects(surface_mask: np.ndarray, object_masks: list[np.ndarray],
                     max_share: float = 0.4) -> np.ndarray:
    """The surface's product pixels: its mask minus everything standing on or in front of it.

    An "object" that covers more than `max_share` of the surface is a detector mix-up (the
    whole counter returned for "cooktop"), not something on the counter, and is ignored.
    """
    out = surface_mask.copy()
    area = max(int(np.count_nonzero(surface_mask)), 1)
    for m in object_masks:
        overlap = (m > 0) & (surface_mask > 0)
        n = int(np.count_nonzero(overlap))
        if n == 0 or n > max_share * area:
            continue
        out[overlap] = 0
    return out


def object_record(label: str, mask: np.ndarray, score: float) -> dict:
    """What the app keeps about a detected object: enough to point at it and to keep it unpainted."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return {"label": label, "score": round(float(score), 3), "area_px": 0}
    return {"label": label, "score": round(float(score), 3), "area_px": int(len(xs)),
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            "centroid": centroid(mask)}

