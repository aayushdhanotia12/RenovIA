"""The team's price & rules sheet: make the template, then import it into prices.json.

    python catalog/kober/price_sheet.py template catalog/kober/precios_renovai.xlsx
    python catalog/kober/price_sheet.py import  catalog/kober/precios_renovai.xlsx
    python catalog/kober/price_sheet.py import  "https://docs.google.com/spreadsheets/d/<id>/edit"
    python catalog/kober/price_sheet.py import  path/to/folder-of-csv-exports/

The sheet is where the business answers live: Kober's cost for every countertop piece
and Spläsh panel, the edge-profile factors, the margin per category, labour, booking
fees, IVA, the cutting allowance, each finish's price category and whether it is
available. Upload the template to Google Drive as a Google Sheet, let the team fill it,
share it as "anyone with the link can view", and import it by URL; or download it as
.xlsx and import the file.

Importing never guesses. Every amount is read as a decimal string and turned into whole
centavos; a missing piece size, an unknown category or an unreadable number stops the
import with a list of what to fix, and the previous prices.json stays in place. The
quote engine (backend/app/quote.py) does all the arithmetic with the tables written here;
nothing in this file multiplies a price.

Status: the sheet says BORRADOR (draft) or VIGENTE (live). Every quote from a draft sheet
says "prices in review"; only a VIGENTE sheet with every margin set produces a clean quote.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.catalogue import Catalogue  # noqa: E402
from backend.app.money import div_round_half_up  # noqa: E402

OUT = HERE / "data" / "prices.json"
PLACEHOLDER = HERE / "data" / "prices.placeholder.json"

TABS = ("Ajustes", "Cubiertas", "Perfiles", "Splash", "Margenes", "ManoDeObra", "Acabados")
CATEGORIES = ("basik", "estandar", "premium", "premium_plus")
PROFILES = ("slim", "original", "original_q", "essence", "basik")
LABOUR = {
    "instalacion_cubierta_por_m": ("countertop_install_per_metre", "por metro lineal medido"),
    "instalacion_splash_por_m2": ("splash_install_per_m2", "por m² medido"),
    "tarja_submontada": ("sink_undermount_each", "por tarja"),
    "union": ("join_each", "por unión entre piezas"),
}
STATUS = {"borrador": "DRAFT", "draft": "DRAFT", "vigente": "LIVE", "live": "LIVE"}
YES = {"si", "sí", "yes", "y", "1", "true", "x"}
NO = {"no", "n", "0", "false", ""}


class SheetError(ValueError):
    pass


# --- reading ---------------------------------------------------------------------

def _norm(text: object) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().strip().lower()
    return re.sub(r"[^a-z0-9%_]+", "_", s).strip("_")


def _rows_from_xlsx(path: Path) -> dict[str, list[dict]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=False)
    out: dict[str, list[dict]] = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows())
        if not rows:
            continue
        header = [_norm(c.value) for c in rows[0]]
        table = []
        for row in rows[1:]:
            rec = {}
            for h, cell in zip(header, row):
                if not h:
                    continue
                value = cell.value
                if isinstance(value, (int, float)) and not isinstance(value, bool) and "%" in (cell.number_format or ""):
                    value = f"{Decimal(str(value)) * 100}%"  # a cell formatted as 16% holds 0.16
                rec[h] = "" if value is None else str(value).strip()
            if any(rec.values()):
                table.append(rec)
        out[ws.title.strip()] = table
    return out


def _rows_from_csv_text(text: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader]
    if not rows:
        return []
    header = [_norm(h) for h in rows[0]]
    table = []
    for row in rows[1:]:
        rec = {h: (v or "").strip() for h, v in zip(header, row) if h}
        if any(rec.values()):
            table.append(rec)
    return table


def _rows_from_folder(folder: Path) -> dict[str, list[dict]]:
    out = {}
    for tab in TABS:
        hits = [p for p in folder.glob("*.csv") if _norm(p.stem).endswith(_norm(tab))]
        if hits:
            out[tab] = _rows_from_csv_text(hits[0].read_text(encoding="utf-8-sig"))
    return out


def _rows_from_google(url: str) -> dict[str, list[dict]]:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not m:
        raise SheetError("not a Google Sheets link")
    out = {}
    for tab in TABS:
        csv_url = (f"https://docs.google.com/spreadsheets/d/{m.group(1)}/gviz/tq?tqx=out:csv&sheet="
                   + urllib.parse.quote(tab))
        req = urllib.request.Request(csv_url, headers={"User-Agent": "RenovAI price import"})
        try:
            text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            raise SheetError(f"could not read tab {tab} ({e}); is the sheet shared as 'anyone with the link'?") from None
        out[tab] = _rows_from_csv_text(text)
    return out


def read_sheet(source: str) -> dict[str, list[dict]]:
    if source.startswith("http"):
        return _rows_from_google(source)
    path = Path(source)
    if path.is_dir():
        return _rows_from_folder(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return _rows_from_xlsx(path)
    raise SheetError(f"{source}: expected an .xlsx file, a folder of CSV exports or a Google Sheets link")


# --- parsing values --------------------------------------------------------------

def _decimal(raw: str, where: str, errors: list[str]) -> Decimal | None:
    s = str(raw).strip().replace("$", "").replace("MXN", "").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):  # 5,670.00
        s = s.replace(",", "")
    elif re.fullmatch(r"-?\d+,\d{1,2}", s):  # 5670,50
        s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation:
        errors.append(f"{where}: '{raw}' is not a number")
        return None
    if value < 0:
        errors.append(f"{where}: '{raw}' is negative")
        return None
    return value


def money_minor(raw: str, where: str, errors: list[str]) -> int | None:
    """'5,670.50' -> 567050 centavos, never through a float."""
    if str(raw).strip() == "":
        errors.append(f"{where}: empty")
        return None
    value = _decimal(raw, where, errors)
    return None if value is None else int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def percent_bp(raw: str, where: str, errors: list[str], max_pct: int = 300) -> int | None:
    """'16', '16%' or a cell formatted as 16% -> 1600 basis points."""
    s = str(raw).strip().rstrip("%").strip()
    if s == "":
        errors.append(f"{where}: empty")
        return None
    value = _decimal(s, where, errors)
    if value is None:
        return None
    if value > max_pct:
        errors.append(f"{where}: {raw} is more than {max_pct}%")
        return None
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def whole_mm(raw: str, where: str, errors: list[str]) -> int | None:
    s = str(raw).strip()
    if re.fullmatch(r"\d+(\.0+)?", s):
        return int(Decimal(s))
    errors.append(f"{where}: '{raw}' must be whole millimetres")
    return None


def yes_no(raw: str, where: str, errors: list[str]) -> bool | None:
    s = _norm(raw)
    if s in YES:
        return True
    if s in NO:
        return False
    errors.append(f"{where}: '{raw}' must be si or no")
    return None


# --- import -----------------------------------------------------------------------

def build_prices(tabs: dict[str, list[dict]], cat: Catalogue, source: str) -> tuple[dict, list[str]]:
    """prices.json content from the sheet's tabs, or SheetError listing everything to fix."""
    errors: list[str] = []
    warnings: list[str] = []
    missing = [t for t in TABS if t not in tabs]
    if missing:
        raise SheetError("missing tabs: " + ", ".join(missing))

    settings = {_norm(r.get("clave")): r.get("valor", "") for r in tabs["Ajustes"] if r.get("clave")}

    def setting(key: str) -> str:
        if key not in settings:
            errors.append(f"Ajustes: no row '{key}'")
            return ""
        return settings[key]

    status = STATUS.get(_norm(setting("estado")))
    if status is None:
        errors.append(f"Ajustes estado: '{settings.get('estado')}' must be BORRADOR or VIGENTE")
    currency = setting("moneda").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        errors.append(f"Ajustes moneda: '{currency}' must be a 3-letter code such as MXN")
    tax_bp = percent_bp(setting("iva_%"), "Ajustes iva_%", errors, max_pct=50)
    includes_tax = yes_no(setting("precios_incluyen_iva"), "Ajustes precios_incluyen_iva", errors)
    tax_confirmed = yes_no(setting("iva_confirmado"), "Ajustes iva_confirmado", errors)
    waste_top = percent_bp(setting("merma_cubierta_%"), "Ajustes merma_cubierta_%", errors, max_pct=50)
    waste_splash = percent_bp(setting("merma_splash_%"), "Ajustes merma_splash_%", errors, max_pct=50)
    # One flat fee for the measuring visit, charged only if the customer doesn't hire the job.
    # Older sheets had a fee per service type; their "instalamos nosotros" fee is taken.
    if "cuota_visita" in settings:
        visit_fee = money_minor(settings["cuota_visita"], "Ajustes cuota_visita", errors)
    else:
        visit_fee = money_minor(setting("cuota_visita_managed"), "Ajustes cuota_visita", errors)

    def net(minor: int | None) -> int | None:
        """Sheet amounts that include IVA are stored without it; the quote adds IVA once."""
        if minor is None or not includes_tax or tax_bp is None:
            return minor
        return div_round_half_up(minor * 10000, 10000 + tax_bp)

    # Countertop pieces: Kober's cost per piece in Original Q.
    pieces: dict[str, dict[str, int]] = {c: {} for c in CATEGORIES}
    for i, r in enumerate(tabs["Cubiertas"], start=2):
        where = f"Cubiertas row {i}"
        category = _norm(r.get("categoria"))
        if category not in CATEGORIES:
            errors.append(f"{where}: category '{r.get('categoria')}' must be one of {', '.join(CATEGORIES)}")
            continue
        w, ln = whole_mm(r.get("ancho_mm", ""), where, errors), whole_mm(r.get("largo_mm", ""), where, errors)
        if str(r.get("costo_kober_original_q", "")).strip() == "":
            continue  # a size the team does not sell; caught below if a finish needs it
        cost = net(money_minor(r.get("costo_kober_original_q", ""), where, errors))
        if None not in (w, ln, cost):
            key = f"{w}x{ln}"
            if key in pieces[category]:
                errors.append(f"{where}: {category} {key} appears twice")
            pieces[category][key] = cost

    profiles: dict[str, int] = {}
    for i, r in enumerate(tabs["Perfiles"], start=2):
        pid = _norm(r.get("perfil"))
        if pid not in PROFILES:
            errors.append(f"Perfiles row {i}: profile '{r.get('perfil')}' must be one of {', '.join(PROFILES)}")
            continue
        bp = percent_bp(r.get("factor_vs_original_q_%", ""), f"Perfiles {pid}", errors, max_pct=300)
        if bp is not None:
            profiles[pid] = bp
    for pid in PROFILES:
        if pid not in profiles:
            errors.append(f"Perfiles: no row for profile '{pid}'")

    panels: dict[str, dict[str, int]] = {c: {} for c in CATEGORIES}
    for i, r in enumerate(tabs["Splash"], start=2):
        where = f"Splash row {i}"
        category = _norm(r.get("categoria"))
        if category not in CATEGORIES:
            errors.append(f"{where}: category '{r.get('categoria')}' must be one of {', '.join(CATEGORIES)}")
            continue
        h, ln = whole_mm(r.get("alto_mm", ""), where, errors), whole_mm(r.get("largo_mm", ""), where, errors)
        if str(r.get("costo_kober", "")).strip() == "":
            continue
        cost = net(money_minor(r.get("costo_kober", ""), where, errors))
        if None not in (h, ln, cost):
            panels[category][f"{h}x{ln}"] = cost

    margins = {"countertop": {}, "splash": {}}
    for i, r in enumerate(tabs["Margenes"], start=2):
        category = _norm(r.get("categoria"))
        if category not in CATEGORIES:
            errors.append(f"Margenes row {i}: category '{r.get('categoria')}' must be one of {', '.join(CATEGORIES)}")
            continue
        for kind, col in (("countertop", "margen_cubierta_%"), ("splash", "margen_splash_%")):
            bp = percent_bp(r.get(col, ""), f"Margenes {category} {col}", errors, max_pct=300)
            if bp is not None:
                margins[kind][category] = bp

    labour: dict[str, int] = {}
    for i, r in enumerate(tabs["ManoDeObra"], start=2):
        concept = _norm(r.get("concepto"))
        if concept not in LABOUR:
            errors.append(f"ManoDeObra row {i}: '{r.get('concepto')}' must be one of {', '.join(LABOUR)}")
            continue
        minor = net(money_minor(r.get("precio", ""), f"ManoDeObra {concept}", errors))
        if minor is not None:
            labour[LABOUR[concept][0]] = minor
    for concept, (key, _) in LABOUR.items():
        if key not in labour:
            errors.append(f"ManoDeObra: no row for '{concept}'")

    finish_category: dict[str, str] = {}
    availability: dict[str, bool] = {}
    seen = set()
    for i, r in enumerate(tabs["Acabados"], start=2):
        fid = str(r.get("id", "")).strip().lower()
        if fid not in cat.finishes:
            errors.append(f"Acabados row {i}: unknown finish id '{r.get('id')}'")
            continue
        seen.add(fid)
        category = _norm(r.get("categoria"))
        if category not in CATEGORIES:
            errors.append(f"Acabados {fid}: category '{r.get('categoria')}' must be one of {', '.join(CATEGORIES)}")
        elif (cat.finishes[fid].line == "basik") != (category == "basik"):
            errors.append(f"Acabados {fid}: Basi-K finishes, and only they, use category basik")
        else:
            finish_category[fid] = category
        ok = yes_no(r.get("disponible", ""), f"Acabados {fid} disponible", errors)
        if ok is not None:
            availability[fid] = ok
    for fid in cat.finishes:
        if fid not in seen:
            warnings.append(f"Acabados: {fid} is not in the sheet; it keeps its catalogue category and stays available")

    if errors:
        raise SheetError("\n".join(errors))

    # Every piece and panel a quote could need must be priced, for the categories finishes use.
    probe = Catalogue(prices={**json.loads(PLACEHOLDER.read_text(encoding="utf-8")), "finish_category": finish_category})
    used = {f.category for f in probe.finishes.values() if availability.get(f.id, True)}
    for category in sorted(used):
        need = probe.piece_sizes(category)
        gaps = [f"{w}x{ln}" for w, ln in need if f"{w}x{ln}" not in pieces[category]]
        if gaps:
            errors.append(f"Cubiertas: {category} has no cost for {', '.join(gaps)}")
        panel_need = [f"{h}x{ln}" for h in probe.splash_heights() for ln in probe.splash_lengths()]
        gaps = [k for k in panel_need if k not in panels[category]]
        if gaps:
            errors.append(f"Splash: {category} has no cost for {', '.join(gaps)}")
        for kind in ("countertop", "splash"):
            if category not in margins[kind]:
                errors.append(f"Margenes: no {kind} margin for {category}")
            elif margins[kind][category] == 0:
                warnings.append(f"Margenes: {kind} margin for {category} is 0%")
    if errors:
        raise SheetError("\n".join(errors))
    if status == "LIVE" and any("margin" in w for w in warnings):
        warnings.append("estado is VIGENTE with a 0% margin: check Margenes before showing quotes")

    placeholder = json.loads(PLACEHOLDER.read_text(encoding="utf-8"))
    body = {
        "status": status, "source": source, "currency": currency,
        "tax": {"name": "IVA", "rate_bp": tax_bp, "confirmed": bool(tax_confirmed),
                "sheet_prices_included_tax": bool(includes_tax)},
        "waste_allowance_bp": {"countertop": waste_top, "splash": waste_splash},
        "default_category_by_line": placeholder["default_category_by_line"],
        "finish_category": finish_category, "availability": availability,
        "profile_factor_bp": profiles,
        "countertop_piece_minor": {c: dict(sorted(v.items())) for c, v in pieces.items() if v},
        "splash_panel_minor": {c: dict(sorted(v.items())) for c, v in panels.items() if v},
        "margin_bp": margins,
        "labour_minor": labour,
        "visit_fee_minor": visit_fee,
        "owner": settings.get("responsable", ""),
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:8]
    body = {"status": status, "version": f"sheet-{time.strftime('%Y%m%d')}-{digest}",
            "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **{k: v for k, v in body.items() if k != "status"}}
    return body, warnings


# --- template -----------------------------------------------------------------------

def template_rows(cat: Catalogue) -> dict[str, list[list]]:
    """The sheet pre-filled from the placeholder price list, so every row the quote needs is there.

    Example costs equal today's placeholder selling prices with a 0% margin, so a quote
    from the untouched template matches the placeholder quote. Replace every cost with
    Kober's, and set your margins."""
    p = json.loads(PLACEHOLDER.read_text(encoding="utf-8"))
    pf = p["profile_factor_bp"]
    oq = pf["original_q"]

    def pesos(minor: int) -> str:
        return f"{minor // 100}.{minor % 100:02d}"

    def band(width: int) -> int:
        return next(b["factor_bp"] for b in p["width_factor_bp"] if width <= b["max_width_mm"])

    rows: dict[str, list[list]] = {}
    rows["Ajustes"] = [
        ["clave", "valor", "nota"],
        ["estado", "BORRADOR", "BORRADOR mientras se revisa; VIGENTE cuando los precios son reales"],
        ["moneda", "MXN", ""],
        ["iva_%", "16", "tasa de IVA"],
        ["precios_incluyen_iva", "no", "si = los importes de esta hoja ya traen IVA (se descuenta al importar)"],
        ["iva_confirmado", "no", "si = el cliente ve 'IVA incluido'; no = se marca por confirmar"],
        ["merma_cubierta_%", "10", "merma por cortes añadida a cada tramo de cubierta"],
        ["merma_splash_%", "10", "merma por cortes añadida a cada tramo de Spläsh"],
        ["cuota_visita", pesos(p["visit_fee_minor"]),
         "visita de medición: sin costo si el cliente contrata la obra; si no, se cobra esta cuota (más IVA)"],
        ["responsable", "", "quién mantiene estos precios"],
    ]
    rows["Cubiertas"] = [["categoria", "ancho_mm", "largo_mm", "costo_kober_original_q", "nota"]]
    for category in CATEGORIES:
        for w, ln in cat.piece_sizes(category):
            factor = pf["basik"] if category == "basik" else oq  # Basi-K pieces come only in their own profile
            sell = div_round_half_up(p["countertop_per_metre_minor"][category] * ln * band(w) * factor,
                                     1000 * 10000 * 10000)
            rows["Cubiertas"].append([category, w, ln, pesos(sell), "EJEMPLO"])
    rows["Perfiles"] = [["perfil", "nombre", "factor_vs_original_q_%", "nota"]]
    for pid in PROFILES:
        if pid == "basik":
            rows["Perfiles"].append([pid, cat.profile(pid)["name"], "100", "Basi-K solo se hace en su perfil: dejar 100"])
            continue
        pct = f"{Decimal(pf[pid] * 100) / oq:.2f}".rstrip("0").rstrip(".")
        rows["Perfiles"].append([pid, cat.profile(pid)["name"], pct, "precio del perfil frente a Original Q"])
    rows["Splash"] = [["categoria", "alto_mm", "largo_mm", "costo_kober", "nota"]]
    for category in CATEGORIES:
        for h in cat.splash_heights():
            for ln in cat.splash_lengths():
                sell = div_round_half_up(p["splash_per_m2_minor"][category] * h * ln, 1_000_000)
                rows["Splash"].append([category, h, ln, pesos(sell), "EJEMPLO"])
    rows["Margenes"] = [["categoria", "margen_cubierta_%", "margen_splash_%"]] + [[c, "0", "0"] for c in CATEGORIES]
    rows["ManoDeObra"] = [["concepto", "unidad", "precio"]] + [
        [concept, unit, pesos(p["labour_minor"][key])] for concept, (key, unit) in LABOUR.items()]
    rows["Acabados"] = [["id", "linea", "nombre", "codigo", "categoria", "disponible", "nota"]]
    for f in cat.finishes.values():
        rows["Acabados"].append([f.id, f.line, f.name, f.code or "", f.category, "si",
                                 "categoría no impresa en el catálogo: confirmar" if f.category_inferred else ""])
    return rows


README_ROWS = [
    "Hoja de precios y reglas de RenovAI (cubiertas y Spläsh Kober)",
    "",
    "Celdas en amarillo = valores de EJEMPLO. Cámbialos por los costos reales de Kober y las tarifas del equipo; luego borra la palabra EJEMPLO de la nota.",
    "Fuente de los ejemplos: lista provisional del prototipo (catalog/kober/data/prices.placeholder.json), 2 oct 2026. No son precios de Kober.",
    "",
    "Pestañas:",
    "  Ajustes: estado (BORRADOR o VIGENTE), moneda, IVA, merma por cortes y cuotas de la visita de medición.",
    "  Cubiertas: costo de Kober por pieza, en perfil Original Q, para cada categoría x ancho x largo (mm). Una fila por pieza.",
    "  Perfiles: precio de cada perfil frente a Original Q (100 = igual; 120 = 20% más caro).",
    "  Splash: costo de Kober por panel Spläsh, por categoría x alto x largo (mm).",
    "  Margenes: margen que se suma al costo, por categoría, para cubiertas y para Spläsh.",
    "  ManoDeObra: instalación por metro, por m² de Spläsh, tarja submontada y unión entre piezas.",
    "  Acabados: categoría de precio de cada acabado y si está disponible (si/no). Un acabado 'no' disponible no se sugiere ni se puede elegir.",
    "",
    "Importes en pesos con hasta 2 decimales (5670.50 o 5,670.50). Porcentajes como 16 o 16%. Medidas en milímetros enteros.",
    "No cambies los nombres de las pestañas ni de las columnas: el sistema los lee así.",
    "",
    "Para usarla: compártela como 'Cualquier persona con el enlace puede ver' y pega el enlace en RenovAI > Visitas > Importar hoja de precios.",
    "Si algo falta o no se entiende, la importación se detiene y muestra qué corregir; los precios anteriores siguen en uso.",
]


def write_template(path: Path, cat: Catalogue) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    head = PatternFill("solid", fgColor="EDE6DD")
    example = PatternFill("solid", fgColor="FFF4D6")
    readme = wb.create_sheet("Leeme")  # the importer reads only the tabs in TABS, so this one is free text
    for line in README_ROWS:
        readme.append([line])
    readme["A1"].font = Font(bold=True, size=14)
    readme["A3"].fill = example
    readme.column_dimensions["A"].width = 120
    for tab, rows in template_rows(cat).items():
        ws = wb.create_sheet(tab)
        for r in rows:
            ws.append(r)
        for cell in ws[1]:
            cell.font, cell.fill = Font(bold=True), head
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str) and re.fullmatch(r"\d+\.\d\d", cell.value):
                    cell.value = Decimal(cell.value)
                    cell.number_format = "#,##0.00"
                if cell.value == "EJEMPLO":
                    cell.fill = example
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, width + 2))
        ws.freeze_panes = "A2"
    wb.save(path)


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("template", "import"):
        print(__doc__)
        return 2
    cat = Catalogue(price_file=PLACEHOLDER.name)
    if sys.argv[1] == "template":
        write_template(Path(sys.argv[2]), cat)
        print(f"template written to {sys.argv[2]}")
        return 0
    try:
        prices, warnings = build_prices(read_sheet(sys.argv[2]), cat, sys.argv[2])
    except SheetError as e:
        print("Price sheet NOT imported. Fix these and import again:\n" + str(e))
        return 1
    OUT.write_text(json.dumps(prices, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for w in warnings:
        print("warning:", w)
    print(f"imported {prices['version']} ({prices['status']}) -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
