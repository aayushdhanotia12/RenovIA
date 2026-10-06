"""End-to-end: the whole customer flow through the HTTP API, offline (mock models)."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app

REPO = Path(__file__).resolve().parents[2]
PHOTO = REPO / "samples" / "kober_photos" / "p7_0_1920x1200.jpg"


def wait_job(client: TestClient, jid: str, timeout_s: float = 120) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{jid}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {jid} did not finish")


class ApiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        settings = Settings(data_dir=Path(cls.tmp.name), ai_mode="mock", staff_token="s3cret-token")
        cls.app = create_app(settings)
        cls.client = TestClient(cls.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.tmp.cleanup()

    def test_full_flow_photo_to_render_and_quote(self):
        c = self.client
        pid = c.post("/api/projects").json()["id"]

        r = c.put(f"/api/projects/{pid}/measurements", json={
            "countertop_runs": [{"run_id": "A", "length_mm": 3600, "depth_mm": 645}],
            "splash_runs": [{"run_id": "S1", "length_mm": 3000, "height_mm": 600}], "sinks": 1})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["measurements"]["scale_confidence"], "low")
        self.assertEqual(r.json()["questions"], [])

        with PHOTO.open("rb") as f:
            photo = c.post(f"/api/projects/{pid}/photos", files={"file": ("kitchen.jpg", f, "image/jpeg")}).json()
        self.assertEqual(photo["checks"]["light"], "pass")

        job = wait_job(c, c.post(f"/api/projects/{pid}/analyse", json={"photo_id": photo["id"]}).json()["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        items = job["result"]["surfaces"]
        self.assertEqual(sorted(i["surface_class"] for i in items), ["backsplash", "countertop"])

        r = c.put(f"/api/projects/{pid}/surfaces", json={"photo_id": photo["id"], "items": items})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["confirmed"])

        job = wait_job(c, c.post(f"/api/projects/{pid}/suggest", json={"style": "mármol blanco"}).json()["job_id"])
        suggestions = job["result"]["suggestions"]
        self.assertEqual(len(suggestions), 3)
        self.assertEqual(suggestions[0]["countertop_finish_id"], "estilo-caracatta")
        self.assertTrue(all("price" not in s for s in suggestions))

        job = wait_job(c, c.post(f"/api/projects/{pid}/designs", json={
            "photo_id": photo["id"], "countertop_finish_id": "estilo-caracatta", "profile_id": "original_q",
            "splash_finish_id": "estilo-caracatta"}).json()["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        did = job["result"]["design_id"]

        dsg = c.get(f"/api/designs/{did}").json()
        layers = dsg["manifest"]["layers"]
        self.assertEqual(sorted(layer["surface_class"] for layer in layers), ["backsplash", "countertop"])
        self.assertTrue(all(len(layer["polygon"]) >= 3 and isinstance(layer["area_mm2"], int) for layer in layers))
        quote = dsg["quote"]
        self.assertTrue(quote["estimate_only"])
        self.assertLess(quote["estimate"]["low"]["minor"], quote["estimate"]["high"]["minor"])
        self.assertEqual(quote["price_list_status"], "PLACEHOLDER")
        self.assertEqual(dsg["model_versions"]["renderer"], "composite-v3")
        # The sample photo has a stored lighting-model result, so the render used it and says so.
        self.assertEqual(dsg["model_versions"]["lighting"], "mock:stored-marigold-iid-lighting")
        self.assertEqual(c.get(dsg["manifest"]["image"]["url"]).status_code, 200)
        # One labelled pointer per priced thing, each pointing at an item the quote prices.
        pointers = dsg["manifest"]["pointers"]
        self.assertEqual(sorted(p["item"] for p in pointers), ["backsplash", "countertop", "profile", "sink"])
        self.assertTrue({p["item"] for p in pointers} - {"profile"} <= {it["item"] for it in quote["items"]})
        self.assertEqual(sum(it["total"]["minor"] for it in quote["items"]), quote["total"]["minor"])
        self.assertTrue(all("price" not in p and "total" not in p for p in pointers))  # prices live in the quote only

        events =c.get(f"/api/jobs/{job['id']}/events").text
        seqs = [json.loads(line[6:])["seq"] for line in events.splitlines() if line.startswith("data: ")]
        self.assertEqual(seqs, sorted(seqs))
        self.assertIn('"stage": "JOB", "status": "done"', events)

        replay = c.get(f"/api/jobs/{job['id']}/events", headers={"Last-Event-ID": str(seqs[-2])}).text
        self.assertEqual(len([ln for ln in replay.splitlines() if ln.startswith("data: ")]), 1)

        # A second browser cannot see any of it.
        with TestClient(self.app) as other:
            self.assertEqual(other.get(f"/api/projects/{pid}").status_code, 404)
            self.assertEqual(other.get(f"/api/designs/{did}").status_code, 404)
            self.assertEqual(other.get(dsg["manifest"]["image"]["url"]).status_code, 404)
            self.assertEqual(other.get(f"/api/jobs/{job['id']}").status_code, 404)

        booking = c.post(f"/api/projects/{pid}/bookings", json={
            "design_id": did, "name": "Ana López", "phone": "+52 33 1234 5678",
            "address": "Av. Patria 123, Zapopan", "preferred_window": "weekday mornings"})
        self.assertEqual(booking.status_code, 201, booking.text)
        self.assertEqual(c.get("/api/staff/bookings").status_code, 403)
        staff = c.get("/api/staff/bookings", headers={"X-Staff-Token": "s3cret-token"}).json()
        self.assertEqual(staff["bookings"][0]["name"], "Ana López")

    def test_style_board_renders_minimalist_warm_contrast_and_statement_designs(self):
        c = self.client
        pid = c.post("/api/projects").json()["id"]
        c.put(f"/api/projects/{pid}/measurements", json={
            "countertop_runs": [{"run_id": "A", "length_mm": 3600, "depth_mm": 645}],
            "splash_runs": [{"run_id": "S1", "length_mm": 3000, "height_mm": 600}], "sinks": 1})
        with PHOTO.open("rb") as f:
            photo = c.post(f"/api/projects/{pid}/photos", files={"file": ("kitchen.jpg", f, "image/jpeg")}).json()
        job = wait_job(c, c.post(f"/api/projects/{pid}/analyse", json={"photo_id": photo["id"]}).json()["job_id"])
        c.put(f"/api/projects/{pid}/surfaces", json={"photo_id": photo["id"], "items": job["result"]["surfaces"]})

        job = wait_job(c, c.post(f"/api/projects/{pid}/styles", json={"photo_id": photo["id"]}).json()["job_id"], 300)
        self.assertEqual(job["status"], "done", job.get("error"))
        board = job["result"]["board"]
        self.assertEqual([b["style_id"] for b in board], ["minimalista", "calido", "contraste", "creativo"])
        self.assertEqual([b["countertop_finish_id"] for b in board],
                         ["estilo-india-white", "estilo-rovere-slavonia", "estilo-black-kandia", "diseno-calcatta-oro"])
        for b in board:
            self.assertEqual(c.get(b["image_url"]).status_code, 200)
            self.assertLess(b["estimate"]["low"]["minor"], b["estimate"]["high"]["minor"])
            self.assertNotIn("price", b)
        self.assertEqual(c.get(f"/api/projects/{pid}").json()["style_board"]["items"], board)
        catalogue = c.get("/api/catalogue").json()
        self.assertEqual([s["id"] for s in catalogue["styles"]], ["minimalista", "calido", "contraste", "creativo"])
        # The landing page states the visit rule with the sheet's fee, IVA included.
        self.assertEqual((catalogue["visit_fee"]["minor"], catalogue["visit_fee_rule"]), (58000, "free_if_hired"))
        self.assertEqual({p["id"]: p["edge_shape"] for p in catalogue["profiles"]}["original"], "rounded")

    def test_float_length_is_refused(self):
        pid = self.client.post("/api/projects").json()["id"]
        r = self.client.put(f"/api/projects/{pid}/measurements",
                            json={"countertop_runs": [{"run_id": "A", "length_mm": 2300.5}]})
        self.assertEqual(r.status_code, 422)

    def test_unusual_depth_raises_a_question_not_a_block(self):
        pid = self.client.post("/api/projects").json()["id"]
        r = self.client.put(f"/api/projects/{pid}/measurements",
                            json={"countertop_runs": [{"run_id": "A", "length_mm": 2300, "depth_mm": 900}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["questions"][0]["id"], "A-depth")

    def test_basik_finish_in_a_non_basik_profile_is_refused(self):
        pid = self.client.post("/api/projects").json()["id"]
        with PHOTO.open("rb") as f:
            photo = self.client.post(f"/api/projects/{pid}/photos", files={"file": ("k.jpg", f, "image/jpeg")}).json()
        r = self.client.post(f"/api/projects/{pid}/designs", json={
            "photo_id": photo["id"], "countertop_finish_id": "basik-almond-leather", "profile_id": "original_q"})
        self.assertEqual(r.status_code, 400)

    def test_not_a_photo_is_refused_with_a_readable_message(self):
        pid = self.client.post("/api/projects").json()["id"]
        r = self.client.post(f"/api/projects/{pid}/photos", files={"file": ("x.txt", b"hello", "text/plain")})
        self.assertEqual(r.status_code, 415)


if __name__ == "__main__":
    unittest.main()
