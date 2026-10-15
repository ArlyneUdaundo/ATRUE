from django.urls import path

from . import views

app_name = 'resorts'

urlpatterns = [
    path('', views.resort_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('add/', views.add_resort, name='add'),
    path('<int:resort_id>/update/', views.update_resort, name='update_resort'),
    path('<int:resort_id>/delete/', views.delete_resort, name='delete_resort'),
    path('units/', views.units, name='units'),
    path('unit/<int:unit_id>/', views.unit_detail, name='unit_detail'),
    path('<int:resort_id>/unit/add/', views.add_unit, name='add_unit'),
    path('unit/<int:unit_id>/update/', views.update_unit, name='update_unit'),
    path('services/', views.services, name='services'),
    path('service/<int:service_id>/', views.service_detail, name='service_detail'),
    path('<int:resort_id>/service/add/', views.add_service, name='add_service'),
    path('service/<int:service_id>/update/', views.update_service, name='update_service'),
    path('book/group/<int:resort_id>/', views.resort_group_start, name='group_start'),
    path('book/flow/<int:resort_id>/', views.resort_flow_select, name='flow_select'),
    path('book/group/review/', views.resort_group_review, name='group_review'),
    path('book/<int:unit_id>/', views.book_resort, name='book'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('booking/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
    path('<slug:resort_id>/', views.resort_detail, name='detail'),
]
