from decimal import Decimal, InvalidOperation
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin

from atrue_core.decorators import manager_required
from atrue_core.services import (
    bill_for_booking,
    log_activity,
    record_payment,
    record_transaction,
    refund_payment,
)

from simulation.models import BILLING_OFFICER_ROLE_CODES

from .models import AdditionalTransaction, Bill, Payment, Receipt


@login_required
def payment_review(request):
    """Billing Officer queue for verifying payments before reservation confirmation."""
    from simulation.models import SimulationRoleAssignment

    assignment_id = request.session.get('active_simulation_task_assignment')
    assignment = (SimulationRoleAssignment.objects.filter(
        pk=assignment_id, student=request.user, role__in=BILLING_OFFICER_ROLE_CODES,
        status='ACTIVE'
    ).select_related('session').first() if assignment_id else None)
    eligible_assignments = SimulationRoleAssignment.objects.filter(
        student=request.user, role__in=BILLING_OFFICER_ROLE_CODES, status='ACTIVE',
        session__isnull=False, establishment__isnull=False,
    ).select_related('session', 'establishment')
    if assignment is None:
        establishment_ids = list(eligible_assignments.order_by().values_list(
            'establishment_id', flat=True).distinct()[:2])
        if len(establishment_ids) == 1:
            assignment = eligible_assignments.filter(
                establishment_id=establishment_ids[0]).first()
    is_admin = request.user.is_staff or request.user.is_superuser
    if not is_admin and (assignment is None or assignment.establishment_id is None):
        raise PermissionDenied(
            'Open payment review from the assigned establishment task. Each Billing Officer assignment covers one establishment.')

    bills = Bill.objects.filter(status=Bill.Status.FULLY_PAID, verified_at__isnull=True)
    rows = []
    for bill in bills.select_related('customer').prefetch_related('payments'):
        booking = bill.booking
        if booking is None:
            continue
        establishment = None
        try:
            from simulation.completion import establishment_for_booking
            establishment = establishment_for_booking(booking)
        except Exception:
            continue
        if (not is_admin and assignment is not None
                and (establishment is None
                     or establishment.pk != assignment.establishment_id)):
            continue
        if request.method == 'POST' and request.POST.get('bill_id') == str(bill.pk):
            if bill.status != Bill.Status.FULLY_PAID:
                messages.error(request, 'Only fully paid bills can be verified.')
                return redirect('transactions:payment_review')
            bill.verified_by = request.user
            bill.verified_at = timezone.now()
            bill.save(update_fields=['verified_by', 'verified_at'])
            from atrue_core.services import log_activity
            log_activity(
                request.user, 'Payment verified', bill.bill_reference,
                session=assignment.session if assignment else None,
                establishment=establishment,
            )
            if booking._meta.app_label == 'resorts' and booking.status == 'PENDING':
                from simulation.models import SimulationRoleAssignment
                from notifications.models import Notification
                from notifications.services import notify_many

                officers = SimulationRoleAssignment.objects.filter(
                    role=SimulationRoleAssignment.Role.RESORT_RESERVATION_OFFICER,
                    status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                    establishment=establishment,
                ).select_related('student')
                if assignment is not None:
                    officers = officers.filter(session=assignment.session)
                notify_many(
                    [row.student for row in officers],
                    Notification.Type.GENERAL,
                    f'Payment verified for resort reservation {booking.booking_reference}. '
                    'Review and confirm the reservation.',
                    session=assignment.session if assignment else None,
                    establishment=establishment,
                )
                messages.success(
                    request,
                    f'Payment for {bill.bill_reference} verified. The resort reservation is now awaiting '
                    'Resort Reservation Officer confirmation.',
                )
            else:
                messages.success(request, f'Payment for {bill.bill_reference} verified.')
            return redirect('transactions:payment_review')
        rows.append({'bill': bill, 'booking': booking, 'establishment': establishment})
    return render(request, 'transactions/payment_review.html', {
        'rows': rows,
        'active_assignment': assignment,
    })


