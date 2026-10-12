from django.contrib import admin

from .models import BlockOutDate, Reservation, Service, Staycation, StaycationPhoto


@admin.register(Staycation)
class StaycationAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'capacity', 'rate', 'status')
    list_filter = ('status',)


@admin.register(BlockOutDate)
class BlockOutDateAdmin(admin.ModelAdmin):
    list_display = ('staycation', 'start_date', 'end_date')
    list_filter = ('staycation',)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('staycation', 'name', 'rate', 'status')
    list_filter = ('staycation', 'status')


@admin.register(StaycationPhoto)
class StaycationPhotoAdmin(admin.ModelAdmin):
    list_display = ('staycation', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer', 'staycation', 'check_in', 'check_out',
                    'number_of_guests', 'status', 'created_at')
    list_filter = ('status',)
    date_hierarchy = 'check_in'