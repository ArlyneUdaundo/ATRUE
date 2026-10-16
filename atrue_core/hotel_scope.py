"""Hotel-scoped access for instructor-assigned simulation students.

A student who is given a hotel role (Front Desk, Concierge, Hotel Manager, ...)
reaches the hotel module through ``manager_required``, which only asks
``accounts.roles.can_access_module`` whether the ROLE owns the module. That
answers "may this person manage hotels at all?" but not "which hotels?".

Without the second question answered the student sees every hotel, every room
and every booking in the platform, and could reach another hotel simply by
editing the id in the URL. The scoping here is deliberately enforced in Python
on top of the querysets and the object lookups, so hiding a control in a
template is never what keeps a student inside their own hotel (BR-085).
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from accounts.roles import (
    FULL_ACCESS_TYPES,
    can_access_module,
    can_create_establishment,
    effective_role_keys,
    owner_role_keys,
)

#: Views that list across hotels and must FILTER rather than reject. Every
#: other hotel management view is keyed to exactly one hotel (directly or
#: through its room/service/amenity/booking) and gets a 403 when the hotel is
#: not assigned.
_LIST_VIEWS = frozenset({'manage', 'rooms', 'services', 'amenities', 'bookings'})

#: Creating or deleting a hotel is a platform-wide action, not something an
#: assigned-hotel student may do. Full-access roles are unaffected.
_PLATFORM_WIDE_VIEWS = frozenset({'add_hotel', 'delete_hotel'})


def is_hotel_scoped(user):
    """True when this request must be confined to the user's assigned hotels.

    Scoping applies to role-holders only: a signed-in customer with no
    simulation role keeps the public storefront (they must still be able to
    browse rooms to book one), and a full-access operator sees everything.
    """
    if not user or not user.is_authenticated:
        return False
    if has_full_hotel_access(user):
        return False
    return can_access_module(user, 'hotels')


def has_full_hotel_access(user):
    """True for the roles that legitimately administer every hotel.

    Django staff and FULL_ACCESS_TYPES (System Administrator, Administrator,
    Instructor/Trainer) are platform-wide operators. A dedicated ``HOTEL_MANAGER``
    account is NOT one of them: it only gets the hotels it was assigned, so
    scoping applies to it too.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    return bool(set(effective_role_keys(user)) & set(FULL_ACCESS_TYPES))


def active_hotel_assignments(user):
    """The user's ACTIVE assignments that point at a hotel."""
    from simulation.models import SimulationRoleAssignment

    return user.simulation_roles.filter(
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        hotel__isnull=False,
    ).select_related('hotel')


def assigned_hotel_ids(user):
    """Ids of the hotels ``user`` is allowed to act on.

    Returns ``None`` when the user is not hotel-scoped at all (full access), and
    a (possibly empty) set of ids otherwise. An empty set is a real answer: a
    student holding only a non-hotel role must not fall back to seeing
    everything, so "no assignment" means "no hotels".
    """
    if has_full_hotel_access(user):
        return None
    if 'HOTEL_OWNER' in owner_role_keys(user):
        from hotels.models import Hotel

        created_ids = Hotel.objects.filter(created_by=user).values_list('pk', flat=True)
        assigned_ids = active_hotel_assignments(user).values_list('hotel_id', flat=True)
        return set(created_ids).union(assigned_ids)
    return set(active_hotel_assignments(user).values_list('hotel_id', flat=True))


def scope_qs(request, qs, field='hotel_id'):
    """Restrict ``qs`` to the hotels this request's user is assigned to.

    ``field`` is the path from the queryset's model to the hotel, e.g.
    ``'hotel_id'`` for ``Room`` and ``'rooms__hotel_id'`` for ``Booking``.
    Call this after :func:`hotel_scoped` has stamped the request. A user with
    no scope yields an empty queryset, never an unrestricted one.
    """
    allowed = getattr(request, 'allowed_hotel_ids', None)
    if allowed is None:
        return qs
    if not allowed:
        return qs.none()
    return qs.filter(**{f'{field}__in': allowed})


def scope_hotels(request, qs):
    """Restrict a ``Hotel`` queryset to the assigned hotels."""
    return scope_qs(request, qs, field='id')


