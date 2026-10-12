"""Populate the database with sample establishments for the ATRUE simulation.

Usage:
    python manage.py seed_data            # seed only if tables are empty
    python manage.py seed_data --force    # clear establishment tables and re-seed
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from activities.models import Activity, ActivityProvider
from airlines.models import Aircraft, Airline, Flight
from hotels.models import Hotel, Room, Service as HotelService
from landmarks.models import Landmark
from tour_package.models import TourPackage
from resorts.models import Resort, RoomVilla, Service as ResortService
from restaurants.models import Restaurant, Table
from staycations.models import Service as StaycationService, Staycation
from transportation.models import Agency, Driver, Vehicle


class Command(BaseCommand):
    help = "Seed sample data for all establishments in the ATRUE platform."

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help="Clear existing establishment data and re-seed.")

    def handle(self, *args, **options):
        force = options['force']
        if self._has_data() and not force:
            self.stdout.write(self.style.WARNING(
                "Establishments already have data. Use --force to re-seed."))
            return
        if force:
            self._clear_all()
            self.stdout.write(self.style.WARNING("Cleared existing establishment data."))
        self._seed()
        self.stdout.write(self.style.SUCCESS("Seeding complete."))

    def _has_data(self):
        return any([
            Airline.objects.exists(), Hotel.objects.exists(), Resort.objects.exists(),
            Staycation.objects.exists(), Restaurant.objects.exists(),
            Agency.objects.exists(), Landmark.objects.exists(),
            ActivityProvider.objects.exists(),
            TourPackage.objects.exists(),
        ])

    def _clear_all(self):
        TourPackage.objects.all().delete()
        Flight.objects.all().delete()
        Aircraft.objects.all().delete()
        Airline.objects.all().delete()
        Hotel.objects.all().delete()
        Resort.objects.all().delete()
        Staycation.objects.all().delete()
        Restaurant.objects.all().delete()
        Agency.objects.all().delete()
        Landmark.objects.all().delete()
        ActivityProvider.objects.all().delete()

    def _seed(self):
        self._seed_airlines()
        self._seed_hotels()
        self._seed_resorts()
        self._seed_staycations()
        self._seed_restaurants()
        self._seed_transportation()
        self._seed_landmarks()
        self._seed_activities()
        self._seed_packages()

    # --- Airlines ---
    def _seed_airlines(self):
        airlines = {}
        for name, contact in [
            ('Philippine Airlines', '(02) 8820-1234'),
            ('Cebu Pacific Air', '(02) 8702-0888'),
            ('AirAsia Philippines', '(02) 7370-4747'),
            ('PAL Express', '(02) 8820-1234'),
        ]:
            airlines[name] = Airline.objects.create(name=name, contact_number=contact)

        fleet = [
            (airlines['Philippine Airlines'], 'Airbus A321neo', 'RP-C9912', 189),
            (airlines['Philippine Airlines'], 'Boeing 777-300ER', 'RP-C7777', 370),
            (airlines['Cebu Pacific Air'], 'Airbus A320neo', 'RP-C6723', 188),
            (airlines['Cebu Pacific Air'], 'Airbus A330-900neo', 'RP-C3901', 460),
            (airlines['AirAsia Philippines'], 'Airbus A320', 'RP-C8618', 180),
            (airlines['PAL Express'], 'Bombardier Q400', 'RP-C5910', 86),
        ]
        aircrafts = []
        for airline, model, tail, seats in fleet:
            aircrafts.append(Aircraft.objects.create(
                airline=airline, model_name=model, tail_number=tail, seating_capacity=seats))

        now = timezone.now()
        routes = [
            # (aircraft, flight_number, origin, destination, hour_offset, duration_h, fare)
            (aircrafts[0], 'PR 101', 'Manila (MNL)', 'Cebu (CEB)', 2, 1.25, 3890),
            (aircrafts[1], 'PR 521', 'Manila (MNL)', 'Davao (DVO)', 5, 2, 4550),
            (aircrafts[2], '5J 553', 'Manila (MNL)', 'Boracay (MPH)', 3, 1, 3290),
            (aircrafts[3], '5J 801', 'Manila (MNL)', 'Singapore (SIN)', 9, 3.5, 12900),
            (aircrafts[4], 'Z2 217', 'Manila (MNL)', 'Cebu (CEB)', 7, 1.25, 2190),
            (aircrafts[5], '2P 2020', 'Manila (MNL)', 'Tuguegarao (TUG)', 11, 1.25, 2650),
            (aircrafts[0], 'PR 102', 'Cebu (CEB)', 'Manila (MNL)', 14, 1.25, 3790),
            (aircrafts[2], '5J 409', 'Manila (MNL)', 'Puerto Princesa (PPS)', 16, 1.5, 3590),
        ]
        for aircraft, number, origin, dest, offset, duration, fare in routes:
            dep = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=offset)
            Flight.objects.create(
                airline=aircraft.airline, aircraft=aircraft, flight_number=number,
                origin=origin, destination=dest, departure_time=dep,
                arrival_time=dep + timedelta(hours=duration), economy_fare=fare, first_class_fare=fare,
            )
        self.stdout.write(self.style.SUCCESS(f"  Airlines: {len(airlines)} | Aircraft: {len(aircrafts)} | Flights: 8"))

    # --- Hotels ---
    def _seed_hotels(self):
        hotels_data = [
            ('Manila Bay Grand Hotel', 'Roxas Blvd, Malate, Manila', '(02) 8523-9876', 'frontdesk@mbgh.ph'),
            ('Intramuros Heritage Hotel', 'Intramuros, Manila', '(02) 8527-4455', 'stay@ihh.ph'),
            ('Highlands View Hotel', 'Tagaytay City, Cavite', '(046) 413-8890', 'info@hvh.ph'),
            ('Cagayan Gateway Hotel', 'Tuguegarao City, Cagayan', '(078) 844-2233', 'reserve@cgh.ph'),
            ('Pearl Palm Hotel', 'Bonifacio Global City, Taguig', '(02) 8777-8899', 'rooms@pearlpalm.ph'),
        ]
        hotels = []
        for name, loc, contact, email in hotels_data:
            hotels.append(Hotel.objects.create(name=name, location=loc, contact_number=contact, email=email))

        room_plans = [
            # (room types, rates)
            (['Deluxe', 'Junior Suite', 'Executive Suite'], [2500, 4500, 7500]),
            (['Standard', 'Deluxe', 'Heritage Suite'], [2200, 3200, 5800]),
            (['Garden Room', 'Deluxe Lake View'], [3100, 4600]),
            (['Standard', 'Superior', 'Executive'], [1900, 2700, 4200]),
            (['Deluxe', 'Premier', 'Family Suite'], [3500, 5200, 8000]),
        ]
        for hi, (types, rates) in enumerate(room_plans):
            for room_no, (rtype, rate) in enumerate(zip(types, rates), start=101):
                Room.objects.create(
                    hotel=hotels[hi], room_number=str(room_no), room_type=rtype,
                    capacity=2 if 'Suite' not in rtype else 4, rate=rate,
                )
        HotelService.objects.create(hotel=hotels[0], name='Room Service', description='24/7 in-room dining', fee=250)
        HotelService.objects.create(hotel=hotels[0], name='Airport Shuttle', description='Complimentary transfers', fee=0)
        HotelService.objects.create(hotel=hotels[4], name='Concierge', description='Tour arrangements', fee=500)
        self.stdout.write(self.style.SUCCESS(f"  Hotels: {len(hotels)} | Rooms: {Room.objects.count()}"))

    # --- Resorts ---
    def _seed_resorts(self):
        resorts_data = [
            ('Coral Blue Beach Resort', 'Station 1, Boracay Island, Aklan', '(036) 288-3344'),
            ('Hinulugan Cove Resort', 'Puerto Princesa, Palawan', '(048) 433-5566'),
            ('Cloud 9 Surf Resort', 'General Luna, Siargao', '(086) 800-1133'),
            ('Palaui Island Retreat', 'Santa Ana, Cagayan', '(078) 123-4567'),
            ('Pagsanjan Falls Lodge', 'Pagsanjan, Laguna', '(049) 504-2233'),
        ]
        resorts = []
        for name, loc, contact in resorts_data:
            resorts.append(Resort.objects.create(name=name, location=loc, contact_number=contact))

        unit_plans = [
            [('Room', 2500), ('Villa', 6500), ('Beach Cabana', 3800)],
            [('Villa', 7200), ('Tree House', 4800)],
            [('Surfer Room', 3200), ('Surf Villa', 6900)],
            [('Cottage', 2800), ('Family Villa', 5500), ('Dorm Room', 1200)],
            [('Room', 2200), ('Riverside Cabin', 3500)],
        ]
        for res_idx, plans in enumerate(unit_plans):
            for unit_no, (utype, rate) in enumerate(plans, start=1):
                RoomVilla.objects.create(
                    resort=resorts[res_idx], unit_type=utype, unit_number=str(unit_no),
                    capacity=2 if utype == 'Room' else 4, rate=rate,
                )
        ResortService.objects.create(resort=resorts[0], name='Island Hopping', description='Boat tour of nearby islets', fee=1500)
        ResortService.objects.create(resort=resorts[0], name='Snorkeling Gear', description='Mask, fins and life vest', fee=350)
        ResortService.objects.create(resort=resorts[3], name='Kayak Rental', description='Per hour', fee=200)
        self.stdout.write(self.style.SUCCESS(f"  Resorts: {len(resorts)} | Units: {RoomVilla.objects.count()}"))

    # --- Staycations ---
    def _seed_staycations(self):
        data = [
            ('Cozy Loft Staycation', 'Kapasigan Ave, Quezon City', 3, 1800),
            ('Seaside Family Home', 'San Fernando, La Union', 6, 4500),
            ('Garden Studio', 'Marikina Heights, Marikina', 2, 1500),
            ('Riverside Timber House', 'Sta. Cruz, Laguna', 5, 5200),
            ('Cape San Agustin Vista', 'San Agustin, Isabela', 4, 2900),
        ]
        staycations = []
        for name, loc, cap, rate in data:
            staycations.append(Staycation.objects.create(name=name, location=loc, capacity=cap, rate=rate))
        StaycationService.objects.create(staycation=staycations[0], name='Self Check-in', fee=0)
        StaycationService.objects.create(staycation=staycations[0], name='Housekeeping', fee=300)
        StaycationService.objects.create(staycation=staycations[2], name='Netflix & Wi-Fi', fee=0)
        self.stdout.write(self.style.SUCCESS(f"  Staycations: {len(staycations)}"))

    # --- Restaurants ---
    def _seed_restaurants(self):
        data = [
            ('Tatak-Bauan Kitchen', 'Baggao, Cagayan', 'Filipino'),
            ('Sinigang House', 'Diliman, Quezon City', 'Filipino'),
            ('King Crab Seafood', 'Greenhills, San Juan', 'Seafood'),
            ('Little Italy Pizzeria', 'Makati City', 'Italian'),
            ('Sizzle & Smoke BBQ', 'Santiago, Isabela', 'BBQ / Grill'),
            ('Green Bowl Cafe', 'Cebu City', 'Healthy / Vegan'),
        ]
        restaurants = []
        for name, loc, cuisine in data:
            restaurants.append(Restaurant.objects.create(name=name, location=loc, cuisine_type=cuisine))
        for ri, rest in enumerate(restaurants):
            for tn in range(1, 6):
                Table.objects.create(
                    restaurant=rest, table_number=f'{ri + 1}-{tn}',
                    capacity=2 if tn % 2 == 0 else 4,
                )
        self.stdout.write(self.style.SUCCESS(f"  Restaurants: {len(restaurants)} | Tables: {Table.objects.count()}"))

    # --- Transportation ---
    def _seed_transportation(self):
        agencies_data = [
            ('Victory Transport Co.', '(02) 8926-0044'),
            ('DMMMSU Trans', '(072) 700-1122'),
            ('Baguio Mount Trans', '(074) 423-8899'),
            ('Cagayan North Rides', '(078) 445-6677'),
        ]
        vehicles_data = [
            ('Victory Transport Co.', ('Deluxe Bus', 'CDU-101', 44), ('Solar Coach', 'CDU-102', 44)),
            ('DMMMSU Trans', ('Van', 'ABX-112', 12), ('Bus', 'ABX-113', 40)),
            ('Baguio Mount Trans', ('Tourist Bus', 'BGU-221', 36), ('Van', 'BGU-222', 11)),
            ('Cagayan North Rides', ('Hi-ace Van', 'TUG-301', 14), ('Jeepney', 'TUG-302', 18)),
        ]
        agencies, vehicles = [], []
        for name, contact in agencies_data:
            agencies.append(Agency.objects.create(name=name, contact_number=contact))
        for ai, (agency_name, v1, v2) in enumerate(vehicles_data):
            vehicles.append(Vehicle.objects.create(agency=agencies[ai], vehicle_type=v1[0], plate_number=v1[1], capacity=v1[2]))
            vehicles.append(Vehicle.objects.create(agency=agencies[ai], vehicle_type=v2[0], plate_number=v2[1], capacity=v2[2]))
        driver_seed = [
            ('Victory Transport Co.', ('Manuel dela Cruz', 'N-01-0001', '0917-111-0001')),
            ('Victory Transport Co.', ('Riza Santos', 'N-01-0002', '0917-111-0002')),
            ('Cagayan North Rides', ('Jomar Agbayani', 'N-02-4412', '0918-222-3344')),
            ('DMMMSU Trans', ('Pedro Ramos', 'N-03-9987', '0920-333-4455')),
        ]
        for agency_name, (fname, lic, cn) in driver_seed:
            agency = next(a for a in agencies if a.name == agency_name)
            Driver.objects.create(agency=agency, full_name=fname, license_number=lic, contact_number=cn)
        self.stdout.write(self.style.SUCCESS(f"  Agencies: {len(agencies)} | Vehicles: {len(vehicles)} | Drivers: {Driver.objects.count()}"))

    # --- Landmarks ---
    def _seed_landmarks(self):
        tourist_spots = [
            ('Banaue Rice Terraces', 'Banaue, Ifugao', 250),
            ('Chocolate Hills', 'Carmen, Bohol', 100),
            ('Kayangan Lake', 'Coron, Palawan', 300),
            ('Trekking Mount Pulag', 'Kabayan, Benguet', 500),
            ('White Beach', 'Boracay Island, Aklan', 150),
        ]
        for name, loc, fee in tourist_spots:
            Landmark.objects.create(name=name, category=Landmark.Category.TOURIST_SPOT, municipality=loc, entry_fee=fee)
        landmarks = [
            ('San Sebastian Basilica', 'Quiapo, Manila', 50),
            ('Rizal Monument', 'Luneta Park, Manila', 0),
            ('Baguio Cathedral', 'Baguio City, Benguet', 0),
            ('Ponce Massacre Site', 'Bauang, La Union', 0),
            ('St. Paul Metropolitan Cathedral', 'Vigan City, Ilocos Sur', 0),
        ]
        for name, loc, fee in landmarks:
            Landmark.objects.create(name=name, category=Landmark.Category.LANDMARK, municipality=loc, entry_fee=fee)
        self.stdout.write(self.style.SUCCESS(f"  Tourist spots: {len(tourist_spots)} | Landmarks: {len(landmarks)}"))

    # --- Activities ---
    def _seed_activities(self):
        providers = [
            ('Siargao Adventure Hub', 'General Luna, Siargao', '(086) 800-2211'),
            ('Palawan Underwater', 'Puerto Princesa, Palawan', '(048) 433-7090'),
            ('Baguio Outdoor Co.', 'Baguio City, Benguet', '(074) 444-5566'),
            ('Cagayan Adventure Co.', 'Tuguegarao City, Cagayan', '(078) 844-9988'),
        ]
        provider_objs = []
        for name, loc, contact in providers:
            provider_objs.append(ActivityProvider.objects.create(name=name, location=loc, contact_number=contact))
        activities = [
            (provider_objs[0], 'Island Hopping Tour', 'Full-day tour of Siargao islets', 2500, 25),
            (provider_objs[1], 'Scuba Diving', 'Beginner dive with full gear', 3000, 8),
            (provider_objs[1], 'Underground River Tour', 'Guided tour of the Puerto Princesa river', 1800, 30),
            (provider_objs[2], 'Zipline Adventure', '500m zipline over pine valley', 450, 40),
            (provider_objs[2], 'Mountain Trekking', 'Guided half-day trek', 900, 15),
            (provider_objs[3], 'Caving Expedition', 'Explore Callao and nearby caves', 1500, 12),
            (provider_objs[3], 'ATV Trail Ride', '1-hour ATV ride on dirt trails', 1000, 20),
        ]
        for provider, name, desc, fee, slots in activities:
            Activity.objects.create(provider=provider, name=name, description=desc, fee=fee, slots=slots)
        self.stdout.write(self.style.SUCCESS(f"  Providers: {len(provider_objs)} | Activities: {len(activities)}"))

    # --- Packages ---
    def _seed_packages(self):
        hotels = list(Hotel.objects.all())
        activities = list(Activity.objects.all())
        packages = [
            ('Boracay Escape', '3D2N resort stay with island hopping and airport transfers.', 3, 12999),
            ('Palawan Discovery', 'Puerto Princesa tour with diving and underground river.', 4, 18900),
            ('Manila City Break', '2 nights in Manila with landmark tour.', 2, 8400),
            ('Cagayan Adventure', 'Caving, ATV and river tour in Cagayan Valley.', 3, 9600),
            ('Baguio Highlands', '2 nights with trekking and zipline.', 2, 7900),
        ]
        pkg_objs = []
        for name, desc, dur, price in packages:
            pkg = TourPackage.objects.create(name=name, description=desc, duration_days=dur, price=price)
            if hotels:
                pkg.included_hotels.add(hotels[len(pkg_objs) % len(hotels)])
            if activities:
                pkg.included_activities.add(activities[(len(pkg_objs) * 2) % len(activities)])
            pkg_objs.append(pkg)
        self.stdout.write(self.style.SUCCESS(f"  Packages: {len(pkg_objs)}"))
