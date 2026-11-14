from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

from .models import Notification
from . import services


@login_required
def notification_list(request):
    status = request.GET.get('status', 'all')
    category = request.GET.get('category', 'all')
    search = (request.GET.get('q') or '').strip()
    qs = Notification.objects.filter(recipient=request.user).select_related(
        'session', 'establishment', 'assignment', 'role', 'actor',
        'transaction', 'related_content_type',
    )
    if status == 'unread':
        qs = qs.filter(is_read=False)
    elif status == 'read':
        qs = qs.filter(is_read=True)
    else:
        status = 'all'

    category_prefixes = {
        'roles': ('ROLE_',),
        'sessions': ('SESSION_',),
        'workflow': ('STUDENT_WORK_',),
        'bookings': ('HOTEL_', 'RESTAURANT_', 'RESORT_', 'STAYCATION_', 'ACTIVITY_',
                     'LANDMARK_', 'FLIGHT_', 'TRAVEL_', 'TOUR_', 'TRANSPORT_'),
        'payments': ('PAYMENT_', 'BILLING_'),
    }
    if category == 'announcements':
        qs = qs.filter(notification_type=Notification.Type.ANNOUNCEMENT)
    elif category == 'updates':
        from django.db.models import Q
        qs = qs.filter(
            Q(notification_type=Notification.Type.UPDATE)
            | Q(notification_type__endswith='_UPDATED')
        )
    elif category in category_prefixes:
        from django.db.models import Q
        category_query = Q()
        for prefix in category_prefixes[category]:
            category_query |= Q(notification_type__startswith=prefix)
        qs = qs.filter(category_query)
    else:
        category = 'all'
    if search:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=search) | Q(message__icontains=search))

    page_obj = Paginator(qs.order_by('-created_at', '-pk'), 25).get_page(
        request.GET.get('page'))
    unread_count_total = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).count()

    context = {
        'notifications': page_obj.object_list,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'status_filter': status,
        'category_filter': category,
        'search_query': search,
        'unread_count_total': unread_count_total,
    }
    return render(request, 'notifications/list.html', context)


@login_required
@require_POST
def mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    try:
        services.mark_read(notification, user=request.user)
    except TypeError:
        try:
            services.mark_read(notification)
        except Exception:
            notification.mark_read() if hasattr(notification, 'mark_read') else setattr(notification, 'is_read', True)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'unread_count': services.unread_count(request.user)})
    return redirect(_notification_destination(notification, request.user))


def _notification_destination(notification, user):
    """Resolve only trusted, permission checked destinations from related rows."""
    try:
        related = notification.related_object
    except ObjectDoesNotExist:
        related = None
    if related is None and notification.transaction_id:
        related = notification.transaction.subject
    if related is not None:
        destination = _record_destination(related, user, notification=notification)
        if destination:
            return destination
    if notification.assignment_id:
        from simulation.models import SimulationRoleAssignment
        assignment = SimulationRoleAssignment.objects.filter(
            pk=notification.assignment_id).select_related(
                'session', 'session__instructor').first()
        if assignment and assignment.student_id == user.pk:
            return reverse('simulation:role_detail', args=[assignment.pk])
        if (assignment and assignment.session_id
                and assignment.session.instructor_id == user.pk):
            return f"{reverse('simulation:workspace')}#session-{assignment.session_id}"
    return reverse('notifications:list')


