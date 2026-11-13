"""Airline workflow (Section 9).

    passenger books a flight -> reservation agent verifies the flight and seat
    -> ticket is issued -> passenger flies -> simulated billing

The airline differs from the other establishments in that ticketing is its own
step: a reservation can be approved while no ticket exists yet, and "ticketed" is
a real, visible change the passenger is told about separately.

Seat availability is worked out from the classroom's own booking rows, because
that is the only seat record the project has - there is no live inventory system
behind this, and a ticket issued here is a simulated coursework artefact rather
than a valid travel document.
"""

from django.db import transaction as db_transaction

from establishments.models import Establishment
from notifications.models import Notification
from notifications.services import notify
from simulation import engine, workflows
from simulation.models import SimulationTransaction

from .models import Booking, Flight

#: Statuses that stop occupying a seat.
RELEASED_STATUSES = [Booking.Status.CANCELLED, Booking.Status.DECLINED]


class AirlineWorkflowError(workflows.WorkflowError):
    pass


def book_flight(*, passenger, establishment, flight, total_amount, trip_type='',
                return_date=None, seats=(), fare_class='ECONOMY', segment='',
                travel_document_type='', travel_document_number='', manager_remarks='',
                services=None, extra_baggage=0, extra_baggage_kg=0, session=None):
    """A passenger books a flight, optionally naming seats.

    ``seats`` are seat numbers as strings ("12A"); they are checked against the
    booking rows that already exist for this flight.
    """
    establishment = _as_airline(establishment)
    seats = [str(number).strip().upper() for number in seats if str(number).strip()]
    for seat_number in seats:
        _ensure_seat_available(flight, seat_number, excluding_booking=None)

    booking = Booking.objects.create(
        passenger=passenger, flight=flight, trip_type=trip_type,
        return_date=return_date, extra_baggage=extra_baggage,
        extra_baggage_kg=extra_baggage_kg,
        travel_document_type=travel_document_type,
        travel_document_number=travel_document_number,
        manager_remarks=manager_remarks, total_bill=workflows.money(total_amount))
    if services:
        booking.services.set(services)

    for order, seat_number in enumerate(seats, start=1):
        _assign_seat(booking, flight, seat_number, passenger, fare_class, segment, order)

    trx = workflows.submit_booking(
        booking=booking, customer=passenger, establishment=establishment,
        session=session if session is not None else workflows.active_session_for(passenger),
        transaction_type=SimulationTransaction.Type.FLIGHT,
        total_amount=workflows.money(total_amount),
        payload={'flight_number': flight.flight_number, 'seats': seats,
                 'trip_type': trip_type, 'fare_class': fare_class})

    notify(passenger, Notification.Type.FLIGHT_RESERVATION_SUBMITTED,
           f'Your booking on flight {flight.flight_number} was received. '
           f'Reference {trx.reference}.',
           transaction=trx, title='Flight reservation received')

    return booking, trx


def verify_reservation(trx, agent, *, remarks=''):
    """The reservation agent checks the flight and seat and confirms the booking."""
    trx = workflows.review_booking(trx, agent, remarks=remarks)
    seats = ', '.join((trx.payload or {}).get('seats') or []) or 'no seat selected'
    notify(trx.initiator, Notification.Type.FLIGHT_RESERVATION_APPROVED,
           f'Flight {trx.payload.get("flight_number")} is reserved for you ({seats}). '
           f'Booking {trx.subject.booking_reference}. Your ticket has not been '
           'issued yet.',
           transaction=trx, title='Flight reservation approved')
    return trx


def decline_reservation(trx, agent, *, remarks=''):
    """The flight is full, or the passenger does not meet the requirements."""
    trx = workflows.decline_booking(trx, agent, remarks=remarks)
    notify(trx.initiator, Notification.Type.FLIGHT_RESERVATION_REJECTED,
           f'{trx.establishment.name} could not reserve your flight.'
           + (f' {remarks}' if remarks else ''),
           transaction=trx, title='Flight reservation rejected')
    return trx


