from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone
from atrue_core.payment_methods import PAYMENT_METHOD_CHOICES, payment_method_label

import uuid


def _ref(prefix="TRX"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _bill_ref():
    return _ref('BILL')


def _pay_ref():
    return _ref('PAY')


def _rct_ref():
    return _ref('RCT')


def _trx_ref():
    return _ref('TRX')

def _order_ref():
    return _ref('ORD')


BILL_STATUS_CHOICES = [
    ('UNPAID', 'Unpaid'),
    ('PARTIALLY_PAID', 'Partially Paid'),
    ('FULLY_PAID', 'Fully Paid'),
]

PAYMENT_STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('PAID', 'Paid'),
    ('REFUNDED', 'Refunded'),
]

CANCELLATION_STATUS_CHOICES = [
    ('REQUESTED', 'Requested'),
    ('APPROVED', 'Approved'),
    ('REJECTED', 'Rejected'),
]

ADDITIONAL_TRANSACTION_TYPE_CHOICES = [
    ('ADDITIONAL_SERVICE', 'Additional Service'),
    ('FOOD_BEVERAGE', 'Food and Beverage'),
    ('TRANSPORTATION', 'Transportation'),
    ('ACTIVITY', 'Activity'),
    ('EQUIPMENT_RENTAL', 'Equipment Rental'),
    ('ROOM_FACILITY', 'Room/Facility Charge'),
    ('BAGGAGE', 'Extra Baggage'),
    ('EXTENSION', 'Extension of Stay'),
    ('UPGRADE', 'Upgrade'),
    ('OTHER', 'Other Charges'),
]

ADDITIONAL_TRANSACTION_STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('PAID', 'Paid'),
    ('PARTIALLY_PAID', 'Partially Paid'),
    ('UNPAID', 'Unpaid'),
    ('CANCELLED', 'Cancelled'),
    ('REFUNDED', 'Refunded'),
]


class BookingLinked(models.Model):
    """Shared fields linking a financial record to its booking (BR-090 & REQ-029)."""

    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    booking = GenericForeignKey('content_type', 'object_id')

    class Meta:
        abstract = True

    def link_to_booking(self, booking):
        if booking is None:
            return
        from django.contrib.contenttypes.models import ContentType
        self.content_type = ContentType.objects.get_for_model(booking)
        self.object_id = booking.pk


class Bill(models.Model):
    """Official billing record for a booking (BR-017, BR-087 to BR-088, BR-093).

    Centralized billing: a booking may have exactly one bill which stores the
    confirmed charges (line items), paid amount and balance due. Real
    financial record with its own reference, items, and balance, so this
    stays a table, not choices.
    """

    class Status(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
        FULLY_PAID = 'FULLY_PAID', 'Fully Paid'

    bill_reference = models.CharField(
        max_length=30, unique=True, editable=False, default=_bill_ref
    )
    booking = GenericForeignKey('content_type', 'object_id')
    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    object_id = models.PositiveBigIntegerField(null=True, blank=True)

    def link_to_booking(self, booking):
        if booking is None:
            return
        self.content_type = ContentType.objects.get_for_model(booking)
        self.object_id = booking.pk
        return self

    service = models.CharField(max_length=30)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='bills'
    )
    items = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=BILL_STATUS_CHOICES, default='UNPAID')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def calculate(self, items):
        """Store line items and recompute totals (BR-088)."""
        self.items = items
        self.total_amount = sum(
            self._amount(item) for item in items
        )
        self._refresh()
        return self

    @staticmethod
    def _amount(item):
        try:
            return _money(item.get('amount', item.get('total', 0)))
        except (AttributeError, TypeError):
            return 0

    def _refresh(self):
        from decimal import Decimal
        paid = Decimal(self.amount_paid)
        self.balance_due = (self.total_amount - paid) if self.total_amount >= 0 else 0
        if self.balance_due <= 0 and self.total_amount > 0:
            self.status = 'FULLY_PAID'
        elif paid > 0:
            self.status = 'PARTIALLY_PAID'
        else:
            self.status = 'UNPAID'
        if self.total_amount == 0:
            self.status = 'FULLY_PAID'
        if self.pk is None:
            self.save()
        else:
            self.save(update_fields=['balance_due', 'status'])

    def add_payment(self, amount):
        from decimal import Decimal
        self.amount_paid = (Decimal(self.amount_paid) + Decimal(amount))
        self.save(update_fields=['amount_paid'])
        self._refresh()

    def __str__(self):
        return f"Bill {self.bill_reference}"


