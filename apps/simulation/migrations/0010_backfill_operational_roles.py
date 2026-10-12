"""Backfill the three-operational-roles model onto existing data.

Sections 6.3 and 6.4 replace a long list of job-specific roles with exactly
three per establishment - Manager, Reservation, Front Desk - each of which must
name the specific establishment it applies to. That changes two things in the
database:

* ``Role`` learns ``operation_category`` and ``requires_establishment``, and
  every row in it must be re-classified by the catalogue.
* ``SimulationRoleAssignment`` learns ``establishment_type`` and
  ``establishment_required``, which existing rows have to be given before the
  database can enforce the rule.

Nothing is deleted. A code that is no longer offered becomes ``is_active=False``
so assignments that already name it keep resolving to a real ``Role`` row.
"""

from django.db import migrations

from simulation.role_catalogue import ROLE_CATALOGUE, all_entries, permissions_for


def _stage_for(operation_category):
    """The stage a role's work is routed at, derived from its category.

    These are the stored *codes*, not the human labels: ``field.choices`` maps a
    code to its label, so indexing it would write "Supervision" into a column
    that the engine compares against ``OVERSIGHT``.
    """
    return {
        'MANAGER': 'OVERSIGHT',
        'RESERVATION': 'INTAKE',
        'FRONT_DESK': 'FULFILLMENT',
        'CUSTOMER': 'INTAKE',
    }.get(operation_category, 'INTAKE')


def sync_role_catalogue(apps, schema_editor):
    """Re-classify every catalogue row: category, establishment scope, permissions.

    Mirrors ``simulation.role_catalogue.sync_roles`` but writes through the
    *historical* model. The catalogue itself is imported rather than copied so
    this migration and the management command cannot disagree about what a role
    is - the same reasoning as ``0006_seed_role_catalogue``.
    """
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
            # Retired roles keep their row so an older assignment still
            # resolves, but must not be offered on the assignment form.
            'is_active': code in offered_codes,
        }
        role = Role.objects.filter(code=code).first()
        if role is None:
            Role.objects.create(code=code, **defaults)
        else:
            for field, value in defaults.items():
                setattr(role, field, value)
            role.save()

    # Anything outside the catalogue stops being offered, but keeps its row so a
    # historical assignment still resolves.
    Role.objects.filter(is_active=True).exclude(
        code__in=[entry[0] for entry in all_entries()]).update(is_active=False)


def drop_establishment_constraint(apps, schema_editor):
    """Remove the establishment constraint if the database already has it.

    This migration is the one that repairs rows the constraint would reject: an
    operational assignment with no establishment can only be fixed by standing it
    down, and a strict constraint demands an establishment of every row regardless
    of status. So the backfill below has to run without it.

    It is dropped rather than assumed absent because a database can already carry
    the constraint while this migration is still unapplied - created by an earlier
    attempt whose migration record did not commit, or by hand. Dropping is safe
    here: ``0011_assign_establishment_constraint`` re-adds it, in its corrected
    form, as soon as the backfill has finished.
    """
    table = 'simulation_simulationroleassignment'
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        'ALTER TABLE %s DROP CONSTRAINT IF EXISTS '
        'sim_assign_establishment_required_for_role' % table)


def backfill_assignments(apps, schema_editor):
    """Give every assignment the establishment type and the "needs one" flag.

    ``establishment_type`` mirrors ``establishment.type``;
    ``establishment_required`` mirrors the role's ``requires_establishment``.
    Both are derived on write by ``SimulationRoleAssignment.save``, so this only
    has to cover rows that already exist.

    An operational role with no establishment is the "Manager of everywhere" row
    that would defeat every scoping check downstream. Rather than inventing an
    establishment for it, the assignment is deactivated and the reason recorded,
    so the instructor sees what happened and can reassign the student properly.
    """
    Assignment = apps.get_model('simulation', 'SimulationRoleAssignment')
    Role = apps.get_model('simulation', 'Role')

    roles = {role.code: role for role in Role.objects.all()}
    establishments = {
        establishment.pk: establishment.type
        for establishment in apps.get_model('establishments', 'Establishment').objects.all()
    }

    orphaned = 0
    for assignment in Assignment.objects.select_related('role_ref', 'establishment').iterator():
        role = assignment.role_ref or roles.get(assignment.role)
        establishment_type = establishments.get(assignment.establishment_id)
        requires_establishment = bool(role and role.requires_establishment)

        assignment.establishment_type = establishment_type
        assignment.establishment_required = requires_establishment

        if requires_establishment and assignment.establishment_id is None:
            assignment.status = 'INACTIVE'
            orphaned += 1

        assignment.save(update_fields=['establishment_type', 'establishment_required',
                                       'status'])

    if orphaned:
        print('  de-activated %d assignment(s) whose role needs an establishment '
              'but had none named' % orphaned)


def forwards(apps, schema_editor):
    # Order matters: the constraint has to go before the rows it would reject are
    # rewritten, and 0011 puts it back once they are clean.
    drop_establishment_constraint(apps, schema_editor)
    sync_role_catalogue(apps, schema_editor)
    backfill_assignments(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0009_role_operation_category_role_requires_establishment_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]