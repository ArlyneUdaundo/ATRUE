from django.contrib import admin

from .models import (
    Aircraft, AircraftType, Airline, AirlineFleet, AirlinePhoto, Airport,
    Booking, Cabin, Flight, FlightItinerary, Manufacturer, Seat, SeatLayout,
    Service,
)


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ('airport_name', 'iata_code', 'icao_code', 'city', 'address', 'country', 'status')
    list_filter = ('status', 'country')
    search_fields = ('airport_name', 'iata_code', 'icao_code', 'city', 'address', 'country', 'region')


@admin.register(Airline)
class AirlineAdmin(admin.ModelAdmin):
    list_display = ('name', 'default_aircraft_type', 'contact_number', 'email', 'status')
    list_filter = ('status',)
    search_fields = ('name', 'airline_id')


@admin.register(Aircraft)
class AircraftAdmin(admin.ModelAdmin):
    list_display = ('airline', 'aircraft_type', 'tail_number', 'seating_capacity', 'status')
    list_filter = ('airline', 'aircraft_type__manufacturer', 'status')
    search_fields = ('tail_number', 'aircraft_id', 'aircraft_type__model_name')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('airline', 'name', 'rate', 'status')
    list_filter = ('airline', 'status')


@admin.register(AirlinePhoto)
class AirlinePhotoAdmin(admin.ModelAdmin):
    list_display = ('airline', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ('flight_number', 'airline', 'itinerary', 'segment_order', 'aircraft',
                    'origin_airport', 'destination_airport',
                    'departure_time', 'arrival_time', 'total_capacity', 'economy_fare', 'status')
    list_filter = ('airline', 'status', 'origin_airport', 'destination_airport')
    # Capacity is derived from the seat layout, so it is not something to type
    # in here.
    readonly_fields = ('total_capacity',)


@admin.register(FlightItinerary)
class FlightItineraryAdmin(admin.ModelAdmin):
    """A connecting journey.

    The legs themselves are edited on the flight form, not here: a segment's
    timing, aircraft and seat map are validated as a chain, so typing them into
    an isolated inline could produce a journey that can never be sold.
    """

    list_display = ('itinerary_reference', 'route_label', 'airline', 'segment_count',
                    'stops_label', 'total_duration_label', 'total_price', 'status')
    list_filter = ('airline', 'flight_type', 'trip_type', 'status', 'booking_available')
    search_fields = ('itinerary_reference',)
    readonly_fields = ('itinerary_reference', 'total_duration_minutes',
                        'total_duration_label')
    # Links out to the legs and the journey page rather than editing them here.
    def itinerary_legs(self, obj):
        return ', '.join(f"{leg.segment_order}. {leg.flight_number} "
                         f"{leg.origin_code}→{leg.destination_code}"
                         for leg in obj.ordered_legs) or '—'
    itinerary_legs.short_description = 'Segments'
    readonly_fields = readonly_fields + ('itinerary_legs',)


class CabinInline(admin.TabularInline):
    """The fare classes of a layout, in airmail order.

    ``blocks`` and ``rows`` are edited as-is; the layout's ``total_capacity`` is
    recounted on save, so it can never drift from the cabins listed here.
    """

    model = Cabin
    extra = 0
    fields = ('fare_class', 'position', 'blocks', 'rows', 'seat_count')
    readonly_fields = ('seat_count',)


@admin.register(SeatLayout)
class SeatLayoutAdmin(admin.ModelAdmin):
    list_display = ('name', 'airline', 'aircraft_type', 'seat_map', 'total_capacity')
    list_filter = ('airline', 'aircraft_type__manufacturer')
    search_fields = ('name', 'airline__name', 'aircraft_type__model_name')
    inlines = (CabinInline,)
    readonly_fields = ('total_capacity',)


@admin.register(Cabin)
class CabinAdmin(admin.ModelAdmin):
    list_display = ('seat_layout', 'fare_class', 'position', 'blocks', 'rows', 'seat_count')
    list_filter = ('fare_class', 'seat_layout__airline')
    search_fields = ('seat_layout__name',)


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ('seat_number', 'seat_layout', 'cabin', 'position')
    list_filter = ('position', 'cabin__fare_class', 'seat_layout__airline')
    search_fields = ('seat_number', 'seat_layout__name')


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'aircraft_types_count')
    search_fields = ('name',)

    @admin.display(description='Types')
    def aircraft_types_count(self, obj):
        return obj.aircraft_types.count()


@admin.register(AircraftType)
class AircraftTypeAdmin(admin.ModelAdmin):
    list_display = ('label', 'manufacturer', 'body_class', 'typical_capacity', 'is_active')
    list_filter = ('manufacturer', 'body_class', 'is_active')
    search_fields = ('model_name', 'manufacturer__name')


@admin.register(AirlineFleet)
class AirlineFleetAdmin(admin.ModelAdmin):
    list_display = ('airline', 'aircraft_type', 'is_primary', 'is_active', 'aircraft_count')
    list_filter = ('is_primary', 'is_active', 'airline')
    search_fields = ('airline__name', 'aircraft_type__model_name')

    @admin.display(description='Aircraft')
    def aircraft_count(self, obj):
        return obj.airline.aircrafts.filter(aircraft_type=obj.aircraft_type).count()


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('pk', 'passenger', 'flight', 'itinerary', 'passengers_count',
                    'total_bill', 'status', 'created_at')
    list_filter = ('status', 'flight', 'itinerary')
