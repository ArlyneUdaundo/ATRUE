from django.db import migrations, models
from django.db.models import F, Q


def backfill_shared_schedules(apps, schema_editor):
    """Promote legacy assignment windows to one window on their session.

    The first complete schedule by assignment creation order represents the
    schedule that originally created the session. Later per-assignment windows
    were the old behavior this migration replaces. Legacy columns remain intact
    for historical reference; runtime access no longer reads them.
    """
    Session = apps.get_model('simulation', 'SimulationSession')
    Assignment = apps.get_model('simulation', 'SimulationRoleAssignment')
    alias = schema_editor.connection.alias

    for session in Session.objects.using(alias).iterator():
        schedule = (
            Assignment.objects.using(alias)
            .filter(
                session_id=session.pk,
                simulation_date__isnull=False,
                start_time__isnull=False,
                end_time__isnull=False,
                end_time__gt=F('start_time'),
            )
            .order_by('assigned_at', 'pk')
            .values_list('simulation_date', 'start_time', 'end_time')
            .first()
        )
        if schedule:
            session.session_date, session.start_time, session.end_time = schedule
            session.save(update_fields=['session_date', 'start_time', 'end_time'])


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0035_task_outcomes'),
    ]

    operations = [
        migrations.AddField(
            model_name='simulationsession',
            name='session_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='simulationsession',
            name='start_time',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='simulationsession',
            name='end_time',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_shared_schedules, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='simulationsession',
            constraint=models.CheckConstraint(
                condition=(
                    Q(session_date__isnull=True, start_time__isnull=True,
                      end_time__isnull=True)
                    | Q(session_date__isnull=False, start_time__isnull=False,
                        end_time__isnull=False, end_time__gt=F('start_time'))
                ),
                name='sim_session_schedule_complete',
            ),
        ),
    ]
