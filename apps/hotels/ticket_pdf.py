"""Server-side PDF renderer for the ATRUE hotel reservation voucher.

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
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing, Line

NAVY = colors.HexColor('#0f172a')
BLUE = colors.HexColor('#1d4ed8')
TEAL = colors.HexColor('#0d9488')
GREEN = colors.HexColor('#ecfdf5')
GREEN_DARK = colors.HexColor('#065f46')
LIGHT = colors.HexColor('#f8fafc')
BORDER = colors.HexColor('#e2e8f0')
SLATE = colors.HexColor('#64748b')


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
    s_estab = ParagraphStyle('estab', fontName='Helvetica-Bold', fontSize=13,
                             textColor=NAVY, leading=16)
    s_sub = ParagraphStyle('sub', fontName='Helvetica', fontSize=8, textColor=SLATE,
                           leading=11)
    s_small = ParagraphStyle('small', fontName='Helvetica', fontSize=8.5,
                             textColor=SLATE, leading=11)
    s_label = ParagraphStyle('label', fontName='Helvetica-Bold', fontSize=6.5,
                             textColor=SLATE, leading=9)
    s_value = ParagraphStyle('value', fontName='Helvetica-Bold', fontSize=9.5,
                             textColor=NAVY, leading=12)
    s_stubcode = ParagraphStyle('stubcode', fontName='Helvetica-Bold', fontSize=15,
                                textColor=NAVY, leading=18)
    s_big = ParagraphStyle('big', fontName='Helvetica-Bold', fontSize=10,
                           textColor=NAVY, leading=13)
    s_hdr = ParagraphStyle('hdr', fontName='Helvetica-Bold', fontSize=11,
                           textColor=NAVY, leading=14)
    s_aster = ParagraphStyle('aster', fontName='Helvetica', fontSize=7.5,
                             textColor=SLATE, leading=10)

    hotel = ctx['hotel']
    info = ctx['booking_info']
    fare = ctx['fare']

    # ---- Header / hotel block ---------------------------------------------
    logo = None
    if hotel['logo_path']:
        try:
            from PIL import Image as PILImage
            im = PILImage.open(hotel['logo_path'])
            w, h = im.size
            target_h = 46
            target_w = max(20, int(w * target_h / max(1, h)))
            logo = RLImage(hotel['logo_path'], width=target_w, height=target_h)
        except Exception:
            logo = None

    hotel_cell = [
        [logo if logo else Paragraph(hotel['name'], s_estab)],
        [Paragraph(f"{hotel['name']} · Estab. ID {hotel['code']}", s_sub)],
        [Paragraph(f"{hotel['location']} · {hotel['contact']} · {hotel['email']}", s_small)],
    ]
    hotel_tbl = Table(hotel_cell, colWidths=[300])
    hotel_tbl.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    right_hdr = [
        [Paragraph('RESERVATION VOUCHER', ParagraphStyle(
            'vch', parent=s_title, textColor=BLUE))],
        [Paragraph(f"Booking Ref: <b>{info['pnr']}</b>", s_big)],
        [Paragraph(f"Issued: {ctx['issued_on']}", s_small)],
    ]
    right_tbl = Table(right_hdr, colWidths=[200])
    right_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
    ]))

    header = Table([[hotel_tbl, Paragraph('', s_sub), right_tbl]], colWidths=[300, 40, 200])
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

    # ---- Stay band ---------------------------------------------------------
    def stay_leg(title, date_val, sub):
        return [
            [Paragraph(title, ParagraphStyle('sl', fontName='Helvetica-Bold',
                                             fontSize=8.5, textColor=colors.white, leading=11))],
            [Paragraph(date_val, ParagraphStyle('sd', fontName='Helvetica-Bold',
                                                fontSize=15, textColor=colors.white, leading=19))],
            [Paragraph(sub, ParagraphStyle('ss', fontName='Helvetica',
                                           fontSize=8, textColor=colors.white, leading=11))],
        ]

    band_left = [
        [Paragraph(f"ROOMS × {ctx['room_count']}", ParagraphStyle(
            'rc', fontName='Helvetica-Bold', fontSize=14, textColor=colors.white, leading=17))],
        [Paragraph(f"{ctx['nights']} night(s) · {info['guests']}", ParagraphStyle(
            'ng', fontName='Helvetica', fontSize=8.5, textColor=colors.white, leading=11))],
        [Paragraph('Check-in time: 2:00 PM · Check-out: 12:00 NN', ParagraphStyle(
            'ct', fontName='Helvetica', fontSize=8, textColor=colors.white, leading=10))],
    ]

    dep = stay_leg('CHECK-IN', ctx['check_in'], 'from 2:00 PM')
    arr = stay_leg('CHECK-OUT', ctx['check_out'], 'until 12:00 NN')
    arrow = [[Paragraph('→', ParagraphStyle('ar', fontName='Helvetica-Bold', fontSize=26,
                                            textColor=colors.white, leading=30))],
             [Paragraph(info['pnr'], ParagraphStyle('pn', fontName='Helvetica-Bold',
                                                    fontSize=7, textColor=colors.white, leading=9))]]

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

    # ---- Rooms table -------------------------------------------------------
    r_head = Paragraph('ROOMS &amp; GUESTS', s_hdr)
    r_rows = [
        [Paragraph('#', s_label), Paragraph('ROOM', s_label),
         Paragraph('GUEST', s_label), Paragraph('DATES', s_label),
         Paragraph('NIGHTS', s_label), Paragraph('GUESTS', s_label),
         Paragraph('VOUCHER NO.', s_label)]
    ]
    for r in ctx['rooms']:
        r_rows.append([
            Paragraph(str(r['index']), s_value),
            Paragraph(f"{r['room_type']} · No. {r['room_number']}", s_value),
            Paragraph(r['guest'], s_small),
            Paragraph(f"{r['check_in']} → {r['check_out']}", s_small),
            Paragraph(str(r['nights']), s_value),
            Paragraph(f"{r['adults']}A / {r['children']}C", s_value),
            Paragraph(_quote(r['voucher_number']), s_value),
        ])
    r_tbl = Table(r_rows, colWidths=[22, 120, 110, 150, 40, 45, 95])
    r_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    # ---- Booking & payment detail grid ------------------------------------
    def det(label, value):
        return [Paragraph(label, s_label), Paragraph(_quote(value), s_value)]

    details = Table([
        [det('BOOKING REFERENCE', info['pnr']),
         det('BOOKING DATE', info['booked_at'])],
        [det('BOOKING STATUS', info['status']),
         det('PAYMENT STATUS', info['payment_status'])],
        [det('NUMBER OF ROOMS', str(info['rooms'])),
         det('NIGHTS', str(info['nights']))],
        [det('TOTAL GUESTS', info['guests']),
         det('LEAD GUEST CONTACT', f"{ctx['lead']['name']} · {ctx['lead']['contact']}")],
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
    fare_rows = [
        [Paragraph('FARE SUMMARY', s_hdr), Paragraph('', s_hdr)],
        [Paragraph('Room charges (%d room(s), %d night(s))'
                   % (ctx['room_count'], ctx['nights']), s_small),
         Paragraph(_php(fare['base_fare']), s_value)],
    ]
    for s in fare['services']:
        fare_rows.append([Paragraph('Service: %s' % _quote(s['label']), s_small),
                          Paragraph(_php(s['amount']), s_value)])
    for a in fare['amenities']:
        fare_rows.append([Paragraph('Amenity: %s' % _quote(a['label']), s_small),
                          Paragraph(_php(a['amount']), s_value)])
    if fare['other']:
        for o in fare['other']:
            fare_rows.append([Paragraph('Other: %s' % _quote(o['label']), s_small),
                              Paragraph(_php(o['amount']), s_value)])
    fare_rows += [
        [Paragraph('TOTAL AMOUNT', ParagraphStyle('tt', parent=s_big, textColor=TEAL)),
         Paragraph(_php(fare['total']), ParagraphStyle('tv', parent=s_value, textColor=TEAL))],
        [Paragraph('Amount paid', s_small), Paragraph(_php(fare['paid']), s_small)],
        [Paragraph('Balance due', s_small), Paragraph(_php(fare['balance']), s_small)],
        [Paragraph('Simulated itinerary pricing — no real taxes or fees are charged.', s_aster),
         Paragraph('', s_small)],
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
        qr_img = RLImage(BytesIO(ctx['qr']['png']), width=64, height=64)
    except Exception:
        pass
    stub_rows = [[Paragraph('STAY DETAILS STUB', s_label)],
                 [qr_img if qr_img else Paragraph('QR', s_big)],
                 [Paragraph(info['pnr'], s_stubcode)],
                 [Paragraph('Scan to verify this booking (simulation).', ParagraphStyle(
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

    # ---- Assemble ----------------------------------------------------------
    story = [header, Spacer(1, 6), _dashed_line(), Spacer(1, 8), band,
             Spacer(1, 12), r_head, Spacer(1, 4), r_tbl, Spacer(1, 12),
             details, Spacer(1, 10), lower, Spacer(1, 14), _dashed_line(),
             Spacer(1, 8)]
    story.extend([
        Paragraph(
            "<b>SIMULATION / ACADEMIC USE ONLY</b> — This document is a simulated "
            "academic reservation voucher generated by the ATRUE Travel &amp; Tours "
            "system. It is <b>not</b> a valid hotel confirmation and cannot be used "
            "for an actual stay.", s_small),
        Spacer(1, 3),
        Paragraph(f"Generated {ctx['issued_on']} · Booking {info['pnr']} · "
                  f"{hotel['name']} · ATRUE Travel &amp; Tours Booking System", s_aster),
    ])
    story.append(Spacer(1, 4))

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor('#f8fafc'))
        canvas.rect(0, 0, A4[0], 10, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor('#e2e8f0'))
        canvas.setFont('Helvetica', 6)
        canvas.restoreState()

    return story