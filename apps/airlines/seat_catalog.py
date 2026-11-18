"""The default seat-type catalogue and helpers for applying it to a layout."""

from decimal import Decimal

DEFAULT_SEAT_TYPES = (
    {
        'code': 'standard', 'name': 'Standard Seat',
        'description': 'A regular seat in the selected cabin.',
        'default_price': Decimal('0.00'), 'color': '#ffffff',
    },
    {
        'code': 'window', 'name': 'Window Seat',
        'description': 'A seat beside the cabin window.',
        'default_price': Decimal('0.00'), 'color': '#dbeafe',
    },
    {
        'code': 'aisle', 'name': 'Aisle Seat',
        'description': 'A seat beside the aisle.',
        'default_price': Decimal('0.00'), 'color': '#bfdbfe',
    },
    {
        'code': 'extra_legroom', 'name': 'Extra Legroom',
        'description': 'A seat with additional legroom.',
        'default_price': Decimal('500.00'), 'color': '#dcfce7',
    },
    {
        'code': 'front_row', 'name': 'Front Row',
        'description': 'A seat in the first row of a cabin.',
        'default_price': Decimal('750.00'), 'color': '#fef3c7',
    },
    {
        'code': 'exit_row', 'name': 'Emergency Exit Row',
        'description': 'A seat beside an emergency exit.',
        'default_price': Decimal('500.00'), 'color': '#fee2e2',
    },
)


def ensure_seat_types():
    """Create any missing catalogue rows and return them keyed by code."""
    from airlines.models import SeatType

    result = {}
    for spec in DEFAULT_SEAT_TYPES:
        seat_type, _ = SeatType.objects.get_or_create(
            code=spec['code'],
            defaults={
                'name': spec['name'],
                'description': spec['description'],
                'default_price': spec['default_price'],
                'color': spec['color'],
            },
        )
        result[seat_type.code] = seat_type
    return result


def apply_default_seat_types(layout):
    """Give every untyped seat a sensible type based on its position."""
    from airlines.models import Seat

    seat_types = ensure_seat_types()
    untyped = Seat.objects.filter(seat_layout=layout, seat_type__isnull=True)
    untyped.filter(position='window').update(seat_type=seat_types['window'])
    untyped.filter(position='aisle').update(seat_type=seat_types['aisle'])
    untyped.filter(position='middle').update(seat_type=seat_types['standard'])


def apply_configured_seat_row_types(layout):
    """Apply configured row features while retaining each seat's position.

    ``Seat.position`` continues to identify window, middle, or aisle. The
    priced ``Seat.seat_type`` records a special row feature when one applies.
    Emergency exit rows are read only from the layout's aircraft configuration.
    """
    from airlines.models import Seat

    cabins = list(layout.cabins.all())
    if (layout.seat_map != '3-3' or len(cabins) != 1
            or cabins[0].blocks != [3, 3] or cabins[0].rows < 11):
        return 0

    seat_types = ensure_seat_types()
    configured_exits = set()
    for row in layout.exit_rows or ():
        try:
            configured_exits.add(int(row))
        except (TypeError, ValueError):
            continue

    special_rows = {1: 'front_row', 4: 'extra_legroom'}
    for row in configured_exits:
        if row not in special_rows:
            special_rows[row] = 'exit_row'

    position_types = {
        'window': 'window', 'middle': 'standard', 'aisle': 'aisle',
    }
    updates = []
    seats = (Seat.objects.filter(seat_layout=layout)
             .select_related('seat_type').order_by('row_number', 'letter'))
    for seat in seats:
        base_code = position_types.get(seat.position, 'standard')
        current_code = seat.seat_type.code if seat.seat_type_id else None
        desired_code = special_rows.get(seat.row_number, base_code)
        if current_code not in (None, base_code) or current_code == desired_code:
            continue
        seat.seat_type = seat_types[desired_code]
        updates.append(seat)

    if updates:
        Seat.objects.bulk_update(updates, ['seat_type'], batch_size=500)
    return len(updates)


def seat_types_in_layout(layout):
    """The distinct seat types actually used by a layout, with their price."""
    from airlines.models import Seat

    if layout is None:
        return []
    rows = (Seat.objects.filter(seat_layout=layout, seat_type__isnull=False)
            .values('seat_type__id', 'seat_type__code', 'seat_type__name',
                    'seat_type__default_price', 'seat_type__color',
                    'seat_type__is_active')
            .distinct())
    types = {}
    for row in rows:
        code = row['seat_type__code']
        types[code] = {
            'key': code,
            'label': row['seat_type__name'],
            'price': row['seat_type__default_price'] or Decimal('0.00'),
            'color': row['seat_type__color'],
            'is_active': row['seat_type__is_active'],
        }
    return sorted(types.values(), key=lambda item: item['label'])


def seat_quote(seat):
    """The seat's configured type and fee, with a safe standard fallback."""
    if seat is None:
        return {'code': 'standard', 'label': 'Standard seat', 'price': Decimal('0.00')}
    if seat.seat_type_id:
        code = seat.seat_type.code
        label = seat.seat_type.name
    else:
        code = 'standard'
        label = 'Standard seat'
    return {'code': code, 'label': label, 'price': seat.price}
