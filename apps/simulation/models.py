from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db import models
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.utils import timezone


BILLING_OFFICER_ROLE_CODES = (
    'HOTEL_BILLING_OFFICER', 'RESORT_BILLING_OFFICER',
    'RESTAURANT_BILLING_OFFICER', 'STAYCATION_BILLING_OFFICER',
    'LANDMARK_BILLING_OFFICER', 'AIRLINE_BILLING_OFFICER',
    'TRAVEL_AGENCY_BILLING_OFFICER', 'TOUR_OPERATOR_BILLING_OFFICER',
    'TOUR_PACKAGE_BILLING_OFFICER', 'ACTIVITY_BILLING_OFFICER',
    'TRANSPORT_BILLING_OFFICER',
    # Kept scoped for pre-migration assignments; new assignments use the
    # explicitly named TOUR_OPERATOR_BILLING_OFFICER role.
    'TOUR_BILLING_OFFICER',
)


#: Legacy role code -> its operation category, for assignments that predate
#: ``Role.operation_category``. Without this an old row would route nowhere.
#: Written as plain strings on purpose: this table sits above both model classes,
#: so referring to their enums here would be a forward reference at import time.
#: The values are exactly ``Role.OperationCategory``'s choices.
LEGACY_OPERATION_CATEGORY = {
    'HOTEL_MANAGER': 'MANAGER',
    'AIRLINE_SUPERVISOR': 'MANAGER',
    'TRANSPORT_MANAGER': 'MANAGER',
    'TOUR_MANAGER': 'MANAGER',
    'TRAVEL_AGENCY_MANAGER': 'MANAGER',
    'BILLING_OFFICER': 'MANAGER',
    'HOTEL_BILLING_OFFICER': 'MANAGER',
    'AIRLINE_BILLING_OFFICER': 'MANAGER',
    'TRANSPORT_BILLING_OFFICER': 'MANAGER',
    'TOUR_BILLING_OFFICER': 'MANAGER',
    'TRAVEL_AGENCY_BILLING_OFFICER': 'MANAGER',
    'TOUR_PACKAGE_MANAGER': 'MANAGER',
    'ACTIVITY_MANAGER': 'MANAGER',
    'TOUR_PACKAGE_FRONT_DESK_OFFICER': 'FRONT_DESK',
    'ACTIVITY_FRONT_DESK_OFFICER': 'FRONT_DESK',
    'HOTEL_RESERVATION_OFFICER': 'RESERVATION',
    'AIRLINE_RESERVATION_AGENT': 'RESERVATION',
    'TRANSPORT_RESERVATION_OFFICER': 'RESERVATION',
    'TRAVEL_AGENCY_RESERVATION_OFFICER': 'RESERVATION',
    'TOUR_COORDINATOR': 'RESERVATION',
    'TRAVEL_CONSULTANT': 'RESERVATION',
    'BOOKING_AGENT': 'RESERVATION',
    'FRONT_DESK': 'FRONT_DESK',
    'RECEPTIONIST': 'FRONT_DESK',
    'CONCIERGE': 'FRONT_DESK',
    'HOUSEKEEPING_OFFICER': 'FRONT_DESK',
    'AIRLINE_TICKETING_OFFICER': 'FRONT_DESK',
    'AIRLINE_CUSTOMER_SERVICE': 'FRONT_DESK',
    'CABIN_CREW': 'FRONT_DESK',
    'TRANSPORT_DISPATCHER': 'FRONT_DESK',
    'TRANSPORT_STAFF': 'FRONT_DESK',
    'TOUR_GUIDE': 'FRONT_DESK',
    'TOUR_OPERATOR': 'FRONT_DESK',
    'RESTAURANT_STAFF': 'FRONT_DESK',
    'GUEST_HOTEL': 'CUSTOMER',
    'CUSTOMER_TOUR': 'CUSTOMER',
    'PASSENGER_AIRLINE': 'CUSTOMER',
}


