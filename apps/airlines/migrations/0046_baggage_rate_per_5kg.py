from decimal import Decimal

from django.db import migrations, models
from django.db.models import F


def convert_rates_to_five_kg_blocks(apps, schema_editor):
    database = schema_editor.connection.alias
    for model_name in ('Flight', 'FlightItinerary'):
        model = apps.get_model('airlines', model_name)
        model.objects.using(database).update(
            baggage_rate=F('baggage_rate') * 5)


def convert_rates_to_per_kg(apps, schema_editor):
    database = schema_editor.connection.alias
    for model_name in ('Flight', 'FlightItinerary'):
        model = apps.get_model('airlines', model_name)
        model.objects.using(database).update(
            baggage_rate=F('baggage_rate') / 5)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0045_bookingseat_passenger_classification'),
    ]

    operations = [
        migrations.RunPython(
            convert_rates_to_five_kg_blocks,
            convert_rates_to_per_kg,
        ),
        migrations.AlterField(
            model_name='flight',
            name='baggage_rate',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('5000.00'),
                help_text='Charge for each 5 kg block of extra baggage',
                max_digits=10,
                verbose_name='Baggage rate per 5 kg (₱)',
            ),
        ),
        migrations.AlterField(
            model_name='flightitinerary',
            name='baggage_rate',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('5000.00'),
                help_text='Charge for each 5 kg block of extra baggage on any leg',
                max_digits=10,
                verbose_name='Baggage rate per 5 kg (₱)',
            ),
        ),
    ]
