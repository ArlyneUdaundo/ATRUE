"""Single source of truth for the ATRUE hotel reservation voucher / e-ticket.

Both the on-screen ticket (``ticket.html``) and the reportlab PDF
(``ticket_pdf.py``) render from :func:`build_ticket_context` so the two outputs
can never disagree. Every value is derived live from the booking record -
nothing is hardcoded.
"""
from decimal import Decimal
from io import BytesIO

import qrcode
from django.template.defaultfilters import date as dj_date
from django.utils import timezone

TICKETABLE_STATUSES = ('CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT', 'MODIFIED', 'COMPLETED')


def _find_bill(booking):
    try:
        from atrue_core.services import bill_for_booking
        return bill_for_booking(booking)
    except Exception:
        return None


def _hotel_logo(hotel):
    """Return (url_for_html, absolute_path_for_pdf) for the hotel image."""
    photo = None
    if hotel is not None:
        try:
            photo = hotel.photos.filter(is_primary=True).first() or hotel.photos.first()
        except Exception:
            photo = None
    from django.conf import settings
    fallback_rel = 'img/atrue-logo-transparent.png'
    fallback_url = settings.STATIC_URL + fallback_rel
    fallback_path = str(settings.STATICFILES_DIRS[0] / fallback_rel)
    if photo is None or not photo.image:
        return fallback_url, fallback_path
    try:
        return photo.image.url, photo.image.path
    except Exception:
        return fallback_url, fallback_path


