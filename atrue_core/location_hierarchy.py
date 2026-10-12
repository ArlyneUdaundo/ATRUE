"""ATRUE — shared hierarchical location data for the booking platform.

Provides a single source of truth for the Country -> Region -> Province ->
City/Municipality -> Barangay -> Listing hierarchy used by every booking category
(hotels, resorts, staycations, restaurants, landmarks, activities, tour packages).

GeoNames (``locations.models``) is the reference source, loaded by
``manage.py sync_geonames``. That data is **worldwide**: every country, region,
province and city/municipality GeoNames knows about. A tree of that size is tens
of megabytes of JSON, so the tree this module builds is scoped to a single
country — the one named by ``settings.LOCATION_PRIMARY_COUNTRY`` unless a caller
asks for another. The country itself is a ``Country`` row rather than a
hard-coded string, and ``/locations/api/?country=XX`` serves any other one on
demand.

Within that country the tree is merged with the locations actually present in the
database, so a value GeoNames spells differently is still offered, and complete
barangay lists are attached for the municipalities that are in use — keeping the
tree small enough to inline into every page. Listing rows carry no country
(Landmark aside), so that merge only applies to the platform's own country; a
tree built for any other country is pure GeoNames.

The picker steps Country -> Province -> City/Municipality -> Barangay. The region
is carried on each province as ``region`` so it can label or group entries, but it
is not a level the user has to step through.

``PROVINCE_MUNICIPALITIES`` remains only as a fallback for when the GeoNames
tables are still empty; it is not merged on top of the GeoNames data.

Matching is tolerant of the messy free-text values used in the database:
``normalize()`` lower-cases and drops "City" suffixes, whitespace, punctuation
and accents so "Davao City" still matches "Davao" and "Peñablanca" still
matches "Penablanca".
"""

import re
import unicodedata

from django.conf import settings

#: Fallback country name, used only when the ``Country`` table is empty (i.e.
#: before ``sync_geonames`` has run). Once loaded, the name comes from the table.
COUNTRY_NAME = "Philippines"

#: The country whose GeoNames quirks the tree knows how to smooth over. The
#: worldwide data needs no such handling; this is the platform's home country.
PHILIPPINES_CODE = "PH"

# ---------------------------------------------------------------------------
# Reference data (Philippines). Only provinces referenced on the platform
# (current data + popular destinations + the spec examples) are listed here;
# the merge step adds every location found in the database.
# ---------------------------------------------------------------------------

# Special destinations that do not map 1:1 onto a municipality name but are
# favourites in the platform's suggestions (Boracay = Malay, Aklan, etc.).
PLACE_ALIASES = {
    "Boracay": {"province": "Aklan", "municipality": "Malay"},
    "Boracay Island": {"province": "Aklan", "municipality": "Malay"},
    "Palaui Island": {"province": "Cagayan", "municipality": "Santa Ana"},
    "Palaui": {"province": "Cagayan", "municipality": "Santa Ana"},
    "Siargao": {"province": "Surigao del Norte", "municipality": "Del Carmen"},
    "Siargao Island": {"province": "Surigao del Norte", "municipality": "Del Carmen"},
    "Davao": {"province": "Davao del Sur"},
    "Mactan": {"province": "Cebu", "municipality": "Lapu-Lapu"},
    "Batanes": {"province": "Batanes"},
}

POPULAR_PROVINCES = [
    "Cagayan", "Cebu", "Bohol", "Pangasinan", "Ilocos Norte", "Ilocos Sur",
    "Palawan", "Davao del Sur", "Metro Manila", "Aklan", "Surigao del Norte",
]

