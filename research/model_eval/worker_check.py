"""Check the model worker end to end: start it, send the Kober sample photo, read the light back.

    RENOVAI_WORKER_TOKEN=test python research/model_eval/worker_check.py

Starts workers.gpu.app on port 9000, calls /health and /lighting through the app's own
client (backend/app/ai/worker.py), and fails unless the answer is a finite H x W x 3 shading
map. Used by the model test run in GitHub Actions (CPU).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.app.ai.worker import WorkerLighting  # noqa: E402

try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx


def main() -> None:
    token = os.environ.setdefault("RENOVAI_WORKER_TOKEN", "test")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory", "workers.gpu.app:create_app",
                             "--port", "9000"], cwd=REPO)
    try:
        for _ in range(60):
            try:
                r = httpx.get("http://127.0.0.1:9000/health", headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 200:
                    print("health", r.json())
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise SystemExit("worker did not start")
        bad = httpx.get("http://127.0.0.1:9000/health", headers={"Authorization": "Bearer wrong"})
        assert bad.status_code == 401, bad.status_code
        img = cv2.imread(str(REPO / "samples/kober_photos/p7_0_1920x1200.jpg"))
        t0 = time.time()
        light = WorkerLighting("http://127.0.0.1:9000", token, timeout_s=900).estimate(img)
        print(f"lighting {light.shape} in {time.time() - t0:.1f}s; median {float(np.median(light)):.3f}")
        assert light.ndim == 3 and light.shape[2] == 3 and np.isfinite(light).all()
        stored = np.load(REPO / "samples/fixtures/kober_p7_light.npz")["shading"].astype(np.float32)
        a = cv2.resize(light.mean(axis=2), (stored.shape[1], stored.shape[0]))
        b = stored.mean(axis=2)
        corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        print(f"correlation with the stored fixture: {corr:.3f}")
        assert corr > 0.8, "the worker's light differs from the stored model output"
        print("worker check passed")
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
