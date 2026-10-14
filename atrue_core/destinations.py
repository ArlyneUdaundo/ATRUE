import threading
import time
from functools import lru_cache

from django.db.models import Q
from django.shortcuts import render
from django.utils.text import slugify
from django.urls import reverse
from urllib.parse import urlencode


DESTINATIONS = {
    "palawan": {
        "name": "Palawan",
        "country": "Philippines",
        "tagline": "Island adventures, turquoise lagoons, and unforgettable sunsets.",
        "image": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["El Nido lagoons", "Coron island hopping", "Puerto Princesa"],
    },
    "boracay": {
        "name": "Boracay",
        "country": "Philippines",
        "tagline": "White-sand beaches, clear waters, and vibrant island life.",
        "image": "https://images.unsplash.com/photo-1518509562904-e7ef99cdcc86?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["White Beach", "Puka Shell Beach", "Island activities"],
    },
    "siargao": {
        "name": "Siargao",
        "country": "Philippines",
        "tagline": "A laid-back surf destination surrounded by tropical scenery.",
        "image": "https://images.unsplash.com/photo-1502680390469-be75c86b636f?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Cloud 9", "Sugba Lagoon", "Naked Island"],
    },
    "palaui-island": {
        "name": "Palaui Island",
        "country": "Philippines",
        "tagline": "Untouched coastlines, rolling hills, and dramatic sea views.",
        "image": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Cape Engaño", "Island trails", "Beach coves"],
    },
    "batanes": {
        "name": "Batanes",
        "country": "Philippines",
        "tagline": "Peaceful landscapes, stone houses, and breathtaking coastal roads.",
        "image": "https://images.unsplash.com/photo-1500534623283-312aade485b7?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Marlboro Hills", "Basco Lighthouse", "Sabtang Island"],
    },
    "cebu": {
        "name": "Cebu",
        "country": "Philippines",
        "tagline": "A mix of city energy, heritage, beaches, and outdoor adventures.",
        "image": "https://images.unsplash.com/photo-1548013146-72479768bada?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Kawasan Falls", "Moalboal", "Cebu heritage sites"],
    },
    "davao": {
        "name": "Davao",
        "country": "Philippines",
        "tagline": "A gateway to nature, culture, and southern Philippine adventures.",
        "image": "https://images.unsplash.com/photo-1537996194471-e657df975ab4?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Mount Apo", "Samal Island", "Philippine Eagle Center"],
    },
    "el-nido": {
        "name": "El Nido",
        "country": "Philippines",
        "tagline": "Limestone cliffs, hidden lagoons, and crystal-clear island waters.",
        "image": "https://images.unsplash.com/photo-1505881502353-a1986add3762?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Big Lagoon", "Small Lagoon", "Nacpan Beach"],
    },
    "vigan": {
        "name": "Vigan",
        "country": "Philippines",
        "tagline": "Historic streets, heritage architecture, and Ilocano culture.",
        "image": "https://images.unsplash.com/photo-1524231757912-21f4fe3a7200?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Calle Crisologo", "Heritage houses", "Local cuisine"],
    },
    "baguio": {
        "name": "Baguio",
        "country": "Philippines",
        "tagline": "Cool mountain weather, pine forests, and a relaxed city escape.",
        "image": "https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Burnham Park", "Mines View Park", "Camp John Hay"],
    },
    "manila": {
        "name": "Manila",
        "country": "Philippines",
        "tagline": "A lively capital with history, culture, shopping, and dining.",
        "image": "https://images.unsplash.com/photo-1555899434-94d1368aa7af?auto=format&fit=crop&w=1400&q=85",
        "highlights": ["Intramuros", "Rizal Park", "Manila Bay"],
    },
}


_DESTINATION_OPTIONS_LOCK = threading.Lock()
_DESTINATION_SEARCH_LOCK = threading.Lock()


@lru_cache(maxsize=2)
def _destination_options_cached(cache_period):
    return _build_destination_options()