class SimulationRoleAssignment(models.Model):
    """Instructor-managed assignment of simulation roles (BR-082, BR-083).

    An assignment is one student's slot inside a simulation session. The
    session is identified by ``activity_name``, a free-text title the
    instructor creates per session ("Activity 1", "Midterm Simulation"); it
    groups students but never decides anything about them. Each assignment
    independently carries the role performed, the establishment it happens at
    (``hotel``, for hotel roles) and the window it is allowed to run in
    (``simulation_date``/``start_time``/``end_time``), so any number of students
    can share one session name while holding their own role, venue and schedule.
    """

    class Role(models.TextChoices):
        # -- BR-083 supported roles -----------------------------------------
        GUEST_HOTEL = 'GUEST_HOTEL', 'Guest – Hotel'
        PASSENGER_AIRLINE = 'PASSENGER_AIRLINE', 'Passenger – Airline'
        CUSTOMER_TOUR = 'CUSTOMER_TOUR', 'Customer – Tour'
        RESORT_GUEST = 'RESORT_GUEST', 'Guest – Resort'
        RESTAURANT_GUEST = 'RESTAURANT_GUEST', 'Guest – Restaurant'
        STAYCATION_GUEST = 'STAYCATION_GUEST', 'Guest – Staycation'
        LANDMARK_GUEST = 'LANDMARK_GUEST', 'Guest – Landmark'
        TOUR_GUEST = 'TOUR_GUEST', 'Guest – Tour Package'
        PASSENGER_TRANSPORT = 'PASSENGER_TRANSPORT', 'Passenger – Land Transportation'
        ACTIVITY_GUEST = 'ACTIVITY_GUEST', 'Guest – Activity'
        # -- The three operational roles of every establishment --------------
        # Airline
        AIRLINE_MANAGER = 'AIRLINE_MANAGER', 'Airline Manager'
        AIRLINE_RESERVATION_AGENT = 'AIRLINE_RESERVATION_AGENT', 'Airline Reservation Agent'
        AIRLINE_FRONT_DESK = 'AIRLINE_FRONT_DESK', 'Airline Front Desk / Operations'
        # Hotel
        HOTEL_MANAGER = 'HOTEL_MANAGER', 'Hotel Manager'
        HOTEL_RESERVATION_OFFICER = 'HOTEL_RESERVATION_OFFICER', 'Hotel Reservation Officer'
        HOTEL_FRONT_DESK = 'HOTEL_FRONT_DESK', 'Hotel Front Desk Officer'
        # Transportation
        TRANSPORT_MANAGER = 'TRANSPORT_MANAGER', 'Transportation Manager'
        TRANSPORT_RESERVATION_AGENT = 'TRANSPORT_RESERVATION_AGENT', 'Transportation Reservation Agent'
        TRANSPORT_FRONT_DESK = 'TRANSPORT_FRONT_DESK', 'Transportation Front Desk / Operations'
        # Tour operation
        TOUR_OPERATOR_MANAGER = 'TOUR_OPERATOR_MANAGER', 'Tour Operator Manager'
        TOUR_RESERVATION_AGENT = 'TOUR_RESERVATION_AGENT', 'Tour Reservation Agent'
        TOUR_FRONT_DESK = 'TOUR_FRONT_DESK', 'Tour Front Desk / Operations'
        # Tour Package roles are assigned to a specific package.
        TOUR_PACKAGE_MANAGER = 'TOUR_PACKAGE_MANAGER', 'Tour Package Manager'
        TOUR_PACKAGE_RESERVATION_OFFICER = (
            'TOUR_PACKAGE_RESERVATION_OFFICER', 'Tour Package Reservation Officer')
        TOUR_PACKAGE_FRONT_DESK_OFFICER = (
            'TOUR_PACKAGE_FRONT_DESK_OFFICER', 'Tour Package Front Desk Officer')
        ACTIVITY_MANAGER = 'ACTIVITY_MANAGER', 'Activity Manager'
        ACTIVITY_RESERVATION_OFFICER = (
            'ACTIVITY_RESERVATION_OFFICER', 'Activity Reservation Officer')
        ACTIVITY_FRONT_DESK_OFFICER = (
            'ACTIVITY_FRONT_DESK_OFFICER', 'Activity Front Desk Officer')
        ACTIVITY_OPERATOR = 'ACTIVITY_OPERATOR', 'Activity / Tour Operator (legacy)'
        # Travel agency
        TRAVEL_AGENCY_MANAGER = 'TRAVEL_AGENCY_MANAGER', 'Travel Agency Manager'
        TRAVEL_AGENCY_RESERVATION_AGENT = 'TRAVEL_AGENCY_RESERVATION_AGENT', 'Travel Agency Reservation Agent'
        TRAVEL_AGENCY_FRONT_DESK = 'TRAVEL_AGENCY_FRONT_DESK', 'Travel Agency Front Desk / Operations'
        # Resort
        RESORT_MANAGER = 'RESORT_MANAGER', 'Resort Manager'
        RESORT_RESERVATION_OFFICER = 'RESORT_RESERVATION_OFFICER', 'Resort Reservation Officer'
        RESORT_FRONT_DESK = 'RESORT_FRONT_DESK', 'Resort Front Desk / Operations'
        # Restaurant
        RESTAURANT_MANAGER = 'RESTAURANT_MANAGER', 'Restaurant Manager'
        RESTAURANT_RESERVATION_OFFICER = 'RESTAURANT_RESERVATION_OFFICER', 'Restaurant Reservation Officer'
        RESTAURANT_FRONT_DESK = 'RESTAURANT_FRONT_DESK', 'Restaurant Front Desk / Operations'
        # Staycation
        STAYCATION_MANAGER = 'STAYCATION_MANAGER', 'Staycation Manager'
        STAYCATION_RESERVATION_OFFICER = 'STAYCATION_RESERVATION_OFFICER', 'Staycation Reservation Officer'
        STAYCATION_FRONT_DESK = 'STAYCATION_FRONT_DESK', 'Staycation Front Desk / Operations'
        # Landmark
        LANDMARK_MANAGER = 'LANDMARK_MANAGER', 'Landmark Manager'
        LANDMARK_RESERVATION_OFFICER = 'LANDMARK_RESERVATION_OFFICER', 'Landmark Reservation Officer'
        LANDMARK_FRONT_DESK = 'LANDMARK_FRONT_DESK', 'Landmark Front Desk / Operations'
        HOTEL_OWNER = 'HOTEL_OWNER', 'Hotel Owner'
        RESORT_OWNER = 'RESORT_OWNER', 'Resort Owner'
        RESTAURANT_OWNER = 'RESTAURANT_OWNER', 'Restaurant Owner'
        STAYCATION_OWNER = 'STAYCATION_OWNER', 'Staycation Owner'
        LANDMARK_OWNER = 'LANDMARK_OWNER', 'Landmark Owner'
        AIRLINE_OWNER = 'AIRLINE_OWNER', 'Airline Owner'
        TRAVEL_AGENCY_OWNER = 'TRAVEL_AGENCY_OWNER', 'Travel Agency Owner'
        TOUR_OPERATOR_OWNER = 'TOUR_OPERATOR_OWNER', 'Tour Operator Owner'
        TOUR_PACKAGE_OWNER = 'TOUR_PACKAGE_OWNER', 'Tour Package Owner'
        ACTIVITY_OWNER = 'ACTIVITY_OWNER', 'Activity Owner'
        TRANSPORTATION_OWNER = 'TRANSPORTATION_OWNER', 'Transportation Owner'
        BILLING_OFFICER = 'BILLING_OFFICER', 'Billing Officer (legacy)'
        # -- Section 6.3 roles retained for existing data --------------------
        # These are no longer offered: every establishment role is one of the
        # three above. The members stay so assignments and screens that still
        # read an older row keep working; ``Role.is_active`` is what retires
        # them from the catalogue.
        TOUR_MANAGER = 'TOUR_MANAGER', 'Tour Manager (legacy)'
        TOUR_COORDINATOR = 'TOUR_COORDINATOR', 'Tour Coordinator (legacy)'
        HOTEL_BILLING_OFFICER = 'HOTEL_BILLING_OFFICER', 'Hotel Billing Officer'
        HOUSEKEEPING_OFFICER = 'HOUSEKEEPING_OFFICER', 'Housekeeping Officer (legacy)'
        AIRLINE_TICKETING_OFFICER = 'AIRLINE_TICKETING_OFFICER', 'Airline Ticketing Officer (legacy)'
        AIRLINE_CUSTOMER_SERVICE = 'AIRLINE_CUSTOMER_SERVICE', 'Airline Customer Service Officer (legacy)'
        AIRLINE_SUPERVISOR = 'AIRLINE_SUPERVISOR', 'Airline Supervisor (legacy)'
        AIRLINE_BILLING_OFFICER = 'AIRLINE_BILLING_OFFICER', 'Airline Billing Officer'
        TRAVEL_AGENCY_RESERVATION_OFFICER = 'TRAVEL_AGENCY_RESERVATION_OFFICER', 'Travel Agency Reservation Officer (legacy)'
        TRAVEL_AGENCY_BILLING_OFFICER = 'TRAVEL_AGENCY_BILLING_OFFICER', 'Travel Agency Billing Officer'
        TOUR_OPERATOR = 'TOUR_OPERATOR', 'Tour Operator (legacy)'
        TOUR_BILLING_OFFICER = 'TOUR_BILLING_OFFICER', 'Tour Billing Officer (legacy)'
        TRANSPORT_RESERVATION_OFFICER = 'TRANSPORT_RESERVATION_OFFICER', 'Transportation Reservation Officer (legacy)'
        TRANSPORT_DISPATCHER = 'TRANSPORT_DISPATCHER', 'Transportation Dispatcher (legacy)'
        TRANSPORT_BILLING_OFFICER = 'TRANSPORT_BILLING_OFFICER', 'Transportation Billing Officer'
        RESORT_BILLING_OFFICER = 'RESORT_BILLING_OFFICER', 'Resort Billing Officer'
        RESTAURANT_BILLING_OFFICER = 'RESTAURANT_BILLING_OFFICER', 'Restaurant Billing Officer'
        STAYCATION_BILLING_OFFICER = 'STAYCATION_BILLING_OFFICER', 'Staycation Billing Officer'
        LANDMARK_BILLING_OFFICER = 'LANDMARK_BILLING_OFFICER', 'Landmark Billing Officer'
        TOUR_OPERATOR_BILLING_OFFICER = 'TOUR_OPERATOR_BILLING_OFFICER', 'Tour Operator Billing Officer'
        TOUR_PACKAGE_BILLING_OFFICER = 'TOUR_PACKAGE_BILLING_OFFICER', 'Tour Package Billing Officer'
        ACTIVITY_BILLING_OFFICER = 'ACTIVITY_BILLING_OFFICER', 'Activity Billing Officer'
        TRAVEL_CONSULTANT = 'TRAVEL_CONSULTANT', 'Travel Consultant (legacy)'
        # Administrative
        INSTRUCTOR = 'INSTRUCTOR', 'Instructor'
        SYSTEM_ADMINISTRATOR = 'SYSTEM_ADMINISTRATOR', 'System Administrator'
        # Legacy simulation roles retained for existing data
        RECEPTIONIST = 'RECEPTIONIST', 'Receptionist (legacy)'
        BOOKING_AGENT = 'BOOKING_AGENT', 'Booking Agent (legacy)'
        FRONT_DESK = 'FRONT_DESK', 'Front Desk Officer (legacy)'
        CONCIERGE = 'CONCIERGE', 'Concierge (legacy)'
        TOUR_GUIDE = 'TOUR_GUIDE', 'Tour Guide (legacy)'
        # The pre-resource activity / tour package roles, superseded by the
        # Reservation Officer + Operator pair for each resource.
        TOUR_PACKAGE_OPERATOR = 'TOUR_PACKAGE_OPERATOR', 'Tour Operator (legacy)'
        RESTAURANT_STAFF = 'RESTAURANT_STAFF', 'Restaurant Staff (legacy)'
        TRANSPORT_STAFF = 'TRANSPORT_STAFF', 'Transport Staff (legacy)'
        CABIN_CREW = 'CABIN_CREW', 'Cabin Crew (legacy)'

    #: The three operational role codes per establishment type, as the
    #: ``(manager, reservation, front desk)`` tuple. This is the whole
    #: operational role structure of the simulation in one place.
    OPERATIONAL_ROLE_CODES = {
        Role.HOTEL_MANAGER: 'HOTEL',
        Role.HOTEL_RESERVATION_OFFICER: 'HOTEL',
        Role.HOTEL_FRONT_DESK: 'HOTEL',
        Role.AIRLINE_MANAGER: 'AIRLINE',
        Role.AIRLINE_RESERVATION_AGENT: 'AIRLINE',
        Role.AIRLINE_FRONT_DESK: 'AIRLINE',
        Role.TRANSPORT_MANAGER: 'TRANSPORTATION',
        Role.TRANSPORT_RESERVATION_AGENT: 'TRANSPORTATION',
        Role.TRANSPORT_FRONT_DESK: 'TRANSPORTATION',
        Role.TOUR_OPERATOR_MANAGER: 'TOUR_OPERATOR',
        Role.TOUR_RESERVATION_AGENT: 'TOUR_OPERATOR',
        Role.TOUR_FRONT_DESK: 'TOUR_OPERATOR',
        Role.TRAVEL_AGENCY_MANAGER: 'TRAVEL_AGENCY',
        Role.TRAVEL_AGENCY_RESERVATION_AGENT: 'TRAVEL_AGENCY',
        Role.TRAVEL_AGENCY_FRONT_DESK: 'TRAVEL_AGENCY',
        Role.RESORT_MANAGER: 'RESORT',
        Role.RESORT_RESERVATION_OFFICER: 'RESORT',
        Role.RESORT_FRONT_DESK: 'RESORT',
        Role.RESTAURANT_MANAGER: 'RESTAURANT',
        Role.RESTAURANT_RESERVATION_OFFICER: 'RESTAURANT',
        Role.RESTAURANT_FRONT_DESK: 'RESTAURANT',
        Role.STAYCATION_MANAGER: 'STAYCATION',
        Role.STAYCATION_RESERVATION_OFFICER: 'STAYCATION',
        Role.STAYCATION_FRONT_DESK: 'STAYCATION',
        Role.LANDMARK_MANAGER: 'LANDMARK',
        Role.LANDMARK_RESERVATION_OFFICER: 'LANDMARK',
        Role.LANDMARK_FRONT_DESK: 'LANDMARK',
        Role.ACTIVITY_MANAGER: 'ACTIVITY',
        Role.ACTIVITY_RESERVATION_OFFICER: 'ACTIVITY',
        Role.ACTIVITY_FRONT_DESK_OFFICER: 'ACTIVITY',
    }

    class AssignmentStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        DONE = 'DONE', 'Done'
        INACTIVE = 'INACTIVE', 'Inactive'

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='simulation_roles'
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_roles'
    )
    role = models.CharField(max_length=40, choices=Role.choices)
    #: Instructor-created session name, e.g. "Activity 1". Free text on purpose:
    #: it is the instructor's own label for the session, shared by every
    #: student in it, and carries no meaning of its own.
    activity_name = models.CharField(max_length=150)
    #: Where a hotel-role student performs the role. Null for roles that are
    #: not tied to an establishment.
    hotel = models.ForeignKey(
        'hotels.Hotel', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='simulation_assignments'
    )
    simulation_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: When the assignment was marked :attr:`AssignmentStatus.DONE` - i.e. when
    #: the student successfully performed the role's required action. Null until
    #: then; never cleared once set.
    completed_at = models.DateTimeField(null=True, blank=True)

    # ------------------------------------------------------------------ #
    # Section 6 / 7 additions.
    #
    # The three fields above predate the simulation-session architecture and are
    # still what the existing pages and ``accounts.roles`` read, so they are kept
    # and mirrored rather than replaced:
    #
    #   activity_name -> session.name   (the free-text label is preserved on the
    #                                    session; the legacy column stays so the
    #                                    older templates keep working)
    #   role          -> Role.code      (see ``role_ref``)
    #   hotel         -> Establishment   (see ``establishment``)
    # ------------------------------------------------------------------ #

    #: The simulation session this assignment belongs to (Section 5.2 rule 4:
    #: "Role assignments must belong to a specific session"). Nullable so the
    #: pre-existing rows created before sessions existed keep working; the data
    #: migration in ``simulation.0007_sessions_and_roles`` backfills them.
    session = models.ForeignKey(
        'simulation.SimulationSession', on_delete=models.CASCADE, null=True, blank=True,
        related_name='assignments')
    #: The catalogue row for :attr:`role`, kept in step by ``save()``. Holds the
    #: category, the establishment type the role belongs to and the workflow
    #: stage it handles, which is what the transaction engine routes on.
    role_ref = models.ForeignKey(
        'simulation.Role', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assignments')
    #: The establishment the student reports to (Section 6.4). Required for
    #: every operational role; null only for the customer roles (Passenger) and
    #: the administrative ones, which are not performed inside an establishment.
    establishment = models.ForeignKey(
        'establishments.Establishment', on_delete=models.PROTECT, null=True, blank=True,
        related_name='simulation_assignments')
    #: Which kind of establishment ``establishment`` is, stored on the
    #: assignment itself. It is a mirror of ``establishment.type`` (see
    #: :meth:`save`) so a role/establishment pair can be validated and reported
    #: on without a join to another app's table - and so the historical fact
    #: "this was a hotel role" survives the establishment being recategorised.
    establishment_type = models.CharField(
        max_length=20, null=True, blank=True, db_index=True)
    #: Whether the assigned role must be performed inside an establishment. A
    #: mirror of ``Role.requires_establishment`` (see :meth:`save`) for the same
    #: reason ``establishment_type`` is mirrored: the database has to be able to
    #: refuse an operational role with no establishment using *this* table's own
    #: columns, because a ``CheckConstraint`` may not reach across a relation.
    establishment_required = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-assigned_at']
        constraints = [
            # Section 6.4: no duplicate *active* assignment for the same student,
            # session, role and establishment. Scoped to rows that have a session
            # so the legacy session-less assignments are not forced together, and
            # to ACTIVE rows so a finished assignment never blocks a re-run.
            # Coalesce makes a NULL establishment compare equal to itself -
            # PostgreSQL otherwise treats each NULL as distinct, which would let
            # a student hold two active "Guest" slots in one session.
            models.UniqueConstraint(
                models.F('student'),
                models.F('session'),
                models.F('role_ref'),
                Coalesce('establishment', Value(0)),
                condition=models.Q(status='ACTIVE', session__isnull=False),
                name='unique_active_assignment_per_student_session_role',
            ),
            # The rule the whole simulation turns on: an operational role is an
            # assignment to ONE specific establishment, so it can never be
            # stored without one. Enforced here as well as in ``clean()`` so a
            # hand-written ORM insert, a management command or a future view
            # cannot create the "Manager of everywhere" row that would defeat
            # every establishment-scoping check downstream. Customer and
            # administrative roles (which are performed outside an
            # establishment) are exempt. Spelled with ``establishment_id`` rather
            # than ``establishment`` so it is plainly a local column test.
            #
            # Only ACTIVE rows are held to it. A finished - or already
            # deactivated - assignment is history, and demanding an
            # establishment of it would mean rewriting the past: the legacy rows
            # this rule was introduced for have no establishment to give, which
            # is exactly why migration 0010 marks them INACTIVE before the
            # constraint is added.
            models.CheckConstraint(
                condition=(models.Q(status='INACTIVE')
                           | models.Q(establishment_required=False)
                           | models.Q(establishment_id__isnull=False)),
                name='sim_assign_establishment_required_for_role',
            ),
        ]
        indexes = [
            models.Index(fields=['session', 'status'], name='sim_assign_session_idx'),
            models.Index(fields=['establishment', 'status'], name='sim_assign_estab_idx'),
            models.Index(fields=['student', 'status'], name='sim_assign_student_idx'),
        ]

    def __str__(self):
        return f"{self.student} - {self.get_role_display()}"

    # -- keeping the legacy columns and the new relations in step -------------

    def save(self, *args, **kwargs):
        """Mirror ``role`` into ``role_ref`` and ``hotel`` into ``establishment``.

        Both directions are maintained on write rather than in a data migration
        so an assignment created by the *old* pages (which only know about
        ``role``/``hotel``) still takes part in session-scoped routing, and one
        created through the new API still populates the columns the old
        templates and ``atrue_core.hotel_scope`` read.
        """
        if not self.role_ref_id and self.role:
            self.role_ref = Role.objects.filter(code=self.role).first()
        if self.session_id and self.session and not self.activity_name:
            self.activity_name = self.session.name
        if not self.establishment_id and self.hotel_id:
            from establishments.models import establishment_for_instance

            self.establishment = establishment_for_instance(self.hotel, create=True)
        elif self.establishment_id and not self.hotel_id:
            # Only mirror back when the establishment really is a hotel, so a
            # hotel column never points at an airline.
            establishment = self.establishment
            if establishment is not None and establishment.type == establishment.Type.HOTEL:
                self.hotel = establishment.entity
        if self.role_ref_id and not self.role:
            self.role = self.role_ref.code
        # ``establishment_type`` is derived, never supplied by the caller, so a
        # stale value on a form cannot make an airline role look like a hotel
        # role. ``establishment_required`` is the same idea: it mirrors the role's
        # own flag so the database-level CHECK sees only this table's columns.
        self.establishment_type = (
            self.establishment.type if self.establishment_id else None)
        self.establishment_required = bool(
            self.role_ref.requires_establishment if self.role_ref_id else False)
        super().save(*args, **kwargs)

    def clean(self):
        """Enforce the assignment rules the database cannot express (Section 7.2).

        The central rule: **role + specific establishment = active assignment**.
        An operational role with no establishment, or with one of the wrong
        type, is not a weaker assignment - it is not a valid assignment, so it
        is refused here rather than being stored and discovered later.
        """
        super().clean()
        errors = {}
        role = self.role_ref
        if role is None and self.role:
            role = Role.objects.filter(code=self.role).first()
        if self.role and role is None:
            errors['role'] = f'"{self.role}" is not a known simulation role.'
        if role is None:
            if self.establishment_id:
                errors['establishment'] = 'Choose a role before choosing an establishment.'
            return self._raise(errors)

        if role.requires_establishment:
            if not self.establishment_id:
                errors['establishment'] = (
                    f'{role.name} is performed inside an establishment, so one must be '
                    'selected. A role is only an assignment together with the '
                    'establishment it applies to.')
            elif self.establishment.type != role.establishment_category:
                errors['establishment'] = (
                    f'{role.name} cannot be assigned to a '
                    f'{self.establishment.get_type_display()}. Choose a '
                    f'{role.get_establishment_category_display()}.')
        elif self.establishment_id:
            # A stray establishment on a customer role would hand the student
            # access to another establishment's queue (Section 19 rule 5).
            errors['establishment'] = f'{role.name} is not establishment-specific.'

        if self.session_id and self.session:
            session = self.session
            if session.status == session.Status.COMPLETED:
                errors['session'] = (
                    f'"{session.name}" is completed. Reopen it before assigning '
                    'new roles.')
            elif session.status == session.Status.ARCHIVED:
                errors['session'] = f'"{session.name}" is archived and is read-only.'
            if session.instructor_id and self.assigned_by_id and (
                    session.instructor_id != self.assigned_by_id):
                errors['assigned_by'] = (
                    'Only the instructor supervising this session (or an '
                    'administrator) may assign roles to it.')
        return self._raise(errors)

    @staticmethod
    def _raise(errors):
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)
        return None

    # -- role helpers ----------------------------------------------------------

    @property
    def role_code(self):
        return self.role_ref.code if self.role_ref_id else self.role

    @property
    def role_label(self):
        if self.role_ref_id:
            return self.role_ref.name
        return self.get_role_display()

    @property
    def requires_establishment(self):
        return bool(self.role_ref.requires_establishment) if self.role_ref_id else False

    @property
    def operation_category(self):
        """``MANAGER`` / ``RESERVATION`` / ``FRONT_DESK`` / ``CUSTOMER`` / ``''``.

        Falls back to deriving the category from the role code for a legacy
        assignment that predates ``Role.operation_category``, so an older row
        still routes to the right pages instead of falling off the task menu.
        """
        if self.role_ref_id:
            if self.role_ref.operation_category:
                return self.role_ref.operation_category
        return LEGACY_OPERATION_CATEGORY.get(
            self.role, Role.OperationCategory.CUSTOMER if self.role else '')

    @property
    def created_at(self):
        """The assignment's creation timestamp.

        The column is named ``assigned_at`` because that is what the rest of the
        platform (and BR-083's wording) calls it; this alias exists so the
        assignment reads as a plain ``created_at``/``updated_at`` record.
        """
        return self.assigned_at

    @property
    def is_active(self):
        return self.status == self.AssignmentStatus.ACTIVE

    def role_permissions(self):
        """Return the list of permissions applicable to the assigned role (FR View Simulation Role)."""
        return ROLE_PERMISSIONS.get(self.role, [])


