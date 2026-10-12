"""Hotel workflow (Section 8).

    guest books rooms -> reservation desk confirms -> guest checks in
    -> checkout -> simulated billing

The steps come from :mod:`simulation.workflows`; what is specific to a hotel is
that a booking has rooms attached to it, and that checking in and checking out are
real events that change the booking the guest sees.

Nothing here books a real room. Room availability is checked only against the
classroom's own records, and "confirmed" means a student reservation desk said so.
"""

from django.db import transaction as db_transaction
from django.utils import timezone

from establishments.models import Establishment
from notifications.models import Notification
from notifications.services import notify
from simulation import engine, workflows
from simulation.models import SimulationTransaction

from .models import Booking, Room

#: ``Room.status`` is a plain choices field rather than an enum in this app, so
#: the codes are named here. Deliberately an allow-list: if a status is added to
#: the model later it is treated as *not* bookable until somebody decides it
#: should be, which is the safe direction to fail in.
ROOM_AVAILABLE = 'AVAILABLE'
ROOM_OCCUPIED = 'OCCUPIED'
BOOKABLE_ROOM_STATUSES = {ROOM_AVAILABLE}


class HotelWorkflowError(workflows.WorkflowError):
    pass


def book_room(*, guest, establishment, rooms, total_amount, check_in, check_out,
              special_requests='', session=None, payer_name='', payer_contact=''):
    """A guest books one or more rooms for a set of dates.

    ``check_in`` and ``check_out`` are required because the booking/room join row
    stores the stay dates; they are what the front desk works from.
    """
    establishment = _as_hotel(establishment)
    rooms = list(rooms)
    if not rooms:
        raise HotelWorkflowError('A booking needs at least one room.', code='no_rooms')
    if check_out <= check_in:
        raise HotelWorkflowError('Check-out has to be after check-in.',
                                 code='bad_dates')
    _ensure_available(rooms)

    booking = Booking.objects.create(
        customer=guest, special_requests=special_requests,
        payer_name=payer_name or guest.get_full_name() or guest.get_username(),
        payer_contact=payer_contact,
        # The booking row timestamps are datetimes while the per-room rows store
        # plain dates, so the stay dates are widened here rather than passing a
        # date into a datetime field.
        checked_in_at=_midnight(check_in), checked_out_at=_midnight(check_out))
    booking.rooms.set(rooms, through_defaults=_stay_details(
        guest, check_in, check_out, special_requests, payer_contact))

    trx = workflows.submit_booking(
        booking=booking, customer=guest, establishment=establishment,
        session=session if session is not None else workflows.active_session_for(guest),
        transaction_type=SimulationTransaction.Type.HOTEL,
        total_amount=workflows.money(total_amount),
        party_size=len(rooms),
        payload={'rooms': [room.room_number for room in rooms],
                 'check_in': str(check_in or ''), 'check_out': str(check_out or '')})

    notify(guest, Notification.Type.HOTEL_RESERVATION_SUBMITTED,
           f'Your room request for {establishment.name} was received. '
           f'Reference {trx.reference}.',
           transaction=trx, title='Reservation received')

    return booking, trx


def confirm_reservation(trx, officer, *, remarks=''):
    """The reservation desk accepts the booking."""
    trx = workflows.review_booking(trx, officer, remarks=remarks)
    notify(trx.initiator, Notification.Type.HOTEL_RESERVATION_APPROVED,
           f'{trx.establishment.name} has reserved '
           f'{", ".join(trx.payload.get("rooms", []))} for you. '
           f'Booking {trx.subject.booking_reference}. This is a simulated reservation.',
           transaction=trx, title='Reservation confirmed')
    return trx


def decline_reservation(trx, officer, *, remarks=''):
    """No rooms can be held after all."""
    trx = workflows.decline_booking(trx, officer, remarks=remarks)
    notify(trx.initiator, Notification.Type.HOTEL_RESERVATION_REJECTED,
           f'{trx.establishment.name} could not reserve your rooms.'
           + (f' {remarks}' if remarks else ''),
           transaction=trx, title='Reservation declined')
    return trx


def cancel_reservation(trx, actor, *, remarks=''):
    trx = workflows.cancel_booking(trx, actor, remarks=remarks)
    notify(trx.initiator, Notification.Type.HOTEL_RESERVATION_CANCELLED,
           f'Booking {trx.subject.booking_reference} was cancelled.'
           + (f' {remarks}' if remarks else ''),
           transaction=trx, title='Reservation cancelled')
    return trx


