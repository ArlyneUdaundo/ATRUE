from django.conf import settings
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus
from atrue_core.slugs import SlugByNameMixin
from atrue_core.payment_methods import PAYMENT_METHOD_CHOICES, payment_method_label

ROOM_TYPE_CHOICES = [
    ('SINGLE', 'Single'),
    ('DOUBLE', 'Double'),
    ('TWIN', 'Twin'),
    ('DELUXE', 'Deluxe'),
    ('SUITE', 'Suite'),
    ('FAMILY', 'Family'),
    ('OTHER', 'Other'),
]

ROOM_STATUS_CHOICES = [
    ('AVAILABLE', 'Available'),
    ('OCCUPIED', 'Occupied'),
    ('RESERVED', 'Reserved'),
    ('MAINTENANCE', 'Under Maintenance'),
]

PAYMENT_MODE_CHOICES = PAYMENT_METHOD_CHOICES

PAYMENT_STATUS_UNPAID = 'UNPAID'
PAYMENT_STATUS_PARTIALLY_PAID = 'PARTIALLY_PAID'
PAYMENT_STATUS_FULLY_PAID = 'FULLY_PAID'

PAYMENT_STATUS_CHOICES = [
    (PAYMENT_STATUS_UNPAID, 'Unpaid'),
    (PAYMENT_STATUS_PARTIALLY_PAID, 'Partially Paid'),
    (PAYMENT_STATUS_FULLY_PAID, 'Fully Paid'),
]

HOTEL_STATUS_CHOICES = [
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

AMENITY_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNAVAILABLE', 'Unavailable'),
]


class Hotel(SlugByNameMixin, models.Model):
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
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    operating_schedule = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=HOTEL_STATUS_CHOICES, default='ACTIVE')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_hotels',
        editable=False,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    ACC_TYPE = 'HOTEL'

    @property
    def accommodation_type(self):
        return 'Hotel'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.establishment_id:
            self.establishment_id = f"HTL-{self.pk:05d}"
            Hotel.objects.filter(pk=self.pk).update(establishment_id=self.establishment_id)

    @property
    def location(self):
        return ', '.join(filter(None, [self.country, self.province, self.municipality, self.barangay])) or 'Location not set'

    def __str__(self):
        return self.name


class HotelPhoto(models.Model):
    """Multiple photos for a hotel listing/detail gallery."""

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='hotel_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            HotelPhoto.objects.filter(hotel=self.hotel).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.hotel.name} - {self.image}"


class Room(models.Model):
    class RoomStatus(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        OCCUPIED = 'OCCUPIED', 'Occupied'
        RESERVED = 'RESERVED', 'Reserved'
        MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

    class RoomType(models.TextChoices):
        SINGLE = 'SINGLE', 'Single'
        DOUBLE = 'DOUBLE', 'Double'
        TWIN = 'TWIN', 'Twin'
        DELUXE = 'DELUXE', 'Deluxe'
        SUITE = 'SUITE', 'Suite'
        FAMILY = 'FAMILY', 'Family'
        OTHER = 'OTHER', 'Other'

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='rooms')
    room_number = models.CharField(max_length=20)
    room_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                               verbose_name="Room ID")
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES, default='SINGLE')
    capacity_adults = models.PositiveIntegerField(default=2)
    capacity_children = models.PositiveIntegerField(default=0)
    max_guest_capacity = models.PositiveIntegerField(default=0, help_text='Maximum guests allowed in the room. 0 means the standard capacity is the maximum.')
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    additional_guest_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    features = models.TextField(blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=ROOM_STATUS_CHOICES, default='AVAILABLE')

    class Meta:
        unique_together = ('hotel', 'room_number')
        ordering = ['room_number']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.room_id:
            # Legacy/imported rows can have primary keys that overlap an ID
            # already assigned to a different room. Keep the familiar RID
            # format, but skip any value already in use.
            sequence = self.pk
            candidate = f"RID-{sequence:05d}"
            while Room.objects.filter(room_id=candidate).exclude(pk=self.pk).exists():
                sequence += 1
                candidate = f"RID-{sequence:05d}"
            self.room_id = candidate
            Room.objects.filter(pk=self.pk).update(room_id=self.room_id)

    @property
    def capacity(self):
        return self.capacity_adults + self.capacity_children

    @property
    def maximum_capacity(self):
        return max(self.capacity, self.max_guest_capacity or 0)

    def __str__(self):
        return f"{self.hotel.name} - Room {self.room_number} ({self.get_room_type_display()})"


