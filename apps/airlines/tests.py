import re
from datetime import date, time, timedelta
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from airlines.fleet_data import CABIN_SPECS, FLEETS
from airlines.itineraries import airport_timezone, combine_local, parse_clock
from airlines.layouts import build_seat_map, resolve_layout
from airlines.models import (
    Aircraft, AircraftType, Airline, AirlineFleet, AirlinePhoto, Airport,
    Booking, Cabin, Flight, FlightItinerary, Manufacturer, Seat,
    SeatLayout, TripRole, TripSegment,
)
from airlines.views import NO_AIRCRAFT
from atrue_core.slugs import get_object_by_slug_or_404

from locations.models import Country, Province, Region


def _spec_for(spec, code):
    """``spec`` is either one cabin key for every type, or a ``{code: key}`` map.

    ``A320`` and ``A321neo`` genuinely are different cabins, so a fixture that
    wants both has to say which spec belongs to which type.
    """
    if isinstance(spec, str):
        return spec
    return spec.get(code, next(iter(spec.values())))


def make_airline(name, types=('A320',), primary='A320', spec='NARROW_180'):
    """Build a whole airline - type, fleet entry, layout, cabins and seats.

    Tests used to lean on a hard-coded preset key; the cabin now lives in the
    database, so a fixture has to build the same chain the migration does.
    Returns the airline and a ``{code: AircraftType}`` map.
    """
    from airlines.fleet_data import write_layout

    airline = Airline.objects.create(name=name, status='ACTIVE')
    types_by_code = {}
    for code in types:
        aircraft_type = _aircraft_type(code)
        AirlineFleet.objects.create(
            airline=airline, aircraft_type=aircraft_type, is_primary=(code == primary))
        write_layout(SeatLayout, Cabin, Seat, airline, aircraft_type,
                     _spec_for(spec, code))
        types_by_code[code] = aircraft_type
    if primary in types_by_code:
        airline.default_aircraft_type = types_by_code[primary]
        airline.save()
    return airline, types_by_code


def _aircraft_type(code):
    from airlines.fleet_data import AIRCRAFT_TYPES, MANUFACTURERS

    brand, model, body_class, capacity = AIRCRAFT_TYPES[code]
    brand_name, country = MANUFACTURERS[brand]
    manufacturer, _ = Manufacturer.objects.get_or_create(
        name=brand_name, defaults={'country': country})
    aircraft_type, _ = AircraftType.objects.get_or_create(
        manufacturer=manufacturer, model_name=model,
        defaults={'body_class': body_class, 'typical_capacity': capacity})
    return aircraft_type


def make_aircraft(airline, type_code, tail, spec='NARROW_180'):
    """Register an airframe in an airline's fleet and fit it out.

    ``spec`` only matters the first time a type is seen: once the layout
    exists, the airframe inherits the cabin the airline already flies that type
    with, which is the whole point of the per-airline layout.
    """
    from airlines.fleet_data import write_layout

    aircraft_type = _aircraft_type(type_code)
    AirlineFleet.objects.get_or_create(airline=airline, aircraft_type=aircraft_type)
    layout = SeatLayout.objects.filter(
        airline=airline, aircraft_type=aircraft_type).first()
    if layout is None:
        layout = write_layout(SeatLayout, Cabin, Seat, airline, aircraft_type, spec)
    return Aircraft.objects.create(
        airline=airline, aircraft_type=aircraft_type, seat_layout=layout,
        tail_number=tail, status=Aircraft.Status.AVAILABLE)


def page_errors(response):
    """The validation messages a rejected form rendered, as plain text.

    ``assertContains`` on a rendered page dumps the whole document on failure,
    which buries the assertion that actually broke, so the alerts are pulled out
    and returned instead.
    """
    from django.contrib.messages import get_messages
    from django.utils.html import strip_tags

    found = [' '.join(strip_tags(str(m)).split())
             for m in get_messages(response.wsgi_request)]
    if found:
        return ' | '.join(found)
    return ' '.join(
        ' '.join(strip_tags(chunk).split())
        for chunk in re.findall(r'class="alert[^"]*"[^>]*>(.*?)</', response.content.decode(),
                                re.S))


def assertRejected(testcase, response, expected):
    """Assert the form came back with a complaint mentioning ``expected``."""
    testcase.assertEqual(response.status_code, 200)
    testcase.assertIn(expected, page_errors(response))


class ManagerPagesRenderTest(TestCase):
    """Every manager screen renders, and none offers a hand-picked cabin.

    A dead form control is worse than a missing one: it looks editable and is
    then silently ignored, so the page is checked rather than assumed.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True)
        self.client.force_login(self.user)
        self.airline, self.types = make_airline('Render Air', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-RND')

    def _pages(self):
        return {
            'manage': reverse('airlines:manage'),
            'flights': reverse('airlines:flights'),
            'aircrafts': reverse('airlines:aircrafts'),
            'flight_list': reverse('airlines:list'),
            'update_airline': reverse('airlines:update_airline', args=[self.airline.pk]),
            'airline_detail': reverse('airlines:airline_detail', args=[self.airline.pk]),
            'airline_fleet': reverse('airlines:airline_fleet', args=[self.airline.pk]),
            'add_aircraft': reverse('airlines:add_aircraft', args=[self.airline.pk]),
            'update_aircraft': reverse(
                'airlines:update_aircraft', args=[self.aircraft.pk]),
            'aircraft_detail': reverse(
                'airlines:aircraft_detail', args=[self.aircraft.pk]),
            'add_flight': reverse('airlines:add_flight', args=[self.airline.pk]),
            'add_flight_schedule': reverse('airlines:add_flight_schedule'),
        }

    def test_every_manager_page_renders(self):
        for name, url in self._pages().items():
            with self.subTest(page=name):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_no_form_offers_a_cabin_or_capacity_to_type_in(self):
        """The cabin is derived, so these controls must not exist anywhere."""
        for name in ('add_aircraft', 'update_aircraft', 'add_flight',
                     'add_flight_schedule', 'update_airline'):
            with self.subTest(page=name):
                body = self.client.get(self._pages()[name]).content.decode()
                for dead_field in ('name="seat_layout"', 'name="total_capacity"',
                                   'name="seating_capacity"'):
                    self.assertNotIn(dead_field, body)

    def test_the_aircraft_form_offers_this_airlines_fleet_types(self):
        """One airline's A320 is the choice; a type it does not fly is not."""
        body = self.client.get(
            reverse('airlines:add_aircraft', args=[self.airline.pk])).content.decode()
        self.assertIn('name="aircraft_type"', body)
        self.assertIn(self.types['A320'].label, body)

    def test_the_aircraft_list_filters_by_aircraft_type_id(self):
        """The type filter is a model id now, not a body class.

        Migrations seed real airlines, so the assertion is about which types
        survive the filter rather than about the total row count.
        """
        other, other_types = make_airline('Other Render Air', types=('A321',))
        stranger = make_aircraft(other, 'A321', 'RP-RND2')
        resp = self.client.get(
            reverse('airlines:aircrafts'),
            {'type': self.types['A320'].pk})
        self.assertEqual(resp.status_code, 200)
        listed = {a.tail_number for a in resp.context['aircrafts']}
        self.assertIn(self.aircraft.tail_number, listed)
        self.assertNotIn(stranger.tail_number, listed)
        for aircraft in resp.context['aircrafts']:
            self.assertEqual(aircraft.aircraft_type_id, self.types['A320'].pk)


class FleetDefinitionTest(TestCase):
    """The reference data the twenty airlines are built from."""

    def test_every_seeded_airline_has_a_fleet_and_a_default(self):
        for name, fleet in FLEETS.items():
            with self.subTest(airline=name):
                self.assertTrue(fleet, "an airline with no aircraft cannot sell a seat")
                self.assertIn(next(iter(fleet)), fleet)

    def test_every_cabin_spec_is_usable(self):
        """A spec is ``[(fare_class, blocks, rows), ...]`` - check the shape."""
        fare_classes = ('FIRST_CLASS', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY')
        for key, spec in CABIN_SPECS.items():
            with self.subTest(spec=key):
                self.assertTrue(spec, "an aircraft with no cabin cannot sell a seat")
                seen = []
                for fare_class, blocks, rows in spec:
                    seen.append(fare_class)
                    self.assertIn(fare_class, fare_classes)
                    self.assertGreater(rows, 0)
                    self.assertTrue(blocks)
                    for block in blocks:
                        self.assertGreater(block, 0)
                self.assertEqual(seen, sorted(
                    seen, key=fare_classes.index), "cabins must run airmail order")
                self.assertEqual(seen[-1], 'ECONOMY',
                                 "every cabin ends in economy")
                self.assertEqual(len(set(seen)), len(seen), "no duplicate cabins")

    def test_a_spec_key_states_the_capacity_it_actually_holds(self):
        """``B777_340`` has to seat 340. A stale row count is a silent lie."""
        for key, spec in CABIN_SPECS.items():
            with self.subTest(spec=key):
                self.assertEqual(
                    int(key.rsplit('_', 1)[-1]),
                    sum(rows * sum(blocks) for _, blocks, rows in spec),
                    'the spec key promises a capacity the rows do not add up to')

    def test_a_layout_written_to_the_database_matches_its_spec(self):
        airline, _ = make_airline('Layout Air', types=('A320',))
        layout = airline.seat_layouts.get()
        self.assertEqual(layout.seat_map, '3-3')
        self.assertEqual(layout.total_capacity, 180)
        # One Seat row per place the map offers, and no more.
        self.assertEqual(Seat.objects.filter(seat_layout=layout).count(), 180)
        self.assertEqual(
            layout.compute_capacity(),
            sum(c.rows * sum(c.blocks) for c in layout.cabins.all()))

    def test_seat_letters_skip_i_and_o(self):
        """A 3-4-3 cabin is 10 seats wide, so it reaches the skipped letters."""
        airline, _ = make_airline('Letter Air', types=('A380-800',), spec='A380_448')
        economy = airline.seat_layouts.get().cabins.get(fare_class='ECONOMY')
        self.assertEqual(economy.blocks, [3, 4, 3])
        # One row is enough: a 3-4-3 cabin is 10 seats wide.
        first_row = Seat.objects.filter(
            cabin=economy, row_number=economy.seats.order_by('row_number')
            .values_list('row_number', flat=True).first()
        ).order_by('letter').values_list('letter', flat=True)
        self.assertEqual(list(first_row),
                         ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K'])
        self.assertFalse(Seat.objects.filter(
            seat_layout=economy.seat_layout, letter__in=['I', 'O']).exists())

    def test_two_airlines_can_fly_the_same_type_differently(self):
        """The whole point of the chain: one airframe, two different cabins."""
        pale, _ = make_airline('Narrow Air', types=('A320',))
        wide, _ = make_airline('Wide Air', types=('B777-300ER',), spec='B777_340')
        self.assertEqual(pale.seat_layouts.get().total_capacity, 180)
        self.assertEqual(wide.seat_layouts.get().total_capacity, 340)
        self.assertNotEqual(pale.seat_layouts.get().pk, wide.seat_layouts.get().pk)


class FleetConstraintTest(TestCase):
    """An aircraft must belong to one airline and one type from its fleet."""

    def setUp(self):
        self.airline, self.types = make_airline('Host Air', types=('A320', 'A321'))
        self.other, self.other_types = make_airline('Guest Air', types=('A320',))

    def test_aircraft_type_outside_the_airlines_fleet_is_rejected(self):
        aircraft = Aircraft(
            airline=self.airline, aircraft_type=self.other_types['A320'],
            tail_number='RP-BAD-1', status='AVAILABLE')
        with self.assertRaises(ValidationError):
            aircraft.full_clean()

    def test_layout_from_another_airline_is_rejected(self):
        aircraft = Aircraft(
            airline=self.airline, aircraft_type=self.types['A320'],
            seat_layout=self.other.seat_layouts.get(),
            tail_number='RP-BAD-2', status='AVAILABLE')
        with self.assertRaises(ValidationError):
            aircraft.full_clean()

    def test_a_type_cannot_be_in_one_airlines_fleet_twice(self):
        with self.assertRaises(ValidationError):
            AirlineFleet(
                airline=self.airline, aircraft_type=self.types['A320']).full_clean()

    def test_one_layout_per_airline_and_type(self):
        with self.assertRaises(ValidationError):
            SeatLayout(
                airline=self.airline, aircraft_type=self.types['A320']).full_clean()

    def test_a_default_type_must_be_in_the_airlines_own_fleet(self):
        """Aircraft types are shared, so the check is on the fleet, not the type.

        'Guest Air' flying an A320 does not make that A320 foreign — both
        airlines point at the same ``AircraftType`` row. What is not allowed is
        a default naming a type this airline has never added to its fleet.
        """
        stranger = _aircraft_type('B777-300ER')
        self.airline.default_aircraft_type = stranger
        with self.assertRaises(ValidationError):
            self.airline.full_clean()
        # The very same type is fine once the airline actually flies it.
        AirlineFleet.objects.create(
            airline=self.airline, aircraft_type=stranger)
        self.airline.full_clean()

    def test_a_valid_aircraft_is_accepted(self):
        aircraft = make_aircraft(self.airline, 'A320', 'RP-OK-1')
        aircraft.full_clean()


class LayoutResolutionTest(TestCase):
    """Most specific first: the aircraft flying it, then the airline's fleet."""

    def setUp(self):
        # Two genuinely different cabins in one fleet: the narrowbody sits 180,
        # the A321neo 240. A single spec for both would hide the whole point.
        self.airline, self.types = make_airline(
            'Resolve Air', types=('A320', 'A321N'), primary='A320',
            spec={'A320': 'NARROW_180', 'A321N': 'NARROW_240'})

    def test_the_operated_aircraft_decides_the_cabin(self):
        """A Cebu Pacific A320neo and an A321neo are not the same cabin."""
        a320 = make_aircraft(self.airline, 'A320', 'RP-RES-1')
        a321 = make_aircraft(self.airline, 'A321N', 'RP-RES-2')
        self.assertEqual(resolve_layout(Flight(airline=self.airline, aircraft=a320))
                         .total_capacity, 180)
        self.assertEqual(resolve_layout(Flight(airline=self.airline, aircraft=a321))
                         .total_capacity, 240)

    def test_a_flight_with_no_aircraft_falls_back_to_the_default_type(self):
        flight = Flight(airline=self.airline)
        self.assertEqual(resolve_layout(flight).aircraft_type, self.types['A320'])

    def test_a_flight_falls_back_to_the_first_active_fleet_type(self):
        """Even with no default set, the airline's fleet still supplies a cabin."""
        self.airline.default_aircraft_type = None
        self.airline.save()
        flight = Flight(airline=self.airline)
        layout = resolve_layout(flight)
        self.assertIsNotNone(layout)
        self.assertIn(layout.aircraft_type, self.types.values())

    def test_no_airline_means_no_cabin(self):
        self.assertIsNone(resolve_layout(None))
        self.assertIsNone(resolve_layout(Flight()))

    def test_capacity_follows_the_cabin_not_the_typed_in_number(self):
        """The record's own seating_capacity cannot override the layout."""
        aircraft = make_aircraft(self.airline, 'A321N', 'RP-RES-3')
        aircraft.seating_capacity = 99
        aircraft.save()
        flight = Flight.objects.create(
            airline=self.airline, aircraft=aircraft, flight_number='FL-CAP',
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
            status='SCHEDULED', economy_fare=1500)
        self.assertEqual(flight.total_capacity, 240)


class SeatMapTest(TestCase):
    """The map the booking page draws is built from the Seat table."""

    def setUp(self):
        self.airline, _ = make_airline(
            'Map Air', types=('A380-800', 'A330-300'), primary='A380-800',
            spec={'A380-800': 'A380_448', 'A330-300': 'A330_324'})
        self.aircraft = make_aircraft(self.airline, 'A380-800', 'A6-MAP')
        self.flight = Flight.objects.create(
            airline=self.airline, aircraft=self.aircraft, flight_number='EK-MAP',
            departure_time=timezone.now() + timedelta(days=3),
            arrival_time=timezone.now() + timedelta(days=3, hours=8),
            status='SCHEDULED', economy_fare=30000)

    def test_the_map_offers_exactly_the_seats_the_database_has(self):
        sm = build_seat_map(self.flight)
        drawn = sum(len(b['cols']) for c in sm['cabins'] for r in c['rows']
                    for b in r['blocks'])
        self.assertEqual(drawn, self.flight.total_capacity)
        self.assertEqual(drawn, Seat.objects.filter(
            seat_layout=self.flight.seat_layout_record).count())

    def test_cabins_come_out_in_airmail_order(self):
        sm = build_seat_map(self.flight)
        self.assertEqual([c['key'] for c in sm['cabins']],
                         ['FIRST_CLASS', 'BUSINESS', 'ECONOMY'])
        self.assertEqual(sm['aircraft'], 'Airbus A380-800')

    def test_row_numbers_run_globally_like_a_boarding_pass(self):
        sm = build_seat_map(self.flight)
        rows = [r['row'] for c in sm['cabins'] for r in c['rows']]
        self.assertEqual(rows, list(range(1, len(rows) + 1)))

    def test_a_1_2_1_cabin_judges_each_block_on_its_own(self):
        first = build_seat_map(self.flight)['cabins'][0]
        self.assertEqual(
            [[c['position'] for c in b['cols']] for b in first['rows'][0]['blocks']],
            [['window'], ['window', 'aisle'], ['window']])

    def test_a_3_4_3_cabin_marks_its_three_aisles(self):
        economy = build_seat_map(self.flight)['cabins'][-1]
        self.assertEqual(
            [[c['position'] for c in b['cols']] for b in economy['rows'][0]['blocks']],
            [['window', 'middle', 'aisle'],
             ['window', 'middle', 'middle', 'aisle'],
             ['window', 'middle', 'aisle']])

    def test_taken_seats_are_marked_and_cannot_be_rebooked(self):
        sm = build_seat_map(self.flight, taken={'1A'})
        first = sm['cabins'][0]['rows'][0]['blocks'][0]['cols'][0]
        self.assertEqual(first['seat'], '1A')
        self.assertTrue(first['taken'])

    def test_each_cabin_prices_from_its_own_fare_field(self):
        sm = build_seat_map(self.flight)
        self.assertEqual(
            [c['fare_field'] for c in sm['cabins']],
            ['first_class_fare', 'business_fare', 'economy_fare'])


class FlightLocationTest(TestCase):
    """The worldwide location hierarchy wired into flights must survive the
    model, the flight list filter and the manager's add-flight form."""

    def setUp(self):
        self.airline, self.types = make_airline('Test Air', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-TST')

    def _flight(self, **kw):
        base = dict(
            airline=self.airline, aircraft=self.aircraft,
            flight_number='FL-001', origin='Manila', destination='Cebu',
            origin_country='Philippines', origin_province='Metro Manila',
            destination_country='Philippines', destination_province='Cebu',
            destination_municipality='Cebu City',
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
            status='SCHEDULED', economy_fare=1500, first_class_fare=3000,
        )
        base.update(kw)
        return Flight.objects.create(**base)

    def test_structured_fields_survive_round_trip(self):
        flight = self._flight(
            flight_number='FL-INTL',
            origin='Bangkok', origin_country='Thailand', origin_province='Bangkok',
            origin_municipality='', destination='Athens', destination_country='Greece',
            destination_province='Attica', destination_municipality='Athens')
        flight = Flight.objects.get(pk=flight.pk)
        self.assertEqual(flight.origin_country, 'Thailand')
        self.assertEqual(flight.origin_province, 'Bangkok')
        self.assertEqual(flight.origin_municipality, '')
        self.assertEqual(flight.destination_country, 'Greece')
        self.assertEqual(flight.destination_province, 'Attica')
        self.assertEqual(flight.destination_municipality, 'Athens')

    def test_list_filters_by_origin_municipality(self):
        self._flight(flight_number='FL-01', origin='Manila', origin_country='Philippines',
                     origin_province='Metro Manila', origin_municipality='Manila')
        self._flight(flight_number='FL-02', origin='Cebu', origin_country='Philippines',
                     origin_province='Cebu', origin_municipality='Cebu City')
        resp = self.client.get(reverse('airlines:list'), {'origin_municipality': 'Manila'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({f.flight_number for f in resp.context['flights']}, {'FL-01'})

    def test_list_filters_by_origin_country_only(self):
        ph = Country.objects.create(geoname_id=-1, code='PH', name='Philippines')
        ncr = Region.objects.create(geoname_id=-2, code='NCR',
                                    name='National Capital Region', country=ph)
        Province.objects.create(geoname_id=-3, code='H2', name='Capital District', region=ncr)
        self._flight(flight_number='FL-01', origin='Manila', origin_country='Philippines',
                     origin_province='Metro Manila')
        self._flight(flight_number='FL-02', origin='Bangkok', origin_country='Thailand',
                     origin_province='Bangkok')
        resp = self.client.get(reverse('airlines:list'), {'origin_country': 'Philippines'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({f.flight_number for f in resp.context['flights']}, {'FL-01'})

    def test_add_flight_saves_airport_fields(self):
        user = get_user_model().objects.create_user(username='boss', password='x', is_staff=True)
        self.client.force_login(user)
        mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            icao_code='RPLL', city='Manila', country='Philippines',
            country_code='PH', region='National Capital Region',
            latitude=14.5086, longitude=121.0194, status='ACTIVE')
        sin = Airport.objects.create(
            airport_name='Singapore Changi Airport', iata_code='SIN',
            icao_code='WSSS', city='Singapore', country='Singapore',
            country_code='SG', region='Singapore',
            latitude=1.3644, longitude=103.9915, status='ACTIVE')
        payload = dict(
            flight_number='FL-NEW', aircraft=self.aircraft.pk, trip_type='ONE_WAY',
            origin_airport=mnl.pk, destination_airport=sin.pk,
            departure_time='2027-01-05T09:00', arrival_time='2027-01-05T11:00',
            economy_fare='1200', first_class_fare='2400', status='SCHEDULED')
        resp = self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]), payload)
        self.assertEqual(resp.status_code, 302)
        flight = Flight.objects.get(flight_number='FL-NEW')
        self.assertEqual(flight.origin_airport, mnl)
        self.assertEqual(flight.destination_airport, sin)
        self.assertEqual(flight.origin, 'Manila')
        self.assertEqual(flight.origin_code, 'MNL')
        self.assertEqual(flight.origin_country, 'Philippines')
        self.assertEqual(flight.origin_province, 'National Capital Region')
        self.assertEqual(flight.origin_municipality, 'Manila')
        self.assertEqual(flight.destination, 'Singapore')
        self.assertEqual(flight.destination_code, 'SIN')
        self.assertEqual(flight.destination_country, 'Singapore')

    def test_add_flight_rejects_same_origin_destination(self):
        user = get_user_model().objects.create_user(username='boss', password='x', is_staff=True)
        self.client.force_login(user)
        mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            icao_code='RPLL', city='Manila', country='Philippines',
            country_code='PH', status='ACTIVE')
        payload = dict(
            flight_number='FL-BAD', aircraft=self.aircraft.pk, trip_type='ONE_WAY',
            origin_airport=mnl.pk, destination_airport=mnl.pk,
            departure_time='2027-01-05T09:00', arrival_time='2027-01-05T11:00',
            economy_fare='1200', first_class_fare='2400', status='SCHEDULED')
        resp = self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]), payload)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='FL-BAD').exists())
        self.assertContains(resp, "Origin and destination cannot be the same airport.")

    def test_a_posted_seat_layout_cannot_smuggle_in_a_foreign_cabin(self):
        """The map is derived, so a hand-posted layout key is simply ignored."""
        user = get_user_model().objects.create_user(username='boss', password='x', is_staff=True)
        self.client.force_login(user)
        mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            icao_code='RPLL', city='Manila', country='Philippines',
            country_code='PH', status='ACTIVE')
        ceb = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            icao_code='RPVM', city='Cebu', country='Philippines',
            country_code='PH', status='ACTIVE')
        payload = dict(
            flight_number='FL-SMUGGLE', trip_type='ONE_WAY',
            origin_airport=mnl.pk, destination_airport=ceb.pk,
            departure_time='2027-01-05T09:00', arrival_time='2027-01-05T11:00',
            seat_layout='EMIRATES_A380',
            economy_fare='1200', first_class_fare='2400', status='SCHEDULED')
        resp = self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]), payload)
        self.assertEqual(resp.status_code, 302)
        flight = Flight.objects.get(flight_number='FL-SMUGGLE')
        self.assertEqual(flight.capacity, 180)
        self.assertEqual(flight.cabin_classes, ['ECONOMY'])


