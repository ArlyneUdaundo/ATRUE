DOMESTIC = 'DOMESTIC'
INTERNATIONAL = 'INTERNATIONAL'
VALID_ROUTE_SCOPES = (DOMESTIC, INTERNATIONAL)


def normalize_route_scope(value):
    value = (value or '').strip().upper()
    return value if value in VALID_ROUTE_SCOPES else ''


def _country_code(airport):
    return (getattr(airport, 'country_code', '') or '').strip().upper()


def _country_name(airport):
    return ' '.join((getattr(airport, 'country', '') or '').split()).casefold()


def route_scope_for_airports(airports):
    airports = list(airports)
    if not airports or any(airport is None for airport in airports):
        return None

    codes = [_country_code(airport) for airport in airports]
    if all(codes):
        return DOMESTIC if len(set(codes)) == 1 else INTERNATIONAL

    names = [_country_name(airport) for airport in airports]
    if all(names):
        return DOMESTIC if len(set(names)) == 1 else INTERNATIONAL

    return None


def route_scope_for_legs(legs):
    airports = []
    for leg in legs or []:
        if isinstance(leg, dict):
            origin = leg.get('origin_airport')
            destination = leg.get('destination_airport')
        else:
            origin = getattr(leg, 'origin_airport', None)
            destination = getattr(leg, 'destination_airport', None)
        if origin is None or destination is None:
            return None
        airports.extend((origin, destination))
    return route_scope_for_airports(airports)
