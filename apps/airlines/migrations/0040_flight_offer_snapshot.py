from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0039_airport_address'),
    ]

    operations = [
        migrations.CreateModel(
            name='FlightOfferSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(db_index=True, default='duffel', max_length=30)),
                ('mode', models.CharField(db_index=True, default='test', max_length=10)),
                ('offer_id', models.CharField(max_length=100)),
                ('origin_code', models.CharField(db_index=True, max_length=8)),
                ('destination_code', models.CharField(db_index=True, max_length=8)),
                ('departure_date', models.DateField(db_index=True)),
                ('return_date', models.DateField(blank=True, null=True)),
                ('passenger_count', models.PositiveSmallIntegerField(default=1)),
                ('cabin_class', models.CharField(default='economy', max_length=20)),
                ('total_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('currency', models.CharField(blank=True, default='', max_length=3)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('retrieved_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('payload', models.JSONField(blank=True, default=dict)),
            ],
            options={'ordering': ['-retrieved_at']},
        ),
        migrations.AddConstraint(
            model_name='flightoffersnapshot',
            constraint=models.UniqueConstraint(
                fields=('provider', 'mode', 'offer_id'),
                name='unique_flight_offer_snapshot',
            ),
        ),
    ]
