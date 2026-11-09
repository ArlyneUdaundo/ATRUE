/* ==========================================================================
   ATRUE — Passenger Details prototype
   All behaviour for the passenger-details page lives here: the shared booking
   state, dynamic passenger forms, the domestic/international toggle, the seat
   map, baggage and insurance selections, the live fare summary and the review
   step. Vanilla JS, one IIFE, no dependencies.

   Nothing here books a flight or takes payment: confirming details creates a
   session-backed ticket preview for the current simulation only.
   ========================================================================== */
(function () {
    'use strict';

    var root = document.querySelector('[data-pd-root]');
    if (!root) { return; }

    // ------------------------------------------------------------ state --
    var fareData = readJSON('pd-fare-data');
    var seatData = readJSON('pd-seat-data');
    var cabinSeatMaps = readJSON('pd-cabin-seat-data');
    var flightData = readJSON('pd-selected-flight-data');

    var state = {
        flightType: (root.dataset.defaultFlightType || 'DOMESTIC').toUpperCase(),
        counts: { adult: 1, child: 0, infant: 0 },
        passengers: [],
        seats: {},
        baggageKg: 0,
        baggagePrice: 0,
        fareClassKey: root.dataset.fareClassKey || flightData.fare_class_key || 'ECONOMY',
        insuranceKey: 'none',
        insurancePrice: 0,
        policyAck: false
    };

    var CATEGORY_ORDER = ['adult', 'child', 'infant'];
    var MAX = {
        adult: Number(fareData.max_adults) || 9,
        child: Number(fareData.max_children) || 6,
        infant: Number(fareData.max_infants) || 4
    };
    var BASE_FARE = Number(root.dataset.baseFare) || 0;
    var TAX_PER_PAX = Number(root.dataset.taxesPerPassenger) || 0;
    var BAGGAGE_BASIS = root.dataset.baggageBasis || 'per_passenger';
    var INSURANCE_BASIS = root.dataset.insuranceBasis || 'per_passenger';
    var SEATABLE = { adult: true, child: true, infant: false };

    // Seat categories and their prices come from the page's own pricing data,
    // so the picker, the summary and the fare total always agree.
    var SEAT_TYPES = {};
    (fareData.seat_types || []).forEach(function (entry) {
        SEAT_TYPES[entry.key] = { label: entry.label, price: Number(entry.price) || 0 };
    });

    var $ = function (sel, scope) { return (scope || root).querySelector(sel); };
    var $$ = function (sel, scope) { return Array.prototype.slice.call((scope || root).querySelectorAll(sel)); };

    function readJSON(id) {
        var el = document.getElementById(id);
        if (!el) { return {}; }
        try { return JSON.parse(el.textContent); } catch (err) { return {}; }
    }

    function money(value) {
        var amount = Number(value || 0);
        var currency = root.dataset.currency || 'PHP';
        if (currency === 'PHP') {
            return '\u20b1' + amount.toLocaleString('en-PH', {
                minimumFractionDigits: 2, maximumFractionDigits: 2
            });
        }
        return new Intl.NumberFormat(undefined, {
            style: 'currency', currency: currency, minimumFractionDigits: 2
        }).format(amount);
    }

    // --------------------------------------------------- passenger totals --
    function totalPassengers() {
        return CATEGORY_ORDER.reduce(function (sum, key) { return sum + state.counts[key]; }, 0);
    }
    function seatablePassengers() {
        return state.passengers.filter(function (p) { return SEATABLE[p.category]; });
    }

    // ----------------------------------------------------- passenger list --
    function countOf(category) {
        return state.passengers.filter(function (p) { return p.category === category; }).length;
    }

    function rebuildPassengers() {
        // The passenger list is the source of truth; the counters read from it.
        CATEGORY_ORDER.forEach(function (category) {
            state.counts[category] = countOf(category);
        });
        state.passengers.forEach(function (pax, index) { pax.number = index + 1; });

        // Drop seat assignments that no longer belong to anyone.
        var stillUsed = {};
        state.passengers.forEach(function (pax) {
            if (pax.seat && SEATABLE[pax.category] && !stillUsed[pax.seat]) {
                stillUsed[pax.seat] = true;
            } else if (pax.seat) {
                delete pax.seat;
            }
        });
        state.seats = stillUsed;

        // A passenger who no longer sits keeps no seat, and the seat list on
        // the modal must follow.
        renderPassengerForms();
        renderSeatPanel();
        renderSeatSummary();
        syncCountInputs();
        updateFare();
        updateContinueAvailability();
    }

    function addPassenger(category) {
        state.passengers.push({ category: category, number: state.passengers.length + 1 });
    }

    function removePassengerAt(index) {
        var pax = state.passengers[index];
        if (!pax) { return; }
        // A booking always keeps at least one adult, so the last one cannot go.
        if (pax.category === 'adult' && countOf('adult') <= 1) { return; }
        state.passengers.splice(index, 1);
        // Never more infants than adults: drop the surplus infants too.
        while (countOf('infant') > countOf('adult')) {
            for (var j = state.passengers.length - 1; j >= 0; j -= 1) {
                if (state.passengers[j].category === 'infant') {
                    state.passengers.splice(j, 1);
                    break;
                }
            }
        }
        rebuildPassengers();
    }

    function renderPassengerForms() {
        var host = $('#pd-passengers');
        var template = document.getElementById('pd-pax-template');
        host.innerHTML = '';
        state.passengers.forEach(function (pax, index) {
            var node = template.content.firstElementChild.cloneNode(true);
            node.setAttribute('data-pd-index', String(index));
            node.dataset.pdCategory = pax.category;
            setText($('[data-pd-pax-label]', node), String(index + 1));
            var catLabel = categoryLabel(pax.category);
            setText($('[data-pd-pax-cat]', node), catLabel);
            // Rewrite name attributes so posted data would be per passenger.
            $$('[name]', node).forEach(function (field) {
                field.name = field.name.replace('__INDEX__', String(index));
            });
            var removeBtn = $('[data-pd-remove]', node);
            // Only offer to remove a traveller when that really removes one:
            // a lone adult stays, because a booking always keeps an adult.
            var canRemove = pax.category === 'adult'
                ? state.counts.adult > 1
                : state.counts[pax.category] > 0;
            removeBtn.hidden = !canRemove;
            removeBtn.setAttribute('data-pd-remove', String(index));
            // Restore values.
            if (pax.values) {
                Object.keys(pax.values).forEach(function (key) {
                    var field = $('[data-pd-field="' + key + '"]', node);
                    if (field) { field.value = pax.values[key]; }
                });
            }
            bindPassengerFields(node, index);
            host.appendChild(node);
        });
        applyFlightTypeToForms();
        renderPassengerSeatLabels();
    }

    function categoryLabel(key) {
        for (var i = 0; i < fareData.passenger_categories.length; i += 1) {
            if (fareData.passenger_categories[i].key === key) {
                return fareData.passenger_categories[i].label;
            }
        }
        return 'Passenger';
    }

    function bindPassengerFields(node, index) {
        $$('[data-pd-field]', node).forEach(function (field) {
            if (field.getAttribute('data-pd-field') === 'classification') {
                field.addEventListener('change', function () {
                    var pax = state.passengers[index];
                    if (pax) { pax.classificationTouched = true; }
                    captureValues(index, node);
                    clearFieldError(field);
                    updateContinueAvailability();
                });
                return;
            }
            if (field.getAttribute('data-pd-field') === 'phone') {
                field.addEventListener('input', function () {
                    field.value = field.value.replace(/[^0-9]/g, '').slice(0, 11);
                    captureValues(index, node);
                    clearFieldError(field);
                });
                field.addEventListener('change', function () {
                    field.value = field.value.replace(/[^0-9]/g, '').slice(0, 11);
                    captureValues(index, node);
                    clearFieldError(field);
                });
            } else {
                field.addEventListener('input', function () { captureValues(index, node); clearFieldError(field); });
                field.addEventListener('change', function () {
                    captureValues(index, node);
                    clearFieldError(field);
                    if (field.getAttribute('data-pd-field') === 'dob') { suggestPassengerClassification(index, node); }
                    updateContinueAvailability();
                });
            }
        });
    }

    function captureValues(index, node) {
        var pax = state.passengers[index];
        if (!pax) { return; }
        pax.values = pax.values || {};
        $$('[data-pd-field]', node).forEach(function (field) {
            pax.values[field.getAttribute('data-pd-field')] = field.value;
        });
        var nameParts = [pax.values.first_name, pax.values.middle_name, pax.values.last_name]
            .map(function (part) { return (part || '').trim(); }).filter(Boolean);
        pax.values.full_name = nameParts.join(' ');
        var fullName = $('[data-pd-field="full_name"]', node);
        if (fullName) { fullName.value = pax.values.full_name; }
        // Keep the open seat picker in sync as the traveller enters their name.
        renderSeatPanel();
        updateFare();
        updateContinueAvailability();
    }

    function suggestPassengerClassification(index, node) {
        var pax = state.passengers[index];
        var dob = $('[data-pd-field="dob"]', node);
        var select = $('[data-pd-classification]', node);
        if (!pax || !dob || !dob.value || !select || pax.classificationTouched) { return; }
        var born = new Date(dob.value + 'T00:00:00');
        var travel = new Date((root.dataset.departureDate || new Date().toISOString().slice(0, 10)) + 'T00:00:00');
        var age = travel.getFullYear() - born.getFullYear();
        if (travel.getMonth() < born.getMonth() ||
            (travel.getMonth() === born.getMonth() && travel.getDate() < born.getDate())) { age -= 1; }
        if (age < 0) { return; }
        var suggested = age < 2 ? 'infant' : (age < 12 ? 'child' : (age >= 60 ? 'senior' : 'adult'));
        select.value = suggested;
        pax.values = pax.values || {};
        pax.values.classification = suggested;
        setText($('[data-pd-classification-hint]', node), 'Suggested from age ' + age + ' on the travel date. You can change this selection.');
        updateFare();
        updateContinueAvailability();
    }

    function passengerDisplayName(pax, index) {
        var fullName = pax && pax.values && pax.values.full_name;
        return fullName && fullName.trim() ? fullName.trim() : 'Passenger ' + (index + 1);
    }

    function renderPassengerSeatLabels() {
        state.passengers.forEach(function (pax, index) {
            var node = $('[data-pd-index="' + index + '"]');
            if (!node) { return; }
            var target = $('[data-pd-pax-seat-value]', node);
            if (target) { setText(target, pax.seat || 'Not selected'); }
        });
    }

    function setText(el, text) { if (el) { el.textContent = text; } }

    // ------------------------------------------------------- flight type --
    function applyFlightTypeToForms() {
        var international = state.flightType === 'INTERNATIONAL';
        state.passengers.forEach(function (pax, index) {
            var node = $('[data-pd-index="' + index + '"]');
            if (!node) { return; }
            [['passport', '[data-pd-passport]'], ['passport_country', '[data-pd-passport-country]'],
                ['passport_expiry', '[data-pd-passport-expiry]']].forEach(function (entry) {
                var wrapper = $(entry[1], node);
                var input = $('[data-pd-field="' + entry[0] + '"]', node);
                if (wrapper) { wrapper.hidden = !international; }
                if (input) {
                    input.required = international;
                    input.setAttribute('aria-required', international ? 'true' : 'false');
                }
                if (!international) { clearFieldError(input); }
            });
        });
        var note = $('[data-pd-flight-type-note]');
        if (note) {
            setText(note, international
                ? 'Passport number, issuing country and expiry are required for international flights.'
                : 'Passport information is not required for domestic flights.');
        }
    }

    function setFlightType(value) {
        state.flightType = value;
        $$('input[name="flight_type"]').forEach(function (input) {
            input.checked = input.value === value;
        });
        applyFlightTypeToForms();
    }

    // ---------------------------------------------------- passenger count --
    function adjustCount(key, delta) {
        setCount(key, countOf(key) + delta);
    }

    function setCount(key, value) {
        var max = MAX[key] || 9;
        var min = key === 'adult' ? 1 : 0;
        value = Math.max(min, Math.min(max, Number(value) || 0));
        if (key === 'infant') { value = Math.min(value, countOf('adult')); }
        var current = countOf(key);
        if (value === current) { return; }
        if (value < current) {
            // Shrink from the end of this category, so the people already at
            // the top of the list keep their details and their seats.
            for (var i = state.passengers.length - 1; i >= 0 && countOf(key) > value; i -= 1) {
                if (state.passengers[i].category === key) {
                    state.passengers.splice(i, 1);
                }
            }
        } else {
            for (var j = current; j < value; j += 1) { addPassenger(key); }
        }
        rebuildPassengers();
    }

    function syncCountInputs() {
        CATEGORY_ORDER.forEach(function (key) {
            var input = $('[data-pd-count="' + key + '"]');
            if (input) { input.value = state.counts[key]; }
        });
        var total = $('[data-pd-pax-total]');
        if (total) { setText(total, String(totalPassengers())); }
    }

    // --------------------------------------------------------------- seats --
    function openSeatModal() {
        if (seatablePassengers().length === 0) {
            return;
        }
        activePaxIndex = firstUnseatedIndex();
        renderSeatPanel();
        paintSeatGrid();
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
    }

    function closeSeatModal() {
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    }

    var activePaxIndex = 0;

    function firstUnseatedIndex() {
        for (var i = 0; i < state.passengers.length; i += 1) {
            if (SEATABLE[state.passengers[i].category] && !state.passengers[i].seat) { return i; }
        }
        for (var j = 0; j < state.passengers.length; j += 1) {
            if (SEATABLE[state.passengers[j].category]) { return j; }
        }
        return 0;
    }

    function seatOwner(seatNumber) {
        for (var i = 0; i < state.passengers.length; i += 1) {
            if (state.passengers[i].seat === seatNumber) { return i; }
        }
        return -1;
    }

    // The seat's own price and category, read off the seat map so the numbers
    // are the ones the page was rendered with.
    function seatInfo(seatNumber) {
        if (!seatNumber) { return null; }
        var button = seatGrid ? seatGrid.querySelector('.pd-seat[data-seat="' + seatNumber + '"]') : null;
        if (!button) { return { key: '', label: '', price: 0 }; }
        var key = button.getAttribute('data-category') || '';
        var type = SEAT_TYPES[key];
        var position = button.getAttribute('data-position-label') || '';
        var category = button.getAttribute('data-category-label') || (type ? type.label : '');
        var feature = (key === 'front' || key === 'legroom') ? category : '';
        return {
            key: key,
            label: position + (feature ? ' · ' + feature : ''),
            price: Number(button.getAttribute('data-price')) || (type ? type.price : 0)
        };
    }

    function seatTotal() {
        var total = 0;
        state.passengers.forEach(function (pax) {
            if (!pax.seat || !SEATABLE[pax.category]) { return; }
            var info = seatInfo(pax.seat);
            total += info ? info.price : 0;
        });
        return total;
    }

    function renderSeatPanel() {
        var list = $('[data-pd-seat-pax-list]');
        if (!list) { return; }
        list.innerHTML = '';
        state.passengers.forEach(function (pax, index) {
            if (!SEATABLE[pax.category]) { return; }
            var seat = pax.seat;
            var info = seatInfo(seat);
            var li = document.createElement('li');
            li.className = 'pd-seat-pax' + (index === activePaxIndex ? ' is-active' : '');
            li.setAttribute('data-pd-pick-pax', String(index));
            li.setAttribute('role', 'button');
            li.setAttribute('tabindex', '0');
            li.setAttribute('aria-pressed', index === activePaxIndex ? 'true' : 'false');
            li.innerHTML =
                '<span class="pd-seat-pax__idx">' + (index + 1) + '</span>' +
                '<span class="pd-seat-pax__who">' +
                    '<span class="pd-seat-pax__name">' + escapeHtml(passengerDisplayName(pax, index)) +
                        (index === activePaxIndex ? ' <em>(selecting)</em>' : '') + '</span>' +
                    '<span class="pd-seat-pax__cat">' + escapeHtml(categoryLabel(pax.category)) + '</span>' +
                '</span>' +
                '<span class="pd-seat-pax__seat' + (seat ? '' : ' is-empty') + '">' +
                    (seat ? escapeHtml(seat) : 'No seat yet') +
                    (seat && info && info.label
                        ? ' <em>' + escapeHtml(info.label) + '</em>' : '') +
                '</span>' +
                (seat
                    ? '<button type="button" class="pd-seat-pax__change" data-pd-clear-seat="' + index +
                      '" aria-label="Change the seat for ' + escapeHtml(passengerDisplayName(pax, index)) +
                      '"><i class="fas fa-arrows-rotate" aria-hidden="true"></i> Change</button>'
                    : '');
            li.addEventListener('click', function (event) {
                if (event.target.closest('[data-pd-clear-seat]')) { return; }
                selectActivePax(index);
            });
            li.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectActivePax(index); }
            });
            list.appendChild(li);
        });
        var paxCount = seatablePassengers().length;
        var barCount = $('[data-pd-seat-flightbar-pax]');
        if (barCount) { setText(barCount, String(paxCount)); }
        renderSeatModalSummary();
        updateSeatModalHint();
    }

    function renderDynamicSeatGrid() {
        if (!seatGrid || !seatData || !Array.isArray(seatData.rows)) { return; }
        var head = '<div class="pd-seat-map__headrow"><span class="pd-seat-map__rowno"></span>' +
            (seatData.letters || []).map(function (letter) {
                return '<span class="pd-seat-map__colhead">' + escapeHtml(letter) + '</span>';
            }).join('') + '<span class="pd-seat-map__rowno"></span></div>';
        var rows = seatData.rows.map(function (row) {
            var exit = row.is_exit ? '<div class="pd-seat-map__exit"><i class="fas fa-person-running"></i> Exit row</div>' : '';
            var seats = (row.seats || []).map(function (seat) {
                var position = seat.position || 'middle';
                var category = seat.category || 'standard';
                var disabled = seat.taken ? ' disabled' : '';
                var taken = seat.taken ? ' pd-seat--taken' : '';
                var aisle = seat.aisle_before ? ' pd-seat--aisle-gap' : '';
                var label = 'Seat ' + seat.number + (seat.taken ? ' unavailable' : ' available');
                return '<button type="button" class="pd-seat pd-seat--' + escapeHtml(position) +
                    ' pd-seat--cat-' + escapeHtml(category) + taken + aisle + '" data-seat="' +
                    escapeHtml(seat.number) + '" data-position="' + escapeHtml(position) +
                    '" data-position-label="' + escapeHtml(seat.position_label || 'Seat') +
                    '" data-category="' + escapeHtml(category) + '" data-category-label="' +
                    escapeHtml(seat.category_label || 'Standard seat') + '" data-price="' +
                    (Number(seat.price) || 0) + '"' + disabled + ' aria-label="' + escapeHtml(label) + '">' +
                    '<span class="pd-seat__letter">' + escapeHtml(seat.letter || '') + '</span>' +
                    '<span class="pd-seat__num">' + escapeHtml(seat.number) + '</span></button>';
            }).join('');
            return exit + '<div class="pd-seat-map__row"><span class="pd-seat-map__rowno">' +
                escapeHtml(row.row || '') + '</span>' + seats +
                '<span class="pd-seat-map__rowno pd-seat-map__rowno--right">' +
                escapeHtml(row.row || '') + '</span></div>';
        }).join('');
        seatGrid.innerHTML = head + rows;
    }

    // The summary inside the modal: one line per passenger with the seat, the
    // category and what that seat costs, then the total.
    function renderSeatModalSummary() {
        var list = $('[data-pd-seat-modal-summary]');
        var totalEl = $('[data-pd-seat-modal-total]');
        if (!list) { return; }
        list.innerHTML = '';
        var assigned = state.passengers.filter(function (p) { return p.seat && SEATABLE[p.category]; });
        if (!assigned.length) {
            var empty = document.createElement('li');
            empty.className = 'pd-seat-summary-panel__empty';
            empty.textContent = 'No seats selected yet.';
            list.appendChild(empty);
        } else {
            assigned.forEach(function (pax) {
                var index = state.passengers.indexOf(pax);
                var info = seatInfo(pax.seat);
                var li = document.createElement('li');
                li.className = 'pd-seat-summary-panel__row';
                li.innerHTML =
                    '<span class="pd-seat-summary-panel__who">' + escapeHtml(passengerDisplayName(pax, index)) + '</span>' +
                    '<span class="pd-seat-summary-panel__seat">' + escapeHtml(pax.seat) + '</span>' +
                    '<span class="pd-seat-summary-panel__cat">' + escapeHtml(info ? info.label : '') + '</span>' +
                    '<span class="pd-seat-summary-panel__price">' +
                        money(info ? info.price : 0) + '</span>';
                list.appendChild(li);
            });
        }
        if (totalEl) { setText(totalEl, money(seatTotal())); }
    }

    function selectActivePax(index) {
        activePaxIndex = index;
        renderSeatPanel();
        paintSeatGrid();
    }

    function paintSeatGrid() {
        $$('.pd-seat').forEach(function (button) {
            var seat = button.getAttribute('data-seat');
            var owner = seatOwner(seat);
            button.classList.toggle('pd-seat--selected', owner !== -1);
            if (owner !== -1) {
                button.setAttribute('aria-label', 'Seat ' + seat + ' selected for passenger ' + (owner + 1));
            } else if (!button.disabled) {
            var position = button.getAttribute('data-position-label') || 'Seat';
            var category = button.getAttribute('data-category-label') || '';
            var key = button.getAttribute('data-category') || '';
            var feature = (key === 'front' || key === 'legroom') ? ', ' + category : '';
                var price = Number(button.getAttribute('data-price')) || 0;
            button.setAttribute('aria-label', 'Seat ' + seat + ' available, ' + position + ' seat' + feature + ', ' + money(price));
            }
        });
    }

    // Releases one passenger's seat so a different one can be chosen.
    function clearSeatFor(index) {
        var pax = state.passengers[index];
        if (!pax || !pax.seat) { return; }
        delete pax.seat;
        delete state.seats[pax.seat];
        activePaxIndex = index;
        renderSeatPanel();
        paintSeatGrid();
        renderPassengerSeatLabels();
        setPanelHint('');
    }

    function assignSeat(seatNumber) {
        var pax = state.passengers[activePaxIndex];
        if (!pax || !SEATABLE[pax.category]) { return; }
        var owner = seatOwner(seatNumber);
        if (owner === activePaxIndex) {
            // Clicking your own seat clears it.
            delete pax.seat;
            delete state.seats[seatNumber];
            setPanelHint('');
        } else if (owner !== -1) {
            // The seat belongs to another traveller. It is never handed over
            // silently: that would quietly unseat somebody. Deselect your own
            // seat first if you want to swap.
            setPanelHint('Seat ' + seatNumber + ' is already assigned to passenger ' +
                (owner + 1) + '. Click your own seat again to give it up first.');
            return;
        } else {
            pax.seat = seatNumber;
            state.seats[seatNumber] = true;
            setPanelHint('');
        }
        // Advance to the next unseated passenger.
        var next = -1;
        for (var i = 0; i < state.passengers.length; i += 1) {
            var cand = state.passengers[i];
            if (SEATABLE[cand.category] && !cand.seat) { next = i; break; }
        }
        activePaxIndex = next === -1 ? activePaxIndex : next;
        renderSeatPanel();
        paintSeatGrid();
        renderPassengerSeatLabels();
    }

    function setPanelHint(message) {
        var hint = $('[data-pd-seat-panel-hint]');
        if (!hint) { return; }
        setText(hint, message);
        hint.classList.toggle('pd-field__hint--error', Boolean(message));
    }

    function updateSeatModalHint() {
        var hint = $('[data-pd-seat-modal-hint]');
        if (!hint) { return; }
        var needed = seatablePassengers().length;
        var done = seatablePassengers().filter(function (p) { return p.seat; }).length;
        setText(hint, done + ' of ' + needed + ' seats selected.');
    }

    function confirmSeats() {
        setPanelHint('');
        closeSeatModal();
        renderSeatSummary();
        clearFieldErrorByName('seats');
    }

    function renderSeatSummary() {
        var list = $('[data-pd-seat-summary-list]');
        var empty = $('[data-pd-seat-summary-empty]');
        var hint = $('[data-pd-seat-hint]');
        var details = $('[data-pd-seat-selected-details]');
        if (!list) { return; }
        list.innerHTML = '';
        var assigned = state.passengers.filter(function (p) { return p.seat && SEATABLE[p.category]; });
        if (assigned.length) {
            assigned.forEach(function (pax) {
                var index = state.passengers.indexOf(pax);
                var li = document.createElement('li');
                var number = index + 1;
                li.innerHTML = '<i class="fas fa-couch"></i> Passenger ' + number +
                    ': <b>' + escapeHtml(pax.seat) + '</b>';
                list.appendChild(li);
            });
            if (empty) { empty.hidden = true; }
            list.hidden = false;
            if (details) {
                details.innerHTML = '';
                assigned.forEach(function (pax) {
                    var index = state.passengers.indexOf(pax);
                    var number = index + 1;
                    var info = seatInfo(pax.seat);
                    var p = document.createElement('p');
                    p.className = 'pd-seat-selected__row';
                    p.innerHTML = '<b>Passenger ' + number + '</b> \u2014 Seat ' +
                        escapeHtml(pax.seat) + ', ' + escapeHtml(info ? info.label : 'Seat') +
                        ' \u2014 ' + money(info ? info.price : 0);
                    details.appendChild(p);
                });
                var totalSeats = document.createElement('p');
                totalSeats.className = 'pd-seat-selected__total';
                totalSeats.innerHTML = 'Total Seat Selection \u2014 ' + money(seatTotal());
                details.appendChild(totalSeats);
            }
        } else {
            if (empty) { empty.hidden = false; }
            list.hidden = true;
            if (details) { details.innerHTML = ''; }
        }
        if (hint) {
            var needed = seatablePassengers().length;
            setText(hint, 'Seat selection is optional. Choose seats for up to ' + needed + ' traveller' +
                (needed === 1 ? '' : 's') + '.');
        }
        updateFare();
    }

    // ------------------------------------------------------- fare summary --
    function updateFare() {
        var pax = totalPassengers();
        var base = BASE_FARE * pax;
        var taxes = TAX_PER_PAX * pax;
        var baggage = BAGGAGE_BASIS === 'per_passenger'
            ? state.baggagePrice * pax : state.baggagePrice;
        var insurance = INSURANCE_BASIS === 'per_passenger'
            ? state.insurancePrice * pax : state.insurancePrice;
        var seatTotalAmount = seatTotal();
        var total = base + taxes + baggage + insurance + seatTotalAmount;

        setText($('[data-pd-fare-base]'), money(base));
        setText($('[data-pd-fare-taxes]'), money(taxes));
        setText($('[data-pd-fare-pax]'), String(pax));
        setText($('[data-pd-fare-class-name]'), fareClassLabel(state.fareClassKey));
        setText($('[data-pd-summary-pax]'), pax + (pax === 1 ? ' traveller' : ' travellers'));
        setText($('[data-pd-summary-classifications]'), passengerClassificationSummary());
        setText($('[data-pd-fare-baggage]'), money(baggage));
        setText($('[data-pd-fare-insurance]'), money(insurance));
        setText($('[data-pd-fare-seat]'), money(seatTotalAmount));
        setText($('[data-pd-fare-total]'), money(total));

        setText($('[data-pd-fare-base-note]'), base > 0 ? '(' + money(BASE_FARE) + ' \u00d7 ' + pax + ')' : '');
        setText($('[data-pd-fare-tax-note]'), taxes > 0 ? '(' + money(TAX_PER_PAX) + ' \u00d7 ' + pax + ')' : '');
        setText($('[data-pd-fare-bag-note]'), state.baggagePrice > 0
            ? (BAGGAGE_BASIS === 'per_passenger' ? '(' + money(state.baggagePrice) + ' \u00d7 ' + pax + ')' : '(flat)')
            : '');
        setText($('[data-pd-fare-ins-note]'), state.insurancePrice > 0
            ? (INSURANCE_BASIS === 'per_passenger' ? '(' + money(state.insurancePrice) + ' \u00d7 ' + pax + ')' : '(flat)')
            : '');
        setText($('[data-pd-fare-per]'), pax > 0
            ? money(total / pax) + ' per passenger on average' : '');
    }

    // ---------------------------------------------------------- insurance --
    function planByKey(key) {
        for (var i = 0; i < fareData.insurance_plans.length; i += 1) {
            if (fareData.insurance_plans[i].key === key) { return fareData.insurance_plans[i]; }
        }
        return null;
    }

    function renderInsuranceInfo() {
        var plan = planByKey(state.insuranceKey);
        if (!plan) { return; }
        var details = plan.details || {};
        var priceNote = Number(plan.price) > 0
            ? plan.name + ' — ' + money(plan.price) + ' per insured passenger. '
            : plan.name + ' — no premium. ';
        setText($('[data-pd-insurance-summary]'), priceNote + (details.summary || ''));
        fillList($('[data-pd-insurance-covers]'), details.covers || []);
        fillList($('[data-pd-insurance-excludes]'), details.excludes || []);
    }

    function fillList(listEl, items) {
        if (!listEl) { return; }
        listEl.innerHTML = '';
        if (!items.length) {
            var li = document.createElement('li');
            li.textContent = 'None.';
            listEl.appendChild(li);
            return;
        }
        items.forEach(function (text) {
            var li = document.createElement('li');
            li.textContent = text;
            listEl.appendChild(li);
        });
    }

    // --------------------------------------------------------- validation --
    var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    var PHONE_RE = /^[0-9][0-9\s-]{6,}$/;

    function updateContinueAvailability() {
        var ready = totalPassengers() > 0 && state.policyAck;
        state.passengers.forEach(function (pax, index) {
            var values = pax.values || {};
            var phone = (values.phone || '').replace(/\s+/g, '');
            var complete = Boolean((values.first_name || '').trim() && (values.last_name || '').trim() &&
                values.classification && EMAIL_RE.test((values.email || '').trim()) &&
                /^\d{11}$/.test((values.phone || '').replace(/\s+/g, '')) &&
                values.dob && values.gender && values.nationality);
            if (state.flightType === 'INTERNATIONAL') {
                complete = complete && values.passport && values.passport_country && values.passport_expiry;
                if (values.passport_expiry && root.dataset.departureDate) {
                    complete = complete && values.passport_expiry > root.dataset.departureDate;
                }
            }
            var node = $('[data-pd-index="' + index + '"]');
            if (node && values.dob) {
                var born = new Date(values.dob + 'T00:00:00');
                var travel = new Date((root.dataset.departureDate || new Date().toISOString().slice(0, 10)) + 'T00:00:00');
                var age = travel.getFullYear() - born.getFullYear();
                if (travel.getMonth() < born.getMonth() ||
                    (travel.getMonth() === born.getMonth() && travel.getDate() < born.getDate())) { age -= 1; }
                var category = age < 2 ? 'infant' : (age < 12 ? 'child' : 'adult');
                complete = complete && age >= 0 && category === pax.category &&
                    classificationMatchesAge(values.classification, age);
            } else { complete = false; }
            ready = ready && complete;
        });
        $$('[data-pd-continue], [data-pd-continue-bottom]').forEach(function (button) {
            button.disabled = !ready;
        });
        var hint = $('[data-pd-continue-hint]');
        if (hint) {
            setText(hint, ready ? 'Passenger information and policy acceptance are complete.'
                : 'Complete required passenger details and accept the policy to continue.');
        }
    }

    function validateAll() {
        clearAllErrors();
        var ok = true;

        if (totalPassengers() < 1) { ok = false; }

        state.passengers.forEach(function (pax, index) {
            var node = $('[data-pd-index="' + index + '"]');
            if (!node) { return; }
            var v = pax.values || {};

            if (!(v.first_name || '').trim()) { fail(node, 'first_name', 'Please enter the first name.'); ok = false; }
            if (!(v.last_name || '').trim()) { fail(node, 'last_name', 'Please enter the last name.'); ok = false; }
            if (!['adult', 'child', 'infant', 'senior', 'pwd'].includes(v.classification)) {
                fail(node, 'classification', 'Select a passenger classification.'); ok = false;
            }
            if (!EMAIL_RE.test((v.email || '').trim())) { fail(node, 'email', 'Please enter a valid email address.'); ok = false; }
            var phoneVal = (v.phone || '').trim().replace(/\s+/g, '');
            if (!phoneVal || !/^\d{11}$/.test(phoneVal)) { fail(node, 'phone', 'Please enter a valid phone number (11 digits only).'); ok = false; } else if (v.phone !== phoneVal) { pax.values.phone = phoneVal; }
            if (!(v.dob || '').trim()) { fail(node, 'dob', 'Please enter the date of birth.'); ok = false; }
            else {
                var born = new Date(v.dob + 'T00:00:00');
                var travel = new Date((root.dataset.departureDate || new Date().toISOString().slice(0, 10)) + 'T00:00:00');
                var age = travel.getFullYear() - born.getFullYear();
                if (travel.getMonth() < born.getMonth() ||
                    (travel.getMonth() === born.getMonth() && travel.getDate() < born.getDate())) { age -= 1; }
                var expected = age < 2 ? 'infant' : (age < 12 ? 'child' : 'adult');
                if (age < 0 || expected !== pax.category) {
                    fail(node, 'dob', 'Date of birth does not match the selected passenger category on the travel date.'); ok = false;
                }
                if (!classificationMatchesAge(v.classification, age)) {
                    fail(node, 'classification', 'Passenger classification does not match the date of birth.'); ok = false;
                }
            }
            if (!(v.gender || '').trim()) { fail(node, 'gender', 'Please select a gender.'); ok = false; }
            if (!(v.nationality || '').trim()) { fail(node, 'nationality', 'Please select a nationality.'); ok = false; }
            if (state.flightType === 'INTERNATIONAL' && !(v.passport || '').trim()) {
                fail(node, 'passport', 'Passport number is required for international flights.'); ok = false;
            }
            if (state.flightType === 'INTERNATIONAL' && !(v.passport_country || '').trim()) {
                fail(node, 'passport_country', 'Passport issuing country is required.'); ok = false;
            }
            if (state.flightType === 'INTERNATIONAL' && !(v.passport_expiry || '').trim()) {
                fail(node, 'passport_expiry', 'Passport expiry date is required.'); ok = false;
            } else if (state.flightType === 'INTERNATIONAL' && root.dataset.departureDate &&
                v.passport_expiry <= root.dataset.departureDate) {
                fail(node, 'passport_expiry', 'Passport must remain valid through the departure date.'); ok = false;
            }
        });

        if (!state.policyAck) {
            setErr('policy', 'Please acknowledge the cancellation and refund policy.');
            ok = false;
        }

        return ok;
    }

    function fail(node, field, message) {
        var fieldWrap = $('[data-pd-field="' + field + '"]', node);
        if (fieldWrap && fieldWrap.closest('.pd-field')) {
            fieldWrap.closest('.pd-field').classList.add('is-invalid');
        }
        var err = $('[data-pd-err="' + field + '"]', node);
        if (err) { err.textContent = message; }
    }

    function classificationMatchesAge(classification, age) {
        if (classification === 'pwd') { return true; }
        if (age >= 60 && (classification === 'senior' || classification === 'adult')) { return true; }
        var suggested = age < 2 ? 'infant' : (age < 12 ? 'child' : 'adult');
        return classification === suggested;
    }

    function clearFieldError(field) {
        if (!field) { return; }
        var wrap = field.closest('.pd-field');
        if (wrap) { wrap.classList.remove('is-invalid'); }
    }

    function clearFieldErrorByName(name) {
        var err = $('[data-pd-err="' + name + '"]');
        if (err) { err.textContent = ''; }
    }

    function setErr(name, message) {
        var err = $('[data-pd-err="' + name + '"]');
        if (err) { err.textContent = message; }
    }

    function clearAllErrors() {
        $$('.pd-field.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
        $$('.pd-field__err').forEach(function (el) { el.textContent = ''; });
    }

    // --------------------------------------------------------------- review --
    function buildReview() {
        var body = $('[data-pd-review-body]');
        if (!body) { return; }
        body.innerHTML = '';

        body.appendChild(block('Flight', [
            row('Airline', flightAirlineText()),
            row('Route', flightRouteText()),
            row('Class', fareClassLabel(state.fareClassKey)),
            row('Segments', (flightData.segments || []).map(function (segment) {
                return segment.flight_number + ' ' + segment.origin_code + '–' + segment.destination_code;
            }).join(' · ') || '—'),
            row('Cancellation & change terms', flightData.cancellation_terms || 'See applicable fare rules')
        ]));

        var paxRows = [row('Travellers', paxSummary())];
        state.passengers.forEach(function (pax, index) {
            var v = pax.values || {};
            var bits = [(v.full_name || 'Passenger ' + (index + 1))];
            if (SEATABLE[pax.category]) { bits.push('Seat ' + (pax.seat || 'not assigned')); }
            bits.push(passengerClassificationLabel((v.classification || pax.category)));
            bits.push(v.email || '');
            bits.push((v.phone_code || '') + ' ' + (v.phone || ''));
            if (state.flightType === 'INTERNATIONAL') { bits.push('Passport ' + (v.passport || '') + ', ' + (v.passport_country || '') + ' (expires ' + (v.passport_expiry || '') + ')'); }
            paxRows.push(row('Passenger ' + (index + 1), bits.filter(Boolean).join(' · ')));
        });
        body.appendChild(block('Passengers', paxRows));

        var services = [row('Extra baggage', baggageLabel())];
        services.push(row('Travel insurance', insuranceLabel()));
        body.appendChild(block('Baggage & insurance', services));

        var seatCount = 0;
        state.passengers.forEach(function(p) { if (p.seat && SEATABLE[p.category]) seatCount++; });
        body.appendChild(block('Seat selection', [
            row('Selected seats', seatCount > 0 ? seatCount + ' seat(s)' : 'None'),
            row('Seat selection total', money(seatTotal()))
        ]));

        body.appendChild(block('Cancellation & refund policy', [
            row('Acknowledged', state.policyAck ? 'Yes' : 'No')
        ]));

        var pax = totalPassengers();
        var baggageTotal = BAGGAGE_BASIS === 'per_passenger' ? state.baggagePrice * pax : state.baggagePrice;
        var insuranceTotal = INSURANCE_BASIS === 'per_passenger' ? state.insurancePrice * pax : state.insurancePrice;
        var seatTotalAmount = seatTotal();
        var priceRows = [
            row('Base fare', money(BASE_FARE * pax)),
            row('Taxes & fees', money(TAX_PER_PAX * pax)),
            row('Extra baggage', money(baggageTotal)),
            row('Travel insurance', money(insuranceTotal)),
            row('Seat selection', money(seatTotalAmount))
        ];
        body.appendChild(block('Price breakdown', priceRows, money(BASE_FARE * pax + TAX_PER_PAX * pax + baggageTotal + insuranceTotal + seatTotalAmount)));
    }

    function buildTicketPayload() {
        return {
            flight: {
                id: flightData.id,
                origin_code: flightData.origin_code,
                destination_code: flightData.destination_code,
                fare_class_key: state.fareClassKey || flightData.fare_class_key || 'ECONOMY'
            },
            departure_date: root.dataset.departureDate || '',
            passengers: state.passengers.map(function (pax) {
                return {
                    name: (pax.values && pax.values.full_name || '').trim(),
                    category: pax.category,
                    seat: pax.seat || '',
                    details: Object.assign({}, pax.values || {})
                };
            }),
            flight_type: state.flightType,
            baggage_kg: state.baggageKg,
            insurance_key: state.insuranceKey,
            policy_acknowledged: Boolean(state.policyAck),
            insurance_terms_acknowledged: Boolean(state.policyAck)
        };
    }

    function block(title, rows, total) {
        var wrap = document.createElement('div');
        wrap.className = 'pd-rv-block';
        var h = document.createElement('h3');
        h.innerHTML = '<i class="fas fa-circle-check"></i> ' + escapeHtml(title);
        wrap.appendChild(h);
        var table = document.createElement('table');
        table.className = 'pd-rv-table';
        var tbody = document.createElement('tbody');
        rows.forEach(function (r) {
            var tr = document.createElement('tr');
            var th = document.createElement('th');
            th.textContent = r[0];
            var td = document.createElement('td');
            td.textContent = r[1];
            tr.appendChild(th); tr.appendChild(td);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        if (total !== undefined) {
            var totalEl = document.createElement('div');
            totalEl.className = 'pd-rv-total';
            totalEl.innerHTML = '<span>Total amount</span><span>' + escapeHtml(total) + '</span>';
            wrap.appendChild(totalEl);
        }
        return wrap;
    }

    function row(label, value) { return [label, value || '\u2014']; }

    function paxSummary() {
        var parts = [];
        CATEGORY_ORDER.forEach(function (key) {
            if (state.counts[key] > 0) {
                parts.push(state.counts[key] + ' ' + categoryLabel(key).toLowerCase() +
                    (state.counts[key] > 1 ? 's' : ''));
            }
        });
        return parts.join(', ');
    }

    function passengerClassificationSummary() {
        var counts = {};
        state.passengers.forEach(function (passenger) {
            var key = (passenger.values && passenger.values.classification) || passenger.category;
            var label = passengerClassificationLabel(key);
            counts[label] = (counts[label] || 0) + 1;
        });
        return Object.keys(counts).map(function (label) {
            return label + (counts[label] > 1 ? ' × ' + counts[label] : '');
        }).join(', ') || '—';
    }

    function passengerClassificationLabel(key) {
        return { adult: 'Adult', child: 'Child', infant: 'Infant', senior: 'Senior Citizen', pwd: 'Person with Disability (PWD)' }[key] || 'Passenger';
    }

    function baggageLabel() {
        if (!state.baggagePrice) { return 'No extra baggage'; }
        var opt = findBaggage(state.baggageKg);
        return (opt ? opt.label : state.baggageKg + ' kg') + ' \u2014 ' + money(state.baggagePrice);
    }

    function insuranceLabel() {
        var plan = planByKey(state.insuranceKey);
        if (!plan || !state.insurancePrice) { return 'No insurance'; }
        return plan.name + ' \u2014 ' + money(state.insurancePrice) + ' per passenger';
    }

    function grandTotal() {
        var pax = totalPassengers();
        return money(
            BASE_FARE * pax + TAX_PER_PAX * pax +
            (BAGGAGE_BASIS === 'per_passenger' ? state.baggagePrice * pax : state.baggagePrice) +
            (INSURANCE_BASIS === 'per_passenger' ? state.insurancePrice * pax : state.insurancePrice)
        );
    }

    function flightRouteText() {
        var summary = document.querySelector('.pd-flight');
        if (!summary) { return '\u2014'; }
        var codes = $$('.pd-endpoint__code', summary).map(function (el) { return el.textContent.trim(); });
        return codes.join(' \u2192 ');
    }

    function flightAirlineText() {
        var name = document.querySelector('.pd-flight__name');
        return name ? name.textContent.trim() : '\u2014';
    }

    function openReview() {
        if (!validateAll()) {
            var firstError = $('.pd-field.is-invalid input, .pd-field.is-invalid select');
            if (firstError) { firstError.focus({ preventScroll: false }); }
            else {
                var errEl = $$('.pd-field__err').filter(function (el) { return el.textContent; })[0];
                if (errEl) { errEl.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
            }
            return;
        }
        buildReview();
        review.hidden = false;
        review.style.display = 'grid';
        review.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
    }

    function closeReview() {
        review.hidden = true;
        review.removeAttribute('style');
        review.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    }

    // --------------------------------------------------------------- utils --
    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function findBaggage(kg) {
        for (var i = 0; i < fareData.baggage_options.length; i += 1) {
            if (Number(fareData.baggage_options[i].kg) === Number(kg)) { return fareData.baggage_options[i]; }
        }
        return null;
    }

    function fareClassByKey(key) {
        return (flightData.fare_classes || []).find(function (item) { return item.key === key; }) || null;
    }

    function fareClassLabel(key) {
        var cabin = fareClassByKey(key);
        return cabin ? cabin.label : (flightData.fare_class_label || 'Economy Class');
    }

    // ------------------------------------------------------------- wiring --
    var modal = $('[data-pd-seat-modal]');
    var review = $('[data-pd-review]');
    var seatGrid = $('[data-pd-seat-grid]');

    // Flight type radios.
    $$('input[name="flight_type"]').forEach(function (input) {
        input.addEventListener('change', function () { setFlightType(input.value); });
    });

    // Count steppers and inputs.
    $$('[data-pd-step]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            adjustCount(btn.getAttribute('data-pd-target'), Number(btn.getAttribute('data-pd-step')));
        });
    });
    $$('[data-pd-count]').forEach(function (input) {
        input.addEventListener('change', function () {
            setCount(input.getAttribute('data-pd-count'), input.value);
        });
        input.addEventListener('input', function () {
            if (input.value === '') { return; }
            setCount(input.getAttribute('data-pd-count'), input.value);
        });
    });

    // Passenger removal (delegated): removes that exact traveller.
    root.addEventListener('click', function (event) {
        var remove = event.target.closest('[data-pd-remove]');
        if (!remove || remove.hidden) { return; }
        removePassengerAt(Number(remove.getAttribute('data-pd-remove')));
    });

    // Seat map clicks.
    if (seatGrid) {
        seatGrid.addEventListener('click', function (event) {
            var seat = event.target.closest('.pd-seat');
            if (!seat || seat.disabled) { return; }
            assignSeat(seat.getAttribute('data-seat'));
        });
    }

    // Release a seat so a different one can be picked for that passenger.
    root.addEventListener('click', function (event) {
        var change = event.target.closest('[data-pd-clear-seat]');
        if (!change) { return; }
        event.stopPropagation();
        clearSeatFor(Number(change.getAttribute('data-pd-clear-seat')));
    });

    // Seat modal open/close/confirm.
    $$('[data-pd-open-seat]').forEach(function (btn) { btn.addEventListener('click', openSeatModal); });
    $$('[data-pd-seat-close]').forEach(function (btn) { btn.addEventListener('click', closeSeatModal); });
    $$('[data-pd-confirm-seats]').forEach(function (btn) { btn.addEventListener('click', confirmSeats); });

    // Baggage choices are checkbox rows for clarity, but each row is an
    // allowance tier. Keep the existing single-tier booking and pricing model.
    var baggageOptions = $$('[data-pd-baggage-option]');
    function selectBaggage(input) {
        baggageOptions.forEach(function (option) {
            option.checked = option === input;
        });
        state.baggageKg = Number(input.value) || 0;
        state.baggagePrice = Number(input.getAttribute('data-price')) || 0;
        updateFare();
    }
    baggageOptions.forEach(function (input) {
        input.addEventListener('change', function () {
            if (input.checked) {
                selectBaggage(input);
                return;
            }
            // Keep a valid no-baggage choice selected if the active tier is
            // unchecked, so the stored payload always matches the UI.
            var noBaggage = baggageOptions.find(function (option) {
                return Number(option.value) === 0;
            });
            if (noBaggage) { selectBaggage(noBaggage); }
            else {
                state.baggageKg = 0;
                state.baggagePrice = 0;
                updateFare();
            }
        });
    });
    var insuranceOptions = $$('[data-pd-insurance-option]');
    insuranceOptions.forEach(function (input) {
        input.addEventListener('change', function () {
            if (!input.checked) { return; }
            state.insuranceKey = input.value;
            state.insurancePrice = Number(input.getAttribute('data-price')) || 0;
            renderInsuranceInfo();
            updateFare();
        });
    });

    $$('[data-pd-fare-class]').forEach(function (input) {
        input.addEventListener('change', function () {
            if (!input.checked) { return; }
            state.fareClassKey = input.value;
            BASE_FARE = Number(input.getAttribute('data-fare')) || 0;
            flightData.fare_class_key = state.fareClassKey;
            setText($('[data-pd-selected-class]'), fareClassLabel(state.fareClassKey));
            if (cabinSeatMaps[state.fareClassKey]) {
                seatData = cabinSeatMaps[state.fareClassKey];
                state.passengers.forEach(function (passenger) { passenger.seat = ''; });
                state.seats = {};
                renderDynamicSeatGrid();
                renderSeatPanel();
                renderSeatSummary();
                renderPassengerSeatLabels();
                paintSeatGrid();
                setText($('[data-pd-seat-class]'), (seatData.layout || '') + ' · ' + fareClassLabel(state.fareClassKey));
                setText($('[data-pd-seat-flightbar-cabin]'), (seatData.cabin || fareClassLabel(state.fareClassKey)) +
                    (seatData.cabin_pitch ? ' · pitch ' + seatData.cabin_pitch : ''));
            }
            var baggageAllowance = $('[data-pd-standard-baggage]');
            if (baggageAllowance) {
                var allowance = Number(input.getAttribute('data-baggage')) || 0;
                setText(baggageAllowance, allowance ? allowance + ' kg' : 'Not specified');
            }
            updateFare();
        });
    });

    // Insurance details toggle.
    var insuranceToggle = $('[data-pd-insurance-toggle]');
    if (insuranceToggle) {
        insuranceToggle.addEventListener('click', function () {
            var terms = $('[data-pd-insurance-terms]');
            var open = terms.hidden;
            terms.hidden = !open;
            insuranceToggle.setAttribute('aria-expanded', String(open));
            setText($('[data-pd-insurance-toggle-text]'), open ? 'Hide Insurance Details' : 'View Insurance Details');
        });
    }

    // Refund details toggle.
    var refundToggle = $('[data-pd-refund-toggle]');
    if (refundToggle) {
        refundToggle.addEventListener('click', function () {
            var more = $('[data-pd-refund-more]');
            var open = more.hidden;
            more.hidden = !open;
            refundToggle.setAttribute('aria-expanded', String(open));
            setText($('[data-pd-refund-toggle-text]'), open ? 'Hide Refund Details' : 'Learn More About Refunds');
        });
    }

    // Policy acknowledgement.
    var ack = $('[data-pd-policy-ack]');
    if (ack) {
        ack.addEventListener('change', function () {
            state.policyAck = ack.checked;
            if (ack.checked) { clearFieldErrorByName('policy'); }
            updateContinueAvailability();
        });
    }

    // Continue + review controls.
    $$('[data-pd-continue]').forEach(function (btn) { btn.addEventListener('click', openReview); });
    var continueBottom = $('[data-pd-continue-bottom]');
    if (continueBottom) {
        continueBottom.addEventListener('click', function () {
            var seatSection = $('#pd-seat-section');
            if (seatSection) { seatSection.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
        });
    }
    var saveButton = $('[data-pd-save]');
    if (saveButton) {
        saveButton.addEventListener('click', function () {
            if (!validateAll()) { updateContinueAvailability(); return; }
            try {
                sessionStorage.setItem('atrue-passenger-draft-' + String(flightData.id), JSON.stringify(buildTicketPayload()));
                var status = $('[data-pd-save-status]');
                if (status) { setText(status, 'Passenger information saved for this booking session.'); }
            } catch (err) {
                var status = $('[data-pd-save-status]');
                if (status) { setText(status, 'Unable to save in this browser. Your details remain on this page.'); }
            }
        });
    }
    $$('[data-pd-review-close]').forEach(function (btn) { btn.addEventListener('click', closeReview); });
    var ticketForm = $('[data-pd-ticket-form]');
    if (ticketForm) {
        ticketForm.addEventListener('submit', function () {
            var payloadField = $('[data-pd-ticket-payload]', ticketForm);
            if (payloadField) { payloadField.value = JSON.stringify(buildTicketPayload()); }
        });
    }

    // Escape closes the topmost overlay.
    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') { return; }
        if (!modal.hidden) { closeSeatModal(); }
        else if (!review.hidden) { closeReview(); }
    });

    // Initialise the passenger list.
    var initial = {};
    var savedDraft = null;
    try {
        savedDraft = JSON.parse(sessionStorage.getItem('atrue-passenger-draft-' + String(flightData.id)) || 'null');
        if (savedDraft && String(savedDraft.flight && savedDraft.flight.id) !== String(flightData.id)) { savedDraft = null; }
    } catch (err) { savedDraft = null; }
    (root.dataset.initialPassengers || '').split(',').forEach(function (chunk) {
        var parts = chunk.split(':');
        if (parts.length === 2 && CATEGORY_ORDER.indexOf(parts[0]) !== -1) {
            initial[parts[0]] = Number(parts[1]);
        }
    });
    if (savedDraft && Array.isArray(savedDraft.passengers) && savedDraft.passengers.length) {
        initial = { adult: 0, child: 0, infant: 0 };
        savedDraft.passengers.forEach(function (passenger) {
            if (initial[passenger.category] !== undefined) { initial[passenger.category] += 1; }
        });
    }
    CATEGORY_ORDER.forEach(function (key) {
        var wanted = initial[key] !== undefined ? initial[key] : (key === 'adult' ? 1 : 0);
        wanted = Math.max(key === 'adult' ? 1 : 0, Math.min(MAX[key], wanted));
        for (var i = 0; i < wanted; i += 1) { addPassenger(key); }
    });

    if (savedDraft && Array.isArray(savedDraft.passengers)) {
        savedDraft.passengers.forEach(function (savedPassenger, index) {
            if (!state.passengers[index]) { return; }
            state.passengers[index].values = Object.assign({}, savedPassenger.details || {});
            state.passengers[index].seat = savedPassenger.seat || '';
            state.passengers[index].classificationTouched = true;
        });
        if (savedDraft.baggage_kg !== undefined) {
            baggageOptions.forEach(function (option) { option.checked = Number(option.value) === Number(savedDraft.baggage_kg); });
        }
        if (savedDraft.insurance_key) {
            insuranceOptions.forEach(function (option) { option.checked = option.value === savedDraft.insurance_key; });
        }
        state.policyAck = Boolean(savedDraft.policy_acknowledged);
        if (ack) { ack.checked = state.policyAck; }
        if (savedDraft.flight && savedDraft.flight.fare_class_key) {
            state.fareClassKey = savedDraft.flight.fare_class_key;
            $$('[data-pd-fare-class]').forEach(function (option) {
                option.checked = option.value === state.fareClassKey;
                if (option.checked) { BASE_FARE = Number(option.getAttribute('data-fare')) || BASE_FARE; }
            });
            if (cabinSeatMaps[state.fareClassKey]) { seatData = cabinSeatMaps[state.fareClassKey]; }
        }
    }

    setFlightType(root.dataset.defaultFlightType || 'DOMESTIC');
    rebuildPassengers();
    syncCountInputs();
    var initialBaggage = baggageOptions.find(function (option) { return option.checked; });
    if (initialBaggage) {
        state.baggageKg = Number(initialBaggage.value) || 0;
        state.baggagePrice = Number(initialBaggage.getAttribute('data-price')) || 0;
    }
    var initialInsurance = insuranceOptions.find(function (option) { return option.checked; });
    if (initialInsurance) {
        state.insuranceKey = initialInsurance.value;
        state.insurancePrice = Number(initialInsurance.getAttribute('data-price')) || 0;
    }
    renderInsuranceInfo();
    renderSeatSummary();
    updateFare();
    updateContinueAvailability();
})();
