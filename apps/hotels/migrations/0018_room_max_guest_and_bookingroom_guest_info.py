from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('hotels', '0017_seed_baguio_hotel_photo'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='max_guest_capacity',
            field=models.PositiveIntegerField(default=0, help_text='Maximum guests allowed in the room. 0 means the standard capacity is the maximum.'),
        ),
        migrations.AddField(model_name='bookingroom', name='guest_first_name', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='bookingroom', name='guest_middle_name', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='bookingroom', name='guest_last_name', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='bookingroom', name='guest_email', field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name='bookingroom', name='guest_contact', field=models.CharField(blank=True, max_length=30)),
        migrations.AddField(model_name='bookingroom', name='guest_special_request', field=models.TextField(blank=True)),
    ]