def cancel_reservation(trx, actor, *, remarks=''):
    """Cancel a booking, which gives the seats back to everyone else."""
    trx = workflows.cancel_booking(trx, actor, remarks=remarks)
    notify(trx.initiator, Notification.Type.FLIGHT_RESERVATION_REJECTED,
           f'Booking {trx.subject.booking_reference} was cancelled.'
           + (f' {remarks}' if remarks else ''),
           transaction=trx, title='Flight booking cancelled')
    return trx


#: Statuses where a passenger or staff may still cancel the booking.
CANCELABLE_STATUSES = (
    Booking.Status.PENDING,
    Booking.Status.ON_HOLD,
    Booking.Status.RESERVED,
    Booking.Status.CONFIRMED,
    Booking.Status.MODIFIED,
)


def cancellation_quote(booking):
    """Work out what a cancellation would refund under the fare rules."""
    from decimal import Decimal

    from atrue_core.services import bill_for_booking

    itinerary = booking.itinerary
    if itinerary is None and booking.flight_id:
        itinerary = booking.flight.itinerary

    if itinerary is not None:
        refundable = bool(itinerary.is_refundable)
        fee = Decimal(itinerary.cancellation_fee or 0)
    else:
        # Legacy direct bookings predate fare rules: refund the fare rather
        # than silently keeping money the passenger was never warned about.
        refundable = True
        fee = Decimal('0')

    bill = bill_for_booking(booking)
    paid = Decimal(bill.amount_paid or 0) if bill else Decimal('0')
    refund_due = max(Decimal('0'), paid - fee) if refundable else Decimal('0')
    return {
        'bill': bill,
        'has_fare_terms': itinerary is not None,
        'refundable': refundable,
        'cancellation_fee': fee,
        'paid': paid,
        'refund_due': refund_due,
    }


def cancel_and_refund_booking(booking, actor, *, remarks=''):
    """Cancel a flight booking and refund any paid amount it is owed.

    The fare's own ``is_refundable`` flag and ``cancellation_fee`` decide how
    much goes back. Refunds are split across the bill's paid payments so a
    cancellation fee can be retained without inventing a separate charge.
    """
    from decimal import Decimal

    from atrue_core.services import bill_for_booking, cancel_booking, refund_payment
    from transactions.models import Payment

    if booking.status == Booking.Status.CANCELLED:
        raise AirlineWorkflowError('This booking is already cancelled.',
                                   code='already_cancelled')
    if booking.status not in CANCELABLE_STATUSES:
        raise AirlineWorkflowError(
            'This booking can no longer be cancelled.', code='not_cancellable')

    quote = cancellation_quote(booking)
    refunded = Decimal('0')

    with db_transaction.atomic():
        remaining = quote['refund_due']
        bill = quote['bill']
        if remaining > 0 and bill is not None:
            payments = bill.payments.filter(
                status__in=[Payment.Status.PAID, Payment.Status.PARTIALLY_REFUNDED],
            ).order_by('paid_at', 'pk')
            for payment in payments:
                if remaining <= 0:
                    break
                available = payment.remaining_refundable
                take = min(available, remaining)
                if take <= 0:
                    continue
                refund_payment(
                    payment=payment, user=actor, amount=take,
                    description=(f'Refund for cancelled flight booking '
                                 f'{booking.booking_reference}'))
                refunded += take
                remaining -= take

        cancel_booking(booking, actor, reason=remarks)

        bill = bill_for_booking(booking)
        if bill is not None:
            booking.refresh_from_db()
            booking.amount_paid = bill.amount_paid
            booking.balance_due = bill.balance_due
            booking.save(update_fields=['amount_paid', 'balance_due'])

    booking.refresh_from_db()
    if refunded > 0:
        message = (f'Booking {booking.booking_reference} was cancelled. '
                   f'PHP {refunded:,.2f} was refunded to your original payment.')
        notification_type = Notification.Type.PAYMENT_REFUNDED
        title = 'Flight booking cancelled and refunded'
    elif not quote['refundable']:
        message = (f'Booking {booking.booking_reference} was cancelled. '
                   'This fare is non-refundable, so no payment was returned.')
        notification_type = Notification.Type.FLIGHT_RESERVATION_REJECTED
        title = 'Flight booking cancelled'
    else:
        message = f'Booking {booking.booking_reference} was cancelled.'
        notification_type = Notification.Type.FLIGHT_RESERVATION_REJECTED
        title = 'Flight booking cancelled'
    notify(booking.passenger, notification_type, message, title=title)

    return {'refunded': refunded, 'quote': quote}


