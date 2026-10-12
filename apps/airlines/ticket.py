"""Single source of truth for the ATRUE airline e-ticket.

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

from transactions.models import Bill

TICKETABLE_STATUSES = ('CONFIRMED', 'CHECKED_IN', 'COMPLETED', 'MODIFIED')


def _airline_logo(airline):
    """Return (url_for_html, absolute_path_for_pdf) for the airline logo."""
    if airline is None:
        return '', ''
    photo = airline.logo_photo
    if photo is None or not photo.image:
        return '', ''
    try:
        return photo.image.url, photo.image.path
    except (ValueError, NotImplementedError):
        return '', ''


def _money(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def _duration(flight):
    if not getattr(flight, 'arrival_time', None) or not getattr(flight, 'departure_time', None):
        return '—'
    try:
        delta = flight.arrival_time - flight.departure_time
        minutes = max(0, int(delta.total_seconds()) // 60)
        hours, mins = divmod(minutes, 60)
        if hours and mins:
            return f"{hours}h {mins}m"
        if hours:
            return f"{hours}h"
        return f"{mins}m"
    except Exception:
        return '—'


def _fare_summary(booking, bill):
    """Split the confirmed bill line items into the e-ticket fare summary.

    Airline bills (BR-046) are: base fare (the flight line), extra baggage and
    add-on services. The system does not model separate tax/airport-fee lines,
    so nothing is invented: whatever the bill holds is grouped and totalled.
    """
    empty = {
        'base_fare': Decimal(0), 'services': [],
        'services_total': Decimal(0), 'baggage': Decimal(0), 'baggage_kg': Decimal(0),
        'other': [], 'total': Decimal(0),
        'paid': Decimal(0), 'balance': Decimal(0),
        'has_breakdown': False,
    }
    if bill is None:
        return empty

    flight_numbers = {
        getattr(flight, 'flight_number', '')
        for flight in (booking.flight, getattr(booking, 'return_flight', None))
        if flight is not None
    }
    base_fare = Decimal(0)
    services = []
    services_total = Decimal(0)
    baggage = Decimal(0)
    other = []

    for item in bill.items or []:
        label = str(item.get('label', '') or item.get('description', ''))
        amount = _money(item.get('amount', item.get('total', 0)))
        bl = label.lower()
        if label in flight_numbers:
            base_fare += amount
        elif 'baggage' in bl or 'luggage' in bl:
            baggage += amount
        elif amount > 0:
            services.append({'label': label, 'amount': amount})
            services_total += amount
        else:
            other.append({'label': label, 'amount': amount})

    result = {
        'base_fare': base_fare,
        'services': services,
        'services_total': services_total,
        'baggage': baggage,
        'baggage_kg': getattr(booking, 'extra_baggage_kg', 0) or Decimal(0),
        'other': other,
        'total': _money(bill.total_amount),
        'paid': _money(bill.amount_paid),
        'balance': _money(bill.balance_due),
        'has_breakdown': bool(bill.items),
    }
    return result


def _qr_png(data):
    """Return PNG bytes of a QR code carrying the ticket payload."""
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


def _itinerary_passengers(booking, seats, itinerary):
    """One ticket row per traveler, carrying that traveler's seat on every leg.

    A connecting booking stores one seat row per passenger per segment, so the
    rows have to be collapsed by passenger or the ticket would print "2
    passengers" four times.  The first segment is the reference: whoever is
    seated on it is on the booking, and their name is the one printed.
    """
    first_order = itinerary.first_leg.segment_order if itinerary.first_leg else 0
    by_name = {}
    for entry in seats:
        by_name.setdefault(entry.passenger_name, []).append(entry)

    rows = []
    for index, (name, entries) in enumerate(by_name.items()):
        seats_by_segment = {e.segment_order: (e.seat_number or '—') for e in entries}
        first = entries[0]
        rows.append({
            'name': name or booking.primary_guest_name or 'Passenger',
            'class': first.get_fare_class_display() if first.fare_class else 'Economy',
            'class_key': first.fare_class or 'ECONOMY',
            # The first leg's seat is the headline one, so a template that only
            # knows about 'seat' still shows a real seat.
            'seat': seats_by_segment.get(first_order, '—'),
            'seats': seats_by_segment,
            'seat_summary': ' / '.join(
                seats_by_segment.get(order, '—')
                for order in sorted(seats_by_segment)),
            'doc_type': (first.get_travel_document_type_display()
                         if first.travel_document_type else '—'),
            'doc_number': first.travel_document_number or '—',
            # The system has no airline-issued ticket-number field. Do not
            # manufacture one from the ATRUE booking reference.
            'ticket_number': '',
            'passenger_type': '',
            'index': index + 1,
        })
    return rows


def _flight_summary(flight):
    """Expose only flight facts stored on the actual schedule record."""
    if flight is None:
        return None

    origin_airport = flight.origin_airport
    destination_airport = flight.destination_airport
    origin_code = ((origin_airport.iata_code if origin_airport else '')
                   or flight.origin_code or '—')
    destination_code = ((destination_airport.iata_code if destination_airport else '')
                        or flight.destination_code or '—')

    def time_value(value):
        return value.strftime('%I:%M %p').lstrip('0') if value else ''

    return {
        'number': flight.flight_number or '—',
        'origin': flight.origin,
        'origin_city': (origin_airport.city if origin_airport and origin_airport.city
                        else flight.origin_municipality or flight.origin),
        'origin_airport': origin_airport.airport_name if origin_airport else '',
        'origin_code': origin_code,
        'destination': flight.destination,
        'destination_city': (destination_airport.city
                             if destination_airport and destination_airport.city
                             else flight.destination_municipality or flight.destination),
        'destination_airport': (destination_airport.airport_name
                                if destination_airport else ''),
        'destination_code': destination_code,
        'terminal': (flight.terminal or '').strip(),
        'gate': (flight.gate or '').strip(),
        'arrival_terminal': (flight.arrival_terminal or '').strip(),
        'arrival_gate': (flight.arrival_gate or '').strip(),
        'aircraft': (f"{flight.aircraft.model_name} ({flight.aircraft.tail_number})"
                     if flight.aircraft else ''),
        'departure_date': dj_date(flight.departure_time, 'F d, Y'),
        'departure_time': dj_date(flight.departure_time, 'h:i A'),
        'departure_day': flight.departure_time.strftime('%a'),
        'arrival_date': dj_date(flight.arrival_time, 'F d, Y'),
        'arrival_time': dj_date(flight.arrival_time, 'h:i A'),
        'duration': _duration(flight),
        'check_in_time': time_value(flight.check_in_time),
        'boarding_time': time_value(flight.boarding_time),
        'checked_baggage_kg': flight.checked_baggage_kg or 0,
        'cabin_baggage_kg': flight.cabin_baggage_kg or 0,
        'status': flight.get_status_display(),
    }


def _direct_passengers(booking, seats):
    """Collapse outbound/return seat rows to one passenger row per traveler."""
    outbound = [seat for seat in seats if seat.segment != 'RETURN']
    returns = [seat for seat in seats if seat.segment == 'RETURN']
    if not outbound:
        outbound = returns
        returns = []

    return_seats = {}
    for seat in returns:
        return_seats.setdefault(seat.passenger_name, []).append(seat)

    rows = []
    used_return = {}
    for index, seat in enumerate(outbound):
        name = seat.passenger_name or booking.primary_guest_name or 'Passenger'
        match_index = used_return.get(seat.passenger_name, 0)
        return_rows = return_seats.get(seat.passenger_name, [])
        return_seat = return_rows[match_index] if match_index < len(return_rows) else None
        used_return[seat.passenger_name] = match_index + 1
        rows.append({
            'name': name,
            'class': seat.get_fare_class_display() if seat.fare_class else 'Economy',
            'class_key': seat.fare_class or 'ECONOMY',
            'seat': seat.seat_number or '—',
            'return_seat': (return_seat.seat_number or '—') if return_seat else '',
            'doc_type': (seat.get_travel_document_type_display()
                         if seat.travel_document_type else '—'),
            # Passenger document number is not an airline ticket number.
            'doc_number': seat.travel_document_number or '—',
            'ticket_number': '',
            'passenger_type': '',
            'index': index + 1,
        })
    return rows


def _itinerary_summary(itinerary):
    """The journey's own header facts for the e-ticket."""
    timing = itinerary.timing
    return {
        'reference': itinerary.itinerary_reference or '—',
        'route': itinerary.route_label,
        'origin': itinerary.origin,
        'destination': itinerary.destination,
        'origin_code': itinerary.origin_code or '—',
        'destination_code': itinerary.destination_code or '—',
        'stops_label': itinerary.stops_label,
        'segment_count': itinerary.segment_count,
        'total_duration': timing['total_label'] or '—',
        'total_price': itinerary.total_price,
    }


