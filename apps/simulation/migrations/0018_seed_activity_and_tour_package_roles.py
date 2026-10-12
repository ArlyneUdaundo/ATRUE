from django.db import migrations

from simulation.role_catalogue import permissions_for


ROLE_ROWS = (
    ('ACTIVITY_MANAGER', 'Activity Manager', 'ACTIVITY', 'ACTIVITY',
     'MANAGER', 'OVERSIGHT', 710),
    ('ACTIVITY_RESERVATION_OFFICER', 'Activity Reservation Officer',
     'ACTIVITY', 'ACTIVITY', 'RESERVATION', 'INTAKE', 720),
    ('ACTIVITY_FRONT_DESK_OFFICER', 'Activity Front Desk Officer',
     'ACTIVITY', 'ACTIVITY', 'FRONT_DESK', 'FULFILLMENT', 730),
    ('TOUR_PACKAGE_MANAGER', 'Tour Package Manager', 'TOUR', 'TOUR_PACKAGE',
     'MANAGER', 'OVERSIGHT', 740),
    ('TOUR_PACKAGE_RESERVATION_OFFICER', 'Tour Package Reservation Officer',
     'TOUR', 'TOUR_PACKAGE', 'RESERVATION', 'INTAKE', 750),
    ('TOUR_PACKAGE_FRONT_DESK_OFFICER', 'Tour Package Front Desk Officer',
     'TOUR', 'TOUR_PACKAGE', 'FRONT_DESK', 'FULFILLMENT', 760),
)


def seed_operational_roles(apps, schema_editor):
    Role = apps.get_model('simulation', 'Role')
    for code, name, category, establishment_type, operation, stage, order in ROLE_ROWS:
        Role.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'category': category,
                'establishment_type': establishment_type,
                'operation_category': operation,
                'workflow_stage': stage,
                'requires_establishment': True,
                'permissions': permissions_for(code),
                'is_active': True,
                'sort_order': order,
            },
        )


def retire_operational_roles(apps, schema_editor):
    Role = apps.get_model('simulation', 'Role')
    Role.objects.filter(code__in=[row[0] for row in ROLE_ROWS]).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0017_alter_role_establishment_type_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_operational_roles, retire_operational_roles),
    ]
