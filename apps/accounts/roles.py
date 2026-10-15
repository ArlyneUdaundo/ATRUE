"""Role registry for the ATRUE simulation platform.

Every supported account type maps to display metadata, a tier, and the quick
actions shown on its role dashboard (``templates/role_dashboard.html``).
``MANAGEMENT_ACCOUNT_TYPES`` is the single source of truth for who is treated
as a platform manager (module admin pages, reporting).
``ACCOUNT_MANAGER_TYPES`` is a stricter subset matching the FR module 1 actors
(Administrator, Instructor/Trainer) for user account management.

Permission lists reuse ``simulation.models.ROLE_PERMISSIONS`` so a role shown
on a user account and the role shown on a simulation assignment stay in sync.
"""

from simulation.models import ROLE_PERMISSIONS, SimulationRoleAssignment

#: Account types that manage the platform (module admins, reporting).
ROLE_KEY_ALIASES = {
    'SYSTEM_ADMINISTRATOR': 'SYSTEM_ADMIN',
    'ADMINISTRATOR': 'ADMIN',
    'HOTEL_OWNER': 'HOTEL_MANAGER',
    'RESORT_OWNER': 'RESORT_MANAGER',
    'RESTAURANT_OWNER': 'RESTAURANT_MANAGER',
    'STAYCATION_OWNER': 'STAYCATION_MANAGER',
    'LANDMARK_OWNER': 'LANDMARK_MANAGER',
    'AIRLINE_OWNER': 'AIRLINE_MANAGER',
    'TRAVEL_AGENCY_OWNER': 'TRAVEL_AGENCY_MANAGER',
    'TOUR_OPERATOR_OWNER': 'TOUR_MANAGER',
    'TOUR_PACKAGE_OWNER': 'TOUR_PACKAGE_MANAGER',
    'ACTIVITY_OWNER': 'ACTIVITY_MANAGER',
    'TRANSPORTATION_OWNER': 'TRANSPORT_MANAGER',
}

MANAGEMENT_ACCOUNT_TYPES = frozenset({
    'SYSTEM_ADMIN',
    'ADMIN',
    'INSTRUCTOR',
    'TOUR_MANAGER',
    'HOTEL_MANAGER',
    'TRAVEL_AGENCY_MANAGER',
    'TRAVEL_CONSULTANT',
    'TOUR_COORDINATOR',
    'BILLING_OFFICER',
    'ACTIVITY_MANAGER',
    'TOUR_PACKAGE_MANAGER',
    'HOTEL_OWNER',
    'RESORT_OWNER',
    'RESTAURANT_OWNER',
    'STAYCATION_OWNER',
    'LANDMARK_OWNER',
    'AIRLINE_OWNER',
    'TRAVEL_AGENCY_OWNER',
    'TOUR_OPERATOR_OWNER',
    'TOUR_PACKAGE_OWNER',
    'ACTIVITY_OWNER',
    'TRANSPORTATION_OWNER',
})

#: Account types that may manage user accounts (FR module 1 actors:
#: Administrator, Instructor/Trainer, plus System Administrator).
#: These may CREATE (student accounts only for ADMIN/INSTRUCTOR), RETRIEVE,
#: VIEW and DEACTIVATE user accounts (USER_ROLE.md module 1).
ACCOUNT_MANAGER_TYPES = frozenset({
    'SYSTEM_ADMIN',
    'ADMIN',
    'INSTRUCTOR',
})

#: Account types that may also UPDATE other user accounts and SET passwords.
#: USER_ROLE.md module 1 grants UPDATE to the Administrator only, while the
#: Instructor/Trainer row is "—", so instructors are limited to their own
#: profile via the VIEW (own) / UPDATE (own) rights.
ACCOUNT_UPDATE_TYPES = frozenset({
    'SYSTEM_ADMIN',
    'ADMIN',
})

#: Account types that may create accounts of ANY type. Only the System
#: Administrator qualifies; Administrator and Instructor/Trainer may only
#: create Student accounts.
ACCOUNT_CREATE_ANY_TYPES = frozenset({
    'SYSTEM_ADMIN',
})

#: Account types with unrestricted access to every module's admin functions.
FULL_ACCESS_TYPES = frozenset({
    'SYSTEM_ADMIN',
    'ADMIN',
    'INSTRUCTOR',
})

