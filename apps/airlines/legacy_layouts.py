"""FROZEN COPY — the seat-layout presets this app used before 0024.

Seat layouts were a hard-coded dict keyed by a short code that ``Airline``,
``Aircraft`` and ``Flight`` each stored in a ``seat_layout`` CharField, so an
aircraft type was not owned by any airline and a flight's cabin had to be picked
by hand from a list of 20-something presets.  0024 replaced all of that with real
tables (``AircraftType``, ``AirlineFleet``, ``SeatLayout``, ``Cabin``, ``Seat``)
and this app's ``layouts`` module became a database-backed engine.

Migrations 0021, 0022 and 0023 still need the preset dict and ``layout_seat_count``
to replay correctly on a fresh database, so they import them from here.  Nothing
in the running app uses this module — do not add new presets here.  New fleet
data goes in ``fleet_data.py`` and new cabin data goes in the database.

Each preset is a representative configuration for the aircraft type named in
``aircraft``; they are not transcribed from published seat maps, and the seat
total shown to a manager is always ``rows * seats-per-row`` of the preset
itself.  Presets are pure data — the engine below turns one into the structure
``book.html`` renders.

Spec fields
-----------
``cabins``      Ordered ``{key, label, blocks, rows}``.  ``blocks`` is the
                seats-per-row of each seat block separated by an aisle
                (``[3, 3]`` = 3-3, ``[1, 2, 1]`` = 1-2-1, ``[3, 4, 3]`` =
                the A380's main deck).  ``rows`` is how many rows the cabin
                has, so a cabin's seat count is ``rows * sum(blocks)``.
``exits``       Global row numbers that are emergency exit rows.
``lavatories``  Global row numbers a lavatory sits directly behind.
``galleys``     ``'front'`` / ``'aft'`` — kitchen units at the cabin ends.
"""

# Airlines skip 'I' and 'O' in seat letters so they cannot be confused with 1/0.
SEAT_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'

# How far each row is inset from the full cabin width, in px, so the first and
# last rows read as the tapering nose and tail cone of the fuselage.
_NOSE_TAPER = (0, 10, 22)
_TAIL_TAPER = (12, 0)

FIRST_CLASS = 'FIRST_CLASS'
BUSINESS = 'BUSINESS'
PREMIUM_ECONOMY = 'PREMIUM_ECONOMY'
ECONOMY = 'ECONOMY'

CABIN_LABELS = {
    FIRST_CLASS: 'First Class',
    BUSINESS: 'Business Class',
    PREMIUM_ECONOMY: 'Premium Economy',
    ECONOMY: 'Economy',
}

# Which Flight fare field pays for each cabin.
CABIN_FARE_FIELDS = {
    FIRST_CLASS: 'first_class_fare',
    BUSINESS: 'business_fare',
    PREMIUM_ECONOMY: 'premium_economy_fare',
    ECONOMY: 'economy_fare',
}

FARE_CLASSES = [FIRST_CLASS, BUSINESS, PREMIUM_ECONOMY, ECONOMY]


def _cabin(key, blocks, rows):
    return {'key': key, 'label': CABIN_LABELS[key], 'blocks': blocks, 'rows': rows}


def _layout(airline, aircraft, seat_map, cabins, exits=(), lavatories=(), galleys=()):
    return {
        'airline': airline,
        'aircraft': aircraft,
        'seat_map': seat_map,
        'cabins': cabins,
        'exits': tuple(exits),
        'lavatories': tuple(lavatories),
        'galleys': tuple(galleys),
    }


