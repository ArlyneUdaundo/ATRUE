from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from locations.models import CityMunicipality, Country, Province, Region

from hotels.models import Amenity, Booking, Hotel, Room, Service


class HotelDetailPresentationTests(TestCase):
    def setUp(self):
        self.hotel = Hotel.objects.create(
            name='Detail Page Hotel', status=Hotel.Status.ACTIVE,
        )
        self.url = reverse('hotels:detail', args=[self.hotel.pk])

    def test_empty_rooms_services_and_amenities_use_compact_empty_states(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No rooms available yet')
        self.assertContains(
            response,
            'Room options will appear here once they are added by the administrator.',
        )
        self.assertContains(response, 'No services have been listed yet.')
        self.assertContains(response, 'No amenities have been listed yet.')
        self.assertContains(response, 'hotel-empty-state')
        self.assertNotContains(response, 'class="empty"')

    def test_real_room_service_and_amenity_data_and_booking_action_render(self):
        room = Room.objects.create(
            hotel=self.hotel, room_number='201', room_type=Room.RoomType.DOUBLE,
            capacity_adults=2, capacity_children=1, rate='4200.00',
            additional_guest_charge='350.00',
            features='Two beds, private balcony',
        )
        self.hotel.contact_number = '09171234567'
        self.hotel.email = 'stay@example.com'
        self.hotel.operating_schedule = 'Open daily, 8 AM–10 PM'
        self.hotel.save()
        Service.objects.create(
            hotel=self.hotel, name='Airport transfer', rate='750.00',
        )
        Service.objects.create(hotel=self.hotel, name='Daily housekeeping', rate='0.00')
        Amenity.objects.create(hotel=self.hotel, name='Swimming pool')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Room {room.room_number}')
        self.assertContains(response, 'Double room')
        self.assertContains(response, 'Two beds, private balcony')
        self.assertContains(response, '4200.00')
        self.assertContains(response, '350.00 per extra guest / night')
        self.assertContains(response, '<h2>Services</h2>', html=True)
        self.assertContains(response, 'Airport transfer')
        self.assertContains(response, 'Paid')
        self.assertContains(response, 'Complimentary')
        self.assertContains(response, 'Swimming pool')
        self.assertContains(response, '09171234567')
        self.assertContains(response, 'stay@example.com')
        self.assertContains(response, 'Open daily, 8 AM–10 PM')
        self.assertContains(response, 'Book')
        self.assertNotContains(response, 'No rooms available yet')
        self.assertNotContains(response, 'No services have been listed yet.')
        self.assertNotContains(response, 'No amenities have been listed yet.')

    def test_multiple_room_cards_keep_long_room_details_inside_the_listing(self):
        Room.objects.create(
            hotel=self.hotel, room_number='PENTHOUSE-202-LONG',
            room_type=Room.RoomType.SUITE, capacity_adults=4,
            capacity_children=2, rate='9800.00',
            features='King bed, lounge area, ocean-facing balcony, air conditioning',
        )
        Room.objects.create(
            hotel=self.hotel, room_number='FAMILY-203',
            room_type=Room.RoomType.FAMILY, capacity_adults=3,
            capacity_children=3, rate='6200.00',
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b'class="hotel-room-card"'), 2)
        self.assertContains(response, 'Room PENTHOUSE-202-LONG')
        self.assertContains(response, 'ocean-facing balcony')
        self.assertContains(response, 'Room FAMILY-203')
        self.assertEqual(response.content.count(b'class="ag-btn btn-sm"'), 2)


