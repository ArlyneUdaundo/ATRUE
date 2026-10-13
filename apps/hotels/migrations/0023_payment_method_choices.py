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
    dependencies = [('hotels', '0022_booking_assigned_to_booking_confirmed_at_and_more')]

    operations = [
        migrations.AlterField(
            model_name='payment', name='mode_of_payment',
            field=models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES),
        ),
    ]
