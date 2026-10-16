from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from transactions.cart import add_booking_to_cart
from transactions.establishment_flow import add_booking as add_establishment_booking
from accounts.roles import (
    FULL_ACCESS_TYPES,
    can_manage_booking,
    effective_role_keys,
    owner_role_keys,
)
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.establishment_deletion import delete_booking_history, delete_linked_establishment_history
from atrue_core.image_utils import delete_image_record, is_valid_image
from atrue_core.search_catalog import render_search_page
from atrue_core.slugs import get_object_by_slug_or_404
from atrue_core.services import (
    bill_for_booking,
    cancel_booking,
    checkout,
    create_bill,
    log_activity,
    record_payment,
)
from simulation.models import SimulationRoleAssignment
from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY, task_operation_for

from .models import Reservation, Restaurant, RestaurantPhoto, Table
from .services import (
    DEPOSIT_PER_GUEST,
    RestaurantReservationError,
    confirm_restaurant_reservation,
    create_restaurant_reservation,
    reject_restaurant_reservation,
    table_has_conflict,
)

#: Storefront routes that only display data. A student whose active task
#: belongs to another module keeps read-only access to these - task routing
#: keeps them out of the management pages, not out of browsing. Anything not
#: listed here still has to be in the assignment's ``allowed_routes``.
BROWSE_ONLY_ROUTES = frozenset({
    'list', 'detail', 'table_detail', 'booking_detail', 'ticket', 'ticket_pdf',
})


def _active_task_assignment(request):
    if not request.user.is_authenticated:
        return None
    assignment_id = request.session.get(TASK_ASSIGNMENT_SESSION_KEY)
    if not assignment_id:
        return None
    assignment = (
        SimulationRoleAssignment.objects
        .filter(
            pk=assignment_id,
            student=request.user,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )
        .select_related('establishment')
        .first()
    )
    if assignment is None:
        request.session.pop(TASK_ASSIGNMENT_SESSION_KEY, None)
        return None
    operation = task_operation_for(assignment)
    route_name = getattr(request.resolver_match, 'url_name', None)
    if operation is None or f'restaurants:{route_name}' not in operation['allowed_routes']:
        if route_name in BROWSE_ONLY_ROUTES:
            # Read-only storefront page: the assignment still scopes what is
            # shown, but it does not own the page, so it is not marked active
            # and the management helpers keep their default behaviour.
            return assignment
        raise PermissionDenied(
            'This restaurant page is not allowed for your active assignment.')
    request.active_simulation_assignment = assignment
    return assignment


def _full_restaurant_access(user):
    return bool(
        user.is_staff
        or set(effective_role_keys(user)).intersection(FULL_ACCESS_TYPES)
    )


def _can_confirm_reservation(request):
    assignment = getattr(request, 'active_simulation_assignment', None)
    if assignment is not None:
        return assignment.role == SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER
    if 'RESTAURANT_RESERVATION_OFFICER' in effective_role_keys(request.user):
        return True
    return SimulationRoleAssignment.objects.filter(
        student=request.user,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role=SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER,
        establishment__type='RESTAURANT',
    ).exists()


def _assigned_restaurant_ids(request):
    if _full_restaurant_access(request.user):
        return None
    if request.user.simulation_roles.filter(status='ACTIVE', role='RESTAURANT_OWNER').exists():
        return None
    assignment = getattr(request, 'active_simulation_assignment', None)
    if assignment is not None:
        establishment = assignment.establishment
        if establishment and establishment.type == 'RESTAURANT' and establishment.entity_id:
            return {establishment.entity_id}
        return set()
    return set(
        SimulationRoleAssignment.objects.filter(
            student=request.user,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            role__in=(
                SimulationRoleAssignment.Role.RESTAURANT_MANAGER,
                SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER,
                SimulationRoleAssignment.Role.RESTAURANT_FRONT_DESK,
                SimulationRoleAssignment.Role.RESTAURANT_STAFF,
            ),
            establishment__type='RESTAURANT',
            establishment__entity_id__isnull=False,
        ).values_list('establishment__entity_id', flat=True)
    )


