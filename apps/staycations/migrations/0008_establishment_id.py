from django.db import migrations, models


def backfill_establishment_ids(apps, schema_editor):
    Staycation = apps.get_model('staycations', 'Staycation')
    for stc in Staycation.objects.all().order_by('pk'):
        if not stc.establishment_id:
            stc.establishment_id = f"STC-{stc.pk:05d}"
            stc.save(update_fields=['establishment_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('staycations', '0007_add_booking_reference'),
    ]

    operations = [
        migrations.AddField(
            model_name='staycation',
            name='establishment_id',
            field=models.CharField(max_length=12, null=True, blank=True, unique=True, verbose_name='Establishment ID'),
        ),
        migrations.RunPython(backfill_establishment_ids),
        migrations.AlterField(
            model_name='staycation',
            name='establishment_id',
            field=models.CharField(editable=False, max_length=12, null=True, unique=True, verbose_name='Establishment ID'),
        ),
    ]