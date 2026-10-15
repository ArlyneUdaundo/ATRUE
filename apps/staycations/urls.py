from django.urls import path

from . import views

app_name = 'staycations'

urlpatterns = [
    path('', views.staycation_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('add/', views.add_staycation, name='add'),
    path('<int:staycation_id>/update/', views.update_staycation, name='update_staycation'),
    path('<int:staycation_id>/delete/', views.delete_staycation, name='delete'),
    path('<int:staycation_id>/service/add/', views.add_service, name='add_service'),
    path('services/', views.services, name='services'),
    path('services/<int:service_id>/', views.service_detail, name='service_detail'),
    path('service/<int:service_id>/update/', views.update_service, name='update_service'),
    path('<int:staycation_id>/block/add/', views.add_block_date, name='add_block'),
    path('block/<int:block_id>/remove/', views.remove_block_date, name='remove_block'),
    path('book/<int:staycation_id>/', views.book_staycation, name='book'),
    path('book/flow/<int:staycation_id>/', views.staycation_flow_select, name='flow_select'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('booking/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
    path('<slug:staycation_id>/', views.staycation_detail, name='detail'),
]
