"""The role catalogue (Section 6.3) as data, in one place.

Every establishment has exactly **three** operational roles, and they are the
same three jobs everywhere:

======================  =================  =====================  =================
establishment           Manager            Reservation            Front Desk
======================  =================  =====================  =================
Airline                 Airline Manager    Airline Reservation    Airline Front Desk /
                                          Agent                 Operations
Hotel                   Hotel Manager      Hotel Reservation      Hotel Front Desk
                                          Officer
Resort                  Resort Manager     Resort Reservation     Resort Front Desk /
                                          Officer                Operations
Restaurant              Restaurant         Restaurant             Restaurant Front Desk /
                        Manager            Reservation Officer    Operations
Staycation              Staycation         Staycation             Staycation Front Desk /
                        Manager            Reservation Officer    Operations
Landmark                Landmark Manager   Landmark Reservation   Landmark Front Desk /
                                          Officer                Operations
Transportation          Transportation     Transportation         Transportation
                        Manager            Reservation Agent      Front Desk / Ops
Tour Operator           Tour Operator      Tour Reservation       Tour Front Desk /
                        Manager            Agent                  Operations
Activity                 Activity Manager    Activity              Activity Front
                                               Reservation Officer   Desk Officer
Tour Package             Tour Package          Tour Package          Tour Package Front
                         Manager              Reservation Officer   Desk Officer
Travel Agency           Travel Agency          Travel Agency          Travel Agency
                         Manager            Reservation Agent      Front Desk / Ops
======================  =================  =====================  =================

Activities use the same separated Manager, Reservation Officer, and Front Desk
roles. Tour Packages have their own package-scoped versions of those roles.

That table is what makes three separate requirements declarative instead of
hard-coded:

* **Section 7.2** - the instructor's establishment picker is driven by
  ``Role.establishment_type``, so selecting "Hotel Manager" immediately reveals
  the hotels and nothing else. Selecting an establishment role *without* an
  establishment is refused by ``SimulationRoleAssignment.clean()`` and by the
  database itself.
* **Section 9.2** - the transaction engine routes a request to whoever holds an
  ACTIVE assignment whose role's ``workflow_stage`` matches the stage the
  request is waiting at. The stage is derived from ``operation_category``, so
  the Manager supervises (and therefore settles simulated billing), the
  Reservation role handles intake, and the Front Desk role fulfils.
* **Section 18** - the permission matrix is generated from ``permissions``.

``sync_roles`` loads this; ``simulation.0006_seed_role_catalogue`` loads it too,
so a fresh database has a usable catalogue without a management command.
"""

from simulation.models import Role

