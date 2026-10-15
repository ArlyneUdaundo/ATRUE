from datetime import date, time

from transactions.cart import add_booking_to_cart
from transactions.establishment_flow import add_booking as add_establishment_booking
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from atrue_core.decorators import manager_required, student_booking_required
from atrue_core.establishment_deletion import delete_booking_history, delete_linked_establishment_history
from atrue_core.image_utils import delete_image_record, is_valid_image
from atrue_core.services import (
    bill_for_booking,
    cancel_booking,
    checkout,
    compute_activity_bill,
    confirm_booking,
    create_bill,
    decline_booking,
    log_activity,
    record_payment,
    resource_is_bookable,
)
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError
from django.db.models import Sum
from accounts.roles import effective_role_keys
from django.shortcuts import get_object_or_404, redirect, render

from atrue_core.search_catalog import render_search_page
from .scope import (
    activity_guest_booking_required,
    activity_role_required,
    assigned_activity_ids_for_roles,
    is_activity_platform_user,
    scope_activities,
    scope_bookings,
    scope_providers,
)

from .models import Activity, ActivityPhoto, ActivityProvider, Booking


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




def _compose_activity_location(request, fallback=''):
    province=(request.POST.get('location_province') or '').strip()
    municipality=(request.POST.get('location_municipality') or '').strip()
    barangay=(request.POST.get('location_barangay') or '').strip()
    country=(request.POST.get('location_country') or '').strip()
    if province or municipality or barangay:
        pieces = ([barangay, municipality, province] if barangay
                  else [municipality, province] if province
                  else [municipality])
        if country:
            pieces.append(country)
        return ', '.join(pieces)
    return (request.POST.get('location') or fallback or '').strip()

def _slots_remaining(activity, schedule_date, exclude_id=None):
    if not activity.capacity:
        return None
    qs = Booking.objects.filter(activity=activity, schedule_date=schedule_date).exclude(
        status__in=[Booking.Status.CANCELLED, Booking.Status.DECLINED])
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    used = qs.aggregate(total=Sum('participant_count'))['total'] or 0
    return max(0, activity.capacity - used)


def activity_list(request):
    activities = Activity.objects.select_related('provider').prefetch_related('photos')
    if request.user.is_authenticated and request.user.is_platform_manager:
        # Managers can see new activities before their provider verification is complete.
        activities = scope_activities(request, activities)
    else:
        # Publish every active activity in the catalogue. The card still marks
        # activities unavailable until their provider is verified.
        activities = activities.filter(status=Activity.Status.ACTIVE)
    return render_search_page(request, 'activity', activities)


@manager_required
@activity_role_required('ACTIVITY_MANAGER')
def manage(request):
    activities = scope_activities(
        request,
        Activity.objects.select_related('provider').prefetch_related('photos').all(),
    )
    return render(request, 'activities/manage.html', {
        'activities': activities,
        'can_delete': is_activity_platform_user(request.user),
        'activity_owner': 'ACTIVITY_OWNER' in effective_role_keys(request.user),
    })


def _save_activity(request, provider, instance=None):
    data = {
        'name': request.POST.get('name'),
        'description': request.POST.get('description', ''),
        'category': request.POST.get('category', 'OUTDOOR'),
        'location': _compose_activity_location(request, instance.location if instance else ''),
        'location_barangay': request.POST.get('location_barangay', ''),
        'location_municipality': request.POST.get('location_municipality', ''),
        'location_province': request.POST.get('location_province', ''),
        'location_country': request.POST.get('location_country', ''),
        'meeting_point': request.POST.get('meeting_point', ''),
        'duration_minutes': int(request.POST.get('duration_minutes') or 60),
        'duration_unit': request.POST.get('duration_unit', 'MINUTES'),
        'required_documents': request.POST.get('required_documents', ''),
        'schedule_date': _parse_date(request.POST.get('schedule_date'), None),
        'schedule_time': _parse_time(request.POST.get('schedule_time'), None),
        'fee': request.POST.get('fee') or 0,
        'capacity': int(request.POST.get('capacity') or 1),
        'requirements': request.POST.get('requirements', ''),
        'required_equipment': request.POST.get('required_equipment', ''),
        'guide_required': request.POST.get('guide_required') == 'on',
        'status': request.POST.get('status', 'ACTIVE'),
    }
    if instance:
        for field, value in data.items():
            setattr(instance, field, value)
        instance.save()
    else:
        instance = Activity.objects.create(provider=provider, **data)

    image = request.FILES.get('image')
    if image and is_valid_image(image):
        instance.image = image
        instance.save(update_fields=['image'])
    images = [f for f in request.FILES.getlist('photos') if is_valid_image(f)]
    for image in images:
        ActivityPhoto.objects.create(activity=instance, image=image, is_primary=not instance.photos.exists())
    for photo in instance.photos.filter(pk__in=request.POST.getlist('delete_photos')):
        delete_image_record(photo)
    if instance.photos.exists() and not instance.photos.filter(is_primary=True).exists():
        first = instance.photos.first()
        first.is_primary = True
        first.save(update_fields=['is_primary'])
    return instance


