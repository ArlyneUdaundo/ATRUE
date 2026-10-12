"""The travel agency workflow, end to end (Section 12).

These tests read as the process a teacher would describe: a student asks for a
trip, a consultant prices it, the student accepts, an officer records a simulated
payment, and the request is closed. They also pin the rules that make that process
safe - the right consultant, the right establishment, the right customer, and no
quotation that silently overwrites the last one.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from audit_logs.models import AuditLog
from billing import services as billing_services
from billing.models import SimulatedBill
from establishments.models import Establishment
from notifications.models import Notification
from simulation.models import SimulationRoleAssignment, SimulationSession, SimulationTransaction
from simulation.role_catalogue import sync_role_catalogue
from travel_agencies import services
from travel_agencies.models import TravelAgencyRequest, TravelQuotation

User = get_user_model()

ITEMS = [{'label': 'Flights', 'amount': '20000.00'},
         {'label': 'Hotel', 'amount': '18000.00'}]


class TravelWorkflowTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.customer = User.objects.create_user(
            'customer', password='pw', account_type=User.AccountType.STUDENT)
        cls.consultant = User.objects.create_user(
            'consultant', password='pw', account_type=User.AccountType.STUDENT)
        cls.other_consultant = User.objects.create_user(
            'other', password='pw', account_type=User.AccountType.STUDENT)
        cls.billing = User.objects.create_user(
            'billing', password='pw', account_type=User.AccountType.STUDENT)
        cls.stranger = User.objects.create_user(
            'stranger', password='pw', account_type=User.AccountType.STUDENT)

        cls.session = SimulationSession.objects.create(
            name='Activity 1', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)
        cls.agency = Establishment.objects.create(
            name='Wanderlust Travel', type=Establishment.Type.TRAVEL_AGENCY)
        cls.other_agency = Establishment.objects.create(
            name='Sunset Tours', type=Establishment.Type.TRAVEL_AGENCY)

        for student, role, establishment in (
                (cls.customer, 'CUSTOMER_TOUR', None),
                (cls.consultant, 'TRAVEL_CONSULTANT', cls.agency),
                (cls.other_consultant, 'TRAVEL_CONSULTANT', cls.other_agency),
                (cls.billing, 'TRAVEL_AGENCY_BILLING_OFFICER', cls.agency)):
            SimulationRoleAssignment.objects.create(
                student=student, assigned_by=cls.instructor, role=role,
                activity_name=cls.session.name, session=cls.session,
                establishment=establishment)


class RequestTests(TravelWorkflowTestCase):

    def test_a_request_is_routed_to_a_consultant_for_review(self):
        request, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', party_size=2, budget='45000')
        self.assertEqual(trx.stage, SimulationTransaction.Stage.INTAKE)
        self.assertEqual(trx.subject, request)
        self.assertEqual(trx.establishment, self.agency)
        self.assertEqual(trx.total_amount, Decimal('45000.00'))

    def test_the_customer_is_told_the_request_was_received(self):
        _, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', budget='45000')
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer, transaction=trx).exists())

    def test_only_the_agencys_consultant_can_claim_the_request(self):
        _, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', budget='45000')
        trx = services.engine.claim_transaction(trx, self.consultant)
        self.assertEqual(trx.claimed_by, self.consultant)

        with self.assertRaises(services.engine.TransactionError):
            services.engine.claim_transaction(trx, self.other_consultant)


class QuotationTests(TravelWorkflowTestCase):

    def quote(self, items=ITEMS, discount='0'):
        request, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', party_size=2, budget='45000')
        return trx, services.prepare_quotation(
            trx, self.consultant, items=items, discount=discount,
            itinerary_days=[{'title': 'Day 1', 'day_number': 1,
                             'activity': 'Arrive in Baguio', 'destination': 'Baguio'}])

    def test_a_quotation_totals_the_line_items(self):
        trx, quotation = self.quote()
        self.assertEqual(quotation.status, TravelQuotation.Status.SENT)
        self.assertEqual(quotation.total, Decimal('38000.00'))
        self.assertEqual(quotation.version, 1)

    def test_a_discount_reduces_the_total(self):
        trx, quotation = self.quote(discount='3000')
        self.assertEqual(quotation.total, Decimal('35000.00'))

    def test_a_re_quote_supersedes_the_previous_one(self):
        trx, first = self.quote()
        second = services.prepare_quotation(
            trx, self.consultant, items=[{'label': 'Flights', 'amount': '15000.00'}])
        first.refresh_from_db()
        self.assertEqual(first.status, TravelQuotation.Status.SUPERSEDED)
        self.assertEqual(second.version, 2)
        self.assertEqual(TravelQuotation.objects.count(), 2)

    def test_the_customer_is_sent_the_quotation(self):
        trx, quotation = self.quote()
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TRAVEL_QUOTATION_READY).exists())

    def test_the_quotation_is_described_as_simulated(self):
        trx, quotation = self.quote()
        message = Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TRAVEL_QUOTATION_READY
        ).values_list('message', flat=True).first()
        self.assertIn('simulated quotation', message)

    def test_a_consultant_from_another_agency_cannot_quote(self):
        request, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', budget='45000')
        with self.assertRaises(services.engine.TransactionError):
            services.prepare_quotation(trx, self.other_consultant, items=ITEMS)

    def test_a_student_with_no_role_cannot_quote(self):
        request, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', budget='45000')
        with self.assertRaises(services.engine.TransactionError):
            services.prepare_quotation(trx, self.stranger, items=ITEMS)


class AcceptanceTests(TravelWorkflowTestCase):

    def quoted(self):
        request, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', party_size=2, budget='45000')
        quotation = services.prepare_quotation(trx, self.consultant, items=ITEMS)
        return trx, quotation

    def test_acceptance_sends_the_request_to_simulated_billing(self):
        trx, quotation = self.quoted()
        trx = services.accept_quotation(trx, self.customer)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.BILLING)
        self.assertEqual(trx.status, SimulationTransaction.Status.CONFIRMED)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, TravelQuotation.Status.ACCEPTED)

    def test_a_different_student_cannot_accept_someone_elses_quotation(self):
        trx, quotation = self.quoted()
        impostor = User.objects.create_user(
            'impostor', password='pw', account_type=User.AccountType.STUDENT)
        with self.assertRaises(services.WorkflowError) as caught:
            services.accept_quotation(trx, impostor)
        self.assertEqual(caught.exception.code, 'not_the_customer')

    def test_the_consultant_is_told_the_quotation_was_accepted(self):
        trx, quotation = self.quoted()
        services.accept_quotation(trx, self.customer)
        self.assertTrue(Notification.objects.filter(
            recipient=self.consultant,
            notification_type=Notification.Type.TRAVEL_REQUEST_ACCEPTED).exists())

    def test_declining_closes_the_request(self):
        trx, quotation = self.quoted()
        trx = services.decline_quotation(trx, self.customer, remarks='Too expensive.')
        self.assertEqual(trx.status, SimulationTransaction.Status.REJECTED)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, TravelQuotation.Status.DECLINED)

    def test_a_declined_request_cannot_be_accepted_later(self):
        trx, quotation = self.quoted()
        services.decline_quotation(trx, self.customer)
        with self.assertRaises(Exception):
            services.accept_quotation(trx, self.customer)


class FullJourneyTests(TravelWorkflowTestCase):

    def test_request_to_payment_closes_the_request_and_the_bill(self):
        request, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', party_size=2, budget='45000')
        quotation = services.prepare_quotation(trx, self.consultant, items=ITEMS)
        trx = services.accept_quotation(trx, self.customer)

        bill = billing_services.issue_bill(trx, self.billing)
        self.assertEqual(bill.total_amount, quotation.total)

        _, bill = billing_services.record_payment(
            bill, self.billing, Decimal('38000.00'))

        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.COMPLETED)
        self.assertEqual(bill.status, SimulatedBill.Status.PAID)

    def test_the_whole_journey_is_in_the_audit_trail(self):
        request, trx = services.submit_request(
            customer=self.customer, establishment=self.agency,
            destination='Baguio', budget='45000')
        quotation = services.prepare_quotation(trx, self.consultant, items=ITEMS)
        trx = services.accept_quotation(trx, self.customer)
        bill = billing_services.issue_bill(trx, self.billing)
        billing_services.record_payment(bill, self.billing, Decimal('38000.00'))

        actions = set(AuditLog.objects.values_list('action', flat=True))
        self.assertTrue({'travel.quotation_sent', 'travel.quotation_accepted',
                         'billing.issue', 'billing.payment'} <= actions)