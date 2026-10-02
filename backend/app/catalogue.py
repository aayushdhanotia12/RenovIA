"""Read model over the Kober catalogue: finishes, product rules and the price list.

The design agent may only name finish ids that exist here, and the quote engine
reads prices only from here. Nothing in this module calls a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
KOBER = REPO / "catalog" / "kober"

WOOD_WORDS = ("oak", "rovere", "olmo", "cherry", "driftwood", "maple", "birdseye", "echo", "mango", "bark", "madagascar", "asian sand")
MARBLE_WORDS = ("marble", "carrara", "calcutta", "calcatta", "caracatta", "marquina", "kandia", "yule", "pulpis", "portoro", "venato", "saint laurent", "lancelot")
GRANITE_WORDS = ("granite", "juparana", "bahia", "blackstar", "topaz", "quartz", "milano", "mystique", "cascade", "alicante", "spring")
CONCRETE_WORDS = ("corten", "cenere", "basalto", "porfido", "manhattan", "slate", "plaster", "cracked", "jupiter", "gesso", "leather", "high rise", "serrania", "luna", "benjamin", "deepstar", "lario", "trinidad", "nebula", "graphite", "shadow")


class CatalogueError(ValueError):
    pass


@dataclass(frozen=True)
class Finish:
    id: str
    line: str
    name: str
    code: str | None
    category: str
    category_inferred: bool
    swatch_path: Path
    swatch_px: int
    tags: tuple[str, ...] = field(default_factory=tuple)
    gloss: float | None = None  # 0 matte .. 1 mirror; None = default by kind of finish

    def public(self) -> dict:
        return {
            "id": self.id, "line": self.line, "name": self.name, "code": self.code,
            "category": self.category, "category_inferred": self.category_inferred,
            "swatch_url": f"/catalog/{self.swatch_path.relative_to(KOBER).as_posix()}",
            "tags": list(self.tags),
        }


def _tags_for(name: str, swatch: Path) -> tuple[str, ...]:
    """Cheap, deterministic style tags from the finish name and swatch colour."""
    lname = name.lower()
    tags: list[str] = []
    if any(w in lname for w in WOOD_WORDS):
        tags.append("wood")
    elif any(w in lname for w in MARBLE_WORDS):
        tags.append("marble")
    elif any(w in lname for w in GRANITE_WORDS):
        tags.append("granite")
    elif any(w in lname for w in CONCRETE_WORDS):
        tags.append("stone-concrete")
    else:
        tags.append("solid")
    img = cv2.imread(str(swatch), cv2.IMREAD_COLOR)
    if img is not None:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
        lightness = float(lab[:, 0].mean()) * 100 / 255
        warmth = float(lab[:, 2].mean()) - 128
        tags.append("light" if lightness > 70 else "dark" if lightness < 35 else "mid-tone")
        tags.append("warm" if warmth > 6 else "cool" if warmth < -1 else "neutral")
        if float(lab[:, 0].std()) > 18:
            tags.append("strong-pattern")
    return tuple(tags)


PLACEHOLDER_PRICES = "prices.placeholder.json"
SHEET_PRICES = "prices.json"  # written by catalog/kober/price_sheet.py from the team's sheet


def resolve_price_file(name: str | None, root: Path = KOBER) -> str:
    """The configured price list, else the imported team sheet, else the placeholder list."""
    if name:
        return name
    return SHEET_PRICES if (root / "data" / SHEET_PRICES).exists() else PLACEHOLDER_PRICES


class Catalogue:
    def __init__(self, root: Path = KOBER, price_file: str | None = PLACEHOLDER_PRICES,
                 prices: dict | None = None) -> None:
        """`prices` (a parsed price list) is for tests and the sheet importer; the app reads files."""
        self._configured = (price_file, prices)
        self.root = root
        self.price_file = "(given)" if prices is not None else resolve_price_file(price_file, root)
        self.products = json.loads((root / "data" / "products.json").read_text(encoding="utf-8"))
        self.prices = prices if prices is not None else json.loads(
            (root / "data" / self.price_file).read_text(encoding="utf-8"))
        self.placeholder_swatches = (root / "swatches" / "PLACEHOLDER").exists()
        default_cat = self.prices["default_category_by_line"]
        overrides = self.prices.get("finish_category", {})
        finishes: dict[str, Finish] = {}
        for raw in json.loads((root / "data" / "finishes.json").read_text(encoding="utf-8")):
            category = overrides.get(raw["id"]) or raw.get("category") or default_cat[raw["line"]]
            swatch = root / raw["swatch"]
            finishes[raw["id"]] = Finish(
                id=raw["id"], line=raw["line"], name=raw["name"], code=raw.get("code"),
                category=category, category_inferred=raw.get("category") is None and raw["id"] not in overrides,
                swatch_path=swatch, swatch_px=raw["swatch_px"], tags=_tags_for(raw["name"], swatch), gloss=raw.get("gloss"),
            )
        self.finishes = finishes
        self.profiles = {p["id"]: p for p in self.products["profiles"]}

    def reload(self) -> None:
        """Read the price list (and finishes) again, e.g. after the team's sheet was imported."""
        price_file, prices = self._configured
        self.__init__(self.root, price_file, prices)

    def price_info(self) -> dict:
        p = self.prices
        return {"status": self.price_status, "version": self.price_version, "file": self.price_file,
                "source": p.get("source"), "imported_at": p.get("imported_at"), "owner": p.get("owner"),
                "currency": self.currency}

    @property
    def currency(self) -> str:
        return self.prices["currency"]

    @property
    def price_status(self) -> str:
        return self.prices.get("status", "LIVE")

    @property
    def price_version(self) -> str:
        """Which price list priced a quote: recorded on every design, like the model versions."""
        return str(self.prices.get("version") or self.prices.get("status", "LIVE").lower())

    def available(self, finish_id: str) -> bool:
        """False only when the team's price sheet marks the finish as not available."""
        return bool(self.prices.get("availability", {}).get(finish_id, True))

    def finish(self, finish_id: str) -> Finish:
        try:
            return self.finishes[finish_id]
        except KeyError:
            raise CatalogueError(f"unknown finish id: {finish_id!r}") from None

    def profile(self, profile_id: str) -> dict:
        try:
            return self.profiles[profile_id]
        except KeyError:
            raise CatalogueError(f"unknown profile id: {profile_id!r}") from None

    def check_profile(self, finish: Finish, profile_id: str) -> None:
        profile = self.profile(profile_id)
        if finish.line not in profile["finish_lines"]:
            raise CatalogueError(f"{finish.name} ({finish.line}) is not made in the {profile['name']} profile")
        if finish.id == "estilo-porfido-nero" and profile_id == "slim":
            raise CatalogueError("Porfido Nero is not made in the Slim profile (catalogue page 30)")

    def default_profile(self, finish: Finish) -> str:
        return "basik" if finish.line == "basik" else "original_q"

    def countertop_width(self, depth_mm: int) -> int:
        sizes = self.products["countertop_sizes"]
        widths = sorted(sizes["standard_widths_mm"] + sizes["wide_widths_mm"])
        for w in widths:
            if w >= depth_mm:
                return w
        raise CatalogueError(f"no standard countertop is {depth_mm} mm deep (max {widths[-1]} mm)")

    def countertop_lengths(self, finish: Finish, width_mm: int, profile_id: str) -> list[int]:
        sizes = self.products["countertop_sizes"]
        if finish.line == "basik" or profile_id == "basik":
            return list(sizes["basik_lengths_mm"])
        if width_mm > 645:
            return list(sizes["wide_lengths_mm"])
        lengths = list(sizes["standard_lengths_mm"])
        if finish.line == "estilo" and width_mm == 645:
            lengths = list(sizes["short_lengths_mm"]) + lengths
        return lengths

    def splash_lengths(self) -> list[int]:
        return list(self.products["splash_panels"]["lengths_mm"])

    def splash_heights(self) -> list[int]:
        return list(self.products["splash_panels"]["heights_mm"])

    def compact_listing(self) -> str:
        """One line per finish for a model prompt: id | name | line | category | tags."""
        return "\n".join(
            f"{f.id} | {f.name} | {f.line} | {f.category} | {', '.join(f.tags)}" for f in self.finishes.values()
        )


    def countertop_categories(self) -> list[str]:
        return sorted({f.category for f in self.finishes.values()})

    def piece_sizes(self, category: str) -> list[tuple[int, int]]:
        """Every (width, length) in mm that some finish of this price category is made in."""
        sizes = self.products["countertop_sizes"]
        widths = sorted(sizes["standard_widths_mm"] + sizes["wide_widths_mm"])
        out: set[tuple[int, int]] = set()
        for f in (f for f in self.finishes.values() if f.category == category):
            profile = self.default_profile(f)
            for w in widths:
                out.update((w, ln) for ln in self.countertop_lengths(f, w, profile))
        return sorted(out)


@lru_cache(maxsize=1)
def get_catalogue() -> Catalogue:
    return Catalogue()
