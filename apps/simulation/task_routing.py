"""Resolve an assignment to the existing, role-appropriate operations pages."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

TASK_ASSIGNMENT_SESSION_KEY = 'active_simulation_task_assignment'


def _operation(
    label,
    route,
    namespace,
    allowed_routes,
    icon='fa-briefcase',
    tasks=None,
    extra_allowed_routes=(),
):
    task_items = tasks or ((label, route, icon),)
    allowed = {f'{namespace}:{name}' for name in allowed_routes}
    allowed.update(extra_allowed_routes)
    allowed.update(item[1] for item in task_items)
    return {
        'label': label,
        'route': route,
        'namespace': namespace,
        'allowed_routes': frozenset(allowed),
        'icon': icon,
        'tasks': tuple(
            {'label': task_label, 'route': task_route, 'icon': task_icon}
            for task_label, task_route, task_icon in task_items
        ),
    }


_HOTEL_MANAGER_ROUTES = {
    'manage', 'update_hotel', 'rooms', 'room_detail', 'update_room', 'add_room',
    'services', 'service_detail', 'update_service', 'add_service',
    'amenities', 'amenity_detail', 'update_amenity', 'add_amenity',
    'bookings', 'booking_detail',
}
_AIRLINE_MANAGER_ROUTES = {
    'manage', 'airline_detail', 'update_airline', 'aircrafts',
    'aircraft_detail', 'airline_fleet', 'add_aircraft', 'update_aircraft',
    'services', 'service_detail', 'add_service', 'update_service',
    'flights', 'update_flight',
    'bookings', 'booking_detail', 'itinerary_detail', 'update_itinerary',
}
_TRANSPORT_MANAGER_ROUTES = {
    'manage', 'agency_vehicles', 'update_agency', 'add_vehicle',
    'update_vehicle', 'add_driver', 'update_driver', 'bookings', 'booking_detail',
}
_PACKAGE_MANAGER_ROUTES = {'manage', 'update_package'}
_ACTIVITY_MANAGER_ROUTES = {
    'manage', 'update_activity',
}
_RESORT_MANAGER_ROUTES = {
    'manage', 'update_resort', 'units', 'unit_detail', 'update_unit', 'add_unit',
    'services', 'service_detail', 'update_service', 'add_service',
    'bookings', 'booking_detail',
}
_RESTAURANT_MANAGER_ROUTES = {
    'manage', 'update_restaurant', 'tables', 'table_detail', 'update_table',
    'add_table', 'bookings', 'booking_detail',
}
_STAYCATION_MANAGER_ROUTES = {
    'manage', 'update_staycation', 'services', 'service_detail', 'update_service',
    'add_service', 'bookings', 'booking_detail',
}
_LANDMARK_MANAGER_ROUTES = {
    'manage', 'update_spot', 'update_landmark', 'bookings', 'booking_detail',
}

_OPERATIONS = {
    'HOTEL': {
        'HOTEL_MANAGER': _operation(
            'Hotel Operations', 'hotels:manage', 'hotels', _HOTEL_MANAGER_ROUTES,
            'fa-hotel',
            tasks=(
                ('Manage Hotel', 'hotels:manage', 'fa-hotel'),
                ('Manage Rooms and Rates', 'hotels:rooms', 'fa-bed'),
                ('Manage Services', 'hotels:services', 'fa-concierge-bell'),
                ('Manage Amenities', 'hotels:amenities', 'fa-bell-concierge'),
                ('Manage Bookings and Guests', 'hotels:bookings', 'fa-calendar-check'),
            ),
        ),
        'FRONT_DESK': _operation(
            'Hotel Operations', 'hotels:bookings', 'hotels',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-concierge-bell',
            tasks=(('Manage Bookings and Guests', 'hotels:bookings', 'fa-calendar-check'),),
        ),
        'RECEPTIONIST': _operation(
            'Hotel Operations', 'hotels:bookings', 'hotels',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-concierge-bell',
            tasks=(('Manage Bookings and Guests', 'hotels:bookings', 'fa-calendar-check'),),
        ),
        'BOOKING_AGENT': _operation(
            'Hotel Operations', 'hotels:bookings', 'hotels',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-concierge-bell',
            tasks=(('Manage Bookings and Guests', 'hotels:bookings', 'fa-calendar-check'),),
        ),
        'HOTEL_RESERVATION_OFFICER': _operation(
            'Hotel Operations', 'hotels:bookings', 'hotels',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-concierge-bell',
            tasks=(('Manage Bookings and Guests', 'hotels:bookings', 'fa-calendar-check'),),
        ),
        'CONCIERGE': _operation(
            'Hotel Operations', 'hotels:amenities', 'hotels',
            {'amenities', 'amenity_detail', 'update_amenity',
             'services', 'service_detail', 'update_service'},
            'fa-bell-concierge',
            tasks=(
                ('Manage Amenities', 'hotels:amenities', 'fa-bell-concierge'),
                ('Manage Services', 'hotels:services', 'fa-concierge-bell'),
            ),
        ),
        'HOUSEKEEPING_OFFICER': _operation(
            'Hotel Operations', 'hotels:rooms', 'hotels',
            {'rooms', 'room_detail', 'update_room'},
            'fa-bed',
            tasks=(('Manage Rooms', 'hotels:rooms', 'fa-bed'),),
        ),
        'HOTEL_BILLING_OFFICER': _operation(
            'Hotel Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
        'BILLING_OFFICER': _operation(
            'Hotel Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
    },
    'AIRLINE': {
        'AIRLINE_SUPERVISOR': _operation(
            'Airline Operations', 'airlines:manage', 'airlines',
            _AIRLINE_MANAGER_ROUTES, 'fa-plane',
            tasks=(
                ('Manage Airline', 'airlines:manage', 'fa-plane'),
                ('Manage Aircraft', 'airlines:aircrafts', 'fa-plane-up'),
                ('Manage Services', 'airlines:services', 'fa-concierge-bell'),
                ('Manage Flights and Schedules', 'airlines:flights', 'fa-plane-departure'),
                ('Manage Bookings', 'airlines:bookings', 'fa-ticket-alt'),
            ),
        ),
        'AIRLINE_RESERVATION_AGENT': _operation(
            'Airline Operations', 'airlines:bookings', 'airlines',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-ticket-alt',
            tasks=(('Manage Bookings', 'airlines:bookings', 'fa-ticket-alt'),),
        ),
        'BOOKING_AGENT': _operation(
            'Airline Operations', 'airlines:bookings', 'airlines',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-ticket-alt',
            tasks=(('Manage Bookings', 'airlines:bookings', 'fa-ticket-alt'),),
        ),
        'AIRLINE_CUSTOMER_SERVICE': _operation(
            'Airline Operations', 'airlines:bookings', 'airlines',
            {'bookings', 'booking_detail', 'ticket'},
            'fa-headset',
            tasks=(('Manage Bookings', 'airlines:bookings', 'fa-ticket-alt'),),
        ),
        'AIRLINE_TICKETING_OFFICER': _operation(
            'Airline Operations', 'airlines:bookings', 'airlines',
            {
                'list', 'airports_api', 'bookings',
                'booking_detail', 'flight_detail', 'ticket', 'ticket_pdf',
                'itinerary_public_detail',
            },
            'fa-ticket-alt',
            tasks=(('Manage Bookings', 'airlines:bookings', 'fa-ticket-alt'),),
        ),
        'CABIN_CREW': _operation(
            'Airline Operations', 'airlines:services', 'airlines',
            {'services', 'service_detail'}, 'fa-plane-departure',
            tasks=(('Manage Airline Services', 'airlines:services',
                    'fa-plane-departure'),),
        ),
        'AIRLINE_BILLING_OFFICER': _operation(
            'Airline Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
        'BILLING_OFFICER': _operation(
            'Airline Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
    },
    'TRAVEL_AGENCY': {
        'TRAVEL_AGENCY_MANAGER': _operation(
            'Travel Agency Operations', 'tour_package:manage', 'tour_package',
            _PACKAGE_MANAGER_ROUTES, 'fa-suitcase-rolling',
            tasks=(('Manage Tour Packages', 'tour_package:manage',
                    'fa-suitcase-rolling'),),
        ),
        'TRAVEL_AGENCY_RESERVATION_OFFICER': _operation(
            'Travel Agency Operations', 'tour_package:manage', 'tour_package',
            {'manage'}, 'fa-calendar-check',
            tasks=(('Manage Tour Packages', 'tour_package:manage',
                    'fa-calendar-check'),),
        ),
        'TRAVEL_CONSULTANT': _operation(
            'Travel Agency Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-map-marked-alt',
            tasks=(('Review Travel Transactions', 'transactions:admin_list',
                    'fa-map-marked-alt'),),
        ),
        'TRAVEL_AGENCY_BILLING_OFFICER': _operation(
            'Travel Agency Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
    },
    'TOUR_OPERATOR': {
        'TOUR_MANAGER': _operation(
            'Tour Operations', 'tour_package:manage', 'tour_package',
            _PACKAGE_MANAGER_ROUTES, 'fa-map-marked-alt',
            tasks=(
                ('Manage Tour Packages', 'tour_package:manage', 'fa-suitcase-rolling'),
                ('Manage Activities', 'activities:manage', 'fa-hiking'),
                ('Manage Landmarks', 'landmarks:manage', 'fa-landmark'),
                ('Manage Tour Transactions', 'transactions:admin_list',
                 'fa-file-invoice-dollar'),
            ),
            extra_allowed_routes={
                'activities:manage', 'landmarks:manage', 'transactions:admin_list',
            },
        ),
        'TOUR_COORDINATOR': _operation(
            'Tour Operations', 'tour_package:manage', 'tour_package',
            {'manage'}, 'fa-calendar-check',
            tasks=(('Manage Tour Packages', 'tour_package:manage',
                    'fa-calendar-check'),),
        ),
        'TOUR_OPERATOR': _operation(
            'Tour Operations', 'tour_package:manage', 'tour_package',
            {'manage'}, 'fa-map-marked-alt',
            tasks=(('Manage Tour Packages', 'tour_package:manage',
                    'fa-map-marked-alt'),),
        ),
        'TOUR_GUIDE': _operation(
            'Tour Operations', 'activities:manage', 'activities',
            {'manage'}, 'fa-route',
            tasks=(('Manage Activities', 'activities:manage', 'fa-route'),),
        ),
        'TOUR_BILLING_OFFICER': _operation(
            'Tour Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
        'BILLING_OFFICER': _operation(
            'Tour Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
    },
    'ACTIVITY': {
        'ACTIVITY_MANAGER': _operation(
            'Activity Operations', 'activities:manage', 'activities',
            _ACTIVITY_MANAGER_ROUTES, 'fa-person-hiking',
            tasks=(
                ('Manage Activities', 'activities:manage', 'fa-person-hiking'),
            ),
        ),
        'ACTIVITY_RESERVATION_OFFICER': _operation(
            'Activity Operations', 'activities:bookings', 'activities',
            {'bookings', 'booking_detail'}, 'fa-calendar-check',
            tasks=(('Manage Activity Bookings', 'activities:bookings',
                    'fa-calendar-check'),),
        ),
        'ACTIVITY_OPERATOR': _operation(
            'Activity Operations', 'activities:operate', 'activities',
            {'operate'}, 'fa-person-hiking',
            tasks=(('Operate Assigned Activity', 'activities:operate',
                    'fa-person-hiking'),),
        ),
        # Existing front-desk assignments resolve to the arrival/check-in page.
        'ACTIVITY_FRONT_DESK_OFFICER': _operation(
            'Activity Operations', 'activities:operate', 'activities',
            {'operate'}, 'fa-person-hiking',
            tasks=(('Handle Activity Arrivals', 'activities:operate',
                    'fa-person-hiking'),),
        ),
    },
    'TOUR_PACKAGE': {
        'TOUR_PACKAGE_MANAGER': _operation(
            'Tour Package Operations', 'tour_package:manage', 'tour_package',
            {'manage', 'update_package'}, 'fa-suitcase-rolling',
            tasks=(
                ('Manage Tour Packages', 'tour_package:manage',
                 'fa-suitcase-rolling'),
            ),
        ),
        'TOUR_PACKAGE_RESERVATION_OFFICER': _operation(
            'Tour Package Operations', 'tour_package:bookings', 'tour_package',
            {'bookings', 'booking_detail'}, 'fa-calendar-check',
            tasks=(('Manage Package Bookings', 'tour_package:bookings',
                    'fa-calendar-check'),),
        ),
        'TOUR_PACKAGE_OPERATOR': _operation(
            'Tour Package Operations', 'tour_package:operate', 'tour_package',
            {'operate'}, 'fa-suitcase-rolling',
            tasks=(('Operate Assigned Tour Package', 'tour_package:operate',
                    'fa-suitcase-rolling'),),
        ),
        'TOUR_PACKAGE_FRONT_DESK_OFFICER': _operation(
            'Tour Package Operations', 'tour_package:operate', 'tour_package',
            {'operate'}, 'fa-suitcase-rolling',
            tasks=(('Operate Assigned Tour Package', 'tour_package:operate',
                    'fa-suitcase-rolling'),),
        ),
    },
    'TRANSPORTATION': {
        'TRANSPORT_MANAGER': _operation(
            'Transportation Operations', 'transportation:manage', 'transportation',
            _TRANSPORT_MANAGER_ROUTES, 'fa-bus',
            tasks=(
                ('Manage Transportation Agency', 'transportation:manage', 'fa-bus'),
                ('Manage Bookings', 'transportation:bookings', 'fa-calendar-check'),
            ),
        ),
        'TRANSPORT_STAFF': _operation(
            'Transportation Operations', 'transportation:bookings', 'transportation',
            {'bookings', 'booking_detail', 'ticket_detail', 'ticket_pdf'},
            'fa-car',
            tasks=(('Manage Bookings', 'transportation:bookings', 'fa-car'),),
        ),
        'TRANSPORT_RESERVATION_OFFICER': _operation(
            'Transportation Operations', 'transportation:bookings', 'transportation',
            {'bookings', 'booking_detail', 'ticket_detail', 'ticket_pdf'},
            'fa-calendar-check',
            tasks=(('Manage Bookings', 'transportation:bookings',
                    'fa-calendar-check'),),
        ),
        'TRANSPORT_DISPATCHER': _operation(
            'Transportation Operations', 'transportation:manage', 'transportation',
            {'manage', 'agency_vehicles', 'bookings', 'booking_detail'},
            'fa-route',
            tasks=(
                ('Manage Transportation Agency', 'transportation:manage', 'fa-bus'),
                ('Manage Bookings', 'transportation:bookings', 'fa-calendar-check'),
            ),
        ),
        'TRANSPORT_BILLING_OFFICER': _operation(
            'Transportation Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
        'BILLING_OFFICER': _operation(
            'Transportation Operations', 'transactions:admin_list', 'transactions',
            {'admin_list'}, 'fa-file-invoice-dollar',
            tasks=(('Manage Bills and Transactions', 'transactions:admin_list',
                    'fa-file-invoice-dollar'),),
        ),
    },
    'RESORT': {
        'RESORT_MANAGER': _operation(
            'Resort Operations', 'resorts:manage', 'resorts',
            _RESORT_MANAGER_ROUTES, 'fa-umbrella-beach',
            tasks=(
                ('Manage Resort', 'resorts:manage', 'fa-umbrella-beach'),
                ('Manage Units', 'resorts:units', 'fa-bed'),
                ('Manage Services', 'resorts:services', 'fa-concierge-bell'),
                ('Manage Bookings and Guests', 'resorts:bookings', 'fa-calendar-check'),
            ),
        ),
        'RESORT_RESERVATION_OFFICER': _operation(
            'Resort Operations', 'resorts:bookings', 'resorts',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-calendar-check',
            tasks=(('Manage Bookings and Guests', 'resorts:bookings', 'fa-calendar-check'),),
        ),
        'RESORT_FRONT_DESK': _operation(
            'Resort Operations', 'resorts:bookings', 'resorts',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-bell-concierge',
            tasks=(('Manage Bookings and Guests', 'resorts:bookings', 'fa-calendar-check'),),
        ),
    },
    'RESTAURANT': {
        'RESTAURANT_MANAGER': _operation(
            'Restaurant Operations', 'restaurants:manage', 'restaurants',
            _RESTAURANT_MANAGER_ROUTES, 'fa-utensils',
            tasks=(
                ('Manage Restaurant', 'restaurants:manage', 'fa-utensils'),
                ('Manage Tables', 'restaurants:tables', 'fa-chair'),
                ('Manage Reservations', 'restaurants:bookings', 'fa-calendar-check'),
            ),
        ),
        'RESTAURANT_RESERVATION_OFFICER': _operation(
            'Restaurant Operations', 'restaurants:bookings', 'restaurants',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-calendar-check',
            tasks=(('Manage Reservations', 'restaurants:bookings', 'fa-calendar-check'),),
        ),
        'RESTAURANT_FRONT_DESK': _operation(
            'Restaurant Operations', 'restaurants:bookings', 'restaurants',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-utensil-spoon',
            tasks=(('Manage Reservations', 'restaurants:bookings', 'fa-calendar-check'),),
        ),
    },
    'STAYCATION': {
        'STAYCATION_MANAGER': _operation(
            'Staycation Operations', 'staycations:manage', 'staycations',
            _STAYCATION_MANAGER_ROUTES, 'fa-couch',
            tasks=(
                ('Manage Staycation', 'staycations:manage', 'fa-couch'),
                ('Manage Services', 'staycations:services', 'fa-concierge-bell'),
                ('Manage Bookings and Guests', 'staycations:bookings', 'fa-calendar-check'),
            ),
        ),
        'STAYCATION_RESERVATION_OFFICER': _operation(
            'Staycation Operations', 'staycations:bookings', 'staycations',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-calendar-check',
            tasks=(('Manage Bookings and Guests', 'staycations:bookings', 'fa-calendar-check'),),
        ),
        'STAYCATION_FRONT_DESK': _operation(
            'Staycation Operations', 'staycations:bookings', 'staycations',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-bell-concierge',
            tasks=(('Manage Bookings and Guests', 'staycations:bookings', 'fa-calendar-check'),),
        ),
    },
    'LANDMARK': {
        'LANDMARK_MANAGER': _operation(
            'Landmark Operations', 'landmarks:manage', 'landmarks',
            _LANDMARK_MANAGER_ROUTES, 'fa-landmark',
            tasks=(
                ('Manage Landmark', 'landmarks:manage', 'fa-landmark'),
                ('Manage Bookings and Visitors', 'landmarks:bookings', 'fa-calendar-check'),
            ),
        ),
        'LANDMARK_RESERVATION_OFFICER': _operation(
            'Landmark Operations', 'landmarks:bookings', 'landmarks',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-calendar-check',
            tasks=(('Manage Bookings and Visitors', 'landmarks:bookings', 'fa-calendar-check'),),
        ),
        'LANDMARK_FRONT_DESK': _operation(
            'Landmark Operations', 'landmarks:bookings', 'landmarks',
            {'bookings', 'booking_detail', 'ticket', 'ticket_pdf'},
            'fa-route',
            tasks=(('Manage Bookings and Visitors', 'landmarks:bookings', 'fa-calendar-check'),),
        ),
    },
}

_LEGACY_ROLE_ESTABLISHMENTS = {
    'TRANSPORT_STAFF': 'TRANSPORTATION',
    'CABIN_CREW': 'AIRLINE',
}

#: The three operational roles of every establishment, pointed at the operations
#: the retired role they replace was given.
#:
#: Aliases rather than fresh ``_operation`` literals on purpose: the operations a
#: role is allowed to reach are the security boundary (they feed
#: ``allowed_routes``, which the backend checks), so the role that replaces
#: another one must not be able to drift away from it. It also keeps a legacy
#: assignment resolvable while a class is still finishing its run.
#:
#: Every operational role in ``role_catalogue.ROLE_CATALOGUE`` has to appear
#: here or "Do the Task" has nothing to open; ``simulation.checks`` enforces it.
_ROLE_ALIASES = {
    'HOTEL': {
        'HOTEL_FRONT_DESK': 'FRONT_DESK',
    },
    'AIRLINE': {
        'AIRLINE_MANAGER': 'AIRLINE_SUPERVISOR',
        'AIRLINE_FRONT_DESK': 'AIRLINE_TICKETING_OFFICER',
    },
    'TRAVEL_AGENCY': {
        'TRAVEL_AGENCY_RESERVATION_AGENT': 'TRAVEL_AGENCY_RESERVATION_OFFICER',
        'TRAVEL_AGENCY_FRONT_DESK': 'TRAVEL_AGENCY_RESERVATION_OFFICER',
    },
    'TOUR_OPERATOR': {
        'TOUR_OPERATOR_MANAGER': 'TOUR_MANAGER',
        'TOUR_RESERVATION_AGENT': 'TOUR_COORDINATOR',
        'TOUR_FRONT_DESK': 'TOUR_GUIDE',
    },
    'TRANSPORTATION': {
        'TRANSPORT_RESERVATION_AGENT': 'TRANSPORT_RESERVATION_OFFICER',
        'TRANSPORT_FRONT_DESK': 'TRANSPORT_DISPATCHER',
    },
}

for _establishment_type, _aliases in _ROLE_ALIASES.items():
    _operations = _OPERATIONS[_establishment_type]
    for _code, _retired_code in _aliases.items():
        _operations.setdefault(_code, _operations[_retired_code])
del _establishment_type, _aliases, _operations, _code, _retired_code

_RESTAURANT_OPERATIONS = _operation(
    'Restaurant Operations', 'restaurants:manage', 'restaurants',
    {'manage', 'tables', 'table_detail', 'update_table', 'bookings', 'booking_detail'},
    'fa-utensils',
    tasks=(
        ('Manage Restaurant', 'restaurants:manage', 'fa-utensils'),
        ('Manage Tables', 'restaurants:tables', 'fa-chair'),
        ('Manage Reservations', 'restaurants:bookings', 'fa-calendar-check'),
    ),
)


#: The storefront guest roles. A guest is performed *outside* an establishment
#: (``establishment_type`` stays None on the assignment), so its module is
#: browse-all for the customer; but an instructor may optionally attach one
#: specific establishment of the module's own type, and the task is then
#: deep-linked onto that place's public page instead of the module list.
#: ``detail_route`` is the public page a linked establishment resolves to; None
#: means the module has no per-place page.
GUEST_MODULES = {
    'GUEST_HOTEL': {'establishment_type': 'HOTEL', 'detail_route': 'hotels:detail'},
    'RESORT_GUEST': {'establishment_type': 'RESORT', 'detail_route': 'resorts:detail'},
    'RESTAURANT_GUEST': {'establishment_type': 'RESTAURANT', 'detail_route': 'restaurants:detail'},
    'STAYCATION_GUEST': {'establishment_type': 'STAYCATION', 'detail_route': 'staycations:detail'},
    'LANDMARK_GUEST': {'establishment_type': 'LANDMARK', 'detail_route': 'landmarks:detail'},
    'PASSENGER_TRANSPORT': {'establishment_type': 'TRANSPORTATION', 'detail_route': 'transportation:agency_vehicles'},
    'TOUR_GUEST': {'establishment_type': 'TOUR_PACKAGE', 'detail_route': 'tour_package:detail'},
    'ACTIVITY_GUEST': {'establishment_type': 'ACTIVITY', 'detail_route': 'activities:detail'},
}


def guest_destination_types():
    """``{role code: establishment type}`` for the guest roles an instructor
    may attach a place to. Only roles whose module has a deep-link target are
    listed, so a guest that cannot be directed anywhere is not offered a picker.
    """
    return {
        code: module['establishment_type']
        for code, module in GUEST_MODULES.items()
        if module['establishment_type'] and module['detail_route']
    }


_GUEST_OPERATIONS = {
    'GUEST_HOTEL': _operation(
        'Hotel Guest Operations', 'hotels:list', 'hotels',
        {'list', 'detail', 'book', 'group_start', 'booking_detail', 'ticket'},
        'fa-hotel',
        tasks=(
            ('Browse Hotel Rooms', 'hotels:list', 'fa-hotel'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
    'RESORT_GUEST': _operation(
        'Resort Guest Operations', 'resorts:list', 'resorts',
        {'list', 'detail', 'book', 'group_start', 'flow_select', 'booking_detail', 'ticket'},
        'fa-umbrella-beach',
        tasks=(
            ('Browse Resort Units', 'resorts:flow_select', 'fa-umbrella-beach'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
    'RESTAURANT_GUEST': _operation(
        'Restaurant Guest Operations', 'restaurants:list', 'restaurants',
        {'list', 'detail', 'book', 'flow_select', 'booking_detail', 'ticket'},
        'fa-utensils',
        tasks=(
            ('Browse Restaurant Tables', 'restaurants:list', 'fa-utensils'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
    'STAYCATION_GUEST': _operation(
        'Staycation Guest Operations', 'staycations:list', 'staycations',
        {'list', 'detail', 'book', 'flow_select', 'booking_detail', 'ticket'},
        'fa-building',
        tasks=(
            ('Browse Staycations', 'staycations:list', 'fa-building'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
    'LANDMARK_GUEST': _operation(
        'Landmark Guest Operations', 'landmarks:list', 'landmarks',
        {'list', 'detail', 'flow_select', 'booking_detail', 'ticket'},
        'fa-star',
        tasks=(
            ('Browse Landmarks', 'landmarks:list', 'fa-star'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
    'TOUR_GUEST': _operation(
        'Tour Guest Operations', 'tour_package:list', 'tour_package',
        {'list', 'detail', 'flow_select', 'booking_detail', 'ticket'},
        'fa-map',
        tasks=(
            ('Browse Tour Packages', 'tour_package:list', 'fa-map'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
    'PASSENGER_TRANSPORT': _operation(
        'Transport Guest Operations', 'transportation:list', 'transportation',
        {'list', 'agency_vehicles', 'book', 'booking_detail', 'ticket'},
        'fa-bus',
        tasks=(
            ('Browse Transport Options', 'transportation:list', 'fa-bus'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
    'ACTIVITY_GUEST': _operation(
        'Activity Guest Operations', 'activities:list', 'activities',
        {'list', 'detail', 'book', 'flow_select', 'booking_detail', 'ticket'},
        'fa-person-hiking',
        tasks=(
            ('Browse Activities', 'activities:list', 'fa-person-hiking'),
            ('View Bookings', 'transactions:booking_list', 'fa-book-open'),
        ),
    ),
}


def _assignment_establishment_key(assignment):
    """The storefront id a deep link should point at, else None.

    The storefront modules address their rows numerically (the ``/<pk>/``
    fallbacks), so the establishment's linked catalogue row id is the argument
    the deep link needs. Only an establishment that *has* a live linked row can
    be deep-linked; a bare row (no entity, or one whose row is gone) is skipped
    and the guest stays on the module list.
    """
    establishment = assignment.establishment
    if establishment is None or not establishment.entity_type_id or not establishment.entity_id:
        return None
    try:
        content_type = ContentType.objects.get_for_id(establishment.entity_type_id)
        model = content_type.model_class()
        if model is None:
            return None
        model._default_manager.get(pk=establishment.entity_id)
    except ObjectDoesNotExist:
        return None
    return establishment.entity_id


def _guest_operation(role_code):
    """The guest's storefront operation, annotated for deep-linking."""
    operation = dict(_GUEST_OPERATIONS[role_code])
    detail_route = GUEST_MODULES[role_code]['detail_route']
    if detail_route:
        operation['detail_route'] = detail_route
    return operation


