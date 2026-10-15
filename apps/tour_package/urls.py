from django.urls import path

from . import views

app_name = 'tour_package'

urlpatterns = [
    path('', views.package_list, name='list'),
    path('manage/', views.manage, name='manage'),
    path('operate/', views.operate, name='operate'),
    path('add/', views.add_package, name='add_package'),
    path('<int:package_id>/update/', views.update_package, name='update_package'),
    path('<int:package_id>/delete/', views.delete_package, name='delete_package'),
    path('book/<int:package_id>/', views.book_package, name='book_package'),
    path('book/flow/<int:package_id>/', views.package_flow_select, name='flow_select'),
    path('bookings/', views.bookings, name='bookings'),
    path('booking/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:booking_id>/ticket/', views.ticket_detail, name='ticket'),
    path('booking/<int:booking_id>/ticket/pdf/', views.ticket_pdf, name='ticket_pdf'),
    path('<slug:package_id>/', views.package_detail, name='detail'),
]
