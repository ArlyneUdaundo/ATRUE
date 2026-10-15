from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus

ACTIVITY_PROVIDER_STATUS_ACTIVE = 'ACTIVE'
ACTIVITY_PROVIDER_STATUS_INACTIVE = 'INACTIVE'
ACTIVITY_PROVIDER_STATUS_SUSPENDED = 'SUSPENDED'

ACTIVITY_PROVIDER_STATUS_CHOICES = [
    (ACTIVITY_PROVIDER_STATUS_ACTIVE, 'Active'),
    (ACTIVITY_PROVIDER_STATUS_INACTIVE, 'Inactive'),
    (ACTIVITY_PROVIDER_STATUS_SUSPENDED, 'Suspended'),
]

ACTIVITY_CATEGORY_CHOICES = [
    ('OUTDOOR', 'Outdoor and Adventure'),
    ('WATER', 'Water Activities'),
    ('CULTURAL', 'Cultural and Sightseeing'),
    ('THEME', 'Theme Parks and Attractions'),
    ('WELLNESS', 'Wellness and Leisure'),
    ('NIGHTLIFE', 'Nightlife and Entertainment'),
]

ACTIVITY_STATUS_ACTIVE = 'ACTIVE'
ACTIVITY_STATUS_INACTIVE = 'INACTIVE'
ACTIVITY_STATUS_SUSPENDED = 'SUSPENDED'
ACTIVITY_STATUS_UNDER_MAINTENANCE = 'UNDER_MAINTENANCE'
ACTIVITY_STATUS_FULLY_BOOKED = 'FULLY_BOOKED'
ACTIVITY_STATUS_CANCELLED = 'CANCELLED'

ACTIVITY_STATUS_CHOICES = [
    (ACTIVITY_STATUS_ACTIVE, 'Active'),
    (ACTIVITY_STATUS_INACTIVE, 'Inactive'),
    (ACTIVITY_STATUS_SUSPENDED, 'Suspended'),
    (ACTIVITY_STATUS_UNDER_MAINTENANCE, 'Under Maintenance'),
    (ACTIVITY_STATUS_FULLY_BOOKED, 'Fully Booked'),
    (ACTIVITY_STATUS_CANCELLED, 'Cancelled'),
]

ACTIVITY_RATE_TYPE_CHOICES = [
    ('PER_PERSON', 'Per Person'),
    ('PER_GROUP', 'Per Group'),
    ('PER_SESSION', 'Per Session'),
]

ACTIVITY_DURATION_UNIT_CHOICES = [
    ('MINUTES', 'Minutes'),
    ('HOURS', 'Hours'),
    ('DAYS', 'Days'),
]

# NOTE: kept for parity with the original file, but still unattached to any
# field on Booking below (no `gender` field exists, and nothing references
# this list). This is dead code either way -- confirm whether Booking should
# actually have a gender field, or whether this should be deleted outright.
BOOKING_GENDER_CHOICES = [
    ('MALE', 'Male'),
    ('FEMALE', 'Female'),
    ('OTHER', 'Other'),
    ('PNTS', 'Prefer not to say'),
]


