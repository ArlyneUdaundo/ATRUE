from django.urls import path

from . import views

app_name = 'records'

urlpatterns = [
    path('', views.record_list, name='list'),
]