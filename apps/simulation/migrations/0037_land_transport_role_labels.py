from django.db import migrations


LAND_TRANSPORT_ROLE_LABELS = {
    'TRANSPORT_MANAGER': 'Land Transportation Manager',
    'TRANSPORT_RESERVATION_AGENT': 'Land Transportation Reservation Officer',
    'TRANSPORT_FRONT_DESK': 'Land Transportation Front Desk Officer',
    'TRANSPORT_BILLING_OFFICER': 'Land Transportation Billing Officer',
    'TRANSPORTATION_OWNER': 'Land Transportation Owner',
}


def update_land_transport_role_labels(apps, schema_editor):
    Role = apps.get_model('simulation', 'Role')
    for code, name in LAND_TRANSPORT_ROLE_LABELS.items():
        Role.objects.filter(code=code).update(name=name, is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ('simulation', '0036_shared_session_task_schedule'),
    ]

    operations = [
        migrations.RunPython(
            update_land_transport_role_labels,
            migrations.RunPython.noop,
        ),
    ]
