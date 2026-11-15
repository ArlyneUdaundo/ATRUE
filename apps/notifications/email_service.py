"""Brevo transactional mail helpers and a small database-backed outbox."""
import base64
from email.utils import formataddr
import json
import logging
import os
import re
import smtplib
import urllib.request
import urllib.error
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)
BREVO_URL = 'https://api.brevo.com/v3/smtp/email'
BREVO_SENDERS_URL = 'https://api.brevo.com/v3/senders'
RESEND_URL = 'https://api.resend.com/emails'


def _gmail_smtp_password_reset_send(*, to_email, subject, html, text):
    """Send reset mail through the Gmail account used as the From address."""
    user = str(getattr(settings, 'GMAIL_SMTP_USER', '') or '').strip()
    password = ''.join(str(
        getattr(settings, 'GMAIL_SMTP_APP_PASSWORD', '') or ''
    ).split())
    sender_name = str(
        getattr(settings, 'GMAIL_SENDER_NAME', '') or ''
    ).replace('\r', ' ').replace('\n', ' ').strip()
    if not user or not password:
        raise RuntimeError('GMAIL_SMTP_CONFIGURATION_MISSING')
    try:
        validate_email(user)
    except ValidationError as exc:
        raise RuntimeError('GMAIL_SMTP_SENDER_INVALID') from exc
    if user.rsplit('@', 1)[-1].casefold() not in {'gmail.com', 'googlemail.com'}:
        raise RuntimeError('GMAIL_SMTP_SENDER_NOT_GMAIL')

    from django.core.mail import EmailMultiAlternatives, get_connection

    connection = get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host='smtp.gmail.com',
        port=587,
        username=user,
        password=password,
        use_tls=True,
        use_ssl=False,
        timeout=20,
    )
    from_email = formataddr((sender_name, user)) if sender_name else user
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=from_email,
        to=[to_email],
        connection=connection,
    )
    message.attach_alternative(html, 'text/html')
    try:
        sent = message.send(fail_silently=False)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError('GMAIL_SMTP_AUTH_FAILED') from exc
    except TimeoutError as exc:
        raise RuntimeError('GMAIL_SMTP_TIMEOUT') from exc
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as exc:
        raise RuntimeError('GMAIL_SMTP_CONNECTION_FAILED') from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError('GMAIL_SMTP_REJECTED') from exc
    if sent != 1:
        raise RuntimeError('GMAIL_SMTP_REJECTED')


def _brevo_config():
    """Return normalized Brevo settings without exposing them in diagnostics."""
    return {
        'api_key': str(getattr(settings, 'BREVO_API_KEY', '') or '').strip(),
        'sender_email': str(getattr(settings, 'BREVO_SENDER_EMAIL', '') or '').strip(),
        'sender_name': str(getattr(settings, 'BREVO_SENDER_NAME', '') or '').strip(),
    }


