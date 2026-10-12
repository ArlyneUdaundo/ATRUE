"""The seat map a flight renders, resolved from the database.

Seat layouts used to be a hard-coded dict keyed by a short code that ``Airline``,
``Aircraft`` and ``Flight`` each stored in a ``seat_layout`` CharField, so the
aircraft dropdown could offer anything and a manager had to pick a map by hand
every time a flight was created.  The chain is now real rows:

    Airline ─┬─ AirlineFleet ─ AircraftType ─┐
             │                               ├─ SeatLayout ─ Cabin ─ Seat
             └─ Aircraft ─────────────────── ┘
                                            ↑
                                         Flight

``resolve_layout`` walks that chain — the aircraft flying the flight, else the
airline's default type — and ``build_seat_map`` turns the ``Seat`` rows it lands
on into the structure ``book.html`` renders.  Nothing here knows an airline by
name, so adding a twenty-first carrier or re-configuring an A350 for a new
operator is a database change, not a code change.
"""

from airlines.fleet_data import (
    CABIN_FARE_FIELDS,
    CABIN_LABELS,
    ECONOMY,
    FARE_CLASSES,
    NOSE_TAPER,
    SEAT_LETTERS,
    TAIL_TAPER,
    seat_position,
)

__all__ = [
    'CABIN_FARE_FIELDS',
    'CABIN_LABELS',
    'FARE_CLASSES',
    'SEAT_LETTERS',
    'build_seat_map',
    'cabin_fare_field',
    'capacity_for',
    'empty_layout',
    'layout_for',
    'resolve_layout',
    'seat_map_label',
    'seat_position',
]


def cabin_fare_field(cabin_key):
    return CABIN_FARE_FIELDS.get(cabin_key, 'economy_fare')


def seat_map_label(cabins):
    """The cabin blocks of a resolved layout, e.g. ``1-2-1 / 2-2-2 / 3-3``."""
    return ' / '.join('-'.join(str(b) for b in cabin['blocks']) for cabin in cabins)


def empty_layout():
    """The map for a flight whose airline has no fleet configured yet.

    Returning an empty cabin list rather than inventing seats keeps the booking
    page honest: a flight with nowhere to sit is not bookable, and the manager
    sees exactly that on the flight form.
    """
    return {
        'id': None,
        'name': 'No seat layout configured',
        'airline': '',
        'aircraft': '',
        'aircraft_type': '',
        'seat_map': '',
        'total_seats': 0,
        'exits': (),
        'lavatories': (),
        'galleys': (),
        'cabins': [],
    }


def resolve_layout(flight):
    """The ``SeatLayout`` a flight sells seats from, or ``None``.

    Most specific first: the aircraft actually flying it, then the airline's
    default type, then the airline's first active fleet type.  A flight with no
    aircraft assigned still books — it just falls back to the airline's fleet,
    which is why the airline is the anchor of the whole chain.
    """
    from airlines.models import SeatLayout

    if flight is None:
        return None

    aircraft = getattr(flight, 'aircraft', None)
    if aircraft is not None and aircraft.seat_layout_id:
        return aircraft.seat_layout

    airline = getattr(flight, 'airline', None)
    if airline is None:
        return None

    if airline.default_aircraft_type_id:
        fallback = SeatLayout.objects.filter(
            airline=airline, aircraft_type_id=airline.default_aircraft_type_id).first()
        if fallback is not None:
            return fallback

    fleet_type = (airline.fleet_entries.filter(is_active=True)
                  .select_related('aircraft_type')
                  .order_by('-is_primary', 'aircraft_type__model_name')
                  .first())
    if fleet_type is None:
        return None
    return SeatLayout.objects.filter(
        airline=airline, aircraft_type=fleet_type.aircraft_type).first()


def _cabins(layout):
    """The layout's cabins, in airmail order, as plain dicts.

    A one-off fetch rather than a query per cabin — the booking page reads every
    cabin and every seat of the layout exactly once.
    """
    return [
        {
            'id': cabin.pk,
            'key': cabin.fare_class,
            'label': CABIN_LABELS.get(cabin.fare_class, cabin.get_fare_class_display()),
            'fare_field': cabin_fare_field(cabin.fare_class),
            'blocks': list(cabin.blocks or ()),
            'rows': cabin.rows,
            'seat_count': cabin.seat_count,
        }
        for cabin in layout.cabins.all()
    ]


def layout_for(flight):
    """The resolved layout as a dict, whatever the flight points at."""
    from airlines.models import SeatLayout  # noqa: F401  (documents the source table)

    layout = resolve_layout(flight)
    if layout is None:
        return empty_layout()

    aircraft = getattr(flight, 'aircraft', None)
    return {
        'id': layout.pk,
        'name': layout.name or layout.label,
        'airline': layout.airline.name,
        'aircraft': layout.aircraft_type.label,
        'aircraft_type': layout.aircraft_type.model_name,
        'seat_map': layout.seat_map,
        'total_seats': layout.total_capacity,
        'exits': tuple(layout.exit_rows or ()),
        'lavatories': tuple(layout.lavatory_rows or ()),
        'galleys': tuple(layout.galley_positions or ()),
        'tail_number': aircraft.tail_number if aircraft is not None else '',
        'cabins': _cabins(layout),
    }


