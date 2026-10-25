"""Render bake-off: which image model makes our kitchens look photographed, and does the stone stay Kober's?

    python research/render_eval/run.py --inputs research/render_eval/inputs --out research/render_eval/results \
        --models openai:gpt-image-2 google:<model> fal:<model-id> ...

For every case (research/render_eval/inputs.py) and every model whose key is set, three arms:
  alone     the customer's photo + the finish swatch, "replace the countertop with this":
            what the model does by itself (expect a re-imagined stone and a changed kitchen);
  finish    our composite + the swatch, "make this a real photograph, change nothing":
            the model as a photographer of our exact render;
  transfer  `finish`'s light (Marigold-IID shading and reflections) on the product's own
            albedo, the customer's photo untouched outside the products (renderer/light_transfer.py).
Per output: alignment to the photo, how much of the kitchen outside the products changed,
how well the countertop pattern still matches the product, the albedo drift, seconds.
Writes one contact sheet per case, the outputs, and summary.json. Runs in GitHub Actions
(.github/workflows/render-eval.yml); the app does not import it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from renderer.composite import srgb_to_linear  # noqa: E402
from renderer.light_transfer import _band, _ncc, align_generated, finish_with_generated  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from providers import FalImages, GeminiImages, OpenAIImages, XAIImages  # noqa: E402

KINDS = {"openai": OpenAIImages, "google": GeminiImages, "fal": FalImages, "xai": XAIImages}

ALONE = ("Replace the kitchen countertop{splash} in the first photo with the material shown in the second image "
         "(Kober {top}), at a realistic scale, with a {edge} front edge. Keep everything else exactly as it is: "
         "same camera angle and framing, the same cabinets, sink, cooktop, objects, walls and lighting. "
         "Do not add or remove anything. Photorealistic.")
FINISH = ("This photo of a real kitchen has just had its countertop{splash} replaced, and the new surfaces look "
          "pasted in. Make it look like an untouched photograph taken with the same camera. Give the {top} "
          "countertop the {shine} it would really have: reflections of the under-cabinet lights, the backsplash "
          "and the objects standing on it, soft contact shadows under every object, and a crisp {edge} front "
          "edge catching the light. Keep the countertop's pattern, veining, colour and scale exactly as they are "
          "(the second image is the real material). Change nothing else: same framing, cabinets, appliances, "
          "objects, walls and lights. Do not add or remove anything.")


def shine(gloss: float) -> str:
    return "polished, mirror-like sheen" if gloss >= 0.4 else "soft satin sheen" if gloss >= 0.2 else "matte finish"


def prompt(template: str, case: dict) -> str:
    splash = " and backsplash" if case.get("backsplash") else ""
    edge = "rounded" if case["profile"]["id"] in ("original", "basik") else "square"
    return template.format(splash=splash, top=case["countertop"]["name"], edge=edge,
                           shine=shine(case["countertop"]["gloss"]))


def jpeg(img: np.ndarray, q: int = 93) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()


def pattern_match(img_bgr: np.ndarray, ref_bgr: np.ndarray, mask: np.ndarray) -> float:
    """Band-pass correlation of log luminance inside the products: 1 = the same pattern as `ref`."""
    def logl(x):
        return np.log(srgb_to_linear(x[..., ::-1]).mean(axis=2) + 1e-3)
    inner = cv2.erode((mask > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    return round(_ncc(_band(logl(img_bgr), 0.8, 4.0), _band(logl(ref_bgr), 0.8, 4.0), inner), 3)  # veins, not light


def outside_change(img_bgr: np.ndarray, photo_bgr: np.ndarray, mask: np.ndarray) -> float:
    """Mean absolute difference (0-255) outside the products, after alignment."""
    out = cv2.dilate((mask > 0).astype(np.uint8), np.ones((15, 15), np.uint8)) == 0
    return round(float(cv2.absdiff(img_bgr, photo_bgr)[out].mean()), 2)


class Intrinsics:
    """Marigold-IID-Lighting on CPU (or the worker's /intrinsics when RENOVAI_WORKER_URL is set)."""

    def __init__(self) -> None:
        import diffusers
        import torch
        self.torch = torch
        self.pipe = diffusers.MarigoldIntrinsicsPipeline.from_pretrained("prs-eth/marigold-iid-lighting-v1-1",
                                                                        torch_dtype=torch.float32)
        self.names = list(self.pipe.target_properties.get("target_names", ["albedo", "shading", "residual"]))

    def __call__(self, bgr: np.ndarray):
        from PIL import Image
        with self.torch.no_grad():
            out = self.pipe(Image.fromarray(bgr[..., ::-1].copy()), num_inference_steps=4, processing_resolution=1024)
        pred = np.asarray(out.prediction.cpu() if hasattr(out.prediction, "cpu") else out.prediction, np.float32)
        if pred.ndim == 4 and pred.shape[1] == 3:
            pred = pred.transpose(0, 2, 3, 1)
        h, w = bgr.shape[:2]
        parts = {n: cv2.resize(pred[i], (w, h), interpolation=cv2.INTER_LINEAR) for i, n in enumerate(self.names)}
        return parts["albedo"], parts["shading"], parts["residual"]


def label(img: np.ndarray, lines: list[str], width: int = 640) -> np.ndarray:
    h, w = img.shape[:2]
    out = cv2.resize(img, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    y = 22
    for text in lines:
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (0, y - 16), (tw + 10, y + 6), (20, 20, 20), -1)
        cv2.putText(out, text, (5, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        y += 24
    return out


def sheet(tiles: list[np.ndarray], cols: int = 3) -> np.ndarray:
    h = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)) for t in tiles]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])


