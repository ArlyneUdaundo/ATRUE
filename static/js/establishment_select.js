/* ============================================================
   ATRUE — Establishment selection page behaviour
   Resorts · Staycations · Restaurants · Tour Packages ·
   Landmarks · Activities

   THE HOTEL PAGE IS THE MASTER TEMPLATE.
   -----------------------------------------
   `buildSection()` and `renderSummary()` below are deliberately a
   line-for-line mirror of static/js/rooms.js (the Hotels page), so every
   establishment reaches the same Guest Information card, the same
   "Optional services for ..." / "Amenities for ..." sections and the same
   Booking computation. Only the nouns (Villa, Table, Session, ...) and the
   numbers coming from that establishment change. Markup, class names, field
   order, labels and behaviour are shared, not forked.

   Server contract (JSON):
     flowConfig   { badge, item, item_plural, hint, charge_section, show_duration }
     itemMeta     id -> { number, name, rate, total, unit_noun, max_guests,
                          bookable, status, charge }
     servicesData [ { id, name, rate } ]   existing Service rows only
     amenityData  [ { id, name } ]         existing Amenity rows only
     itemDetails  id -> { ... }            photos & details modal
     preselected  [ guest objects ]        preserved after a validation error
     selectedIds  [ id ]                   selection preserved after a re-render

   POST names: item_ids[] / item_<n>_<field> / payment_method / pay_later.
   Nothing here invents a price: a category with no stored rate has
   charge.rate === '0' and is labelled "No rate on file".
   ============================================================ */