#: Permission lists shown on an assignment and on the role dashboard. The three
#: operational roles of every establishment share the same shape; only the nouns
#: differ (rooms vs seats vs vehicles vs tours), never the job itself.
_MANAGER_PERMISSIONS = [
    'Manage only the assigned establishment: its information, inventory, rates and availability',
    'Supervise the reservation and front desk roles at the same establishment',
    'Approve, reject, cancel and forward the establishment\'s transactions',
    'Record simulated payments and review the establishment\'s transactions',
]
_RESERVATION_PERMISSIONS = [
    'View only the reservations belonging to the assigned establishment',
    'Check availability and verify the reservation details',
    'Claim a reservation, then approve or reject it',
    'Forward an approved reservation to front desk / operations or to billing',
]
_FRONT_DESK_PERMISSIONS = [
    'View confirmed reservations for the assigned establishment',
    'Verify the establishment and its availability against the reservation',
    'Record guest arrival, fulfilment and departure (check-in, dispatch, ticketing)',
    'Update the operational status of the establishment and its bookings',
]
#: Activity Operators fulfil one specific activity and record who attended.
_OPERATOR_PERMISSIONS = [
    'View only the bookings of the assigned activity',
    'Attend and complete bookings (record arrival and fulfilment)',
    'Update the operational status of the assigned activity',
]
_AIRLINE_MANAGER_PERMISSIONS = [
    'Manage only the assigned airline: its information, aircraft and aircraft types',
    'Manage flights, routes, seats, fares and availability',
    *_MANAGER_PERMISSIONS[2:],
]
_HOTEL_MANAGER_PERMISSIONS = [
    'Manage only the assigned hotel: its information, rooms, room types, rates and availability',
    'Manage the hotel\'s amenities and services',
    *_MANAGER_PERMISSIONS[2:],
]
_TOUR_MANAGER_PERMISSIONS = [
    'Manage only the assigned tour operator: its company information and tour packages',
    'Manage destinations, schedules, prices and availability',
    *_MANAGER_PERMISSIONS[2:],
]
_TOUR_PACKAGE_MANAGER_PERMISSIONS = [
    'Manage only tour packages assigned to this account',
    'Manage package details, included hotels, schedules, pricing and availability',
]
_TOUR_PACKAGE_RESERVATION_PERMISSIONS = [
    'View only bookings for assigned tour packages',
    'Confirm or reject bookings for assigned tour packages',
]
_TOUR_PACKAGE_FRONT_DESK_PERMISSIONS = [
    'View only bookings for assigned tour packages',
    'Record guest arrival and complete assigned package bookings',
]
_ACTIVITY_MANAGER_PERMISSIONS = [
    'Manage only the assigned activities',
    'Manage activity schedules, fees, capacity and requirements',
]
_ACTIVITY_FRONT_DESK_PERMISSIONS = [
    'View only bookings for assigned activities',
    'Verify confirmed bookings and record guest arrival and check-in',
    'Update guest arrival and check-in statuses',
]
_RESORT_MANAGER_PERMISSIONS = [
    'Manage only the assigned resort: its information, units, rates and availability',
    'Manage the resort\'s services, amenities and house rules',
    *_MANAGER_PERMISSIONS[2:],
]
_RESTAURANT_MANAGER_PERMISSIONS = [
    'Manage only the assigned restaurant: its information, tables, cuisines and availability',
    'Manage the restaurant\'s services, seating areas and rates',
    *_MANAGER_PERMISSIONS[2:],
]
_STAYCATION_MANAGER_PERMISSIONS = [
    'Manage only the assigned staycation: its information, capacity, rates and availability',
    'Manage the staycation\'s services, house rules and blocked-out dates',
    *_MANAGER_PERMISSIONS[2:],
]
_LANDMARK_MANAGER_PERMISSIONS = [
    'Manage only the assigned landmark: its information, fees and visiting capacity',
    'Manage tours, guided-tour rates and attraction availability',
    *_MANAGER_PERMISSIONS[2:],
]

