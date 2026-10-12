from django import template
from django.conf import settings

import os

register = template.Library()


def _usable_image_urls(photo_rows):
    """Return only URLs whose underlying media file actually exists on disk.

    This mirrors atrue_core.search_catalog._usable_images so that hotel image
    areas never render a broken/empty <img> when a database record references
    a file that is missing (e.g. demo_hotel_01.jpg)."""
    urls = []
    for photo in photo_rows:
        name = getattr(photo, 'image', None)
        if not name:
            continue
        path = name.name if hasattr(name, 'name') else str(name)
        if not path:
            continue
        try:
            full = os.path.join(settings.MEDIA_ROOT, path)
            if os.path.isfile(full) and os.path.getsize(full) > 0:
                urls.append(settings.MEDIA_URL + path)
        except OSError:
            continue
    return urls


@register.filter
def existing_photos(photos_qs):
    """Filter a photos queryset to only records whose image exists on disk."""
    if photos_qs is None:
        return []
    try:
        rows = list(photos_qs)
    except (TypeError, ValueError):
        return []
    return [p for p in rows if any(getattr(p, 'image', None).name == u.replace(settings.MEDIA_URL, '')
                                       for u in _usable_image_urls([p]))]


@register.filter
def photo_cover(photos_qs, fallback=''):
    """First usable image URL (or fallback) for a hotel card cover."""
    urls = _usable_image_urls(photos_qs) if photos_qs is not None else []
    return urls[0] if urls else fallback


@register.filter
def photo_urls(photos_qs):
    """All usable image URLs for a photo queryset (in DB order)."""
    return _usable_image_urls(photos_qs) if photos_qs is not None else []
