"""Reconcile every aircraft's recorded capacity with the seat layout it flies.

0028 moved the "Cebu Pacific Air" aircraft onto Cebu Pacific's own layouts.
Those layouts are the real ones - a 198-seat A320neo and a 240-seat A321neo -
while the aircraft records still carried the 180 seats they had under the old
presets, so the number on the record and the seat map the booking page draws
had drifted apart.

Capacity is only ever raised, never lowered, because a seat that has already
been sold cannot be taken away by a configuration change.  Aircraft with no
seats sold snap to their layout exactly, so a genuine shrink is still honoured
once nothing is booked against them.
"""

from django.db import migrations
from django.db.models import Count


def reconcile_capacity(apps, schema_editor):
    """Set seating_capacity to the layout, floored at the seats already sold."""
    Aircraft = apps.get_model('airlines', 'Aircraft')
    Booking = apps.get_model('airlines', 'Booking')

    # Mirrors airlines.views._cutoff_statuses: a seat on a cancelled, declined,
    # completed or checked-out booking is not still sellable capacity.
    cutoff = ['CANCELLED', 'DECLINED', 'COMPLETED', 'CHECKED_OUT']
    sold_per_flight = dict(
        Booking.objects.exclude(status__in=cutoff)
        .values_list('flight_id')
        .annotate(sold=Count('seat_entries'))
    )

    for aircraft in Aircraft.objects.select_related('seat_layout').iterator():
        seats_sold = sum(
            sold_per_flight.get(flight_id, 0)
            for flight_id in aircraft.flights.values_list('id', flat=True)
        )
        capacity = max(aircraft.seating_capacity,
                       aircraft.seat_layout.total_capacity,
                       seats_sold)
        if capacity != aircraft.seating_capacity:
            aircraft.seating_capacity = capacity
            aircraft.save(update_fields=['seating_capacity'])


def restore_capacity(apps, schema_editor):
    """Put every aircraft back to exactly what its layout offers."""
    Aircraft = apps.get_model('airlines', 'Aircraft')
    for aircraft in Aircraft.objects.select_related('seat_layout').iterator():
        if aircraft.seating_capacity != aircraft.seat_layout.total_capacity:
            aircraft.seating_capacity = aircraft.seat_layout.total_capacity
            aircraft.save(update_fields=['seating_capacity'])


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0028_fold_legacy_airlines'),
    ]

    operations = [
        migrations.RunPython(reconcile_capacity, restore_capacity),
    ]
