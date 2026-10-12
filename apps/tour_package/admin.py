from django.contrib import admin

from .models import Booking, BookingGuest, TourPackage, TourPackagePhoto


@admin.register(TourPackage)
class TourPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'establishment', 'price', 'status', 'validity_start_date', 'validity_end_date')
    list_filter = ('establishment', 'status')
    filter_horizontal = ('included_hotels', 'included_resorts', 'included_flights',
                         'included_activities', 'included_restaurants', 'included_transport')


@admin.register(TourPackagePhoto)
class TourPackagePhotoAdmin(admin.ModelAdmin):
    list_display = ('package', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


@admin.register(BookingGuest)
class BookingGuestAdmin(admin.ModelAdmin):
    list_display = ('booking', 'full_name', 'emergency_contact_name', 'emergency_contact_number')
    list_filter = ('booking__package',)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_reference', 'customer', 'package', 'travel_date', 'status')
    list_filter = ('status',)
    search_fields = ('booking_reference', 'customer__username')