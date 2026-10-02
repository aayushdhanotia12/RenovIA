"""Render invariants and model-output validation."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from backend.app.ai.base import ModelError
from backend.app.ai.mock import MockDetector
from backend.app.ai.suggester import suggestion_schema, validate_suggestions
from backend.app.catalogue import get_catalogue
from backend.app.geometry import fit_quad, order_quad
from backend.app.render import SurfacePlan, render_design
from renderer.composite import RenderOptions, Surface, assert_outside_unchanged, fill_specks, view_cosine

REPO = Path(__file__).resolve().parents[2]
PHOTO = REPO / "samples" / "kober_photos" / "p7_0_1920x1200.jpg"
GOLDEN = Path(__file__).parent / "golden" / "kober_p7_caracatta_small.png"
CAT = get_catalogue()


def plans_for(img):
    dets = MockDetector().detect(img)
    return [SurfacePlan(f"{d.surface_class}_1", d.surface_class, "A" if d.surface_class == "countertop" else "S1",
                        d.quad, d.mask, 3600 if d.surface_class == "countertop" else 3000,
                        645 if d.surface_class == "countertop" else 600, d.score) for d in dets]


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.img = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
        top = CAT.finish("estilo-caracatta")
        cls.out, cls.layers, cls.masks = render_design(cls.img, plans_for(cls.img), top, top, Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_pixel_outside_a_product_mask_changes(self):
        assert_outside_unchanged(self.img, self.out, list(self.masks.values()))

    def test_every_rendered_surface_has_a_clickable_layer_with_a_finish_id(self):
        self.assertEqual({layer["finish_id"] for layer in self.layers}, {"estilo-caracatta"})
        self.assertEqual(len(self.layers), 2)

    def test_render_matches_the_golden_image_within_tolerance(self):
        small = cv2.resize(self.out, (480, 300), interpolation=cv2.INTER_AREA)
        if not GOLDEN.exists():  # first run records the golden; review it by eye, then commit it
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(GOLDEN), small)
            self.skipTest("golden image recorded")
        golden = cv2.imread(str(GOLDEN), cv2.IMREAD_COLOR)
        diff = float(np.abs(small.astype(np.int16) - golden.astype(np.int16)).mean())
        self.assertLess(diff, 1.5, f"render drifted from golden by {diff:.2f} grey levels on average")

    def test_a_pixel_changed_outside_the_masks_fails_the_assertion(self):
        tampered = self.out.copy()
        tampered[5, 5] = tampered[5, 5] ^ 0xFF
        with self.assertRaises(AssertionError):
            assert_outside_unchanged(self.img, tampered, list(self.masks.values()))


class RendererV2Tests(unittest.TestCase):
    def test_a_logo_sized_hole_inside_the_counter_is_repainted_but_a_bottle_sized_one_is_kept(self):
        mask = np.full((1200, 1920), 255, np.uint8)
        mask[800:810, 1800:1840] = 0      # printed logo, 400 px
        mask[600:720, 460:550] = 0        # bottle, 10,800 px
        out = fill_specks(mask)
        self.assertTrue((out[800:810, 1800:1840] == 255).all())
        self.assertTrue((out[600:720, 460:550] == 0).all())

    def test_the_p7_counter_is_seen_at_a_glancing_angle(self):
        img = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
        top = next(p for p in plans_for(img) if p.surface_class == "countertop")
        s = Surface("c", "countertop", [tuple(p) for p in top.quad], 3600, 645, [])
        cos = view_cosine(s, img.shape[:2])[top.mask > 0]
        self.assertTrue(0.1 < float(np.median(cos)) < 0.5)  # roughly 60-85 degrees from the normal

    def test_the_first_renderer_still_keeps_every_pixel_outside_the_masks(self):
        img = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
        top = CAT.finish("estilo-porfido-nero")
        with tempfile.TemporaryDirectory() as tmp:
            out, _, masks = render_design(img, plans_for(img), top, top, Path(tmp), RenderOptions.v1())
        assert_outside_unchanged(img, out, list(masks.values()))


class GeometryTests(unittest.TestCase):
    def test_trapezoid_mask_fits_back_left_back_right_front_right_front_left(self):
        mask = np.zeros((400, 600), np.uint8)
        cv2.fillPoly(mask, [np.int32([[150, 100], [450, 100], [560, 300], [40, 300]])], 255)
        quad = fit_quad(mask)
        for got, want in zip(quad, [[150, 100], [450, 100], [560, 300], [40, 300]]):
            self.assertLessEqual(abs(got[0] - want[0]) + abs(got[1] - want[1]), 6)

    def test_order_quad_sorts_any_point_order(self):
        self.assertEqual(order_quad(np.array([[560, 300], [150, 100], [40, 300], [450, 100]])),
                         [[150, 100], [450, 100], [560, 300], [40, 300]])


class SuggestionValidationTests(unittest.TestCase):
    def good(self, **over):
        d = {"title": "Mármol", "countertop_finish_id": "estilo-caracatta", "profile_id": "original_q",
             "backsplash_finish_id": "none", "reason": "Luminoso."}
        d.update(over)
        return d

    def test_a_suggestion_carrying_a_price_is_dropped(self):
        out = validate_suggestions({"designs": [self.good(price=12000), self.good()]}, CAT)
        self.assertEqual(len(out), 1)

    def test_a_capitalised_catalogue_id_from_the_model_still_matches(self):
        out = validate_suggestions({"designs": [self.good(countertop_finish_id="Diseno-White-Carrara",
                                                          profile_id="Original_Q")]}, CAT)
        self.assertEqual((out[0]["countertop_finish_id"], out[0]["profile_id"]), ("diseno-white-carrara", "original_q"))

    def test_an_invented_finish_id_is_dropped(self):
        out = validate_suggestions({"designs": [self.good(countertop_finish_id="estilo-golden-onyx"), self.good()]}, CAT)
        self.assertEqual(len(out), 1)

    def test_a_basik_finish_in_essence_profile_is_dropped(self):
        with self.assertRaises(ModelError):
            validate_suggestions({"designs": [self.good(countertop_finish_id="basik-graphite-nebula",
                                                        profile_id="essence")]}, CAT)

    def test_the_tool_schema_has_no_price_total_or_currency_field(self):
        props = suggestion_schema(CAT)["properties"]["designs"]["items"]["properties"]
        self.assertFalse({"price", "total", "currency", "amount"} & set(props))
        self.assertIn("estilo-caracatta", props["countertop_finish_id"]["enum"])


if __name__ == "__main__":
    unittest.main()
