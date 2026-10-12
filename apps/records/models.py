from django.conf import settings
from django.db import models

RECORD_TYPE_CHOICES = [
    ('BOOKING', 'Booking'),
    ('PAYMENT', 'Payment'),
    ('REFUND', 'Refund'),
    ('CANCELLATION', 'Cancellation'),
    ('MODIFICATION', 'Modification'),
    ('ADDITIONAL_TRANSACTION', 'Additional Transaction'),
]


class TransactionRecord(models.Model):
    """Audit log entry — each row is its own record with a unique
    reference number, actor, and timestamp, so this stays a table,
    not choices."""

    class RecordType(models.TextChoices):
        BOOKING = 'BOOKING', 'Booking'
        PAYMENT = 'PAYMENT', 'Payment'
        REFUND = 'REFUND', 'Refund'
        CANCELLATION = 'CANCELLATION', 'Cancellation'
        MODIFICATION = 'MODIFICATION', 'Modification'
        ADDITIONAL_TRANSACTION = 'ADDITIONAL_TRANSACTION', 'Additional Transaction'

    record_type = models.CharField(max_length=25, choices=RECORD_TYPE_CHOICES)
    reference_number = models.CharField(max_length=30, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='transaction_records')
    remarks = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.record_type} - {self.reference_number}"