from datetime import date, time

from transactions.cart import add_booking_to_cart
from transactions.establishment_flow import add_booking as add_establishment_booking
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.establishment_deletion import delete_booking_history, delete_linked_establishment_history
from atrue_core.image_utils import delete_image_record, is_valid_image
from atrue_core.slugs import get_object_by_slug_or_404
from atrue_core.services import (
    _load,
    bill_for_booking,
    cancel_booking,
    checkout,
    compute_package_bill,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    record_payment,
)
from django.core.exceptions import PermissionDenied
from accounts.roles import effective_role_keys
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from atrue_core.search_catalog import render_search_page

from .models import Booking, BookingGuest, TourPackage, TourPackagePhoto
from .scope import (
    FRONTDESK_ROLES,
    GUEST_ROLES,
    PACKAGE_MANAGER_ROLES,
    RESERVATION_ROLES,
    assigned_operator_for_write,
    assigned_package_ids,
    is_platform_operator,
    may_manage_package,
    may_book_package,
    may_process_frontdesk,
    may_review_booking,
    scope_bookings,
    scope_packages,
)


def _parse_date(value, fallback):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback


def _parse_time(value, fallback=None):
    try:
        return time.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback


def _save_guests(booking, request):
    """Persist other-traveler names and their emergency contacts from the form."""
    names = request.POST.getlist('guest_full_name')
    contacts = request.POST.getlist('guest_emergency_contact_name')
    numbers = request.POST.getlist('guest_emergency_contact_number')
    relationships = request.POST.getlist('guest_emergency_contact_relationship')
    for i, name in enumerate(names):
        name = (name or '').strip()
        if not name:
            continue
        BookingGuest.objects.create(
            booking=booking,
            full_name=name,
            emergency_contact_name=_at(contacts, i),
            emergency_contact_number=_at(numbers, i),
            emergency_contact_relationship=_at(relationships, i),
        )


def _at(values, index):
    try:
        return (values[index] or '').strip()
    except (IndexError, TypeError):
        return ''


def _components_bookable(package):
    from airlines.models import Aircraft

    hotels = all(h.status == 'ACTIVE' for h in package.included_hotels.all())
    resorts = all(r.status == 'ACTIVE' for r in package.included_resorts.all())
    flights = all(f.status in ('SCHEDULED', 'DELAYED')
                  and (f.aircraft is None
                       or f.aircraft.status not in (Aircraft.Status.MAINTENANCE, Aircraft.Status.INACTIVE))
                  for f in package.included_flights.all())
    activities = all(a.bookable for a in package.included_activities.all())
    return hotels and resorts and flights and activities


def package_list(request):
    packages = TourPackage.objects.filter(
        status=TourPackage.Status.ACTIVE,
    ).prefetch_related('photos')
    return render_search_page(request, 'package', packages)


def package_detail(request, package_id):
    """View a single tour package (FR-025 VIEW Package)."""
    package = get_object_by_slug_or_404(
        TourPackage.objects.prefetch_related('photos'), package_id)
    is_manager = may_manage_package(request, package.pk)
    if not package.bookable and not is_manager:
        messages.error(request, "This package is currently unavailable.")
        return redirect('tour_package:list')
    return render(request, 'tour_package/detail.html', {
        'package': package,
        'is_manager': is_manager,
        'can_book': may_book_package(request, package.pk),
    })


@manager_required
def manage(request):
    if not (may_manage_package(request) or is_platform_operator(request.user)):
        raise PermissionDenied('Only an assigned Tour Package Manager may manage package details.')
    packages = scope_packages(
        request, TourPackage.objects.prefetch_related('photos').all(), PACKAGE_MANAGER_ROLES)
    return render(request, 'tour_package/manage.html', {
        'packages': packages,
        'can_create_package': is_platform_operator(request.user),
        'package_owner': bool(set(effective_role_keys(request.user)).intersection({
                'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER', 'TRAVEL_AGENCY_OWNER'
            })),
        'can_delete_package': is_platform_operator(request.user),
    })


