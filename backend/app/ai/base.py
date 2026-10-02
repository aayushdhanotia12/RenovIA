"""Model adapter interfaces. Swap hosted APIs for self-hosted open-source models by
writing a new adapter; nothing else in the app changes.

None of these interfaces can return a price: detectors return pixels, the describer
returns words, and the suggester returns finish ids that the catalogue validates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class Detection:
    surface_class: str   # countertop | backsplash
    mask: np.ndarray     # uint8 HxW, 255 inside
    score: float
    quad: list | None = None  # plane corners when the detector knows them (fixtures); else fitted from the mask


class SurfaceDetector(Protocol):
    model_id: str

    def detect(self, image_bgr: np.ndarray) -> list[Detection]: ...


class KitchenDescriber(Protocol):
    model_id: str

    def describe(self, image_bgr: np.ndarray, language: str) -> dict: ...


class FinishSuggester(Protocol):
    model_id: str

    def suggest(self, description: dict | None, style: str, budget: str | None, language: str) -> list[dict]: ...


class ModelError(RuntimeError):
    """A model call failed or returned something unusable. Retry or fall back."""
