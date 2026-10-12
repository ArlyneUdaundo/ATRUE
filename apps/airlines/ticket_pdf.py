"""Server-side PDF renderer for the ATRUE airline e-ticket.

Uses reportlab (Platypus) to produce a print-ready A4 document from the exact
same ``build_ticket_context`` used by the HTML ticket, so screen and PDF never
disagree. Standard Helvetica fonts are used (they do not carry the Peso
U+20B1 glyph, so amounts are prefixed with "PhP").
"""
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing, Line
from reportlab.graphics import renderPDF

NAVY = colors.HexColor('#0f172a')
BLUE = colors.HexColor('#1d4ed8')
TEAL = colors.HexColor('#0d9488')
GREEN = colors.HexColor('#ecfdf5')
GREEN_DARK = colors.HexColor('#065f46')
LIGHT = colors.HexColor('#f8fafc')
BORDER = colors.HexColor('#e2e8f0')
SLATE = colors.HexColor('#64748b')
DARK = colors.HexColor('#0f172a')


def _php(value):
    return "PhP " + format(Decimal(str(value or 0)), ",.2f")


def _quote(s):
    return str(s or '')


def _dashed_line():
    d = Drawing(0, 0)
    line = Line(0, 0, 520, 0)
    line.strokeColor = BORDER
    line.strokeDashArray = (2, 3)
    d.add(line)
    d.width = 520
    d.height = 2
    return d


