import django.db.models.deletion
from django.db import migrations, models


def _flights_with_aircraft(apps):
    Flight = apps.get_model('airlines', 'Flight')
    return Flight.objects.filter(aircraft__isnull=False).only('pk', 'aircraft_id', 'total_capacity')


def copy_aircraft_capacity(apps, schema_editor):
    """Seed total_capacity from the assigned aircraft so every already-scheduled
    flight keeps selling the same number of seats it sold before."""
    Aircraft = apps.get_model('airlines', 'Aircraft')
    Flight = apps.get_model('airlines', 'Flight')
    capacities = dict(Aircraft.objects.values_list('id', 'seating_capacity'))
    for flight in _flights_with_aircraft(apps):
        if not flight.total_capacity:
            flight.total_capacity = capacities.get(flight.aircraft_id, 0)
            flight.save(update_fields=['total_capacity'])


def clear_aircraft_capacity(apps, schema_editor):
    Aircraft = apps.get_model('airlines', 'Aircraft')
    Flight = apps.get_model('airlines', 'Flight')
    capacities = dict(Aircraft.objects.values_list('id', 'seating_capacity'))
    for flight in _flights_with_aircraft(apps):
        if flight.total_capacity == capacities.get(flight.aircraft_id):
            flight.total_capacity = 0
            flight.save(update_fields=['total_capacity'])


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0019_airport_country_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='flight',
            name='total_capacity',
            field=models.PositiveIntegerField(default=0, help_text='Seats sold on this flight. Leave the aircraft unassigned and set this directly to schedule a flight without a seat layout.', verbose_name='Seat capacity'),
        ),
        migrations.AlterField(
            model_name='flight',
            name='aircraft',
            field=models.ForeignKey(blank=True, help_text='Optional — a flight is a schedule, so it can be created without registering an aircraft first', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='flights', to='airlines.aircraft'),
        ),
        migrations.RunPython(copy_aircraft_capacity, clear_aircraft_capacity),
    ]
