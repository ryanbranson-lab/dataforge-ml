"""Build deterministic local manifests without overwriting existing output."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from .manifest import (
    MAX_FILE,
    MAX_MANIFEST,
    MAX_RECORDS,
    _local_file,
    _relative_path,
    _text,
)

MEDIA_TYPES = {
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
MAX_ENTRIES = 20000
MAX_DEPTH = 32
BLOCK_BYTES = 1024 * 1024


def _scan(root: Path) -> list[str]:
    files = []
    pending = [(root, 0)]
    entries = 0
    while pending:
        directory, depth = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise ValueError("tree exceeds 20000 entries")
                path = Path(child.path)
                relative = path.relative_to(root).as_posix()
                if not _text(relative):
                    raise ValueError("invalid relative path text")
                _relative_path(relative)
                if child.is_symlink():
                    raise ValueError("symlinks are not supported")
                if child.is_dir(follow_symlinks=False):
                    if depth >= MAX_DEPTH:
                        raise ValueError("tree exceeds 32 directory levels")
                    pending.append((path, depth + 1))
                elif child.is_file(follow_symlinks=False):
                    if path.suffix.lower() not in MEDIA_TYPES:
                        raise ValueError(
                            "unsupported input extension; no files are silently omitted"
                        )
                    files.append(relative)
                    if len(files) > MAX_RECORDS:
                        raise ValueError("tree exceeds 10000 files")
                else:
                    raise ValueError("nonregular input is not supported")
    if not files:
        raise ValueError("dataset must contain at least one supported file")
    return sorted(files)


def _read_file(
    path: Path, media_type: str, check_images: bool, max_pixels: int
) -> tuple[str, int]:
    before = path.stat()
    if before.st_size > MAX_FILE:
        raise ValueError("input file exceeds 64 MiB")
    digest = hashlib.sha256()
    count = 0
    text_decoder = (
        codecs.getincrementaldecoder("utf-8")() if media_type == "text/plain" else None
    )
    image_bytes = (
        bytearray() if check_images and media_type.startswith("image/") else None
    )
    with path.open("rb") as stream:
        while block := stream.read(BLOCK_BYTES):
            count += len(block)
            if count > MAX_FILE:
                raise ValueError("input file exceeds 64 MiB")
            digest.update(block)
            if text_decoder is not None:
                text_decoder.decode(block)
            if image_bytes is not None:
                image_bytes.extend(block)
    if text_decoder is not None:
        text_decoder.decode(b"", final=True)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or count != before.st_size:
        raise ValueError("input changed while it was being read")
    if image_bytes is not None:
        from .images import check_image

        finding = check_image(bytes(image_bytes), media_type, max_pixels)
        if finding is not None:
            raise ValueError(f"image validation failed: {finding}")
    return digest.hexdigest(), count


def _publish(output: Path, raw: bytes) -> None:
    """A hard link atomically exposes complete bytes and refuses any target."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".dataforge-manifest-", dir=output.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_manifest(
    root: str | Path,
    *,
    split: str,
    license_declaration: str,
    output: str | Path,
    check_images: bool = False,
    max_pixels: int = 16_000_000,
) -> dict[str, Any]:
    """Create a version-1 manifest from trusted frozen local content.

    Supported text is strict UTF-8; image media types are extension declarations
    unless image checking is explicitly enabled. No licensing rights are inferred.
    Destination must be outside the dataset root and must not already exist.
    """
    if not _text(split) or not _text(license_declaration):
        raise ValueError("split and license must be explicit nonblank bounded text")
    if type(check_images) is not bool:
        raise ValueError("check_images must be boolean")
    if check_images:
        from .images import require_decoder, validate_pixel_limit

        require_decoder()
        validate_pixel_limit(max_pixels)
    elif max_pixels != 16_000_000:
        raise ValueError("max_pixels requires check_images=True")
    source = Path(root)
    if source.is_symlink():
        raise ValueError("dataset root must not be a symlink")
    base = source.resolve(strict=True)
    if not base.is_dir():
        raise ValueError("root must be a directory")
    destination = Path(output)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("output already exists")
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("output parent must be a directory")
    target = parent / destination.name
    if target.is_relative_to(base):
        raise ValueError("output must be outside the dataset root")
    raw = bytearray()
    total_bytes = 0
    files = _scan(base)
    for relative in files:
        path = _local_file(base, relative)
        media_type = MEDIA_TYPES[path.suffix.lower()]
        digest, count = _read_file(path, media_type, check_images, max_pixels)
        record = {
            "version": 1,
            "id": "path-sha256:" + hashlib.sha256(relative.encode("utf-8")).hexdigest(),
            "path": relative,
            "split": split,
            "media_type": media_type,
            "sha256": digest,
            "license": license_declaration,
        }
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(raw) + len(encoded) > MAX_MANIFEST:
            raise ValueError("manifest exceeds 8 MiB")
        raw.extend(encoded)
        total_bytes += count
    _publish(target, bytes(raw))
    return {
        "schema_version": 1,
        "records": len(files),
        "total_bytes": total_bytes,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "image_checks": check_images,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("--split", required=True)
    parser.add_argument("--license", required=True, dest="license_declaration")
    parser.add_argument("--output", required=True)
    parser.add_argument("--check-images", action="store_true")
    parser.add_argument("--max-pixels", type=int, default=16_000_000)
    args = parser.parse_args()
    try:
        result = build_manifest(
            args.root,
            split=args.split,
            license_declaration=args.license_declaration,
            output=args.output,
            check_images=args.check_images,
            max_pixels=args.max_pixels,
        )
    except (OSError, ValueError) as exc:
        print(f"manifest build failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