def check_brevo_connection():
    """Validate Brevo credentials and that the configured sender is active."""
    config = _brevo_config()
    if not all(config.values()):
        raise RuntimeError('EMAIL_CONFIGURATION_MISSING')
    req = urllib.request.Request(
        BREVO_SENDERS_URL, method='GET',
        headers={'api-key': config['api_key'], 'accept': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f'BREVO_HTTP_{response.status}')
            result = json.loads(response.read().decode() or '{}')
    except urllib.error.HTTPError as exc:
        provider_code = ''
        try:
            error_body = json.loads(exc.read().decode() or '{}')
            provider_code = re.sub(
                r'[^A-Za-z0-9_-]', '', str(error_body.get('code', ''))
            )[:40].upper()
        except (ValueError, AttributeError, UnicodeDecodeError):
            pass
        suffix = f'_{provider_code}' if provider_code else ''
        raise RuntimeError(f'BREVO_HTTP_{exc.code}{suffix}') from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise RuntimeError('BREVO_CONNECTION_FAILED') from exc
    sender = next((
        item for item in result.get('senders', [])
        if str(item.get('email', '')).strip().casefold() == config['sender_email'].casefold()
    ), None)
    if not sender or sender.get('active') is not True:
        raise RuntimeError('BREVO_SENDER_NOT_VERIFIED')
    return True


def _email_error_code(exc):
    """Return a safe, compact diagnostic code without storing provider messages."""
    message = str(exc)
    if message in {'EMAIL_CONFIGURATION_MISSING', 'RECIPIENT_UNAVAILABLE',
                   'ETICKET_GENERATION_FAILED', 'BOOKING_NOT_CONFIRMED',
                   'BREVO_TIMEOUT', 'BREVO_CONNECTION_FAILED',
                   'BREVO_INVALID_RESPONSE', 'BREVO_SENDER_NOT_VERIFIED'}:
        return message
    if re.fullmatch(r'BREVO_HTTP_\d{3}(?:_[A-Z0-9_-]{1,40})?', message):
        return message
    return type(exc).__name__.upper()[:80]


def _brevo_send(*, to_email, to_name, subject, html, text, idempotency_key,
                attachments=None):
    config = _brevo_config()
    if not all(config.values()):
        raise RuntimeError('EMAIL_CONFIGURATION_MISSING')
    body = {
        'sender': {'email': config['sender_email'], 'name': config['sender_name']},
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
            'api-key': config['api_key'], 'accept': 'application/json',
            'content-type': 'application/json',
        },
    )
    try:
        # Booking confirmation carries a base64 PDF attachment, unlike the
        # small password-reset message. Give Brevo enough time to accept it.
        with urllib.request.urlopen(req, timeout=30) as response:
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
    except TimeoutError as exc:
        raise RuntimeError('BREVO_TIMEOUT') from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, 'reason', None), TimeoutError):
            raise RuntimeError('BREVO_TIMEOUT') from exc
        raise RuntimeError('BREVO_CONNECTION_FAILED') from exc
    message_id = result.get('messageId')
    if not isinstance(message_id, str) or not message_id.strip():
        raise RuntimeError('BREVO_INVALID_RESPONSE')
    return message_id.strip()


def _resend_config():
    """Return password-reset-only Resend settings without logging credentials."""
    return {
        'api_key': str(getattr(settings, 'RESEND_API_KEY', '') or '').strip(),
        'sender_email': str(getattr(settings, 'RESEND_SENDER_EMAIL', '') or '').strip(),
        'sender_name': str(getattr(settings, 'RESEND_SENDER_NAME', '') or '').strip(),
    }


def _resend_password_reset_send(*, to_email, to_name, subject, html, text,
                                idempotency_key):
    """Send one password-reset message through Resend's official REST API."""
    config = _resend_config()
    if not config['api_key'] or not config['sender_email']:
        raise RuntimeError('RESEND_CONFIGURATION_MISSING')
    try:
        validate_email(config['sender_email'])
    except ValidationError as exc:
        raise RuntimeError('RESEND_SENDER_INVALID') from exc

    sender_name = config['sender_name'].replace('\r', ' ').replace('\n', ' ').strip()
    sender = formataddr((sender_name, config['sender_email'])) if sender_name else config['sender_email']
    body = {
        'from': sender,
        'to': [to_email],
        'subject': subject,
        'html': html,
        'text': text,
    }
    req = urllib.request.Request(
        RESEND_URL, data=json.dumps(body).encode(), method='POST',
        headers={
            'authorization': f"Bearer {config['api_key']}",
            'accept': 'application/json',
            'content-type': 'application/json',
            'Idempotency-Key': str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode() or '{}')
    except urllib.error.HTTPError as exc:
        provider_code = ''
        try:
            error_body = json.loads(exc.read().decode() or '{}')
            raw_code = error_body.get('name') or error_body.get('code') or ''
            provider_code = re.sub(r'[^A-Za-z0-9_-]', '', str(raw_code))[:40].upper()
        except (ValueError, AttributeError, UnicodeDecodeError):
            pass
        suffix = f'_{provider_code}' if provider_code else ''
        raise RuntimeError(f'RESEND_HTTP_{exc.code}{suffix}') from exc
    except TimeoutError as exc:
        raise RuntimeError('RESEND_TIMEOUT') from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, 'reason', None), TimeoutError):
            raise RuntimeError('RESEND_TIMEOUT') from exc
        raise RuntimeError('RESEND_CONNECTION_FAILED') from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError('RESEND_INVALID_RESPONSE') from exc

    message_id = result.get('id') if isinstance(result, dict) else None
    if not isinstance(message_id, str) or not message_id.strip():
        raise RuntimeError('RESEND_INVALID_RESPONSE')
    return message_id.strip()


