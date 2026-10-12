from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus

AGENCY_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNDER_MAINTENANCE', 'Under Maintenance'),
]

VEHICLE_TYPE_CHOICES = [
    ('CAR', 'Car'),
    ('VAN', 'Van'),
    ('BUS', 'Bus'),
    ('PUV', 'Public Utility Vehicle'),
    ('OTHER', 'Other'),
]

VEHICLE_STATUS_CHOICES = [
    ('AVAILABLE', 'Available'),
    ('IN_USE', 'In Use'),
    ('MAINTENANCE', 'Under Maintenance'),
]

ROADWORTHINESS_CHOICES = [
    ('ROADWORTHY', 'Roadworthy'),
    ('NOT_ROADWORTHY', 'Not Roadworthy'),
    ('PENDING', 'Pending Inspection'),
]

DRIVER_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
]


class Agency(models.Model):
    """Real entity managed by admins (Establishment Management module) —
    each row has its own contact info and service areas, so this stays a
    table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'

    name = models.CharField(max_length=150)
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True, help_text="Street address line")
    country = models.CharField(max_length=100, blank=True, default='')
    barangay = models.CharField(max_length=100, blank=True)
    municipality = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    areas = models.TextField(blank=True, help_text="Areas served (multi-select equivalent, FR-021)")
    description = models.TextField(blank=True)
    operating_hours = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=AGENCY_STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    @property
    def location(self):
        return ', '.join(filter(None, [self.country, self.address, self.barangay, self.municipality, self.province])) or 'Location not set'

    def __str__(self):
        return self.name


class AgencyPhoto(models.Model):
    """Multiple photos for a transport agency listing/detail gallery."""

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='agency_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            AgencyPhoto.objects.filter(agency=self.agency).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.agency.name} - {self.image}"


class Vehicle(models.Model):
    """Each vehicle has a unique plate_number, rate, and status that
    changes over time — a real record, not a fixed option, so it stays
    a table."""

    class VehicleType(models.TextChoices):
        CAR = 'CAR', 'Car'
        VAN = 'VAN', 'Van'
        BUS = 'BUS', 'Bus'
        PUV = 'PUV', 'Public Utility Vehicle'
        OTHER = 'OTHER', 'Other'

    class VehicleStatus(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        IN_USE = 'IN_USE', 'In Use'
        MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='vehicles')
    vehicle_type = models.CharField(max_length=10, choices=VEHICLE_TYPE_CHOICES, default='VAN')
    vehicle_name = models.CharField(max_length=100, blank=True, default='')
    image = models.ImageField(upload_to='transport_vehicles/', blank=True)
    plate_number = models.CharField(max_length=20, unique=True)
    capacity = models.PositiveIntegerField()
    rate_per_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    roadworthiness = models.CharField(max_length=15, choices=ROADWORTHINESS_CHOICES, default='ROADWORTHY')
    status = models.CharField(max_length=15, choices=VEHICLE_STATUS_CHOICES, default='AVAILABLE')

    def __str__(self):
        return f"{self.get_vehicle_type_display()} - {self.plate_number}"

    @property
    def label(self):
        return self.vehicle_name or self.get_vehicle_type_display()


class Driver(models.Model):
    """Each driver has a unique license_number and personal accreditation
    details — a real record, not a fixed option, so it stays a table."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='drivers')
    full_name = models.CharField(max_length=150)
    license_number = models.CharField(max_length=30, unique=True)
    license_type = models.CharField(max_length=50, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    accreditation = models.TextField(blank=True, help_text="Accreditation / qualification details (FR-023)")
    contact_number = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=DRIVER_STATUS_CHOICES, default='ACTIVE')

    def __str__(self):
        return self.full_name


class Booking(BookingFieldsMixin):
    """Real customer transaction record — stays a table."""

    Status = BookingStatus

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='transport_bookings')
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name='bookings')
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    pickup_location = models.CharField(max_length=255)
    drop_off_location = models.CharField(max_length=255)
    distance_km = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    schedule = models.DateTimeField()
    duration_hours = models.PositiveIntegerField(default=3)
    passengers = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-created_at']

    @property
    def primary_guest_name(self):
        """Primary guest = the account holder."""
        return self.customer.get_full_name() or self.customer.username

    def __str__(self):
        return f"Booking {self.booking_reference}"
