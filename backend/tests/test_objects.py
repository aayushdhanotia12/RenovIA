"""Objects on and in front of the surfaces: asked of SAM 3 by name, cut out of the product masks."""

import base64
import json
import unittest

import cv2
import numpy as np

try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

from backend.app.ai.fal_sam3 import ALWAYS_OBJECTS, FalSam3Detector
from backend.app.ai.suggester import DESCRIBE_SCHEMA, clean_objects
from backend.app.ai.mock import MockDetector
from backend.app.geometry import object_record, subtract_objects

H, W = 300, 400


def png_uri(mask: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", mask)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def rect(x0, y0, x1, y1) -> np.ndarray:
    m = np.zeros((H, W), np.uint8)
    m[y0:y1, x0:x1] = 255
    return m


class FakeSam3:
    """Answers like fal's SAM 3 endpoint: a counter, a sink on it, nothing else, and one failing prompt."""

    def __init__(self):
        self.prompts = []

    def __call__(self, request):
        prompt = json.loads(request.content)["prompt"]
        self.prompts.append(prompt)
        if prompt == "toaster":
            return httpx.Response(500, text="upstream error")
        masks = {"kitchen countertop": [rect(0, 150, 400, 260)], "sink": [rect(60, 170, 140, 220)]}.get(prompt, [])
        return httpx.Response(200, json={"masks": [{"url": png_uri(m)} for m in masks],
                                         "scores": [0.9] * len(masks)})


class Sam3ObjectTests(unittest.TestCase):
    def test_sam3_is_asked_for_both_surfaces_every_object_claude_saw_and_the_sink_cooktop_and_faucet(self):
        fake = FakeSam3()
        det = FalSam3Detector("key", transport=httpx.MockTransport(fake), workers=4)
        found = det.detect(np.zeros((H, W, 3), np.uint8), objects=["Soap dispenser", "toaster", "sink"])
        self.assertEqual(set(fake.prompts), {"kitchen countertop", "kitchen backsplash", *ALWAYS_OBJECTS,
                                             "soap dispenser", "toaster"})
        self.assertEqual(len(fake.prompts), len(set(fake.prompts)))  # "sink" asked once
        # The toaster prompt failed upstream: skipped, the rest still arrive.
        self.assertEqual([(d.surface_class, d.label) for d in found], [("countertop", None), ("object", "sink")])

    def test_a_failed_surface_prompt_still_fails_the_detection(self):
        def handler(request):
            return httpx.Response(503, text="busy")
        det = FalSam3Detector("key", transport=httpx.MockTransport(handler))
        with self.assertRaises(Exception):
            det.detect(np.zeros((H, W, 3), np.uint8))


class ObjectListTests(unittest.TestCase):
    def test_claudes_list_becomes_short_unique_prompts_without_the_surfaces_themselves(self):
        raw = ["Faucet", "faucet", "paper_towel holder", "granite countertop", "upper cabinet", "  Soap  dispenser ",
               "a very long description of a blue ceramic jar", 7]
        self.assertEqual(clean_objects(raw), ["faucet", "paper towel holder", "soap dispenser"])

    def test_the_describe_schema_asks_for_objects(self):
        self.assertIn("objects", DESCRIBE_SCHEMA["required"])


class SubtractObjectsTests(unittest.TestCase):
    def test_a_sink_in_a_400x110_counter_is_cut_out_of_the_product_mask(self):
        counter, sink = rect(0, 150, 400, 260), rect(60, 170, 140, 220)
        product = subtract_objects(counter, [sink])
        self.assertTrue((product[170:220, 60:140] == 0).all())
        self.assertEqual(int(np.count_nonzero(product)), 400 * 110 - 80 * 50)

    def test_an_object_covering_most_of_the_counter_is_a_mix_up_and_is_ignored(self):
        counter = rect(0, 150, 400, 260)
        whole = rect(0, 140, 400, 270)  # "cooktop" answered with the whole counter
        self.assertEqual(int(np.count_nonzero(subtract_objects(counter, [whole]))), 400 * 110)

    def test_an_object_record_has_its_box_and_centre_for_a_pointer(self):
        rec = object_record("sink", rect(60, 170, 140, 220), 0.91)
        self.assertEqual(rec["bbox"], [60, 170, 140, 220])
        self.assertEqual(rec["centroid"], [99, 194])
        self.assertEqual(rec["area_px"], 80 * 50)

    def test_offline_p7_photo_comes_with_its_sink_cooktop_and_tap(self):
        from pathlib import Path
        img = cv2.imread(str(Path(__file__).resolve().parents[2] / "samples/kober_photos/p7_0_1920x1200.jpg"))
        labels = {d.label for d in MockDetector().detect(img) if d.surface_class == "object"}
        self.assertTrue({"sink", "cooktop", "faucet"} <= labels)


if __name__ == "__main__":
    unittest.main()
