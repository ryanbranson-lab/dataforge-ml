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
