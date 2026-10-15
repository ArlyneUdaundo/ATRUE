from datetime import datetime, timedelta

from transactions.cart import add_booking_to_cart
from transactions.establishment_flow import add_booking as add_establishment_booking
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.establishment_deletion import delete_booking_history, delete_linked_establishment_history
from atrue_core.image_utils import delete_image_record, is_valid_image
from atrue_core.services import (
    bill_for_booking,
    cancel_booking,
    checkout,
    compute_attraction_bill,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    record_payment,
    resource_is_bookable,
)
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from accounts.roles import effective_role_keys

from atrue_core.search_catalog import render_search_page

from .models import Landmark, LandmarkPhoto, Ticket
from .scope import landmark_scope


def _parse_datetime(value, fallback):
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback
    if dt.tzinfo is None:
        return timezone.make_aware(dt)
    return dt.astimezone(timezone.get_current_timezone())


def _capacity_remaining(destination, visit_date, destination_type, exclude_id=None):
    if not destination.capacity:
        return None
    qs = Ticket.objects.filter(
        destination_type=destination_type,
        visit_datetime__date=visit_date,
        destination=destination,
    ).exclude(status__in=[Ticket.Status.CANCELLED, Ticket.Status.DECLINED, Ticket.Status.USED])
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    used = qs.aggregate(total=Sum('number_of_visitors'))['total'] or 0
    return max(0, destination.capacity - used)


def landmark_list(request):
    destinations = Landmark.objects.prefetch_related('photos').filter(
        status=Landmark.Status.ACTIVE,
        category=Landmark.Category.LANDMARK,
    ).order_by('name')
    return render_search_page(request, 'landmark', destinations)


@manager_required
@landmark_scope.decorator()
def manage(request):
    landmarks = Landmark.objects.prefetch_related('photos').filter(category=Landmark.Category.LANDMARK)
    landmarks = landmark_scope.scope_queryset(request, landmarks)
    query = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()
    if query:
        search = (
            Q(name__icontains=query) | Q(description__icontains=query)
            | Q(country__icontains=query) | Q(region__icontains=query)
            | Q(province__icontains=query) | Q(municipality__icontains=query)
            | Q(barangay__icontains=query)
        )
        landmarks = landmarks.filter(search)
    if status in dict(Landmark.Status.choices):
        landmarks = landmarks.filter(status=status)
    return render(request, 'landmarks/manage.html', {
        'landmarks': landmarks,
        'query': query,
        'selected_status': status,
        'status_choices': Landmark.Status.choices,
        'can_delete': not landmark_scope.is_scoped(request.user),
        'landmark_owner': 'LANDMARK_OWNER' in effective_role_keys(request.user),
    })


def _save_attraction(category, request, instance=None, key=''):
    prefix = key + '_' if key else ''
    data = {
        'name': (request.POST.get(f'{prefix}name') or '').strip(),
        'description': request.POST.get(f'{prefix}description', ''),
        'country': request.POST.get(f'{prefix}country', ''),
        'region': request.POST.get(f'{prefix}region', ''),
        'province': request.POST.get(f'{prefix}province', ''),
        'municipality': request.POST.get(f'{prefix}municipality', ''),
        'barangay': request.POST.get(f'{prefix}barangay', ''),
        'contact_number': request.POST.get(f'{prefix}contact_number', ''),
        'open_hours': request.POST.get(f'{prefix}open_hours', ''),
        'entry_fee': request.POST.get(f'{prefix}entry_fee') or 0,
        'capacity': request.POST.get(f'{prefix}capacity') or 0,
        'guided_tour_rate': request.POST.get(f'{prefix}guided_tour_rate') or 0,
        'private_tour_rate': request.POST.get(f'{prefix}private_tour_rate') or 0,
        'status': request.POST.get(f'{prefix}status', 'ACTIVE'),
    }
    if not data['name']:
        raise ValueError('Name is required.')
    if data['status'] not in dict(Landmark.Status.choices):
        raise ValueError('Choose a valid status.')
    try:
        data['capacity'] = int(data['capacity'])
        if data['capacity'] < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Capacity must be zero or a positive whole number.')
    try:
        from decimal import Decimal, InvalidOperation
        for amount_field in ('entry_fee', 'guided_tour_rate', 'private_tour_rate'):
            data[amount_field] = Decimal(str(data[amount_field]))
            if data[amount_field] < 0:
                raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise ValueError('Fees must be valid non-negative amounts.')
    images = request.FILES.getlist('photos')
    if any(not is_valid_image(image) for image in images):
        raise ValueError('Upload valid JPEG, PNG, or WebP image files no larger than 10 MB.')
    if instance:
        for field, value in data.items():
            setattr(instance, field, value)
        instance.save()
    else:
        data['category'] = category
        instance = Landmark.objects.create(**data)
    for image in images:
        LandmarkPhoto.objects.create(landmark=instance, image=image, is_primary=not instance.photos.exists())
    for photo in instance.photos.filter(pk__in=request.POST.getlist('delete_photos')):
        delete_image_record(photo)
    if instance.photos.exists() and not instance.photos.filter(is_primary=True).exists():
        first = instance.photos.first()
        first.is_primary = True
        first.save(update_fields=['is_primary'])
    return instance


