from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transportation', '0006_add_booking_reference'),
    ]

    operations = [
        migrations.AlterField(
            model_name='agency',
            name='address',
            field=models.CharField(blank=True, help_text='Street address line', max_length=255),
        ),
        migrations.AddField(
            model_name='agency',
            name='barangay',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='agency',
            name='municipality',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='agency',
            name='province',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]