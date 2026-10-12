from django.db import migrations

from airlines.legacy_layouts import build_seat_map


def reseat_legacy_bookings(apps, schema_editor):
    """Move seats booked under the old synthetic 6-abreast grid onto real seats.

    Migration 0021 gave every flight a real cabin configuration, so a seat number
    like ``2F`` (a 6-abreast column) or ``1F`` (which the airline's first class
    1-2-1 cabin does not have) no longer names a seat the guest can see.  Left
    alone those bookings would be invisible on the map yet still hold a seat, so
    each one is moved to a free real seat in the cabin it was sold in.
    """
    Booking = apps.get_model('airlines', 'Booking')
    BookingSeat = apps.get_model('airlines', 'BookingSeat')
    Flight = apps.get_model('airlines', 'Flight')

    for flight in Flight.objects.select_related('airline').all():
        layout = build_seat_map(flight, [])
        real = {
            cabin['key']: [col['seat'] for row in cabin['rows']
                           for block in row['blocks'] for col in block['cols']]
            for cabin in layout['cabins']
        }
        taken = {
            seat for seat in BookingSeat.objects.filter(booking__flight=flight)
            .values_list('seat_number', flat=True) if seat
        }
        # Each cabin hands out its own seats, oldest booking first.
        spare = {
            key: [seat for seat in seats if seat not in taken] for key, seats in real.items()
        }
        for seat in BookingSeat.objects.filter(booking__flight=flight).order_by('id'):
            number = (seat.seat_number or '').strip()
            cabin = seat.fare_class
            if number in real.get(cabin, ()) or cabin not in real:
                continue
            # Fall back to any cabin the airline actually flies.
            options = real.get(cabin) or [s for seats in real.values() for s in seats]
            pool = spare.get(cabin) or [s for seats in spare.values() for s in seats]
            replacement = next((s for s in pool if s not in taken), None)
            if not replacement:
                continue
            if cabin not in real:
                cabin = next(key for key, seats in real.items() if replacement in seats)
                seat.fare_class = cabin
            seat.seat_number = replacement
            seat.save(update_fields=['seat_number', 'fare_class'])
            taken.add(replacement)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0021_airline_seat_layout_flight_business_fare_and_more'),
    ]

    operations = [
        migrations.RunPython(reseat_legacy_bookings, migrations.RunPython.noop),
    ]