def capacity_for(flight):
    """Sellable seats on a flight: the sum of its resolved layout's cabins."""
    if flight is None:
        return 0
    layout = resolve_layout(flight)
    return layout.total_capacity if layout is not None else 0


def _taper(row_no, total_rows):
    """Inset in px for the nose and tail of the fuselage."""
    if row_no <= len(NOSE_TAPER):
        return NOSE_TAPER[row_no - 1]
    from_end = total_rows - row_no
    if from_end < len(TAIL_TAPER):
        return TAIL_TAPER[from_end]
    return 0


def build_seat_map(flight, taken=()):
    """Turn a flight's layout into the structure ``book.html`` renders.

    ``taken`` is the set of seat numbers already assigned on the flight
    (BR-043).  Returns the fuselage plus one entry per cabin, in airmail order
    from the nose, with rows numbered globally like a real boarding pass.

    Seat positions come from the ``Seat`` rows themselves, so the map always
    matches what the database says the aircraft is fitted out with.
    """
    layout = layout_for(flight)
    taken = set(taken or ())
    if not layout['cabins']:
        return {
            'key': '',
            'name': layout['name'],
            'airline': layout['airline'],
            'aircraft': layout['aircraft'],
            'tail_number': layout['tail_number'],
            'seat_map': '',
            'total_seats': 0,
            'cabins': [],
        }

    # One query for the whole layout, grouped by cabin, rather than one per row.
    seats_by_cabin = {}
    for seat in _layout_seats(layout['id']):
        seats_by_cabin.setdefault(seat['cabin_id'], {}) \
            .setdefault(seat['row_number'], []).append(seat)

    total_rows = sum(cabin['rows'] for cabin in layout['cabins'])
    row_no = 0
    cabins = []

    for cabin in layout['cabins']:
        rows = []
        cabin_seats = seats_by_cabin.get(cabin['id'], {})
        for _ in range(cabin['rows']):
            row_no += 1
            row_seats = cabin_seats.get(row_no, [])
            blocks = []
            seat_at = 0
            for block_no, block_width in enumerate(cabin['blocks']):
                cols = []
                for _ in range(block_width):
                    seat = row_seats[seat_at] if seat_at < len(row_seats) else None
                    if seat is None:
                        # The map and the Seat table are written together, so this
                        # only happens if a cabin's blocks were edited without its
                        # seats being regenerated.  Render the tile as unavailable
                        # rather than inventing a seat number nobody can book.
                        cols.append({
                            'seat': '', 'label': '', 'taken': True,
                            'position': 'aisle', 'block': block_no,
                        })
                    else:
                        cols.append({
                            'seat': seat['seat_number'],
                            'label': seat['letter'],
                            'taken': seat['seat_number'] in taken,
                            'position': seat['position'],
                            'block': block_no,
                        })
                    seat_at += 1
                blocks.append({'width': block_width, 'cols': cols})
            rows.append({
                'row': row_no,
                'blocks': blocks,
                'is_exit': row_no in layout['exits'],
                'taper': _taper(row_no, total_rows),
                'after': ('lavatory' if row_no in layout['lavatories'] else None),
            })
        if layout['galleys'] and 'front' in layout['galleys'] and not cabins and rows:
            rows[0]['before'] = 'galley'
        cabins.append({
            'key': cabin['key'],
            'label': cabin['label'],
            'fare_field': cabin['fare_field'],
            # What this cabin actually sells for on this flight, so the cabin
            # heading can name the price instead of leaving it blank.
            'fare': flight.fare_for(cabin['key']),
            'seat_count': cabin['seat_count'],
            # The column headings for this cabin: the seat letters of its first
            # row, grouped by the same seat blocks the rows below use.  Taken
            # from the Seat table rather than counted, so a 3-4-3 really does
            # head its columns A B C | D E F G | H J K.  The header row and the
            # data rows are then built from the same blocks, which is what keeps
            # the letters lined up over their own seats.
            'head_blocks': [
                {'width': block['width'],
                 'labels': [col['label'] for col in block['cols']]}
                for block in (rows[0]['blocks'] if rows else [])
            ],
            'rows': rows,
        })

    if layout['galleys'] and 'aft' in layout['galleys'] and cabins:
        cabins[-1]['rows'][-1]['after'] = 'galley'

    return {
        'key': layout['name'],
        'name': layout['name'],
        'airline': layout['airline'],
        'aircraft': layout['aircraft'],
        # Which airframe is actually flying this leg, so a round trip's two tabs
        # show two different aircraft rather than looking like the same cabin.
        'tail_number': layout['tail_number'],
        'seat_map': layout['seat_map'],
        'total_seats': sum(c['seat_count'] for c in cabins),
        'cabins': cabins,
    }


def _layout_seats(layout_id):
    from airlines.models import Seat

    return Seat.objects.filter(seat_layout_id=layout_id).values(
        'cabin_id', 'row_number', 'letter', 'seat_number', 'position')
