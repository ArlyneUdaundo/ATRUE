from datetime import date, datetime, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from establishments.models import Establishment
from simulation.models import SimulationRoleAssignment, SimulationSession
from simulation.test_assignment_flow import AssignmentFlowTestCase, Role

User = get_user_model()


class SharedSessionScheduleAccessTests(AssignmentFlowTestCase):
    """Every role in one session follows the same server-side time window."""

    session_date = date(2026, 11, 14)

    def setUp(self):
        super().setUp()
        self.session = SimulationSession.objects.create(
            name='Shared Schedule', instructor=self.instructor,
            session_date=self.session_date, start_time=time(8), end_time=time(10),
        )
        fourth_student = User.objects.create_user(
            'frontdesk', password='pw', account_type=User.AccountType.STUDENT)
        airline_student = User.objects.create_user(
            'airline_student', password='pw', account_type=User.AccountType.STUDENT)
        airline_establishment = Establishment.objects.create(
            name='Cebu Pacific', type=Establishment.Type.AIRLINE)
        self.role_assignments = [
            self.assign(self.arlyne, Role.GUEST_HOTEL, activity_name=self.session.name,
                        session=self.session),
            self.assign(self.angela, Role.HOTEL_BILLING_OFFICER, self.sunrise_est,
                        activity_name=self.session.name, session=self.session),
            self.assign(self.john, Role.HOTEL_RESERVATION_OFFICER, self.sunrise_est,
                        activity_name=self.session.name, session=self.session),
            self.assign(fourth_student, Role.HOTEL_FRONT_DESK, self.sunrise_est,
                        activity_name=self.session.name, session=self.session),
            self.assign(airline_student, Role.AIRLINE_FRONT_DESK, airline_establishment,
                        activity_name=self.session.name, session=self.session),
        ]

    def at(self, hour, minute=0):
        return timezone.make_aware(
            datetime.combine(self.session_date, time(hour, minute)),
            timezone.get_current_timezone(),
        )

    def test_roles_share_one_schedule_and_start_together_at_inclusive_boundary(self):
        for assignment in self.role_assignments:
            with self.subTest(role=assignment.role):
                self.assertEqual(assignment.session_id, self.session.pk)
                self.assertIsNone(assignment.simulation_date)
                self.assertIsNone(assignment.start_time)
                self.assertIsNone(assignment.end_time)
                self.client.force_login(assignment.student)
                with patch('django.utils.timezone.now', return_value=self.at(7, 59)):
                    before = self.client.get(
                        reverse('simulation:do_task', args=[assignment.pk]))
                self.assertEqual(before.status_code, 302)
                self.assertEqual(before.url, reverse(
                    'simulation:role_detail', args=[assignment.pk]))
                self.client.logout()

                self.client.force_login(assignment.student)
                with patch('django.utils.timezone.now', return_value=self.at(8)):
                    started = self.client.get(
                        reverse('simulation:do_task', args=[assignment.pk]))
                self.assertEqual(started.status_code, 200)
                self.client.logout()

    def test_roles_all_lose_access_at_exclusive_end_boundary(self):
        for assignment in self.role_assignments:
            with self.subTest(role=assignment.role):
                self.client.force_login(assignment.student)
                with patch('django.utils.timezone.now', return_value=self.at(9, 59)):
                    active = self.client.get(
                        reverse('simulation:do_task', args=[assignment.pk]))
                self.assertEqual(active.status_code, 200)
                with patch('django.utils.timezone.now', return_value=self.at(10)):
                    ended = self.client.get(
                        reverse('simulation:do_task', args=[assignment.pk]))
                self.assertEqual(ended.status_code, 302)
                self.assertEqual(ended.url, reverse(
                    'simulation:role_detail', args=[assignment.pk]))
                self.client.logout()

    def test_task_api_rejects_requests_after_the_shared_session_ends(self):
        assignment = self.role_assignments[3]
        self.client.force_login(assignment.student)
        with patch('django.utils.timezone.now', return_value=self.at(8)):
            self.client.get(reverse('simulation:do_task', args=[assignment.pk]))
        with patch('django.utils.timezone.now', return_value=self.at(10)):
            response = self.client.post(
                reverse('hotels:bookings'), {'action': 'confirm'},
                HTTP_ACCEPT='application/json',
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])

    def test_airline_task_routes_follow_the_same_session_boundary(self):
        assignment = self.role_assignments[-1]
        self.client.force_login(assignment.student)
        with patch('django.utils.timezone.now', return_value=self.at(8)):
            started = self.client.get(reverse('simulation:do_task', args=[assignment.pk]))
        self.assertEqual(started.status_code, 200)
        with patch('django.utils.timezone.now', return_value=self.at(10)):
            response = self.client.get(reverse('airlines:bookings'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse(
            'simulation:role_detail', args=[assignment.pk]))

    def test_instructor_schedule_change_updates_access_for_every_assignment(self):
        self.client.force_login(self.instructor)
        response = self.client.post(
            reverse('simulation:update_session', args=[self.session.pk]),
            {
                'name': self.session.name,
                'description': '',
                'session_date': self.session_date.isoformat(),
                'start_time': '09:00',
                'end_time': '11:00',
                'start_date': '',
                'end_date': '',
                'status': SimulationSession.Status.SCHEDULED,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.session.refresh_from_db()
        for assignment in self.role_assignments:
            assignment.refresh_from_db()
            self.assertEqual(assignment.session.start_time, time(9))
            self.assertEqual(assignment.session.end_time, time(11))

    def test_schedule_update_rejects_missing_or_backwards_times(self):
        self.client.force_login(self.instructor)
        for start, end in (('', '10:00'), ('10:00', '10:00'), ('11:00', '10:00')):
            with self.subTest(start=start, end=end):
                response = self.client.post(
                    reverse('simulation:update_session', args=[self.session.pk]),
                    {
                        'name': self.session.name,
                        'session_date': self.session_date.isoformat(),
                        'start_time': start,
                        'end_time': end,
                        'status': SimulationSession.Status.SCHEDULED,
                    },
                )
                self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.start_time, time(8))
        self.assertEqual(self.session.end_time, time(10))

    def test_instructor_session_creation_requires_and_stores_one_shared_schedule(self):
        self.client.force_login(self.instructor)
        url = reverse('simulation:add_session')
        invalid = self.client.post(url, {
            'name': 'Missing Schedule', 'session_date': self.session_date.isoformat(),
            'start_time': '08:00', 'end_time': '',
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(SimulationSession.objects.filter(name='Missing Schedule').exists())

        created = self.client.post(url, {
            'name': 'New Scheduled Session',
            'session_date': self.session_date.isoformat(),
            'start_time': '08:30', 'end_time': '10:30',
        })
        self.assertEqual(created.status_code, 302)
        session = SimulationSession.objects.get(name='New Scheduled Session')
        self.assertEqual(session.session_date, self.session_date)
        self.assertEqual(session.start_time, time(8, 30))
        self.assertEqual(session.end_time, time(10, 30))