@manager_required
@landmark_scope.decorator()
def add_spot(request):
    if request.method == 'POST':
        spot = _save_attraction(Landmark.Category.TOURIST_SPOT, request)
        log_activity(request.user, "Created tourist spot", spot.name)
        messages.success(request, f"Tourist spot '{spot.name}' created.")
        return redirect('landmarks:manage')
    return render(request, 'landmarks/spot_form.html', {'spot': None, 'title': 'Tourist Spot'})


@manager_required
@landmark_scope.decorator()
def update_spot(request, spot_id):
    spot = get_object_or_404(
        landmark_scope.scope_queryset(request, Landmark.objects.prefetch_related('photos')),
        pk=spot_id,
        category=Landmark.Category.TOURIST_SPOT,
    )
    if request.method == 'POST':
        try:
            _save_attraction(Landmark.Category.TOURIST_SPOT, request, instance=spot)
        except (ValueError, ValidationError) as exc:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
                return JsonResponse({'ok': False, 'errors': errors}, status=400)
            messages.error(request, str(exc))
            return render(request, 'landmarks/spot_form.html', {'spot': spot, 'title': 'Tourist Spot'}, status=400)
        log_activity(request.user, "Updated tourist spot", spot.name)
        messages.success(request, "Tourist spot updated.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            photo = spot.photos.first()
            return JsonResponse({'ok': True, 'id': spot.pk, 'name': spot.name,
                'location': spot.location, 'status': spot.status,
                'status_display': spot.get_status_display(),
                'image_url': photo.image.url if photo and photo.image else ''})
        return redirect('landmarks:manage')
    return render(request, 'landmarks/spot_form.html', {'spot': spot, 'title': 'Tourist Spot'})


@manager_required
@landmark_scope.decorator()
def add_landmark(request):
    if request.method == 'POST':
        landmark = _save_attraction(Landmark.Category.LANDMARK, request)
        log_activity(request.user, "Created landmark", landmark.name)
        messages.success(request, f"Landmark '{landmark.name}' created.")
        return redirect('landmarks:manage')
    return render(request, 'landmarks/landmark_form.html', {'landmark': None, 'title': 'Landmark'})


@manager_required
@landmark_scope.decorator()
def update_landmark(request, landmark_id):
    landmark = get_object_or_404(
        landmark_scope.scope_queryset(request, Landmark.objects.prefetch_related('photos')),
        pk=landmark_id,
        category=Landmark.Category.LANDMARK,
    )
    if request.method == 'POST':
        try:
            _save_attraction(Landmark.Category.LANDMARK, request, instance=landmark)
        except (ValueError, ValidationError) as exc:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
                return JsonResponse({'ok': False, 'errors': errors}, status=400)
            messages.error(request, str(exc))
            return render(request, 'landmarks/landmark_form.html', {'landmark': landmark, 'title': 'Landmark'}, status=400)
        log_activity(request.user, "Updated landmark", landmark.name)
        messages.success(request, "Landmark updated.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            photo = landmark.photos.first()
            return JsonResponse({'ok': True, 'id': landmark.pk, 'name': landmark.name,
                'location': landmark.location, 'status': landmark.status,
                'status_display': landmark.get_status_display(),
                'image_url': photo.image.url if photo and photo.image else ''})
        return redirect('landmarks:manage')
    return render(request, 'landmarks/landmark_form.html', {'landmark': landmark, 'title': 'Landmark'})


@manager_required
@landmark_scope.decorator()
def delete_landmark(request, landmark_id):
    if request.method != 'POST':
        messages.warning(request, 'Invalid request.')
        return redirect('landmarks:manage')
    landmark = get_object_or_404(
        landmark_scope.scope_queryset(request, Landmark.objects.all()),
        pk=landmark_id,
        category=Landmark.Category.LANDMARK,
    )
    name = landmark.name
    try:
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            delete_booking_history(Ticket.objects.filter(destination=landmark))
            delete_linked_establishment_history(landmark)
            landmark.delete()
    except ProtectedError:
        messages.error(request, f"Landmark '{name}' is linked to existing records and cannot be deleted. Set its status to Inactive instead.")
        return redirect('landmarks:manage')
    log_activity(request.user, 'Deleted landmark', name)
    messages.success(request, f"Landmark '{name}' and its ticket history deleted.")
    return redirect('landmarks:manage')


def _render_ticket_page(request, *, destination_type, destination, name, fee, cancel_url,
                        guided_tour_rate, private_tour_rate):
    default_date = timezone.now() + timedelta(days=3)
    remaining = _capacity_remaining(destination, default_date.date(), destination_type)
    if request.method == 'POST':
        when = _parse_datetime(request.POST.get('visit_datetime'), default_date)
        visitors = int(request.POST.get('visitors') or 1)
        remaining_on_date = _capacity_remaining(destination, when.date(), destination_type)
        if remaining_on_date is not None and visitors > remaining_on_date:
            messages.error(request, f"Only {remaining_on_date} visitor slot(s) remain for this date.")
            return render(request, 'landmarks/book.html', {
                'name': name, 'fee': fee, 'default_date': default_date,
                'guided_tour_rate': guided_tour_rate, 'private_tour_rate': private_tour_rate,
                'remaining': remaining_on_date,
            })

        tour = request.POST.get('guided_tour', Ticket.GuidedTour.NONE)
        tour_rate = {'NONE': 0, 'STANDARD': guided_tour_rate, 'PRIVATE': private_tour_rate}.get(tour, 0)
        tour_participants = visitors if tour == 'STANDARD' else (1 if tour == 'PRIVATE' else 0)

        equipment_rate = float(request.POST.get('equipment_rate') or 0)
        equipment_qty = int(request.POST.get('equipment_quantity') or 0)
        equipment_charge = equipment_rate * equipment_qty
        equipment_charges = ([{'label': 'Equipment rental',
                               'quantity': equipment_qty, 'rate': equipment_rate,
                               'amount': equipment_charge}] if equipment_qty else None)

        items = compute_attraction_bill(fee, visitors, guided_tour_rate=tour_rate,
                                        tour_participants=tour_participants,
                                        equipment_charges=equipment_charges)
        total = float(fee) * visitors + float(tour_rate) * tour_participants + equipment_charge

        ticket = Ticket.objects.create(
            customer=request.user,
            destination_type=destination_type,
            destination=destination,
            visit_datetime=when,
            number_of_visitors=visitors,
            guided_tour=tour,
            equipment_rate=equipment_rate,
            equipment_quantity=equipment_qty,
            special_requests=request.POST.get('special_requests', ''),
            payer_name=request.POST.get('payer_name', ''),
            payer_contact=request.POST.get('payer_contact', ''),
            status=Ticket.Status.PENDING,
        )
        bill = create_bill(service='ticket', customer=request.user, items=items, booking=ticket)
        ticket.total_bill = total
        ticket.save(update_fields=['total_bill'])

        from simulation.completion import complete_guest_booking
        from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

        complete_guest_booking(
            request.user,
            task_assignment_id=request.session.get(TASK_ASSIGNMENT_SESSION_KEY),
            booking_reference=ticket.booking_reference,
        )

        if request.POST.get('book_and_add') == '1':
            try:
                add_establishment_booking(request, ticket)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('landmarks:booking_detail', ticket.id)
            messages.success(request, f'Added to this establishment booking: {ticket.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':
            add_booking_to_cart(request, ticket)
            messages.success(request, f"Ticket added to your Trip Cart: {ticket.booking_reference}")
            return redirect('transactions:cart')

        if request.POST.get('pay_later') == 'on':
            messages.success(request, f"Ticket saved! Reference: {ticket.booking_reference} (pending payment)")
            return redirect('landmarks:booking_detail', ticket.id)
        checkout(
            user=request.user,
            service='ticket',
            booking=ticket,
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=f"Ticket {ticket.booking_reference}",
            items=items,
            bill=bill,
        )
        ticket.refresh_from_db()
        ticket.amount_paid = total
        ticket.balance_due = 0
        ticket.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, f"Ticket purchased! Reference: {ticket.booking_reference}")
        return redirect('landmarks:booking_detail', ticket.id)
    return render(request, 'landmarks/book.html', {
        'name': name, 'fee': fee, 'default_date': default_date,
        'guided_tour_rate': guided_tour_rate, 'private_tour_rate': private_tour_rate,
        'remaining': remaining,
    })


@login_required
@student_booking_required
def book_spot(request, spot_id):
    spot = get_object_or_404(Landmark, pk=spot_id, category=Landmark.Category.TOURIST_SPOT)
    if not resource_is_bookable(spot):
        messages.error(request, "This tourist spot is not currently bookable.")
        return redirect('landmarks:list')
    return _render_ticket_page(
        request,
        destination_type=Ticket.DestinationType.TOURIST_SPOT,
        destination=spot,
        name=spot.name,
        fee=spot.entry_fee,
        cancel_url='landmarks:list',
        guided_tour_rate=spot.guided_tour_rate,
        private_tour_rate=spot.private_tour_rate,
    )


@login_required
@student_booking_required
def book_landmark(request, landmark_id):
    landmark = get_object_or_404(Landmark, pk=landmark_id, category=Landmark.Category.LANDMARK)
    if not resource_is_bookable(landmark):
        messages.error(request, "This landmark is not currently bookable.")
        return redirect('landmarks:list')
    return _render_ticket_page(
        request,
        destination_type=Ticket.DestinationType.LANDMARK,
        destination=landmark,
        name=landmark.name,
        fee=landmark.entry_fee,
        cancel_url='landmarks:list',
        guided_tour_rate=landmark.guided_tour_rate,
        private_tour_rate=landmark.private_tour_rate,
    )


@manager_required
@landmark_scope.decorator()
def bookings(request):
    from accounts.roles import landmark_work_queue

    queue = landmark_work_queue(request.user)
    default_status = 'PENDING' if queue == 'confirm' else 'CONFIRMED' if queue == 'checkin' else ''
    status = request.GET.get('status', default_status)
    qs = Ticket.objects.select_related('customer', 'destination')
    qs = landmark_scope.scope_qs(request, qs, field='destination_id')
    if status:
        qs = qs.filter(status=status)
    return render(request, 'landmarks/bookings.html', {
        'bookings': qs,
        'status': status,
        'queue': queue,
    })


@login_required
@landmark_scope.decorator()
def booking_detail(request, booking_id):
    from accounts.roles import (
        can_checkin_landmark_booking,
        can_confirm_landmark_booking,
        can_manage_booking,
    )
    from transactions.models import Bill, Payment

    booking = get_object_or_404(Ticket.objects.select_related('customer', 'destination'), pk=booking_id)
    if booking.customer_id != request.user.id and not can_manage_booking(request.user, 'landmarks'):
        messages.warning(request, "You cannot view this ticket.")
        return redirect('landmarks:list')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()
    can_manage = bool(can_manage_booking(request.user, 'landmarks'))
    can_confirm = bool(can_confirm_landmark_booking(request.user))
    can_checkin = bool(can_checkin_landmark_booking(request.user))

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')
        if action == 'confirm':
            if not can_confirm:
                messages.error(request, "Only the landmark reservation officer can confirm this ticket.")
                return redirect('landmarks:booking_detail', booking.id)
            confirm_booking(booking, request.user)
            if getattr(booking, 'payment_review_pending', False):
                messages.warning(request, 'Waiting for the Billing Officer to verify full payment before confirmation.')
        elif action == 'decline':
            if not can_confirm:
                messages.error(request, "Only the landmark reservation officer can decline this ticket.")
                return redirect('landmarks:booking_detail', booking.id)
            decline_booking(booking, request.user)
        elif action == 'use':
            if not can_checkin:
                messages.error(request, "Only the landmark front desk officer can check this ticket in.")
                return redirect('landmarks:booking_detail', booking.id)
            booking.status = Ticket.Status.USED
            booking.save(update_fields=['status'])
            log_activity(request.user, "Ticket checked in", str(booking.pk))
        elif action == 'modify':
            booking.number_of_visitors = int(request.POST.get('visitors') or booking.number_of_visitors)
            booking.visit_datetime = _parse_datetime(request.POST.get('visit_datetime'), booking.visit_datetime)
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            booking.status = Ticket.Status.MODIFIED
            booking.save()
        elif action == 'cancel':
            cancel_booking(booking, request.user)
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='ticket',
                bill=bill,
            )
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('landmarks:booking_detail', booking.id)

    return render(request, 'landmarks/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'can_print_ticket': booking.customer_id == request.user.id and not request.user.is_staff and not can_manage,
        'can_confirm': can_confirm,
        'can_checkin': can_checkin,
    })


