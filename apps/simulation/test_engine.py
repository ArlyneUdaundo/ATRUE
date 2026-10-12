"""Rules the transaction engine must never break (Section 19).

Each test names the rule it defends, because these are the guarantees the
platform is judged on: routing to the right role, isolation between
establishments and sessions, single-owner claiming, no self-approval, legal
transitions only, and an audit/notification trail for every one of them.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from audit_logs.models import AuditLog
from establishments.models import Establishment
from notifications.models import Notification
from simulation import engine
from simulation.models import (
    Role,
    SimulationRoleAssignment,
    SimulationSession,
    SimulationTransaction,
    TransactionEvent,
)
from simulation.role_catalogue import permissions_for, sync_role_catalogue
from travel_agencies.models import TravelAgencyRequest

User = get_user_model()

OPERATIONAL_CATEGORIES = [
    Role.Category.HOTEL, Role.Category.AIRLINE, Role.Category.TOUR,
    Role.Category.TRANSPORTATION, Role.Category.TRAVEL_AGENCY,
]


class EngineTestCase(TestCase):
    """Shared fixtures: one active session, two agencies, and the classroom cast.

    The cast mirrors the classroom the requirements describe, in terms of the
    three-operational-roles model: a customer, the Reservation role at one
    agency, the Manager at the same agency (who settles the bills), the
    Reservation role at a *different* agency, and the instructor.
    """

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()

        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.customer = cls._student('customer')
        cls.consultant = cls._student('consultant')
        cls.billing = cls._student('billing')
        cls.other_consultant = cls._student('otherconsultant')

        cls.session = SimulationSession.objects.create(
            name='Activity 1', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)

        cls.agency = Establishment.objects.create(
            name='Wanderlust Travel', type=Establishment.Type.TRAVEL_AGENCY)
        cls.other_agency = Establishment.objects.create(
            name='Globetrotter Agency', type=Establishment.Type.TRAVEL_AGENCY)

        # `billing` is the agency Manager: simulated billing is an oversight
        # action, so there is no separate billing officer to route to.
        cls.assign(cls.customer, 'PASSENGER_AIRLINE')
        cls.assign(cls.consultant, 'TRAVEL_AGENCY_RESERVATION_AGENT', cls.agency)
        cls.assign(cls.billing, 'TRAVEL_AGENCY_MANAGER', cls.agency)
        cls.assign(cls.other_consultant, 'TRAVEL_AGENCY_RESERVATION_AGENT', cls.other_agency)

    @staticmethod
    def _student(username):
        return User.objects.create_user(
            username, password='pw', first_name=username.capitalize(),
            account_type=User.AccountType.STUDENT)

    @classmethod
    def assign(cls, student, role_code, establishment=None):
        return SimulationRoleAssignment.objects.create(
            student=student, assigned_by=cls.instructor, role=role_code,
            activity_name=cls.session.name, session=cls.session,
            establishment=establishment)

    def make_request(self, **overrides):
        fields = {
            'customer': self.customer,
            'establishment': self.agency,
            'destination': 'Baguio',
            'travel_date': date(2026, 11, 1),
            'return_date': date(2026, 11, 5),
            'party_size': 2,
        }
        fields.update(overrides)
        return TravelAgencyRequest.objects.create(**fields)

    def make_transaction(self, subject=None, **overrides):
        """A saved PENDING travel-agency request raised by the customer."""
        subject = subject or self.make_request()
        trx = engine.submit_transaction(
            subject=subject,
            transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
            initiator=overrides.pop('initiator', self.customer),
            session=overrides.pop('session', self.session),
            establishment=overrides.pop('establishment', self.agency),
            **overrides,
        )
        trx.refresh_from_db()
        return trx


class SubmitTests(EngineTestCase):

    def test_submitted_request_is_routed_to_the_intake_stage(self):
        trx = self.make_transaction()
        self.assertEqual(trx.status, SimulationTransaction.Status.PENDING)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.INTAKE)
        self.assertEqual(trx.establishment, self.agency)
        self.assertEqual(trx.session, self.session)

    def test_the_reservation_is_referenced_not_copied(self):
        request = self.make_request()
        trx = self.make_transaction(subject=request)
        self.assertEqual(trx.subject_id, request.pk)
        self.assertEqual(trx.subject, request)
        self.assertEqual(trx.subject_label, request.request_reference)

    def test_submission_is_never_claimed_by_the_initiator(self):
        self.assertIsNone(self.make_transaction().claimed_by)

    def test_submission_is_announced_to_the_handlers_not_the_initiator(self):
        self.make_transaction()
        recipients = set(Notification.objects.values_list('recipient', flat=True))
        self.assertIn(self.consultant.pk, recipients)
        self.assertNotIn(self.customer.pk, recipients)

    def test_submission_leaves_an_audit_trail(self):
        self.make_transaction()
        self.assertTrue(AuditLog.objects.filter(
            action='transaction.submit', actor=self.customer).exists())

    def test_submission_leaves_an_immutable_history_row(self):
        trx = self.make_transaction()
        event = TransactionEvent.objects.get(transaction=trx, action='submit')
        self.assertEqual(event.actor, self.customer)
        with self.assertRaises(ValueError):
            event.delete()

    def test_a_student_with_no_active_role_cannot_raise_a_request(self):
        stranger = self._student('stranger')
        with self.assertRaises(engine.NotEligibleError):
            engine.submit_transaction(
                subject=self.make_request(),
                transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
                initiator=stranger, session=self.session, establishment=self.agency)

    def test_request_is_refused_when_the_session_is_not_active(self):
        self.session.status = SimulationSession.Status.COMPLETED
        self.session.save(update_fields=['status'])
        with self.assertRaises(engine.SessionNotActiveError):
            self.make_transaction()

    def test_request_cannot_be_routed_to_the_wrong_kind_of_establishment(self):
        hotel = Establishment.objects.create(name='ABC Grand', type=Establishment.Type.HOTEL)
        with self.assertRaises(engine.TransactionError) as caught:
            engine.submit_transaction(
                subject=self.make_request(),
                transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
                initiator=self.customer, session=self.session, establishment=hotel)
        self.assertEqual(caught.exception.code, 'establishment_type_mismatch')

    def test_inactive_establishment_accepts_nothing(self):
        self.agency.status = Establishment.Status.SUSPENDED
        self.agency.save(update_fields=['status'])
        with self.assertRaises(engine.TransactionError) as caught:
            self.make_transaction()
        self.assertEqual(caught.exception.code, 'establishment_inactive')

    def test_a_request_with_no_subject_is_refused(self):
        with self.assertRaises(engine.TransactionError) as caught:
            engine.submit_transaction(
                subject=None,
                transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
                initiator=self.customer, session=self.session,
                establishment=self.agency)
        self.assertEqual(caught.exception.code, 'no_subject')


class ClaimTests(EngineTestCase):

    def test_the_responsible_consultant_can_claim(self):
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.consultant)
        trx.refresh_from_db()
        self.assertEqual(trx.claimed_by, self.consultant)
        self.assertEqual(trx.status, SimulationTransaction.Status.UNDER_REVIEW)
        self.assertIsNotNone(trx.claimed_at)

    def test_only_one_student_can_hold_a_claim(self):
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.consultant)
        with self.assertRaises(engine.AlreadyClaimedError):
            engine.claim_transaction(trx, self.other_consultant)

    def test_the_initiator_may_never_claim_their_own_request(self):
        trx = self.make_transaction()
        with self.assertRaises(engine.SelfApprovalError):
            engine.claim_transaction(trx, self.customer)

    def test_a_student_at_another_establishment_may_not_claim(self):
        trx = self.make_transaction()
        with self.assertRaises(engine.NotEligibleError):
            engine.claim_transaction(trx, self.other_consultant)

    def test_the_right_establishment_in_another_session_grants_nothing(self):
        other_session = SimulationSession.objects.create(
            name='Activity 2', instructor=self.instructor,
            status=SimulationSession.Status.ACTIVE)
        SimulationRoleAssignment.objects.create(
            student=self.other_consultant, assigned_by=self.instructor,
            role='TRAVEL_CONSULTANT', activity_name=other_session.name,
            session=other_session, establishment=self.agency)
        trx = self.make_transaction()
        with self.assertRaises(engine.NotEligibleError):
            engine.claim_transaction(trx, self.other_consultant)

    def test_inactive_assignment_grants_no_authority(self):
        SimulationRoleAssignment.objects.filter(student=self.consultant).update(
            status=SimulationRoleAssignment.AssignmentStatus.INACTIVE)
        trx = self.make_transaction()
        with self.assertRaises(engine.NotEligibleError):
            engine.claim_transaction(trx, self.consultant)

    def test_claiming_tells_the_initiator_who_took_the_request(self):
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.consultant)
        self.assertTrue(Notification.objects.filter(
            recipient=self.customer,
            notification_type=Notification.Type.TRANSACTION_CLAIMED).exists())

    def test_a_claim_can_be_released_for_a_classmate(self):
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.consultant)
        engine.release_claim(trx, self.consultant)
        trx.refresh_from_db()
        self.assertIsNone(trx.claimed_by)
        self.assertEqual(trx.status, SimulationTransaction.Status.PENDING)

    def test_only_the_holder_or_a_supervisor_can_release_a_claim(self):
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.consultant)
        with self.assertRaises(engine.NotEligibleError):
            engine.release_claim(trx, self.customer)


class TransitionTests(EngineTestCase):

    def claimed(self, actor=None):
        trx = self.make_transaction()
        engine.claim_transaction(trx, actor or self.consultant)
        trx.refresh_from_db()
        return trx

    def test_approval_hands_the_request_to_fulfilment(self):
        trx = self.claimed()
        engine.approve(trx, self.consultant)
        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.CONFIRMED)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.FULFILLMENT)
        self.assertIsNotNone(trx.confirmed_at)

    def test_approval_may_go_straight_to_billing(self):
        trx = self.claimed()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        self.assertEqual(trx.stage, SimulationTransaction.Stage.BILLING)

    def test_approval_cannot_send_the_request_somewhere_absurd(self):
        trx = self.claimed()
        with self.assertRaises(engine.TransactionError) as caught:
            engine.approve(trx, self.consultant, stage='INTAKE')
        self.assertEqual(caught.exception.code, 'bad_stage')

    def test_the_initiator_may_not_approve_their_own_request(self):
        trx = self.make_transaction()
        # Even holding a second, operational role at the same agency, the rule is
        # absolute: you cannot process your own request (Scenario 5).
        self.assign(self.customer, 'TRAVEL_CONSULTANT', self.agency)
        with self.assertRaises(engine.SelfApprovalError):
            engine.approve(trx, self.customer)

    def test_an_unclaimed_request_cannot_be_approved(self):
        trx = self.make_transaction()
        with self.assertRaises(engine.NotEligibleError):
            engine.approve(trx, self.consultant)

    def test_rejection_closes_the_request(self):
        trx = self.claimed()
        engine.reject(trx, self.consultant, remarks='No availability that week.')
        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.REJECTED)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.CLOSED)

    def test_a_closed_request_never_moves_again(self):
        trx = self.claimed()
        engine.reject(trx, self.consultant)
        with self.assertRaises(engine.IllegalTransitionError):
            engine.approve(trx, self.consultant)

    def test_a_request_under_review_is_not_claimable_again(self):
        trx = self.claimed()
        with self.assertRaises(engine.AlreadyClaimedError):
            engine.claim_transaction(trx, self.consultant)

    def test_billing_is_worked_by_the_manager(self):
        trx = self.claimed()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        engine.claim_transaction(trx, self.billing)
        engine.complete(trx, self.billing)
        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.COMPLETED)
        self.assertEqual(trx.stage, SimulationTransaction.Stage.DONE)
        self.assertIsNone(trx.claimed_by)
        self.assertIsNotNone(trx.completed_at)

    def test_the_manager_supervises_the_intake_stage(self):
        """Oversight means a Manager may act at any stage, not only billing.

        Replacing the billing officer with the Manager would be a downgrade if the
        Manager could then no longer see or act on a request before it is billed.
        """
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.billing)
        trx.refresh_from_db()
        self.assertEqual(trx.claimed_by, self.billing)

    def test_the_reservation_role_cannot_act_at_the_billing_stage(self):
        """Billing belongs to the Manager, so the Reservation role is out."""
        trx = self.claimed()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        with self.assertRaises(engine.NotEligibleError):
            engine.claim_transaction(trx, self.consultant)

    def test_a_fulfilment_step_refused_while_the_request_awaits_billing(self):
        trx = self.claimed()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        engine.claim_transaction(trx, self.billing)
        with self.assertRaises(engine.StageMismatchError):
            engine.fulfil(trx, self.billing)

    def test_history_records_the_full_path_of_a_request(self):
        trx = self.claimed()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        engine.claim_transaction(trx, self.billing)
        engine.complete(trx, self.billing)
        path = list(TransactionEvent.objects.filter(transaction=trx)
                    .order_by('created_at', 'id')
                    .values_list('action', 'from_status', 'to_status'))
        self.assertEqual(path, [
            ('submit', '', 'PENDING'),
            ('claim', 'PENDING', 'UNDER_REVIEW'),
            ('approve', 'UNDER_REVIEW', 'CONFIRMED'),
            ('claim', 'CONFIRMED', 'CONFIRMED'),
            ('complete', 'CONFIRMED', 'COMPLETED'),
        ])

    def test_oversight_roles_may_act_at_any_stage(self):
        self.assign(self.instructor, 'TRAVEL_AGENCY_MANAGER', self.agency)
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.instructor)
        engine.approve(trx, self.instructor)
        trx.refresh_from_db()
        self.assertEqual(trx.status, SimulationTransaction.Status.CONFIRMED)

    def test_an_unknown_action_is_refused(self):
        trx = self.claimed()
        with self.assertRaises(engine.TransactionError) as caught:
            engine.transition(trx, self.consultant, 'teleport')
        self.assertEqual(caught.exception.code, 'unknown_action')


class VisibilityTests(EngineTestCase):

    def test_the_initiator_can_see_their_own_request(self):
        trx = self.make_transaction()
        self.assertIn(trx, engine.visible_transactions(self.customer))

    def test_the_handling_consultant_can_see_the_request(self):
        trx = self.make_transaction()
        self.assertIn(trx, engine.visible_transactions(self.consultant))

    def test_a_student_at_another_establishment_sees_nothing(self):
        self.make_transaction()
        self.assertFalse(engine.visible_transactions(self.other_consultant).exists())

    def test_the_instructor_sees_everything_in_their_session(self):
        self.make_transaction()
        self.assertEqual(engine.visible_transactions(self.instructor).count(), 1)

    def test_handlers_are_the_reservation_role_and_the_supervising_manager(self):
        """At intake the Reservation role handles it; the Manager oversees.

        ``handlers_for`` deliberately includes the oversight stage alongside the
        stage itself, so a request is never sitting with nobody who can see it.
        """
        trx = self.make_transaction()
        handlers = {assignment.student for assignment in engine.handlers_for(trx)}
        self.assertEqual(handlers, {self.consultant, self.billing})

    def test_handlers_change_once_the_request_reaches_billing(self):
        trx = self.claimed_transaction()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        handlers = {assignment.student for assignment in engine.handlers_for(trx)}
        self.assertEqual(handlers, {self.billing})

    def claimed_transaction(self):
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.consultant)
        trx.refresh_from_db()
        return trx


class CatalogueTests(TestCase):
    """Section 6.3: the catalogue is data, and it is seeded rather than typed."""

    def test_every_active_catalogue_row_carries_its_permissions(self):
        sync_role_catalogue()
        for role in Role.objects.filter(is_active=True):
            self.assertEqual(role.permissions, permissions_for(role.code))

    def test_synchronising_twice_changes_nothing(self):
        sync_role_catalogue()
        before = Role.objects.count()
        self.assertEqual(sync_role_catalogue(), (0, 0, 0))
        self.assertEqual(Role.objects.count(), before)

    def test_operational_roles_belong_to_an_establishment(self):
        for role in Role.objects.filter(
                establishment_type__isnull=False, is_active=True):
            self.assertTrue(role.requires_establishment, role.code)

    def test_every_establishment_type_has_its_operational_roles(self):
        """Each establishment carries the operational categories it needs.

        Most establishments field the Manager / Reservation / Front Desk
        triple, but Activities and Tour Packages carry just Reservation +
        Operator (the Operator is their Front Desk), because the Manager
        authority for one activity or package sits with the parent Tour
        Operator.
        """
        for establishment_type in Role.EstablishmentType.values:
            categories = set(Role.objects.filter(
                establishment_type=establishment_type, is_active=True,
            ).values_list('operation_category', flat=True))
            if establishment_type in (Role.EstablishmentType.ACTIVITY,
                                      Role.EstablishmentType.TOUR_PACKAGE):
                expected = {Role.OperationCategory.RESERVATION,
                            Role.OperationCategory.FRONT_DESK}
            else:
                expected = {Role.OperationCategory.MANAGER,
                            Role.OperationCategory.RESERVATION,
                            Role.OperationCategory.FRONT_DESK}
            self.assertEqual(categories, expected, establishment_type)

    def test_the_roles_of_every_establishment_route_to_distinct_stages(self):
        """The stages follow the categories, so the two-person resource sets
        cover intake and fulfilment rather than oversight."""
        for establishment_type in Role.EstablishmentType.values:
            # Read the attribute, not values_list(): on a field with choices
            # values_list yields the label rather than the stored code.
            stages = {
                role.workflow_stage for role in Role.objects.filter(
                    establishment_type=establishment_type, is_active=True)
            }
            if establishment_type in (Role.EstablishmentType.ACTIVITY,
                                      Role.EstablishmentType.TOUR_PACKAGE):
                expected = {Role.WorkflowStage.INTAKE,
                            Role.WorkflowStage.FULFILLMENT}
            else:
                expected = {Role.WorkflowStage.OVERSIGHT,
                            Role.WorkflowStage.INTAKE,
                            Role.WorkflowStage.FULFILLMENT}
            self.assertEqual(stages, expected, establishment_type)

    def test_billing_is_a_manager_action_rather_than_a_fourth_role(self):
        """Simulated billing must not reintroduce a billing-officer role.

        The Manager supervises, so the billing stage is reachable; what must not
        happen is a fourth operational role existing just to close the bill.
        """
        for establishment_type in Role.EstablishmentType.values:
            codes = list(Role.objects.filter(
                establishment_type=establishment_type, is_active=True,
            ).values_list('code', flat=True))
            # Activities and packages run a two-person set (Reservation +
            # Operator); the rest of the platform runs the Manager triple.
            minimum = 3 if establishment_type not in (
                Role.EstablishmentType.ACTIVITY,
                Role.EstablishmentType.TOUR_PACKAGE) else 2
            self.assertGreaterEqual(len(codes), minimum, establishment_type)
            self.assertFalse(
                [code for code in codes if 'BILLING' in code],
                f'{establishment_type} still has a billing role: {codes}',
            )

    def test_customer_roles_belong_to_no_establishment(self):
        for role in Role.objects.filter(
                category=Role.Category.CUSTOMER, is_active=True):
            self.assertFalse(role.requires_establishment, role.code)