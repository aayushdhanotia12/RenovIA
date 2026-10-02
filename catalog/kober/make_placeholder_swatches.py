"""Stand-in finish images, used only until the real Kober swatches are extracted.

The real swatches come from the Kober catalogue PDF:

    python catalog/kober/extract_kober.py path/to/CATKBR25AGO26.pdf

That PDF was not available when this repo was rebuilt on 2 Oct 2026, so this script
draws a plausible texture for every finish in data/finishes.json (marble veins, wood
grain, granite speckle, concrete mottling or a flat colour, in the finish's colours)
so the app, the tests and the renders work. It also writes swatches/PLACEHOLDER, which
the API reports and the app shows as "sample textures" next to every finish.

It never overwrites a real swatch: files are only written where none exists, unless
--force is given. Running extract_kober.py replaces them all and removes the marker.

    python catalog/kober/make_placeholder_swatches.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MARKER = HERE / "swatches" / "PLACEHOLDER"

# Base colour (B, G, R) and secondary colour (veins, grain, speckle) per finish where
# the name says it; everything else falls back to keywords below.
COLOURS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "estilo-porfido-gesso": ((200, 205, 210), (170, 176, 182)),
    "estilo-porfido-nero": ((38, 38, 40), (70, 70, 74)),
    "estilo-corten-grigio": ((112, 116, 120), (80, 88, 98)),
    "estilo-basalto-vulcano": ((52, 54, 58), (78, 80, 84)),
    "estilo-basalto-cenere": ((150, 154, 158), (120, 124, 128)),
    "estilo-caviar-silver": ((168, 168, 166), (120, 120, 120)),
    "estilo-jupiter-moon": ((176, 180, 184), (140, 144, 150)),
    "estilo-manhattan-grey": ((126, 128, 130), (96, 98, 100)),
    "diseno-portoro": ((22, 22, 24), (90, 160, 200)),
    "diseno-calcatta-oro": ((232, 236, 238), (120, 170, 196)),
    "diseno-milano-amber": ((120, 150, 180), (70, 100, 130)),
    "diseno-kahalari-topaz": ((110, 138, 160), (60, 80, 100)),
    "diseno-bordeaux-juparana": ((90, 96, 130), (40, 40, 70)),
    "diseno-cafe-di-pesco": ((96, 118, 140), (60, 76, 92)),
    "diseno-wild-cherry": ((60, 86, 140), (40, 56, 96)),
    "diseno-satin-stainless": ((186, 186, 182), (160, 160, 158)),
    "diseno-designer-white": ((238, 240, 240), (238, 240, 240)),
    "diseno-black": ((30, 30, 32), (30, 30, 32)),
    "estilo-nero": ((28, 28, 30), (40, 40, 42)),
    "basik-almond-leather": ((170, 196, 214), (140, 166, 186)),
    "basik-buka-bark": ((60, 82, 108), (40, 56, 76)),
    "basik-desert-spring": ((150, 176, 196), (110, 132, 150)),
}
LIGHT = ("white", "carrara", "calcutta", "caracatta", "yule", "ice", "frost", "pearl", "ipanema", "india", "glace",
         "winter", "luna", "gesso", "plaster", "high rise")
DARK = ("black", "nero", "kandia", "cardoso", "marquina", "deepstar", "blackstar", "noir", "graphite", "vulcano",
        "shadow", "dusk", "slate", "nebula")
WOOD = ("oak", "rovere", "olmo", "maple", "cherry", "driftwood", "mango", "bark", "madagascar", "asian sand", "echo",
        "birdseye")
MARBLE = ("marble", "carrara", "calcutta", "calcatta", "caracatta", "marquina", "kandia", "yule", "pulpis", "portoro",
          "venato", "saint laurent", "pesco", "cascade", "beige")
GRANITE = ("granite", "juparana", "topaz", "quartz", "milano", "mystique", "alicante", "spring", "bahia", "lapidus",
           "serrania", "trinidad")
SOLID = ("designer white", "black", "satin stainless")


def _rng(key: str) -> np.random.Generator:
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "little"))


def value_noise(rng: np.random.Generator, size: int, octaves: int = 5, base: int = 4) -> np.ndarray:
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = base * 2 ** o
        grid = rng.random((cells + 1, cells + 1)).astype(np.float32)
        out += amp * cv2.resize(grid, (size, size), interpolation=cv2.INTER_CUBIC)
        total += amp
        amp *= 0.5
    out /= total
    return (out - out.min()) / max(1e-6, float(out.max() - out.min()))


def kind_of(fid: str, name: str) -> str:
    n = name.lower()
    if fid in ("diseno-designer-white", "diseno-black", "diseno-satin-stainless", "estilo-nero"):
        return "solid"
    if any(w in n for w in WOOD):
        return "wood"
    if any(w in n for w in MARBLE):
        return "marble"
    if any(w in n for w in GRANITE):
        return "granite"
    return "stone"


def colours_for(fid: str, name: str, kind: str) -> tuple[np.ndarray, np.ndarray]:
    if fid in COLOURS:
        a, b = COLOURS[fid]
        return np.array(a, np.float32), np.array(b, np.float32)
    n = name.lower()
    rng = _rng("colour:" + fid)
    if kind == "wood":
        light = any(w in n for w in ("white", "pale", "pearl", "greige", "sand", "birdseye"))
        base = np.array([150, 186, 214] if light else [78, 112, 150], np.float32) + rng.uniform(-14, 14, 3)
        return base, base * 0.72
    if any(w in n for w in DARK):
        return np.array([34, 34, 36], np.float32) + rng.uniform(-4, 4, 3), np.array([200, 200, 204], np.float32)
    if any(w in n for w in LIGHT):
        return np.array([232, 234, 234], np.float32) + rng.uniform(-6, 2, 3), np.array([150, 154, 160], np.float32)
    grey = float(rng.uniform(110, 175))
    return np.array([grey, grey + 2, grey + 4], np.float32), np.array([grey - 40] * 3, np.float32)


def draw(fid: str, name: str, size: int) -> np.ndarray:
    kind = kind_of(fid, name)
    base, second = colours_for(fid, name, kind)
    rng = _rng(fid)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32) / size
    fine = rng.normal(0, 1, (size, size)).astype(np.float32)
    if kind == "solid":
        img = np.broadcast_to(base, (size, size, 3)) + 1.6 * fine[..., None]
    elif kind == "wood":
        warp = value_noise(rng, size, 4, 2)
        rings = np.sin((ys * 34 + 3.0 * warp) * np.pi) * 0.5 + 0.5
        streak = cv2.GaussianBlur(rng.random((size, size)).astype(np.float32), (0, 0), sigmaX=size / 3, sigmaY=0.8)
        streak = (streak - streak.min()) / max(1e-6, float(streak.max() - streak.min()))
        t = np.clip(0.55 * rings + 0.45 * streak, 0, 1)[..., None]
        img = base * (1 - 0.55 * t) + second * (0.55 * t) + 3.0 * fine[..., None]
    elif kind == "marble":
        turb = value_noise(rng, size, 6, 3)
        angle = float(rng.uniform(0.3, 1.2))
        line = np.abs(np.sin((xs * np.cos(angle) + ys * np.sin(angle)) * 7 * np.pi + 6.0 * turb))
        vein = np.clip(1.0 - line / 0.08, 0, 1) ** 1.5
        cloud = value_noise(rng, size, 4, 2)
        t = np.clip(0.85 * vein + 0.12 * cloud, 0, 1)[..., None]
        img = base * (1 - t) + second * t + 2.0 * fine[..., None]
    elif kind == "granite":
        cloud = value_noise(rng, size, 3, 3)[..., None]
        speck = (rng.random((size, size)) > 0.82).astype(np.float32)
        speck = cv2.dilate(speck, np.ones((2, 2), np.uint8))[..., None]
        light = (rng.random((size, size)) > 0.93).astype(np.float32)[..., None]
        img = base * (0.9 + 0.2 * cloud) * (1 - 0.6 * speck) + second * 0.6 * speck + 70 * light + 4 * fine[..., None]
    else:  # stone / concrete
        cloud = value_noise(rng, size, 6, 2)[..., None]
        pores = cv2.GaussianBlur((rng.random((size, size)) > 0.97).astype(np.float32), (0, 0), 0.8)[..., None]
        img = base * (0.86 + 0.28 * cloud) - 60 * pores + 3.5 * fine[..., None]
        img = img * 0.85 + second * 0.15 * (1 - cloud)
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def main() -> None:
    force = "--force" in sys.argv
    finishes = json.loads((HERE / "data" / "finishes.json").read_text(encoding="utf-8"))
    written = 0
    for f in finishes:
        path = HERE / f["swatch"]
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), draw(f["id"], f["name"], int(f["swatch_px"])))
        written += 1
    if written:
        MARKER.write_text("Swatches in this folder are drawn by make_placeholder_swatches.py, not taken from the "
                          "Kober catalogue. Run extract_kober.py on the catalogue PDF to replace them.\n")
    print(f"{written} placeholder swatches written ({len(finishes) - written} kept)")


if __name__ == "__main__":
    main()
