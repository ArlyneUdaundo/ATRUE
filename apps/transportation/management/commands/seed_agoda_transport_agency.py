"""Seed the Agoda-listed land-transport agency (Manila Private Airport
Transfer) with its photos, vehicles and drivers — everything the Land
Transport module needs (agency -> cars -> drivers).

Usage:
    python manage.py seed_agoda_transport_agency
"""

from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.core.files import File

from transportation.models import Agency, AgencyPhoto, Driver, Vehicle


PHOTOS_DIR = Path("media") / "agency_photos"

AGENCY_NAME = "Manila Private Airport Transfer (MPV or SUV Service)"

AGENCY_DATA = {
    "name": AGENCY_NAME,
    "contact_number": "+639176543210",
    "email": "bookings@manilaprivateairporttransfer.ph",
    "address": "NAIA Terminal 3 Arrival Area, Andrews Avenue",
    "barangay": "Pasong Tamo",
    "municipality": "Quezon City",
    "province": "Metro Manila",
    "areas": (
        "NAIA Terminal 1, Terminal 2, Terminal 3, Terminal 4;\n"
        "Makati, Bonifacio Global City (BGC), Pasay, Manila, Quezon City, "
        "Paranaque, Ortigas Center;\n"
        "Door-to-door transfers to/from airports, hotels, resorts, casinos "
        "and any address within Metro Manila."
    ),
    "description": (
        "A dedicated private airport-transfer service on Agoda for Manila. A "
        "professional driver meets you at a clearly designated pick-up point "
        "holding a sign with your name, keeps in touch directly via WhatsApp, "
        "and drives you door-to-door in a comfortable air-conditioned MPV or "
        "SUV. Fuel, toll and parking fees are already covered by the booking, "
        "and one hour of free waiting time is included — ideal for both "
        "arrivals and departures across Metro Manila."
    ),
    "operating_hours": "Open 24/7 (daily, including holidays)",
    "status": Agency.Status.ACTIVE,
}

VEHICLES = [
    {
        "vehicle_type": Vehicle.VehicleType.CAR,
        "vehicle_name": "Toyota Vios (Sedan)",
        "plate_number": "NCR-4821",
        "capacity": 3,
        "rate_per_km": Decimal("120.00"),
    },
    {
        "vehicle_type": Vehicle.VehicleType.VAN,
        "vehicle_name": "Toyota Innova (MPV)",
        "plate_number": "NCR-7394",
        "capacity": 6,
        "rate_per_km": Decimal("150.00"),
    },
    {
        "vehicle_type": Vehicle.VehicleType.CAR,
        "vehicle_name": "Toyota Fortuner (SUV)",
        "plate_number": "NCR-2056",
        "capacity": 5,
        "rate_per_km": Decimal("180.00"),
    },
    {
        "vehicle_type": Vehicle.VehicleType.VAN,
        "vehicle_name": "Toyota Hi-Ace (Private Van)",
        "plate_number": "NCR-6713",
        "capacity": 12,
        "rate_per_km": Decimal("220.00"),
    },
]

DRIVERS = [
    {
        "full_name": "Rafael M. Santos",
        "license_number": "NCR-0912345",
        "license_type": "Professional (NP)",
        "accreditation": "LTFRB-accredited airport transfer driver; 8 years experience across NAIA terminals.",
        "contact_number": "+639171110001",
    },
    {
        "full_name": "Joel B. Reyes",
        "license_number": "NCR-0987654",
        "license_type": "Professional (NP)",
        "accreditation": "Meet-and-greet and flight-tracking trained; fluent in English and Tagalog.",
        "contact_number": "+639171110002",
    },
    {
        "full_name": "Marlon D. Cruz",
        "license_number": "NCR-0954321",
        "license_type": "Professional (NP)",
        "accreditation": "Metro Manila route specialist for Makati, BGC and Ortigas hotel pick-ups.",
        "contact_number": "+639171110003",
    },
]

AGENCY_PHOTOS = [
    ("van_static.jpg", "Air-conditioned private van for group transfers", True),
    ("sedan_static.jpg", "Comfortable sedan for solo and couple transfers", False),
    ("suv_static.jpg", "SUV for family and small-group airport transfers", False),
]


class Command(BaseCommand):
    help = "Seed the Agoda Manila Private Airport Transfer agency with photos, vehicles and drivers."

    def handle(self, *args, **options):
        agency, created = Agency.objects.get_or_create(name=AGENCY_NAME, defaults=AGENCY_DATA)
        if not created:
            for field, value in AGENCY_DATA.items():
                setattr(agency, field, value)
            agency.save()
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} agency: {agency.name}"))

        for file_name, caption, is_primary in AGENCY_PHOTOS:
            if not agency.photos.filter(caption=caption).exists() and (PHOTOS_DIR / file_name).exists():
                with open(PHOTOS_DIR / file_name, "rb") as fh:
                    AgencyPhoto.objects.create(
                        agency=agency,
                        image=File(fh, name=file_name),
                        caption=caption,
                        is_primary=is_primary,
                    )
                self.stdout.write(self.style.SUCCESS(f"  Added photo {file_name}"))

        for data in VEHICLES:
            vehicle, v_created = Vehicle.objects.get_or_create(
                agency=agency, plate_number=data["plate_number"], defaults=data)
            if not v_created:
                for field, value in data.items():
                    setattr(vehicle, field, value)
                vehicle.save()
            self.stdout.write(self.style.SUCCESS(
                f"  {'Created' if v_created else 'Updated'} vehicle {vehicle.plate_number}"))

        for data in DRIVERS:
            driver, d_created = Driver.objects.get_or_create(
                agency=agency, license_number=data["license_number"], defaults=data)
            if not d_created:
                for field, value in data.items():
                    setattr(driver, field, value)
                driver.save()
            self.stdout.write(self.style.SUCCESS(
                f"  {'Created' if d_created else 'Updated'} driver {driver.full_name}"))

        self.stdout.write(self.style.SUCCESS(
            f"Done: 1 agency, {agency.photos.count()} photo(s), "
            f"{agency.vehicles.count()} vehicle(s), {agency.drivers.count()} driver(s)."))