def _money(value):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _row_date(value):
    """Extract a plain date from a row's sort/filter value.

    Pending payments store an int (their pk) instead of a datetime, so
    never let that crash the date filters.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _package_scope(request):
    from tour_package.scope import GUEST_ROLES, package_ids_for_roles
    return package_ids_for_roles(request, GUEST_ROLES)


def _package_booking_accessible(request, booking):
    if booking is None or booking._meta.app_label != 'tour_package':
        return True
    allowed = _package_scope(request)
    return allowed is None or booking.package_id in allowed


def _hide_unassigned_package_links(request, queryset, *, linked_prefix=''):
    allowed = _package_scope(request)
    if allowed is None:
        return queryset
    from tour_package.models import Booking as TourPackageBooking
    disallowed = TourPackageBooking.objects.exclude(package_id__in=allowed).values('pk')
    link = f'{linked_prefix}content_type__'
    return queryset.exclude(
        Q(**{f'{link}app_label': 'tour_package', f'{link}model': 'booking'})
        & Q(**{f'{linked_prefix}object_id__in': disallowed})
    )


def _user_bookings(user, request=None):
    """Collect (booking, service) pairs across all service apps (BR-018 picker)."""
    pairs = []
    try:
        from airlines.models import Booking as AirlineBooking
        for b in AirlineBooking.objects.filter(passenger=user):
            pairs.append((b, 'flight'))
    except Exception:
        pass
    try:
        from hotels.models import Booking as HotelBooking
        for b in HotelBooking.objects.filter(customer=user):
            pairs.append((b, 'hotel'))
    except Exception:
        pass
    try:
        from resorts.models import Reservation as ResortReservation
        for b in ResortReservation.objects.filter(customer=user):
            pairs.append((b, 'resort'))
    except Exception:
        pass
    try:
        from staycations.models import Reservation as StaycationReservation
        for b in StaycationReservation.objects.filter(customer=user):
            pairs.append((b, 'staycation'))
    except Exception:
        pass
    try:
        from restaurants.models import Reservation as RestoReservation
        for b in RestoReservation.objects.filter(customer=user):
            pairs.append((b, 'restaurant'))
    except Exception:
        pass
    try:
        from transportation.models import Booking as TransportBooking
        for b in TransportBooking.objects.filter(customer=user):
            pairs.append((b, 'transport'))
    except Exception:
        pass
    try:
        from landmarks.models import Ticket as LandmarkTicket
        for b in LandmarkTicket.objects.filter(customer=user):
            pairs.append((b, 'ticket'))
    except Exception:
        pass
    try:
        from activities.models import Booking as ActivityBooking
        for b in ActivityBooking.objects.filter(customer=user):
            pairs.append((b, 'activity'))
    except Exception:
        pass
    try:
        from tour_package.models import Booking as TourPackageBooking
        packages = TourPackageBooking.objects.filter(customer=user)
        if request is not None:
            allowed = _package_scope(request)
            if allowed is not None:
                packages = packages.filter(package_id__in=allowed)
        for b in packages:
            pairs.append((b, 'package'))
    except Exception:
        pass
    pairs.sort(key=lambda p: getattr(p[0], 'created_at', None) or p[0].pk, reverse=True)
    namespace_map = {
        'flight': 'airlines',
        'hotel': 'hotels',
        'resort': 'resorts',
        'staycation': 'staycations',
        'restaurant': 'restaurants',
        'transport': 'transportation',
        'ticket': 'landmarks',
        'activity': 'activities',
        'package': 'tour_package',
    }
    return [
        {
            'booking': booking,
            'service': service,
            'app_label': booking._meta.app_label,
            'model_name': booking._meta.model_name,
            'pk': booking.pk,
            'reference': booking.booking_reference,
            'label': str(booking),
            'detail_url': reverse(f"{namespace_map[service]}:booking_detail", args=[booking.pk]),
        }
        for booking, service in pairs
    ]


@login_required
def transaction_list(request):
    user = request.user
    bills = Bill.objects.filter(customer=user).prefetch_related('payments')
    payments = Payment.objects.select_related('bill').filter(customer=user).order_by('-paid_at')
    receipts = Receipt.objects.select_related('bill').filter(customer=user)
    from .models import TravelOrder
    orders = TravelOrder.objects.filter(customer=user).prefetch_related('items')
    bills = _hide_unassigned_package_links(request, bills)
    payments = _hide_unassigned_package_links(request, payments)
    receipts = _hide_unassigned_package_links(request, receipts, linked_prefix='bill__')
    allowed = _package_scope(request)
    if allowed is not None:
        from django.contrib.contenttypes.models import ContentType
        package_booking_type = ContentType.objects.get(app_label='tour_package', model='booking')
        from tour_package.models import Booking as TourPackageBooking
        disallowed = TourPackageBooking.objects.exclude(package_id__in=allowed).values('pk')
        orders = orders.exclude(
            items__content_type=package_booking_type,
            items__object_id__in=disallowed,
        ).distinct()
    return render(request, 'transactions/list.html', {
        'bills': bills,
        'payments': payments,
        'receipts': receipts,
        'orders': orders,
    })


def _linked_booking_ref(record):
    """Best-effort booking reference for a payment/additional transaction."""
    booking = getattr(record, 'booking', None)
    bill = getattr(record, 'bill', None)
    target = booking or (bill.booking if bill else None)
    if target is not None:
        return getattr(target, 'booking_reference', '') or str(target.pk)
    return ''


@manager_required
def admin_list(request):
    """FR-006 List of Transactions – search/filter/sort across payments,
    refunds and additional (adjustment) transactions."""
    payments = list(Payment.objects.select_related('bill', 'bill__customer', 'customer').all())
    adjustments = list(AdditionalTransaction.objects.select_related('customer').all())

    rows = []
    for p in payments:
        rows.append({
            'reference': p.payment_reference,
            'booking_ref': _linked_booking_ref(p),
            'customer': p.customer.get_full_name() or p.customer.username,
            'date': p.paid_at or p.pk,
            'type': 'Refund' if p.status == 'REFUNDED' else 'Booking Payment',
            'amount': p.amount,
            'status': {'PENDING': 'Pending', 'PAID': 'Completed', 'REFUNDED': 'Refunded'}.get(p.status, p.status),
            'bill_id': p.bill_id,
        })
    for a in adjustments:
        rows.append({
            'reference': a.transaction_reference,
            'booking_ref': _linked_booking_ref(a),
            'customer': a.customer.get_full_name() or a.customer.username,
            'date': a.created_at,
            'type': f"Adjustment - {a.get_transaction_type_display()}",
            'amount': a.total_amount,
            'status': a.get_status_display(),
            'bill_id': None,
        })

    q = (request.GET.get('q') or '').strip()
    ttype = request.GET.get('type', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    amount_min = _money(request.GET.get('amount_min') or 0)
    amount_max = _money(request.GET.get('amount_max') or 0)
    sort = request.GET.get('sort', 'date')

    if q:
        rows = [r for r in rows if q.lower() in r['reference'].lower()
                or q.lower() in r['booking_ref'].lower()
                or q.lower() in r['customer'].lower()]
    if ttype == 'payment':
        rows = [r for r in rows if r['type'] == 'Booking Payment']
    elif ttype == 'refund':
        rows = [r for r in rows if r['type'] == 'Refund']
    elif ttype == 'adjustment':
        rows = [r for r in rows if r['type'].startswith('Adjustment')]
    elif ttype:
        rows = [r for r in rows if r['type'].lower() == ttype.lower()]
    if status:
        rows = [r for r in rows if r['status'].lower() == status.lower()]
    if date_from:
        try:
            dmin = date.fromisoformat(date_from)
            rows = [r for r in rows if _row_date(r['date']) is not None and _row_date(r['date']) >= dmin]
        except ValueError:
            pass
    if date_to:
        try:
            dmax = date.fromisoformat(date_to)
            rows = [r for r in rows if _row_date(r['date']) is not None and _row_date(r['date']) <= dmax]
        except ValueError:
            pass
    if amount_min > 0:
        rows = [r for r in rows if r['amount'] >= amount_min]
    if amount_max > 0:
        rows = [r for r in rows if r['amount'] <= amount_max]
    if sort == 'amount':
        rows.sort(key=lambda r: r['amount'], reverse=True)
    elif sort == 'type':
        rows.sort(key=lambda r: r['type'])
    elif sort == 'status':
        rows.sort(key=lambda r: r['status'])
    else:
        rows.sort(key=lambda r: r['date'], reverse=True)

    return render(request, 'transactions/admin_list.html', {
        'rows': rows,
        'q': q,
        'ttype': ttype,
        'status': status,
        'date_from': date_from,
        'date_to': date_to,
        'amount_min': amount_min,
        'amount_max': amount_max,
        'sort': sort,
        'transaction_types': [
            ('payment', 'Booking Payment'), ('refund', 'Refund'),
            ('adjustment', 'Adjustment'), ('other', 'Other'),
        ],
        'status_choices': [('Pending', 'Pending'), ('Completed', 'Completed'),
                           ('Failed', 'Failed'), ('Cancelled', 'Cancelled'),
                           ('Refunded', 'Refunded')],
    })


@login_required
def bill_detail(request, bill_id):
    bill = get_object_or_404(Bill.objects.prefetch_related('payments', 'receipts'), pk=bill_id)
    if bill.customer_id != request.user.id:
        messages.warning(request, "You cannot view this bill.")
        return redirect('transactions:list')
    booking = bill.booking
    if not _package_booking_accessible(request, booking):
        raise PermissionDenied('This Tour Package booking is not assigned to your account.')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'pay':
            amount = _money(request.POST.get('amount') or 0)
            method = request.POST.get('payment_method', 'GCASH')
            if amount <= 0:
                messages.error(request, "Enter a valid amount to pay.")
            else:
                record_payment(
                    customer=request.user,
                    amount=amount,
                    method=method,
                    service=bill.service,
                    description=f"Payment for {bill.bill_reference}",
                    bill=bill,
                    booking=booking,
                )
                messages.success(request, "Payment recorded and receipt issued.")
        elif action == 'refund':
            payment = get_object_or_404(Payment, pk=request.POST.get('payment_id'), customer=request.user)
            if payment.status == 'REFUNDED':
                messages.warning(request, "This payment is already refunded.")
            else:
                refund_payment(payment=payment, user=request.user,
                               description=f"Refund of {payment.amount} from {bill.bill_reference}")
                messages.success(request, "Payment refunded.")
        elif action == 'additional':
            purchase_type = request.POST.get('transaction_type', AdditionalTransaction.TransactionType.ADDITIONAL_SERVICE)
            description = request.POST.get('description', '').strip()
            quantity = int(request.POST.get('quantity') or 1)
            rate = _money(request.POST.get('rate') or 0)
            total = quantity * rate
            if not description or total <= 0:
                messages.error(request, "Provide a description and a valid rate.")
            elif booking is None:
                messages.error(request, "This bill is not linked to a booking; additional transactions cannot be added.")
            else:
                additional = AdditionalTransaction.objects.create(
                    customer=request.user,
                    transaction_type=purchase_type,
                    description=description,
                    quantity=quantity,
                    rate=rate,
                    total_amount=total,
                    status=AdditionalTransaction.Status.UNPAID,
                )
                additional.link_to_booking(booking)
                additional.save(update_fields=['content_type', 'object_id'])
                log_activity(request.user, "Additional transaction recorded",
                             f"{additional.transaction_reference} - {description} ({total})")
                record_transaction('ADDITIONAL_TRANSACTION', additional.transaction_reference, request.user,
                                   f"Additional transaction {additional.transaction_reference} - {description}")
        return redirect('transactions:bill_detail', bill.id)

    additional_transactions = AdditionalTransaction.objects.filter(
        content_type=bill.content_type,
        object_id=bill.object_id,
        customer=request.user,
    ).order_by('-created_at') if bill.content_type_id else AdditionalTransaction.objects.none()

    return render(request, 'transactions/bill.html', {
        'bill': bill,
        'booking': booking,
        'payments': bill.payments.all(),
        'receipts': bill.receipts.all() if bill.pk else [],
        'additional_transactions': additional_transactions,
        'additional_types': AdditionalTransaction.TransactionType.choices,
    })


@login_required
def receipt_detail(request, receipt_id):
    receipt = get_object_or_404(Receipt.objects.select_related('bill', 'payment', 'customer'), pk=receipt_id)
    if receipt.customer_id != request.user.id and not request.user.is_staff:
        messages.warning(request, "You cannot view this receipt.")
        return redirect('transactions:list')
    booking = receipt.bill.booking if receipt.bill_id else None
    if not _package_booking_accessible(request, booking):
        raise PermissionDenied('This Tour Package payment is not assigned to your account.')
    return render(request, 'transactions/receipt.html', {'receipt': receipt})


@login_required
def additional_list(request):
    records = (AdditionalTransaction.objects
               .filter(customer=request.user)
               .order_by('-created_at'))
    records = _hide_unassigned_package_links(request, records)
    return render(request, 'transactions/additional.html', {
        'booking_pairs': _user_bookings(request.user, request),
        'additional_types': AdditionalTransaction.TransactionType.choices,
    })


@login_required
def additional_add(request):
    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        quantity = int(request.POST.get('quantity') or 1)
        rate = _money(request.POST.get('rate') or 0)
        purchase_type = request.POST.get('transaction_type', AdditionalTransaction.TransactionType.ADDITIONAL_SERVICE)
        booking_ref = request.POST.get('booking_ref', '')
        if not description or rate <= 0:
            messages.error(request, "Provide a description and a valid rate.")
            return redirect('transactions:additional_add')
        try:
            app_label, model_name, object_id = booking_ref.split(':')
        except ValueError:
            messages.error(request, "Choose the booking this additional charge belongs to.")
            return redirect('transactions:additional_add')
        booking = _resolve_booking(app_label, model_name, object_id)
        if booking is None or not _package_booking_accessible(request, booking):
            messages.error(request, "The selected booking could not be found.")
            return redirect('transactions:additional_add')
        total = quantity * rate
        additional = AdditionalTransaction.objects.create(
            customer=request.user,
            transaction_type=purchase_type,
            description=description,
            quantity=quantity,
            rate=rate,
            total_amount=total,
            status=AdditionalTransaction.Status.UNPAID,
        )
        additional.link_to_booking(booking)
        additional.save(update_fields=['content_type', 'object_id'])
        log_activity(request.user, "Additional transaction recorded",
                     f"{additional.transaction_reference} - {description} ({total})")
        bill = bill_for_booking(booking)
        record_transaction('ADDITIONAL_TRANSACTION', additional.transaction_reference, request.user,
                           f"Additional transaction {additional.transaction_reference} - {description}")
        messages.success(request, f"Additional transaction added: {additional.transaction_reference}")
        if bill:
            return redirect('transactions:bill_detail', bill.id)
        return redirect('transactions:additional_list')
    return render(request, 'transactions/additional.html', {
        'booking_pairs': _user_bookings(request.user, request),
        'additional_types': AdditionalTransaction.TransactionType.choices,
    })


def _resolve_booking(app_label, model_name, object_id):
    from django.apps import apps
    try:
        model = apps.get_model(app_label, model_name)
        return model.objects.get(pk=object_id)
    except Exception:
        return None


@login_required
def booking_list(request):
    """Unified 'My Bookings' across every service app (replaces removed bookings app)."""
    rows = []
    for item in _user_bookings(request.user, request):
        booking = item['booking']
        rows.append({
            'item': item,
            'service': item['service'],
            'reference': booking.booking_reference,
            'details': str(booking),
            'status': booking.status,
            'created': getattr(booking, 'created_at', None) or booking.pk,
            'bill': bill_for_booking(booking),
            'detail_url': item['detail_url'],
        })
    rows.sort(key=lambda r: r['created'] or 0, reverse=True)
    return render(request, 'transactions/bookings.html', {'rows': rows})
@xframe_options_sameorigin
@login_required
def trip_cart(request):
    return redirect('home')


@xframe_options_sameorigin
@login_required
def trip_cart_remove(request):
    return redirect('home')


@xframe_options_sameorigin
@login_required
def trip_cart_clear(request):
    return redirect('home')


@xframe_options_sameorigin
@login_required
def trip_cart_checkout(request):
    return redirect('home')

@xframe_options_sameorigin
@login_required
def order_detail(request, order_id):
    from .models import TravelOrder
    order = get_object_or_404(TravelOrder.objects.prefetch_related('items'), pk=order_id, customer=request.user)
    allowed = _package_scope(request)
    if allowed is not None:
        for item in order.items.all():
            if (item.content_type.app_label == 'tour_package'
                    and item.content_type.model == 'booking'
                    and not _package_booking_accessible(
                        request, item.content_type.get_object_for_this_type(pk=item.object_id))):
                raise PermissionDenied('This order contains an unassigned Tour Package booking.')
    return render(request, 'transactions/order_detail.html', {'order': order})

@xframe_options_sameorigin
@login_required
def establishment_booking(request):
    """Review and pay for multiple resources from ONE establishment only."""
    from django.contrib.contenttypes.models import ContentType
    from django.db import transaction as db_transaction
    from atrue_core.services import bill_for_booking, create_bill, record_payment, record_transaction, make_reference, log_activity
    from .models import TravelOrder, TravelOrderItem
    from .establishment_flow import resolve, clear

    resolved, meta = resolve(request)
    if not resolved:
        messages.warning(request, 'There are no pending items in this establishment booking.')
        return redirect('home')
    allowed = _package_scope(request)
    if allowed is not None and any(
            booking._meta.app_label == 'tour_package'
            and booking.package_id not in allowed
            for _, booking in resolved):
        raise PermissionDenied('This establishment order contains an unassigned Tour Package booking.')
    total = sum((getattr(b, 'total_bill', 0) for _, b in resolved), 0)
    # Django templates intentionally disallow attributes beginning with an
    # underscore (for example booking._meta). Prepare the display label here
    # instead of reaching into model internals from the template.
    display_rows = [
        (key, booking, getattr(booking._meta, 'verbose_name', booking.__class__.__name__))
        for key, booking in resolved
    ]
    if request.method != 'POST':
        return render(request, 'transactions/establishment_booking.html', {
            'rows': display_rows, 'meta': meta, 'total': total,
        })

    method = request.POST.get('payment_method', 'GCASH')
    pay_later = request.POST.get('pay_later') == 'on'
    with db_transaction.atomic():
        order = TravelOrder.objects.create(
            customer=request.user,
            status=TravelOrder.Status.PENDING,
            total_amount=total,
            balance_due=total,
            payment_method=method,
        )
        items = []
        for _, booking in resolved:
            service = booking._meta.app_label
            amount = getattr(booking, 'total_bill', 0)
            desc = str(booking)
            items.append({'label': service.replace('_', ' ').title(), 'description': desc,
                          'quantity': 1, 'rate': amount, 'amount': amount})
            ct = ContentType.objects.get_for_model(booking)
            TravelOrderItem.objects.create(order=order, content_type=ct, object_id=booking.pk,
                                           service=service, description=desc, amount=amount)
            from notifications.email_service import queue_booking_confirmation
            queue_booking_confirmation(booking)

        bill = create_bill(service='bundle', customer=request.user, items=items)
        order.bill = bill
        order.save(update_fields=['bill'])

        if not pay_later:
            record_payment(customer=request.user, amount=total, method=method,
                           service='bundle', description=f'ATrue establishment order {order.order_reference}', bill=bill)
            order.status = TravelOrder.Status.CONFIRMED
            order.amount_paid = total
            order.balance_due = 0
            order.save(update_fields=['status', 'amount_paid', 'balance_due'])
            # Bookings stay PENDING — each reservation officer confirms before
            # the customer holds a CONFIRMED booking.
            for _, booking in resolved:
                update_fields = []
                if hasattr(booking, 'amount_paid'):
                    booking.amount_paid = getattr(booking, 'total_bill', 0)
                    update_fields.append('amount_paid')
                if hasattr(booking, 'balance_due'):
                    booking.balance_due = 0
                    update_fields.append('balance_due')
                if update_fields:
                    booking.save(update_fields=update_fields)
                individual = bill_for_booking(booking)
                if individual:
                    individual.amount_paid = individual.total_amount
                    individual.balance_due = 0
                    individual.status = 'FULLY_PAID'
                    individual.save(update_fields=['amount_paid', 'balance_due', 'status'])

        else:
            for _, booking in resolved:
                booking.status = 'PENDING'
                booking.save(update_fields=['status'])

        log_activity(request.user, 'Created establishment booking order',
                     f'{order.order_reference}: {meta.get("establishment_name", "Establishment")} · {len(resolved)} item(s)')
        record_transaction('BOOKING', make_reference('ORD'), request.user,
                           f'One-establishment booking {order.order_reference}')
        clear(request)

    if pay_later:
        messages.success(request, f'Booking order {order.order_reference} created. Payment is pending.')
    else:
        messages.success(request, f'Booking order {order.order_reference} paid · items pending reservation officer confirmation.')
    return redirect('transactions:order_detail', order.id)


@login_required
def establishment_booking_clear(request):
    from .establishment_flow import clear
    if request.method == 'POST':
        clear(request)
    return redirect('home')


