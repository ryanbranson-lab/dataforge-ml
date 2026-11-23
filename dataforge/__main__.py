"""Validate local JSONL byte-provenance manifests."""

import argparse
import json
import sys

from .manifest import validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        report = validate(args.manifest, args.root)
    except (OSError, ValueError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
