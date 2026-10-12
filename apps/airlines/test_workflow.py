"""Airline workflow tests (Section 9).

The rules under test: a seat can only be held once, ticketing is a step separate
from approval, only the airline's own staff may act, and a ticket issued here is
never presented as a real travel document.
"""

from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from airlines import services
from airlines.models import Airline, Booking, Flight
from billing import services as billing_services
from billing.models import SimulatedBill
from establishments.models import Establishment, establishment_for_instance
from notifications.models import Notification
from simulation.models import SimulationRoleAssignment, SimulationSession, SimulationTransaction
from simulation.role_catalogue import sync_role_catalogue

User = get_user_model()


class AirlineWorkflowTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.passenger = User.objects.create_user(
            'passenger', password='pw', account_type=User.AccountType.STUDENT)
        cls.agent = User.objects.create_user(
            'agent', password='pw', account_type=User.AccountType.STUDENT)
        cls.ticketing = User.objects.create_user(
            'ticketing', password='pw', account_type=User.AccountType.STUDENT)
        cls.billing = User.objects.create_user(
            'billing', password='pw', account_type=User.AccountType.STUDENT)
        cls.rival = User.objects.create_user(
            'rival', password='pw', account_type=User.AccountType.STUDENT)

        cls.session = SimulationSession.objects.create(
            name='Activity 1', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)

        cls.carrier = Airline.objects.create(name='SkyWest')
        cls.establishment = establishment_for_instance(
            cls.carrier, create=True, defaults={'status': 'ACTIVE'})
        cls.other_airline = Airline.objects.create(name='Island Air')
        cls.other_establishment = establishment_for_instance(
            cls.other_airline, create=True, defaults={'status': 'ACTIVE'})

        for student, role, establishment in (
                (cls.passenger, 'PASSENGER_AIRLINE', None),
                (cls.agent, 'AIRLINE_RESERVATION_AGENT', cls.establishment),
                (cls.ticketing, 'AIRLINE_TICKETING_OFFICER', cls.establishment),
                (cls.billing, 'AIRLINE_BILLING_OFFICER', cls.establishment),
                (cls.rival, 'AIRLINE_RESERVATION_AGENT', cls.other_establishment)):
            SimulationRoleAssignment.objects.create(
                student=student, assigned_by=cls.instructor, role=role,
                activity_name=cls.session.name, session=cls.session,
                establishment=establishment)

        departs = timezone.now() + timedelta(days=7)
        cls.flight = Flight.objects.create(
            airline=cls.carrier, origin='Manila', destination='Baguio',
            departure_time=departs, arrival_time=departs + timedelta(hours=2))

    def booking(self, passenger=None, seats=('12A',), total='8500.00'):
        return services.book_flight(
            passenger=passenger or self.passenger, establishment=self.establishment,
            flight=self.flight, total_amount=total, trip_type='ONE_WAY', seats=seats)


