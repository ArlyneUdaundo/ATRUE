"""Build a locations/data/geonames_*.json seed from an official GeoNames dump.

Usage::

    python build_geonames_seed.py <dump.txt> [output.json] [--levels spine|full]
                                   [--country-info countryInfo.txt]

The input is a tab-separated GeoNames dump whose columns are::

    geonameid  name  asciiname  alternatenames  latitude  longitude
    feature class  feature code  country code  cc2
    admin1  admin2  admin3  admin4
    population  elevation  dem  timezone  modification date

Two dumps are supported:

``allCountries.txt``
    From https://download.geonames.org/export/dump/allCountries.zip. The default
    output is ``geonames_world.json`` and the default ``--levels spine`` keeps only
    the administrative spine, which is what makes a worldwide tree affordable:
    roughly 250 countries, 5k regions, 35k provinces and 350k cities.

``PH.txt`` (or any other single country)
    From https://download.geonames.org/export/dump/PH.zip. With
    ``--levels full`` the settlement-level features (``ADM4``, ``PPL``, ``PPLX``)
    are also kept as barangays, which is how the Philippine seed gets its ~41,000.

The administrative spine is ``PCLI`` countries, ``ADM1`` regions, ``ADM2``
provinces and ``ADM3`` cities/municipalities. Physical features (streams,
mountains, hotels, points of interest, ...) are dropped, as are the historical
``H``/``D`` variants such as ``ADM2H`` and ``ADM3H`` -- those are the reason the
dump also contains pseudo-codes such as ``NIR`` (the pre-2001 Negros Island
Region).

Worldwide output differs from a single-country build in two ways that matter
downstream:

* **Parent links are geoname ids, not admin codes.** An ``admin1`` code such as
  ``01`` means a different region in every country, so the flat sections link
  children to parents by ``*_geoname_id``. ``sync_geonames`` resolves those the
  same way, which is what makes a multi-country database safe.
* **Country display names come from ``countryInfo.txt``** where available,
  because GeoNames records a country under its formal constitutional name
  ("Kingdom of Denmark") while ``countryInfo.txt`` carries the name people
  recognise ("Denmark"). ``asciiname`` still comes from the dump, so the formal
  name is not lost.

A country code that appears on an ``ADM1`` row without a matching ``PCLI`` row is
synthesised rather than dropped, so no region is ever orphaned; a handful of
territories need this.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from locations.names import clean_name, normalize_place_name  # noqa: E402

# Column offsets in the GeoNames dump.
COL_ID = 0
COL_NAME = 1
COL_ASCII = 2
COL_LAT = 4
COL_LNG = 5
COL_FCODE = 7
COL_COUNTRY = 8
COL_A1 = 10
COL_A2 = 11
COL_A3 = 12

COUNTRY_FEATURE = 'PCLI'
REGION_FEATURE = 'ADM1'
PROVINCE_FEATURE = 'ADM2'
CITY_FEATURE = 'ADM3'
SETTLEMENT_FEATURES = ('ADM4', 'PPL', 'PPLX')

#: GeoNames records countries under their formal constitutional name, which
#: ``countryInfo.txt`` does not. The short name is what people recognise.
FORMAL_NAME_PREFIX = re.compile(
    r'^(?:Republic\s+of\s+the|Federation\s+of\s+the|State\s+of\s+the|Kingdom\s+of\s+the)\s+',
    re.IGNORECASE,
)

#: Widths the models declare. Rows that would not fit are reported rather than
#: silently truncated, so a surprise shows up in the build report.
MAX_CODE = {'country': 2, 'region': 8, 'province': 16, 'city': 16}
MAX_NAME = 200

WORLD_DUMP = 'allCountries.txt'
WORLD_OUTPUT = 'geonames_world.json'
COUNTRY_DUMP_URL = 'https://download.geonames.org/export/dump/allCountries.zip'
WORLD_DUMP_URL = 'https://download.geonames.org/export/dump/{}.zip'


def _coord(value):
    """Round a dump coordinate to the 7dp the models store; ``None`` when absent."""
    try:
        return round(float(value), 7)
    except (TypeError, ValueError):
        return None


def _place(row, feature):
    return {
        'geoname_id': int(row[COL_ID]),
        'name': clean_name(row[COL_NAME]),
        'asciiname': row[COL_ASCII].strip(),
        'latitude': _coord(row[COL_LAT]),
        'longitude': _coord(row[COL_LNG]),
        'feature_code': feature,
    }


def read_rows(path):
    """Yield the tab-separated rows of a GeoNames dump, skipping short lines."""
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            columns = line.rstrip('\n').split('\t')
            if len(columns) > COL_A3:
                yield columns


def read_country_info(path):
    """ISO alpha-2 -> country display name, from ``countryInfo.txt``.

    Returns ``{}`` when the file is absent so a per-country build still works
    with nothing but the dump. The geoname id is picked up too, which lets a
    country code that has no ``PCLI`` row still get a real id.
    """
    names = {}
    if not path or not os.path.exists(path):
        return names
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            if line.startswith('#'):
                continue
            columns = line.rstrip('\n').split('\t')
            if len(columns) < 5:
                continue
            code = columns[0].strip().upper()
            name = columns[4].strip()
            if len(code) != 2 or not name or code in names:
                continue
            entry = {'name': name}
            try:
                entry['geoname_id'] = int(columns[17])
            except (IndexError, TypeError, ValueError):
                pass
            names[code] = entry
    return names


def _synthetic_geoname_id(code):
    """A stable, unique, negative id for a country with no GeoNames row.

    Real GeoNames ids are positive, so a negative value can never collide with
    one and the id stays deterministic across rebuilds.
    """
    return -(ord(code[0]) * 256 + ord(code[1]) + 1)


def _collect(path, want_settlements):
    """One pass over the dump, gathering every row we might keep.

    Rows are filed under their *full* natural key -- the country code plus every
    admin code above them -- so nothing depends on the order the dump happens to
    be in, and two rows that mean the same place cannot end up in different
    countries. De-duplication by name happens here too, per parent, because
    several codes can name the same city.
    """
    countries = {}
    regions = {}
    provinces = {}
    cities = {}
    settlements = {}

    province_names = set()
    city_names = set()

    for row in read_rows(path):
        feature = row[COL_FCODE]
        if feature not in (COUNTRY_FEATURE, REGION_FEATURE, PROVINCE_FEATURE, CITY_FEATURE,
                           *SETTLEMENT_FEATURES):
            continue

        iso = row[COL_COUNTRY].strip().upper()
        a1 = row[COL_A1].strip()
        a2 = row[COL_A2].strip()
        a3 = row[COL_A3].strip()

        if feature == COUNTRY_FEATURE:
            if len(iso) != 2 or iso in countries:
                continue
            formal = clean_name(row[COL_NAME])
            countries[iso] = {
                'geoname_id': int(row[COL_ID]),
                'code': iso,
                'name': FORMAL_NAME_PREFIX.sub('', formal).strip() or formal,
                'asciiname': row[COL_ASCII].strip(),
                'latitude': _coord(row[COL_LAT]),
                'longitude': _coord(row[COL_LNG]),
                'feature_code': COUNTRY_FEATURE,
            }
            continue

        # Every remaining level hangs off an admin1, and a row without one has
        # no place in the tree.
        if not iso or not a1:
            continue

        if feature == REGION_FEATURE:
            key = (iso, a1)
            if key in regions:
                continue
            place = _place(row, feature)
            place['code'] = a1
            regions[key] = place
            continue

        if feature == PROVINCE_FEATURE:
            if not a2:
                continue
            key = (iso, a1, a2)
            if key in provinces:
                continue
            name_key = (iso, a1, normalize_place_name(row[COL_NAME]))
            if not name_key[2] or name_key in province_names:
                continue
            province_names.add(name_key)
            place = _place(row, feature)
            place['code'] = a2
            provinces[key] = place
            continue

        if feature == CITY_FEATURE:
            if not a2 or not a3:
                continue
            key = (iso, a1, a2, a3)
            if key in cities:
                continue
            name_key = (iso, a1, a2, normalize_place_name(row[COL_NAME]))
            if not name_key[3] or name_key in city_names:
                continue
            city_names.add(name_key)
            place = _place(row, feature)
            place['code'] = a3
            cities[key] = place
            continue

        if want_settlements and feature in SETTLEMENT_FEATURES and a3:
            key = (iso, a1, a2, a3, normalize_place_name(row[COL_NAME]))
            if not key[4] or key in settlements:
                continue
            place = _place(row, feature)
            settlements[key] = place

    return countries, regions, provinces, cities, settlements


def _resolve(countries, regions, provinces, cities, settlements, country_info,
             want_settlements):
    """Turn the collected rows into the five flat sections, children linking to
    parents by geoname id.

    Any row whose parent is missing is dropped rather than emitted, so the
    result is always self-consistent: ``sync_geonames`` never has to skip
    anything.
    """
    warnings = []
    orphans = {'regions': 0, 'provinces': 0, 'cities': 0, 'settlements': 0}

    # A country code on an ADM1 row with no PCLI row of its own still needs a
    # parent, so synthesise one. This happens for a few territories.
    for iso in sorted({key[0] for key in regions}):
        if iso in countries:
            continue
        known = country_info.get(iso) or {}
        countries[iso] = {
            'geoname_id': known.get('geoname_id') or _synthetic_geoname_id(iso),
            'code': iso,
            'name': known.get('name') or iso,
            'asciiname': '',
            'latitude': None,
            'longitude': None,
            'feature_code': COUNTRY_FEATURE,
        }
        warnings.append(f'synthesised country row for {iso!r} (no PCLI record)')

    # A country that ``countryInfo.txt`` lists but the dump never mentions still
    # belongs in a worldwide reference table. Small territories such as Turks
    # and Caicos, Gibraltar or the Cocos Islands have no ``PCLI`` row *and* no
    # ``ADM1`` row, so the loop above never sees them and an airport in one of
    # them cannot resolve a country name. They are added here from the same
    # authoritative ISO list, using the identical synthetic-id fallback.
    for iso in sorted(country_info):
        if iso in countries:
            continue
        known = country_info[iso]
        countries[iso] = {
            'geoname_id': known.get('geoname_id') or _synthetic_geoname_id(iso),
            'code': iso,
            'name': known.get('name') or iso,
            'asciiname': '',
            'latitude': None,
            'longitude': None,
            'feature_code': COUNTRY_FEATURE,
        }
        warnings.append(f'added country row for {iso!r} from countryInfo.txt (no dump record)')

    # countryInfo.txt is the better display name; prefer it, and fall back to
    # the dump's own short name.
    for iso, record in countries.items():
        known = country_info.get(iso)
        if known and known.get('name'):
            record['name'] = known['name']

    country_id = {iso: record['geoname_id'] for iso, record in countries.items()}

    out_regions = []
    region_id = {}
    for key in sorted(regions):
        record = regions[key]
        if key[0] not in country_id:
            orphans['regions'] += 1
            continue
        record['country_geoname_id'] = country_id[key[0]]
        out_regions.append(record)
        region_id[key[:2]] = record['geoname_id']

    out_provinces = []
    province_id = {}
    for key in sorted(provinces):
        record = provinces[key]
        parent = region_id.get(key[:2])
        if parent is None:
            orphans['provinces'] += 1
            continue
        record['region_geoname_id'] = parent
        out_provinces.append(record)
        province_id[key[:3]] = record['geoname_id']

    out_cities = []
    city_id = {}
    for key in sorted(cities):
        record = cities[key]
        parent = province_id.get(key[:3])
        if parent is None:
            orphans['cities'] += 1
            continue
        record['province_geoname_id'] = parent
        out_cities.append(record)
        city_id[key[:4]] = record['geoname_id']

    # A settlement row carries only an admin3 code, and GeoNames' own admin1/admin2
    # on those rows is often stale -- "Poblacion" under San Pedro carries the NCR's
    # admin1 and no admin2 at all. Matching on the full chain would drop those, so
    # the admin3 code within one country is the key instead. Where two provinces
    # in a country reused one admin3 code the match would be ambiguous, so that is
    # reported rather than guessed.
    city_id_by_a3 = {}
    ambiguous = set()
    for key, geoname_id in city_id.items():
        short = (key[0], key[3])
        if short in city_id_by_a3 and city_id_by_a3[short] != geoname_id:
            ambiguous.add(short)
        city_id_by_a3[short] = geoname_id
    for short in sorted(ambiguous):
        warnings.append(
            f'admin3 code {short[1]!r} is shared by two provinces in {short[0]!r}; '
            'some settlements may attach to the wrong city')

    out_settlements = []
    if want_settlements:
        city_name_by_id = {record['geoname_id']: record['name'] for record in out_cities}
        for key in sorted(settlements):
            parent = city_id_by_a3.get((key[0], key[3]))
            if parent is None:
                orphans['settlements'] += 1
                continue
            record = settlements[key]
            # A populated place repeating its own city's name is the city centre,
            # not a unit beneath it.
            if normalize_place_name(record['name']) == normalize_place_name(
                    city_name_by_id[parent]):
                continue
            record['city_geoname_id'] = parent
            out_settlements.append(record)

    # Report anything that would not fit the model columns rather than
    # truncating it silently.
    for label, width, rows, key in (
        ('region', MAX_CODE['region'], out_regions, 'code'),
        ('province', MAX_CODE['province'], out_provinces, 'code'),
        ('city', MAX_CODE['city'], out_cities, 'code'),
    ):
        for record in rows:
            if len(record[key]) > width:
                warnings.append(
                    f"{label} {record['name']!r} code {record[key]!r} exceeds {width} chars")
            if len(record['name']) > MAX_NAME:
                warnings.append(f"{label} {record['name'][:40]!r}... name exceeds {MAX_NAME} chars")

    return {
        'countries': [countries[iso] for iso in sorted(countries)],
        'regions': out_regions,
        'provinces': out_provinces,
        'cities': out_cities,
        'barangays': out_settlements,
    }, warnings, orphans


def build(src_path, levels='spine', country_info_path=None):
    """Build a seed dict from ``src_path``."""
    want_settlements = levels == 'full'
    country_info = read_country_info(country_info_path)
    collected = _collect(src_path, want_settlements)
    sections, warnings, orphans = _resolve(*collected, country_info, want_settlements)

    base = os.path.basename(src_path)
    is_world = base.lower() == WORLD_DUMP.lower()
    if is_world:
        source = f'GeoNames worldwide dump ({COUNTRY_DUMP_URL})'
        description = 'Worldwide geographic reference data from GeoNames.'
    else:
        code = base[:-4] if base.lower().endswith('.txt') else base
        source = f'GeoNames country dump ({WORLD_DUMP_URL.format(code)})'
        description = f'{code} geographic reference data from GeoNames.'

    levels_used = ['country', 'region', 'province', 'city/municipality']
    if want_settlements:
        levels_used.append('barangay')

    seed = {
        'meta': {
            'source': source,
            'description': description,
            'levels': levels_used,
            'identifier': 'geoname_id',
            'scope': 'world' if is_world else code,
        },
    }
    seed.update(sections)
    return seed, warnings, orphans


def _default_output(src_path):
    base = os.path.basename(src_path)
    code = base[:-4] if base.lower().endswith('.txt') else base
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        WORLD_OUTPUT if code.lower() == 'allcountries' else f'geonames_{code.lower()}.json',
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Build a locations seed from a GeoNames dump.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'examples:\n'
            '  python build_geonames_seed.py allCountries.txt\n'
            '  python build_geonames_seed.py PH.txt --levels full '
            '--country-info countryInfo.txt\n'
        ),
    )
    parser.add_argument('source', help='GeoNames dump, e.g. allCountries.txt or PH.txt')
    parser.add_argument('output', nargs='?', help='output JSON (default: derived from the source)')
    parser.add_argument('--levels', choices=('spine', 'full'), default='spine',
                        help='"spine" keeps the administrative levels only; '
                             '"full" also keeps settlement-level features as barangays')
    parser.add_argument('--country-info', default=None,
                        help='countryInfo.txt, used for friendlier country names')
    options = parser.parse_args(argv)

    src_path = options.source
    if not os.path.exists(src_path):
        print(f'Source dump not found: {src_path}')
        return 1
    out_path = options.output or _default_output(src_path)

    seed, warnings, orphans = build(src_path, options.levels, options.country_info)

    with open(out_path, 'w', encoding='utf-8') as handle:
        json.dump(seed, handle, ensure_ascii=False, separators=(',', ':'))

    print(f'source   : {src_path}')
    print(f'levels   : {options.levels}')
    print(f'countries: {len(seed["countries"])}')
    print(f'regions  : {len(seed["regions"])}')
    print(f'provinces: {len(seed["provinces"])}')
    print(f'cities   : {len(seed["cities"])}')
    print(f'barangays: {len(seed["barangays"])}')
    dropped = {k: v for k, v in orphans.items() if v}
    if dropped:
        print(f'dropped (no parent in the spine): {dropped}')
    if warnings:
        print(f'warnings : {len(warnings)}')
        for line in warnings[:20]:
            print(f'    {line}')
        if len(warnings) > 20:
            print(f'    ... and {len(warnings) - 20} more')
    print(f'written  : {out_path} ({os.path.getsize(out_path)} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
