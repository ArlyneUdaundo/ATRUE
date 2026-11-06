"""Resolve an airline's official logo once and keep a local, locked copy."""

from __future__ import annotations

import html
import io
import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.text import slugify
from PIL import Image, UnidentifiedImageError

from .models import Airline, AirlinePhoto

logger = logging.getLogger(__name__)

USER_AGENT = 'ATRUE-Flight-Management/1.0 (airline logo storage)'
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
WIKIDATA_API = 'https://www.wikidata.org/w/api.php'
COMMONS_API = 'https://commons.wikimedia.org/w/api.php'


def _read_url(url, *, limit=MAX_DOWNLOAD_BYTES):
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'image/*,application/json'})
    with urlopen(request, timeout=7) as response:
        content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError('Logo response exceeded the download size limit.')
        return content, response.headers.get('Content-Type', '')


def _read_json(url):
    raw, _content_type = _read_url(url, limit=1_000_000)
    return json.loads(raw.decode('utf-8'))


def _normalized_name(value):
    return ''.join(char for char in (value or '').casefold() if char.isalnum())


def _wikidata_logo_filename(airline_name):
    search_url = WIKIDATA_API + '?' + urlencode({
        'action': 'wbsearchentities', 'search': airline_name, 'language': 'en',
        'format': 'json', 'type': 'item', 'limit': 10,
    })
    results = _read_json(search_url).get('search', [])
    target = _normalized_name(airline_name)
    exact_airline_items = [
        result for result in results
        if _normalized_name(result.get('label')) == target
        and re.search(r'\b(airline|air carrier|air transport)\b',
                      result.get('description', ''), re.I)
    ]
    for result in exact_airline_items:
        entity_url = 'https://www.wikidata.org/wiki/Special:EntityData/' + quote(result['id']) + '.json'
        entity = _read_json(entity_url).get('entities', {}).get(result['id'], {})
        statements = entity.get('claims', {}).get('P154', [])
        for statement in statements:
            data = statement.get('mainsnak', {}).get('datavalue', {}).get('value')
            if isinstance(data, str) and data.strip():
                return data.strip()
    return None


def _commons_logo_info(filename):
    title = 'File:' + filename
    url = COMMONS_API + '?' + urlencode({
        'action': 'query', 'titles': title, 'prop': 'imageinfo',
        'iiprop': 'url|mime|extmetadata', 'iiurlwidth': 800,
        'format': 'json', 'formatversion': 2,
    })
    pages = _read_json(url).get('query', {}).get('pages', [])
    if not pages:
        return None
    info = (pages[0].get('imageinfo') or [{}])[0]
    thumb_url = info.get('thumburl')
    parsed_url = urlparse(thumb_url or '')
    if parsed_url.scheme != 'https' or parsed_url.hostname != 'upload.wikimedia.org':
        return None
    metadata = info.get('extmetadata') or {}
    value = lambda key: _plain_text((metadata.get(key) or {}).get('value', ''))
    return {
        'url': thumb_url,
        'source_url': info.get('descriptionurl', ''),
        'license_name': value('LicenseShortName')[:120],
        'attribution': (value('Credit') or value('Artist'))[:250],
    }


def _plain_text(value):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or ''))).strip()


def _as_png(content, content_type):
    if not content_type.lower().startswith('image/'):
        raise ValueError('Logo source did not return an image.')
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError('Logo image dimensions exceeded the safe limit.')
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP', 'GIF'}:
                raise ValueError('Logo image format is not supported.')
            rgba = image.convert('RGBA')
            output = io.BytesIO()
            rgba.save(output, format='PNG', optimize=True)
            result = output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError('Logo source returned an invalid image.') from exc
    if len(result) > MAX_DOWNLOAD_BYTES:
        raise ValueError('Processed logo exceeded the storage size limit.')
    return result


def _resolve_logo(airline_name):
    filename = _wikidata_logo_filename(airline_name)
    if not filename:
        return None
    info = _commons_logo_info(filename)
    if not info:
        return None
    content, content_type = _read_url(info['url'])
    return _as_png(content, content_type), info


def ensure_airline_logo(airline_id):
    """Attach a local logo if this airline does not already have one.

    Lookup failures leave the airline without a logo so templates can render
    their built-in placeholder. This is safe to retry from the management
    command; an existing locked logo is always reused.
    """
    try:
        airline = Airline.objects.get(pk=airline_id)
        locked = AirlinePhoto.objects.filter(
            airline_id=airline_id, is_locked_logo=True).first()
        if locked:
            return locked

        # Promote a previously registered primary mark instead of replacing it.
        legacy_logo = AirlinePhoto.objects.filter(
            airline_id=airline_id, is_primary=True).first()
        if legacy_logo:
            AirlinePhoto.objects.filter(pk=legacy_logo.pk).update(is_locked_logo=True)
            legacy_logo.refresh_from_db()
            return legacy_logo

        # Reuse the stored file for duplicate records with the same airline name.
        shared = AirlinePhoto.objects.filter(
            airline__name__iexact=airline.name, is_locked_logo=True,
        ).exclude(airline_id=airline_id).first()
        if shared and shared.image:
            return AirlinePhoto.objects.create(
                airline=airline, image=shared.image.name, is_primary=True,
                is_locked_logo=True, source_url=shared.source_url,
                license_name=shared.license_name, attribution=shared.attribution,
                caption='Official airline logo',
            )

        resolved = _resolve_logo(airline.name)
        if not resolved:
            logger.info('No verified logo found for airline %s', airline.name)
            return None
        image_bytes, metadata = resolved

        with transaction.atomic():
            airline = Airline.objects.select_for_update().get(pk=airline_id)
            locked = AirlinePhoto.objects.filter(
                airline_id=airline_id, is_locked_logo=True).first()
            if locked:
                return locked
            legacy_logo = AirlinePhoto.objects.filter(
                airline_id=airline_id, is_primary=True).first()
            if legacy_logo:
                AirlinePhoto.objects.filter(pk=legacy_logo.pk).update(is_locked_logo=True)
                legacy_logo.refresh_from_db()
                return legacy_logo

            shared = AirlinePhoto.objects.filter(
                airline__name__iexact=airline.name, is_locked_logo=True,
            ).exclude(airline_id=airline_id).first()
            if shared and shared.image:
                return AirlinePhoto.objects.create(
                    airline=airline, image=shared.image.name, is_primary=True,
                    is_locked_logo=True, source_url=shared.source_url,
                    license_name=shared.license_name, attribution=shared.attribution,
                    caption='Official airline logo',
                )

            storage_name = f'airline_photos/official/{airline.pk}-{slugify(airline.name) or "airline"}.png'
            if not default_storage.exists(storage_name):
                storage_name = default_storage.save(storage_name, ContentFile(image_bytes))
            return AirlinePhoto.objects.create(
                airline=airline, image=storage_name, is_primary=True,
                is_locked_logo=True, source_url=metadata.get('source_url', ''),
                license_name=metadata.get('license_name', ''),
                attribution=metadata.get('attribution', ''),
                caption='Official airline logo',
            )
    except Airline.DoesNotExist:
        return None
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning('Could not retrieve a logo for airline id %s: %s', airline_id, exc)
        return None
