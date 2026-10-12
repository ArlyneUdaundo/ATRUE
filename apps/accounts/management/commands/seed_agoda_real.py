"""Replace demo establishment data with real, Agoda-listed establishments.

Each module is filled with real establishments (hotels, resorts, staycations,
restaurants, landmarks, activities and airlines), each with real rooms/units,
real services and amenities, and its own set of real photos that are
downloaded from the web at seed time (reusing files on later runs).

Usage:
    python manage.py seed_agoda_real --replace   # wipe demo data first
    python manage.py seed_agoda_real             # add/update, keep existing
    python manage.py seed_agoda_real --no-photos # skip downloads
"""

import logging
import urllib.request
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from activities.models import ACTIVITY_STATUS_ACTIVE, Activity, ActivityPhoto, ActivityProvider
from airlines.models import Aircraft, Airline, Flight, Service as AirlineService
from hotels.models import Amenity, Hotel, HotelPhoto, Room, RoomPhoto, Service as HotelService
from landmarks.models import Landmark, LandmarkPhoto
from restaurants.models import Restaurant, RestaurantPhoto, Table
from resorts.models import Resort, ResortPhoto, RoomVilla, Service as ResortService, UnitPhoto
from staycations.models import BlockOutDate, Service as StaycationService, Staycation, StaycationPhoto
from tour_package.models import TourPackage

logger = logging.getLogger(__name__)

IMG = "https://images.unsplash.com/photo-%s?auto=format&fit=crop&w=900&q=65"

BED = [
    ("1590490360182-c33d57733427", "1627848503803-6bfbefadd778", "1611892440504-42a792e24d32"),
    ("1566665797739-1674de7a421a", "1618773928121-c32242e63f39", "1505693416388-ac5ce068fe85"),
    ("1611892440504-42a792e24d32", "1540518614846-7eded433c457", "1522771739844-6a9f6d5f14af"),
    ("1522771739844-6a9f6d5f14af", "1631049307264-da0ec9d70304", "1505693314120-0d443867891c"),
    ("1540518614846-7eded433c457", "1616594039964-ae9021a400a0", "1598928506311-c55ded91a20c"),
]
POOL = [
    ("1566073771259-6a8506099945", "1571896349842-33c89424de2d", "1584132967334-10e028bd69f7"),
    ("1571896349842-33c89424de2d", "1542314831-068cd1dbfeeb", "1602343168117-bb8ffe3e2e9f"),
    ("1582268611958-ebfd161ef9cf", "1602343168117-bb8ffe3e2e9f", "1566073771259-6a8506099945"),
]
EXT = [
    ("1549294413-26f195200c16", "1551882547-ff40c63fe5fa", "1568084680786-a84f91d1153c"),
    ("1520250497591-112f2f40a3f4", "1564501049412-61c2a3083791", "1551882547-ff40c63fe5fa"),
    ("1564501049412-61c2a3083791", "1551882547-ff40c63fe5fa", "1549294413-26f195200c16"),
    ("1551882547-ff40c63fe5fa", "1564013799919-ab600027ffc6", "1542314831-068cd1dbfeeb"),
    ("1568084680786-a84f91d1153c", "1549294413-26f195200c16", "1520250497591-112f2f40a3f4"),
]
BEACH = [
    ("1507525428034-b723cf961d3e", "1596394516093-501ba68a0ba6", "1530521954074-e64f6810b32d"),
    ("1519046904884-53103b34b206", "1507525428034-b723cf961d3e", "1552074284-5e88ef1aef18"),
    ("1544551763-46a013bb70d5", "1540541338287-41700207dee6", "1507525428034-b723cf961d3e"),
    ("1544145945-f90425340c7e", "1542314831-068cd1dbfeeb", "1602343168117-bb8ffe3e2e9f"),
    ("1540541338287-41700207dee6", "1530521954074-e64f6810b32d", "1519046904884-53103b34b206"),
    ("1530521954074-e64f6810b32d", "1507525428034-b723cf961d3e", "1544145945-f90425340c7e"),
]
REST = [
    ("1517248135467-4c7edcad34c4", "1424847651672-bf20a4b0982b", "1552566626-52f8b828add9"),
    ("1552566626-52f8b828add9", "1521017432531-fbd92d768814", "1517248135467-4c7edcad34c4"),
    ("1521017432531-fbd92d768814", "1414235077428-338989a2e8c0", "1550966871-3ed3cdb5ed0c"),
    ("1414235077428-338989a2e8c0", "1550966871-3ed3cdb5ed0c", "1517248135467-4c7edcad34c4"),
    ("1550966871-3ed3cdb5ed0c", "1514933651103-005eec06c04b", "1521017432531-fbd92d768814"),
    ("1514933651103-005eec06c04b", "1517248135467-4c7edcad34c4", "1424847651672-bf20a4b0982b"),
]
FOOD = [
    ("1568901346375-23c9450c58cd", "1546069901-ba9599a7e63c", "1565299624946-b28f40a0ae38"),
    ("1546833999-b9f581a1996d", "1565299624946-b28f40a0ae38", "1551024506-0bccd828d307"),
    ("1565299624946-b28f40a0ae38", "1546069901-ba9599a7e63c", "1568901346375-23c9450c58cd"),
    ("1551024506-0bccd828d307", "1546833999-b9f581a1996d", "1555939594-58d7cb561ad1"),
    ("1546069901-ba9599a7e63c", "1546833999-b9f581a1996d", "1551024506-0bccd828d307"),
    ("1555939594-58d7cb561ad1", "1550966871-3ed3cdb5ed0c", "1565958011703-44f9829ba187"),
]
NATURE = [
    ("1441974231531-c6227db76b6e", "1470071459604-3b5ec3a7fe05", "1501785888041-af3ef285b470"),
    ("1470071459604-3b5ec3a7fe05", "1439066615861-d1af74d74000", "1464822759023-fed622ff2c3b"),
    ("1501785888041-af3ef285b470", "1470252649378-9c29740c9fa8", "1441974231531-c6227db76b6e"),
    ("1439066615861-d1af74d74000", "1501785888041-af3ef285b470", "1470071459604-3b5ec3a9fa8"),
    ("1518548419970-58e3b4079ab2", "1470071459604-3b5ec3a7fe05", "1439066615861-d1af74d74000"),
    ("1464822759023-fed622ff2c3b", "1501785888041-af3ef285b470", "1518548419970-58e3b4079ab2"),
]
WATERFALL = ("1432405972618-c60b0225b8f9", "1501785888041-af3ef285b470", "1518548419970-58e3b4079ab2")
CITY = ("1477959858617-67f85cf4f1df", "1514565131-fce0801e5785", "1449824913935-59a10b8d2000")
WATER = [
    ("1540202404-a2f29016b523", "1507525428034-b723cf961d3e", "1544551763-46a013bb70d5"),
    ("1502680390469-be75c86b636f", "1544551763-46a013bb70d5", "1531722569936-825d3dd91b15"),
    ("1531722569936-825d3dd91b15", "1544551763-46a013bb70d5", "1507525428034-b723cf961d3e"),
]
WELLNESS = ("1544161515-4ab6ce6db874", "1540555700478-4be289fbecef", "1540331547168-8b63109225b7")
HIKING = ("1551632811-561732d1e306", "1464822759023-fed622ff2c3b", "1501785888041-af3ef285b470")
CRUISE = [
    ("1496070249387-15db2798b018", "1514525253161-7a46d19cd819", "1507525428034-b723cf961d3e"),
    ("1531722569936-825d3dd91b15", "1544551763-46a013bb70d5", "1507525428034-b723cf961d3e"),
]
FAIR = ("1513889961551-628c1e5e2ee9", "1477959858617-67f85cf4f1df", "1514565131-fce0801e5785")
CULTURAL = ("1490730141103-6cac27aaab94", "1514525253161-7a46d19cd819", "1477959858617-67f85cf4f1df")
CAMPING = ("1504280390367-361c6d9f38f4", "1501785888041-af3ef285b470", "1470071459604-3b5ec3a7fe05")
NIGHT = ("1514933651103-005eec06c04b", "1424847651672-bf20a4b0982b", "1552566626-52f8b828add9")
FEEDING = ("1437622368342-7a3d73a34c8f", "1544551763-46a013bb70d5", "1507525428034-b723cf961d3e")
BIKE = ("1599579089226-e9e4a61b47b9", "1501785888041-af3ef285b470", "1470071459604-3b5ec3a7fe05")
DIVE = [
    ("1540202404-a2f29016b523", "1544551763-46a013bb70d5", "1507525428034-b723cf961d3e"),
]


def _urls(ids):
    return [IMG % pid for pid in ids]


def download(candidates, dest_dir, filename):
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    if target.exists() and target.stat().st_size > 0:
        return filename
    for url in candidates:
        try:
            with urllib.request.urlopen(url, timeout=25) as resp:
                data = resp.read()
            if data and len(data) > 2000:
                target.write_bytes(data)
                return filename
        except Exception:
            continue
    return None


def _safe_name(text):
    cleaned = "".join(c if c.isalnum() else "-" for c in text.lower())
    return "-".join(p for p in cleaned.split("-") if p)[:40] or "img"


def _rotated(pool, n):
    if not pool:
        return []
    n %= len(pool)
    return pool[n:] + pool[:n]


def attach_photos(parent, rel_name, photo_model, subdir, captions, photo_pool):
    """captions: list of captions for the gallery. photo_pool: parallel list of
    (caption, [candidate ids or urls...]) entries. Each establishment picks its
    own entries by rotating through the pool so its gallery differs from
    neighbours. Candidate ids are auto-converted to Unsplash URLs."""
    dest_dir = Path(settings.MEDIA_ROOT) / subdir
    pool = list(photo_pool or [])
    specs = []
    for i, cap in enumerate(captions):
        if pool:
            entry = pool[i % len(pool)]
            ids = entry[1] if isinstance(entry, tuple) and len(entry) == 2 else entry
            ids = list(ids)
        else:
            ids = list(WATERFALL)
        if ids and str(ids[0]).startswith("http"):
            urls = ids
        else:
            urls = _urls(ids)
        specs.append((cap, urls))
    for order, (cap, urls) in enumerate(specs):
        fname = (_safe_name(getattr(parent, "name", str(parent)))
                 + "--%02d" % (order + 1) + ".jpg")
        got = download(urls, dest_dir, fname)
        if not got:
            continue
        with open(dest_dir / got, "rb") as fh:
            kwargs = {rel_name: parent, "image": File(fh, name=got),
                      "caption": cap if cap else ""}
            if "is_primary" in {f.name for f in photo_model._meta.get_fields()}:
                kwargs["is_primary"] = (order == 0)
            photo_model.objects.create(**kwargs)


def wipe_all(write):
    models = [
        ActivityPhoto, Activity, ActivityProvider,
        LandmarkPhoto, Landmark,
        RestaurantPhoto, Table, Restaurant,
        StaycationPhoto, BlockOutDate, StaycationService, Staycation,
        ResortPhoto, RoomVilla, ResortService, Resort,
        HotelPhoto, Room, Amenity, HotelService, Hotel,
        Flight, AirlineService, Aircraft, Airline,
    ]
    for model in models:
        try:
            count, _ = model.objects.all().delete()
            write(f"  wiped {model.__name__}: {count} row(s)")
        except Exception as exc:
            write(f"  skipped {model.__name__}: {exc}")


# ---------------------------------------------------------------------------
# REAL DATA — HOTELS (Agoda-listed Philippine hotels)
# ---------------------------------------------------------------------------
D = Decimal


def h(name, province, municipality, barangay, phone, email, ops, rooms, services, amenities):
    return {
        "name": name, "province": province, "municipality": municipality,
        "barangay": barangay, "contact_number": phone, "email": email,
        "operating_schedule": ops, "rooms": rooms,
        "services": services, "amenities": amenities,
    }


