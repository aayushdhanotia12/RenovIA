"""RenovAI's model worker: the open models we run ourselves, behind one small HTTP API.

It runs anywhere Python and PyTorch do: a cloud GPU that bills per second and stops when
idle (modal_app.py), a rented GPU box, or a Mac (Apple's MPS backend). The app server
calls it through backend/app/ai/worker.py and falls back to its own estimates when the
worker is unreachable.

    POST /lighting   body: the photo (JPEG/PNG)  ->  .npy float16 H x W x 3, linear diffuse shading
                     (Marigold-IID-Lighting v1-1: the room's light without surfaces' colour or shine)
    GET  /health     which models are loaded, on which device

Every request needs `Authorization: Bearer <RENOVAI_WORKER_TOKEN>`. Models load on first use.
Run locally:  RENOVAI_WORKER_TOKEN=... uvicorn --factory workers.gpu.app:create_app --port 9000
"""

from __future__ import annotations

import io
import os
import threading
import time

import numpy as np
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

LIGHTING_MODEL = "prs-eth/marigold-iid-lighting-v1-1"
MAX_UPLOAD = 15 * 1024 * 1024


def pick_device() -> tuple[str, object]:
    import torch
    if torch.cuda.is_available():
        return "cuda", torch.float16
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32


class Lighting:
    def __init__(self) -> None:
        import diffusers
        import torch
        self.device, dtype = pick_device()
        kwargs = {"torch_dtype": dtype}
        if dtype == torch.float16:
            kwargs["variant"] = "fp16"
        try:
            pipe = diffusers.MarigoldIntrinsicsPipeline.from_pretrained(LIGHTING_MODEL, **kwargs)
        except (OSError, ValueError):  # no fp16 files published: load the full weights in half precision
            kwargs.pop("variant", None)
            pipe = diffusers.MarigoldIntrinsicsPipeline.from_pretrained(LIGHTING_MODEL, **kwargs)
        self.pipe = pipe.to(self.device)
        names = list(self.pipe.target_properties.get("target_names", ["albedo", "shading", "residual"]))
        self.index = names.index("shading")
        self.lock = threading.Lock()

    def __call__(self, image_bytes: bytes) -> np.ndarray:
        import torch
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        with self.lock, torch.no_grad():  # one diffusion at a time per process
            out = self.pipe(img, num_inference_steps=4, processing_resolution=768)
        pred = out.prediction
        pred = np.asarray(pred.cpu().float() if hasattr(pred, "cpu") else pred, np.float32)
        if pred.ndim == 4 and pred.shape[1] == 3:
            pred = pred.transpose(0, 2, 3, 1)
        return pred[self.index]


_models: dict[str, object] = {}
_load_lock = threading.Lock()


def model(name: str):
    with _load_lock:
        if name not in _models:
            _models[name] = {"lighting": Lighting}[name]()
        return _models[name]


def create_app() -> Starlette:
    token = os.environ.get("RENOVAI_WORKER_TOKEN", "")
    if not token:
        raise RuntimeError("set RENOVAI_WORKER_TOKEN")

    def authorised(request: Request) -> bool:
        return request.headers.get("authorization", "") == f"Bearer {token}"

    async def health(request: Request):
        if not authorised(request):
            return JSONResponse({"detail": "unauthorised"}, status_code=401)
        device, _ = pick_device()
        return JSONResponse({"ok": True, "device": device, "loaded": sorted(_models),
                             "models": {"lighting": LIGHTING_MODEL}})

    async def lighting(request: Request):
        if not authorised(request):
            return JSONResponse({"detail": "unauthorised"}, status_code=401)
        body = await request.body()
        if not body or len(body) > MAX_UPLOAD:
            return JSONResponse({"detail": "send one photo up to 15 MB as the request body"}, status_code=400)
        t0 = time.time()
        try:
            shading = model("lighting")(body)
        except Exception as e:  # noqa: BLE001 - report, don't crash the worker
            return JSONResponse({"detail": f"{type(e).__name__}: {e}"}, status_code=500)
        buf = io.BytesIO()
        np.save(buf, shading.astype(np.float16), allow_pickle=False)
        return Response(buf.getvalue(), media_type="application/octet-stream",
                        headers={"X-Model": LIGHTING_MODEL, "X-Seconds": f"{time.time() - t0:.2f}"})

    return Starlette(routes=[Route("/health", health), Route("/lighting", lighting, methods=["POST"])])