ROLE_PERMISSIONS = {
    # -- customer (simulation roles with no establishment) ---------------------
    'GUEST_HOTEL': ['Book and reserve hotel rooms', 'View reservations and rates', 'Settle hotel bills and payments'],
    'PASSENGER_AIRLINE': ['Search and book flights', 'Select seats and passengers', 'View and cancel flight bookings'],
    'CUSTOMER_TOUR': ['Reserve tour packages', 'View itineraries and inclusions', 'Make tour payments'],
    'RESORT_GUEST': ['Search and book resort stays', 'View resort rates and availability', 'Manage own reservations'],
    'RESTAURANT_GUEST': ['Search and book restaurant tables', 'View menus and rates', 'Manage own reservations'],
    'STAYCATION_GUEST': ['Search and book staycations', 'Add staycation services', 'Manage own reservations'],
    'LANDMARK_GUEST': ['Search and book landmark visits', 'View guided-tour options', 'Manage own reservations'],
    'TOUR_GUEST': ['Search and book tour packages', 'View itineraries and inclusions', 'Manage own reservations'],
    'PASSENGER_TRANSPORT': ['Search and book land transportation', 'View routes and fares', 'Manage own reservations'],
    'ACTIVITY_GUEST': ['Search and book activities', 'View schedules and requirements', 'Manage own reservations'],
    # -- airline: Manager / Reservation Agent / Front Desk --------------------
    'AIRLINE_MANAGER': _AIRLINE_MANAGER_PERMISSIONS,
    'AIRLINE_RESERVATION_AGENT': _RESERVATION_PERMISSIONS,
    'AIRLINE_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- hotel: Manager / Reservation Officer / Front Desk Officer ------------
    'HOTEL_MANAGER': _HOTEL_MANAGER_PERMISSIONS,
    'HOTEL_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'HOTEL_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- transportation: Manager / Reservation Agent / Front Desk -------------
    'TRANSPORT_MANAGER': _MANAGER_PERMISSIONS,
    'TRANSPORT_RESERVATION_AGENT': _RESERVATION_PERMISSIONS,
    'TRANSPORT_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- tour operator: Manager / Reservation Agent / Front Desk ---------------
    'TOUR_OPERATOR_MANAGER': _TOUR_MANAGER_PERMISSIONS,
    'TOUR_RESERVATION_AGENT': _RESERVATION_PERMISSIONS,
    'TOUR_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    'TOUR_PACKAGE_MANAGER': _TOUR_PACKAGE_MANAGER_PERMISSIONS,
    'TOUR_PACKAGE_RESERVATION_OFFICER': _TOUR_PACKAGE_RESERVATION_PERMISSIONS,
    'TOUR_PACKAGE_OPERATOR': _TOUR_PACKAGE_FRONT_DESK_PERMISSIONS,
    'TOUR_PACKAGE_FRONT_DESK_OFFICER': _TOUR_PACKAGE_FRONT_DESK_PERMISSIONS,
    'ACTIVITY_MANAGER': _ACTIVITY_MANAGER_PERMISSIONS,
    'ACTIVITY_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'ACTIVITY_OPERATOR': _OPERATOR_PERMISSIONS,
    'ACTIVITY_FRONT_DESK_OFFICER': _ACTIVITY_FRONT_DESK_PERMISSIONS,
    # -- travel agency: Manager / Reservation Agent / Front Desk --------------
    'TRAVEL_AGENCY_MANAGER': _MANAGER_PERMISSIONS,
    'TRAVEL_AGENCY_RESERVATION_AGENT': _RESERVATION_PERMISSIONS,
    'TRAVEL_AGENCY_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- resort: Manager / Reservation Officer / Front Desk -----------------
    'RESORT_MANAGER': _RESORT_MANAGER_PERMISSIONS,
    'RESORT_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'RESORT_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- restaurant: Manager / Reservation Officer / Front Desk -------------
    'RESTAURANT_MANAGER': _RESTAURANT_MANAGER_PERMISSIONS,
    'RESTAURANT_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'RESTAURANT_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- staycation: Manager / Reservation Officer / Front Desk -------------
    'STAYCATION_MANAGER': _STAYCATION_MANAGER_PERMISSIONS,
    'STAYCATION_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'STAYCATION_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- landmark: Manager / Reservation Officer / Front Desk ---------------
    'LANDMARK_MANAGER': _LANDMARK_MANAGER_PERMISSIONS,
    'LANDMARK_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'LANDMARK_FRONT_DESK': _FRONT_DESK_PERMISSIONS,
    # -- legacy: kept so an existing assignment still describes itself --------
    'TOUR_MANAGER': ['Manage tour itineraries', 'Coordinate tour schedules', 'Oversee tour coordinators and guides'],
    'TRAVEL_CONSULTANT': ['Advise customers on destinations', 'Create travel itineraries', 'Process bookings'],
    'TOUR_COORDINATOR': ['Coordinate tour groups', 'Communicate with hotels and customers', 'Ensure schedule adherence'],
    'BILLING_OFFICER': ['Issue bills and receipts', 'Process payments', 'Reconcile transaction records'],
    'RECEPTIONIST': ['Receive guests and check them in', 'Handle walk-in inquiries'],
    'BOOKING_AGENT': ['Process bookings for customers', 'Check availability and rates'],
    'FRONT_DESK': ['Manage front-desk operations', 'Handle guest check-in and out'],
    'CONCIERGE': ['Assist guests with requests', 'Coordinate in-house services'],
    'TOUR_GUIDE': ['Lead tour groups', 'Provide destination information'],
    'RESTAURANT_STAFF': ['Handle restaurant reservations', 'Serve and assist customers'],
    'TRANSPORT_STAFF': ['Coordinate transportation bookings', 'Assist with transfers'],
    'CABIN_CREW': ['Manage in-flight service', 'Assist airline passengers'],
    'AIRLINE_TICKETING_OFFICER': [
        'Search available flights and view flight information',
        'Retrieve reservations and review passenger and booking details',
        'Review payment status before issuing tickets',
        'Issue and retrieve tickets for confirmed reservations',
        'Process eligible booking changes and cancellations',
    ],
    # Legacy codes whose role was one of the three. They keep the description
    # of the job they were folded into so an older dashboard row still reads
    # correctly.
    'HOUSEKEEPING_OFFICER': _FRONT_DESK_PERMISSIONS,
    'AIRLINE_CUSTOMER_SERVICE': _FRONT_DESK_PERMISSIONS,
    'AIRLINE_SUPERVISOR': _MANAGER_PERMISSIONS,
    'TRANSPORT_DISPATCHER': _FRONT_DESK_PERMISSIONS,
    'TRANSPORT_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'TRAVEL_AGENCY_RESERVATION_OFFICER': _RESERVATION_PERMISSIONS,
    'TOUR_OPERATOR': _FRONT_DESK_PERMISSIONS,
    'HOTEL_BILLING_OFFICER': _MANAGER_PERMISSIONS,
    'AIRLINE_BILLING_OFFICER': _MANAGER_PERMISSIONS,
    'TRANSPORT_BILLING_OFFICER': _MANAGER_PERMISSIONS,
    'TOUR_BILLING_OFFICER': _MANAGER_PERMISSIONS,
    'TRAVEL_AGENCY_BILLING_OFFICER': _MANAGER_PERMISSIONS,
}


