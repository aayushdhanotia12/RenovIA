"""Deterministic quote engine for Kober countertops and Spläsh panels.

This is the only code that multiplies a quantity by a price. Prices come from the
catalogue read model, never from a request and never from a model's output.

Countertops are sold as whole pieces of standard lengths, so the engine:
  1. adds the waste allowance to each measured run,
  2. picks the standard width that covers the run's depth,
  3. picks the cheapest combination of standard lengths that covers the run
     (fewest pieces on a tie), counting a join between pieces,
  4. prices pieces, splash panels, labour and IVA in integer centavos.

While a quote is an estimate (no site visit yet) it carries a range. The range is
computed by re-running the whole quote with every measured length scaled down and
up by the tolerance for the capture method, so a small length error that tips a run
into the next piece size shows up in the range, as it would on the day.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import combinations_with_replacement

from .catalogue import Catalogue, CatalogueError, Finish
from .money import Money, div_round_half_up, round_outward, sum_money

TOLERANCE_BP = {"high": 200, "medium": 500, "low": 1000, "verified": 0}
RANGE_STEP_MINOR = {"high": 1000, "medium": 5000, "low": 10000, "verified": 1}
MAX_RUN_MM = 12000

TEXT = {
    "en": {
        "piece": "Countertop {finish}, {profile}, {w} x {l} mm",
        "run": "Run {run}: {length} + {pct}% allowance = {needed} -> {pieces}",
        "run_extra": "Run {run}: extra piece for the same run, joined (see above)",
        "install": "Countertop installation, {length}", "install_detail": "Charged on the measured length, without the allowance.",
        "join": "Joint between countertop pieces", "join_detail": "A run longer than the longest standard piece needs a joint.",
        "sink": "Undermount sink cut-out and fitting", "sink_detail": "Kober undermount service.",
        "panel": "Spläsh panel {finish}, {h} x {l} mm",
        "splash_run": "Run {run}: {length} x {height} high, + {pct}% = {needed} -> {rows} row(s) of {pieces}",
        "splash_install": "Spläsh installation, {area} m²", "splash_install_detail": "Charged on the measured area, without the allowance.",
        "placeholder": "Prices are placeholders, not Kober prices or your team's rates.",
        "draft": "Prices are from the team's price sheet, still in review (DRAFT).",
        "tax_confirmed": "{name} {pct}% included in the total.",
        "allowance": "{pct}% cutting allowance added to every run.",
        "tax": "{name} {pct}% (to confirm: market and whether prices are shown with {name}).",
        "inferred": "{finish}: price category not printed in the catalogue; priced as {category}.",
    },
    "es": {
        "piece": "Cubierta {finish}, perfil {profile}, {w} x {l} mm",
        "run": "Tramo {run}: {length} + {pct}% de merma = {needed} -> {pieces}",
        "run_extra": "Tramo {run}: pieza adicional del mismo tramo, con unión (ver arriba)",
        "install": "Instalación de cubierta, {length}", "install_detail": "Se cobra sobre el largo medido, sin la merma.",
        "join": "Unión entre piezas de cubierta", "join_detail": "Un tramo más largo que la pieza estándar más larga necesita una unión.",
        "sink": "Corte y submontado de tarja", "sink_detail": "Servicio de submontado Kober.",
        "panel": "Panel Spläsh {finish}, {h} x {l} mm",
        "splash_run": "Tramo {run}: {length} x {height} de alto, + {pct}% = {needed} -> {rows} fila(s) de {pieces}",
        "splash_install": "Instalación de Spläsh, {area} m²", "splash_install_detail": "Se cobra sobre el área medida, sin la merma.",
        "placeholder": "Precios de ejemplo: no son precios de Kober ni las tarifas de tu equipo.",
        "draft": "Precios de la hoja del equipo, todavía en revisión (BORRADOR).",
        "tax_confirmed": "{name} {pct}% incluido en el total.",
        "allowance": "{pct}% de merma por cortes en cada tramo.",
        "tax": "{name} {pct}% (por confirmar: mercado y si los precios se muestran con {name}).",
        "inferred": "{finish}: el catálogo no indica su categoría de precio; se cotizó como {category}.",
    },
}


class QuoteError(ValueError):
    pass


@dataclass(frozen=True)
class CountertopRun:
    run_id: str
    length_mm: int
    depth_mm: int = 645


@dataclass(frozen=True)
class SplashRun:
    run_id: str
    length_mm: int
    height_mm: int = 600


@dataclass(frozen=True)
class QuoteRequest:
    countertop_finish_id: str
    profile_id: str
    countertop_runs: tuple[CountertopRun, ...]
    splash_finish_id: str | None = None
    splash_runs: tuple[SplashRun, ...] = ()
    sinks: int = 0
    scale_confidence: str = "low"
    fulfilment_type: str = "MANAGED"
    language: str = "en"


@dataclass
class QuoteLine:
    group: str          # materials | labour
    kind: str           # countertop_piece | splash_panel | install_countertop | install_splash | sink_undermount | join
    surface: str | None  # countertop | backsplash | None
    description: str
    qty: int
    unit: str
    unit_price: Money
    total: Money
    detail: str
    finish_id: str | None = None

    def to_json(self) -> dict:
        return {
            "group": self.group, "kind": self.kind, "surface": self.surface, "description": self.description,
            "qty": self.qty, "unit": self.unit, "unit_price": self.unit_price.to_json(),
            "total": self.total.to_json(), "detail": self.detail, "finish_id": self.finish_id,
        }


@dataclass
class Quote:
    currency: str
    lines: list[QuoteLine]
    materials: Money
    labour: Money
    subtotal: Money
    tax: Money
    tax_rate_bp: int
    total: Money
    estimate_low: Money
    estimate_high: Money
    booking_fee: Money
    scale_confidence: str
    estimate_only: bool
    price_list_status: str
    assumptions: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "currency": self.currency,
            "lines": [ln.to_json() for ln in self.lines],
            "materials": self.materials.to_json(), "labour": self.labour.to_json(),
            "subtotal": self.subtotal.to_json(), "tax": self.tax.to_json(), "tax_rate_bp": self.tax_rate_bp,
            "total": self.total.to_json(),
            "estimate": {"low": self.estimate_low.to_json(), "high": self.estimate_high.to_json()},
            "booking_fee": self.booking_fee.to_json(),
            "balance": {
                "low": (self.estimate_low - self.booking_fee).to_json(),
                "high": (self.estimate_high - self.booking_fee).to_json(),
            },
            "scale_confidence": self.scale_confidence, "estimate_only": self.estimate_only,
            "price_list_status": self.price_list_status, "assumptions": self.assumptions,
        }


def choose_pieces(required_mm: int, lengths: list[int], max_pieces: int = 4) -> tuple[int, ...]:
    """Cheapest set of standard lengths covering required_mm: least total length,
    then fewest pieces, then the longest single piece (joins away from the middle)."""
    options = sorted(set(lengths))
    best: tuple[tuple[int, int, int], tuple[int, ...]] | None = None
    for n in range(1, max_pieces + 1):
        for combo in combinations_with_replacement(options, n):
            total = sum(combo)
            if total < required_mm:
                continue
            key = (total, n, -max(combo))
            if best is None or key < best[0]:
                best = (key, combo)
    if best is None:
        raise QuoteError(f"{required_mm} mm needs more than {max_pieces} pieces")
    return tuple(sorted(best[1], reverse=True))


def _with_allowance(length_mm: int, waste_bp: int) -> int:
    return div_round_half_up(length_mm * (10000 + waste_bp), 10000)


def _fmt_m(mm: int) -> str:
    cm = div_round_half_up(mm, 10)
    return f"{cm // 100}.{cm % 100:02d} m"


def _fmt_m2(mm2: int) -> str:
    hundredths = div_round_half_up(mm2, 10_000)
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def _width_factor_bp(prices: dict, width_mm: int) -> int:
    for band in prices["width_factor_bp"]:
        if width_mm <= band["max_width_mm"]:
            return band["factor_bp"]
    raise QuoteError(f"no width price band for {width_mm} mm")


def _piece_price(prices: dict, cur: str, top: Finish, width: int, length: int, profile_id: str) -> Money:
    """One countertop piece, before tax.

    With the team's price sheet imported, the price is Kober's cost for that exact piece
    (category x width x length, quoted in Original Q), times the profile's factor against
    Original Q, plus the category's margin. Without it (the placeholder list), a price per
    metre is scaled by the piece's length and width band."""
    table = prices.get("countertop_piece_minor")
    profile_bp = prices["profile_factor_bp"][profile_id]
    if table is not None:
        cost = table.get(top.category, {}).get(f"{width}x{length}")
        if cost is None:
            raise QuoteError(f"the price sheet has no {top.category} countertop piece of {width} x {length} mm")
        margin = prices.get("margin_bp", {}).get("countertop", {}).get(top.category, 0)
        return Money(div_round_half_up(cost * profile_bp * (10000 + margin), 10000 * 10000), cur)
    per_m = prices["countertop_per_metre_minor"][top.category]
    wf = _width_factor_bp(prices, width)
    return Money(div_round_half_up(per_m * length * wf * profile_bp, 1000 * 10000 * 10000), cur)


