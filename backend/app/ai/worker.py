"""Client for our own model worker (workers/gpu): the open models RenovAI runs itself.

The worker runs on a cloud GPU that bills per second and stops when idle, or on a Mac;
it serves Marigold-IID-Lighting today. Requests carry the photo as JPEG and the team's
worker token; the answer is a NumPy array (.npy bytes), never anything that can price.
"""

from __future__ import annotations

import io

import cv2
import numpy as np

try:
    import httpx2 as httpx  # the maintained successor; same API
except ImportError:  # pragma: no cover
    import httpx

from .base import ModelError

LIGHTING_MODEL = "prs-eth/marigold-iid-lighting-v1-1"


def _jpeg(image_bgr: np.ndarray, max_side: int = 1536) -> bytes:
    h, w = image_bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    small = cv2.resize(image_bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) \
        if scale < 1 else image_bgr
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ModelError("could not encode the photo")
    return buf.tobytes()


class WorkerLighting:
    """Marigold-IID-Lighting's diffuse shading, from our worker."""

    def __init__(self, url: str, token: str, timeout_s: float = 180.0, transport=None) -> None:
        if not url:
            raise ModelError("RENOVAI_WORKER_URL is not set")
        self.url, self.token, self.timeout_s, self.transport = url.rstrip("/"), token, timeout_s, transport
        self.model_id = f"worker:{LIGHTING_MODEL}"

    def estimate(self, image_bgr: np.ndarray) -> np.ndarray | None:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "image/jpeg"}
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                r = client.post(f"{self.url}/lighting", content=_jpeg(image_bgr), headers=headers)
        except httpx.HTTPError as e:
            raise ModelError(f"model worker unreachable: {e}") from e
        if r.status_code >= 400:
            raise ModelError(f"model worker error {r.status_code}: {r.text[:200]}")
        try:
            arr = np.load(io.BytesIO(r.content), allow_pickle=False)
        except ValueError as e:
            raise ModelError("model worker answered with something that is not an array") from e
        if arr.ndim != 3 or arr.shape[2] != 3 or not np.isfinite(arr).all():
            raise ModelError(f"unexpected lighting shape {arr.shape}")
        return arr.astype(np.float32)
