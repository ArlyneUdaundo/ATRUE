"""Brevo transactional mail helpers and a small database-backed outbox."""
import base64
import json
import logging
import os
import re
import urllib.request
import urllib.error
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)
BREVO_URL = 'https://api.brevo.com/v3/smtp/email'


def _email_error_code(exc):
    """Return a safe, compact diagnostic code without storing provider messages."""
    message = str(exc)
    if message in {'EMAIL_CONFIGURATION_MISSING', 'RECIPIENT_UNAVAILABLE',
                   'ETICKET_GENERATION_FAILED', 'BOOKING_NOT_CONFIRMED'}:
        return message
    if re.fullmatch(r'BREVO_HTTP_\d{3}(?:_[A-Z0-9_-]{1,40})?', message):
        return message
    return type(exc).__name__.upper()[:80]


def _brevo_send(*, to_email, to_name, subject, html, text, idempotency_key,
                attachments=None):
    api_key = getattr(settings, 'BREVO_API_KEY', '')
    sender_email = getattr(settings, 'BREVO_SENDER_EMAIL', '')
    sender_name = getattr(settings, 'BREVO_SENDER_NAME', '')
    if not api_key or not sender_email or not sender_name:
        raise RuntimeError('EMAIL_CONFIGURATION_MISSING')
    body = {
        'sender': {'email': sender_email, 'name': sender_name},
        'to': [{'email': to_email, **({'name': to_name} if to_name else {})}],
        'subject': subject,
        'htmlContent': html,
        'headers': {'Idempotency-Key': str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))},
    }
    if attachments:
        body['attachment'] = [
            {'name': item['name'], 'content': base64.b64encode(item['content']).decode('ascii')}
            for item in attachments
        ]
    req = urllib.request.Request(
        BREVO_URL, data=json.dumps(body).encode(), method='POST',
        headers={
            'api-key': api_key, 'accept': 'application/json',
            'content-type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode() or '{}')
    except urllib.error.HTTPError as exc:
        provider_code = ''
        try:
            error_body = json.loads(exc.read().decode() or '{}')
            raw_code = error_body.get('code', '')
            provider_code = re.sub(r'[^A-Za-z0-9_-]', '', str(raw_code))[:40].upper()
        except (ValueError, AttributeError, UnicodeDecodeError):
            pass
        safe_code = f'BREVO_HTTP_{exc.code}'
        if provider_code:
            safe_code += f'_{provider_code}'
        raise RuntimeError(safe_code) from exc
    return result.get('messageId', '')


def _ticketable(booking):
    module = booking._meta.app_label
    if module == 'airlines':
        from airlines.ticket import TICKETABLE_STATUSES
        return booking.status in TICKETABLE_STATUSES
    from atrue_core.etickets import TICKETABLE_STATUSES
    return module in TICKETABLE_STATUSES and booking.status in TICKETABLE_STATUSES[module]


def _build_ticket_pdf(booking):
    """Render the system's actual persisted booking e-ticket to a PDF attachment."""
    try:
        module = booking._meta.app_label
        if module == 'airlines':
            from io import BytesIO
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.units import mm
            from reportlab.platypus import SimpleDocTemplate
            from airlines.ticket import build_ticket_context
            from airlines.ticket_pdf_itinerary import _build as build_story

            context = build_ticket_context(booking)
            buffer = BytesIO()
            document = SimpleDocTemplate(
                buffer, pagesize=landscape(A4), leftMargin=14 * mm,
                rightMargin=14 * mm, topMargin=9 * mm, bottomMargin=10 * mm,
                title=f"ATRUE E-Ticket {booking.booking_reference}",
                author='ATRUE Travel & Tours (Simulation)',
            )
            story, on_page = build_story(context)
            document.build(story, onFirstPage=on_page, onLaterPages=on_page)
            content = buffer.getvalue()
            buffer.close()
            filename = context['download_name']
        else:
            from atrue_core.services import bill_for_booking
            from atrue_core.etickets import build_eticket_context
            from atrue_core.eticket_pdf import build_pdf_response

            bill = bill_for_booking(booking)
            context = build_eticket_context(module, booking, bill)
            response = build_pdf_response(context)
            content = response.content
            filename = context['download_name']
        if not content.startswith(b'%PDF'):
            raise ValueError('Generated ticket is not a PDF')
        filename = re.sub(r'[^A-Za-z0-9_.-]', '_', str(filename))[:120]
        return {'name': filename or 'ATRUE-eticket.pdf', 'content': content}
    except Exception as exc:
        logger.warning('E-ticket PDF generation failed; booking=%s', booking.pk)
        raise RuntimeError('ETICKET_GENERATION_FAILED') from exc


def _send_and_record(delivery_id):
    from .models import EmailDelivery
    row = EmailDelivery.objects.filter(pk=delivery_id).first()
    if not row or row.status == EmailDelivery.Status.SENT:
        return
    row.attempts += 1
    try:
        booking = row.booking
        user = (getattr(booking, 'customer', None) or getattr(booking, 'passenger', None)
                or getattr(booking, 'user', None))
        if not row.recipient or user is None:
            raise RuntimeError('RECIPIENT_UNAVAILABLE')
        details = _booking_details(booking)
        details.update({'customer_name': user.get_full_name() or user.get_username(),
                        'booking_reference': getattr(booking, 'booking_reference', booking.pk),
                        'contact_email': row.recipient})
        subject = f"Booking received: {details['booking_reference']}"
        context = {**details, 'brand': 'ATRUE Simulation Portal'}
        html = render_to_string('emails/booking_confirmation.html', context)
        plain = render_to_string('emails/booking_confirmation.txt', context)
        ticket_pdf = _build_ticket_pdf(booking)
        message_id = _brevo_send(
            to_email=row.recipient, to_name=details['customer_name'], subject=subject,
            html=html, text=plain, idempotency_key=row.idempotency_key,
            attachments=[ticket_pdf],
        )
        row.status = EmailDelivery.Status.SENT
        row.provider_message_id = message_id
        row.error_code = ''
    except Exception as exc:
        # Only a fixed category is stored. Never persist provider bodies, PII or secrets.
        row.status = EmailDelivery.Status.FAILED
        row.error_code = _email_error_code(exc)
        logger.warning('Booking email failed; delivery_id=%s code=%s', row.pk, row.error_code)
    row.save(update_fields=['attempts', 'status', 'provider_message_id', 'error_code', 'updated_at'])


def queue_booking_confirmation(booking):
    """Create one delivery record per persisted booking; send only post-commit."""
    from .models import EmailDelivery
    from django.db import IntegrityError
    if not _ticketable(booking):
        # A pending or unconfirmed booking has no valid e-ticket to send yet.
        return None
    model = booking._meta.concrete_model
    key = f'booking-confirmation:{model._meta.label_lower}:{booking.pk}'
    customer = (getattr(booking, 'customer', None) or getattr(booking, 'passenger', None)
                or getattr(booking, 'user', None))
    recipient = (getattr(customer, 'email', '') or '').strip() if customer else ''
    try:
        row, created = EmailDelivery.objects.get_or_create(
            idempotency_key=key,
            defaults={'content_type': ContentType.objects.get_for_model(model),
                      'object_id': booking.pk, 'event': 'BOOKING_CONFIRMATION',
                      'recipient': recipient},
        )
    except Exception:
        logger.exception('Could not queue booking email; model=%s pk=%s', model._meta.label_lower, booking.pk)
        return
    if created:
        transaction.on_commit(lambda: _send_and_record(row.pk))


def _booking_details(booking):
    """Collect non-empty, already stored booking fields without guessing values."""
    labels = (
        ('service', ('hotel', 'resort', 'staycation', 'restaurant', 'tour_package',
                     'activity', 'landmark', 'flight', 'vehicle', 'table')),
        ('travel_date', ('travel_date', 'visit_date', 'reservation_date', 'check_in', 'date')),
        ('guests', ('number_of_guests', 'guests', 'guest_count', 'passengers', 'adults')),
        ('status', ('get_status_display', 'status')),
    )
    result = {}
    for label, names in labels:
        for name in names:
            value = getattr(booking, name, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if value not in (None, ''):
                result[label] = str(value)
                break
    flight = getattr(booking, 'flight', None)
    if flight is not None:
        route = ' to '.join(str(part) for part in (getattr(flight, 'origin', ''),
                                                    getattr(flight, 'destination', '')) if part)
        flight_label = ' '.join(str(part) for part in (getattr(flight, 'flight_number', ''), route) if part)
        if flight_label:
            result['itinerary'] = flight_label
        departure = getattr(flight, 'departure_time', None)
        if departure:
            result['travel_date'] = str(departure)
    for date_field in ('check_in', 'check_out', 'schedule_date', 'visit_date', 'departure_date'):
        value = getattr(booking, date_field, None)
        if value:
            result[date_field] = str(value)
    guest_count = next((getattr(booking, field, None) for field in
                        ('participant_count', 'passenger_count', 'number_of_guests',
                         'number_of_adults', 'guests')
                        if getattr(booking, field, None) not in (None, '')), None)
    if guest_count is not None:
        result['guests'] = str(guest_count)
    for relation in ('unit', 'staycation', 'restaurant', 'package', 'tour_package', 'activity'):
        related = getattr(booking, relation, None)
        if related is not None:
            result['service'] = str(related)
            break
    rooms = getattr(booking, 'rooms', None)
    if rooms is not None and hasattr(rooms, 'all'):
        room_labels = [str(room) for room in rooms.all()[:5]]
        if room_labels:
            result['rooms'] = ', '.join(room_labels)
    try:
        from atrue_core.services import bill_for_booking
        bill = bill_for_booking(booking)
    except Exception:
        bill = None
    if bill:
        result['payment_status'] = 'Paid' if Decimal(bill.balance_due or 0) <= 0 and Decimal(bill.total_amount or 0) > 0 else 'Payment pending'
    elif getattr(booking, 'amount_paid', None) is not None:
        paid = Decimal(booking.amount_paid or 0)
        total = Decimal(getattr(booking, 'total_bill', 0) or 0)
        result['payment_status'] = 'Paid' if total > 0 and paid >= total else 'Payment pending'
    customer = getattr(booking, 'customer', None) or getattr(booking, 'passenger', None) or getattr(booking, 'user', None)
    if customer and getattr(customer, 'contact_number', ''):
        result['contact_phone'] = customer.contact_number
    return result


def deliver_password_reset(token_id, raw_token):
    """Send reset link; raw token is held only in this post-commit callback."""
    from .models import PasswordResetToken
    row = PasswordResetToken.objects.select_related('user').filter(pk=token_id).first()
    if not row:
        return
    try:
        base = getattr(settings, 'APP_BASE_URL', '').rstrip('/')
        if not base:
            raise RuntimeError('EMAIL_CONFIGURATION_MISSING')
        link = f'{base}/accounts/reset-password/{row.user_id}/#{raw_token}'
        html = render_to_string('emails/password_reset.html', {
            'user_name': row.user.get_full_name() or row.user.get_username(),
            'reset_url': link, 'expires_minutes': 30,
        })
        text = (f"Reset your ATRUE password: {link}\nThis link expires in 30 minutes. "
                "If you did not request this, ignore this email.")
        row.provider_message_id = _brevo_send(
            to_email=row.user.email, to_name=row.user.get_full_name(),
            subject='Reset your ATRUE password', html=html, text=text,
            idempotency_key=f'password-reset:{row.pk}',
        )
        row.email_status = 'SENT'
    except Exception as exc:
        row.email_status = 'FAILED'
        logger.warning('Password reset email failed; token_id=%s code=%s', row.pk,
                       _email_error_code(exc))
    row.save(update_fields=['email_status', 'provider_message_id'])
