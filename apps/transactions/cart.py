from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404

from .models import TravelOrderItem

SESSION_KEY = 'atrue_trip_cart'


def _key_for(booking):
    ct = ContentType.objects.get_for_model(booking)
    return f'{ct.app_label}:{ct.model}:{booking.pk}'


def cart_keys(request):
    return list(request.session.get(SESSION_KEY, []))


def add_booking_to_cart(request, booking):
    key = _key_for(booking)
    keys = cart_keys(request)
    if key not in keys:
        keys.append(key)
    request.session[SESSION_KEY] = keys
    request.session.modified = True


def remove_key(request, key):
    keys = [k for k in cart_keys(request) if k != key]
    request.session[SESSION_KEY] = keys
    request.session.modified = True


def clear_cart(request):
    request.session.pop(SESSION_KEY, None)
    request.session.modified = True


def resolve_cart(request):
    from django.apps import apps
    resolved = []
    valid = []
    for key in cart_keys(request):
        try:
            app_label, model_name, object_id = key.split(':', 2)
            model = apps.get_model(app_label, model_name)
            booking = model.objects.get(pk=int(object_id))
            if getattr(booking, 'customer_id', getattr(booking, 'passenger_id', None)) != request.user.id:
                continue
            if str(getattr(booking, 'status', '')).upper() in {'CANCELLED', 'DECLINED', 'COMPLETED', 'USED'}:
                continue
            valid.append(key)
            resolved.append((key, booking))
        except Exception:
            continue
    if valid != cart_keys(request):
        request.session[SESSION_KEY] = valid
        request.session.modified = True
    return resolved



def create_single_booking_order(*, request, booking, service, amount, description,
                                 items=None, payment_method='GCASH', pay_later=False):
    """Create one customer TravelOrder for one booking.

    This is the direct-checkout path used by flights and land transportation.
    A multi-passenger flight (or a vehicle carrying multiple passengers) is
    still ONE booking, ONE TravelOrder, ONE combined bill and, when paid now,
    ONE payment. Passenger count stays inside the booking rather than creating
    separate financial transactions per passenger.
    """
    from decimal import Decimal
    from django.contrib.contenttypes.models import ContentType
    from django.db import transaction as db_transaction
    from atrue_core.services import bill_for_booking, create_bill, log_activity, record_payment, record_transaction, make_reference
    from .models import TravelOrder, TravelOrderItem

    amount = Decimal(str(amount or 0))
    bill_items = items or [{
        'label': f'{service.capitalize()} charge',
        'quantity': 1,
        'rate': amount,
        'amount': amount,
    }]

    with db_transaction.atomic():
        order = TravelOrder.objects.create(
            customer=request.user,
            status=TravelOrder.Status.PENDING,
            total_amount=amount,
            balance_due=amount,
            payment_method=payment_method,
        )
        ct = ContentType.objects.get_for_model(booking)
        TravelOrderItem.objects.create(
            order=order,
            content_type=ct,
            object_id=booking.pk,
            service=service,
            description=description,
            amount=amount,
        )
        from notifications.email_service import queue_booking_confirmation
        queue_booking_confirmation(booking)
        combined_bill = create_bill(service='bundle', customer=request.user, items=bill_items)
        order.bill = combined_bill
        order.save(update_fields=['bill'])

        if pay_later:
            log_activity(request.user, f'Placed {service} booking', description)
            record_transaction('BOOKING', make_reference('BOOK'), request.user,
                               f'{service.capitalize()} booking order {order.order_reference}')
            return order

        record_payment(
            customer=request.user,
            amount=amount,
            method=payment_method,
            service='bundle',
            description=f'ATrue order {order.order_reference}: {description}',
            bill=combined_bill,
        )
        order.status = TravelOrder.Status.CONFIRMED
        order.amount_paid = amount
        order.balance_due = 0
        order.save(update_fields=['status', 'amount_paid', 'balance_due'])

        # Booking stays PENDING — the module's own officer confirms it later,
        # while the actual customer payment remains the ONE combined order bill.
        update_fields = []
        if hasattr(booking, 'amount_paid'):
            booking.amount_paid = amount
            update_fields.append('amount_paid')
        if hasattr(booking, 'balance_due'):
            booking.balance_due = 0
            update_fields.append('balance_due')
        if update_fields:
            booking.save(update_fields=update_fields)

        # Keep the module-specific bill synchronized for existing BR/FR screens,
        # while the actual customer payment remains the ONE combined order bill.
        individual = bill_for_booking(booking)
        if individual:
            individual.amount_paid = individual.total_amount
            individual.balance_due = 0
            individual.status = 'FULLY_PAID'
            individual.save(update_fields=['amount_paid', 'balance_due', 'status'])

        log_activity(request.user, f'Paid for {service} booking order',
                     f'{order.order_reference}: {description} · pending officer confirmation')
        record_transaction('BOOKING', make_reference('ORD'), request.user,
                           f'One-order {service} booking {order.order_reference}')
        return order
