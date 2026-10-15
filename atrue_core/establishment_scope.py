"""Establishment-scoped access for instructor-assigned simulation students.

Generic version of ``atrue_core.hotel_scope``. A student given an operational
role (Manager, Reservation Officer, Front Desk, ...) reaches a module through
``manager_required``, which only answers "may this person manage staycations at
all?" - it does not say "which staycations?".

Without the second question the student sees every staycation, every service
and every booking in the platform, and can reach another establishment simply by
editing the id in the URL. The scope is therefore enforced in Python on top of
the querysets and the object lookups, so hiding a control in a template is never
what keeps a student inside their assigned establishment.

The scope is keyed off the assignment's ``establishment`` link: an ACTIVE
assignment points at exactly one ``Establishment`` row (``establishment_type``
mirrors the type so the filter never needs a join), and the ``entity_id`` of
that row is the id of the catalogue record the student reports to (a
``Staycation``, ``Resort``, ``Restaurant``, ...). One :class:`EstablishmentScope`
instance per establishment type is all an app needs.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

from accounts.roles import FULL_ACCESS_TYPES, can_access_module, effective_role_keys


def assigned_establishment_pks(request, establishment_type):
    """Return active assignment ids for records linked to an Establishment row."""
    user = request.user
    if not user.is_authenticated:
        return set()
    if user.is_staff or set(effective_role_keys(user)).intersection(FULL_ACCESS_TYPES):
        return None

    assignment = getattr(request, 'active_simulation_assignment', None)
    if assignment is not None:
        if (assignment.role_ref_id
                and assignment.role_ref.code.endswith('_OWNER')
                and assignment.role_ref.establishment_category == establishment_type):
            return None
        establishment = assignment.establishment
        if establishment and establishment.type == establishment_type:
            return {establishment.pk}
        return set()

    from simulation.models import SimulationRoleAssignment

    owner_codes = {
        'HOTEL': 'HOTEL_OWNER', 'RESORT': 'RESORT_OWNER',
        'RESTAURANT': 'RESTAURANT_OWNER', 'STAYCATION': 'STAYCATION_OWNER',
        'LANDMARK': 'LANDMARK_OWNER', 'AIRLINE': 'AIRLINE_OWNER',
        'TRAVEL_AGENCY': 'TRAVEL_AGENCY_OWNER', 'TOUR_OPERATOR': 'TOUR_OPERATOR_OWNER',
        'TOUR_PACKAGE': 'TOUR_PACKAGE_OWNER', 'ACTIVITY': 'ACTIVITY_OWNER',
        'TRANSPORTATION': 'TRANSPORTATION_OWNER',
    }
    if owner_codes.get(establishment_type) in effective_role_keys(user):
        return None

    return set(
        SimulationRoleAssignment.objects.filter(
            student=user,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            establishment__type=establishment_type,
        ).values_list('establishment_id', flat=True)
    )


def assigned_establishment_for_write(request, establishment_type):
    """Resolve the one assigned establishment used when creating its records."""
    from django.core.exceptions import PermissionDenied
    from establishments.models import Establishment

    allowed = assigned_establishment_pks(request, establishment_type)
    if allowed is None:
        return None
    if len(allowed) != 1:
        raise PermissionDenied(
            'Select one active establishment assignment before creating records.')
    return Establishment.objects.get(pk=next(iter(allowed)))


class EstablishmentScope:
    """Scope machinery for one establishment type (staycation, resort, ...)."""

    def __init__(self, *, establishment_type, module, list_views, platform_views,
                 id_resolvers, allowed_attr, assignment_attr, query_param,
                 entity_label):
        self.establishment_type = establishment_type
        self.module = module
        self.list_views = frozenset(list_views)
        self.platform_views = frozenset(platform_views)
        self.id_resolvers = id_resolvers
        self.allowed_attr = allowed_attr
        self.assignment_attr = assignment_attr
        self.query_param = query_param
        self.entity_label = entity_label

    # -- predicates -----------------------------------------------------------

    def has_full_access(self, user):
        """True for platform-wide operators (staff, System Admin, Admin, Instructor)."""
        if not user or not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        return bool(set(effective_role_keys(user)) & set(FULL_ACCESS_TYPES))

    def is_scoped(self, user):
        """True when this request must be confined to the user's assigned
        establishments of this type.

        Scoping applies to role-holders only: a signed-in customer with no
        simulation role keeps the public storefront, and a full-access operator
        sees everything. A dedicated ``*_MANAGER`` account is scoped too - it
        only gets the establishments it was assigned.
        """
        if not user or not user.is_authenticated:
            return False
        if self.has_full_access(user):
            return False
        return can_access_module(user, self.module)

    # -- assignments ----------------------------------------------------------

    def active_assignments(self, user):
        """The user's ACTIVE assignments that point at this establishment type."""
        from simulation.models import SimulationRoleAssignment

        return user.simulation_roles.filter(
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            establishment__type=self.establishment_type,
        ).select_related('establishment')

    def assigned_ids(self, user):
        """Catalogue ids of the establishments ``user`` may act on.

        ``None`` means the user is not scoped at all (full access); an empty set
        is a real answer - "no assignment" means "no establishments".
        """
        if self.has_full_access(user):
            return None
        owner_code = {
            'HOTEL': 'HOTEL_OWNER', 'RESORT': 'RESORT_OWNER',
            'RESTAURANT': 'RESTAURANT_OWNER', 'STAYCATION': 'STAYCATION_OWNER',
            'LANDMARK': 'LANDMARK_OWNER', 'AIRLINE': 'AIRLINE_OWNER',
            'TRAVEL_AGENCY': 'TRAVEL_AGENCY_OWNER',
            'TOUR_OPERATOR': 'TOUR_OPERATOR_OWNER',
            'TOUR_PACKAGE': 'TOUR_PACKAGE_OWNER', 'ACTIVITY': 'ACTIVITY_OWNER',
            'TRANSPORTATION': 'TRANSPORTATION_OWNER',
        }.get(self.establishment_type)
        if owner_code and owner_code in effective_role_keys(user):
            return None
        return set(
            self.active_assignments(user).values_list('establishment__entity_id', flat=True))

    def assignment_for(self, user, establishment_id):
        """The user's ACTIVE assignment that covers ``establishment_id``."""
        if not establishment_id or not self.is_scoped(user):
            return None
        return (
            self.active_assignments(user)
            .filter(establishment__entity_id=establishment_id)
            .order_by('-assigned_at')
            .first()
        )

    # -- queryset helpers -----------------------------------------------------

    def scope_qs(self, request, qs, field):
        """Restrict ``qs`` to the establishments this request's user is assigned.

        ``field`` is the path from the queryset's model to the catalogue row id,
        e.g. ``'id'`` for the establishment model itself and ``'staycation_id'``
        for its services or bookings. A user with no scope yields an empty
        queryset, never an unrestricted one.
        """
        allowed = getattr(request, self.allowed_attr, None)
        if allowed is None:
            return qs
        if not allowed:
            return qs.none()
        return qs.filter(**{f'{field}__in': allowed})

    def scope_queryset(self, request, qs):
        """Restrict a queryset of the establishment's own catalogue model."""
        return self.scope_qs(request, qs, field='id')

    # -- object-keyed lookup --------------------------------------------------

    def resolve_ids(self, kwargs):
        """The catalogue ids a view is acting on, read from its URL kwargs.

        ``staycation_id`` is passed straight through. The service/block/booking
        views are keyed by their own object, so the parent establishment is read
        from the row itself. Returns ``None`` when the view is not establishment-
        keyed, which means the caller should filter rather than reject.
        """
        if not kwargs:
            return None
        for kwarg, resolver in self.id_resolvers.items():
            if kwarg in kwargs:
                return resolver(kwargs[kwarg])
        return None

    # -- decorator ------------------------------------------------------------

    def decorator(self):
        """Confine a management view to the establishments the user is assigned.

        * Full-access roles and unassigned customers pass through untouched.
        * A view keyed to one establishment (or to a service/booking that belongs
          to one) raises 403 when that establishment is not assigned, so editing
          the id in the URL cannot reach another establishment's data.
        * A list view gets ``request.<allowed_attr>`` set and filters its
          queryset with :meth:`scope_qs`; the pickers in its template are narrowed
          the same way, so an unassigned establishment is not even offered.
        * ``?<query_param>=<id>`` (the value "Do the Task" carries in) selects
          the active assignment banner and is verified against the assignment
          table.
        """

        def deco(view_func):
            @wraps(view_func)
            def wrap(request, *args, **kwargs):
                user = request.user
                setattr(request, self.assignment_attr, None)
                task_assignment = getattr(request, 'active_simulation_assignment', None)
                task_entity_id = (
                    task_assignment.establishment.entity_id
                    if task_assignment and task_assignment.establishment_id
                    and task_assignment.establishment_type == self.establishment_type
                    else None
                )
                if not self.is_scoped(user) and task_entity_id is None:
                    setattr(request, self.allowed_attr, None)
                    return view_func(request, *args, **kwargs)

                allowed = ({task_entity_id} if task_entity_id is not None
                           else self.assigned_ids(user))
                setattr(request, self.allowed_attr, allowed)
                if task_entity_id is not None:
                    setattr(request, self.assignment_attr, task_assignment)

                requested = (request.GET.get(self.query_param) or '').strip()
                if requested.isdigit():
                    requested = int(requested)
                    if requested not in allowed:
                        # The deep link may only point at an establishment the
                        # student actually holds.
                        raise PermissionDenied(
                            f'You are not assigned to that {self.entity_label}.')
                    if task_entity_id is None:
                        setattr(request, self.assignment_attr,
                                self.assignment_for(user, requested))

                view_name = getattr(
                    getattr(request.resolver_match, 'func', None), '__name__', '')
                if view_name in self.list_views:
                    return view_func(request, *args, **kwargs)
                owner_code = {
                    'HOTEL': 'HOTEL_OWNER', 'RESORT': 'RESORT_OWNER',
                    'RESTAURANT': 'RESTAURANT_OWNER', 'STAYCATION': 'STAYCATION_OWNER',
                    'LANDMARK': 'LANDMARK_OWNER', 'AIRLINE': 'AIRLINE_OWNER',
                    'TRAVEL_AGENCY': 'TRAVEL_AGENCY_OWNER',
                    'TOUR_OPERATOR': 'TOUR_OPERATOR_OWNER',
                    'TOUR_PACKAGE': 'TOUR_PACKAGE_OWNER', 'ACTIVITY': 'ACTIVITY_OWNER',
                    'TRANSPORTATION': 'TRANSPORTATION_OWNER',
                }.get(self.establishment_type)
                has_owner_role = bool(owner_code and owner_code in effective_role_keys(user))
                if view_name in self.platform_views and not has_owner_role:
                    raise PermissionDenied(
                        f'Only a platform administrator can add or remove '
                        f'{self.entity_label} establishments.')

                ids = self.resolve_ids(kwargs) if kwargs else None
                if ids is not None and allowed is not None and not ids <= allowed:
                    raise PermissionDenied(
                        f'You are not assigned to this {self.entity_label}. Ask your '
                        f'instructor to assign you to it before managing its records.'
                    )
                return view_func(request, *args, **kwargs)

            return wrap

        return deco
