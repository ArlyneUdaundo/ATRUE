"""Presentation helpers for the customer Rooms page (``hotels/group_select_rooms``).

This module is **display only**. It derives the richer room specification that
the Rooms page renders -- room size, bed type, an amenity grid, badges, a guest
score and the real price breakdown -- entirely from data ATRUE already stores
(``Room`` fields, ``Room.features`` / ``Room.description`` and the hotel's active
amenities / services).

Nothing here is imported by the booking pipeline. ``_create_hotel_booking``,
``BookingRoom.room_bill`` and every bill/payment record keep using
``Room.rate`` as the single authoritative nightly price, so booking, billing
and transaction behaviour are unchanged by the Rooms page redesign.

Why there is exactly one price per room
---------------------------------------
An earlier version of this page invented several "rate plans" per room (advance
purchase, breakfast included, saver...) and let the guest pick one. That was
removed because none of it was real:

* ``Room`` stores a single nightly rate, so every plan rendered the *same*
  price -- the "Compare offers" matrix was comparing identical numbers.
* AFTURE stores no rate-plan, cancellation-policy or breakfast record, so the
  promised terms ("free cancellation until 24h", "non-refundable after
  booking", "breakfast for 2 included") were claims the booking engine never
  enforced and could not honour.
* The chosen plan was never posted to the server, so picking "Pay in full now"
  did not actually pay anything: prepayment is decided solely by the booking
  form's own payment-method and pay-later controls.

The page now shows the single rate ATRUE will actually charge, plus the terms
it can genuinely stand behind. Real per-plan pricing would need a persisted
rate-plan model, which is a schema change and out of scope for this redesign.
"""

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.urls import reverse

# --------------------------------------------------------------------------
# Room specification
# --------------------------------------------------------------------------

SIZE_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:sq\.?\s?m\.?|m2|m²|square\s+met(?:re|er)s?|sqm)\b', re.I)
BED_RE = re.compile(
    r'(\d+)?\s*[-]?\s*'
    r'(queen|king|twin|single|double|bunk|sofa|day\s?bed|water\s?bed|mattress|crib)'
    r'\s*(?:beds?)?',
    re.I,
)
FEATURE_SPLIT_RE = re.compile(r'[,\n\r]+|;')

# Bed configuration implied by the room type when features say nothing.
BED_BY_ROOM_TYPE = {
    'SINGLE': '1 Single bed',
    'DOUBLE': '1 Double bed',
    'TWIN': '2 Twin beds',
    'DELUXE': '1 Queen bed',
    'SUITE': '1 King bed',
    'FAMILY': 'Bunk beds',
    'OTHER': '1 Double bed',
}

# Honest fallback when no floor area is recorded: a capacity band, not a
# fabricated square-metre figure.
SIZE_BAND_BY_ROOM_TYPE = {
    'SINGLE': 'Compact · sleeps 1',
    'DOUBLE': 'Standard · sleeps 2',
    'TWIN': 'Standard · sleeps 2',
    'DELUXE': 'Spacious · sleeps 3',
    'SUITE': 'Two-room · sleeps 4',
    'FAMILY': 'Family size · sleeps 6',
    'OTHER': 'Standard · sleeps 2',
}

DINING_HINTS = ('restaurant', 'cafe', 'café', 'buffet', 'lounge', 'dining', 'bar', 'kitchen')

