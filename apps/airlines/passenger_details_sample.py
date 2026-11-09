"""Sample data for the passenger details prototype page.

The passenger details page is a front-end prototype of the ATRUE booking
interface: it renders the selected sample flight plus the optional extras
(seats, baggage, insurance) using fixed sample prices. Nothing here is written
to the database, no booking is created and no payment is taken. Every price is
labelled on the page as a sample that, in the real system, would come from the
airline's fare rules for the specific route and cabin.

The template and JavaScript only read prepared values from here, so the client
never invents a price of its own and the fare summary always matches what the
server rendered alongside it.
"""
from __future__ import annotations

from .sample_flights import sample_results

#: Extra checked baggage, sold in 5 kg blocks. ``(kg, price)`` in Philippine
#: pesos. The first row is "no extra baggage" and is the default selection.
BAGGAGE_OPTIONS = (
    (0, 0),
    (5, 5000),
    (10, 10000),
    (15, 15000),
    (20, 20000),
    (25, 25000),
    (30, 30000),
)

#: Optional travel insurance plans. ``(key, name, price per passenger)``.
INSURANCE_PLANS = (
    ('none', 'No Insurance', 0),
    ('basic', 'Basic Protection', 299),
    ('standard', 'Standard Protection', 499),
    ('premium', 'Premium Protection', 799),
)

#: Passenger categories. ``(key, label)`` and the maximum each category allows.
#: Infants travel on an adult's lap and do not occupy a seat.
PASSENGER_CATEGORIES = (
    ('adult', 'Adult', '12 years and older'),
    ('child', 'Child', '2-11 years'),
    ('infant', 'Infant', 'Under 2 years'),
)

MAX_ADULTS = 9
MAX_CHILDREN = 6
MAX_INFANTS = 4

#: Sample taxes and fees, per passenger, on top of the base fare.
TAXES_AND_FEES_PER_PASSENGER = 550

#: How much each extra service is charged.
#:   per_passenger - price multiplied by the passenger count
#:   per_booking   - one flat charge for the whole booking
BAGGAGE_CHARGE_BASIS = 'per_passenger'
INSURANCE_CHARGE_BASIS = 'per_passenger'

#: Sample seat map for the prototype's aircraft (a 3-3 single-aisle cabin).
#: ``rows`` lists the row numbers; ``blocks`` splits each row around the aisle;
#: ``taken`` lists seats already occupied. The page draws window, middle and
#: aisle seats from these blocks and marks the blocked seats unavailable.
SEAT_MAP = {
    'aircraft': 'Airbus A320',
    'layout': '3-3',
    'cabin': 'Economy',
    'cabin_pitch': '30 in',
    'blocks': [['A', 'B', 'C'], ['D', 'E', 'F']],
    'rows': list(range(6, 25)),
    'window_letters': ('A', 'F'),
    'aisle_letters': ('C', 'D'),
    'exit_rows': (11, 12),
    'taken': (
        '6A', '6F', '7C', '8D', '9A', '9B', '10E', '11F', '12A', '12C',
        '14D', '15F', '17B', '18E', '19A', '20C', '21F', '23D', '24A',
    ),
}

#: Seat categories and the sample surcharge each one carries, in Philippine
#: pesos. ``(key, label, price)``. A seat's category is worked out from the
#: real layout: the front rows, the exit rows, and where the seat sits in its
#: row (window, aisle or middle). The price is the sample the page shows; in
#: the live system it comes from the airline's own seat pricing.
SEAT_TYPES = (
    ('standard', 'Standard Seat', 0),
    ('window', 'Window Seat', 250),
    ('aisle', 'Aisle Seat', 200),
    ('legroom', 'Extra Legroom', 450),
    ('front', 'Front Row', 350),
)

#: How many rows at the nose of the aircraft are sold as front rows.
FRONT_ROW_COUNT = 2

#: The note shown under the seat price list in the seat picker.
SEAT_PRICING_NOTE = (
    'Seat prices are samples for this prototype. In the live system the '
    'airline sets the price of every seat category for the route and cabin.'
)

