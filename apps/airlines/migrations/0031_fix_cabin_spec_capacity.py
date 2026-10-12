"""Rewrite the seat layouts whose spec row counts did not add up to their name.

Three cabin specs in ``fleet_data.CABIN_SPECS`` promised a capacity their rows
did not produce, so every layout written from them advertised the wrong number
of seats:

* ``B777_340`` had 24 economy rows instead of 30, laying out 304 seats under a
  name that says 340. Eleven airlines' 777-300ER fleets were built from it.
* ``B787_350`` had 45 economy rows instead of 42, laying out 368 seats where
  the key says 350. Three airlines' 787-10 fleets were affected.
* ``NARROW_189`` could not be a 3-3 cabin at all, because 189 is not a multiple
  of six. It is renamed ``NARROW_186`` for the 186 seats 31 rows add up to.

Only those layouts are rebuilt. Their cabins and the individual ``Seat`` rows
inside them are deleted and rewritten from the corrected spec, so the map the
booking page draws and the seat count the database reports can never disagree.
Capacity never drops below seats already sold, because a seat somebody has
booked cannot be taken away by a configuration change.
"""

from django.db import migrations
from django.db.models import Count

from airlines.fleet_data import (
    AIRCRAFT_TYPES, CABIN_SPECS, FLEETS, seat_position,
)

# The specs that were corrected. Layouts written from any other spec are left
# alone, so fixing one airline's cabin never rewrites a neighbour's.
CORRECTED_SPECS = ('B777_340', 'B787_350', 'NARROW_186')

# Mirrors airlines.views._cutoff_statuses: a seat on a cancelled, declined,
# completed or checked-out booking is not still sellable capacity.
CUTOFF_STATUSES = ['CANCELLED', 'DECLINED', 'COMPLETED', 'CHECKED_OUT']


def _corrected_targets():
    """``{(airline name, type model name): spec key}`` for the affected fleets."""
    targets = {}
    for airline_name, fleet in FLEETS.items():
        for code, spec_key in fleet.items():
            if spec_key in CORRECTED_SPECS:
                model_name = AIRCRAFT_TYPES[code][1]
                targets[(airline_name, model_name)] = spec_key
    return targets


def _rewrite_cabins(Cabin, Seat, layout, spec_key):
    """Replace a layout's cabins and seat rows with the corrected spec."""
    spec = CABIN_SPECS[spec_key]
    letters = 'ABCDEFGHJKLMNPQRSTUVWXYZ'

    Seat.objects.filter(seat_layout=layout).delete()
    Cabin.objects.filter(seat_layout=layout).delete()

    first_row = 1
    for position, (fare_class, blocks, rows) in enumerate(spec):
        cabin = Cabin.objects.create(
            seat_layout=layout, fare_class=fare_class,
            position=position, blocks=list(blocks), rows=rows)
        batch = []
        for row_number in range(first_row, first_row + rows):
            letter_at = 0
            for block_width in blocks:
                for seat_at in range(block_width):
                    letter = letters[letter_at]
                    batch.append(Seat(
                        seat_layout=layout, cabin=cabin, row_number=row_number,
                        letter=letter,
                        seat_number='%d%s' % (row_number, letter),
                        position=seat_position(block_width, seat_at)))
                    letter_at += 1
            if len(batch) >= 500:
                Seat.objects.bulk_create(batch)
                batch = []
        if batch:
            Seat.objects.bulk_create(batch)
        first_row += rows


def fix_cabin_spec_capacity(apps, schema_editor):
    """Rebuild the affected layouts, then re-derive what flies on them."""
    Aircraft = apps.get_model('airlines', 'Aircraft')
    Airline = apps.get_model('airlines', 'Airline')
    Booking = apps.get_model('airlines', 'Booking')
    Cabin = apps.get_model('airlines', 'Cabin')
    Flight = apps.get_model('airlines', 'Flight')
    Seat = apps.get_model('airlines', 'Seat')
    SeatLayout = apps.get_model('airlines', 'SeatLayout')

    fixed = 0
    for (airline_name, model_name), spec_key in _corrected_targets().items():
        airline = Airline.objects.filter(name=airline_name).first()
        if airline is None:
            continue
        layout = SeatLayout.objects.filter(
            airline=airline, aircraft_type__model_name=model_name).first()
        if layout is None:
            continue

        expected = sum(rows * sum(blocks) for _, blocks, rows in CABIN_SPECS[spec_key])
        if layout.total_capacity == expected:
            continue  # already correct, nothing to rewrite

        _rewrite_cabins(Cabin, Seat, layout, spec_key)
        layout.total_capacity = expected
        layout.save(update_fields=['total_capacity'])
        fixed += 1

        # The airframes on this type now offer the corrected capacity.
        for aircraft in Aircraft.objects.filter(seat_layout=layout):
            if aircraft.seating_capacity != expected:
                aircraft.seating_capacity = expected
                aircraft.save(update_fields=['seating_capacity'])

        # ... and so do the flights, never below seats already sold.
        sold = dict(
            Booking.objects.exclude(status__in=CUTOFF_STATUSES)
            .filter(flight__aircraft__seat_layout=layout)
            .values_list('flight_id')
            .annotate(sold=Count('seat_entries')))
        for flight in Flight.objects.filter(aircraft__seat_layout=layout):
            capacity = max(expected, sold.get(flight.pk, 0))
            if capacity != flight.total_capacity:
                flight.total_capacity = capacity
                flight.save(update_fields=['total_capacity'])

    print('rewrote %d seat layouts from the corrected cabin specs' % fixed)


def keep_corrected_capacity(apps, schema_editor):
    """No reverse: the corrected specs are the source of truth going forward."""


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0030_reconcile_flight_capacity'),
    ]

    operations = [
        migrations.RunPython(fix_cabin_spec_capacity, keep_corrected_capacity),
    ]
