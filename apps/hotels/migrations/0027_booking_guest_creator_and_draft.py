import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


def backfill_booking_people(apps, schema_editor):
    Booking = apps.get_model('hotels', 'Booking')
    HotelGuest = apps.get_model('hotels', 'HotelGuest')
    for booking in Booking.objects.select_related('customer').all().iterator():
        if not booking.created_by_id:
            booking.created_by_id = booking.customer_id
            booking.save(update_fields=['created_by'])
        first_entry = booking.room_entries.order_by('selection_order', 'pk').first()
        if not first_entry:
            continue
        guest = HotelGuest.objects.create(
            first_name=first_entry.guest_first_name or booking.customer.first_name or booking.customer.username,
            middle_name=first_entry.guest_middle_name or booking.customer.middle_name or '',
            last_name=first_entry.guest_last_name or booking.customer.last_name or booking.customer.username,
            email=first_entry.guest_email or booking.customer.email or '',
            contact=first_entry.guest_contact or booking.customer.contact_number or '',
        )
        booking.guest_id = guest.pk
        booking.save(update_fields=['guest'])
        for entry in booking.room_entries.order_by('selection_order', 'pk'):
            if entry.pk == first_entry.pk:
                entry.guest_id = guest.pk
            else:
                entry.guest_id = HotelGuest.objects.create(
                    first_name=entry.guest_first_name or booking.customer.first_name or booking.customer.username,
                    middle_name=entry.guest_middle_name or '',
                    last_name=entry.guest_last_name or booking.customer.last_name or booking.customer.username,
                    email=entry.guest_email or booking.customer.email or '',
                    contact=entry.guest_contact or booking.customer.contact_number or '',
                ).pk
            entry.save(update_fields=['guest'])


class Migration(migrations.Migration):

    # PostgreSQL cannot create the subsequent FK/unique indexes while a single
    # atomic migration still has pending trigger events from earlier ALTERs.
    # Commit each schema operation before applying the next one.
    atomic = False

    dependencies = [
        ('hotels', '0026_hotel_created_by'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HotelGuest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=100)),
                ('middle_name', models.CharField(blank=True, max_length=100)),
                ('last_name', models.CharField(max_length=100)),
                ('email', models.EmailField(max_length=254)),
                ('contact', models.CharField(max_length=30)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ],
        ),
        migrations.AddField(
            model_name='booking', name='guest',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='bookings', to='hotels.hotelguest'),
        ),
        migrations.AddField(
            model_name='booking', name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='created_hotel_bookings', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='booking', name='draft_key',
            field=models.CharField(blank=True, editable=False, max_length=36, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='bookingroom', name='guest',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='room_reservations', to='hotels.hotelguest'),
        ),
        migrations.RunPython(backfill_booking_people, migrations.RunPython.noop),
    ]
