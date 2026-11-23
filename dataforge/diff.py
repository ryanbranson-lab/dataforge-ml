"""Deterministic metadata comparison; no dataset content files are opened."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .manifest import FIELDS, read_manifest


def compare(before: str | Path, after: str | Path) -> dict[str, Any]:
    """Join validated records by stable ID and report declared field changes.

    Record reordering is not semantic drift, but raw input hashes still differ.
    Reports contain IDs and line numbers, never file paths, payload or field values.
    """
    old_rows, old_hash = read_manifest(before)
    new_rows, new_hash = read_manifest(after)
    old = {row["id"]: (line, row) for line, row in old_rows}
    new = {row["id"]: (line, row) for line, row in new_rows}
    added = [
        {"id": key, "line": new[key][0]} for key in sorted(new.keys() - old.keys())
    ]
    removed = [
        {"id": key, "line": old[key][0]} for key in sorted(old.keys() - new.keys())
    ]
    changed = []
    unchanged = 0
    for key in sorted(old.keys() & new.keys()):
        fields = sorted(
            field
            for field in FIELDS - {"id", "version"}
            if old[key][1][field] != new[key][1][field]
        )
        if fields:
            changed.append(
                {
                    "id": key,
                    "before_line": old[key][0],
                    "after_line": new[key][0],
                    "fields": fields,
                }
            )
        else:
            unchanged += 1
    return {
        "schema_version": 1,
        "before_sha256": old_hash,
        "after_sha256": new_hash,
        "content_files_verified": False,
        "has_drift": bool(added or removed or changed),
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    args = parser.parse_args()
    try:
        report = compare(args.before, args.after)
    except (OSError, ValueError) as exc:
        print(f"comparison failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 1 if report["has_drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
