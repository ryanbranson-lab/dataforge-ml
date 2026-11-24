import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from dataforge.build import build_manifest
from dataforge.manifest import read_manifest, validate


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "dataset"
        self.root.mkdir()
        self.output = self.parent / "manifest.jsonl"
        (self.root / "one.txt").write_text(
            "original synthetic text\n", encoding="utf-8"
        )

    def build(self, **kwargs):
        return build_manifest(
            self.root,
            split="train",
            license_declaration="MIT",
            output=self.output,
            **kwargs,
        )

    def png(self):
        stream = io.BytesIO()
        Image.new("RGB", (3, 2), "blue").save(stream, format="PNG")
        return stream.getvalue()

    def command(self):
        return [
            sys.executable,
            "-m",
            "dataforge.build",
            str(self.root),
            "--split",
            "train",
            "--license",
            "MIT",
            "--output",
            str(self.output),
        ]

    def test_real_tree_hashes_sizes_schema_and_validator_compatibility(self):
        folder = self.root / "nested"
        folder.mkdir()
        (folder / "two.PNG").write_bytes(self.png())
        report = self.build(check_images=True)
        rows, digest = read_manifest(self.output)
        self.assertEqual(
            [row["path"] for _, row in rows], ["nested/two.PNG", "one.txt"]
        )
        self.assertEqual(report["records"], 2)
        self.assertEqual(
            report["total_bytes"],
            sum((self.root / row["path"]).stat().st_size for _, row in rows),
        )
        self.assertEqual(report["manifest_sha256"], digest)
        self.assertTrue(report["image_checks"])
        for _, row in rows:
            self.assertEqual(
                row["sha256"],
                hashlib.sha256((self.root / row["path"]).read_bytes()).hexdigest(),
            )
            self.assertEqual(
                row["id"],
                "path-sha256:" + hashlib.sha256(row["path"].encode()).hexdigest(),
            )
            self.assertEqual(row["license"], "MIT")
        self.assertTrue(validate(self.output, self.root, check_images=True)["ok"])

    def test_determinism_and_path_identity_survive_content_change(self):
        self.build()
        original = self.output.read_bytes()
        second = self.parent / "second.jsonl"
        build_manifest(
            self.root, split="train", license_declaration="MIT", output=second
        )
        self.assertEqual(original, second.read_bytes())
        old_id = json.loads(original)["id"]
        (self.root / "one.txt").write_text("new version")
        third = self.parent / "third.jsonl"
        build_manifest(
            self.root, split="train", license_declaration="MIT", output=third
        )
        self.assertEqual(json.loads(third.read_text())["id"], old_id)
        self.assertNotEqual(
            json.loads(third.read_text())["sha256"], json.loads(original)["sha256"]
        )

    def test_metadata_declarations_are_explicit_and_bounded(self):
        for split, license_name in [
            ("", "MIT"),
            ("train", ""),
            ("train", " " * 2),
            ("train", "x" * 4097),
            (True, "MIT"),
        ]:
            with self.subTest(split=split), self.assertRaises(ValueError):
                build_manifest(
                    self.root,
                    split=split,
                    license_declaration=license_name,
                    output=self.output,
                )
        self.assertFalse(self.output.exists())

    def test_output_inside_tree_alias_and_existing_target_are_rejected(self):
        for target in [self.root / "built.jsonl", self.root / "one.txt"]:
            with (
                self.subTest(target=target),
                self.assertRaises((ValueError, FileExistsError)),
            ):
                build_manifest(
                    self.root, split="train", license_declaration="MIT", output=target
                )
        alias = self.parent / "root-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            build_manifest(
                self.root,
                split="train",
                license_declaration="MIT",
                output=alias / "built.jsonl",
            )
        self.output.write_bytes(b"user-owned manifest")
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.output.read_bytes(), b"user-owned manifest")

    def test_output_cannot_become_input_on_rescan(self):
        self.build()
        target = self.parent / "rescanned.jsonl"
        result = build_manifest(
            self.root, split="train", license_declaration="MIT", output=target
        )
        self.assertEqual(result["records"], 1)
        self.assertEqual(self.output.read_bytes(), target.read_bytes())

    def test_no_silent_unsupported_input_or_nonregular_file(self):
        unsupported = self.root / "hidden.csv"
        unsupported.write_text("not silently dropped")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.build()
        unsupported.unlink()
        os.mkfifo(self.root / "pipe.txt")
        with self.assertRaisesRegex(ValueError, "nonregular"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_symlink_root_file_directory_and_noncanonical_filename_rejected(self):
        alias = self.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "root must not be a symlink"):
            build_manifest(
                alias, split="train", license_declaration="MIT", output=self.output
            )
        for directory in [False, True]:
            link = self.root / "link"
            link.symlink_to(
                self.parent if directory else self.root / "one.txt",
                target_is_directory=directory,
            )
            with self.assertRaisesRegex(ValueError, "symlinks"):
                self.build()
            link.unlink()
        (self.root / "bad\\name.txt").write_text("bad filename")
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.build()

    def test_limits_fail_before_publication(self):
        for limit, amount in [
            ("MAX_FILE", 3),
            ("MAX_MANIFEST", 20),
            ("MAX_RECORDS", 0),
            ("MAX_ENTRIES", 0),
        ]:
            with (
                patch("dataforge.build." + limit, amount),
                self.subTest(limit=limit),
                self.assertRaises(ValueError),
            ):
                self.build()
            self.assertFalse(self.output.exists())
        (self.root / "folder").mkdir()
        with patch("dataforge.build.MAX_DEPTH", 0), self.assertRaises(ValueError):
            self.build()

    def test_invalid_utf8_and_incremental_multibyte_text(self):
        text = self.root / "one.txt"
        text.write_bytes(b"broken \xff")
        with self.assertRaises(UnicodeError):
            self.build()
        self.assertFalse(self.output.exists())
        text.write_text("small é text", encoding="utf-8")
        with patch("dataforge.build.BLOCK_BYTES", 1):
            result = self.build()
        self.assertEqual(result["total_bytes"], len(text.read_bytes()))

    def test_image_corruption_is_opt_in_and_atomic(self):
        (self.root / "bad.png").write_bytes(b"not a PNG")
        result = self.build()
        self.assertFalse(result["image_checks"])
        other = self.parent / "verified.jsonl"
        with self.assertRaisesRegex(ValueError, "image_invalid"):
            build_manifest(
                self.root,
                split="train",
                license_declaration="MIT",
                output=other,
                check_images=True,
            )
        self.assertFalse(other.exists())

    def test_exclusive_publication_race_preserves_existing_complete_file(self):
        original_link = os.link

        def competitor(source, target):
            Path(target).write_bytes(b"competitor")
            return original_link(source, target)

        with (
            patch("dataforge.build.os.link", side_effect=competitor),
            self.assertRaises(FileExistsError),
        ):
            self.build()
        self.assertEqual(self.output.read_bytes(), b"competitor")
        self.assertEqual(list(self.parent.glob(".dataforge-manifest-*")), [])

    def test_fsync_failure_publishes_nothing_and_cleans_owned_temp(self):
        with (
            patch(
                "dataforge.build.os.fsync", side_effect=OSError("injected sync failure")
            ),
            self.assertRaises(OSError),
        ):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.parent.glob(".dataforge-manifest-*")), [])

    def test_publish_observes_complete_valid_manifest(self):
        original_link = os.link

        def inspect(source, target):
            rows, _ = read_manifest(source)
            self.assertEqual(len(rows), 1)
            self.assertFalse(Path(target).exists())
            return original_link(source, target)

        with patch("dataforge.build.os.link", side_effect=inspect):
            self.build()

    def test_cli_success_no_overwrite_and_no_optional_dependency(self):
        command = self.command()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["records"], 1)
        previous = self.output.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.output.read_bytes(), previous)
        clean_output = self.parent / "no-site.jsonl"
        command = [sys.executable, "-S"] + command[1:-1] + [str(clean_output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(clean_output.read_bytes(), previous)

    def test_empty_tree_missing_root_and_missing_output_parent(self):
        empty = self.parent / "empty"
        empty.mkdir()
        with self.assertRaises(ValueError):
            build_manifest(
                empty, split="train", license_declaration="MIT", output=self.output
            )
        for root, output in [
            (self.parent / "absent", self.output),
            (self.root, self.parent / "absent" / "manifest.jsonl"),
        ]:
            with self.assertRaises(OSError):
                build_manifest(
                    root, split="train", license_declaration="MIT", output=output
                )
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
