"""Surface detection with SAM 3 on fal.ai (text-prompted segmentation).

Request and response fields follow the fal-ai/sam-3/image API page (Sep 2026):
input image_url, prompt, apply_mask, return_multiple_masks, max_masks, include_scores,
sync_mode; output masks[] (image files), scores[] and metadata[].score.
Run `python -m backend.tools.try_models <photo>` against a real key to confirm the
shape before relying on it; the parser below accepts both URL and data-URI masks.
"""

from __future__ import annotations

import base64

import cv2
try:
    import httpx2 as httpx  # the maintained successor; same API
except ImportError:  # pragma: no cover
    import httpx
import numpy as np

from .base import Detection, ModelError

PROMPTS = {
    "countertop": "kitchen countertop",
    "backsplash": "kitchen backsplash",
}


def _to_data_uri(image_bgr: np.ndarray, max_side: int) -> tuple[str, float]:
    h, w = image_bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    small = cv2.resize(image_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image_bgr
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ModelError("could not encode image")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode(), scale


def _fetch_mask(ref: str, client: httpx.Client) -> np.ndarray:
    if ref.startswith("data:"):
        raw = base64.b64decode(ref.split(",", 1)[1])
    else:
        r = client.get(ref, timeout=60)
        r.raise_for_status()
        raw = r.content
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ModelError("SAM 3 returned a mask that is not an image")
    if img.ndim == 3:
        img = img[..., 3] if img.shape[2] == 4 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return np.where(img > 127, 255, 0).astype(np.uint8)


class FalSam3Detector:
    def __init__(self, fal_key: str, base_url: str = "https://fal.run", endpoint: str = "fal-ai/sam-3/image",
                 min_score: float = 0.35, max_side: int = 1536, timeout_s: float = 120.0) -> None:
        if not fal_key:
            raise ModelError("FAL_KEY is not set")
        self.fal_key, self.url = fal_key, f"{base_url.rstrip('/')}/{endpoint}"
        self.min_score, self.max_side, self.timeout_s = min_score, max_side, timeout_s
        self.model_id = f"fal:{endpoint}"

    def detect(self, image_bgr: np.ndarray) -> list[Detection]:
        h, w = image_bgr.shape[:2]
        data_uri, _ = _to_data_uri(image_bgr, self.max_side)
        found: list[Detection] = []
        headers = {"Authorization": f"Key {self.fal_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout_s) as client:
            for surface_class, prompt in PROMPTS.items():
                body = {"image_url": data_uri, "prompt": prompt, "apply_mask": False, "return_multiple_masks": True,
                        "max_masks": 4, "include_scores": True, "include_boxes": True, "sync_mode": True,
                        "output_format": "png"}
                r = client.post(self.url, json=body, headers=headers)
                if r.status_code >= 400:
                    raise ModelError(f"SAM 3 error {r.status_code}: {r.text[:300]}")
                out = r.json()
                masks = out.get("masks") or []
                scores = out.get("scores") or [m.get("score") for m in out.get("metadata") or []]
                for i, m in enumerate(masks):
                    ref = m.get("url") if isinstance(m, dict) else m
                    if not ref:
                        continue
                    score = float(scores[i]) if i < len(scores) and scores[i] is not None else 0.5
                    if score < self.min_score:
                        continue
                    mask = cv2.resize(_fetch_mask(ref, client), (w, h), interpolation=cv2.INTER_NEAREST)
                    if np.count_nonzero(mask) < 0.002 * w * h:
                        continue
                    found.append(Detection(surface_class=surface_class, mask=mask, score=score))
        return found
