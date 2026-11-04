import io
import unittest

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from atrue_core.image_utils import (
    MAX_PHOTO_UPLOAD_BYTES,
    validate_establishment_photos,
    validate_image_upload,
)

INVALID_MESSAGE = 'Please upload a valid JPG, JPEG, or PNG image.'


def image_upload(name='sample.jpg', image_format='JPEG', content_type=None):
    stream = io.BytesIO()
    Image.new('RGB', (3, 3), 'blue').save(stream, format=image_format)
    if content_type is None:
        content_type = f'image/{image_format.lower()}'
    return SimpleUploadedFile(name, stream.getvalue(), content_type=content_type)


class OversizedUpload:
    name = 'large.jpg'
    size = MAX_PHOTO_UPLOAD_BYTES + 1


class PhotoUploadValidationTests(unittest.TestCase):
    def test_accepts_jpeg_and_png_extension_and_content(self):
        self.assertIsNotNone(validate_image_upload(image_upload()))
        self.assertIsNotNone(validate_image_upload(
            image_upload('sample.png', 'PNG')))

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(ValidationError) as raised:
            validate_image_upload(image_upload('photo.gif', 'GIF'))
        self.assertIn(INVALID_MESSAGE, raised.exception.messages)

    def test_rejects_format_that_does_not_match_the_extension(self):
        with self.assertRaises(ValidationError) as raised:
            validate_image_upload(image_upload('photo.png', 'JPEG'))
        self.assertIn(INVALID_MESSAGE, raised.exception.messages)

    def test_rejects_an_empty_file(self):
        with self.assertRaises(ValidationError) as raised:
            validate_image_upload(SimpleUploadedFile(
                'empty.jpg', b'', content_type='image/jpeg'))
        self.assertIn(
            'The selected image is empty. Please choose a different file.',
            raised.exception.messages,
        )

    def test_rejects_file_over_5_mb_before_decoding(self):
        with self.assertRaises(ValidationError) as raised:
            validate_image_upload(OversizedUpload())
        self.assertIn(
            'Image size must not exceed 5 MB.', raised.exception.messages)

    def test_enforces_five_photo_limit_and_allows_slots_freed_by_removal(self):
        with self.assertRaises(ValidationError) as raised:
            validate_establishment_photos([image_upload()], existing_count=5)
        self.assertIn(
            'You can upload a maximum of 5 establishment photos.',
            raised.exception.messages,
        )
        accepted = validate_establishment_photos(
            [image_upload(), image_upload()], existing_count=5, delete_count=2)
        self.assertEqual(len(accepted), 2)

    def test_failed_validation_does_not_mutate_existing_photo_state(self):
        existing_count = 3
        with self.assertRaises(ValidationError):
            validate_establishment_photos(
                [image_upload('wrong.gif', 'GIF')],
                existing_count=existing_count,
            )
        self.assertEqual(existing_count, 3)


if __name__ == '__main__':
    unittest.main()
