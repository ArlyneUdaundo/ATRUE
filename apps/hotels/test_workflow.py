"""Hotel workflow tests (Section 8).

These read as the guest's journey and the front desk's rules: a room can only be
held once, only the hotel's own staff may confirm it, and the booking row the rest
of the site displays never disagrees with the simulation transaction.
"""

from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from atrue_core import services as core_services
from billing import services as billing_services
from billing.models import SimulatedBill
from establishments.models import Establishment, establishment_for_instance
from hotels import services
from hotels.models import Booking, Hotel, Room
from hotels.views import _room_turnover_conflict
from notifications.models import Notification
from simulation import engine
from simulation.models import SimulationRoleAssignment, SimulationSession, SimulationTransaction
from simulation.role_catalogue import sync_role_catalogue

User = get_user_model()

STAY_IN = timezone.now().date()
STAY_OUT = STAY_IN + timedelta(days=2)


class HotelWorkflowTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.guest = User.objects.create_user(
            'guest', password='pw', account_type=User.AccountType.STUDENT)
        cls.front_desk = User.objects.create_user(
            'frontdesk', password='pw', account_type=User.AccountType.STUDENT)
        cls.housekeeper = User.objects.create_user(
            'housekeeper', password='pw', account_type=User.AccountType.STUDENT)
        cls.billing = User.objects.create_user(
            'billing', password='pw', account_type=User.AccountType.STUDENT)
        cls.other_hotel_staff = User.objects.create_user(
            'otherstaff', password='pw', account_type=User.AccountType.STUDENT)

        cls.session = SimulationSession.objects.create(
            name='Activity 1', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)
        cls.hotel = Hotel.objects.create(name='Bahay Ko', province='Pangasinan')
        cls.establishment = establishment_for_instance(cls.hotel, create=True,
                                                       defaults={'status': 'ACTIVE'})
        cls.other_establishment = Establishment.objects.create(
            name='Seaside Inn', type=Establishment.Type.HOTEL,
            address='La Union', contact_number='1', email='a@b.c')

        for student, role, establishment in (
                (cls.guest, 'GUEST_HOTEL', None),
                (cls.front_desk, 'HOTEL_RESERVATION_OFFICER', cls.establishment),
                (cls.housekeeper, 'HOUSEKEEPING_OFFICER', cls.establishment),
                (cls.billing, 'HOTEL_BILLING_OFFICER', cls.establishment),
                (cls.other_hotel_staff, 'FRONT_DESK', cls.other_establishment)):
            SimulationRoleAssignment.objects.create(
                student=student, assigned_by=cls.instructor, role=role,
                activity_name=cls.session.name, session=cls.session,
                establishment=establishment)

        cls.room = Room.objects.create(
            hotel=cls.hotel, room_number='101', room_type='DELUXE',
            rate=Decimal('4500.00'), max_guest_capacity=2,
            status=services.ROOM_AVAILABLE)
        cls.other_room = Room.objects.create(
            hotel=cls.hotel, room_number='102', room_type='DELUXE',
            rate=Decimal('4500.00'), max_guest_capacity=2,
            status=services.ROOM_AVAILABLE)

    def booking(self, rooms=None, total='9000.00'):
        return services.book_room(
            guest=self.guest, establishment=self.establishment,
            rooms=rooms if rooms is not None else [self.room],
            total_amount=total, check_in=timezone.now().date(),
            check_out=timezone.now().date() + timedelta(days=2))


