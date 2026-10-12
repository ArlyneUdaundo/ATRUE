"""Offer the per-module guest / customer roles.

Section 6.3 keeps a single customer row (``PASSENGER_AIRLINE``), but the
simulation also admits per-module guest roles - a student booked in as the
guest of a resort, restaurant, staycation, landmark, tour package, land
transportation or activity, plus the hotel guest. They all act *on* the
platform (they never acquire an establishment), which is exactly how the
original ``GUEST_HOTEL`` behaved before it was retired.

This mirrors ``simulation.role_catalogue.sync_roles`` but writes through the
historical model so it runs inside ``migrate``.
"""

from django.db import migrations

from simulation.role_catalogue import ROLE_CATALOGUE, all_entries, permissions_for


def _stage_for(operation_category):
    return {
        'MANAGER': 'OVERSIGHT',
        'RESERVATION': 'INTAKE',
        'FRONT_DESK': 'FULFILLMENT',
        'CUSTOMER': 'INTAKE',
    }.get(operation_category, 'INTAKE')


def sync_role_catalogue(apps, schema_editor):
    Role = apps.get_model('simulation', 'Role')
    offered_codes = {entry[0] for entry in ROLE_CATALOGUE}

    for entry in all_entries():
        code, name, category, establishment_type, operation_category, order = entry[:6]
        defaults = {
            'name': name,
            'category': category,
            'establishment_type': establishment_type,
            'operation_category': operation_category,
            'requires_establishment': establishment_type is not None,
            'workflow_stage': _stage_for(operation_category),
            'sort_order': order,
            'permissions': permissions_for(code),
            'is_active': code in offered_codes,
        }
        role = Role.objects.filter(code=code).first()
        if role is None:
            Role.objects.create(code=code, **defaults)
        else:
            for field, value in defaults.items():
                setattr(role, field, value)
            role.save()


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0014_alter_role_category_and_more'),
    ]

    operations = [
        migrations.RunPython(sync_role_catalogue, migrations.RunPython.noop),
    ]