(function () {
    'use strict';

    var CONFIG = readJSON('flowConfig') || {};
    var ITEM_META = readJSON('itemMeta') || {};
    var SERVICES = readJSON('servicesData') || [];
    var AMENITIES = readJSON('amenityData') || [];
    var DETAILS = readJSON('itemDetails') || {};
    var PRESELECTED = readJSON('preselected') || [];
    var PRIMARY_GUEST = readJSON('primaryGuest') || {};
    var SELECTED_IDS = readJSON('selectedIds') || [];
    if (!Array.isArray(PRESELECTED)) { PRESELECTED = []; }
    if (!Array.isArray(SELECTED_IDS)) { SELECTED_IDS = []; }

    var form = document.getElementById('bookingForm');
    if (!form) { return; }

    var BADGE = CONFIG.badge || 'ITEM';
    var ITEM = CONFIG.item || 'Item';
    var ITEM_PLURAL = (CONFIG.item_plural || 'Items').toLowerCase();
    var HINT = CONFIG.hint || 'Recalculated live as you pick items, dates, guests and services.';
    var CHARGE_SECTION = CONFIG.charge_section || (ITEM_PLURAL + ' charges');
    var SHOW_DURATION = CONFIG.show_duration === true;

    var inputsBox = document.getElementById('itemIdsInputs');
    var guestBox = document.getElementById('selectedItemsSection');
    var guestModal = document.getElementById('guestModal');
    var guestModalSub = document.getElementById('guestModalSub');
    var guestSave = document.getElementById('guestModalSave');
    var guestOpener = null;
    var compBox = document.getElementById('computationSummary');
    var linesBox = document.getElementById('pbItemLines');
    var totalBox = document.getElementById('pbTotal');
    var totalLabel = document.getElementById('pbTotalLabel');
    var countPanel = document.getElementById('itemCountPanel');
    var countSelected = document.getElementById('pbItemsSelected');
    var continueBtn = document.getElementById('continueBtn');
    var nightsBox = document.getElementById('pbNights');
    var guestsBox = document.getElementById('pbGuests');
    var divider = document.getElementById('pbDivider');
    var checkInEl = document.getElementById('bkCheckIn');
    var checkOutEl = document.getElementById('bkCheckOut');

    var SELECTED = [];   // one entry per booked item, in selection order

    function readJSON(id) {
        var el = document.getElementById(id);
        if (!el) { return null; }
        var parsed;
        try { parsed = JSON.parse(el.textContent); } catch (e) { return null; }
        // json_script serialises the value itself. If a string ever reaches it
        // the block is double-encoded, which would turn an object into a string
        // and break every lookup below, so unwrap it instead of failing.
        if (typeof parsed === 'string') {
            try { return JSON.parse(parsed); } catch (e) { return null; }
        }
        return parsed;
    }

    /* ---------------------------------------------------------- helpers */
    // Same two formatters the Hotels page uses.

    function peso(n) {
        return Number(n || 0).toLocaleString('en-PH', { maximumFractionDigits: 0 });
    }

    function fmt(n) {
        return '\u20B1 ' + Number(n || 0).toLocaleString('en-PH', {
            minimumFractionDigits: 2, maximumFractionDigits: 2
        });
    }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function plural(count, one, many) {
        return count === 1 ? one : (many || one + 's');
    }

    function meta(id) { return ITEM_META[String(id)] || {}; }

    function findIndex(id) {
        for (var i = 0; i < SELECTED.length; i++) {
            if (String(SELECTED[i].item_id) === String(id)) { return i; }
        }
        return -1;
    }

    function emptyGuest() {
        return {
            first_name: '', middle_name: '', last_name: '', email: '', contact: '',
            adults: 1, children: 0, special_request: '', services: [], amenities: []
        };
    }

    function makeEntry(id) {
        var m = meta(id);
        var c = m.charge || {};
        return {
            item_id: id,
            number: m.number || String(id),
            name: m.name || ITEM,
            rate: Number(m.rate || 0),
            max_guests: Number(m.max_guests || 1),
            charge: c,
            guest: SELECTED.length === 0 ? Object.assign(emptyGuest(), PRIMARY_GUEST) : emptyGuest(),
            services: [],
            amenities: []
        };
    }

    function currentNights() {
        if (!checkInEl || !checkOutEl) { return SHOW_DURATION ? 1 : null; }
        var ds = Date.parse(checkInEl.value + 'T00:00:00');
        var de = Date.parse(checkOutEl.value + 'T00:00:00');
        if (!isFinite(ds) || !isFinite(de) || de <= ds) { return SHOW_DURATION ? null : 1; }
        return Math.max(1, Math.round((de - ds) / 86400000));
    }

    // --- charge arithmetic, mirroring each adapter's build_booking() -------

    function lineTotals(entry) {
        var c = entry.charge || {};
        var nights = currentNights() || 1;
        var guests = Math.max(0, Number(entry.guest.adults) || 0)
            + Math.max(0, Number(entry.guest.children) || 0);
        var rate = Number(c.rate || entry.rate || 0);
        var unit = c.unit_noun || 'night';

        var units = c.mode === 'nights' ? nights
            : c.mode === 'guests' ? Math.max(1, guests) : 1;
        var base = rate * units;

        var included = Number(c.included || 0);
        var overIncluded = Math.max(0, guests - included);
        var extraRate = Number(c.extra_rate || 0);
        var extraUnits = 0;
        if (extraRate > 0 && overIncluded > 0) {
            extraUnits = c.extra_mode === 'nights'
                ? overIncluded * nights
                : c.extra_mode === 'guests' ? overIncluded : 1;
        }
        var extraTotal = extraRate * extraUnits;

        return {
            nights: nights, guests: guests, rate: rate, unit: unit,
            units: units, base: base,
            overIncluded: overIncluded, extraRate: extraRate, extraTotal: extraTotal
        };
    }

    function serviceTotal(index) {
        var total = 0;
        var scope = guestBox || document;
        Array.prototype.slice.call(
            scope.querySelectorAll('[data-guest-section="' + index + '"] input[data-service]:checked')
        ).forEach(function (cb) {
            var svc = SERVICES.filter(function (s) { return String(s.id) === cb.value; })[0];
            if (svc) { total += Number(svc.rate || 0); }
        });
        return total;
    }

    /* ------------------------------------------------- selection actions */

    function addItem(id) {
        if (findIndex(id) !== -1) { return; }
        SELECTED.push(makeEntry(id));
    }

    function removeItem(id) {
        var idx = findIndex(id);
        if (idx !== -1) {
            SELECTED.splice(idx, 1);
            if (idx === 0 && SELECTED.length) {
                ['first_name','middle_name','last_name','email','contact'].forEach(function (key) {
                    SELECTED[0].guest[key] = PRIMARY_GUEST[key] || '';
                });
            }
        }
    }

    function toggleItem(id) {
        if (meta(id).bookable === false) { return; }
        if (findIndex(id) === -1) { addItem(id); } else { removeItem(id); }
    }

    function renderCardStates() {
        Array.prototype.forEach.call(document.querySelectorAll('[data-item-book]'), function (btn) {
            var id = btn.getAttribute('data-item-book');
            var on = findIndex(id) !== -1;
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
            btn.classList.toggle('is-on', on);
            btn.innerHTML = on
                ? '<i class="fas fa-check"></i> Selected'
                : '<i class="fas fa-circle-check"></i> Select';
        });
        Array.prototype.forEach.call(document.querySelectorAll('[data-item-card]'), function (card) {
            var id = card.getAttribute('data-item-card');
            card.classList.toggle('is-selected', findIndex(id) !== -1);
            // Reopen guest information for an already selected item, the same
            // affordance the Hotels room cards carry.
            var foot = card.querySelector('.rm-rate-foot');
            if (foot) {
                var btn = foot.querySelector('[data-guest-open]');
                if (!btn) {
                    btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'rm-btn rm-btn-sm';
                    btn.setAttribute('data-guest-open', id);
                    btn.innerHTML = '<i class="fas fa-user-pen"></i> Guest info';
                    foot.appendChild(btn);
                }
                btn.hidden = findIndex(id) === -1;
            }
        });
    }

    /* -------------------------------------------------- guest information
       Mirrors rooms.js buildSection(): same section/card structure, same
       header, same field order and labels, same extras blocks, same error
       slot. Only the badge noun, the item name and the numbers differ. */
    function buildSection(s, i) {
        var g = s.guest;
        var c = s.charge || {};
        var totals = lineTotals(s);

        var svcBoxes = SERVICES.map(function (svc) {
            var checked = s.services.indexOf(Number(svc.id)) !== -1 ? ' checked' : '';
            return '<label class="checkbox"><input type="checkbox" name="item_' + i + '_services"'
                + ' data-service value="' + esc(svc.id) + '"' + checked + '> '
                + esc(svc.name) + ' (+' + fmt(svc.rate) + ')</label>';
        }).join('');
        var amnBoxes = AMENITIES.map(function (amn) {
            var checked = s.amenities.indexOf(Number(amn.id)) !== -1 ? ' checked' : '';
            return '<label class="checkbox"><input type="checkbox" name="item_' + i + '_amenities"'
                + ' data-amenity value="' + esc(amn.id) + '"' + checked + '> '
                + esc(amn.name) + '</label>';
        }).join('');

        // Both sections are always present so the guest-information card is the
        // same in all seven categories. When a category has no stored rows the
        // block keeps its heading and states that plainly - no options are
        // invented, so nothing is ever added to the total.
        function extrasBlock(title, boxes, emptyNote) {
            return '<div class="bk-guest-extras">' +
                '<div style="flex:1 1 100%"><b>' + title + '</b></div>' +
                (boxes || '<small class="meta">' + emptyNote + '</small>') +
                '</div>';
        }
        var svcBlock = extrasBlock(
            'Optional services for ' + esc(ITEM) + ' ' + (i + 1),
            svcBoxes,
            'No optional services for this ' + esc(ITEM.toLowerCase()) + '.'
        );
        var amnBlock = extrasBlock(
            'Amenities for ' + esc(ITEM) + ' ' + (i + 1),
            amnBoxes,
            'No amenities listed for this ' + esc(ITEM.toLowerCase()) + '.'
        );

        // Same shape as the Hotels information line, filled from this item.
        var info = [esc(s.number)];
        info.push(totals.rate > 0
            ? fmt(totals.rate) + '/' + esc(c.unit_noun || 'night')
            : 'No rate on file');
        info.push('Included guests: ' + (Number(c.included) || 0));
        info.push('Max: ' + s.max_guests);
        if (totals.extraRate > 0) {
            info.push(esc(c.extra_label || 'Extra guest') + ': ' + fmt(totals.extraRate)
                + '/guest/' + (c.extra_mode === 'nights' ? 'night' : 'person'));
        }

        return '' +
        '<section class="bk-guest-card" data-guest-section="' + i + '">' +
            '<div class="bk-guest-head">' +
                '<div><span class="badge badge-blue">' + esc(BADGE) + ' ' + (i + 1) + (i === 0 ? ' - Primary Guest' : ' - Additional Guest') + '</span>' +
                '<h3 style="margin:8px 0 2px">' + esc(s.name) + '</h3>' +
                '<small>' + info.join(' &middot; ') + '</small>' +
                '</div>' +
                '<button type="button" class="bk-remove" data-remove-item="' + esc(s.item_id) + '">' +
                    '<i class="fas fa-times"></i> Remove</button>' +
            '</div>' +
            '<div class="form-grid" style="margin-top:16px">' +
                '<div class="form-group"><label>First Name *</label>' +
                    '<input name="item_' + i + '_first_name" class="form-input" value="' + esc(g.first_name) + '"' + (i === 0 ? ' readonly aria-readonly="true"' : '') + '></div>' +
                '<div class="form-group"><label>Middle Name</label>' +
                    '<input name="item_' + i + '_middle_name" class="form-input" value="' + esc(g.middle_name) + '"' + (i === 0 ? ' readonly aria-readonly="true"' : '') + '></div>' +
                '<div class="form-group"><label>Last Name *</label>' +
                    '<input name="item_' + i + '_last_name" class="form-input" value="' + esc(g.last_name) + '"' + (i === 0 ? ' readonly aria-readonly="true"' : '') + '></div>' +
            '</div>' +
            '<div class="form-grid">' +
                '<div class="form-group"><label>Email *</label>' +
                    '<input type="email" name="item_' + i + '_email" class="form-input" value="' + esc(g.email) + '"' + (i === 0 ? ' readonly aria-readonly="true"' : '') + '></div>' +
                '<div class="form-group"><label>Contact Number *</label>' +
                    '<input type="text" name="item_' + i + '_contact" class="form-input" value="' + esc(g.contact) + '"' + (i === 0 ? ' readonly aria-readonly="true"' : '') +
                    ' inputmode="numeric" pattern="[0-9]*" maxlength="20" autocomplete="off"' +
                    ' oninput="this.value=this.value.replace(/\\D/g, \'\')" title="Numbers only"></div>' +
            '</div>' +
            '<div class="form-grid">' +
                '<div class="form-group"><label>Adults *</label>' +
                    '<input type="number" name="item_' + i + '_adults" class="form-input" value="' + Number(g.adults || 0) + '" min="0"></div>' +
                '<div class="form-group"><label>Children</label>' +
                    '<input type="number" name="item_' + i + '_children" class="form-input" value="' + Number(g.children || 0) + '" min="0"></div>' +
                '<div class="form-group"><label>Total guests</label>' +
                    '<div class="form-input" style="background:#f8fafc" data-guest-total="' + i + '">' +
                    (totals.guests) + ' <small class="meta">of ' + s.max_guests + ' max</small></div></div>' +
            '</div>' +
            '<div class="form-group" style="margin:0"><label>Special Request</label>' +
                '<textarea name="item_' + i + '_special_request" class="form-input" rows="2">' +
                esc(g.special_request) + '</textarea></div>' +
            svcBlock + amnBlock +
            '<div class="bk-guest-err"></div>' +
        '</section>';
    }

function renderSections() {
if (!guestBox) { return; }
        guestBox.innerHTML = SELECTED.map(buildSection).join('');
        // The guest modal sits outside <form>, so tie the per-item fields back
        // to the booking form with the HTML form="" attribute. Same inputs,
        // same names, same submit.
        if (form && form.id) {
            Array.prototype.forEach.call(
                guestBox.querySelectorAll('input, textarea, select'),
                function (el) { el.setAttribute('form', form.id); });
        }
    }

    function renderHiddenIds() {
        if (!inputsBox) { return; }
        inputsBox.innerHTML = SELECTED.map(function (s) {
            return '<input type="hidden" name="item_ids" value="' + esc(s.item_id) + '">';
        }).join('');
    }

    // Same read-back the Hotels page does before every re-render, so nothing
    // the guest typed is lost when a card is selected or removed.
    function syncFromDom() {
        SELECTED.forEach(function (s, i) {
            var sec = document.querySelector('[data-guest-section="' + i + '"]');
            if (!sec) { return; }
            function inVal(name) {
                var el = sec.querySelector('[name="item_' + i + '_' + name + '"]');
                return el ? el.value : '';
            }
            function checked(sel) {
                return Array.prototype.slice.call(sec.querySelectorAll(sel))
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
            s.services = checked('[name="item_' + i + '_services"]:checked');
            s.amenities = checked('[name="item_' + i + '_amenities"]:checked');
        });
    }

    /* -------------------------------------------------------- computation
       Mirrors rooms.js computeAll()/renderSummary(): the same
       bk-summary card, the same bk-sum-section heading, the same
       per-item row + indented breakdown, subtotal and grand total. */
    function computeAll() {
        var nights = currentNights();
        var okDates = nights !== null;

        var rows = SELECTED.map(function (s) {
            var t = lineTotals(s);
            var svcTotal = serviceTotal(SELECTED.indexOf(s));
            var svcNames = s.services.map(function (id) {
                var svc = SERVICES.filter(function (x) { return Number(x.id) === Number(id); })[0];
                return svc ? svc.name : '';
            }).filter(Boolean);
            return {
                s: s, t: t, nights: t.nights,
                svcTotal: svcTotal, svcNames: svcNames,
                total: t.base + t.extraTotal + svcTotal
            };
        });

        var baseSub = rows.reduce(function (a, r) { return a + r.t.base; }, 0);
        var extraSub = rows.reduce(function (a, r) { return a + r.t.extraTotal; }, 0);
        var svcSub = rows.reduce(function (a, r) { return a + r.svcTotal; }, 0);
        var grand = baseSub + extraSub + svcSub;
        var gpTotal = rows.reduce(function (a, r) { return a + r.t.guests; }, 0);

        if (nightsBox && SHOW_DURATION) {
            nightsBox.textContent = okDates ? nights : '\u2014';
        }
        if (totalLabel) {
            totalLabel.textContent = (SHOW_DURATION && okDates)
                ? 'Estimated total \u00d7 ' + nights + ' night' + plural(nights, '', 's')
                : 'Estimated total';
        }
        if (totalBox) { totalBox.textContent = fmt(grand); }
        if (guestsBox && SELECTED.length) {
            guestsBox.textContent = gpTotal >= 1
                ? gpTotal + ' guest' + plural(gpTotal, '', 's') : '\u2014';
        }
        if (countPanel) {
            countPanel.textContent = SELECTED.length >= 1
                ? SELECTED.length + ' ' + ITEM_PLURAL
                    + (SELECTED.length === 1 ? '' : 's') + ' selected'
                : '0 selected';
        }
        if (countSelected) { countSelected.textContent = SELECTED.length; }
        if (divider) { divider.style.display = SELECTED.length ? 'block' : 'none'; }

        if (linesBox) {
            if (!SELECTED.length) {
                linesBox.innerHTML = '<div class="ag-pb-row"><span>Select at least one '
                    + esc(ITEM_PLURAL) + '</span><b>\u2014</b></div>';
            } else {
                linesBox.innerHTML = rows.map(function (r, i) {
                    var html = '<div class="ag-pb-row"><span>' + esc(ITEM) + ' ' + (i + 1) + ' &middot; '
                        + esc(r.s.number) + ' <small class="meta">' + esc(r.s.name) + '</small>'
                        + (r.t.overIncluded ? ' <small class="meta">+' + r.t.overIncluded
                            + ' extra guest(s)</small>' : '') +
                        '</span><b>' + fmt(r.t.rate) + ' \u00d7 ' + r.t.units + '</b></div>';
                    if (r.t.extraTotal > 0) {
                        html += '<div class="ag-pb-row"><span>&nbsp;&nbsp;+ '
                            + esc((r.s.charge || {}).extra_label || 'Extra guest') + ' charge</span><b>'
                            + fmt(r.t.extraTotal) + '</b></div>';
                    }
                    if (r.svcTotal > 0) {
                        html += '<div class="ag-pb-row"><span>&nbsp;&nbsp;+ Services</span><b>'
                            + fmt(r.svcTotal) + '</b></div>';
                    }
                    return html;
                }).join('');
            }
        }
        if (continueBtn) {
            continueBtn.disabled = !SELECTED.length;
        }

        renderSummary(rows, baseSub, extraSub, svcSub, grand, okDates);
        updateGuestTotals(rows);
    }

    function renderSummary(rows, baseSub, extraSub, svcSub, grand, okDates) {
        if (!compBox) { return; }
        if (!SELECTED.length) {
            compBox.innerHTML = '<div class="card card-pad bk-summary"><h3>Booking computation</h3>'
                + '<p class="bk-sum-hint">Select at least one ' + esc(ITEM_PLURAL)
                + ' to see the full computation.</p></div>';
            return;
        }
        var head = (SHOW_DURATION && okDates)
            ? CHARGE_SECTION + ' \u00d7 ' + rows[0].nights + ' night'
                + ((rows[0].nights === 1) ? '' : 's')
            : CHARGE_SECTION;

        var body = rows.map(function (r, i) {
            var t = r.t;
            var unitLabel = t.units + ' ' + plural(t.units, t.unit, t.unit + 's');
            var html = '<div class="bk-sum-row"><span>' + esc(ITEM) + ' ' + (i + 1) + ' &middot; '
                + esc(r.s.name) + ' (' + esc(r.s.number) + ')</span><b>' + fmt(t.base) + '</b></div>';
            html += '<div class="bk-sum-row" style="padding-left:14px"><span>' + fmt(t.rate)
                + ' \u00d7 ' + unitLabel + '</span><b>' + fmt(t.base) + '</b></div>';
            if (t.extraTotal > 0) {
                html += '<div class="bk-sum-row" style="padding-left:14px"><span class="bk-sum-extra">+ '
                    + t.overIncluded + ' extra guest(s) '
                    + esc((r.s.charge || {}).extra_label || 'charge').toLowerCase()
                    + '</span><b class="bk-sum-extra">' + fmt(t.extraTotal) + '</b></div>';
            }
            if (r.svcNames.length) {
                html += '<div class="bk-sum-row" style="padding-left:14px"><span>+ '
                    + esc(r.svcNames.join(', ')) + '</span><b>' + fmt(r.svcTotal) + '</b></div>';
            }
            return html;
        }).join('');

        var servicesSection = svcSub > 0
            ? '<div class="bk-sum-section">Service charges</div>'
              + '<div class="bk-sum-row"><span>Services across all ' + esc(ITEM_PLURAL)
                + '</span><b>' + fmt(svcSub) + '</b></div>'
              + '<div class="bk-sum-subtotal"><span>Subtotal</span><span>'
                + fmt(baseSub + extraSub + svcSub) + '</span></div>'
            : '<div class="bk-sum-subtotal"><span>Subtotal</span><span>'
                + fmt(baseSub + extraSub) + '</span></div>';

        compBox.innerHTML =
            '<div class="card card-pad bk-summary">' +
                '<h3>Booking computation</h3>' +
                '<p class="bk-sum-hint">' + esc(HINT) + '</p>' +
                '<div class="bk-sum-section">' + esc(head) + '</div>' + body + servicesSection +
                '<div class="bk-sum-total"><span>Grand total</span><b>' + fmt(grand) + '</b></div>' +
            '</div>';
    }

    function updateGuestTotals(rows) {
        rows.forEach(function (r, i) {
            var el = document.querySelector('[data-guest-total="' + i + '"]');
            if (el) {
                el.innerHTML = r.t.guests + ' <small class="meta">of '
                    + r.s.max_guests + ' max</small>';
            }
        });
    }

    /* ------------------------------------------------- guest info modal
       Same behaviour as the Hotels page: selecting an item opens the modal
       instead of scrolling to the form, the page behind stays locked, and the
       fields keep their existing names so the booking submit is unchanged. */

    function guestModalOpen() {
        return !!(guestModal && guestModal.classList.contains('open'));
    }

    function detailsOpen() {
        var m = document.getElementById('itemModal');
        return !!(m && m.classList.contains('open'));
    }

    function modalFocusables(root) {
        return Array.prototype.slice.call(root.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]),'
            + ' textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
            .filter(function (el) { return el.getClientRects().length > 0; });
    }

    function openGuestModal(itemId) {
        if (!guestModal || !SELECTED.length) { return; }
        var idx = (itemId === undefined || itemId === null) ? 0 : findIndex(itemId);
        if (idx === -1) { return; }
        syncFromDom();
        renderSections();
        var s = SELECTED[idx];
        if (guestModalSub) {
            guestModalSub.textContent = (SELECTED.length > 1
                ? ITEM + ' ' + (idx + 1) + ' of ' + SELECTED.length + ' · '
                : '') + s.name
                + (s.number && s.number !== s.name ? ' · ' + s.number : '')
                + '. Please provide the guest details below.';
        }
        guestModal.classList.add('open');
        document.body.style.overflow = 'hidden';
        var card = guestBox.querySelector('.bk-guest-card:not([hidden])');
        var target = card && card.querySelector(
            'input:not([disabled]):not([readonly]), select:not([disabled]), textarea:not([disabled])'
        );
        // Wait for the modal to paint before focusing an input. Calling
        // getClientRects() for every field here forced synchronous layout and
        // could stall category selection on slower devices.
        if (target) {
            requestAnimationFrame(function () {
                if (!guestModalOpen() || !target.isConnected) { return; }
                try { target.focus({ preventScroll: true }); }
                catch (err) { target.focus(); }
            });
        }
        guestModalBodyReset();
    }

    function guestModalBodyReset() {
        var body = guestModal ? guestModal.querySelector('.rm-modal-body') : null;
        if (body) { body.scrollTop = 0; }
    }

    function closeGuestModal() {
        if (!guestModal || !guestModalOpen()) { return; }
        syncFromDom();
        computeAll();
        guestModal.classList.remove('open');
        if (!detailsOpen()) { document.body.style.overflow = ''; }
        // preventScroll: returning focus must not move the page.
        if (guestOpener && guestOpener.focus) {
            try { guestOpener.focus({ preventScroll: true }); }
            catch (err) { guestOpener.focus(); }
        }
        guestOpener = null;
    }

    /* ---------------------------------------------------------- validation
       Same client-side rules and same inline error boxes as the Hotels page. */
    function validateAll() {
        var errs = [];
        SELECTED.forEach(function (s, i) {
            var g = s.guest;
            var msgs = [];
            if (g.first_name.trim() === '' || g.last_name.trim() === '' ||
                g.email.trim() === '' || g.contact.trim() === '' ||
                (g.adults + g.children) < 1) {
                msgs.push('Please complete the required guest information for '
                    + ITEM + ' ' + (i + 1) + '.');
            }
            if (g.email.trim() !== '' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(g.email.trim())) {
                msgs.push('Enter a valid email for ' + ITEM + ' ' + (i + 1) + '.');
            }
            if (g.contact.trim() !== '' && /\D/.test(g.contact.trim())) {
                msgs.push('Contact number for ' + ITEM + ' ' + (i + 1)
                    + ' must contain numbers only.');
            }
            if ((g.adults + g.children) > s.max_guests) {
                msgs.push(ITEM + ' ' + (i + 1) + ' (' + s.number + ') allows up to '
                    + s.max_guests + ' guest(s); you entered ' + (g.adults + g.children) + '.');
            }
            if (msgs.length) { errs.push({ index: i, msgs: msgs }); }
        });
        return errs;
    }

    function showErrors(errs) {
        Array.prototype.forEach.call(document.querySelectorAll('.bk-guest-card'), function (sec) {
            sec.classList.remove('has-error');
            var box = sec.querySelector('.bk-guest-err');
            if (box) { box.innerHTML = ''; }
        });
        var firstBad = null;
        errs.forEach(function (e) {
            var sec = document.querySelector('[data-guest-section="' + e.index + '"]');
            if (!sec) { return; }
            sec.classList.add('has-error');
            var box = sec.querySelector('.bk-guest-err');
            if (box) {
                box.innerHTML = '<b>' + esc(ITEM) + ' ' + (e.index + 1) + '</b>'
                    + '<ul style="margin:4px 0 0 16px">'
                    + e.msgs.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join('')
                    + '</ul>';
            }
            if (!firstBad) { firstBad = sec; }
        });
        if (firstBad && firstBad.scrollIntoView) {
            firstBad.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function renderAll() {
        renderHiddenIds();
        renderSections();
        renderCardStates();
        computeAll();
    }

    /* ------------------------------------------------------ details modal */

    function openDetails(id) {
        var d = DETAILS[String(id)];
        var modal = document.getElementById('itemModal');
        var body = document.getElementById('itemModalBody');
        var sub = document.getElementById('itemModalSub');
        var full = document.getElementById('itemModalFull');
        var title = document.getElementById('itemModalTitle');
        if (!d || !modal || !body) { return; }

        if (title) { title.textContent = d.name || 'Details'; }
        if (sub) { sub.textContent = (d.number ? d.number + ' \u00b7 ' : '') + (d.est_name || ''); }
        if (full && d.detail_url) { full.href = d.detail_url; }

        var html = '';
        if (d.photos && d.photos.length) {
            html += '<div class="rm-modal-hero"><img src="' + esc(d.photos[0])
                + '" alt="' + esc(d.name) + '"></div>'
              + '<div class="rm-modal-strip">' + d.photos.map(function (src, i) {
                  return '<img src="' + esc(src) + '" alt="Photo ' + (i + 1) + '"'
                      + ' data-modal-shot="' + i + '"' + (i === 0 ? ' class="is-active"' : '')
                      + '>';
              }).join('') + '</div>';
        }
        html += '<div class="rm-modal-sec"><div class="rm-modal-grid">';
        (d.facts || []).forEach(function (f) {
            html += '<div><b>' + esc(f[1]) + '</b><small>' + esc(f[2]) + '</small></div>';
        });
        if (d.status) { html += '<div><b>' + esc(d.status) + '</b><small>Status</small></div>'; }
        if (d.rate_display) {
            html += '<div><b>' + esc(d.rate_display) + '</b><small>per ' + esc(d.unit_noun) + '</small></div>';
        }
        if (d.total_display) {
            html += '<div><b>' + esc(d.total_display) + '</b><small>Total</small></div>';
        }
        html += '</div></div>';
        if (d.description) {
            html += '<div class="rm-modal-sec"><h4>Description</h4><div class="rm-modal-text">'
                + esc(d.description) + '</div></div>';
        }
        if (d.features && d.features.length) {
            html += '<div class="rm-modal-sec"><h4>Features</h4><div class="rm-amen-grid">'
                + d.features.map(function (f) { return '<span class="rm-amen">' + esc(f) + '</span>'; }).join('')
                + '</div></div>';
        }
        if (d.amenities && d.amenities.length) {
            html += '<div class="rm-modal-sec"><h4>Features &amp; options</h4><div class="rm-amen-grid">'
                + d.amenities.map(function (a) { return '<span class="rm-amen">' + esc(a) + '</span>'; }).join('')
                + '</div></div>';
        }
        body.innerHTML = html;
        modal.classList.add('open');
        document.body.style.overflow = 'hidden';
        /* Always open on the header + top of the photo, never on the scroll
           position left behind by a previously viewed item. */
        body.scrollTop = 0;
        requestAnimationFrame(function () { body.scrollTop = 0; });

        Array.prototype.forEach.call(modal.querySelectorAll('[data-modal-shot]'), function (img) {
            img.addEventListener('click', function () {
                var heroImg = body.querySelector('.rm-modal-hero img');
                if (heroImg) {
                    heroImg.src = img.getAttribute('src');
                }
                Array.prototype.forEach.call(body.querySelectorAll('[data-modal-shot]'), function (o) {
                    o.classList.remove('is-active');
                });
                img.classList.add('is-active');
            });
        });
    }

    function closeDetails() {
        var modal = document.getElementById('itemModal');
        if (!modal) { return; }
        modal.classList.remove('open');
        document.body.style.overflow = '';
    }

    /* ------------------------------------------------------ photo galleries */

    Array.prototype.forEach.call(document.querySelectorAll('[data-item-card]'), function (card) {
        var shots = card.querySelectorAll('.rm-shot');
        if (!shots.length) { return; }
        var index = 0;
        var counter = card.querySelector('[data-shot-index]');
        function show(next) {
            index = (next + shots.length) % shots.length;
            Array.prototype.forEach.call(shots, function (s, i) {
                s.classList.toggle('is-active', i === index);
            });
            Array.prototype.forEach.call(card.querySelectorAll('[data-shot-thumb]'), function (t, i) {
                t.classList.toggle('is-active', i === index);
            });
            if (counter) { counter.textContent = index + 1; }
        }
        var prev = card.querySelector('[data-shot-prev]');
        var next = card.querySelector('[data-shot-next]');
        if (prev) { prev.addEventListener('click', function (e) { e.stopPropagation(); show(index - 1); }); }
        if (next) { next.addEventListener('click', function (e) { e.stopPropagation(); show(index + 1); }); }
        Array.prototype.forEach.call(card.querySelectorAll('[data-shot-thumb]'), function (t, i) {
            t.addEventListener('click', function (e) { e.stopPropagation(); show(i); });
        });
    });

    /* ------------------------------------------------------------- wiring */

    document.addEventListener('click', function (ev) {
        var guestOpen = ev.target.closest('[data-guest-open]');
        if (guestOpen) {
            ev.preventDefault();
            ev.stopPropagation();
            guestOpener = guestOpen;
            openGuestModal(guestOpen.getAttribute('data-guest-open'));
            return;
        }
        if (ev.target.closest('[data-guest-close]')) { closeGuestModal(); return; }
        var book = ev.target.closest('[data-item-book]');
        if (book) {
            var id = book.getAttribute('data-item-book');
            syncFromDom();
            toggleItem(id);
            renderAll();
            // Keep selection immediate so users can select several items
            // without a modal covering the remaining cards. Guest details are
            // available from the newly shown Guest info button; submitting the
            // booking with incomplete details opens the same modal for them.
            return;
        }
        var open = ev.target.closest('[data-open-details]');
        if (open) { openDetails(open.getAttribute('data-open-details')); return; }
        if (ev.target.closest('[data-close-modal]')) { closeDetails(); return; }
        if (ev.target.id === 'itemModal') { closeDetails(); }
        if (ev.target.id === 'guestModal') { closeGuestModal(); }
    });

    document.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Escape') { return; }
        if (guestModalOpen()) { closeGuestModal(); return; }
        var modal = document.getElementById('itemModal');
        if (modal && modal.classList.contains('open')) { closeDetails(); }
    });

    // Keep Tab inside the guest modal while it is open.
    if (guestModal) {
        guestModal.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Tab') { return; }
            var f = modalFocusables(guestModal);
            if (!f.length) { return; }
            var first = f[0], last = f[f.length - 1];
            if (ev.shiftKey && document.activeElement === first) {
                ev.preventDefault(); last.focus();
            } else if (!ev.shiftKey && document.activeElement === last) {
                ev.preventDefault(); first.focus();
            }
        });
        guestModal.addEventListener('click', function (ev) {
            if (ev.target === guestModal) { closeGuestModal(); }
        });
    }

    if (guestSave) {
        guestSave.addEventListener('click', function () {
            syncFromDom();
            var errs = validateAll();
            if (errs.length) { showErrors(errs); return; }
            closeGuestModal();
            document.dispatchEvent(new CustomEvent('atrue:establishment-guest-info-complete'));
        });
    }

    // When validation fails the guest fields live in the modal, so surface it -
    // otherwise the errors render inside a hidden overlay and look like nothing
    // happened. openGuestModal() rebuilds the sections, so it must run before
    // showErrors() paints into them.
    function revealGuestErrors(errs) {
        var target = errs[0] && SELECTED[errs[0].index];
        if (!guestModalOpen()) {
            openGuestModal(target ? target.item_id : null);
        }
        showErrors(errs);
    }

    // Guest block: Remove button + live recompute, exactly like the Hotels page.
    if (guestBox) {
        guestBox.addEventListener('input', function () {
            if (SELECTED.length) { syncFromDom(); computeAll(); }
        });
        guestBox.addEventListener('change', function () {
            if (SELECTED.length) { syncFromDom(); computeAll(); }
        });
        guestBox.addEventListener('click', function (ev) {
            var rm = ev.target.closest('[data-remove-item]');
            if (rm) {
                syncFromDom();
                removeItem(rm.getAttribute('data-remove-item'));
                renderAll();
                // Removing the last item leaves the modal with nothing to show.
                if (!SELECTED.length && guestModalOpen()) { closeGuestModal(); }
            }
        });
    }

    // Live date changes from the search bar, like the Hotels page.
    var searchCi = document.getElementById('searchCheckIn');
    var searchCo = document.getElementById('searchCheckOut');
    function syncDates() {
        if (searchCi && searchCi.value && checkInEl) { checkInEl.value = searchCi.value; }
        if (searchCo && searchCo.value && checkOutEl) { checkOutEl.value = searchCo.value; }
        computeAll();
    }
    if (searchCi) { searchCi.addEventListener('change', syncDates); }
    if (searchCo) { searchCo.addEventListener('change', syncDates); }

    form.addEventListener('submit', function (ev) {
        if (!SELECTED.length) { ev.preventDefault(); return; }
        syncFromDom();
        var errs = validateAll();
        if (errs.length) {
            ev.preventDefault();
            revealGuestErrors(errs);
            return;
        }
        if (continueBtn) {
            continueBtn.disabled = true;
            continueBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Booking...';
        }
    });

    /* ---------------------------------------------------------- seeding
       Restore the selection after a server validation error, then layer the
       guest values the server read back, exactly as rooms.js does with
       PRESELECTED. */
    SELECTED_IDS.forEach(function (id) { addItem(id); });
    if (SELECTED.length) {
        PRESELECTED.forEach(function (p, i) {
            if (!SELECTED[i] || !p) { return; }
            SELECTED[i].guest = {
                first_name: p.first_name || '',
                middle_name: p.middle_name || '',
                last_name: p.last_name || '',
                email: p.email || '',
                contact: p.contact || '',
                adults: Number(p.adults) || 1,
                children: Number(p.children) || 0,
                special_request: p.special_request || '',
                services: (p.services || []).map(Number),
                amenities: (p.amenities || []).map(Number)
            };
        });
    }

    renderAll();
})();
