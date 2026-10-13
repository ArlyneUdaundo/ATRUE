from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from atrue_core.storage_backends import ProfilePictureStorage
from django.utils.functional import cached_property

from simulation.models import SimulationRoleAssignment

ACCOUNT_TYPE_CHOICES = [
    ('STUDENT', 'Student'),
    ('INSTRUCTOR', 'Instructor/Trainer'),
    ('ADMIN', 'Administrator'),
    ('SYSTEM_ADMIN', 'System Administrator'),
]

# BR-083 simulation roles also exist as account types so every role can be
# created directly and tested with its own dashboard page.
ACCOUNT_TYPE_CHOICES += list(SimulationRoleAssignment.Role.choices)

SEX_CHOICES = [
    ('M', 'Male'),
    ('F', 'Female'),
]

USER_STATUS_ACTIVE = 'ACTIVE'
USER_STATUS_INACTIVE = 'INACTIVE'
USER_STATUS_SUSPENDED = 'SUSPENDED'

USER_STATUS_CHOICES = [
    (USER_STATUS_ACTIVE, 'Active'),
    (USER_STATUS_INACTIVE, 'Inactive'),
    (USER_STATUS_SUSPENDED, 'Suspended'),
]

NATIONALITY_CHOICES = [
    ('FILIPINO', 'Filipino'),
    ('OTHER', 'Other'),
]


def profile_picture_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    return f'profile_pictures/user_{instance.pk}/{uuid4().hex}{extension}'


