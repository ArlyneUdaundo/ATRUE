"""Seed the worldwide airport reference table from the public OurAirports dataset.

Airports are database-driven seed data (never hard-coded into templates or
JavaScript).  This command loads the OurAirports ``airports.csv`` and keeps only
the rows that are real airports with an IATA code (small/medium/large).  The
``country`` / ``region`` fields are resolved against the existing GeoNames-backed
``locations`` hierarchy so the airport list bridges to the worldwide location
data already in ATRUE.

Usage::

    python manage.py seed_airports              # download + upsert
    python manage.py seed_airports --path file  # reuse a local CSV
    python manage.py seed_airports --source only

If the download is unavailable a small built-in fallback list is used so the
module still works offline; ``seed_airports --source only`` writes a fresh
download to the given path without touching the database.
"""

import csv
import math
import os
import shutil
import tempfile
import urllib.request
from collections import defaultdict

from django.core.management.base import BaseCommand

from airlines.models import Airport
from locations.models import Country, Province, Region

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORT_TYPES = {"small_airport", "medium_airport", "large_airport"}

#: GeoNames airport records are keyed by coordinates in a 0.01 degree grid so
#: an OurAirports airport can be matched to its GeoNames record (and therefore
#: its administrative division) without any name matching.  0.01 deg is ~1.1 km.
GEONAMES_GRID_STEP = 0.01
GEONAMES_MAX_KM = 15.0

#: Local GeoNames dump used to resolve the airport's region name.  When it is
#: not present the command falls back to ISO subdivision codes.
GEONAMES_DUMP = os.path.join(tempfile.gettempdir(), "opencode", "geonames", "allCountries.txt")

# OurAirports ISO 3166-2 subdivision codes do not always match the GeoNames
# admin1/admin2 code the ATRUE hierarchy was seeded with.  The few Philippine
# mismatches are mapped here; everything else resolves directly.
PH_REGION_ALIASES = {"00": "NCR", "MNL": "NCR", "NCR": "NCR"}

