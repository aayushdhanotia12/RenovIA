"""Camera data from the photo's EXIF, with the traps (digital zoom, nonsense values, crops) checked."""

import io
import unittest

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from backend.app.camera import camera_from_exif


def jpeg(make: str | None = None, f35=None, zoom=None, pixels=None, size=(400, 300), orientation=None) -> bytes:
    exif = Image.Exif()
    if make:
        exif[0x010F] = make
    if orientation:
        exif[0x0112] = orientation
    ifd = exif.get_ifd(0x8769)
    if f35 is not None:
        ifd[0xA405] = f35
    if zoom is not None:
        ifd[0xA404] = IFDRational(int(zoom * 100), 100)
    if pixels:
        ifd[0xA002], ifd[0xA003] = pixels
    buf = io.BytesIO()
    Image.new("RGB", size, (128, 128, 128)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


class CameraTests(unittest.TestCase):
    def test_iphone_main_camera_26mm_resized_to_1920x1440_is_1442_px(self):
        cam = camera_from_exif(jpeg("Apple", 26, pixels=(4032, 3024)), 1920, 1440)
        self.assertEqual((cam["source"], cam["focal_px"], cam["lens"]), ("exif", 1442, "main"))

    def test_iphone_ultra_wide_13mm_is_kept_and_named(self):
        cam = camera_from_exif(jpeg("Apple", 13, pixels=(4032, 3024)), 1920, 1440)
        self.assertEqual((cam["source"], cam["lens"], cam["focal_px"]), ("exif", "ultra-wide", 721))

    def test_samsung_24mm_at_2x_digital_zoom_is_48mm_but_apple_zoom_is_already_included(self):
        self.assertEqual(camera_from_exif(jpeg("samsung", 24, zoom=2.0), 400, 300)["focal_35mm"], 48.0)
        self.assertEqual(camera_from_exif(jpeg("Apple", 52, zoom=2.0), 400, 300)["focal_35mm"], 52.0)

    def test_a_177mm_reading_from_a_capture_app_falls_back_to_the_26mm_default(self):
        cam = camera_from_exif(jpeg("Apple", 177), 400, 300)
        self.assertEqual((cam["source"], cam["focal_35mm"]), ("default", 26.0))
        self.assertIn("implausible", cam["reason"])

    def test_a_square_crop_of_a_4032x3024_photo_falls_back_to_the_default(self):
        cam = camera_from_exif(jpeg("Apple", 26, pixels=(4032, 3024), size=(300, 300)), 300, 300)
        self.assertEqual((cam["source"], cam["reason"]), ("default", "photo was cropped"))

    def test_a_portrait_photo_rotated_by_exif_is_not_mistaken_for_a_crop(self):
        cam = camera_from_exif(jpeg("Apple", 26, pixels=(4032, 3024), size=(400, 300), orientation=6), 300, 400)
        self.assertEqual(cam["source"], "exif")

    def test_a_photo_without_camera_data_uses_the_default(self):
        buf = io.BytesIO()
        Image.new("RGB", (40, 30)).save(buf, "PNG")
        self.assertEqual(camera_from_exif(buf.getvalue(), 40, 30)["source"], "default")


if __name__ == "__main__":
    unittest.main()
