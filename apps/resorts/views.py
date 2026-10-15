from datetime import date, timedelta
from decimal import Decimal

from transactions.cart import add_booking_to_cart
from transactions.establishment_flow import add_booking as add_establishment_booking
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone
from accounts.roles import effective_role_keys
from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.establishment_deletion import delete_booking_history, delete_linked_establishment_history
from atrue_core.image_utils import delete_image_record, is_valid_image
from atrue_core.slugs import get_object_by_slug_or_404
from atrue_core.services import (
    bill_for_booking,
    cancel_booking,
    checkout,
    compute_resort_bill,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    overlapping_booking_exists,
    record_payment,
    record_transaction,
    resource_is_bookable,
    turnover_conflicts,
    validate_stay_dates,
)
from django.shortcuts import get_object_or_404, redirect, render

from atrue_core.search_catalog import render_search_page

from transactions.models import TravelOrder, TravelOrderItem

from .models import AdditionalGuest, Reservation, Resort, ResortPhoto, RoomVilla, Service, UnitPhoto
from .scope import resort_scope


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


def _assigned_resort_ids(request):
    """The ``Resort`` pks this request's user is confined to.

    ``None`` means the user is not scoped at all (full-access operator, or a
    plain customer browsing the storefront); an empty set is a real answer -
    a role holder whose active assignment points at no resort (or another
    module) sees nothing here.
    """
    if resort_scope.has_full_access(request.user):
        return None
    if 'RESORT_OWNER' in effective_role_keys(request.user):
        return None
    assignment = getattr(request, 'active_simulation_assignment', None)
    if assignment is not None:
        establishment = assignment.establishment
        if establishment and establishment.type == 'RESORT':
            return {establishment.entity_id} if establishment.entity_id else set()
        return set()
    return set(
        resort_scope.active_assignments(request.user)
        .exclude(establishment__entity_id__isnull=True)
        .values_list('establishment__entity_id', flat=True)
    )


def resort_list(request):
    resorts = Resort.objects.filter(status=Resort.Status.ACTIVE).prefetch_related(
        'photos', 'units', 'units__photos', 'services'
    )
    return render_search_page(request, 'resort', resorts)