def _panel_price(prices: dict, cur: str, splash: Finish, height: int, length: int) -> Money:
    """One Spläsh panel, before tax: the sheet's cost for that panel plus margin, else a price per m²."""
    table = prices.get("splash_panel_minor")
    if table is not None:
        cost = table.get(splash.category, {}).get(f"{height}x{length}")
        if cost is None:
            raise QuoteError(f"the price sheet has no {splash.category} Spläsh panel of {height} x {length} mm")
        margin = prices.get("margin_bp", {}).get("splash", {}).get(splash.category, 0)
        return Money(div_round_half_up(cost * (10000 + margin), 10000), cur)
    return Money(div_round_half_up(prices["splash_per_m2_minor"][splash.category] * height * length, 1_000_000), cur)


def _validate(req: QuoteRequest) -> None:
    if req.scale_confidence not in TOLERANCE_BP:
        raise QuoteError(f"scale_confidence must be one of {sorted(TOLERANCE_BP)}; got {req.scale_confidence!r}")
    if not req.countertop_runs:
        raise QuoteError("at least one countertop run is required")
    for run in (*req.countertop_runs, *req.splash_runs):
        if isinstance(run.length_mm, bool) or not isinstance(run.length_mm, int):
            raise QuoteError(f"run {run.run_id}: length_mm must be an integer number of millimetres")
        if not 100 <= run.length_mm <= MAX_RUN_MM:
            raise QuoteError(f"run {run.run_id}: length {run.length_mm} mm is outside 100-{MAX_RUN_MM} mm")
    for run in req.countertop_runs:
        if isinstance(run.depth_mm, bool) or not isinstance(run.depth_mm, int) or not 300 <= run.depth_mm <= 1000:
            raise QuoteError(f"run {run.run_id}: depth must be an integer between 300 and 1000 mm")
    for run in req.splash_runs:
        if isinstance(run.height_mm, bool) or not isinstance(run.height_mm, int) or not 50 <= run.height_mm <= 2400:
            raise QuoteError(f"splash {run.run_id}: height must be an integer between 50 and 2400 mm")
    if req.splash_runs and not req.splash_finish_id:
        raise QuoteError("splash runs given without a splash finish")
    if isinstance(req.sinks, bool) or not isinstance(req.sinks, int) or not 0 <= req.sinks <= 4:
        raise QuoteError("sinks must be an integer from 0 to 4")


