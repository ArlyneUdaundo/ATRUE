from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0044_backfill_seeded_airline_logos'),
    ]

    operations = [
        migrations.AddField(
            model_name='bookingseat',
            name='passenger_classification',
            field=models.CharField(blank=True, choices=[('adult', 'Adult'), ('child', 'Child'), ('infant', 'Infant'), ('senior', 'Senior Citizen'), ('pwd', 'Person with Disability (PWD)')], default='', max_length=10),
        ),
    ]
