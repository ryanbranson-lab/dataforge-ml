import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataforge.manifest import validate


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "sample.txt").write_bytes(b"synthetic sample\n")
        self.digest = hashlib.sha256(
            (self.root / "sample.txt").read_bytes()
        ).hexdigest()
        self.manifest = self.root / "manifest.jsonl"
        self.row = {
            "version": 1,
            "id": "one",
            "path": "sample.txt",
            "split": "train",
            "media_type": "text/plain",
            "sha256": self.digest,
            "license": "CC0-1.0",
        }
        self.write([self.row])

    def write(self, rows):
        self.manifest.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def test_valid_and_provenance(self):
        result = validate(self.manifest, self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"], 1)
        self.assertEqual(
            result["manifest_sha256"],
            hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
        )
        self.assertEqual((self.root / "sample.txt").read_bytes(), b"synthetic sample\n")

    def test_byte_drift(self):
        (self.root / "sample.txt").write_bytes(b"changed")
        self.assertEqual(
            validate(self.manifest, self.root)["findings"],
            [{"line": 1, "code": "hash_mismatch"}],
        )

    def test_duplicates_and_cross_split(self):
        self.write(
            [
                self.row,
                dict(self.row, id="two"),
                dict(self.row, id="three", split="eval"),
            ]
        )
        findings = validate(self.manifest, self.root)["findings"]
        self.assertEqual(
            [finding["code"] for finding in findings],
            ["duplicate_within_split", "cross_split_overlap"],
        )
        self.assertTrue(all(finding["first_line"] == 1 for finding in findings))

    def test_path_escape_and_noncanonical(self):
        for path in [
            "../sample.txt",
            "/etc/passwd",
            "./sample.txt",
            "a//b",
            "a/../sample.txt",
            "a\\b",
            "sample.txt\x00",
        ]:
            self.write([dict(self.row, path=path)])
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate(self.manifest, self.root)

    def test_symlink_rejected(self):
        (self.root / "alias.txt").symlink_to(self.root / "sample.txt")
        self.write([dict(self.row, path="alias.txt")])
        with self.assertRaises(ValueError):
            validate(self.manifest, self.root)

    def test_missing_file_and_directory(self):
        self.write([dict(self.row, path="missing")])
        with self.assertRaises(OSError):
            validate(self.manifest, self.root)
        (self.root / "folder").mkdir()
        self.write([dict(self.row, path="folder")])
        with self.assertRaises(ValueError):
            validate(self.manifest, self.root)

    def test_schema_and_ids(self):
        for row in [
            dict(self.row, version=True),
            dict(self.row, extra=1),
            dict(self.row, license=""),
            dict(self.row, sha256="BAD"),
            dict(self.row, media_type="video/mp4"),
            dict(self.row, id="\ud800"),
        ]:
            self.write([row])
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate(self.manifest, self.root)
        self.write([self.row, self.row])
        with self.assertRaises(ValueError):
            validate(self.manifest, self.root)

    def test_invalid_json(self):
        for raw in [b"", b"\n", b"\xff", b'{"id":1,"id":2}', b'{"x":NaN}']:
            self.manifest.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate(self.manifest, self.root)

    def test_size_limits(self):
        with patch("dataforge.manifest.MAX_MANIFEST", 3), self.assertRaises(ValueError):
            validate(self.manifest, self.root)
        with patch("dataforge.manifest.MAX_FILE", 3), self.assertRaises(ValueError):
            validate(self.manifest, self.root)
        with patch("dataforge.manifest.MAX_RECORDS", 0), self.assertRaises(ValueError):
            validate(self.manifest, self.root)

    def test_cli_success_findings_failure(self):
        command = [
            sys.executable,
            "-m",
            "dataforge",
            str(self.manifest),
            "--root",
            str(self.root),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        (self.root / "sample.txt").write_bytes(b"drift")
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.manifest.write_text("{}")
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("validation failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
