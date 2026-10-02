"""Finish suggestions: the design agent.

Claude receives the whole Kober finish list (about 80 lines, small enough that no
search index is needed) plus a description of the customer's kitchen, and answers in
JSON constrained by a schema (structured outputs) that only allows catalogue finish
ids. The schema has no price, total or currency field, so the model cannot state a
price. Every answer is validated again here before anything uses it; ids are compared
case-insensitively because structured outputs do not guarantee enum capitalisation.
"""

from __future__ import annotations

import json

import numpy as np

from ..catalogue import Catalogue, CatalogueError
from .anthropic_client import AnthropicClient
from .base import ModelError

ALLOWED_KEYS = {"title", "countertop_finish_id", "profile_id", "backsplash_finish_id", "reason"}
LANGUAGES = {"es": "Mexican Spanish", "en": "English"}


def suggestion_schema(cat: Catalogue) -> dict:
    ids = sorted(cat.finishes)
    return {
        "type": "object", "additionalProperties": False, "required": ["designs"],
        "properties": {"designs": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": {
                "type": "object", "additionalProperties": False, "required": sorted(ALLOWED_KEYS),
                "properties": {
                    "title": {"type": "string", "maxLength": 48},
                    "countertop_finish_id": {"type": "string", "enum": ids},
                    "profile_id": {"type": "string", "enum": sorted(cat.profiles)},
                    "backsplash_finish_id": {"type": "string", "enum": ids + ["none"]},
                    "reason": {"type": "string", "maxLength": 280},
                },
            },
        }},
    }


def validate_suggestions(raw: object, cat: Catalogue) -> list[dict]:
    """Keep only well-formed suggestions that the catalogue can actually make."""
    if not isinstance(raw, dict) or not isinstance(raw.get("designs"), list):
        raise ModelError("suggestions must be an object with a designs list")
    clean: list[dict] = []
    for d in raw["designs"]:
        if not isinstance(d, dict) or set(d) - ALLOWED_KEYS:
            continue  # extra keys (a price, a total) mean the answer is not trusted
        try:
            top = cat.finish(_id(d["countertop_finish_id"]))
            profile_id = _id(d["profile_id"])
            cat.check_profile(top, profile_id)
            splash_id = _id(d.get("backsplash_finish_id"))
            splash = None if splash_id in ("", "none") else cat.finish(splash_id).id
        except (CatalogueError, KeyError):
            continue
        if not cat.available(top.id) or (splash and not cat.available(splash)):
            continue  # the team marked it out of stock in the price sheet
        clean.append({
            "title": str(d.get("title", ""))[:48].strip() or top.name,
            "countertop_finish_id": top.id, "profile_id": profile_id,
            "backsplash_finish_id": splash, "reason": str(d.get("reason", ""))[:280].strip(),
        })
    if not clean:
        raise ModelError("no usable suggestions")
    return clean[:3]


def _id(value: object) -> str:
    return "" if value is None else str(value).strip().lower()


def _system(language: str) -> str:
    return (
        "You are a kitchen designer for a countertop installer that sells only Kober products. "
        "Propose exactly three combinations of countertop finish, edge profile and Spläsh backsplash finish "
        "for the customer's kitchen, using only ids from the catalogue list. Never mention prices, totals, "
        "discounts or currency; pricing is done by other software. Rules: finishes of line 'basik' use only "
        "profile 'basik'; other finishes use 'slim', 'original', 'original_q' or 'essence'; Porfido Nero is not "
        "made in 'slim'. The backsplash may match the countertop, contrast with it, or be 'none'. Suit the "
        "existing cabinets, floor and walls. Budget 'economy' favours categories basik and estandar, 'mid' "
        "estandar and premium, 'premium' premium_plus. Make the three options clearly different from each other. "
        f"Write title and reason in {LANGUAGES.get(language, 'English')}; the reason is one or two sentences "
        "telling the customer why it suits their kitchen."
    )


class ClaudeSuggester:
    def __init__(self, client: AnthropicClient, cat: Catalogue) -> None:
        self.client, self.cat = client, cat
        self.model_id = f"anthropic:{client.model}"

    def suggest(self, description: dict | None, style: str, budget: str | None, language: str) -> list[dict]:
        text = (
            f"Kitchen description: {json.dumps(description or {}, ensure_ascii=False)}\n"
            f"Customer's style request: {style or 'no preference'}\n"
            f"Budget: {budget or 'not given'}\n\n"
            "Catalogue (id | name | line | category | tags):\n" + self.cat.compact_listing()
        )
        raw = self.client.json_call(
            system=_system(language), content=[{"type": "text", "text": text}],
            schema=suggestion_schema(self.cat), max_tokens=4000,
        )
        return validate_suggestions(raw, self.cat)


DESCRIBE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["cabinets", "floor", "walls", "current_countertop", "current_backsplash", "lighting", "style", "colours"],
    "properties": {
        "cabinets": {"type": "string", "maxLength": 140},
        "floor": {"type": "string", "maxLength": 140},
        "walls": {"type": "string", "maxLength": 140},
        "current_countertop": {"type": "string", "maxLength": 140},
        "current_backsplash": {"type": "string", "maxLength": 140},
        "lighting": {"type": "string", "maxLength": 140},
        "style": {"type": "string", "maxLength": 140},
        "colours": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 30}},
    },
}


class ClaudeDescriber:
    def __init__(self, client: AnthropicClient) -> None:
        self.client = client
        self.model_id = f"anthropic:{client.model}"

    def describe(self, image_bgr: np.ndarray, language: str = "en") -> dict:
        from .anthropic_client import image_block
        out = self.client.json_call(
            system="You describe kitchen photos for a countertop designer. Be factual and brief. Say 'not visible' "
                   "when you cannot see something.",
            content=[image_block(image_bgr), {"type": "text", "text": "Describe this kitchen."}],
            schema=DESCRIBE_SCHEMA, max_tokens=2000,
        )
        return {k: out.get(k) for k in DESCRIBE_SCHEMA["properties"]}