def providers(specs: list[str]):
    out = []
    for spec in specs:
        kind, _, model = spec.partition(":")
        extra = {}
        if "|" in model:  # fal:<model-id>|image_url  -> a model whose input is a single image
            model, field = model.split("|", 1)
            extra["image_field"] = field
        p = KINDS[kind](model, **extra)
        (out if p.available() else []).append(p)
        if not p.available():
            print(f"skip {spec}: {p.key_env} not set", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--models", nargs="+", required=True, help="kind:model, e.g. openai:gpt-image-2")
    ap.add_argument("--cases", nargs="*", default=None)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    models = providers(args.models)
    intrinsics = None
    try:
        intrinsics = Intrinsics()
    except Exception as e:  # noqa: BLE001
        print("no intrinsics model, the transfer arm is skipped:", e, flush=True)

    summary = {"models": [m.label for m in models], "cases": []}
    for case_dir in sorted(p for p in args.inputs.iterdir() if p.is_dir()):
        if args.cases and case_dir.name not in args.cases:
            continue
        case = json.loads((case_dir / "case.json").read_text())
        photo = cv2.imread(str(case_dir / "photo.jpg"))
        ours = cv2.imread(str(case_dir / "composite.jpg"))
        swatch = (case_dir / "swatch.jpg").read_bytes()
        mask = cv2.imread(str(case_dir / "mask.png"), cv2.IMREAD_GRAYSCALE)
        alpha = cv2.imread(str(case_dir / "alpha.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
        albedo = np.load(case_dir / "albedo.npz")["albedo"].astype(np.float32)
        out_dir = args.out / case_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        tiles = [label(photo, ["customer photo"]),
                 label(ours, ["ours today (composite-v3)", f"pattern {pattern_match(ours, ours, mask)}"])]
        rows = []
        for m in models:
            for arm, template, images in (("alone", ALONE, [jpeg(photo), swatch]),
                                          ("finish", FINISH, [jpeg(ours), swatch])):
                rec = {"model": m.label, "arm": arm}
                t0 = time.time()
                try:
                    gen = cv2.imdecode(np.frombuffer(m.edit(images, prompt(template, case)), np.uint8), cv2.IMREAD_COLOR)
                except Exception as e:  # noqa: BLE001 - record, carry on with the next model
                    rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
                    print(m.label, arm, rec["error"], flush=True)
                    rows.append(rec)
                    continue
                rec["seconds"] = round(time.time() - t0, 1)
                rec["size"] = list(gen.shape[1::-1])
                al = align_generated(gen, photo, mask == 0)
                rec.update(alignment=round(al.score, 3), outside_change=outside_change(al.warped, photo, mask),
                           pattern=pattern_match(al.warped, ours, mask))
                tag = f"{m.name}_{m.model.replace('/', '-')}_{arm}"
                cv2.imwrite(str(out_dir / f"{tag}.jpg"), al.warped, [cv2.IMWRITE_JPEG_QUALITY, 92])
                tiles.append(label(al.warped, [f"{m.label} · {arm}", f"{rec['seconds']} s · align {rec['alignment']}",
                                               f"kitchen change {rec['outside_change']} · pattern {rec['pattern']}"]))
                if arm == "finish" and intrinsics is not None:
                    try:
                        final, drift = finish_with_generated(photo, albedo, alpha, mask, al.warped, intrinsics)
                        rec["transfer"] = {"pattern": pattern_match(final, ours, mask), "drift_pattern": round(drift.pattern, 3),
                                           "drift_colour_de": round(drift.colour_de, 2), "shown": drift.ok() and al.score >= 0.9}
                        cv2.imwrite(str(out_dir / f"{tag}_transfer.jpg"), final, [cv2.IMWRITE_JPEG_QUALITY, 92])
                        tiles.append(label(final, [f"{m.label} · transfer", f"pattern {rec['transfer']['pattern']}",
                                                   f"model drift {rec['transfer']['drift_pattern']} / dE {rec['transfer']['drift_colour_de']}"]))
                    except Exception as e:  # noqa: BLE001
                        rec["transfer"] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
                print(json.dumps(rec), flush=True)
                rows.append(rec)
        cv2.imwrite(str(args.out / f"sheet_{case_dir.name}.jpg"), sheet(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88])
        summary["cases"].append({"case": case_dir.name, "countertop": case["countertop"]["name"], "results": rows})
        (args.out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
