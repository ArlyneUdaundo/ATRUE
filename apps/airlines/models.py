from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from atrue_core.models import BookingFieldsMixin, BookingStatus
from airlines.fleet_data import BODY_CLASSES, CABIN_LABELS
from airlines.itineraries import (
    DEFAULT_TIMEZONE_FALLBACK as DEFAULT_AIRPORT_TIMEZONE,
    format_duration,
    itinerary_timing,
    total_price,
)
from airlines.layouts import CABIN_FARE_FIELDS, FARE_CLASSES, capacity_for


AIRLINE_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNDER_MAINTENANCE', 'Under Maintenance'),
]

# The airframe family a type belongs to.  This is a property of the *type*, not
# of the operator, so it lives on AircraftType rather than on Aircraft — a
# Cebu Pacific A320neo and a PAL A320 are both narrow-bodies.
AIRCRAFT_TYPE_CHOICES = BODY_CLASSES

AIRCRAFT_STATUS_CHOICES = [
    ('AVAILABLE', 'Available'),
    ('ASSIGNED', 'Assigned'),
    ('MAINTENANCE', 'Under Maintenance'),
    ('INACTIVE', 'Inactive'),
]

SERVICE_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('INACTIVE', 'Inactive'),
    ('SUSPENDED', 'Suspended'),
    ('UNAVAILABLE', 'Unavailable'),
]

FLIGHT_STATUS_CHOICES = [
    ('SCHEDULED', 'Scheduled'),
    ('DELAYED', 'Delayed'),
    ('CANCELLED', 'Cancelled'),
    ('COMPLETED', 'Completed'),
]

#: One segment is a direct flight, two or more is a connecting one.  The value
#: is stored on ``FlightItinerary`` because the *number of legs* — not a label —
#: is what decides it, and a label would let the two drift apart.
FLIGHT_TYPE_CHOICES = [
    ('DIRECT', 'Direct'),
    ('CONNECTING', 'Connecting'),
]

ROUTE_SCOPE_CHOICES = [
    ('DOMESTIC', 'Domestic'),
    ('INTERNATIONAL', 'International'),
]

FARE_CLASS_CHOICES = [
    ('FIRST_CLASS', 'First Class'),
    ('BUSINESS', 'Business Class'),
    ('PREMIUM_ECONOMY', 'Premium Economy'),
    ('ECONOMY', 'Economy'),
]

TRAVEL_DOCUMENT_TYPE_CHOICES = [
    ('PASSPORT', 'Passport'),
    ('OTHER', 'Other'),
]

class TripType(models.TextChoices):
    """Shared by Flight (what the airline sells) and Booking (what the
    passenger bought), so both always agree on the same values."""

    ONE_WAY = 'ONE_WAY', 'One-Way'
    ROUND_TRIP = 'ROUND_TRIP', 'Round-Trip'


class TripRole(models.TextChoices):
    """Which leg of a round trip a ``Flight`` row is.

    A round trip is stored as two real flight rows rather than one row with a
    return date, because the two legs can be operated by different aircraft and
    therefore have different cabins and seat maps.  The outbound leg carries the
    ``ROUND_TRIP`` trip type; the return leg is marked here and pointed at its
    partner through :attr:`Flight.paired_flight`.
    """

    OUTBOUND = 'OUTBOUND', 'Outbound'
    RETURN = 'RETURN', 'Return'


class TripSegment(models.TextChoices):
    """Which leg of the journey a booked seat belongs to."""

    DEPARTURE = 'DEPARTURE', 'Departure'
    RETURN = 'RETURN', 'Return'


class Manufacturer(models.Model):
    """The aircraft brand: Airbus, Boeing, ATR.

    Kept separate from ``AircraftType`` so a manager can list "every type Airbus
    builds" without string-matching on the model name.
    """

    name = models.CharField(max_length=80, unique=True)
    country = models.CharField(max_length=80, blank=True, default='')
    code = models.CharField(max_length=12, blank=True, default='')

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Manufacturers'

    def __str__(self):
        return self.name


class AircraftType(models.Model):
    """An airframe a carrier can operate, e.g. Airbus A350-900.

    Global reference data — the same row is shared by every airline that flies
    it, which is what makes a type belong to a *fleet* rather than to one
    aircraft.  The cabin an individual aircraft is configured with lives on
    ``SeatLayout``, not here, because two airlines flying the same type sell
    different cabins.
    """

    class BodyClass(models.TextChoices):
        NARROW_BODY = 'NARROW_BODY', 'Narrow-Body'
        WIDE_BODY = 'WIDE_BODY', 'Wide-Body'
        REGIONAL = 'REGIONAL', 'Regional'
        TURBOPROP = 'TURBOPROP', 'Turboprop'
        PRIVATE_JET = 'PRIVATE_JET', 'Private Jet'
        OTHER = 'OTHER', 'Other'

    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.PROTECT, related_name='aircraft_types',
        verbose_name="Aircraft brand")
    model_name = models.CharField(
        max_length=80, help_text="Variant only — the brand is the foreign key (A350-900)")
    body_class = models.CharField(
        max_length=15, choices=BodyClass.choices, default=BodyClass.NARROW_BODY,
        db_index=True)
    typical_capacity = models.PositiveIntegerField(
        default=0, verbose_name="Typical seats",
        help_text="Reference seat count for this type, before an operator's cabin "
                  "configuration is applied.")
    is_active = models.BooleanField(
        default=True,
        help_text="Cleared to be added to an airline's fleet. Untick to retire the "
                  "type without touching the aircraft already flying it.")

    class Meta:
        ordering = ['manufacturer__name', 'model_name']
        constraints = [
            models.UniqueConstraint(
                fields=['manufacturer', 'model_name'],
                name='unique_manufacturer_model',
            ),
        ]

    @property
    def label(self):
        """'Airbus A350-900' — what every dropdown and the seat map show."""
        return f"{self.manufacturer.name} {self.model_name}"

    def __str__(self):
        return self.label


