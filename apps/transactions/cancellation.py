"""Shared customer cancellation-request flow across every booking service."""

import os
from decimal import Decimal
from pathlib import Path

from PIL import Image, UnidentifiedImageError
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

SERVICE_LABELS = {
    'airlines': 'Airline Booking',
    'hotels': 'Hotel Reservation',
    'resorts': 'Resort Reservation',
    'staycations': 'Staycation Reservation',
    'restaurants': 'Restaurant Reservation',
    'transportation': 'Transportation Booking',
    'landmarks': 'Landmark Ticket',
    'activities': 'Activity Booking',
    'tour_package': 'Tour Package Booking',
}

CANCELABLE_STATUSES = (
    BookingStatus.PENDING,
    BookingStatus.ON_HOLD,
    BookingStatus.RESERVED,
    BookingStatus.CONFIRMED,
    BookingStatus.MODIFIED,
)

PROOF_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
PROOF_MAX_BYTES = 2 * 1024 * 1024
PROOF_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png'}
PROOF_IMAGE_FORMATS = {'JPEG', 'PNG'}
PROOF_PDF_CONTENT_TYPE = 'application/pdf'
INVALID_PROOF_MESSAGE = 'Upload a JPG, JPEG, PNG, or PDF E-TICKET file (2 MB or smaller).'
OVERSIZED_PROOF_MESSAGE = 'Supporting file must be 2 MB or smaller.'


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


def _display_name(user):
    if user is None:
        return ''
    return user.get_full_name() or user.username


def _format_date(value):
    return value.strftime('%b %d, %Y') if value else ''


def _format_time(value):
    return value.strftime('%H:%M') if value else ''


def _format_datetime(value):
    if not value:
        return ''
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%b %d, %Y %H:%M')


def _add_detail(rows, label, value):
    if value is None:
        return
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return
    rows.append({'label': label, 'value': value})


def booking_summary(booking):
    """Return the booking-type details shown to the customer and reviewer."""
    if booking is None:
        return None

    app_label = booking._meta.app_label
    rows = []

    if app_label == 'hotels':
        entries = list(booking.room_entries.select_related('room__hotel').all())
        hotel = entries[0].room.hotel if entries else None
        _add_detail(rows, 'Guest', booking.primary_guest_name)
        _add_detail(rows, 'Hotel', getattr(hotel, 'name', ''))
        _add_detail(rows, 'Room(s)', ', '.join(
            entry.room.room_number for entry in entries))
        _add_detail(rows, 'Check-in', _format_date(booking.check_in))
        _add_detail(rows, 'Check-out', _format_date(booking.check_out))
        _add_detail(
            rows, 'Guests',
            f'{booking.number_of_adults} adult(s), '
            f'{booking.number_of_children} child(ren)')
    elif app_label == 'airlines':
        flight = getattr(booking, 'flight', None)
        seats = list(booking.seat_entries.all())
        passenger_names = [seat.passenger_name for seat in seats if seat.passenger_name]
        _add_detail(
            rows, 'Passenger',
            ', '.join(passenger_names) or _display_name(booking.passenger))
        _add_detail(
            rows, 'Airline',
            getattr(getattr(flight, 'airline', None), 'name', ''))
        if flight is not None:
            _add_detail(rows, 'Flight', str(flight))
            _add_detail(
                rows, 'Route', f'{flight.origin} to {flight.destination}')
            _add_detail(
                rows, 'Departure', _format_datetime(flight.departure_time))
        if booking.return_flight_id:
            _add_detail(rows, 'Return flight', str(booking.return_flight))
            _add_detail(
                rows, 'Return departure',
                _format_datetime(booking.return_flight.departure_time))
        _add_detail(rows, 'Trip type', booking.get_trip_type_display())
        if seats:
            _add_detail(rows, 'Seats', ', '.join(
                seat.seat_number for seat in seats if seat.seat_number))
            _add_detail(rows, 'Fare class', seats[0].get_fare_class_display())
    elif app_label == 'resorts':
        unit = getattr(booking, 'unit', None)
        _add_detail(rows, 'Guest', booking.primary_guest_name)
        _add_detail(
            rows, 'Resort', getattr(getattr(unit, 'resort', None), 'name', ''))
        _add_detail(
            rows, 'Unit',
            f'{unit.get_unit_type_display()} {unit.unit_number}'
            if unit is not None else '')
        _add_detail(rows, 'Check-in', _format_date(booking.check_in))
        _add_detail(rows, 'Check-out', _format_date(booking.check_out))
        _add_detail(
            rows, 'Guests',
            f'{booking.number_of_adults} adult(s), '
            f'{booking.number_of_children} child(ren)')
    elif app_label == 'staycations':
        staycation = getattr(booking, 'staycation', None)
        _add_detail(rows, 'Guest', booking.primary_guest_name)
        _add_detail(rows, 'Staycation', getattr(staycation, 'name', ''))
        _add_detail(rows, 'Check-in', _format_date(booking.check_in))
        _add_detail(rows, 'Check-out', _format_date(booking.check_out))
        _add_detail(
            rows, 'Guests',
            f'{booking.number_of_adults} adult(s), '
            f'{booking.number_of_children} child(ren)')
    elif app_label == 'restaurants':
        table = getattr(booking, 'table', None)
        _add_detail(rows, 'Guest', booking.primary_guest_name)
        _add_detail(
            rows, 'Restaurant',
            getattr(getattr(table, 'restaurant', None), 'name', ''))
        _add_detail(rows, 'Table', getattr(table, 'table_number', ''))
        _add_detail(
            rows, 'Date & time',
            _format_datetime(booking.reservation_datetime))
        _add_detail(rows, 'Guests', booking.number_of_guests)
    elif app_label == 'transportation':
        vehicle = getattr(booking, 'vehicle', None)
        _add_detail(rows, 'Guest', booking.primary_guest_name)
        _add_detail(
            rows, 'Agency', getattr(getattr(vehicle, 'agency', None), 'name', ''))
        _add_detail(
            rows, 'Vehicle',
            getattr(vehicle, 'vehicle_name', '') or str(vehicle or ''))
        _add_detail(rows, 'Pickup', booking.pickup_location)
        _add_detail(rows, 'Drop-off', booking.drop_off_location)
        _add_detail(rows, 'Schedule', _format_datetime(booking.schedule))
        _add_detail(rows, 'Passengers', booking.passengers)
    elif app_label == 'landmarks':
        _add_detail(rows, 'Visitor', booking.primary_guest_name)
        _add_detail(
            rows, 'Destination type', booking.get_destination_type_display())
        _add_detail(
            rows, 'Destination',
            getattr(booking.destination, 'name', '')
            if booking.destination_id else '')
        _add_detail(rows, 'Visit', _format_datetime(booking.visit_datetime))
        _add_detail(rows, 'Visitors', booking.number_of_visitors)
        _add_detail(
            rows, 'Guided tour', booking.get_guided_tour_display())
    elif app_label == 'activities':
        activity = getattr(booking, 'activity', None)
        _add_detail(rows, 'Participant', booking.primary_participant_name)
        _add_detail(rows, 'Activity', getattr(activity, 'name', ''))
        _add_detail(
            rows, 'Provider',
            getattr(getattr(activity, 'provider', None), 'name', ''))
        _add_detail(rows, 'Date', _format_date(booking.schedule_date))
        _add_detail(rows, 'Time', ' - '.join(filter(None, [
            _format_time(booking.start_time), _format_time(booking.end_time)])))
        _add_detail(rows, 'Participants', booking.participant_count)
    elif app_label == 'tour_package':
        package = getattr(booking, 'package', None)
        _add_detail(rows, 'Traveler', booking.primary_traveler_name)
        _add_detail(rows, 'Package', getattr(package, 'name', ''))
        _add_detail(rows, 'Travel date', _format_date(booking.travel_date))
        _add_detail(rows, 'Time', ' - '.join(filter(None, [
            _format_time(booking.start_time), _format_time(booking.end_time)])))
        _add_detail(rows, 'Travelers', booking.number_of_travelers)
    else:
        _add_detail(rows, 'Booking', str(booking))

    return {
        'service': SERVICE_LABELS.get(
            app_label, booking._meta.verbose_name.title()),
        'rows': rows,
    }


