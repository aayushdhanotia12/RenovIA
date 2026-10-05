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
from renderer.composite import (RenderOptions, Surface, assert_outside_unchanged, fill_specks, split_glare,
                                view_cosine)
from renderer.faces import countertop_faces, profile_shade, vertical_vanishing_point

REPO = Path(__file__).resolve().parents[2]
PHOTO = REPO / "samples" / "kober_photos" / "p7_0_1920x1200.jpg"
GOLDEN = Path(__file__).parent / "golden" / "kober_p7_caracatta_small.png"
CAT = get_catalogue()


def plans_for(img):
    dets = [d for d in MockDetector().detect(img) if d.surface_class != "object"]
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


class SlabFaceTests(unittest.TestCase):
    """composite-v3: the countertop's front edge and ends are drawn as faces, and old glare is split off."""

    @classmethod
    def setUpClass(cls):
        cls.img = cv2.imread(str(PHOTO), cv2.IMREAD_COLOR)
        cls.plans = plans_for(cls.img)
        cls.top = next(p for p in cls.plans if p.surface_class == "countertop")
        cls.wall = next(p for p in cls.plans if p.surface_class == "backsplash")
        cls.gray = cv2.cvtColor(cls.img, cv2.COLOR_BGR2GRAY).astype(np.float32)

    def faces(self, mask, predict):
        return countertop_faces(self.img.shape[:2], [tuple(p) for p in self.top.quad], 3600, 645, mask, 40,
                                "rounded", 0.45, 0.67, (80, 80), vertical_vanishing_point(self.wall.quad),
                                predict_band=predict, photo_lum=self.gray)

    def below_front_line(self, xs, ys):
        (x0, y0), (x1, y1) = self.top.quad[3], self.top.quad[2]
        return ys > y0 + (xs - x0) * (y1 - y0) / (x1 - x0) - 1

    def test_p7_detected_counter_gets_its_40mm_front_edge_inside_the_detected_mask(self):
        fm = self.faces(self.top.mask, predict=False)
        self.assertEqual(fm.kind, "band")
        self.assertGreater(fm.count(), 20000)
        self.assertEqual(int(np.count_nonzero(fm.added)), 0)  # nothing outside the detected product mask

    def test_hand_drawn_p7_outline_gets_a_predicted_edge_only_below_its_front_line(self):
        mask = np.zeros(self.img.shape[:2], np.uint8)
        cv2.fillPoly(mask, [np.int32(self.top.quad)], 255)
        fm = self.faces(mask, predict=True)
        self.assertEqual(fm.kind, "predicted")
        ys, xs = np.nonzero(fm.added)
        front = xs <= self.top.quad[2][0]  # the end face sits right of the front-right corner
        self.assertTrue(self.below_front_line(xs[front].astype(float), ys[front].astype(float)).all())
        # Near the front-right corner the old edge is ~57 px tall; the band must not run into the doors.
        col = fm.mask[:, 1500]
        self.assertLess(int(np.count_nonzero(col)), 90)

    def test_detected_mask_ending_at_the_front_line_draws_the_edge_on_its_own_front_strip(self):
        mask = np.zeros(self.img.shape[:2], np.uint8)
        cv2.fillPoly(mask, [np.int32(self.top.quad)], 255)
        fm = self.faces(mask, predict=False)
        self.assertEqual(fm.kind, "inward")
        self.assertEqual(int(np.count_nonzero(fm.added)), 0)

    def test_hand_drawn_outlines_still_change_no_pixel_outside_the_product_masks(self):
        plans = []
        for p in plans_for(self.img):
            mask = np.zeros(self.img.shape[:2], np.uint8)
            cv2.fillPoly(mask, [np.int32(p.quad)], 255)
            p.mask, p.detected = mask, False
            plans.append(p)
        with tempfile.TemporaryDirectory() as tmp:
            out, layers, masks = render_design(self.img, plans, CAT.finish("estilo-rovere-slavonia"), None, Path(tmp),
                                               profile=CAT.profile("original_q"))
        assert_outside_unchanged(self.img, out, list(masks.values()))
        self.assertEqual(next(layer for layer in layers if layer["surface_class"] == "countertop")["edge_kind"],
                         "predicted")

    def test_glare_at_twice_the_median_light_is_split_off_and_light_below_the_median_passes(self):
        diffuse, glare = split_glare(np.array([0.6, 1.0, 1.2, 2.0], np.float32), cap=0.3)
        self.assertAlmostEqual(float(diffuse[0]), 0.6, places=5)
        self.assertAlmostEqual(float(diffuse[1]), 1.0, places=5)
        self.assertLess(float(diffuse[3]), 1.3)
        self.assertAlmostEqual(float(diffuse[3] + glare[3]), 2.0, places=5)

    def test_rounded_original_edge_catches_more_light_just_below_the_top_than_square_original_q(self):
        x = np.array([0.1], np.float32)
        rounded = float(profile_shade(x, 0.62, "rounded", 0.45)[0])
        square = float(profile_shade(x, 0.62, "square", 0.45)[0])
        self.assertGreater(rounded, square + 0.2)
        self.assertAlmostEqual(float(profile_shade(np.array([0.5]), 0.62, "square", 0.45)[0]), 0.62, places=5)


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
