"""Remodel kitchen photos in several styles with the live models, end to end.

    python -m backend.tools.remodel --request requests/remodel.json

The request file lists photos (repo paths or URLs to download first) and styles:

    {"run_id": "mexico-01", "photos": ["samples/mexico/01.jpg", "https://..."],
     "styles": ["minimalista", "calido", "contraste", "creativo"], "language": "es"}

For each photo: SAM 3 finds the countertop and backsplash, Claude describes the
kitchen, then for each style Claude picks finishes from the Kober catalogue and the
renderer draws them. Sizes come from the surface's true proportions (a 600 mm deep
counter), since nobody typed measurements. Everything lands in runs/<run_id>/, with
a log and a summary.json; one photo failing doesn't stop the others.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from backend.app.ai.anthropic_client import AnthropicClient
from backend.app.ai.fal_sam3 import FalSam3Detector
from backend.app.ai.suggester import ClaudeDescriber, ClaudeSuggester
from backend.app.catalogue import get_catalogue
from backend.app.config import get_settings
from backend.app.geometry import fit_quad, rectangle_aspect, valid_quad
from backend.app.render import render_design, SurfacePlan
from backend.app.styles import STYLES, brief_for

REPO = Path(__file__).resolve().parents[2]
DEPTH_MM = {"countertop": 600, "backsplash": 600}


def ascii_label(text: str) -> str:
    """OpenCV's built-in font has no accents."""
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def fetch(src: str, dest_dir: Path, index: int) -> Path:
    if not src.startswith("http"):
        return (REPO / src).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0 (RenovAI test harness)"})
    data = urllib.request.urlopen(req, timeout=60).read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"not an image: {src}")
    path = dest_dir / f"{index:02d}.jpg"
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return path


def plans_from(img: np.ndarray, detections) -> tuple[list[SurfacePlan], list[dict]]:
    h, w = img.shape[:2]
    plans, info = [], []
    for cls in ("countertop", "backsplash"):
        cands = [d for d in detections if d.surface_class == cls]
        if not cands:
            continue
        best = max(cands, key=lambda d: d.score * np.count_nonzero(d.mask))
        quad = best.quad or fit_quad(best.mask)
        if not quad or not valid_quad(quad, w, h):
            info.append({"surface": cls, "skipped": "no usable four-corner outline"})
            continue
        try:
            aspect = rectangle_aspect(quad, w, h)
        except ValueError:
            aspect = 4.0
        depth = DEPTH_MM[cls]
        length = int(np.clip(round(depth * aspect / 10) * 10, 600, 6000))
        plans.append(SurfacePlan(f"{cls}_1", cls, "A" if cls == "countertop" else "S1", quad, best.mask, length, depth,
                                 best.score))
        info.append({"surface": cls, "score": round(best.score, 3), "quad": quad, "estimated_mm": [length, depth]})
    return plans, info


def overlay(img: np.ndarray, plans: list[SurfacePlan]) -> np.ndarray:
    out = img.copy()
    colours = {"countertop": (51, 90, 200), "backsplash": (234, 196, 147)}
    for p in plans:
        tint = np.zeros_like(out)
        tint[:] = colours[p.surface_class]
        out = np.where(p.mask[..., None] > 0, (0.55 * out + 0.45 * tint).astype(np.uint8), out)
        cv2.polylines(out, [np.int32(p.quad)], True, (255, 255, 255), 3)
    return out


def caption(img: np.ndarray, lines: list[str]) -> np.ndarray:
    h, w = img.shape[:2]
    scale = w / 1600
    bar = int(46 * scale * len(lines)) + int(16 * scale)
    out = img.copy()
    cv2.rectangle(out, (0, h - bar), (w, h), (22, 20, 18), -1)
    for i, line in enumerate(lines):
        y = h - bar + int((i + 1) * 46 * scale)
        cv2.putText(out, line, (int(18 * scale), y), cv2.FONT_HERSHEY_SIMPLEX, 1.1 * scale, (245, 241, 237),
                    max(1, int(2 * scale)), cv2.LINE_AA)
    return out


