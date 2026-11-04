"""Sample results shown on the public flight search results page.

The search results page is a front-end recreation of the ATRUE booking
interface, so it renders this fixed sample schedule instead of live airline
inventory. Nothing here is written to the database, none of these rows are
bookable, and the page labels them as sample results.

Everything the presentation needs is derived here - clock times, duration,
departure window, stop count, emissions and price - so templates and
JavaScript only read prepared fields and never do travel maths of their own.

The search results preview can assign a variety of sample routes to its rows;
detail and passenger-preview views can request one specific route instead.
"""
from __future__ import annotations

#: Airline identity for a sample row. ``group`` is the filter bucket shown in
#: the sidebar; ``logo`` is a static asset so the page never depends on media
#: uploads being present.
AIRLINES = {
    'PR': {
        'name': 'Philippine Airlines',
        'group': 'philippine-airlines',
        'logo': 'img/airlines/pal-mark.png',
        'origin_terminal': 'Terminal 3',
        'destination_terminal': 'Terminal 1',
        'checked_baggage': '20kg',
        'cabin_baggage': '7kg',
        'wifi': 'free',
        'meal': 'included',
    },
    '5J': {
        'name': 'Cebu Pacific',
        'group': 'cebu-pacific',
        'logo': 'img/airlines/cebu-pacific-mark.png',
        'origin_terminal': 'Terminal 3',
        'destination_terminal': 'Terminal 2',
        'checked_baggage': '15kg',
        'cabin_baggage': '7kg',
        'wifi': 'none',
        'meal': 'purchase',
    },
    'Z2': {
        'name': 'AirAsia',
        'group': 'airasia',
        'logo': 'img/airlines/airasia-mark.png',
        'origin_terminal': 'Terminal 4',
        'destination_terminal': 'Terminal 2',
        'checked_baggage': '15kg',
        'cabin_baggage': '7kg',
        'wifi': 'paid',
        'meal': 'purchase',
    },
    '2P': {
        'name': 'PAL Express',
        'group': 'others',
        'logo': '',
        'origin_terminal': 'Terminal 2',
        'destination_terminal': 'Terminal 1',
        'checked_baggage': '20kg',
        'cabin_baggage': '7kg',
        'wifi': 'free',
        'meal': 'snack',
    },
    'DG': {
        'name': 'CebGo',
        'group': 'others',
        'logo': '',
        'origin_terminal': 'Terminal 4',
        'destination_terminal': 'Terminal 1',
        'checked_baggage': '10kg',
        'cabin_baggage': '5kg',
        'wifi': 'none',
        'meal': 'snack',
    },
}

#: Filter buckets, in the order the sidebar lists them.
AIRLINE_FILTERS = (
    ('philippine-airlines', 'Philippine Airlines'),
    ('cebu-pacific', 'Cebu Pacific'),
    ('airasia', 'AirAsia'),
    ('others', 'Others'),
)

STOP_FILTERS = (('nonstop', 'Non-stop'), ('1', '1 Stop'), ('2+', '2+ Stops'))

BAND_FILTERS = (
    ('early', 'Early Morning', '12am-6am'),
    ('morning', 'Morning', '6am-12pm'),
    ('afternoon', 'Afternoon', '12pm-6pm'),
    ('evening', 'Evening', '6pm-12am'),
)

DURATION_FILTERS = (
    ('lt1', 'Less than 1h'),
    ('1-3', '1h-3h'),
    ('3-6', '3h-6h'),
)

#: Airports offered in the search form. ``code -> (city, airport name)`` so a
#: route change can relabel every card without another server round trip.
AIRPORT_CHOICES = (
    ('MNL', 'Manila', 'Ninoy Aquino International Airport'),
    ('CEB', 'Cebu', 'Mactan-Cebu International Airport'),
    ('DVO', 'Davao', 'Francisco Bangoy International Airport'),
    ('ILO', 'Iloilo', 'Iloilo International Airport'),
    ('KLO', 'Kalibo', 'Kalibo International Airport'),
    ('PPS', 'Puerto Princesa', 'Puerto Princesa International Airport'),
    ('MPH', 'Caticlan', 'Godofredo P. Ramos Airport'),
    ('CGY', 'Cagayan de Oro', 'Lumbia Airport'),
    ('TAC', 'Tacloban', 'Daniel Z. Romualdez Airport'),
    ('ZAM', 'Zamboanga', 'Zamboanga International Airport'),
    ('BKK', 'Bangkok', 'Suvarnabhumi Airport'),
    ('SIN', 'Singapore', 'Singapore Changi Airport'),
    ('HKG', 'Hong Kong', 'Hong Kong International Airport'),
    ('DXB', 'Dubai', 'Dubai International Airport'),
    ('KUL', 'Kuala Lumpur', 'Kuala Lumpur International Airport'),
    ('TPE', 'Taipei', 'Taiwan Taoyuan International Airport'),
    ('HND', 'Tokyo', 'Tokyo Haneda International Airport'),
    ('ICN', 'Seoul', 'Incheon International Airport'),
    ('CGK', 'Jakarta', 'Soekarno-Hatta International Airport'),
    ('SGN', 'Ho Chi Minh City', 'Tan Son Nhat International Airport'),
    ('SYD', 'Sydney', 'Sydney Kingsford Smith Airport'),
    ('LHR', 'London', 'Heathrow Airport'),
)

