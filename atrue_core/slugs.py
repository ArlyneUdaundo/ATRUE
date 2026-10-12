"""URL-friendly slugs derived from an item's name / identifier.

Every listing detail page uses a clean, human-readable slug like
``/hotels/dragon-home-inn/`` instead of exposing internal primary keys or
per-tab context UUIDs in the browser URL.

Slugs are computed deterministically from the item's ``name`` (or for flights
from the ``flight_number``), so they never need to be stored on the model and
there is no migration to run. Legacy ``/<id>/`` links keep working because the
detail views fall back to a numeric lookup.
"""

from django.http import Http404

from django.utils.text import slugify


def make_slug(value, fallback="item"):
    """Lower-case, hyphen-separated, URL-safe slug for ``value``."""
    slug = slugify(value or "")
    return slug or fallback


def matches_slug(instance, slug):
    """True when ``slug`` is the instance's canonical URL slug."""
    return getattr(instance, "slug", None) == (slug or "")


class SlugByNameMixin:
    """Attach a deterministic ``slug`` property built from ``name``."""

    @property
    def slug(self):
        return make_slug(getattr(self, "name", ""))


def get_by_slug(queryset, key):
    """Resolve a URL slug back to a model instance (or None).

    A numeric key is treated as a legacy primary-key fallback so old
    ``/<id>/`` bookmarks and any remaining internal links keep working.

    The canonical slug is always tried first: an item whose name slugifies to an
    all-digit string (a flight numbered "098", a hotel called "2024") would
    otherwise be unreachable, because the numeric fallback would look for a
    primary key 98 and 404 on a row that plainly exists.
    """
    key = (key or "").strip()
    for obj in queryset:
        if matches_slug(obj, key):
            return obj
    if key.isdigit():
        return queryset.filter(pk=int(key)).first()
    return None


def get_object_by_slug_or_404(queryset, key):
    """``get_by_slug`` with Django's usual 404-on-miss behaviour."""
    obj = get_by_slug(queryset, key)
    if obj is None:
        raise Http404("No matching object found for this URL.")
    return obj