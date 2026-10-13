from django import template

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
            if name.storage.exists(path):
                urls.append(name.url)
        except Exception:
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
    usable = []
    for photo in rows:
        image = getattr(photo, 'image', None)
        try:
            if image and image.name and image.storage.exists(image.name):
                usable.append(photo)
        except Exception:
            continue
    return usable


@register.filter
def photo_cover(photos_qs, fallback=''):
    """First usable image URL (or fallback) for a hotel card cover."""
    urls = _usable_image_urls(photos_qs) if photos_qs is not None else []
    return urls[0] if urls else fallback


@register.filter
def photo_urls(photos_qs):
    """All usable image URLs for a photo queryset (in DB order)."""
    return _usable_image_urls(photos_qs) if photos_qs is not None else []
