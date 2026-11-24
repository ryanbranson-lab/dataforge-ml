"""Bounded local manifest validation; declared media types are metadata only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

MAX_MANIFEST = 8 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_RECORDS = 10000
FIELDS = {"version", "id", "path", "split", "media_type", "sha256", "license"}
MEDIA_TYPES = {"text/plain", "image/png", "image/jpeg"}


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _text(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _relative_path(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or "\\" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("path must be a canonical relative POSIX file path")
    return relative


def _local_file(root: Path, value: str) -> Path:
    relative = _relative_path(value)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink paths are not supported")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("path must name a regular file within the dataset root")
    return resolved


def read_manifest(manifest: str | Path) -> tuple[list[tuple[int, dict[str, Any]]], str]:
    """Validate metadata without opening declared content files or verifying bytes."""
    descriptor = os.open(manifest, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("manifest input must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_MANIFEST + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_MANIFEST:
        raise ValueError("manifest exceeds 8 MiB")
    lines = raw.decode("utf-8").split("\n")
    if lines[-1] == "":
        lines.pop()
    if not 1 <= len(lines) <= MAX_RECORDS:
        raise ValueError("manifest requires 1 to 10000 records")
    rows = []
    ids: set[str] = set()
    for number, line in enumerate(lines, 1):
        try:
            row = json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
        except (ValueError, RecursionError) as exc:
            raise ValueError(f"invalid JSON at line {number}") from exc
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError(f"invalid fields at line {number}")
        if type(row["version"]) is not int or row["version"] != 1:
            raise ValueError("unsupported record version")
        if any(not _text(row[key]) for key in FIELDS - {"version"}):
            raise ValueError(f"invalid string field at line {number}")
        if row["id"] in ids:
            raise ValueError("duplicate record ID")
        ids.add(row["id"])
        if row["media_type"] not in MEDIA_TYPES:
            raise ValueError("unsupported declared media type")
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise ValueError("sha256 must be lowercase hexadecimal")
        _relative_path(row["path"])
        rows.append((number, row))
    return rows, hashlib.sha256(raw).hexdigest()


def validate(
    manifest: str | Path,
    root: str | Path,
    *,
    check_images: bool = False,
    max_pixels: int = 16_000_000,
) -> dict[str, Any]:
    """Return findings, never rewrite source files; schema or I/O errors abort.

    Files and root must be trusted, immutable local inputs during validation.
    Path checks are not race-resistant isolation against another local process.
    """
    metadata, manifest_hash = read_manifest(manifest)
    return _validate_content(
        metadata, manifest_hash, root, check_images=check_images, max_pixels=max_pixels
    )


def _validate_content(
    metadata: list[tuple[int, dict[str, Any]]],
    manifest_hash: str,
    root: str | Path,
    *,
    check_images: bool = False,
    max_pixels: int = 16_000_000,
) -> dict[str, Any]:
    """Validate content against an already parsed manifest snapshot (internal)."""
    if type(check_images) is not bool:
        raise ValueError("check_images must be boolean")
    if check_images:
        from .images import require_decoder, validate_pixel_limit

        require_decoder()
        validate_pixel_limit(max_pixels)
    elif max_pixels != 16_000_000:
        raise ValueError("max_pixels requires check_images=True")
    images_checked = 0
    base = Path(root).resolve(strict=True)
    if not base.is_dir():
        raise ValueError("root must be a directory")
    rows = [(number, row, _local_file(base, row["path"])) for number, row in metadata]
    findings = []
    seen: dict[str, tuple[int, str]] = {}
    split_seen: dict[tuple[str, str], int] = {}
    for number, row, path in rows:
        image_bytes = (
            bytearray()
            if check_images and row["media_type"].startswith("image/")
            else None
        )
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                total += len(block)
                if total > MAX_FILE:
                    raise ValueError("dataset file exceeds 64 MiB")
                digest.update(block)
                if image_bytes is not None:
                    image_bytes.extend(block)
        observed = digest.hexdigest()
        if observed != row["sha256"]:
            findings.append({"line": number, "code": "hash_mismatch"})
            continue
        if image_bytes is not None:
            from .images import check_image

            images_checked += 1
            image_finding = check_image(
                bytes(image_bytes), row["media_type"], max_pixels
            )
            if image_finding is not None:
                findings.append({"line": number, "code": image_finding})
        key = (observed, row["split"])
        if key in split_seen:
            findings.append(
                {
                    "line": number,
                    "code": "duplicate_within_split",
                    "first_line": split_seen[key],
                }
            )
        else:
            split_seen[key] = number
        if observed in seen and seen[observed][1] != row["split"]:
            findings.append(
                {
                    "line": number,
                    "code": "cross_split_overlap",
                    "first_line": seen[observed][0],
                }
            )
        else:
            seen.setdefault(observed, (number, row["split"]))
    report: dict[str, Any] = {
        "schema_version": 1,
        "manifest_sha256": manifest_hash,
        "records": len(rows),
        "ok": not findings,
        "findings": findings,
    }

    if check_images:
        report["image_validation"] = {
            "enabled": True,
            "checked": images_checked,
            "max_pixels": max_pixels,
        }
    return report
