import json
import logging
from smtplib import SMTPException
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from transactions.cart import add_booking_to_cart, create_single_booking_order
from transactions.establishment_flow import add_booking as add_establishment_booking
from accounts.roles import FULL_ACCESS_TYPES, can_access_module, effective_role_keys
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Case, Count, ExpressionWrapper, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.clickjacking import xframe_options_sameorigin

from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.image_utils import is_valid_image
from atrue_core.location_hierarchy import country_province_keys, location_matches
from atrue_core.slugs import get_object_by_slug_or_404
from atrue_core.services import (
    bill_for_booking,
    cancel_booking,
    checkout,
    compute_airline_bill,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    record_payment,
    resource_is_bookable,
)
from locations.geonames_service import search_worldwide_places

from .itineraries import (
    DEFAULT_TIMEZONE_FALLBACK as DEFAULT_AIRPORT_TIMEZONE,
    MAX_ITINERARY_SEGMENTS,
    airport_timezone,
    combine_local,
    format_duration,
    itinerary_timing,
    layover_minutes,
    parse_clock,
    segment_duration_minutes,
)
from .layouts import build_seat_map
from .models import (
    Airline,
    AirlineFleet,
    AirlinePhoto,
    Aircraft,
    AircraftType,
    Airport,
    Booking,
    Cabin,
    FARE_CLASS_CHOICES,
    Flight,
    FlightItinerary,
    Seat,
    SeatLayout,
    Service,
    TripRole,
    TripSegment,
)

logger = logging.getLogger(__name__)


def _serialize_airport(airport):
    cities = [p for p in (airport.city, airport.country) if p]
    return {
        'id': airport.pk,
        'name': airport.airport_name,
        'iata': airport.iata_code,
        'icao': airport.icao_code,
        'code': airport.code,
        'city': airport.city,
        'country': airport.country,
        'region': airport.region,
        'label': f"{airport.code} — {', '.join(cities)}",
    }


def _airport_endpoint_payload(airport):
    """Denormalised flight fields derived from the passenger's chosen airport."""
    return {
        'airport': airport,
        'name': airport.city or airport.airport_name,
        'code': airport.code,
        'country': airport.country,
        'region': airport.region,
        'municipality': airport.city,
    }


def airports_api(request):
    """JSON endpoint backing the worldwide airport picker.

    Search is server-side (name / IATA / ICAO / city / country / region) so the
    whole world list never has to be shipped to the browser.  ``?id=N`` returns a
    single airport for pre-filled form values.
    """
    q = (request.GET.get('q') or '').strip()
    pk = (request.GET.get('id') or '').strip()
    qs = Airport.objects.filter(status=Airport.Status.ACTIVE)

    if pk:
        try:
            airport = qs.get(pk=pk)
        except (Airport.DoesNotExist, ValueError):
            return JsonResponse({'results': []})
        return JsonResponse({'results': [_serialize_airport(airport)]})

    if q:
        airport_matches = (
            Q(iata_code__iexact=q) | Q(icao_code__iexact=q)
            | Q(airport_name__icontains=q) | Q(city__icontains=q)
            | Q(country__icontains=q) | Q(region__icontains=q)
        )
        for place in search_worldwide_places(q, limit=30):
            if place['level'] == 'city':
                airport_matches |= Q(
                    city__iexact=place['municipality'],
                    country_code__iexact=place['country_code'],
                )
            elif place['level'] == 'province':
                airport_matches |= Q(
                    region__iexact=place['province'],
                    country_code__iexact=place['country_code'],
                )
        qs = qs.filter(airport_matches).annotate(exact=Case(
            When(iata_code__iexact=q, then=Value(1)),
            When(icao_code__iexact=q, then=Value(2)),
            default=Value(3), output_field=IntegerField(),
        )).order_by('exact', 'airport_name')[:30]
    else:
        qs = qs.order_by('city', 'airport_name')[:10]

    return JsonResponse({'results': [_serialize_airport(a) for a in qs]})


def _parse_dt(value):
    if not value:
        return None
    value = value.replace('T', ' ')
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value):
    """Parse an ISO date string ("YYYY-MM-DD") or return None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except (TypeError, ValueError):
        return None


def _cutoff_statuses():
    return (Booking.Status.CANCELLED, Booking.Status.DECLINED,
            Booking.Status.COMPLETED, Booking.Status.CHECKED_OUT)


def _booked_seats(flight, segment=TripSegment.DEPARTURE):
    """How many seats are already sold on one leg of a journey."""
    if segment == TripSegment.RETURN:
        qs = Booking.objects.filter(return_flight=flight)
    else:
        qs = Booking.objects.filter(flight=flight)
    return qs.exclude(status__in=_cutoff_statuses()).aggregate(
        total=Count('seat_entries', filter=Q(seat_entries__segment=segment))
    )['total'] or 0


def _booked_seat_numbers(flight, segment=TripSegment.DEPARTURE):
    """All seat numbers currently assigned on one leg (taken seats, BR-043).

    Scoped by segment because a round-trip passenger holds a seat on each leg,
    and 12A outbound is still free to be taken inbound.
    """
    if segment == TripSegment.RETURN:
        qs = Booking.BookingSeat.objects.filter(
            booking__return_flight=flight, segment=TripSegment.RETURN)
    else:
        qs = Booking.BookingSeat.objects.filter(
            booking__flight=flight, segment=TripSegment.DEPARTURE)
    return set(qs.exclude(booking__status__in=_cutoff_statuses())
               .values_list('seat_number', flat=True))


def _seat_map(flight, segment=TripSegment.DEPARTURE):
    """The flight's real cabin layout, built from its airline's aircraft.

    Each cabin carries the fare that flight sells it at, so the booking page can
    price a cabin without knowing which field the fare lives in.
    """
    seat_map = build_seat_map(flight, _booked_seat_numbers(flight, segment))
    for cabin in seat_map['cabins']:
        cabin['fare'] = flight.fare_for(cabin['key'])
    return seat_map


def _seats_exist(flight, seat_numbers):
    """Whether every seat number is one the flight's own layout actually has."""
    if not seat_numbers:
        return True
    layout = flight.seat_layout_record
    if layout is None:
        return False
    real = set(Seat.objects.filter(seat_layout=layout, seat_number__in=seat_numbers)
               .values_list('seat_number', flat=True))
    return real == set(seat_numbers)


def _posted_seat_list(request, index):
    """The seats posted for one leg of a connecting journey, in passenger order.

    The itinerary booking form names its seat fields per leg
    (``seg_0_seat_numbers``, ``seg_1_seat_numbers``, ...) so two legs of the same
    journey can never submit into one field.  Each field carries that leg's
    *whole* seat list for the party, pipe separated, because that list is also
    what fixes the number of passengers: one entry per traveller, on every leg.
    A form that sent only the lead seat falls back to ``seg_<index>_primary_seat``.
    """
    seats = []
    for value in request.POST.getlist(f'seg_{index}_seat_numbers'):
        seats.extend(part for part in
                     (p.strip().upper() for p in str(value).split('|'))
                     if part)
    if not seats:
        primary = (request.POST.get(f'seg_{index}_primary_seat') or '').strip().upper()
        if primary:
            seats = [primary]
    return seats


