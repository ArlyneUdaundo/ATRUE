"""Seed the role catalogue (Section 6.3) and backfill legacy assignments.

Run automatically so a fresh PostgreSQL database has a usable role catalogue
without anyone having to remember to run a management command first.
"""

from django.db import migrations

from simulation.role_catalogue import ROLE_CATALOGUE, permissions_for


def seed_roles(apps, schema_editor):
    """Create every catalogue row (mirrors ``simulation.sync_role_catalogue``).

    The rows are written through the *historical* model, but the catalogue data
    itself comes from ``simulation.role_catalogue`` rather than being copied
    here: it is pure data, so importing it is safe, and it means the migration
    and the ``seed_roles`` command can never disagree about what a role is.
    """
    Role = apps.get_model('simulation', 'Role')

    for code, name, category, establishment_type, stage, order in ROLE_CATALOGUE:
        defaults = {
            'name': name,
            'category': category,
            'establishment_type': establishment_type,
            'workflow_stage': stage,
            'sort_order': order,
            'permissions': permissions_for(code),
            'is_active': True,
        }
        role = Role.objects.filter(code=code).first()
        if role is None:
            Role.objects.create(code=code, **defaults)
            continue
        for field, value in defaults.items():
            setattr(role, field, value)
        role.save()

    # Any code kept as a row purely so historical assignments stay readable
    # stops being offered as a choice.
    known = {code for code, *_ in ROLE_CATALOGUE}
    Role.objects.exclude(code__in=known).update(is_active=False)


def backfill_legacy_assignments(apps, schema_editor):
    """Attach pre-existing assignments to a session, role row and establishment.

    Before this migration an assignment knew only a free-text ``activity_name``,
    a role code and (optionally) a hotel. Section 5.2 requires a session and
    Section 6.4 a centralised establishment, so each distinct ``activity_name``
    becomes one session owned by whoever assigned the work (falling back to the
    student, because ``SimulationSession.instructor`` is non-null and
    ``PROTECT``ed).
    """
    Session = apps.get_model('simulation', 'SimulationSession')
    Assignment = apps.get_model('simulation', 'SimulationRoleAssignment')
    Role = apps.get_model('simulation', 'Role')
    Establishment = apps.get_model('establishments', 'Establishment')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Hotel = apps.get_model('hotels', 'Hotel')

    roles = {role.code: role.pk for role in Role.objects.all()}
    hotel_content_type = ContentType.objects.get_for_model(Hotel, for_concrete_model=False)

    sessions_by_name = {}
    for assignment in Assignment.objects.filter(session__isnull=True).iterator():
        name = assignment.activity_name or 'General Training'
        session = sessions_by_name.get(name)
        if session is None:
            session = Session.objects.create(
                name=name,
                description='Reconstructed automatically from assignments created '
                            'before simulation sessions existed.',
                instructor_id=assignment.assigned_by_id or assignment.student_id,
                status='DRAFT',
            )
            sessions_by_name[name] = session

        assignment.session_id = session.pk
        assignment.role_ref_id = roles.get(assignment.role)

        if assignment.hotel_id and assignment.establishment_id is None:
            hotel = Hotel.objects.filter(pk=assignment.hotel_id).first()
            if hotel is not None:
                establishment, _ = Establishment.objects.get_or_create(
                    entity_type=hotel_content_type,
                    entity_id=hotel.pk,
                    defaults={
                        'name': hotel.name,
                        'type': 'HOTEL',
                        'status': 'ACTIVE' if hotel.status == 'ACTIVE' else 'INACTIVE',
                    },
                )
                assignment.establishment_id = establishment.pk

        assignment.save(update_fields=['session', 'role_ref', 'establishment'])


def backfill_linked_establishments(apps, schema_editor):
    """Give every seeded catalogue row a centralised ``Establishment``.

    Section 6.4 asks for one establishment registry across all five
    establishments, but the hotel/airline/transportation apps already own their
    own rows. Linking them here means the instructor's establishment picker has
    something to assign students to immediately after a deploy, instead of
    having to hand-build it.

    Fields are read by name rather than through ``str(row)``: a historical model
    has no ``__str__``, so that produced names like "Airline object (1)".
    """
    Establishment = apps.get_model('establishments', 'Establishment')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    #: ``(establishment type, app, model, address parts)``
    linked = (
        ('HOTEL', 'hotels', 'Hotel', ('barangay', 'municipality', 'province', 'country')),
        ('AIRLINE', 'airlines', 'Airline', ()),
        ('TRANSPORTATION', 'transportation', 'Agency', ('address',)),
    )

    for establishment_type, app_label, model_name, address_parts in linked:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover - all three apps are installed
            continue

        content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
        for row in model.objects.all().iterator():
            if Establishment.objects.filter(
                    entity_type=content_type, entity_id=row.pk).exists():
                continue

            # A catalogue row's own status decides whether students may be routed
            # to it; anything unrecognised is treated as inactive rather than
            # quietly assumed active.
            status = 'ACTIVE' if getattr(row, 'status', '') == 'ACTIVE' else 'INACTIVE'

            Establishment.objects.create(
                name=(row.name or '')[:150],
                type=establishment_type,
                status=status,
                address=', '.join(
                    part for part in (getattr(row, name, '') or ''
                                      for name in address_parts) if part
                )[:255],
                contact_number=(getattr(row, 'contact_number', '') or '')[:20],
                email=(getattr(row, 'email', '') or '')[:254],
                entity_type=content_type,
                entity_id=row.pk,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0034_airport_timezones_and_segment_timing'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('hotels', '0020_correct_room_1508_rate'),
        ('simulation', '0005_simulationtransaction_transactionevent_and_more'),
        ('transportation', '0009_agency_country'),
    ]

    operations = [
        migrations.RunPython(seed_roles, migrations.RunPython.noop),
        migrations.RunPython(backfill_linked_establishments, migrations.RunPython.noop),
        migrations.RunPython(backfill_legacy_assignments, migrations.RunPython.noop),
    ]