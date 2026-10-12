"""Make "an operational role always names its establishment" a database rule.

Added after ``0010_backfill_operational_roles`` has given every existing
assignment its ``establishment_type`` and ``establishment_required`` values, so
it is created against data that already satisfies it.

Spelled with ``establishment_required`` and ``establishment_id`` - both columns
of this table - because a CHECK constraint cannot reach across a relation to
``role_ref``. ``establishment_required`` is the mirror of the role's own flag,
kept up to date by ``SimulationRoleAssignment.save``.

INACTIVE rows are exempt. An assignment that has been stood down is a record of
what a student used to do, not a live grant of authority, so there is nothing to
protect by demanding an establishment. This is also what lets 0010 deactivate a
legacy operational assignment that has no establishment to give: without the
exemption, adding this constraint would fail on exactly the rows 0010 had to
repair.
"""

from django.db import migrations, models


def drop_stale_constraint(apps, schema_editor):
    """Clear out an older copy of this constraint before adding the current one.

    The definition changed to exempt INACTIVE rows, and ``AddConstraint`` refuses
    to reuse a name that is already taken. 0010 normally removes the old copy;
    this covers a database that still carries one regardless, so applying the
    corrected rule does not need manual SQL first.
    """
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        'ALTER TABLE simulation_simulationroleassignment '
        'DROP CONSTRAINT IF EXISTS sim_assign_establishment_required_for_role')


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0010_backfill_operational_roles'),
    ]

    operations = [
        migrations.RunPython(drop_stale_constraint, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='simulationroleassignment',
            constraint=models.CheckConstraint(
                condition=models.Q(('status', 'INACTIVE'),
                                    ('establishment_required', False),
                                    ('establishment_id__isnull', False),
                                    _connector='OR'),
                name='sim_assign_establishment_required_for_role',
            ),
        ),
    ]