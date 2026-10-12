"""Timezone-aware timing maths for flight itineraries.

A connecting journey is a chain of real flight legs, and each leg leaves one
airport's local clock and lands on another's.  Subtracting the two clock times
the administrator typed gives the wrong answer the moment the airports are in
different zones — MNL 10:00 to HKG 14:00 is four hours of clock time but only
three hours of flying.  Every duration, layover and total in ATRUE is therefore
computed here from timezone-aware values, and never from local clock
subtraction.

The helpers are deliberately free of model imports so both ``models`` and
``views`` can use them without a circular import: the caller passes the airport
objects (or plain IANA timezone names) in.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    'MAX_ITINERARY_SEGMENTS',
    'airport_timezone',
    'combine_local',
    'format_duration',
    'is_valid_timezone',
    'itinerary_timing',
    'layover_minutes',
    'resolve_timezone',
    'segment_duration_minutes',
    'utc_of',
]

#: A journey with more legs than this is not a connecting flight, it is a
#: mis-typed form, so the resolver refuses it rather than writing it.
MAX_ITINERARY_SEGMENTS = 6

#: Used when an airport carries no timezone of its own: the platform default
#: (``settings.TIME_ZONE``), which is how a direct schedule written before
#: timezone data existed keeps behaving exactly as it did.
DEFAULT_TIMEZONE_FALLBACK = 'Asia/Manila'


def is_valid_timezone(name):
    """Whether ``name`` is an IANA zone this installation can resolve."""
    if not name:
        return False
    try:
        ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False
    return True


def resolve_timezone(name, default=None):
    """Return a usable ``ZoneInfo`` for ``name``, or the platform default."""
    if name:
        try:
            return ZoneInfo(str(name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            pass
    if default:
        try:
            return ZoneInfo(str(default))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            pass
    return ZoneInfo(DEFAULT_TIMEZONE_FALLBACK)


def airport_timezone(airport, default=None):
    """The IANA zone of an ``Airport`` record.

    Airports seeded before timezone support have an empty ``timezone`` column;
    those fall back to the platform zone so their existing schedules keep the
    exact durations they always had.
    """
    return resolve_timezone(getattr(airport, 'timezone', '') or '', default)


def combine_local(day, clock, tzinfo):
    """Attach ``tzinfo`` to a naive local date+time, as an aware datetime.

    A flight schedule is written in *airport local* time, so the wall-clock
    value the manager typed belongs to that airport's zone, not the server's.
    """
    if day is None or clock is None:
        return None
    return datetime.combine(day, clock, tzinfo=tzinfo)


def utc_of(value, tzinfo):
    """The UTC instant for a naive local ``value`` read in ``tzinfo``."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=tzinfo)
    return value.astimezone(ZoneInfo('UTC'))


