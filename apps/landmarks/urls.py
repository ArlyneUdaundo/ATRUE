from django.urls import path

from . import views

app_name = 'landmarks'

urlpatterns = [
    path('', views.landmark_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('spot/add/', views.add_spot, name='add_spot'),
    path('spot/<int:spot_id>/update/', views.update_spot, name='update_spot'),
    path('landmark/add/', views.add_landmark, name='add_landmark'),
    path('landmark/<int:landmark_id>/update/', views.update_landmark, name='update_landmark'),
    path('book-spot/<int:spot_id>/', views.book_spot, name='book_spot'),
    path('book-landmark/<int:landmark_id>/', views.book_landmark, name='book_landmark'),
    path('flow/<int:pk>/', views.landmark_flow_select, name='flow_select'),
    path('flow/<int:pk>/detail/', views.landmark_detail, name='detail'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('booking/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
]