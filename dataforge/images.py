"""Optional bounded PNG/JPEG integrity checks on an encoded-byte snapshot."""

from __future__ import annotations

import io
import warnings

DEFAULT_MAX_PIXELS = 16_000_000
MAX_PIXELS_LIMIT = 100_000_000


def require_decoder() -> None:
    """Fail explicitly when the optional decoder is absent or permissive."""
    try:
        from PIL import ImageFile
    except ImportError as exc:
        raise ValueError("image checks require requirements-images.txt") from exc
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError("image checks require LOAD_TRUNCATED_IMAGES=False")


def validate_pixel_limit(max_pixels: int) -> None:
    if type(max_pixels) is not int or not 1 <= max_pixels <= MAX_PIXELS_LIMIT:
        raise ValueError("max_pixels must be an integer from 1 to 100000000")


def check_image(raw: bytes, declared_type: str, max_pixels: int) -> str | None:
    """Return a finding code, not semantic image quality or codec isolation."""
    from PIL import Image

    require_decoder()
    validate_pixel_limit(max_pixels)
    expected = {"image/png": "PNG", "image/jpeg": "JPEG"}[declared_type]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG"]) as image:
                if image.width * image.height > max_pixels:
                    return "image_pixel_limit"
                if image.format != expected:
                    return "image_type_mismatch"
                if getattr(image, "n_frames", 1) != 1:
                    return "image_multiframe"
                image.verify()
            # verify does not decode pixels and invalidates the image handle.
            with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG"]) as decoded:
                if decoded.width * decoded.height > max_pixels:
                    return "image_pixel_limit"
                decoded.load()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        return "image_pixel_limit"
    except (OSError, SyntaxError, ValueError):
        return "image_invalid"
    return None
