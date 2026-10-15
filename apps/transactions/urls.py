from django.urls import path

from . import views

app_name = 'transactions'

urlpatterns = [
    path('payment-review/', views.payment_review, name='payment_review'),
    path('', views.transaction_list, name='list'),
    path('admin/', views.admin_list, name='admin_list'),
    path('bills/<int:bill_id>/', views.bill_detail, name='bill_detail'),
    path('receipts/<int:receipt_id>/', views.receipt_detail, name='receipt_detail'),
    path('additional/', views.additional_list, name='additional_list'),
    path('additional/add/', views.additional_add, name='additional_add'),
    path('bookings/', views.booking_list, name='booking_list'),
    path('cart/', views.trip_cart, name='cart'),
    path('cart/remove/', views.trip_cart_remove, name='cart_remove'),
    path('cart/clear/', views.trip_cart_clear, name='cart_clear'),
    path('cart/checkout/', views.trip_cart_checkout, name='cart_checkout'),
    path('establishment/', views.establishment_booking, name='establishment_booking'),
    path('establishment/clear/', views.establishment_booking_clear, name='establishment_booking_clear'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
]
