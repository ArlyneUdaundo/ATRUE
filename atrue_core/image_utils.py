"""Shared helpers for validating uploaded media files."""

import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from django.core.exceptions import ValidationError

MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PHOTO_UPLOAD_BYTES = MAX_IMAGE_UPLOAD_BYTES
MAX_ESTABLISHMENT_PHOTOS = 5
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png'}
FORMAT_EXTENSIONS = {
    'JPEG': {'.jpg', '.jpeg'},
    'PNG': {'.png'},
}
INVALID_IMAGE_MESSAGE = 'Please upload a valid JPG, JPEG, or PNG image.'
OVERSIZED_IMAGE_MESSAGE = 'Image size must not exceed 5 MB.'
EMPTY_IMAGE_MESSAGE = 'The selected image is empty. Please choose a different file.'
logger = logging.getLogger(__name__)


class InvalidImageUpload(ValueError):
    """Raised by storage when a model/admin upload bypasses a form validator."""


def _file_size(fileobj):
    """Return the upload size without consuming the file pointer."""
    size = getattr(fileobj, 'size', None)
    if isinstance(size, int):
        return size
    try:
        position = fileobj.tell()
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(position)
        return size
    except (AttributeError, OSError, ValueError):
        return None


def _rewind(fileobj):
    try:
        fileobj.seek(0)
    except (AttributeError, OSError, ValueError):
        pass


def _validate_content(fileobj):
    """Validate size, real image format, and decodability."""
    size = _file_size(fileobj)
    if size is not None and size <= 0:
        raise ValidationError(EMPTY_IMAGE_MESSAGE)
    if size is not None and size > MAX_PHOTO_UPLOAD_BYTES:
        raise ValidationError(OVERSIZED_IMAGE_MESSAGE)

    try:
        with Image.open(fileobj) as image:
            if image.format not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError(INVALID_IMAGE_MESSAGE)
            image.verify()
        _rewind(fileobj)
        # verify() only checks the header. Re-open and load the pixels so a
        # truncated or corrupt image is rejected before it reaches storage.
        with Image.open(fileobj) as image:
            if image.format not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError(INVALID_IMAGE_MESSAGE)
            image.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ValidationError(INVALID_IMAGE_MESSAGE) from None
    finally:
        _rewind(fileobj)
    return fileobj


def is_valid_image(fileobj):
    """Return True when a file is a decodable JPEG/PNG within the 5 MB limit."""
    try:
        _validate_content(fileobj)
    except ValidationError:
        return False
    return True


def validate_image_upload(fileobj, *, filename=None):
    """Validate extension, MIME type, size, and decoded content."""
    name = filename if filename is not None else getattr(fileobj, 'name', '')
    suffix = Path(name or '').suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(INVALID_IMAGE_MESSAGE)

    content_type = (getattr(fileobj, 'content_type', '') or '').split(';', 1)[0].lower()
    if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValidationError(INVALID_IMAGE_MESSAGE)

    _validate_content(fileobj)
    try:
        with Image.open(fileobj) as image:
            if suffix not in FORMAT_EXTENSIONS.get(image.format, set()):
                raise ValidationError(INVALID_IMAGE_MESSAGE)
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ValidationError(INVALID_IMAGE_MESSAGE) from None
    finally:
        _rewind(fileobj)
    return fileobj


def validate_establishment_photos(files, *, existing_count=0, delete_count=0):
    """Validate a batch and enforce the five-photo limit before any DB writes."""
    files = list(files)
    for image in files:
        validate_image_upload(image)
    remaining = max(0, int(existing_count) - int(delete_count))
    if remaining + len(files) > MAX_ESTABLISHMENT_PHOTOS:
        raise ValidationError('You can upload a maximum of 5 establishment photos.')
    return files


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


def delete_stored_files(names, storages):
    """Best-effort cleanup for files written before a later database failure."""
    for storage, name in zip(storages, names):
        if not storage or not name:
            continue
        try:
            storage.delete(name)
        except Exception:
            logger.exception('Could not remove orphaned image file %s', name)
