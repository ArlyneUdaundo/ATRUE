import json
import os

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def usable_urls(photos_qs):
    """Return only image URLs whose media file actually exists on disk.

    Use on any HotelPhoto / RoomPhoto queryset (e.g. hotel.photos.all) so that
    a missing/empty file never renders a blank <img>. Mirrors the
    _usable_images() logic used by the search catalog.
    """
    out = []
    if photos_qs is None:
        return out
    try:
        rows = list(photos_qs)
    except (TypeError, ValueError):
        return out
    for p in rows:
        f = getattr(getattr(p, "image", None), "name", None) or ""
        full = os.path.join(settings.MEDIA_ROOT, f)
        if os.path.isfile(full) and os.path.getsize(full) > 0:
            out.append(settings.MEDIA_URL + f)
    return out


@register.filter
def usable_json(photos_qs):
    """usable_urls() result serialized as a JSON array (for data-images='...')."""
    return mark_safe(json.dumps(usable_urls(photos_qs)))