#: Per-role module (URL namespace) access, derived from the admin/management
#: actions listed in ROLE_DEFS below. Each role may only open the admin
#: functions of the modules it is assigned to. Support-tier staff are granted
#: the modules their role dashboard advertises (Receptionist/Front Desk respond
#: to hotel bookings, Concierge manages hotel amenities, Wait Staff handle
#: restaurant reservations, Transport Staff coordinate transport bookings and
#: Cabin Crew run airline services) per USER_ROLE.md; guest accounts are
#: booking-only and are intentionally not listed here.
MANAGEMENT_MODULE_ACCESS = {
    'TOUR_MANAGER': frozenset({'tour_package', 'activities', 'landmarks', 'transactions'}),
    'HOTEL_MANAGER': frozenset({'hotels', 'staycations', 'transactions'}),
    'TRAVEL_AGENCY_MANAGER': frozenset({'airlines', 'hotels', 'tour_package', 'transactions'}),
    'TRAVEL_CONSULTANT': frozenset({'transactions'}),
    'TOUR_COORDINATOR': frozenset({'tour_package', 'activities', 'landmarks', 'transactions'}),
    'AIRLINE_MANAGER': frozenset({'airlines'}),
    'TRANSPORT_MANAGER': frozenset({'transportation'}),
    'RESORT_MANAGER': frozenset({'resorts', 'staycations', 'transactions'}),
    'RESTAURANT_MANAGER': frozenset({'restaurants', 'transactions'}),
    'STAYCATION_MANAGER': frozenset({'staycations', 'transactions'}),
    'LANDMARK_MANAGER': frozenset({'landmarks', 'transactions'}),
    'ACTIVITY_MANAGER': frozenset({'activities'}),
    'TOUR_PACKAGE_MANAGER': frozenset({'tour_package'}),
    'RECEPTIONIST': frozenset({'hotels'}),
    'FRONT_DESK': frozenset({'hotels'}),
    'CONCIERGE': frozenset({'hotels'}),
    'RESORT_STAFF': frozenset({'resorts'}),
    'RESTAURANT_STAFF': frozenset({'restaurants'}),
    'STAYCATION_STAFF': frozenset({'staycations'}),
    'LANDMARK_STAFF': frozenset({'landmarks'}),
    'TRANSPORT_STAFF': frozenset({'transportation'}),
    'CABIN_CREW': frozenset({'airlines'}),
}

#: Each operational role, given the access of the retired role it replaces.
#:
#: This map is what turns "an instructor assigned this student a role" into access
#: at all (``effective_role_keys`` feeds :func:`can_access_module`): without an
#: entry the assignment is stored and displayed perfectly well and the student is
#: then refused every module it names. It is a fourth list of role names that has
#: to move in step with ``role_catalogue`` - as it did not when the
#: three-roles-per-establishment catalogue was introduced.
#:
#: The hotels, transportation, tour and travel-agency families keep whole-module
#: access, because that is how their retired roles already worked: a hotel student
#: may open the hotels module and is then confined to their own hotel by
#: ``atrue_core.hotel_scope``, which reads the establishment mirrored onto each
#: assignment. The airline family is the exception - its retired non-manager roles
#: deliberately had *no* module access and were limited to an allowlist, so the
#: airline Manager keeps the module and the two airline staff roles are allowlisted
#: below instead.
_OPERATIONAL_MODULE_ACCESS = {
    'HOTEL_MANAGER': 'HOTEL_MANAGER',
    'HOTEL_RESERVATION_OFFICER': 'FRONT_DESK',
    'HOTEL_FRONT_DESK': 'FRONT_DESK',
    'AIRLINE_MANAGER': 'CABIN_CREW',
    'TRANSPORT_MANAGER': 'TRANSPORT_STAFF',
    'TRANSPORT_RESERVATION_AGENT': 'TRANSPORT_STAFF',
    'TRANSPORT_FRONT_DESK': 'TRANSPORT_STAFF',
    'TOUR_OPERATOR_MANAGER': 'TOUR_MANAGER',
    'TOUR_RESERVATION_AGENT': 'TOUR_COORDINATOR',
    'TOUR_FRONT_DESK': 'TOUR_COORDINATOR',
    'TRAVEL_AGENCY_MANAGER': 'TRAVEL_AGENCY_MANAGER',
    'TRAVEL_AGENCY_RESERVATION_AGENT': 'TRAVEL_AGENCY_MANAGER',
    'TRAVEL_AGENCY_FRONT_DESK': 'TRAVEL_AGENCY_MANAGER',
    'RESORT_MANAGER': 'RESORT_MANAGER',
    'RESORT_RESERVATION_OFFICER': 'RESORT_STAFF',
    'RESORT_FRONT_DESK': 'RESORT_STAFF',
    'RESTAURANT_MANAGER': 'RESTAURANT_MANAGER',
    'RESTAURANT_RESERVATION_OFFICER': 'RESTAURANT_STAFF',
    'RESTAURANT_FRONT_DESK': 'RESTAURANT_STAFF',
    'STAYCATION_MANAGER': 'STAYCATION_MANAGER',
    'STAYCATION_RESERVATION_OFFICER': 'STAYCATION_STAFF',
    'STAYCATION_FRONT_DESK': 'STAYCATION_STAFF',
    'LANDMARK_MANAGER': 'LANDMARK_MANAGER',
    'LANDMARK_RESERVATION_OFFICER': 'LANDMARK_STAFF',
    'LANDMARK_FRONT_DESK': 'LANDMARK_STAFF',
}

MANAGEMENT_MODULE_ACCESS.update({
    code: MANAGEMENT_MODULE_ACCESS[retired]
    for code, retired in _OPERATIONAL_MODULE_ACCESS.items()
})

MANAGEMENT_MODULE_ACCESS.update({
    'HOTEL_OWNER': frozenset({'hotels'}),
    'RESORT_OWNER': frozenset({'resorts'}),
    'RESTAURANT_OWNER': frozenset({'restaurants'}),
    'STAYCATION_OWNER': frozenset({'staycations'}),
    'LANDMARK_OWNER': frozenset({'landmarks'}),
    'AIRLINE_OWNER': frozenset({'airlines'}),
    'TRAVEL_AGENCY_OWNER': frozenset({'tour_package'}),
    'TOUR_OPERATOR_OWNER': frozenset({'tour_package'}),
    'TOUR_PACKAGE_OWNER': frozenset({'tour_package'}),
    'ACTIVITY_OWNER': frozenset({'activities'}),
    'TRANSPORTATION_OWNER': frozenset({'transportation'}),
})

