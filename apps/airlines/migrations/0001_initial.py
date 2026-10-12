import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Airline',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('contact_number', models.CharField(blank=True, max_length=20)),
                ('status', models.CharField(choices=[('ACTIVE', 'Active'), ('INACTIVE', 'Inactive'), ('SUSPENDED', 'Suspended')], default='ACTIVE', max_length=10)),
            ],
        ),
        migrations.CreateModel(
            name='Aircraft',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('model_name', models.CharField(max_length=100)),
                ('tail_number', models.CharField(max_length=20, unique=True)),
                ('seating_capacity', models.PositiveIntegerField()),
                ('airline', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='aircrafts', to='airlines.airline')),
            ],
        ),
        migrations.CreateModel(
            name='Flight',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('flight_number', models.CharField(max_length=20)),
                ('origin', models.CharField(max_length=100)),
                ('destination', models.CharField(max_length=100)),
                ('departure_time', models.DateTimeField()),
                ('arrival_time', models.DateTimeField()),
                ('fare', models.DecimalField(decimal_places=2, max_digits=10)),
                ('status', models.CharField(choices=[('SCHEDULED', 'Scheduled'), ('DELAYED', 'Delayed'), ('CANCELLED', 'Cancelled'), ('COMPLETED', 'Completed')], default='SCHEDULED', max_length=10)),
                ('aircraft', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='flights', to='airlines.aircraft')),
                ('airline', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='flights', to='airlines.airline')),
            ],
        ),
        migrations.CreateModel(
            name='Booking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('booking_reference', models.CharField(max_length=30, unique=True)),
                ('seat_number', models.CharField(blank=True, max_length=10)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('CONFIRMED', 'Confirmed'), ('CANCELLED', 'Cancelled'), ('COMPLETED', 'Completed')], default='PENDING', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('flight', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bookings', to='airlines.flight')),
                ('passenger', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='airline_bookings', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]