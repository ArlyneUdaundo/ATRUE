"""The instructor assigns a role, the student works it, the backend holds the line.

Roles are the three operational roles of an establishment (Manager, Reservation,
Front Desk) plus Passenger. Every operational role names *one* establishment, and
these tests hold both halves of that rule together: the assign and edit forms offer
exactly that, and the pages behind them refuse everything outside it.

The hotel family is used for the detailed boundary tests because it is the
establishment whose isolation is enforced through its own mirror column
(``hotel``, written by ``SimulationRoleAssignment.save``) and read by
``atrue_core.hotel_scope``; the airline family covers a role that is allowlisted
rather than given a whole module.
"""

from datetime import date, timedelta
from decimal import Decimal
import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from atrue_core.context_processors import _location_tree_cached
from airlines.models import Airline, Flight
from airlines.tests import make_aircraft, make_airline
from establishments.models import Establishment, establishment_for_instance
from hotels.models import Booking, BookingRoom, Hotel, Room
from locations.models import CityMunicipality, Country, Province, Region
from simulation.models import Role as RoleModel
from simulation.models import SimulationRoleAssignment, SimulationSession
from simulation.role_catalogue import ROLE_CATALOGUE
from simulation.task_routing import _OPERATIONS, _RESTAURANT_OPERATIONS, task_operation_for
from staycations.models import Staycation

User = get_user_model()
#: ``Role.X`` reads better than ``RoleModel.X`` when naming a role code, and the
#: codes are the vocabulary both the form and the view speak.
Role = SimulationRoleAssignment.Role


class AssignmentFlowTestCase(TestCase):
    """Two hotels and a tour operator, a Front Desk student, an instructor."""

    @classmethod
    def setUpTestData(cls):
        # Hotel forms validate province/municipality against the canonical
        # location tree, and that tree is cached process-wide, so this fixture
        # seeds a real pair and the cache is dropped per test (same pattern as
        # hotels.tests.HotelCountryTests).
        country = Country.objects.create(
            geoname_id=1694008, code='PH', name='Philippines',
            asciiname='Republic of the Philippines',
            latitude=13.40882, longitude=122.56155, feature_code='PCLI',
        )
        region = Region.objects.create(geoname_id=7521301, code='07', name='Central Visayas', country=country)
        province = Province.objects.create(geoname_id=1695021, code='40', name='Cebu', region=region)
        CityMunicipality.objects.create(
            geoname_id=1695044, code='063070000', name='Cebu City', province=province)

        cls.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        cls.sunrise = Hotel.objects.create(
            name='Sunrise Hotel', country='Philippines',
            province='Cebu', municipality='Cebu City')
        cls.grand = Hotel.objects.create(
            name='Grand Hotel', country='Philippines',
            province='Cebu', municipality='Cebu City')

        cls.sunrise_room = Room.objects.create(
            hotel=cls.sunrise, room_number='101', room_type=Room.RoomType.DELUXE, rate=2500)
        cls.grand_room = Room.objects.create(
            hotel=cls.grand, room_number='201', room_type=Room.RoomType.DELUXE, rate=3100)

        # The shared establishment wrapper for each hotel, created the same way
        # the application does so the assignment points at the same row.
        cls.sunrise_est = establishment_for_instance(cls.sunrise, create=True)
        cls.grand_est = establishment_for_instance(cls.grand, create=True)
        cls.tour_est = Establishment.objects.create(
            name='Cebu Trails Tour Operator', type=Establishment.Type.TOUR_OPERATOR)

        # A per-resource activity and tour package: each has its own wrapper from
        # the auto-establish signal, so the per-resource roles can be assigned.
        from activities.models import Activity, ActivityProvider
        from tour_package.models import TourPackage

        provider = ActivityProvider.objects.create(
            name='Cebu Trails Provider', location='Cebu')
        cls.activity = Activity.objects.create(
            name='Cebu Trails Canyoneering', provider=provider, fee=500)
        cls.activity_est = establishment_for_instance(cls.activity)
        cls.package = TourPackage.objects.create(name='Cebu City Tour', price=2000)
        cls.package_est = establishment_for_instance(cls.package)

        cls.arlyne = User.objects.create_user(
            'arlyne', password='pw', first_name='Arlyne', middle_name='Joy',
            last_name='Udaundo', account_type=User.AccountType.STUDENT)
        cls.angela = User.objects.create_user(
            'angela', password='pw', first_name='Angela', middle_name='Mae',
            last_name='Cruz', account_type=User.AccountType.STUDENT)
        cls.john = User.objects.create_user(
            'john', password='pw', first_name='John', last_name='Cruz',
            account_type=User.AccountType.STUDENT)

    def setUp(self):
        # Another app's test may have primed this cache with a different tree.
        _location_tree_cached.cache_clear()
        self.addCleanup(_location_tree_cached.cache_clear)

    def assign(self, student, role, establishment=None, activity_name='Activity 1', **extra):
        """Assign a role, mirroring the assign form's own fields."""
        return SimulationRoleAssignment.objects.create(
            student=student, assigned_by=self.instructor, role=role,
            establishment=establishment, activity_name=activity_name, **extra)

    def book(self, hotel, room, customer):
        booking = Booking.objects.create(customer=customer)
        BookingRoom.objects.create(
            booking=booking, room=room, check_in=date.today(),
            check_out=date.today() + timedelta(days=2), number_of_adults=1)
        return booking


class TaskOperationsRouteTests(TestCase):
    """Every displayed operation points to an existing route it authorizes."""

    def test_each_establishment_type_has_operations_and_clickable_routes(self):
        self.assertEqual(set(_OPERATIONS), set(RoleModel.EstablishmentType.values))
        operations = [
            operation
            for role_operations in _OPERATIONS.values()
            for operation in role_operations.values()
        ]
        operations.append(_RESTAURANT_OPERATIONS)
        for operation in operations:
            self.assertTrue(operation['tasks'])
            for task in operation['tasks']:
                self.assertIn(task['route'], operation['allowed_routes'])
                self.assertTrue(
                    reverse(task['route']),
                    f"{task['label']} does not resolve: {task['route']}",
                )

    def test_every_establishment_roles_share_one_operation(self):
        """An establishment's operational roles are views of one job.

        Most establishments field a Manager, Reservation Officer and Front
        Desk; an Activity or Tour Package fields just a Reservation Officer
        and an Operator (the Operator is its Front Desk), because the Manager
        authority sits with the parent Tour Operator. Either way the roles
        keep one operation: the same label, and every task a non-manager role
        offers is a task the Manager - when there is one - is also allowed to
        open. That keeps "three roles" (or two) from turning into several
        dashboards.
        """
        for establishment_type, role_operations in _OPERATIONS.items():
            with self.subTest(establishment_type=establishment_type):
                active = [
                    code for code, _label, _category, est_type, _op, _order
                    in ROLE_CATALOGUE
                    if est_type == establishment_type
                ]
                self.assertGreaterEqual(len(active), 2, active)
                labels = set()
                manager_routes = None
                for code in active:
                    with self.subTest(role=code):
                        self.assertIn(code, role_operations)
                        operation = role_operations[code]
                        labels.add(operation['label'])
                        routes = {task['route'] for task in operation['tasks']}
                        if code.endswith('MANAGER'):
                            manager_routes = routes
                        else:
                            self.assertTrue(
                                routes,
                                f'{code} has no tasks, so "Do the Task" opens '
                                'an empty screen')
                self.assertEqual(
                    len(labels), 1,
                    f'{establishment_type}: the roles are views of one '
                    f'operation but got {sorted(labels)}')
                if manager_routes is not None and establishment_type != RoleModel.EstablishmentType.TOUR_PACKAGE:
                    for code in active:
                        if code.endswith('MANAGER'):
                            continue
                        with self.subTest(role=code):
                            self.assertLessEqual(
                                {task['route'] for task in role_operations[code]['tasks']},
                                manager_routes,
                                f'{code} offers a task its manager cannot open')