def issue_ticket(trx, ticketing_officer, *, remarks=''):
    """Issue the simulated ticket once the reservation is approved.

    Ticketing is a separate step rather than a flag on the booking so that
    "approved" and "ticketed" cannot be mistaken for one another.
    """
    trx = workflows.start_service(
        trx, ticketing_officer, remarks=remarks or 'Simulated ticket issued.',
        legacy_status=Booking.Status.CONFIRMED, action='ticket_issued')
    booking = trx.subject
    booking.status = Booking.Status.CONFIRMED
    booking.save(update_fields=['status'])

    notify(trx.initiator, Notification.Type.FLIGHT_TICKET_ISSUED,
           f'Your simulated ticket for flight {trx.payload.get("flight_number")} '
           f'is ready. Booking {booking.booking_reference}. This is a classroom '
           'artefact and is not a valid travel document.',
           transaction=trx, title='Ticket issued')
    return trx


def complete_flight(trx, actor, *, remarks=''):
    """The flight has been flown."""
    return workflows.start_service(trx, actor, remarks=remarks,
                                   legacy_status=Booking.Status.USED)


def send_to_billing(trx, actor, *, remarks=''):
    trx = workflows.send_to_billing(trx, actor, remarks=remarks)
    notify(trx.initiator, Notification.Type.BILLING_READY,
           f'Your flight on {trx.establishment.name} is ready for simulated billing.',
           transaction=trx, title='Ready for billing')
    return trx


def _as_airline(establishment):
    if establishment is None:
        raise AirlineWorkflowError('A flight booking needs an airline.',
                                   code='no_establishment')
    if establishment.type != Establishment.Type.AIRLINE:
        raise AirlineWorkflowError(
            f'{establishment.name} is a '
            f'{establishment.get_type_display().lower()}, not an airline.',
            code='wrong_establishment_type')
    return establishment


def _held_seat_query(flight, seat_number):
    """Booking rows still holding ``seat_number`` on ``flight``.

    ``Flight.itinerary_seat_entries`` is the reverse of ``BookingSeat.flight``, so
    this asks the bookings rather than the seat layout: a cancelled or declined
    booking no longer holds the seat.
    """
    return flight.itinerary_seat_entries.filter(seat_number=seat_number).exclude(
        booking__status__in=RELEASED_STATUSES)


def _ensure_seat_available(flight, seat_number, excluding_booking=None):
    """Refuse a seat somebody else already holds on this flight."""
    taken = _held_seat_query(flight, seat_number)
    if excluding_booking is not None:
        taken = taken.exclude(booking=excluding_booking)
    if taken.exists():
        raise AirlineWorkflowError(
            f'Seat {seat_number} on flight {flight.flight_number} is already taken.',
            code='seat_taken')


def _assign_seat(booking, flight, seat_number, passenger, fare_class, segment, order):
    """Record the seat under a lock, so two passengers cannot claim one.

    The check runs inside the same atomic block as the insert, which is what stops
    two simultaneous bookings from both seeing the seat as free.
    """
    with db_transaction.atomic():
        locked_flight = Flight.objects.select_for_update().get(pk=flight.pk)
        if _held_seat_query(locked_flight, seat_number).exists():
            raise AirlineWorkflowError(
                f'Seat {seat_number} was taken a moment ago.', code='seat_taken')
        booking.BookingSeat.objects.create(
            booking=booking, flight=locked_flight, seat_number=seat_number,
            segment=segment or locked_flight.flight_number,
            segment_order=order, fare_class=fare_class,
            passenger_name=passenger.get_full_name() or passenger.get_username())