def check_in(trx, receptionist, *, remarks=''):
    """The guest arrives; the rooms become occupied.

    Only hotel staff may do this. The engine would let the guest themselves report
    an arrival, because that is a reasonable thing for a customer to say, but
    moving rooms into OCCUPIED is the hotel's own operational record and must not
    be something a guest can do to themselves.
    """
    _require_hotel_staff(trx, receptionist)
    booking = trx.subject
    with db_transaction.atomic():
        for room in booking.rooms.all():
            room.status = ROOM_OCCUPIED
            room.save(update_fields=['status'])

    trx = workflows.start_service(trx, receptionist, remarks=remarks,
                                  legacy_status=Booking.Status.CHECKED_IN,
                                  action='check_in')

    notify(trx.initiator, Notification.Type.HOTEL_RESERVATION_APPROVED,
           f'You have checked in at {trx.establishment.name}. '
           f'Booking {trx.subject.booking_reference}.',
           transaction=trx, title='Checked in')
    return trx


def check_out(trx, receptionist, *, remarks=''):
    """The guest leaves; the rooms are cleaned and re-offered."""
    _require_hotel_staff(trx, receptionist)
    booking = trx.subject
    with db_transaction.atomic():
        for room in booking.rooms.all():
            room.status = ROOM_AVAILABLE
            room.save(update_fields=['status'])

    trx = workflows.start_service(trx, receptionist,
                                  remarks=remarks or 'Guest checked out.',
                                  legacy_status=Booking.Status.CHECKED_OUT,
                                  action='check_out')
    return trx


def send_to_billing(trx, actor, *, remarks=''):
    """Forward the stay for simulated billing."""
    trx = workflows.send_to_billing(trx, actor, remarks=remarks)
    notify(trx.initiator, Notification.Type.BILLING_READY,
           f'Your stay at {trx.establishment.name} is ready for simulated billing.',
           transaction=trx, title='Ready for billing')
    return trx


def complete_stay(trx, actor, *, remarks=''):
    """The stay is finished; only billing can close it now."""
    return workflows.finish_service(trx, actor, remarks=remarks,
                                    legacy_status=Booking.Status.COMPLETED)


def _midnight(day):
    """The start of ``day`` as a timezone-aware datetime."""
    from datetime import datetime, time as time_of_day

    return timezone.make_aware(datetime.combine(day, time_of_day.min))


def _require_hotel_staff(trx, actor):
    """Refuse anyone who is not assigned to this hotel for the request's session."""
    from simulation.models import SimulationRoleAssignment

    held = SimulationRoleAssignment.objects.filter(
        student=actor, establishment=trx.establishment,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        session=trx.session).exists()
    if not held:
        raise HotelWorkflowError(
            f'{actor} does not work at {trx.establishment.name} and cannot record '
            'room occupancy.', code='not_hotel_staff')


def _stay_details(guest, check_in, check_out, special_requests, payer_contact):
    """Details the booking/room join row needs for every room in the booking."""
    first, _, last = (guest.get_full_name() or guest.get_username()).partition(' ')
    return {
        'check_in': check_in, 'check_out': check_out,
        'number_of_adults': 1, 'number_of_children': 0,
        'guest_first_name': first or 'Guest',
        'guest_middle_name': '', 'guest_last_name': last or '',
        'guest_email': guest.email or '',
        'guest_contact': payer_contact or '',
        'guest_special_request': special_requests or '',
    }


def _as_hotel(establishment):
    if establishment is None:
        raise HotelWorkflowError('A hotel booking needs a hotel.',
                                 code='no_establishment')
    if establishment.type != Establishment.Type.HOTEL:
        raise HotelWorkflowError(
            f'{establishment.name} is a {establishment.get_type_display().lower()}, '
            'not a hotel.', code='wrong_establishment_type')
    return establishment


def _ensure_available(rooms):
    """Refuse rooms that are already held, so two guests cannot claim one.

    Availability is the classroom's own room table; no external inventory system
    is consulted, because there isn't one.
    """
    taken = [room for room in rooms if room.status not in BOOKABLE_ROOM_STATUSES]
    if taken:
        names = ', '.join(f'{room.room_number} ({room.get_status_display().lower()})'
                          for room in taken)
        raise HotelWorkflowError(f'Those rooms are not available: {names}.',
                                 code='room_not_available')