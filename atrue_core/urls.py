from django.conf import settings
from django.contrib import admin
from datetime import date, time
import threading
import time as monotonic_time

from django.shortcuts import render
from django.urls import include, path, re_path, reverse
from django.views.static import serve

from accounts import views as accounts_views
from atrue_core import views as atrue_views
from atrue_core import dashboard_views
from atrue_core.destinations import (
    DESTINATIONS,
    destination_detail,
    destination_options,
    destination_search_options,
)


_HOME_COUNT_LOCK = threading.Lock()
_HOME_COUNT_CACHE = {}


def _cached_home_search_count(key, querysets):
    """Avoid repeating the same multi-catalog COUNT queries during a traffic burst."""
    now = monotonic_time.monotonic()
    with _HOME_COUNT_LOCK:
        cached = _HOME_COUNT_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
        total = sum(
            queryset.count()
            if hasattr(queryset, 'count') and not isinstance(queryset, list)
            else len(queryset)
            for queryset in querysets
        )
        if len(_HOME_COUNT_CACHE) >= 128:
            _HOME_COUNT_CACHE.clear()
        _HOME_COUNT_CACHE[key] = (now + 20, total)
        return total


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
        flight_destination_airport = (request.GET.get('destination_airport') or '').strip()
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
            if not check_in:
                search_errors.append('Select a departure date.')
            else:
                dep = parsed_date(check_in, 'Departure date')
                if dep:
                    if trip_type == 'ROUND_TRIP':
                        if not check_out:
                            search_errors.append('Select a return date.')
                        else:
                            ret = parsed_date(check_out, 'Return date')
                            if ret and ret < dep:
                                search_errors.append('The return date cannot be earlier than the departure date.')
                    elif trip_type == 'ONE_WAY' and dep < date.today():
                        search_errors.append('The departure date cannot be in the past.')
            if not adults.isdigit() or int(adults) < 1:
                search_errors.append('Select the number of adults.')
            if not children.isdigit() or int(children) < 0:
                search_errors.append('Select the number of children.')
            if not fare_class:
                fare_class = 'ECONOMY'
        else:
            if not check_in:
                search_errors.append('Select a check-in date.')
            else:
                ci = parsed_date(check_in, 'Check-in date')
                if ci and ci < date.today():
                    search_errors.append('The check-in date cannot be in the past.')
            if not adults.isdigit() or int(adults) < 1:
                search_errors.append('Select the number of guests.')
            if not rooms.isdigit() or int(rooms) < 1:
                search_errors.append('Select the number of rooms.')
            if tab in {'hotels', 'resorts', 'staycations'}:
                if not check_out:
                    search_errors.append('Select a check-out date.')
                else:
                    co = parsed_date(check_out, 'Check-out date')
                    if co and 'ci' in locals() and co <= ci:
                        search_errors.append('The check-out date must be after the check-in date.')
            elif tab == 'landtransportation':
                if not reservation_time:
                    search_errors.append('Select a travel time.')
                else:
                    try:
                        time.fromisoformat(reservation_time)
                    except ValueError:
                        search_errors.append('Enter a valid travel time.')
            elif tab == 'restaurants':
                if not reservation_time:
                    search_errors.append('Select a reservation time.')
                else:
                    try:
                        time.fromisoformat(reservation_time)
                    except ValueError:
                        search_errors.append('Enter a valid reservation time.')

        if not search_errors:
            params = {'search_submit': '1', 'tab': tab, 'destination': selected_destination}
            if q:
                params['q'] = q
            if flight_origin_airport:
                params['origin_airport'] = flight_origin_airport
            if flight_destination_airport:
                params['destination_airport'] = flight_destination_airport
            if check_in:
                params['check_in'] = check_in
            if check_out:
                params['check_out'] = check_out
            if reservation_time:
                params['reservation_time'] = reservation_time
            if trip_type:
                params['trip_type'] = trip_type
            if fare_class:
                params['fare_class'] = fare_class
            if adults:
                params['adults'] = adults
            if children:
                params['children'] = children
            if rooms:
                params['rooms'] = rooms
            if tab == 'flights':
                return HttpResponseRedirect(f"{reverse('airlines:search_results')}?{urlencode(params)}")
            if tab == 'hotels':
                return HttpResponseRedirect(f"{reverse('hotels:list')}?{urlencode(params)}")
            if tab == 'resorts':
                return HttpResponseRedirect(f"{reverse('resorts:list')}?{urlencode(params)}")
            if tab == 'staycations':
                return HttpResponseRedirect(f"{reverse('staycations:list')}?{urlencode(params)}")
            if tab == 'restaurants':
                return HttpResponseRedirect(f"{reverse('restaurants:list')}?{urlencode(params)}")
            if tab == 'landmarks':
                return HttpResponseRedirect(f"{reverse('landmarks:list')}?{urlencode(params)}")
            if tab == 'activities':
                return HttpResponseRedirect(f"{reverse('activities:list')}?{urlencode(params)}")
            if tab == 'tours':
                return HttpResponseRedirect(f"{reverse('tour_package:list')}?{urlencode(params)}")
            if tab == 'landtransportation':
                return HttpResponseRedirect(f"{reverse('transportation:list')}?{urlencode(params)}")

    # Build featured listings
    def limit_qs(qs, n=6):
        try:
            return list(qs[:n])
        except Exception:
            return list(qs)

    hero_images = []
    for source in (
        Resort.objects.filter(status='ACTIVE').prefetch_related('photos').order_by('name'),
        Staycation.objects.filter(status='ACTIVE').prefetch_related('photos').order_by('name'),
    ):
        for establishment in source:
            photo = next((item for item in establishment.photos.all() if item.is_primary), None)
            photo = photo or next(iter(establishment.photos.all()), None)
            if photo and photo.image:
                try:
                    if photo.image.storage.exists(photo.image.name):
                        hero_images.append({
                            'url': photo.image.url,
                            'name': establishment.name,
                        })
                except (OSError, ValueError, NotImplementedError):
                    continue
            if len(hero_images) >= 4:
                break
        if len(hero_images) >= 4:
            break

    show = {'all','flights','hotels','resorts','staycations','restaurants','landmarks','activities','tours','landtransportation'}
    if tab != 'all':
        show = {tab}

    hotels_qs = Hotel.objects.filter(status='ACTIVE').order_by('-id') if hasattr(Hotel, 'objects') else []
    resorts_qs = Resort.objects.filter(status='ACTIVE').order_by('-id') if hasattr(Resort, 'objects') else []
    stay_qs = Staycation.objects.filter(status='ACTIVE').order_by('-id') if hasattr(Staycation, 'objects') else []
    rest_qs = Restaurant.objects.filter(status='ACTIVE').order_by('-id') if hasattr(Restaurant, 'objects') else []
    lm_qs = Landmark.objects.filter(status='ACTIVE').order_by('-id') if hasattr(Landmark, 'objects') else []
    act_qs = Activity.objects.filter(status='ACTIVE').order_by('-id') if hasattr(Activity, 'objects') else []
    pkg_qs = TourPackage.objects.filter(status='ACTIVE').order_by('-id') if hasattr(TourPackage, 'objects') else []
    flights_qs = Flight.objects.all().order_by('-id') if hasattr(Flight, 'objects') else []

    country = (request.GET.get('country') or request.COOKIES.get('atrue_loc_country') or '').strip()
    province = (request.GET.get('province') or request.COOKIES.get('atrue_loc_province') or '').strip()
    municipality = (request.GET.get('municipality') or request.COOKIES.get('atrue_loc_municipality') or '').strip()
    barangay = (request.GET.get('barangay') or request.COOKIES.get('atrue_loc_barangay') or '').strip()
    loc_country, loc_province = country, province
    loc_municipality, loc_barangay = municipality, barangay
    country_keys = country_province_keys(country) if country else None
    if q:
        from atrue_core.search_catalog import _item_loc

        def match_text(category_key, obj):
            loc = _item_loc(category_key, obj)
            return location_matches(
                loc, loc_province, loc_municipality, loc_barangay,
                loc_text=loc.get("loc_text"),
                country=loc_country, country_provinces=country_keys,
            )

        try:
            hotels_qs = [h for h in hotels_qs if match_text("hotel", h)]
        except Exception:
            pass

    def apply_loc(qs):
        try:
            return qs.filter(location__icontains=q) if q and hasattr(qs, 'filter') else qs
        except Exception:
            try:
                return [x for x in qs if q.lower() in (getattr(x,'location','') or '').lower()]
            except Exception:
                return qs

    hotels_qs = apply_loc(hotels_qs)
    resorts_qs = apply_loc(resorts_qs)
    stay_qs = apply_loc(stay_qs)
    rest_qs = apply_loc(rest_qs)
    lm_qs = apply_loc(lm_qs)
    act_qs = apply_loc(act_qs)
    pkg_qs = apply_loc(pkg_qs)

    home_destinations = destination_options()[:12]
    shown = {
        'flights': limit_qs(flights_qs, 6),
        'hotels': limit_qs(hotels_qs, 6),
        'resorts': limit_qs(resorts_qs, 6),
        'staycations': limit_qs(stay_qs, 6),
        'restaurants': limit_qs(rest_qs, 6),
        'landmarks': limit_qs(lm_qs, 6),
        'activities': limit_qs(act_qs, 6),
        'packages': limit_qs(pkg_qs, 6),
        'landtransportation': [],
    }
    if 'flights' in show:
        try:
            shown['flights'] = list(Flight.objects.all().select_related('airline').annotate(min_price=Min('itineraries__price')).order_by('-id')[:6])
        except Exception:
            shown['flights'] = limit_qs(flights_qs, 6)

    return render(request, 'home.html', {
        'active_tab': tab,
        'search_q': q,
        'search_errors': search_errors,
        'hotels': shown['hotels'],
        'resorts': shown['resorts'],
        'staycations': shown['staycations'],
        'restaurants': shown['restaurants'],
        'landmarks': shown['landmarks'],
        'activities': shown['activities'],
        'packages': shown['packages'],
        'flights': shown['flights'],
        'show': show,
        'selected_destination':selected_destination,
        'search_today':date.today().isoformat(),
        'loc_country':loc_country,'loc_province':loc_province,'loc_municipality':loc_municipality,'loc_barangay':loc_barangay,
        'loc_display':location_display(loc_province,loc_municipality,loc_barangay,loc_country),
        'search_count':_cached_home_search_count(
            (tuple(show), q.casefold(), loc_country.casefold(),
             loc_province.casefold(), loc_municipality.casefold(),
             loc_barangay.casefold()),
            [
                source for key, source in (
                    ('flights', flights_qs),
                    ('hotels', hotels_qs),
                    ('resorts', resorts_qs),
                    ('staycations', stay_qs),
                    ('restaurants', rest_qs),
                    ('landmarks', lm_qs),
                    ('activities', act_qs),
                    ('packages', pkg_qs),
                )
                if key in show or 'all' in show or (key == 'packages' and 'tours' in show)
            ],
        ),
        'search_check_in':request.GET.get('check_in',''),'search_check_out':request.GET.get('check_out',''),'search_guests':request.GET.get('guests','2'),
        'search_trip_type':request.GET.get('trip_type','ONE_WAY'),
        'search_flight_class':request.GET.get('fare_class', request.GET.get('class', 'ECONOMY')),
        'flight_class_choices':FARE_CLASS_CHOICES,
        'airports_api_url':reverse('airlines:airports_api'),
        'search_flight_origin_airport': (
            Airport.objects.filter(pk=request.GET.get('origin_airport')).first()
            if (request.GET.get('origin_airport') or '').isdigit() else None
        ),
        'search_flight_airport': (
            Airport.objects.filter(pk=request.GET.get('destination_airport')).first()
            if (request.GET.get('destination_airport') or '').isdigit() else None
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


urlpatterns = [
    path('', home, name='home'),
    path('destinations/<slug:slug>/', destination_detail, name='destination_detail'),
    path('locations/api/', atrue_views.location_api, name='location_api'),
    path('locations/api/search/', atrue_views.location_search_api, name='location_search_api'),
    path('locations/api/barangays/', atrue_views.location_barangays_api, name='location_barangays_api'),
    path('dashboard/', accounts_views.dashboard, name='dashboard'),
    path('admin/', admin.site.urls),
    path('accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),
    path('flights/', include(('airlines.urls', 'airlines'), namespace='airlines')),
    path('simulation/', include(('simulation.urls', 'simulation'), namespace='simulation')),
    path('notifications/', include(('notifications.urls', 'notifications'), namespace='notifications')),
    path('hotels/', include(('hotels.urls', 'hotels'), namespace='hotels')),
    path('resorts/', include(('resorts.urls', 'resorts'), namespace='resorts')),
    path('staycations/', include(('staycations.urls', 'staycations'), namespace='staycations')),
    path('restaurants/', include(('restaurants.urls', 'restaurants'), namespace='restaurants')),
    path('transportation/', include(('transportation.urls', 'transportation'), namespace='transportation')),
    path('landmarks/', include(('landmarks.urls', 'landmarks'), namespace='landmarks')),
    path('activities/', include(('activities.urls', 'activities'), namespace='activities')),
    path('packages/', include(('tour_package.urls', 'tour_package'), namespace='tour_package')),
    path('transactions/', include(('transactions.urls', 'transactions'), namespace='transactions')),
]
try:
    from django.urls import include
    urlpatterns.append(path('establishments/', include(('establishments.urls', 'establishments'), namespace='establishments')))
except Exception:
    pass
if settings.SERVE_MEDIA_FILES:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