class ActivityProvider(models.Model):
    """Real entity managed by admins (Establishment Management module) —
    each row has its own contact info and verification status, so this
    stays a table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    establishment = models.ForeignKey(
        'establishments.Establishment',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='activity_providers',
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    location = models.CharField(max_length=255)
    country = models.CharField(max_length=100, blank=True, default='')
    contact_number = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True, default='')
    service_area = models.CharField(max_length=255, blank=True, help_text="Service area (FR-029)")
    operating_schedule = models.CharField(max_length=150, blank=True, help_text="Operating schedule (FR-029)")
    verified = models.BooleanField(default=False, help_text="Verified providers may publish activities (BR-066)")
    status = models.CharField(
        max_length=10, choices=ACTIVITY_PROVIDER_STATUS_CHOICES, default=ACTIVITY_PROVIDER_STATUS_ACTIVE
    )

    class Meta:
        ordering = ['name']

    @property
    def bookable(self):
        # Provider verification is an administrative review marker; it does
        # not block guest bookings when the provider is active.
        return self.status == ACTIVITY_PROVIDER_STATUS_ACTIVE

    def __str__(self):
        return self.name


class Activity(models.Model):
    """Each activity is its own listing with pricing, schedule, and
    requirements — a real record, not a fixed option, so it stays a table."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'
        FULLY_BOOKED = 'FULLY_BOOKED', 'Fully Booked'
        CANCELLED = 'CANCELLED', 'Cancelled'

    provider = models.ForeignKey(ActivityProvider, on_delete=models.PROTECT, related_name='activities')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=10, choices=ACTIVITY_CATEGORY_CHOICES, default='OUTDOOR')
    location = models.CharField(max_length=255, default='')
    location_barangay = models.CharField(max_length=100, blank=True, default='')
    location_municipality = models.CharField(max_length=100, blank=True, default='')
    location_country = models.CharField(max_length=100, blank=True, default='')
    location_province = models.CharField(max_length=100, blank=True, default='')
    meeting_point = models.CharField(max_length=255, blank=True, default='')
    duration_minutes = models.PositiveIntegerField(default=60, help_text="Duration in minutes")
    duration_unit = models.CharField(
        max_length=10, choices=ACTIVITY_DURATION_UNIT_CHOICES, default='MINUTES', help_text="Duration unit (FR-030)"
    )
    required_documents = models.TextField(blank=True, default='', help_text="Required documents (FR-030), e.g. government-issued ID, waiver")
    schedule_date = models.DateField(null=True, blank=True)
    schedule_time = models.TimeField(null=True, blank=True)
    schedule_end_time = models.TimeField(null=True, blank=True, help_text="End time (FR-030)")
    operating_days = models.CharField(max_length=100, blank=True, help_text="Comma-separated operating days, e.g. Mon-Fri (FR-030)")
    fee = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate per participant")
    rate_type = models.CharField(max_length=15, choices=ACTIVITY_RATE_TYPE_CHOICES, default='PER_PERSON')
    additional_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                         help_text="Additional fee on top of the base rate (FR-030)")
    capacity = models.PositiveIntegerField(default=1)
    min_participants = models.PositiveIntegerField(default=1, help_text="Minimum participants (FR-030)")
    requirements = models.TextField(blank=True, default='', help_text="Age restrictions, skill levels, prerequisites (BR-068)")
    required_equipment = models.TextField(blank=True, default='')
    guide_required = models.BooleanField(default=False)
    image = models.ImageField(upload_to='activity_images/', blank=True)
    status = models.CharField(max_length=20, choices=ACTIVITY_STATUS_CHOICES, default=ACTIVITY_STATUS_ACTIVE)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    @property
    def duration(self):
        h, m = divmod(self.duration_minutes, 60)
        if h and m:
            return f"{h}h {m}m"
        if h:
            return f"{h}h"
        return f"{m}m"

    @property
    def full_location(self):
        parts = filter(None, [self.location, self.location_barangay, self.location_municipality, self.location_province])
        return ', '.join(parts) or 'Location not set'

    @property
    def bookable(self):
        return self.status == ACTIVITY_STATUS_ACTIVE and self.provider.bookable

    def __str__(self):
        return self.name


class ActivityPhoto(models.Model):
    """Multiple photos for an activity listing/detail gallery."""

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='activity_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            ActivityPhoto.objects.filter(activity=self.activity).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.activity.name} - {self.image}"


class Booking(BookingFieldsMixin):
    """Real customer transaction record — stays a table."""

    Status = BookingStatus

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='activity_bookings')
    activity = models.ForeignKey(Activity, on_delete=models.PROTECT, related_name='bookings')
    schedule_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True, help_text="Planned start time (FR-031)")
    end_time = models.TimeField(null=True, blank=True, help_text="Planned end time (FR-031)")
    participant_count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-created_at']

    @property
    def primary_participant_name(self):
        """Primary participant = the account holder (FR-031)."""
        return self.customer.get_full_name() or self.customer.username

    @property
    def first_name(self):
        return self.customer.first_name or ''

    @property
    def middle_name(self):
        return self.customer.middle_name or ''

    @property
    def last_name(self):
        return self.customer.last_name or ''

    @property
    def age(self):
        """Participant age computed from the account (BR-007)."""
        dob = self.customer.date_of_birth
        if not dob:
            return None
        today = timezone.localdate()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @property
    def email(self):
        return self.customer.email or ''

    @property
    def gender(self):
        return {'M': 'MALE', 'F': 'FEMALE'}.get(self.customer.sex, 'PNTS')

    @property
    def contact_number(self):
        return self.customer.contact_number or ''

    @property
    def emergency_contact_name(self):
        return self.customer.emergency_contact_name or ''

    @property
    def emergency_contact_number(self):
        return self.customer.emergency_contact_number or ''

    @property
    def emergency_contact_relationship(self):
        return self.customer.emergency_contact_relationship or ''

    def __str__(self):
        return f"Booking {self.booking_reference}"
