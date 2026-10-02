"""The four design styles a customer can ask for, or see side by side.

Each style has customer-facing names in Spanish and English, and a brief for Claude.
The brief only steers the choice of finishes; validation against the catalogue and
pricing work exactly as for a free-text request.
"""

from __future__ import annotations

STYLE_IDS = ("minimalista", "calido", "contraste", "creativo")

STYLES: dict[str, dict[str, str]] = {
    "minimalista": {
        "es": "Minimalista", "en": "Minimalist",
        "blurb_es": "Claro y sereno: cubierta y salpicadero iguales o casi iguales.",
        "blurb_en": "Light and calm: countertop and backsplash the same or nearly the same.",
        "brief": "Minimalist: light, quiet colours; the backsplash matches or is very close to the countertop; "
                 "no strong pattern; clean and calm.",
    },
    "calido": {
        "es": "Cálido natural", "en": "Warm natural",
        "blurb_es": "Madera o piedra cálida con un salpicadero neutro y suave.",
        "blurb_en": "Wood or warm stone with a soft, neutral backsplash.",
        "brief": "Warm natural: a wood-look or warm stone countertop with a soft, neutral backsplash; cosy and "
                 "inviting.",
    },
    "contraste": {
        "es": "Contraste", "en": "Bold contrast",
        "blurb_es": "Oscuro contra claro: una cocina con carácter.",
        "blurb_en": "Dark against light: a kitchen with character.",
        "brief": "Bold contrast: a dark countertop with a light backsplash, or a light countertop with a dark "
                 "backsplash; crisp and graphic.",
    },
    "creativo": {
        "es": "Creativo", "en": "Statement",
        "blurb_es": "Un mármol o un patrón protagonista, sin perder lo práctico.",
        "blurb_en": "One striking marble or pattern as the hero, still practical.",
        "brief": "Creative statement: one striking marble or strongly patterned finish as the hero of the "
                 "kitchen, balanced so it stays livable.",
    },
}


def brief_for(style_id: str | None, free_text: str = "") -> str:
    """What the suggester is asked for: the style's brief, plus anything the customer typed."""
    parts = []
    if style_id:
        parts.append(STYLES[style_id]["brief"])
    if free_text.strip():
        parts.append(f"The customer adds: {free_text.strip()}")
    return " ".join(parts)


def public_styles() -> list[dict]:
    return [{"id": sid, "name": {"es": s["es"], "en": s["en"]}, "blurb": {"es": s["blurb_es"], "en": s["blurb_en"]}}
            for sid, s in STYLES.items()]
