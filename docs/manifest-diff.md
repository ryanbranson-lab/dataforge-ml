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
