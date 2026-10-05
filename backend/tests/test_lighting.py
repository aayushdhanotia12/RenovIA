"""The room's light from a lighting model (Marigold-IID-Lighting via our worker, or stored offline)."""

import io
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from backend.app.ai.base import ModelError
from backend.app.ai.mock import MockDetector, MockLighting
from backend.app.ai.worker import WorkerLighting
from backend.app.catalogue import get_catalogue
from backend.app.render import SurfacePlan, render_design
from renderer.composite import assert_outside_unchanged, light_from_model

REPO = Path(__file__).resolve().parents[2]
PHOTO = REPO / "samples" / "kober_photos" / "p7_0_1920x1200.jpg"
GOLDEN = Path(__file__).parent / "golden" / "kober_p7_caracatta_marigold_small.png"
CAT = get_catalogue()


def npy(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return buf.getvalue()


class WorkerLightingTests(unittest.TestCase):
    def test_the_worker_gets_the_photo_with_the_token_and_its_array_comes_back_as_float(self):
        seen = {}

        def handler(request):
            seen["auth"], seen["type"] = request.headers["authorization"], request.headers["content-type"]
            return httpx.Response(200, content=npy(np.full((40, 60, 3), 0.5, np.float16)))

        light = WorkerLighting("http://worker", "s3cret", transport=httpx.MockTransport(handler)).estimate(
            np.zeros((300, 400, 3), np.uint8))
        self.assertEqual((seen["auth"], seen["type"]), ("Bearer s3cret", "image/jpeg"))
        self.assertEqual((light.shape, light.dtype), ((40, 60, 3), np.float32))

    def test_a_refused_or_garbled_answer_is_a_model_error_so_the_render_falls_back(self):
        for response in (httpx.Response(401, text="unauthorised"), httpx.Response(200, content=b"not an array"),
                         httpx.Response(200, content=npy(np.zeros((40, 60), np.float16)))):
            worker = WorkerLighting("http://worker", "x", transport=httpx.MockTransport(lambda r, resp=response: resp))
            with self.assertRaises(ModelError):
                worker.estimate(np.zeros((30, 40, 3), np.uint8))


class StoredLightingTests(unittest.TestCase):
    def test_the_sample_photo_has_its_stored_marigold_light_and_other_photos_have_none(self):
        img = cv2.imread(str(PHOTO))
        light = MockLighting().estimate(img)
        self.assertEqual(light.shape[2], 3)
        self.assertIsNone(MockLighting().estimate(np.full((300, 400, 3), 90, np.uint8)))


class ModelLightRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = cv2.imread(str(PHOTO))
        cls.plans = [SurfacePlan(f"{d.surface_class}_1", d.surface_class, "A" if d.surface_class == "countertop" else "S1",
                                 d.quad, d.mask, 3600 if d.surface_class == "countertop" else 3000,
                                 645 if d.surface_class == "countertop" else 600, d.score)
                     for d in MockDetector().detect(cls.img) if d.surface_class != "object"]
        cls.light = light_from_model(MockLighting().estimate(cls.img), cls.img)
        cls.tmp = tempfile.TemporaryDirectory()
        top = CAT.finish("estilo-caracatta")
        cls.out, _, cls.masks = render_design(cls.img, cls.plans, top, top, Path(cls.tmp.name), light=cls.light)
        cls.builtin, _, _ = render_design(cls.img, cls.plans, top, top, Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_light_is_upsampled_to_the_photo_and_stays_positive(self):
        self.assertEqual(self.light.shape, self.img.shape)
        self.assertGreater(float(self.light.min()), 0.0)

    def test_rendering_with_model_light_still_changes_no_pixel_outside_the_product_masks(self):
        assert_outside_unchanged(self.img, self.out, list(self.masks.values()))

    def test_model_light_changes_the_render_inside_the_surfaces(self):
        inside = np.zeros(self.img.shape[:2], bool)
        for m in self.masks.values():
            inside |= m > 0
        diff = np.abs(self.out.astype(np.int16) - self.builtin.astype(np.int16)).mean(axis=-1)
        self.assertGreater(float(diff[inside].mean()), 2.0)

    def test_render_with_model_light_matches_its_golden_image(self):
        small = cv2.resize(self.out, (480, 300), interpolation=cv2.INTER_AREA)
        if not GOLDEN.exists():  # first run records the golden; review it by eye, then commit it
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(GOLDEN), small)
            self.skipTest("golden image recorded")
        golden = cv2.imread(str(GOLDEN), cv2.IMREAD_COLOR)
        diff = float(np.abs(small.astype(np.int16) - golden.astype(np.int16)).mean())
        self.assertLess(diff, 1.5, f"render drifted from golden by {diff:.2f} grey levels on average")


if __name__ == "__main__":
    unittest.main()
