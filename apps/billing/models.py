"""Centralized *simulated* billing (Section 15).

Nothing in this app touches a payment gateway, a bank or a card network, and
nothing here claims a real booking or ticket was made (Section 19 rules 17-18).
A :class:`SimulatedBill` is a classroom artefact: a Billing Officer types the
amount the establishment would have charged, and the platform records that a
student recorded it.

This is deliberately a *separate* model from ``transactions.Bill``, which is the
platform's real commercial billing and is untouched by the simulation. Sharing
one table would mean simulated classroom payments mixing with the live booking
ledger, so the two never see each other's rows.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


def _bill_reference():
    import uuid

    return f'SIM-BILL-{uuid.uuid4().hex[:8].upper()}'


def _payment_reference():
    import uuid

    return f'SIM-PAY-{uuid.uuid4().hex[:8].upper()}'


class SimulatedBill(models.Model):
    """The amount a student must settle for one approved simulation transaction."""

    class Status(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PENDING_VERIFICATION = 'PENDING_VERIFICATION', 'Pending Verification'
        PAID = 'PAID', 'Paid (Simulated)'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'
        REFUNDED = 'REFUNDED', 'Refunded (Simulated)'

    #: Section 15.3 statuses that still expect money to be recorded.
    OPEN_STATUSES = frozenset({Status.UNPAID, Status.PENDING_VERIFICATION})
    #: Statuses that are final; a second payment against them is refused
    #: (Section 15.4: "Prevent duplicate simulated payment processing").
    CLOSED_STATUSES = frozenset({Status.PAID, Status.REJECTED, Status.CANCELLED,
                                  Status.REFUNDED})

    bill_reference = models.CharField(
        max_length=30, unique=True, editable=False, default=_bill_reference,
        verbose_name='Bill Reference')

    transaction = models.OneToOneField(
        'simulation.SimulationTransaction', on_delete=models.CASCADE,
        related_name='simulated_bill',
        help_text='One bill per transaction - a transaction cannot be settled twice '
                  'through two different bills.')
    establishment = models.ForeignKey(
        'establishments.Establishment', on_delete=models.PROTECT, related_name='simulated_bills')
    session = models.ForeignKey(
        'simulation.SimulationSession', on_delete=models.CASCADE, related_name='simulated_bills')
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='simulated_bills')

    items = models.JSONField(default=list, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=22, choices=Status.choices,
                              default=Status.UNPAID, db_index=True)

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='issued_simulated_bills')
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['establishment', 'status'], name='simbill_queue_idx'),
            models.Index(fields=['session', 'status'], name='simbill_session_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_paid__gte=0),
                name='simbill_amount_paid_non_negative'),
        ]

    def __str__(self):
        return self.bill_reference

    def calculate(self, items):
        """Store the line items and recompute the totals."""
        from decimal import Decimal, InvalidOperation

        self.items = list(items or [])

        def amount_of(item):
            try:
                return Decimal(item.get('amount', item.get('total', 0)) or 0)
            except (InvalidOperation, TypeError, ValueError):
                return Decimal(0)

        self.total_amount = sum((amount_of(item) for item in self.items), Decimal(0))
        self.refresh_balance()
        return self

    def refresh_balance(self):
        from decimal import Decimal

        self.balance_due = max(Decimal(0), Decimal(self.total_amount)
                               - Decimal(self.amount_paid))
        return self.balance_due

    @property
    def is_settled(self):
        return self.status == self.Status.PAID

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES


class SimulatedPayment(models.Model):
    """One simulated payment a Billing Officer recorded against a bill."""

    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        GCASH = 'GCASH', 'GCash'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
        CARD = 'CARD', 'Card'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Verification'
        PAID = 'PAID', 'Paid (Simulated)'
        REJECTED = 'REJECTED', 'Rejected'
        REFUNDED = 'REFUNDED', 'Refunded (Simulated)'

    payment_reference = models.CharField(
        max_length=30, unique=True, editable=False, default=_payment_reference,
        verbose_name='Payment Reference')

    bill = models.ForeignKey(SimulatedBill, on_delete=models.CASCADE, related_name='payments')
    transaction = models.ForeignKey(
        'simulation.SimulationTransaction', on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.CASH)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PAID, db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='simulated_payments')
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    recorded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['bill', 'status'], name='simpay_bill_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='simpay_amount_positive'),
        ]

    def __str__(self):
        return self.payment_reference


class BillingEvent(models.Model):
    """Append-only billing history (Section 15.4: "Record every billing status change")."""

    bill = models.ForeignKey(
        SimulatedBill, on_delete=models.CASCADE, related_name='events')
    transaction = models.ForeignKey(
        'simulation.SimulationTransaction', on_delete=models.CASCADE,
        related_name='billing_events')
    action = models.CharField(max_length=40)
    from_status = models.CharField(max_length=22, blank=True)
    to_status = models.CharField(max_length=22, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='billing_events')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.bill.bill_reference}: {self.action}'

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('BillingEvent rows are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('BillingEvent rows cannot be deleted.')