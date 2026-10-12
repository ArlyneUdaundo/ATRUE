from django.contrib import admin

from .models import Activity, ActivityPhoto, Booking


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider', 'category', 'fee', 'capacity', 'bookable', 'status')
    list_filter = ('category', 'status', 'provider')


@admin.register(ActivityPhoto)
class ActivityPhotoAdmin(admin.ModelAdmin):
    list_display = ('activity', 'is_primary', 'caption', 'created_at')
    list_filter = ('is_primary',)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer', 'activity', 'schedule_date',
                    'participant_count', 'total_bill', 'status', 'created_at')
    list_filter = ('status', 'schedule_date')
    date_hierarchy = 'schedule_date'
