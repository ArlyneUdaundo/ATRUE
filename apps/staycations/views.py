from datetime import date, timedelta

from transactions.cart import add_booking_to_cart
from transactions.establishment_flow import add_booking as add_establishment_booking
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils import timezone
from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.image_utils import is_valid_image
from atrue_core.slugs import get_object_by_slug_or_404
from atrue_core.services import (
    bill_for_booking,
    cancel_booking,
    checkout,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    overlapping_booking_exists,
    record_payment,
    resource_is_bookable,
)
from django.shortcuts import get_object_or_404, redirect, render

from atrue_core.search_catalog import render_search_page

from .models import BlockOutDate, Reservation, Service, Staycation, StaycationPhoto
from .scope import staycation_scope


def _parse_date(value, fallback):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback


def staycation_list(request):
    staycations = Staycation.objects.prefetch_related('services', 'blocked_dates', 'photos').filter(status=Staycation.Status.ACTIVE)
    staycations = [s for s in staycations if resource_is_bookable(s)]
    return render_search_page(request, 'staycation', staycations)


@manager_required
@staycation_scope.decorator()
def manage(request):
    qs = Staycation.objects.prefetch_related('services', 'blocked_dates', 'photos').all()
    qs = staycation_scope.scope_queryset(request, qs)
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
    return render(request, 'staycations/manage.html', {
        'staycations': qs,
        'q': q,
        'status': status,
        'country': country,
        'province': province,
        'municipality': municipality,
        'barangay': barangay,
        'status_choices': Staycation.Status.choices,
        'active_assignment': request.assigned_staycation_assignment,
        'scoped_user': staycation_scope.is_scoped(request.user),
    })


@manager_required
@staycation_scope.decorator()
def add_staycation(request):
    if request.method == 'POST':
        staycation = Staycation.objects.create(
            name=request.POST.get('name'),
            country=request.POST.get('country', ''),
            province=request.POST.get('province', ''),
            municipality=request.POST.get('municipality', ''),
            barangay=request.POST.get('barangay', ''),
            contact_number=request.POST.get('contact_number', ''),
            email=request.POST.get('email', ''),
            capacity=int(request.POST.get('capacity') or 1),
            capacity_adults=int(request.POST.get('capacity_adults') or 1),
            capacity_children=int(request.POST.get('capacity_children') or 0),
            house_rules=request.POST.get('house_rules', ''),
            rate=request.POST.get('rate') or 0,
            status=request.POST.get('status', Staycation.Status.ACTIVE),
        )
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for index, image in enumerate(photos):
            StaycationPhoto.objects.create(staycation=staycation, image=image, is_primary=(index == 0))
        log_activity(request.user, "Created staycation",
                     f"{staycation.name} ({staycation.establishment_id})")
        messages.success(request, f"Staycation '{staycation.name}' created (ID: {staycation.establishment_id}).")
        return redirect('staycations:manage')
    return render(request, 'staycations/form.html', {'staycation': None})


@manager_required
@staycation_scope.decorator()
def update_staycation(request, staycation_id):
    staycation = get_object_or_404(Staycation, pk=staycation_id)
    if request.method == 'POST':
        for field in ('name', 'country', 'province', 'municipality', 'barangay', 'contact_number', 'email',
                      'house_rules', 'rate', 'status'):
            setattr(staycation, field, request.POST.get(field) or getattr(staycation, field))
        for field in ('capacity', 'capacity_adults', 'capacity_children'):
            try:
                setattr(staycation, field, int(request.POST.get(field) or getattr(staycation, field)))
            except (TypeError, ValueError):
                pass
        staycation.save()
        photos = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
        for image in photos:
            StaycationPhoto.objects.create(staycation=staycation, image=image, is_primary=not staycation.photos.exists())
        for photo in staycation.photos.filter(pk__in=request.POST.getlist('delete_photos')):
            photo.delete()
        if staycation.photos.exists() and not staycation.photos.filter(is_primary=True).exists():
            first = staycation.photos.first()
            first.is_primary = True
            first.save(update_fields=['is_primary'])
        log_activity(request.user, "Updated staycation",
                     f"{staycation.name} ({staycation.establishment_id})")
        messages.success(request, "Staycation updated.")
        return redirect('staycations:manage')
    return render(request, 'staycations/form.html', {'staycation': staycation})


