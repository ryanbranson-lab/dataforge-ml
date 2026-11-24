# Deterministic local manifest generation

```sh
python -m dataforge.build frozen-dataset --split train --license MIT --output manifests/train.jsonl
python -m dataforge manifests/train.jsonl --root frozen-dataset
```

`build_manifest(root, *, split, license_declaration, output, check_images=False,
max_pixels=16000000)` returns a summary with schema_version, records, total_bytes,
manifest_sha256 and image_checks. The output is the existing version-1 JSONL schema,
so validation and comparison require no schema change. The caller must supply
nonblank bounded split/license declarations; they are not inferred or proof of
rights. Output's parent directory must already exist.

## Selection and deterministic identity

All regular files must have supported extensions: .txt, .png, .jpg or .jpeg
(case-insensitive matching, original case retained in paths). Text must decode as
strict UTF-8 using an incremental decoder; content is otherwise not normalized or
rewritten. Image media type is an extension declaration, not an inferred format.
Default construction only hashes image bytes. To verify/decode PNG/JPEG under
pixel limits, install requirements-images.txt and add --check-images; changed
--max-pixels requires this flag. Missing decoder or corrupt/type-mismatched images
fail construction. Existing byte-validation/comparison defaults remain unchanged.

Traversal includes hidden files and directories. Unsupported extensions, unsafe
names, symlink entries (files or directories), symlink roots, nonregular files and
permission/read errors abort: nothing is silently omitted. There is no configurable
ignore rule or automatic repair. Select a clean frozen data root instead of mixing
source code, manifests and payload files. Empty datasets remain unsupported under
the version-1 nonempty-manifest contract.

Records are sorted by canonical relative POSIX path. Stable IDs are `path-sha256:`
plus SHA-256 of that exact UTF-8 relative path. IDs are independent of absolute
root, content, split and license; moving/renaming an item changes identity, while
editing its bytes changes the content digest under the same ID. No Unicode, case
or text-content normalization is applied. JSON uses sorted fields and compact
ASCII serialization. Frozen paths/bytes plus identical declarations yield exact
identical manifest bytes; no timestamps or random IDs enter the manifest.

File hashes and total_bytes are computed from actual bounded reads, not size
metadata alone. total_bytes counts bytes processed per path, not unique physical
storage (hard-linked copies still have separate records). Before/after file
identity, size and modification time are checked to catch obvious changes during
a read. This is a best-effort check, not a race-resistant multi-file snapshot.
Duplicate content is not silently deduplicated or treated as a construction error;
run the existing validator for explicit duplicate/overlap quality findings.

## Bounds and publication

Caps: 10,000 files, 20,000 total directory entries, 32 directory levels below root,
64 MiB per file, and 8 MiB of encoded manifest bytes. Traversal and reads fail once
a cap is exceeded. Native image decoder overhead and cumulative CPU/RSS are not
fully constrained by these limits. Input must be trusted frozen local content;
no filesystem isolation, remote ingestion or distributed processing is provided.

Output must be outside the resolved dataset root, including parent symlink aliases.
This prevents a generated manifest from becoming an input on a subsequent scan.
Existing output files, directories and symlinks are never overwritten. All input
checks and full bounded JSONL assembly finish before publication. A same-directory
temporary file is flushed/fsynced and exposed using an atomic exclusive hard link;
a competing target causes failure rather than replacement. Owned temporary files
are cleaned up on ordinary exceptions. Filesystems must support local hard links.
Atomic complete visibility is the contract, not power-loss durability or directory
fsync guarantees. Process death can leave an owned temporary; it is outside input.

CLI exit 0 means construction succeeded and emits the summary. Exit 2 means an
argument, metadata, path, input, size, decoder or output conflict failure; stdout
contains no partial success report. No partial output manifest is published on
ordinary validation/read/publication errors. Payload files are never rewritten.
The summary omits license strings and record paths; the manifest itself includes
paths/declarations and should be reviewed before sharing.