AIRPORT_NAMES = {code: name for code, _, name in AIRPORT_CHOICES}
AIRPORT_CITIES = {code: city for code, city, _ in AIRPORT_CHOICES}
AIRPORT_COUNTRIES = {
    'MNL': 'Philippines', 'CEB': 'Philippines', 'DVO': 'Philippines',
    'ILO': 'Philippines', 'KLO': 'Philippines', 'PPS': 'Philippines',
    'MPH': 'Philippines', 'CGY': 'Philippines', 'TAC': 'Philippines',
    'ZAM': 'Philippines', 'BKK': 'Thailand', 'SIN': 'Singapore',
    'HKG': 'Hong Kong', 'DXB': 'United Arab Emirates',
    'KUL': 'Malaysia', 'TPE': 'Taiwan', 'HND': 'Japan', 'ICN': 'South Korea',
    'CGK': 'Indonesia', 'SGN': 'Vietnam', 'SYD': 'Australia', 'LHR': 'United Kingdom',
}

MIXED_SAMPLE_ROUTES = (
    ('MNL', 'CEB'), ('MNL', 'SIN'), ('MNL', 'HKG'), ('MNL', 'BKK'),
    ('MNL', 'HND'), ('MNL', 'DXB'), ('CEB', 'DVO'), ('SIN', 'KUL'),
    ('HKG', 'TPE'), ('BKK', 'ICN'), ('CGK', 'SGN'), ('SYD', 'SIN'),
    ('LHR', 'DXB'), ('MNL', 'PPS'), ('MNL', 'ILO'),
)

#: The schedule. First five rows are the reference results (Philippine
#: Airlines 06:20-07:55 at 2,498, then Cebu Pacific, AirAsia, Philippine
#: Airlines and AirAsia); the rest continue the same day in ascending fare
#: order so the default price sort shows them in this order.
#: (flight number, airline key, depart, arrive, price, stops, aircraft)
_SCHEDULE = (
    ('PR 1642', 'PR', '06:20', '07:55', 2498, 0, 'Airbus A320'),
    ('5J 571', '5J', '08:20', '09:50', 3198, 0, 'Airbus A321neo'),
    ('Z2 7705', 'Z2', '10:55', '12:25', 3299, 0, 'Airbus A320'),
    ('PR 1846', 'PR', '15:50', '17:30', 3299, 0, 'Airbus A321'),
    ('Z2 7719', 'Z2', '18:20', '19:55', 4099, 0, 'Airbus A320neo'),
    ('5J 579', '5J', '04:15', '05:45', 4198, 0, 'Airbus A320'),
    ('Z2 7723', 'Z2', '00:35', '02:00', 4298, 0, 'Airbus A320neo'),
    ('PR 1852', 'PR', '13:05', '14:45', 4499, 0, 'Airbus A321'),
    ('2P 284', '2P', '05:35', '06:30', 4650, 0, 'Airbus A320'),
    ('5J 585', '5J', '19:40', '21:10', 4780, 0, 'Airbus A321neo'),
    ('PR 1858', 'PR', '06:55', '08:30', 4899, 0, 'Airbus A320'),
    ('Z2 7731', 'Z2', '16:25', '18:00', 5050, 0, 'Airbus A320'),
    ('5J 587', '5J', '02:50', '04:20', 5198, 0, 'Airbus A320'),
    ('PR 1862', 'PR', '12:40', '14:20', 5350, 0, 'Airbus A321'),
    ('DG 6017', 'DG', '07:15', '08:10', 5480, 0, 'ATR 72-600'),
    ('Z2 7737', 'Z2', '14:55', '16:25', 5599, 0, 'Airbus A320neo'),
    ('PR 1868', 'PR', '21:20', '22:55', 5750, 0, 'Airbus A320'),
    ('5J 591', '5J', '20:35', '22:05', 5899, 0, 'Airbus A321'),
    ('PR 1874', 'PR', '17:45', '20:40', 5980, 1, 'Airbus A321'),
    ('Z2 7743', 'Z2', '03:25', '04:55', 6150, 0, 'Airbus A320'),
    ('2P 292', '2P', '12:35', '13:30', 6299, 0, 'Airbus A320'),
    ('5J 597', '5J', '20:05', '21:40', 6450, 0, 'Airbus A321neo'),
    ('PR 1880', 'PR', '09:25', '12:40', 6599, 1, 'Airbus A321'),
    ('Z2 7749', 'Z2', '18:55', '20:30', 6850, 0, 'Airbus A320neo'),
    ('5J 603', '5J', '15:30', '19:45', 7150, 2, 'Airbus A320'),
    ('PR 1886', 'PR', '05:55', '07:30', 7480, 0, 'Airbus A320'),
    ('DG 6051', 'DG', '06:30', '07:25', 7850, 0, 'ATR 72-600'),
    ('5J 615', '5J', '13:45', '16:30', 8290, 1, 'Airbus A321'),
    ('5J 619', '5J', '21:05', '00:00', 8750, 1, 'Airbus A320'),
    ('PR 1892', 'PR', '11:15', '14:30', 9450, 1, 'Airbus A321'),
    ('Z2 7757', 'Z2', '14:10', '16:50', 11450, 1, 'Airbus A320'),
    ('PR 1899', 'PR', '07:50', '12:35', 14980, 2, 'Airbus A330-300'),
)