class Airline(models.Model):
    """Real entity managed by admins (Establishment Management module) —
    each row has its own contact info, so this stays a table, not choices."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNDER_MAINTENANCE = 'UNDER_MAINTENANCE', 'Under Maintenance'

    name = models.CharField(max_length=150)
    airline_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                 verbose_name="Airline ID")
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    description = models.TextField(blank=True)
    operating_info = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=AIRLINE_STATUS_CHOICES, default='ACTIVE')
    default_aircraft_type = models.ForeignKey(
        AircraftType, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='default_for', verbose_name="Default aircraft type",
        help_text="The type a flight falls back to when a schedule is created before "
                  "an aircraft is assigned. Must be one of this airline's fleet types.")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.airline_id:
            self.airline_id = f"ALN-{self.pk:05d}"
            Airline.objects.filter(pk=self.pk).update(airline_id=self.airline_id)

    def clean(self):
        super().clean()
        if (self.default_aircraft_type_id
                and not self.fleet_entries.filter(
                    aircraft_type_id=self.default_aircraft_type_id).exists()):
            raise ValidationError({
                'default_aircraft_type':
                    f"{self.default_aircraft_type.label} is not in this airline's fleet. "
                    "Add the type to the fleet first."
            })

    @property
    def logo_photo(self):
        """The photo that acts as this airline's official mark.

        Only one image ever need be shown for an airline, and the system
        already keeps those images as :class:`AirlinePhoto` rows. The primary
        one is the logo (that is the convention the search results and tickets
        have always read); a gallery with no primary falls back to its first
        photo. Read through ``self.photos.all()`` so a view that prefetched the
        gallery pays no extra query.
        """
        photos = list(self.photos.all())
        for photo in photos:
            if photo.is_primary:
                return photo
        return photos[0] if photos else None

    @property
    def logo_url(self):
        """URL of the airline logo, or ``''`` when none is stored.

        Templates use this to render a logo wherever airline identity appears;
        an empty value is the signal to show the clean fallback instead.
        """
        photo = self.logo_photo
        if photo is None or not photo.image:
            return ''
        try:
            return photo.image.url
        except (ValueError, NotImplementedError):
            return ''

    def __str__(self):
        return self.name


class AirlinePhoto(models.Model):
    """Multiple photos for an airline listing/detail gallery."""

    airline = models.ForeignKey(Airline, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='airline_photos/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def save(self, *args, **kwargs):
        if self.is_primary:
            AirlinePhoto.objects.filter(airline=self.airline).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.airline.name} - {self.image}"


class AirlineFleet(models.Model):
    """One aircraft type in one airline's fleet.

    This join is what makes the aircraft dropdown airline-scoped: only types an
    airline actually operates are offered, and only they may appear on a flight
    or under an ``Aircraft``.  Adding or removing a row is how a manager changes
    what an airline flies, without touching the types other airlines share.
    """

    airline = models.ForeignKey(Airline, on_delete=models.CASCADE, related_name='fleet_entries')
    aircraft_type = models.ForeignKey(
        AircraftType, on_delete=models.CASCADE, related_name='operators',
        verbose_name="Aircraft type")
    is_primary = models.BooleanField(
        default=False,
        help_text="The type this airline is best known for, and the fallback for a "
                  "flight with no aircraft assigned yet.")
    is_active = models.BooleanField(
        default=True,
        help_text="Untick to retire the type from the fleet while keeping the "
                  "aircraft and flights already on it.")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['airline__name', 'aircraft_type__manufacturer__name',
                    'aircraft_type__model_name']
        constraints = [
            models.UniqueConstraint(
                fields=['airline', 'aircraft_type'],
                name='unique_airline_aircraft_type',
            ),
        ]

    def __str__(self):
        return f"{self.airline.name} · {self.aircraft_type.label}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_primary:
            AirlineFleet.objects.filter(airline=self.airline).exclude(pk=self.pk).update(is_primary=False)
            Airline.objects.filter(pk=self.airline_id).update(default_aircraft_type=self.aircraft_type_id)


class SeatLayout(models.Model):
    """How one airline configures one aircraft type: 'Cebu Pacific A320'.

    A seat map belongs to the *pair*, not to the type, because the same
    A350-900 is a 1-2-1 / 2-2-2 / 3-3 cabin for one operator and a different
    one for the next.  Every ``Aircraft`` of that airline and type points here,
    and every ``Flight`` on that aircraft inherits it — the booking page never
    asks which map to draw, it asks the flight.
    """

    airline = models.ForeignKey(Airline, on_delete=models.CASCADE, related_name='seat_layouts')
    aircraft_type = models.ForeignKey(
        AircraftType, on_delete=models.CASCADE, related_name='seat_layouts',
        verbose_name="Aircraft type")
    name = models.CharField(
        max_length=160, blank=True, default='',
        help_text="Defaults to '<Airline> <Type> Seat Layout'.")
    seat_map = models.CharField(
        max_length=40, blank=True, default='',
        help_text="The cabin blocks, e.g. 3-3 or 1-2-1 / 2-2-2 / 3-3.")
    total_capacity = models.PositiveIntegerField(
        default=0, editable=False, verbose_name="Seat capacity",
        help_text="Every seat in every cabin of this layout, seats the map offers.")
    exit_rows = models.JSONField(default=list, blank=True)
    lavatory_rows = models.JSONField(default=list, blank=True)
    galley_positions = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['airline__name', 'aircraft_type__model_name']
        constraints = [
            models.UniqueConstraint(
                fields=['airline', 'aircraft_type'],
                name='unique_airline_seat_layout',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = f"{self.airline.name} {self.aircraft_type.model_name} Seat Layout"
        super().save(*args, **kwargs)
        # Recount only once the row exists, otherwise the cabins that define the
        # capacity are not there yet and the count comes back as zero.
        if self.pk:
            self.refresh_capacity()

    def compute_capacity(self):
        if not self.pk:
            return self.total_capacity
        return sum(cabin.rows * sum(cabin.blocks) for cabin in self.cabins.all())

    def refresh_capacity(self):
        """Recount the seats after a cabin is added, edited or removed."""
        self.total_capacity = self.compute_capacity()
        SeatLayout.objects.filter(pk=self.pk).update(total_capacity=self.total_capacity)
        return self.total_capacity

    @property
    def label(self):
        return f"{self.airline.name} {self.aircraft_type.label} ({self.seat_map}, {self.total_capacity} seats)"

    def __str__(self):
        return self.name or self.label


class Cabin(models.Model):
    """A fare class within a seat layout: the economy block or the first-class
    cabin, how wide it is and how many rows it has.

    ``blocks`` is the seats per row split by an aisle, so ``[3, 3]`` is 3-3 and
    ``[1, 2, 1]`` is 1-2-1.  ``rows`` is how many rows the cabin has, so its
    seat count is always ``rows * sum(blocks)``.
    """

    class FareClass(models.TextChoices):
        FIRST_CLASS = 'FIRST_CLASS', 'First Class'
        BUSINESS = 'BUSINESS', 'Business Class'
        PREMIUM_ECONOMY = 'PREMIUM_ECONOMY', 'Premium Economy'
        ECONOMY = 'ECONOMY', 'Economy'

    seat_layout = models.ForeignKey(SeatLayout, on_delete=models.CASCADE, related_name='cabins')
    fare_class = models.CharField(
        max_length=20, choices=FareClass.choices, default=FareClass.ECONOMY)
    position = models.PositiveSmallIntegerField(
        default=0, help_text="Order from the nose of the aircraft.")
    blocks = models.JSONField(
        default=list,
        help_text="Seats per row split by an aisle — [3, 3] is 3-3, [1, 2, 1] is 1-2-1.")
    rows = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['seat_layout', 'position']
        constraints = [
            models.UniqueConstraint(
                fields=['seat_layout', 'position'],
                name='unique_cabin_position',
            ),
        ]

    def save(self, *args, **kwargs):
        # ``position`` is always supplied by the caller. It used to be filled in
        # from the current maximum, but the first cabin sits at 0 and 0 is
        # falsy, so the nose cabin was silently renumbered and collided with the
        # next one. Airmail order has to be written down, not guessed.
        super().save(*args, **kwargs)
        self.seat_layout.refresh_capacity()

    @property
    def label(self):
        return CABIN_LABELS.get(self.fare_class, self.get_fare_class_display())

    @property
    def fare_field(self):
        return CABIN_FARE_FIELDS.get(self.fare_class, 'economy_fare')

    @property
    def seat_count(self):
        return self.rows * sum(self.blocks or ())

    @property
    def seat_map(self):
        return '-'.join(str(b) for b in (self.blocks or ()))

    def __str__(self):
        return f"{self.label} ({self.seat_map} × {self.rows})"


class Seat(models.Model):
    """One physical seat on the map.

    Materialised rather than computed so a seat number can be checked with a
    query: the booking page asks "does this flight's layout have a seat 40A?"
    and a stale or forged form posting an impossible number fails that lookup
    instead of reaching a save.
    """

    seat_layout = models.ForeignKey(SeatLayout, on_delete=models.CASCADE, related_name='seats')
    cabin = models.ForeignKey(Cabin, on_delete=models.CASCADE, related_name='seats')
    row_number = models.PositiveIntegerField(
        db_index=True, help_text="Global row from the nose, as on a boarding pass.")
    letter = models.CharField(max_length=2)
    seat_number = models.CharField(
        max_length=8, db_index=True, help_text="Row and letter together, e.g. 40A.")
    position = models.CharField(
        max_length=8, default='window', choices=[
            ('window', 'Window'), ('middle', 'Middle'), ('aisle', 'Aisle')])

    class Meta:
        ordering = ['seat_layout', 'row_number', 'letter']
        constraints = [
            models.UniqueConstraint(
                fields=['seat_layout', 'seat_number'],
                name='unique_seat_per_layout',
            ),
        ]

    def __str__(self):
        return self.seat_number


class Aircraft(models.Model):
    """A single airframe in an airline's fleet, e.g. RP-C3270.

    It belongs to exactly one airline and exactly one type from that airline's
    fleet, and it carries the seat layout that airline flies for that type — so
    assigning a flight to an aircraft is all it takes for the booking page to
    know which map to draw.
    """

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'
        INACTIVE = 'INACTIVE', 'Inactive'

    airline = models.ForeignKey(Airline, on_delete=models.CASCADE, related_name='aircrafts')
    aircraft_type = models.ForeignKey(
        AircraftType, on_delete=models.PROTECT, related_name='aircraft',
        verbose_name="Aircraft type")
    seat_layout = models.ForeignKey(
        SeatLayout, on_delete=models.PROTECT, related_name='aircraft',
        help_text="The cabin this airframe is fitted out with. Defaults to the "
                  "airline's own layout for the type.")
    aircraft_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                   verbose_name="Aircraft ID")
    tail_number = models.CharField(max_length=20, unique=True)
    seating_capacity = models.PositiveIntegerField(
        editable=False,
        help_text="Taken from the seat layout, so the record and the seat map "
                  "can never disagree.")
    status = models.CharField(max_length=15, choices=AIRCRAFT_STATUS_CHOICES, default='AVAILABLE')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if self.seat_layout_id and not self.seating_capacity:
            self.seating_capacity = self.seat_layout.total_capacity
        super().save(*args, **kwargs)
        if not self.aircraft_id:
            self.aircraft_id = f"ACR-{self.pk:05d}"
            Aircraft.objects.filter(pk=self.pk).update(aircraft_id=self.aircraft_id)

    def clean(self):
        super().clean()
        if not self.aircraft_type_id or not self.seat_layout_id:
            return
        # An airframe may only wear a layout its own airline flies for its own
        # type: an Emirates A380 map can never end up on a Cebu Pacific A320.
        if self.seat_layout.airline_id != self.airline_id:
            raise ValidationError({
                'seat_layout': "That seat layout belongs to a different airline."})
        if self.seat_layout.aircraft_type_id != self.aircraft_type_id:
            raise ValidationError({
                'seat_layout': "That seat layout is configured for a different "
                               "aircraft type."})
        if not AirlineFleet.objects.filter(
                airline_id=self.airline_id, aircraft_type_id=self.aircraft_type_id).exists():
            raise ValidationError({
                'aircraft_type': f"{self.aircraft_type.label} is not in "
                                 f"{self.airline.name}'s fleet."})

    @property
    def model_name(self):
        return self.aircraft_type.label

    @property
    def body_class(self):
        return self.aircraft_type.body_class

    def get_aircraft_type_display(self):
        return self.aircraft_type.get_body_class_display()

    def get_body_class_display(self):
        return self.aircraft_type.get_body_class_display()

    @property
    def cabin_configuration(self):
        return self.seat_layout.seat_map if self.seat_layout_id else ''

    def __str__(self):
        return f"{self.tail_number} — {self.model_name}"


class Service(models.Model):
    """Per-airline rate/hours are admin-managed data (Establishment
    Management CRUD), so this stays a table rather than fixed choices."""

    class ServiceStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        UNAVAILABLE = 'UNAVAILABLE', 'Unavailable'

    airline = models.ForeignKey(Airline, on_delete=models.CASCADE, related_name='services')
    service_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                  verbose_name="Service ID")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    operating_hours = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=SERVICE_STATUS_CHOICES, default='ACTIVE')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.service_id:
            self.service_id = f"SVX-{self.pk:05d}"
            Service.objects.filter(pk=self.pk).update(service_id=self.service_id)

    def __str__(self):
        return self.name


class Airport(models.Model):
    """Worldwide airport reference data.

    Seeded from the public OurAirports dataset via ``manage.py seed_airports``,
    so flight search and schedules can use any airport on Earth instead of only
    Philippine ones. ``country``/``region``/``city`` are de-normalised display
    text resolved against the existing GeoNames location hierarchy at seed time,
    so the airport list bridges to the worldwide location data without a second
    hierarchy.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'

    airport_id = models.CharField(max_length=12, unique=True, editable=False, null=True,
                                  verbose_name="Airport ID")
    airport_name = models.CharField(max_length=200, db_index=True, verbose_name="Airport name")
    iata_code = models.CharField(max_length=8, blank=True, default='', db_index=True,
                                 verbose_name="IATA code")
    icao_code = models.CharField(max_length=8, blank=True, default='',
                                 verbose_name="ICAO code")
    city = models.CharField(max_length=120, blank=True, default='', db_index=True,
                            verbose_name="City / municipality")
    country = models.CharField(max_length=100, db_index=True, verbose_name="Country")
    country_code = models.CharField(max_length=2, blank=True, default='',
                                    verbose_name="Country code",
                                    help_text="ISO 3166-1 alpha-2 country code.")
    region = models.CharField(max_length=120, blank=True, default='',
                              verbose_name="Region / province / state")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    timezone = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
        help_text="IANA zone the airport's local clock runs on, e.g. Asia/Manila. "
                  "A connecting itinerary needs it to work out the real flight "
                  "time between two airports in different zones.")
    terminals = models.CharField(
        max_length=120, blank=True, default='',
        help_text="Terminals this airport operates, comma separated, e.g. 1, 2, 3. "
                  "Offered as choices when a schedule names a terminal.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['airport_name']
        verbose_name_plural = 'Airports'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.airport_id:
            self.airport_id = f"APT-{self.pk:05d}"
            Airport.objects.filter(pk=self.pk).update(airport_id=self.airport_id)

    def __str__(self):
        return f"{self.airport_name} ({self.iata_code or self.icao_code or '—'})"

    @property
    def code(self):
        return self.iata_code or self.icao_code or ''

    @property
    def short_label(self):
        return ', '.join(p for p in (self.city, self.country) if p)

    @property
    def timezone_name(self):
        """The airport's IANA zone, falling back to the platform default.

        Airports seeded before timezone support have an empty column; they keep
        behaving exactly as before instead of becoming unschedulable.
        """
        return self.timezone or DEFAULT_AIRPORT_TIMEZONE

    @property
    def terminal_list(self):
        """The airport's terminals as a list, for terminal pickers."""
        return [t.strip() for t in (self.terminals or '').split(',') if t.strip()]


class Flight(models.Model):
    """Transactional/schedule data (new record per flight instance) — not
    an option set, so this stays a table."""

    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        DELAYED = 'DELAYED', 'Delayed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        COMPLETED = 'COMPLETED', 'Completed'

    class FareClass(models.TextChoices):
        FIRST_CLASS = 'FIRST_CLASS', 'First Class'
        BUSINESS = 'BUSINESS', 'Business Class'
        PREMIUM_ECONOMY = 'PREMIUM_ECONOMY', 'Premium Economy'
        ECONOMY = 'ECONOMY', 'Economy'

    TripType = TripType

    airline = models.ForeignKey(Airline, on_delete=models.PROTECT, related_name='flights')
    aircraft = models.ForeignKey(Aircraft, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='flights',
                                 help_text="Optional — a flight is a schedule, so it can be "
                                           "created before an aircraft is registered. Whichever "
                                           "aircraft is assigned supplies the seat map.")
    flight_number = models.CharField(max_length=20, blank=True, default='', db_index=True,
                                     help_text="Unique managed flight number (FR-017)")
    origin = models.CharField(max_length=100)
    destination = models.CharField(max_length=100)
    origin_code = models.CharField(max_length=8, blank=True, default='',
                                   verbose_name="Origin airport code",
                                   help_text="Optional IATA-style code (e.g. MNL) shown on the e-ticket")
    destination_code = models.CharField(max_length=8, blank=True, default='',
                                        verbose_name="Destination airport code",
                                        help_text="Optional IATA-style code (e.g. CEB) shown on the e-ticket")
    origin_country = models.CharField(max_length=100, blank=True, default='',
                                      help_text="Origin country, from the ATRUE location hierarchy")
    origin_province = models.CharField(max_length=120, blank=True, default='',
                                       help_text="Origin province / region, from the ATRUE location hierarchy")
    origin_municipality = models.CharField(max_length=120, blank=True, default='',
                                           help_text="Origin city / municipality, from the ATRUE location hierarchy")
    destination_country = models.CharField(max_length=100, blank=True, default='',
                                           help_text="Destination country, from the ATRUE location hierarchy")
    destination_province = models.CharField(max_length=120, blank=True, default='',
                                            help_text="Destination province / region, from the ATRUE location hierarchy")
    destination_municipality = models.CharField(max_length=120, blank=True, default='',
                                                help_text="Destination city / municipality, from the ATRUE location hierarchy")
    origin_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, null=True, blank=True,
        related_name='origin_flights', verbose_name="Origin airport")
    destination_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, null=True, blank=True,
        related_name='destination_flights', verbose_name="Destination airport")
    terminal = models.CharField(max_length=50, blank=True, default='',
                                verbose_name="Departure terminal",
                                help_text="Optional terminal shown on the e-ticket (if available)")
    gate = models.CharField(max_length=50, blank=True, default='',
                            verbose_name="Departure gate",
                            help_text="Optional gate shown on the e-ticket (if available)")
    # ---- Connecting-flight (itinerary segment) columns ----------------------
    # A flight row is one real leg.  A connecting journey is several of these
    # rows tied together by ``itinerary`` and ordered by ``segment_order``, so
    # nothing here duplicates a direct flight's behaviour — a flight with no
    # itinerary keeps working exactly as before.
    itinerary = models.ForeignKey(
        'FlightItinerary', on_delete=models.CASCADE, null=True, blank=True,
        related_name='legs', verbose_name="Itinerary",
        help_text="The journey this leg belongs to. Blank for a standalone "
                  "(direct) flight, which is how existing schedules keep working.")
    segment_order = models.PositiveSmallIntegerField(
        default=1, db_index=True,
        help_text="Position of this leg in its itinerary. 1 is the first leg; "
                  "the arrival airport of each leg must be the departure airport "
                  "of the next.")
    arrival_terminal = models.CharField(
        max_length=50, blank=True, default='', verbose_name="Arrival terminal",
        help_text="Optional arrival terminal (if available)")
    arrival_gate = models.CharField(
        max_length=50, blank=True, default='', verbose_name="Arrival gate",
        help_text="Optional arrival gate (if available)")
    departure_timezone = models.CharField(
        max_length=64, blank=True, default='',
        help_text="IANA zone the origin airport's clock runs on, e.g. Asia/Manila. "
                  "Copied from the airport when the schedule is saved.")
    arrival_timezone = models.CharField(
        max_length=64, blank=True, default='',
        help_text="IANA zone the destination airport's clock runs on.")
    check_in_time = models.TimeField(
        null=True, blank=True, verbose_name="Check-in time",
        help_text="Optional local check-in time at the origin")
    boarding_time = models.TimeField(
        null=True, blank=True, verbose_name="Boarding time",
        help_text="Optional local boarding time at the origin")
    baggage_claim = models.CharField(
        max_length=50, blank=True, default='', verbose_name="Baggage claim",
        help_text="Optional belt / claim area at the destination (if available)")
    segment_duration_minutes = models.PositiveIntegerField(
        default=0, editable=False,
        help_text="Minutes actually in the air on this leg, computed from the "
                  "two airports' time zones. Never typed in by hand.")
    checked_baggage_kg = models.PositiveSmallIntegerField(
        default=0, verbose_name="Checked baggage (kg)",
        help_text="Checked baggage allowance included in the fare, per passenger")
    cabin_baggage_kg = models.PositiveSmallIntegerField(
        default=0, verbose_name="Cabin baggage (kg)",
        help_text="Cabin baggage allowance included in the fare, per passenger")
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    trip_type = models.CharField(
        max_length=15, choices=TripType.choices, default=TripType.ONE_WAY,
        verbose_name="Trip Type",
        help_text="Whether this flight is sold as a one-way or round-trip service")
    trip_role = models.CharField(
        max_length=10, choices=TripRole.choices, default=TripRole.OUTBOUND,
        verbose_name="Trip Role",
        help_text="Which leg of a round trip this row is. Outbound legs carry "
                  "the trip type; the return leg is linked to its partner.")
    round_trip_group = models.UUIDField(
        null=True, blank=True, db_index=True, editable=False,
        help_text="Shared by both legs of a round trip so they can be found "
                  "again without knowing either leg's id")
    paired_flight = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name="Paired Flight",
        help_text="The other leg of this round trip")
    total_capacity = models.PositiveIntegerField(
        default=0, editable=False, verbose_name="Seat capacity",
        help_text="Seats sellable on this flight. Kept in step with the seat layout "
                  "the flight's airline flies.")
    first_class_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    business_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                        verbose_name="Business class fare (₱)")
    premium_economy_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                               verbose_name="Premium economy fare (₱)")
    economy_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    baggage_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                       verbose_name="Baggage rate per kg (₱)",
                                       help_text="Charge per kilogram of extra baggage")
    status = models.CharField(max_length=10, choices=FLIGHT_STATUS_CHOICES, default='SCHEDULED')

    class Meta:
        ordering = ['departure_time']

    def __str__(self):
        if self.itinerary_id and self.segment_order > 1:
            return (f"Segment {self.segment_order}: {self.flight_number} "
                    f"{self.origin} -> {self.destination}")
        return f"{self.flight_number} {self.origin} -> {self.destination}"

    def save(self, *args, **kwargs):
        # The aircraft flying the flight decides the cabin, and the cabin decides
        # how many seats can be sold — so capacity is never typed in by hand.
        seats = capacity_for(self)
        if seats != self.total_capacity:
            self.total_capacity = seats
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {'total_capacity'}
        self.refresh_segment_timing()
        super().save(*args, **kwargs)

    def refresh_segment_timing(self):
        """Recompute the in-air minutes for this leg from the two time zones.

        Runs on every save so a leg's stored duration can never disagree with
        the airports it flies between — including after an airport's timezone
        is corrected.  A direct flight reads exactly the same answer as before,
        because both ends sit in the platform zone unless the airports say
        otherwise.
        """
        timing = itinerary_timing([self])
        leg = timing['legs'][0] if timing['legs'] else {}
        minutes = leg.get('flight_minutes')
        self.segment_duration_minutes = minutes if minutes and minutes > 0 else 0
        if self.origin_airport_id and not self.departure_timezone:
            self.departure_timezone = self.origin_airport.timezone_name
        if self.destination_airport_id and not self.arrival_timezone:
            self.arrival_timezone = self.destination_airport.timezone_name
        return self.segment_duration_minutes

    # ---- Itinerary (connecting flight) helpers ----------------------------
    @property
    def is_itinerary_segment(self):
        """Whether this leg belongs to a connecting journey."""
        return self.itinerary_id is not None

    @property
    def ordered_segments(self):
        """Every leg of this flight's itinerary, in travel order.

        Returns a single-item list for a direct flight, so callers can treat
        "one segment" and "a connecting itinerary" the same way.
        """
        if not self.itinerary_id:
            return [self]
        return list(self.itinerary.ordered_legs)

    @property
    def next_segment(self):
        """The leg flown after this one, or ``None`` on the last leg."""
        segments = self.ordered_segments
        for index, segment in enumerate(segments):
            if segment.pk == self.pk and index + 1 < len(segments):
                return segments[index + 1]
        return None

    @property
    def previous_segment(self):
        """The leg flown before this one, or ``None`` on the first leg."""
        segments = self.ordered_segments
        for index, segment in enumerate(segments):
            if segment.pk == self.pk and index > 0:
                return segments[index - 1]
        return None

    @property
    def layover_after_minutes(self):
        """Minutes on the ground at this leg's destination, before the next."""
        following = self.next_segment
        if following is None:
            return None
        timing = itinerary_timing([self, following])
        layovers = timing['layovers']
        return layovers[0]['minutes'] if layovers else None

    @property
    def layover_after_label(self):
        return format_duration(self.layover_after_minutes)

    @property
    def leg_label(self):
        """``MNL - SIN`` / ``MNL → SIN``, using codes when the airports are known."""
        origin = (self.origin_airport.code if self.origin_airport_id else '') or self.origin_code
        destination = (self.destination_airport.code if self.destination_airport_id else '') or self.destination_code
        if origin and destination:
            return f"{origin} - {destination}"
        return f"{self.origin} - {self.destination}"

    @property
    def duration_label(self):
        """``3h 30m`` for this leg, from the stored in-air minutes."""
        return format_duration(self.segment_duration_minutes or None)

    @property
    def departure_timezone_name(self):
        return (self.departure_timezone
                or (self.origin_airport.timezone_name if self.origin_airport_id else '')
                or DEFAULT_AIRPORT_TIMEZONE)

    @property
    def arrival_timezone_name(self):
        return (self.arrival_timezone
                or (self.destination_airport.timezone_name if self.destination_airport_id else '')
                or DEFAULT_AIRPORT_TIMEZONE)

    @property
    def capacity(self):
        return self.total_capacity

    @property
    def seat_layout(self):
        """The seat map this flight renders, resolved from the relationship.

        The aircraft flying it wins; a flight scheduled before an aircraft is
        chosen falls back to the airline's default type.  The booking page reads
        this and never picks a map itself.
        """
        from airlines.layouts import layout_for

        return layout_for(self)

    @property
    def seat_layout_record(self):
        """The ``SeatLayout`` row behind :attr:`seat_layout`, if there is one.

        Resolved exactly the way the map is, so a flight scheduled before an
        aircraft was chosen still knows which seats it is selling.
        """
        from airlines.layouts import resolve_layout

        return resolve_layout(self)

    @property
    def cabin_classes(self):
        """The fare classes this flight actually sells, in airmail order."""
        from airlines.layouts import layout_for

        return [c['key'] for c in layout_for(self)['cabins']]

    def fare_for(self, fare_class):
        return getattr(self, CABIN_FARE_FIELDS.get(fare_class, 'economy_fare'), 0)

    def has_seat(self, seat_number):
        """Whether this flight's own layout really has that seat."""
        layout = self.seat_layout_record
        if layout is None:
            return False
        return Seat.objects.filter(seat_layout=layout, seat_number=seat_number).exists()

    @property
    def slug(self):
        from atrue_core.slugs import make_slug
        return make_slug(self.flight_number, "flight-%s" % self.pk)

    @property
    def is_return_leg(self):
        return self.trip_role == TripRole.RETURN

    @property
    def partner_flight(self):
        """The other leg of this round trip, or ``None`` for a one-way flight.

        A booking that covers a round trip needs both legs, and each leg owns
        its own aircraft, cabin and seat map, so the two rows stay separate and
        this is how one finds the other.
        """
        if self.paired_flight_id:
            return self.paired_flight
        if not self.round_trip_group:
            return None
        return Flight.objects.filter(
            round_trip_group=self.round_trip_group
        ).exclude(pk=self.pk).first()

    @property
    def return_flight(self):
        """The return leg of this flight's round trip, if it has one.

        ``None`` on the return leg itself and on every one-way flight, so callers
        can treat "book a return seat only when this is not None".
        """
        if self.trip_role == TripRole.RETURN:
            return None
        return self.partner_flight

    @property
    def departure_flight(self):
        """The outbound leg when this row is the return leg, else ``self``."""
        return self.partner_flight if self.trip_role == TripRole.RETURN else self

    @property
    def is_round_trip(self):
        """True when this flight is sold together with a return leg.

        The outbound leg answers True; the return leg answers True as well so
        either leg can be opened from a search result and still know it is part
        of a round trip.
        """
        return self.round_trip_group is not None

    def clean(self):
        super().clean()
        if self.aircraft_id and self.airline_id and self.aircraft.airline_id != self.airline_id:
            raise ValidationError({
                'aircraft': f"{self.aircraft.tail_number} belongs to "
                            f"{self.aircraft.airline.name}, not {self.airline.name}."})
        if self.round_trip_group and self.pk:
            twin = Flight.objects.filter(
                round_trip_group=self.round_trip_group
            ).exclude(pk=self.pk)
            if not twin.exists():
                raise ValidationError({
                    'trip_type': "A round trip needs both a departure and a "
                                 "return leg."})
        self._clean_itinerary_position()

    def _clean_itinerary_position(self):
        """A leg must sit where it says it does inside its itinerary.

        Segment order is what decides the travel sequence, so a first leg that
        is not order 1, a duplicate order, or an order already taken by another
        leg of the same journey are all rejected rather than silently renumbered
        — two legs fighting over the same position is exactly the corruption
        that makes a connecting journey impossible to fly.
        """
        if not self.itinerary_id:
            if self.segment_order and self.segment_order != 1:
                raise ValidationError({
                    'segment_order': "A flight outside an itinerary is a single "
                                     "leg, so it is always segment 1."})
            return
        if self.itinerary.airline_id != self.airline_id:
            raise ValidationError({
                'itinerary': f"This itinerary belongs to "
                             f"{self.itinerary.airline.name}, not "
                             f"{self.airline.name}."})
        if not self.segment_order or self.segment_order < 1:
            raise ValidationError({
                'segment_order': "A segment's position in the journey starts at 1."})
        clash = Flight.objects.filter(
            itinerary_id=self.itinerary_id, segment_order=self.segment_order)
        if self.pk:
            clash = clash.exclude(pk=self.pk)
        if clash.exists():
            raise ValidationError({
                'segment_order': f"Segment {self.segment_order} of this "
                                 "itinerary already exists. Segments must be "
                                 "in order with no gaps."})


