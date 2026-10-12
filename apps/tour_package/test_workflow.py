"""Tour operator workflow tests (Section 11).

The rules under test: a package that is not on sale cannot be booked, a guide has
to be assigned before the tour runs, attendance is recorded as an event rather
than a status jump, and only the operator's own staff may act.
"""

from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from billing import services as billing_services
from billing.models import SimulatedBill
from establishments.models import Establishment
from establishments.models import establishment_for_instance
from notifications.models import Notification
from simulation.models import SimulationRoleAssignment, SimulationSession, SimulationTransaction
from simulation.role_catalogue import sync_role_catalogue
from tour_package import services
from tour_package.models import Booking, TourPackage

User = get_user_model()

TRAVEL_DATE = timezone.now().date() + timedelta(days=10)


class TourWorkflowTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.customer = User.objects.create_user(
            'customer', password='pw', account_type=User.AccountType.STUDENT)
        cls.coordinator = User.objects.create_user(
            'coordinator', password='pw', account_type=User.AccountType.STUDENT)
        cls.guide = User.objects.create_user(
            'guide', password='pw', account_type=User.AccountType.STUDENT)
        cls.billing = User.objects.create_user(
            'billing', password='pw', account_type=User.AccountType.STUDENT)
        cls.rival = User.objects.create_user(
            'rival', password='pw', account_type=User.AccountType.STUDENT)

        cls.session = SimulationSession.objects.create(
            name='Activity 1', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)

        # Tour operators have no catalogue record of their own to wrap, so these
        # establishments are created directly rather than linked to a legacy model.
        cls.establishment = Establishment.objects.create(
            name='Adventure Trail Co', type=Establishment.Type.TOUR_OPERATOR,
            address='Baguio', contact_number='1', email='trails@example.test')
        cls.other_establishment = Establishment.objects.create(
            name='Other Trails', type=Establishment.Type.TOUR_OPERATOR,
            address='La Union', contact_number='1', email='other@example.test')

        for student, role, establishment in (
                (cls.coordinator, 'TOUR_COORDINATOR', cls.establishment),
                (cls.guide, 'TOUR_GUIDE', cls.establishment),
                (cls.billing, 'TOUR_BILLING_OFFICER', cls.establishment),
                (cls.rival, 'TOUR_COORDINATOR', cls.other_establishment)):
            SimulationRoleAssignment.objects.create(
                student=student, assigned_by=cls.instructor, role=role,
                activity_name=cls.session.name, session=cls.session,
                establishment=establishment)

        cls.package = TourPackage.objects.create(
            name='Baguio Day Trip', price=Decimal('6500.00'),
            included_headcount=4, status=TourPackage.Status.ACTIVE)
        package_establishment = establishment_for_instance(cls.package)
        SimulationRoleAssignment.objects.create(
            student=cls.customer, assigned_by=cls.instructor,
            role='TOUR_GUEST', activity_name=cls.session.name,
            session=cls.session, establishment=package_establishment)
        cls.sold_out = TourPackage.objects.create(
            name='Sampaguita Tour', price=Decimal('9000.00'),
            included_headcount=4, status=TourPackage.Status.FULLY_BOOKED)

    def booking(self, package=None, travellers=2, total='13000.00'):
        return services.book_package(
            customer=self.customer, establishment=self.establishment,
            package=package or self.package, total_amount=total,
            travel_date=TRAVEL_DATE, number_of_travelers=travellers,
            number_of_adults=travellers, number_of_children=0)


