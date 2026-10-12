"""Geographic reference data sourced from GeoNames.

The hierarchy mirrors the administrative structure worldwide:

    Country -> Region -> Province -> City/Municipality -> Barangay

``Country`` is ``ADM0``, ``Region`` is ``ADM1``, ``Province`` is ``ADM2`` and
``CityMunicipality`` is ``ADM3``. Not every country populates every level, so the
tree skips the ones that are empty for a given place (a city-state such as
Singapore has no ``ADM2``).

``Barangay`` is ``ADM4`` and is only loaded for the Philippines: worldwide there
are roughly 13 million ``ADM4`` rows, which is far more data than the picker can
use. Elsewhere the hierarchy stops at ``ADM3``.

Each level is keyed by its GeoNames identifier (``geoname_id``), which is the
canonical id used by the upstream dataset, and additionally carries the GeoNames
administrative code (``code``) where the dump provides a usable one. Display
names come straight from GeoNames, so this replaces the former PSGC tables with a
single internationally recognised source.

Administrative codes are only unique *within* their parent, never globally:
``01`` is a region code in many countries at once, so uniqueness is enforced per
parent rather than per column.

``Country`` is a real row rather than a hard-coded string so the root of the
hierarchy is data too, and the platform is no longer Philippines-only.

Load the data with::

    python manage.py sync_geonames
"""

from django.db import models

#: GeoNames feature code for a country (``PCLI`` = "independent political entity").
COUNTRY_FEATURE = 'PCLI'

#: GeoNames feature codes that make up the administrative spine. The ``H``/``D``
#: variants (ADM1H, ADM2H, ADM3H, ADMD, ...) are historical or countrywide
#: pseudo-units and are intentionally excluded.
REGION_FEATURE = 'ADM1'
PROVINCE_FEATURE = 'ADM2'
CITY_FEATURE = 'ADM3'

#: Settlement-level features that represent a barangay.
BARANGAY_FEATURES = ('ADM4', 'PPL', 'PPLX')


class GeoPlace(models.Model):
    """Columns shared by every GeoNames feature at every level."""

    geoname_id = models.BigIntegerField(
        unique=True, verbose_name="GeoNames ID",
        help_text="GeoNames identifier for this place.",
    )
    name = models.CharField(max_length=200, db_index=True)
    asciiname = models.CharField(
        max_length=200, blank=True, default='', verbose_name="ASCII name",
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
    )
    feature_code = models.CharField(max_length=8, blank=True, default='')

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class Country(GeoPlace):
    """Root of the hierarchy — a country (GeoNames ``PCLI``).

    ``code`` is the ISO 3166-1 alpha-2 code, which is also the ``country`` field
    in the GeoNames dump, so the two line up exactly.
    """

    code = models.CharField(
        max_length=2, unique=True, verbose_name="ISO 3166-1 alpha-2",
        help_text="Two-letter country code, e.g. PH.",
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'Country'
        verbose_name_plural = 'Countries'

    def __str__(self):
        return self.name


class Region(GeoPlace):
    """Second level — a first-order administrative division (GeoNames ``ADM1``).

    Called a "region" in the Philippines and a state/province/oblasto almost
    everywhere else, so the generic name is used throughout.
    """

    code = models.CharField(
        max_length=8, verbose_name="Region code",
        help_text="GeoNames admin1 code (e.g. 01, 40, NCR).",
    )
    country = models.ForeignKey(
        Country, on_delete=models.PROTECT, related_name='regions',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'Region'
        constraints = [
            # Admin1 codes are only unique within a country: "01" is a region in
            # many different countries, so the code cannot be unique on its own.
            models.UniqueConstraint(fields=['country', 'code'], name='unique_region_code_per_country'),
        ]

    def __str__(self):
        return self.name


class Province(GeoPlace):
    """Third level — a second-order division (GeoNames ``ADM2``)."""

    code = models.CharField(
        max_length=16, verbose_name="Province code",
        help_text="GeoNames admin2 code (e.g. H2).",
    )
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name='provinces')

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['region', 'code'], name='unique_province_code_per_region'),
        ]

    def __str__(self):
        return self.name


class CityMunicipality(GeoPlace):
    """Fourth level — a city or a municipality."""

    code = models.CharField(
        max_length=16, verbose_name="City/Municipality code",
        help_text="GeoNames admin3 code (e.g. 045647000).",
    )
    province = models.ForeignKey(
        Province, on_delete=models.PROTECT, related_name='municipalities',
    )

    class Meta:
        ordering = ['name']
        # Without these Django's naive pluralizer renders "City municipalitys".
        verbose_name = 'City/municipality'
        verbose_name_plural = 'Cities/municipalities'
        constraints = [
            models.UniqueConstraint(fields=['province', 'code'], name='unique_city_code_per_province'),
        ]

    def __str__(self):
        return self.name


class Barangay(GeoPlace):
    """Lowest level (fifth) — a barangay, a Philippine ``ADM4`` unit.

    Only loaded for the Philippines. GeoNames has no administrative code for
    most barangays in that dump, so the row is identified solely by its
    ``geoname_id``.
    """

    city_municipality = models.ForeignKey(
        CityMunicipality, on_delete=models.PROTECT, related_name='barangays',
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Barangays'

    def __str__(self):
        return self.name
