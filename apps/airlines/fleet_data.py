"""The aircraft brands, types and per-airline fleets ATRUE starts with.

Every airline owns a fleet, a fleet is a set of ``AircraftType`` rows, and each
``(airline, aircraft_type)`` pair has its own ``SeatLayout``.  Nothing here is
read at request time: 0024 loads this into real tables and the app then works
purely off the database, so a manager can add, edit or remove a type, an
aircraft or a cabin long after the seed has run.

Shape
-----
``MANUFACTURERS``  brand -> ``(name, country)``.  "Aircraft brands": Airbus, Boeing.
``AIRCRAFT_TYPES``  type code -> ``(brand, model, body class, typical capacity)``.
``CABIN_SPECS``     spec key -> ordered ``(fare class, seat blocks, rows)``.
``FLEETS``          airline name -> ``{type code: cabin spec key}``, in airmail
                    order.  The first entry is the airline's default type, used
                    when a flight is scheduled before an aircraft is chosen.
``SEED_AIRCRAFT``   airline name -> a couple of real tail numbers, so every
                    airline has an aircraft to show on day one.

``derive_markers`` / ``seat_map_label`` / ``iter_seats`` turn a cabin spec into
the rows the seeder writes, so a new fleet entry only needs one line here.

A cabin spec is ``(fare class, blocks, rows)`` where ``blocks`` is the seats per
row split by an aisle — ``(3, 3)`` is 3-3, ``(1, 2, 1)`` is 1-2-1, ``(3, 4, 3)``
is the A380 main deck — and ``rows`` is how many rows that cabin has, so the
cabin's seat count is always ``rows * sum(blocks)``.  Row numbers run globally
from the nose, the way a boarding pass numbers them.
"""

# Airlines skip 'I' and 'O' in seat letters so they cannot be confused with 1/0.
SEAT_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'

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

BODY_CLASSES = [
    ('NARROW_BODY', 'Narrow-Body'),
    ('WIDE_BODY', 'Wide-Body'),
    ('REGIONAL', 'Regional'),
    ('TURBOPROP', 'Turboprop'),
    ('PRIVATE_JET', 'Private Jet'),
    ('OTHER', 'Other'),
]

# How far each row is inset from the full cabin width, in px, so the first and
# last rows read as the tapering nose and tail cone of the fuselage.
NOSE_TAPER = (0, 10, 22)
TAIL_TAPER = (12, 0)


# --------------------------------------------------------------------------
# Brands
# --------------------------------------------------------------------------

MANUFACTURERS = {
    'AIRBUS': ('Airbus', 'France'),
    'BOEING': ('Boeing', 'United States'),
    'ATR': ('ATR', 'France'),
    'DEHAVILLAND': ('De Havilland Canada', 'Canada'),
    'EMBRAER': ('Embraer', 'Brazil'),
}


# --------------------------------------------------------------------------
# Aircraft types:  code -> (brand, model name, body class, typical seats)
# --------------------------------------------------------------------------

AIRCRAFT_TYPES = {
    'A320': ('AIRBUS', 'A320', 'NARROW_BODY', 180),
    'A320N': ('AIRBUS', 'A320neo', 'NARROW_BODY', 194),
    'A321': ('AIRBUS', 'A321', 'NARROW_BODY', 220),
    'A321N': ('AIRBUS', 'A321neo', 'NARROW_BODY', 236),
    'A330-300': ('AIRBUS', 'A330-300', 'WIDE_BODY', 290),
    'A350-900': ('AIRBUS', 'A350-900', 'WIDE_BODY', 310),
    'A350-1000': ('AIRBUS', 'A350-1000', 'WIDE_BODY', 350),
    'A380-800': ('AIRBUS', 'A380-800', 'WIDE_BODY', 500),
    'B737-800': ('BOEING', '737-800', 'NARROW_BODY', 189),
    'B737-900ER': ('BOEING', '737-900ER', 'NARROW_BODY', 220),
    'B767-300ER': ('BOEING', '767-300ER', 'WIDE_BODY', 260),
    'B777-200ER': ('BOEING', '777-200ER', 'WIDE_BODY', 365),
    'B777-300ER': ('BOEING', '777-300ER', 'WIDE_BODY', 425),
    'B787-9': ('BOEING', '787-9', 'WIDE_BODY', 290),
    'B787-10': ('BOEING', '787-10', 'WIDE_BODY', 330),
    'ATR72-600': ('ATR', '72-600', 'TURBOPROP', 78),
    'DH8-400': ('DEHAVILLAND', 'Dash 8-400', 'TURBOPROP', 76),
    'E190': ('EMBRAER', 'E190-100', 'REGIONAL', 100),
}

