import builtins
import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageFile

from dataforge.manifest import validate


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.jsonl"

    def image(self, format="PNG", size=(8, 8)):
        output = io.BytesIO()
        Image.new("RGB", size, (12, 34, 56)).save(output, format=format)
        return output.getvalue()

    def write(self, raw, media_type="image/png", path="sample.bin"):
        (self.root / "sample.bin").write_bytes(raw)
        row = {
            "version": 1,
            "id": "synthetic-image",
            "path": path,
            "split": "train",
            "media_type": media_type,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "license": "MIT",
        }
        self.manifest.write_text(json.dumps(row) + "\n")

    def check(self, **kwargs):
        return validate(self.manifest, self.root, check_images=True, **kwargs)

    def test_valid_png_and_jpeg_decode(self):
        for format, media in [("PNG", "image/png"), ("JPEG", "image/jpeg")]:
            raw = self.image(format)
            self.write(raw, media)
            result = self.check()
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["image_validation"]["checked"], 1)
            self.assertEqual((self.root / "sample.bin").read_bytes(), raw)

    def test_default_still_checks_bytes_without_interpreting_media(self):
        self.write(b"not an image")
        with patch(
            "dataforge.images.require_decoder",
            side_effect=AssertionError("unexpected decoder"),
        ):
            result = validate(self.manifest, self.root)
        self.assertTrue(result["ok"])
        self.assertNotIn("image_validation", result)

    def test_corrupt_truncated_and_declared_type_mismatch(self):
        for raw, media, code in [
            (b"not an image", "image/png", "image_invalid"),
            (self.image()[:-15], "image/png", "image_invalid"),
            (self.image("JPEG")[:-20], "image/jpeg", "image_invalid"),
            (self.image("JPEG"), "image/png", "image_type_mismatch"),
            (self.image(), "image/jpeg", "image_type_mismatch"),
        ]:
            self.write(raw, media)
            result = self.check()
            with self.subTest(code=code):
                self.assertFalse(result["ok"])
                self.assertEqual(result["findings"], [{"line": 1, "code": code}])

    def test_pixel_bound_precedes_decoding_even_for_large_header(self):
        raw = bytearray(self.image())
        raw[16:24] = struct.pack(">II", 4000, 4000)
        raw[29:33] = struct.pack(">I", zlib.crc32(raw[12:29]))
        self.write(bytes(raw))
        with patch.object(
            Image.Image, "load", side_effect=AssertionError("must not allocate")
        ):
            result = self.check(max_pixels=100)
        self.assertEqual(result["findings"][0]["code"], "image_pixel_limit")

    def test_decoder_bomb_warning_and_error_are_rejected(self):
        self.write(self.image())
        for limit in [50, 10]:
            with (
                self.subTest(limit=limit),
                patch.object(Image, "MAX_IMAGE_PIXELS", limit),
            ):
                self.assertEqual(
                    self.check()["findings"][0]["code"], "image_pixel_limit"
                )

    def test_multiframe_png_rejected(self):
        output = io.BytesIO()
        first = Image.new("RGB", (3, 3), "red")
        second = Image.new("RGB", (3, 3), "blue")
        first.save(output, format="PNG", save_all=True, append_images=[second])
        self.write(output.getvalue())
        self.assertEqual(self.check()["findings"][0]["code"], "image_multiframe")

    def test_hash_failure_not_mislabeled_as_image_success(self):
        self.write(self.image())
        (self.root / "sample.bin").write_bytes(self.image("JPEG"))
        result = self.check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["findings"][0]["code"], "hash_mismatch")
        self.assertEqual(result["image_validation"]["checked"], 0)

    def test_text_not_decoded_and_unsafe_paths_still_fail(self):
        self.write(b"plain synthetic text", "text/plain")
        result = self.check()
        self.assertTrue(result["ok"])
        self.assertEqual(result["image_validation"]["checked"], 0)
        self.write(self.image(), path="../escape")
        with self.assertRaises(ValueError):
            self.check()
        self.write(self.image(), path="alias")
        (self.root / "alias").symlink_to(self.root / "sample.bin")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.check()

    def test_options_and_missing_optional_dependency_fail_explicitly(self):
        self.write(self.image())
        for limit in [True, 0, 100000001]:
            with self.assertRaises(ValueError):
                self.check(max_pixels=limit)
        with self.assertRaises(ValueError):
            validate(self.manifest, self.root, max_pixels=10)
        original_import = builtins.__import__

        def without_pillow(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("optional decoder absent")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_pillow):
            with self.assertRaisesRegex(ValueError, "requirements-images"):
                self.check()
        with patch.object(ImageFile, "LOAD_TRUNCATED_IMAGES", True):
            with self.assertRaisesRegex(ValueError, "LOAD_TRUNCATED_IMAGES"):
                self.check()

    def test_default_cli_works_without_site_packages_and_optional_mode_fails(self):
        self.write(b"not an image")
        command = [
            sys.executable,
            "-S",
            "-m",
            "dataforge",
            str(self.manifest),
            "--root",
            str(self.root),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("image_validation", json.loads(result.stdout))
        result = subprocess.run(
            command + ["--check-images"], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("requirements-images", result.stderr)

    def test_cli_findings_exit_one_and_configuration_error_no_report(self):
        self.write(b"corrupt synthetic image")
        command = [
            sys.executable,
            "-m",
            "dataforge",
            str(self.manifest),
            "--root",
            str(self.root),
            "--check-images",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["findings"][0]["code"], "image_invalid"
        )
        result = subprocess.run(
            command + ["--max-pixels", "0"], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
