from django.urls import path

from . import views

app_name = 'hotels'

urlpatterns = [
    path('', views.hotel_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('add/', views.add_hotel, name='add'),
    path('<int:hotel_id>/update/', views.update_hotel, name='update_hotel'),
    path('<int:hotel_id>/delete/', views.delete_hotel, name='delete_hotel'),
    path('<int:hotel_id>/rooms/add/', views.add_room, name='add_room'),
    path('rooms/', views.rooms, name='rooms'),
    path('rooms/<int:room_id>/', views.room_detail, name='room_detail'),
    path('rooms/<int:room_id>/update/', views.update_room, name='update_room'),
    path('rooms/<int:room_id>/delete/', views.delete_room, name='delete_room'),
    path('<int:hotel_id>/services/add/', views.add_service, name='add_service'),
    path('services/', views.services, name='services'),
    path('services/<int:service_id>/', views.service_detail, name='service_detail'),
    path('services/<int:service_id>/update/', views.update_service, name='update_service'),
    path('services/<int:service_id>/delete/', views.delete_service, name='delete_service'),
    path('<int:hotel_id>/amenities/add/', views.add_amenity, name='add_amenity'),
    path('amenities/', views.amenities, name='amenities'),
    path('amenities/<int:amenity_id>/', views.amenity_detail, name='amenity_detail'),
    path('amenities/<int:amenity_id>/update/', views.update_amenity, name='update_amenity'),
    path('amenities/<int:amenity_id>/delete/', views.delete_amenity, name='delete_amenity'),
    path('book/group/<int:hotel_id>/', views.hotel_group_start, name='group_start'),
    path('book/group/<int:hotel_id>/select/', views.hotel_group_select_rooms, name='group_select_rooms'),
    path('book/group/guests/', views.hotel_group_guests, name='group_guests'),
    path('book/group/review/', views.hotel_group_review, name='group_review'),
    path('book/group/payment/', views.hotel_group_payment, name='group_payment'),
    path('book/<int:room_id>/', views.book_hotel, name='book'),
    path('bookings/', views.bookings, name='bookings'),
    path('bookings/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('bookings/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('bookings/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
    path('<slug:hotel_id>/', views.hotel_detail, name='detail'),
]