from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('restaurants', '0013_alter_reservation_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='table',
            name='cost_per_table',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]