@manager_required
@activity_role_required('ACTIVITY_MANAGER')
def add_activity(request):
    provider = None
    providers = scope_providers(request, ActivityProvider.objects.all())
    if request.method == 'POST':
        pid = (request.POST.get('provider') or '').strip()
        if not providers.exists():
            messages.error(request, "Add or assign an activity provider before creating an activity.")
            provider = None
        elif pid and (not pid.isdigit() or not providers.filter(pk=int(pid)).exists()):
            messages.error(request, "The selected activity provider is unavailable.")
            provider = providers.first()
        else:
            provider = providers.get(pk=int(pid)) if pid else providers.first()
        if provider is None:
            return render(request, 'activities/activity_form.html', {
                'activity': None, 'providers': providers, 'selected_provider': None})
        activity = _save_activity(request, provider)
        log_activity(request.user, "Created activity", activity.name)
        messages.success(request, f"Activity '{activity.name}' created.")
        return redirect('activities:manage')
    if request.GET.get('provider'):
        provider = get_object_or_404(providers, pk=request.GET['provider'])
    else:
        provider = providers.first()
    return render(request, 'activities/activity_form.html', {'activity': None, 'providers': providers,
                                                             'selected_provider': provider})


@manager_required
@activity_role_required('ACTIVITY_MANAGER')
def update_activity(request, activity_id):
    activity = get_object_or_404(
        scope_activities(request, Activity.objects.prefetch_related('photos')),
        pk=activity_id,
    )
    if request.method == 'POST':
        _save_activity(request, activity.provider, instance=activity)
        log_activity(request.user, "Updated activity", activity.name)
        messages.success(request, "Activity updated.")
        return redirect('activities:manage')
    return render(request, 'activities/activity_form.html', {'activity': activity})


@manager_required
@activity_role_required('ACTIVITY_MANAGER')
def delete_activity(request, activity_id):
    if request.method != 'POST':
        messages.warning(request, 'Invalid request.')
        return redirect('activities:manage')
    activity = get_object_or_404(scope_activities(request, Activity.objects.all()), pk=activity_id)
    name = activity.name
    try:
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            delete_booking_history(Booking.objects.filter(activity=activity))
            delete_linked_establishment_history(activity)
            activity.delete()
    except ProtectedError:
        messages.error(request, f"Activity '{name}' is linked to existing records and cannot be deleted. Set its status to Inactive instead.")
        return redirect('activities:manage')
    log_activity(request.user, 'Deleted activity', name)
    messages.success(request, f"Activity '{name}' and its booking history deleted.")
    return redirect('activities:manage')