def destination_options():
    """Cache the destination catalogue for five minutes per app process."""
    with _DESTINATION_OPTIONS_LOCK:
        return _destination_options_cached(int(time.monotonic() // 300))


def _build_destination_options():
    """Return curated destinations plus every location used by live listings."""
    from activities.models import Activity, ActivityProvider
    from airlines.models import Flight
    from hotels.models import Hotel
    from landmarks.models import Landmark
    from restaurants.models import Restaurant
    from resorts.models import Resort
    from staycations.models import Staycation
    from tour_package.models import TourPackage

    ordered_names = list(dict.fromkeys(
        value["name"] for value in DESTINATIONS.values()
    ))
    discovered = set()

    location_pairs = (
        Hotel.objects.filter(status=Hotel.Status.ACTIVE)
        .values_list("province", "municipality"),
        Resort.objects.filter(status=Resort.Status.ACTIVE)
        .values_list("province", "municipality"),
        Staycation.objects.filter(status=Staycation.Status.ACTIVE)
        .values_list("province", "municipality"),
        Landmark.objects.filter(status=Landmark.Status.ACTIVE)
        .values_list("province", "municipality"),
        Activity.objects.filter(
            status=Activity.Status.ACTIVE,
            provider__status="ACTIVE",
            provider__verified=True,
        ).values_list("location_province", "location_municipality"),
        TourPackage.objects.filter(status=TourPackage.Status.ACTIVE)
        .values_list("destination_province", "destination_city"),
        Flight.objects.exclude(status__in=("CANCELLED", "COMPLETED"))
        .values_list("origin_province", "origin_municipality"),
        Flight.objects.exclude(status__in=("CANCELLED", "COMPLETED"))
        .values_list("destination_province", "destination_municipality"),
    )
    for pairs in location_pairs:
        for province, municipality in pairs.distinct():
            for value in (municipality, province):
                name = (value or "").strip()
                if name:
                    discovered.add(name)

    for location in Restaurant.objects.filter(
        status=Restaurant.Status.ACTIVE
    ).values_list("location", flat=True).distinct():
        discovered.update(
            part.strip() for part in (location or "").split(",") if part.strip()
        )

    curated_keys = {slugify(name) for name in ordered_names}
    ordered_names.extend(sorted(
        (name for name in discovered if slugify(name) not in curated_keys),
        key=str.casefold,
    ))
    return [
        {"name": name, "slug": slugify(name)}
        for name in ordered_names
    ]


@lru_cache(maxsize=8)
def _destination_search_options_cached(cache_period, destination_names, properties_only):
    destinations = [
        {"name": name, "slug": slug}
        for name, slug in destination_names
    ]
    return _build_destination_search_options(destinations, properties_only)


def destination_search_options(destinations=None, properties_only=False):
    """Cache the expensive autocomplete catalogue for five minutes."""
    if destinations is None and not properties_only:
        destinations = destination_options()
    destination_names = tuple(
        (str(item.get("name", "")), str(item.get("slug", "")))
        for item in (destinations or ())
    )
    with _DESTINATION_SEARCH_LOCK:
        return _destination_search_options_cached(
            int(time.monotonic() // 300), destination_names, bool(properties_only)
        )


def _build_destination_search_options(destinations=None, properties_only=False):
    """Return destinations and active listing names for homepage autocomplete.

    When ``properties_only`` is True the suggestions are restricted to live
    property names (hotels, resorts, staycations, restaurants, tours) — no
    curated destinations, cities, regions, countries, or airport names.
    """
    from activities.models import Activity, ActivityProvider
    from transportation.models import Agency
    from hotels.models import Hotel
    from landmarks.models import Landmark
    from restaurants.models import Restaurant
    from resorts.models import Resort
    from staycations.models import Staycation
    from tour_package.models import TourPackage

    suggestions = {}

    def add(name, categories):
        normalized = name.strip() if name else ""
        if not normalized:
            return
        entry = suggestions.setdefault(
            normalized.casefold(),
            {"name": normalized, "categories": {"all"}},
        )
        entry["categories"].update(categories)

    all_service_categories = {
        "hotels", "resorts", "staycations", "restaurants", "tours",
        "activities", "landmarks", "landtransportation",
    }
    if not properties_only:
        for option in (destinations if destinations is not None else destination_options()):
            add(option["name"], all_service_categories)

        from airlines.models import Airport
        airport_places = Airport.objects.filter(
            status=Airport.Status.ACTIVE
        ).values_list("city", "region", "country").distinct()
        for city, region, country in airport_places:
            for place in (city, region, country):
                add(place, all_service_categories)

    catalog_sources = (
        (Hotel.objects.filter(status=Hotel.Status.ACTIVE), "hotels"),
        (Resort.objects.filter(status=Resort.Status.ACTIVE), "resorts"),
        (Staycation.objects.filter(status=Staycation.Status.ACTIVE), "staycations"),
        (Restaurant.objects.filter(status=Restaurant.Status.ACTIVE), "restaurants"),
        (Landmark.objects.filter(status=Landmark.Status.ACTIVE), ("landmarks", "tours")),
        (
            Activity.objects.filter(
                status=Activity.Status.ACTIVE,
                provider__status="ACTIVE",
                provider__verified=True,
            ),
            ("activities", "tours"),
        ),
        (Agency.objects.filter(status=Agency.Status.ACTIVE), "landtransportation"),
        (TourPackage.objects.filter(status=TourPackage.Status.ACTIVE), "tours"),
    )
    for queryset, category in catalog_sources:
        for name in queryset.values_list("name", flat=True):
            add(name, set(category) if isinstance(category, tuple) else {category})

    return [
        {
            "name": entry["name"],
            "slug": slugify(entry["name"]),
            "categories": " ".join(sorted(entry["categories"])),
        }
        for entry in sorted(
            suggestions.values(), key=lambda item: item["name"].casefold()
        )
    ]


def destination_detail(request, slug):
    destination = DESTINATIONS.get(slug)
    if destination is None:
        destination_name = slug.replace("-", " ").title()
        destination = {
            "name": destination_name,
            "country": "Philippines",
            "tagline": f"Explore places and experiences in {destination_name}.",
            "image": "",
            "highlights": [],
        }

    name = destination["name"]
    from activities.models import Activity, ActivityProvider
    from transportation.models import Agency
    from airlines.models import Flight
    from hotels.models import Hotel
    from landmarks.models import Landmark
    from restaurants.models import Restaurant
    from resorts.models import Resort
    from staycations.models import Staycation
    from tour_package.models import TourPackage

    sections = [
        {
            "title": "Flights",
            "icon": "fa-plane",
            "search_url": reverse("airlines:list") + "?" + urlencode({
                "destination": name,
            }),
            "items": [
                {
                    "name": f"{item.flight_number}: {item.origin} to {item.destination}",
                    "url": reverse("airlines:flight_detail", args=[item.slug]),
                }
                for item in Flight.objects.filter(
                    status__in=(Flight.Status.SCHEDULED, Flight.Status.DELAYED),
                    itinerary__isnull=True,
                ).filter(
                    Q(origin__icontains=name) | Q(destination__icontains=name)
                    | Q(origin_province__icontains=name)
                    | Q(origin_municipality__icontains=name)
                    | Q(destination_province__icontains=name)
                    | Q(destination_municipality__icontains=name)
                ).order_by("departure_time")
            ],
        },
        {
            "title": "Landmarks",
            "icon": "fa-landmark",
            "search_url": reverse("landmarks:list") + "?" + urlencode({"q": name}),
            "items": [
                {"name": item.name, "url": reverse("landmarks:flow_select", args=[item.pk])}
                for item in Landmark.objects.filter(
                    status=Landmark.Status.ACTIVE,
                ).filter(
                    Q(province__icontains=name) | Q(municipality__icontains=name)
                ).order_by("name")
            ],
        },
        {
            "title": "Hotels",
            "icon": "fa-hotel",
            "search_url": reverse("hotels:list") + "?" + urlencode({"q": name}),
            "items": [
                {"name": item.name, "url": reverse("hotels:detail", args=[item.slug])}
                for item in Hotel.objects.filter(
                    status=Hotel.Status.ACTIVE,
                ).filter(
                    Q(province__icontains=name) | Q(municipality__icontains=name)
                ).order_by("name")
            ],
        },
        {
            "title": "Resorts",
            "icon": "fa-umbrella-beach",
            "search_url": reverse("resorts:list") + "?" + urlencode({"q": name}),
            "items": [
                {"name": item.name, "url": reverse("resorts:detail", args=[item.slug])}
                for item in Resort.objects.filter(
                    status=Resort.Status.ACTIVE,
                ).filter(
                    Q(province__icontains=name) | Q(municipality__icontains=name)
                ).order_by("name")
            ],
        },
        {
            "title": "Staycations",
            "icon": "fa-couch",
            "search_url": reverse("staycations:list") + "?" + urlencode({"q": name}),
            "items": [
                {"name": item.name, "url": reverse("staycations:detail", args=[item.slug])}
                for item in Staycation.objects.filter(
                    status=Staycation.Status.ACTIVE,
                ).filter(
                    Q(province__icontains=name) | Q(municipality__icontains=name)
                ).order_by("name")
            ],
        },
        {
            "title": "Restaurants",
            "icon": "fa-utensils",
            "search_url": reverse("restaurants:list") + "?" + urlencode({"q": name}),
            "items": [
                {"name": item.name, "url": reverse("restaurants:detail", args=[item.slug])}
                for item in Restaurant.objects.filter(
                    status=Restaurant.Status.ACTIVE,
                    location__icontains=name,
                ).order_by("name")
            ],
        },
        {
            "title": "Tours",
            "icon": "fa-suitcase-rolling",
            "search_url": reverse("tour_package:list") + "?" + urlencode({"q": name}),
            "items": [
                {"name": item.name, "url": reverse("tour_package:detail", args=[item.slug])}
                for item in TourPackage.objects.filter(
                    status=TourPackage.Status.ACTIVE,
                ).filter(
                    Q(destination_name__icontains=name)
                    | Q(destination_city__icontains=name)
                    | Q(destination_province__icontains=name)
                ).order_by("name")
            ],
        },
        {
            "title": "Activities",
            "icon": "fa-person-hiking",
            "search_url": reverse("activities:list") + "?" + urlencode({"q": name}),
            "items": [
                {"name": item.name, "url": reverse("activities:flow_select", args=[item.pk])}
                for item in Activity.objects.filter(
                    status=Activity.Status.ACTIVE,
                    provider__status=ActivityProvider.Status.ACTIVE,
                    provider__verified=True,
                ).filter(
                    Q(location__icontains=name) | Q(location_province__icontains=name)
                    | Q(location_municipality__icontains=name)
                ).order_by("name")
            ],
        },
    ]
    return render(request, "destination_detail.html", {
        "destination": destination,
        "slug": slug,
        "sections": sections,
    })