# Representative seat configurations.  Seat totals follow rows x seats-per-row,
# so the number in the label is always what the booking page renders.
SEAT_LAYOUTS = {
    'GENERIC_NARROW': _layout(
        'Generic narrowbody', 'Airbus A320', '3-3',
        [_cabin(ECONOMY, [3, 3], 30)], galleys=('front', 'aft')),
    'GENERIC_WIDE': _layout(
        'Generic widebody', 'Boeing 777-200', '3-3-3',
        [_cabin(ECONOMY, [3, 3, 3], 30)], galleys=('front', 'aft')),

    'PAL_A330': _layout(
        'Philippine Airlines', 'Airbus A330-300', '1-2-1 / 2-2-2 / 3-3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 8), _cabin(BUSINESS, [2, 2, 2], 10),
         _cabin(ECONOMY, [3, 3, 3], 28)],
        exits=(21, 39), lavatories=(19, 38), galleys=('front', 'aft')),
    'CEBU_A320': _layout(
        'Cebu Pacific', 'Airbus A320neo', '3-3',
        [_cabin(ECONOMY, [3, 3], 30)], galleys=('front', 'aft')),
    'AIRASIA_A320': _layout(
        'Philippines AirAsia', 'Airbus A320', '3-3',
        [_cabin(ECONOMY, [3, 3], 30)], galleys=('front', 'aft')),
    'A321NEO_3_3': _layout(
        'Generic single-aisle', 'Airbus A321neo', '3-3',
        [_cabin(ECONOMY, [3, 3], 40)], galleys=('front', 'aft')),
    'ATR72_600_2_2': _layout(
        'Generic turboprop', 'ATR 72-600', '2-2',
        [_cabin(ECONOMY, [2, 2], 19)], galleys=('front', 'aft')),
    'DASH8_400_2_2': _layout(
        'Generic turboprop', 'De Havilland Dash 8-400', '2-2',
        [_cabin(ECONOMY, [2, 2], 19)], galleys=('front', 'aft')),
    'A350_900_1_2_1': _layout(
        'Generic widebody', 'Airbus A350-900', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 3), _cabin(BUSINESS, [2, 2, 2], 8),
         _cabin(ECONOMY, [3, 3], 39)],
        exits=(14, 38), lavatories=(12, 37), galleys=('front', 'aft')),
    'PAL_A350': _layout(
        'Philippine Airlines', 'Airbus A350-900', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 8),
         _cabin(ECONOMY, [3, 3], 40)],
        exits=(15, 40), lavatories=(13, 39), galleys=('front', 'aft')),
    'SIA_A350': _layout(
        'Singapore Airlines', 'Airbus A350-900', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 3), _cabin(BUSINESS, [2, 2, 2], 8),
         _cabin(ECONOMY, [3, 3], 52)],
        exits=(14, 38), lavatories=(12, 37), galleys=('front', 'aft')),
    'CATHAY_A350': _layout(
        'Cathay Pacific', 'Airbus A350-900', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 6),
         _cabin(ECONOMY, [3, 3], 43)],
        exits=(13, 31), lavatories=(11, 30), galleys=('front', 'aft')),
    'JAL_787': _layout(
        'Japan Airlines', 'Boeing 787-9', '1-2-1 / 2-2-2 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 10),
         _cabin(PREMIUM_ECONOMY, [2, 2, 2], 8), _cabin(ECONOMY, [3, 3], 22)],
        exits=(20, 40), lavatories=(18, 39), galleys=('front', 'aft')),
    'ANA_777': _layout(
        'All Nippon Airways', 'Boeing 777-300ER', '1-2-1 / 2-2-2 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 13),
         _cabin(PREMIUM_ECONOMY, [2, 2, 2], 20), _cabin(ECONOMY, [3, 3], 35)],
        exits=(22, 56), lavatories=(20, 55), galleys=('front', 'aft')),
    'KOREAN_787': _layout(
        'Korean Air', 'Boeing 787-10', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 12),
         _cabin(ECONOMY, [3, 3], 40)],
        exits=(22, 47), lavatories=(20, 46), galleys=('front', 'aft')),
    'MALAYSIA_A350': _layout(
        'Malaysia Airlines', 'Airbus A350-900', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 6),
         _cabin(ECONOMY, [3, 3], 50)],
        exits=(14, 39), lavatories=(12, 38), galleys=('front', 'aft')),
    'THAI_787': _layout(
        'Thai Airways', 'Boeing 787-9', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 10),
         _cabin(ECONOMY, [3, 3], 46)],
        exits=(20, 49), lavatories=(18, 48), galleys=('front', 'aft')),
    'VIETNAM_787': _layout(
        'Vietnam Airlines', 'Boeing 787-10', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 10),
         _cabin(ECONOMY, [3, 3], 48)],
        exits=(21, 50), lavatories=(19, 49), galleys=('front', 'aft')),
    'EMIRATES_A380': _layout(
        'Emirates', 'Airbus A380-800', '1-2-1 / 1-2-1 / 3-4-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 3), _cabin(BUSINESS, [1, 2, 1], 19),
         _cabin(ECONOMY, [3, 4, 3], 36)],
        exits=(35, 57), lavatories=(24, 58), galleys=('front', 'aft')),
    'QATAR_A350': _layout(
        'Qatar Airways', 'Airbus A350-1000', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 3), _cabin(BUSINESS, [2, 2, 2], 11),
         _cabin(ECONOMY, [3, 3], 47)],
        exits=(18, 48), lavatories=(16, 47), galleys=('front', 'aft')),
    'ETIHAD_787': _layout(
        'Etihad Airways', 'Boeing 787-9', '1-2-1 / 2-2-2 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 7),
         _cabin(PREMIUM_ECONOMY, [2, 2, 2], 10), _cabin(ECONOMY, [3, 3], 33)],
        exits=(23, 43), lavatories=(21, 42), galleys=('front', 'aft')),
    'SAUDIA_777': _layout(
        'Saudia', 'Boeing 777-300ER', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 19),
         _cabin(ECONOMY, [3, 3], 31)],
        exits=(27, 50), lavatories=(25, 49), galleys=('front', 'aft')),
    'UNITED_777': _layout(
        'United Airlines', 'Boeing 777-200ER', '1-2-1 / 2-2-2 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 10),
         _cabin(PREMIUM_ECONOMY, [2, 2, 2], 12), _cabin(ECONOMY, [3, 3], 29)],
        exits=(20, 48), lavatories=(18, 47), galleys=('front', 'aft')),
    'DELTA_A350': _layout(
        'Delta Air Lines', 'Airbus A350-900', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 8), _cabin(BUSINESS, [2, 2, 2], 7),
         _cabin(ECONOMY, [3, 3], 31)],
        exits=(20, 43), lavatories=(18, 42), galleys=('front', 'aft')),
    'AMERICAN_777': _layout(
        'American Airlines', 'Boeing 777-300ER', '1-2-1 / 2-2-2 / 2-4-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 12),
         _cabin(PREMIUM_ECONOMY, [2, 4, 2], 6), _cabin(ECONOMY, [3, 3], 45)],
        exits=(24, 57), lavatories=(22, 56), galleys=('front', 'aft')),
    'TURKISH_777': _layout(
        'Turkish Airlines', 'Boeing 777-300ER', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 14),
         _cabin(ECONOMY, [3, 3], 48)],
        exits=(23, 54), lavatories=(21, 53), galleys=('front', 'aft')),
    'AIRFRANCE_777': _layout(
        'Air France', 'Boeing 777-300ER', '1-2-1 / 2-2-2 / 3-3',
        [_cabin(FIRST_CLASS, [1, 2, 1], 4), _cabin(BUSINESS, [2, 2, 2], 10),
         _cabin(ECONOMY, [3, 3], 40)],
        exits=(19, 47), lavatories=(17, 46), galleys=('front', 'aft')),
}

