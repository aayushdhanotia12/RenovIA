# RenovAI prototype: kitchen countertops with Kober finishes

A customer uploads a photo of their kitchen and types the countertop lengths. The app finds the countertop and backsplash, lets them fix the outline, suggests Kober finishes (or lets them pick from the full catalogue), and shows the kitchen rendered with the real finish. One click shows the same kitchen in four styles side by side. Every surface is clickable, and a quote comes back in pieces, installation and IVA. The customer can share the design on WhatsApp, print the quote, and request your team's measuring visit. Your team then schedules the visit, records what they measured, and gets the final quote in the same app.

## Status, 2 Oct 2026

- **Works end to end offline.** Photo, surfaces, suggestions or the four-style board, render, quote, share link, printable quote, visit request, then the team's side: schedule, visit, final quote. 80 Python tests pass, as does a Chromium smoke test (`web/e2e/smoke.py`) that clicks through all of it, the phone layouts and the English toggle.
- **New since 29 Sep:** the price & rules sheet for the team (`catalog/kober/price_sheet.py`), the staff view with scheduling and the visit's final quote, WhatsApp sharing with a read-only link, and printable quotes. See "For your team" below.
- **Rebuilt on 2 Oct from the project copy.** The Kober catalogue PDF wasn't available, so the finish images in `catalog/kober/swatches/` are drawn stand-ins (marked by `swatches/PLACEHOLDER`, and the catalogue screen says "texturas de muestra"). Run `make catalogue PDF=...` with the Kober PDF to put the real ones back. The sample photo was rebuilt from the saved comparison grid at half resolution, scaled up.
- **Live models are wired but not yet run against the real APIs.** The first job with keys is `make models PHOTO=...`.
- **Prices are placeholders** until the team's sheet is imported, and every quote says so.

## Quick start

```bash
cp .env.example .env
make setup        # pip install + npm install + build the web app
make test         # all tests, offline, about 2 minutes
make run          # http://127.0.0.1:8000
```

No Node.js? The web app ships prebuilt in `web/dist`, so `pip install -r requirements.txt` then `make run` is enough.

With `RENOVAI_AI_MODE=mock` (the default), upload `samples/kober_photos/p7_0_1920x1200.jpg` to see the full flow with detected surfaces. Any other photo works too: place the surfaces by hand on the "check the surfaces" screen.

**Live mode:** set `RENOVAI_AI_MODE=live`, `FAL_KEY` and `ANTHROPIC_API_KEY`, then check the models on a real photo first with `make models PHOTO=path/to/kitchen.jpg`. It prints what SAM 3 found and what Claude suggests, and writes an overlay image showing the masks.

## For your team

### The price & rules sheet

Every business number lives in one workbook the team fills in: Kober's cost for each countertop piece (price category x width x length, in Original Q), each profile's price against Original Q, Spläsh panel costs, the margin per category, labour, booking fees, IVA, the cutting allowance, and each finish's price category and availability.

1. The template is `catalog/kober/precios_renovai_plantilla.xlsx` (regenerate it with `python catalog/kober/price_sheet.py template out.xlsx`). Yellow cells are example values; the `Leeme` tab explains every tab.
2. Upload it to Google Drive and open it as a Google Sheet. Fill it in, leaving `estado` as `BORRADOR` while you check it.
3. Share it as "anyone with the link can view", and paste the link on the staff page under "Importar hoja de precios" (or set `RENOVAI_PRICE_SHEET_URL`). From the command line: `make prices SHEET=<link or .xlsx>`.
4. The import checks everything: every piece size a finish can need, numbers that are numbers, known categories, Basi-K rules. If anything is missing it lists what to fix and keeps the old prices.
5. Quotes from a `BORRADOR` sheet say "prices in review". Set `estado` to `VIGENTE` when the prices are real. `iva_confirmado = si` changes the IVA note to "IVA included".

All arithmetic stays in `backend/app/quote.py`: piece price = Kober cost x profile factor x (1 + margin), in whole centavos. A piece the sheet doesn't price is refused, never guessed.

### The staff view

Set `RENOVAI_STAFF_TOKEN`, open `/#/staff` and type the token. For each visit request you get the customer's photo, the render, the finishes and the range they saw, with buttons to call, open WhatsApp with a message ready, or open the address in Maps. Then:

