import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from dataforge.diff import compare
from dataforge.manifest import DEFAULT_TOTAL_BYTES, MAX_TOTAL_BYTES, validate


class ContentBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "manifest.jsonl"

    def write(self, payloads, media_type="text/plain"):
        rows = []
        for i, raw in enumerate(payloads):
            name = f"{i}.bin"
            (self.root / name).write_bytes(raw)
            rows.append(
                {
                    "version": 1,
                    "id": f"synthetic-{i}",
                    "path": name,
                    "split": "train",
                    "media_type": media_type,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "license": "MIT",
                }
            )
        self.manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return rows

    def test_multiple_files_exact_budget_empty_files_and_default_receipt(self):
        self.write([b"abc", b"d", b""])
        checked = validate(self.manifest, self.root, max_total_bytes=4)
        self.assertTrue(checked["ok"])
        self.assertEqual(
            checked["content_validation"], {"bytes_read": 4, "max_total_bytes": 4}
        )
        default = validate(self.manifest, self.root)
        self.assertEqual(
            default["content_validation"]["max_total_bytes"], DEFAULT_TOTAL_BYTES
        )
        self.assertEqual(default["content_validation"]["bytes_read"], 4)

    def test_unbuffered_reads_stop_at_single_detection_byte(self):
        self.write([b"abc", b"defgh"])
        original_open = Path.open
        observed = []
        requests = []

        class Tracked:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def read(self, size):
                requests.append(size)
                raw = self.stream.read(size)
                observed.append(len(raw))
                return raw

        def tracking_open(path, *args, **kwargs):
            self.assertEqual(kwargs.get("buffering"), 0)
            return Tracked(original_open(path, *args, **kwargs))

        with patch("pathlib.Path.open", new=tracking_open):
            with self.assertRaisesRegex(ValueError, "total byte budget"):
                validate(self.manifest, self.root, max_total_bytes=4)
        self.assertEqual(sum(observed), 5)
        self.assertTrue(all(size > 0 for size in requests))
        self.assertEqual(requests, [5, 2, 2])

    def test_hash_mismatches_still_consume_budget(self):
        rows = self.write([b"ab", b"cde"])
        rows[0]["sha256"] = "0" * 64
        self.manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaisesRegex(ValueError, "total byte budget"):
            validate(self.manifest, self.root, max_total_bytes=4)
        report = validate(self.manifest, self.root, max_total_bytes=5)
        self.assertEqual(report["content_validation"]["bytes_read"], 5)
        self.assertEqual(report["findings"], [{"line": 1, "code": "hash_mismatch"}])

    def test_file_cap_remains_independent_of_total_budget(self):
        self.write([b"abcd"])
        with patch("dataforge.manifest.MAX_FILE", 3):
            with self.assertRaisesRegex(ValueError, "file exceeds"):
                validate(self.manifest, self.root, max_total_bytes=10)

    def test_invalid_budget_before_manifest_or_payload_reads(self):
        for value in [True, False, 0, -1, MAX_TOTAL_BYTES + 1, 1.5, "4", None]:
            with self.subTest(value=value):
                with patch(
                    "dataforge.manifest.read_manifest",
                    side_effect=AssertionError("not read"),
                ):
                    with self.assertRaises(ValueError):
                        validate(self.manifest, self.root, max_total_bytes=value)

    def test_optional_image_validation_obeys_same_content_budget(self):
        image = io.BytesIO()
        Image.new("RGB", (2, 2), (12, 34, 56)).save(image, format="PNG")
        raw = image.getvalue()
        self.write([raw], media_type="image/png")
        result = validate(
            self.manifest, self.root, check_images=True, max_total_bytes=len(raw)
        )
        self.assertEqual(result["image_validation"]["checked"], 1)
        self.assertEqual(result["content_validation"]["bytes_read"], len(raw))
        with self.assertRaises(ValueError):
            validate(
                self.manifest,
                self.root,
                check_images=True,
                max_total_bytes=len(raw) - 1,
            )

    def test_diff_per_root_budget_and_metadata_rejection(
        self,
    ):
        self.write([b"ab", b"cd"])
        report = compare(
            self.manifest,
            self.manifest,
            before_root=self.root,
            after_root=self.root,
            max_total_bytes=4,
        )
        for name in ["before", "after"]:
            self.assertEqual(
                report["verification"][name]["content_validation"]["bytes_read"], 4
            )
        with self.assertRaises(ValueError):
            compare(
                self.manifest,
                self.manifest,
                before_root=self.root,
                after_root=self.root,
                max_total_bytes=3,
            )
        with self.assertRaisesRegex(ValueError, "requires both roots"):
            compare(self.manifest, self.manifest, max_total_bytes=4)

    def test_cli_success_and_budget_failure_are_atomic_reports_and_inputs_unchanged(
        self,
    ):
        self.write([b"ab", b"cd"])
        before = {p: p.read_bytes() for p in self.root.iterdir()}
        args = [
            sys.executable,
            "-m",
            "dataforge",
            str(self.manifest),
            "--root",
            str(self.root),
            "--max-total-bytes",
        ]
        good = subprocess.run(args + ["4"], capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)["content_validation"]["bytes_read"], 4)
        for value in ["3", "0", str(MAX_TOTAL_BYTES + 1)]:
            bad = subprocess.run(args + [value], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(bad.stdout, "")
        diff = subprocess.run(
            [
                sys.executable,
                "-m",
                "dataforge.diff",
                str(self.manifest),
                str(self.manifest),
                "--before-root",
                str(self.root),
                "--after-root",
                str(self.root),
                "--max-total-bytes",
                "4",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(diff.returncode, 0, diff.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