def _password_reset_send(provider, *, to_email, to_name, subject, html, text,
                         idempotency_key):
    """Dispatch reset mail only; booking email delivery always remains Brevo."""
    if provider == 'brevo':
        return _brevo_send(
            to_email=to_email, to_name=to_name, subject=subject, html=html,
            text=text, idempotency_key=idempotency_key,
        )
    if provider == 'resend':
        return _resend_password_reset_send(
            to_email=to_email, to_name=to_name, subject=subject, html=html,
            text=text, idempotency_key=idempotency_key,
        )
    if provider == 'gmail_smtp':
        return _gmail_smtp_password_reset_send(
            to_email=to_email, subject=subject, html=html,
            text=text,
        )
    raise RuntimeError('PASSWORD_RESET_PROVIDER_UNSUPPORTED')


def _password_reset_error_code(exc):
    """Return a safe provider code; discard raw error bodies and PII."""
    message = str(exc)
    allowed = {
        'EMAIL_CONFIGURATION_MISSING', 'PASSWORD_RESET_PROVIDER_UNSUPPORTED',
        'RESEND_CONFIGURATION_MISSING', 'RESEND_SENDER_INVALID',
        'RESEND_TIMEOUT', 'RESEND_CONNECTION_FAILED', 'RESEND_INVALID_RESPONSE',
        'BREVO_TIMEOUT', 'BREVO_CONNECTION_FAILED', 'BREVO_INVALID_RESPONSE',
        'BREVO_SENDER_NOT_VERIFIED',
        'GMAIL_SMTP_CONFIGURATION_MISSING', 'GMAIL_SMTP_SENDER_INVALID',
        'GMAIL_SMTP_SENDER_NOT_GMAIL', 'GMAIL_SMTP_AUTH_FAILED',
        'GMAIL_SMTP_TIMEOUT', 'GMAIL_SMTP_CONNECTION_FAILED',
        'GMAIL_SMTP_REJECTED',
    }
    if message in allowed:
        return message
    if re.fullmatch(r'(?:BREVO|RESEND)_HTTP_\d{3}(?:_[A-Z0-9_-]{1,40})?', message):
        return message
    return type(exc).__name__.upper()[:80]


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
        subject = f"Booking confirmed: {details['booking_reference']}"
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
    """Send reset link using the configured reset provider; token stays local."""
    from .models import PasswordResetToken
    row = PasswordResetToken.objects.select_related('user').filter(pk=token_id).first()
    if not row:
        return
    try:
        provider = str(getattr(settings, 'PASSWORD_RESET_EMAIL_PROVIDER', 'brevo') or 'brevo').strip().lower()
        base = (getattr(settings, 'APP_BASE_URL', '') or
                getattr(settings, 'RENDER_EXTERNAL_URL', '')).rstrip('/')
        if not base:
            raise RuntimeError('EMAIL_CONFIGURATION_MISSING')
        link = f'{base}/accounts/reset-password/{row.user_id}/#{raw_token}'
        html = render_to_string('emails/password_reset.html', {
            'user_name': row.user.get_full_name() or row.user.get_username(),
            'reset_url': link,
            'logo_url': f'{base}/static/img/atrue-logo-transparent.png',
            'expires_minutes': 30,
        })
        text = (f"Reset your ATRUE password: {link}\nThis link expires in 30 minutes. "
                "If you did not request this, ignore this email.")
        message_id = _password_reset_send(
            provider,
            to_email=row.user.email, to_name=row.user.get_full_name(),
            subject='Reset your ATRUE password', html=html, text=text,
            idempotency_key=f'password-reset:{row.pk}',
        )
        row.provider_message_id = message_id or ''
        row.email_status = 'SENT'
        if message_id:
            logger.info(
                'Password reset email accepted by %s API; token_id=%s provider_message_id=%s',
                provider, row.pk, message_id,
            )
        else:
            logger.info(
                'Password reset email accepted by %s SMTP relay; token_id=%s',
                provider, row.pk,
            )
    except Exception as exc:
        row.email_status = 'FAILED'
        logger.warning('Password reset email failed; token_id=%s code=%s', row.pk,
                       _password_reset_error_code(exc))
    row.save(update_fields=['email_status', 'provider_message_id'])
