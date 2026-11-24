import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataforge.audit import audit_manifests


def record(identifier, digest="a" * 64, **changes):
    return dict(
        version=1,
        id=identifier,
        path=identifier + ".txt",
        split="train",
        media_type="text/plain",
        sha256=digest,
        license="CC0-1.0",
        **changes,
    )


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, rows):
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_cross_source_collision_and_conflicting_ids_are_distinct(self):
        a = self.write("a", [record("one"), record("two")])
        b = self.write("b", [record("one", "b" * 64), record("three")])
        result = audit_manifests({"train": a, "eval": b})
        self.assertEqual(result["cross_source_sha256_groups"], 1)
        self.assertEqual(result["cross_source_sha256_records"], 3)
        self.assertEqual(result["duplicate_id_groups"], 1)
        self.assertEqual(result["conflicting_id_groups"], 1)
        self.assertFalse(result["content_files_verified"])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_exact_duplicate_id_is_not_conflicting(self):
        a = self.write("a", [record("same")])
        b = self.write("b", [record("same")])
        result = audit_manifests({"a": a, "b": b})
        self.assertEqual(result["duplicate_id_groups"], 1)
        self.assertEqual(result["conflicting_id_groups"], 0)

    def test_order_independent_examples_and_no_payload_opens(self):
        a = self.write("a", [record("z"), record("a")])
        b = self.write("b", [record("x")])
        original_open = os.open
        seen = []

        def checked(path, *args, **kwargs):
            self.assertIn(Path(path), (a, b))
            seen.append(Path(path))
            return original_open(path, *args, **kwargs)

        with patch("dataforge.manifest.os.open", side_effect=checked):
            first = audit_manifests({"z": a, "a": b})
        second = audit_manifests({"a": b, "z": a})
        self.assertEqual(first, second)
        self.assertEqual(len(seen), 2)
        self.assertEqual(
            [m["id"] for m in first["sha256_examples"][0]["members"]], ["x", "a", "z"]
        )

    def test_examples_and_members_are_bounded_with_exact_counts(self):
        a = self.write("a", [record(str(i)) for i in range(5)])
        b = self.write("b", [record("other")])
        one = audit_manifests({"a": a, "b": b}, max_examples=1)
        self.assertEqual(one["cross_source_sha256_records"], 6)
        self.assertEqual(len(one["sha256_examples"][0]["members"]), 1)
        self.assertTrue(one["sha256_examples"][0]["members_truncated"])
        zero = audit_manifests({"a": a, "b": b}, max_examples=0)
        self.assertEqual(zero["sha256_examples"], [])
        self.assertTrue(zero["sha256_examples_truncated"])

    def test_same_source_duplicates_are_not_cross_source(self):
        a = self.write("a", [record("one"), record("two")])
        b = self.write("b", [record("three", "b" * 64)])
        self.assertEqual(
            audit_manifests({"a": a, "b": b})["cross_source_sha256_groups"], 0
        )

    def test_bounds_reject_bool_bad_names_and_source_counts(self):
        a = self.write("a", [record("one")])
        b = self.write("b", [record("two")])
        for limit in (True, -1, 101, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                audit_manifests({"a": a, "b": b}, max_examples=limit)
        for sources in ({"a": a}, {"Bad": a, "b": b}, {str(i): a for i in range(9)}):
            with self.assertRaises(ValueError):
                audit_manifests(sources)

    def test_symlink_alias_and_fifo_rejected_without_read(self):
        a = self.write("a", [record("one")])
        alias = self.root / "alias"
        alias.symlink_to(a)
        with self.assertRaises(ValueError):
            audit_manifests({"a": a, "b": alias})
        alias.unlink()
        os.link(a, alias)
        with self.assertRaises(ValueError):
            audit_manifests({"a": a, "b": alias})
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            audit_manifests({"a": a, "b": fifo})

    def test_invalid_manifest_aborts_and_cli_has_no_partial_stdout(self):
        a = self.write("a", [record("one")])
        b = self.write("b", [record("two"), record("two")])
        with self.assertRaises(ValueError):
            audit_manifests({"a": a, "b": b})
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "dataforge.audit",
                "--source",
                f"a={a}",
                "--source",
                f"b={b}",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertNotIn(str(self.root), done.stderr)

    def test_cli_success_and_duplicate_source_name_rejected(self):
        a = self.write("a", [record("one")])
        b = self.write("b", [record("two")])
        args = [
            sys.executable,
            "-m",
            "dataforge.audit",
            "--source",
            f"a={a}",
            "--source",
            f"b={b}",
        ]
        done = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["records"], 2)
        done = subprocess.run(
            args + ["--source", f"a={a}"], capture_output=True, text=True
        )
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")

    def test_report_byte_bound_is_enforced_before_cli_output(self):
        a = self.write("a", [record("one")])
        b = self.write("b", [record("two")])
        with patch("dataforge.audit.MAX_REPORT_BYTES", 100):
            with self.assertRaises(ValueError):
                audit_manifests({"a": a, "b": b})
