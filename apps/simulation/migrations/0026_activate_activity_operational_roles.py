"""Activate the separated Activity Manager and Front Desk roles."""

from django.db import migrations

from simulation.role_catalogue import sync_activity_roles


def sync_role_catalogue(apps, schema_editor):
    sync_activity_roles()


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0025_update_activity_role_labels'),
    ]

    operations = [
        migrations.RunPython(sync_role_catalogue, migrations.RunPython.noop),
    ]
