# RenovAI prototype: instructions for Claude Code

Read `README.md` for the flow, `DECISIONS.md` for why the prototype differs from the long-term spec, and `PROTOTYPE-PLAN.md` for what comes next. The long-term spec (ARCHITECTURE, MEASUREMENT, UI-SPEC, AI-MODELS, PLAN) lives in the "Proyct IA" project; its invariants apply here unless DECISIONS.md says otherwise.

## Invariants: a change that breaks one is wrong even if tests pass

- **Renders show only buyable products.** Surfaces are composited from catalogue finish images (`renderer/`). Any AI image pass must paste the product layers back afterwards, and `assert_outside_unchanged` must keep passing on every render.
- **The model proposes, the platform prices.** Model outputs are ids and words. `backend/app/ai/suggester.py` validates every answer against the catalogue and availability. Never add a price, total, quantity or waste field to a model schema.
- **`backend/app/quote.py` is the only code that multiplies by a price.** Prices come from `catalog/kober/data/prices*.json` (written by `catalog/kober/price_sheet.py` from the team's sheet), never from a request or a model. The importer only parses and validates; it never computes a price.
- **Integer millimetres and integer centavos everywhere.** Use `Money`, `div_round_half_up` and `StrictInt` fields. No floats in money or lengths; the sheet importer goes through `Decimal` strings.
- **Estimates carry a range until a site visit.** `scale_confidence` is `low` for typed measurements; only `price_quote(..., final=True)` (the staff visit) removes the range, and the customer's own design keeps its estimate.
- **Owner scoping.** Every customer store read takes the owner; media is served only to the project's owner. Share links expose one design and no personal data. Staff routes check the team key; staff media goes through signed, expiring links.
- **Record model and price versions.** Designs store `model_versions` including `price_list`; keep adapters' `model_id` accurate.

## Commands

- `make test`: all Python tests (unittest; offline). Run before every commit.
- `make run`, then `make e2e`: browser smoke test in mock mode. Run after any UI or API change. Set `RENOVAI_STAFF_TOKEN` for both to include the staff side.
- `cd web && npm run build && npm run typecheck`: rebuild the web app and check types.
- `make models PHOTO=...`: try live SAM 3 + Claude on one photo (needs keys).
- `make prices SHEET=...`: import the team's price sheet (Google Sheets link, .xlsx, or a folder of CSV exports).
- `make catalogue PDF=...`: extract the real Kober swatches; then delete `backend/tests/golden/`, re-run `make test`, look at the new golden image, and run `python samples/make_demo_assets.py`.

## Conventions

- Backend: Python 3.11+, Starlette, pydantic v2 (`extra="forbid"`), sync pipeline functions run as jobs in threads (`jobs.py`), progress stages `GEOMETRY`, `DESCRIBE`, `DESIGN`, `RENDER`, `QUOTE`. Settings come from `RENOVAI_*` environment variables or `.env` (`config.py`, no pydantic-settings).
- HTTP client: `httpx2` if installed, else `httpx` (same API).
- Frontend: React, hash routes, strings in `web/src/i18n.ts` (Spanish first; add English alongside). Design tokens live in `web/src/styles.css`; the design review and the shared view are always dark; print styles live under `@media print`. `web/public/` is copied into `dist/` (fonts, the landing demo).
- Claude calls go through `AnthropicClient.json_call` (structured outputs, `output_config.format`). Don't force a tool call or set `temperature`: Claude Sonnet 5.5 rejects both with a 400. Read response blocks by type; thinking blocks can come first.
- Tests are named after their worked example (e.g. `test_run_2300mm_..._is_one_3000mm_piece_at_5670_mxn`).
- The golden render (`backend/tests/golden/`) changes only on purpose: delete it, re-run, look at the new image, then commit.

## Quality first, then cost

- Don't ship a weaker version of something the product needs to save money or time (a fixed object list instead of looking at the photo, a guessed length, a cheaper model that does the job worse). If we need it, we build it properly, and then make it cheaper without losing quality: self-hosting, caching, batching.
- Don't propose shortcuts that compromise quality or long-term sustainability unless they bring a clear short-term benefit to customers, and say what they cost.

## Ask rather than guess

- Real prices, the countertop allowance (10% is a placeholder instruction), labour rates, booking fee, IVA display: these belong in the team's sheet.
- Which Kober finishes are made in which profiles and lengths when the catalogue is silent.
- Anything that changes what a customer is charged.