PROVINCE_MUNICIPALITIES = {
    "Cagayan": [
        "Abulug", "Alcala", "Allacapan", "Amulung", "Aparri", "Baggao",
        "Ballesteros", "Buguey", "Calayan", "Camalaniugan", "Claveria",
        "Enrile", "Gattaran", "Gonzaga", "Iguig", "Lal-lo", "Lasam",
        "Pamplona", "Peñablanca", "Piat", "Rizal", "Sanchez-Mira",
        "Santa Ana", "Santa Praxedes", "Santa Teresita", "Santo Niño",
        "Solana", "Tuao", "Tuguegarao City",
    ],
    "Cebu": [
        "Alcantara", "Alcoy", "Alegria", "Aloguinsan", "Argao", "Asturias",
        "Badian", "Balamban", "Bantayan", "Barili", "Bogo", "Boljoon",
        "Borbon", "Carcar", "Carmen", "Catmon", "Cebu City", "Compostela",
        "Consolacion", "Cordova", "Daanbantayan", "Dalaguete", "Dumanjug",
        "Ginatilan", "Lapu-Lapu", "Liloan", "Madridejos", "Malabuyoc",
        "Medellin", "Minglanilla", "Moalboal", "Mandaue", "Naga",
        "Oslob", "Pilar", "Pinamungajan", "Poro", "Ronda", "Samboan",
        "San Fernando", "San Francisco", "San Remigio", "Santa Fe",
        "Santander", "Sibonga", "Sogod", "Tabogon", "Tabuelan", "Talisay",
        "Toledo", "Tuburan", "Tudela",
    ],
    "Bohol": [
        "Alburquerque", "Alicia", "Anda", "Antequera", "Baclayon",
        "Balilihan", "Batuan", "Bien Unido", "Bilar", "Buenavista",
        "Calape", "Candijay", "Carmen", "Catigbian", "Clarin", "Corella",
        "Cortes", "Dagohoy", "Danao", "Dauis", "Dimiao", "Duero",
        "Garcia Hernandez", "Getafe", "Guindulman", "Inabanga", "Jagna",
        "Lila", "Loboc", "Loon", "Mabini", "Maribojoc", "Panglao",
        "Pilar", "Sagbayan", "San Isidro", "San Miguel", "Sevilla",
        "Sierra Bullones", "Sikatuna", "Tagbilaran City", "Talibon",
        "Trinidad", "Tubigon", "Ubay", "Valencia",
    ],
    "Pangasinan": [
        "Alaminos", "Aguilar", "Alcala", "Anda", "Asingan", "Balungao",
        "Bani", "Basista", "Bautista", "Bayambang", "Binalonan",
        "Binmaley", "Bolinao", "Bugallon", "Burgos", "Calasiao",
        "Dagupan", "Dasol", "Infanta", "Labrador", "Laoac", "Lingayen",
        "Mabini", "Malasiqui", "Manaoag", "Mangaldan", "Mangatarem",
        "Mapandan", "Natividad", "Pozorrubio", "Rosales", "San Carlos",
        "San Fabian", "San Jacinto", "San Manuel", "San Nicolas",
        "San Quintin", "Santa Barbara", "Santa Maria", "Santo Tomas",
        "Sison", "Sual", "Tayug", "Umingan", "Urbiztondo", "Urdaneta",
        "Villasis",
    ],
    "Ilocos Norte": [
        "Adams", "Bacarra", "Badoc", "Bangui", "Banna", "Batac", "Burgos",
        "Carasi", "Currimao", "Dingras", "Dumalneg", "Laoag", "Marcos",
        "Nueva Era", "Pagudpud", "Paoay", "Pasuquin", "Piddig", "Pinili",
        "San Nicolas", "Sarrat", "Solsona", "Vintar",
    ],
    "Ilocos Sur": [
        "Alilem", "Banayoyo", "Bantay", "Burgos", "Cabugao", "Candon",
        "Caoayan", "Cervantes", "Galimuyod", "Gregorio del Pilar",
        "Lidlidda", "Magsingal", "Nagbukel", "Narvacan", "Quirino",
        "Salcedo", "San Emilio", "San Esteban", "San Ildefonso", "San Juan",
        "San Vicente", "Santa", "Santa Catalina", "Santa Cruz",
        "Santa Lucia", "Santa Maria", "Santiago", "Santo Domingo", "Sigay",
        "Sinait", "Sugpon", "Suyo", "Tagudin", "Vigan",
    ],
    "Palawan": [
        "Aborlan", "Agutaya", "Araceli", "Balabac", "Bataraza",
        "Brooke's Point", "Busuanga", "Cagayancillo", "Coron", "Culion",
        "Cuyo", "Dumaran", "El Nido", "Kalayaan", "Linapacan", "Magsaysay",
        "Narra", "Puerto Princesa", "Quezon", "Rizal", "Roxas",
        "San Vicente", "Sofronio Española", "Taytay",
    ],
    "Benguet": [
        "Atok", "Bakun", "Bokod", "Buguias", "Itogon", "Kabayan",
        "Kapangan", "Kibungan", "La Trinidad", "Mankayan", "Sablan",
        "Tuba", "Tublay", "Baguio",
    ],
    "Iloilo": [
        "Ajuy", "Alimodian", "Anilao", "Badiangan", "Balasan", "Banate",
        "Barotac Nuevo", "Barotac Viejo", "Batad", "Bingawan", "Cabatuan",
        "Calinog", "Carles", "Concepcion", "Dingle", "Dueñas", "Dumangas",
        "Estancia", "Guimbal", "Igbaras", "Iloilo City", "Janiuay",
        "Lambunao", "Leganes", "Lemery", "Leon", "Maasin", "Miagao",
        "Mina", "New Lucena", "Oton", "Passi", "Pavia", "Pototan",
        "San Dionisio", "San Enrique", "San Joaquin", "San Miguel",
        "San Rafael", "Santa Barbara", "Sara", "Tigbauan", "Tubungan",
        "Zarraga",
    ],
    "Davao del Sur": [
        "Bansalan", "Digos", "Hagonoy", "Kiblawan", "Magsaysay",
        "Malalag", "Matanao", "Padada", "Santa Cruz", "Sulop", "Davao City",
    ],
    "Davao del Norte": [
        "Asuncion", "Braulio E. Dujali", "Carmen", "Kapalong",
        "New Corella", "Panabo", "San Isidro", "Santo Tomas", "Tagum",
        "Samal",
    ],
    "Metro Manila": [
        "Caloocan", "Las Piñas", "Makati", "Malabon", "Mandaluyong",
        "Manila", "Marikina", "Muntinlupa", "Navotas", "Parañaque",
        "Pasay", "Pasig", "Pateros", "Quezon City", "San Juan", "Taguig",
        "Valenzuela",
    ],
    "Batanes": ["Basco", "Itbayat", "Ivana", "Mahatao", "Sabtang", "Uyugan"],
    "La Union": [
        "Agoo", "Aringay", "Bacnotan", "Bagulin", "Balaoan", "Bangar",
        "Bauang", "Burgos", "Caba", "Luna", "Naguilian", "Pugo",
        "Rosario", "San Fernando", "San Gabriel", "San Juan", "Santo Tomas",
        "Santol", "Sudipen", "Tubao",
    ],
    "Nueva Vizcaya": [
        "Alfonso Castañeda", "Ambaguio", "Aritao", "Bagabag", "Bambang",
        "Bayombong", "Diadi", "Dupax del Norte", "Dupax del Sur", "Kasibu",
        "Kayapa", "Quezon", "Santa Fe", "Solano", "Villaverde",
    ],
    "Isabela": [
        "Alicia", "Angadanan", "Aurora", "Benito Soliven", "Burgos",
        "Cabagan", "Cabatuan", "Cauayan", "Cordon", "Delfin Albano",
        "Dinapigue", "Divilacan", "Echague", "Gamu", "Ilagan", "Jones",
        "Luna", "Maconacon", "Mallig", "Naguilian", "Palanan", "Quezon",
        "Quirino", "Ramon", "Reina Mercedes", "Roxas", "San Agustin",
        "San Guillermo", "San Isidro", "San Manuel", "San Mariano",
        "San Mateo", "San Pablo", "Santa Maria", "Santiago", "Santo Tomas",
        "Tumauini",
    ],
    "Aklan": [
        "Altavas", "Balete", "Banga", "Batan", "Buruanga", "Ibajay",
        "Kalibo", "Lezo", "Libacao", "Madalag", "Makato", "Malay",
        "Malinao", "Nabas", "New Washington", "Numancia", "Tangalan",
    ],
    "Surigao del Norte": [
        "Alegria", "Bacuag", "Burgos", "Claver", "Dapa", "Del Carmen",
        "General Luna", "Gigaquit", "Mainit", "Malimono", "Pilar", "Placer",
        "San Benito", "San Francisco", "San Isidro", "Santa Monica",
        "Sison", "Socorro", "Tagana-an", "Surigao City",
    ],
    "Rizal": [
        "Angono", "Antipolo", "Baras", "Binangonan", "Cainta", "Cardona",
        "Jalajala", "Morong", "Pililla", "Rodriguez", "San Mateo", "Tanay",
        "Taytay", "Teresa",
    ],
    "Bulacan": [
        "Angat", "Balagtas", "Baliuag", "Bocaue", "Bulakan", "Bustos",
        "Calumpit", "Doña Remedios Trinidad", "Guiguinto", "Hagonoy",
        "Malolos", "Marilao", "Meycauayan", "Norzagaray", "Obando",
        "Pandi", "Paombong", "Plaridel", "Pulilan", "San Ildefonso",
        "San Jose del Monte", "San Miguel", "San Rafael", "Santa Maria",
    ],
    "Cavite": [
        "Alfonso", "Amadeo", "Bacoor", "Carmona", "Cavite City",
        "Dasmariñas", "General Emilio Aguinaldo", "General Mariano Alvarez",
        "General Trias", "Imus", "Indang", "Kawit", "Magallanes",
        "Maragondon", "Mendez", "Naic", "Noveleta", "Rosario", "Silang",
        "Tagaytay", "Tanza", "Ternate", "Trece Martires City",
    ],
    "Laguna": [
        "Alaminos", "Bay", "Biñan", "Cabuyao", "Calamba", "Calauan",
        "Cavinti", "Famy", "Kalayaan", "Liliw", "Los Baños", "Luisiana",
        "Lumban", "Mabitac", "Magdalena", "Majayjay", "Nagcarlan", "Paete",
        "Pagsanjan", "Pakil", "Pangil", "Pila", "Rizal", "San Pablo",
        "San Pedro", "Santa Cruz", "Santa Maria", "Santa Rosa", "Siniloan",
        "Victoria",
    ],
    "Batangas": [
        "Agoncillo", "Alitagtag", "Balayan", "Balete", "Batangas City",
        "Bauan", "Calaca", "Calatagan", "Cuenca", "Ibaan", "Laurel",
        "Lemery", "Lian", "Lipa", "Lobo", "Mabini", "Malvar",
        "Mataasnakahoy", "Nasugbu", "Padre Garcia", "Rosario", "San Jose",
        "San Juan", "San Luis", "San Nicolas", "San Pascual",
        "Santa Teresita", "Santo Tomas", "Taal", "Talisay", "Tanauan",
        "Taysan", "Tingloy", "Tuy",
    ],
    "Pampanga": [
        "Angeles", "Apalit", "Arayat", "Bacolor", "Candaba",
        "Floridablanca", "Guagua", "Lubao", "Macabebe", "Magalang",
        "Mabalacat", "Masantol", "Mexico", "Minalin", "Porac",
        "San Fernando", "San Luis", "San Simon", "Santa Ana", "Santa Rita",
        "Santo Tomas", "Sasmuan",
    ],
    "Nueva Ecija": [
        "Aliaga", "Bongabon", "Cabiao", "Cabanatuan", "Carranglan",
        "Cuyapo", "Gabaldon", "General Mamerto Natividad", "General Tinio",
        "Guimba", "Jaen", "Laur", "Licab", "Llanera", "Lupao", "Muñoz",
        "Nampicuan", "Palayan", "Pantabangan", "Peñaranda", "Quezon",
        "Rizal", "San Antonio", "San Isidro", "San Jose City",
        "San Leonardo", "Santa Rosa", "Santo Domingo", "Talavera",
        "Talugtug", "Zaragoza",
    ],
    "Quezon": [
        "Agdangan", "Alabat", "Atimonan", "Buenavista", "Burdeos",
        "Calauag", "Candelaria", "Catanauan", "Dolores", "General Luna",
        "General Nakar", "Guinayangan", "Gumaca", "Infanta", "Jomalig",
        "Lopez", "Lucban", "Lucena", "Macalelon", "Mauban", "Mulanay",
        "Padre Burgos", "Pagbilao", "Panukulan", "Patnanungan", "Perez",
        "Pitogo", "Plaridel", "Polillo", "Quezon", "Real", "Sampaloc",
        "San Andres", "San Antonio", "San Francisco", "San Narciso",
        "Sariaya", "Tagkawayan", "Tayabas", "Tiaong", "Unisan",
    ],
    "Tarlac": [
        "Anao", "Bamban", "Camiling", "Capas", "Concepcion", "Gerona",
        "La Paz", "Mayantoc", "Moncada", "Paniqui", "Pura", "Ramos",
        "San Clemente", "San Jose", "San Manuel", "Santa Ignacia",
        "Tarlac City", "Victoria",
    ],
    "Zambales": [
        "Botolan", "Cabangan", "Candelaria", "Castillejos", "Iba",
        "Masinloc", "Palauig", "San Antonio", "San Felipe", "San Marcelino",
        "San Narciso", "Santa Cruz", "Subic", "Olongapo City",
    ],
    "Occidental Mindoro": [
        "Abra de Ilog", "Calintaan", "Looc", "Lubang", "Magsaysay",
        "Mamburao", "Paluan", "Rizal", "Sablayan", "San Jose",
        "Santa Cruz",
    ],
    "Oriental Mindoro": [
        "Baco", "Bansud", "Bongabong", "Bulalacao", "Calapan", "Gloria",
        "Mansalay", "Naujan", "Pinamalayan", "Pola", "Puerto Galera",
        "Roxas", "San Teodoro", "Socorro", "Victoria",
    ],
    "Camarines Sur": [
        "Baao", "Balatan", "Bato", "Bombon", "Buhi", "Bula", "Cabusao",
        "Calabanga", "Camaligan", "Canaman", "Caramoan", "Del Gallego",
        "Gainza", "Garchitorena", "Goa", "Iriga", "Lagonoy", "Libmanan",
        "Lupi", "Magarao", "Milaor", "Minalabac", "Nabua", "Naga",
        "Ocampo", "Pamplona", "Pasacao", "Pili", "Presentacion",
        "Ragay", "Sagñay", "San Fernando", "San Jose", "Sipocot",
        "Siruma", "Tigaon", "Tinambac",
    ],
    "Albay": [
        "Bacacay", "Camalig", "Daraga", "Guinobatan", "Jovellar",
        "Legazpi", "Libon", "Ligao", "Malilipot", "Malinao", "Manito",
        "Oas", "Pio Duran", "Polangui", "Rapu-Rapu", "Santo Domingo",
        "Tabaco", "Tiwi",
    ],
    "Negros Occidental": [
        "Bacolod", "Bago", "Binalbagan", "Cadiz", "Calatrava", "Candoni",
        "Cauayan", "Enrique B. Magalona", "Escalante", "Himamaylan",
        "Hinigaran", "Himogon", "Ilog", "Isabela", "Kabankalan", "La Carlota",
        "La Castellana", "Manapla", "Moises Padilla", "Murcia", "Pontevedra",
        "Pulupandan", "Salvador Benedicto", "San Carlos", "San Enrique",
        "Sagay", "Silay", "Sipalay", "Talisay", "Toboso", "Valladolid",
        "Victorias", "Victorias City",
    ],
}


