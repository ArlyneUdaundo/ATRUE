"""Activate package-scoped Tour Package Manager and Front Desk roles.

The existing role codes were retired when package management moved to the
parent Tour Operator. Tour Packages now require their own assigned Manager,
Reservation Officer, and Front Desk. The former Operator code is retained as a
retired alias; assignments that already use it are preserved.
"""

from django.db import migrations

from simulation.role_catalogue import sync_roles


def sync_role_catalogue(apps, schema_editor):
    sync_roles()


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0022_simulationroleassignment_completed_at_and_more'),
    ]

    operations = [
        migrations.RunPython(sync_role_catalogue, migrations.RunPython.noop),
    ]
