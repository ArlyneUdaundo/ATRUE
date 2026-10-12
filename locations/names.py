"""Name normalisation for GeoNames place names.

Deliberately free of Django imports so the standalone seed builder
(``locations/data/build_geonames_seed.py``) and the runtime app share one
implementation and can never drift apart.

Two different jobs live here:

``clean_name``
    Tidies a *display* name by dropping the noise prefixes GeoNames carries on
    administrative features ("Province of Isabela" -> "Isabela").

``normalize_place_name``
    Produces a *match key* for de-duplicating rows and for tolerant lookups. It
    removes accents, punctuation and case, but deliberately keeps the words
    "city" and "municipality" — stripping them would collapse genuinely distinct
    places such as the province of Cotabato and the independent city of Cotabato
    City.

Note that ``atrue_core.location_hierarchy.normalize`` looks similar but is *not*
a duplicate: that one deliberately drops "city"/"municipality" because it is a
fuzzy matcher for merging free-text values typed by staff onto GeoNames names
(so a saved "Dagupan" lands on "Dagupan City"). Exact resolution and fuzzy
merging want opposite behaviour here, so the two are kept separate on purpose.
"""

import re
import unicodedata

#: Prefixes GeoNames puts on administrative feature names.
NOISE_PREFIXES = (
    re.compile(r'^province\s+of\s+', re.IGNORECASE),
    re.compile(r'^municipality\s+of\s+', re.IGNORECASE),
    re.compile(r'^city\s+of\s+', re.IGNORECASE),
)


def strip_accents(value):
    """Replace accented characters with their ASCII base letters."""
    decomposed = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def clean_name(value):
    """Display name without the ``Province of``/``City of``/``Municipality of`` prefix."""
    name = ' '.join(str(value or '').split())
    for pattern in NOISE_PREFIXES:
        name = pattern.sub('', name)
    return name.strip()


def normalize_place_name(value):
    """Case-, accent- and punctuation-insensitive key for a place name.

    The words "city" and "municipality" are preserved so that a province and a
    same-named independent city stay distinguishable.
    """
    text = strip_accents(value).lower()
    text = text.replace('.', ' ').replace("'", ' ').replace('-', ' ')
    return ''.join(ch for ch in ' '.join(text.split()) if ch.isalnum() or ch == ' ')
