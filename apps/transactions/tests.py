from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from atrue_core.services import refund_payment

from transactions.models import Bill, Payment

User = get_user_model()


class RefundPaymentTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            'payer', password='pw', account_type=User.AccountType.STUDENT)
        self.bill = Bill.objects.create(
            service='flight', customer=self.user, total_amount=Decimal('1000.00'),
            amount_paid=Decimal('1000.00'), balance_due=Decimal('0.00'),
            status=Bill.Status.FULLY_PAID)
        self.payment = Payment.objects.create(
            bill=self.bill, customer=self.user, amount=Decimal('1000.00'),
            method='GCASH', status=Payment.Status.PAID, paid_at=timezone.now())

    def test_a_full_refund_reverses_the_payment_and_bill(self):
        refund_payment(payment=self.payment, user=self.user)

        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.payment.refunded_amount, Decimal('1000.00'))
        self.assertEqual(self.bill.amount_paid, Decimal('0.00'))
        self.assertEqual(self.bill.balance_due, Decimal('1000.00'))

    def test_a_partial_refund_keeps_the_remaining_payment_refundable(self):
        refund_payment(payment=self.payment, user=self.user, amount=Decimal('300.00'))

        self.payment.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PARTIALLY_REFUNDED)
        self.assertEqual(self.payment.refunded_amount, Decimal('300.00'))
        self.assertEqual(self.payment.remaining_refundable, Decimal('700.00'))
        self.assertEqual(self.bill.amount_paid, Decimal('700.00'))
        self.assertEqual(self.bill.balance_due, Decimal('300.00'))

    def test_a_pending_payment_cannot_be_refunded(self):
        self.payment.status = Payment.Status.PENDING
        self.payment.save(update_fields=['status'])

        with self.assertRaises(ValueError):
            refund_payment(payment=self.payment, user=self.user)