@login_required
@student_booking_required
@activity_guest_booking_required
def book_activity(request, activity_id):
    activity = get_object_or_404(Activity.objects.select_related('provider'), pk=activity_id)
    if not activity.bookable or not resource_is_bookable(activity.provider):
        messages.error(request, "This activity is not currently bookable.")
        return redirect('activities:list')

    default_date = date.today()
    remaining = _slots_remaining(activity, default_date)
    if request.method == 'POST':
        when = _parse_date(request.POST.get('schedule_date'), default_date)
        participants = int(request.POST.get('participants') or 1)
        remaining_on_date = _slots_remaining(activity, when)
        if remaining_on_date is not None and participants > remaining_on_date:
            messages.error(request, f"This activity has only {remaining_on_date} slot(s) open on that date (BR-067).")
            return render(request, 'activities/book.html', {
                'activity': activity, 'default_date': default_date, 'remaining': remaining_on_date,
            })

        total = float(activity.fee) * participants
        booking = Booking.objects.create(
            customer=request.user,
            activity=activity,
            schedule_date=when,
            start_time=_parse_time(request.POST.get('start_time'), None),
            end_time=_parse_time(request.POST.get('end_time'), None),
            participant_count=participants,
            special_requests=request.POST.get('special_requests', ''),
            payer_name=request.POST.get('payer_name', ''),
            payer_contact=request.POST.get('payer_contact', ''),
            status=Booking.Status.PENDING,
        )
        items = compute_activity_bill(activity, participants)
        bill = create_bill(service='activity', customer=request.user, items=items, booking=booking)
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
                return redirect('activities:booking_detail', booking.id)
            messages.success(request, f'Added to this establishment booking: {booking.booking_reference}')
            return redirect('transactions:establishment_booking')

        if request.POST.get('add_to_cart') == '1':


            add_booking_to_cart(request, booking)


            messages.success(request, f"Added to your Trip Cart: {booking.booking_reference}")


            return redirect('transactions:cart')



        if request.POST.get('pay_later') == 'on':
            messages.success(request, f"Activity booking saved! Reference: {booking.booking_reference} (pending payment)")
            return redirect('activities:booking_detail', booking.id)
        checkout(
            user=request.user,
            service='activity',
            booking=booking,
            amount=total,
            payment_method=request.POST.get('payment_method', 'GCASH'),
            description=f"Activity booking {booking.booking_reference}",
            items=items,
            bill=bill,
        )
        booking.refresh_from_db()
        booking.amount_paid = total
        booking.balance_due = 0
        booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, f"Activity booked! Reference: {booking.booking_reference}")
        return redirect('activities:booking_detail', booking.id)
    return render(request, 'activities/book.html', {
        'activity': activity, 'default_date': default_date, 'remaining': remaining,
    })


@manager_required
@activity_role_required(
    'ACTIVITY_RESERVATION_OFFICER',
    'ACTIVITY_FRONT_DESK_OFFICER',
    'ACTIVITY_OPERATOR',
)
def bookings(request):
    status = request.GET.get('status', '')
    qs = scope_bookings(
        request,
        Booking.objects.select_related('customer', 'activity').all(),
    )
    if status:
        qs = qs.filter(status=status)
    return render(request, 'activities/bookings.html', {
        'bookings': qs, 'status': status, 'status_choices': Booking.Status.choices,
    })


