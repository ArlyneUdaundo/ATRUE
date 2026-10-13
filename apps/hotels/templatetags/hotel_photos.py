import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def usable_urls(photos_qs):
    """Return only image URLs whose media file actually exists on disk.

    Use on any HotelPhoto / RoomPhoto queryset (e.g. hotel.photos.all) so that
    a missing/empty file never renders a blank <img>. Mirrors the
    _usable_images() logic used by the search catalog.
    """
    if photos_qs is None:
        return []
    try:
        rows = list(photos_qs)
    except (TypeError, ValueError):
        return []
    # Reuse the catalog's short-lived, bounded storage existence cache. This
    # keeps homepage cards accurate without issuing one remote HEAD per render.
    from atrue_core.search_catalog import _usable_images

    return _usable_images([
        (image.storage, image.name)
        for photo in rows
        if (image := getattr(photo, 'image', None)) and image.name
    ])


@register.filter
def stored_image_urls(photos_qs):
    """Return verified stored URLs, using cached existence probes."""
    return usable_urls(photos_qs)


@register.filter
def first_usable_url(photos_qs):
    """Get the first valid cover without probing every gallery image."""
    if photos_qs is None:
        return ''
    try:
        rows = list(photos_qs)
    except (TypeError, ValueError):
        return ''
    from atrue_core.search_catalog import _usable_images

    for photo in rows:
        image = getattr(photo, 'image', None)
        if not image or not image.name:
            continue
        urls = _usable_images([(image.storage, image.name)])
        if urls:
            return urls[0]
    return ''


@register.filter
def usable_json(photos_qs):
    """usable_urls() result serialized as a JSON array (for data-images='...')."""
    return mark_safe(json.dumps(usable_urls(photos_qs)))
