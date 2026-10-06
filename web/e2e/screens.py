"""Screenshot every screen at web (1440 x 900) and mobile (390 x 844, 2x) sizes, for design review.

Needs a running server in mock mode with a staff token:
    RENOVAI_STAFF_TOKEN=demo uvicorn --factory backend.app.main:create_app --port 8765
Then:
    RENOVAI_STAFF_TOKEN=demo python web/e2e/screens.py http://127.0.0.1:8765 out_dir

Writes out_dir/web/*.png and out_dir/mobile/*.png with matching names. The project, its
suggestions and the four-style board are set up once through the API; each viewport then
visits the same screens.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import APIRequestContext, BrowserContext, Page, expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
PHOTO = REPO / "samples" / "kober_photos" / "p7_0_1920x1200.jpg"
STAFF_TOKEN = os.environ.get("RENOVAI_STAFF_TOKEN", "")
VIEWPORTS = {"web": ({"width": 1440, "height": 900}, 1), "mobile": ({"width": 390, "height": 844}, 2)}


def ok(resp):
    assert resp.ok, f"{resp.status} {resp.url}: {resp.text()[:300]}"
    return resp.json()


def wait_job(api: APIRequestContext, base: str, job_id: str, timeout: float = 300) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = ok(api.get(f"{base}/api/jobs/{job_id}"))
        if job["status"] == "done":
            return job["result"]
        if job["status"] == "failed":
            raise SystemExit(f"job {job_id} failed: {job['error']}")
        time.sleep(0.5)
    raise SystemExit(f"job {job_id} timed out")


def set_up(ctx: BrowserContext, base: str) -> dict:
    """One project with a photo, measurements, confirmed surfaces, suggestions, a board and a share link."""
    api = ctx.request
    pid = ok(api.post(f"{base}/api/projects"))["id"]
    photo = ok(api.post(f"{base}/api/projects/{pid}/photos", multipart={
        "file": {"name": PHOTO.name, "mimeType": "image/jpeg", "buffer": PHOTO.read_bytes()}}))
    ok(api.put(f"{base}/api/projects/{pid}/measurements", data={
        "countertop_runs": [{"run_id": "A", "length_mm": 3600, "depth_mm": 645}],
        "splash_runs": [{"run_id": "S1", "length_mm": 3000, "height_mm": 600}],
        "sinks": 1, "confirmed_questions": []}))
    found = wait_job(api, base, ok(api.post(f"{base}/api/projects/{pid}/analyse",
                                            data={"photo_id": photo["id"], "language": "es"}))["job_id"])
    ok(api.put(f"{base}/api/projects/{pid}/surfaces", data={"photo_id": photo["id"], "items": found["surfaces"]}))
    wait_job(api, base, ok(api.post(f"{base}/api/projects/{pid}/suggest", data={
        "style": "fácil de limpiar", "style_id": "calido", "budget": None, "language": "es"}))["job_id"])
    board = wait_job(api, base, ok(api.post(f"{base}/api/projects/{pid}/styles", data={
        "photo_id": photo["id"], "budget": None, "language": "es"}))["job_id"])["board"]
    design = next(b["design_id"] for b in board if b["style_id"] == "contraste")
    share = ok(api.post(f"{base}/api/designs/{design}/share"))["share_id"]
    return {"pid": pid, "photo": photo["id"], "design": design, "share": share}


def settle(page: Page, ms: int = 800) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def capture(page: Page, base: str, p: dict, out: Path, phone: bool) -> None:
    def shot(name: str, full: bool = False) -> None:
        if full:  # from the top, so the sticky header sits where it belongs
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(200)
        page.screenshot(path=str(out / f"{name}.png"), full_page=full)

    pid, photo, did = p["pid"], p["photo"], p["design"]

    page.goto(f"{base}/#/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("Tu cocina")
    settle(page, 1200)
    shot("01-landing")
    shot("02-landing-full-page", full=True)
    page.locator(".demo-rows button").first.click()
    page.locator("#demo").scroll_into_view_if_needed()
    settle(page, 500)
    shot("03-landing-demo-surface-tapped")

    page.goto(f"{base}/#/p/{pid}")
    expect(page.locator(".dropzone-img")).to_be_visible(timeout=20000)
    settle(page)
    shot("04-step1-your-kitchen", full=True)

    page.goto(f"{base}/#/p/{pid}/surfaces/{photo}")
    expect(page.locator(".quad-editor svg")).to_be_visible(timeout=20000)
    settle(page)
    shot("05-step2-surfaces", full=True)

    page.evaluate("sessionStorage.setItem('renovai.style', 'calido')")
    page.goto(f"{base}/#/p/{pid}/finishes/{photo}")
    expect(page.locator("article.suggestion")).to_have_count(3, timeout=20000)
    settle(page)
    shot("06-step3-style-and-suggestions", full=True)
    page.get_by_role("tab", name="Catálogo completo").click()
    page.locator(".swatch-card").nth(9).click()
    expect(page.locator(".choice-bar")).to_be_visible()
    settle(page, 500)
    shot("07-step3-full-catalogue")

    page.goto(f"{base}/#/p/{pid}/styles/{photo}")
    expect(page.locator(".board-card img")).to_have_count(4, timeout=20000)
    settle(page, 1200)
    shot("08-four-styles-board", full=True)

    page.goto(f"{base}/#/d/{did}")
    expect(page.locator(".review .canvas-img").nth(1)).to_be_visible(timeout=20000)
    settle(page, 1400)
    shot("09-design-review")
    page.locator(".review .ptag[data-item=countertop]").click()
    expect(page.locator("aside.sheet")).to_be_visible()
    settle(page, 500)
    shot("10-design-review-surface-sheet")
    page.locator("aside.sheet .edge-link").click()
    expect(page.locator("aside.sheet .edge-options")).to_be_visible()
    settle(page, 400)
    shot("10b-design-review-edge-sheet")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Comparar").click()
    page.locator(".review .canvas input[type=range]").fill("50")
    settle(page, 300)
    shot("11-design-review-before-after")
    page.get_by_role("button", name="Comparar").click()
    page.get_by_role("button", name="Ver cotización completa").click()
    expect(page.locator(".quote-full")).to_be_visible()
    settle(page, 400)
    if phone:  # the floating price bar would land mid-page in a full-page capture
        page.add_style_tag(content=".mobile-bar { display: none !important; }")
    shot("12-design-review-full-quote", full=True)

    page.evaluate("window.scrollTo(0, 0)")
    page.locator(".quote-actions").get_by_role("button", name="Compartir").click()
    expect(page.locator(".share-link input")).not_to_have_value("", timeout=10000)
    settle(page, 400)
    shot("13-share-dialog")
    page.locator(".modal").get_by_role("button", name="Cerrar").click()

    page.goto(f"{base}/#/d/{did}/print")
    expect(page.locator(".print-sheet")).to_be_visible(timeout=20000)
    settle(page, 1000)
    shot("14-printable-quote", full=True)

    page.goto(f"{base}/#/s/{p['share']}")
    expect(page.locator(".review .canvas-img").nth(1)).to_be_visible(timeout=20000)
    settle(page, 1200)
    shot("15-shared-view")

    page.goto(f"{base}/#/d/{did}")
    expect(page.locator(".review .canvas-img").nth(1)).to_be_visible(timeout=20000)
    page.locator(".quote-card .btn-accent").click()
    page.get_by_label("Nombre").fill("Ana López")
    page.get_by_label("Teléfono").fill("33 1234 5678")
    page.get_by_label("Dirección").fill("Av. Patria 123, Zapopan, Jal.")
    page.get_by_label("¿Cuándo te conviene?").fill("Sábado por la mañana")
    settle(page, 400)
    shot("16-booking-form")
    page.get_by_role("button", name="Reservar visita", exact=True).last.click()
    expect(page.locator(".booked")).to_be_visible(timeout=10000)
    settle(page, 500)
    shot("17-booking-done")

    if STAFF_TOKEN:
        page.goto(f"{base}/#/staff")
        page.evaluate("sessionStorage.removeItem('renovai.staff')")
        page.reload()
        page.get_by_placeholder("Clave del equipo").fill(STAFF_TOKEN)
        page.get_by_role("button", name="Entrar").click()
        row = page.locator(".visit-list button", has_text="Ana López").first
        expect(row).to_be_visible(timeout=10000)
        settle(page, 300)
        shot("18-staff-visit-requests")
        row.click()
        expect(page.locator(".visit-detail h2", has_text="Ana López")).to_be_visible(timeout=10000)
        settle(page, 800)
        shot("19-staff-visit-detail", full=True)


def run(base: str, out: Path) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        errors: list[str] = []
        project: dict | None = None
        cookies = None
        for name, (viewport, scale) in VIEWPORTS.items():
            ctx = browser.new_context(viewport=viewport, device_scale_factor=scale, is_mobile=name == "mobile",
                                      has_touch=name == "mobile")
            if cookies:
                ctx.add_cookies(cookies)  # same owner, so both viewports see the same project
            if project is None:
                ctx.request.get(f"{base}/api/health")
                project = set_up(ctx, base)
                cookies = ctx.cookies()
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(f"{name}: {e}"))
            folder = out / name
            folder.mkdir(parents=True, exist_ok=True)
            capture(page, base, project, folder, phone=name == "mobile")
            ctx.close()
        browser.close()
        if errors:
            raise SystemExit("page errors:\n" + "\n".join(errors))
    print("screens written to", out)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765",
        Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "samples" / "out" / "screens")