def _require_assigned_restaurant(request, restaurant_id):
    assignment = _active_task_assignment(request)
    if (
        assignment
        and assignment.establishment_id
        and assignment.establishment.type == 'RESTAURANT'
        and assignment.establishment.entity_id != restaurant_id
    ):
        raise PermissionDenied(
            'You are not assigned to this restaurant.')


def _location_parts(value, countries=None):
    """Best-effort split of stored `barangay, municipality/city, province[, country]` text for edit forms.

    A trailing part is treated as the country when it names one GeoNames knows,
    so worldwide restaurant records round-trip through the cascade picker.
    """
    if countries is None:
        from atrue_core.location_hierarchy import _available_countries
        countries = [c['name'] for c in _available_countries()]
    parts = [p.strip() for p in (value or '').split(',') if p.strip()]
    country = ''
    if parts and parts[-1] in countries:
        country = parts.pop()
    if len(parts) >= 3:
        return {'barangay': parts[-3], 'municipality': parts[-2], 'province': parts[-1], 'country': country}
    if len(parts) == 2:
        return {'barangay': '', 'municipality': parts[0], 'province': parts[1], 'country': country}
    if len(parts) == 1:
        return {'barangay': '', 'municipality': parts[0], 'province': '', 'country': country}
    return {'barangay': '', 'municipality': '', 'province': '', 'country': country}

def _compose_location(request, fallback=''):
    province = (request.POST.get('location_province') or '').strip()
    municipality = (request.POST.get('location_municipality') or '').strip()
    barangay = (request.POST.get('location_barangay') or '').strip()
    country = (request.POST.get('location_country') or '').strip()
    if province or municipality or barangay:
        pieces = ([barangay, municipality, province] if barangay
                  else [municipality, province] if province
                  else [municipality])
        if country:
            pieces.append(country)
        return ', '.join(pieces)
    return (request.POST.get('location') or fallback or '').strip()


def _parse_datetime(value, fallback):
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback
    if dt.tzinfo is None:
        return timezone.make_aware(dt)
    return dt.astimezone(timezone.get_current_timezone())


def _parse_date(value, fallback):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback


def _parse_int(value, fallback):
    try:
        return int(value)
    except (ValueError, TypeError):
        return fallback


def _parse_table_cost(value):
    try:
        cost = Decimal((value or '').strip())
        if not cost.is_finite() or cost < 0:
            return None
        return cost.quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def restaurant_list(request):
    restaurants = Restaurant.objects.prefetch_related('tables', 'photos').filter(status=Restaurant.Status.ACTIVE)
    assignment = _active_task_assignment(request)
    establishment = assignment.establishment if assignment else None
    # Only a restaurant assignment narrows the catalogue. An assignment in
    # another module leaves the browse list intact - the student simply gets
    # the read-only storefront, while the management pages stay blocked.
    if establishment and establishment.type == 'RESTAURANT' and establishment.entity_id:
        restaurants = restaurants.filter(pk=establishment.entity_id)
    # Keep every active restaurant in the public catalogue, even before its
    # tables are configured. Newly created restaurants should be visible right
    # away; the detail page can show that no tables have been added yet.
    return render_search_page(request, 'restaurant', restaurants)


