"""Surface detection with SAM 3 on fal.ai (text-prompted segmentation).

SAM 3 finds what it is asked for, nothing else. Besides the two surfaces it is asked for
every object Claude saw on or in front of them (the describer's open "objects" list),
plus the sink, cooktop and faucet, which are part of every countertop job. The pipeline
subtracts the objects from the surface masks, so the finish is never painted over
anything that is really there. One request per prompt, a few at a time, at $0.005 a
request on fal (Oct 2026).

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
# Always asked: they sit in the counter itself and every installation has to plan around them.
ALWAYS_OBJECTS = ("sink", "cooktop", "faucet")
MAX_OBJECTS = 40


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
                 min_score: float = 0.35, max_side: int = 1536, timeout_s: float = 120.0,
                 workers: int = 8, transport=None) -> None:
        if not fal_key:
            raise ModelError("FAL_KEY is not set")
        self.fal_key, self.url = fal_key, f"{base_url.rstrip('/')}/{endpoint}"
        self.min_score, self.max_side, self.timeout_s = min_score, max_side, timeout_s
        self.workers, self.transport = workers, transport
        self.model_id = f"fal:{endpoint}"

    def _ask(self, data_uri: str, prompt: str, max_masks: int, size: tuple[int, int],
             min_area: float) -> list[tuple[np.ndarray, float]]:
        w, h = size
        headers = {"Authorization": f"Key {self.fal_key}", "Content-Type": "application/json"}
        body = {"image_url": data_uri, "prompt": prompt, "apply_mask": False, "return_multiple_masks": True,
                "max_masks": max_masks, "include_scores": True, "include_boxes": True, "sync_mode": True,
                "output_format": "png"}
        with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:  # one client per thread
            r = client.post(self.url, json=body, headers=headers)
            if r.status_code >= 400:
                raise ModelError(f"SAM 3 error {r.status_code} for {prompt!r}: {r.text[:300]}")
            out = r.json()
            masks = out.get("masks") or []
            scores = out.get("scores") or [m.get("score") for m in out.get("metadata") or []]
            found = []
            for i, m in enumerate(masks):
                ref = m.get("url") if isinstance(m, dict) else m
                if not ref:
                    continue
                score = float(scores[i]) if i < len(scores) and scores[i] is not None else 0.5
                if score < self.min_score:
                    continue
                mask = cv2.resize(_fetch_mask(ref, client), (w, h), interpolation=cv2.INTER_NEAREST)
                if np.count_nonzero(mask) < min_area * w * h:
                    continue
                found.append((mask, score))
        return found

    def detect(self, image_bgr: np.ndarray, objects: list[str] | None = None) -> list[Detection]:
        """Both surfaces, plus every object named in `objects` (Claude's list) and the sink, cooktop and faucet."""
        from concurrent.futures import ThreadPoolExecutor

        h, w = image_bgr.shape[:2]
        data_uri, _ = _to_data_uri(image_bgr, self.max_side)
        names = list(dict.fromkeys([*ALWAYS_OBJECTS, *(o.strip().lower() for o in objects or [] if o.strip())]))
        jobs = [(cls, prompt, 4, 0.002) for cls, prompt in PROMPTS.items()]
        jobs += [("object", prompt, 8, 0.00005) for prompt in names[:MAX_OBJECTS]]
        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as pool:
            futures = [(cls, prompt, pool.submit(self._ask, data_uri, prompt, n, (w, h), area))
                       for cls, prompt, n, area in jobs]
            found: list[Detection] = []
            for cls, prompt, fut in futures:
                try:
                    results = fut.result()
                except ModelError:
                    if cls != "object":
                        raise
                    continue  # one object prompt failing must not lose the surfaces
                for mask, score in results:
                    found.append(Detection(surface_class=cls, mask=mask, score=score,
                                           label=prompt if cls == "object" else None))
        return found
