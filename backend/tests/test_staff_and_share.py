"""Field team view, the visit's final quote, and read-only share links (offline, mock models)."""

import tempfile
import time
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.staff import media_ok, media_signature, whatsapp_number
from backend.tests.test_api import PHOTO, wait_job

TOKEN = "team-key-123"
STAFF = {"X-Staff-Token": TOKEN}


class StaffAndShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = create_app(Settings(data_dir=Path(cls.tmp.name), ai_mode="mock", staff_token=TOKEN,
                                      public_url="https://renovai.example.mx"))
        cls.client = TestClient(cls.app)
        cls.client.__enter__()
        c = cls.client
        cls.pid = c.post("/api/projects").json()["id"]
        c.put(f"/api/projects/{cls.pid}/measurements", json={
            "countertop_runs": [{"run_id": "A", "length_mm": 2300, "depth_mm": 645}],
            "splash_runs": [{"run_id": "S1", "length_mm": 2300, "height_mm": 600}], "sinks": 1})
        with PHOTO.open("rb") as f:
            photo = c.post(f"/api/projects/{cls.pid}/photos", files={"file": ("k.jpg", f, "image/jpeg")}).json()
        job = wait_job(c, c.post(f"/api/projects/{cls.pid}/analyse", json={"photo_id": photo["id"]}).json()["job_id"])
        c.put(f"/api/projects/{cls.pid}/surfaces", json={"photo_id": photo["id"], "items": job["result"]["surfaces"]})
        job = wait_job(c, c.post(f"/api/projects/{cls.pid}/designs", json={
            "photo_id": photo["id"], "countertop_finish_id": "diseno-white-carrara", "profile_id": "original_q",
            "splash_finish_id": "diseno-white-carrara"}).json()["job_id"])
        cls.did = job["result"]["design_id"]
        cls.bid = c.post(f"/api/projects/{cls.pid}/bookings", json={
            "design_id": cls.did, "name": "Ana López", "phone": "33 1234 5678",
            "address": "Av. Patria 123, Zapopan", "preferred_window": "mañanas"}).json()["id"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.tmp.cleanup()

    def test_staff_list_needs_the_team_key_and_shows_the_request_with_a_whatsapp_number(self):
        c = self.client
        self.assertEqual(c.get("/api/staff/bookings").status_code, 403)
        self.assertEqual(c.get("/api/staff/bookings", headers={"X-Staff-Token": "wrong"}).status_code, 403)
        rows = c.get("/api/staff/bookings", headers=STAFF).json()
        row = next(r for r in rows["bookings"] if r["id"] == self.bid)
        self.assertEqual((row["name"], row["whatsapp"]), ("Ana López", "523312345678"))
        self.assertIn(row["status"], ("new", "scheduled", "visited"))  # other tests in this class move it along
        self.assertEqual(row["countertop"]["id"], "diseno-white-carrara")
        self.assertEqual(rows["prices"]["status"], "PLACEHOLDER")
        self.assertEqual(c.get(row["thumb_url"]).status_code, 200)  # signed link, no key in the URL
        self.assertNotIn(TOKEN, row["thumb_url"])

    def test_a_tampered_or_expired_media_link_is_refused(self):
        exp = int(time.time()) + 60
        good = media_signature(TOKEN, self.bid, "photo", exp)
        self.assertTrue(media_ok(TOKEN, self.bid, "photo", str(exp), good))
        self.assertFalse(media_ok(TOKEN, self.bid, "render", str(exp), good))
        self.assertFalse(media_ok(TOKEN, self.bid, "photo", str(int(time.time()) - 1),
                                  media_signature(TOKEN, self.bid, "photo", int(time.time()) - 1)))
        self.assertEqual(self.client.get(f"/api/staff/media/{self.bid}/photo?exp={exp}&sig=00").status_code, 403)

    def test_scheduling_and_notes_are_saved_and_a_bad_status_is_refused(self):
        c = self.client
        r = c.patch(f"/api/staff/bookings/{self.bid}", headers=STAFF,
                    json={"status": "scheduled", "scheduled_at": "2026-10-06T10:00", "assigned_to": "Luis",
                          "staff_notes": "Tocar en el portón azul"})
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()["booking"]
        self.assertEqual((b["status"], b["scheduled_at"], b["assigned_to"]), ("scheduled", "2026-10-06T10:00", "Luis"))
        self.assertEqual(c.patch(f"/api/staff/bookings/{self.bid}", headers=STAFF, json={"status": "paid"}).status_code, 422)
        self.assertEqual(c.patch(f"/api/staff/bookings/{self.bid}", json={"status": "visited"}).status_code, 403)

    def test_visit_measuring_2350mm_instead_of_2300_gives_a_single_final_figure_and_the_difference(self):
        c = self.client
        r = c.post(f"/api/staff/bookings/{self.bid}/visit", headers=STAFF, json={
            "countertop_runs": [{"run_id": "A", "length_mm": 2350, "depth_mm": 645}],
            "splash_runs": [{"run_id": "S1", "length_mm": 2350, "height_mm": 600}], "sinks": 1,
            "tool": "laser", "measured_by": "Luis"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        final = d["final_quote"]
        self.assertFalse(final["estimate_only"])
        self.assertEqual(final["scale_confidence"], "verified")
        self.assertEqual(final["estimate"]["low"], final["estimate"]["high"])
        diff = d["verified"]["differences"]["countertop"][0]
        self.assertEqual((diff["customer_mm"], diff["team_mm"], diff["diff_mm"], diff["diff_bp"]), (2300, 2350, 50, 213))
        self.assertTrue(d["verified"]["within_range"])
        self.assertEqual(d["booking"]["status"], "visited")
        self.assertEqual(d["booking"]["final_total"], final["total"])
        # the customer's own design keeps its estimate; only the visit record carries the final figure
        self.assertTrue(c.get(f"/api/designs/{self.did}").json()["quote"]["estimate_only"])

    def test_a_float_length_at_the_visit_is_refused(self):
        r = self.client.post(f"/api/staff/bookings/{self.bid}/visit", headers=STAFF, json={
            "countertop_runs": [{"run_id": "A", "length_mm": 2350.5}]})
        self.assertEqual(r.status_code, 422)

    def test_a_share_link_shows_the_design_to_anyone_but_nothing_personal_and_not_the_project(self):
        c = self.client
        r = c.post(f"/api/designs/{self.did}/share")
        self.assertEqual(r.status_code, 201, r.text)
        share = r.json()
        self.assertTrue(share["url"].startswith("https://renovai.example.mx/#/s/"))
        self.assertEqual(c.post(f"/api/designs/{self.did}/share").json()["share_id"], share["share_id"])  # one per design
        with TestClient(self.app) as other:
            shared = other.get(f"/api/shared/{share['share_id']}").json()
            self.assertTrue(shared["shared"])
            self.assertEqual(shared["finishes"]["countertop"]["id"], "diseno-white-carrara")
            self.assertNotIn("project_id", shared)
            self.assertNotIn("Ana", str(shared))
            self.assertEqual(other.get(shared["manifest"]["image"]["url"]).status_code, 200)
            self.assertEqual(other.get(shared["manifest"]["before_url"]).status_code, 200)
            self.assertEqual(other.get(f"/api/projects/{self.pid}").status_code, 404)
            self.assertEqual(other.post(f"/api/designs/{self.did}/share").status_code, 404)  # not theirs to share
            self.assertEqual(other.get("/api/shared/not-a-share").status_code, 404)


class WhatsappNumberTests(unittest.TestCase):
    def test_a_10_digit_mexican_number_gets_52_and_an_international_one_keeps_its_code(self):
        self.assertEqual(whatsapp_number("33 1234 5678"), "523312345678")
        self.assertEqual(whatsapp_number("+52 1 33 1234 5678"), "5213312345678")
        self.assertEqual(whatsapp_number("+1 (415) 555-0100"), "14155550100")
        self.assertIsNone(whatsapp_number("12345"))


if __name__ == "__main__":
    unittest.main()