class BookingTests(HotelWorkflowTestCase):

    def test_a_booking_is_routed_to_the_reservation_desk(self):
        booking, trx = self.booking()
        self.assertEqual(trx.stage, SimulationTransaction.Stage.INTAKE)
        self.assertEqual(trx.establishment, self.establishment)
        self.assertEqual(trx.subject, booking)
        self.assertEqual(booking.rooms.count(), 1)

    def test_the_guest_is_told_the_reservation_arrived(self):
        _, trx = self.booking()
        self.assertTrue(Notification.objects.filter(
            recipient=self.guest,
            notification_type=Notification.Type.HOTEL_RESERVATION_SUBMITTED).exists())

    def test_a_booking_needs_at_least_one_room(self):
        with self.assertRaises(services.HotelWorkflowError) as caught:
            services.book_room(guest=self.guest, establishment=self.establishment,
                                rooms=[], total_amount='9000.00',
                                check_in=STAY_IN, check_out=STAY_OUT)
        self.assertEqual(caught.exception.code, 'no_rooms')

    def test_an_occupied_room_cannot_be_booked(self):
        self.room.status = services.ROOM_OCCUPIED
        self.room.save()
        with self.assertRaises(services.HotelWorkflowError) as caught:
            self.booking()
        self.assertEqual(caught.exception.code, 'room_not_available')

    def test_a_room_under_maintenance_cannot_be_booked(self):
        self.room.status = 'MAINTENANCE'
        self.room.save()
        with self.assertRaises(services.HotelWorkflowError):
            self.booking()

    def test_a_travel_agency_cannot_take_hotel_bookings(self):
        agency = Establishment.objects.create(
            name='Wanderlust', type=Establishment.Type.TRAVEL_AGENCY,
            address='Manila', contact_number='1', email='a@b.c')
        with self.assertRaises(services.HotelWorkflowError) as caught:
            services.book_room(guest=self.guest, establishment=agency,
                               rooms=[self.room], total_amount='9000.00',
                               check_in=STAY_IN, check_out=STAY_OUT)
        self.assertEqual(caught.exception.code, 'wrong_establishment_type')


class ReservationDeskTests(HotelWorkflowTestCase):

    def test_the_desk_confirms_the_reservation(self):
        _, trx = self.booking()
        trx = services.confirm_reservation(trx, self.front_desk)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.FULFILLMENT)
        self.assertEqual(trx.status, SimulationTransaction.Status.CONFIRMED)
        self.assertEqual(trx.subject.status, Booking.Status.CONFIRMED)

    def test_the_guest_is_told_the_room_is_reserved(self):
        _, trx = self.booking()
        trx = services.confirm_reservation(trx, self.front_desk)
        self.assertTrue(Notification.objects.filter(
            recipient=self.guest,
            notification_type=Notification.Type.HOTEL_RESERVATION_APPROVED).exists())

    def test_the_reservation_is_described_as_simulated(self):
        _, trx = self.booking()
        services.confirm_reservation(trx, self.front_desk)
        message = Notification.objects.filter(
            recipient=self.guest,
            notification_type=Notification.Type.HOTEL_RESERVATION_APPROVED
        ).values_list('message', flat=True).first()
        self.assertIn('simulated reservation', message)

    def test_staff_from_another_hotel_cannot_confirm(self):
        _, trx = self.booking()
        with self.assertRaises(engine.TransactionError):
            services.confirm_reservation(trx, self.other_hotel_staff)

    def test_the_guest_cannot_confirm_their_own_booking(self):
        _, trx = self.booking()
        with self.assertRaises(engine.SelfApprovalError):
            services.confirm_reservation(trx, self.guest)

    def test_declining_marks_the_booking_declined(self):
        _, trx = self.booking()
        trx = services.decline_reservation(trx, self.front_desk, remarks='Fully booked.')
        self.assertEqual(trx.status, SimulationTransaction.Status.REJECTED)
        self.assertEqual(trx.subject.status, Booking.Status.DECLINED)


class StayTests(HotelWorkflowTestCase):

    def confirmed(self):
        _, trx = self.booking()
        return services.confirm_reservation(trx, self.front_desk)

    def test_checking_in_occupies_the_room(self):
        trx = self.confirmed()
        trx = services.check_in(trx, self.housekeeper)
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, services.ROOM_OCCUPIED)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.FULFILLMENT)
        self.assertEqual(trx.subject.status, Booking.Status.CHECKED_IN)

    def test_checking_out_frees_the_room_again(self):
        trx = self.confirmed()
        trx = services.check_in(trx, self.housekeeper)
        services.check_out(trx, self.housekeeper)
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, services.ROOM_AVAILABLE)
        self.assertEqual(trx.subject.status, Booking.Status.CHECKED_OUT)

    def test_a_freed_room_can_be_booked_by_someone_else(self):
        trx = self.confirmed()
        services.check_out(trx, self.housekeeper)
        other_guest = User.objects.create_user(
            'guest2', password='pw', account_type=User.AccountType.STUDENT)
        SimulationRoleAssignment.objects.create(
            student=other_guest, assigned_by=self.instructor, role='GUEST_HOTEL',
            activity_name=self.session.name, session=self.session)
        booking, second = services.book_room(
            guest=other_guest, establishment=self.establishment,
            rooms=[self.room], total_amount='4500.00',
            check_in=timezone.now().date(), check_out=timezone.now().date() + timedelta(days=1))
        self.assertEqual(second.subject.rooms.first(), self.room)

    def test_the_guest_cannot_check_themselves_in(self):
        trx = self.confirmed()
        with self.assertRaises(services.HotelWorkflowError) as caught:
            services.check_in(trx, self.guest)
        self.assertEqual(caught.exception.code, 'not_hotel_staff')
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, services.ROOM_AVAILABLE)


