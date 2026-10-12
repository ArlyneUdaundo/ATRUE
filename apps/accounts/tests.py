"""Per-tab ("one tab = one ATRUE workspace") isolation tests.

Cookies are shared by every tab in a browser, so these tests drive a SINGLE
test Client for all tabs on purpose: that reproduces one browser's cookie jar
exactly, which is the only way a cross-tab leak shows up. Each tab carries its
own ``ctx`` token, the same opaque selector a real tab keeps in
``sessionStorage``.

Covered here:
  * five roles signed in simultaneously, one per tab;
  * each tab resolving its own identity, role and booking state;
  * refresh not switching users;
  * logging out one tab leaving the others signed in;
  * a request with no token inheriting nobody's login.
"""
from datetime import date, timedelta
from io import BytesIO
import json
import os
import re
import tempfile
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import AuthContext
from accounts.roles import (
    can_access_module, can_access_module_route, effective_role_keys,
    is_airline_booking_restricted, is_airline_ticketing_only,
)
from accounts.forms import ProfilePhotoForm
from accounts.views import is_admin_user
from simulation.models import SimulationRoleAssignment

# Absolute import (not a relative one) so this module also imports cleanly when
# the test runner discovers it as ``apps.accounts.tests``; a relative import
# would build a second, unregistered copy of the User model.
User = get_user_model()

PASSWORD = "TabTest!2345"
CSRF_FIELD = re.compile(rb'name="csrfmiddlewaretoken" value="([^"]+)"')
# (username, account_type, label). INSTRUCTOR is in MANAGEMENT_ACCOUNT_TYPES,
# so it legitimately manages accounts alongside ADMIN.
TABS = {
    1: ("tab1_guest", "STUDENT", "Guest"),
    2: ("tab2_admin", "ADMIN", "Administrator"),
    3: ("tab3_desk", "FRONT_DESK", "Front Desk"),
    4: ("tab4_instr", "INSTRUCTOR", "Instructor"),
    5: ("tab5_tour", "CUSTOMER_TOUR", "Travel Consultant"),
}
MANAGERS = ("ADMIN", "SYSTEM_ADMIN", "INSTRUCTOR")
ROOMS_B = 2


def _make_hotel(name, establishment_id, room_numbers):
    """A minimal ACTIVE hotel with AVAILABLE rooms, so the booking test does
    not depend on whatever fixture data happens to be in the database."""
    from decimal import Decimal

    from hotels.models import Hotel, Room

    hotel = Hotel.objects.create(
        name=name,
        establishment_id=establishment_id,
        status=Hotel.Status.ACTIVE,
    )
    rooms = []
    for number in room_numbers:
        rooms.append(Room.objects.create(
            hotel=hotel,
            room_number=number,
            room_id="%s-%s" % (establishment_id, number),
            room_type=Room.RoomType.DELUXE,
            rate=Decimal("4500.00"),
            status=Room.RoomStatus.AVAILABLE,
        ))
    return hotel, rooms


def _available_rooms(hotel_id, count, check_in, check_out):
    """Rooms the booking view will actually accept, using its own checks."""
    from hotels.models import Room
    from hotels.views import _room_date_conflict

    picked = []
    qs = Room.objects.filter(hotel_id=hotel_id, status=Room.RoomStatus.AVAILABLE)
    for room in qs.order_by("pk"):
        if not _room_date_conflict(room, check_in, check_out):
            picked.append(room.pk)
            if len(picked) == count:
                break
    return picked


class Tab:
    """One browser tab: its own token on top of the shared cookie jar.

    The tab also carries its own CSRF token, the way a real one does - it is
    read out of the page it last loaded and replayed on the next POST. The suite
    runs with ``enforce_csrf_checks=True`` on purpose: a login rotates the CSRF
    token, and when that rotation reached the shared browser cookie it silently
    invalidated the tokens already sitting in every other tab's forms. A client
    that does not enforce CSRF cannot see that failure at all.
    """

    def __init__(self, client, number, username, account_type):
        self.client = client
        self.number = number
        self.username = username
        self.account_type = account_type
        self.ctx = "test-ctx-token-for-tab-%d-abcdef" % number
        self.pk = None
        self._csrf = None

    def get(self, url, transport="header"):
        headers = {"HTTP_X_ATRUE_CTX": self.ctx} if transport != "query" else {}
        if transport == "query":
            url = "%s%sctx=%s" % (url, "&" if "?" in url else "?", self.ctx)
        response = self.client.get(url, **headers)
        found = CSRF_FIELD.search(response.content)
        if found:
            self._csrf = found.group(1).decode()
        return response

    def csrf(self):
        """The token this tab is currently holding, fetching one if needed.

        Sourced from ``/accounts/csrf/`` rather than by scraping the sign-in
        page: an already-signed-in tab is redirected straight off that page
        (it has no business being offered a second sign-in form), so it renders
        no ``{% csrf_token %}`` to scrape. The endpoint answers for any tab,
        signed in or not.
        """
        if self._csrf is None:
            headers = {"HTTP_X_ATRUE_CTX": self.ctx}
            response = self.client.get("/accounts/csrf/", **headers)
            self._csrf = json.loads(response.content)["csrf_token"]
        return self._csrf

    def post(self, url, data=None, transport="header"):
        headers = {"HTTP_X_ATRUE_CTX": self.ctx} if transport != "query" else {}
        if transport == "query":
            url = "%s%sctx=%s" % (url, "&" if "?" in url else "?", self.ctx)
        payload = dict(data or {})
        payload["ctx"] = self.ctx
        payload["csrfmiddlewaretoken"] = self.csrf()
        response = self.client.post(url, payload, **headers)
        if response.status_code == 200:
            found = CSRF_FIELD.search(response.content)
            if found:
                self._csrf = found.group(1).decode()
        return response

    def login(self):
        response = self.post("/accounts/login/",
                             {"username": self.username, "password": PASSWORD})
        # login() rotated the token; drop the stale one so the next POST reloads
        # it, exactly as a browser does by re-rendering after sign-in.
        self._csrf = None
        return response

    def logout(self):
        return self.post("/accounts/logout/")

    def context(self):
        return AuthContext.objects.filter(token=self.ctx).select_related("user").first()

    def bound_username(self):
        row = self.context()
        return row.user.username if row else None

    def store(self):
        import importlib

        return importlib.import_module(settings.SESSION_ENGINE).SessionStore(
            self.session_key())

    def session_key(self):
        row = self.context()
        return row.session_key if row else None

    def booking(self):
        return self.store().get("hotel_group_booking") or {}


class PerTabSessionIsolationTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.tabs = {}
        for number, (username, account_type, _label) in TABS.items():
            user = User.objects.create_user(
                username=username, password=PASSWORD, email=username + "@example.test")
            user.account_type = account_type
            user.is_active = True
            user.is_staff = account_type in ("ADMIN", "SYSTEM_ADMIN")
            user.save()
            tab = Tab(self.client, number, username, account_type)
            tab.pk = user.pk
            self.tabs[number] = tab

    # ------------------------------------------------------------------ auth
    def test_each_tab_binds_to_its_own_user_and_session(self):
        for tab in self.tabs.values():
            tab.login()
            self.assertEqual(tab.bound_username(), tab.username)

        keys = [t.session_key() for t in self.tabs.values()]
        self.assertEqual(len(set(keys)), len(TABS),
                         "every tab must own a distinct server-side session")

        # The shared cookie may be absent entirely (nothing has used it) or hold
        # a throwaway session, but it must never BE a tab's authenticated
        # session, otherwise one tab could authenticate another.
        cookie = self.client.cookies.get("sessionid")
        if cookie is not None:
            self.assertNotIn(cookie.value, set(keys),
                             "the shared cookie must not BE any tab's session")

    def test_identity_resolves_from_the_tab_not_the_cookie(self):
        for tab in self.tabs.values():
            tab.login()
        for tab in self.tabs.values():
            response = tab.get("/accounts/my-account/", transport="header")
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/accounts/%d/" % tab.pk,
                          response.headers["Location"])
            self.assertIn("ctx=" + tab.ctx, response.headers["Location"])

    def test_query_and_header_transport_agree(self):
        for tab in self.tabs.values():
            tab.login()
        for transport in ("header", "query"):
            for tab in self.tabs.values():
                response = tab.get("/accounts/my-account/", transport=transport)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/accounts/%d/" % tab.pk,
                              response.headers["Location"])
                self.assertIn("ctx=" + tab.ctx, response.headers["Location"])

    def test_role_gating_follows_the_tab(self):
        for tab in self.tabs.values():
            tab.login()
        for tab in self.tabs.values():
            response = tab.get("/accounts/accounts/")
            should_allow = tab.account_type in MANAGERS
            self.assertEqual(response.status_code == 200, should_allow,
                             "%s (%s) on account admin" % (tab.username, tab.account_type))

    # --------------------------------------------------------------- booking
    def test_two_tabs_hold_two_independent_bookings(self):
        today = date.today()
        ci_a, co_a = today + timedelta(days=30), today + timedelta(days=32)
        ci_b, co_b = today + timedelta(days=60), today + timedelta(days=64)
        hotel_a, made_a = _make_hotel("Tab Test Hotel A", "TSTA", ["101", "102", "103"])
        hotel_b, made_b = _make_hotel("Tab Test Hotel B", "TSTB", ["201", "202", "203"])
        rooms_a = _available_rooms(hotel_a.pk, 1, ci_a, co_a)
        rooms_b = _available_rooms(hotel_b.pk, ROOMS_B, ci_b, co_b)
        self.assertEqual(rooms_a, [made_a[0].pk])
        self.assertEqual(rooms_b, [made_b[0].pk, made_b[1].pk])

        one, five = self.tabs[1], self.tabs[5]
        one.login()
        five.login()

        for tab, hotel, ci, co, rooms, adults, children, pay in (
            (one, hotel_a.pk, ci_a, co_a, rooms_a, 1, 0, "GCA"),
            (five, hotel_b.pk, ci_b, co_b, rooms_b, 3, 1, "GCASH"),
        ):
            start = tab.get(
                reverse("hotels:group_start", args=[hotel])
                + "?check_in=%s&check_out=%s&rooms=%d&adults=%d"
                  % (ci, co, len(rooms), adults))
            self.assertEqual(start.status_code, 200)
            response = tab.post(
                reverse("hotels:group_select_rooms", args=[hotel]),
                {"room_ids": rooms, "check_in": ci.isoformat(),
                 "check_out": co.isoformat(), "adults": adults,
                 "children": children, "payment_method": pay})
            self.assertEqual(response.status_code, 302)
            landing = tab.get(response.headers["Location"].split("?")[0])
            self.assertEqual(landing.status_code, 200)
            self.assertIn("guest", response.headers["Location"].lower())

        a, b = one.booking(), five.booking()
        self.assertEqual(a["hotel_id"], hotel_a.pk)
        self.assertEqual(list(a["room_ids"]), rooms_a)
        self.assertEqual(a["check_in"], ci_a.isoformat())
        self.assertEqual(a["rooms_needed"], 1)
        self.assertEqual(b["hotel_id"], hotel_b.pk)
        self.assertEqual(list(b["room_ids"]), rooms_b)
        self.assertEqual(b["check_in"], ci_b.isoformat())
        self.assertEqual(b["rooms_needed"], ROOMS_B)
        self.assertNotEqual(a["payment_method"], b["payment_method"])

    def test_booking_state_survives_the_other_tab_and_a_logout(self):
        today = date.today()
        ci_a, co_a = today + timedelta(days=30), today + timedelta(days=32)
        ci_b, co_b = today + timedelta(days=60), today + timedelta(days=64)
        hotel_a, made_a = _make_hotel("Tab Test Hotel A", "TSTA", ["101", "102"])
        hotel_b, made_b = _make_hotel("Tab Test Hotel B", "TSTB", ["201", "202"])
        rooms_a = _available_rooms(hotel_a.pk, 1, ci_a, co_a)
        rooms_b = _available_rooms(hotel_b.pk, 1, ci_b, co_b)

        one, five = self.tabs[1], self.tabs[5]
        one.login()
        five.login()
        for tab, hotel, ci, co, rooms in (
            (one, hotel_a.pk, ci_a, co_a, rooms_a),
            (five, hotel_b.pk, ci_b, co_b, rooms_b),
        ):
            tab.post(reverse("hotels:group_select_rooms", args=[hotel]),
                     {"room_ids": rooms, "check_in": ci.isoformat(),
                      "check_out": co.isoformat(), "adults": 1,
                      "children": 0, "payment_method": "GCA"})

        one.logout()
        self.assertEqual(five.booking().get("room_ids"), rooms_b)
        self.assertEqual(five.booking().get("hotel_id"), hotel_b.pk)

    # --------------------------------------------------------- refresh/logout
    def test_refresh_does_not_switch_any_tab_to_another_user(self):
        for tab in self.tabs.values():
            tab.login()
        for _ in range(2):
            for tab in self.tabs.values():
                tab.get("/dashboard/")
        for tab in self.tabs.values():
            self.assertEqual(tab.bound_username(), tab.username)

    def test_logout_affects_only_its_own_tab(self):
        for tab in self.tabs.values():
            tab.login()
        self.tabs[1].logout()

        # The tab keeps an anonymous workspace so it can be shown the
        # confirmation, but that workspace grants no identity at all.
        signed_out = self.tabs[1].context()
        self.assertIsNotNone(signed_out, "tab 1 must keep its own context")
        self.assertIsNone(signed_out.user_id, "tab 1 must no longer be a user")

        response = self.tabs[1].get("/accounts/my-account/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.headers["Location"])
        for number in (2, 3, 4, 5):
            self.assertEqual(self.tabs[number].bound_username(),
                             self.tabs[number].username)

    def test_signed_out_tab_workspace_grants_no_access(self):
        """An anonymous context must not become a back door into user admin."""
        tab = self.tabs[2]
        tab.login()
        tab.logout()
        for url in ("/accounts/accounts/", "/dashboard/", "/"):
            self.assertNotEqual(tab.get(url).status_code, 403,
                                "signed-out context must not raise PermissionDenied")
        self.assertNotEqual(tab.get("/accounts/accounts/").status_code, 200)

    def test_logout_notice_is_read_only_by_the_tab_that_signed_out(self):
        """A browser-wide message queue hands the banner to whichever tab
        happens to render next - here, the tab that is still signed in."""
        one, two = self.tabs[1], self.tabs[2]
        one.login()
        two.login()
        one.get("/dashboard/")
        two.get("/dashboard/")

        one.logout()

        # The still-signed-in tab loads a page first and would win the race if
        # the queue were shared.
        self.assertFalse(b"been signed out" in two.get("/dashboard/").content,
                         "tab 2 saw tab 1's sign-out notice")
        self.assertTrue(b"been signed out" in one.get("/").content,
                        "tab 1 never saw its own sign-out notice")
        self.assertEqual(two.bound_username(), two.username)

    # ------------------------------------------------------------------ CSRF
    def test_signing_in_one_tab_leaves_other_tabs_forms_usable(self):
        """Regression: login() rotates the CSRF token.

        The five tabs each load the sign-in form - as happens when you open them
        all first and then type into them one at a time - and every one of them
        must still be able to submit. While the token lived in a browser-wide
        cookie, the first sign-in invalidated the forms already sitting in the
        other four tabs and their POSTs came back 403.
        """
        for tab in self.tabs.values():
            tab.get("/accounts/login/")

        for tab in self.tabs.values():
            response = tab.post("/accounts/login/",
                                {"username": tab.username, "password": PASSWORD})
            self.assertEqual(response.status_code, 302,
                             "%s was rejected by CSRF after another tab signed in"
                             % tab.username)

        for tab in self.tabs.values():
            self.assertEqual(tab.bound_username(), tab.username)

    def test_each_tab_keeps_its_own_csrf_secret(self):
        for tab in self.tabs.values():
            tab.login()
        secrets = [tab.store().get("_csrftoken") for tab in self.tabs.values()]
        self.assertTrue(all(secrets), "every tab needs a CSRF secret")
        self.assertEqual(len(set(secrets)), len(TABS),
                         "CSRF secrets must not be shared between tabs")
        self.assertNotIn("csrftoken", self.client.cookies,
                         "no browser-wide CSRF cookie may be issued")

    def test_authenticated_tab_can_post_a_form_after_another_tab_signed_in(self):
        """A real form POST from a page that was filled in before another tab
        signed in - the ordinary "I left the form open" case."""
        two, four, one = self.tabs[2], self.tabs[4], self.tabs[1]
        two.login()
        four.login()

        # Both manager tabs load a form and keep the token, as a browser does
        # while the page sits open.
        form = two.get("/accounts/create/")
        self.assertEqual(form.status_code, 200)
        two.get("/accounts/accounts/")

        # A third tab now signs in, rotating the CSRF token underneath them.
        one.login()

        response = two.post("/accounts/create/",
                            {"email": "new.person@example.test",
                             "first_name": "New", "last_name": "Person",
                             "account_type": "STUDENT"})
        self.assertNotEqual(response.status_code, 403,
                            "CSRF must not reject a tab because another tab signed in")
        # The form is re-rendered with validation errors, not a 403.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(one.bound_username(), one.username)
        self.assertEqual(two.bound_username(), two.username)
        self.assertEqual(four.bound_username(), four.username)

    # -------------------------------------------------------------- security
    def test_tokenless_request_inherits_nobody_login(self):
        for tab in self.tabs.values():
            tab.login()
        before = set(AuthContext.objects.values_list("token", flat=True))
        response = self.client.get("/accounts/accounts/")
        self.assertNotEqual(response.status_code, 200)
        after = set(AuthContext.objects.values_list("token", flat=True))
        new_for_test_users = {
            token for token in (after - before)
            if AuthContext.objects.filter(
                token=token,
                user__username__in=[v[0] for v in TABS.values()]).exists()
        }
        self.assertEqual(new_for_test_users, set(),
                         "an anonymous request must not adopt a signed-in tab")

    def test_unknown_token_gets_no_privilege(self):
        response = self.client.get("/accounts/accounts/",
                                   HTTP_X_ATRUE_CTX="never-issued-token")
        self.assertNotEqual(response.status_code, 200)

    def test_token_alone_does_not_authenticate_without_a_session(self):
        """A leaked/guessed selector is useless without its live session."""
        tab = self.tabs[2]
        tab.login()
        stale = self.client.get("/accounts/accounts/",
                                HTTP_X_ATRUE_CTX=tab.ctx)
        self.assertEqual(stale.status_code, 200)

        # Deleting the backing session must strip access for that token.
        from importlib import import_module

        store = import_module(settings.SESSION_ENGINE)
        store.SessionStore(tab.session_key()).flush()
        after = self.client.get("/accounts/accounts/", HTTP_X_ATRUE_CTX=tab.ctx)
        self.assertNotEqual(after.status_code, 200)


class PerTabSessionCreationTests(TestCase):
    def setUp(self):
        self.client = Client()

    def new_tab_tokens(self):
        # Exercise more contexts than the legacy five-user isolation fixture.
        # The application itself has no corresponding tab count.
        return [uuid4().hex for _ in range(12)]

    def session_for(self, context):
        from importlib import import_module

        engine = import_module(settings.SESSION_ENGINE)
        return engine.SessionStore(context.session_key)

    def test_anonymous_tabs_get_distinct_workflow_sessions(self):
        tokens = self.new_tab_tokens()
        contexts = []

        for token in tokens:
            response = self.client.get(
                reverse('accounts:csrf_token'),
                HTTP_X_ATRUE_CTX=token,
            )
            self.assertEqual(response.status_code, 200)
            context = AuthContext.objects.get(token=token)
            self.assertIsNone(context.user_id)
            contexts.append(context)

        session_keys = [context.session_key for context in contexts]
        self.assertEqual(len(set(session_keys)), len(tokens))

        for index, (token, context) in enumerate(zip(tokens, contexts)):
            session = self.session_for(context)
            session['workflow_state'] = {
                'establishment': f'hotel-{index}',
                'guest': f'guest-{index}',
                'booking': f'booking-{index}',
                'filter': f'filter-{index}',
                'page': index + 1,
            }
            session.save()

        for index, (token, context) in enumerate(zip(tokens, contexts)):
            response = self.client.get(
                reverse('accounts:csrf_token'),
                HTTP_ATRUE_CTX=token,
            )
            self.assertEqual(response.status_code, 200)
            context.refresh_from_db()
            self.assertEqual(context.session_key, session_keys[index])
            state = self.session_for(context).get('workflow_state')
            self.assertEqual(state['establishment'], f'hotel-{index}')
            self.assertEqual(state['guest'], f'guest-{index}')
            self.assertEqual(state['booking'], f'booking-{index}')
            self.assertEqual(state['filter'], f'filter-{index}')
            self.assertEqual(state['page'], index + 1)

    def test_authenticated_tabs_keep_the_same_user_but_separate_workflows(self):
        user = User.objects.create_user(
            username='multi_tab_user',
            password=PASSWORD,
        )
        self.client.force_login(user)
        shared_auth_session_key = self.client.session.session_key
        tokens = self.new_tab_tokens()

        contexts = []
        for token in tokens:
            cookie_session = self.client.session
            self.assertEqual(cookie_session.get('_auth_user_id'), str(user.pk))
            response = self.client.get(
                reverse('accounts:csrf_token'),
                HTTP_X_ATRUE_CTX=token,
            )
            self.assertEqual(response.status_code, 200)
            context = AuthContext.objects.get(token=token)
            self.assertEqual(context.user_id, user.pk)
            contexts.append(context)

        session_keys = [context.session_key for context in contexts]
        self.assertEqual(len(set(session_keys)), len(tokens))
        self.assertNotIn(shared_auth_session_key, session_keys)

        for index, (token, context) in enumerate(zip(tokens, contexts)):
            session = self.session_for(context)
            session['hotel_group_booking'] = {
                'hotel_id': index + 1,
                'guest_name': f'Guest {index + 1}',
            }
            session.save()

        for index, (token, context) in enumerate(zip(tokens, contexts)):
            response = self.client.get(
                reverse('accounts:csrf_token'),
                HTTP_X_ATRUE_CTX=token,
            )
            self.assertEqual(response.status_code, 200)
            context.refresh_from_db()
            self.assertEqual(context.user_id, user.pk)
            booking = self.session_for(context).get('hotel_group_booking')
            self.assertEqual(booking['hotel_id'], index + 1)
            self.assertEqual(booking['guest_name'], f'Guest {index + 1}')

    def test_duplicated_tab_copies_identity_but_not_workflow_state(self):
        user = User.objects.create_user(
            username='duplicated_tab_user',
            password=PASSWORD,
        )
        self.client.force_login(user)
        source_token, duplicate_token = self.new_tab_tokens()[:2]

        self.client.get(
            reverse('accounts:csrf_token'),
            HTTP_X_ATRUE_CTX=source_token,
        )
        source_context = AuthContext.objects.get(token=source_token)
        source_session = self.session_for(source_context)
        source_session['hotel_group_booking'] = {
            'hotel_id': 42,
            'guest_name': 'Original tab guest',
        }
        source_session.save()

        response = self.client.get(
            reverse('accounts:csrf_token') + '?source_ctx=' + source_token,
            HTTP_X_ATRUE_CTX=duplicate_token,
        )
        self.assertEqual(response.status_code, 200)

        duplicate_context = AuthContext.objects.get(token=duplicate_token)
        self.assertEqual(duplicate_context.user_id, user.pk)
        self.assertNotEqual(duplicate_context.session_key, source_context.session_key)
        duplicate_session = self.session_for(duplicate_context)
        self.assertEqual(duplicate_session.get('_auth_user_id'), str(user.pk))
        self.assertIsNone(duplicate_session.get('hotel_group_booking'))
        self.assertEqual(
            source_session.get('hotel_group_booking')['guest_name'],
            'Original tab guest',
        )


class AdminAccessRoleNormalizationTests(TestCase):
    def test_active_system_admin_role_matches_account_type_permissions(self):
        user = User.objects.create_user(
            username='role_admin',
            password=PASSWORD,
            email='role_admin@example.test',
            account_type='STUDENT',
        )
        SimulationRoleAssignment.objects.create(
            student=user,
            assigned_by=user,
            role=SimulationRoleAssignment.Role.SYSTEM_ADMINISTRATOR,
            activity_name='Admin Trial',
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )

        self.assertIn('SYSTEM_ADMIN', effective_role_keys(user))
        self.assertTrue(is_admin_user(user))
        self.assertTrue(can_access_module(user, 'hotels'))
        self.assertTrue(can_access_module(user, 'transactions'))

    def test_inactive_system_admin_role_does_not_keep_admin_access(self):
        user = User.objects.create_user(
            username='role_admin_revoked',
            password=PASSWORD,
            email='role_admin_revoked@example.test',
            account_type='STUDENT',
        )
        assignment = SimulationRoleAssignment.objects.create(
            student=user,
            assigned_by=user,
            role=SimulationRoleAssignment.Role.SYSTEM_ADMINISTRATOR,
            activity_name='Admin Trial',
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )

        self.assertTrue(is_admin_user(user))
        assignment.status = SimulationRoleAssignment.AssignmentStatus.INACTIVE
        assignment.save(update_fields=['status'])
        self.assertNotIn('SYSTEM_ADMIN', effective_role_keys(user))
        self.assertFalse(is_admin_user(user))


class AirlineTicketingOfficerAccessTests(TestCase):
    """An airline staff role serves passengers without administering the airline.

    Uses the current ``AIRLINE_FRONT_DESK`` rather than the retired
    ``AIRLINE_TICKETING_OFFICER``: an operational role must name the airline it is
    performed in, and the retired code is no longer offered.
    """

    def setUp(self):
        from establishments.models import Establishment

        self.user = User.objects.create_user(
            username='ticketing_officer',
            email='ticketing_officer@example.test',
            account_type='STUDENT',
        )
        self.airline = Establishment.objects.create(
            name='Ticketing Test Airline', type=Establishment.Type.AIRLINE)
        self.assignment = SimulationRoleAssignment.objects.create(
            student=self.user,
            role=SimulationRoleAssignment.Role.AIRLINE_FRONT_DESK,
            establishment=self.airline,
            activity_name='Session 1',
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )

    def test_ticketing_role_grants_only_ticketing_airline_routes(self):
        self.assertTrue(is_airline_ticketing_only(self.user))
        self.assertTrue(is_airline_booking_restricted(self.user))
        self.assertFalse(can_access_module(self.user, 'airlines'))
        for route in (
            'list', 'airports_api', 'bookings',
            'booking_detail', 'flight_detail', 'ticket', 'ticket_pdf',
            'itinerary_public_detail',
        ):
            with self.subTest(route=route):
                self.assertTrue(can_access_module_route(self.user, 'airlines', route))

        for route in (
            'manage', 'airline_detail', 'aircrafts', 'aircraft_detail',
            'airline_fleet', 'fleet_api', 'services', 'service_detail',
            'flights', 'itinerary_detail', 'add_flight',
            'update_flight', 'book',
        ):
            with self.subTest(route=route):
                self.assertFalse(can_access_module_route(self.user, 'airlines', route))

    def test_revoking_ticketing_role_removes_airline_access(self):
        self.assignment.status = SimulationRoleAssignment.AssignmentStatus.INACTIVE
        self.assignment.save(update_fields=['status'])

        self.assertFalse(is_airline_ticketing_only(self.user))
        self.assertFalse(can_access_module_route(self.user, 'airlines', 'bookings'))

    def test_other_active_roles_keep_their_own_access(self):
        from establishments.models import Establishment

        hotel_assignment = SimulationRoleAssignment.objects.create(
            student=self.user,
            role=SimulationRoleAssignment.Role.HOTEL_MANAGER,
            establishment=Establishment.objects.create(
                name='Ticketing Test Hotel', type=Establishment.Type.HOTEL),
            activity_name='Hotel Session',
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )

        self.assertFalse(is_airline_ticketing_only(self.user))
        self.assertTrue(can_access_module_route(self.user, 'airlines', 'bookings'))
        self.assertTrue(can_access_module(self.user, 'hotels'))
        self.assertTrue(is_airline_booking_restricted(self.user))
        self.client.force_login(self.user)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, 'Flight Search')
        self.assertContains(dashboard, 'Hotel Admin')
        hotel_assignment.status = SimulationRoleAssignment.AssignmentStatus.INACTIVE
        hotel_assignment.save(update_fields=['status'])
        self.assertTrue(can_access_module_route(self.user, 'airlines', 'bookings'))

    def test_passenger_role_keeps_its_booking_rights_with_ticketing_role(self):
        SimulationRoleAssignment.objects.create(
            student=self.user,
            role=SimulationRoleAssignment.Role.PASSENGER_AIRLINE,
            activity_name='Passenger Session',
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )

        self.assertFalse(is_airline_booking_restricted(self.user))


