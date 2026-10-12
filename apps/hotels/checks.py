"""Data-quality checks for hotel room rates.

A single mistyped rate becomes the hotel's advertised "from" price, because the
public card advertises min(Room.rate) across available rooms. These checks are
warnings rather than errors so they surface the problem without blocking a
deploy or a management command.
"""

from decimal import Decimal, InvalidOperation

from django.core.checks import Warning, register

# A rate below this share of the hotel's median rate is far more likely to be a
# dropped-zero typo (69 vs 6900) than a genuine bargain room.
OUTLIER_RATIO = Decimal('0.25')
MIN_ROOMS_FOR_OUTLIER_CHECK = 3


@register()
def room_rate_sanity(app_configs, **kwargs):
    from django.db import connection

    try:
        from hotels.models import Room
    except Exception:
        return []

    if connection.introspection.table_names() and \
            Room._meta.db_table not in connection.introspection.table_names():
        return []

    problems = []

    try:
        rooms = list(
            Room.objects.filter(status='AVAILABLE').values_list('id', 'hotel_id', 'rate')
        )
    except Exception:
        # The table does not exist yet (fresh database, or before the first
        # ``migrate``). There is nothing to inspect, and raising here would
        # break ``manage.py migrate`` / ``makemigrations`` on a new deployment.
        return []
    if not rooms:
        return []

    by_hotel = {}
    for room_id, hotel_id, rate in rooms:
        if rate <= 0:
            problems.append(Warning(
                'Room %s has a non-positive rate (%s), which cannot be charged.'
                % (room_id, rate),
                hint='Enter the nightly rate, or mark the room unavailable.',
                id='hotels.W002',
            ))
            continue
        by_hotel.setdefault(hotel_id, []).append((room_id, rate))

    for hotel_id, entries in by_hotel.items():
        if len(entries) < MIN_ROOMS_FOR_OUTLIER_CHECK:
            continue
        rates = sorted(rate for _, rate in entries)
        mid = len(rates) // 2
        median = rates[mid] if len(rates) % 2 else (rates[mid - 1] + rates[mid]) / 2
        if median <= 0:
            continue
        for room_id, rate in entries:
            if rate < median * OUTLIER_RATIO:
                problems.append(Warning(
                    'Room %s in hotel %s is priced at %s, far below that hotel\'s '
                    'median rate of %s. It will be advertised as the hotel\'s '
                    '"from" price.' % (room_id, hotel_id, rate, median),
                    hint='Confirm the rate is real and not a dropped-zero typo.',
                    id='hotels.W003',
                ))

    return problems
