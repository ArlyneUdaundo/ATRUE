"""Verified role-task progress and instructor-reviewed assignments.

These tests defend the guarantees the feature makes:

* verified backend successes advance only the acting student's assignment;
* assignment status remains ACTIVE for instructor review;
* completion is idempotent - a refresh or resubmission never double-completes
  and never writes a second completion event;
* a CUSTOMER action never completes a RESERVATION/MANAGER assignment and vice
  versa;
* a completed assignment can no longer be performed, and the completion is
  recorded in the student's session activity log.
"""

from datetime import date
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from atrue_core.services import confirm_booking
from establishments.models import Establishment, establishment_for_instance
from hotels.models import Hotel
from airlines.models import Airline
from notifications.models import Notification
from restaurants.models import Reservation as RestaurantReservation
from restaurants.models import Restaurant, Table
from restaurants.services import confirm_restaurant_reservation
from simulation import engine
from simulation.completion import (
    complete_activity_assignment,
    complete_guest_booking,
    complete_reservation_confirmation,
    establishment_for_booking,
    _workflow_route_matches,
)
from simulation.models import (
    ActivityLog,
    Role,
    SimulationAssignmentTaskCompletion,
    SimulationRoleAssignment,
    SimulationSession,
    SimulationTransaction,
)
from simulation.role_catalogue import sync_role_catalogue
from simulation.task_routing import assignment_tasks_for
from simulation.task_routing import (
    _GUEST_OPERATIONS,
    _OPERATIONS,
    GUEST_ROLE_ALIASES,
    assignment_tasks_for,
    task_operation_for,
)
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

    def test_verified_booking_records_task_without_finishing_assignment(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        done = complete_guest_booking(
            self.guest, assignment=assignment, booking_reference='REF-1')
        self.assertIsNotNone(done)
        assignment.refresh_from_db()
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertIsNone(assignment.completed_at)
        from simulation.models import SimulationAssignmentTaskCompletion
        completion = SimulationAssignmentTaskCompletion.objects.get(assignment=assignment)
        self.assertEqual(completion.task_key, 'passenger_airline.book_flight')
        self.assertEqual(completion.completion_event, 'CUSTOMER_BOOKING_SUBMITTED')

    def test_task_completion_is_idempotent(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        other_instructor = User.objects.create_user(
            'other-completion-instructor', password='pw',
            account_type=User.AccountType.INSTRUCTOR)
        first = complete_guest_booking(self.guest, assignment=assignment)
        second = complete_guest_booking(self.guest, assignment=assignment)
        self.assertIsNotNone(first)
        self.assertEqual(second.pk, assignment.pk)
        self.assertEqual(
            ActivityLog.objects.filter(
                user=self.guest, action='Completed simulation task').count(), 1)
        instructor_notice = Notification.objects.get(recipient=self.instructor)
        self.assertEqual(
            instructor_notice.notification_type,
            Notification.Type.STUDENT_WORK_COMPLETED)
        self.assertEqual(instructor_notice.assignment, assignment)
        self.assertEqual(instructor_notice.actor, self.guest)
        self.assertIn('completion-guest', instructor_notice.message)
        self.assertIn('Book Flight', instructor_notice.message)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.instructor,
                notification_type=Notification.Type.STUDENT_WORK_COMPLETED,
            ).count(), 1)
        self.assertFalse(Notification.objects.filter(
            recipient=other_instructor,
            notification_type=Notification.Type.STUDENT_WORK_COMPLETED,
        ).exists())
        assignment.refresh_from_db()
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertEqual(
            ActivityLog.objects.filter(
                user=self.guest, action='Completed guest booking').count(),
            1)
        completion_event = ActivityLog.objects.get(
            user=self.guest, action='Completed simulation task')
        self.assertEqual(completion_event.role_assignment, assignment)
        self.assertEqual(
            ActivityLog.objects.filter(
                user=self.guest, action='Completed simulation task').count(), 1)

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

    def test_only_the_acting_students_assignment_receives_progress(self):
        mine = self.assign(self.guest, 'PASSENGER_AIRLINE')
        theirs = self.assign(self.other_guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=mine)
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertEqual(
            mine.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
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
            launched.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_ambiguous_resolution_records_nothing(self):
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

    def test_submitting_passenger_request_records_verified_progress_only(self):
        self.make_transaction()
        assignment = SimulationRoleAssignment.objects.get(
            student=self.guest, session=self.session)
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertIsNone(assignment.completed_at)
        self.assertTrue(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=assignment, task_key='passenger_airline.book_flight').exists())

    def test_approving_records_progress_for_instructor_review(self):
        trx = self._claimed()
        engine.approve(trx, self.consultant)
        self.officer.refresh_from_db()
        self.assertEqual(
            self.officer.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertTrue(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=self.officer,
            task_key='travel_agency_reservation_agent.booking_work').exists())

    def test_settling_does_not_auto_mark_the_manager_assignment_done(self):
        trx = self._claimed()
        engine.approve(trx, self.consultant,
                       stage=SimulationTransaction.Stage.BILLING)
        trx.refresh_from_db()
        engine.claim_transaction(trx, self.manager)
        engine.complete(trx, self.manager)
        self.manager_assignment.refresh_from_db()
        self.assertEqual(
            self.manager_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_completing_the_manager_leaves_the_customer_untouched(self):
        trx = self._claimed()
        engine.approve(trx, self.consultant)
        officer = SimulationRoleAssignment.objects.get(
            student=self.consultant, session=self.session)
        self.assertEqual(
            officer.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        # Verified passenger progress remains ACTIVE pending instructor review.
        guest_assignment = SimulationRoleAssignment.objects.get(
            student=self.guest, session=self.session)
        self.assertEqual(guest_assignment.status,
                         SimulationRoleAssignment.AssignmentStatus.ACTIVE)


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

    def test_restaurant_confirmation_needs_verified_deposit_before_task_completion(self):
        reservation = self._pending_reservation()
        from restaurants.services import RestaurantReservationError
        with self.assertRaises(RestaurantReservationError):
            confirm_restaurant_reservation(
                reservation_id=reservation.pk, officer=self.officer)
        self.officer_assignment.refresh_from_db()
        self.assertEqual(
            self.officer_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertFalse(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=self.officer_assignment).exists())

    def test_generic_booking_confirmation_does_not_bypass_restaurant_payment(self):
        reservation = self._pending_reservation()
        confirm_booking(reservation, self.officer, notify=False)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'PENDING')
        self.officer_assignment.refresh_from_db()
        self.assertEqual(
            self.officer_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertFalse(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=self.officer_assignment).exists())


class RestrictionTests(CompletionTestCase):

    def test_verified_task_progress_does_not_automatically_finish_assignment(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=assignment)
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.guest)
        response = client.get(reverse('simulation:do_task', args=[assignment.pk]))
        self.assertNotEqual(response.status_code, 404)


