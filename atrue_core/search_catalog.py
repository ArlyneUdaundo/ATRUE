"""
ATRUE — Shared, reusable booking/search catalog.

One configuration + one set of helpers powers every booking category page
(hotels, resorts, staycations, tour packages, restaurants, landmarks and
activities) so every listing page renders the SAME Agoda-style booking layout
while swapping in category-specific search fields, filters, sorting, prices
and action buttons.

Views only need to fetch the bookable queryset for their model and call
``render_search_page(request, category_key, objects)``.
"""

import hashlib
import json
import os
import time
from functools import lru_cache
from urllib.parse import urlencode

from django.conf import settings
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from atrue_core.location_hierarchy import (
    build_location_hierarchy,
    country_province_keys,
    location_display,
    location_matches,
)

# ---------------------------------------------------------------------------
# Stable "simulated" aggregates
# ---------------------------------------------------------------------------
# The simulator has no review dataset, so a deterministic aggregate is derived
# per listing to power the rating badge, star rating and review-count visuals
# a booking platform needs. Values are stable across page reloads.


def _seed(item, salt):
    raw = "%s:%s:%s" % (salt, getattr(item, "pk", 0), getattr(item, "name", ""))
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest(), 16)


def guest_score(item):
    return round(8.0 + (_seed(item, "score") % 17) / 10.0, 1)


def star_rating(item):
    return 3 + (_seed(item, "stars") % 3)


def review_count(item):
    return 210 + (_seed(item, "reviews") % 640)


def score_label(score):
    if score >= 9.0:
        return "Excellent"
    if score >= 8.5:
        return "Very good"
    if score >= 8.0:
        return "Good"
    return "Pleasant"


