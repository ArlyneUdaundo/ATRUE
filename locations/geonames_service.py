"""Lookups over the locally stored GeoNames reference data.

The platform resolves locations from its own database rather than calling the
GeoNames web API: the data is loaded once by ``manage.py sync_geonames``, so
lookups are fast, work offline and never depend on a third-party service or an
API credential.

That data is worldwide, so the functions here take an optional ``country`` and
default to the platform's own country (``settings.LOCATION_PRIMARY_COUNTRY``).
Without it a name like "Victoria" would match a city in every country at once.
"""

from django.conf import settings
from django.db.models import Q

from .models import Barangay, CityMunicipality, Country, Province, Region
from .names import normalize_place_name, strip_accents


def _scope(queryset, country=None, path='region__country'):
    """Narrow ``queryset`` to one country, by code or by name.

    ``path`` is the route from ``queryset``'s model to its ``Country``, which
    differs per level (``region__country``, ``province__region__country``, ...).
    Falls back to the configured primary country, and to no narrowing at all when
    there is no configured country and none was passed.
    """
    wanted = ((country or '').strip()
              or getattr(settings, 'LOCATION_PRIMARY_COUNTRY', '').strip())
    if not wanted:
        return queryset
    return queryset.filter(
        Q(**{f'{path}__code__iexact': wanted}) | Q(**{f'{path}__name__iexact': wanted})
    )


def is_populated():
    """True once ``sync_geonames`` has loaded the reference tables."""
    return Country.objects.exists()


def default_country():
    """The country the platform operates in, as a dict, or ``None`` if not loaded.

    Resolved from ``settings.LOCATION_PRIMARY_COUNTRY`` rather than by taking the
    first row, which with the worldwide data would be whichever country happens to
    sort first by name.
    """
    wanted = (getattr(settings, 'LOCATION_PRIMARY_COUNTRY', '') or '').strip()
    if not wanted:
        return None
    country = Country.objects.filter(code__iexact=wanted).first()
    if country is None:
        country = Country.objects.filter(name__iexact=wanted).first()
    if country is None:
        return None
    return {
        'geoname_id': country.geoname_id,
        'code': country.code,
        'name': country.name,
        'region_count': country.regions.count(),
    }


def hierarchy_stats():
    """Row counts per level."""
    return {
        'countries': Country.objects.count(),
        'regions': Region.objects.count(),
        'provinces': Province.objects.count(),
        'cities_municipalities': CityMunicipality.objects.count(),
        'barangays': Barangay.objects.count(),
    }


def _exact_or_like(query, *fields):
    return Q(**{f'{field}__iexact': query for field in fields})


def search_places(query, limit=10, country=None):
    """Search provinces, cities/municipalities and barangays by name.

    Returns a list of dicts sorted by level (province first, then
    city/municipality, then barangay) so a broad query still leads with the
    broadest match.
    """
    query = (query or '').strip()
    if not query:
        return []

    results = []

    provinces = _scope(Province.objects.all(), country).filter(
        _exact_or_like(query, 'name')
    ).select_related('region', 'region__country')[:limit]
    for province in provinces:
        results.append({
            'level': 'province',
            'geoname_id': province.geoname_id,
            'name': province.name,
            'province': province.name,
            'region': province.region.name,
            'country': province.region.country.name,
            'country_code': province.region.country.code,
        })

    cities = _scope(
        CityMunicipality.objects.filter(_exact_or_like(query, 'name')),
        country, 'province__region__country',
    ).select_related('province', 'province__region', 'province__region__country')[:limit]
    for city in cities:
        results.append({
            'level': 'city',
            'geoname_id': city.geoname_id,
            'name': city.name,
            'province': city.province.name,
            'region': city.province.region.name,
            'country': city.province.region.country.name,
            'country_code': city.province.region.country.code,
        })

    barangays = _scope(
        Barangay.objects.filter(_exact_or_like(query, 'name')),
        country, 'city_municipality__province__region__country',
    ).select_related(
        'city_municipality', 'city_municipality__province',
        'city_municipality__province__region', 'city_municipality__province__region__country',
    )[:limit]
    for barangay in barangays:
        province = barangay.city_municipality.province
        results.append({
            'level': 'barangay',
            'geoname_id': barangay.geoname_id,
            'name': barangay.name,
            'municipality': barangay.city_municipality.name,
            'province': province.name,
            'region': province.region.name,
            'country': province.region.country.name,
            'country_code': province.region.country.code,
        })

    return results[:limit]


