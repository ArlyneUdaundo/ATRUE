"""Landscape PDF renderer for the ATRUE flight itinerary document."""
from decimal import Decimal
from html import escape

from django.contrib.staticfiles import finders
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


NAVY = colors.HexColor('#172b4d')
BLUE = colors.HexColor('#1769d2')
PALE = colors.HexColor('#edf6ff')
LIGHT = colors.HexColor('#f7faff')
BORDER = colors.HexColor('#d9e5f1')
SLATE = colors.HexColor('#667991')
GREEN = colors.HexColor('#e7f7ee')
GREEN_TEXT = colors.HexColor('#146b46')
PAGE_SIZE = landscape(A4)


def _text(value):
    return escape(str(value or ''))


def _money(value):
    try:
        return 'PhP ' + format(Decimal(str(value or 0)), ',.2f')
    except Exception:
        return 'Not available'


def _styles():
    return {
        'title': ParagraphStyle('eti_title', fontName='Helvetica-Bold', fontSize=18,
                                leading=21, textColor=NAVY),
        'brand': ParagraphStyle('eti_brand', fontName='Helvetica-Bold', fontSize=13,
                                leading=15, textColor=BLUE),
        'subtitle': ParagraphStyle('eti_subtitle', fontName='Helvetica', fontSize=8.5,
                                   leading=11, textColor=SLATE),
        'label': ParagraphStyle('eti_label', fontName='Helvetica-Bold', fontSize=7,
                                leading=9, textColor=SLATE),
        'value': ParagraphStyle('eti_value', fontName='Helvetica-Bold', fontSize=9,
                                leading=12, textColor=NAVY),
        'body': ParagraphStyle('eti_body', fontName='Helvetica', fontSize=8,
                               leading=11, textColor=NAVY),
        'small': ParagraphStyle('eti_small', fontName='Helvetica', fontSize=7,
                                leading=9, textColor=SLATE),
        'section': ParagraphStyle('eti_section', fontName='Helvetica-Bold', fontSize=10,
                                  leading=13, textColor=NAVY),
        'code': ParagraphStyle('eti_code', fontName='Helvetica-Bold', fontSize=23,
                               leading=25, textColor=NAVY, alignment=1),
        'city': ParagraphStyle('eti_city', fontName='Helvetica-Bold', fontSize=8.5,
                               leading=11, textColor=NAVY, alignment=1),
        'right': ParagraphStyle('eti_right', fontName='Helvetica', fontSize=8,
                                leading=11, textColor=NAVY, alignment=2),
    }


