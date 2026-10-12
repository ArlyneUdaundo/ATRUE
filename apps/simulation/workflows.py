"""Shared workflow steps for the four booking-based establishments (Sections 8-12).

Hotel, airline, tour operator and transportation all follow the same shape:

    guest/passenger books -> reservation desk reviews -> service is delivered
    -> simulated billing settles it

Only the *details* differ (a room, a seat, a guide, a driver), so the steps live
here once and each app's ``services`` module supplies its own specifics. That is
deliberate: if the routing, claiming, isolation or self-approval rules change,
they change for every establishment at the same time and cannot be quietly
forgotten in one of them.

This module also keeps the legacy ``Booking.status`` in step with the
``SimulationTransaction``. The booking tables predate the simulation and other
pages still read them, so leaving them disagreeing would show a student a
"confirmed" booking that the workflow has actually cancelled.
"""

from decimal import Decimal, InvalidOperation

from audit_logs.services import audit
from notifications.models import Notification
from notifications.services import notify
from simulation import engine
from simulation.models import SimulationTransaction


class WorkflowError(Exception):
    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.code = code


def money(value):
    try:
        return Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


#: How a simulation transaction's state maps onto the legacy booking status that
#: the rest of the platform still displays.
LEGACY_STATUS = {
    SimulationTransaction.Status.DRAFT: 'PENDING',
    SimulationTransaction.Status.PENDING: 'PENDING',
    SimulationTransaction.Status.UNDER_REVIEW: 'PENDING',
    SimulationTransaction.Status.CONFIRMED: 'CONFIRMED',
    SimulationTransaction.Status.REJECTED: 'DECLINED',
    SimulationTransaction.Status.CANCELLED: 'CANCELLED',
    SimulationTransaction.Status.COMPLETED: 'COMPLETED',
}


def sync_booking_status(transaction, booking=None, *, override=None):
    """Mirror the transaction's state onto the legacy booking row.

    ``override`` is for the statuses only the establishment itself knows about -
    CHECKED_IN and CHECKED_OUT are real service events the transaction does not
    model. Subjects with no ``status`` field (a travel request, for instance) are
    left alone rather than being forced into a shape they do not have.
    """
    booking = booking if booking is not None else transaction.subject
    if booking is None or not hasattr(booking, 'status'):
        return None
    wanted = override or LEGACY_STATUS.get(transaction.status, 'PENDING')
    if booking.status != wanted:
        booking.status = wanted
        booking.save(update_fields=['status'])
    return booking


def submit_booking(*, booking, customer, establishment, session, transaction_type,
                   total_amount, **payload):
    """A customer books; the reservation desk is handed the request."""
    trx = engine.submit_transaction(
        subject=booking,
        transaction_type=transaction_type,
        initiator=customer,
        establishment=establishment,
        session=session,
        total_amount=total_amount,
        **payload,
    )
    audit(f'{transaction_type}.booking_submitted', actor=customer, transaction=trx,
          details=f'{booking.booking_reference}.',
          new_value=booking.booking_reference)

    notify(customer, Notification.Type.GENERAL,
           f'Your booking {booking.booking_reference} was received and is now '
           f'with the reservation desk. Reference {trx.reference}.',
           transaction=trx, title='Booking received')

    return trx


def review_booking(trx, officer, *, remarks='', stage=None):
    """The reservation desk claims and confirms a booking.

    An approval always hands the request on - to fulfilment, or straight to
    billing for a request that needs no preparation - so the reservation desk
    accepting a booking moves it out of intake. The legacy booking row is marked
    CONFIRMED because that is what the existing pages show.
    """
    trx.refresh_from_db()
    if not trx.is_claimed:
        trx = engine.claim_transaction(trx, officer,
                                       remarks=remarks or 'Claimed to review the booking.')
    if stage is None:
        trx = engine.approve(trx, officer, remarks=remarks or 'Reservation accepted.')
    else:
        trx = engine.approve(trx, officer, stage=stage,
                             remarks=remarks or 'Reservation accepted.')
    sync_booking_status(trx)
    return trx


def start_service(trx, actor, *, remarks='', legacy_status='CHECKED_IN', action='start_service'):
    """Record that service has begun, without moving the request.

    The request is already at the fulfilment stage by the time anything is
    delivered to a customer - that is what the approval did. Checking somebody in,
    dispatching a vehicle or issuing a ticket happens *inside* that stage, so this
    records an event and leaves the request where it is.
    """
    trx.refresh_from_db()
    if trx.stage != SimulationTransaction.Stage.FULFILLMENT:
        raise engine.StageMismatchError(
            f'The service has not been approved yet: {trx.reference} is at the '
            f'{trx.get_stage_display().lower()} stage.')

    trx = engine.record_progress(trx, actor, action, remarks=remarks)
    sync_booking_status(trx, override=legacy_status)
    return trx


def finish_service(trx, actor, *, remarks='', legacy_status='CHECKED_OUT'):
    """The service has been delivered, so the request is finished.

    ``engine.fulfil`` is the completion that belongs to fulfilment; the other
    completion in the engine, ``complete``, is the one billing uses once a bill is
    settled, and it may only be used from the billing stage.
    """
    trx.refresh_from_db()
    if trx.stage == SimulationTransaction.Stage.FULFILLMENT:
        if not trx.is_claimed:
            # Closing out the service is work on the request, so it is picked up
            # first. The engine still checks the actor's assignment and refuses
            # anyone who raised the request themselves.
            trx = engine.claim_transaction(
                trx, actor, remarks=remarks or 'Claimed to close the service.')
        trx = engine.fulfil(trx, actor, remarks=remarks or 'Service delivered.')
    elif trx.stage != SimulationTransaction.Stage.DONE:
        raise engine.StageMismatchError(
            f'The service cannot be finished from the '
            f'{trx.get_stage_display().lower()} stage.')

    sync_booking_status(trx, override=legacy_status)
    return trx


def send_to_billing(trx, actor, *, remarks=''):
    """Forward the finished booking for simulated billing."""
    trx.refresh_from_db()
    if not trx.is_claimed:
        # Approving a booking hands it on and releases the claim, so whoever
        # delivers the service picks it up again to pass it to billing.
        trx = engine.claim_transaction(
            trx, actor, remarks=remarks or 'Claimed to forward the request for billing.')
    trx = engine.forward_to_billing(trx, actor, remarks=remarks)
    sync_booking_status(trx)
    return trx


def decline_booking(trx, officer, *, remarks=''):
    trx = engine.reject(trx, officer, remarks=remarks)
    sync_booking_status(trx)
    return trx


def cancel_booking(trx, actor, *, remarks=''):
    """Cancel a booking, before or after service has started."""
    trx = engine.cancel(trx, actor, remarks=remarks)
    sync_booking_status(trx)
    return trx


def active_session_for(user, establishment=None):
    """The one active session this student belongs to, or ``None``.

    ``None`` is allowed on purpose: a customer booking outside an activity is
    legitimate, and the engine will simply require an approver.
    """
    from simulation.models import SimulationRoleAssignment, SimulationSession

    sessions = SimulationSession.objects.filter(
        status=SimulationSession.Status.ACTIVE,
        assignments__student=user,
        assignments__status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).distinct()
    return sessions.first() if sessions.count() == 1 else None