def staycation_detail(request, staycation_id):
    """FR-003 VIEW Staycation – full detail profile (capacity, services, house rules)."""
    staycation = get_object_by_slug_or_404(
        Staycation.objects.prefetch_related('services', 'blocked_dates', 'photos'),
        staycation_id,
    )
    if staycation.status != Staycation.Status.ACTIVE and not (getattr(request.user, 'is_staff', False) or getattr(request.user, 'account_type', None) in ('ADMIN', 'INSTRUCTOR')):
        messages.error(request, "This staycation is currently unavailable.")
        return redirect('staycations:list')
    return render(request, 'staycations/detail.html', {
        'staycation': staycation,
        'is_manager': getattr(request.user, 'is_staff', False) or getattr(request.user, 'account_type', None) in ('ADMIN', 'INSTRUCTOR'),
    })


@manager_required
@staycation_scope.decorator()
def add_service(request, staycation_id):
    staycation = get_object_or_404(Staycation, pk=staycation_id)
    if request.method == 'POST':
        service = Service.objects.create(
            staycation=staycation,
            name=request.POST.get('name'),
            description=request.POST.get('description', ''),
            rate=request.POST.get('rate') or 0,
            operating_hours=request.POST.get('operating_hours', ''),
            status=request.POST.get('status', Service.ServiceStatus.ACTIVE),
        )
        log_activity(request.user, "Added staycation service",
                     f"{service.name} ({service.service_id}) in {staycation.name}")
        messages.success(request, f"Service '{service.name}' added (ID: {service.service_id}).")
        if request.POST.get('return_to_manage'):
            return redirect('staycations:manage')
        if request.POST.get('return_to_detail'):
            return redirect('staycations:detail', staycation.slug)
        return redirect('staycations:update_staycation', staycation.id)
    return render(request, 'staycations/service_form.html', {'staycation': staycation, 'service': None})


@manager_required
@staycation_scope.decorator()
def update_service(request, service_id):
    service = get_object_or_404(Service, pk=service_id)
    if request.method == 'POST':
        for field in ('name', 'rate', 'status', 'description', 'operating_hours'):
            setattr(service, field, request.POST.get(field) or getattr(service, field))
        service.save()
        log_activity(request.user, "Updated staycation service",
                     f"{service.name} ({service.service_id}) in {service.staycation.name}")
        messages.success(request, "Service updated.")
        return redirect('staycations:update_staycation', service.staycation_id)
    return render(request, 'staycations/service_form.html', {'staycation': service.staycation, 'service': service})


