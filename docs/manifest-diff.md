# Dataset manifest comparison

```sh
python -m dataforge.diff examples/manifest.jsonl examples/manifest-next.jsonl
```

The command validates both version-1 metadata manifests, joins records by stable
ID and reports added/removed IDs and changed fields. Shared record changes can
include sha256, split, path, media_type and license simultaneously. Results are
sorted by ID; source line numbers refer to each input separately. Record reordering
alone is not semantic drift, although hashes of raw manifest bytes will differ.

Exit codes: 0 no declared drift; 1 declared drift; 2 malformed metadata or I/O
failure. Errors produce no partial stdout. Reports contain IDs, line numbers,
field names and raw manifest hashes; no content payload, paths or field values.
IDs can themselves be sensitive: inspect reports before sharing.

`read_manifest` is the common bounded metadata parser used by both comparison and
byte validation. All existing schema rules, size limits, UTF-8, duplicate-key/ID,
license-metadata and canonical-path requirements apply to comparison. Empty
manifests remain invalid under version 1; an empty JSONL file cannot represent a
zero-record dataset. A future empty-dataset contract requires a reviewed version.

Comparison does not resolve paths, open content files, verify declared hashes,
validate image contents or establish license rights. `content_files_verified`
is always false. Run `python -m dataforge ... --root ...` separately against frozen
content for byte validation. Neither operation rewrites inputs or claims an atomic
snapshot of concurrently changing data. The example changes the declared split
of an original synthetic record; it is not an actual train/evaluation experiment.

## Opt-in verification of both frozen dataset roots

```sh
python -m dataforge.diff before.jsonl after.jsonl --before-root frozen-before --after-root frozen-after
```

Both root flags must be supplied together. Without them the original metadata-only
API, report and exit codes are unchanged. With them, both manifests are parsed
once and each parsed snapshot is passed to the existing bounded byte validator.
This binds comparison and verification to the same manifest-byte hashes even if a
manifest path is subsequently replaced. Freeze all manifests/content for meaningful
results: the operation does not establish a multi-file atomic filesystem snapshot.

Missing files, symlinks, unsafe paths, invalid metadata, oversized content and any
file SHA-256 mismatch abort with exit 2 and no partial stdout report. A mismatch
is an observed failure to satisfy a declaration, distinct from a legitimate
declared change between the two frozen versions. On successful byte checks,
`content_files_verified` is true and `verification.before` / `verification.after`
contain the existing validation reports. This means all declared bytes matched;
it does not prove image correctness, legal licensing rights or semantic equality.

Byte verification does not hide quality findings. Duplicate/split-overlap findings
remain in each validation report, and `verification.quality_ok` is false if either
version has findings. Verified mode exits 0 only when there is no declared drift
and both quality reports are clean; it exits 1 for declared drift or quality
findings when byte checks otherwise succeeded. A failure never prints a report
claiming `content_files_verified=true`.

Library callers use `compare(before, after, before_root=..., after_root=...)`.
Roots and content are trusted local inputs, with the same limits and filesystem-race
limitations as the standalone validator. Reports continue to omit content paths,
payloads and changed metadata values; record IDs may still be sensitive.

The common metadata reader opens manifests nonblocking, checks the opened
file descriptor is a regular file, then performs its bounded read. FIFOs and
other special files fail rather than waiting for a writer; direct manifest
symlinks are rejected. Parent directories and inputs must remain trusted and
frozen. This does not add hostile-filesystem race isolation or filesystem-root
confinement, and regular-file reads can still be subject to host I/O delays.
