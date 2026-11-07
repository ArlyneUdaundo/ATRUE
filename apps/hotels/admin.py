from django.contrib import admin

from .models import HotelGuest, HotelPhoto, Booking, BookingRoom, Hotel, Room, RoomPhoto, Service


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


class BookingRoomInline(admin.TabularInline):
    model = BookingRoom
    extra = 0
    fields = ('selection_order', 'room', 'guest_first_name', 'guest_middle_name',
              'guest_last_name', 'guest_email', 'guest_contact', 'number_of_adults',
              'number_of_children', 'guest_special_request')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('pk', 'guest', 'created_by', 'rooms_list', 'dates', 'number_of_guests', 'status', 'created_at')
    list_filter = ('status',)
    list_select_related = ('customer', 'guest', 'created_by')
    inlines = (BookingRoomInline,)

    def guest(self, obj):
        return obj.primary_guest_name

    guest.short_description = 'Customer / Guest'

    def rooms_list(self, obj):
        return ", ".join(room.room_number for room in obj.rooms.all())

    rooms_list.short_description = 'Rooms'

    def dates(self, obj):
        entry = obj.room_entries.first()
        if entry is None:
            return '—'
        return f"{entry.check_in:%Y-%m-%d} → {entry.check_out:%Y-%m-%d}"

    dates.short_description = 'Dates'


@admin.register(HotelGuest)
class HotelGuestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'contact', 'created_at')
    search_fields = ('first_name', 'last_name', 'email')
    readonly_fields = ('created_at',)

@admin.register(HotelPhoto)
class HotelPhotoAdmin(admin.ModelAdmin):
    list_display = ("hotel", "is_primary", "caption", "created_at")
    list_filter = ("is_primary",)
