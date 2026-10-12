from django.urls import path

from . import views

app_name = 'airlines'

urlpatterns = [
    path('', views.flight_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('airline/<int:airline_id>/', views.airline_detail, name='airline_detail'),
    path('<int:airline_id>/update/', views.update_airline, name='update_airline'),
    path('aircrafts/', views.aircrafts, name='aircrafts'),
    path('aircraft/<int:aircraft_id>/', views.aircraft_detail, name='aircraft_detail'),
    path('<int:airline_id>/fleet/', views.airline_fleet, name='airline_fleet'),
    path('api/fleet/<int:airline_id>/', views.fleet_api, name='fleet_api'),
    path('<int:airline_id>/aircraft/add/', views.add_aircraft, name='add_aircraft'),
    path('aircraft/<int:aircraft_id>/update/', views.update_aircraft, name='update_aircraft'),
    path('services/', views.services, name='services'),
    path('service/<int:service_id>/', views.service_detail, name='service_detail'),
    path('<int:airline_id>/service/add/', views.add_service, name='add_service'),
    path('service/<int:service_id>/update/', views.update_service, name='update_service'),
    path('flights/', views.flights, name='flights'),
    path('api/airports/', views.airports_api, name='airports_api'),
    path('flights/add/', views.add_flight, name='add_flight_schedule'),
    path('<int:airline_id>/flight/add/', views.add_flight, name='add_flight'),
    path('flight/<int:flight_id>/update/', views.update_flight, name='update_flight'),
    path('book/<int:flight_id>/', views.book_flight, name='book'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('ticket/<int:booking_id>/', views.ticket_detail, name='ticket'),
    path('ticket/<int:booking_id>/pdf/', views.ticket_pdf, name='ticket_pdf'),
    # Itinerary routes come before the flight slug catch-all, which would
    # otherwise swallow "itinerary/<id>".
    path('itinerary/<int:itinerary_id>/', views.itinerary_public_detail,
         name='itinerary_public_detail'),
    path('manage/itinerary/<int:itinerary_id>/', views.itinerary_detail,
         name='itinerary_detail'),
    path('manage/itinerary/<int:itinerary_id>/update/', views.update_itinerary,
         name='update_itinerary'),
    path('itinerary/<int:itinerary_id>/book/', views.book_itinerary,
         name='book_itinerary'),
    path('<slug:flight_id>/', views.flight_detail, name='flight_detail'),
]
