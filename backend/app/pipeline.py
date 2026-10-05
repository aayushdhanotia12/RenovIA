"""The work behind each job: analyse a photo, suggest finishes, render and price a design.

These functions run in worker threads and report progress through `progress(stage, ...)`.
Stage names match the progress screen: GEOMETRY, DESCRIBE, DESIGN, RENDER, QUOTE.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from renderer.composite import light_from_model

from .ai.base import ModelError
from .ai.factory import Models
from .catalogue import Catalogue
from .config import Settings
from .geometry import fit_quad, mask_polygon, object_record, polygon_mask, subtract_objects
from .quote import CountertopRun, QuoteRequest, SplashRun, price_quote
from .render import RENDERER_VERSION, SurfacePlan, render_design, save_render
from .store import Store, new_id
from .styles import STYLE_IDS, STYLES, brief_for


class FlowError(ValueError):
    """The customer has to do something first (measure, confirm surfaces...)."""


# Progress details are shown to the customer under each stage, so they follow the job's language.
_DETAIL = {
    "find": ("Buscando tu cubierta, tu salpicadero y lo que hay sobre ellos",
             "Finding your countertop, backsplash and everything on them"),
    "found": ("Encontramos {top} cubierta(s) y {splash} salpicadero(s)", "Found {top} countertop and {splash} backsplash surface(s)"),
    "look": ("Observando tus gabinetes y paredes", "Looking at your cabinets and walls"),
    "retry": ("Revisando otra vez", "Taking a second look"),
    "choose": ("Eligiendo acabados del catálogo Kober", "Choosing finishes from the Kober catalogue"),
    "options": ("{n} opciones listas", "{n} options ready"),
    "lay": ("Colocando {name} a su tamaño real", "Laying {name} at its real size"),
    "price": ("Calculando piezas, merma e instalación", "Working out pieces, allowance and installation"),
}


def detail(key: str, language: str | None, **values) -> str:
    es, en = _DETAIL[key]
    return (en if language == "en" else es).format(**values)


@dataclass
class Ctx:
    settings: Settings
    store: Store
    cat: Catalogue
    models: Models

    def project_dir(self, pid: str) -> Path:
        return self.settings.data_dir / "media" / pid

    @property
    def texture_cache(self) -> Path:
        return self.settings.data_dir / "cache" / "textures"


def load_photo(ctx: Ctx, owner: str, pid: str, photo_id: str) -> tuple[dict, np.ndarray]:
    photo = ctx.store.photo(owner, pid, photo_id)
    img = cv2.imread(str(ctx.project_dir(pid) / photo["path"]), cv2.IMREAD_COLOR)
    if img is None:
        raise FlowError("photo file is missing")
    return photo, img


def analyse(ctx: Ctx, owner: str, pid: str, photo_id: str, language: str, progress) -> dict:
    project = ctx.store.project(owner, pid)
    _, img = load_photo(ctx, owner, pid, photo_id)
    progress("GEOMETRY", detail=detail("find", language))
    # Claude looks first: its list of what stands on the counter tells SAM 3 what to cut out.
    try:
        description = ctx.models.describer.describe(img, language)
    except ModelError:
        description = None
    try:
        detections = ctx.models.detector.detect(img, objects=(description or {}).get("objects"))
    except ModelError as e:
        progress("GEOMETRY", "failed", detail=str(e))
        detections = []
    meas = project["measurements"] or {}
    top_runs = [r["run_id"] for r in meas.get("countertop_runs", [])] or ["A"]
    splash_runs = [r["run_id"] for r in meas.get("splash_runs", [])] or ["S1"]
    mask_dir = ctx.project_dir(pid) / "masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    objects = [d for d in detections if d.surface_class == "object"]
    items = []
    for cls, runs in (("countertop", top_runs), ("backsplash", splash_runs)):
        dets = sorted((d for d in detections if d.surface_class == cls), key=lambda d: -int(np.count_nonzero(d.mask)))
        for i, det in enumerate(dets[:len(runs)]):
            sid = f"{cls}_{i + 1}"
            quad = det.quad or fit_quad(det.mask)
            if quad is None:
                continue
            product = subtract_objects(det.mask, [o.mask for o in objects])  # never paint over a tap or a bottle
            mask_file = f"masks/{photo_id}_{sid}.png"
            cv2.imwrite(str(ctx.project_dir(pid) / mask_file), product)
            items.append({"surface_id": sid, "surface_class": cls, "run_id": runs[i], "quad": quad,
                          "polygon": mask_polygon(product), "mask_file": mask_file, "score": round(det.score, 3)})
    # The room's light without the old surfaces' colour or shine (lighting model), kept per photo.
    light_file = None
    if ctx.models.lighting is not None:
        try:
            light = ctx.models.lighting.estimate(img)
        except ModelError:
            light = None
        if light is not None:
            light_file = f"light/{photo_id}.npz"
            (ctx.project_dir(pid) / "light").mkdir(parents=True, exist_ok=True)
            np.savez_compressed(ctx.project_dir(pid) / light_file, shading=light.astype(np.float16))
    object_items = []
    for j, obj in enumerate(sorted(objects, key=lambda d: -d.score)[:40]):
        object_file = f"masks/{photo_id}_object_{j + 1}.png"
        cv2.imwrite(str(ctx.project_dir(pid) / object_file), obj.mask)
        object_items.append({**object_record(obj.label or "object", obj.mask, obj.score), "mask_file": object_file})
    found = sum(1 for it in items if it["surface_class"] == "countertop")
    progress("GEOMETRY", "done", detail=detail(
        "found", language, top=found, splash=sum(1 for it in items if it["surface_class"] == "backsplash")))

    progress("DESCRIBE", detail=detail("look", language))
    progress("DESCRIBE", "done")

    surfaces = project["surfaces"] or {}
    surfaces[photo_id] = {"confirmed": False, "items": items, "objects": object_items,
                          "detector": ctx.models.detector.model_id, "light_file": light_file,
                          "lighting": ctx.models.lighting.model_id if light_file else None}
    ctx.store.update_project(owner, pid, surfaces=surfaces, description=description)
    return {"photo_id": photo_id, "surfaces": items, "objects": object_items, "description": description}


def _suggest_once(ctx: Ctx, description: dict | None, brief: str, budget: str | None, language: str,
                  progress) -> list[dict]:
    last: Exception | None = None
    for _ in range(2):
        try:
            return ctx.models.suggester.suggest(description, brief, budget, language)
        except ModelError as e:
            last = e
            progress("DESIGN", detail=detail("retry", language))
    raise FlowError(f"could not produce suggestions: {last}")


def suggest(ctx: Ctx, owner: str, pid: str, style: str, budget: str | None, language: str, progress,
            style_id: str | None = None) -> dict:
    project = ctx.store.project(owner, pid)
    progress("DESIGN", detail=detail("choose", language))
    items = _suggest_once(ctx, project["description"], brief_for(style_id, style) if style_id else style, budget,
                          language, progress)
    ctx.store.update_project(owner, pid, suggestions={"style": style, "style_id": style_id, "budget": budget,
                                                      "items": items, "model": ctx.models.suggester.model_id})
    progress("DESIGN", "done", detail=detail("options", language, n=len(items)))
    return {"suggestions": items}


def quote_request(meas: dict, choice: dict, cat: Catalogue) -> QuoteRequest:
    """The quote request for a stored design choice and the project's measurements."""
    has_splash = bool(choice.get("splash_finish_id"))
    return QuoteRequest(
        countertop_finish_id=choice["countertop_finish_id"], profile_id=choice["profile_id"],
        countertop_runs=tuple(CountertopRun(r["run_id"], r["length_mm"], r["depth_mm"]) for r in meas["countertop_runs"]),
        splash_finish_id=choice["splash_finish_id"] if has_splash else None,
        splash_runs=tuple(SplashRun(r["run_id"], r["length_mm"], r["height_mm"]) for r in meas.get("splash_runs", []))
        if has_splash else (),
        sinks=int(meas.get("sinks", 0)), scale_confidence=meas.get("scale_confidence", "low"),
        fulfilment_type=choice.get("fulfilment_type", "MANAGED"), language=choice.get("language", "es"),
    )