class ActivityAndTourPackageRoleAccessTests(TestCase):
    def test_role_accounts_get_their_domain_access_and_dashboard(self):
        roles = (
            # (account_type, module, has_module_access, staff_route, dashboard_label)
            ('ACTIVITY_MANAGER', 'activities', True, 'bookings', 'Activity Manager'),
            ('ACTIVITY_RESERVATION_OFFICER', 'activities', False, 'bookings',
             'Activity Reservation Officer'),
            ('ACTIVITY_OPERATOR', 'activities', False, 'operate',
             'Activity / Tour Operator'),
            ('TOUR_PACKAGE_MANAGER', 'tour_package', True, 'bookings',
             'Tour Package Manager'),
            ('TOUR_PACKAGE_RESERVATION_OFFICER', 'tour_package', False, 'bookings',
             'Tour Package Reservation Officer'),
            ('TOUR_PACKAGE_OPERATOR', 'tour_package', False, 'operate',
             'Tour Operator'),
        )
        for role, module, has_module, staff_route, label in roles:
            with self.subTest(role=role):
                user = User.objects.create_user(
                    username=role.lower(),
                    email=f'{role.lower()}@example.test',
                    account_type=role,
                )
                self.assertEqual(
                    can_access_module(user, module),
                    has_module,
                )
                self.assertTrue(
                    can_access_module_route(user, module, staff_route),
                )
                self.assertEqual(
                    can_access_module_route(user, module, 'manage'),
                    has_module,
                )
                # The route allowlist never implies whole-module management
                # (a Manager already has whole-module access by virtue of the
                # module itself).
                if not has_module:
                    self.assertFalse(
                        can_access_module_route(
                            user, module,
                            'add_provider' if module == 'activities'
                            else 'add_package'),
                    )
                self.client.force_login(user)
                dashboard = self.client.get(reverse('dashboard'))
                self.assertEqual(dashboard.status_code, 200)
                self.assertContains(dashboard, label)


class UserProfilePictureTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_dir.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        self.user = User.objects.create_user(
            username='picture_owner',
            password=PASSWORD,
            account_type='STUDENT',
        )
        self.client.force_login(self.user)
        self.update_url = reverse('accounts:account_update', args=[self.user.pk])

    def png_upload(self, name, color):
        from PIL import Image

        image = Image.new('RGB', (3, 2), color=color)
        image_bytes = BytesIO()
        image.save(image_bytes, format='PNG')
        return SimpleUploadedFile(name, image_bytes.getvalue(), content_type='image/png')

    def test_upload_appears_in_the_existing_avatar_and_persists_after_login(self):
        response = self.client.post(self.update_url, {
            'profile_picture': self.png_upload('profile.png', 'red'),
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_picture.name.startswith(
            f'profile_pictures/user_{self.user.pk}/'))

        self.client.logout()
        self.client.force_login(self.user)
        avatar_markup = f'<img src="{self.user.profile_picture.url}" alt="">'
        for url in (self.update_url, reverse('accounts:account_detail', args=[self.user.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, avatar_markup, html=True)

    def test_account_page_keeps_username_initial_when_no_picture_exists(self):
        response = self.client.get(reverse('accounts:account_detail', args=[self.user.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="profile-photo profile-photo-empty"')
        self.assertContains(
            response,
            '<span class="profile-photo-initials" aria-hidden="true">P</span>',
            html=True,
        )

    def test_picture_can_be_replaced_and_cleared(self):
        self.client.post(self.update_url, {
            'profile_picture': self.png_upload('first.png', 'red'),
        })
        self.user.refresh_from_db()
        first_picture = self.user.profile_picture.name

        self.client.post(self.update_url, {
            'profile_picture': self.png_upload('second.png', 'blue'),
        })
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.profile_picture.name, first_picture)

        self.client.post(self.update_url, {'profile_picture-clear': 'on'})
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_picture)
        response = self.client.get(self.update_url)
        # The profile page falls back to the account's initials once the stored
        # photo is gone.
        profile = self.client.get(reverse('accounts:account_detail', args=[self.user.pk]))
        self.assertContains(
            profile,
            '<span class="profile-photo-initials" aria-hidden="true">P</span>',
            html=True,
        )

    def test_manager_cannot_edit_another_users_profile_picture(self):
        manager = User.objects.create_user(
            username='picture_manager',
            password=PASSWORD,
            account_type='ADMIN',
            is_staff=True,
        )
        target = User.objects.create_user(username='picture_target', password=PASSWORD)
        self.client.force_login(manager)

        response = self.client.get(reverse('accounts:account_update', args=[target.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="profile_picture"')


class UserInitialsTests(TestCase):
    """The default avatar has to say who the account is.

    The navigation avatar used to render the first character of the whole user
    object, which happened to be the first letter of the name but by accident,
    and nothing at all for an account with no name. These lock in the rule.
    """

    def initials_for(self, **kwargs):
        user = User.objects.create_user(
            username=kwargs.pop('username', 'initials_user'),
            password=PASSWORD,
            **kwargs,
        )
        return user.initials

    def test_uses_first_and_last_name_when_present(self):
        self.assertEqual(
            self.initials_for(first_name='Aica', last_name='Santos'), 'AS')

    def test_prefers_the_middle_name_over_the_last_name_when_there_is_no_last(self):
        self.assertEqual(
            self.initials_for(first_name='Arlyne', middle_name='Joy'), 'AJ')

    def test_uses_the_middle_initial_when_no_middle_name(self):
        self.assertEqual(
            self.initials_for(first_name='Juan', middle_initial='D.'), 'JD')

    def test_falls_back_to_the_first_name_alone(self):
        self.assertEqual(self.initials_for(first_name='Maria'), 'M')

    def test_falls_back_to_the_username_when_the_account_has_no_name(self):
        self.assertEqual(self.initials_for(username='zandro'), 'Z')

    def test_never_returns_an_empty_avatar(self):
        user = User.objects.create_user(username='xavier', password=PASSWORD)
        self.assertTrue(user.initials, 'an avatar with no letter looks broken')


class ProfileHeaderLayoutTests(TestCase):
    """The profile header's structure: photo, then name, then handle, then actions."""

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_dir.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        self.user = User.objects.create_user(
            username='aica', password=PASSWORD, first_name='Aica',
            middle_name='Santos', last_name='Dela Cruz',
            email='aica@example.com', account_type='STUDENT',
        )
        self.client.force_login(self.user)
        self.detail_url = reverse('accounts:account_detail', args=[self.user.pk])

    def png_upload(self, name='photo.png', color='red'):
        from PIL import Image

        image = Image.new('RGB', (8, 8), color=color)
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def test_header_places_the_photo_above_the_name_username_and_actions(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        photo = body.index('class="profile-photo profile-photo-empty"')
        name = body.index('class="profile-hero-name"')
        handle = body.index('class="profile-hero-handle"')
        actions = body.index('class="profile-hero-actions"')
        self.assertLess(photo, name, 'the photo must come before the name')
        self.assertLess(name, handle, 'the username must come after the name')
        self.assertLess(handle, actions, 'the actions must come last')

    def test_header_shows_the_full_name_and_the_username(self):
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'Aica Dela Cruz')
        self.assertContains(response, '@aica')

    def test_header_offers_edit_profile(self):
        response = self.client.get(self.detail_url)
        self.assertContains(response, reverse('accounts:account_update', args=[self.user.pk]))
        self.assertContains(response, 'Edit Profile')

    def test_header_change_photo_button_opens_the_photo_panel(self):
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'Change Photo')
        self.assertContains(response, 'aria-controls="profilePhotoPanel"')
        self.assertContains(response, 'id="profilePhotoInput"')

    def test_account_information_is_shown_in_its_own_sections(self):
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'Personal Information')
        self.assertContains(response, 'Account Information')
        self.assertContains(response, 'Account Role')
        self.assertContains(response, 'Account Status')
        self.assertContains(response, self.user.get_account_type_display())
        self.assertContains(response, self.user.get_status_display())
        self.assertContains(response, 'aica@example.com')

    def test_photo_is_rendered_from_the_saved_upload(self):
        self.client.post(self.detail_url, {
            'profile_picture': self.png_upload(),
        })
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_picture)

        response = self.client.get(self.detail_url)
        self.assertContains(
            response, f'src="{self.user.profile_picture.url}"')

    def test_photo_panel_starts_closed_and_opens_on_the_change_photo_button(self):
        response = self.client.get(self.detail_url)
        body = response.content.decode()

        # The panel and its toggle are wired to each other: the panel carries the
        # ``hidden`` attribute on a clean load, and the button says collapsed.
        self.assertIn('id="profilePhotoPanel"', body)
        panel_at = body.index('id="profilePhotoPanel"')
        self.assertIn('hidden', body[panel_at:panel_at + 200],
                      'the photo panel must start closed')
        self.assertIn('id="profilePhotoToggle"', body)
        self.assertIn('aria-controls="profilePhotoPanel"', body)

    def test_a_rejected_upload_redisplays_the_panel_with_the_error(self):
        response = self.client.post(self.detail_url, {
            'profile_picture': SimpleUploadedFile(
                'notes.txt', b'this is not an image', content_type='text/plain'),
        })
        self.assertEqual(response.status_code, 200)
        # The panel has to be open, or the error is invisible to the user.
        self.assertContains(response, 'aria-labelledby')
        self.assertContains(response, 'not an image or a corrupted image')
        self.assertFalse(self.user.profile_picture)


class ProfilePhotoUploadTests(TestCase):
    """Upload, preview, change, remove, save -- from the profile page itself."""

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_dir.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        self.user = User.objects.create_user(
            username='photographer', password=PASSWORD,
            first_name='Aica', last_name='Santos')
        self.client.force_login(self.user)
        self.detail_url = reverse('accounts:account_detail', args=[self.user.pk])
        self.remove_url = reverse('accounts:account_photo_remove', args=[self.user.pk])

    def png_upload(self, name='photo.png', color='red', size=(8, 8)):
        from PIL import Image

        image = Image.new('RGB', size, color=color)
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def upload(self, **overrides):
        data = {'profile_picture': self.png_upload()}
        data.update(overrides)
        return self.client.post(self.detail_url, data)

    def stored_path(self):
        self.user.refresh_from_db()
        return str(self.user.profile_picture.path)

    def test_saving_a_photo_from_the_profile_page_persists_it(self):
        response = self.upload()
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_picture.name.startswith(
            f'profile_pictures/user_{self.user.pk}/'))

    def saved_url(self):
        self.user.refresh_from_db()
        return self.user.profile_picture.url

    def test_the_saved_photo_survives_logging_out_and_back_in(self):
        self.upload()
        expected = self.saved_url()

        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get(self.detail_url)
        self.assertContains(response, f'src="{expected}"')

    def test_the_photo_survives_a_page_refresh(self):
        self.upload()
        expected = self.saved_url()
        for _ in range(2):
            with self.subTest(refresh='reload'):
                response = self.client.get(self.detail_url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'src="{expected}"')

    def test_a_second_upload_replaces_the_first_and_deletes_the_old_file(self):
        self.upload()
        first_path = self.stored_path()
        self.assertTrue(os.path.exists(first_path))

        self.upload(color='blue')
        self.assertNotEqual(self.stored_path(), first_path)
        self.assertFalse(
            os.path.exists(first_path),
            'a replaced photo must not be left behind on disk')

    def test_the_photo_can_be_removed_from_the_profile_page(self):
        self.upload()
        removed_path = self.stored_path()

        response = self.client.post(self.remove_url)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_picture)
        self.assertFalse(os.path.exists(removed_path))

        # Back to the initials avatar.
        self.assertContains(
            self.client.get(self.detail_url),
            '<span class="profile-photo-initials" aria-hidden="true">AS</span>',
            html=True,
        )

    def test_removing_without_a_photo_is_harmless(self):
        response = self.client.post(self.remove_url)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_picture)

    def test_removing_ignores_a_get_request(self):
        self.upload()
        expected = self.saved_url()
        response = self.client.get(self.remove_url)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.profile_picture.url, expected,
                         'a GET must not delete a file')

    def test_a_non_image_is_rejected_with_a_readable_message(self):
        response = self.client.post(self.detail_url, {
            'profile_picture': SimpleUploadedFile(
                'resume.pdf', b'%PDF-1.4 not an image', content_type='application/pdf'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not an image or a corrupted image')
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_picture)

    def test_an_oversized_photo_is_rejected(self):
        # A flat colour compresses to almost nothing, so the pixels are random:
        # the point is the *uploaded* byte count, not the image dimensions.
        from PIL import Image

        image = Image.frombytes(
            'RGB', (1400, 1400), os.urandom(1400 * 1400 * 3))
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        oversized = SimpleUploadedFile(
            'huge.png', buffer.getvalue(), content_type='image/png')
        self.assertGreater(oversized.size, ProfilePhotoForm.MAX_BYTES)

        response = self.client.post(
            self.detail_url, {'profile_picture': oversized})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please choose one under 2 MB')
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_picture)

    def test_an_account_manager_cannot_remove_another_users_photo(self):
        self.upload()
        expected = self.saved_url()

        manager = User.objects.create_user(
            username='photo_admin', password=PASSWORD,
            account_type='ADMIN', is_staff=True)
        self.client.force_login(manager)
        response = self.client.post(
            reverse('accounts:account_photo_remove', args=[self.user.pk]))
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertEqual(self.user.profile_picture.url, expected)
        self.assertNotContains(
            self.client.get(reverse('accounts:account_detail', args=[self.user.pk])),
            'Save Photo',
            msg_prefix='a manager must not be offered the photo controls')

    def test_the_photo_controls_are_absent_from_another_users_profile(self):
        self.upload()
        manager = User.objects.create_user(
            username='viewer_admin', password=PASSWORD,
            account_type='ADMIN', is_staff=True)
        self.client.force_login(manager)
        response = self.client.get(reverse('accounts:account_detail', args=[self.user.pk]))
        self.assertNotContains(response, 'id="profilePhotoPanel"')
        self.assertNotContains(response, 'Save Photo')


class NavigationAvatarTests(TestCase):
    """The top-right account area shows the photo, or the initials."""

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_dir.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        self.user = User.objects.create_user(
            username='navuser', password=PASSWORD,
            first_name='Aica', middle_name='Joy', last_name='Santos')

    def upload_photo(self):
        from PIL import Image

        image = Image.new('RGB', (8, 8), color='red')
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        self.client.force_login(self.user)
        self.client.post(reverse('accounts:account_detail', args=[self.user.pk]), {
            'profile_picture': SimpleUploadedFile(
                'nav.png', buffer.getvalue(), content_type='image/png'),
        })
        self.user.refresh_from_db()

    def test_navigation_shows_the_uploaded_photo(self):
        self.upload_photo()
        response = self.client.get(reverse('simulation:workspace'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<span class="avatar"><img src="{self.user.profile_picture.url}" alt=""></span>',
            html=True)

    def test_navigation_shows_initials_when_there_is_no_photo(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('simulation:workspace'))
        self.assertContains(
            response, '<span class="avatar">AJ</span>', html=True)
