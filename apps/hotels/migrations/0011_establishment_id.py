from django.db import migrations, models


def backfill_establishment_ids(apps, schema_editor):
    Hotel = apps.get_model('hotels', 'Hotel')
    for hotel in Hotel.objects.all().order_by('pk'):
        if not hotel.establishment_id:
            hotel.establishment_id = f"HTL-{hotel.pk:05d}"
            hotel.save(update_fields=['establishment_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('hotels', '0010_bookingroom_pricing'),
    ]

    operations = [
        migrations.AddField(
            model_name='hotel',
            name='establishment_id',
            field=models.CharField(max_length=12, null=True, blank=True, unique=True, verbose_name='Establishment ID'),
        ),
        migrations.RunPython(backfill_establishment_ids),
        migrations.AlterField(
            model_name='hotel',
            name='establishment_id',
            field=models.CharField(editable=False, max_length=12, null=True, unique=True, verbose_name='Establishment ID'),
        ),
    ]