# Hand-written: Flight fare split (BR-046), automatic flight number from
# aircraft tail number, and Booking.BookingSeat junction table holding each
# paying passenger's seat + fare class (BR-043).

import django.db.models.deletion
from django.db import migrations, models


def backfill_seats(apps, schema_editor):
    Booking = apps.get_model('airlines', 'Booking')
    Flight = apps.get_model('airlines', 'Flight')
    BookingSeat = apps.get_model('airlines', 'BookingSeat')

    for booking in Booking.objects.all():
        count = booking.passengers_count or 1
        for _ in range(count):
            BookingSeat.objects.create(
                booking=booking,
                passenger_name=booking.primary_guest_name or '',
                seat_number=booking.seat_number or '',
            )

    for flight in Flight.objects.all():
        flight.first_class_fare = flight.fare
        flight.economy_fare = flight.fare
        flight.save(update_fields=['first_class_fare', 'economy_fare'])


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0004_aircraft_aircraft_type_booking_contact_email_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='flight',
            name='first_class_fare',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='flight',
            name='economy_fare',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.CreateModel(
            name='bookingseat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('passenger_name', models.CharField(blank=True, max_length=200)),
                ('seat_number', models.CharField(blank=True, max_length=10)),
                ('fare_class', models.CharField(choices=[('FIRST_CLASS', 'First Class'), ('ECONOMY', 'Economy')], default='ECONOMY', max_length=15)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seat_entries', to='airlines.booking')),
            ],
        ),
        migrations.RunPython(backfill_seats, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='flight',
            name='fare',
        ),
        migrations.RemoveField(
            model_name='flight',
            name='flight_number',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='seat_number',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='passengers_count',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='total_bill',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='amount_paid',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='balance_due',
        ),
    ]