from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from uuid import uuid4

from transactions.cart import add_booking_to_cart, create_single_booking_order
from transactions.establishment_flow import add_booking as add_establishment_booking
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from atrue_core.decorators import manager_required, student_booking_required
from accounts.roles import effective_role_keys
from atrue_core.image_utils import delete_image_record, is_valid_image
from atrue_core.services import (
    bill_for_booking,
    bill_items_total,
    cancel_booking,
    checkout,
    compute_transport_bill,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    record_payment,
    resource_is_bookable,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .models import Agency, AgencyPhoto, Booking, Driver, Vehicle
from .scope import assigned_agency_ids, scope_agencies, scope_bookings


def _parse_datetime(value, fallback):
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback
    if dt.tzinfo is None:
        return timezone.make_aware(dt)
    return dt.astimezone(timezone.get_current_timezone())


def _vehicle_conflict(vehicle, when, duration_hours=3):
    end = when + timedelta(hours=duration_hours)
    qs = Booking.objects.filter(vehicle=vehicle).exclude(
        status__in=[Booking.Status.CANCELLED, Booking.Status.COMPLETED, Booking.Status.DECLINED,
                    Booking.Status.CHECKED_OUT]
    )
    for b in qs:
        if b.schedule < end and (b.schedule + timedelta(hours=b.duration_hours)) > when:
            return True
    return False


def _vehicle_photo_url(agency, vehicle):
    try:
        if vehicle.image and vehicle.image.name and vehicle.image.storage.exists(vehicle.image.name):
            return vehicle.image.url
    except Exception:
        pass
    vehicle_terms = set(re.findall(
        r"[a-z0-9]+", f"{vehicle.label} {vehicle.get_vehicle_type_display()}".lower()
    )) - {'toyota', 'car', 'cars', 'vehicle', 'vehicles', 'type'}
    for photo in agency.photos.all():
        photo_terms = set(re.findall(
            r"[a-z0-9]+", f"{photo.caption} {photo.image.name}".lower()
        ))
        if not vehicle_terms.intersection(photo_terms):
            continue
        try:
            if photo.image.name and photo.image.storage.exists(photo.image.name):
                return photo.image.url
        except Exception:
            continue
    return ''


def _store_vehicle_image(vehicle, uploaded_image):
    """Save replacement photos under unique paths to avoid stale cached images."""
    if not uploaded_image or not is_valid_image(uploaded_image):
        return False
    suffix = uploaded_image.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_image.name else 'jpg'
    suffix = ''.join(ch for ch in suffix if ch.isalnum())[:8] or 'jpg'
    vehicle.image.save(f'{uuid4().hex}.{suffix}', uploaded_image, save=False)
    return True


def transportation_list(request):
    """Vehicle list with date-based availability.

    Each vehicle is checked against the customer-selected schedule datetime:
    a vehicle only appears bookable when it is not reserved for that time and
    is not in use / under maintenance.
    """
    default_schedule = timezone.now() + timedelta(hours=3)
    schedule = _parse_datetime(request.GET.get('schedule'), default_schedule)
    search_query = (request.GET.get('q') or '').strip()
    agencies = Agency.objects.prefetch_related('photos', 'vehicles', 'drivers').filter(status=Agency.Status.ACTIVE)
    if search_query:
        agencies = agencies.filter(
            Q(name__icontains=search_query) | Q(address__icontains=search_query)
            | Q(barangay__icontains=search_query) | Q(municipality__icontains=search_query)
            | Q(province__icontains=search_query) | Q(country__icontains=search_query)
        )
    result = []
    for agency in agencies:
        result.append({'agency': agency, 'vehicles': list(agency.vehicles.all())})
    return render(request, 'transportation/list.html', {
        'agencies': result,
        'schedule': schedule,
        'search_query': search_query,
        'transportation_owner': request.user.is_authenticated and 'TRANSPORTATION_OWNER' in effective_role_keys(request.user),
    })


def agency_vehicles(request, agency_id):
    """Choose a travel agency first (step 1), then pick a car (step 2)."""
    default_schedule = timezone.now() + timedelta(hours=3)
    schedule = _parse_datetime(request.GET.get('schedule'), default_schedule)
    agency = get_object_or_404(
        Agency.objects.prefetch_related('photos', 'vehicles', 'drivers'), pk=agency_id)
    vehicles = []
    for vehicle in agency.vehicles.all():
        available = (vehicle.status == Vehicle.VehicleStatus.AVAILABLE
                     and not _vehicle_conflict(vehicle, schedule))
        vehicles.append({
            'vehicle': vehicle,
            'available': available,
            'photo_url': _vehicle_photo_url(agency, vehicle),
        })
    return render(request, 'transportation/agency_vehicles.html', {
        'agency': agency,
        'vehicles': vehicles,
        'schedule': schedule,
    })


@manager_required
def manage(request):
    agencies = scope_agencies(
        request,
        Agency.objects.prefetch_related('photos', 'vehicles', 'drivers').all(),
    )
    return render(request, 'transportation/manage.html', {
        'agencies': agencies,
        'transportation_owner': 'TRANSPORTATION_OWNER' in effective_role_keys(request.user),
    })


@manager_required
def add_agency(request):
    # Creating an agency is a platform-side deed: a slot-holder may manage only
    # the agencies they were assigned, never create a brand new one.
    if assigned_agency_ids(request) is not None:
        raise PermissionDenied(
            'You can only manage the transport agencies you are assigned to.')
    if request.method == 'POST':
        agency = Agency.objects.create(
            name=request.POST.get('name'),
            contact_number=request.POST.get('contact_number', ''),
            email=request.POST.get('email', ''),
            address=request.POST.get('address', ''),
            country=request.POST.get('country', ''),
            barangay=request.POST.get('barangay', ''),
            municipality=request.POST.get('municipality', ''),
            province=request.POST.get('province', ''),
            operating_hours=request.POST.get('operating_hours', ''),
            status=request.POST.get('status', Agency.Status.ACTIVE),
        )
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for index, image in enumerate(photos):
            AgencyPhoto.objects.create(agency=agency, image=image, is_primary=(index == 0))
        log_activity(request.user, "Created transport agency", agency.name)
        messages.success(request, f"Agency '{agency.name}' created.")
        return redirect('transportation:manage')
    return render(request, 'transportation/agency_form.html', {'agency': None})


@manager_required
def update_agency(request, agency_id):
    agency = get_object_or_404(
        scope_agencies(request, Agency.objects.prefetch_related('photos')), pk=agency_id)
    if request.method == 'POST':
        for field in ('name', 'contact_number', 'email', 'address', 'country', 'barangay', 'municipality', 'province',
                      'operating_hours', 'status'):
            setattr(agency, field, request.POST.get(field) or getattr(agency, field))
        agency.save()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        if photos:
            # The first newly uploaded image becomes the cover photo. Existing
            # primary photos remain in the gallery but no longer mask it.
            agency.photos.filter(is_primary=True).update(is_primary=False)
            for index, image in enumerate(photos):
                AgencyPhoto.objects.create(agency=agency, image=image, is_primary=(index == 0))
        for photo in agency.photos.filter(pk__in=request.POST.getlist('delete_photos')):
            delete_image_record(photo)
        if agency.photos.exists() and not agency.photos.filter(is_primary=True).exists():
            first = agency.photos.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        log_activity(request.user, "Updated transport agency", agency.name)
        messages.success(request, "Agency updated.")
        return redirect('transportation:manage')
    return render(request, 'transportation/agency_form.html', {'agency': agency})


@manager_required
def add_vehicle(request, agency_id):
    agency = get_object_or_404(scope_agencies(request, Agency.objects.all()), pk=agency_id)
    if request.method == 'POST':
        vehicle = Vehicle(
            agency=agency,
            vehicle_type=request.POST.get('vehicle_type', Vehicle.VehicleType.VAN),
            vehicle_name=request.POST.get('vehicle_name', ''),
            plate_number=request.POST.get('plate_number'),
            capacity=int(request.POST.get('capacity') or 1),
            rate_per_km=request.POST.get('rate_per_km') or 0,
            status=request.POST.get('status', Vehicle.VehicleStatus.AVAILABLE),
        )
        uploaded_image = request.FILES.get('image')
        if uploaded_image:
            _store_vehicle_image(vehicle, uploaded_image)
        elif request.POST.get('remove_image') and vehicle.image:
            vehicle.image.delete(save=False)
        vehicle.save()
        messages.success(request, "Vehicle added.")
        return redirect('transportation:update_agency', agency.id)
    return render(request, 'transportation/vehicle_form.html', {'agency': agency, 'vehicle': None})


@manager_required
def update_vehicle(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
    allowed = assigned_agency_ids(request)
    if allowed is not None and vehicle.agency_id not in allowed:
        raise PermissionDenied(
            'You can only manage the vehicles of the agencies you are assigned to.')
    if request.method == 'POST':
        for field in ('vehicle_type', 'vehicle_name', 'plate_number', 'capacity', 'rate_per_km', 'status'):
            value = request.POST.get(field)
            if field == 'capacity':
                value = int(value or vehicle.capacity)
            setattr(vehicle, field, value or getattr(vehicle, field))
        _store_vehicle_image(vehicle, request.FILES.get('image'))
        vehicle.save()
        messages.success(request, "Vehicle updated.")
        return redirect('transportation:update_agency', vehicle.agency_id)
    return render(request, 'transportation/vehicle_form.html', {'agency': vehicle.agency, 'vehicle': vehicle})


@manager_required
def add_driver(request, agency_id):
    agency = get_object_or_404(scope_agencies(request, Agency.objects.all()), pk=agency_id)
    if request.method == 'POST':
        Driver.objects.create(
            agency=agency,
            full_name=request.POST.get('full_name'),
            license_number=request.POST.get('license_number'),
            contact_number=request.POST.get('contact_number', ''),
            status=request.POST.get('status', Driver.Status.ACTIVE),
        )
        messages.success(request, "Driver added.")
        return redirect('transportation:update_agency', agency.id)
    return render(request, 'transportation/driver_form.html', {'agency': agency, 'driver': None})


@manager_required
def update_driver(request, driver_id):
    driver = get_object_or_404(Driver, pk=driver_id)
    allowed = assigned_agency_ids(request)
    if allowed is not None and driver.agency_id not in allowed:
        raise PermissionDenied(
            'You can only manage the drivers of the agencies you are assigned to.')
    if request.method == 'POST':
        for field in ('full_name', 'license_number', 'contact_number', 'status'):
            setattr(driver, field, request.POST.get(field) or getattr(driver, field))
        driver.save()
        messages.success(request, "Driver updated.")
        return redirect('transportation:update_agency', driver.agency_id)
    return render(request, 'transportation/driver_form.html', {'agency': driver.agency, 'driver': driver})


def _booking_is_embedded(request):
    """True when the booking page is being loaded inside the dashboard modal."""
    return request.GET.get('embed') == '1' or request.POST.get('embed') == '1'


def _book_context(request, vehicle, drivers, default_schedule, **extra):
    context = {
        'vehicle': vehicle,
        'drivers': drivers,
        'default_schedule': default_schedule,
        'rate_per_km': vehicle.rate_per_km,
        'photo_url': _vehicle_photo_url(vehicle.agency, vehicle),
        'embed': _booking_is_embedded(request),
    }
    context.update(extra)
    return context


@xframe_options_sameorigin
@login_required
@student_booking_required
def book_vehicle(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle.objects.select_related('agency').prefetch_related('agency__drivers'), pk=vehicle_id)
    if not resource_is_bookable(vehicle):
        messages.error(request, "This vehicle is not currently available for booking.")
        return redirect('transportation:list')
    default_schedule = _parse_datetime(request.GET.get('schedule'), timezone.now() + timedelta(hours=3))
    drivers = vehicle.agency.drivers.filter(status=Driver.Status.ACTIVE)

    if request.method == 'POST':
        when = _parse_datetime(request.POST.get('schedule'), default_schedule)
        try:
            distance = Decimal(request.POST.get('distance_km') or 0)
        except (InvalidOperation, TypeError, ValueError):
            distance = Decimal(0)
        try:
            duration = int(request.POST.get('duration_hours') or 3)
        except (TypeError, ValueError):
            duration = 3
        try:
            passenger_count = int(request.POST.get('passengers') or 1)
        except (TypeError, ValueError):
            passenger_count = 1

        # Re-validate every rule server-side before touching the database so a
        # forged or stale form can never create an overlapping/invalid booking.
        error = None
        if _vehicle_conflict(vehicle, when, duration):
            error = ("This vehicle is already reserved for the selected schedule. "
                     "Pick a different date or choose another vehicle.")
        elif distance <= 0:
            error = "Enter the travel distance in kilometres (greater than 0)."
        elif duration < 1:
            error = "Rental duration must be at least 1 hour."
        elif passenger_count < 1 or passenger_count > vehicle.capacity:
            error = f"Passenger count must be between 1 and {vehicle.capacity} for this vehicle."

        if error:
            estimated_total = None
            if distance > 0:
                estimated_total = bill_items_total(
                    compute_transport_bill(vehicle.rate_per_km, distance))
            return render(request, 'transportation/book.html', _book_context(
                request, vehicle, drivers, default_schedule,
                booking_error=error,
                form_data=request.POST,
                form_schedule=when,
                estimated_total=estimated_total,
            ))

        items = compute_transport_bill(vehicle.rate_per_km, distance)
        total = bill_items_total(items)

        booking = Booking.objects.create(
            customer=request.user,
            vehicle=vehicle,
            driver_id=request.POST.get('driver') or None,
            pickup_location=request.POST.get('pickup_location'),
            drop_off_location=request.POST.get('drop_off_location'),
            distance_km=distance,
            schedule=when,
            duration_hours=duration,
            passengers=passenger_count,
            special_requests=request.POST.get('special_requests', ''),
            payer_name=request.POST.get('payer_name', ''),
            payer_contact=request.POST.get('payer_contact', ''),
            status=Booking.Status.PENDING,
        )
        bill = create_bill(service='transport', customer=request.user, items=items, booking=booking)
        booking.total_bill = total
        booking.save(update_fields=['total_bill'])

        from simulation.completion import complete_guest_booking
        from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

        complete_guest_booking(
            request.user,
            task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
            booking_reference=booking.booking_reference,
        )

        if request.POST.get('book_and_add') == '1':
            try:
                add_establishment_booking(request, booking)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('transportation:booking_detail', booking.id)
            messages.success(request, f'Added to this establishment booking: {booking.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':


            add_booking_to_cart(request, booking)


            messages.success(request, f"Added to your Trip Cart: {booking.booking_reference}")


            return redirect('transactions:cart')



        passenger_summary = f"{passenger_count} passenger" if passenger_count == 1 else f"{passenger_count} passengers"
        order = create_single_booking_order(
            request=request,
            booking=booking,
            service='transport',
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=(f"{vehicle.label} · {booking.pickup_location} → {booking.drop_off_location} · {passenger_summary}"),
            items=items,
            pay_later=request.POST.get('pay_later') == 'on',
        )
        booking.refresh_from_db()

        if _booking_is_embedded(request):
            # Inside the modal, confirm in place so the parent page can refresh
            # the vehicle list only after the booking really succeeded.
            return render(request, 'transportation/book.html', _book_context(
                request, vehicle, drivers, default_schedule,
                booking_success=True,
                order=order,
                booking=booking,
                passenger_summary=passenger_summary,
                total=total,
            ))

        if request.POST.get('pay_later') == 'on':
            messages.success(request, f"Transport order created: {order.order_reference} · {passenger_summary} under ONE transaction (pending payment).")
        else:
            messages.success(request, f"Transport booked successfully: {order.order_reference} · {passenger_summary} under ONE transaction.")
        return redirect('transactions:order_detail', order.id)

    booking_error = None
    if _vehicle_conflict(vehicle, default_schedule):
        booking_error = "This vehicle is already reserved for the selected schedule. Pick a different date or choose another vehicle."
    return render(request, 'transportation/book.html', _book_context(
        request, vehicle, drivers, default_schedule, booking_error=booking_error))


@manager_required
def bookings(request):
    status = request.GET.get('status', '')
    qs = scope_bookings(
        request,
        Booking.objects.select_related('customer', 'vehicle__agency', 'driver'),
    )
    if status:
        qs = qs.filter(status=status)
    return render(request, 'transportation/bookings.html', {'bookings': qs, 'status': status})


@xframe_options_sameorigin
@login_required
def booking_detail(request, booking_id):
    from accounts.roles import can_manage_booking
    from transactions.models import Bill, Payment

    booking = get_object_or_404(Booking.objects.select_related('customer', 'vehicle__agency', 'driver'), pk=booking_id)
    if booking.customer_id != request.user.id and not can_manage_booking(request.user, 'transportation'):
        messages.warning(request, "You cannot view this booking.")
        return redirect('transportation:list')

    # A role holder may only reach the bookings of the agencies they were
    # assigned; an otherwise-allowed id in the URL must not reach another
    # agency's booking. Booking-as-customer stays open, since a student can
    # legitimately book a vehicle they are not assigned to manage.
    allowed = assigned_agency_ids(request)
    if (allowed is not None
            and booking.customer_id != request.user.id
            and booking.vehicle.agency_id not in allowed):
        raise PermissionDenied(
            'You can only manage bookings for the transport agencies you are assigned to.')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()
    can_manage = bool(can_manage_booking(request.user, 'transportation'))

    from accounts.roles import can_process_booking_checkin
    can_process_checkin = can_process_booking_checkin(request.user, 'transportation')

    from accounts.roles import is_reservation_officer
    reservation_officer = is_reservation_officer(request.user, 'transportation')

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')
        if can_process_checkin and action not in {'checkin', 'checkout'}:
            raise PermissionDenied('Transport Front Desk may only process pickup and drop-off.')
        if reservation_officer and action != 'confirm':
            raise PermissionDenied('Reservation Officers may only confirm payment-verified reservations.')
        if action in {'checkin', 'checkout'} and not can_process_checkin:
            raise PermissionDenied('Reservation Officers cannot process check-in or check-out.')
        if action == 'confirm':
            if not reservation_officer:
                raise PermissionDenied('Only the Transport Reservation Officer may confirm a payment-verified booking.')
            confirm_booking(booking, request.user)
            if getattr(booking, 'payment_review_pending', False):
                messages.warning(request, 'Waiting for the Billing Officer to verify full payment before confirmation.')
            else:
                booking.vehicle.status = 'IN_USE'
                booking.vehicle.save(update_fields=['status'])
        elif action == 'decline':
            decline_booking(booking, request.user)
        elif action == 'checkin':
            booking.status = Booking.Status.CHECKED_IN
            booking.save(update_fields=['status'])
            log_activity(request.user, "Pickup confirmed", str(booking.pk))
        elif action == 'checkout':
            booking.status = Booking.Status.CHECKED_OUT
            booking.save(update_fields=['status'])
            booking.vehicle.status = 'AVAILABLE'
            booking.vehicle.save(update_fields=['status'])
            log_activity(request.user, "Drop-off completed", str(booking.pk))
        elif action == 'modify':
            booking.schedule = _parse_datetime(request.POST.get('schedule'), booking.schedule)
            booking.pickup_location = request.POST.get('pickup_location', booking.pickup_location)
            booking.drop_off_location = request.POST.get('drop_off_location', booking.drop_off_location)
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            booking.status = Booking.Status.MODIFIED
            booking.save()
        elif action == 'cancel':
            cancel_booking(booking, request.user)
            booking.vehicle.status = 'AVAILABLE'
            booking.vehicle.save(update_fields=['status'])
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='transport',
                bill=bill,
            )
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('transportation:booking_detail', booking.id)

    return render(request, 'transportation/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'is_reservation_officer': reservation_officer,
        'can_manage_lifecycle': can_manage and not reservation_officer and not can_process_checkin,
        'can_print_ticket': booking.customer_id == request.user.id and not request.user.is_staff and not can_manage,
        'can_process_checkin': can_process_checkin,
    })


@login_required
def ticket_detail(request, booking_id):
    from atrue_core.etickets import eticket_detail
    return eticket_detail(request, 'transportation', booking_id)


@login_required
def ticket_pdf(request, booking_id):
    from atrue_core.etickets import eticket_pdf
    return eticket_pdf(request, 'transportation', booking_id)