def contact_sheet(tiles: list[np.ndarray], cols: int = 3, width: int = 900) -> np.ndarray:
    rows = []
    sized = [cv2.resize(t, (width, int(t.shape[0] * width / t.shape[1])), interpolation=cv2.INTER_AREA) for t in tiles]
    th = max(t.shape[0] for t in sized)
    sized = [cv2.copyMakeBorder(t, 0, th - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)) for t in sized]
    while len(sized) % cols:
        sized.append(np.zeros_like(sized[0]))
    for i in range(0, len(sized), cols):
        rows.append(np.hstack(sized[i:i + cols]))
    return np.vstack(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    args = ap.parse_args()
    req = json.loads(Path(args.request).read_text())
    run_id = req.get("run_id") or time.strftime("run-%Y%m%d-%H%M%S")
    out_root = REPO / "runs" / run_id
    out_root.mkdir(parents=True, exist_ok=True)
    styles = req.get("styles") or list(STYLES)
    language = req.get("language", "es")

    s = get_settings()
    cat = get_catalogue()
    detector = FalSam3Detector(s.fal_key or "", s.fal_base_url, s.sam3_endpoint, s.sam3_min_score)
    claude = AnthropicClient(s.anthropic_api_key or "", s.anthropic_model, s.anthropic_base_url, effort=s.anthropic_effort)
    describer, suggester = ClaudeDescriber(claude), ClaudeSuggester(claude, cat)
    cache = REPO / ".cache" / "textures"
    summary = {"run_id": run_id, "models": {"detector": detector.model_id, "claude": claude.model,
                                           "effort": s.anthropic_effort}, "photos": []}

    for i, src in enumerate(req["photos"], start=1):
        rec: dict = {"source": src}
        summary["photos"].append(rec)
        try:
            path = fetch(src, REPO / req.get("download_dir", "samples/mexico"), i)
            rec["photo"] = str(path.relative_to(REPO))
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            scale = min(1.0, 2048 / max(img.shape[:2]))
            if scale < 1:
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            stem = f"{i:02d}"
            d = out_root / stem
            d.mkdir(exist_ok=True)
            cv2.imwrite(str(d / "original.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])

            t0 = time.time()
            dets = detector.detect(img)
            plans, rec["surfaces"] = plans_from(img, dets)
            rec["sam3_seconds"] = round(time.time() - t0, 1)
            cv2.imwrite(str(d / "surfaces.jpg"), overlay(img, plans), [cv2.IMWRITE_JPEG_QUALITY, 88])
            print(f"[{stem}] SAM 3: {len(dets)} masks, using {[p.surface_class for p in plans]}", flush=True)

            t0 = time.time()
            desc = describer.describe(img, language)
            rec["description"], rec["describe_seconds"] = desc, round(time.time() - t0, 1)

            tiles = [caption(img, ["Original"]), caption(overlay(img, plans), ["Superficies detectadas (SAM 3)"])]
            rec["styles"] = {}
            for style in styles:
                t0 = time.time()
                designs = suggester.suggest(desc, brief_for(style) if style in STYLES else style, None, language)
                pick = designs[0]
                top = cat.finish(pick["countertop_finish_id"])
                splash = cat.finish(pick["backsplash_finish_id"]) if pick["backsplash_finish_id"] else None
                srec = {"design": pick, "suggest_seconds": round(time.time() - t0, 1)}
                if plans:
                    t0 = time.time()
                    image, layers, _ = render_design(img, plans, top, splash, cache)
                    srec["render_seconds"] = round(time.time() - t0, 1)
                    cv2.imwrite(str(d / f"{style}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    names = ascii_label(f"Cubierta: {top.name}" + (f"  |  Salpicadero: {splash.name}" if splash else ""))
                    tiles.append(caption(image, [ascii_label(STYLES[style]['es'] if style in STYLES else style), names]))
                rec["styles"][style] = srec
                print(f"[{stem}] {style}: {top.name} / {splash.name if splash else '-'}", flush=True)
            cv2.imwrite(str(out_root / f"sheet_{stem}.jpg"), contact_sheet(tiles), [cv2.IMWRITE_JPEG_QUALITY, 85])
        except Exception as e:  # keep going: one bad photo must not sink the run
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["traceback"] = traceback.format_exc()[-2000:]
            print(f"[{i:02d}] FAILED {rec['error']}", flush=True)
    (out_root / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    failed = sum(1 for p in summary["photos"] if "error" in p)
    print(f"done: {len(summary['photos']) - failed} ok, {failed} failed -> runs/{run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
