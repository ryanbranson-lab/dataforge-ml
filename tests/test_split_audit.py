import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataforge.split_audit import audit_splits


def record(identifier, split="train", digest="a" * 64):
    return dict(
        version=1,
        id=identifier,
        path=identifier + ".txt",
        split=split,
        media_type="text/plain",
        sha256=digest,
        license="CC0-1.0",
    )


class SplitAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "manifest.jsonl"

    def write(self, rows):
        self.manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_combined_manifest_counts_distinct_cross_split_groups_and_records(self):
        self.write(
            [
                record("one"),
                record("two"),
                record("three", "eval"),
                record("four", "test", "b" * 64),
            ]
        )
        before = self.manifest.read_bytes()
        result = audit_splits(self.manifest)
        self.assertEqual(result["cross_split_sha256_groups"], 1)
        self.assertEqual(result["cross_split_sha256_records"], 3)
        self.assertEqual(result["splits"], {"eval": 1, "test": 1, "train": 2})
        self.assertEqual(result["declared_sha256_groups"], 2)
        self.assertFalse(result["ok"])
        self.assertFalse(result["content_files_verified"])
        self.assertEqual(result["manifest_sha256"], hashlib.sha256(before).hexdigest())
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn(".txt", json.dumps(result))
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_same_split_duplicates_are_not_cross_split_and_distinct_hashes_are_ok(self):
        self.write([record("a"), record("b"), record("c", "eval", "b" * 64)])
        result = audit_splits(self.manifest)
        self.assertTrue(result["ok"])
        self.assertEqual(result["cross_split_sha256_records"], 0)
        self.assertEqual(result["examples"], [])
        self.assertFalse(result["examples_truncated"])

    def test_zero_examples_and_member_limits_preserve_counts(self):
        self.write([record(str(i), str(i)) for i in range(5)])
        zero = audit_splits(self.manifest, max_examples=0)
        self.assertEqual(zero["cross_split_sha256_records"], 5)
        self.assertEqual(zero["examples"], [])
        self.assertTrue(zero["examples_truncated"])
        one = audit_splits(self.manifest, max_examples=1)["examples"][0]
        self.assertEqual(len(one["members"]), 1)
        self.assertEqual(len(one["splits"]), 1)
        self.assertTrue(one["members_truncated"])
        self.assertTrue(one["splits_truncated"])

    def test_order_independent_findings_and_only_manifest_opened(self):
        rows = [record("z"), record("a", "eval"), record("b", "test")]
        self.write(rows)
        original = os.open
        opened = []

        def checked(path, *args, **kwargs):
            self.assertEqual(Path(path), self.manifest)
            opened.append(path)
            return original(path, *args, **kwargs)

        with patch("dataforge.manifest.os.open", side_effect=checked):
            first = audit_splits(self.manifest)
        self.assertEqual(len(opened), 1)
        self.write(list(reversed(rows)))
        second = audit_splits(self.manifest)
        self.assertNotEqual(first.pop("manifest_sha256"), second.pop("manifest_sha256"))
        self.assertEqual(first, second)

    def test_bounds_and_report_limit_abort(self):
        self.write([record("a")])
        for limit in (True, -1, 101, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                audit_splits(self.manifest, max_examples=limit)
        with patch("dataforge.split_audit.MAX_REPORT_BYTES", 10):
            with self.assertRaises(ValueError):
                audit_splits(self.manifest)

    def test_malformed_duplicate_ids_and_special_files_fail_closed(self):
        self.write([record("same"), record("same", "eval")])
        with self.assertRaises(ValueError):
            audit_splits(self.manifest)
        self.manifest.write_text('{"bad":true}\n')
        with self.assertRaises(ValueError):
            audit_splits(self.manifest)
        alias = self.root / "alias"
        alias.symlink_to(self.manifest)
        with self.assertRaises(OSError):
            audit_splits(alias)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        done = subprocess.run(
            [sys.executable, "-m", "dataforge.split_audit", str(fifo)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")

    def test_cli_three_exit_outcomes_and_no_partial_error_output(self):
        args = [sys.executable, "-m", "dataforge.split_audit", str(self.manifest)]
        self.write([record("a"), record("b", "eval")])
        collision = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(collision.returncode, 1)
        self.assertFalse(json.loads(collision.stdout)["ok"])
        self.write([record("a")])
        clear = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(clear.returncode, 0)
        self.assertTrue(json.loads(clear.stdout)["ok"])
        self.manifest.write_text("bad\n")
        invalid = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stdout, "")
        self.assertNotIn(str(self.root), invalid.stderr)
