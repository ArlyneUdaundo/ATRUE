"""Optional Duffel flight search (read-only; ATRUE owns all bookings)."""

import json
import logging
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class LiveFlightSearchError(Exception):
    """A provider configuration, network, or response error safe for the UI."""


def search_offers(origin, destination, departure_date, passengers=1,
                  return_date=None, cabin_class='economy', timeout=12):
    """Search Duffel offers, without ever creating an order or taking payment.

    Returns the provider offer payloads as-is so ATRUE can retain the provider's
    itinerary, exact currency and source identifiers for its local simulation.
    """
    token = os.getenv('DUFFEL_ACCESS_TOKEN', '').strip()
    mode = os.getenv('DUFFEL_MODE', 'test').strip().lower()
    if not token:
        raise LiveFlightSearchError('Duffel flight search is not configured.')
    if mode not in ('test', 'live'):
        raise LiveFlightSearchError(
            'Duffel mode must be either test or live.')
    if mode == 'test' and not token.startswith('duffel_test_'):
        raise LiveFlightSearchError(
            'Test mode requires a Duffel test token (duffel_test_...).')
    if mode == 'live' and token.startswith('duffel_test_'):
        raise LiveFlightSearchError(
            'A Duffel test token cannot be used in live mode.')
    if not (origin and destination and departure_date):
        return []

    slices = [{
        'origin': origin,
        'destination': destination,
        'departure_date': departure_date,
    }]
    if return_date:
        slices.append({
            'origin': destination,
            'destination': origin,
            'departure_date': return_date,
        })
    body = {
        'data': {
            'slices': slices,
            'passengers': [{'type': 'adult'} for _ in range(max(1, min(9, int(passengers))))],
            'cabin_class': cabin_class,
        }
    }
    request = Request(
        'https://api.duffel.com/air/offer_requests',
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Duffel-Version': 'v2',
        },
        method='POST',
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        logger.warning('Duffel flight search returned HTTP %s', exc.code)
        raise LiveFlightSearchError(
            'Live flight search is temporarily unavailable. Please try again.') from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning('Duffel flight search failed: %s', type(exc).__name__)
        raise LiveFlightSearchError(
            'Live flight search is temporarily unavailable. Please try again.') from exc
    return (payload.get('data') or {}).get('offers') or []


def offer_rows(offers, mode='test', limit=30):
    """Reduce Duffel payloads to safe, template-ready search result rows."""
    rows = []
    for offer in (offers or [])[:limit]:
        slices = offer.get('slices') or []
        segments = []
        for journey_number, slice_data in enumerate(slices, start=1):
            for segment in slice_data.get('segments') or []:
                origin = segment.get('origin') or {}
                destination = segment.get('destination') or {}
                operating = segment.get('operating_carrier') or {}
                marketing = segment.get('marketing_carrier') or operating
                segments.append({
                    'flight_number': segment.get('marketing_carrier_flight_number') or '',
                    'airline': marketing.get('name') or 'Airline',
                    'origin_code': origin.get('iata_code') or '',
                    'origin_name': origin.get('name') or '',
                    'destination_code': destination.get('iata_code') or '',
                    'destination_name': destination.get('name') or '',
                    'departing_at': segment.get('departing_at') or '',
                    'arriving_at': segment.get('arriving_at') or '',
                    'aircraft': (segment.get('aircraft') or {}).get('name') or '',
                    'journey_number': journey_number,
                })
        if not segments:
            continue
        amount = offer.get('total_amount') or offer.get('base_amount') or ''
        currency = offer.get('total_currency') or offer.get('base_currency') or ''
        try:
            # Duffel returns prices in the offer's source currency. Show a PHP
            # estimate for common currencies while retaining the exact quote.
            usd_php = Decimal(os.getenv('DUFFEL_USD_PHP_RATE', '63.01'))
            currency_rates = {'USD': usd_php, 'PHP': Decimal('1')}
            rate = currency_rates.get(currency)
            peso_price = (
                (Decimal(str(amount)) * rate).quantize(
                    Decimal('1'), rounding=ROUND_HALF_UP)
                if rate is not None and amount else None
            )
        except (InvalidOperation, TypeError, ValueError):
            peso_price = None
        owner = offer.get('owner') or {}
        raw_conditions = offer.get('conditions') or {}
        conditions = []
        if isinstance(raw_conditions, dict):
            for key, label in (
                ('change_before_departure', 'Changes before departure'),
                ('change_after_departure', 'Changes after departure'),
                ('refund_before_departure', 'Refund before departure'),
                ('refund_after_departure', 'Refund after departure'),
            ):
                detail = raw_conditions.get(key) or {}
                if detail.get('allowed') is True:
                    conditions.append(f'{label}: allowed')
                elif detail.get('allowed') is False:
                    conditions.append(f'{label}: not allowed')
                elif detail:
                    conditions.append(f'{label}: check provider rules')
        first_passengers = (
            (offer.get('slices') or [{}])[0]
            .get('segments', [{}])[0].get('passengers') or [{}]
        )
        cabin = first_passengers[0].get('cabin_class') or {}
        if isinstance(cabin, dict):
            cabin = cabin.get('name') or cabin.get('marketing_name') or ''
        baggage = []
        for passenger in first_passengers:
            for item in passenger.get('baggages') or []:
                quantity = item.get('quantity')
                label = item.get('type') or 'Baggage'
                baggage.append(f'{quantity} × {label}' if quantity is not None else label)
        rows.append({
            'id': offer.get('id') or '',
            'segments': segments,
            'airline': segments[0]['airline'],
            'price': amount,
            'currency': currency,
            'peso_price': peso_price,
            'owner': owner.get('name') or '',
            'cabin_class': cabin,
            'conditions': conditions,
            'baggage': baggage,
            'expires_at': offer.get('expires_at') or '',
            'stops': max(0, len(segments) - 1),
            'mode': mode,
            'payload': offer,
        })
    return rows
