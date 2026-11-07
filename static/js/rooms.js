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
    var PRESELECTED = readJson('preselected', []);
    var PRIMARY_GUEST = readJson('primaryGuest', {});
    // Large optional datasets are parsed only when the guest opens the
    // corresponding extras or room details. Parsing every room photo/details
    // payload during startup made the selection page unresponsive on slower
    // devices even when the guest only wanted to choose a room.
    var SERVICES = null;
    var AMENITIES = null;
    var DETAILS = null;

    function servicesData() {
        if (SERVICES === null) SERVICES = readJson('servicesData', {});
        return SERVICES;
    }

    function amenitiesData() {
        if (AMENITIES === null) AMENITIES = readJson('amenitiesData', {});
        return AMENITIES;
    }

    function roomDetailsData() {
        if (DETAILS === null) DETAILS = readJson('roomDetails', {});
        return DETAILS;
    }

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
    var modalSelect = document.getElementById('roomModalSelect');
    var roomLightbox = document.getElementById('roomLightbox');
    var roomLightboxImage = document.getElementById('roomLightboxImage');
    var roomLightboxCounter = document.getElementById('roomLightboxCounter');
    var activeModalRoomId = null;
    var activeModalPhotos = [];
    var activePhotoIndex = 0;
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

    // Guest fields are always supplied by the person booking for the customer.
    function primaryReadonly() { return ''; }

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
            guest: SELECTED.length === 0 ? Object.assign(emptyGuest(), PRIMARY_GUEST) : emptyGuest(),
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

    // Refresh the right-hand booking summary as soon as room selection changes.
    function updateRoomSelection(roomId) {
        syncRoomIds();
        var picked = findIndex(roomId) !== -1;
        var card = cardOf(roomId);
        if (card) {
            card.classList.toggle('is-selected', picked);
            var rate = card.querySelector('.rm-rate');
            if (rate) rate.classList.toggle('is-selected', picked);
            Array.prototype.forEach.call(card.querySelectorAll('[data-room-book]'), function (el) {
                el.classList.toggle('is-on', picked);
                el.setAttribute('aria-pressed', picked ? 'true' : 'false');
                el.innerHTML = picked
                    ? '<i class="fas fa-check"></i> Selected'
                    : '<i class="fas fa-circle-check"></i> Select';
            });
            var guestButton = card.querySelector('[data-guest-open]');
            if (guestButton) guestButton.hidden = !picked;
        }
        Array.prototype.forEach.call(document.querySelectorAll('[data-compare-book]'), function (el) {
            if (Number(el.getAttribute('data-compare-book')) !== Number(roomId)) return;
            el.classList.toggle('is-on', picked);
            el.setAttribute('aria-pressed', picked ? 'true' : 'false');
            el.innerHTML = picked
                ? '<i class="fas fa-check"></i> Selected'
                : '<i class="fas fa-circle-check"></i> Select';
        });
        if (roomCountPanel) roomCountPanel.textContent = SELECTED.length + ' selected';
        if (pbRoomsSelected) pbRoomsSelected.textContent = SELECTED.length;
        if (btn) {
            btn.disabled = !SELECTED.length || currentNights() === null;
            btn.innerHTML = SELECTED.length
                ? '<i class="fas fa-bed"></i> BOOK ' + SELECTED.length + ' ROOM' + (SELECTED.length === 1 ? '' : 'S')
                : '<i class="fas fa-bed"></i> Book room(s)';
        }
        syncRoomModalButton();
        computeAll();
    }

    function syncRoomModalButton() {
        if (!modalSelect || activeModalRoomId === null) return;
        var d = roomDetailsData()[String(activeModalRoomId)] || {};
        var selected = findIndex(activeModalRoomId) !== -1;
        modalSelect.disabled = !d.bookable;
        modalSelect.setAttribute('aria-pressed', selected ? 'true' : 'false');
        modalSelect.classList.toggle('is-selected', selected);
        modalSelect.innerHTML = !d.bookable
            ? '<i class="fas fa-ban" aria-hidden="true"></i> Unavailable'
            : selected
                ? '<i class="fas fa-check" aria-hidden="true"></i> Selected · Remove room'
                : '<i class="fas fa-bed" aria-hidden="true"></i> Select Room';
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
        Array.prototype.forEach.call(document.querySelectorAll('[data-compare-book]'), function (el) {
            var picked = findIndex(el.getAttribute('data-compare-book')) !== -1;
            el.classList.toggle('is-on', picked);
            el.setAttribute('aria-pressed', picked ? 'true' : 'false');
            el.innerHTML = picked
                ? '<i class="fas fa-check"></i> Selected'
                : '<i class="fas fa-circle-check"></i> Select';
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
        for (var j = 0; j < cards.length; j++) cards[j].hidden = false;
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
        // Re-render all room forms so every selected room stays visible.
        renderSections();
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
        // Save edits for the currently visible guest before switching rooms.
        syncFromDom();
        ACTIVE = Math.max(0, Math.min(SELECTED.length - 1, idx));
        var s = SELECTED[ACTIVE];
        if (guestModalSub && s) {
            guestModalSub.textContent = SELECTED.length > 1
                ? 'Guest information for all ' + SELECTED.length + ' selected rooms. Room 1 uses your account profile; enter each additional room guest manually.'
                : 'Guest information for this room. Room 1 uses your account profile.';
        }
        // Show the modal immediately as part of the Select click. Every
        // selected room has its own visible guest form in this modal.
        guestModal.classList.add('open');
        document.body.style.overflow = 'hidden';
        renderSections();
        var card = wrap && wrap.querySelector('.bk-guest-card');
        var target = card && card.querySelector(
            'input:not([disabled]):not([readonly]), select:not([disabled]), textarea:not([disabled])'
        );
        if (target) {
            window.requestAnimationFrame(function () {
                if (!guestModalOpen() || !target.isConnected) return;
                try { target.focus({ preventScroll: true }); }
                catch (err) { target.focus(); }
            });
        }
    }

    function closeGuestModal() {
        if (!guestModal || !guestModalOpen()) return;
        syncFromDom();
        guestModal.classList.remove('open');
        if (!modal || !modal.classList.contains('open')) document.body.style.overflow = '';
        computeAll();
        // preventScroll: returning focus must not move the page.
        if (guestOpener && guestOpener.focus) {
            try { guestOpener.focus({ preventScroll: true }); }
            catch (err) { guestOpener.focus(); }
        }
        guestOpener = null;
    }

    function buildSection(s, i) {
        var g = s.guest;
        function extrasBlock(kind, title, count) {
            if (!count) return '';
            var selected = kind === 'services' ? s.services : s.amenities;
            var name = kind === 'services' ? 'services' : 'amenities';
            var selectedInputs = (selected || []).map(function (id) {
                return '<input type="hidden" name="room_' + i + '_' + name + '" value="' + Number(id) + '">';
            }).join('');
            return '<details class="bk-guest-extras" data-room-extras="' + kind + '" data-room-index="' + i + '">' +
                '<summary><b>' + title + '</b> <small class="meta">(' + count + ')</small></summary>' +
                '<div data-extras-options><small class="meta">Open to load options.</small></div></details>' +
                '<div data-room-selected="' + kind + '">' + selectedInputs + '</div>';
        }
        var svcBlock = extrasBlock('services', 'Optional services for Room ' + (i + 1), Number(form.getAttribute('data-service-count') || 0));
        var amnBlock = extrasBlock('amenities', 'Amenities for Room ' + (i + 1), Number(form.getAttribute('data-amenity-count') || 0));
        return '' +
        '<section class="bk-guest-card" id="bkRoomPanel' + i + '" data-guest-section="' + i + '">' +
            '<div class="bk-guest-head">' +
                '<div><span class="badge badge-blue">Room ' + (i + 1) + (i === 0 ? ' — Account Owner' : ' — Additional Guest') + '</span>' +
                '<h3 style="margin:8px 0 2px">' + esc(s.room_type) + ' Room</h3>' +
                '<small>Room ' + esc(s.room_number) + ' · ' + fmt(s.rate) + '/night · Included guests: ' + s.capacity + ' · Max: ' + s.max_guests + (s.additional_charge > 0 ? ' · Extra guest: ' + fmt(s.additional_charge) + '/guest/night' : '') + '</small>' +
                '<p class="meta" style="margin:8px 0 0">' + (i === 0
                    ? 'Guest information is filled from your account profile.'
                    : 'Enter the name and contact information for this room’s guest.') + '</p>' +
                '</div>' +
                '<button type="button" class="bk-remove" data-remove-room="' + s.room_id + '"><i class="fas fa-times"></i> Remove</button>' +
            '</div>' +
            '<div class="bk-guest-grid">' +
                '<div class="form-group"><label>First Name *</label><input name="room_' + i + '_first_name" class="form-input" value="' + esc(g.first_name) + '"' + primaryReadonly(g.first_name, i) + '></div>' +
                '<div class="form-group"><label>Middle Name</label><input name="room_' + i + '_middle_name" class="form-input" value="' + esc(g.middle_name) + '"' + primaryReadonly(g.middle_name, i) + '></div>' +
                '<div class="form-group"><label>Last Name *</label><input name="room_' + i + '_last_name" class="form-input" value="' + esc(g.last_name) + '"' + primaryReadonly(g.last_name, i) + '></div>' +
                '<div class="form-group"><label>Email *</label><input type="email" name="room_' + i + '_email" class="form-input" value="' + esc(g.email) + '"' + primaryReadonly(g.email, i) + '></div>' +
                '<div class="form-group"><label>Contact Number *</label><input type="text" name="room_' + i + '_contact" class="form-input" value="' + esc(g.contact) + '"' + primaryReadonly(g.contact, i) + ' inputmode="numeric" pattern="[0-9]*" maxlength="20" autocomplete="off" oninput="this.value=this.value.replace(/\\D/g,\'\')" title="Numbers only"></div>' +
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
        wrap.innerHTML = tabsMarkup() + SELECTED.map(function (room, index) {
            return buildSection(room, index);
        }).join('');
        Array.prototype.forEach.call(wrap.querySelectorAll('[data-room-extras]'), function (details) {
            function loadOptions() {
                if (details.dataset.loaded === 'true') return;
                details.dataset.loaded = 'true';
                var index = Number(details.getAttribute('data-room-index'));
                var selected = SELECTED[index];
                var kind = details.getAttribute('data-room-extras');
                var target = details.querySelector('[data-extras-options]');
                if (!selected || !target) return;
                var data = kind === 'services' ? servicesData() : amenitiesData();
                var name = kind === 'services' ? 'services' : 'amenities';
                target.innerHTML = Object.keys(data).map(function (id) {
                    var item = data[id];
                    var checked = selected[name].indexOf(Number(id)) !== -1 ? ' checked' : '';
                    var label = kind === 'services'
                        ? esc(item.name) + ' (+₱ ' + esc(item.rate) + ')'
                        : esc(item.name);
                    return '<label class="checkbox"><input type="checkbox" name="room_' + index + '_' + name + '" value="' + id + '"' + checked + '> ' + label + '</label>';
                }).join('');
                var selectedInputs = details.parentElement.querySelector('[data-room-selected="' + kind + '"]');
                if (selectedInputs) selectedInputs.remove();
                if (form && form.id) {
                    Array.prototype.forEach.call(target.querySelectorAll('input'), function (input) {
                        input.setAttribute('form', form.id);
                    });
                }
            }
            details.addEventListener('toggle', function () {
                if (details.open) loadOptions();
            });
            if (details.open) loadOptions();
        });
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
            var servicesBlock = sec.querySelector('[data-room-extras="services"]');
            var amenitiesBlock = sec.querySelector('[data-room-extras="amenities"]');
            if (!servicesBlock || servicesBlock.dataset.loaded === 'true') s.services = checked('services');
            if (!amenitiesBlock || amenitiesBlock.dataset.loaded === 'true') s.amenities = checked('amenities');
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
            var serviceData = s.services.length ? servicesData() : {};
            var svcTotal = s.services.reduce(function (a, id) {
                var svc = serviceData[String(id)];
                return a + (svc ? Number(svc.rate) : 0);
            }, 0);
            var svcNames = s.services.map(function (id) {
                var svc = serviceData[String(id)];
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
            : '<i class="fas fa-bed"></i> REVIEW &amp; PAY (' + SELECTED.length + ' ROOM' + (SELECTED.length === 1 ? '' : 'S') + ')';
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
        if (errs.length) setActive(errs[0].index);
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
        if (firstBad && firstBad.scrollIntoView) {
            firstBad.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function renderAll() {
        syncRoomIds();
        if (guestModalOpen()) renderSections();
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

    function amenityMarkup(list, className) {
        if (!list || !list.length) return '<p class="rmd-empty">No amenities listed for this room.</p>';
        return '<div class="rmd-amenities-grid ' + (className || '') + '">' + list.map(function (item) {
            var label = typeof item === 'string' ? item : item.label;
            var icon = typeof item === 'string' ? 'fa-check' : (item.icon || 'fa-check');
            return '<span class="rmd-amenity"><i class="fas ' + esc(icon) + '" aria-hidden="true"></i>' + esc(label) + '</span>';
        }).join('') + '</div>';
    }

    function paintRoomPhoto(index) {
        if (!activeModalPhotos.length) return;
        activePhotoIndex = (index + activeModalPhotos.length) % activeModalPhotos.length;
        var hero = modalBody.querySelector('[data-room-hero-image]');
        if (hero) hero.src = activeModalPhotos[activePhotoIndex];
        var count = modalBody.querySelector('[data-room-photo-count]');
        if (count) count.textContent = (activePhotoIndex + 1) + ' / ' + activeModalPhotos.length;
        Array.prototype.forEach.call(modalBody.querySelectorAll('[data-room-thumb]'), function (thumb) {
            var active = Number(thumb.getAttribute('data-room-thumb')) === activePhotoIndex;
            thumb.classList.toggle('is-active', active);
            if (active) thumb.setAttribute('aria-current', 'true');
            else thumb.removeAttribute('aria-current');
        });
        if (roomLightbox && !roomLightbox.hidden) {
            roomLightboxImage.src = activeModalPhotos[activePhotoIndex];
            roomLightboxCounter.textContent = (activePhotoIndex + 1) + ' / ' + activeModalPhotos.length;
        }
    }

    function openRoomLightbox(index) {
        if (!roomLightbox || !activeModalPhotos.length) return;
        paintRoomPhoto(index);
        roomLightbox.hidden = false;
        document.body.classList.add('rm-lightbox-open');
        var closeButton = roomLightbox.querySelector('[data-lightbox-close]');
        if (closeButton) closeButton.focus({ preventScroll: true });
    }

    function closeRoomLightbox() {
        if (!roomLightbox) return;
        roomLightbox.hidden = true;
        document.body.classList.remove('rm-lightbox-open');
    }

    function openDetails(roomId) {
        var d = roomDetailsData()[String(roomId)];
        if (!d || !modal) return;
        activeModalRoomId = roomId;
        activeModalPhotos = Array.isArray(d.photos) ? d.photos : [];
        activePhotoIndex = 0;
        modalTitle.textContent = d.name + ' · Room ' + d.room_number;
        modalSub.textContent = [d.hotel_name, d.hotel_location, d.status].filter(Boolean).join(' · ');

        var gallery = activeModalPhotos.length
            ? '<div class="rmd-gallery">' +
                '<button type="button" class="rmd-main-photo" data-room-open-lightbox aria-label="Open room photo gallery">' +
                    '<img data-room-hero-image src="' + esc(activeModalPhotos[0]) + '" alt="' + esc(d.name) + ' room photo" loading="eager">' +
                    '<span class="rmd-photo-count" data-room-photo-count>1 / ' + activeModalPhotos.length + '</span>' +
                '</button>' +
                (activeModalPhotos.length > 1 ? '<button type="button" class="rmd-gallery-arrow rmd-gallery-prev" data-room-photo-prev aria-label="Previous photo"><i class="fas fa-chevron-left"></i></button>' +
                    '<button type="button" class="rmd-gallery-arrow rmd-gallery-next" data-room-photo-next aria-label="Next photo"><i class="fas fa-chevron-right"></i></button>' : '') +
                '<div class="rmd-thumbs">' + activeModalPhotos.slice(0, 4).map(function (src, i) {
                    var remaining = activeModalPhotos.length - 4;
                    return '<button type="button" class="rmd-thumb' + (i === 0 ? ' is-active' : '') + '" data-room-thumb="' + i + '" aria-label="Show photo ' + (i + 1) + '">' +
                        '<img src="' + esc(src) + '" alt="" loading="lazy">' +
                        (i === 3 && remaining > 0 ? '<span>+' + remaining + ' photos</span>' : '') + '</button>';
                }).join('') + '</div></div>'
            : '<div class="rmd-no-photo"><i class="fas fa-bed" aria-hidden="true"></i><span>No room photos available</span></div>';

        var overview = [
            ['fa-ruler-combined', d.size || 'Not specified', 'Room size'],
            ['fa-bed', d.bed || 'Not specified', d.bed_count ? d.bed_count + ' bed' + (d.bed_count === 1 ? '' : 's') : 'Bed type'],
            ['fa-user-group', 'Up to ' + d.max_guests, d.sleeps || 'Guest capacity'],
            ['fa-eye', d.view_type || 'Not specified', 'Room view']
        ];
        var nights = Math.max(1, Number(d.nights) || 1);
        var guests = (Number(d.adults) || 0) + (Number(d.children) || 0);
        var requestedRooms = Math.max(1, Number(d.rooms_requested) || 1);
        var dateLabel = function (iso) {
            if (!iso) return 'Not selected';
            var date = new Date(iso + 'T00:00:00');
            return isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
        };
        var amenities = (d.amenities || []).filter(function (item) {
            return typeof item === 'string' || item.source === 'hotel';
        });
        var compactAmenities = amenities.slice(0, 8);
        var amenityMore = amenities.length > 8
            ? '<button class="rmd-text-button" type="button" data-room-amenity-toggle>View all ' + amenities.length + ' amenities</button>' : '';
        var guestFee = Number(d.extra_guest_charge) > 0
            ? '<div class="rmd-price-note">Extra guest charge: ₱ ' + peso(d.extra_guest_charge) + ' per guest, per night.</div>' : '';

        modalBody.innerHTML = '<div class="rmd-layout"><div class="rmd-main-column">' + gallery +
            '<section class="rmd-section rmd-overview"><h4>Room overview</h4><div class="rmd-overview-grid">' + overview.map(function (item) {
                return '<div class="rmd-overview-item"><i class="fas ' + item[0] + '" aria-hidden="true"></i><span><b>' + esc(item[1]) + '</b><small>' + esc(item[2]) + '</small></span></div>';
            }).join('') + '</div></section>' +
            '<section class="rmd-section"><h4>About this room</h4><p class="rmd-description">' + esc(d.description || 'No room description has been provided.') + '</p></section>' +
            (d.features && d.features.length ? '<section class="rmd-section"><h4>Room features</h4>' + amenityMarkup(d.features) + '</section>' : '') +
            '<section class="rmd-section"><h4>Property amenities &amp; services</h4><div data-room-amenities-collapsed>' + amenityMarkup(compactAmenities) + '</div>' +
                (amenityMore ? '<div data-room-amenities-expanded hidden>' + amenityMarkup(amenities) + '</div>' + amenityMore : '') + '</section>' +
            '</div><aside class="rmd-booking-card"><div class="rmd-booking-top"><span>Room rate</span><div><b>₱ ' + peso(d.rate) + '</b><small>per night</small></div></div>' +
            '<div class="rmd-booking-dates"><div><small>Check-in</small><b>' + esc(dateLabel(d.check_in)) + '</b></div><i class="fas fa-arrow-right" aria-hidden="true"></i><div><small>Check-out</small><b>' + esc(dateLabel(d.check_out)) + '</b></div></div>' +
            '<div class="rmd-booking-row"><span>Length of stay</span><b>' + nights + ' night' + (nights === 1 ? '' : 's') + '</b></div>' +
            '<div class="rmd-booking-row"><span>Guests</span><b>' + guests + ' guest' + (guests === 1 ? '' : 's') + '</b></div>' +
            '<div class="rmd-booking-row"><span>Rooms requested</span><b>' + requestedRooms + '</b></div>' +
            '<div class="rmd-booking-divider"></div><div class="rmd-booking-row"><span>Room subtotal</span><b>₱ ' + peso(d.total) + '</b></div>' + guestFee +
            '<p class="rmd-booking-disclaimer">Room subtotal is based on the displayed nightly rate and stay length. Any applicable extra guest charge is calculated from the guest details you provide.</p>' +
            '<a class="rmd-full-details" href="' + esc(d.detail_url || '#') + '">View full room details <i class="fas fa-arrow-up-right-from-square"></i></a></aside></div>';

        if (modalSelect) syncRoomModalButton();
        modal.classList.add('open');
        document.body.style.overflow = 'hidden';
        modalBody.scrollTop = 0;
        var closeBtn = modal.querySelector('.rm-modal-x');
        if (closeBtn) { try { closeBtn.focus({ preventScroll: true }); } catch (err) { closeBtn.focus(); } }
        requestAnimationFrame(function () { modalBody.scrollTop = 0; });
        Array.prototype.forEach.call(modalBody.querySelectorAll('[data-room-thumb]'), function (thumb) {
            thumb.addEventListener('click', function () { paintRoomPhoto(Number(thumb.getAttribute('data-room-thumb'))); });
        });
        var prev = modalBody.querySelector('[data-room-photo-prev]');
        var next = modalBody.querySelector('[data-room-photo-next]');
        var openGallery = modalBody.querySelector('[data-room-open-lightbox]');
        if (prev) prev.addEventListener('click', function () { paintRoomPhoto(activePhotoIndex - 1); });
        if (next) next.addEventListener('click', function () { paintRoomPhoto(activePhotoIndex + 1); });
        if (openGallery) openGallery.addEventListener('click', function () { openRoomLightbox(activePhotoIndex); });
        var more = modalBody.querySelector('[data-room-amenity-toggle]');
        if (more) more.addEventListener('click', function () {
            var collapsed = modalBody.querySelector('[data-room-amenities-collapsed]');
            var expanded = modalBody.querySelector('[data-room-amenities-expanded]');
            var showAll = expanded.hidden;
            expanded.hidden = !showAll;
            collapsed.hidden = showAll;
            more.textContent = showAll ? 'Show fewer amenities' : 'View all ' + amenities.length + ' amenities';
        });
    }

    function closeDetails() {
        if (!modal) return;
        closeRoomLightbox();
        modal.classList.remove('open');
        document.body.style.overflow = '';
        activeModalRoomId = null;
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
                if (guestModalOpen()) syncFromDom();
                // Match the resort picker: the selection control toggles the
                // room in and out, while Guest info stays a separate action.
                if (findIndex(roomId) !== -1) removeRoom(roomId);
                else addRoom(roomId);
                updateRoomSelection(roomId);
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
            var roomId = Number(b.getAttribute('data-compare-book'));
            if (guestModalOpen()) syncFromDom();
            if (findIndex(roomId) !== -1) removeRoom(roomId);
            else addRoom(roomId);
            updateRoomSelection(roomId);
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
    if (modalSelect) {
        modalSelect.addEventListener('click', function () {
            if (activeModalRoomId === null) return;
            var d = roomDetailsData()[String(activeModalRoomId)] || {};
            if (!d.bookable) return;
            var card = cardOf(activeModalRoomId);
            var selectButton = card && card.querySelector('[data-room-book]');
            if (selectButton && !selectButton.disabled) {
                selectButton.click();
                closeDetails();
            }
        });
    }
    if (roomLightbox) {
        var lightboxClose = roomLightbox.querySelector('[data-lightbox-close]');
        var lightboxPrev = roomLightbox.querySelector('[data-lightbox-prev]');
        var lightboxNext = roomLightbox.querySelector('[data-lightbox-next]');
        if (lightboxClose) lightboxClose.addEventListener('click', closeRoomLightbox);
        if (lightboxPrev) lightboxPrev.addEventListener('click', function () { paintRoomPhoto(activePhotoIndex - 1); });
        if (lightboxNext) lightboxNext.addEventListener('click', function () { paintRoomPhoto(activePhotoIndex + 1); });
        roomLightbox.addEventListener('click', function (e) { if (e.target === roomLightbox) closeRoomLightbox(); });
    }

    // Guest information modal: opened by Guest info, closed by X / Cancel /
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
            var errs = validateAll();
            if (errs.length) { showErrors(errs); return; }
            // Saving guest details submits the server form; Django persists the
            // booking and sends the student straight to its review page.
            if (form.requestSubmit) form.requestSubmit();
        });
    }
    document.addEventListener('keydown', function (e) {
        if (roomLightbox && !roomLightbox.hidden) {
            if (e.key === 'Escape') { closeRoomLightbox(); return; }
            if (e.key === 'ArrowLeft') { paintRoomPhoto(activePhotoIndex - 1); return; }
            if (e.key === 'ArrowRight') { paintRoomPhoto(activePhotoIndex + 1); return; }
        }
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
            openGuestModal(SELECTED[errs[0].index].room_id);
            showErrors(errs);
            return;
        }
        // Trigger summary step before submitting
        document.dispatchEvent(new CustomEvent('atrue:hotel-guest-info-complete'));
        // Don't disable immediately if we want summary to show first
        // btn.disabled = true;
        // btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Opening payment...';
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

