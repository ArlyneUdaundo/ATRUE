from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

from django.template.loader import get_template
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from airlines.models import Airport
from hotels.models import Hotel
from atrue_core.urls import home


class HomeSearchRoutingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.future = (date.today() + timedelta(days=5)).isoformat()
        self.later = (date.today() + timedelta(days=8)).isoformat()
        self.origin_airport = Airport.objects.create(
            airport_name="Ninoy Aquino International Airport",
            iata_code="MNL",
            city="Manila",
            country="Philippines",
        )
        self.destination_airport = Airport.objects.create(
            airport_name="Mactan-Cebu International Airport",
            iata_code="CEB",
            city="Cebu City",
            country="Philippines",
        )

    def search(self, **params):
        return home(self.factory.get("/", params))

    def test_flight_search_redirect_preserves_trip_and_passenger_choices(self):
        response = self.search(
            search_submit="1",
            tab="flights",
            origin_airport=str(self.origin_airport.pk),
            destination_airport=str(self.destination_airport.pk),
            check_in=self.future,
            check_out=self.later,
            trip_type="ROUND_TRIP",
            fare_class="BUSINESS",
            guests="3",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response["Location"]).path, reverse("airlines:list"))
        params = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(params["origin_airport"], [str(self.origin_airport.pk)])
        self.assertEqual(
            params["destination_airport"], [str(self.destination_airport.pk)]
        )
        self.assertEqual(params["search_submit"], ["1"])
        self.assertNotIn("origin", params)
        self.assertNotIn("destination", params)
        self.assertEqual(params["departure_date"], [self.future])
        self.assertEqual(params["return_date"], [self.later])
        self.assertEqual(params["trip_type"], ["ROUND_TRIP"])
        self.assertEqual(params["fare_class"], ["BUSINESS"])
        self.assertEqual(params["passengers"], ["3"])

    def test_flight_search_requires_a_selected_destination_airport(self):
        response = self.client.get(
            reverse("home"),
            {
                "search_submit": "1",
                "tab": "flights",
                "guests": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a flying-to airport.")
        self.assertContains(response, "Select the departure date.")
        self.assertNotContains(response, "Select a flying-from airport.")
        self.assertNotContains(
            response, "Choose a destination airport from the suggestions."
        )
        self.assertNotContains(response, "Departure date is required.")

    def test_flight_search_redirects_with_only_a_destination_airport(self):
        response = self.search(
            search_submit="1",
            tab="flights",
            destination_airport=str(self.destination_airport.pk),
            check_in=self.future,
            trip_type="ONE_WAY",
            guests="1",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response["Location"]).path, reverse("airlines:list"))
        params = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(params["search_submit"], ["1"])
        self.assertEqual(
            params["destination_airport"], [str(self.destination_airport.pk)]
        )
        self.assertNotIn("origin_airport", params)

    def test_one_way_search_does_not_require_or_send_a_return_date(self):
        response = self.search(
            search_submit="1",
            tab="flights",
            origin_airport=str(self.origin_airport.pk),
            destination_airport=str(self.destination_airport.pk),
            check_in=self.future,
            trip_type="ONE_WAY",
            guests="1",
        )

        self.assertEqual(response.status_code, 302)
        params = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(params["trip_type"], ["ONE_WAY"])
        self.assertNotIn("return_date", params)

    def test_round_trip_rejects_return_date_before_departure(self):
        response = self.client.get(
            reverse("home"),
            {
                "search_submit": "1",
                "tab": "flights",
                "origin_airport": self.origin_airport.pk,
                "destination_airport": self.destination_airport.pk,
                "check_in": self.later,
                "check_out": self.future,
                "trip_type": "ROUND_TRIP",
                "guests": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Return date cannot be earlier than departure."
        )

    def test_hotel_search_redirects_with_dates_guests_and_rooms(self):
        response = self.search(
            search_submit="1",
            tab="hotels",
            q="Palawan",
            check_in=self.future,
            check_out=self.later,
            adults="2",
            children="1",
            rooms="2",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response["Location"]).path, reverse("hotels:list"))
        params = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(params["q"], ["Palawan"])
        self.assertEqual(params["check_in"], [self.future])
        self.assertEqual(params["check_out"], [self.later])
        self.assertEqual(params["guests"], ["3"])
        self.assertEqual(params["adults"], ["2"])
        self.assertEqual(params["children"], ["1"])
        self.assertEqual(params["rooms"], ["2"])

    def test_restaurant_and_tour_dates_use_existing_catalog_parameter(self):
        restaurant_response = self.search(
            search_submit="1",
            tab="restaurants",
            q="Baggao",
            check_in=self.future,
            reservation_time="18:30",
            adults="3",
            children="0",
        )
        restaurant_query = parse_qs(urlsplit(restaurant_response["Location"]).query)
        self.assertEqual(urlsplit(restaurant_response["Location"]).path,
                         reverse("restaurants:list"))
        self.assertEqual(restaurant_query["date"], [self.future])
        self.assertEqual(restaurant_query["check_in"], [self.future])
        self.assertEqual(restaurant_query["time"], ["18:30"])
        self.assertEqual(restaurant_query["guests"], ["3"])

        tour_response = self.search(
            search_submit="1",
            tab="tours",
            q="Palawan",
            check_in=self.future,
            adults="2",
            children="1",
        )
        tour_query = parse_qs(urlsplit(tour_response["Location"]).query)
        self.assertEqual(urlsplit(tour_response["Location"]).path, reverse("home"))
        self.assertEqual(urlsplit(tour_response["Location"]).fragment, "live")
        self.assertEqual(tour_query["tab"], ["tours"])
        self.assertEqual(tour_query["q"], ["Palawan"])
        self.assertEqual(tour_query["check_in"], [self.future])

    def test_restaurant_search_requires_a_reservation_time(self):
        response = self.client.get(
            reverse("home"),
            {
                "search_submit": "1",
                "tab": "restaurants",
                "q": "Baggao",
                "check_in": self.future,
                "guests": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a reservation time.")

    def test_all_search_opens_combined_destination_results(self):
        response = self.search(search_submit="1", tab="all", q="Baguio")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response["Location"]).path, reverse("home"))
        self.assertEqual(urlsplit(response["Location"]).fragment, "live")
        params = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(params["tab"], ["all"])
        self.assertEqual(params["q"], ["Baguio"])
        results = self.client.get(
            reverse("home"), {"tab": "all", "q": "Baguio"}
        )
        for section in (
            "show_flights",
            "show_hotels",
            "show_resorts",
            "show_staycations",
            "show_restaurants",
            "show_spots",
            "show_activities",
            "show_packages",
        ):
            self.assertTrue(results.context[section])

    def test_tour_search_shows_existing_tours_activities_and_landmarks(self):
        response = self.client.get(
            reverse("home"), {"tab": "tours", "q": "Palawan"}
        )

        self.assertTrue(response.context["show_packages"])
        self.assertTrue(response.context["show_activities"])
        self.assertTrue(response.context["show_spots"])
        self.assertFalse(response.context["show_restaurants"])

    def test_all_search_requires_a_destination(self):
        response = self.client.get(
            reverse("home"),
            {"search_submit": "1", "tab": "all"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a destination or property to search.")

    def test_resort_and_staycation_searches_preserve_stay_dates(self):
        for tab, route_name in (
            ("resorts", "resorts:list"),
            ("staycations", "staycations:list"),
        ):
            with self.subTest(tab=tab):
                response = self.search(
                    search_submit="1",
                    tab=tab,
                    q="Cebu",
                    check_in=self.future,
                    check_out=self.later,
                    adults="2",
                    children="0",
                    rooms="1",
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(urlsplit(response["Location"]).path,
                                 reverse(route_name))
                query = parse_qs(urlsplit(response["Location"]).query)
                self.assertEqual(query["check_in"], [self.future])
                self.assertEqual(query["check_out"], [self.later])

    def test_home_and_destination_templates_compile(self):
        get_template("home.html")
        get_template("destination_detail.html")


class DestinationPageTests(TestCase):
    def test_home_renders_dynamic_destinations_without_rating_stars(self):
        Hotel.objects.create(
            name="Lake View Hotel",
            province="Cagayan",
            municipality="Baggao",
        )

        response = Client().get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-airport-picker')
        self.assertContains(response, 'id="destinationSuggestions" role="listbox"')
        self.assertContains(response, "Search destination")
        self.assertContains(response, 'class="hm-destination-option"')
        self.assertNotContains(response, 'id="flightOriginField"')
        self.assertNotContains(response, 'id="flightDestinationField"')

    def test_home_autocomplete_includes_active_property_names(self):
        Hotel.objects.create(
            name="Lake View Hotel",
            province="Cagayan",
            municipality="Baggao",
        )

        response = self.client.get(reverse("home"), {"tab": "hotels"})

        self.assertContains(
            response,
            'data-destination="Lake View Hotel" data-categories="all hotels"',
        )

    def test_home_autocomplete_excludes_city_country_and_airport_names(self):
        Airport.objects.create(
            airport_name="Example City International Airport",
            iata_code="XCT",
            city="Example City",
            country="Example Country",
            region="Example Region",
        )
        Airport.objects.create(
            airport_name="Closed City Airport",
            iata_code="CLO",
            city="Closed City",
            country="Example Country",
            status=Airport.Status.INACTIVE,
        )

        response = self.client.get(reverse("home"), {"tab": "hotels"})

        self.assertNotContains(response, 'data-destination="Example City"')
        self.assertNotContains(response, 'data-destination="Example Region"')
        self.assertNotContains(response, 'data-destination="Example Country"')
        self.assertNotContains(response, 'data-destination="Closed City"')

    def test_destination_shows_live_service_sections_and_real_search_links(self):
        response = Client().get(reverse("destination_detail", args=["palawan"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Flights in Palawan")
        self.assertContains(response, "Hotels in Palawan")
        self.assertContains(response, "Activities in Palawan")
        self.assertContains(response, "No hotels are listed for this destination yet.")
        self.assertContains(response, reverse("hotels:list") + "?q=Palawan")
        self.assertContains(response, reverse("airlines:list") + "?destination=Palawan")