#: Minimal fallback rows (same column order as airports.csv) used only when the
#: live download is unavailable, so the worldwide airport picker still works.
#: Columns: id, ident, type, name, latitude_deg, longitude_deg, elevation_ft,
#: continent, iso_country, iso_region, municipality, scheduled_service,
#: icao_code, iata_code, gps_code, local_code, home_link, wikipedia_link, keywords
FALLBACK_ROWS = [
    (1, "RPLL", "large_airport", "Ninoy Aquino International Airport", 14.5086, 121.0198, 75, "AS", "PH", "PH-00", "Manila (Pasay)", "yes", "RPLL", "MNL", "RPLL", "", "", "https://en.wikipedia.org/wiki/Ninoy_Aquino_International_Airport", ""),
    (2, "RPVM", "large_airport", "Mactan Cebu International Airport", 10.3075, 123.9794, 31, "AS", "PH", "PH-CEB", "Cebu City/Lapu-Lapu City", "yes", "RPVM", "CEB", "RPVM", "", "", "https://en.wikipedia.org/wiki/Mactan%E2%80%93Cebu_International_Airport", ""),
    (3, "RPMD", "medium_airport", "Francisco Bangoy International Airport", 7.1255, 125.6458, 96, "AS", "PH", "PH-DVO", "Davao City", "yes", "RPMD", "DVO", "RPMD", "", "", "https://en.wikipedia.org/wiki/Francisco_Bangoy_International_Airport", ""),
    (4, "RPMZ", "medium_airport", "Zamboanga International Airport", 6.9224, 122.0596, 20, "AS", "PH", "PH-ZAM", "Zamboanga City", "yes", "RPMZ", "ZAM", "RPMZ", "", "", "https://en.wikipedia.org/wiki/Zamboanga_International_Airport", ""),
    (5, "RPVP", "medium_airport", "Puerto Princesa International Airport", 9.7421, 118.7587, 22, "AS", "PH", "PH-PLW", "Puerto Princesa City", "yes", "RPVP", "PPS", "RPVP", "", "", "https://en.wikipedia.org/wiki/Puerto_Princesa_International_Airport", ""),
    (6, "RPLI", "medium_airport", "Laoag International Airport", 18.1781, 120.5321, 25, "AS", "PH", "PH-ILN", "Laoag", "yes", "RPLI", "LAO", "RPLI", "", "", "", ""),
    (7, "RPMG", "small_airport", "Dipolog Airport", 8.6010, 123.3419, 12, "AS", "PH", "PH-ZAN", "Dipolog", "yes", "RPMG", "DPL", "RPMG", "", "", "", ""),
    (8, "RPVE", "small_airport", "Godofredo P. Ramos Airport", 11.9244, 121.9542, 6, "AS", "PH", "PH-AKL", "Malay (Boracay)", "yes", "RPVE", "MPH", "RPVE", "", "", "https://en.wikipedia.org/wiki/Godofredo_P._Ramos_Airport", ""),
    (9, "RPUB", "small_airport", "Loakan Airport", 16.3755, 120.6190, 4251, "AS", "PH", "PH-BEN", "Baguio City", "yes", "RPUB", "BAG", "RPUB", "", "", "", ""),
    (10, "RPMI", "small_airport", "Iligan Airport", 8.2298, 124.2306, 20, "AS", "PH", "PH-BAS", "Iligan City", "yes", "RPMI", "IGN", "RPMI", "", "", "", ""),
    (11, "RPNS", "small_airport", "Surigao Airport", 8.5122, 125.6721, 20, "AS", "PH", "PH-SUR", "Surigao City", "yes", "RPNS", "SUG", "RPNS", "", "", "", ""),
    (12, "RPNO", "small_airport", "Siargao Airport", 9.8591, 126.0141, 12, "AS", "PH", "PH-SUR", "Dapa (Siargao)", "yes", "RPNO", "IAO", "RPNO", "", "", "", ""),
    (13, "WSSS", "large_airport", "Singapore Changi Airport", 1.3644, 103.9915, 22, "AS", "SG", "SG-04", "Singapore", "yes", "WSSS", "SIN", "WSSS", "", "", "https://en.wikipedia.org/wiki/Singapore_Changi_Airport", ""),
    (14, "RJTT", "large_airport", "Tokyo Haneda International Airport", 35.5494, 139.7798, 21, "AS", "JP", "JP-13", "Tokyo", "yes", "RJTT", "HND", "RJTT", "", "", "https://en.wikipedia.org/wiki/Haneda_Airport", ""),
    (15, "RJAA", "large_airport", "Narita International Airport", 35.7722, 140.3883, 141, "AS", "JP", "JP-12", "Narita", "yes", "RJAA", "NRT", "RJAA", "", "", "https://en.wikipedia.org/wiki/Narita_International_Airport", ""),
    (16, "OMDB", "large_airport", "Dubai International Airport", 25.2528, 55.3644, 62, "AS", "AE", "AE-DU", "Dubai", "yes", "OMDB", "DXB", "OMDB", "", "", "https://en.wikipedia.org/wiki/Dubai_International_Airport", ""),
    (17, "EGLL", "large_airport", "London Heathrow Airport", 51.4706, -0.4619, 83, "EU", "GB", "GB-ENG", "London", "yes", "EGLL", "LHR", "EGLL", "", "", "https://en.wikipedia.org/wiki/Heathrow_Airport", ""),
    (18, "LFPG", "large_airport", "Charles de Gaulle International Airport", 49.0097, 2.5479, 392, "EU", "FR", "FR-IDF", "Paris", "yes", "LFPG", "CDG", "LFPG", "", "", "https://en.wikipedia.org/wiki/Charles_de_Gaulle_Airport", ""),
    (19, "KLAX", "large_airport", "Los Angeles International Airport", 33.9425, -118.4081, 125, "NA", "US", "US-CA", "Los Angeles", "yes", "KLAX", "LAX", "KLAX", "", "", "https://en.wikipedia.org/wiki/Los_Angeles_International_Airport", ""),
    (20, "KJFK", "large_airport", "John F. Kennedy International Airport", 40.6398, -73.7789, 13, "NA", "US", "US-NY", "New York", "yes", "KJFK", "JFK", "KJFK", "", "", "https://en.wikipedia.org/wiki/John_F._Kennedy_International_Airport", ""),
    (21, "RKSI", "large_airport", "Incheon International Airport", 37.4602, 126.4407, 23, "AS", "KR", "KR-28", "Seoul", "yes", "RKSI", "ICN", "RKSI", "", "", "https://en.wikipedia.org/wiki/Incheon_International_Airport", ""),
    (22, "VHHH", "large_airport", "Hong Kong International Airport", 22.3080, 113.9185, 28, "AS", "HK", "HK-NT", "Hong Kong", "yes", "VHHH", "HKG", "VHHH", "", "", "https://en.wikipedia.org/wiki/Hong_Kong_International_Airport", ""),
    (23, "VTBS", "large_airport", "Suvarnabhumi Airport", 13.6900, 100.7501, 5, "AS", "TH", "TH-10", "Bangkok", "yes", "VTBS", "BKK", "VTBS", "", "", "https://en.wikipedia.org/wiki/Suvarnabhumi_Airport", ""),
    (24, "VTBD", "large_airport", "Don Mueang International Airport", 13.9126, 100.6068, 9, "AS", "TH", "TH-10", "Bangkok", "yes", "VTBD", "DMK", "VTBD", "", "", "https://en.wikipedia.org/wiki/Don_Mueang_International_Airport", ""),
    (25, "YSSY", "large_airport", "Sydney Kingsford Smith International Airport", -33.9461, 151.1772, 21, "OC", "AU", "AU-NSW", "Sydney", "yes", "YSSY", "SYD", "YSSY", "", "", "https://en.wikipedia.org/wiki/Sydney_Airport", ""),
    (26, "RJBB", "large_airport", "Kansai International Airport", 34.4347, 135.2442, 26, "AS", "JP", "JP-27", "Osaka", "yes", "RJBB", "KIX", "RJBB", "", "", "https://en.wikipedia.org/wiki/Kansai_International_Airport", ""),
    (27, "EDDF", "large_airport", "Frankfurt Main Airport", 50.0333, 8.5706, 364, "EU", "DE", "DE-HE", "Frankfurt am Main", "yes", "EDDF", "FRA", "EDDF", "", "", "https://en.wikipedia.org/wiki/Frankfurt_Airport", ""),
    (28, "EHAM", "large_airport", "Amsterdam Airport Schiphol", 52.3086, 4.7639, -11, "EU", "NL", "NL-NH", "Amsterdam", "yes", "EHAM", "AMS", "EHAM", "", "", "https://en.wikipedia.org/wiki/Amsterdam_Airport_Schiphol", ""),
    (29, "RCTP", "large_airport", "Taiwan Taoyuan International Airport", 25.0777, 121.2328, 108, "AS", "TW", "TW-TAO", "Taoyuan", "yes", "RCTP", "TPE", "RCTP", "", "", "https://en.wikipedia.org/wiki/Taoyuan_International_Airport", ""),
    (30, "WIII", "large_airport", "Soekarno-Hatta International Airport", -6.1256, 106.6559, 33, "AS", "ID", "ID-BT", "Jakarta", "yes", "WIII", "CGK", "WIII", "", "", "https://en.wikipedia.org/wiki/Soekarno%E2%80%93Hatta_International_Airport", ""),
    (31, "VVTS", "large_airport", "Tan Son Nhat International Airport", 10.8188, 106.6520, 33, "AS", "VN", "VN-SE", "Ho Chi Minh City", "yes", "VVTS", "SGN", "VVTS", "", "", "https://en.wikipedia.org/wiki/Tan_Son_Nhat_International_Airport", ""),
    (32, "VMMC", "large_airport", "Macau International Airport", 22.1496, 113.5916, 20, "AS", "MO", "MO", "Macau", "yes", "VMMC", "MFM", "VMMC", "", "", "https://en.wikipedia.org/wiki/Macau_International_Airport", ""),
]


