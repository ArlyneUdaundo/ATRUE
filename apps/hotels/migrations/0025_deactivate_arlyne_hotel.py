from django.db import migrations


def deactivate_arlyne_hotel(apps, schema_editor):
    Hotel = apps.get_model('hotels', 'Hotel')
    Hotel.objects.filter(name__iexact='Arlyne hotel').update(status='INACTIVE')


class Migration(migrations.Migration):

    dependencies = [
        ('hotels', '0024_alter_bookingroom_options_and_more'),
    ]

    operations = [
        migrations.RunPython(deactivate_arlyne_hotel, migrations.RunPython.noop),
    ]
