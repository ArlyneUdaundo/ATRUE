from django.contrib import admin

from .models import HotelPhoto, Booking, Hotel, Room, RoomPhoto, Service


@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'contact_number', 'email', 'status')
    list_filter = ('status',)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('hotel', 'room_number', 'room_type', 'capacity', 'rate', 'status')
    list_filter = ('hotel', 'room_type', 'status')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('hotel', 'name', 'rate', 'status')
    list_filter = ('hotel', 'status')


@admin.register(RoomPhoto)
class RoomPhotoAdmin(admin.ModelAdmin):
    list_display = ('room', 'caption', 'image')
    list_filter = ('room__hotel',)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer', 'rooms_list', 'dates', 'number_of_guests', 'status', 'created_at')
    list_filter = ('status',)
    list_select_related = ('customer',)

    def rooms_list(self, obj):
        return ", ".join(room.room_number for room in obj.rooms.all())

    rooms_list.short_description = 'Rooms'

    def dates(self, obj):
        entry = obj.room_entries.first()
        if entry is None:
            return '—'
        return f"{entry.check_in:%Y-%m-%d} → {entry.check_out:%Y-%m-%d}"

    dates.short_description = 'Dates'

@admin.register(HotelPhoto)
class HotelPhotoAdmin(admin.ModelAdmin):
    list_display = ("hotel", "is_primary", "caption", "created_at")
    list_filter = ("is_primary",)