# Free-text model names on pre-existing aircraft records, matched longest needle
# first so 'a321neo' wins over 'a321'.  Keyed by AircraftType code.
TYPE_MATCHERS = {
    'A321N': ('a321neo', 'a321neo'),
    'A320N': ('a320neo', 'a320neo'),
    'A321': ('a321', 'a321'),
    'A320': ('a320', 'a320'),
    'A330-300': ('a330300', 'a330-300', 'a330'),
    'A350-1000': ('a3501000', 'a350-1000'),
    'A350-900': ('a350900', 'a350-900', 'a350'),
    'A380-800': ('a380800', 'a380-800', 'a380'),
    'B737-900ER': ('b737900er', '737-900er'),
    'B737-800': ('b737800', '737-800', 'b737', '737'),
    'B767-300ER': ('b767300er', '767-300er', 'b767', '767'),
    'B777-200ER': ('b777200er', '777-200er'),
    'B777-300ER': ('b777300er', '777-300er', 'b777', '777'),
    'B787-10': ('b78710', '787-10'),
    'B787-9': ('b7879', '787-9', 'b787', '787'),
    'ATR72-600': ('atr72600', 'atr72', 'atr 72', 'atr'),
    'DH8-400': ('dh8400', 'dash8400', 'dash 8', 'dash8'),
    'E190': ('e190',),
}


# --------------------------------------------------------------------------
# Cabin configurations
# --------------------------------------------------------------------------

CABIN_SPECS = {
    # --- single-cabin narrowbodies and turboprops ------------------------
    'NARROW_180': [(ECONOMY, (3, 3), 30)],
    # 31 rows of 3-3 is 186 seats. A 737-800 is often listed at 189, but 189
    # is not a multiple of 6, so a pure 3-3 cabin cannot reach it — the key
    # states what the rows actually add up to.
    'NARROW_186': [(ECONOMY, (3, 3), 31)],
    'NARROW_198': [(ECONOMY, (3, 3), 33)],
    'NARROW_204': [(ECONOMY, (3, 3), 34)],
    'NARROW_216': [(ECONOMY, (3, 3), 36)],
    'NARROW_240': [(ECONOMY, (3, 3), 40)],
    'TURBOPROP_76': [(ECONOMY, (2, 2), 19)],

    # --- A330 family (1-2-1 first, 2-2-2 business, 3-3-3 economy) ---------
    'A330_290': [(FIRST_CLASS, (1, 2, 1), 5), (BUSINESS, (2, 2, 2), 12), (ECONOMY, (3, 3, 3), 22)],
    'A330_324': [(FIRST_CLASS, (1, 2, 1), 6), (BUSINESS, (2, 2, 2), 14), (ECONOMY, (3, 3, 3), 24)],

    # --- A350 family (1-2-1 / 2-2-2 / 3-3) -------------------------------
    'A350_294': [(FIRST_CLASS, (1, 2, 1), 3), (BUSINESS, (2, 2, 2), 8), (ECONOMY, (3, 3), 39)],
    'A350_310': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 9), (ECONOMY, (3, 3), 40)],
    'A350_334': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 11), (ECONOMY, (3, 3), 42)],
    'A350_366': [(FIRST_CLASS, (1, 2, 1), 3), (BUSINESS, (2, 2, 2), 12), (ECONOMY, (3, 3), 47)],

    # --- A380 (3-4-3 main deck) ------------------------------------------
    'A380_448': [(FIRST_CLASS, (1, 2, 1), 3), (BUSINESS, (1, 2, 1), 19), (ECONOMY, (3, 4, 3), 36)],
    'A380_306': [(FIRST_CLASS, (1, 2, 1), 6), (BUSINESS, (2, 2, 2), 12), (ECONOMY, (3, 3), 35)],

    # --- 777 family ------------------------------------------------------
    'B777_292': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 14), (ECONOMY, (3, 3), 32)],
    'B777_316': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 19), (ECONOMY, (3, 3), 31)],
    'B777_340': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 15), (PREMIUM_ECONOMY, (2, 2, 2), 9),
                 (ECONOMY, (3, 3), 30)],

    # --- 787 / 767 family ------------------------------------------------
    'B787_244': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 6), (PREMIUM_ECONOMY, (2, 2, 2), 6),
                 (ECONOMY, (3, 3), 26)],
    'B787_280': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 7), (PREMIUM_ECONOMY, (2, 2, 2), 9),
                 (ECONOMY, (3, 3), 28)],
    'B787_328': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 12), (ECONOMY, (3, 3), 40)],
    'B787_350': [(FIRST_CLASS, (1, 2, 1), 5), (BUSINESS, (2, 2, 2), 13), (ECONOMY, (3, 3), 42)],
    'B767_334': [(FIRST_CLASS, (1, 2, 1), 4), (BUSINESS, (2, 2, 2), 8), (ECONOMY, (3, 3, 3), 30)],
}