def _save_package(request, instance=None):
    from activities.models import Activity
    from airlines.models import Flight
    from hotels.models import Hotel
    from restaurants.models import Restaurant
    from resorts.models import Resort
    from transportation.models import Agency

    data = {
        'name': request.POST.get('name'),
        'description': request.POST.get('description', ''),
        'destination_name': request.POST.get('destination_name', ''),
        'destination_country': request.POST.get('destination_country', ''),
        'destination_province': request.POST.get('destination_province', ''),
        'destination_city': request.POST.get('destination_city', ''),
        'duration_days': int(request.POST.get('duration_days') or 1),
        'base_price': request.POST.get('base_price') or 0,
        'discount': request.POST.get('discount') or 0,
        'price': request.POST.get('price') or request.POST.get('base_price') or 0,
        'extra_person_rate': request.POST.get('extra_person_rate') or 0,
        'included_headcount': int(request.POST.get('included_headcount') or 1),
        'included_adults': int(request.POST.get('included_adults') or 1),
        'included_children': int(request.POST.get('included_children') or 0),
        'validity_start_date': _parse_date(request.POST.get('validity_start_date'), date.today()),
        'validity_end_date': _parse_date(request.POST.get('validity_end_date'), date.today()),
        'inclusions': request.POST.get('inclusions', ''),
        'exclusions': request.POST.get('exclusions', ''),
        'included_tour_guide': request.POST.get('included_tour_guide') == 'on',
        'included_other_services': request.POST.get('included_other_services', ''),
        'terms_and_conditions': request.POST.get('terms_and_conditions', ''),
        'cancellation_policy': request.POST.get('cancellation_policy', ''),
        'status': request.POST.get('status', 'ACTIVE'),
    }
    hotel_ids = [int(v) for v in request.POST.getlist('hotels')]
    resort_ids = [int(v) for v in request.POST.getlist('resorts')]
    flight_ids = [int(v) for v in request.POST.getlist('flights')]
    activity_ids = [int(v) for v in request.POST.getlist('activities')]
    restaurant_ids = [int(v) for v in request.POST.getlist('restaurants')]
    transport_ids = [int(v) for v in request.POST.getlist('transport')]

    if instance:
        for field, value in data.items():
            setattr(instance, field, value)
        instance.save()
        package = instance
    else:
        package = TourPackage.objects.create(
            establishment=assigned_operator_for_write(request),
            **data,
        )

    if 'hotels' in request.POST:
        package.included_hotels.set(Hotel.objects.filter(pk__in=hotel_ids))
    if 'resorts' in request.POST:
        package.included_resorts.set(Resort.objects.filter(pk__in=resort_ids))
    if 'flights' in request.POST:
        package.included_flights.set(Flight.objects.filter(pk__in=flight_ids))
    if 'activities' in request.POST:
        package.included_activities.set(Activity.objects.filter(pk__in=activity_ids))
    if 'restaurants' in request.POST:
        package.included_restaurants.set(Restaurant.objects.filter(pk__in=restaurant_ids))
    if 'transport' in request.POST:
        package.included_transport.set(Agency.objects.filter(pk__in=transport_ids))
    images = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
    for image in images:
        TourPackagePhoto.objects.create(package=package, image=image, is_primary=not package.photos.exists())
    for photo in package.photos.filter(pk__in=request.POST.getlist('delete_photos')):
        delete_image_record(photo)
    if package.photos.exists() and not package.photos.filter(is_primary=True).exists():
        first = package.photos.first()
        first.is_primary = True
        first.save(update_fields=['is_primary'])
    return package


@manager_required
def add_package(request):
    package_owner = bool(set(effective_role_keys(request.user)).intersection({
            'TOUR_PACKAGE_OWNER', 'TOUR_OPERATOR_OWNER', 'TRAVEL_AGENCY_OWNER'
        }))
    if not is_platform_operator(request.user) and not package_owner:
        raise PermissionDenied('Only a platform administrator or instructor can create tour packages.')
    if request.method == 'POST':
        package = _save_package(request)
        log_activity(request.user, "Created tour package", package.name)
        messages.success(request, f"Package '{package.name}' created.")
        return redirect('tour_package:manage')
    return render(request, 'tour_package/form.html', _component_context(None))


@manager_required
def update_package(request, package_id):
    package = get_object_or_404(
        scope_packages(request, TourPackage.objects.all(), PACKAGE_MANAGER_ROLES),
        pk=package_id,
    )
    if not may_manage_package(request, package.pk):
        raise PermissionDenied('Only an assigned Tour Package Manager may update this package.')
    if request.method == 'POST':
        _save_package(request, instance=package)
        log_activity(request.user, "Updated tour package", package.name)
        messages.success(request, "Package updated.")
        return redirect('tour_package:manage')
    if request.GET.get('modal') == '1':
        return render(request, 'tour_package/_edit_modal.html', _component_context(package))
    return render(request, 'tour_package/form.html', _component_context(package))