@manager_required
def manage(request):
    qs = Restaurant.objects.prefetch_related('tables', 'photos').all()
    restaurant_ids = _assigned_restaurant_ids(request)
    if restaurant_ids is not None:
        qs = qs.filter(pk__in=restaurant_ids)
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    location = (request.GET.get('location') or '').strip()
    cuisine = (request.GET.get('cuisine') or '').strip()
    if q:
        qs = qs.filter(Q(restaurant_id__icontains=q) | Q(name__icontains=q) |
                       Q(contact_number__icontains=q) | Q(email__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if location:
        qs = qs.filter(location__icontains=location)
    if cuisine:
        qs = qs.filter(cuisine_type__icontains=cuisine)
    return render(request, 'restaurants/manage.html', {
        'restaurants': qs,
        'q': q,
        'status': status,
        'location': location,
        'cuisine': cuisine,
        'status_choices': Restaurant.Status.choices,
        'seating_area_choices': Table.SeatingArea.choices,
        'table_status_choices': Table.Status.choices,
        'can_delete': restaurant_ids is None,
    })


@manager_required
def add_restaurant(request):
    if request.method == 'POST':
        cost_per_table = _parse_table_cost(request.POST.get('cost_per_table'))
        if cost_per_table is None:
            messages.error(request, "Enter a valid cost per table (0 or more).")
            return redirect('restaurants:add')
        restaurant = Restaurant.objects.create(
            name=request.POST.get('name'),
            location=_compose_location(request),
            country=request.POST.get('location_country', ''),
            cuisine_type=request.POST.get('cuisine_type', ''),
            contact_number=request.POST.get('contact_number', ''),
            email=request.POST.get('email', ''),
            operating_hours=request.POST.get('operating_hours', ''),
            cost_per_table=cost_per_table,
            status=request.POST.get('status', Restaurant.Status.ACTIVE),
        )
        restaurant.refresh_from_db()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for index, image in enumerate(photos):
            RestaurantPhoto.objects.create(restaurant=restaurant, image=image, is_primary=(index == 0))
        log_activity(request.user, "Created restaurant", f"{restaurant.name} ({restaurant.restaurant_id})")
        messages.success(request, f"Restaurant '{restaurant.name}' created (ID: {restaurant.restaurant_id}).")
        return redirect('restaurants:manage')
    return render(request, 'restaurants/form.html', {
        'restaurant': None,
        'status_choices': Restaurant.Status.choices,
        'location_parts': _location_parts(''),
    })


@manager_required
def update_restaurant(request, restaurant_id):
    restaurant = get_object_or_404(Restaurant, pk=restaurant_id)
    if request.method == 'POST':
        cost_per_table = _parse_table_cost(request.POST.get('cost_per_table'))
        if cost_per_table is None:
            messages.error(request, "Enter a valid cost per table (0 or more).")
            return render(request, 'restaurants/form.html', {
                'restaurant': restaurant,
                'status_choices': Restaurant.Status.choices,
                'location_parts': _location_parts(restaurant.location),
            })
        for field in ('name', 'cuisine_type', 'contact_number',
                      'email', 'operating_hours', 'status'):
            setattr(restaurant, field, request.POST.get(field) or getattr(restaurant, field))
        restaurant.location = _compose_location(request, restaurant.location)
        restaurant.country = request.POST.get('location_country') or restaurant.country
        restaurant.cost_per_table = cost_per_table
        restaurant.save()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for image in photos:
            RestaurantPhoto.objects.create(restaurant=restaurant, image=image, is_primary=not restaurant.photos.exists())
        for photo in restaurant.photos.filter(pk__in=request.POST.getlist('delete_photos')):
            delete_image_record(photo)
        if restaurant.photos.exists() and not restaurant.photos.filter(is_primary=True).exists():
            first = restaurant.photos.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        log_activity(request.user, "Updated restaurant", f"{restaurant.name} ({restaurant.restaurant_id})")
        messages.success(request, "Restaurant updated.")
        if request.POST.get('return_to_detail'):
            return redirect('restaurants:detail', restaurant.slug)
        return redirect('restaurants:manage')
    return render(request, 'restaurants/form.html', {
        'restaurant': restaurant,
        'status_choices': Restaurant.Status.choices,
        'location_parts': _location_parts(restaurant.location),
    })


@manager_required
def delete_restaurant(request, restaurant_id):
    if request.method != 'POST':
        messages.warning(request, 'Invalid request.')
        return redirect('restaurants:manage')
    restaurant_ids = _assigned_restaurant_ids(request)
    qs = Restaurant.objects.all()
    if restaurant_ids is not None:
        qs = qs.filter(pk__in=restaurant_ids)
    restaurant = get_object_or_404(qs, pk=restaurant_id)
    name = restaurant.name
    try:
        with transaction.atomic():
            delete_booking_history(Reservation.objects.filter(table__restaurant=restaurant))
            delete_linked_establishment_history(restaurant)
            restaurant.delete()
    except ProtectedError:
        messages.error(request, f"Restaurant '{name}' is linked to existing records and cannot be deleted. Set its status to Inactive instead.")
        return redirect('restaurants:manage')
    log_activity(request.user, 'Deleted restaurant', name)
    messages.success(request, f"Restaurant '{name}' and its reservation history deleted.")
    return redirect('restaurants:manage')


def restaurant_detail(request, restaurant_id):
    """FR-011 VIEW Restaurant – full detail profile (tables)."""
    restaurant = get_object_by_slug_or_404(
        Restaurant.objects.prefetch_related('tables', 'photos'),
        restaurant_id,
    )
    _require_assigned_restaurant(request, restaurant.pk)
    is_manager = getattr(request.user, 'is_staff', False) or getattr(request.user, 'account_type', None) in ('ADMIN', 'INSTRUCTOR')
    if restaurant.status != Restaurant.Status.ACTIVE and not is_manager:
        messages.error(request, "This restaurant is currently unavailable.")
        return redirect('restaurants:list')
    return render(request, 'restaurants/detail.html', {
        'restaurant': restaurant,
        'is_manager': is_manager,
        'primary_guest': {
            'first_name': (request.user.first_name or request.user.username).strip(),
            'middle_name': getattr(request.user, 'middle_name', '') or '',
            'last_name': request.user.last_name or '',
            'email': request.user.email or '',
            'contact': getattr(request.user, 'contact_number', '') or '',
        },
        'status_choices': Restaurant.Status.choices,
        'seating_area_choices': Table.SeatingArea.choices,
        'table_status_choices': Table.Status.choices,
    })


@manager_required
def add_table(request, restaurant_id):
    restaurant = get_object_or_404(Restaurant, pk=restaurant_id)
    error = None
    if request.method == 'POST':
        table_number = (request.POST.get('table_number') or '').strip()
        if not table_number:
            error = "Table number is required."
        elif Table.objects.filter(restaurant=restaurant, table_number=table_number).exists():
            error = f"Table {table_number} already exists in '{restaurant.name}'. Choose a different table number."
        else:
            table = Table.objects.create(
                restaurant=restaurant,
                table_number=table_number,
                capacity=_parse_int(request.POST.get('capacity'), 2),
                seating_area=request.POST.get('seating_area', Table.SeatingArea.INDOOR),
                status=request.POST.get('status', Table.Status.AVAILABLE),
            )
            log_activity(request.user, "Added restaurant table",
                         f"{table.table_id} (Table {table.table_number}) in {restaurant.name}")
            messages.success(request, f"Table {table.table_number} added (ID: {table.table_id}).")
            if request.POST.get('return_to_manage') or request.GET.get('return_to_manage'):
                return redirect('restaurants:manage')
            if request.POST.get('return_to_detail'):
                return redirect('restaurants:detail', restaurant.slug)
            return redirect('restaurants:update_restaurant', restaurant.id)
    if error and request.POST.get('return_to_manage'):
        messages.error(request, error)
        return redirect('restaurants:manage')
    if error and request.POST.get('return_to_detail'):
        messages.error(request, error)
        return redirect('restaurants:detail', restaurant.slug)
    return render(request, 'restaurants/table_form.html', {
        'restaurant': restaurant, 'table': None, 'error': error,
        'return_to_manage': request.GET.get('return_to_manage') == '1' or request.POST.get('return_to_manage') == '1',
        'seating_area_choices': Table.SeatingArea.choices,
        'status_choices': Table.Status.choices,
    })


@manager_required
def update_table(request, table_id):
    table = get_object_or_404(Table, pk=table_id)
    error = None
    if request.method == 'POST':
        table_number = (request.POST.get('table_number') or table.table_number).strip()
        duplicate = Table.objects.filter(restaurant=table.restaurant, table_number=table_number).exclude(pk=table.pk).exists()
        if duplicate:
            error = f"Table {table_number} already exists in '{table.restaurant.name}'. Choose a different table number."
        else:
            table.table_number = table_number
            table.capacity = _parse_int(request.POST.get('capacity'), table.capacity)
            table.seating_area = request.POST.get('seating_area', table.seating_area)
            table.status = request.POST.get('status', table.status)
            table.save()
            log_activity(request.user, "Updated restaurant table",
                         f"{table.table_id} (Table {table.table_number}) in {table.restaurant.name}")
            messages.success(request, "Table updated.")
            if request.POST.get('return_to_detail'):
                return redirect('restaurants:detail', table.restaurant.slug)
            return redirect('restaurants:update_restaurant', table.restaurant_id)
    if error and request.POST.get('return_to_detail'):
        messages.error(request, error)
        return redirect('restaurants:detail', table.restaurant.slug)
    return render(request, 'restaurants/table_form.html', {
        'restaurant': table.restaurant, 'table': table, 'error': error,
        'seating_area_choices': Table.SeatingArea.choices,
        'status_choices': Table.Status.choices,
    })


@manager_required
def tables(request):
    """FR-012 RETRIEVE Tables – search by restaurant, capacity, location, status."""
    qs = Table.objects.select_related('restaurant').all()
    restaurant_ids = _assigned_restaurant_ids(request)
    restaurants = Restaurant.objects.all()
    if restaurant_ids is not None:
        qs = qs.filter(restaurant_id__in=restaurant_ids)
        restaurants = restaurants.filter(pk__in=restaurant_ids)
    q = (request.GET.get('q') or '').strip()
    restaurant_id = (request.GET.get('restaurant') or '').strip()
    seating_area = (request.GET.get('seating_area') or '').strip()
    status = (request.GET.get('status') or '').strip()
    capacity = (request.GET.get('capacity') or '').strip()
    if q:
        qs = qs.filter(Q(table_id__icontains=q) | Q(table_number__icontains=q) | Q(restaurant__name__icontains=q))
    if restaurant_id:
        qs = qs.filter(restaurant_id=restaurant_id)
    if seating_area:
        qs = qs.filter(seating_area=seating_area)
    if status:
        qs = qs.filter(status=status)
    if capacity:
        qs = qs.filter(capacity__gte=_parse_int(capacity, 0))
    return render(request, 'restaurants/tables.html', {
        'tables': qs,
        'q': q,
        'restaurant_id': restaurant_id,
        'seating_area': seating_area,
        'status': status,
        'capacity': capacity,
        'restaurants': restaurants,
        'seating_area_choices': Table.SeatingArea.choices,
        'status_choices': Table.Status.choices,
    })


@login_required
def table_detail(request, table_id):
    """FR-012 VIEW Table – availability, capacity, reserve."""
    table = get_object_or_404(Table.objects.select_related('restaurant'), pk=table_id)
    _require_assigned_restaurant(request, table.restaurant_id)
    is_manager = request.user.is_staff or request.user.account_type in ('ADMIN', 'INSTRUCTOR')
    if table.status == Table.Status.MAINTENANCE and not is_manager:
        messages.error(request, "This table is currently unavailable.")
        return redirect('restaurants:detail', table.restaurant.slug)
    return render(request, 'restaurants/table_detail.html', {
        'table': table,
        'is_manager': is_manager,
    })


@login_required
@student_booking_required
def book_restaurant(request, table_id):
    table = get_object_or_404(Table.objects.select_related('restaurant'), pk=table_id)
    _require_assigned_restaurant(request, table.restaurant_id)
    if table.status == Table.Status.MAINTENANCE:
        messages.error(request, "This table is not currently available for booking.")
        return redirect('restaurants:list')
    default_when = timezone.now() + timedelta(hours=2)
    default_guests = max(1, min(2, table.capacity))
    if request.method == 'POST':
        when = _parse_datetime(request.POST.get('reservation_datetime'), default_when)
        guests = _parse_int(request.POST.get('guests'), 1)
        deposit = DEPOSIT_PER_GUEST * guests
        try:
            with transaction.atomic():
                reservation = create_restaurant_reservation(
                    customer=request.user,
                    table=table,
                    when=when,
                    guests=guests,
                    deposit=deposit,
                    seating_preference=request.POST.get('seating_preference', ''),
                    occasion=request.POST.get('occasion', Reservation.Occasion.NONE),
                    special_requests=request.POST.get('special_requests', ''),
                    additional_notes=request.POST.get('additional_notes', ''),
                    payer_name=request.POST.get('payer_name', ''),
                    payer_contact=request.POST.get('payer_contact', ''),
                )
                items = [{
                    'label': 'Table deposit',
                    'description': f"{guests} guest(s) deposit",
                    'quantity': guests,
                    'rate': DEPOSIT_PER_GUEST,
                    'amount': deposit,
                }]
                bill = create_bill(
                    service='restaurant',
                    customer=request.user,
                    items=items,
                    booking=reservation,
                )
                reservation.total_bill = deposit
                reservation.save(update_fields=['total_bill'])
        except RestaurantReservationError as exc:
            messages.error(request, str(exc))
            return render(request, 'restaurants/book.html', {
                'table': table,
                'default_when': default_when,
                'deposit_per_guest': DEPOSIT_PER_GUEST,
                'default_guests': default_guests,
                'occasions': Reservation.Occasion.choices,
                'booking_error': str(exc),
            })

        from simulation.completion import complete_guest_booking
        from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

        complete_guest_booking(
            request.user,
            task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
            booking_reference=reservation.booking_reference,
        )

        if request.POST.get('book_and_add') == '1':
            try:
                add_establishment_booking(request, reservation)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('restaurants:booking_detail', reservation.id)
            messages.success(request, f'Added to this establishment booking: {reservation.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':
            add_booking_to_cart(request, reservation)
            messages.success(request, f"Added to your Trip Cart: {reservation.booking_reference}")
            return redirect('transactions:cart')

        if request.POST.get('pay_later') == 'on':
            messages.success(
                request,
                'Reservation submitted. Status: Pending. Waiting for Restaurant '
                'Reservation Officer confirmation.',
            )
            return redirect('restaurants:booking_detail', reservation.id)
        checkout(
            user=request.user,
            service='restaurant',
            booking=reservation,
            amount=deposit,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=f"Table deposit for reservation {reservation.booking_reference}",
            items=items,
            bill=bill,
        )
        reservation.refresh_from_db()
        reservation.amount_paid = bill.amount_paid
        reservation.balance_due = bill.balance_due
        reservation.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(
            request,
            'Reservation submitted. Status: Pending. Waiting for Restaurant '
            'Reservation Officer confirmation.',
        )
        return redirect('restaurants:booking_detail', reservation.id)
    return render(request, 'restaurants/book.html', {
        'table': table,
        'default_when': default_when,
        'deposit_per_guest': DEPOSIT_PER_GUEST,
        'default_guests': default_guests,
        'occasions': Reservation.Occasion.choices,
    })


@manager_required
def bookings(request):
    qs = Reservation.objects.select_related('customer', 'table__restaurant')
    restaurant_ids = _assigned_restaurant_ids(request)
    if restaurant_ids is not None:
        if restaurant_ids:
            qs = qs.filter(table__restaurant_id__in=restaurant_ids)
        else:
            qs = qs.none()
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    seating_area = (request.GET.get('seating_area') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    guests = (request.GET.get('guests') or '').strip()
    sort = (request.GET.get('sort') or '').strip()
    if q:
        qs = qs.filter(
            Q(booking_reference__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__first_name__icontains=q)
            | Q(customer__last_name__icontains=q)
            | Q(table__restaurant__name__icontains=q)
            | Q(table__table_number__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if seating_area:
        qs = qs.filter(table__seating_area=seating_area)
    if date_from:
        qs = qs.filter(reservation_datetime__date__gte=_parse_date(date_from, None))
    if date_to:
        qs = qs.filter(reservation_datetime__date__lte=_parse_date(date_to, None))
    if guests:
        qs = qs.filter(number_of_guests__gte=_parse_int(guests, 0))
    sort_map = {
        'reservation_datetime': 'reservation_datetime',
        'status': 'status',
        'guests': '-number_of_guests',
        'created_at': '-created_at',
    }
    qs = qs.order_by(sort_map.get(sort, '-reservation_datetime'))
    return render(request, 'restaurants/bookings.html', {
        'bookings': qs,
        'q': q,
        'status': status,
        'seating_area': seating_area,
        'date_from': date_from,
        'date_to': date_to,
        'guests': guests,
        'sort': sort,
        'seating_area_choices': Table.SeatingArea.choices,
        'status_choices': Reservation.Status.choices,
        'restaurants': (
            Restaurant.objects.all() if restaurant_ids is None
            else Restaurant.objects.filter(pk__in=restaurant_ids)
        ),
    })


@login_required
def booking_detail(request, booking_id):
    from transactions.models import Bill, Payment

    _active_task_assignment(request)
    booking = get_object_or_404(
        Reservation.objects.select_related('customer', 'table__restaurant'),
        pk=booking_id,
    )
    _require_assigned_restaurant(request, booking.table.restaurant_id)
    can_manage = bool(can_manage_booking(request.user, 'restaurants'))
    can_confirm = can_manage and _can_confirm_reservation(request)
    if can_manage:
        restaurant_ids = _assigned_restaurant_ids(request)
        if (
            restaurant_ids is not None
            and booking.table.restaurant_id not in restaurant_ids
        ):
            raise PermissionDenied('You are not assigned to this restaurant.')
    elif booking.customer_id != request.user.id:
        messages.warning(request, "You cannot view this booking.")
        return redirect('restaurants:list')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()

    from accounts.roles import can_process_booking_checkin
    can_process_checkin = can_process_booking_checkin(request.user, 'restaurants')

    from accounts.roles import is_reservation_officer
    reservation_officer = is_reservation_officer(request.user, 'restaurants')

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')
        if can_process_checkin and action not in {'checkin', 'checkout'}:
            raise PermissionDenied('Restaurant Front Desk may only check guests in or out.')
        if reservation_officer and action not in {'confirm', 'decline'}:
            raise PermissionDenied('Reservation Officers may only confirm or reject reservations.')
        if action in {'checkin', 'checkout'} and not can_process_checkin:
            raise PermissionDenied('Reservation Officers cannot process check-in or check-out.')
        remark = (request.POST.get('remark') or '').strip()
        if action in {'confirm', 'decline'} and not can_confirm:
            raise PermissionDenied(
                'Only the Restaurant Reservation Officer can confirm or reject reservations.')
        if action == 'confirm':
            try:
                confirm_restaurant_reservation(
                    reservation_id=booking.pk,
                    officer=request.user,
                    remarks=remark,
                )
            except RestaurantReservationError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    'Reservation confirmed. The Restaurant Guest has been notified.',
                )
            return redirect('restaurants:booking_detail', booking.id)
        elif action == 'decline':
            try:
                reject_restaurant_reservation(
                    reservation_id=booking.pk,
                    officer=request.user,
                    reason=request.POST.get('rejection_reason', ''),
                    remarks=remark,
                )
            except RestaurantReservationError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    'Reservation rejected. The Restaurant Guest has been notified.',
                )
            return redirect('restaurants:booking_detail', booking.id)
        elif action == 'checkin':
            if booking.status != Reservation.Status.CONFIRMED:
                messages.error(request, 'Only confirmed reservations can be marked as seated.')
                return redirect('restaurants:booking_detail', booking.id)
            booking.status = Reservation.Status.CHECKED_IN
            booking.checked_in_at = timezone.now()
            booking.save(update_fields=['status', 'checked_in_at'])
            booking.table.status = Table.Status.OCCUPIED
            booking.table.save(update_fields=['status'])
            log_activity(request.user, "Party seated", str(booking.pk))
        elif action == 'checkout':
            if booking.status != Reservation.Status.CHECKED_IN:
                messages.error(request, 'Only seated guests can be marked as finished.')
                return redirect('restaurants:booking_detail', booking.id)
            booking.status = Reservation.Status.CHECKED_OUT
            booking.checked_out_at = timezone.now()
            booking.save(update_fields=['status', 'checked_out_at'])
            booking.table.status = Table.Status.AVAILABLE
            booking.table.save(update_fields=['status'])
            log_activity(request.user, "Party completed meal", str(booking.pk))
        elif action == 'modify':
            when = _parse_datetime(request.POST.get('reservation_datetime'), booking.reservation_datetime)
            guests = _parse_int(request.POST.get('guests'), booking.number_of_guests)
            if guests > booking.table.capacity:
                messages.error(request, f"Party of {guests} exceeds this table's capacity of {booking.table.capacity}.")
                return redirect('restaurants:booking_detail', booking.id)
            if table_has_conflict(
                booking.table, when, exclude_reservation_id=booking.pk,
            ):
                messages.error(request, "The table is already reserved for the requested time slot.")
                return redirect('restaurants:booking_detail', booking.id)
            old_deposit = float(booking.deposit)
            booking.reservation_datetime = when
            booking.number_of_guests = guests
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            booking.deposit = DEPOSIT_PER_GUEST * guests
            booking.status = Reservation.Status.MODIFIED
            booking.save()
            if float(booking.deposit) != old_deposit and bill:
                items = [{'label': 'Table deposit', 'description': f"{booking.number_of_guests} guest(s) deposit",
                          'quantity': booking.number_of_guests, 'rate': DEPOSIT_PER_GUEST,
                          'amount': booking.deposit}]
                bill.calculate(items)
                bill.save(update_fields=['items', 'total_amount'])
                booking.total_bill = booking.deposit
                booking.save(update_fields=['total_bill'])
            messages.success(request, "Reservation modified.")
            return redirect('restaurants:booking_detail', booking.id)
        elif action == 'cancel':
            cancel_booking(booking, request.user)
            log_activity(booking.customer, "Restaurant reservation cancelled",
                         f"{booking.booking_reference} at {booking.table.restaurant.name}")
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='restaurant',
                bill=bill,
            )
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('restaurants:booking_detail', booking.id)

    return render(request, 'restaurants/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'is_reservation_officer': reservation_officer,
        'can_manage_lifecycle': can_manage and not reservation_officer and not can_process_checkin,
        'can_print_ticket': booking.customer_id == request.user.id and not request.user.is_staff and not can_manage,
        'can_process_checkin': can_process_checkin,
        'can_confirm': can_confirm,
    })


@login_required
def ticket_detail(request, booking_id):
    from atrue_core.etickets import eticket_detail
    return eticket_detail(request, 'restaurants', booking_id)


@login_required
def ticket_pdf(request, booking_id):
    from atrue_core.etickets import eticket_pdf
    return eticket_pdf(request, 'restaurants', booking_id)


# ---------------------------------------------------------------------------
# Shared establishment flow (atrue_core.establishment_flow)
# ---------------------------------------------------------------------------


@login_required
@student_booking_required
@transaction.atomic
def restaurant_flow_select(request, restaurant_id):
    """Accept the detail-page table cart and create all selected reservations."""
    from atrue_core.establishment_flow import handle_flow

    _require_assigned_restaurant(request, restaurant_id)
    if request.method == 'GET':
        restaurant = get_object_or_404(Restaurant, pk=restaurant_id)
        return redirect('restaurants:detail', restaurant.slug)
    return handle_flow(request, 'restaurant', restaurant_id)
