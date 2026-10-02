"""Browser smoke test: click through the whole customer flow and the team's side, saving screenshots.

Needs a running server in mock mode:
    RENOVAI_AI_MODE=mock RENOVAI_STAFF_TOKEN=demo uvicorn --factory backend.app.main:create_app --port 8765
Then:
    RENOVAI_STAFF_TOKEN=demo python web/e2e/smoke.py http://127.0.0.1:8765 out_dir
(Without the token the staff checks are skipped.)

The flow: landing (demo hotspots, style chip, photo drop) -> measurements -> surfaces ->
style step (suggestions, catalogue) -> one design -> the 4-style board -> design review
(hotspot sheet, before/after, share on WhatsApp, printable quote, booking) -> the shared
link opened by someone else -> phone layouts -> staff (schedule, record the visit, final
quote, print) -> English.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import Page, expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
PHOTO = REPO / "samples" / "kober_photos" / "p7_0_1920x1200.jpg"
# The staff side is checked only when the server under test was given a staff token.
STAFF_TOKEN = os.environ.get("RENOVAI_STAFF_TOKEN", "")


def settle(page: Page, ms: int = 700) -> None:
    """Let images decode and entrance animations finish before a screenshot."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def run(base: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
        shot = lambda name, **kw: page.screenshot(path=str(out / name), **kw)  # noqa: E731

        # ---------------------------------------------------------------- landing
        page.goto(base + "/#/")
        expect(page.get_by_role("heading", level=1)).to_contain_text("Tu cocina")
        settle(page, 1200)
        shot("01_home.png")
        shot("01b_home_full.png", full_page=True)
        page.locator(".demo-rows button").first.click()
        expect(page.locator(".hot-chip")).to_be_visible()
        page.locator("#demo").scroll_into_view_if_needed()
        settle(page, 400)
        shot("02_home_demo.png")

        page.evaluate("window.scrollTo(0, 0)")
        page.get_by_role("radio", name="Cálido natural").click()
        page.locator(".prompt input[type=file]").set_input_files(str(PHOTO))

        # ---------------------------------------------------------------- step 1
        expect(page.get_by_role("heading", name="Cuéntanos de tu cocina")).to_be_visible(timeout=20000)
        expect(page.locator(".dropzone-img")).to_be_visible(timeout=20000)
        runs = page.locator(".run-row input")
        runs.nth(0).fill("360")   # countertop A length, cm
        runs.nth(2).fill("300")   # backsplash S1 length, cm
        settle(page)
        shot("03_measure.png", full_page=True)
        page.get_by_role("button", name="Buscar la cubierta en la foto").click()
        try:
            expect(page.locator(".working")).to_be_visible(timeout=3000)
            shot("04_working.png")
        except AssertionError:
            pass  # the mock pipeline can finish before the progress view is painted

        # ---------------------------------------------------------------- step 2
        expect(page.get_by_role("heading", name="¿Encontramos bien tu cubierta?")).to_be_visible(timeout=60000)
        settle(page)
        shot("05_surfaces.png", full_page=True)
        page.get_by_role("button", name="Sí, están bien").click()

        # ---------------------------------------------------------------- step 3
        expect(page.get_by_role("heading", name="¿Qué estilo te gusta?")).to_be_visible(timeout=20000)
        expect(page.locator(".style-card.on")).to_have_count(1)  # the chip picked on the landing page
        expect(page.locator(".style-card.on")).to_contain_text("Cálido natural")
        page.get_by_placeholder("Ej. que combine con piso gris").fill("fácil de limpiar")
        page.get_by_role("button", name="Sugerencias cálido natural").click()
        expect(page.locator("article.suggestion")).to_have_count(3, timeout=60000)
        settle(page)
        shot("06_style_step.png", full_page=True)

        page.get_by_role("tab", name="Catálogo completo").click()
        page.locator(".swatch-card").first.click()
        expect(page.locator(".choice-bar")).to_be_visible()
        settle(page, 400)
        shot("07_catalogue.png")
        page.get_by_role("tab", name="Estilos").click()

        # one design from a suggestion
        page.locator("article.suggestion").first.get_by_role("button").click()
        expect(page.locator(".review .canvas-img").nth(1)).to_be_visible(timeout=180000)
        settle(page, 1200)
        shot("08_result_suggestion.png")
        page.locator(".review-head .link-back").click()

        # the four styles at once
        expect(page.get_by_role("heading", name="¿Qué estilo te gusta?")).to_be_visible(timeout=20000)
        page.get_by_role("button", name="Ver mi cocina en los 4 estilos").click()
        try:
            expect(page.locator(".working")).to_be_visible(timeout=3000)
            page.wait_for_timeout(1500)
            shot("09_working_styles.png")
        except AssertionError:
            pass
        expect(page.get_by_role("heading", name="Tu cocina en 4 estilos")).to_be_visible(timeout=240000)
        expect(page.locator(".board-card img")).to_have_count(4)
        settle(page, 1000)
        shot("10_board.png", full_page=True)
        page.locator(".board-card", has_text="Contraste").click()

        # ---------------------------------------------------------------- step 4: design review
        expect(page.locator(".review .canvas-img").nth(1)).to_be_visible(timeout=20000)
        expect(page.locator(".review-head .pill-tabs button.on")).to_have_text("Contraste")
        settle(page, 1200)
        shot("11_result.png")
        design_url = page.url
        page.locator("polygon.hotspot").last.click()
        expect(page.locator("aside.sheet")).to_be_visible()
        settle(page, 400)
        shot("12_hotspot_sheet.png")
        page.keyboard.press("Escape")
        expect(page.locator("aside.sheet")).to_have_count(0)

        page.get_by_role("button", name="Comparar").click()
        page.locator(".review .canvas input[type=range]").fill("50")
        settle(page, 300)
        shot("13_before_after.png")
        page.get_by_role("button", name="Comparar").click()

        page.get_by_role("button", name="Ver cotización completa").click()
        expect(page.locator(".quote-full")).to_be_visible()
        settle(page, 300)
        shot("14_full_quote.png", full_page=True)

        # share on WhatsApp: a read-only link in a wa.me message
        page.locator(".quote-actions").get_by_role("button", name="Compartir").click()
        wa = page.locator("a[data-share=whatsapp]")
        expect(wa).to_have_attribute("href", re.compile(r"^https://wa\.me/\?text="), timeout=10000)
        text = unquote(parse_qs(urlparse(wa.get_attribute("href")).query)["text"][0])
        share_url = re.search(r"https?://\S+/#/s/[0-9a-f]+", text).group(0)
        settle(page, 300)
        shot("15_share.png")
        page.locator(".modal").get_by_role("button", name="Cerrar").click()

        # printable quote
        page.locator(".quote-actions").get_by_role("button", name="Imprimir").click()
        expect(page.locator(".print-sheet")).to_be_visible(timeout=10000)
        expect(page.locator(".print-sheet")).to_contain_text("Cotización estimada")
        expect(page.locator(".print-sheet table.lines").first).to_be_visible()
        settle(page, 800)
        shot("16_print.png", full_page=True)
        page.emulate_media(media="print")
        settle(page, 200)
        shot("16b_print_media.png", full_page=True)
        page.emulate_media(media="screen")
        page.goto(design_url)
        expect(page.locator(".review .canvas-img").nth(1)).to_be_visible(timeout=20000)

        page.get_by_role("button", name="Reservar visita de medición").click()
        page.get_by_label("Nombre").fill("Ana López")
        page.get_by_label("Teléfono").fill("33 1234 5678")
        page.get_by_label("Dirección").fill("Av. Patria 123, Zapopan, Jal.")
        settle(page, 300)
        shot("17_booking.png")
        page.get_by_role("button", name="Reservar visita", exact=True).click()
        expect(page.locator(".booked")).to_be_visible(timeout=10000)
        settle(page, 400)
        shot("18_booked.png")
        page.locator(".modal").get_by_role("button", name="Cerrar").click()

        # ---------------------------------------------------------------- shared link, another person
        other = browser.new_context(viewport={"width": 1440, "height": 900})
        op = other.new_page()
        op.on("pageerror", lambda e: errors.append(f"shared pageerror: {e}"))
        op.goto(share_url.replace(re.match(r"https?://[^/]+", share_url).group(0), base))
        expect(op.get_by_text("Un diseño de cocina compartido contigo")).to_be_visible(timeout=20000)
        expect(op.locator(".review .canvas-img").nth(1)).to_be_visible()
        op.wait_for_load_state("networkidle")
        op.wait_for_timeout(900)
        op.screenshot(path=str(out / "19_shared_view.png"))
        other.close()

        # ---------------------------------------------------------------- phone
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload()  # goto(page.url) with a #hash is a same-document navigation and keeps state
        expect(page.locator(".review .canvas-img").nth(1)).to_be_visible(timeout=20000)
        settle(page, 1200)
        shot("20_result_phone.png", full_page=True)
        page.goto(base + "/#/")
        expect(page.get_by_role("heading", level=1)).to_contain_text("Tu cocina")
        settle(page, 1000)
        shot("21_home_phone.png")
        page.set_viewport_size({"width": 1440, "height": 900})

        # ---------------------------------------------------------------- staff
        if STAFF_TOKEN:
            page.goto(base + "/#/staff")
            page.get_by_placeholder("Clave del equipo").fill(STAFF_TOKEN)
            page.get_by_role("button", name="Entrar").click()
            row = page.locator(".visit-list button", has_text="Ana López").first
            expect(row).to_be_visible(timeout=10000)
            expect(page.locator(".price-strip")).to_contain_text("Precios de ejemplo")
            row.click()
            expect(page.locator(".visit-detail h2", has_text="Ana López")).to_be_visible(timeout=10000)
            wa_visit = page.locator(".contact-actions a", has_text="WhatsApp")
            expect(wa_visit).to_have_attribute("href", re.compile(r"^https://wa\.me/523312345678\?text="))
            page.get_by_label("Fecha y hora de la visita").fill("2026-10-06T10:00")
            page.get_by_label("Quién va").fill("Luis")
            page.locator(".visit-detail .card").nth(1).get_by_role("button", name="Guardar").click()
            expect(page.locator(".visit-list button.on .status-pill")).to_have_text("Agendada", timeout=10000)
            settle(page, 500)
            shot("22_staff.png", full_page=True)

            visit = page.locator("form.card")
            visit.locator(".visit-run").first.get_by_label("Largo").fill("365")
            visit.get_by_label("Midió").fill("Luis")
            visit.get_by_role("button", name="Guardar visita y cotización final").click()
            expect(page.locator(".final-figure")).to_be_visible(timeout=15000)
            expect(page.locator(".delta-table")).to_contain_text("+5 cm")
            expect(page.locator(".visit-list button.on .status-pill")).to_have_text("Visitada")
            settle(page, 500)
            shot("23_staff_final_quote.png", full_page=True)
            page.get_by_role("button", name="Imprimir cotización final").click()
            expect(page.locator(".print-sheet")).to_contain_text("Cotización final", timeout=10000)
            expect(page.locator(".print-sheet")).to_contain_text("Ana López")
            settle(page, 800)
            shot("24_staff_print.png", full_page=True)

        # ---------------------------------------------------------------- English
        page.goto(base + "/#/")
        page.get_by_role("button", name="English").click()
        expect(page.get_by_role("heading", level=1)).to_contain_text("Your kitchen")
        page.get_by_role("button", name="Español").click()
        expect(page.get_by_role("heading", level=1)).to_contain_text("Tu cocina")

        if errors:
            raise SystemExit("page errors:\n" + "\n".join(errors))
        browser.close()
    print("smoke test passed; screenshots in", out)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765",
        Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "samples" / "out" / "e2e")
