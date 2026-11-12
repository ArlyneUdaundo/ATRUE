from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from .passenger_pricing import age_on_date, category_for_age, quote_passenger_legs


class PassengerAgePricingTests(SimpleTestCase):
    def test_age_categories_use_travel_date_boundaries(self):
        travel_date = date(2026, 11, 12)

        self.assertEqual(age_on_date(date(2024, 11, 13), travel_date), 1)
        self.assertEqual(category_for_age(age_on_date(date(2024, 11, 13), travel_date)), 'infant')
        self.assertEqual(category_for_age(age_on_date(date(2024, 11, 12), travel_date)), 'child')
        self.assertEqual(category_for_age(age_on_date(date(2014, 11, 13), travel_date)), 'child')
        self.assertEqual(category_for_age(age_on_date(date(2014, 11, 12), travel_date)), 'adult')

    def test_future_birth_date_is_rejected(self):
        with self.assertRaises(ValueError):
            age_on_date(date(2026, 11, 13), date(2026, 11, 12))

    def test_airline_rules_price_each_leg_and_lap_infant_separately(self):
        adult_rule = SimpleNamespace(
            adult_fare_percent=Decimal('100'),
            child_fare_percent=Decimal('75'),
            infant_seat_fare_percent=Decimal('60'),
            infant_lap_fee=Decimal('25'),
            tax_percent=Decimal('10'),
            additional_passenger_fee=Decimal('5'),
        )
        child_rule = SimpleNamespace(
            adult_fare_percent=Decimal('100'),
            child_fare_percent=Decimal('50'),
            infant_seat_fare_percent=Decimal('60'),
            infant_lap_fee=Decimal('40'),
            tax_percent=Decimal('5'),
            additional_passenger_fee=Decimal('7'),
        )
        first_leg = SimpleNamespace(airline_id=1, fare_for=lambda _fare_class: Decimal('100'))
        second_leg = SimpleNamespace(airline_id=2, fare_for=lambda _fare_class: Decimal('200'))

        lap_total, lap_legs = quote_passenger_legs(
            [first_leg, second_leg], {1: adult_rule, 2: child_rule},
            'infant', 'lap', 'ECONOMY')
        seat_total, _seat_legs = quote_passenger_legs(
            [first_leg, second_leg], {1: adult_rule, 2: child_rule},
            'child', 'seat', 'ECONOMY')

        self.assertEqual(lap_total, {
            'fare': Decimal('0.00'), 'tax': Decimal('0.00'),
            'fee': Decimal('12.00'), 'infant_fee': Decimal('65.00'),
        })
        self.assertEqual(lap_legs[0]['infant_fee'], Decimal('25.00'))
        self.assertEqual(lap_legs[1]['infant_fee'], Decimal('40.00'))
        self.assertEqual(seat_total, {
            'fare': Decimal('175.00'), 'tax': Decimal('12.50'),
            'fee': Decimal('12.00'), 'infant_fee': Decimal('0.00'),
        })