DEFAULT_LAYOUT = 'GENERIC_NARROW'


def layout_seat_count(key):
    """Total sellable seats in a layout."""
    layout = SEAT_LAYOUTS.get(key) or SEAT_LAYOUTS[DEFAULT_LAYOUT]
    return sum(c['rows'] * sum(c['blocks']) for c in layout['cabins'])


def cabin_fare_field(cabin_key):
    return CABIN_FARE_FIELDS.get(cabin_key, 'economy_fare')


SEAT_LAYOUT_CHOICES = [
    (key, '%s — %s (%s, %d seats)' % (
        layout['airline'], layout['aircraft'], layout['seat_map'],
        layout_seat_count(key)))
    for key, layout in SEAT_LAYOUTS.items()
]


def layout_choices():
    return list(SEAT_LAYOUT_CHOICES)


def layout_for(flight):
    """The layout a flight renders: its own override, else its airline's."""
    return SEAT_LAYOUTS[layout_key_for(flight)]


def layout_key_for(flight):
    """The preset key a flight renders.

    Most specific wins: the flight's own override, then the cabin of the
    aircraft actually flying it, then the airline's default.  A flight with no
    aircraft assigned still books — it just falls back to the airline.
    """
    for source in (flight, getattr(flight, 'aircraft', None), getattr(flight, 'airline', None)):
        key = (getattr(source, 'seat_layout', '') or '').strip()
        if key in SEAT_LAYOUTS:
            return key
    return DEFAULT_LAYOUT


