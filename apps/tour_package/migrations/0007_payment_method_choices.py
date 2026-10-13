from django.db import migrations, models


PAYMENT_METHOD_CHOICES = [
    ('GCASH', 'GCash'),
    ('MAYA', 'Maya'),
    ('BANK_TRANSFER', 'Bank Transfer'),
    ('CREDIT_CARD', 'Credit Card'),
    ('DEBIT_CARD', 'Debit Card'),
    ('PAYPAL', 'PayPal'),
    ('QR_PH', 'QR Ph'),
]


class Migration(migrations.Migration):
    dependencies = [('tour_package', '0006_tourpackage_establishment')]

    operations = [
        migrations.AlterField(
            model_name='booking', name='payment_method',
            field=models.CharField(max_length=15, choices=PAYMENT_METHOD_CHOICES, default='GCASH'),
        ),
    ]