class RoomPhoto(models.Model):
    """Multiple photos per room (FR-003: Photos - Attachment (Image, Multiple))."""

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='room_photos/')
    caption = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return f"{self.room} - {self.image}"


class AdditionalGuest(models.Model):
    """Additional guest per room (FR-006: Additional guest information)."""

    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='additional_guests')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Service(models.Model):
    class ServiceStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNAVAILABLE = 'UNAVAILABLE', 'Unavailable'

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='services')
    name = models.CharField(max_length=100)
    service_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                 verbose_name="Service ID")
    description = models.TextField(blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    operating_hours = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=SERVICE_STATUS_CHOICES, default='ACTIVE')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.service_id:
            self.service_id = f"SVC-{self.pk:05d}"
            Service.objects.filter(pk=self.pk).update(service_id=self.service_id)

    def __str__(self):
        return self.name


class Amenity(models.Model):
    class AmenityStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNAVAILABLE = 'UNAVAILABLE', 'Unavailable'

    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='amenities')
    name = models.CharField(max_length=100)
    amenity_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                 verbose_name="Amenity ID")
    description = models.TextField(blank=True)
    operating_hours = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=AMENITY_STATUS_CHOICES, default='ACTIVE')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.amenity_id:
            self.amenity_id = f"AMN-{self.pk:05d}"
            Amenity.objects.filter(pk=self.pk).update(amenity_id=self.amenity_id)

    def __str__(self):
        return self.name


class Booking(BookingFieldsMixin):
    Status = BookingStatus

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='hotel_bookings')
    rooms = models.ManyToManyField(Room, through='BookingRoom', related_name='bookings')
    checked_in_at = models.DateTimeField(null=True, blank=True, editable=False)
    checked_out_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']

    @property
    def primary_guest_name(self):
        """Primary guest = the account holder (BR-029)."""
        return self.customer.get_full_name() or self.customer.username

    @property
    def check_in(self):
        """Earliest check-in across room entries."""
        return min((e.check_in for e in self.room_entries.all()), default=None)

    @property
    def check_out(self):
        """Latest check-out across room entries."""
        return max((e.check_out for e in self.room_entries.all()), default=None)

    @property
    def number_of_adults(self):
        return sum(e.number_of_adults for e in self.room_entries.all())

    @property
    def number_of_children(self):
        return sum(e.number_of_children for e in self.room_entries.all())

    @property
    def nights(self):
        entry = self.room_entries.first()
        if entry is None:
            return 0
        return max(1, (entry.check_out - entry.check_in).days)

    @property
    def number_of_rooms(self):
        return self.room_entries.count()

    @property
    def number_of_guests(self):
        return self.number_of_adults + self.number_of_children

    @property
    def room_bill(self):
        """Sum of Room Bill across every booked room in this booking (BR-032)."""
        return sum((entry.room_bill for entry in self.room_entries.all()), 0)

    @property
    def services_bill(self):
        """Sum of Services Bill across every booked room in this booking (BR-032)."""
        return sum((entry.services_bill for entry in self.room_entries.all()), 0)

    @property
    def amenities_bill(self):
        """Sum of Amenities Bill across every booked room in this booking (BR-032)."""
        return sum((entry.amenities_bill for entry in self.room_entries.all()), 0)

    @property
    def total_bill(self):
        """Total Bill = Room Bill + Services Bill + Amenities Bill (BR-032)."""
        return self.room_bill + self.services_bill + self.amenities_bill

    @property
    def total_paid(self):
        """Amount settled for this booking.

        Payments are recorded centrally as ``transactions.Payment`` rows linked
        to the booking's Bill (see ``atrue_core.services.checkout`` /
        ``record_payment``), so the stored ``amount_paid`` field is the primary
        source. Legacy ``hotels.Payment`` rows are still summed when present.
        """
        settled = sum((p.amount for p in self.payments.all()), 0)
        return settled or self.amount_paid

    @property
    def balance_due(self):
        """Balance Due = Total Bill - Downpayment (generalized to all payments so far) (BR-032)."""
        return self.total_bill - self.total_paid

    @property
    def payment_status(self):
        """Derived payment status, mirroring BR-033's example (Unpaid / Partially Paid / Fully Paid)."""
        if self.total_paid <= 0:
            return PAYMENT_STATUS_UNPAID
        if self.balance_due <= 0:
            return PAYMENT_STATUS_FULLY_PAID
        return PAYMENT_STATUS_PARTIALLY_PAID

    def __str__(self):
        return f"Booking {self.booking_reference}"


