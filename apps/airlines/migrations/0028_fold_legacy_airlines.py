"""Fold the legacy "Cebu Pacific Air" row into "Cebu Pacific", and give every
airline that has a fleet a default aircraft type.

0026 backfilled existing aircraft by matching their free-text model name, which
created the fleet entry it needed but never marked one of them as the airline's
primary type.  Airlines that were not in the seed data - the "ATRUE Demo Air"
rows, "PAL Express" and "Cebu Pacific Air" - were therefore left with a fleet
and no default, so a flight scheduled on one of them before an aircraft was
assigned had no cabin to sell.

0024 also seeded "Cebu Pacific" while the database already held the same
carrier under the older name "Cebu Pacific Air", complete with three aircraft
and four flights.  Two rows for one airline means an operator appears twice in
the manage list and the two sets of aircraft are split apart, so the legacy row
is folded into the seeded one here.
"""

from django.db import migrations

# Older name -> seeded name.  Only carriers that already existed in the database
# under a different name belong here.
RENAME_INTO_SEED = {
    'Cebu Pacific Air': 'Cebu Pacific',
}


def fold_legacy_airlines(apps, schema_editor):
    """Move aircraft, flights, fleets and layouts onto the seeded airline."""
    Airline = apps.get_model('airlines', 'Airline')
    Aircraft = apps.get_model('airlines', 'Aircraft')
    Flight = apps.get_model('airlines', 'Flight')
    AirlineFleet = apps.get_model('airlines', 'AirlineFleet')
    SeatLayout = apps.get_model('airlines', 'SeatLayout')

    for legacy_name, seeded_name in RENAME_INTO_SEED.items():
        legacy = Airline.objects.filter(name=legacy_name).first()
        target = Airline.objects.filter(name=seeded_name).first()
        if legacy is None or target is None or legacy.pk == target.pk:
            continue

        for aircraft in Aircraft.objects.filter(airline=legacy):
            # The layout has to move with the aircraft: it is unique per
            # (airline, type) and the seeded airline already owns that layout.
            landing_layout = SeatLayout.objects.filter(
                airline=target, aircraft_type=aircraft.aircraft_type).first()
            if landing_layout is None:
                continue
            aircraft.seat_layout = landing_layout
            aircraft.airline = target
            # The seeded layout is the one the carrier really flies, so the
            # record has to agree with it.  Capacity only ever moves up: a seat
            # already sold can never be taken away by a layout change.
            aircraft.seating_capacity = max(
                aircraft.seating_capacity, landing_layout.total_capacity)
            aircraft.save(update_fields=['airline', 'seat_layout', 'seating_capacity'])

        Flight.objects.filter(airline=legacy).update(airline=target)

        # Fleet entries and layouts are unique per (airline, type), so only the
        # ones the seeded airline does not already have are worth moving.  A
        # duplicate layout is redundant and cannot be moved at all, so it goes.
        for entry in AirlineFleet.objects.filter(airline=legacy):
            if not AirlineFleet.objects.filter(
                    airline=target, aircraft_type=entry.aircraft_type).exists():
                entry.airline = target
                entry.save(update_fields=['airline'])

        for layout in SeatLayout.objects.filter(airline=legacy):
            if SeatLayout.objects.filter(
                    airline=target, aircraft_type=layout.aircraft_type).exists():
                # Still in use by an aircraft that had nowhere else to land?
                if Aircraft.objects.filter(seat_layout=layout).exists():
                    continue
                layout.delete()
            else:
                layout.airline = target
                layout.save(update_fields=['airline'])
        legacy.delete()


def restore_legacy_airlines(apps, schema_editor):
    """Put the folded row back under its old name.

    The aircraft keep the seeded airline's layout, which is the seat map they
    are already flying, so only the row is renamed back rather than rebuilt.
    """
    Airline = apps.get_model('airlines', 'Airline')
    for legacy_name, seeded_name in RENAME_INTO_SEED.items():
        seeded = Airline.objects.filter(name=seeded_name).first()
        if seeded is not None:
            seeded.name = legacy_name
            seeded.save(update_fields=['name'])


def set_default_types(apps, schema_editor):
    """Give every airline with a fleet but no default its first active type.

    This is what a flight falls back to when it is scheduled before an aircraft
    is assigned, so an airline missing one cannot sell a seat.
    """
    Airline = apps.get_model('airlines', 'Airline')

    for airline in Airline.objects.filter(
            default_aircraft_type__isnull=True).iterator():
        entry = airline.fleet_entries.filter(is_active=True).order_by(
            '-is_primary', 'aircraft_type__manufacturer__name',
            'aircraft_type__model_name').first()
        if entry is None:
            continue
        entry.is_primary = True
        entry.save(update_fields=['is_primary'])
        Airline.objects.filter(pk=airline.pk).update(
            default_aircraft_type_id=entry.aircraft_type_id)


def clear_default_types(apps, schema_editor):
    """Undo only the defaults this migration invented.

    The seeded airlines already had a default from 0024, so anything set here
    is cleared again to leave the database as it was found.
    """
    Airline = apps.get_model('airlines', 'Airline')
    from airlines.fleet_data import FLEETS  # noqa: PLC0415
    seeded = Airline.objects.filter(name__in=list(FLEETS))
    seeded.update(default_aircraft_type=None)
    apps.get_model('airlines', 'AirlineFleet').objects.filter(
        airline__name__in=list(FLEETS), is_primary=True).update(is_primary=False)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0027_drop_legacy_layout_overrides'),
    ]

    operations = [
        migrations.RunPython(fold_legacy_airlines, restore_legacy_airlines),
        migrations.RunPython(set_default_types, clear_default_types),
    ]
