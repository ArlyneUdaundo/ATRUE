"""Shared service layer connecting the ATRUE platform.

Centralizes the cross-app workflows described in ATRUE_BRS.md / ATRUE_FR.md:
  - availability checks and conflict prevention
  - billing computation (hotel, resort, airline, transport, attraction, activity, package)
  - payment recording with balances and receipts
  - booking confirmation / response / cancellation
  - activity logging and transaction records
  - role helpers guarded by simulation role / account type
"""

import uuid

from datetime import timedelta

from django.utils import timezone

from accounts.models import User
from simulation.models import ActivityLog
from records.models import TransactionRecord


def make_reference(prefix="ATR"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def log_activity(user, action, details="", session=None, establishment=None, role=None):
    """Persist an action to the simulation activity log (BR-085)."""
    if user and user.is_authenticated:
        sim_role = role
        if not sim_role and user.simulation_roles.exists():
            try:
                sim_role = user.simulation_roles.order_by('-assigned_at').first().role
            except Exception:
                sim_role = ''
        ActivityLog.objects.create(
            user=user,
            action=action,
            details=details or "",
            simulation_role=sim_role or '',
            session=session,
            establishment=establishment,
        )


def record_transaction(record_type, reference_number, user, remarks=""):
    """Persist an immutable transaction record (records app)."""
    TransactionRecord.objects.create(
        record_type=record_type,
        reference_number=reference_number,
        user=user if user.is_authenticated else None,
        remarks=remarks,
    )


def bill_for_booking(booking):
    """Return the official bill linked to a specific booking (BR-090).

    Uses the booking's content-type/object-id link so a customer with many
    bookings of the same service never pays against the wrong bill.
    """
    if booking is None:
        return None
    from django.contrib.contenttypes.models import ContentType

    from transactions.models import Bill
    ct = ContentType.objects.get_for_model(booking)
    return Bill.objects.filter(content_type=ct, object_id=booking.pk).order_by('-created_at').first()


def record_payment(*, customer, amount, method, service="", description="",
                   bill=None, require_paid=True, booking=None):
    """Create a Payment for a booking and update the linked bill (BR-089).

    When the payment is completed a receipt is issued automatically (BR-092).
    Returns the payment instance.
    """
    from transactions.models import Bill, Payment, Receipt
    from atrue_core.payment_methods import validate_payment_method

    method = validate_payment_method(method)

    if booking is not None and bill is None:
        bill = bill_for_booking(booking)
    if bill is None:
        bill = Bill.objects.filter(customer=customer, service=service).order_by('-created_at').first()
    if bill:
        bill.add_payment(amount)

    payment = Payment.objects.create(
        bill=bill,
        customer=customer,
        amount=amount,
        method=method,
        status=Payment.Status.PAID if require_paid else Payment.Status.PENDING,
        paid_at=timezone.now() if require_paid else None,
    )
    if bill is not None and bill.booking is not None:
        payment.link_to_booking(bill.booking)
        payment.save(update_fields=['content_type', 'object_id'])

    log_activity(customer, f"Payment recorded for {service or 'booking'}",
                 f"Payment {payment.payment_reference} - {amount} via {method}")
    record_transaction(TransactionRecord.RecordType.PAYMENT, make_reference("PAY"), customer,
                       f"{description or f'Payment of {amount} via {method}'}")

    if payment.status == Payment.Status.PAID:
        Receipt.objects.create(
            payment=payment,
            bill=bill,
            customer=customer,
            amount=amount,
            remark=description or f"Payment via {method}",
        )

    if bill and bill.status == Bill.Status.FULLY_PAID:
        log_activity(customer, "Booking fully paid", str(bill.pk))
    return payment


def refund_payment(*, payment, user, description=""):
    """Reverse a completed payment (FR Module 36 - refund).

    Marks the payment REFUNDED, reduces the linked bill's paid amount and
    re-balances it, then logs both activity and a transaction record.
    """
    from decimal import Decimal

    from transactions.models import Bill, Payment

    if payment.status == 'REFUNDED':
        return payment
    payment.status = 'REFUNDED'
    payment.save(update_fields=['status'])
    bill = payment.bill
    if bill:
        bill.amount_paid = Decimal(bill.amount_paid) - Decimal(payment.amount)
        bill.amount_paid = max(Decimal(0), bill.amount_paid)
        bill.save(update_fields=['amount_paid'])
        bill._refresh()
    log_activity(user, f"Refunded payment",
                 f"Payment {payment.payment_reference} refunded - {payment.amount}")
    record_transaction(TransactionRecord.RecordType.REFUND, make_reference("REF"), user,
                       description or f"Refund of {payment.amount}")
    return payment


def create_bill(*, service, customer, items, booking=None):
    """Create the official bill for a booking (BR-017, BR-087).

    `items` is a list of dicts: {label, quantity, rate, amount}.
    """
    from transactions.models import Bill
    bill = Bill(service=service, customer=customer)
    if booking is not None:
        bill.link_to_booking(booking)
    bill.calculate(items)
    if booking is not None:
        # Queue alongside the persisted booking and dispatch after commit.
        from notifications.email_service import queue_booking_confirmation
        queue_booking_confirmation(booking)
    return bill


def checkout(*, user, service, booking, amount, payment_method, description="",
             items=None, bill=None, auto_confirm=False, session=None, establishment=None):
    """Run the full checkout pipeline for a booking.

    By default, does NOT auto-confirm (leaves booking as PENDING).
    Pass auto_confirm=True only for flows that must remain backward compatible.
    """
    from django.db import transaction

    with transaction.atomic():
        try:
            booking.refresh_from_db()
        except Exception:
            pass
        if getattr(booking, 'status', None) not in ('PENDING',):
            # Don't re-confirm if not pending
            pass

        log_activity(user, f"Placed {service} booking", description or str(booking.pk), session=session, establishment=establishment)

        bill_items = items or [{
            'label': f"{service.capitalize()} charge",
            'quantity': 1,
            'rate': amount,
            'amount': amount,
        }]
        if bill is None:
            bill = create_bill(
                service=service,
                customer=user,
                items=bill_items,
                booking=booking,
            )

        payment = record_payment(
            customer=user,
            amount=amount,
            method=payment_method,
            service=service,
            bill=bill,
            description=description or str(bill.pk),
        )

        record_transaction(TransactionRecord.RecordType.BOOKING, make_reference("BOOK"), user,
                           f"{service.capitalize()} booking {booking.pk}")

        if auto_confirm:
            booking.status = 'CONFIRMED'
            booking.confirmed_at = timezone.now()
            booking.confirmed_by = user
            booking.save(update_fields=['status', 'confirmed_at', 'confirmed_by'])

        if bill.status == 'FULLY_PAID':
            log_activity(user, "Booking fully paid", str(bill.pk), session=session, establishment=establishment)
        return payment


# -- Availability helpers (BR-013, BR-014) -------------------------------------

def overlapping_booking_exists(model, *, resource_field, resource, start, end,
                               statuses=('PENDING', 'ON_HOLD', 'RESERVED', 'CONFIRMED', 'CHECKED_IN', 'MODIFIED')):
    """Check that a capacity-controlled resource is not double-booked (BR-014)."""
    qs = model.objects.filter(**{resource_field: resource})
    qs = qs.exclude(status__in=('CANCELLED', 'COMPLETED', 'CHECKED_OUT', 'DECLINED', 'RETURNED'))
    qs = qs.filter(check_in__lt=end, check_out__gt=start)
    return qs.exists()


def resource_is_bookable(instance):
    """Generic check used across establishment resources (BR-010, BR-025)."""
    if instance is None:
        return False
    status = getattr(instance, 'status', None)
    if status is None:
        return True
    unavailable = {'MAINTENANCE', 'UNDER_MAINTENANCE', 'UNAVAILABLE', 'INACTIVE',
                   'SUSPENDED', 'OCCUPIED', 'RESERVED', 'IN_USE', 'NOT_AVAILABLE',
                   'FULLY_BOOKED', 'CANCELLED', 'EXPIRED', 'ASSIGNED'}
    return str(status).upper() not in unavailable


def active_record_queryset(model, field='status'):
    """Return public-facing queryset: only ACTIVE establishments (BR-010)."""
    return model.objects.filter(**{f'{field}': 'ACTIVE'})


# -- Room turnover and stay-date validation ------------------------------------
# The turnover interval is the readiness gap required between two stays of the
# same capacity resource. Stays are stored at date granularity, so a sub-day
# interval (the default 60 minutes) is absorbed on the checkout day itself and
# never pushes a booking to another date; only whole-day intervals (>= 1440
# minutes, e.g. a cleaning day) move the next available date.

_MINUTES_PER_DAY = 24 * 60


def turnover_minutes():
    """Configured room-turnover interval between stays (default: 60 min)."""
    from django.conf import settings

    try:
        return max(0, int(getattr(settings, 'ROOM_TURNOVER_MINUTES', 60)))
    except (TypeError, ValueError):
        return 60


def turnover_whole_days(minutes=None):
    """Whole checkout-days consumed by a turnover interval."""
    m = turnover_minutes() if minutes is None else minutes
    if not m or m <= 0:
        return 0
    return m // _MINUTES_PER_DAY


def next_available_check_in(prior_check_out, minutes=None):
    """Earliest date a capacity resource can accept its next stay."""
    if not prior_check_out:
        return prior_check_out
    return prior_check_out + timedelta(days=turnover_whole_days(minutes))


def turnover_conflicts(check_in, prior_check_out, minutes=None):
    """True when ``check_in`` falls inside a prior stay's turnover window."""
    if not check_in or not prior_check_out:
        return False
    return check_in < next_available_check_in(prior_check_out, minutes)


def validate_stay_dates(check_in, check_out):
    """Backend validation chain: date validity and check-in/out order."""
    errors = []
    if not check_in:
        errors.append('Check-in date is required.')
    if not check_out:
        errors.append('Check-out date is required.')
    if check_in and check_out and check_out <= check_in:
        errors.append('Check-out has to be after check-in.')
    return errors


# -- Booking lifecycle helpers (BR-015, BR-016, BR-021, BR-022) ---------------

def billing_officer_session_for_booking(booking, user, session=None):
    """Return the booking's session when it has an active assigned biller."""
    from simulation.models import BILLING_OFFICER_ROLE_CODES, SimulationRoleAssignment

    from simulation.completion import establishment_for_booking
    booking_establishment = establishment_for_booking(booking)
    review_session = session
    if review_session is None:
        if booking_establishment is not None:
            reservation_assignment = SimulationRoleAssignment.objects.filter(
                student=user,
                status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                establishment=booking_establishment,
            ).select_related('session').first()
            review_session = reservation_assignment.session if reservation_assignment else None
    if review_session and booking_establishment and SimulationRoleAssignment.objects.filter(
            session=review_session,
            establishment=booking_establishment,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
            role__in=BILLING_OFFICER_ROLE_CODES).exists():
        return review_session
    return None

def confirm_booking(booking, user, notify=True, session=None, establishment=None):
    """Set a booking to CONFIRMED with payment gate and audit."""
    from decimal import Decimal
    from django.db import transaction

    with transaction.atomic():
        try:
            booking.refresh_from_db()
        except Exception:
            pass
        current = getattr(booking, 'status', None)
        allowed_from = ('ON_HOLD', 'RESERVED', 'PENDING')
        if current not in allowed_from:
            return booking

        bill = bill_for_booking(booking)
        review_session = billing_officer_session_for_booking(
            booking, user, session=session)
        if review_session is not None and (
                bill is None or bill.status != 'FULLY_PAID' or not bill.verified_at):
            booking.payment_review_pending = True
            booking.payment_review_waiting_payment = bool(
                bill is None or bill.status != 'FULLY_PAID')
            return booking
        if bill is not None:
            total = Decimal(bill.total_amount or 0)
            paid = Decimal(bill.amount_paid or 0)
            if paid < total:
                booking.status = 'RETURNED'
                booking.declined_reason = 'Payment incomplete. Amount paid less than total.'
                booking.declined_at = timezone.now()
                booking.save(update_fields=['status', 'declined_reason', 'declined_at'])
                record_transaction(TransactionRecord.RecordType.BOOKING, make_reference("BOOK"), user,
                                   f"Booking returned (payment incomplete) - {getattr(booking, 'pk', '')}")
                return booking

        booking.status = 'CONFIRMED'
        booking.confirmed_by = user
        booking.confirmed_at = timezone.now()
        booking.save(update_fields=['status', 'confirmed_by', 'confirmed_at'])

    if notify:
        customer = (getattr(booking, 'customer', None)
                    or getattr(booking, 'passenger', None)
                    or getattr(booking, 'user', None))
        log_activity(user, "Booking confirmed", str(booking.pk), session=session, establishment=establishment)
        if customer and customer != user:
            log_activity(customer, "Your booking has been confirmed.",
                         str(getattr(booking, 'booking_reference', booking.pk)), session=session, establishment=establishment)
    record_transaction(TransactionRecord.RecordType.BOOKING, make_reference("BOOK"), user,
                       f"Booking confirmed - {getattr(booking, 'pk', '')}")
    # Confirming is the reservation officer's/manager's required action: their
    # own assignment is completed now that the booking is really saved as
    # CONFIRMED. Resolution is establishment-scoped, so a student who does not
    # actually hold this establishment's role is never credited.
    from simulation.completion import (complete_reservation_confirmation,
                                       establishment_for_booking)
    resolved_establishment = establishment or establishment_for_booking(booking)
    if resolved_establishment is not None:
        complete_reservation_confirmation(
            user, establishment=resolved_establishment, session=session,
            booking_reference=getattr(booking, 'booking_reference', '') or '')
    # Send the system-generated ticket only after status and payment checks pass.
    from notifications.email_service import queue_booking_confirmation
    queue_booking_confirmation(booking)
    return booking


def reserve_booking(booking, reserver, *, hold_minutes=None, notify=True, session=None, establishment=None):
    from django.db import transaction

    with transaction.atomic():
        try:
            booking.refresh_from_db()
        except Exception:
            pass
        current = getattr(booking, 'status', None)
        if current != 'PENDING':
            return booking
        booking.status = 'RESERVED'
        booking.reserved_by = reserver
        booking.reserved_at = timezone.now()
        if not getattr(booking, 'assigned_to', None):
            booking.assigned_to = reserver
        if hold_minutes:
            from datetime import timedelta
            booking.hold_expires_at = timezone.now() + timedelta(minutes=hold_minutes)
        booking.save(update_fields=['status', 'reserved_by', 'reserved_at', 'assigned_to', 'hold_expires_at'])
    if notify:
        customer = (getattr(booking, 'customer', None)
                    or getattr(booking, 'passenger', None)
                    or getattr(booking, 'user', None))
        log_activity(reserver, "Booking reserved", str(booking.pk), session=session, establishment=establishment)
        if customer and customer != reserver:
            log_activity(customer, "Your booking has been reserved.",
                         str(getattr(booking, 'booking_reference', booking.pk)), session=session, establishment=establishment)
    record_transaction(TransactionRecord.RecordType.BOOKING, make_reference("BOOK"), reserver,
                       f"Booking reserved - {getattr(booking, 'pk', '')}")
    return booking


def decline_booking(booking, user, reason='', notify=True, session=None, establishment=None):
    booking.status = 'DECLINED'
    booking.declined_reason = reason
    booking.declined_at = timezone.now()
    booking.save(update_fields=['status', 'declined_reason', 'declined_at'])
    if notify:
        customer = (getattr(booking, 'customer', None)
                    or getattr(booking, 'passenger', None)
                    or getattr(booking, 'user', None))
        log_activity(user, "Booking declined", str(booking.pk), session=session, establishment=establishment)
        if customer and customer != user:
            log_activity(customer, "Your booking has been declined.",
                         str(getattr(booking, 'booking_reference', booking.pk)), session=session, establishment=establishment)
    record_transaction(TransactionRecord.RecordType.BOOKING, make_reference("BOOK"), user,
                       f"Booking declined - {getattr(booking, 'pk', '')}")
    return booking
    log_activity(user, "Booking declined", str(booking.pk))


def cancel_booking(booking, user, release_callback=None):
    """Mark booking CANCELLED and release the reserved resource (BR-021)."""
    from transactions.models import Bill, Cancellation
    customer = getattr(booking, 'customer', None) or getattr(booking, 'passenger', None) or user
    cancellation = Cancellation(requested_by=user, status=Cancellation.Status.APPROVED)
    cancellation.link_to_booking(booking)
    cancellation.save()
    booking.status = 'CANCELLED'
    booking.save(update_fields=['status'])
    if release_callback:
        release_callback()
    log_activity(user, "Booking cancelled", f"{str(booking.booking_reference)} ({str(cancellation.pk)})")
    record_transaction(TransactionRecord.RecordType.CANCELLATION, make_reference("CANCEL"), user,
                       f"Cancellation for {booking.booking_reference}")


# -- Billing formulas from the BRS ---------------------------------------------

def _load(items):
    from decimal import Decimal, InvalidOperation
    return Decimal(items) if items is not None else Decimal(0)


def compute_hotel_bill(room, nights, adults=0, children=0, additional_guest_charge=0,
                       services=None, amenities=None, downpayment=0, extra_charges=None):
    """BR-032: Room Bill = (Room Rate + Additional Guest Charge) x Nights;
    Total = Room Bill + Services + Amenities."""
    from decimal import Decimal
    rate = Decimal(room.rate)
    room_bill = (rate + Decimal(additional_guest_charge or 0)) * Decimal(nights)
    items = [{'label': room.get_room_type_display() if hasattr(room, 'get_room_type_display') else room.room_type,
              'description': f"Room {room.room_number} x {nights} night(s)",
              'quantity': nights, 'rate': rate + Decimal(additional_guest_charge or 0),
              'amount': room_bill}]
    for s in (services or []):
        items.append({'label': getattr(s, 'name', str(s)), 'description': 'Hotel service',
                      'quantity': 1, 'rate': getattr(s, 'fee', getattr(s, 'rate', 0)),
                      'amount': getattr(s, 'fee', getattr(s, 'rate', 0))})
    for a in (amenities or []):
        items.append({'label': getattr(a, 'name', str(a)), 'description': 'Hotel amenity',
                      'quantity': 1, 'rate': 0, 'amount': 0})
    if extra_charges:
        for item in extra_charges:
            items.append(item)
    return items


def compute_resort_bill(unit, nights, services=None, extra_charges=None):
    """BR-039: Accommodation Charges + Services/Activities + Amenities + authorised extras."""
    items = [{'label': unit.unit_type, 'description': f"{unit} x {nights} night(s)",
              'quantity': nights, 'rate': unit.rate, 'amount': unit.rate * nights}]
    for s in (services or []):
        items.append({'label': getattr(s, 'name', str(s)), 'description': 'Resort service',
                      'quantity': 1, 'rate': getattr(s, 'fee', getattr(s, 'rate', 0)),
                      'amount': getattr(s, 'fee', getattr(s, 'rate', 0))})
    for item in (extra_charges or []):
        items.append(item)
    return items
def compute_airline_bill(flight, passengers, fare, services=None, baggage_charge=0, 
                         baggage_kg=0, return_flight=None, return_fare=None,
                         itinerary_legs=None):
    """BR-046: Base Fare + Taxes/Fees + Additional Services + Extra Baggage.

    A round trip is two flown legs, so it bills as two: each leg is its own
    ``Flight`` row with its own fare, and charging the passenger once for a
    journey they take twice would understate the ticket.

    A connecting itinerary bills the same way, one line per leg.  Each leg is a
    real flight with its own fare — a MNL-SIN hop on a widebody and a SIN-DXB
    hop on a narrowbody are not the same ticket price — so the passenger sees
    the journey priced out in the legs they actually fly, plus the itinerary's
    own base fare.  ``itinerary_legs`` is a list of ``(leg, fare)`` pairs; the
    existing ``flight`` argument stays the first leg, which keeps every direct
    and round-trip caller working unchanged.
    """
    items = [{'label': flight.flight_number, 'description': f"{flight.origin} to {flight.destination}",
              'quantity': passengers, 'rate': fare, 'amount': fare * passengers}]
    if itinerary_legs:
        # Leg 1 is already billed above as ``flight``/``fare``, so only the rest
        # of the chain is added here.
        itinerary_flight = getattr(flight, 'itinerary', None)
        for leg, leg_fare in itinerary_legs:
            if leg.pk == flight.pk:
                continue
            items.append({'label': leg.flight_number,
                          'description': f"{leg.origin} to {leg.destination}",
                          'quantity': passengers, 'rate': leg_fare,
                          'amount': leg_fare * passengers})
        if itinerary_flight is not None:
            stop_count = itinerary_flight.stops
            if stop_count:
                items.append({
                    'label': 'Connecting itinerary fee',
                    'description': (f"{stop_count} connection"
                                    f"{'s' if stop_count != 1 else ''} on "
                                    f"{itinerary_flight.route_label}"),
                    'quantity': passengers,
                    'rate': itinerary_flight.service_fee or 0,
                    'amount': (itinerary_flight.service_fee or 0) * passengers,
                })
    if return_flight is not None:
        back = return_fare if return_fare is not None else fare
        items.append({'label': return_flight.flight_number,
                      'description': f"{return_flight.origin} to {return_flight.destination}",
                      'quantity': passengers, 'rate': back, 'amount': back * passengers})
    if baggage_charge:

        items.append({'label': 'Extra baggage (%.2f kg)' % baggage_kg if baggage_kg else 'Extra baggage',
                      'quantity': 1, 'rate': baggage_charge,
                      'amount': baggage_charge})
    for s in (services or []):
        items.append({'label': getattr(s, 'name', str(s)), 'quantity': 1,
                      'rate': getattr(s, 'fee', getattr(s, 'rate', 0)),
                      'amount': getattr(s, 'fee', getattr(s, 'rate', 0))})
    return items


def compute_transport_bill(rate, distance_km, extra_charges=None):
    """BR-054: Applicable Rate x Distance (km) + authorised charges."""
    items = [{'label': 'Transportation', 'description': f"{distance_km} km",
              'quantity': 1, 'rate': rate, 'amount': rate * distance_km}]
    for item in (extra_charges or []):
        items.append(item)
    return items


def compute_attraction_bill(entry_fee, visitors, guided_tour_rate=0, tour_participants=0,
                            equipment_charges=None):
    """BR-063: Entrance + Guided Tour + Accessibility/Equipment charges."""
    items = [{'label': 'Entrance ticket', 'quantity': visitors, 'rate': entry_fee,
              'amount': entry_fee * visitors}]
    if guided_tour_rate and tour_participants:
        items.append({'label': 'Guided tour', 'quantity': tour_participants,
                      'rate': guided_tour_rate, 'amount': guided_tour_rate * tour_participants})
    for e in (equipment_charges or []):
        items.append(e)
    return items


def compute_activity_bill(activity, participants, extra_charges=None):
    items = [{'label': activity.name, 'quantity': participants,
              'rate': activity.fee, 'amount': activity.fee * participants}]
    for item in (extra_charges or []):
        items.append(item)
    return items


def compute_package_bill(package, total_heads, included_headcount, extra_person_rate):
    """BR-080, BR-081: Package Bill = Confirmed Package Price + (Additional Heads x Rate)."""
    extra_heads = max(0, int(total_heads) - int(included_headcount))
    adjustment = _load(extra_heads) * _load(extra_person_rate)
    items = [{'label': package.name, 'description': 'Confirmed package price',
              'quantity': 1, 'rate': package.price, 'amount': package.price}]
    if extra_heads:
        items.append({'label': f'Extra person ({extra_heads} head(s))',
                      'quantity': extra_heads, 'rate': extra_person_rate, 'amount': adjustment})
    return items, extra_heads, adjustment


# -- Role helpers --------------------------------------------------------------

def is_role(user, role_value):
    if not user or not user.is_authenticated:
        return False
    return user.simulation_roles.filter(role=role_value).exists()


def is_manager(user):
    if not user or not user.is_authenticated:
        return False
    from accounts.roles import MANAGEMENT_ACCOUNT_TYPES
    return user.account_type in MANAGEMENT_ACCOUNT_TYPES


def active_student_roles(user):
    """Return the list of currently-assigned roles for a user."""
    if not user or not user.is_authenticated:
        return []
    return list(user.simulation_roles.all())
