"""Shared establishment selection flow for the non-hotel categories.

Why this module exists
======================
The Hotel flow is the reference implementation of the ATRUE establishment
journey (browse -> search -> establishment detail -> selectable items ->
live booking panel -> guest information -> optional services/amenities ->
computation -> final action).  It lives in ``apps/hotels`` and is NOT touched
by this module.

The remaining six categories (Resorts, Staycations, Restaurants, Tour
Packages, Landmarks, Activities) previously each had their own unrelated
single-item ``book.html`` page, and Landmarks / Activities had no detail
page at all.  This module gives them the SAME interaction structure.

Two rules govern everything here
--------------------------------
1. **No invented data.**  Every value rendered comes from a field the
   category already stores.  Where a category has no concept of something the
   Hotel flow shows (a nightly rate, amenities, a per-item number), the
   template omits that block rather than fabricating a value.  Specifically:

   * ``Table`` and ``Restaurant`` have no rate field at all, so Restaurants
     render "Contact establishment for pricing" instead of a peso figure.
   * Only ``hotels`` has an ``Amenity`` model, so the amenities block renders
     for Hotels alone.
   * ``Service`` models exist for Hotels, Resorts and Staycations only, so
     optional services render for those three.
   * Staycations, Landmarks and Tour Packages have no per-item model, so the
     establishment itself is presented as the single selectable item using
     its own stored rate / entry fee / price.

2. **No schema changes.**  Nothing here adds a model, field or migration.
   Booking creation writes to each category's existing booking model.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from atrue_core.payment_methods import PAYMENT_METHOD_CHOICES

import logging

from django.urls import reverse

logger = logging.getLogger(__name__)


# Reuse the Hotels presentation helpers rather than duplicating the icon
# table and the free-text feature splitter.
from hotels.room_offers import _icon_for, split_features

from atrue_core.services import (
    create_bill, log_activity, record_payment, record_transaction,
)


# ---------------------------------------------------------------------------
# Small numeric / display helpers
# ---------------------------------------------------------------------------

CONTACT_DIGITS_RE = None  # populated lazily to avoid an import cycle cost


def dec(value):
    """Coerce anything to Decimal without raising."""
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def money(amount):
    """Peso string for a charge amount. Missing values never render as 'PHP None'."""
    if amount is None or amount == '':
        return 'Price unavailable'
    return f'\u20b1{dec(amount):,.0f}'


def price_text(amount, free_when_zero=False):
    """Display a price with explicit free / unavailable states.

    ``money()`` reports a zero charge as PHP 0, which reads like a real price.
    This distinguishes a genuinely free item (landmark entry_fee) from one that
    simply has no rate set.
    """
    if amount is None or amount == '':
        return 'Price unavailable'
    value = dec(amount)
    if value <= 0:
        return 'Free' if free_when_zero else 'Price unavailable'
    return f'\u20b1{value:,.0f}'


def q2(amount):
    return dec(amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def empty_guest():
    return {
        'first_name': '', 'middle_name': '', 'last_name': '',
        'email': '', 'contact': '', 'adults': 1, 'children': 0,
        'special_request': '', 'services': [], 'amenities': [],
    }


def guest_defaults(count):
    return [empty_guest() for _ in range(count)]


# ---------------------------------------------------------------------------
# Normalised shapes
# ---------------------------------------------------------------------------
#
# ``item`` dicts intentionally mirror the key names the Hotels room-card
# builder produces, so one shared template can render a hotel room, a resort
# villa, a restaurant table and a landmark identically.
#
#   id               int    primary key of the selectable item
#   name             str    human name, e.g. "Deluxe Room"
#   number           str    the per-item identifier, e.g. "Room 203"
#   display_status   str    Available / Reserved / In Use / Under Maintenance
#   bookable         bool
#   facts            [(icon, value, label)]   the three-up fact strip
#   amenities        [{label, icon}]
#   amenities_extra  int
#   badges           [{label, icon, tone}]
#   score            {score, scale, label, basis}
#   rate             dict | None   None when the category stores no price
#   photos           [photo objects with .image.url]
#   description      str
#   obj              the model instance


def _score_from(photo_count, feature_count, amenity_count, max_guests, rate, basis):
    """ATrUE Guest Score, computed the same transparent way as Hotels.

    ATRUE stores no review table, so the score is derived only from signals
    ATRUE actually holds.  The basis string is always passed through to the
    UI so it is never mistaken for aggregated guest reviews.
    """
    photo_points = min(2.0, photo_count * 0.5)
    feature_points = min(3.0, feature_count * 0.5)
    amenity_points = min(2.0, amenity_count * 0.4)
    space_points = 1.0 if (max_guests or 0) >= 3 else 0.5
    per_guest = dec(rate) / max(1, int(max_guests or 1))
    value_points = 2.0 if per_guest <= 2500 else 1.5 if per_guest <= 4000 else 1.0
    if not dec(rate):
        # No stored price (Restaurants): value cannot be scored honestly, so
        # it is dropped and the basis says so.
        score = photo_points + feature_points + amenity_points + space_points
        basis = 'Photos, features & space (no rate on file)'
    else:
        score = photo_points + feature_points + amenity_points + space_points + value_points
    score = max(5.0, min(9.9, round(score, 1)))
    if score >= 9.0:
        label = 'Exceptional'
    elif score >= 7.5:
        label = 'Very good'
    elif score >= 6.5:
        label = 'Good'
    else:
        label = 'Pleasant'
    return {'score': score, 'scale': 10, 'label': label, 'basis': basis}


def _badges(is_recommended, siblings_available, status):
    badges = []
    if is_recommended:
        badges.append({'label': 'Recommended', 'icon': 'fa-star', 'tone': 'brand'})
    if siblings_available <= 1 and status == 'AVAILABLE':
        badges.append({'label': f'Last one left', 'icon': 'fa-fire', 'tone': 'urgent'})
    return badges


def _amenity_grid(labels, limit=10):
    items, seen = [], set()
    for label in labels:
        key = (label or '').strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        items.append({'label': label.strip(), 'icon': _icon_for(label)})
    return items[:limit], max(0, len(items) - limit)


def _rate_block(rate_value, nights, unit_noun, extra_charge=0, extra_label=None):
    """The one price ATRUE will actually charge, mirroring ``room_offers.build_rate``."""
    nights = max(1, int(nights or 1))
    rate = q2(rate_value)
    total = q2(rate * nights)
    extra = q2(extra_charge)
    return {
        'rate': rate,
        'nights': nights,
        'total': total,
        'extra_charge': extra,
        'unit_noun': unit_noun,
        'extra_label': extra_label or 'extra guest',
        'rate_amount': f'{rate:,.0f}',
        'total_amount': f'{total:,.0f}',
        'rate_display': money(rate),
        'total_display': money(total),
        'extra_display': money(extra),
        'has_extra': extra > 0,
        'rate_is_free': rate <= 0,
    }


def _inclusions(item, est, adapter, max_guests, rate_block, nights):
    """The 'Includes' bullet list, built only from what the category stores."""
    perks = []
    perks.append({'icon': 'fa-wallet', 'text': 'Pay online now or pay when you arrive'})
    if max_guests:
        perks.append({
            'icon': 'fa-user-group',
            'text': f'{max_guests} guest{max_guests == 1 and "" or "s"} maximum',
        })
    if rate_block and rate_block['has_extra']:
        perks.append({
            'icon': 'fa-plus',
            'text': f"{rate_block['extra_display']} per {rate_block['extra_label']}, per {rate_block['unit_noun']}",
        })
    for extra in adapter.extra_inclusions(est, item):
        perks.append(extra)
    return perks


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class BaseAdapter:
    """One establishment category, expressed in the normalised item shape.

    Subclasses fill in the category's real vocabulary (what a bookable thing
    is called, how it is priced, what can be attached to it) so the shared
    template never has to hard-code a single category.
    """

    key = ''
    label = ''
    singular = ''
    item_noun = ''
    item_noun_plural = ''
    # Badge text in the guest-information card header (Hotels uses ROOM).
    item_badge = 'ITEM'
    # Heading above the item charges in the booking computation
    # (the Hotels page says "Room charges x N nights").
    charge_section = 'Item charges'
    icon = 'fa-building'
    # 'night' for lodging, otherwise the noun a single booking covers.
    unit_noun = 'night'
    duration_noun = 'Nights'
    price_missing_note = ''
    lodging = False
    date_label = 'Check-in'
    end_date_label = 'Check-out'
    show_time = False
    time_label = 'Time'
    # False when going over max_guests is legal and priced (Tour Packages bill
    # extra_person_rate instead of refusing the booking).
    enforce_capacity = True
    # Extra per-guest text inputs this category's booking model stores.
    guest_extra_fields = ()

    # -- overridable defaults -----------------------------------------------
    def default_date(self, est, fallback):
        """A sensible first date for this category (packages use validity)."""
        return fallback

    def extras(self, est):
        """Optional item-level choices backed by real stored rates."""
        return []


    # -- identity -----------------------------------------------------------
    def get_est(self, pk):
        raise NotImplementedError

    def est_name(self, est):
        return est.name

    def est_location(self, est):
        return getattr(est, 'location', '') or ''

    # -- urls ---------------------------------------------------------------
    def list_url(self):
        raise NotImplementedError

    def detail_url(self, est):
        raise NotImplementedError

    def select_url(self, est):
        raise NotImplementedError

    def booking_detail_url(self, booking):
        raise NotImplementedError

    # -- dates --------------------------------------------------------------
    def nights_for(self, check_in, check_out):
        if not self.lodging:
            return 1
        return max(1, (check_out - check_in).days)

    # -- items --------------------------------------------------------------
    def items(self, est, check_in, check_out, nights):
        raise NotImplementedError

    def services(self, est):
        return []

    def amenities(self, est):
        return []

    def extra_inclusions(self, est, item):
        return []

    def charge_plan(self, rate_value, unit_noun, included, max_guests,
                    extra_rate=0, mode='flat', extra_mode='none',
                    extra_label='Extra guest'):
        """How this item is charged, described in a form the shared
        ``establishment_select.js`` computation can mirror exactly.

        ``mode`` multiplies the base rate:
            ``nights`` -> rate x nights      (Resorts, Staycations)
            ``guests`` -> rate x guests      (Landmarks, Tour Packages,
                                            per-person Activities)
            ``flat``   -> rate x 1           (Tables, per-group Activities)
        ``extra_mode`` applies the same multipliers to guests beyond
        ``included``: ``nights`` or ``guests``, or ``none``.

        The server stays authoritative -- ``build_booking`` computes the real
        bill -- but the browser must show the same arithmetic live, so both
        read this one description.
        """
        return {
            'mode': mode,
            'rate': str(q2(dec(rate_value))),
            'unit_noun': unit_noun,
            'included': int(included or 0),
            'max_guests': int(max_guests or 1),
            'extra_rate': str(q2(dec(extra_rate))),
            'extra_mode': extra_mode,
            'extra_label': extra_label,
        }

    # -- booking ------------------------------------------------------------
    def build_booking(self, user, est, selections, ctx):
        raise NotImplementedError

    # -- shared assembly ----------------------------------------------------
    def build_cards(self, est, check_in, check_out):
        """Normalised item cards plus everything the shared template needs."""
        nights = self.nights_for(check_in, check_out)
        raw = self.items(est, check_in, check_out, nights)
        amenities = self.amenities(est)
        service_rows = self.services(est)
        amenity_labels = [a['name'] for a in amenities] + [s['name'] for s in service_rows]

        # Score every item first, then flag the strongest one as Recommended.
        for r in raw:
            r['score'] = _score_from(
                len(r['photos']), len(r.get('feature_labels', [])),
                len(amenities) + len(service_rows),
                r['max_guests'], r['_rate_value'],
                'Photos, features, amenities & rate',
            )
        best = None
        bookable = [r for r in raw if r['bookable']]
        if bookable:
            best = max(bookable, key=lambda r: (r['score']['score'], r['_rate_value']))

        cards = []
        for r in raw:
            labels = list(r.get('feature_labels', [])) + amenity_labels
            grid, extra = _amenity_grid(labels)
            card = {
                'id': r['id'],
                'name': r['name'],
                'number': r['number'],
                'max_guests': r['max_guests'],
                'sleeps': r['sleeps'],
                'display_status': r['display_status'],
                'bookable': r['bookable'],
                'facts': r['facts'],
                'amenities': grid,
                'amenities_extra': extra,
                'badges': _badges(r['id'] == (best['id'] if best else None),
                                  r.get('siblings_available', 1), r['raw_status']),
                'score': r['score'],
                'rate': r['rate'],
                'photos': r['photos'],
                'description': r.get('description', ''),
                'includes': _inclusions(r, est, self, r['max_guests'], r['rate'], nights),
                'price_missing_note': self.price_missing_note,
                'features': r.get('feature_labels', []),
                'charge': r.get('charge') or self.charge_plan(0, '', 0, r['max_guests']),
            }
            card['details'] = {
                'name': r['name'],
                'number': r['number'],
                'status': r['display_status'],
                'bookable': r['bookable'],
                'max_guests': r['max_guests'],
                'sleeps': r['sleeps'],
                'facts': r['facts'],
                'rate_display': r['rate']['rate_display'] if r['rate'] else '',
                'total_display': r['rate']['total_display'] if r['rate'] else '',
                'unit_noun': r['rate']['unit_noun'] if r['rate'] else '',
                'description': r.get('description', ''),
                'features': r.get('feature_labels', []),
                'amenities': [a['label'] for a in grid],
                'score': r['score']['score'],
                'score_label': r['score']['label'],
                'score_basis': r['score']['basis'],
                'badges': [b['label'] for b in card['badges']],
                'photos': [p.image.url for p in r['photos']],
                'est_name': self.est_name(est),
                'est_location': self.est_location(est),
                'detail_url': self.detail_url(est),
            }
            cards.append(card)
        return cards, nights, service_rows, amenity_rows(amenities)

    def item_meta(self, est, cards, selected):
        """``roomsMeta`` equivalent, keyed by item id."""
        meta = {}
        for card in cards:
            rate = card['rate']
            meta[str(card['id'])] = {
                'number': card['number'],
                'name': card['name'],
                'rate': str(rate['rate']) if rate else '0',
                'total': str(rate['total']) if rate else '0',
                'unit_noun': rate['unit_noun'] if rate else '',
                'max_guests': card['max_guests'] or 1,
                'bookable': card['bookable'],
                'status': card['display_status'],
                'charge': card['charge'],
            }
        return meta



def amenity_rows(amenities):
    return [{'id': str(a['id']), 'name': a['name']} for a in amenities]

# ---------------------------------------------------------------------------
# Resorts -- bookable items are the resort's own villas / units.
# ---------------------------------------------------------------------------


class ResortAdapter(BaseAdapter):
    key = 'resort'
    label = 'Resorts'
    singular = 'Resort'
    item_noun = 'Villa'
    item_noun_plural = 'Villas'
    item_badge = 'VILLA'
    charge_section = 'Villa charges'
    icon = 'fa-umbrella-beach'
    unit_noun = 'night'
    duration_noun = 'Nights'
    lodging = True

    def get_est(self, pk):
        from resorts.models import Resort
        return Resort.objects.filter(status=Resort.Status.ACTIVE).prefetch_related(
            'units__photos', 'services'
        ).get(pk=pk)

    def list_url(self):
        return reverse('resorts:list')

    def detail_url(self, est):
        return reverse('resorts:detail', args=[est.slug])

    def select_url(self, est):
        return reverse('resorts:group_start', args=[est.pk])

    def booking_detail_url(self, booking):
        return reverse('resorts:booking_detail', args=[booking.pk])

    def services(self, est):
        from resorts.models import Service
        return [
            {'id': s.id, 'name': s.name, 'rate': str(s.rate)}
            for s in est.services.filter(status=Service.ServiceStatus.ACTIVE)
        ]

    def items(self, est, check_in, check_out, nights):
        from resorts.models import Reservation, RoomVilla
        from atrue_core.services import overlapping_booking_exists

        units = list(est.units.all())
        # Count first so every card sees the same "how many are left" number.
        available = 0
        for unit in units:
            if unit.status == RoomVilla.Status.AVAILABLE and not overlapping_booking_exists(
                Reservation, resource_field='unit', resource=unit,
                start=check_in, end=check_out,
            ):
                available += 1
        rows = []
        for unit in units:
            if unit.status == RoomVilla.Status.AVAILABLE and not overlapping_booking_exists(
                Reservation, resource_field='unit', resource=unit,
                start=check_in, end=check_out,
            ):
                status, bookable = 'Available', True
            elif unit.status == RoomVilla.Status.MAINTENANCE:
                status, bookable = 'Under Maintenance', False
            elif unit.status == RoomVilla.Status.OCCUPIED:
                status, bookable = 'In Use', False
            else:
                status, bookable = 'Reserved', False
            capacity = unit.capacity
            features = split_features(unit.features) or split_features(unit.description)
            rows.append({
                'id': unit.id,
                'obj': unit,
                'name': f'{unit.get_unit_type_display()} {unit.unit_number}',
                'number': f'Unit {unit.unit_number}',
                'display_status': status,
                'raw_status': unit.status,
                'bookable': bookable,
                'facts': [
                    ('fa-users', capacity, 'Guests'),
                    ('fa-umbrella-beach', unit.get_unit_type_display(), 'Unit type'),
                    ('fa-user-group', capacity, 'Max guests'),
                ],
                'max_guests': capacity,
                'sleeps': f'{unit.capacity_adults} adult(s), {unit.capacity_children} child(ren)',
                'feature_labels': features,
                'photos': list(unit.photos.all()),
                'rate': _rate_block(unit.rate, nights, 'night', unit.additional_guest_charge),
                'charge': self.charge_plan(
                    unit.rate, 'night', capacity, capacity,
                    extra_rate=unit.additional_guest_charge,
                    mode='nights', extra_mode='nights',
                    extra_label='Additional guest',
                ),
                '_rate_value': dec(unit.rate),
                'siblings_available': available,
                'description': unit.description or '',
            })
        return rows

    def build_booking(self, user, est, selections, ctx):
        from resorts.models import Reservation, RoomVilla, Service
        from django.db import transaction as db_transaction

        check_in, check_out, nights = ctx['check_in'], ctx['check_out'], ctx['nights']
        try:
            with db_transaction.atomic():
                for sel in selections:
                    unit = RoomVilla.objects.select_for_update().get(pk=sel['card']['id'])
                    if unit.status != RoomVilla.Status.AVAILABLE or unit.resort_id != est.pk:
                        raise ValueError(f'Villa {unit.unit_number} is no longer available.')
                payer = selections[0]['guest']
                booking = Reservation.objects.create(
                    customer=user,
                    unit=RoomVilla.objects.get(pk=selections[0]['card']['id']),
                    number_of_units=len(selections),
                    check_in=check_in,
                    check_out=check_out,
                    number_of_adults=sum(max(0, int(s['guest']['adults'])) for s in selections),
                    number_of_children=sum(max(0, int(s['guest']['children'])) for s in selections),
                    payer_name=f"{payer['first_name']} {payer['last_name']}".strip(),
                    payer_contact=payer['contact'],
                    special_requests='; '.join(
                        s['guest']['special_request'] for s in selections
                        if s['guest'].get('special_request')
                    ),
                )
                bill_items = []
                svc_map = {s.id: s for s in est.services.filter(status=Service.ServiceStatus.ACTIVE)}
                for idx, sel in enumerate(selections, start=1):
                    unit = RoomVilla.objects.get(pk=sel['card']['id'])
                    card = sel['card']
                    guests = max(0, int(sel['guest']['adults'])) + max(0, int(sel['guest']['children']))
                    extra = max(0, guests - card['max_guests'])
                    base = q2(card['rate']['rate']) if card['rate'] else Decimal('0')
                    total = q2(base * nights)
                    bill_items.append({
                        'label': card['name'],
                        'description': f'{card["number"]} x {nights} night(s)',
                        'quantity': nights, 'rate': base, 'amount': total,
                    })
                    if extra and card['rate'] and card['rate']['extra_charge']:
                        extra_total = q2(card['rate']['extra_charge'] * extra * nights)
                        bill_items.append({
                            'label': 'Additional guest charge',
                            'description': f'{card["number"]}: {extra} extra guest(s) x {nights} night(s)',
                            'quantity': extra * nights, 'rate': card['rate']['extra_charge'],
                            'amount': extra_total,
                        })
                        total += extra_total
                    picked = [svc_map[i] for i in sel['guest'].get('services', []) if i in svc_map]
                    if picked:
                        booking.services.add(*picked)
                        for svc in picked:
                            bill_items.append({
                                'label': svc.name,
                                'description': f'{card["number"]} resort service',
                                'quantity': 1, 'rate': q2(svc.rate), 'amount': q2(svc.rate),
                            })
                            total += q2(svc.rate)
                return booking, bill_items, None
        except ValueError as exc:
            return None, [], str(exc)
        except Exception:
            # Never swallow a real failure silently: the generic message is for
            # the customer, the traceback goes to the log.
            logger.exception('establishment flow: %s booking could not be created', self.key)
            return None, [], 'We could not complete this booking. Please try again.'


# ---------------------------------------------------------------------------
# Staycations -- no per-item model exists, so the staycation itself is the
# single selectable item, priced from Staycation.rate.
# ---------------------------------------------------------------------------


class StaycationAdapter(BaseAdapter):
    key = 'staycation'
    label = 'Staycations'
    singular = 'Staycation'
    item_noun = 'Stay'
    item_noun_plural = 'Stays'
    item_badge = 'STAY'
    charge_section = 'Stay charges'
    icon = 'fa-couch'
    unit_noun = 'night'
    duration_noun = 'Nights'
    lodging = True

    def get_est(self, pk):
        from staycations.models import Staycation
        return Staycation.objects.filter(status=Staycation.Status.ACTIVE).prefetch_related(
            'photos', 'services', 'blocked_dates'
        ).get(pk=pk)

    def list_url(self):
        return reverse('staycations:list')

    def detail_url(self, est):
        return reverse('staycations:detail', args=[est.slug])

    def select_url(self, est):
        return reverse('staycations:flow_select', args=[est.pk])

    def booking_detail_url(self, booking):
        return reverse('staycations:booking_detail', args=[booking.pk])

    def services(self, est):
        from staycations.models import Service
        return [
            {'id': s.id, 'name': s.name, 'rate': str(s.rate)}
            for s in est.services.filter(status=Service.ServiceStatus.ACTIVE)
        ]

    def extra_inclusions(self, est, item):
        out = []
        rules = [ln.strip() for ln in (est.house_rules or '').splitlines() if ln.strip()]
        if rules:
            out.append({'icon': 'fa-clipboard-list', 'text': rules[0]})
        return out

    def is_blocked(self, est, check_in, check_out):
        for block in est.blocked_dates.all():
            if block.start_date < check_out and block.end_date > check_in:
                return True
        return False

    def items(self, est, check_in, check_out, nights):
        blocked = self.is_blocked(est, check_in, check_out)
        if blocked:
            status, bookable = 'Reserved', False
        elif est.status != 'ACTIVE':
            status, bookable = 'In Use', False
        else:
            status, bookable = 'Available', True
        capacity = est.capacity or (est.capacity_adults + est.capacity_children) or 1
        features = split_features(est.house_rules)
        return [{
            'id': est.pk,
            'obj': est,
            'name': est.name,
            'number': f'Staycation {getattr(est, "establishment_id", "") or est.pk}',
            'display_status': status,
            'raw_status': est.status,
            'bookable': bookable,
            'facts': [
                ('fa-users', capacity, 'Guests'),
                ('fa-door-open', 'Entire home', 'Space'),
                ('fa-user-group', est.capacity_adults + est.capacity_children or capacity, 'Max guests'),
            ],
            'max_guests': capacity,
            'sleeps': f'{est.capacity_adults} adult(s), {est.capacity_children} child(ren)',
            'feature_labels': features,
            'photos': list(est.photos.all()),
            'rate': _rate_block(est.rate, nights, 'night'),
            'charge': self.charge_plan(
                est.rate, 'night', capacity, capacity,
                mode='nights', extra_mode='none',
            ),
            '_rate_value': dec(est.rate),
            'siblings_available': 1 if bookable else 0,
            'description': '',
        }]

    def build_booking(self, user, est, selections, ctx):
        from staycations.models import Reservation, Service
        from django.db import transaction as db_transaction

        check_in, check_out, nights = ctx['check_in'], ctx['check_out'], ctx['nights']
        try:
            with db_transaction.atomic():
                if self.is_blocked(est, check_in, check_out):
                    raise ValueError('Those dates are blocked for this staycation.')
                sel = selections[0]
                card = sel['card']
                guest = sel['guest']
                booking = Reservation.objects.create(
                    customer=user,
                    staycation=est,
                    check_in=check_in,
                    check_out=check_out,
                    number_of_adults=max(0, int(guest['adults'])),
                    number_of_children=max(0, int(guest['children'])),
                    payer_name=f"{guest['first_name']} {guest['last_name']}".strip(),
                    payer_contact=guest['contact'],
                    special_requests=guest.get('special_request', ''),
                )
                base = q2(est.rate)
                bill_items = [{
                    'label': est.name,
                    'description': f'{nights} night(s)',
                    'quantity': nights, 'rate': base, 'amount': q2(base * nights),
                }]
                svc_map = {s.id: s for s in est.services.filter(status=Service.ServiceStatus.ACTIVE)}
                picked = [svc_map[i] for i in guest.get('services', []) if i in svc_map]
                if picked:
                    booking.services.add(*picked)
                    for svc in picked:
                        bill_items.append({
                            'label': svc.name,
                            'description': 'Staycation add-on',
                            'quantity': 1, 'rate': q2(svc.rate), 'amount': q2(svc.rate),
                        })
                return booking, bill_items, None
        except ValueError as exc:
            return None, [], str(exc)
        except Exception:
            # Never swallow a real failure silently: the generic message is for
            # the customer, the traceback goes to the log.
            logger.exception('establishment flow: %s booking could not be created', self.key)
            return None, [], 'We could not complete this booking. Please try again.'


# ---------------------------------------------------------------------------
# Restaurants -- the bookable items are tables.
# NEITHER Restaurant NOR Table stores a price, so ``rate`` is None everywhere
# and the shared template shows "Contact establishment for pricing".  The only
# stored money figure is Reservation.deposit, which defaults to 0.
# ---------------------------------------------------------------------------


class RestaurantAdapter(BaseAdapter):
    key = 'restaurant'
    label = 'Restaurants'
    singular = 'Restaurant'
    item_noun = 'Table'
    item_noun_plural = 'Tables'
    item_badge = 'TABLE'
    charge_section = 'Table charges'
    icon = 'fa-utensils'
    unit_noun = 'table'
    duration_noun = 'Seating'
    price_missing_note = 'Contact establishment for pricing'
    date_label = 'Reservation date'
    show_time = True
    time_label = 'Reservation time'

    def get_est(self, pk):
        from restaurants.models import Restaurant
        return Restaurant.objects.filter(status=Restaurant.Status.ACTIVE).prefetch_related(
            'tables', 'photos'
        ).get(pk=pk)

    def list_url(self):
        return reverse('restaurants:list')

    def detail_url(self, est):
        return reverse('restaurants:detail', args=[est.slug])

    def select_url(self, est):
        return reverse('restaurants:flow_select', args=[est.pk])

    def booking_detail_url(self, booking):
        return reverse('restaurants:booking_detail', args=[booking.pk])

    def items(self, est, check_in, check_out, nights):
        from restaurants.models import Table

        rows = []
        for table in est.tables.all():
            if table.status == Table.Status.MAINTENANCE:
                status, bookable = 'Under Maintenance', False
            else:
                status, bookable = 'Choose reservation time', True
            rows.append({
                'id': table.pk,
                'obj': table,
                'name': f'Table {table.table_number}',
                'number': f'Table {table.table_number}',
                'display_status': status,
                'raw_status': table.status,
                'bookable': bookable,
                'facts': [
                    ('fa-users', table.capacity, 'Seats'),
                    ('fa-chair', table.get_seating_area_display(), 'Seating'),
                    ('fa-user-group', table.capacity, 'Max guests'),
                ],
                'max_guests': table.capacity,
                'sleeps': f'{table.capacity} guests',
                'feature_labels': [],
                'photos': [],
                'rate': None,
                # Restaurants store no rate, so nothing is charged online. The
                # plan says so explicitly rather than showing an invented price.
                'charge': self.charge_plan(
                    0, 'table', table.capacity, table.capacity,
                    mode='flat', extra_mode='none',
                ),
                '_rate_value': Decimal('0'),
                'siblings_available': sum(
                    1 for t in est.tables.all()
                    if t.status != Table.Status.MAINTENANCE
                ),
                'description': '',
            })
        return rows

    def build_booking(self, user, est, selections, ctx):
        from restaurants.models import Table
        from restaurants.services import (
            RestaurantReservationError,
            create_restaurant_reservation,
        )

        table_id = selections[0]['card']['id']
        guest = selections[0]['guest']
        try:
            table = Table.objects.get(pk=table_id, restaurant=est)
            reservation = create_restaurant_reservation(
                customer=user,
                table=table,
                when=ctx['reservation_datetime'],
                guests=max(1, int(guest['adults']) + int(guest['children'])),
                seating_preference=table.seating_area,
                special_requests=guest.get('special_request', ''),
                deposit=Decimal('0.00'),
            )
            return reservation, [], None
        except RestaurantReservationError as exc:
            return None, [], str(exc)
        except Table.DoesNotExist:
            return None, [], 'The selected table is no longer available.'


# ---------------------------------------------------------------------------
# Tour Packages -- no departure model, so the package is the single item and
# the bill uses the stored price + extra_person_rate headcount adjustment.
# ---------------------------------------------------------------------------


class PackageAdapter(BaseAdapter):
    key = 'package'
    label = 'Tour Packages'
    singular = 'Tour Package'
    item_noun = 'Package'
    item_noun_plural = 'Packages'
    item_badge = 'DEPARTURE'
    charge_section = 'Package charges'
    icon = 'fa-suitcase-rolling'
    unit_noun = 'person'
    duration_noun = 'Duration'
    date_label = 'Travel date'
    show_time = True
    time_label = 'Start time'
    # A package has no hard headcount limit: anyone beyond the included
    # headcount is billed at extra_person_rate by build_booking.
    enforce_capacity = False
    # No extra guest fields: the Hotels guest-information card is the master
    # template and it has none, so every category shows the same fields only.
    guest_extra_fields = ()

    def default_date(self, est, fallback):
        today = fallback
        return est.validity_start_date if est.validity_start_date > today else today

    def get_est(self, pk):
        from tour_package.models import TourPackage
        return TourPackage.objects.prefetch_related('photos').get(pk=pk)

    def est_location(self, est):
        return ', '.join(filter(None, [
            est.destination_city, est.destination_province, est.destination_country,
        ])) or est.destination_name or ''

    def list_url(self):
        return reverse('tour_package:list')

    def detail_url(self, est):
        return reverse('tour_package:detail', args=[est.slug])

    def select_url(self, est):
        return reverse('tour_package:flow_select', args=[est.pk])

    def booking_detail_url(self, booking):
        return reverse('tour_package:booking_detail', args=[booking.pk])

    def items(self, est, check_in, check_out, nights):
        if est.status == 'ACTIVE':
            status = 'Available'
        elif est.status == 'FULLY_BOOKED':
            status = 'Reserved'
        else:
            status = est.get_status_display()
        bookable = bool(est.bookable and est.valid_on(check_in))
        features = [p.strip() for p in (est.inclusions or '').replace('\n', ',').split(',') if p.strip()]
        rate = _rate_block(
            est.price, 1, 'person', extra_label='extra person',
        )
        rate['extra_charge'] = q2(est.extra_person_rate)
        rate['extra_display'] = money(rate['extra_charge'])
        rate['has_extra'] = rate['extra_charge'] > 0
        return [{
            'id': est.pk,
            'obj': est,
            'name': est.name,
            'number': f'{est.duration_days}-day package',
            'display_status': status,
            'raw_status': est.status,
            'bookable': bookable,
            'facts': [
                ('fa-clock', f'{est.duration_days} day{"s" if est.duration_days != 1 else ""}', 'Duration'),
                ('fa-users', est.included_headcount, 'Included pax'),
                ('fa-calendar-check', est.validity_end_date.strftime('%b %d, %Y'), 'Valid until'),
            ],
            'max_guests': max(1, est.included_headcount),
            'sleeps': f'{est.included_adults} adult(s), {est.included_children} child(ren) included',
            'feature_labels': features,
            'photos': list(est.photos.all()),
            'rate': rate,
            'charge': self.charge_plan(
                est.price, 'person', est.included_headcount,
                max(1, est.included_headcount),
                extra_rate=est.extra_person_rate,
                mode='guests', extra_mode='guests',
                extra_label='Additional head',
            ),
            '_rate_value': dec(est.price),
            'siblings_available': 1 if bookable else 0,
            'description': est.description or '',
        }]

    def extra_inclusions(self, est, item):
        out = []
        if est.included_tour_guide:
            out.append({'icon': 'fa-user-tie', 'text': 'Tour guide included'})
        if est.included_flights.exists():
            out.append({'icon': 'fa-plane', 'text': 'Flights included'})
        if est.included_transport.exists():
            out.append({'icon': 'fa-car', 'text': 'Transport included'})
        if est.cancellation_policy:
            out.append({'icon': 'fa-rotate-left', 'text': est.cancellation_policy.splitlines()[0].strip()})
        return out

    def build_booking(self, user, est, selections, ctx):
        from tour_package.models import Booking, BookingGuest
        from django.db import transaction as db_transaction

        sel = selections[0]
        guest = sel['guest']
        travel_date = ctx['check_in']
        try:
            with db_transaction.atomic():
                if not est.valid_on(travel_date):
                    raise ValueError('This package is not valid on that travel date.')
                adults = max(0, int(guest['adults']))
                children = max(0, int(guest['children']))
                booking = Booking.objects.create(
                    customer=user,
                    package=est,
                    travel_date=travel_date,
                    start_time=ctx.get('start_time'),
                    end_time=ctx.get('end_time'),
                    number_of_travelers=max(1, adults + children),
                    number_of_adults=adults,
                    number_of_children=children,
                    payment_method=ctx.get('payment_method') or DEFAULT_PAYMENT_METHOD,
                    payer_name=f"{guest['first_name']} {guest['last_name']}".strip(),
                    payer_contact=guest['contact'],
                    special_requests=guest.get('special_request', ''),
                )
                BookingGuest.objects.create(
                    booking=booking,
                    full_name=' '.join(
                        part for part in [guest['first_name'], guest.get('middle_name', ''), guest['last_name']]
                        if part
                    ).strip(),
                    emergency_contact_name=guest.get('emergency_contact_name', ''),
                    emergency_contact_number=guest.get('emergency_contact', ''),
                    emergency_contact_relationship=guest.get('emergency_contact_relationship', ''),
                )
                travelers = booking.number_of_travelers
                bill_items = [{
                    'label': est.name,
                    'description': f'{travelers} traveler(s) x {price_text(est.price, free_when_zero=True)}',
                    'quantity': travelers, 'rate': q2(est.price),
                    'amount': q2(est.price * travelers),
                }]
                extra_heads = max(0, travelers - est.included_headcount)
                if extra_heads and est.extra_person_rate:
                    bill_items.append({
                        'label': 'Additional head rate',
                        'description': f'{extra_heads} traveller(s) beyond {est.included_headcount} included',
                        'quantity': extra_heads, 'rate': q2(est.extra_person_rate),
                        'amount': q2(est.extra_person_rate * extra_heads),
                    })
                return booking, bill_items, None
        except ValueError as exc:
            return None, [], str(exc)
        except Exception:
            # Never swallow a real failure silently: the generic message is for
            # the customer, the traceback goes to the log.
            logger.exception('establishment flow: %s booking could not be created', self.key)
            return None, [], 'We could not complete this booking. Please try again.'


# ---------------------------------------------------------------------------
# Landmarks -- Landmark.entry_fee is the one price; the landmark itself is the
# single selectable item.  Guided-tour rates are stored on the landmark, so
# they are offered as real options.  There is no equipment catalogue, so the
# Ticket.equipment_* fields are left at 0 rather than inventing products.
# ---------------------------------------------------------------------------


class LandmarkAdapter(BaseAdapter):
    key = 'landmark'
    label = 'Landmarks'
    singular = 'Landmark'
    item_noun = 'Entry Pass'
    item_noun_plural = 'Entry Passes'
    item_badge = 'PASS'
    charge_section = 'Entry fees'
    icon = 'fa-landmark'
    unit_noun = 'visitor'
    duration_noun = 'Visit'
    date_label = 'Visit date'
    show_time = True
    time_label = 'Arrival time'

    def extras(self, est):
        rows = []
        for opt in self.tour_options(est):
            rows.append({
                'name': 'guided_tour', 'label': 'Guided tour', 'value': opt['value'],
                'text': '%s - %s%s' % (
                    opt['label'], money(opt['rate']),
                    '' if opt['flat'] else ' per visitor',
                ),
            })
        return rows

    def get_est(self, pk):
        from landmarks.models import Landmark
        return Landmark.objects.filter(status=Landmark.Status.ACTIVE).prefetch_related('photos').get(pk=pk)

    def list_url(self):
        return reverse('landmarks:list')

    def detail_url(self, est):
        return reverse('landmarks:detail', args=[est.pk])

    def select_url(self, est):
        return reverse('landmarks:flow_select', args=[est.pk])

    def booking_detail_url(self, booking):
        return reverse('landmarks:booking_detail', args=[booking.pk])

    def tour_options(self, est):
        opts = [{'value': 'NONE', 'label': 'No guided tour', 'rate': Decimal('0'), 'flat': True}]
        if dec(est.guided_tour_rate):
            opts.append({
                'value': 'STANDARD', 'label': 'Standard guided tour',
                'rate': q2(est.guided_tour_rate), 'flat': False,
            })
        if dec(est.private_tour_rate):
            opts.append({
                'value': 'PRIVATE', 'label': 'Private guided tour',
                'rate': q2(est.private_tour_rate), 'flat': True,
            })
        return opts

    def items(self, est, check_in, check_out, nights):
        if est.status == 'ACTIVE':
            status, bookable = 'Available', True
        elif est.status == 'UNDER_MAINTENANCE':
            status, bookable = 'Under Maintenance', False
        else:
            status, bookable = est.get_status_display(), False
        features = [ln.strip() for ln in (est.open_hours or '').splitlines() if ln.strip()]
        return [{
            'id': est.pk,
            'obj': est,
            'name': est.name,
            'number': est.get_category_display(),
            'display_status': status,
            'raw_status': est.status,
            'bookable': bookable,
            'facts': [
                ('fa-ticket', price_text(est.entry_fee, free_when_zero=True), 'Entry fee'),
                ('fa-users', est.capacity or 'Unlimited', 'Visitors/day'),
                ('fa-clock', est.open_hours or 'Hours not listed', 'Opening hours'),
            ],
            'max_guests': est.capacity or 99,
            'sleeps': f'Up to {est.capacity} visitors per day' if est.capacity else 'Open visit',
            'feature_labels': features,
            'photos': list(est.photos.all()),
            'rate': _rate_block(est.entry_fee, 1, 'visitor'),
            'charge': self.charge_plan(
                est.entry_fee, 'visitor', 0, est.capacity or 99,
                mode='guests', extra_mode='none',
            ),
            '_rate_value': dec(est.entry_fee),
            'siblings_available': 1 if bookable else 0,
            'description': est.description or '',
        }]

    def extra_inclusions(self, est, item):
        out = []
        if est.open_hours:
            out.append({'icon': 'fa-clock', 'text': est.open_hours})
        for opt in self.tour_options(est)[1:]:
            out.append({
                'icon': 'fa-user-tie' if opt['value'] == 'STANDARD' else 'fa-users',
                'text': f"{opt['label']} - {money(opt['rate'])}"
                        + (' per visitor' if not opt['flat'] else ''),
            })
        return out

    def _bill_items(self, est, visitors, tour_opt):
        """Entry fee per visitor, plus the chosen guided tour at its stored rate."""
        bill = []
        if dec(est.entry_fee):
            bill.append({
                'label': 'Entry fee',
                'description': '%s x %d visitor(s)' % (est.name, visitors),
                'quantity': visitors, 'rate': q2(est.entry_fee),
                'amount': q2(est.entry_fee * visitors),
            })
        if tour_opt and dec(tour_opt.get('rate')):
            qty = 1 if tour_opt['flat'] else visitors
            bill.append({
                'label': tour_opt['label'],
                'description': 'per visitor' if not tour_opt['flat'] else 'flat rate',
                'quantity': qty, 'rate': q2(tour_opt['rate']),
                'amount': q2(tour_opt['rate'] * qty),
            })
        return bill

    def build_booking(self, user, est, selections, ctx):
        from django.db.models import Sum
        from landmarks.models import Ticket
        from django.db import transaction as db_transaction

        sel = selections[0]
        guest = sel['guest']
        visitors = max(1, int(guest['adults']))
        tour = ctx.get('guided_tour') or 'NONE'
        opts = {o['value']: o for o in self.tour_options(est)}
        if tour not in opts:
            tour = 'NONE'
        opt = opts[tour]
        try:
            with db_transaction.atomic():
                visit = ctx['visit_datetime']
                booked = Ticket.objects.filter(
                    destination=est, visit_datetime__date=visit.date(),
                ).aggregate(total=Sum('number_of_visitors'))['total'] or 0
                if est.capacity and booked + visitors > est.capacity:
                    raise ValueError(
                        f'Only {max(0, est.capacity - booked)} visitor slot(s) left for that date.'
                    )
                return Ticket.objects.create(
                    customer=user,
                    destination_type=est.category,
                    destination=est,
                    visit_datetime=visit,
                    number_of_visitors=visitors,
                    guided_tour=tour,
                    equipment_rate=Decimal('0.00'),
                    equipment_quantity=0,
                    payer_name=f"{guest['first_name']} {guest['last_name']}".strip(),
                    payer_contact=guest['contact'],
                    special_requests=guest.get('special_request', ''),
                ), self._bill_items(est, visitors, opt), None
        except ValueError as exc:
            return None, [], str(exc)
        except Exception:
            # Never swallow a real failure silently: the generic message is for
            # the customer, the traceback goes to the log.
            logger.exception('establishment flow: %s booking could not be created', self.key)
            return None, [], 'We could not complete this booking. Please try again.'


# ---------------------------------------------------------------------------
# Activities -- the bookable item is the activity session itself.  The
# provider is the establishment context, so the adapter keys on Activity.
# ---------------------------------------------------------------------------


class ActivityAdapter(BaseAdapter):
    key = 'activity'
    label = 'Activities'
    singular = 'Activity'
    item_noun = 'Session'
    item_noun_plural = 'Sessions'
    item_badge = 'SESSION'
    charge_section = 'Session fees'
    icon = 'fa-person-hiking'
    unit_noun = 'session'
    duration_noun = 'Session'
    date_label = 'Activity date'
    show_time = True
    time_label = 'Start time'

    def default_date(self, est, fallback):
        if est.schedule_date and est.schedule_date > fallback:
            return est.schedule_date
        return fallback

    def get_est(self, pk):
        from activities.models import Activity
        return Activity.objects.select_related('provider').prefetch_related('photos').get(pk=pk)

    def est_name(self, est):
        return est.name

    def est_location(self, est):
        return est.full_location

    def provider_name(self, est):
        return est.provider.name if est.provider_id else ''

    def list_url(self):
        return reverse('activities:list')

    def detail_url(self, est):
        return reverse('activities:detail', args=[est.pk])

    def select_url(self, est):
        return reverse('activities:flow_select', args=[est.pk])

    def booking_detail_url(self, booking):
        return reverse('activities:booking_detail', args=[booking.pk])

    def rate_noun(self, act):
        return {
            'PER_PERSON': 'participant', 'PER_GROUP': 'group', 'PER_SESSION': 'session',
        }.get(act.rate_type, 'participant')

    def items(self, act, check_in, check_out, nights):
        if not act.bookable:
            status, bookable = act.get_status_display(), False
        elif act.schedule_date and act.schedule_date != check_in:
            status, bookable = f'Runs {act.schedule_date.strftime("%b %d, %Y")}', False
        else:
            status, bookable = 'Available', True
        rate = _rate_block(act.fee, 1, self.rate_noun(act))
        rate['extra_charge'] = q2(act.additional_fee)
        rate['extra_label'] = 'additional fee'
        rate['extra_display'] = money(rate['extra_charge'])
        rate['has_extra'] = rate['extra_charge'] > 0
        features = [f.strip() for f in
                    ','.join([act.requirements, act.required_equipment, act.required_documents]).split(',')
                    if f.strip()]
        return [{
            'id': act.pk,
            'obj': act,
            'name': act.name,
            'number': act.get_category_display(),
            'display_status': status,
            'raw_status': act.status,
            'bookable': bookable,
            'facts': [
                ('fa-clock', act.duration, 'Duration'),
                ('fa-users', act.capacity, 'Max pax'),
                ('fa-tag', price_text(act.fee), f'per {self.rate_noun(act)}'),
            ],
            'max_guests': act.capacity,
            'sleeps': f'Minimum {act.min_participants} participant(s)',
            'feature_labels': features,
            'photos': list(act.photos.all()),
            'rate': rate,
            'charge': self.charge_plan(
                act.fee, self.rate_noun(act), 0, act.capacity,
                extra_rate=act.additional_fee,
                mode='guests' if act.rate_type == 'PER_PERSON' else 'flat',
                extra_mode='guests' if act.rate_type == 'PER_PERSON' else 'flat',
                extra_label='Additional fee',
            ),
            '_rate_value': dec(act.fee),
            'siblings_available': 1 if bookable else 0,
            'description': act.description or '',
        }]

    def extra_inclusions(self, act, item):
        out = []
        if act.meeting_point:
            out.append({'icon': 'fa-location-dot', 'text': f'Meet at {act.meeting_point}'})
        if act.guide_required:
            out.append({'icon': 'fa-user-tie', 'text': 'Certified guide required'})
        if act.operating_days:
            out.append({'icon': 'fa-calendar-week', 'text': act.operating_days})
        if act.provider_id and act.provider.verified:
            out.append({'icon': 'fa-badge-check', 'text': f'Verified provider: {act.provider.name}'})
        return out

    def build_booking(self, user, est, selections, ctx):
        from activities.models import Booking
        from django.db import transaction as db_transaction

        sel = selections[0]
        guest = sel['guest']
        participants = max(1, int(guest['adults']))
        schedule_date = ctx['check_in']
        try:
            with db_transaction.atomic():
                act = type(est).objects.select_for_update().select_related('provider').get(pk=est.pk)
                if not act.bookable:
                    raise ValueError('This activity is not accepting bookings right now.')
                if act.schedule_date and act.schedule_date != schedule_date:
                    raise ValueError('This activity runs on a different date.')
                if participants > act.capacity:
                    raise ValueError(f'This activity allows up to {act.capacity} participants.')
                if participants < act.min_participants:
                    raise ValueError(f'This activity requires at least {act.min_participants} participants.')
                booking = Booking.objects.create(
                    customer=user,
                    activity=act,
                    schedule_date=schedule_date,
                    start_time=ctx.get('start_time') or act.schedule_time,
                    end_time=ctx.get('end_time') or act.schedule_end_time,
                    participant_count=participants,
                    payer_name=f"{guest['first_name']} {guest['last_name']}".strip(),
                    payer_contact=guest['contact'],
                    special_requests=guest.get('special_request', ''),
                )
                per = act.rate_type == 'PER_PERSON'
                qty = participants if per else 1
                bill_items = [{
                    'label': act.name,
                    'description': (f'{participants} participant(s)' if per else f'per {self.rate_noun(act)}'),
                    'quantity': qty, 'rate': q2(act.fee), 'amount': q2(act.fee * qty),
                }]
                if act.additional_fee:
                    add_qty = participants if act.rate_type == 'PER_PERSON' else 1
                    bill_items.append({
                        'label': 'Additional fee',
                        'description': act.name,
                        'quantity': add_qty, 'rate': q2(act.additional_fee),
                        'amount': q2(act.additional_fee * add_qty),
                    })
                return booking, bill_items, None
        except ValueError as exc:
            return None, [], str(exc)
        except Exception:
            # Never swallow a real failure silently: the generic message is for
            # the customer, the traceback goes to the log.
            logger.exception('establishment flow: %s booking could not be created', self.key)
            return None, [], 'We could not complete this booking. Please try again.'


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ADAPTERS = {
    a.key: a()
    for a in (
        ResortAdapter, StaycationAdapter, RestaurantAdapter,
        PackageAdapter, LandmarkAdapter, ActivityAdapter,
    )
}


def get_adapter(key):
    try:
        return ADAPTERS[key]
    except KeyError:
        raise KeyError(f'No establishment flow adapter for category {key!r}')


# ---------------------------------------------------------------------------
# Shared request handling
# ---------------------------------------------------------------------------

PAYMENT_METHODS = [
    {'value': value, 'label': label}
    for value, label in PAYMENT_METHOD_CHOICES
]

DEFAULT_PAYMENT_METHOD = 'GCASH'


def parse_date(value, default):
    from datetime import date as _date
    from django.utils import timezone

    if value:
        try:
            return _date.fromisoformat(str(value).strip()[:10])
        except (TypeError, ValueError):
            pass
    return default


def parse_int(value, default, minimum=None):
    try:
        out = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None and out < minimum:
        return default
    return out


def _aware(dt):
    from django.utils import timezone
    return timezone.make_aware(dt, timezone.get_current_timezone()) if timezone.is_naive(dt) else dt


def _datetime_on(day, hhmm, default_hhmm):
    from datetime import datetime, time as dtime
    hour, minute = default_hhmm
    if hhmm:
        try:
            raw = str(hhmm).strip()[:5]
            hour, minute = (int(x) for x in raw.split(':'))
        except (TypeError, ValueError):
            pass
    return _aware(datetime.combine(day, dtime(hour=hour, minute=minute)))


def parse_guest_lines(request, cards, adapter):
    """Read the per-item guest blocks exactly like the Hotels page does.

    The Hotels form uses ``room_<index>_<field>`` names; the shared form uses
    ``item_<index>_<field>``.  Both are re-read here so a validation error can
    re-render the page with everything the guest typed still in place.
    """
    lines, errors = [], []
    for idx in range(len(cards)):
        prefix = f'item_{idx}_'
        line = empty_guest()
        for field in line:
            line[field] = (request.POST.get(prefix + field) or '').strip()
        line['adults'] = parse_int(line['adults'], 1, 1)
        line['children'] = parse_int(line['children'], 0, 0)
        line['services'] = [
            int(x) for x in request.POST.getlist(prefix + 'services') if str(x).isdigit()
        ]
        line['amenities'] = [
            int(x) for x in request.POST.getlist(prefix + 'amenities') if str(x).isdigit()
        ]
        for extra in adapter.guest_extra_fields:
            line[extra['name']] = (request.POST.get(prefix + extra['name']) or '').strip()

        who = cards[idx]['name']
        if not line['first_name']:
            errors.append(f'{who}: guest first name is required.')
        if not line['last_name']:
            errors.append(f'{who}: guest last name is required.')
        contact = line['contact'].replace(' ', '')
        if not contact:
            errors.append(f'{who}: a contact number is required.')
        elif not contact.lstrip('+').isdigit() or not 7 <= len(contact.lstrip('+')) <= 15:
            errors.append(f'{who}: contact number must be 7-15 digits.')
        guests = line['adults'] + line['children']
        if guests < 1:
            errors.append(f'{who}: at least one adult is required.')
        capacity = cards[idx]['max_guests']
        if adapter.enforce_capacity and capacity and guests > capacity:
            errors.append(f'{who}: only {capacity} guest(s) fit this selection.')
        lines.append(line)
    return lines, errors


def _flow_ctx(adapter, est, check_in, check_out, source):
    """Everything category-specific about the requested dates."""
    from datetime import timedelta

    ctx = {
        'check_in': check_in,
        'check_out': check_out,
        'nights': adapter.nights_for(check_in, check_out),
        'adults': parse_int(source.get('adults'), 2, 1),
        'children': parse_int(source.get('children'), 0, 0),
        'payment_method': source.get('payment_method') or DEFAULT_PAYMENT_METHOD,
        'pay_later': source.get('pay_later') == 'on',
    }
    if adapter.key == 'restaurant':
        ctx['reservation_datetime'] = _datetime_on(check_in, source.get('time'), (19, 0))
    if adapter.key == 'landmark':
        ctx['visit_datetime'] = _datetime_on(check_in, source.get('time'), (9, 0))
        ctx['guided_tour'] = (source.get('guided_tour') or 'NONE').strip()
    if adapter.key in ('activity', 'package'):
        hhmm = source.get('time')
        ctx['start_time'] = _datetime_on(check_in, hhmm, (9, 0)).time() if hhmm else None
        ctx['end_time'] = None
    return ctx


def _context_for(request, adapter, est, check_in, check_out, source,
                 selected_cards=None, guest_lines=None, errors=None):
    cards, nights, service_rows, amenity_rows_ = adapter.build_cards(est, check_in, check_out)
    if selected_cards is not None:
        keep = {c['id'] for c in selected_cards}
        cards = [c for c in cards if c['id'] in keep] or cards
    if guest_lines is None:
        guest_lines = guest_defaults(len(cards))
    return {
        'adapter': adapter,
        'category': adapter.key,
        'category_label': adapter.label,
        'est': est,
        'est_name': adapter.est_name(est),
        'est_location': adapter.est_location(est),
        'cards': cards,
        'item_meta_json': adapter.item_meta(est, cards, selected_cards or []),
        'item_details_json': {str(c['id']): c['details'] for c in cards},
        # The Hotels page re-seeds its selection from the server on a
        # validation re-render; the shared page does the same with the ids.
        'selected_ids_json': [c['id'] for c in (selected_cards or [])],
        'nights': nights,
        'check_in': check_in,
        'check_out': check_out,
        'services': service_rows,
        'amenities': amenity_rows_,
        'guests': guest_lines,
        'errors': errors or [],
        'payment_methods': PAYMENT_METHODS,
        'selected_payment_method': (source.get('payment_method') or DEFAULT_PAYMENT_METHOD),
        'pay_later': source.get('pay_later') == 'on',
        'tour_options': adapter.extras(est),
        'guest_extra_fields': adapter.guest_extra_fields,
        'flow_config_json': {
            # The Hotels guest-information card is the master template. These are
            # the only words that change per category; the markup, CSS and
            # behaviour are produced by the same builder for all seven.
            'badge': adapter.item_badge,
            'item': adapter.item_noun,
            'item_plural': adapter.item_noun_plural,
            'hint': 'Recalculated live as you pick %s, dates, guests and services.'
                    % adapter.item_noun_plural.lower(),
            'charge_section': adapter.charge_section,
            'show_duration': adapter.lodging,
        },
        'date_label': adapter.date_label,
        'end_date_label': adapter.end_date_label,
        'show_end_date': adapter.lodging,
        'show_time': adapter.show_time,
        'time_label': adapter.time_label,
        'item_noun': adapter.item_noun,
        'item_noun_plural': adapter.item_noun_plural,
        'unit_noun': adapter.unit_noun,
        'duration_noun': adapter.duration_noun,
        'price_missing_note': adapter.price_missing_note,
        'select_url': adapter.select_url(est),
        'detail_url': adapter.detail_url(est),
        'list_url': adapter.list_url(),
        'has_price': any(c['rate'] for c in cards),
    }




def handle_flow(request, adapter_key, pk):
    """The single view body behind every non-hotel establishment booking page.

    GET  -> renders the shared selection page for that establishment.
    POST -> validates, creates the category's own booking record in one
            transaction, issues the bill / payment / transaction record, and
            redirects to that category's booking detail page.  A validation
            error re-renders the page with the selection and guest data kept.
    """
    from datetime import date, timedelta

    from django.contrib import messages
    from django.http import Http404
    from django.shortcuts import redirect, render

    from transactions.models import Bill

    adapter = get_adapter(adapter_key)
    try:
        est = adapter.get_est(pk)
    except Exception as exc:
        raise Http404(f'{adapter.singular} not found') from exc

    source = request.POST if request.method == 'POST' else request.GET
    default_in = date.today() + timedelta(days=1)
    default_in = adapter.default_date(est, default_in)
    check_in = parse_date(source.get('check_in'), default_in)
    check_out = parse_date(source.get('check_out'), check_in + timedelta(days=1))
    if check_out <= check_in:
        check_out = check_in + timedelta(days=1)

    if request.method != 'POST':
        return render(
            request, 'establishments/select.html',
            _context_for(request, adapter, est, check_in, check_out, source),
        )

    ctx = _flow_ctx(adapter, est, check_in, check_out, source)
    cards, _nights, _svcs, _amens = adapter.build_cards(est, check_in, check_out)
    by_id = {c['id']: c for c in cards}

    chosen = []
    for raw in request.POST.getlist('item_ids'):
        try:
            chosen.append(int(raw))
        except (TypeError, ValueError):
            continue
    chosen = list(dict.fromkeys(chosen))

    if not chosen:
        messages.error(request, f'Please select at least one {adapter.item_noun.lower()}.')
        return redirect(f'{adapter.select_url(est)}?check_in={check_in}')

    selected = [by_id[i] for i in chosen if i in by_id]
    if len(selected) != len(chosen):
        messages.error(request, 'One of your selections is no longer listed.')
        return redirect(f'{adapter.select_url(est)}?check_in={check_in}')
    for card in selected:
        if not card['bookable']:
            messages.error(request, f"{card['name']} is not available for those details.")
            return redirect(f'{adapter.select_url(est)}?check_in={check_in}')

    guest_lines, errors = parse_guest_lines(request, selected, adapter)
    if errors:
        return render(
            request, 'establishments/select.html',
            _context_for(request, adapter, est, check_in, check_out, source,
                         selected_cards=selected, guest_lines=guest_lines, errors=errors),
        )

    selections = [
        {'card': card, 'guest': guest_lines[i]}
        for i, card in enumerate(selected)
    ]
    booking, bill_items, error = adapter.build_booking(request.user, est, selections, ctx)
    if error or booking is None:
        return render(
            request, 'establishments/select.html',
            _context_for(request, adapter, est, check_in, check_out, source,
                         selected_cards=selected, guest_lines=guest_lines, errors=[error or 'Booking failed.']),
        )

    total = sum((dec(i.get('amount')) for i in bill_items), Decimal('0'))
    bill = create_bill(service=adapter.key, customer=request.user, items=bill_items, booking=booking)
    booking.total_bill = total
    booking.balance_due = total
    booking.save(update_fields=['total_bill', 'balance_due'])

    if adapter.key == 'restaurant':
        booking.status = booking.Status.PENDING
        booking.amount_paid = Decimal('0.00')
        booking.balance_due = total
        booking.save(update_fields=[
            'status', 'amount_paid', 'balance_due',
        ])
        log_activity(
            request.user,
            'Submitted restaurant reservation',
            f'{booking.booking_reference} - pending officer confirmation',
        )
        record_transaction(
            'BOOKING',
            booking.booking_reference,
            request.user,
            f'Restaurant reservation {booking.booking_reference} submitted',
        )
        messages.success(
            request,
            'Reservation submitted. Status: Pending. Waiting for Restaurant '
            'Reservation Officer confirmation.',
        )
    elif ctx['pay_later']:
        booking.status = booking.Status.PENDING
        booking.save(update_fields=['status'])
        log_activity(request.user, f'Placed {adapter.label.lower().rstrip("s")} booking',
                     f'{booking.booking_reference} - pending payment')
        record_transaction('BOOKING', booking.booking_reference, request.user,
                           f'{adapter.label} booking {booking.booking_reference}')
        messages.success(
            request,
            f'{adapter.singular} booking {booking.booking_reference} created. Payment is pending.',
        )
    else:
        record_payment(customer=request.user, amount=total, method=ctx['payment_method'],
                       service=adapter.key,
                       description=f'{adapter.singular} booking {booking.booking_reference}',
                       bill=bill, booking=booking)
        booking.status = booking.Status.PENDING
        booking.amount_paid = total
        booking.balance_due = Decimal('0.00')
        booking.save(update_fields=['status', 'amount_paid', 'balance_due'])
        log_activity(request.user, f'Paid for {adapter.label.lower().rstrip("s")} booking',
                     f'{booking.booking_reference} - paid, pending officer confirmation')
        record_transaction('BOOKING', booking.booking_reference, request.user,
                           f'{adapter.singular} booking {booking.booking_reference} paid')
        messages.success(
            request,
            f'Booking {booking.booking_reference} paid. Status: Pending. Waiting for '
            f'{adapter.singular} Reservations Officer confirmation.',
        )

    return redirect(adapter.booking_detail_url(booking))


# ---------------------------------------------------------------------------
# Shared detail page
# ---------------------------------------------------------------------------
#
# Resorts, Staycations, Restaurants and Tour Packages already ship their own
# ``detail.html`` and are left alone.  Landmarks and Activities had no detail
# page at all, so both now render this one from the same adapter data.  It
# reuses the normalised item cards, so the three steps read as one flow.


def detail_context(adapter, est, check_in, check_out):
    from atrue_core.search_catalog import ACTIVITY_CATEGORY_LABELS, LANDMARK_CATEGORY_LABELS

    cards, nights, services, amenities = adapter.build_cards(est, check_in, check_out)
    facts = []
    if adapter.key == 'landmark':
        facts = [
            ('fa-ticket', LANDMARK_CATEGORY_LABELS.get(est.category, est.category), 'Type'),
            ('fa-clock', est.open_hours or 'Hours not listed', 'Opening hours'),
            ('fa-users', est.capacity or 'Unlimited', 'Visitors per day'),
            ('fa-location-dot', est.location, 'Location'),
        ]
    elif adapter.key == 'activity':
        facts = [
            ('fa-tag', ACTIVITY_CATEGORY_LABELS.get(est.category, est.category), 'Type'),
            ('fa-clock', est.duration, 'Duration'),
            ('fa-users', est.capacity, 'Max participants'),
            ('fa-location-dot', est.full_location, 'Location'),
        ]
    return {
        'adapter': adapter,
        'category': adapter.key,
        'category_label': adapter.label,
        'est': est,
        'est_name': adapter.est_name(est),
        'est_location': adapter.est_location(est),
        'cards': cards,
        'facts': [f for f in facts if f[1]],
        'services': services,
        'amenities': amenities,
        'nights': nights,
        'check_in': check_in,
        'check_out': check_out,
        'date_label': adapter.date_label,
        'end_date_label': adapter.end_date_label,
        'show_end_date': adapter.lodging,
        'show_time': adapter.show_time,
        'time_label': adapter.time_label,
        'item_noun_plural': adapter.item_noun_plural,
        'unit_noun': adapter.unit_noun,
        'price_missing_note': adapter.price_missing_note,
        'select_url': adapter.select_url(est),
        'list_url': adapter.list_url(),
        'has_price': any(c['rate'] for c in cards),
        'tour_options': adapter.extras(est),
    }