def _record_destination(record, user, *, notification=None):
    """Map known persisted records to their existing, permission-checked views."""
    from django.core.exceptions import ObjectDoesNotExist

    try:
        label = record._meta.label_lower
        if label == 'simulation.simulationroleassignment':
            if record.student_id == user.pk:
                return reverse('simulation:role_detail', args=[record.pk])
            return None
        if label == 'simulation.simulationsession':
            if record.instructor_id == user.pk or record.assignments.filter(student=user).exists():
                return f"{reverse('simulation:workspace')}#session-{record.pk}"
            return None
        if label == 'travel_agencies.travelagencyrequest' and notification is not None:
            return reverse('notifications:travel_request', args=[notification.pk])
        routes = {
            'hotels.booking': ('hotels:booking_detail', 'booking_id'),
            'resorts.reservation': ('resorts:booking_detail', 'booking_id'),
            'staycations.reservation': ('staycations:booking_detail', 'booking_id'),
            'restaurants.reservation': ('restaurants:booking_detail', 'booking_id'),
            'activities.booking': ('activities:booking_detail', 'booking_id'),
            'tour_package.booking': ('tour_package:booking_detail', 'booking_id'),
            'landmarks.ticket': ('landmarks:booking_detail', 'booking_id'),
            'airlines.booking': ('airlines:booking_detail', 'booking_id'),
            'transportation.booking': ('transportation:booking_detail', 'booking_id'),
            'transactions.bill': ('transactions:bill_detail', 'bill_id'),
        }
        if label == 'billing.simulatedbill':
            transaction = record.transaction
            return _record_destination(transaction.subject, user, notification=notification) if transaction and transaction.subject else None
        if label == 'billing.simulatedpayment':
            bill = record.bill
            transaction = bill.transaction if bill else None
            return _record_destination(transaction.subject, user, notification=notification) if transaction and transaction.subject else None
        if label == 'transactions.payment':
            if record.content_type_id and record.object_id:
                return _record_destination(record.booking, user)
        route = routes.get(label)
        if route:
            route_name, _parameter = route
            return reverse(route_name, args=[record.pk])
    except (ObjectDoesNotExist, NoReverseMatch, AttributeError):
        return None
    return None


@login_required
def travel_request_detail(request, pk):
    """Recipient-scoped detail destination for the travel agency workflow."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    try:
        record = notification.related_object
    except ObjectDoesNotExist:
        record = None
    if record is None and notification.transaction_id:
        try:
            record = notification.transaction.subject
        except ObjectDoesNotExist:
            record = None
    if not record or record._meta.label_lower != 'travel_agencies.travelagencyrequest':
        messages.info(request, 'The travel request is no longer available.')
        return redirect('notifications:list')

    from simulation.models import SimulationRoleAssignment

    is_customer = record.customer_id == request.user.pk
    is_consultant = record.quotations.filter(prepared_by=request.user).exists()
    is_assigned_consultant = SimulationRoleAssignment.objects.filter(
        student=request.user,
        session=notification.session,
        establishment=record.establishment,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role__in=(
            SimulationRoleAssignment.Role.TRAVEL_AGENCY_MANAGER,
            SimulationRoleAssignment.Role.TRAVEL_AGENCY_RESERVATION_AGENT,
            SimulationRoleAssignment.Role.TRAVEL_AGENCY_FRONT_DESK,
        ),
    ).exists()
    if not (is_customer or is_consultant or is_assigned_consultant):
        return redirect('notifications:list')

    return render(request, 'notifications/travel_request_detail.html', {
        'notification': notification,
        'travel_request': record,
        'quotation': record.current_quotation,
    })


@login_required
@require_POST
def open_notification(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    services.mark_read(notification, user=request.user)
    destination = _notification_destination(notification, request.user)
    try:
        related_record_exists = notification.related_object is not None
    except ObjectDoesNotExist:
        related_record_exists = False
    if notification.related_object_id and not related_record_exists:
        messages.info(request, 'The related record is no longer available. You are viewing your notification history.')
    return redirect(destination)


@login_required
@require_POST
def mark_all_read(request):
    try:
        services.mark_all_read(user=request.user)
    except TypeError:
        services.mark_all_read(request.user)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'unread_count': 0})
    return redirect('notifications:list')


@login_required
def unread_count_json(request):
    return JsonResponse({'unread_count': services.unread_count(request.user)})


@login_required
def recent_json(request):
    items = []
    for n in Notification.objects.filter(recipient=request.user).select_related(
        'session', 'establishment', 'assignment', 'role', 'actor'
    )[:5]:
        items.append({
            'id': n.pk,
            'title': n.title or n.get_notification_type_display(),
            'message': n.message,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat(),
            'url': reverse('notifications:open', args=[n.pk]),
        })
    return JsonResponse({'results': items, 'unread_count': services.unread_count(request.user)})
