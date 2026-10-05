"""Offline stand-ins for the models, so the whole app runs and tests without keys.

MockDetector returns stored surfaces and objects for known sample photos
(samples/fixtures) and nothing for other photos, in which case the user places the
corners by hand.
MockSuggester picks from a fixed set by keywords; its output goes through the same
validation as Claude's.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from ..catalogue import Catalogue
from .base import Detection
from ..styles import STYLES
from .suggester import validate_suggestions

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "samples" / "fixtures"


def photo_key(image_bgr: np.ndarray) -> str:
    """64-bit difference hash: survives resizing and JPEG re-encoding of the same photo."""
    gray = cv2.cvtColor(cv2.resize(image_bgr, (9, 8), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    bits = (gray[:, 1:] > gray[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def _hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class MockDetector:
    model_id = "mock:fixtures"

    def detect(self, image_bgr: np.ndarray, objects: list[str] | None = None) -> list[Detection]:
        index = FIXTURES / "index.json"
        if not index.exists():
            return []
        key = photo_key(image_bgr)
        h, w = image_bgr.shape[:2]
        best = min(json.loads(index.read_text()).items(), key=lambda kv: _hamming(kv[0], key), default=None)
        if best is None or _hamming(best[0], key) > 6:
            return []
        entry = best[1]
        sx, sy = w / entry["width"], h / entry["height"]
        out = []
        for item in entry["surfaces"]:
            mask = cv2.imread(str(FIXTURES / item["mask"]), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
            quad = [[round(x * sx), round(y * sy)] for x, y in item["quad"]] if item.get("quad") else None
            out.append(Detection(surface_class=item["surface_class"],
                                 mask=np.where(mask > 127, 255, 0).astype(np.uint8),
                                 score=float(item.get("score", 0.9)), quad=quad))
        for item in entry.get("objects", []):
            mask = cv2.imread(str(FIXTURES / item["mask"]), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
            out.append(Detection(surface_class="object", mask=np.where(mask > 127, 255, 0).astype(np.uint8),
                                 score=float(item.get("score", 0.9)), label=item["label"]))
        return out


class MockLighting:
    """Stored lighting-model output for known sample photos (samples/fixtures); None otherwise,
    in which case the renderer estimates the light from the photo, as it does without a worker."""

    model_id = "mock:stored-marigold-iid-lighting"

    def estimate(self, image_bgr: np.ndarray) -> np.ndarray | None:
        index = FIXTURES / "index.json"
        if not index.exists():
            return None
        key = photo_key(image_bgr)
        best = min(json.loads(index.read_text()).items(), key=lambda kv: _hamming(kv[0], key), default=None)
        if best is None or _hamming(best[0], key) > 6 or not best[1].get("light"):
            return None
        path = FIXTURES / best[1]["light"]["file"]
        if not path.exists():
            return None
        return np.load(path)["shading"].astype(np.float32)


class MockDescriber:
    model_id = "mock:describer"

    def describe(self, image_bgr: np.ndarray, language: str = "en") -> dict:
        lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
        light = float(lab[:, 0].mean()) / 2.55
        return {
            "cabinets": "not analysed (offline mode)", "floor": "not analysed", "walls": "not analysed",
            "current_countertop": "not analysed", "current_backsplash": "not analysed",
            "lighting": "bright" if light > 60 else "dim", "style": "unknown", "colours": [], "objects": [],
        }


SETS = {
    "light": [
        ("estilo-caracatta", "original_q", "estilo-caracatta"),
        ("diseno-calcutta-marble", "original", "estilo-black-kandia"),
        ("diseno-white-carrara", "slim", "none"),
    ],
    "wood": [
        ("estilo-rovere-slavonia", "essence", "estilo-porfido-gesso"),
        ("estilo-mayacamas-oak", "original_q", "estilo-india-white"),
        ("estilo-olmo-mercurio", "slim", "estilo-manhattan-grey"),
    ],
    "dark": [
        ("estilo-black-kandia", "essence", "estilo-caracatta"),
        ("estilo-nero", "original_q", "estilo-nero"),
        ("estilo-porfido-nero", "original", "estilo-porfido-gesso"),
    ],
    "economy": [
        ("basik-calcutta-marble", "basik", "none"),
        ("basik-buka-bark", "basik", "none"),
        ("basik-saint-laurent-marble", "basik", "none"),
    ],
}
# One curated set per style preset (backend/app/styles.py), first option = the style board's pick.
STYLE_SETS = {
    "minimalista": [
        ("estilo-india-white", "slim", "estilo-india-white"),
        ("diseno-white-carrara", "slim", "diseno-white-carrara"),
        ("estilo-basalto-cenere", "original_q", "estilo-basalto-cenere"),
    ],
    "calido": [
        ("estilo-rovere-slavonia", "essence", "estilo-porfido-gesso"),
        ("estilo-mayacamas-oak", "original_q", "estilo-ipanema-white"),
        ("estilo-pale-lancelot-oak", "original", "diseno-luna-winter"),
    ],
    "contraste": [
        ("estilo-black-kandia", "original_q", "estilo-caracatta"),
        ("estilo-porfido-nero", "original", "estilo-white-kandia"),
        ("estilo-caracatta", "original_q", "estilo-nero"),
    ],
    "creativo": [
        ("diseno-calcatta-oro", "essence", "estilo-marquina"),
        ("diseno-portoro", "original_q", "diseno-portoro"),
        ("estilo-cracked-marble-plaster", "essence", "estilo-grey-pulpis"),
    ],
}
STYLE_ECONOMY = {
    "minimalista": [("basik-high-rise", "basik", "none")],
    "calido": [("basik-buka-bark", "basik", "none")],
    "contraste": [("basik-graphite-nebula", "basik", "none")],
    "creativo": [("basik-saint-laurent-marble", "basik", "none")],
}
KEYWORDS = {
    "light": ("blanc", "white", "marm", "marble", "claro", "light", "lumin"),
    "wood": ("mader", "wood", "calid", "warm", "natural", "roble", "oak"),
    "dark": ("negr", "black", "oscur", "dark", "elegan"),
}
TEXT = {
    "es": ("Opción {n}", "Combina {top} con {splash}; queda bien con tu cocina y es fácil de mantener."),
    "en": ("Option {n}", "Pairs {top} with {splash}; it suits your kitchen and is easy to look after."),
}


class MockSuggester:
    model_id = "mock:suggester"

    def __init__(self, cat: Catalogue) -> None:
        self.cat = cat

    def suggest(self, description: dict | None, style: str, budget: str | None, language: str) -> list[dict]:
        style_l = (style or "").lower()
        preset = next((sid for sid, s in STYLES.items() if s["brief"].lower() in style_l), None)
        if preset:
            picks = STYLE_ECONOMY[preset] + STYLE_SETS[preset][:2] if budget == "economy" else STYLE_SETS[preset]
        else:
            key = "economy" if budget == "economy" else next(
                (k for k, words in KEYWORDS.items() if any(w in style_l for w in words)), None)
            picks = SETS[key] if key else [SETS["light"][0], SETS["wood"][0], SETS["dark"][0]]
        title, reason = TEXT.get(language, TEXT["en"])
        if preset:
            title = STYLES[preset]["es" if language == "es" else "en"] + " {n}"
        designs = []
        for n, (top, profile, splash) in enumerate(picks, 1):
            splash_name = self.cat.finish(splash).name if splash != "none" else ("sin Spläsh" if language == "es" else "no Spläsh")
            designs.append({
                "title": f"{title.format(n=n)}: {self.cat.finish(top).name}",
                "countertop_finish_id": top, "profile_id": profile, "backsplash_finish_id": splash,
                "reason": reason.format(top=self.cat.finish(top).name, splash=splash_name),
            })
        return validate_suggestions({"designs": designs}, self.cat)