AMENITY_ICONS = (
    ('wifi', 'fa-wifi'),
    ('wi-fi', 'fa-wifi'),
    ('internet', 'fa-wifi'),
    ('aircon', 'fa-snowflake'),
    ('air-con', 'fa-snowflake'),
    ('air conditioning', 'fa-snowflake'),
    ('aircon', 'fa-wind'),
    ('climate', 'fa-wind'),
    ('shower', 'fa-shower'),
    ('bathtub', 'fa-bath'),
    ('bath', 'fa-bath'),
    ('jacuzzi', 'fa-hot-tub'),
    ('tub', 'fa-bath'),
    ('toilet', 'fa-toilet'),
    ('tv', 'fa-tv'),
    ('television', 'fa-tv'),
    ('cable', 'fa-tv'),
    ('coffee', 'fa-mug-hot'),
    ('tea', 'fa-mug-hot'),
    ('mini bar', 'fa-glass-cheese'),
    ('minibar', 'fa-glass-cheese'),
    ('bar', 'fa-martini-glass'),
    ('restaurant', 'fa-utensils'),
    ('dining', 'fa-utensils'),
    ('breakfast', 'fa-utensils'),
    ('gym', 'fa-dumbbell'),
    ('fitness', 'fa-dumbbell'),
    ('pool', 'fa-swimming-pool'),
    ('swimming', 'fa-swimming-pool'),
    ('spa', 'fa-spa'),
    ('sauna', 'fa-hot-tub'),
    ('massage', 'fa-spa'),
    ('parking', 'fa-car'),
    ('valet', 'fa-car'),
    ('airport', 'fa-plane'),
    ('shuttle', 'fa-van-shuttle'),
    ('pickup', 'fa-van-shuttle'),
    ('laundry', 'fa-shirt'),
    ('workspace', 'fa-laptop'),
    ('desk', 'fa-laptop'),
    ('safe', 'fa-lock'),
    ('balcony', 'fa-door-open'),
    ('veranda', 'fa-door-open'),
    ('terrace', 'fa-sun'),
    ('view', 'fa-mountain-sun'),
    ('fireplace', 'fa-fire'),
    ('pet', 'fa-paw'),
    ('accessible', 'fa-wheelchair'),
    ('kitchen', 'fa-kitchen-set'),
    ('kitchenette', 'fa-kitchen-set'),
)


def _icon_for(label):
    low = label.lower()
    for needle, icon in AMENITY_ICONS:
        if needle in low:
            return icon
    return 'fa-circle-check'


