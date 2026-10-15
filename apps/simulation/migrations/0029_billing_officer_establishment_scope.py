from django.db import migrations


def scope_billing_officers(apps, schema_editor):
    Role = apps.get_model('simulation', 'Role')
    Assignment = apps.get_model('simulation', 'SimulationRoleAssignment')

    Role.objects.filter(code='BILLING_OFFICER').update(
        requires_establishment=True,
    )
    Assignment.objects.filter(
        role='BILLING_OFFICER', status='ACTIVE', establishment__isnull=False,
    ).update(establishment_required=True)
    # Older Billing Officer assignments had no establishment and effectively
    # applied to every property. Retire those broad assignments so instructors
    # can replace them with one specific assignment per establishment.
    Assignment.objects.filter(
        role='BILLING_OFFICER', status='ACTIVE', establishment__isnull=True,
    ).update(status='INACTIVE')


class Migration(migrations.Migration):
    dependencies = [
        ('simulation', '0028_seed_billing_and_owner_roles'),
    ]

    operations = [
        migrations.RunPython(scope_billing_officers, migrations.RunPython.noop),
    ]
