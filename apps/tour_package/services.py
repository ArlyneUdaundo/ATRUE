"""Tour operator workflow (Section 11).

    customer books a package -> coordinator checks capacity -> guide runs the tour
    -> attendance recorded -> simulated billing

Specific to a tour is that capacity is finite and the guide has to be assigned
before the tour can run, which is why fulfilment is a real step here rather than a
status change.
"""

from django.db import transaction as db_transaction

from establishments.models import Establishment
from notifications.models import Notification
from notifications.services import notify
from simulation import workflows
from simulation.models import SimulationTransaction

from .models import Booking, TourPackage


class TourWorkflowError(workflows.WorkflowError):
    pass


def book_package(*, customer, establishment, package, total_amount, travel_date,
                 number_of_travelers=1, number_of_adults=1, number_of_children=0,
                 start_time=None, end_time=None, payment_method='', special_requests='',
                 session=None):
    """A customer books a tour package."""
    _ensure_bookable(package, number_of_travelers)
    from simulation.models import SimulationRoleAssignment

    assigned_guest = SimulationRoleAssignment.objects.filter(
        student=customer,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role__in=('TOUR_GUEST', 'CUSTOMER_TOUR'),
        establishment__type='TOUR_PACKAGE',
        establishment__entity_id=package.pk,
    ).exists()
    if not assigned_guest:
        raise TourWorkflowError(
            'The customer is not assigned to this tour package.',
            code='package_not_assigned')
    establishment = _as_tour_operator(establishment)

    booking = Booking.objects.create(
        customer=customer, package=package, travel_date=travel_date,
        start_time=start_time, end_time=end_time,
        number_of_travelers=number_of_travelers,
        number_of_adults=number_of_adults, number_of_children=number_of_children,
        payment_method=payment_method, special_requests=special_requests,
        total_bill=workflows.money(total_amount))

    trx = workflows.submit_booking(
        booking=booking, customer=customer, establishment=establishment,
        session=session if session is not None else workflows.active_session_for(customer),
        transaction_type=SimulationTransaction.Type.TOUR,
        total_amount=workflows.money(total_amount),
        party_size=number_of_travelers,
        payload={'package': str(package), 'travel_date': str(travel_date)})

    notify(customer, Notification.Type.TOUR_REQUEST_SUBMITTED,
           f'Your booking for {package} on {travel_date} was received. '
           f'Reference {trx.reference}.',
           transaction=trx, title='Tour request received')

    return booking, trx


def confirm_booking(trx, coordinator, *, remarks=''):
    trx = workflows.review_booking(trx, coordinator, remarks=remarks)
    notify(trx.initiator, Notification.Type.TOUR_REQUEST_APPROVED,
           f'{trx.establishment.name} has confirmed your tour for '
           f'{trx.subject.travel_date}. Booking {trx.subject.booking_reference}. '
           'This is a simulated tour booking.',
           transaction=trx, title='Tour confirmed')
    return trx


def decline_booking(trx, coordinator, *, remarks=''):
    trx = workflows.decline_booking(trx, coordinator, remarks=remarks)
    notify(trx.initiator, Notification.Type.TOUR_REQUEST_REJECTED,
           f'{trx.establishment.name} could not take your booking.'
           + (f' {remarks}' if remarks else ''),
           transaction=trx, title='Tour request rejected')
    return trx


def assign_guide(trx, guide, *, remarks=''):
    """A guide takes the tour; the tour cannot start without one."""
    trx = workflows.start_service(trx, guide, remarks=remarks or 'Guide assigned.',
                                  legacy_status=Booking.Status.CONFIRMED)
    notify(trx.initiator, Notification.Type.TOUR_REQUEST_APPROVED,
           f'{guide.get_full_name() or guide.get_username()} is guiding your tour '
           f'on {trx.subject.travel_date}.',
           transaction=trx, title='Guide assigned')
    return trx


def record_attendance(trx, guide, *, participants=()):
    """The guide records who actually turned up."""
    recorded = ', '.join(str(name) for name in participants) or 'all booked travellers'
    trx = workflows.start_service(trx, guide,
                                  remarks=f'Attendance recorded: {recorded}.',
                                  legacy_status=Booking.Status.USED)
    notify(trx.initiator, Notification.Type.TOUR_COMPLETED,
           f'Your tour on {trx.subject.travel_date} has finished. '
           f'Participants recorded: {recorded}.',
           transaction=trx, title='Tour completed')
    return trx


def send_to_billing(trx, actor, *, remarks=''):
    return workflows.send_to_billing(trx, actor, remarks=remarks)


def _as_tour_operator(establishment):
    if establishment is None:
        raise TourWorkflowError('A tour booking needs a tour operator.',
                                code='no_establishment')
    if establishment.type != Establishment.Type.TOUR_OPERATOR:
        raise TourWorkflowError(
            f'{establishment.name} is a '
            f'{establishment.get_type_display().lower()}, not a tour operator.',
            code='wrong_establishment_type')
    return establishment


def _ensure_bookable(package, travellers):
    """Refuse a package that is not on sale, or over the headcount it includes.

    The package carries a status of its own (a fully booked or expired package
    must not be sold) plus the headcount its price includes; anything beyond that
    headcount is a quote, not a booking.
    """
    if package.status != TourPackage.Status.ACTIVE:
        raise TourWorkflowError(
            f'{package.name} is {package.get_status_display().lower()} and is not '
            'being sold.', code='package_not_available')

    included = package.included_headcount or 0
    if travellers > included:
        raise TourWorkflowError(
            f'{package.name} includes {included} traveller(s); {travellers} were '
            'asked for, which needs a quote rather than a booking.',
            code='over_capacity')