#: (code, label, category, establishment_type, operation_category, sort_order)
#:
#: This is the *offered* catalogue: exactly what an instructor may assign, and
#: nothing else. ``category``/``establishment_type`` use Role's own choices; a
#: None establishment_type marks a role performed without an establishment (the
#: passenger, and the administrative roles).
#: ``workflow_stage`` is not written here - it is derived from
#: ``operation_category`` by
#: :data:`simulation.models.Role.STAGE_FOR_OPERATION_CATEGORY` so the two can
#: never disagree.
#:
#: The row shape is six-wide because ``simulation.0006_seed_role_catalogue``
#: unpacks it positionally; retired roles live in :data:`RETIRED_ROLES` instead
#: of being flagged here.
ROLE_CATALOGUE = [
    # -- Simulation customer / guest roles (no establishment) -----------------
    ('PASSENGER_AIRLINE', 'Passenger - Airline', Role.Category.CUSTOMER, None,
     Role.OperationCategory.CUSTOMER, 10),
    ('GUEST_HOTEL', 'Guest - Hotel', Role.Category.CUSTOMER, None,
     Role.OperationCategory.CUSTOMER, 20),
    ('RESORT_GUEST', 'Guest - Resort', Role.Category.CUSTOMER, None,
     Role.OperationCategory.CUSTOMER, 30),
    ('RESTAURANT_GUEST', 'Guest - Restaurant', Role.Category.CUSTOMER, None,
     Role.OperationCategory.CUSTOMER, 40),
    ('STAYCATION_GUEST', 'Guest - Staycation', Role.Category.CUSTOMER, None,
     Role.OperationCategory.CUSTOMER, 50),
    ('LANDMARK_GUEST', 'Guest - Landmark', Role.Category.CUSTOMER, None,
     Role.OperationCategory.CUSTOMER, 60),
    ('TOUR_GUEST', 'Guest - Tour Package', Role.Category.CUSTOMER, None,
     Role.OperationCategory.CUSTOMER, 70),
    ('PASSENGER_TRANSPORT', 'Passenger - Land Transportation', Role.Category.CUSTOMER,
     None, Role.OperationCategory.CUSTOMER, 80),
    ('ACTIVITY_GUEST', 'Guest - Activity', Role.Category.ACTIVITY, None,
     Role.OperationCategory.CUSTOMER, 90),

    # -- Airline: Manager / Reservation Agent / Front Desk --------------------
    ('AIRLINE_MANAGER', 'Airline Manager', Role.Category.AIRLINE,
     Role.EstablishmentType.AIRLINE, Role.OperationCategory.MANAGER, 210),
    ('AIRLINE_RESERVATION_AGENT', 'Airline Reservation Agent', Role.Category.AIRLINE,
     Role.EstablishmentType.AIRLINE, Role.OperationCategory.RESERVATION, 220),
    ('AIRLINE_FRONT_DESK', 'Airline Front Desk / Operations', Role.Category.AIRLINE,
     Role.EstablishmentType.AIRLINE, Role.OperationCategory.FRONT_DESK, 230),

    # -- Hotel: Manager / Reservation Officer / Front Desk Officer ------------
    ('HOTEL_MANAGER', 'Hotel Manager', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.MANAGER, 110),
    ('HOTEL_RESERVATION_OFFICER', 'Hotel Reservation Officer', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.RESERVATION, 120),
    ('HOTEL_FRONT_DESK', 'Hotel Front Desk Officer', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.FRONT_DESK, 130),

    # -- Transportation: Manager / Reservation Agent / Front Desk -------------
    ('TRANSPORT_MANAGER', 'Transportation Manager', Role.Category.TRANSPORTATION,
     Role.EstablishmentType.TRANSPORTATION, Role.OperationCategory.MANAGER, 510),
    ('TRANSPORT_RESERVATION_AGENT', 'Transportation Reservation Agent',
     Role.Category.TRANSPORTATION, Role.EstablishmentType.TRANSPORTATION,
     Role.OperationCategory.RESERVATION, 520),
    ('TRANSPORT_FRONT_DESK', 'Transportation Front Desk / Operations',
     Role.Category.TRANSPORTATION, Role.EstablishmentType.TRANSPORTATION,
     Role.OperationCategory.FRONT_DESK, 530),

    # -- Tour operation: Manager / Reservation Agent / Front Desk --------------
    ('TOUR_OPERATOR_MANAGER', 'Tour Operator Manager', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.MANAGER, 410),
    ('TOUR_RESERVATION_AGENT', 'Tour Reservation Agent', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.RESERVATION, 420),
    ('TOUR_FRONT_DESK', 'Tour Front Desk / Operations', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.FRONT_DESK, 430),

    # -- Activities: Manager / Reservation Officer / Front Desk --------------
    ('ACTIVITY_MANAGER', 'Activity Manager', Role.Category.ACTIVITY,
     Role.EstablishmentType.ACTIVITY, Role.OperationCategory.MANAGER, 710),
    ('ACTIVITY_RESERVATION_OFFICER', 'Activity Reservation Officer',
     Role.Category.ACTIVITY, Role.EstablishmentType.ACTIVITY,
     Role.OperationCategory.RESERVATION, 720),
    ('ACTIVITY_FRONT_DESK_OFFICER', 'Activity Front Desk Officer',
     Role.Category.ACTIVITY, Role.EstablishmentType.ACTIVITY,
     Role.OperationCategory.FRONT_DESK, 730),
    # -- Tour packages: Manager / Reservation Officer / Front Desk ---------
    ('TOUR_PACKAGE_MANAGER', 'Tour Package Manager', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_PACKAGE, Role.OperationCategory.MANAGER, 740),
    ('TOUR_PACKAGE_RESERVATION_OFFICER', 'Tour Package Reservation Officer',
     Role.Category.TOUR, Role.EstablishmentType.TOUR_PACKAGE,
     Role.OperationCategory.RESERVATION, 750),
    ('TOUR_PACKAGE_FRONT_DESK_OFFICER', 'Tour Package Front Desk Officer',
     Role.Category.TOUR, Role.EstablishmentType.TOUR_PACKAGE,
     Role.OperationCategory.FRONT_DESK, 760),

    # -- Travel agency: Manager / Reservation Agent / Front Desk --------------
    ('TRAVEL_AGENCY_MANAGER', 'Travel Agency Manager', Role.Category.TRAVEL_AGENCY,
     Role.EstablishmentType.TRAVEL_AGENCY, Role.OperationCategory.MANAGER, 310),
    ('TRAVEL_AGENCY_RESERVATION_AGENT', 'Travel Agency Reservation Agent',
     Role.Category.TRAVEL_AGENCY, Role.EstablishmentType.TRAVEL_AGENCY,
     Role.OperationCategory.RESERVATION, 320),
    ('TRAVEL_AGENCY_FRONT_DESK', 'Travel Agency Front Desk / Operations',
     Role.Category.TRAVEL_AGENCY, Role.EstablishmentType.TRAVEL_AGENCY,
     Role.OperationCategory.FRONT_DESK, 330),

    # -- Resort: Manager / Reservation Officer / Front Desk --------------------
    ('RESORT_MANAGER', 'Resort Manager', Role.Category.RESORT,
     Role.EstablishmentType.RESORT, Role.OperationCategory.MANAGER, 140),
    ('RESORT_RESERVATION_OFFICER', 'Resort Reservation Officer', Role.Category.RESORT,
     Role.EstablishmentType.RESORT, Role.OperationCategory.RESERVATION, 150),
    ('RESORT_FRONT_DESK', 'Resort Front Desk / Operations', Role.Category.RESORT,
     Role.EstablishmentType.RESORT, Role.OperationCategory.FRONT_DESK, 160),

    # -- Restaurant: Manager / Reservation Officer / Front Desk ---------------
    ('RESTAURANT_MANAGER', 'Restaurant Manager', Role.Category.RESTAURANT,
     Role.EstablishmentType.RESTAURANT, Role.OperationCategory.MANAGER, 610),
    ('RESTAURANT_RESERVATION_OFFICER', 'Restaurant Reservation Officer',
     Role.Category.RESTAURANT, Role.EstablishmentType.RESTAURANT,
     Role.OperationCategory.RESERVATION, 620),
    ('RESTAURANT_FRONT_DESK', 'Restaurant Front Desk / Operations',
     Role.Category.RESTAURANT, Role.EstablishmentType.RESTAURANT,
     Role.OperationCategory.FRONT_DESK, 630),

    # -- Staycation: Manager / Reservation Officer / Front Desk ---------------
    ('STAYCATION_MANAGER', 'Staycation Manager', Role.Category.STAYCATION,
     Role.EstablishmentType.STAYCATION, Role.OperationCategory.MANAGER, 640),
    ('STAYCATION_RESERVATION_OFFICER', 'Staycation Reservation Officer',
     Role.Category.STAYCATION, Role.EstablishmentType.STAYCATION,
     Role.OperationCategory.RESERVATION, 650),
    ('STAYCATION_FRONT_DESK', 'Staycation Front Desk / Operations',
     Role.Category.STAYCATION, Role.EstablishmentType.STAYCATION,
     Role.OperationCategory.FRONT_DESK, 660),

    # -- Landmark: Manager / Reservation Officer / Front Desk -----------------
    ('LANDMARK_MANAGER', 'Landmark Manager', Role.Category.LANDMARK,
     Role.EstablishmentType.LANDMARK, Role.OperationCategory.MANAGER, 670),
    ('LANDMARK_RESERVATION_OFFICER', 'Landmark Reservation Officer',
     Role.Category.LANDMARK, Role.EstablishmentType.LANDMARK,
     Role.OperationCategory.RESERVATION, 680),
    ('LANDMARK_FRONT_DESK', 'Landmark Front Desk / Operations',
     Role.Category.LANDMARK, Role.EstablishmentType.LANDMARK,
     Role.OperationCategory.FRONT_DESK, 690),

    # -- Billing and establishment owners ----------------------------------
    ('BILLING_OFFICER', 'Billing Officer', Role.Category.ADMIN, None,
     Role.OperationCategory.BILLING, 800),
    ('HOTEL_OWNER', 'Hotel Owner', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.MANAGER, 810),
    ('RESORT_OWNER', 'Resort Owner', Role.Category.RESORT,
     Role.EstablishmentType.RESORT, Role.OperationCategory.MANAGER, 820),
    ('RESTAURANT_OWNER', 'Restaurant Owner', Role.Category.RESTAURANT,
     Role.EstablishmentType.RESTAURANT, Role.OperationCategory.MANAGER, 830),
    ('STAYCATION_OWNER', 'Staycation Owner', Role.Category.STAYCATION,
     Role.EstablishmentType.STAYCATION, Role.OperationCategory.MANAGER, 840),
    ('LANDMARK_OWNER', 'Landmark Owner', Role.Category.LANDMARK,
     Role.EstablishmentType.LANDMARK, Role.OperationCategory.MANAGER, 850),
    ('AIRLINE_OWNER', 'Airline Owner', Role.Category.AIRLINE,
     Role.EstablishmentType.AIRLINE, Role.OperationCategory.MANAGER, 860),
    ('TRAVEL_AGENCY_OWNER', 'Travel Agency Owner', Role.Category.TRAVEL_AGENCY,
     Role.EstablishmentType.TRAVEL_AGENCY, Role.OperationCategory.MANAGER, 870),
    ('TOUR_OPERATOR_OWNER', 'Tour Operator Owner', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.MANAGER, 880),
    ('TOUR_PACKAGE_OWNER', 'Tour Package Owner', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_PACKAGE, Role.OperationCategory.MANAGER, 890),
    ('ACTIVITY_OWNER', 'Activity Owner', Role.Category.ACTIVITY,
     Role.EstablishmentType.ACTIVITY, Role.OperationCategory.MANAGER, 900),
    ('TRANSPORTATION_OWNER', 'Transportation Owner', Role.Category.TRANSPORTATION,
     Role.EstablishmentType.TRANSPORTATION, Role.OperationCategory.MANAGER, 910),

    # -- Administrative ------------------------------------------------------
    ('INSTRUCTOR', 'Instructor', Role.Category.ADMIN, None, '', 900),
    ('SYSTEM_ADMINISTRATOR', 'System Administrator', Role.Category.ADMIN, None, '',
     910),
]

