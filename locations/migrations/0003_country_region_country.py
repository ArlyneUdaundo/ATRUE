"""Promote the country from a hard-coded string to a real row.

Adds the ``Country`` table, hangs ``Region`` off it, and backfills the one
country the GeoNames Philippines dump describes (PCLI ``PH``) so the existing 17
regions gain a parent instead of being orphaned.

The FK is added nullable, backfilled, then made non-null, so this works on a
populated database without a default that has to be guessed at.
"""

from django.db import migrations, models
import django.db.models.deletion

# GeoNames PCLI row for the Philippines (country code "PH").
PHILIPPINES = {
    'geoname_id': 1694008,
    'code': 'PH',
    'name': 'Philippines',
    'asciiname': 'Republic of the Philippines',
    'latitude': 13.40882,
    'longitude': 122.56155,
    'feature_code': 'PCLI',
}


def create_country(apps, schema_editor):
    """Insert the country row and attach every region to it.

    This backfills an *existing* dataset. On a fresh database there is nothing to
    backfill, so no row is invented here: the country is reference data and is
    loaded by ``manage.py sync_geonames`` like every other level. Creating it in
    the migration would also mean every freshly created test database silently
    starts with a country in it.
    """
    Country = apps.get_model('locations', 'Country')
    Region = apps.get_model('locations', 'Region')
    if not Region.objects.exists():
        return

    country, _ = Country.objects.update_or_create(
        code=PHILIPPINES['code'],
        defaults={
            'geoname_id': PHILIPPINES['geoname_id'],
            'name': PHILIPPINES['name'],
            'asciiname': PHILIPPINES['asciiname'],
            'latitude': PHILIPPINES['latitude'],
            'longitude': PHILIPPINES['longitude'],
            'feature_code': PHILIPPINES['feature_code'],
        },
    )
    Region.objects.update(country=country)


def detach_country(apps, schema_editor):
    """Reverse the backfill; the column is dropped straight after."""
    Region = apps.get_model('locations', 'Region')
    Region.objects.update(country=None)


class Migration(migrations.Migration):

    dependencies = [
        ('locations', '0002_barangay_citymunicipality_province_region_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Country',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('geoname_id', models.BigIntegerField(help_text='GeoNames identifier for this place.', unique=True, verbose_name='GeoNames ID')),
                ('name', models.CharField(db_index=True, max_length=200)),
                ('asciiname', models.CharField(blank=True, default='', max_length=200, verbose_name='ASCII name')),
                ('latitude', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ('feature_code', models.CharField(blank=True, default='', max_length=8)),
                ('code', models.CharField(help_text='Two-letter country code, e.g. PH.', max_length=2, unique=True, verbose_name='ISO 3166-1 alpha-2')),
            ],
            options={
                'verbose_name': 'Country',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='region',
            name='country',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='regions', to='locations.country'),
        ),
        migrations.RunPython(create_country, detach_country),
        migrations.AlterField(
            model_name='region',
            name='country',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='regions', to='locations.country'),
        ),
    ]
