"""Add the resort, restaurant, staycation and landmark roles to the catalogue.

Section 6.3 gives every establishment the same three jobs - Manager,
Reservation, Front Desk - and the four new establishment types (Resort,
Restaurant, Staycation, Landmark) were added to the picker without their three
roles. Without rows in the ``Role`` table an instructor cannot assign those jobs,
and ``simulation.W004`` calls out the gap as soon as it is introduced.

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
        ('simulation', '0012_alter_role_category_alter_role_establishment_type_and_more'),
    ]

    operations = [
        migrations.RunPython(sync_role_catalogue, migrations.RunPython.noop),
    ]