class ActivityLog(models.Model):
    """Significant simulation actions for traceability (BR-085, REQ-028)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='activity_logs'
    )
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True, default='')
    simulation_activity = models.CharField(max_length=150, blank=True, default='')
    simulation_role = models.CharField(max_length=40, blank=True, default='')
    session = models.ForeignKey(
        'simulation.SimulationSession', null=True, blank=True, on_delete=models.SET_NULL
    )
    establishment = models.ForeignKey(
        'establishments.Establishment', null=True, blank=True, on_delete=models.SET_NULL
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.action}"

    class Meta:
        ordering = ['-timestamp']


def _transaction_reference():
    """Human-quotable reference for a simulation transaction (SIM-TRX-XXXXXXXX).

    Students read these out loud to each other across a classroom, so it is
    short, uppercase and collision-checked by the unique constraint rather than
    by a counter - a counter would need an extra row to keep in step.
    """
    import uuid

    return f'SIM-TRX-{uuid.uuid4().hex[:8].upper()}'


# =========================================================================== #
#  SECTION 5 / 6 / 9 - simulation sessions, the role catalogue and the
#  centralized student-to-student transaction engine.
#
#  Appended to simulation/models.py rather than placed at the top so the legacy
#  ``SimulationRoleAssignment`` / ``ActivityLog`` models keep their migration
#  history untouched (Section 1: extend, do not replace).
# =========================================================================== #


class SimulationSession(models.Model):
    """A controlled learning environment owned by one instructor (Section 5).

    The session is the isolation boundary for everything else: role
    assignments, transactions, notifications and audit entries all hang off it,
    and Section 5.2 rules 5-6 make "another session's transactions" unreachable
    rather than merely hidden.
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        ACTIVE = 'ACTIVE', 'Active'
        COMPLETED = 'COMPLETED', 'Completed'
        ARCHIVED = 'ARCHIVED', 'Archived'

    #: Statuses that accept brand-new operational transactions.
    OPEN_STATUSES = frozenset({Status.SCHEDULED, Status.ACTIVE})
    #: Statuses that accept none at all, until an instructor reopens them.
    CLOSED_STATUSES = frozenset({Status.DRAFT, Status.COMPLETED, Status.ARCHIVED})

    name = models.CharField(max_length=150)
    session_id = models.CharField(
        max_length=12, unique=True, editable=False, null=True, verbose_name='Session ID')
    description = models.TextField(blank=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='simulation_sessions')

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.DRAFT, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['instructor', 'status'], name='sim_session_owner_idx'),
            models.Index(fields=['status', 'start_date'], name='sim_session_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(end_date__isnull=True)
                           | models.Q(start_date__isnull=True)
                           | models.Q(end_date__gte=models.F('start_date'))),
                name='sim_session_dates_ordered',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.session_id:
            self.session_id = f'SES-{self.pk:05d}'
            SimulationSession.objects.filter(pk=self.pk).update(session_id=self.session_id)

    # -- lifecycle ------------------------------------------------------------

    def clean(self):
        super().clean()
        errors = {}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors['end_date'] = 'The end date cannot be earlier than the start date.'
        if self.status == self.Status.ACTIVE and self.start_date and \
                self.start_date > timezone.localdate():
            errors['status'] = ('This session starts in the future. Leave it Scheduled '
                                'until it actually begins.')
        return self._raise(errors)

    @staticmethod
    def _raise(errors):
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)
        return None

    @property
    def is_open(self):
        """True when the session currently accepts new transactions."""
        return self.status in self.OPEN_STATUSES

    @property
    def is_closed(self):
        return self.status in self.CLOSED_STATUSES

    def within_dates(self, today=None):
        """Whether *today* falls inside the session window (open-ended = always).

        A SCHEDULED session is "scheduled" precisely because its window has not
        arrived, so the window is what decides whether it may trade yet.
        """
        if not (self.start_date or self.end_date):
            return True
        today = today or timezone.localdate()
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        return True

    def accepts_transactions(self, *, today=None):
        """Section 5.2 rule 7 / Section 19 rule 20: the single gate for new work."""
        return self.is_open and self.within_dates(today)

    def activate(self):
        if self.status == self.Status.ACTIVE:
            return False
        self.status = self.Status.ACTIVE
        self.activated_at = timezone.now()
        self.completed_at = None
        return True

    def complete(self):
        if self.status == self.Status.COMPLETED:
            return False
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        return True

    def participants(self):
        """Every student holding at least one assignment in this session."""
        from django.contrib.auth import get_user_model

        ids = self.assignments.values_list('student_id', flat=True)
        return get_user_model().objects.filter(pk__in=set(ids)).order_by('last_name', 'first_name')

    def establishments(self):
        """The establishments this session actually operates in."""
        from establishments.models import Establishment

        ids = self.assignments.exclude(establishment=None).values_list(
            'establishment_id', flat=True)
        return Establishment.objects.filter(pk__in=set(ids)).order_by('type', 'name')