@manager_required
def delete_package(request, package_id):
    if request.method != 'POST':
        messages.warning(request, 'Invalid request.')
        return redirect('tour_package:manage')
    package = get_object_or_404(
        scope_packages(request, TourPackage.objects.all(), PACKAGE_MANAGER_ROLES), pk=package_id)
    if not may_manage_package(request, package.pk):
        raise PermissionDenied('Only an assigned Tour Package Manager may delete this package.')
    name = package.name
    try:
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            delete_booking_history(Booking.objects.filter(package=package))
            delete_linked_establishment_history(package)
            package.delete()
    except ProtectedError:
        messages.error(request, f"Tour package '{name}' is linked to existing records and cannot be deleted. Set its status to Inactive instead.")
        return redirect('tour_package:manage')
    log_activity(request.user, 'Deleted tour package', name)
    messages.success(request, f"Tour package '{name}' and its booking history deleted.")
    return redirect('tour_package:manage')


def _component_context(package=None):
    from activities.models import Activity
    from airlines.models import Flight
    from hotels.models import Hotel
    from restaurants.models import Restaurant
    from resorts.models import Resort
    from transportation.models import Agency

    context = {
        'package': package,
        'hotels': Hotel.objects.filter(status=Hotel.Status.ACTIVE),
        'resorts': Resort.objects.filter(status=Resort.Status.ACTIVE),
        'flights': Flight.objects.select_related('aircraft').all(),
        'activities': Activity.objects.select_related('provider').filter(status=Activity.Status.ACTIVE),
        'restaurants': Restaurant.objects.filter(status=Restaurant.Status.ACTIVE),
        'transport': Agency.objects.all(),
    }
    if package:
        context['selected_hotels'] = list(package.included_hotels.values_list('id', flat=True))
        context['selected_resorts'] = list(package.included_resorts.values_list('id', flat=True))
        context['selected_flights'] = list(package.included_flights.values_list('id', flat=True))
        context['selected_activities'] = list(package.included_activities.values_list('id', flat=True))
        context['selected_restaurants'] = list(package.included_restaurants.values_list('id', flat=True))
        context['selected_transport'] = list(package.included_transport.values_list('id', flat=True))
    return context


@login_required
@student_booking_required
def book_package(request, package_id):
    package = get_object_or_404(
        scope_packages(request, TourPackage.objects.all(), GUEST_ROLES), pk=package_id)
    if not may_book_package(request, package.pk):
        raise PermissionDenied('Only a Tour Package Guest assigned to this package may book it.')
    if request.method == 'POST':
        travel_date = _parse_date(request.POST.get('travel_date'), date.today())
        if not package.valid_on(travel_date):
            messages.error(request, "This package is not valid on the chosen travel date (BR-079).")
            return redirect('tour_package:list')
        if not _components_bookable(package):
            messages.error(request, "A package component is currently unavailable (BR-073 to BR-075).")
            return redirect('tour_package:list')

        travelers = int(request.POST.get('travelers') or 1)
        adults = int(request.POST.get('adults') or 0)
        children = int(request.POST.get('children') or 0)
        if not adults and not children:
            adults = travelers
        items, extra_heads, adjustment = compute_package_bill(
            package, travelers, package.included_headcount, package.extra_person_rate)
        total = _load(package.price) + adjustment

        booking = Booking.objects.create(
            customer=request.user,
            package=package,
            travel_date=travel_date,
            start_time=_parse_time(request.POST.get('start_time'), None),
            end_time=_parse_time(request.POST.get('end_time'), None),
            number_of_travelers=travelers,
            number_of_adults=adults,
            number_of_children=children,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            special_requests=request.POST.get('special_requests', ''),
            payer_name=request.POST.get('payer_name', ''),
            payer_contact=request.POST.get('payer_contact', ''),
            status=Booking.Status.PENDING,
        )
        bill = create_bill(service='tour_package', customer=request.user, items=items, booking=booking)
        booking.total_bill = total
        booking.save(update_fields=['total_bill'])
        _save_guests(booking, request)

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
                return redirect('tour_package:booking_detail', booking.id)
            messages.success(request, f'Added to this establishment booking: {booking.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':


            add_booking_to_cart(request, booking)


            messages.success(request, f"Added to your Trip Cart: {booking.booking_reference}")


            return redirect('transactions:cart')



        if request.POST.get('pay_later') == 'on':
            messages.success(request, f"Package booking saved! Reference: {booking.booking_reference} (pending payment)")
            return redirect('tour_package:booking_detail', booking.id)
        checkout(
            user=request.user,
            service='tour_package',
            booking=booking,
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=f"Tour package booking {booking.booking_reference}",
            items=items,
            bill=bill,
        )
        booking.refresh_from_db()
        booking.amount_paid = total
        booking.balance_due = 0
        booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, f"Package booked! Reference: {booking.booking_reference}")
        return redirect('tour_package:booking_detail', booking.id)
    return render(request, 'tour_package/book.html', {'package': package, 'today': date.today()})