# Operational staff roles are allowlisted rather than given the whole module,
# keeping reservation and front-desk roles out of manager-only routes.
_OPERATIONAL_STAFF_ROLES = {
    'AIRLINE_RESERVATION_AGENT': 'AIRLINE',
    'AIRLINE_FRONT_DESK': 'AIRLINE',
    'ACTIVITY_RESERVATION_OFFICER': 'ACTIVITY',
    'ACTIVITY_OPERATOR': 'ACTIVITY',
    'ACTIVITY_FRONT_DESK_OFFICER': 'ACTIVITY',
    'TOUR_PACKAGE_RESERVATION_OFFICER': 'TOUR_PACKAGE',
    'TOUR_PACKAGE_OPERATOR': 'TOUR_PACKAGE',
    'TOUR_PACKAGE_FRONT_DESK_OFFICER': 'TOUR_PACKAGE',
}


# Ticketing staff may use passenger-facing airline search and reservation/ticket
# pages, but not the airline administration routes guarded by manager_required.
ROLE_MODULE_ROUTE_ACCESS = {
    'AIRLINE_RESERVATION_AGENT': {
        'airlines': frozenset({
            'bookings', 'booking_detail', 'ticket', 'ticket_pdf',
        }),
    },
    'AIRLINE_TICKETING_OFFICER': {
        'airlines': frozenset({
            'list', 'airports_api',
            'bookings', 'booking_detail', 'flight_detail', 'ticket', 'ticket_pdf',
            'itinerary_public_detail',
        }),
    },
}


def _route_grants_from_operations():
    """Group each allowlisted role's routes by URL namespace.

    Read from ``task_routing`` rather than written out by hand so the routes
    "Do the Task" links to and the routes the backend will admit cannot disagree:
    the task button must not lead to a 403, and a role must not reach a page it
    was never offered. Retired keys already listed above are left alone.
    """
    from simulation.task_routing import _OPERATIONS

    grants = {}
    for code, establishment_type in _OPERATIONAL_STAFF_ROLES.items():
        operation = _OPERATIONS.get(establishment_type, {}).get(code)
        if operation is None:
            continue
        by_module = {}
        for route in operation['allowed_routes']:
            namespace, _, name = route.partition(':')
            if name:
                by_module.setdefault(namespace, set()).add(name)
        grants[code] = {module: frozenset(names)
                        for module, names in by_module.items()}
    return grants


ROLE_MODULE_ROUTE_ACCESS.update(_route_grants_from_operations())

ROLE_MODULE_ROUTE_ACCESS['BILLING_OFFICER'] = {
    'transactions': frozenset({'payment_review'}),
}


def _normalize_role_key(key):
    """Translate legacy simulation role aliases back onto the platform keys."""
    return ROLE_KEY_ALIASES.get(key, key)


def effective_role_keys(user):
    """Return the role keys currently in effect for ``user``: their account type
    plus every ACTIVE instructor-assigned simulation role (BR-083/BR-084).

    This is the single source of truth for what a user may do: a student who
    was assigned the HOTEL_MANAGER role by an instructor is treated as a Hotel
    Manager and gains that role's module access (hotels, staycations, billing).
    """
    if not user or not user.is_authenticated:
        return set()
    keys = {_normalize_role_key(user.account_type)}
    for role in user.simulation_roles.filter(
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).values_list('role', flat=True):
        keys.add(_normalize_role_key(role))
    return keys


def can_access_module(user, module):
    """Return True when ``user`` may manage the given URL namespace ``module``.

    Django staff/superusers and FULL_ACCESS_TYPES (System Administrator,
    Administrator, Instructor/Trainer) always pass; management accounts are
    limited to the modules in MANAGEMENT_MODULE_ACCESS; everyone else is
    booking-only. An ACTIVE instructor-assigned simulation role grants the same
    module access as the account type itself (BR-084).
    """
    if user.is_staff:
        return True
    for key in effective_role_keys(user):
        if key in FULL_ACCESS_TYPES:
            return True
        if module in MANAGEMENT_MODULE_ACCESS.get(key, frozenset()):
            return True
    return False


def can_access_module_route(user, module, route_name):
    """Check access to one module route, including role-specific route grants.

    A role with full module ownership keeps its existing access. Restricted
    role grants are an allowlist and never imply management access to the whole
    module.
    """
    if not user or not user.is_authenticated:
        return False
    if can_access_module(user, module):
        return True
    return any(
        route_name in ROLE_MODULE_ROUTE_ACCESS.get(key, {}).get(module, ())
        for key in effective_role_keys(user)
    )


#: The airline staff roles: they serve passengers from inside the airline but do
#: not administer it, so they carry an allowlist rather than module access. The
#: retired ``AIRLINE_TICKETING_OFFICER`` is listed so an assignment made before
#: the catalogue change keeps behaving exactly as it did.
AIRLINE_STAFF_ROLE_KEYS = frozenset({
    'AIRLINE_TICKETING_OFFICER',
    'AIRLINE_RESERVATION_AGENT',
    'AIRLINE_FRONT_DESK',
})

#: Airline staff who work an issued ticket rather than a reservation. The active
#: ``AIRLINE_FRONT_DESK`` replaced ``AIRLINE_TICKETING_OFFICER``, so both are
#: listed: gating the narrower action set on the retired code alone would let
#: the new role perform every manager action on a booking.
AIRLINE_TICKETING_ROLE_KEYS = frozenset({
    'AIRLINE_TICKETING_OFFICER',
    'AIRLINE_FRONT_DESK',
})


