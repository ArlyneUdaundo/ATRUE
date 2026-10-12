"""Load the GeoNames seeds into the database.

    python manage.py sync_geonames

Every ``locations/data/geonames_*.json`` seed is loaded, or just the ones named
with ``--seed`` (repeatable). The seeds are complementary rather than
overlapping: ``geonames_world.json`` carries the administrative spine for every
country, while ``geonames_ph.json`` additionally carries the Philippine
settlement level (barangays) that the worldwide dump is not used for.

The command is idempotent: rows are upserted on ``geoname_id``, so re-running it
refreshes names and coordinates without duplicating anything. Because children
reference parents by ``geoname_id`` -- which is unique worldwide, unlike an admin
code such as ``01`` -- one set of lookups resolves parents across every country.
Nothing is deleted unless ``--prune`` is passed, which removes rows that are in
none of the loaded seeds.
"""

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from locations.models import Barangay, CityMunicipality, Country, Province, Region

DATA_DIR = Path(__file__).resolve().parents[2] / 'data'
SEED_GLOB = 'geonames_*.json'

BATCH_SIZE = 2000

#: Columns every level stores, from the ``GeoPlace`` abstract base.
BASE_FIELDS = ('geoname_id', 'name', 'asciiname', 'latitude', 'longitude', 'feature_code')

#: Seed section -> model, in parent-before-child order. ``parent`` is the model's
#: foreign-key field and ``link`` the seed field holding the parent's
#: ``geoname_id``; ``extra`` lists the fields beyond the shared base ones.
LEVELS = (
    ('countries', Country, None, None, ('code',)),
    ('regions', Region, 'country', 'country_geoname_id', ('code',)),
    ('provinces', Province, 'region', 'region_geoname_id', ('code',)),
    ('cities', CityMunicipality, 'province', 'province_geoname_id', ('code',)),
    ('barangays', Barangay, 'city_municipality', 'city_geoname_id', ()),
)

PARENT_MODEL = {
    'country': Country,
    'region': Region,
    'province': Province,
    'city_municipality': CityMunicipality,
}

#: How each level reads on the console.
LABELS = {
    'countries': 'countries',
    'regions': 'regions',
    'provinces': 'provinces',
    'cities': 'cities + municipalities',
    'barangays': 'barangays',
}


def _decimal(value):
    return Decimal(str(value)) if value is not None else None


def load_seeds(paths):
    """Read and merge every seed into one dict per level, keyed by geoname id.

    Seeds are merged rather than applied one after another so that a row present
    in two seeds (the Philippine spine appears in both) is written once. Where
    two seeds disagree about a row the later seed wins, and because parent links
    are geoname ids the disagreement can only ever be about names, coordinates
    or which parent a place sits under -- never about a collision.
    """
    merged = {section: {} for section, _, _, _, _ in LEVELS}
    seen = []

    for path in paths:
        with path.open(encoding='utf-8') as handle:
            seed = json.load(handle)
        missing = [s for s in merged if s not in seed]
        if missing:
            raise CommandError(
                f'Seed {path.name} is missing the section(s): {", ".join(missing)}')
        for section in merged:
            for item in seed[section]:
                merged[section][item['geoname_id']] = item
        seen.append(path.name)

    return merged, seen