_WIFI_LABELS = {
    'free': 'Free Wi-Fi',
    'paid': 'Wi-Fi for purchase',
    'none': 'No Wi-Fi',
}

_MEAL_LABELS = {
    'included': 'Meal included',
    'snack': 'Snack included',
    'purchase': 'Meal for purchase',
}


def _clock(value: str) -> tuple[str, int]:
    """``'14:05' -> ('02:05 PM', 845)``: display clock and minutes past midnight."""
    hour, minute = (int(part) for part in value.split(':'))
    total = hour * 60 + minute
    suffix = 'AM' if hour < 12 else 'PM'
    display_hour = hour % 12 or 12
    return f'{display_hour:02d}:{minute:02d} {suffix}', total


def _duration_text(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if not hours:
        return f'{remainder}m'
    return f'{hours}h {remainder:02d}m'


def _band(total_minutes: int) -> str:
    hour = total_minutes // 60
    if hour < 6:
        return 'early'
    if hour < 12:
        return 'morning'
    if hour < 18:
        return 'afternoon'
    return 'evening'


def _duration_bucket(minutes: int) -> str:
    if minutes < 60:
        return 'lt1'
    if minutes < 180:
        return '1-3'
    return '3-6'


def _fare_rules(airline: str) -> list[str]:
    return [
        f'Fare is per passenger and excludes terminal and convenience fees.',
        f'{airline} allows date changes up to 4 hours before departure for a '
        f'\u20b11,500 rebooking fee plus any fare difference.',
        'Seats are assigned at online check-in unless pre-purchased.',
    ]


def _change_rules(airline: str) -> list[str]:
    return [
        f'Cancellation requests are accepted up to 24 hours before departure; '
        f'a \u20b11,200 service fee applies.',
        'Ticket name changes are not permitted after issuance.',
        'If ATRUE cancels or delays the flight by more than 3 hours, you may '
        'rebook on the next available flight at no cost.',
    ]


def filter_counts(rows: list[dict]) -> dict:
    """Sidebar counts for a result set, keyed the way the sidebar lists them.

    The counts are rendered with the page so the sidebar is truthful before
    any JavaScript runs; the client never has to invent numbers.
    """
    def count(key, value):
        return sum(1 for row in rows if row[key] == value)

    return {
        'stops': {value: count('stops_bucket', value)
                  for value, _ in STOP_FILTERS},
        'airline': {value: count('airline_group', value)
                    for value, _ in AIRLINE_FILTERS},
        'band': {value: count('band', value)
                 for value, _, _ in BAND_FILTERS},
        'duration': {value: count('duration_bucket', value)
                     for value, _ in DURATION_FILTERS},
    }


def filter_groups(rows: list[dict]) -> list[dict]:
    """Checkbox groups for the sidebar, ready for the template to loop.

    Labels, hints and counts travel together so the sidebar template is a
    dumb ``{% for %}`` and every number on the page comes from the data.
    """
    counts = filter_counts(rows)
    return [
        {
            'key': 'stops',
            'title': 'Stops',
            'items': [
                {'value': value, 'label': label, 'hint': '',
                 'count': counts['stops'][value]}
                for value, label in STOP_FILTERS
            ],
        },
        {
            'key': 'airline',
            'title': 'Airlines',
            'select_all': True,
            'items': [
                {'value': value, 'label': label, 'hint': '',
                 'count': counts['airline'][value]}
                for value, label in AIRLINE_FILTERS
            ],
        },
        {
            'key': 'band',
            'title': 'Departure Time',
            'items': [
                {'value': value, 'label': label, 'hint': window,
                 'count': counts['band'][value]}
                for value, label, window in BAND_FILTERS
            ],
        },
        {
            'key': 'duration',
            'title': 'Flight Duration',
            'items': [
                {'value': value, 'label': label, 'hint': '',
                 'count': counts['duration'][value]}
                for value, label in DURATION_FILTERS
            ],
        },
    ]


def sample_results(origin_code: str = 'MNL',
                   destination_code: str = 'CEB', mixed: bool = False) -> list[dict]:
    """Return sample schedules for one searched route or a mixed route preview.

    Times, durations, windows, stops and emissions are computed once so the
    template and the client-side filters sort and group identical values.
    """
    origin_code = (origin_code or 'MNL').upper()[:3]
    destination_code = (destination_code or 'CEB').upper()[:3]
    results = []
    for index, (flight_number, airline_key, depart, arrive, price, stops,
                aircraft) in enumerate(_SCHEDULE, start=1):
        row_origin, row_destination = (
            MIXED_SAMPLE_ROUTES[(index - 1) % len(MIXED_SAMPLE_ROUTES)]
            if mixed else (origin_code, destination_code)
        )
        origin_airport = AIRPORT_NAMES.get(
            row_origin, f'{AIRPORT_CITIES.get(row_origin, row_origin)} Airport')
        destination_airport = AIRPORT_NAMES.get(
            row_destination,
            f'{AIRPORT_CITIES.get(row_destination, row_destination)} Airport')
        airline = AIRLINES[airline_key]
        depart_label, depart_minutes = _clock(depart)
        arrive_label, arrive_minutes = _clock(arrive)
        if arrive_minutes <= depart_minutes:
            arrive_minutes += 24 * 60  # overnight arrival
        duration = arrive_minutes - depart_minutes
        stops_label = 'Non-stop' if stops == 0 else (
            f'{stops} Stop' if stops == 1 else f'{stops} Stops')
        wifi = airline['wifi']
        meal = airline['meal']
        results.append({
            'id': f'FS{index:02d}',
            'airline': airline['name'],
            'airline_key': airline_key,
            'airline_group': airline['group'],
            'airline_logo': airline['logo'],
            'flight_number': flight_number,
            'aircraft': aircraft,
            'depart_time': depart_label,
            'arrive_time': arrive_label,
            'depart_minutes': depart_minutes,
            'arrive_minutes': arrive_minutes,
            'overnight': arrive_minutes >= 24 * 60,
            'duration_minutes': duration,
            'duration_text': _duration_text(duration),
            'stops': stops,
            'stops_label': stops_label,
            'stops_bucket': 'nonstop' if stops == 0 else str(stops) if stops == 1 else '2+',
            'price': price,
            'price_text': f'{price:,}',
            'band': _band(depart_minutes),
            'duration_bucket': _duration_bucket(duration),
            'emissions': round(45 + duration * 0.55 + stops * 30),
            'wifi': wifi,
            'wifi_label': _WIFI_LABELS[wifi],
            'meal': meal,
            'meal_label': _MEAL_LABELS[meal],
            'checked_baggage': airline['checked_baggage'],
            'cabin_baggage': airline['cabin_baggage'],
            'origin_code': row_origin,
            'destination_code': row_destination,
            'origin_airport': origin_airport,
            'destination_airport': destination_airport,
            'origin_city': AIRPORT_CITIES.get(row_origin, row_origin),
            'destination_city': AIRPORT_CITIES.get(row_destination, row_destination),
            'origin_country': AIRPORT_COUNTRIES.get(row_origin, ''),
            'destination_country': AIRPORT_COUNTRIES.get(row_destination, ''),
            'origin_address': '',
            'destination_address': '',
            'origin_terminal': airline['origin_terminal'],
            'destination_terminal': airline['destination_terminal'],
            'fare_rules': _fare_rules(airline['name']),
            'change_rules': _change_rules(airline['name']),
        })
    return results
