"""Transportation workflow (Section 12).

    customer books a vehicle -> reservation officer verifies the route and vehicle
    -> dispatcher sends the driver -> trip happens -> simulated billing

The distinguishing step is dispatch: an approved booking is not yet on the road,
and a trip without a driver is not a trip, so dispatch is a real workflow step and
the customer is told about it separately.
"""

from django.db import transaction as db_transaction

from establishments.models import Establishment
from notifications.models import Notification
from notifications.services import notify
from simulation import workflows
from simulation.models import SimulationTransaction

from .models import Booking


class TransportWorkflowError(workflows.WorkflowError):
    pass


#: Statuses in which a trip is still going to happen. Anything else (rejected,
#: cancelled, completed) does not hold a driver up.
OPEN_STATUSES = [
    SimulationTransaction.Status.DRAFT,
    SimulationTransaction.Status.PENDING,
    SimulationTransaction.Status.UNDER_REVIEW,
    SimulationTransaction.Status.CONFIRMED,
]


def book_vehicle(*, customer, establishment, vehicle, total_amount, pickup_location,
                 drop_off_location, schedule, distance_km=0, duration_hours=1,
                 passengers=1, driver=None, special_requests='', session=None):
    """A customer books a vehicle."""
    establishment = _as_transport(establishment)
    if driver is not None and driver_is_busy(driver):
        raise TransportWorkflowError(
            f'{driver} is already on a trip.', code='driver_unavailable')

    booking = Booking.objects.create(
        customer=customer, vehicle=vehicle, driver=driver,
        pickup_location=pickup_location, drop_off_location=drop_off_location,
        distance_km=workflows.money(distance_km),
        schedule=schedule, duration_hours=duration_hours, passengers=passengers,
        special_requests=special_requests, total_bill=workflows.money(total_amount))

    trx = workflows.submit_booking(
        booking=booking, customer=customer, establishment=establishment,
        session=session if session is not None else workflows.active_session_for(customer),
        transaction_type=SimulationTransaction.Type.TRANSPORTATION,
        total_amount=workflows.money(total_amount),
        party_size=passengers,
        payload={'vehicle': str(vehicle), 'route': f'{pickup_location} to {drop_off_location}',
                 'schedule': str(schedule)})

    notify(customer, Notification.Type.TRANSPORT_REQUEST_SUBMITTED,
           f'Your transport request from {pickup_location} to {drop_off_location} '
           f'was received. Reference {trx.reference}.',
           transaction=trx, title='Transport request received')

    return booking, trx


def confirm_request(trx, officer, *, remarks=''):
    trx = workflows.review_booking(trx, officer, remarks=remarks)
    notify(trx.initiator, Notification.Type.TRANSPORT_REQUEST_APPROVED,
           f'{trx.establishment.name} has approved your trip from '
           f'{trx.subject.pickup_location} to {trx.subject.drop_off_location}. '
           f'Booking {trx.subject.booking_reference}.',
           transaction=trx, title='Transport request approved')
    return trx


def decline_request(trx, officer, *, remarks=''):
    trx = workflows.decline_booking(trx, officer, remarks=remarks)
    notify(trx.initiator, Notification.Type.TRANSPORT_REQUEST_REJECTED,
           f'{trx.establishment.name} could not take your trip.'
           + (f' {remarks}' if remarks else ''),
           transaction=trx, title='Transport request rejected')
    return trx


def driver_is_busy(driver):
    """Is this driver already out on a trip?

    ``Driver.status`` records whether they are employed, not whether they are
    currently driving, and there is no column for the second. It is worked out
    from the driver's bookings instead: a driver is busy while any of their
    bookings still has an open simulation transaction. Cancelled, rejected and
    completed trips do not hold anybody up.
    """
    from django.contrib.contenttypes.models import ContentType

    from simulation.models import SimulationTransaction

    content_type = ContentType.objects.get_for_model(Booking)
    booking_ids = Booking.objects.filter(driver=driver).values_list('pk', flat=True)
    return SimulationTransaction.objects.filter(
        subject_type=content_type,
        subject_id__in=booking_ids,
        status__in=OPEN_STATUSES,
    ).exists()


def dispatch(trx, dispatcher, *, driver=None, remarks=''):
    """Send the vehicle and driver out.

    Availability is re-checked here rather than trusted from the booking, because
    the driver may have been given another trip in between.
    """
    driver = driver if driver is not None else trx.subject.driver
    if driver is None:
        raise TransportWorkflowError('A trip needs a driver.', code='no_driver')
    if driver_is_busy(driver) and driver.pk != trx.subject.driver_id:
        raise TransportWorkflowError(
            f'{driver} is already on a trip.', code='driver_unavailable')

    trx.subject.driver = driver
    trx.subject.save(update_fields=['driver'])

    trx = workflows.start_service(trx, dispatcher,
                                  remarks=remarks or 'Vehicle dispatched.',
                                  legacy_status=Booking.Status.CONFIRMED,
                                  action='dispatch')

    notify(trx.initiator, Notification.Type.TRANSPORT_DISPATCHED,
           f'Your vehicle is on its way from {trx.subject.pickup_location}. '
           f'Booking {trx.subject.booking_reference}.',
           transaction=trx, title='Vehicle dispatched')
    return trx


def complete_trip(trx, dispatcher, *, remarks=''):
    """The trip has finished, which frees the driver for the next one."""
    return workflows.finish_service(trx, dispatcher, remarks=remarks,
                                    legacy_status=Booking.Status.COMPLETED)


def send_to_billing(trx, actor, *, remarks=''):
    return workflows.send_to_billing(trx, actor, remarks=remarks)


def _as_transport(establishment):
    if establishment is None:
        raise TransportWorkflowError('A transport booking needs a transport company.',
                                     code='no_establishment')
    if establishment.type != Establishment.Type.TRANSPORTATION:
        raise TransportWorkflowError(
            f'{establishment.name} is a '
            f'{establishment.get_type_display().lower()}, not a transport company.',
            code='wrong_establishment_type')
    return establishment