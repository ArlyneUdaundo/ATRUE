"""Hotel guest task tracking and the redesigned sessions dashboard."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from atrue_core.services import confirm_booking, create_bill
from establishments.models import Establishment, establishment_for_instance
from hotels.models import Booking, BookingRoom, Hotel, Room
from simulation.completion import (
    record_hotel_guest_booking,
    record_hotel_guest_payment_verified,
    record_hotel_guest_reservation_confirmed,
)
from simulation.models import (
    SimulationAssignmentTaskCompletion,
    SimulationRoleAssignment,
    SimulationSession,
)
from simulation.role_catalogue import sync_role_catalogue
from simulation.task_routing import assignment_tasks_for
from transactions.models import Bill, Payment

User = get_user_model()


class HotelGuestFlowTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'hotel-instructor', password='pw',
            account_type=User.AccountType.INSTRUCTOR)
        cls.guest = User.objects.create_user(
            'hotel-guest', password='pw', account_type=User.AccountType.STUDENT)
        cls.billing = User.objects.create_user(
            'hotel-billing', password='pw', account_type=User.AccountType.STUDENT)
        cls.officer = User.objects.create_user(
            'hotel-officer', password='pw', account_type=User.AccountType.STUDENT)
        cls.other_guest = User.objects.create_user(
            'hotel-other-guest', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.session = SimulationSession.objects.create(
            name='Hotel Simulation', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE,
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=1))
        cls.hotel = Hotel.objects.create(
            name='Task Hotel', status=Hotel.Status.ACTIVE)
        cls.room = Room.objects.create(
            hotel=cls.hotel, room_number='101', room_type=Room.RoomType.DOUBLE,
            capacity_adults=2, rate=Decimal('1000.00'))
        cls.establishment = establishment_for_instance(cls.hotel, create=True)

    def setUp(self):
        self.guest_assignment = self.assign(
            self.guest, 'GUEST_HOTEL', self.establishment)
        self.billing_assignment = self.assign(
            self.billing, 'HOTEL_BILLING_OFFICER', self.establishment)
        self.officer_assignment = self.assign(
            self.officer, 'HOTEL_RESERVATION_OFFICER', self.establishment)
        self.booking = self._make_booking(self.guest)
        self.bill = self._make_bill(self.booking)

    def assign(self, student, role_code, establishment=None):
        return SimulationRoleAssignment.objects.create(
            student=student, assigned_by=self.instructor, role=role_code,
            activity_name=self.session.name, session=self.session,
            establishment=establishment)

    def _make_booking(self, customer):
        booking = Booking.objects.create(customer=customer)
        BookingRoom.objects.create(
            booking=booking, room=self.room,
            check_in=date.today(), check_out=date.today() + timedelta(days=1),
            number_of_adults=1)
        return booking

    def _make_bill(self, booking):
        return create_bill(
            service='HOTEL', customer=booking.customer, booking=booking,
            items=[{'label': 'Room', 'quantity': 1,
                    'rate': Decimal('1000.00'), 'amount': Decimal('1000.00')}])

    def _payment(self, status=Payment.Status.PENDING):
        return Payment.objects.create(
            bill=self.bill, customer=self.guest, amount=Decimal('1000.00'),
            method='GCASH', status=status)

    def _events(self, assignment=None):
        return set(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=assignment or self.guest_assignment,
        ).values_list('completion_event', flat=True))

    def _confirm_payment(self, payment, action='confirm_payment'):
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.billing)
        session = client.session
        session['active_simulation_task_assignment'] = self.billing_assignment.pk
        session.save()
        return client.post(
            reverse('transactions:payment_review'),
            {'payment_id': payment.pk, 'action': action})

    def _complete_tasks(self, count):
        tasks = assignment_tasks_for(self.guest_assignment)[:count]
        for task in tasks:
            SimulationAssignmentTaskCompletion.objects.create(
                assignment=self.guest_assignment,
                task_key=task['key'],
                task_label=task['label'],
                completion_event=task['completion_events'][0],
                booking_reference=(
                    self.booking.booking_reference if count >= 3 else ''),
            )

    def _progress(self):
        from simulation.views import assignment_progress_data
        return assignment_progress_data(self.guest_assignment)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class HotelGuestTaskTests(HotelGuestFlowTestCase):

    def test_guest_role_has_five_verified_workflow_tasks(self):
        tasks = assignment_tasks_for(self.guest_assignment)
        self.assertEqual([task['label'] for task in tasks], [
            'Select a hotel room',
            'Complete guest information',
            'Submit booking request',
            'Payment verification by Billing Officer',
            'Reservation confirmation',
        ])
        self.assertEqual([task['key'] for task in tasks], [
            'hotel_guest.select_room',
            'hotel_guest.guest_information',
            'hotel_guest.submit_booking',
            'hotel_guest.payment_verification',
            'hotel_guest.reservation_confirmation',
        ])
        self.assertTrue(all(task['completion_events'] for task in tasks))

    def test_guest_tasks_include_required_descriptions(self):
        tasks = assignment_tasks_for(self.guest_assignment)
        self.assertEqual([task['description'] for task in tasks], [
            'Choose an available room and confirm the selection.',
            'Enter the required guest details.',
            'Send the booking request to the hotel.',
            'Wait for the Billing Officer to confirm the payment.',
            'Ensure the booking is fully confirmed.',
        ])

    def test_progress_reports_twenty_percent_after_room_selection(self):
        self._complete_tasks(1)
        progress = self._progress()
        self.assertEqual(progress['title'], 'Hotel Booking Progress')
        self.assertEqual((progress['completed'], progress['percent']), (1, 20))
        self.assertEqual(progress['state'], 'in_progress')
        self.assertEqual(progress['tasks'][0]['state'], 'completed')
        self.assertEqual(progress['tasks'][1]['state'], 'pending')

    def test_progress_reports_forty_percent_after_guest_information(self):
        self._complete_tasks(2)
        progress = self._progress()
        self.assertEqual((progress['completed'], progress['percent']), (2, 40))
        self.assertEqual(progress['state'], 'in_progress')
        self.assertEqual(progress['tasks'][1]['state'], 'completed')
        self.assertEqual(progress['tasks'][2]['state'], 'pending')

    def test_progress_reports_sixty_percent_after_booking_submission(self):
        self._complete_tasks(3)
        progress = self._progress()
        self.assertEqual((progress['completed'], progress['percent']), (3, 60))
        self.assertEqual(progress['tasks'][2]['state'], 'completed')
        self.assertEqual(progress['tasks'][3]['state'], 'pending')
        self.assertEqual(progress['tasks'][4]['state'], 'pending')

    def test_pending_payment_shows_awaiting_confirmation_at_sixty_percent(self):
        self._complete_tasks(3)
        self._payment()
        progress = self._progress()
        self.assertEqual((progress['completed'], progress['percent']), (3, 60))
        self.assertEqual(progress['state'], 'awaiting')
        self.assertEqual(progress['tasks'][3]['state'], 'awaiting')
        self.assertEqual(
            progress['tasks'][3]['status'], 'Awaiting Confirmation')
        self.assertIn('Billing Officer', progress['awaiting_message'])

    def test_payment_verification_does_not_infer_reservation_confirmation(self):
        self._complete_tasks(3)
        payment = self._payment()
        self._confirm_payment(payment)
        progress = self._progress()
        self.assertEqual((progress['completed'], progress['percent']), (4, 80))
        self.assertEqual(progress['tasks'][3]['state'], 'completed')
        self.assertEqual(progress['tasks'][4]['state'], 'pending')

    def test_all_verified_tasks_report_one_hundred_percent(self):
        self._complete_tasks(3)
        record_hotel_guest_payment_verified(
            self.booking, session=self.session, actor=self.billing)
        record_hotel_guest_reservation_confirmed(
            self.booking, session=self.session, actor=self.officer)
        progress = self._progress()
        self.assertEqual((progress['completed'], progress['percent']), (5, 100))
        self.assertEqual(progress['state'], 'complete')
        self.assertTrue(progress['is_complete'])
        self.assertTrue(progress['ready_to_mark_done'])
        self.assertIn('instructor review', progress['success_message'])

    def test_marked_done_assignment_reports_one_hundred_percent(self):
        self._complete_tasks(3)
        record_hotel_guest_payment_verified(
            self.booking, session=self.session, actor=self.billing)
        record_hotel_guest_reservation_confirmed(
            self.booking, session=self.session, actor=self.officer)
        SimulationRoleAssignment.objects.filter(
            pk=self.guest_assignment.pk).update(
                status=SimulationRoleAssignment.AssignmentStatus.DONE,
                completed_at=timezone.now())
        self.guest_assignment.refresh_from_db()
        progress = self._progress()
        self.assertEqual((progress['completed'], progress['percent']), (5, 100))
        self.assertEqual(progress['state'], 'done')
        self.assertFalse(progress['ready_to_mark_done'])
        self.assertIn('marked this role', progress['success_message'])

    def test_saved_booking_records_submission_only(self):
        record_hotel_guest_booking(
            self.guest, self.booking, assignment=self.guest_assignment)
        self.assertEqual(self._events(), {'CUSTOMER_BOOKING_SUBMITTED'})
        self.guest_assignment.refresh_from_db()
        self.assertEqual(
            self.guest_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertEqual(
            SimulationAssignmentTaskCompletion.objects.filter(
                assignment=self.guest_assignment,
                booking_reference=self.booking.booking_reference,
            ).count(),
            1)

    def test_booking_tasks_are_isolated_between_assignments(self):
        other = self.assign(self.other_guest, 'GUEST_HOTEL', self.establishment)
        record_hotel_guest_booking(
            self.guest, self.booking, assignment=self.guest_assignment)
        self.assertEqual(len(self._events()), 1)
        self.assertFalse(SimulationAssignmentTaskCompletion.objects.filter(
            assignment=other).exists())

    def test_rejected_payment_does_not_complete_verification(self):
        record_hotel_guest_booking(
            self.guest, self.booking, assignment=self.guest_assignment)
        payment = self._payment()
        self._confirm_payment(payment, action='reject_payment')
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertNotIn('PAYMENT_VERIFIED', self._events())

    def test_full_payment_then_reservation_confirmation_complete_last_two_tasks(self):
        record_hotel_guest_booking(
            self.guest, self.booking, assignment=self.guest_assignment)
        payment = self._payment()
        response = self._confirm_payment(payment)
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.bill.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertIsNotNone(self.bill.verified_at)
        self.assertIn('PAYMENT_VERIFIED', self._events())
        self.assertNotIn('RESERVATION_CONFIRMED', self._events())
        self.assertEqual(self.booking.status, Booking.Status.PENDING)

        confirm_booking(self.booking, self.officer, notify=False)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertIn('RESERVATION_CONFIRMED', self._events())
        self.guest_assignment.refresh_from_db()
        self.assertEqual(
            self.guest_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.ACTIVE)

    def test_instructor_marks_done_after_all_verified_tasks(self):
        record_hotel_guest_booking(
            self.guest, self.booking, assignment=self.guest_assignment)
        record_hotel_guest_payment_verified(
            self.booking, session=self.session, actor=self.billing)
        record_hotel_guest_reservation_confirmed(
            self.booking, session=self.session, actor=self.officer)
        from simulation.views import assignment_progress_data
        progress = assignment_progress_data(self.guest_assignment)
        self.assertEqual((progress['completed'], progress['tracked'],
                          progress['percent']), (3, 5, 60))
        self.assertFalse(progress['ready_to_mark_done'])

        client = Client(SERVER_NAME='localhost')
        client.force_login(self.instructor)
        response = client.post(
            reverse('simulation:unassign', args=[self.guest_assignment.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.guest_assignment.refresh_from_db()
        self.assertEqual(
            self.guest_assignment.status,
            SimulationRoleAssignment.AssignmentStatus.DONE)

    def test_modal_shows_ready_to_mark_done_after_full_completion(self):
        record_hotel_guest_booking(
            self.guest, self.booking, assignment=self.guest_assignment)
        record_hotel_guest_payment_verified(
            self.booking, session=self.session, actor=self.billing)
        record_hotel_guest_reservation_confirmed(
            self.booking, session=self.session, actor=self.officer)
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.instructor)
        response = client.get(reverse('simulation:workspace'))
        self.assertContains(response, 'Hotel Booking Progress')
        self.assertContains(response, 'Task is finished and verified.')
        self.assertNotContains(response, 'Task is currently being done.')
        self.assertContains(
            response, 'Waiting for another role (e.g., Billing Officer).')
        self.assertContains(response, 'No verified completion has been recorded yet.')
        self.assertContains(
            response,
            'Progress is based on actual verified task completion records, '
            'not just page visits.')


class SessionsDashboardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        sync_role_catalogue()
        cls.instructor = User.objects.create_user(
            'dashboard-instructor', password='pw',
            account_type=User.AccountType.INSTRUCTOR)
        cls.student = User.objects.create_user(
            'dashboard-student', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.active = SimulationSession.objects.create(
            name='Active Session', instructor=cls.instructor,
            status=SimulationSession.Status.ACTIVE)
        cls.draft = SimulationSession.objects.create(
            name='Draft Session', instructor=cls.instructor,
            status=SimulationSession.Status.DRAFT)

    def setUp(self):
        SimulationRoleAssignment.objects.create(
            student=self.student, assigned_by=self.instructor,
            role='HOTEL_RESERVATION_OFFICER', activity_name=self.active.name,
            session=self.active,
            establishment=Establishment.objects.create(
                name='Dashboard Hotel', type=Establishment.Type.HOTEL))

    def test_dashboard_uses_actual_counts_and_filters(self):
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.instructor)
        response = client.get(reverse('simulation:workspace'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['total_sessions'], 2)
        self.assertEqual(response.context['summary']['active_sessions'], 1)
        self.assertEqual(response.context['summary']['draft_sessions'], 1)
        self.assertEqual(response.context['summary']['total_students'], 1)

        filtered = client.get(reverse('simulation:workspace'), {'status': 'DRAFT'})
        names = [session.name for session in filtered.context['sessions']]
        self.assertEqual(names, ['Draft Session'])

        searched = client.get(reverse('simulation:workspace'), {'q': 'Active'})
        names = [session.name for session in searched.context['sessions']]
        self.assertEqual(names, ['Active Session'])

    def test_session_card_counts_assigned_students_not_the_whole_roster(self):
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.instructor)
        response = client.get(
            reverse('simulation:workspace'), {'q': 'Active Session'})
        session = response.context['sessions'][0]
        self.assertEqual(session.assigned_student_count, 1)
        self.assertEqual(session.completed_student_count, 0)
        self.assertEqual(session.student_progress_percent, 0)

    def test_dashboard_exposes_specified_heading_toolbar_and_summary_cards(self):
        client = Client(SERVER_NAME='localhost')
        client.force_login(self.instructor)
        response = client.get(reverse('simulation:workspace'))
        self.assertContains(
            response,
            'Manage and monitor all simulation sessions, student assignments, '
            'and role activities.')
        self.assertContains(
            response,
            'placeholder="Search sessions by name, code, or instructor..."')
        self.assertContains(response, 'All Statuses')
        for modifier in ('blue', 'green', 'purple', 'orange'):
            self.assertContains(response, f'sim-summary-card--{modifier}')