class Role(models.Model):
    """The role catalogue (Section 6.3).

    Every establishment exposes exactly **three** operational roles, and they
    are the same three jobs everywhere even though the job titles differ by
    industry:

    ============================  ===========  =====================================
    ``operation_category``        display      job
    ============================  ===========  =====================================
    ``MANAGER``                   Manager      runs the establishment itself
    ``RESERVATION``               Reservation  receives and decides on reservations
    ``FRONT_DESK``                Front Desk   delivers the service to the customer
    ============================  ===========  =====================================

    ``operation_category`` is the one field the whole platform routes on, so
    "which role is this?" never has to be answered by a per-module ``if``.
    ``workflow_stage`` is derived from it (:data:`STAGE_FOR_OPERATION_CATEGORY`)
    and drives the transaction engine. The three operational roles handle the
    core booking workflow; establishment-specific Billing Officers handle the
    separate payment verification stage.

    A row here is also the single source of truth for the other two questions
    that used to be answered by scattered ``if`` statements:

    1. **Which establishment category does this role belong to?**
       (``establishment_type``) Drives the instructor's dynamic establishment
       picker (Section 7.2) and stops a Hotel Front Desk being assigned to an
       airline.
    2. **Does it need an establishment at all?** (``requires_establishment``)
       Guest / Passenger / Customer do not; the three operational roles do -
       always, without exception.
    """

    class Category(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        HOTEL = 'HOTEL', 'Hotel'
        RESORT = 'RESORT', 'Resort'
        RESTAURANT = 'RESTAURANT', 'Restaurant'
        STAYCATION = 'STAYCATION', 'Staycation'
        LANDMARK = 'LANDMARK', 'Landmark'
        AIRLINE = 'AIRLINE', 'Airline'
        TRAVEL_AGENCY = 'TRAVEL_AGENCY', 'Travel Agency'
        TOUR = 'TOUR', 'Tour Operation'
        ACTIVITY = 'ACTIVITY', 'Activity'
        TRANSPORTATION = 'TRANSPORTATION', 'Transportation'
        ADMIN = 'ADMIN', 'Administrative'

    #: The three operational jobs every establishment has, plus the customer
    #: side. Blank means "not an establishment role" (administrative roles).
    class OperationCategory(models.TextChoices):
        MANAGER = 'MANAGER', 'Manager'
        RESERVATION = 'RESERVATION', 'Reservation Agent / Officer'
        FRONT_DESK = 'FRONT_DESK', 'Front Desk / Operations Officer'
        BILLING = 'BILLING', 'Billing Officer'
        CUSTOMER = 'CUSTOMER', 'Customer'

    #: The three operational categories, in the order an instructor meets them.
    OPERATIONAL_CATEGORIES = (
        OperationCategory.MANAGER,
        OperationCategory.RESERVATION,
        OperationCategory.FRONT_DESK,
    )

    class WorkflowStage(models.TextChoices):
        #: The role raises and/or handles customer requests (front desk, agent...).
        INTAKE = 'INTAKE', 'Request Intake'
        #: The role fulfils an approved request (front desk, dispatch).
        FULFILLMENT = 'FULFILLMENT', 'Fulfilment'
        #: The role records the simulated payment.
        BILLING = 'BILLING', 'Simulated Billing'
        #: The role supervises and may act anywhere in the workflow.
        OVERSIGHT = 'OVERSIGHT', 'Supervision'

    class EstablishmentType(models.TextChoices):
        HOTEL = 'HOTEL', 'Hotel'
        RESORT = 'RESORT', 'Resort'
        RESTAURANT = 'RESTAURANT', 'Restaurant'
        STAYCATION = 'STAYCATION', 'Staycation'
        LANDMARK = 'LANDMARK', 'Landmark'
        AIRLINE = 'AIRLINE', 'Airline'
        TRAVEL_AGENCY = 'TRAVEL_AGENCY', 'Travel Agency'
        TOUR_OPERATOR = 'TOUR_OPERATOR', 'Tour Operator'
        TOUR_PACKAGE = 'TOUR_PACKAGE', 'Tour Package'
        ACTIVITY = 'ACTIVITY', 'Activity'
        TRANSPORTATION = 'TRANSPORTATION', 'Transportation Agency'

    #: ``operation_category`` -> the workflow stage the engine routes on.
    #:
    #: A Manager supervises (so it can act at *any* stage, including the
    #: simulated-billing one that used to be a separate role), a Reservation
    #: role handles requests as they arrive, and a Front Desk role delivers the
    #: service once the request is approved.
    STAGE_FOR_OPERATION_CATEGORY = {
        OperationCategory.MANAGER: WorkflowStage.OVERSIGHT,
        OperationCategory.RESERVATION: WorkflowStage.INTAKE,
        OperationCategory.FRONT_DESK: WorkflowStage.FULFILLMENT,
        OperationCategory.BILLING: WorkflowStage.BILLING,
        OperationCategory.CUSTOMER: WorkflowStage.INTAKE,
    }

    #: Maps operational areas onto establishment app choices. Activity and Tour
    #: Package operations are scoped to the resource itself: each activity and
    #: each tour package is wrapped in its own ``Establishment`` of the matching
    #: type (see ``establishments.establishment_for_instance``), so "which
    #: activity?" is answered the same way "which hotel?" is - with a single
    #: establishment the student is assigned to.
    ESTABLISHMENT_TYPE_MAP = {
        EstablishmentType.HOTEL: 'HOTEL',
        EstablishmentType.RESORT: 'RESORT',
        EstablishmentType.RESTAURANT: 'RESTAURANT',
        EstablishmentType.STAYCATION: 'STAYCATION',
        EstablishmentType.LANDMARK: 'LANDMARK',
        EstablishmentType.AIRLINE: 'AIRLINE',
        EstablishmentType.TRAVEL_AGENCY: 'TRAVEL_AGENCY',
        EstablishmentType.TOUR_OPERATOR: 'TOUR_OPERATOR',
        EstablishmentType.TOUR_PACKAGE: 'TOUR_PACKAGE',
        EstablishmentType.ACTIVITY: 'ACTIVITY',
        EstablishmentType.TRANSPORTATION: 'TRANSPORTATION',
    }

    code = models.CharField(max_length=40, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    establishment_type = models.CharField(
        max_length=20, choices=EstablishmentType.choices, null=True, blank=True,
        db_index=True)
    #: The one field the platform routes on: MANAGER / RESERVATION / FRONT_DESK
    #: for the three operational roles of every establishment, CUSTOMER for the
    #: passenger, blank for administrative roles.
    operation_category = models.CharField(
        max_length=20, choices=OperationCategory.choices, blank=True, default='',
        db_index=True)
    workflow_stage = models.CharField(
        max_length=15, choices=WorkflowStage.choices, default=WorkflowStage.INTAKE,
        db_index=True)
    #: True for establishment-scoped operational and billing roles. Stored
    #: rather than derived from ``establishment_type`` so the database itself
    #: can refuse an assignment that names such a role with no establishment
    #: (``SimulationRoleAssignment``'s check constraint reads this column).
    requires_establishment = models.BooleanField(default=False, db_index=True)
    permissions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'Roles'
        indexes = [
            models.Index(fields=['category', 'workflow_stage'], name='role_cat_stage_idx'),
            models.Index(fields=['establishment_type', 'operation_category'],
                         name='role_estab_opcat_idx'),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Operational and typed billing roles belong to an establishment;
        # customers, generic administrative roles and owners do not.
        self.requires_establishment = bool(
            self.establishment_type and not self.code.endswith('_OWNER'))
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not self.establishment_type and self.category not in (
                self.Category.CUSTOMER, self.Category.ADMIN):
            errors['establishment_type'] = (
                f'{self.get_category_display()} roles must name the establishment '
                'category they are performed in.')
        if self.category == self.Category.CUSTOMER and self.establishment_type:
            errors['establishment_type'] = 'Customer roles are not establishment-specific.'
        if self.establishment_type:
            if not self.operation_category:
                errors['operation_category'] = (
                    f'An establishment role must be one of '
                    f'{", ".join(self.OPERATIONAL_CATEGORIES)}.')
            elif (self.operation_category not in self.OPERATIONAL_CATEGORIES
                  and not (self.operation_category == self.OperationCategory.BILLING
                           and self.code in BILLING_OFFICER_ROLE_CODES)):
                errors['operation_category'] = (
                    f'"{self.operation_category}" is not a valid establishment role.')
        elif self.operation_category and self.operation_category not in (
                self.OperationCategory.CUSTOMER, self.OperationCategory.BILLING):
            errors['operation_category'] = (
                f'"{self.operation_category}" is performed inside an establishment, so '
                'it cannot name one here.')
        return self._raise(errors)

    @staticmethod
    def _raise(errors):
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)
        return None

    @property
    def establishment_category(self):
        """The ``establishments.Establishment.Type`` value this role belongs to."""
        return self.ESTABLISHMENT_TYPE_MAP.get(self.establishment_type)

    def get_establishment_category_display(self):
        """Human label for :attr:`establishment_category`.

        Used in the assignment validation message, so it reads "Hotel Manager
        cannot be assigned to an Airline. Choose a Hotel." rather than
        comparing two different enumerations.
        """
        from establishments.models import Establishment

        category = self.establishment_category
        if not category:
            return ''
        return dict(Establishment.Type.choices).get(category, '')


class SimulationTransaction(models.Model):
    """One student-to-student operational transaction (Section 9).

    A single row carries everything the engine needs to route, claim, validate
    and audit the work: who raised it, under which role, in which session, for
    which establishment, which stage it is at and who is handling it. The
    concrete reservation itself stays in the module that owns it
    (``hotels.Booking``, ``airlines.Booking``, ``tour_package.Booking``,
    ``transportation.Booking``, ``travel_agencies.TravelAgencyRequest``) and is
    attached through :attr:`subject`, so nothing is duplicated (Section 8.1 /
    Section 1: do not duplicate existing reservation functionality).
    """

    class Type(models.TextChoices):
        HOTEL = 'HOTEL', 'Hotel Reservation'
        FLIGHT = 'FLIGHT', 'Flight Reservation'
        TRAVEL_AGENCY = 'TRAVEL_AGENCY', 'Travel Agency Request'
        TOUR = 'TOUR', 'Tour Package Booking'
        TRANSPORTATION = 'TRANSPORTATION', 'Transportation Reservation'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PENDING = 'PENDING', 'Pending'
        UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'
        COMPLETED = 'COMPLETED', 'Completed'

    class Stage(models.TextChoices):
        #: Waiting for the establishment's intake role to respond.
        INTAKE = 'INTAKE', 'Awaiting Establishment'
        #: Approved and waiting for fulfilment (ticketing, dispatch).
        FULFILLMENT = 'FULFILLMENT', 'Awaiting Fulfilment'
        #: Approved and waiting for the simulated billing officer.
        BILLING = 'BILLING', 'Awaiting Simulated Billing'
        #: Finished - paid, ticketed or dispatched.
        DONE = 'DONE', 'Completed'
        #: Closed without payment (rejected or cancelled).
        CLOSED = 'CLOSED', 'Closed'

    #: Statuses that will never move again.
    TERMINAL_STATUSES = frozenset({
        Status.REJECTED, Status.CANCELLED, Status.COMPLETED})
    #: Statuses an operational role is allowed to act on.
    ACTIONABLE_STATUSES = frozenset({Status.PENDING, Status.UNDER_REVIEW})

    reference = models.CharField(
        max_length=20, unique=True, editable=False, default=_transaction_reference)

    session = models.ForeignKey(
        SimulationSession, on_delete=models.CASCADE, related_name='transactions')
    establishment = models.ForeignKey(
        'establishments.Establishment', on_delete=models.PROTECT,
        related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=Type.choices, db_index=True)

    #: Section 19 rules 10-11: a transaction must have a valid initiator and a
    #: valid session. Both are non-null and PROTECT/CASCADE respectively.
    initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='initiated_transactions')
    initiator_role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name='initiated_transactions')
    initiator_assignment = models.ForeignKey(
        SimulationRoleAssignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='initiated_transactions')

    #: The concrete reservation this transaction coordinates.
    subject_type = models.ForeignKey(
        'contenttypes.ContentType', on_delete=models.PROTECT, related_name='+')
    subject_id = models.PositiveBigIntegerField()
    subject = GenericForeignKey('subject_type', 'subject_id')

    status = models.CharField(max_length=15, choices=Status.choices,
                              default=Status.PENDING, db_index=True)
    stage = models.CharField(max_length=15, choices=Stage.choices,
                             default=Stage.INTAKE, db_index=True)

    #: Section 9.3 claim: who is working on it right now.
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='claimed_transactions')
    claimed_by_role = models.ForeignKey(
        Role, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='claimed_transactions')
    claimed_at = models.DateTimeField(null=True, blank=True)

    #: Travel / stay date and party size, used by the capacity checks in the
    #: hotel / tour / transportation workflows (Section 19 rule 15).
    service_date = models.DateField(null=True, blank=True, db_index=True)
    service_end_date = models.DateField(null=True, blank=True)
    party_size = models.PositiveIntegerField(default=1)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remarks = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            # The processing queue: one establishment's open work, oldest first.
            models.Index(fields=['establishment', 'status', 'stage'],
                         name='simtrx_queue_idx'),
            models.Index(fields=['session', 'status'], name='simtrx_session_idx'),
            models.Index(fields=['initiator', '-created_at'], name='simtrx_initiator_idx'),
            models.Index(fields=['claimed_by', 'status'], name='simtrx_claimed_idx'),
            models.Index(fields=['subject_type', 'subject_id'], name='simtrx_subject_idx'),
        ]
        constraints = [
            # Section 19 rule 6 / Scenario 5: the student who raised a
            # transaction can never be the student holding its claim. Enforced
            # here as well as in the service layer so a hand-edited POST or a
            # direct ORM write cannot smuggle a self-approval through.
            models.CheckConstraint(
                condition=models.Q(claimed_by__isnull=True)
                | ~models.Q(claimed_by=models.F('initiator')),
                name='simtrx_claimant_is_not_initiator'),
            # party_size is used as a capacity input, so it must be at least one.
            models.CheckConstraint(
                condition=models.Q(party_size__gte=1),
                name='simtrx_party_size_positive'),
            # Section 19 rule 12: an establishment is required for every
            # workflow, so it can never be blank.
            models.CheckConstraint(
                condition=~models.Q(establishment__isnull=True),
                name='simtrx_establishment_required'),
        ]

    def __str__(self):
        return self.reference

    @property
    def is_open(self):
        return self.status not in self.TERMINAL_STATUSES

    @property
    def is_claimed(self):
        return self.claimed_by_id is not None

    @property
    def is_claimed_by_initiator(self):
        """Scenario 5: the conflict case, exposed so the UI can explain it."""
        return bool(self.claimed_by_id and self.claimed_by_id == self.initiator_id)

    @property
    def subject_label(self):
        """A short human label for the underlying reservation."""
        subject = self.subject
        for attribute in ('booking_reference', 'reference', 'request_reference'):
            value = getattr(subject, attribute, None)
            if value:
                return str(value)
        return str(subject) if subject is not None else self.reference


class TransactionEvent(models.Model):
    """Append-only status history for one transaction (Section 9 / Section 17).

    This is the "transaction history" the requirements ask to be preserved: it
    is never rewritten, so an instructor reviewing a session can reconstruct
    exactly who moved a request from PENDING to UNDER_REVIEW and why.
    """

    transaction = models.ForeignKey(
        SimulationTransaction, on_delete=models.CASCADE, related_name='events')
    action = models.CharField(max_length=40)
    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15, blank=True)
    from_stage = models.CharField(max_length=15, blank=True)
    to_stage = models.CharField(max_length=15, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transaction_events')
    role = models.ForeignKey(
        Role, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transaction_events')
    establishment = models.ForeignKey(
        'establishments.Establishment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transaction_events')
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['transaction', 'created_at'], name='simtrx_event_idx'),
        ]

    def __str__(self):
        return f'{self.transaction.reference}: {self.action}'

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('TransactionEvent rows are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('TransactionEvent rows cannot be deleted.')
