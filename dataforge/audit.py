"""Bounded cross-manifest audit of declared digests and record identifiers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .manifest import read_manifest

MAX_SOURCES = 8
MAX_EXAMPLES = 100
MAX_REPORT_BYTES = 2 * 1024 * 1024


def audit_manifests(
    sources: dict[str, str | Path], *, max_examples: int = 20
) -> dict[str, Any]:
    """Read metadata only from frozen trusted regular manifests, never payloads."""
    if not isinstance(sources, dict) or not 2 <= len(sources) <= MAX_SOURCES:
        raise ValueError("audit requires 2 to 8 named manifests")
    if type(max_examples) is not int or not 0 <= max_examples <= MAX_EXAMPLES:
        raise ValueError("max_examples must be an integer from 0 to 100")
    if any(
        not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name)
        for name in sources
    ):
        raise ValueError("source names require bounded lowercase identifiers")
    digests: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    identifiers: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    manifests: list[dict[str, Any]] = []
    identities = set()
    for name, value in sorted(sources.items()):
        path = Path(value)
        if path.is_symlink() or not path.is_file():
            raise ValueError("sources must be trusted regular manifest files")
        info = path.stat()
        identity = (info.st_dev, info.st_ino)
        if identity in identities:
            raise ValueError("source files must be distinct")
        identities.add(identity)
        parsed_rows, digest = read_manifest(path)
        manifests.append({"name": name, "sha256": digest, "records": len(parsed_rows)})
        for _, row in parsed_rows:
            digests.setdefault(row["sha256"], []).append((name, row))
            identifiers.setdefault(row["id"], []).append((name, row))

    def members(rows: list[tuple[str, dict[str, Any]]]) -> list[dict[str, str]]:
        return [
            {"source": name, "id": row["id"]}
            for name, row in sorted(rows, key=lambda item: (item[0], item[1]["id"]))
        ]

    collision_count = collision_records = duplicate_count = conflict_count = 0
    collision_examples: list[dict[str, Any]] = []
    duplicate_examples: list[dict[str, Any]] = []
    for digest, rows in sorted(digests.items()):
        if len({name for name, _ in rows}) < 2:
            continue
        collision_count += 1
        collision_records += len(rows)
        if len(collision_examples) < max_examples:
            # Each group can itself contain 80,000 rows; bound member examples too.
            collision_examples.append(
                {
                    "sha256": digest,
                    "records": len(rows),
                    "sources": sorted({name for name, _ in rows}),
                    "members": members(rows)[:max_examples],
                    "members_truncated": len(rows) > max_examples,
                }
            )
    for identifier, rows in sorted(identifiers.items()):
        if len(rows) < 2:
            continue
        duplicate_count += 1
        conflict = any(row != rows[0][1] for _, row in rows[1:])
        conflict_count += int(conflict)
        if len(duplicate_examples) < max_examples:
            duplicate_examples.append(
                {
                    "id": identifier,
                    "conflicting_declarations": conflict,
                    "sources": sorted(name for name, _ in rows),
                }
            )
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "cross-manifest-declaration-audit",
        "content_files_verified": False,
        "sources": manifests,
        "records": sum(item["records"] for item in manifests),
        "cross_source_sha256_groups": collision_count,
        "cross_source_sha256_records": collision_records,
        "duplicate_id_groups": duplicate_count,
        "conflicting_id_groups": conflict_count,
        "max_examples": max_examples,
        "sha256_examples": collision_examples,
        "id_examples": duplicate_examples,
        "sha256_examples_truncated": collision_count > max_examples,
        "id_examples_truncated": duplicate_count > max_examples,
    }
    if (
        len(json.dumps(report, sort_keys=True, allow_nan=False).encode())
        > MAX_REPORT_BYTES
    ):
        raise ValueError("audit report exceeds 2 MiB; request fewer examples")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--max-examples", type=int, default=20)
    args = parser.parse_args()
    try:
        sources = {}
        for declaration in args.source:
            name, separator, path = declaration.partition("=")
            if not separator or not path or name in sources:
                raise ValueError("sources require unique NAME=PATH declarations")
            sources[name] = path
        report = audit_manifests(sources, max_examples=args.max_examples)
    except (OSError, ValueError, TypeError):
        print(
            "Audit failed: check manifest inputs and bounded options.", file=sys.stderr
        )
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