class FlightScheduleTest(TestCase):
    """A flight is only a schedule: it must be creatable with nothing but an
    airline, a route and a departure/arrival — no aircraft, and no seat layout
    chosen by hand, because the seats come from the airline's real cabin."""

    def setUp(self):
        self.airline, self.types = make_airline('Test Air', types=('A320',))
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            icao_code='RPLL', city='Manila', country='Philippines', status='ACTIVE')
        self.ceb = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            icao_code='RPVM', city='Cebu', country='Philippines', status='ACTIVE')

    def _login(self):
        user = get_user_model().objects.create_user(username='boss', password='x', is_staff=True)
        self.client.force_login(user)
        return user

    def _payload(self, **kw):
        base = dict(
            airline=self.airline.pk, trip_type='ONE_WAY',
            origin_airport=self.mnl.pk, destination_airport=self.ceb.pk,
            departure_time='2027-01-05T09:00', arrival_time='2027-01-05T11:00',
            economy_fare='1200', first_class_fare='2400', business_fare='0',
            premium_economy_fare='0', status='SCHEDULED')
        base.update(kw)
        return base

    def test_standalone_schedule_form_creates_flight_without_aircraft(self):
        self._login()
        resp = self.client.post(reverse('airlines:add_flight_schedule'),
                                self._payload(flight_number='FL-NOAC'))
        self.assertEqual(resp.status_code, 302)
        flight = Flight.objects.get(flight_number='FL-NOAC')
        self.assertIsNone(flight.aircraft)
        self.assertEqual(flight.airline, self.airline)
        # Inherits the airline's real 3-3 narrowbody: 180 sellable seats.
        self.assertEqual(flight.capacity, 180)
        self.assertEqual(flight.seat_layout_record.airline, self.airline)

    def test_schedule_form_requires_an_airline(self):
        self._login()
        resp = self.client.post(reverse('airlines:add_flight_schedule'),
                                self._payload(flight_number='FL-NOAIR', airline=''))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='FL-NOAIR').exists())
        self.assertContains(resp, "Please choose an airline.")

    def test_standalone_form_get_renders_without_aircraft(self):
        self._login()
        resp = self.client.get(reverse('airlines:add_flight_schedule'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="airline"')
        self.assertNotContains(resp, 'name="total_capacity"')

    def test_assigned_aircraft_supplies_its_own_cabin(self):
        self._login()
        aircraft = make_aircraft(self.airline, 'A320', 'RP-CAP')
        resp = self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]),
                                self._payload(flight_number='FL-CAP', aircraft=aircraft.pk))
        self.assertEqual(resp.status_code, 302)
        flight = Flight.objects.get(flight_number='FL-CAP')
        self.assertEqual(flight.aircraft, aircraft)
        self.assertEqual(flight.capacity, 180)
        aircraft.refresh_from_db()
        self.assertEqual(aircraft.status, Aircraft.Status.ASSIGNED)

    def test_a_second_type_in_the_fleet_changes_the_cabin(self):
        """Dependent dropdown all the way through: the aircraft decides the map."""
        self._login()
        self.airline.fleet_entries.filter(
            aircraft_type=self.types['A320']).update(is_active=False)
        # The A321N is new to this airline, so it gets fitted out at 240 while
        # the retired A320's 180-seat layout is left on the book untouched.
        wide = make_aircraft(self.airline, 'A321N', 'RP-WIDE', spec='NARROW_240')
        resp = self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]),
                                self._payload(flight_number='FL-WIDE', aircraft=wide.pk))
        self.assertEqual(resp.status_code, 302)
        flight = Flight.objects.get(flight_number='FL-WIDE')
        self.assertEqual(flight.capacity, 240)
        self.assertEqual(flight.cabin_classes, ['ECONOMY'])

    def test_aircraft_from_another_airline_is_not_assignable(self):
        self._login()
        other, _ = make_airline('Other Air', types=('A320',))
        foreign = make_aircraft(other, 'A320', 'RP-FOR')
        resp = self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]),
                                self._payload(flight_number='FL-FOR', aircraft=foreign.pk))
        self.assertEqual(resp.status_code, 302)
        flight = Flight.objects.get(flight_number='FL-FOR')
        self.assertIsNone(flight.aircraft)
        self.assertEqual(flight.capacity, 180)

    def test_an_airline_with_no_fleet_cannot_be_scheduled(self):
        """Nothing to sell means nothing to schedule."""
        self._login()
        bare = Airline.objects.create(name='Bare Air', status='ACTIVE')
        resp = self.client.post(reverse('airlines:add_flight', args=[bare.pk]),
                                self._payload(flight_number='FL-BARE', airline=''))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='FL-BARE').exists())
        self.assertContains(resp, 'no aircraft types in its fleet')

    def test_retiring_a_type_leaves_the_flights_already_on_it_alone(self):
        """A type can leave the fleet without stranding the aircraft flying it."""
        self._login()
        aircraft = make_aircraft(self.airline, 'A320', 'RP-RETIRE')
        flight = Flight.objects.create(
            airline=self.airline, aircraft=aircraft, flight_number='FL-RETIRE',
            origin_airport=self.mnl, destination_airport=self.ceb,
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
            status='SCHEDULED', economy_fare=1500)
        self.assertEqual(flight.capacity, 180)
        self.airline.fleet_entries.filter(
            aircraft_type=self.types['A320']).update(is_active=False)
        flight.refresh_from_db()
        self.assertEqual(flight.seat_layout_record, aircraft.seat_layout)
        self.assertEqual(flight.capacity, 180)

    def test_updating_can_detach_the_aircraft(self):
        self._login()
        aircraft = make_aircraft(self.airline, 'A320', 'RP-DET')
        flight = Flight.objects.create(
            airline=self.airline, aircraft=aircraft, flight_number='FL-DET',
            origin_airport=self.mnl, destination_airport=self.ceb,
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
            status='SCHEDULED', economy_fare=1500, first_class_fare=3000)
        resp = self.client.post(reverse('airlines:update_flight', args=[flight.pk]),
                                self._payload(flight_number='FL-DET', aircraft=''))
        self.assertEqual(resp.status_code, 302)
        flight.refresh_from_db()
        self.assertIsNone(flight.aircraft)
        self.assertEqual(flight.capacity, 180)
        self.assertEqual(flight.origin_airport, self.mnl)
        self.assertEqual(flight.destination_airport, self.ceb)
        self.assertLess(flight.departure_time, flight.arrival_time)
        aircraft.refresh_from_db()
        self.assertEqual(aircraft.status, Aircraft.Status.AVAILABLE)

    def test_aircraft_cannot_fly_two_overlapping_flights(self):
        self._login()
        aircraft = make_aircraft(self.airline, 'A320', 'RP-DUP')
        self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]),
                         self._payload(flight_number='FL-DUP1', aircraft=aircraft.pk))
        resp = self.client.post(reverse('airlines:add_flight', args=[self.airline.pk]),
                                self._payload(flight_number='FL-DUP2', aircraft=aircraft.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='FL-DUP2').exists())
        self.assertContains(resp, "RP-DUP is already scheduled during that time.")

    def test_public_list_reports_remaining_seats_from_flight_capacity(self):
        Flight.objects.create(
            airline=self.airline, flight_number='FL-CAP-LIST',
            origin_airport=self.mnl, destination_airport=self.ceb,
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
            status='SCHEDULED', economy_fare=1500, first_class_fare=3000)
        resp = self.client.get(reverse('airlines:list'))
        self.assertEqual(resp.status_code, 200)
        flight = next(f for f in resp.context['flights'] if f.flight_number == 'FL-CAP-LIST')
        self.assertEqual(flight.remaining_seats, 180)