class Command(BaseCommand):
    help = 'Load the GeoNames reference data into the database.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--seed', action='append', default=None, metavar='PATH',
            help='Seed JSON to load (repeatable). Defaults to every '
                 f'locations/data/{SEED_GLOB}.')
        parser.add_argument(
            '--prune', action='store_true',
            help='Delete rows that appear in none of the loaded seeds.')

    def _resolve_seeds(self, options):
        given = options['seed']
        if given is None:
            paths = sorted(DATA_DIR.glob(SEED_GLOB))
        elif isinstance(given, (list, tuple)):
            paths = [Path(value) for value in given]
        else:
            # ``call_command`` hands a scalar straight through when --seed is
            # given once (argparse would have wrapped it in a list).
            paths = [Path(given)]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            raise CommandError(f'Seed file(s) not found: {", ".join(missing)}')
        if not paths:
            raise CommandError(
                f'No seed files found. Expected locations/data/{SEED_GLOB} '
                f'(see locations/data/build_geonames_seed.py).')
        return paths

    @transaction.atomic
    def handle(self, *args, **options):
        paths = self._resolve_seeds(options)
        merged, names = load_seeds(paths)
        self.stdout.write('Loading: ' + ', '.join(names))

        stats, skipped = {}, {}
        for section, model, parent_key, link, extra in LEVELS:
            stats[section], skipped[section] = self._load_level(
                model, list(merged[section].values()), parent_key, link, extra)

        pruned = 0
        if options['prune']:
            pruned = self._prune(merged)

        # The location tree is lru_cached for the frontend feeds, so drop it.
        try:
            from atrue_core.context_processors import _location_tree_cached
            _location_tree_cached.cache_clear()
        except Exception as exc:
            self.stderr.write(self.style.WARNING(
                f'Could not clear the cached location tree: {exc}'))

        self.stdout.write(self.style.SUCCESS('GeoNames sync complete:'))
        for section, model, _, _, _ in LEVELS:
            self.stdout.write(f'    {LABELS[section]:<22}: {model.objects.count()}')
        self.stdout.write('    added this run          : ' + ', '.join(
            f'{stats[s]} {LABELS[s]}' for s, _, _, _, _ in LEVELS))
        if pruned:
            self.stdout.write(f'    pruned (not in a seed) : {pruned}')

        orphans = {k: v for k, v in skipped.items() if v}
        if orphans:
            self.stdout.write(self.style.WARNING(
                '    skipped (no parent row) : '
                + ', '.join(f'{v} {LABELS[k]}' for k, v in orphans.items())))

    def _load_level(self, model, items, parent_key, link, extra):
        """Insert one level, resolving each row's parent by ``geoname_id``.

        Parents are looked up from the database, which is safe at every level
        because the levels load in parent-before-child order and ``geoname_id`` is
        unique worldwide -- unlike an admin code such as ``01``, which names a
        different region in every country. A row whose parent is missing is
        skipped and counted rather than being written with a dangling reference.
        """
        if not items:
            return 0, 0

        parent_pks = {}
        if parent_key:
            parent_pks = dict(
                PARENT_MODEL[parent_key].objects.values_list('geoname_id', 'pk'))

        update_fields = ['name', 'asciiname', 'latitude', 'longitude', 'feature_code']
        update_fields += list(extra)
        if parent_key:
            update_fields.append(parent_key)

        rows, skipped = [], 0
        for item in items:
            row = {
                'geoname_id': item['geoname_id'],
                'name': item.get('name', ''),
                'asciiname': item.get('asciiname', ''),
                'latitude': _decimal(item.get('latitude')),
                'longitude': _decimal(item.get('longitude')),
                'feature_code': item.get('feature_code', ''),
            }
            for field in extra:
                row[field] = item.get(field, '')

            if parent_key:
                parent_pk = parent_pks.get(item.get(link))
                if parent_pk is None:
                    skipped += 1
                    continue
                row[parent_key + '_id'] = parent_pk

            rows.append(model(**row))

        before = model.objects.count()
        for start in range(0, len(rows), BATCH_SIZE):
            model.objects.bulk_create(
                rows[start:start + BATCH_SIZE],
                update_conflicts=True,
                update_fields=update_fields,
                unique_fields=['geoname_id'],
            )
        return model.objects.count() - before, skipped

    def _prune(self, merged):
        """Delete rows whose geoname_id appears in none of the loaded seeds."""
        removed = 0
        # Children first so the PROTECT constraints never block the prune.
        for section, model, _, _, _ in reversed(LEVELS):
            stale = model.objects.exclude(geoname_id__in=merged[section])
            removed += stale.count()
            stale.delete()
        return removed
