"""Ad-hoc geometry check — run via: manage.py test width_probe -v 2"""
import re

from django.test import TestCase
from django.urls import reverse

from airlines.layouts import build_seat_map
from airlines.tests import make_airline
from airlines.models import Flight
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

CSS = open('static/css/dashboard.css', encoding='utf-8').read()


class WidthProbe(TestCase):
    def test_probe(self):
        airline, _ = make_airline('Emirates PH', types=('A380-800',),
                                  primary='A380-800', spec='A380_448')
        user = get_user_model().objects.create_user(
            username='probe', password='x', email='p@e.com')
        self.client.force_login(user)
        flight = Flight.objects.create(
            airline=airline, flight_number='EK-301',
            departure_time=timezone.now() + timedelta(days=3),
            arrival_time=timezone.now() + timedelta(days=3, hours=8),
            status='SCHEDULED', economy_fare=30000)
        body = self.client.get(
            reverse('airlines:book', args=[flight.pk])).content.decode()
        seat_map = build_seat_map(flight)

        base = re.search(r'\.seat-grid \{(.*?)\}', CSS, re.S).group(1)
        tok = {k: int(v) for k, v in re.findall(
            r'--(seat-w|seat-h|seat-gap|aisle-w|row-no-w):\s*(\d+)px', base)}
        print('\ndesktop seat tokens:', tok)

        for m in re.finditer(
                r'seat-cabin-title">([^<]+)</span>.*?seat-cabin-deck(.*?)</section>',
                body, re.S):
            name, deck = m.group(1), m.group(2)
            head = re.search(r'seat-row-head">(.*?)</div>', deck, re.S).group(1)
            letters = re.findall(r'seat-col-label">([A-Z])</span>', head)
            head_gaps = head.count('seat-aisle-gap')
            rows = re.findall(r'class="seat-row"[^>]*>(.*?)</div>', deck, re.S)
            per_row = [len(re.findall(r'class="seat-tile', r)) for r in rows]
            width = (tok['row-no-w'] + tok['seat-gap']
                     + per_row[0] * (tok['seat-w'] + tok['seat-gap'])
                     + head_gaps * (tok['aisle-w'] + tok['seat-gap']))
            print('%-16s cols=%-2d letters=%-24s gaps=%d tiles=%-3s rows=%-3d width=%dpx'
                  % (name, len(letters), ''.join(letters), head_gaps,
                     sorted(set(per_row)), len(rows), width))
            assert len(set(per_row)) == 1, 'ragged cabin %s' % set(per_row)
            assert len(letters) == per_row[0]

        card = re.search(r'\.seat-modal-card \{[^}]*width:\s*min\((\d+)px', CSS).group(1)
        pax = re.search(r'\.seat-pax \{[^}]*flex:\s*0 0 (\d+)px', CSS, re.S).group(1)
        gap = re.search(r'\.seat-modal-body \{[^}]*gap:\s*(\d+)px', CSS, re.S).group(1)
        pad = re.search(r'\.seat-modal-body \{[^}]*padding:\s*([^;]+);', CSS, re.S).group(1)
        print('\ncard=%s pax=%s gap=%s padding=%s' % (card, pax, gap, pad))
        print('cabins:', [(c['label'], c['key']) for c in seat_map['cabins']])
