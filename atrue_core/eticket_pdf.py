"""Server-side PDF renderer for every ATRUE establishment e-ticket.

Uses reportlab (Platypus) and renders from the exact same normalized context
``atrue_core.etickets.build_eticket_context`` produces for the generic HTML
ticket (``templates/etickets/eticket.html``), so screen and PDF never disagree.
Standard Helvetica fonts are used (no Peso U+20B1 glyph), so amounts are
prefixed with "PhP".
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
    return str((s or '').strip() or '—')


def _dashed_line():
    d = Drawing(0, 0)
    line = Line(0, 0, 520, 0)
    line.strokeColor = BORDER
    line.strokeDashArray = (2, 3)
    d.add(line)
    d.width = 520
    d.height = 2
    return d


def build_story(ctx):
    estab = ctx['establishment']
    info = ctx['booking_info']
    fare = ctx['fare']

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

    # ---- Header / establishment block --------------------------------------
    logo = None
    if estab['logo_path']:
        try:
            from PIL import Image as PILImage
            im = PILImage.open(estab['logo_path'])
            w, h = im.size
            target_h = 46
            target_w = max(20, int(w * target_h / max(1, h)))
            logo = RLImage(estab['logo_path'], width=target_w, height=target_h)
        except Exception:
            logo = None

    estab_cell = [
        [logo if logo else Paragraph(estab['name'], s_estab)],
        [Paragraph(f"{estab['name']} · Estab. ID {estab['code']}", s_sub)],
        [Paragraph(f"{estab['location']} · {estab['contact']} · {estab['email']}", s_small)],
    ]
    estab_tbl = Table(estab_cell, colWidths=[300])
    estab_tbl.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    right_hdr = [
        [Paragraph(ctx['doc_type'], ParagraphStyle(
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

    header = Table([[estab_tbl, Paragraph('', s_sub), right_tbl]], colWidths=[300, 40, 200])
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

    # ---- Booking band ---------------------------------------------------------
    def leg_cell(label, code, sub):
        return [
            [Paragraph(label, ParagraphStyle('bl', fontName='Helvetica-Bold',
                                             fontSize=8.5, textColor=colors.white, leading=11))],
            [Paragraph(code, ParagraphStyle('bc', fontName='Helvetica-Bold',
                                            fontSize=15, textColor=colors.white, leading=19))],
            [Paragraph(sub, ParagraphStyle('bs', fontName='Helvetica',
                                           fontSize=8, textColor=colors.white, leading=11))],
        ]

    band_left = [
        [Paragraph(_quote(ctx['band']['title']), ParagraphStyle(
            'bt', fontName='Helvetica-Bold', fontSize=14, textColor=colors.white, leading=17))],
        [Paragraph(_quote(ctx['band'].get('subtitle', '')), ParagraphStyle(
            'bsu', fontName='Helvetica', fontSize=8.5, textColor=colors.white, leading=11))],
        [Paragraph(_quote(ctx['band'].get('note', '')), ParagraphStyle(
            'bn', fontName='Helvetica', fontSize=8, textColor=colors.white, leading=10))],
    ]

    legs = ctx['band']['legs']
    band_cells = [band_left]
    band_widths = [170]
    for i, leg in enumerate(legs):
        arrow_w = 50 if i > 0 else 0
        if i > 0:
            band_cells.append([[
                [Paragraph('→', ParagraphStyle('ar', fontName='Helvetica-Bold', fontSize=26,
                                               textColor=colors.white, leading=30))],
                [Paragraph(info['pnr'], ParagraphStyle('pn', fontName='Helvetica-Bold',
                                                       fontSize=7, textColor=colors.white, leading=9))],
            ]])
            band_widths.append(arrow_w)
        band_cells.append(leg_cell(leg['label'], leg['code'], leg.get('sub', '')))
        band_widths.append(140 if len(legs) == 1 else 130)

    band = Table([band_cells], colWidths=band_widths[:len(band_cells)])
    band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BLUE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))

    # ---- Lead guest table -----------------------------------------------------
    lead = ctx['lead']
    lead_tbl = Table([[
        [Paragraph('LEAD GUEST / CONTACT', s_label)],
        [Paragraph('NAME', s_label), Paragraph('CONTACT', s_label),
         Paragraph('EMAIL', s_label), Paragraph('VOUCHER NO.', s_label)],
        [Paragraph(_quote(lead['name']), s_value),
         Paragraph(_quote(lead['contact']), s_small),
         Paragraph(_quote(lead['email']), s_small),
         Paragraph(_quote(ctx['voucher_number']), s_value)],
    ]], colWidths=[520])
    lead_tbl.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)),
        ('GRID', (0, 1), (-1, 1), 0.5, BORDER),
        ('GRID', (0, 2), (-1, 2), 0.5, BORDER),
        ('BACKGROUND', (0, 1), (-1, 1), LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    # ---- Details grid ---------------------------------------------------------
    grid = ctx['info_grid']
    pairs = []
    row = []
    for label, value in grid:
        row.append([Paragraph(label.upper(), s_label), Paragraph(_quote(value), s_value)])
        if len(row) == 2:
            pairs.append(row)
            row = []
    if row:
        pairs.append(row)
    if len(pairs[-1]) == 1:
        pairs[-1].append([Paragraph('', s_label), Paragraph('', s_value)])
    details = Table(pairs, colWidths=[260, 260])
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
    ]
    for r in fare['rows']:
        fare_rows.append([Paragraph(_quote(r['label']), s_small),
                          Paragraph(_php(r['amount']), s_value)])
    if not fare['has_breakdown']:
        fare_rows.append([Paragraph('Billed directly by the establishment.', s_aster),
                          Paragraph('', s_small)])
    fare_rows += [
        [Paragraph('TOTAL AMOUNT', ParagraphStyle('tt', parent=s_big, textColor=TEAL)),
         Paragraph(_php(fare['total']), ParagraphStyle('tv', parent=s_value, textColor=TEAL))],
        [Paragraph('Amount paid', s_small), Paragraph(_php(fare['paid']), s_small)],
        [Paragraph('Balance due', s_small), Paragraph(_php(fare['balance']), s_small)],
        [Paragraph('Simulated pricing — no real taxes or fees are charged.', s_aster),
         Paragraph('', s_small)],
    ]
    total_idx = len(fare_rows) - 4
    fare_tbl = Table(fare_rows, colWidths=[300, 100])
    fare_tbl.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
        ('INNERGRID', (0, 1), (-1, -1), 0.5, BORDER),
        ('LINEABOVE', (0, total_idx), (-1, total_idx), 0.8, TEAL),
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
    stub_rows = [[Paragraph(f"{ctx['doc_type'][:20].upper()} STUB", s_label)],
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

    story = [header, Spacer(1, 6), status_badge, Spacer(1, 2), _dashed_line(),
             Spacer(1, 8), band, Spacer(1, 12), lead_tbl, Spacer(1, 12),
             Paragraph('DETAILS', s_hdr), Spacer(1, 4), details,
             Spacer(1, 10), lower, Spacer(1, 14), _dashed_line(), Spacer(1, 8)]
    story.extend([
        Paragraph(
            "<b>SIMULATION / ACADEMIC USE ONLY</b> — This document is a simulated "
            "e-ticket generated by the ATRUE Travel &amp; Tours system. It is "
            "<b>not</b> a valid confirmation and cannot be used for an actual "
            "transaction.", s_small),
        Spacer(1, 3),
        Paragraph(f"Generated {ctx['issued_on']} · Booking {info['pnr']} · "
                  f"{estab['name']} · ATRUE Travel &amp; Tours Booking System", s_aster),
    ])
    story.append(Spacer(1, 4))
    return story


def build_pdf_response(ctx, filename=None):
    """Return an HttpResponse containing the rendered generic e-ticket PDF."""
    from django.http import HttpResponse

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=filename or ctx['download_name'],
        author='ATRUE Travel & Tours (Simulation)',
    )
    doc.build(build_story(ctx))
    buf.seek(0)
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'inline; filename="{filename or ctx["download_name"]}"'
    )
    return response