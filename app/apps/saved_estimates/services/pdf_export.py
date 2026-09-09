from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PAGE_MARGIN = 16 * mm


def estimate_pdf_bytes(estimate):
    """Return a standalone PDF quotation generated from an immutable snapshot."""
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=PAGE_MARGIN,
        leftMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=f'{estimate.reference} Freight Estimate',
        author='Freight Calculator',
    )

    styles = _styles()
    story = [
        _header_table(estimate, styles),
        Spacer(1, 6 * mm),
        Paragraph('Shipment', styles['section']),
        Spacer(1, 2 * mm),
        _shipment_table(estimate, styles),
        Spacer(1, 6 * mm),
        Paragraph('Freight items', styles['section']),
        Spacer(1, 2 * mm),
        _items_table(estimate, styles),
        Spacer(1, 6 * mm),
        Paragraph('Available freight options', styles['section']),
        Spacer(1, 2 * mm),
        _options_table(estimate, styles),
        Spacer(1, 6 * mm),
        Paragraph(
            'Rates are estimates only and exclude GST. Final pricing may vary due to '
            'applicable fuel surcharges and shipment conditions.',
            styles['disclaimer'],
        ),
    ]

    document.build(story)
    return output.getvalue()


def estimate_pdf_filename(estimate):
    return f'{estimate.reference}.pdf'


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'EstimateTitle',
            parent=base['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#082a58'),
            spaceAfter=1 * mm,
        ),
        'reference': ParagraphStyle(
            'EstimateReference',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=13,
            textColor=colors.HexColor('#59718e'),
        ),
        'client': ParagraphStyle(
            'EstimateClient',
            parent=base['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=13,
            alignment=TA_RIGHT,
            textColor=colors.HexColor('#132238'),
        ),
        'meta_right': ParagraphStyle(
            'EstimateMetaRight',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            alignment=TA_RIGHT,
            textColor=colors.HexColor('#59718e'),
        ),
        'section': ParagraphStyle(
            'EstimateSection',
            parent=base['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=15,
            textColor=colors.HexColor('#082a58'),
            spaceAfter=0,
        ),
        'cell': ParagraphStyle(
            'EstimateCell',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=8.3,
            leading=10.5,
            alignment=TA_LEFT,
        ),
        'cell_right': ParagraphStyle(
            'EstimateCellRight',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=8.3,
            leading=10.5,
            alignment=TA_RIGHT,
        ),
        'header_cell': ParagraphStyle(
            'EstimateHeaderCell',
            parent=base['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8.2,
            leading=10,
            textColor=colors.HexColor('#193154'),
        ),
        'disclaimer': ParagraphStyle(
            'EstimateDisclaimer',
            parent=base['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=11,
            textColor=colors.HexColor('#59718e'),
        ),
    }


def _header_table(estimate, styles):
    created = estimate.created_at.strftime('%d %b %Y %H:%M')
    left = [
        Paragraph('Freight estimate', styles['title']),
        Paragraph(_text(estimate.reference), styles['reference']),
    ]
    right = [
        Paragraph(_text(estimate.client.name), styles['client']),
        Paragraph(created, styles['meta_right']),
    ]
    table = Table([[left, right]], colWidths=[105 * mm, 57 * mm])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#dce5f1')),
    ]))
    return table


def _shipment_table(estimate, styles):
    source = estimate.input_snapshot or {}
    from_address = source.get('from_address') or {}
    from_label = from_address.get('name') or 'Default / Not selected'
    cubic_margin = source.get('cubic_margin_percent')
    values = [
        ('From', from_label),
        ('Destination', estimate.destination_label or '-'),
        ('Tailgate', source.get('tailgate') or '-'),
        ('Cubic margin', f'{cubic_margin if cubic_margin is not None else 0}%'),
        ('Total weight', _with_unit(estimate.total_weight_kg, 'kg')),
        ('Total cubic', _with_unit(estimate.total_cubic_m3, 'm3')),
        ('Best estimate ex GST', _money(estimate.best_estimate_ex_gst)),
    ]
    rows = [
        [Paragraph(_text(label), styles['header_cell']), Paragraph(_text(value), styles['cell'])]
        for label, value in values
    ]
    table = Table(rows, colWidths=[42 * mm, 120 * mm])
    table.setStyle(_body_table_style())
    return table


def _items_table(estimate, styles):
    headers = ['SKU', 'Qty', 'Type', 'L (m)', 'W (m)', 'H (m)', 'Weight (kg)', 'Cubic (m3)']
    rows = [[Paragraph(header, styles['header_cell']) for header in headers]]
    for line in (estimate.input_snapshot or {}).get('lines', []):
        rows.append([
            Paragraph(_text(line.get('sku')), styles['cell']),
            Paragraph(_text(line.get('quantity')), styles['cell_right']),
            Paragraph(_text(line.get('freight_type')), styles['cell']),
            Paragraph(_text(line.get('length_m')), styles['cell_right']),
            Paragraph(_text(line.get('width_m')), styles['cell_right']),
            Paragraph(_text(line.get('height_m')), styles['cell_right']),
            Paragraph(_text(line.get('weight_kg')), styles['cell_right']),
            Paragraph(_text(line.get('cubic_m3')), styles['cell_right']),
        ])
    if len(rows) == 1:
        rows.append([Paragraph('-', styles['cell'])] + [''] * 7)

    widths = [39, 13, 16, 17, 17, 17, 23, 20]
    table = Table(rows, colWidths=[value * mm for value in widths], repeatRows=1)
    table.setStyle(_grid_table_style())
    return table


def _options_table(estimate, styles):
    headers = ['Carrier', 'Service', 'Estimate ex GST', 'Status']
    rows = [[Paragraph(header, styles['header_cell']) for header in headers]]
    for result in estimate.result_snapshot or []:
        rows.append([
            Paragraph(_text(result.get('carrier')), styles['cell']),
            Paragraph(_text(result.get('service')), styles['cell']),
            Paragraph(_money(result.get('estimate_ex_gst')), styles['cell_right']),
            Paragraph(_text(result.get('status')), styles['cell']),
        ])
    if len(rows) == 1:
        rows.append([Paragraph('-', styles['cell']), '', '', ''])

    table = Table(rows, colWidths=[45 * mm, 45 * mm, 42 * mm, 30 * mm], repeatRows=1)
    table.setStyle(_grid_table_style())
    return table


def _body_table_style():
    return TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f2f6fb')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ])


def _grid_table_style():
    return TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f2f6fb')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f1')),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])


def _text(value):
    if value is None or value == '':
        return '-'
    return str(value)


def _with_unit(value, unit):
    if value is None or value == '':
        return '-'
    return f'{value} {unit}'


def _money(value):
    if value is None or value == '':
        return '-'
    try:
        return f'${float(value):,.2f}'
    except (TypeError, ValueError):
        return f'${value}'