def money(value):
    """Format an amount as '2,600' (PHP pesos). Returns None for zero/blank."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    return "{:,.0f}".format(f)


def price_display(value, free_when_zero=False):
    """Classify a listing price into what its card has to render.

    Returns ``(amount, kind)``. ``amount`` is the formatted peso string or
    ``None``; ``kind`` is ``"amount"`` when a real positive price exists,
    ``"free"`` when the business genuinely charges nothing, and
    ``"unavailable"`` when no usable price is stored.

    ``money()`` collapses zero and missing into the same ``None``, so a card
    could not tell "free" apart from "unknown" and simply printed nothing.
    That is why a landmark with a 0.00 entry fee rendered with a blank price
    instead of "Free".
    """
    amount = _num(value)
    if amount is None:
        return None, "unavailable"
    if amount <= 0:
        return None, ("free" if free_when_zero else "unavailable")
    return "{:,.0f}".format(amount), "amount"


def price_prose(kind, amount, priced, plain_text):
    """Card description text that can never print a broken amount.

    ``priced`` is a format string using ``{amount}`` and is used only when a
    real price exists, so a card can no longer render "PHP None".
    """
    if kind == "amount":
        return priced.format(amount=u"\u20b1" + amount)
    return plain_text


@lru_cache(maxsize=8192)
def _cached_storage_exists(storage, path, cache_period):
    """Avoid repeating remote storage HEAD checks for the same image.

    Cache for at most one minute. The storage and path are part of the key, so
    the same object name in two storage backends cannot collide.
    """
    return storage.exists(path)


def _usable_images(paths):
    from django.core.files.storage import default_storage
    out = []
    seen = set()
    cache_period = int(time.monotonic() // 60)
    for value in paths:
        if isinstance(value, tuple):
            storage, path = value
        else:
            storage, path = default_storage, value
        if not path:
            continue
        key = (storage, path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if (getattr(storage, 'can_render_url_without_exists_check', False)
                    or _cached_storage_exists(storage, path, cache_period)):
                url = storage.url(path)
                if url not in out:
                    out.append(url)
        except Exception:
            continue
    return out


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cheapest_rate(available, field="rate"):
    """Lowest chargeable rate across the bookable rooms/units.

    A room typed in with a zero or negative rate must not win the minimum and
    hide every real rate in the building, so only positive rates compete. The
    caller decides what an absent result means.
    """
    rates = []
    for entry in available:
        value = getattr(entry, field, None)
        number = _num(value)
        if number is not None and number > 0:
            rates.append(value)
    return min(rates, default=None)


# ---------------------------------------------------------------------------
# Category configuration
# ---------------------------------------------------------------------------

CATEGORIES = [
    {"key": "hotel", "label": "Hotels", "icon": "fa-hotel"},
    {"key": "package", "label": "Tour Packages", "icon": "fa-suitcase-rolling"},
    {"key": "resort", "label": "Resorts", "icon": "fa-umbrella-beach"},
    {"key": "staycation", "label": "Staycations", "icon": "fa-couch"},
    {"key": "restaurant", "label": "Restaurants", "icon": "fa-utensils"},
    {"key": "landmark", "label": "Landmarks", "icon": "fa-landmark"},
    {"key": "activity", "label": "Activities", "icon": "fa-person-hiking"},
]

CATEGORY_URL = {
    "hotel": "hotels:list",
    "package": "tour_package:list",
    "resort": "resorts:list",
    "staycation": "staycations:list",
    "restaurant": "restaurants:list",
    "landmark": "landmarks:list",
    "activity": "activities:list",
}

ACTIVITY_CATEGORY_LABELS = {
    "OUTDOOR": "Outdoor & Adventure",
    "WATER": "Water Activities",
    "CULTURAL": "Cultural & Sightseeing",
    "THEME": "Theme Parks & Attractions",
    "WELLNESS": "Wellness & Leisure",
    "NIGHTLIFE": "Nightlife & Entertainment",
}

ROOM_TYPE_LABELS = {
    "SINGLE": "Single",
    "DOUBLE": "Double",
    "TWIN": "Twin",
    "DELUXE": "Deluxe",
    "SUITE": "Suite",
    "FAMILY": "Family",
    "OTHER": "Other",
}

UNIT_TYPE_LABELS = {
    "ROOM": "Room",
    "VILLA": "Villa",
    "SUITE": "Suite",
    "CABANA": "Cabana",
    "OTHER": "Other",
}

LANDMARK_CATEGORY_LABELS = {
    "TOURIST_SPOT": "Tourist Spot",
    "LANDMARK": "Landmark",
}

POPULAR_DESTINATIONS = [
    "Manila", "Quezon City", "Makati", "Baggao", "Cagayan", "Palawan",
    "El Nido", "Boracay", "Siargao", "Palaui Island", "Batanes", "Cebu",
    "Mactan", "Davao", "Davao City", "Iloilo", "Iloilo City", "Vigan",
    "Baguio", "Baguio City", "Sabang", "Puerto Galera", "Ecoland",
    "Mines View", "City Proper", "Corong-Corong",
]


def _province_index(item):
    parts = []
    for attr in ("province", "municipality", "barangay", "region", "country"):
        val = getattr(item, attr, None)
        if val:
            parts.extend([p.strip() for p in str(val).split(",") if p.strip()])
    return parts


def _item_loc(category_key, item):
    """Structured location for the hierarchical picker, per category."""
    if category_key == "restaurant":
        text = getattr(item, "location", None)
        return {"province": [], "municipality": [], "barangay": [], "loc_text": str(text) if text else ""}
    if category_key == "package":
        return {
            "province": [getattr(item, "destination_province", "") or ""],
            "municipality": [getattr(item, "destination_city", "") or ""],
            "barangay": [],
            "loc_text": "",
        }
    if category_key == "activity":
        return {
            "province": [getattr(item, "location_province", "") or ""],
            "municipality": [getattr(item, "location_municipality", "") or ""],
            "barangay": [getattr(item, "location_barangay", "") or ""],
            "loc_text": str(getattr(item, "location", "") or ""),
        }
    return {
        "province": [getattr(item, "province", "") or ""],
        "municipality": [getattr(item, "municipality", "") or ""],
        "barangay": [getattr(item, "barangay", "") or ""],
        "loc_text": "",
    }


def _searchable(*attrs):
    def f(item):
        pool = []
        for attr in attrs:
            val = getattr(item, attr, None)
            if val:
                pool.append(str(val))
        return " ".join(pool).lower()
    return f


def _duration_bucket(minutes):
    if minutes >= 60 * 24 * 7:
        return "1 week +"
    if minutes >= 60 * 24:
        return "Days"
    if minutes >= 60 * 6:
        return "Day trips"
    if minutes >= 60 * 2:
        return "2–6 hrs"
    if minutes >= 60:
        return "1–2 hrs"
    return "Under 1 hr"


def _package_duration_bucket(days):
    if days >= 8:
        return "8+ days"
    if days >= 4:
        return "4–7 days"
    if days >= 2:
        return "2–3 days"
    return "Day trip"


def _stay_capacity_bucket(capacity):
    if capacity >= 5:
        return "5+ guests"
    if capacity >= 3:
        return "2–4 guests"
    return "Up to 2 guests"


def _restaurant_price_class(item, idx):
    return ["₱", "₱₱", "₱₱₱"][_seed(item, "price") % 3]


# --- Index builders (filterable values per category) -----------------------

def _index_hotel(item):
    available = [r for r in item.rooms.all() if getattr(r, "status", "") == "AVAILABLE"]
    cheapest = _cheapest_rate(available)
    search = _searchable("name", "province", "municipality", "barangay", "establishment_id")(item)
    return {
        "price": _num(cheapest),
        "stars": star_rating(item),
        "score": guest_score(item),
        "province": _province_index(item),
        "room_type": sorted({ROOM_TYPE_LABELS.get(r.room_type, r.room_type) for r in item.rooms.all()}),
        "tags": [a.name for a in item.amenities.all()],
        "search": search,
    }


def _index_resort(item):
    available = [u for u in item.units.all() if getattr(u, "status", "") == "AVAILABLE"]
    cheapest = _cheapest_rate(available)
    search = _searchable("name", "province", "municipality", "barangay", "resort_id")(item)
    return {
        "price": _num(cheapest),
        "stars": star_rating(item),
        "score": guest_score(item),
        "province": _province_index(item),
        "unit_type": sorted({UNIT_TYPE_LABELS.get(u.unit_type, u.unit_type) for u in item.units.all()}),
        "tags": [s.name for s in item.services.all()],
        "search": search,
    }


def _index_staycation(item):
    return {
        "price": _num(item.rate),
        "stars": star_rating(item),
        "score": guest_score(item),
        "province": _province_index(item),
        "capacity": _stay_capacity_bucket(item.capacity),
        "tags": [s.name for s in item.services.all()],
        "search": _searchable("name", "province", "municipality", "barangay", "establishment_id")(item),
    }


def _index_package(item):
    inclusions = [p.strip() for p in (item.inclusions or "").replace("\n", ",").split(",") if p.strip()]
    dest = ", ".join(filter(None, [item.destination_city, item.destination_province, item.destination_country]))
    search = _searchable("name", "destination_name", "destination_city", "destination_province", "destination_country")(item)
    return {
        "price": _num(item.price),
        "stars": star_rating(item),
        "score": guest_score(item),
        "province": [x for x in [item.destination_province, item.destination_city] if x] or [dest] or ["—"],
        "duration": _package_duration_bucket(item.duration_days),
        "tags": inclusions,
        "search": search,
    }


def _index_restaurant(item):
    areas = sorted({t.get_seating_area_display() for t in item.tables.all()})
    max_cap = max((t.capacity for t in item.tables.all()), default=0)
    return {
        "price": _restaurant_price_class(item, None),
        "stars": star_rating(item),
        "score": guest_score(item),
        "province": [item.location],
        "cuisine": [item.cuisine_type] if item.cuisine_type else [],
        "area": areas,
        "capacity": _stay_capacity_bucket(max_cap),
        "search": _searchable("name", "location", "cuisine_type", "restaurant_id")(item),
    }


def _index_landmark(item):
    province = _province_index(item)
    label = LANDMARK_CATEGORY_LABELS.get(item.category, item.category)
    return {
        "price": _num(item.entry_fee),
        "stars": star_rating(item),
        "score": guest_score(item),
        "province": province or ["—"],
        "category": [label],
        "open": ["yes"] if item.open_hours else ["no"],
        "search": _searchable("name", "province", "municipality", "barangay", "description", "region", "country")(item),
    }


def _index_activity(item):
    label = ACTIVITY_CATEGORY_LABELS.get(item.category, item.category)
    return {
        "price": _num(item.fee),
        "stars": star_rating(item),
        "score": guest_score(item),
        "province": _province_index(item) or [item.provider.name if item.provider_id else "—"],
        "category": [label],
        "duration": _duration_bucket(item.duration_minutes),
        "bookable": bool(item.bookable),
        "search": _searchable("name", "description", "location", "location_municipality", "location_province", "meeting_point")(item) + " " + (item.provider.name.lower() if item.provider_id else ""),
    }


def _price_matches(value, pmin, pmax):
    """True when a stored price falls inside the requested range.

    A category may not have a numeric rate at all (Restaurants index a price
    class such as "Mid-range"), and that can never satisfy a numeric range, so
    it is treated exactly like a missing price: it matches only an open range.
    """
    if pmin is None and pmax is None:
        return True
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    if pmin is not None and value < pmin:
        return False
    if pmax is not None and value > pmax:
        return False
    return True


def _category_indexer(category_key):
    return {
        "hotel": _index_hotel,
        "resort": _index_resort,
        "staycation": _index_staycation,
        "package": _index_package,
        "restaurant": _index_restaurant,
        "landmark": _index_landmark,
        "activity": _index_activity,
    }[category_key]


# --- Filter specifications per category ------------------------------------

FILTER_SPECS = {
    "hotel": [
        {"group": "Your budget", "type": "price", "param_min": "price_min", "param_max": "price_max"},
        {"group": "Star rating", "type": "choice", "param": "stars", "key": "stars", "fixed": ["5", "4", "3"]},
        {"group": "Guest score", "type": "choice", "param": "score", "key": "score", "fixed": ["9", "8"]},
        {"group": "Location", "type": "choice", "param": "province", "key": "province"},
        {"group": "Room type", "type": "choice", "param": "room_type", "key": "room_type"},
        {"group": "Popular amenities", "type": "choice", "param": "tags", "key": "tags"},
    ],
    "resort": [
        {"group": "Your budget", "type": "price", "param_min": "price_min", "param_max": "price_max"},
        {"group": "Star rating", "type": "choice", "param": "stars", "key": "stars", "fixed": ["5", "4", "3"]},
        {"group": "Guest score", "type": "choice", "param": "score", "key": "score", "fixed": ["9", "8"]},
        {"group": "Location", "type": "choice", "param": "province", "key": "province"},
        {"group": "Unit type", "type": "choice", "param": "unit_type", "key": "unit_type"},
        {"group": "Services", "type": "choice", "param": "tags", "key": "tags"},
    ],
    "staycation": [
        {"group": "Your budget", "type": "price", "param_min": "price_min", "param_max": "price_max"},
        {"group": "Guest score", "type": "choice", "param": "score", "key": "score", "fixed": ["9", "8"]},
        {"group": "Location", "type": "choice", "param": "province", "key": "province"},
        {"group": "Capacity", "type": "choice", "param": "capacity", "key": "capacity"},
        {"group": "Add-on services", "type": "choice", "param": "tags", "key": "tags"},
    ],
    "package": [
        {"group": "Your budget", "type": "price", "param_min": "price_min", "param_max": "price_max"},
        {"group": "Duration", "type": "choice", "param": "duration", "key": "duration"},
        {"group": "Guest score", "type": "choice", "param": "score", "key": "score", "fixed": ["9", "8"]},
        {"group": "Location", "type": "choice", "param": "province", "key": "province"},
        {"group": "Inclusions", "type": "choice", "param": "tags", "key": "tags"},
    ],
    "restaurant": [
        {"group": "Cuisine", "type": "choice", "param": "cuisine", "key": "cuisine"},
        {"group": "Guest score", "type": "choice", "param": "score", "key": "score", "fixed": ["9", "8"]},
        {"group": "Location", "type": "choice", "param": "province", "key": "province"},
        {"group": "Seating", "type": "choice", "param": "area", "key": "area"},
        {"group": "Group size", "type": "choice", "param": "capacity", "key": "capacity"},
    ],
    "landmark": [
        {"group": "Category", "type": "choice", "param": "category", "key": "category"},
        {"group": "Guest score", "type": "choice", "param": "score", "key": "score", "fixed": ["9", "8"]},
        {"group": "Location", "type": "choice", "param": "province", "key": "province"},
        {"group": "Opening hours", "type": "choice", "param": "open", "key": "open"},
    ],
    "activity": [
        {"group": "Activity type", "type": "choice", "param": "category", "key": "category"},
        {"group": "Your budget", "type": "price", "param_min": "price_min", "param_max": "price_max"},
        {"group": "Duration", "type": "choice", "param": "duration", "key": "duration"},
        {"group": "Guest score", "type": "choice", "param": "score", "key": "score", "fixed": ["9", "8"]},
        {"group": "Location", "type": "choice", "param": "province", "key": "province"},
    ],
}


def _option_label(key, value):
    if key == "stars":
        return "★ " * int(value)
    if key == "score":
        return value + "+"
    if key == "open":
        return "Open hours listed" if value in ("yes", "True", "1") else "No open hours"
    if key == "capacity":
        return value
    label = str(value)
    return label[:1].upper() + label[1:] if label else label


def _derive_options(spec, working, idx_for):
    key = spec["key"]
    # Count distinct values once per listing in one pass. The previous nested
    # scan compared every option against every listing, which became quadratic
    # as the catalog and its filter facets grew.
    counts = {}
    for it in working:
        for value in set(_as_list(idx_for[id(it)].get(key))):
            counts[value] = counts.get(value, 0) + 1

    raw_options = spec["fixed"] if spec.get("fixed") else counts.keys()
    return [
        {"value": value, "label": _option_label(key, value),
         "count": counts.get(value, 0), "checked": False}
        for value in raw_options
    ]


# --- Card builders (one per category) --------------------------------------

def _photo_urls(photos_qs):
    return _usable_images([
        (p.image.storage, p.image.name)
        for p in photos_qs
        if getattr(p, "image", None) and p.image.name
    ])


# category key -> (app namespace, name of the selection view)
# Hotels is the reference flow and keeps its own route; every other category
# now has a `flow_select` view backed by atrue_core.establishment_flow.
FLOW_ROUTE = {
    "hotel": ("hotels", "group_start"),
    "resort": ("resorts", "flow_select"),
    "staycation": ("staycations", "flow_select"),
    "restaurant": ("restaurants", "flow_select"),
    "package": ("tour_package", "flow_select"),
    "landmark": ("landmarks", "flow_select"),
    "activity": ("activities", "flow_select"),
}


def _can_book(request):
    """True when this visitor may open the booking flow directly.

    A signed-in, bookable customer goes straight to the selection page so the
    dates they searched with travel along. Anonymous visitors, admins and
    deactivated accounts keep the profile page, because the booking views are
    guarded by @login_required / @student_booking_required.
    """
    from accounts.views import is_admin_user

    user = getattr(request, "user", None)
    return bool(
        user is not None
        and user.is_authenticated
        and not is_admin_user(user)
        and getattr(user, "is_bookable", False)
    )


def _flow_cta(request, key, est_id, detail_url, label, stay_params=()):
    """Card CTA plus the secondary detail link, for every category.

    Returns the three keys a listing card needs, so every card offers the same
    two ways forward: book straight away, or read the profile first.
    """
    if not _can_book(request):
        return {"cta_url": detail_url, "cta_label": label,
                "detail_url": detail_url, "detail_label": "See Details"}
    namespace, route = FLOW_ROUTE[key]
    url = reverse("%s:%s" % (namespace, route), args=[est_id])
    stay = {}
    preserve = (
        "check_in", "check_out", "date", "time", "guests", "adults",
        "children", "rooms", *stay_params,
    )
    for name in dict.fromkeys(preserve):
        value = (request.GET.get(name) or "").strip()
        if value:
            stay[name] = value
    if stay:
        url += "?" + urlencode(stay)
    return {"cta_url": url, "cta_label": label,
            "detail_url": detail_url, "detail_label": "See Details"}


def _hotel_card(item, request):
    available = [r for r in item.rooms.all() if getattr(r, "status", "") == "AVAILABLE"]
    cheapest = _cheapest_rate(available)
    price, price_kind = price_display(cheapest)
    where = item.municipality or item.province or "the area"
    max_cap = max((r.capacity for r in available), default=0)
    images = _photo_urls(item.photos.all())
    if not images:
        for r in available[:2]:
            images += _photo_urls(r.photos.all())
    if not images:
        # Local fallback so every hotel card remains image-based even before
        # an administrator uploads property photos.
        images = [settings.STATIC_URL + 'img/hotel-placeholder.svg']
    score = guest_score(item)
    amenities = [a.name for a in item.amenities.all()][:4]
    detail_url = reverse("hotels:detail", args=[item.slug])
    cta = _flow_cta(request, "hotel", item.pk, detail_url, "Choose rooms",
                    stay_params=("check_in", "check_out", "rooms", "adults", "children"))
    return {
        "card_class": "bk-card--hotel bk-card--establishment",
        "title": item.name,
        "subtitle": "Hotel",
        "stars": star_rating(item),
        "location": item.location,
        "score": score,
        "score_label": score_label(score),
        "reviews": review_count(item),
        "meta": [
            ("fa-circle-check", "%d room%s available" % (len(available), "" if len(available) == 1 else "s")),
            ("fa-users", "up to %d guests" % max_cap) if max_cap else None,
            ("fa-clock", item.operating_schedule or "Open daily"),
            ("fa-concierge-bell", "%d amenit%s" % (len(amenities), "y" if len(amenities) == 1 else "ies")) if amenities else None,
        ],
        "tags": amenities,
        "desc": price_prose(price_kind, price,
                            "Comfortable rooms from {amount} per night near " + where + ".",
                            "Comfortable rooms near " + where + "."),
        "price": price,
        "price_kind": price_kind,
        "price_label": "/night",
        "imgs": images,
        "icon": "fa-hotel",
        "cta_url": cta["cta_url"],
        "cta_label": cta["cta_label"],
        # Secondary action on the card: full hotel profile page.
        "detail_label": cta["detail_label"],
        "detail_url": cta["detail_url"],
    }


def _resort_card(item, request):
    available = [u for u in item.units.all() if getattr(u, "status", "") == "AVAILABLE"]
    cheapest = _cheapest_rate(available)
    price, price_kind = price_display(cheapest)
    units = [u for u in item.units.all()]
    max_cap = max((u.capacity for u in units), default=0)
    images = _photo_urls(item.photos.all())
    if not images:
        for u in units[:2]:
            images += _photo_urls(u.photos.all())
    if not images:
        images = [settings.STATIC_URL + 'img/hotel-placeholder.svg']
    score = guest_score(item)
    services = [s.name for s in item.services.all()][:4]
    return {
        "card_class": "bk-card--establishment",
        "title": item.name,
        "subtitle": "Resort",
        "stars": star_rating(item),
        "location": item.location,
        "score": score,
        "score_label": score_label(score),
        "reviews": review_count(item),
        "meta": [m for m in [
            ("fa-umbrella-beach", "%d unit%s" % (len(units), "" if len(units) == 1 else "s")),
            ("fa-users", "up to %d guests" % max_cap) if max_cap else None,
            ("fa-clock", item.operating_schedule or "Open daily"),
            ("fa-concierge-bell", "%d service%s" % (len(services), "" if len(services) == 1 else "s")) if services else None,
        ] if m],
        "tags": services,
        "desc": price_prose(price_kind, price,
                            "Beach-front villa, cabana and room stays from {amount} per night.",
                            "Beach-front villa, cabana and room stays. Contact the resort for rates."),
        "price": price,
        "price_kind": price_kind,
        "price_label": "/night",
        "imgs": images,
        "icon": "fa-umbrella-beach",
        **_flow_cta(request, "resort", item.pk, reverse("resorts:detail", args=[item.slug]),
                    "Choose a villa", stay_params=("check_in", "check_out")),
    }


def _staycation_card(item, request):
    price, price_kind = price_display(item.rate)
    score = guest_score(item)
    services = [s.name for s in item.services.all()][:4]
    images = _photo_urls(item.photos.all())
    if not images:
        images = [settings.STATIC_URL + 'img/hotel-placeholder.svg']
    return {
        "card_class": "bk-card--establishment",
        "title": item.name,
        "subtitle": "Staycation",
        "stars": star_rating(item),
        "location": item.location,
        "score": score,
        "score_label": score_label(score),
        "reviews": review_count(item),
        "meta": [m for m in [
            ("fa-users", "sleeps %d" % item.capacity),
            ("fa-clock-rotate-left", item.house_rules.split("\n")[0] if item.house_rules else "Self check-in"),
            ("fa-concierge-bell", "%d add-on%s" % (len(services), "" if len(services) == 1 else "s")) if services else None,
        ] if m],
        "tags": services,
        "desc": price_prose(price_kind, price,
                            "A cozy private getaway at {amount} per night in "
                            + (item.municipality or item.province or "a quiet neighbourhood") + ".",
                            "A cozy private getaway in "
                            + (item.municipality or item.province or "a quiet neighbourhood") + "."),
        "price": price,
        "price_kind": price_kind,
        "price_label": "/night",
        "imgs": images,
        "icon": "fa-couch",
        **_flow_cta(request, "staycation", item.pk, reverse("staycations:detail", args=[item.slug]),
                    "Reserve this stay", stay_params=("check_in", "check_out")),
    }


def _package_card(item, request):
    price, price_kind = price_display(item.price)
    score = guest_score(item)
    inclusions = [p.strip() for p in (item.inclusions or "").replace("\n", ",").split(",") if p.strip()]
    plan_lines = [p.strip() for p in (item.inclusions or "").splitlines() if p.strip()]
    dest = item.destination_name or ", ".join(filter(None, [item.destination_city, item.destination_province])) or "Philippines"
    images = _photo_urls(item.photos.all())
    detail_url = reverse('tour_package:detail', args=[item.slug])
    package_actions = _flow_cta(request, 'package', item.pk, detail_url,
                                'Book this package', stay_params=('check_in',))
    from tour_package.scope import may_book_package
    if request.user.is_authenticated and not may_book_package(request, item.pk):
        package_actions.update(cta_url=detail_url, cta_label='See Details')
    return {
        "title": item.name,
        "subtitle": "Tour Package",
        "stars": star_rating(item),
        "location": dest,
        "score": score,
        "score_label": score_label(score),
        "reviews": review_count(item),
        "meta": [
            ("fa-clock", "%d day%s" % (item.duration_days, "" if item.duration_days == 1 else "s")),
            ("fa-users", "up to %d pax" % item.included_headcount),
            ("fa-calendar-check", "valid until %s" % item.validity_end_date.strftime("%b %d, %Y")),
        ],
        "plan": plan_lines,
        "card_class": "bk-card--package bk-card--establishment",
        "tags": (inclusions or ["All-inclusive itinerary"])[:4],
        "desc": item.description or price_prose(price_kind, price,
                            "An all-inclusive itinerary starting at {amount} per person.",
                            "An all-inclusive itinerary. Contact the agency for rates."),
        "price": price,
        "price_kind": price_kind,
        "price_label": "/person",
        "imgs": images,
        "icon": "fa-suitcase-rolling",
        **package_actions,
    }


def _restaurant_card(item, request):
    score = guest_score(item)
    price_class = ["₱", "₱₱", "₱₱₱"][_seed(item, "price") % 3]
    tables = list(item.tables.all())
    available = [t for t in tables if getattr(t, "status", "") == "AVAILABLE"]
    max_cap = max((t.capacity for t in tables), default=0)
    images = _photo_urls(item.photos.all())
    if not images:
        images = [settings.STATIC_URL + 'img/restaurant-placeholder.svg']
    return {
        "card_class": "bk-card--establishment",
        "title": item.name,
        "subtitle": item.cuisine_type or "Restaurant",
        "stars": star_rating(item),
        "location": item.location,
        "score": score,
        "score_label": score_label(score),
        "reviews": review_count(item),
        "meta": [
            ("fa-clock", item.operating_hours or "Open daily"),
            ("fa-chair", "%d tables · seats up to %d" % (len(tables), max_cap)),
            ("fa-user-check", "%d tables free now" % len(available)),
        ],
        "tags": [item.cuisine_type] if item.cuisine_type else [],
        "desc": "%s dining · reserve a table ahead with no booking fee." % (item.cuisine_type or "Local"),
        "price": price_class,
        "price_is_class": True,
        "price_label": "avg. /person",
        "imgs": images,
        "icon": "fa-utensils",
        **_flow_cta(request, "restaurant", item.pk, reverse("restaurants:detail", args=[item.slug]),
                    "Reserve a table", stay_params=("check_in",)),
    }


def _landmark_card(item, request):
    score = guest_score(item)
    spot = item.category == "TOURIST_SPOT"
    images = _photo_urls(item.photos.all())
    if not images:
        images = [settings.STATIC_URL + 'img/landmark-placeholder.svg']
    # The search card renders one cover plus four thumbnails. Keep its count
    # and clickable gallery aligned with those five photos.
    images = images[:5]
    price, price_kind = price_display(item.entry_fee, free_when_zero=True)
    return {
        "card_class": "bk-card--establishment",
        "title": item.name,
        "subtitle": "Tourist Spot" if spot else "Landmark",
        "stars": star_rating(item),
        "location": item.location,
        "score": score,
        "score_label": score_label(score),
        "reviews": review_count(item),
        "meta": [m for m in [
            ("fa-clock", item.open_hours or "Check official hours"),
            ("fa-users", "%d visitors/day" % item.capacity) if item.capacity else ("fa-users", "Open visit"),
            ("fa-route", "Guided tours available") if item.guided_tour_rate else None,
        ] if m],
        "tags": [],
        "desc": item.description or price_prose(price_kind, price,
                            "Entry pass for one visitor at {amount}.",
                            "Free entry for one visitor."),
        "price": price,
        "price_kind": price_kind,
        "price_label": "/visitor",
        "imgs": images,
        "icon": "fa-mountain" if spot else "fa-landmark",
        **_flow_cta(request, "landmark", item.pk, reverse("landmarks:detail", args=[item.pk]),
                    "Get tickets", stay_params=("check_in",)),
    }


def _activity_card(item, request):
    score = guest_score(item)
    label = ACTIVITY_CATEGORY_LABELS.get(item.category, item.category)
    images = _usable_images([item.image.name]) if item.image else []
    images += _photo_urls(item.photos.all())
    if not images:
        images = [settings.STATIC_URL + 'img/activity-placeholder.svg']
    price, price_kind = price_display(item.fee)
    rate = item.get_rate_type_display().lower() if hasattr(item, "get_rate_type_display") else "person"
    detail_url = reverse("activities:detail", args=[item.pk])
    cta = (
        _flow_cta(request, "activity", item.pk, detail_url, "Book now", stay_params=("check_in",))
        if item.bookable else
        {"cta_url": detail_url, "cta_label": "Currently unavailable",
         "detail_url": detail_url, "detail_label": "See Details"}
    )
    return {
        "card_class": "bk-card--establishment",
        "title": item.name,
        "subtitle": label,
        "stars": star_rating(item),
        "location": item.full_location,
        "score": score,
        "score_label": score_label(score),
        "reviews": review_count(item),
        "meta": [m for m in [
            ("fa-clock", item.duration),
            ("fa-person-walking", "%d pax max" % item.capacity),
            ("fa-building", item.provider.name) if item.provider_id else None,
        ] if m],
        "tags": [label] + ([item.meeting_point] if item.meeting_point else []),
        "desc": item.description or price_prose(price_kind, price,
                            "Book a slot with a verified provider for {amount} per " + rate + ".",
                            "Book a slot with a verified provider. Contact the provider for rates."),
        "price": price,
        "price_kind": price_kind,
        "price_label": "/" + rate,
        "imgs": images,
        "icon": "fa-person-hiking",
        **cta,
    }


# --- Sorts -----------------------------------------------------------------

SORT_OPTIONS = {
    "hotel": [("recommended", "Recommended"), ("price", "Lowest price"), ("rating", "Highest rated"), ("stars", "Star rating")],
    "resort": [("recommended", "Recommended"), ("price", "Lowest price"), ("rating", "Highest rated"), ("stars", "Star rating")],
    "staycation": [("recommended", "Recommended"), ("price", "Lowest price"), ("rating", "Highest rated")],
    "package": [("recommended", "Recommended"), ("price", "Lowest price"), ("rating", "Highest rated"), ("duration", "Longest trip")],
    "restaurant": [("recommended", "Recommended"), ("capacity", "Larger tables"), ("rating", "Highest rated")],
    "landmark": [("recommended", "Recommended"), ("price", "Lowest fee"), ("rating", "Highest rated")],
    "activity": [("recommended", "Recommended"), ("price", "Lowest price"), ("rating", "Highest rated"), ("duration", "Longest duration")],
}


def _apply_sort(category_key, items, request, idx_for):
    sort = (request.GET.get("sort") or "recommended").strip()
    allowed = {s[0] for s in SORT_OPTIONS.get(category_key, [])}
    if sort not in allowed:
        sort = "recommended"

    def keyfn(it):
        idx = idx_for[id(it)]
        if sort == "price":
            v = idx.get("price")
            return (0, v) if v is not None else (1, None)
        if sort == "rating":
            return -(idx.get("score") or 0)
        if sort == "stars":
            return -(idx.get("stars") or 0)
        if sort == "duration":
            return -(_seed(it, "duration") % 60)
        if sort == "capacity":
            return -(_seed(it, "capacity") % 12)
        return 0

    if sort == "recommended":
        return list(items)
    return sorted(items, key=keyfn)


# --- Master context builder ------------------------------------------------

def build_search_context(request, category_key, items):
    """Turn a plain queryset/list of objects into the full page context."""
    cfg = FALLBACK_CONFIG[category_key]
    items = list(items)
    idx_for = {id(it): _category_indexer(category_key)(it) for it in items}
    loc_for = {id(it): _item_loc(category_key, it) for it in items}

    loc_country = (request.GET.get("loc_country") or "").strip()
    loc_province = (request.GET.get("loc_province") or "").strip()
    loc_municipality = (request.GET.get("loc_municipality") or "").strip()
    loc_barangay = (request.GET.get("loc_barangay") or "").strip()

    q = (request.GET.get("q") or "").strip()
    if q:
        items = [it for it in items if q.lower() in idx_for[id(it)]["search"]]

    if loc_country or loc_province or loc_municipality or loc_barangay:
        # Resolved once per request rather than per item.
        country_keys = country_province_keys(loc_country) if loc_country else None
        items = [
            it for it in items
            if location_matches(
                loc_for[id(it)], loc_province, loc_municipality, loc_barangay,
                loc_text=loc_for[id(it)].get("loc_text"),
                country=loc_country, country_provinces=country_keys,
            )
        ]

    pmin = _num(request.GET.get("price_min"))
    pmax = _num(request.GET.get("price_max"))
    if pmin is not None or pmax is not None:
        items = [it for it in items if _price_matches(idx_for[id(it)].get("price"), pmin, pmax)]

    working = items

    groups = []
    selected = {}
    for spec in FILTER_SPECS[category_key]:
        if spec["type"] == "price":
            groups.append({
                "group": spec["group"],
                "type": "price",
                "param_min": spec["param_min"],
                "param_max": spec["param_max"],
                "value_min": request.GET.get(spec["param_min"], ""),
                "value_max": request.GET.get(spec["param_max"], ""),
            })
            continue
        param = spec["param"]
        key = spec["key"]
        chosen = [v for v in request.GET.getlist(param) if v]
        selected[key] = chosen
        options = _derive_options(spec, working, idx_for)
        for opt in options:
            opt["checked"] = opt["value"] in chosen
        groups.append({"group": spec["group"], "type": "choice", "param": param, "options": options})

    def _matches(it):
        idx = idx_for[id(it)]
        for key, chosen in selected.items():
            if not chosen:
                continue
            vals = _as_list(idx.get(key))
            if not any(c in vals for c in chosen):
                return False
        return True

    filtered = [it for it in working if _matches(it)]
    filtered = _apply_sort(category_key, filtered, request, idx_for)
    total_results = len(filtered)
    result_page = Paginator(filtered, 16).get_page(request.GET.get("page"))

    cards = [cfg["card"](it, request) for it in result_page.object_list]
    for card in cards:
        card["imgs_json"] = json.dumps(card.get("imgs") or [])

    page_query = request.GET.copy()
    page_query.pop(LIVE_FLAG, None)
    previous_page_url = next_page_url = None
    if result_page.has_previous():
        page_query["page"] = result_page.previous_page_number()
        previous_page_url = request.path + "?" + page_query.urlencode()
    if result_page.has_next():
        page_query["page"] = result_page.next_page_number()
        next_page_url = request.path + "?" + page_query.urlencode()

    active_count = sum(1 for vals in selected.values() for _ in vals if vals) + (1 if pmin is not None or pmax is not None else 0)

    preserve = ["q", "guests", "tables", "children", "rooms", "adults", "loc_country", "loc_province", "loc_municipality", "loc_barangay"]
    clear_params = {k: request.GET[k] for k in preserve if request.GET.get(k)}
    clear_url = request.path + ("?" + urlencode(clear_params) if clear_params else "")

    sort = (request.GET.get("sort") or "recommended").strip()
    if sort not in {s[0] for s in SORT_OPTIONS.get(category_key, [])}:
        sort = "recommended"

    sort_options = []
    for value, label in SORT_OPTIONS.get(category_key, []):
        params = {k: v for k, v in request.GET.lists() if k != "sort"}
        if value != "recommended":
            params["sort"] = [value]
        merged = []
        for k, vals in params.items():
            for v in vals:
                merged.append((k, v))
        sort_options.append({
            "value": value,
            "label": label,
            "active": value == sort,
            "url": request.path + ("?" + urlencode(merged) if merged else ""),
        })

    categories_nav = []
    for cat in CATEGORIES:
        categories_nav.append({
            "key": cat["key"],
            "label": cat["label"],
            "icon": cat["icon"],
            "url": reverse(CATEGORY_URL[cat["key"]]),
            "active": cat["key"] == category_key,
        })

    guests_adults = _int_req(request, "adults", cfg["default_adults"])
    guests_children = _int_req(request, "children", 0)
    guests_rooms = _int_req(request, "rooms", 1)
    guests_count = _int_req(request, "guests", cfg.get("default_guests", cfg["default_adults"]))
    tables_count = _int_req(request, "tables", 1)

    dest_suggestions = list(POPULAR_DESTINATIONS)
    for it in working:
        for v in _as_list(idx_for[id(it)].get("province")):
            if v != "—" and v not in dest_suggestions:
                dest_suggestions.append(v)

    context = {
        "category": category_key,
        "cfg": cfg,
        "categories": categories_nav,
        "things": cards,
        "total": total_results,
        "result_page": result_page,
        "previous_page_url": previous_page_url,
        "next_page_url": next_page_url,
        "sort": sort,
        "sort_options": sort_options,
        "filter_groups": groups,
        "active_filters": active_count,
        "clear_url": clear_url,
        "search_q": q,
        "loc_country": loc_country,
        "loc_province": loc_province,
        "loc_municipality": loc_municipality,
        "loc_barangay": loc_barangay,
        "loc_display": location_display(loc_province, loc_municipality, loc_barangay, loc_country),
        "check_in": request.GET.get("check_in", ""),
        "check_out": request.GET.get("check_out", ""),
        "reserve_date": request.GET.get("date", ""),
        "reserve_time": request.GET.get("time", ""),
        "guests": {"adults": guests_adults, "children": guests_children, "rooms": guests_rooms},
        "guests_count": guests_count,
        "tables_count": tables_count,
        "dest_suggestions": dest_suggestions,
        "can_manage": bool(getattr(request.user, "is_platform_manager", False)),
        "manage_url": reverse(cfg["manage_url_name"]) if cfg.get("manage_url_name") else None,
        "management_url": reverse(cfg["management_url_name"]) if cfg.get("management_url_name") else None,
        "result_kicker": cfg["result_kicker"],
        "hero_title": cfg["hero_title"],
        "hero_sub": cfg["hero_sub"],
    }
    return context


def _int_req(request, name, default):
    try:
        return max(0, int(request.GET.get(name, default)))
    except (TypeError, ValueError):
        return default


FALLBACK_CONFIG = {
    "hotel": {
        "default_adults": 2,
        "card": _hotel_card,
        "manage_url_name": "hotels:add",
        "result_kicker": "places to stay",
        "hero_title": "Find your perfect stay",
        "hero_sub": "Search hotels, compare room rates and check availability across partner properties.",
        "date_mode": "range",
        "search_icon": "fa-location-dot",
    },
    "resort": {
        "default_adults": 2,
        "card": _resort_card,
        "manage_url_name": "resorts:add",
        "result_kicker": "beach escapes",
        "hero_title": "Escape to a resort",
        "hero_sub": "Browse villas, rooms and cabanas at partner resorts with service add-ons.",
        "date_mode": "range",
        "search_icon": "fa-location-dot",
    },
    "staycation": {
        "default_adults": 2,
        "card": _staycation_card,
        "manage_url_name": "staycations:add",
        "result_kicker": "cozy getaways",
        "hero_title": "Staycations worth staying for",
        "hero_sub": "Private homes and lofts with self check-in and flexible stays.",
        "date_mode": "range",
        "search_icon": "fa-location-dot",
    },
    "package": {
        "default_adults": 2,
        "card": _package_card,
        "manage_url_name": "tour_package:add_package",
        "result_kicker": "all-inclusive trips",
        "hero_title": "All-in vacations, one price",
        "hero_sub": "Flights, stays, activities and transport bundled into effortless itineraries.",
        "date_mode": "range",
        "search_icon": "fa-location-dot",
    },
    "restaurant": {
        "default_adults": 2,
        "card": _restaurant_card,
        "manage_url_name": "restaurants:add",
        "result_kicker": "dining spots",
        "hero_title": "Book a table, skip the wait",
        "hero_sub": "Browse partner restaurants, check tables and reserve ahead with no booking fee.",
        "date_mode": "single",
        "search_icon": "fa-utensils",
    },
    "landmark": {
        "default_adults": 2,
        "card": _landmark_card,
        "manage_url_name": "landmarks:add_landmark",
        "result_kicker": "must-see destinations",
        "hero_title": "Explore landmarks & tourist spots",
        "hero_sub": "Buy entry passes in advance and plan your visit date.",
        "date_mode": "single",
        "show_time": True,
        "time_slots": ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
        "search_icon": "fa-mountain",
    },
    "activity": {
        "default_adults": 2,
        "card": _activity_card,
        "manage_url_name": "activities:add_activity",
        "management_url_name": "activities:manage",
        "result_kicker": "adventures & tours",
        "hero_title": "Adventures with open slots",
        "hero_sub": "Book thrilling experiences with certified providers — ziplines, treks, watersports and more.",
        "date_mode": "single",
        "search_icon": "fa-person-hiking",
    },
}


# Marker query flag the listing JavaScript adds to ask for just the results
# region instead of the whole page. Keeping it a query flag means every
# category list view is covered by the one render_search_page below, with no
# extra URL route and no duplicated filtering.
LIVE_FLAG = "_live"


def _live_query(request):
    """The request's own query string without the live marker."""
    pairs = [(k, v) for k, vs in request.GET.lists() if k != LIVE_FLAG for v in vs]
    return urlencode(pairs)


def _live_response(request, context):
    """Return only what changes when a filter changes: the results markup, the
    per-option counts, the active-filter count and the resulting query string.

    The markup comes from the same ``search/_results.html`` partial the full
    page includes, so a live update and a full page load are identical.
    """
    option_counts = {}
    for group in context["filter_groups"]:
        if group.get("type") != "choice":
            continue
        option_counts[group["param"]] = {
            str(opt["value"]): opt.get("count", 0) for opt in group.get("options", [])
        }

    return JsonResponse({
        "html": render_to_string("search/_results.html", context, request=request),
        "total": context["total"],
        "option_counts": option_counts,
        "active_filters": context["active_filters"],
        "query": _live_query(request),
        "path": request.path,
    })


def render_search_page(request, category_key, objects):
    """Render any category listing with the shared Agoda-style search layout.

    Also answers the live-filter request used by the listing JavaScript, so a
    filter click updates the results in place instead of reloading the page.
    Filtering itself is unchanged: both paths run the same
    ``build_search_context``.
    """
    context = build_search_context(request, category_key, objects)
    if request.GET.get(LIVE_FLAG) == "1":
        return _live_response(request, context)
    return render(request, "search/search_page.html", context)

