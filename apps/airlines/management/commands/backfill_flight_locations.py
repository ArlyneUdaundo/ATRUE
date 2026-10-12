"""Backfill the structured origin/destination location fields on existing
flights from their free-text ``origin`` / ``destination`` strings.

The route strings follow the app's historical conventions (``"Manila (MNL)"``,
``"Cebu (CEB)"``, ``"Bangkok"``, ``"Los Angeles"``).  This command resolves
those strings against the GeoNames-backed ``locations`` hierarchy the picker
uses, one endpoint at a time, and only when that endpoint has no structured
fields yet.  Resolutions that cannot be made confidently are skipped and
listed, never guessed.
"""

import re

from django.core.management.base import BaseCommand

from airlines.models import Airport, Flight
from atrue_core.location_hierarchy import PLACE_ALIASES, normalize
from locations.models import CityMunicipality, Country, Province, Region

# Trailing airport code: "Manila (MNL)", "Cebu CEB" etc.
CODE_SUFFIX = re.compile(r"\s*\(?[A-Z]{2,4}\)?\s*$")

# A code embedded in a route string, used as a strong hint when the flight's
# own code field is empty: "Manila (MNL)" -> MNL, "Cebu CEB" -> CEB.
CODE_IN_NAME = re.compile(r"\(([A-Z0-9]{2,4})\)\s*$|\b([A-Z0-9]{2,4})\s*$")


def extract_code(value):
    """The IATA/ICAO hint inside a route string, or ``''``."""
    match = CODE_IN_NAME.search((value or "").strip())
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").upper()

PHILIPPINES = "Philippines"

# Airport codes for places whose flight strings are not IATA codes.
# Boracay is served by MPH (Godofredo P. Ramos), which existing flight
# "5J 501 Manila -> Boracay (MPH)" already uses in this app.
AIRPORT_NAME_ALIASES = {
    "boracay": "MPH",
    # The app has always treated bare "Manila" / "Cebu" as the Philippine
    # airports (see OVERRIDES); a bare name has to win over e.g. "Manila
    # Municipal Airport" in Arkansas.
    "manila": "MNL",
}

# Endpoints that do not line up 1:1 with a GeoNames row the picker offers.
# "Manila" is the NCR city whose admin divisions the tree collapses into the
# "Metro Manila" province; Bangkok / Los Angeles live at admin1 level (a region,
# not a province).  ``country / province / municipality`` in picker terms.
OVERRIDES = {
    "manila": (PHILIPPINES, "Metro Manila", ""),
    "bangkok": ("Thailand", "Bangkok", ""),
    "los angeles": ("United States", "California", ""),
}


def clean_name(value):
    name = (value or "").strip()
    name = CODE_SUFFIX.sub(" ", name).strip()
    if "(" in name:
        name = name.split("(")[0].strip()
    return name


def build_maps():
    ph_munis = {}
    for m in CityMunicipality.objects.select_related("province__region__country").filter(
        province__region__country__code="PH"
    ):
        ph_munis.setdefault(normalize(m.name), []).append((m.province.name, m.name))

    ph_provs = {}
    ph_prov_ids = set()
    for p in Province.objects.select_related("region__country").filter(region__country__code="PH"):
        ph_provs.setdefault(normalize(p.name), []).append(p.name)
        ph_prov_ids.add(p.id)

    world_provs = {}
    for p in Province.objects.select_related("region__country").exclude(pk__in=ph_prov_ids):
        world_provs.setdefault(normalize(p.name), []).append((p.name, p.region.country.name))

    regions = {}
    for r in Region.objects.select_related("country"):
        regions.setdefault(normalize(r.name), []).append((r.name, r.country.name))

    countries = {}
    for c in Country.objects.all():
        countries.setdefault(normalize(c.name), c.name)

    aliases = {normalize(k): v for k, v in PLACE_ALIASES.items()}
    return ph_munis, ph_provs, world_provs, regions, countries, aliases


def _pick_province(candidates):
    if not candidates:
        return None
    name, country = sorted(set(candidates), key=lambda c: (c[1] != PHILIPPINES, c[0]))[0]
    return {"country": country, "province": name, "municipality": ""}


def _pick_region(candidates):
    if not candidates:
        return None
    name, country = sorted(set(candidates), key=lambda c: (c[1] != PHILIPPINES, c[0]))[0]
    return {"country": country, "province": name, "municipality": ""}