def search_worldwide_places(query, limit=20):
    """Search GeoNames countries, provinces, cities and Philippine barangays.

    Unlike ``search_places``, this lookup is deliberately not scoped to the
    configured primary country. It is used by autocomplete fields where a
    traveler may search for a place anywhere in the world.
    """
    query = (query or '').strip()
    if len(query) < 2:
        return []

    limit = max(1, min(int(limit), 50))
    ascii_query = strip_accents(query)
    name_filter = (
        Q(name__icontains=query) | Q(asciiname__icontains=ascii_query)
    )
    results = []

    countries = Country.objects.filter(name_filter)[:limit]
    for country in countries:
        results.append({
            'level': 'country',
            'geoname_id': country.geoname_id,
            'name': country.name,
            'sub': 'Country',
            'country': country.name,
            'country_code': country.code,
            'province': '',
            'municipality': '',
            'barangay': '',
        })

    provinces = Province.objects.filter(name_filter).select_related(
        'region', 'region__country',
    )[:limit]
    for province in provinces:
        country = province.region.country
        results.append({
            'level': 'province',
            'geoname_id': province.geoname_id,
            'name': province.name,
            'sub': f'{province.region.name}, {country.name}',
            'country': country.name,
            'country_code': country.code,
            'province': province.name,
            'municipality': '',
            'barangay': '',
        })

    cities = CityMunicipality.objects.filter(name_filter).select_related(
        'province', 'province__region', 'province__region__country',
    )[:limit]
    for city in cities:
        province = city.province
        country = province.region.country
        results.append({
            'level': 'city',
            'geoname_id': city.geoname_id,
            'name': city.name,
            'sub': f'{province.name}, {country.name}',
            'country': country.name,
            'country_code': country.code,
            'province': province.name,
            'municipality': city.name,
            'barangay': '',
        })

    barangays = Barangay.objects.filter(name_filter).select_related(
        'city_municipality__province__region__country',
        'city_municipality__province',
        'city_municipality',
    )[:limit]
    for barangay in barangays:
        city = barangay.city_municipality
        province = city.province
        country = province.region.country
        results.append({
            'level': 'barangay',
            'geoname_id': barangay.geoname_id,
            'name': barangay.name,
            'sub': f'{city.name}, {province.name}, {country.name}',
            'country': country.name,
            'country_code': country.code,
            'province': province.name,
            'municipality': city.name,
            'barangay': barangay.name,
        })

    query_key = normalize_place_name(query)
    level_rank = {'city': 0, 'province': 1, 'country': 2, 'barangay': 3}
    results.sort(key=lambda result: (
        0 if normalize_place_name(result['name']) == query_key else 1,
        level_rank[result['level']],
        result['name'].casefold(),
    ))
    return results[:limit]


def resolve_location(province_name, municipality_name='', barangay_name='', country=None):
    """Resolve a free-text province/municipality/barangay triple to GeoNames.

    Each level is resolved within its parent, so a municipality that does not
    belong to the given province is never accepted. Unmatched levels come back
    as empty strings and the deeper levels are then left unresolved.
    """
    empty = {
        'country': '', 'country_code': '', 'region': '', 'region_geoname_id': '',
        'province': '', 'province_geoname_id': '',
        'municipality': '', 'municipality_geoname_id': '',
        'barangay': '', 'barangay_geoname_id': '',
    }

    province = _match(
        _scope(Province.objects.select_related('region', 'region__country'), country),
        province_name, 'name',
    )
    if province is None:
        return empty

    empty['country'] = province.region.country.name
    empty['country_code'] = province.region.country.code
    empty['region'] = province.region.name
    empty['region_geoname_id'] = province.region.geoname_id
    empty['province'] = province.name
    empty['province_geoname_id'] = province.geoname_id

    city = _match(province.municipalities.all(), municipality_name, 'name')
    if city is None:
        return empty

    empty['municipality'] = city.name
    empty['municipality_geoname_id'] = city.geoname_id

    barangay = _match(city.barangays.all(), barangay_name, 'name')
    if barangay is not None:
        empty['barangay'] = barangay.name
        empty['barangay_geoname_id'] = barangay.geoname_id

    return empty


def _match(queryset, value, field):
    """Find one row whose name matches ``value``, tolerating accents and case.

    The full queryset is scanned rather than ``.only()`` because callers pass
    ``select_related`` querysets, and deferring a field that is also traversed
    raises ``FieldError``. The candidate sets are small (one province's
    municipalities, or one city's barangays).
    """
    value = (value or '').strip()
    if not value:
        return None
    exact = queryset.filter(**{f'{field}__iexact': value}).first()
    if exact is not None:
        return exact

    key = normalize_place_name(value)
    if not key:
        return None
    for row in queryset:
        if normalize_place_name(getattr(row, field)) == key:
            return row
    return None
