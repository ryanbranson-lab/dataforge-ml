"""Audit declared digest groups that cross split declarations in one manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .manifest import read_manifest

MAX_EXAMPLES = 100
MAX_REPORT_BYTES = 2 * 1024 * 1024


def audit_splits(manifest: str | Path, *, max_examples: int = 20) -> dict[str, Any]:
    """Inspect bounded metadata only; declared payload files are never opened."""
    if type(max_examples) is not int or not 0 <= max_examples <= MAX_EXAMPLES:
        raise ValueError("max_examples must be an integer from 0 to 100")
    rows, manifest_hash = read_manifest(manifest)
    groups: dict[str, list[dict[str, Any]]] = {}
    split_counts: dict[str, int] = {}
    for _, row in rows:
        groups.setdefault(row["sha256"], []).append(row)
        split_counts[row["split"]] = split_counts.get(row["split"], 0) + 1
    count = records = 0
    examples: list[dict[str, Any]] = []
    for digest, members in sorted(groups.items()):
        splits = sorted({row["split"] for row in members})
        if len(splits) < 2:
            continue
        count += 1
        records += len(members)
        if len(examples) < max_examples:
            ordered = sorted(members, key=lambda row: (row["split"], row["id"]))
            examples.append(
                {
                    "sha256": digest,
                    "records": len(members),
                    "splits": splits[:max_examples],
                    "splits_truncated": len(splits) > max_examples,
                    "members": [
                        {"id": row["id"], "split": row["split"]}
                        for row in ordered[:max_examples]
                    ],
                    "members_truncated": len(members) > max_examples,
                }
            )
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "cross-split-declaration-audit",
        "content_files_verified": False,
        "manifest_sha256": manifest_hash,
        "records": len(rows),
        "declared_sha256_groups": len(groups),
        "splits": dict(sorted(split_counts.items())),
        "cross_split_sha256_groups": count,
        "cross_split_sha256_records": records,
        "ok": count == 0,
        "max_examples": max_examples,
        "examples": examples,
        "examples_truncated": count > max_examples,
    }
    payload = json.dumps(report, sort_keys=True, allow_nan=False).encode()
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("audit report exceeds 2 MiB; request fewer examples")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--max-examples", type=int, default=20)
    args = parser.parse_args()
    try:
        report = audit_splits(args.manifest, max_examples=args.max_examples)
    except (OSError, ValueError, TypeError):
        print(
            "Split audit failed: check manifest and bounded options.", file=sys.stderr
        )
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
