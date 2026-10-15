"""Shared helpers for validating uploaded media files."""

import logging

from PIL import Image

MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}
logger = logging.getLogger(__name__)


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


def delete_image_record(instance, field_name='image'):
    """Delete an image record and remove its stored file when possible.

    Django does not remove a FileField's stored object when its model row is
    deleted. Remove the database record first so the gallery reflects the
    successful request, then clean up the now-unreferenced file. A storage
    cleanup failure is logged without turning a successful record deletion
    into a misleading failed form response.
    """
    image = getattr(instance, field_name, None)
    storage = getattr(image, 'storage', None)
    name = getattr(image, 'name', '') if image else ''
    instance.delete()
    if storage and name:
        try:
            storage.delete(name)
        except Exception:
            logger.exception('Could not remove deleted image file %s', name)