_OWNER_OPERATIONS = {
    'HOTEL_OWNER': ('HOTEL', 'HOTEL_MANAGER', 'hotels:add', 'Add Hotel'),
    'RESORT_OWNER': ('RESORT', 'RESORT_MANAGER', 'resorts:add', 'Add Resort'),
    'RESTAURANT_OWNER': ('RESTAURANT', 'RESTAURANT_MANAGER', 'restaurants:add', 'Add Restaurant'),
    'STAYCATION_OWNER': ('STAYCATION', 'STAYCATION_MANAGER', 'staycations:add', 'Add Staycation'),
    'LANDMARK_OWNER': ('LANDMARK', 'LANDMARK_MANAGER', 'landmarks:add_landmark', 'Add Landmark'),
    'AIRLINE_OWNER': ('AIRLINE', 'AIRLINE_MANAGER', 'airlines:add_flight_schedule', 'Add Flight'),
    'TRAVEL_AGENCY_OWNER': ('TRAVEL_AGENCY', 'TRAVEL_AGENCY_MANAGER', 'tour_package:add_package', 'Add Package'),
    'TOUR_OPERATOR_OWNER': ('TOUR_OPERATOR', 'TOUR_OPERATOR_MANAGER', 'tour_package:add_package', 'Add Package'),
    'TOUR_PACKAGE_OWNER': ('TOUR_PACKAGE', 'TOUR_PACKAGE_MANAGER', 'tour_package:add_package', 'Add Package'),
    'ACTIVITY_OWNER': ('ACTIVITY', 'ACTIVITY_MANAGER', 'activities:add_activity', 'Add Activity'),
    'TRANSPORTATION_OWNER': ('TRANSPORTATION', 'TRANSPORT_MANAGER', 'transportation:add_agency', 'Add Agency'),
}


