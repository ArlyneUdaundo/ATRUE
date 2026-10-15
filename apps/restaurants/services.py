"""Transactional restaurant reservation operations."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from establishments.models import Establishment
from notifications.models import Notification
from notifications.services import notify, notify_many
from simulation.models import SimulationRoleAssignment

from .models import Reservation, Table

TABLE_WINDOW_MINUTES = 120
INACTIVE_RESERVATION_STATUSES = (
    Reservation.Status.CANCELLED,
    Reservation.Status.COMPLETED,
    Reservation.Status.CHECKED_OUT,
    Reservation.Status.DECLINED,
    Reservation.Status.REJECTED,
    Reservation.Status.RETURNED,
    Reservation.Status.USED,
)


class RestaurantReservationError(ValueError):
    """A reservation cannot move to the requested state."""


def table_has_conflict(table, when, *, exclude_reservation_id=None):
    start = when - timedelta(minutes=TABLE_WINDOW_MINUTES)
    end = when + timedelta(minutes=TABLE_WINDOW_MINUTES)
    reservations = Reservation.objects.filter(
        table=table,
        reservation_datetime__range=(start, end),
    ).exclude(status__in=INACTIVE_RESERVATION_STATUSES)
    if exclude_reservation_id is not None:
        reservations = reservations.exclude(pk=exclude_reservation_id)
    return reservations.exists()


def _establishment_for_restaurant(restaurant_id):
    return Establishment.objects.filter(
        type=Establishment.Type.RESTAURANT,
        entity_id=restaurant_id,
    ).first()


def _notify_assigned_officers(reservation):
    establishment = _establishment_for_restaurant(reservation.table.restaurant_id)
    officers = SimulationRoleAssignment.objects.filter(
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role__in=(
            SimulationRoleAssignment.Role.RESTAURANT_MANAGER,
            SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER,
        ),
        establishment__type=Establishment.Type.RESTAURANT,
        establishment__entity_id=reservation.table.restaurant_id,
    ).select_related('student')
    message = (
        f"Reservation {reservation.booking_reference} from "
        f"{reservation.customer.get_full_name() or reservation.customer.username} "
        f"at {reservation.table.restaurant.name} is pending review. "
        f"{reservation.reservation_datetime:%b %d, %Y %H:%M}; "
        f"Table {reservation.table.table_number}; "
        f"{reservation.number_of_guests} guest(s)."
    )
    notify_many(
        [assignment.student for assignment in officers],
        Notification.Type.RESTAURANT_RESERVATION_SUBMITTED,
        message,
        establishment=establishment,
        title='Restaurant Reservation Submitted',
    )


def create_restaurant_reservation(
    *, customer, table, when, guests, deposit=0, seating_preference='',
    occasion=Reservation.Occasion.NONE, special_requests='',
    additional_notes='', payer_name='', payer_contact='',
):
    with transaction.atomic():
        locked_table = Table.objects.select_for_update().select_related(
            'restaurant',
        ).get(pk=table.pk)
        if locked_table.status == Table.Status.MAINTENANCE:
            raise RestaurantReservationError(
                'This table is not currently available for booking.')
        if guests < 1:
            raise RestaurantReservationError(
                'At least one guest is required.')
        if guests > locked_table.capacity:
            raise RestaurantReservationError(
                f"Party of {guests} exceeds this table's capacity of "
                f"{locked_table.capacity}.")
        if table_has_conflict(locked_table, when):
            raise RestaurantReservationError(
                'This table is already reserved for the requested time slot.')

        reservation = Reservation.objects.create(
            customer=customer,
            table=locked_table,
            reservation_datetime=when,
            number_of_guests=guests,
            seating_preference=seating_preference,
            occasion=occasion,
            special_requests=special_requests,
            additional_notes=additional_notes,
            payer_name=payer_name,
            payer_contact=payer_contact,
            deposit=deposit,
            status=Reservation.Status.PENDING,
        )
        _notify_assigned_officers(reservation)
        return reservation


def confirm_restaurant_reservation(*, reservation_id, officer, remarks=''):
    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().select_related(
            'customer', 'table__restaurant',
        ).get(pk=reservation_id)
        if reservation.status != Reservation.Status.PENDING:
            raise RestaurantReservationError(
                'Only pending reservations can be confirmed.')

        table = Table.objects.select_for_update().get(pk=reservation.table_id)
        if (table.status == Table.Status.MAINTENANCE
                or table_has_conflict(
                    table,
                    reservation.reservation_datetime,
                    exclude_reservation_id=reservation.pk,
                )):
            raise RestaurantReservationError(
                'This table is no longer available for the selected date and time.')

        establishment = _establishment_for_restaurant(table.restaurant_id)
        from transactions.models import Bill
        from atrue_core.services import bill_for_booking
        bill = bill_for_booking(reservation)
        if bill is None or bill.status != Bill.Status.FULLY_PAID or not bill.verified_at:
            raise RestaurantReservationError(
                'A Billing Officer must verify the fully paid deposit before this reservation can be confirmed.')
        reservation.status = Reservation.Status.CONFIRMED
        reservation.confirmed_at = timezone.now()
        reservation.confirmed_by = officer
        if remarks:
            reservation.manager_remarks = remarks
        reservation.save(update_fields=[
            'status', 'confirmed_at', 'confirmed_by', 'manager_remarks',
        ])
        notify(
            reservation.customer,
            Notification.Type.RESTAURANT_RESERVATION_CONFIRMED,
            (
                f"Your reservation at {table.restaurant.name} has been confirmed. "
                f"Date: {reservation.reservation_datetime:%b %d, %Y}; "
                f"Time: {reservation.reservation_datetime:%H:%M}; "
                f"Table: {table.table_number}; "
                f"Guests: {reservation.number_of_guests}; "
                f"Reservation ID: {reservation.booking_reference}; "
                f"Status: CONFIRMED. Confirmed by: Restaurant Reservation Officer "
                f"({officer.get_full_name() or officer.username}) at "
                f"{reservation.confirmed_at:%b %d, %Y %H:%M}."
            ),
            establishment=establishment,
            title='Restaurant Reservation Confirmed',
        )
        from atrue_core.services import log_activity

        log_activity(
            officer,
            'Confirmed restaurant reservation',
            f'{reservation.booking_reference} at {table.restaurant.name}',
            establishment=establishment,
        )
        from simulation.completion import complete_reservation_confirmation

        if establishment is not None:
            complete_reservation_confirmation(
                officer, establishment=establishment,
                booking_reference=reservation.booking_reference,
            )
        from notifications.email_service import queue_booking_confirmation
        queue_booking_confirmation(reservation)
        return reservation


def reject_restaurant_reservation(*, reservation_id, officer, reason, remarks=''):
    reason = reason.strip()
    if not reason:
        raise RestaurantReservationError(
            'Please provide a reason for rejecting this reservation.')

    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().select_related(
            'customer', 'table__restaurant',
        ).get(pk=reservation_id)
        if reservation.status != Reservation.Status.PENDING:
            raise RestaurantReservationError(
                'Only pending reservations can be rejected.')

        establishment = _establishment_for_restaurant(
            reservation.table.restaurant_id,
        )
        reservation.status = Reservation.Status.REJECTED
        reservation.declined_reason = reason
        reservation.declined_at = timezone.now()
        if remarks:
            reservation.manager_remarks = remarks
        reservation.save(update_fields=[
            'status', 'declined_reason', 'declined_at', 'manager_remarks',
        ])
        notify(
            reservation.customer,
            Notification.Type.RESTAURANT_RESERVATION_REJECTED,
            (
                f"Your reservation at {reservation.table.restaurant.name} "
                f"({reservation.booking_reference}) was rejected. "
                f"Reason: {reason}"
            ),
            establishment=establishment,
            title='Restaurant Reservation Rejected',
        )
        from atrue_core.services import log_activity

        log_activity(
            officer,
            'Rejected restaurant reservation',
            f'{reservation.booking_reference}: {reason}',
            establishment=establishment,
        )
        return reservation
