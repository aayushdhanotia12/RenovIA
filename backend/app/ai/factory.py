"""Choose model adapters from settings. `RENOVAI_AI_MODE=mock` runs fully offline."""

from __future__ import annotations

from dataclasses import dataclass

from ..catalogue import Catalogue
from ..config import Settings
from .anthropic_client import AnthropicClient
from .base import FinishSuggester, KitchenDescriber, ModelError, SurfaceDetector
from .fal_sam3 import FalSam3Detector
from .mock import MockDescriber, MockDetector, MockSuggester
from .suggester import ClaudeDescriber, ClaudeSuggester


@dataclass
class Models:
    detector: SurfaceDetector
    describer: KitchenDescriber
    suggester: FinishSuggester

    def versions(self) -> dict:
        return {"detector": self.detector.model_id, "describer": self.describer.model_id,
                "suggester": self.suggester.model_id}


def build_models(settings: Settings, cat: Catalogue) -> Models:
    if settings.ai_mode == "mock":
        return Models(MockDetector(), MockDescriber(), MockSuggester(cat))
    missing = [name for name, value in (("FAL_KEY", settings.fal_key), ("ANTHROPIC_API_KEY", settings.anthropic_api_key))
               if not value]
    if missing:
        raise ModelError(f"RENOVAI_AI_MODE=live needs {', '.join(missing)} (see .env.example)")
    claude = AnthropicClient(settings.anthropic_api_key, settings.anthropic_model, settings.anthropic_base_url,
                             effort=settings.anthropic_effort)
    detector = FalSam3Detector(settings.fal_key, settings.fal_base_url, settings.sam3_endpoint, settings.sam3_min_score)
    return Models(detector, ClaudeDescriber(claude), ClaudeSuggester(claude, cat))