#: Roles that have been folded into one of the three operational roles above.
#:
#: Same six-wide shape, but these rows are created ``is_active=False`` and are
#: never offered to an instructor. They are *not* deleted, because an assignment
#: that already names one must keep resolving to a real ``Role`` row so the
#: student can still finish the work they started.
#: ``LEGACY_OPERATION_CATEGORY`` in simulation/models.py maps each code to the
#: category its work now sits in, so an in-flight transaction is still routed.
RETIRED_ROLES = [
    ('CUSTOMER_TOUR', 'Customer - Tour (retired)', Role.Category.TOUR, None,
     Role.OperationCategory.CUSTOMER, 1020),
    ('TOUR_MANAGER', 'Tour Manager (retired)', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.MANAGER, 1030),
    ('TOUR_COORDINATOR', 'Tour Coordinator (retired)', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.RESERVATION, 1040),
    ('TOUR_GUIDE', 'Tour Guide (retired)', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.FRONT_DESK, 1050),
    ('TOUR_OPERATOR', 'Tour Operator (retired)', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.FRONT_DESK, 1060),
    ('HOTEL_BILLING_OFFICER', 'Hotel Billing Officer (retired)', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.MANAGER, 1080),
    ('AIRLINE_BILLING_OFFICER', 'Airline Billing Officer (retired)',
     Role.Category.AIRLINE, Role.EstablishmentType.AIRLINE,
     Role.OperationCategory.MANAGER, 1090),
    ('TRANSPORT_BILLING_OFFICER', 'Transportation Billing Officer (retired)',
     Role.Category.TRANSPORTATION, Role.EstablishmentType.TRANSPORTATION,
     Role.OperationCategory.MANAGER, 1100),
    ('TOUR_BILLING_OFFICER', 'Tour Billing Officer (retired)', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_OPERATOR, Role.OperationCategory.MANAGER, 1110),
    ('TRAVEL_AGENCY_BILLING_OFFICER', 'Travel Agency Billing Officer (retired)',
     Role.Category.TRAVEL_AGENCY, Role.EstablishmentType.TRAVEL_AGENCY,
     Role.OperationCategory.MANAGER, 1120),
    ('HOUSEKEEPING_OFFICER', 'Housekeeping Officer (retired)', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.FRONT_DESK, 1130),
    ('RECEPTIONIST', 'Receptionist (retired)', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.FRONT_DESK, 1140),
    ('CONCIERGE', 'Concierge (retired)', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.FRONT_DESK, 1150),
    ('FRONT_DESK', 'Front Desk Officer (retired)', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.FRONT_DESK, 1160),
    ('BOOKING_AGENT', 'Booking Agent (retired)', Role.Category.HOTEL,
     Role.EstablishmentType.HOTEL, Role.OperationCategory.RESERVATION, 1170),
    ('AIRLINE_TICKETING_OFFICER', 'Airline Ticketing Officer (retired)',
     Role.Category.AIRLINE, Role.EstablishmentType.AIRLINE,
     Role.OperationCategory.FRONT_DESK, 1180),
    ('AIRLINE_CUSTOMER_SERVICE', 'Airline Customer Service Officer (retired)',
     Role.Category.AIRLINE, Role.EstablishmentType.AIRLINE,
     Role.OperationCategory.FRONT_DESK, 1190),
    ('AIRLINE_SUPERVISOR', 'Airline Supervisor (retired)', Role.Category.AIRLINE,
     Role.EstablishmentType.AIRLINE, Role.OperationCategory.MANAGER, 1200),
    ('CABIN_CREW', 'Cabin Crew (retired)', Role.Category.AIRLINE,
     Role.EstablishmentType.AIRLINE, Role.OperationCategory.FRONT_DESK, 1210),
    ('TRANSPORT_RESERVATION_OFFICER', 'Transportation Reservation Officer (retired)',
     Role.Category.TRANSPORTATION, Role.EstablishmentType.TRANSPORTATION,
     Role.OperationCategory.RESERVATION, 1220),
    ('TRANSPORT_DISPATCHER', 'Transportation Dispatcher (retired)',
     Role.Category.TRANSPORTATION, Role.EstablishmentType.TRANSPORTATION,
     Role.OperationCategory.FRONT_DESK, 1230),
    ('TRANSPORT_STAFF', 'Transport Staff (retired)', Role.Category.TRANSPORTATION,
     Role.EstablishmentType.TRANSPORTATION, Role.OperationCategory.FRONT_DESK, 1240),
    ('TRAVEL_AGENCY_RESERVATION_OFFICER',
     'Travel Agency Reservation Officer (retired)', Role.Category.TRAVEL_AGENCY,
     Role.EstablishmentType.TRAVEL_AGENCY, Role.OperationCategory.RESERVATION, 1250),
    ('TRAVEL_CONSULTANT', 'Travel Consultant (retired)',
     Role.Category.TRAVEL_AGENCY, Role.EstablishmentType.TRAVEL_AGENCY,
     Role.OperationCategory.RESERVATION, 1260),
    ('RESTAURANT_STAFF', 'Restaurant Staff (retired)', Role.Category.ADMIN, None,
     Role.OperationCategory.FRONT_DESK, 1270),
    # The former Activity Operator and Tour Package Operator remain readable
    # for existing assignments, but new assignments use the distinct roles above.
    ('ACTIVITY_OPERATOR', 'Activity / Tour Operator (retired)',
     Role.Category.ACTIVITY, Role.EstablishmentType.ACTIVITY,
     Role.OperationCategory.FRONT_DESK, 1410),
    ('TOUR_PACKAGE_OPERATOR', 'Tour Operator (legacy)', Role.Category.TOUR,
     Role.EstablishmentType.TOUR_PACKAGE, Role.OperationCategory.FRONT_DESK, 1430),
]

