from django.db import migrations, models


def backfill_room_ids(apps, schema_editor):
    Room = apps.get_model('hotels', 'Room')
    for room in Room.objects.all().order_by('pk'):
        if not room.room_id:
            room.room_id = f"RID-{room.pk:05d}"
            room.save(update_fields=['room_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('hotels', '0011_establishment_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='room_id',
            field=models.CharField(max_length=12, null=True, blank=True, unique=True, verbose_name='Room ID'),
        ),
        migrations.RunPython(backfill_room_ids),
        migrations.AlterField(
            model_name='room',
            name='room_id',
            field=models.CharField(editable=False, max_length=12, null=True, unique=True, verbose_name='Room ID'),
        ),
    ]