class TourBookingTests(TourWorkflowTestCase):

    def test_a_booking_is_routed_to_the_coordinator(self):
        booking, trx = self.booking()
        self.assertEqual(trx.stage, SimulationTransaction.Stage.INTAKE)
        self.assertEqual(trx.subject, booking)
        self.assertEqual(trx.party_size, 2)

    def test_a_fully_booked_package_cannot_be_sold(self):
        with self.assertRaises(services.TourWorkflowError) as caught:
            self.booking(package=self.sold_out)
        self.assertEqual(caught.exception.code, 'package_not_available')

    def test_more_travellers_than_the_package_includes_is_refused(self):
        with self.assertRaises(services.TourWorkflowError) as caught:
            self.booking(travellers=9)
        self.assertEqual(caught.exception.code, 'over_capacity')

    def test_an_airline_cannot_sell_tours(self):
        airline = Establishment.objects.create(
            name='SkyWest', type=Establishment.Type.AIRLINE,
            address='Manila', contact_number='1', email='a@b.c')
        with self.assertRaises(services.TourWorkflowError) as caught:
            services.book_package(customer=self.customer, establishment=airline,
                                  package=self.package, total_amount='6500.00',
                                  travel_date=TRAVEL_DATE)
        self.assertEqual(caught.exception.code, 'wrong_establishment_type')

    def test_the_customer_is_told_the_request_arrived(self):
        self.booking()
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TOUR_REQUEST_SUBMITTED).exists())

    def test_the_coordinator_confirms_the_booking(self):
        _, trx = self.booking()
        trx = services.confirm_booking(trx, self.coordinator)
        self.assertEqual(trx.status, SimulationTransaction.Status.CONFIRMED)

    def test_the_booking_is_described_as_simulated(self):
        _, trx = self.booking()
        services.confirm_booking(trx, self.coordinator)
        message = Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TOUR_REQUEST_APPROVED
        ).values_list('message', flat=True).first()
        self.assertIn('simulated tour booking', message)

    def test_staff_from_another_operator_cannot_confirm(self):
        _, trx = self.booking()
        with self.assertRaises(Exception):
            services.confirm_booking(trx, self.rival)

    def test_the_customer_cannot_confirm_their_own_booking(self):
        _, trx = self.booking()
        with self.assertRaises(Exception):
            services.confirm_booking(trx, self.customer)

    def test_a_rejected_booking_tells_the_customer(self):
        _, trx = self.booking()
        trx = services.decline_booking(trx, self.coordinator, remarks='Fully booked.')
        self.assertEqual(trx.status, SimulationTransaction.Status.REJECTED)
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TOUR_REQUEST_REJECTED).exists())


class TourDeliveryTests(TourWorkflowTestCase):

    def confirmed(self):
        _, trx = self.booking()
        return services.confirm_booking(trx, self.coordinator)

    def test_a_guide_is_assigned_before_the_tour_runs(self):
        trx = self.confirmed()
        trx = services.assign_guide(trx, self.guide)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.FULFILLMENT)
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TOUR_REQUEST_APPROVED).exists())

    def test_the_coordinator_cannot_act_as_the_guide(self):
        trx = self.confirmed()
        with self.assertRaises(Exception):
            services.record_attendance(trx, self.coordinator, participants=['Ana'])

    def test_attendance_is_recorded_and_the_customer_is_told(self):
        trx = self.confirmed()
        trx = services.assign_guide(trx, self.guide)
        trx = services.record_attendance(trx, self.guide,
                                         participants=['Ana', 'Ben'])
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TOUR_COMPLETED).exists())


class TourJourneyTests(TourWorkflowTestCase):

    def test_booking_to_payment_closes_the_booking(self):
        _, trx = self.booking()
        trx = services.confirm_booking(trx, self.coordinator)
        trx = services.assign_guide(trx, self.guide)
        trx = services.record_attendance(trx, self.guide, participants=['Ana'])
        trx = services.send_to_billing(trx, self.guide)

        bill = billing_services.issue_bill(trx, self.billing,
                                           total_amount=Decimal('13000.00'))
        _, bill = billing_services.record_payment(bill, self.billing,
                                                 Decimal('13000.00'))

        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.COMPLETED)
        self.assertEqual(bill.status, SimulatedBill.Status.PAID)
        self.assertEqual(trx.subject.status, Booking.Status.COMPLETED)
