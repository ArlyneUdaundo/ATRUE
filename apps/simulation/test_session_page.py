"""The session page lists the class and each row saves through the modal.

The instructor's session page is a roster: every student appears in each
expanded session, with an "Assign Role" button when they hold nothing there and
an "Edit Assignment" button when they do. Both post to ``session_assignment``,
which is the AJAX twin of the standalone assign form and must not become a way
around its rules (live catalogue, role/establishment agreement, schedule window,
one active role per student).
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from simulation.models import SimulationRoleAssignment, SimulationSession
from simulation.test_assignment_flow import AssignmentFlowTestCase

User = get_user_model()
Role = SimulationRoleAssignment.Role


class SessionPageRosterTests(AssignmentFlowTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor)
        self.session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor)

    def test_every_student_gets_a_row_with_assign_or_edit(self):
        self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Activity 1', session=self.session)

        response = self.client.get(reverse('simulation:workspace'))

        self.assertContains(response, 'Arlyne Joy Udaundo')
        self.assertContains(response, 'Angela Mae Cruz')
        self.assertContains(response, 'John Cruz')
        self.assertContains(response, 'No role assigned')
        self.assertContains(response, 'Edit Assignment')
        self.assertContains(response, 'Assign Role')
        self.assertContains(response, '3 students')
        # The assign action is a button on the row, never a bare link.
        self.assertNotContains(response, '>Assign Role</a>')

    def test_session_with_one_assignment_still_gives_the_count(self):
        self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            session=self.session)
        response = self.client.get(reverse('simulation:workspace'))
        self.assertContains(response, 'Session 1')
        self.assertContains(response, '3 students')

    def test_instructor_session_roster_opens_in_a_modal(self):
        self.session.start_date = '2026-10-12'
        self.session.end_date = '2026-10-14'
        self.session.save(update_fields=['start_date', 'end_date'])

        response = self.client.get(reverse('simulation:workspace'))

        self.assertContains(response, 'id="sessionStudentModal"')
        self.assertContains(response, 'role="dialog" aria-modal="true"')
        self.assertContains(response, 'data-session-open')
        self.assertContains(response, 'data-session-start="Oct 12, 2026"')
        self.assertContains(response, 'data-session-end="Oct 14, 2026"')
        self.assertContains(response, 'id="assignmentModal"')
        self.assertNotContains(
            response,
            '<details class="simulation-session simulation-session--modal" open>',
        )

    def test_the_modal_exposes_the_live_role_catalogue(self):
        response = self.client.get(reverse('simulation:workspace'))
        self.assertContains(response, f'value="{Role.HOTEL_FRONT_DESK}"')
        self.assertContains(response, f'value="{Role.PASSENGER_AIRLINE}"')
        # A role retired from the catalogue is not offered by the modal either.
        self.assertNotContains(response, f'value="{Role.RECEPTIONIST}"')


class StudentSessionPageTests(AssignmentFlowTestCase):
    """The roster and Assign Role modal belong to the instructor account only.

    The student keeps the original session page: their own role cards and the
    "Do the Task" entry point into the operations flow. Assigning a role only
    records the instructor's decision; it must never hand the student the
    instructor's roster or modal.
    """

    def setUp(self):
        super().setUp()
        self.session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor)
        self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Session 1', session=self.session)
        self.client.force_login(self.arlyne)

    def test_student_keeps_the_do_the_task_flow(self):
        response = self.client.get(reverse('simulation:workspace'))

        self.assertContains(response, 'My Roles')
        self.assertContains(response, 'Do the Task')

    def test_student_never_sees_the_assign_modal_or_roster(self):
        response = self.client.get(reverse('simulation:workspace'))

        self.assertNotContains(response, 'id="assignmentModal"')
        self.assertNotContains(response, 'simulation-student-row')
        self.assertNotContains(response, 'Edit Assignment')


class SessionAssignmentEndpointTests(AssignmentFlowTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor)
        self.session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor)
        self.url = reverse('simulation:session_assignment', args=[self.session.pk])

    def post(self, **overrides):
        data = {
            'student': self.arlyne.pk,
            'role': Role.HOTEL_FRONT_DESK,
            'establishment': self.sunrise_est.pk,
            'simulation_date': '2026-09-26',
            'start_time': '07:00',
            'end_time': '17:00',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_a_row_can_assign_a_student(self):
        response = self.post()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['action'], 'assign')

        assignment = SimulationRoleAssignment.objects.get(student=self.arlyne)
        self.assertEqual(assignment.session, self.session)
        self.assertEqual(assignment.establishment_id, self.sunrise_est.pk)
        self.assertEqual(assignment.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertEqual(payload['assignment']['id'], assignment.pk)
        self.assertEqual(payload['assignment']['role_display'], 'Hotel Front Desk Officer')
        self.assertEqual(payload['assignment']['establishment'], 'Sunrise Hotel')

    def test_a_row_can_edit_its_assignment_and_schedule(self):
        assignment = self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Activity 1', session=self.session)

        response = self.post(
            assignment_id=assignment.pk,
            role=Role.HOTEL_RESERVATION_OFFICER,
            simulation_date='2026-10-01',
            start_time='08:00',
            end_time='12:00',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        assignment.refresh_from_db()
        self.assertEqual(assignment.role, Role.HOTEL_RESERVATION_OFFICER)
        self.assertEqual(assignment.establishment_id, self.sunrise_est.pk)
        self.assertEqual(assignment.simulation_date.isoformat(), '2026-10-01')
        self.assertEqual(assignment.start_time.strftime('%H:%M'), '08:00')

    def test_an_operational_role_still_needs_an_establishment(self):
        response = self.post(establishment='')
        self.assertEqual(response.status_code, 400)
        self.assertIn('establishment', response.json()['errors'][0].lower())
        self.assertFalse(SimulationRoleAssignment.objects.exists())

    def test_a_customer_role_stores_no_establishment(self):
        response = self.post(role=Role.PASSENGER_AIRLINE, establishment='')
        self.assertTrue(response.json()['ok'])
        assignment = SimulationRoleAssignment.objects.get()
        self.assertIsNone(assignment.establishment_id)

    def test_a_partial_or_backwards_schedule_is_refused(self):
        for data in (
            {'simulation_date': '2026-09-26', 'start_time': '', 'end_time': ''},
            {'start_time': '17:00', 'end_time': '07:00'},
        ):
            with self.subTest(data=data):
                response = self.post(**data)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(SimulationRoleAssignment.objects.exists())

    def test_the_schedule_is_optional(self):
        response = self.post(simulation_date='', start_time='', end_time='')
        self.assertTrue(response.json()['ok'])
        assignment = SimulationRoleAssignment.objects.get()
        self.assertIsNone(assignment.simulation_date)

    def test_a_duplicate_active_role_needs_the_override(self):
        self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Elsewhere')

        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()['clash'])
        self.assertFalse(
            SimulationRoleAssignment.objects.filter(session=self.session).exists())

        response = self.post(assign_again='yes')
        self.assertTrue(response.json()['ok'])
        self.assertTrue(
            SimulationRoleAssignment.objects.filter(session=self.session).exists())

    def test_re_saving_the_row_being_edited_is_not_a_clash(self):
        assignment = self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Activity 1', session=self.session)

        response = self.post(assignment_id=assignment.pk)

        self.assertTrue(response.json()['ok'])

    def test_an_unknown_role_is_refused(self):
        response = self.post(role='NOT_A_REAL_ROLE')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SimulationRoleAssignment.objects.exists())

    def test_an_assignment_from_another_session_cannot_be_edited(self):
        other = SimulationSession.objects.create(
            name='Session 2', instructor=self.instructor)
        assignment = self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Activity 1', session=other)

        response = self.post(assignment_id=assignment.pk)

        self.assertEqual(response.status_code, 404)
        assignment.refresh_from_db()
        self.assertEqual(assignment.session, other)

    def test_only_post_is_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_a_student_cannot_save(self):
        self.client.force_login(self.arlyne)
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SimulationRoleAssignment.objects.exists())

    def test_an_instructor_who_is_not_a_manager_cannot_save_into_this_session(self):
        # An instructor is normally also a manager (and may supervise any
        # session); this staff-but-student account is the narrow case that
        # reaches the "only the session's own instructor" branch.
        other = User.objects.create_user(
            'staffstudent', password='pw', is_staff=True,
            account_type=User.AccountType.STUDENT)
        self.client.force_login(other)

        response = self.post()

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SimulationRoleAssignment.objects.exists())

    def test_a_completed_session_cannot_be_changed(self):
        self.session.status = SimulationSession.Status.COMPLETED
        self.session.save(update_fields=['status'])

        response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SimulationRoleAssignment.objects.exists())
