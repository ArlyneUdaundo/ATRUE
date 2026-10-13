from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus
from atrue_core.slugs import SlugByNameMixin
from atrue_core.payment_methods import PAYMENT_METHOD_CHOICES, payment_method_label

TOUR_PACKAGE_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('EXPIRED', 'Expired'),
    ('FULLY_BOOKED', 'Fully Booked'),
    ('UNDER_MAINTENANCE', 'Under Maintenance'),
]

class TourPackage(SlugByNameMixin, models.Model):
    """Package of valid establishments, activities, and/or services (BR-071).
    Each row has its own pricing, dates, and inclusions, so this stays a
    table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        EXPIRED = 'EXPIRED', 'Expired'
        FULLY_BOOKED = 'FULLY_BOOKED', 'Fully Booked'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'

    establishment = models.ForeignKey(
        'establishments.Establishment',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='tour_packages',
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    destination_name = models.CharField(max_length=255, blank=True)
    destination_country = models.CharField(max_length=100, blank=True, default='')
    destination_province = models.CharField(max_length=100, blank=True)
    destination_city = models.CharField(max_length=100, blank=True)

    duration_days = models.PositiveIntegerField(default=1)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Final package price (BR-080)")
    extra_person_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            help_text="Charge per additional head beyond included headcount (BR-081)")

    included_headcount = models.PositiveIntegerField(default=1)
    included_adults = models.PositiveIntegerField(default=1)
    included_children = models.PositiveIntegerField(default=0)

    validity_start_date = models.DateField(default=timezone.localdate)
    validity_end_date = models.DateField(default=timezone.localdate)

    inclusions = models.TextField(blank=True, default='')
    exclusions = models.TextField(blank=True, default='')
    included_tour_guide = models.BooleanField(default=False)
    included_other_services = models.TextField(blank=True, default='')
    terms_and_conditions = models.TextField(blank=True, default='')
    cancellation_policy = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=TOUR_PACKAGE_STATUS_CHOICES, default='ACTIVE')

    included_hotels = models.ManyToManyField('hotels.Hotel', blank=True, related_name='tour_packages')
    included_resorts = models.ManyToManyField('resorts.Resort', blank=True, related_name='tour_packages')
    included_flights = models.ManyToManyField('airlines.Flight', blank=True, related_name='tour_packages')
    included_activities = models.ManyToManyField('activities.Activity', blank=True, related_name='tour_packages')
    included_restaurants = models.ManyToManyField('restaurants.Restaurant', blank=True, related_name='tour_packages')
    included_transport = models.ManyToManyField('transportation.Agency', blank=True, related_name='tour_packages')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-pk']

    @property
    def bookable(self):
        return (self.status == 'ACTIVE'
                and self.validity_start_date <= self.validity_end_date)

    def valid_on(self, travel_date):
        return (self.status == 'ACTIVE'
                and self.validity_start_date <= travel_date <= self.validity_end_date)

    def __str__(self):
        return self.name


class TourPackagePhoto(models.Model):
    """Multiple photos for a tour package listing/detail gallery."""

    package = models.ForeignKey(TourPackage, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='tour_package_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            TourPackagePhoto.objects.filter(package=self.package).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.package.name} - {self.image}"


class Booking(BookingFieldsMixin):
    """Tour package booking with headcount adjustment billing (BR-075 to
    BR-081). Real customer transaction record — stays a table."""

    Status = BookingStatus

    class PaymentMethod(models.TextChoices):
        GCASH = 'GCASH', 'GCash'
        MAYA = 'MAYA', 'Maya'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
        CREDIT_CARD = 'CREDIT_CARD', 'Credit Card'
        DEBIT_CARD = 'DEBIT_CARD', 'Debit Card'
        PAYPAL = 'PAYPAL', 'PayPal'
        QR_PH = 'QR_PH', 'QR Ph'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='tour_package_bookings')
    package = models.ForeignKey(TourPackage, on_delete=models.PROTECT, related_name='bookings')
    travel_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    number_of_travelers = models.PositiveIntegerField(default=1)
    number_of_adults = models.PositiveIntegerField(default=1)
    number_of_children = models.PositiveIntegerField(default=0)
    payment_method = models.CharField(max_length=15, choices=PAYMENT_METHOD_CHOICES, default='GCASH')

    class Meta:
        ordering = ['-created_at']

    @property
    def primary_traveler_name(self):
        return self.customer.get_full_name() or self.customer.username

    def get_payment_method_display(self):
        return payment_method_label(self.payment_method)

    @property
    def contact_number(self):
        return self.customer.contact_number

    @property
    def extra_heads(self):
        return max(0, self.number_of_travelers - self.package.included_headcount)

    @property
    def adjustment_amount(self):
        return _money(self.package.extra_person_rate) * self.extra_heads

    def __str__(self):
        return f"Booking {self.booking_reference}"


class BookingGuest(models.Model):
    """Other traveler on a tour package booking plus their emergency contact."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='guests')
    full_name = models.CharField(max_length=200)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_number = models.CharField(max_length=11, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.full_name


def _money(value):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)
