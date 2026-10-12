from django.db import migrations, models


def backfill_service_ids(apps, schema_editor):
    Service = apps.get_model('hotels', 'Service')
    for svc in Service.objects.all().order_by('pk'):
        if not svc.service_id:
            svc.service_id = f"SVC-{svc.pk:05d}"
            svc.save(update_fields=['service_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('hotels', '0012_room_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='service_id',
            field=models.CharField(max_length=12, null=True, blank=True, unique=True, verbose_name='Service ID'),
        ),
        migrations.RunPython(backfill_service_ids),
        migrations.AlterField(
            model_name='service',
            name='service_id',
            field=models.CharField(editable=False, max_length=12, null=True, unique=True, verbose_name='Service ID'),
        ),
    ]