def resolve_hotel_ids(view_name, kwargs):
    """The hotels a view is acting on, read from its URL kwargs.

    ``hotel_id`` is passed straight through. The room/service/amenity/booking
    views are keyed by their own object, so the parent hotel is read from the
    row itself. A booking may span rooms in more than one hotel, so this
    returns a set and the caller requires it to be fully assigned.

    Returns ``None`` when the view is not hotel-keyed at all, which means the
    caller should filter rather than reject.
    """
    if 'hotel_id' in kwargs:
        return {kwargs['hotel_id']}
    from hotels.models import Amenity, Booking, Room, Service

    if 'room_id' in kwargs:
        return set(Room.objects.filter(pk=kwargs['room_id']).values_list('hotel_id', flat=True))
    if 'service_id' in kwargs:
        return set(Service.objects.filter(pk=kwargs['service_id']).values_list('hotel_id', flat=True))
    if 'amenity_id' in kwargs:
        return set(Amenity.objects.filter(pk=kwargs['amenity_id']).values_list('hotel_id', flat=True))
    if 'booking_id' in kwargs:
        return set(
            Booking.objects.filter(pk=kwargs['booking_id']).values_list('rooms__hotel_id', flat=True)
        )
    return None


def active_hotel_assignment_for(user, hotel_id):
    """The user's ACTIVE assignment that covers ``hotel_id``.

    Used for the "Welcome, <name> / Your Assignment" banner so the student is
    always told which role and hotel they are currently acting as. Returns
    ``None`` when the hotel is not one of theirs or the user is not scoped.
    """
    if not hotel_id or not is_hotel_scoped(user):
        return None
    return (
        active_hotel_assignments(user)
        .filter(hotel_id=hotel_id)
        .order_by('-assigned_at')
        .first()
    )


def hotel_scoped(view_func):
    """Confine a hotel view to the hotels the user is assigned to.

    * Full-access roles and unassigned customers pass through untouched.
    * A view keyed to one hotel (or to a room/service/amenity/booking that
      belongs to one) raises 403 when that hotel is not assigned, so swapping
      the id in the URL cannot reach another hotel's data.
    * A list view gets ``request.allowed_hotel_ids`` set and filters its
      queryset with :func:`scope_qs`; the hotel pickers in its template are
      narrowed the same way, so an unassigned hotel is not even offered.
    * ``?hotel=<id>`` (the value "Do the Task" carries in) selects the active
      assignment banner and is verified against the same assignment table.
    """

    @wraps(view_func)
    def wrap(request, *args, **kwargs):
        user = request.user
        request.assigned_hotel_assignment = None
        task_assignment = getattr(request, 'active_simulation_assignment', None)
        task_hotel_id = (
            task_assignment.hotel_id
            if task_assignment and task_assignment.establishment_id
            and task_assignment.establishment.type == 'HOTEL'
            else None
        )
        view_name = getattr(getattr(request.resolver_match, 'func', None), '__name__', '')
        # Enforce owner-only hotel creation before the unscoped-user fast path.
        if (view_name in _PLATFORM_WIDE_VIEWS
                and not can_create_establishment(user, 'hotels')):
            raise PermissionDenied('You are not authorised to add or remove hotels.')
        if not is_hotel_scoped(user) and task_hotel_id is None:
            request.allowed_hotel_ids = None
            return view_func(request, *args, **kwargs)

        allowed = {task_hotel_id} if task_hotel_id is not None else assigned_hotel_ids(user)
        request.allowed_hotel_ids = allowed
        if task_hotel_id is not None:
            request.assigned_hotel_assignment = task_assignment

        requested = (request.GET.get('hotel') or '').strip()
        if requested.isdigit() and allowed is not None:
            requested = int(requested)
            if requested not in allowed:
                # The deep link may only point at a hotel this student holds.
                raise PermissionDenied('You are not assigned to that hotel.')
            if task_hotel_id is None:
                request.assigned_hotel_assignment = active_hotel_assignment_for(user, requested)

        if view_name in _LIST_VIEWS:
            return view_func(request, *args, **kwargs)

        hotel_ids = resolve_hotel_ids(view_name, kwargs) if kwargs else None
        if hotel_ids is not None and allowed is not None and not hotel_ids <= allowed:
            raise PermissionDenied(
                'You are not assigned to this hotel. Ask your instructor to '
                'assign you to it before managing its records.'
            )
        return view_func(request, *args, **kwargs)

    return wrap