@manager_required
def bookings(request):
    if not (may_review_booking(request) or is_platform_operator(request.user)):
        raise PermissionDenied('Only an assigned reservation officer may review package bookings.')
    status = request.GET.get('status', '')
    qs = scope_bookings(
        request,
        Booking.objects.select_related('customer', 'package').prefetch_related('guests').all(),
        RESERVATION_ROLES,
    )
    if status:
        qs = qs.filter(status=status)
    return render(request, 'tour_package/bookings.html', {'bookings': qs, 'status': status})


@login_required
def booking_detail(request, booking_id):
    from transactions.models import Bill

    staff_guest_roles = RESERVATION_ROLES | FRONTDESK_ROLES | GUEST_ROLES
    booking = get_object_or_404(
        scope_bookings(request, Booking.objects.select_related('customer', 'package').prefetch_related('guests'),
                       staff_guest_roles),
        pk=booking_id)
    is_platform = is_platform_operator(request.user)
    is_reservation = may_review_booking(request, booking.package_id)
    is_frontdesk = may_process_frontdesk(request, booking.package_id)
    is_owner = (booking.customer_id == request.user.id
                and may_book_package(request, booking.package_id))
    if not (is_platform or is_reservation or is_frontdesk or is_owner):
        messages.warning(request, "You cannot view this booking.")
        return redirect('tour_package:list')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Bill.objects.none()
    can_manage = is_platform

    if request.method == 'POST':
        action = request.POST.get('action')
        allowed_actions = (
            {'confirm', 'decline', 'attend', 'complete', 'cancel', 'modify', 'pay'} if is_platform else
            {'confirm', 'decline'} if is_reservation else
            {'attend', 'complete'} if is_frontdesk else set()
        )
        if action not in allowed_actions:
            raise PermissionDenied('Your Tour Package role does not permit this booking action.')
        if action == 'confirm':
            confirm_booking(booking, request.user)
            if getattr(booking, 'payment_review_pending', False):
                messages.warning(request, 'Waiting for the Billing Officer to verify full payment before confirmation.')
        elif action == 'decline':
            decline_booking(booking, request.user)
        elif action == 'attend':
            booking.status = Booking.Status.CHECKED_IN
            booking.save(update_fields=['status'])
        elif action == 'complete':
            booking.status = Booking.Status.COMPLETED
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['status', 'amount_paid', 'balance_due'])
        elif action == 'modify':
            booking.travel_date = _parse_date(request.POST.get('travel_date'), booking.travel_date)
            booking.number_of_travelers = int(request.POST.get('travelers') or booking.number_of_travelers)
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            items, extra_heads, adjustment = compute_package_bill(
                booking.package, booking.number_of_travelers,
                booking.package.included_headcount, booking.package.extra_person_rate)
            booking.total_bill = _load(booking.package.price) + adjustment
            booking.status = Booking.Status.MODIFIED
            booking.guests.all().delete()
            _save_guests(booking, request)
            booking.save()
            if bill is not None:
                bill.calculate(items)
            else:
                create_bill(service='tour_package', customer=booking.customer, items=items, booking=booking)
        elif action == 'cancel':
            cancel_booking(booking, request.user)
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='tour_package',
                bill=bill,
            )
            bill.refresh_from_db()
            booking.amount_paid = bill.amount_paid
            booking.balance_due = bill.balance_due
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('tour_package:booking_detail', booking.id)

    return render(request, 'tour_package/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'can_review': is_reservation,
        'can_frontdesk': is_frontdesk,
    })