class Command(BaseCommand):
    help = "Fill origin/destination country/province/municipality for existing flights."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force-airport-links", action="store_true",
            help="Clear existing origin_airport/destination_airport links and relink by code.",
        )

    def handle(self, *args, **options):
        ph_munis, ph_provs, world_provs, regions, countries, aliases = build_maps()
        overrides = {k: v for k, v in OVERRIDES.items()}

        touched = 0
        unresolved = set()
        for flight in Flight.objects.all().iterator():
            changed = []
            for side in ("origin", "destination"):
                country = getattr(flight, f"{side}_country")
                province = getattr(flight, f"{side}_province")
                municipality = getattr(flight, f"{side}_municipality")
                if country or province or municipality:
                    continue
                loc = self._resolve(clean_name(getattr(flight, side)),
                                    ph_munis, ph_provs, world_provs, regions,
                                    countries, aliases, overrides)
                if not loc:
                    unresolved.add(getattr(flight, side))
                    continue
                setattr(flight, f"{side}_country", loc["country"])
                setattr(flight, f"{side}_province", loc["province"])
                setattr(flight, f"{side}_municipality", loc["municipality"])
                changed += [
                    f"{side}_country", f"{side}_province", f"{side}_municipality",
                ]
            if changed:
                flight.save(update_fields=changed)
                touched += 1

        self.stdout.write(self.style.SUCCESS(f"Backfill complete. {touched} flight(s) updated."))
        if unresolved:
            self.stdout.write(self.style.WARNING("Could not resolve (left blank):"))
            for name in sorted(unresolved):
                self.stdout.write(f"  - {name}")

        if options["force_airport_links"]:
            Flight.objects.update(origin_airport=None, destination_airport=None)

        self._link_airports()

    def _link_airports(self):
        """Point existing flights at their Airport rows (by IATA/ICAO code, or by
        a unique clean-name match) so the worldwide airport UI works on old data."""
        touched = []
        unmatched = []
        for flight in Flight.objects.select_related("origin_airport", "destination_airport").all().iterator():
            changed = []
            for side in ("origin", "destination"):
                fk = f"{side}_airport"
                if getattr(flight, fk):
                    continue
                airport = self._match_airport(
                    getattr(flight, f"{side}_code"), getattr(flight, side))
                if airport is None:
                    if getattr(flight, side):
                        unmatched.append((getattr(flight, f"{side}_code"), getattr(flight, side)))
                    continue
                setattr(flight, fk, airport)
                changed.append(fk)
            if changed:
                flight.save(update_fields=changed)
                touched.append(flight.flight_number)

        self.stdout.write(self.style.SUCCESS(
            f"Airport links complete. {len(touched)} flight(s) updated."))
        if unmatched:
            self.stdout.write(self.style.WARNING("Could not link airports (left blank):"))
            for code, name in sorted(set(unmatched)):
                self.stdout.write(f"  - {code or '--'} | {name}")

    def _match_airport(self, code, raw_name):
        code = (code or "").strip().upper()
        if not code:
            code = AIRPORT_NAME_ALIASES.get(normalize(clean_name(raw_name)), "")
        if not code:
            code = extract_code(raw_name)
        if code:
            exact = Airport.objects.filter(iata_code=code)[:1]
            if exact:
                return exact[0]
            icao = Airport.objects.filter(icao_code=code)[:1]
            if icao:
                return icao[0]
        name = clean_name(raw_name)
        key = normalize(name)
        if not key:
            return None
        by_city = list(Airport.objects.filter(city__iexact=name)[:2])
        if len(by_city) == 1:
            return by_city[0]
        candidates = list(
            Airport.objects.filter(airport_name__icontains=name)[:2]
        )
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _resolve(self, name, ph_munis, ph_provs, world_provs, regions,
                 countries, aliases, overrides):
        if not name:
            return None
        key = normalize(name)
        if not key:
            return None

        if key in overrides:
            country, province, municipality = overrides[key]
            return {"country": country, "province": province, "municipality": municipality}

        if key in aliases:
            target = aliases[key]
            return {"country": PHILIPPINES, "province": target.get("province", ""),
                    "municipality": target.get("municipality", "")}

        if key in ph_munis:
            province, municipality = ph_munis[key][0]
            return {"country": PHILIPPINES, "province": province, "municipality": municipality}

        if key in ph_provs:
            return {"country": PHILIPPINES, "province": ph_provs[key][0], "municipality": ""}

        if key in countries:
            return {"country": countries[key], "province": "", "municipality": ""}

        if key in regions:
            return _pick_region(regions[key])

        if key in world_provs:
            return _pick_province(world_provs[key])

        return None