from datetime import date

from django.db import migrations, models


def backfill_bookingroom(apps, schema_editor):
    Booking = apps.get_model('hotels', 'Booking')
    BookingRoom = apps.get_model('hotels', 'BookingRoom')
    for entry in BookingRoom.objects.all():
        b = entry.booking
        if b is None:
            entry.check_in = date.today()
            entry.check_out = date.today()
            entry.number_of_adults = 1
            entry.number_of_children = 0
            entry.save()
            continue
        check_in = b.check_in or (b.created_at.date() if b.created_at else date.today())
        check_out = b.check_out or check_in
        entry.check_in = check_in
        entry.check_out = check_out
        entry.number_of_adults = b.number_of_adults or 1
        entry.number_of_children = b.number_of_children or 0
        entry.services.set(b.services.all())
        entry.amenities.set(b.amenities.all())
        entry.save(update_fields=['check_in', 'check_out', 'number_of_adults', 'number_of_children'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('hotels', '0008_add_booking_reference'),
    ]

    operations = [
        migrations.AddField(
            model_name='bookingroom',
            name='check_in',
            field=models.DateField(null=True),
        ),
        migrations.AddField(
            model_name='bookingroom',
            name='check_out',
            field=models.DateField(null=True),
        ),
        migrations.AddField(
            model_name='bookingroom',
            name='number_of_adults',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='bookingroom',
            name='number_of_children',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='bookingroom',
            name='services',
            field=models.ManyToManyField(blank=True, related_name='_merged_services', to='hotels.service'),
        ),
        migrations.AddField(
            model_name='bookingroom',
            name='amenities',
            field=models.ManyToManyField(blank=True, related_name='_merged_amenities', to='hotels.amenity'),
        ),
        migrations.RunPython(backfill_bookingroom, noop_reverse),
        migrations.RemoveField(
            model_name='booking',
            name='check_in',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='check_out',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='number_of_adults',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='number_of_children',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='services',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='amenities',
        ),
        migrations.AlterField(
            model_name='bookingroom',
            name='services',
            field=models.ManyToManyField(blank=True, related_name='bookings', to='hotels.service'),
        ),
        migrations.AlterField(
            model_name='bookingroom',
            name='amenities',
            field=models.ManyToManyField(blank=True, related_name='bookings', to='hotels.amenity'),
        ),
        migrations.AlterField(
            model_name='bookingroom',
            name='check_in',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='bookingroom',
            name='check_out',
            field=models.DateField(),
        ),
    ]