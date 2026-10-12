"""Give the airport table its time zones and terminals, and time the existing legs.

Purely additive.  Nothing is deleted and no existing value is overwritten: a
row that already carries a timezone keeps it, so a corrected zone an operator
entered by hand survives this migration.

The flight backfill is a no-op numerically for every flight that already
existed.  ``Flight.departure_time``/``arrival_time`` are stored as aware
datetimes, and a leg whose airports carry no zone of their own is timed in the
platform zone — so an existing MNL->HKG row keeps exactly the duration it
always showed.  What is new is the ``departure_timezone`` / ``arrival_timezone``
columns being populated, which is what a future connecting itinerary reads.
"""

from django.db import migrations


def fill_airport_timezones(apps, schema_editor):
    """Write the IANA zone and terminal list onto every airport we can resolve.

    ``airlines.timezone_data`` is imported rather than copied so there is one
    table of truth; it is reference data that only ever gains entries, so a
    future migration re-running this logic stays correct.
    """
    from airlines.timezone_data import terminals_for_airport, timezone_for_airport

    Airport = apps.get_model('airlines', 'Airport')
    for airport in Airport.objects.all().iterator():
        updates = {}
        if not airport.timezone:
            zone = timezone_for_airport(airport)
            if zone:
                updates['timezone'] = zone
        if not airport.terminals:
            terminals = terminals_for_airport(airport)
            if terminals:
                updates['terminals'] = terminals
        if updates:
            Airport.objects.filter(pk=airport.pk).update(**updates)


def backfill_segment_timing(apps, schema_editor):
    """Stamp each existing flight with its airports' zones and in-air minutes.

    Uses the same ``itinerary_timing`` maths the rest of the app uses, so the
    stored number and the number the UI shows come from one place.
    """
    from airlines.itineraries import itinerary_timing

    Flight = apps.get_model('airlines', 'Flight')
    for flight in Flight.objects.select_related(
            'origin_airport', 'destination_airport').all().iterator():
        updates = {}
        if not flight.departure_timezone and flight.origin_airport_id:
            zone = getattr(flight.origin_airport, 'timezone', '') or ''
            if zone:
                updates['departure_timezone'] = zone
        if not flight.arrival_timezone and flight.destination_airport_id:
            zone = getattr(flight.destination_airport, 'timezone', '') or ''
            if zone:
                updates['arrival_timezone'] = zone
        if not flight.segment_duration_minutes:
            timing = itinerary_timing([flight])
            minutes = timing['legs'][0]['flight_minutes'] if timing['legs'] else None
            if minutes and minutes > 0:
                updates['segment_duration_minutes'] = minutes
        if updates:
            Flight.objects.filter(pk=flight.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0033_flight_itinerary'),
    ]

    operations = [
        migrations.RunPython(fill_airport_timezones, migrations.RunPython.noop),
        migrations.RunPython(backfill_segment_timing, migrations.RunPython.noop),
    ]
