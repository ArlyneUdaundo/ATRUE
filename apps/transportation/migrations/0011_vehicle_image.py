from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transportation', '0010_booking_assigned_to_booking_confirmed_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='image',
            field=models.ImageField(blank=True, upload_to='transport_vehicles/'),
        ),
    ]
