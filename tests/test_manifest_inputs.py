import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataforge.manifest import read_manifest


class ManifestInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "manifest.jsonl"
        self.raw = (
            json.dumps(
                dict(
                    version=1,
                    id="sample",
                    path="sample.txt",
                    split="train",
                    media_type="text/plain",
                    sha256="a" * 64,
                    license="CC0-1.0",
                )
            )
            + "\n"
        ).encode()
        self.manifest.write_bytes(self.raw)

    def test_regular_file_metadata_and_digest_preserved(self):
        rows, digest = read_manifest(self.manifest)
        self.assertEqual(rows[0][1]["id"], "sample")
        self.assertEqual(digest, hashlib.sha256(self.raw).hexdigest())

    def test_fifo_validator_and_diff_terminate_without_writer(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for args in (
            ["-m", "dataforge", str(fifo), "--root", str(self.root)],
            ["-m", "dataforge.diff", str(self.manifest), str(fifo)],
        ):
            with self.subTest(args=args):
                done = subprocess.run(
                    [sys.executable, *args], capture_output=True, text=True, timeout=5
                )
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertIn("regular file", done.stderr)

    def test_direct_symlink_and_directory_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.manifest)
        with self.assertRaises(OSError):
            read_manifest(alias)
        with self.assertRaises((OSError, ValueError)):
            read_manifest(self.root)

    def test_nonregular_rejection_closes_open_descriptor(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        real_close = os.close
        closed = []

        def tracked(descriptor):
            closed.append(descriptor)
            return real_close(descriptor)

        with patch("dataforge.manifest.os.close", side_effect=tracked):
            with self.assertRaises(ValueError):
                read_manifest(fifo)
        self.assertEqual(len(closed), 1)
        with self.assertRaises(OSError):
            os.fstat(closed[0])

    def test_bounded_read_is_preserved(self):
        with patch("dataforge.manifest.MAX_MANIFEST", len(self.raw) - 1):
            with self.assertRaisesRegex(ValueError, "8 MiB"):
                read_manifest(self.manifest)
