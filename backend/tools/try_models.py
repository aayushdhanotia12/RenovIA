"""Check the live models against one photo before switching the app to live mode.

    python -m backend.tools.try_models path/to/kitchen.jpg

Needs FAL_KEY and ANTHROPIC_API_KEY (see .env.example). Prints what SAM 3 found, what
Claude sees, and three suggestions, and writes an overlay image next to the photo so
you can judge the masks by eye.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from backend.app.ai.anthropic_client import AnthropicClient
from backend.app.ai.fal_sam3 import FalSam3Detector
from backend.app.ai.suggester import ClaudeDescriber, ClaudeSuggester
from backend.app.catalogue import get_catalogue
from backend.app.config import get_settings
from backend.app.geometry import fit_quad


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    photo = Path(sys.argv[1])
    img = cv2.imread(str(photo), cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"cannot read {photo}")
    s = get_settings()

    t0 = time.time()
    dets = FalSam3Detector(s.fal_key or "", s.fal_base_url, s.sam3_endpoint, s.sam3_min_score).detect(img)
    print(f"SAM 3: {len(dets)} surface(s) in {time.time() - t0:.1f}s")
    overlay = img.copy()
    colours = {"countertop": (51, 90, 200), "backsplash": (234, 196, 147)}
    for d in dets:
        quad = fit_quad(d.mask)
        print(f"  {d.surface_class:10s} score {d.score:.2f}  area {np.count_nonzero(d.mask)} px  quad {quad}")
        tint = np.zeros_like(overlay)
        tint[:] = colours[d.surface_class]
        overlay = np.where(d.mask[..., None] > 0, (0.55 * overlay + 0.45 * tint).astype(np.uint8), overlay)
        if quad:
            cv2.polylines(overlay, [np.int32(quad)], True, (255, 255, 255), 3)
    out = photo.with_name(photo.stem + "_sam3.jpg")
    cv2.imwrite(str(out), overlay)
    print(f"  overlay written to {out}")

    claude = AnthropicClient(s.anthropic_api_key or "", s.anthropic_model, s.anthropic_base_url, effort=s.anthropic_effort)
    t0 = time.time()
    desc = ClaudeDescriber(claude).describe(img, "en")
    print(f"\nClaude ({s.anthropic_model}, effort {s.anthropic_effort or 'default'}) description in "
          f"{time.time() - t0:.1f}s:\n{json.dumps(desc, indent=1)}")
    t0 = time.time()
    sugg = ClaudeSuggester(claude, get_catalogue()).suggest(desc, "white marble, bright", None, "es")
    print(f"\nSuggestions in {time.time() - t0:.1f}s:\n{json.dumps(sugg, indent=1, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