def _owner_operation(role_code):
    establishment_type, manager_code, add_route, add_label = _OWNER_OPERATIONS[role_code]
    base = _OPERATIONS.get(establishment_type, {}).get(manager_code)
    if base is None:
        return None
    result = dict(base)
    owner_routes = {add_route}
    if role_code == 'AIRLINE_OWNER':
        # Airline detail pages use this route when adding a flight to a
        # selected airline; the schedule page uses add_flight_schedule.
        owner_routes.add('airlines:add_flight')
    result['allowed_routes'] = frozenset(set(base['allowed_routes']) | owner_routes)
    result['tasks'] = ({'label': add_label, 'route': add_route, 'icon': 'fa-plus'},) + base['tasks']
    return result


for _owner_code, (_owner_type, *_owner_rest) in _OWNER_OPERATIONS.items():
    _OPERATIONS.setdefault(_owner_type, {})[_owner_code] = _owner_operation(_owner_code)
del _owner_code, _owner_type, _owner_rest


_BILLING_OPERATION = _operation(
    'Billing Officer', 'transactions:payment_review', 'transactions',
    {'payment_review'}, 'fa-file-invoice-dollar',
    tasks=(('Review and confirm payments', 'transactions:payment_review', 'fa-file-invoice-dollar'),),
)