class HotelJourneyTests(HotelWorkflowTestCase):

    def test_stay_to_payment_closes_the_booking(self):
        _, trx = self.booking()
        trx = services.confirm_reservation(trx, self.front_desk)
        trx = services.check_in(trx, self.housekeeper)
        trx = services.check_out(trx, self.housekeeper)
        trx = services.send_to_billing(trx, self.housekeeper)

        bill = billing_services.issue_bill(trx, self.billing, total_amount=Decimal('9000.00'))
        _, bill = billing_services.record_payment(bill, self.billing, Decimal('9000.00'))

        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.COMPLETED)
        self.assertEqual(bill.status, SimulatedBill.Status.PAID)
        self.assertEqual(trx.subject.status, Booking.Status.COMPLETED)

    def test_cancelling_a_reservation_closes_the_booking(self):
        _, trx = self.booking()
        trx = services.cancel_reservation(trx, self.guest, remarks='Plans changed.')
        self.assertEqual(trx.status, SimulationTransaction.Status.CANCELLED)
        self.assertEqual(trx.subject.status, Booking.Status.CANCELLED)


class TurnoverRuleTests(TestCase):
    """The shared room-turnover rule (ROOM_TURNOVER_MINUTES) and stay-date chain."""

    @override_settings(ROOM_TURNOVER_MINUTES=60)
    def test_default_turnover_never_pushes_to_another_date(self):
        self.assertEqual(core_services.turnover_whole_days(), 0)
        check_out = date(2026, 10, 8)
        self.assertEqual(core_services.next_available_check_in(check_out), check_out)
        self.assertFalse(core_services.turnover_conflicts(date(2026, 10, 8), check_out))

    @override_settings(ROOM_TURNOVER_MINUTES=1800)
    def test_whole_day_turnover_pushes_the_next_available_date(self):
        self.assertEqual(core_services.turnover_whole_days(), 1)
        check_out = date(2026, 10, 8)
        self.assertEqual(core_services.next_available_check_in(check_out), date(2026, 10, 9))
        self.assertTrue(core_services.turnover_conflicts(date(2026, 10, 8), check_out))
        self.assertFalse(core_services.turnover_conflicts(date(2026, 10, 9), check_out))

    def test_stay_dates_reject_backwards_ranges(self):
        self.assertEqual(
            core_services.validate_stay_dates(date(2026, 10, 9), date(2026, 10, 8)),
            ['Check-out has to be after check-in.'])
        self.assertEqual(
            core_services.validate_stay_dates(None, date(2026, 10, 8))[0],
            'Check-in date is required.')
        self.assertEqual(
            core_services.validate_stay_dates(date(2026, 10, 8), date(2026, 10, 9)), [])


class TurnoverEnforcementTests(HotelWorkflowTestCase):
    """Whole-day turnover blocks a re-checkin on a prior checkout day."""

    def test_sub_day_turnover_keeps_the_checkout_day_bookable(self):
        self.booking()
        prev_out = timezone.now().date() + timedelta(days=2)
        self.assertFalse(_room_turnover_conflict(self.room, prev_out))

    @override_settings(ROOM_TURNOVER_MINUTES=1440)
    def test_whole_day_turnover_blocks_until_the_day_after_checkout(self):
        self.booking()
        prev_out = timezone.now().date() + timedelta(days=2)
        self.assertTrue(_room_turnover_conflict(self.room, prev_out))
        self.assertFalse(_room_turnover_conflict(self.room, prev_out + timedelta(days=1)))
