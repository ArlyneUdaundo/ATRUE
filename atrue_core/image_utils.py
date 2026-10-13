"""Shared helpers for validating uploaded media files."""

from PIL import Image

MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}


class InvalidImageUpload(ValueError):
    """Raised by storage when a model/admin upload bypasses a form validator."""


def is_valid_image(fileobj):
    """Return True if the uploaded file is a decodable image.

    Runs Pillow's verify() which decodes the image header (and, when
    feasible, enough to detect truncation) without writing anything.
    The file handle is rewound so it can be re-read by the storage layer.
    """
    try:
        if getattr(fileobj, 'size', 0) > MAX_IMAGE_UPLOAD_BYTES:
            return False
        with Image.open(fileobj) as im:
            if im.format not in ALLOWED_IMAGE_FORMATS:
                return False
            im.verify()
    except Exception:
        return False
    finally:
        try:
            fileobj.seek(0)
        except (OSError, AttributeError, ValueError):
            pass
    return True
