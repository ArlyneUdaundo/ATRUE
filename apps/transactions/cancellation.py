"""Shared customer cancellation-request flow across every booking service."""

import os
from decimal import Decimal

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.utils import timezone

from atrue_core.models import BookingStatus

from .models import Cancellation

SERVICE_MODELS = {
    'airlines': 'booking',
    'hotels': 'booking',
    'resorts': 'reservation',
    'staycations': 'reservation',
    'restaurants': 'reservation',
    'transportation': 'booking',
    'landmarks': 'ticket',
    'activities': 'booking',
    'tour_package': 'booking',
}

SERVICE_NAMESPACES = {
    'airlines': 'airlines',
    'hotels': 'hotels',
    'resorts': 'resorts',
    'staycations': 'staycations',
    'restaurants': 'restaurants',
    'transportation': 'transportation',
    'landmarks': 'landmarks',
    'activities': 'activities',
    'tour_package': 'tour_package',
}

CANCELABLE_STATUSES = (
    BookingStatus.PENDING,
    BookingStatus.ON_HOLD,
    BookingStatus.RESERVED,
    BookingStatus.CONFIRMED,
    BookingStatus.MODIFIED,
)

PROOF_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.webp'}
PROOF_MAX_BYTES = 10 * 1024 * 1024


def resolve_service_booking(app_label, model_name, object_id):
    """Load a booking only when it belongs to a supported service app."""
    expected = SERVICE_MODELS.get(app_label)
    if expected is None or expected != model_name:
        return None
    try:
        model = django_apps.get_model(app_label, model_name)
    except LookupError:
        return None
    return model.objects.filter(pk=object_id).first()


def booking_owner_id(booking):
    return getattr(booking, 'customer_id', None) or getattr(
        booking, 'passenger_id', None)


def resolve_owned_booking(user, app_label, model_name, object_id):
    booking = resolve_service_booking(app_label, model_name, object_id)
    if booking is None:
        return None
    if booking_owner_id(booking) != user.pk and not user.is_staff:
        return None
    return booking


def latest_cancellation_request(booking):
    if booking is None or booking.pk is None:
        return None
    from django.contrib.contenttypes.models import ContentType
    content_type = ContentType.objects.get_for_model(booking)
    return (Cancellation.objects
            .filter(content_type=content_type, object_id=booking.pk)
            .order_by('-requested_at', '-pk')
            .first())


def pending_cancellation_request(booking):
    latest = latest_cancellation_request(booking)
    if latest is not None and latest.status == Cancellation.Status.REQUESTED:
        return latest
    return None


def can_request_cancellation(booking, user=None):
    if booking is None:
        return False
    if user is not None and booking_owner_id(booking) != user.pk and not user.is_staff:
        return False
    if booking.status not in CANCELABLE_STATUSES:
        return False
    return pending_cancellation_request(booking) is None


def validate_proof(proof):
    if proof is None:
        raise ValidationError(
            'Upload proof that you own this booking, such as a valid ID or your e-ticket.')
    name = (getattr(proof, 'name', '') or '').lower()
    extension = os.path.splitext(name)[1]
    if extension not in PROOF_EXTENSIONS:
        raise ValidationError(
            'Upload a PDF or image file (JPG, PNG, or WEBP) as proof.')
    if getattr(proof, 'size', 0) > PROOF_MAX_BYTES:
        raise ValidationError('The proof file must be 10 MB or smaller.')


def request_cancellation(booking, user, *, reason, proof, proof_type):
    """Create a cancellation request that still needs staff approval."""
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError('Enter the reason for cancelling this booking.')
    if booking.status == BookingStatus.CANCELLED:
        raise ValidationError('This booking is already cancelled.')
    if booking.status not in CANCELABLE_STATUSES:
        raise ValidationError('This booking can no longer be cancelled.')
    if pending_cancellation_request(booking) is not None:
        raise ValidationError(
            'A cancellation request for this booking is already waiting for review.')
    if proof_type not in Cancellation.ProofType.values:
        raise ValidationError('Select the type of proof you are uploading.')
    validate_proof(proof)

    cancellation = Cancellation(
        requested_by=user,
        status=Cancellation.Status.REQUESTED,
        reason=reason,
        proof_type=proof_type,
        proof=proof,
    )
    cancellation.link_to_booking(booking)
    cancellation.save()
    return cancellation


def _release_booking_resource(booking):
    if booking._meta.app_label != 'hotels':
        return
    from hotels.models import Room
    for room in booking.rooms.all():
        room.status = Room.RoomStatus.AVAILABLE
        room.save(update_fields=['status'])


def process_generic_cancellation(cancellation, actor, *, approve, remarks=''):
    """Approve or reject a non-airline cancellation request."""
    from atrue_core.services import bill_for_booking, cancel_booking, refund_payment

    review_remarks = (remarks or '').strip()
    if cancellation.status != Cancellation.Status.REQUESTED:
        raise ValidationError('This cancellation request has already been reviewed.')
    booking = cancellation.booking
    if booking is None:
        raise ValidationError('The booking for this request no longer exists.')

    now = timezone.now()
    cancellation.processed_by = actor
    cancellation.processed_at = now
    cancellation.responded_at = now
    cancellation.review_remarks = review_remarks

    if not approve:
        cancellation.status = Cancellation.Status.REJECTED
        cancellation.save()
        return {'approved': False, 'refunded': Decimal('0')}

    if booking.status not in CANCELABLE_STATUSES:
        raise ValidationError('This booking can no longer be cancelled.')

    refunded = Decimal('0')
    bill = bill_for_booking(booking)
    if bill is not None:
        from .models import Payment
        payments = bill.payments.filter(
            status__in=[Payment.Status.PAID, Payment.Status.PARTIALLY_REFUNDED],
        ).order_by('paid_at', 'pk')
        for payment in payments:
            take = payment.remaining_refundable
            if take <= 0:
                continue
            refund_payment(
                payment=payment, user=actor, amount=take,
                description=f'Refund for cancelled booking {booking.booking_reference}')
            refunded += take

    cancel_booking(
        booking, actor, release_callback=lambda: _release_booking_resource(booking),
        reason=cancellation.reason, cancellation=cancellation)
    cancellation.refund_amount = refunded
    cancellation.status = Cancellation.Status.APPROVED
    cancellation.save()
    return {'approved': True, 'refunded': refunded}