# --------------------------------------------------------------------------
# The twenty airlines ATRUE sells
# --------------------------------------------------------------------------

FLEETS = {
    'Philippine Airlines': {
        'A320': 'NARROW_180',
        'A321': 'NARROW_216',
        'A330-300': 'A330_324',
        'A350-900': 'A350_334',
        'B777-300ER': 'B777_340',
    },
    'Cebu Pacific': {
        'A320': 'NARROW_180',
        'A320N': 'NARROW_198',
        'A321N': 'NARROW_240',
        'A330-300': 'A330_290',
        'ATR72-600': 'TURBOPROP_76',
    },
    'Philippines AirAsia': {
        'A320': 'NARROW_180',
        'A320N': 'NARROW_198',
        'ATR72-600': 'TURBOPROP_76',
    },
    'Singapore Airlines': {
        'A350-900': 'A350_366',
        'A380-800': 'A380_306',
        'B777-300ER': 'B777_340',
        'B787-10': 'B787_350',
    },
    'Cathay Pacific': {
        'A321N': 'NARROW_240',
        'A330-300': 'A330_290',
        'A350-900': 'A350_310',
        'B777-300ER': 'B777_316',
    },
    'Japan Airlines': {
        'A350-900': 'A350_334',
        'B737-800': 'NARROW_186',
        'B787-9': 'B787_280',
    },
    'ANA': {
        'B787-9': 'B787_280',
        'B777-300ER': 'B777_340',
        'A380-800': 'A380_306',
    },
    'Korean Air': {
        'A321N': 'NARROW_240',
        'A330-300': 'A330_290',
        'B777-300ER': 'B777_340',
        'B787-10': 'B787_350',
    },
    'Malaysia Airlines': {
        'A350-900': 'A350_334',
        'B777-300ER': 'B777_316',
        'A330-300': 'A330_290',
    },
    'Thai Airways': {
        'B787-9': 'B787_280',
        'B777-300ER': 'B777_340',
        'A350-900': 'A350_334',
    },
    'Vietnam Airlines': {
        'B787-10': 'B787_350',
        'A350-900': 'A350_334',
        'A321N': 'NARROW_240',
    },
    'Emirates': {
        'A380-800': 'A380_448',
        'A350-900': 'A350_366',
        'B777-300ER': 'B777_340',
    },
    'Qatar Airways': {
        'A350-1000': 'A350_366',
        'A380-800': 'A380_448',
        'B777-300ER': 'B777_340',
    },
    'Etihad Airways': {
        'B787-9': 'B787_280',
        'A350-900': 'A350_334',
        'B777-300ER': 'B777_316',
    },
    'Saudia': {
        'B777-300ER': 'B777_340',
        'A320': 'NARROW_180',
        'B787-9': 'B787_280',
    },
    'United Airlines': {
        'B777-200ER': 'B777_292',
        'B737-800': 'NARROW_198',
        'B787-9': 'B787_280',
    },
    'Delta Air Lines': {
        'A350-900': 'A350_334',
        'B737-900ER': 'NARROW_240',
        'B767-300ER': 'B767_334',
    },
    'American Airlines': {
        'B777-300ER': 'B777_340',
        'B737-800': 'NARROW_198',
        'B787-9': 'B787_244',
    },
    'Turkish Airlines': {
        'B777-300ER': 'B777_340',
        'A321N': 'NARROW_240',
        'B737-800': 'NARROW_198',
    },
    'Air France': {
        'B777-300ER': 'B777_340',
        'A350-900': 'A350_334',
        'B737-800': 'NARROW_186',
    },
}