def _money(value):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


class Payment(BookingLinked):
    """Payment record linked to a booking or bill (BR-089 to BR-092, BR-033).
    Each row is a real payment event with its own reference and amount, so
    this stays a table, not choices."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'
        REFUNDED = 'REFUNDED', 'Refunded'

    payment_reference = models.CharField(
        max_length=30, unique=True, editable=False,         default=_pay_ref
    )
    bill = models.ForeignKey(Bill, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-paid_at', '-id']

    def get_method_display(self):
        return payment_method_label(self.method)

    def __str__(self):
        return f"Payment {self.payment_reference}"


class Cancellation(BookingLinked):
    """Each row is a specific cancellation request tied to a booking, with
    its own requester and timestamps, so this stays a table."""

    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', 'Requested'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cancellations'
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=CANCELLATION_STATUS_CHOICES, default='REQUESTED')
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Cancellation {self.pk}"


class Receipt(models.Model):
    """Official receipt issued for a completed payment (BR-092). Each row
    is its own issued document, so this stays a table."""

    receipt_reference = models.CharField(
        max_length=30, unique=True, editable=False,         default=_rct_ref
    )
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name='receipts'
    )
    bill = models.ForeignKey(
        Bill, on_delete=models.SET_NULL, null=True, blank=True, related_name='receipts'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='receipts'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    remark = models.CharField(max_length=255, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_at']

    def __str__(self):
        return f"Receipt {self.receipt_reference}"


class AdditionalTransaction(BookingLinked):
    """Separate transactions requested after the original booking (BR-018, BR-019).

    These remain independently identifiable from the original booking and never
    silently merge into it. Each row is its own charge with a unique
    reference, so this stays a table.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'
        PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
        UNPAID = 'UNPAID', 'Unpaid'
        CANCELLED = 'CANCELLED', 'Cancelled'
        REFUNDED = 'REFUNDED', 'Refunded'

    class TransactionType(models.TextChoices):
        ADDITIONAL_SERVICE = 'ADDITIONAL_SERVICE', 'Additional Service'
        FOOD_BEVERAGE = 'FOOD_BEVERAGE', 'Food and Beverage'
        TRANSPORTATION = 'TRANSPORTATION', 'Transportation'
        ACTIVITY = 'ACTIVITY', 'Activity'
        EQUIPMENT_RENTAL = 'EQUIPMENT_RENTAL', 'Equipment Rental'
        ROOM_FACILITY = 'ROOM_FACILITY', 'Room/Facility Charge'
        BAGGAGE = 'BAGGAGE', 'Extra Baggage'
        EXTENSION = 'EXTENSION', 'Extension of Stay'
        UPGRADE = 'UPGRADE', 'Upgrade'
        OTHER = 'OTHER', 'Other Charges'

    transaction_reference = models.CharField(
        max_length=30, unique=True, editable=False,         default=_trx_ref
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='additional_transactions'
    )
    transaction_type = models.CharField(
        max_length=30, choices=ADDITIONAL_TRANSACTION_TYPE_CHOICES, default='ADDITIONAL_SERVICE'
    )
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=ADDITIONAL_TRANSACTION_STATUS_CHOICES, default='UNPAID')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"AdditionalTransaction {self.transaction_reference}"

class TravelOrder(models.Model):
    """One Shopee-style checkout transaction that groups multiple ATRUE bookings.

    A customer can add hotel rooms, flights, restaurant reservations, activities,
    transport, packages, resorts, staycations and attraction tickets to one cart
    and pay them as one combined transaction.
    """
    class Status(models.TextChoices):
        CART = 'CART', 'Cart'
        PENDING = 'PENDING', 'Pending Payment'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        COMPLETED = 'COMPLETED', 'Completed'

    order_reference = models.CharField(max_length=30, unique=True, editable=False, default=_order_ref)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='travel_orders')
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True)
    bill = models.OneToOneField('Bill', on_delete=models.SET_NULL, null=True, blank=True, related_name='travel_order')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.order_reference


class TravelOrderItem(models.Model):
    """A booking line inside one combined TravelOrder transaction."""
    order = models.ForeignKey(TravelOrder, on_delete=models.CASCADE, related_name='items')
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    booking = GenericForeignKey('content_type', 'object_id')
    service = models.CharField(max_length=30)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.order.order_reference} - {self.description}"