class User(AbstractUser):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    class AccountType(models.TextChoices):
        STUDENT = 'STUDENT', 'Student'
        INSTRUCTOR = 'INSTRUCTOR', 'Instructor/Trainer'
        ADMIN = 'ADMIN', 'Administrator'
        SYSTEM_ADMIN = 'SYSTEM_ADMIN', 'System Administrator'
        GUEST_HOTEL = 'GUEST_HOTEL', 'Guest – Hotel'
        PASSENGER_AIRLINE = 'PASSENGER_AIRLINE', 'Passenger – Airline'
        CUSTOMER_TOUR = 'CUSTOMER_TOUR', 'Customer – Tour'
        TOUR_MANAGER = 'TOUR_MANAGER', 'Tour Manager'
        HOTEL_MANAGER = 'HOTEL_MANAGER', 'Hotel Manager'
        TRAVEL_AGENCY_MANAGER = 'TRAVEL_AGENCY_MANAGER', 'Travel Agency Manager'
        TRAVEL_CONSULTANT = 'TRAVEL_CONSULTANT', 'Travel Consultant'
        TOUR_COORDINATOR = 'TOUR_COORDINATOR', 'Tour Coordinator'
        BILLING_OFFICER = 'BILLING_OFFICER', 'Billing Officer'
        RECEPTIONIST = 'RECEPTIONIST', 'Receptionist'
        BOOKING_AGENT = 'BOOKING_AGENT', 'Booking Agent'
        FRONT_DESK = 'FRONT_DESK', 'Front Desk Officer'
        CONCIERGE = 'CONCIERGE', 'Concierge'
        TOUR_GUIDE = 'TOUR_GUIDE', 'Tour Guide'
        RESTAURANT_STAFF = 'RESTAURANT_STAFF', 'Restaurant Staff'
        TRANSPORT_STAFF = 'TRANSPORT_STAFF', 'Transport Staff'
        CABIN_CREW = 'CABIN_CREW', 'Cabin Crew'

    middle_name = models.CharField(max_length=100, blank=True)
    middle_initial = models.CharField(max_length=10, blank=True)
    suffix = models.CharField(max_length=10, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)
    contact_number = models.CharField(max_length=11, blank=True)
    residential_address = models.CharField(max_length=255, blank=True)
    nationality = models.CharField(max_length=100, choices=NATIONALITY_CHOICES, default='FILIPINO', blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_number = models.CharField(max_length=11, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)
    profile_picture = models.ImageField(
        upload_to=profile_picture_upload_to, blank=True,
        storage=ProfilePictureStorage(),
    )
    account_type = models.CharField(max_length=40, choices=ACCOUNT_TYPE_CHOICES, default='STUDENT')
    status = models.CharField(max_length=10, choices=USER_STATUS_CHOICES, default=USER_STATUS_ACTIVE)

    @property
    def is_platform_manager(self):
        """True for administrators, management-role accounts, and students whose
        ACTIVE instructor-assigned role is a management role (BR-084). Drives the
        management nav and admin controls on list pages."""
        from accounts.roles import MANAGEMENT_ACCOUNT_TYPES, effective_role_keys
        return self.is_staff or bool(effective_role_keys(self) & MANAGEMENT_ACCOUNT_TYPES)

    @property
    def is_account_manager(self):
        """True for FR account-management actors (Administrator, Instructor/Trainer)."""
        from accounts.roles import ACCOUNT_MANAGER_TYPES
        return self.is_staff or self.account_type in ACCOUNT_MANAGER_TYPES

    @property
    def can_manage_hotels(self):
        """True when this user may manage hotel operations (hotels module access).

        Includes support-tier roles granted the ``hotels`` module (Front Desk,
        Receptionist, Concierge) alongside management accounts (BR-084)."""
        from accounts.roles import can_access_module
        return bool(can_access_module(self, 'hotels'))

    @cached_property
    def is_airline_ticketing_only(self):
        from accounts.roles import is_airline_ticketing_only
        return is_airline_ticketing_only(self)

    @cached_property
    def is_airline_booking_restricted(self):
        from accounts.roles import is_airline_booking_restricted
        return is_airline_booking_restricted(self)

    @property
    def is_bookable(self):
        """BR-007: a deactivated/suspended account cannot make new bookings."""
        return self.status == USER_STATUS_ACTIVE

    @property
    def initials(self):
        """Up to two initials for the default avatar.

        Prefers the real name, so the avatar reads "AJ" for Arlyne Joy Udaundo
        rather than the first letter of a username. Falls back through the middle
        name, then the first name, then the username, so an account with nothing
        filled in still gets a stable letter instead of an empty circle.
        """
        def initial(value):
            return value.strip()[0] if value and value.strip() else ''

        first = initial(self.first_name)
        middle = initial(self.middle_name) or initial(self.middle_initial)
        last = initial(self.last_name)
        letters = ''.join(part for part in (first, middle or last) if part)
        return letters.upper()[:2] or initial(self.username).upper()

    @property
    def full_profile(self):
        parts = [self.first_name or '', self.middle_name or '', self.last_name or '']
        name = ' '.join(filter(None, parts)).strip() or self.username
        if self.suffix:
            name = f"{name}, {self.suffix}"
        return name

    # -- Section 4 / 6: role and session helpers ----------------------------

    @property
    def is_instructor(self):
        """True for accounts allowed to create and supervise sessions.

        ``is_staff`` covers the System Administrator, and the account-type
        check covers an Instructor/Trainer account. Both were already the
        instructor test in ``simulation.views._is_instructor``; the name is
        exposed here so the API permission classes and the services agree with
        the HTML pages instead of each re-deriving it.
        """
        return self.is_staff or self.account_type in (
            'INSTRUCTOR', 'ADMIN', 'SYSTEM_ADMIN')

    @property
    def is_student(self):
        return self.account_type == self.AccountType.STUDENT

    def student_profile_record(self, *, create=True):
        """The student's academic profile, created on demand.

        Section 4.2 wants a profile for every student, but the existing account
        forms do not collect academic fields, so creating the row lazily keeps
        every already-provisioned student valid without a data migration.
        """
        profile, _ = StudentProfile.objects.get_or_create(
            user=self) if create else StudentProfile.objects.get_or_none(user=self)
        return profile

    def active_role_assignments(self, *, session=None):
        """Every ACTIVE assignment this user holds, optionally within one session."""
        assignments = self.simulation_roles.filter(status='ACTIVE').select_related(
            'role_ref', 'establishment', 'session')
        if session is not None:
            assignments = assignments.filter(session=session)
        return assignments

    def assignment_for_role(self, role_code, *, session=None):
        """The ACTIVE assignment granting ``role_code``, or None.

        The lookup is through this user's own assignments, so asking for a role
        the student was never assigned simply returns None - the basis of
        "a student cannot access an unassigned role" (Section 19 rule 3).
        """
        assignments = self.active_role_assignments(session=session)
        return assignments.filter(role=role_code).first() or \
            assignments.filter(role_ref__code=role_code).first()

    def has_role(self, role_code, *, session=None, establishment=None):
        """Whether the user holds an ACTIVE assignment for this role/establishment."""
        assignments = self.active_role_assignments(session=session)
        if establishment is not None:
            assignments = assignments.filter(establishment=establishment)
        return assignments.filter(role=role_code).exists() or \
            assignments.filter(role_ref__code=role_code).exists()

    def is_session_instructor(self, session):
        if session is None or self.is_staff:
            return False
        if session.instructor_id == self.pk:
            return True
        profile = InstructorProfile.objects.filter(user=self).first()
        return bool(profile and profile.supervises(session))

    @property
    def is_system_admin(self):
        return self.is_superuser or self.account_type in (
            self.AccountType.SYSTEM_ADMIN, self.AccountType.ADMIN)

    def __str__(self):
        return self.get_full_name() or self.username


class AuthContext(models.Model):
    """Per-tab authenticated context for multi-account / multi-role tabs.

    Django's session cookie is shared by every tab in the same browser profile,
    which would force all tabs to the *last* account that signed in. To let
    different tabs act as different users (and different roles) at the same
    time, each tab keeps a random high-entropy token in its own
    ``sessionStorage`` and sends it on every request (``?ctx=`` or the
    ``X-ATRUE-CTX`` header). This model binds that token to a real Django
    session, so the middleware can activate the correct authenticated context
    per tab without ever using a session-global "active role" variable.

    The token is only a selector for an existing Django session — it carries no
    credentials of its own, and every activation is re-validated against the
    bound session before it is honoured.

    ``user`` is nullable to represent a tab that has signed out. Signing out
    flushes the tab's session, so nothing of the previous account survives in
    it; what the row preserves is the tab's own *anonymous* workspace, which is
    where the "you have been signed out" notice is queued. A NULL user grants no
    access whatsoever: activating such a context yields a session with no
    ``_auth_user_id``, so ``request.user`` is anonymous and every
    permission check still applies. Reachable only by a request already
    presenting the matching token.
    """

    token = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='auth_contexts', null=True, blank=True,
    )
    session_key = models.CharField(max_length=80, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_used']

    def __str__(self):
        who = self.user.username if self.user_id else 'signed out'
        return f"{who} @ {self.token[:8]}…"


# --------------------------------------------------------------------------- #
#  Section 4.2 / 4.3 - academic profiles
#
#  These are deliberately *profiles*, not a second identity: Section 4.1
#  requires one account per student no matter how many operational roles that
#  student holds, so the academic data hangs off the existing ``User`` rather
#  than replacing it. Only the fields the existing ``User`` does not already
#  carry are added here - name, contact, nationality and status all stay on
#  ``User`` so no existing page has to be changed to keep working.
# --------------------------------------------------------------------------- #

YEAR_LEVEL_CHOICES = [
    ('FIRST_YEAR', 'First Year'),
    ('SECOND_YEAR', 'Second Year'),
    ('THIRD_YEAR', 'Third Year'),
    ('FOURTH_YEAR', 'Fourth Year'),
]


class StudentProfile(models.Model):
    """Academic details for a student account (Section 4.2).

    One row per user, created on demand by :meth:`User.student_profile_record`,
    so a student who signs up through the existing account forms and never
    touches this screen still has a usable profile.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_profile')
    student_id = models.CharField(
        max_length=30, unique=True, blank=True, verbose_name='Student ID')
    program = models.CharField(
        max_length=150, blank=True, default='BS Tourism Management',
        help_text='Course / programme.')
    year_level = models.CharField(max_length=15, choices=YEAR_LEVEL_CHOICES, blank=True)
    section = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.ACTIVE, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__last_name', 'user__first_name']
        indexes = [
            models.Index(fields=['year_level', 'section'], name='student_cohort_idx'),
        ]

    def __str__(self):
        return f'{self.student_id or self.user.username} ({self.user.full_profile})'

    def save(self, *args, **kwargs):
        # Assign the next free student number on first save, mirroring the
        # ``HTL-00001`` / ``ALN-00001`` convention the catalogue models already
        # use for their own ids.
        if not self.student_id:
            self.student_id = self._next_student_id()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_student_id():
        import re

        highest = 0
        pattern = re.compile(r'^S-(\d+)$')
        for value in StudentProfile.objects.filter(
                student_id__startswith='S-').values_list('student_id', flat=True):
            match = pattern.match(value or '')
            if match:
                highest = max(highest, int(match.group(1)))
        return f'S-{highest + 1:05d}'


class InstructorProfile(models.Model):
    """Teaching details for an instructor account (Section 4.3).

    ``SimulationSession.instructor`` points at the ``User``; this profile adds
    the academic context (rank, department) and the list of colleagues who may
    co-supervise a session, which is what makes "an instructor only accesses the
    sessions they are authorized to supervise" (Section 19 rule 19) expressible
    for more than one person.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='instructor_profile')
    employee_id = models.CharField(max_length=30, blank=True, verbose_name='Employee ID')
    rank = models.CharField(max_length=80, blank=True)
    department = models.CharField(
        max_length=150, blank=True, default='Tourism Management')
    #: Other instructors allowed to supervise the same sessions.
    co_instructors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='co_supervised_by')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__last_name', 'user__first_name']

    def __str__(self):
        return self.user.full_profile

    def supervises(self, session):
        """True when this instructor may monitor ``session`` (Section 19 rule 19)."""
        if session is None:
            return False
        user = self.user
        if user.is_staff or user.is_superuser:
            return True
        if session.instructor_id == user.pk:
            return True
        return self.co_instructors.filter(pk=session.instructor_id).exists()