def _decimal(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _peso(amount):
    return f'\u20b1{amount:,.0f}'


def split_features(text):
    """Split the stored free-text ``features``/``description`` blob into a list."""
    if not text:
        return []
    cleaned = str(text).replace('\u00a0', ' ')
    parts = [p.strip(' -\u2022\u2013\u2014\t') for p in FEATURE_SPLIT_RE.split(cleaned)]
    out, seen = [], set()
    for part in parts:
        low = part.lower()
        if not part or len(part) < 2 or low in seen:
            continue
        seen.add(low)
        out.append(part)
    return out


def room_size(room):
    """Recorded floor area (e.g. ``24 m²``) or a capacity band when unknown."""
    haystack = ' '.join([room.features or '', room.description or ''])
    match = SIZE_RE.search(haystack)
    if match:
        value = match.group(1)
        try:
            pretty = str(int(float(value)))
        except (TypeError, ValueError):
            pretty = value
        return {'value': f'{pretty} m²', 'is_measured': True}
    band = SIZE_BAND_BY_ROOM_TYPE.get(room.room_type, 'Standard')
    return {'value': band, 'is_measured': False}


def bed_type(room):
    """Normalised bed configuration from ``features``/``description``."""
    haystack = ' '.join([room.features or '', room.description or ''])
    match = BED_RE.search(haystack)
    if match:
        count = match.group(1)
        kind = re.sub(r'\s+', ' ', match.group(2).strip().lower())
        label = kind.capitalize()
        if kind == 'daybed':
            label = 'Day bed'
        elif kind == 'waterbed':
            label = 'Water bed'
        if count and int(count) > 1:
            return f'{int(count)} {label} beds'
        return f'{label} bed'
    return BED_BY_ROOM_TYPE.get(room.room_type, '1 Double bed')


def guest_score(room, amenity_count):
    """ATrUE Guest Score: a transparent 10-point rating computed from real data.

    ATRUE stores no review table, so instead of inventing review counts this
    scores the room on signals ATRUE actually holds -- how much is documented
    (photos, features, hotel amenities) and how much room you get per peso.
    The UI labels it "ATrUE Guest Score" and shows the basis, so it is never
    mistaken for aggregated guest reviews.
    """
    photo_points = min(2.0, len(list(room.photos.all())) * 0.5)
    feature_points = min(3.0, len(split_features(room.features)) * 0.5)
    amenity_points = min(2.0, amenity_count * 0.4)
    space_points = 1.0 if room.maximum_capacity >= 3 else 0.5
    rate = _decimal(room.rate)
    per_guest = rate / max(1, room.maximum_capacity)
    value_points = 2.0 if per_guest <= 2500 else 1.5 if per_guest <= 4000 else 1.0
    score = round(photo_points + feature_points + amenity_points + space_points + value_points, 1)
    score = max(5.0, min(9.9, score))
    if score >= 9.0:
        label = 'Exceptional'
    elif score >= 7.5:
        label = 'Very good'
    elif score >= 6.5:
        label = 'Good'
    else:
        label = 'Pleasant'
    return {
        'score': score,
        'scale': 10,
        'label': label,
        'basis': 'Amenities, photos, features & value',
    }


def room_amenities(room, hotel_amenities, hotel_services, limit=10):
    """De-duplicated amenity grid built from room features + hotel offerings."""
    items, seen = [], set()
    for label in split_features(room.features)[:limit]:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({'label': label, 'icon': _icon_for(label), 'source': 'room'})
    extra = 0
    for label in [a.name for a in hotel_amenities] + [s.name for s in hotel_services]:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({'label': label, 'icon': _icon_for(label), 'source': 'hotel'})
        extra += 1
        if len(items) >= limit + 4:
            break
    return items, extra


def hotel_has_dining(amenities):
    return any(hint in (a.name or '').lower() for a in amenities for hint in DINING_HINTS)


def build_rate(room, nights):
    """The one price ATRUE will actually charge for this room.

    Mirrors ``_create_hotel_booking`` exactly: ``Room.rate`` per night, plus the
    room's real ``additional_guest_charge`` for guests beyond its standard
    capacity. No discounts, no plan-specific terms, nothing the billing code
    would not honour.
    """
    nights = max(1, int(nights or 1))
    rate = _decimal(room.rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = (rate * nights).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    extra = _decimal(room.additional_guest_charge).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {
        'rate': rate,
        'nights': nights,
        'total': total,
        'extra_guest_charge': extra,
        'rate_amount': f'{rate:,.0f}',
        'total_amount': f'{total:,.0f}',
        'rate_display': _peso(rate),
        'total_display': _peso(total),
        'extra_display': _peso(extra),
        'has_extra': extra > 0,
    }


def room_badges(room, is_recommended, bookable_siblings, has_dining):
    """Highlight chips shown above the room name.

    Every badge is a fact ATRUE can verify from its own data -- no "free
    cancellation" or "lowest rate" style promises.
    """
    badges = []
    if is_recommended:
        badges.append({'label': 'Recommended', 'icon': 'fa-star', 'tone': 'brand'})
    if bookable_siblings <= 1 and room.status == 'AVAILABLE':
        badges.append({'label': 'Last room left', 'icon': 'fa-fire', 'tone': 'urgent'})
    if has_dining:
        badges.append({'label': 'On-site dining', 'icon': 'fa-utensils', 'tone': 'amber'})
    return badges


def build_room_cards(rooms, bookable_flags, hotel_amenities, hotel_services, nights):
    """Assemble everything the Rooms page needs for each room card.

    ``bookable_flags`` maps room id -> whether it can be booked for the chosen
    dates. ``rooms`` must already carry ``photos`` (prefetched).
    """
    amenities = list(hotel_amenities)
    services = list(hotel_services)
    has_dining = hotel_has_dining(amenities)

    same_type = {}
    for room in rooms:
        if bookable_flags.get(room.id):
            same_type.setdefault(room.room_type, []).append(room)

    # Everything derived per room is computed once and reused.
    derived = {}
    for room in rooms:
        amenity_items, hotel_extra = room_amenities(room, amenities, services)
        derived[room.id] = {
            'amenities': amenity_items[:10],
            'amenities_extra': max(0, len(amenity_items) - 10) + hotel_extra,
            'score': guest_score(room, len(amenity_items)),
            'rate': build_rate(room, nights),
        }

    # "Recommended" is the best-scoring bookable room, with the most expensive
    # room of a type winning ties -- mirrors how OTAs surface a flagship room.
    best_id = None
    candidates = [r for r in rooms if bookable_flags.get(r.id)]
    if candidates:
        best_id = max(
            candidates,
            key=lambda r: (derived[r.id]['score']['score'], _decimal(r.rate)),
        ).id

    cards = []
    for room in rooms:
        info = derived[room.id]
        cards.append({
            'room': room,
            'name': f"{room.get_room_type_display()} Room",
            'display_status': '',
            'bookable': bool(bookable_flags.get(room.id)),
            'size': room_size(room),
            'bed': bed_type(room),
            'max_guests': room.maximum_capacity,
            'sleeps': f"{room.capacity_adults} adult{room.capacity_adults == 1 and '' or 's'}, "
                      f"{room.capacity_children} child{room.capacity_children == 1 and '' or 'ren'}",
            'score': info['score'],
            'amenities': info['amenities'],
            'amenities_extra': info['amenities_extra'],
            'badges': room_badges(
                room, room.id == best_id, len(same_type.get(room.room_type, [])), has_dining
            ),
            'rate': info['rate'],
            'max_rooms': len(same_type.get(room.room_type, [])),
            'description': room.description or '',
            'photos': list(room.photos.all()),
        })
    return cards


def compare_rooms(cards, nights):
    """Flat rows for the "Compare rooms" matrix.

    Compares the rooms ATRUE actually has -- their real rate, size, bed,
    capacity and score. The cheapest bookable room is flagged.
    """
    rows = []
    for card in cards:
        if not card['bookable']:
            continue
        rate = card['rate']
        rows.append({
            'room_id': card['room'].id,
            'room_number': card['room'].room_number,
            'name': card['name'],
            'size': card['size']['value'],
            'bed': card['bed'],
            'max_guests': card['max_guests'],
            'score': card['score']['score'],
            'score_label': card['score']['label'],
            'rate_value': rate['rate'],
            'rate_display': rate['rate_display'],
            'total_display': rate['total_display'],
            'nights': nights,
            'extra_display': rate['extra_display'],
            'has_extra': rate['has_extra'],
            'is_cheapest': False,
        })
    if rows:
        cheapest = min(rows, key=lambda r: r['rate_value'])
        cheapest['is_cheapest'] = True
    return rows


def details_payload(cards, hotel, room_detail_url_name, check_in, check_out):
    """JSON-serialisable snapshot per room, used by the "Photos & details" modal."""
    payload = {}
    for card in cards:
        room = card['room']
        rate = card['rate']
        payload[str(room.id)] = {
            'name': card['name'],
            'room_number': room.room_number,
            'room_id': room.room_id,
            'status': card['display_status'],
            'bookable': card['bookable'],
            'size': card['size']['value'],
            'bed': card['bed'],
            'sleeps': card['sleeps'],
            'max_guests': card['max_guests'],
            'rate': str(room.rate),
            'total': str(rate['total']),
            'rate_display': rate['rate_display'],
            'total_display': rate['total_display'],
            'nights': rate['nights'],
            'extra_guest_charge': str(room.additional_guest_charge),
            'has_extra': rate['has_extra'],
            'description': room.description or '',
            'features': split_features(room.features),
            'amenities': [a['label'] for a in card['amenities']],
            'score': card['score']['score'],
            'score_label': card['score']['label'],
            'score_basis': card['score']['basis'],
            'badges': [b['label'] for b in card['badges']],
            'photos': [p.image.url for p in card['photos']],
            'hotel_name': hotel.name,
            'hotel_location': hotel.location,
            'detail_url': reverse(
                room_detail_url_name, args=[room.id]
            ) + '?' + f'check_in={check_in.isoformat()}&check_out={check_out.isoformat()}',
        }
    return payload
