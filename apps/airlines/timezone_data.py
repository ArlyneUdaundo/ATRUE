"""IANA time zones and terminals for the ATRUE airport table.

An airport's clock is a fact about the place, not about the schedule, so it
belongs to airport master data rather than to a flight.  Without it a
connecting journey cannot be timed honestly: MNL 10:00 to HKG 14:00 is four
hours of clock difference but three hours of flying.

Two levels are kept:

``AIRPORT_TIMEZONES``
    Exact IATA -> zone, used for every airport ATRUE schedules or demonstrates
    (the Philippines, plus the international hubs a connecting itinerary needs).
    Per-airport because a country can run more than one zone — the United States
    alone runs six.

``COUNTRY_TIMEZONES``
    ISO 3166-1 alpha-2 -> zone, the fallback for the rest of the worldwide
    airport table so an itinerary can be built through any airport in the world.

``AIRPORT_TERMINALS`` lists the terminals each airport operates, so the flight
form can offer a real choice instead of a free-text box.

Loaded by ``manage.py seed_flight_timezones`` and by migration 0034.  Existing
rows are only ever *filled in* — nothing here deletes or overwrites data the
database already holds.
"""

#: IATA -> IANA timezone.
AIRPORT_TIMEZONES = {
    # ---- Philippines ----------------------------------------------------
    'MNL': 'Asia/Manila',   # Ninoy Aquino International, Manila / Pasay
    'CEB': 'Asia/Manila',   # Mactan-Cebu International, Lapu-Lapu
    'DVO': 'Asia/Manila',   # Francisco Bangoy International, Davao
    'CRK': 'Asia/Manila',   # Clark International, Angeles / Pampanga
    'ILO': 'Asia/Manila',   # Mandurriao Airport, Iloilo
    'BCD': 'Asia/Manila',   # Bicol International, Legazpi
    'PPS': 'Asia/Manila',   # Puerto Princesa International
    'MPH': 'Asia/Manila',   # Godofredo P. Ramos, Malay / Boracay
    'KLO': 'Asia/Manila',   # Kalibo International
    'TAG': 'Asia/Manila',   # Tagbilaran / Bohol
    'ZAM': 'Asia/Manila',   # Zamboanga International
    'IAO': 'Asia/Manila',   # Sayak / Siargao
    'BAG': 'Asia/Manila',   # Loakan, Baguio
    'LAO': 'Asia/Manila',   # Laoag International
    'SUG': 'Asia/Manila',   # Surigao
    'IGN': 'Asia/Manila',   # Iligan
    # ---- International hubs ATRUE connects through ----------------------
    'SIN': 'Asia/Singapore',        # Singapore Changi
    'HKG': 'Asia/Hong_Kong',        # Hong Kong International
    'NRT': 'Asia/Tokyo',            # Narita International, Tokyo
    'HND': 'Asia/Tokyo',            # Haneda, Tokyo
    'ICN': 'Asia/Seoul',            # Incheon International, Seoul
    'BKK': 'Asia/Bangkok',          # Suvarnabhumi, Bangkok
    'DOH': 'Asia/Qatar',            # Hamad International, Doha
    'DXB': 'Asia/Dubai',            # Dubai International
    'AUH': 'Asia/Dubai',            # Abu Dhabi International
    'KUL': 'Asia/Kuala_Lumpur',     # Kuala Lumpur International
    'LHR': 'Europe/London',         # London Heathrow
    'CDG': 'Europe/Paris',          # Paris Charles de Gaulle
    'LGA': 'America/New_York',      # New York LaGuardia
    'JFK': 'America/New_York',      # New York JFK
    'LAX': 'America/Los_Angeles',   # Los Angeles International
    'SFO': 'America/Los_Angeles',   # San Francisco
    'ORD': 'America/Chicago',       # Chicago O'Hare
    'SYD': 'Australia/Sydney',      # Sydney Kingsford Smith
    'MEL': 'Australia/Melbourne',   # Melbourne Tullamarine
    'DEL': 'Asia/Kolkata',          # Delhi Indira Gandhi
    'BOM': 'Asia/Kolkata',          # Mumbai Chhatrapati Shivaji
    'DAD': 'Asia/Ho_Chi_Minh',      # Ho Chi Minh City Tan Son Nhat
    'SGN': 'Asia/Ho_Chi_Minh',      # Ho Chi Minh City (alias)
    'HAN': 'Asia/Ho_Chi_Minh',      # Hanoi Noi Bai
    'PEK': 'Asia/Shanghai',         # Beijing Capital
    'PVG': 'Asia/Shanghai',         # Shanghai Pudong
    'TPE': 'Asia/Taipei',           # Taipei Taoyuan
    'CGK': 'Asia/Jakarta',          # Jakarta Soekarno-Hatta
}