def _money(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def _voucher_number(reference, seq):
    """Deterministic per-room voucher number derived from the booking
    reference, e.g. ATR-AB12CD34-001."""
    suffix = str(reference).replace('-', '')[-6:] or 'ATR'
    return f"ATR-{suffix}-{int(seq):03d}"


def _fare_summary(booking, bill):
    """Split the confirmed bill line items into the hotel voucher fare summary.

    Hotel bills (BR-032) are: room charges (rate x nights, plus any
    extra-guest charge), add-on services and amenities. Nothing is invented:
    whatever the bill holds is grouped and totalled, so the voucher always
    agrees with the billing panel.
    """
    empty = {
        'base_fare': Decimal(0), 'services': [],
        'services_total': Decimal(0), 'amenities': [],
        'amenities_total': Decimal(0), 'other': [],
        'total': Decimal(0), 'paid': Decimal(0), 'balance': Decimal(0),
        'has_breakdown': False,
    }
    if bill is None:
        return empty

    base_fare = Decimal(0)
    services = []
    services_total = Decimal(0)
    amenities = []
    amenities_total = Decimal(0)
    other = []

    for item in bill.items or []:
        label = str(item.get('label', '') or item.get('description', ''))
        amount = _money(item.get('amount', item.get('total', 0)))
        desc = str(item.get('description', '') or '')
        dl = desc.lower()
        if 'hotel service' in dl:
            services.append({'label': label, 'description': desc, 'amount': amount})
            services_total += amount
        elif 'hotel amenity' in dl:
            amenities.append({'label': label, 'description': desc, 'amount': amount})
            amenities_total += amount
        elif 'night' in dl or label == 'Room Charge':
            base_fare += amount
        else:
            other.append({'label': label, 'description': desc, 'amount': amount})

    return {
        'base_fare': base_fare,
        'services': services,
        'services_total': services_total,
        'amenities': amenities,
        'amenities_total': amenities_total,
        'other': other,
        'total': _money(bill.total_amount),
        'paid': _money(bill.amount_paid),
        'balance': _money(bill.balance_due),
        'has_breakdown': bool(bill.items),
    }


def _computed_fare(booking):
    """Fallback fare summary computed straight from the booking model."""
    services = [
        {'label': line.service.name, 'description': '', 'amount': _money(line.price_at_booking)}
        for entry in booking.room_entries.all()
        for line in entry.booked_services.all()
    ]
    amenities = [
        {'label': line.amenity.name, 'description': '', 'amount': _money(line.price_at_booking)}
        for entry in booking.room_entries.all()
        for line in entry.booked_amenities.all()
    ]
    return {
        'base_fare': _money(booking.room_bill),
        'services': services,
        'services_total': sum((s['amount'] for s in services), Decimal(0)),
        'amenities': amenities,
        'amenities_total': sum((a['amount'] for a in amenities), Decimal(0)),
        'other': [],
        'total': _money(booking.total_bill),
        'paid': _money(booking.amount_paid or booking.total_paid),
        'balance': _money(booking.total_bill - (booking.amount_paid or booking.total_paid)),
        'has_breakdown': False,
    }


def _qr_png(data):
    """Return PNG bytes of a QR code carrying the voucher payload."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#0f172a', back_color='white')
    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def build_ticket_context(booking):
    """Assemble every datum the hotel e-ticket needs, shared by HTML and PDF."""
    entries = list(booking.room_entries.all())

    hotel = None
    if entries:
        hotel = entries[0].room.hotel
    logo_url, logo_path = _hotel_logo(hotel)

    bill = _find_bill(booking)

    rooms = []
    for i, entry in enumerate(entries):
        room = entry.room
        guest_name = ' '.join(filter(None, [
            entry.guest_first_name, entry.guest_middle_name, entry.guest_last_name,
        ])).strip() or booking.primary_guest_name or 'Guest'
        rooms.append({
            'index': i + 1,
            'room_number': room.room_number,
            'room_id': room.room_id or '—',
            'room_type': room.get_room_type_display(),
            'guest': guest_name,
            'check_in': dj_date(entry.check_in, 'F d, Y'),
            'check_out': dj_date(entry.check_out, 'F d, Y'),
            'nights': entry.nights,
            'adults': entry.number_of_adults,
            'children': entry.number_of_children,
            'guests': entry.total_guests,
            'services': [
                {'name': line.service.name, 'rate': line.price_at_booking}
                for line in entry.booked_services.all()
            ],
            'amenities': [
                {'name': line.amenity.name, 'rate': line.price_at_booking}
                for line in entry.booked_amenities.all()
            ],
            'room_bill': entry.room_bill,
            'services_total': entry.services_bill,
            'amenities_total': entry.amenities_bill,
            'total_bill': entry.total_bill,
            'voucher_number': _voucher_number(booking.booking_reference, i + 1),
        })

    check_in = booking.check_in
    check_out = booking.check_out

    qr_payload = ('ATRUE|SIM|{ref}|{hotel}|{rooms}|{guests}|{status}'.format(
        ref=booking.booking_reference,
        hotel=(hotel.name if hotel else '—'),
        rooms=','.join(r['room_number'] for r in rooms) or '—',
        guests=str(booking.number_of_guests),
        status=booking.status,
    ))

    payment_status = '—'
    if bill is not None:
        payment_status = bill.get_status_display()
    elif booking.payment_status:
        payment_status = {'UNPAID': 'Unpaid', 'PARTIALLY_PAID': 'Partially Paid',
                          'FULLY_PAID': 'Fully Paid'}.get(
                              booking.payment_status, booking.payment_status.title())

    return {
        'booking': booking,
        'bill': bill,
        'hotel': {
            'name': hotel.name if hotel else '—',
            'code': getattr(hotel, 'establishment_id', None) or '—',
            'contact': getattr(hotel, 'contact_number', '') or '',
            'email': getattr(hotel, 'email', '') or '',
            'location': hotel.location if hotel else '—',
            'logo_url': logo_url,
            'logo_path': logo_path,
        },
        'rooms': rooms,
        'room_count': len(rooms),
        'nights': booking.nights,
        'check_in': dj_date(check_in, 'F d, Y') if check_in else '—',
        'check_out': dj_date(check_out, 'F d, Y') if check_out else '—',
        'lead': {
            'name': booking.primary_guest_name or '—',
            'contact': booking.customer.contact_number or booking.payer_contact or '—',
            'email': booking.customer.email or '—',
        },
        'booking_info': {
            'pnr': booking.booking_reference,
            'booked_at': dj_date(booking.created_at, 'F d, Y · h:i A'),
            'status': booking.get_status_display(),
            'status_key': booking.status,
            'payment_status': payment_status,
            'guests': f"{booking.number_of_adults}A / {booking.number_of_children}C",
            'rooms': booking.number_of_rooms,
            'nights': booking.nights,
        },
        'fare': _fare_summary(booking, bill) if bill and bill.items else _computed_fare(booking),
        'qr': {
            'payload': qr_payload,
            'png': _qr_png(qr_payload),
        },
        'issued_on': timezone.localtime().strftime('%B %d, %Y · %H:%M'),
        'download_name': f"ATRUE-ReservationVoucher-{booking.booking_reference}.pdf",
    }
