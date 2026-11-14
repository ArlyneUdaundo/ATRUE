from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from airlines import services
from airlines.models import Airline, Booking, Flight, FlightItinerary
from establishments.models import establishment_for_instance
from simulation.models import SimulationRoleAssignment, SimulationSession
from transactions.models import Bill, Cancellation, Payment

User = get_user_model()


class CancellationRefundTests(TestCase):

    def setUp(self):
        self.passenger = User.objects.create_user(
            'refund-passenger', password='pw',
            account_type=User.AccountType.STUDENT)
        self.officer = User.objects.create_user(
            'refund-officer', password='pw',
            account_type=User.AccountType.STUDENT)
        self.airline = Airline.objects.create(name='Refund Air')
        departs = timezone.now() + timedelta(days=7)
        self.flight = Flight.objects.create(
            airline=self.airline, origin='Manila', destination='Cebu',
            departure_time=departs, arrival_time=departs + timedelta(hours=2))
        self.booking = Booking.objects.create(
            passenger=self.passenger, flight=self.flight,
            status=Booking.Status.CONFIRMED, total_bill=Decimal('1000.00'),
            amount_paid=Decimal('1000.00'), balance_due=Decimal('0.00'))
        self.bill = Bill.objects.create(
            service='flight', customer=self.passenger,
            total_amount=Decimal('1000.00'), amount_paid=Decimal('1000.00'),
            balance_due=Decimal('0.00'), status=Bill.Status.FULLY_PAID)
        self.bill.link_to_booking(self.booking)
        self.bill.save()
        self.payment = Payment.objects.create(
            bill=self.bill, customer=self.passenger, amount=Decimal('1000.00'),
            method='GCASH', status=Payment.Status.PAID, paid_at=timezone.now())

    def _cancellation(self):
        return Cancellation.objects.get(object_id=self.booking.pk)

    def test_request_requires_a_reason(self):
        with self.assertRaises(services.AirlineWorkflowError) as caught:
            services.request_cancellation_refund(
                self.booking, self.passenger, reason='   ')

        self.assertEqual(caught.exception.code, 'reason_required')
        self.assertFalse(
            Cancellation.objects.filter(object_id=self.booking.pk).exists())

    def test_request_does_not_cancel_or_refund_before_review(self):
        cancellation = services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')

        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(cancellation.status, Cancellation.Status.REQUESTED)
        self.assertEqual(cancellation.reason, 'Change of plans')
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.bill.amount_paid, Decimal('1000.00'))

    def test_a_second_request_is_prevented_while_pending(self):
        services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')

        with self.assertRaises(services.AirlineWorkflowError) as caught:
            services.request_cancellation_refund(
                self.booking, self.passenger, reason='Again')

        self.assertEqual(caught.exception.code, 'request_pending')
        self.assertEqual(
            Cancellation.objects.filter(object_id=self.booking.pk).count(), 1)

    def test_approval_refunds_the_full_fare_for_a_refundable_booking(self):
        cancellation = services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')

        result = services.process_cancellation_refund(
            cancellation, self.officer, approve=True, remarks='Approved.')

        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        cancellation.refresh_from_db()
        self.assertEqual(result['refunded'], Decimal('1000.00'))
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.bill.amount_paid, Decimal('0.00'))
        self.assertEqual(cancellation.status, Cancellation.Status.APPROVED)
        self.assertEqual(cancellation.refund_amount, Decimal('1000.00'))
        self.assertEqual(cancellation.processed_by, self.officer)

        self.client.force_login(self.passenger)
        page = self.client.get(
            reverse('airlines:booking_detail', args=[self.booking.pk]))
        self.assertContains(page, 'Cancellation Approved')

    def test_approval_retains_the_cancellation_fee(self):
        self.booking.itinerary = FlightItinerary.objects.create(
            airline=self.airline, is_refundable=True,
            cancellation_fee=Decimal('250.00'))
        self.booking.save(update_fields=['itinerary'])
        cancellation = services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')

        result = services.process_cancellation_refund(
            cancellation, self.officer, approve=True)

        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        cancellation.refresh_from_db()
        self.assertEqual(result['refunded'], Decimal('750.00'))
        self.assertEqual(self.payment.status, Payment.Status.PARTIALLY_REFUNDED)
        self.assertEqual(self.payment.refunded_amount, Decimal('750.00'))
        self.assertEqual(self.bill.amount_paid, Decimal('250.00'))
        self.assertEqual(cancellation.refund_amount, Decimal('750.00'))
        self.assertEqual(cancellation.cancellation_fee, Decimal('250.00'))

    def test_approval_of_a_non_refundable_fare_returns_nothing(self):
        self.booking.itinerary = FlightItinerary.objects.create(
            airline=self.airline, is_refundable=False,
            cancellation_fee=Decimal('0.00'))
        self.booking.save(update_fields=['itinerary'])
        cancellation = services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')

        result = services.process_cancellation_refund(
            cancellation, self.officer, approve=True)

        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(result['refunded'], Decimal('0.00'))
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.payment.refunded_amount, Decimal('0.00'))

    def test_rejection_keeps_the_booking_and_payment_untouched(self):
        cancellation = services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')

        result = services.process_cancellation_refund(
            cancellation, self.officer, approve=False,
            remarks='Outside the refund window.')

        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        cancellation.refresh_from_db()
        self.assertFalse(result['approved'])
        self.assertEqual(result['refunded'], Decimal('0.00'))
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(cancellation.status, Cancellation.Status.REJECTED)
        self.assertEqual(cancellation.review_remarks, 'Outside the refund window.')
        self.assertEqual(cancellation.processed_by, self.officer)

    def test_a_reviewed_request_cannot_be_processed_twice(self):
        cancellation = services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')
        services.process_cancellation_refund(
            cancellation, self.officer, approve=False)

        with self.assertRaises(services.AirlineWorkflowError) as caught:
            services.process_cancellation_refund(
                cancellation, self.officer, approve=True)

        self.assertEqual(caught.exception.code, 'request_reviewed')

    def test_billing_officer_approves_from_the_payment_review_page(self):
        instructor = User.objects.create_user(
            'airline-instructor', password='pw',
            account_type=User.AccountType.INSTRUCTOR)
        session = SimulationSession.objects.create(
            name='Airline Simulation', instructor=instructor,
            status=SimulationSession.Status.ACTIVE,
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=1))
        establishment = establishment_for_instance(self.airline, create=True)
        assignment = SimulationRoleAssignment.objects.create(
            student=self.officer, assigned_by=instructor,
            role='AIRLINE_BILLING_OFFICER', session=session,
            establishment=establishment)
        cancellation = services.request_cancellation_refund(
            self.booking, self.passenger, reason='Change of plans')

        self.client.force_login(self.officer)
        client_session = self.client.session
        client_session['active_simulation_task_assignment'] = assignment.pk
        client_session.save()

        page = self.client.get(reverse('transactions:payment_review'))
        self.assertContains(page, 'Refund request')

        response = self.client.post(
            reverse('transactions:payment_review'),
            {'cancellation_id': cancellation.pk, 'action': 'approve_refund',
             'review_remarks': 'Approved.'})

        self.assertRedirects(response, reverse('transactions:payment_review'))
        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        cancellation.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(cancellation.status, Cancellation.Status.APPROVED)
        self.assertEqual(cancellation.processed_by, self.officer)

    def test_a_passenger_can_submit_a_request_from_the_booking_page(self):
        self.client.force_login(self.passenger)

        response = self.client.post(
            reverse('airlines:booking_detail', args=[self.booking.pk]),
            {'action': 'cancel', 'manager_remarks': 'Change of plans'})

        self.assertRedirects(
            response, reverse('airlines:booking_detail', args=[self.booking.pk]))
        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        cancellation = self._cancellation()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(cancellation.status, Cancellation.Status.REQUESTED)
        self.assertEqual(cancellation.reason, 'Change of plans')

        page = self.client.get(
            reverse('airlines:booking_detail', args=[self.booking.pk]))
        self.assertContains(page, 'Cancellation Request Pending Review')
