"""Supabase Storage backends for public listings and private profile images."""

import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage, storages
from django.utils.deconstruct import deconstructible
from storages.backends.s3 import S3Storage

from atrue_core.image_utils import InvalidImageUpload, is_valid_image


class _SupabaseS3Storage(S3Storage):
    """Shared server-side S3 configuration for Supabase Storage."""

    bucket_env = ''
    private = False

    def __init__(self, **kwargs):
        endpoint = os.getenv('SUPABASE_S3_ENDPOINT', '').strip()
        access_key = os.getenv('SUPABASE_S3_ACCESS_KEY_ID', '').strip()
        secret_key = os.getenv('SUPABASE_S3_SECRET_ACCESS_KEY', '').strip()
        region = os.getenv('SUPABASE_STORAGE_REGION', '').strip()
        bucket = os.getenv(self.bucket_env, '').strip()
        if not all((endpoint, access_key, secret_key, region, bucket)):
            raise ImproperlyConfigured(
                'Configure SUPABASE_S3_ENDPOINT, SUPABASE_S3_ACCESS_KEY_ID, '
                'SUPABASE_S3_SECRET_ACCESS_KEY, SUPABASE_STORAGE_REGION, and '
                f'{self.bucket_env} before uploading files.'
            )
        kwargs.setdefault('bucket_name', bucket)
        kwargs.setdefault('endpoint_url', endpoint)
        kwargs.setdefault('region_name', region)
        kwargs.setdefault('access_key', access_key)
        kwargs.setdefault('secret_key', secret_key)
        kwargs.setdefault('addressing_style', 'path')
        kwargs.setdefault('signature_version', 's3v4')
        kwargs.setdefault('file_overwrite', False)
        kwargs.setdefault('default_acl', None)
        kwargs.setdefault('querystring_auth', self.private)
        kwargs.setdefault('querystring_expire', 3600)
        if not self.private:
            parsed = urlparse(os.getenv('SUPABASE_URL', endpoint))
            if not parsed.hostname:
                parsed = urlparse(endpoint)
            kwargs.setdefault(
                'custom_domain',
                f'{parsed.netloc}/storage/v1/object/public/{bucket}',
            )
            kwargs.setdefault('url_protocol', 'https:')
        super().__init__(**kwargs)

    def _save(self, name, content):
        # Enforce the upload rules at the storage boundary too, so Django admin
        # and any future ImageField handler cannot bypass the view validation.
        if not is_valid_image(content):
            raise InvalidImageUpload(
                'Upload a valid JPEG, PNG, or WebP image no larger than 10 MB.'
            )
        return super()._save(name, content)


class SupabasePublicStorage(_SupabaseS3Storage):
    """Public URLs for establishment, room, airline, and gallery images."""

    bucket_env = 'SUPABASE_STORAGE_BUCKET'
    # Public URLs are deterministic and do not need an S3 HEAD request before
    # rendering. Avoiding one remote request per gallery image keeps listing
    # pages responsive under concurrent traffic.
    can_render_url_without_exists_check = True


class SupabasePrivateStorage(_SupabaseS3Storage):
    """Time-limited signed URLs for account profile pictures."""

    bucket_env = 'SUPABASE_PRIVATE_BUCKET'
    private = True


@deconstructible
class ProfilePictureStorage(FileSystemStorage):
    """Keep profile pictures private in Supabase, local in unconfigured dev."""

    @property
    def _remote(self):
        from django.conf import settings
        if not settings.SUPABASE_PRIVATE_STORAGE_CONFIGURED:
            if not settings.DEBUG:
                raise ImproperlyConfigured(
                    'Private Supabase Storage is required in production. Configure '
                    'the SUPABASE_* server-side credentials and private bucket.'
                )
            return None
        storage = getattr(self, '_profile_remote_storage', None)
        if storage is None:
            storage = SupabasePrivateStorage()
            self._profile_remote_storage = storage
        return storage

    def save(self, name, content, max_length=None):
        remote = self._remote
        return (remote.save(name, content, max_length=max_length) if remote
                else super().save(name, content, max_length=max_length))

    def open(self, name, mode='rb'):
        remote = self._remote
        return remote.open(name, mode) if remote else super().open(name, mode)

    def delete(self, name):
        remote = self._remote
        return remote.delete(name) if remote else super().delete(name)

    def exists(self, name):
        remote = self._remote
        return remote.exists(name) if remote else super().exists(name)

    def size(self, name):
        remote = self._remote
        return remote.size(name) if remote else super().size(name)

    def url(self, name):
        remote = self._remote
        return remote.url(name) if remote else super().url(name)

    def path(self, name):
        remote = self._remote
        return remote.path(name) if remote else super().path(name)