class ReservationTests(AirlineWorkflowTestCase):

    def test_a_reservation_is_routed_to_the_agent(self):
        booking, trx = self.booking()
        self.assertEqual(trx.stage, SimulationTransaction.Stage.INTAKE)
        self.assertEqual(trx.subject, booking)
        self.assertEqual(trx.establishment, self.establishment)

    def test_the_seat_is_recorded_on_the_booking(self):
        booking, _ = self.booking()
        self.assertEqual(
            list(booking.seats_for_flight(self.flight)), ['12A'])

    def test_a_taken_seat_cannot_be_booked_twice(self):
        self.booking()
        with self.assertRaises(services.AirlineWorkflowError) as caught:
            self.booking()
        self.assertEqual(caught.exception.code, 'seat_taken')

    def test_a_cancelled_booking_gives_its_seat_back(self):
        booking, trx = self.booking()
        services.cancel_reservation(trx, self.passenger, remarks='Change of plans.')
        # The seat is free again, so the same seat can be booked by someone else
        # (a second booking by the same passenger would be blocked: their guest
        # activity completed on the first booking).
        second, _ = self.booking(passenger=self.rival)
        self.assertEqual(
            list(second.seats_for_flight(self.flight)), ['12A'])

    def test_a_hotel_cannot_sell_flights(self):
        hotel = Establishment.objects.create(
            name='Bahay Ko', type=Establishment.Type.HOTEL,
            address='Pangasinan', contact_number='1', email='a@b.c')
        with self.assertRaises(services.AirlineWorkflowError) as caught:
            services.book_flight(passenger=self.passenger, establishment=hotel,
                                 flight=self.flight, total_amount='8500.00')
        self.assertEqual(caught.exception.code, 'wrong_establishment_type')

    def test_the_agent_verifies_the_reservation(self):
        _, trx = self.booking()
        trx = services.verify_reservation(trx, self.agent)
        self.assertEqual(trx.status, SimulationTransaction.Status.CONFIRMED)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.FULFILLMENT)

    def test_staff_from_another_airline_cannot_verify(self):
        _, trx = self.booking()
        with self.assertRaises(Exception):
            services.verify_reservation(trx, self.rival)

    def test_the_passenger_cannot_verify_their_own_reservation(self):
        _, trx = self.booking()
        with self.assertRaises(Exception):
            services.verify_reservation(trx, self.passenger)

    def test_a_rejected_reservation_tells_the_passenger(self):
        _, trx = self.booking()
        trx = services.decline_reservation(trx, self.agent, remarks='Flight is full.')
        self.assertEqual(trx.status, SimulationTransaction.Status.REJECTED)
        self.assertTrue(Notification.objects.filter(
            recipient=self.passenger,
            notification_type=Notification.Type.FLIGHT_RESERVATION_REJECTED).exists())


class TicketingTests(AirlineWorkflowTestCase):

    def verified(self):
        _, trx = self.booking()
        return services.verify_reservation(trx, self.agent)

    def test_a_ticket_is_issued_after_approval_not_before(self):
        trx = self.verified()
        trx = services.issue_ticket(trx, self.ticketing)
        # Issuing a ticket happens *during* fulfilment, not instead of it: the
        # request still has to be flown and then billed.
        self.assertEqual(trx.stage, SimulationTransaction.Stage.FULFILLMENT)
        self.assertEqual(trx.subject.status, Booking.Status.CONFIRMED)

    def test_the_ticket_is_told_to_be_a_classroom_artefact(self):
        trx = self.verified()
        services.issue_ticket(trx, self.ticketing)
        message = Notification.objects.filter(
            recipient=self.passenger,
            notification_type=Notification.Type.FLIGHT_TICKET_ISSUED
        ).values_list('message', flat=True).first()
        self.assertIn('not a valid travel document', message)

    def test_the_agent_cannot_issue_a_ticket(self):
        trx = self.verified()
        with self.assertRaises(Exception):
            services.issue_ticket(trx, self.agent)


class AirlineJourneyTests(AirlineWorkflowTestCase):

    def test_reservation_to_payment_closes_the_booking(self):
        _, trx = self.booking()
        trx = services.verify_reservation(trx, self.agent)
        trx = services.issue_ticket(trx, self.ticketing)
        trx = services.complete_flight(trx, self.ticketing)
        trx = services.send_to_billing(trx, self.ticketing)

        bill = billing_services.issue_bill(trx, self.billing, total_amount=Decimal('8500.00'))
        _, bill = billing_services.record_payment(bill, self.billing, Decimal('8500.00'))

        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.COMPLETED)
        self.assertEqual(bill.status, SimulatedBill.Status.PAID)
        self.assertEqual(trx.subject.status, Booking.Status.COMPLETED)

    def test_a_flight_that_was_flown_is_marked_used(self):
        _, trx = self.booking()
        trx = services.verify_reservation(trx, self.agent)
        trx = services.issue_ticket(trx, self.ticketing)
        trx = services.complete_flight(trx, self.ticketing)
        trx.subject.refresh_from_db()
        self.assertEqual(trx.subject.status, Booking.Status.USED)

    def test_the_ticket_is_never_a_valid_travel_document(self):
        _, trx = self.booking()
        trx = services.verify_reservation(trx, self.agent)
        services.issue_ticket(trx, self.ticketing)
        messages = ' '.join(Notification.objects.filter(
            recipient=self.passenger).values_list('message', flat=True))
        self.assertIn('not a valid travel document', messages)