def _price_lines(req: QuoteRequest, cat: Catalogue) -> tuple[list[QuoteLine], list[str]]:
    prices, cur = cat.prices, cat.currency
    tx = TEXT.get(req.language, TEXT["en"])
    notes: list[str] = []
    try:
        top = cat.finish(req.countertop_finish_id)
        cat.check_profile(top, req.profile_id)
        splash: Finish | None = cat.finish(req.splash_finish_id) if req.splash_finish_id else None
    except CatalogueError as e:
        raise QuoteError(str(e)) from None

    lines: list[QuoteLine] = []
    waste_top = prices["waste_allowance_bp"]["countertop"]
    waste_splash = prices["waste_allowance_bp"]["splash"]
    profile_name = cat.profile(req.profile_id)["name"]
    if top.category_inferred:
        notes.append(tx["inferred"].format(finish=top.name, category=top.category))

    piece_counts: Counter[tuple[int, int]] = Counter()
    piece_detail: dict[tuple[int, int], list[str]] = {}
    joins = 0
    install_mm = 0
    for run in req.countertop_runs:
        width = cat.countertop_width(run.depth_mm)
        needed = _with_allowance(run.length_mm, waste_top)
        pieces = choose_pieces(needed, cat.countertop_lengths(top, width, req.profile_id))
        joins += len(pieces) - 1
        install_mm += run.length_mm
        detail = tx["run"].format(run=run.run_id, length=_fmt_m(run.length_mm), pct=f"{waste_top / 100:g}",
                                  needed=_fmt_m(needed), pieces=" + ".join(_fmt_m(p) for p in pieces))
        for length in pieces:
            piece_counts[(width, length)] += 1
            # The run's arithmetic goes on its longest piece; other sizes in the same run point back to it.
            text = detail if length == pieces[0] else tx["run_extra"].format(run=run.run_id)
            if text not in piece_detail.setdefault((width, length), []):
                piece_detail[(width, length)].append(text)

    # Longest piece first within each width, so a run's explanation comes before its extra pieces.
    for (width, length), qty in sorted(piece_counts.items(), key=lambda kv: (kv[0][0], -kv[0][1])):
        unit = _piece_price(prices, cur, top, width, length, req.profile_id)
        lines.append(QuoteLine(
            group="materials", kind="countertop_piece", surface="countertop",
            description=tx["piece"].format(finish=top.name, profile=profile_name, w=width, l=length),
            qty=qty, unit="piece", unit_price=unit, total=unit.times(qty),
            detail="; ".join(piece_detail[(width, length)]), finish_id=top.id,
        ))

    labour = prices["labour_minor"]
    lines.append(QuoteLine(
        group="labour", kind="install_countertop", surface="countertop",
        description=tx["install"].format(length=_fmt_m(install_mm)),
        qty=1, unit="job", unit_price=Money(div_round_half_up(labour["countertop_install_per_metre"] * install_mm, 1000), cur),
        total=Money(div_round_half_up(labour["countertop_install_per_metre"] * install_mm, 1000), cur),
        detail=tx["install_detail"],
    ))
    if joins:
        unit = Money(labour["join_each"], cur)
        lines.append(QuoteLine(
            group="labour", kind="join", surface="countertop", description=tx["join"],
            qty=joins, unit="joint", unit_price=unit, total=unit.times(joins), detail=tx["join_detail"],
        ))
    if req.sinks:
        unit = Money(labour["sink_undermount_each"], cur)
        lines.append(QuoteLine(
            group="labour", kind="sink_undermount", surface="countertop", description=tx["sink"],
            qty=req.sinks, unit="sink", unit_price=unit, total=unit.times(req.sinks), detail=tx["sink_detail"],
        ))

    if splash is not None and req.splash_runs:
        if splash.category_inferred and splash.id != top.id:
            notes.append(tx["inferred"].format(finish=splash.name, category=splash.category))
        heights = sorted(cat.splash_heights())
        panel_counts: Counter[tuple[int, int]] = Counter()
        panel_detail: dict[tuple[int, int], list[str]] = {}
        area_mm2 = 0
        for run in req.splash_runs:
            panel_h = next((h for h in heights if h >= run.height_mm), heights[-1])
            rows = -(-run.height_mm // panel_h)
            needed = _with_allowance(run.length_mm, waste_splash)
            pieces = choose_pieces(needed, cat.splash_lengths())
            area_mm2 += run.length_mm * run.height_mm
            detail = tx["splash_run"].format(run=run.run_id, length=_fmt_m(run.length_mm), height=_fmt_m(run.height_mm),
                                             pct=f"{waste_splash / 100:g}", needed=_fmt_m(needed), rows=rows,
                                             pieces=" + ".join(_fmt_m(p) for p in pieces))
            for length in pieces:
                panel_counts[(panel_h, length)] += rows
                text = detail if length == pieces[0] else tx["run_extra"].format(run=run.run_id)
                if text not in panel_detail.setdefault((panel_h, length), []):
                    panel_detail[(panel_h, length)].append(text)
        for (h, length), qty in sorted(panel_counts.items(), key=lambda kv: (kv[0][0], -kv[0][1])):
            unit = _panel_price(prices, cur, splash, h, length)
            lines.append(QuoteLine(
                group="materials", kind="splash_panel", surface="backsplash",
                description=tx["panel"].format(finish=splash.name, h=h, l=length),
                qty=qty, unit="panel", unit_price=unit, total=unit.times(qty),
                detail="; ".join(panel_detail[(h, length)]), finish_id=splash.id,
            ))
        install = Money(div_round_half_up(labour["splash_install_per_m2"] * area_mm2, 1_000_000), cur)
        lines.append(QuoteLine(
            group="labour", kind="install_splash", surface="backsplash",
            description=tx["splash_install"].format(area=_fmt_m2(area_mm2)),
            qty=1, unit="job", unit_price=install, total=install, detail=tx["splash_install_detail"],
        ))
    return lines, notes


def _totals(lines: list[QuoteLine], cat: Catalogue) -> tuple[Money, Money, Money, Money, Money]:
    cur = cat.currency
    materials = sum_money([ln.total for ln in lines if ln.group == "materials"], cur)
    labour = sum_money([ln.total for ln in lines if ln.group == "labour"], cur)
    subtotal = materials + labour
    tax = subtotal.mul_ratio(cat.prices["tax"]["rate_bp"], 10000)
    return materials, labour, subtotal, tax, subtotal + tax


def _scaled(req: QuoteRequest, ratio_bp: int) -> QuoteRequest:
    def s(mm: int) -> int:
        return max(100, div_round_half_up(mm * ratio_bp, 10000))
    return replace(
        req,
        countertop_runs=tuple(replace(r, length_mm=s(r.length_mm)) for r in req.countertop_runs),
        splash_runs=tuple(replace(r, length_mm=s(r.length_mm), height_mm=max(50, s(r.height_mm))) for r in req.splash_runs),
    )


def price_quote(req: QuoteRequest, cat: Catalogue, final: bool = False) -> Quote:
    """Price a design. `final=True` is used only after a site visit with verified measurements."""
    _validate(req)
    confidence = "verified" if final else req.scale_confidence
    lines, notes = _price_lines(req, cat)
    materials, labour, subtotal, tax, total = _totals(lines, cat)

    tol = TOLERANCE_BP[confidence]
    if tol:
        lo_total = _totals(_price_lines(_scaled(req, 10000 - tol), cat)[0], cat)[4]
        hi_total = _totals(_price_lines(_scaled(req, 10000 + tol), cat)[0], cat)[4]
        low = min(lo_total, total, key=lambda m: m.minor)
        high = max(hi_total, total, key=lambda m: m.minor)
        low, high = round_outward(low, high, RANGE_STEP_MINOR[confidence])
    else:
        low = high = total

    fee = Money(cat.prices["booking_fee_minor"][req.fulfilment_type], cat.currency)
    tx = TEXT.get(req.language, TEXT["en"])
    assumptions = list(notes)
    if cat.price_status != "LIVE":
        assumptions.insert(0, tx["draft"] if cat.price_status == "DRAFT" else tx["placeholder"])
    assumptions.append(tx["allowance"].format(pct=f"{cat.prices['waste_allowance_bp']['countertop'] / 100:g}"))
    tax_rule = cat.prices["tax"]
    assumptions.append(tx["tax_confirmed" if tax_rule.get("confirmed") else "tax"].format(
        name=tax_rule["name"], pct=f"{tax_rule['rate_bp'] / 100:g}"))
    return Quote(
        currency=cat.currency, lines=lines, materials=materials, labour=labour, subtotal=subtotal,
        tax=tax, tax_rate_bp=cat.prices["tax"]["rate_bp"], total=total, estimate_low=low, estimate_high=high,
        booking_fee=fee, scale_confidence=confidence, estimate_only=not final,
        price_list_status=cat.price_status, assumptions=assumptions,
    )
