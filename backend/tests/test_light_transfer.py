"""Light from a generated photo, pattern from the product (renderer/light_transfer.py)."""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from renderer.composite import linear_to_srgb, srgb_to_linear
from renderer.light_transfer import align_generated, albedo_drift, finish_with_generated

H, W = 360, 540


def kitchen() -> tuple[np.ndarray, np.ndarray]:
    """A textured 'room' and a countertop mask across its lower half."""
    rng = np.random.default_rng(1)
    room = cv2.GaussianBlur(rng.uniform(40, 220, (H, W, 3)).astype(np.float32), (0, 0), 3)
    cv2.rectangle(room, (60, 40), (200, 150), (30, 60, 140), -1)
    cv2.circle(room, (420, 90), 45, (200, 210, 230), -1)
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [np.array([[40, 230], [500, 210], [530, 330], [10, 340]])], 255)
    return np.clip(room, 0, 255).astype(np.uint8), mask


def veined(seed: int) -> np.ndarray:
    """A white stone with dark veins, linear RGB."""
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), 0.75, np.float32)
    for _ in range(14):
        pts = np.cumsum(rng.normal(0, 18, (12, 2)), axis=0) + rng.uniform([0, 200], [W, 350])
        cv2.polylines(base, [pts.astype(np.int32)], False, (0.08, 0.08, 0.09), 2, cv2.LINE_AA)
    return base


def shift(img: np.ndarray, dx: float, dy: float, scale: float = 1.0) -> np.ndarray:
    M = np.array([[scale, 0, dx], [0, scale, dy]], np.float32)
    return cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)


class LightTransferTests(unittest.TestCase):
    def setUp(self):
        self.photo, self.mask = kitchen()
        self.product = veined(7)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.shading = (0.55 + 0.6 * np.exp(-((xx - 300) ** 2 + (yy - 250) ** 2) / 4000.0))[..., None].repeat(3, 2)
        self.residual = np.zeros((H, W, 3), np.float32)
        cv2.ellipse(self.residual, (200, 260), (30, 6), 0, 0, 360, (0.25, 0.25, 0.25), -1)  # a reflected light

    def generated(self, albedo: np.ndarray, dx=3.0, dy=-2.0, scale=1.01) -> np.ndarray:
        lin = srgb_to_linear(self.photo[..., ::-1])
        inside = (self.mask > 0)[..., None]
        lin = np.where(inside, albedo * self.shading + self.residual, lin)
        return shift(linear_to_srgb(lin)[..., ::-1].astype(np.uint8), dx, dy, scale)

    def test_a_generated_photo_shifted_by_3px_and_scaled_1pct_is_aligned_back(self):
        al = align_generated(self.generated(self.product), self.photo, self.mask == 0)
        self.assertGreater(al.score, 0.97)
        back = cv2.absdiff(al.warped, self.photo)[self.mask == 0].mean()
        self.assertLess(back, 4.0)

    def test_the_product_pattern_survives_while_the_light_comes_from_the_generated_photo(self):
        imagined = veined(99)  # the model drew its own veins
        gen = self.generated(imagined, 0, 0, 1.0)
        intrinsics = lambda _bgr: (imagined, self.shading, self.residual)  # noqa: E731
        alpha = (self.mask > 0).astype(np.float32)
        out, drift = finish_with_generated(self.photo, self.product, alpha, self.mask, gen, intrinsics)
        want = linear_to_srgb(self.product * self.shading + self.residual)[..., ::-1]
        inside = self.mask > 0
        self.assertLess(np.abs(out[inside].astype(int) - want[inside].astype(int)).mean(), 1.0)
        self.assertTrue((out[~inside] == self.photo[~inside]).all())  # the customer's photo, byte for byte
        self.assertFalse(drift.ok())  # and the drift is reported, so the app can fall back

    def test_drift_is_low_when_the_model_kept_the_stone_and_high_when_it_recoloured_it(self):
        kept = albedo_drift(self.product * 1.02, self.product, self.mask)
        self.assertTrue(kept.ok(), kept)
        warmer = self.product * np.array([1.0, 0.9, 0.7], np.float32)
        self.assertGreater(albedo_drift(warmer, self.product, self.mask).colour_de, 6.0)


if __name__ == "__main__":
    unittest.main()
