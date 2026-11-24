"""Assign declared SHA-256 groups to deterministic weighted manifest splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from .build import _publish
from .manifest import MAX_MANIFEST, read_manifest

MAX_SPLITS = 16
DOMAIN = b"dataforge-partition-v1\x00"


def _weights(fractions: dict[str, float]) -> dict[str, float]:
    if not isinstance(fractions, dict) or not 1 <= len(fractions) <= MAX_SPLITS:
        raise ValueError("fractions requires 1 to 16 named splits")
    result = {}
    for name, value in fractions.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]{0,63}", name
        ):
            raise ValueError("split names must be bounded lowercase identifiers")
        if (
            type(value) not in (int, float)
            or not 0 <= value <= 1
            or not math.isfinite(value)
        ):
            raise ValueError(
                "fractions must be finite numbers from 0 to 1, excluding booleans"
            )
        result[name] = float(value)
    if not math.isclose(math.fsum(result.values()), 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError("fractions must sum to 1 within absolute tolerance 1e-12")
    return dict(sorted(result.items()))


def _assign(digest: str, seed: int, weights: dict[str, float]) -> str:
    raw = hashlib.sha256(
        DOMAIN + struct.pack(">I", seed) + bytes.fromhex(digest)
    ).digest()
    position = Fraction(int.from_bytes(raw, "big"), 1 << 256)
    # Exact rational comparison avoids rounding the sampled 256-bit value to 1.
    exact = {name: Fraction.from_float(value) for name, value in weights.items()}
    total = sum(exact.values(), Fraction())
    cumulative = Fraction()
    for name, weight in exact.items():
        cumulative += weight / total
        if position < cumulative:
            return name
    raise RuntimeError("partition threshold invariant violated")


def partition_manifest(
    manifest: str | Path, *, output: str | Path, seed: int, fractions: dict[str, float]
) -> dict[str, Any]:
    """Rewrite only split declarations; data files are never opened or modified.

    Equal declared digests remain grouped, but are not evidence of actual content
    equality or semantic leakage freedom. Sizes are weighted assignments, not quotas.
    """
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an unsigned 32-bit integer")
    weights = _weights(fractions)
    source = Path(manifest)
    if source.is_symlink():
        raise ValueError("input manifest must not be a symlink")
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError("input manifest must be a regular file")
    destination = Path(output)
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("output parent must be a directory")
    target = parent / destination.name
    if target == source or (target.exists() and target.samefile(source)):
        raise ValueError("input and output must not overlap")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("output already exists")
    rows, input_hash = read_manifest(source)
    group_splits = {
        digest: _assign(digest, seed, weights)
        for digest in sorted({row["sha256"] for _, row in rows})
    }
    counts = dict.fromkeys(weights, 0)
    group_counts = dict.fromkeys(weights, 0)
    for assigned in group_splits.values():
        group_counts[assigned] += 1
    raw = bytearray()
    for _, row in sorted(rows, key=lambda pair: pair[1]["id"]):
        assigned = group_splits[row["sha256"]]
        record = dict(row, split=assigned)
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(raw) + len(encoded) > MAX_MANIFEST:
            raise ValueError("partitioned manifest exceeds 8 MiB")
        raw.extend(encoded)
        counts[assigned] += 1
    _publish(target, bytes(raw))
    return {
        "schema_version": 1,
        "assignment": "sha256-weighted-v1",
        "seed": seed,
        "fractions": weights,
        "grouping": "declared-sha256",
        "content_files_verified": False,
        "input_sha256": input_hash,
        "output_sha256": hashlib.sha256(raw).hexdigest(),
        "records": len(rows),
        "groups": len(group_splits),
        "counts": counts,
        "group_counts": group_counts,
    }


def _cli_fractions(values: list[str]) -> dict[str, float]:
    result = {}
    for value in values:
        name, separator, fraction = value.partition("=")
        if not separator or name in result:
            raise ValueError("each --split requires a unique NAME=FRACTION")
        try:
            result[name] = float(fraction)
        except ValueError as exc:
            raise ValueError("invalid split fraction") from exc
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--split", action="append", required=True)
    args = parser.parse_args()
    try:
        report = partition_manifest(
            args.manifest,
            output=args.output,
            seed=args.seed,
            fractions=_cli_fractions(args.split),
        )
    except (OSError, ValueError) as exc:
        print(f"partition failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