class FlightItinerary(models.Model):
    """One passenger journey made of one or more real flight legs.

    A direct flight is still a single ``Flight`` row and needs nothing here.
    A *connecting* flight is several rows joined by this table:

        FlightItinerary  MNL - SIN - DXB
          leg 1  Flight  PR 102   MNL -> SIN   (segment_order 1)
          leg 2  Flight  PR 908   SIN -> DXB   (segment_order 2)

    The itinerary is what a passenger buys, searches for and is ticketed on; the
    legs are what actually fly, each with its own aircraft, cabin, seat map and
    fare.  ``flight_type`` is therefore *derived* from the number of legs rather
    than typed in, so the two can never disagree.
    """

    class FlightType(models.TextChoices):
        DIRECT = 'DIRECT', 'Direct'
        CONNECTING = 'CONNECTING', 'Connecting'

    class RouteScope(models.TextChoices):
        DOMESTIC = 'DOMESTIC', 'Domestic'
        INTERNATIONAL = 'INTERNATIONAL', 'International'

    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        DELAYED = 'DELAYED', 'Delayed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        COMPLETED = 'COMPLETED', 'Completed'

    airline = models.ForeignKey(
        Airline, on_delete=models.PROTECT, related_name='itineraries',
        verbose_name="Airline")
    itinerary_reference = models.CharField(
        max_length=16, unique=True, editable=False, null=True,
        verbose_name="Itinerary reference")
    trip_type = models.CharField(
        max_length=15, choices=TripType.choices, default=TripType.ONE_WAY,
        verbose_name="Trip type")
    flight_type = models.CharField(
        max_length=12, choices=FLIGHT_TYPE_CHOICES, default=FlightType.DIRECT,
        editable=False, verbose_name="Flight type",
        help_text="Derived from the number of legs: one leg is direct, two or "
                  "more is connecting.")
    route_scope = models.CharField(
        max_length=15, choices=ROUTE_SCOPE_CHOICES, default=RouteScope.DOMESTIC,
        verbose_name="Route scope",
        help_text="Derived from the journey's two end airports: same country is "
                  "domestic, anything else is international.")
    status = models.CharField(
        max_length=10, choices=FLIGHT_STATUS_CHOICES, default='SCHEDULED')
    operating_days = models.CharField(
        max_length=40, blank=True, default='',
        help_text="Days the journey operates, comma separated, e.g. "
                  "MON,TUE,WED. Blank means every day.")
    booking_available = models.BooleanField(
        default=True,
        help_text="Untick to keep the schedule visible but stop it being sold.")
    currency = models.CharField(max_length=3, default='PHP')

    # ---- Pricing -----------------------------------------------------------
    # The itinerary price is the whole-journey price: base fare plus the
    # surcharges a connecting passenger pays once, not once per leg.
    base_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    taxes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    airport_fees = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fuel_surcharge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    service_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, editable=False,
        verbose_name="Total price",
        help_text="Base fare + taxes + airport fees + fuel surcharge + service "
                  "fee - discount, recomputed on every save.")
    baggage_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Baggage rate per kg (₱)",
        help_text="Charge per kilogram of extra baggage on any leg")

    # ---- Booking rules -----------------------------------------------------
    is_refundable = models.BooleanField(default=False)
    is_changeable = models.BooleanField(default=False)
    change_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cancellation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_advance_booking_hours = models.PositiveIntegerField(
        default=0, verbose_name="Minimum advance booking (hours)")
    min_connection_minutes = models.PositiveIntegerField(
        default=45, verbose_name="Minimum connection time (minutes)",
        help_text="A connection shorter than this is rejected: the passenger "
                  "could not make it.")
    max_connection_minutes = models.PositiveIntegerField(
        default=0, verbose_name="Maximum connection time (minutes)",
        help_text="0 means no upper limit.")

    total_duration_minutes = models.PositiveIntegerField(
        default=0, editable=False, verbose_name="Total journey (minutes)",
        help_text="First departure to final arrival across every leg, computed "
                  "from the airports' time zones.")
    stops = models.PositiveSmallIntegerField(
        default=0, editable=False, verbose_name="Stops",
        help_text="Number of legs minus one: 0 for a direct flight.")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Flight itinerary'
        verbose_name_plural = 'Flight itineraries'

    def __str__(self):
        return f"{self.itinerary_reference or 'ITIN'} {self.route_label}"

    def save(self, *args, **kwargs):
        # A connecting journey is priced and timed as one thing, so both totals
        # are recomputed here rather than trusted from the form.
        self.total_price = total_price(
            self.base_fare, self.taxes, self.airport_fees,
            self.fuel_surcharge, self.service_fee, self.discount)
        self.refresh_timing()
        super().save(*args, **kwargs)
        if not self.itinerary_reference:
            self.itinerary_reference = f"ITN-{self.pk:06d}"
            FlightItinerary.objects.filter(pk=self.pk).update(
                itinerary_reference=self.itinerary_reference)

    def refresh_timing(self):
        """Recount the journey's duration, stops and flight type from its legs."""
        legs = list(self.ordered_legs)
        self.stops = max(0, len(legs) - 1)
        self.flight_type = (self.FlightType.DIRECT if len(legs) <= 1
                            else self.FlightType.CONNECTING)
        timing = itinerary_timing(legs)
        self.total_duration_minutes = timing['total_minutes'] or 0
        scope = self.derive_route_scope(legs)
        if scope:
            self.route_scope = scope
        return self.total_duration_minutes

    @staticmethod
    def derive_route_scope(legs):
        """Domestic when both ends are in one country, international otherwise.

        Derived rather than typed in, because a scope that disagrees with the
        airports is worse than no scope at all.
        """
        legs = list(legs or [])
        if not legs:
            return None
        first, last = legs[0], legs[-1]
        origin = first.origin_airport if first.origin_airport_id else None
        destination = last.destination_airport if last.destination_airport_id else None
        if origin is None or destination is None:
            return None
        if origin.country_code and origin.country_code == destination.country_code:
            return FlightItinerary.RouteScope.DOMESTIC
        return FlightItinerary.RouteScope.INTERNATIONAL

    @property
    def ordered_legs(self):
        """The journey's legs in travel order, with their airports resolved.

        A prefetched ``legs`` cache is reused when there is one, so a search that
        returns a page of itineraries does not run a query per journey.  The
        cached rows are re-sorted rather than returned as prefetched: a prefetch
        only carries the ordering its own queryset asked for, and this property
        promises travel order to every caller.
        """
        if not self.pk:
            return []
        cache = getattr(self, '_prefetched_objects_cache', None) or {}
        if 'legs' in cache:
            return sorted(cache['legs'],
                          key=lambda leg: (leg.segment_order or 0, leg.pk or 0))
        return list(self.legs.select_related(
            'airline', 'aircraft', 'aircraft__aircraft_type__manufacturer',
            'origin_airport', 'destination_airport',
        ).order_by('segment_order', 'id'))

    @property
    def segments(self):
        """Alias for :attr:`ordered_legs` — the segment wording used on screen."""
        return self.ordered_legs

    @property
    def segment_count(self):
        return self.legs.count() if self.pk else 0

    @property
    def is_connecting(self):
        return (self.flight_type == self.FlightType.CONNECTING
                or self.stops > 0)

    @property
    def first_leg(self):
        legs = self.ordered_legs
        return legs[0] if legs else None

    @property
    def last_leg(self):
        legs = self.ordered_legs
        return legs[-1] if legs else None

    @property
    def timing(self):
        """Per-leg flight times, layovers and the whole-journey totals."""
        return itinerary_timing(self.ordered_legs)

    @property
    def total_duration_label(self):
        return format_duration(self.total_duration_minutes or None)

    @property
    def layovers(self):
        return self.timing['layovers']

    @property
    def origin_airport(self):
        leg = self.first_leg
        return leg.origin_airport if leg else None

    @property
    def destination_airport(self):
        leg = self.last_leg
        return leg.destination_airport if leg else None

    @property
    def connecting_airports(self):
        """The airports a passenger changes at, in order."""
        return [layover['airport'] for layover in self.layovers
                if layover['airport'] is not None]

    @property
    def departure_time(self):
        leg = self.first_leg
        return leg.departure_time if leg else None

    @property
    def arrival_time(self):
        leg = self.last_leg
        return leg.arrival_time if leg else None

    @property
    def origin(self):
        leg = self.first_leg
        return leg.origin if leg else ''

    @property
    def destination(self):
        leg = self.last_leg
        return leg.destination if leg else ''

    @property
    def origin_code(self):
        leg = self.first_leg
        return leg.origin_code if leg else ''

    @property
    def destination_code(self):
        leg = self.last_leg
        return leg.destination_code if leg else ''

    @property
    def route_label(self):
        """``MNL - SIN - DXB`` — the whole journey in one line."""
        legs = self.ordered_legs
        if not legs:
            return ''
        codes = [(leg.origin_airport.code if leg.origin_airport_id else '')
                 or leg.origin_code or leg.origin for leg in legs]
        tail = (legs[-1].destination_airport.code
                if legs[-1].destination_airport_id else '') \
            or legs[-1].destination_code or legs[-1].destination
        return ' - '.join(c for c in codes + [tail] if c)

    @property
    def stops_label(self):
        if not self.stops:
            return 'Direct'
        return f"{self.stops} Stop" + ("s" if self.stops > 1 else "")

    @property
    def price_breakdown(self):
        """The fare lines, in the order the ticket prints them."""
        return [
            ('Base fare', self.base_fare),
            ('Taxes', self.taxes),
            ('Airport fees', self.airport_fees),
            ('Fuel surcharge', self.fuel_surcharge),
            ('Service fee', self.service_fee),
        ]

    @property
    def economy_fare(self):
        """What a passenger pays, so templates read one name for either shape."""
        return self.total_price

    def is_bookable(self):
        return (self.booking_available
                and self.status in (self.Status.SCHEDULED, self.Status.DELAYED)
                and bool(self.ordered_legs))

    def clean(self):
        super().clean()
        legs = list(self.ordered_legs)
        if self.pk and len(legs) < 2 and self.flight_type == self.FlightType.CONNECTING:
            raise ValidationError({
                'flight_type': "A connecting journey needs at least two legs."})


