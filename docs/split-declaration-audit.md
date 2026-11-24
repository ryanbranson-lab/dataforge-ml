# Audit split declarations in one combined manifest

```sh
python -m dataforge.split_audit combined.jsonl --max-examples 20
```

`audit_splits(manifest, *, max_examples=20)` validates the whole version-1 manifest
and groups records by their declared SHA-256. A group is cross-split when it has
at least two distinct exact split strings. Duplicate declarations within one split
are not cross-split findings. Record counts include every member of a crossing
group, including multiple members in one split. Split counts cover all input rows.

This is metadata-only: no declared payload file is opened. Equal declarations do
not establish actual byte equality, semantic duplication, statistical independence
or leakage freedom. `content_files_verified=false` is explicit. Use frozen content
validation independently when actual-byte overlap is the required question.

Reports include the input-byte digest, exact totals and stable sorted group/member
examples. Row order changes the manifest digest but not findings. `max_examples`
must be an integer0–100 (bool rejected); it bounds displayed groups, members per
group and split names per group independently. Zero hides examples but retains all
counts and truncation flags. No paths, licenses or payload text are exported;
IDs, split names and digests still reveal metadata and need review before sharing.

The shared regular-file reader enforces8 MiB/10,000-record input bounds and rejects
malformed records, duplicate IDs, final-component symlinks and special files before
reads. Reports are separately capped at2 MiB; very large split-name totals can
exceed that bound even with zero examples. Trusted frozen directories/files remain
required; parent symlinks are not excluded and no hostile-filesystem isolation or
regular-file I/O deadline is claimed. No file is created or modified.

CLI exit0 means no declared cross-split groups; exit1 means groups found; exit2
means invalid input/options or I/O/report-limit failure, with no partial stdout.
Exit0 is not a dataset quality or leakage-freedom certificate. Runtime has no
optional image/model dependency and needs no paid service.