def is_airline_ticketing_only(user):
    """Whether the user's only non-default role is an airline staff role."""
    if not user or not user.is_authenticated:
        return False
    role_keys = effective_role_keys(user)
    staff_keys = role_keys & AIRLINE_STAFF_ROLE_KEYS
    if len(staff_keys) != 1:
        return False
    if user.account_type == 'STUDENT':
        return role_keys == {'STUDENT'} | staff_keys
    return role_keys == staff_keys


def is_airline_booking_restricted(user):
    """Airline staff cannot create passenger bookings unless another role grants it."""
    role_keys = effective_role_keys(user)
    return (
        bool(role_keys & AIRLINE_STAFF_ROLE_KEYS)
        and 'PASSENGER_AIRLINE' not in role_keys
        and not can_access_module(user, 'airlines')
    )


#: Landmark operational roles: the Reservation Officer receives and confirms
#: requests, the Front Desk checks confirmed tickets in. The manager keeps both
#: sides as oversight, and platform accounts (staff, management types) may do
#: either. Both roles share the whole landmarks module (LANDMARK_STAFF), so
#: ``can_manage_booking`` alone cannot tell them apart - these helpers do.
LANDMARK_RESERVATION_ROLE_KEYS = frozenset({
    'LANDMARK_RESERVATION_OFFICER',
})

LANDMARK_CHECKIN_ROLE_KEYS = frozenset({
    'LANDMARK_FRONT_DESK',
})


def can_confirm_landmark_booking(user):
    """True when ``user`` may confirm/decline a landmark ticket request."""
    if not user or not user.is_authenticated:
        return False
    return bool(effective_role_keys(user) & LANDMARK_RESERVATION_ROLE_KEYS)


def can_checkin_landmark_booking(user):
    """True when ``user`` may check a confirmed landmark ticket in."""
    if not user or not user.is_authenticated:
        return False
    return bool(effective_role_keys(user) & LANDMARK_CHECKIN_ROLE_KEYS)


def landmark_work_queue(user):
    """The landmark bookings a role works by default: ``'confirm'`` for a
    reservation officer, ``'checkin'`` for a front desk officer, ``None`` for a
    manager/platform account that may work every status."""
    if not user or not user.is_authenticated:
        return None
    if is_platform_user(user):
        return None
    role_keys = effective_role_keys(user)
    if role_keys & LANDMARK_RESERVATION_ROLE_KEYS and not role_keys & LANDMARK_CHECKIN_ROLE_KEYS:
        return 'confirm'
    if role_keys & LANDMARK_CHECKIN_ROLE_KEYS and not role_keys & LANDMARK_RESERVATION_ROLE_KEYS:
        return 'checkin'
    return None


# --------------------------------------------------------------------------- #
# Django admin permissions
#
# The role registry above governs this project's *own* pages. The Django admin
# at /admin/ ignores it entirely and only honours real ``auth`` permissions, so
# a staff account created outside ``seed_roles`` reaches /admin/ and is then
# refused every changelist with a bare 403 ("You do not have permission to
# access this part of the admin"). ``sync_admin_permissions`` derives the
# matching ``auth`` permissions from the same registry so the two agree.
# --------------------------------------------------------------------------- #

#: Apps holding platform data (everything installed that is not django.*).
#: Reference apps such as ``locations`` back the pickers on the admin screens
#: and ride along with the rest rather than being granted on their own.
def _platform_app_labels():
    from django.apps import apps as django_apps

    return {config.label for config in django_apps.get_app_configs()
            if not config.name.startswith('django.')}


def admin_app_labels(user):
    """App labels whose models ``user`` may administer in the Django admin.

    Mirrors the short-circuit at the top of ``can_access_module``: staff (and
    superusers) reach every module of this project, so they are granted the
    whole platform. Non-staff accounts get nothing, because ``AdminSite`` refuses
    them at the door anyway and their access is governed by the role registry
    on the project's own pages.
    """
    if not user.is_staff:
        return set()
    return _platform_app_labels()


#: Apps where ``delete`` is withheld in the admin:
#:
#: ``accounts`` - deleting a user would cascade away their booking history,
#:   which FR-005 deliberately preserves: accounts are deactivated
#:   (``User.Status.INACTIVE``), never removed.
#: ``locations`` - GeoNames reference data loaded by ``sync_geonames``. Its
#:   Country/Region/Province/CityMunicipality/Barangay models are multi-table
#:   children of GeoPlace, so removing one cascades through the shared parent
#:   and can take the whole geographic tree with it.
NO_DELETE_APP_LABELS = frozenset({'accounts', 'locations'})


def admin_permission_diff(user):
    """Return ``(to_grant, to_revoke)`` permission ids for ``user``'s role.

    Both sets are empty for a superuser, which Django already authorises
    outright.
    """
    from django.contrib.auth.models import Permission

    if user.is_superuser:
        return set(), set()

    granted = Permission.objects.filter(
        content_type__app_label__in=admin_app_labels(user)
    ).exclude(
        codename__startswith='delete_',
        content_type__app_label__in=NO_DELETE_APP_LABELS,
    )
    wanted = set(granted.values_list('id', flat=True))
    current = set(user.user_permissions.values_list('id', flat=True))
    return wanted - current, current - wanted