class Booking(BookingFieldsMixin):
    """Real customer transaction record — stays a table."""

    Status = BookingStatus

    flight = models.ForeignKey(Flight, on_delete=models.PROTECT, related_name='bookings')
    return_flight = models.ForeignKey(
        Flight, on_delete=models.PROTECT, null=True, blank=True,
        related_name='return_bookings', verbose_name="Return Flight",
        help_text="The return leg of a round trip. Each leg is a real flight "
                  "row, so the two segments can have different aircraft and "
                  "seat maps.")
    itinerary = models.ForeignKey(
        FlightItinerary, on_delete=models.PROTECT, null=True, blank=True,
        related_name='bookings', verbose_name="Itinerary",
        help_text="The connecting journey this booking covers. Blank for a "
                  "direct flight or a round trip, which keep using "
                  "flight/return_flight. Set, the booking holds every segment "
                  "of one journey rather than being a separate booking per leg.")
    passenger = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='airline_bookings')
    extra_baggage = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    extra_baggage_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                           verbose_name="Extra baggage (kg)")
    travel_document_type = models.CharField(
        max_length=20, blank=True,
        choices=TRAVEL_DOCUMENT_TYPE_CHOICES,
        help_text="Travel document information (FR-020)")
    travel_document_number = models.CharField(max_length=50, blank=True)
    services = models.ManyToManyField(Service, blank=True, related_name='bookings')
    manager_remarks = models.TextField(blank=True, help_text="Remarks from the airline on confirm/decline (FR-018)")
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)

    TripType = TripType
    TripSegment = TripSegment

    trip_type = models.CharField(
        max_length=15, choices=TripType.choices, default=TripType.ONE_WAY,
        verbose_name="Trip Type")
    return_date = models.DateField(
        null=True, blank=True, verbose_name="Return Date",
        help_text="Return travel date for Round-Trip bookings. Kept in step "
                  "with the return leg's departure date when one is linked.")

    class BookingSeat(models.Model):
        """One row per assigned seat — also a real record, not an option set."""

        class Meta:
            ordering = ['segment_order', 'id']

        booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='seat_entries')
        passenger_name = models.CharField(max_length=200, blank=True)
        seat_number = models.CharField(max_length=10, blank=True)
        segment = models.CharField(
            max_length=10, choices=TripSegment.choices, default=TripSegment.DEPARTURE,
            verbose_name="Segment",
            help_text="Which leg of the journey this seat is on. A round-trip "
                      "passenger holds one seat per leg, and 12A outbound may "
                      "be 12A inbound too.")
        flight = models.ForeignKey(
            Flight, on_delete=models.PROTECT, null=True, blank=True,
            related_name='itinerary_seat_entries', verbose_name="Flight segment",
            help_text="The exact leg of a connecting itinerary this seat is "
                      "on. A passenger on MNL-SIN-DXB holds 12A on the MNL-SIN "
                      "aircraft and 14A on the SIN-DXB one, so the seat has to "
                      "name the leg rather than the trip. Blank for a direct "
                      "flight or round trip, which use segment/flight.")
        segment_order = models.PositiveSmallIntegerField(
            default=0, editable=False,
            help_text="The leg's position in the itinerary, copied from the "
                      "flight so the e-ticket can print segments in order.")
        fare_class = models.CharField(max_length=15, choices=FARE_CLASS_CHOICES, default='ECONOMY')
        travel_document_type = models.CharField(
            max_length=20, blank=True, choices=TRAVEL_DOCUMENT_TYPE_CHOICES,
            help_text="Per-passenger travel document (FR-020)")
        travel_document_number = models.CharField(max_length=50, blank=True)

        class Meta:
            constraints = [
                # A round trip's seats stay unique per leg exactly as before.
                models.UniqueConstraint(
                    fields=['booking', 'segment', 'seat_number'],
                    condition=models.Q(seat_number__gt='', flight__isnull=True),
                    name='unique_seat_per_booking_segment',
                ),
                # A connecting journey's seats are unique per *flight*, because
                # the same seat number is a different physical seat on each
                # aircraft — 12A on leg 1 and 12A on leg 2 are both correct.
                models.UniqueConstraint(
                    fields=['booking', 'flight', 'seat_number'],
                    condition=models.Q(seat_number__gt='', flight__isnull=False),
                    name='unique_seat_per_booking_itinerary_flight',
                ),
            ]

        def save(self, *args, **kwargs):
            self._ensure_seat_available()
            if self.flight_id and not self.segment_order:
                self.segment_order = self.flight.segment_order or 0
            super().save(*args, **kwargs)

        def _ensure_seat_available(self):
            """A seat must never be assigned twice on the same flight leg (BR-043).

            Scoped to the leg rather than the booking, because seats are booked
            per flight: the return leg is its own ``Flight`` row, so seat 12A can
            legitimately be held on both legs of a round trip — and on every leg
            of a connecting itinerary, each of which is a different airframe.
            """
            seat = (self.seat_number or '').strip()
            if not seat:
                return
            if self.flight_id:
                leg = dict(flight_id=self.flight_id)
            elif self.segment == TripSegment.RETURN:
                leg = dict(booking__return_flight_id=self.booking.return_flight_id)
            else:
                leg = dict(booking__flight_id=self.booking.flight_id)
            dup = (
                Booking.BookingSeat.objects.exclude(pk=self.pk)
                .filter(seat_number=seat, segment=self.segment, **leg)
                .exclude(booking__status__in=[Booking.Status.CANCELLED, Booking.Status.DECLINED])
            )
            if dup.exists():
                raise ValueError(f"Seat {seat} is already assigned on this flight (BR-043).")

        def __str__(self):
            prefix = f"Segment {self.segment_order} " if self.segment_order > 1 else ""
            return f"{prefix}Seat {self.seat_number} ({self.get_fare_class_display()})"

    class Meta:
        ordering = ['-created_at']

    @property
    def passengers_count(self):
        """How many travelers are on this booking.

        A direct flight and a round trip hold one seat row per passenger per leg,
        so counting rows works for them.  A connecting journey holds one row per
        passenger *per segment*, so its row count is the party size times the
        number of legs — the distinct seat rows on the first leg are the real
        headcount.
        """
        if self.itinerary_id:
            first = self.booked_legs()[:1]
            if not first:
                return 0
            return self.seat_entries.filter(flight=first[0]).count()
        return self.seat_entries.count()

    @property
    def has_return_segment(self):
        return self.return_flight_id is not None

    @property
    def is_itinerary_booking(self):
        """A connecting journey is one booking holding every leg of it."""
        return self.itinerary_id is not None

    def booked_legs(self):
        """The distinct legs of a connecting booking, in travel order.

        Empty for a direct flight or round trip, so callers can branch on
        ``if booking.booked_legs()`` and read the same name either way.
        """
        if not self.itinerary_id:
            return []
        flights = Flight.objects.filter(
            pk__in=self.seat_entries.exclude(flight_id=None)
            .values_list('flight_id', flat=True)).order_by('segment_order', 'id')
        return list(flights)

    def seats_for(self, segment):
        """The assigned seats on one leg, ordered by the seat map's row order."""
        return [entry.seat_number for entry in
                self.seat_entries.filter(segment=segment)]

    @property
    def itinerary_seats(self):
        """Seat rows in travel order, so a connecting ticket prints leg by leg.

        Ordered by the leg's own ``segment_order`` rather than the row id, so a
        booking that was edited still prints MNL-SIN before SIN-DXB.
        """
        return sorted(
            self.seat_entries.all(),
            key=lambda entry: (entry.segment_order or 0, entry.pk or 0))

    def seats_for_flight(self, flight):
        """The assigned seats on one leg of a connecting journey."""
        return [entry.seat_number for entry in
                self.seat_entries.filter(flight=flight)]

    def sync_return_date(self):
        """Keep :attr:`return_date` honest when a return leg is linked.

        The return leg is a real flight, so its own departure date is the
        authoritative return date; the column is kept only so existing reports
        and the e-ticket keep reading a single value.
        """
        if self.return_flight_id:
            self.return_date = self.return_flight.departure_time.date()
        elif self.trip_type != TripType.ROUND_TRIP:
            self.return_date = None
        return self.return_date

    @property
    def primary_guest_name(self):
        """Primary guest = the account (passenger) holder."""
        return self.passenger.get_full_name() or self.passenger.username

    @property
    def contact_number(self):
        """Booking contact reused from the account (BR-003)."""
        return self.passenger.contact_number

    @property
    def contact_email(self):
        """Booking contact email reused from the account (BR-003)."""
        return self.passenger.email

    def __str__(self):
        return f"Booking {self.booking_reference}"