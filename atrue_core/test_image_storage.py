"""Regression tests for image validation and durable-storage upload behavior."""

from io import BytesIO
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.db import transaction
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from atrue_core.image_utils import (
    ALLOWED_IMAGE_FORMATS,
    InvalidImageUpload,
    MAX_IMAGE_UPLOAD_BYTES,
    is_valid_image,
)
from atrue_core.storage_backends import SupabasePublicStorage
from atrue_core.middleware import StorageUploadErrorMiddleware
from hotels.models import Hotel, HotelPhoto


def image_upload(image_format='PNG', name=None):
    stream = BytesIO()
    Image.new('RGB', (3, 3), color='red').save(stream, format=image_format)
    extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif'}[image_format]
    return SimpleUploadedFile(
        name or f'test.{extension}', stream.getvalue(),
        content_type=f'image/{extension}',
    )


class ImageValidationTests(SimpleTestCase):
    def test_accepts_jpeg_png_and_webp_image_bytes(self):
        self.assertEqual(ALLOWED_IMAGE_FORMATS, {'JPEG', 'PNG', 'WEBP'})
        for image_format in ('JPEG', 'PNG', 'WEBP'):
            with self.subTest(image_format=image_format):
                self.assertTrue(is_valid_image(image_upload(image_format)))

    def test_rejects_gif_and_non_image_bytes(self):
        self.assertFalse(is_valid_image(image_upload('GIF')))
        self.assertFalse(is_valid_image(SimpleUploadedFile(
            'not-an-image.png', b'not image bytes', content_type='image/png')))

    def test_rejects_image_above_server_size_limit(self):
        valid = image_upload('PNG')
        oversized = SimpleUploadedFile(
            'large.png', valid.read() + b'x' * (MAX_IMAGE_UPLOAD_BYTES + 1),
            content_type='image/png')
        self.assertFalse(is_valid_image(oversized))

    def test_storage_boundary_rejects_uploads_that_bypass_form_validation(self):
        storage_env = {
            'SUPABASE_S3_ENDPOINT': 'https://project.storage.supabase.co/storage/v1/s3',
            'SUPABASE_S3_ACCESS_KEY_ID': 'test-access',
            'SUPABASE_S3_SECRET_ACCESS_KEY': 'test-secret',
            'SUPABASE_STORAGE_REGION': 'ap-southeast-1',
            'SUPABASE_STORAGE_BUCKET': 'establishment-images',
        }
        with patch.dict('os.environ', storage_env, clear=False):
            storage = SupabasePublicStorage()
        with self.assertRaises(InvalidImageUpload):
            storage._save('hotel_photos/invalid.png', BytesIO(b'not an image'))

    def test_missing_supabase_configuration_fails_closed_in_production(self):
        with override_settings(DEBUG=False, SUPABASE_PRIVATE_STORAGE_CONFIGURED=False):
            storage = StorageUploadErrorMiddleware(lambda request: None)
            response = storage.process_exception(
                None, ImproperlyConfigured('Configure SUPABASE credentials'))
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'image storage is unavailable', response.content.lower())


class ImageUploadIntegrationTests(TestCase):
    def setUp(self):
        self.hotel = Hotel.objects.create(name='Storage test hotel')
        self.field = HotelPhoto._meta.get_field('image')

    def test_upload_saves_database_path_and_public_image_url(self):
        storage = Mock()
        storage.save.return_value = 'hotel_photos/unique-test.png'
        with patch.object(self.field, 'storage', storage):
            photo = HotelPhoto.objects.create(
                hotel=self.hotel, image=image_upload('PNG'))

        photo.refresh_from_db()
        self.assertEqual(photo.image.name, 'hotel_photos/unique-test.png')
        storage_env = {
            'SUPABASE_URL': 'https://project.supabase.co',
            'SUPABASE_S3_ENDPOINT': 'https://project.storage.supabase.co/storage/v1/s3',
            'SUPABASE_S3_ACCESS_KEY_ID': 'test-access',
            'SUPABASE_S3_SECRET_ACCESS_KEY': 'test-secret',
            'SUPABASE_STORAGE_REGION': 'ap-southeast-1',
            'SUPABASE_STORAGE_BUCKET': 'establishment-images',
        }
        with patch.dict('os.environ', storage_env, clear=False):
            url = SupabasePublicStorage().url(photo.image.name)
        self.assertIn('/establishment-images/hotel_photos/unique-test.png', url)
        self.assertTrue(url.startswith('https://project.supabase.co/'))
        storage.save.assert_called_once()

    def test_storage_failure_does_not_create_photo_record(self):
        storage = Mock()
        storage.save.side_effect = OSError('Supabase unavailable')
        with patch.object(self.field, 'storage', storage):
            with self.assertRaises(OSError), transaction.atomic():
                HotelPhoto.objects.create(
                    hotel=self.hotel, image=image_upload('PNG'))
        self.assertFalse(HotelPhoto.objects.filter(hotel=self.hotel).exists())

    def test_anonymous_user_cannot_access_admin_upload_handler(self):
        response = self.client.post(reverse('hotels:add'), data={
            'name': 'Unauthorized hotel',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Hotel.objects.filter(name='Unauthorized hotel').exists())

    def test_non_manager_cannot_access_admin_upload_handler(self):
        user = get_user_model().objects.create_user(
            username='image-customer', password='test-password')
        self.client.force_login(user)
        response = self.client.post(reverse('hotels:add'), data={
            'name': 'Unauthorized hotel',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Hotel.objects.filter(name='Unauthorized hotel').exists())
