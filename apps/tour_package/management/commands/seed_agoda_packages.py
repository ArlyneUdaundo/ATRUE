"""Seed the three real, Agoda-listed tour packages into the Tour Package
establishment (photo on top, itinerary/plan + included items below).

Usage:
    python manage.py seed_agoda_packages
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from tour_package.models import TourPackage, TourPackagePhoto


class Command(BaseCommand):
    help = "Seed the 3 Agoda tour packages (Boracay / Underground River / Kawasan)."

    def handle(self, *args, **options):
        today = date.today()
        validity_end = today + timedelta(days=365)

        packages = [
            {
                "name": "Boracay Island Hopping Tour (Puka Beach, Coral Garden & Crystal Cove) with Lunch",
                "description": (
                    "A 5-hour island-hopping cruise around Boracay Island on a traditional "
                    "outrigger bangka. Swim in the crystal-clear waters of Puka Beach, snorkel "
                    "among tropical fish at Coral Garden, explore Crystal Cove Island's rock "
                    "formations, and enjoy a freshly cooked Filipino lunch on the beach."
                ),
                "destination_name": "Boracay Island",
                "destination_country": "Philippines",
                "destination_province": "Aklan",
                "destination_city": "Malay",
                "duration_days": 1,
                "base_price": "1999",
                "discount": "99",
                "price": "1900",
                "extra_person_rate": "1900",
                "included_headcount": 1,
                "included_adults": 1,
                "included_children": 0,
                "validity_start_date": today,
                "validity_end_date": validity_end,
                "inclusions": (
                    "Hotel pickup from Station 1, 2 or 3 (~9:00 AM departure);\n"
                    "Ride a shared outrigger bangka with an experienced crew;\n"
                    "Stop 1: Puka Beach (Yapak) - swim and relax on shell-strewn white sand;\n"
                    "Stop 2: Snorkel at Coral Garden - tropical fish and coral reefs;\n"
                    "Stop 3: Crystal Cove Island - rock formations, caves and observation deck "
                    "(entrance fee at own expense);\n"
                    "Optional stop: Magic Island - cliff jumping and snorkeling "
                    "(entrance fee at own expense);\n"
                    "Lunch at Tambisaan Beach - Filipino buffet lunch with seasonal fruits;\n"
                    "Boat cruise back to the departure point (~2:00 PM);\n"
                    "Return drop-off to your Boracay hotel."
                ),
                "exclusions": (
                    "Crystal Cove entrance fee (approx. PHP 200-300/pax);\n"
                    "Magic Island entrance fee (approx. PHP 200-250/pax);\n"
                    "Underwater camera rentals;\n"
                    "Gratuities and personal expenses."
                ),
                "included_tour_guide": True,
                "included_other_services": (
                    "Shared outrigger boat (bangka) with crew;\n"
                    "Snorkeling mask and life vest;\n"
                    "Complimentary bottled water;\n"
                    "Filipino lunch (BBQ, rice, fruits)."
                ),
                "terms_and_conditions": (
                    "Tour departs daily at 9:30 AM from Astoria Station 1 or Bulabog Beach "
                    "depending on season. Tour is subject to sea conditions."
                ),
                "cancellation_policy": (
                    "Free rescheduling or full refund with at least 24 hours' notice."
                ),
                "status": "ACTIVE",
                "photo": "boracay.jpg",
                "photo_caption": "White Beach, Boracay",
            },
            {
                "name": "Puerto Princesa Underground River Day Tour (UNESCO World Heritage)",
                "description": (
                    "A full-day guided tour to one of the New 7 Wonders of Nature and a "
                    "UNESCO World Heritage Site. Glide by paddle boat through 8.2 km of "
                    "limestone caverns on the world's longest navigable underground river, "
                    "then enjoy a Filipino buffet lunch in Sabang."
                ),
                "destination_name": "Puerto Princesa Underground River",
                "destination_country": "Philippines",
                "destination_province": "Palawan",
                "destination_city": "Puerto Princesa City",
                "duration_days": 1,
                "base_price": "2500",
                "discount": "300",
                "price": "2200",
                "extra_person_rate": "2200",
                "included_headcount": 1,
                "included_adults": 1,
                "included_children": 0,
                "validity_start_date": today,
                "validity_end_date": validity_end,
                "inclusions": (
                    "6:30-7:00 AM hotel pickup within Puerto Princesa City;\n"
                    "2-hour scenic air-conditioned drive to Sabang Wharf;\n"
                    "Boat transfer across Sabang Bay to the Underground River entrance;\n"
                    "Guided paddle-boat cruise through the cave (approx. 45 minutes);\n"
                    "Marvel at dramatic stalactites, stalagmites and cathedral chambers;\n"
                    "45-minute audio-guided interpretation of the cave's ecosystem;\n"
                    "Filipino buffet lunch at a local restaurant;\n"
                    "Return to Puerto Princesa City hotel between 4:00-5:00 PM."
                ),
                "exclusions": (
                    "Environmental fee (approx. PHP 150/person) payable on site;\n"
                    "Underground River booking office permit processing of personal I.D.s;\n"
                    "Hotel pickup outside Puerto Princesa City (surcharge applies);\n"
                    "Tips, photos and souvenir purchases."
                ),
                "included_tour_guide": True,
                "included_other_services": (
                    "Visitors entrance permit processed;\n"
                    "Round-trip air-conditioned van transfers;\n"
                    "Boat transfers with life vest;\n"
                    "Service of a licensed tour guide;\n"
                    "Audio tour device;\n"
                    "Buffet lunch."
                ),
                "terms_and_conditions": (
                    "All guests must present a valid I.D. and register at the Underground "
                    "River Booking Office before entering the national park."
                ),
                "cancellation_policy": (
                    "Free cancellation up to 24 hours before the tour for a full refund."
                ),
                "status": "ACTIVE",
                "photo": "underground_river.jpg",
                "photo_caption": "Puerto Princesa Underground River, Palawan",
            },
            {
                "name": "Kawasan Falls Canyoneering Adventure (Badian, Cebu) with Lunch",
                "description": (
                    "Full-day canyoneering adventure along the Badian River ending at the "
                    "famous turquoise Kawasan Falls. Trek, swim and leap your way through "
                    "dramatic limestone canyons under the supervision of a licensed guide, "
                    "then cool off in the crystal-clear waters of Kawasan with a Filipino lunch."
                ),
                "destination_name": "Kawasan Falls",
                "destination_country": "Philippines",
                "destination_province": "Cebu",
                "destination_city": "Badian",
                "duration_days": 1,
                "base_price": "3200",
                "discount": "400",
                "price": "2800",
                "extra_person_rate": "2800",
                "included_headcount": 1,
                "included_adults": 1,
                "included_children": 1,
                "validity_start_date": today,
                "validity_end_date": validity_end,
                "inclusions": (
                    "4:30-5:00 AM hotel pickup from Cebu City or Mactan;\n"
                    "Approx. 3-hour private air-conditioned van transfer to Badian;\n"
                    "Meet your licensed resident canyoneering guide in Badian;\n"
                    "Short motorbike ride to the canyon jump-off point;\n"
                    "3-4 hour canyoneering: trekking, swimming and cliff jumps through "
                    "the Badian River canyons;\n"
                    "Arrive at Kawasan Falls - swim in the crystal-clear turquoise pools;\n"
                    "Complimentary Filipino lunch by the falls;\n"
                    "Return transfer to Cebu City / Mactan hotel (~5:00 PM)."
                ),
                "exclusions": (
                    "Zipline (approx. PHP 500-600/person, optional);\n"
                    "Underwater camera / GoPro rental (approx. PHP 1,000);\n"
                    "Breakfast and other meals;\n"
                    "Tips and personal expenses."
                ),
                "included_tour_guide": True,
                "included_other_services": (
                    "Round-trip private transfers from Cebu City or Mactan;\n"
                    "Licensed and DOT-trained tour guide;\n"
                    "Canyoneering entrance fees;\n"
                    "Safety gear: helmet, life vest, aqua shoes and dry bag;\n"
                    "Bottled water;\n"
                    "Complimentary Filipino lunch."
                ),
                "terms_and_conditions": (
                    "Participants must be physically fit. Pregnant guests and persons with "
                    "serious medical conditions are not allowed; children under 7 not "
                    "permitted. Optional cliff jumps can be skipped based on comfort level."
                ),
                "cancellation_policy": (
                    "Free cancellation up to 24 hours before the activity for a full refund."
                ),
                "status": "ACTIVE",
                "photo": "kawasan.jpg",
                "photo_caption": "Kawasan Falls, Badian Cebu",
            },
        ]

        created = 0
        updated = 0
        for data in packages:
            photo_name = data.pop("photo")
            photo_caption = data.pop("photo_caption")
            pkg, was_created = TourPackage.objects.get_or_create(name=data["name"], defaults=data)
            if not was_created:
                for field, value in data.items():
                    setattr(pkg, field, value)
                pkg.save()
            # Attach the Agoda tour photo.
            primary = pkg.photos.filter(is_primary=True).first()
            if not primary:
                TourPackagePhoto.objects.create(
                    package=pkg,
                    image="tour_package_photos/" + photo_name,
                    caption=photo_caption,
                    is_primary=True,
                )
            created += was_created
            updated += 0 if was_created else 1
            self.stdout.write(self.style.SUCCESS(f"  {'Created' if was_created else 'Updated'} {pkg.name}"))

        # Keep only the three Agoda tours active in the establishment.
        active_names = [p["name"] for p in packages]
        inactive = TourPackage.objects.filter(status="ACTIVE").exclude(name__in=active_names)
        count = inactive.update(status="INACTIVE")
        self.stdout.write(self.style.WARNING(f"  Deactivated {count} non-Agoda package(s)."))

        self.stdout.write(self.style.SUCCESS(
            f"Done: {created} created, {updated} updated. Active Agoda packages: {len(active_names)}"))