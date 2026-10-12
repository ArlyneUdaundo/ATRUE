from django.contrib import admin

from .models import Landmark, LandmarkPhoto, Ticket


@admin.register(Landmark)
class LandmarkAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'location', 'entry_fee', 'capacity', 'status')
    list_filter = ('category', 'status')


@admin.register(LandmarkPhoto)
class LandmarkPhotoAdmin(admin.ModelAdmin):
    list_display = ('landmark', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer', 'destination_type', 'visit_datetime',
                    'number_of_visitors', 'guided_tour', 'total_bill', 'status', 'created_at')
    list_filter = ('destination_type', 'status', 'guided_tour')
    date_hierarchy = 'visit_datetime'