def _strip_accents(value):
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(value):
    """Canonical, forgiving form of a location name for matching."""
    if not value:
        return ""
    text = _strip_accents(str(value)).lower()
    text = text.replace("city", " ").replace("municipality", " ")
    text = text.replace("mun.", " ").replace(".", " ").replace("'", " ")
    text = text.replace("-", " ").replace("  ", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return "".join(ch for ch in text if ch.isalnum() or ch == " ")


def _dedupe(values):
    seen = []
    keys = set()
    for value in values:
        if not value:
            continue
        value = str(value).strip()
        key = normalize(value)
        if not key or key in keys:
            continue
        keys.add(key)
        seen.append(value)
    return seen


# ---------------------------------------------------------------------------
# Database sources — every category contributes its structured location value.
# ---------------------------------------------------------------------------

def _db_location_rows():
    """Yield dicts of structured province/municipality/barangay found in listings.

    Rows are scoped to the platform's own country: since the tree is only
    merged for that country, a foreign listing must never inject its
    provinces into it (e.g. "Leyte, Florida"). Blank rows are legacy data and
    are assumed to be home-country.
    """
    from activities.models import Activity
    from hotels.models import Hotel
    from landmarks.models import Landmark
    from resorts.models import Resort
    from restaurants.models import Restaurant
    from staycations.models import Staycation
    from tour_package.models import TourPackage

    def ok(country_value):
        if not (country_value or '').strip():
            return True
        row = _country_row(country_value)
        if row is None:
            return False
        return row.code == primary_country_code()

    for cls, p, m, b, c in [
        (Hotel, "province", "municipality", "barangay", "country"),
        (Resort, "province", "municipality", "barangay", "country"),
        (Staycation, "province", "municipality", "barangay", "country"),
        (Landmark, "province", "municipality", "barangay", "country"),
    ]:
        for row in cls.objects.values(p, m, b, c).distinct():
            if row.get(p) or row.get(m) or row.get(b):
                if not ok(row.get(c)):
                    continue
                yield {"province": row.get(p), "municipality": row.get(m), "barangay": row.get(b)}

    for row in Activity.objects.values(
        "location_province", "location_municipality", "location_barangay", "location_country"
    ).distinct():
        if row.get("location_province") or row.get("location_municipality") or row.get("location_barangay"):
            if not ok(row.get("location_country")):
                continue
            yield {
                "province": row.get("location_province"),
                "municipality": row.get("location_municipality"),
                "barangay": row.get("location_barangay"),
            }

    for row in TourPackage.objects.values(
        "destination_province", "destination_city", "destination_country"
    ).distinct():
        if row.get("destination_province") or row.get("destination_city"):
            if not ok(row.get("destination_country")):
                continue
            yield {
                "province": row.get("destination_province"),
                "municipality": row.get("destination_city"),
                "barangay": None,
            }


def _scan_restaurants(base):
    """Best-effort: restaurants store a single free-text ``location`` string.

    We pick out any known province and, riding on it, known municipalities so
    "Baggao, Cagayan" associates Baggao under Cagayan even though the model
    has no structured location fields. ``base`` is the province -> municipality
    map currently being built, so this follows whichever reference source is
    in play.
    """
    from restaurants.models import Restaurant

    province_keys = [(p, normalize(p)) for p in base if p]
    for value, country in Restaurant.objects.values_list("location", "country"):
        if not value:
            continue
        if (country or '').strip():
            row = _country_row(country)
            if row is None or row.code != primary_country_code():
                continue
        text = str(value)
        low = normalize(text)
        province = next((p for p, k in province_keys if k and k in low), None)
        if not province:
            continue
        municipality = next(
            (m for m in base[province]
             if m and normalize(m) and normalize(m) in low),
            None,
        )
        if municipality:
            yield {"province": province, "municipality": municipality, "barangay": None}


# ---------------------------------------------------------------------------
# GeoNames reference data
# ---------------------------------------------------------------------------

#: GeoNames codes the National Capital Region's own admin1, whose admin2 rows
#: are legacy districts ("Capital District", "Eastern Manila District", ...) that
#: mean nothing to users. The listings already store "Metro Manila", so the NCR
#: cities are presented as one province under that name instead.
NCR_REGION_CODE = 'NCR'
METRO_MANILA = 'Metro Manila'


def primary_country_code():
    """ISO code of the country the platform is built around, from settings."""
    return (getattr(settings, 'LOCATION_PRIMARY_COUNTRY', '') or '').strip().upper()


def _country_row(country=None):
    """The ``Country`` row for ``country``, or the platform's own country.

    ``country`` is an ISO code or a name and is matched leniently, so a value
    straight off a query string works. Passing nothing (or an empty value) means
    "the platform's own country", from ``LOCATION_PRIMARY_COUNTRY``. Returns
    ``None`` when there is no such row, which is the state before
    ``sync_geonames`` has run and the signal to fall back to the static map.
    """
    from locations.models import Country

    wanted = (country or '').strip() or primary_country_code()
    if wanted:
        row = Country.objects.filter(code__iexact=wanted).first()
        if row is not None:
            return row
        row = Country.objects.filter(name__iexact=wanted).first()
        if row is not None:
            return row
    return None


def country_dict(country=None):
    """A country as ``{'name', 'code', 'geoname_id'}``, or ``None`` if unknown.

    Used by the API layer, which needs to tell "no such country" apart from "the
    platform's country".
    """
    row = _country_row(country)
    if row is None:
        return None
    return {"name": row.name, "code": row.code, "geoname_id": row.geoname_id}


def primary_country():
    """The country the tree is rooted at.

    Returns a dict with ``name``, ``code`` and ``geoname_id``. Falls back to the
    ``COUNTRY_NAME`` constant (and an empty code) when the tables have not been
    populated yet, so the tree still renders before ``sync_geonames`` has run.
    """
    country = country_dict()
    if country is None:
        return {"name": COUNTRY_NAME, "code": "", "geoname_id": ""}
    return country


def is_primary_country(code):
    """True when ``code`` is the country listings, overrides and validation apply to.

    The listing tables carry province/municipality/barangay free text with no
    country, and the ``PLACE_ALIASES``/``POPULAR_PROVINCES``/NCR-collapse
    overrides are all Philippine, so those only ever apply to this country.
    """
    if not code:
        return False
    wanted = primary_country_code()
    if wanted:
        return code.upper() == wanted
    # No configured country: the tables hold one country's data, the Philippines.
    return code.upper() == PHILIPPINES_CODE


def _province_label(province_name, region_code, country_code):
    """The label a province is shown under in the tree.

    Identical to the stored name everywhere except the Philippine NCR, which is
    collapsed into a single "Metro Manila" province. The other countries in the
    worldwide data have no such quirk, so the collapse stays scoped to the
    Philippines.
    """
    if is_primary_country(country_code) and region_code == NCR_REGION_CODE:
        return METRO_MANILA
    return province_name


def _geonames_base(country_row):
    """Province -> municipality -> barangays skeleton from the GeoNames tables.

    Scoped to one country: the worldwide data is far too large to walk, and a
    tree is only ever useful for the country being browsed. Municipalities start
    with an empty barangay list; complete barangay lists are filled in later, and
    only for the municipalities listings actually use, which keeps the tree small
    enough to inline on every page.

    Returns ``(base, label_by_province, region_by_label, country_by_label)`` or
    ``(None, {}, {}, {})`` when the tables have not been populated yet (before
    ``manage.py sync_geonames`` has run). ``label_by_province`` maps each stored
    ``Province`` name to the label it is shown under in the tree, which differs
    only for the collapsed NCR; ``region_by_label`` maps each tree label to the
    name of the region it belongs to; ``country_by_label`` maps it to the
    country's ``{'name', 'code'}``, which is what lets the picker offer a
    country as its first step.
    """
    from django.db.models import Prefetch

    from locations.models import CityMunicipality, Province

    if country_row is None:
        return None, {}, {}, {}

    base = {}
    label_by_province = {}
    region_by_label = {}
    country_by_label = {}
    provinces = (
        Province.objects.filter(region__country=country_row)
        .select_related('region', 'region__country')
        .prefetch_related(Prefetch(
            'municipalities',
            queryset=CityMunicipality.objects.order_by('name'),
        ))
        .order_by('name')
    )
    for province in provinces:
        label = _province_label(province.name, province.region.code,
                                province.region.country.code)
        label_by_province[province.name] = label
        # The collapsed NCR districts all sit in one region, so first-one-wins
        # gives the right answer without a second pass.
        region_by_label.setdefault(label, province.region.name)
        country_by_label.setdefault(
            label, {'name': province.region.country.name, 'code': province.region.country.code},
        )
        bucket = base.setdefault(label, {})
        for municipality in province.municipalities.all():
            bucket.setdefault(municipality.name, [])
    return base, label_by_province, region_by_label, country_by_label


def _fill_geonames_barangays(base, label_by_province, used):
    """Give every municipality in ``used`` its full GeoNames barangay list.

    ``used`` holds ``(province, municipality)`` pairs that listings reference,
    where the province is the tree label. For the collapsed NCR that label
    ("Metro Manila") is not a stored ``Province`` name, so the label is expanded
    back to the district rows it covers before querying.

    Barangay names already collected from the listings are merged in first, so a
    previously-saved barangay that GeoNames does not carry is never dropped.
    """
    from locations.models import CityMunicipality

    if not used:
        return

    # Tree label -> the stored Province names it covers.
    names_by_label = {}
    for province_name, label in label_by_province.items():
        names_by_label.setdefault(label, set()).add(province_name)

    wanted = {(normalize(p), normalize(m)) for p, m in used}
    province_names = set()
    for label, _ in used:
        province_names |= names_by_label.get(label, {label})

    cities = (
        CityMunicipality.objects
        .filter(province__name__in=province_names,
                name__in={m for _, m in used})
        .select_related('province')
        .prefetch_related('barangays')
    )
    for city in cities:
        label = label_by_province.get(city.province.name, city.province.name)
        if (normalize(label), normalize(city.name)) not in wanted:
            continue
        bucket = base.get(label)
        if not bucket or city.name not in bucket:
            continue
        names = [b.name for b in city.barangays.all()]
        bucket[city.name] = _dedupe(list(bucket[city.name]) + names)


def stored_province_names(province_label, country=None):
    """The stored ``Province`` names that a tree label covers, within one country.

    For almost every province the label *is* the stored name. The collapsed NCR
    is the exception: the tree shows one "Metro Manila" province, but GeoNames
    stores four legacy districts under one region, so the label maps back to all
    four. Scoping to a country matters once the data is worldwide, because
    province names repeat across borders ("Victoria" is a city in many places).
    """
    from locations.models import Province

    label = (province_label or "").strip()
    if not label:
        return []

    row = _country_row(country)
    provinces = Province.objects.all()
    if row is not None:
        provinces = provinces.filter(region__country=row)

    if row is not None and is_primary_country(row.code) \
            and normalize(label) == normalize(METRO_MANILA):
        return list(
            provinces.filter(region__code=NCR_REGION_CODE)
            .order_by('name')
            .values_list('name', flat=True)
        )

    exact = list(
        provinces.filter(name__iexact=label)
        .order_by('name')
        .values_list('name', flat=True)
    )
    if exact:
        return exact

    # Fall back to a normalised comparison so a value typed by hand still hits.
    key = normalize(label)
    return [
        name for name in
        provinces.order_by('name').values_list('name', flat=True)
        if normalize(name) == key
    ]


def _listing_barangays(province_names, province_label, municipality_name):
    """Barangay names that only exist as listing free text for this municipality.

    GeoNames does not carry every barangay, and listings sometimes record a
    variant that was never imported. The hierarchy merges those into the pick
    list, so the lazy endpoint must do the same -- otherwise a name that is
    selectable on an inlined list would vanish when the same city is loaded on
    demand. Without this a saved value like "Bagbag (North EDSA)" would look
    unrecognised and drop an existing record into free text.
    """
    muni_key = normalize(municipality_name)
    prov_keys = {normalize(name) for name in province_names}
    prov_keys.add(normalize(province_label))
    # A listing may name an older province that GeoNames now folds into this one
    # ("Siargao" is part of "Surigao del Norte"), and the hierarchy resolves that
    # through PLACE_ALIASES. The lazy endpoint has to agree or a saved barangay
    # would disappear from its own city.
    for alias, target in PLACE_ALIASES.items():
        if normalize(target.get("province") or "") in prov_keys:
            prov_keys.add(normalize(alias))

    found = []
    for row in _db_location_rows():
        row_province = (row.get("province") or "").strip()
        row_muni = (row.get("municipality") or "").strip()
        row_brgy = (row.get("barangay") or "").strip()
        if not row_brgy or not row_muni:
            continue
        if normalize(row_muni) != muni_key:
            continue
        if row_province and normalize(row_province) not in prov_keys:
            continue
        found.append(row_brgy)
    return found


def municipality_barangays(province_label, municipality_name, country=None):
    """The full barangay list for one tree province/municipality pair.

    ``province_label`` and ``municipality_name`` are the values the tree shows,
    so "Metro Manila" resolves through the collapsed NCR districts. Both are
    matched leniently (case, accents, "City" suffix) because callers may be
    replaying a value typed by a user. ``country`` scopes the lookup, which
    matters now that the same municipality name can exist in several countries.

    The result is the same list the hierarchy would have inlined for that
    municipality: every GeoNames ``Barangay`` row plus any name that only exists
    in listing free text, deduplicated and sorted case-insensitively. An unknown
    province or municipality yields an empty list rather than an error, so a stale
    bookmarked URL degrades to free text instead of a 500.
    """
    from locations.models import CityMunicipality

    province_names = stored_province_names(province_label, country)
    if not province_names:
        return []

    name = (municipality_name or "").strip()
    if not name:
        return []

    cities = CityMunicipality.objects.filter(
        province__name__in=province_names
    ).prefetch_related('barangays')

    city = cities.filter(name__iexact=name).first()
    if city is None:
        key = normalize(name)
        city = next((c for c in cities if normalize(c.name) == key), None)

    names = []
    if city is not None:
        names.extend(barangay.name for barangay in city.barangays.all())
    # Listing-only names apply even when GeoNames has no matching row, because
    # the value may predate the GeoNames import.
    names.extend(_listing_barangays(province_names, province_label, name))

    return sorted(
        _dedupe(names),
        key=lambda value: (value.lower(), value),
    )


def _static_base():
    """Fallback skeleton from the hard-coded map, used only when GeoNames is empty."""
    return {province: {municipality: [] for municipality in municipalities}
            for province, municipalities in PROVINCE_MUNICIPALITIES.items()}


# ---------------------------------------------------------------------------
# Hierarchy builder
# ---------------------------------------------------------------------------

def _available_countries():
    """Every country GeoNames has a province for, with a province count.

    This is the picker's first step, so it has to be the whole world even though
    the tree itself is scoped to one country. One query, so it stays cheap
    against the worldwide tables.
    """
    from django.db.models import Count

    from locations.models import Country

    rows = (
        Country.objects
        .annotate(province_count=Count('regions__provinces', distinct=True))
        .order_by('name')
        .values('code', 'name', 'province_count')
    )
    return [
        {"code": row["code"], "name": row["name"], "count": row["province_count"]}
        for row in rows
    ]


def build_location_hierarchy(country=None):
    """Build the Country -> Province -> Municipality -> Barangay tree for one country.

    ``country`` is an ISO code or a name; it defaults to the platform's own
    country (``settings.LOCATION_PRIMARY_COUNTRY``). The worldwide GeoNames data
    is far too large to return in one payload, so a tree is always built for a
    single country and other countries are fetched on demand from
    ``/locations/api/?country=XX``.

    GeoNames is the reference source: every province and city/municipality in
    that country is offered, not just the ones a listing happens to use. That is
    merged with the locations actually present in the database so a value that
    GeoNames spells differently is still selectable, and complete barangay lists
    are attached for the municipalities that are in use. That merge only happens
    for the platform's own country, since listing rows carry no country of their
    own; a tree for any other country is pure GeoNames.

    The country is read from the ``Country`` table rather than hard-coded, and
    each province carries the name of the region it belongs to. The region stays
    out of the cascade itself (the picker steps country -> province ->
    municipality -> barangay) but is available to label or group provinces.

    ``countries`` lists every country available in the database, not just this
    one, so the picker can offer a country as its first step.
    """
    country_row = _country_row(country)
    base, label_by_province, region_by_label, country_by_label = _geonames_base(country_row)
    geo_backed = base is not None
    if not geo_backed:
        base = _static_base()

    if country_row is not None:
        country_info = {"name": country_row.name, "code": country_row.code}
        # Listing free text has no country of its own, so it is only merged into
        # the platform's own country. Doing otherwise would inject Philippine
        # locations into, say, a United States tree.
        merge_listings = is_primary_country(country_row.code)
    else:
        country_info = {"name": COUNTRY_NAME, "code": ""}
        merge_listings = True

    def resolve_province(name):
        if not name:
            return None
        key = normalize(name)
        for known in base:
            if normalize(known) == key:
                return known
        if merge_listings:
            for alias, target in PLACE_ALIASES.items():
                if normalize(alias) == key and target.get("province"):
                    return target["province"]
        return None

    def resolve_municipality(bucket, name, province):
        """Map free text onto a canonical municipality name in ``bucket``.

        Returns ``(name, known)``. ``known`` is False only when the value adds
        no city, i.e. it merely repeats the province ("Cebu" recorded as the
        municipality of province "Cebu"). A genuine city that happens to
        normalise to the province name -- "Cebu City" under "Cebu" -- is
        resolved against the bucket first and therefore kept.
        """
        key = normalize(name)
        if not key:
            return name, False
        for known in bucket:
            if known and normalize(known) == key:
                return known, True
        if key == normalize(province):
            return name, False
        return name, True

    used = set()
    if merge_listings:
        for row in _db_location_rows():
            province = resolve_province(row.get("province") or "")
            if not province:
                continue
            muni = (row.get("municipality") or "").strip()
            brgy = (row.get("barangay") or "").strip()
            bucket = base.setdefault(province, {})
            if not muni:
                continue
            muni, known = resolve_municipality(bucket, muni, province)
            if not known:
                continue
            brgys = bucket.setdefault(muni, [])
            if brgy and brgy not in brgys:
                brgys.append(brgy)
            used.add((province, muni))

        for row in _scan_restaurants(base):
            province = resolve_province(row.get("province") or "")
            if province and row.get("municipality"):
                base.setdefault(province, {}).setdefault(row["municipality"], [])

    if geo_backed and merge_listings:
        _fill_geonames_barangays(base, label_by_province, used)

    provinces = []
    for prov, munis in base.items():
        muni_list = [
            {"name": m, "barangays": _dedupe(brgys)}
            for m, brgys in munis.items()
            if m != ""
        ]
        muni_list.sort(key=lambda x: normalize(x["name"]))
        entry = {"name": prov, "municipalities": muni_list}
        # Only GeoNames-backed provinces have a known region; ones merged in from
        # listing free text (or from the static fallback) may not.
        region_name = region_by_label.get(prov)
        if region_name:
            entry["region"] = region_name
        # The country is repeated on each province rather than nested, so the
        # payload stays flat and the picker can filter without walking a tree.
        country = country_by_label.get(prov)
        if country:
            entry["country"] = country["name"]
            entry["country_code"] = country["code"]
        provinces.append(entry)

    is_popular = lambda name: name in POPULAR_PROVINCES  # noqa: E731
    provinces.sort(key=lambda x: (not is_popular(x["name"]), normalize(x["name"])))

    names = {prov["name"] for prov in provinces}
    # Both the curated shortlist and the aliases are Philippine, so they are only
    # offered for the platform's own country.
    popular = [p for p in POPULAR_PROVINCES if p in names] if merge_listings else []

    aliases = {}
    if merge_listings:
        for name, target in PLACE_ALIASES.items():
            province = target.get("province")
            if province and province in names:
                entry = {"province": province}
                if target.get("municipality"):
                    entry["municipality"] = target["municipality"]
                aliases[name] = entry

    # Every country GeoNames has data for, so the picker can offer a country as
    # its first step and switch the whole tree. ``count`` is the number of
    # provinces available, letting the UI show the size of a choice without a
    # second lookup. Ordered by name, with the platform's own country first.
    countries = _available_countries()
    countries.sort(key=lambda c: (c["code"] != country_info["code"], c["name"].lower()))

    return {
        # ``country`` stays a plain string: static/js/location-picker.js uses it
        # directly as the breadcrumb label and the search-result subtitle.
        "country": country_info["name"],
        "country_code": country_info["code"],
        "countries": countries,
        "provinces": provinces,
        "popular": popular,
        "aliases": aliases,
    }


def location_errors(country, province, municipality, barangay=""):
    """Worldwide server-side validation for the cascade picker.

    Mirrors what ``static/js/location-cascade.js`` lets the user select:
    province and municipality are required and must form a real pair inside the
    tree for ``country``, and a barangay is required only when the chosen
    municipality has barangays on file. ``country`` is a name or ISO code and
    defaults to the platform's own country, so every establishment form can
    validate with the same helper no matter which country it is saving.
    Returns a list of human-readable messages (empty when valid).
    """
    from atrue_core.context_processors import _location_tree_cached

    errors = []
    if not (province or "").strip():
        errors.append("Province is required.")
    if not (municipality or "").strip():
        errors.append("Municipality/City is required.")
    if errors:
        return errors

    row = _country_row(country)
    code = row.code if row is not None else None
    tree = _location_tree_cached(code or '')

    key = normalize(province)
    matched = None
    for prov in tree["provinces"]:
        if normalize(prov.get("name")) == key:
            matched = prov
            break
    if matched is None:
        errors.append(f"'{province}' is not a recognized province.")
        return errors

    muni = next(
        (m for m in matched.get("municipalities", [])
         if normalize(m.get("name")) == normalize(municipality)),
        None,
    )
    if muni is None:
        errors.append(f"'{municipality}' is not part of {matched['name']}.")
    elif muni.get("barangays") and not (barangay or "").strip():
        errors.append(f"Barangay is required for {muni['name']}, {matched['name']}.")
    return errors


def location_display(province, municipality, barangay=None, country=None):
    """Human-readable path for the search field (e.g. "Cagayan, Baggao")."""
    parts = [p for p in [country, province, municipality, barangay] if p]
    return ", ".join(parts)


def country_province_keys(country):
    """Normalised province labels belonging to ``country``.

    Returns a set ready to hand to ``location_matches`` so a search can stop at
    the country. Listings do not store a country, so this is how a country-only
    selection is resolved: by which provinces the country owns. Accepts a country
    name or ISO code and expands the collapsed NCR to the label the tree shows.
    Returns ``None`` when the country is unknown, which makes the caller skip the
    country filter rather than silently match everything.
    """
    if not (country or "").strip():
        return None

    from locations.models import Province

    row = _country_row(country)
    if row is None:
        return None

    labels = Province.objects.filter(region__country=row).values_list(
        'name', 'region__code', 'region__country__code',
    )
    return {
        normalize(_province_label(province_name, region_code, country_code))
        for province_name, region_code, country_code in labels
    }


def location_matches(loc, province, municipality, barangay, loc_text=None,
                     country=None, country_provinces=None):
    """Resolve one item's location against the selected hierarchy.

    ``loc`` is a dict with "province", "municipality", "barangay" lists (or
    strings). ``loc_text`` is an optional free-text blob (used by restaurants)
    that is matched with naive substring semantics against the selected values.

    ``country`` is the top of the hierarchy, so a search can stop at the country.
    Listings do not store a country (only ``Landmark`` does), so a country-only
    selection is resolved through ``country_provinces`` -- the set of that
    country's province labels, precomputed once per request by the caller. A
    country combined with a province needs no help: the province already implies
    its country.
    """
    if not (country or province or municipality or barangay):
        return True

    prov_n = normalize(province)
    mun_n = normalize(municipality)
    brgy_n = normalize(barangay)
    country_n = normalize(country)

    item_provs = _as_list(loc.get("province"))
    item_muns = _as_list(loc.get("municipality"))
    item_brgys = _as_list(loc.get("barangay"))

    blob = normalize(loc_text) if loc_text else ""
    use_text = bool(blob)

    if country_n and not prov_n:
        if use_text:
            if country_n not in blob:
                return False
        else:
            own = _as_list(loc.get("country"))
            if own and any(normalize(v) == country_n for v in own):
                pass
            elif country_provinces is not None:
                if not any(normalize(v) in country_provinces for v in item_provs):
                    return False
            elif not own:
                # No country information at all for this item and none supplied:
                # cannot confirm, so do not claim a match.
                return False

    if prov_n:
        if use_text:
            if prov_n not in blob:
                return False
        elif not any(normalize(v) == prov_n for v in item_provs):
            return False

    if mun_n:
        if use_text:
            if mun_n not in blob:
                return False
        elif not any(normalize(v) == mun_n for v in item_muns):
            return False

    if brgy_n:
        if use_text:
            if brgy_n not in blob:
                return False
        elif not any(normalize(v) == brgy_n for v in item_brgys):
            return False

    return True


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]