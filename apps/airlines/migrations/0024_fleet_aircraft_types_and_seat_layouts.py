"""Give every airline its own fleet, its own aircraft and its own seat layout.

Until now the cabin a flight drew was a hard-coded preset code shared by all
twenty airlines, and any of them could wear any of them.  This builds the real
chain instead - brand -> aircraft type -> airline fleet -> seat layout -> cabin
-> seat - and loads the twenty airlines ATRUE sells into it, so from here on an
aircraft dropdown can only ever offer types that airline actually operates.
"""

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

from airlines.fleet_data import (
    AIRCRAFT_TYPES,
    BODY_CLASSES,
    FLEETS,
    MANUFACTURERS,
    write_layout,
)


def seed_fleet(apps, schema_editor):
    """Load brands, types, the twenty airlines, their fleets and their cabins.

    Every ``(airline, aircraft type)`` pair gets its own layout, which is the
    point of the whole exercise: a Cebu Pacific A320 and a Philippine Airlines
    A320 are the same airframe and two different cabins.
    """
    Manufacturer = apps.get_model('airlines', 'Manufacturer')
    AircraftType = apps.get_model('airlines', 'AircraftType')
    Airline = apps.get_model('airlines', 'Airline')
    AirlineFleet = apps.get_model('airlines', 'AirlineFleet')
    SeatLayout = apps.get_model('airlines', 'SeatLayout')
    Cabin = apps.get_model('airlines', 'Cabin')
    Seat = apps.get_model('airlines', 'Seat')

    brands = {}
    for code, (name, country) in MANUFACTURERS.items():
        brand, _ = Manufacturer.objects.get_or_create(
            name=name, defaults={'country': country})
        brands[code] = brand

    types = {}
    for code, (brand, model, body_class, capacity) in AIRCRAFT_TYPES.items():
        aircraft_type, _ = AircraftType.objects.get_or_create(
            manufacturer=brands[brand], model_name=model,
            defaults={'body_class': body_class, 'typical_capacity': capacity})
        types[code] = aircraft_type

    for name, fleet in FLEETS.items():
        airline, _ = Airline.objects.get_or_create(
            name=name, defaults={'status': 'ACTIVE'})
        for position, (type_code, spec_key) in enumerate(fleet.items()):
            aircraft_type = types[type_code]
            AirlineFleet.objects.get_or_create(
                airline=airline, aircraft_type=aircraft_type,
                defaults={'is_primary': position == 0})
            if SeatLayout.objects.filter(airline=airline,
                                         aircraft_type=aircraft_type).exists():
                continue
            write_layout(SeatLayout, Cabin, Seat, airline, aircraft_type, spec_key)

    # The first fleet type of each airline is the type a flight falls back to
    # when it is scheduled before an aircraft has been assigned.
    for entry in AirlineFleet.objects.filter(is_primary=True).iterator():
        Airline.objects.filter(pk=entry.airline_id).update(
            default_aircraft_type_id=entry.aircraft_type_id)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0023_aircraft_seat_layout_alter_airline_seat_layout_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Manufacturer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True)),
                ('country', models.CharField(blank=True, default='', max_length=80)),
                ('code', models.CharField(blank=True, default='', max_length=12)),
            ],
            options={
                'verbose_name_plural': 'Manufacturers',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='AircraftType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('model_name', models.CharField(
                    help_text="Variant only — the brand is the foreign key (A350-900)",
                    max_length=80)),
                ('body_class', models.CharField(
                    choices=BODY_CLASSES, db_index=True, default='NARROW_BODY',
                    max_length=15)),
                ('typical_capacity', models.PositiveIntegerField(
                    default=0,
                    help_text="Reference seat count for this type, before an operator's"
                              " cabin configuration is applied.",
                    verbose_name='Typical seats')),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text="Cleared to be added to an airline's fleet. Untick to"
                              " retire the type without touching the aircraft already"
                              " flying it.")),
                ('manufacturer', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='aircraft_types', to='airlines.manufacturer',
                    verbose_name='Aircraft brand')),
            ],
            options={
                'ordering': ['manufacturer__name', 'model_name'],
            },
        ),
        migrations.CreateModel(
            name='SeatLayout',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(
                    blank=True, default='', max_length=160,
                    help_text="Defaults to '<Airline> <Type> Seat Layout'.")),
                ('seat_map', models.CharField(
                    blank=True, default='', max_length=40,
                    help_text="The cabin blocks, e.g. 3-3 or 1-2-1 / 2-2-2 / 3-3.")),
                ('total_capacity', models.PositiveIntegerField(
                    default=0, editable=False,
                    help_text="Every seat in every cabin of this layout, seats the map"
                              " offers.",
                    verbose_name='Seat capacity')),
                ('exit_rows', models.JSONField(blank=True, default=list)),
                ('lavatory_rows', models.JSONField(blank=True, default=list)),
                ('galley_positions', models.JSONField(blank=True, default=list)),
                ('aircraft_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='seat_layouts', to='airlines.aircrafttype',
                    verbose_name='Aircraft type')),
                ('airline', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='seat_layouts', to='airlines.airline')),
            ],
            options={
                'ordering': ['airline__name', 'aircraft_type__model_name'],
            },
        ),
        migrations.CreateModel(
            name='AirlineFleet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('is_primary', models.BooleanField(
                    default=False,
                    help_text="The type this airline is best known for, and the fallback"
                              " for a flight with no aircraft assigned yet.")),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text="Untick to retire the type from the fleet while keeping"
                              " the aircraft and flights already on it.")),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now,
                                                    editable=False)),
                ('aircraft_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='operators', to='airlines.aircrafttype',
                    verbose_name='Aircraft type')),
                ('airline', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fleet_entries', to='airlines.airline')),
            ],
            options={
                'ordering': ['airline__name', 'aircraft_type__manufacturer__name',
                             'aircraft_type__model_name'],
            },
        ),
        migrations.CreateModel(
            name='Cabin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('fare_class', models.CharField(
                    choices=[('FIRST_CLASS', 'First Class'), ('BUSINESS', 'Business Class'),
                             ('PREMIUM_ECONOMY', 'Premium Economy'),
                             ('ECONOMY', 'Economy')],
                    default='ECONOMY', max_length=20)),
                ('position', models.PositiveSmallIntegerField(
                    default=0, help_text="Order from the nose of the aircraft.")),
                ('blocks', models.JSONField(
                    default=list,
                    help_text="Seats per row split by an aisle — [3, 3] is 3-3,"
                              " [1, 2, 1] is 1-2-1.")),
                ('rows', models.PositiveIntegerField(default=0)),
                ('seat_layout', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cabins', to='airlines.seatlayout')),
            ],
            options={
                'ordering': ['seat_layout', 'position'],
            },
        ),
        migrations.CreateModel(
            name='Seat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('row_number', models.PositiveIntegerField(
                    db_index=True,
                    help_text="Global row from the nose, as on a boarding pass.")),
                ('letter', models.CharField(max_length=2)),
                ('seat_number', models.CharField(
                    db_index=True, max_length=8,
                    help_text="Row and letter together, e.g. 40A.")),
                ('position', models.CharField(
                    choices=[('window', 'Window'), ('middle', 'Middle'),
                             ('aisle', 'Aisle')],
                    default='window', max_length=8)),
                ('cabin', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='seats', to='airlines.cabin')),
                ('seat_layout', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='seats', to='airlines.seatlayout')),
            ],
            options={
                'ordering': ['seat_layout', 'row_number', 'letter'],
            },
        ),
        migrations.AddConstraint(
            model_name='aircrafttype',
            constraint=models.UniqueConstraint(
                fields=('manufacturer', 'model_name'), name='unique_manufacturer_model'),
        ),
        migrations.AddConstraint(
            model_name='airlinefleet',
            constraint=models.UniqueConstraint(
                fields=('airline', 'aircraft_type'),
                name='unique_airline_aircraft_type'),
        ),
        migrations.AddConstraint(
            model_name='seatlayout',
            constraint=models.UniqueConstraint(
                fields=('airline', 'aircraft_type'), name='unique_airline_seat_layout'),
        ),
        migrations.AddConstraint(
            model_name='cabin',
            constraint=models.UniqueConstraint(
                fields=('seat_layout', 'position'), name='unique_cabin_position'),
        ),
        migrations.AddConstraint(
            model_name='seat',
            constraint=models.UniqueConstraint(
                fields=('seat_layout', 'seat_number'), name='unique_seat_per_layout'),
        ),
        migrations.AddField(
            model_name='airline',
            name='default_aircraft_type',
            field=models.ForeignKey(
                blank=True, null=True,
                help_text="The type a flight falls back to when a schedule is created"
                          " before an aircraft is assigned. Must be one of this"
                          " airline's fleet types.",
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='default_for', to='airlines.aircrafttype',
                verbose_name='Default aircraft type'),
        ),
        migrations.RunPython(seed_fleet, migrations.RunPython.noop),
    ]
