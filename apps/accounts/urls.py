from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password/<int:user_id>/', views.reset_password_view, name='reset_password'),
    path('csrf/', views.csrf_token_view, name='csrf_token'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('create/', views.account_create, name='account_create'),
    path('accounts/', views.account_list, name='account_list'),
    path('my-account/', views.my_account, name='my_account'),
    path('accounts/<int:pk>/', views.account_detail, name='account_detail'),
    path('accounts/<int:pk>/update/', views.account_update, name='account_update'),
    path('accounts/<int:pk>/deactivate/', views.account_deactivate, name='account_deactivate'),
    path('accounts/<int:pk>/delete/', views.account_delete, name='account_delete'),
    path('accounts/<int:pk>/deactivate-confirm/', views.account_deactivate_confirm, name='account_deactivate_confirm'),
    path('accounts/<int:pk>/photo/remove/', views.account_photo_remove, name='account_photo_remove'),
    path('accounts/<int:pk>/password/', views.account_change_password, name='account_change_password'),
    path('change-password/', views.change_password, name='change_password'),
    path('dashboard-stats/<str:kind>/', views.stats_list, name='stats_list'),
]
