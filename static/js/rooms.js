/* ============================================================
   ATRUE — Rooms page behaviour
   Room photos & details · Compare rooms · room selection
   (Select toggle) · guest information · live computation · booking submit.

   Server contract (unchanged): posts check_in / check_out /
   rooms_needed / adults / children / room_ids[] / room_N_* guest
   fields / payment_method / pay_later to hotels:group_select_rooms.
   ============================================================ */
(function () {
    'use strict';

    function readJson(id, fallback) {
        var el = document.getElementById(id);
        if (!el) return fallback;
        try { return JSON.parse(el.textContent || '') || fallback; }
        catch (e) { return fallback; }
    }

    var RATE = readJson('roomRates', {});
    var META = readJson('roomsMeta', {});
    var SERVICES = readJson('servicesData', {});
    var AMENITIES = readJson('amenitiesData', {});
    var PRESELECTED = readJson('preselected', []);
    var DETAILS = readJson('roomDetails', {});

    var form = document.getElementById('bookingForm');
    if (!form) return;

    var cards = Array.prototype.slice.call(document.querySelectorAll('[data-room-card]'));
    var roomCountPanel = document.getElementById('roomCountPanel');
    var pbRoomsSelected = document.getElementById('pbRoomsSelected');
    var pbCheckInEl = document.getElementById('pbCheckIn');
    var pbCheckOutEl = document.getElementById('pbCheckOut');
    var pbNightsEl = document.getElementById('pbNights');
    var pbGuestsEl = document.getElementById('pbGuests');
    var lines = document.getElementById('pbRoomLines');
    var divider = document.getElementById('pbDivider');
    var totalEl = document.getElementById('pbTotal');
    var totalLabel = document.getElementById('pbTotalLabel');
    var btn = document.getElementById('continueBtn');
    var wrap = document.getElementById('selectedRoomsSection');
    var summary = document.getElementById('computationSummary');
    var roomIdsEl = document.getElementById('roomIdsInputs');
    var roomsNeededEl = document.getElementById('bkRoomsNeeded');
    var ci = document.getElementById('bkCheckIn');
    var co = document.getElementById('bkCheckOut');

    var modal = document.getElementById('roomModal');
    var modalTitle = document.getElementById('roomModalTitle');
    var modalSub = document.getElementById('roomModalSub');
    var modalBody = document.getElementById('roomModalBody');
    var modalFull = document.getElementById('roomModalFull');
    var comparePanel = document.getElementById('comparePanel');
    var compareToggle = document.getElementById('compareToggle');

    var guestModal = document.getElementById('guestModal');
    var guestModalSub = document.getElementById('guestModalSub');
    var guestSave = document.getElementById('guestModalSave');
    var guestOpener = null;

    var SELECTED = [];      // one entry per booked room, in selection order
    var ACTIVE = 0;         // index into SELECTED whose guest card is visible

    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    /* ---------------------------------------------------------- helpers */

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function peso(n) {
        return Number(n || 0).toLocaleString('en-PH', { maximumFractionDigits: 0 });
    }

    function fmt(n) {
        return '₱ ' + Number(n || 0).toLocaleString('en-PH', {
            minimumFractionDigits: 2, maximumFractionDigits: 2
        });
    }

    function prettyDate(iso) {
        var d = new Date(iso + 'T00:00:00');
        if (isNaN(d.getTime())) return '—';
        return MONTHS[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
    }

    function cardOf(id) {
        return document.querySelector('[data-room-card="' + id + '"]');
    }

    function metaOf(id) {
        return META[String(id)] || {};
    }

    function typeOf(id) {
        var card = cardOf(id);
        return card ? card.getAttribute('data-room-type') : '';
    }

    function currentNights() {
        var ds = Date.parse(ci.value + 'T00:00:00');
        var de = Date.parse(co.value + 'T00:00:00');
        if (!isFinite(ds) || !isFinite(de) || de <= ds) return null;
        return Math.max(1, Math.round((de - ds) / 86400000));
    }

    function findIndex(roomId) {
        for (var i = 0; i < SELECTED.length; i++) {
            if (SELECTED[i].room_id === Number(roomId)) return i;
        }
        return -1;
    }

    function emptyGuest() {
        return {
            first_name: '', middle_name: '', last_name: '', email: '', contact: '',
            adults: 1, children: 0, special_request: ''
        };
    }

    function makeEntry(roomId) {
        var m = metaOf(roomId);
        return {
            room_id: Number(roomId),
            room_number: m.room_number || String(roomId),
            room_type: m.room_type || 'Room',
            room_type_key: typeOf(roomId),
            rate: Number(m.rate || RATE[roomId] || 0),
            capacity: Number(m.capacity || 1),
            max_guests: Number(m.max_guests || 1),
            additional_charge: Number(m.additional_charge || 0),
            guest: emptyGuest(),
            services: [],
            amenities: []
        };
    }

    /* ------------------------------------------------- selection actions */

    function addRoom(roomId) {
        if (findIndex(roomId) !== -1) return;
        SELECTED.push(makeEntry(roomId));
    }

    function removeRoom(roomId) {
        var idx = findIndex(roomId);
        if (idx === -1) return;
        var wasActive = (ACTIVE === idx);
        SELECTED.splice(idx, 1);
        if (wasActive) ACTIVE = Math.min(idx, SELECTED.length - 1);
        else if (idx < ACTIVE) ACTIVE -= 1;
        if (ACTIVE < 0) ACTIVE = 0;
    }

    function toggleRoom(roomId) {
        var id = Number(roomId);
        if (findIndex(id) === -1) addRoom(id);
        else removeRoom(id);
    }

    /* ------------------------------------------------------- card chrome */

    function paintRoomButtons() {
        cards.forEach(function (card) {
            var id = Number(card.getAttribute('data-room-card'));
            var picked = findIndex(id) !== -1;
            var rate = card.querySelector('.rm-rate');
            if (rate) rate.classList.toggle('is-selected', picked);
            Array.prototype.forEach.call(card.querySelectorAll('[data-room-book]'), function (el) {
                el.classList.toggle('is-on', picked);
                el.setAttribute('aria-pressed', picked ? 'true' : 'false');
                el.innerHTML = picked
                    ? '<i class="fas fa-check"></i> Selected'
                    : '<i class="fas fa-circle-check"></i> Select';
            });
            var gbtn = card.querySelector('[data-guest-open]');
            if (gbtn) {
                gbtn.hidden = !picked;
                gbtn.setAttribute('aria-label', 'Guest information for room ' +
                    (metaOf(id).room_number || id));
            }
        });
    }

    function paintCards() {
        cards.forEach(function (card) {
            var id = Number(card.getAttribute('data-room-card'));
            card.classList.toggle('is-selected', findIndex(id) !== -1);
        });
        paintRoomButtons();
    }

    /* -------------------------------------------------- guest + summary */

    function guestComplete(s) {
        var g = s.guest || {};
        return !!(g.first_name && g.last_name && g.email && g.contact) &&
            (Number(g.adults || 0) + Number(g.children || 0)) >= 1;
    }

    function tabsMarkup() {
        if (SELECTED.length < 2) return '';
        return '<div class="bk-room-tabs" role="tablist" aria-label="Selected rooms">' +
            SELECTED.map(function (s, i) {
                return '<button type="button" role="tab" class="bk-room-tab' +
                    (i === ACTIVE ? ' is-active' : '') + '" data-room-tab="' + i + '"' +
                    ' id="bkRoomTab' + i + '" aria-controls="bkRoomPanel' + i + '"' +
                    ' aria-selected="' + (i === ACTIVE ? 'true' : 'false') + '"' +
                    ' tabindex="' + (i === ACTIVE ? '0' : '-1') + '">' +
                    '<span class="bk-room-tab-no">Room ' + (i + 1) + '</span>' +
                    '<span class="bk-room-tab-meta">' + esc(s.room_number) + '</span>' +
                    (guestComplete(s) ? '<i class="fas fa-check bk-tab-done"></i>' : '') +
                    '</button>';
            }).join('') +
        '</div>';
    }

    function paintTabs() {
        var cards = wrap.querySelectorAll('.bk-guest-card');
        var tabbed = SELECTED.length >= 2;
        for (var j = 0; j < cards.length; j++) {
            cards[j].hidden = (j !== ACTIVE);
            if (tabbed) {
                cards[j].setAttribute('role', 'tabpanel');
                cards[j].setAttribute('aria-labelledby', 'bkRoomTab' + j);
            } else {
                cards[j].removeAttribute('role');
                cards[j].removeAttribute('aria-labelledby');
            }
        }
        var tabs = wrap.querySelectorAll('[data-room-tab]');
        for (var i = 0; i < tabs.length; i++) {
            var on = (i === ACTIVE);
            tabs[i].classList.toggle('is-active', on);
            tabs[i].setAttribute('aria-selected', on ? 'true' : 'false');
            tabs[i].setAttribute('tabindex', on ? '0' : '-1');
        }
    }

    function setActive(i) {
        if (!SELECTED.length) return;
        syncFromDom();
        ACTIVE = Math.max(0, Math.min(SELECTED.length - 1, i));
        paintTabs();
    }

    /* ------------------------------------------------- guest info modal */

    function guestModalOpen() {
        return !!(guestModal && guestModal.classList.contains('open'));
    }

    function modalFocusables(root) {
        return Array.prototype.slice.call(root.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]),' +
            ' textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
            .filter(function (el) { return el.getClientRects().length > 0; });
    }

    function openGuestModal(roomId) {
        if (!guestModal || !SELECTED.length) return;
        var idx = (roomId === undefined || roomId === null) ? ACTIVE : findIndex(roomId);
        if (idx === -1) return;
        setActive(idx);
        var s = SELECTED[ACTIVE];
        if (guestModalSub && s) {
            guestModalSub.textContent = 'Room ' + (ACTIVE + 1) + ' of ' + SELECTED.length +
                ' · ' + s.room_type + ' · Room ' + s.room_number +
                '. Please provide the guest details below.';
        }
        guestModal.classList.add('open');
        document.body.style.overflow = 'hidden';
        var card = wrap.querySelector('.bk-guest-card:not([hidden])');
        var fields = card ? modalFocusables(card) : [];
        var target = fields.filter(function (el) { return el.tagName === 'INPUT' && !el.value; })[0] || fields[0];
        if (target) target.focus();
    }

    function closeGuestModal() {
        if (!guestModal || !guestModalOpen()) return;
        syncFromDom();
        guestModal.classList.remove('open');
        if (!modal || !modal.classList.contains('open')) document.body.style.overflow = '';
        // preventScroll: returning focus must not move the page.
        if (guestOpener && guestOpener.focus) {
            try { guestOpener.focus({ preventScroll: true }); }
            catch (err) { guestOpener.focus(); }
        }
        guestOpener = null;
    }

    function buildSection(s, i) {
        var g = s.guest;
        var svcBoxes = Object.keys(SERVICES).map(function (id) {
            var svc = SERVICES[id];
            var checked = s.services.indexOf(Number(id)) !== -1 ? ' checked' : '';
            return '<label class="checkbox"><input type="checkbox" name="room_' + i + '_services" value="' + id + '"' + checked + '> ' + esc(svc.name) + ' (+₱ ' + esc(svc.rate) + ')</label>';
        }).join('');
        var amnBoxes = Object.keys(AMENITIES).map(function (id) {
            var checked = s.amenities.indexOf(Number(id)) !== -1 ? ' checked' : '';
            return '<label class="checkbox"><input type="checkbox" name="room_' + i + '_amenities" value="' + id + '"' + checked + '> ' + esc(AMENITIES[id].name) + '</label>';
        }).join('');
        var svcBlock = svcBoxes ? '<div class="bk-guest-extras"><div><b>Optional services for Room ' + (i + 1) + '</b></div>' + svcBoxes + '</div>' : '';
        var amnBlock = amnBoxes ? '<div class="bk-guest-extras"><div><b>Amenities for Room ' + (i + 1) + '</b></div>' + amnBoxes + '</div>' : '';
        return '' +
        '<section class="bk-guest-card" id="bkRoomPanel' + i + '" data-guest-section="' + i + '">' +
            '<div class="bk-guest-head">' +
                '<div><span class="badge badge-blue">ROOM ' + (i + 1) + '</span>' +
                '<h3 style="margin:8px 0 2px">' + esc(s.room_type) + ' Room</h3>' +
                '<small>Room ' + esc(s.room_number) + ' · ' + fmt(s.rate) + '/night · Included guests: ' + s.capacity + ' · Max: ' + s.max_guests + (s.additional_charge > 0 ? ' · Extra guest: ' + fmt(s.additional_charge) + '/guest/night' : '') + '</small>' +
                '</div>' +
                '<button type="button" class="bk-remove" data-remove-room="' + s.room_id + '"><i class="fas fa-times"></i> Remove</button>' +
            '</div>' +
            '<div class="bk-guest-grid">' +
                '<div class="form-group"><label>First Name *</label><input name="room_' + i + '_first_name" class="form-input" value="' + esc(g.first_name) + '"></div>' +
                '<div class="form-group"><label>Middle Name</label><input name="room_' + i + '_middle_name" class="form-input" value="' + esc(g.middle_name) + '"></div>' +
                '<div class="form-group"><label>Last Name *</label><input name="room_' + i + '_last_name" class="form-input" value="' + esc(g.last_name) + '"></div>' +
                '<div class="form-group"><label>Email *</label><input type="email" name="room_' + i + '_email" class="form-input" value="' + esc(g.email) + '"></div>' +
                '<div class="form-group"><label>Contact Number *</label><input type="text" name="room_' + i + '_contact" class="form-input" value="' + esc(g.contact) + '" inputmode="numeric" pattern="[0-9]*" maxlength="20" autocomplete="off" oninput="this.value=this.value.replace(/\\D/g,\'\')" title="Numbers only"></div>' +
                '<div class="form-group"><label>Adults *</label><input type="number" name="room_' + i + '_adults" class="form-input" value="' + Number(g.adults || 0) + '" min="0"></div>' +
                '<div class="form-group"><label>Children</label><input type="number" name="room_' + i + '_children" class="form-input" value="' + Number(g.children || 0) + '" min="0"></div>' +
                '<div class="form-group"><label>Total guests</label><div class="form-input" style="background:#f8fafc" data-guest-total="' + i + '">' + (Number(g.adults || 0) + Number(g.children || 0)) + ' <small class="meta">of ' + s.max_guests + ' max</small></div></div>' +
                '<div class="form-group bk-col-4"><label>Special Request</label><textarea name="room_' + i + '_special_request" class="form-input" rows="2">' + esc(g.special_request) + '</textarea></div>' +
            '</div>' +
            svcBlock + amnBlock +
            '<div class="bk-guest-err"></div>' +
        '</section>';
    }

    function renderSections() {
        wrap.innerHTML = tabsMarkup() + SELECTED.map(buildSection).join('');
        // The guest modal lives outside <form>, so the per-room fields are tied
        // back to the booking form with the HTML form="" attribute. Same inputs,
        // same names, same submit.
        if (form && form.id) {
            Array.prototype.forEach.call(
                wrap.querySelectorAll('input, textarea, select'),
                function (el) { el.setAttribute('form', form.id); });
        }
        if (SELECTED.length === 0) {
            ACTIVE = 0;
            return;
        }
        if (ACTIVE >= SELECTED.length) {
            ACTIVE = SELECTED.length - 1;
        }
        paintTabs();
    }

    function syncRoomIds() {
        if (roomIdsEl) {
            roomIdsEl.innerHTML = SELECTED.map(function (s) {
                return '<input type="hidden" name="room_ids" value="' + s.room_id + '">';
            }).join('');
        }
        if (roomsNeededEl) roomsNeededEl.value = SELECTED.length;
    }

    function syncFromDom() {
        SELECTED.forEach(function (s, i) {
            var sec = document.querySelector('[data-guest-section="' + i + '"]');
            if (!sec) return;
            function inVal(name) {
                var el = sec.querySelector('[name="room_' + i + '_' + name + '"]');
                return el ? el.value : '';
            }
            function checked(name) {
                return Array.prototype.slice
                    .call(sec.querySelectorAll('[name="room_' + i + '_' + name + '"]:checked'))
                    .map(function (el) { return Number(el.value); });
            }
            s.guest.first_name = inVal('first_name');
            s.guest.middle_name = inVal('middle_name');
            s.guest.last_name = inVal('last_name');
            s.guest.email = inVal('email');
            s.guest.contact = inVal('contact');
            s.guest.special_request = inVal('special_request');
            s.guest.adults = Math.max(0, parseInt(inVal('adults'), 10) || 0);
            s.guest.children = Math.max(0, parseInt(inVal('children'), 10) || 0);
            s.services = checked('services');
            s.amenities = checked('amenities');
        });
    }

    function computeAll() {
        var nights = currentNights();
        var okDates = nights !== null;
        if (!okDates) nights = 1;
        var rows = SELECTED.map(function (s) {
            var guests = s.guest.adults + s.guest.children;
            var extra = Math.max(0, guests - s.capacity);
            var roomTotal = s.rate * nights;
            var extraTotal = s.additional_charge * extra * nights;
            var svcTotal = s.services.reduce(function (a, id) {
                var svc = SERVICES[String(id)];
                return a + (svc ? Number(svc.rate) : 0);
            }, 0);
            var svcNames = s.services.map(function (id) {
                var svc = SERVICES[String(id)];
                return svc ? svc.name : '';
            }).filter(Boolean);
            return {
                s: s, nights: nights, guests: guests, extra: extra,
                roomTotal: roomTotal, extraTotal: extraTotal,
                svcTotal: svcTotal, svcNames: svcNames,
                total: roomTotal + extraTotal + svcTotal
            };
        });
        var roomsSub = rows.reduce(function (a, r) { return a + r.roomTotal; }, 0);
        var extraSub = rows.reduce(function (a, r) { return a + r.extraTotal; }, 0);
        var svcSub = rows.reduce(function (a, r) { return a + r.svcTotal; }, 0);
        var grand = roomsSub + extraSub + svcSub;

        if (pbNightsEl) pbNightsEl.textContent = okDates ? nights : '—';
        if (totalLabel) {
            totalLabel.textContent = okDates
                ? ('Estimated total × ' + nights + ' night' + (nights === 1 ? '' : 's'))
                : 'Check-out must be after check-in';
        }
        if (totalEl) totalEl.textContent = okDates ? fmt(grand) : '₱ 0';
        if (pbCheckInEl) pbCheckInEl.textContent = prettyDate(ci.value);
        if (pbCheckOutEl) pbCheckOutEl.textContent = prettyDate(co.value);
        var gpTotal = rows.reduce(function (a, r) { return a + r.guests; }, 0);
        if (pbGuestsEl && SELECTED.length) {
            pbGuestsEl.textContent = gpTotal >= 1 ? gpTotal + ' guest' + (gpTotal === 1 ? '' : 's') : '—';
        }
        if (roomCountPanel) {
            roomCountPanel.textContent = SELECTED.length >= 1
                ? SELECTED.length + ' room' + (SELECTED.length === 1 ? '' : 's') + ' selected'
                : '0 selected';
        }
        if (pbRoomsSelected) pbRoomsSelected.textContent = SELECTED.length;
        if (lines) {
            if (!SELECTED.length) {
                lines.innerHTML = '<div class="ag-pb-row"><span>Select at least one room</span><b>—</b></div>';
            } else {
                lines.innerHTML = rows.map(function (r, i) {
                    var html = '<div class="ag-pb-row"><span>Room ' + (i + 1) + ' · ' + esc(r.s.room_number) +
                        ' <small class="meta">' + esc(r.s.room_type) + '</small>' +
                        (r.extra ? ' <small class="meta">+' + r.extra + ' extra guest(s)</small>' : '') +
                        '</span><b>' + fmt(r.s.rate) + ' × ' + r.nights + '</b></div>';
                    if (r.extraTotal > 0) {
                        html += '<div class="ag-pb-row"><span>&nbsp;&nbsp;+ Extra guest charge</span><b>' + fmt(r.extraTotal) + '</b></div>';
                    }
                    if (r.svcTotal > 0) {
                        html += '<div class="ag-pb-row"><span>&nbsp;&nbsp;+ Services</span><b>' + fmt(r.svcTotal) + '</b></div>';
                    }
                    return html;
                }).join('');
            }
            if (divider) divider.style.display = SELECTED.length ? 'block' : 'none';
        }
        if (btn) {
            btn.disabled = !SELECTED.length || !okDates;
            btn.innerHTML = SELECTED.length < 1
                ? '<i class="fas fa-bed"></i> Book room(s)'
                : '<i class="fas fa-bed"></i> BOOK ' + SELECTED.length + ' ROOM' + (SELECTED.length === 1 ? '' : 'S');
        }

        renderSummary(rows, roomsSub, extraSub, svcSub, grand, okDates);
        updateGuestTotals(rows);
        paintTabDone();
    }

    function paintTabDone() {
        Array.prototype.forEach.call(wrap.querySelectorAll('[data-room-tab]'), function (t) {
            var s = SELECTED[Number(t.getAttribute('data-room-tab'))];
            if (!s) return;
            var done = guestComplete(s);
            var icon = t.querySelector('.bk-tab-done');
            if (done && !icon) {
                t.insertAdjacentHTML('beforeend', '<i class="fas fa-check bk-tab-done"></i>');
            } else if (!done && icon) {
                icon.parentNode.removeChild(icon);
            }
        });
    }

    function renderSummary(rows, roomsSub, extraSub, svcSub, grand, okDates) {
        if (!summary) return;
        if (!SELECTED.length) {
            summary.innerHTML = '<div class="card card-pad bk-summary"><h3>Booking computation</h3>' +
                '<p class="bk-sum-hint">Select at least one room to see the full computation.</p></div>';
            return;
        }
        var roomHtml = rows.map(function (r, i) {
            var html = '<div class="bk-sum-row"><span>Room ' + (i + 1) + ' · ' + esc(r.s.room_type) +
                ' (' + esc(r.s.room_number) + ')</span><b>' + fmt(r.roomTotal) + '</b></div>';
            html += '<div class="bk-sum-row" style="padding-left:14px"><span>' + fmt(r.s.rate) + ' × ' +
                r.nights + ' night' + (r.nights === 1 ? '' : 's') + '</span><b>' + fmt(r.roomTotal) + '</b></div>';
            if (r.extraTotal > 0) {
                html += '<div class="bk-sum-row" style="padding-left:14px"><span class="bk-sum-extra">+ ' +
                    r.extra + ' extra guest(s) charge</span><b class="bk-sum-extra">' + fmt(r.extraTotal) + '</b></div>';
            }
            if (r.svcNames.length) {
                html += '<div class="bk-sum-row" style="padding-left:14px"><span>+ ' + esc(r.svcNames.join(', ')) +
                    '</span><b>' + fmt(r.svcTotal) + '</b></div>';
            }
            return html;
        }).join('');
        var servicesSection = svcSub > 0
            ? '<div class="bk-sum-section">Service charges</div>' +
              '<div class="bk-sum-row"><span>Services across all rooms</span><b>' + fmt(svcSub) + '</b></div>' +
              '<div class="bk-sum-subtotal"><span>Subtotal</span><span>' + fmt(roomsSub + extraSub + svcSub) + '</span></div>'
            : '<div class="bk-sum-subtotal"><span>Subtotal</span><span>' + fmt(roomsSub + extraSub) + '</span></div>';
        summary.innerHTML =
            '<div class="card card-pad bk-summary">' +
                '<h3>Booking computation</h3>' +
                '<p class="bk-sum-hint">Recalculated live as you pick rooms, dates, guests and services.</p>' +
                '<div class="bk-sum-section">Room charges × ' + (okDates ? rows[0].nights : '—') +
                    ' night' + ((okDates && rows[0].nights === 1) ? '' : 's') + '</div>' +                 roomHtml +
                servicesSection +
                '<div class="bk-sum-total"><span>Grand total</span><b>' + fmt(grand) + '</b></div>' +
            '</div>';
    }

    function updateGuestTotals(rows) {
        rows.forEach(function (r, i) {
            var el = document.querySelector('[data-guest-total="' + i + '"]');
            if (el) el.innerHTML = r.guests + ' <small class="meta">of ' + r.s.max_guests + ' max</small>';
        });
    }

    function validateAll() {
        var errs = [];
        SELECTED.forEach(function (s, i) {
            var g = s.guest;
            var msgs = [];
            if (g.first_name.trim() === '' || g.last_name.trim() === '' ||
                g.email.trim() === '' || g.contact.trim() === '' ||
                (g.adults + g.children) < 1) {
                msgs.push('Please complete the required guest information for Room ' + (i + 1) + '.');
            }
            if (g.email.trim() !== '' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(g.email.trim())) {
                msgs.push('Enter a valid email for Room ' + (i + 1) + '.');
            }
            if (g.contact.trim() !== '' && /\D/.test(g.contact.trim())) {
                msgs.push('Contact number for Room ' + (i + 1) + ' must contain numbers only.');
            }
            if ((g.adults + g.children) > s.max_guests) {
                msgs.push('Room ' + (i + 1) + ' (' + s.room_number + ') allows up to ' +
                    s.max_guests + ' guest(s); you entered ' + (g.adults + g.children) + '.');
            }
            if (msgs.length) errs.push({ index: i, msgs: msgs });
        });
        return errs;
    }

    function clearErrors() {
        Array.prototype.forEach.call(document.querySelectorAll('.bk-guest-card'), function (sec) {
            sec.classList.remove('has-error');
            var box = sec.querySelector('.bk-guest-err');
            if (box) box.innerHTML = '';
        });
    }

    function showErrors(errs) {
        clearErrors();
        var firstBad = null;
        var firstBadIdx = -1;
        errs.forEach(function (e) {
            var sec = document.querySelector('[data-guest-section="' + e.index + '"]');
            if (!sec) return;
            sec.classList.add('has-error');
            var box = sec.querySelector('.bk-guest-err');
            if (box) {
                box.innerHTML = '<b>Room ' + (e.index + 1) + '</b><ul style="margin:4px 0 0 16px">' +
                    e.msgs.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join('') + '</ul>';
            }
            if (!firstBad) { firstBad = sec; firstBadIdx = e.index; }
        });
        if (firstBadIdx !== -1) setActive(firstBadIdx);
        if (firstBad && firstBad.scrollIntoView) {
            firstBad.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function renderAll() {
        syncRoomIds();
        renderSections();
        paintCards();
        computeAll();
    }

    /* --------------------------------------------------------- galleries */

    function initGallery(card) {
        var shots = Array.prototype.slice.call(card.querySelectorAll('.rm-shot'));
        if (!shots.length) return;
        var counter = card.querySelector('[data-shot-index]');
        var thumbs = Array.prototype.slice.call(card.querySelectorAll('[data-shot-thumb]'));
        var idx = 0;

        function paint() {
            shots.forEach(function (img, i) { img.classList.toggle('is-active', i === idx); });
            thumbs.forEach(function (t, i) { t.classList.toggle('is-active', i === idx); });
            if (counter) counter.textContent = idx + 1;
        }
        function go(step) {
            idx = (idx + step + shots.length) % shots.length;
            paint();
        }
        var prev = card.querySelector('[data-shot-prev]');
        var next = card.querySelector('[data-shot-next]');
        if (prev) prev.addEventListener('click', function (e) { e.stopPropagation(); go(-1); });
        if (next) next.addEventListener('click', function (e) { e.stopPropagation(); go(1); });
        thumbs.forEach(function (t, i) {
            t.addEventListener('click', function (e) { e.stopPropagation(); idx = i; paint(); });
        });
        paint();
    }

    /* ------------------------------------------------------ details modal */

    function amenityMarkup(list) {
        if (!list || !list.length) return '<p class="rm-modal-text" style="color:var(--slate-500)">Not listed.</p>';
        return '<div class="rm-modal-grid">' + list.map(function (label) {
            return '<span class="rm-amen"><i class="fas fa-check"></i> ' + esc(label) + '</span>';
        }).join('') + '</div>';
    }

    function openDetails(roomId) {
        var d = DETAILS[String(roomId)];
        if (!d || !modal) return;
        modalTitle.textContent = d.name + ' · Room ' + d.room_number;
        modalSub.textContent = d.hotel_name + ' · ' + d.hotel_location + ' · ' + d.status;

        var hero = d.photos.length
            ? '<div class="rm-modal-hero"><img src="' + esc(d.photos[0]) + '" alt="' + esc(d.name) + '"></div>' +
              '<div class="rm-modal-strip">' + d.photos.map(function (src, i) {
                  return '<img src="' + esc(src) + '" alt="Photo ' + (i + 1) + '" data-modal-shot="' + i + '"' +
                      (i === 0 ? ' class="is-active"' : '') + '>';
              }).join('') + '</div>'
            : '<div class="rm-modal-hero"><i class="fas fa-bed"></i></div>';

        var priceRows =
            '<tr><td><b>Per night</b></td><td class="c-price"><b>₱ ' + peso(d.rate) + '</b></td></tr>' +
            '<tr><td>Stay total (' + d.nights + ' night' + (d.nights === 1 ? '' : 's') + ')</td>' +
                '<td class="c-price">₱ ' + peso(d.total) + '</td></tr>' +
            '<tr><td>Extra guest</td><td>' +
                (Number(d.additional_guest_charge) > 0
                    ? '₱ ' + peso(d.additional_guest_charge) + ' per guest, per night'
                    : 'No charge') +
            '</td></tr>' +
            '<tr><td>Payment</td><td>Pay online now or pay when you arrive</td></tr>';

        modalBody.innerHTML =
            hero +
            '<div class="rm-badges">' +
                (d.badges.length
                    ? d.badges.map(function (b) { return '<span class="rm-badge rm-badge-blue"><i class="fas fa-check"></i> ' + esc(b) + '</span>'; }).join('')
                    : '<span class="rm-badge rm-badge-muted">No highlights for this room</span>') +
            '</div>' +
            '<div class="rm-facts">' +
                '<div class="rm-fact"><i class="fas fa-ruler-combined"></i><span><b>' + esc(d.size) + '</b><small>Room size</small></span></div>' +
                '<div class="rm-fact"><i class="fas fa-bed"></i><span><b>' + esc(d.bed) + '</b><small>Bed type</small></span></div>' +
                '<div class="rm-fact"><i class="fas fa-user-group"></i><span><b>Max ' + d.max_guests + ' guests</b><small>' + esc(d.sleeps) + '</small></span></div>' +
                '<div class="rm-fact"><i class="fas fa-star"></i><span><b>' + d.score + ' / 10</b><small>' + esc(d.score_label) + ' · ' + esc(d.score_basis) + '</small></span></div>' +
                '<div class="rm-fact"><i class="fas fa-tag"></i><span><b>₱ ' + peso(d.rate) + '</b><small>Standard nightly rate</small></span></div>' +
                '<div class="rm-fact"><i class="fas fa-id-card"></i><span><b>' + esc(d.room_id) + '</b><small>Room ID</small></span></div>' +
            '</div>' +
            '<div class="rm-modal-sec"><h4>Description</h4><div class="rm-modal-text">' +
                (d.description ? esc(d.description) : '<span style="color:var(--slate-500)">No description provided.</span>') +
            '</div></div>' +
            '<div class="rm-modal-sec"><h4>Room features</h4>' + amenityMarkup(d.features) + '</div>' +
            '<div class="rm-modal-sec"><h4>Property amenities &amp; services</h4>' + amenityMarkup(d.amenities) + '</div>' +
            '<div class="rm-modal-sec"><h4>What you will pay</h4>' +
                '<div class="rm-compare-scroll"><table><tbody>' + priceRows + '</tbody></table></div>' +
            '</div>';

        if (modalFull) modalFull.href = d.detail_url;
        modal.classList.add('open');
        document.body.style.overflow = 'hidden';
        /* Always open on the header + top of the photo. innerHTML is rebuilt
           above, but a previous room may have left the body scrolled, so reset
           it explicitly after the new content is in place. */
        modalBody.scrollTop = 0;
        var closeBtn = modal.querySelector('.rm-modal-x');
        /* preventScroll: a bare focus() can scroll the freshly rebuilt modal to
           the X button, which would hide the top of the photo on open. */
        if (closeBtn) { try { closeBtn.focus({ preventScroll: true }); }
                         catch (err) { closeBtn.focus(); } }
        requestAnimationFrame(function () { modalBody.scrollTop = 0; });

        Array.prototype.forEach.call(modalBody.querySelectorAll('[data-modal-shot]'), function (img) {
            img.addEventListener('click', function () {
                var heroImg = modalBody.querySelector('.rm-modal-hero img');
                if (heroImg) {
                    heroImg.src = img.getAttribute('src');
                }
                Array.prototype.forEach.call(modalBody.querySelectorAll('[data-modal-shot]'), function (o) {
                    o.classList.remove('is-active');
                });
                img.classList.add('is-active');
            });
        });
    }

    function closeDetails() {
        if (!modal) return;
        modal.classList.remove('open');
        document.body.style.overflow = '';
    }

    /* ------------------------------------------------------------- wiring */

    cards.forEach(function (card) {
        var roomId = Number(card.getAttribute('data-room-card'));
        var type = card.getAttribute('data-room-type');
        var bookable = !card.classList.contains('is-unavailable');
        if (!bookable) {
            Array.prototype.forEach.call(
                card.querySelectorAll('[data-room-book]'),
                function (el) { el.disabled = true; }
            );
        }
        initGallery(card);

        if (!bookable) return;

        Array.prototype.forEach.call(card.querySelectorAll('[data-room-book]'), function (b) {
            b.addEventListener('click', function () {
                var wasSelected = findIndex(roomId) !== -1;
                syncFromDom();
                toggleRoom(roomId);
                renderAll();
                // Selecting a room opens the guest information modal straight
                // away; the page never scrolls down to the form.
                if (!wasSelected) {
                    guestOpener = b;
                    openGuestModal(roomId);
                }
            });
        });

        // Reopen the guest information for an already selected room.
        var guestBtn = card.querySelector('.rm-rate-foot [data-guest-open]');
        if (!guestBtn) {
            guestBtn = document.createElement('button');
            guestBtn.type = 'button';
            guestBtn.className = 'rm-btn rm-btn-sm';
            guestBtn.setAttribute('data-guest-open', roomId);
            guestBtn.innerHTML = '<i class="fas fa-user-pen"></i> Guest info';
            guestBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                guestOpener = guestBtn;
                openGuestModal(roomId);
            });
            var foot = card.querySelector('.rm-rate-foot');
            if (foot) foot.appendChild(guestBtn);
        }
        guestBtn.hidden = findIndex(roomId) === -1;

        Array.prototype.forEach.call(card.querySelectorAll('[data-open-details]'), function (btn) {
            btn.addEventListener('click', function (e) { e.stopPropagation(); openDetails(roomId); });
        });
    });

    Array.prototype.forEach.call(document.querySelectorAll('[data-compare-book]'), function (b) {
        b.addEventListener('click', function () {
            var wasSelected = findIndex(Number(b.getAttribute('data-compare-book'))) !== -1;
            syncFromDom();
            var roomId = Number(b.getAttribute('data-compare-book'));
            if (findIndex(roomId) === -1) addRoom(roomId);
            else removeRoom(roomId);
            renderAll();
            // Same behaviour as the card button: modal, not a page scroll.
            if (!wasSelected) {
                guestOpener = b;
                openGuestModal(roomId);
            }
        });
    });

    if (compareToggle && comparePanel) {
        compareToggle.addEventListener('click', function () {
            var open = comparePanel.hidden;
            comparePanel.hidden = !open;
            compareToggle.classList.toggle('is-active', open);
            compareToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }
    var compareClose = document.getElementById('compareClose');
    if (compareClose && comparePanel && compareToggle) {
        compareClose.addEventListener('click', function () {
            comparePanel.hidden = true;
            compareToggle.classList.remove('is-active');
            compareToggle.setAttribute('aria-expanded', 'false');
        });
    }

    if (modal) {
        Array.prototype.forEach.call(modal.querySelectorAll('[data-close-modal]'), function (b) {
            b.addEventListener('click', closeDetails);
        });
        modal.addEventListener('click', function (e) { if (e.target === modal) closeDetails(); });
    }

    // Guest information modal: opened by Select, closed by X / Cancel /
    // backdrop / Escape. It never scrolls the page, and the form inside it keeps
    // the existing per-room field names so the booking submit is unchanged.
    Array.prototype.forEach.call(document.querySelectorAll('[data-guest-close]'), function (b) {
        b.addEventListener('click', function () { closeGuestModal(); });
    });
    if (guestModal) {
        guestModal.addEventListener('click', function (e) {
            if (e.target === guestModal) closeGuestModal();
        });
        guestModal.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab') return;
            var f = modalFocusables(guestModal);
            if (!f.length) return;
            var first = f[0], last = f[f.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        });
    }
    if (guestSave) {
        guestSave.addEventListener('click', function () {
            syncFromDom();
            var errs = validateAll().filter(function (e) { return e.index === ACTIVE; });
            if (errs.length) { showErrors(errs); return; }
            closeGuestModal();
            document.dispatchEvent(new CustomEvent('atrue:hotel-guest-info-complete'));
        });
    }
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (guestModalOpen()) { closeGuestModal(); return; }
        if (modal && modal.classList.contains('open')) closeDetails();
    });

    // Dynamic guest sections: live recompute on input.
    wrap.addEventListener('input', function () {
        if (SELECTED.length) { syncFromDom(); computeAll(); }
    });
    wrap.addEventListener('change', function () {
        if (SELECTED.length) { syncFromDom(); computeAll(); }
    });
    wrap.addEventListener('click', function (e) {
        var tab = e.target.closest('[data-room-tab]');
        if (tab) { setActive(Number(tab.getAttribute('data-room-tab'))); return; }
        var rm = e.target.closest('[data-remove-room]');
        if (rm) { syncFromDom(); removeRoom(rm.getAttribute('data-remove-room')); renderAll(); }
    });
    wrap.addEventListener('keydown', function (e) {
        if (!SELECTED.length || SELECTED.length < 2) return;
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' &&
            e.key !== 'Home' && e.key !== 'End') return;
        if (!e.target.closest('[data-room-tab]')) return;
        e.preventDefault();
        var next = ACTIVE;
        if (e.key === 'ArrowRight') next = (ACTIVE + 1) % SELECTED.length;
        else if (e.key === 'ArrowLeft') next = (ACTIVE - 1 + SELECTED.length) % SELECTED.length;
        else if (e.key === 'Home') next = 0;
        else next = SELECTED.length - 1;
        setActive(next);
        var t = wrap.querySelector('[data-room-tab="' + next + '"]');
        if (t) t.focus();
    });

    form.addEventListener('submit', function (e) {
        if (!SELECTED.length) { e.preventDefault(); return; }
        syncFromDom();
        var errs = validateAll();
        if (errs.length) {
            e.preventDefault();
            showErrors(errs);
            return;
        }
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Booking...';
    });

    // Seed from the server-side prefill (validation-error re-render).
    PRESELECTED.forEach(function (p) {
        if (findIndex(p.room_id) === -1) {
            addRoom(p.room_id);
            var entry = SELECTED[SELECTED.length - 1];
            entry.room_number = p.room_number;
            entry.room_type = p.room_type;
            entry.rate = Number(p.rate);
            entry.capacity = Number(p.capacity);
            entry.max_guests = Number(p.max_guests);
            entry.additional_charge = Number(p.additional_charge);
            entry.guest = {
                first_name: (p.guest && p.guest.first_name) || '',
                middle_name: (p.guest && p.guest.middle_name) || '',
                last_name: (p.guest && p.guest.last_name) || '',
                email: (p.guest && p.guest.email) || '',
                contact: (p.guest && p.guest.contact) || '',
                adults: Number((p.guest && p.guest.adults) || 1),
                children: Number((p.guest && p.guest.children) || 0),
                special_request: (p.guest && p.guest.special_request) || ''
            };
            entry.services = (p.services || []).map(Number);
            entry.amenities = (p.amenities || []).map(Number);
        }
    });

    renderAll();
})();

