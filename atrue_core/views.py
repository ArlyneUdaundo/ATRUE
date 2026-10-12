from django.http import JsonResponse

from atrue_core.context_processors import _location_tree_cached
from atrue_core.location_hierarchy import (
    country_dict,
    municipality_barangays,
    primary_country,
)
from locations.geonames_service import search_worldwide_places


def _requested_country(request):
    """The ``?country=`` value, validated against the GeoNames countries.

    Returns ``(country_dict_or_None, requested)``. ``requested`` is the raw
    non-empty value, so a caller can tell "asked for a country that does not
    exist" from "did not ask at all" and answer 400 instead of silently serving
    the platform's own country.
    """
    requested = (request.GET.get('country') or '').strip()
    if not requested:
        return None, ''
    return country_dict(requested), requested


def location_api(request):
    """JSON endpoint serving one country's Province -> Municipality tree.

    Consumed by the reusable hierarchical location picker (location-picker.js)
    so any page can render the same selector against live database data.

    ``GET /locations/api/?country=XX`` serves any country GeoNames has data for;
    without the parameter it serves the platform's own country. One country at a
    time is not an arbitrary limit: the worldwide data is roughly 35,000
    provinces, and returning all of them would be a payload no page could use.

    The tree deliberately carries barangay lists only for the municipalities that
    existing listings already use -- inlining all ~41,000 for the Philippines
    would add roughly a megabyte to every page. Callers fetch the rest on demand
    from ``location_barangays_api``.
    """
    country, requested = _requested_country(request)
    if requested and country is None:
        return JsonResponse(
            {'error': f'Unknown country: {requested}'}, status=400)
    return JsonResponse(_location_tree_cached(country['code'] if country else ''))


def location_search_api(request):
    """Search GeoNames places worldwide for autocomplete fields."""
    query = (request.GET.get('q') or '').strip()
    results = search_worldwide_places(query)
    return JsonResponse({'results': results})


def location_barangays_api(request):
    """JSON endpoint serving one municipality's full GeoNames barangay list.

    ``GET /locations/api/barangays/?province=<label>&municipality=<name>&country=<code>``

    ``province`` is the label the tree shows, so the collapsed "Metro Manila"
    resolves to the GeoNames districts behind it. ``country`` scopes the lookup and
    defaults to the platform's own country. Unknown values return an empty list
    with a 200 so a stale page degrades to free text instead of erroring.
    """
    province = (request.GET.get('province') or '').strip()
    municipality = (request.GET.get('municipality') or '').strip()
    country, requested = _requested_country(request)

    if requested and country is None:
        return JsonResponse(
            {'error': f'Unknown country: {requested}'}, status=400)

    barangays = municipality_barangays(province, municipality,
                                       country['code'] if country else None)
    # Echo back the country actually served, so a client that asked for the
    # default does not have to know which one that is.
    resolved = country or primary_country()

    return JsonResponse({
        'country': resolved['name'], 'country_code': resolved['code'],
        'province': province, 'municipality': municipality,
        'barangays': barangays, 'count': len(barangays),
    })
