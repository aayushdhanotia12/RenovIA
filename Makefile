PY ?= python3
PORT ?= 8000

.PHONY: setup web test run e2e fixtures catalogue models prices

setup:            ## install Python and web dependencies, build the web app
	$(PY) -m pip install -r requirements-dev.txt
	cd web && npm install && npm run build

web:              ## rebuild the web app into web/dist
	cd web && npm run build

test:             ## unit, render and API tests (offline)
	$(PY) -m unittest discover -s backend/tests -t .

run:              ## start the app on http://127.0.0.1:$(PORT)
	$(PY) -m uvicorn --factory backend.app.main:create_app --reload --port $(PORT)

e2e:              ## click through the whole flow in Chromium (server must be running in mock mode)
	$(PY) web/e2e/smoke.py http://127.0.0.1:$(PORT)

fixtures:         ## rebuild offline fixtures for the sample photo
	$(PY) samples/make_fixtures.py

catalogue:        ## re-extract finishes from the Kober PDF: make catalogue PDF=path/to/catalogo.pdf
	$(PY) catalog/kober/extract_kober.py $(PDF)

models:           ## try the live models on one photo: make models PHOTO=path/to/kitchen.jpg
	$(PY) -m backend.tools.try_models $(PHOTO)

prices:           ## import the team's price sheet: make prices SHEET=path/to/sheet.xlsx (or a Google Sheets CSV export folder)
	$(PY) catalog/kober/price_sheet.py import $(SHEET)
