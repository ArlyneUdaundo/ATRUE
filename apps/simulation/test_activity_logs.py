"""Activity logs organized by simulation session (BR-085).

Covers the session-card list page, the session-specific log page, backend
filtering through the real ``ActivityLog.session`` relationship, RBAC and the
guarantee that reading pages never records or duplicates logs.
"""
from datetime import datetime

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from atrue_core.services import log_activity
from establishments.models import Establishment
from simulation.models import (
    ActivityLog, SimulationRoleAssignment, SimulationSession,
)


class SessionLogsBase(TestCase):
    def setUp(self):
        self.instructor = User.objects.create_user(
            'inst', password='pw', account_type=User.AccountType.INSTRUCTOR)
        self.john = User.objects.create_user(
            'john', password='pw', first_name='John', last_name='Dela Cruz',
            account_type=User.AccountType.STUDENT)
        self.maria = User.objects.create_user(
            'maria', password='pw', first_name='Maria', last_name='Santos',
            account_type=User.AccountType.STUDENT)
        self.session_a = SimulationSession.objects.create(
            name='Session Alpha', instructor=self.instructor)
        self.session_b = SimulationSession.objects.create(
            name='Session Beta', instructor=self.instructor)
        self.session_empty = SimulationSession.objects.create(
            name='Session Empty', instructor=self.instructor)
        self.est_hotel = Establishment.objects.create(
            name='ABC Grand Hotel', type='HOTEL')
        self.est_restaurant = Establishment.objects.create(
            name='Dine Well', type='RESTAURANT')

    def assign(self, student, session, role, establishment, activity='Activity 1'):
        return SimulationRoleAssignment.objects.create(
            student=student,
            assigned_by=self.instructor,
            role=role,
            activity_name=activity,
            session=session,
            establishment=establishment,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )

    def log(self, user, session, action, **kwargs):
        return ActivityLog.objects.create(
            user=user, session=session, action=action, **kwargs)


