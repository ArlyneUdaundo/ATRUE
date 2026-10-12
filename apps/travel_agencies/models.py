"""Travel agency workflow records (Section 12).

The other four categories already had a reservation table to reuse - ``hotels``,
``airlines``, ``tour_package`` and ``transportation`` all ship a ``Booking``.
A travel agency did not, so this app owns the one record the agency workflow
needs: a customer's request, the consultant's itinerary, and the simulated
quotation the customer then accepts or declines.

These rows are the *subject* of a ``simulation.SimulationTransaction``; they hold
no status of their own beyond the customer's decision, because the operational
status (PENDING -> UNDER_REVIEW -> CONFIRMED ...) belongs to the transaction
engine and is what the students act on.
"""

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models
from django.utils import timezone


def _money(value):
    try:
        return Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _request_reference():
    """Short, quotable request reference (TRQ-XXXXXXXX).

    Students read these out to each other across a classroom, so the reference is
    short and uppercase; uniqueness comes from the column's unique constraint
    rather than a counter that could drift out of step.
    """
    import uuid

    return f'TRQ-{uuid.uuid4().hex[:8].upper()}'


def _quotation_reference():
    import uuid

    return f'QT-{uuid.uuid4().hex[:8].upper()}'


class TravelAgencyRequest(models.Model):
    """A customer's travel request to a travel agency (Section 12.2)."""

    class Decision(models.TextChoices):
        #: No decision yet - the consultant has not sent a quotation.
        NONE = 'NONE', 'Awaiting Quotation'
        QUOTED = 'QUOTED', 'Quotation Sent'
        ACCEPTED = 'ACCEPTED', 'Quotation Accepted'
        DECLINED = 'DECLINED', 'Quotation Declined'
        WITHDRAWN = 'WITHDRAWN', 'Withdrawn by Customer'

    request_reference = models.CharField(
        max_length=30, unique=True, editable=False, default=_request_reference,
        verbose_name='Request Reference')

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='travel_agency_requests')
    establishment = models.ForeignKey(
        'establishments.Establishment', on_delete=models.PROTECT,
        related_name='travel_requests',
        help_text='The agency the request was sent to.')

    destination = models.CharField(max_length=150)
    origin = models.CharField(max_length=150, blank=True)
    travel_date = models.DateField(null=True, blank=True)
    return_date = models.DateField(null=True, blank=True)
    party_size = models.PositiveIntegerField(default=1)
    budget = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    #: Free-form requirements as the customer stated them (Section 12.2).
    requirements = models.TextField(blank=True)
    decision = models.CharField(max_length=10, choices=Decision.choices,
                                default=Decision.NONE, db_index=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['establishment', 'decision'], name='trav_req_queue_idx'),
            models.Index(fields=['customer', '-created_at'], name='trav_req_customer_idx'),
        ]

    def __str__(self):
        return self.request_reference

    def clean(self):
        super().clean()
        errors = {}
        if self.travel_date and self.return_date and self.return_date < self.travel_date:
            errors['return_date'] = 'The return date cannot be earlier than the travel date.'
        if self.party_size < 1:
            errors['party_size'] = 'At least one traveller is required.'
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    @property
    def nights(self):
        if not (self.travel_date and self.return_date):
            return 0
        return max(0, (self.return_date - self.travel_date).days)

    @property
    def current_quotation(self):
        """The latest quotation the consultant sent, or None."""
        return self.quotations.order_by('-version', '-created_at').first()


class TravelItinerary(models.Model):
    """The consultant's proposed day-by-day plan (Section 12.3).

    One request may be re-quoted (a destination is out of budget, the dates
    move), so itineraries are versioned rather than edited in place and each one
    keeps its own revision number. That is what makes "all quotation changes
    must be recorded" (Section 12.5) true by construction.
    """

    request = models.ForeignKey(
        TravelAgencyRequest, on_delete=models.CASCADE, related_name='itineraries')
    version = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=150)
    day_number = models.PositiveSmallIntegerField(default=1)
    activity = models.CharField(max_length=200)
    destination = models.CharField(max_length=150, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='travel_itineraries')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['version', 'day_number', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['request', 'version', 'day_number'],
                name='unique_itinerary_day_per_version'),
        ]

    def __str__(self):
        return f'{self.request.request_reference} v{self.version} day {self.day_number}'


class TravelQuotation(models.Model):
    """A simulated quotation prepared by the consultant (Section 12.3).

    Quotation amounts are *simulated*: nothing here touches a payment gateway
    and no money moves until a Billing Officer records a simulated payment
    against the transaction (Section 15.1).
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent to Customer'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        DECLINED = 'DECLINED', 'Declined'
        SUPERSEDED = 'SUPERSEDED', 'Superseded'

    quotation_reference = models.CharField(
        max_length=30, unique=True, editable=False, default=_quotation_reference,
        verbose_name='Quotation Reference')

    request = models.ForeignKey(
        TravelAgencyRequest, on_delete=models.CASCADE, related_name='quotations')
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.DRAFT, db_index=True)

    #: Line items as {label, quantity, rate, amount}; kept as JSON so a
    #: consultant is not forced into a fixed package shape.
    items = models.JSONField(default=list, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valid_until = models.DateField(null=True, blank=True)
    terms = models.TextField(blank=True)

    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='prepared_quotations')
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-version', '-created_at']
        constraints = [
            # One live quotation per version; a re-quote bumps the version.
            models.UniqueConstraint(
                fields=['request', 'version'], name='unique_quotation_version_per_request'),
        ]

    def __str__(self):
        return self.quotation_reference

    def calculate(self, items):
        """Store line items and recompute the totals (mirror of Bill.calculate)."""
        self.items = list(items or [])
        self.subtotal = sum((_money(item.get('amount', 0)) for item in self.items),
                            Decimal(0))
        self.total = max(Decimal(0), self.subtotal - _money(self.discount))
        return self

    @property
    def is_decided(self):
        return self.status in (self.Status.ACCEPTED, self.Status.DECLINED)

    def accept(self, customer):
        """Record the customer's acceptance; only the requester may accept."""
        if self.request.customer_id != getattr(customer, 'pk', None):
            raise PermissionError('Only the customer who raised the request may accept it.')
        if self.status != self.Status.SENT:
            raise ValueError('Only a sent quotation can be accepted.')
        self.status = self.Status.ACCEPTED
        self.save(update_fields=['status', 'updated_at'])
        return self

    def decline(self, customer):
        """Record the customer's decline; only the requester may decline."""
        if self.request.customer_id != getattr(customer, 'pk', None):
            raise PermissionError('Only the customer who raised the request may decline it.')
        if self.status != self.Status.SENT:
            raise ValueError('Only a sent quotation can be declined.')
        self.status = self.Status.DECLINED
        self.save(update_fields=['status', 'updated_at'])
        return self