@login_required
def ticket_detail(request, booking_id):
    from atrue_core.etickets import eticket_detail
    ticket_roles = GUEST_ROLES | RESERVATION_ROLES | FRONTDESK_ROLES
    get_object_or_404(scope_bookings(request, Booking.objects.all(), ticket_roles), pk=booking_id)
    return eticket_detail(request, 'tour_package', booking_id)


@login_required
def ticket_pdf(request, booking_id):
    from atrue_core.etickets import eticket_pdf
    ticket_roles = GUEST_ROLES | RESERVATION_ROLES | FRONTDESK_ROLES
    get_object_or_404(scope_bookings(request, Booking.objects.all(), ticket_roles), pk=booking_id)
    return eticket_pdf(request, 'tour_package', booking_id)


# ---------------------------------------------------------------------------
# Shared establishment flow (atrue_core.establishment_flow)
# ---------------------------------------------------------------------------


@login_required
@student_booking_required
def package_flow_select(request, package_id):
    """Choose the package, add traveller details and confirm in one page."""
    from atrue_core.establishment_flow import handle_flow

    get_object_or_404(scope_packages(request, TourPackage.objects.all(), GUEST_ROLES), pk=package_id)
    if not may_book_package(request, package_id):
        raise PermissionDenied('Only an assigned Tour Package Guest may book a package.')
    return handle_flow(request, 'package', package_id)


@manager_required
def operate(request):
    """Run the assigned tour package on the day: attend and complete its
    bookings and keep the package's operational status current (operator)."""
    if not (may_process_frontdesk(request) or is_platform_operator(request.user)):
        raise PermissionDenied('Only assigned Tour Package frontdesk staff may operate package bookings.')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_status' and not is_platform_operator(request.user):
            raise PermissionDenied('Frontdesk staff cannot change package availability.')
        package = get_object_or_404(
            scope_packages(
                request,
                TourPackage.objects.prefetch_related('photos').all(),
                FRONTDESK_ROLES,
            ),
            pk=request.POST.get('package_id'),
        )
        booking = None
        if action in {'attend', 'complete'}:
            booking = get_object_or_404(
                scope_bookings(
                    request,
                    Booking.objects.select_related('customer').prefetch_related('guests').all(),
                    FRONTDESK_ROLES,
                ),
                pk=request.POST.get('booking_id'),
            )
            if booking.package_id != package.pk:
                raise PermissionDenied('The booking does not belong to the selected tour package.')
        if action == 'attend':
            booking.status = Booking.Status.CHECKED_IN
            booking.save(update_fields=['status'])
            log_activity(request.user, "Package booking attended", str(booking.pk))
        elif action == 'complete':
            bill = bill_for_booking(booking)
            booking.status = Booking.Status.COMPLETED
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['status', 'amount_paid', 'balance_due'])
            log_activity(request.user, "Package booking completed", str(booking.pk))
        elif action == 'update_status':
            new_status = request.POST.get('status')
            if new_status in {
                TourPackage.Status.ACTIVE,
                TourPackage.Status.UNDER_MAINTENANCE,
                TourPackage.Status.FULLY_BOOKED,
                TourPackage.Status.SUSPENDED,
            }:
                package.status = new_status
                package.save(update_fields=['status'])
                log_activity(request.user, "Updated tour package status", package.name)
        messages.success(request, "Operation completed.")
        return redirect('tour_package:operate')

    packages = scope_packages(
        request,
        TourPackage.objects.prefetch_related('photos').all(),
        FRONTDESK_ROLES,
    )
    bookings = scope_bookings(
        request,
        Booking.objects.select_related('customer').prefetch_related('guests').all(),
        FRONTDESK_ROLES,
    )
    bookings_by_package = {}
    for booking in bookings:
        bookings_by_package.setdefault(booking.package_id, []).append(booking)
    rows = [
        {'package': package, 'bookings': bookings_by_package.get(package.id, [])}
        for package in packages
    ]
    return render(request, 'tour_package/operate.html', {
        'rows': rows,
        'can_update_package_status': is_platform_operator(request.user),
        'status_choices': [
            ('ACTIVE', 'Active'),
            ('UNDER_MAINTENANCE', 'Under Maintenance'),
            ('FULLY_BOOKED', 'Fully Booked'),
            ('SUSPENDED', 'Suspended'),
        ],
    })
