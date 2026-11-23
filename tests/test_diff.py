import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataforge.diff import compare


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.before = self.root / "old.jsonl"
        self.after = self.root / "new.jsonl"
        self.row = {
            "version": 1,
            "id": "one",
            "path": "absent.txt",
            "split": "train",
            "media_type": "text/plain",
            "sha256": "a" * 64,
            "license": "MIT",
        }
        self.write(self.before, [self.row])
        self.write(self.after, [self.row])

    def write(self, path, rows):
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def test_reorder_not_drift_but_changes_hash(self):
        rows = [self.row, dict(self.row, id="two")]
        self.write(self.before, rows)
        self.write(self.after, list(reversed(rows)))
        report = compare(self.before, self.after)
        self.assertFalse(report["has_drift"])
        self.assertEqual(report["unchanged"], 2)
        self.assertNotEqual(report["before_sha256"], report["after_sha256"])
        self.assertEqual(
            report["before_sha256"],
            hashlib.sha256(self.before.read_bytes()).hexdigest(),
        )

    def test_added_removed_and_stable_sort(self):
        self.write(self.before, [self.row, dict(self.row, id="removed")])
        self.write(
            self.after, [dict(self.row, id="z"), self.row, dict(self.row, id="a")]
        )
        report = compare(self.before, self.after)
        self.assertEqual(
            report["added"], [{"id": "a", "line": 3}, {"id": "z", "line": 1}]
        )
        self.assertEqual(report["removed"], [{"id": "removed", "line": 2}])
        self.assertEqual(report["unchanged"], 1)

    def test_simultaneous_changes_are_classified_without_values(self):
        self.write(
            self.after,
            [
                dict(
                    self.row,
                    split="eval",
                    sha256="b" * 64,
                    path="sensitive-name.txt",
                    license="Apache-2.0",
                    media_type="image/png",
                )
            ],
        )
        report = compare(self.before, self.after)
        self.assertEqual(
            report["changed"][0]["fields"],
            ["license", "media_type", "path", "sha256", "split"],
        )
        self.assertNotIn("sensitive-name", json.dumps(report))
        self.assertNotIn("Apache", json.dumps(report))
        self.assertTrue(report["has_drift"])

    def test_content_is_not_opened_or_attested(self):
        self.assertFalse(compare(self.before, self.after)["content_files_verified"])
        self.assertFalse((self.root / "absent.txt").exists())
        with patch(
            "dataforge.manifest._local_file",
            side_effect=AssertionError("content must not be resolved"),
        ):
            compare(self.before, self.after)

    def test_invalid_metadata_in_either_input(self):
        for path in [self.before, self.after]:
            original = path.read_bytes()
            for rows in [
                [],
                [self.row, self.row],
                [dict(self.row, version=2)],
                [dict(self.row, path="../escape")],
                [dict(self.row, license="")],
            ]:
                self.write(path, rows)
                with self.subTest(path=path, rows=rows), self.assertRaises(ValueError):
                    compare(self.before, self.after)
            path.write_bytes(original)

    def test_strict_json_and_missing_file(self):
        for raw in [b"\xff", b"\n", b'{"id":1,"id":2}\n', b'{"x":NaN}\n']:
            self.after.write_bytes(raw)
            with self.assertRaises(ValueError):
                compare(self.before, self.after)
        with self.assertRaises(OSError):
            compare(self.before, self.root / "missing")

    def test_cli_exit_codes_and_no_partial_output(self):
        cmd = [
            sys.executable,
            "-m",
            "dataforge.diff",
            str(self.before),
            str(self.after),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.write(self.after, [dict(self.row, split="eval")])
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["has_drift"])
        self.after.write_text("{}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("comparison failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
