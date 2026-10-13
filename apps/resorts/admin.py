from django.contrib import admin

from .models import AdditionalGuest, Reservation, Resort, ResortPhoto, RoomVilla, Service, UnitPhoto


@admin.register(Resort)
class ResortAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'contact_number', 'status')
    list_filter = ('status',)


@admin.register(RoomVilla)
class RoomVillaAdmin(admin.ModelAdmin):
    list_display = ('resort', 'unit_type', 'unit_number', 'capacity', 'rate', 'status')
    list_filter = ('resort', 'unit_type', 'status')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('resort', 'name', 'rate', 'status')
    list_filter = ('resort', 'status')


@admin.register(UnitPhoto)
class UnitPhotoAdmin(admin.ModelAdmin):
    list_display = ('unit', 'caption', 'image')
    list_filter = ('unit__resort',)


@admin.register(ResortPhoto)
class ResortPhotoAdmin(admin.ModelAdmin):
    list_display = ('resort', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


class AdditionalGuestInline(admin.TabularInline):
    model = AdditionalGuest
    extra = 0
    fields = ('selection_order', 'unit', 'first_name', 'middle_name', 'last_name', 'email', 'contact', 'adults', 'children', 'special_requests')


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer', 'unit', 'check_in', 'check_out',
                    'number_of_guests', 'status', 'created_at')
    list_filter = ('status',)
    inlines = (AdditionalGuestInline,)
    date_hierarchy = 'check_in'