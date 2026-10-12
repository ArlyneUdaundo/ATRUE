from django.urls import path

from . import views

app_name = 'activities'

urlpatterns = [
    path('', views.activity_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('operate/', views.operate, name='operate'),
    path('add/', views.add_activity, name='add_activity'),
    path('<int:activity_id>/update/', views.update_activity, name='update_activity'),
    path('book/<int:activity_id>/', views.book_activity, name='book_activity'),
    path('flow/<int:pk>/', views.activity_flow_select, name='flow_select'),
    path('flow/<int:pk>/detail/', views.activity_detail, name='detail'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('booking/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
]