def sync_admin_permissions(user):
    """Align ``user``'s Django admin permissions with their platform role.

    Grants view/change/add/delete on every model in ``admin_app_labels(user)``
    (minus ``NO_DELETE_APP_LABELS``) and revokes anything the role no longer
    covers, so demoting an account immediately removes its admin reach.

    Returns ``(granted, revoked)`` counts.
    """
    granted, revoked = admin_permission_diff(user)
    if not granted and not revoked:
        return 0, 0

    wanted = (set(user.user_permissions.values_list('id', flat=True)) | granted) - revoked
    user.user_permissions.set(wanted)
    return len(granted), len(revoked)


def can_manage_booking(user, module):
    """True when ``user`` may manage a booking in ``module``: platform accounts
    (staff, management account types) or any ACTIVE assigned role owning the
    module (e.g. a student assigned HOTEL_MANAGER can respond to hotel bookings)."""
    return is_platform_user(user) or can_access_module_route(
        user, module, 'booking_detail',
    )


_RESERVATION_ONLY_ROLE_KEYS = {
    'airlines': {'AIRLINE_RESERVATION_AGENT', 'AIRLINE_RESERVATION_OFFICER'},
    'hotels': {'HOTEL_RESERVATION_OFFICER'},
    'resorts': {'RESORT_RESERVATION_OFFICER'},
    'restaurants': {'RESTAURANT_RESERVATION_OFFICER'},
    'staycations': {'STAYCATION_RESERVATION_OFFICER'},
    'transportation': {'TRANSPORT_RESERVATION_AGENT', 'TRANSPORT_RESERVATION_OFFICER'},
    'activities': {'ACTIVITY_RESERVATION_OFFICER'},
    'landmarks': {'LANDMARK_RESERVATION_OFFICER'},
    'tour_package': {'TOUR_PACKAGE_RESERVATION_OFFICER', 'TOUR_RESERVATION_AGENT'},
}


def is_reservation_officer(user, module):
    """True for a reservation-only role that must not access lifecycle controls."""
    if not user or not user.is_authenticated or is_platform_user(user):
        return False
    keys = effective_role_keys(user)
    reservation_roles = _RESERVATION_ONLY_ROLE_KEYS.get(module, set())
    if not keys & reservation_roles:
        return False
    lifecycle_roles = {
        'airlines': {'AIRLINE_MANAGER', 'AIRLINE_FRONT_DESK', 'AIRLINE_TICKETING_OFFICER'},
        'hotels': {'HOTEL_MANAGER', 'HOTEL_OWNER', 'HOTEL_FRONT_DESK', 'RECEPTIONIST', 'FRONT_DESK'},
        'resorts': {'RESORT_MANAGER', 'RESORT_OWNER', 'RESORT_FRONT_DESK'},
        'restaurants': {'RESTAURANT_MANAGER', 'RESTAURANT_OWNER', 'RESTAURANT_FRONT_DESK'},
        'staycations': {'STAYCATION_MANAGER', 'STAYCATION_OWNER', 'STAYCATION_FRONT_DESK'},
        'transportation': {'TRANSPORT_MANAGER', 'TRANSPORTATION_OWNER', 'TRANSPORT_FRONT_DESK'},
        'activities': {'ACTIVITY_MANAGER', 'ACTIVITY_OWNER', 'ACTIVITY_FRONT_DESK_OFFICER', 'ACTIVITY_OPERATOR'},
        'landmarks': {'LANDMARK_MANAGER', 'LANDMARK_OWNER', 'LANDMARK_FRONT_DESK'},
        'tour_package': {'TOUR_PACKAGE_MANAGER', 'TOUR_PACKAGE_OWNER', 'TOUR_FRONT_DESK', 'TOUR_PACKAGE_FRONT_DESK_OFFICER', 'TOUR_PACKAGE_OPERATOR'},
    }.get(module, set())
    return not bool(keys & lifecycle_roles)


def can_process_booking_checkin(user, module):
    """Only the assigned front-desk role may process arrival/departure."""
    if not user or not user.is_authenticated:
        return False
    front_desk_roles = {
        'hotels': {'HOTEL_FRONT_DESK', 'FRONT_DESK', 'RECEPTIONIST'},
        'resorts': {'RESORT_FRONT_DESK'},
        'restaurants': {'RESTAURANT_FRONT_DESK'},
        'staycations': {'STAYCATION_FRONT_DESK'},
        'transportation': {'TRANSPORT_FRONT_DESK'},
        'airlines': {'AIRLINE_FRONT_DESK'},
        'activities': {'ACTIVITY_FRONT_DESK_OFFICER', 'ACTIVITY_OPERATOR'},
        'landmarks': {'LANDMARK_FRONT_DESK'},
        'tour_package': {'TOUR_FRONT_DESK', 'TOUR_PACKAGE_FRONT_DESK_OFFICER', 'TOUR_PACKAGE_OPERATOR'},
    }
    return bool(set(effective_role_keys(user)) & front_desk_roles.get(module, set()))


def is_platform_user(user):
    """True for platform accounts (staff and management account types), regardless
    of temporary student role assignments (used to keep booking-as-customer open
    to students)."""
    if not user or not user.is_authenticated:
        return False
    return user.is_staff or user.account_type in MANAGEMENT_ACCOUNT_TYPES


def is_account_manager(user):
    """FR Module 1: can CREATE / RETRIEVE / VIEW / DEACTIVATE user accounts.

    System Administrator, Administrator and Instructor/Trainer (USER_ROLE.md).
    """
    return user.is_authenticated and (user.is_staff or user.account_type in ACCOUNT_MANAGER_TYPES)