def task_operation_for(assignment):
    """Return the operations and task routes allowed for this assignment."""
    role_code = assignment.role_ref.code if assignment.role_ref_id else assignment.role
    from .models import BILLING_OFFICER_ROLE_CODES
    if role_code in BILLING_OFFICER_ROLE_CODES:
        if not assignment.establishment_id:
            return None
        operation = dict(_BILLING_OPERATION)
        role_name = assignment.role_ref.name if assignment.role_ref_id else assignment.get_role_display()
        operation['label'] = role_name
        operation['tasks'] = tuple(
            {**task, 'label': role_name}
            for task in _BILLING_OPERATION['tasks']
        )
        return operation
    if role_code.endswith('_OWNER') and role_code in _OWNER_OPERATIONS:
        return _owner_operation(role_code)
    if role_code == 'PASSENGER_AIRLINE':
        return _operation(
            'Airline Passenger Operations', 'airlines:list', 'airlines',
            {
                'list', 'airports_api', 'book', 'book_itinerary',
                'flight_detail', 'booking_detail', 'ticket', 'ticket_pdf',
                'itinerary_public_detail',
            },
            'fa-plane',
            tasks=(
                ('Book Flight', 'airlines:list', 'fa-plane'),
                ('View Booking', 'transactions:booking_list', 'fa-book-open'),
                ('Manage Booking', 'transactions:booking_list', 'fa-pen-to-square'),
                ('Select Seat', 'airlines:list', 'fa-chair'),
                ('View Ticket', 'transactions:booking_list', 'fa-ticket-alt'),
            ),
        )
    if role_code in _GUEST_OPERATIONS:
        return _guest_operation(role_code)
    if role_code == 'RESTAURANT_STAFF':
        if assignment.establishment_id:
            establishment_type = assignment.establishment.type
            if establishment_type != 'TOUR_OPERATOR':
                return None
            if (assignment.role_ref_id
                    and assignment.role_ref.requires_establishment
                    and establishment_type != assignment.role_ref.establishment_category):
                return None
        return _RESTAURANT_OPERATIONS

    establishment_type = None
    if assignment.establishment_id:
        establishment_type = assignment.establishment.type
    elif assignment.hotel_id:
        establishment_type = 'HOTEL'
    elif assignment.role_ref_id:
        establishment_type = assignment.role_ref.establishment_type
    else:
        establishment_type = _LEGACY_ROLE_ESTABLISHMENTS.get(role_code)

    if not establishment_type:
        return None
    if (establishment_type == 'HOTEL' and not assignment.hotel_id
            and assignment.role_ref_id and assignment.role_ref.requires_establishment):
        return None
    if assignment.role_ref_id and assignment.role_ref.requires_establishment:
        if establishment_type != assignment.role_ref.establishment_category:
            return None
    routing_type = (
        assignment.role_ref.establishment_type
        if assignment.role_ref_id and assignment.role_ref.establishment_type
        else establishment_type
    )
    return _OPERATIONS.get(routing_type, {}).get(role_code)


