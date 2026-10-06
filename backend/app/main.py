"""HTTP API and static web app.

Run:  uvicorn --factory backend.app.main:create_app --port 8000
"""

from __future__ import annotations

import importlib.util
import json
import re
import secrets
import time
from pathlib import Path

import cv2
import numpy as np
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .ai.base import ModelError
from .ai.factory import build_models
from .catalogue import Catalogue, CatalogueError
from .config import REPO, Settings, get_settings
from .geometry import valid_quad
from .jobs import JobHub
from .camera import camera_from_exif
from .photo_checks import check_photo
from .pipeline import Ctx, FlowError, analyse, design, style_board, suggest
from .quote import QuoteError, visit_fee
from .render import edge_shape
from .schemas import (AnalyseIn, BookingIn, BookingUpdateIn, DesignIn, MeasurementsIn, StyleBoardIn, SuggestIn,
                      SurfacesIn, VisitIn, plausibility_questions)
from .staff import media_ok, signed_media_url, visit_result, whatsapp_number
from .styles import public_styles
from .store import NotFound, Store, new_id

COOKIE = "renovai_owner"
OWNER_RE = re.compile(r"^[a-f0-9]{32}$")


class OwnerMiddleware:
    """Anonymous per-browser identity: every project query is scoped by it."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cookie_header = dict(scope.get("headers") or []).get(b"cookie", b"").decode()
        cookies = dict(part.strip().split("=", 1) for part in cookie_header.split(";") if "=" in part)
        owner = cookies.get(COOKIE, "")
        fresh = not OWNER_RE.match(owner)
        if fresh:
            owner = secrets.token_hex(16)
        scope.setdefault("state", {})["owner"] = owner

        async def send_with_cookie(message):
            if fresh and message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(
                    "set-cookie", f"{COOKIE}={owner}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000")
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or get_settings()
    store = Store(settings.data_dir / "renovai.sqlite3")
    cat = Catalogue(price_file=settings.price_file)
    ctx = Ctx(settings, store, cat, build_models(settings, cat))
    hub = JobHub(store)

    async def body(request: Request, model):
        try:
            return model.model_validate(await request.json())
        except json.JSONDecodeError:
            raise HTTPException(400, "body must be JSON") from None

    def owner(request: Request) -> str:
        return request.state.owner

    async def health(request: Request):
        return JSONResponse({"ok": True, "ai_mode": settings.ai_mode, "models": ctx.models.versions(),
                             "price_list": cat.price_status, "price_version": cat.price_version,
                             "currency": cat.currency, "placeholder_swatches": cat.placeholder_swatches})

    async def catalogue(request: Request):
        return JSONResponse({
            "finishes": [f.public() | {"available": cat.available(f.id)} for f in cat.finishes.values()],
            "profiles": [p | {"edge_shape": edge_shape(p)} for p in cat.profiles.values()],
            "currency": cat.currency, "price_list_status": cat.price_status, "styles": public_styles(),
            "placeholder_swatches": cat.placeholder_swatches,
            "visit_fee": visit_fee(cat).to_json(), "visit_fee_rule": "free_if_hired",
        })

    async def create_project(request: Request):
        return JSONResponse(store.create_project(owner(request)), status_code=201)

    async def get_project(request: Request):
        return JSONResponse(store.project(owner(request), request.path_params["pid"]))

    async def put_measurements(request: Request):
        pid = request.path_params["pid"]
        m = await body(request, MeasurementsIn)
        data = m.model_dump()
        data.update(capture_method="manual", scale_confidence="low")
        store.update_project(owner(request), pid, measurements=data)
        return JSONResponse({"measurements": data, "questions": plausibility_questions(m)})

    async def upload_photo(request: Request):
        pid = request.path_params["pid"]
        store.project(owner(request), pid)
        async with request.form(max_files=1) as form:  # closes the spooled upload file on exit
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(400, "send the photo as multipart field 'file'")
            raw = await upload.read()
        if len(raw) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"photos up to {settings.max_upload_mb} MB")
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(415, "This file is not a photo we can read. JPEG, PNG and WebP work.")
        h, w = img.shape[:2]
        scale = min(1.0, settings.render_max_side / max(h, w))
        if scale < 1:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        photo_id = new_id("pho")
        rel = f"photos/{photo_id}.jpg"
        path = ctx.project_dir(pid) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        checks = check_photo(img, raw)
        checks["camera"] = camera_from_exif(raw, img.shape[1], img.shape[0])
        photo = store.add_photo(owner(request), pid, photo_id, rel, img.shape[1], img.shape[0], checks)
        photo["url"] = f"/media/{pid}/{rel}"
        return JSONResponse(photo, status_code=201)

    async def start_analyse(request: Request):
        pid, who = request.path_params["pid"], owner(request)
        a = await body(request, AnalyseIn)
        store.photo(who, pid, a.photo_id)
        jid = hub.start(who, pid, "analyse", lambda p: analyse(ctx, who, pid, a.photo_id, a.language, p))
        return JSONResponse({"job_id": jid}, status_code=202)

    async def put_surfaces(request: Request):
        pid, who = request.path_params["pid"], owner(request)
        s = await body(request, SurfacesIn)
        photo = store.photo(who, pid, s.photo_id)
        project = store.project(who, pid)
        runs = {r["run_id"] for r in (project["measurements"] or {}).get("countertop_runs", [])}
        runs |= {r["run_id"] for r in (project["measurements"] or {}).get("splash_runs", [])}
        items = []
        for it in s.items:
            if it.run_id not in runs:
                raise HTTPException(400, f"surface {it.surface_id} points at unknown run {it.run_id}")
            if not valid_quad(it.quad, photo["width"], photo["height"]):
                raise HTTPException(400, f"the corners of {it.surface_id} don't make a four-sided shape")
            if it.mask_file and not (ctx.project_dir(pid) / it.mask_file).exists():
                raise HTTPException(400, f"unknown mask for {it.surface_id}")
            items.append(it.model_dump())
        surfaces = project["surfaces"] or {}
        before = surfaces.get(s.photo_id) or {}
        surfaces[s.photo_id] = {"confirmed": True, "items": items, "objects": before.get("objects", []),
                                "detector": before.get("detector", "manual"),
                                "light_file": before.get("light_file"), "lighting": before.get("lighting")}
        store.update_project(who, pid, surfaces=surfaces)
        return JSONResponse(surfaces[s.photo_id])

    async def start_suggest(request: Request):
        pid, who = request.path_params["pid"], owner(request)
        s = await body(request, SuggestIn)
        store.project(who, pid)
        jid = hub.start(who, pid, "suggest",
                        lambda p: suggest(ctx, who, pid, s.style, s.budget, s.language, p, style_id=s.style_id))
        return JSONResponse({"job_id": jid}, status_code=202)

    async def start_style_board(request: Request):
        pid, who = request.path_params["pid"], owner(request)
        b = await body(request, StyleBoardIn)
        store.photo(who, pid, b.photo_id)
        jid = hub.start(who, pid, "styles",
                        lambda p: style_board(ctx, who, pid, b.photo_id, b.budget, b.language, p))
        return JSONResponse({"job_id": jid}, status_code=202)

    async def start_design(request: Request):
        pid, who = request.path_params["pid"], owner(request)
        d = await body(request, DesignIn)
        store.photo(who, pid, d.photo_id)
        cat.check_profile(cat.finish(d.countertop_finish_id), d.profile_id)
        if d.splash_finish_id:
            cat.finish(d.splash_finish_id)
        choice = d.model_dump(exclude={"photo_id"})
        jid = hub.start(who, pid, "design", lambda p: design(ctx, who, pid, d.photo_id, choice, p))
        return JSONResponse({"job_id": jid}, status_code=202)

    def with_finishes(dsg: dict) -> dict:
        choice = dsg["choice"]
        dsg["finishes"] = {
            "countertop": cat.finish(choice["countertop_finish_id"]).public(),
            "backsplash": cat.finish(choice["splash_finish_id"]).public() if choice.get("splash_finish_id") else None,
        }
        dsg["profile"] = cat.profile(choice["profile_id"])
        return dsg

    async def get_design(request: Request):
        return JSONResponse(with_finishes(store.design(owner(request), request.path_params["did"])))

    def public_base(request: Request) -> str:
        return (settings.public_url or str(request.base_url)).rstrip("/")

    async def share_design(request: Request):
        """A read-only link to this design for WhatsApp: the render and the quote, nothing personal."""
        did = request.path_params["did"]
        sid = store.create_share(owner(request), did)
        return JSONResponse({"share_id": sid, "url": f"{public_base(request)}/#/s/{sid}"}, status_code=201)

    async def get_shared(request: Request):
        sid = request.path_params["sid"]
        dsg = with_finishes(store.shared_design(sid))
        dsg["manifest"]["image"]["url"] = f"/shared/{sid}/render.jpg"
        dsg["manifest"]["before_url"] = f"/shared/{sid}/before.jpg"
        for layer in dsg["manifest"]["layers"]:
            layer.pop("mask_url", None)
        keep = ("id", "choice", "manifest", "quote", "finishes", "profile", "created_at")
        return JSONResponse({k: dsg[k] for k in keep} | {"shared": True})

    async def shared_media(request: Request):
        sid, name = request.path_params["sid"], request.path_params["name"]
        dsg = store.shared_design(sid)
        if name == "render.jpg":
            rel = dsg["render_path"]
        elif name == "before.jpg":
            rel = dsg["manifest"]["before_url"].split(f"/media/{dsg['project_id']}/", 1)[-1]
        else:
            raise HTTPException(404, "not found")
        target = (ctx.project_dir(dsg["project_id"]) / rel).resolve()
        if not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target, headers={"Cache-Control": "private, max-age=3600"})

    async def get_job(request: Request):
        jid = request.path_params["jid"]
        job = store.job(owner(request), jid)
        job["events"] = hub.events(jid)
        return JSONResponse(job)

    async def job_events(request: Request):
        jid, who = request.path_params["jid"], owner(request)
        store.job(who, jid)
        after = request.headers.get("last-event-id") or request.query_params.get("after") or "0"
        after_seq = int(after) if after.isdigit() else 0

        async def gen():
            async for ev in hub.stream(who, jid, after_seq):
                yield f"id: {ev['seq']}\nevent: progress\ndata: {json.dumps(ev)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def create_booking(request: Request):
        pid, who = request.path_params["pid"], owner(request)
        b = await body(request, BookingIn)
        if b.design_id:
            store.design(who, b.design_id)
        return JSONResponse(store.add_booking(who, pid, b.model_dump()), status_code=201)

    # ------------------------------------------------------------- field team (staff)
    def require_staff(request: Request) -> None:
        token = request.headers.get("x-staff-token") or ""
        if not token or settings.staff_token == "change-me" or not secrets.compare_digest(token, settings.staff_token):
            raise HTTPException(403, "staff token required (set RENOVAI_STAFF_TOKEN)")

    def staff_summary(b: dict) -> dict:
        choice = b.pop("choice", None) or {}
        quote = b.pop("quote", None)
        final = b.get("final_quote")
        top = cat.finishes.get(choice.get("countertop_finish_id", ""))
        splash = cat.finishes.get(choice.get("splash_finish_id") or "")
        has_design = bool(b.get("design_id"))
        return {
            **{k: b.get(k) for k in ("id", "project_id", "design_id", "created_at", "updated_at", "status", "name",
                                     "phone", "address", "preferred_window", "fulfilment_type", "notes",
                                     "scheduled_at", "assigned_to", "staff_notes", "visited_at")},
            "whatsapp": whatsapp_number(b.get("phone") or ""),
            "estimate": quote["estimate"] if quote else None,
            "final_total": final["total"] if final else None,
            "countertop": top.public() if top else None, "backsplash": splash.public() if splash else None,
            "profile": cat.profiles.get(choice.get("profile_id", ""), {}).get("name"),
            "thumb_url": signed_media_url(settings.staff_token, b["id"], "render") if has_design else None,
        }

    async def staff_bookings(request: Request):
        require_staff(request)
        return JSONResponse({"bookings": [staff_summary(b) for b in store.staff_bookings()],
                             "prices": cat.price_info()})

    async def staff_booking_detail(request: Request):
        require_staff(request)
        bid = request.path_params["bid"]
        b = store.staff_booking(bid)
        detail = {"booking": staff_summary(dict(b)), "verified": b.get("verified"), "final_quote": b.get("final_quote"),
                  "design": None, "measurements": None}
        detail["measurements"] = store.staff_project(b["project_id"])["measurements"]
        if b.get("design_id"):
            dsg = with_finishes(store.staff_design(b["design_id"]))
            dsg["manifest"]["image"]["url"] = signed_media_url(settings.staff_token, bid, "render")
            dsg["manifest"]["before_url"] = signed_media_url(settings.staff_token, bid, "photo")
            detail["design"] = {k: dsg[k] for k in ("id", "choice", "manifest", "quote", "finishes", "profile",
                                                    "model_versions")}
        return JSONResponse(detail)

    async def staff_update_booking(request: Request):
        require_staff(request)
        u = await body(request, BookingUpdateIn)
        fields = {k: v for k, v in u.model_dump().items() if k in u.model_fields_set}
        store.update_booking(request.path_params["bid"], **fields)
        return await staff_booking_detail(request)

    async def staff_visit(request: Request):
        """The team's measurements: price the design again as a final quote and keep the differences."""
        require_staff(request)
        bid = request.path_params["bid"]
        v = await body(request, VisitIn)
        b = store.staff_booking(bid)
        if not b.get("design_id"):
            raise HTTPException(400, "this request has no design to price")
        dsg = store.staff_design(b["design_id"])
        customer = store.staff_project(b["project_id"])["measurements"] or {}
        if dsg["choice"].get("splash_finish_id") is None and v.splash_runs:
            raise HTTPException(400, "this design has no backsplash finish; leave the backsplash runs empty")
        result = visit_result(v.model_dump(), customer, dsg["choice"], dsg["quote"]["estimate"], cat, v.language)
        store.update_booking(bid, status="visited", visited_at=time.time(), **result)
        return await staff_booking_detail(request)

    async def staff_media(request: Request):
        bid, kind = request.path_params["bid"], request.path_params["kind"]
        if not media_ok(settings.staff_token, bid, kind, request.query_params.get("exp", ""),
                        request.query_params.get("sig", "")):
            raise HTTPException(403, "link expired; reload the staff page")
        b = store.staff_booking(bid)
        if not b.get("design_id"):
            raise HTTPException(404, "not found")
        dsg = store.staff_design(b["design_id"])
        rel = dsg["render_path"] if kind == "render" else \
            dsg["manifest"]["before_url"].split(f"/media/{dsg['project_id']}/", 1)[-1]
        target = (ctx.project_dir(dsg["project_id"]) / rel).resolve()
        if not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target, headers={"Cache-Control": "private, max-age=3600"})

    async def staff_prices(request: Request):
        require_staff(request)
        return JSONResponse({"prices": cat.price_info(), "sheet_url": settings.price_sheet_url or None})

    async def staff_import_prices(request: Request):
        """Import the team's Google Sheet (or the configured one) and start quoting from it at once."""
        require_staff(request)
        try:
            data = await request.json()
        except json.JSONDecodeError:
            data = {}
        source = (data or {}).get("url") or settings.price_sheet_url
        if not source or not str(source).startswith("https://docs.google.com/spreadsheets/"):
            raise HTTPException(400, "give the Google Sheets link of the price sheet")
        if cat.price_file not in ("prices.json", "prices.placeholder.json"):
            raise HTTPException(409, f"RENOVAI_PRICE_FILE pins {cat.price_file}; clear it to quote from the sheet")
        spec = importlib.util.spec_from_file_location("price_sheet", REPO / "catalog" / "kober" / "price_sheet.py")
        sheet = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sheet)
        try:
            prices, warnings = sheet.build_prices(sheet.read_sheet(source), Catalogue(), source)
        except sheet.SheetError as e:
            return JSONResponse({"error": "sheet", "detail": str(e).splitlines()}, status_code=422)
        sheet.OUT.write_text(json.dumps(prices, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        cat.reload()
        return JSONResponse({"prices": cat.price_info(), "warnings": warnings})

    async def media(request: Request):
        pid, rel = request.path_params["pid"], request.path_params["path"]
        store.project(owner(request), pid)  # only the owner can fetch their photos and renders
        base = ctx.project_dir(pid).resolve()
        target = (base / rel).resolve()
        if base not in target.parents or not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target)

    async def not_found(request: Request, exc: Exception):
        return JSONResponse({"error": "not_found", "detail": str(exc)}, status_code=404)

    async def bad_request(request: Request, exc: Exception):
        return JSONResponse({"error": "invalid", "detail": str(exc)}, status_code=400)

    async def invalid(request: Request, exc: ValidationError):
        return JSONResponse({"error": "invalid", "detail": json.loads(exc.json())}, status_code=422)

    async def model_failed(request: Request, exc: Exception):
        return JSONResponse({"error": "model_unavailable", "detail": str(exc)}, status_code=502)

    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": "http", "detail": exc.detail}, status_code=exc.status_code)

    routes = [
        Route("/api/health", health),
        Route("/api/catalogue", catalogue),
        Route("/api/projects", create_project, methods=["POST"]),
        Route("/api/projects/{pid}", get_project),
        Route("/api/projects/{pid}/measurements", put_measurements, methods=["PUT"]),
        Route("/api/projects/{pid}/photos", upload_photo, methods=["POST"]),
        Route("/api/projects/{pid}/analyse", start_analyse, methods=["POST"]),
        Route("/api/projects/{pid}/surfaces", put_surfaces, methods=["PUT"]),
        Route("/api/projects/{pid}/suggest", start_suggest, methods=["POST"]),
        Route("/api/projects/{pid}/designs", start_design, methods=["POST"]),
        Route("/api/projects/{pid}/styles", start_style_board, methods=["POST"]),
        Route("/api/projects/{pid}/bookings", create_booking, methods=["POST"]),
        Route("/api/designs/{did}", get_design),
        Route("/api/jobs/{jid}", get_job),
        Route("/api/jobs/{jid}/events", job_events),
        Route("/api/designs/{did}/share", share_design, methods=["POST"]),
        Route("/api/shared/{sid}", get_shared),
        Route("/shared/{sid}/{name}", shared_media),
        Route("/api/staff/bookings", staff_bookings),
        Route("/api/staff/bookings/{bid}", staff_booking_detail),
        Route("/api/staff/bookings/{bid}", staff_update_booking, methods=["PATCH"]),
        Route("/api/staff/bookings/{bid}/visit", staff_visit, methods=["POST"]),
        Route("/api/staff/media/{bid}/{kind}", staff_media),
        Route("/api/staff/prices", staff_prices),
        Route("/api/staff/prices/import", staff_import_prices, methods=["POST"]),
        Route("/media/{pid}/{path:path}", media),
        Mount("/catalog", app=StaticFiles(directory=str(REPO / "catalog" / "kober")), name="catalog"),
    ]
    web_dist = REPO / "web" / "dist"
    if web_dist.exists():
        routes.append(Mount("/", app=StaticFiles(directory=str(web_dist), html=True), name="web"))

    app = Starlette(routes=routes, exception_handlers={
        NotFound: not_found, FlowError: bad_request, QuoteError: bad_request, CatalogueError: bad_request,
        ValidationError: invalid, ModelError: model_failed, HTTPException: http_error,
    })
    app.state.ctx, app.state.hub = ctx, hub
    return OwnerMiddleware(app)