def segment_duration_minutes(departure_local, arrival_local, departure_tz, arrival_tz):
    """Minutes actually in the air for one leg.

    Both ends are airport-local clock readings, so they are converted to UTC
    before subtracting.  Returns ``None`` when either end is missing, and
    ``None`` rather than a negative number for a leg that would arrive before it
    departed — the caller turns that into a validation error.
    """
    dep = utc_of(departure_local, departure_tz)
    arr = utc_of(arrival_local, arrival_tz)
    if dep is None or arr is None:
        return None
    minutes = int((arr - dep).total_seconds() // 60)
    return minutes if minutes >= 0 else None


def layover_minutes(previous_arrival_local, next_departure_local,
                     previous_tz, next_tz):
    """Minutes on the ground between two legs, or ``None`` when invalid.

    Same rule as the flight time: convert both sides to UTC first, because the
    layover clock is written at two different airports.
    """
    arr = utc_of(previous_arrival_local, previous_tz)
    dep = utc_of(next_departure_local, next_tz)
    if arr is None or dep is None:
        return None
    minutes = int((dep - arr).total_seconds() // 60)
    return minutes if minutes >= 0 else None


def format_duration(minutes):
    """Human duration for a stored minute count: ``3h 30m``, ``45m``, ``2h``."""
    if minutes is None:
        return ''
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return ''
    if minutes < 0:
        return ''
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _local(segment, attr_dt, attr_tz):
    """The aware local datetime for a segment, from its own columns.

    Django stores these as UTC, so a leg that departs Manila at 08:00 is read
    back as 00:00 UTC.  The *instant* is right, but the wall clock is not: a
    ticket that printed the stored value would tell a passenger their Dubai
    flight lands at 14:00 when the airport clock says 18:00.  So an aware value
    is converted into the leg's own zone rather than handed back untouched.

    Falls back to the airport's zone when the segment itself carries none, so a
    segment written before the timezone columns existed still computes.
    """
    value = getattr(segment, attr_dt, None)
    if value is None:
        return None
    tz_name = getattr(segment, attr_tz, '') or ''
    if not tz_name:
        airport = getattr(segment, _airport_attr(attr_tz), None)
        tz_name = getattr(airport, 'timezone', '') or ''
    zone = resolve_timezone(tz_name)
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def _airport_attr(attr_tz):
    return 'origin_airport' if attr_tz.endswith('departure_timezone') else 'destination_airport'


def itinerary_timing(segments):
    """Per-leg flight times, per-connection layovers and the whole-journey totals.

    ``segments`` is the ordered list of ``Flight`` rows of one itinerary.  The
    returned dict is what the flight form preview, the search card, the detail
    timeline and the e-ticket all read, so those four can never disagree about
    how long a journey is::

        {
          'legs': [{'segment': s, 'flight_minutes': .., 'label': '3h 30m',
                    'departure_local': aware, 'arrival_local': aware}, ...],
          'layovers': [{'airport': a, 'minutes': .., 'label': '2h 30m'}, ...],
          'total_minutes': .., 'total_label': '13h',
          'stops': .., 'segment_count': ..,
        }
    """
    legs = list(segments or [])
    rows = []
    for segment in legs:
        departure_local = _local(segment, 'departure_time', 'departure_timezone')
        arrival_local = _local(segment, 'arrival_time', 'arrival_timezone')
        minutes = segment_duration_minutes(
            departure_local, arrival_local,
            departure_local.tzinfo if departure_local else None,
            arrival_local.tzinfo if arrival_local else None)
        rows.append({
            'segment': segment,
            'flight_minutes': minutes,
            'label': format_duration(minutes),
            'departure_local': departure_local,
            'arrival_local': arrival_local,
        })

    layovers = []
    for previous, current in zip(rows, rows[1:]):
        minutes = layover_minutes(
            previous['arrival_local'], current['departure_local'],
            previous['arrival_local'].tzinfo if previous['arrival_local'] else None,
            current['departure_local'].tzinfo if current['departure_local'] else None)
        layovers.append({
            'airport': getattr(previous['segment'], 'destination_airport', None),
            'minutes': minutes,
            'label': format_duration(minutes),
        })

    total = None
    if rows and rows[0]['departure_local'] and rows[-1]['arrival_local']:
        first, last = rows[0]['departure_local'], rows[-1]['arrival_local']
        delta = last.astimezone(ZoneInfo('UTC')) - first.astimezone(ZoneInfo('UTC'))
        total = max(0, int(delta.total_seconds() // 60))

    return {
        'legs': rows,
        'layovers': layovers,
        'total_minutes': total,
        'total_label': format_duration(total),
        'stops': max(0, len(legs) - 1),
        'segment_count': len(legs),
    }


def parse_clock(value):
    """Parse an ``HH:MM`` string (or a ``datetime.time``) from a form post."""
    if value in (None, ''):
        return None
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    text = str(value).strip()
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def total_price(base_fare, taxes=0, airport_fees=0, fuel_surcharge=0,
                service_fee=0, discount=0):
    """TOTAL = base + taxes + airport fees + fuel surcharge + service fee - discount.

    Shared by the resolver, the form preview and the price summary so the number
    a manager sees is the number that is stored.
    """
    def _num(value):
        try:
            return value if value else 0
        except TypeError:
            return 0

    total = (_num(base_fare) + _num(taxes) + _num(airport_fees)
             + _num(fuel_surcharge) + _num(service_fee) - _num(discount))
    return max(0, total)


def timedelta_minutes(value):
    """Coerce a ``timedelta`` to whole minutes, rounded down."""
    if value is None:
        return None
    if isinstance(value, timedelta):
        return int(value.total_seconds() // 60)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
