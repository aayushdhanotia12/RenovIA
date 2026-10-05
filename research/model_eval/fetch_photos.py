"""Download free-licence kitchen photos from Wikimedia Commons for the model test run.

    python research/model_eval/fetch_photos.py --n 6 --out research/model_eval/photos

Only CC0, public-domain, CC BY and CC BY-SA photos at least 1200 px wide are taken; the
author and licence of each go to attribution.json next to the photos. The Kober sample
photo from the repo is always added first, so its results can be compared with the
offline fixtures.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = "RenovAI-model-eval/1.0 (https://github.com/aayushdhanotia12/RenovIA; research test run)"
CATEGORIES = ["Category:Kitchens in Mexico", "Category:Kitchen countertops", "Category:Countertops",
              "Category:Modern kitchens", "Category:Kitchens"]
SEARCHES = ["kitchen countertop backsplash", "cocina cubierta", "kitchen counter"]
OK_LICENCE = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? ?[0-9.]*)", re.I)
REPO = Path(__file__).resolve().parents[2]


def query(params: dict) -> dict:
    params = {"format": "json", "formatversion": 2, **params}
    r = requests.get(API, params=params, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return r.json()


def candidates() -> list[dict]:
    info = {"prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1600,
            "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription"}
    pages: dict[str, dict] = {}
    for cat in CATEGORIES:
        try:
            data = query({"action": "query", "generator": "categorymembers", "gcmtitle": cat, "gcmtype": "file",
                          "gcmlimit": 50, **info})
        except requests.RequestException:
            continue
        for p in data.get("query", {}).get("pages", []):
            pages.setdefault(p["title"], {**p, "source": cat})
    for q in SEARCHES:
        try:
            data = query({"action": "query", "generator": "search", "gsrsearch": f"{q} filetype:bitmap",
                          "gsrnamespace": 6, "gsrlimit": 30, **info})
        except requests.RequestException:
            continue
        for p in data.get("query", {}).get("pages", []):
            pages.setdefault(p["title"], {**p, "source": f"search: {q}"})
    out = []
    for title, p in pages.items():
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        licence = (meta.get("LicenseShortName") or {}).get("value", "")
        if not OK_LICENCE.match(licence.strip()) or ii.get("width", 0) < 1200 or ii.get("width", 0) < ii.get("height", 1):
            continue
        if not title.lower().endswith((".jpg", ".jpeg")):
            continue
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        out.append({"title": title, "url": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"),
                    "licence": licence, "author": artist[:200], "source": p["source"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    taken = [{"file": "00_kober_p7.jpg", "title": "Kober catalogue page 7 kitchen (repo sample)",
              "licence": "Kober catalogue image, used internally", "source": "samples/kober_photos"}]
    shutil.copy(REPO / "samples/kober_photos/p7_0_1920x1200.jpg", args.out / "00_kober_p7.jpg")
    # Prefer photos from the Mexico and countertop categories, then the rest.
    ranked = sorted(candidates(), key=lambda c: (0 if "Mexico" in c["source"] else 1 if "ountertop" in c["source"] else 2))
    for c in ranked:
        if len(taken) > args.n:
            break
        try:
            r = requests.get(c["url"], headers={"User-Agent": UA}, timeout=120)
            r.raise_for_status()
        except requests.RequestException as e:
            print("skip", c["title"], e)
            continue
        name = f"{len(taken):02d}_" + re.sub(r"[^A-Za-z0-9]+", "_", c["title"][5:])[:50].strip("_") + ".jpg"
        (args.out / name).write_bytes(r.content)
        taken.append({"file": name, **c})
        print("took", c["title"], c["licence"])
        time.sleep(1.0)  # be polite to Commons
    (args.out / "attribution.json").write_text(json.dumps(taken, indent=1, ensure_ascii=False))
    print(f"{len(taken)} photos in {args.out}")


if __name__ == "__main__":
    main()
