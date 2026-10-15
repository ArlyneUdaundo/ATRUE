"""Shared e-ticket / voucher engine for every ATRUE establishment module.

Each module adapter produces one normalized context dict (see
``build_eticket_context``) that the generic HTML ticket (``templates/
etickets/eticket.html``) and the generic ReportLab PDF (``eticket_pdf.py``)
render from, so screen and PDF can never disagree.

Booking models all inherit :class:`atrue_core.models.BookingFieldsMixin`, so
the shared fields (``booking_reference``, ``status``, ``total_bill``,
``amount_paid``, ``balance_due``, ``created_at``…) are identical everywhere.
"""
from decimal import Decimal
from io import BytesIO

import qrcode
from django.template.defaultfilters import date as dj_date
from django.utils import timezone

TICKETABLE_STATUSES = {
    'resorts': ('CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT', 'MODIFIED', 'COMPLETED'),
    'staycations': ('CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT', 'MODIFIED', 'COMPLETED'),
    'restaurants': ('CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT', 'MODIFIED', 'COMPLETED'),
    'landmarks': ('CONFIRMED', 'USED', 'MODIFIED', 'COMPLETED'),
    'activities': ('CONFIRMED', 'CHECKED_IN', 'MODIFIED', 'COMPLETED'),
    'tour_package': ('CONFIRMED', 'MODIFIED', 'COMPLETED'),
    'transportation': ('CONFIRMED', 'CHECKED_IN', 'MODIFIED', 'COMPLETED'),
}

DOC_TYPES = {
    'resorts': ('RESORT RESERVATION VOUCHER', 'ResortVoucher'),
    'staycations': ('STAYCATION RESERVATION VOUCHER', 'StaycationVoucher'),
    'restaurants': ('TABLE RESERVATION VOUCHER', 'TableVoucher'),
    'landmarks': ('ENTRANCE TICKET', 'EntranceTicket'),
    'activities': ('ACTIVITY VOUCHER', 'ActivityVoucher'),
    'tour_package': ('TOUR ITINERARY VOUCHER', 'TourVoucher'),
    'transportation': ('TRANSPORT VOUCHER', 'TransportVoucher'),
}


