# Unreleased

Initial CPU-compatible manifest validation and byte provenance foundation. No public release or production readiness claim.

Unreleased: metadata-only manifest comparison, drift classification and CLI.

Unreleased: opt-in two-root byte-verified comparison with strict hash mismatch
failures, snapshot-bound metadata and explicit quality findings; metadata-only
behavior remains unchanged.

Unreleased: optional bounded PNG/JPEG structural integrity checks, type and
animation validation, real decoding, pixel/decompression protection and mandatory
image CI. Default byte validation and comparison behavior remain unchanged.

Unreleased: bounded deterministic local manifest construction, explicit license/
split declarations, stable relative-path IDs, actual hashes/byte totals, opt-in
image checks and exclusive atomic-complete publication outside the input tree.

Unreleased: deterministic seeded split assignment by declared SHA-256 group, with
explicit fractions, full record preservation, actual counts, metadata-only status
and bounded atomic no-clobber output. No exact split-size or leakage guarantee.

Unreleased: bounded single-manifest split-declaration audit with stable examples,
complete declared-group counts, explicit metadata-only status and findings exit1.

Unreleased: aggregate content-byte budgets for validation and verified diff, with
unbuffered bounded reads, complete byte accounting including hash mismatches,
explicit per-root limits and no partial success report after budget exhaustion.
