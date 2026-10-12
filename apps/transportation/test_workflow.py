"""Transportation workflow tests (Section 12).

The rules under test: a trip needs a driver, one driver cannot be on two trips at
once, dispatch is a step the customer is told about separately from approval, and
only the transport company's own staff may act.
"""

from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from billing import services as billing_services
from billing.models import SimulatedBill
from establishments.models import Establishment, establishment_for_instance
from notifications.models import Notification
from simulation.models import SimulationRoleAssignment, SimulationSession, SimulationTransaction
from simulation.role_catalogue import sync_role_catalogue
from transportation import services
from transportation.models import Agency, Booking, Driver, Vehicle

User = get_user_model()

SCHEDULE = timezone.now() + timedelta(days=5)


class TransportWorkflowTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.customer = User.objects.create_user(
            'customer', password='pw', account_type=User.AccountType.STUDENT)
        cls.officer = User.objects.create_user(
            'officer', password='pw', account_type=User.AccountType.STUDENT)
        cls.dispatcher = User.objects.create_user(
            'dispatcher', password='pw', account_type=User.AccountType.STUDENT)
        cls.billing = User.objects.create_user(
            'billing', password='pw', account_type=User.AccountType.STUDENT)
        cls.rival = User.objects.create_user(
            'rival', password='pw', account_type=User.AccountType.STUDENT)

        cls.session = SimulationSession.objects.create(
            name='Activity 1', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)

        cls.agency = Agency.objects.create(name='Pangasinan Transport')
        cls.establishment = establishment_for_instance(
            cls.agency, create=True, defaults={'status': 'ACTIVE'})
        cls.other_agency = Agency.objects.create(name='Rival Transport')
        cls.other_establishment = establishment_for_instance(
            cls.other_agency, create=True, defaults={'status': 'ACTIVE'})

        for student, role, establishment in (
                (cls.customer, 'CUSTOMER_TOUR', None),
                (cls.officer, 'TRANSPORT_RESERVATION_OFFICER', cls.establishment),
                (cls.dispatcher, 'TRANSPORT_DISPATCHER', cls.establishment),
                (cls.billing, 'TRANSPORT_BILLING_OFFICER', cls.establishment),
                (cls.rival, 'TRANSPORT_RESERVATION_OFFICER', cls.other_establishment)):
            SimulationRoleAssignment.objects.create(
                student=student, assigned_by=cls.instructor, role=role,
                activity_name=cls.session.name, session=cls.session,
                establishment=establishment)

        cls.vehicle = Vehicle.objects.create(
            agency=cls.agency, plate_number='ABC-123', capacity=12)
        cls.driver = Driver.objects.create(
            agency=cls.agency, full_name='Rosa Mendoza', license_number='L-1')

    def booking(self, driver=None, total='4500.00'):
        return services.book_vehicle(
            customer=self.customer, establishment=self.establishment,
            vehicle=self.vehicle, total_amount=total,
            pickup_location='Dagupan', drop_off_location='Baguio',
            schedule=SCHEDULE, distance_km='120', duration_hours=3,
            passengers=2, driver=driver)


class TransportBookingTests(TransportWorkflowTestCase):

    def test_a_request_is_routed_to_the_reservation_officer(self):
        booking, trx = self.booking()
        self.assertEqual(trx.stage, SimulationTransaction.Stage.INTAKE)
        self.assertEqual(trx.subject, booking)
        self.assertEqual(trx.establishment, self.establishment)

    def test_a_hotel_cannot_provide_transport(self):
        hotel = Establishment.objects.create(
            name='Bahay Ko', type=Establishment.Type.HOTEL,
            address='Pangasinan', contact_number='1', email='a@b.c')
        with self.assertRaises(services.TransportWorkflowError) as caught:
            services.book_vehicle(customer=self.customer, establishment=hotel,
                                  vehicle=self.vehicle, total_amount='4500.00',
                                  pickup_location='Dagupan',
                                  drop_off_location='Baguio', schedule=SCHEDULE)
        self.assertEqual(caught.exception.code, 'wrong_establishment_type')

    def test_the_officer_confirms_the_request(self):
        _, trx = self.booking()
        trx = services.confirm_request(trx, self.officer)
        self.assertEqual(trx.status, SimulationTransaction.Status.CONFIRMED)

    def test_staff_from_another_company_cannot_confirm(self):
        _, trx = self.booking()
        with self.assertRaises(Exception):
            services.confirm_request(trx, self.rival)

    def test_the_customer_cannot_confirm_their_own_request(self):
        _, trx = self.booking()
        with self.assertRaises(Exception):
            services.confirm_request(trx, self.customer)

    def test_a_rejected_request_tells_the_customer(self):
        _, trx = self.booking()
        trx = services.decline_request(trx, self.officer, remarks='No vehicle free.')
        self.assertEqual(trx.status, SimulationTransaction.Status.REJECTED)
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TRANSPORT_REQUEST_REJECTED).exists())


class DispatchTests(TransportWorkflowTestCase):

    def confirmed(self, driver=None):
        _, trx = self.booking(driver=driver)
        return services.confirm_request(trx, self.officer)

    def test_dispatch_needs_a_driver(self):
        trx = self.confirmed()
        with self.assertRaises(services.TransportWorkflowError) as caught:
            services.dispatch(trx, self.dispatcher)
        self.assertEqual(caught.exception.code, 'no_driver')

    def test_dispatching_sends_the_driver_and_tells_the_customer(self):
        trx = self.confirmed()
        trx = services.dispatch(trx, self.dispatcher, driver=self.driver)
        trx.subject.refresh_from_db()
        self.assertEqual(trx.subject.driver, self.driver)
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TRANSPORT_DISPATCHED).exists())

    def test_a_driver_already_on_a_trip_cannot_be_booked_again(self):
        trx = self.confirmed()
        services.dispatch(trx, self.dispatcher, driver=self.driver)
        with self.assertRaises(services.TransportWorkflowError) as caught:
            self.booking(driver=self.driver)
        self.assertEqual(caught.exception.code, 'driver_unavailable')

    def test_a_finished_trip_frees_the_driver(self):
        trx = self.confirmed()
        trx = services.dispatch(trx, self.dispatcher, driver=self.driver)
        services.complete_trip(trx, self.dispatcher)
        self.assertFalse(services.driver_is_busy(self.driver))

    def test_a_dispatcher_cannot_dispatch_without_an_assignment(self):
        trx = self.confirmed()
        with self.assertRaises(Exception):
            services.dispatch(trx, self.rival, driver=self.driver)


class TransportJourneyTests(TransportWorkflowTestCase):

    def test_request_to_payment_closes_the_booking(self):
        _, trx = self.booking()
        trx = services.confirm_request(trx, self.officer)
        trx = services.dispatch(trx, self.dispatcher, driver=self.driver)
        trx = services.send_to_billing(trx, self.dispatcher)

        bill = billing_services.issue_bill(trx, self.billing,
                                           total_amount=Decimal('4500.00'))
        _, bill = billing_services.record_payment(bill, self.billing,
                                                 Decimal('4500.00'))

        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.COMPLETED)
        self.assertEqual(bill.status, SimulatedBill.Status.PAID)
        self.assertEqual(trx.subject.status, Booking.Status.COMPLETED)