#: ISO 3166-1 alpha-2 -> IANA timezone, the fallback for the rest of the
#: worldwide airport table.  Countries that run a single zone only.
COUNTRY_TIMEZONES = {
    'PH': 'Asia/Manila',
    'SG': 'Asia/Singapore',
    'HK': 'Asia/Hong_Kong',
    'JP': 'Asia/Tokyo',
    'KR': 'Asia/Seoul',
    'TH': 'Asia/Bangkok',
    'MY': 'Asia/Kuala_Lumpur',
    'ID': 'Asia/Jakarta',
    'VN': 'Asia/Ho_Chi_Minh',
    'IN': 'Asia/Kolkata',
    'QA': 'Asia/Qatar',
    'AE': 'Asia/Dubai',
    'SA': 'Asia/Riyadh',
    'KW': 'Asia/Kuwait',
    'BH': 'Asia/Bahrain',
    'OM': 'Asia/Muscat',
    'JO': 'Asia/Amman',
    'IL': 'Asia/Jerusalem',
    'TR': 'Europe/Istanbul',
    'GB': 'Europe/London',
    'IE': 'Europe/Dublin',
    'FR': 'Europe/Paris',
    'DE': 'Europe/Berlin',
    'NL': 'Europe/Amsterdam',
    'ES': 'Europe/Madrid',
    'IT': 'Europe/Rome',
    'PT': 'Europe/Lisbon',
    'BE': 'Europe/Brussels',
    'CH': 'Europe/Zurich',
    'AT': 'Europe/Vienna',
    'DK': 'Europe/Copenhagen',
    'SE': 'Europe/Stockholm',
    'NO': 'Europe/Oslo',
    'FI': 'Europe/Helsinki',
    'PL': 'Europe/Warsaw',
    'CZ': 'Europe/Prague',
    'GR': 'Europe/Athens',
    'AU': 'Australia/Sydney',
    'NZ': 'Pacific/Auckland',
    'CN': 'Asia/Shanghai',
    'TW': 'Asia/Taipei',
    'US': 'America/New_York',
    'CA': 'America/Toronto',
    'MX': 'America/Mexico_City',
    'BR': 'America/Sao_Paulo',
    'AR': 'America/Argentina/Buenos_Aires',
    'ZA': 'Africa/Johannesburg',
    'EG': 'Africa/Cairo',
    'KE': 'Africa/Nairobi',
    'NG': 'Africa/Lagos',
}

#: IATA -> comma-separated terminal list, for the terminal picker.
AIRPORT_TERMINALS = {
    'MNL': '1, 2, 3, 4, 5, 6',
    'CEB': '1, 2',
    'DVO': '1',
    'CRK': '1, 2',
    'ILO': '1, 2',
    'BCD': '1',
    'PPS': '1, 2',
    'MPH': '1',
    'KLO': '1, 2',
    'TAG': '1',
    'ZAM': '1',
    'IAO': '1',
    'BAG': '1',
    'LAO': '1',
    'SIN': '1, 2, 3, 4',
    'HKG': '1',
    'NRT': '1, 2, 3',
    'HND': '2, 3',
    'ICN': '1, 2',
    'BKK': '1, 2, 3, 4, Suvarnabhumi, Don Mueang',
    'KUL': '1, 2, klia2, klia3',
    'DOH': '1, 2, 3',
    'DXB': '1, 2, 3',
    'AUH': 'A, B, C, D',
    'LHR': '2, 3, 4, 5',
    'CDG': '1, 2E, 2F, 2G, 2K',
    'LGA': 'A, B, C, D',
    'JFK': '1, 2, 4, 5, 7, 8',
    'LAX': '1, 2, 3, 4, 5, 6, 7, 8, TBIT',
    'SFO': '1, 2, 3, I, G, A',
    'ORD': '1, 2, 3, 5',
    'SYD': '1, 2, 3',
    'MEL': '2, 3, 4',
    'DEL': '1, 2, 3',
    'BOM': '1, 2',
    'DAD': '1, 2',
    'HAN': '1, 2',
    'PEK': '2, 3, 1',
    'PVG': '1, 2, S1, S2',
    'TPE': '1, 2',
    'CGK': '1, 2, 3',
}


def timezone_for_airport(airport):
    """The IANA zone for an ``Airport``, or ``''`` when nothing is known.

    Prefers the airport's own data, then an exact IATA match, then the
    country.  Returns an empty string rather than guessing, so the caller can
    fall back to the platform zone explicitly and visibly.
    """
    if getattr(airport, 'timezone', ''):
        return airport.timezone
    iata = (getattr(airport, 'iata_code', '') or '').strip().upper()
    if iata in AIRPORT_TIMEZONES:
        return AIRPORT_TIMEZONES[iata]
    icao = (getattr(airport, 'icao_code', '') or '').strip().upper()
    if icao in AIRPORT_TIMEZONES:
        return AIRPORT_TIMEZONES[icao]
    code = (getattr(airport, 'country_code', '') or '').strip().upper()
    return COUNTRY_TIMEZONES.get(code, '')


def terminals_for_airport(airport):
    """The terminal list for an ``Airport``, or ``''`` when none is recorded."""
    if getattr(airport, 'terminals', ''):
        return airport.terminals
    iata = (getattr(airport, 'iata_code', '') or '').strip().upper()
    return AIRPORT_TERMINALS.get(iata, '')
