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
            name='ActivityLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(max_length=255)),
                ('details', models.TextField(blank=True, default='')),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activity_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
        migrations.CreateModel(
            name='SimulationRoleAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('RECEPTIONIST', 'Receptionist'), ('BOOKING_AGENT', 'Booking Agent'), ('FRONT_DESK', 'Front Desk Officer'), ('CONCIERGE', 'Concierge'), ('TOUR_GUIDE', 'Tour Guide'), ('RESTAURANT_STAFF', 'Restaurant Staff'), ('TRANSPORT_STAFF', 'Transport Staff'), ('CABIN_CREW', 'Cabin Crew'), ('TRAVEL_CONSULTANT', 'Travel Consultant'), ('HOTEL_MANAGER', 'Hotel Manager')], max_length=25)),
                ('simulation_activity', models.CharField(default='General Training', max_length=150)),
                ('assigned_at', models.DateTimeField(auto_now_add=True)),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_roles', to=settings.AUTH_USER_MODEL)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='simulation_roles', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]