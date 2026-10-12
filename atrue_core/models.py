"""Shared, cross-app building blocks for the ATRUE booking platform.

The booking lifecycle fields (status, payer, billing) are defined ONCE here and
inherited by every booking/reservation/ticket model so they are never repeated
per module.
"""
from django.db import models

import uuid


def make_booking_reference(prefix="ATR"):
    """Generate a unique booking reference (used by model save() overrides)."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class BookingStatus(models.TextChoices):
    """Shared booking lifecycle statuses (BR-016, BR-033, BR-090, BR-092)."""

    PENDING = 'PENDING', 'Pending'
    ON_HOLD = 'ON_HOLD', 'On Hold (Awaiting Payment)'
    RESERVED = 'RESERVED', 'Reserved'
    CONFIRMED = 'CONFIRMED', 'Confirmed'
    DECLINED = 'DECLINED', 'Declined'
    RETURNED = 'RETURNED', 'Returned'
    MODIFIED = 'MODIFIED', 'Modified'
    CHECKED_IN = 'CHECKED_IN', 'Checked-In'
    CHECKED_OUT = 'CHECKED_OUT', 'Checked-Out'
    USED = 'USED', 'Used'
    CANCELLED = 'CANCELLED', 'Cancelled'
    COMPLETED = 'COMPLETED', 'Completed'


class BookingFieldsMixin(models.Model):
    """Shared booking-lifecycle fields reused by every booking/reservation model."""

    booking_reference = models.CharField(
        max_length=30, unique=True, editable=False, default=make_booking_reference,
        help_text="Unique booking reference (BR-017, BR-033, BR-090)",
    )
    status = models.CharField(
        max_length=20, choices=BookingStatus.choices, default=BookingStatus.PENDING
    )
    special_requests = models.TextField(blank=True)
    payer_name = models.CharField(max_length=200, blank=True)
    payer_contact = models.CharField(max_length=200, blank=True)
    total_bill = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    assigned_to = models.ForeignKey(
        'accounts.User', null=True, blank=True, related_name='%(app_label)s_%(class)s_assigned',
        on_delete=models.SET_NULL
    )
    reserved_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, related_name='%(app_label)s_%(class)s_reserved',
        on_delete=models.SET_NULL
    )
    confirmed_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, related_name='%(app_label)s_%(class)s_confirmed',
        on_delete=models.SET_NULL
    )
    reserved_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    declined_reason = models.TextField(blank=True)
    hold_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True