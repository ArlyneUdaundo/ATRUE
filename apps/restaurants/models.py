from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin
from atrue_core.slugs import SlugByNameMixin

RESTAURANT_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNDER_MAINTENANCE', 'Under Maintenance'),
]

SEATING_AREA_CHOICES = [
    ('INDOOR', 'Indoor'),
    ('OUTDOOR', 'Outdoor'),
    ('BAR', 'Bar/Counter'),
    ('PRIVATE', 'Private Area'),
]

TABLE_STATUS_CHOICES = [
    ('AVAILABLE', 'Available'),
    ('OCCUPIED', 'Occupied'),
    ('RESERVED', 'Reserved'),
    ('MAINTENANCE', 'Under Maintenance'),
]

# NOTE: mirrors SEATING_AREA_CHOICES exactly. Kept separate here for parity
# with the original file; consider reusing SEATING_AREA_CHOICES instead if
# these should always change together.
SEATING_PREFERENCE_CHOICES = [
    ('INDOOR', 'Indoor'),
    ('OUTDOOR', 'Outdoor'),
    ('BAR', 'Bar/Counter'),
    ('PRIVATE', 'Private Area'),
]

OCCASION_CHOICES = [
    ('NONE', 'None'),
    ('BIRTHDAY', 'Birthday'),
    ('ANNIVERSARY', 'Anniversary'),
    ('BUSINESS', 'Business'),
    ('DATE', 'Date / Romantic'),
    ('GRADUATION', 'Graduation'),
    ('FAMILY_REUNION', 'Family Reunion'),
    ('DEBUT', 'Debut'),
    ('ENGAGEMENT', 'Engagement'),
    ('CHRISTENING', 'Christening'),
    ('HOLIDAY_CELEBRATION', 'Holiday Celebration'),
    ('CASUAL_DINING', 'Casual Dining'),
    ('OTHER', 'Other'),
]


class Restaurant(SlugByNameMixin, models.Model):
    """Real entity managed by admins (Establishment Management module) —
    each row has its own contact info and cuisine, so this stays a
    table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'

    name = models.CharField(max_length=150)
    restaurant_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                    verbose_name="Restaurant ID")
    location = models.CharField(max_length=255)
    country = models.CharField(max_length=100, blank=True, default='')
    cuisine_type = models.CharField(max_length=100, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    operating_hours = models.CharField(max_length=150, blank=True)
    cost_per_table = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=RESTAURANT_STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.restaurant_id:
            self.restaurant_id = f"RST-{self.pk:05d}"
            Restaurant.objects.filter(pk=self.pk).update(restaurant_id=self.restaurant_id)

    def __str__(self):
        return self.name


class RestaurantPhoto(models.Model):
    """Multiple photos for a restaurant listing/detail gallery."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='restaurant_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            RestaurantPhoto.objects.filter(restaurant=self.restaurant).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.restaurant.name} - {self.image}"


class Table(models.Model):
    """Each table has its own number and capacity, and its status changes
    with bookings — a real record, not a fixed option, so it stays a table."""

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        OCCUPIED = 'OCCUPIED', 'Occupied'
        RESERVED = 'RESERVED', 'Reserved'
        MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

    class SeatingArea(models.TextChoices):
        INDOOR = 'INDOOR', 'Indoor'
        OUTDOOR = 'OUTDOOR', 'Outdoor'
        BAR = 'BAR', 'Bar/Counter'
        PRIVATE = 'PRIVATE', 'Private Area'

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='tables')
    table_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                verbose_name="Table ID")
    table_number = models.CharField(max_length=20)
    capacity = models.PositiveIntegerField(default=2)
    seating_area = models.CharField(max_length=10, choices=SEATING_AREA_CHOICES, default='INDOOR')
    status = models.CharField(max_length=15, choices=TABLE_STATUS_CHOICES, default='AVAILABLE')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.table_id:
            self.table_id = f"TBL-{self.pk:05d}"
            Table.objects.filter(pk=self.pk).update(table_id=self.table_id)

    def __str__(self):
        return f"{self.restaurant.name} - Table {self.table_number}"

    class Meta:
        unique_together = ('restaurant', 'table_number')


class Reservation(BookingFieldsMixin):
    """Real customer transaction record — stays a table."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        ON_HOLD = 'ON_HOLD', 'On Hold (Awaiting Payment)'
        RESERVED = 'RESERVED', 'Reserved'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        DECLINED = 'DECLINED', 'Declined'
        REJECTED = 'REJECTED', 'Rejected'
        RETURNED = 'RETURNED', 'Returned'
        MODIFIED = 'MODIFIED', 'Modified'
        CHECKED_IN = 'CHECKED_IN', 'Checked-In'
        CHECKED_OUT = 'CHECKED_OUT', 'Checked-Out'
        USED = 'USED', 'Used'
        CANCELLED = 'CANCELLED', 'Cancelled'
        COMPLETED = 'COMPLETED', 'Completed'

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )

    class Occasion(models.TextChoices):
        NONE = 'NONE', 'None'
        BIRTHDAY = 'BIRTHDAY', 'Birthday'
        ANNIVERSARY = 'ANNIVERSARY', 'Anniversary'
        BUSINESS = 'BUSINESS', 'Business'
        DATE = 'DATE', 'Date / Romantic'
        GRADUATION = 'GRADUATION', 'Graduation'
        FAMILY_REUNION = 'FAMILY_REUNION', 'Family Reunion'
        DEBUT = 'DEBUT', 'Debut'
        ENGAGEMENT = 'ENGAGEMENT', 'Engagement'
        CHRISTENING = 'CHRISTENING', 'Christening'
        HOLIDAY_CELEBRATION = 'HOLIDAY_CELEBRATION', 'Holiday Celebration'
        CASUAL_DINING = 'CASUAL_DINING', 'Casual Dining'
        OTHER = 'OTHER', 'Other'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='restaurant_reservations')
    table = models.ForeignKey(Table, on_delete=models.PROTECT, related_name='reservations')
    reservation_datetime = models.DateTimeField()
    number_of_guests = models.PositiveIntegerField(default=1)
    seating_preference = models.CharField(max_length=10, choices=SEATING_PREFERENCE_CHOICES, blank=True)
    occasion = models.CharField(max_length=30, choices=OCCASION_CHOICES, default='NONE')
    additional_notes = models.TextField(blank=True)
    deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    manager_remarks = models.TextField(blank=True, help_text="Remarks from the restaurant on confirm/decline (FR Module 11)")
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-reservation_datetime']

    @property
    def primary_guest_name(self):
        """Primary guest/booking contact = the account holder."""
        return self.customer.get_full_name() or self.customer.username

    @property
    def contact_number(self):
        """Booking contact number reused from the account (BR-003)."""
        return self.customer.contact_number

    def __str__(self):
        return f"Reservation {self.booking_reference}"