def design(ctx: Ctx, owner: str, pid: str, photo_id: str, choice: dict, progress) -> dict:
    cat = ctx.cat
    top = cat.finish(choice["countertop_finish_id"])
    cat.check_profile(top, choice["profile_id"])
    splash = cat.finish(choice["splash_finish_id"]) if choice.get("splash_finish_id") else None

    project = ctx.store.project(owner, pid)
    meas = project["measurements"]
    if not meas or not meas.get("countertop_runs"):
        raise FlowError("add the countertop measurements first")
    surf = (project["surfaces"] or {}).get(photo_id)
    if not surf or not surf["items"]:
        raise FlowError("mark the countertop on the photo first")
    photo, img = load_photo(ctx, owner, pid, photo_id)
    h, w = img.shape[:2]

    top_runs = {r["run_id"]: r for r in meas["countertop_runs"]}
    splash_runs = {r["run_id"]: r for r in meas.get("splash_runs", [])}
    plans: list[SurfacePlan] = []
    for item in surf["items"]:
        if item["surface_class"] == "countertop":
            run = top_runs.get(item["run_id"])
            if run is None:
                continue
            width_mm, height_mm = run["length_mm"], run["depth_mm"]
        else:
            run = splash_runs.get(item["run_id"])
            if run is None or splash is None:
                continue
            width_mm, height_mm = run["length_mm"], run["height_mm"]
        if item.get("mask_file"):
            mask = cv2.imread(str(ctx.project_dir(pid) / item["mask_file"]), cv2.IMREAD_GRAYSCALE)
        else:
            mask = polygon_mask(item.get("polygon") or item["quad"], (h, w))
        plans.append(SurfacePlan(item["surface_id"], item["surface_class"], item["run_id"], item["quad"],
                                 mask, width_mm, height_mm, item.get("score") or 1.0,
                                 detected=bool(item.get("mask_file"))))
    if not any(p.surface_class == "countertop" for p in plans):
        raise FlowError("no countertop surface matches the measured runs")

    language = choice.get("language", "es")
    progress("RENDER", detail=detail("lay", language, name=top.name))
    camera = (photo.get("checks") or {}).get("camera") or {}
    light, lighting_id = None, "builtin:photo-luminance"
    if surf.get("light_file") and (ctx.project_dir(pid) / surf["light_file"]).exists():
        light = light_from_model(np.load(ctx.project_dir(pid) / surf["light_file"])["shading"], img)
        lighting_id = surf.get("lighting") or "unknown"
    image, layers, masks = render_design(img, plans, top, splash, ctx.texture_cache,
                                         profile=cat.profile(choice["profile_id"]),
                                         focal_px=camera.get("focal_px") if camera.get("source") == "exif" else None,
                                         light=light)
    design_id = new_id("dsg")
    save_render(ctx.project_dir(pid) / "renders", design_id, image, masks)
    progress("RENDER", "done")

    progress("QUOTE", detail=detail("price", language))
    quote = price_quote(quote_request(meas, choice, cat), cat).to_json()
    for layer in layers:
        layer["mask_url"] = f"/media/{pid}/renders/{design_id}_{layer['surface_id']}.png"
    manifest = {
        "render_id": design_id,
        "image": {"url": f"/media/{pid}/renders/{design_id}.jpg", "width": w, "height": h},
        "before_url": f"/media/{pid}/{photo['path']}",
        "layers": layers,
        "camera": {"focal_px": camera.get("focal_px"), "source": camera.get("source", "default")},
    }
    versions = {**ctx.models.versions(), "lighting": lighting_id, "renderer": RENDERER_VERSION,
                "price_list": cat.price_version}
    ctx.store.add_design(pid, design_id, photo_id, choice, f"renders/{design_id}.jpg", manifest, quote, versions)
    progress("QUOTE", "done")
    return {"design_id": design_id}