#: Historical alias: older imports and the 0006 data migration use this name.
ROLE_CATALOGUE_ROWS = ROLE_CATALOGUE
ACTIVITY_ROLE_CODES = frozenset({
    'ACTIVITY_GUEST',
    'ACTIVITY_MANAGER',
    'ACTIVITY_RESERVATION_OFFICER',
    'ACTIVITY_FRONT_DESK_OFFICER',
    'ACTIVITY_OPERATOR',
})

#: The three operational categories, in workflow order.
OPERATIONAL_CATEGORIES = (
    Role.OperationCategory.MANAGER,
    Role.OperationCategory.RESERVATION,
    Role.OperationCategory.FRONT_DESK,
)

#: The operational categories every establishment type must have, keyed by the
#: ``Role.EstablishmentType``.
REQUIRED_OPERATIONAL_CATEGORIES = {
    Role.EstablishmentType.ACTIVITY: (
        Role.OperationCategory.MANAGER,
        Role.OperationCategory.RESERVATION,
        Role.OperationCategory.FRONT_DESK,
    ),
    Role.EstablishmentType.TOUR_PACKAGE: (
        Role.OperationCategory.MANAGER,
        Role.OperationCategory.RESERVATION,
        Role.OperationCategory.FRONT_DESK,
    ),
}


