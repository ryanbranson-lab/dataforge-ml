# Security

Only validate trusted local regular files and freeze the dataset during scans.
The validator does not execute commands, fetch URLs or rewrite input data. It
rejects path traversal and symlinks, but does not isolate against hostile local
filesystem races or prevent blocking if files are replaced during checks. Per-file
and manifest limits bound memory and individual content reads, not total runtime.
No sensitive record payload is included in reports. Digests may reveal membership
in known datasets; review reports before sharing. No private vulnerability-report
channel is configured; do not put secrets or sensitive datasets in public issues.
Image MIME and license declarations are not security or legal verification.

Comparison reports contain record IDs, which may be sensitive. They deliberately
omit changed values and never attest that current content matches declared hashes.

Verified comparison parses each manifest once and checks the corresponding bytes
under both explicitly supplied roots. It does not provide filesystem isolation or
an atomic snapshot across files. Both roots are required; metadata-only comparison
never silently starts accessing content. A verification failure emits no partial
report or success assertion.

Image integrity is explicitly opt-in and uses native Pillow codecs on the same
bounded byte snapshot as SHA-256. Pixel limits precede full decode, but do not
provide isolation, complete RSS/CPU quotas or protection against codec defects.
Only trusted frozen local input is supported. The decoder must not be configured
to tolerate truncated images. See docs/image-integrity.md for bounds and limits.

The local manifest builder rejects symlinks/nonregular/unsupported inputs and
requires output outside the dataset root. It scans trusted frozen files without
filesystem-race isolation. Complete output is published exclusively; prior files
are never replaced, and input bytes are never rewritten. License declarations
are caller-supplied metadata, not inferred rights. See docs/manifest-build.md.

Partitioning only rewrites validated split declarations into a new exclusive output;
it does not open content files or verify declared digests. Matching digest metadata
is not proof of actual byte equality or absence of semantic leakage. Input/output
aliases and overwrites are rejected; atomic publication has the builder's same
trusted-filesystem and durability limits. See docs/partitioning.md.
