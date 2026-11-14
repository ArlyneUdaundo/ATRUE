from atrue_core.establishment_scope import (
    assigned_establishment_for_write,
    assigned_establishment_pks,
)
from accounts.roles import FULL_ACCESS_TYPES, effective_role_keys, owner_role_keys


ESTABLISHMENT_TYPE = 'TOUR_PACKAGE'

PACKAGE_MANAGER_ROLES = frozenset({
    'TOUR_PACKAGE_MANAGER', 'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER',
    'TRAVEL_AGENCY_OWNER', 'TOUR_OPERATOR_MANAGER', 'TOUR_MANAGER',
    'TRAVEL_AGENCY_MANAGER',
})
RESERVATION_ROLES = frozenset({
    'TOUR_PACKAGE_RESERVATION_OFFICER', 'TOUR_RESERVATION_AGENT',
    'TOUR_COORDINATOR', 'TRAVEL_AGENCY_RESERVATION_AGENT',
    'TRAVEL_AGENCY_RESERVATION_OFFICER',
})
FRONTDESK_ROLES = frozenset({
    'TOUR_PACKAGE_FRONT_DESK_OFFICER', 'TOUR_PACKAGE_OPERATOR',
    'TOUR_FRONT_DESK', 'TOUR_GUIDE', 'TRAVEL_AGENCY_FRONT_DESK',
})
GUEST_ROLES = frozenset({'TOUR_GUEST', 'CUSTOMER_TOUR'})

SIMULATION_WIDE_PACKAGE_ROLES = frozenset({
    'TOUR_OPERATOR_MANAGER', 'TOUR_MANAGER', 'TRAVEL_AGENCY_MANAGER',
    'TOUR_RESERVATION_AGENT', 'TOUR_COORDINATOR',
    'TRAVEL_AGENCY_RESERVATION_AGENT', 'TRAVEL_AGENCY_RESERVATION_OFFICER',
    'TOUR_FRONT_DESK', 'TOUR_GUIDE', 'TRAVEL_AGENCY_FRONT_DESK',
})


def is_platform_operator(user):
    return bool(user.is_authenticated and (
        user.is_staff or set(effective_role_keys(user)) & FULL_ACCESS_TYPES))


def has_package_role(request, roles):
    if is_platform_operator(request.user):
        return True
    if set(effective_role_keys(request.user)).intersection(roles):
        return True
    if owner_role_keys(request.user).intersection(
            {'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER', 'TRAVEL_AGENCY_OWNER'}):
        return True
    allowed = package_ids_for_roles(request, roles)
    return allowed is None or bool(allowed)


def package_ids_for_roles(request, roles):
    if not request.user.is_authenticated:
        return None
    if is_platform_operator(request.user):
        return None
    active = getattr(request, 'active_simulation_assignment', None)
    if active is None:
        assignment_id = request.session.get('active_simulation_task_assignment')
        if assignment_id:
            from simulation.models import SimulationRoleAssignment

            active = SimulationRoleAssignment.objects.filter(
                pk=assignment_id,
                student=request.user,
                status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            ).select_related('establishment').first()
    if active is not None:
        if active.role in {'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER',
                           'TRAVEL_AGENCY_OWNER'}:
            return None
        if active.role in SIMULATION_WIDE_PACKAGE_ROLES and active.role in roles:
            return None
        establishment = active.establishment
        if (establishment and establishment.type == ESTABLISHMENT_TYPE
                and active.role in roles):
            return {establishment.entity_id}
        return set()
    from simulation.models import SimulationRoleAssignment
    from establishments.models import Establishment
    if owner_role_keys(request.user).intersection(
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
    allowed = package_ids_for_roles(request, roles)
    return allowed is None or package_id in allowed


def may_manage_package(request, package_id=None):
    return (has_package_role(request, PACKAGE_MANAGER_ROLES) if package_id is None
            else package_has_role(request, package_id, PACKAGE_MANAGER_ROLES))


def may_review_booking(request, package_id=None):
    return (has_package_role(request, RESERVATION_ROLES) if package_id is None
            else package_has_role(request, package_id, RESERVATION_ROLES))


def may_process_frontdesk(request, package_id=None):
    return (has_package_role(request, FRONTDESK_ROLES) if package_id is None
            else package_has_role(request, package_id, FRONTDESK_ROLES))


def _is_unassigned_public_booker(request):
    user = request.user
    if (not user.is_authenticated
            or user.account_type not in {'STUDENT', 'CUSTOMER_TOUR'}
            or not user.is_bookable):
        return False

    active = getattr(request, 'active_simulation_assignment', None)
    if active is None:
        assignment_id = request.session.get('active_simulation_task_assignment')
        if assignment_id:
            from simulation.models import SimulationRoleAssignment

            active = SimulationRoleAssignment.objects.filter(
                pk=assignment_id,
                student=user,
                status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            ).first()
    if active is not None:
        return False

    from simulation.models import SimulationRoleAssignment
    return not SimulationRoleAssignment.objects.filter(
        student=user,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).exists()


def _is_unscoped_assigned_package_guest(request):
    """Whether the active guest assignment intentionally has no package scope.

    Guest establishments are optional in the role assignment form. A student
    assigned as a Tour Guest without a specific package should be able to browse
    the public package directory, while guests assigned to one package remain
    limited to that package.
    """
    user = request.user
    if not user.is_authenticated or not user.is_bookable:
        return False

    active = getattr(request, 'active_simulation_assignment', None)
    if active is None:
        assignment_id = request.session.get('active_simulation_task_assignment')
        if assignment_id:
            from simulation.models import SimulationRoleAssignment

            active = SimulationRoleAssignment.objects.filter(
                pk=assignment_id,
                student=user,
                status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            ).first()

    return bool(
        active is not None
        and active.status == 'ACTIVE'
        and active.role in GUEST_ROLES
        and active.establishment_id is None
    )


def scope_bookable_packages(request, queryset):
    allowed = package_ids_for_roles(request, GUEST_ROLES)
    if allowed is None:
        return queryset
    if allowed:
        return queryset.filter(pk__in=allowed)
    if (_is_unassigned_public_booker(request)
            or _is_unscoped_assigned_package_guest(request)):
        return queryset
    return queryset.none()


def scope_directory_packages(request, queryset):
    allowed = assigned_package_ids(request)
    if allowed is None:
        return queryset
    if allowed:
        return queryset.filter(pk__in=allowed)
    if (_is_unassigned_public_booker(request)
            or _is_unscoped_assigned_package_guest(request)):
        return queryset
    return queryset.none()


def scope_customer_bookings(request, queryset, roles):
    scoped = scope_bookings(request, queryset, roles)
    if _is_unassigned_public_booker(request):
        from django.db.models import Q

        return queryset.filter(
            Q(customer=request.user) | Q(pk__in=scoped.values('pk')))
    return scoped


def may_book_package(request, package_id=None):
    allowed = package_ids_for_roles(request, GUEST_ROLES)
    if allowed is None:
        return True
    if package_id is None:
        return (bool(allowed) or _is_unassigned_public_booker(request)
                or _is_unscoped_assigned_package_guest(request))
    return package_id in allowed or (
        not allowed and (_is_unassigned_public_booker(request)
                         or _is_unscoped_assigned_package_guest(request)))


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
    active = getattr(request, 'active_simulation_assignment', None)
    if active and active.role in (
            SIMULATION_WIDE_PACKAGE_ROLES & PACKAGE_MANAGER_ROLES):
        return None
    return assigned_establishment_for_write(request, ESTABLISHMENT_TYPE)
