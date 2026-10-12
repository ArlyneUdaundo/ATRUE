from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('resorts', '0012_reservation_assigned_to_reservation_confirmed_at_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='roomvilla',
            name='unit_number',
            field=models.CharField(max_length=100),
        ),
    ]
