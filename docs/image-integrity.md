# Opt-in PNG/JPEG image integrity

Install `python -m pip install -r requirements-images.txt`, then run:

```sh
python -m dataforge manifest.jsonl --root frozen-data --check-images --max-pixels 16000000
```

The optional runtime dependency is pinned to Pillow 13.0.0, the current stable
release checked for this change. [Official image API](https://pillow.readthedocs.io/en/stable/reference/Image.html)
and [license](https://github.com/python-pillow/Pillow/blob/13.0.0/LICENSE).
Pillow uses MIT-CMU; repository code remains MIT. No dependency source or wheels
are vendored; preserve upstream license notices if redistributing dependencies.

Without `--check-images`, original byte validation, report shape, exit codes and
standard-library-only runtime remain unchanged. `--max-pixels` requires image mode
when changed from its default. Metadata-only and two-root comparison modes are
unchanged; they do not silently enable a decoder.

Image mode requires the optional decoder explicitly, even for an all-text input.
Missing dependency or permissive global LOAD_TRUNCATED_IMAGES configuration causes
exit 2 with no report. The implementation never changes Pillow's global limits
or truncated-image flag. Do not concurrently mutate decoder globals in an embedded
application. Development dependencies include the decoder so tests/type checking
run against its types; ordinary runtime usage does not require development tools.

For each hash-matching record declared image/png or image/jpeg, the validator
retains the bounded encoded-byte snapshot used by SHA-256 and checks only PNG/JPEG
formats. It checks dimensions before pixel loading, compares the detected format
with the declaration, rejects multiple frames, calls verify(), then reopens the
same snapshot and calls load() to actually decode pixels. Pillow verify() alone
does not decode. Pixel count defaults to 16,000,000 and can be set from 1 through
100,000,000. Pillow decompression warnings/errors are failures too. Text records
are not decoded or reclassified as images.

## Findings and results

Image findings are image_invalid (broken/unidentified/truncated content),
image_type_mismatch, image_multiframe and image_pixel_limit. Existing hash mismatch
findings take precedence: mismatching bytes are not fed to a decoder. The optional
image_validation field reports enabled=true, attempted image count and pixel limit;
it is not a success claim. Overall ok=false and exit 1 mean one or more findings.
Schema/path/I/O/configuration errors remain exit 2 with no partial stdout. Reports
contain neither payloads nor image metadata such as EXIF or decoded dimensions.

## Bounds and trust

Existing bounds remain 64 MiB per content file and 8 MiB/10,000 manifest records.
Only image-mode image records retain encoded bytes; all reads and hashes bind to
that snapshot. Native codec overhead, compressed metadata, total dataset CPU time,
RSS and cumulative scan cost are not fully controlled by pixel/file limits. This
is not a sandbox or guarantee against decoder vulnerabilities. Use trusted frozen
local inputs and keep codecs maintained; hostile files need process isolation and
resource budgets beyond this prototype. Filesystem checks remain non-race-resistant.

Successful decode establishes bounded structural integrity under the tested
codec, not visual meaning, perceptual quality, OCR correctness, safety, licensing
rights, absence of hidden data, or training usefulness. Inputs are never rewritten.
All image tests generate original small synthetic pixel fixtures in temporary
folders; no real-world or third-party images or model results are included.

The mandatory image-integrity CI job installs the pinned optional dependency and
runs real PNG/JPEG decode and failure tests without skips. The regular supported
Python matrix runs the regression suite, including a real `python -S` subprocess
that proves default validation works without site packages and image mode fails
explicitly when the decoder is absent.
