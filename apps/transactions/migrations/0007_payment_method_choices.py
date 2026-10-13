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
    dependencies = [('transactions', '0006_travelorder')]

    operations = [
        migrations.AlterField(
            model_name='payment', name='method',
            field=models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES),
        ),
        migrations.AlterField(
            model_name='travelorder', name='payment_method',
            field=models.CharField(blank=True, max_length=20, choices=PAYMENT_METHOD_CHOICES),
        ),
    ]
