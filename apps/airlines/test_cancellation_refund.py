from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from airlines import services
from airlines.models import Airline, Booking, Flight, FlightItinerary
from transactions.models import Bill, Payment

User = get_user_model()


class CancellationRefundTests(TestCase):

    def setUp(self):
        self.passenger = User.objects.create_user(
            'refund-passenger', password='pw',
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

    def test_cancelling_a_paid_booking_refunds_the_whole_fare(self):
        result = services.cancel_and_refund_booking(self.booking, self.passenger)

        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(result['refunded'], Decimal('1000.00'))
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.bill.amount_paid, Decimal('0.00'))

    def test_the_cancellation_fee_is_retained(self):
        self.booking.itinerary = FlightItinerary.objects.create(
            airline=self.airline, is_refundable=True,
            cancellation_fee=Decimal('250.00'))

        result = services.cancel_and_refund_booking(self.booking, self.passenger)

        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(result['refunded'], Decimal('750.00'))
        self.assertEqual(self.payment.status, Payment.Status.PARTIALLY_REFUNDED)
        self.assertEqual(self.payment.refunded_amount, Decimal('750.00'))
        self.assertEqual(self.bill.amount_paid, Decimal('250.00'))

    def test_a_passenger_can_cancel_from_the_booking_page(self):
        self.client.force_login(self.passenger)

        response = self.client.post(
            reverse('airlines:booking_detail', args=[self.booking.pk]),
            {'action': 'cancel', 'manager_remarks': 'Change of plans'})

        self.assertRedirects(
            response, reverse('airlines:booking_detail', args=[self.booking.pk]))
        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)

    def test_a_non_refundable_fare_is_cancelled_without_a_refund(self):
        self.booking.itinerary = FlightItinerary.objects.create(
            airline=self.airline, is_refundable=False,
            cancellation_fee=Decimal('0.00'))

        result = services.cancel_and_refund_booking(self.booking, self.passenger)

        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(result['refunded'], Decimal('0.00'))
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.payment.refunded_amount, Decimal('0.00'))
