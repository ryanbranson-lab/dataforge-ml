# Architecture decision 001: validate provenance before data processing

Implemented slice: bounded JSONL metadata validation, local file hashing and exact
byte-duplicate/split-overlap detection. The schema is one object per physical line
with exactly version=1, id, path, split, media_type, sha256 and license. IDs are
unique; string fields are nonblank, UTF-8 encodable and at most 4,096 characters.
Declared types are text/plain, image/png and image/jpeg. MIME is metadata only:
files are not decoded and their semantic contents are not validated. License is
required metadata, not a legal compatibility check. Files and metadata are never
rewritten. A final newline is optional; blank records and duplicate JSON keys fail.

The validator loads at most 8 MiB and 10,000 metadata records, then streams each
file in 1 MiB blocks, rejecting files larger than 64 MiB. Paths must be canonical
relative POSIX paths; absolute paths, dot segments, backslashes, NULs and symlinks
are rejected. Root containment and regular-file checks precede file access.
These checks assume trusted immutable local inputs and are not race-resistant
against concurrent hostile filesystem mutation.

Only hash-matching records enter duplicate checks. A within-split finding points
to the first matching record in that split; a cross-split finding points to the
first same-digest record in a different split. Earlier records are not relabeled
retroactively. Reports contain line numbers and digests, not payloads or IDs.
Schema/I/O errors abort with no report; findings produce a complete report and
nonzero findings status. Hashes describe bytes read, not an atomic dataset snapshot.

No model inference, image decoding, quality scoring, fuzzy deduplication, dataset
storage, Arrow conversion, service, or distributed processing exists yet. Next:
manifest version comparison, pinned image decoder and measured partitioned scans.
Dataset-preflight is separately owned and was not copied into this implementation.
