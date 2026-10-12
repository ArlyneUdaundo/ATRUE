"""Tests for the GeoNames reference data and the location tree built from it.

These use a small hand-built slice of GeoNames rather than the full seed, so
they stay fast and do not depend on ``sync_geonames`` having been run.
"""

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from atrue_core.location_hierarchy import (
    build_location_hierarchy,
    country_province_keys,
    location_display,
    location_errors,
    location_matches,
    municipality_barangays,
    stored_province_names,
)
from locations import geonames_service
from locations.models import Barangay, CityMunicipality, Country, Province, Region
from locations.names import clean_name, normalize_place_name
from django.template.loader import render_to_string

#: Mirrors the GeoNames PCLI row for the Philippines.
PHILIPPINES_SEED_ROW = {
    'geoname_id': 1694008, 'code': 'PH', 'name': 'Philippines',
    'asciiname': 'Republic of the Philippines',
    'latitude': 13.40882, 'longitude': 122.56155, 'feature_code': 'PCLI',
}


class NameHelperTests(TestCase):
    def test_clean_name_strips_geonames_prefixes(self):
        self.assertEqual(clean_name('Province of Isabela'), 'Isabela')
        self.assertEqual(clean_name('City of Vigan'), 'Vigan')
        self.assertEqual(clean_name('Municipality of Pateros'), 'Pateros')
        self.assertEqual(clean_name('  Benguet  '), 'Benguet')

    def test_normalize_is_accent_and_punctuation_insensitive(self):
        self.assertEqual(normalize_place_name('Parañaque'), normalize_place_name('Paranaque'))
        self.assertEqual(normalize_place_name("Santa Ana's"), 'santa ana s')
        self.assertEqual(normalize_place_name('Lapu-Lapu'), 'lapu lapu')

    def test_normalize_keeps_city_so_province_and_city_stay_distinct(self):
        # Cotabato the province and Cotabato City are distinct places.
        self.assertNotEqual(normalize_place_name('Cotabato'), normalize_place_name('Cotabato City'))


class SeedFixtureTests(TestCase):
    """A miniature GeoNames slice, mirroring the shape the sync command expects."""

    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(**PHILIPPINES_SEED_ROW)
        region = Region.objects.create(
            geoname_id=7521301, code='01', name='Ilocos', country=cls.country,
        )
        region_ncr = Region.objects.create(
            geoname_id=7521311, code='NCR', name='National Capital Region', country=cls.country,
        )

        cls.pangasinan = Province.objects.create(
            geoname_id=1695357, code='51', name='Pangasinan', region=region,
        )
        Province.objects.create(
            geoname_id=1716796, code='H3', name='Negros Occidental', region=region,
        )
        district = Province.objects.create(
            geoname_id=11395836, code='137400000', name='Eastern Manila District', region=region_ncr,
        )

        cls.dagupan = CityMunicipality.objects.create(
            geoname_id=1683502, code='015533000', name='Dagupan City', province=cls.pangasinan,
        )
        cls.quezon = CityMunicipality.objects.create(
            geoname_id=1114855, code='137402000', name='Quezon City', province=district,
        )
        CityMunicipality.objects.create(
            geoname_id=9999999, code='015599000', name='Urdaneta City', province=cls.pangasinan,
        )

        cls.poblacion = Barangay.objects.create(
            geoname_id=1111111, name='Poblacion', city_municipality=cls.dagupan,
        )
        Barangay.objects.create(
            geoname_id=1111112, name='Mabini', city_municipality=cls.dagupan,
        )

    def test_sync_command_loads_and_is_idempotent(self):
        seed = {
            'meta': {'source': 'test'},
            'countries': [PHILIPPINES_SEED_ROW],
            'regions': [{'geoname_id': 1, 'code': 'R1', 'name': 'Region One',
                         'asciiname': 'Region One', 'latitude': 1.0, 'longitude': 2.0,
                         'feature_code': 'ADM1', 'country_geoname_id': 1694008}],
            'provinces': [{'geoname_id': 2, 'code': 'P1', 'name': 'Province One',
                           'asciiname': 'Province One', 'latitude': None, 'longitude': None,
                           'feature_code': 'ADM2', 'region_geoname_id': 1}],
            'cities': [{'geoname_id': 3, 'code': 'C1', 'name': 'City One',
                        'asciiname': 'City One', 'latitude': None, 'longitude': None,
                        'feature_code': 'ADM3', 'province_geoname_id': 2}],
            'barangays': [{'geoname_id': 4, 'name': 'Barangay One', 'asciiname': 'Barangay One',
                           'latitude': None, 'longitude': None, 'feature_code': 'PPL',
                           'city_geoname_id': 3}],
        }
        with seed_file(seed) as path:
            call_command('sync_geonames', seed=path, verbosity=0)
            self.assertEqual(Country.objects.filter(code='PH').count(), 1)
            self.assertEqual(Region.objects.filter(code='R1').count(), 1)
            self.assertEqual(Province.objects.filter(code='P1').count(), 1)
            self.assertEqual(CityMunicipality.objects.filter(code='C1').count(), 1)
            self.assertEqual(Barangay.objects.filter(geoname_id=4).count(), 1)

            # The loaded region must be parented to the loaded country.
            self.assertEqual(Region.objects.get(code='R1').country.code, 'PH')

            # Re-running must update, not duplicate.
            call_command('sync_geonames', seed=path, verbosity=0)
            self.assertEqual(Country.objects.filter(code='PH').count(), 1)
            self.assertEqual(Region.objects.filter(code='R1').count(), 1)
            self.assertEqual(Barangay.objects.filter(geoname_id=4).count(), 1)

    def test_region_with_unknown_country_is_skipped(self):
        """A region pointing at a country missing from the seed is reported, not loaded."""
        from io import StringIO

        seed = {
            'meta': {},
            'countries': [PHILIPPINES_SEED_ROW],
            'regions': [{'geoname_id': 1, 'code': 'RX', 'name': 'Orphan Region',
                         'asciiname': '', 'latitude': None, 'longitude': None,
                         'feature_code': 'ADM1', 'country_geoname_id': 999999}],
            'provinces': [], 'cities': [], 'barangays': [],
        }
        out = StringIO()
        with seed_file(seed) as path:
            call_command('sync_geonames', seed=path, verbosity=0, stdout=out)
        self.assertFalse(Region.objects.filter(code='RX').exists())
        self.assertIn('skipped (no parent row)', out.getvalue())
        self.assertIn('regions', out.getvalue())

    def test_two_seeds_are_loaded_and_pruned_as_a_union(self):
        """The PH spine can live in a worldwide seed and its barangays in a PH one.

        ``--prune`` must keep anything in either seed: pruning the world away
        would take the Philippine barangays with it, and pruning the PH seed
        away would drop every other country.
        """
        world = {
            'meta': {},
            'countries': [PHILIPPINES_SEED_ROW],
            'regions': [{'geoname_id': 7521301, 'code': '01', 'name': 'Ilocos',
                         'asciiname': '', 'latitude': None, 'longitude': None,
                         'feature_code': 'ADM1', 'country_geoname_id': 1694008}],
            'provinces': [{'geoname_id': 1695357, 'code': '51', 'name': 'Pangasinan',
                           'asciiname': '', 'latitude': None, 'longitude': None,
                           'feature_code': 'ADM2', 'region_geoname_id': 7521301}],
            'cities': [{'geoname_id': 1683502, 'code': '015533000', 'name': 'Dagupan City',
                        'asciiname': '', 'latitude': None, 'longitude': None,
                        'feature_code': 'ADM3', 'province_geoname_id': 1695357}],
            'barangays': [],
        }
        ph = {
            'meta': {},
            'countries': [PHILIPPINES_SEED_ROW],
            'regions': [{'geoname_id': 7521301, 'code': '01', 'name': 'Ilocos',
                         'asciiname': '', 'latitude': None, 'longitude': None,
                         'feature_code': 'ADM1', 'country_geoname_id': 1694008}],
            'provinces': [{'geoname_id': 1695357, 'code': '51', 'name': 'Pangasinan',
                           'asciiname': '', 'latitude': None, 'longitude': None,
                           'feature_code': 'ADM2', 'region_geoname_id': 7521301}],
            'cities': [{'geoname_id': 1683502, 'code': '015533000', 'name': 'Dagupan City',
                        'asciiname': '', 'latitude': None, 'longitude': None,
                        'feature_code': 'ADM3', 'province_geoname_id': 1695357}],
            'barangays': [{'geoname_id': self.poblacion.geoname_id, 'name': 'Poblacion',
                           'asciiname': '', 'latitude': None, 'longitude': None,
                           'feature_code': 'PPL', 'city_geoname_id': 1683502}],
        }
        stale = Barangay.objects.create(geoname_id=777, name='Stale', city_municipality=self.dagupan)

        with seed_file(world) as world_path, seed_file(ph) as ph_path:
            call_command('sync_geonames', seed=[world_path, ph_path], prune=True, verbosity=0)

        # Everything in either seed survives; the extra barangay does not.
        self.assertTrue(Barangay.objects.filter(geoname_id=self.poblacion.geoname_id).exists())
        self.assertFalse(Barangay.objects.filter(pk=stale.pk).exists())
        self.assertEqual(Country.objects.filter(code='PH', geoname_id=1694008).count(), 1)

    def test_prune_removes_rows_absent_from_seed(self):
        stale = Barangay.objects.create(geoname_id=555, name='Stale', city_municipality=self.dagupan)
        # The seed must stay internally consistent: keeping Poblacion means
        # keeping its city and province, otherwise the PROTECT foreign keys
        # would (correctly) refuse the delete.
        seed = {
            'meta': {},
            'countries': [PHILIPPINES_SEED_ROW],
            'regions': [{'geoname_id': 7521301, 'code': '01', 'name': 'Ilocos',
                         'asciiname': '', 'latitude': None, 'longitude': None,
                         'feature_code': 'ADM1', 'country_geoname_id': 1694008}],
            'provinces': [{'geoname_id': 1695357, 'code': '51', 'name': 'Pangasinan',
                           'asciiname': '', 'latitude': None, 'longitude': None,
                           'feature_code': 'ADM2', 'region_geoname_id': 7521301}],
            'cities': [{'geoname_id': 1683502, 'code': '015533000', 'name': 'Dagupan City',
                        'asciiname': '', 'latitude': None, 'longitude': None,
                        'feature_code': 'ADM3', 'province_geoname_id': 1695357}],
            'barangays': [{'geoname_id': self.poblacion.geoname_id, 'name': 'Poblacion',
                           'asciiname': '', 'latitude': None, 'longitude': None,
                           'feature_code': 'PPL', 'city_geoname_id': 1683502}],
        }
        with seed_file(seed) as path:
            call_command('sync_geonames', seed=path, prune=True, verbosity=0)
        self.assertFalse(Barangay.objects.filter(pk=stale.pk).exists())
        self.assertTrue(Barangay.objects.filter(geoname_id=self.poblacion.geoname_id).exists())
        # Mabini was not in the seed, so it is pruned.
        self.assertFalse(Barangay.objects.filter(name='Mabini').exists())
        # Urdaneta was not in the seed either.
        self.assertFalse(CityMunicipality.objects.filter(name='Urdaneta City').exists())


class HierarchyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(**PHILIPPINES_SEED_ROW)
        region = Region.objects.create(
            geoname_id=7521301, code='01', name='Ilocos', country=cls.country,
        )
        region_ncr = Region.objects.create(
            geoname_id=7521311, code='NCR', name='National Capital Region', country=cls.country,
        )
        province = Province.objects.create(geoname_id=1695357, code='51', name='Pangasinan', region=region)
        district = Province.objects.create(
            geoname_id=11395836, code='137400000', name='Eastern Manila District', region=region_ncr,
        )
        dagupan = CityMunicipality.objects.create(
            geoname_id=1683502, code='015533000', name='Dagupan City', province=province,
        )
        CityMunicipality.objects.create(
            geoname_id=1114855, code='137402000', name='Quezon City', province=district,
        )
        CityMunicipality.objects.create(
            geoname_id=222, code='015599000', name='Urdaneta City', province=province,
        )
        Barangay.objects.create(geoname_id=1111111, name='Poblacion', city_municipality=dagupan)
        Barangay.objects.create(geoname_id=1111112, name='Mabini', city_municipality=dagupan)

    def test_tree_offers_every_geonames_municipality(self):
        tree = build_location_hierarchy()
        pangasinan = next(p for p in tree['provinces'] if p['name'] == 'Pangasinan')
        names = {m['name'] for m in pangasinan['municipalities']}
        self.assertEqual(names, {'Dagupan City', 'Urdaneta City'})

    def test_ncr_districts_are_presented_as_metro_manila(self):
        tree = build_location_hierarchy()
        province_names = {p['name'] for p in tree['provinces']}
        self.assertNotIn('Eastern Manila District', province_names)
        metro = next(p for p in tree['provinces'] if p['name'] == 'Metro Manila')
        self.assertEqual([m['name'] for m in metro['municipalities']], ['Quezon City'])

    def test_barangays_only_populated_for_municipalities_in_use(self):
        from hotels.models import Hotel

        Hotel.objects.create(name='Test hotel', province='Pangasinan', municipality='Dagupan City')
        tree = build_location_hierarchy()
        pangasinan = next(p for p in tree['provinces'] if p['name'] == 'Pangasinan')
        by_name = {m['name']: m['barangays'] for m in pangasinan['municipalities']}
        self.assertEqual(sorted(by_name['Dagupan City']), ['Mabini', 'Poblacion'])
        # Urdaneta is on file but no listing uses it, so it carries no barangays.
        self.assertEqual(by_name['Urdaneta City'], [])

    def test_city_named_after_its_province_is_kept(self):
        """A listing saying "Cebu City" under province "Cebu" must not be dropped."""
        from hotels.models import Hotel

        Hotel.objects.create(name='Test hotel', province='Pangasinan',
                             municipality='Dagupan City', barangay='Poblacion')
        Hotel.objects.create(name='Other hotel', province='Pangasinan',
                             municipality='Dagupan', barangay='Mabini')
        tree = build_location_hierarchy()
        pangasinan = next(p for p in tree['provinces'] if p['name'] == 'Pangasinan')
        names = {m['name'] for m in pangasinan['municipalities']}
        # "Dagupan" resolves onto the canonical "Dagupan City" rather than
        # creating a second, bogus municipality.
        self.assertIn('Dagupan City', names)
        self.assertNotIn('Dagupan', names)

    def test_tree_is_json_serialisable_and_shaped_for_the_frontend(self):
        tree = build_location_hierarchy()
        json.dumps(tree, ensure_ascii=False)
        self.assertEqual(tree['country'], 'Philippines')
        for province in tree['provinces']:
            self.assertIn('name', province)
            for municipality in province['municipalities']:
                self.assertIn('name', municipality)
                self.assertIsInstance(municipality['barangays'], list)

    def test_falls_back_to_static_map_when_tables_are_empty(self):
        wipe_hierarchy()
        tree = build_location_hierarchy()
        self.assertTrue(tree['provinces'], 'fallback should still offer provinces')
        self.assertIn('Cagayan', {p['name'] for p in tree['provinces']})

    def test_country_comes_from_the_database_not_a_constant(self):
        tree = build_location_hierarchy()
        self.assertEqual(tree['country'], self.country.name)
        self.assertEqual(tree['country_code'], 'PH')
        # The name is read from the row, not from the COUNTRY_NAME fallback, so a
        # row that spells it differently wins.
        self.country.name = 'Republika ng Pilipinas'
        self.country.save()
        self.assertEqual(build_location_hierarchy()['country'], 'Republika ng Pilipinas')

    def test_country_falls_back_to_the_constant_when_unloaded(self):
        wipe_hierarchy()
        tree = build_location_hierarchy()
        self.assertEqual(tree['country'], 'Philippines')
        self.assertEqual(tree['country_code'], '')

    def test_provinces_carry_their_region(self):
        tree = build_location_hierarchy()
        by_name = {p['name']: p for p in tree['provinces']}
        self.assertEqual(by_name['Pangasinan']['region'], 'Ilocos')
        # The collapsed NCR still reports the region it really belongs to.
        self.assertEqual(by_name['Metro Manila']['region'], 'National Capital Region')


