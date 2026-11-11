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
