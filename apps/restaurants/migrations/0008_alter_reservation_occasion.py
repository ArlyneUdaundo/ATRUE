from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('restaurants', '0007_add_booking_reference'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reservation',
            name='occasion',
            field=models.CharField(choices=[('NONE', 'None'), ('BIRTHDAY', 'Birthday'), ('ANNIVERSARY', 'Anniversary'), ('BUSINESS', 'Business'), ('DATE', 'Date / Romantic'), ('GRADUATION', 'Graduation'), ('FAMILY_REUNION', 'Family Reunion'), ('DEBUT', 'Debut'), ('ENGAGEMENT', 'Engagement'), ('CHRISTENING', 'Christening'), ('HOLIDAY_CELEBRATION', 'Holiday Celebration'), ('CASUAL_DINING', 'Casual Dining'), ('OTHER', 'Other')], default='NONE', max_length=30),
        ),
    ]