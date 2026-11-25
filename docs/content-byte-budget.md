# Aggregate content-byte validation budgets

```sh
python -m dataforge input.jsonl --root frozen-data --max-total-bytes 268435456
python -m dataforge.diff before.jsonl after.jsonl --before-root old-data --after-root new-data --max-total-bytes 268435456
```

`validate(..., max_total_bytes=...)` and byte-verified `compare(...,
max_total_bytes=...)` accept a strict integer1–1,073,741,824 bytes (1GiB), excluding
bool. Default is268,435,456 bytes (256MiB). Invalid budgets fail before opening the
manifest. This deliberately tightens previous default behavior: a collection of
many individually valid files can now exceed a finite aggregate limit.

The budget counts actual bytes returned by unbuffered content reads across every
record in one validation, including records whose digest later mismatches. It is
not based on declared sizes, unique paths, accepted hashes or successful image
checks. Empty files cost0 bytes. A repeated path that is opened/read again consumes
budget again. No record is silently skipped, sampled down or truncated to fit.

Each read requests at most the remaining aggregate allowance plus one detection
byte, and at most the remaining64MiB per-file allowance plus one detection byte.
If either limit is exceeded, validation aborts immediately. Accepted content reads
are at most the configured limit; an over-limit failure returns at most one extra
content byte before abort. That byte is not passed to hashing/image decoding and
there is no partial success report. Success reports include content_validation
with max_total_bytes and bytes_read, even when other quality findings exist.

These are application-returned content bytes, not a bound on OS/device read-ahead,
metadata I/O, decoded pixel memory or wall-clock duration. Content streams are
unbuffered to avoid Python read prefetch; image decoding retains its separate
pixel limit. The8MiB metadata/10,000-record and64MiB per-file limits still apply.
Source/host directories must remain trusted and frozen; path checks are not
hostile-filesystem isolation and a budget is not a timeout for slow regular files.

Verified diff applies the budget independently to each root, not to the combined
pair. Two successful root checks may return twice the configured budget in total;
if the second exceeds its budget, the whole comparison fails without a report.
This is not a simultaneous snapshot or a multi-root resource attestation.
Metadata-only comparison performs no content reads and rejects a nondefault custom
content budget without both roots. Existing default metadata-only calls remain
valid and do not claim content validation.

CLI exit2 denotes invalid options/I/O/limit failure with no success JSON. Existing
quality findings still use exit1. Inputs are never written or repaired. No model,
network, cloud allocation, deployment or paid resource is introduced.
