import json
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.hotels.templatetags.hotel_photos import (
    first_usable_url,
    stored_image_urls,
)
from atrue_core.search_catalog import (
    _cached_storage_exists,
    _photo_urls,
    _usable_images,
)


class SearchCatalogImageTests(SimpleTestCase):
    def setUp(self):
        _cached_storage_exists.cache_clear()
        self.storage = Mock()
        self.storage.exists.side_effect = lambda path: path != 'missing.jpg'
        self.storage.url.side_effect = lambda path: f'https://images.example/{path}'

    def tearDown(self):
        _cached_storage_exists.cache_clear()

    def test_count_and_gallery_include_each_existing_path_once(self):
        photos = [
            SimpleNamespace(image=SimpleNamespace(
                storage=self.storage, name=f'photo-{index}.jpg'))
            for index in range(5)
        ]
        # Duplicate database rows must not inflate the displayed count.
        photos.append(SimpleNamespace(image=SimpleNamespace(
            storage=self.storage, name='photo-2.jpg')))
        photos.append(SimpleNamespace(image=SimpleNamespace(
            storage=self.storage, name='missing.jpg')))

        urls = _photo_urls(photos)
        gallery_json = json.dumps(urls)

        self.assertEqual(len(urls), 5)
        self.assertEqual(len(json.loads(gallery_json)), 5)
        self.assertEqual(len(set(urls)), 5)
        self.assertNotIn('missing.jpg', gallery_json)

    def test_three_available_photos_produce_three_gallery_items(self):
        photos = [
            SimpleNamespace(image=SimpleNamespace(
                storage=self.storage, name=f'photo-{index}.jpg'))
            for index in range(3)
        ]

        self.assertEqual(len(_photo_urls(photos)), 3)

    def test_homepage_image_filter_omits_missing_storage_objects(self):
        photos = [
            SimpleNamespace(image=SimpleNamespace(
                storage=self.storage, name='photo-1.jpg')),
            SimpleNamespace(image=SimpleNamespace(
                storage=self.storage, name='missing.jpg')),
        ]

        self.assertEqual(
            stored_image_urls(photos),
            ['https://images.example/photo-1.jpg'],
        )

    def test_homepage_cover_uses_first_existing_photo_and_stops_there(self):
        photos = [
            SimpleNamespace(image=SimpleNamespace(
                storage=self.storage, name='missing.jpg')),
            SimpleNamespace(image=SimpleNamespace(
                storage=self.storage, name='cover.jpg')),
            SimpleNamespace(image=SimpleNamespace(
                storage=self.storage, name='gallery-2.jpg')),
        ]

        self.assertEqual(
            first_usable_url(photos), 'https://images.example/cover.jpg')
        self.assertEqual(self.storage.exists.call_count, 2)

    def test_storage_existence_is_cached_within_the_cache_period(self):
        _usable_images([
            (self.storage, 'cover.jpg'),
            (self.storage, 'cover.jpg'),
        ])
        _usable_images([(self.storage, 'cover.jpg')])

        self.storage.exists.assert_called_once_with('cover.jpg')

    def test_storage_failure_skips_only_the_unavailable_image(self):
        self.storage.exists.side_effect = lambda path: (
            (_ for _ in ()).throw(OSError('storage unavailable'))
            if path == 'broken.jpg' else True
        )

        urls = _usable_images([
            (self.storage, 'broken.jpg'),
            (self.storage, 'good.jpg'),
        ])

        self.assertEqual(urls, ['https://images.example/good.jpg'])

