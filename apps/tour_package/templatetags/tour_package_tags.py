from django import template

register = template.Library()


def _usable_image_urls(photo_rows):
    """Return URLs for saved image paths without remote existence probes."""
    urls = []
    for photo in photo_rows:
        name = getattr(photo, 'image', None)
        if not name:
            continue
        path = name.name if hasattr(name, 'name') else str(name)
        if not path:
            continue
        try:
            urls.append(name.url)
        except Exception:
            continue
    return urls


@register.filter
def photo_urls(photos_qs):
    """All usable image URLs for a tour package photo queryset."""
    if photos_qs is None:
        return []
    try:
        rows = list(photos_qs)
    except (TypeError, ValueError):
        return []
    return _usable_image_urls(rows)


@register.filter
def photo_cover(photos_qs, fallback=''):
    """First usable image URL (or fallback) for a tour package card."""
    urls = photo_urls(photos_qs) if photos_qs is not None else []
    return urls[0] if urls else fallback


@register.filter(name='lines')
def plan_lines(text):
    """Split a plan/inclusion text field into non-empty trimmed lines."""
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]