@login_required
def booking_detail(request, booking_id):
    from transactions.models import Bill, Payment

    booking = get_object_or_404(Booking.objects.select_related('customer', 'activity', 'activity__provider'),
                                pk=booking_id)
    platform_user = is_activity_platform_user(request.user)
    is_customer = booking.customer_id == request.user.id
    reservation_ids = assigned_activity_ids_for_roles(
        request, {'ACTIVITY_RESERVATION_OFFICER'})
    frontdesk_ids = assigned_activity_ids_for_roles(
        request, {'ACTIVITY_FRONT_DESK_OFFICER', 'ACTIVITY_OPERATOR'})
    operator_ids = assigned_activity_ids_for_roles(request, {'ACTIVITY_OPERATOR'})
    can_reserve = platform_user or (reservation_ids is not None and booking.activity_id in reservation_ids)
    can_frontdesk = platform_user or (frontdesk_ids is not None and booking.activity_id in frontdesk_ids)
    can_operator = platform_user or (operator_ids is not None and booking.activity_id in operator_ids)
    if not is_customer and not (can_reserve or can_frontdesk):
        raise PermissionDenied('You cannot view this activity booking.')

    bill = bill_for_booking(booking)
    payments = bill.payments.all() if bill else Payment.objects.none()
    can_manage = can_reserve or can_frontdesk

    if request.method == 'POST':
        action = request.POST.get('action')
        allowed_actions = set()
        if can_reserve:
            allowed_actions.update({'confirm', 'decline', 'modify', 'cancel'})
        if can_frontdesk:
            allowed_actions.add('attend')
        if can_operator:
            allowed_actions.update({'complete', 'pay'})
        if action not in allowed_actions:
            raise PermissionDenied('This booking action is not allowed for your activity role.')
        if action == 'confirm':
            confirm_booking(booking, request.user)
            if getattr(booking, 'payment_review_pending', False):
                messages.warning(request, 'Waiting for the Billing Officer to verify full payment before confirmation.')
        elif action == 'decline':
            decline_booking(booking, request.user)
        elif action == 'attend':
            if booking.status != Booking.Status.CONFIRMED:
                raise PermissionDenied('Only confirmed activity bookings may be checked in.')
            booking.status = Booking.Status.CHECKED_IN
            booking.save(update_fields=['status'])
            log_activity(request.user, "Activity booking attended", str(booking.pk))
        elif action == 'complete':
            if booking.status != Booking.Status.CHECKED_IN:
                raise PermissionDenied('Only checked-in activity bookings may be completed.')
            booking.status = Booking.Status.COMPLETED
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['status', 'amount_paid', 'balance_due'])
        elif action == 'modify':
            when = _parse_date(request.POST.get('schedule_date'), booking.schedule_date)
            remaining_on_date = _slots_remaining(booking.activity, when, exclude_id=booking.id)
            participants = int(request.POST.get('participants') or booking.participant_count)
            if remaining_on_date is not None and participants > remaining_on_date:
                messages.error(request, "Insufficient capacity for those slots on the new date.")
                return redirect('activities:booking_detail', booking.id)
            booking.schedule_date = when
            booking.participant_count = participants
            booking.special_requests = request.POST.get('special_requests', booking.special_requests)
            booking.status = Booking.Status.MODIFIED
            booking.save()
        elif action == 'cancel':
            cancel_booking(booking, request.user)
        elif action == 'pay':
            record_payment(
                customer=request.user if request.user == booking.customer else booking.customer,
                amount=request.POST.get('amount') or 0,
                method=request.POST.get('payment_method', 'GCASH'),
                service='activity',
                bill=bill,
            )
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['amount_paid', 'balance_due'])
        messages.success(request, "Action completed.")
        return redirect('activities:booking_detail', booking.id)

    return render(request, 'activities/booking_detail.html', {
        'booking': booking,
        'bill': bill,
        'payments': payments,
        'can_manage': can_manage,
        'can_print_ticket': booking.customer_id == request.user.id and not request.user.is_staff and not can_manage,
    })


@login_required
def ticket_detail(request, booking_id):
    _require_activity_ticket_access(request, booking_id)
    from atrue_core.etickets import eticket_detail
    return eticket_detail(request, 'activities', booking_id)


@login_required
def ticket_pdf(request, booking_id):
    _require_activity_ticket_access(request, booking_id)
    from atrue_core.etickets import eticket_pdf
    return eticket_pdf(request, 'activities', booking_id)


