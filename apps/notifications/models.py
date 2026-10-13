"""Centralized, reusable notification store (Section 16).

Every simulation event that concerns a particular student raises one of these
rows through :func:`notifications.services.notify`. Notifications are strictly
per-recipient: the queryset is always filtered by ``recipient``, so one student
can never read another's (Section 16: "Do not expose one student's private
notifications to another student", and test 45).
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    """One message delivered to one student (or instructor)."""

    class Type(models.TextChoices):
        # -- session & role administration ----------------------------------
        ROLE_ASSIGNED = 'ROLE_ASSIGNED', 'Role assigned'
        ROLE_MODIFIED = 'ROLE_MODIFIED', 'Role modified'
        ROLE_REMOVED = 'ROLE_REMOVED', 'Role removed'
        SESSION_ACTIVATED = 'SESSION_ACTIVATED', 'Simulation session activated'
        SESSION_COMPLETED = 'SESSION_COMPLETED', 'Simulation session completed'
        # -- hotel workflow -------------------------------------------------
        HOTEL_RESERVATION_SUBMITTED = 'HOTEL_RESERVATION_SUBMITTED', 'Hotel reservation submitted'
        HOTEL_RESERVATION_APPROVED = 'HOTEL_RESERVATION_APPROVED', 'Hotel reservation approved'
        HOTEL_RESERVATION_REJECTED = 'HOTEL_RESERVATION_REJECTED', 'Hotel reservation rejected'
        HOTEL_RESERVATION_CANCELLED = 'HOTEL_RESERVATION_CANCELLED', 'Hotel reservation cancelled'
        # -- restaurant workflow -------------------------------------------
        RESTAURANT_RESERVATION_SUBMITTED = 'RESTAURANT_RESERVATION_SUBMITTED', 'Restaurant reservation submitted'
        RESTAURANT_RESERVATION_CONFIRMED = 'RESTAURANT_RESERVATION_CONFIRMED', 'Restaurant reservation confirmed'
        RESTAURANT_RESERVATION_REJECTED = 'RESTAURANT_RESERVATION_REJECTED', 'Restaurant reservation rejected'
        # -- airline workflow -----------------------------------------------
        FLIGHT_RESERVATION_SUBMITTED = 'FLIGHT_RESERVATION_SUBMITTED', 'Flight reservation submitted'
        FLIGHT_RESERVATION_APPROVED = 'FLIGHT_RESERVATION_APPROVED', 'Flight reservation approved'
        FLIGHT_RESERVATION_REJECTED = 'FLIGHT_RESERVATION_REJECTED', 'Flight reservation rejected'
        FLIGHT_TICKET_ISSUED = 'FLIGHT_TICKET_ISSUED', 'Simulated ticket generated'
        # -- travel agency ---------------------------------------------------
        TRAVEL_REQUEST_SUBMITTED = 'TRAVEL_REQUEST_SUBMITTED', 'Travel request submitted'
        TRAVEL_QUOTATION_READY = 'TRAVEL_QUOTATION_READY', 'Travel quotation ready'
        TRAVEL_REQUEST_ACCEPTED = 'TRAVEL_REQUEST_ACCEPTED', 'Travel quotation accepted'
        TRAVEL_REQUEST_DECLINED = 'TRAVEL_REQUEST_DECLINED', 'Travel quotation declined'
        # -- tour operator ---------------------------------------------------
        TOUR_REQUEST_SUBMITTED = 'TOUR_REQUEST_SUBMITTED', 'Tour request submitted'
        TOUR_REQUEST_APPROVED = 'TOUR_REQUEST_APPROVED', 'Tour request approved'
        TOUR_REQUEST_REJECTED = 'TOUR_REQUEST_REJECTED', 'Tour request rejected'
        TOUR_COMPLETED = 'TOUR_COMPLETED', 'Tour completed'
        # -- transportation ---------------------------------------------------
        TRANSPORT_REQUEST_SUBMITTED = 'TRANSPORT_REQUEST_SUBMITTED', 'Transportation request submitted'
        TRANSPORT_REQUEST_APPROVED = 'TRANSPORT_REQUEST_APPROVED', 'Transportation request approved'
        TRANSPORT_REQUEST_REJECTED = 'TRANSPORT_REQUEST_REJECTED', 'Transportation request rejected'
        TRANSPORT_DISPATCHED = 'TRANSPORT_DISPATCHED', 'Vehicle dispatched'
        # -- billing / transactions -------------------------------------------
        BILLING_READY = 'BILLING_READY', 'Transaction ready for billing'
        PAYMENT_RECORDED = 'PAYMENT_RECORDED', 'Simulated payment recorded'
        PAYMENT_REJECTED = 'PAYMENT_REJECTED', 'Simulated payment rejected'
        PAYMENT_REFUNDED = 'PAYMENT_REFUNDED', 'Simulated payment refunded'
        TRANSACTION_CLAIMED = 'TRANSACTION_CLAIMED', 'Transaction claimed'
        TRANSACTION_ESCALATED = 'TRANSACTION_ESCALATED', 'Transaction needs attention'
        GENERAL = 'GENERAL', 'Notice'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=40, choices=Type.choices, db_index=True)
    title = models.CharField(max_length=150, blank=True)
    message = models.TextField()

    # The transaction this concerns, when there is one. SET_NULL so a deleted
    # (rolled back) transaction never takes the notification queue with it.
    transaction = models.ForeignKey(
        'simulation.SimulationTransaction', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications')
    session = models.ForeignKey(
        'simulation.SimulationSession', on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications')
    establishment = models.ForeignKey(
        'establishments.Establishment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications')

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            # The inbox query: one recipient, unread first, newest first.
            models.Index(fields=['recipient', 'is_read', '-created_at'],
                         name='notif_inbox_idx'),
        ]

    def __str__(self):
        return f'{self.recipient}: {self.get_notification_type_display()}'

    def mark_read(self, *, save=True):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            if save:
                self.save(update_fields=['is_read', 'read_at'])
        return self


class EmailDelivery(models.Model):
    """Transactional email outbox. SENT means Brevo accepted the request."""
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        SENT = 'SENT', 'Accepted by provider'
        FAILED = 'FAILED', 'Failed'

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    booking = GenericForeignKey('content_type', 'object_id')
    event = models.CharField(max_length=40)
    recipient = models.EmailField(blank=True)
    idempotency_key = models.CharField(max_length=180, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    provider_message_id = models.CharField(max_length=255, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['status', 'created_at'], name='email_outbox_status_idx')]


class PasswordResetToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    email_status = models.CharField(max_length=12, default='PENDING')
    provider_message_id = models.CharField(max_length=255, blank=True)


class PasswordResetRequest(models.Model):
    email_digest = models.CharField(max_length=64, db_index=True)
    ip_digest = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