def operation_with_urls(assignment, operation):
    """Return an operation with reversed URLs for its clickable task entries."""
    result = {**operation, 'url': reverse(operation['route'])}
    if assignment.hotel_id and operation['namespace'] == 'hotels':
        result['url'] += f'?hotel={assignment.hotel_id}'

    landing_key = _assignment_establishment_key(assignment)
    if operation.get('detail_route') and landing_key is not None:
        # A guest pointed at a specific establishment lands on *that place's*
        # public page, not the whole-module list.
        result['url'] = reverse(operation['detail_route'], args=[landing_key])

    tasks = []
    for task in operation['tasks']:
        if task['route'] == operation['route'] \
                and operation.get('detail_route') and landing_key is not None:
            url = reverse(operation['detail_route'], args=[landing_key])
        elif task['route'] == 'resorts:flow_select':
            # A linked resort guest should land directly on that resort's
            # unit selection page. Guests without a linked resort still need
            # to choose one from the public resort list first.
            url = (
                reverse('resorts:flow_select', args=[landing_key])
                if landing_key is not None
                else reverse('resorts:list')
            )
        else:
            url = reverse(task['route'])
            if assignment.hotel_id and task['route'].startswith('hotels:'):
                url += f'?hotel={assignment.hotel_id}'
        tasks.append({**task, 'url': url})
    result['tasks'] = tasks
    return result
