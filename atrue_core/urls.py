from django.conf import settings
from django.contrib import admin
from datetime import date, time

from django.shortcuts import render
from django.urls import include, path, re_path, reverse
from django.views.static import serve

from accounts import views as accounts_views
from atrue_core import views as atrue_views
from atrue_core.destinations import (
    DESTINATIONS,
    destination_detail,
    destination_options,
    destination_search_options,
)


def home(request):
    # Full ATRUE landing page: searchable flights, hotels, resorts, staycations,
    # restaurants, tourist spots, activities and packages. Retains V8 location
    # filtering and the real hotel catalog redirect.
    from activities.models import Activity
    from airlines.models import Flight
    from django.db.models import Min, Q
    from hotels.models import Hotel
    from landmarks.models import Landmark
    from tour_package.models import TourPackage
    from resorts.models import Resort
    from restaurants.models import Restaurant
    from staycations.models import Staycation
    from atrue_core.location_hierarchy import country_province_keys, location_display, location_matches
    from airlines.models import Airport, FARE_CLASS_CHOICES
    from urllib.parse import urlencode
    from django.http import HttpResponseRedirect

    tab = (request.GET.get('tab') or 'all').strip().lower()
    if tab not in {'all', 'flights', 'hotels', 'resorts', 'staycations',
                   'restaurants', 'tours', 'activities', 'landmarks',
                   'landtransportation'}:
        tab = 'all'
    selected_destination = (request.GET.get('destination') or '').strip()
    destination = DESTINATIONS.get(selected_destination)
    q = (request.GET.get('q') or '').strip()
    if destination and not q:
        q = destination['name']
    elif selected_destination and not destination:
        q = q or selected_destination.replace('-', ' ').title()
    if not selected_destination and q:
        selected_destination = next(
            (slug for slug, value in DESTINATIONS.items()
             if value['name'].casefold() == q.casefold()),
            '',
        )
    search_errors = []

    if request.GET.get('search_submit') == '1':
        flight_origin_airport = (request.GET.get('origin_airport') or '').strip()
        flight_destination_airport = (
            request.GET.get('destination_airport') or ''
        ).strip()
        check_in = (request.GET.get('check_in') or '').strip()
        check_out = (request.GET.get('check_out') or '').strip()
        reservation_time = (request.GET.get('reservation_time') or '').strip()
        trip_type = (request.GET.get('trip_type') or 'ONE_WAY').strip()
        fare_class = (request.GET.get('fare_class') or 'ECONOMY').strip()
        adults = (request.GET.get('adults') or '2').strip()
        children = (request.GET.get('children') or '0').strip()
        rooms = (request.GET.get('rooms') or '1').strip()

        def parsed_date(value, label, required=True):
            if not value:
                if required:
                    search_errors.append(f'Select the {label.lower()}.')
                return None
            try:
                return date.fromisoformat(value)
            except ValueError:
                search_errors.append(f'Enter a valid {label.lower()}.')
                return None

        if tab == 'flights':
            # The home page only asks for a destination airport; the departure
            # airport is optional and can be chosen on the flight results page.
            if not flight_destination_airport.isdigit():
                search_errors.append('Select a flying-to airport.')
            elif not Airport.objects.filter(
                pk=flight_destination_airport, status=Airport.Status.ACTIVE
            ).exists():
                search_errors.append('Select a valid flying-to airport.')
            if flight_origin_airport:
                if not flight_origin_airport.isdigit():
                    search_errors.append('Select a flying-from airport.')
                elif not Airport.objects.filter(
                    pk=flight_origin_airport, status=Airport.Status.ACTIVE
                ).exists():
                    search_errors.append('Select a valid flying-from airport.')
            if (
                flight_origin_airport.isdigit()
                and flight_destination_airport.isdigit()
                and int(flight_origin_airport) == int(flight_destination_airport)
            ):
                search_errors.append('Flying-from and flying-to airports must be different.')
            departure = parsed_date(check_in, 'Departure date')
            if departure and departure < date.today():
                search_errors.append('Departure date cannot be in the past.')
            if trip_type not in {'ONE_WAY', 'ROUND_TRIP'}:
                search_errors.append('Choose a valid trip type.')
            if fare_class not in {value for value, _ in FARE_CLASS_CHOICES}:
                search_errors.append('Choose a valid flight class.')
            if trip_type == 'ROUND_TRIP':
                return_date = parsed_date(check_out, 'Return date')
                if departure and return_date and return_date < departure:
                    search_errors.append('Return date cannot be earlier than departure.')
            try:
                passenger_count = int(request.GET.get('guests') or '2')
                if not 1 <= passenger_count <= 9:
                    raise ValueError
            except (TypeError, ValueError):
                passenger_count = 2
                search_errors.append('Passenger count must be between 1 and 9.')
        else:
            if not q:
                search_errors.append('Enter a destination or property to search.')
            start_date = parsed_date(
                check_in,
                'Reservation date' if tab == 'restaurants' else
                'Tour date' if tab == 'tours' else
                'Activity date' if tab == 'activities' else
                'Visit date' if tab == 'landmarks' else
                'Travel date' if tab == 'landtransportation' else 'Check-in date',
                required=tab != 'all',
            )
            end_date = None
            if tab in {'hotels', 'resorts', 'staycations'}:
                end_date = parsed_date(check_out, 'Check-out date')
                if start_date and end_date and end_date <= start_date:
                    search_errors.append('Check-out must be after check-in.')
            if start_date and start_date < date.today():
                search_errors.append('The selected date cannot be in the past.')
            try:
                adult_count = int(adults)
                child_count = int(children)
                if adult_count < 1 or child_count < 0:
                    raise ValueError
            except (TypeError, ValueError):
                adult_count, child_count = 2, 0
                if tab != 'restaurants':
                    search_errors.append('Enter between 1 and 9 guests.')
            if tab == 'restaurants':
                # The restaurant search uses the Guests & Tables selector: a
                # single guest count plus a table count. Adults/children/rooms
                # remain hotel concepts.
                guest_q = (request.GET.get('guests') or '').strip()
                if guest_q.isdigit():
                    guest_count = int(guest_q)
                    if not 1 <= guest_count <= 30:
                        guest_count = max(1, adult_count + child_count)
                        search_errors.append('Enter between 1 and 30 guests.')
                else:
                    guest_count = max(1, adult_count + child_count)
                try:
                    tables_count = int(request.GET.get('tables') or '1')
                    if not 1 <= tables_count <= 20:
                        raise ValueError
                except (TypeError, ValueError):
                    tables_count = 1
                    search_errors.append('Table count must be between 1 and 20.')
                adult_count, child_count = guest_count, 0
                room_count = tables_count
            else:
                if adult_count + child_count > 9:
                    adult_count, child_count = 2, 0
                    search_errors.append('Enter between 1 and 9 guests.')
                try:
                    room_count = int(rooms)
                    if room_count < 1 or room_count > 9:
                        raise ValueError
                except (TypeError, ValueError):
                    room_count = 1
                    if tab in {'hotels', 'resorts'}:
                        search_errors.append('Room count must be between 1 and 9.')
            if tab == 'restaurants':
                if not reservation_time:
                    search_errors.append('Select a reservation time.')
                else:
                    try:
                        time.fromisoformat(reservation_time)
                    except ValueError:
                        search_errors.append('Enter a valid reservation time.')

        if not search_errors:
            params = {}
            if tab == 'flights':
                params = {
                    'search_submit': '1',
                    'destination_airport': flight_destination_airport,
                    'departure_date': check_in,
                    'trip_type': trip_type,
                    'fare_class': fare_class,
                    'passengers': passenger_count,
                }
                if flight_origin_airport:
                    params['origin_airport'] = flight_origin_airport
                if trip_type == 'ROUND_TRIP':
                    params['return_date'] = check_out
                target = 'airlines:list'
            elif tab in {'all', 'tours'}:
                params = {
                    'tab': tab,
                    'q': q,
                    'guests': adult_count + child_count,
                    'adults': adult_count,
                    'children': child_count,
                }
                if check_in:
                    params['check_in'] = check_in
                if check_out:
                    params['check_out'] = check_out
                return HttpResponseRedirect(
                    reverse('home') + '?' + urlencode(params) + '#live'
                )
            else:
                params = {
                    'q': q,
                    'guests': adult_count + child_count,
                    'adults': adult_count,
                    'children': child_count,
                }
                if tab in {'restaurants', 'tours', 'activities', 'landmarks'}:
                    params['date'] = check_in
                if check_in:
                    params['check_in'] = check_in
                if check_out:
                    params['check_out'] = check_out
                if tab in {'hotels', 'resorts'}:
                    params['rooms'] = room_count
                if tab == 'restaurants':
                    params['tables'] = room_count
                if tab == 'restaurants':
                    params['time'] = reservation_time
                    target = 'restaurants:list'
                elif tab == 'hotels':
                    target = 'hotels:list'
                elif tab == 'resorts':
                    target = 'resorts:list'
                elif tab == 'staycations':
                    target = 'staycations:list'
                elif tab == 'activities':
                    target = 'activities:list'
                elif tab == 'landmarks':
                    target = 'landmarks:list'
                elif tab == 'landtransportation':
                    params['schedule'] = check_in + 'T09:00'
                    target = 'transportation:list'
                else:
                    target = 'tour_package:list'
            return HttpResponseRedirect(
                reverse(target) + '?' + urlencode(params)
            )

    loc_country = (request.GET.get('loc_country') or '').strip()
    loc_province = (request.GET.get('loc_province') or '').strip()
    loc_municipality = (request.GET.get('loc_municipality') or '').strip()
    loc_barangay = (request.GET.get('loc_barangay') or '').strip()

    flights_qs = Flight.objects.select_related('airline', 'aircraft').exclude(status__in=['CANCELLED','COMPLETED'])
    hotels_qs = Hotel.objects.filter(status='ACTIVE').prefetch_related('photos','rooms').annotate(from_rate=Min('rooms__rate'))
    resorts_qs = Resort.objects.filter(status='ACTIVE').annotate(from_rate=Min('units__rate'))
    staycations_qs = Staycation.objects.filter(status='ACTIVE')
    restaurants_qs = Restaurant.objects.filter(status='ACTIVE')
    spots_qs = Landmark.objects.filter(status='ACTIVE', category='TOURIST_SPOT').prefetch_related('photos')
    activities_qs = Activity.objects.select_related('provider').filter(status='ACTIVE', provider__status='ACTIVE', provider__verified=True)
    packages_qs = TourPackage.objects.filter(status='ACTIVE')

    if q:
        flights_qs = flights_qs.filter(Q(origin__icontains=q) | Q(destination__icontains=q)
                                       | Q(origin_country__icontains=q) | Q(origin_province__icontains=q)
                                       | Q(origin_municipality__icontains=q) | Q(destination_country__icontains=q)
                                       | Q(destination_province__icontains=q) | Q(destination_municipality__icontains=q))
        hotels_qs = hotels_qs.filter(Q(name__icontains=q) | Q(province__icontains=q) | Q(municipality__icontains=q) | Q(barangay__icontains=q))
        resorts_qs = resorts_qs.filter(Q(name__icontains=q) | Q(province__icontains=q) | Q(municipality__icontains=q) | Q(barangay__icontains=q))
        staycations_qs = staycations_qs.filter(Q(name__icontains=q) | Q(province__icontains=q) | Q(municipality__icontains=q) | Q(barangay__icontains=q))
        restaurants_qs = restaurants_qs.filter(Q(name__icontains=q) | Q(location__icontains=q) | Q(cuisine_type__icontains=q))
        spots_qs = spots_qs.filter(Q(name__icontains=q) | Q(province__icontains=q) | Q(municipality__icontains=q) | Q(description__icontains=q))
        activities_qs = activities_qs.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
            | Q(location__icontains=q) | Q(location_province__icontains=q)
            | Q(location_municipality__icontains=q)
            | Q(location_barangay__icontains=q)
            | Q(provider__name__icontains=q)
        )
        packages_qs = packages_qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(destination_name__icontains=q) | Q(destination_city__icontains=q) | Q(destination_province__icontains=q))

    if loc_country or loc_province or loc_municipality or loc_barangay:
        # Resolved once, not per item: listings store no country, so a
        # country-only selection is matched through the country's provinces.
        country_keys = country_province_keys(loc_country) if loc_country else None
        def match(item, p='province', m='municipality', b='barangay'):
            return location_matches({'province':[getattr(item,p,'') or ''], 'municipality':[getattr(item,m,'') or ''], 'barangay':[getattr(item,b,'') or ''], 'loc_text':''}, loc_province, loc_municipality, loc_barangay, '', country=loc_country, country_provinces=country_keys)
        hotels_qs=[x for x in hotels_qs if match(x)]
        resorts_qs=[x for x in resorts_qs if match(x)]
        staycations_qs=[x for x in staycations_qs if match(x)]
        spots_qs=[x for x in spots_qs if match(x)]
        activities_qs=[x for x in activities_qs if match(x,'location_province','location_municipality','location_barangay')]
        packages_qs=[x for x in packages_qs if location_matches({'province':[x.destination_province or ''],'municipality':[x.destination_city or ''],'barangay':[],'loc_text':''},loc_province,loc_municipality,loc_barangay,'',country=loc_country,country_provinces=country_keys)]
        # A flight touches a place if either endpoint is there.
        def flight_match(f):
            origin_ok = location_matches(
                {'province': [f.origin_province or ''], 'municipality': [f.origin_municipality or ''],
                 'barangay': [], 'loc_text': ''},
                loc_province, loc_municipality, loc_barangay, '',
                country=loc_country, country_provinces=country_keys)
            dest_ok = location_matches(
                {'province': [f.destination_province or ''], 'municipality': [f.destination_municipality or ''],
                 'barangay': [], 'loc_text': ''},
                loc_province, loc_municipality, loc_barangay, '',
                country=loc_country, country_provinces=country_keys)
            return origin_ok or dest_ok
        flights_qs = [x for x in flights_qs if flight_match(x)]
        # Restaurants keep a single free-text location, so the selection is
        # matched against that blob instead of separate columns. Going through
        # location_matches (rather than substring tests) is what makes the
        # barangay level work here too, and keeps the home page consistent with
        # the catalogue search.
        restaurants_qs=[x for x in restaurants_qs if location_matches({}, loc_province, loc_municipality, loc_barangay, x.location or '', country=loc_country)]

    groups={
        'flights':['flights'],'hotels':['hotels'],'resorts':['resorts'],'staycations':['staycations'],
        'restaurants':['restaurants'],'landmarks':['spots'],'activities':['activities'],'landtransportation':[],'packages':['packages'],
        'tours':['packages','activities','spots'],
        'all':['flights','hotels','resorts','staycations','restaurants','spots','activities','packages'],
    }
    show=groups.get(tab,groups['all'])
    active=bool(q or loc_country or loc_province or loc_municipality or loc_barangay)
    featured=lambda qs: qs if active else qs[:3]
    shown={'flights':flights_qs,'hotels':hotels_qs,'resorts':resorts_qs,'staycations':staycations_qs,'restaurants':restaurants_qs,'spots':spots_qs,'activities':activities_qs,'packages':packages_qs}
    def count(x): return x.count() if hasattr(x,'count') and not isinstance(x,list) else len(x)

    home_destinations = destination_options()
    hero_images = []
    hero_spots = Landmark.objects.filter(
        status='ACTIVE', category='TOURIST_SPOT'
    ).prefetch_related('photos').order_by('name')
    for hero_spot in hero_spots:
        hero_photo = hero_spot.photos.first()
        if hero_photo and hero_photo.image:
            hero_images.append({'url': hero_photo.image.url, 'name': hero_spot.name})
        if len(hero_images) >= 4:
            break
    return render(request,'home.html',{
        'featured_flights':featured(flights_qs), 'featured_hotels':featured(hotels_qs),
        'featured_resorts':featured(resorts_qs), 'featured_staycations':featured(staycations_qs),
        'featured_restaurants':featured(restaurants_qs), 'featured_spots':featured(spots_qs),
        'featured_activities':featured(activities_qs), 'featured_packages':featured(packages_qs),
        'search_active':active,'search_query':q,'search_tab':tab,
        'search_reservation_time':request.GET.get('reservation_time',''),
        'search_errors':search_errors,
        'selected_destination':selected_destination,
        'search_today':date.today().isoformat(),
        'loc_country':loc_country,'loc_province':loc_province,'loc_municipality':loc_municipality,'loc_barangay':loc_barangay,
        'loc_display':location_display(loc_province,loc_municipality,loc_barangay,loc_country),
        'search_count':sum(count(shown[k]) for k in show),
        'search_check_in':request.GET.get('check_in',''),'search_check_out':request.GET.get('check_out',''),'search_guests':request.GET.get('guests','2'),
        'search_trip_type':request.GET.get('trip_type','ONE_WAY'),
        'search_flight_class':request.GET.get(
            'fare_class', request.GET.get('class', 'ECONOMY')),
        'flight_class_choices':FARE_CLASS_CHOICES,
        'airports_api_url':reverse('airlines:airports_api'),
        'search_flight_origin_airport': (
            Airport.objects.filter(
                pk=request.GET.get('origin_airport')
            ).first()
            if (request.GET.get('origin_airport') or '').isdigit()
            else None
        ),
        'search_flight_airport': (
            Airport.objects.filter(
                pk=request.GET.get('destination_airport')
            ).first()
            if (request.GET.get('destination_airport') or '').isdigit()
            else None
        ),
        'hero_images': hero_images,
        'destination_options': home_destinations,
        'destination_search_options': destination_search_options(home_destinations, properties_only=True),
        'search_rooms':request.GET.get('rooms','1'),'search_adults':request.GET.get('adults',request.GET.get('guests','2')),'search_children':request.GET.get('children','0'),
        'search_tables':request.GET.get('tables','1'),
        'show_flights':'flights' in show,'show_hotels':'hotels' in show,'show_resorts':'resorts' in show,
        'show_staycations':'staycations' in show,'show_restaurants':'restaurants' in show,'show_spots':'spots' in show,
        'show_activities':'activities' in show,'show_packages':'packages' in show,
    })

urlpatterns=[
    path('',home,name='home'),
    path('destinations/<slug:slug>/',destination_detail,name='destination_detail'),
    path('locations/api/',atrue_views.location_api,name='location_api'),
    path('locations/api/search/',atrue_views.location_search_api,name='location_search_api'),
    path('locations/api/barangays/',atrue_views.location_barangays_api,name='location_barangays_api'),
    path('dashboard/',accounts_views.dashboard,name='dashboard'),
    path('admin/',admin.site.urls),
    path('accounts/',include('accounts.urls')), path('flights/',include('airlines.urls')), path('simulation/',include('simulation.urls')),
    path('hotels/',include('hotels.urls')), path('resorts/',include('resorts.urls')), path('staycations/',include('staycations.urls')),
    path('restaurants/',include('restaurants.urls')), path('transportation/',include('transportation.urls')), path('landmarks/',include('landmarks.urls')),
    path('activities/',include('activities.urls')), path('packages/',include('tour_package.urls')), path('transactions/',include('transactions.urls')),
]
if settings.SERVE_MEDIA_FILES:
    # django.conf.urls.static.static() intentionally returns no route when
    # DEBUG=False, so use the serving view directly for Render's public media.
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
