"""Automatic activity completion (Section: no manual instructor marking).

These tests defend the guarantees the feature makes:

* a student's assignment is only completed from a verified backend success;
* only the acting student's own assignment is ever completed;
* completion is idempotent - a refresh or resubmission never double-completes
  and never writes a second completion event;
* a CUSTOMER action never completes a RESERVATION/MANAGER assignment and vice
  versa;
* a completed assignment can no longer be performed, and the completion is
  recorded in the student's session activity log.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from atrue_core.services import confirm_booking
from establishments.models import Establishment, establishment_for_instance
from restaurants.models import Reservation as RestaurantReservation
from restaurants.models import Restaurant, Table
from restaurants.services import confirm_restaurant_reservation
from simulation import engine
from simulation.completion import (
    complete_activity_assignment,
    complete_guest_booking,
    complete_reservation_confirmation,
    establishment_for_booking,
)
from simulation.models import (
    ActivityLog,
    Role,
    SimulationRoleAssignment,
    SimulationSession,
    SimulationTransaction,
)
from simulation.role_catalogue import sync_role_catalogue
from travel_agencies.models import TravelAgencyRequest

User = get_user_model()


class CompletionTestCase(TestCase):
    """One active session, one travel-agency establishment, and a small cast."""

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'completion-instructor', password='pw',
            account_type=User.AccountType.INSTRUCTOR)
        cls.guest = cls._student('completion-guest')
        cls.other_guest = cls._student('completion-other-guest')
        cls.consultant = cls._student('completion-consultant')
        cls.manager = cls._student('completion-manager')

        cls.session = SimulationSession.objects.create(
            name='Completion Activity', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)
        cls.agency = Establishment.objects.create(
            name='Completion Agency', type=Establishment.Type.TRAVEL_AGENCY)

    @staticmethod
    def _student(username):
        return User.objects.create_user(
            username, password='pw', account_type=User.AccountType.STUDENT)

    @classmethod
    def assign(cls, student, role_code, establishment=None):
        return SimulationRoleAssignment.objects.create(
            student=student, assigned_by=cls.instructor, role=role_code,
            activity_name=cls.session.name, session=cls.session,
            establishment=establishment)

    def make_transaction(self):
        request = TravelAgencyRequest.objects.create(
            customer=self.guest, establishment=self.agency,
            destination='Baguio', travel_date=date(2026, 11, 1),
            return_date=date(2026, 11, 5), party_size=2)
        trx = engine.submit_transaction(
            subject=request,
            transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
            initiator=self.guest, session=self.session,
            establishment=self.agency)
        trx.refresh_from_db()
        return trx


class HelperTests(CompletionTestCase):

    def test_completing_marks_the_assignment_done_and_stamps_the_time(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        done = complete_guest_booking(
            self.guest, assignment=assignment, booking_reference='REF-1')
        self.assertIsNotNone(done)
        assignment.refresh_from_db()
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.DONE)
        self.assertIsNotNone(assignment.completed_at)

    def test_completion_is_idempotent(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        first = complete_guest_booking(self.guest, assignment=assignment)
        second = complete_guest_booking(self.guest, assignment=assignment)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        assignment.refresh_from_db()
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.DONE)
        self.assertEqual(
            ActivityLog.objects.filter(
                user=self.guest, action='Completed guest booking').count(),
            1)

    def test_a_customer_action_never_completes_an_officer_assignment(self):
        assignment = self.assign(
            self.consultant, 'TRAVEL_AGENCY_RESERVATION_AGENT', self.agency)
        self.assertIsNone(
            complete_guest_booking(self.consultant, assignment=assignment))
        assignment.refresh_from_db()
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_an_officer_action_never_completes_a_customer_assignment(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        self.assertIsNone(complete_reservation_confirmation(
            self.guest, assignment=assignment, establishment=self.agency))
        assignment.refresh_from_db()
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_only_the_acting_students_assignment_is_completed(self):
        mine = self.assign(self.guest, 'PASSENGER_AIRLINE')
        theirs = self.assign(self.other_guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=mine)
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertEqual(
            mine.status, SimulationRoleAssignment.AssignmentStatus.DONE)
        self.assertEqual(
            theirs.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_a_task_assignment_id_resolves_the_launched_role(self):
        launched = self.assign(self.guest, 'PASSENGER_AIRLINE')
        self.assign(self.guest, 'GUEST_HOTEL')
        done = complete_guest_booking(
            self.guest, task_assignment_id=launched.pk)
        self.assertEqual(done.pk, launched.pk)
        launched.refresh_from_db()
        self.assertEqual(
            launched.status, SimulationRoleAssignment.AssignmentStatus.DONE)

    def test_ambiguous_resolution_completes_nothing(self):
        first = self.assign(self.guest, 'PASSENGER_AIRLINE')
        second = self.assign(self.guest, 'GUEST_HOTEL')
        self.assertIsNone(complete_guest_booking(self.guest))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(
            first.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertEqual(
            second.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_a_completion_is_written_to_the_activity_log_with_the_session(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=assignment)
        log = ActivityLog.objects.get(
            user=self.guest, action='Completed guest booking')
        self.assertEqual(log.session, self.session)
        self.assertEqual(log.simulation_role, 'PASSENGER_AIRLINE')


class EngineCompletionTests(CompletionTestCase):

    def setUp(self):
        self.assign(self.guest, 'PASSENGER_AIRLINE')
        self.officer = self.assign(
            self.consultant, 'TRAVEL_AGENCY_RESERVATION_AGENT', self.agency)
        self.manager_assignment = self.assign(
            self.manager, 'TRAVEL_AGENCY_MANAGER', self.agency)

    def _claimed(self):
        trx = self.make_transaction()
        engine.claim_transaction(trx, self.consultant)
        trx.refresh_from_db()
        return trx

    def test_submitting_a_request_completes_the_customer(self):
        self.make_transaction()
        assignment = SimulationRoleAssignment.objects.get(
            student=self.guest, session=self.session)
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.DONE)
        self.assertIsNotNone(assignment.completed_at)

    def test_approving_completes_the_reservation_officer(self):
        trx = self._claimed()
        engine.approve(trx, self.consultant)
        self.officer.refresh_from_db()
        self.assertEqual(
            self.officer.status, SimulationRoleAssignment.AssignmentStatus.DONE)

    def test_settling_billing_completes_the_manager(self):
        trx = self._claimed()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        engine.claim_transaction(trx, self.manager)
        engine.complete(trx, self.manager)
        self.manager_assignment.refresh_from_db()
        self.assertEqual(
            self.manager_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.DONE)

    def test_completing_the_manager_leaves_the_customer_untouched(self):
        trx = self._claimed()
        engine.approve(trx, self.consultant)
        officer = SimulationRoleAssignment.objects.get(
            student=self.consultant, session=self.session)
        self.assertEqual(
            officer.status, SimulationRoleAssignment.AssignmentStatus.DONE)
        # The guest's assignment was completed at submit; the officer's action
        # must not have disturbed anybody else.
        self.assertEqual(
            SimulationRoleAssignment.objects.filter(
                status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                session=self.session).count(), 1)


class LegacyConfirmationTests(TestCase):
    """The request-free confirm services used by the booking apps."""

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'legacy-instructor', password='pw',
            account_type=User.AccountType.INSTRUCTOR)
        cls.guest = User.objects.create_user(
            'legacy-guest', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.officer = User.objects.create_user(
            'legacy-officer', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.restaurant = Restaurant.objects.create(
            name='Completion Bistro', location='Manila')
        cls.establishment = establishment_for_instance(
            cls.restaurant, create=True)
        cls.table = Table.objects.create(
            restaurant=cls.restaurant, table_number='C1', capacity=4)
        cls.session = SimulationSession.objects.create(
            name='Legacy Activity', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)
        cls.officer_assignment = SimulationRoleAssignment.objects.create(
            student=cls.officer, assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER,
            activity_name=cls.session.name, session=cls.session,
            establishment=cls.establishment)

    def _pending_reservation(self):
        return RestaurantReservation.objects.create(
            customer=self.guest, table=self.table,
            reservation_datetime=self._when(), number_of_guests=2,
            status=RestaurantReservation.Status.PENDING)

    @staticmethod
    def _when():
        from datetime import datetime
        from django.utils import timezone
        return timezone.make_aware(
            datetime(2028, 10, 20, 19, 30), timezone.get_current_timezone())

    def test_establishment_for_booking_finds_the_restaurant_establishment(self):
        reservation = self._pending_reservation()
        self.assertEqual(
            establishment_for_booking(reservation), self.establishment)

    def test_confirming_a_restaurant_reservation_completes_the_officer(self):
        reservation = self._pending_reservation()
        confirm_restaurant_reservation(
            reservation_id=reservation.pk, officer=self.officer)
        self.officer_assignment.refresh_from_db()
        self.assertEqual(
            self.officer_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.DONE)
        self.assertEqual(
            ActivityLog.objects.filter(
                user=self.officer,
                action='Completed reservation confirmation').count(), 1)

    def test_generic_confirm_booking_completes_the_officer(self):
        reservation = self._pending_reservation()
        confirm_booking(reservation, self.officer, notify=False)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'CONFIRMED')
        self.officer_assignment.refresh_from_db()
        self.assertEqual(
            self.officer_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.DONE)


class RestrictionTests(CompletionTestCase):

    def test_a_done_assignment_cannot_start_its_task(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=assignment)
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.guest)
        response = client.get(reverse('simulation:do_task', args=[assignment.pk]))
        self.assertEqual(response.status_code, 404)

    def test_an_active_assignment_can_still_start_its_task(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.guest)
        response = client.get(reverse('simulation:do_task', args=[assignment.pk]))
        self.assertNotEqual(response.status_code, 404)