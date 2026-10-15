from django.db import migrations


BILLING_ROLES = {
    'HOTEL': ('HOTEL_BILLING_OFFICER', 'Hotel Billing Officer', 'HOTEL', 780),
    'RESORT': ('RESORT_BILLING_OFFICER', 'Resort Billing Officer', 'RESORT', 781),
    'RESTAURANT': ('RESTAURANT_BILLING_OFFICER', 'Restaurant Billing Officer', 'RESTAURANT', 782),
    'STAYCATION': ('STAYCATION_BILLING_OFFICER', 'Staycation Billing Officer', 'STAYCATION', 783),
    'LANDMARK': ('LANDMARK_BILLING_OFFICER', 'Landmark Billing Officer', 'LANDMARK', 784),
    'AIRLINE': ('AIRLINE_BILLING_OFFICER', 'Airline Billing Officer', 'AIRLINE', 785),
    'TRAVEL_AGENCY': ('TRAVEL_AGENCY_BILLING_OFFICER', 'Travel Agency Billing Officer', 'TRAVEL_AGENCY', 786),
    'TOUR_OPERATOR': ('TOUR_OPERATOR_BILLING_OFFICER', 'Tour Operator Billing Officer', 'TOUR_OPERATOR', 787),
    'TOUR_PACKAGE': ('TOUR_PACKAGE_BILLING_OFFICER', 'Tour Package Billing Officer', 'TOUR_PACKAGE', 788),
    'ACTIVITY': ('ACTIVITY_BILLING_OFFICER', 'Activity Billing Officer', 'ACTIVITY', 789),
    'TRANSPORTATION': ('TRANSPORT_BILLING_OFFICER', 'Transportation Billing Officer', 'TRANSPORTATION', 790),
}


def split_billing_roles(apps, schema_editor):
    Role = apps.get_model('simulation', 'Role')
    Assignment = apps.get_model('simulation', 'SimulationRoleAssignment')

    typed_roles = {}
    for establishment_type, (code, name, category, order) in BILLING_ROLES.items():
        role, _ = Role.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'category': category,
                'establishment_type': establishment_type,
                'operation_category': 'BILLING',
                'workflow_stage': 'BILLING',
                'requires_establishment': True,
                'permissions': [
                    'Review paid bookings for the assigned establishment',
                    'Verify payment before reservation confirmation',
                ],
                'is_active': True,
                'sort_order': order,
            },
        )
        typed_roles[establishment_type] = role

    for assignment in Assignment.objects.filter(
            role__in=('BILLING_OFFICER', 'TOUR_BILLING_OFFICER'),
            status='ACTIVE').select_related('establishment'):
        establishment = assignment.establishment
        typed_role = typed_roles.get(establishment.type) if establishment else None
        if typed_role is None:
            assignment.status = 'INACTIVE'
            assignment.save(update_fields=['status'])
            continue

        duplicate = Assignment.objects.filter(
            student_id=assignment.student_id,
            session_id=assignment.session_id,
            role_ref_id=typed_role.pk,
            establishment_id=establishment.pk,
            status='ACTIVE',
        ).exclude(pk=assignment.pk).exists()
        if duplicate:
            assignment.status = 'INACTIVE'
            assignment.save(update_fields=['status'])
            continue

        assignment.role = typed_role.code
        assignment.role_ref = typed_role
        assignment.establishment_type = establishment.type
        assignment.establishment_required = True
        assignment.save(update_fields=[
            'role', 'role_ref', 'establishment_type', 'establishment_required',
        ])

    Role.objects.filter(code='BILLING_OFFICER').update(
        is_active=False, requires_establishment=False,
    )
    Role.objects.filter(code='TOUR_BILLING_OFFICER').update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ('simulation', '0029_billing_officer_establishment_scope'),
    ]

    operations = [
        migrations.RunPython(split_billing_roles, migrations.RunPython.noop),
    ]
