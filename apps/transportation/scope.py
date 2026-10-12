from atrue_core.establishment_scope import (
    assigned_establishment_for_write,
    assigned_establishment_pks,
)


ESTABLISHMENT_TYPE = 'TRANSPORTATION'


def _entity_ids(allowed):
    """Map ``Establishment`` pks onto the agency rows they wrap, or pass a
    full-access user through untouched (``allowed`` is None then).
    """
    if allowed is None:
        return None
    from establishments.models import Establishment

    return set(
        Establishment.objects.filter(pk__in=allowed)
        .values_list('entity_id', flat=True)
    )


def assigned_agency_ids(request):
    """The ``Agency`` pks this request's user may act on.

    ``None`` means no scope (platform-wide operator); an empty set is the real
    answer "no active assignment points at an agency".
    """
    return _entity_ids(assigned_establishment_pks(request, ESTABLISHMENT_TYPE))


def scope_agencies(request, queryset):
    allowed = assigned_agency_ids(request)
    if allowed is None:
        return queryset
    return queryset.filter(pk__in=allowed)


def scope_bookings(request, queryset):
    allowed = assigned_agency_ids(request)
    if allowed is None:
        return queryset
    return queryset.filter(vehicle__agency_id__in=allowed)


def assigned_operator_for_write(request):
    return assigned_establishment_for_write(request, ESTABLISHMENT_TYPE)