def _permissions_for_category(category):
    """The permission lists, shaped for the job rather than the establishment.

    The Manager's list is the broadest because a Manager supervises every stage
    (including simulated billing); the two operational lists differ only in
    whether they settle payments; the customer list is about booking rather than
    operating.
    """
    manager = [
        'Manage only the assigned establishment: its information, inventory, '
        'rates and availability',
        'Supervise the reservation and front desk roles at the same establishment',
        'Approve, reject, cancel and forward the establishment\'s transactions',
        'Record simulated payments and review the establishment\'s transactions',
    ]
    reservation = [
        'View only the reservations belonging to the assigned establishment',
        'Check availability and verify the reservation details',
        'Claim a reservation, then approve or reject it',
        'Forward an approved reservation to front desk / operations or to billing',
    ]
    front_desk = [
        'View confirmed reservations for the assigned establishment',
        'Verify the establishment and its availability against the reservation',
        'Record guest arrival, fulfilment and departure (check-in, dispatch, ticketing)',
        'Update the operational status of the establishment and its bookings',
    ]
    customer = [
        'Search the platform\'s offerings as a customer',
        'Submit reservation requests to an establishment',
        'View the status of their own requests',
        'Cancel or amend an eligible request',
    ]
    admin = [
        'Supervise simulation sessions and the students inside them',
        'Assign and retire student roles',
        'Review every session\'s transactions for compliance',
    ]
    return {
        Role.OperationCategory.MANAGER: manager,
        Role.OperationCategory.RESERVATION: reservation,
        Role.OperationCategory.FRONT_DESK: front_desk,
        Role.OperationCategory.BILLING: [
            'Review paid bookings in the assigned simulation session',
            'Verify payment records before reservation confirmation',
        ],
        Role.OperationCategory.CUSTOMER: customer,
        '': admin,
    }.get(category, [])


