from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from establishments.models import establishment_for_instance
from hotels.models import Hotel
from simulation.models import ActivityLog, SimulationRoleAssignment

User = get_user_model()


class AssignSimulationRoleTests(TestCase):
    """The four assignment inputs are independent: the session name the
    instructor types must never imply a role, an establishment or a schedule
    (BR-083).

    Roles are the three-operational-roles model: an establishment role names the
    *specific* establishment it applies to, so the tests post an ``establishment``
    rather than a hotel.
    """

    def setUp(self):
        self.instructor = User.objects.create_user(
            'inst', password='pw', account_type=User.AccountType.INSTRUCTOR)
        self.student = User.objects.create_user(
            'john', password='pw', first_name='John', last_name='Dela Cruz',
            account_type=User.AccountType.STUDENT)
        self.hotel = Hotel.objects.create(name='ABC Grand Hotel')
        self.establishment = establishment_for_instance(self.hotel, create=True)
        self.url = reverse('simulation:assign')
        self.client.force_login(self.instructor)

    def post(self, **overrides):
        data = {
            'activity_name': 'Activity 1',
            'student': self.student.id,
            'role': SimulationRoleAssignment.Role.HOTEL_FRONT_DESK,
            'establishment': self.establishment.id,
            'simulation_date': '2026-09-26',
            'start_time': '07:00',
            'end_time': '17:00',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def assign(self, **overrides):
        self.assertEqual(self.post(**overrides).status_code, 302)
        return SimulationRoleAssignment.objects.get(student=self.student)

    # -- 1. the activity is free text, not a predefined choice ---------------

    def test_activity_name_is_free_text(self):
        for name in ('Activity 2', 'Midterm Simulation', 'Hotel Front Desk Activity',
                     'Practical Activity 1', 'Final Simulation'):
            self.assign(activity_name=name)
            self.assertEqual(SimulationRoleAssignment.objects.get(student=self.student).activity_name, name)
            SimulationRoleAssignment.objects.filter(student=self.student).delete()

    def test_blank_activity_name_is_rejected(self):
        response = self.post(activity_name='   ')
        # The form is re-rendered rather than redirected, so the student, role
        # and establishment the instructor already chose are still filled in.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Name the activity.')
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.student).exists())

    def test_predefined_general_training_is_not_forced(self):
        self.assign(activity_name='Activity 1')
        self.assertNotEqual(SimulationRoleAssignment.objects.get().activity_name, 'General Training')

    # -- 2. activity does not drive role / establishment / schedule ----------

    def test_activity_name_does_not_imply_a_role_or_establishment(self):
        a = self.assign(activity_name='Midterm Simulation',
                        role=SimulationRoleAssignment.Role.PASSENGER_AIRLINE,
                        establishment='',
                        simulation_date='', start_time='', end_time='')
        self.assertEqual(a.role, SimulationRoleAssignment.Role.PASSENGER_AIRLINE)
        self.assertIsNone(a.establishment)
        self.assertIsNone(a.simulation_date)

    def test_one_session_shared_by_students_with_own_roles(self):
        second = User.objects.create_user('maria', password='pw', first_name='Maria',
                                          last_name='Santos',
                                          account_type=User.AccountType.STUDENT)
        self.assign(activity_name='Activity 1')
        self.client.post(self.url, {
            'activity_name': 'Activity 1', 'student': second.id,
            'role': SimulationRoleAssignment.Role.HOTEL_RESERVATION_OFFICER,
            'establishment': self.establishment.id,
        })
        shared = SimulationRoleAssignment.objects.filter(activity_name='Activity 1')
        self.assertEqual(shared.count(), 2)
        self.assertEqual(
            shared.filter(role=SimulationRoleAssignment.Role.HOTEL_FRONT_DESK).count(), 1)
        self.assertEqual(
            shared.filter(role=SimulationRoleAssignment.Role.HOTEL_RESERVATION_OFFICER).count(), 1)

    # -- 3. an operational role always names its establishment -----------------

    def test_establishment_role_requires_an_establishment(self):
        self.post(role=SimulationRoleAssignment.Role.HOTEL_FRONT_DESK, establishment='')
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.student).exists())

    def test_customer_role_needs_no_establishment(self):
        a = self.assign(role=SimulationRoleAssignment.Role.PASSENGER_AIRLINE, establishment='')
        self.assertIsNone(a.establishment)
        self.assertFalse(a.establishment_required)

    def test_the_three_operational_roles_all_require_an_establishment(self):
        for code in (SimulationRoleAssignment.Role.HOTEL_MANAGER,
                     SimulationRoleAssignment.Role.HOTEL_RESERVATION_OFFICER,
                     SimulationRoleAssignment.Role.HOTEL_FRONT_DESK):
            self.post(role=code, establishment='', activity_name=f'Activity {code}')
            self.assertFalse(
                SimulationRoleAssignment.objects.filter(
                    student=self.student, role=code).exists(),
                f'{code} must not be assignable without an establishment',
            )

    def test_an_establishment_of_the_wrong_type_is_refused(self):
        from airlines.models import Airline

        airline = Airline.objects.create(name='Cebu Pacific')
        airline_establishment = establishment_for_instance(airline, create=True)
        self.post(role=SimulationRoleAssignment.Role.HOTEL_FRONT_DESK,
                  establishment=airline_establishment.id)
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.student).exists())

    def test_the_establishment_is_stored_and_mirrors_its_type(self):
        a = self.assign()
        self.assertEqual(a.establishment_id, self.establishment.id)
        self.assertEqual(a.establishment_type, 'HOTEL')
        self.assertTrue(a.establishment_required)
        # The legacy hotel column is kept in step for the older templates.
        self.assertEqual(a.hotel_id, self.hotel.pk)

    # -- 4. schedule ----------------------------------------------------------

    def test_schedule_is_stored(self):
        a = self.assign()
        self.assertEqual(str(a.simulation_date), '2026-09-26')
        self.assertEqual(a.start_time.strftime('%H:%M'), '07:00')
        self.assertEqual(a.end_time.strftime('%H:%M'), '17:00')

    def test_schedule_is_optional(self):
        a = self.assign(simulation_date='', start_time='', end_time='')
        self.assertIsNone(a.simulation_date)
        self.assertIsNone(a.start_time)

    def test_partial_schedule_is_rejected(self):
        self.post(simulation_date='2026-09-26', start_time='', end_time='')
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.student).exists())

    def test_end_before_start_is_rejected(self):
        self.post(start_time='17:00', end_time='07:00')
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.student).exists())

    # -- 5. one active session per role, unless the admin overrides ----------

    def test_duplicate_role_for_same_student_is_still_blocked(self):
        self.assign()
        self.post(activity_name='Activity 2')
        self.assertEqual(SimulationRoleAssignment.objects.filter(student=self.student).count(), 1)

    def test_finished_assignment_does_not_block_the_role_again(self):
        self.assign()
        self.post(activity_name='Activity 2')
        SimulationRoleAssignment.objects.update(
            status=SimulationRoleAssignment.AssignmentStatus.INACTIVE)
        self.post(activity_name='Activity 3')
        self.assertEqual(
            SimulationRoleAssignment.objects.filter(
                student=self.student,
                role=SimulationRoleAssignment.Role.HOTEL_FRONT_DESK).count(), 2)

    def test_admin_can_explicitly_assign_the_same_role_again(self):
        self.assign()
        self.post(activity_name='Activity 2', assign_again='yes')
        live = SimulationRoleAssignment.objects.filter(
            student=self.student, role=SimulationRoleAssignment.Role.HOTEL_FRONT_DESK)
        self.assertEqual(live.count(), 2)
        self.assertEqual(
            sorted(live.values_list('activity_name', flat=True)),
            ['Activity 1', 'Activity 2'])

    def test_explicit_repeat_is_recorded_in_the_activity_log(self):
        self.assign()
        self.post(activity_name='Activity 2', assign_again='yes')
        actions = list(ActivityLog.objects.values_list('action', flat=True))
        self.assertIn('Re-assigned an already active role', actions)
        detail = ActivityLog.objects.get(action='Re-assigned an already active role').details
        self.assertIn('Activity 1', detail)
        self.assertIn('Activity 2', detail)

    def test_override_does_not_apply_to_a_different_role(self):
        self.assign()
        self.post(role=SimulationRoleAssignment.Role.PASSENGER_AIRLINE, establishment='',
                  activity_name='Activity 2', assign_again='yes')
        self.assertEqual(SimulationRoleAssignment.objects.filter(student=self.student).count(), 2)

    def test_a_retired_role_is_no_longer_assignable(self):
        self.post(role=SimulationRoleAssignment.Role.RECEPTIONIST,
                  establishment=self.establishment.id)
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.student).exists())

    def test_assign_form_offers_the_repeat_override(self):
        self.client.force_login(self.instructor)
        response = self.client.get(self.url)
        self.assertContains(response, 'name="assign_again"')
        self.assertContains(response, 'Assign this role again')

    def test_non_instructor_cannot_assign(self):
        self.client.force_login(self.student)
        response = self.client.post(self.url, {
            'activity_name': 'Activity 1', 'student': self.student.id,
            'role': SimulationRoleAssignment.Role.HOTEL_FRONT_DESK,
            'establishment': self.establishment.id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SimulationRoleAssignment.objects.exists())

    def test_assign_page_offers_the_establishment_picker(self):
        self.client.force_login(self.instructor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="activity_name"')
        self.assertNotContains(response, 'value="General Training"')
        self.assertContains(response, 'name="establishment"')
        self.assertContains(response, self.hotel.name)
        self.assertContains(response, SimulationRoleAssignment.Role.HOTEL_FRONT_DESK)

    def test_assign_page_offers_only_the_three_operational_roles_per_establishment(self):
        self.client.force_login(self.instructor)
        response = self.client.get(self.url)
        for code in ('HOTEL_MANAGER', 'HOTEL_RESERVATION_OFFICER', 'HOTEL_FRONT_DESK',
                     'AIRLINE_MANAGER', 'AIRLINE_RESERVATION_AGENT', 'AIRLINE_FRONT_DESK',
                     'TRANSPORT_MANAGER', 'TRANSPORT_RESERVATION_AGENT', 'TRANSPORT_FRONT_DESK',
                     'TOUR_OPERATOR_MANAGER', 'TOUR_RESERVATION_AGENT', 'TOUR_FRONT_DESK',
                     'ACTIVITY_RESERVATION_OFFICER', 'ACTIVITY_OPERATOR',
                     'TOUR_PACKAGE_MANAGER', 'TOUR_PACKAGE_RESERVATION_OFFICER',
                     'TOUR_PACKAGE_FRONT_DESK_OFFICER'):
            self.assertContains(response, code)
        # Roles folded into the three must not be offered.
        for retired in ('RECEPTIONIST', 'HOUSEKEEPING_OFFICER', 'AIRLINE_TICKETING_OFFICER',
                        'HOTEL_BILLING_OFFICER', 'CONCIERGE',
                        'ACTIVITY_MANAGER', 'ACTIVITY_FRONT_DESK_OFFICER',
                        'TOUR_PACKAGE_OPERATOR'):
            self.assertNotContains(response, f'value="{retired}"')
