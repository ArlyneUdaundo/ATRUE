from django.contrib import admin

from .models import Reservation, Restaurant, RestaurantPhoto, Table


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'cuisine_type', 'status')
    list_filter = ('status', 'cuisine_type')


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ('restaurant', 'table_number', 'capacity', 'status')
    list_filter = ('restaurant', 'status')


@admin.register(RestaurantPhoto)
class RestaurantPhotoAdmin(admin.ModelAdmin):
    list_display = ('restaurant', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer', 'table', 'reservation_datetime',
                    'number_of_guests', 'status', 'created_at')
    list_filter = ('status',)
    date_hierarchy = 'reservation_datetime'