def _clean_city(value):
    """Turn ourAirports municipalities into tidy city names: ``"Manila (Pasay)"``
    -> ``"Manila"`` and ``"Cebu City/Lapu-Lapu City"`` -> ``"Cebu City"``."""
    value = (value or '').strip()
    value = value.split('/')[0].strip()
    if '(' in value:
        value = value.split('(')[0].strip()
    return value


class Command(BaseCommand):
    help = "Load worldwide airports into the Airport table."

    def add_arguments(self, parser):
        parser.add_argument('--path', default='', help='Local airports.csv to read.')
        parser.add_argument('--source', action='store_true',
                            help='Only download the CSV to a file; do not seed the DB.')
        parser.add_argument('--geonames', default='',
                            help='Path to the GeoNames allCountries.txt dump (optional).')

    def handle(self, *args, **options):
        path = options['path']
        if not path:
            path = self._download()
        if options['source']:
            self.stdout.write(f"Saved source to: {path}")
            return

        rows = self._read_rows(path)
        countries = {c.code: c.name for c in Country.objects.all()}
        geonames = self._build_geonames_index(options['geonames'])
        created = updated = skipped = 0

        for row in rows:
            iata = (row.get('iata_code') or '').strip().upper()
            if row.get('type') not in AIRPORT_TYPES or not iata:
                continue
            name = (row.get('name') or '').strip()
            city = _clean_city(row.get('municipality'))
            iso_country = (row.get('iso_country') or '').strip().upper()
            country = countries.get(iso_country) or iso_country
            region = self._resolve_region(iso_country, (row.get('iso_region') or '').strip(),
                                          row.get('latitude_deg'), row.get('longitude_deg'),
                                          geonames)
            icao = (row.get('icao_code') or row.get('gps_code') or '').strip().upper()
            try:
                lat = float(row.get('latitude_deg')) if row.get('latitude_deg') else None
            except (TypeError, ValueError):
                lat = None
            try:
                lon = float(row.get('longitude_deg')) if row.get('longitude_deg') else None
            except (TypeError, ValueError):
                lon = None

            airport = Airport.objects.filter(iata_code=iata).order_by('id').first()
            if airport is None:
                Airport.objects.create(
                    airport_name=name[:200], iata_code=iata[:8], icao_code=icao[:8],
                    city=city[:120], country=country[:100], country_code=iso_country[:2],
                    region=region[:120], latitude=lat, longitude=lon,
                    status=Airport.Status.ACTIVE)
                created += 1
            else:
                if (airport.airport_name != name or airport.city != city
                        or airport.country != country or airport.country_code != iso_country
                        or airport.region != region or airport.icao_code != icao):
                    airport.airport_name = name[:200]
                    airport.city = city[:120]
                    airport.country = country[:100]
                    airport.country_code = iso_country[:2]
                    airport.region = region[:120]
                    airport.icao_code = icao[:8]
                    airport.latitude = lat
                    airport.longitude = lon
                    airport.status = Airport.Status.ACTIVE
                    airport.save(update_fields=[
                        'airport_name', 'icao_code', 'city', 'country', 'country_code',
                        'region', 'latitude', 'longitude', 'status'])
                    updated += 1
                else:
                    skipped += 1

        self.stdout.write(self.style.SUCCESS(
            "Airport seed complete: "
            f"{created} created, {updated} updated, {skipped} unchanged "
            f"({Airport.objects.count()} airports in DB)."))

    def _build_geonames_index(self, explicit_path):
        """Index GeoNames airport (AIRP) records by (country, 0.01deg cell)."""
        dump = explicit_path or GEONAMES_DUMP
        if not os.path.exists(dump):
            return None
        self.stdout.write("Building GeoNames airport index (this reads the dump once)...")
        index = defaultdict(list)

        def grid(lat, lng):
            return (round(float(lat), 2), round(float(lng), 2))

        with open(dump, encoding='utf-8') as fh:
            for line in fh:
                p = line.rstrip('\n').split('\t')
                if len(p) < 12 or p[7] != 'AIRP':
                    continue
                try:
                    k = grid(p[4], p[5])
                except (TypeError, ValueError):
                    continue
                index[(p[8], k)].append((float(p[4]), float(p[5]), p[10], p[11]))
        return index

    def _resolve_region(self, country_code, iso_region, lat, lng, geonames):
        if geonames is not None and lat and lng:
            admin1, admin2 = self._nearest(geonames, country_code, lat, lng)
            if admin1:
                region = Region.objects.filter(
                    country__code=country_code, code__iexact=admin1).first()
                if region:
                    if admin2:
                        province = region.provinces.filter(code__iexact=admin2).first()
                        if province:
                            return province.name
                    return region.name
        return self._fallback_region(country_code, iso_region)

    def _nearest(self, index, country_code, lat, lng):
        best1 = best2 = None
        best_d = GEONAMES_MAX_KM
        lat, lng = float(lat), float(lng)

        def hav(a, b, c, d):
            R = 6371.0
            p1, p2 = math.radians(a), math.radians(c)
            dphi = math.radians(c - a)
            dlmb = math.radians(d - b)
            s = (math.sin(dphi / 2) ** 2
                 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
            return 2 * R * math.asin(math.sqrt(s))

        step = GEONAMES_GRID_STEP
        for dlat in (-step, 0, step):
            for dlng in (-step, 0, step):
                cell = (round(lat + dlat, 2), round(lng + dlng, 2))
                for plat, plng, admin1, admin2 in index.get((country_code, cell), ()):
                    distance = hav(lat, lng, plat, plng)
                    if distance < best_d:
                        best_d, best1, best2 = distance, admin1, admin2
        return best1, best2

    def _fallback_region(self, country_code, iso_region):
        if not iso_region:
            return ''
        suffix = iso_region.split('-')[-1].strip().upper()
        candidates = [suffix]
        if country_code == 'PH':
            candidates = [PH_REGION_ALIASES.get(suffix, suffix), suffix]
        for code in candidates:
            region = Region.objects.filter(country__code=country_code, code__iexact=code).first()
            if region:
                return region.name
            province = Province.objects.filter(
                region__country__code=country_code, code__iexact=code).first()
            if province:
                return province.name
        return iso_region

    def _download(self):
        cache = os.path.join(tempfile.gettempdir(), 'opencode', 'ourairports', 'airports.csv')
        if os.path.exists(cache):
            return cache
        self.stdout.write(f"Downloading {OURAIRPORTS_URL} ...")
        try:
            req = urllib.request.Request(OURAIRPORTS_URL, headers={'User-Agent': 'ATRUE/1.0'})
            with urllib.request.urlopen(req, timeout=60) as resp, open(cache, 'wb') as out:
                shutil.copyfileobj(resp, out)
            return cache
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Download failed ({exc}); using built-in fallback list."))
            return None

    def _read_rows(self, path):
        if path:
            with open(path, encoding='utf-8-sig') as fh:
                yield from csv.DictReader(fh)
            return
        for row in FALLBACK_ROWS:
            keys = ["id", "ident", "type", "name", "latitude_deg", "longitude_deg",
                    "elevation_ft", "continent", "iso_country", "iso_region",
                    "municipality", "scheduled_service", "icao_code", "iata_code",
                    "gps_code", "local_code", "home_link", "wikipedia_link", "keywords"]
            yield dict(zip(keys, row))