# Cross-manifest declaration audit

```sh
python -m dataforge.audit --source train=train.jsonl --source eval=eval.jsonl --max-examples 20
```

`audit_manifests(sources, *, max_examples=20)` validates 2–8 distinctly named local
version-1 manifests. It reads metadata only, never declared payload paths. A
cross-source SHA256 group means the same digest is **declared** in at least two
sources; within-source duplicates alone do not qualify. Group and participating
record counts account for all qualifying declarations. It separately counts IDs
shared by sources, marking an ID conflicting when any complete record declaration
differs, including split, path, license or digest. Identical records sharing an ID
are duplicates without a declaration conflict.

The report explicitly sets `content_files_verified=false`. Equal declarations do
not prove content equality, semantic duplication or train/test leakage. Distinct
declarations do not establish leakage freedom. Validate actual bytes separately.
Source labels are caller-defined; the command does not infer train/evaluation roles.
Findings do not make the command fail: exit 0 means a complete audit report, not a
quality verdict. Invalid inputs/options or I/O failure exit 2 without partial stdout.

Input limits are 8 MiB and 10,000 records per source (up to 64 MiB / 80,000 records
across eight). Names are bounded lowercase identifiers. Examples have strict
integer limit 0–100, rejecting booleans. Both group examples and members per SHA
group are limited; truncation flags preserve exact counts. ID groups contain at
most eight source names. Sources/groups/members sort deterministically. Row order
can change source-byte hashes, but not findings/examples. Final serialized reports
are capped at 2 MiB; request fewer examples if needed. Zero examples keeps counts.

Source paths must be distinct regular files; direct symlinks and same-inode aliases
are rejected. Inputs and directories must be trusted and frozen. Pre-open checks
are not hostile-filesystem race isolation; parent symlinks are not excluded.
Reports omit host and payload paths, but include caller labels, IDs and declared
digests. Review identifiers before sharing. No files are rewritten, no model runs,
no optional image runtime or paid resources are needed.
