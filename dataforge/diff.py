"""Compare metadata, optionally verifying both frozen local dataset roots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .manifest import (
    DEFAULT_TOTAL_BYTES,
    FIELDS,
    _validate_content,
    read_manifest,
    validate_total_budget,
)


def compare(
    before: str | Path,
    after: str | Path,
    *,
    before_root: str | Path | None = None,
    after_root: str | Path | None = None,
    max_total_bytes: int = DEFAULT_TOTAL_BYTES,
) -> dict[str, Any]:
    """Join validated records by stable ID and report declared field changes.

    Record reordering is not semantic drift, but raw input hashes still differ.
    Reports contain IDs and line numbers, never file paths, payload or field values.
    Both roots opt into byte verification; neither root preserves metadata-only mode.
    Hash mismatch, missing content and unsafe paths abort without a partial report.
    """
    validate_total_budget(max_total_bytes)
    if before_root is None and max_total_bytes != DEFAULT_TOTAL_BYTES:
        raise ValueError("custom content budget requires both roots")
    if (before_root is None) != (after_root is None):
        raise ValueError("before_root and after_root must be supplied together")
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
    report = {
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
    if before_root is not None and after_root is not None:
        before_check = _validate_content(
            old_rows, old_hash, before_root, max_total_bytes=max_total_bytes
        )
        after_check = _validate_content(
            new_rows, new_hash, after_root, max_total_bytes=max_total_bytes
        )
        for label, check in (("before", before_check), ("after", after_check)):
            if any(finding["code"] == "hash_mismatch" for finding in check["findings"]):
                raise ValueError(f"{label} content differs from declared SHA-256")
        report["content_files_verified"] = True
        report["verification"] = {
            "before": before_check,
            "after": after_check,
            "quality_ok": before_check["ok"] and after_check["ok"],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--before-root")
    parser.add_argument("--after-root")
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_TOTAL_BYTES)
    args = parser.parse_args()
    try:
        report = compare(
            args.before,
            args.after,
            before_root=args.before_root,
            after_root=args.after_root,
            max_total_bytes=args.max_total_bytes,
        )
    except (OSError, ValueError) as exc:
        print(f"comparison failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    quality_ok = report.get("verification", {}).get("quality_ok", True)
    return 1 if report["has_drift"] or not quality_ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