- **Schedule it:** date and time, who goes, team notes, and status (new, scheduled, visited, cancelled).
- **Record the visit:** type what the team measured (prefilled with the customer's numbers). The design is priced again as a final quote, with no range, and the page shows the difference from what the customer typed, per run, and whether the final price landed inside the range they were shown. Print it or send it on WhatsApp.

The difference per run is kept on every visit. It is the honest measure of how good typed measurements are (MEASUREMENT.md), and it is what the launch gate is judged on.

### Sharing and printing (customers)

On the design review, **Compartir** makes a read-only link to that design (render, finishes, quote; never the customer's name or phone) and opens WhatsApp with a message ready. **Imprimir** opens a quote page laid out for A4 that prints or saves as PDF from the browser. Set `RENOVAI_PUBLIC_URL` to the app's public address so shared links point there.

## How it works

| Step | What runs | Model? |
|---|---|---|
| Photo checks | Brightness, sharpness, camera data (`photo_checks.py`) | No |
| Find surfaces | SAM 3 on fal.ai, prompted "kitchen countertop" and "kitchen backsplash"; the outline becomes four draggable corners | SAM 3 |
| Describe the kitchen | Claude looks at cabinets, floor and walls, for the suggestions | Claude Sonnet 5.5 |
| Suggest finishes | Claude picks 3 combinations from the available Kober finishes, answering in JSON whose schema only allows catalogue ids (structured outputs) | Claude Sonnet 5.5 |
| Four styles at once | For each preset (Minimalista, Cálido natural, Contraste, Creativo, `styles.py`), one suggestion is rendered and priced like any design | Claude Sonnet 5.5 |
| Render | Finish image grown into a large non-repeating texture, warped onto each surface at real size, room lighting kept, plus reflections, contact shadows and matched grain (`renderer/`, `composite-v2`) | **No**: deterministic |
| Quote | Standard piece lengths per run, Spläsh panels, allowance, installation, IVA, estimate range (`quote.py`), from the team's price sheet | **No** |
| Final quote | The team's measurements, priced the same way with `final=True` (`staff.py`) | **No** |

Every model sits behind a small adapter in `backend/app/ai/`. Moving to self-hosted open-source models later (SAM 3 weights, Qwen) means writing one new adapter, not touching the flow.

## The web app

Spanish first, with an English toggle. Design tokens (warm neutrals, one clay accent, motion, the always-dark design review) come from UI-SPEC and live in `web/src/styles.css`; the look follows the Lovable reference.

- **Landing:** drop a photo into the prompt box, a live demo where every surface is clickable, how it works, the four styles, and what it costs.
- **Step 1–3:** photo and run lengths, surfaces as draggable corners, style cards or the full catalogue (finishes the team marked unavailable are greyed out).
- **Step 4, design review:** hotspots, product sheet, before/after, the quote range, full quote, share, print, and the visit request.
- **Shared link** (`#/s/<id>`): the design, read-only, with "design your kitchen".
- **Printable quote** (`#/d/<id>/print`) and the team's final quote (`#/staff/print/<id>`).
- **Staff** (`#/staff`): the visit list, detail, scheduling, visit record and final quote, and the price-sheet import.

## Rules this code keeps

- **What the customer sees is buyable.** Renders are built from the catalogue finish image, and no pixel outside a product surface changes. `assert_outside_unchanged` runs on every render, and a golden-image test guards against drift.
- **The model proposes, the platform prices.** The suggestion schema has no price, total or currency field. Answers are validated against the catalogue (and availability), and `quote.py` is the only code that multiplies by a price.
- **Money is whole centavos, lengths are whole millimetres.** A float is refused at the API, including the visit form; the sheet importer reads amounts as decimal strings, never floats.
- **Typed measurements never look precise.** Quotes show a range until the team's measurements produce the final quote.
- **Nobody sees another customer's project.** Every customer query is scoped by the browser's owner cookie. Share links show one design and nothing personal. The staff side needs the team key, and its photos are served through signed links that expire.

## Placeholders and assumptions to confirm

- **Prices, installation rates and booking fees:** placeholder MXN numbers until the sheet is imported.
- **IVA 16%**, and whether prices are shown with IVA included (the sheet's `iva_confirmado`).
- **10% allowance on every run.** For countertops this matters: a 3.60 m run becomes 3.96 m and needs a 3.00 m + 1.20 m piece and a joint.
- **Finish images:** stand-ins until the Kober PDF is re-extracted. Finish scale assumes a PDF swatch pixel is 1.5 mm.
- **Price categories:** some finishes have no printed category; the sheet's `Acabados` tab is where the team confirms them.

## Known limitations

- **L-shaped counters and islands:** each run needs its own surface (one detected mask per run). L-shapes haven't been tested on real photos yet.
- **Hand-placed surfaces** repaint everything inside the corners, including objects standing on the counter.
- **Edge profile** changes the price, not the render.
- **Not included yet:** sinks aren't re-rendered, no online payment, no customer accounts (the team shares one key), and everything runs as a single server process.

## Repo map

```
backend/app/         API (Starlette), pipeline, quote engine, catalogue, staff (visit, final quote, signed links), storage, model adapters (ai/)
backend/tests/       unit, quote, price sheet, render (golden image), model, API, staff and share tests
backend/tools/       try_models.py: check live SAM 3 + Claude on one photo; remodel.py: batch remodel with live models
renderer/            compositor (homography, relighting, mask assertion) and texture synthesis
catalog/kober/       PDF extractor, finishes.json (78 finishes), products.json, prices, price_sheet.py + template, placeholder swatches
web/                 React app; styles.css holds the tokens; esbuild build; Playwright smoke and screens tests
samples/             sample photo, offline fixtures, make_demo_assets.py (landing demo), compare_renders.py
```

`DECISIONS.md` lists where the prototype deliberately departs from the long-term spec. `PROTOTYPE-PLAN.md` has the plan to 28 Oct.