# A couple of real tail numbers per airline so every fleet has aircraft on day
# one.  Registrations follow the operator's real prefix.
SEED_AIRCRAFT = {
    'Philippine Airlines': [('A320', 'RP-C3201'), ('A330-300', 'RP-C3332')],
    'Cebu Pacific': [('A320N', 'RP-C3270'), ('A321N', 'RP-C4101')],
    'Philippines AirAsia': [('A320', 'RP-C8902'), ('A320N', 'RP-C8897')],
    'Singapore Airlines': [('A350-900', '9V-SGA'), ('A380-800', '9V-SKA')],
    'Cathay Pacific': [('A350-900', 'B-LXA'), ('A330-300', 'B-LAP')],
    'Japan Airlines': [('A350-900', 'JA016J'), ('B787-9', 'JA898A')],
    'ANA': [('B787-9', 'JA873A'), ('B777-300ER', 'JA732A')],
    'Korean Air': [('B787-10', 'HL8210'), ('B777-300ER', 'HL7530')],
    'Malaysia Airlines': [('A350-900', '9M-MAC'), ('B777-300ER', '9M-MRO')],
    'Thai Airways': [('B787-9', 'HS-TBA'), ('B777-300ER', 'HS-TBQ')],
    'Vietnam Airlines': [('B787-10', 'VN847'), ('A350-900', 'VN374')],
    'Emirates': [('A380-800', 'A6-APE'), ('A350-900', 'A6-BLJ')],
    'Qatar Airways': [('A350-1000', 'A7-ANA'), ('A380-800', 'A7-APA')],
    'Etihad Airways': [('B787-9', 'A6-BVA'), ('A350-900', 'A6-BLA')],
    'Saudia': [('B777-300ER', 'HZ-AEA'), ('A320', 'HZ-ABA')],
    'United Airlines': [('B777-200ER', 'N778UA'), ('B737-800', 'N37277')],
    'Delta Air Lines': [('A350-900', 'N501DN'), ('B737-900ER', 'N8390M')],
    'American Airlines': [('B777-300ER', 'N793AN'), ('B737-800', 'N912NN')],
    'Turkish Airlines': [('B777-300ER', 'TC-JJN'), ('A321N', 'TC-LJA')],
    'Air France': [('B777-300ER', 'F-GSQI'), ('A350-900', 'F-HTYA')],
}

# Airlines that already exist in the database under a different name get the
# fleet that matches what they already fly, so their existing aircraft link up.
FLEET_ALIASES = {
    'Cebu Pacific Air': 'Cebu Pacific',
    'Philippines AirAsia': 'Philippines AirAsia',
    'Philippine Airlines': 'Philippine Airlines',
    'PAL Express': 'Philippine Airlines',
}


# --------------------------------------------------------------------------
# Turning a cabin spec into rows
# --------------------------------------------------------------------------

def _normalise(value):
    return ''.join(ch for ch in (value or '').lower() if ch.isalnum())


def match_type_code(model_name, default=None):
    """Map a free-text model name such as ``Airbus A321neo`` onto a type code.

    Longest needles are tested first, so ``A321neo`` is not read as an ``A321``
    and ``Dash 8-400`` is not read as an ``8``.  Returns ``default`` when the
    name matches nothing this app knows about.
    """
    name = _normalise(model_name)
    for code, needles in sorted(TYPE_MATCHERS.items(), key=lambda kv: -len(kv[0])):
        for needle in needles:
            flat = _normalise(needle)
            if flat and flat in name:
                return code
    return default


def cabin_seat_count(cabins):
    """Total sellable seats in a cabin spec."""
    return sum(rows * sum(blocks) for _, blocks, rows in cabins)


def total_rows(cabins):
    return sum(rows for _, _, rows in cabins)


def seat_map_label(cabins):
    """``'3-3'`` or ``'1-2-1 / 2-2-2 / 3-3'`` — the cabin's blocks, nose first."""
    return ' / '.join('-'.join(str(b) for b in blocks) for _, blocks, _ in cabins)


