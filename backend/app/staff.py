"""The field team's side: signed media links, the visit record and the final quote.

When someone from the team measures a kitchen, their lengths replace the customer's and
the quote is priced again with `final=True`: one figure, no range. The difference between
what the customer typed and what the team measured is kept for every run, because it is
the only honest measure of how good typed measurements are (MEASUREMENT.md), and whether
the final price landed inside the range the customer was shown.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time

from .catalogue import Catalogue
from .money import div_round_half_up
from .pipeline import quote_request
from .quote import price_quote

MEDIA_KINDS = ("photo", "render")
LINK_TTL_S = 12 * 3600


def media_signature(secret: str, bid: str, kind: str, expires: int) -> str:
    return hmac.new(secret.encode(), f"{bid}:{kind}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def signed_media_url(secret: str, bid: str, kind: str, now: float | None = None) -> str:
    """A photo or render link the staff page can put in an <img>, without the team key in the URL."""
    expires = int((now or time.time()) + LINK_TTL_S)
    return f"/api/staff/media/{bid}/{kind}?exp={expires}&sig={media_signature(secret, bid, kind, expires)}"


def media_ok(secret: str, bid: str, kind: str, exp: str, sig: str) -> bool:
    if kind not in MEDIA_KINDS or not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(media_signature(secret, bid, kind, int(exp)), sig)


def whatsapp_number(phone: str, default_country: str = "52") -> str | None:
    """Digits for a wa.me link: a 10-digit Mexican number gets +52; anything else must carry its code."""
    digits = re.sub(r"\D", "", phone or "")
    if phone.strip().startswith("+") or phone.strip().startswith("00"):
        digits = digits[2:] if phone.strip().startswith("00") else digits
        return digits if 8 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return default_country + digits
    return digits if 11 <= len(digits) <= 15 else None


def _differences(customer: list[dict], team: list[dict], size_key: str) -> list[dict]:
    """Signed difference per run, team minus customer, in mm and in basis points of the team's length."""
    typed = {r["run_id"]: r for r in customer}
    out = []
    for r in team:
        c = typed.get(r["run_id"])
        row = {"run_id": r["run_id"], "team_mm": r["length_mm"], "customer_mm": c["length_mm"] if c else None}
        if c:
            diff = r["length_mm"] - c["length_mm"]
            row.update(diff_mm=diff, diff_bp=div_round_half_up(diff * 10000, r["length_mm"]))
            row[f"team_{size_key}"] = r.get(size_key)
            row[f"customer_{size_key}"] = c.get(size_key)
        out.append(row)
    return out


def visit_result(visit: dict, customer: dict, choice: dict, estimate: dict, cat: Catalogue, language: str) -> dict:
    """The verified record and the final quote for one visit.

    `visit` holds the team's runs (integer mm), `customer` the project's typed measurements,
    `choice` the design's finishes, and `estimate` the range the customer was shown."""
    team = {"countertop_runs": visit["countertop_runs"], "splash_runs": visit.get("splash_runs", []),
            "sinks": visit["sinks"], "scale_confidence": "verified"}
    final = price_quote(quote_request(team, {**choice, "language": language}, cat), cat, final=True).to_json()
    low, high = estimate["low"]["minor"], estimate["high"]["minor"]
    total = final["total"]["minor"]
    verified = {
        **{k: team[k] for k in ("countertop_runs", "splash_runs", "sinks")},
        "tool": visit.get("tool"), "measured_by": visit.get("measured_by"), "notes": visit.get("notes"),
        "at": time.time(),
        "differences": {
            "countertop": _differences(customer.get("countertop_runs", []), team["countertop_runs"], "depth_mm"),
            "backsplash": _differences(customer.get("splash_runs", []), team["splash_runs"], "height_mm"),
        },
        "estimate": estimate, "final_total": final["total"],
        "within_range": low <= total <= high,
        "vs_estimate_minor": 0 if low <= total <= high else (total - high if total > high else total - low),
    }
    return {"verified": verified, "final_quote": final}