def _money(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def _fmtd(value):
    return dj_date(value, 'F d, Y') if value else '—'


def _fmtdt(value):
    return dj_date(value, 'F d, Y · h:i A') if value else '—'


def _voucher_number(booking):
    suffix = str(booking.booking_reference).replace('-', '')[-6:] or 'ATR'
    return f"ATR-{suffix}-001"


def _logo(entity):
    """Return (url_for_html, absolute_path_for_pdf) for the establishment."""
    photo = None
    if entity is not None:
        try:
            photos = getattr(entity, 'photos', None)
            if photos is not None:
                photo = photos.filter(is_primary=True).first() or photos.first()
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


def _qr_png(data):
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


def _payment_status(booking, bill):
    if bill is not None:
        return bill.get_status_display()
    total = _money(booking.total_bill)
    paid = _money(booking.amount_paid)
    if total and paid >= total:
        return 'Fully Paid'
    if paid > 0:
        return 'Partially Paid'
    return 'Unpaid'


def _lead(booking, name, contact, email, note=''):
    return {
        'name': name or '—',
        'contact': contact or '—',
        'email': email or '—',
        'note': note,
    }


def _base_ctx(module, booking, bill, entity, band, grid, lead, doc_rows, gen_rows):
    doc_type, doc_tag = DOC_TYPES[module]
    logo_url, logo_path = _logo(entity)
    return {
        'base_tpl': module,
        'back_name': f"{module}:booking_detail",
        'doc_type': doc_type,
        'establishment': {
            'name': getattr(entity, 'name', module.title()) or module.title(),
            'code': getattr(entity, 'establishment_id', None) or getattr(entity, 'restaurant_id', None) or '—',
            'contact': getattr(entity, 'contact_number', '') or getattr(entity, 'contact_email', '') or '',
            'email': getattr(entity, 'email', '') or getattr(entity, 'contact_email', '') or '',
            'location': getattr(entity, 'location', '') or '',
            'logo_url': logo_url,
            'logo_path': logo_path,
        },
        'band': band,
        'info_grid': grid,
        'lead': lead,
        'fare_doc_rows': doc_rows,
        'fare_gen_rows': gen_rows,
    }


# -- Per-module adapters ----------------------------------------------------

def _ctx_resorts(booking, bill):
    unit = booking.unit
    resort = unit.resort
    nights = booking.nights
    base = _money(unit.rate) * _money(nights) * _money(booking.number_of_units)
    rows = [(f"Unit charge ({booking.number_of_units} × {unit.get_unit_type_display()} · {nights} night(s))", base)]
    rows += [(f"Service · {s.name}", s.rate) for s in booking.services.all()]
    grid = [
        ('Resort', resort.name),
        ('Unit', f"{unit.unit_number} ({unit.get_unit_type_display()})"),
        ('Unit ID', unit.unit_id or '—'),
        ('Capacity', f"{unit.capacity_adults}A / {unit.capacity_children}C"),
        ('Check-in', _fmtd(booking.check_in)), ('Check-out', _fmtd(booking.check_out)),
        ('Nights', str(nights)), ('Guests', f"{booking.number_of_adults}A / {booking.number_of_children}C"),
        ('Units', str(booking.number_of_units)), ('Voucher No.', _voucher_number(booking)),
        ('Special requests', booking.special_requests or '—'),
    ]
    lead = _lead(booking, booking.primary_guest_name or booking.customer.get_full_name(),
                 booking.customer.contact_number or booking.payer_contact,
                 booking.customer.email)
    band = {
        'title': f"{booking.number_of_units} × {unit.get_unit_type_display()}",
        'subtitle': f"{nights} night(s) · {booking.number_of_adults}A / {booking.number_of_children}C",
        'note': 'Check-in 2:00 PM · Check-out 12:00 NN',
        'legs': [
            {'label': 'Check-in', 'code': _fmtd(booking.check_in), 'sub': 'from 2:00 PM'},
            {'label': 'Check-out', 'code': _fmtd(booking.check_out), 'sub': 'until 12:00 NN'},
        ],
    }
    return _base_ctx('resorts', booking, bill, resort, band, grid, lead, rows, [])


def _ctx_staycations(booking, bill):
    stay = booking.staycation
    nights = booking.nights
    base = _money(stay.rate) * _money(nights)
    rows = [(f"{stay.name} ({nights} night(s))", base)]
    rows += [(f"Service · {s.name}", s.rate) for s in booking.services.all()]
    grid = [
        ('Staycation', stay.name),
        ('Establishment ID', getattr(stay, 'establishment_id', None) or '—'),
        ('Address', getattr(stay, 'location', '') or '—'),
        ('Capacity', f"{stay.capacity_adults} adults / {stay.capacity_children} children"),
        ('Check-in', _fmtd(booking.check_in)), ('Check-out', _fmtd(booking.check_out)),
        ('Nights', str(nights)), ('Guests', f"{booking.number_of_adults}A / {booking.number_of_children}C"),
        ('Voucher No.', _voucher_number(booking)),
        ('Special requests', booking.special_requests or '—'),
    ]
    lead = _lead(booking, booking.primary_guest_name or booking.customer.get_full_name(),
                 booking.customer.contact_number or booking.payer_contact,
                 booking.customer.email)
    band = {
        'title': stay.name,
        'subtitle': f"{nights} night(s) · {booking.number_of_adults}A / {booking.number_of_children}C",
        'note': 'Check-in 2:00 PM · Check-out 12:00 NN',
        'legs': [
            {'label': 'Check-in', 'code': _fmtd(booking.check_in), 'sub': 'from 2:00 PM'},
            {'label': 'Check-out', 'code': _fmtd(booking.check_out), 'sub': 'until 12:00 NN'},
        ],
    }
    return _base_ctx('staycations', booking, bill, stay, band, grid, lead, rows, [])


def _ctx_restaurants(booking, bill):
    table = booking.table
    rest = table.restaurant
    rows = [('Table reservation', _money(booking.deposit or 0))]
    grid = [
        ('Restaurant', rest.name),
        ('Table', f"{table.table_number} ({table.get_seating_area_display()})"),
        ('Reservation', _fmtdt(booking.reservation_datetime)),
        ('Guests', f"{booking.number_of_guests} guest(s)"),
        ('Occasion', booking.get_occasion_display()),
        ('Seating preference', booking.get_seating_preference_display()),
        ('Deposit', f"₱ {booking.deposit or 0}"),
        ('Voucher No.', _voucher_number(booking)),
        ('Special requests', booking.special_requests or '—'),
    ]
    lead = _lead(booking, booking.primary_guest_name or booking.customer.get_full_name(),
                 booking.customer.contact_number or booking.payer_contact,
                 booking.customer.email)
    band = {
        'title': f"Table {table.table_number}",
        'subtitle': f"{booking.number_of_guests} guest(s) · {rest.name}",
        'note': f"{booking.get_occasion_display()} · {booking.get_seating_preference_display()}",
        'legs': [
            {'label': 'Reservation', 'code': _fmtdt(booking.reservation_datetime),
             'sub': f"Table for {booking.number_of_guests}"},
        ],
    }
    return _base_ctx('restaurants', booking, bill, rest, band, grid, lead, rows, [])


def _ctx_landmarks(booking, bill):
    dest = booking.destination
    entry = _money(dest.entry_fee) if dest else Decimal(0)
    tour = Decimal(0)
    if booking.guided_tour == 'STANDARD' and dest:
        tour = _money(dest.guided_tour_rate)
    elif booking.guided_tour == 'PRIVATE' and dest:
        tour = _money(dest.private_tour_rate)
    equip = _money(booking.equipment_rate) * _money(booking.equipment_quantity)
    entrance = entry * _money(booking.number_of_visitors)
    rows = [
        (f"Entrance ({booking.number_of_visitors} visitor(s))", entrance),
        (f"Guided tour · {booking.get_guided_tour_display()}", tour),
    ]
    if booking.equipment_quantity:
        rows.append((f"Equipment rental × {booking.equipment_quantity}", equip))
    grid = [
        ('Destination', dest.name if dest else '—'),
        ('Category', booking.get_destination_type_display()),
        ('Visit', _fmtdt(booking.visit_datetime)),
        ('Visitors', f"{booking.number_of_visitors}"),
        ('Guided tour', booking.get_guided_tour_display()),
        ('Visitor age', booking.visitor_age or '—'),
        ('Voucher No.', _voucher_number(booking)),
        ('Special requests', booking.special_requests or '—'),
    ]
    lead = _lead(booking, booking.primary_guest_name or booking.customer.get_full_name(),
                 booking.contact_number or booking.customer.contact_number,
                 booking.visitor_email)
    band = {
        'title': dest.name if dest else 'Attraction',
        'subtitle': f"{booking.number_of_visitors} visitor(s) · {booking.get_destination_type_display()}",
        'note': f'{booking.get_guided_tour_display()} guided tour',
        'legs': [
            {'label': 'Visit', 'code': _fmtdt(booking.visit_datetime),
             'sub': f"{booking.number_of_visitors} visitor(s)"},
        ],
    }
    return _base_ctx('landmarks', booking, bill, dest, band, grid, lead, rows, [])


def _ctx_activities(booking, bill):
    act = booking.activity
    prov = act.provider
    base = _money(act.fee) * _money(booking.participant_count) + _money(act.additional_fee or 0)
    rows = [(f"{act.name} ({booking.participant_count} participant(s))", base)]
    grid = [
        ('Activity', act.name),
        ('Provider', prov.name if prov else '—'),
        ('Location', getattr(act, 'full_location', None) or act.location or '—'),
        ('Meeting point', act.meeting_point or '—'),
        ('Schedule', _fmtd(booking.schedule_date) if booking.schedule_date else '—'),
        ('Time', f"{_hm(booking.start_time)}–{_hm(booking.end_time)}" if booking.start_time else '—'),
        ('Duration', act.duration or '—'),
        ('Participants', str(booking.participant_count)),
        ('Rate type', act.get_rate_type_display()),
        ('Voucher No.', _voucher_number(booking)),
        ('Special requests', booking.special_requests or '—'),
    ]
    lead = _lead(booking, booking.primary_participant_name or booking.customer.get_full_name(),
                 booking.contact_number or booking.customer.contact_number,
                 booking.email or booking.customer.email)
    band = {
        'title': act.name,
        'subtitle': (prov.name if prov else '—') + f" · {booking.participant_count} participant(s)",
        'note': f"Duration {act.duration or '—'}",
        'legs': [
            {'label': 'Schedule', 'code': _fmtd(booking.schedule_date),
             'sub': f"{_hm(booking.start_time)}–{_hm(booking.end_time)}" if booking.start_time else act.duration or '—'},
        ],
    }
    return _base_ctx('activities', booking, bill, act, band, grid, lead, rows, [])


def _ctx_tour_package(booking, bill):
    pkg = booking.package
    rows = [(f"Package · {pkg.name}", _money(pkg.price))]
    grid = [
        ('Package', pkg.name),
        ('Destination', getattr(pkg, 'destination_name', '') or '—'),
        ('Duration', f"{pkg.duration_days} day(s)"),
        ('Travel date', _fmtd(booking.travel_date)),
        ('Time', f"{_hm(booking.start_time)}–{_hm(booking.end_time)}" if booking.start_time else '—'),
        ('Travelers', f"{booking.number_of_adults}A / {booking.number_of_children}C ({booking.number_of_travelers} total)"),
        ('Payment method', booking.get_payment_method_display()),
        ('Inclusions', (pkg.inclusions or '—')[:200]),
        ('Voucher No.', _voucher_number(booking)),
        ('Special requests', booking.special_requests or '—'),
    ]
    lead = _lead(booking, booking.primary_traveler_name or booking.customer.get_full_name(),
                 booking.contact_number or booking.customer.contact_number,
                 booking.customer.email)
    band = {
        'title': pkg.name,
        'subtitle': getattr(pkg, 'destination_name', '') or '—',
        'note': f"{pkg.duration_days} day(s) · {booking.number_of_travelers} traveler(s)",
        'legs': [
            {'label': 'Travel date', 'code': _fmtd(booking.travel_date),
             'sub': f"{_hm(booking.start_time)}–{_hm(booking.end_time)}" if booking.start_time else f"{pkg.duration_days} day(s)"},
        ],
    }
    return _base_ctx('tour_package', booking, bill, pkg, band, grid, lead, rows, [])


def _ctx_transportation(booking, bill):
    veh = booking.vehicle
    agency = veh.agency
    base = _money(veh.rate_per_km) * _money(booking.distance_km)
    rows = [(f"Transport · {veh.label} ({booking.distance_km} km)", base)]
    driver = booking.driver.full_name if getattr(booking, 'driver_id', None) and booking.driver else 'To be assigned'
    grid = [
        ('Agency', agency.name),
        ('Vehicle', f"{veh.label} · {veh.plate_number}"),
        ('Driver', driver),
        ('Pick-up', booking.pickup_location),
        ('Drop-off', booking.drop_off_location),
        ('Distance', f"{booking.distance_km} km"),
        ('Schedule', _fmtdt(booking.schedule)),
        ('Duration', f"{booking.duration_hours} hr(s)"),
        ('Passengers', str(booking.passengers)),
        ('Voucher No.', _voucher_number(booking)),
        ('Special requests', booking.special_requests or '—'),
    ]
    lead = _lead(booking, booking.primary_guest_name or booking.customer.get_full_name(),
                 booking.customer.contact_number or booking.payer_contact,
                 booking.customer.email)
    band = {
        'title': f"{veh.label} · {veh.plate_number}",
        'subtitle': agency.name,
        'note': f"{booking.passengers} passenger(s) · {booking.duration_hours} hr(s)",
        'legs': [
            {'label': 'Schedule', 'code': _fmtdt(booking.schedule),
             'sub': f"{booking.pickup_location} → {booking.drop_off_location}"},
        ],
    }
    return _base_ctx('transportation', booking, bill, agency, band, grid, lead, rows, [])


ADAPTERS = {
    'resorts': _ctx_resorts,
    'staycations': _ctx_staycations,
    'restaurants': _ctx_restaurants,
    'landmarks': _ctx_landmarks,
    'activities': _ctx_activities,
    'tour_package': _ctx_tour_package,
    'transportation': _ctx_transportation,
}


def _hm(value):
    """Return a time value as 'H:MM AM' (blank-tolerant)."""
    if not value:
        return ''
    return dj_date(value, 'h:i A')


def build_eticket_context(module, booking, bill=None):
    """Assemble the normalized context every module's e-ticket renders from."""
    adapter = ADAPTERS[module]
    base = adapter(booking, bill)

    qr_payload = 'ATRUE|SIM|{mod}|{ref}|{estab}|{status}'.format(
        mod=module,
        ref=booking.booking_reference,
        estab=base['establishment']['name'],
        status=booking.status,
    )

    statuses = TICKETABLE_STATUSES[module]
    return {
        'module': module,
        'doc_type': base['doc_type'],
        'establishment': base['establishment'],
        'booking': booking,
        'bill': bill,
        'band': base['band'],
        'info_grid': base['info_grid'],
        'lead': base['lead'],
        'booking_info': {
            'pnr': booking.booking_reference,
            'booked_at': _fmtdt(booking.created_at),
            'status': booking.get_status_display(),
            'status_key': booking.status,
            'payment_status': _payment_status(booking, bill),
            'ticket_allowed': booking.status in statuses,
        },
        'fare': _fare_summary(booking, bill, base['fare_doc_rows'], base['fare_gen_rows']),
        'voucher_number': _voucher_number(booking),
        'qr': {
            'payload': qr_payload,
            'png': _qr_png(qr_payload),
        },
        'issued_on': timezone.localtime().strftime('%B %d, %Y · %H:%M'),
        'download_name': f"ATRUE-{DOC_TYPES[module][1]}-{booking.booking_reference}.pdf",
    }


def _fare_summary(booking, bill, doc_rows, gen_rows):
    """Prefer the real bill line items; fall back to adapter-computed rows."""
    if bill is not None and bill.items:
        rows = [
            {'label': str(i.get('label') or i.get('description') or 'Item'),
             'amount': i.get('amount', i.get('total', 0))}
            for i in bill.items
        ]
        total, paid, balance = bill.total_amount, bill.amount_paid, bill.balance_due
    else:
        rows = [{'label': label, 'amount': amount} for label, amount in (doc_rows or gen_rows or [])]
        total, paid, balance = booking.total_bill, booking.amount_paid, booking.balance_due
    return {
        'rows': rows,
        'total': total or 0,
        'paid': paid or 0,
        'balance': balance or 0,
        'has_breakdown': bool(rows),
    }


# -- View helpers -------------------------------------------------------------

def _load_booking(module, booking_id):
    from django.apps import apps

    model = apps.get_model(module, {
        'resorts': 'Reservation', 'staycations': 'Reservation', 'restaurants': 'Reservation',
        'landmarks': 'Ticket', 'activities': 'Booking', 'tour_package': 'Booking',
        'transportation': 'Booking',
    }[module])
    return model.objects.select_related('customer').get(pk=booking_id)


def _user_may_view(request, module, booking):
    from accounts.roles import can_manage_booking
    cid = booking.customer_id if hasattr(booking, 'customer_id') else getattr(booking, 'passenger_id', None)
    # Only the guest who owns the booking may print or download its ticket.
    return cid == request.user.id and not (
        request.user.is_staff or can_manage_booking(request.user, module)
    )


def eticket_detail(request, module, booking_id):
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect, render
    from django.urls import reverse

    from atrue_core.services import bill_for_booking

    booking = _load_booking(module, booking_id)
    if not _user_may_view(request, module, booking):
        messages.warning(request, "You cannot view this e-ticket.")
        return redirect(f'{module}:booking_detail', booking_id)

    if booking.status not in TICKETABLE_STATUSES[module]:
        messages.warning(request, "The e-ticket is available once the booking is confirmed.")
        return redirect(f'{module}:booking_detail', booking_id)

    bill = bill_for_booking(booking)
    ctx = build_eticket_context(module, booking, bill)

    import base64
    ctx['qr']['data_uri'] = 'data:image/png;base64,' + base64.b64encode(ctx['qr']['png']).decode('ascii')

    return render(request, 'etickets/eticket.html', {
        'ticket': ctx,
        'printable': True,
        'back_url': reverse(f'{module}:booking_detail', args=[booking_id]),
        'pdf_url': reverse(f'{module}:ticket_pdf', args=[booking_id]),
        'module_label': DOC_TYPES[module][0].title(),
    })


def eticket_pdf(request, module, booking_id):
    from django.contrib import messages
    from django.http import HttpResponse
    from django.shortcuts import redirect

    from atrue_core.services import bill_for_booking

    booking = _load_booking(module, booking_id)
    if not _user_may_view(request, module, booking):
        messages.warning(request, "You cannot download this e-ticket.")
        return redirect(f'{module}:booking_detail', booking_id)

    if booking.status not in TICKETABLE_STATUSES[module]:
        messages.warning(request, "The e-ticket is available once the booking is confirmed.")
        return redirect(f'{module}:booking_detail', booking_id)

    bill = bill_for_booking(booking)
    ctx = build_eticket_context(module, booking, bill)

    from atrue_core.eticket_pdf import build_pdf_response
    return build_pdf_response(ctx)