def _itinerary_segments(itinerary, seats):
    """Per-segment print rows, each with every traveler's seat on that leg."""
    timing = itinerary.timing
    rows = []
    for position, entry in enumerate(timing['legs']):
        leg = entry['segment']
        order = leg.segment_order
        # The layover at index i sits between leg i and leg i + 1, so leg at
        # position p was reached after layover p - 1.
        layover_before = (timing['layovers'][position - 1]
                          if position > 0 else None)
        rows.append({
            'order': order,
            'flight_number': leg.flight_number,
            'airline_name': leg.airline.name,
            'airline_logo_url': leg.airline.logo_url,
            'origin': leg.origin,
            'destination': leg.destination,
            'origin_code': (leg.origin_airport.code
                            if leg.origin_airport_id else leg.origin_code) or '—',
            'destination_code': (leg.destination_airport.code
                                 if leg.destination_airport_id
                                 else leg.destination_code) or '—',
            'origin_city': (leg.origin_airport.city
                            if leg.origin_airport_id else leg.origin),
            'destination_city': (leg.destination_airport.city
                                 if leg.destination_airport_id else leg.destination),
            'origin_airport_name': (leg.origin_airport.airport_name
                                    if leg.origin_airport_id else ''),
            'destination_airport_name': (leg.destination_airport.airport_name
                                         if leg.destination_airport_id else ''),
            # The local times, not the stored UTC ones: a ticket that says a
            # Dubai flight lands at 14:00 when the airport clock says 18:00 is
            # worse than useless. The leg's own zone is already applied by
            # itinerary_timing.
            'departure_date': dj_date(entry['departure_local'], 'F d, Y'),
            'departure_time': dj_date(entry['departure_local'], 'h:i A'),
            'arrival_date': dj_date(entry['arrival_local'], 'F d, Y'),
            'arrival_time': dj_date(entry['arrival_local'], 'h:i A'),
            'departure_day': entry['departure_local'].strftime('%a'),
            'departure_timezone': leg.departure_timezone or '',
            'arrival_timezone': leg.arrival_timezone or '',
            'terminal': (leg.terminal or '').strip() or '—',
            'gate': (leg.gate or '').strip() or '—',
            'arrival_terminal': (leg.arrival_terminal or '').strip() or '—',
            'arrival_gate': (leg.arrival_gate or '').strip() or '—',
            'aircraft': (f"{leg.aircraft.model_name} ({leg.aircraft.tail_number})"
                         if leg.aircraft else '—'),
            'checked_baggage_kg': leg.checked_baggage_kg or 0,
            'cabin_baggage_kg': leg.cabin_baggage_kg or 0,
            'check_in_time': leg.check_in_time.strftime('%I:%M %p').lstrip('0')
                             if leg.check_in_time else '',
            'boarding_time': leg.boarding_time.strftime('%I:%M %p').lstrip('0')
                             if leg.boarding_time else '',
            'duration': entry['label'] or '—',
            'layover_before': layover_before['label'] if layover_before else '',
            'layover_airport': (layover_before['airport'].code
                                if layover_before and layover_before['airport']
                                else ''),
            'seats': {
                e.passenger_name: (e.seat_number or '—')
                for e in seats if e.segment_order == order
            },
        })
    return rows