class AssignFormJavaScriptPayloadTests(AssignmentFlowTestCase):
    """The browser-side contract of the assign form.

    A previous version of this form passed pre-serialised JSON strings into
    ``json_script``, which encodes them a second time. The page then parsed a
    ``str`` instead of a list/dict, so ``students.filter`` threw during init,
    every listener bound after it was lost, and the page degraded to a plain
    text box with no results dropdown and no establishment field. The
    Django-level assertions in AdminAssignmentTests all passed while the UI was
    completely broken, so these tests assert the rendered payload the browser
    receives.
    """

    def setUp(self):
        self.client.force_login(self.instructor)

    def script_payload(self, body, script_id):
        match = re.search(
            rf'<script id="{script_id}"[^>]*>(.*?)</script>', body, re.S)
        self.assertIsNotNone(match, f'{script_id} block missing from the page')
        return json.loads(match.group(1))

    def test_student_lookup_data_arrives_as_a_json_list(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        payload = self.script_payload(body, 'studentData')
        self.assertIsInstance(
            payload, list,
            'studentData must be a JSON list; a str means the caller passed a '
            'pre-serialised string to json_script and the page JS will throw')
        self.assertIn(self.arlyne.id, [row['id'] for row in payload])
        for row in payload:
            self.assertIn('search', row)
            self.assertIn('name', row)

    def test_student_roles_map_arrives_as_a_json_object(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        payload = self.script_payload(body, 'studentRoles')
        self.assertIsInstance(payload, dict)
        self.assertIn(str(self.arlyne.id), payload)

    def test_establishment_data_arrives_grouped_by_establishment_type(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        payload = self.script_payload(body, 'establishmentData')
        self.assertIsInstance(payload, dict)
        self.assertIn(
            self.sunrise_est.pk,
            [row['id'] for row in payload[Establishment.Type.HOTEL]],
        )
        self.assertIn(
            self.grand_est.pk,
            [row['id'] for row in payload[Establishment.Type.HOTEL]],
        )

    def test_role_to_establishment_type_map_names_the_per_resource_roles(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        payload = self.script_payload(body, 'roleEstablishmentTypes')
        self.assertEqual(payload[Role.HOTEL_FRONT_DESK], Establishment.Type.HOTEL)
        self.assertEqual(payload[Role.AIRLINE_FRONT_DESK], Establishment.Type.AIRLINE)
        for role in (Role.ACTIVITY_RESERVATION_OFFICER, Role.ACTIVITY_OPERATOR):
            self.assertEqual(payload[role], Establishment.Type.ACTIVITY)
        for role in (Role.TOUR_PACKAGE_MANAGER, Role.TOUR_PACKAGE_RESERVATION_OFFICER,
                     Role.TOUR_PACKAGE_FRONT_DESK_OFFICER):
            self.assertEqual(payload[role], Establishment.Type.TOUR_PACKAGE)
        # The customer role is performed outside any establishment. It has to be
        # *present with no type* rather than missing: the page switches on the
        # lookup, so a missing key would read as undefined and could not be told
        # apart from a role the server forgot to publish.
        self.assertIn(Role.PASSENGER_AIRLINE, payload)
        self.assertIsNone(payload[Role.PASSENGER_AIRLINE])

    def test_student_search_matches_name_initials_and_partials(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        rows = {row['id']: row for row in self.script_payload(body, 'studentData')}
        arlyne = rows[self.arlyne.id]
        for term in ('arlyne', 'ar', 'arlyne u', 'au', 'u'):
            self.assertIn(
                term, arlyne['search'],
                f'searching {term!r} should match Arlyne Joy Udaundo')

    def test_no_script_block_is_embedded_inside_inline_javascript(self):
        """``{{ x|json_script:"id" }}.textContent`` is a syntax error.

        json_script emits a whole <script> element, so chaining .textContent
        onto the template tag closes the block early and leaves stray text in
        the surrounding script.
        """
        for url in (reverse('simulation:assign'),):
            body = self.client.get(url).content.decode()
            for script in re.findall(r'<script>(.*?)</script>', body, re.S):
                self.assertNotIn(
                    '</script>', script,
                    'an inline <script> contains a nested </script> close tag')
                self.assertNotRegex(
                    script, r'</script>\s*\.textContent',
                    'json_script output must be read via getElementById, not '
                    'by chaining .textContent onto the template tag')

    def test_assign_form_submits_ids_rather_than_typed_text(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        self.assertIn('name="student"', body)
        self.assertIn('type="hidden"', body)
        self.assertIn('id="studentSearch"', body)
        self.assertRegex(body, r'<select name="establishment"[^>]*id="establishmentSelect"')

    def test_establishment_field_is_conditional_on_the_role(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        self.assertIn('id="establishmentGroup"', body)
        self.assertIn('id="establishmentSelect"', body)
        self.assertIn('roleEstablishmentTypes', body)
        # The group starts hidden and the page switches on the role -> type map:
        # a role with no type hides it again and disables the select, so nothing
        # is submitted by accident.
        self.assertRegex(body, r'id="establishmentGroup"[^>]*display:none')
        self.assertIn("group.style.display = 'none'", body)
        self.assertIn('select.disabled = true', body)

    def test_held_role_stays_selectable_so_the_override_is_reachable(self):
        """A disabled <option> cannot be clicked by a user.

        Disabling the conflicting role made the "assign this role again"
        override unreachable: the instructor could never select the held role,
        so the prompt never appeared. The block is enforced on submit instead.
        """
        self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        body = self.client.get(reverse('simulation:assign')).content.decode()
        self.assertIn('opt.disabled = false', body)
        self.assertNotIn('opt.disabled = Boolean(held)', body)
        self.assertIn("addEventListener('submit'", body)

    def test_repeat_override_prompt_text_is_present(self):
        body = self.client.get(reverse('simulation:assign')).content.decode()
        self.assertIn('Assign this role again', body)
        self.assertIn('id="assignAgain"', body)


class EstablishmentFieldServerSideTests(AssignmentFlowTestCase):
    """The server must not rely on the form having hidden or cleared the field.

    The establishment box is filled by JS from a per-type list, but a
    hand-crafted POST can send whatever it likes, so these rules are re-checked on
    save: the establishment must exist, be active, and be of the role's own type.
    """

    def setUp(self):
        self.client.force_login(self.instructor)

    def post(self, **overrides):
        data = {
            'activity_name': 'Activity 1',
            'student': self.arlyne.id,
            'role': Role.HOTEL_FRONT_DESK,
            'establishment': self.sunrise_est.pk,
            'simulation_date': '',
            'start_time': '',
            'end_time': '',
        }
        data.update(overrides)
        return self.client.post(reverse('simulation:assign'), data)

    def test_operational_role_without_an_establishment_is_refused(self):
        response = self.post(establishment='')
        # The form comes back rather than redirecting, so the instructor keeps
        # the activity, student and role they had already chosen.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SimulationRoleAssignment.objects.exists())
        self.assertContains(
            response, 'is performed inside an establishment, so select the one this '
            'student will work at', msg_prefix='')

    def test_an_establishment_of_the_wrong_type_is_refused(self):
        airline = Establishment.objects.create(
            name='Cebu Pacific', type=Establishment.Type.AIRLINE)
        response = self.post(establishment=airline.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SimulationRoleAssignment.objects.exists())
        self.assertContains(response, 'Select an active Hotel')

    def test_an_unknown_establishment_id_is_rejected(self):
        self.post(establishment=self.grand_est.pk + 99999)
        self.assertFalse(SimulationRoleAssignment.objects.exists())

    def test_assignment_saves_the_establishment_id_not_the_name(self):
        self.post()
        assignment = SimulationRoleAssignment.objects.get()
        self.assertEqual(assignment.establishment_id, self.sunrise_est.pk)
        self.assertEqual(assignment.establishment, self.sunrise_est)

    def test_a_hotel_role_also_mirrors_its_hotel(self):
        """The hotel column is what ``atrue_core.hotel_scope`` reads."""
        self.post()
        assignment = SimulationRoleAssignment.objects.get()
        self.assertEqual(assignment.hotel, self.sunrise)

    def test_an_establishment_posted_for_the_customer_role_is_discarded(self):
        self.post(role=Role.PASSENGER_AIRLINE)
        assignment = SimulationRoleAssignment.objects.get()
        self.assertIsNone(
            assignment.establishment_id,
            'the customer role is performed outside any establishment; keeping '
            'one would grant hotel access to a customer')
        self.assertIsNone(assignment.hotel_id)

    def test_a_discarded_establishment_grants_no_access(self):
        self.post(role=Role.PASSENGER_AIRLINE)
        self.client.force_login(self.arlyne)
        for url in (
            reverse('hotels:manage'),
            reverse('hotels:update_hotel', args=[self.sunrise.pk]),
            reverse('hotels:bookings'),
        ):
            with self.subTest(url=url):
                self.assertNotEqual(self.client.get(url).status_code, 200)

    def test_student_id_is_taken_from_the_hidden_field_only(self):
        """The visible box is free text, so typed text must never be trusted."""
        self.post(student='Arlyne')
        self.assertFalse(SimulationRoleAssignment.objects.exists())
        self.post(student='')
        self.assertFalse(SimulationRoleAssignment.objects.exists())


class AdminAssignmentTests(AssignmentFlowTestCase):
    """Sections 1-3 and 9: the instructor's side of the flow."""

    def setUp(self):
        self.client.force_login(self.instructor)

    def post(self, **overrides):
        data = {
            'activity_name': 'Activity 1',
            'student': self.arlyne.id,
            'role': Role.HOTEL_FRONT_DESK,
            'establishment': self.sunrise_est.pk,
            'simulation_date': '2026-09-26',
            'start_time': '07:00',
            'end_time': '17:00',
        }
        data.update(overrides)
        return self.client.post(reverse('simulation:assign'), data)

    def test_assignment_stores_student_role_establishment_status_and_date(self):
        self.assertEqual(self.post().status_code, 302)
        a = SimulationRoleAssignment.objects.get(student=self.arlyne)
        self.assertEqual(a.role, Role.HOTEL_FRONT_DESK)
        self.assertEqual(a.student_id, self.arlyne.id)
        self.assertEqual(a.establishment_id, self.sunrise_est.pk)
        self.assertEqual(a.status, SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        self.assertIsNotNone(a.assigned_at)

    def test_role_choices_offer_the_catalogue_and_nothing_else(self):
        response = self.client.get(reverse('simulation:assign'))
        for role in (Role.HOTEL_MANAGER, Role.HOTEL_RESERVATION_OFFICER,
                     Role.HOTEL_FRONT_DESK, Role.PASSENGER_AIRLINE):
            self.assertContains(response, f'value="{role}"')
        for retired in (Role.RECEPTIONIST, Role.CONCIERGE, Role.TOUR_GUIDE,
                        Role.AIRLINE_TICKETING_OFFICER):
                with self.subTest(retired=retired):
                    self.assertNotContains(response, f'value="{retired}"')

    def test_administrative_roles_are_not_offered(self):
        """An instructor runs the simulation; they do not hand out admin roles."""
        response = self.client.get(reverse('simulation:assign'))
        for administrative in (Role.INSTRUCTOR, Role.SYSTEM_ADMINISTRATOR):
            with self.subTest(role=administrative):
                self.assertNotContains(response, f'value="{administrative}"')

    def test_an_administrative_role_cannot_be_assigned_by_a_hand_built_post(self):
        for administrative in (Role.INSTRUCTOR, Role.SYSTEM_ADMINISTRATOR):
            with self.subTest(role=administrative):
                self.post(role=administrative, establishment='')
                self.assertFalse(
                    SimulationRoleAssignment.objects.filter(
                        student=self.arlyne).exists(),
                    'the form hides administrative roles, so the server must '
                    'refuse one too')

    def test_a_retired_role_cannot_be_assigned_by_a_hand_built_post(self):
        """The form hides them; the server has to agree.

        Otherwise deprecating a role only hides the dropdown while a stale page,
        a bookmarked POST or a scripted client keeps handing it out.
        """
        self.post(role=Role.RECEPTIONIST)
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.arlyne).exists())

    def test_autocomplete_matches_name_initials_and_first_letter(self):
        response = self.client.get(reverse('simulation:assign'))
        self.assertContains(response, 'id="studentSearch"')
        self.assertContains(response, 'id="studentResults"')
        payload = json.loads(
            response.context['student_options']
            if isinstance(response.context['student_options'], str)
            else json.dumps(response.context['student_options'])
        )
        keys = {s['username']: s['search'] for s in payload}
        self.assertIn('arlyne joy udaundo', keys['arlyne'])
        self.assertIn('udaundo arlyne joy', keys['arlyne'])
        self.assertIn('aju', keys['arlyne'])
        self.assertIn('amc', keys['angela'])

    def test_assign_page_offers_the_establishments_of_every_type(self):
        response = self.client.get(reverse('simulation:assign'))
        self.assertContains(response, self.sunrise.name)
        self.assertContains(response, self.grand.name)
        self.assertContains(response, self.tour_est.name)

    def test_operational_role_without_establishment_is_rejected(self):
        self.post(establishment='')
        self.assertFalse(
            SimulationRoleAssignment.objects.filter(student=self.arlyne).exists())

    def test_customer_role_stores_no_establishment(self):
        self.post(role=Role.PASSENGER_AIRLINE, establishment='')
        a = SimulationRoleAssignment.objects.get(student=self.arlyne)
        self.assertIsNone(a.establishment)

    def test_admin_table_shows_every_assignment_column(self):
        a = self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.assign(self.john, Role.PASSENGER_AIRLINE, None, activity_name='Activity 2')
        response = self.client.get(reverse('simulation:role_list'))
        self.assertContains(response, 'Arlyne')
        self.assertContains(response, 'Sunrise Hotel')
        self.assertContains(response, 'Active')
        self.assertContains(response, reverse('simulation:unassign', args=[a.id]))
        self.assertContains(response, f"{reverse('simulation:role_detail', args=[a.id])}#update-role")


    def test_admin_can_filter_assignments_by_hotel_and_student(self):
        self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.assign(self.john, Role.HOTEL_FRONT_DESK, self.grand_est, activity_name='Activity 2')
        by_hotel = self.client.get(reverse('simulation:role_list'), {'hotel': self.grand.pk})
        self.assertEqual([a.student_id for a in by_hotel.context['roles']], [self.john.id])
        by_student = self.client.get(reverse('simulation:role_list'), {'q': 'arlyne'})
        self.assertEqual([a.student_id for a in by_student.context['roles']], [self.arlyne.id])

    def test_admin_changes_role_and_establishment(self):
        a = self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.client.post(reverse('simulation:role_update', args=[a.id]), {
            'role': Role.HOTEL_MANAGER, 'establishment': self.grand_est.pk,
            'reason': 'rotation',
        })
        a.refresh_from_db()
        self.assertEqual(a.role, Role.HOTEL_MANAGER)
        self.assertEqual(a.establishment_id, self.grand_est.pk)
        self.assertEqual(a.hotel, self.grand, 'the hotel mirror must follow the edit')

    def test_admin_cannot_strip_an_operational_role_of_its_establishment(self):
        """Editing must not be a way around the assign form's checks."""
        a = self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.client.post(reverse('simulation:role_update', args=[a.id]),
                         {'role': Role.HOTEL_MANAGER})
        a.refresh_from_db()
        self.assertEqual(a.establishment_id, self.sunrise_est.pk)

    def test_admin_cannot_switch_a_role_to_another_establishment_type(self):
        a = self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.client.post(reverse('simulation:role_update', args=[a.id]), {
            'role': Role.AIRLINE_FRONT_DESK, 'establishment': self.grand_est.pk,
        })
        a.refresh_from_db()
        self.assertEqual(a.role, Role.HOTEL_FRONT_DESK)
        self.assertEqual(a.establishment_id, self.sunrise_est.pk)

    def test_editing_keeps_the_establishment_when_only_the_role_changes(self):
        a = self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.client.post(reverse('simulation:role_update', args=[a.id]),
                         {'role': Role.HOTEL_RESERVATION_OFFICER})
        a.refresh_from_db()
        self.assertEqual(a.role, Role.HOTEL_RESERVATION_OFFICER)
        self.assertEqual(a.establishment_id, self.sunrise_est.pk)

    def test_activity_roles_keep_the_assigned_activity_when_rotated(self):
        a = self.assign(
            self.arlyne, Role.ACTIVITY_RESERVATION_OFFICER, self.activity_est)
        for role in (Role.ACTIVITY_OPERATOR, Role.ACTIVITY_RESERVATION_OFFICER):
            with self.subTest(role=role):
                self.client.post(reverse('simulation:role_update', args=[a.id]), {
                    'role': role,
                    'reason': 'role rotation',
                })
                a.refresh_from_db()
                self.assertEqual(a.role, role)
                self.assertEqual(a.establishment_id, self.activity_est.pk)

    def test_package_roles_keep_the_assigned_package_when_rotated(self):
        a = self.assign(
            self.angela, Role.TOUR_PACKAGE_RESERVATION_OFFICER, self.package_est)
        for role in (Role.TOUR_PACKAGE_FRONT_DESK_OFFICER,
                     Role.TOUR_PACKAGE_RESERVATION_OFFICER):
            with self.subTest(role=role):
                self.client.post(reverse('simulation:role_update', args=[a.id]), {
                    'role': role,
                    'reason': 'role rotation',
                })
                a.refresh_from_db()
                self.assertEqual(a.role, role)
                self.assertEqual(a.establishment_id, self.package_est.pk)

    def test_a_student_may_not_edit_their_own_assignment(self):
        a = self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.client.force_login(self.arlyne)
        self.client.post(reverse('simulation:role_update', args=[a.id]),
                         {'role': Role.HOTEL_MANAGER})
        a.refresh_from_db()
        self.assertEqual(a.role, Role.HOTEL_FRONT_DESK)

    def test_admin_deactivates_an_assignment(self):
        a = self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.client.post(reverse('simulation:unassign', args=[a.id]))
        a.refresh_from_db()
        self.assertEqual(a.status, SimulationRoleAssignment.AssignmentStatus.INACTIVE)


class RoleDetailEstablishmentDisplayTests(AssignmentFlowTestCase):
    def test_role_detail_displays_establishments_for_current_and_other_roles(self):
        restaurant = Establishment.objects.create(
            name='Locavore', type=Establishment.Type.RESTAURANT)
        assignment = self.assign(
            self.arlyne, Role.RESTAURANT_MANAGER, restaurant)
        self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.client.force_login(self.arlyne)

        response = self.client.get(
            reverse('simulation:role_detail', args=[assignment.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<i class="fas fa-building"></i> Establishment')
        self.assertContains(response, 'Locavore')
        self.assertContains(response, 'Sunrise Hotel')
        self.assertContains(response, '<th>Establishment</th>')
        self.assertNotContains(response, '<th>Hotel</th>')


class GuestRoleDestinationTests(AssignmentFlowTestCase):
    """Attaching a place to a guest assignment points "Do the Task" at it.

    Guest roles are performed outside an establishment (their ``establishment_type``
    is None), so their module is browse-all for the customer. An instructor may
    still attach *one optional* establishment of the guest's own module type; the
    task then deep-links the student onto that place's public page instead of the
    module list.
    """

    def setUp(self):
        self.client.force_login(self.instructor)
        self.staycation = Staycation.objects.create(
            name='Cebu Getaway Staycation', rate=Decimal('2500.00'))
        self.staycation_est = establishment_for_instance(self.staycation, create=True)

    def post(self, role, establishment, **overrides):
        data = {
            'activity_name': 'Guest drill',
            'student': self.arlyne.id,
            'role': role,
            'establishment': '' if establishment is None else establishment.pk,
            'simulation_date': '2026-09-26',
            'start_time': '07:00',
            'end_time': '17:00',
        }
        data.update(overrides)
        return self.client.post(reverse('simulation:assign'), data)

    def test_assign_accepts_and_stores_a_guest_establishment(self):
        response = self.post(Role.STAYCATION_GUEST, self.staycation_est)
        self.assertEqual(response.status_code, 302)
        assignment = SimulationRoleAssignment.objects.get(student=self.arlyne)
        self.assertEqual(assignment.role, Role.STAYCATION_GUEST)
        self.assertEqual(assignment.establishment_id, self.staycation_est.pk)

    def test_assign_refuses_a_guest_establishment_of_the_wrong_type(self):
        response = self.post(Role.STAYCATION_GUEST, self.sunrise_est)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SimulationRoleAssignment.objects.filter(student=self.arlyne).exists())
        self.assertContains(response, 'Select an active staycation')

    def test_guest_may_be_left_without_a_place(self):
        response = self.post(Role.GUEST_HOTEL, None)
        self.assertEqual(response.status_code, 302)
        assignment = SimulationRoleAssignment.objects.get(student=self.arlyne)
        self.assertIsNone(assignment.establishment_id)

    def test_guest_without_a_place_lands_on_the_module_list(self):
        assignment = self.assign(self.angela, Role.STAYCATION_GUEST)
        self.client.force_login(self.angela)
        response = self.client.get(reverse('simulation:do_task', args=[assignment.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['operation']['url'], reverse('staycations:list'))

    def test_guest_with_a_place_lands_on_that_place(self):
        assignment = self.assign(
            self.angela, Role.STAYCATION_GUEST, self.staycation_est)
        self.client.force_login(self.angela)
        response = self.client.get(reverse('simulation:do_task', args=[assignment.id]))

        landing = reverse('staycations:detail', args=[self.staycation.pk])
        self.assertEqual(response.context['operation']['url'], landing)
        browse = next(
            t for t in response.context['operation']['tasks']
            if t['route'] == 'staycations:list')
        self.assertEqual(
            browse['url'], landing,
            'the module-browse task must also deep-link to the assigned place')
        bookings = next(
            t for t in response.context['operation']['tasks']
            if t['route'] == 'transactions:booking_list')
        self.assertEqual(bookings['url'], reverse('transactions:booking_list'))

    def test_the_deep_linked_landing_actually_opens(self):
        assignment = self.assign(
            self.angela, Role.STAYCATION_GUEST, self.staycation_est)
        self.client.force_login(self.angela)
        response = self.client.get(reverse('simulation:do_task', args=[assignment.id]))
        landing = response.context['operation']['url']
        self.assertEqual(self.client.get(landing).status_code, 200)

    def test_a_bare_unlinked_establishment_is_not_deep_linked(self):
        bare = Establishment.objects.create(
            name='Bare Resort', type=Establishment.Type.RESORT)
        assignment = self.assign(self.angela, Role.RESORT_GUEST, bare)
        self.client.force_login(self.angela)
        response = self.client.get(reverse('simulation:do_task', args=[assignment.id]))
        self.assertEqual(response.context['operation']['url'], reverse('resorts:list'))

    def test_every_guest_role_resolves_to_operations(self):
        """None of the guest roles may leave "Do the Task" dead."""
        for role, establishment in (
            (Role.GUEST_HOTEL, self.sunrise_est),
            (Role.RESORT_GUEST, None),
            (Role.RESTAURANT_GUEST, None),
            (Role.STAYCATION_GUEST, self.staycation_est),
            (Role.LANDMARK_GUEST, None),
            (Role.TOUR_GUEST, None),
            (Role.PASSENGER_TRANSPORT, None),
            (Role.ACTIVITY_GUEST, None),
        ):
            with self.subTest(role=role):
                assignment = self.assign(self.angela, role, establishment)
                operation = task_operation_for(assignment)
                self.assertIsNotNone(operation, f'{role} has no operations')
                self.assertTrue(operation['tasks'])

    def test_role_update_repoints_a_guest_establishment(self):
        assignment = self.assign(self.angela, Role.STAYCATION_GUEST)
        self.client.post(reverse('simulation:role_update', args=[assignment.id]), {
            'role': Role.STAYCATION_GUEST,
            'establishment': self.staycation_est.pk,
            'reason': 'point at the assigned staycation',
        })
        assignment.refresh_from_db()
        self.assertEqual(assignment.establishment_id, self.staycation_est.pk)


class RoleCatalogueDatabaseAgreementTests(AssignmentFlowTestCase):
    """The assign form and the assign view must read the same list of roles.

    The dropdown is built from ``ROLE_CATALOGUE`` while the POST handler needs a
    live ``Role`` row to store against, so a database whose catalogue has not been
    synced (the seeding migration was never applied, or a role was added since)
    used to offer ``Airline Manager`` in the list and then answer the very same
    submission with "Select a valid role." Every test here deletes the row first,
    which is exactly that state.
    """

    def setUp(self):
        self.client.force_login(self.instructor)
        self.cebupac = Establishment.objects.create(
            name='Cebu Pacific', type=Establishment.Type.AIRLINE)
        self.pal = Establishment.objects.create(
            name='Philippine Airlines', type=Establishment.Type.AIRLINE)
        # One establishment of every remaining type, so the catalogue walk below
        # can reach each role at the kind of place it is performed in.
        self.transport_est = Establishment.objects.create(
            name='Cebu Jeepney Transport', type=Establishment.Type.TRANSPORTATION)
        self.travel_est = Establishment.objects.create(
            name='Island Travel Agency', type=Establishment.Type.TRAVEL_AGENCY)
        self.resort_est = Establishment.objects.create(
            name='Bluewater Resort', type=Establishment.Type.RESORT)
        self.restaurant_est = Establishment.objects.create(
            name='Seaside Grill Restaurant', type=Establishment.Type.RESTAURANT)
        self.staycation_est = Establishment.objects.create(
            name='Cebu Getaway Staycation', type=Establishment.Type.STAYCATION)
        self.landmark_est = Establishment.objects.create(
            name='Magellan Cross Landmark', type=Establishment.Type.LANDMARK)
        self.activity_est = Establishment.objects.create(
            name='Cebu Trails Activity', type=Establishment.Type.ACTIVITY)
        self.tour_package_est = Establishment.objects.create(
            name='Cebu City Tour Package', type=Establishment.Type.TOUR_PACKAGE)
        self.establishment_of_type = {
            Establishment.Type.AIRLINE: self.cebupac,
            Establishment.Type.HOTEL: self.sunrise_est,
            Establishment.Type.TOUR_OPERATOR: self.tour_est,
            Establishment.Type.TRANSPORTATION: self.transport_est,
            Establishment.Type.TRAVEL_AGENCY: self.travel_est,
            Establishment.Type.RESORT: self.resort_est,
            Establishment.Type.RESTAURANT: self.restaurant_est,
            Establishment.Type.STAYCATION: self.staycation_est,
            Establishment.Type.LANDMARK: self.landmark_est,
            RoleModel.EstablishmentType.ACTIVITY: self.activity_est,
            RoleModel.EstablishmentType.TOUR_PACKAGE: self.tour_package_est,
        }

    def post(self, role, establishment=None, **overrides):
        data = {
            'activity_name': 'Activity 1',
            'student': self.arlyne.id,
            'role': role,
            'establishment': '' if establishment is None else establishment.pk,
            'simulation_date': '2026-09-26',
            'start_time': '07:00',
            'end_time': '17:00',
        }
        data.update(overrides)
        return self.client.post(reverse('simulation:assign'), data)

    def drop_role_row(self, code):
        """Leave the database without the row the catalogue still names."""
        RoleModel.objects.filter(code=code).delete()
        self.assertFalse(RoleModel.objects.filter(code=code).exists())

    def test_airline_manager_is_offered_and_accepted_without_its_database_row(self):
        self.drop_role_row(Role.AIRLINE_MANAGER)
        response = self.client.get(reverse('simulation:assign'))
        self.assertContains(response, f'value="{Role.AIRLINE_MANAGER}"')

        response = self.post(Role.AIRLINE_MANAGER, self.cebupac)
        self.assertEqual(response.status_code, 302, msg='offered roles must be assignable')
        a = SimulationRoleAssignment.objects.get(student=self.arlyne)
        self.assertEqual(a.role, Role.AIRLINE_MANAGER)
        self.assertEqual(a.establishment_id, self.cebupac.pk)
        self.assertEqual(a.role_ref.code, Role.AIRLINE_MANAGER)

    def test_every_offered_role_is_accepted_for_the_right_establishment(self):
        """Nothing on the dropdown may be a dead end.

        Walks the whole catalogue rather than a hand-picked few, so a role added
        later cannot quietly become un-assignable.
        """
        for code, _label, _category, establishment_type, _op, _order in ROLE_CATALOGUE:
            if code in {Role.INSTRUCTOR, Role.SYSTEM_ADMINISTRATOR}:
                continue
            if code in {Role.RECEPTIONIST, Role.CONCIERGE, Role.TOUR_GUIDE,
                        Role.AIRLINE_TICKETING_OFFICER}:
                continue  # retired: deliberately not on the form
            self.drop_role_row(code)
            establishment = self.establishment_of_type.get(establishment_type)
            with self.subTest(role=code):
                response = self.post(code, establishment, activity_name=f'A {code}')
                self.assertEqual(response.status_code, 302,
                                 msg=f'{code} is offered but was refused')
                self.assertTrue(
                    SimulationRoleAssignment.objects.filter(
                        student=self.arlyne, role=code).exists())

    def test_the_second_airline_establishment_works_for_the_same_role(self):
        """The role is not tied to one airline; the establishment is chosen."""
        self.drop_role_row(Role.AIRLINE_MANAGER)
        # A different student per airline, because one student may not hold the
        # same role in two live sessions without ticking the repeat override.
        for student, establishment in ((self.arlyne, self.cebupac), (self.angela, self.pal)):
            with self.subTest(establishment=establishment.name):
                response = self.post(
                    Role.AIRLINE_MANAGER, establishment, student=student.id,
                    activity_name=f'At {establishment.name}')
                self.assertEqual(response.status_code, 302)
                self.assertTrue(SimulationRoleAssignment.objects.filter(
                    student=student, establishment=establishment).exists())

    def test_other_airline_roles_are_accepted_at_their_own_establishment(self):
        for code in (Role.AIRLINE_RESERVATION_AGENT, Role.AIRLINE_FRONT_DESK):
            with self.subTest(role=code):
                self.drop_role_row(code)
                response = self.post(code, self.pal, activity_name=f'A {code}')
                self.assertEqual(response.status_code, 302)
                a = SimulationRoleAssignment.objects.get(role=code)
                self.assertEqual(a.establishment_id, self.pal.pk)

    def test_a_role_with_no_database_row_is_not_accepted_from_a_hand_built_post(self):
        """Self-healing must not widen what the server accepts.

        A code that is not in the catalogue is refused whether or not a row for it
        happens to exist, so a retired role cannot be revived by a stale page.
        """
        response = self.post(Role.RECEPTIONIST, self.sunrise_est)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SimulationRoleAssignment.objects.exists())
        self.assertContains(response, 'Select a valid role.')

    def test_an_administrative_role_is_still_refused_when_its_row_exists(self):
        response = self.post(Role.SYSTEM_ADMINISTRATOR, self.sunrise_est)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SimulationRoleAssignment.objects.exists())
        self.assertContains(response, 'Select a valid role.')


class RejectedSubmissionKeepsItsInputTests(AssignmentFlowTestCase):
    """A rejected submission must not throw away what the instructor typed.

    The failure that started this redirects dropped every field, so a typo in one
    box cost a full re-entry of the student, role, establishment and schedule.
    """

    def setUp(self):
        self.client.force_login(self.instructor)
        self.cebupac = Establishment.objects.create(
            name='Cebu Pacific', type=Establishment.Type.AIRLINE)

    def test_schedule_student_and_role_survive_a_missing_establishment(self):
        response = self.client.post(reverse('simulation:assign'), {
            'activity_name': 'Activity 3',
            'student': self.arlyne.id,
            'role': Role.AIRLINE_MANAGER,
            'establishment': '',
            'simulation_date': '2026-09-26',
            'start_time': '07:00',
            'end_time': '17:00',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Activity 3"')
        self.assertContains(response, 'value="2026-09-26"')
        self.assertContains(response, 'value="07:00"')
        self.assertContains(response, 'value="17:00"')
        self.assertContains(response, f'value="{self.arlyne.id}"')
        self.assertContains(response, 'Arlyne')
        self.assertContains(
            response, f'<option value="{Role.AIRLINE_MANAGER}" selected>',
            msg_prefix='the role the instructor picked has to stay picked')

    def test_the_chosen_establishment_survives_a_rejection(self):
        response = self.client.post(reverse('simulation:assign'), {
            'activity_name': 'Activity 3',
            'student': self.arlyne.id,
            'role': Role.AIRLINE_MANAGER,
            'establishment': self.cebupac.pk,
            'simulation_date': '',
            'start_time': '',
            'end_time': '',
            # An end before the start is refused, so the rest must come back.
            'start_time': '17:00',
            'end_time': '07:00',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-chosen="{self.cebupac.pk}"')
        self.assertContains(response, 'Activity 3')

    def test_a_missing_activity_name_keeps_the_rest_of_the_form(self):
        response = self.client.post(reverse('simulation:assign'), {
            'activity_name': '',
            'student': self.arlyne.id,
            'role': Role.PASSENGER_AIRLINE,
            'simulation_date': '2026-09-26',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Name the activity')
        self.assertContains(response, f'<option value="{Role.PASSENGER_AIRLINE}" selected>')

    def test_a_duplicate_role_keeps_the_form_and_the_repeat_override_reachable(self):
        self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        response = self.client.post(reverse('simulation:assign'), {
            'activity_name': 'Activity 1',
            'student': self.arlyne.id,
            'role': Role.HOTEL_FRONT_DESK,
            'establishment': self.sunrise_est.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already an active assignment')
        self.assertContains(response, 'id="assignAgain"')
        self.assertEqual(SimulationRoleAssignment.objects.filter(
            student=self.arlyne).count(), 1)

    def test_an_unknown_student_is_reported_and_the_other_fields_survive(self):
        response = self.client.post(reverse('simulation:assign'), {
            'activity_name': 'Activity 3',
            'student': '999999',
            'role': Role.PASSENGER_AIRLINE,
            'simulation_date': '2026-09-26',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a student from the list')
        self.assertContains(response, 'value="Activity 3"')


class MyRolesAndDoTheTaskTests(AssignmentFlowTestCase):
    """Sections 4, 5 and 8: what the student sees and where the button goes."""

    def setUp(self):
        self.assignment = self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.tour = self.assign(
            self.arlyne, Role.TOUR_FRONT_DESK, self.tour_est,
            activity_name='Activity 2')
        self.client.force_login(self.arlyne)

    def test_my_roles_lists_each_role_with_its_establishment(self):
        response = self.client.get(reverse('simulation:workspace'))
        self.assertContains(response, 'My Roles')
        self.assertContains(response, self.assignment.get_role_display())
        self.assertContains(response, 'Sunrise Hotel')
        self.assertContains(response, 'Do the Task')

    def test_workspace_shows_sessions_before_their_role_activities(self):
        session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor,
        )
        self.assignment.session = session
        self.assignment.activity_name = session.name
        self.assignment.save(update_fields=['session', 'activity_name'])
        response = self.client.get(reverse('simulation:workspace'))
        body = response.content.decode()
        self.assertContains(response, 'Simulation sessions')
        self.assertContains(response, 'Session 1')
        self.assertLess(body.index('simulation-session-list'), body.index('Activities and roles'))
        self.assertContains(response, reverse('simulation:do_task', args=[self.assignment.id]))

    def test_do_the_task_shows_the_assigned_hotel_operations_entry(self):
        response = self.client.get(reverse('simulation:do_task', args=[self.assignment.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hotel Operations')
        self.assertContains(response, 'Manage Bookings and Guests')
        self.assertContains(response, 'class="nav-dd-menu"')
        self.assertNotContains(response, 'Open Hotel Operations')
        self.assertNotContains(response, 'User Admins')
        self.assertEqual(
            response.context['operation']['tasks'][0]['url'],
            f"{reverse('hotels:bookings')}?hotel={self.sunrise.pk}",
        )
        self.assertEqual(
            response.context['operation']['url'],
            f"{reverse('hotels:bookings')}?hotel={self.sunrise.pk}",
        )

    def test_passenger_airline_task_opens_its_operations_page(self):
        passenger_assignment = self.assign(
            self.arlyne, Role.PASSENGER_AIRLINE, activity_name='Flight Activity')

        response = self.client.get(
            reverse('simulation:do_task', args=[passenger_assignment.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'simulation/task_operations.html')
        self.assertContains(response, 'Airline Passenger Operations')
        for label in (
            'Book Flight', 'View Booking', 'Manage Booking',
            'Select Seat', 'View Ticket',
        ):
            with self.subTest(label=label):
                self.assertContains(response, label)
        self.assertNotContains(response, 'passenger-task-workspace')
        self.assertEqual(
            response.context['operation']['tasks'][0]['url'],
            reverse('airlines:list'),
        )
        self.assertEqual(
            response.context['operation']['tasks'][1]['url'],
            reverse('transactions:booking_list'),
        )
        for task in response.context['operation']['tasks']:
            with self.subTest(task=task['label']):
                self.assertEqual(self.client.get(task['url']).status_code, 200)
        self.assertEqual(
            self.client.session['active_simulation_task_assignment'],
            passenger_assignment.pk,
        )

    def test_another_establishment_type_uses_its_own_operations_module(self):
        response = self.client.get(reverse('simulation:do_task', args=[self.tour.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tour Operations')
        self.assertEqual(
            response.context['operation']['url'],
            reverse('activities:manage'),
        )

    def test_every_operational_role_resolves_to_operations(self):
        """Each of the three roles must open something for its own type."""
        for role, establishment_type in (
            (Role.HOTEL_MANAGER, Establishment.Type.HOTEL),
            (Role.HOTEL_RESERVATION_OFFICER, Establishment.Type.HOTEL),
            (Role.HOTEL_FRONT_DESK, Establishment.Type.HOTEL),
            (Role.TOUR_OPERATOR_MANAGER, Establishment.Type.TOUR_OPERATOR),
            (Role.TOUR_RESERVATION_AGENT, Establishment.Type.TOUR_OPERATOR),
            (Role.TOUR_FRONT_DESK, Establishment.Type.TOUR_OPERATOR),
            (Role.ACTIVITY_RESERVATION_OFFICER, Establishment.Type.ACTIVITY),
            (Role.ACTIVITY_OPERATOR, Establishment.Type.ACTIVITY),
            (Role.TOUR_PACKAGE_RESERVATION_OFFICER, Establishment.Type.TOUR_PACKAGE),
            (Role.TOUR_PACKAGE_OPERATOR, Establishment.Type.TOUR_PACKAGE),
        ):
            with self.subTest(role=role):
                establishment = {
                    Establishment.Type.HOTEL: self.sunrise_est,
                    Establishment.Type.TOUR_OPERATOR: self.tour_est,
                    Establishment.Type.ACTIVITY: self.activity_est,
                    Establishment.Type.TOUR_PACKAGE: self.package_est,
                }[establishment_type]
                assignment = self.assign(
                    self.angela, role, establishment, activity_name='Routing')
                operation = task_operation_for(assignment)
                self.assertIsNotNone(
                    operation,
                    f'{role} has no operations, so "Do the Task" would be dead')
                self.assertTrue(operation['tasks'])
                if role.startswith('ACTIVITY_'):
                    self.assertTrue(
                        all(task['route'].startswith('activities:')
                            for task in operation['tasks']))
                if role.startswith('TOUR_PACKAGE_'):
                    self.assertTrue(
                        all(task['route'].startswith('tour_package:')
                            for task in operation['tasks']))

    def test_assignment_task_context_is_independent_between_tabs(self):
        airline, _types = make_airline('Sky Air')
        airline_est = establishment_for_instance(airline, create=True)
        hotel_assignment = self.assign(
            self.angela, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Hotel Activity')
        airline_assignment = self.assign(
            self.angela, Role.AIRLINE_FRONT_DESK, airline_est,
            activity_name='Airline Activity')
        self.client.force_login(self.angela)

        hotel_context = 'hotel-task-context-1'
        airline_context = 'airline-task-context-2'
        hotel_landing = self.client.get(
            reverse('simulation:do_task', args=[hotel_assignment.id]),
            HTTP_X_ATRUE_CTX=hotel_context,
        )
        airline_landing = self.client.get(
            reverse('simulation:do_task', args=[airline_assignment.id]),
            HTTP_X_ATRUE_CTX=airline_context,
        )
        self.assertContains(hotel_landing, 'Hotel Operations')
        self.assertContains(airline_landing, 'Airline Operations')

        hotel_operations = hotel_landing.context['operation']['url']
        airline_operations = airline_landing.context['operation']['url']
        self.assertEqual(
            self.client.get(hotel_operations, HTTP_X_ATRUE_CTX=hotel_context).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(airline_operations, HTTP_X_ATRUE_CTX=airline_context).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse('airlines:manage'), HTTP_X_ATRUE_CTX=hotel_context,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse('hotels:manage'), HTTP_X_ATRUE_CTX=airline_context,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse('hotels:amenities'), HTTP_X_ATRUE_CTX=hotel_context,
            ).status_code,
            403,
        )

    def test_do_the_task_lands_on_the_hotel_screen_with_context(self):
        """The button opens the hotel screen already scoped to that hotel."""
        mine = self.book(self.sunrise, self.sunrise_room, self.arlyne)
        self.book(self.grand, self.grand_room, self.john)

        landing = self.client.get(
            reverse('simulation:do_task', args=[self.assignment.id]))
        response = self.client.get(landing.context['operation']['url'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [b.pk for b in response.context['bookings']], [mine.pk],
            'the landing page must list only the assigned hotel\'s bookings')
        self.assertContains(response, 'Sunrise Hotel')
        self.assertNotContains(response, 'Grand Hotel')

    def test_student_cannot_start_another_students_task(self):
        self.client.force_login(self.john)
        response = self.client.get(reverse('simulation:do_task', args=[self.assignment.id]))
        self.assertEqual(response.status_code, 404)

    def test_inactive_assignment_cannot_start_a_task(self):
        self.assignment.status = SimulationRoleAssignment.AssignmentStatus.INACTIVE
        self.assignment.save(update_fields=['status'])
        response = self.client.get(reverse('simulation:do_task', args=[self.assignment.id]))
        self.assertEqual(response.status_code, 404)


class HotelAccessBoundaryTests(AssignmentFlowTestCase):
    """Sections 6 and 7: the backend, not the template, holds the boundary."""

    def setUp(self):
        self.assignment = self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)
        self.sunrise_booking = self.book(self.sunrise, self.sunrise_room, self.john)
        self.grand_booking = self.book(self.grand, self.grand_room, self.john)
        self.client.force_login(self.arlyne)

    # -- list screens are filtered, not emptied ------------------------------

    def test_manage_lists_only_the_assigned_hotel(self):
        response = self.client.get(reverse('hotels:manage'))
        self.assertEqual([h.id for h in response.context['hotels']], [self.sunrise.id])
        self.assertNotContains(response, self.grand.name)
        self.assertNotContains(response, 'hotel-search-panel')

    def test_rooms_list_only_covers_the_assigned_hotel(self):
        response = self.client.get(reverse('hotels:rooms'))
        self.assertEqual([r.id for r in response.context['rooms']], [self.sunrise_room.id])
        self.assertNotContains(response, 'name="hotel"')

    def test_service_and_amenity_lists_hide_hotel_filter(self):
        for route in ('hotels:services', 'hotels:amenities'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'name="hotel"')

    def test_bookings_list_only_covers_the_assigned_hotel(self):
        response = self.client.get(reverse('hotels:bookings'))
        self.assertEqual([b.id for b in response.context['bookings']], [self.sunrise_booking.id])
        self.assertNotContains(response, 'name="hotel"')

    def test_hotel_picker_in_bookings_hides_the_other_hotel(self):
        response = self.client.get(reverse('hotels:bookings'))
        self.assertEqual([h.id for h in response.context['hotels']], [self.sunrise.id])

    def test_cannot_widen_the_list_by_guessing_a_hotel_id_in_the_query(self):
        response = self.client.get(reverse('hotels:rooms'), {'hotel': self.grand.id})
        self.assertEqual(response.status_code, 403)

    # -- object access is refused -------------------------------------------

    def test_cannot_open_another_hotels_edit_page(self):
        response = self.client.get(reverse('hotels:update_hotel', args=[self.grand.id]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_open_another_hotels_room(self):
        response = self.client.get(reverse('hotels:room_detail', args=[self.grand_room.id]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_edit_another_hotels_room(self):
        response = self.client.get(reverse('hotels:update_room', args=[self.grand_room.id]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_read_another_hotels_booking(self):
        response = self.client.get(reverse('hotels:booking_detail', args=[self.grand_booking.id]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_check_in_a_guest_at_another_hotel(self):
        response = self.client.post(
            reverse('hotels:booking_detail', args=[self.grand_booking.id]),
            {'action': 'checkin'})
        self.assertEqual(response.status_code, 403)
        self.grand_booking.refresh_from_db()
        self.assertNotEqual(self.grand_booking.status, Booking.Status.CHECKED_IN)

    def test_cannot_add_a_room_to_another_hotel(self):
        response = self.client.post(reverse('hotels:add_room', args=[self.grand.id]), {
            'room_number': '999', 'room_type': Room.RoomType.DELUXE, 'rate': '1000'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Room.objects.filter(hotel=self.grand, room_number='999').exists())

    def test_cannot_delete_another_hotel(self):
        response = self.client.post(reverse('hotels:delete_hotel', args=[self.grand.id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Hotel.objects.filter(pk=self.grand.pk).exists())

    def test_cannot_create_a_hotel(self):
        response = self.client.post(reverse('hotels:add'), {
            'name': 'Rogue Hotel', 'country': 'Philippines',
            'province': 'Pangasinan', 'municipality': 'Dagupan City'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Hotel.objects.filter(name='Rogue Hotel').exists())

    def test_deep_link_to_another_hotel_is_refused(self):
        response = self.client.get(reverse('hotels:manage'), {'hotel': self.grand.id})
        self.assertEqual(response.status_code, 403)

    # -- the permitted work still works --------------------------------------

    def test_can_view_own_hotels_booking_and_guest_details(self):
        response = self.client.get(reverse('hotels:booking_detail', args=[self.sunrise_booking.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['can_manage'])
        self.assertContains(response, self.john.get_full_name())

    def test_can_check_in_a_guest_at_the_assigned_hotel(self):
        response = self.client.post(
            reverse('hotels:booking_detail', args=[self.sunrise_booking.id]),
            {'action': 'checkin'})
        self.assertEqual(response.status_code, 302)
        self.sunrise_booking.refresh_from_db()
        self.assertEqual(self.sunrise_booking.status, Booking.Status.CHECKED_IN)

    def test_can_check_out_and_release_the_room(self):
        self.client.post(reverse('hotels:booking_detail', args=[self.sunrise_booking.id]),
                         {'action': 'checkin'})
        self.client.post(reverse('hotels:booking_detail', args=[self.sunrise_booking.id]),
                         {'action': 'checkout'})
        self.sunrise_booking.refresh_from_db()
        self.sunrise_room.refresh_from_db()
        self.assertEqual(self.sunrise_booking.status, Booking.Status.CHECKED_OUT)
        self.assertEqual(self.sunrise_room.status, Room.RoomStatus.AVAILABLE)

    def test_add_hotel_button_is_hidden_from_a_scoped_student(self):
        response = self.client.get(reverse('hotels:manage'))
        self.assertTrue(response.context['hotel_scoped_user'])
        self.assertNotContains(response, reverse('hotels:add'))

    def test_delete_button_is_hidden_from_a_scoped_student(self):
        response = self.client.get(reverse('hotels:manage'))
        self.assertNotContains(response, reverse('hotels:delete_hotel', args=[self.sunrise.id]))

    def test_update_link_only_appears_on_their_own_hotels_page(self):
        own = self.client.get(reverse('hotels:detail', args=[self.sunrise.slug]))
        self.assertTrue(own.context['can_edit_hotel'])
        other = self.client.get(reverse('hotels:detail', args=[self.grand.slug]))
        self.assertFalse(other.context['can_edit_hotel'])

    # -- rule: may manage everything inside their own hotel -----------------

    def test_can_open_the_edit_page_of_their_own_hotel(self):
        response = self.client.get(reverse('hotels:update_hotel', args=[self.sunrise.id]))
        self.assertEqual(response.status_code, 200)

    def test_can_edit_their_own_hotels_information(self):
        response = self.client.post(reverse('hotels:update_hotel', args=[self.sunrise.id]), {
            'name': 'Sunrise Hotel Renamed', 'country': 'Philippines',
            'province': 'Cebu', 'municipality': 'Cebu City'})
        self.assertEqual(response.status_code, 302)
        self.sunrise.refresh_from_db()
        self.assertEqual(self.sunrise.name, 'Sunrise Hotel Renamed')
        self.sunrise.name = 'Sunrise Hotel'
        self.sunrise.save(update_fields=['name'])

    def test_can_add_a_room_to_their_own_hotel(self):
        response = self.client.post(reverse('hotels:add_room', args=[self.sunrise.id]), {
            'room_number': '555', 'room_type': Room.RoomType.DELUXE, 'rate': '4200'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Room.objects.filter(hotel=self.sunrise, room_number='555').exists())

    def test_can_view_and_edit_their_own_hotels_room(self):
        self.assertEqual(
            self.client.get(reverse('hotels:room_detail', args=[self.sunrise_room.id])).status_code, 200)
        response = self.client.post(reverse('hotels:update_room', args=[self.sunrise_room.id]), {
            'room_number': '101', 'room_type': Room.RoomType.SUITE, 'rate': '2600'})
        self.assertEqual(response.status_code, 302)
        self.sunrise_room.refresh_from_db()
        self.assertEqual(self.sunrise_room.room_type, Room.RoomType.SUITE)

    def test_can_confirm_a_booking_at_their_own_hotel(self):
        self.client.post(reverse('hotels:booking_detail', args=[self.sunrise_booking.id]),
                         {'action': 'confirm'})
        self.sunrise_booking.refresh_from_db()
        self.assertEqual(self.sunrise_booking.status, Booking.Status.CONFIRMED)

    def test_can_update_booking_status_at_their_own_hotel(self):
        self.client.post(reverse('hotels:booking_detail', args=[self.sunrise_booking.id]),
                         {'action': 'checkin'})
        self.client.post(reverse('hotels:booking_detail', args=[self.sunrise_booking.id]),
                         {'action': 'checkout'})
        self.sunrise_booking.refresh_from_db()
        self.assertEqual(self.sunrise_booking.status, Booking.Status.CHECKED_OUT)

    def test_cannot_edit_another_hotels_information(self):
        response = self.client.post(reverse('hotels:update_hotel', args=[self.grand.id]), {
            'name': 'Hijacked', 'country': 'Philippines',
            'province': 'Cebu', 'municipality': 'Cebu City'})
        self.assertEqual(response.status_code, 403)
        self.grand.refresh_from_db()
        self.assertEqual(self.grand.name, 'Grand Hotel')


class UnaffectedAudiencesTests(AssignmentFlowTestCase):
    """Existing behaviour must survive: admins see all, customers still book."""

    def setUp(self):
        self.assign(self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est)

    def test_platform_admin_still_sees_every_hotel(self):
        User.objects.create_user('sysadmin', password='pw', account_type='SYSTEM_ADMIN')
        admin = User.objects.get(username='sysadmin')
        self.client.force_login(admin)
        response = self.client.get(reverse('hotels:manage'))
        self.assertEqual(
            sorted(h.id for h in response.context['hotels']),
            sorted([self.sunrise.id, self.grand.id]))
        self.assertEqual(
            self.client.get(reverse('hotels:update_hotel', args=[self.grand.id])).status_code, 200)

    def test_django_staff_still_sees_every_hotel(self):
        staff = User.objects.create_user('staff', password='pw', is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse('hotels:manage'))
        self.assertEqual(
            sorted(h.id for h in response.context['hotels']),
            sorted([self.sunrise.id, self.grand.id]))

    def test_student_without_a_role_keeps_the_public_hotel_pages(self):
        self.client.force_login(self.john)
        self.assertEqual(self.client.get(reverse('hotels:list')).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('hotels:room_detail', args=[self.grand_room.id])).status_code, 200)

    def test_deactivated_assignment_loses_hotel_access(self):
        self.client.force_login(self.arlyne)
        SimulationRoleAssignment.objects.filter(student=self.arlyne).update(
            status=SimulationRoleAssignment.AssignmentStatus.INACTIVE)
        response = self.client.get(reverse('hotels:manage'))
        self.assertEqual(response.status_code, 302)  # redirected: role no longer grants the module
        self.assertEqual(
            self.client.get(reverse('hotels:update_hotel', args=[self.sunrise.id])).status_code, 302)

    def test_student_with_two_hotels_reaches_both(self):
        self.assign(self.arlyne, Role.HOTEL_MANAGER, self.grand_est,
                    activity_name='Activity 2')
        self.client.force_login(self.arlyne)
        response = self.client.get(reverse('hotels:manage'))
        self.assertEqual(
            sorted(h.id for h in response.context['hotels']),
            sorted([self.sunrise.id, self.grand.id]))


class SimulationSessionManagementTests(AssignmentFlowTestCase):
    def setUp(self):
        self.client.force_login(self.instructor)

    def test_instructor_can_create_a_session_without_assigning_a_role(self):
        response = self.client.post(reverse('simulation:add_session'), {
            'name': 'Session 1',
            'description': 'Hotel operations practice',
        })

        self.assertRedirects(response, reverse('simulation:workspace'))
        session = SimulationSession.objects.get(name='Session 1')
        self.assertEqual(session.instructor, self.instructor)
        self.assertEqual(session.description, 'Hotel operations practice')
        self.assertFalse(session.assignments.exists())

        workspace = self.client.get(reverse('simulation:workspace'))
        self.assertContains(workspace, 'Session 1')
        self.assertContains(workspace, 'Add Session')
        self.assertNotContains(workspace, '>Assign Role</a>')

    def test_session_card_add_activity_assigns_activity_to_that_session(self):
        session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor,
        )
        response = self.client.get(
            reverse('simulation:assign'), {'session': session.pk})
        self.assertContains(response, 'Add Activity to Session 1')

        response = self.client.post(reverse('simulation:assign'), {
            'session': session.pk,
            'activity_name': 'Activity 1',
            'student': self.arlyne.pk,
            'role': Role.HOTEL_FRONT_DESK,
            'establishment': self.sunrise_est.pk,
        })

        self.assertRedirects(response, reverse('simulation:workspace'))
        assignment = SimulationRoleAssignment.objects.get(
            student=self.arlyne, activity_name='Activity 1')
        self.assertEqual(assignment.session, session)
        self.assertEqual(assignment.establishment_id, self.sunrise_est.pk)

        workspace = self.client.get(reverse('simulation:workspace'))
        body = workspace.content.decode()
        self.assertLess(body.index('Session 1'), body.index('Activity 1'))
        self.assertIn(f'?session={session.pk}', body)

    def test_instructor_can_update_a_session(self):
        session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor,
            description='Before', status=SimulationSession.Status.DRAFT,
        )
        response = self.client.post(
            reverse('simulation:update_session', args=[session.pk]),
            {
                'name': 'Session 1 Revised',
                'description': 'After editing',
                'start_date': '',
                'end_date': '',
                'status': SimulationSession.Status.SCHEDULED,
            })
        self.assertRedirects(response, reverse('simulation:workspace'))
        session.refresh_from_db()
        self.assertEqual(session.name, 'Session 1 Revised')
        self.assertEqual(session.description, 'After editing')
        self.assertEqual(session.status, SimulationSession.Status.SCHEDULED)
        self.assertIsNone(session.start_date)

    def test_instructor_can_update_dates_and_status(self):
        session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor,
            status=SimulationSession.Status.SCHEDULED,
        )
        self.client.post(
            reverse('simulation:update_session', args=[session.pk]),
            {
                'name': 'Session 1',
                'description': '',
                'start_date': '2026-09-25',
                'end_date': '2026-09-26',
                'status': SimulationSession.Status.ACTIVE,
            })
        session.refresh_from_db()
        self.assertEqual(session.start_date.isoformat(), '2026-09-25')
        self.assertEqual(session.end_date.isoformat(), '2026-09-26')
        self.assertEqual(session.status, SimulationSession.Status.ACTIVE)
        self.assertEqual(session.activated_at.date(),
                         timezone.localdate())

    def test_update_session_renders_the_editable_fields(self):
        session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor,
            description='Practice', start_date=date(2026, 9, 25),
            status=SimulationSession.Status.SCHEDULED,
        )
        response = self.client.get(
            reverse('simulation:update_session', args=[session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Session 1"')
        self.assertContains(response, 'Practice')
        self.assertContains(response, 'value="2026-09-25"')
        self.assertContains(response,
                            f'value="{SimulationSession.Status.SCHEDULED}" selected')

    def test_a_student_may_not_update_a_session(self):
        other = User.objects.create_user(
            'studentwouldbe', password='pw', account_type=User.AccountType.STUDENT)
        session = SimulationSession.objects.create(
            name='Theirs', instructor=self.instructor)
        self.client.force_login(other)
        response = self.client.post(
            reverse('simulation:update_session', args=[session.pk]),
            {'name': 'Mine now', 'description': '', 'start_date': '',
             'end_date': '', 'status': SimulationSession.Status.DRAFT})
        self.assertRedirects(response, reverse('simulation:workspace'))
        session.refresh_from_db()
        self.assertEqual(session.name, 'Theirs')

    def test_update_session_rejects_a_future_start_while_activating(self):
        session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor,
            status=SimulationSession.Status.DRAFT,
        )
        response = self.client.post(
            reverse('simulation:update_session', args=[session.pk]),
            {
                'name': 'Session 1',
                'description': '',
                'start_date': '2999-12-31',
                'end_date': '',
                'status': SimulationSession.Status.ACTIVE,
            })
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.status, SimulationSession.Status.DRAFT)
        self.assertContains(response, 'starts in the future')

    def test_update_session_keeps_assignments_intact(self):
        session = SimulationSession.objects.create(
            name='Session 1', instructor=self.instructor)
        assignment = self.assign(
            self.arlyne, Role.HOTEL_FRONT_DESK, self.sunrise_est,
            activity_name='Activity 1')
        assignment.session = session
        assignment.save(update_fields=['session'])
        self.client.post(
            reverse('simulation:update_session', args=[session.pk]),
            {
                'name': 'Session 1 Renamed',
                'description': '',
                'start_date': '',
                'end_date': '',
                'status': SimulationSession.Status.SCHEDULED,
            })
        assignment.refresh_from_db()
        self.assertEqual(assignment.session_id, session.pk)


class AirlineFrontDeskRouteAccessTests(AssignmentFlowTestCase):
    """The airline staff role serves passengers without administering the airline."""

    def setUp(self):
        super().setUp()
        self.airline_est = Establishment.objects.create(
            name='Cebu Pacific', type=Establishment.Type.AIRLINE)
        self.assignment = self.assign(
            self.arlyne, Role.AIRLINE_FRONT_DESK, self.airline_est,
            activity_name='Ticketing Session',
        )
        airline = Airline.objects.create(name='Ticketing Test Airline')
        self.flight = Flight.objects.create(
            airline=airline, flight_number='TST-101',
            origin='Manila', destination='Cebu',
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
        )
        self.client.force_login(self.arlyne)

    def test_front_desk_can_search_and_retrieve_reservations(self):
        self.assertEqual(
            self.client.get(reverse('airlines:list')).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('airlines:bookings')).status_code, 200)

    def test_front_desk_can_view_flight_details_without_admin_controls(self):
        response = self.client.get(
            reverse('airlines:flight_detail', args=[self.flight.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TST-101')
        self.assertNotContains(response, reverse(
            'airlines:update_flight', args=[self.flight.pk]))
        self.assertNotContains(response, reverse(
            'airlines:flights'))
        self.assertContains(response, reverse('airlines:list'))

    def test_active_task_can_open_flight_details(self):
        session = self.client.session
        session['active_simulation_task_assignment'] = self.assignment.pk
        session.save()

        response = self.client.get(
            reverse('airlines:flight_detail', args=[self.flight.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse(
            'airlines:update_flight', args=[self.flight.pk]))

    def test_front_desk_cannot_open_airline_administration_routes(self):
        for route, args in (
            ('airlines:manage', ()),
            ('airlines:airline_detail', (1,)),
            ('airlines:aircrafts', ()),
            ('airlines:airline_fleet', (1,)),
            ('airlines:fleet_api', (1,)),
            ('airlines:services', ()),
            ('airlines:flights', ()),
            ('airlines:add_flight_schedule', ()),
        ):
            with self.subTest(route=route, args=args):
                response = self.client.get(reverse(route, args=args))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('dashboard'))

    def test_dashboard_exposes_the_front_desk_tools_without_admin_menus(self):
        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'Flight Search')
        self.assertContains(response, 'Retrieve Reservations')
        self.assertNotContains(response, 'Airline Admin')
        self.assertNotContains(response, 'Land Transportation')
        self.assertNotContains(response, 'User Admins')

    def test_front_desk_cannot_start_a_passenger_booking(self):
        response = self.client.get(reverse('airlines:book', args=[1]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('airlines:list'))

    def test_an_airline_manager_may_reach_the_administration_routes(self):
        """The Manager is the one airline role that owns the module."""
        manager = User.objects.create_user(
            'airlinemanager', password='pw', account_type=User.AccountType.STUDENT)
        self.assign(manager, Role.AIRLINE_MANAGER, self.airline_est,
                    activity_name='Manager Session')
        self.client.force_login(manager)
        self.assertEqual(
            self.client.get(reverse('airlines:manage')).status_code, 200)


class AirlinePassengerWorkspaceTaskTests(AssignmentFlowTestCase):
    def setUp(self):
        self.assignment = self.assign(
            self.arlyne, Role.PASSENGER_AIRLINE,
            activity_name='Passenger Session',
        )
        self.client.force_login(self.arlyne)

    def test_workspace_keeps_passenger_role_actions_organized(self):
        response = self.client.get(reverse('simulation:workspace'))

        self.assertContains(response, 'Do the Task')
        self.assertNotContains(response, 'Airline Passenger Tasks')

    def test_active_passenger_task_can_view_flight_detail_without_other_bookings(self):
        self.assign(
            self.arlyne, Role.HOTEL_MANAGER, self.sunrise_est,
            activity_name='Hotel Manager Activity')
        airline, _ = make_airline('Passenger Flight Test Airline')
        aircraft = make_aircraft(airline, 'A320', 'PAX-TEST')
        flight = Flight.objects.create(
            airline=airline,
            aircraft=aircraft,
            flight_number='PAX-101',
            origin='Manila',
            destination='Cebu',
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
        )
        self.client.get(reverse('simulation:do_task', args=[self.assignment.pk]))

        response = self.client.get(
            reverse('airlines:flight_detail', args=[flight.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PAX-101')
        self.assertFalse(response.context['can_manage_airline'])
        self.assertTrue(response.context['can_book_flight'])
        self.assertContains(
            response,
            f'href="{reverse("airlines:book", args=[flight.id])}"',
        )
        self.assertNotContains(response, 'Bookings (')
        booking_response = self.client.get(
            reverse('airlines:book', args=[flight.id]))
        self.assertEqual(booking_response.status_code, 200)
        self.assertTemplateUsed(booking_response, 'airlines/book.html')

    def test_passenger_cannot_view_flight_detail_without_active_task(self):
        airline = Airline.objects.create(name='Passenger Flight Test Airline')
        flight = Flight.objects.create(
            airline=airline,
            flight_number='PAX-102',
            origin='Manila',
            destination='Cebu',
            departure_time=timezone.now() + timedelta(days=2),
            arrival_time=timezone.now() + timedelta(days=2, hours=1),
        )

        response = self.client.get(
            reverse('airlines:flight_detail', args=[flight.slug]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))
