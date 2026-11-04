from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('simulation', '0033_simulationassignmenttaskcompletion'),
    ]

    operations = [
        migrations.AddField(
            model_name='simulationassignmenttaskcompletion',
            name='booking_reference',
            field=models.CharField(
                blank=True, db_index=True, default='', max_length=50,
                help_text='Booking that verified this task, when the action produced one.'),
        ),
    ]