def build_ticket_context(booking):
    """Assemble every datum the e-ticket needs, shared by HTML and PDF."""
    from datetime import datetime

    now = timezone.localtime()

    flight = booking.flight
    airline = flight.airline if flight else None
    itinerary = booking.itinerary if booking.is_itinerary_booking else None
    logo_url, logo_path = _airline_logo(airline)
    bill = _find_bill(booking)
    # Read once, in travel order: a connecting booking holds one seat row per
    # passenger per segment, so the plain id order would print the two segments
    # interleaved.
    seats = list(booking.itinerary_seats) if booking.pk else []

    if itinerary:
        passengers = _itinerary_passengers(booking, seats, itinerary)
    elif seats:
        passengers = _direct_passengers(booking, seats)
    else:
        passengers = [{
            'name': booking.primary_guest_name or 'Passenger',
            'class': 'Economy',
            'class_key': 'ECONOMY',
            'seat': '—',
            'doc_type': booking.get_travel_document_type_display() if booking.travel_document_type else '—',
            'doc_number': booking.travel_document_number or '—',
            'ticket_number': '',
            'passenger_type': '',
            'index': 1,
        }]

    outbound_summary = _flight_summary(flight)
    return_summary = _flight_summary(booking.return_flight)
    return_airline = booking.return_flight.airline if booking.return_flight else None
    return_logo_url, return_logo_path = _airline_logo(return_airline)
    departure_seat = next((seat for seat in seats if seat.segment != 'RETURN'), None)
    return_seat = next((seat for seat in seats if seat.segment == 'RETURN'), None)

    origin_code = (flight.origin_code or '').strip() or '—'
    dest_code = (flight.destination_code or '').strip() or '—'
    # A journey is flown from its first airport to its last, not from the first
    # leg's origin to the first leg's destination.
    if itinerary:
        origin_code = (itinerary.origin_code or origin_code).strip() or '—'
        dest_code = (itinerary.destination_code or dest_code).strip() or '—'

    qr_payload = ('ATRUE|SIM|{ref}|{flight}|{o}-{d}|{seats}|{status}'.format(
        ref=booking.booking_reference,
        flight=(itinerary.itinerary_reference if itinerary else flight.flight_number),
        o=origin_code, d=dest_code,
        seats=','.join(p['seat'] for p in passengers if p['seat'] != '—') or '—',
        status=booking.status,
    ))

    return {
        'booking': booking,
        'bill': bill,
        'airline': {
            'name': airline.name if airline else '—',
            'code': getattr(airline, 'airline_id', None) or '—',
            'contact': getattr(airline, 'contact_number', '') or '',
            'email': getattr(airline, 'email', '') or '',
            'logo_url': logo_url,
            'logo_path': logo_path,
        },
        'return_airline': {
            'name': return_airline.name if return_airline else '',
            'logo_url': return_logo_url,
            'logo_path': return_logo_path,
        },
        'return_fare_type': (
            return_seat.get_fare_class_display()
            if return_seat and return_seat.fare_class
            else departure_seat.get_fare_class_display()
            if departure_seat and departure_seat.fare_class
            else 'Not provided'
        ),
        'flight': outbound_summary,
        'return_flight': return_summary,
        'passengers': passengers,
        'passenger_count': len(passengers),
        'is_itinerary': bool(itinerary),
        'itinerary': _itinerary_summary(itinerary) if itinerary else None,
        'segments': _itinerary_segments(itinerary, seats) if itinerary else [],
        'lead': {
            'name': booking.primary_guest_name or '—',
            'contact': booking.contact_number or booking.payer_contact or '—',
            'email': booking.contact_email or '—',
        },
        'booking_info': {
            'booking_reference': booking.booking_reference,
            # This project has no airline-provider PNR field or integration.
            'airline_pnr': '',
            'booked_at': dj_date(booking.created_at, 'F d, Y · h:i A')
                         if getattr(booking, 'created_at', None) else '—',
            'status': booking.get_status_display(),
            'status_key': booking.status,
            'payment_status': bill.get_status_display() if bill else '—',
            'trip_type': booking.get_trip_type_display(),
            'trip_type_key': booking.trip_type,
            'return_date': dj_date(booking.return_date, 'F d, Y') if booking.return_date else '—',
            'fare_type': (departure_seat.get_fare_class_display()
                          if departure_seat and departure_seat.fare_class
                          else 'Not provided'),
            'baggage': (f"Extra baggage: {booking.extra_baggage_kg} kg"
                        if booking.extra_baggage else ''),
            'baggage_kg': booking.extra_baggage_kg,
        },
        'fare': _fare_summary(booking, bill),
        'qr': {
            'payload': qr_payload,
            'png': _qr_png(qr_payload),
        },
        'issued_on': now.strftime('%B %d, %Y · %H:%M'),
        'download_name': f"ATRUE-Eticket-{booking.booking_reference}.pdf",
    }


def _find_bill(booking):
    try:
        from atrue_core.services import bill_for_booking
        return bill_for_booking(booking)
    except Exception:
        return None