def _section(title, style):
    table = Table([[Paragraph(_text(title), style)]], colWidths=[PAGE_SIZE[0] - 28 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PALE),
        ('BOX', (0, 0), (-1, -1), .5, BORDER),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return table


def _stack(items, width):
    """Stack flowables in a nested table that ReportLab can split safely."""
    table = Table([[item] for item in items], colWidths=[width])
    table.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    return table


def _flight_route(title, flight, airline_name, fare_type, style, *, logo_path=None):
    w = PAGE_SIZE[0] - 28 * mm
    half = (w - 86 * mm) / 2
    center = 86 * mm

    def airport(code, city, name, date, time, terminal, gate):
        extra = []
        if terminal:
            extra.append('Terminal ' + _text(terminal))
        if gate:
            extra.append('Gate ' + _text(gate))
        return [
            Paragraph(_text(code or '—'), style['code']),
            Paragraph(_text(city or '—'), style['city']),
            Paragraph(_text(name or 'Airport name not provided'), style['small']),
            Paragraph(f"{_text(date)} · {_text(time)}", style['value']),
            Paragraph(' · '.join(extra) if extra else 'Terminal / gate not provided', style['small']),
        ]

    left = airport(flight.get('origin_code'), flight.get('origin_city'),
                   flight.get('origin_airport'), flight.get('departure_date'),
                   flight.get('departure_time'), flight.get('terminal'), flight.get('gate'))
    right = airport(flight.get('destination_code'), flight.get('destination_city'),
                    flight.get('destination_airport'), flight.get('arrival_date'),
                    flight.get('arrival_time'), flight.get('arrival_terminal'),
                    flight.get('arrival_gate'))
    middle = [
        Paragraph('<font color="#1769d2"><b>FLIGHT</b></font>', ParagraphStyle(
            'eti_plane_' + title.replace(' ', '_'), fontName='Helvetica-Bold',
            fontSize=16, leading=18, textColor=BLUE, alignment=1)),
        Paragraph('------------------------------', ParagraphStyle(
            'eti_line_' + title.replace(' ', '_'), fontName='Helvetica', fontSize=7,
            leading=9, textColor=BLUE, alignment=1)),
        Paragraph(_text(flight.get('duration') or 'Duration not available'),
                  ParagraphStyle('eti_dur_' + title.replace(' ', '_'), parent=style['small'], alignment=1)),
    ]
    route = Table([[_stack(left, half), _stack(middle, center), _stack(right, half)]],
                  colWidths=[half, center, half])
    route.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
    ]))
    airline_cell = []
    if logo_path:
        try:
            airline_cell.append(Image(logo_path, width=26 * mm, height=10 * mm,
                                      kind='proportional'))
        except Exception:
            pass
    airline_cell.append(Paragraph(
        f"<b>{_text(airline_name)}</b> · {_text(flight.get('number'))}"
        f" · Class: {_text(fare_type or 'Not provided')}"
        f" · Aircraft: {_text(flight.get('aircraft') or 'Not provided')}", style['small']))
    baggage = []
    if flight.get('checked_baggage_kg'):
        baggage.append(f"Checked baggage: {flight['checked_baggage_kg']} kg")
    if flight.get('cabin_baggage_kg'):
        baggage.append(f"Cabin baggage: {flight['cabin_baggage_kg']} kg")
    airline_cell.append(Paragraph(_text(' · '.join(baggage) or 'Baggage allowance not provided'), style['small']))
    strip = Table([[_stack(airline_cell, w)]], colWidths=[w])
    strip.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT),
        ('BOX', (0, 0), (-1, -1), .5, BORDER),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return [
        _section(title, style['section']), route, strip,
        Spacer(1, 7),
    ]


