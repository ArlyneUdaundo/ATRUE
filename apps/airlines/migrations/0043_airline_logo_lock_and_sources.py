from django.db import migrations, models
import django.db.models.deletion


def lock_existing_primary_logos(apps, schema_editor):
    AirlinePhoto = apps.get_model('airlines', 'AirlinePhoto')
    AirlinePhoto.objects.filter(is_primary=True).update(is_locked_logo=True)


def unlock_existing_primary_logos(apps, schema_editor):
    AirlinePhoto = apps.get_model('airlines', 'AirlinePhoto')
    AirlinePhoto.objects.filter(is_locked_logo=True).update(is_locked_logo=False)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0042_passenger_details_persistence'),
    ]

    operations = [
        migrations.AddField(
            model_name='airlinephoto',
            name='is_locked_logo',
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name='airlinephoto',
            name='source_url',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='airlinephoto',
            name='license_name',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='airlinephoto',
            name='attribution',
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.RunPython(lock_existing_primary_logos, unlock_existing_primary_logos),
        migrations.AlterField(
            model_name='airlinephoto',
            name='airline',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='photos', to='airlines.airline'),
        ),
        migrations.AddConstraint(
            model_name='airlinephoto',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_locked_logo', True)),
                fields=('airline',), name='one_locked_logo_per_airline'),
        ),
    ]