def derive_markers(cabins):
    """Where the emergency exits, lavatories and galleys sit in this cabin.

    Derived from the cabin blocks rather than hand-listed per layout, so a new
    fleet entry only has to declare its cabins.  Every cabin boundary is a
    lavatory with an exit row beside it, the first and last rows are exits, and
    the kitchens sit at the two ends of the cabin.
    """
    total = total_rows(cabins)
    boundaries = []
    running = 0
    for _, _, rows in cabins[:-1]:
        running += rows
        boundaries.append(running)
    return {
        'exit_rows': sorted({1, total, *boundaries}),
        'lavatory_rows': boundaries,
        'galley_positions': ['front', 'aft'],
    }


def seat_position(block_width, seat_at):
    """Window / middle / aisle, judged inside its own seat block.

    In a 1-2-1 the pair is two aisle seats, and a 3-4-3 centre block has windows
    at both ends and a middle seat in between.
    """
    if seat_at == 0:
        return 'window'
    if seat_at == block_width - 1:
        return 'aisle'
    return 'middle'


def iter_seats(cabins):
    """Yield ``(row_number, letter, position, seat_number)`` for a cabin spec.

    Row numbers run globally from the nose across cabin boundaries, the way a
    boarding pass numbers them, and letters run left to right skipping 'I'/'O'.
    """
    row_no = 0
    for _, blocks, rows in cabins:
        for _ in range(rows):
            row_no += 1
            letter_at = 0
            for block_width in blocks:
                for seat_at in range(block_width):
                    letter = SEAT_LETTERS[letter_at]
                    yield row_no, letter, seat_position(block_width, seat_at), '%d%s' % (row_no, letter)
                    letter_at += 1


# --------------------------------------------------------------------------
# Writing a layout into the database
# --------------------------------------------------------------------------

# Cabin for a type this app has no curated spec for, keyed by body class.  Used
# when an aircraft already on record flies a type its airline was never
# configured for, so the record still gets a legal, bookable cabin.
FALLBACK_SPECS = {
    'NARROW_BODY': 'NARROW_180',
    'WIDE_BODY': 'B777_292',
    'REGIONAL': 'NARROW_180',
    'TURBOPROP': 'TURBOPROP_76',
    'PRIVATE_JET': 'NARROW_180',
    'OTHER': 'NARROW_180',
}

# Seats written per bulk_create call — big enough to be quick, small enough that
# a layout of a 424-seat 777 does not build one enormous statement.
SEAT_BATCH = 2000


def write_layout(SeatLayout, Cabin, Seat, airline, aircraft_type, spec_key):
    """Create the ``SeatLayout``, its ``Cabin``s and every ``Seat`` it holds.

    ``SeatLayout``/``Cabin``/``Seat`` are passed in rather than imported so this
    works from a migration's historical models as well as from live code.

    The layout is written as one unit: the cabin blocks and the individual seats
    always come from the same spec, so the map rendered on the booking page can
    never offer a seat the database does not hold.
    """
    cabins = CABIN_SPECS[spec_key]
    markers = derive_markers(cabins)
    layout = SeatLayout.objects.create(
        airline=airline,
        aircraft_type=aircraft_type,
        name=f"{airline.name} {aircraft_type.model_name} Seat Layout",
        seat_map=seat_map_label(cabins),
        exit_rows=markers['exit_rows'],
        lavatory_rows=markers['lavatory_rows'],
        galley_positions=markers['galley_positions'],
        total_capacity=cabin_seat_count(cabins),
    )

    batch = []
    first_row = 1
    for position, (fare_class, blocks, rows) in enumerate(cabins):
        cabin = Cabin.objects.create(
            seat_layout=layout, fare_class=fare_class,
            position=position, blocks=list(blocks), rows=rows)
        for row_number, letter, seat_position_kind, seat_number in iter_seats(
                [(fare_class, blocks, rows)]):
            batch.append(Seat(
                seat_layout=layout, cabin=cabin,
                row_number=first_row + row_number - 1,
                letter=letter,
                seat_number='%d%s' % (first_row + row_number - 1, letter),
                position=seat_position_kind))
            if len(batch) >= SEAT_BATCH:
                Seat.objects.bulk_create(batch)
                batch = []
        first_row += rows
    if batch:
        Seat.objects.bulk_create(batch)
    return layout
