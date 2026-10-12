"""Drop the last of the preset-key columns and re-seat every flight.

``Airline.seat_layout`` and ``Flight.seat_layout`` were the manual override
slots: the airline picked one cabin for its whole operation, and a manager could
override it per flight.  Neither is needed now — a flight reads its layout
through the aircraft it is operated by, falling back to the airline's default
type — so both go, and the capacity on every flight is recounted from the
relationship instead.

Seats already sold are never dropped: a flight's capacity is only ever raised to
what its new layout holds.
"""

from django.db import migrations


def reseat_flights(apps, schema_editor):
    """Recount each flight's sellable seats from its resolved layout."""
    Flight = apps.get_model('airlines', 'Flight')
    for flight in Flight.objects.select_related('airline', 'aircraft').iterator():
        layout = None
        if flight.aircraft_id and flight.aircraft.seat_layout_id:
            layout = flight.aircraft.seat_layout
        elif flight.airline.default_aircraft_type_id:
            layout = apps.get_model('airlines', 'SeatLayout').objects.filter(
                airline_id=flight.airline_id,
                aircraft_type_id=flight.airline.default_aircraft_type_id).first()
        if layout is None or layout.total_capacity == flight.total_capacity:
            continue
        if layout.total_capacity > flight.total_capacity:
            flight.total_capacity = layout.total_capacity
            flight.save(update_fields=['total_capacity'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0026_aircraft_fleet_links'),
    ]

    operations = [
        migrations.RunPython(reseat_flights, noop),
        migrations.RemoveField(
            model_name='airline',
            name='legacy_seat_layout',
        ),
        migrations.RemoveField(
            model_name='flight',
            name='legacy_seat_layout',
        ),
    ]
