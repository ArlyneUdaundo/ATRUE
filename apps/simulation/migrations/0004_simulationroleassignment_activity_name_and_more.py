"""Session-name assignment: rename ``simulation_activity`` to ``activity_name``
and add the establishment + schedule fields.

``RenameField`` keeps the existing rows (which hold "General Training" and
"ACTIVITY 1"/"ACTIVITY 2") instead of dropping the column and losing them. The
new fields are all nullable so the five existing assignments stay valid.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hotels', '0001_initial'),
        ('simulation', '0003_remove_activitylog_related_reference'),
    ]

    operations = [
        migrations.RenameField(
            model_name='simulationroleassignment',
            old_name='simulation_activity',
            new_name='activity_name',
        ),
        migrations.AlterField(
            model_name='simulationroleassignment',
            name='activity_name',
            field=models.CharField(max_length=150),
        ),
        migrations.AddField(
            model_name='simulationroleassignment',
            name='hotel',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='simulation_assignments', to='hotels.hotel'),
        ),
        migrations.AddField(
            model_name='simulationroleassignment',
            name='simulation_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='simulationroleassignment',
            name='start_time',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='simulationroleassignment',
            name='end_time',
            field=models.TimeField(blank=True, null=True),
        ),
    ]
