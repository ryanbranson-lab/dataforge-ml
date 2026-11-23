# DataForge ML

CPU-first multimodal dataset metadata and byte-provenance validation, owned by
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