HOTELS = [
    h("The Manila Hotel", "Metro Manila", "Manila", "Ermita", "0252730011",
      "reservations@manilahotel.com.ph", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("SINGLE", "101", 1, 0, D("7800"), "24 sqm, 1 Queen bed"),
          ("DOUBLE", "201", 2, 1, D("9200"), "28 sqm, 1 King bed, garden view"),
          ("TWIN", "202", 2, 1, D("9200"), "28 sqm, 2 Twin beds, garden view"),
          ("DELUXE", "301", 2, 2, D("11500"), "36 sqm, Manila Bay view"),
          ("SUITE", "501", 3, 2, D("18500"), "One-bedroom suite, 60 sqm, bay window"),
          ("FAMILY", "405", 4, 2, D("15800"), "45 sqm, connecting beds"),
      ], [
          ("Room Service", 0, "24 hours", "In-room dining, Filipino and international menu"),
          ("Airport Transfer", 2500, "24 hours", "Private vehicle from NAIA to hotel"),
          ("Spa & Massage", 1800, "10 AM - 9 PM", "Signature hilot and Swedish massage"),
          ("Laundry Service", 250, "Same-day before 10 AM", "Per-piece washing and pressing"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Outdoor pool, sun deck and pool bar", "ACTIVE"),
          ("Gym & Fitness Center", "6 AM - 10 PM", "Cardio and free-weights area", "ACTIVE"),
          ("Free Parking", "24 hours", "Valet and self-parking for guests", "ACTIVE"),
          ("High-Speed Wi-Fi", "24 hours", "In all rooms and public areas", "ACTIVE"),
          ("Restaurant & Bar", "6 AM - 11 PM", "Buffet breakfast and a la carte dining", "ACTIVE"),
      ]),
    h("Sofitel Philippine Plaza Manila", "Metro Manila", "Pasay City", "Mall of Asia Complex",
      "0287338888", "resort.info@sofitel.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "701", 2, 1, D("11500"), "32 sqm, king bed, garden view"),
          ("TWIN", "703", 2, 1, D("11500"), "32 sqm, twin beds"),
          ("SUITE", "901", 2, 2, D("23500"), "Prestige suite, 54 sqm, sunset view"),
          ("FAMILY", "608", 3, 2, D("18500"), "Club Millesime access, 40 sqm"),
          ("OTHER", "1202", 2, 0, D("9800"), "Superior corner room, 30 sqm"),
      ], [
          ("Lobby Bar", 0, "9 AM - 1 AM", "Cocktails and light bites"),
          ("Club Millesime Lounge", 5000, "6 AM - 11 PM", "Lounge access with canapes"),
          ("Airport Transfer", 2600, "24 hours", "Chauffeured sedan"),
          ("In-Room Dining", 0, "24 hours", "24-hour room service"),
      ], [
          ("Outdoor Pool", "6 AM - 9 PM", "Two cascading lagoon pools", "ACTIVE"),
          ("Spa", "10 AM - 10 PM", "So Sofitel spa treatments", "ACTIVE"),
          ("Fitness Center", "24 hours", "State-of-the-art equipment", "ACTIVE"),
          ("Free Wi-Fi", "24 hours", "Lounge and rooms", "ACTIVE"),
          ("Business Center", "8 AM - 8 PM", "Meeting rooms", "ACTIVE"),
      ]),
    h("Shangri-La at the Fort", "Metro Manila", "Taguig City", "Bonifacio Global City",
      "0288208888", "signature.sltf@shangri-la.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "1501", 2, 1, D("13500"), "42 sqm, city or garden view"),
          ("SUITE", "2201", 2, 2, D("26000"), "Horizon club suite, 55 sqm"),
          ("TWIN", "1503", 2, 1, D("13500"), "42 sqm, twin beds"),
          ("FAMILY", "1820", 3, 2, D("16800"), "Family Suite, 48 sqm"),
          ("OTHER", "2508", 2, 0, D("11800"), "City-view deluxe, 38 sqm"),
      ], [
          ("Airport Transfer", 2650, "24 hours", "Luxury sedan or van"),
          ("In-Room Dining", 0, "24 hours", "Round the clock"),
          ("Spa", 2200, "10 AM - 10 PM", "Chi spa treatments"),
          ("Breakfast Buffet", 0, "6:30 AM - 10:30 AM", "Included at Horizon Club"),
      ], [
          ("Outdoor Pool", "6 AM - 9 PM", "50m lap pool with cabanas", "ACTIVE"),
          ("Fitness Center", "24 hours", "Full-service gym", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complimentary for guests", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Kids Club", "9 AM - 7 PM", "Supervised activities", "ACTIVE"),
      ]),
    h("Dusit Thani Manila", "Metro Manila", "Makati City", "Ayala Center", "0282388888",
      "res-om@dusit.com", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("SINGLE", "1105", 1, 0, D("6500"), "24 sqm, queen bed"),
          ("DELUXE", "1502", 2, 1, D("8600"), "31 sqm, king bed, Makati view"),
          ("TWIN", "1504", 2, 1, D("8600"), "31 sqm, twin beds"),
          ("SUITE", "2601", 2, 2, D("17500"), "Dusit Suite, 62 sqm"),
          ("OTHER", "903", 2, 0, D("7400"), "Superior, city view"),
      ], [
          ("In-Room Dining", 0, "24 hours", "Thai and international"),
          ("Airport Transfer", 2300, "24 hours", "Sedan service"),
          ("Benjarong Thai Restaurant", 0, "11 AM - 2 PM, 6 PM - 10 PM", "Authentic Thai"),
          ("Laundry", 0, "Overnight", "Same-day if requested before 9 AM"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Heated outdoor pool", "ACTIVE"),
          ("Devarana Spa", "10 AM - 10 PM", "Traditional Thai spa", "ACTIVE"),
          ("Fitness Center", "6 AM - 10 PM", "Technogym equipment", "ACTIVE"),
          ("Parking", "24 hours", "Complimentary covered", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All guest areas", "ACTIVE"),
      ]),
    h("The Peninsula Manila", "Metro Manila", "Makati City", "Ayala Avenue", "0288788888",
      "pma@peninsula.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "816", 2, 1, D("15500"), "Deluxe room, 1 King bed"),
          ("SUITE", "2604", 2, 2, D("33000"), "Peninsula Suite, garden view"),
          ("TWIN", "820", 2, 1, D("15500"), "Deluxe twin"),
          ("FAMILY", "1612", 4, 2, D("22000"), "Two-bedroom family suite"),
          ("OTHER", "717", 2, 0, D("12900"), "Grand deluxe"),
      ], [
          ("Espresso Lounge", 0, "6 AM - 12 MN", "High tea and desserts"),
          ("In-Room Dining", 0, "24 hours", "International menu"),
          ("Chauffeured Car", 0, "Within Makati", "Complimentary on request"),
          ("Laundry & Valet", 0, "Expedite available", "Per piece"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Outdoor heated pool, garden view", "ACTIVE"),
          ("Health Club", "6 AM - 10 PM", "Gym, sauna, steam", "ACTIVE"),
          ("The Spa", "10 AM - 10 PM", "Signature Peninsula rituals", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Lobby Lounge Bands", "Evenings", "Live music", "ACTIVE"),
      ]),
    h("Discovery Primea", "Metro Manila", "Makati City", "Ayala Avenue", "0285798888",
      "guestservices@discovery.com.ph", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "2002", 2, 1, D("11800"), "Deluxe room, Ayala view"),
          ("SUITE", "3101", 2, 2, D("21500"), "One-bedroom suite"),
          ("TWIN", "2010", 2, 1, D("11800"), "Deluxe twin"),
          ("FAMILY", "3408", 4, 2, D("19800"), "Family suite, 2 bedrooms"),
          ("OTHER", "1804", 2, 0, D("9900"), "Superior"),
      ], [
          ("In-Room Dining", 0, "24 hours", "Filipino & international"),
          ("Airport Transfer", 2400, "24 hours", "Private car"),
          ("Spa", 2000, "10 AM - 10 PM", "Wellness therapies"),
          ("Laundry", 0, "Same day", "Express available"),
      ], [
          ("Infinity Pool", "6 AM - 9 PM", "Rooftop, Makati skyline", "ACTIVE"),
          ("Gym", "24 hours", "State-of-the-art", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Cinema", "Screening evenings", "Private 22-seat cinema", "ACTIVE"),
      ]),
    h("Marco Polo Ortigas Manila", "Metro Manila", "Pasig City", "Ortigas Center", "0287207777",
      "mpm.reservations@marcopolohotels.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "2705", 2, 1, D("9800"), "Deluxe, 1 King bed, city view"),
          ("TWIN", "2707", 2, 1, D("9800"), "Deluxe twin"),
          ("SUITE", "3501", 2, 2, D("19500"), "One-bedroom suite, Club access"),
          ("FAMILY", "3120", 4, 2, D("15800"), "Family room"),
          ("OTHER", "2210", 2, 0, D("8800"), "Superior"),
      ], [
          ("Club Lounge", 4800, "6 AM - 11 PM", "Complimentary refreshments"),
          ("In-Room Dining", 0, "24 hours", "Full menu"),
          ("Airport Transfer", 2350, "24 hours", "Private sedan"),
          ("Car & Bike Hire", 0, "8 AM - 6 PM", "Explore Ortigas"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Indoor heated pool", "ACTIVE"),
          ("Fitness Center", "24 hours", "Running track, gym", "ACTIVE"),
          ("Business Center", "24 hours", "Work stations", "ACTIVE"),
          ("Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "Entire property", "ACTIVE"),
      ]),
    h("New World Makati Hotel", "Metro Manila", "Makati City", "Ayala Avenue", "0281116888",
      "reservation.nwmakati@newworldhotels.com", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "906", 2, 1, D("8800"), "Deluxe, city view"),
          ("TWIN", "908", 2, 1, D("8800"), "Deluxe twin"),
          ("SUITE", "1812", 2, 2, D("16800"), "Executive suite"),
          ("FAMILY", "1505", 3, 2, D("12500"), "Family room"),
          ("OTHER", "1102", 2, 0, D("7600"), "Superior"),
      ], [
          ("Room Service", 0, "24 hours", "Filipino and international"),
          ("Airport Transfer", 2200, "24 hours", "Private convoy"),
          ("Spa", 1600, "10 AM - 9 PM", "Massage and wellness"),
          ("Laundry", 0, "Same-day", "Per piece"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Outdoor pool", "ACTIVE"),
          ("Gym", "6 AM - 10 PM", "Equipped", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Business Lounge", "8 AM - 8 PM", "Meeting support", "ACTIVE"),
      ]),
    h("Belmont Hotel Manila", "Metro Manila", "Pasay City", "Mall of Asia Complex", "0283188888",
      "info@belmonthotelmanila.com", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("SINGLE", "505", 1, 0, D("5200"), "20 sqm, queen bed, runway view"),
          ("DELUXE", "808", 2, 1, D("6800"), "24 sqm, king bed"),
          ("TWIN", "812", 2, 1, D("6800"), "24 sqm, twin beds"),
          ("SUITE", "1801", 2, 1, D("11800"), "One-bedroom, runway view"),
          ("OTHER", "915", 2, 0, D("5800"), "Standard queen"),
      ], [
          ("Room Service", 0, "24 hours", "Deli selections"),
          ("Airport Shuttle", 0, "On the hour", "Complimentary schedule"),
          ("Gym Access", 0, "24 hours", "Partner facility"),
          ("Laundry", 0, "Express available", "Per piece"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Outdoor pool", "ACTIVE"),
          ("Complimentary Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("ATM & Convenience", "24 hours", "On-site", "ACTIVE"),
          ("Cleaning Everyday", "Daily", "Turndown on request", "ACTIVE"),
      ]),
    h("Marriott Hotel Manila", "Metro Manila", "Pasay City", "Newport City", "0288558888",
      "marriottmanila.reservations@marriott.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "1204", 2, 1, D("9200"), "Deluxe, king bed, runway view"),
          ("TWIN", "1206", 2, 1, D("9200"), "Deluxe twin"),
          ("SUITE", "3201", 2, 2, D("21000"), "One-bedroom suite"),
          ("FAMILY", "2914", 4, 2, D("14800"), "Family guest room"),
          ("OTHER", "1308", 2, 0, D("7900"), "Superior"),
      ], [
          ("In-Room Dining", 0, "24 hours", "International"),
          ("Airport Shuttle", 0, "Every 30 min", "Complimentary to NAIA T3"),
          ("Spa", 2300, "10 AM - 10 PM", "Full-service"),
          ("Cru Lounge", 0, "5 PM - 12 MN", "Cocktails and light bites"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Outdoor pool with cabanas", "ACTIVE"),
          ("Fitness Center", "24 hours", "Full-service gym", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("M Club Lounge", "6 AM - 11 PM", "Complimentary refreshments", "ACTIVE"),
      ]),
    h("Okada Manila", "Metro Manila", "Paranaque City", "Entertainment City", "0288888777",
      "hospitality@okadamanila.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "1501", 2, 1, D("11800"), "Deluxe king, bay view"),
          ("TWIN", "1503", 2, 1, D("11800"), "Deluxe twin"),
          ("SUITE", "3501", 2, 2, D("28500"), "Mega suite, living area"),
          ("FAMILY", "2218", 4, 2, D("18500"), "Family suite"),
          ("OTHER", "1705", 2, 0, D("9800"), "Superior"),
      ], [
          ("24hr In-Room Dining", 0, "24 hours", "Fine dining"),
          ("Airport Transfer", 2800, "24 hours", "Luxury cars"),
          ("Spa", 2500, "10 AM - 10 PM", "Frills spa"),
          ("The Cafe", 0, "6 AM - 11 PM", "International buffet"),
      ], [
          ("Wave Pool", "8 AM - 9 PM", "The Cove, wave pool", "ACTIVE"),
          ("The Garden", "8 AM - 11 PM", "Outdoor parks", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complementary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Shopping Boulevard", "10 AM - 11 PM", "Retail promenade", "ACTIVE"),
      ]),
    h("Solaire Resort & Casino", "Metro Manila", "Paranaque City", "Entertainment City",
      "0288888888", "guestservices@solaireresort.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "2602", 2, 1, D("13500"), "Sky tower deluxe"),
          ("TWIN", "2604", 2, 1, D("13500"), "Sky tower deluxe twin"),
          ("SUITE", "4501", 2, 2, D("35500"), "Panoramic suite"),
          ("FAMILY", "3015", 4, 2, D("19000"), "Family suite"),
          ("OTHER", "2808", 2, 0, D("11500"), "Tower deluxe"),
      ], [
          ("In-Room Dining", 0, "24 hours", "Gourmet"),
          ("Airport Transfer", 2800, "24 hours", "Luxury fleet"),
          ("Spa", 2600, "11 AM - 11 PM", "Spa at Solaire"),
          ("Finestra", 0, "Dinner", "Italian fine dining"),
      ], [
          ("Sky Pool", "6 AM - 10 PM", "Overlooks Manila Bay", "ACTIVE"),
          ("Fitness & Yoga Studio", "6 AM - 10 PM", "Classes daily", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("The Shoppes", "11 AM - 11 PM", "Retail", "ACTIVE"),
          ("Beach Club", "9 AM - 10 PM", "Cabanas by the bay", "ACTIVE"),
      ]),
    h("Park Inn by Radisson Davao", "Davao Region", "Davao City", "Lanang", "0822338888",
      "reservations.dvo.parkinn@radisson.com", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("SINGLE", "408", 1, 0, D("4200"), "Standard queen"),
          ("DELUXE", "612", 2, 1, D("5200"), "Deluxe, Davao Gulf view"),
          ("TWIN", "614", 2, 1, D("5200"), "Deluxe twin"),
          ("SUITE", "1101", 2, 1, D("9200"), "Junior suite"),
          ("FAMILY", "815", 3, 2, D("7800"), "Family room"),
      ], [
          ("Room Service", 0, "24 hours", "Light menu"),
          ("SMX Davao Shuttle", 0, "On demand", "Complimentary"),
          ("Laundry", 0, "Same day", "Per piece"),
          ("Breakfast Buffet", 0, "6 AM - 10 AM", "At RBG Restaurant"),
      ], [
          ("Outdoor Pool", "6 AM - 9 PM", "Pool deck", "ACTIVE"),
          ("Gym", "6 AM - 10 PM", "Equipped", "ACTIVE"),
          ("Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Prayer Room", "24 hours", "On-site", "ACTIVE"),
      ]),
    h("Waterfront Insular Hotel Davao", "Davao Region", "Davao City", "Lanang", "0822332881",
      "reservations@waterfronthotels.com.ph", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "704", 2, 1, D("6100"), "Deluxe garden view"),
          ("TWIN", "706", 2, 1, D("6100"), "Deluxe twin"),
          ("SUITE", "1501", 2, 2, D("11800"), "Executive suite, sea view"),
          ("FAMILY", "1310", 4, 2, D("9800"), "Deluxe family"),
          ("OTHER", "502", 2, 0, D("5400"), "Superior"),
      ], [
          ("D'Creamery", 0, "9 AM - 9 PM", "Cafe and pastries"),
          ("In-Room Dining", 0, "24 hours", "Cuisine from Lamesa"),
          ("Airport Transfer", 1800, "24 hours", "Private van"),
          ("Sail Bar", 0, "5 PM - 12 MN", "Poolside cocktails"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Seafront pool", "ACTIVE"),
          ("Pantalan Family Waterpark", "9 AM - 5 PM", "Water slides", "ACTIVE"),
          ("Fitness Center", "6 AM - 10 PM", "Gym", "ACTIVE"),
          ("Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
      ]),
    h("Bai Hotel Cebu", "Central Visayas", "Mandaue City", "Subangdaku", "0323188888",
      "reservations@baihotel.com.ph", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "1602", 2, 1, D("6900"), "Deluxe, city view"),
          ("TWIN", "1604", 2, 1, D("6900"), "Deluxe twin"),
          ("SUITE", "3201", 2, 2, D("15500"), "Executive suite"),
          ("FAMILY", "2918", 4, 2, D("11500"), "Family room"),
          ("OTHER", "1508", 2, 0, D("5900"), "Superior"),
      ], [
          ("In-Room Dining", 0, "24 hours", "Filipino and international"),
          ("Airport Transfer", 1900, "24 hours", "Private car"),
          ("Alima Wellness", 2200, "10 AM - 10 PM", "Spa and massage"),
          ("Poolside Grill", 0, "11 AM - 10 PM", "Live cooking"),
      ], [
          ("Sky Pool", "6 AM - 9 PM", "Rooftop with skyline view", "ACTIVE"),
          ("Gym", "6 AM - 10 PM", "Fitness center", "ACTIVE"),
          ("Valet Parking", "24 hours", "Complimentary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Kids Playroom", "8 AM - 8 PM", "Supervised", "ACTIVE"),
      ]),
    h("Radisson Blu Cebu", "Central Visayas", "Cebu City", "Lahug", "0324029900",
      "info.cebu@radissonblu.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "1803", 2, 1, D("7700"), "Deluxe, Columnums view"),
          ("TWIN", "1805", 2, 1, D("7700"), "Deluxe twin"),
          ("SUITE", "2901", 2, 2, D("16800"), "Business suite"),
          ("FAMILY", "2310", 4, 2, D("12900"), "Family connecting room"),
          ("OTHER", "1702", 2, 0, D("6600"), "Standard"),
      ], [
          ("Feria Food Market", 0, "6 AM - 10 PM", "Live station buffet"),
          ("In-Room Dining", 0, "24 hours", "Room service"),
          ("Airport Transfer", 1850, "24 hours", "Private sedan"),
          ("Spa", 2100, "10 AM - 10 PM", "Massage therapies"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Outdoor pool", "ACTIVE"),
          ("Fitness Center", "6 AM - 10 PM", "Modern gym", "ACTIVE"),
          ("Parking", "24 hours", "Complementary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Business Center", "24 hours", "Work space", "ACTIVE"),
      ]),
    h("The Manor at Camp John Hay", "Cordillera", "Baguio City", "Camp John Hay", "0744245301",
      "reservations@themanorjohnhay.com", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "312", 2, 1, D("6800"), "Deluxe, pine view"),
          ("TWIN", "314", 2, 1, D("6800"), "Deluxe twin"),
          ("SUITE", "516", 2, 2, D("11800"), "One-bedroom suite, fireplace"),
          ("FAMILY", "618", 4, 2, D("9800"), "Family lodge"),
          ("OTHER", "224", 2, 0, D("5800"), "Superior"),
      ], [
          ("Room Service", 0, "7 AM - 10 PM", "Comfort food"),
          ("Le Chef", 0, "6 AM - 10 PM", "Buffet and grill"),
          ("Spa", 1500, "10 AM - 9 PM", "Forest serenity massage"),
          ("Camp Jamboree", 0, "10 AM - 8 PM", "Family activities"),
      ], [
          ("Golf Course Access", "6 AM - 6 PM", "18-hole course nearby", "ACTIVE"),
          ("Children's Park", "9 AM - 8 PM", "Open play area", "ACTIVE"),
          ("Parking", "24 hours", "Free", "ACTIVE"),
          ("Wi-Fi", "24 hours", "Lobby and rooms", "ACTIVE"),
          ("Bonfire Pits", "6 PM - 10 PM", "Seasonal", "ACTIVE"),
      ]),
    h("Fili Hotel at Festive Walk", "Western Visayas", "Iloilo City", "Mandurriao", "0333218888",
      "fili@festivewalk.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "1210", 2, 1, D("5800"), "Deluxe, Festive Walk view"),
          ("TWIN", "1212", 2, 1, D("5800"), "Deluxe twin"),
          ("SUITE", "2010", 2, 2, D("11800"), "Executive suite"),
          ("FAMILY", "1815", 4, 2, D("9800"), "Family room"),
          ("OTHER", "1105", 2, 0, D("4900"), "Superior"),
      ], [
          ("Room Service", 0, "24 hours", "Filipino and international"),
          ("Harbor Grill", 0, "6 AM - 10 PM", "Buffet with Ilonggo classics"),
          ("Laundry", 0, "Same-day", "Per piece"),
          ("Airport Transfer", 1500, "24 hours", "Private van"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Pool with city view", "ACTIVE"),
          ("Gym", "6 AM - 10 PM", "Equipped", "ACTIVE"),
          ("Parking", "24 hours", "Complementary", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Events Hall", "8 AM - 10 PM", "Banquet facilities", "ACTIVE"),
      ]),
    h("Best Western Plus The Ivywall Hotel", "MIMAROPA", "Puerto Princesa City", "Taft Street",
      "0484338840", "reservations@theivywall.com", "Check-in 2 PM / Check-out 12 NN (daily)", [
          ("SINGLE", "410", 1, 0, D("3500"), "Cozy single"),
          ("DELUXE", "708", 2, 1, D("4800"), "Deluxe, pool view"),
          ("TWIN", "710", 2, 1, D("4800"), "Deluxe twin"),
          ("SUITE", "1201", 2, 2, D("8200"), "Suite with living area"),
          ("FAMILY", "1012", 4, 2, D("6800"), "Family room"),
      ], [
          ("Rooftop Dining", 0, "6 AM - 10 PM", "Breakfast and dinner"),
          ("Tour Desk", 0, "6 AM - 6 PM", "Underground River bookings"),
          ("Laundry", 0, "Same-day", "Per piece"),
          ("Airport Shuttle", 450, "On schedule", "Shared van"),
      ], [
          ("Swimming Pool", "6 AM - 9 PM", "Rooftop pool", "ACTIVE"),
          ("Gym", "6 AM - 10 PM", "Small fitness room", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Restaurant", "6 AM - 10 PM", "Local and international", "ACTIVE"),
          ("Parking", "24 hours", "Free", "ACTIVE"),
      ]),
    h("Henann Resort Alona Beach", "Central Visayas", "Panglao", "Tawala", "0385029062",
      "reservations@henann.com", "Check-in 3 PM / Check-out 12 NN (daily)", [
          ("DELUXE", "7201", 2, 1, D("9200"), "Deluxe room, pool view"),
          ("TWIN", "7203", 2, 1, D("9200"), "Deluxe twin"),
          ("SUITE", "8201", 2, 2, D("16800"), "Executive suite"),
          ("FAMILY", "6008", 4, 2, D("14800"), "Family suite"),
          ("CABANA" if False else "OTHER", "1102", 2, 0, D("7600"), "Garden view"),
      ], [
          ("Room Service", 0, "24 hours", "Resort menu"),
          ("Airport Transfer", 1600, "24 hours", "Private van"),
          ("Spa", 1500, "10 AM - 9 PM", "Massage with sea view"),
          ("Dive Center", 2600, "8 AM - 5 PM", "Scuba packages"),
      ], [
          ("Infinity Pool", "6 AM - 9 PM", "Overlooking the beach", "ACTIVE"),
          ("Beachfront", "24 hours", "Direct Alona Beach access", "ACTIVE"),
          ("Gym", "6 AM - 10 PM", "Equipped", "ACTIVE"),
          ("Wi-Fi", "24 hours", "All areas", "ACTIVE"),
          ("Kids Pool", "6 AM - 9 PM", "Shallow wading pool", "ACTIVE"),
      ]),
]

def make_hotel_slots():
    """Rotate photo pools so every establishment gets a distinct gallery."""
    pools = [EXT, BED, POOL]
    caps = ("Hotel facade", "Guest room", "Pool area")
    out = []
    i = 0
    for entry in HOTELS:
        photos = []
        for k, cap in enumerate(caps):
            src = pools[k % len(pools)]
            ids = src[i % len(src)]
            photos.append((cap, _urls(list(ids))))
        out.append(photos)
        i += 1
    return out


# ---------------------------------------------------------------------------
# REAL DATA — RESORTS
# ---------------------------------------------------------------------------
def r(name, province, municipality, barangay, phone, email, ops, units, services):
    return {
        "name": name, "province": province, "municipality": municipality,
        "barangay": barangay, "contact_number": phone, "email": email,
        "operating_schedule": ops, "units": units, "services": services,
    }


RESORTS = [
    r("Discovery Shores Boracay", "Western Visayas", "Malay", "Balabag (Station 1)",
      "0362884500", "reservations@discovershoresboracay.com", "Check-in 3 PM / Check-out 12 NN", [
          ("ROOM", "1001", 2, 1, D("11800"), "Deluxe room, garden view"),
          ("SUITE", "2201", 2, 2, D("19800"), "One-bedroom suite"),
          ("VILLA", "3101", 3, 2, D("28500"), "Beachfront villa with plunge pool"),
          ("CABANA", "1402", 2, 1, D("14500"), "Cabanas at the shore"),
          ("OTHER", "1805", 2, 0, D("9800"), "Superior"),
      ], [
          ("Airport Transfer", 3500, "On arrival", "Caticlan pick-up via boat"),
          ("Spa", 2800, "10 AM - 9 PM", "Tirta spa"),
          ("Watersports", 1500, "9 AM - 5 PM", "Kayak and paddleboard"),
          ("Island Hopping", 1600, "9 AM - 3 PM", "Boracay islands"),
      ]),
    r("The Lind Boracay", "Western Visayas", "Malay", "Balabag (Station 1)",
      "0362882312", "reservations@thelindboracay.com", "Check-in 3 PM / Check-out 12 NN", [
          ("ROOM", "2304", 2, 1, D("13800"), "Lind room, sea view"),
          ("SUITE", "3501", 2, 2, D("24500"), "Premier suite"),
          ("VILLA", "4101", 4, 2, D("39000"), "Two-bedroom villa, private pool"),
          ("CABANA", "1606", 2, 1, D("16500"), "Beach cabana"),
          ("OTHER", "2408", 2, 0, D("11500"), "Deluxe garden"),
      ], [
          ("Airport Transfer", 3600, "On arrival", "Boat and van"),
          ("Spa", 2600, "10 AM - 9 PM", "Lind spa"),
          ("Sunset Sail", 1200, "4 PM - 6 PM", "Paraw sailing"),
          ("Yoga", 900, "7 AM - 8 AM", "Beachfront class"),
      ]),
    r("Shangri-La's Boracay Resort and Spa", "Western Visayas", "Malay", "Yapak",
      "0362884988", "boracay@shangri-la.com", "Check-in 3 PM / Check-out 12 NN", [
          ("DELUXE", "3007", 2, 1, D("18500"), "Deluxe Sea View"),
          ("SUITE", "5201", 2, 2, D("38000"), "Suite with private pool"),
          ("VILLA", "6101", 4, 2, D("52000"), "Beach villa"),
          ("FAMILY" if False else "OTHER", "4210", 2, 1, D("21500"), "Deluxe Pool View"),
      ], [
          ("Airport Transfer", 4500, "On arrival", "Welcome lounge at Caticlan"),
          ("Spa", 3500, "10 AM - 9 PM", "Chi spa signature"),
          ("Island Hopping", 2500, "9 AM - 3 PM", "Private yacht"),
          ("Beach Grill Package", 2500, "12 NN - 3 PM", "Dining by the shore"),
      ]),
    r("Henann Palm Beach Resort", "Western Visayas", "Malay", "Balabag (Station 2)",
      "0362886888", "reservations@henann.com", "Check-in 3 PM / Check-out 12 NN", [
          ("DELUXE", "3102", 2, 1, D("9800"), "Deluxe, pool view"),
          ("TWIN", "3104", 2, 1, D("9800"), "Deluxe twin"),
          ("SUITE", "4401", 2, 2, D("17800"), "One-bedroom suite"),
          ("OTHER", "2608", 2, 0, D("8600"), "Garden view"),
      ], [
          ("Airport Transfer", 3200, "On arrival", "Van and boat"),
          ("Spa", 1800, "10 AM - 9 PM", "Palm spa"),
          ("Watersports", 1400, "9 AM - 5 PM", "Jet ski and banana boat"),
          ("Fire Dance Show", 0, "8 PM nightly", "Beachfront entertainment"),
      ]),
    r("Crimson Resort and Spa Mactan", "Central Visayas", "Lapu-Lapu City", "Punta Engano",
      "0324019988", "reservations@crimsonhotel.com", "Check-in 3 PM / Check-out 12 NN", [
          ("ROOM", "5206", 2, 1, D("11500"), "Deluxe room, pool view"),
          ("SUITE", "6601", 2, 2, D("22500"), "Premier suite"),
          ("VILLA", "7101", 3, 2, D("32000"), "Beachfront villa with pool"),
          ("CABANA", "4302", 2, 1, D("12800"), "Pool cabana"),
          ("OTHER", "5408", 2, 0, D("9800"), "Garden room"),
      ], [
          ("Airport Transfer", 1700, "24 hours", "Private van"),
          ("Spa", 2800, "10 AM - 9 PM", "Aum spa"),
          ("Diving", 2600, "8 AM - 5 PM", "Hilutungan marine reserve"),
          ("Island Hopping", 2400, "9 AM - 4 PM", "Olango and Caohagan"),
      ]),
    r("Plantation Bay Resort and Spa", "Central Visayas", "Lapu-Lapu City", "Marigondon",
      "0325059800", "info@plantationbay.com", "Check-in 3 PM / Check-out 12 NN", [
          ("ROOM", "214", 2, 1, D("8200"), "Galaxy room, lagoon view"),
          ("SUITE", "418", 2, 2, D("15800"), "Allegro suite"),
          ("VILLA", "612", 4, 2, D("28500"), "Casa suite with pool"),
          ("OTHER", "112", 2, 0, D("6800"), "Standard"),
      ], [
          ("Airport Transfer", 1750, "24 hours", "Private van"),
          ("Spa", 2400, "10 AM - 9 PM", "Tirolesa and spa"),
          ("Diving", 2650, "8 AM - 5 PM", "House reef"),
          ("Zipline", 900, "9 AM - 5 PM", "Over the lagoon"),
      ]),
    r("Bluewater Maribago Beach Resort", "Central Visayas", "Lapu-Lapu City", "Maribago",
      "0324021780", "maribago@bluewater.com.ph", "Check-in 2 PM / Check-out 12 NN", [
          ("ROOM", "310", 2, 1, D("6800"), "Deluxe garden"),
          ("SUITE", "508", 2, 2, D("12800"), "Royal room"),
          ("VILLA", "720", 4, 2, D("22500"), "Garden villa"),
          ("CABANA", "204", 2, 0, D("7600"), "Beach cabana"),
          ("OTHER", "413", 2, 0, D("5900"), "Superior"),
      ], [
          ("Airport Transfer", 1700, "24 hours", "Private van"),
          ("Spa", 1800, "10 AM - 9 PM", "Hilom spa"),
          ("Diving", 2400, "8 AM - 5 PM", "Barrier reef"),
          ("Sunset Cruise", 1100, "4 PM - 6 PM", "Sails and snacks"),
      ]),
    r("South Palms Resort Panglao", "Central Visayas", "Panglao", "Danao", "0385022271",
      "reservations@southpalms.com", "Check-in 2 PM / Check-out 12 NN", [
          ("ROOM", "1209", 2, 1, D("8200"), "Deluxe room, garden"),
          ("SUITE", "2310", 2, 2, D("14800"), "One-bedroom suite"),
          ("VILLA", "3105", 4, 2, D("26000"), "Family villa"),
          ("CABANA", "0812", 2, 1, D("9200"), "Beach hut"),
          ("OTHER", "1503", 2, 0, D("7200"), "Superior"),
      ], [
          ("Airport Transfer", 1700, "24 hours", "Tagbilaran pick-up"),
          ("Massage", 1200, "10 AM - 9 PM", "Couples hilot"),
          ("Island Hopping", 1600, "9 AM - 3 PM", "Balicasag and Pamilacan"),
          ("Dolphin Watching", 1500, "5:30 AM - 8 AM", "Dawn expedition"),
      ]),
    r("Amorita Resort", "Central Visayas", "Panglao", "Tawala", "0385029057",
      "reservations@amoritaresort.com", "Check-in 3 PM / Check-out 12 NN", [
          ("ROOM", "3102", 2, 1, D("8800"), "Deluxe room, sea view"),
          ("SUITE", "4401", 2, 2, D("16500"), "One-bedroom suite"),
          ("VILLA", "5201", 4, 2, D("31000"), "Villa with private pool"),
          ("OTHER", "2806", 2, 0, D("7600"), "Standard garden"),
      ], [
          ("Airport Transfer", 1650, "24 hours", "Tagbilaran van"),
          ("Spa", 2000, "10 AM - 9 PM", "Spa at Amorita"),
          ("Island Hopping", 1700, "9 AM - 3 PM", "Private outrigger"),
          ("Sunset Yoga", 600, "5 PM - 6 PM", "Clifftop by the sea"),
      ]),
    r("Club Paradise Palawan", "MIMAROPA", "Coron", "Dimakya Island", "0484342888",
      "reservations@clubparadisepalawan.com", "Check-in 2 PM / Check-out 12 NN", [
          ("ROOM", "102", 2, 1, D("11000"), "Deluxe room, ocean view"),
          ("SUITE", "201", 2, 2, D("17500"), "Family suite"),
          ("VILLA", "301", 3, 2, D("24000"), "Beach house"),
          ("CABANA", "115", 2, 0, D("12500"), "Cottage by the shore"),
          ("OTHER", "140", 2, 0, D("9800"), "Standard"),
      ], [
          ("Island Hopping", 1900, "9 AM - 4 PM", "Coron classic lagoons"),
          ("Diving", 3000, "8 AM - 5 PM", "WWII wrecks"),
          ("Kayak Rental", 500, "6 AM - 5 PM", "Half-day"),
          ("Massage", 1400, "10 AM - 8 PM", "Sand bar massage"),
      ]),
    r("El Nido Resorts Miniloc Island", "MIMAROPA", "El Nido", "Miniloc Island",
      "0485339000", "miniloc@elnidoresorts.com", "Check-in 2 PM / Check-out 12 NN", [
          ("ROOM", "11", 2, 1, D("15000"), "Beach cottage"),
          ("SUITE", "21", 2, 2, D("22000"), "Water cottage"),
          ("VILLA", "31", 4, 2, D("34000"), "Duplex water cottage"),
          ("OTHER", "08", 2, 0, D("12500"), "Garden room"),
      ], [
          ("Island Hopping", 2400, "9 AM - 5 PM", "Big Lagoon and Secret Lagoon"),
          ("Spa", 2200, "10 AM - 8 PM", "Alma spa"),
          ("Snorkeling", 800, "6 AM - 6 PM", "House reef"),
          ("Tavern Dinner", 1500, "Nightly", "Filipino feast"),
      ]),
    r("Daluyon Beach and Mountain Resort", "MIMAROPA", "Puerto Princesa", "Sabang",
      "0487230090", "reservation@daluyonresort.com", "Check-in 2 PM / Check-out 12 NN", [
          ("ROOM", "203", 2, 1, D("7200"), "Deluxe, garden view"),
          ("SUITE", "310", 2, 2, D("12800"), "Suite with balcony"),
          ("VILLA", "412", 4, 2, D("22000"), "Family cabana"),
          ("CABANA", "120", 2, 0, D("8200"), "Beachfront hut"),
      ], [
          ("Underground River Tour", 1400, "8 AM - 3 PM", "Shared with boat"),
          ("Airport Transfer", 2000, "24 hours", "Private with stopovers"),
          ("Massage", 1200, "10 AM - 8 PM", "Hilot"),
          ("Sabang Falls Trek", 600, "9 AM - 4 PM", "Guided hike"),
      ]),
    r("Misibis Bay", "Bicol Region", "Bacacay", "Cagraray Island", "0524818010",
      "reservations@misibisbay.com", "Check-in 3 PM / Check-out 12 NN", [
          ("ROOM", "1502", 2, 1, D("11500"), "Deluxe, Mayon view"),
          ("SUITE", "2601", 2, 2, D("21500"), "One-bedroom suite"),
          ("VILLA", "3201", 4, 2, D("36000"), "Villa with plunge pool"),
          ("OTHER", "1708", 2, 0, D("9800"), "Superior"),
      ], [
          ("Airport Transfer", 2500, "24 hours", "Legazpi van and boat"),
          ("Spa", 2600, "10 AM - 9 PM", "Mayon resort spa"),
          ("Island Hopping", 1800, "9 AM - 4 PM", "Cagraray islands"),
          ("Volcano Tour", 1500, "8 AM - 3 PM", "Cagsawa and Mayon"),
      ]),
    r("The Farm at San Benito", "CALABARZON", "Lipa City", "Mataas na Lupa", "0437604800",
      "stay@thefarmatsanbenito.com", "Check-in 2 PM / Check-out 12 NN", [
          ("ROOM", "101", 2, 1, D("14000"), "Garden villa"),
          ("SUITE", "T120", 2, 2, D("18500"), "Twin garden villa"),
          ("VILLA", "204", 4, 2, D("32000"), "Pool villas"),
          ("OTHER", "P08", 2, 0, D("12500"), "Pond view"),
      ], [
          ("Detox Program", 6500, "Daily", "Juice cleanse and meals"),
          ("Spa", 3000, "10 AM - 9 PM", "Sanctuary spa"),
          ("Yoga", 700, "6:30 AM daily", "Teacher-led classes"),
          ("Healing Consult", 2500, "By appointment", "Integrative medicine"),
      ]),
    r("Canyon Cove Resort", "CALABARZON", "Nasugbu", "Wawa", "0439311000",
      "reservations@canyoncove.ph", "Check-in 2 PM / Check-out 12 NN", [
          ("ROOM", "310", 2, 1, D("5200"), "Deluxe, garden view"),
          ("SUITE", "502", 2, 2, D("9800"), "One-bedroom suite"),
          ("CABANA", "220", 2, 1, D("6800"), "Beach hut"),
          ("OTHER", "125", 2, 0, D("4400"), "Standard"),
      ], [
          ("Wave Pool", 0, "9 AM - 6 PM", "Family water amenities"),
          ("Spa", 1100, "10 AM - 8 PM", "Massage"),
          ("Banana Boat", 600, "9 AM - 5 PM", "Per person"),
          ("Beach Volleyball", 0, "8 AM - 6 PM", "Net on the shore"),
      ]),
]


def make_resort_slots():
    caps = ("Resort grounds", "Cottage or suite", "Pool and beach")
    out = []
    pools = [BEACH, BED, POOL]
    i = 0
    for entry in RESORTS:
        photos = []
        for k, cap in enumerate(caps):
            src = pools[k % len(pools)]
            ids = src[i % len(src)]
            photos.append((cap, _urls(list(ids))))
        out.append(photos)
        i += 1
    return out


# ---------------------------------------------------------------------------
# REAL DATA — STAYCATIONS
# ---------------------------------------------------------------------------
def s(name, province, municipality, barangay, phone, email, units, adults, children, rate, rules, services):
    return {
        "name": name, "province": province, "municipality": municipality,
        "barangay": barangay, "contact_number": phone, "email": email,
        "capacity": units, "adults": adults, "children": children, "rate": rate,
        "rules": rules, "services": services,
    }


STAYCATIONS = [
    s("Sea Residences Tower A Staycation", "Metro Manila", "Pasay City", "Mall of Asia Complex",
      "09171110001", "stay.searesidences@gmail.com", 5, 5, 2, D("2200"),
      "Quiet hours 10 PM - 6 AM; no smoking inside; building card access required; max 5 guests.",
      [("Self Check-in", 0, "2 PM - 8 PM", "Key pickup at lobby"), ("Housekeeping", 350, "On request", "Daily tidy"),
       ("Early Check-in", 300, "Before 2 PM", "Subject to availability"), ("Late Check-out", 500, "Until 6 PM", "Subject to availability")]),
    s("Air Residences Studio", "Metro Manila", "Makati City", "Bangkal", "09171110002",
      "airresidence.rent@gmail.com", 2, 2, 1, D("1900"),
      "No smoking; pets not allowed; building pool rules apply; ID deposit required.",
      [("Self Check-in", 0, "3PM - 9PM", "Smart lock access"), ("Airport Pick-up", 1300, "24 hours", "From NAIA T3")]),
    s("SMDC Light Residences 1BR", "Metro Manila", "Mandaluyong City", "Barangka Ilaya",
      "09171110003", "lightresidence@gmail.com", 4, 4, 2, D("2400"),
      "Maximum 4 pax; no parties; quiet hour 11 PM; pool access 6 AM - 9 PM.",
      [("Self Check-in", 0, "2 PM - 10 PM", "Building concierge"), ("Extra Mattress", 250, "On request", "Per night")]),
    s("SMDC Sun Residences Condo", "Metro Manila", "Quezon City", "Socorro",
      "09171110004", "sunresidence.rent@gmail.com", 3, 3, 1, D("2100"),
      "No smoking indoors; visitors must register at the lobby; check-out 12 NN.",
      [("Self Check-in", 0, "3 PM", "Digital pass"), ("Housekeeping", 300, "On request", "Light cleaning")]),
    s("SMDC Grass Residences Loft", "Metro Manila", "Quezon City", "Bagbag (North EDSA)",
      "09171110005", "grassloft.mla@gmail.com", 4, 4, 2, D("2600"),
      "Loft stairs not for small children; no parties; quiet hours 10 PM - 6 AM.",
      [("Self Check-in", 0, "2 PM - 8 PM", "Assisted by host"), ("Parking", 150, "Daily", "Building parking")]),
    s("Breeze Residences Tower 2", "Metro Manila", "Pasay City", "San Rafael",
      "09171110006", "breeze.t2@gmail.com", 3, 3, 1, D("2300"),
      "Max 3 guests; no smoking; pool 6 AM - 9 PM; visitors need ID.",
      [("Self Check-in", 0, "2 PM - 9 PM", "Concierge self check-in"), ("Late Check-out", 400, "Until 5 PM", "Subject to availability")]),
    s("Venice Luxury Residences 1BR", "Metro Manila", "Taguig City", "Fort Bonifacio",
      "09171110007", "veniceluxury.bgc@gmail.com", 3, 3, 1, D("4200"),
      "Elegant living; no large events; building amenities included; quiet hours.",
      [("Self Check-in", 0, "2 PM - 10 PM", "Host meet and greet"), ("Cleaning Service", 500, "On request", "Full clean"),
       ("Gym Access", 0, "5 AM - 10 PM", "Building gym")]),
    s("Uptown Parksuites Studio", "Metro Manila", "Taguig City", "Fort Bonifacio",
      "09171110008", "uptownparksuites.bgc@gmail.com", 2, 2, 1, D("3600"),
      "BGC walking district; no smoking; max 2 guests; building rules apply.",
      [("Self Check-in", 0, "2 PM - 9 PM", "Front desk assistance"), ("Parking", 200, "Daily", "Building parking")]),
    s("SMDC Mezza Residences 1BR", "Metro Manila", "Manila", "Sta. Mesa",
      "09171110009", "mezzarena.riverside@gmail.com", 4, 4, 2, D("2300"),
      "Near LRT 2; no pets; max 4; check-in from 3 PM.",
      [("Self Check-in", 0, "3 PM - 9 PM", "Smart lock"), ("Extra Room Linen", 150, "On request", "Per set")]),
    s("Shang Grand Tower Condo", "Metro Manila", "Manila", "Binondo",
      "09171110010", "shanggrandtower.mla@gmail.com", 3, 3, 1, D("2000"),
      "Chinatown living; no smoking; visitors must register; quiet hours.",
      [("Self Check-in", 0, "2 PM - 8 PM", "Building concierge"), ("Housekeeping", 300, "On request", "Daily")]),
]


def make_staycation_slots():
    caps = ("Living area", "Bedroom", "Kitchen and dining")
    out = []
    pools = [BED, BED, FOOD]
    i = 0
    for entry in STAYCATIONS:
        photos = []
        for k, cap in enumerate(caps):
            src = pools[k % len(pools)]
            ids = src[i % len(src)]
            photos.append((cap, _urls(list(ids))))
        out.append(photos)
        i += 1
    return out


# ---------------------------------------------------------------------------
# REAL DATA — RESTAURANTS
# ---------------------------------------------------------------------------
def srest(name, location, cuisine, phone, email, hours, tables, food_photo=True):
    return {
        "name": name, "location": location, "cuisine": cuisine, "phone": phone,
        "email": email, "hours": hours, "tables": tables, "food": food_photo,
    }


RESTAURANTS = [
    srest("Antonio's Restaurant", "Brgy. Neogan, Tagaytay City, Cavite", "Modern Filipino fine dining",
          "0464130970", "dining@antoniosrestaurant.ph", "Tue-Sun 11 AM - 2 PM, 6 PM - 10 PM", [("T1", 4, "PRIVATE"), ("T2", 4, "INDOOR"), ("T3", 6, "INDOOR"), ("T4", 8, "OUTDOOR")]),
    srest("Manam Comfort Filipino", "Greenbelt 3, Ayala Center, Makati City", "Filipino comfort food",
          "0287282948", "manam.greenbelt@thegroup.ph", "Daily 11 AM - 10 PM", [("T1", 4, "INDOOR"), ("T2", 4, "INDOOR"), ("T3", 6, "INDOOR"), ("T4", 8, "OUTDOOR")]),
    srest("Vikings Luxury Buffet", "By the Bay, SM Mall of Asia, Pasay City", "International buffet",
          "0285568800", "moa@vikings.ph", "Daily 11 AM - 3 PM, 6 PM - 10 PM", [("B1", 6, "PRIVATE"), ("B2", 12, "PRIVATE"), ("B3", 8, "PRIVATE"), ("B4", 10, "PRIVATE")]),
    srest("People's Palace", "Greenbelt 3, Ayala Center, Makati City", "Thai",
          "0287522296", "peoplespalace@thegroup.ph", "Daily 11 AM - 10 PM", [("T1", 2, "INDOOR"), ("T2", 4, "INDOOR"), ("T3", 6, "INDOOR")]),
    srest("Cafe Ysabel", "455 P. Guevarra St., San Juan City", "Contemporary European",
          "0272419096", "cafeyesabel.ph@gmail.com", "Tue-Sun 11 AM - 2 PM, 6 PM - 10 PM", [("T1", 4, "INDOOR"), ("T2", 6, "INDOOR"), ("T3", 8, "PRIVATE"), ("T4", 10, "PRIVATE")]),
    srest("Max's Restaurant - Scout Tuason", "83 Sct. Tuason St., Quezon City", "Filipino fried chicken",
          "0283732009", "scouttuason@maxschicken.com", "Daily 9 AM - 12 MN", [("T1", 4, "INDOOR"), ("T2", 4, "INDOOR"), ("T3", 8, "INDOOR"), ("T4", 10, "INDOOR")]),
    srest("Gerry's Grill - Glorietta", "Glorietta 2, Ayala Center, Makati City", "Grilled Filipino barbecue",
          "0288928191", "gerrys.glorietta@gmail.com", "Daily 10 AM - 11 PM", [("T1", 2, "BAR"), ("T2", 4, "INDOOR"), ("T3", 6, "OUTDOOR"), ("T4", 8, "OUTDOOR")]),
    srest("Sarsa Kitchen + Bar", "Kapitolyo, Pasig City", "Filipino with regional twists",
          "09663888888", "sarsa.pasig@gmail.com", "Tue-Sun 11 AM - 10 PM", [("T1", 2, "BAR"), ("T2", 4, "INDOOR"), ("T3", 4, "INDOOR"), ("T4", 8, "OUTDOOR")]),
    srest("Nono's Pasta & Pizza", "Greenhills Shopping Center, San Juan City", "Italian",
          "0272188181", "nonos.greenhills@gmail.com", "Daily 11 AM - 10 PM", [("T1", 4, "INDOOR"), ("T2", 4, "INDOOR"), ("T3", 6, "INDOOR"), ("T4", 6, "INDOOR")]),
    srest("Mesa Filipino Moderne", "SM Aura Premier, Bonifacio Global City, Taguig", "Filipino",
          "0285655810", "mesa.aure@gmail.com", "Daily 10 AM - 10 PM", [("T1", 4, "INDOOR"), ("T2", 6, "INDOOR"), ("T3", 8, "PRIVATE")]),
    srest("Locavore", "Ugong Norte, Eastwood City, Quezon City", "Modern Filipino",
          "0283447842", "locavore.qc@gmail.com", "Tue-Sun 11 AM - 2 PM, 6 PM - 11 PM", [("T1", 4, "INDOOR"), ("T2", 4, "INDOOR"), ("T3", 6, "PRIVATE"), ("T4", 8, "PRIVATE")]),
    srest("Lemoni Cafe", "18 Brixton St., Kapitolyo, Pasig City", "Casual French-Asian",
          "09171110011", "lemonicafe.pasig@gmail.com", "Mon-Sat 9 AM - 9 PM", [("T1", 2, "BAR"), ("T2", 4, "INDOOR"), ("T3", 6, "OUTDOOR")]),
    srest("Wildflour Cafe + Bakery", "Net Dr., Bonifacio Global City, Taguig", "Cafe and bakery",
          "0288567601", "bgc@wildflour.com.ph", "Daily 7 AM - 10 PM", [("T1", 2, "BAR"), ("T2", 4, "INDOOR"), ("T3", 6, "OUTDOOR")]),
    srest("Lola Cafe", "Ortega St., San Juan City", "Filipino all-day dining",
          "0276543210", "lolacafe.sanjuan@gmail.com", "Daily 8 AM - 10 PM", [("T1", 4, "INDOOR"), ("T2", 4, "INDOOR"), ("T3", 8, "INDOOR")]),
    srest("The Filling Station Bar and Cafe", "7272 J.P. Rizal St., Poblacion, Makati", "American diner",
          "0288991133", "fillingstation.makati@gmail.com", "Daily 11 AM - 12 MN", [("T1", 2, "BAR"), ("T2", 4, "INDOOR"), ("T3", 6, "INDOOR"), ("T4", 8, "OUTDOOR")]),
    srest("Crisostomo", "S Maison, Seaside Blvd., Pasay City", "Filipino heritage cuisine",
          "0289554400", "crisostomo.smaison@gmail.com", "Daily 11 AM - 10 PM", [("T1", 4, "INDOOR"), ("T2", 6, "INDOOR"), ("T3", 8, "PRIVATE")]),
    srest("Razon's of Guagua", "Angeles City, Pampanga", "Kapampangan",
          "0453223761", "razons.guagua@gmail.com", "Daily 9 AM - 9 PM", [("T1", 4, "INDOOR"), ("T2", 6, "INDOOR"), ("T3", 10, "INDOOR")]),
    srest("Casa Roces", "Crescent St., Quezon City", "Filipino and Spanish",
          "0271271952", "casrocesqc@gmail.com", "Tue-Sun 11 AM - 11 PM", [("T1", 4, "INDOOR"), ("T2", 6, "INDOOR"), ("T3", 8, "PRIVATE")]),
    srest("Cafe Adriatico", "1790 M. Adriatico St., Malate, Manila", "Spanish-Filipino",
          "0252180831", "cafeadriatico.malate@gmail.com", "Daily 7 AM - 12 MN", [("T1", 2, "BAR"), ("T2", 4, "INDOOR"), ("T3", 6, "OUTDOOR")]),
    srest("Via Mare - Greenbelt", "Greenbelt 5, Ayala Center, Makati City", "Filipino seafood",
          "0288724185", "viamare.greenbelt@gmail.com", "Daily 11 AM - 10 PM", [("T1", 4, "INDOOR"), ("T2", 6, "INDOOR"), ("T3", 8, "OUTDOOR")]),
]


def make_restaurant_slots():
    caps = ("Dining room", "Signature dish")
    out = []
    pools = [REST, FOOD]
    i = 0
    for entry in RESTAURANTS:
        photos = []
        for k, cap in enumerate(caps):
            src = pools[k % len(pools)]
            ids = src[i % len(src)]
            photos.append((cap, _urls(list(ids))))
        out.append(photos)
        i += 1
    return out


# ---------------------------------------------------------------------------
# REAL DATA — LANDMARKS / TOURIST SPOTS
# ---------------------------------------------------------------------------
def l(category, name, country, region, province, municipality, barangay, phone,
      description, open_hours, entry_fee, capacity, tour_rate, private_rate, caps, pool):
    return {
        "category": category, "name": name, "country": country, "region": region,
        "province": province, "municipality": municipality, "barangay": barangay,
        "phone": phone, "description": description, "open_hours": open_hours,
        "entry_fee": entry_fee, "capacity": capacity, "tour_rate": tour_rate,
        "private_rate": private_rate, "captions": caps, "pool": pool,
    }


LANDMARKS = [
    l("TOURIST_SPOT", "Banaue Rice Terraces", "Philippines", "Cordillera", "Ifugao", "Banaue", "Central Banaue",
      "09171110021", "UNESCO-listed 2,000-year-old hand-carved terraces forming giant green steps on the Cordillera mountains, best viewed at sunrise.", "6 AM - 5 PM",
      D("150"), 500, D("350"), D("1800"), ("Banaue rice terraces", "Mountain view", "Terraces detail"), NATURE),
    l("TOURIST_SPOT", "Chocolate Hills", "Philippines", "Central Visayas", "Bohol", "Carmen", "Cabul-an",
      "09171110022", "More than 1,200 near-identical grass-covered hillocks that turn chocolate-brown in the dry season, spread across Bohol's Karst plains.", "8 AM - 6 PM",
      D("100"), 1000, D("300"), D("1500"), ("Chocolate hills viewpoint", "Bohol karst hills"), NATURE),
    l("TOURIST_SPOT", "Puerto Princesa Underground River", "Philippines", "MIMAROPA", "Palawan", "Puerto Princesa", "Sabang",
      "09171110023", "A navigable 8.2-km underground river inside a cave system framed by karst limestone, part of the Puerto Princesa Subterranean River national park.", "8 AM - 4 PM",
      D("200"), 800, D("500"), D("3600"), ("Underground river entrance", "Sabang limestone cliffs", "Jungle river"), WATERFALL),
    l("TOURIST_SPOT", "Kawasan Falls", "Philippines", "Central Visayas", "Cebu", "Badian", "Matutinao",
      "09171110024", "A cascade of turquoise water through multi-tiered limestone pools deep in the Badian forest, famous for canyoneering and cliff-jumping.", "7 AM - 5 PM",
      D("100"), 600, D("250"), D("1800"), ("Kawasan falls cascade", "Turquoise pools", "Forest canyon"), WATERFALL),
    l("TOURIST_SPOT", "Kayangan Lake", "Philippines", "MIMAROPA", "Palawan", "Coron", "Barangay 1",
      "09171110025", "Crystal-clear saltwater lake framed by sheer karst cliffs; a short uphill trail rewards visitors with Coron's iconic postcard view.", "7 AM - 5 PM",
      D("150"), 400, D("400"), D("2500"), ("Kayangan lake lookout", "Karst cliffs lake"), WATERFALL),
    l("TOURIST_SPOT", "Mount Pulag", "Philippines", "Cordillera", "Benguet", "Kabayan", "Tinoc",
      "09171110026", "The highest peak in Luzon and the 'playground of the gods', famed for its sea of clouds and grasslands at 2,926 meters above sea level.", "4 AM - 5 PM (registration required)",
      D("100"), 200, D("600"), D("4000"), ("Mount Pulag sea of clouds", "Grassland summit"), HIKING),
    l("TOURIST_SPOT", "White Beach, Boracay", "Philippines", "Western Visayas", "Aklan", "Malay", "Station 1-3",
      "09171110027", "Four kilometres of powdery white sand on the western shore of Boracay, backed by coconut palms and a lively beachfront.", "24 hours",
      D("0"), 5000, D("400"), D("3000"), ("White Beach shoreline", "Boatav Boracay beach"), BEACH[0]),
    l("TOURIST_SPOT", "Taal Volcano", "Philippines", "CALABARZON", "Batangas", "Talisay", "Buco",
      "09171110028", "The world's smallest active volcano inside a lake inside a volcano; a short boat hop and trek reaches the crater rim.", "8 AM - 4 PM",
      D("150"), 400, D("450"), D("2800"), ("Taal volcano crater", "Taal lake crossing"), HIKING),
    l("LANDMARK", "Fort Santiago", "Philippines", "Metro Manila", "NCR", "Manila", "Intramuros",
      "09171110029", "A 16th-century stone fortress at the mouth of the Pasig that guarded old Manila, deep inside the walled city of Intramuros.", "8 AM - 6 PM",
      D("75"), 1500, D("300"), D("1500"), ("Fort Santiago gate", "Intramuros walls", "Rizal shrine"), CITY),
    l("LANDMARK", "Rizal Park (Luneta)", "Philippines", "Metro Manila", "NCR", "Manila", "Ermita",
      "09171110030", "The country's National Park built to honor Jose Rizal, spanning 58 hectares of gardens, monuments and open lawns by Manila Bay.", "5 AM - 9 PM",
      D("0"), 10000, D("200"), D("1200"), ("Rizal monument", "Luneta gardens"), CITY),
    l("LANDMARK", "Calle Crisologo, Vigan", "Philippines", "Ilocos Region", "Ilocos Sur", "Vigan", "Heritage Village",
      "09171110031", "A cobblestoned street in Vigan's UNESCO heritage old town lined with ancestral houses, gas lamps and horse-drawn calesas.", "24 hours (tourists 6 AM - 12 MN)",
      D("0"), 3000, D("350"), D("2200"), ("Calle Crisologo heritage street", "Vigan ancestral houses"), CITY),
    l("TOURIST_SPOT", "Mayon Volcano", "Philippines", "Bicol Region", "Albay", "Daraga", "Cagsawa",
      "09171110032", "An almost perfectly conical stratovolcano towering above the Bicol plains, world-famous for its symmetric slopes and the Cagsawa Ruins.", "6 AM - 6 PM (view area)",
      D("100"), 800, D("400"), D("2500"), ("Mayon volcano cone", "Cagsawa ruins and Mayon"), HIKING),
    l("TOURIST_SPOT", "Philippine Tarsier Sanctuary", "Philippines", "Central Visayas", "Bohol", "Corella", "Canapnapan",
      "09171110033", "A protected forest reserve dedicated to the world's smallest primate, the Philippine tarsier, with shady boardwalk trails and a viewing area.", "9 AM - 4 PM",
      D("100"), 300, D("250"), D("1500"), ("Tarsier in the wild", "Forest sanctuary trail"), NATURE),
    l("TOURIST_SPOT", "Big Lagoon, El Nido", "Philippines", "MIMAROPA", "Palawan", "El Nido", "Buena Suerte",
      "09171110034", "A lagoon of electric-blue water enclosed by towering limestone cliffs, part of the classic El Nido island-hopping itinerary.", "8 AM - 5 PM",
      D("200"), 400, D("500"), D("3500"), ("Big Lagoon karst walls", "El Nido lagoon"), WATER[0]),
    l("TOURIST_SPOT", "Apo Island Marine Reserve", "Philippines", "Central Visayas", "Negros Oriental", "Dauin", "San Juan",
      "09171110035", "A marine sanctuary off Dauin known for abundant green sea turtles, coral gardens and easy shore diving just meters from the sand.", "6 AM - 6 PM",
      D("200"), 500, D("450"), D("3000"), ("Apo Island reef", "Turtle encounter"), DIVE[0]),
    l("TOURIST_SPOT", "Chico's Diving Spot, Balicasag", "Philippines", "Central Visayas", "Bohol", "Panglao", "Poblacion",
      "09171110036", "A premier dive site around tiny Balicasag Island — steep drop-offs, coral gardens and schools of jackfish just off the shore.", "8 AM - 5 PM",
      D("300"), 300, D("700"), D("5000"), ("Balicasag drop-off", "Sea turtle reef"), DIVE[0]),
]


def make_landmark_slots():
    out = []
    for entry in LANDMARKS:
        pool = entry["pool"]
        specs = []
        for k, cap in enumerate(entry["captions"]):
            ids = pool if isinstance(pool, tuple) else pool[k % len(pool)]
            if isinstance(pool, tuple):
                ids = pool
            elif isinstance(pool, list):
                ids = pool[k % len(pool)]
            if isinstance(ids, str):
                ids = (ids,)
            specs.append((cap, _urls(list(ids))))
        out.append(specs)
    return out


# ---------------------------------------------------------------------------
# REAL DATA — ACTIVITIES
# ---------------------------------------------------------------------------
PROVIDERS = [
    ("Boracay Adventure Tours", "Operates land and water activities on Boracay Island since 2009.",
     "Balabag, Malay, Aklan", "0362881111", "tours@boracayadventure.ph", "Boracay Island",
     "Daily 8 AM - 6 PM", True),
    ("Kawasan Canyoneering Cebu", "Certified guides for the classic Badian-Alegria downriver canyoneering run.",
     "Badian, Cebu", "0325011000", "book@kawasan-canyon.ph", "Cebu South",
     "Daily 6 AM - 4 PM", True),
    ("Palawan Discover Your Roots", "Palawan tour operator for Underground River and island hopping.",
     "Puerto Princesa City, Palawan", "0484331100", "booking@discoverpalawan.ph", "Palawan",
     "Daily 6 AM - 6 PM", True),
    ("Siargao Surf School", "Pro-certified surf instructors for every level on Cloud 9 and local breaks.",
     "General Luna, Siargao", "09171110041", "surf@siargaosurfschool.ph", "Siargao",
     "Daily 6 AM - 7 PM", True),
    ("Bohol Outdoor Adventures", "Countryside tours and diving around Bohol and Panglao.",
     "Panglao, Bohol", "0385021000", "trips@boholoutdoor.ph", "Bohol",
     "Daily 7 AM - 6 PM", True),
    ("Baguio Treks and Zipline", "High-elevation adventures: trails, ziplines and ATV near Baguio.",
     "Baguio City, Benguet", "0744421000", "guide@baguiotreks.ph", "Baguio and Benguet",
     "Daily 7 AM - 5 PM", True),
    ("Ilocos Heritage Routes", "Vigan and Ilocos cultural walking tours led by licensed local guides.",
     "Vigan City, Ilocos Sur", "0777221000", "tours@ilocosheritage.ph", "Ilocos Region",
     "Daily 7 AM - 7 PM", True),
    ("The Farm San Benito Wellness", "Wellness, yoga and spa day experiences at The Farm at San Benito, Lipa.",
     "Lipa City, Batangas", "0437604800", "wellness@thefarmsanbenito.ph", "Batangas",
     "Daily 7 AM - 7 PM", True),
]

ACTIVITIES = [
    ("Boracay Island Hopping Tour", "WATER", "Island-hopping via outrigger to Puka Shell Beach, magic island and a snorkeling stop.", None,
     "Balabag", "Malay", "Aklan", "D' Talipapa Meeting Point", 300, "HOURS", None, None, None, "Daily",
     D("1600"), "PER_PERSON", D("0"), 30, 2, None, None, True, "active", 0),
    ("Kawasan Canyoneering Adventure", "WATER", "Jump, swim and slide down more than a dozen falls and pools on the Badian canyon run.", None,
     "Matutinao", "Badian", "Cebu", "Kawasan Registration", 240, "MINUTES", None, None, None, "Daily",
     D("2500"), "PER_PERSON", D("0"), 25, 4, None, None, True, "active", 1),
    ("Puerto Princesa Underground River Tour", "CULTURAL", "Boat ride into the famed Underground River with environmental fee and shuttle included.", None,
     "Sabang", "Puerto Princesa", "Palawan", "Robinsons Terminal", 480, "MINUTES", None, None, None, "Daily",
     D("1450"), "PER_PERSON", D("0"), 40, 1, None, None, True, "active", 2),
    ("El Nido Big Lagoon Island Hopping", "WATER", "Full-day island-hopping visiting Big Lagoon, Secret Lagoon, Shimizu and Seven Commandos Beach.", None,
     "Buena Suerte", "El Nido", "Palawan", "El Nido Municipal Dock", 480, "MINUTES", None, None, None, "Daily",
     D("1800"), "PER_PERSON", D("0"), 45, 2, None, None, True, "active", 2),
    ("Siargao Surfing Lesson", "WATER", "One-on-one beginner lessons on gentle breaks, with board and rash guard included.", None,
     "General Luna", "General Luna", "Surigao del Norte", "Cloud 9 Boardwalk", 120, "MINUTES", None, None, None, "Daily",
     D("900"), "PER_PERSON", D("0"), 10, 1, None, None, True, "active", 3),
    ("Whale Shark Encounter Oslob", "WATER", "Snorkel beside gentle whale sharks in Oslob, with briefing, life vest and beach entry.", None,
     "Tan-awan", "Oslob", "Cebu", "Oslob Visitor Center", 90, "MINUTES", None, None, None, "Daily",
     D("1100"), "PER_PERSON", D("0"), 30, 1, None, None, True, "active", 1),
    ("Bohol Countryside Tour", "CULTURAL", "Tarsier sanctuary, Blood Compact site, Loboc River cruise and Chocolate Hills viewpoint.", None,
     "Carmen", "Carmen", "Bohol", "Tagbilaran City Center", 480, "MINUTES", None, None, None, "Daily",
     D("1600"), "PER_PERSON", D("0"), 12, 2, None, None, True, "active", 4),
    ("Balicasag Island Dive", "WATER", "Two guided dives at Balicasag Marine Sanctuary with all gear included.", None,
     "Panglao", "Panglao", "Bohol", "Alona Beach Pier", 360, "MINUTES", None, None, None, "Daily",
     D("3000"), "PER_PERSON", D("0"), 8, 1, None, None, True, "active", 4),
    ("ATV Ridges Tour Baguio", "OUTDOOR", "Ride an ATV across pine-clad ridges with mountain overlooks, briefing and helmet included.", None,
     "Camp John Hay", "Baguio", "Benguet", "ATV Station, Camp John Hay", 120, "MINUTES", None, None, None, "Daily",
     D("900"), "PER_SESSION", D("0"), 20, 1, None, None, True, "active", 5),
    ("Zipline at D'juris Park", "OUTDOOR", "High-line zipline over the Baguio plateau with tandem option available.", None,
     "D'juris Park", "Baguio", "Benguet", "D'juris Park Entrance", 30, "MINUTES", None, None, None, "Daily",
     D("400"), "PER_PERSON", D("0"), 30, 1, None, None, True, "active", 5),
    ("Parasailing at Boracay", "WATER", "Soar 15 meters above Bulabog Beach with a thrilling motorized parasail ride.", None,
     "Balabag", "Malay", "Aklan", "Bulabog Beach Sports Center", 15, "MINUTES", None, None, None, "Daily",
     D("1200"), "PER_PERSON", D("0"), 20, 1, None, None, True, "active", 0),
    ("Coron Island Hopping and Kayaking", "WATER", "Paddle Kayangan Lake, Twin Lagoon, Barracuda Lake and Atwayan Beach in one day.", None,
     "Barangay 5", "Coron", "Palawan", "Coron Town Port", 480, "MINUTES", None, None, None, "Daily",
     D("1500"), "PER_PERSON", D("0"), 20, 2, None, None, True, "active", 2),
    ("Vigan Heritage Walking Tour", "CULTURAL", "Guided walk through Calle Crisologo, pottery shops and Vigan's ancestral houses.", None,
     "Heritage Village", "Vigan", "Ilocos Sur", "Vigan Cathedral", 180, "MINUTES", None, None, None, "Daily",
     D("500"), "PER_PERSON", D("0"), 15, 2, None, None, True, "active", 6),
    ("Spa Day at The Farm San Benito", "WELLNESS", "A half-day of wellness: hydrotherapy, yoga and a signature massage in Lipa, Batangas.", None,
     "Mataas na Lupa", "Lipa", "Batangas", "The Farm Reception", 300, "MINUTES", None, None, None, "Daily",
     D("3500"), "PER_PERSON", D("0"), 10, 1, None, None, True, "active", 7),
    ("Baguio Ecology Trail and Camping", "OUTDOOR", "Overnight trail camping among the pine forests of Benguet with tents and meals included.", None,
     "Camp Jamboree", "Baguio", "Benguet", "Camp Jamboree Trailhead", 1440, "MINUTES", None, None, None, "Weekends",
     D("1800"), "PER_PERSON", D("0"), 15, 2, None, None, True, "active", 5),
]


def make_activity_images(name):
    maps = {
        "Boracay Island Hopping Tour": ("Island hopping boat", CRUISE[0]),
        "Kawasan Canyoneering Adventure": ("Canyoneering run", WATER[1]),
        "Puerto Princesa Underground River Tour": ("Underground river boat", WATERFALL),
        "El Nido Big Lagoon Island Hopping": ("Big Lagoon boards", WATER[2]),
        "Siargao Surfing Lesson": ("Surf lesson", WATER[1]),
        "Whale Shark Encounter Oslob": ("Whale shark swim", FEEDING),
        "Bohol Countryside Tour": ("Countryside view", NATURE),
        "Balicasag Island Dive": ("Reef dive", DIVE[0]),
        "ATV Ridges Tour Baguio": ("ATV ridge ride", HIKING),
        "Zipline at D'juris Park": ("Zipline among the pines", HIKING),
        "Parasailing at Boracay": ("Parasail over the bay", WATER[2]),
        "Coron Island Hopping and Kayaking": ("Kayaking the lagoon", CRUISE[1]),
        "Vigan Heritage Walking Tour": ("Vigan heritage street", CITY),
        "Spa Day at The Farm San Benito": ("Wellness day spa", WELLNESS),
        "Baguio Ecology Trail and Camping": ("Highland trail camping", CAMPING),
    }
    return maps.get(name, ("Activity", HIKING))


# ---------------------------------------------------------------------------
# REAL DATA — AIRLINES
# ---------------------------------------------------------------------------
def a(name, phone, email, desc, info, aircrafts, flights, services):
    return {
        "name": name, "phone": phone, "email": email, "description": desc,
        "operating": info, "aircrafts": aircrafts, "flights": flights, "services": services,
    }


AIRLINES = [
    a("Philippine Airlines", "0288558888", "flypal@pal.com.ph",
      "Flag carrier of the Philippines flying to Manila, provincial hubs and international destinations since 1941.",
      "Counter opens 3 hours before departure; web and mobile check-in available.",
      [("Airbus A321neo", "NARROW_BODY", "RP-C4129", 199),
       ("Airbus A330-300", "WIDE_BODY", "RP-C3332", 321),
       ("Airbus A350-900", "WIDE_BODY", "RP-C3501", 295)],
      [("PR 001", "AIR", "Manila", "Los Angeles", "MNL", "LAX", "Terminal 1", "A1", "2026-10-01 09:00", "2026-10-01 14:05", D("68500"), D("33500"), D("250")),
       ("PR 103", "AIR", "Manila", "Cebu", "MNL", "CEB", "Terminal 2", "B3", "2026-10-01 06:10", "2026-10-01 07:25", D("4200"), D("2500"), D("180")),
       ("PR 200", "AIR", "Manila", "Davao", "MNL", "DVO", "Terminal 2", "A4", "2026-10-01 07:30", "2026-10-01 09:15", D("5300"), D("3100"), D("180")),
       ("PR 301", "AIR", "Cebu", "Palawan", "CEB", "PPS", "Terminal D", "C2", "2026-10-01 08:20", "2026-10-01 09:10", D("4600"), D("2800"), D("170"))],
      [("Bags of Hope", D("0"), "Before boarding", "Complimentary 7 kg hand-carry"), ("Business Lounge", D("0"), "3 hours before flight", "Lounge access for business class"),
       ("Excess Baggage Prepaid", D("250"), "24 hours", "Per kg purchased in advance")]),
    a("Cebu Pacific Air", "0287020888", "booking@cebupacificair.com",
      "Value carrier of the Philippines with the widest domestic network and regional routes from its hubs.",
      "Self-service kiosks and online check-in available; free carry-on rules apply.",
      [("Airbus A320neo", "NARROW_BODY", "RP-C3270", 194),
       ("Airbus A321neo", "NARROW_BODY", "RP-C4101", 226),
       ("ATR 72-600", "TURBOPROP", "RP-C7251", 78)],
      [("5J 501", "AIR", "Manila", "Boracay", "MNL", "MPH", "Terminal 3", "D5", "2026-10-01 06:30", "2026-10-01 07:35", D("3500"), D("2100"), D("200")),
       ("5J 600", "AIR", "Manila", "Hong Kong", "MNL", "HKG", "Terminal 3", "B9", "2026-10-01 10:15", "2026-10-01 12:25", D("14800"), D("8400"), D("220")),
       ("5J 190", "AIR", "Cebu", "Siargao", "CEB", "IAO", "Terminal 1", "C8", "2026-10-01 07:00", "2026-10-01 08:00", D("3800"), D("2300"), D("170")),
       ("5J 290", "AIR", "Manila", "Puerto Princesa", "MNL", "PPS", "Terminal 3", "A10", "2026-10-01 07:20", "2026-10-01 08:50", D("3900"), D("2400"), D("180"))],
      [("Cebu Pacific Cargo", D("0"), "Office hours", "Air freight for parcels"), ("Rapid Rewards Check-in", D("0"), "During check-in", "Priority line in select hubs")]),
    a("Philippines AirAsia", "0288889999", "ask@airasia.ph",
      "Low-cost carrier connecting Philippine cities and Asian destinations from Manila and regional bases.",
      "Mobile app check-in; baggage and meal add-ons purchasable up to 4 hours before flight.",
      [("Airbus A320neo", "NARROW_BODY", "RP-C8902", 188),
       ("Airbus A321neo", "NARROW_BODY", "RP-C8704", 236)],
      [("Z2 710", "AIR", "Manila", "Cebu", "MNL", "CEB", "Terminal 2", "B1", "2026-10-01 08:40", "2026-10-01 09:55", D("3800"), D("2200"), D("190")),
       ("Z2 300", "AIR", "Manila", "Bangkok", "MNL", "DMK", "Terminal 2", "D1", "2026-10-01 11:30", "2026-10-01 13:55", D("12500"), D("6900"), D("210")),
       ("Z2 580", "AIR", "Cebu", "Davao", "CEB", "DVO", "Terminal 1", "A4", "2026-10-01 09:10", "2026-10-01 10:05", D("3600"), D("2000"), D("170"))],
      [("AirAsia Super App", D("0"), "24 hours", "Self-serve booking changes"), ("Xcite Bento", D("650"), "On board", "Prepaid meal bundle")]),
    a("PAL Express", "0288558888", "pax.express@pal.com.ph",
      "Philippine Airlines' regional arm operating short-haul flights across the archipelago from major hubs.",
      "Complimentary 10 kg check-in bag; 7 kg hand-carry.",
      [("Airbus A320", "NARROW_BODY", "RP-C8455", 180),
       ("De Havilland Dash 8-400", "TURBOPROP", "RP-C5923", 76)],
      [("2P 820", "AIR", "Manila", "Baguio", "MNL", "BAG", "Terminal 2", "C3", "2026-10-01 07:40", "2026-10-01 08:45", D("4200"), D("2600"), D("170")),
       ("2P 330", "AIR", "Manila", "Iloilo", "MNL", "ILO", "Terminal 2", "A2", "2026-10-01 06:45", "2026-10-01 08:00", D("3800"), D("2300"), D("170")),
       ("2P 470", "AIR", "Cebu", "Zamboanga", "CEB", "ZAM", "Terminal 1", "B6", "2026-10-01 10:05", "2026-10-01 11:15", D("4100"), D("2500"), D("170"))],
      [("Express Self Check-in", D("0"), "24 hours", "Phone and web check-in"), ("Seat Selection", D("250"), "During booking", "Standard seat")]),
]


def make_activity_photos(activity, use_photos):
    if not use_photos:
        return [("Activity", [])]
    cap, pool = make_activity_images(activity)
    if isinstance(pool, tuple):
        ids = list(pool)
    elif isinstance(pool, list) and pool:
        ids = list(pool[0]) if isinstance(pool[0], tuple) else list(pool)
    else:
        ids = [pool]
    return [(cap, _urls(ids))]


# ---------------------------------------------------------------------------
# THE COMMAND
# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = "Replace demo establishments with real Agoda-listed data and photos."

    def add_arguments(self, parser):
        parser.add_argument("--replace", action="store_true",
                            help="Delete existing demo data for the modules before seeding.")
        parser.add_argument("--no-photos", action="store_true",
                            help="Skip downloading photos.")

    def handle(self, *args, **options):
        if options["replace"]:
            self.stdout.write("Removing demo establishment data...")
            wipe_all(self.stdout.write)

        self._seed_hotels(options)
        self._seed_resorts(options)
        self._seed_staycations(options)
        self._seed_restaurants(options)
        self._seed_landmarks(options)
        self._seed_activities(options)
        self._seed_airlines(options)
        self._deactivate_demo()

        self.stdout.write(self.style.SUCCESS(
            "Done. Real Agoda-listed establishments seeded."))

    def _deactivate_demo(self):
        """Booking-protected demo rows cannot be deleted; hide them from the
        catalog instead by switching them to INACTIVE (row IDs kept intact)."""
        from activities.models import ACTIVITY_STATUS_INACTIVE

        def hide(model, names, inactive_value):
            leftovers = model.objects.exclude(name__in=names)
            count = leftovers.update(status=inactive_value)
            if count:
                self.stdout.write(f"  hid {count} demo {model.__name__}(s)")

        hide(Hotel, {e["name"] for e in HOTELS}, Hotel.Status.INACTIVE)
        hide(Resort, {e["name"] for e in RESORTS}, Resort.Status.INACTIVE)
        hide(Staycation, {e["name"] for e in STAYCATIONS}, Staycation.Status.INACTIVE)
        hide(Restaurant, {e["name"] for e in RESTAURANTS}, Restaurant.Status.INACTIVE)
        hide(Landmark, {e["name"] for e in LANDMARKS}, Landmark.Status.INACTIVE)
        hide(ActivityProvider, {p[0] for p in PROVIDERS}, ActivityProvider.Status.INACTIVE)
        hide(Activity, {a[0] for a in ACTIVITIES}, ACTIVITY_STATUS_INACTIVE)
        hide(Airline, {e["name"] for e in AIRLINES}, Airline.Status.INACTIVE)

    # ---- hotels -----------------------------------------------------------
    def _seed_hotels(self, options):
        use_photos = not options["no_photos"]
        self._room_photo_idx = 0
        slots = make_hotel_slots() if use_photos else [[(c, [])] for c in ("Hotel facade",)]
        for entry, photos in zip(HOTELS, slots):
            hotel, created = Hotel.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "province": entry["province"], "municipality": entry["municipality"],
                    "barangay": entry["barangay"], "contact_number": entry["contact_number"],
                    "email": entry["email"], "operating_schedule": entry["operating_schedule"],
                    "status": Hotel.Status.ACTIVE,
                })
            for num, room in enumerate(entry["rooms"], start=1):
                rtype, rnum, adults, children, rate, features = room
                if hotel.rooms.filter(room_number=rnum).exists():
                    continue
                Room.objects.create(
                    hotel=hotel, room_number=rnum, room_type=rtype,
                    capacity_adults=adults, capacity_children=children,
                    rate=rate, features=features,
                    description=f"{entry['name']} - {rtype.title()} room, "
                                f"sleeps {adults + children}.",
                )
            for r in hotel.rooms.all():
                if use_photos and not r.photos.exists():
                    attach_photos(r, "room", RoomPhoto, "room_photos",
                                  ("Guest bedroom", "Room view", "Room amenities"),
                                  _rotated(BED * 3, self._room_photo_idx))
                self._room_photo_idx += 1
            for name, rate, hours, desc in entry["services"]:
                if hotel.services.filter(name=name).exists():
                    continue
                HotelService.objects.create(
                    hotel=hotel, name=name, rate=D(rate), operating_hours=hours,
                    description=desc, status=HotelService.ServiceStatus.ACTIVE,
                )
            for name, hours, desc, status in entry["amenities"]:
                if hotel.amenities.filter(name=name).exists():
                    continue
                Amenity.objects.create(
                    hotel=hotel, name=name, operating_hours=hours,
                    description=desc, status=status)
            if use_photos and not hotel.photos.exists():
                attach_photos(hotel, "hotel", HotelPhoto, "hotel_photos",
                              [p[0] for p in photos], photos)
                self.stdout.write(f"  Hotel: {hotel.name} | rooms={hotel.rooms.count()} "
                                  f"services={hotel.services.count()} amenities={hotel.amenities.count()} "
                                  f"photos={hotel.photos.count()}")
        self.stdout.write(self.style.SUCCESS(f"Hotels done: {Hotel.objects.count()}"))

    # ---- resorts ----------------------------------------------------------
    def _seed_resorts(self, options):
        use_photos = not options["no_photos"]
        self._unit_photo_idx = 0
        slots = make_resort_slots() if use_photos else [[(c, [])] for c in ("Resort grounds",)]
        for entry, photos in zip(RESORTS, slots):
            resort, created = Resort.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "province": entry["province"], "municipality": entry["municipality"],
                    "barangay": entry["barangay"], "contact_number": entry["contact_number"],
                    "email": entry["email"], "operating_schedule": entry["operating_schedule"],
                    "status": Resort.Status.ACTIVE,
                })
            for num, unit in enumerate(entry["units"], start=1):
                utype, unum, adults, children, rate, features = unit
                if resort.units.filter(unit_number=unum).exists():
                    continue
                RoomVilla.objects.create(
                    resort=resort, unit_number=unum, unit_type=utype,
                    capacity_adults=adults, capacity_children=children,
                    rate=rate, features=features,
                    description=f"{entry['name']} - {utype.title()} unit, "
                                f"sleeps {adults + children}.",
                )
            for u in resort.units.all():
                if use_photos and not u.photos.exists():
                    attach_photos(u, "unit", UnitPhoto, "resort_unit_photos",
                                  ("Guest bedroom", "Unit interior"),
                                  _rotated((BED + BEACH) * 3, self._unit_photo_idx))
                self._unit_photo_idx += 1
            for name, rate, hours, desc in entry["services"]:
                if resort.services.filter(name=name).exists():
                    continue
                ResortService.objects.create(
                    resort=resort, name=name, rate=D(rate), operating_hours=hours,
                    description=desc, status=ResortService.ServiceStatus.ACTIVE,
                )
            if use_photos and not resort.photos.exists():
                attach_photos(resort, "resort", ResortPhoto, "resort_photos",
                              [p[0] for p in photos], photos)
                self.stdout.write(f"  Resort: {resort.name} | units={resort.units.count()} "
                                  f"services={resort.services.count()} photos={resort.photos.count()}")
        self.stdout.write(self.style.SUCCESS(f"Resorts done: {Resort.objects.count()}"))

    # ---- staycations ------------------------------------------------------
    def _seed_staycations(self, options):
        use_photos = not options["no_photos"]
        slots = make_staycation_slots() if use_photos else [[(c, [])] for c in ("Living area",)]
        for entry, photos in zip(STAYCATIONS, slots):
            st, created = Staycation.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "province": entry["province"], "municipality": entry["municipality"],
                    "barangay": entry["barangay"], "contact_number": entry["contact_number"],
                    "email": entry["email"], "capacity": entry["capacity"],
                    "capacity_adults": entry["adults"], "capacity_children": entry["children"],
                    "rate": entry["rate"], "house_rules": entry["rules"],
                    "status": Staycation.Status.ACTIVE,
                })
            for name, rate, hours, desc in entry["services"]:
                if st.services.filter(name=name).exists():
                    continue
                StaycationService.objects.create(
                    staycation=st, name=name, rate=D(rate), operating_hours=hours,
                    description=desc, status=StaycationService.ServiceStatus.ACTIVE,
                )
            if use_photos and not st.photos.exists():
                attach_photos(st, "staycation", StaycationPhoto, "staycation_photos",
                              [p[0] for p in photos], photos)
                self.stdout.write(f"  Staycation: {st.name} | services={st.services.count()} "
                                  f"photos={st.photos.count()}")
        self.stdout.write(self.style.SUCCESS(f"Staycations done: {Staycation.objects.count()}"))

    # ---- restaurants ------------------------------------------------------
    def _seed_restaurants(self, options):
        use_photos = not options["no_photos"]
        slots = make_restaurant_slots() if use_photos else [[(c, [])] for c in ("Dining room",)]
        for entry, photos in zip(RESTAURANTS, slots):
            rest, created = Restaurant.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "location": entry["location"], "cuisine_type": entry["cuisine"],
                    "contact_number": entry["phone"], "email": entry["email"],
                    "operating_hours": entry["hours"], "status": Restaurant.Status.ACTIVE,
                })
            for tno, cap, area in entry["tables"]:
                if rest.tables.filter(table_number=tno).exists():
                    continue
                Table.objects.create(
                    restaurant=rest, table_number=tno, capacity=cap,
                    seating_area=area, status=Table.Status.AVAILABLE,
                )
            if use_photos and not rest.photos.exists():
                attach_photos(rest, "restaurant", RestaurantPhoto, "restaurant_photos",
                              [p[0] for p in photos], photos)
                self.stdout.write(f"  Restaurant: {rest.name} | tables={rest.tables.count()} "
                                  f"photos={rest.photos.count()}")
        self.stdout.write(self.style.SUCCESS(f"Restaurants done: {Restaurant.objects.count()}"))

    # ---- landmarks --------------------------------------------------------
    def _seed_landmarks(self, options):
        use_photos = not options["no_photos"]
        slots = make_landmark_slots() if use_photos else [[(c, [])] for c in ("Landmark",)]
        for entry, photos in zip(LANDMARKS, slots):
            lm, created = Landmark.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "category": entry["category"], "country": entry["country"],
                    "region": entry["region"], "province": entry["province"],
                    "municipality": entry["municipality"], "barangay": entry["barangay"],
                    "contact_number": entry["phone"], "description": entry["description"],
                    "open_hours": entry["open_hours"], "entry_fee": entry["entry_fee"],
                    "capacity": entry["capacity"], "guided_tour_rate": entry["tour_rate"],
                    "private_tour_rate": entry["private_rate"], "status": Landmark.Status.ACTIVE,
                })
            if use_photos and not lm.photos.exists():
                attach_photos(lm, "landmark", LandmarkPhoto, "landmark_photos",
                              [p[0] for p in photos], photos)
                self.stdout.write(f"  Landmark: {lm.name} | photos={lm.photos.count()}")
        self.stdout.write(self.style.SUCCESS(f"Landmarks done: {Landmark.objects.count()}"))

    # ---- activities -------------------------------------------------------
    def _seed_activities(self, options):
        use_photos = not options["no_photos"]
        removed_activity_names = {
            "ATV Ridges Tour Baguio", "Baguio Ecology Trail and Camping",
            "Balicasag Island Dive", "Bohol Countryside Tour",
            "Boracay Island Hopping Tour", "Coron Island Hopping and Kayaking",
            "El Nido Big Lagoon Island Hopping", "Kawasan Canyoneering Adventure",
            "kayak", "Parasailing at Boracay", "Puerto Princesa Underground River Tour",
            "Siargao Surfing Lesson", "Spa Day at The Farm San Benito",
            "Surfing Lesson", "Vigan Heritage Walking Tour",
            "Whale Shark Encounter Oslob", "Zipline at D'juris Park",
        }
        providers = {}
        for name, desc, location, phone, email, area, ops, verified in PROVIDERS:
            provider, _ = ActivityProvider.objects.update_or_create(
                name=name,
                defaults={
                    "description": desc, "location": location, "contact_number": phone,
                    "contact_email": email, "service_area": area, "operating_schedule": ops,
                    "verified": verified, "status": ActivityProvider.Status.ACTIVE,
                })
            providers[name] = provider
        default_caps = ("Activity overview",)
        for idx, act in enumerate(ACTIVITIES):
            (name, category, desc, loc_placeholder, barangay, municipality, province,
             meeting, duration_min, duration_unit, sched_date, sched_time, end_time,
             op_days, fee, rate_type, add_fee, capacity, min_pax, reqdoc, req_equip,
             guide, status, provider_idx) = act
            if name in removed_activity_names:
                continue
            provider = providers[PROVIDERS[provider_idx][0]]
            activity, created = Activity.objects.update_or_create(
                name=name, provider=provider,
                defaults={
                    "category": category, "description": desc,
                    "location": f"{municipality}, {province}",
                    "location_barangay": barangay, "location_municipality": municipality,
                    "location_province": province, "meeting_point": meeting,
                    "duration_minutes": duration_min, "duration_unit": duration_unit,
                    "schedule_date": sched_date, "schedule_time": sched_time,
                    "schedule_end_time": end_time, "operating_days": op_days,
                    "fee": D(fee), "rate_type": rate_type, "additional_fee": D(add_fee),
                    "capacity": capacity, "min_participants": min_pax,
                    "required_documents": reqdoc or "Valid government-issued ID",
                    "required_equipment": req_equip or "Comfortable shoes, sun protection",
                    "guide_required": guide,
                    "status": ACTIVITY_STATUS_ACTIVE,
                })
            if use_photos and not activity.photos.exists():
                img_spec = make_activity_photos(activity.name, True)
                attach_photos(activity, "activity", ActivityPhoto, "activity_photos",
                              [s[0] for s in img_spec], img_spec)
            self.stdout.write(f"  Activity: {activity.name} | provider={provider.name} "
                              f"photos={activity.photos.count()}")
        self.stdout.write(self.style.SUCCESS(
            f"Activity providers: {ActivityProvider.objects.count()}, "
            f"activities: {Activity.objects.count()}"))

    # ---- airlines ---------------------------------------------------------
    def _seed_airlines(self, options):
        from datetime import datetime
        for entry in AIRLINES:
            airline, created = Airline.objects.update_or_create(
                name=entry["name"],
                defaults={
                    "contact_number": entry["phone"], "email": entry["email"],
                    "description": entry["description"], "operating_info": entry["operating"],
                    "status": Airline.Status.ACTIVE,
                })
            for model, atype, tail, seats in entry["aircrafts"]:
                if aircraft := airline.aircrafts.filter(tail_number=tail).first():
                    for fld, val in (("model_name", model), ("aircraft_type", atype),
                                     ("seating_capacity", seats)):
                        setattr(aircraft, fld, val)
                    aircraft.status = Aircraft.Status.AVAILABLE
                    aircraft.save()
                else:
                    Aircraft.objects.create(
                        airline=airline, model_name=model, aircraft_type=atype,
                        tail_number=tail, seating_capacity=seats,
                        status=Aircraft.Status.AVAILABLE,
                    )
            for (fnum, _khang, origin, dest, ocode, dcode, terminal, gate,
                 dep, arr, fc, ec, brate) in entry["flights"]:
                flight, _ = Flight.objects.update_or_create(
                    flight_number=fnum,
                    defaults={
                        "airline": airline,
                        "aircraft": airline.aircrafts.first(),
                        "origin": origin, "destination": dest,
                        "origin_code": ocode, "destination_code": dcode,
                        "terminal": terminal, "gate": gate,
                        "departure_time": datetime.strptime(dep, "%Y-%m-%d %H:%M"),
                        "arrival_time": datetime.strptime(arr, "%Y-%m-%d %H:%M"),
                        "first_class_fare": fc, "economy_fare": ec,
                        "baggage_rate": brate, "status": Flight.Status.SCHEDULED,
                    })
            for name, rate, hours, desc in entry["services"]:
                if airline.services.filter(name=name).exists():
                    continue
                AirlineService.objects.create(
                    airline=airline, name=name, rate=D(rate), operating_hours=hours,
                    description=desc, status=AirlineService.ServiceStatus.ACTIVE,
                )
            self.stdout.write(f"  Airline: {airline.name} | aircraft={airline.aircrafts.count()} "
                              f"flights={airline.flights.count()} services={airline.services.count()}")
        self.stdout.write(self.style.SUCCESS(
            f"Airlines done: {Airline.objects.count()}"))
