"""Point every existing aircraft at a real type, fleet entry and seat layout.

The old record said "Airbus A320neo" in a free-text column and named a preset
key.  Each aircraft is matched to a seeded ``AircraftType``, that type is added
to the airline's fleet if it is not there already - which is what makes the old
"ATRUE Demo Air" rows' A320s legal - and the aircraft is handed the seat layout
that airline flies for that type.

The twenty airlines seeded in 0024 also get a couple of real tail numbers here,
because this is the first migration where ``Aircraft`` has a type to point at.
"""

from django.db import migrations, models
import django.db.models.deletion

from airlines.fleet_data import (
    AIRCRAFT_TYPES,
    FALLBACK_SPECS,
    FLEET_ALIASES,
    FLEETS,
    MANUFACTURERS,
    SEED_AIRCRAFT,
    match_type_code,
    write_layout,
)


def _airline_primary_code(airline_name):
    """The type code of an airline's primary fleet entry, if it has one."""
    fleet = FLEETS.get(FLEET_ALIASES.get(airline_name, airline_name))
    return next(iter(fleet), None) if fleet else None


def _type_for_code(AircraftType, code):
    spec = AIRCRAFT_TYPES.get(code)
    if spec is None:
        return None
    return AircraftType.objects.filter(
        manufacturer__name=MANUFACTURERS[spec[0]][0], model_name=spec[1]).first()


def _layout_for(apps, airline, aircraft_type):
    """The airline's layout for this type, created with a default cabin if the
    airline was never configured for the type."""
    SeatLayout = apps.get_model('airlines', 'SeatLayout')
    layout = SeatLayout.objects.filter(
        airline=airline, aircraft_type=aircraft_type).first()
    if layout is not None:
        return layout
    return write_layout(
        SeatLayout,
        apps.get_model('airlines', 'Cabin'),
        apps.get_model('airlines', 'Seat'),
        airline, aircraft_type,
        FALLBACK_SPECS.get(aircraft_type.body_class, 'NARROW_180'),
    )


def link_aircraft(apps, schema_editor):
    """Attach every existing aircraft to a type, a fleet entry and a layout."""
    Aircraft = apps.get_model('airlines', 'Aircraft')
    AircraftType = apps.get_model('airlines', 'AircraftType')
    AirlineFleet = apps.get_model('airlines', 'AirlineFleet')

    for aircraft in Aircraft.objects.select_related('airline').iterator():
        airline = aircraft.airline
        # The airline's own fleet wins over a global guess from the model name;
        # an unrecognised name falls back to the airline's primary type.
        code = (match_type_code(aircraft.legacy_model_name or '')
                or _airline_primary_code(airline.name))
        aircraft_type = _type_for_code(AircraftType, code) if code else None
        if aircraft_type is None:
            # Nothing matched and the airline has no seeded fleet: leave the
            # aircraft unattached rather than invent a type for it.
            continue

        AirlineFleet.objects.get_or_create(airline=airline, aircraft_type=aircraft_type)
        layout = _layout_for(apps, airline, aircraft_type)
        aircraft.aircraft_type_id = aircraft_type.pk
        aircraft.seat_layout_id = layout.pk
        aircraft.seating_capacity = layout.total_capacity
        aircraft.save(update_fields=['aircraft_type', 'seat_layout', 'seating_capacity'])


def unlink_aircraft(apps, schema_editor):
    apps.get_model('airlines', 'Aircraft').objects.update(
        aircraft_type=None, seat_layout=None)


def seed_aircraft(apps, schema_editor):
    """Give each seeded airline a couple of real aircraft to show."""
    Aircraft = apps.get_model('airlines', 'Aircraft')
    Airline = apps.get_model('airlines', 'Airline')
    AircraftType = apps.get_model('airlines', 'AircraftType')
    SeatLayout = apps.get_model('airlines', 'SeatLayout')

    for name, rows in SEED_AIRCRAFT.items():
        airline = Airline.objects.filter(name=name).first()
        if airline is None:
            continue
        for code, tail_number in rows:
            if Aircraft.objects.filter(tail_number=tail_number).exists():
                continue
            aircraft_type = _type_for_code(AircraftType, code)
            if aircraft_type is None:
                continue
            layout = SeatLayout.objects.filter(
                airline=airline, aircraft_type=aircraft_type).first()
            if layout is None:
                continue
            Aircraft.objects.create(
                airline=airline, aircraft_type=aircraft_type, seat_layout=layout,
                tail_number=tail_number, status='AVAILABLE',
                seating_capacity=layout.total_capacity)


def unseed_aircraft(apps, schema_editor):
    Aircraft = apps.get_model('airlines', 'Aircraft')
    for rows in SEED_AIRCRAFT.values():
        Aircraft.objects.filter(
            tail_number__in=[tail for _, tail in rows]).delete()


class Migration(migrations.Migration):

    # This migration backfills rows *and* then alters the same tables. On
    # PostgreSQL the backend implements foreign keys as triggers, so an
    # ``ALTER TABLE`` issued after those inserts inside the same transaction is
    # refused with "cannot ALTER TABLE ... because it has pending trigger
    # events". SQLite rebuilts the table instead and never objected, which is
    # why this only surfaced when the project moved to PostgreSQL. Running the
    # operations in separate transactions lets each ``ALTER TABLE`` start clean.
    atomic = False

    dependencies = [
        ('airlines', '0025_rename_legacy_aircraft_layout_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='aircraft',
            name='aircraft_type',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='aircraft', to='airlines.aircrafttype',
                verbose_name='Aircraft type'),
        ),
        migrations.AddField(
            model_name='aircraft',
            name='seat_layout',
            field=models.ForeignKey(
                null=True,
                help_text="The cabin this airframe is fitted out with. Defaults to the "
                          "airline's own layout for the type.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name='aircraft', to='airlines.seatlayout'),
        ),
        migrations.AlterField(
            model_name='aircraft',
            name='seating_capacity',
            field=models.PositiveIntegerField(
                editable=False,
                help_text="Taken from the seat layout, so the record and the seat "
                          "map can never disagree."),
        ),
        migrations.RunPython(link_aircraft, unlink_aircraft),
        migrations.RunPython(seed_aircraft, unseed_aircraft),
        # Everything is linked by now, so the two columns stop being optional.
        # If any row survived the backfill unmatched this raises rather than
        # silently leaving an aircraft that belongs to no fleet.
        migrations.AlterField(
            model_name='aircraft',
            name='aircraft_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='aircraft', to='airlines.aircrafttype',
                verbose_name='Aircraft type'),
        ),
        migrations.AlterField(
            model_name='aircraft',
            name='seat_layout',
            field=models.ForeignKey(
                help_text="The cabin this airframe is fitted out with. Defaults to the "
                          "airline's own layout for the type.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name='aircraft', to='airlines.seatlayout'),
        ),
        migrations.AlterField(
            model_name='flight',
            name='aircraft',
            field=models.ForeignKey(
                blank=True, null=True,
                help_text='Optional — a flight is a schedule, so it can be created '
                          'before an aircraft is registered. Whichever aircraft is '
                          'assigned supplies the seat map.',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='flights', to='airlines.aircraft'),
        ),
        migrations.RemoveField(
            model_name='aircraft',
            name='legacy_model_name',
        ),
        migrations.RemoveField(
            model_name='aircraft',
            name='legacy_body_class',
        ),
        migrations.RemoveField(
            model_name='aircraft',
            name='legacy_seat_layout',
        ),
    ]