#: A short, non-binding description of each insurance plan, its cover and its
#: exclusions. These are illustrative for the prototype and are not the terms
#: of any real policy.
INSURANCE_DETAILS = {
    'none': {
        'summary': 'No travel insurance is added to this booking.',
        'covers': [],
        'excludes': [
            'No trip cancellation, medical or baggage cover is provided.',
        ],
    },
    'basic': {
        'summary': 'Essential cover for unexpected events before and during the trip.',
        'covers': [
            'Emergency medical expenses up to \u20b1500,000.',
            'Trip cancellation for a covered reason up to \u20b150,000.',
            'Loss of checked baggage up to \u20b120,000.',
        ],
        'excludes': [
            'Pre-existing medical conditions.',
            'Cancellation because you changed your mind.',
            'High-value items and electronics in checked baggage.',
        ],
    },
    'standard': {
        'summary': 'Wider cover with trip interruption and higher medical limits.',
        'covers': [
            'Emergency medical expenses up to \u20b11,500,000.',
            'Trip cancellation or interruption up to \u20b1150,000.',
            'Loss of checked baggage up to \u20b140,000.',
            'Travel delay from 6 hours.',
            'Delayed baggage and personal accident cover, subject to policy limits.',
        ],
        'excludes': [
            'Pre-existing medical conditions unless declared and accepted.',
            'Adventure sports and activities not listed in the policy.',
            'Travel against medical advice.',
        ],
    },
    'premium': {
        'summary': 'Our highest limits, including travel delay and missed connection.',
        'covers': [
            'Emergency medical expenses up to \u20b13,000,000.',
            'Trip cancellation or interruption up to \u20b1300,000.',
            'Loss of checked baggage up to \u20b180,000.',
            'Travel delay from 3 hours and missed connection cover.',
            'Emergency medical evacuation and repatriation.',
            'Flight delay, lost or delayed baggage, and personal accident cover, subject to policy limits.',
        ],
        'excludes': [
            'Pre-existing medical conditions unless declared and accepted.',
            'Known events, epidemics and travel against government advice.',
            'Professional sports and racing.',
        ],
    },
}

#: The cancellation and refund process shown in the policy card. ``(title, body)``.
REFUND_STEPS = (
    ('Submit a cancellation request',
     'Open the booking, choose \u201cRequest Cancellation\u201d, and give the '
     'booking reference and the reason for cancelling.'),
    ('Provide supporting documents',
     'For illness, a medical or family emergency, or another potentially '
     'eligible reason, upload the documents that reason needs. Only documents '
     'relevant to the policy in force are requested.'),
    ('Verify eligibility',
     'The fare conditions, the airline\u2019s cancellation rules, the deadline '
     'for the request and any insurance cover are checked against the booking.'),
    ('Review the request',
     'A booking administrator or the airline reviews the request and the '
     'documents. A request is never approved automatically just because a '
     'reason was entered.'),
    ('Determine the refund',
     'The outcome is one of: a full refund, a partial refund after applicable '
     'fees, a refund under the purchased insurance subject to its terms, or no '
     'refund under the applicable conditions.'),
    ('Process the approved refund',
     'For approved requests the amount, payment method, status and processing '
     'date are recorded, and you are notified when the refund is processed.'),
)

#: Possible statuses a refund request can move through.
REFUND_STATUSES = (
    'Submitted',
    'Under Review',
    'Additional Documents Required',
    'Approved',
    'Rejected',
    'Refund Processing',
    'Refunded',
)


def _money(value) -> str:
    """Format a peso amount the way the page shows it, e.g. ``\u20b12,498.00``."""
    return f'\u20b1{value:,.2f}'


def selected_flight(origin_code: str = 'MNL', destination_code: str = 'CEB',
                    index: int = 0) -> dict:
    """The flight whose details the passenger page summarises.

    Reuses the sample schedule so the page agrees with the results list, then
    adds the extra fields the passenger page needs (class, meal and Wi-Fi
    labels, aircraft already present) and formatted money strings.
    """
    rows = sample_results(origin_code, destination_code)
    index = max(0, min(index, len(rows) - 1))
    flight = dict(rows[index])
    flight['fare_class'] = 'Economy'
    flight['fare_class_label'] = 'Economy Class'
    flight['base_fare'] = flight['price']
    flight['base_fare_text'] = _money(flight['price'])
    return flight


def fare_context(selected: dict) -> dict:
    """Everything the fare summary and extras selectors need to render.

    Prices are sent to the page as numbers so the JavaScript can recompute the
    total from the current selections; the matching ``*_text`` strings are sent
    too so the first paint already shows formatted values.
    """
    baggage = [
        {'kg': kg, 'price': price, 'price_text': _money(price),
         'label': 'No extra baggage' if kg == 0 else f'{kg} kg'}
        for kg, price in BAGGAGE_OPTIONS
    ]
    insurance = [
        {'key': key, 'name': name, 'price': price, 'price_text': _money(price),
         'details': INSURANCE_DETAILS[key]}
        for key, name, price in INSURANCE_PLANS
    ]
    return {
        'base_fare': selected['base_fare'],
        'currency': 'PHP',
        'base_fare_text': selected['base_fare_text'],
        'taxes_per_passenger': TAXES_AND_FEES_PER_PASSENGER,
        'taxes_per_passenger_text': _money(TAXES_AND_FEES_PER_PASSENGER),
        'baggage_options': baggage,
        'insurance_plans': insurance,
        'baggage_basis': BAGGAGE_CHARGE_BASIS,
        'insurance_basis': INSURANCE_CHARGE_BASIS,
        'seat_types': [
            {'key': key, 'label': label, 'price': price,
             'price_text': _money(price)}
            for key, label, price in SEAT_TYPES
        ],
        'seat_pricing_note': SEAT_PRICING_NOTE,
        'passenger_categories': [
            {'key': key, 'label': label, 'hint': hint}
            for key, label, hint in PASSENGER_CATEGORIES
        ],
        'max_adults': MAX_ADULTS,
        'max_children': MAX_CHILDREN,
        'max_infants': MAX_INFANTS,
    }


