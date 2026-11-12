"""Age-based passenger classification and airline fare-rule calculations."""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal('0.00')
CENT = Decimal('0.01')


def age_on_date(date_of_birth, travel_date):
    if not date_of_birth or not travel_date or date_of_birth > travel_date:
        raise ValueError('Passenger date of birth must be on or before the travel date.')
    return travel_date.year - date_of_birth.year - (
        (travel_date.month, travel_date.day)
        < (date_of_birth.month, date_of_birth.day))


def category_for_age(age):
    if age < 0:
        raise ValueError('Passenger age cannot be negative.')
    if age < 2:
        return 'infant'
    if age < 12:
        return 'child'
    return 'adult'


def fare_rules_for_legs(legs):
    rules = {}
    for leg in legs:
        if leg.airline_id not in rules:
            rules[leg.airline_id], _created = AirlineFareRule.objects.get_or_create(
                airline_id=leg.airline_id)
    return rules


def quote_passenger_legs(legs, rules_by_airline, category, infant_option, fare_class):
    """Return rounded category fares and per-leg persisted pricing snapshots."""
    fare_key = {
        'adult': 'adult_fare_percent',
        'child': 'child_fare_percent',
        'infant': 'infant_seat_fare_percent',
    }[category]
    percent = Decimal('100')
    total = {'fare': ZERO, 'tax': ZERO, 'fee': ZERO, 'infant_fee': ZERO}
    leg_quotes = []
    for leg in legs:
        rule = rules_by_airline[leg.airline_id]
        cabin_fare = Decimal(leg.fare_for(fare_class) or 0)
        is_lap_infant = category == 'infant' and infant_option == 'lap'
        passenger_fare = ZERO if is_lap_infant else money(
            cabin_fare * Decimal(getattr(rule, fare_key)) / Decimal('100'))
        tax = money(passenger_fare * Decimal(rule.tax_percent) / Decimal('100'))
        fee = money(rule.additional_passenger_fee)
        infant_fee = money(rule.infant_lap_fee) if is_lap_infant else ZERO
        quote = {
            'fare': passenger_fare,
            'tax': tax,
            'fee': fee,
            'infant_fee': infant_fee,
        }
        leg_quotes.append(quote)
        for key in total:
            total[key] += quote[key]
    return total, leg_quotes


def money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def category_pricing(legs, rules_by_airline, fare_class, itinerary_fee=ZERO):
    """Prepare browser-safe per-category prices from the selected flight legs."""
    result = {}
    for category in ('adult', 'child', 'infant'):
        option = 'lap' if category == 'infant' else 'seat'
        total, _quotes = quote_passenger_legs(
            legs, rules_by_airline, category, option, fare_class)
        if category == 'infant':
            seated, _quotes = quote_passenger_legs(
                legs, rules_by_airline, category, 'seat', fare_class)
            total['seat_fare'] = seated['fare']
            total['seat_tax'] = seated['tax']
            total['seat_fee'] = seated['fee']
        else:
            total['seat_fare'] = total['fare']
            total['seat_tax'] = total['tax']
            total['seat_fee'] = total['fee']
        total['fee'] = total['fee'] + money(itinerary_fee)
        total['rules_configured'] = all(
            rules_by_airline[leg.airline_id].is_configured for leg in legs)
        result[category] = {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in total.items()
        }
    return result
