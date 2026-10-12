import django.db.models.deletion
from django.db import migrations, models


def backfill_booking_rooms(apps, schema_editor):
    Booking = apps.get_model('hotels', 'Booking')
    BookingRoom = apps.get_model('hotels', 'BookingRoom')
    for booking in Booking.objects.exclude(room_id=None):
        BookingRoom.objects.get_or_create(booking=booking, room_id=booking.room_id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('hotels', '0004_booking_amenities_note_booking_number_of_rooms_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookingRoom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='room_entries', to='hotels.booking')),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='booking_entries', to='hotels.room')),
            ],
            options={
                'unique_together': {('booking', 'room')},
            },
        ),
        migrations.RunPython(backfill_booking_rooms, noop_reverse),
        migrations.RemoveField(
            model_name='booking',
            name='room',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='number_of_rooms',
        ),
        migrations.AddField(
            model_name='booking',
            name='rooms',
            field=models.ManyToManyField(related_name='bookings', through='hotels.BookingRoom', to='hotels.room'),
        ),
    ]