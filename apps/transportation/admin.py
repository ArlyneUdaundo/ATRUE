from django.contrib import admin

from .models import Agency, AgencyPhoto, Booking, Driver, Vehicle


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_number', 'email', 'status')
    list_filter = ('status',)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('agency', 'label', 'plate_number', 'capacity', 'rate_per_km', 'status')
    list_filter = ('agency', 'vehicle_type', 'status')


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'agency', 'license_number', 'contact_number', 'status')
    list_filter = ('agency', 'status')


@admin.register(AgencyPhoto)
class AgencyPhotoAdmin(admin.ModelAdmin):
    list_display = ('agency', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer', 'vehicle', 'driver', 'pickup_location',
                    'drop_off_location', 'distance_km', 'schedule', 'total_bill', 'status', 'created_at')
    list_filter = ('status',)
    date_hierarchy = 'schedule'