def all_entries():
    """Offered roles followed by retired ones: the full set of rows to sync."""
    return list(ROLE_CATALOGUE) + list(RETIRED_ROLES)


def permissions_for(code):
    """The Section 18 permission matrix as data.

    Reads the catalogue row for ``code`` rather than keeping a second hand-
    maintained list, so a role's permissions cannot drift from the role itself.
    Retired codes are included: their rows still exist and still describe a job.
    """
    row = next((entry for entry in all_entries() if entry[0] == code), None)
    if row is None:
        return []
    if code == 'ACTIVITY_MANAGER':
        return [
            'Manage only activities assigned to this account',
            'Manage activity details, schedules, prices, capacity and availability',
        ]
    if code == 'ACTIVITY_RESERVATION_OFFICER':
        return [
            'View only bookings for assigned activities',
            'Confirm or reject bookings for assigned activities',
            'Update reservation records within the booking workflow',
        ]
    if code == 'ACTIVITY_FRONT_DESK_OFFICER':
        return [
            'View only bookings for assigned activities',
            'Verify confirmed bookings and record guest arrival and check-in',
        ]
    if code == 'TOUR_PACKAGE_MANAGER':
        return [
            'Manage only tour packages assigned to this account',
            'Manage package details, included hotels, schedules, pricing and availability',
        ]
    if code == 'TOUR_PACKAGE_RESERVATION_OFFICER':
        return [
            'View only bookings for assigned tour packages',
            'Confirm or reject bookings for assigned tour packages',
        ]
    if code in {'TOUR_PACKAGE_FRONT_DESK_OFFICER', 'TOUR_PACKAGE_OPERATOR'}:
        return [
            'View only bookings for assigned tour packages',
            'Record guest arrival and complete assigned package bookings',
        ]
    return _permissions_for_category(row[4])