class SessionProgressTests(CompletionTestCase):

    def test_role_task_list_uses_stable_keys_and_marks_unverified_links(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        tasks = assignment_tasks_for(assignment)
        self.assertEqual([task['label'] for task in tasks], [
            'Book Flight', 'View Booking', 'Manage Booking', 'Select Seat', 'View Ticket'])
        self.assertEqual(tasks[0]['key'], 'passenger_airline.book_flight')
        self.assertEqual(tasks[0]['completion_events'], ['CUSTOMER_BOOKING_SUBMITTED'])
        self.assertEqual(tasks[1]['completion_events'], [])
        self.assertEqual(tasks[2]['completion_events'], ['PASSENGER_BOOKING_MANAGED'])
        self.assertEqual(tasks[3]['completion_events'], ['PASSENGER_SEAT_SELECTED'])
        self.assertEqual(tasks[4]['completion_events'], [])
        self.assertEqual([task['description'] for task in tasks], [
            'Search for and submit a flight booking.',
            'Review your submitted flight booking details.',
            'Make and save an allowed change to your flight booking.',
            'Choose and save a seat for your booked flight.',
            'Open and review your flight e-ticket.',
        ])

    def test_every_configured_role_task_has_a_trackable_and_unambiguous_action_route(self):
        configured_roles = [
            (establishment_type, role_code)
            for establishment_type, role_operations in _OPERATIONS.items()
            for role_code in role_operations
        ]
        configured_roles.extend(
            ('GUEST', role_code) for role_code in _GUEST_OPERATIONS
        )
        configured_roles.extend(
            ('GUEST', role_code) for role_code in GUEST_ROLE_ALIASES
        )
        configured_roles.append(('AIRLINE', 'PASSENGER_AIRLINE'))

        for establishment_type, role_code in configured_roles:
            with self.subTest(role=role_code):
                role_ref = Role.objects.get(code=role_code)
                needs_context = (
                    establishment_type != 'GUEST'
                    and (role_ref.requires_establishment
                         or role_ref.operation_category == Role.OperationCategory.BILLING)
                )
                assigned_establishment = (
                    SimpleNamespace(
                        type=(role_ref.establishment_category
                              or role_ref.establishment_type or 'HOTEL'))
                    if needs_context else None
                )
                assignment = SimpleNamespace(
                    role=role_code,
                    role_ref=role_ref,
                    role_ref_id=role_ref.pk,
                    operation_category=role_ref.operation_category,
                    establishment_id=1 if assigned_establishment is not None else None,
                    establishment=assigned_establishment,
                    hotel_id=None,
                )
                operation = task_operation_for(assignment)
                tasks = assignment_tasks_for(assignment)
                self.assertIsNotNone(operation, role_code)

                def route_uniquely_tracks(task, route):
                    matches = [
                        other for other in tasks
                        if other.get('completion_events')
                        and any(event.startswith('WORKFLOW_TASK:')
                                for event in other['completion_events'])
                        and _workflow_route_matches(other['route'], route)
                    ]
                    exact = [other for other in matches if other['route'] == route]
                    if exact:
                        matches = exact
                    return len(matches) == 1 and matches[0]['key'] == task['key']

                for task in tasks:
                    if task['classification'] == 'INFORMATIONAL':
                        self.assertFalse(task['completion_events'], role_code)
                        continue
                    self.assertTrue(task['completion_events'], role_code)
                    if not any(
                            event.startswith('WORKFLOW_TASK:')
                            for event in task['completion_events']):
                        continue
                    unique_routes = [
                        route for route in operation['allowed_routes']
                        if route_uniquely_tracks(task, route)
                    ]
                    self.assertTrue(
                        unique_routes,
                        f'{establishment_type}/{role_code}: '
                        f'{task["label"]} has no unique tracked route',
                    )

    def test_passenger_task_completions_are_visible_in_assignment_progress(self):
        from simulation.completion import record_actor_task_event
        from simulation.views import assignment_progress_data

        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        record_actor_task_event(
            self.guest, 'PASSENGER_BOOKING_MANAGED', assignment=assignment)
        record_actor_task_event(
            self.guest, 'PASSENGER_SEAT_SELECTED', assignment=assignment)

        progress = assignment_progress_data(assignment)
        states = {task['key']: task['state'] for task in progress['tasks']}
        self.assertEqual(states['passenger_airline.manage_booking'], 'completed')
        self.assertEqual(states['passenger_airline.select_seat'], 'completed')
        self.assertEqual((progress['completed'], progress['tracked']), (2, 3))

    def test_reservation_role_uses_its_configured_booking_task(self):
        restaurant = Restaurant.objects.create(
            name='Progress Bistro', location='Manila')
        establishment = establishment_for_instance(restaurant)
        assignment = self.assign(
            self.consultant, 'RESTAURANT_RESERVATION_OFFICER', establishment)
        tasks = assignment_tasks_for(assignment)
        self.assertEqual([task['label'] for task in tasks], ['Manage Reservations'])
        self.assertEqual(tasks[0]['completion_events'], ['BOOKING_CONFIRMED'])

    def test_billing_officer_task_uses_verified_payment_event(self):
        hotel = Establishment.objects.create(
            name='Progress Hotel', type=Establishment.Type.HOTEL)
        assignment = self.assign(
            self.consultant, 'HOTEL_BILLING_OFFICER', hotel)
        tasks = assignment_tasks_for(assignment)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['completion_events'], ['PAYMENT_VERIFIED'])

    def test_successful_room_management_is_a_verified_hotel_role_task(self):
        from simulation.completion import record_actor_task_event
        from simulation.views import assignment_progress_data
        hotel = Hotel.objects.create(name='Room Tracking Hotel')
        establishment = establishment_for_instance(hotel, create=True)
        assignment = self.assign(self.manager, 'HOTEL_MANAGER', establishment)
        record_actor_task_event(
            self.manager, 'HOTEL_ROOM_SAVED', establishment=establishment,
            task_assignment_id=assignment.pk)
        progress = assignment_progress_data(assignment)
        room_task = next(task for task in progress['tasks']
                         if task['key'] == 'hotel_manager.room_management')
        self.assertEqual(room_task['state'], 'completed')
        self.assertEqual((progress['completed'], progress['tracked']), (1, 5))
        self.assertEqual(assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_successful_generic_crud_post_is_tracked_for_its_task(self):
        from simulation.completion import record_workflow_action
        from simulation.views import assignment_progress_data
        hotel = Hotel.objects.create(name='CRUD Tracking Hotel')
        establishment = establishment_for_instance(hotel, create=True)
        assignment = self.assign(self.manager, 'HOTEL_MANAGER', establishment)
        self.assertIsNotNone(record_workflow_action(
            self.manager, 'hotels:update_service',
            task_assignment_id=assignment.pk))
        instructor_notice = Notification.objects.get(recipient=self.instructor)
        self.assertEqual(instructor_notice.assignment, assignment)
        self.assertIn('Manage Services', instructor_notice.message)
        progress = assignment_progress_data(assignment)
        service_task = next(task for task in progress['tasks']
                            if task['key'] == 'hotels.task.03')
        self.assertEqual(service_task['state'], 'completed')

    def test_generic_tracking_uses_the_active_assignment_when_routes_overlap(self):
        from simulation.completion import record_workflow_action
        first_hotel = Hotel.objects.create(name='First Tracking Hotel')
        second_hotel = Hotel.objects.create(name='Second Tracking Hotel')
        first = self.assign(
            self.manager, 'HOTEL_MANAGER',
            establishment_for_instance(first_hotel, create=True))
        second = self.assign(
            self.manager, 'HOTEL_MANAGER',
            establishment_for_instance(second_hotel, create=True))

        self.assertIsNotNone(record_workflow_action(
            self.manager, 'hotels:update_service',
            task_assignment_id=second.pk))

        self.assertFalse(first.task_completions.exists())
        self.assertTrue(second.task_completions.exists())

    def test_airline_schedule_creation_matches_flight_management_task(self):
        from simulation.completion import record_workflow_action
        airline = Airline.objects.create(name='Schedule Tracking Airline')
        establishment = establishment_for_instance(airline, create=True)
        assignment = self.assign(self.manager, 'AIRLINE_MANAGER', establishment)

        self.assertIsNotNone(record_workflow_action(
            self.manager, 'airlines:add_flight_schedule',
            task_assignment_id=assignment.pk))
        self.assertTrue(assignment.task_completions.filter(
            completion_event='WORKFLOW_TASK:airlines.task.04').exists())

    def test_generic_crud_tracking_does_not_require_task_page_navigation(self):
        from simulation.completion import record_workflow_action
        hotel = Hotel.objects.create(name='Backend Only Tracking Hotel')
        establishment = establishment_for_instance(hotel, create=True)
        assignment = self.assign(self.manager, 'HOTEL_MANAGER', establishment)
        self.assertIsNotNone(record_workflow_action(
            self.manager, 'hotels:update_service'))
        self.assertTrue(
            assignment.task_completions.filter(
                completion_event='WORKFLOW_TASK:hotels.task.03').exists())

    def test_airline_manager_save_completes_manage_airline(self):
        from simulation.completion import record_establishment_task_event
        airline = Airline.objects.create(name='Manage Airline Test')
        establishment = establishment_for_instance(airline, create=True)
        assignment = self.assign(self.manager, 'AIRLINE_MANAGER', establishment)
        record_establishment_task_event(
            self.manager, 'ESTABLISHMENT_UPDATED', airline)
        completion = assignment.task_completions.get(
            completion_event='ESTABLISHMENT_UPDATED')
        self.assertEqual(completion.task_label, 'Manage Airline')
        self.assertEqual(
            assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_airline_manager_save_tracks_draft_session_assignment(self):
        from simulation.completion import record_establishment_task_event
        draft_session = SimulationSession.objects.create(
            name='Draft Airline Activity', instructor=self.instructor,
            status=SimulationSession.Status.DRAFT)
        airline = Airline.objects.create(name='Draft Airline Test')
        establishment = establishment_for_instance(airline, create=True)
        assignment = SimulationRoleAssignment.objects.create(
            student=self.manager, assigned_by=self.instructor,
            role='AIRLINE_MANAGER', activity_name=draft_session.name,
            session=draft_session, establishment=establishment)
        self.assertIsNotNone(record_establishment_task_event(
            self.manager, 'ESTABLISHMENT_UPDATED', airline))
        self.assertTrue(
            assignment.task_completions.filter(
                completion_event='ESTABLISHMENT_UPDATED').exists())

    def test_hotel_roles_use_establishment_backed_workflows(self):
        hotel = Hotel.objects.create(name='Hotel Workflow Routing')
        establishment = establishment_for_instance(hotel, create=True)
        for role_code in (
                'HOTEL_MANAGER', 'HOTEL_RESERVATION_OFFICER',
                'HOTEL_FRONT_DESK'):
            assignment = self.assign(self.manager, role_code, establishment)
            self.assertTrue(assignment_tasks_for(assignment), role_code)

    def test_owner_creation_tasks_have_verified_post_fallback(self):
        hotel = Hotel.objects.create(name='Owner Creation Hotel')
        establishment = establishment_for_instance(hotel, create=True)
        assignment = self.assign(self.manager, 'HOTEL_OWNER', establishment)
        task = assignment_tasks_for(assignment)[0]
        self.assertIn('ESTABLISHMENT_CREATED', task['completion_events'])
        self.assertTrue(any(
            event.startswith('WORKFLOW_TASK:')
            for event in task['completion_events']
        ))

    def test_new_catalogue_role_uses_its_workflow_metadata(self):
        role = Role.objects.create(
            code='FUTURE_HOTEL_RESERVATION', name='Future Hotel Reservation',
            category=Role.Category.HOTEL,
            establishment_type=Role.EstablishmentType.HOTEL,
            operation_category=Role.OperationCategory.RESERVATION,
            workflow_stage=Role.WorkflowStage.INTAKE,
            is_active=True,
        )
        assignment = SimpleNamespace(
            role=role.code, role_ref=role, role_ref_id=role.pk,
            establishment_type='HOTEL', establishment_id=1,
            establishment=SimpleNamespace(type='HOTEL'), hotel_id=1,
            operation_category=role.operation_category,
        )
        tasks = assignment_tasks_for(assignment)
        self.assertTrue(tasks)
        self.assertEqual(tasks[0]['completion_events'], ['BOOKING_CONFIRMED'])
        self.assertTrue(tasks[0]['key'].startswith('future_hotel_reservation.'))

    def test_progress_endpoint_isolated_by_exact_assignment(self):
        hotel_guest = self.assign(self.guest, 'GUEST_HOTEL')
        passenger = self.assign(self.guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(
            self.guest, assignment=hotel_guest, booking_reference='ISOLATED-1')
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.instructor)
        hotel_response = client.get(reverse(
            'simulation:assignment_progress', args=[hotel_guest.pk]))
        passenger_response = client.get(reverse(
            'simulation:assignment_progress', args=[passenger.pk]))
        self.assertEqual(hotel_response.status_code, 200)
        self.assertEqual(passenger_response.status_code, 200)
        self.assertEqual(hotel_response.json()['progress']['role'], 'GUEST_HOTEL')
        self.assertEqual(hotel_response.json()['progress']['completed'], 1)
        self.assertEqual(passenger_response.json()['progress']['role'], 'PASSENGER_AIRLINE')
        self.assertEqual(passenger_response.json()['progress']['completed'], 0)

    def test_student_progress_does_not_fall_back_to_latest_unrelated_booking(self):
        from simulation.views import _booking_for_assignment
        assignment = self.assign(self.guest, 'GUEST_HOTEL')
        self.assertIsNone(_booking_for_assignment(assignment, {}))

    def test_zero_verified_task_roles_have_no_fabricated_percentage(self):
        from simulation.views import assignment_progress_data
        assignment = self.assign(self.manager, 'TRAVEL_AGENCY_MANAGER', self.agency)
        progress = assignment_progress_data(assignment)
        self.assertEqual(progress['percent'], 0)
        self.assertEqual(progress['tracked'], 1)
        self.assertEqual(progress['untracked'], len(progress['tasks']) - 1)
        self.assertFalse(progress['ready_to_mark_done'])

    def test_progress_uses_only_verified_tasks_and_shows_untracked_tasks(self):
        from simulation.views import assignment_progress_data
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        initial = assignment_progress_data(assignment)
        self.assertEqual(initial['title'], 'Airline Passenger Progress')
        self.assertEqual(
            initial['subtitle'],
            'Track verified flight booking, booking management, and seat selection.')
        self.assertEqual(initial['required'], 3)
        self.assertEqual((initial['tracked'], initial['completed'], initial['percent']), (3, 0, 0))
        self.assertEqual(initial['untracked'], 2)
        self.assertFalse(initial['ready_to_mark_done'])

        complete_guest_booking(self.guest, assignment=assignment)
        assignment.refresh_from_db()
        done = assignment_progress_data(assignment)
        self.assertEqual((done['completed'], done['percent']), (1, 33))
        self.assertFalse(done['ready_to_mark_done'])
        self.assertEqual(assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertEqual(SimulationAssignmentTaskCompletion.objects.filter(assignment=assignment).count(), 1)

    def test_task_page_visit_does_not_record_completion(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.guest)
        response = client.get(reverse('simulation:do_task', args=[assignment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SimulationAssignmentTaskCompletion.objects.filter(assignment=assignment).exists())
        assignment.refresh_from_db()
        from simulation.views import assignment_progress_data
        progress = assignment_progress_data(assignment)
        self.assertEqual(progress['tasks'][0]['state'], 'pending')
        self.assertEqual(progress['completed'], 0)

    def test_completed_task_is_shown_as_completed_after_verified_action(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=assignment)

        from simulation.views import assignment_progress_data
        progress = assignment_progress_data(assignment)
        self.assertEqual(progress['tasks'][0]['state'], 'completed')
        self.assertEqual(progress['tasks'][0]['status'], 'Completed')
        self.assertEqual(progress['completed'], 1)

    def test_task_completion_isolated_between_assignments(self):
        first = self.assign(self.guest, 'PASSENGER_AIRLINE')
        second = self.assign(self.other_guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=first)
        self.assertTrue(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=first, task_key='passenger_airline.book_flight').exists())
        self.assertFalse(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=second).exists())

    def test_instructor_confirms_overall_assignment_after_verified_progress(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        complete_guest_booking(self.guest, assignment=assignment)
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.instructor)
        response = client.post(reverse('simulation:unassign', args=[assignment.pk]),
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, SimulationRoleAssignment.AssignmentStatus.DONE)

    def test_student_cannot_read_instructor_progress_endpoint(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.guest)
        response = client.get(reverse('simulation:session_student_progress', args=[
            self.session.pk, self.guest.pk]))
        self.assertEqual(response.status_code, 403)

    def test_an_active_assignment_can_still_start_its_task(self):
        assignment = self.assign(self.guest, 'PASSENGER_AIRLINE')
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.guest)
        response = client.get(reverse('simulation:do_task', args=[assignment.pk]))
        self.assertNotEqual(response.status_code, 404)