@manager_required
@resort_scope.decorator()
def manage(request):
    qs = Resort.objects.prefetch_related('photos', 'units', 'services').all()
    qs = resort_scope.scope_queryset(request, qs)
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    country = (request.GET.get('country') or '').strip()
    province = (request.GET.get('province') or '').strip()
    municipality = (request.GET.get('municipality') or '').strip()
    barangay = (request.GET.get('barangay') or '').strip()
    if q:
        qs = qs.filter(Q(resort_id__icontains=q) | Q(name__icontains=q) |
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
    return render(request, 'resorts/manage.html', {
        'resorts': qs,
        'q': q,
        'status': status,
        'country': country,
        'province': province,
        'municipality': municipality,
        'barangay': barangay,
        'status_choices': Resort.Status.choices,
        'unit_type_choices': RoomVilla.UnitType.choices,
        'unit_status_choices': RoomVilla.Status.choices,
        'can_delete': not resort_scope.is_scoped(request.user),
    })


@manager_required
def add_resort(request):
    if request.method == 'POST':
        resort = Resort.objects.create(
            name=request.POST.get('name'),
            country=request.POST.get('country', ''),
            province=request.POST.get('province', ''),
            municipality=request.POST.get('municipality', ''),
            barangay=request.POST.get('barangay', ''),
            contact_number=request.POST.get('contact_number', ''),
            email=request.POST.get('email', ''),
            operating_schedule=request.POST.get('operating_schedule', ''),
        )
        resort.refresh_from_db()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for index, image in enumerate(photos):
            ResortPhoto.objects.create(resort=resort, image=image, is_primary=(index == 0))
        log_activity(request.user, "Created resort", f"{resort.name} ({resort.resort_id})")
        messages.success(request, f"Resort '{resort.name}' created (ID: {resort.resort_id}).")
        return redirect('resorts:manage')
    return render(request, 'resorts/form.html', {
        'resort': None,
        'status_choices': Resort.Status.choices,
    })


@manager_required
def update_resort(request, resort_id):
    resort = get_object_or_404(Resort, pk=resort_id)
    if request.method == 'POST':
        for field in ('name', 'country', 'province', 'municipality', 'barangay',
                      'contact_number', 'email', 'operating_schedule', 'status'):
            setattr(resort, field, request.POST.get(field, getattr(resort, field)))
        resort.save()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for image in photos:
            ResortPhoto.objects.create(resort=resort, image=image, is_primary=not resort.photos.exists())
        for photo in resort.photos.filter(pk__in=request.POST.getlist('delete_photos')):
            delete_image_record(photo)
        if resort.photos.exists() and not resort.photos.filter(is_primary=True).exists():
            first = resort.photos.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        log_activity(request.user, "Updated resort", f"{resort.name} ({resort.resort_id})")
        messages.success(request, "Resort updated.")
        return redirect('resorts:manage')
    return render(request, 'resorts/form.html', {
        'resort': resort,
        'status_choices': Resort.Status.choices,
    })


@manager_required
@resort_scope.decorator()
def delete_resort(request, resort_id):
    if request.method != 'POST':
        messages.warning(request, 'Invalid request.')
        return redirect('resorts:manage')
    resort = get_object_or_404(
        resort_scope.scope_queryset(request, Resort.objects.all()), pk=resort_id)
    name = resort.name
    try:
        with db_transaction.atomic():
            delete_booking_history(Reservation.objects.filter(unit__resort=resort))
            delete_linked_establishment_history(resort)
            resort.delete()
    except ProtectedError:
        messages.error(request, f"Resort '{name}' is linked to existing records and cannot be deleted. Set its status to Inactive instead.")
        return redirect('resorts:manage')
    log_activity(request.user, 'Deleted resort', name)
    messages.success(request, f"Resort '{name}' and its booking history deleted.")
    return redirect('resorts:manage')


def resort_detail(request, resort_id):
    """FR-003 VIEW Resort – full detail profile (units, services)."""
    resort = get_object_by_slug_or_404(
        Resort.objects.prefetch_related('photos', 'units', 'services'),
        resort_id,
    )
    is_manager = getattr(request.user, 'is_staff', False) or getattr(request.user, 'account_type', None) in ('ADMIN', 'INSTRUCTOR')
    if resort.status != Resort.Status.ACTIVE and not is_manager:
        messages.error(request, "This resort is currently unavailable.")
        return redirect('resorts:list')
    return render(request, 'resorts/detail.html', {
        'resort': resort,
        'is_manager': is_manager,
    })


@manager_required
def add_unit(request, resort_id):
    resort = get_object_or_404(Resort, pk=resort_id)
    error = None
    if request.method == 'POST':
        unit_number = (request.POST.get('unit_number') or '').strip()
        if not unit_number:
            error = "Unit number is required."
        elif len(unit_number) > 100:
            error = "Unit number must be 100 characters or fewer."
        elif RoomVilla.objects.filter(resort=resort, unit_number=unit_number).exists():
            error = f"Unit {unit_number} already exists in '{resort.name}'. Choose a different unit number."
        else:
            unit = RoomVilla.objects.create(
                resort=resort,
                unit_type=request.POST.get('unit_type', RoomVilla.UnitType.ROOM),
                unit_number=unit_number,
                capacity_adults=_parse_int(request.POST.get('capacity_adults'), 2),
                capacity_children=_parse_int(request.POST.get('capacity_children'), 0),
                rate=request.POST.get('rate') or 0,
                additional_guest_charge=request.POST.get('additional_guest_charge') or 0,
                features=request.POST.get('features', ''),
                description=request.POST.get('description', ''),
                status=request.POST.get('status', RoomVilla.Status.AVAILABLE),
            )
            for image in request.FILES.getlist('photos'):
                if is_valid_image(image):
                    UnitPhoto.objects.create(unit=unit, image=image)
            log_activity(request.user, "Added resort unit",
                         f"{unit.unit_id} ({unit.unit_number}) in {resort.name}")
            messages.success(request, f"Unit {unit.unit_number} added (ID: {unit.unit_id}).")
            if request.POST.get('return_to_detail'):
                return redirect('resorts:detail', resort.slug)
            if request.POST.get('return_to_manage'):
                return redirect('resorts:manage')
            return redirect('resorts:update_resort', resort.id)
    return render(request, 'resorts/unit_form.html', {
        'resort': resort, 'unit': None, 'error': error,
        'unit_type_choices': RoomVilla.UnitType.choices,
        'status_choices': RoomVilla.Status.choices,
    })


@manager_required
def update_unit(request, unit_id):
    unit = get_object_or_404(RoomVilla.objects.prefetch_related('photos'), pk=unit_id)
    error = None
    if request.method == 'POST':
        unit_number = (request.POST.get('unit_number') or unit.unit_number).strip()
        duplicate = RoomVilla.objects.filter(resort=unit.resort, unit_number=unit_number).exclude(pk=unit.pk).exists()
        if not unit_number:
            error = "Unit number is required."
        elif len(unit_number) > 100:
            error = "Unit number must be 100 characters or fewer."
        elif duplicate:
            error = f"Unit {unit_number} already exists in '{unit.resort.name}'. Choose a different unit number."
        else:
            unit.unit_number = unit_number
            unit.unit_type = request.POST.get('unit_type', unit.unit_type)
            unit.capacity_adults = _parse_int(request.POST.get('capacity_adults'), unit.capacity_adults)
            unit.capacity_children = _parse_int(request.POST.get('capacity_children'), unit.capacity_children)
            unit.rate = request.POST.get('rate') or unit.rate
            unit.additional_guest_charge = request.POST.get('additional_guest_charge') or unit.additional_guest_charge
            unit.features = request.POST.get('features', unit.features)
            unit.description = request.POST.get('description', unit.description)
            unit.status = request.POST.get('status', unit.status)
            unit.save()
            for image in request.FILES.getlist('photos'):
                if is_valid_image(image):
                    UnitPhoto.objects.create(unit=unit, image=image)
            for photo in unit.photos.filter(pk__in=request.POST.getlist('delete_photos')):
                delete_image_record(photo)
            log_activity(request.user, "Updated resort unit",
                         f"{unit.unit_id} ({unit.unit_number}) in {unit.resort.name}")
            messages.success(request, "Unit updated.")
            return redirect('resorts:update_resort', unit.resort_id)
    return render(request, 'resorts/unit_form.html', {
        'resort': unit.resort, 'unit': unit, 'error': error,
        'unit_type_choices': RoomVilla.UnitType.choices,
        'status_choices': RoomVilla.Status.choices,
    })


@manager_required
def units(request):
    """FR-005 RETRIEVE Rooms/Villas – search and filter by resort, type, capacity, status."""
    qs = RoomVilla.objects.select_related('resort').prefetch_related('photos').all()
    q = (request.GET.get('q') or '').strip()
    resort_id = (request.GET.get('resort') or '').strip()
    unit_type = (request.GET.get('unit_type') or '').strip()
    status = (request.GET.get('status') or '').strip()
    capacity = (request.GET.get('capacity') or '').strip()
    if q:
        qs = qs.filter(Q(unit_id__icontains=q) | Q(unit_number__icontains=q) | Q(resort__name__icontains=q))
    if resort_id:
        qs = qs.filter(resort_id=resort_id)
    if unit_type:
        qs = qs.filter(unit_type=unit_type)
    if status:
        qs = qs.filter(status=status)
    if capacity:
        qs = qs.filter(capacity_adults__gte=_parse_int(capacity, 0))
    return render(request, 'resorts/units.html', {
        'units': qs,
        'q': q,
        'resort_id': resort_id,
        'unit_type': unit_type,
        'status': status,
        'capacity': capacity,
        'resorts': Resort.objects.all(),
        'unit_type_choices': RoomVilla.UnitType.choices,
        'status_choices': RoomVilla.Status.choices,
    })


@login_required
def unit_detail(request, unit_id):
    """FR-005 VIEW Room/Villa – full detail profile (photos, features, rate, availability)."""
    unit = get_object_or_404(
        RoomVilla.objects.select_related('resort').prefetch_related('photos'),
        pk=unit_id,
    )
    is_manager = request.user.is_staff or request.user.account_type in ('ADMIN', 'INSTRUCTOR')
    if unit.status != RoomVilla.Status.AVAILABLE and not is_manager:
        messages.error(request, "This unit is currently unavailable.")
        return redirect('resorts:detail', unit.resort.slug)
    return render(request, 'resorts/unit_detail.html', {
        'unit': unit,
        'is_manager': is_manager,
    })


@manager_required
def add_service(request, resort_id):
    resort = get_object_or_404(Resort, pk=resort_id)
    if request.method == 'POST':
        service = Service.objects.create(
            resort=resort,
            name=request.POST.get('name'),
            description=request.POST.get('description', ''),
            capacity=_parse_int(request.POST.get('capacity'), 0),
            rate=request.POST.get('rate') or 0,
            operating_hours=request.POST.get('operating_hours', ''),
            status=request.POST.get('status', Service.ServiceStatus.ACTIVE),
        )
        service.refresh_from_db()
        log_activity(request.user, "Added resort service", f"{service.name} ({service.service_id}) in {resort.name}")
        messages.success(request, f"Service '{service.name}' added (ID: {service.service_id}).")
        return redirect('resorts:update_resort', resort.id)
    return render(request, 'resorts/service_form.html', {
        'resort': resort, 'service': None,
        'status_choices': Service.ServiceStatus.choices,
    })


@manager_required
def update_service(request, service_id):
    service = get_object_or_404(Service, pk=service_id)
    if request.method == 'POST':
        service.name = request.POST.get('name', service.name)
        service.description = request.POST.get('description', service.description)
        service.capacity = _parse_int(request.POST.get('capacity'), service.capacity)
        service.rate = request.POST.get('rate') or service.rate
        service.operating_hours = request.POST.get('operating_hours', service.operating_hours)
        service.status = request.POST.get('status', service.status)
        service.save()
        log_activity(request.user, "Updated resort service",
                     f"{service.name} ({service.service_id}) in {service.resort.name}")
        messages.success(request, "Service updated.")
        return redirect('resorts:update_resort', service.resort_id)
    return render(request, 'resorts/service_form.html', {
        'resort': service.resort, 'service': service,
        'status_choices': Service.ServiceStatus.choices,
    })


@manager_required
def services(request):
    """FR-009 RETRIEVE Resort Services – search by name, schedule, status, resort."""
    qs = Service.objects.select_related('resort').all()
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    resort_id = (request.GET.get('resort') or '').strip()
    if q:
        qs = qs.filter(Q(service_id__icontains=q) | Q(name__icontains=q) |
                       Q(operating_hours__icontains=q) | Q(resort__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if resort_id:
        qs = qs.filter(resort_id=resort_id)
    return render(request, 'resorts/services.html', {
        'services': qs,
        'q': q,
        'status': status,
        'resort_id': resort_id,
        'resorts': Resort.objects.all(),
        'status_choices': Service.ServiceStatus.choices,
    })


@login_required
def service_detail(request, service_id):
    """FR-009 VIEW Resort Service – full details (active for customers)."""
    service = get_object_or_404(Service.objects.select_related('resort'), pk=service_id)
    is_manager = request.user.is_staff or request.user.account_type in ('ADMIN', 'INSTRUCTOR')
    if service.status != Service.ServiceStatus.ACTIVE and not is_manager:
        messages.error(request, "This service is currently unavailable.")
        return redirect('resorts:detail', service.resort.slug)
    return render(request, 'resorts/service_detail.html', {
        'service': service,
        'is_manager': is_manager,
    })


@login_required
@student_booking_required
def resort_group_start(request, resort_id):
    """Direct multi-villa resort booking. Each selected villa becomes its own
    reservation, all paid under ONE TravelOrder / ONE payment transaction."""
    resort = get_object_or_404(
        Resort.objects.filter(status=Resort.Status.ACTIVE).prefetch_related('units__photos', 'services'),
        pk=resort_id,
    )
    base_in = date.today() + timedelta(days=1)
    base_out = base_in + timedelta(days=1)
    check_in = _parse_date(request.GET.get('check_in'), base_in)
    check_out = _parse_date(request.GET.get('check_out'), base_out)
    if check_out <= check_in:
        check_out = check_in + timedelta(days=1)

    if request.method == 'POST':
        check_in = _parse_date(request.POST.get('check_in'), check_in)
        check_out = _parse_date(request.POST.get('check_out'), check_out)
        if check_out <= check_in:
            check_out = check_in + timedelta(days=1)
        villa_ids = [int(x) for x in request.POST.getlist('villa_ids') if str(x).isdigit()]
        villa_ids = list(dict.fromkeys(villa_ids))
        if not villa_ids:
            messages.error(request, 'Choose at least one villa to book.')
            return redirect('resorts:group_start', resort.id)
        villas = list(RoomVilla.objects.filter(resort=resort, pk__in=villa_ids).prefetch_related('photos'))
        villas.sort(key=lambda unit: villa_ids.index(unit.pk))
        for unit in villas:
            if unit.status != RoomVilla.Status.AVAILABLE or overlapping_booking_exists(
                Reservation, resource_field='unit', resource=unit, start=check_in, end=check_out
            ):
                messages.error(request, f'Villa {unit.unit_number} is no longer available for those dates.')
                return redirect('resorts:group_start', resort.id)
        adults = _parse_int(request.POST.get('adults'), 1)
        children = _parse_int(request.POST.get('children'), 0)
        villas_data = []
        for unit in villas:
            services = [int(x) for x in request.POST.getlist(f'services_{unit.id}') if str(x).isdigit()]
            villas_data.append({'unit_id': unit.id, 'services': services})
        request.session['resort_group_booking'] = {
            'resort_id': resort.id,
            'check_in': check_in.isoformat(),
            'check_out': check_out.isoformat(),
            'nights': max(1, (check_out - check_in).days),
            'adults': max(1, adults),
            'children': max(0, children),
            'special_requests': (request.POST.get('special_requests') or '').strip(),
            'payer_name': request.user.full_profile,
            'payer_contact': request.user.contact_number or '',
            'villas': villas_data,
        }
        request.session.modified = True
        return redirect('resorts:group_review')

    available = [
        u for u in resort.units.all()
        if u.status == RoomVilla.Status.AVAILABLE
        and not overlapping_booking_exists(Reservation, resource_field='unit', resource=u, start=check_in, end=check_out)
    ]
    return render(request, 'resorts/group_select.html', {
        'resort': resort,
        'available_units': available,
        'check_in': check_in,
        'check_out': check_out,
        'nights': max(1, (check_out - check_in).days),
        'services': resort.services.filter(status=Service.ServiceStatus.ACTIVE),
    })


@login_required
@student_booking_required
def resort_group_review(request):
    """Review + payment for the multi-villa booking (ONE transaction)."""
    data = request.session.get('resort_group_booking') or {}
    if not data.get('villas'):
        messages.error(request, 'Start a resort booking first.')
        return redirect('resorts:list')
    resort = get_object_or_404(
        Resort.objects.filter(status=Resort.Status.ACTIVE).prefetch_related('services', 'units__photos'),
        pk=data['resort_id'],
    )
    check_in = date.fromisoformat(data['check_in'])
    check_out = date.fromisoformat(data['check_out'])
    nights = max(1, (check_out - check_in).days)
    unit_ids = [item['unit_id'] for item in data['villas']]
    units = {u.pk: u for u in RoomVilla.objects.filter(resort=resort, pk__in=unit_ids).prefetch_related('photos')}
    lines = []
    grand_total = Decimal('0')
    unit_subtotal = Decimal('0')
    services_subtotal = Decimal('0')
    for item in data['villas']:
        unit = units.get(item['unit_id'])
        if unit is None:
            messages.error(request, 'One of the selected villas is no longer available.')
            request.session.pop('resort_group_booking', None)
            request.session.modified = True
            return redirect('resorts:list')
        selected_services = list(resort.services.filter(
            pk__in=item.get('services', []), status=Service.ServiceStatus.ACTIVE))
        unit_total = unit.rate * nights
        services_total = sum((s.rate for s in selected_services), Decimal('0'))
        amount = unit_total + services_total
        grand_total += amount
        unit_subtotal += unit_total
        services_subtotal += services_total
        lines.append({
            'unit': unit, 'nights': nights, 'unit_total': unit_total,
            'services': selected_services, 'services_total': services_total, 'amount': amount,
        })

    if request.method == 'POST':
        if request.POST.get('action') == 'edit':
            return redirect('resorts:group_start', resort.id)
        method = request.POST.get('payment_method') or 'GCASH'
        pay_later = request.POST.get('pay_later') == 'on'
        try:
            with db_transaction.atomic():
                reservations = []
                bill_items = []
                amounts = []
                for item, line in zip(data['villas'], lines):
                    unit = line['unit']
                    if unit.status != RoomVilla.Status.AVAILABLE or overlapping_booking_exists(
                        Reservation, resource_field='unit', resource=unit, start=check_in, end=check_out
                    ):
                        raise ValueError(f'{unit.get_unit_type_display()} {unit.unit_number} is no longer available for the selected dates.')
                    reservation = Reservation.objects.create(
                        customer=request.user,
                        unit=unit,
                        check_in=check_in,
                        check_out=check_out,
                        number_of_units=1,
                        number_of_adults=max(1, data.get('adults', 1)),
                        number_of_children=max(0, data.get('children', 0)),
                        special_requests=data.get('special_requests', ''),
                        payer_name=request.user.full_profile,
                        payer_contact=request.user.contact_number or '',
                        status=Reservation.Status.PENDING,
                    )
                    reservation.services.set(line['services'])
                    reservations.append(reservation)
                    amounts.append(line['amount'])
                    bill_items.append({
                        'label': f'{unit.get_unit_type_display()} {unit.unit_number}',
                        'description': f'{nights} night(s) at {resort.name}',
                        'quantity': nights, 'rate': unit.rate, 'amount': unit.rate * nights,
                    })
                    for service in line['services']:
                        bill_items.append({
                            'label': service.name,
                            'description': f'{unit.get_unit_type_display()} {unit.unit_number} service',
                            'quantity': 1, 'rate': service.rate, 'amount': service.rate,
                        })
                total = sum((Decimal(str(i['amount'])) for i in bill_items), Decimal('0'))
                order = TravelOrder.objects.create(
                    customer=request.user,
                    status=TravelOrder.Status.PENDING,
                    total_amount=total,
                    balance_due=total,
                    payment_method=method,
                )
                ct = ContentType.objects.get_for_model(Reservation)
                for reservation, amount, line in zip(reservations, amounts, lines):
                    TravelOrderItem.objects.create(
                        order=order,
                        content_type=ct,
                        object_id=reservation.pk,
                        service='resort',
                        description=f"{line['unit'].get_unit_type_display()} {line['unit'].unit_number} · {resort.name} · {nights} night(s)",
                        amount=amount,
                    )
                    reservation.total_bill = amount
                    reservation.balance_due = amount
                    reservation.save(update_fields=['total_bill', 'balance_due'])
                    from notifications.email_service import queue_booking_confirmation
                    queue_booking_confirmation(reservation)
                combined_bill = create_bill(service='bundle', customer=request.user, items=bill_items)
                order.bill = combined_bill
                order.save(update_fields=['bill'])

                from simulation.completion import complete_guest_booking
                from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

                complete_guest_booking(
                    request.user,
                    task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
                    booking_reference=order.order_reference,
                )
                request.session.pop('resort_group_booking', None)
                request.session.modified = True
                if pay_later:
                    log_activity(request.user, 'Placed resort group booking',
                                 f'{order.order_reference} · {len(reservations)} villa(s) · pending payment')
                    record_transaction('BOOKING', order.order_reference, request.user,
                                       f'Resort group booking {order.order_reference}')
                    messages.success(request, f'Resort booking order {order.order_reference} created. {len(reservations)} villa(s) · payment pending.')
                    return redirect('transactions:order_detail', order.id)
                record_payment(
                    customer=request.user, amount=total, method=method,
                    service='bundle',
                    description=f'ATrue order {order.order_reference}: {len(reservations)} resort villa(s)',
                    bill=combined_bill,
                )
                order.status = TravelOrder.Status.CONFIRMED
                order.amount_paid = total
                order.balance_due = 0
                order.save(update_fields=['status', 'amount_paid', 'balance_due'])
                for reservation, amount in zip(reservations, amounts):
                    reservation.status = Reservation.Status.PENDING
                    reservation.amount_paid = amount
                    reservation.balance_due = 0
                    reservation.save(update_fields=['status', 'amount_paid', 'balance_due'])
                log_activity(request.user, 'Paid for resort group booking',
                             f'{order.order_reference} · {len(reservations)} villa(s) · pending officer confirmation')
                record_transaction('BOOKING', order.order_reference, request.user,
                                   f'Resort group booking {order.order_reference} paid')
                messages.success(request, f'Resort booking order {order.order_reference} paid. '
                                          f'{len(reservations)} villa(s) · pending officer confirmation.')
                return redirect('transactions:order_detail', order.id)
        except ValueError as exc:
            messages.error(request, str(exc))
            request.session.pop('resort_group_booking', None)
            request.session.modified = True
            return redirect('resorts:group_start', resort.id)

    return render(request, 'resorts/group_review.html', {
        'resort': resort,
        'lines': lines,
        'check_in': check_in,
        'check_out': check_out,
        'nights': nights,
        'grand_total': grand_total,
        'unit_subtotal': unit_subtotal,
        'services_subtotal': services_subtotal,
    })


@login_required
@student_booking_required
def book_resort(request, unit_id):
    unit = get_object_or_404(RoomVilla.objects.select_related('resort'), pk=unit_id)
    if not resource_is_bookable(unit):
        messages.error(request, "This unit is not currently available for booking.")
        return redirect('resorts:list')
    base_in = date.today() + timedelta(days=1)
    base_out = base_in + timedelta(days=1)
    if request.method == 'POST':
        check_in = _parse_date(request.POST.get('check_in'), base_in)
        check_out = _parse_date(request.POST.get('check_out'), base_out)

        if overlapping_booking_exists(
            Reservation, resource_field='unit', resource=unit, start=check_in, end=check_out
        ):
            messages.error(request, "This unit is already reserved for the selected dates.")
            return render(request, 'resorts/book.html', {
                'unit': unit, 'check_in': check_in, 'check_out': check_out,
                'nights': max(1, (check_out - check_in).days),
                'services': unit.resort.services.filter(status=Service.ServiceStatus.ACTIVE),
            })

        reservation = Reservation.objects.create(
            customer=request.user,
            unit=unit,
            check_in=check_in,
            check_out=check_out,
            number_of_units=_parse_int(request.POST.get('number_of_units'), 1),
            number_of_adults=_parse_int(request.POST.get('adults'), 1),
            number_of_children=_parse_int(request.POST.get('children'), 0),
            special_requests=request.POST.get('special_requests', ''),
            payer_name=request.user.full_profile,
            payer_contact=request.user.contact_number or '',
            status=Reservation.Status.PENDING,
        )
        reservation.services.set(request.POST.getlist('services'))
        unit.status = RoomVilla.Status.RESERVED
        unit.save(update_fields=['status'])

        first_names = request.POST.getlist('additional_first_name')
        last_names = request.POST.getlist('additional_last_name')
        countries = request.POST.getlist('additional_country')
        for fn, ln, country in zip(first_names, last_names, countries):
            if fn.strip() or ln.strip():
                AdditionalGuest.objects.create(
                    reservation=reservation,
                    first_name=fn.strip(),
                    last_name=ln.strip(),
                    country=country.strip(),
                )

        items = compute_resort_bill(
            unit, reservation.nights,
            services=reservation.services.select_related().all(),
            extra_charges=[
                {
                    'label': 'Additional guest charge',
                    'quantity': reservation.nights,
                    'rate': unit.additional_guest_charge,
                    'amount': unit.additional_guest_charge * reservation.nights,
                }
            ] if unit.additional_guest_charge else None,
        )
        total = sum(float(i['amount']) for i in items)
        bill = create_bill(service='resort', customer=request.user, items=items, booking=reservation)
        reservation.total_bill = total
        reservation.save(update_fields=['total_bill'])

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
                return redirect('resorts:booking_detail', reservation.id)
            messages.success(request, f'Added to this establishment booking: {reservation.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':


            add_booking_to_cart(request, reservation)


            messages.success(request, f"Added to your Trip Cart: {reservation.booking_reference}")


            return redirect('transactions:cart')



        if request.POST.get('pay_later') == 'on':
            messages.success(request, f"Reservation saved! Reference: {reservation.booking_reference} (pending payment)")
            return redirect('resorts:booking_detail', reservation.id)
        checkout(
            user=request.user,
            service='resort',
            booking=reservation,
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=f"Resort booking {reservation.booking_reference}",
            items=items,
            bill=bill,
        )
        reservation.refresh_from_db()
        reservation.amount_paid = total
        reservation.balance_due = 0
        reservation.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, f"Resort booked! Reference: {reservation.booking_reference}")
        return redirect('resorts:booking_detail', reservation.id)
    return render(request, 'resorts/book.html', {
        'unit': unit,
        'check_in': base_in,
        'check_out': base_out,
        'nights': 1,
        'services': unit.resort.services.filter(status=Service.ServiceStatus.ACTIVE),
    })


@manager_required
def bookings(request):
    qs = Reservation.objects.select_related('customer', 'unit__resort')
    resort_ids = _assigned_resort_ids(request)
    if resort_ids is not None:
        qs = (qs.filter(unit__resort_id__in=resort_ids) if resort_ids
              else qs.none())
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    unit_type = (request.GET.get('unit_type') or '').strip()
    check_in_from = (request.GET.get('check_in_from') or '').strip()
    check_out_to = (request.GET.get('check_out_to') or '').strip()
    sort = (request.GET.get('sort') or '').strip()
    if q:
        qs = qs.filter(
            Q(booking_reference__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__first_name__icontains=q)
            | Q(customer__last_name__icontains=q)
            | Q(unit__resort__name__icontains=q)
            | Q(unit__unit_number__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if unit_type:
        qs = qs.filter(unit__unit_type=unit_type)
    if check_in_from:
        qs = qs.filter(check_in__gte=_parse_date(check_in_from, None))
    if check_out_to:
        qs = qs.filter(check_out__lte=_parse_date(check_out_to, None))
    sort_map = {
        'check_in': 'check_in',
        'check_out': 'check_out',
        'status': 'status',
        'created_at': '-created_at',
    }
    qs = qs.order_by(sort_map.get(sort, '-created_at'))
    return render(request, 'resorts/bookings.html', {
        'bookings': qs,
        'q': q,
        'status': status,
        'unit_type': unit_type,
        'check_in_from': check_in_from,
        'check_out_to': check_out_to,
        'sort': sort,
        'unit_type_choices': RoomVilla.UnitType.choices,
        'resorts': (
            Resort.objects.all() if resort_ids is None
            else Resort.objects.filter(pk__in=resort_ids)
        ),
    })


@login_required
def booking_detail(request, booking_id):
    from accounts.roles import can_manage_booking
    from transactions.models import Bill, Payment

    booking = get_object_or_404(
        Reservation.objects.select_related('customer', 'unit__resort').prefetch_related('additional_guests__unit'),
        pk=booking_id,
    )
    if booking.customer_id != request.user.id and not can_manage_booking(request.user, 'resorts'):
        messages.warning(request, "You cannot view this booking.")
        return redirect('resorts:list')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()
    can_manage = bool(can_manage_booking(request.user, 'resorts'))

    # A role holder may only reach the reservations of the resorts they were
    # assigned; an otherwise-allowed id in the URL must not reach another
    # resort's booking. Booking-as-customer stays open, since a student can
    # legitimately book a resort they are not assigned to operate.
    resort_ids = _assigned_resort_ids(request)
    if (
        booking.customer_id != request.user.id
        and can_manage
        and resort_ids is not None
        and booking.unit.resort_id not in resort_ids
    ):
        raise PermissionDenied('You are not assigned to this resort.')

    from accounts.roles import can_process_booking_checkin
    can_process_checkin = can_process_booking_checkin(request.user, 'resorts')

    from accounts.roles import is_reservation_officer
    reservation_officer = is_reservation_officer(request.user, 'resorts')

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')
        if reservation_officer and action not in {'confirm', 'decline'}:
            raise PermissionDenied('Reservation Officers may only review pending reservations.')
        if action in {'checkin', 'checkout'} and not can_process_checkin:
            raise PermissionDenied('Reservation Officers cannot process check-in or check-out.')
        remark = (request.POST.get('remark') or '').strip()
        if action == 'confirm':
            booking.manager_remarks = remark or booking.manager_remarks
            if remark:
                booking.save(update_fields=['manager_remarks'])
            confirm_booking(booking, request.user)
            if getattr(booking, 'payment_review_pending', False):
                messages.warning(request, 'Waiting for the Billing Officer to verify full payment before confirmation.')
            else:
                log_activity(booking.customer, "Resort reservation confirmed",
                             f"{booking.booking_reference} for {booking.unit.resort.name}")
        elif action == 'decline':
            booking.manager_remarks = remark or booking.manager_remarks
            booking.save(update_fields=['manager_remarks'])
            decline_booking(booking, request.user)
            booking.unit.status = 'AVAILABLE'
            booking.unit.save(update_fields=['status'])
            log_activity(booking.customer, "Resort reservation declined",
                         f"{booking.booking_reference} - {remark or 'no remark'}")
        elif action == 'checkin':
            booking.status = Reservation.Status.CHECKED_IN
            booking.checked_in_at = timezone.now()
            booking.save(update_fields=['status', 'checked_in_at'])
            booking.unit.status = 'OCCUPIED'
            booking.unit.save(update_fields=['status'])
            log_activity(request.user, "Guest checked in", str(booking.pk))
        elif action == 'checkout':
            booking.status = Reservation.Status.CHECKED_OUT
            booking.checked_out_at = timezone.now()
            booking.save(update_fields=['status', 'checked_out_at'])
            booking.unit.status = 'AVAILABLE'
            booking.unit.save(update_fields=['status'])
            log_activity(request.user, "Guest checked out", str(booking.pk))
        elif action == 'modify':
            new_in = _parse_date(request.POST.get('check_in'), booking.check_in)
            new_out = _parse_date(request.POST.get('check_out'), booking.check_out)
            date_errors = validate_stay_dates(new_in, new_out)
            if date_errors:
                messages.error(request, date_errors[0])
                return redirect('resorts:booking_detail', booking.id)
            conflict = Reservation.objects.filter(
                unit=booking.unit,
                check_in__lt=new_out,
                check_out__gt=new_in,
            ).exclude(pk=booking.pk).exclude(
                status__in=[Reservation.Status.CANCELLED, Reservation.Status.DECLINED,
                            Reservation.Status.CHECKED_OUT]
            ).exists()
            if conflict:
                messages.error(request, "The unit is already reserved for the selected dates.")
                return redirect('resorts:booking_detail', booking.id)
            prior_check_outs = Reservation.objects.filter(
                unit=booking.unit,
                check_out__lte=new_in,
            ).exclude(pk=booking.pk).exclude(
                status__in=[Reservation.Status.CANCELLED, Reservation.Status.DECLINED,
                            Reservation.Status.CHECKED_OUT]
            ).values_list('check_out', flat=True)
            if any(turnover_conflicts(new_in, prior) for prior in prior_check_outs):
                messages.error(request, "The unit is still in turnover for the selected check-in date.")
                return redirect('resorts:booking_detail', booking.id)
            booking.check_in = new_in
            booking.check_out = new_out
            booking.number_of_adults = _parse_int(request.POST.get('adults'), booking.number_of_adults)
            booking.number_of_children = _parse_int(request.POST.get('children'), booking.number_of_children)
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            booking.status = Reservation.Status.MODIFIED
            booking.save()
            items = compute_resort_bill(
                booking.unit, booking.nights,
                services=booking.services.select_related().all(),
                extra_charges=[
                    {
                        'label': 'Additional guest charge',
                        'quantity': booking.nights,
                        'rate': booking.unit.additional_guest_charge,
                        'amount': booking.unit.additional_guest_charge * booking.nights,
                    }
                ] if booking.unit.additional_guest_charge else None,
            )
            total = sum(float(i['amount']) for i in items)
            if bill:
                bill.calculate(items)
                bill.save(update_fields=['items', 'total_amount'])
            booking.total_bill = total
            booking.save(update_fields=['total_bill'])
            log_activity(request.user, "Modified resort reservation",
                         f"{booking.booking_reference} - new total ₱{total}")
        elif action == 'cancel':
            cancel_booking(booking, request.user)
            booking.unit.status = 'AVAILABLE'
            booking.unit.save(update_fields=['status'])
            log_activity(booking.customer, "Resort reservation cancelled",
                         f"{booking.booking_reference} for {booking.unit.resort.name}")
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='resort',
                bill=bill,
            )
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('resorts:booking_detail', booking.id)

    return render(request, 'resorts/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'is_reservation_officer': reservation_officer,
        'can_manage_lifecycle': can_manage and not reservation_officer,
        'can_print_ticket': booking.customer_id == request.user.id and not request.user.is_staff and not can_manage,
        'can_process_checkin': can_process_checkin,
    })


@login_required
def ticket_detail(request, booking_id):
    from atrue_core.etickets import eticket_detail
    return eticket_detail(request, 'resorts', booking_id)


@login_required
def ticket_pdf(request, booking_id):
    from atrue_core.etickets import eticket_pdf
    return eticket_pdf(request, 'resorts', booking_id)


# ---------------------------------------------------------------------------
# Shared establishment flow (atrue_core.establishment_flow)
# Same structure as the Hotel booking page: selectable units with a live
# right-hand summary, per-villa guest information, optional resort services,
# the computed total and a single final action.
# ---------------------------------------------------------------------------


@login_required
@student_booking_required
def resort_flow_select(request, resort_id):
    """Choose villas, add services and confirm the resort booking in one page."""
    from atrue_core.establishment_flow import handle_flow

    return handle_flow(request, 'resort', resort_id)

