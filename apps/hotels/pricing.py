"""Standard ATRUE room pricing.

The Add/Edit Room form no longer starts blank. Both money fields are pre-filled
from this table so a manager gets ATRUE's standard price for the selected room
type and can still type an override if the property genuinely differs.

This module is the **only** place these numbers live. Change a value here and
it applies to the form defaults, and to ``manage.py set_standard_rates`` which
backfills the rooms already in the database.

Why the rate is per room type
-----------------------------
``Room`` has a single ``rate`` column and the booking engine bills
``room.rate`` per night, so the rate is the one number ATRUE can actually
charge and display. A per-type table keeps a Suite from costing the same as a
Single without inventing per-booking "rate plans" that the booking pipeline
would never honour (see ``apps/hotels/room_offers.py`` for why those were
removed).
"""

from decimal import Decimal, InvalidOperation

# Standard nightly rate per room type, in pesos.
RATE_BY_ROOM_TYPE = {
    'SINGLE': Decimal('5900.00'),
    'DOUBLE': Decimal('6900.00'),
    'TWIN': Decimal('6900.00'),
    'DELUXE': Decimal('11500.00'),
    'SUITE': Decimal('15500.00'),
    'FAMILY': Decimal('15500.00'),
    'OTHER': Decimal('6900.00'),
}

# Additional guest charge per extra guest, per night, in pesos.
# ~8% of the standard rate, rounded to a clean figure.
EXTRA_GUEST_CHARGE_BY_ROOM_TYPE = {
    'SINGLE': Decimal('500.00'),
    'DOUBLE': Decimal('500.00'),
    'TWIN': Decimal('500.00'),
    'DELUXE': Decimal('800.00'),
    'SUITE': Decimal('1000.00'),
    'FAMILY': Decimal('1000.00'),
    'OTHER': Decimal('500.00'),
}

# Used when a room type is missing or unrecognised.
FALLBACK_RATE = RATE_BY_ROOM_TYPE['DOUBLE']
FALLBACK_EXTRA_GUEST_CHARGE = EXTRA_GUEST_CHARGE_BY_ROOM_TYPE['DOUBLE']


def standard_rate(room_type):
    return RATE_BY_ROOM_TYPE.get(room_type, FALLBACK_RATE)


def standard_extra_guest_charge(room_type):
    return EXTRA_GUEST_CHARGE_BY_ROOM_TYPE.get(room_type, FALLBACK_EXTRA_GUEST_CHARGE)


def parse_money(raw, default):
    """Turn a POSTed money string into a non-negative ``Decimal``.

    Returns ``(value, error)``. Blank input falls back to ``default`` so a
    cleared field cannot silently become a free room, and junk input returns a
    message instead of raising inside the model's ``get_prep_value``.
    """
    text = (raw or '').strip().replace(',', '')
    if not text:
        return default, None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, 'Enter a valid amount, for example 6900 or 6900.00.'
    if value < 0:
        return None, 'Amount cannot be negative.'
    return value.quantize(Decimal('0.01')), None