def resolve_owned_booking(user, app_label, model_name, object_id):
    booking = resolve_service_booking(app_label, model_name, object_id)
    if booking is None:
        return None
    if booking_owner_id(booking) != user.pk:
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
    if user is not None and booking_owner_id(booking) != user.pk:
        return False
    if booking.status not in CANCELABLE_STATUSES:
        return False
    return pending_cancellation_request(booking) is None


def _rewind(fileobj):
    try:
        fileobj.seek(0)
    except (AttributeError, OSError, ValueError):
        pass


def validate_proof(proof):
    if proof is None:
        raise ValidationError(
            'Upload proof that you own this booking, such as a valid ID or your e-ticket.')

    name = getattr(proof, 'name', '') or ''
    suffix = Path(name).suffix.lower()
    if suffix not in PROOF_EXTENSIONS:
        raise ValidationError(INVALID_PROOF_MESSAGE)

    size = getattr(proof, 'size', None)
    if size is not None and size > PROOF_MAX_BYTES:
        raise ValidationError(OVERSIZED_PROOF_MESSAGE)
    if size is not None and size <= 0:
        raise ValidationError(INVALID_PROOF_MESSAGE)

    content_type = (getattr(proof, 'content_type', '') or '').split(';', 1)[0].lower()

    try:
        if suffix == '.pdf':
            if content_type and content_type != PROOF_PDF_CONTENT_TYPE:
                raise ValidationError(INVALID_PROOF_MESSAGE)
            header = proof.read(5)
            _rewind(proof)
            if header != b'%PDF-':
                raise ValidationError(INVALID_PROOF_MESSAGE)
            return

        if content_type and content_type not in PROOF_IMAGE_CONTENT_TYPES:
            raise ValidationError(INVALID_PROOF_MESSAGE)
        with Image.open(proof) as image:
            if image.format not in PROOF_IMAGE_FORMATS:
                raise ValidationError(INVALID_PROOF_MESSAGE)
            image.verify()
        _rewind(proof)
        with Image.open(proof) as image:
            if image.format not in PROOF_IMAGE_FORMATS:
                raise ValidationError(INVALID_PROOF_MESSAGE)
            if image.format == 'JPEG' and suffix not in {'.jpg', '.jpeg'}:
                raise ValidationError(INVALID_PROOF_MESSAGE)
            if image.format == 'PNG' and suffix != '.png':
                raise ValidationError(INVALID_PROOF_MESSAGE)
            image.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ValidationError(INVALID_PROOF_MESSAGE) from None
    finally:
        _rewind(proof)


def request_cancellation(booking, user, *, reason, proof, proof_type):
    """Create a cancellation request that still needs staff approval."""
    owner_id = booking_owner_id(booking)
    if owner_id is None or owner_id != user.pk:
        raise ValidationError(
            'You can only request cancellation for your own booking.')
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