@manager_required
@staycation_scope.decorator()
def services(request):
    """FR-002 Retrieve the Service of the Staycation – search by name, status, establishment."""
    qs = Service.objects.select_related('staycation').all()
    qs = staycation_scope.scope_qs(request, qs, field='staycation_id')
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    establishment = (request.GET.get('establishment') or '').strip()
    if q:
        qs = qs.filter(Q(service_id__icontains=q) | Q(name__icontains=q) | Q(staycation__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if establishment:
        qs = qs.filter(staycation__name__icontains=establishment)
    return render(request, 'staycations/services.html', {
        'services': qs,
        'q': q,
        'status': status,
        'establishment': establishment,
        'status_choices': Service.ServiceStatus.choices,
    })


@login_required
def service_detail(request, service_id):
    """FR-003/FR-004 View the Services of the Staycation – full details (active for customers)."""
    service = get_object_or_404(Service.objects.select_related('staycation'), pk=service_id)
    is_manager = request.user.is_staff or request.user.account_type in ('ADMIN', 'INSTRUCTOR')
    if service.status != Service.ServiceStatus.ACTIVE and not is_manager:
        messages.error(request, "This service is currently unavailable.")
        return redirect('staycations:detail', service.staycation.slug)
    return render(request, 'staycations/service_detail.html', {
        'service': service,
        'is_manager': is_manager,
    })


@manager_required
@staycation_scope.decorator()
def add_block_date(request, staycation_id):
    staycation = get_object_or_404(Staycation, pk=staycation_id)
    if request.method == 'POST':
        start = _parse_date(request.POST.get('start_date'), date.today())
        end = _parse_date(request.POST.get('end_date'), start)
        if end < start:
            start, end = end, start
        BlockOutDate.objects.create(staycation=staycation, start_date=start, end_date=end)
        messages.success(request, "Block-out dates added.")
        return redirect('staycations:update_staycation', staycation.id)
    return redirect('staycations:manage')


@manager_required
@staycation_scope.decorator()
def remove_block_date(request, block_id):
    block = get_object_or_404(BlockOutDate, pk=block_id)
    staycation_id = block.staycation_id
    block.delete()
    messages.success(request, "Block-out dates removed.")
    return redirect('staycations:update_staycation', staycation_id)


@login_required
@student_booking_required
def book_staycation(request, staycation_id):
    staycation = get_object_or_404(Staycation, pk=staycation_id)
    if not resource_is_bookable(staycation):
        messages.error(request, "This staycation is not currently bookable.")
        return redirect('staycations:list')
    base_in = date.today() + timedelta(days=1)
    base_out = base_in + timedelta(days=1)
    if request.method == 'POST':
        check_in = _parse_date(request.POST.get('check_in'), base_in)
        check_out = _parse_date(request.POST.get('check_out'), base_out)

        for block in staycation.blocked_dates.all():
            if check_in < block.end_date and check_out > block.start_date:
                messages.error(request, f"Selected dates fall on a block-out period ({block.start_date} to {block.end_date}).")
                return render(request, 'staycations/book.html', {
                    'staycation': staycation, 'check_in': check_in, 'check_out': check_out,
                    'nights': max(1, (check_out - check_in).days),
                    'services': staycation.services.filter(status=Service.ServiceStatus.ACTIVE),
                })

        if overlapping_booking_exists(
            Reservation, resource_field='staycation', resource=staycation,
            start=check_in, end=check_out,
        ):
            messages.error(request, "This staycation is already reserved for the selected dates.")
            return render(request, 'staycations/book.html', {
                'staycation': staycation, 'check_in': check_in, 'check_out': check_out,
                'nights': max(1, (check_out - check_in).days),
                'services': staycation.services.filter(status=Service.ServiceStatus.ACTIVE),
            })

        nights = max(1, (check_out - check_in).days)
        reservation = Reservation.objects.create(
            customer=request.user,
            staycation=staycation,
            check_in=check_in,
            check_out=check_out,
            number_of_adults=int(request.POST.get('adults') or 1),
            number_of_children=int(request.POST.get('children') or 0),
            special_requests=request.POST.get('special_requests', ''),
            payer_name=request.user.full_profile,
            payer_contact=request.user.contact_number or '',
            status=Reservation.Status.PENDING,
        )
        reservation.services.set(request.POST.getlist('services'))

        first_names = request.POST.getlist('additional_first_name')
        last_names = request.POST.getlist('additional_last_name')
        countries = request.POST.getlist('additional_country')
        for fn, ln, ct in zip(first_names, last_names, countries):
            if (fn or '').strip() and (ln or '').strip():
                from .models import AdditionalGuest
                AdditionalGuest.objects.create(
                    reservation=reservation,
                    first_name=fn.strip(),
                    last_name=ln.strip(),
                    country=(ct or '').strip(),
                )

        from simulation.completion import complete_guest_booking
        from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

        complete_guest_booking(
            request.user,
            task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
            booking_reference=reservation.booking_reference,
        )

        service_items = [
            {'label': s.name, 'description': 'Staycation service',
             'quantity': 1, 'rate': s.rate, 'amount': s.rate}
            for s in reservation.services.all()
        ]
        items = [{'label': 'Staycation', 'description': f"{staycation.name} x {nights} night(s)",
                  'quantity': nights, 'rate': staycation.rate, 'amount': staycation.rate * nights}]
        items += service_items
        total = staycation.rate * nights + sum(float(s.rate) for s in reservation.services.all())
        bill = create_bill(service='staycation', customer=request.user, items=items, booking=reservation)
        reservation.total_bill = total
        reservation.save(update_fields=['total_bill'])

        if request.POST.get('book_and_add') == '1':
            try:
                add_establishment_booking(request, reservation)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('staycations:booking_detail', reservation.id)
            messages.success(request, f'Added to this establishment booking: {reservation.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':


            add_booking_to_cart(request, reservation)


            messages.success(request, f"Added to your Trip Cart: {reservation.booking_reference}")


            return redirect('transactions:cart')



        if request.POST.get('pay_later') == 'on':
            messages.success(request, f"Reservation saved! Reference: {reservation.booking_reference} (pending payment)")
            return redirect('staycations:booking_detail', reservation.id)
        checkout(
            user=request.user,
            service='staycation',
            booking=reservation,
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=f"Staycation booking {reservation.booking_reference}",
            items=items,
            bill=bill,
        )
        reservation.refresh_from_db()
        reservation.amount_paid = total
        reservation.balance_due = 0
        reservation.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, f"Staycation booked! Reference: {reservation.booking_reference}")
        return redirect('staycations:booking_detail', reservation.id)
    return render(request, 'staycations/book.html', {
        'staycation': staycation,
        'check_in': base_in,
        'check_out': base_out,
        'nights': 1,
        'services': staycation.services.filter(status=Service.ServiceStatus.ACTIVE),
    })


@manager_required
@staycation_scope.decorator()
def bookings(request):
    qs = Reservation.objects.select_related('customer', 'staycation')
    qs = staycation_scope.scope_qs(request, qs, field='staycation_id')
    status = request.GET.get('status', '')
    staycation_id = request.GET.get('staycation', '')
    q = request.GET.get('q', '')
    check_in = request.GET.get('check_in', '')
    check_out = request.GET.get('check_out', '')
    sort = request.GET.get('sort', '')
    if status:
        qs = qs.filter(status=status)
    if staycation_id:
        qs = qs.filter(staycation_id=staycation_id)
    if q:
        qs = qs.filter(
            Q(booking_reference__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__first_name__icontains=q)
            | Q(customer__last_name__icontains=q)
        )
    if check_in:
        try:
            qs = qs.filter(check_in__gte=date.fromisoformat(check_in))
        except ValueError:
            pass
    if check_out:
        try:
            qs = qs.filter(check_out__lte=date.fromisoformat(check_out))
        except ValueError:
            pass
    sort_map = {
        'booking_date': '-created_at',
        'check_in': 'check_in',
        'check_out': 'check_out',
        'status': 'status',
    }
    qs = qs.distinct().order_by(sort_map.get(sort, '-created_at'))
    return render(request, 'staycations/bookings.html', {
        'bookings': qs,
        'status': status,
        'q': q,
        'check_in': check_in,
        'check_out': check_out,
        'sort': sort,
    })


@login_required
@staycation_scope.decorator()
def booking_detail(request, booking_id):
    from accounts.roles import can_manage_booking
    from transactions.models import Bill, Payment

    booking = get_object_or_404(Reservation.objects.select_related('customer', 'staycation'), pk=booking_id)
    if booking.customer_id != request.user.id and not can_manage_booking(request.user, 'staycations'):
        messages.warning(request, "You cannot view this booking.")
        return redirect('staycations:list')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()
    can_manage = bool(can_manage_booking(request.user, 'staycations'))

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')
        if action == 'confirm':
            confirm_booking(booking, request.user)
        elif action == 'decline':
            decline_booking(booking, request.user)
        elif action == 'checkin' or action == 'self_checkin':
            booking.status = Reservation.Status.CHECKED_IN
            booking.checked_in_at = timezone.now()
            booking.save(update_fields=['status', 'checked_in_at'])
            log_activity(request.user, "Guest checked in" + (" (self)" if action == 'self_checkin' else ""),
                         booking.booking_reference)
            messages.success(request, "Checked in." if action == 'self_checkin' else "Guest checked in.")
        elif action == 'checkout' or action == 'self_checkout':
            booking.status = Reservation.Status.CHECKED_OUT
            booking.checked_out_at = timezone.now()
            booking.save(update_fields=['status', 'checked_out_at'])
            log_activity(request.user, "Guest checked out" + (" (self)" if action == 'self_checkout' else ""),
                         booking.booking_reference)
            messages.success(request, "Checked out." if action == 'self_checkout' else "Guest checked out.")
        elif action == 'modify':
            booking.check_in = _parse_date(request.POST.get('check_in'), booking.check_in)
            booking.check_out = _parse_date(request.POST.get('check_out'), booking.check_out)
            booking.number_of_adults = int(request.POST.get('adults') or booking.number_of_adults)
            booking.number_of_children = int(request.POST.get('children') or booking.number_of_children)
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            booking.status = Reservation.Status.MODIFIED
            booking.save()
        elif action == 'cancel':
            cancel_booking(booking, request.user)
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='staycation',
                bill=bill,
            )
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('staycations:booking_detail', booking.id)

    return render(request, 'staycations/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'is_owner': request.user == booking.customer,
        'is_manager': can_manage_booking(request.user, 'staycations'),
    })


@login_required
def ticket_detail(request, booking_id):
    from atrue_core.etickets import eticket_detail
    return eticket_detail(request, 'staycations', booking_id)


@login_required
def ticket_pdf(request, booking_id):
    from atrue_core.etickets import eticket_pdf
    return eticket_pdf(request, 'staycations', booking_id)


# ---------------------------------------------------------------------------
# Shared establishment flow (atrue_core.establishment_flow)
# ---------------------------------------------------------------------------


@login_required
@student_booking_required
def staycation_flow_select(request, staycation_id):
    """Choose the stay, add optional services and confirm in one page."""
    from atrue_core.establishment_flow import handle_flow

    return handle_flow(request, 'staycation', staycation_id)
