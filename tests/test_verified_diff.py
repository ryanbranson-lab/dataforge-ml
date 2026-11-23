import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataforge.diff import compare


class VerifiedDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.before = self.directory / "before.jsonl"
        self.after = self.directory / "after.jsonl"
        self.old_root = self.directory / "old"
        self.new_root = self.directory / "new"
        for root in (self.old_root, self.new_root):
            root.mkdir()
            (root / "sample.txt").write_bytes(b"original synthetic bytes\n")
        self.row = {
            "version": 1,
            "id": "one",
            "path": "sample.txt",
            "split": "train",
            "media_type": "text/plain",
            "license": "MIT",
            "sha256": hashlib.sha256(b"original synthetic bytes\n").hexdigest(),
        }
        self.write(self.before, [self.row])
        self.write(self.after, [self.row])

    def write(self, path, rows):
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def verified(self):
        return compare(
            self.before, self.after, before_root=self.old_root, after_root=self.new_root
        )

    def command(self):
        return [
            sys.executable,
            "-m",
            "dataforge.diff",
            str(self.before),
            str(self.after),
            "--before-root",
            str(self.old_root),
            "--after-root",
            str(self.new_root),
        ]

    def test_identical_snapshots_are_verified_without_declared_drift(self):
        report = self.verified()
        self.assertTrue(report["content_files_verified"])
        self.assertFalse(report["has_drift"])
        self.assertTrue(report["verification"]["quality_ok"])
        self.assertEqual(
            report["verification"]["before"]["manifest_sha256"], report["before_sha256"]
        )
        self.assertEqual(
            report["verification"]["after"]["manifest_sha256"], report["after_sha256"]
        )
        self.assertEqual(
            (self.new_root / "sample.txt").read_bytes(), b"original synthetic bytes\n"
        )

    def test_changed_bytes_with_unchanged_metadata_fail_on_either_side(self):
        for root, label in [(self.old_root, "before"), (self.new_root, "after")]:
            sample = root / "sample.txt"
            original = sample.read_bytes()
            sample.write_bytes(b"unrecorded byte drift")
            with (
                self.subTest(side=label),
                self.assertRaisesRegex(ValueError, label + " content differs"),
            ):
                self.verified()
            sample.write_bytes(original)

    def test_valid_declared_content_and_split_changes_are_reported(self):
        (self.new_root / "sample.txt").write_bytes(b"new frozen version")
        row = dict(
            self.row,
            split="eval",
            sha256=hashlib.sha256(b"new frozen version").hexdigest(),
        )
        self.write(self.after, [row])
        report = self.verified()
        self.assertTrue(report["content_files_verified"])
        self.assertTrue(report["has_drift"])
        self.assertEqual(report["changed"][0]["fields"], ["sha256", "split"])

    def test_partial_roots_are_invalid_and_metadata_mode_remains_offline(self):
        for kwargs in [{"before_root": self.old_root}, {"after_root": self.new_root}]:
            with self.assertRaisesRegex(ValueError, "supplied together"):
                compare(self.before, self.after, **kwargs)
        with patch(
            "dataforge.diff._validate_content",
            side_effect=AssertionError("must not access files"),
        ):
            result = compare(self.before, self.after)
        self.assertFalse(result["content_files_verified"])
        self.assertNotIn("verification", result)

    def test_missing_file_symlink_and_traversal_are_rejected(self):
        (self.new_root / "sample.txt").unlink()
        with self.assertRaises(OSError):
            self.verified()
        (self.new_root / "sample.txt").symlink_to(self.old_root / "sample.txt")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.verified()
        self.write(self.after, [dict(self.row, path="../old/sample.txt")])
        with self.assertRaisesRegex(ValueError, "canonical relative"):
            self.verified()

    def test_quality_findings_are_not_hidden_by_valid_bytes(self):
        rows = [self.row, dict(self.row, id="two")]
        self.write(self.before, rows)
        self.write(self.after, rows)
        report = self.verified()
        self.assertTrue(report["content_files_verified"])
        self.assertFalse(report["has_drift"])
        self.assertFalse(report["verification"]["quality_ok"])
        self.assertEqual(
            report["verification"]["after"]["findings"][0]["code"],
            "duplicate_within_split",
        )
        result = subprocess.run(self.command(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["verification"]["quality_ok"])

    def test_metadata_and_hash_binding_uses_parsed_snapshots(self):
        from dataforge.manifest import _validate_content

        original_after_hash = hashlib.sha256(self.after.read_bytes()).hexdigest()

        def verify_snapshot(rows, digest, root):
            # Change the path's metadata after both inputs were parsed. The
            # evaluation must still bind to its original byte snapshot.
            self.write(self.after, [dict(self.row, sha256="0" * 64)])
            return _validate_content(rows, digest, root)

        with patch("dataforge.diff._validate_content", side_effect=verify_snapshot):
            report = self.verified()
        self.assertEqual(report["after_sha256"], original_after_hash)
        self.assertTrue(report["content_files_verified"])
        self.assertNotEqual(
            report["after_sha256"], hashlib.sha256(self.after.read_bytes()).hexdigest()
        )

    def test_cli_zero_drift_error_and_no_partial_failure_report(self):
        result = subprocess.run(self.command(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["content_files_verified"])
        self.write(self.after, [dict(self.row, split="eval")])
        result = subprocess.run(self.command(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(json.loads(result.stdout)["has_drift"])
        (self.new_root / "sample.txt").write_bytes(b"changed")
        result = subprocess.run(self.command(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("content differs", result.stderr)

    def test_cli_partial_roots_and_malformed_input_emit_no_report(self):
        result = subprocess.run(self.command()[:-2], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.write(self.after, [self.row, self.row])
        result = subprocess.run(self.command(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("duplicate record ID", result.stderr)


if __name__ == "__main__":
    unittest.main()