class HotelCountryTests(TestCase):
    """Worldwide Country -> Province -> City cascade on the hotel forms."""

    @classmethod
    def setUpTestData(cls):
        cls.ph = Country.objects.create(
            geoname_id=1694008, code='PH', name='Philippines',
            asciiname='Republic of the Philippines',
            latitude=13.40882, longitude=122.56155, feature_code='PCLI',
        )
        region_ph = Region.objects.create(
            geoname_id=7521301, code='01', name='Ilocos', country=cls.ph,
        )
        cls.pangasinan = Province.objects.create(
            geoname_id=1695357, code='51', name='Pangasinan', region=region_ph,
        )
        CityMunicipality.objects.create(
            geoname_id=1683502, code='015533000', name='Dagupan City', province=cls.pangasinan,
        )
        Hotel.objects.create(
            name='Pangasinan Lodge', country='Philippines',
            province='Pangasinan', municipality='Dagupan City',
        )

        cls.thailand = Country.objects.create(
            geoname_id=8350000, code='TH', name='Thailand', asciiname='Thailand',
        )
        region_th = Region.objects.create(
            geoname_id=8350001, code='01', name='Bangkok', country=cls.thailand,
        )
        cls.bangkok = Province.objects.create(
            geoname_id=8350002, code='A10', name='Bangkok', region=region_th,
        )
        CityMunicipality.objects.create(
            geoname_id=8350003, code='1001', name='Bangkok', province=cls.bangkok,
        )

    def setUp(self):
        from atrue_core.context_processors import _location_tree_cached
        _location_tree_cached.cache_clear()
        self.manager = get_user_model().objects.create_user('manager', password='pw', is_staff=True)
        self.client.force_login(self.manager)

    def test_add_hotel_in_a_foreign_country(self):
        response = self.client.post(reverse('hotels:add'), {
            'name': 'Bangkok Riverside',
            'country': 'Thailand',
            'province': 'Bangkok',
            'municipality': 'Bangkok',
            'barangay': '',
        })
        self.assertRedirects(response, reverse('hotels:manage'))
        hotel = Hotel.objects.get(name='Bangkok Riverside')
        self.assertEqual(hotel.country, 'Thailand')
        self.assertEqual(hotel.location, 'Thailand, Bangkok, Bangkok')

    def test_home_country_flow(self):
        response = self.client.post(reverse('hotels:add'), {
            'name': 'Dagupan Market Inn',
            'country': 'Philippines',
            'province': 'Pangasinan',
            'municipality': 'Dagupan City',
            'barangay': '',
        })
        self.assertRedirects(response, reverse('hotels:manage'))
        hotel = Hotel.objects.get(name='Dagupan Market Inn')
        self.assertEqual(hotel.country, 'Philippines')
        self.assertEqual(hotel.location, 'Philippines, Pangasinan, Dagupan City')

    def test_manage_filters_by_country(self):
        self.client.post(reverse('hotels:add'), {
            'name': 'Bangkok Riverside', 'country': 'Thailand',
            'province': 'Bangkok', 'municipality': 'Bangkok', 'barangay': '',
        })
        response = self.client.get(reverse('hotels:manage'), {'country': 'Thailand'})
        self.assertContains(response, 'Bangkok Riverside')
        self.assertNotContains(response, 'Pangasinan Lodge')

    def test_manage_form_renders_the_country_step(self):
        response = self.client.get(reverse('hotels:manage'))
        self.assertContains(response, 'data-cascade="country"')
        self.assertContains(response, 'data-init-country')

    def test_manage_page_omits_text_search_but_keeps_filters(self):
        response = self.client.get(reverse('hotels:manage'))
        self.assertNotContains(response, 'id="hotel-search-query"')
        self.assertContains(response, 'name="status"')
        self.assertContains(response, 'name="country"')

    def test_room_management_keeps_hotel_filter_for_platform_managers(self):
        response = self.client.get(reverse('hotels:rooms'))
        self.assertContains(response, 'name="hotel"')

    def test_hotel_selectors_remain_for_platform_managers(self):
        for route in ('hotels:services', 'hotels:amenities', 'hotels:bookings'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertContains(response, 'name="hotel"')

    def test_province_must_belong_to_the_selected_country(self):
        response = self.client.post(reverse('hotels:add'), {
            'name': 'Bad Hotel',
            'country': 'Thailand',
            'province': 'Pangasinan',
            'municipality': 'Bangkok',
            'barangay': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is not a recognized province")
        self.assertFalse(Hotel.objects.filter(name='Bad Hotel').exists())

    def test_edit_prefills_the_country(self):
        hotel = Hotel.objects.create(
            name='Bangkok Riverside', country='Thailand',
            province='Bangkok', municipality='Bangkok',
        )
        response = self.client.get(reverse('hotels:update_hotel', args=[hotel.id]))
        self.assertContains(response, 'data-init-country="Thailand"')


class HotelGroupRoomTabTests(TestCase):
    """The Room 1/2/3 tabbed form posts room_<index>_* fields, so the server has
    to read them against the order the rooms were submitted in. Removing a room
    renumbers the tabs; the guest line of every surviving room must stay with
    its own room."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='traveller', password='pw', email='t@example.com',
            first_name='Taylor', last_name='Account', contact_number='09171112222',
        )
        self.client.force_login(self.user)
        self.hotel = Hotel.objects.create(
            name='Avenue Tower Suites', establishment_id='H-9001',
            country='Philippines', province='Metro Manila', municipality='Manila',
            status=Hotel.Status.ACTIVE,
        )
        self.service = Service.objects.create(
            hotel=self.hotel, name='Airport Transfer', rate='750.00',
            status=Service.ServiceStatus.ACTIVE,
        )
        self.amenity = Amenity.objects.create(
            hotel=self.hotel, name='Alima Wellness',
            status=Amenity.AmenityStatus.ACTIVE,
        )
        self.rooms = [
            Room.objects.create(
                hotel=self.hotel, room_number=number, room_type='DELUXE',
                capacity_adults=2, capacity_children=1, max_guest_capacity=4,
                rate=f'{500 * (i + 2)}.00', additional_guest_charge='300.00',
                status=Room.RoomStatus.AVAILABLE,
            )
            for i, number in enumerate(('101', '102', '103'))
        ]
        self.check_in = timezone.localdate() + timedelta(days=10)
        self.check_out = self.check_in + timedelta(days=2)

    def _post(self, room_ids, guests):
        payload = {
            'check_in': self.check_in.isoformat(),
            'check_out': self.check_out.isoformat(),
            'adults': '2', 'children': '0', 'payment_method': 'GCASH',
            'room_ids': list(room_ids),
        }
        for index, guest in enumerate(guests):
            payload.update({
                f'room_{index}_first_name': guest['first_name'],
                f'room_{index}_last_name': 'Guest',
                f'room_{index}_email': guest['email'],
                f'room_{index}_contact': '09171234567',
                f'room_{index}_adults': '2',
                f'room_{index}_children': '0',
            })
            if guest.get('services'):
                payload[f'room_{index}_services'] = guest['services']
            if guest.get('amenities'):
                payload[f'room_{index}_amenities'] = guest['amenities']
        return self.client.post(
            reverse('hotels:group_select_rooms', args=[self.hotel.pk]), payload)

    def _guest(self, first, email, services=None, amenities=None):
        guest = {'first_name': first, 'email': email}
        if services:
            guest['services'] = services
        if amenities:
            guest['amenities'] = amenities
        return guest

    def test_guest_lines_follow_the_submitted_room_order(self):
        """Room 1 = the first submitted id, not the lowest id."""
        first, second, third = self.rooms
        response = self._post(
            [third.pk, first.pk],
            [
                self._guest('Third', 'third@example.com', services=[self.service.pk],
                            amenities=[self.amenity.pk]),
                self._guest('First', 'first@example.com'),
            ],
        )
        booking = Booking.objects.get()
        self.assertRedirects(
            response, reverse('hotels:booking_detail', args=[booking.pk]),
            fetch_redirect_response=False,
        )
        entries = list(booking.room_entries.select_related('room').order_by('pk'))
        self.assertEqual([e.room_id for e in entries], [third.pk, first.pk])
        self.assertEqual([e.guest_first_name for e in entries], ['Taylor', 'First'])
        self.assertEqual([e.guest_email for e in entries],
                         ['t@example.com', 'first@example.com'])
        self.assertEqual(
            entries[0].booked_services.get().service_id, self.service.pk)
        self.assertEqual(
            entries[0].booked_amenities.get().amenity_id, self.amenity.pk)
        self.assertEqual(entries[1].booked_services.count(), 0)

    def test_removing_a_room_keeps_the_surviving_guest_lines(self):
        """Room 2 removed in the browser renumbers Room 3 to index 1; its guest
        data must still land on that room."""
        first, _, third = self.rooms
        response = self._post(
            [first.pk, third.pk],
            [
                self._guest('First', 'first@example.com'),
                self._guest('Third', 'third@example.com', amenities=[self.amenity.pk]),
            ],
        )
        booking = Booking.objects.get()
        self.assertRedirects(
            response, reverse('hotels:booking_detail', args=[booking.pk]),
            fetch_redirect_response=False,
        )
        entries = list(booking.room_entries.select_related('room').order_by('pk'))
        self.assertEqual([e.room_id for e in entries], [first.pk, third.pk])
        self.assertEqual([e.guest_first_name for e in entries], ['Taylor', 'Third'])
        self.assertEqual(
            entries[1].booked_amenities.get().amenity_id, self.amenity.pk)

    def test_validation_error_keeps_room_order_and_typed_guest_data(self):
        """The re-render has to rebuild the tabs in the submitted order with the
        typed values, otherwise switching rooms loses input."""
        first, second, third = self.rooms
        response = self._post(
            [third.pk, first.pk, second.pk],
            [
                self._guest('Third', 'third@example.com'),
                self._guest('', 'first@example.com'),  # missing first name
                self._guest('Second', 'second@example.com',
                            services=[self.service.pk]),
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please complete the required guest information for Room 2.')
        preselected = response.context['preselected']
        self.assertEqual([p['room_id'] for p in preselected],
                         [third.pk, first.pk, second.pk])
        self.assertEqual([p['guest']['first_name'] for p in preselected],
                         ['Taylor', '', 'Second'])
        self.assertEqual(preselected[2]['services'], [self.service.pk])
        self.assertFalse(Booking.objects.exists())

    def test_guests_step_renders_one_card_per_room_in_session_order(self):
        session = self.client.session
        session['hotel_group_booking'] = {
            'hotel_id': self.hotel.pk,
            'check_in': self.check_in.isoformat(),
            'check_out': self.check_out.isoformat(),
            'rooms_needed': 3,
            'adults_search': 2,
            'children_search': 0,
            'room_ids': [self.rooms[2].pk, self.rooms[0].pk],
        }
        session.save()
        response = self.client.get(reverse('hotels:group_guests'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [room.pk for room, _guest in response.context['room_forms']],
            [self.rooms[2].pk, self.rooms[0].pk])
        self.assertContains(response, 'room_0_first_name')
        self.assertContains(response, 'room_1_first_name')
        self.assertContains(response, self.service.name)


class HotelGuestModalMarkupTests(TestCase):
    """Guest information is presented through a modal instead of a section the
    user has to scroll down to. The modal stays outside the animated page
    content, while JavaScript associates its fields with the booking form."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='traveller', password='pw', email='t@example.com',
            first_name='Taylor', last_name='Account', contact_number='09171112222',
        )
        self.client.force_login(self.user)
        self.hotel = Hotel.objects.create(
            name='Avenue Tower Suites', establishment_id='H-9001',
            country='Philippines', province='Metro Manila', municipality='Manila',
            status=Hotel.Status.ACTIVE,
        )
        self.rooms = [
            Room.objects.create(
                hotel=self.hotel, room_number=number, room_type='DELUXE',
                capacity_adults=2, capacity_children=1, max_guest_capacity=4,
                rate='2500.00', status=Room.RoomStatus.AVAILABLE,
            )
            for number in ('101', '102')
        ]
        self.check_in = timezone.localdate() + timedelta(days=10)
        self.check_out = self.check_in + timedelta(days=2)
        session = self.client.session
        session['hotel_group_booking'] = {
            'hotel_id': self.hotel.pk,
            'check_in': self.check_in.isoformat(),
            'check_out': self.check_out.isoformat(),
            'rooms_needed': 2, 'adults_search': 2, 'children_search': 0,
            'room_ids': [room.pk for room in self.rooms],
        }
        session.save()

    def _page(self):
        response = self.client.get(reverse('hotels:group_start', args=[self.hotel.pk]))
        self.assertEqual(response.status_code, 200)
        return response

    def test_guest_section_is_inside_the_guest_modal(self):
        html = self._page().content.decode()
        modal_at = html.index('id="guestModal"')
        section_at = html.index('id="selectedRoomsSection"')
        # The guest fields render inside the modal, not further down the page.
        self.assertLess(modal_at, section_at)
        self.assertLess(section_at, html.index('id="roomModal"'))
        self.assertIn('role="dialog"', html[modal_at:modal_at + 400])
        self.assertIn('aria-modal="true"', html[modal_at:modal_at + 400])

    def test_guest_modal_sits_outside_the_animated_content_and_booking_form(self):
        html = self._page().content.decode()
        form_at = html.index('id="bookingForm"')
        form_end = html.index('</form>', form_at)
        modal_at = html.index('id="guestModal"')
        main_end = html.index('</main>', form_at)
        self.assertGreater(modal_at, form_end,
                           'the fixed modal must not be nested in the booking form')
        self.assertGreater(modal_at, main_end,
                           'the fixed modal must be outside animated .content')

    def test_room_select_and_modal_render_for_another_student_hotel(self):
        other_hotel = Hotel.objects.create(
            name='Harbor View Inn', establishment_id='H-9002',
            country='Philippines', province='Cebu', municipality='Cebu City',
            status=Hotel.Status.ACTIVE,
        )
        room = Room.objects.create(
            hotel=other_hotel, room_number='201', room_type='DELUXE',
            capacity_adults=2, capacity_children=1, max_guest_capacity=4,
            rate='3200.00', status=Room.RoomStatus.AVAILABLE,
        )
        session = self.client.session
        session['hotel_group_booking'] = {
            'hotel_id': other_hotel.pk,
            'check_in': self.check_in.isoformat(),
            'check_out': self.check_out.isoformat(),
            'rooms_needed': 1, 'adults_search': 1, 'children_search': 0,
            'room_ids': [room.pk],
        }
        session.save()

        response = self.client.get(reverse('hotels:group_start', args=[other_hotel.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'data-room-book="{room.pk}"', html)
        self.assertIn('id="guestModal"', html)
        self.assertGreater(html.index('id="guestModal"'), html.index('</main>'))

    def test_guest_modal_has_cancel_and_continue_controls(self):
        html = self._page().content.decode()
        modal_at = html.index('id="guestModal"')
        modal_html = html[modal_at:html.index('id="roomModal"', modal_at)]
        self.assertIn('data-guest-close', modal_html)
        self.assertIn('id="guestModalSave"', modal_html)
        self.assertIn('Guest Information', modal_html)
        self.assertNotIn('type="submit"', modal_html,
                         'the modal buttons must not submit the booking')

    def test_guest_section_is_not_rendered_as_a_page_section(self):
        """The booking computation summary stays on the page; the guest form
        only exists inside the modal."""
        html = self._page().content.decode()
        modal_at = html.index('id="guestModal"')
        summary_at = html.index('id="computationSummary"')
        self.assertGreater(modal_at, summary_at)
        # Only one guest host element exists, and it is the one in the modal.
        self.assertEqual(html.count('id="selectedRoomsSection"'), 1)