class CountryLevelTests(TestCase):
    """The country is the first step of the picker, so it has to be real data."""

    def setUp(self):
        # Any earlier test that rendered a page cached the inlined default tree
        # (a module-level lru_cache keyed by country code). Tests share one
        # process, so that cached tree may have been built from an unrelated
        # database state -- clear it to test against this class's own data.
        from atrue_core.context_processors import _location_tree_cached
        _location_tree_cached.cache_clear()

    @classmethod
    def setUpTestData(cls):
        cls.ph = Country.objects.create(**PHILIPPINES_SEED_ROW)
        region_ph = Region.objects.create(
            geoname_id=7521301, code='01', name='Ilocos', country=cls.ph,
        )
        region_ncr = Region.objects.create(
            geoname_id=7521311, code='NCR', name='National Capital Region', country=cls.ph,
        )
        cls.pangasinan = Province.objects.create(
            geoname_id=1695357, code='51', name='Pangasinan', region=region_ph,
        )
        district = Province.objects.create(
            geoname_id=11395836, code='137400000', name='Eastern Manila District', region=region_ncr,
        )
        CityMunicipality.objects.create(
            geoname_id=1683502, code='015533000', name='Dagupan City', province=cls.pangasinan,
        )
        CityMunicipality.objects.create(
            geoname_id=1114855, code='137402000', name='Quezon City', province=district,
        )

    def test_tree_lists_countries_with_a_province_count(self):
        tree = build_location_hierarchy()
        self.assertEqual(
            tree['countries'], [{'code': 'PH', 'name': 'Philippines', 'count': 2}]
        )

    def test_every_province_carries_its_country(self):
        tree = build_location_hierarchy()
        by_name = {p['name']: p for p in tree['provinces']}
        self.assertEqual(by_name['Pangasinan']['country'], 'Philippines')
        self.assertEqual(by_name['Pangasinan']['country_code'], 'PH')
        # The collapsed NCR keeps the country too.
        self.assertEqual(by_name['Metro Manila']['country_code'], 'PH')

    def test_country_province_keys_expands_the_collapsed_ncr(self):
        keys = country_province_keys('Philippines')
        self.assertIn('pangasinan', keys)
        # Stored as a district, shown as "Metro Manila".
        self.assertIn('metro manila', keys)
        self.assertNotIn('eastern manila district', keys)

    def test_country_province_keys_accepts_an_iso_code_or_a_name(self):
        self.assertEqual(country_province_keys('PH'), country_province_keys('Philippines'))
        self.assertEqual(country_province_keys('philippines'), country_province_keys('PH'))

    def test_country_province_keys_is_none_for_unknown_or_blank(self):
        """None tells the caller to skip the filter, not to match everything."""
        for value in ('', '   ', 'Atlantis', 'ZZ'):
            self.assertIsNone(country_province_keys(value))

    def test_country_only_selection_matches_via_province_ownership(self):
        keys = country_province_keys('Philippines')
        in_ph = {'province': ['Pangasinan'], 'municipality': [], 'barangay': [], 'loc_text': ''}
        self.assertTrue(location_matches(in_ph, '', '', '', '', country='Philippines', country_provinces=keys))
        # A province the country does not own must not match.
        elsewhere = {'province': ['Bangkok'], 'municipality': [], 'barangay': [], 'loc_text': ''}
        self.assertFalse(location_matches(elsewhere, '', '', '', '', country='Philippines', country_provinces=keys))

    def test_country_is_skipped_when_a_province_is_also_selected(self):
        """The province already implies its country, so no lookup is needed."""
        loc = {'province': ['Pangasinan'], 'municipality': ['Dagupan City'], 'barangay': [], 'loc_text': ''}
        self.assertTrue(location_matches(loc, 'Pangasinan', 'Dagupan City', '', '', country='Philippines', country_provinces=None))

    def test_country_matches_a_free_text_blob(self):
        """Restaurants only have a combined location string."""
        keys = country_province_keys('Philippines')
        self.assertTrue(location_matches({}, '', '', '', 'Baggao, Cagayan, Philippines', country='Philippines', country_provinces=keys))
        self.assertFalse(location_matches({}, '', '', '', 'Baggao, Cagayan', country='Thailand', country_provinces=set()))

    def test_country_alone_does_not_match_an_item_with_no_location(self):
        keys = country_province_keys('Philippines')
        self.assertFalse(location_matches({'province': [], 'municipality': [], 'barangay': [], 'loc_text': ''},
                                          '', '', '', '', country='Philippines', country_provinces=keys))

    def test_no_location_selection_matches_everything(self):
        loc = {'province': ['Pangasinan'], 'municipality': [], 'barangay': [], 'loc_text': ''}
        self.assertTrue(location_matches(loc, '', '', '', ''))

    def test_location_display_puts_the_country_first(self):
        self.assertEqual(
            location_display('Cagayan', 'Baggao', None, 'Philippines'),
            'Philippines, Cagayan, Baggao',
        )
        # Still works without one.
        self.assertEqual(location_display('Cagayan', 'Baggao'), 'Cagayan, Baggao')

    def test_second_country_appears_in_the_tree(self):
        """A second country must not leak into the default tree or share codes.

        The default tree is scoped to the platform's own country; the other one is
        reachable on demand. Both happen to use ``01` as a region code -- exactly
        the collision the earlier code-based seed would have merged.
        """
        thailand = Country.objects.create(
            geoname_id=8350000, code='TH', name='Thailand', asciiname='Thailand',
        )
        region_th = Region.objects.create(
            geoname_id=8350001, code='01', name='Bangkok', country=thailand,
        )
        Province.objects.create(geoname_id=8350002, code='A10', name='Bangkok', region=region_th)
        CityMunicipality.objects.create(
            geoname_id=8350003, code='1001', name='Bangkok', province=Province.objects.get(code='A10'),
        )

        tree = build_location_hierarchy()
        # The country list shows both, each with its province count.
        codes = {c['code']: c for c in tree['countries']}
        self.assertEqual(set(codes), {'PH', 'TH'})
        self.assertEqual(codes['PH']['count'], 2)
        self.assertEqual(codes['TH']['count'], 1)
        # But the tree's provinces are only the platform's own country.
        by_name = {p['name']: p for p in tree['provinces']}
        self.assertNotIn('Bangkok', by_name)
        self.assertEqual(by_name['Pangasinan']['country_code'], 'PH')

        # The other country is served on demand and only carries its own data.
        th_tree = build_location_hierarchy('Thailand')
        self.assertEqual(th_tree['country'], 'Thailand')
        self.assertEqual(th_tree['country_code'], 'TH')
        th_by_name = {p['name']: p for p in th_tree['provinces']}
        self.assertEqual(set(th_by_name), {'Bangkok'})
        self.assertEqual(th_by_name['Bangkok']['country_code'], 'TH')
        self.assertEqual(th_by_name['Bangkok']['region'], 'Bangkok')

        # A Thailand-only province is reachable by its own country's key, and an
        # ISO-2 code works as well as the name.
        th_keys = country_province_keys('Thailand')
        self.assertIn('bangkok', th_keys)
        self.assertNotIn('pangasinan', th_keys)
        self.assertEqual(country_province_keys('TH'), th_keys)

    def test_default_location_api_serves_only_the_primary_country(self):
        response = self.client.get(reverse('location_api'))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['country_code'], 'PH')
        self.assertEqual({c['code'] for c in payload['countries']}, {'PH'})

    def test_location_api_serves_an_other_country_on_demand(self):
        thailand = Country.objects.create(
            geoname_id=8350000, code='TH', name='Thailand', asciiname='Thailand',
        )
        region_th = Region.objects.create(
            geoname_id=8350001, code='01', name='Bangkok', country=thailand,
        )
        Province.objects.create(geoname_id=8350002, code='A10', name='Bangkok', region=region_th)

        response = self.client.get(reverse('location_api'), {'country': 'TH'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['country'], 'Thailand')
        self.assertEqual([p['name'] for p in payload['provinces']], ['Bangkok'])

    def test_location_api_400_for_an_unknown_country(self):
        response = self.client.get(reverse('location_api'), {'country': 'Atlantis'})
        self.assertEqual(response.status_code, 400)

    def test_foreign_tree_has_no_philippine_overrides(self):
        """The NCR collapse, aliases and popular list are Philippine-only."""
        japan = Country.objects.create(geoname_id=8350010, code='JP', name='Japan', asciiname='Japan')
        Region.objects.create(geoname_id=8350011, code='NCR', name='Kanto', country=japan)
        Province.objects.create(geoname_id=8350012, code='N1', name='X', region=Region.objects.get(geoname_id=8350011))

        tree = build_location_hierarchy('JP')
        self.assertEqual({p['name'] for p in tree['provinces']}, {'X'})
        self.assertEqual(tree['popular'], [])
        self.assertEqual(tree['aliases'], {})

    def test_search_page_accepts_a_country_only_filter(self):
        response = self.client.get('/hotels/', {'loc_country': 'Philippines'})
        self.assertEqual(response.status_code, 200)
        response = self.client.get('/hotels/', {'loc_country': 'Atlantis'})
        # An unknown country must not blow up or silently return everything.
        self.assertEqual(response.status_code, 200)


class LocationErrorsTests(TestCase):
    """The shared server-side validator behind the worldwide cascade picker."""

    def setUp(self):
        from atrue_core.context_processors import _location_tree_cached
        _location_tree_cached.cache_clear()

    @classmethod
    def setUpTestData(cls):
        cls.ph = Country.objects.create(**PHILIPPINES_SEED_ROW)
        region_ph = Region.objects.create(
            geoname_id=7521301, code='01', name='Ilocos', country=cls.ph,
        )
        cls.pangasinan = Province.objects.create(
            geoname_id=1695357, code='51', name='Pangasinan', region=region_ph,
        )
        dagupan = CityMunicipality.objects.create(
            geoname_id=1683502, code='015533000', name='Dagupan City', province=cls.pangasinan,
        )
        Barangay.objects.create(geoname_id=1111111, name='Poblacion', city_municipality=dagupan)

        # A listing that actually uses Dagupan so its barangays get inlined and
        # the barangay-required rule applies (barangays attach to "used" cities).
        from hotels.models import Hotel
        Hotel.objects.create(
            name='Dagupan Plaza', province='Pangasinan',
            municipality='Dagupan City', barangay='Poblacion',
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

    def test_home_country_valid_with_barangay(self):
        self.assertEqual(location_errors('', 'Pangasinan', 'Dagupan City', 'Poblacion'), [])
        self.assertEqual(location_errors('PH', 'Pangasinan', 'Dagupan City', 'Poblacion'), [])
        self.assertEqual(location_errors('Philippines', 'Pangasinan', 'Dagupan City', 'Poblacion'), [])

    def test_barangay_required_only_when_one_is_on_file(self):
        self.assertEqual(
            location_errors('', 'Pangasinan', 'Dagupan City', ''),
            ["Barangay is required for Dagupan City, Pangasinan."],
        )

    def test_foreign_country_ok_without_barangay(self):
        self.assertEqual(location_errors('Thailand', 'Bangkok', 'Bangkok'), [])
        self.assertEqual(location_errors('TH', 'Bangkok', 'Bangkok', ''), [])

    def test_province_municipality_must_form_a_pair_in_the_same_country(self):
        # A Philippine province does not exist inside Thailand's tree.
        self.assertEqual(
            location_errors('Thailand', 'Pangasinan', 'Bangkok'),
            ["'Pangasinan' is not a recognized province."],
        )
        # And a Bangkok municipality is not part of the Philippine province.
        self.assertEqual(
            location_errors('', 'Pangasinan', 'Bangkok'),
            ["'Bangkok' is not part of Pangasinan."],
        )

    def test_required_fields(self):
        self.assertIn('Province is required.', location_errors('', '', 'Dagupan City'))
        self.assertIn('Municipality/City is required.', location_errors('', 'Pangasinan', ''))

    def test_country_name_or_code_or_blank_mean_the_home_country(self):
        self.assertEqual(
            location_errors('Philippines', 'Pangasinan', 'Dagupan City', 'Poblacion'),
            location_errors('PH', 'Pangasinan', 'Dagupan City', 'Poblacion'),
        )
        self.assertEqual(
            location_errors('PH', 'Pangasinan', 'Dagupan City', 'Poblacion'),
            location_errors('', 'Pangasinan', 'Dagupan City', 'Poblacion'),
        )

    def test_foreign_listings_do_not_leak_into_the_home_tree(self):
        """A hotel in another country must never inject its provinces into PH."""
        from hotels.models import Hotel
        Hotel.objects.create(
            name='Bangkok Riverside', province='Bangkok', municipality='Bangkok', country='Thailand',
        )
        Hotel.objects.create(
            name='Pangasinan Lodge', province='Pangasinan', municipality='Dagupan City', country='Philippines',
        )
        tree = build_location_hierarchy()
        by_name = {p['name']: p for p in tree['provinces']}
        self.assertNotIn('Bangkok', by_name)
        # The home-country listing is still merged in.
        self.assertEqual(
            [m['name'] for m in by_name['Pangasinan']['municipalities']],
            ['Dagupan City'],
        )


class LazyBarangayTests(TestCase):
    """The on-demand barangay list behind the add/edit cascade and search picker.

    The inlined tree only carries barangays for municipalities a listing already
    uses, so the rest are fetched per municipality at selection time. These tests
    pin that the fetched list is identical to the one that would have been
    inlined, because a difference would make a saved location look unrecognised.
    """

    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(**PHILIPPINES_SEED_ROW)
        region = Region.objects.create(
            geoname_id=7521301, code='01', name='Ilocos', country=cls.country,
        )
        region_ncr = Region.objects.create(
            geoname_id=7521311, code='NCR', name='National Capital Region', country=cls.country,
        )
        cls.pangasinan = Province.objects.create(
            geoname_id=1695357, code='51', name='Pangasinan', region=region,
        )
        district = Province.objects.create(
            geoname_id=11395836, code='137400000', name='Eastern Manila District', region=region_ncr,
        )
        cls.dagupan = CityMunicipality.objects.create(
            geoname_id=1683502, code='015533000', name='Dagupan City', province=cls.pangasinan,
        )
        cls.quezon = CityMunicipality.objects.create(
            geoname_id=1114855, code='137402000', name='Quezon City', province=district,
        )
        # A municipality with barangays on file but no listing using it, which is
        # exactly the case the inline tree leaves empty.
        cls.urdaneta = CityMunicipality.objects.create(
            geoname_id=222, code='015599000', name='Urdaneta City', province=cls.pangasinan,
        )
        cls.poblacion = Barangay.objects.create(
            geoname_id=1111111, name='Poblacion', city_municipality=cls.dagupan,
        )
        Barangay.objects.create(geoname_id=1111112, name='Mabini', city_municipality=cls.dagupan)
        Barangay.objects.create(geoname_id=1111113, name='Anthem', city_municipality=cls.urdaneta)
        Barangay.objects.create(geoname_id=1111114, name='Bagong Silangan', city_municipality=cls.quezon)

    def test_resolves_municipality_that_the_tree_left_empty(self):
        from atrue_core.location_hierarchy import build_location_hierarchy

        tree = build_location_hierarchy()
        pangasinan = next(p for p in tree['provinces'] if p['name'] == 'Pangasinan')
        inlined = {m['name']: m['barangays'] for m in pangasinan['municipalities']}
        self.assertEqual(inlined['Urdaneta City'], [], 'fixture must leave this one empty')

        self.assertEqual(
            municipality_barangays('Pangasinan', 'Urdaneta City'), ['Anthem']
        )

    def test_resolves_collapsed_ncr_label(self):
        """The tree shows "Metro Manila"; the rows live under a district."""
        self.assertEqual(
            municipality_barangays('Metro Manila', 'Quezon City'), ['Bagong Silangan']
        )

    def test_stored_province_names_maps_the_ncr_label(self):
        self.assertEqual(
            stored_province_names('Metro Manila'), ['Eastern Manila District']
        )
        self.assertEqual(stored_province_names('Pangasinan'), ['Pangasinan'])

    def test_matching_ignores_case_padding_and_the_city_suffix(self):
        for label in ('Pangasinan', 'pangasinan', '  PANGASINAN '):
            for muni in ('Dagupan City', 'dagupan city', ' DAGUPAN   CITY '):
                self.assertEqual(
                    municipality_barangays(label, muni), ['Mabini', 'Poblacion']
                )

    def test_unknown_and_blank_input_yields_an_empty_list(self):
        for province, muni in (('', ''), ('Nowhere', 'X'), ('Pangasinan', ''),
                               ('Pangasinan', 'No Such Town')):
            self.assertEqual(municipality_barangays(province, muni), [])

    def test_includes_barangay_that_only_exists_in_listing_text(self):
        """A name GeoNames lacks must not vanish from its own city."""
        from hotels.models import Hotel

        Hotel.objects.create(name='Legacy hotel', province='Pangasinan',
                             municipality='Dagupan City', barangay='Legacy Brgy')
        self.assertIn(
            'Legacy Brgy', municipality_barangays('Pangasinan', 'Dagupan City')
        )

    def test_listing_province_alias_still_matches(self):
        """A listing naming an old province GeoNames folded away still matches.

        "Siargao" is an alias for "Surigao del Norte", so a hotel recorded that
        way contributes a barangay to Surigao del Norte in the tree. The lazy
        lookup has to reach the same conclusion.
        """
        from atrue_core.location_hierarchy import PLACE_ALIASES
        from hotels.models import Hotel

        self.assertEqual(
            PLACE_ALIASES['Siargao']['province'], 'Surigao del Norte',
            'fixture assumes this alias exists',
        )
        surigao = Province.objects.create(
            geoname_id=444, code='30', name='Surigao del Norte', region=self.pangasinan.region,
        )
        general_luna = CityMunicipality.objects.create(
            geoname_id=555, code='303800000', name='General Luna', province=surigao,
        )
        Barangay.objects.create(geoname_id=556, name='Tourism', city_municipality=general_luna)
        Hotel.objects.create(name='Island resort', province='Siargao',
                             municipality='General Luna', barangay='Legacy Brgy')

        self.assertIn(
            'Legacy Brgy',
            municipality_barangays('Surigao del Norte', 'General Luna'),
        )

    def test_fetched_list_matches_the_inlined_list(self):
        from atrue_core.location_hierarchy import build_location_hierarchy

        from hotels.models import Hotel

        Hotel.objects.create(name='In use', province='Pangasinan',
                             municipality='Dagupan City', barangay='Mabini')
        tree = build_location_hierarchy()
        for province in tree['provinces']:
            for municipality in province['municipalities']:
                if not municipality['barangays']:
                    continue
                self.assertEqual(
                    set(municipality['barangays']),
                    set(municipality_barangays(province['name'], municipality['name'])),
                    f"{province['name']} / {municipality['name']}",
                )

    def test_api_returns_the_list_for_a_valid_pair(self):
        response = self.client.get(
            reverse('location_barangays_api'),
            {'province': 'Pangasinan', 'municipality': 'Urdaneta City'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['barangays'], ['Anthem'])
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['province'], 'Pangasinan')
        self.assertEqual(payload['municipality'], 'Urdaneta City')
        self.assertEqual(payload['country'], 'Philippines')
        self.assertEqual(payload['country_code'], 'PH')

    def test_api_degrades_to_an_empty_list_instead_of_erroring(self):
        """A stale page must fall back to free text, not 500."""
        for query in ({}, {'province': 'Nowhere', 'municipality': 'X'}):
            response = self.client.get(reverse('location_barangays_api'), query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['barangays'], [])
            self.assertEqual(response.json()['count'], 0)

    def test_api_resolves_the_collapsed_ncr_label(self):
        response = self.client.get(
            reverse('location_barangays_api'),
            {'province': 'Metro Manila', 'municipality': 'Quezon City'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['barangays'], ['Bagong Silangan'])


class ServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(**PHILIPPINES_SEED_ROW)
        region = Region.objects.create(
            geoname_id=1, code='06', name='Western Visayas', country=cls.country,
        )
        province = Province.objects.create(geoname_id=2, code='04', name='Aklan', region=region)
        malay = CityMunicipality.objects.create(
            geoname_id=3, code='060402000', name='Malay', province=province,
        )
        Barangay.objects.create(geoname_id=4, name='Balabag', city_municipality=malay)

    def test_is_populated_and_stats(self):
        self.assertTrue(geonames_service.is_populated())
        self.assertEqual(geonames_service.hierarchy_stats()['barangays'], 1)
        self.assertEqual(geonames_service.hierarchy_stats()['countries'], 1)

    def test_default_country(self):
        country = geonames_service.default_country()
        self.assertEqual(country['code'], 'PH')
        self.assertEqual(country['name'], 'Philippines')
        self.assertEqual(country['region_count'], 1)

    def test_default_country_is_none_when_unloaded(self):
        wipe_hierarchy()
        self.assertIsNone(geonames_service.default_country())
        self.assertFalse(geonames_service.is_populated())

    def test_resolve_location_is_tolerant_and_hierarchical(self):
        result = geonames_service.resolve_location('aklan', 'Malay', 'Balabag')
        self.assertEqual(result['province'], 'Aklan')
        self.assertEqual(result['municipality'], 'Malay')
        self.assertEqual(result['barangay'], 'Balabag')
        self.assertEqual(result['region'], 'Western Visayas')
        self.assertEqual(result['country'], 'Philippines')
        self.assertEqual(result['country_code'], 'PH')


    def test_resolve_location_rejects_a_municipality_from_another_province(self):
        result = geonames_service.resolve_location('Aklan', 'Davao City')
        self.assertEqual(result['municipality'], '')
        self.assertEqual(result['province'], 'Aklan')

    def test_resolve_location_unknown_province_returns_empty(self):
        result = geonames_service.resolve_location('Atlantis', 'Malay')
        self.assertEqual(result['province'], '')
        self.assertEqual(result['municipality'], '')

    def test_search_places_finds_each_level(self):
        results = geonames_service.search_places('Malay')
        self.assertEqual([r['level'] for r in results], ['city'])
        self.assertEqual(results[0]['province'], 'Aklan')
        self.assertEqual(results[0]['country'], 'Philippines')

        results = geonames_service.search_places('Balabag')
        self.assertEqual([r['level'] for r in results], ['barangay'])
        self.assertEqual(results[0]['municipality'], 'Malay')
        self.assertEqual(results[0]['country_code'], 'PH')

    def test_search_places_ignores_blank_query(self):
        self.assertEqual(geonames_service.search_places('   '), [])


class WorldwideGeoNamesSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        thailand = Country.objects.create(
            geoname_id=9000001, code='TH', name='Thailand', asciiname='Thailand',
        )
        region = Region.objects.create(
            geoname_id=9000002, code='10', name='Bangkok', country=thailand,
        )
        province = Province.objects.create(
            geoname_id=9000003, code='BKK', name='Bangkok', region=region,
        )
        CityMunicipality.objects.create(
            geoname_id=9000004, code='1001', name='Bangkok', province=province,
        )

        brazil = Country.objects.create(
            geoname_id=9000005, code='BR', name='Brazil', asciiname='Brazil',
        )
        region = Region.objects.create(
            geoname_id=9000006, code='27', name='Sao Paulo', country=brazil,
        )
        province = Province.objects.create(
            geoname_id=9000007, code='SP', name='São Paulo', asciiname='Sao Paulo',
            region=region,
        )
        CityMunicipality.objects.create(
            geoname_id=9000008, code='3550308', name='São Paulo',
            asciiname='Sao Paulo', province=province,
        )

    def test_search_api_finds_places_outside_the_primary_country(self):
        response = self.client.get(
            reverse('location_search_api'), {'q': 'Bangkok'},
        )

        self.assertEqual(response.status_code, 200)
        city = next(
            result for result in response.json()['results']
            if result['level'] == 'city' and result['country_code'] == 'TH'
        )
        self.assertEqual(city['municipality'], 'Bangkok')
        self.assertEqual(city['country'], 'Thailand')

    def test_search_api_matches_ascii_place_names(self):
        response = self.client.get(
            reverse('location_search_api'), {'q': 'Sao Paulo'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(
            result['level'] == 'city'
            and result['country_code'] == 'BR'
            and result['name'] == 'São Paulo'
            for result in response.json()['results']
        ))

    def test_search_api_ignores_queries_shorter_than_two_characters(self):
        response = self.client.get(reverse('location_search_api'), {'q': 'B'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])


class SeedFileTests(TestCase):
    """The committed seeds must match what the models expect."""

    DATA_DIR = Path(__file__).resolve().parent / 'data'

    def _assert_links_resolve(self, seed, name):
        """Every child links to a parent actually in the seed, by geoname id."""
        country_ids = {c['geoname_id'] for c in seed['countries']}
        region_ids = {r['geoname_id'] for r in seed['regions']}
        province_ids = {p['geoname_id'] for p in seed['provinces']}
        city_ids = {c['geoname_id'] for c in seed['cities']}

        self.assertTrue(len(seed['countries']) >= 1, name)
        for region in seed['regions']:
            self.assertIn(region['country_geoname_id'], country_ids, name)
        for province in seed['provinces']:
            self.assertIn(province['region_geoname_id'], region_ids, name)
        for city in seed['cities']:
            self.assertIn(city['province_geoname_id'], province_ids, name)
        for barangay in seed['barangays']:
            self.assertIn(barangay['city_geoname_id'], city_ids, name)

    def test_seed_files_are_present_and_consistent(self):
        for name in ('geonames_ph.json', 'geonames_world.json'):
            seed_path = self.DATA_DIR / name
            self.assertTrue(seed_path.exists(), 'run locations/data/build_geonames_seed.py')
            seed = json.loads(seed_path.read_text(encoding='utf-8'))
            self._assert_links_resolve(seed, name)

    def test_philippines_seed_shape(self):
        seed = json.loads((self.DATA_DIR / 'geonames_ph.json').read_text(encoding='utf-8'))
        self.assertEqual(seed['meta']['scope'], 'PH')
        self.assertEqual(len(seed['countries']), 1)
        self.assertEqual(seed['countries'][0]['code'], 'PH')
        # The display name is the short form; the constitutional name is kept aside.
        self.assertEqual(seed['countries'][0]['name'], 'Philippines')
        self.assertEqual(seed['countries'][0]['feature_code'], 'PCLI')
        self.assertEqual(len(seed['regions']), 17)
        # The settlement level is what makes this seed more than the world spine.
        self.assertGreater(len(seed['barangays']), 40000)

    def test_worldwide_seed_covers_the_spine(self):
        seed = json.loads((self.DATA_DIR / 'geonames_world.json').read_text(encoding='utf-8'))
        self.assertEqual(seed['meta']['scope'], 'world')
        # The settlement level is only produced by a --levels full build (PH).
        self.assertEqual(seed['barangays'], [])
        # Sanity floors so a truncated or half-built seed never sneaks in.
        self.assertGreaterEqual(len(seed['countries']), 200)
        self.assertGreaterEqual(len(seed['regions']), 3000)
        self.assertGreaterEqual(len(seed['provinces']), 40000)
        self.assertGreaterEqual(len(seed['cities']), 100000)

    def test_worldwide_seed_contains_every_iso_territory(self):
        """Territories the dump never mentions must still be selectable.

        GeoNames records a ``PCLI`` row for most countries, but small
        dependencies and disputed territories such as Gibraltar, the Cocos
        Islands or Antarctica have none, and no ``ADM1`` row either, so nothing
        in the dump pulls them in. An airport in one of them would then keep a
        bare ISO code as its country name. They are added from countryInfo.txt
        instead, so the seed covers the whole ISO 3166-1 list.
        """
        seed = json.loads((self.DATA_DIR / 'geonames_world.json').read_text(encoding='utf-8'))
        by_code = {c['code']: c for c in seed['countries']}
        self.assertEqual(len(by_code), len(seed['countries']), 'duplicate country code')

        territories = ('TC', 'VG', 'EH', 'AQ', 'FK', 'GI', 'AW', 'CW', 'IO',
                       'CC', 'CX', 'NU', 'SX', 'BL', 'NF')
        for code in territories:
            self.assertIn(code, by_code, f'{code} missing from the world seed')
            country = by_code[code]
            # A human name, not the bare code that countryInfo.txt never fills.
            self.assertTrue(country['name'], code)
            self.assertNotEqual(country['name'], code, code)
            self.assertEqual(country['feature_code'], 'PCLI', code)

    def test_worldwide_seed_country_ids_are_unique(self):
        """Ids must stay distinct: children link to their country by this id."""
        seed = json.loads((self.DATA_DIR / 'geonames_world.json').read_text(encoding='utf-8'))
        ids = [c['geoname_id'] for c in seed['countries']]
        self.assertEqual(len(ids), len(set(ids)))
        # A synthetic id must never collide with a real positive GeoNames id.
        for country in seed['countries']:
            if country['geoname_id'] < 0:
                self.assertNotIn(country['geoname_id'], set(i for i in ids if i >= 0),
                                 country['code'])

    def test_worldwide_seed_contains_the_philippines_spine(self):
        """The platform's own country must be fully selectable from the world seed."""
        seed = json.loads((self.DATA_DIR / 'geonames_world.json').read_text(encoding='utf-8'))
        ph = [c for c in seed['countries'] if c['code'] == 'PH']
        self.assertEqual(len(ph), 1)
        self.assertEqual(ph[0]['name'], 'Philippines')
        ph_regions = [r for r in seed['regions'] if r['country_geoname_id'] == ph[0]['geoname_id']]
        self.assertGreaterEqual(len(ph_regions), 17)


class CascadeContractTests(TestCase):
    """The five-level cascade: Country -> Region -> Province -> Municipality -> Barangay.

    The cascade itself is client-side JavaScript, and the project has no JS test
    runner, so these tests pin the two halves it depends on: the markup hooks it
    binds to, and the data contract its ``country == 'PH'`` branch reads.
    """

    PARTIAL = 'search/_loc_cascade_field.html'
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self._seq = 0

    def render_cascade(self, **context):
        base = {
            'country_name': 'country',
            'country_value': '',
            'province_name': 'province',
            'province_value': '',
            'municipality_name': 'municipality',
            'municipality_value': '',
            'barangay_name': 'barangay',
            'barangay_value': '',
        }
        base.update(context)
        return render_to_string(self.PARTIAL, base)

    # ---- markup the JS binds to ---------------------------------

    def test_partial_renders_all_five_levels_in_order(self):
        html = self.render_cascade()
        positions = []
        for level in ('country', 'region', 'province', 'municipality', 'barangay'):
            marker = 'data-cascade="%s"' % level
            self.assertIn(marker, html, level)
            positions.append(html.index(marker))
        self.assertEqual(positions, sorted(positions),
                         'levels must appear in cascade order')

    def test_region_select_is_a_filter_unless_a_field_name_is_given(self):
        """A filter needs no model column; where one exists it must submit."""
        html = self.render_cascade()
        self.assertIn('data-cascade="region"', html)
        self.assertNotRegex(html, r'<select[^>]*data-cascade="region"[^>]*\bname=')

        html = self.render_cascade(region_name='region', region_value='Bicol Region')
        self.assertRegex(html, r'<select[^>]*name="region"[^>]*data-cascade="region"')
        self.assertIn('data-init-region="Bicol Region"', html)

    def test_barangay_group_is_marked_so_it_can_be_hidden_entirely(self):
        """Non-Philippine countries hide the level, so the wrapper is the hook."""
        html = self.render_cascade()
        self.assertEqual(html.count('data-cascade-group="barangay"'), 1)
        group = html[html.index('data-cascade-group="barangay"'):]
        # Both controls live inside the group: the pick-list and the free-text
        # fallback share one name, and the JS keeps exactly one enabled.
        self.assertIn('data-cascade="barangay"', group)
        self.assertIn('data-cascade="barangay-text"', group)

    def test_country_province_municipality_barangay_still_submit(self):
        html = self.render_cascade()
        for field in ('country', 'province', 'municipality', 'barangay'):
            self.assertRegex(html, r'<select[^>]*name="%s"' % field, field)

    # ---- the data the PH-only branch reads ---------------------

    def _make_country(self, code, name, region_name):
        self._seq += 1
        country = Country.objects.create(
            geoname_id=9900000 + self._seq, code=code, name=name, asciiname=name)
        region = Region.objects.create(
            geoname_id=9800000 + self._seq, code='R1', name=region_name, country=country)
        province = Province.objects.create(
            geoname_id=9700000 + self._seq, code='P1', name='P1', region=region)
        return country, region, province

    def test_philippine_flow_offers_barangays(self):
        """The Philippines is the one country that keeps all five levels."""
        self._make_country('PH', 'Philippines', 'Bicol')
        city = CityMunicipality.objects.create(
            geoname_id=9600000, code='M1', name='Altavas',
            province=Province.objects.get(code='P1'))
        Barangay.objects.create(
            geoname_id=9500000, name='Bankerohan', city_municipality=city)

        tree = build_location_hierarchy('PH')
        entry = next(p for p in tree['provinces'] if p['name'] == 'P1')
        self.assertEqual(entry['region'], 'Bicol')

        response = self.client.get(reverse('location_barangays_api'), {
            'country': 'PH', 'province': 'P1', 'municipality': 'Altavas',
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['country_code'], 'PH')
        self.assertIn('Bankerohan', payload['barangays'])

    def test_non_philippine_flow_has_regions_but_no_barangays(self):
        """Elsewhere the cascade ends at Municipality/City, so barangays are empty."""
        self._make_country('JP', 'Japan', 'Kanto')
        tree = build_location_hierarchy('JP')
        self.assertEqual(len(tree['provinces']), 1)
        entry = tree['provinces'][0]
        # The region level is worldwide, which is what makes a US or Japanese
        # province list navigable at all.
        self.assertEqual(entry['region'], 'Kanto')
        for muni in entry['municipalities']:
            self.assertEqual(muni['barangays'], [])

    def test_barangays_endpoint_is_empty_for_a_foreign_country(self):
        country, _region, province = self._make_country('JP', 'Japan', 'Kanto')
        city = CityMunicipality.objects.create(
            geoname_id=9600001, code='M1', name='Bihoro', province=province)

        response = self.client.get(reverse('location_barangays_api'), {
            'country': 'JP', 'province': 'P1', 'municipality': 'Bihoro',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['barangays'], [])
        self.assertEqual(response.json()['count'], 0)

    def test_region_is_present_on_every_province_in_the_tree(self):
        """The region select is derived from the tree, so it needs this field."""
        self._make_country('US', 'United States', 'California')
        self._make_country('BR', 'Brazil', 'Acre')
        for code in ('US', 'BR'):
            for province in build_location_hierarchy(code)['provinces']:
                self.assertTrue(province.get('region'),
                                '%s province %s has no region' % (code, province['name']))

    # ---- the rule the JS branches on ---------------------------

    def test_cascade_script_gates_barangay_on_the_philippines(self):
        """Guard: no JS runner, so assert the branch itself is still present."""
        script = (self.PROJECT_ROOT / 'static' / 'js' / 'location-cascade.js').read_text(
            encoding='utf-8')
        self.assertIn("=== 'PH'", script)
        self.assertIn('function usesBarangays()', script)
        # The group must be hidden rather than merely emptied.
        self.assertIn("bGroup.hidden = true", script)
        # And a country switch must not leave a stale value behind.
        self.assertIn('clearBarangay();', script)

    def test_picker_script_gates_barangay_on_the_philippines(self):
        script = (self.PROJECT_ROOT / 'static' / 'js' / 'location-picker.js').read_text(
            encoding='utf-8')
        self.assertIn("=== 'PH'", script)
        self.assertIn('function usesBarangays()', script)

    def test_landmark_forms_have_a_single_country_control(self):
        """Two inputs named ``country`` meant Django kept only the last one.

        The cascade's select owns Country now, so the visible control a user
        types into is the control that is actually submitted.
        """
        for name in ('landmarks/landmark_form.html', 'landmarks/spot_form.html'):
            source = (self.PROJECT_ROOT / 'templates' / name).read_text(encoding='utf-8')
            self.assertNotIn('name="country"', source, name)
            self.assertIn("country_name='country'", source, name)
            # Region is a real column on the landmark models, so the cascade's
            # select must submit it rather than being a pure filter.
            self.assertIn("region_name='region'", source, name)


@contextmanager
def seed_file(payload):
    """Write ``payload`` to a temp JSON file and yield its path."""
    handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
    try:
        json.dump(payload, handle, ensure_ascii=False)
        handle.close()
        yield handle.name
    finally:
        Path(handle.name).unlink(missing_ok=True)


def wipe_hierarchy():
    """Delete every reference row, children first so PROTECT never blocks it."""
    Barangay.objects.all().delete()
    CityMunicipality.objects.all().delete()
    Province.objects.all().delete()
    Region.objects.all().delete()
    Country.objects.all().delete()