class RoundTripScheduleTest(TestCase):
    """A round trip is two real legs, not one row with a return date.

    Each leg can be operated by a different airframe, so each one has to keep its
    own cabin, capacity and seat map; the two are tied together by a shared group
    so either can be opened and still find its partner.
    """

    def setUp(self):
        self.airline, self.types = make_airline(
            'Round Trip Air', types=('A320', 'A330-300'),
            spec={'A320': 'NARROW_180', 'A330-300': 'A330_324'})
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            icao_code='RPLL', city='Manila', country='Philippines', status='ACTIVE')
        self.ceb = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            icao_code='RPVM', city='Cebu', country='Philippines', status='ACTIVE')
        self.narrow = make_aircraft(self.airline, 'A320', 'RP-RT-NARROW')
        self.wide = make_aircraft(self.airline, 'A330-300', 'RP-RT-WIDE')
        user = get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True)
        self.client.force_login(user)
        # Booking is for travellers, not the manager, so the booking tests sign
        # in as a separate non-staff account.
        self.traveller = get_user_model().objects.create_user(
            username='traveller', password='x', email='t@example.com')

    def _payload(self, **kw):
        base = dict(
            airline=self.airline.pk, trip_type='ROUND_TRIP',
            flight_number='5J100', origin_airport=self.mnl.pk,
            destination_airport=self.ceb.pk,
            departure_time='2027-01-05T09:00', arrival_time='2027-01-05T11:00',
            return_flight_number='5J101',
            return_origin_airport=self.ceb.pk, return_destination_airport=self.mnl.pk,
            return_departure_time='2027-01-12T09:00',
            return_arrival_time='2027-01-12T11:00',
            economy_fare='1200', first_class_fare='2400', business_fare='0',
            premium_economy_fare='0', status='SCHEDULED')
        base.update(kw)
        return base

    def _add(self, **kw):
        return self.client.post(
            reverse('airlines:add_flight_schedule'), self._payload(**kw))

    def test_a_round_trip_stores_two_linked_legs_flying_in_reverse(self):
        self.assertEqual(self._add().status_code, 302)
        out = Flight.objects.get(flight_number='5J100')
        back = Flight.objects.get(flight_number='5J101')

        self.assertEqual(out.trip_type, Flight.TripType.ROUND_TRIP)
        self.assertEqual(out.trip_role, TripRole.OUTBOUND)
        self.assertEqual(back.trip_role, TripRole.RETURN)
        # The return is a schedule in its own right, so it is sold as a one-way
        # leg of the trip rather than as a second round trip.
        self.assertEqual(back.trip_type, Flight.TripType.ONE_WAY)

        self.assertIsNotNone(out.round_trip_group)
        self.assertEqual(out.round_trip_group, back.round_trip_group)
        self.assertEqual(out.paired_flight, back)
        self.assertEqual(back.paired_flight, out)

        self.assertEqual((out.origin_airport, out.destination_airport),
                         (self.mnl, self.ceb))
        self.assertEqual((back.origin_airport, back.destination_airport),
                         (self.ceb, self.mnl))
        self.assertEqual(out.return_flight, back)
        self.assertIsNone(back.return_flight)
        self.assertEqual(back.departure_flight, out)
        self.assertTrue(out.is_round_trip)
        self.assertTrue(back.is_round_trip)

    def test_round_trip_search_returns_paired_reverse_route_on_selected_date(self):
        self.assertEqual(self._add().status_code, 302)
        outbound = Flight.objects.get(flight_number='5J100')
        self.client.force_login(self.traveller)
        response = self.client.get(reverse('airlines:list'), {
            'search_submit': '1',
            'origin_airport': self.mnl.pk,
            'destination_airport': self.ceb.pk,
            'departure_date': '2027-01-05',
            'return_date': '2027-01-12',
            'trip_type': 'ROUND_TRIP',
            'fare_class': 'ECONOMY',
            'passengers': '1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual([flight.pk for flight in response.context['flights']],
                         [outbound.pk])
        self.assertEqual(response.context['flights'][0].search_fare, 2400)
        self.assertEqual([flight.pk for flight in response.context['return_rows']], [outbound.return_flight.pk])
        self.assertEqual(response.context['return_rows'][0].search_fare, 1200)
        self.assertContains(response, 'Outbound flights')
        self.assertContains(response, 'Return flights')
        self.assertContains(response, 'js-select-outbound')
        self.assertContains(response, 'js-select-return')
        self.assertContains(response, 'Combined round-trip price')
        self.assertContains(response, 'Jan 12')

    def test_browser_round_trip_selection_preserves_outbound_and_books_the_pair(self):
        from playwright.sync_api import sync_playwright

        self.assertEqual(self._add().status_code, 302)
        outbound = Flight.objects.get(flight_number='5J100')
        self.client.force_login(self.traveller)
        response = self.client.get(reverse('airlines:list'), {
            'search_submit': '1',
            'origin_airport': self.mnl.pk,
            'destination_airport': self.ceb.pk,
            'departure_date': '2027-01-05',
            'return_date': '2027-01-12',
            'trip_type': 'ROUND_TRIP',
            'fare_class': 'ECONOMY',
            'passengers': '1',
        })
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_content(response.content.decode(), wait_until='domcontentloaded')
            page.get_by_role('button', name='Select outbound').click()
            self.assertTrue(page.locator('[data-return-section]').is_visible())
            outbound_card = page.locator(
                '.js-select-outbound[data-flight-id="%s"]' % outbound.pk
            ).locator('xpath=ancestor::article')
            self.assertIn('is-selected', outbound_card.get_attribute('class'))
            page.locator('.js-select-return:visible').click()
            self.assertIn('is-selected', outbound_card.get_attribute('class'))
            self.assertTrue(page.locator('[data-trip-selection]').is_visible())
            self.assertIn('2,400', page.locator('[data-combined-price]').inner_text())
            expected_booking = reverse('airlines:book', args=[outbound.pk])
            self.assertIn(expected_booking, page.locator('[data-book-selected-flight]').get_attribute('href'))
            browser.close()

    def test_round_trip_search_requires_return_date_not_before_departure(self):
        self._add()
        response = self.client.get(reverse('airlines:list'), {
            'search_submit': '1',
            'origin_airport': self.mnl.pk,
            'destination_airport': self.ceb.pk,
            'departure_date': '2027-01-12',
            'return_date': '2027-01-05',
            'trip_type': 'ROUND_TRIP',
            'passengers': '1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'Return date cannot be earlier than departure.')
        self.assertEqual(list(response.context['flights']), [])

    def test_each_leg_can_fly_a_different_aircraft_with_its_own_seat_map(self):
        """The reason the return is a second row: a widebody back and a narrowbody
        out means two different cabins and two different seat maps."""
        self.assertEqual(self._add(aircraft=self.narrow.pk,
                                   return_aircraft=self.wide.pk).status_code, 302)
        out = Flight.objects.get(flight_number='5J100')
        back = Flight.objects.get(flight_number='5J101')

        self.assertEqual(out.aircraft, self.narrow)
        self.assertEqual(back.aircraft, self.wide)
        self.assertEqual(out.seat_layout_record, self.narrow.seat_layout)
        self.assertEqual(back.seat_layout_record, self.wide.seat_layout)
        self.assertNotEqual(out.seat_layout_record, back.seat_layout_record)
        self.assertEqual(out.capacity, 180)
        self.assertEqual(back.capacity, 324)
        for airframe in (self.narrow, self.wide):
            airframe.refresh_from_db()
            self.assertEqual(airframe.status, Aircraft.Status.ASSIGNED)

    def test_the_return_leg_can_reuse_the_departure_aircraft(self):
        """A blank return aircraft means "same airframe turns back"."""
        self.assertEqual(self._add(aircraft=self.narrow.pk,
                                   return_aircraft='').status_code, 302)
        out = Flight.objects.get(flight_number='5J100')
        back = Flight.objects.get(flight_number='5J101')
        self.assertEqual(back.aircraft, self.narrow)
        self.assertEqual(back.seat_layout_record, out.seat_layout_record)

    def test_the_return_leg_can_stay_unassigned(self):
        """The explicit "not assigned yet" choice keeps the leg open, and the
        airframe already flying the outbound is not dragged onto it."""
        self.assertEqual(self._add(aircraft=self.narrow.pk,
                                   return_aircraft=NO_AIRCRAFT).status_code, 302)
        back = Flight.objects.get(flight_number='5J101')
        self.assertIsNone(back.aircraft)
        # Falls back to the airline default cabin, exactly like a one-way.
        self.assertEqual(back.seat_layout_record.airline, self.airline)
        self.assertEqual(back.capacity, 180)

    def test_the_return_leg_must_fly_the_route_in_reverse(self):
        resp = self._add(return_origin_airport=self.mnl.pk,
                         return_destination_airport=self.ceb.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='5J101').exists())
        self.assertContains(resp, "Return origin must be the departure destination")

    def test_the_return_cannot_depart_before_the_outbound(self):
        resp = self._add(return_departure_time='2027-01-04T09:00',
                         return_arrival_time='2027-01-04T11:00')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='5J101').exists())
        self.assertContains(resp, "Return date must not be earlier")

    def test_a_round_trip_needs_both_flight_numbers(self):
        resp = self._add(return_flight_number='')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='5J100').exists())
        self.assertContains(resp, "Return flight number is required.")

    def test_a_foreign_aircraft_cannot_be_smuggled_onto_the_return_leg(self):
        other, _ = make_airline('Foreign Air', types=('A320',))
        foreign = make_aircraft(other, 'A320', 'RP-RT-FOR')
        self._add(return_aircraft=foreign.pk)
        back = Flight.objects.get(flight_number='5J101')
        self.assertIsNone(back.aircraft)

    def test_an_aircraft_already_flying_the_outbound_is_not_double_booked(self):
        """The return inherits the outbound airframe, so it must be checked
        against the outbound's own times rather than passing as a free slot."""
        # An existing flight already occupies the return window on this airframe.
        Flight.objects.create(
            airline=self.airline, aircraft=self.narrow, flight_number='5J900',
            origin_airport=self.ceb, destination_airport=self.mnl,
            departure_time=timezone.make_aware(
                timezone.datetime(2027, 1, 12, 9, 0)),
            arrival_time=timezone.make_aware(
                timezone.datetime(2027, 1, 12, 11, 0)),
            status='SCHEDULED', economy_fare=1200)
        resp = self._add(aircraft=self.narrow.pk, return_aircraft='')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Flight.objects.filter(flight_number='5J101').exists())
        self.assertContains(resp, "RP-RT-NARROW is already scheduled")

    def test_editing_the_return_leg_edits_the_whole_trip(self):
        self._add()
        back = Flight.objects.get(flight_number='5J101')
        resp = self.client.get(reverse('airlines:update_flight', args=[back.pk]))
        self.assertRedirects(
            resp, reverse('airlines:update_flight',
                          args=[back.paired_flight.pk]), fetch_redirect_response=False)

    def test_the_form_offers_one_way_and_round_trip_before_anything_else(self):
        resp = self.client.get(reverse('airlines:add_flight_schedule'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="trip_type"')
        self.assertContains(resp, 'value="ONE_WAY"')
        self.assertContains(resp, 'value="ROUND_TRIP"')
        # Airlines are picked from the ones already in the system, not created here.
        self.assertContains(resp, 'name="airline"')
        self.assertNotContains(resp, 'name="total_capacity"')
        # No hand-drawn seat map: the cabins come from the fleet.
        self.assertNotContains(resp, 'name="cabin_layout"')

    def test_booking_a_round_trip_books_both_legs_with_separate_seats(self):
        self._add(aircraft=self.narrow.pk, return_aircraft=self.wide.pk)
        out = Flight.objects.get(flight_number='5J100')
        back = Flight.objects.get(flight_number='5J101')

        self.client.force_login(self.traveller)
        page = self.client.get(reverse('airlines:book', args=[out.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['return_flight'], back)
        self.assertIsNotNone(page.context['return_seat_map'])
        # Both cabins are on the page, so the passenger picks a seat on each leg.
        # Passenger 1 is assigned from the hidden primary field; the extra
        # passenger rows (2+) are built by JS from the two maps.
        self.assertContains(page, 'name="primary_return_seat"')
        self.assertContains(page, 'data-return-panel')
        self.assertContains(page, 'data-seat-side="return"')
        # The two legs are sold on different airframes, so both maps differ.
        self.assertContains(page, 'RP-RT-WIDE')

    def test_booking_the_return_leg_directly_lands_on_the_outbound(self):
        self._add()
        back = Flight.objects.get(flight_number='5J101')
        self.client.force_login(self.traveller)
        resp = self.client.get(reverse('airlines:book', args=[back.pk]))
        self.assertRedirects(
            resp, reverse('airlines:book', args=[back.paired_flight.pk]),
            fetch_redirect_response=False)

    def test_downgrading_to_one_way_keeps_the_return_leg_as_a_schedule(self):
        self._add(aircraft=self.narrow.pk, return_aircraft=self.wide.pk)
        out = Flight.objects.get(flight_number='5J100')
        resp = self.client.post(
            reverse('airlines:update_flight', args=[out.pk]),
            self._payload(trip_type='ONE_WAY', aircraft=self.narrow.pk,
                          return_flight_number='', return_origin_airport='',
                          return_destination_airport='',
                          return_departure_time='', return_arrival_time=''))
        self.assertEqual(resp.status_code, 302)
        out.refresh_from_db()
        back = Flight.objects.get(flight_number='5J101')
        self.assertEqual(out.trip_type, Flight.TripType.ONE_WAY)
        self.assertIsNone(out.round_trip_group)
        self.assertIsNone(out.paired_flight)
        # The leg is still a real, bookable flight — it is just no longer paired.
        self.assertEqual(back.trip_type, Flight.TripType.ONE_WAY)
        self.assertEqual(back.trip_role, TripRole.OUTBOUND)
        self.assertIsNone(back.round_trip_group)
        self.assertEqual(back.aircraft, self.wide)

    def test_turning_a_one_way_into_a_round_trip_attaches_a_return_leg(self):
        self.client.post(reverse('airlines:add_flight_schedule'),
                         self._payload(trip_type='ONE_WAY', return_flight_number='',
                                       return_origin_airport='', return_destination_airport='',
                                       return_departure_time='', return_arrival_time=''))
        out = Flight.objects.get(flight_number='5J100')
        self.assertIsNone(out.paired_flight)

        resp = self.client.post(reverse('airlines:update_flight', args=[out.pk]),
                                self._payload(aircraft=self.narrow.pk,
                                              return_aircraft=self.wide.pk))
        self.assertEqual(resp.status_code, 302)
        out.refresh_from_db()
        back = Flight.objects.get(flight_number='5J101')
        self.assertEqual(out.trip_type, Flight.TripType.ROUND_TRIP)
        self.assertEqual(out.paired_flight, back)
        self.assertEqual(back.paired_flight, out)
        self.assertEqual(back.aircraft, self.wide)

    def test_the_seat_map_renders_the_airlines_real_cabin(self):
        wide, _ = make_airline('Wide Map Air', types=('A330-300',),
                               spec='A330_324')
        flight = Flight.objects.create(
            airline=wide, flight_number='FL-MAP',
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
            status='SCHEDULED', economy_fare=1500, first_class_fare=3000)
        seat_map = build_seat_map(flight)
        self.assertEqual(seat_map['aircraft'], 'Airbus A330-300')
        self.assertEqual(seat_map['total_seats'], 324)
        self.assertEqual(
            [c['key'] for c in seat_map['cabins']],
            ['FIRST_CLASS', 'BUSINESS', 'ECONOMY'])
        first = seat_map['cabins'][0]
        self.assertEqual(first['label'], 'First Class')
        self.assertEqual(len(first['rows']), 6)
        economy = seat_map['cabins'][-1]
        self.assertEqual(len(economy['rows'][0]['blocks']), 3)
        # Rows run globally: 6 first + 14 business + 24 economy, so the last
        # economy row is row 44 and its last block is 3-3-3.
        self.assertEqual(
            [c['seat'] for c in economy['rows'][-1]['blocks'][-1]['cols']],
            ['44G', '44H', '44J'])


class FleetManagementTest(TestCase):
    """The manager adds and removes types from an airline's own fleet."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True)
        self.client.force_login(self.user)
        self.airline, self.types = make_airline('Fleet Air', types=('A320',))
        self.other_type = AircraftType.objects.get(
            manufacturer__name='Boeing', model_name='737-800')

    def test_fleet_page_lists_only_this_airlines_types(self):
        make_airline('Neighbour Air', types=('A321',))
        resp = self.client.get(reverse('airlines:airline_fleet', args=[self.airline.pk]))
        self.assertEqual(resp.status_code, 200)
        listed = {row['entry'].aircraft_type_id for row in resp.context['fleet_entries']}
        self.assertEqual(listed, {self.types['A320'].pk})
        # A321 belongs to the neighbour. It is offered in the "add a type"
        # dropdown as a choice, but it is not one of this airline's rows.
        a321 = AircraftType.objects.get(model_name='A321')
        self.assertNotIn(a321.pk, resp.context['in_fleet_ids'])
        self.assertContains(resp, 'A320')
        # One table row for the one type in the fleet.
        self.assertContains(resp, 'Retire', count=1)

    def test_a_type_can_be_added_to_the_fleet(self):
        resp = self.client.post(
            reverse('airlines:airline_fleet', args=[self.airline.pk]),
            {'action': 'add', 'aircraft_type': self.other_type.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(AirlineFleet.objects.filter(
            airline=self.airline, aircraft_type=self.other_type).exists())

    def test_a_type_outside_the_fleet_cannot_be_added_twice(self):
        AirlineFleet.objects.create(
            airline=self.airline, aircraft_type=self.other_type)
        self.client.post(reverse('airlines:airline_fleet', args=[self.airline.pk]),
                         {'action': 'add', 'aircraft_type': self.other_type.pk})
        self.assertEqual(AirlineFleet.objects.filter(
            airline=self.airline, aircraft_type=self.other_type).count(), 1)

    def test_a_type_can_be_retired_without_deleting_the_aircraft(self):
        """Retiring takes the type out of the dropdowns, not off the aircraft."""
        aircraft = make_aircraft(self.airline, 'A320', 'RP-RET')
        resp = self.client.post(
            reverse('airlines:airline_fleet', args=[self.airline.pk]),
            {'action': 'remove', 'aircraft_type': self.types['A320'].pk})
        self.assertEqual(resp.status_code, 302)
        entry = AirlineFleet.objects.get(
            airline=self.airline, aircraft_type=self.types['A320'])
        self.assertFalse(entry.is_active)
        self.assertTrue(Aircraft.objects.filter(pk=aircraft.pk).exists())
        # Retired types drop out of the API the forms read.
        ids = {r['id'] for r in self.client.get(
            reverse('airlines:fleet_api', args=[self.airline.pk])
        ).json()['aircraft_types']}
        self.assertEqual(ids, set())

    def test_a_retired_type_can_be_put_back(self):
        self.client.post(
            reverse('airlines:airline_fleet', args=[self.airline.pk]),
            {'action': 'remove', 'aircraft_type': self.types['A320'].pk})
        resp = self.client.post(
            reverse('airlines:airline_fleet', args=[self.airline.pk]),
            {'action': 'restore', 'aircraft_type': self.types['A320'].pk})
        self.assertEqual(resp.status_code, 302)
        entry = AirlineFleet.objects.get(
            airline=self.airline, aircraft_type=self.types['A320'])
        self.assertTrue(entry.is_active)

    def test_a_type_still_flying_aircraft_cannot_be_deleted(self):
        make_aircraft(self.airline, 'A320', 'RP-KEEP')
        self.client.post(reverse('airlines:airline_fleet', args=[self.airline.pk]),
                         {'action': 'delete', 'aircraft_type': self.types['A320'].pk})
        self.assertTrue(AirlineFleet.objects.filter(
            airline=self.airline, aircraft_type=self.types['A320']).exists())

    def test_fleet_api_returns_only_this_airlines_types(self):
        make_airline('Neighbour Air', types=('A321',))
        resp = self.client.get(reverse('airlines:fleet_api', args=[self.airline.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['airline']['name'], 'Fleet Air')
        ids = {r['id'] for r in body['aircraft_types']}
        self.assertEqual(ids, {self.types['A320'].pk})
        # The neighbour's A321 is not in this airline's dropdown.
        self.assertNotIn(
            AircraftType.objects.get(model_name='A321').pk, ids)
        # Each entry carries the cabin so the form can show it without a
        # second round trip.
        layout = body['aircraft_types'][0]['seat_layout']
        self.assertEqual(layout['capacity'], 180)
        self.assertEqual(layout['seat_map'], '3-3')


class BookingSeatLayoutTest(TestCase):
    """The booking page draws the flight's real cabin and only sells it."""

    def setUp(self):
        self.airline, _ = make_airline(
            'Emirates PH', types=('A380-800',), primary='A380-800',
            spec='A380_448')
        self.user = get_user_model().objects.create_user(
            username='traveller', password='x', email='t@example.com')
        self.client.force_login(self.user)
        self.flight = Flight.objects.create(
            airline=self.airline, flight_number='EK-301',
            departure_time=timezone.now() + timedelta(days=3),
            arrival_time=timezone.now() + timedelta(days=3, hours=8),
            status='SCHEDULED', economy_fare=30000, first_class_fare=90000,
            business_fare=60000)

    def _book(self, **kw):
        payload = dict(
            trip_type='ONE_WAY', passengers='1', fare_class='ECONOMY',
            primary_seat='40A', travel_document_type='PASSPORT',
            travel_document_number='P1234567', payer_name='Traveller',
            payer_contact='09170000000')
        payload.update(kw)
        return self.client.post(
            reverse('airlines:book', args=[self.flight.pk]), payload)

    def test_booking_page_renders_the_cabin_not_a_synthetic_grid(self):
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'seat-grid')
        self.assertContains(resp, 'Airbus A380-800')
        self.assertContains(resp, 'data-seat="1A"')
        self.assertContains(resp, 'data-seat="40A"')
        self.assertContains(resp, 'First Class')
        self.assertContains(resp, 'Business Class')
        self.assertNotContains(resp, 'name="total_capacity"')

    def test_the_seat_map_has_no_airplane_outline_around_it(self):
        """The seats are the map.  No fuselage border, no nose, no tail cone is
        drawn around them — the grid just sits on the popup's background."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('seat-fuselage', body)

    def test_the_seat_popup_is_pinned_to_the_viewport(self):
        """The popup has to escape the page entrance animation.

        ``.content`` finishes its fade on ``transform: translateY(0)`` and keeps
        that value (``animation-fill-mode: both``).  A transformed ancestor is
        the containing block for ``position: fixed`` descendants, so a popup
        left inside ``.content`` measures itself against the whole page instead
        of the viewport: it drifts down past the booking form and its bottom
        lands below the fold, cutting the seat map in half.  Parking it under
        ``<body>`` restores real viewport-fixed positioning.
        """
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        body = resp.content.decode()
        self.assertIn('function pinModalToViewport()', body)
        self.assertIn('document.body.appendChild(modal)', body)
        # openModal must actually pin it before the popup is shown.
        open_modal = body.split('function openModal()', 1)[1].split('\n}', 1)[0]
        self.assertIn('pinModalToViewport()', open_modal)
        self.assertNotIn('seat-end', body)
        self.assertNotIn('seat-end-nose', body)
        self.assertNotIn('seat-end-cone', body)
        self.assertNotIn('seat-end-cockpit', body)
        self.assertNotIn('seat-end-tail', body)
        # The grid wrapper that replaced the fuselage is still there.
        self.assertIn('class="seat-grid"', body)
        # Nothing was sacrificed to get there: rows, letters, numbers, cabins
        # and the aisle are all still drawn.
        self.assertIn('seat-row-no', body)
        self.assertIn('seat-aisle-gap', body)
        self.assertIn('seat-cabin-deck', body)
        self.assertIn('>A</span>', body)

    def test_the_route_sits_outside_the_scrolling_map_area(self):
        """The route must be a fixed sibling of the seat map.

        It used to be drawn inside the strip that also holds the segment tabs,
        whose ``overflow-y: hidden`` clipped the text to a few pixels.  The route
        is now its own row above the legend, a sibling of ``.seat-modal-body``,
        so the only element that scrolls is the seat map itself.
        """
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        body = resp.content.decode()
        self.assertIn('class="seat-route"', body)
        card = body.split('class="seat-modal-card"', 1)[1]
        route_at = card.index('class="seat-route"')
        body_at = card.index('class="seat-modal-body"')
        legend_at = card.index('class="seat-modal-legend"')
        self.assertLess(route_at, body_at)
        self.assertLess(route_at, legend_at)
        # ...and it is not inside the scrollable body at all.
        self.assertNotIn('class="seat-route"', body.split(
            'class="seat-modal-body"', 1)[1].split('</aside>', 1)[0])

    def test_the_route_shows_each_airport_code_exactly_once(self):
        """No "Manila (MNL) (MNL)".

        ``Flight.origin`` is free text: some rows hold "Manila (MNL)", others just
        "Manila".  The route line therefore reads the code from the airport
        reference and falls back to the raw text only when there is no airport,
        instead of bolting a second "(CODE)" onto text that may already end in one.
        """
        manila = Airport.objects.create(
            airport_name='Ninoy Aquino', iata_code='MNL', city='Manila',
            country='Philippines', status='ACTIVE')
        cebu = Airport.objects.create(
            airport_name='Mactan-Cebu', iata_code='CEB', city='Cebu City',
            country='Philippines', status='ACTIVE')
        self.flight.origin = 'Manila (MNL)'
        self.flight.destination = 'Cebu (CEB)'
        self.flight.origin_airport = manila
        self.flight.destination_airport = cebu
        self.flight.save()
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        route = self._route_of(resp)
        self.assertEqual(route, 'Manila (MNL) \u2192 Cebu City (CEB)')
        self.assertEqual(route.count('(MNL)'), 1)
        self.assertEqual(route.count('(CEB)'), 1)

    def test_the_route_falls_back_to_the_raw_text_without_an_airport(self):
        """A flight with no airport reference still renders one label per end,
        and no code is invented or repeated."""
        self.flight.origin = 'Boracay'
        self.flight.destination = 'Iloilo'
        self.flight.origin_code = 'KLO'
        self.flight.destination_code = 'ILO'
        self.flight.save()
        route = self._route_of(self.client.get(
            reverse('airlines:book', args=[self.flight.pk])))
        self.assertEqual(route, 'Boracay \u2192 Iloilo')
        # Codes that live only on the flight are not invented into the route.
        self.assertNotIn('(KLO)', route)
        self.assertNotIn('(ILO)', route)

    def test_a_route_shorter_than_the_old_fallback_still_reads_once(self):
        """The regression that produced "Manila (MNL) (MNL)": stored text already
        carrying its code, combined with a second code appended to it."""
        self.flight.origin = 'Manila (MNL)'
        self.flight.destination = 'Cebu (CEB)'
        self.flight.origin_airport = Airport.objects.create(
            airport_name='Ninoy Aquino', iata_code='MNL', city='Manila',
            country='Philippines', status='ACTIVE')
        self.flight.destination_airport = Airport.objects.create(
            airport_name='Mactan-Cebu', iata_code='CEB', city='Cebu',
            country='Philippines', status='ACTIVE')
        self.flight.save()
        route = self._route_of(self.client.get(
            reverse('airlines:book', args=[self.flight.pk])))
        self.assertNotIn('(MNL) (MNL)', route)
        self.assertNotIn('(CEB) (CEB)', route)
        self.assertEqual(route.count('(MNL)'), 1)

    def test_the_route_is_not_repeated_by_the_segment_tabs(self):
        """One-way bookings have a single segment, so the switcher has nothing to
        switch between and would only echo the route line above it."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        body = resp.content.decode()
        self.assertNotIn('class="seat-tabs"', body)
        self.assertNotIn('class="seat-tab"', body)
        # The route itself is still there exactly once.
        self.assertEqual(body.count('class="seat-route"'), 1)

    def test_the_segment_tabs_come_back_when_there_is_a_return_flight(self):
        """Two segments means the switcher earns its place again."""
        back = Flight.objects.create(
            airline=self.airline, flight_number='EK-302',
            departure_time=timezone.now() + timedelta(days=6),
            arrival_time=timezone.now() + timedelta(days=6, hours=8),
            status='SCHEDULED', economy_fare=30000,
            first_class_fare=90000, business_fare=60000)
        # The return leg is found through paired_flight, not assigned as a field.
        self.flight.paired_flight = back
        self.flight.save()
        back.trip_role = TripRole.RETURN
        back.save()
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        body = resp.content.decode()
        self.assertIn('class="seat-tabs"', body)
        self.assertEqual(body.count('data-seat-segment='), 2)
        # Still exactly one route line.
        self.assertEqual(body.count('class="seat-route"'), 1)

    def _route_of(self, resp):
        """The rendered text of the route row, whitespace collapsed."""
        m = re.search(r'<div class="seat-route"[^>]*>(.*?)</div>',
                      resp.content.decode(), re.S)
        self.assertIsNotNone(m, 'route row not rendered')
        text = unescape(re.sub(r'<[^>]+>', ' ', m.group(1)))
        return re.sub(r'\s+', ' ', text).strip()

    def test_the_route_row_is_never_clipped_by_a_height(self):
        """The route row is sized by its own line box, not a fixed height.

        A small ``height`` plus the tab strip's ``overflow-y: hidden`` is what
        cut the text in half, so the rule must keep ``height: auto``, a real
        line-height and ``overflow: visible``.
        """
        css = (Path(settings.BASE_DIR) / 'static' / 'css'
               / 'dashboard.css').read_text(encoding='utf-8')
        rule = css.split('.seat-route {', 1)[1].split('\n}', 1)[0]
        self.assertNotIn('height: 20px', rule)
        self.assertNotIn('height: 24px', rule)
        self.assertNotIn('height: 25px', rule)
        self.assertNotIn('overflow: hidden', rule)
        self.assertNotIn('overflow-y: hidden', rule)
        # It must not be allowed to shrink or scroll either.
        self.assertIn('line-height', rule)
        self.assertIn('flex: 0 0 auto', rule)
        # The legend stays a fixed, non-scrolling row below the route.
        legend = css.split('.seat-modal-legend {', 1)[1].split('\n}', 1)[0]
        self.assertIn('flex: 0 0 auto', legend)
        self.assertNotIn('overflow', legend)

    def test_the_cabin_has_no_green_exit_marker_beside_the_seats(self):
        """The cabin drew a green door icon beside every exit row, which read as
        decoration next to the seats rather than as part of the layout.

        The marker is gone. The spacer that held it stays, so the rows keep their
        width and nothing about the seat grid moves.
        """
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        body = resp.content.decode()
        self.assertNotIn('fa-door-open', body)
        self.assertNotIn('Emergency exit row', body)
        # The spacer is still in every row, so the grid cannot reflow.
        seat_map = body.split('class="seat-grid"', 1)[1]
        self.assertEqual(seat_map.count('class="seat-exit"'),
                         seat_map.count('class="seat-row"'))
        # The seats themselves are untouched.
        self.assertIn('data-seat="1A"', body)
        self.assertIn('data-seat="40A"', body)

    def test_the_legend_items_share_one_baseline_and_one_swatch_size(self):
        """Free, Selected and Unavailable are one row.

        Each item is an inline-flex box that centres its swatch and its label, so
        the three share a centre line instead of each being aligned on its own
        ``vertical-align`` nudge.
        """
        css = (Path(settings.BASE_DIR) / 'static' / 'css'
               / 'dashboard.css').read_text(encoding='utf-8')
        legend = css.split('.seat-modal-legend {', 1)[1].split('\n}', 1)[0]
        self.assertIn('display: flex', legend)
        self.assertIn('align-items: center', legend)
        # Items are centred as a unit, so the legend itself cannot scroll away.
        self.assertIn('flex: 0 0 auto', legend)
        item = css.split('.seat-modal-legend > span {', 1)[1].split('\n}', 1)[0]
        self.assertIn('display: inline-flex', item)
        self.assertIn('align-items: center', item)
        # The old per-swatch nudge is gone; centring replaces it.
        swatch = css.split('.seat-modal-legend .seat-swatch {', 1)[1]
        swatch = swatch.split('\n}', 1)[0]
        self.assertNotIn('vertical-align: -', swatch)
        self.assertIn('flex: 0 0 auto', swatch)

    def test_a_cabin_is_drawn_as_rows_across_with_letters_heading_them(self):
        """A cabin reads as a cabin: the seat letters head their own columns,
        and each row lays its seats out sideways across the map rather than
        stacking them into a column."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        seat_map = build_seat_map(self.flight)
        cabins = len(seat_map['cabins'])

        # One deck and one letter-header per cabin, and the header is drawn
        # before any seat, so the letters are column headings.
        self.assertEqual(body.count('class="seat-cabin-deck"'), cabins)
        self.assertEqual(body.count('class="seat-row seat-row-head"'), cabins)
        self.assertLess(body.index('seat-col-label'), body.index('seat-tile'))

        # Every data row is one horizontal run: row number first, then the
        # seats of that row side by side.
        data_rows = body.split('class="seat-row"')[1:]
        self.assertEqual(len(data_rows), sum(len(c['rows']) for c in seat_map['cabins']))
        for row in data_rows:
            row = row[:row.index('</div>')]
            self.assertIn('seat-row-no', row)
            self.assertIn('seat-tile', row)
            # Row number leads, seats follow: a row is never a column.
            self.assertLess(row.index('seat-row-no'), row.index('seat-tile'))
            # Seats are laid out as siblings in one row, in seat order.
            letters = re.findall(r'seat-letter">([A-Z])</span>', row)
            self.assertEqual(letters, sorted(letters, key=lambda v: letters.index(v)))
            self.assertGreater(len(letters), 1)

    def test_the_column_letters_come_from_the_aircraft_configuration(self):
        """The heading over a cabin must be exactly the letters sitting under
        it, split into the same seat groups — taken from the Seat rows, never
        counted in the view.  Verified at the data level and against the HTML
        that is actually rendered, for every cabin on the flight."""
        seat_map = build_seat_map(self.flight)
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()

        expected_labels = 0
        expected_aisles = 0
        for cabin in seat_map['cabins']:
            blocks = cabin['head_blocks']
            expected_aisles += max(len(blocks) - 1, 0)
            for index, block in enumerate(blocks):
                # The heading of a seat group is that group's own letters.
                row_block = cabin['rows'][0]['blocks'][index]
                self.assertEqual(block['labels'],
                                 [col['label'] for col in row_block['cols']])
                self.assertEqual(len(block['labels']), block['width'])
                expected_labels += block['width']
                # Every heading letter has a real, bookable seat under it.
                for col in row_block['cols']:
                    self.assertTrue(col['seat'])
                    self.assertIn(col['seat'], self.flight.seat_layout_record
                                  .seats.values_list('seat_number', flat=True))

        # And the page drew exactly that many headings, and one aisle between
        # each pair of groups.
        self.assertEqual(body.count('seat-col-label'), expected_labels)
        self.assertEqual(body.count('class="seat-row seat-row-head"'),
                         len(seat_map['cabins']))
        # Aisle elements only ever appear inside a row, so the total across the
        # page is one per group boundary, per row.
        aisles_in_rows = sum(
            max(len(row['blocks']) - 1, 0)
            for cabin in seat_map['cabins'] for row in cabin['rows'])
        # Aisle-position *seats* exist too, so count the gap element exactly:
        # it only ever appears between two seat groups, once per boundary.
        self.assertEqual(body.count('class="seat-aisle-gap"'),
                         aisles_in_rows + expected_aisles)
        aisle_seats = sum(
            1 for c in seat_map['cabins'] for r in c['rows']
            for b in r['blocks'] for col in b['cols'] if col['position'] == 'aisle')
        self.assertGreater(aisle_seats, 0, 'fixture has no aisle seats')

    def test_every_cabin_uses_the_same_structure(self):
        """Cabins must not be drawn differently from one another: a widebody's
        first class cannot be a column while its economy runs across."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        decks = body.count('class="seat-cabin-deck"')
        headers = body.count('class="seat-row seat-row-head"')
        rows = body.count('class="seat-row"')
        self.assertEqual(decks, 3)
        self.assertEqual(headers, decks)
        self.assertGreaterEqual(rows, decks)

    def test_every_cabin_section_is_named_with_its_class_and_fare(self):
        """The heading has to say which cabin you are picking in, and what it
        costs — an unlabelled band of seats is how people book the wrong class."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for label in ('First Class', 'Business Class', 'Economy'):
            self.assertIn('seat-cabin-title">%s<' % label, body)
        # A380 flies three cabins; it has no premium economy, so none is shown.
        self.assertNotIn('Premium Economy', body)
        # The fare is filled in, not left blank.
        self.assertNotIn('&#8369;  each', body)
        self.assertIn('seat-cabin-meta', body)

    def test_the_legend_offers_only_the_three_seat_statuses(self):
        """Window / middle / aisle are positions, not statuses; Primary (You) was
        a fourth colour that no longer exists.  Three swatches, nothing more."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        legend = body.split('seat-modal-legend')[1].split('</div>')[0]
        for swatch in ('free', 'picked', 'used'):
            self.assertIn('seat-swatch %s' % swatch, legend)
        self.assertNotIn('seat-swatch primary', legend)
        self.assertNotIn('seat-swatch seat-window', legend)
        self.assertNotIn('seat-swatch seat-middle', legend)
        self.assertNotIn('seat-swatch seat-aisle-seat', legend)
        # Only the three words that describe what a passenger can do.
        self.assertIn('Free', legend)
        self.assertIn('Selected', legend)
        self.assertIn('Unavailable', legend)
        # Taken seats carry an X and stay unselectable; selected seats carry a
        # passenger icon.
        self.assertIn('seat-icon-taken', body)
        self.assertIn('seat-icon-picked', body)
        self.assertIn('fa-times', legend)
        self.assertIn('fa-user', legend)

    def test_the_seat_map_sits_in_a_popup_behind_a_select_seat_button(self):
        """The booking page offers a button, not a cabin: the map is opened in a
        modal so the form behind it is not buried under 59 rows of seats."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The trigger, and its initial wording.
        self.assertIn('id="seat-open"', body)
        self.assertIn('Select Seat', body)
        # A modal with a heading and a close control, hidden until asked for.
        self.assertIn('id="seat-modal"', body)
        self.assertIn('class="seat-modal" id="seat-modal" hidden', body)
        self.assertIn('Seat selection', body)
        self.assertIn('seat-modal-close', body)
        # The cabin lives inside the modal, not loose in the page body.
        self.assertLess(body.index('seat-modal-body'), body.index('seat-grid'))
        self.assertLess(body.index('seat-grid'), body.index('seat-modal-foot'))

    def test_the_popup_opens_by_itself_over_the_booking_form(self):
        """Seat choice is the seat-selection step, so the popup puts itself up,
        centred, instead of waiting to be asked for."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The overlay starts hidden and the script opens it on load.
        self.assertIn('id="seat-modal" hidden', body)
        self.assertIn('openModal();', body)
        self.assertLess(body.index('setSegment(\'departure\');'),
                        body.index('openModal();'))

    def test_the_popup_carries_the_passenger_list_and_the_footer(self):
        """Passengers are chosen before a seat, and the footer reports the
        subtotal and moves on to the next segment."""
        resp = self.client.get(reverse('airlines:book', args=[self.flight.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="seat-pax-list"', body)
        self.assertIn('id="seat-subtotal"', body)
        self.assertIn('id="seat-next"', body)
        # A one-way trip has nothing to switch between, so no segment tabs; the
        # route line above is the only place the route is written.
        self.assertNotIn('class="seat-tabs"', body)
        self.assertNotIn('data-seat-segment="departure"', body)
        self.assertNotIn('data-seat-segment="return"', body)

    def test_a_round_trip_gets_a_tab_per_segment(self):
        """Both legs get their own tab, each with its own aircraft's map, so a
        seat on one leg is never confused with a seat on the other."""
        out = Flight.objects.create(
            airline=self.airline, flight_number='5J200',
            departure_time=timezone.now() + timedelta(days=4),
            arrival_time=timezone.now() + timedelta(days=4, hours=8),
            status='SCHEDULED', economy_fare=30000)
        back = Flight.objects.create(
            airline=self.airline, flight_number='5J201',
            departure_time=timezone.now() + timedelta(days=9),
            arrival_time=timezone.now() + timedelta(days=9, hours=8),
            status='SCHEDULED', economy_fare=30000,
            round_trip_group=out.round_trip_group, paired_flight=out)
        out.round_trip_group = back.round_trip_group
        out.paired_flight = back
        out.save()

        resp = self.client.get(reverse('airlines:book', args=[out.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertEqual(body.count('class="seat-tab"'), 2)
        self.assertIn('data-seat-segment="return"', body)
        # Two independent maps, one per leg.
        self.assertIn('data-seat-panel="departure"', body)
        self.assertIn('data-seat-panel="return"', body)
        # The return panel is rendered but not the one on show.
        self.assertIn('data-seat-panel="return" data-return-panel hidden', body)

    def test_a_cabin_the_aircraft_does_not_fly_cannot_be_booked(self):
        resp = self._book(fare_class='PREMIUM_ECONOMY', primary_seat='40A')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'does not offer that cabin')
        self.assertEqual(Booking.objects.filter(flight=self.flight).count(), 0)

    def test_a_seat_outside_the_layout_is_rejected(self):
        resp = self._book(primary_seat='99Z')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'not on this aircraft')
        self.assertEqual(Booking.objects.filter(flight=self.flight).count(), 0)

    def test_a_business_cabin_seat_is_booked_at_the_business_fare(self):
        resp = self._book(fare_class='BUSINESS', primary_seat='5C')
        self.assertEqual(resp.status_code, 302)
        seat = Booking.BookingSeat.objects.get(booking__flight=self.flight)
        self.assertEqual(seat.seat_number, '5C')
        self.assertEqual(seat.fare_class, 'BUSINESS')

    def test_a_seat_from_another_airlines_layout_cannot_be_booked(self):
        """Seat numbers are only real inside the layout they belong to."""
        other, _ = make_airline('Other Emirates', types=('A320',))
        narrow = Flight.objects.create(
            airline=other, flight_number='EK-302',
            departure_time=timezone.now() + timedelta(days=3),
            arrival_time=timezone.now() + timedelta(days=3, hours=8),
            status='SCHEDULED', economy_fare=30000)
        # Row 44 is a real seat number on the A380 (it has 59 rows) but not on
        # the 30-row narrowbody, so the number alone proves nothing.
        self.assertTrue(Seat.objects.filter(
            seat_layout=self.flight.seat_layout_record, seat_number='44A').exists())
        self.assertFalse(Seat.objects.filter(
            seat_layout=narrow.seat_layout_record, seat_number='44A').exists())
        self.assertFalse(narrow.has_seat('44A'))
        self.assertTrue(self.flight.has_seat('44A'))


class AirportTest(TestCase):
    """The worldwide airport model, its search API and list filtering."""

    def _airport(self, **kw):
        base = dict(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            icao_code='RPLL', city='Manila', country='Philippines',
            country_code='PH', region='National Capital Region',
            latitude=14.5086, longitude=121.0194, status='ACTIVE')
        base.update(kw)
        return Airport.objects.create(**base)

    def test_airport_id_is_zero_padded(self):
        airport = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            icao_code='RPVM', city='Cebu', country='Philippines',
            country_code='PH', status='ACTIVE')
        self.assertTrue(airport.airport_id.startswith('APT-'))
        self.assertRegex(airport.airport_id, r'^APT-\d{5}$')

    def test_code_and_short_label(self):
        airport = self._airport()
        self.assertEqual(airport.code, 'MNL')
        airport.iata_code = ''
        self.assertEqual(airport.code, 'RPLL')
        self.assertIn('Manila, Philippines', airport.short_label)

    def test_api_searches_by_name_city_and_country(self):
        self._airport()
        self._airport(airport_name='Mactan-Cebu International Airport',
                      iata_code='CEB', icao_code='RPVM', city='Cebu')
        self._airport(airport_name='All Nippon Heathrow', iata_code='XXX',
                      icao_code='', city='London', country='United Kingdom',
                      country_code='GB')
        url = reverse('airlines:airports_api')

        resp = self.client.get(url, {'q': 'Ninoy'})
        self.assertEqual(resp.status_code, 200)
        codes = [r['code'] for r in resp.json()['results']]
        self.assertIn('MNL', codes)
        self.assertNotIn('CEB', codes)

        resp = self.client.get(url, {'q': 'Cebu'})
        self.assertTrue(any(r['code'] == 'CEB' for r in resp.json()['results']))

        resp = self.client.get(url, {'q': 'United Kingdom'})
        self.assertTrue(any(r['country'] == 'United Kingdom' for r in resp.json()['results']))

    def test_api_uses_worldwide_geonames_to_match_ascii_city_queries(self):
        from locations.models import CityMunicipality, Country, Province, Region

        brazil = Country.objects.create(
            geoname_id=9100001, code='BR', name='Brazil', asciiname='Brazil',
        )
        region = Region.objects.create(
            geoname_id=9100002, code='27', name='Sao Paulo', country=brazil,
        )
        province = Province.objects.create(
            geoname_id=9100003, code='SP', name='São Paulo',
            asciiname='Sao Paulo', region=region,
        )
        CityMunicipality.objects.create(
            geoname_id=9100004, code='3550308', name='São Paulo',
            asciiname='Sao Paulo', province=province,
        )
        airport = self._airport(
            airport_name='Congonhas Airport', iata_code='CGH', icao_code='SBSP',
            city='São Paulo', country='Brazil', country_code='BR',
            region='Sao Paulo',
        )

        response = self.client.get(reverse('airlines:airports_api'), {'q': 'Sao Paulo'})

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            airport.pk, [result['id'] for result in response.json()['results']],
        )

    def test_api_exact_iata_ranked_first(self):
        self._airport(airport_name='AAA Fake', iata_code='LAX', icao_code='KLAX',
                      city='Los Angeles', country='United States', country_code='US')
        self._airport(airport_name='Los Angeles International Airport',
                      iata_code='LAX2', icao_code='', city='Los Angeles',
                      country='United States', country_code='US')
        resp = self.client.get(reverse('airlines:airports_api'), {'q': 'LAX'})
        results = resp.json()['results']
        self.assertTrue(results)
        self.assertEqual(results[0]['code'], 'LAX')

    def test_api_returns_single_by_id(self):
        airport = self._airport()
        resp = self.client.get(reverse('airlines:airports_api'), {'id': airport.pk})
        results = resp.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], airport.pk)
        self.assertEqual(results[0]['code'], 'MNL')

    def test_api_ignores_inactive_airports(self):
        self._airport(iata_code='OLD1', status='INACTIVE')
        resp = self.client.get(reverse('airlines:airports_api'), {'q': 'OLD1'})
        self.assertEqual(resp.json()['results'], [])

    def test_list_filters_by_airport_ids(self):
        self.airline, self.types = make_airline('Test Air', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-TST')
        mnl = self._airport()
        ceb = self._airport(airport_name='Mactan-Cebu International Airport',
                            iata_code='CEB', icao_code='RPVM', city='Cebu')
        sia = self._airport(airport_name='Singapore Changi Airport', iata_code='SIN',
                            icao_code='WSSS', city='Singapore', country='Singapore',
                            country_code='SG')

        def flight(number, origin, destination):
            Flight.objects.create(
                airline=self.airline, aircraft=self.aircraft, flight_number=number,
                origin_airport=origin, destination_airport=destination,
                departure_time=timezone.now() + timedelta(days=2),
                arrival_time=timezone.now() + timedelta(days=2, hours=2),
                status='SCHEDULED', economy_fare=1500, first_class_fare=3000)

        flight('FL-A', mnl, ceb)
        flight('FL-B', mnl, sia)

        resp = self.client.get(reverse('airlines:list'), {'origin_airport': mnl.pk})
        self.assertEqual({f.flight_number for f in resp.context['flights']}, {'FL-A', 'FL-B'})

        resp = self.client.get(reverse('airlines:list'),
                               {'origin_airport': mnl.pk, 'destination_airport': ceb.pk})
        self.assertEqual({f.flight_number for f in resp.context['flights']}, {'FL-A'})


class NumericFlightNumberSlugTest(TestCase):
    """A flight number that is all digits still has to be reachable.

    Detail pages are addressed by slug, and the slug of flight "098" is "098" —
    which is also a valid legacy primary key.  The slug has to win, otherwise the
    page 404s looking for flight 98 while the real flight sits right there.
    """

    def setUp(self):
        self.airline, _ = make_airline('Numeric Air', types=('A320',))
        self.flight = Flight.objects.create(
            airline=self.airline, flight_number='098',
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=2),
            status='SCHEDULED', economy_fare=1500, first_class_fare=3000)
        # flight_detail is a manager view, so it needs a manager account.
        self.client.force_login(get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True))

    def test_an_all_digit_flight_number_is_reachable_by_its_slug(self):
        self.assertEqual(self.flight.slug, '098')
        resp = self.client.get(reverse('airlines:flight_detail', args=['098']))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['flight'], self.flight)

    def test_the_slug_wins_over_a_legacy_primary_key_link(self):
        """The same key can be a real pk for a different flight; the canonical
        slug still resolves to the row it belongs to."""
        self.assertEqual(get_object_by_slug_or_404(
            Flight.objects.all(), '098'), self.flight)

    def test_legacy_primary_key_links_still_work(self):
        """Old /<id>/ bookmarks keep resolving, which is the whole point of the
        numeric fallback — it just no longer pre-empts a real slug."""
        other = Flight.objects.create(
            airline=self.airline, flight_number='FL-OTHER',
            departure_time=timezone.now() + timedelta(days=3),
            arrival_time=timezone.now() + timedelta(days=3, hours=2),
            status='SCHEDULED', economy_fare=1500, first_class_fare=3000)
        self.assertEqual(
            get_object_by_slug_or_404(Flight.objects.all(), str(other.pk)), other)
        resp = self.client.get(reverse('airlines:flight_detail', args=[other.pk]))
        self.assertEqual(resp.status_code, 200)


class ConnectingItineraryScheduleTest(TestCase):
    """A connecting journey is several real legs sold as one thing.

    Each leg keeps its own ``Flight`` row, aircraft, cabin and seat map, because
    that is what makes a MNL-SIN-DXB ticketable and check-in-able leg by leg.  The
    itinerary is the ordering and the shared fare that ties them together.
    """

    def setUp(self):
        self.airline, _ = make_airline(
            'Cebu Pacific', types=('A320', 'A330-300'),
            spec={'A320': 'NARROW_180', 'A330-300': 'A330_324'})
        self.narrow = make_aircraft(self.airline, 'A320', 'RP-C8899')
        self.wide = make_aircraft(self.airline, 'A330-300', 'RP-C8900')
        # Deliberately different zones: the connection rules have to work on real
        # instants, not on two wall clocks that happen to look compatible.

        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            icao_code='RPLL', city='Manila', country='Philippines',
            status='ACTIVE', timezone='Asia/Manila')
        self.sin = Airport.objects.create(
            airport_name='Changi Airport', iata_code='SIN', icao_code='WSSS',
            city='Singapore', country='Singapore', status='ACTIVE',
            timezone='Asia/Singapore')
        self.dxb = Airport.objects.create(
            airport_name='Dubai International Airport', iata_code='DXB',
            icao_code='OMDB', city='Dubai', country='United Arab Emirates',
            status='ACTIVE', timezone='Asia/Dubai')
        # A fourth airport that is in no chain, so a route gap can be described.
        self.ceb = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            icao_code='RPVM', city='Cebu', country='Philippines',
            status='ACTIVE', timezone='Asia/Manila')
        self.inactive = Airport.objects.create(

            airport_name='Closed Field', iata_code='ZZZ', city='Nowhere',
            country='Philippines', status='INACTIVE', timezone='Asia/Manila')
        self.manager = get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True)
        self.client.force_login(self.manager)

    def _payload(self, **kw):
        base = dict(
            flight_type='CONNECTING', airline=self.airline.pk,
            segment_count='2', status='SCHEDULED', itinerary_status='SCHEDULED',
            booking_available='on', min_connection_minutes='45',
            seg_0_flight_number='5J711',
            seg_0_aircraft=self.narrow.pk,
            seg_0_origin_airport=self.mnl.pk,
            seg_0_destination_airport=self.sin.pk,
            seg_0_departure_date='2027-03-05', seg_0_departure_time='08:00',
            seg_0_arrival_date='2027-03-05', seg_0_arrival_time='11:00',
            seg_0_economy_fare='2600',
            seg_1_flight_number='5J712',
            seg_1_aircraft=self.wide.pk,
            seg_1_origin_airport=self.sin.pk,
            seg_1_destination_airport=self.dxb.pk,
            seg_1_departure_date='2027-03-05', seg_1_departure_time='13:30',
            seg_1_arrival_date='2027-03-05', seg_1_arrival_time='18:00',
            seg_1_economy_fare='2800',
        )
        base.update(kw)
        return base

    def _add(self, **kw):
        return self.client.post(
            reverse('airlines:add_flight_schedule'), self._payload(**kw))

    # ---- creating the journey ------------------------------------------

    def test_a_two_leg_journey_saves_one_itinerary_and_two_legs(self):
        self.assertEqual(self._add().status_code, 302)
        self.assertEqual(FlightItinerary.objects.count(), 1)
        itinerary = FlightItinerary.objects.get()

        self.assertEqual(itinerary.flight_type, FlightItinerary.FlightType.CONNECTING)
        self.assertEqual(itinerary.segment_count, 2)
        self.assertEqual(itinerary.stops, 1)
        self.assertEqual(itinerary.route_label, 'MNL - SIN - DXB')
        legs = itinerary.ordered_legs
        self.assertEqual([leg.segment_order for leg in legs], [1, 2])
        self.assertEqual([leg.flight_number for leg in legs], ['5J711', '5J712'])
        # Each leg is a real schedule with its own airframe and seat map.
        self.assertEqual([leg.aircraft_id for leg in legs],
                         [self.narrow.pk, self.wide.pk])
        self.assertNotEqual(legs[0].seat_layout_record.pk,
                            legs[1].seat_layout_record.pk)


    def test_the_journey_duration_adds_the_layover(self):
        self._add()
        itinerary = FlightItinerary.objects.get()
        # 3h + 2h30m layover + 8h30m = 14h door to door.
        self.assertEqual(itinerary.total_duration_minutes, 14 * 60)
        self.assertEqual(itinerary.total_duration_label, '14h')
        self.assertEqual(itinerary.stops_label, '1 Stop')

    def test_leg_times_are_stored_in_utc_not_wall_clock(self):
        """08:00 in Manila is 00:00 UTC.  Storing the wall clock instead would
        shift every leg by the airport's offset and quietly break every
        duration and connection check downstream."""
        from datetime import timezone as dt_timezone

        self._add()
        legs = FlightItinerary.objects.get().ordered_legs
        self.assertEqual(
            legs[0].departure_time.astimezone(dt_timezone.utc).hour, 0)
        self.assertEqual(legs[0].departure_timezone, 'Asia/Manila')
        self.assertEqual(legs[0].arrival_timezone, 'Asia/Singapore')
        # ...and the leg duration is still the real 3 hours, not 11.
        self.assertEqual(legs[0].segment_duration_minutes, 180)


    def test_each_leg_can_carry_its_own_cabin_fares(self):
        self._add(seg_0_business_fare='9000', seg_1_business_fare='15000')
        legs = FlightItinerary.objects.get().ordered_legs
        self.assertEqual([leg.business_fare for leg in legs],
                         [9000, 15000])
        self.assertEqual([leg.economy_fare for leg in legs], [2600, 2800])

    def test_optional_segment_detail_is_kept(self):
        self._add(seg_0_departure_terminal='3', seg_0_departure_gate='A12',
                  seg_0_baggage_claim='B4', seg_0_check_in_time='06:00',
                  seg_0_boarding_time='07:20', seg_0_checked_baggage_kg='20',
                  seg_1_arrival_gate='D7')
        legs = FlightItinerary.objects.get().ordered_legs
        self.assertEqual(legs[0].terminal, '3')
        self.assertEqual(legs[0].gate, 'A12')
        self.assertEqual(legs[0].baggage_claim, 'B4')
        self.assertEqual(legs[0].check_in_time.strftime('%H:%M'), '06:00')
        self.assertEqual(legs[0].boarding_time.strftime('%H:%M'), '07:20')
        self.assertEqual(legs[0].checked_baggage_kg, 20)
        self.assertEqual(legs[1].arrival_gate, 'D7')

    def test_a_blank_base_fare_falls_back_to_the_sum_of_the_leg_fares(self):
        self._add(base_fare='')
        self.assertEqual(FlightItinerary.objects.get().base_fare, 5400)

    def test_an_explicit_base_fare_is_kept(self):
        self._add(base_fare='5000')
        self.assertEqual(FlightItinerary.objects.get().base_fare, 5000)

    # ---- rules that make it one flyable journey -------------------------

    def test_a_gap_in_the_route_is_rejected(self):
        """MNL->SIN then CEB->DXB is two flights, not a connection: the
        passenger would be stranded in Singapore."""
        self._add(seg_1_origin_airport=self.ceb.pk)
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_1_origin_airport=self.ceb.pk),
                            '')

    def test_a_connection_shorter_than_the_minimum_is_rejected(self):
        self._add(seg_1_departure_time='11:30')  # 30 minutes in Singapore
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_1_departure_time='11:30'),
                            '')

    def test_a_connection_over_the_maximum_is_rejected(self):
        self._add(max_connection_minutes='60', seg_1_departure_date='2027-03-05',
                  seg_1_departure_time='23:00', seg_1_arrival_date='2027-03-06',
                  seg_1_arrival_time='06:00')
        self.assertEqual(FlightItinerary.objects.count(), 0)

    def test_a_leg_departing_before_the_previous_one_arrives_is_rejected(self):
        self._add(seg_1_departure_date='2027-03-04', seg_1_departure_time='13:30',
                  seg_1_arrival_date='2027-03-05', seg_1_arrival_time='18:00')
        self.assertEqual(FlightItinerary.objects.count(), 0)

    def test_a_single_leg_cannot_be_saved_as_a_connecting_journey(self):
        self._add(segment_count='1')
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(segment_count='1'),
                            '')

    def test_more_segments_than_the_cap_is_rejected(self):
        self._add(segment_count='99')
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(segment_count='99'),
                            '')

    def test_a_zero_segment_count_is_rejected(self):
        self._add(segment_count='0')
        self.assertEqual(FlightItinerary.objects.count(), 0)

    def test_a_flight_number_already_in_the_schedule_is_rejected(self):
        Flight.objects.create(
            airline=self.airline, flight_number='5J999',
            origin_airport=self.mnl, destination_airport=self.ceb,
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=2),
            status='SCHEDULED', economy_fare=1000)
        self._add(seg_1_flight_number='5J999')
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_1_flight_number='5J999'),
                       'already exists')

    def test_a_leg_may_not_reuse_a_number_the_journey_already_uses(self):
        """The per-leg check only sees what is already saved, so a number typed
        twice into a brand new journey has to be caught here or it reaches two
        rows - where nobody could tell the segments apart at the gate."""
        self._add(seg_1_flight_number='5J711')
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_1_flight_number='5J711'),
                            '')


    def test_an_inactive_airport_is_rejected(self):
        self._add(seg_1_destination_airport=self.inactive.pk)
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_1_destination_airport=self.inactive.pk),
                            '')

    def test_a_leg_from_and_to_the_same_airport_is_rejected(self):
        self._add(seg_0_destination_airport=self.mnl.pk,
                  seg_1_origin_airport=self.mnl.pk)
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_0_destination_airport=self.mnl.pk,
                                      seg_1_origin_airport=self.mnl.pk),
                            '')

    def test_arriving_before_departing_within_one_leg_is_rejected(self):
        self._add(seg_0_arrival_time='07:00')
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_0_arrival_time='07:00'),
                            '')

    def test_one_aircraft_cannot_fly_two_legs_at_the_same_time(self):
        self._add(seg_1_aircraft=self.narrow.pk,  # same airframe, overlapping
                  seg_1_departure_date='2027-03-05', seg_1_departure_time='09:00',
                  seg_1_arrival_date='2027-03-05', seg_1_arrival_time='12:00')
        self.assertEqual(FlightItinerary.objects.count(), 0)

    def test_an_aircraft_already_scheduled_elsewhere_cannot_be_reused(self):
        other = Airport.objects.create(
            airport_name='Clark', iata_code='CRK', city='Angeles',
            country='Philippines', status='ACTIVE', timezone='Asia/Manila')
        # The clash has to be on the same day as the journey, not just the same
        # relative offset: an airframe next Tuesday is no use to a flight in 2027.
        from airlines.itineraries import combine_local
        Flight.objects.create(
            airline=self.airline, aircraft=self.narrow, flight_number='5J900',
            origin_airport=self.mnl, destination_airport=other,
            departure_time=combine_local(date(2027, 3, 5), time(9, 0),
                                        ZoneInfo('Asia/Manila')),
            arrival_time=combine_local(date(2027, 3, 5), time(12, 0),
                                      ZoneInfo('Asia/Manila')),
            status='SCHEDULED', economy_fare=1000)
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(),
                            '')

    def test_an_aircraft_from_another_airline_is_never_scheduled(self):
        """A forged hidden field must not put a rival's airframe on the leg."""
        rival, _ = make_airline('Rival Air', types=('A320',))
        theirs = make_aircraft(rival, 'A320', 'RP-RIVAL')
        self._add(seg_0_aircraft=theirs.pk)
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(seg_0_aircraft=theirs.pk),
                            '')


    def test_a_minimum_longer_than_the_maximum_is_rejected(self):
        self._add(min_connection_minutes='180', max_connection_minutes='60')
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(min_connection_minutes='180',
                                      max_connection_minutes='60'),
                            '')

    def test_an_airline_without_a_fleet_cannot_take_a_journey(self):
        empty = Airline.objects.create(name='No Fleet Air', status='ACTIVE')
        self._add(airline=empty.pk)
        self.assertEqual(FlightItinerary.objects.count(), 0)
        assertRejected(self, self._add(airline=empty.pk),
                            '')

    def test_no_journey_is_written_when_a_later_leg_is_invalid(self):
        """Leg 1 is fine, leg 2 is not.  Nothing may be left half-saved, or the
        schedule would advertise a connection that cannot be flown."""
        self._add(seg_1_flight_number='')
        self.assertEqual(FlightItinerary.objects.count(), 0)
        self.assertEqual(Flight.objects.count(), 0)

    def test_a_reversed_chain_is_still_a_valid_journey(self):
        """MNL->SIN->MNL is a round trip flown as one chain, so it has to be
        accepted: the continuity and layover rules are what reject a broken
        chain, not the fact that the route doubles back."""
        self._add(seg_1_destination_airport=self.mnl.pk)
        self.assertEqual(FlightItinerary.objects.count(), 1)
        self.assertEqual(FlightItinerary.objects.get().route_label,
                         'MNL - SIN - MNL')



