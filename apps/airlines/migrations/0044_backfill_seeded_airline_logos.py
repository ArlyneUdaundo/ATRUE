"""Attach bundled official marks to existing seeded airlines without a logo."""

from django.core.files.storage import default_storage
from django.db import migrations

from airlines.logo_data import seed_airline_logos


def backfill_missing_seeded_logos(apps, schema_editor):
    seed_airline_logos(
        apps.get_model('airlines', 'Airline'),
        apps.get_model('airlines', 'AirlinePhoto'),
        default_storage,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0043_airline_logo_lock_and_sources'),
    ]

    operations = [
        migrations.RunPython(
            backfill_missing_seeded_logos,
            migrations.RunPython.noop,
        ),
    ]