class BookingRoom(models.Model):
    """A booked room inside a Booking, with its own dates/guests (BR-032)."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='room_entries')
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name='booking_entries')
    selection_order = models.PositiveSmallIntegerField(null=True, blank=True)
    check_in = models.DateField()
    check_out = models.DateField()
    number_of_adults = models.PositiveIntegerField(default=1)
    number_of_children = models.PositiveIntegerField(default=0)
    guest_first_name = models.CharField(max_length=100, blank=True)
    guest_middle_name = models.CharField(max_length=100, blank=True)
    guest_last_name = models.CharField(max_length=100, blank=True)
    guest_email = models.EmailField(blank=True)
    guest_contact = models.CharField(max_length=30, blank=True)
    guest_special_request = models.TextField(blank=True)
    services = models.ManyToManyField(
        Service, through='BookedService', blank=True, related_name='bookings'
    )
    amenities = models.ManyToManyField(
        Amenity, through='BookedAmenity', blank=True, related_name='bookings'
    )

    class Meta:
        ordering = ['selection_order', 'pk']
        unique_together = ('booking', 'room')

    @property
    def nights(self):
        return max(1, (self.check_out - self.check_in).days)

    @property
    def total_guests(self):
        return self.number_of_adults + self.number_of_children

    @property
    def additional_guest_count(self):
        """Number of guests above the room's included capacity."""
        return max(0, self.total_guests - self.room.capacity)

    @property
    def has_additional_guests(self):
        return self.additional_guest_count > 0

    @property
    def additional_guest_total(self):
        return self.room.additional_guest_charge * self.additional_guest_count * self.nights

    @property
    def effective_room_rate(self):
        return self.room.rate + (self.room.additional_guest_charge * self.additional_guest_count)

    @property
    def room_bill(self):
        """Room rate plus one configured extra-guest charge per extra guest per night."""
        return (self.room.rate * self.nights) + self.additional_guest_total

    @property
    def services_bill(self):
        """Sum of all booked service prices for this room entry (BR-032)."""
        return sum((line.price_at_booking for line in self.booked_services.all()), 0)

    @property
    def amenities_bill(self):
        """Sum of all booked amenity prices for this room entry (BR-032)."""
        return sum((line.price_at_booking for line in self.booked_amenities.all()), 0)

    @property
    def total_bill(self):
        """Total Bill = Room Bill + Services Bill + Amenities Bill, per room entry (BR-032)."""
        return self.room_bill + self.services_bill + self.amenities_bill

    def __str__(self):
        return f"{self.booking} -> {self.room.room_number}"


class BookedService(models.Model):
    """Junction table: services checked for a specific BookingRoom.

    Stores a price snapshot so later changes to Service.rate don't
    retroactively alter past bookings/invoices.
    """

    booking_room = models.ForeignKey(BookingRoom, on_delete=models.CASCADE, related_name='booked_services')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='booking_service_lines')
    price_at_booking = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ('booking_room', 'service')

    def __str__(self):
        return f"{self.booking_room} - {self.service.name}"


class BookedAmenity(models.Model):
    """Junction table: amenities checked for a specific BookingRoom.

    Stores a price snapshot so later changes to Amenity pricing don't
    retroactively alter past bookings/invoices.
    """

    booking_room = models.ForeignKey(BookingRoom, on_delete=models.CASCADE, related_name='booked_amenities')
    amenity = models.ForeignKey(Amenity, on_delete=models.PROTECT, related_name='booking_amenity_lines')
    price_at_booking = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        unique_together = ('booking_room', 'amenity')

    def __str__(self):
        return f"{self.booking_room} - {self.amenity.name}"


class Payment(models.Model):
    """A single payment/settlement applied to a Booking (BR-033).

    A booking can have more than one Payment record (e.g. an initial
    downpayment, followed by a later full settlement), so this is kept as
    its own table with a FK to Booking rather than fields on Booking itself.
    """

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name='payments')
    mode_of_payment = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_UNPAID)
    reference_number = models.CharField(max_length=100, blank=True)
    payment_date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['payment_date']

    def __str__(self):
        return f"{self.booking} - {self.get_mode_of_payment_display()} - {self.amount}"

    def get_mode_of_payment_display(self):
        return payment_method_label(self.mode_of_payment)
