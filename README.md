# DataForge ML

CPU-first multimodal dataset metadata, version comparison and byte-provenance validation, owned by
`ryanbranson-lab`. This early slice validates local manifests, detects byte drift
and finds exact duplicates/overlap between dataset splits. It provides a testable
foundation for later dataset processing, not a large-scale data platform.

## Run and test

Python 3.12+; no runtime dependencies, model downloads, GPU or API keys. From this
repository root:

```sh
python -m dataforge examples/manifest.jsonl --root examples/data
python -m unittest discover -s tests -v
python -m pip install -r requirements-dev.txt
ruff check dataforge tests
ruff format --check dataforge tests
mypy
```

Each JSONL record has exactly `version` (integer 1), `id`, `path`, `split`,
`media_type`, `sha256`, `license`. Other values are nonblank strings. IDs are unique;
paths are canonical relative POSIX paths under `--root`; symlinks and traversal
are rejected. Media types: `text/plain`, `image/png`, `image/jpeg`. The lowercase
SHA-256 is checked against actual file bytes. Files must remain unchanged during
validation. License declarations are required metadata, not verified rights.

Reports include the raw manifest hash, record count and findings by line number:
`hash_mismatch`, `duplicate_within_split`, `cross_split_overlap`. Only records with
matching hashes enter duplicate checks. Exact equality compares bytes, not
normalized text or similar images. The CLI exits 0 for a clean report, 1 for
findings, 2 for invalid metadata or I/O failure. Invalid input emits no partial
report. Input files are never rewritten. Examples are original synthetic fixtures;
no employer or third-party datasets are included.

## Architecture and scope

`dataforge/manifest.py` handles bounded manifest validation and streaming hashing;
`__main__.py` provides the CLI. Limits: 8 MiB/10,000 manifest records,
4,096 characters/string, 64 MiB/content file. Tests cover schema failures, path
escape, symlinks, byte drift, duplicates, provenance and actual CLI exit codes.
CPU CI checks Python 3.12–3.14, lint and strict typing. See actual workflow results;
a prepared matrix alone is not proof that each version passed.

This slice does not decode images, verify MIME, score quality, normalize text,
detect semantic duplicates, fetch remote data or distribute work. Path checks
assume trusted immutable local inputs; they do not isolate hostile filesystem
races. No throughput, memory-scale or model-quality claims have been measured.

See [architecture](docs/architecture.md), [specification](docs/specification.json),
[contributing](CONTRIBUTING.md), [security](SECURITY.md) and [changes](CHANGELOG.md).
Next: reviewed manifest contract, version/drift comparisons, bounded image decoder
and measured partitioned processing. Audio/video and distributed services follow
only when licensing, resources and measured need justify them. MIT licensed.

Prepared by Codex with the repository owner's authorization. This is independent
new code; existing projects under other accounts were not relabeled as this
account's contributions. Genuine independent review is still required.

## Compare dataset declarations

Run `python -m dataforge.diff examples/manifest.jsonl examples/manifest-next.jsonl`.
The supplied example reports a declared split change and exits 1. Exit 0 means no
declared drift; exit 2 means invalid inputs. Content files are not opened or
verified by comparison. See [manifest comparison](docs/manifest-diff.md).

For an opt-in comparison of actual bytes in two frozen versions, supply both
`--before-root` and `--after-root` to `dataforge.diff`. A hash mismatch or missing
content aborts without a report; verified byte equality remains distinct from
reported quality findings. See the [verified-mode contract](docs/manifest-diff.md).

## Optional image integrity

Install `requirements-images.txt` and add `--check-images` to the validation CLI
to verify/decode declared PNG/JPEG records under explicit pixel bounds. Default
validation and metadata comparison remain dependency-free and byte-oriented.
This checks structural integrity, not semantic quality or safety. See
[image-integrity contracts and limits](docs/image-integrity.md).

## Build a manifest from a frozen local dataset

Run `python -m dataforge.build frozen-data --split train --license MIT --output manifests/train.jsonl`.
Supply the license declaration yourself and put output outside the data root.
Stable path IDs, hashes and byte totals come from bounded local traversal/reads;
unsupported files or errors fail rather than being silently dropped. Existing
output is never overwritten. Image decoding remains opt-in with `--check-images`.
See [manifest generation](docs/manifest-build.md) for exact bounds and semantics.

## Assign dataset splits by declared duplicate groups

`python -m dataforge.partition input.jsonl --output partitioned.jsonl --seed 42 --split train=0.8 --split eval=0.2`
keeps matching declared SHA-256 groups together, preserves IDs/paths/licenses, and
reports actual per-split counts. Assignment is reproducible and row-order independent;
sizes are not exact quotas and small splits may be empty. Grouping is metadata-only,
not proof of byte equality or leakage freedom. See [partitioning](docs/partitioning.md).

Audit cross-manifest digest declarations and ID conflicts with
`python -m dataforge.audit --source train=train.jsonl --source eval=eval.jsonl`.
See [partition audit](docs/partition-audit.md) for bounded reports and metadata-only limits.

For a single combined manifest, use
`python -m dataforge.split_audit combined.jsonl --max-examples 20` to identify
declared digest groups crossing its split fields. Exit1 reports findings; payload
files are not opened. See [split declaration audit](docs/split-declaration-audit.md).

Content validation now has a256MiB aggregate default budget. Set
`--max-total-bytes` explicitly when needed (maximum1GiB); verified diffs apply it
independently per root. See [byte-budget accounting](docs/content-byte-budget.md)
for actual returned bytes, failure detection and compatibility limits.
