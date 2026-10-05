"""Model test run: MoGe-2 (depth, normals, camera), GeoCalib (camera, gravity) and
Marigold-IID-Lighting (albedo, diffuse shading, glare residual) on kitchen photos, on CPU.

    python research/model_eval/run.py --photos research/model_eval/photos --out research/model_eval/results

For each photo it writes a contact sheet (sheet_<name>.jpg), the raw outputs at reduced
size (<name>.npz: depth, normals, Marigold shading and residual, our luminance shading)
and one line in summary.json with timings and every camera estimate side by side:
EXIF (backend/app/camera.py), MoGe-2 and GeoCalib. A model that fails to install or run
is recorded as an error and the others carry on.

It runs in GitHub Actions (.github/workflows/model-eval.yml); the app does not import it.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.app.camera import camera_from_exif  # noqa: E402
from renderer.composite import clean_shading, srgb_to_linear  # noqa: E402

MAX_SIDE = 1280   # photos are scaled down to this before any model sees them
TILE_W = 480


def fov_deg(focal_px: float, size_px: float) -> float:
    return math.degrees(2 * math.atan(size_px / (2 * focal_px)))


def label(img: np.ndarray, lines: list[str]) -> np.ndarray:
    out = img.copy()
    y = 22
    for text in lines:
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (0, y - 16), (tw + 10, y + 6), (20, 20, 20), -1)
        cv2.putText(out, text, (5, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        y += 24
    return out


def tile(img: np.ndarray, lines: list[str]) -> np.ndarray:
    h, w = img.shape[:2]
    small = cv2.resize(img, (TILE_W, round(h * TILE_W / w)), interpolation=cv2.INTER_AREA)
    return label(small, lines)


def to_u8(x: np.ndarray, lo: float | None = None, hi: float | None = None) -> np.ndarray:
    lo = np.nanpercentile(x, 2) if lo is None else lo
    hi = np.nanpercentile(x, 98) if hi is None else hi
    return np.clip((x - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)


def sheet(tiles: list[np.ndarray], cols: int = 3) -> np.ndarray:
    h = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)) for t in tiles]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])


# --- models (each loaded once; a failure is recorded, not raised) ---------------------

class MoGe2:
    name = "Ruicheng/moge-2-vitb-normal"

    def __init__(self):
        import torch
        from moge.model.v2 import MoGeModel
        self.torch = torch
        self.model = MoGeModel.from_pretrained(self.name).eval()

    def __call__(self, rgb: np.ndarray) -> dict:
        t = self.torch.tensor(rgb / 255.0, dtype=self.torch.float32).permute(2, 0, 1)
        with self.torch.no_grad():
            out = self.model.infer(t)
        depth = out["depth"].cpu().numpy()
        normal = out["normal"].cpu().numpy() if "normal" in out and out["normal"] is not None else None
        K = out["intrinsics"].cpu().numpy()
        h, w = rgb.shape[:2]
        fx = float(K[0, 0]) * w if K[0, 0] < 10 else float(K[0, 0])  # MoGe returns normalised intrinsics
        return {"depth": depth, "normal": normal, "focal_px": fx, "mask": out.get("mask")}


class GeoCalibModel:
    name = "GeoCalib (pinhole)"

    def __init__(self):
        from geocalib import GeoCalib
        self.model = GeoCalib()

    def __call__(self, path: Path, scale: float) -> dict:
        img = self.model.load_image(str(path))
        res = self.model.calibrate(img)
        cam, grav = res["camera"], res["gravity"]
        f = cam.f.reshape(-1).tolist()
        roll, pitch = [math.degrees(float(v)) for v in grav.rp.reshape(-1).tolist()[:2]]
        out = {"focal_px": float(f[0]) * scale, "roll_deg": round(roll, 2), "pitch_deg": round(pitch, 2)}
        for key in ("focal_uncertainty", "vfov_uncertainty", "roll_uncertainty", "pitch_uncertainty"):
            if key in res:
                out[key] = round(float(res[key].reshape(-1)[0]), 4)
        return out


class MarigoldIID:
    name = "prs-eth/marigold-iid-lighting-v1-1"

    def __init__(self):
        import diffusers
        import torch
        self.torch = torch
        self.pipe = diffusers.MarigoldIntrinsicsPipeline.from_pretrained(self.name, torch_dtype=torch.float32)

    def __call__(self, rgb: np.ndarray) -> dict:
        from PIL import Image
        with self.torch.no_grad():
            out = self.pipe(Image.fromarray(rgb), num_inference_steps=4, processing_resolution=768)
        pred = out.prediction  # (targets, H, W, 3) or (targets, 3, H, W), linear
        pred = np.asarray(pred.cpu() if hasattr(pred, "cpu") else pred)
        names = list(self.pipe.target_properties.get("target_names", ["albedo", "shading", "residual"]))
        if pred.ndim == 4 and pred.shape[1] == 3:
            pred = pred.transpose(0, 2, 3, 1)
        return {n: pred[i] for i, n in enumerate(names)}


def load(cls):
    t0 = time.time()
    try:
        m = cls()
        return m, {"loaded_s": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        return None, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    attribution = {a["file"]: a for a in json.loads((args.photos / "attribution.json").read_text())}

    models, status = {}, {}
    for key, cls in (("moge2", MoGe2), ("geocalib", GeoCalibModel), ("marigold", MarigoldIID)):
        models[key], status[key] = load(cls)
        print(key, status[key], flush=True)

    summary = {"models": {k: getattr(c, "name", k) for k, c in (("moge2", MoGe2), ("geocalib", GeoCalibModel),
                                                                 ("marigold", MarigoldIID))},
               "load": status, "photos": []}
    for path in sorted(args.photos.glob("*.jpg")):
        raw = path.read_bytes()
        bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        h0, w0 = bgr.shape[:2]
        scale = min(1.0, MAX_SIDE / max(h0, w0))
        if scale < 1:
            bgr = cv2.resize(bgr, (round(w0 * scale), round(h0 * scale)), interpolation=cv2.INTER_AREA)
        h, w = bgr.shape[:2]
        rgb = bgr[..., ::-1].copy()
        rec = {"file": path.name, "size": [w, h], "attribution": attribution.get(path.name, {})}
        cam = camera_from_exif(raw, w, h)
        rec["exif"] = {k: cam.get(k) for k in ("source", "focal_35mm", "focal_px", "lens", "reason", "make", "model")}
        tiles = [tile(bgr, [path.name[:40], f"EXIF: {cam['source']} f={cam['focal_px']}px "
                                            f"({fov_deg(cam['focal_px'], w):.0f} deg)"])]
        npz: dict[str, np.ndarray] = {}

        # Our current light estimate (renderer v3) over the whole photo, for comparison.
        lin = srgb_to_linear(rgb)
        ours = clean_shading(lin, np.full((h, w), 255, np.uint8), 22.0)
        npz["ours_shading"] = cv2.resize(ours, (w // 2, h // 2)).astype(np.float16)
        tiles.append(tile(cv2.cvtColor(to_u8(np.log(ours), -0.7, 0.7), cv2.COLOR_GRAY2BGR),
                          ["Ours today: luminance shading (log)"]))

        if models["moge2"] is not None:
            try:
                t0 = time.time()
                m = models["moge2"](rgb)
                rec["moge2"] = {"seconds": round(time.time() - t0, 1), "focal_px": round(m["focal_px"], 1),
                                "fov_deg": round(fov_deg(m["focal_px"], w), 1)}
                d = m["depth"]
                finite = np.isfinite(d)
                rec["moge2"]["depth_m_median"] = round(float(np.median(d[finite])), 2) if finite.any() else None
                inv = np.where(finite, 1.0 / np.maximum(d, 1e-3), 0)
                tiles.append(tile(cv2.applyColorMap(to_u8(inv), cv2.COLORMAP_TURBO),
                                  [f"MoGe-2 depth ({rec['moge2']['seconds']}s)",
                                   f"focal {m['focal_px']:.0f}px, fov {rec['moge2']['fov_deg']} deg"]))
                npz["moge_depth"] = cv2.resize(np.nan_to_num(d, nan=0, posinf=0), (w // 2, h // 2)).astype(np.float16)
                if m["normal"] is not None:
                    n = np.nan_to_num(m["normal"])
                    tiles.append(tile(((n * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)[..., ::-1],
                                      ["MoGe-2 normals"]))
                    npz["moge_normal"] = cv2.resize(n, (w // 2, h // 2)).astype(np.float16)
            except Exception as e:  # noqa: BLE001
                rec["moge2"] = {"error": f"{type(e).__name__}: {e}"}

        if models["geocalib"] is not None:
            try:
                t0 = time.time()
                g = models["geocalib"](path, scale)
                g["seconds"] = round(time.time() - t0, 1)
                g["fov_deg"] = round(fov_deg(g["focal_px"], w), 1)
                rec["geocalib"] = g
            except Exception as e:  # noqa: BLE001
                rec["geocalib"] = {"error": f"{type(e).__name__}: {e}"}

        if models["marigold"] is not None:
            try:
                t0 = time.time()
                mg = models["marigold"](rgb)
                rec["marigold"] = {"seconds": round(time.time() - t0, 1), "targets": list(mg)}
                for name, arr in mg.items():
                    arr = np.asarray(arr, np.float32)
                    if name == "albedo":
                        view = (np.clip(arr, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)[..., ::-1]
                    elif name == "shading":
                        lum = arr.mean(axis=-1)
                        view = cv2.cvtColor(to_u8(np.log(lum / max(float(np.median(lum)), 1e-6) + 1e-4), -0.7, 0.7),
                                            cv2.COLOR_GRAY2BGR)
                    else:
                        view = (np.clip(arr * 4, 0, 1) * 255).astype(np.uint8)[..., ::-1]
                    tiles.append(tile(view, [f"Marigold {name}" + (f" ({rec['marigold']['seconds']}s)"
                                                                   if name == "albedo" else "")]))
                    small = cv2.resize(arr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
                    npz[f"marigold_{name}"] = small.astype(np.float16)
            except Exception as e:  # noqa: BLE001
                rec["marigold"] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}

        g = rec.get("geocalib", {})
        if "focal_px" in g:
            tiles[0] = label(tiles[0], ["", "", f"GeoCalib: f={g['focal_px']:.0f}px fov {g['fov_deg']} deg",
                                        f"roll {g.get('roll_deg')}  pitch {g.get('pitch_deg')}"])
        cv2.imwrite(str(args.out / f"sheet_{path.stem}.jpg"), sheet(tiles), [cv2.IMWRITE_JPEG_QUALITY, 85])
        np.savez_compressed(args.out / f"{path.stem}.npz", **npz)
        summary["photos"].append(rec)
        print(json.dumps({k: v for k, v in rec.items() if k != "attribution"}), flush=True)
        (args.out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print("done", len(summary["photos"]), "photos")


if __name__ == "__main__":
    main()
