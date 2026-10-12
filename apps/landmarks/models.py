from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus

LANDMARK_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNDER_MAINTENANCE', 'Under Maintenance'),
]

LANDMARK_CATEGORY_CHOICES = [
    ('TOURIST_SPOT', 'Tourist Spot'),
    ('LANDMARK', 'Landmark'),
]

# NOTE: mirrors LANDMARK_CATEGORY_CHOICES exactly. Kept separate here for
# parity with the original file; consider reusing LANDMARK_CATEGORY_CHOICES
# instead if these should always change together.
TICKET_DESTINATION_TYPE_CHOICES = [
    ('TOURIST_SPOT', 'Tourist Spot'),
    ('LANDMARK', 'Landmark'),
]

TICKET_GUIDED_TOUR_CHOICES = [
    ('NONE', 'No Guided Tour'),
    ('STANDARD', 'Standard Guided Tour'),
    ('PRIVATE', 'Private Guided Tour'),
]


class Landmark(models.Model):
    """Real entity managed by admins (Establishment Management module) —
    each row has its own location, fees, and capacity, so this stays a
    table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'

    class Category(models.TextChoices):
        TOURIST_SPOT = 'TOURIST_SPOT', 'Tourist Spot'
        LANDMARK = 'LANDMARK', 'Landmark'

    category = models.CharField(max_length=15, choices=LANDMARK_CATEGORY_CHOICES, default='LANDMARK')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    country = models.CharField(max_length=100, blank=True, default='')
    region = models.CharField(max_length=100, blank=True, default='', help_text="Region (FR-025)")
    province = models.CharField(max_length=100, blank=True, default='')
    municipality = models.CharField(max_length=100, blank=True, default='')
    barangay = models.CharField(max_length=100, blank=True, default='')
    contact_number = models.CharField(max_length=20, blank=True, default='')
    open_hours = models.CharField(max_length=150, blank=True, default='')
    entry_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    capacity = models.PositiveIntegerField(default=0, help_text="Max daily visitors (0 = unlimited)")
    guided_tour_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Standard guided tour rate per visitor")
    private_tour_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Private guided tour flat rate")
    status = models.CharField(max_length=20, choices=LANDMARK_STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    @property
    def location(self):
        return ', '.join(filter(None, [self.country, self.province, self.municipality, self.barangay])) or 'Location not set'

    @property
    def fee(self):
        return self.entry_fee

    def __str__(self):
        return self.name


class LandmarkPhoto(models.Model):
    """Multiple photos for a landmark/tourist spot listing/detail gallery."""

    landmark = models.ForeignKey(Landmark, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='landmark_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            LandmarkPhoto.objects.filter(landmark=self.landmark).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.landmark.name} - {self.image}"


class Ticket(BookingFieldsMixin):
    """Real customer transaction record — stays a table."""

    Status = BookingStatus

    class DestinationType(models.TextChoices):
        TOURIST_SPOT = 'TOURIST_SPOT', 'Tourist Spot'
        LANDMARK = 'LANDMARK', 'Landmark'

    class GuidedTour(models.TextChoices):
        NONE = 'NONE', 'No Guided Tour'
        STANDARD = 'STANDARD', 'Standard Guided Tour'
        PRIVATE = 'PRIVATE', 'Private Guided Tour'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='attraction_tickets')
    destination_type = models.CharField(max_length=15, choices=TICKET_DESTINATION_TYPE_CHOICES)
    destination = models.ForeignKey(Landmark, on_delete=models.PROTECT, null=True, blank=True, related_name='tickets')
    visit_datetime = models.DateTimeField(default=timezone.now)
    number_of_visitors = models.PositiveIntegerField(default=1)
    guided_tour = models.CharField(max_length=10, choices=TICKET_GUIDED_TOUR_CHOICES, default='NONE')
    equipment_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Equipment charge per item (FR-026)")
    equipment_quantity = models.PositiveIntegerField(default=0, help_text="Quantity of equipment rented (FR-026)")

    class Meta:
        ordering = ['-created_at']

    @property
    def primary_guest_name(self):
        """Primary visitor = the account holder (FR-026)."""
        return self.customer.get_full_name() or self.customer.username

    @property
    def visitor_age(self):
        """Age of the primary visitor, computed from the account (BR-007)."""
        dob = getattr(self.customer, 'date_of_birth', None)
        if not dob:
            return None
        today = timezone.localdate()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @property
    def visitor_email(self):
        """Primary visitor email reused from the account."""
        return self.customer.email

    @property
    def contact_number(self):
        """Primary visitor contact reused from the account."""
        return self.customer.contact_number

    def __str__(self):
        return f"Ticket {self.booking_reference}"