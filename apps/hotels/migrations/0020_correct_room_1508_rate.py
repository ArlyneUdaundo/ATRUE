from decimal import Decimal

from django.db import migrations

# Room 1508 at Bai Hotel Cebu was saved with rate 69.00 instead of 6900.00.
# The hotel card advertises min(Room.rate), so the typo published a
# "from PHP 69 / night" rate on the public listing.
#
# The row is matched on its own identifying fields (hotel + room number) rather
# than a bare primary key, and only rewritten while it still holds the bad
# value, so re-running this never clobbers a rate an admin has since corrected.
BAD_RATE = Decimal('69.00')
GOOD_RATE = Decimal('6900.00')


def correct_room_1508_rate(apps, schema_editor):
    Hotel = apps.get_model('hotels', 'Hotel')
    Room = apps.get_model('hotels', 'Room')
    room = (
        Room.objects
        .filter(room_number='1508', rate=BAD_RATE, hotel__name='Bai Hotel Cebu')
        .first()
    )
    if room is None:
        return
    room.rate = GOOD_RATE
    room.save(update_fields=['rate'])


def restore_room_1508_rate(apps, schema_editor):
    Hotel = apps.get_model('hotels', 'Hotel')
    Room = apps.get_model('hotels', 'Room')
    room = (
        Room.objects
        .filter(room_number='1508', rate=GOOD_RATE, hotel__name='Bai Hotel Cebu')
        .first()
    )
    if room is None:
        return
    room.rate = BAD_RATE
    room.save(update_fields=['rate'])


class Migration(migrations.Migration):
    dependencies = [('hotels', '0019_hotel_country')]
    operations = [
        migrations.RunPython(correct_room_1508_rate, restore_room_1508_rate),
    ]