def _require_activity_ticket_access(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    from accounts.roles import can_manage_booking
    if (booking.customer_id == request.user.id
            and not request.user.is_staff
            and not can_manage_booking(request.user, 'activities')):
        return
    raise PermissionDenied('Only the guest who owns this activity booking may print its ticket.')


# ---------------------------------------------------------------------------
# Shared establishment flow (atrue_core.establishment_flow)
# ---------------------------------------------------------------------------


def activity_detail(request, pk):
    """Establishment detail step for an activity session."""
    from atrue_core.establishment_flow import detail_context, get_adapter

    activity = get_object_or_404(
        Activity.objects.select_related('provider').prefetch_related('photos'),
        pk=pk,
    )
    adapter = get_adapter('activity')
    from datetime import timedelta

    from atrue_core.establishment_flow import parse_date

    check_in = parse_date(
        request.GET.get('date'), adapter.default_date(activity, date.today() + timedelta(days=1))
    )
    check_out = check_in + timedelta(days=1)
    context = detail_context(adapter, activity, check_in, check_out)
    context['is_activity_manager'] = bool(
        request.user.is_authenticated
        and (is_activity_platform_user(request.user)
             or 'ACTIVITY_MANAGER' in effective_role_keys(request.user))
    )
    return render(request, 'establishments/detail.html', context)


@login_required
@student_booking_required
@activity_guest_booking_required
def activity_flow_select(request, pk):
    """Choose the session, add participant details and confirm in one page."""
    from atrue_core.establishment_flow import handle_flow

    return handle_flow(request, 'activity', pk)


@manager_required
@activity_role_required('ACTIVITY_FRONT_DESK_OFFICER', 'ACTIVITY_OPERATOR')
def operate(request):
    """Run the assigned activity on the day: attend and complete its bookings
    and keep the activity's operational status current (operator's page)."""
    if request.method == 'POST':
        action = request.POST.get('action')
        activity = get_object_or_404(
            scope_activities(
                request,
                Activity.objects.select_related('provider').prefetch_related('photos').all(),
            ),
            pk=request.POST.get('activity_id'),
        )
        booking = None
        if action in {'attend', 'complete'}:
            booking = get_object_or_404(
                scope_bookings(request, Booking.objects.select_related('customer').all()),
                pk=request.POST.get('booking_id'),
            )
            if booking.activity_id != activity.id:
                raise PermissionDenied('This booking does not belong to the selected activity.')
        if action == 'attend':
            authorized_ids = assigned_activity_ids_for_roles(
                request, {'ACTIVITY_FRONT_DESK_OFFICER', 'ACTIVITY_OPERATOR'})
            if not is_activity_platform_user(request.user) and (
                    authorized_ids is None or activity.id not in authorized_ids):
                raise PermissionDenied('Only activity front desk staff can check in guests.')
            if booking.status != Booking.Status.CONFIRMED:
                raise PermissionDenied('Only confirmed activity bookings may be checked in.')
            booking.status = Booking.Status.CHECKED_IN
            booking.save(update_fields=['status'])
            log_activity(request.user, "Activity booking attended", str(booking.pk))
        elif action == 'complete':
            authorized_ids = assigned_activity_ids_for_roles(request, {'ACTIVITY_OPERATOR'})
            if not is_activity_platform_user(request.user) and (
                    authorized_ids is None or activity.id not in authorized_ids):
                raise PermissionDenied('This role cannot complete activity bookings.')
            if booking.status != Booking.Status.CHECKED_IN:
                raise PermissionDenied('Only checked-in activity bookings may be completed.')
            bill = bill_for_booking(booking)
            booking.status = Booking.Status.COMPLETED
            booking.amount_paid = bill.amount_paid if bill else 0
            booking.balance_due = bill.balance_due if bill else 0
            booking.save(update_fields=['status', 'amount_paid', 'balance_due'])
            log_activity(request.user, "Activity booking completed", str(booking.pk))
        elif action == 'update_status':
            authorized_ids = assigned_activity_ids_for_roles(request, {'ACTIVITY_OPERATOR'})
            if not is_activity_platform_user(request.user) and (
                    authorized_ids is None or activity.id not in authorized_ids):
                raise PermissionDenied('This role cannot change activity operational settings.')
            new_status = request.POST.get('status')
            if new_status in {
                Activity.Status.ACTIVE,
                Activity.Status.UNDER_MAINTENANCE,
                Activity.Status.FULLY_BOOKED,
                Activity.Status.SUSPENDED,
            }:
                activity.status = new_status
                activity.save(update_fields=['status'])
                log_activity(request.user, "Updated activity status", activity.name)
        else:
            raise PermissionDenied('Unknown activity operation.')
        messages.success(request, "Operation completed.")
        return redirect('activities:operate')

    activities = scope_activities(
        request,
        Activity.objects.select_related('provider').prefetch_related('photos').all(),
    )
    bookings = scope_bookings(request, Booking.objects.select_related('customer').all())
    bookings_by_activity = {}
    for booking in bookings:
        bookings_by_activity.setdefault(booking.activity_id, []).append(booking)
    rows = [
        {'activity': activity, 'bookings': bookings_by_activity.get(activity.id, [])}
        for activity in activities
    ]
    return render(request, 'activities/operate.html', {
        'rows': rows,
        'status_choices': [
            ('ACTIVE', 'Active'),
            ('UNDER_MAINTENANCE', 'Under Maintenance'),
            ('FULLY_BOOKED', 'Fully Booked'),
            ('SUSPENDED', 'Suspended'),
        ],
    })


