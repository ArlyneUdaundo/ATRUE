from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flight',
            name='flight_number',
            field=models.CharField(max_length=20, unique=True),
        ),
    ]