# 30-day prototype plan: 29 Sep – 28 Oct 2026

Target: demo-ready on **Fri 23 Oct**, with a buffer to **Wed 28 Oct**. "Demo-ready" means your field team can take 15–20 real kitchens through photo, render, quote and visit request, and the quotes are ones they would stand behind.

## Done on day 1 (28 Sep)

- Kober catalogue extracted: 78 finishes with images, codes and categories, plus sizes, profiles, Spläsh panels, sinks and rules.
- Render engine working on a real photo: marble, wood and dark finishes on countertop and backsplash, lighting kept, objects left untouched.
- Quote engine: standard pieces, allowance, joints, sinks, Spläsh, installation, IVA, estimate range. Every rule has a test named after its worked example.
- The full app runs offline, from photo to render, quote and visit request, in Spanish with an English toggle.

## Done on day 2 (29 Sep)

- Sharper renders (`composite-v2`): reflections in glossy tops, contact shadows, grain matched to the photo.
- Claude client ready for Claude Sonnet 5.5: answers through structured outputs, with retries only on temporary errors.
- Four styles plus one click that designs, renders and prices the kitchen in all four.
- New interface in the Lovable style, with phone layouts throughout.

## Done on day 5 (2 Oct)

- **Price & rules sheet:** a template workbook for the team (pieces by category x width x length, profiles, Spläsh, margins, labour, fees, IVA, allowance, finish categories and availability), an importer that validates everything, and quotes priced from it. The team imports it from the staff page by pasting the Google Sheets link.
- **Staff view:** visit requests with photo, render, finishes and the range the customer saw; call, WhatsApp and Maps buttons; scheduling, who goes, notes and status.
- **Visit record and final quote:** the team types what they measured, the design is priced again without a range, and the difference from the customer's numbers is kept per run, with whether the final price fell inside the range shown.
- **WhatsApp sharing and printable quotes:** a read-only link per design, and an A4 quote page for customers and for the team's final quote.
- Repo rebuilt from the project copy; real Kober swatches still to restore from the PDF.

## Done on days 6–7 (3–4 Oct)

- Research on the latest tech for each part of the pipeline (in the project: `claude/research/Kitchen visualizer core tech 2026.md`).
- Renders `composite-v3`: the countertop has a real edge and visible ends at the profile's thickness, and the old counter's glare no longer shows as haze on the new finish.
- Objects: Claude lists everything on the counter and backsplash, SAM 3 cuts each one out, so the finish is never painted over a tap, sink, hob or bottle.
- Camera data kept from the photo (with checks), used for the render.
- A GitHub test run for MoGe-2, GeoCalib and Marigold-IID on free-licence kitchen photos (`.github/workflows/model-eval.yml`). GeoCalib matched the photo's own camera data within 7%; Marigold's lighting is now used by the renderer.
- Our own model worker (`workers/gpu`) serving Marigold-IID-Lighting, ready to deploy on Modal once the account exists; the offline mode uses Marigold's stored output for the sample photo.
- Research on competitors' tech and pricing, video capture and Mac mini hosting (project: `claude/research/Competitors video and local hosting.md`).

## Week 1 · 29 Sep – 4 Oct · go live with real models

| Who | What |
|---|---|
| You | Upload the Kober catalogue PDF (CATKBR25AGO26) to the repo or the chat, so the real finish images replace the stand-ins |
| You | Add `ANTHROPIC_API_KEY` and `FAL_KEY` as GitHub repository secrets (Settings > Secrets and variables > Actions) |
| You | 10–20 photos of real kitchens your team has measured, with countertop lengths and depths |
| You | Fill the price sheet: start from `catalog/kober/precios_renovai_plantilla.xlsx` in Google Drive |
| Me | Run `make models` on every photo; tune SAM 3 prompts and thresholds; switch the app to live mode |
| Me | Remodel 8–10 Mexican kitchen photos in the four styles with the live models (`backend/tools/remodel.py`, `.github/workflows/remodel.yml`) |

## Week 2 · 5 – 11 Oct · accuracy on real kitchens

- L-shaped counters and islands: one surface per run, mapped to the measured runs.
- Import the team's price sheet and confirmed rules (allowance, joints, sink service, fees); set it VIGENTE.
- Use full-slab textures at their true scale, if Kober provides them.
- Your field team checks 10 quotes against what they would charge; fix every disagreement.

## Week 3 · 12 – 18 Oct · polish

- Optional AI polish pass (Qwen-Image-Edit) behind a switch, with product pixels pasted back. Keep it only if it looks better.
- Screen polish, photo tips on phones, faster first render (texture cache warmed per finish).
- Visit-accuracy report across visits: median and worst difference per run, share of final prices inside the range.

## Week 4 · 19 – 25 Oct · real-world trial

- Deploy to one cloud server with HTTPS; set `RENOVAI_PUBLIC_URL` so shared links point there.
- Your team runs 15–20 real kitchens end to end, including scheduling and recording visits in the staff view, then 5 people outside the team try it unaided.
- Fix what they hit. **Demo-ready Fri 23 Oct.**

## Buffer · 26 – 28 Oct

Anything that slipped, and demo rehearsal.

## After the prototype

The long plan in the "RenovAI Execution Plan" doc still applies: measurement accuracy tracking (started here with the visit record), payments, phone scanning, and the one fine-tune. It starts from a working product instead of from scratch, and its phases are re-dated when the prototype ends.
