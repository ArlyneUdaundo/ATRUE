from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus
from atrue_core.slugs import SlugByNameMixin

RESORT_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNDER_MAINTENANCE', 'Under Maintenance'),
]

UNIT_TYPE_CHOICES = [
    ('ROOM', 'Room'),
    ('VILLA', 'Villa'),
    ('SUITE', 'Suite'),
    ('CABANA', 'Cabana'),
    ('OTHER', 'Other'),
]

UNIT_STATUS_CHOICES = [
    ('AVAILABLE', 'Available'),
    ('OCCUPIED', 'Occupied'),
    ('RESERVED', 'Reserved'),
    ('MAINTENANCE', 'Under Maintenance'),
]

SERVICE_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNAVAILABLE', 'Unavailable'),
]


class Resort(SlugByNameMixin, models.Model):
    """Real entity managed by admins (Establishment Management module) —
    each row has its own contact info and location, so this stays a
    table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'

    name = models.CharField(max_length=150)
    resort_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                 verbose_name="Resort ID")
    country = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    municipality = models.CharField(max_length=100, blank=True)
    barangay = models.CharField(max_length=100, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    operating_schedule = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=RESORT_STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.resort_id:
            self.resort_id = f"RSR-{self.pk:05d}"
            Resort.objects.filter(pk=self.pk).update(resort_id=self.resort_id)

    @property
    def location(self):
        return ', '.join(filter(None, [self.country, self.province, self.municipality, self.barangay])) or 'Location not set'

    def __str__(self):
        return self.name


class ResortPhoto(models.Model):
    """Multiple photos for a resort listing/detail gallery."""

    resort = models.ForeignKey(Resort, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='resort_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            ResortPhoto.objects.filter(resort=self.resort).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.resort.name} - {self.image}"


class RoomVilla(models.Model):
    """Each unit has its own number, capacity, and rate, and its status
    changes with bookings — a real record, not a fixed option, so it
    stays a table."""

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        OCCUPIED = 'OCCUPIED', 'Occupied'
        RESERVED = 'RESERVED', 'Reserved'
        MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

    class UnitType(models.TextChoices):
        ROOM = 'ROOM', 'Room'
        VILLA = 'VILLA', 'Villa'
        SUITE = 'SUITE', 'Suite'
        CABANA = 'CABANA', 'Cabana'
        OTHER = 'OTHER', 'Other'

    resort = models.ForeignKey(Resort, on_delete=models.CASCADE, related_name='units')
    unit_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                               verbose_name="Unit ID")
    unit_type = models.CharField(max_length=10, choices=UNIT_TYPE_CHOICES, default='ROOM')
    unit_number = models.CharField(max_length=100)
    capacity_adults = models.PositiveIntegerField(default=2)
    capacity_children = models.PositiveIntegerField(default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    additional_guest_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    features = models.TextField(blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=UNIT_STATUS_CHOICES, default='AVAILABLE')

    class Meta:
        unique_together = ('resort', 'unit_number')
        ordering = ['unit_number']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.unit_id:
            self.unit_id = f"UNT-{self.pk:05d}"
            RoomVilla.objects.filter(pk=self.pk).update(unit_id=self.unit_id)

    @property
    def capacity(self):
        return self.capacity_adults + self.capacity_children

    def __str__(self):
        return f"{self.resort.name} - {self.get_unit_type_display()} {self.unit_number}"


class UnitPhoto(models.Model):
    """Multiple photos per room/villa (FR-008: Photos - Image attachment, multiple).
    Each row is its own uploaded image, so this stays a table."""

    unit = models.ForeignKey(RoomVilla, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='resort_unit_photos/')
    caption = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return f"{self.unit} - {self.image}"


class AdditionalGuest(models.Model):
    """Additional guest per unit (FR-010: Additional Guest information).
    Each row is a specific person tied to a reservation, so this stays
    a table."""

    reservation = models.ForeignKey('Reservation', on_delete=models.CASCADE, related_name='additional_guests')
    unit = models.ForeignKey('RoomVilla', null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned_guests')
    selection_order = models.PositiveSmallIntegerField(null=True, blank=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    contact = models.CharField(max_length=20, blank=True)
    adults = models.PositiveSmallIntegerField(default=1)
    children = models.PositiveSmallIntegerField(default=0)
    special_requests = models.TextField(blank=True)
    country = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['selection_order', 'pk']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Service(models.Model):
    """Per-resort rate/hours are admin-managed data (Establishment
    Management CRUD), so this stays a table rather than fixed choices."""

    class ServiceStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNAVAILABLE = 'UNAVAILABLE', 'Unavailable'

    resort = models.ForeignKey(Resort, on_delete=models.CASCADE, related_name='services')
    service_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                  verbose_name="Service ID")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    capacity = models.PositiveIntegerField(default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    operating_hours = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=SERVICE_STATUS_CHOICES, default='ACTIVE')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.service_id:
            self.service_id = f"RSV-{self.pk:05d}"
            Service.objects.filter(pk=self.pk).update(service_id=self.service_id)

    def __str__(self):
        return self.name


class Reservation(BookingFieldsMixin):
    """Real customer transaction record — stays a table."""

    Status = BookingStatus

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='resort_reservations')
    unit = models.ForeignKey(RoomVilla, on_delete=models.PROTECT, related_name='reservations')
    number_of_units = models.PositiveIntegerField(default=1)
    check_in = models.DateField()
    check_out = models.DateField()
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    number_of_adults = models.PositiveIntegerField(default=1)
    number_of_children = models.PositiveIntegerField(default=0)
    manager_remarks = models.TextField(blank=True, help_text="Remarks from the resort on confirm/decline (FR Module 10)")
    services = models.ManyToManyField(Service, blank=True, related_name='reservations')
    services_note = models.TextField(blank=True, help_text="Note for requested services/activities (FR-010)")

    class Meta:
        ordering = ['-created_at']

    @property
    def primary_guest_name(self):
        """Primary guest = the account holder."""
        return self.customer.get_full_name() or self.customer.username

    @property
    def nights(self):
        return max(1, (self.check_out - self.check_in).days)

    @property
    def number_of_guests(self):
        return self.number_of_adults + self.number_of_children

    def __str__(self):
        return f"Reservation {self.booking_reference}"
