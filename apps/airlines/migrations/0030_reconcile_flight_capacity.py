"""Bring every flight's recorded capacity in line with the cabin it now sells.

``Flight.save()`` has always derived ``total_capacity`` from the flight's seat
layout rather than trusting a typed-in number, but that only runs when a flight
is next saved.  The rows that existed before the fleet work still carry the
capacity their airline's old hard-coded preset happened to have - a Philippine
A320 advertising 240 seats against a 180-seat cabin, and the Cebu Pacific
flights advertising 180 against the 198-seat A320neo layout they now fly.

They are re-derived here with the same rule used everywhere else: capacity
never drops below the seats already sold, because a seat somebody has booked
cannot be taken away by a configuration change.
"""

from django.db import migrations
from django.db.models import Count


def reconcile_flight_capacity(apps, schema_editor):
    """Re-derive total_capacity from each flight's resolved layout."""
    Flight = apps.get_model('airlines', 'Flight')
    Aircraft = apps.get_model('airlines', 'Aircraft')
    SeatLayout = apps.get_model('airlines', 'SeatLayout')
    AirlineFleet = apps.get_model('airlines', 'AirlineFleet')
    Booking = apps.get_model('airlines', 'Booking')

    # Mirrors airlines.views._cutoff_statuses: a seat on a cancelled, declined,
    # completed or checked-out booking is not still sellable capacity.
    cutoff = ['CANCELLED', 'DECLINED', 'COMPLETED', 'CHECKED_OUT']
    sold_per_flight = dict(
        Booking.objects.exclude(status__in=cutoff)
        .values_list('flight_id')
        .annotate(sold=Count('seat_entries'))
    )

    for flight in Flight.objects.select_related(
            'airline', 'aircraft__seat_layout').iterator():
        # Same order as airlines.layouts.resolve_layout: the aircraft flying it
        # wins, then the airline's default type, then its first active fleet type.
        layout = None
        if flight.aircraft_id and flight.aircraft.seat_layout_id:
            layout = flight.aircraft.seat_layout
        if layout is None and flight.airline.default_aircraft_type_id:
            layout = SeatLayout.objects.filter(
                airline_id=flight.airline_id,
                aircraft_type_id=flight.airline.default_aircraft_type_id).first()
        if layout is None:
            entry = AirlineFleet.objects.filter(
                airline_id=flight.airline_id, is_active=True).first()
            if entry is not None:
                layout = SeatLayout.objects.filter(
                    airline_id=flight.airline_id,
                    aircraft_type_id=entry.aircraft_type_id).first()
        if layout is None:
            continue

        capacity = max(layout.total_capacity, sold_per_flight.get(flight.pk, 0))
        if capacity != flight.total_capacity:
            flight.total_capacity = capacity
            flight.save(update_fields=['total_capacity'])


def restore_flight_capacity(apps, schema_editor):
    """Snap every flight back to exactly what its layout offers."""
    Flight = apps.get_model('airlines', 'Flight')
    for flight in Flight.objects.select_related('aircraft__seat_layout').iterator():
        layout = flight.aircraft.seat_layout if flight.aircraft_id else None
        if layout is not None and flight.total_capacity != layout.total_capacity:
            flight.total_capacity = layout.total_capacity
            flight.save(update_fields=['total_capacity'])


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0029_reconcile_aircraft_capacity'),
    ]

    operations = [
        migrations.RunPython(reconcile_flight_capacity, restore_flight_capacity),
    ]
