import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataforge.manifest import read_manifest, validate
from dataforge.partition import partition_manifest


class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.jsonl"
        self.output = self.root / "output.jsonl"
        self.row = {
            "version": 1,
            "id": "one",
            "path": "unavailable.txt",
            "split": "original",
            "media_type": "text/plain",
            "sha256": "a" * 64,
            "license": "MIT",
        }
        self.rows = [
            dict(
                self.row,
                id=f"row-{i:03}",
                sha256=hashlib.sha256(str(i // 2).encode()).hexdigest(),
            )
            for i in range(80)
        ]
        self.write(self.rows)

    def write(self, rows):
        self.source.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def partition(self, **kwargs):
        return partition_manifest(
            self.source,
            output=self.output,
            seed=7,
            fractions={"train": 0.8, "eval": 0.2},
            **kwargs,
        )

    def command(self):
        return [
            sys.executable,
            "-m",
            "dataforge.partition",
            str(self.source),
            "--output",
            str(self.output),
            "--seed",
            "7",
            "--split",
            "train=0.8",
            "--split",
            "eval=0.2",
        ]

    def test_duplicate_groups_never_cross_and_records_are_preserved(self):
        payload = self.root / "unavailable.txt"
        payload.write_bytes(b"original payload must remain unchanged")
        report = self.partition()
        self.assertEqual(
            payload.read_bytes(), b"original payload must remain unchanged"
        )
        new, digest = read_manifest(self.output)
        groups = {}
        original = {row["id"]: row for row in self.rows}
        self.assertEqual(len(new), len(self.rows))
        for _, row in new:
            groups.setdefault(row["sha256"], set()).add(row["split"])
            self.assertEqual(
                {k: v for k, v in row.items() if k != "split"},
                {k: v for k, v in original[row["id"]].items() if k != "split"},
            )
        self.assertTrue(all(len(splits) == 1 for splits in groups.values()))
        self.assertEqual(report["groups"], 40)
        self.assertEqual(sum(report["counts"].values()), 80)
        self.assertEqual(sum(report["group_counts"].values()), 40)
        self.assertEqual(report["output_sha256"], digest)
        self.assertEqual(
            report["input_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest()
        )
        self.assertFalse(report["content_files_verified"])
        self.assertEqual(report["grouping"], "declared-sha256")
        self.assertEqual(
            payload.read_bytes(), b"original payload must remain unchanged"
        )

    def test_reordering_input_and_config_preserves_exact_output(self):
        self.partition()
        first = self.output.read_bytes()
        second = self.root / "second.jsonl"
        self.write(list(reversed(self.rows)))
        report = partition_manifest(
            self.source, output=second, seed=7, fractions={"eval": 0.2, "train": 0.8}
        )
        self.assertEqual(first, second.read_bytes())
        self.assertEqual(report["output_sha256"], hashlib.sha256(first).hexdigest())
        self.assertEqual(
            [row["id"] for _, row in read_manifest(second)[0]],
            sorted(row["id"] for row in self.rows),
        )

    def test_seed_changes_some_assignments_and_keeps_groups(self):
        self.partition()
        old = {row["id"]: row["split"] for _, row in read_manifest(self.output)[0]}
        second = self.root / "second.jsonl"
        partition_manifest(
            self.source, output=second, seed=8, fractions={"train": 0.8, "eval": 0.2}
        )
        new = {row["id"]: row["split"] for _, row in read_manifest(second)[0]}
        self.assertNotEqual(old, new)

    def test_small_groups_allow_empty_splits_and_no_size_guarantee(self):
        self.write([self.row, dict(self.row, id="two")])
        report = self.partition()
        self.assertEqual(sorted(report["counts"].values()), [0, 2])
        self.assertEqual(sorted(report["group_counts"].values()), [0, 1])
        other = self.root / "all.jsonl"
        report = partition_manifest(
            self.source, output=other, seed=0, fractions={"train": 0, "eval": 1}
        )
        self.assertEqual(report["counts"], {"eval": 2, "train": 0})

    def test_existing_byte_validator_accepts_combined_output_with_empty_split(self):
        content = self.root / "real.txt"
        content.write_bytes(b"original synthetic partition fixture")
        row = dict(
            self.row,
            path="real.txt",
            sha256=hashlib.sha256(content.read_bytes()).hexdigest(),
        )
        self.write([row])
        report = self.partition()
        self.assertEqual(sorted(report["counts"].values()), [0, 1])
        self.assertTrue(validate(self.output, self.root)["ok"])
        self.assertEqual(read_manifest(self.output)[0][0][1]["id"], row["id"])

    def test_fraction_types_finiteness_sum_names_and_count_bounds(self):
        for fractions in [
            {},
            [],
            {"train": True},
            {"train": float("nan")},
            {"train": math.inf},
            {"train": -1, "eval": 2},
            {"train": "1"},
            {"train": 0.7, "eval": 0.2},
            {"Train": 1},
            {"bad name": 1},
            {str(i): 1 / 17 for i in range(17)},
            {"train": 10**1000},
        ]:
            with self.subTest(fractions=fractions), self.assertRaises(ValueError):
                partition_manifest(
                    self.source, output=self.output, seed=7, fractions=fractions
                )
            self.assertFalse(self.output.exists())

    def test_valid_float_rounding_is_normalized_without_record_loss(self):
        report = partition_manifest(
            self.source,
            output=self.output,
            seed=2**32 - 1,
            fractions={"train": 0.1, "dev": 0.2, "eval": 0.7},
        )
        self.assertEqual(sum(report["counts"].values()), len(self.rows))
        self.assertEqual(len(read_manifest(self.output)[0]), len(self.rows))

    def test_seed_bounds_exclude_booleans(self):
        for seed in [True, -1, 2**32, 1.5, "7"]:
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                partition_manifest(
                    self.source, output=self.output, seed=seed, fractions={"train": 1}
                )
        self.assertFalse(self.output.exists())

    def test_invalid_input_metadata_never_publishes(self):
        for rows in [
            [],
            [self.row, self.row],
            [dict(self.row, version=2)],
            [dict(self.row, license="")],
            [dict(self.row, path="../escape")],
            [dict(self.row, sha256="bad")],
        ]:
            self.write(rows)
            with self.assertRaises(ValueError):
                self.partition()
            self.assertFalse(self.output.exists())
        for raw in [b"\xff", b'{"id":1,"id":2}\n', b'{"x":NaN}\n']:
            self.source.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.partition()

    def test_no_overwrite_input_overlap_hardlink_and_symlinks(self):
        original = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "overlap"):
            partition_manifest(
                self.source, output=self.source, seed=7, fractions={"train": 1}
            )
        os.link(self.source, self.output)
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.partition()
        self.assertEqual(self.source.read_bytes(), original)
        self.output.unlink()
        self.output.symlink_to(self.source)
        with self.assertRaises((ValueError, FileExistsError)):
            self.partition()
        self.output.unlink()
        self.output.write_bytes(b"user-owned output")
        with self.assertRaises(FileExistsError):
            self.partition()
        self.assertEqual(self.output.read_bytes(), b"user-owned output")
        self.assertEqual(self.source.read_bytes(), original)

    def test_atomic_publication_failure_and_output_size_limit(self):
        with (
            patch("dataforge.partition.MAX_MANIFEST", 10),
            self.assertRaises(ValueError),
        ):
            self.partition()
        self.assertFalse(self.output.exists())
        with (
            patch("dataforge.build.os.fsync", side_effect=OSError("injected failure")),
            self.assertRaises(OSError),
        ):
            self.partition()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".dataforge-manifest-*")), [])
        original_link = os.link

        def race(source, target):
            Path(target).write_bytes(b"racing owner")
            return original_link(source, target)

        with (
            patch("dataforge.build.os.link", side_effect=race),
            self.assertRaises(FileExistsError),
        ):
            self.partition()
        self.assertEqual(self.output.read_bytes(), b"racing owner")

    def test_cli_success_duplicate_ratios_errors_and_no_site_dependency(self):
        result = subprocess.run(self.command(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["content_files_verified"])
        original = self.output.read_bytes()
        result = subprocess.run(self.command(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.output.read_bytes(), original)
        for addition in [
            ["--split", "train=0.1"],
            ["--split", "bad"],
            ["--split", "more=NaN"],
        ]:
            command = self.command()
            command[command.index("--output") + 1] = str(self.root / "invalid.jsonl")
            result = subprocess.run(command + addition, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertFalse((self.root / "invalid.jsonl").exists())
        command = self.command()
        command[command.index("--output") + 1] = str(self.root / "no-site.jsonl")
        result = subprocess.run(
            [sys.executable, "-S"] + command[1:], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "no-site.jsonl").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
