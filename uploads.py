"""
Image upload handling.

Security posture:
- The client's declared Content-Type / filename extension is NEVER trusted.
  Every upload is opened with Pillow and verified as a genuine, decodable
  image before anything is written to disk.
- Files are re-encoded on save (not just copied) — this strips EXIF/GPS
  metadata and any non-image bytes appended to the file.
- Filenames are always server-generated (uuid4), never derived from the
  client's filename — this closes path traversal and overwrite risks.
- Flask's MAX_CONTENT_LENGTH config already rejects oversized request
  bodies before this code even runs.
"""

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from flask import current_app

# Formats we're willing to accept as input. Anything else — including a
# file that merely has a .jpg extension but isn't actually a JPEG — is
# rejected once Pillow tries to open it.
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}

MAX_AVATAR_DIMENSION = 512
MAX_POST_IMAGE_DIMENSION = 1600


class UploadError(ValueError):
    pass


def _upload_dir() -> Path:
    path = Path(current_app.root_path) / "static" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_and_verify(file_storage) -> Image.Image:
    data = file_storage.read()
    if not data:
        raise UploadError("The uploaded file is empty.")

    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()  # cheap structural check; the file object is unusable after this
    except (UnidentifiedImageError, OSError):
        raise UploadError("That doesn't look like a valid image file.")

    if probe.format not in ACCEPTED_FORMATS:
        raise UploadError(f"Unsupported image format: {probe.format}.")

    # Re-open for real use — verify() leaves the image in a closed state.
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def save_image(file_storage, *, max_dimension: int) -> str:
    """Validate, resize, strip metadata, and save an uploaded image.
    Returns a URL path suitable for storing in the DB and rendering with
    url_for('static', filename=...)."""
    image = _load_and_verify(file_storage)

    image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    filename = f"{uuid.uuid4().hex}.{'png' if has_alpha else 'jpg'}"
    dest = _upload_dir() / filename

    if has_alpha:
        image.convert("RGBA").save(dest, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(dest, format="JPEG", quality=85, optimize=True)

    return f"uploads/{filename}"


def save_avatar(file_storage) -> str:
    return save_image(file_storage, max_dimension=MAX_AVATAR_DIMENSION)


def save_post_image(file_storage) -> str:
    return save_image(file_storage, max_dimension=MAX_POST_IMAGE_DIMENSION)
