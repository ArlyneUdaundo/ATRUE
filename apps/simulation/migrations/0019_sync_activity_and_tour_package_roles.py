"""Synchronise the role catalogue after the activity / tour package rework.

The four pre-resource roles (Activity Manager, Activity Front Desk Officer,
Tour Package Manager, Tour Package Front Desk Officer) are superseded by the
per-resource Reservation Officer + Operator pair and now live in
``RETIRED_ROLES``, while ``ACTIVITY_OPERATOR`` and ``TOUR_PACKAGE_OPERATOR``
are new active entries. ``sync_roles`` reconciles the ``Role`` table with the
catalogue: it creates the two operators, retires the four old roles (as
``is_active=False``, never a delete, so an existing assignment still resolves)
and refreshes names, stages and permissions.
"""

from django.db import migrations

from simulation.role_catalogue import sync_roles


def sync(apps, schema_editor):
    sync_roles()


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0018_seed_activity_and_tour_package_roles'),
    ]

    operations = [
        migrations.RunPython(sync, migrations.RunPython.noop),
    ]