def style_board(ctx: Ctx, owner: str, pid: str, photo_id: str, budget: str | None, language: str, progress,
                style_ids: tuple[str, ...] = STYLE_IDS) -> dict:
    """One finished design per style (minimalist, warm, contrast, statement), for side-by-side comparison.

    Each style is suggested, rendered and priced exactly like a single design; a style that
    fails is reported on the board and the others still arrive."""
    project = ctx.store.project(owner, pid)
    has_splash = bool((project["measurements"] or {}).get("splash_runs"))
    board: list[dict] = []
    n = len(style_ids)

    def quiet(stage: str, status: str = "running", detail: str | None = None, percent: int | None = None) -> None:
        if status == "running":  # per-design "done" events would tick the stages off too early
            progress("RENDER", detail=f"{label} ({i}/{n}): {detail or ''}".rstrip(": "))

    for i, sid in enumerate(style_ids, 1):
        label = STYLES[sid]["es" if language == "es" else "en"]
        progress("DESIGN", detail=f"{label} ({i}/{n})")
        try:
            pick = _suggest_once(ctx, project["description"], brief_for(sid), budget, language, quiet)[0]
            choice = {"countertop_finish_id": pick["countertop_finish_id"], "profile_id": pick["profile_id"],
                      "splash_finish_id": pick["backsplash_finish_id"] if has_splash else None,
                      "fulfilment_type": "MANAGED", "language": language}
            done = design(ctx, owner, pid, photo_id, choice, quiet)
            dsg = ctx.store.design(owner, done["design_id"])
            board.append({"style_id": sid, "design_id": done["design_id"], "title": pick["title"],
                          "reason": pick["reason"], **{k: choice[k] for k in ("countertop_finish_id", "profile_id",
                                                                           "splash_finish_id")},
                          "image_url": dsg["manifest"]["image"]["url"], "estimate": dsg["quote"]["estimate"]})
        except (FlowError, ModelError) as e:
            board.append({"style_id": sid, "error": str(e)})
    if not any("design_id" in b for b in board):
        raise FlowError("none of the styles could be designed: " + "; ".join(b.get("error", "") for b in board))
    progress("DESIGN", "done")
    progress("RENDER", "done")
    progress("QUOTE", "done")
    ctx.store.update_project(owner, pid, style_board={"photo_id": photo_id, "budget": budget, "items": board})
    return {"board": board}