class ConnectingItineraryEditTest(TestCase):
    """Editing a journey reuses its ``Flight`` rows.

    A leg that is deleted and recreated would take its seat bookings with it, so
    a booked journey would silently lose every passenger's seat.
    """

    def setUp(self):
        self.airline, _ = make_airline('Cebu Pacific', types=('A320',))
        self.narrow = make_aircraft(self.airline, 'A320', 'RP-C8899')
        self.wide = make_aircraft(self.airline, 'A320', 'RP-C8900')
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            city='Manila', country='Philippines', status='ACTIVE',
            timezone='Asia/Manila')
        self.sin = Airport.objects.create(
            airport_name='Changi Airport', iata_code='SIN', city='Singapore',
            country='Singapore', status='ACTIVE', timezone='Asia/Singapore')
        self.dxb = Airport.objects.create(
            airport_name='Dubai International Airport', iata_code='DXB',
            city='Dubai', country='United Arab Emirates', status='ACTIVE',
            timezone='Asia/Dubai')
        self.bkk = Airport.objects.create(
            airport_name='Suvarnabhumi', iata_code='BKK', city='Bangkok',
            country='Thailand', status='ACTIVE', timezone='Asia/Bangkok')
        self.client.force_login(get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True))
        self.itinerary = self._create()
        self.legs = self.itinerary.ordered_legs

    def _payload(self, **kw):
        base = dict(
            flight_type='CONNECTING', airline=self.airline.pk,
            segment_count='2', itinerary_status='SCHEDULED', booking_available='on',
            min_connection_minutes='45',
            seg_0_id=str(self.legs[0].pk), seg_0_flight_number='5J711',
            seg_0_aircraft=self.narrow.pk, seg_0_origin_airport=self.mnl.pk,
            seg_0_destination_airport=self.sin.pk,
            seg_0_departure_date='2027-03-05', seg_0_departure_time='08:00',
            seg_0_arrival_date='2027-03-05', seg_0_arrival_time='11:00',
            seg_0_economy_fare='2600',
            seg_1_id=str(self.legs[1].pk), seg_1_flight_number='5J712',
            seg_1_aircraft=self.wide.pk, seg_1_origin_airport=self.sin.pk,
            seg_1_destination_airport=self.dxb.pk,
            seg_1_departure_date='2027-03-05', seg_1_departure_time='13:30',
            seg_1_arrival_date='2027-03-05', seg_1_arrival_time='18:00',
            seg_1_economy_fare='2800',
        )
        base.update(kw)
        return base

    def _create(self):
        payload = dict(
            flight_type='CONNECTING', airline=self.airline.pk,
            segment_count='2', itinerary_status='SCHEDULED', booking_available='on',
            min_connection_minutes='45',
            seg_0_flight_number='5J711', seg_0_aircraft=self.narrow.pk,
            seg_0_origin_airport=self.mnl.pk, seg_0_destination_airport=self.sin.pk,
            seg_0_departure_date='2027-03-05', seg_0_departure_time='08:00',
            seg_0_arrival_date='2027-03-05', seg_0_arrival_time='11:00',
            seg_0_economy_fare='2600',
            seg_1_flight_number='5J712', seg_1_aircraft=self.wide.pk,
            seg_1_origin_airport=self.sin.pk, seg_1_destination_airport=self.dxb.pk,
            seg_1_departure_date='2027-03-05', seg_1_departure_time='13:30',
            seg_1_arrival_date='2027-03-05', seg_1_arrival_time='18:00',
            seg_1_economy_fare='2800')
        self.client.post(reverse('airlines:add_flight_schedule'), payload)
        return FlightItinerary.objects.get()

    def _update(self, **kw):
        return self.client.post(
            reverse('airlines:update_itinerary', args=[self.itinerary.pk]),
            self._payload(**kw))

    def test_editing_a_journey_reuses_the_existing_leg_rows(self):
        original_pks = [leg.pk for leg in self.legs]
        self.assertEqual(self._update().status_code, 302)
        self.assertEqual(FlightItinerary.objects.count(), 1)
        self.assertEqual([leg.pk for leg in self.itinerary.ordered_legs],
                         original_pks)
        self.assertEqual(Flight.objects.count(), 2)

    def test_a_leg_can_be_retimed_without_being_recreated(self):
        original_pks = [leg.pk for leg in self.legs]
        self.assertEqual(self._update(seg_1_departure_time='14:00').status_code, 302)
        self.itinerary.refresh_from_db()
        self.assertEqual([leg.pk for leg in self.itinerary.ordered_legs],
                         original_pks)
        # Pushing the second departure back half an hour lengthens the layover by
        # 30 minutes and shortens the second leg by the same 30, because its
        # arrival still stands, so the journey total is unchanged at 14h - but the
        # cached total has to be recomputed from the legs rather than left sitting
        # on whatever it was when the itinerary was created. The layover moving to
        # 3h is what proves the legs were actually re-read.
        self.assertEqual(self.itinerary.timing['layovers'][0]['label'], '3h')
        self.assertEqual(self.itinerary.timing['legs'][1]['label'], '8h')
        self.assertEqual(self.itinerary.total_duration_minutes, 14 * 60)


    def test_a_third_leg_can_be_appended(self):
        self._update(
            segment_count='3',
            seg_2_flight_number='5J713', seg_2_aircraft=self.narrow.pk,
            seg_2_origin_airport=self.dxb.pk, seg_2_destination_airport=self.bkk.pk,
            seg_2_departure_date='2027-03-05', seg_2_departure_time='21:00',
            seg_2_arrival_date='2027-03-06', seg_2_arrival_time='03:00',
            seg_2_economy_fare='3000')
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.segment_count, 3)
        self.assertEqual(self.itinerary.stops, 2)
        self.assertEqual(self.itinerary.route_label, 'MNL - SIN - DXB - BKK')
        self.assertEqual([leg.flight_number for leg in self.itinerary.ordered_legs],
                         ['5J711', '5J712', '5J713'])
        # The two original rows are still the same rows.
        self.assertEqual([leg.pk for leg in self.itinerary.ordered_legs[:2]],
                         [leg.pk for leg in self.legs])

    def test_dropping_the_third_leg_deletes_it_and_leaves_no_orphan(self):
        """A stranded segment 2 with no segment 1 is not a journey, and it would
        still turn up in search as a separate direct flight."""
        self._update(
            segment_count='3',
            seg_2_flight_number='5J713', seg_2_aircraft=self.narrow.pk,
            seg_2_origin_airport=self.dxb.pk, seg_2_destination_airport=self.bkk.pk,
            seg_2_departure_date='2027-03-05', seg_2_departure_time='21:00',
            seg_2_arrival_date='2027-03-06', seg_2_arrival_time='03:00',
            seg_2_economy_fare='3000')
        kept = [leg.pk for leg in self.itinerary.ordered_legs]
        dropped = kept[2]
        self.assertEqual(self._update(segment_count='2').status_code, 302)
        self.itinerary.refresh_from_db()
        self.assertEqual([leg.pk for leg in self.itinerary.ordered_legs], kept[:2])
        self.assertFalse(Flight.objects.filter(pk=dropped).exists())
        self.assertEqual(Flight.objects.filter(itinerary=self.itinerary).count(), 2)
        self.assertEqual([leg.segment_order for leg in self.itinerary.ordered_legs],
                         [1, 2])

    def test_a_journey_cannot_be_edited_down_to_a_single_leg(self):
        """One segment is a direct flight, which has its own form; silently
        accepting it here would leave a 'connecting' itinerary holding one leg."""
        response = self._update(segment_count='1')
        assertRejected(self, response, 'at least 2')
        self.itinerary.refresh_from_db()
        self.assertEqual(Flight.objects.filter(itinerary=self.itinerary).count(), 2)
        self.assertEqual(self.itinerary.segment_count, 2)

    def test_a_rejected_edit_keeps_the_journey_and_its_timestamps(self):
        before = self.itinerary.total_duration_minutes
        assertRejected(self, self._update(seg_1_departure_time='10:00'),
                       'connection')
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.total_duration_minutes, before)
        self.assertEqual(Flight.objects.count(), 2)


    def test_the_edit_form_offers_the_existing_legs_in_travel_order(self):
        resp = self.client.get(
            reverse('airlines:update_itinerary', args=[self.itinerary.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('data-segment-template', body)
        self.assertIn('"5J711"', body)
        self.assertIn('"5J712"', body)
        # Local wall clocks, not the UTC values in the columns.
        self.assertIn('"departure_time": "08:00"', body)
        self.assertIn('"arrival_time": "18:00"', body)
        self.assertLess(body.index('"5J711"'), body.index('"5J712"'))


class ConnectingItineraryPagesTest(TestCase):

    """The manager and public pages, and the flight page they redirect from."""

    def setUp(self):
        self.airline, _ = make_airline('Cebu Pacific', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-C8899')
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            city='Manila', country='Philippines', status='ACTIVE',
            timezone='Asia/Manila')
        self.sin = Airport.objects.create(
            airport_name='Changi Airport', iata_code='SIN', city='Singapore',
            country='Singapore', status='ACTIVE', timezone='Asia/Singapore')
        self.dxb = Airport.objects.create(
            airport_name='Dubai International Airport', iata_code='DXB',
            city='Dubai', country='United Arab Emirates', status='ACTIVE',
            timezone='Asia/Dubai')
        self.manager = get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True)
        self.traveller = get_user_model().objects.create_user(
            username='traveller', password='x', email='t@example.com')
        self.client.force_login(self.manager)
        self.client.post(
            reverse('airlines:add_flight_schedule'),
            dict(
                flight_type='CONNECTING', airline=self.airline.pk,
                segment_count='2', itinerary_status='SCHEDULED',
                booking_available='on', min_connection_minutes='45',
                seg_0_flight_number='5J711', seg_0_aircraft=self.aircraft.pk,
                seg_0_origin_airport=self.mnl.pk,
                seg_0_destination_airport=self.sin.pk,
                seg_0_departure_date='2027-03-05',
                seg_0_departure_time='08:00',
                seg_0_arrival_date='2027-03-05',
                seg_0_arrival_time='11:00', seg_0_economy_fare='2600',
                seg_1_flight_number='5J712', seg_1_aircraft=self.aircraft.pk,
                seg_1_origin_airport=self.sin.pk,
                seg_1_destination_airport=self.dxb.pk,
                seg_1_departure_date='2027-03-05',
                seg_1_departure_time='13:30',
                seg_1_arrival_date='2027-03-05',
                seg_1_arrival_time='18:00', seg_1_economy_fare='2800'))
        self.itinerary = FlightItinerary.objects.get()

    def test_the_manager_page_shows_the_whole_journey(self):
        resp = self.client.get(
            reverse('airlines:itinerary_detail', args=[self.itinerary.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(self.itinerary.itinerary_reference, body)
        self.assertIn('5J711', body)
        self.assertIn('5J712', body)
        self.assertIn('1 Stop', body)

    def test_a_leg_page_redirects_to_the_journey_not_the_single_leg(self):
        """Opening one leg of a connection and seeing only that leg would invite
        a manager to edit half a journey."""
        leg = self.itinerary.ordered_legs[1]
        resp = self.client.get(reverse('airlines:flight_detail', args=[leg.pk]))
        self.assertRedirects(
            resp, reverse('airlines:itinerary_detail', args=[self.itinerary.pk]))

    def test_the_public_page_needs_a_signed_in_traveller(self):
        self.client.logout()
        resp = self.client.get(
            reverse('airlines:itinerary_public_detail', args=[self.itinerary.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp['Location'])

    def test_the_public_page_shows_both_legs_to_a_traveller(self):
        self.client.force_login(self.traveller)
        resp = self.client.get(
            reverse('airlines:itinerary_public_detail', args=[self.itinerary.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('5J711', body)
        self.assertIn('5J712', body)
        self.assertIn('14h', body)

    def test_a_manager_cannot_be_bought_a_ticket_for_someone_elses_passenger(self):
        """The manager page is not a booking page."""
        self.client.logout()
        resp = self.client.get(
            reverse('airlines:itinerary_public_detail', args=[self.itinerary.pk]),
            follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('/accounts/login/', resp.request['PATH_INFO'])


class ConnectingItineraryFormTest(TestCase):
    """The one form has to serve both shapes without either blocking the other."""

    def setUp(self):
        self.airline, _ = make_airline('Cebu Pacific', types=('A320',))
        self.client.force_login(get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True))

    def test_the_form_offers_all_three_flight_types(self):
        resp = self.client.get(reverse('airlines:add_flight_schedule'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for value in ('DIRECT', 'ROUND_TRIP', 'CONNECTING'):
            self.assertIn('value="%s" data-flight-type' % value, body)

    def test_the_direct_form_is_the_default(self):
        body = self.client.get(
            reverse('airlines:add_flight_schedule')).content.decode()
        self.assertIn('data-direct-section', body)
        self.assertNotIn('data-direct-section hidden', body)
        self.assertIn('data-connecting-section hidden', body)

    def test_the_connecting_form_carries_the_segment_scaffolding(self):
        body = self.client.get(
            reverse('airlines:add_flight_schedule'),
            {'flight_type': 'CONNECTING'}).content.decode()
        self.assertIn('data-segment-template', body)
        self.assertIn('name="segment_count"', body)
        self.assertIn('data-add-segment', body)
        self.assertIn('data-direct-section hidden', body)
        self.assertNotIn('data-connecting-section hidden', body)

    def test_the_airline_picker_is_shared_by_both_forms(self):
        """The operator is chosen before the shape is known, and the connecting
        validator reads it from the same field."""
        for query in ({}, {'flight_type': 'CONNECTING'}):
            body = self.client.get(
                reverse('airlines:add_flight_schedule'), query).content.decode()
            self.assertIn('name="airline"', body)
            self.assertIn('data-airline', body)

    def test_trip_type_is_carried_for_the_direct_validator(self):
        """The direct view still reads trip_type; it is synced from the flight
        type the manager actually picked."""
        body = self.client.get(
            reverse('airlines:add_flight_schedule'),
            {'flight_type': 'CONNECTING'}).content.decode()
        self.assertIn('data-trip-type-sync', body)
        # One Way is the only trip type a connecting chain can be.
        self.assertIn('value="ONE_WAY"', body)
        self.assertNotIn('name="trip_type" value="ONE_WAY"', body)


class ConnectingItinerarySearchTest(TestCase):
    """A journey is searched and sold as one card, not as its legs."""

    def setUp(self):
        self.airline, _ = make_airline('Cebu Pacific', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-C8899')
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            city='Manila', country='Philippines', status='ACTIVE',
            timezone='Asia/Manila')
        self.sin = Airport.objects.create(
            airport_name='Changi Airport', iata_code='SIN', city='Singapore',
            country='Singapore', status='ACTIVE', timezone='Asia/Singapore')
        self.dxb = Airport.objects.create(
            airport_name='Dubai International Airport', iata_code='DXB',
            city='Dubai', country='United Arab Emirates', status='ACTIVE',
            timezone='Asia/Dubai')
        self.ceb = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            city='Cebu', country='Philippines', status='ACTIVE',
            timezone='Asia/Manila')
        self.traveller = get_user_model().objects.create_user(
            username='traveller', password='x', email='t@example.com')
        self.departure = timezone.now() + timedelta(days=30)
        # The schedule is management data, so it is written as a manager first;
        # only the search below is the traveller's.
        self.client.force_login(get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True))
        self.client.post(reverse('airlines:add_flight_schedule'),
            dict(
                flight_type='CONNECTING', airline=self.airline.pk,
                segment_count='2', itinerary_status='SCHEDULED',
                booking_available='on', min_connection_minutes='45',
                seg_0_flight_number='5J711', seg_0_aircraft=self.aircraft.pk,
                seg_0_origin_airport=self.mnl.pk,
                seg_0_destination_airport=self.sin.pk,
                seg_0_departure_date=self.departure.strftime('%Y-%m-%d'),
                seg_0_departure_time='08:00',
                seg_0_arrival_date=self.departure.strftime('%Y-%m-%d'),
                seg_0_arrival_time='11:00', seg_0_economy_fare='2600',
                seg_1_flight_number='5J712', seg_1_aircraft=self.aircraft.pk,
                seg_1_origin_airport=self.sin.pk,
                seg_1_destination_airport=self.dxb.pk,
                seg_1_departure_date=self.departure.strftime('%Y-%m-%d'),
                seg_1_departure_time='13:30',
                seg_1_arrival_date=self.departure.strftime('%Y-%m-%d'),
                seg_1_arrival_time='18:00', seg_1_economy_fare='2800'))
        self.itinerary = FlightItinerary.objects.get()
        self.client.force_login(self.traveller)

    def _search(self, origin, destination, **extra):
        # The live search form is a GET with the airport pickers, so this reads
        # the same page a passenger does rather than a private entry point.
        payload = dict(
            origin_airport=origin.pk, destination_airport=destination.pk,
            departure_date=self.departure.strftime('%Y-%m-%d'),
            trip_type='ONE_WAY')
        payload.update(extra)
        return self.client.get(reverse('airlines:list'), payload)

    def test_searching_the_whole_route_finds_the_journey_once(self):
        resp = self._search(self.mnl, self.dxb)
        self.assertEqual(resp.status_code, 200)
        rows = resp.context['itinerary_rows']
        self.assertEqual([r['itinerary'].pk for r in rows], [self.itinerary.pk])

    def test_search_keeps_passenger_and_cabin_choices_through_booking_link(self):
        fare_class = self.itinerary.ordered_legs[0].cabin_classes[0]
        response = self._search(
            self.mnl, self.dxb, fare_class=fare_class, passengers='3')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['itinerary_rows']), 1)
        row = response.context['itinerary_rows'][0]
        self.assertEqual(
            row['search_fare'],
            sum(leg.fare_for(fare_class) for leg in row['legs']),
        )
        self.assertIn(
            f'fare_class={fare_class}&passengers=3',
            unescape(response.content.decode()),
        )

    def test_a_search_for_only_the_first_leg_does_not_find_the_journey(self):
        """MNL->SIN is a different journey from MNL->DXB.  Selling the whole
        connection to someone who asked for a hop to Singapore would be
        overselling."""
        resp = self._search(self.mnl, self.sin)
        self.assertEqual(list(resp.context['itinerary_rows']), [])
        self.assertEqual(list(resp.context['flights']), [])

    def test_the_journey_legs_do_not_also_appear_as_direct_flights(self):
        """Otherwise the same connection is sold twice, once as a 14h journey
        and once as a 3h hop."""
        resp = self._search(self.mnl, self.dxb)
        direct = list(resp.context['flights'])
        self.assertEqual(direct, [])
        # ...and the journey is still offered, as the one result it is.
        self.assertEqual(len(resp.context['itinerary_rows']), 1)

    def test_the_card_shows_the_journey_duration_and_stops(self):
        body = self._search(self.mnl, self.dxb).content.decode()
        self.assertIn('1 Stop', body)
        self.assertIn('14h', body)

    def test_the_journey_is_one_collapsed_card_with_its_legs_inside(self):
        """A connection is one result the passenger chooses, not two rows they
        have to pick between.  The legs are detail, so they live inside the card
        that is hidden until the journey is expanded."""
        body = self._search(self.mnl, self.dxb).content.decode()
        # Counted on the markup, not on the toggle hook: that name also appears in
        # the page script, so counting it would count the JavaScript too.
        self.assertEqual(body.count('<article class="fcard'), 1)
        self.assertEqual(body.count('<button type="button" class="fcard-summary-toggle"'), 1)
        self.assertEqual(body.count('fcard-leg-no'), 2)


class FlightResultCardTest(TestCase):
    """A search result is one card that opens to show its detail and its fare.

    The result row is a button, not a link: choosing between what a flight
    includes means looking inside it.  Opening the card shows the journey's facts
    and the Select that actually goes to the booking form.  These tests pin that
    contract so a later tweak cannot quietly turn the list back into rows of
    legs, or take the Select away from the card.
    """

    def setUp(self):
        self.airline, _ = make_airline('Cebu Pacific', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-C8899')
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            city='Manila', country='Philippines', status='ACTIVE',
            timezone='Asia/Manila')
        self.ceb = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            city='Cebu', country='Philippines', status='ACTIVE', timezone='Asia/Manila')
        self.traveller = get_user_model().objects.create_user(
            username='traveller', password='x', email='t@example.com')
        self.client.force_login(self.traveller)
        self.depart = timezone.now() + timedelta(days=30)

    def _flight(self, number, fare, minutes, **kw):
        base = dict(
            airline=self.airline, aircraft=self.aircraft,
            flight_number=number, origin_airport=self.mnl,
            destination_airport=self.ceb, origin=self.mnl.city,
            destination=self.ceb.city,
            departure_time=self.depart,
            arrival_time=self.depart + timedelta(minutes=minutes),
            segment_duration_minutes=minutes,
            status='SCHEDULED', economy_fare=fare, first_class_fare=fare * 2)
        base.update(kw)
        return Flight.objects.create(**base)

    def _search(self):
        return self.client.get(reverse('airlines:list'), dict(
            origin_airport=self.mnl.pk, destination_airport=self.ceb.pk,
            departure_date=self.depart.strftime('%Y-%m-%d'),
            trip_type='ONE_WAY'))

    def test_the_head_is_a_button_that_reports_whether_it_is_open(self):
        """The card is a disclosure, so it is a real button and says whether it
        is currently showing its detail."""
        self._flight('5J-1', 1200, 90)
        body = self._search().content.decode()
        self.assertEqual(
            body.count('<button type="button" class="fcard-summary-toggle"'), 1)
        self.assertIn('aria-expanded="false"', body)
        self.assertNotIn('Return flights', body)
        self.assertIn('class="btn btn-brand fcard-select"', body)

    def test_the_detail_is_hidden_until_the_card_is_opened(self):
        """Each result arrives collapsed, or a long list would open as a wall of
        panels and the summaries could not be compared."""
        self._flight('5J-1', 1200, 90)
        self._flight('5J-2', 1500, 100)
        body = self._search().content.decode()
        self.assertEqual(body.count('<article class="fcard'), 2)
        self.assertEqual(body.count('class="fcard-body" hidden'), 2)
        self.assertEqual(body.count('class="fcard-detail-grid"'), 2)

    def test_the_detail_uses_only_available_flight_facts(self):
        """The timeline shows stored airport details and hides unknown facts."""
        self._flight('5J-1', 1200, 90)
        body = self._search().content.decode()
        self.assertIn('Ninoy Aquino International Airport', body)
        self.assertIn('Mactan-Cebu International Airport', body)
        self.assertNotIn('To be assigned', body)
        self.assertNotIn('Checked baggage</small>', body)
        self.assertNotIn('Cabin baggage</small>', body)

    def test_airline_wide_addons_are_not_presented_as_flight_amenities(self):
        """Airline Service rows are optional sale items, not flight-specific amenities."""
        from airlines.models import Service

        self._flight('5J-1', 1200, 90)
        Service.objects.create(airline=self.airline, name='Travel insurance')
        body = self._search().content.decode()
        self.assertNotIn('Available airline services', body)
        self.assertNotIn('Travel insurance', body)

    def test_browser_expands_and_collapses_without_selecting_the_flight(self):
        from playwright.sync_api import sync_playwright

        self._flight('5J-1', 1200, 90)
        flight = Flight.objects.get(flight_number='5J-1')
        body = self._search().content.decode()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_content(body, wait_until='domcontentloaded')
            card = page.locator('.fcard').first
            toggle = card.locator('.fcard-summary-toggle')
            detail = card.locator('.fcard-body')
            self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
            self.assertTrue(detail.is_hidden())
            select = card.locator('.fcard-select')
            self.assertTrue(select.is_visible())
            self.assertIn(reverse('airlines:book', args=[flight.pk]), select.get_attribute('href'))
            toggle.click()
            self.assertEqual(toggle.get_attribute('aria-expanded'), 'true')
            self.assertTrue(detail.is_visible())
            self.assertNotIn('is-selected', card.get_attribute('class'))
            toggle.click()
            self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
            self.assertTrue(detail.is_hidden())
            self.assertNotIn('is-selected', card.get_attribute('class'))
            browser.close()

    def test_select_is_separate_from_the_expand_control_and_leads_to_booking(self):
        """Selection is separate from expanding the card details."""
        flight = self._flight('5J-1', 1200, 90)
        body = self._search().content.decode()
        self.assertEqual(body.count('fcard-select'), 1)
        # The href comes before the class name on the anchor, so read backwards.
        anchor_start = body.rindex('<a ', 0, body.index('fcard-select'))
        anchor = body[anchor_start:body.index('</a>', anchor_start)]
        self.assertIn(reverse('airlines:book', args=[flight.pk]), anchor)

    def test_every_bookable_result_offers_a_select(self):
        for number in ('5J-1', '5J-2', '5J-3'):
            self._flight(number, 1200, 90)
        body = self._search().content.decode()
        self.assertEqual(body.count('<article class="fcard'), 3)
        self.assertEqual(body.count('fcard-select'), 3)

    def test_a_sold_out_result_offers_no_select(self):
        """A full flight cannot be chosen, so its card has nothing to commit to."""
        self._fill_seats(self._flight('5J-FULL', 800, 200, total_capacity=1))
        self._flight('5J-OPEN', 1400, 100)
        body = self._search().content.decode()
        self.assertIn('Sold out', body)
        self.assertEqual(body.count('fcard-select'), 1)

    def test_the_row_shows_the_airline_times_stops_and_price(self):
        flight = self._flight('5J-1', 1200, 90)
        body = self._search().content.decode()
        self.assertIn(self.airline.name, body)
        self.assertIn('5J-1', body)
        self.assertIn('\u20b11200', body)
        self.assertIn('MNL', body)
        self.assertIn('CEB', body)
        self.assertIn('Direct', body)
        # The row prints the local departure time, not the stored UTC value.
        local = timezone.localtime(self.depart)
        self.assertIn(local.strftime('%H:%M'), body)
        self.assertIn('1h 30m', body)
        self.assertIn(f'data-flight-id="flight-{flight.pk}"', body)

    def test_the_cheapest_result_is_badged_cheapest(self):
        cheap = self._flight('5J-CHEAP', 900, 300)
        pricey = self._flight('5J-PRICEY', 3000, 110)
        self._flight('5J-MID', 2000, 120)
        badges = self._search().context['badges']
        self.assertIn('cheapest', badges[cheap.pk])
        self.assertNotIn('cheapest', badges[pricey.pk])

    def test_the_fastest_result_is_badged_best_not_merely_the_cheapest(self):
        """Best means short and good value, so the badge goes to the quickest
        journey rather than to whichever flight happens to be discounted."""
        slow = self._flight('5J-SLOW', 1000, 600)
        fast = self._flight('5J-FAST', 2500, 90)
        badges = self._search().context['badges']
        self.assertIn('best', badges[fast.pk])
        self.assertNotIn('best', badges[slow.pk])
        self.assertIn('cheapest', badges[slow.pk])
        body = self._search().content.decode()
        self.assertIn('>Cheapest<', body)
        self.assertIn('>Best<', body)

    def test_only_one_result_is_badged_both_cheapest_and_best(self):
        only = self._flight('5J-ONLY', 1500, 100)
        flags = self._search().context['badges'][only.pk]
        self.assertEqual(flags, {'cheapest', 'best'})

    def test_a_sold_out_result_is_never_recommended(self):
        """'Cheapest' is an invitation to buy.  Pointing it at a flight with no
        seats left is an advert for something that cannot be bought."""
        empty = self._flight('5J-FULL', 800, 200, total_capacity=1)
        bookable = self._flight('5J-OPEN', 1400, 100)
        self._fill_seats(empty)
        badges = self._search().context['badges']
        self.assertNotIn('cheapest', badges[empty.pk])
        self.assertNotIn('best', badges[empty.pk])
        self.assertIn('cheapest', badges[bookable.pk])
        body = self._search().content.decode()
        self.assertIn('Sold out', body)

    def test_an_airline_logo_is_used_when_one_is_uploaded(self):
        """The reference design leads with the carrier's mark, so it comes from
        the AirlinePhoto already in the database rather than a stock image."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        flight = self._flight('5J-1', 1200, 90)
        AirlinePhoto.objects.create(
            airline=self.airline, is_primary=True,
            image=SimpleUploadedFile('logo.png', b'\x89PNG\r\n\x1a\n' + b'0' * 40,
                                     content_type='image/png'))
        photos = self._search().context['airline_logos']
        self.assertEqual(photos[self.airline.pk].airline, self.airline)
        body = self._search().content.decode()
        self.assertIn('<span class="fcard-logo">', body)
        self.assertNotIn('photo-1436491865332', body)
        self.assertIn(str(flight.pk), body)

    def test_a_flight_without_a_logo_still_renders_a_placeholder(self):
        self._flight('5J-1', 1200, 90)
        body = self._search().content.decode()
        self.assertIn('fas fa-plane', body)
    def _fill_seats(self, flight):
        """Book the flight until its remaining seats are zero.

        The view counts ``Booking.seat_entries`` against capacity and only a
        seat_number is needed for an entry to count, so the test stamps entries
        rather than allocating a whole seat map per instance.
        """
        booking = Booking.objects.create(
            flight=flight, passenger=self.traveller, trip_type='ONE_WAY',
            status='CONFIRMED', booking_reference='SEATFULL')
        for i in range(1, (flight.total_capacity or 1) + 1):
            booking.seat_entries.create(seat_number=f'{i}A')


class ConnectingItineraryBookingTest(TestCase):
    """One purchase, one booking, one seat per passenger per leg."""

    def setUp(self):
        self.airline, _ = make_airline('Cebu Pacific', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-C8899')
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            city='Manila', country='Philippines', status='ACTIVE',
            timezone='Asia/Manila')
        self.sin = Airport.objects.create(
            airport_name='Changi Airport', iata_code='SIN', city='Singapore',
            country='Singapore', status='ACTIVE', timezone='Asia/Singapore')
        self.dxb = Airport.objects.create(
            airport_name='Dubai International Airport', iata_code='DXB',
            city='Dubai', country='United Arab Emirates', status='ACTIVE',
            timezone='Asia/Dubai')
        self.manager = get_user_model().objects.create_user(
            username='boss', password='x', is_staff=True)
        self.traveller = get_user_model().objects.create_user(
            username='traveller', password='x', email='t@example.com')
        self.client.force_login(self.manager)
        departure = timezone.now() + timedelta(days=30)
        self.day = departure.strftime('%Y-%m-%d')
        self.client.post(
            reverse('airlines:add_flight_schedule'),
            dict(
                flight_type='CONNECTING', airline=self.airline.pk,
                segment_count='2', itinerary_status='SCHEDULED',
                booking_available='on', min_connection_minutes='45',
                seg_0_flight_number='5J711', seg_0_aircraft=self.aircraft.pk,
                seg_0_origin_airport=self.mnl.pk,
                seg_0_destination_airport=self.sin.pk,
                seg_0_departure_date=self.day, seg_0_departure_time='08:00',
                seg_0_arrival_date=self.day, seg_0_arrival_time='11:00',
                seg_0_economy_fare='2600',
                seg_1_flight_number='5J712', seg_1_aircraft=self.aircraft.pk,
                seg_1_origin_airport=self.sin.pk,
                seg_1_destination_airport=self.dxb.pk,
                seg_1_departure_date=self.day, seg_1_departure_time='13:30',
                seg_1_arrival_date=self.day, seg_1_arrival_time='18:00',
                seg_1_economy_fare='2800', service_fee='150'))
        self.itinerary = FlightItinerary.objects.get()
        self.legs = self.itinerary.ordered_legs
        self.client.force_login(self.traveller)

    def _book(self, **kw):
        payload = dict(
            itinerary=self.itinerary.pk, trip_type='ONE_WAY',
            passengers_name='Eula Espiritu', passengers_contact='09170000000',
            travel_document_type='PASSPORT',
            travel_document_number='P1234567', payment_method='GCASH',
            seg_0_primary_seat='1A', seg_0_seat_numbers='1A|1B',
            seg_1_primary_seat='1A', seg_1_seat_numbers='1A|1B',
            extra_baggage='0', extra_baggage_kg='0')
        payload.update(kw)
        return self.client.post(
            reverse('airlines:book_itinerary', args=[self.itinerary.pk]), payload)

    def test_one_purchase_makes_one_booking_not_one_per_leg(self):
        self.assertEqual(self._book().status_code, 302)
        self.assertEqual(Booking.objects.filter(itinerary=self.itinerary).count(), 1)

    def test_each_passenger_gets_a_seat_on_every_leg(self):
        self._book()
        booking = Booking.objects.get(itinerary=self.itinerary)
        self.assertEqual(booking.seat_entries.count(), 4)
        self.assertEqual(
            sorted(booking.seat_entries.values_list(
                'segment_order', 'seat_number')),
            [(1, '1A'), (1, '1B'), (2, '1A'), (2, '1B')])

    def test_the_booking_is_attached_to_the_first_leg_and_the_journey(self):
        """Legacy booking screens read ``flight``, so it points at the leg the
        passenger boards first, while ``itinerary`` carries the whole chain."""
        self._book()
        booking = Booking.objects.get(itinerary=self.itinerary)
        self.assertEqual(booking.flight_id, self.legs[0].pk)
        self.assertEqual(booking.itinerary_id, self.itinerary.pk)

    def test_the_passenger_count_is_travellers_not_seat_rows(self):
        """Two passengers on two legs is four seat rows but two people."""
        self._book()
        booking = Booking.objects.get(itinerary=self.itinerary)
        self.assertEqual(booking.seat_entries.count(), 4)
        self.assertEqual(booking.passengers_count, 2)

    def test_a_seat_already_taken_on_the_second_leg_blocks_the_booking(self):
        """A seat free on leg 1 but gone on leg 2 is not a saleable seat: the
        passenger would be bumped in Singapore."""
        BookingSeat = Booking.BookingSeat
        other = Booking.objects.create(
            passenger=self.traveller, flight=self.legs[1],
            trip_type=Booking.TripType.ONE_WAY, status=Booking.Status.CONFIRMED)
        BookingSeat.objects.create(
            booking=other, flight=self.legs[1], segment_order=2,
            passenger_name='Someone Else', seat_number='1A',
            fare_class='ECONOMY')
        self._book()
        self.assertEqual(
            Booking.objects.filter(itinerary=self.itinerary).count(), 0)

    def test_a_seat_free_on_every_leg_is_sold_to_both_travellers(self):
        self._book(seg_0_seat_numbers='1A|1B', seg_1_seat_numbers='1A|1B')
        booking = Booking.objects.get(itinerary=self.itinerary)
        # Two travellers, two seats, on both legs: four seat rows, not four
        # bookings and not a refusal because the seat numbers repeat per leg.
        self.assertEqual(
            sorted(booking.seat_entries.values_list('segment_order', 'seat_number')),
            [(1, '1A'), (1, '1B'), (2, '1A'), (2, '1B')])
        self.assertEqual(booking.passengers_count, 2)

    def test_the_journey_bill_covers_every_leg(self):
        from django.contrib.contenttypes.models import ContentType
        from transactions.models import Bill
        self._book()
        booking = Booking.objects.get(itinerary=self.itinerary)
        # Bill.booking is a generic relation, so it is looked up by type + id.
        bill = Bill.objects.get(content_type=ContentType.objects.get_for_model(Booking),
                                object_id=booking.pk)
        labels = ' '.join(str(item.get('label', '')) for item in bill.items)
        self.assertIn('5J711', labels)
        self.assertIn('5J712', labels)

    def test_the_booking_page_offers_a_picker_for_every_leg(self):
        resp = self.client.get(
            reverse('airlines:book_itinerary', args=[self.itinerary.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('seg_0_primary_seat', body)
        self.assertIn('seg_1_primary_seat', body)
        self.assertIn('5J711', body)
        self.assertIn('5J712', body)

    def test_the_booking_page_drives_every_leg_from_the_server_index_list(self):
        """The seat picker is driven by JS built from segment_rows.

        A malformed Django tag here renders a broken array such as
        ``[0, {1{]``, which leaves the page loading but silently doing nothing.
        Asserting the exact literals keeps that from passing unnoticed.
        """
        resp = self.client.get(
            reverse('airlines:book_itinerary', args=[self.itinerary.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('var SEGMENTS = [0, 1];', body)
        self.assertIn('var SEGMENT_ORDERS = [1, 2];', body)
        # One hidden full-party seat list per leg, keyed by the same index.
        self.assertIn('name="seg_0_seat_numbers"', body)
        self.assertIn('name="seg_1_seat_numbers"', body)

    def test_the_seat_popup_is_pinned_to_the_viewport(self):
        """The connecting popup escapes .content for the same reason the direct
        one does: a transformed ancestor is the containing block for
        position:fixed, which would size the popup against the page and push the
        seat map below the fold."""
        resp = self.client.get(
            reverse('airlines:book_itinerary', args=[self.itinerary.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('function pinModalToViewport()', body)
        self.assertIn('document.body.appendChild(modal)', body)
        open_modal = body.split('function openModal()', 1)[1].split('\n}', 1)[0]
        self.assertIn('pinModalToViewport()', open_modal)

    def test_the_route_of_a_journey_sits_outside_the_scrolling_map_area(self):
        """Every leg is named in a fixed route row above the legend, never
        inside the strip whose overflow clipped the direct page's route."""
        resp = self.client.get(
            reverse('airlines:book_itinerary', args=[self.itinerary.pk]))
        body = resp.content.decode()
        self.assertIn('class="seat-route"', body)
        card = body.split('class="seat-modal-card"', 1)[1]
        self.assertLess(card.index('class="seat-route"'),
                        card.index('class="seat-modal-body"'))
        self.assertNotIn('class="seat-route"', body.split(
            'class="seat-modal-body"', 1)[1].split('</aside>', 1)[0])

    def test_a_journey_route_names_every_leg_without_repeating_a_code(self):
        """One row for the whole journey, first end once and last end once.

        The old per-leg loop appended each leg's own code, which both repeated
        the middle airports and doubled the code wherever the stored text already
        ended in one.
        """
        resp = self.client.get(
            reverse('airlines:book_itinerary', args=[self.itinerary.pk]))
        body = resp.content.decode()
        self.assertEqual(body.count('class="seat-route"'), 1)
        row = re.search(r'<div class="seat-route"[^>]*>(.*?)</div>', body, re.S)
        text = re.sub(r'\s+', ' ', unescape(
            re.sub(r'<[^>]+>', ' ', row.group(1)))).strip()
        codes = re.findall(r'\(([A-Z]{3})\)', text)
# One arrow per leg, and the codes are distinct because each airport is
        # named exactly once: MNL → SIN → DXB for a two-leg journey.
        self.assertEqual(text.count('→'), self.itinerary.legs.count())
        self.assertEqual(len(codes), self.itinerary.legs.count() + 1)
        self.assertEqual(len(codes), len(set(codes)), text)
        self.itinerary.status = Flight.Status.CANCELLED
        self.itinerary.save()
        self.assertEqual(Booking.objects.filter(itinerary=self.itinerary).count(), 0)

    def test_a_journey_with_booking_closed_cannot_be_booked(self):
        self.itinerary.booking_available = False
        self.itinerary.save()
        self.assertEqual(Booking.objects.filter(itinerary=self.itinerary).count(), 0)

    def test_a_manager_cannot_book_on_a_travellers_behalf(self):
        """Booking is for the traveller; the manager schedules, the traveller
        pays."""
        self.client.force_login(self.manager)
        self.assertEqual(Booking.objects.filter(itinerary=self.itinerary).count(), 0)


class ConnectingItineraryTicketTest(TestCase):
    """The e-ticket is built from the shared context both renderers read."""

    def setUp(self):
        from airlines.ticket import build_ticket_context

        self.build = build_ticket_context
        self.airline, _ = make_airline('Cebu Pacific', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-C8899')
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            city='Manila', country='Philippines', status='ACTIVE',
            timezone='Asia/Manila')
        self.sin = Airport.objects.create(
            airport_name='Changi Airport', iata_code='SIN', city='Singapore',
            country='Singapore', status='ACTIVE', timezone='Asia/Singapore')
        self.dxb = Airport.objects.create(
            airport_name='Dubai International Airport', iata_code='DXB',
            city='Dubai', country='United Arab Emirates', status='ACTIVE',
            timezone='Asia/Dubai')
        self.traveller = get_user_model().objects.create_user(
            username='traveller', password='x', email='t@example.com')
        departure = timezone.now() + timedelta(days=30)
        self.day = departure.strftime('%Y-%m-%d')
        self.itinerary = FlightItinerary.objects.create(
            airline=self.airline, flight_type='CONNECTING',
            trip_type='ONE_WAY', status='SCHEDULED', booking_available=True,
            base_fare=5400, service_fee=150)
        self.legs = []
        day = date.fromisoformat(self.day)
        for order, (number, origin, destination, depart, arrive, fare) in enumerate((
                ('5J711', self.mnl, self.sin, '08:00', '11:00', 2600),
                ('5J712', self.sin, self.dxb, '13:30', '18:00', 2800)), start=1):
            # Built exactly as the schedule form builds them: the wall clock is
            # read in each airport's own zone, not the platform's.
            self.legs.append(Flight.objects.create(
                airline=self.airline, itinerary=self.itinerary,
                segment_order=order, flight_number=number,
                aircraft=self.aircraft, origin_airport=origin,
                destination_airport=destination,
                departure_timezone=origin.timezone_name,
                arrival_timezone=destination.timezone_name,
                departure_time=combine_local(
                    day, parse_clock(depart), airport_timezone(origin)),
                arrival_time=combine_local(
                    day, parse_clock(arrive), airport_timezone(destination)),
                economy_fare=fare, status='SCHEDULED'))
        self.itinerary.refresh_timing()
        self.itinerary.save()
        self.booking = Booking.objects.create(
            passenger=self.traveller, flight=self.legs[0],
            itinerary=self.itinerary, trip_type=Booking.TripType.ONE_WAY,
            status=Booking.Status.CONFIRMED)
        for order, leg in enumerate(self.legs, start=1):
            for name, seat in (('Eula Espiritu', '1A'), ('Second Pax', '1B')):
                Booking.BookingSeat.objects.create(
                    booking=self.booking, flight=leg, segment_order=order,
                    passenger_name=name, seat_number=seat, fare_class='ECONOMY')

    def test_the_ticket_lists_every_leg(self):
        ctx = self.build(self.booking)
        self.assertTrue(ctx['is_itinerary'])
        self.assertEqual([s['flight_number'] for s in ctx['segments']],
                         ['5J711', '5J712'])

    def test_the_ticket_shows_each_leg_in_its_own_local_time(self):
        """A ticket that says the Dubai flight lands at 14:00 when the airport
        clock says 18:00 is worse than no ticket at all."""
        ctx = self.build(self.booking)
        first, second = ctx['segments']
        # Zero-padded 12-hour clocks, exactly as the direct ticket prints them.
        self.assertEqual(first['departure_time'], '08:00 AM')
        self.assertEqual(second['arrival_time'], '06:00 PM')

    def test_the_ticket_collapses_seat_rows_to_one_row_per_traveller(self):
        """Four seat rows are two people, and a ticket listing a person twice
        would look like a double booking."""
        ctx = self.build(self.booking)
        self.assertEqual(ctx['passenger_count'], 2)
        self.assertEqual(len(ctx['passengers']), 2)
        self.assertEqual([p['name'] for p in ctx['passengers']],
                         ['Eula Espiritu', 'Second Pax'])

    def test_each_traveller_shows_their_seat_on_every_leg(self):
        ctx = self.build(self.booking)
        self.assertEqual(ctx['passengers'][0]['seats'], {1: '1A', 2: '1A'})
        self.assertEqual(ctx['passengers'][1]['seats'], {1: '1B', 2: '1B'})

    def test_the_ticket_states_the_whole_journey_duration(self):
        ctx = self.build(self.booking)
        self.assertEqual(ctx['itinerary']['total_duration'], '14h')
        self.assertEqual(ctx['itinerary']['route'], 'MNL - SIN - DXB')

    def test_connecting_itinerary_ticket_page_renders(self):
        self.client.force_login(self.traveller)

        response = self.client.get(
            reverse('airlines:ticket', args=[self.booking.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '06:00 PM')
        self.assertContains(response, '<h3>Cebu Pacific</h3>')
        self.assertNotContains(response, 'Operated by ATRUE')

    def test_a_direct_booking_ticket_is_unchanged(self):
        """The connecting work must not leak into the direct ticket."""
        # The legs are protected while a booking holds them, so the journey
        # booking is released first.
        self.booking.delete()
        Flight.objects.filter(pk__in=[leg.pk for leg in self.legs]).delete()
        direct = Flight.objects.create(
            airline=self.airline, flight_number='5J800',
            aircraft=self.aircraft, origin_airport=self.mnl,
            destination_airport=self.sin,
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=3),
            economy_fare=2600, status='SCHEDULED')
        booking = Booking.objects.create(
            passenger=self.traveller, flight=direct,
            trip_type=Booking.TripType.ONE_WAY, status=Booking.Status.CONFIRMED)
        Booking.BookingSeat.objects.create(
            booking=booking, passenger_name='Eula Espiritu', seat_number='1A',
            fare_class='ECONOMY')
        ctx = self.build(booking)
        self.assertFalse(ctx['is_itinerary'])
        self.assertEqual(ctx['segments'], [])
        self.assertEqual(ctx['passengers'][0]['seat'], '1A')
        self.assertEqual(ctx['passengers'][0].get('seat_summary'), None)


class RoundTripEticketTest(TestCase):
    """Round-trip itinerary and PDF use the actual two flight records."""

    def setUp(self):
        from airlines.ticket import build_ticket_context

        self.build = build_ticket_context
        self.airline, _ = make_airline('ATRUE Test Air', types=('A320',))
        self.aircraft = make_aircraft(self.airline, 'A320', 'RP-ETI-TST')
        self.mnl = Airport.objects.create(
            airport_name='Ninoy Aquino International Airport', iata_code='MNL',
            city='Manila', country='Philippines', status='ACTIVE', timezone='Asia/Manila')
        self.ceb = Airport.objects.create(
            airport_name='Mactan-Cebu International Airport', iata_code='CEB',
            city='Cebu', country='Philippines', status='ACTIVE', timezone='Asia/Manila')
        self.traveller = get_user_model().objects.create_user(
            username='roundtrip-traveller', password='x', email='roundtrip@example.com')
        depart = timezone.now() + timedelta(days=30)
        ret = depart + timedelta(days=4)
        self.outbound = Flight.objects.create(
            airline=self.airline, aircraft=self.aircraft, flight_number='ATR801',
            origin='Manila', destination='Cebu', origin_airport=self.mnl,
            destination_airport=self.ceb, departure_time=depart,
            arrival_time=depart + timedelta(hours=1, minutes=25),
            status='SCHEDULED', economy_fare=2500)
        self.return_flight = Flight.objects.create(
            airline=self.airline, aircraft=self.aircraft, flight_number='ATR802',
            origin='Cebu', destination='Manila', origin_airport=self.ceb,
            destination_airport=self.mnl, departure_time=ret,
            arrival_time=ret + timedelta(hours=1, minutes=25),
            status='SCHEDULED', economy_fare=2500)
        self.booking = Booking.objects.create(
            passenger=self.traveller, flight=self.outbound,
            return_flight=self.return_flight, trip_type=Booking.TripType.ROUND_TRIP,
            status=Booking.Status.CONFIRMED)
        for name, seat in (('Jamie Cruz', '12A'), ('Taylor Reyes', '12B')):
            Booking.BookingSeat.objects.create(
                booking=self.booking, passenger_name=name, seat_number=seat,
                fare_class='ECONOMY', segment=TripSegment.DEPARTURE)
            Booking.BookingSeat.objects.create(
                booking=self.booking, passenger_name=name, seat_number=seat,
                fare_class='ECONOMY', segment=TripSegment.RETURN)

    def test_round_trip_and_multiple_passengers_are_rendered_from_booking_data(self):
        context = self.build(self.booking)

        self.assertEqual(context['passenger_count'], 2)
        self.assertEqual(context['return_flight']['number'], 'ATR802')
        self.assertEqual([p['return_seat'] for p in context['passengers']], ['12A', '12B'])
        self.assertFalse(context['booking_info']['airline_pnr'])
        self.assertTrue(all(not p['ticket_number'] for p in context['passengers']))

        self.client.force_login(self.traveller)
        page = self.client.get(reverse('airlines:ticket', args=[self.booking.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Outbound Flight')
        self.assertContains(page, 'Return Flight')
        self.assertContains(page, 'ATR802')
        self.assertContains(page, 'Not available')
        self.assertNotContains(page, 'TICKET NO.')

    def test_landscape_pdf_download_renders(self):
        self.client.force_login(self.traveller)
        response = self.client.get(reverse('airlines:ticket_pdf', args=[self.booking.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(b'%PDF-', response.content[:8])
        self.assertIn(b'attachment;', response['Content-Disposition'].encode())


class ItineraryTimingTest(TestCase):
    """The timezone maths the whole feature rests on.

    A connecting journey is measured between airports in different time zones, so
    "3 hours" has to mean three real hours rather than three wall-clock hours.
    """

    def _flight(self, number, origin, destination, depart, arrive):
        return Flight.objects.create(
            airline=origin.aircraft.airline, flight_number=number,
            aircraft=origin.aircraft, origin_airport=origin.origin_airport,
            destination_airport=origin.destination_airport,
            departure_timezone=origin.departure_timezone,
            arrival_timezone=origin.arrival_timezone,
            departure_time=depart, arrival_time=arrive, economy_fare=1000,
            status='SCHEDULED')

    def setUp(self):
        from datetime import datetime

        from airlines.itineraries import (combine_local, format_duration,
                                          itinerary_timing, layover_minutes,
                                          segment_duration_minutes)

        self.combine = combine_local
        self.timing = itinerary_timing
        self.layover = layover_minutes
        self.segment = segment_duration_minutes
        self.fmt = format_duration
        self.dt = datetime

    def test_a_leg_across_timezones_is_measured_in_real_hours(self):
        from zoneinfo import ZoneInfo
        manila = ZoneInfo('Asia/Manila')   # UTC+8
        dubai = ZoneInfo('Asia/Dubai')     # UTC+4, four hours behind
        departure = self.dt(2027, 3, 5, 8, 0, tzinfo=manila)
        arrival = self.dt(2027, 3, 5, 12, 0, tzinfo=dubai)
        # 08:00 Manila is 00:00 UTC and 12:00 Dubai is 08:00 UTC, so the aircraft
        # is airborne for eight hours even though the two clocks only appear four
        # hours apart. Subtracting the wall clocks would halve every long leg.
        self.assertEqual(
            self.segment(departure, arrival, manila, dubai), 8 * 60)

    def test_a_connection_across_timezones_is_measured_in_real_minutes(self):
        from zoneinfo import ZoneInfo
        singapore = ZoneInfo('Asia/Singapore')  # same offset as Manila
        dubai = ZoneInfo('Asia/Dubai')          # 4 hours behind
        arrival = self.dt(2027, 3, 5, 11, 0, tzinfo=singapore)
        departure = self.dt(2027, 3, 5, 13, 30, tzinfo=singapore)
        self.assertEqual(self.layover(arrival, departure, singapore, singapore), 150)
        # The same two instants written in the arrival airport's zone: 15:00 to
        # 17:30 in Dubai is still 2h30m, so the answer cannot depend on which
        # zone the layover is read in.
        self.assertEqual(
            self.layover(self.dt(2027, 3, 5, 15, 0, tzinfo=dubai),
                         self.dt(2027, 3, 5, 17, 30, tzinfo=dubai),
                         dubai, dubai), 150)

    def test_a_leg_crossing_midnight_keeps_the_right_date(self):
        from zoneinfo import ZoneInfo
        tokyo = ZoneInfo('Asia/Tokyo')            # UTC+9
        honolulu = ZoneInfo('Pacific/Honolulu')   # UTC-10, nineteen hours behind
        departure = self.dt(2027, 3, 5, 10, 0, tzinfo=tokyo)
        arrival = self.dt(2027, 3, 5, 6, 0, tzinfo=honolulu)
        # 10:00 Tokyo is 01:00 UTC and 06:00 Honolulu is 16:00 UTC the same day:
        # fifteen hours airborne, landing on the calendar date it actually is in
        # Hawaii rather than the one it left the Philippines on.
        self.assertEqual(
            self.segment(departure, arrival, tokyo, honolulu), 15 * 60)

    def test_an_aware_value_is_converted_into_the_legs_own_zone(self):
        """The stored value is UTC.  Reading it back as UTC would print a
        Manila 08:00 departure as 00:00 and a Dubai landing four hours early."""
        from zoneinfo import ZoneInfo
        from django.utils import timezone as dj_timezone
        from airlines.itineraries import _local

        flight = Flight(
            departure_time=dj_timezone.now(),
            departure_timezone='Asia/Manila', arrival_timezone='Asia/Dubai')
        local = _local(flight, 'departure_time', 'departure_timezone')
        # A ZoneInfo's offset is only knowable at a date, so compare the local
        # reading's own offset against the expected one on the same day.
        self.assertEqual(local.utcoffset(),
                         ZoneInfo('Asia/Manila').utcoffset(local.replace(tzinfo=None)))
        self.assertEqual(local.utcoffset().total_seconds() / 3600, 8)

    def test_an_aware_value_is_not_handed_back_as_utc(self):
        from django.utils import timezone as dj_timezone
        from airlines.itineraries import _local

        stored = dj_timezone.now()
        flight = Flight(departure_time=stored, departure_timezone='Asia/Dubai',
                        arrival_timezone='Asia/Dubai')
        local = _local(flight, 'departure_time', 'departure_timezone')
        # Same instant...
        self.assertEqual(local, stored)
        # ...different wall clock, which is the whole point.
        self.assertNotEqual(local.hour, stored.hour)
        self.assertEqual(local.utcoffset().total_seconds() / 3600, 4)

    def test_a_naive_value_is_pinned_to_the_legs_zone(self):
        from zoneinfo import ZoneInfo
        from airlines.itineraries import _local

        flight = Flight(
            departure_time=self.dt(2027, 3, 5, 8, 0),
            departure_timezone='Asia/Manila', arrival_timezone='Asia/Dubai')
        local = _local(flight, 'departure_time', 'departure_timezone')
        self.assertEqual(local.tzinfo, ZoneInfo('Asia/Manila'))
        self.assertEqual(local.hour, 8)

    def test_a_missing_timezone_falls_back_to_the_default_zone(self):
        from zoneinfo import ZoneInfo
        from airlines.itineraries import DEFAULT_TIMEZONE_FALLBACK, _local

        flight = Flight(departure_time=self.dt(2027, 3, 5, 8, 0),
                        departure_timezone='', arrival_timezone='')
        local = _local(flight, 'departure_time', 'departure_timezone')
        self.assertEqual(local.utcoffset(),
                         ZoneInfo(DEFAULT_TIMEZONE_FALLBACK).utcoffset(
                             local.replace(tzinfo=None)))
        self.assertEqual(local.utcoffset().total_seconds() / 3600, 8)

    def test_durations_are_written_in_a_readable_shape(self):
        self.assertEqual(self.fmt(45), '45m')
        self.assertEqual(self.fmt(60), '1h')
        self.assertEqual(self.fmt(90), '1h 30m')
        self.assertEqual(self.fmt(150), '2h 30m')
        self.assertEqual(self.fmt(1440), '24h')

    def test_a_backwards_leg_has_no_duration(self):
        from zoneinfo import ZoneInfo
        zone = ZoneInfo('Asia/Manila')
        self.assertIsNone(
            self.segment(self.dt(2027, 3, 5, 12, 0, tzinfo=zone),
                         self.dt(2027, 3, 5, 8, 0, tzinfo=zone), zone, zone))


class ReservationAgentBookingAccessTests(TestCase):

    def setUp(self):
        from establishments.models import establishment_for_instance
        from simulation.models import SimulationRoleAssignment

        User = get_user_model()
        self.agent = User.objects.create_user(
            username='reservation-agent', password='x', account_type='STUDENT')
        self.passenger = User.objects.create_user(
            username='booking-passenger', password='x',
            account_type='STUDENT', email='passenger@example.com')
        self.airline, _ = make_airline('Assigned Air', types=('A320',))
        self.other_airline, _ = make_airline('Other Air', types=('A320',))
        self.establishment = establishment_for_instance(
            self.airline, create=True, defaults={'status': 'ACTIVE'})
        SimulationRoleAssignment.objects.create(
            student=self.agent, role='AIRLINE_RESERVATION_AGENT',
            activity_name='Reservation Practice',
            establishment=self.establishment)
        departure = timezone.now() + timedelta(days=5)
        self.flight = Flight.objects.create(
            airline=self.airline, flight_number='AS-101',
            origin='Manila', destination='Cebu',
            departure_time=departure, arrival_time=departure + timedelta(hours=1),
            status='SCHEDULED', economy_fare=1500)
        self.other_flight = Flight.objects.create(
            airline=self.other_airline, flight_number='OA-101',
            origin='Manila', destination='Cebu',
            departure_time=departure, arrival_time=departure + timedelta(hours=1),
            status='SCHEDULED', economy_fare=1500)
        self.booking = Booking.objects.create(
            passenger=self.passenger, flight=self.flight,
            status=Booking.Status.PENDING)
        self.other_booking = Booking.objects.create(
            passenger=self.passenger, flight=self.other_flight,
            status=Booking.Status.PENDING)
        self.client.force_login(self.agent)

    def test_booking_list_and_flight_filter_only_show_the_assigned_airline(self):
        response = self.client.get(reverse('airlines:bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['bookings'].values_list('pk', flat=True)),
            [self.booking.pk])
        self.assertEqual(
            list(response.context['flights'].values_list('pk', flat=True)),
            [self.flight.pk])
        widened_response = self.client.get(
            reverse('airlines:bookings'),
            {'flight': self.other_flight.pk},
        )
        self.assertFalse(widened_response.context['bookings'].exists())

    def test_services_directory_and_filter_only_show_the_assigned_airline(self):
        from airlines.models import Service
        from simulation.models import SimulationRoleAssignment

        assigned_service = Service.objects.create(
            airline=self.airline, name='Assigned Service')
        other_service = Service.objects.create(
            airline=self.other_airline, name='Other Service')
        manager = get_user_model().objects.create_user(
            username='airline-service-manager',
            password='x',
            account_type='STUDENT',
        )
        SimulationRoleAssignment.objects.create(
            student=manager,
            role='AIRLINE_MANAGER',
            activity_name='Airline Management',
            establishment=self.establishment,
        )
        self.client.force_login(manager)

        response = self.client.get(reverse('airlines:services'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['services'].values_list('pk', flat=True)),
            [assigned_service.pk],
        )
        self.assertEqual(
            list(response.context['airlines'].values_list('pk', flat=True)),
            [self.airline.pk],
        )
        self.assertNotContains(response, other_service.name)

        widened_response = self.client.get(
            reverse('airlines:services'),
            {'airline': self.other_airline.pk},
        )
        self.assertFalse(widened_response.context['services'].exists())

    def test_flights_directory_only_shows_the_assigned_airline(self):
        from establishments.models import establishment_for_instance
        from simulation.models import SimulationRoleAssignment

        manager = get_user_model().objects.create_user(
            username='airline-manager', password='x', account_type='STUDENT')
        SimulationRoleAssignment.objects.create(
            student=manager,
            role='AIRLINE_MANAGER',
            activity_name='Airline Management',
            establishment=establishment_for_instance(self.airline),
        )
        self.client.force_login(manager)

        response = self.client.get(reverse('airlines:flights'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['flights'].values_list('pk', flat=True)),
            [self.flight.pk],
        )
        self.assertEqual(
            list(response.context['airlines'].values_list('pk', flat=True)),
            [self.airline.pk],
        )
        widened_response = self.client.get(
            reverse('airlines:flights'),
            {'airline': self.other_airline.pk},
        )
        self.assertFalse(widened_response.context['flights'].exists())

    def test_airline_management_directory_only_shows_the_assigned_airline(self):
        from establishments.models import establishment_for_instance
        from simulation.models import SimulationRoleAssignment

        manager = get_user_model().objects.create_user(
            username='airline-directory-manager',
            password='x',
            account_type='STUDENT',
        )
        SimulationRoleAssignment.objects.create(
            student=manager,
            role='AIRLINE_MANAGER',
            activity_name='Airline Management',
            establishment=establishment_for_instance(self.airline),
        )
        self.client.force_login(manager)

        response = self.client.get(reverse('airlines:manage'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['airlines'].values_list('pk', flat=True)),
            [self.airline.pk],
        )

    def test_aircraft_directory_only_shows_aircraft_for_the_assigned_airline(self):
        from establishments.models import establishment_for_instance
        from simulation.models import SimulationRoleAssignment

        manager = get_user_model().objects.create_user(
            username='aircraft-directory-manager',
            password='x',
            account_type='STUDENT',
        )
        SimulationRoleAssignment.objects.create(
            student=manager,
            role='AIRLINE_MANAGER',
            activity_name='Airline Management',
            establishment=establishment_for_instance(self.airline),
        )
        assigned_aircraft = make_aircraft(self.airline, 'A320', 'RP-ASG')
        other_aircraft = make_aircraft(self.other_airline, 'A320', 'RP-OTH')
        self.client.force_login(manager)

        response = self.client.get(reverse('airlines:aircrafts'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['aircrafts'].values_list('pk', flat=True)),
            [assigned_aircraft.pk],
        )
        self.assertNotContains(response, other_aircraft.tail_number)
        self.assertEqual(
            list(response.context['airlines'].values_list('pk', flat=True)),
            [self.airline.pk],
        )

        widened_response = self.client.get(
            reverse('airlines:aircrafts'),
            {'airline': self.other_airline.pk},
        )
        self.assertFalse(widened_response.context['aircrafts'].exists())

    def test_an_inactive_task_in_the_tab_session_falls_back_to_active_role_access(self):
        from simulation.models import SimulationRoleAssignment

        stale_assignment = SimulationRoleAssignment.objects.create(
            student=self.agent,
            role='AIRLINE_RESERVATION_AGENT',
            activity_name='Expired Reservation Task',
            establishment=self.establishment,
            status=SimulationRoleAssignment.AssignmentStatus.INACTIVE,
        )
        session = self.client.session
        session['active_simulation_task_assignment'] = stale_assignment.pk
        session.save()

        response = self.client.get(reverse('airlines:bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            'active_simulation_task_assignment', self.client.session)

    def test_agent_cannot_open_or_ticket_another_airlines_booking(self):
        detail = self.client.get(reverse(
            'airlines:booking_detail', args=[self.other_booking.pk]))
        ticket = self.client.get(reverse(
            'airlines:ticket', args=[self.other_booking.pk]))

        self.assertRedirects(detail, reverse('airlines:list'))
        self.assertRedirects(ticket, reverse('airlines:list'))

    def test_confirming_a_pending_booking_emails_the_passenger_only_once(self):
        from unittest.mock import patch
        from notifications.models import EmailDelivery

        url = reverse('airlines:booking_detail', args=[self.booking.pk])
        with patch('notifications.email_service._brevo_send', return_value='brevo-accepted-1') as send:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(url, {'action': 'confirm'})

        self.assertRedirects(response, url)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        delivery = EmailDelivery.objects.get(event='BOOKING_CONFIRMATION')
        self.assertEqual(delivery.recipient, 'passenger@example.com')
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.provider_message_id, 'brevo-accepted-1')
        self.assertIn(self.booking.booking_reference, send.call_args.kwargs['text'])

        self.client.post(url, {'action': 'confirm'})
        self.assertEqual(send.call_count, 1)

    def test_agent_cannot_confirm_their_own_booking(self):
        own_booking = Booking.objects.create(
            passenger=self.agent, flight=self.flight,
            status=Booking.Status.PENDING)

        response = self.client.post(
            reverse('airlines:booking_detail', args=[own_booking.pk]),
            {'action': 'confirm'})

        self.assertEqual(response.status_code, 403)
        own_booking.refresh_from_db()
        self.assertEqual(own_booking.status, Booking.Status.PENDING)


class AirlineFrontDeskBookingActionTests(TestCase):
    """The ticketing restriction has to follow the role, not the retired code.

    ``AIRLINE_FRONT_DESK`` replaced ``AIRLINE_TICKETING_OFFICER`` while the view
    still keyed the narrower action set off the retired code. Renaming the role
    without widening the check would have quietly promoted every new Front Desk
    holder to a full booking manager.
    """

    def setUp(self):
        from establishments.models import establishment_for_instance
        from simulation.models import SimulationRoleAssignment

        User = get_user_model()
        self.front_desk = User.objects.create_user(
            username='airline-front-desk', password='x', account_type='STUDENT')
        self.retired = User.objects.create_user(
            username='airline-retired-ticketing', password='x',
            account_type='STUDENT')
        self.passenger = User.objects.create_user(
            username='fd-passenger', password='x', account_type='STUDENT')
        self.airline, _ = make_airline('Ticketed Air', types=('A320',))
        self.establishment = establishment_for_instance(
            self.airline, create=True, defaults={'status': 'ACTIVE'})
        for student, role in (
                (self.front_desk, 'AIRLINE_FRONT_DESK'),
                (self.retired, 'AIRLINE_TICKETING_OFFICER')):
            SimulationRoleAssignment.objects.create(
                student=student, role=role, activity_name='Ticketing Practice',
                establishment=self.establishment)
        departure = timezone.now() + timedelta(days=5)
        self.flight = Flight.objects.create(
            airline=self.airline, flight_number='FD-101',
            origin='Manila', destination='Cebu',
            departure_time=departure, arrival_time=departure + timedelta(hours=1),
            status='SCHEDULED', economy_fare=1500)

    def booking_for(self, student=None):
        return Booking.objects.create(
            passenger=student or self.passenger, flight=self.flight,
            status=Booking.Status.PENDING)

    def test_front_desk_cannot_perform_the_manager_actions(self):
        booking = self.booking_for()
        self.client.force_login(self.front_desk)

        response = self.client.post(
            reverse('airlines:booking_detail', args=[booking.pk]),
            {'action': 'confirm'})

        self.assertEqual(response.status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PENDING)

    def test_the_retired_role_keeps_the_same_restriction(self):
        booking = self.booking_for()
        self.client.force_login(self.retired)

        response = self.client.post(
            reverse('airlines:booking_detail', args=[booking.pk]),
            {'action': 'confirm'})

        self.assertEqual(response.status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PENDING)

    def test_front_desk_is_still_flagged_as_restricted_on_the_page(self):
        self.client.force_login(self.front_desk)
        response = self.client.get(
            reverse('airlines:booking_detail', args=[self.booking_for().pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['ticketing_restricted'])


class BookingSearchLayoutTests(TestCase):

    def test_search_filters_and_submit_control_share_a_four_column_grid(self):
        user = get_user_model().objects.create_user(
            username='booking-manager', password='x', is_staff=True)
        self.client.force_login(user)

        response = self.client.get(reverse('airlines:bookings'))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        search_form = body.split('class="card card-pad booking-search-form"', 1)[1]
        search_form = search_form.split('</form>', 1)[0]
        self.assertIn('class="form-grid booking-search-grid"', search_form)
        self.assertEqual(search_form.count('class="form-group"'), 6)
        self.assertIn('booking-search-submit', search_form)
        self.assertIn(
            'grid-template-columns: repeat(4, minmax(0, 1fr));', body)
        self.assertIn(
            'grid-template-columns: repeat(2, minmax(0, 1fr));', body)