def active_entries():
    """The catalogue rows an instructor may assign, in display order.

    Administrative accounts are excluded: an instructor runs a simulation, they
    do not hand out platform administration as a role to practise. The rows stay
    in :data:`ROLE_CATALOGUE` (and stay active in the database) so an existing
    ``Instructor`` assignment still resolves, but they are off the assign form
    and refused by the assign view.
    """
    return [entry for entry in ROLE_CATALOGUE
            if entry[2] != Role.Category.ADMIN or entry[0] == 'BILLING_OFFICER']


def missing_active_codes():
    """Offered codes the ``Role`` table does not (yet) hold as an active row.

    The catalogue is the source of truth for *what a role is*; the ``Role`` table
    is what an assignment can point at, because ``SimulationRoleAssignment``
    stores the role twice (a code and a foreign key). Anything that reads one and
    compares it against the other has to know about the gap, or it will offer a
    role the backend then refuses.
    """
    codes = [entry[0] for entry in active_entries()]
    present = set(
        Role.objects.filter(code__in=codes, is_active=True).values_list('code', flat=True))
    return [code for code in codes if code not in present]


def active_codes():
    return [entry[0] for entry in active_entries()]


def retired_codes():
    return [entry[0] for entry in RETIRED_ROLES]


def operational_codes_for(establishment_type):
    """The (manager, reservation, front desk) codes of one establishment type."""
    return [entry[0] for entry in active_entries()
            if entry[3] == establishment_type and entry[4] in OPERATIONAL_CATEGORIES
            and not entry[0].endswith('_OWNER')]


def sync_roles():
    """Create/update every catalogue row and retire codes that vanished.

    Returns ``(created, updated, deactivated)``. Safe to run repeatedly, which
    is what the data migration and the ``seed_roles`` command both rely on.

    Retiring means ``is_active = False``, never a delete: an assignment that
    already names a retired role must keep resolving to its row so the student
    can still finish the work they started.
    """
    created = updated = deactivated = 0
    for entry in all_entries():
        code, name, category, establishment_type, operation_category, order = entry[:6]
        defaults = {
            'name': name,
            'category': category,
            'establishment_type': establishment_type,
            'operation_category': operation_category,
            'requires_establishment': establishment_type is not None or code == 'BILLING_OFFICER',
            'workflow_stage': Role.STAGE_FOR_OPERATION_CATEGORY.get(
                operation_category, Role.WorkflowStage.INTAKE),
            'sort_order': order,
            'permissions': permissions_for(code),
            'is_active': entry in ROLE_CATALOGUE,
        }
        role = Role.objects.filter(code=code).first()
        if role is None:
            Role.objects.create(code=code, **defaults)
            created += 1
            continue
        changed = False
        for field, value in defaults.items():
            if getattr(role, field) != value:
                setattr(role, field, value)
                changed = True
        if changed:
            role.save()
            updated += 1
    known = {entry[0] for entry in all_entries()}
    deactivated += Role.objects.exclude(code__in=known).filter(is_active=True).update(
        is_active=False)
    return created, updated, deactivated


def sync_activity_roles():
    """Synchronize only Activity roles when the assign form repairs its catalogue."""
    created = updated = 0
    for entry in all_entries():
        code, name, category, establishment_type, operation_category, order = entry[:6]
        if code not in ACTIVITY_ROLE_CODES:
            continue
        defaults = {
            'name': name,
            'category': category,
            'establishment_type': establishment_type,
            'operation_category': operation_category,
            'requires_establishment': establishment_type is not None or code == 'BILLING_OFFICER',
            'workflow_stage': Role.STAGE_FOR_OPERATION_CATEGORY.get(
                operation_category, Role.WorkflowStage.INTAKE),
            'sort_order': order,
            'permissions': permissions_for(code),
            'is_active': entry in ROLE_CATALOGUE,
        }
        role = Role.objects.filter(code=code).first()
        if role is None:
            Role.objects.create(code=code, **defaults)
            created += 1
        else:
            changed = []
            for field, value in defaults.items():
                if getattr(role, field) != value:
                    setattr(role, field, value)
                    changed.append(field)
            if changed:
                role.save(update_fields=changed)
                updated += 1
    return created, updated


#: Historical name. The seeding command and the 0006 data migration both call
#: this, so the old spelling stays as the real implementation.
sync_role_catalogue = sync_roles