def _aircraft_conflict(aircraft, departure, arrival, exclude_id=None):
    """An ASSIGNED aircraft must never fly (or be maintained) twice at once (BR-041)."""
    qs = Flight.objects.filter(aircraft=aircraft).exclude(
        status__in=[Flight.Status.CANCELLED, Flight.Status.COMPLETED]
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    if departure and arrival:
        qs = qs.filter(departure_time__lt=arrival, arrival_time__gt=departure)
    return qs.exists()


def _itinerary_search(request, dep=None):
    """Search connecting itineraries, each as one result.

    An itinerary matches on its *ends*: a MNL to DXB search must offer the
    MNL-SIN-DXB journey even though no leg flies MNL-DXB directly.

    The origin conditions and the destination conditions are applied in separate
    ``.filter()`` calls on purpose.  Django opens one join per ``filter()`` on a
    multi-valued relation, and collapsing them into a single call would force
    every condition onto the *same* leg row - demanding a leg that is both
    segment 1 and the last segment, which no journey with a stop can satisfy.  Two
    joins are safe here because ``legs`` is this itinerary's own reverse
    relation, so both ends are still drawn from one journey.
    """
    last_order = Flight.objects.filter(
        itinerary=OuterRef('pk')).order_by('-segment_order').values(
        'segment_order')[:1]

    origin = (request.GET.get('origin', '') or '').strip()
    destination = (request.GET.get('destination', '') or '').strip()
    origin_airport = (request.GET.get('origin_airport') or '').strip()
    destination_airport = (request.GET.get('destination_airport') or '').strip()

    if not origin and not destination and not origin_airport and not destination_airport and not dep:
        # No criteria at all: the browse page shows nothing rather than every
        # itinerary in the database, matching how the direct list behaves.
        return []

    itineraries = FlightItinerary.objects.filter(
        status__in=(FlightItinerary.Status.SCHEDULED,
                     FlightItinerary.Status.DELAYED)
    ).prefetch_related('legs__origin_airport', 'legs__destination_airport')

    # The journey's first leg decides where the passenger leaves from.
    if origin_airport.isdigit():
        itineraries = itineraries.filter(legs__segment_order=1,
                                         legs__origin_airport_id=int(origin_airport))
    elif origin:
        itineraries = itineraries.filter(legs__segment_order=1,
                                         legs__origin__icontains=origin)
    # ...and its last leg decides where they end up.
    if destination_airport.isdigit():
        itineraries = itineraries.filter(legs__segment_order=last_order,
                                         legs__destination_airport_id=int(destination_airport))
    elif destination:
        itineraries = itineraries.filter(legs__segment_order=last_order,
                                         legs__destination__icontains=destination)
    if dep:
        itineraries = itineraries.filter(legs__segment_order=1,
                                         legs__departure_time__date__gte=dep)
    itineraries = itineraries.distinct()

    # Structured location filters reuse the same helper as the direct list, so
    # a country/province/municipality picker means the same thing for both.
    origin_country = (request.GET.get('origin_country') or '').strip()
    origin_province = (request.GET.get('origin_province') or '').strip()
    origin_municipality = (request.GET.get('origin_municipality') or '').strip()
    destination_country = (request.GET.get('destination_country') or '').strip()
    destination_province = (request.GET.get('destination_province') or '').strip()
    destination_municipality = (request.GET.get('destination_municipality') or '').strip()

    results = list(itineraries.select_related('airline'))
    if origin_country or origin_province or origin_municipality:
        origin_keys = country_province_keys(origin_country) if origin_country else None
        results = [it for it in results if it.first_leg and location_matches(
            {'province': [it.first_leg.origin_province or ''],
             'municipality': [it.first_leg.origin_municipality or ''],
             'barangay': [], 'loc_text': ''},
            origin_province, origin_municipality, '',
            country=origin_country, country_provinces=origin_keys)]
    if destination_country or destination_province or destination_municipality:
        destination_keys = (country_province_keys(destination_country)
                            if destination_country else None)
        results = [it for it in results if it.last_leg and location_matches(
            {'province': [it.last_leg.destination_province or ''],
             'municipality': [it.last_leg.destination_municipality or ''],
             'barangay': [], 'loc_text': ''},
            destination_province, destination_municipality, '',
            country=destination_country, country_provinces=destination_keys)]
    return results


def _itinerary_result_rows(itineraries):
    """Turn itineraries into search-card rows, pricing seats in one query.

    ``remaining`` is the seats left on the *tightest* leg, not the sum: one
    passenger needs one seat on every leg, so the smallest cabin is what caps
    the party.
    """
    rows = []
    all_legs = []
    for itinerary in itineraries:
        legs = itinerary.ordered_legs
        itinerary._card_legs = legs
        all_legs.extend(legs)
    booked = {}
    if all_legs:
        for flight_id, total in Booking.BookingSeat.objects.filter(
            flight__in=all_legs).exclude(
            booking__status__in=_cutoff_statuses()
        ).values_list('flight').annotate(total=Count('id')):
            booked[flight_id] = total
    for itinerary in itineraries:
        legs = itinerary._card_legs
        remaining = None
        for leg in legs:
            leg_remaining = max(0, leg.capacity - booked.get(leg.pk, 0))
            remaining = (leg_remaining if remaining is None
                         else min(remaining, leg_remaining))
        rows.append({
            'itinerary': itinerary,
            'legs': legs,
            'timing': itinerary.timing,
            'remaining': remaining if remaining is not None else 0,
        })
    return rows


def _result_badges(flights, itinerary_rows):
    """Mark the cheapest and the best results in one search, across both shapes.

    A direct flight and a connecting journey are sold on the same page, so the
    two lists are compared together: the badges have to mean "cheapest of what
    this search actually returned", not "cheapest of whichever kind this is".

    "Cheapest" is the lowest per-passenger price. "Best" is the shortest
    door-to-door time and, within that same duration, the cheapest — so it never
    lands on a slow flight just because that one is short-priced. Both badges
    only go to a result that is still bookable; ties go to the first row.
    """
    entries = []
    for flight in flights:
        entries.append({
            'obj': flight,
            'price': Decimal(getattr(flight, 'search_fare', flight.economy_fare)),
            'minutes': flight.segment_duration_minutes or 0,
            'bookable': (flight.remaining_seats or 0) > 0,
        })
    for row in itinerary_rows:
        itinerary = row['itinerary']
        entries.append({
            'obj': itinerary,
            'price': Decimal(row.get('search_fare', itinerary.economy_fare)),
            'minutes': itinerary.total_duration_minutes or 0,
            'bookable': itinerary.is_bookable() and row['remaining'] > 0,
        })

    # Keyed by primary key, not by object identity: the template looks a card up
    # with ``f.id`` while the test holds its own instance of the same row.
    flags = {entry['obj'].pk: set() for entry in entries}
    if not entries:
        return flags
    bookable = [e for e in entries if e['bookable']] or entries

    flags[min(bookable, key=lambda e: e['price'])['obj'].pk].add('cheapest')
    # ``minutes`` is a duration, so the quickest result is the *smallest* one.
    quickest = min(e['minutes'] for e in bookable)
    same_time = [e for e in bookable if e['minutes'] == quickest]
    flags[min(same_time, key=lambda e: e['price'])['obj'].pk].add('best')
    return flags


def _result_logos(flights, itinerary_rows):
    """Primary logo per airline, fetched once for the whole page.

    Each result only needs its airline's logo, but the cards are rendered from a
    list, so the lookup happens once here instead of once per card.
    """
    airline_ids = {f.airline_id for f in flights if f.airline_id}
    airline_ids.update(row['itinerary'].airline_id for row in itinerary_rows)
    logos = {}
    if airline_ids:
        photos = (AirlinePhoto.objects
                  .filter(airline_id__in=airline_ids)
                  .order_by('airline_id', '-is_primary', 'id'))
        for photo in photos:
            logos.setdefault(photo.airline_id, photo)
    return logos


def _local(value):
    """A datetime in the platform zone, which is what a page prints.

    Stored times are aware UTC; the result row and the modal have to show the
    same local clock, so both read through here rather than formatting the raw
    value and hoping the caller remembered.
    """
    return timezone.localtime(value) if timezone.is_aware(value) else value


def long_date(value):
    """``Tuesday, 3 November 2026``, with no leading zero on the day.

    Assembled by hand rather than with ``%-d``, which is a glibc extension and
    raises a ValueError on Windows.
    """
    if not value:
        return ''
    value = _local(value)
    return f"{value.strftime('%A, %B')} {value.day}, {value.year}"


@xframe_options_sameorigin
def flight_list(request):
    booked_sub = Booking.objects.filter(flight=OuterRef('pk')).exclude(
        status__in=_cutoff_statuses()
    ).values('flight').annotate(total=Count('seat_entries')).values('total')

    flights = Flight.objects.select_related(
        'airline', 'aircraft', 'origin_airport', 'destination_airport',
        'paired_flight', 'paired_flight__origin_airport',
        'paired_flight__destination_airport',
    ).prefetch_related('airline__photos').filter(
        status__in=[Flight.Status.SCHEDULED, Flight.Status.DELAYED],
        # A leg that belongs to a connecting journey is not offered on its own:
        # the journey is the thing a passenger buys, so the leg would otherwise
        # appear twice — once alone and once inside the itinerary.
        itinerary__isnull=True,
    ).annotate(remaining_seats=ExpressionWrapper(
        F('total_capacity') - Coalesce(
            Subquery(booked_sub, output_field=IntegerField()), 0),
        output_field=IntegerField(),
    ))

    origin = (request.GET.get('origin', '') or '').strip()
    destination = (request.GET.get('destination', '') or '').strip()
    origin_airport = (request.GET.get('origin_airport') or '').strip()
    destination_airport = (request.GET.get('destination_airport') or '').strip()
    origin_country = (request.GET.get('origin_country') or '').strip()
    origin_province = (request.GET.get('origin_province') or '').strip()
    origin_municipality = (request.GET.get('origin_municipality') or '').strip()
    destination_country = (request.GET.get('destination_country') or '').strip()
    destination_province = (request.GET.get('destination_province') or '').strip()
    destination_municipality = (request.GET.get('destination_municipality') or '').strip()
    trip_type = request.GET.get('trip_type', Booking.TripType.ONE_WAY)
    departure_date = request.GET.get('departure_date', '')
    return_date = request.GET.get('return_date', '')
    search_submitted = request.GET.get('search_submit') == '1'
    search_errors = []
    if trip_type not in (Booking.TripType.ONE_WAY, Booking.TripType.ROUND_TRIP):
        trip_type = Booking.TripType.ONE_WAY
        if search_submitted:
            search_errors.append('Choose One-way or Round-trip.')
    dep = _parse_date(departure_date)
    ret = _parse_date(return_date)
    if search_submitted:
        # The destination is what the passenger searched for; the departure
        # airport is optional and can be refined on this page.
        if not destination_airport.isdigit() or not Airport.objects.filter(
            pk=destination_airport, status=Airport.Status.ACTIVE
        ).exists():
            search_errors.append('Select a valid flying-to airport.')
        if origin_airport:
            if not origin_airport.isdigit() or not Airport.objects.filter(
                pk=origin_airport, status=Airport.Status.ACTIVE
            ).exists():
                search_errors.append('Select a valid flying-from airport.')
            elif destination_airport.isdigit() and int(origin_airport) == int(destination_airport):
                search_errors.append(
                    'Flying-from and flying-to airports must be different.')
        if not departure_date or dep is None:
            search_errors.append('Select a valid departure date.')
        elif dep < timezone.localdate():
            search_errors.append('Departure date cannot be in the past.')
        if trip_type == Booking.TripType.ROUND_TRIP:
            if not return_date or ret is None:
                search_errors.append('Select a valid return date.')
            elif dep and ret < dep:
                search_errors.append(
                    'Return date cannot be earlier than departure.')
            elif ret < timezone.localdate():
                search_errors.append('Return date cannot be in the past.')
    requested_fare_class = (request.GET.get('fare_class') or '').strip()
    fare_class = (
        requested_fare_class
        if requested_fare_class in dict(FARE_CLASS_CHOICES)
        else ''
    )
    if search_submitted and requested_fare_class and not fare_class:
        search_errors.append('Choose a valid fare class.')
    try:
        raw_passengers = request.GET.get('passengers') or '1'
        passengers = int(raw_passengers)
    except (TypeError, ValueError):
        passengers = 1
    if not 1 <= passengers <= 9:
        if search_submitted:
            search_errors.append('Passenger count must be between 1 and 9.')
        passengers = 1
    filter_party_size = bool(request.GET.get('passengers'))
    if origin:
        flights = flights.filter(origin__icontains=origin)
    if destination:
        flights = flights.filter(destination__icontains=destination)
    if origin_airport.isdigit():
        flights = flights.filter(origin_airport_id=origin_airport)
    if destination_airport.isdigit():
        flights = flights.filter(destination_airport_id=destination_airport)
    if dep:
        if search_submitted:
            flights = flights.filter(departure_time__date=dep)
        else:
            flights = flights.filter(departure_time__date__gte=dep)
    if search_submitted and not search_errors:
        flights = flights.filter(trip_role=TripRole.OUTBOUND)
        if trip_type == Booking.TripType.ONE_WAY:
            flights = flights.filter(trip_type=Booking.TripType.ONE_WAY)
        else:
            flights = flights.filter(
                trip_type=Booking.TripType.ROUND_TRIP,
                paired_flight__status__in=(
                    Flight.Status.SCHEDULED,
                    Flight.Status.DELAYED,
                ),
                paired_flight__isnull=False,
                paired_flight__departure_time__date=ret,
            )
            if origin_airport.isdigit() and destination_airport.isdigit():
                flights = flights.filter(
                    paired_flight__origin_airport_id=destination_airport,
                    paired_flight__destination_airport_id=origin_airport,
                )
            return_booked = Booking.objects.filter(
                flight_id=OuterRef('paired_flight_id')
            ).exclude(
                status__in=_cutoff_statuses()
            ).values('flight').annotate(
                total=Count('seat_entries')
            ).values('total')
            flights = flights.annotate(
                return_remaining_seats=ExpressionWrapper(
                    F('paired_flight__total_capacity') - Coalesce(
                        Subquery(return_booked, output_field=IntegerField()), 0
                    ),
                    output_field=IntegerField(),
                )
            )

    # Structured location filters (from the ATUE location picker). A country-only
    # selection is matched through the country's provinces; municipality/province
    # are matched on the flight's own structured fields.
    if origin_country or origin_province or origin_municipality:
        origin_keys = country_province_keys(origin_country) if origin_country else None
        flights = [f for f in flights if location_matches(
            {'province': [f.origin_province or ''], 'municipality': [f.origin_municipality or ''],
             'barangay': [], 'loc_text': ''},
            origin_province, origin_municipality, '',
            country=origin_country, country_provinces=origin_keys)]
    if destination_country or destination_province or destination_municipality:
        destination_keys = country_province_keys(destination_country) if destination_country else None
        flights = [f for f in flights if location_matches(
            {'province': [f.destination_province or ''], 'municipality': [f.destination_municipality or ''],
             'barangay': [], 'loc_text': ''},
            destination_province, destination_municipality, '',
            country=destination_country, country_provinces=destination_keys)]

    if search_errors:
        flights = []
    flights = list(flights)
    itinerary_rows = (
        []
        if search_errors or (
            search_submitted and trip_type == Booking.TripType.ROUND_TRIP
        )
        else _itinerary_result_rows(_itinerary_search(request, dep))
    )
    if fare_class:
        flights = [
            flight for flight in flights
            if fare_class in flight.cabin_classes
            and (
                not search_submitted
                or trip_type != Booking.TripType.ROUND_TRIP
                or fare_class in flight.return_flight.cabin_classes
            )
        ]
        itinerary_rows = [
            row for row in itinerary_rows
            if all(fare_class in leg.cabin_classes for leg in row['legs'])
        ]
    if filter_party_size:
        flights = [
            flight for flight in flights
            if flight.remaining_seats >= passengers
            and (
                not search_submitted
                or trip_type != Booking.TripType.ROUND_TRIP
                or flight.return_remaining_seats >= passengers
            )
        ]
        itinerary_rows = [
            row for row in itinerary_rows
            if row['remaining'] >= passengers
        ]
    return_rows = []
    seen_return_ids = set()
    for flight in flights:
        flight.outbound_search_fare = (
            flight.fare_for(fare_class) if fare_class else flight.economy_fare
        )
        flight.search_fare = flight.outbound_search_fare
        if search_submitted and trip_type == Booking.TripType.ROUND_TRIP:
            return_flight = flight.return_flight
            flight.return_search_fare = (
                return_flight.fare_for(fare_class)
                if fare_class else return_flight.economy_fare
            )
            flight.search_fare += flight.return_search_fare
            if return_flight.pk not in seen_return_ids:
                seen_return_ids.add(return_flight.pk)
                return_flight.search_fare = flight.return_search_fare
                return_flight.search_remaining_seats = flight.return_remaining_seats
                return_flight.search_outbound_id = flight.pk
                return_flight.search_pair_total = flight.search_fare
                return_rows.append(return_flight)
    for row in itinerary_rows:
        row['search_fare'] = (
            sum(
                (leg.fare_for(fare_class) for leg in row['legs']),
                Decimal('0'),
            )
            if fare_class
            else row['itinerary'].economy_fare
        )

    return render(request, 'airlines/list.html', {
        'flights': flights,
        'return_rows': return_rows,
        'is_round_trip_search': search_submitted and trip_type == Booking.TripType.ROUND_TRIP,
        'itinerary_rows': itinerary_rows,
        'badges': _result_badges(flights, itinerary_rows),
        'airline_logos': _result_logos(flights, itinerary_rows),
        'origin': origin,
        'destination': destination,
        'origin_airport': origin_airport,
        'destination_airport': destination_airport,
        'origin_airport_object': (
            Airport.objects.filter(pk=origin_airport).first()
            if origin_airport.isdigit() else None
        ),
        'destination_airport_object': (
            Airport.objects.filter(pk=destination_airport).first()
            if destination_airport.isdigit() else None
        ),
        'origin_country': origin_country,
        'origin_province': origin_province,
        'origin_municipality': origin_municipality,
        'destination_country': destination_country,
        'destination_province': destination_province,
        'destination_municipality': destination_municipality,
        'trip_type': trip_type,
        'departure_date': departure_date,
        'return_date': return_date,
        'search_today': timezone.localdate().isoformat(),
        'fare_class': fare_class,
        'fare_class_choices': FARE_CLASS_CHOICES,
        'passengers': passengers,
        'search_errors': search_errors,
    })


@manager_required
def manage(request):
    qs = Airline.objects.prefetch_related(
        'photos', 'aircrafts__aircraft_type__manufacturer', 'services', 'flights',
        'fleet_entries__aircraft_type__manufacturer')
    airline_ids = _assigned_airline_ids_for_management(request)
    if airline_ids is not None:
        qs = qs.filter(pk__in=airline_ids)
    q = request.GET.get('q', '')
    status = request.GET.get('status', '')
    if q:
        qs = qs.filter(Q(airline_id__icontains=q) | Q(name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, 'airlines/manage.html', {
        'airlines': qs,
        'q': q,
        'status': status,
    })


def _airline_form_context(airline=None):
    return {
        'airline': airline,
        'fleet_types': _fleet_types(airline),
    }


@manager_required
def update_airline(request, airline_id):
    airline = get_object_or_404(
        Airline.objects.prefetch_related('photos', 'fleet_entries__aircraft_type'),
        pk=airline_id)
    if request.method == 'POST':
        for field in ('name', 'contact_number', 'email', 'description', 'operating_info', 'status'):
            setattr(airline, field, request.POST.get(field) or getattr(airline, field))
        default_type = _post_pk(request, 'default_aircraft_type')
        if default_type is not None:
            # The fallback type for flights scheduled without an aircraft has to
            # be one this airline actually flies, or the flight would be sold a
            # cabin the airline does not operate.
            fleet = airline.fleet_entries.filter(
                aircraft_type_id=default_type, is_active=True).first()
            if fleet is None:
                messages.error(
                    request,
                    "The default aircraft type must be one of this airline's fleet types.")
            else:
                airline.default_aircraft_type = fleet.aircraft_type
        airline.save()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for image in photos:
            AirlinePhoto.objects.create(airline=airline, image=image, is_primary=not airline.photos.exists())
        for photo in airline.photos.filter(pk__in=request.POST.getlist('delete_photos')):
            photo.delete()
        if airline.photos.exists() and not airline.photos.filter(is_primary=True).exists():
            first = airline.photos.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        # A new logo replaces the current one outright: only one image is ever
        # the airline's mark, so keeping the old photo around would leave the
        # search results and tickets showing the previous carrier mark.
        logo = request.FILES.get('logo')
        if logo and is_valid_image(logo):
            for photo in airline.photos.all():
                photo.delete()
            AirlinePhoto.objects.create(airline=airline, image=logo, is_primary=True)
        elif request.POST.get('remove_logo'):
            airline.photos.all().delete()
        # A flight is only bookable for the seats its layout has, and the layout
        # now comes from the airline's fleet, so changing the default type has to
        # re-seat the flights that have no aircraft of their own.
        for flight in airline.flights.filter(aircraft__isnull=True):
            flight.save()
        log_activity(request.user, "Updated airline", f"{airline.airline_id} - {airline.name}")
        messages.success(request, "Airline updated.")
        return redirect('airlines:manage')
    return render(request, 'airlines/form.html', _airline_form_context(airline))


@manager_required
def airline_detail(request, airline_id):
    airline = get_object_or_404(
        Airline.objects.prefetch_related(
            'photos', 'services', 'flights__aircraft',
            'fleet_entries__aircraft_type__manufacturer',
            'aircrafts__aircraft_type__manufacturer',
            'aircrafts__seat_layout__aircraft_type__manufacturer',
        ),
        pk=airline_id)
    return render(request, 'airlines/detail.html', {
        'airline': airline,
        'fleet_entries': airline.fleet_entries.all(),
    })


def _query_pk(request, key):
    """Return the chosen id as a positive int, from the form or the query string.

    The dependent dropdowns re-render the page with the chosen airline / type in
    the query string, so a form has to read its selection from either place.
    None means "absent or garbage", which callers treat as "nothing selected".
    """
    value = (request.POST.get(key) or request.GET.get(key) or '').strip()
    return int(value) if value.isdigit() and int(value) else None


def _query_str(request, key):
    """A non-numeric form/query choice (e.g. the trip type) from either place."""
    return (request.POST.get(key) or request.GET.get(key) or '').strip()


def _fleet_types(airline, active_only=True):
    """The aircraft types an airline operates — the only ones it may ever show.

    This is the single place the airline -> aircraft-type relationship is read,
    so every dropdown in the admin interface narrows the same way.
    """
    if airline is None:
        return AircraftType.objects.none()
    entries = AirlineFleet.objects.filter(airline=airline)
    if active_only:
        entries = entries.filter(is_active=True)
    return (AircraftType.objects
            .filter(pk__in=entries.values_list('aircraft_type_id', flat=True))
            .select_related('manufacturer')
            .order_by('manufacturer__name', 'model_name'))


def _fleet_layouts(airline):
    """Every seat layout this airline flies, keyed by aircraft type id."""
    if airline is None:
        return {}
    return {layout.aircraft_type_id: layout for layout in
            SeatLayout.objects.filter(airline=airline)
            .select_related('aircraft_type__manufacturer')}


def _aircraft_form_context(airline, aircraft=None, selected_type=None):
    """Context for the aircraft form, with the airline's fleet as the choices.

    ``selected_type`` narrows the tail-number list further, so the form behaves
    as the dependent pair the requirement asks for: pick a type, and only that
    type's airframes are offered.
    """
    layouts = _fleet_layouts(airline)
    fleet_types = [t for t in _fleet_types(airline) if t.pk in layouts]
    return {
        'airline': airline,
        'aircraft': aircraft,
        'fleet_types': fleet_types,
        'fleet_layouts': layouts,
        'aircrafts': (airline.aircrafts.filter(aircraft_type_id=selected_type)
                      if selected_type else airline.aircrafts.none()),
        'selected_type': selected_type,
    }


@manager_required
def add_aircraft(request, airline_id):
    airline = get_object_or_404(
        Airline.objects.prefetch_related('fleet_entries__aircraft_type__manufacturer'),
        pk=airline_id)
    selected_type = _query_pk(request, 'aircraft_type')
    layouts = _fleet_layouts(airline)
    fleet_types = [t for t in _fleet_types(airline) if t.pk in layouts]
    if not fleet_types:
        messages.error(
            request, f"{airline.name} has no fleet types configured yet. "
                     "Add aircraft types to the airline's fleet first.")
        return redirect('airlines:airline_fleet', airline.pk)
    if request.method == 'POST':
        tail_number = request.POST.get('tail_number', '').strip().upper()
        aircraft_type = AircraftType.objects.filter(pk=selected_type).first()
        # The layout is never chosen by hand: the type the manager picked in this
        # airline's fleet decides which cabin this airframe is fitted out with.
        layout = layouts.get(selected_type)
        if aircraft_type is None or layout is None:
            messages.error(request, "Choose an aircraft type from this airline's fleet.")
        elif not tail_number:
            messages.error(request, "Tail number is required.")
        elif Aircraft.objects.filter(tail_number=tail_number).exists():
            messages.error(request, f"Tail number '{tail_number}' is already registered.")
        else:
            aircraft = Aircraft(airline=airline, aircraft_type=aircraft_type,
                                seat_layout=layout, tail_number=tail_number,
                                status=request.POST.get('status', Aircraft.Status.AVAILABLE),
                                seating_capacity=layout.total_capacity)
            try:
                aircraft.full_clean(exclude=['aircraft_id'])
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                aircraft.save()
                log_activity(request.user, "Added aircraft",
                             f"{aircraft.aircraft_id} - {tail_number}")
                messages.success(
                    request,
                    f"Aircraft {aircraft.aircraft_id} ({tail_number}) added with the "
                    f"{layout.seat_map} / {layout.total_capacity}-seat "
                    f"{aircraft_type.label} layout.")
                return redirect('airlines:airline_detail', airline.id)
    return render(request, 'airlines/aircraft_form.html',
                  _aircraft_form_context(airline, selected_type=selected_type))


@manager_required
def update_aircraft(request, aircraft_id):
    aircraft = get_object_or_404(
        Aircraft.objects.select_related('airline', 'aircraft_type__manufacturer',
                                        'seat_layout__aircraft_type__manufacturer'),
        pk=aircraft_id)
    airline = aircraft.airline
    selected_type = _query_pk(request, 'aircraft_type') or aircraft.aircraft_type_id
    layouts = _fleet_layouts(airline)
    if request.method == 'POST':
        tail_number = request.POST.get('tail_number', '').strip().upper()
        duplicate = (Aircraft.objects.filter(tail_number=tail_number)
                     .exclude(pk=aircraft.pk).exists()) if tail_number else False
        layout = layouts.get(selected_type)
        aircraft_type = AircraftType.objects.filter(pk=selected_type).first()
        if not tail_number:
            messages.error(request, "Tail number is required.")
        elif duplicate:
            messages.error(request, f"Tail number '{tail_number}' is already registered.")
        elif aircraft_type is None or layout is None:
            messages.error(request, "Choose an aircraft type from this airline's fleet.")
        else:
            aircraft.aircraft_type = aircraft_type
            aircraft.seat_layout = layout
            aircraft.tail_number = tail_number
            aircraft.status = request.POST.get('status') or aircraft.status
            aircraft.seating_capacity = layout.total_capacity
            try:
                aircraft.full_clean(exclude=['aircraft_id'])
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                aircraft.save()
                # A flight renders its aircraft's cabin, so re-fitting this
                # airframe has to re-seat every flight it operates.  Seats
                # already sold are never dropped, only raised.
                for flight in aircraft.flights.all():
                    flight.save()
                log_activity(request.user, "Updated aircraft",
                             f"{aircraft.aircraft_id} - {aircraft.tail_number}")
                messages.success(request, "Aircraft updated.")
                return redirect('airlines:airline_detail', aircraft.airline_id)
    return render(request, 'airlines/aircraft_form.html',
                  _aircraft_form_context(airline, aircraft=aircraft,
                                         selected_type=selected_type))


@manager_required
def airline_fleet(request, airline_id):
    """An airline's fleet: which aircraft types it operates, and its seat maps.

    Adding a type here is what makes it appear in the aircraft and flight
    dropdowns; removing one takes it out of both.  Aircraft and flights already
    on the type are kept — only the type's availability changes.
    """
    airline = get_object_or_404(
        Airline.objects.prefetch_related('photos', 'fleet_entries__aircraft_type__manufacturer'),
        pk=airline_id)
    layouts = _fleet_layouts(airline)

    if request.method == 'POST':
        action = request.POST.get('action')
        type_id = _post_pk(request, 'aircraft_type')
        entry = AirlineFleet.objects.filter(airline=airline, aircraft_type_id=type_id).first()
        if action == 'add':
            aircraft_type = AircraftType.objects.filter(pk=type_id, is_active=True).first()
            if aircraft_type is None:
                messages.error(request, "Choose an aircraft type to add to the fleet.")
            elif entry is not None:
                messages.warning(request, f"{aircraft_type.label} is already in the fleet.")
            else:
                first = not airline.fleet_entries.exists()
                AirlineFleet.objects.create(airline=airline, aircraft_type=aircraft_type,
                                            is_primary=first)
                if not layouts.get(aircraft_type.pk):
                    _create_default_layout(airline, aircraft_type)
                if first:
                    airline.default_aircraft_type = aircraft_type
                    airline.save(update_fields=['default_aircraft_type'])
                log_activity(request.user, "Added fleet type",
                             f"{airline.name} · {aircraft_type.label}")
                messages.success(request, f"{aircraft_type.label} added to {airline.name}'s fleet.")
        elif action == 'remove':
            # Retiring, not deleting: the type leaves the dropdowns but the
            # aircraft and flights already on it are left alone, so an
            # in-progress schedule is never stranded by a fleet change.
            if entry is None:
                messages.error(request, "That type is not in this airline's fleet.")
            else:
                entry.is_active = False
                entry.save(update_fields=['is_active'])
                log_activity(request.user, "Updated fleet",
                             f"{airline.name} · {entry.aircraft_type.label}")
                messages.success(
                    request,
                    f"{entry.aircraft_type.label} retired from {airline.name}'s fleet.")
        elif action == 'restore':
            if entry is None:
                messages.error(request, "That type is not in this airline's fleet.")
            else:
                entry.is_active = True
                entry.save(update_fields=['is_active'])
                log_activity(request.user, "Updated fleet",
                             f"{airline.name} · {entry.aircraft_type.label}")
                messages.success(request, f"{entry.aircraft_type.label} restored.")
        elif action == 'delete':
            # A hard delete is only safe once nothing is flying the type, and
            # the seat layout goes with it.
            if entry is None:
                messages.error(request, "That type is not in this airline's fleet.")
            elif airline.aircrafts.filter(aircraft_type=entry.aircraft_type).exists():
                messages.error(
                    request,
                    f"{entry.aircraft_type.label} still has aircraft registered. "
                    "Retire the type instead of deleting it.")
            else:
                label = entry.aircraft_type.label
                entry.delete()
                log_activity(request.user, "Deleted fleet type",
                             f"{airline.name} · {label}")
                messages.success(request, f"{label} removed from {airline.name}'s fleet.")

        elif action == 'primary':
            if entry is None:
                messages.error(request, "That type is not in this airline's fleet.")
            else:
                for other in airline.fleet_entries.all():
                    other.is_primary = (other.pk == entry.pk)
                    other.save(update_fields=['is_primary'])
                airline.default_aircraft_type = entry.aircraft_type
                airline.save(update_fields=['default_aircraft_type'])
                messages.success(
                    request,
                    f"{entry.aircraft_type.label} is now {airline.name}'s default type.")
        return redirect('airlines:airline_fleet', airline.pk)

    # One dict per row so the template reads a plain table instead of walking
    # related objects and looking a layout up by key.
    rows = []
    for entry in airline.fleet_entries.select_related('aircraft_type__manufacturer'):
        rows.append({
            'entry': entry,
            'type': entry.aircraft_type,
            'layout': layouts.get(entry.aircraft_type_id),
            'aircraft_count': airline.aircrafts.filter(
                aircraft_type=entry.aircraft_type).count(),
        })
    return render(request, 'airlines/fleet.html', {
        'airline': airline,
        'fleet_entries': rows,
        'available_types': AircraftType.objects.filter(is_active=True),
        'in_fleet_ids': {r['entry'].aircraft_type_id for r in rows},
    })


def _create_default_layout(airline, aircraft_type):
    """Give a newly added fleet type a cabin to fly.

    The spec comes from the aircraft type's body class, so the new type is
    immediately bookable instead of blocking every flight until a manager edits
    cabins by hand.
    """
    from airlines.fleet_data import FALLBACK_SPECS, write_layout

    return write_layout(SeatLayout, Cabin, Seat, airline, aircraft_type,
                        FALLBACK_SPECS.get(aircraft_type.body_class, 'NARROW_180'))


@manager_required
def aircrafts(request):
    qs = Aircraft.objects.select_related(
        'airline', 'aircraft_type__manufacturer', 'seat_layout').prefetch_related('airline__photos')
    airline_ids = _assigned_airline_ids_for_management(request)
    airlines = Airline.objects.prefetch_related('photos')
    if airline_ids is not None:
        qs = qs.filter(airline_id__in=airline_ids)
        airlines = airlines.filter(pk__in=airline_ids)
    q = request.GET.get('q', '')
    airline = request.GET.get('airline', '')
    aircraft_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    min_capacity = request.GET.get('min_capacity', '')
    if q:
        qs = qs.filter(Q(aircraft_id__icontains=q) | Q(tail_number__icontains=q)
                       | Q(aircraft_type__model_name__icontains=q)
                       | Q(aircraft_type__manufacturer__name__icontains=q))
    if airline:
        qs = qs.filter(airline_id=airline)
    if aircraft_type:
        qs = qs.filter(aircraft_type_id=aircraft_type)
    if status:
        qs = qs.filter(status=status)
    if min_capacity:
        qs = qs.filter(seating_capacity__gte=int(min_capacity))
    return render(request, 'airlines/aircrafts.html', {
        'aircrafts': qs,
        'airlines': airlines,
        'aircraft_types': AircraftType.objects.select_related('manufacturer'),
        'q': q, 'airline': airline, 'type': aircraft_type,
        'status': status, 'min_capacity': min_capacity,
    })


@manager_required
def aircraft_detail(request, aircraft_id):
    aircraft = get_object_or_404(
        Aircraft.objects.select_related(
            'airline', 'aircraft_type__manufacturer',
            'seat_layout__aircraft_type__manufacturer').prefetch_related('flights'),
        pk=aircraft_id)
    return render(request, 'airlines/aircraft_detail.html', {'aircraft': aircraft})


@manager_required
def fleet_api(request, airline_id):
    """JSON for the dependent aircraft-type / aircraft dropdowns.

    The admin forms also work without JavaScript by re-rendering the page, so
    this endpoint is the faster path rather than the only path: it returns the
    types the airline operates, each with the tail numbers already registered
    against it and the seat layout that type flies.
    """
    airline = get_object_or_404(Airline, pk=airline_id)
    layouts = _fleet_layouts(airline)
    types = []
    for aircraft_type in _fleet_types(airline):
        layout = layouts.get(aircraft_type.pk)
        if layout is None:
            continue
        types.append({
            'id': aircraft_type.pk,
            'label': aircraft_type.label,
            'body_class': aircraft_type.get_body_class_display(),
            'seat_layout': {
                'id': layout.pk,
                'name': layout.name,
                'seat_map': layout.seat_map,
                'capacity': layout.total_capacity,
                'cabins': [
                    {'key': cabin.fare_class, 'label': cabin.label,
                     'seat_map': cabin.seat_map, 'rows': cabin.rows,
                     'seats': cabin.seat_count}
                    for cabin in layout.cabins.all()
                ],
            },
            'aircraft': [
                {'id': a.pk, 'tail_number': a.tail_number, 'status': a.status,
                 'status_display': a.get_status_display()}
                for a in airline.aircrafts.filter(aircraft_type=aircraft_type)
            ],
        })
    return JsonResponse({'airline': {'id': airline.pk, 'name': airline.name},
                         'aircraft_types': types})


@manager_required
def add_service(request, airline_id):
    airline = get_object_or_404(Airline, pk=airline_id)
    if request.method == 'POST':
        service = Service.objects.create(
            airline=airline,
            name=request.POST.get('name'),
            description=request.POST.get('description', ''),
            rate=request.POST.get('rate') or 0,
            operating_hours=request.POST.get('operating_hours', ''),
            status=request.POST.get('status', Service.ServiceStatus.ACTIVE),
        )
        log_activity(request.user, "Added airline service", f"{service.service_id} - {service.name}")
        messages.success(request, f"Service {service.service_id} ({service.name}) added.")
        return redirect('airlines:airline_detail', airline.id)
    return render(request, 'airlines/service_form.html', {'airline': airline, 'service': None})


@manager_required
def update_service(request, service_id):
    service = get_object_or_404(Service, pk=service_id)
    if request.method == 'POST':
        for field in ('name', 'description', 'rate', 'operating_hours', 'status'):
            setattr(service, field, request.POST.get(field) or getattr(service, field))
        service.save()
        log_activity(request.user, "Updated airline service", f"{service.service_id} - {service.name}")
        messages.success(request, "Service updated.")
        return redirect('airlines:airline_detail', service.airline_id)
    return render(request, 'airlines/service_form.html', {'airline': service.airline, 'service': service})


@manager_required
def services(request):
    qs = Service.objects.select_related('airline').prefetch_related('airline__photos')
    airline_ids = _assigned_airline_ids_for_management(request)
    airlines = Airline.objects.prefetch_related('photos')
    if airline_ids is not None:
        qs = qs.filter(airline_id__in=airline_ids)
        airlines = airlines.filter(pk__in=airline_ids)
    q = request.GET.get('q', '')
    airline = request.GET.get('airline', '')
    status = request.GET.get('status', '')
    if q:
        qs = qs.filter(Q(service_id__icontains=q) | Q(name__icontains=q))
    if airline:
        qs = qs.filter(airline_id=airline)
    if status:
        qs = qs.filter(status=status)
    return render(request, 'airlines/services.html', {
        'services': qs,
        'airlines': airlines,
        'q': q, 'airline': airline, 'status': status,
    })


@manager_required
def service_detail(request, service_id):
    service = get_object_or_404(
        Service.objects.select_related('airline').prefetch_related('bookings'),
        pk=service_id)
    return render(request, 'airlines/service_detail.html', {'service': service})


@manager_required
def flights(request):
    qs = (Flight.objects
          .select_related('airline', 'aircraft', 'origin_airport', 'destination_airport')
          .prefetch_related('airline__photos'))
    airline_ids = _assigned_airline_ids_for_management(request)
    airlines = Airline.objects.prefetch_related('photos')
    if airline_ids is not None:
        qs = qs.filter(airline_id__in=airline_ids)
        airlines = airlines.filter(pk__in=airline_ids)
    q = request.GET.get('q', '')
    airline = request.GET.get('airline', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if q:
        qs = qs.filter(Q(flight_number__icontains=q) | Q(origin__icontains=q) | Q(destination__icontains=q)
                       | Q(origin_country__icontains=q) | Q(origin_province__icontains=q) | Q(origin_municipality__icontains=q)
                       | Q(destination_country__icontains=q) | Q(destination_province__icontains=q) | Q(destination_municipality__icontains=q)
                       | Q(origin_airport__airport_name__icontains=q) | Q(origin_airport__iata_code__icontains=q)
                       | Q(destination_airport__airport_name__icontains=q) | Q(destination_airport__iata_code__icontains=q))
    if airline:
        qs = qs.filter(airline_id=airline)
    if status:
        qs = qs.filter(status=status)
    if date_from:
        from_dt = _parse_dt(date_from)
        if from_dt:
            qs = qs.filter(departure_time__date__gte=from_dt.date())
    if date_to:
        to_dt = _parse_dt(date_to)
        if to_dt:
            qs = qs.filter(departure_time__date__lte=to_dt.date())
    return render(request, 'airlines/flights.html', {
        'flights': qs,
        'airlines': airlines,
        'q': q, 'airline': airline, 'status': status,
        'date_from': date_from, 'date_to': date_to,
    })


def _assigned_airline_ids_for_management(request):
    user = request.user
    if user.is_staff or set(effective_role_keys(user)).intersection(FULL_ACCESS_TYPES):
        return None

    assignment = getattr(request, 'active_simulation_assignment', None)
    if assignment is not None:
        establishment = assignment.establishment
        if establishment and establishment.type == 'AIRLINE' and establishment.entity_id:
            return {establishment.entity_id}
        return set()

    from simulation.models import SimulationRoleAssignment

    return set(
        SimulationRoleAssignment.objects.filter(
            student=user,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            establishment__type='AIRLINE',
            establishment__entity_id__isnull=False,
        ).values_list('establishment__entity_id', flat=True)
    )


def _post_pk(request, key):
    """Return the posted id as a positive int, or None when absent/garbage."""
    value = (request.POST.get(key) or '').strip()
    return int(value) if value.isdigit() and int(value) else None


def _active_airlines_unique_names():
    """Return one active airline per displayed name for airline selectors."""
    airlines = Airline.objects.filter(
        status=Airline.Status.ACTIVE
    ).order_by('name', 'pk').prefetch_related('photos')
    unique = []
    seen_names = set()
    for airline in airlines:
        normalized_name = ' '.join(airline.name.split()).casefold()
        if normalized_name and normalized_name not in seen_names:
            seen_names.add(normalized_name)
            unique.append(airline)
    return unique


def _flight_form_context(airline=None, flight=None, airline_fixed=False,
                         aircraft_type=None, return_aircraft_type=None,
                         trip_type=None):
    """Context for the flight form, scoped to the chosen airline's fleet.

    The aircraft list is the airline's own — an Emirates airframe can never be
    offered on a Cebu Pacific flight — and the type dropdown narrows it further,
    so the form reads as the dependent pair the requirement describes.  The same
    list backs both legs, because a round trip is flown by the same operator and
    the browser filters it to the type each leg selects.
    """
    return_leg = None
    if flight is not None:
        airline = flight.airline
        airline_fixed = True
        if flight.aircraft_id:
            aircraft_type = aircraft_type or flight.aircraft.aircraft_type_id
        return_leg = flight.return_flight
        if return_leg is None and return_aircraft_type is None:
            return_aircraft_type = aircraft_type
        trip_type = flight.trip_type
    elif trip_type not in (Flight.TripType.ONE_WAY, Flight.TripType.ROUND_TRIP):
        trip_type = Flight.TripType.ONE_WAY
    if airline is None:
        aircrafts = Aircraft.objects.none()
    elif flight is None:
        aircrafts = airline.aircrafts.filter(status=Aircraft.Status.AVAILABLE)
    else:
        # Keep the aircraft already on this flight selectable, even if it has
        # since been marked as assigned to another flight.
        keep = Q(status=Aircraft.Status.AVAILABLE)
        if flight.aircraft_id:
            keep |= Q(pk=flight.aircraft_id)
        if return_leg is not None and return_leg.aircraft_id:
            keep |= Q(pk=return_leg.aircraft_id)
        aircrafts = airline.aircrafts.filter(keep)
    layouts = _fleet_layouts(airline)
    types = [t for t in _fleet_types(airline) if t.pk in layouts]
    return {
        'airline': airline,
        'airline_fixed': airline_fixed,
        'airlines': _active_airlines_unique_names(),
        'aircrafts': aircrafts.select_related(
            'aircraft_type__manufacturer', 'seat_layout'
        ).prefetch_related('seat_layout__cabins'),
        'aircraft_types': types,
        'fleet_layouts': layouts,
        'selected_type': aircraft_type,
        'return_selected_type': return_aircraft_type,
        'trip_type': trip_type,
        'flight': flight,
        'return_leg': return_leg,
    }


NO_AIRCRAFT = '__none__'


def _posted_aircraft(request, prefix, airline):
    """The aircraft posted for one leg, only if it really belongs to the airline.

    The dropdown is airline-scoped, but a POST is not, so the relationship is
    re-checked here — an airframe from another carrier can never be smuggled onto
    a flight just by forging a hidden field.

    ``None`` is returned for "no airframe" and for a value that failed the checks;
    :func:`_resolve_leg` needs to tell those apart, so the raw value is inspected
    there via :data:`NO_AIRCRAFT` for the explicit "leave this leg unassigned"
    choice that a round trip needs (its return leg may reuse the departure airframe
    or deliberately fly a different one, or stay unscheduled like any other).
    """
    value = (request.POST.get(prefix + 'aircraft') or '').strip()
    if not value or value == NO_AIRCRAFT:
        return None
    aircraft = Aircraft.objects.select_related(
        'seat_layout', 'aircraft_type').filter(pk=value).first()
    if aircraft is None:
        return None
    if airline is not None and aircraft.airline_id != airline.pk:
        return None
    return aircraft


def _resolve_leg(request, airline, prefix='', label='Departure',
                 exclude_flight_id=None, aircraft=None):
    """Parse and validate one leg of a schedule.

    ``prefix`` is empty for the departure leg and ``'return_'`` for the return
    leg, so both go through identical validation and the return leg cannot drift
    from the departure one.  An aircraft stays optional — a flight is a
    schedule, and the seat map is derived from the airline's fleet when no
    airframe is assigned yet — but an aircraft that *is* chosen must have a
    configured seat layout, or the leg would sell seats nobody can sit in.

    ``aircraft`` overrides whatever the POST selected, which is how a round trip
    reuses the departure airframe on its return leg while still validating it
    like a real choice.

    Returns ``(data, errors)`` where ``data`` holds Flight attributes.
    """
    label = label.rstrip()
    flight_number = (request.POST.get(prefix + 'flight_number') or '').strip().upper()
    origin_airport = Airport.objects.filter(
        pk=_post_pk(request, prefix + 'origin_airport') or 0,
        status=Airport.Status.ACTIVE).first()
    destination_airport = Airport.objects.filter(
        pk=_post_pk(request, prefix + 'destination_airport') or 0,
        status=Airport.Status.ACTIVE).first()
    departure = _parse_dt(request.POST.get(prefix + 'departure_time'))
    arrival = _parse_dt(request.POST.get(prefix + 'arrival_time'))
    if aircraft is None:
        aircraft = _posted_aircraft(request, prefix, airline)

    errors = []
    if not flight_number:
        errors.append(f"{label} flight number is required.")
    else:
        duplicates = Flight.objects.filter(flight_number=flight_number)
        if exclude_flight_id:
            duplicates = duplicates.exclude(pk=exclude_flight_id)
        if duplicates.exists():
            errors.append(f"Flight number '{flight_number}' already exists.")
    if origin_airport is None:
        errors.append(f"{label} origin airport is required.")
    if destination_airport is None:
        errors.append(f"{label} destination airport is required.")
    if origin_airport and destination_airport and origin_airport.pk == destination_airport.pk:
        errors.append("Origin and destination cannot be the same airport.")
    if not departure or not arrival:
        errors.append(f"{label} departure and arrival times are required.")
    elif arrival <= departure:
        errors.append(f"{label} arrival must be after departure.")
    if aircraft is not None:
        if aircraft.seat_layout_id is None:
            errors.append(
                f"{aircraft.tail_number} has no seat layout configured, so it "
                "cannot be sold. Configure its seat layout first.")
        elif departure and arrival and _aircraft_conflict(
                aircraft, departure, arrival, exclude_id=exclude_flight_id):
            errors.append(
                f"{aircraft.tail_number} is already scheduled during that time.")

    data = {
        'aircraft': aircraft,
        'flight_number': flight_number,
        'origin_airport': origin_airport,
        'destination_airport': destination_airport,
        'departure_time': departure,
        'arrival_time': arrival,
    }
    if origin_airport and destination_airport:
        origin = _airport_endpoint_payload(origin_airport)
        destination = _airport_endpoint_payload(destination_airport)
        data.update({
            'origin': origin['name'],
            'destination': destination['name'],
            'origin_code': origin['code'][:8],
            'destination_code': destination['code'][:8],
            'origin_country': origin['country'],
            'origin_province': origin['region'],
            'origin_municipality': origin['municipality'],
            'destination_country': destination['country'],
            'destination_province': destination['region'],
            'destination_municipality': destination['municipality'],
        })
    return data, errors


def _resolve_flight_schedule(request, flight=None, airline=None):
    """Parse and validate the whole Add/Update Flight form, both legs included.

    An aircraft is optional — a flight is only a schedule.  The sellable seats
    come from the seat layout of whichever aircraft operates the leg, falling
    back to the airline's default type (BR-042); an aircraft is only checked for
    availability when one is actually assigned (BR-041).

    A Round Trip is stored as two ``Flight`` rows that share a round-trip group,
    because the two legs can be operated by different aircraft and therefore
    have different cabins and seat maps.  The return leg's route is forced to
    mirror the outbound one rather than trusted from the form.

    Returns ``(result, errors)``.  ``result`` carries ``departure``/``return_leg``
    Flight attribute dicts plus the shared pricing and status fields.
    """
    # The URL pins the airline when the form was reached from an airline page;
    # otherwise the manager chooses it in the form itself.
    if airline is None:
        airline = Airline.objects.filter(
            pk=_post_pk(request, 'airline') or 0,
            status=Airline.Status.ACTIVE).first()

    trip_type = request.POST.get('trip_type') or (
        flight.trip_type if flight else Flight.TripType.ONE_WAY)
    if trip_type not in (Flight.TripType.ONE_WAY, Flight.TripType.ROUND_TRIP):
        trip_type = flight.trip_type if flight else Flight.TripType.ONE_WAY

    errors = []
    if airline is None:
        errors.append("Please choose an airline.")
    if airline is not None and not airline.fleet_entries.filter(is_active=True).exists():
        errors.append(
            f"{airline.name} has no aircraft types in its fleet, so there is no "
            "cabin to sell. Configure the fleet first.")

    exclude_id = flight.pk if flight else None
    departure, departure_errors = _resolve_leg(
        request, airline, prefix='', label='Departure', exclude_flight_id=exclude_id)
    errors.extend(departure_errors)

    # Only the departure leg's aircraft may still be "keep the current value"
    # when the key is absent, which happens on a partial update.
    if flight is not None and 'aircraft' not in request.POST:
        departure['aircraft'] = flight.aircraft

    return_leg = None
    if trip_type == Flight.TripType.ROUND_TRIP:
        # "Same aircraft as departure" posts a blank value, which is also how a
        # leg is left unassigned.  The two are told apart by NO_AIRCRAFT: blank
        # copies the departure airframe, and the sentinel keeps the return leg
        # open.  The inherited airframe is resolved before validation so it is
        # held to the same seat-layout and no-double-booking rules as a chosen
        # one instead of quietly skipping them.
        posted_return = (request.POST.get('return_aircraft') or '').strip()
        return_aircraft = None
        if posted_return == '' and departure.get('aircraft') is not None:
            return_aircraft = departure['aircraft']
        return_leg, return_errors = _resolve_leg(
            request, airline, prefix='return_', label='Return',
            exclude_flight_id=exclude_id, aircraft=return_aircraft)
        errors.extend(return_errors)
        # The return leg flies the route in reverse, so the form's copy of it is
        # cross-checked rather than believed: a mismatch means the manager
        # flipped one end of the journey by accident.
        if departure.get('origin_airport') and return_leg.get('origin_airport'):
            if return_leg['origin_airport'].pk != departure['destination_airport'].pk:
                errors.append(
                    "Return origin must be the departure destination "
                    f"({departure['destination']}).")
        if departure.get('destination_airport') and return_leg.get('destination_airport'):
            if return_leg['destination_airport'].pk != departure['origin_airport'].pk:
                errors.append(
                    "Return destination must be the departure origin "
                    f"({departure['origin']}).")
        if departure.get('departure_time') and return_leg.get('departure_time'):
            if return_leg['departure_time'].date() < departure['departure_time'].date():
                errors.append("Return date must not be earlier than the departure date.")
        # One airframe cannot fly both legs back to back.
        out_ac = departure.get('aircraft')
        back_ac = return_leg.get('aircraft')
        if out_ac is not None and back_ac is not None and out_ac.pk == back_ac.pk:
            if return_leg['departure_time'] and return_leg['arrival_time'] \
                    and _aircraft_conflict(
                        out_ac, return_leg['departure_time'],
                        return_leg['arrival_time'], exclude_id=exclude_id):
                errors.append(
                    f"{out_ac.tail_number} is already flying the return leg during "
                    "that time. Choose a different aircraft.")

    result = {
        'airline': airline,
        'trip_type': trip_type,
        'departure': departure,
        'return_leg': return_leg,
        'terminal': (request.POST.get('terminal') or '').strip()[:50],
        'gate': (request.POST.get('gate') or '').strip()[:50],
        'first_class_fare': request.POST.get('first_class_fare') or 0,
        'business_fare': request.POST.get('business_fare') or 0,
        'premium_economy_fare': request.POST.get('premium_economy_fare') or 0,
        'economy_fare': request.POST.get('economy_fare') or 0,
        'baggage_rate': request.POST.get('baggage_rate') or 0,
        'status': request.POST.get('status') or (flight.status if flight else Flight.Status.SCHEDULED),
    }
    return result, errors


# ---------------------------------------------------------------------------
# Connecting flights: one itinerary, several real legs
# ---------------------------------------------------------------------------
# The Add/Update Flight form posts its segments as ``seg_<n>_<field>`` with a
# ``segment_count``, so any number of connections can be added or removed in the
# browser without the server needing to know in advance how many there will be.
# Every field is still validated here: a post can lie about the segment count,
# the airports, the times or the aircraft, and each of those is re-checked here.


def _segment_key(index, field):
    return f"seg_{index}_{field}"


def _posted_segment_count(request):
    """How many legs the form says the journey has, capped at the sane maximum.

    The cap matters: a forged count of 100000 would otherwise make the
    validator loop over 100000 absent fields.
    """
    raw = (request.POST.get('segment_count') or '').strip()
    if not raw.isdigit():
        return 0
    return min(int(raw), MAX_ITINERARY_SEGMENTS + 1)


def _posted_time(request, index, field):
    return parse_clock(request.POST.get(_segment_key(index, field)))


def _posted_day(request, index, field):
    return _parse_date(request.POST.get(_segment_key(index, field)))


def _posted_decimal(request, key, default=0):
    """Read a money/weight field as a number, ignoring anything that is not one."""
    raw = (request.POST.get(key) or '').strip().replace(',', '')
    if not raw:
        return default
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _posted_int(request, key, default=0):
    raw = (request.POST.get(key) or '').strip()
    return int(raw) if raw.isdigit() and int(raw) >= 0 else default


def _posted_airport(request, index, field):
    """The airport posted for one leg, only if it is a real active airport."""
    return Airport.objects.filter(
        pk=_post_pk(request, _segment_key(index, field)) or 0,
        status=Airport.Status.ACTIVE).first()


def _resolve_itinerary_leg(request, airline, index, label, exclude_flight_id=None):
    """Parse and validate one leg of a connecting journey.

    Times are read as *airport-local* date + clock and pinned to that airport's
    own timezone before anything is compared, so a Manila departure and a Dubai
    arrival are measured against real instants rather than two wall clocks.
    """
    errors = []
    flight_number = (request.POST.get(_segment_key(index, 'flight_number'))
                     or '').strip().upper()
    origin_airport = _posted_airport(request, index, 'origin_airport')
    destination_airport = _posted_airport(request, index, 'destination_airport')
    departure_day = _posted_day(request, index, 'departure_date')
    departure_clock = _posted_time(request, index, 'departure_time')
    arrival_day = _posted_day(request, index, 'arrival_date')
    arrival_clock = _posted_time(request, index, 'arrival_time')

    if not flight_number:
        errors.append(f"{label} flight number is required.")
    else:
        duplicates = Flight.objects.filter(flight_number=flight_number)
        if exclude_flight_id:
            duplicates = duplicates.exclude(pk=exclude_flight_id)
        if duplicates.exists():
            errors.append(f"Flight number '{flight_number}' already exists.")
    if origin_airport is None:
        errors.append(f"{label} departure airport is required.")
    if destination_airport is None:
        errors.append(f"{label} arrival airport is required.")
    if origin_airport and destination_airport and origin_airport.pk == destination_airport.pk:
        errors.append(
            f"{label}: departure and arrival airports cannot be the same "
            f"({origin_airport.code or origin_airport.airport_name}).")

    if not departure_day or not departure_clock:
        errors.append(f"{label} departure date and time are required.")
    if not arrival_day or not arrival_clock:
        errors.append(f"{label} arrival date and time are required.")

    departure_local = arrival_local = None
    if departure_day and departure_clock and origin_airport:
        departure_local = combine_local(departure_day, departure_clock,
                                        airport_timezone(origin_airport))
    if arrival_day and arrival_clock and destination_airport:
        arrival_local = combine_local(arrival_day, arrival_clock,
                                      airport_timezone(destination_airport))

    flight_minutes = None
    if departure_local and arrival_local:
        flight_minutes = segment_duration_minutes(
            departure_local, arrival_local,
            departure_local.tzinfo, arrival_local.tzinfo)
        if flight_minutes is None:
            errors.append(
                f"{label} arrival must be after departure "
                f"(the times are read in each airport's own time zone).")

    aircraft = _posted_aircraft(request, _segment_key(index, ''), airline)
    if aircraft is None:
        # A value was posted but did not survive the ownership check, so the
        # leg would quietly end up on the airline's default layout instead. That
        # is a forged or stale option, and the manager needs to be told rather
        # than left wondering why their airframe vanished.
        raw_aircraft = (request.POST.get(_segment_key(index, 'aircraft')) or '').strip()
        if raw_aircraft and raw_aircraft != NO_AIRCRAFT:
            errors.append(
                f"{label}: aircraft {raw_aircraft} is not an airframe of "
                f"{airline.name if airline else 'this airline'}. Pick one from "
                "the list, or leave it blank to use the airline's default fleet.")
    if aircraft is not None and aircraft.seat_layout_id is None:
        errors.append(
            f"{aircraft.tail_number} has no seat layout configured, so it "
            "cannot be sold. Configure its seat layout first.")

    data = {
        'flight_number': flight_number,
        'origin_airport': origin_airport,
        'destination_airport': destination_airport,
        'aircraft': aircraft,
        'departure_time': departure_local,
        'arrival_time': arrival_local,
        'segment_duration_minutes': flight_minutes or 0,
        'terminal': (request.POST.get(_segment_key(index, 'departure_terminal'))
                     or '').strip()[:50],
        'gate': (request.POST.get(_segment_key(index, 'departure_gate'))
                 or '').strip()[:50],
        'arrival_terminal': (request.POST.get(_segment_key(index, 'arrival_terminal'))
                             or '').strip()[:50],
        'arrival_gate': (request.POST.get(_segment_key(index, 'arrival_gate'))
                         or '').strip()[:50],
        'baggage_claim': (request.POST.get(_segment_key(index, 'baggage_claim'))
                          or '').strip()[:50],
        'check_in_time': _posted_time(request, index, 'check_in_time'),
        'boarding_time': _posted_time(request, index, 'boarding_time'),
        'checked_baggage_kg': _posted_int(
            request, _segment_key(index, 'checked_baggage_kg')),
        'cabin_baggage_kg': _posted_int(
            request, _segment_key(index, 'cabin_baggage_kg')),
        'departure_timezone': (origin_airport.timezone_name if origin_airport else ''),
        'arrival_timezone': (destination_airport.timezone_name
                             if destination_airport else ''),
        'first_class_fare': _posted_decimal(
            request, _segment_key(index, 'first_class_fare')),
        'business_fare': _posted_decimal(
            request, _segment_key(index, 'business_fare')),
        'premium_economy_fare': _posted_decimal(
            request, _segment_key(index, 'premium_economy_fare')),
        'economy_fare': _posted_decimal(
            request, _segment_key(index, 'economy_fare')),
    }
    if origin_airport and destination_airport:
        origin = _airport_endpoint_payload(origin_airport)
        destination = _airport_endpoint_payload(destination_airport)
        data.update({
            'origin': origin['name'],
            'destination': destination['name'],
            'origin_code': origin['code'][:8],
            'destination_code': destination['code'][:8],
            'origin_country': origin['country'],
            'origin_province': origin['region'],
            'origin_municipality': origin['municipality'],
            'destination_country': destination['country'],
            'destination_province': destination['region'],
            'destination_municipality': destination['municipality'],
        })

    # A single airframe cannot be in two places at once, checked across the
    # whole journey rather than leg by leg (see _check_itinerary_aircraft).
    return data, errors


def _check_itinerary_sequence(legs, errors, min_connection_minutes=0,
                              max_connection_minutes=0):
    """The rules that make a chain of legs one flyable journey.

    Three things must hold between consecutive legs:

    1. the previous leg's arrival airport *is* the next leg's departure airport,
    2. the next leg departs after the previous one arrives, and
    3. the connection is long enough to make (and not longer than the operator
       allows).

    A mismatch on (1) is the interesting one: MNL->SIN followed by CEB->DXB is
    two flights, not one journey, and a passenger holding both would be stranded
    in Singapore.
    """
    from zoneinfo import ZoneInfo

    for index, (previous, current) in enumerate(zip(legs, legs[1:]), start=2):
        prev_arrival = previous.get('destination_airport')
        next_origin = current.get('origin_airport')
        if prev_arrival and next_origin and prev_arrival.pk != next_origin.pk:
            errors.append(
                f"Segment {index} departs from "
                f"{next_origin.code or next_origin.airport_name} but segment "
                f"{index - 1} arrives at "
                f"{prev_arrival.code or prev_arrival.airport_name}. Each "
                "connection must continue from the airport the previous leg "
                "arrived at.")
        prev_arrival_at = previous.get('arrival_time')
        next_departure_at = current.get('departure_time')
        if prev_arrival_at and next_departure_at:
            minutes = layover_minutes(
                prev_arrival_at, next_departure_at,
                ZoneInfo(previous.get('arrival_timezone') or DEFAULT_AIRPORT_TIMEZONE),
                ZoneInfo(current.get('departure_timezone') or DEFAULT_AIRPORT_TIMEZONE))
            if minutes is None:
                errors.append(
                    f"Segment {index} departs before segment {index - 1} "
                    "arrives. A connection has to happen after the passenger "
                    "has landed.")
            elif min_connection_minutes and minutes < min_connection_minutes:
                errors.append(
                    f"Segment {index} connects after only {format_duration(minutes)}; "
                    f"this itinerary needs at least "
                    f"{format_duration(min_connection_minutes)} to make the "
                    "connection.")
            elif max_connection_minutes and minutes > max_connection_minutes:
                errors.append(
                    f"Segment {index} connects after {format_duration(minutes)}, "
                    f"longer than the {format_duration(max_connection_minutes)} "
                    "this itinerary allows.")


def _check_itinerary_aircraft(legs, errors, exclude_ids=()):
    """One airframe cannot fly two legs of the same journey at the same time."""
    for index, leg in enumerate(legs, start=1):
        aircraft = leg.get('aircraft')
        if aircraft is None:
            continue
        departure, arrival = leg.get('departure_time'), leg.get('arrival_time')
        if not (departure and arrival):
            continue
        if _aircraft_conflict(aircraft, departure, arrival,
                              exclude_id=exclude_ids[index - 1] if exclude_ids else None):
            errors.append(
                f"Segment {index}: {aircraft.tail_number} is already scheduled "
                "during that time.")
        for other_index, other in enumerate(legs, start=1):
            if other_index <= index or other.get('aircraft') is not aircraft:
                continue
            other_departure = other.get('departure_time')
            other_arrival = other.get('arrival_time')
            if not (other_departure and other_arrival):
                continue
            if departure < other_arrival and other_departure < arrival:
                errors.append(
                    f"Segments {index} and {other_index} both use "
                    f"{aircraft.tail_number} at the same time. One aircraft "
                    "cannot fly two legs at once.")


def _check_itinerary_flight_numbers(legs, errors):
    """No two legs of one journey may share a flight number.

    The per-leg check only looks at what is already in the database, so a number
    that appears twice in a *new* journey would otherwise sail through and be
    written to two rows.  Two segments of one ticket under the same number cannot
    be told apart at the gate or on a boarding pass.
    """
    seen = {}
    for index, leg in enumerate(legs, start=1):
        number = (leg.get('flight_number') or '').strip()
        if not number:
            continue
        if number in seen:
            errors.append(
                f"Segments {seen[number]} and {index} both use flight number "
                f"'{number}'. Every leg of a journey needs its own number.")
        else:
            seen[number] = index


def _resolve_itinerary_schedule(request, airline=None, itinerary=None):
    """Parse and validate a whole connecting itinerary, server-side.

    Returns ``(result, errors)``.  ``result['legs']`` is a list of ``Flight``
    attribute dicts in travel order, ready to be turned into rows.  The same
    function serves create and update, so a journey cannot be created with rules
    it could not be edited under.
    """
    if airline is None:
        airline = Airline.objects.filter(
            pk=_post_pk(request, 'airline') or 0,
            status=Airline.Status.ACTIVE).first()
    if itinerary is not None:
        airline = airline or itinerary.airline

    trip_type = request.POST.get('trip_type') or (
        itinerary.trip_type if itinerary else Flight.TripType.ONE_WAY)
    if trip_type not in (Flight.TripType.ONE_WAY, Flight.TripType.ROUND_TRIP):
        trip_type = itinerary.trip_type if itinerary else Flight.TripType.ONE_WAY

    errors = []
    if airline is None:
        errors.append("Please choose an airline.")
    if airline is not None and not airline.fleet_entries.filter(is_active=True).exists():
        errors.append(
            f"{airline.name} has no aircraft types in its fleet, so there is no "
            "cabin to sell. Configure the fleet first.")

    # Existing legs, so an update can exclude each leg's own row from the
    # duplicate and double-booking checks instead of colliding with itself.
    existing = list(itinerary.ordered_legs) if itinerary is not None else []
    exclude_ids = [None] * MAX_ITINERARY_SEGMENTS
    for index in range(min(len(existing), MAX_ITINERARY_SEGMENTS)):
        posted_id = _post_pk(request, _segment_key(index, 'id'))
        if posted_id and any(leg.pk == posted_id for leg in existing):
            exclude_ids[index] = posted_id

    count = _posted_segment_count(request)
    if count < 1:
        errors.append("A connecting itinerary needs at least one flight segment.")
    elif count > MAX_ITINERARY_SEGMENTS:
        errors.append(
            f"A journey can have at most {MAX_ITINERARY_SEGMENTS} segments.")
    if count == 1:
        errors.append(
            "A connecting itinerary needs at least 2 flight segments. Use "
            "Direct for a single flight.")

    legs = []
    for index in range(min(count, MAX_ITINERARY_SEGMENTS)):
        leg, leg_errors = _resolve_itinerary_leg(
            request, airline, index, f"Segment {index + 1}",
            exclude_flight_id=exclude_ids[index])
        leg['segment_order'] = index + 1
        leg['id'] = exclude_ids[index]
        legs.append(leg)
        errors.extend(leg_errors)

    min_connection = _posted_int(request, 'min_connection_minutes', 45)
    max_connection = _posted_int(request, 'max_connection_minutes', 0)
    if max_connection and min_connection > max_connection:
        errors.append(
            "The minimum connection time cannot be longer than the maximum "
            "connection time.")

    # Sequence and aircraft checks only make sense on legs that parsed, so they
    # run on what came back and report whatever is missing rather than crashing.
    _check_itinerary_sequence(legs, errors, min_connection, max_connection)
    _check_itinerary_aircraft(legs, errors, exclude_ids)
    _check_itinerary_flight_numbers(legs, errors)

    result = {
        'airline': airline,
        'trip_type': trip_type,
        'legs': legs,
        'status': (request.POST.get('itinerary_status')
                   or (itinerary.status if itinerary else Flight.Status.SCHEDULED)),
        'operating_days': (request.POST.get('operating_days') or '').strip()[:40],
        'booking_available': request.POST.get('booking_available') is not None,
        'base_fare': _posted_decimal(request, 'base_fare'),
        'taxes': _posted_decimal(request, 'taxes'),
        'airport_fees': _posted_decimal(request, 'airport_fees'),
        'fuel_surcharge': _posted_decimal(request, 'fuel_surcharge'),
        'service_fee': _posted_decimal(request, 'service_fee'),
        'discount': _posted_decimal(request, 'discount'),
        'baggage_rate': _posted_decimal(request, 'itinerary_baggage_rate'),
        'is_refundable': request.POST.get('is_refundable') is not None,
        'is_changeable': request.POST.get('is_changeable') is not None,
        'change_fee': _posted_decimal(request, 'change_fee'),
        'cancellation_fee': _posted_decimal(request, 'cancellation_fee'),
        'min_advance_booking_hours': _posted_int(request, 'min_advance_booking_hours'),
        'min_connection_minutes': min_connection,
        'max_connection_minutes': max_connection,
    }
    if not result['base_fare'] and legs:
        # A journey with no base fare would be sold at zero, which is a booking
        # the platform cannot take money for.
        result['base_fare'] = sum(
            (leg.get('economy_fare') or 0) for leg in legs)
    return result, errors


def _save_itinerary(result, itinerary=None):
    """Write a validated itinerary and its legs to the database.

    The legs are saved in travel order inside the caller's transaction so a
    failure part-way cannot leave a journey whose segment 2 has no segment 1.
    """
    airline = result['airline']
    if itinerary is None:
        itinerary = FlightItinerary(airline=airline)
    for key in ('trip_type', 'status', 'operating_days', 'booking_available',
                'base_fare', 'taxes', 'airport_fees', 'fuel_surcharge',
                'service_fee', 'discount', 'baggage_rate', 'is_refundable',
                'is_changeable', 'change_fee', 'cancellation_fee',
                'min_advance_booking_hours', 'min_connection_minutes',
                'max_connection_minutes'):
        setattr(itinerary, key, result[key])
    itinerary.save()

    existing = {leg.pk: leg for leg in itinerary.ordered_legs}
    seen = set()
    saved = []
    for leg in result['legs']:
        leg_id = leg.get('id')
        flight = existing.get(leg_id) if leg_id else None
        if flight is None:
            flight = Flight(airline=airline, itinerary=itinerary)
        for key, value in leg.items():
            if key in ('id',):
                continue
            setattr(flight, key, value)
        flight.airline = airline
        flight.itinerary = itinerary
        flight.trip_type = Flight.TripType.ONE_WAY
        flight.trip_role = TripRole.OUTBOUND
        flight.round_trip_group = None
        flight.paired_flight = None
        flight.save()
        seen.add(flight.pk)
        saved.append(flight)
        _apply_aircraft_status(flight, None)

    # A leg the manager deleted is removed with the journey: leaving it would
    # strand the sequence (a segment 2 with no segment 1) and it would still
    # appear in search as a separate direct flight.
    for pk, flight in existing.items():
        if pk not in seen:
            flight.delete()
    itinerary.refresh_timing()
    itinerary.save()
    return itinerary, saved


def _leg_text(leg, rejected, field):
    """Read a short text field off a segment, whether it is a row or a dict."""
    return (leg.get(field) or '') if rejected else (getattr(leg, field, '') or '')


def _leg_number(leg, rejected, field):
    """Read a numeric field off a segment, whether it is a row or a dict."""
    return (leg.get(field) or 0) if rejected else (getattr(leg, field, 0) or 0)


def _leg_clock(leg, rejected, field):
    """A HH:MM string for a time field, which may be stored as a time or a dt."""
    value = leg.get(field) if rejected else getattr(leg, field, None)
    if not value:
        return ''
    try:
        return value.strftime('%H:%M')
    except AttributeError:
        return str(value)[:5]


def _itinerary_form_context(airline=None, itinerary=None, legs=None):
    """Context for the connecting-flight part of the flight form.

    The aircraft list stays the airline's own, exactly as on the direct form, so
    an Emirates airframe can never be offered on a Cebu Pacific journey.  When a
    rejected POST comes back, ``legs`` carries what was actually typed so the
    manager does not lose the whole journey to one bad field.
    """
    if itinerary is not None:
        airline = itinerary.airline
    legs = itinerary.ordered_legs if itinerary is not None else (legs or [])
    # The segment inputs are split into a date and a clock so each is read in its
    # own airport's time zone, so the form needs the legs as *local* wall clock
    # strings rather than the UTC values stored in the columns.
    #
    # Two shapes arrive here. A saved itinerary (and a plain GET) hands over
    # ``Flight`` rows, whose times are UTC in the database and need the segment's
    # own zone. A rejected POST hands over the attribute dicts straight out of
    # :func:`_resolve_itinerary_leg`, whose times are already the local values
    # the manager typed, so they are used as they are.
    rejected = bool(legs) and isinstance(legs[0], dict)
    timing = {'legs': []} if rejected else itinerary_timing(legs)
    by_pk = {leg.pk: entry for leg, entry in zip(legs, timing['legs'])}
    leg_fields = []
    for position, leg in enumerate(legs):
        entry = by_pk.get(getattr(leg, 'pk', None), {})
        if rejected:
            departure = leg.get('departure_time')
            arrival = leg.get('arrival_time')
            origin, destination = leg.get('origin_airport'), leg.get('destination_airport')
            aircraft_id, leg_id = '', leg.get('id') or ''
        else:
            departure = entry.get('departure_local')
            arrival = entry.get('arrival_local')
            origin = leg.origin_airport if leg.origin_airport_id else None
            destination = leg.destination_airport if leg.destination_airport_id else None
            aircraft_id, leg_id = leg.aircraft_id or '', leg.pk
        leg_fields.append({
            'id': leg_id,
            'flight_number': leg['flight_number'] if rejected else (leg.flight_number or ''),
            'aircraft': aircraft_id,
            'origin': origin.pk if origin else '',
            'origin_code': origin.code or '' if origin else '',
            'origin_city': origin.city or '' if origin else '',
            'destination': destination.pk if destination else '',
            'destination_code': destination.code or '' if destination else '',
            'destination_city': destination.city or '' if destination else '',
            'departure_date': departure.strftime('%Y-%m-%d') if departure else '',
            'departure_time': departure.strftime('%H:%M') if departure else '',
            'arrival_date': arrival.strftime('%Y-%m-%d') if arrival else '',
            'arrival_time': arrival.strftime('%H:%M') if arrival else '',
            'departure_terminal': _leg_text(leg, rejected, 'terminal'),
            'departure_gate': _leg_text(leg, rejected, 'gate'),
            'arrival_terminal': _leg_text(leg, rejected, 'arrival_terminal'),
            'arrival_gate': _leg_text(leg, rejected, 'arrival_gate'),
            'baggage_claim': _leg_text(leg, rejected, 'baggage_claim'),
            'check_in_time': _leg_clock(leg, rejected, 'check_in_time'),
            'boarding_time': _leg_clock(leg, rejected, 'boarding_time'),
            'checked_baggage_kg': _leg_number(leg, rejected, 'checked_baggage_kg'),
            'cabin_baggage_kg': _leg_number(leg, rejected, 'cabin_baggage_kg'),
            'economy_fare': str(_leg_number(leg, rejected, 'economy_fare')),
            'premium_economy_fare': str(_leg_number(leg, rejected, 'premium_economy_fare')),
            'business_fare': str(_leg_number(leg, rejected, 'business_fare')),
            'first_class_fare': str(_leg_number(leg, rejected, 'first_class_fare')),
        })
    active_airlines = _active_airlines_unique_names()
    return {
        'airline': airline,
        'airlines': active_airlines,
        'airlines_json': json.dumps([
            {'id': a.pk, 'name': a.name, 'logo': a.logo_url,
             'types': [{'id': t.pk, 'label': t.label,
                        'seats': t.typical_capacity}
                       for t in _fleet_types(a)],
             'aircrafts': [
                 {'id': ac.pk, 'label': f"{ac.model_name} ({ac.tail_number})",
                  'type': ac.aircraft_type_id,
                  'map': ac.seat_layout.seat_map,
                  'seats': ac.seat_layout.total_capacity}
                 for ac in a.aircrafts.filter(status=Aircraft.Status.AVAILABLE)
                 .select_related('aircraft_type__manufacturer', 'seat_layout')]}
            for a in active_airlines]),
        'itinerary': itinerary,
        'itinerary_legs': legs,
        # A plain list, not a pre-dumped string: the template hands it to
        # json_script, which serialises it itself. Everything in it is already a
        # str/int/bool so the amounts stay exact.
        'itinerary_legs_data': leg_fields,
        'flight_type': (itinerary.flight_type if itinerary is not None
                        else FlightItinerary.FlightType.CONNECTING),
        'max_segments': MAX_ITINERARY_SEGMENTS,
        'timezones': sorted({
            tz for tz in Airport.objects.exclude(timezone='')
            .values_list('timezone', flat=True).distinct() if tz}),
    }



@manager_required
def flight_detail(request, flight_id):
    flight = get_object_by_slug_or_404(
        Flight.objects.select_related(
            'airline', 'aircraft__aircraft_type__manufacturer',
            'aircraft__seat_layout__aircraft_type__manufacturer',
            'airline__default_aircraft_type__manufacturer',
        ).prefetch_related('bookings'),
        flight_id)
    # A leg of a connecting journey is one row of a bigger journey, so opening
    # it lands on the itinerary. The manager then edits or views the whole
    # thing, never one leg out of context.
    if flight.itinerary_id:
        if (not can_access_module(request.user, 'airlines')
                or hasattr(request, 'active_simulation_assignment')):
            return redirect('airlines:itinerary_public_detail', flight.itinerary.pk)
        return redirect('airlines:itinerary_detail', flight.itinerary.pk)
    remaining = flight.capacity - _booked_seats(flight)
    active_assignment = getattr(request, 'active_simulation_assignment', None)
    return render(request, 'airlines/flight_detail.html', {
        'flight': flight,
        'remaining': remaining,
        'seat_layout': flight.seat_layout,
        'can_book_flight': (
            active_assignment is not None
            and active_assignment.role == 'PASSENGER_AIRLINE'
            and remaining > 0
            and resource_is_bookable(flight)
            and flight.status in (Flight.Status.SCHEDULED, Flight.Status.DELAYED)
        ),
        'can_manage_airline': (
            can_access_module(request.user, 'airlines')
            and active_assignment is None
        ),
    })


def _itinerary_seat_maps(itinerary):
    """Per-leg seat availability and seat map for a connecting journey.

    Each leg is a different airframe, so each gets its own map: 12A on the MNL-SIN
    aircraft says nothing about the SIN-DXB one.  A leg with no seat layout
    configured is reported as unavailable rather than silently drawing an empty
    cabin nobody can book.
    """
    rows = []
    for leg in itinerary.ordered_legs:
        seat_map = _seat_map(leg)
        capacity = leg.capacity
        rows.append({
            'flight': leg,
            'seat_map': seat_map,
            'remaining': max(0, capacity - _booked_seats(leg)),
            'cabin_classes': leg.cabin_classes,
        })
    return rows


@manager_required
def itinerary_detail(request, itinerary_id):
    """The whole connecting journey: every leg, every layover, the whole price.

    The manager screen, so it also carries the edit and delete-deactivate
    controls for the schedule.
    """
    itinerary = get_object_or_404(
        FlightItinerary.objects.select_related('airline'), pk=itinerary_id)
    timing = itinerary.timing
    segment_rows = _itinerary_seat_maps(itinerary)
    return render(request, 'airlines/itinerary_detail.html', {
        'itinerary': itinerary,
        'timing': timing,
        'legs': itinerary.ordered_legs,
        'first_leg': itinerary.first_leg,
        'last_leg': itinerary.last_leg,
        'remaining': min([row['remaining'] for row in segment_rows] or [0]),
        'segment_maps': segment_rows,
    })


@login_required
def itinerary_public_detail(request, itinerary_id):
    """The passenger-facing timeline for one connecting journey.

    Shows only this itinerary — never another flight, and never land
    transportation — with a segment per real leg and the layover between them.
    """
    itinerary = get_object_or_404(
        FlightItinerary.objects.select_related('airline'),
        pk=itinerary_id)
    if not itinerary.is_bookable():
        messages.warning(request, "This journey is not currently bookable.")
        return redirect('airlines:list')
    timing = itinerary.timing
    segment_rows = _itinerary_seat_maps(itinerary)
    return render(request, 'airlines/itinerary_public.html', {
        'itinerary': itinerary,
        'timing': timing,
        'legs': itinerary.ordered_legs,
        'segment_rows': segment_rows,
        'remaining': min([row['remaining'] for row in segment_rows] or [0]),
        'trip_type': itinerary.trip_type,
    })


def _shared_leg_fields(data):
    """The pricing/status fields both legs of a trip are sold on."""
    return {key: data[key] for key in (
        'terminal', 'gate', 'first_class_fare', 'business_fare',
        'premium_economy_fare', 'economy_fare', 'baggage_rate', 'status')}


def _save_round_trip(request, flight, result):
    """Persist a Round Trip as two linked flight rows.

    The two legs are separate ``Flight`` rows rather than one row with a return
    date, because the airline can operate the return with a different aircraft —
    and then it has a different cabin, capacity and seat map.  Both rows share a
    ``round_trip_group`` and point at each other, so either leg can be opened and
    still find its partner.
    """
    group = uuid.uuid4()
    shared = _shared_leg_fields(result)
    departure = result['departure']
    flight.airline = result['airline']
    flight.trip_type = Flight.TripType.ROUND_TRIP
    flight.trip_role = TripRole.OUTBOUND
    flight.round_trip_group = group
    for key, value in departure.items():
        setattr(flight, key, value)
    for key, value in shared.items():
        setattr(flight, key, value)
    flight.save()

    leg = result['return_leg']
    back = Flight(
        airline=result['airline'],
        trip_type=Flight.TripType.ONE_WAY,
        trip_role=TripRole.RETURN,
        round_trip_group=group,
        paired_flight=flight,
        **leg, **shared,
    )
    back.full_clean(exclude=['paired_flight'], validate_unique=False)
    back.save()
    flight.paired_flight = back
    flight.save(update_fields=['paired_flight'])
    return back


def _apply_aircraft_status(flight, previous_aircraft_id):
    """Keep the ASSIGNED/AVAILABLE flag in step with the flights that use it.

    An airframe is only released back to AVAILABLE when no other scheduled or
    delayed flight is still pointing at it, otherwise reassigning a leg would
    free an aircraft that is still in the air.
    """
    if previous_aircraft_id and previous_aircraft_id != flight.aircraft_id:
        old = Aircraft.objects.filter(pk=previous_aircraft_id).first()
        if old is not None and not old.flights.exclude(
                pk=flight.pk).filter(
                status__in=(Flight.Status.SCHEDULED, Flight.Status.DELAYED)).exists():
            old.status = Aircraft.Status.AVAILABLE
            old.save(update_fields=['status'])
    if flight.aircraft_id:
        flight.aircraft.status = (
            Aircraft.Status.ASSIGNED
            if flight.status in (Flight.Status.SCHEDULED, Flight.Status.DELAYED)
            else Aircraft.Status.AVAILABLE)
        flight.aircraft.save(update_fields=['status'])


def _is_connecting_post(request):
    """Whether a submitted flight form is asking for a connecting itinerary.

    Read from the form rather than inferred, so the manager's choice of
    Direct / Connecting is the thing that decides which branch runs.
    """
    value = (request.POST.get('flight_type') or '').strip().upper()
    return value == FlightItinerary.FlightType.CONNECTING


def _add_itinerary(request, airline, airline_fixed=False):
    """Create a connecting itinerary from the Add Flight form.

    Everything is validated by :func:`_resolve_itinerary_schedule` before a row
    is written, and the whole save runs in one transaction so a rejected leg
    cannot leave half a journey behind.
    """
    posted_legs = None
    if request.method == 'POST':
        result, errors = _resolve_itinerary_schedule(request, airline=airline)
        if errors:
            for error in errors:
                messages.error(request, error)
            posted_legs = result['legs']
            airline = result['airline'] or airline
        else:
            with transaction.atomic():
                itinerary, legs = _save_itinerary(result)
            route = itinerary.route_label
            log_activity(request.user, "Added flight itinerary",
                         f"{itinerary.itinerary_reference} - {route} "
                         f"({itinerary.segment_count} segments, "
                         f"{itinerary.stops} stop"
                         f"{'s' if itinerary.stops != 1 else ''})")
            messages.success(
                request,
                f"Itinerary {itinerary.itinerary_reference} added: {route} "
                f"— {itinerary.stops_label}, {itinerary.total_duration_label} "
                f"total.")
            return redirect('airlines:itinerary_detail', itinerary.pk)

    context = _flight_form_context(airline=airline, airline_fixed=airline_fixed)
    context.update(_itinerary_form_context(airline=airline, legs=posted_legs))
    context['flight_type'] = FlightItinerary.FlightType.CONNECTING
    return render(request, 'airlines/flight_form.html', context)


def _update_itinerary(request, itinerary):
    """Edit a connecting journey, adding, reordering or removing legs.

    Each leg's row id travels with the form, so editing a journey reuses its
    existing ``Flight`` rows rather than deleting and recreating them: a booked
    leg keeps its seat bookings.  Legs whose ids the manager removed are deleted
    by :func:`_save_itinerary`.
    """
    if request.method == 'POST':
        result, errors = _resolve_itinerary_schedule(
            request, airline=itinerary.airline, itinerary=itinerary)
        if errors:
            for error in errors:
                messages.error(request, error)
            context = _flight_form_context(
                airline=itinerary.airline, airline_fixed=True)
            context.update(_itinerary_form_context(
                airline=itinerary.airline, itinerary=itinerary,
                legs=result['legs']))
            context['flight_type'] = FlightItinerary.FlightType.CONNECTING
            context['itinerary'] = itinerary
            return render(request, 'airlines/flight_form.html', context)
        with transaction.atomic():
            itinerary, legs = _save_itinerary(result, itinerary=itinerary)
        log_activity(request.user, "Updated flight itinerary",
                     f"{itinerary.itinerary_reference} - {itinerary.route_label} "
                     f"({itinerary.segment_count} segments)")
        messages.success(
            request,
            f"Itinerary {itinerary.itinerary_reference} updated: "
            f"{itinerary.route_label} — {itinerary.stops_label}.")
        return redirect('airlines:itinerary_detail', itinerary.pk)

    context = _flight_form_context(
        airline=itinerary.airline, airline_fixed=True)
    context.update(_itinerary_form_context(airline=itinerary.airline,
                                          itinerary=itinerary))
    context['flight_type'] = FlightItinerary.FlightType.CONNECTING
    return render(request, 'airlines/flight_form.html', context)


@manager_required
def update_itinerary(request, itinerary_id):
    """Edit a whole connecting itinerary, reachable from any of its legs."""
    itinerary = get_object_or_404(
        FlightItinerary.objects.select_related('airline'), pk=itinerary_id)
    return _update_itinerary(request, itinerary)


@manager_required
def add_flight(request, airline_id=None):
    """Create a flight schedule entry.

    ``airline_id`` is optional: without it the manager picks the airline in the
    form, so a schedule can be created without navigating through airline and
    aircraft records first.  Either way the aircraft list is that airline's own
    fleet, and the seat map follows from whatever aircraft is chosen.

    A Round Trip saves the outbound leg plus its return leg as two linked
    flights, so each segment can be flown — and sold — with its own aircraft.

    A Connecting flight saves one itinerary plus a ``Flight`` row per leg, so the
    journey is searched, shown and ticketed as a single thing while each leg
    keeps its own aircraft, cabin, seat map and fare.
    """
    airline = get_object_or_404(Airline, pk=airline_id) if airline_id is not None else None
    airline_fixed = airline_id is not None
    if airline is None and request.method == 'GET':
        # The aircraft list is airline-scoped, so the standalone form pre-selects
        # the airline from the query string and narrows the fleet to match.
        selected = _query_pk(request, 'airline')
        airline = Airline.objects.filter(
            pk=selected, status=Airline.Status.ACTIVE).first() if selected else None

    # A connecting journey is a different form, so it is branched on up front and
    # gets its own view rather than being threaded through the direct one.
    if _is_connecting_post(request) or _query_str(request, 'flight_type') == 'CONNECTING':
        return _add_itinerary(request, airline, airline_fixed)

    aircraft_type = _query_pk(request, 'aircraft_type')
    return_aircraft_type = _query_pk(request, 'return_aircraft_type')
    trip_type = _query_str(request, 'trip_type') or Flight.TripType.ONE_WAY
    # A rejected POST re-renders with what the manager actually chose, so the
    # return section stays open and the typed values are not silently lost.
    posted_trip_type = None
    if request.method == 'POST':
        result, errors = _resolve_flight_schedule(request, airline=airline)
        if errors:
            for error in errors:
                messages.error(request, error)
            posted_trip_type = result['trip_type']
            airline = result['airline'] or airline
            departure = result['departure']
            aircraft_type = (departure['aircraft'].aircraft_type_id
                             if departure.get('aircraft') else aircraft_type)
            return_leg = result.get('return_leg') or {}
            return_aircraft_type = (return_leg['aircraft'].aircraft_type_id
                                    if return_leg.get('aircraft') else return_aircraft_type)
        else:
            with transaction.atomic():
                flight = Flight(airline=result['airline'])
                if result['trip_type'] == Flight.TripType.ROUND_TRIP:
                    back = _save_round_trip(request, flight, result)
                else:
                    for key, value in result['departure'].items():
                        setattr(flight, key, value)
                    for key, value in _shared_leg_fields(result).items():
                        setattr(flight, key, value)
                    flight.trip_type = Flight.TripType.ONE_WAY
                    flight.trip_role = TripRole.OUTBOUND
                    flight.save()
                    back = None
                _apply_aircraft_status(flight, None)
                if back is not None:
                    _apply_aircraft_status(back, None)
            leg_note = (f" Return leg {back.flight_number} scheduled on "
                        f"{back.departure_time.date():%b %d, %Y}." if back else "")
            log_activity(request.user, "Added flight",
                         f"{flight.flight_number} - {flight.origin} to {flight.destination}")
            messages.success(request, f"Flight {flight.flight_number} added.{leg_note}")
            return redirect('airlines:flight_detail', flight.slug)
    return render(request, 'airlines/flight_form.html',
                  _flight_form_context(airline=airline, airline_fixed=airline_fixed,
                                       aircraft_type=aircraft_type,
                                       return_aircraft_type=return_aircraft_type,
                                       trip_type=posted_trip_type or trip_type))


@manager_required
def update_flight(request, flight_id):
    """Update a schedule, treating a Round Trip as one editable trip.

    Opening either leg lands on the same form: the outbound leg is what gets
    edited, and its return leg is edited alongside it so the two stay a matched
    pair.  Downgrading a Round Trip to a One Way keeps the return flight as a
    standalone schedule instead of deleting it — an operator who already
    advertised that leg should not silently lose it.

    A leg of a connecting journey is edited as the whole journey, so segments
    cannot be reordered or removed one at a time out of context.
    """
    flight = get_object_or_404(
        Flight.objects.select_related('airline', 'aircraft__aircraft_type__manufacturer',
                                      'aircraft__seat_layout__aircraft_type__manufacturer',
                                      'paired_flight__aircraft__seat_layout'),
        pk=flight_id)
    # Editing the return leg edits the trip, so redirect to its outbound partner.
    if flight.is_return_leg:
        return redirect('airlines:update_flight', flight.partner_flight.pk)
    # Editing any leg of a connecting journey edits the journey.
    if flight.itinerary_id:
        return redirect('airlines:update_itinerary', flight.itinerary_id)

    aircraft_type = _query_pk(request, 'aircraft_type')
    return_aircraft_type = _query_pk(request, 'return_aircraft_type')
    return_leg = flight.return_flight
    if request.method == 'POST':
        result, errors = _resolve_flight_schedule(request, flight=flight,
                                                  airline=flight.airline)
        if errors:
            for error in errors:
                messages.error(request, error)
            departure = result['departure']
            aircraft_type = (departure['aircraft'].aircraft_type_id
                             if departure.get('aircraft') else aircraft_type)
            back = result.get('return_leg') or {}
            return_aircraft_type = (back['aircraft'].aircraft_type_id
                                    if back.get('aircraft') else return_aircraft_type)
        else:
            old_aircraft_id = flight.aircraft_id
            old_back_aircraft_id = return_leg.aircraft_id if return_leg else None
            with transaction.atomic():
                if result['trip_type'] == Flight.TripType.ROUND_TRIP:
                    group = flight.round_trip_group or uuid.uuid4()
                    flight.round_trip_group = group
                    flight.trip_type = Flight.TripType.ROUND_TRIP
                    flight.trip_role = TripRole.OUTBOUND
                    for key, value in result['departure'].items():
                        setattr(flight, key, value)
                    for key, value in _shared_leg_fields(result).items():
                        setattr(flight, key, value)
                    flight.save()
                    leg = result['return_leg']
                    if return_leg is None:
                        return_leg = Flight(
                            airline=flight.airline, trip_role=TripRole.RETURN,
                            round_trip_group=group, paired_flight=flight,
                            **leg, **_shared_leg_fields(result))
                        return_leg.save()
                    else:
                        return_leg.round_trip_group = group
                        for key, value in leg.items():
                            setattr(return_leg, key, value)
                        for key, value in _shared_leg_fields(result).items():
                            setattr(return_leg, key, value)
                        return_leg.save()
                    flight.paired_flight = return_leg
                    flight.save(update_fields=['paired_flight'])
                    return_leg.paired_flight = flight
                    return_leg.save(update_fields=['paired_flight'])
                else:
                    # Downgraded to a one-way: detach the return leg but keep it.
                    # The detached leg keeps its own aircraft, so no airframe is
                    # released here — it is still flying that leg.
                    if return_leg is not None:
                        return_leg.paired_flight = None
                        return_leg.round_trip_group = None
                        return_leg.trip_role = TripRole.OUTBOUND
                        return_leg.trip_type = Flight.TripType.ONE_WAY
                        return_leg.save(update_fields=[
                            'paired_flight', 'round_trip_group',
                            'trip_role', 'trip_type'])
                        return_leg = None
                    flight.trip_type = Flight.TripType.ONE_WAY
                    flight.trip_role = TripRole.OUTBOUND
                    flight.round_trip_group = None
                    flight.paired_flight = None
                    for key, value in result['departure'].items():
                        setattr(flight, key, value)
                    for key, value in _shared_leg_fields(result).items():
                        setattr(flight, key, value)
                    flight.save()
                _apply_aircraft_status(flight, old_aircraft_id)
            if return_leg is not None:
                _apply_aircraft_status(return_leg, old_back_aircraft_id)
            log_activity(request.user, "Updated flight",
                         f"{flight.flight_number} - {flight.origin} to {flight.destination}")
            messages.success(request, "Flight updated.")
            return redirect('airlines:flight_detail', flight.slug)
    return render(request, 'airlines/flight_form.html',
                  _flight_form_context(flight=flight, aircraft_type=aircraft_type,
                                       return_aircraft_type=return_aircraft_type))


@xframe_options_sameorigin
@login_required
@student_booking_required
def book_flight(request, flight_id):
    flight = get_object_or_404(
        Flight.objects.select_related(
            'airline', 'aircraft',
            'aircraft__aircraft_type__manufacturer',
            'aircraft__seat_layout__aircraft_type__manufacturer',
            'airline__default_aircraft_type__manufacturer',
        ), pk=flight_id)
    # A round trip is booked as one journey, so opening the return leg lands on
    # the outbound leg — that keeps the booking stored departure-first and stops
    # a passenger from buying a return that has no outward flight behind it.
    if flight.is_return_leg and flight.partner_flight is not None:
        return redirect('airlines:book', flight.partner_flight.pk)
    if not resource_is_bookable(flight) or flight.status not in (Flight.Status.SCHEDULED, Flight.Status.DELAYED):
        messages.error(request, "This flight is not currently bookable.")
        return redirect('airlines:list')

    # The return leg is its own flight, so it has its own cabin, capacity and
    # seat map — booking the outbound seat does not reserve a seat inbound.
    return_flight = flight.return_flight
    if return_flight is not None:
        if (not resource_is_bookable(return_flight)
                or return_flight.status not in (Flight.Status.SCHEDULED, Flight.Status.DELAYED)):
            messages.error(request, "The return leg of this trip is not currently bookable.")
            return redirect('airlines:list')

    booked = _booked_seats(flight)
    remaining = max(0, flight.capacity - booked)
    if remaining <= 0:
        messages.error(request, "This flight is fully booked (no seats available).")
        return redirect('airlines:list')
    seat_map = _seat_map(flight)

    return_remaining = None
    return_seat_map = None
    if return_flight is not None:
        return_remaining = max(
            0, return_flight.capacity - _booked_seats(return_flight, TripSegment.RETURN))
        if return_remaining <= 0:
            messages.error(request, "The return leg of this trip is fully booked.")
            return redirect('airlines:list')
        return_seat_map = _seat_map(return_flight, TripSegment.RETURN)

    if return_flight is not None:
        # The operator already scheduled both legs, so the trip type and the
        # return date are facts of the schedule rather than a passenger choice.
        trip_type = Booking.TripType.ROUND_TRIP
        return_date = return_flight.departure_time.date().isoformat()
    else:
        trip_type = (request.POST.get('trip_type') or request.GET.get('trip_type')
                     or flight.trip_type or Booking.TripType.ONE_WAY)
        if trip_type not in (Booking.TripType.ONE_WAY, Booking.TripType.ROUND_TRIP):
            trip_type = Booking.TripType.ONE_WAY
        return_date = (request.POST.get('return_date') or request.GET.get('return_date') or '').strip()
    departure_date = (request.POST.get('departure_date') or request.GET.get('departure_date') or '').strip()
    return_date_obj = _parse_date(return_date)
    try:
        passengers = int(
            request.POST.get('passengers')
            or request.GET.get('passengers')
            or 1
        )
    except (TypeError, ValueError):
        passengers = 1
    selected_fare_class = (
        request.POST.get('fare_class')
        or request.GET.get('fare_class')
        or Flight.FareClass.ECONOMY
    )

    def _trip_context():
        return {
            'trip_type': trip_type,
            'return_date': return_date,
            'departure_date': departure_date,
            'passengers': passengers,
            'fare_class': selected_fare_class,
            'return_flight': return_flight,
            'return_seat_map': return_seat_map,
            'return_remaining': return_remaining,
        }

    def _rerender(**extra):
        return render(request, 'airlines/book.html', {
            'flight': flight,
            'remaining': remaining,
            'seat_map': seat_map,
            'services': flight.airline.services.filter(
                status=Service.ServiceStatus.ACTIVE),
            **_trip_context(),
            **extra,
        })

    if request.method == 'POST':
        if trip_type == Booking.TripType.ROUND_TRIP and not return_date_obj:
            messages.error(request, 'Return date is required for a Round-Trip booking.')
            return _rerender()
        if return_flight is None and return_date_obj and return_date_obj <= flight.departure_time.date():
            messages.error(request, 'Return date must be after the departure date.')
            return _rerender()
        try:
            passengers = int(request.POST.get('passengers') or 1)
        except (TypeError, ValueError):
            passengers = 1
        if passengers < 1:
            messages.error(request, 'At least 1 passenger is required.')
            return _rerender()
        if passengers > remaining:
            messages.error(request, f"Only {remaining} seat(s) remain on this flight.")
            return _rerender()
        if return_flight is not None and passengers > return_remaining:
            messages.error(
                request,
                f"Only {return_remaining} seat(s) remain on the return leg.")
            return _rerender()

        passenger_names = request.POST.getlist('passenger_names')
        primary_seat = (request.POST.get('primary_seat') or '').strip().upper()
        seat_numbers = request.POST.getlist('seat_numbers')
        primary_return_seat = (request.POST.get('primary_return_seat') or '').strip().upper()
        return_seat_numbers = request.POST.getlist('return_seat_numbers')
        travel_document_types = request.POST.getlist('travel_document_types')
        travel_document_numbers = request.POST.getlist('travel_document_numbers')
        fare_class = (request.POST.get('fare_class') or Flight.FareClass.ECONOMY).strip()
        # Seat 1 (the primary guest) is submitted separately; every other
        # seat comes from the dynamic passenger rows that only render for
        # 2+ seats.
        all_seats = ([primary_seat] + list(seat_numbers))[:passengers]
        all_return_seats = (
            [primary_return_seat] + list(return_seat_numbers))[:passengers] \
            if return_flight is not None else []

        # Real-flight style group booking: one booking contains all passengers.
        # Validate the requested seats before creating anything so a duplicate
        # seat cannot produce a server error or a partial booking.
        selected_seats = [s.strip().upper() for s in all_seats if s.strip()]
        # A seat number the layout does not have is a forged or stale form, so
        # it is rejected before any booking row is written.
        if selected_seats and not _seats_exist(flight, selected_seats):
            messages.error(request, 'One or more selected seats are not on this aircraft.')
            return _rerender()

        if len(selected_seats) != len(set(selected_seats)):
            messages.error(request, 'Each passenger must have a different seat number.')
            return _rerender()
        if selected_seats:
            occupied = set(
                Booking.BookingSeat.objects.filter(
                    booking__flight=flight,
                    segment=TripSegment.DEPARTURE,
                    seat_number__in=selected_seats,
                ).exclude(booking__status__in=_cutoff_statuses())
                .values_list('seat_number', flat=True)
            )
            if occupied:
                messages.error(request, f"Seat(s) already assigned on this flight: {', '.join(sorted(occupied))}.")
                return _rerender()

        # Every passenger on one booking shares the cabin they are seated in, so
        # a fare class the aircraft does not fly cannot be charged for.
        if fare_class not in flight.cabin_classes:
            messages.error(request, 'This flight does not offer that cabin.')
            return _rerender()

        # ---- Return leg -------------------------------------------------
        # A round trip is validated on its own leg: the seats are checked
        # against the return aircraft's layout, not the departure one, and the
        # same seat number is free to be reused inbound.
        if return_flight is not None:
            selected_return_seats = [s.strip().upper() for s in all_return_seats if s.strip()]
            if len(selected_return_seats) != passengers:
                messages.error(
                    request,
                    f"Choose a return seat for each of the {passengers} passenger(s).")
                return _rerender()
            if not _seats_exist(return_flight, selected_return_seats):
                messages.error(
                    request, 'One or more return seats are not on the return aircraft.')
                return _rerender()
            if len(selected_return_seats) != len(set(selected_return_seats)):
                messages.error(request, 'Each passenger must have a different return seat.')
                return _rerender()
            occupied_return = set(
                Booking.BookingSeat.objects.filter(
                    booking__return_flight=return_flight,
                    segment=TripSegment.RETURN,
                    seat_number__in=selected_return_seats,
                ).exclude(booking__status__in=_cutoff_statuses())
                .values_list('seat_number', flat=True)
            )
            if occupied_return:
                messages.error(
                    request,
                    f"Return seat(s) already assigned: {', '.join(sorted(occupied_return))}.")
                return _rerender()
            if fare_class not in return_flight.cabin_classes:
                messages.error(
                    request,
                    "The return flight does not offer that cabin — pick a cabin "
                    "both flights operate.")
                return _rerender()
        else:
            selected_return_seats = []

        # Passenger 1 is always the primary guest (account owner); the form
        # only submits names for the additional seats, so the lead name is
        # fixed to the account.
        lead_name = request.user.get_full_name() or request.user.username or 'Passenger'
        names = [lead_name]
        for n in passenger_names[:passengers - 1]:
            names.append(n)
        while len(names) < passengers:
            names.append('')

        extras = flight.airline.services.filter(
            pk__in=request.POST.getlist('services'), status=Service.ServiceStatus.ACTIVE)
        baggage_kg = float(request.POST.get('baggage') or 0)
        baggage_charge = baggage_kg * float(flight.baggage_rate or 0)
        fare = flight.fare_for(fare_class)
        return_fare = (return_flight.fare_for(fare_class)
                       if return_flight is not None else None)
        items = compute_airline_bill(flight, passengers, fare, services=extras,
                                     baggage_charge=baggage_charge, baggage_kg=baggage_kg,
                                     return_flight=return_flight, return_fare=return_fare)
        leg_total = float(fare) * passengers
        if return_flight is not None:
            leg_total += float(return_fare) * passengers
        total = leg_total + sum(float(getattr(s, 'rate', 0)) for s in extras) + baggage_charge

        booking = Booking.objects.create(
            flight=flight,
            return_flight=return_flight,
            passenger=request.user,
            status=Booking.Status.PENDING,
            trip_type=trip_type,
            return_date=return_date_obj if trip_type == Booking.TripType.ROUND_TRIP else None,
            extra_baggage=baggage_charge,
            extra_baggage_kg=baggage_kg,
            travel_document_type=request.POST.get('travel_document_type', ''),
            travel_document_number=request.POST.get('travel_document_number', ''),
            payer_name=request.POST.get('payer_name', request.user.get_full_name() or request.user.username),
            payer_contact=request.POST.get('payer_contact', request.user.contact_number or ''),
            special_requests=request.POST.get('special_requests', ''),
        )
        # The primary guest's travel document is the booking-level one; each
        # additional passenger submits its own from the dynamic rows.
        booking_doc_type = request.POST.get('travel_document_type', '')
        booking_doc_number = request.POST.get('travel_document_number', '')
        for i in range(passengers):
            if i == 0:
                seat_doc_type = booking_doc_type
                seat_doc_number = booking_doc_number
            else:
                seat_doc_type = travel_document_types[i - 1] if i - 1 < len(travel_document_types) else ''
                seat_doc_number = travel_document_numbers[i - 1] if i - 1 < len(travel_document_numbers) else ''
            Booking.BookingSeat.objects.create(
                booking=booking,
                passenger_name=names[i] if i < len(names) else '',
                seat_number=all_seats[i] if i < len(all_seats) else '',
                segment=TripSegment.DEPARTURE,
                fare_class=fare_class,
                travel_document_type=seat_doc_type,
                travel_document_number=seat_doc_number,
            )
            # The return leg is a second seat for the same traveler, on the
            # return aircraft — 12A out, 14C back.
            if return_flight is not None and i < len(all_return_seats):
                Booking.BookingSeat.objects.create(
                    booking=booking,
                    passenger_name=names[i] if i < len(names) else '',
                    seat_number=all_return_seats[i],
                    segment=TripSegment.RETURN,
                    fare_class=fare_class,
                    travel_document_type=seat_doc_type,
                    travel_document_number=seat_doc_number,
                )
        booking.services.set(extras)
        bill = create_bill(service='flight', customer=request.user, items=items, booking=booking)
        booking.total_bill = total
        booking.save(update_fields=['total_bill'])

        from simulation.completion import complete_guest_booking
        from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

        complete_guest_booking(
            request.user,
            task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
            booking_reference=booking.booking_reference,
        )

        if request.POST.get('book_and_add') == '1':
            try:
                add_establishment_booking(request, booking)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('airlines:booking_detail', booking.id)
            messages.success(request, f'Added to this establishment booking: {booking.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':


            add_booking_to_cart(request, booking)


            messages.success(request, f"Added to your Trip Cart: {booking.booking_reference}")


            return redirect('transactions:cart')



        passenger_count = passengers
        passenger_summary = f"{passenger_count} passenger" if passenger_count == 1 else f"{passenger_count} passengers"
        if return_flight is not None:
            route_summary = (
                f"{flight.flight_number} {flight.origin} → {flight.destination} ⇄ "
                f"{return_flight.flight_number} {return_flight.origin} → {return_flight.destination}")
        else:
            route_summary = f"{flight.flight_number} {flight.origin} → {flight.destination}"
        order = create_single_booking_order(
            request=request,
            booking=booking,
            service='flight',
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=(f"{route_summary} · {passenger_summary}"),
            items=items,
            pay_later=request.POST.get('pay_later') == 'on',
        )
        booking.refresh_from_db()
        if request.POST.get('pay_later') == 'on':
            messages.success(request, f"Flight order created: {order.order_reference} · {passenger_summary} under ONE transaction (pending payment).")
        else:
            messages.success(request, f"Flight booked successfully: {order.order_reference} · {passenger_summary} under ONE transaction.")
        return redirect('transactions:order_detail', order.id)

    return _rerender()


@login_required
@student_booking_required
def book_itinerary(request, itinerary_id):
    """Book a whole connecting journey as one reservation.

    The passenger picks a seat on *every* leg, because each leg is a different
    airframe with a different cabin: 12A on the MNL-SIN aircraft is not the seat
    they will sit in on SIN-DXB.  All legs are written to one ``Booking`` with
    ``Booking.itinerary`` set, so the ticket, the booking detail page and the
    billing all show the journey as the single thing it is.

    Capacity is checked on the tightest leg rather than summed, since one
    passenger occupies one seat on every leg.
    """
    itinerary = get_object_or_404(
        FlightItinerary.objects.select_related('airline'), pk=itinerary_id)
    legs = list(itinerary.ordered_legs)
    if not resource_is_bookable(itinerary) or not itinerary.is_bookable():
        messages.error(request, "This itinerary is not currently bookable.")
        return redirect('airlines:itinerary_public_detail', itinerary.pk)

    segment_rows = []
    for index, leg in enumerate(legs):
        leg_booked = _booked_seats(leg)
        segment_rows.append({
            'index': index,
            'flight': leg,
            'seat_map': _seat_map(leg),
            'remaining': max(0, leg.capacity - leg_booked),
        })
    if not segment_rows:
        messages.error(request, "This itinerary has no flight segments to book.")
        return redirect('airlines:itinerary_public_detail', itinerary.pk)

    # The tightest leg sets the party size: three free seats on the last hop
    # cannot carry four passengers through the first.
    remaining = min(row['remaining'] for row in segment_rows)
    if remaining <= 0:
        full = next(row for row in segment_rows if row['remaining'] <= 0)
        messages.error(
            request,
            f"Segment {full['flight'].segment_order} "
            f"({full['flight'].flight_number}) is fully booked.")
        return redirect('airlines:itinerary_public_detail', itinerary.pk)

    services = itinerary.airline.services.filter(
        status=Service.ServiceStatus.ACTIVE)
    timing = itinerary.timing
    try:
        passengers = int(
            request.POST.get('passengers')
            or request.GET.get('passengers')
            or 1
        )
    except (TypeError, ValueError):
        passengers = 1
    available_fare_classes = [
        fare_class for fare_class in legs[0].cabin_classes
        if all(fare_class in leg.cabin_classes for leg in legs[1:])
    ]
    selected_fare_class = (
        request.POST.get('fare_class')
        or request.GET.get('fare_class')
        or Flight.FareClass.ECONOMY
    )

    def _rerender(**extra):
        return render(request, 'airlines/book_itinerary.html', {
            'itinerary': itinerary,
            'timing': timing,
            'legs': legs,
            'segment_rows': segment_rows,
            'remaining': remaining,
            'services': services,
            'trip_type': itinerary.trip_type,
            'passengers': passengers,
            'fare_class': selected_fare_class,
            'available_fare_classes': available_fare_classes,
            **extra,
        })

    if request.method == 'POST':
        # ---- Seats, validated per leg ------------------------------------
        # The seat lists themselves fix the party size: each leg's field carries
        # the whole party, one entry per passenger. Reading the count off the
        # seats rather than trusting a posted number is what stops a forged
        # "passengers=1" from selling a seat list nobody paid for.
        seats_by_leg = {}
        for row in segment_rows:
            leg = row['flight']
            order = leg.segment_order
            chosen = _posted_seat_list(request, row['index'])
            if not chosen:
                messages.error(
                    request,
                    f"Choose a seat for every passenger on segment {order} "
                    f"({leg.flight_number}).")
                return _rerender()
            if len(chosen) != len(set(chosen)):
                messages.error(
                    request,
                    f"Each passenger must have a different seat on segment "
                    f"{order} ({leg.flight_number}).")
                return _rerender()
            if not _seats_exist(leg, chosen):
                messages.error(
                    request,
                    f"One or more selected seats are not on the aircraft "
                    f"operating segment {order} ({leg.flight_number}).")
                return _rerender()
            occupied = set(
                Booking.BookingSeat.objects.filter(
                    flight=leg,
                    seat_number__in=chosen,
                ).exclude(booking__status__in=_cutoff_statuses())
                .values_list('seat_number', flat=True))
            if occupied:
                messages.error(
                    request,
                    f"Seat(s) already assigned on segment {order} "
                    f"({leg.flight_number}): {', '.join(sorted(occupied))}.")
                return _rerender()
            seats_by_leg[leg.pk] = chosen

        # One passenger occupies one seat on every leg, so a leg that carries a
        # different number of seats from the rest is a tampered or half-filled
        # form: it would leave someone unbumped at a connection.
        party_sizes = {len(seats) for seats in seats_by_leg.values()}
        if len(party_sizes) != 1:
            messages.error(
                request,
                "Every segment of this itinerary needs a seat for each "
                "passenger, so all segments must have the same number of seats "
                "chosen.")
            return _rerender()
        passengers = party_sizes.pop()

        claimed = request.POST.get('passengers')
        if claimed not in (None, ''):
            try:
                claimed = int(claimed)
            except (TypeError, ValueError):
                claimed = 0
            if claimed != passengers:
                messages.error(
                    request,
                    f"You chose {passengers} seat(s) per segment but asked for "
                    f"{claimed} passenger(s). Choose one seat per passenger on "
                    "every segment.")
                return _rerender()

        if passengers > remaining:
            messages.error(
                request,
                f"Only {remaining} seat(s) remain on this itinerary's tightest leg.")
            return _rerender()

        # One cabin for the whole journey: a fare class the tightest leg's
        # aircraft does not fly cannot be charged for.
        fare_class = (request.POST.get('fare_class')
                      or Flight.FareClass.ECONOMY).strip()
        for leg in legs:
            if fare_class not in leg.cabin_classes:
                messages.error(
                    request,
                    f"Segment {leg.segment_order} ({leg.flight_number}) does not "
                    f"offer {fare_class} — pick a cabin every segment operates.")
                return _rerender()

        lead_name = request.user.get_full_name() or request.user.username or 'Passenger'
        names = [lead_name]
        for name in request.POST.getlist('passenger_names')[:passengers - 1]:
            names.append(name)
        while len(names) < passengers:
            names.append('')

        extras = itinerary.airline.services.filter(
            pk__in=request.POST.getlist('services'),
            status=Service.ServiceStatus.ACTIVE)
        try:
            baggage_kg = float(request.POST.get('baggage') or 0)
        except (TypeError, ValueError):
            baggage_kg = 0
        baggage_kg = max(0, baggage_kg)
        # The rate is the itinerary's, falling back to the first leg's, so the
        # quoted price matches what the journey card showed.
        baggage_rate = itinerary.baggage_rate or legs[0].baggage_rate or 0
        baggage_charge = baggage_kg * float(baggage_rate or 0)

        # Each leg keeps its own fare; the chain sums to the journey price.
        leg_fares = [(leg, leg.fare_for(fare_class)) for leg in legs]
        total_leg_fare = sum(float(fare) for _, fare in leg_fares) * passengers
        total = (total_leg_fare
                 + sum(float(getattr(s, 'rate', 0)) for s in extras)
                 + baggage_charge
                 + float(itinerary.service_fee or 0) * passengers)
        items = compute_airline_bill(
            legs[0], passengers, leg_fares[0][1], services=extras,
            baggage_charge=baggage_charge, baggage_kg=baggage_kg,
            itinerary_legs=leg_fares)

        travel_document_type = request.POST.get('travel_document_type', '')
        travel_document_number = request.POST.get('travel_document_number', '')
        extra_doc_types = request.POST.getlist('travel_document_types')
        extra_doc_numbers = request.POST.getlist('travel_document_numbers')

        with transaction.atomic():
            booking = Booking.objects.create(
                itinerary=itinerary,
                flight=legs[0],
                passenger=request.user,
                status=Booking.Status.PENDING,
                trip_type=Booking.TripType.ONE_WAY,
                extra_baggage=baggage_charge,
                extra_baggage_kg=baggage_kg,
                travel_document_type=travel_document_type,
                travel_document_number=travel_document_number,
                payer_name=request.POST.get(
                    'payer_name',
                    request.user.get_full_name() or request.user.username),
                payer_contact=request.POST.get(
                    'payer_contact', request.user.contact_number or ''),
                special_requests=request.POST.get('special_requests', ''),
            )
            for leg in legs:
                for i in range(passengers):
                    if i == 0:
                        seat_doc_type = travel_document_type
                        seat_doc_number = travel_document_number
                    else:
                        seat_doc_type = (extra_doc_types[i - 1]
                                         if i - 1 < len(extra_doc_types) else '')
                        seat_doc_number = (extra_doc_numbers[i - 1]
                                           if i - 1 < len(extra_doc_numbers) else '')
                    Booking.BookingSeat.objects.create(
                        booking=booking,
                        flight=leg,
                        segment_order=leg.segment_order,
                        passenger_name=names[i] if i < len(names) else '',
                        seat_number=seats_by_leg[leg.pk][i],
                        segment=TripSegment.DEPARTURE,
                        fare_class=fare_class,
                        travel_document_type=seat_doc_type,
                        travel_document_number=seat_doc_number,
                    )
            booking.services.set(extras)
            bill = create_bill(service='flight', customer=request.user, items=items,
                               booking=booking)
            booking.total_bill = total
            booking.save(update_fields=['total_bill'])

        from simulation.completion import complete_guest_booking
        from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

        complete_guest_booking(
            request.user,
            task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
            booking_reference=booking.booking_reference,
        )

        if request.POST.get('book_and_add') == '1':
            try:
                add_establishment_booking(request, booking)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('airlines:booking_detail', booking.id)
            messages.success(
                request,
                f'Added to this establishment booking: {booking.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':
            add_booking_to_cart(request, booking)
            messages.success(
                request, f"Added to your Trip Cart: {booking.booking_reference}")
            return redirect('transactions:cart')

        passenger_summary = (f"{passengers} passenger" if passengers == 1
                             else f"{passengers} passengers")
        route_summary = (f"{itinerary.itinerary_reference} {itinerary.route_label} "
                         f"({itinerary.stops_label})")
        order = create_single_booking_order(
            request=request,
            booking=booking,
            service='flight',
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=f"{route_summary} · {passenger_summary}",
            items=items,
            pay_later=request.POST.get('pay_later') == 'on',
        )
        booking.refresh_from_db()
        if request.POST.get('pay_later') == 'on':
            messages.success(
                request,
                f"Flight order created: {order.order_reference} · {route_summary} "
                f"· {passenger_summary} under ONE transaction (pending payment).")
        else:
            messages.success(
                request,
                f"Flight booked successfully: {order.order_reference} · "
                f"{route_summary} · {passenger_summary} under ONE transaction.")
        return redirect('transactions:order_detail', order.id)

    return _rerender()


@manager_required
def bookings(request):
    qs = Booking.objects.select_related('passenger', 'flight__airline')
    airline_ids = _assigned_airline_ids_for_management(request)
    if airline_ids is not None:
        qs = qs.filter(flight__airline_id__in=airline_ids)
    q = request.GET.get('q', '')
    status = request.GET.get('status', '')
    trip_type = request.GET.get('trip_type', '')
    flight_id = request.GET.get('flight', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    if q:
        qs = qs.filter(
            Q(booking_reference__icontains=q) |
            Q(passenger__username__icontains=q) |
            Q(passenger__first_name__icontains=q) |
            Q(passenger__last_name__icontains=q) |
            Q(flight__flight_number__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if trip_type:
        qs = qs.filter(trip_type=trip_type)
    if flight_id:
        qs = qs.filter(flight_id=flight_id)
    if date_from:
        from_dt = _parse_dt(date_from)
        if from_dt:
            qs = qs.filter(created_at__date__gte=from_dt.date())
    if date_to:
        to_dt = _parse_dt(date_to)
        if to_dt:
            qs = qs.filter(created_at__date__lte=to_dt.date())
    flights = Flight.objects.all()
    if airline_ids is not None:
        flights = flights.filter(airline_id__in=airline_ids)
    return render(request, 'airlines/bookings.html', {
        'bookings': qs,
        'flights': flights,
        'q': q, 'status': status, 'trip_type': trip_type, 'flight': flight_id,
        'date_from': date_from, 'date_to': date_to,
        'trip_type_choices': Booking.TripType.choices,
    })


def _assigned_airline_ids(user):
    from django.contrib.contenttypes.models import ContentType
    from simulation.models import SimulationRoleAssignment

    airline_type = ContentType.objects.get_for_model(Airline)
    return SimulationRoleAssignment.objects.filter(
        student=user,
        role=SimulationRoleAssignment.Role.AIRLINE_RESERVATION_AGENT,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        establishment__entity_type=airline_type,
    ).values_list('establishment__entity_id', flat=True)


def _reservation_agent_can_access_airline(user, airline):
    from establishments.models import establishment_for_instance

    establishment = establishment_for_instance(airline)
    return bool(
        establishment
        and establishment.entity_id in set(_assigned_airline_ids(user))
    )


@xframe_options_sameorigin
@login_required
def booking_detail(request, booking_id):
    from accounts.roles import (
        AIRLINE_TICKETING_ROLE_KEYS, can_access_module, can_manage_booking,
        effective_role_keys,
    )
    from transactions.models import Bill, Payment

    booking = get_object_or_404(Booking.objects.select_related('passenger', 'flight__airline'), pk=booking_id)
    role_keys = effective_role_keys(request.user)
    can_manage = bool(can_manage_booking(request.user, 'airlines'))
    reservation_agent_restricted = (
        can_manage
        and 'AIRLINE_RESERVATION_AGENT' in role_keys
        and not can_access_module(request.user, 'airlines')
    )
    if reservation_agent_restricted:
        can_manage = _reservation_agent_can_access_airline(
            request.user, booking.flight.airline)
    if booking.passenger_id != request.user.id and not can_manage:
        messages.warning(request, "You cannot view this booking.")
        return redirect('airlines:list')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()
    ticketing_restricted = (
        can_manage
        and bool(role_keys & AIRLINE_TICKETING_ROLE_KEYS)
        and not can_access_module(request.user, 'airlines')
    )

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')
        if reservation_agent_restricted and (
            action not in {'confirm', 'decline'}
            or booking.passenger_id == request.user.id
        ):
            raise PermissionDenied(
                'Airline Reservation Agents may only confirm or decline another passenger’s booking for their assigned airline.')
        if ticketing_restricted and action not in {'modify', 'cancel'}:
            raise PermissionDenied(
                'Airline Ticketing Officers may only process ticket changes and cancellations.')
        remark = request.POST.get('manager_remarks', '').strip()
        if action == 'confirm':
            was_pending = booking.status == Booking.Status.PENDING
            confirm_booking(booking, request.user)
            if remark:
                booking.manager_remarks = remark
                booking.save(update_fields=['manager_remarks'])
            log_activity(booking.passenger, f"Flight {booking.booking_reference} confirmed",
                         f"{booking.flight.flight_number} {booking.flight.origin}-{booking.flight.destination}"
                         + (f" | Remarks: {remark}" if remark else ""))
            if was_pending:
                recipient = booking.passenger.email.strip()
                if not recipient:
                    messages.warning(
                        request,
                        "Booking confirmed, but the passenger has no email address on their account.")
                else:
                    message = (
                        f"Hello {booking.passenger.get_full_name() or booking.passenger.username},\n\n"
                        f"Your flight booking has been confirmed.\n\n"
                        f"Airline: {booking.flight.airline.name}\n"
                        f"Booking reference: {booking.booking_reference}\n"
                        f"Flight: {booking.flight.flight_number}\n"
                        f"Route: {booking.flight.origin} to {booking.flight.destination}\n"
                        f"Departure: {timezone.localtime(booking.flight.departure_time):%B %d, %Y %H:%M}\n\n"
                        "Sign in to ATRUE to view your booking and e-ticket."
                    )
                    try:
                        sent = send_mail(
                            subject=f"Flight booking {booking.booking_reference} confirmed",
                            message=message,
                            from_email=None,
                            recipient_list=[recipient],
                            fail_silently=False,
                        )
                    except (OSError, SMTPException):
                        logger.exception(
                            "Failed to send airline booking confirmation email for booking %s",
                            booking.pk,
                        )
                        messages.error(
                            request,
                            "Booking confirmed, but the confirmation email could not be sent.")
                    else:
                        if sent:
                            messages.success(
                                request,
                                f"Confirmation email sent to {recipient}.")
                        else:
                            messages.error(
                                request,
                                "Booking confirmed, but the email backend did not send the confirmation.")
        elif action == 'decline':
            decline_booking(booking, request.user)
            if remark:
                booking.manager_remarks = remark
                booking.save(update_fields=['manager_remarks'])
            log_activity(booking.passenger, f"Flight {booking.booking_reference} declined",
                         f"{booking.flight.flight_number}"
                         + (f" | Remarks: {remark}" if remark else ""))
        elif action == 'checkin':
            booking.status = Booking.Status.CHECKED_IN
            booking.checked_in_at = timezone.now()
            booking.save(update_fields=['status', 'checked_in_at'])
            log_activity(request.user, "Passenger checked in", booking.booking_reference)
            log_activity(booking.passenger, f"Check-in {booking.booking_reference}", booking.flight.flight_number)
        elif action == 'checkout':
            booking.status = Booking.Status.CHECKED_OUT
            booking.checked_out_at = timezone.now()
            booking.save(update_fields=['status', 'checked_out_at'])
            log_activity(request.user, "Passenger travelled", booking.booking_reference)
            log_activity(booking.passenger, f"Travel completed {booking.booking_reference}",
                         booking.flight.flight_number)
        elif action == 'modify':
            new_count = int(request.POST.get('passengers') or booking.passengers_count)
            current = booking.seat_entries.count()
            flight = booking.flight
            new_trip_type = request.POST.get('trip_type') or booking.trip_type
            if new_trip_type not in (Booking.TripType.ONE_WAY, Booking.TripType.ROUND_TRIP):
                new_trip_type = Booking.TripType.ONE_WAY
            new_return = _parse_date(request.POST.get('return_date'))
            if new_trip_type == Booking.TripType.ROUND_TRIP and not new_return:
                messages.error(request, 'Return date is required for a Round-Trip booking.')
            elif new_return and new_return <= flight.departure_time.date():
                messages.error(request, 'Return date must be after the departure date.')
            elif 0 <= new_count <= flight.capacity:
                if new_count > current:
                    default_name = booking.primary_guest_name or request.user.get_full_name() or ''
                    for _ in range(new_count - current):
                        Booking.BookingSeat.objects.create(booking=booking, passenger_name=default_name)
                elif new_count < current:
                    for seat in booking.seat_entries.all()[new_count:]:
                        seat.delete()
                booking.trip_type = new_trip_type
                booking.return_date = new_return if new_trip_type == Booking.TripType.ROUND_TRIP else None
                booking.special_requests = request.POST.get('special_requests', booking.special_requests)
                booking.travel_document_type = request.POST.get('travel_document_type', booking.travel_document_type)
                booking.travel_document_number = request.POST.get('travel_document_number', booking.travel_document_number)
                booking.payer_name = request.POST.get('payer_name', booking.payer_name)
                booking.payer_contact = request.POST.get('payer_contact', booking.payer_contact)
                booking.status = Booking.Status.MODIFIED
                booking.save()
                fare = booking.seat_entries.first().fare_class or Flight.FareClass.ECONOMY
                items = compute_airline_bill(
                    booking.flight, new_count, booking.flight.fare_for(fare),
                    services=booking.services.all(), baggage_charge=booking.extra_baggage,
                    baggage_kg=booking.extra_baggage_kg)
                if bill:
                    bill.calculate(items)
                    bill.save(update_fields=['items', 'total_amount'])
                booking.total_bill = bill.total_amount if bill else 0
                booking.balance_due = bill.balance_due if bill else 0
                booking.save(update_fields=['total_bill', 'balance_due'])
                log_activity(request.user, "Flight booking modified", booking.booking_reference)
                log_activity(booking.passenger, f"Flight {booking.booking_reference} modified",
                             f"Now {new_count} passenger(s)", )
            else:
                messages.error(request, f"Invalid passenger count (max {flight.capacity}).")
        elif action == 'cancel':
            cancel_booking(booking, request.user)
            log_activity(booking.passenger, f"Flight {booking.booking_reference} cancelled",
                         booking.flight.flight_number)
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.passenger else booking.passenger,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='flight',
                bill=bill,
            )
            booking.refresh_from_db()
            if bill:
                bill.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else booking.amount_paid
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('airlines:booking_detail', booking.id)

    # A connecting booking has one `flight` (the first leg) but several segments,
    # so the page needs the whole chain and the tightest leg's capacity rather
    # than whichever leg happens to be on the row.  The rows are assembled here
    # rather than in the template so the seat chips line up with their leg and
    # the layover sits between the two legs it belongs to.
    itinerary = booking.itinerary
    legs = itinerary.ordered_legs if itinerary is not None else []
    timing = itinerary_timing(legs) if legs else None
    seats_by_segment = {}
    for seat in booking.seat_entries.filter(flight__isnull=False):
        seats_by_segment.setdefault(seat.segment_order, []).append(
            f"{seat.seat_number or '—'} {seat.get_fare_class_display()}")
    layovers = (timing or {}).get('layovers') or []
    itinerary_rows = []
    for index, leg in enumerate(legs):
        itinerary_rows.append({
            'leg': leg,
            'entry': timing['legs'][index] if timing and index < len(timing['legs']) else None,
            'layover': layovers[index] if index < len(layovers) else None,
            'seats': seats_by_segment.get(index + 1, []),
        })
    return render(request, 'airlines/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'ticketing_restricted': ticketing_restricted,
        'reservation_agent_restricted': reservation_agent_restricted,
        'flight_capacity': booking.flight.capacity,
        'itinerary': itinerary,
        'itinerary_legs': legs,
        'itinerary_rows': itinerary_rows,
        'itinerary_timing': timing,
        'itinerary_capacity': min((leg.capacity for leg in legs), default=0),
    })


def _get_ticket_booking(request, booking_id):
    """Load an airline booking the current user is allowed to ticket."""
    from accounts.roles import (
        can_access_module, can_manage_booking, effective_role_keys)

    booking = get_object_or_404(
        Booking.objects.select_related('passenger', 'flight__airline', 'flight__aircraft'),
        pk=booking_id)
    can_manage = can_manage_booking(request.user, 'airlines')
    if (
        can_manage
        and 'AIRLINE_RESERVATION_AGENT' in effective_role_keys(request.user)
        and not can_access_module(request.user, 'airlines')
    ):
        can_manage = _reservation_agent_can_access_airline(
            request.user, booking.flight.airline)
    if booking.passenger_id != request.user.id and not can_manage:
        messages.warning(request, "You cannot view this booking.")
        return None
    return booking


@login_required
def ticket_detail(request, booking_id):
    from .ticket import build_ticket_context

    import base64

    booking = _get_ticket_booking(request, booking_id)
    if booking is None:
        return redirect('airlines:list')

    ctx = build_ticket_context(booking)
    ctx['qr']['data_uri'] = 'data:image/png;base64,' + base64.b64encode(ctx['qr']['png']).decode('ascii')
    return render(request, 'airlines/ticket_itinerary.html', {
        'ticket': ctx,
        'printable': booking.status in ('CONFIRMED', 'CHECKED_IN', 'COMPLETED', 'MODIFIED'),
    })


@login_required
def ticket_pdf(request, booking_id):
    from io import BytesIO

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    from django.http import HttpResponse

    from .ticket import build_ticket_context
    from .ticket_pdf_itinerary import _build as build_pdf_story

    booking = _get_ticket_booking(request, booking_id)
    if booking is None:
        return redirect('airlines:list')

    ctx = build_ticket_context(booking)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=9 * mm, bottomMargin=10 * mm,
        title=f"ATRUE E-Ticket Itinerary {booking.booking_reference}",
        author='ATRUE Travel & Tours (Simulation)',
    )
    story, on_page = build_pdf_story(ctx)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f"attachment; filename={ctx['download_name']}"
    return response
