from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus
from atrue_core.slugs import SlugByNameMixin

STAYCATION_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNDER_MAINTENANCE', 'Under Maintenance'),
]

SERVICE_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNAVAILABLE', 'Unavailable'),
]


class Staycation(SlugByNameMixin, models.Model):
    """Real entity managed by admins (Establishment Management module) —
    each row has its own contact info, capacity, and rate, so this stays
    a table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'

    name = models.CharField(max_length=150)
    establishment_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                       verbose_name="Establishment ID")
    country = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    municipality = models.CharField(max_length=100, blank=True)
    barangay = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(default=1)
    capacity_adults = models.PositiveIntegerField(default=1, help_text="Max number of adults (FR-011)")
    capacity_children = models.PositiveIntegerField(default=0, help_text="Max number of children (FR-011)")
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    house_rules = models.TextField(blank=True, help_text="House rules / schedule (FR-011)")
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STAYCATION_STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    @property
    def accommodation_type(self):
        return 'Staycation'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.establishment_id:
            self.establishment_id = f"STC-{self.pk:05d}"
            Staycation.objects.filter(pk=self.pk).update(establishment_id=self.establishment_id)

    @property
    def location(self):
        return ', '.join(filter(None, [self.country, self.province, self.municipality, self.barangay])) or 'Location not set'

    def __str__(self):
        return self.name


class StaycationPhoto(models.Model):
    """Multiple photos for a staycation listing/detail gallery."""

    staycation = models.ForeignKey(Staycation, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='staycation_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            StaycationPhoto.objects.filter(staycation=self.staycation).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staycation.name} - {self.image}"


class BlockOutDate(models.Model):
    """Each row is a specific date range an admin blocked off — a real
    record, not an option set, so this stays a table."""

    staycation = models.ForeignKey(Staycation, on_delete=models.CASCADE, related_name='blocked_dates')
    start_date = models.DateField()
    end_date = models.DateField()

    def __str__(self):
        return f"{self.staycation.name}: {self.start_date} to {self.end_date}"


class Service(models.Model):
    """Per-staycation rate/hours are admin-managed data (Establishment
    Management CRUD), so this stays a table rather than fixed choices."""

    class ServiceStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNAVAILABLE = 'UNAVAILABLE', 'Unavailable'

    staycation = models.ForeignKey(Staycation, on_delete=models.CASCADE, related_name='services')
    name = models.CharField(max_length=100)  # Self check-in, Housekeeping, Early check-in, Late check-out
    service_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                 verbose_name="Service ID")
    description = models.TextField(blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    operating_hours = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=SERVICE_STATUS_CHOICES, default='ACTIVE')

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.service_id:
            self.service_id = f"SVC-{self.pk:05d}"
            Service.objects.filter(pk=self.pk).update(service_id=self.service_id)

    def __str__(self):
        return self.name


class Reservation(BookingFieldsMixin):
    """Real customer transaction record — stays a table."""

    Status = BookingStatus

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='staycation_reservations')
    staycation = models.ForeignKey(Staycation, on_delete=models.PROTECT, related_name='reservations')
    check_in = models.DateField()
    check_out = models.DateField()
    number_of_adults = models.PositiveIntegerField(default=1)
    number_of_children = models.PositiveIntegerField(default=0)
    services = models.ManyToManyField(Service, blank=True, related_name='reservations')
    checked_in_at = models.DateTimeField(null=True, blank=True, editable=False)
    checked_out_at = models.DateTimeField(null=True, blank=True, editable=False)

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


class AdditionalGuest(models.Model):
    """Additional guest per staycation reservation (FR-013: Additional
    Guest information). Each row is a specific person tied to a
    reservation, so this stays a table."""

    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name='additional_guests')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"