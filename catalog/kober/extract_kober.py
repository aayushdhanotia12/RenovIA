"""Extract the Kober catalogue PDF into structured data and swatch images.

Usage:
    python catalog/kober/extract_kober.py path/to/CATALOGO_KOBER.pdf

Writes, next to this file:
    data/finishes.json          one record per finish (line, name, code, category, swatch path)
    swatches/<line>/<id>.png    the finish image as shown in the PDF
    swatches/contact_sheet.png  every swatch with its name, for a visual check

Sizes, profiles and rules that the PDF states in prose live in data/products.json,
which is maintained by hand from the same catalogue pages (each entry cites its page).

Built for catalogue CATKBR25AGO26. Page layouts are fixed per edition, so a new
edition may need the page numbers and cell sizes below adjusted.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber
from PIL import Image, ImageDraw
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
RENDER_DPI = 400

# Pages that carry one finish line each, and how their labels sit relative to the swatch.
FINISH_PAGES = {
    11: {"line": "estilo", "label": "inside", "max_label_top": 560},
    12: {"line": "diseno", "label": "below", "max_label_top": 560, "cell": 60.1, "gap": 3.6},
    13: {"line": "basik", "label": "below", "max_label_top": 280, "cell": 60.0, "gap": 3.6},
}

# Finish codes and price categories from the availability table on page 13.
# Only finishes sold as boards, splash-backs or large-format bars are listed there.
TABLE_P13 = {
    "estilo": {
        "BASALTO VULCANO": ("3340", "premium_plus"), "BASALTO CENERE": ("3342", "premium_plus"),
        "BLACK CARDOSO": ("3432", "premium_plus"), "BLACK KANDIA": ("3452", "premium_plus"),
        "CARACATTA": ("8150", "premium_plus"), "CORTEN GRIGIO": ("3331", "premium_plus"),
        "GREY PULPIS": ("3445", "premium_plus"), "MANHATTAN GREY": ("8146", "premium_plus"),
        "MARQUINA": ("3433", "premium_plus"), "NERO": ("0509", "premium_plus"),
        "OLMO MERCURIO": ("4539", "premium_plus"), "PORFIDO NERO": ("3329", "premium_plus"),
        "PORFIDO GESSO": ("3328", "premium_plus"), "ROVERE ROCK": ("4585", "premium_plus"),
        "ROVERE SLAVONIA": ("4587", "premium_plus"), "WHITE KANDIA": ("3451", "premium_plus"),
        "WHITE YULE": ("3449", "premium_plus"), "PALE LANCELOT OAK": ("R20027", "premium"),
        "INDIA WHITE": ("S63045", "premium"), "CAVIAR SILVER": ("S63066", "premium"),
    },
    "diseno": {
        "BLACK ALICANTE": ("4926K-07", "estandar"),
        "CALCUTTA MARBLE": ("4925-01", "estandar"),
        "WHITE CARRARA": ("4924-38", "estandar"),
    },
}


@dataclass
class Finish:
    id: str
    line: str                    # estilo | diseno | basik
    name: str
    code: str | None             # Kober finish code, where the catalogue prints one
    category: str | None         # premium_plus | premium | estandar | basik, where printed
    swatch: str                  # path relative to this folder
    swatch_px: int               # shortest side of the swatch image, in pixels
    swatch_source: str           # pdf_image | page_render | solid_colour
    board_splash_available: bool # listed in the page-13 availability table


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def cmyk_to_rgb(color) -> tuple[int, int, int]:
    if color is None:
        return (255, 255, 255)
    if len(color) == 4:
        c, m, y, k = color
        return tuple(round(255 * (1 - v) * (1 - k)) for v in (c, m, y))
    if len(color) == 3:
        return tuple(round(255 * v) for v in color)
    return (round(255 * color[0]),) * 3


def labels_below(words: list[dict], max_top: float) -> list[dict]:
    """Group upper-case words printed under swatches into labels, one per swatch."""
    caps = [
        w for w in words
        if 80 < w["top"] < max_top and w["text"] == w["text"].upper() and any(c.isalpha() for c in w["text"])
    ]
    caps.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
    lines: list[list[dict]] = []
    for w in caps:
        if lines and abs(lines[-1][0]["top"] - w["top"]) < 1.5:
            lines[-1].append(w)
        else:
            lines.append([w])
    labels: list[dict] = []
    for line in lines:
        segments: list[list[dict]] = []
        for w in sorted(line, key=lambda w: w["x0"]):
            if segments and w["x0"] - segments[-1][-1]["x1"] < 3.0:  # words inside one label sit ~2 pt apart
                segments[-1].append(w)
            else:
                segments.append([w])
        for seg in segments:
            x0, top = seg[0]["x0"], seg[0]["top"]
            text = " ".join(w["text"] for w in seg)
            owner = next(
                (lb for lb in labels if abs(lb["x0"] - x0) < 1.5 and 4 < top - lb["last_top"] < 10), None
            )
            if owner:
                owner["text"] += " " + text
                owner["last_top"] = top
            else:
                labels.append({"x0": x0, "top": top, "last_top": top, "text": text})
    return labels


def label_inside(words: list[dict], box: dict) -> str:
    x0, x1, top, bottom = box["x0"], box["x1"], box["top"], box["bottom"]
    lo = top + 0.55 * (bottom - top)
    picked = [w for w in words if x0 - 1 <= (w["x0"] + w["x1"]) / 2 <= x1 + 1 and lo <= w["top"] <= bottom + 1]
    picked.sort(key=lambda w: (round(w["top"]), w["x0"]))
    return " ".join(w["text"] for w in picked).strip()


def render_page(pdf_path: Path, page_no: int, workdir: Path) -> Image.Image:
    stem = workdir / f"p{page_no}"
    subprocess.run(
        ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", str(RENDER_DPI), "-png", "-singlefile",
         str(pdf_path), str(stem)],
        check=True,
    )
    return Image.open(f"{stem}.png").convert("RGB")


def aligned(box: dict, cell: tuple[float, float, float, float], tol: float = 2.5) -> bool:
    x0, top, x1, bottom = cell
    return (abs(box["x0"] - x0) < tol and abs(box["x1"] - x1) < tol
            and abs(box["top"] - top) < tol and abs(box["bottom"] - bottom) < tol)


def make_finish(line: str, name: str, img: Image.Image, source: str) -> Finish:
    fid = f"{line}-{slugify(name)}"
    rel = Path("swatches") / line / f"{fid}.png"
    (HERE / rel).parent.mkdir(parents=True, exist_ok=True)
    img.save(HERE / rel)
    code, category = TABLE_P13.get(line, {}).get(name, (None, None))
    return Finish(
        id=fid, line=line, name=name.title().replace("´", "'"), code=code,
        category=category or ("basik" if line == "basik" else None),
        swatch=str(rel), swatch_px=min(img.size), swatch_source=source,
        board_splash_available=name in TABLE_P13.get(line, {}),
    )


def extract(pdf_path: Path) -> list[Finish]:
    reader = PdfReader(str(pdf_path))
    finishes: list[Finish] = []
    with pdfplumber.open(str(pdf_path)) as pdf, tempfile.TemporaryDirectory() as tmp:
        for page_no, cfg in FINISH_PAGES.items():
            line, page = cfg["line"], pdf.pages[page_no - 1]
            words = page.extract_words()
            raw = {img.name.rsplit(".", 1)[0].lstrip("/"): img for img in reader.pages[page_no - 1].images}

            if cfg["label"] == "inside":
                boxes = [
                    im for im in page.images
                    if 50 <= im["x1"] - im["x0"] <= 90 and abs((im["x1"] - im["x0"]) - (im["bottom"] - im["top"])) < 3
                ]
                for box in sorted(boxes, key=lambda b: (round(b["top"]), b["x0"])):
                    name = label_inside(words, box)
                    if name:
                        finishes.append(make_finish(line, name, raw[box["name"]].image.convert("RGB"), "pdf_image"))
                continue

            rendered = None
            size, gap = cfg["cell"], cfg["gap"]
            for lb in labels_below(words, cfg["max_label_top"]):
                bottom = lb["top"] - gap
                cell = (lb["x0"] - 1.0, bottom - size, lb["x0"] - 1.0 + size, bottom)
                image_box = next((im for im in page.images if aligned(im, cell)), None)
                rect_box = next((r for r in page.rects if aligned(r, cell) and r.get("fill")), None)
                if image_box is not None:
                    img, source = raw[image_box["name"]].image.convert("RGB"), "pdf_image"
                elif rect_box is not None:
                    img, source = Image.new("RGB", (256, 256), cmyk_to_rgb(rect_box.get("non_stroking_color"))), "solid_colour"
                else:
                    if rendered is None:
                        rendered = render_page(pdf_path, page_no, Path(tmp))
                    k = RENDER_DPI / 72.0
                    inset = 0.8
                    x0, top, x1, bot = cell
                    img = rendered.crop((round((x0 + inset) * k), round((top + inset) * k),
                                         round((x1 - inset) * k), round((bot - inset) * k)))
                    source = "page_render"
                finishes.append(make_finish(line, lb["text"], img, source))
    return finishes


def contact_sheet(finishes: list[Finish], path: Path, cell: int = 150) -> None:
    cols = 10
    rows = -(-len(finishes) // cols)
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 30)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(finishes):
        x, y = (i % cols) * cell, (i // cols) * (cell + 30)
        sw = Image.open(HERE / f.swatch).convert("RGB").resize((cell - 8, cell - 8))
        sheet.paste(sw, (x + 4, y + 4))
        draw.text((x + 4, y + cell - 2), f.name[:24], fill="black")
        draw.text((x + 4, y + cell + 11), f"{f.line} {f.code or '-'} {f.swatch_px}px", fill="gray")
    sheet.save(path)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    finishes = extract(Path(sys.argv[1]))
    ids = [f.id for f in finishes]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        sys.exit(f"duplicate finish ids: {sorted(dupes)}")
    data_dir = HERE / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "finishes.json").write_text(
        json.dumps([asdict(f) for f in finishes], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    contact_sheet(finishes, HERE / "swatches" / "contact_sheet.png")
    (HERE / "swatches" / "PLACEHOLDER").unlink(missing_ok=True)  # real swatches now
    counts = {ln: sum(f.line == ln for f in finishes) for ln in ("estilo", "diseno", "basik")}
    print(f"{len(finishes)} finishes: {counts}")


if __name__ == "__main__":
    main()