def _build(builder_ctx):
    ctx = builder_ctx
    s_title = ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=15,
                             textColor=NAVY, leading=18)
    s_airline = ParagraphStyle('airline', fontName='Helvetica-Bold', fontSize=13,
                               textColor=NAVY, leading=16)
    s_sub = ParagraphStyle('sub', fontName='Helvetica', fontSize=8, textColor=SLATE,
                           leading=11)
    s_small = ParagraphStyle('small', fontName='Helvetica', fontSize=8.5,
                             textColor=SLATE, leading=11)
    s_label = ParagraphStyle('label', fontName='Helvetica-Bold', fontSize=6.5,
                             textColor=SLATE, leading=9)
    s_value = ParagraphStyle('value', fontName='Helvetica-Bold', fontSize=9.5,
                             textColor=NAVY, leading=12)
    s_flightno = ParagraphStyle('flightno', fontName='Helvetica-Bold', fontSize=22,
                                textColor=colors.white, leading=24)
    s_code = ParagraphStyle('code', fontName='Helvetica-Bold', fontSize=26,
                            textColor=colors.white, leading=30)
    s_stubcode = ParagraphStyle('stubcode', fontName='Helvetica-Bold', fontSize=15,
                                textColor=NAVY, leading=18)
    s_big = ParagraphStyle('big', fontName='Helvetica-Bold', fontSize=10,
                           textColor=NAVY, leading=13)
    s_hdr = ParagraphStyle('hdr', fontName='Helvetica-Bold', fontSize=11,
                           textColor=NAVY, leading=14)
    s_aster = ParagraphStyle('aster', fontName='Helvetica', fontSize=7.5,
                             textColor=SLATE, leading=10)

    airline = ctx['airline']
    flight = ctx['flight']
    info = ctx['booking_info']
    fare = ctx['fare']

    # ---- Header / airline block -------------------------------------------
    logo = None
    if airline['logo_path']:
        try:
            from PIL import Image as PILImage
            im = PILImage.open(airline['logo_path'])
            w, h = im.size
            target_h = 46
            target_w = max(20, int(w * target_h / max(1, h)))
            logo = Image(airline['logo_path'], width=target_w, height=target_h)
        except Exception:
            logo = None

    airline_cell = [
        [logo if logo else Paragraph(airline['name'], s_airline)],
        [Paragraph(f"{airline['name']} · Airline Code {airline['code']}", s_sub)],
        [Paragraph(f"{airline['contact']} · {airline['email']}", s_small)],
    ]
    airline_tbl = Table(airline_cell, colWidths=[300])
    airline_tbl.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    right_hdr = [
        [Paragraph('ELECTRONIC TICKET', ParagraphStyle(
            'tkt', parent=s_title, textColor=BLUE)), ],
        [Paragraph(f"Booking Ref / PNR: <b>{info['pnr']}</b>", s_big)],
        [Paragraph(f"Issued: {ctx['issued_on']}", s_small)],
    ]
    right_tbl = Table(right_hdr, colWidths=[200])
    right_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 1), (0, 1), 'RIGHT'),
        ('ALIGN', (0, 2), (0, 2), 'RIGHT'),
    ]))

    header = Table([[airline_tbl, Paragraph('', s_sub), right_tbl]], colWidths=[300, 40, 200])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    status_badge = Table(
        [[Paragraph(f"STATUS: {info['status'].upper()}", ParagraphStyle(
            'st', fontName='Helvetica-Bold', fontSize=9, textColor=GREEN_DARK, leading=11))]],
        colWidths=[150])
    status_badge.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GREEN),
        ('ROUNDEDCORNERS', [6, 6, 6, 6]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))

    # ---- Boarding / flight band -------------------------------------------
    # A connecting journey's band shows the whole itinerary: its reference, the
    # journey's two ends and the total time.  The per-segment breakdown is
    # printed as its own table just below, so the band stays the same shape
    # whether there is one flight or six.
    itinerary = ctx.get('itinerary')
    if itinerary:
        band_left = [
            [Paragraph(f"ITINERARY {itinerary['reference']}", s_flightno)],
            [Paragraph(_quote(itinerary['route']), ParagraphStyle(
                'ac', fontName='Helvetica', fontSize=8.5, textColor=colors.white, leading=11))],
            [Paragraph(f"{itinerary['stops_label']} · {itinerary['segment_count']} segments",
                       ParagraphStyle('tg', fontName='Helvetica', fontSize=8.5,
                                      textColor=colors.white, leading=11))],
        ]
    else:
        band_left = [
            [Paragraph(f"FLIGHT {flight['number']}", s_flightno)],
            [Paragraph(f"{flight['aircraft']}", ParagraphStyle(
                'ac', fontName='Helvetica', fontSize=8.5, textColor=colors.white, leading=11))],
            [Paragraph(f"Terminal {flight['terminal']} · Gate {flight['gate']}", ParagraphStyle(
                'tg', fontName='Helvetica', fontSize=8.5, textColor=colors.white, leading=11))],
        ]

    def leg(code, city, date, day):
        return [
            [Paragraph(code, s_code)],
            [Paragraph(city, ParagraphStyle('city', fontName='Helvetica-Bold',
                                            fontSize=10, textColor=colors.white, leading=13))],
            [Paragraph(f"{day} {date}", ParagraphStyle('dt', fontName='Helvetica',
                                                       fontSize=8.5, textColor=colors.white, leading=11))],
        ]

    if itinerary:
        segments = ctx['segments']
        first_seg, last_seg = segments[0], segments[-1]
        dep = leg(itinerary['origin_code'], itinerary['origin'],
                  f"{first_seg['departure_date']} · {first_seg['departure_time']}",
                  first_seg['departure_day'])
        arr = leg(itinerary['destination_code'], itinerary['destination'],
                  f"{last_seg['arrival_date']} · {last_seg['arrival_time']}", '')
        duration = f"Total {itinerary['total_duration']}"
    else:
        dep = leg(flight['origin_code'], flight['origin'],
                  f"{flight['departure_date']} · {flight['departure_time']}", flight['departure_day'])
        arr = leg(flight['destination_code'], flight['destination'],
                  f"{flight['arrival_date']} · {flight['arrival_time']}", '')
        duration = flight['duration']

    arrow = [[Paragraph('→', ParagraphStyle('ar', fontName='Helvetica-Bold', fontSize=26,
                                            textColor=colors.white, leading=30))],
             [Paragraph(duration, ParagraphStyle('du', fontName='Helvetica-Bold',
                                                 fontSize=8, textColor=colors.white, leading=10))]]

    band = Table([[band_left, dep, arrow, arr]], colWidths=[160, 150, 60, 150])
    band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BLUE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('ALIGN', (3, 0), (3, -1), 'CENTER'),
    ]))

    # ---- Passenger table ---------------------------------------------------
    # A connecting journey's seat column lists that traveler's seat on every
    # segment in order, so one row per traveler stays one row per traveler.
    p_head = Paragraph('PASSENGER &amp; SEAT', s_hdr)
    p_rows_header = [
        [Paragraph('#', s_label), Paragraph('PASSENGER', s_label),
         Paragraph('CLASS', s_label),
         Paragraph('SEATS' if itinerary else 'SEAT', s_label),
         Paragraph('TRAVEL DOCUMENT', s_label), Paragraph('TICKET NO.', s_label)]
    ]
    for p in ctx['passengers']:
        p_rows_header.append([
            Paragraph(str(p['index']), s_value),
            Paragraph(_quote(p['name']), s_value),
            Paragraph(_quote(p['class']), s_value),
            Paragraph(_quote(p.get('seat_summary') or p['seat']), s_value),
            Paragraph(f"{p['doc_type']} {p['doc_number']}" if p['doc_type'] != '—' else '—', s_small),
            Paragraph(_quote(p['ticket_number']), s_value),
        ])
    p_tbl = Table(p_rows_header, colWidths=[22, 160, 60, 55, 140, 105])
    p_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))

    # ---- Booking & payment detail grid ------------------------------------
    def det(label, value):
        return [Paragraph(label, s_label), Paragraph(_quote(value), s_value)]

    details = Table([
        [det('BOOKING REFERENCE / PNR', info['pnr']),
         det('BOOKING DATE', info['booked_at'])],
        [det('BOOKING STATUS', info['status']),
         det('PAYMENT STATUS', info['payment_status'])],
        [det('FARE TYPE', info['fare_type']),
         det('NUMBER OF PASSENGERS', str(ctx['passenger_count']))],
        [det('TRIP TYPE', info['trip_type']),
         det('RETURN DATE', info['return_date'])],
        [det('BAGGAGE', info['baggage']),
         det('LEAD PASSENGER CONTACT', f"{ctx['lead']['name']} · {ctx['lead']['contact']}")],
    ], colWidths=[260, 260])
    details.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))

    # ---- Fare summary + QR stub -------------------------------------------
    fare_label = (f"Base fare ({ctx['passenger_count']} passenger(s), "
                  f"{itinerary['reference']})" if itinerary
                  else 'Base fare (%d passenger(s), %s)' % (ctx['passenger_count'], flight['number']))
    fare_rows = [
        [Paragraph('FARE SUMMARY', s_hdr), Paragraph('', s_hdr)],
        [Paragraph(fare_label, s_small),
         Paragraph(_php(fare['base_fare']), s_value)],
    ]
    for s in fare['services']:
        fare_rows.append([Paragraph('Additional service: %s' % _quote(s['label']), s_small),
                          Paragraph(_php(s['amount']), s_value)])
    fare_rows.append([Paragraph('Extra baggage%s' % ((' (%s kg)' % fare['baggage_kg']) if fare.get('baggage_kg') else ''), s_small), Paragraph(_php(fare['baggage']), s_value)])
    if fare['other']:
        for o in fare['other']:
            fare_rows.append([Paragraph('Other: %s' % _quote(o['label']), s_small),
                              Paragraph(_php(o['amount']), s_value)])
    fare_rows += [
        [Paragraph('TOTAL AMOUNT', ParagraphStyle('tt', parent=s_big, textColor=TEAL)),
         Paragraph(_php(fare['total']), ParagraphStyle('tv', parent=s_value, textColor=TEAL))],
        [Paragraph('Amount paid', s_small), Paragraph(_php(fare['paid']), s_small)],
        [Paragraph('Balance due', s_small), Paragraph(_php(fare['balance']), s_small)],
        [Paragraph('Simulated itinerary pricing — no real taxes or airport fees are charged.', s_aster), Paragraph('', s_small)],
    ]
    fare_tbl = Table(fare_rows, colWidths=[300, 100])
    fare_tbl.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
        ('INNERGRID', (0, 1), (-1, -1), 0.5, BORDER),
        ('LINEABOVE', (0, 4), (-1, 4), 0.8, TEAL),
        ('ROWBACKGROUNDS', (1, 1), (-1, -2), [colors.white, LIGHT]),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (1, 1), (1, -2), 'RIGHT'),
    ]))

    qr_img = None
    try:
        qr_img = Image(BytesIO(ctx['qr']['png']), width=64, height=64)
    except Exception:
        pass
    stub_rows = [[Paragraph('FLIGHT DETAILS STUB', s_label)],
                 [qr_img if qr_img else Paragraph('QR', s_big)],
                 [Paragraph(info['pnr'], s_stubcode)],
                 [Paragraph(f"Scan to verify this booking (simulation).", ParagraphStyle(
                     'sc', fontName='Helvetica', fontSize=6.5, textColor=SLATE, leading=9))],
                 [Paragraph(f"Issued {ctx['issued_on']}", s_aster)]]
    stub_tbl = Table(stub_rows, colWidths=[100])
    stub_tbl.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, TEAL),
        ('LINEAFTER', (0, 0), (0, -1), 1.4, TEAL),
        ('LINEBEFORE', (0, 0), (0, -1), 1.4, TEAL),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    stub_tbl = Table([[Paragraph('✂', s_small)], [stub_tbl]], colWidths=[100])
    stub_tbl.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    lower = Table([[fare_tbl, stub_tbl]], colWidths=[400, 120])
    lower.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    # ---- Itinerary segment table (connecting journeys only) ----------------
    # Built only when the booking is an itinerary, so a direct flight or a round
    # trip produces the exact same PDF as before.
    segment_block = []
    if itinerary:
        seg_rows = [[
            Paragraph('#', s_label), Paragraph('FLIGHT', s_label),
            Paragraph('ROUTE', s_label), Paragraph('DEPARTURE', s_label),
            Paragraph('ARRIVAL', s_label), Paragraph('DURATION', s_label),
            Paragraph('AIRCRAFT', s_label),
        ]]
        for seg in ctx['segments']:
            dur = seg['duration']
            if seg['layover_before']:
                dur += f"<br/><font size=6>{seg['layover_before']} layover at {seg['layover_airport']}</font>"
            seg_rows.append([
                Paragraph(str(seg['order']), s_value),
                Paragraph(_quote(seg['flight_number']), s_value),
                Paragraph(f"{seg['origin_code']} → {seg['destination_code']}", s_value),
                Paragraph(f"{seg['departure_date']}<br/>{seg['departure_time']}", s_small),
                Paragraph(f"{seg['arrival_date']}<br/>{seg['arrival_time']}", s_small),
                Paragraph(dur, s_small),
                Paragraph(_quote(seg['aircraft']), s_small),
            ])
        seg_tbl = Table(seg_rows, colWidths=[20, 60, 80, 105, 105, 105, 105])
        seg_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        segment_block = [
            Paragraph('ITINERARY', s_hdr), Spacer(1, 4), seg_tbl, Spacer(1, 4),
            Paragraph(f"Total journey time {itinerary['total_duration']} door to "
                      f"door, including every layover.", s_aster),
            Spacer(1, 12),
        ]

    # ---- Assemble ----------------------------------------------------------
    story = [header, Spacer(1, 6), _dashed_line(), Spacer(1, 8), band,
             Spacer(1, 12)] + segment_block + [
             p_head, Spacer(1, 4), p_tbl, Spacer(1, 12),
             details, Spacer(1, 10), lower, Spacer(1, 14), _dashed_line(),
             Spacer(1, 8)]
    story.extend([
        Paragraph(
            "<b>SIMULATION / ACADEMIC USE ONLY</b> — This document is a simulated "
            "academic booking ticket generated by the ATRUE Travel &amp; Tours "
            "system. It is <b>not</b> a valid airline ticket or boarding pass and "
            "cannot be used for travel.", s_small),
        Spacer(1, 3),
        Paragraph(f"Generated {ctx['issued_on']} · Booking {info['pnr']} · "
                  f"{airline['name']} · ATRUE Travel &amp; Tours Booking System", s_aster),
    ])

    # Sticky footer disclaimer on the page (below story).
    story.append(Spacer(1, 4))

    # Page background band accent
    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor('#f8fafc'))
        canvas.rect(0, 0, A4[0], 10, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor('#e2e8f0'))
        canvas.setFont('Helvetica', 6)
        canvas.restoreState()

    return story