class SessionLogsListingTests(SessionLogsBase):
    """1. Sessions grouped, 2/3. per-session pages only show their own logs,
    4. multiple activities in one session, 5. empty session, 6. roles and
    establishments surface."""

    def setUp(self):
        super().setUp()
        self.assign(self.john, self.session_a,
                    SimulationRoleAssignment.Role.GUEST_HOTEL, self.est_hotel)
        self.log(self.john, self.session_a, 'Started simulation task',
                 simulation_role=SimulationRoleAssignment.Role.GUEST_HOTEL,
                 establishment=self.est_hotel)
        self.log(self.john, self.session_a, 'Payment recorded for hotel',
                 simulation_role=SimulationRoleAssignment.Role.GUEST_HOTEL,
                 establishment=self.est_hotel)
        self.assign(self.maria, self.session_b,
                    SimulationRoleAssignment.Role.RESTAURANT_GUEST,
                    self.est_restaurant)
        self.log(self.maria, self.session_b, 'Started simulation task',
                 simulation_role=SimulationRoleAssignment.Role.RESTAURANT_GUEST,
                 establishment=self.est_restaurant)
        self.client.force_login(self.instructor)

    def test_logs_page_lists_each_session_with_stats(self):
        response = self.client.get(reverse('simulation:logs'))
        self.assertEqual(response.status_code, 200)
        sessions = {s.name: s for s in response.context['sessions']}
        self.assertIn('Session Alpha', sessions)
        self.assertIn('Session Beta', sessions)
        self.assertIn('Session Empty', sessions)
        self.assertEqual(sessions['Session Alpha'].log_count, 2)
        self.assertEqual(sessions['Session Alpha'].student_count, 1)
        self.assertEqual(sessions['Session Beta'].log_count, 1)
        self.assertEqual(sessions['Session Beta'].student_count, 1)
        self.assertEqual(sessions['Session Empty'].log_count, 0)
        self.assertContains(response, 'Session Alpha')
        self.assertContains(response, 'Session Beta')

    def test_clicking_session_a_shows_only_session_a_logs(self):
        url = reverse('simulation:session_logs', args=[self.session_a.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Started simulation task')
        self.assertContains(response, 'Payment recorded for hotel')
        self.assertNotContains(response, 'B_start')
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Started simulation task', 'Payment recorded for hotel'])

    def test_clicking_session_b_shows_only_session_b_logs(self):
        url = reverse('simulation:session_logs', args=[self.session_b.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Started simulation task'])
        self.assertEqual(response.context['rows'][0]['student'], self.maria)

    def test_back_navigation_to_sessions_link_present(self):
        response = self.client.get(
            reverse('simulation:session_logs', args=[self.session_a.id]))
        self.assertContains(response, 'Activity Logs')
        self.assertContains(response, 'Back to Sessions')

    def test_session_with_no_activities_shows_empty_message(self):
        url = reverse('simulation:session_logs', args=[self.session_empty.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'No activity logs have been recorded for this session yet.')

    def test_different_roles_and_establishments_are_displayed(self):
        url = reverse('simulation:session_logs', args=[self.session_a.id])
        response = self.client.get(url)
        self.assertContains(response, 'ABC Grand Hotel')
        self.assertContains(response, 'Guest – Hotel')
        self.assertContains(response, 'Active')

        url_b = reverse('simulation:session_logs', args=[self.session_b.id])
        response_b = self.client.get(url_b)
        self.assertContains(response_b, 'Dine Well')
        self.assertContains(response_b, 'Guest – Restaurant')

    def test_newest_activities_are_displayed_first(self):
        first = self.log(self.john, self.session_a, 'Older task',
                         simulation_role=SimulationRoleAssignment.Role.GUEST_HOTEL)
        ActivityLog.objects.filter(pk=first.pk).update(
            timestamp=datetime(2025, 1, 1, 8, 0))
        url = reverse('simulation:session_logs', args=[self.session_a.id])
        response = self.client.get(url)
        actions = [r['log'].action for r in response.context['rows']]
        self.assertEqual(actions[0], 'Payment recorded for hotel')
        self.assertEqual(actions[-1], 'Older task')


class SessionLogsFilterTests(SessionLogsBase):
    """7. Search and date filters return accurate results."""

    def setUp(self):
        super().setUp()
        self.assign(self.john, self.session_a,
                    SimulationRoleAssignment.Role.GUEST_HOTEL, self.est_hotel)
        self.assign(self.maria, self.session_a,
                    SimulationRoleAssignment.Role.RESTAURANT_GUEST,
                    self.est_restaurant)
        early = self.log(
            self.john, self.session_a, 'Started simulation task',
            simulation_role=SimulationRoleAssignment.Role.GUEST_HOTEL,
            establishment=self.est_hotel)
        late = self.log(
            self.maria, self.session_a, 'Payment recorded for hotel',
            simulation_role=SimulationRoleAssignment.Role.RESTAURANT_GUEST,
            establishment=self.est_restaurant)
        ActivityLog.objects.filter(pk=early.pk).update(
            timestamp=datetime(2026, 10, 1, 9, 0))
        ActivityLog.objects.filter(pk=late.pk).update(
            timestamp=datetime(2026, 10, 5, 10, 0))
        self.client.force_login(self.instructor)
        self.url = reverse('simulation:session_logs', args=[self.session_a.id])

    def test_search_student_name(self):
        response = self.client.get(self.url, {'q': 'Maria'})
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Payment recorded for hotel'])

    def test_establishment_filter(self):
        response = self.client.get(self.url, {'establishment': self.est_hotel.id})
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Started simulation task'])

    def test_role_filter(self):
        response = self.client.get(
            self.url, {'role': SimulationRoleAssignment.Role.RESTAURANT_GUEST})
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Payment recorded for hotel'])

    def test_activity_text_filter(self):
        response = self.client.get(self.url, {'activity': 'payment'})
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Payment recorded for hotel'])

    def test_date_range_filter(self):
        response = self.client.get(
            self.url, {'from': '2026-10-02', 'to': '2026-10-31'})
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Payment recorded for hotel'])

    def test_filters_combine(self):
        response = self.client.get(
            self.url, {'q': 'John', 'role': SimulationRoleAssignment.Role.GUEST_HOTEL})
        self.assertCountEqual(
            [r['log'].action for r in response.context['rows']],
            ['Started simulation task'])


class SessionLogsAccessTests(SessionLogsBase):
    """8. Unauthorized users cannot access restricted session logs."""

    def setUp(self):
        super().setUp()
        self.assign(self.john, self.session_a,
                    SimulationRoleAssignment.Role.GUEST_HOTEL, self.est_hotel)
        self.log(self.john, self.session_a, 'Started simulation task',
                 simulation_role=SimulationRoleAssignment.Role.GUEST_HOTEL,
                 establishment=self.est_hotel)
        self.outsider = User.objects.create_user(
            'outsider', password='pw', first_name='Out', last_name='Sider',
            account_type=User.AccountType.STUDENT)
        self.url_a = reverse('simulation:session_logs', args=[self.session_a.id])

    def test_outsider_student_is_forbidden(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.url_a)
        self.assertEqual(response.status_code, 403)

    def test_student_sees_own_session_in_list_and_inside_it(self):
        self.assign(self.outsider, self.session_b,
                    SimulationRoleAssignment.Role.RESTAURANT_GUEST,
                    self.est_restaurant)
        self.log(self.outsider, self.session_b, 'Started simulation task',
                 simulation_role=SimulationRoleAssignment.Role.RESTAURANT_GUEST,
                 establishment=self.est_restaurant)
        self.client.force_login(self.outsider)
        response = self.client.get(reverse('simulation:logs'))
        names = [s.name for s in response.context['sessions']]
        self.assertIn('Session Beta', names)
        self.assertNotIn('Session Alpha', names)

        inside = self.client.get(
            reverse('simulation:session_logs', args=[self.session_b.id]))
        self.assertEqual(inside.status_code, 200)
        self.assertCountEqual(
            [r['log'].user for r in inside.context['rows']], [self.outsider])
        self.assertEqual(self.client.get(self.url_a).status_code, 403)

    def test_instructor_sees_all_sessions(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse('simulation:logs'))
        self.assertEqual(response.status_code, 200)
        names = [s.name for s in response.context['sessions']]
        self.assertIn('Session Alpha', names)
        self.assertIn('Session Beta', names)
        self.assertIn('Session Empty', names)


class SessionLogsRecordingTests(SessionLogsBase):
    """9. Existing activity recording keeps working and is never duplicated."""

    def test_log_activity_attaches_the_session_and_page_reads_do_not_duplicate(self):
        self.client.force_login(self.instructor)
        log_activity(self.instructor, 'Updated simulation session',
                     self.session_a.name, session=self.session_a)
        self.assertEqual(
            ActivityLog.objects.filter(session=self.session_a).count(), 1)

        url = reverse('simulation:session_logs', args=[self.session_a.id])
        for _ in range(2):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Updated simulation session')

        self.assertEqual(
            ActivityLog.objects.filter(session=self.session_a).count(), 1)

    def test_session_data_is_not_fabricated_by_the_listing(self):
        # A session with no logs must not invent any.
        self.client.force_login(self.instructor)
        url = reverse('simulation:session_logs', args=[self.session_empty.id])
        response = self.client.get(url)
        self.assertEqual(response.context['rows'], [])
        self.assertEqual(ActivityLog.objects.filter(
            session=self.session_empty).count(), 0)