def _seat_category(row: int, position: str, exit_rows: set, front_rows: set) -> str:
    """Which seat category a seat is sold as.

    A row near the nose is a front row and an exit row has the extra
    legroom, so those win over where the seat sits in its row. Everything
    else is decided by the seat's own position: window, aisle or middle.
    """
    if row in front_rows:
        return 'front'
    if row in exit_rows:
        return 'legroom'
    if position == 'window':
        return 'window'
    if position == 'aisle':
        return 'aisle'
    return 'standard'


def seat_map_context(aircraft: str | None = None) -> dict:
    """The seat map with each seat's row, letter, position and availability.

    Each seat also carries the category it is sold as and the price of that
    category, so the picker can show what a seat costs without the page
    inventing a price of its own.
    """
    # The result preview has multiple aircraft types. Match the seat map to
    # the aircraft on the selected result instead of always showing an A320.
    aircraft_name = (aircraft or SEAT_MAP['aircraft']).strip()
    aircraft_key = aircraft_name.lower()
    if aircraft_key.startswith('atr 72'):
        blocks = [['A', 'B'], ['C', 'D']]
        rows = list(range(1, 19))
        layout, pitch = '2-2', '30 in'
        exit_rows = {9, 10}
        window, aisle = {'A', 'D'}, {'B', 'C'}
    elif aircraft_key.startswith('airbus a330'):
        blocks = [['A', 'C'], ['D', 'E', 'F', 'G'], ['H', 'K']]
        rows = list(range(10, 41))
        layout, pitch = '2-4-2', '32 in'
        exit_rows = {20, 21}
        window, aisle = {'A', 'K'}, {'C', 'D', 'G', 'H'}
    else:
        blocks = [['A', 'B', 'C'], ['D', 'E', 'F']]
        wide = 'a321' in aircraft_key
        rows = list(range(6, 40 if wide else 36))
        layout, pitch = '3-3', '30 in'
        exit_rows = {12, 13, 26, 27} if wide else {11, 12, 25, 26}
        window, aisle = {'A', 'F'}, {'C', 'D'}
    taken = set(SEAT_MAP['taken'])
    letters = [letter for block in blocks for letter in block]
    front_rows = set(rows[:FRONT_ROW_COUNT])
    prices = {key: price for key, _label, price in SEAT_TYPES}
    labels = {key: label for key, label, _price in SEAT_TYPES}
    seats = []
    for row in rows:
        row_seats = []
        for letter in letters:
            number = f'{row}{letter}'
            if letter in window:
                position = 'window'
            elif letter in aisle:
                position = 'aisle'
            else:
                position = 'middle'
            position_label = {
                'window': 'Window',
                'aisle': 'Aisle',
                'middle': 'Middle',
            }[position]
            category = _seat_category(row, position, exit_rows, front_rows)
            price = prices.get(category, 0)
            row_seats.append({
                'number': number,
                'letter': letter,
                'aisle_before': any(letter == block[0] for block in blocks[1:]),
                'position': position,
                'position_label': position_label,
                'category': category,
                'category_label': labels.get(category, 'Standard Seat'),
                'price': price,
                'price_text': _money(price),
                'taken': number in taken,
            })
        seats.append({'row': row, 'seats': row_seats,
                      'is_exit': row in exit_rows})
    return {
        'aircraft': aircraft_name,
        'layout': layout,
        'cabin': SEAT_MAP['cabin'],
        'cabin_pitch': pitch,
        'blocks': blocks,
        'aisle_starts': [block[0] for block in blocks[1:]],
        'letters': letters,
        'rows': seats,
        'exit_rows': sorted(exit_rows),
        'front_rows': sorted(front_rows),
    }


def refund_context() -> dict:
    """The cancellation/refund policy content for the information card."""
    return {
        'steps': [{'title': title, 'body': body} for title, body in REFUND_STEPS],
        'statuses': list(REFUND_STATUSES),
    }
