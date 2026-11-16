from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0010_cancellation_refund_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='cancellation',
            name='proof',
            field=models.FileField(blank=True, upload_to='cancellation_proofs/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='cancellation',
            name='proof_type',
            field=models.CharField(blank=True, choices=[
                ('ID', 'Valid government-issued ID'),
                ('ETICKET', 'E-Ticket / Booking voucher'),
                ('PAYMENT', 'Proof of payment'),
                ('OTHER', 'Other supporting document'),
            ], max_length=10),
        ),
    ]