def can_update_accounts(user):
    """FR Module 1 UPDATE: only System Administrator / Administrator may update
    other user accounts; the Instructor/Trainer row is "—" (own profile only)."""
    return user.is_authenticated and (user.is_staff or user.account_type in ACCOUNT_UPDATE_TYPES)


def can_create_any_account(user):
    """Only the System Administrator may create accounts of any type; other
    account managers are limited to Student accounts (FR-001)."""
    return user.is_authenticated and (user.is_staff or user.account_type in ACCOUNT_CREATE_ANY_TYPES)

TIER_LABELS = {
    'PLATFORM': 'Platform Administrator',
    'MANAGEMENT': 'Management',
    'GUEST': 'Simulation Guest',
    'SUPPORT': 'Support Staff',
}


def _role(key, label, icon, tier, blurb, actions, permissions=None):
    return {
        'key': key,
        'label': label,
        'icon': icon,
        'tier': tier,
        'blurb': blurb,
        'permissions': permissions if permissions is not None else ROLE_PERMISSIONS.get(key, []),
        'actions': [{'url': url, 'icon': icon_name, 'label': action_label}
                    for url, icon_name, action_label in actions],
    }


ROLE_DEFS = {
    'SYSTEM_ADMIN': _role(
        'SYSTEM_ADMIN', 'System Administrator', 'fa-user-shield', 'PLATFORM',
        'Full control over accounts, services, simulations and platform reporting.',
        [
            ('accounts:account_list', 'fa-users', 'Manage User Accounts'),
            ('accounts:account_create', 'fa-user-plus', 'Create User Account'),
            ('simulation:assign', 'fa-user-tag', 'Assign Simulation Roles'),
            ('simulation:role_list', 'fa-clipboard-list', 'Role Assignments'),
            ('simulation:logs', 'fa-history', 'Activity Logs'),
            ('admin:index', 'fa-cog', 'Django Admin Site'),
        ],
        permissions=[
            'Create, view, update and deactivate user accounts',
            'Assign simulation roles to students',
            'Manage every service module (flights, hotels, tours, transport, ...)',
            'Approve and review transactions and payments',
            'Review activity logs and platform reports',
        ],
    ),
    # -- Management tier -------------------------------------------------------
    'TOUR_MANAGER': _role(
        'TOUR_MANAGER', 'Tour Manager', 'fa-briefcase', 'MANAGEMENT',
        'Oversee tour itineraries, schedules, coordinators and guides.',
        [
            ('tour_package:manage', 'fa-luggage-cart', 'Tour Package Admin'),
            ('tour_package:list', 'fa-suitcase-rolling', 'Browse Tour Packages'),
            ('activities:manage', 'fa-person-hiking', 'Activity Admin'),
            ('landmarks:manage', 'fa-monument', 'Attraction Admin'),
            ('transactions:admin_list', 'fa-file-invoice-dollar', 'Transactions'),
        ],
    ),
    'HOTEL_MANAGER': _role(
        'HOTEL_MANAGER', 'Hotel Manager', 'fa-hotel', 'MANAGEMENT',
        'Manage hotel operations, rooms, staff and occupancy reports.',
        [
            ('hotels:manage', 'fa-hotel', 'Hotel Admin'),
            ('hotels:rooms', 'fa-bed', 'Room Management'),
            ('hotels:services', 'fa-concierge-bell', 'Hotel Services'),
            ('hotels:amenities', 'fa-swimming-pool', 'Hotel Amenities'),
            ('staycations:manage', 'fa-couch', 'Staycation Admin'),
            ('hotels:bookings', 'fa-book-open', 'Hotel Bookings'),
            ('transactions:admin_list', 'fa-file-invoice-dollar', 'Transactions'),
        ],
    ),
    'TRAVEL_AGENCY_MANAGER': _role(
        'TRAVEL_AGENCY_MANAGER', 'Travel Agency Manager', 'fa-suitcase', 'MANAGEMENT',
        'Oversee agency operations, consultants, bookings and agency reports.',
        [
            ('airlines:manage', 'fa-plane-departure', 'Airline Admin'),
            ('airlines:flights', 'fa-fighter-jet', 'Flights'),
            ('airlines:bookings', 'fa-book-open', 'Airline Bookings'),
            ('airlines:services', 'fa-concierge-bell', 'Airline Services'),
            ('hotels:manage', 'fa-hotel', 'Hotel Admin'),
            ('tour_package:manage', 'fa-luggage-cart', 'Tour Package Admin'),
            ('transactions:admin_list', 'fa-file-invoice-dollar', 'Transactions'),
        ],
    ),
    'TRAVEL_CONSULTANT': _role(
        'TRAVEL_CONSULTANT', 'Travel Consultant', 'fa-compass', 'MANAGEMENT',
        'Advise customers on destinations, create itineraries and process bookings.',
        [
            ('airlines:list', 'fa-plane', 'Search Flights'),
            ('hotels:list', 'fa-hotel', 'Search Hotels'),
            ('resorts:list', 'fa-umbrella-beach', 'Search Resorts'),
            ('tour_package:list', 'fa-suitcase-rolling', 'Search Tour Packages'),
            ('restaurants:list', 'fa-utensils', 'Restaurants'),
            ('transactions:admin_list', 'fa-file-invoice-dollar', 'Transactions'),
        ],
    ),
    'TOUR_COORDINATOR': _role(
        'TOUR_COORDINATOR', 'Tour Coordinator', 'fa-calendar-check', 'MANAGEMENT',
        'Coordinate tour groups and keep hotels, partners and customers in sync.',
        [
            ('tour_package:manage', 'fa-luggage-cart', 'Tour Package Admin'),
            ('tour_package:bookings', 'fa-book-open', 'Tour Package Bookings'),
            ('activities:manage', 'fa-person-hiking', 'Activity Admin'),
            ('landmarks:manage', 'fa-monument', 'Attraction Admin'),
            ('activities:bookings', 'fa-book-open', 'Activity Bookings'),
            ('transactions:admin_list', 'fa-file-invoice-dollar', 'Transactions'),
        ],
    ),
    'ACTIVITY_MANAGER': _role(
        'ACTIVITY_MANAGER', 'Activity Manager', 'fa-person-hiking', 'MANAGEMENT',
        'Manage only assigned activity listings, schedules, prices and capacity.',
        [('activities:manage', 'fa-person-hiking', 'Activity Management')],
    ),
    'ACTIVITY_RESERVATION_OFFICER': _role(
        'ACTIVITY_RESERVATION_OFFICER', 'Activity Reservation Officer',
        'fa-calendar-check', 'SUPPORT',
        'Review and process bookings for the assigned activity operation.',
        [('activities:bookings', 'fa-calendar-check', 'Activity Bookings')],
    ),
    'ACTIVITY_OPERATOR': _role(
        'ACTIVITY_OPERATOR', 'Activity / Tour Operator',
        'fa-person-hiking', 'SUPPORT',
        'Operate the one assigned activity: attend and complete its bookings and '
        'update its operational status.',
        [('activities:operate', 'fa-person-hiking', 'Operate Assigned Activity')],
    ),
    'ACTIVITY_FRONT_DESK_OFFICER': _role(
        'ACTIVITY_FRONT_DESK_OFFICER', 'Activity Front Desk Officer',
        'fa-person-hiking', 'SUPPORT',
        'Verify confirmed bookings and handle guest arrivals for assigned activities.',
        [('activities:operate', 'fa-person-hiking', 'Activity Arrivals')],
    ),
    'TOUR_PACKAGE_MANAGER': _role(
        'TOUR_PACKAGE_MANAGER', 'Tour Package Manager', 'fa-suitcase-rolling',
        'MANAGEMENT',
        'Manage only assigned tour package details, pricing, schedules, and availability.',
        [
            ('tour_package:manage', 'fa-suitcase-rolling', 'Tour Package Management'),
        ],
    ),
    'TOUR_PACKAGE_RESERVATION_OFFICER': _role(
        'TOUR_PACKAGE_RESERVATION_OFFICER', 'Tour Package Reservation Officer',
        'fa-calendar-check', 'SUPPORT',
        'Review and process bookings for the assigned tour package operation.',
        [('tour_package:bookings', 'fa-calendar-check', 'Package Bookings')],
    ),
    'TOUR_PACKAGE_OPERATOR': _role(
        'TOUR_PACKAGE_OPERATOR', 'Tour Operator (legacy)',
        'fa-suitcase-rolling', 'SUPPORT',
        'Legacy frontdesk role for existing package assignments.',
        [('tour_package:operate', 'fa-suitcase-rolling', 'Operate Assigned Tour Package')],
    ),
    'TOUR_PACKAGE_FRONT_DESK_OFFICER': _role(
        'TOUR_PACKAGE_FRONT_DESK_OFFICER', 'Tour Package Front Desk Officer',
        'fa-suitcase-rolling', 'SUPPORT',
        'Handle fulfilment for bookings at the assigned tour package operation.',
        [('tour_package:operate', 'fa-suitcase-rolling', 'Operate Assigned Tour Package')],
    ),
    'BILLING_OFFICER': _role(
        'BILLING_OFFICER', 'Billing Officer', 'fa-calculator', 'MANAGEMENT',
        'Issue bills and receipts, process payments and reconcile records.',
        [
            ('transactions:admin_list', 'fa-file-invoice-dollar', 'All Transactions'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
            ('transactions:additional_list', 'fa-plus-circle', 'Additional Charges'),
            ('transactions:additional_add', 'fa-plus', 'Add Additional Charge'),
            ('transactions:booking_list', 'fa-bookmark', 'Bookings Ledger'),
        ],
    ),
    # -- Guest / customer tier -------------------------------------------------
    'GUEST_HOTEL': _role(
        'GUEST_HOTEL', 'Guest – Hotel', 'fa-bed', 'GUEST',
        'Book hotel and staycation rooms, view rates and settle bills.',
        [
            ('hotels:list', 'fa-hotel', 'Browse Hotels'),
            ('staycations:list', 'fa-couch', 'Browse Staycations'),
            ('restaurants:list', 'fa-utensils', 'Restaurants'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    'PASSENGER_AIRLINE': _role(
        'PASSENGER_AIRLINE', 'Passenger – Airline', 'fa-plane', 'GUEST',
        'Search and book flights, select seats and manage your bookings.',
        [
            ('airlines:list', 'fa-plane', 'Search Flights'),
            ('airlines:bookings', 'fa-book-open', 'My Flight Bookings'),
            ('transportation:list', 'fa-bus', 'Ground Transportation'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    'CUSTOMER_TOUR': _role(
        'CUSTOMER_TOUR', 'Customer – Tour', 'fa-suitcase-rolling', 'GUEST',
        'Reserve tour packages, view itineraries and make tour payments.',
        [
            ('tour_package:list', 'fa-suitcase-rolling', 'Browse Tour Packages'),
            ('activities:list', 'fa-hiking', 'Browse Activities'),
            ('landmarks:list', 'fa-landmark', 'Browse Landmarks'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    # -- Support tier ----------------------------------------------------------
    'RECEPTIONIST': _role(
        'RECEPTIONIST', 'Receptionist', 'fa-handshake', 'SUPPORT',
        'Receive guests, check them in and handle walk-in inquiries.',
        [
            ('hotels:list', 'fa-hotel', 'Browse Hotels'),
            ('hotels:bookings', 'fa-book-open', 'Hotel Bookings'),
            ('restaurants:list', 'fa-utensils', 'Restaurants'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    'BOOKING_AGENT': _role(
        'BOOKING_AGENT', 'Booking Agent', 'fa-headset', 'SUPPORT',
        'Process customer bookings and check availability and rates.',
        [
            ('airlines:list', 'fa-plane', 'Search Flights'),
            ('hotels:list', 'fa-hotel', 'Search Hotels'),
            ('resorts:list', 'fa-umbrella-beach', 'Search Resorts'),
            ('tour_package:list', 'fa-suitcase-rolling', 'Search Tour Packages'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
        ],
    ),
    'FRONT_DESK': _role(
        'FRONT_DESK', 'Front Desk Officer', 'fa-concierge-bell', 'SUPPORT',
        'Manage hotel operations, rooms, services, amenities and guest check-in/check-out.',
        [
            ('hotels:manage', 'fa-hotel', 'Hotel Admin'),
            ('hotels:rooms', 'fa-bed', 'Room Management'),
            ('hotels:services', 'fa-concierge-bell', 'Hotel Services'),
            ('hotels:amenities', 'fa-swimming-pool', 'Hotel Amenities'),
            ('hotels:bookings', 'fa-book-open', 'Hotel Bookings'),
            ('hotels:list', 'fa-hotel', 'Browse Hotels'),
            ('landmarks:list', 'fa-landmark', 'Attractions'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    'CONCIERGE': _role(
        'CONCIERGE', 'Concierge', 'fa-bell-concierge', 'SUPPORT',
        'Assist guests with requests and coordinate in-house services.',
        [
            ('hotels:list', 'fa-hotel', 'Browse Hotels'),
            ('hotels:amenities', 'fa-swimming-pool', 'Hotel Amenities'),
            ('restaurants:list', 'fa-utensils', 'Restaurants'),
            ('activities:list', 'fa-hiking', 'Activities'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
        ],
    ),
    'TOUR_GUIDE': _role(
        'TOUR_GUIDE', 'Tour Guide', 'fa-map-signs', 'SUPPORT',
        'Lead tour groups and provide destination information.',
        [
            ('tour_package:list', 'fa-suitcase-rolling', 'Tour Packages'),
            ('activities:list', 'fa-hiking', 'Activities'),
            ('landmarks:list', 'fa-landmark', 'Landmarks'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
        ],
    ),
    'RESTAURANT_STAFF': _role(
        'RESTAURANT_STAFF', 'Restaurant Staff', 'fa-utensil-spoon', 'SUPPORT',
        'Handle restaurant reservations and serve customers.',
        [
            ('restaurants:list', 'fa-utensils', 'Browse Restaurants'),
            ('restaurants:tables', 'fa-chair', 'Restaurant Tables'),
            ('restaurants:bookings', 'fa-book-open', 'Restaurant Reservations'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    'TRANSPORT_STAFF': _role(
        'TRANSPORT_STAFF', 'Transport Staff', 'fa-bus', 'SUPPORT',
        'Coordinate transportation bookings and assist with transfers.',
        [
            ('transportation:list', 'fa-bus', 'Browse Transportation'),
            ('transportation:manage', 'fa-bus-simple', 'Transport Admin'),
            ('transportation:bookings', 'fa-book-open', 'Transport Bookings'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    'CABIN_CREW': _role(
        'CABIN_CREW', 'Cabin Crew', 'fa-user-tie', 'SUPPORT',
        'Manage in-flight service and assist airline passengers.',
        [
            ('airlines:list', 'fa-plane', 'Browse Flights'),
            ('airlines:services', 'fa-concierge-bell', 'Airline Services'),
            ('airlines:bookings', 'fa-book-open', 'Airline Bookings'),
            ('transactions:booking_list', 'fa-bookmark', 'My Bookings'),
            ('transactions:list', 'fa-credit-card', 'My Transactions'),
        ],
    ),
    'AIRLINE_TICKETING_OFFICER': _role(
        'AIRLINE_TICKETING_OFFICER', 'Airline Ticketing Officer',
        'fa-ticket-alt', 'SUPPORT',
        'Retrieve airline reservations, verify payment details and manage ticket issuance.',
        [
            ('airlines:list', 'fa-magnifying-glass', 'Flight Search'),
            ('airlines:bookings', 'fa-book-open', 'Retrieve Reservations'),
        ],
        permissions=[
            'View airline reservation summaries on the dashboard',
            'Search flights and view flight information',
            'Retrieve reservations and review passenger and booking details',
            'Review payment status and issue tickets for confirmed reservations',
            'Manage tickets and process eligible booking changes and cancellations',
        ],
    ),
}