def capacity_for(flight):
    return layout_seat_count(layout_key_for(flight))


def _taper(row_no, total_rows):
    """Inset in px for the nose and tail of the fuselage."""
    if row_no <= len(_NOSE_TAPER):
        return _NOSE_TAPER[row_no - 1]
    from_end = total_rows - row_no
    if from_end < len(_TAIL_TAPER):
        return _TAIL_TAPER[from_end]
    return 0


def build_seat_map(flight, taken=()):
    """Turn a flight's layout into the structure ``book.html`` renders.

    ``taken`` is the set of seat numbers already assigned on the flight
    (BR-043).  Returns the fuselage plus one entry per cabin, in airmail order
    from the nose, with rows numbered globally like a real boarding pass.
    """
    layout = layout_for(flight)
    taken = set(taken or ())
    total_rows = sum(c['rows'] for c in layout['cabins'])
    row_no = 0
    cabins = []

    for cabin in layout['cabins']:
        rows = []
        for _ in range(cabin['rows']):
            row_no += 1
            blocks = []
            letter_at = 0
            for block_no, block_width in enumerate(cabin['blocks']):
                cols = []
                for seat_at in range(block_width):
                    letter = SEAT_LETTERS[letter_at]
                    seat = '%d%s' % (row_no, letter)
                    cols.append({
                        'seat': seat,
                        'label': letter,
                        'taken': seat in taken,
                        'position': _position(block_width, seat_at),
                        'block': block_no,
                    })
                    letter_at += 1
                blocks.append({'width': block_width, 'cols': cols})
            rows.append({
                'row': row_no,
                'blocks': blocks,
                'is_exit': row_no in layout['exits'],
                'taper': _taper(row_no, total_rows),
                'after': ('lavatory' if row_no in layout['lavatories'] else None),
            })
        if layout['galleys'] and 'front' in layout['galleys'] and not cabins:
            rows[0]['before'] = 'galley'
        cabins.append({
            'key': cabin['key'],
            'label': cabin['label'],
            'fare_field': cabin_fare_field(cabin['key']),
            'seat_count': cabin['rows'] * sum(cabin['blocks']),
            'rows': rows,
        })

    if layout['galleys'] and 'aft' in layout['galleys'] and cabins:
        cabins[-1]['rows'][-1]['after'] = 'galley'

    return {
        'key': layout_key_for(flight),
        'airline': layout['airline'],
        'aircraft': layout['aircraft'],
        'seat_map': layout['seat_map'],
        'total_seats': total_rows and sum(c['seat_count'] for c in cabins),
        'cabins': cabins,
    }


def _position(block_width, seat_at):
    """Window / middle / aisle, mirroring how a seat is described on a boarding pass.

    Judged inside its own block, so in a 1-2-1 the pair is two aisle seats and a
    3-4-3 centre block has windows at both ends and a middle seat in between.
    """
    if seat_at == 0:
        return 'window'
    if seat_at == block_width - 1:
        return 'aisle'
    return 'middle'
