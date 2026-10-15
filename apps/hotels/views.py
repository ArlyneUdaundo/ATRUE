import json
import re
from datetime import date, timedelta

from transactions.cart import add_booking_to_cart
from transactions.establishment_flow import add_booking as add_establishment_booking
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction as db_transaction
from django.db.models import Q
from django.core.validators import validate_email
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from accounts.roles import effective_role_keys
from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.hotel_scope import (
    assigned_hotel_ids, hotel_scoped, is_hotel_scoped, scope_hotels, scope_qs,
)
from atrue_core.image_utils import delete_image_record, is_valid_image
from atrue_core.establishment_deletion import delete_booking_history, delete_linked_establishment_history
from atrue_core.services import (
    bill_for_booking,
    cancel_booking,
    checkout,
    compute_hotel_bill,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    record_payment,
    record_transaction,
    resource_is_bookable,
    turnover_conflicts,
    turnover_whole_days,
    validate_stay_dates,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from atrue_core.search_catalog import render_search_page
from atrue_core.location_hierarchy import location_errors
from atrue_core.slugs import get_object_by_slug_or_404

from . import pricing, room_offers
from .models import AdditionalGuest, Amenity, Booking, Hotel, HotelPhoto, Room, RoomPhoto, Service


# Guest contact numbers are digits only: no letters, spaces or punctuation.
# ASCII-only on purpose -- str.isdigit() also accepts things like '²' and
# Arabic-Indic digits, which are not dialable.
CONTACT_DIGITS_RE = re.compile(r'[0-9]+')
MIN_CONTACT_DIGITS = 7
MAX_CONTACT_DIGITS = 15


def _parse_date(value, fallback):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback


def _room_date_conflict(room, start, end, exclude_pk=None):
    """Check a room is not double-booked across BookingRoom entries (BR-014)."""
    qs = Booking.objects.filter(
        room_entries__room=room,
        room_entries__check_in__lt=end,
        room_entries__check_out__gt=start,
    ).exclude(
        status__in=[Booking.Status.CANCELLED, Booking.Status.COMPLETED,
                    Booking.Status.CHECKED_OUT, Booking.Status.DECLINED]
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def _room_turnover_conflict(room, check_in, exclude_pk=None):
    """True when ``check_in`` falls inside a prior stay's turnover window."""
    if turnover_whole_days() <= 0:
        return False
    qs = Booking.objects.filter(
        room_entries__room=room,
        room_entries__check_out__lte=check_in,
    ).exclude(
        status__in=[Booking.Status.CANCELLED, Booking.Status.COMPLETED,
                    Booking.Status.CHECKED_OUT, Booking.Status.DECLINED]
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    prior_check_outs = qs.values_list('room_entries__check_out', flat=True)
    return any(turnover_conflicts(check_in, prior) for prior in prior_check_outs)


def _room_available_for_dates(room, check_in, check_out):
    """A room is bookable for a date range only when it is not reserved,
    occupied, or under maintenance AND has no conflicting reservation."""
    return (room.status == Room.RoomStatus.AVAILABLE
            and not _room_date_conflict(room, check_in, check_out)
            and not _room_turnover_conflict(room, check_in))


def _location_errors(province, municipality, barangay="", country=""):
    """Server-side check against the canonical (worldwide) location hierarchy.

    Province + Municipality/City are always required; Barangay is required
    only when the chosen city/municipality has barangays on file. A free-text
    Barangay is accepted, but Province/Municipality must form a real pair in
    the selected country's tree.
    """
    return location_errors(country, province, municipality, barangay)


# -- Establishment CRUD ---------------------------------------------------------

def hotel_list(request):
    hotels = Hotel.objects.filter(status=Hotel.Status.ACTIVE).prefetch_related(
        'photos', 'rooms', 'rooms__photos', 'services', 'amenities'
    )

    # The landing-page search passes dates/guest counts here. Filter hotels by
    # rooms that are actually usable for the requested stay instead of merely
    # checking the room's static AVAILABLE status.
    check_in = _parse_date(request.GET.get('check_in'), None)
    check_out = _parse_date(request.GET.get('check_out'), None)
    try:
        adults = max(1, int(request.GET.get('adults') or request.GET.get('guests') or 2))
    except (TypeError, ValueError):
        adults = 2
    try:
        children = max(0, int(request.GET.get('children') or 0))
    except (TypeError, ValueError):
        children = 0
    try:
        requested_rooms = max(1, int(request.GET.get('rooms') or 1))
    except (TypeError, ValueError):
        requested_rooms = 1

    def room_available(room):
        if room.status != Room.RoomStatus.AVAILABLE:
            return False
        if check_in and check_out and check_out > check_in:
            return not _room_date_conflict(room, check_in, check_out)
        return True

    if (request.user.is_authenticated and request.user.can_manage_hotels) or not (check_in and check_out):
        # Show every active hotel in the catalogue until a customer requests
        # specific dates. Apply room availability only to an actual date search.
        filtered = list(hotels)
    else:
        filtered = []
        for hotel in hotels:
            hotel_rooms = list(hotel.rooms.all())
            available_rooms = [r for r in hotel_rooms if room_available(r)]
            if not hotel_rooms or len(available_rooms) >= requested_rooms:
                filtered.append(hotel)
    return render_search_page(request, 'hotel', filtered)


@manager_required
@hotel_scoped
def manage(request):
    qs = Hotel.objects.prefetch_related('photos', 'rooms', 'rooms__photos', 'services', 'amenities').all()
    qs = scope_hotels(request, qs)
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    country = (request.GET.get('country') or '').strip()
    province = (request.GET.get('province') or '').strip()
    municipality = (request.GET.get('municipality') or '').strip()
    barangay = (request.GET.get('barangay') or '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(establishment_id__icontains=q) |
                       Q(contact_number__icontains=q) | Q(email__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if country:
        qs = qs.filter(country__icontains=country)
    if province:
        qs = qs.filter(province__icontains=province)
    if municipality:
        qs = qs.filter(municipality__icontains=municipality)
    if barangay:
        qs = qs.filter(barangay__icontains=barangay)
    return render(request, 'hotels/manage.html', {
        'hotels': qs,
        'q': q,
        'status': status,
        'country': country,
        'province': province,
        'municipality': municipality,
        'barangay': barangay,
        'status_choices': Hotel.Status.choices,
        'active_assignment': request.assigned_hotel_assignment,
        'hotel_scoped_user': is_hotel_scoped(request.user),
        'hotel_owner': 'HOTEL_OWNER' in effective_role_keys(request.user),
    })

@manager_required
@hotel_scoped
def add_hotel(request):
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        country = (request.POST.get('country') or '').strip()
        province = (request.POST.get('province') or '').strip()
        municipality = (request.POST.get('municipality') or '').strip()
        barangay = (request.POST.get('barangay') or '').strip()
        fd = {
            'name': name,
            'country': country,
            'province': province,
            'municipality': municipality,
            'barangay': barangay,
            'contact_number': request.POST.get('contact_number', ''),
            'email': request.POST.get('email', ''),
            'operating_schedule': request.POST.get('operating_schedule', ''),
        }
        errors = []
        if not name:
            errors.append("Hotel name is required.")
        errors.extend(_location_errors(province, municipality, barangay, country))
        if errors:
            return render(request, 'hotels/form.html', {
                'hotel': None,
                'fd': fd,
                'error': ' '.join(errors),
            })
        hotel = Hotel.objects.create(
            name=name,
            country=country,
            province=province,
            municipality=municipality,
            barangay=barangay,
            contact_number=request.POST.get('contact_number', ''),
            email=request.POST.get('email', ''),
            operating_schedule=request.POST.get('operating_schedule', ''),
        )
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for index, image in enumerate(photos):
            HotelPhoto.objects.create(hotel=hotel, image=image, is_primary=(index == 0))
        log_activity(request.user, "Created hotel", f"{hotel.name} ({hotel.establishment_id})")
        messages.success(request, f"Hotel '{hotel.name}' created (ID: {hotel.establishment_id}).")
        return redirect('hotels:manage')
    return render(request, 'hotels/form.html', {'hotel': None, 'fd': {}})


@manager_required
@hotel_scoped
def update_hotel(request, hotel_id):
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        country = (request.POST.get('country') or '').strip()
        province = (request.POST.get('province') or '').strip()
        municipality = (request.POST.get('municipality') or '').strip()
        barangay = (request.POST.get('barangay') or '').strip()
        fd = {
            'name': name,
            'country': country,
            'province': province,
            'municipality': municipality,
            'barangay': barangay,
            'contact_number': request.POST.get('contact_number', ''),
            'email': request.POST.get('email', ''),
            'operating_schedule': request.POST.get('operating_schedule', ''),
            'status': request.POST.get('status', hotel.status),
        }
        errors = []
        if not name:
            errors.append("Hotel name is required.")
        errors.extend(_location_errors(province, municipality, barangay, country))
        if errors:
            return render(request, 'hotels/form.html', {
                'hotel': hotel,
                'fd': fd,
                'error': ' '.join(errors),
            })
        hotel.name = name
        hotel.country = country
        hotel.province = province
        hotel.municipality = municipality
        hotel.barangay = barangay
        hotel.contact_number = fd['contact_number']
        hotel.email = fd['email']
        hotel.operating_schedule = fd['operating_schedule']
        hotel.status = fd['status']
        hotel.save()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for image in photos:
            HotelPhoto.objects.create(hotel=hotel, image=image, is_primary=not hotel.photos.exists())
        for photo in hotel.photos.filter(pk__in=request.POST.getlist('delete_photos')):
            delete_image_record(photo)
        # Always keep a primary image when photos exist.
        if hotel.photos.exists() and not hotel.photos.filter(is_primary=True).exists():
            first = hotel.photos.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        log_activity(request.user, "Updated hotel", f"{hotel.name} ({hotel.establishment_id})")
        messages.success(request, "Hotel updated.")
        return redirect('hotels:manage')
    return render(request, 'hotels/form.html', {'hotel': hotel, 'fd': {
        'name': hotel.name,
        'country': hotel.country,
        'province': hotel.province,
        'municipality': hotel.municipality,
        'barangay': hotel.barangay,
        'contact_number': hotel.contact_number,
        'email': hotel.email,
        'operating_schedule': hotel.operating_schedule,
        'status': hotel.status,
    }})


@manager_required
@hotel_scoped
def delete_hotel(request, hotel_id):
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    if request.method == 'POST':
        name = hotel.name
        bookings = Booking.objects.filter(rooms__hotel=hotel).distinct()
        with db_transaction.atomic():
            delete_booking_history(bookings, include_hotel_payments=True)
            delete_linked_establishment_history(hotel)
            hotel.delete()
        log_activity(request.user, "Deleted hotel", name)
        messages.success(request, f"Hotel '{name}' and its booking history deleted.")
        return redirect('hotels:manage')
    messages.warning(request, "Invalid request.")
    return redirect('hotels:manage')


def hotel_detail(request, hotel_id):
    """FR-003 VIEW Hotel – full detail profile (rooms, services, amenities).

    Room availability is computed against the customer-selected check-in /
    check-out dates: a room appears bookable only when it is not reserved,
    currently in use, or under maintenance for that date range.
    """
    hotel = get_object_by_slug_or_404(
        Hotel.objects.prefetch_related('photos', 'rooms', 'rooms__photos', 'services', 'amenities'),
        hotel_id,
    )
    can_manage = getattr(request.user, 'can_manage_hotels', False)
    if hotel.status != Hotel.Status.ACTIVE and not can_manage:
        messages.error(request, "This hotel is currently unavailable.")
        return redirect('hotels:list')
    default_in = date.today() + timedelta(days=1)
    check_in = _parse_date(request.GET.get('check_in'), default_in)
    check_out = _parse_date(request.GET.get('check_out'), default_in + timedelta(days=1))
    if check_out <= check_in:
        check_out = check_in + timedelta(days=1)
    available_room_ids = {
        r.id for r in hotel.rooms.all()
        if _room_available_for_dates(r, check_in, check_out)
    }
    # The public page is open to everyone, but the "Update" control is only
    # honest when this user could actually open the edit screen: a Front Desk
    # student may edit their own hotel and nobody else's.
    can_edit = can_manage and (
        not is_hotel_scoped(request.user) or hotel.id in assigned_hotel_ids(request.user)
    )
    return render(request, 'hotels/detail.html', {
        'hotel': hotel,
        'is_manager': can_manage,
        'can_edit_hotel': can_edit,
        'check_in': check_in,
        'check_out': check_out,
        'nights': max(1, (check_out - check_in).days),
        'available_room_ids': available_room_ids,
    })


# -- Room CRUD -----------------------------------------------------------------

@manager_required
@hotel_scoped
def add_room(request, hotel_id):
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    error = None
    room_type = Room.RoomType.SINGLE
    if request.method == 'POST':
        room_number = (request.POST.get('room_number') or '').strip()
        room_type = request.POST.get('room_type') or Room.RoomType.SINGLE
        # Price defaults come from the standard ATRUE table, keyed by room type.
        # A manager can still type an override, but a blank or broken amount
        # falls back to the standard price instead of silently becoming 0.
        rate, rate_err = pricing.parse_money(
            request.POST.get('rate'), pricing.standard_rate(room_type))
        extra_charge, extra_err = pricing.parse_money(
            request.POST.get('additional_guest_charge'),
            pricing.standard_extra_guest_charge(room_type))
        if rate_err or extra_err:
            error = rate_err or extra_err
        elif Room.objects.filter(hotel=hotel, room_number=room_number).exists():
            error = f"Room {room_number} already exists in '{hotel.name}'. Choose a different room number."
        else:
            room = Room.objects.create(
                hotel=hotel,
                room_number=room_number,
                room_type=room_type,
                capacity_adults=int(request.POST.get('capacity_adults') or 2),
                capacity_children=int(request.POST.get('capacity_children') or 0),
                max_guest_capacity=int(request.POST.get('max_guest_capacity') or 0),
                rate=rate,
                additional_guest_charge=extra_charge,
                features=request.POST.get('features', ''),
                description=request.POST.get('description', ''),
                status=request.POST.get('status', Room.RoomStatus.AVAILABLE),
            )
            for image in request.FILES.getlist('photos'):
                if is_valid_image(image):
                    RoomPhoto.objects.create(room=room, image=image)
            log_activity(request.user, "Added hotel room",
                         f"{room.room_id} ({room.room_number}) in {hotel.name}")
            messages.success(request, f"Room {room.room_number} added (ID: {room.room_id}).")
            return redirect(f"{reverse('hotels:rooms')}?hotel={hotel.pk}")
    return render(request, 'hotels/room_form.html', _room_form_context(
        hotel=hotel, room=None, error=error, room_type=room_type,
    ))


@manager_required
@hotel_scoped
def update_room(request, room_id):
    room = get_object_or_404(Room.objects.prefetch_related('photos'), pk=room_id)
    error = None
    room_type = room.room_type
    if request.method == 'POST':
        room_number = (request.POST.get('room_number') or room.room_number).strip()
        room_type = request.POST.get('room_type') or room.room_type
        rate, rate_err = pricing.parse_money(
            request.POST.get('rate'), room.rate)
        extra_charge, extra_err = pricing.parse_money(
            request.POST.get('additional_guest_charge'), room.additional_guest_charge)
        duplicate = Room.objects.filter(hotel=room.hotel, room_number=room_number).exclude(pk=room.pk).exists()
        if rate_err or extra_err:
            error = rate_err or extra_err
        elif duplicate:
            error = f"Room {room_number} already exists in '{room.hotel.name}'. Choose a different room number."
        else:
            room.room_number = room_number
            room.room_type = room_type
            room.capacity_adults = int(request.POST.get('capacity_adults') or room.capacity_adults)
            room.capacity_children = int(request.POST.get('capacity_children') or room.capacity_children)
            room.max_guest_capacity = int(request.POST.get('max_guest_capacity') or 0)
            # parse_money returns the existing value when a field is left blank,
            # and 0 is preserved rather than being treated as "missing".
            room.rate = rate
            room.additional_guest_charge = extra_charge
            room.features = request.POST.get('features', room.features)
            room.description = request.POST.get('description', room.description)
            room.status = request.POST.get('status', room.status)
            room.save()
            for image in request.FILES.getlist('photos'):
                if is_valid_image(image):
                    RoomPhoto.objects.create(room=room, image=image)
            for photo in room.photos.filter(pk__in=request.POST.getlist('delete_photos')):
                delete_image_record(photo)
            log_activity(request.user, "Updated hotel room",
                         f"{room.room_id} ({room.room_number}) in {room.hotel.name}")
            messages.success(request, "Room updated.")
            return redirect('hotels:manage')
    return render(request, 'hotels/room_form.html', _room_form_context(
        hotel=room.hotel, room=room, error=error, room_type=room_type,
    ))


def _room_form_context(hotel, room, error, room_type):
    """Context for ``hotels/room_form.html``, including the standard prices.

    When adding a room the form is pre-filled with ATRUE's standard rate for the
    selected room type; when editing, the room's own stored values are used.
    """
    return {
        'hotel': hotel,
        'room': room,
        'error': error,
        'room_type_choices': Room.RoomType.choices,
        'status_choices': Room.RoomStatus.choices,
        'default_rate': pricing.standard_rate(room_type),
        'default_extra_guest_charge': pricing.standard_extra_guest_charge(room_type),
        'autofill_pricing': room is None,
        'rate_lookup_json': json.dumps(
            {k: f'{v:.2f}' for k, v in pricing.RATE_BY_ROOM_TYPE.items()}),
        'extra_lookup_json': json.dumps(
            {k: f'{v:.2f}' for k, v in pricing.EXTRA_GUEST_CHARGE_BY_ROOM_TYPE.items()}),
    }


@manager_required
@hotel_scoped
def delete_room(request, room_id):
    room = get_object_or_404(Room, pk=room_id)
    if request.method == 'POST':
        active = room.booking_entries.filter(
            booking__status__in=[Booking.Status.PENDING, Booking.Status.CONFIRMED,
                                 Booking.Status.MODIFIED, Booking.Status.CHECKED_IN]
        ).exists()
        if active:
            messages.error(request,
                           f"Room {room.room_number} is reserved by active bookings and cannot be deleted.")
        else:
            hotel_name = room.hotel.name
            room_number = room.room_number
            room.delete()
            log_activity(request.user, "Deleted hotel room", f"Room {room_number} in {hotel_name}")
            messages.success(request, f"Room {room_number} deleted.")
        return redirect('hotels:manage')
    messages.warning(request, "Invalid request.")
    return redirect('hotels:manage')


@manager_required
@hotel_scoped
def rooms(request):
    """FR-002 RETRIEVE Rooms – search and filter by hotel, type, or status."""
    qs = Room.objects.select_related('hotel').prefetch_related('photos').all()
    qs = scope_qs(request, qs, field='hotel_id')
    q = (request.GET.get('q') or '').strip()
    hotel_id = (request.GET.get('hotel') or '').strip()
    room_type = (request.GET.get('room_type') or '').strip()
    status = (request.GET.get('status') or '').strip()
    if q:
        qs = qs.filter(Q(room_id__icontains=q) | Q(room_number__icontains=q) | Q(hotel__name__icontains=q))
    if hotel_id.isdigit():
        qs = qs.filter(hotel_id=int(hotel_id))
    if room_type:
        qs = qs.filter(room_type=room_type)
    if status:
        qs = qs.filter(status=status)
    hotels = scope_hotels(request, Hotel.objects.all())
    add_hotel_id = hotel_id if hotel_id.isdigit() else (hotels.first().id if hotels.exists() else None)
    return render(request, 'hotels/rooms.html', {
        'rooms': qs,
        'q': q,
        'hotel_id': hotel_id,
        'room_type': room_type,
        'status': status,
        'hotels': hotels,
        'add_hotel_id': add_hotel_id,
        'hotel_scoped_user': is_hotel_scoped(request.user),
        'room_type_choices': Room.RoomType.choices,
        'status_choices': Room.RoomStatus.choices,
    })


@login_required
@hotel_scoped
def room_detail(request, room_id):
    """FR-003 VIEW Room – full detail profile (photos, features, rate, availability).

    Booking opportunities are computed against the customer-selected
    check-in / check-out dates (default: tomorrow for one night).
    """
    room = get_object_or_404(
        Room.objects.select_related('hotel').prefetch_related('photos'),
        pk=room_id,
    )
    is_manager = request.user.can_manage_hotels
    if room.status != Room.RoomStatus.AVAILABLE and not is_manager:
        messages.error(request, "This room is currently unavailable.")
        return redirect('hotels:detail', room.hotel.slug)
    default_in = date.today() + timedelta(days=1)
    check_in = _parse_date(request.GET.get('check_in'), default_in)
    check_out = _parse_date(request.GET.get('check_out'), default_in + timedelta(days=1))
    if check_out <= check_in:
        check_out = check_in + timedelta(days=1)
    available_for_dates = bool(is_manager) or _room_available_for_dates(room, check_in, check_out)
    return render(request, 'hotels/room_detail.html', {
        'room': room,
        'is_manager': is_manager,
        'check_in': check_in,
        'check_out': check_out,
        'available_for_dates': available_for_dates,
    })


# -- Service / Amenity CRUD ----------------------------------------------------

@manager_required
@hotel_scoped
def add_service(request, hotel_id):
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        description = request.POST.get('description', '')
        rate = request.POST.get('rate') or 0
        operating_hours = request.POST.get('operating_hours', '')
        status = request.POST.get('status', Service.ServiceStatus.ACTIVE)
        created = 0
        with db_transaction.atomic():
            for target_hotel in scope_hotels(request, Hotel.objects.all()):
                exists = Service.objects.filter(hotel=target_hotel, name__iexact=name).exists()
                if exists:
                    continue
                service = Service.objects.create(
                    hotel=target_hotel,
                    name=name,
                    description=description,
                    rate=rate,
                    operating_hours=operating_hours,
                    status=status,
                )
                created += 1
        log_activity(request.user, "Added shared hotel service",
                     f"{name} added to {created} hotel(s), starting from {hotel.name}")
        messages.success(request, f"Service '{name}' added to {created} hotel(s). Existing same-name services were kept.")
        return redirect('hotels:manage')
    return render(request, 'hotels/service_form.html', {'hotel': hotel, 'service': None})

@manager_required
@hotel_scoped
def update_service(request, service_id):
    service = get_object_or_404(Service, pk=service_id)
    if request.method == 'POST':
        service.name = request.POST.get('name', service.name)
        service.description = request.POST.get('description', service.description)
        service.rate = request.POST.get('rate') or service.rate
        service.operating_hours = request.POST.get('operating_hours', service.operating_hours)
        service.status = request.POST.get('status', service.status)
        service.save()
        log_activity(request.user, "Updated hotel service",
                     f"{service.name} ({service.service_id}) in {service.hotel.name}")
        messages.success(request, "Service updated.")
        return redirect('hotels:manage')
    return render(request, 'hotels/service_form.html', {'hotel': service.hotel, 'service': service})


@manager_required
@hotel_scoped
def delete_service(request, service_id):
    service = get_object_or_404(Service, pk=service_id)
    if request.method == 'POST':
        if service.booking_service_lines.exists():
            messages.error(request,
                           f"Service '{service.name}' is attached to booking records and cannot be deleted. Set its status to Inactive instead.")
        else:
            hotel_name = service.hotel.name
            name = service.name
            service.delete()
            log_activity(request.user, "Deleted hotel service", f"{name} in {hotel_name}")
            messages.success(request, f"Service '{name}' deleted.")
        return redirect('hotels:manage')
    messages.warning(request, "Invalid request.")
    return redirect('hotels:manage')


@manager_required
@hotel_scoped
def services(request):
    """FR-002 Retrieve the Service of the Hotel – search by name, status, hotel."""
    qs = Service.objects.select_related('hotel').all()
    qs = scope_qs(request, qs, field='hotel_id')
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    hotel_id = (request.GET.get('hotel') or '').strip()
    if q:
        qs = qs.filter(Q(service_id__icontains=q) | Q(name__icontains=q) | Q(hotel__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if hotel_id.isdigit():
        qs = qs.filter(hotel_id=int(hotel_id))
    hotels = scope_hotels(request, Hotel.objects.all())
    add_hotel_id = hotel_id if hotel_id.isdigit() else (hotels.first().id if hotels.exists() else None)
    return render(request, 'hotels/services.html', {
        'services': qs,
        'q': q,
        'status': status,
        'hotel_id': hotel_id,
        'hotels': hotels,
        'add_hotel_id': add_hotel_id,
        'hotel_scoped_user': is_hotel_scoped(request.user),
        'status_choices': Service.ServiceStatus.choices,
    })


@login_required
@hotel_scoped
def service_detail(request, service_id):
    """FR-003/FR-004 View the Services of the Hotel – full details (active for customers)."""
    service = get_object_or_404(Service.objects.select_related('hotel'), pk=service_id)
    is_manager = request.user.can_manage_hotels
    if service.status != Service.ServiceStatus.ACTIVE and not is_manager:
        messages.error(request, "This service is currently unavailable.")
        return redirect('hotels:detail', service.hotel.slug)
    return render(request, 'hotels/service_detail.html', {
        'service': service,
        'is_manager': is_manager,
    })


@manager_required
@hotel_scoped
def add_amenity(request, hotel_id):
    hotel = get_object_or_404(Hotel, pk=hotel_id)
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        description = request.POST.get('description', '')
        operating_hours = request.POST.get('operating_hours', '')
        status = request.POST.get('status', Amenity.AmenityStatus.ACTIVE)
        created = 0
        with db_transaction.atomic():
            for target_hotel in scope_hotels(request, Hotel.objects.all()):
                exists = Amenity.objects.filter(hotel=target_hotel, name__iexact=name).exists()
                if exists:
                    continue
                Amenity.objects.create(
                    hotel=target_hotel,
                    name=name,
                    description=description,
                    operating_hours=operating_hours,
                    status=status,
                )
                created += 1
        log_activity(request.user, "Added shared hotel amenity",
                     f"{name} added to {created} hotel(s), starting from {hotel.name}")
        messages.success(request, f"Amenity '{name}' added to {created} hotel(s). Existing same-name amenities were kept.")
        return redirect('hotels:manage')
    return render(request, 'hotels/amenity_form.html', {'hotel': hotel, 'amenity': None})

@manager_required
@hotel_scoped
def update_amenity(request, amenity_id):
    amenity = get_object_or_404(Amenity, pk=amenity_id)
    if request.method == 'POST':
        amenity.name = request.POST.get('name', amenity.name)
        amenity.description = request.POST.get('description', amenity.description)
        amenity.operating_hours = request.POST.get('operating_hours', amenity.operating_hours)
        amenity.status = request.POST.get('status', amenity.status)
        amenity.save()
        log_activity(request.user, "Updated hotel amenity",
                     f"{amenity.name} ({amenity.amenity_id}) in {amenity.hotel.name}")
        messages.success(request, "Amenity updated.")
        return redirect('hotels:manage')
    return render(request, 'hotels/amenity_form.html', {'hotel': amenity.hotel, 'amenity': amenity})


@manager_required
@hotel_scoped
def delete_amenity(request, amenity_id):
    amenity = get_object_or_404(Amenity, pk=amenity_id)
    if request.method == 'POST':
        if amenity.booking_amenity_lines.exists():
            messages.error(request,
                           f"Amenity '{amenity.name}' is attached to booking records and cannot be deleted. Set its status to Inactive instead.")
        else:
            hotel_name = amenity.hotel.name
            name = amenity.name
            amenity.delete()
            log_activity(request.user, "Deleted hotel amenity", f"{name} in {hotel_name}")
            messages.success(request, f"Amenity '{name}' deleted.")
        return redirect('hotels:manage')
    messages.warning(request, "Invalid request.")
    return redirect('hotels:manage')


@manager_required
@hotel_scoped
def amenities(request):
    """FR-002 Retrieve Amenities – search by name, status, or hotel."""
    qs = Amenity.objects.select_related('hotel').all()
    qs = scope_qs(request, qs, field='hotel_id')
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    hotel_id = (request.GET.get('hotel') or '').strip()
    if q:
        qs = qs.filter(Q(amenity_id__icontains=q) | Q(name__icontains=q) | Q(hotel__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if hotel_id.isdigit():
        qs = qs.filter(hotel_id=int(hotel_id))
    hotels = scope_hotels(request, Hotel.objects.all())
    add_hotel_id = hotel_id if hotel_id.isdigit() else (hotels.first().id if hotels.exists() else None)
    return render(request, 'hotels/amenities.html', {
        'amenities': qs,
        'q': q,
        'status': status,
        'hotel_id': hotel_id,
        'hotels': hotels,
        'add_hotel_id': add_hotel_id,
        'hotel_scoped_user': is_hotel_scoped(request.user),
        'status_choices': Amenity.AmenityStatus.choices,
    })


@login_required
@hotel_scoped
def amenity_detail(request, amenity_id):
    """FR-004 View Amenity – full details (active only for customers)."""
    amenity = get_object_or_404(Amenity.objects.select_related('hotel'), pk=amenity_id)
    is_manager = request.user.can_manage_hotels
    if amenity.status != Amenity.AmenityStatus.ACTIVE and not is_manager:
        messages.error(request, "This amenity is currently unavailable.")
        return redirect('hotels:detail', amenity.hotel.slug)
    return render(request, 'hotels/amenity_detail.html', {
        'amenity': amenity,
        'is_manager': is_manager,
    })


# -- Booking -------------------------------------------------------------------

def _room_display_status(room, check_in, check_out):
    """Human-ready availability label for the customer RoOMs page.

    Mirrors the reference UI vocabulary: Available / Reserved / In Use /
    Under Maintenance. Base states come from the room's current lifecycle
    status; a room that is nominally AVAILABLE but has a conflicting
    reservation on the chosen dates is surfaced as Reserved for those dates.
    """
    if room.status == Room.RoomStatus.MAINTENANCE:
        return "Under Maintenance"
    if room.status == Room.RoomStatus.OCCUPIED:
        return "In Use"
    if room.status == Room.RoomStatus.RESERVED:
        return "Reserved"
    if _room_available_for_dates(room, check_in, check_out):
        return "Available"
    return "Reserved"


def _guest_line_defaults(rooms, user=None):
    """Guest lines ordered by selected rooms, with account holder first."""
    lines = [{
        'first_name': '', 'middle_name': '', 'last_name': '',
        'email': '', 'contact': '', 'adults': 1, 'children': 0,
        'special_request': '', 'services': [], 'amenities': [],
    } for _ in rooms]
    if lines and user is not None:
        lines[0].update({'first_name': user.first_name or user.username,
            'middle_name': user.middle_name or '', 'last_name': user.last_name or '',
            'email': user.email or '', 'contact': user.contact_number or ''})
    return lines


def _parse_guest_lines(request, rooms):
    """Parse per-room guest lines from the dynamic booking form (room_0_* fields).

    Validates required guest information per room and the guest count against
    the room's maximum capacity. Returns (guest_lines, errors).
    """
    guest_lines = []
    errors = []
    for idx, room in enumerate(rooms):
        prefix = f'room_{idx}_'
        first = (request.POST.get(prefix + 'first_name') or '').strip()
        middle = (request.POST.get(prefix + 'middle_name') or '').strip()
        last = (request.POST.get(prefix + 'last_name') or '').strip()
        email = (request.POST.get(prefix + 'email') or '').strip()
        contact = (request.POST.get(prefix + 'contact') or '').strip()
        special = (request.POST.get(prefix + 'special_request') or '').strip()
        if idx == 0:
            first = request.user.first_name or request.user.username
            middle = request.user.middle_name or ''
            last = request.user.last_name or ''
            email = request.user.email or ''
            contact = request.user.contact_number or ''
        try:
            adults = max(0, int(request.POST.get(prefix + 'adults') or 0))
            children = max(0, int(request.POST.get(prefix + 'children') or 0))
        except (TypeError, ValueError):
            adults, children = 0, 0
        total_guests = adults + children
        if not first or not last or not email or not contact or total_guests < 1:
            errors.append(f"Please complete the required guest information for Room {idx + 1}.")
        if email:
            try:
                validate_email(email)
            except Exception:
                errors.append(f"Enter a valid email for Room {idx + 1}.")
        if contact and not CONTACT_DIGITS_RE.fullmatch(contact):
            errors.append(
                f"Contact number for Room {idx + 1} must contain numbers only "
                f"(no letters, spaces or symbols)."
            )
        elif contact and not MIN_CONTACT_DIGITS <= len(contact) <= MAX_CONTACT_DIGITS:
            errors.append(
                f"Contact number for Room {idx + 1} must be "
                f"{MIN_CONTACT_DIGITS}-{MAX_CONTACT_DIGITS} digits."
            )
        if total_guests > room.maximum_capacity:
            errors.append(
                f"Room {idx + 1} ({room.room_number}) allows up to {room.maximum_capacity} guest(s); "
                f"you entered {total_guests}."
            )
        services = [int(x) for x in request.POST.getlist(prefix + 'services') if str(x).isdigit()]
        amenities = [int(x) for x in request.POST.getlist(prefix + 'amenities') if str(x).isdigit()]
        guest_lines.append({
            'first_name': first, 'middle_name': middle, 'last_name': last,
            'email': email, 'contact': contact, 'adults': adults, 'children': children,
            'special_request': special, 'services': services, 'amenities': amenities,
        })
    return guest_lines, errors


def _preselected_data(rooms, guest_lines):
    """Selected rooms + guest info for the JS single-source state (before json_encode)."""
    payload = []
    for idx, room in enumerate(rooms):
        g = guest_lines[idx] if idx < len(guest_lines) else {}
        payload.append({
            'room_id': room.id,
            'room_number': room.room_number,
            'room_type': room.get_room_type_display(),
            'rate': str(room.rate),
            'capacity': room.capacity,
            'max_guests': room.maximum_capacity,
            'additional_charge': str(room.additional_guest_charge),
            'guest': {
                'first_name': g.get('first_name', ''),
                'middle_name': g.get('middle_name', ''),
                'last_name': g.get('last_name', ''),
                'email': g.get('email', ''),
                'contact': g.get('contact', ''),
                'adults': int(g.get('adults', 1)),
                'children': int(g.get('children', 0)),
                'special_request': g.get('special_request', ''),
            },
            'services': [int(s) for s in g.get('services', [])],
            'amenities': [int(a) for a in g.get('amenities', [])],
        })
    return payload


def _rooms_meta_dict(rooms, cards=None):
    """Room lookup data for the dynamic form JS, keyed by room id (before json_encode)."""
    extra = {c['room'].id: c for c in (cards or [])}
    meta = {}
    for r in rooms:
        card = extra.get(r.id, {})
        meta[str(r.id)] = {
            'room_number': r.room_number,
            'room_type': r.get_room_type_display(),
            'rate': str(r.rate),
            'capacity': r.capacity,
            'max_guests': r.maximum_capacity,
            'additional_charge': str(r.additional_guest_charge),
            'bookable': bool(card.get('bookable', True)),
            'max_rooms': card.get('max_rooms', 1),
        }
    return meta


def _services_map(services):
    return {str(s.id): {'name': s.name, 'rate': str(s.rate)} for s in services}


def _amenities_map(amenities):
    return {str(a.id): {'name': a.name} for a in amenities}


def _render_room_selection(request, hotel, check_in, check_out, rooms_needed, adults, children,
                           selected_rooms=None, guest_lines=None, errors=None):
    """Render the single-page dynamic room selection / booking form.

    Also used to re-render the page after a validation error, keeping the
    selected rooms and typed guest information intact for correction.

    The room cards are built by ``room_offers`` (presentation only): they add
    the size / bed / amenity / badge / rate detail the Rooms page renders.
    ``room_data`` keeps the original per-room shape because the booking
    JavaScript reads from it.
    """
    rooms = sorted(hotel.rooms.all(), key=lambda r: (r.get_room_type_display(), r.room_number))
    nights = max(1, (check_out - check_in).days)
    room_data = []
    for room in rooms:
        status = _room_display_status(room, check_in, check_out)
        features = [f.strip() for f in (room.features or '').replace('\r', '').split('\n') if f.strip()] or []
        room_data.append({
            'room': room,
            'display_status': status,
            'bookable': status == "Available",
            'features': features,
        })
    bookable_flags = {item['room'].id: item['bookable'] for item in room_data}
    services = list(hotel.services.filter(status=Service.ServiceStatus.ACTIVE))
    amenities = list(hotel.amenities.filter(status=Amenity.AmenityStatus.ACTIVE))
    room_cards = room_offers.build_room_cards(rooms, bookable_flags, amenities, services, nights)
    display_status = {item['room'].id: item['display_status'] for item in room_data}
    for card in room_cards:
        card['display_status'] = display_status.get(card['room'].id, '')
    selected_rooms = selected_rooms or []
    if guest_lines is None:
        guest_lines = _guest_line_defaults(selected_rooms, request.user)
    session = request.session.get('hotel_group_booking') or {}
    return render(request, 'hotels/group_select_rooms.html', {
        'hotel': hotel,
        'room_data': room_data,
        'room_cards': room_cards,
        'compare_rooms': room_offers.compare_rooms(room_cards, nights),
        'room_details': room_offers.details_payload(
            room_cards, hotel, 'hotels:room_detail', check_in, check_out
        ),
        'check_in': check_in,
        'check_out': check_out,
        'nights': nights,
        'rooms_needed': rooms_needed,
        'adults': adults,
        'children': children,
        'default_payment_method': session.get('payment_method', 'GCASH'),
        'default_pay_later': bool(session.get('pay_later')),
        'room_rates': {str(r.id): str(r.rate) for r in rooms},
        'rooms_meta': _rooms_meta_dict(rooms, room_cards),
        'services_map': _services_map(services),
        'amenities_map': _amenities_map(amenities),
        'services': services,
        'amenities': amenities,
        'preselected': _preselected_data(selected_rooms, guest_lines),
        'primary_guest': {'first_name': request.user.first_name or request.user.username,
            'middle_name': request.user.middle_name or '', 'last_name': request.user.last_name or '',
            'email': request.user.email or '', 'contact': request.user.contact_number or ''},
        'errors': errors or [],
    })


def _create_hotel_booking(user, hotel, rooms, check_in, check_out, guest_lines,
                          method='GCASH', pay_later=False):
    """Create a multi-room hotel booking in ONE database transaction.

    One Booking + one room entry per selected room + one bill + one payment
    (when paying now) + one transaction record. Availability is re-verified
    inside the transaction so no partial booking is ever left behind.
    Returns (booking, error): booking is None when creation failed.
    """
    nights = max(1, (check_out - check_in).days)
    date_errors = validate_stay_dates(check_in, check_out)
    if date_errors:
        return None, date_errors[0]
    try:
        with db_transaction.atomic():
            for room in rooms:
                if not _room_available_for_dates(room, check_in, check_out):
                    raise ValueError(f"Room {room.room_number} is no longer available for the selected dates.")
            booking = Booking.objects.create(
                customer=user,
                payer_name=user.full_profile,
                payer_contact=user.contact_number or '',
                status=Booking.Status.PENDING,
            )
            bill_items = []
            for idx, room in enumerate(rooms):
                g = guest_lines[idx]
                adults = int(g['adults']); children = int(g['children'])
                total_guests = adults + children
                entry = booking.room_entries.create(
                    room=room, selection_order=idx + 1, check_in=check_in, check_out=check_out,
                    number_of_adults=adults, number_of_children=children,
                    guest_first_name=g.get('first_name', ''), guest_middle_name=g.get('middle_name', ''),
                    guest_last_name=g.get('last_name', ''), guest_email=g.get('email', ''),
                    guest_contact=g.get('contact', ''), guest_special_request=g.get('special_request', ''),
                )
                selected_services = list(hotel.services.filter(pk__in=g.get('services', []), status=Service.ServiceStatus.ACTIVE))
                selected_amenities = list(hotel.amenities.filter(pk__in=g.get('amenities', []), status=Amenity.AmenityStatus.ACTIVE))
                entry.booked_services.bulk_create([
                    entry.booked_services.model(booking_room=entry, service=s, price_at_booking=s.rate) for s in selected_services
                ])
                entry.booked_amenities.bulk_create([
                    entry.booked_amenities.model(booking_room=entry, amenity=a, price_at_booking=0) for a in selected_amenities
                ])
                extra_count = max(0, total_guests - room.capacity)
                room_amount = room.rate * nights
                extra_amount = room.additional_guest_charge * extra_count * nights
                bill_items.append({'label': room.get_room_type_display(), 'description': f'Room {room.room_number} × {nights} night(s)', 'quantity': nights, 'rate': room.rate, 'amount': room_amount})
                if extra_count:
                    bill_items.append({'label': 'Additional guest charge', 'description': f'Room {room.room_number}: {extra_count} extra guest(s) × {nights} night(s)', 'quantity': extra_count * nights, 'rate': room.additional_guest_charge, 'amount': extra_amount})
                for service in selected_services:
                    bill_items.append({'label': service.name, 'description': f'Room {room.room_number} hotel service', 'quantity': 1, 'rate': service.rate, 'amount': service.rate})
            total = sum((Decimal(str(i['amount'])) for i in bill_items), Decimal('0'))
            bill = create_bill(service='hotel', customer=user, items=bill_items, booking=booking)
            if pay_later:
                log_activity(user, 'Placed hotel group booking', f'{booking.booking_reference} · {len(rooms)} room(s) · pending payment')
                record_transaction('BOOKING', booking.booking_reference, user, f'Hotel group booking {booking.booking_reference}')
            else:
                record_payment(customer=user, amount=total, method=method, service='hotel',
                               description=f'Hotel group booking {booking.booking_reference}', bill=bill, booking=booking)
                booking.status = Booking.Status.PENDING
                booking.amount_paid = total
                booking.save(update_fields=['status', 'amount_paid'])
                log_activity(user, 'Paid for hotel group booking', f'{booking.booking_reference} · {len(rooms)} room(s) · pending officer confirmation')
                record_transaction('BOOKING', booking.booking_reference, user, f'Hotel group booking {booking.booking_reference} paid')
            return booking, None
    except ValueError as exc:
        return None, str(exc)


@login_required
@student_booking_required
def hotel_group_start(request, hotel_id):
    """Start a direct multi-room hotel booking. No Trip Cart is used.

    The Rooms page lists EVERY room of the hotel with a per-date availability
    badge (Available / Reserved / In Use / Under Maintenance). Only rooms that
    are genuinely bookable for the chosen check-in / check-out can be
    selected; everything else is shown disabled.
    """
    hotel = get_object_or_404(
        Hotel.objects.filter(status=Hotel.Status.ACTIVE).prefetch_related('rooms', 'rooms__photos', 'services', 'amenities'),
        pk=hotel_id,
    )
    check_in = _parse_date(request.GET.get('check_in'), date.today() + timedelta(days=1))
    check_out = _parse_date(request.GET.get('check_out'), check_in + timedelta(days=1))
    try:
        rooms_needed = max(1, int(request.GET.get('rooms') or 1))
    except (TypeError, ValueError):
        rooms_needed = 1
    try:
        adults = max(1, int(request.GET.get('adults') or rooms_needed))
    except (TypeError, ValueError):
        adults = rooms_needed
    try:
        children = max(0, int(request.GET.get('children') or 0))
    except (TypeError, ValueError):
        children = 0
    if check_out <= check_in:
        check_out = check_in + timedelta(days=1)
    rooms = sorted(hotel.rooms.all(), key=lambda r: (r.get_room_type_display(), r.room_number))
    room_data = []
    for room in rooms:
        status = _room_display_status(room, check_in, check_out)
        features = [f.strip() for f in (room.features or '').replace('\r', '').split('\n') if f.strip()] or []
        room_data.append({
            'room': room,
            'display_status': status,
            'bookable': status == "Available",
            'features': features,
        })
    available = [r['room'] for r in room_data if r['bookable']]
    if len(available) < rooms_needed:
        messages.error(request, f"{hotel.name} does not have {rooms_needed} room(s) available for those dates.")
        return redirect('hotels:list')
    return _render_room_selection(
        request, hotel, check_in, check_out, rooms_needed, adults, children,
    )


@login_required
@student_booking_required
def hotel_group_select_rooms(request, hotel_id):
    """Single-page dynamic booking submission.

    Validates the selected rooms, then either keeps the legacy multi-step
    behaviour (room selection only -> guest info step) or, when the dynamic
    form submits the per-room guest data (room_N_* fields), creates the whole
    multi-room booking in ONE transaction and answers with the booking page.
    On validation errors the page is re-rendered with the selection and the
    entered guest information preserved for correction.
    """
    hotel = get_object_or_404(
        Hotel.objects.filter(status=Hotel.Status.ACTIVE).prefetch_related('rooms', 'rooms__photos', 'services', 'amenities'),
        pk=hotel_id,
    )
    if request.method != 'POST':
        return redirect('hotels:group_start', hotel_id)
    check_in = _parse_date(request.POST.get('check_in'), date.today() + timedelta(days=1))
    check_out = _parse_date(request.POST.get('check_out'), check_in + timedelta(days=1))
    if check_out <= check_in:
        check_out = check_in + timedelta(days=1)
    room_ids = []
    for raw in request.POST.getlist('room_ids'):
        try:
            room_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    room_ids = list(dict.fromkeys(room_ids))
    if not room_ids:
        messages.error(request, "Please select at least one available room.")
        return redirect(f"/hotels/book/group/{hotel.id}/?check_in={check_in.isoformat()}&check_out={check_out.isoformat()}&rooms=1&adults={request.POST.get('adults','1')}&children={request.POST.get('children','0')}")
    rooms_needed = len(room_ids)
    rooms = list(Room.objects.filter(hotel=hotel, pk__in=room_ids).prefetch_related('photos'))
    if len(rooms) != rooms_needed:
        messages.error(request, "One or more selected rooms are no longer available.")
        return redirect('hotels:group_start', hotel.id)
    rooms.sort(key=lambda r: room_ids.index(r.pk))
    for room in rooms:
        if room.status != Room.RoomStatus.AVAILABLE or _room_date_conflict(room, check_in, check_out):
            messages.error(request, f"Room {room.room_number} is no longer available for those dates.")
            return redirect('hotels:group_start', hotel.id)

    adults_search = int(request.POST.get('adults') or rooms_needed)
    children_search = int(request.POST.get('children') or 0)
    is_final = any(key.startswith('room_0_') for key in request.POST)

    if not is_final:
        request.session['hotel_group_booking'] = {
            'hotel_id': hotel.id,
            'check_in': check_in.isoformat(),
            'check_out': check_out.isoformat(),
            'rooms_needed': rooms_needed,
            'adults_search': adults_search,
            'children_search': children_search,
            'room_ids': room_ids,
            'payment_method': request.POST.get('payment_method', 'GCASH'),
            'pay_later': request.POST.get('pay_later') == 'on',
        }
        request.session.modified = True
        return redirect('hotels:group_guests')

    guest_lines, errors = _parse_guest_lines(request, rooms)
    if errors:
        return _render_room_selection(
            request, hotel, check_in, check_out, rooms_needed, adults_search, children_search,
            selected_rooms=rooms, guest_lines=guest_lines, errors=errors,
        )
    method = request.POST.get('payment_method', 'GCASH')
    pay_later = request.POST.get('pay_later') == 'on'
    booking, create_error = _create_hotel_booking(
        request.user, hotel, rooms, check_in, check_out, guest_lines, method, pay_later,
    )
    if create_error:
        return _render_room_selection(
            request, hotel, check_in, check_out, rooms_needed, adults_search, children_search,
            selected_rooms=rooms, guest_lines=guest_lines, errors=[create_error],
        )
    from simulation.completion import complete_guest_booking
    from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

    complete_guest_booking(
        request.user,
        task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
        booking_reference=booking.booking_reference,
    )
    request.session.pop('hotel_group_booking', None)
    request.session.modified = True
    if booking.status == Booking.Status.CONFIRMED:
        messages.success(request, f'Hotel booking confirmed! Reference: {booking.booking_reference}')
    else:
        messages.success(request, f'Hotel booking {booking.booking_reference} created. Payment is pending.')
    return redirect('hotels:booking_detail', booking.id)


@login_required
@student_booking_required
def hotel_group_guests(request):
    data = request.session.get('hotel_group_booking') or {}
    if not data.get('room_ids'):
        return redirect('hotels:list')
    hotel = get_object_or_404(Hotel.objects.filter(status=Hotel.Status.ACTIVE).prefetch_related('services', 'amenities'), pk=data['hotel_id'])
    rooms = list(Room.objects.filter(hotel=hotel, pk__in=data['room_ids']).prefetch_related('photos'))
    rooms.sort(key=lambda r: data['room_ids'].index(r.pk))
    check_in = date.fromisoformat(data['check_in'])
    check_out = date.fromisoformat(data['check_out'])
    if request.method == 'POST':
        guest_lines, errors = _parse_guest_lines(request, rooms)
        if errors:
            return render(request, 'hotels/group_guests.html', {
                'hotel': hotel, 'room_forms': list(zip(rooms, guest_lines)), 'check_in': check_in, 'check_out': check_out,
                'nights': max(1, (check_out - check_in).days), 'errors': errors,
            })
        request.session['hotel_group_booking']['guests'] = guest_lines
        request.session.modified = True
        return redirect('hotels:group_review')
    return render(request, 'hotels/group_guests.html', {
        'hotel': hotel, 'room_forms': list(zip(rooms, _guest_line_defaults(rooms, request.user))), 'check_in': check_in, 'check_out': check_out,
        'nights': max(1, (check_out - check_in).days),
    })


@login_required
@student_booking_required
def hotel_group_review(request):
    data = request.session.get('hotel_group_booking') or {}
    if not data.get('room_ids') or not data.get('guests'):
        return redirect('hotels:list')
    hotel = get_object_or_404(
        Hotel.objects.filter(status=Hotel.Status.ACTIVE).prefetch_related('services', 'amenities'),
        pk=data['hotel_id'],
    )
    rooms = list(Room.objects.filter(hotel=hotel, pk__in=data['room_ids']).prefetch_related('photos'))
    rooms.sort(key=lambda r: data['room_ids'].index(r.pk))
    check_in = date.fromisoformat(data['check_in']); check_out = date.fromisoformat(data['check_out'])
    nights = max(1, (check_out - check_in).days)
    lines = []
    grand_total = Decimal('0')
    room_subtotal = Decimal('0')
    extra_subtotal = Decimal('0')
    services_subtotal = Decimal('0')
    for idx, room in enumerate(rooms):
        g = data['guests'][idx]
        adults = int(g['adults']); children = int(g['children'])
        total_guests = adults + children
        extra_count = max(0, total_guests - room.capacity)
        extra_total = room.additional_guest_charge * extra_count * nights
        room_total = room.rate * nights
        selected_services = list(room.hotel.services.filter(pk__in=g.get('services', []), status=Service.ServiceStatus.ACTIVE))
        selected_amenities = list(room.hotel.amenities.filter(pk__in=g.get('amenities', []), status=Amenity.AmenityStatus.ACTIVE))
        services_total = sum((s.rate for s in selected_services), Decimal('0'))
        amount = room_total + extra_total + services_total
        grand_total += amount
        room_subtotal += room_total
        extra_subtotal += extra_total
        services_subtotal += services_total
        lines.append({
            'index': idx + 1, 'room': room, 'guest': g, 'extra_count': extra_count,
            'extra_total': extra_total, 'room_total': room_total, 'services': selected_services,
            'amenities': selected_amenities, 'services_total': services_total, 'amount': amount,
        })
    if request.method == 'POST':
        if request.POST.get('action') == 'edit':
            return redirect('hotels:group_guests')
        if request.POST.get('action') == 'proceed_payment':
            return render(request, 'hotels/group_payment.html', {
                'hotel': hotel, 'lines': lines, 'check_in': check_in, 'check_out': check_out,
                'nights': nights, 'grand_total': grand_total,
                'default_payment_method': data.get('payment_method', 'GCASH'),
                'default_pay_later': bool(data.get('pay_later')),
            })
    return render(request, 'hotels/group_review.html', {
        'hotel': hotel, 'lines': lines, 'check_in': check_in, 'check_out': check_out,
        'nights': nights, 'grand_total': grand_total, 'room_subtotal': room_subtotal,
        'extra_subtotal': extra_subtotal, 'services_subtotal': services_subtotal,
    })


@login_required
@student_booking_required
def hotel_group_payment(request):
    data = request.session.get('hotel_group_booking') or {}
    if not data.get('room_ids') or not data.get('guests'):
        return redirect('hotels:list')
    hotel = get_object_or_404(
        Hotel.objects.filter(status=Hotel.Status.ACTIVE).prefetch_related('services', 'amenities'),
        pk=data['hotel_id'],
    )
    rooms = list(Room.objects.filter(hotel=hotel, pk__in=data['room_ids']).prefetch_related('photos'))
    rooms.sort(key=lambda r: data['room_ids'].index(r.pk))
    check_in = date.fromisoformat(data['check_in']); check_out = date.fromisoformat(data['check_out'])
    if len(rooms) != len(data['room_ids']):
        messages.error(request, 'One or more rooms are no longer available.')
        return redirect('hotels:group_start', hotel.id)
    if request.method != 'POST':
        return redirect('hotels:group_review')
    method = request.POST.get('payment_method', 'GCASH')
    pay_later = request.POST.get('pay_later') == 'on'
    booking, create_error = _create_hotel_booking(
        request.user, hotel, rooms, check_in, check_out, data['guests'], method, pay_later,
    )
    if create_error:
        messages.error(request, create_error)
        return redirect('hotels:group_start', hotel.id)
    from simulation.completion import complete_guest_booking
    from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

    complete_guest_booking(
        request.user,
        task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
        booking_reference=booking.booking_reference,
    )
    request.session.pop('hotel_group_booking', None)
    request.session.modified = True
    if booking.status == Booking.Status.CONFIRMED:
        messages.success(request, f'Hotel booking confirmed! Reference: {booking.booking_reference}')
    else:
        messages.success(request, f'Hotel booking {booking.booking_reference} created. Payment is pending.')
    return redirect('hotels:booking_detail', booking.id)


@login_required
@student_booking_required
def book_hotel(request, room_id):
    """Compatibility entry point: send single-room users into the same direct hotel flow."""
    room = get_object_or_404(Room.objects.select_related('hotel'), pk=room_id)
    query = f"?rooms=1&room_id={room.id}"
    return redirect(f"/hotels/book/group/{room.hotel_id}/{query}")


@manager_required
@hotel_scoped
def bookings(request):
    qs = Booking.objects.select_related('customer').prefetch_related(
        'rooms__hotel', 'rooms__hotel__photos', 'room_entries', 'room_entries__room',
    )
    qs = scope_qs(request, qs, field='rooms__hotel_id')
    status = request.GET.get('status', '')
    hotel_id = request.GET.get('hotel', '')
    q = request.GET.get('q', '')
    check_in = request.GET.get('check_in', '')
    check_out = request.GET.get('check_out', '')
    sort = request.GET.get('sort', '')
    if status:
        qs = qs.filter(status=status)
    if hotel_id:
        qs = qs.filter(rooms__hotel_id=hotel_id)
    if q:
        qs = qs.filter(
            Q(booking_reference__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__first_name__icontains=q)
            | Q(customer__last_name__icontains=q)
        )
    from datetime import date
    if check_in:
        try:
            qs = qs.filter(room_entries__check_in__gte=date.fromisoformat(check_in))
        except ValueError:
            pass
    if check_out:
        try:
            qs = qs.filter(room_entries__check_out__lte=date.fromisoformat(check_out))
        except ValueError:
            pass
    sort_map = {
        'booking_date': '-created_at',
        'check_in': 'room_entries__check_in',
        'check_out': 'room_entries__check_out',
        'status': 'status',
    }
    qs = qs.distinct().order_by(sort_map.get(sort, '-created_at'))
    return render(request, 'hotels/bookings.html', {
        'bookings': qs,
        'hotels': scope_hotels(request, Hotel.objects.all()),
        'hotel_scoped_user': is_hotel_scoped(request.user),
        'status': status,
        'q': q,
        'check_in': check_in,
        'check_out': check_out,
        'sort': sort,
    })


@login_required
@hotel_scoped
def booking_detail(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('customer').prefetch_related(
            'rooms__hotel', 'rooms__hotel__photos', 'room_entries', 'room_entries__room',
            'room_entries__services', 'room_entries__amenities',
            'additional_guests',
        ), pk=booking_id
    )
    if booking.customer_id != request.user.id and not (request.user.is_staff or is_manager_user(request.user)):
        messages.warning(request, "You cannot view this booking.")
        return redirect('hotels:list')

    from transactions.models import Bill, Payment
    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()

    can_manage = request.user.is_staff or is_manager_user(request.user)

    from accounts.roles import can_process_booking_checkin
    can_process_checkin = can_process_booking_checkin(request.user, 'hotels')

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')
        if action in {'checkin', 'checkout'} and not can_process_checkin:
            raise PermissionDenied('Reservation Officers cannot process check-in or check-out.')
        if action == 'confirm':
            confirm_booking(booking, request.user)
            if getattr(booking, 'payment_review_pending', False):
                messages.warning(request, 'Waiting for the Billing Officer to verify full payment before confirmation.')
            else:
                messages.success(request, "Booking confirmed.")
        elif action == 'decline':
            decline_booking(booking, request.user)
            messages.success(request, "Booking declined.")
        elif action == 'checkin':
            booking.status = Booking.Status.CHECKED_IN
            booking.checked_in_at = timezone.now()
            booking.save(update_fields=['status', 'checked_in_at'])
            for room in booking.rooms.all():
                room.status = Room.RoomStatus.OCCUPIED
                room.save(update_fields=['status'])
            log_activity(request.user, "Guest checked in", str(booking.pk))
            messages.success(request, "Guest checked in.")
        elif action == 'checkout':
            booking.status = Booking.Status.CHECKED_OUT
            booking.checked_out_at = timezone.now()
            booking.save(update_fields=['status', 'checked_out_at'])
            for room in booking.rooms.all():
                room.status = Room.RoomStatus.AVAILABLE
                room.save(update_fields=['status'])
            log_activity(request.user, "Guest checked out", str(booking.pk))
            messages.success(request, "Guest checked out.")
        elif action == 'modify':
            first_entry = booking.room_entries.first()
            new_in = _parse_date(request.POST.get('check_in'),
                                 first_entry.check_in if first_entry else date.today() + timedelta(days=1))
            new_out = _parse_date(request.POST.get('check_out'),
                                  first_entry.check_out if first_entry else new_in + timedelta(days=1))
            date_errors = validate_stay_dates(new_in, new_out)
            if date_errors:
                messages.error(request, date_errors[0])
                return redirect('hotels:booking_detail', booking.id)
            for entry in booking.room_entries.all():
                if (_room_date_conflict(entry.room, new_in, new_out, exclude_pk=booking.pk)
                        or _room_turnover_conflict(entry.room, new_in, exclude_pk=booking.pk)):
                    messages.error(request, f"Room {entry.room.room_number} is already reserved for the selected dates.")
                    return redirect('hotels:booking_detail', booking.id)
            for entry in booking.room_entries.all():
                entry.check_in = new_in
                entry.check_out = new_out
                entry.number_of_adults = int(request.POST.get('adults') or entry.number_of_adults)
                entry.number_of_children = int(request.POST.get('children') or entry.number_of_children)
                entry.save()
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            booking.status = Booking.Status.MODIFIED
            booking.save()
            messages.success(request, "Booking modified.")
        elif action == 'cancel':
            cancel_booking(booking, request.user)
            for room in booking.rooms.all():
                room.status = Room.RoomStatus.AVAILABLE
                room.save(update_fields=['status'])
            messages.success(request, "Booking cancelled and rooms released.")
        elif action == 'pay':
            amount = request.POST.get('amount') or 0
            method = request.POST.get('payment_method', 'GCASH')
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=amount,
                method=method,
                service='hotel',
                bill=bill,
                description=f"Additional payment for booking {booking.booking_reference}",
            )
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else booking.amount_paid
            booking.save(update_fields=['amount_paid'])
            messages.success(request, "Payment recorded.")
        return redirect('hotels:booking_detail', booking.id)

    return render(request, 'hotels/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'can_print_ticket': booking.customer_id == request.user.id and not request.user.is_staff and not can_manage,
        'can_process_checkin': can_process_checkin,
    })


def is_manager_user(user):
    from accounts.roles import can_manage_booking
    return can_manage_booking(user, 'hotels')


def _get_ticket_booking(request, booking_id):
    """Load a hotel booking the current user is allowed to voucher."""
    from accounts.roles import can_manage_booking

    booking = get_object_or_404(
        Booking.objects.select_related('customer').prefetch_related(
            'room_entries__room__hotel__photos',
            'room_entries__booked_services__service',
            'room_entries__booked_amenities__amenity',
        ),
        pk=booking_id,
    )
    if booking.customer_id != request.user.id or can_manage_booking(request.user, 'hotels') or request.user.is_staff:
        messages.warning(request, "Only the guest who owns this booking may print its ticket.")
        return None
    return booking


@login_required
def ticket_detail(request, booking_id):
    from .ticket import build_ticket_context

    import base64

    booking = _get_ticket_booking(request, booking_id)
    if booking is None:
        return redirect('hotels:list')

    ctx = build_ticket_context(booking)
    ctx['qr']['data_uri'] = 'data:image/png;base64,' + base64.b64encode(ctx['qr']['png']).decode('ascii')
    from .ticket import TICKETABLE_STATUSES
    return render(request, 'hotels/ticket.html', {
        'ticket': ctx,
        'printable': booking.status in TICKETABLE_STATUSES,
    })


@login_required
def ticket_pdf(request, booking_id):
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    from django.http import HttpResponse

    from .ticket import build_ticket_context
    from .ticket_pdf import _build as build_pdf_story

    booking = _get_ticket_booking(request, booking_id)
    if booking is None:
        return redirect('hotels:list')

    ctx = build_ticket_context(booking)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=14 * mm,
        title=f"ATRUE Reservation Voucher {booking.booking_reference}",
        author='ATRUE Travel & Tours (Simulation)',
    )
    doc.build(build_pdf_story(ctx))
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f"inline; filename={ctx['download_name']}"
    return response

