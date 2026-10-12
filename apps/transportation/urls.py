from django.urls import path

from . import views

app_name = 'transportation'

urlpatterns = [
    path('', views.transportation_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('add/', views.add_agency, name='add_agency'),
    path('agency/<int:agency_id>/', views.agency_vehicles, name='agency_vehicles'),
    path('<int:agency_id>/update/', views.update_agency, name='update_agency'),
    path('<int:agency_id>/vehicle/add/', views.add_vehicle, name='add_vehicle'),
    path('vehicle/<int:vehicle_id>/update/', views.update_vehicle, name='update_vehicle'),
    path('<int:agency_id>/driver/add/', views.add_driver, name='add_driver'),
    path('driver/<int:driver_id>/update/', views.update_driver, name='update_driver'),
    path('book/<int:vehicle_id>/', views.book_vehicle, name='book'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('booking/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
]