from atrue_core.establishment_scope import (
    assigned_establishment_for_write,
    assigned_establishment_pks,
)
from accounts.roles import FULL_ACCESS_TYPES, effective_role_keys


ESTABLISHMENT_TYPE = 'TOUR_PACKAGE'

PACKAGE_MANAGER_ROLES = frozenset({
    'TOUR_PACKAGE_MANAGER', 'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER',
    'TRAVEL_AGENCY_OWNER',
})
RESERVATION_ROLES = frozenset({
    'TOUR_PACKAGE_RESERVATION_OFFICER',
})
FRONTDESK_ROLES = frozenset({
    'TOUR_PACKAGE_FRONT_DESK_OFFICER', 'TOUR_PACKAGE_OPERATOR',
})
GUEST_ROLES = frozenset({'TOUR_GUEST', 'CUSTOMER_TOUR'})


def is_platform_operator(user):
    return bool(user.is_authenticated and (
        user.is_staff or set(effective_role_keys(user)) & FULL_ACCESS_TYPES))


def has_package_role(request, roles):
    if is_platform_operator(request.user):
        return True
    if set(effective_role_keys(request.user)).intersection(roles):
        return True
    if set(effective_role_keys(request.user)).intersection(
            {'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER', 'TRAVEL_AGENCY_OWNER'}):
        return True
    return bool(package_ids_for_roles(request, roles))


def package_ids_for_roles(request, roles):
    if not request.user.is_authenticated:
        return None
    if is_platform_operator(request.user):
        return None
    active = getattr(request, 'active_simulation_assignment', None)
    if active is not None:
        if active.role in {'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER',
                           'TRAVEL_AGENCY_OWNER'}:
            return None
        establishment = active.establishment
        if (establishment and establishment.type == ESTABLISHMENT_TYPE
                and active.role in roles):
            return {establishment.entity_id}
        return set()
    from simulation.models import SimulationRoleAssignment
    from establishments.models import Establishment
    if set(effective_role_keys(request.user)).intersection(
            {'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER', 'TRAVEL_AGENCY_OWNER'}):
        return None
    return set(Establishment.objects.filter(
        simulation_assignments__student=request.user,
        simulation_assignments__status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        simulation_assignments__role__in=roles,
        type=ESTABLISHMENT_TYPE,
    ).values_list('entity_id', flat=True))


def package_has_role(request, package_id, roles):
    if is_platform_operator(request.user):
        return True
    return package_id in (package_ids_for_roles(request, roles) or set())


def may_manage_package(request, package_id=None):
    return (has_package_role(request, PACKAGE_MANAGER_ROLES) if package_id is None
            else package_has_role(request, package_id, PACKAGE_MANAGER_ROLES))


def may_review_booking(request, package_id=None):
    return (has_package_role(request, RESERVATION_ROLES) if package_id is None
            else package_has_role(request, package_id, RESERVATION_ROLES))


def may_process_frontdesk(request, package_id=None):
    return (has_package_role(request, FRONTDESK_ROLES) if package_id is None
            else package_has_role(request, package_id, FRONTDESK_ROLES))


def may_book_package(request, package_id=None):
    return (has_package_role(request, GUEST_ROLES) if package_id is None
            else package_has_role(request, package_id, GUEST_ROLES))


def _entity_ids(allowed):
    """Map ``Establishment`` pks onto the catalogue rows they wrap, or pass a
    full-access user through untouched (``allowed`` is None then).
    """
    if allowed is None:
        return None
    from establishments.models import Establishment

    return set(
        Establishment.objects.filter(pk__in=allowed)
        .values_list('entity_id', flat=True)
    )


def assigned_package_ids(request):
    """The ``TourPackage`` pks this request's user may act on.

    ``None`` means no scope (platform-wide operator); an empty set is the real
    answer "no active assignment points at a tour package".
    """
    return _entity_ids(assigned_establishment_pks(request, ESTABLISHMENT_TYPE))


def scope_packages(request, queryset, roles=None):
    if not request.user.is_authenticated:
        return queryset
    allowed = assigned_package_ids(request) if roles is None else package_ids_for_roles(request, roles)
    if allowed is None:
        return queryset
    return queryset.filter(pk__in=allowed)


def scope_bookings(request, queryset, roles=None):
    if not request.user.is_authenticated:
        return queryset
    allowed = assigned_package_ids(request) if roles is None else package_ids_for_roles(request, roles)
    if allowed is None:
        return queryset
    return queryset.filter(package_id__in=allowed)


def assigned_operator_for_write(request):
    return assigned_establishment_for_write(request, ESTABLISHMENT_TYPE)
