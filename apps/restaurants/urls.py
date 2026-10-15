from django.urls import path

from . import views

app_name = 'restaurants'

urlpatterns = [
    path('', views.restaurant_list, name='list'),
    path('tables/', views.tables, name='tables'),
    path('table/<int:table_id>/', views.table_detail, name='table_detail'),
    path('manage/', views.manage, name='manage'),
    path('add/', views.add_restaurant, name='add'),
    path('<int:restaurant_id>/update/', views.update_restaurant, name='update_restaurant'),
    path('<int:restaurant_id>/delete/', views.delete_restaurant, name='delete_restaurant'),
    path('<int:restaurant_id>/table/add/', views.add_table, name='add_table'),
    path('table/<int:table_id>/update/', views.update_table, name='update_table'),
    path('book/<int:table_id>/', views.book_restaurant, name='book'),
    path('book/flow/<int:restaurant_id>/', views.restaurant_flow_select, name='flow_select'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('booking/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
    path('<slug:restaurant_id>/', views.restaurant_detail, name='detail'),
]
