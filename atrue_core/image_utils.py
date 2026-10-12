"""Shared helpers for validating uploaded media files."""

from PIL import Image


def is_valid_image(fileobj):
    """Return True if the uploaded file is a decodable image.

    Runs Pillow's verify() which decodes the image header (and, when
    feasible, enough to detect truncation) without writing anything.
    The file handle is rewound so it can be re-read by the storage layer.
    """
    try:
        with Image.open(fileobj) as im:
            im.verify()
    except Exception:
        return False
    finally:
        try:
            fileobj.seek(0)
        except (OSError, AttributeError, ValueError):
            pass
    return True