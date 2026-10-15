from django.db import migrations


def seed_new_assignable_roles(apps, schema_editor):
    Role = apps.get_model('simulation', 'Role')
    from simulation.role_catalogue import ROLE_CATALOGUE, permissions_for

    workflow_stages = {
        'MANAGER': 'OVERSIGHT',
        'RESERVATION': 'INTAKE',
        'FRONT_DESK': 'FULFILLMENT',
        'BILLING': 'BILLING',
        'CUSTOMER': 'INTAKE',
    }
    for code, name, category, establishment_type, operation_category, sort_order in ROLE_CATALOGUE:
        if code != 'BILLING_OFFICER' and not code.endswith('_OWNER'):
            continue
        Role.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'category': category,
                'establishment_type': establishment_type,
                'operation_category': operation_category,
                'workflow_stage': workflow_stages.get(operation_category, 'INTAKE'),
                'requires_establishment': bool(
                    establishment_type and not code.endswith('_OWNER')),
                'permissions': permissions_for(code),
                'is_active': True,
                'sort_order': sort_order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('simulation', '0027_alter_role_operation_category_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_new_assignable_roles, migrations.RunPython.noop),
    ]
