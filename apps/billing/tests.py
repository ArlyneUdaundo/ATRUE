"""Rules the simulated billing service must never break (Section 15).

The platform records what a student *would* have charged; it never takes money
and never claims a real booking exists. These tests defend that, plus the two
rules that keep bills and requests honest: one bill per request, one settlement
per bill, and a settled bill finishing its request.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from audit_logs.models import AuditLog
from billing import services
from billing.models import BillingEvent, SimulatedBill, SimulatedPayment
from establishments.models import Establishment
from notifications.models import Notification
from simulation import engine
from simulation.models import (
    SimulationRoleAssignment,
    SimulationSession,
    SimulationTransaction,
)
from simulation.role_catalogue import sync_role_catalogue
from travel_agencies.models import TravelAgencyRequest

User = get_user_model()


class BillingTestCase(TestCase):
    """A request that has been approved and is waiting for simulated billing."""

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()

        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.customer = User.objects.create_user(
            'customer', password='pw', account_type=User.AccountType.STUDENT)
        cls.consultant = User.objects.create_user(
            'consultant', password='pw', account_type=User.AccountType.STUDENT)
        cls.billing = User.objects.create_user(
            'billing', password='pw', account_type=User.AccountType.STUDENT)

        cls.session = SimulationSession.objects.create(
            name='Activity 1', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)
        cls.agency = Establishment.objects.create(
            name='Wanderlust Travel', type=Establishment.Type.TRAVEL_AGENCY)

        cls.assign(cls.customer, 'CUSTOMER_TOUR')
        cls.assign(cls.consultant, 'TRAVEL_CONSULTANT', cls.agency)
        cls.assign(cls.billing, 'TRAVEL_AGENCY_BILLING_OFFICER', cls.agency)

    @classmethod
    def assign(cls, student, role_code, establishment=None):
        return SimulationRoleAssignment.objects.create(
            student=student, assigned_by=cls.instructor, role=role_code,
            activity_name=cls.session.name, session=cls.session,
            establishment=establishment)

    def awaiting_billing(self, total=Decimal('12000.00')):
        """A transaction the consultant has approved straight into billing."""
        request = TravelAgencyRequest.objects.create(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', party_size=2, budget=total)
        trx = engine.submit_transaction(
            subject=request,
            transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
            initiator=self.customer, session=self.session,
            establishment=self.agency, total_amount=total)
        engine.claim_transaction(trx, self.consultant)
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        return trx


class IssueBillTests(BillingTestCase):

    def test_a_bill_is_raised_for_the_approved_request(self):
        trx = self.awaiting_billing()
        bill = services.issue_bill(trx, self.billing)
        self.assertEqual(bill.customer, self.customer)
        self.assertEqual(bill.establishment, self.agency)
        self.assertEqual(bill.status, SimulatedBill.Status.UNPAID)
        self.assertEqual(bill.total_amount, Decimal('12000.00'))

    def test_one_request_cannot_be_billed_twice(self):
        trx = self.awaiting_billing()
        first = services.issue_bill(trx, self.billing)
        second = services.issue_bill(trx, self.billing)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SimulatedBill.objects.count(), 1)

    def test_a_request_still_awaiting_approval_cannot_be_billed(self):
        request = TravelAgencyRequest.objects.create(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', party_size=2)
        trx = engine.submit_transaction(
            subject=request,
            transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
            initiator=self.customer, session=self.session,
            establishment=self.agency)
        with self.assertRaises(services.BillingError) as caught:
            services.issue_bill(trx, self.billing)
        self.assertEqual(caught.exception.code, 'not_at_billing_stage')

    def test_line_items_are_totalled(self):
        trx = self.awaiting_billing(total=0)
        bill = services.issue_bill(trx, self.billing, items=[
            {'description': 'Hotel', 'amount': '8000.00'},
            {'description': 'Transport', 'amount': '2500.00'},
        ])
        self.assertEqual(bill.total_amount, Decimal('10500.00'))
        self.assertEqual(bill.balance_due, Decimal('10500.00'))

    def test_issuing_notifies_the_customer_and_writes_an_audit_row(self):
        trx = self.awaiting_billing()
        services.issue_bill(trx, self.billing)
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.BILLING_READY).exists())
        self.assertTrue(AuditLog.objects.filter(action='billing.issue').exists())


class PaymentTests(BillingTestCase):

    def billed(self, total=Decimal('12000.00')):
        trx = self.awaiting_billing(total=total)
        return trx, services.issue_bill(trx, self.billing, total_amount=total)

    def test_a_full_payment_settles_the_bill(self):
        trx, bill = self.billed()
        payment, bill = services.record_payment(bill, self.billing, Decimal('12000.00'))
        self.assertEqual(bill.status, SimulatedBill.Status.PAID)
        self.assertEqual(bill.balance_due, Decimal('0.00'))
        self.assertIsNotNone(bill.settled_at)
        self.assertEqual(payment.status, SimulatedPayment.Status.PAID)
        self.assertIsNotNone(payment.recorded_at)

    def test_a_settled_bill_finishes_the_simulation_request(self):
        trx, bill = self.billed()
        services.record_payment(bill, self.billing, Decimal('12000.00'))
        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.COMPLETED)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.DONE)

    def test_a_partial_payment_leaves_the_balance_due(self):
        trx, bill = self.billed()
        _, bill = services.record_payment(bill, self.billing, Decimal('5000.00'))
        self.assertEqual(bill.balance_due, Decimal('7000.00'))
        self.assertEqual(bill.status, SimulatedBill.Status.PENDING_VERIFICATION)
        trx.refresh_from_db()
        self.assertNotEqual(trx.status, SimulationTransaction.Status.COMPLETED)

    def test_two_partial_payments_settle_the_bill(self):
        trx, bill = self.billed()
        _, bill = services.record_payment(bill, self.billing, Decimal('5000.00'))
        _, bill = services.record_payment(bill, self.billing, Decimal('7000.00'))
        self.assertEqual(bill.status, SimulatedBill.Status.PAID)
        self.assertEqual(bill.amount_paid, Decimal('12000.00'))

    def test_a_settled_bill_refuses_a_second_payment(self):
        trx, bill = self.billed()
        services.record_payment(bill, self.billing, Decimal('12000.00'))
        with self.assertRaises(services.DuplicatePaymentError):
            services.record_payment(bill, self.billing, Decimal('12000.00'))

    def test_overpaying_is_refused(self):
        trx, bill = self.billed()
        with self.assertRaises(services.BillingError) as caught:
            services.record_payment(bill, self.billing, Decimal('13000.00'))
        self.assertEqual(caught.exception.code, 'amount_exceeds_balance')

    def test_a_non_positive_amount_is_refused(self):
        trx, bill = self.billed()
        for amount in ('0', '-500', 'not money'):
            with self.assertRaises(services.InvalidAmountError):
                services.record_payment(bill, self.billing, Decimal(amount) if amount != 'not money' else amount)

    def test_every_payment_is_recorded_in_the_billing_history(self):
        trx, bill = self.billed()
        services.record_payment(bill, self.billing, Decimal('12000.00'))
        history = list(BillingEvent.objects.filter(bill=bill)
                       .values_list('action', 'to_status'))
        self.assertEqual(history, [('issue', 'UNPAID'), ('payment', 'PAID')])

    def test_billing_history_rows_cannot_be_deleted(self):
        trx, bill = self.billed()
        event = BillingEvent.objects.filter(bill=bill).first()
        with self.assertRaises(ValueError):
            event.delete()

    def test_a_payment_is_described_as_simulated(self):
        trx, bill = self.billed()
        services.record_payment(bill, self.billing, Decimal('12000.00'))
        message = Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.PAYMENT_RECORDED
        ).values_list('message', flat=True).first()
        self.assertIn('Simulated classroom payment', message)
        self.assertIn('no real funds', message)


class BillClosureTests(BillingTestCase):

    def billed(self):
        trx = self.awaiting_billing()
        return trx, services.issue_bill(trx, self.billing, total_amount=Decimal('12000.00'))

    def test_a_bill_can_be_rejected(self):
        trx, bill = self.billed()
        services.reject_bill(bill, self.billing, remarks='Duplicate request.')
        bill.refresh_from_db()
        self.assertEqual(bill.status, SimulatedBill.Status.REJECTED)

    def test_a_rejected_bill_takes_no_payment(self):
        trx, bill = self.billed()
        services.reject_bill(bill, self.billing, remarks='Duplicate request.')
        with self.assertRaises(services.BillNotPayableError):
            services.record_payment(bill, self.billing, Decimal('100.00'))

    def test_a_settled_bill_can_be_refunded(self):
        trx, bill = self.billed()
        services.record_payment(bill, self.billing, Decimal('12000.00'))
        services.refund_bill(bill, self.billing, remarks='Trip cancelled.')
        bill.refresh_from_db()
        self.assertEqual(bill.status, SimulatedBill.Status.REFUNDED)

    def test_the_customer_is_told_about_a_rejection(self):
        trx, bill = self.billed()
        services.reject_bill(bill, self.billing, remarks='Duplicate request.')
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.PAYMENT_REJECTED).exists())