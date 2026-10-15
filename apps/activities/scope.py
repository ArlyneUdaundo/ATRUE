from django.db.models import Q
from atrue_core.establishment_scope import (
    assigned_establishment_for_write,
)
from functools import wraps

from django.core.exceptions import PermissionDenied

from accounts.roles import FULL_ACCESS_TYPES, effective_role_keys
from .models import Activity


ESTABLISHMENT_TYPE = 'ACTIVITY'


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


def _active_assignment(request):
    assignment = getattr(request, 'active_simulation_assignment', None)
    if assignment is not None:
        return assignment
    from simulation.models import SimulationRoleAssignment
    from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

    assignment_id = request.session.get(TASK_ASSIGNMENT_SESSION_KEY)
    if not assignment_id or not request.user.is_authenticated:
        return None
    assignment = (
        SimulationRoleAssignment.objects.filter(
            pk=assignment_id,
            student=request.user,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        ).select_related('establishment').first()
    )
    if assignment is not None:
        request.active_simulation_assignment = assignment
    return assignment


def assigned_activity_ids(request):
    """The ``Activity`` pks this request's user may act on.

    ``None`` means no scope (platform-wide operator); an empty set is the real
    answer "no active assignment points at an activity".
    """
    if not request.user.is_authenticated:
        return set()
    if is_activity_platform_user(request.user):
        return None
    # Activity owners are account-level operators too; they may create the
    # first activity before an establishment assignment exists.
    if 'ACTIVITY_OWNER' in effective_role_keys(request.user):
        return None
    assignment = _active_assignment(request)
    roles = getattr(request, 'activity_authorized_roles', None)
    if roles is None:
        from accounts.roles import effective_role_keys
        roles = effective_role_keys(request.user)
    if assignment is not None:
        if assignment.role == 'ACTIVITY_OWNER':
            return None
        if (assignment.role not in roles or not assignment.establishment_id
                or assignment.establishment.type != ESTABLISHMENT_TYPE):
            return set()
        return _entity_ids({assignment.establishment_id})
    from simulation.models import SimulationRoleAssignment
    establishments = set(
        SimulationRoleAssignment.objects.filter(
            student=request.user,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            role__in=roles,
            establishment__type=ESTABLISHMENT_TYPE,
        ).values_list('establishment_id', flat=True)
    )
    return _entity_ids(establishments)


def assigned_activity_ids_for_roles(request, roles):
    """Return only activities covered by assignments for the requested role(s)."""
    if is_activity_platform_user(request.user):
        return None
    original = getattr(request, 'activity_authorized_roles', None)
    request.activity_authorized_roles = frozenset(roles)
    try:
        return assigned_activity_ids(request)
    finally:
        if original is None:
            delattr(request, 'activity_authorized_roles')
        else:
            request.activity_authorized_roles = original


def activity_roles_for_request(request):
    """Return activity roles in force, respecting an explicitly selected task."""
    user = request.user
    roles = effective_role_keys(user)
    assignment = _active_assignment(request)
    if assignment is not None:
        from accounts.roles import ROLE_KEY_ALIASES
        roles = {assignment.role, ROLE_KEY_ALIASES.get(assignment.role, assignment.role),
                 user.account_type}
    return roles


def is_activity_platform_user(user):
    """Platform operators retain their existing unrestricted activity access."""
    return bool(
        user.is_authenticated
        and (user.is_staff or effective_role_keys(user).intersection(FULL_ACCESS_TYPES))
    )


def activity_role_required(*roles):
    """Require an activity-specific role (or an unrestricted platform role)."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not is_activity_platform_user(request.user):
                allowed_roles = activity_roles_for_request(request).intersection(roles)
                if not allowed_roles:
                    raise PermissionDenied('This activity operation is not allowed for your role.')
                request.activity_authorized_roles = frozenset(allowed_roles)
            else:
                request.activity_authorized_roles = None
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def activity_guest_booking_required(view_func):
    """Keep operational task holders out of the customer booking workflow."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        roles = activity_roles_for_request(request)
        staff_roles = {
            'ACTIVITY_MANAGER',
            'ACTIVITY_RESERVATION_OFFICER',
            'ACTIVITY_FRONT_DESK_OFFICER',
            'ACTIVITY_OPERATOR',
        }
        if roles.intersection(staff_roles) and 'ACTIVITY_GUEST' not in roles:
            raise PermissionDenied('Activity staff must use their assigned operations workflow.')
        return view_func(request, *args, **kwargs)
    return wrapped


def scope_activities(request, queryset):
    allowed = assigned_activity_ids(request)
    if allowed is None:
        return queryset
    if not allowed:
        return queryset.none()
    return queryset.filter(pk__in=allowed)


def scope_providers(request, queryset):
    allowed = assigned_activity_ids(request)
    if allowed is None:
        return queryset
    return queryset.filter(activities__pk__in=allowed).distinct()


def scope_bookings(request, queryset):
    allowed = assigned_activity_ids(request)
    if allowed is None:
        return queryset
    return queryset.filter(activity_id__in=allowed)


def assigned_operator_for_write(request):
    return assigned_establishment_for_write(request, ESTABLISHMENT_TYPE)