def _build(ctx):
    style = _styles()
    w = PAGE_SIZE[0] - 28 * mm
    story = []

    brand_path = finders.find('img/atrue-logo-transparent.png')
    brand = []
    if brand_path:
        try:
            brand.append(Image(brand_path, width=20 * mm, height=20 * mm,
                               kind='proportional'))
        except Exception:
            pass
    brand.append(Paragraph('<b>ATRUE</b><br/><font size="7" color="#667991">TRAVEL &amp; TOURS</font>', style['brand']))
    info = ctx['booking_info']
    header_left = Table([[_stack(brand, 28 * mm), _stack([
                                 Paragraph('E-Ticket Itinerary', style['title']),
                                 Paragraph('Flight Booking Confirmation', style['subtitle'])], 75 * mm)]],
                        colWidths=[28 * mm, 75 * mm])
    header_left.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    header_right = Table([
        [Paragraph('DOCUMENT GENERATED', style['label']), Paragraph(_text(ctx['issued_on']), style['value'])],
        [Paragraph('ATRUE BOOKING NUMBER', style['label']), Paragraph(_text(info['booking_reference']), style['value'])],
        [Paragraph('AIRLINE PNR', style['label']), Paragraph(_text(info.get('airline_pnr') or 'Not available'), style['value'])],
        [Paragraph('BOOKING STATUS', style['label']), Paragraph(_text(info['status']), style['value'])],
    ], colWidths=[44 * mm, 54 * mm])
    header_right.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    header = Table([[header_left, header_right]], colWidths=[w * .66, w * .34])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, -1), .8, BORDER),
    ]))
    story.extend([header, Spacer(1, 8)])

    # Passenger details contain one row per actual passenger. The database has
    # no airline-issued ticket number or passenger-type field, so neither is made up.
    story.append(_section('PASSENGER DETAILS', style['section']))
    p_rows = [[Paragraph('#', style['label']), Paragraph('PASSENGER NAME', style['label']),
               Paragraph('CABIN CLASS', style['label']), Paragraph('SEAT(S)', style['label']),
               Paragraph('TRAVEL DOCUMENT TYPE', style['label'])]]
    for passenger in ctx['passengers']:
        seat = passenger.get('seat_summary') or passenger.get('seat') or 'Not assigned'
        if passenger.get('return_seat'):
            seat += ' / ' + passenger['return_seat']
        doc_type = passenger.get('doc_type') if passenger.get('doc_type') != '—' else 'Not provided'
        p_rows.append([
            Paragraph(str(passenger['index']), style['body']),
            Paragraph(_text(passenger['name']), style['value']),
            Paragraph(_text(passenger.get('class') or 'Not provided'), style['body']),
            Paragraph(_text(seat), style['body']),
            Paragraph(_text(doc_type), style['body']),
        ])
    p_table = Table(p_rows, colWidths=[10 * mm, 70 * mm, 40 * mm, 55 * mm, w - 175 * mm], repeatRows=1)
    p_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT), ('GRID', (0, 0), (-1, -1), .45, BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.extend([p_table, Spacer(1, 5), Paragraph(
        'Keep this ATRUE itinerary for reference and check-in. Airline ticket numbers are shown only when an airline/provider supplies them.',
        style['small']), Spacer(1, 9)])

    story.append(_section('FLIGHT DETAILS', style['section']))
    airline_logo = ctx['airline'].get('logo_path')
    if ctx.get('itinerary'):
        segments = ctx['segments']
        if segments:
            first, last = segments[0], segments[-1]
            journey = {
                'number': ctx['itinerary']['reference'],
                'origin_code': ctx['itinerary']['origin_code'],
                'origin_city': first.get('origin_city'),
                'origin_airport': first.get('origin_airport_name'),
                'departure_date': first['departure_date'], 'departure_time': first['departure_time'],
                'terminal': first.get('terminal'), 'gate': first.get('gate'),
                'destination_code': ctx['itinerary']['destination_code'],
                'destination_city': last.get('destination_city'),
                'destination_airport': last.get('destination_airport_name'),
                'arrival_date': last['arrival_date'], 'arrival_time': last['arrival_time'],
                'arrival_terminal': last.get('arrival_terminal'), 'arrival_gate': last.get('arrival_gate'),
                'duration': ctx['itinerary']['total_duration'], 'aircraft': '',
            }
            story.extend(_flight_route(
                'OUTBOUND FLIGHT · ' + ctx['itinerary']['stops_label'], journey,
                ctx['airline']['name'], info['fare_type'], style, logo_path=airline_logo))
        segment_rows = [[Paragraph('#', style['label']), Paragraph('AIRLINE / FLIGHT', style['label']),
                         Paragraph('ROUTE', style['label']), Paragraph('DEPARTURE', style['label']),
                         Paragraph('ARRIVAL', style['label']), Paragraph('DURATION / LAYOVER', style['label']),
                         Paragraph('AIRCRAFT', style['label'])]]
        for seg in segments:
            segment_rows.append([
                Paragraph(str(seg['order']), style['body']),
                Paragraph(_text(seg.get('airline_name')) + '<br/><b>' + _text(seg['flight_number']) + '</b>', style['body']),
                Paragraph(_text(seg['origin_code']) + ' to ' + _text(seg['destination_code']), style['value']),
                Paragraph(_text(seg['departure_date']) + '<br/>' + _text(seg['departure_time']), style['small']),
                Paragraph(_text(seg['arrival_date']) + '<br/>' + _text(seg['arrival_time']), style['small']),
                Paragraph(_text(seg['duration']) + (('<br/>Layover: ' + _text(seg['layover_before']) + ' at ' + _text(seg['layover_airport'])) if seg['layover_before'] else ''), style['small']),
                Paragraph(_text(seg['aircraft'] or 'Not provided'), style['small']),
            ])
        seg_table = Table(segment_rows, colWidths=[9 * mm, 48 * mm, 48 * mm, 47 * mm, 47 * mm, 65 * mm, w - 264 * mm], repeatRows=1)
        seg_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT), ('GRID', (0, 0), (-1, -1), .45, BORDER),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.extend([seg_table, Spacer(1, 8)])
    else:
        flight = ctx['flight']
        story.extend(_flight_route('OUTBOUND FLIGHT', flight, ctx['airline']['name'],
                                   info['fare_type'], style, logo_path=airline_logo))

    if ctx.get('return_flight'):
        return_flight = ctx['return_flight']
        return_airline = ctx.get('return_airline') or {}
        story.extend(_flight_route(
            'RETURN FLIGHT', return_flight,
            return_airline.get('name') or ctx['airline']['name'],
            ctx.get('return_fare_type') or info['fare_type'], style,
            logo_path=return_airline.get('logo_path')))

    story.append(_section('IMPORTANT TRAVEL INFORMATION', style['section']))
    flight = ctx['flight']
    checkin = ('Check-in time: ' + flight['check_in_time']
               if flight.get('check_in_time') else 'Check the airline\'s official check-in and airport arrival guidance.')
    if flight.get('boarding_time'):
        checkin += '<br/>Boarding: ' + _text(flight['boarding_time'])
    docs = 'Bring valid travel documents required for the route and keep the ATRUE booking number available.'
    checked = (f"Checked baggage: {flight['checked_baggage_kg']} kg"
               if flight.get('checked_baggage_kg') else 'Checked baggage allowance not specified.')
    cabin = (f"Cabin baggage: {flight['cabin_baggage_kg']} kg"
             if flight.get('cabin_baggage_kg') else 'Cabin baggage allowance not specified.')
    reminders = 'Flight details may change. Confirm current schedule and requirements with the airline.'
    info_cells = [
        ('CHECK-IN INSTRUCTIONS', checkin),
        ('TRAVEL DOCUMENTS', docs),
        ('BAGGAGE ALLOWANCE', checked + '<br/>' + cabin),
        ('REMINDERS', reminders + '<br/>Schedule status: ' + _text(flight.get('status'))),
    ]
    info_table = Table([[Paragraph('<b>' + label + '</b><br/>' + body, style['small'])
                         for label, body in info_cells]], colWidths=[w / 4] * 4)
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT), ('BOX', (0, 0), (-1, -1), .5, BORDER),
        ('INNERGRID', (0, 0), (-1, -1), .5, BORDER), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.extend([info_table, Spacer(1, 8), _section('BOOKING & PAYMENT', style['section'])])

    info_cells = [
        ('ATRUE BOOKING NUMBER', info['booking_reference']),
        ('AIRLINE PNR', info.get('airline_pnr') or 'Not available'),
        ('BOOKING STATUS', info['status']),
        ('PAYMENT STATUS', info['payment_status']),
        ('TRIP TYPE', info['trip_type']),
        ('PASSENGERS', str(ctx['passenger_count'])),
        ('BOOKED ON', info['booked_at']),
        ('CABIN CLASS', info['fare_type']),
    ]
    booking_rows = []
    for start in range(0, len(info_cells), 4):
        booking_rows.append([Paragraph('<font color="#667991" size="6"><b>' + _text(label)
                                       + '</b></font><br/><b>' + _text(value) + '</b>', style['body'])
                             for label, value in info_cells[start:start + 4]])
    booking_table = Table(booking_rows, colWidths=[w / 4] * 4)
    booking_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), .45, BORDER), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.extend([booking_table, Spacer(1, 8)])

    fare = ctx['fare']
    if fare.get('has_breakdown'):
        fare_lines = [[Paragraph('FARE SUMMARY', style['section']),
                       Paragraph('AMOUNT', style['label'])],
                      [Paragraph('Total amount', style['body']), Paragraph(_money(fare['total']), style['value'])],
                      [Paragraph('Amount paid', style['body']), Paragraph(_money(fare['paid']), style['body'])],
                      [Paragraph('Balance due', style['body']), Paragraph(_money(fare['balance']), style['body'])]]
        fare_table = Table(fare_lines, colWidths=[w - 45 * mm, 45 * mm], hAlign='LEFT')
        fare_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), .5, BORDER), ('INNERGRID', (0, 0), (-1, -1), .4, BORDER),
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT), ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.extend([fare_table, Spacer(1, 8)])

    story.extend([Spacer(1, 9), Paragraph(
        '<b>ATRUE · Discover more. Travel further.</b><br/>'
        'SIMULATION / ACADEMIC USE ONLY — This itinerary reflects ATRUE booking data. '
        'It is not an airline-issued ticket or boarding pass.', style['small'])])

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(PALE)
        canvas.rect(0, 0, PAGE_SIZE[0], 5 * mm, fill=1, stroke=0)
        canvas.restoreState()

    return story, on_page