@login_required
def ticket_detail(request, booking_id):
    from atrue_core.etickets import eticket_detail
    return eticket_detail(request, 'landmarks', booking_id)


@login_required
def ticket_pdf(request, booking_id):
    from atrue_core.etickets import eticket_pdf
    return eticket_pdf(request, 'landmarks', booking_id)


# ---------------------------------------------------------------------------
# Shared establishment flow (atrue_core.establishment_flow)
# ---------------------------------------------------------------------------


def landmark_detail(request, pk):
    """Establishment detail step for a landmark / tourist spot.

    Landmarks previously jumped straight from the search results to the ticket
    form, so they had no detail page.  This renders the shared detail step and
    links onward to the shared selection page.
    """
    from atrue_core.establishment_flow import detail_context, get_adapter

    landmark = get_object_or_404(
        Landmark.objects.filter(status=Landmark.Status.ACTIVE).prefetch_related('photos'),
        pk=pk,
    )
    adapter = get_adapter('landmark')
    from datetime import date, timedelta

    check_in = adapter.default_date(landmark, date.today() + timedelta(days=1))
    from atrue_core.establishment_flow import parse_date

    check_in = parse_date(request.GET.get('date'), check_in)
    check_out = parse_date(request.GET.get('check_out'), check_in + timedelta(days=1))
    if check_out <= check_in:
        check_out = check_in + timedelta(days=1)
    context = detail_context(adapter, landmark, check_in, check_out)
    # The shared detail page is also used by public visitors. Show the
    # management shortcuts only to accounts that can enter management flows.
    from accounts.roles import can_access_module
    context['is_landmark_manager'] = bool(
        request.user.is_authenticated and can_access_module(request.user, 'landmarks')
    )
    context['landmark_edit_url'] = (
        'landmarks:update_landmark' if landmark.category == Landmark.Category.LANDMARK
        else 'landmarks:update_spot'
    )
    return render(request, 'establishments/detail.html', context)


@login_required
@student_booking_required
def landmark_flow_select(request, pk):
    """Choose the visit, add guest details and buy the entry pass in one page."""
    from atrue_core.establishment_flow import handle_flow

    return handle_flow(request, 'landmark', pk)
