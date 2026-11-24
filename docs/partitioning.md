# Deterministic declared-digest group partitioning

```sh
python -m dataforge.partition input.jsonl --output partitioned.jsonl --seed 42 --split train=0.8 --split eval=0.2
```

`partition_manifest(manifest, *, output, seed, fractions)` validates the complete
version-1 manifest and writes one new combined manifest with assigned split fields.
No payload file is opened, moved, copied or changed. All input records, IDs, paths,
licenses, media types and content declarations are retained; only split is replaced.
Output records are sorted by exact ID and compact sorted-key JSON is deterministic.
Input row order can change the input-byte hash, but not assignments/output bytes.
Prior split declarations are intentionally replaced, not treated as constraints.

## Grouping and assignment contract: sha256-weighted-v1

Group records by their declared lowercase SHA-256 string, so matching declarations
cannot cross assigned splits. Compute SHA-256 of:

`b"dataforge-partition-v1\x00"` (where \x00 denotes one NUL byte), followed by the
seed as unsigned four-byte big-endian integer, then the 32 decoded digest bytes.
Interpret all 256 hash bits as an unsigned integer divided by 2^256. Select a
half-open cumulative weighted interval in lexicographic split-name order. Fraction
values are the exact rationals represented by the supplied Python floats; their
sum is normalized exactly for interval construction. No hash-to-float conversion
can round the sample to 1 and lose a record. New groups do not reshuffle existing
groups when seed/configuration are unchanged. Dictionary insertion order is irrelevant.

Seed must be an integer 0–2^32-1; bool is rejected. Supply 1–16 uniquely named splits
with lowercase identifiers up to 64 characters. Values must be finite int/float
numbers in [0,1], excluding bool; sum must equal 1 within absolute tolerance 1e-12
(no relative tolerance). Tiny representation differences are normalized as above.
Zero-weight splits are permitted and receive no groups. CLI repeats --split
NAME=FRACTION; duplicate names, malformed values, NaN/Infinity and bad sums fail.
The report records requested fractions, seed and algorithm name for reproduction.

## Counts are observations, not quotas

Assignments are weighted hash buckets, not exact-size stratification. Entire groups
stay together, even if large. Reported counts and group_counts include every
configured split, including zero; their sums account for all input rows/groups.
Small datasets may have empty splits or very uneven sizes. No exact proportions,
nonempty holdout, class balance or statistical independence is guaranteed. Changing
the seed can change assignments but is not guaranteed to move every/small group.

## Trust, limits and output

Grouping is **metadata-only**: `grouping="declared-sha256"` and
`content_files_verified=false` are explicit in every summary. A declaration can be
wrong, and equal declarations do not establish actual byte equality or any semantic
leakage guarantee. Validate frozen content independently first; near-duplicates,
related samples and train/test contamination require additional policies. This
command performs no model evaluation or semantic deduplication.

Existing full metadata validation applies: malformed versions/fields, duplicate IDs,
unsafe paths, bad hashes, empty manifests and input limits abort. Input must be a
trusted regular manifest file, not a symlink or pipe. Existing 10,000-record and
8 MiB manifest limits apply; output is separately capped at 8 MiB after serialization.
IDs, names and paths are not normalized silently. Input/output aliases or hard-link
overlap are rejected, and no existing target, including symlinks, is overwritten.
Output's parent must exist. Complete bytes use the builder's flushed/fsynced temp
and exclusive atomic hard-link publication. Ordinary failures emit no partial
success report or partial target; a racing target is preserved. Local hard-link
support is required; this is not power-loss/directory-sync durability or hostile
filesystem-race isolation. Owned temporary files may remain after process death.

CLI exits 0 for successful assignment/publication and 2 for invalid input/configuration,
I/O or output conflict, with no partial stdout on failure. Success is not a dataset
quality/leakage verdict. The summary includes hashes/counts/configuration, not record
payloads or paths. The output manifest still contains existing paths/declarations,
so review it before sharing. No optional Pillow dependency or paid resource is needed.
