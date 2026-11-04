from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notification_list, name='list'),
    path('mark-read/<int:pk>/', views.mark_read, name='mark_read'),
    path('open/<int:pk>/', views.open_notification, name='open'),
    path('travel-request/<int:pk>/', views.travel_request_detail, name='travel_request'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_read'),
    path('api/unread-count/', views.unread_count_json, name='unread_count'),
    path('api/recent/', views.recent_json, name='recent'),
]
