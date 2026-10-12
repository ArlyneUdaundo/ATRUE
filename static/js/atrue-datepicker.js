/* ============================================================
   ATRUE Date Picker — single reusable calendar component.
   Auto-enhances every <input type="date"> (native input remains
   in the form as the value store so backend contracts are kept).
   Supports:
     - Single-date mode (restaurants, activities, tours, DOB, ...)
     - Date-range mode (flight departure/return, hotel check-in/out)
   ============================================================ */
(function () {
    'use strict';

    var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'];
    var MAGIC = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

    var RANGE_PAIRS = [
        ['check_in', 'check_out'],
        ['checkin', 'checkout'],
        ['departure_date', 'return_date'],
        ['start_date', 'end_date'],
        ['pickup_date', 'return_date'],
        ['from_date', 'to_date'],
        ['tour_start_date', 'tour_end_date'],
    ];

    var CONTROLLERS = new WeakMap();

    function normalizeName(value) {
        return (value || '').toLowerCase().trim();
    }

    function isIndependentEndpoint(input) {
        return ['check_in', 'check_out', 'checkin', 'checkout'].indexOf(
            normalizeName(input && input.getAttribute('name'))) !== -1;
    }

    function pad2(n) {
        return n < 10 ? '0' + n : '' + n;
    }

    function toISO(d) {
        return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    }

    function parseISO(text) {
        if (!text) return null;
        var parts = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(text).trim());
        if (!parts) return null;
        var d = new Date(+parts[1], +parts[2] - 1, +parts[3], 12, 0, 0, 0);
        return isNaN(d.getTime()) ? null : d;
    }

    function startOfMonth(d) {
        return new Date(d.getFullYear(), d.getMonth(), 1, 12, 0, 0, 0);
    }

    function addMonths(d, count) {
        var out = new Date(d.getFullYear(), d.getMonth() + count, 1, 12, 0, 0, 0);
        return out;
    }

    function mondayIndex(d) {
        return (d.getDay() + 6) % 7;
    }

    function sameDay(a, b) {
        return a && b &&
            a.getFullYear() === b.getFullYear() &&
            a.getMonth() === b.getMonth() &&
            a.getDate() === b.getDate();
    }

    function isBefore(a, b) {
        return a && b && a.getTime() < b.getTime();
    }

    function formatShort(d) {
        return MAGIC[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
    }

    function formatLong(d) {
        return MONTHS[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
    }

    function readDisabledISO(input) {
        var out = {};
        var raw = input && input.getAttribute ? input.getAttribute('data-adp-disabled') : null;
        if (raw) {
            String(raw).split(',').forEach(function (token) {
                var iso = String(token).trim();
                if (iso) out[iso] = true;
            });
        }
        return out;
    }

    function findRangePair(input) {
        var form = input.closest('form');
        if (!form) return null;
        var name = normalizeName(input.getAttribute('name'));
        if (!name) return null;
        for (var i = 0; i < RANGE_PAIRS.length; i++) {
            var first = RANGE_PAIRS[i][0];
            var second = RANGE_PAIRS[i][1];
            if (name !== first && name !== second) continue;
            var partnerName = name === first ? second : first;
            var partner = form.querySelector('input[name="' + partnerName + '"]');
            if (partner && partner.getAttribute('type') === 'date') {
                var isStart = name === first;
                return {
                    start: isStart ? input : partner,
                    end: isStart ? partner : input
                };
            }
        }
        return null;
    }

    function effectiveMin(pair) {
        var min = [];
        if (pair) {
            [pair.start, pair.end].forEach(function (el) {
                if (el && el.min) min.push(el.min);
            });
        }
        min.sort();
        return min.length ? min[min.length - 1] : null;
    }

    function effectiveMax(pair) {
        var max = [];
        if (pair) {
            [pair.start, pair.end].forEach(function (el) {
                if (el && el.max) max.push(el.max);
            });
        }
        max.sort();
        return max.length ? max[0] : null;
    }

    function buildDateCell(day, opts) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'adp-day';
        btn.textContent = day.getDate();
        btn.dataset.dayiso = toISO(day);
        if (opts.disabled) btn.disabled = true;
        return btn;
    }

    function renderTrigger(input, value) {
        var anchor = input.closest('.adp-anchor');
        var placeholder = anchor ? anchor.querySelector('.adp-trigger-placeholder') : null;
        if (!placeholder) return;
        var triggerValue = anchor.querySelector('.adp-trigger-value');
        if (!triggerValue) return;
        if (value) {
            placeholder.style.display = 'none';
            triggerValue.textContent = value;
            triggerValue.style.display = '';
            anchor.classList.add('has-value');
        } else {
            placeholder.style.display = '';
            triggerValue.style.display = 'none';
            anchor.classList.remove('has-value');
        }
    }

    function createController(input, pair) {
        var endpointMode = !!(pair && isIndependentEndpoint(input));
        var range = !!(pair && !endpointMode && !pair.end.disabled);
        var controller = {
            input: input,
            pair: pair,
            endpointMode: endpointMode,
            range: range,
            popup: null,
            popupShape: null,
            openedBy: null,
            startDate: pair ? (parseISO(pair.start.value) || null) : null,
            endDate: pair ? (parseISO(pair.end.value) || null) : null,
            selected: range ? null : (parseISO(input.value) || null),
            base: startOfMonth(new Date()),
            minISO: pair && !endpointMode ? effectiveMin(pair) : (input.min || null),
            maxISO: pair && !endpointMode ? effectiveMax(pair) : (input.max || null),
            disabledISO: {}
        };
        if (range && controller.startDate && controller.endDate &&
                isBefore(controller.endDate, controller.startDate)) {
            controller.endDate = null;
        }
        return controller;
    }

    function buildPopup(controller) {
        var popup = document.createElement('div');
        popup.className = 'adp-popup';
        popup.setAttribute('role', 'dialog');
        popup.setAttribute('aria-modal', 'false');
        popup.setAttribute('aria-label', controller.range ? 'Select dates' : 'Select date');

        popup.addEventListener('click', function (event) {
            var nav = event.target.closest('.adp-nav');
            if (!nav || nav.disabled) return;
            event.preventDefault();
            event.stopPropagation();
            controller.base = addMonths(controller.base, nav.classList.contains('adp-nav-next') ? 1 : -1);
            renderMonths(controller);
        });
        if (controller.range) popup.classList.add('is-range');

        var head = document.createElement('div');
        head.className = 'adp-head';

        var title = document.createElement('span');
        title.className = 'adp-title';
        title.innerHTML = '<i class="fas fa-calendar-days"></i> ' +
            (controller.range ? 'Select dates' : 'Select date');

        var x = document.createElement('button');
        x.type = 'button';
        x.className = 'adp-x';
        x.setAttribute('aria-label', 'Close date picker');
        x.innerHTML = '<i class="fas fa-xmark"></i>';
        x.addEventListener('click', function () {
            closePopup(controller);
        });

        head.appendChild(title);
        head.appendChild(x);

        var display = document.createElement('div');
        display.className = 'adp-display';
        var cells = document.createElement('div');
        cells.className = 'adp-display-cells';
        if (controller.range) {
            var rl = rangeLabelSet(controller);
            cells.appendChild(displayCell(rl.aLabel, 'departure'));
            cells.appendChild(displayCell(rl.bLabel, 'return'));
        } else {
            cells.appendChild(displayCell('Selected date', 'single', true));
        }
        display.appendChild(cells);

        var months = document.createElement('div');
        months.className = 'adp-months';

        var monthCount = controller.range ? 2 : 1;
        for (var i = 0; i < monthCount; i++) {
            var month = document.createElement('div');
            month.className = 'adp-month';
            month.dataset.adpMonth = i;
            months.appendChild(month);
        }

        var footer = document.createElement('div');
        footer.className = 'adp-footer';

        var clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'adp-btn-clear';
        clear.textContent = 'Clear';
        clear.addEventListener('click', function () {
            reset(controller);
        });
        footer.appendChild(clear);

        var foot = document.createElement('div');
        foot.className = 'adp-foot';

        var done = document.createElement('button');
        done.type = 'button';
        done.className = 'adp-btn-done';
        done.textContent = 'Done';
        done.addEventListener('click', function () {
            commit(controller);
        });
        foot.appendChild(done);

        popup.appendChild(head);
        popup.appendChild(display);
        popup.appendChild(months);
        popup.appendChild(footer);
        popup.appendChild(foot);
        return popup;
    }

    function displayCell(labelText, key, single) {
        var cell = document.createElement('div');
        cell.className = 'adp-display-cell' + (single ? ' adp-display-single' : '');
        cell.classList.add('is-empty');
        var label = document.createElement('div');
        label.className = 'adp-display-cell-label';
        label.textContent = labelText;
        var value = document.createElement('div');
        value.className = 'adp-display-cell-value';
        value.dataset.adpDisplayValue = key;
        value.textContent = '—';
        cell.appendChild(label);
        cell.appendChild(value);
        return cell;
    }

    function refreshControllerState(controller) {
        var input = controller.input;
        controller.minISO = controller.pair && !controller.endpointMode ? effectiveMin(controller.pair) : (input.min || null);
        controller.maxISO = controller.pair && !controller.endpointMode ? effectiveMax(controller.pair) : (input.max || null);
        controller.disabledISO = readDisabledISO(input);
        if (controller.pair && !controller.endpointMode && controller.pair.end && controller.pair.end !== input) {
            controller.disabledISO = Object.assign(controller.disabledISO,
                readDisabledISO(controller.pair.end));
        }
    }

    function fieldLabel(input) {
        if (!input || !input.parentElement) return '';
        var labelEl = input.parentElement.querySelector('label');
        if (!labelEl && input.id) {
            labelEl = document.querySelector('label[for="' + input.id + '"]');
        }
        if (!labelEl) {
            var prev = input.previousElementSibling;
            if (prev && prev.tagName === 'LABEL') labelEl = prev;
        }
        return labelEl ? (labelEl.textContent || '') : '';
    }

    function parseLabel(text) {
        if (!text) return '';
        return text.replace(/\s*[:：]\s*$/, '').slice(0, 18).trim();
    }

    function rangeLabelSet(controller) {
        var start = controller.pair && controller.pair.start;
        var end = controller.pair && controller.pair.end;
        var aText = parseLabel(fieldLabel(start));
        var bText = parseLabel(fieldLabel(end));
        return {
            aLabel: aText ? aText + ':' : 'Start date:',
            bLabel: bText ? bText + ':' : 'End date:'
        };
    }

    function renderMonths(controller) {
        var popup = controller.popup;
        if (!popup) return;
        var base = controller.base;
        var months = popup.querySelectorAll('.adp-month');
        var total = months.length;

        for (var i = 0; i < total; i++) {
            var visible = addMonths(base, i);
            var title = document.createElement('div');
            title.className = 'adp-month-title';

            var prev = document.createElement('button');
            prev.type = 'button';
            prev.className = 'adp-nav adp-nav-prev';
            prev.setAttribute('aria-label', 'Previous month');
            prev.innerHTML = '<i class="fas fa-chevron-left"></i>';

            var caption = document.createElement('span');
            caption.className = 'adp-month-title-text';
            caption.textContent = MONTHS[visible.getMonth()] + ' ' + visible.getFullYear();

            var next = document.createElement('button');
            next.type = 'button';
            next.className = 'adp-nav adp-nav-next';
            next.setAttribute('aria-label', 'Next month');
            next.innerHTML = '<i class="fas fa-chevron-right"></i>';

            title.appendChild(prev);
            title.appendChild(caption);
            title.appendChild(next);

            var weekdays = document.createElement('div');
            weekdays.className = 'adp-weekdays';
            WEEKDAYS.forEach(function (label) {
                var cell = document.createElement('span');
                cell.className = 'adp-weekday';
                cell.textContent = label;
                weekdays.appendChild(cell);
            });

            var days = document.createElement('div');
            days.className = 'adp-days';
            var minDate = parseISO(controller.minISO);
            var maxDate = parseISO(controller.maxISO);
            var disabledSet = controller.disabledISO || {};
            var gridStart = mondayIndex(visible);
            var offsetMonth = addMonths(visible, 0);
            var first = new Date(offsetMonth.getFullYear(), offsetMonth.getMonth(), 1, 12, 0, 0, 0);
            var daysInMonth = new Date(offsetMonth.getFullYear(), offsetMonth.getMonth() + 1, 0, 12, 0, 0, 0).getDate();

            for (var g = 0; g < gridStart; g++) {
                var empty = document.createElement('span');
                empty.className = 'adp-day is-empty';
                days.appendChild(empty);
            }

            for (var day = 1; day <= daysInMonth; day++) {
                var date = new Date(first.getFullYear(), first.getMonth(), day, 12, 0, 0, 0);
                var disabled = (minDate && isBefore(date, minDate)) ||
                    (maxDate && isBefore(maxDate, date)) ||
                    !!disabledSet[toISO(date)];
                var cell = buildDateCell(date, { disabled: disabled });
                if (!controller.range && controller.selected && sameDay(date, controller.selected)) cell.classList.add('is-selected');
                cell.addEventListener('click', function () {
                    selectDate(controller, this.dataset.dayiso);
                });
                days.appendChild(cell);
            }

            var monthEl = months[i];
            monthEl.replaceChildren(title, weekdays, days);
            updateNavState(controller, prev, next);
        }
        applyRangeClasses(controller);
        renderSummary(controller);
    }

    function updateNavState(controller, prev, next) {
        var minDate = parseISO(controller.minISO);
        var maxDate = parseISO(controller.maxISO);
        var firstVisible = addMonths(controller.base, 0);
        var lastVisible = addMonths(controller.base, controller.range ? 1 : 0);
        var lastDay = new Date(lastVisible.getFullYear(), lastVisible.getMonth() + 1, 0, 12, 0, 0, 0);
        if (prev) prev.disabled = !!(minDate && isBefore(lastDay, minDate));
        if (next) next.disabled = !!(maxDate && isBefore(maxDate, lastDay));
    }

    function applyRangeClasses(controller) {
        var popup = controller.popup;
        if (!popup) return;
        var start = controller.range ? controller.startDate : null;
        var end = controller.range ? controller.endDate : null;
        popup.querySelectorAll('.adp-day').forEach(function (day) {
            day.classList.remove('in-range', 'is-start', 'is-end', 'is-selected');
            var iso = day.dataset.dayiso;
            var date = parseISO(iso);
            if (!date) return;
            if (!controller.range && controller.selected && sameDay(date, controller.selected)) {
                day.classList.add('is-selected');
            }
            if (start && sameDay(date, start)) day.classList.add('is-start');
            if (end && sameDay(date, end)) day.classList.add('is-end');
            if (start && end && iso > toISO(start) && iso < toISO(end)) {
                day.classList.add('in-range');
            }
        });
    }

    function renderSummary(controller) {
        if (!controller.popup) return;
        var startValue = controller.range ? controller.startDate : controller.selected;
        var endValue = controller.range ? controller.endDate : null;
        controller.popup.querySelectorAll('[data-adp-display-value]').forEach(function (el) {
            var key = el.dataset.adpDisplayValue;
            var date = key === 'departure' ? controller.startDate :
                key === 'return' ? controller.endDate : controller.selected;
            var cell = el.closest('.adp-display-cell');
            if (cell) {
                if (date) {
                    el.textContent = formatLong(date);
                    cell.classList.remove('is-empty');
                } else {
                    el.textContent = '—';
                    cell.classList.add('is-empty');
                }
            }
        });
        var done = controller.popup.querySelector('.adp-btn-done');
        if (done) done.disabled = controller.range
            ? !(startValue && endValue)
            : !controller.selected;
    }

    function selectDate(controller, iso) {
        var date = parseISO(iso);
        if (!date) return;
        if (controller.range) {
            if (!controller.startDate || controller.endDate) {
                controller.startDate = date;
                controller.endDate = null;
            } else if (isBefore(date, controller.startDate)) {
                controller.startDate = date;
                controller.endDate = null;
            } else {
                controller.endDate = date;
            }
        } else {
            controller.selected = date;
        }
        applyRangeClasses(controller);
        renderSummary(controller);
    }

    function commit(controller) {
        if (controller.range) {
            if (controller.startDate && controller.endDate) {
                setInputValue(controller.pair.start, toISO(controller.startDate));
                setInputValue(controller.pair.end, toISO(controller.endDate));
                closePopup(controller);
            }
        } else {
            if (controller.selected) {
                setInputValue(controller.input, toISO(controller.selected));
                closePopup(controller);
            }
        }
    }

    function reset(controller) {
        var inputs = controller.range
            ? [controller.pair.start, controller.pair.end]
            : [controller.input];
        if (controller.range) {
            controller.startDate = null;
            controller.endDate = null;
        } else {
            controller.selected = null;
        }
        inputs.forEach(function (input) {
            if (!input) return;
            input.value = '';
            renderTrigger(input, '');
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        });
        applyRangeClasses(controller);
        renderSummary(controller);
    }

    function setInputValue(input, iso) {
        if (!input) return;
        input.value = iso;
        renderTrigger(input, formatShort(parseISO(iso)));
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function openPopup(controller, anchor) {
        var input = controller.input;
        controller.range = !!(controller.pair && !controller.endpointMode && !controller.pair.end.disabled);
        controller.startDate = controller.pair ? (parseISO(controller.pair.start.value) || null) : null;
        controller.endDate = controller.pair ? (parseISO(controller.pair.end.value) || null) : null;
        controller.selected = controller.range ? null : (parseISO(input.value) || null);
        if (controller.range && controller.startDate && controller.endDate &&
                isBefore(controller.endDate, controller.startDate)) {
            controller.endDate = null;
        }
        controller.base = startOfMonth(controller.range
            ? (controller.startDate || new Date())
            : (controller.selected || new Date()));
        refreshControllerState(controller);

        if (!controller.popup || controller.popupShape !== controller.range) {
            if (controller.popup && controller.popup.parentNode) {
                controller.popup.parentNode.removeChild(controller.popup);
            }
            if (controller.popup) controller.popup.remove();
            controller.popup = buildPopup(controller);
            controller.popupShape = controller.range;
        }

        if (controller.popup.parentNode) {
            controller.popup.parentNode.removeChild(controller.popup);
        }
        document.body.appendChild(controller.popup);
        controller.openedBy = anchor;

        var popupTrigger = anchor.querySelector('.adp-trigger');
        if (popupTrigger) {
            popupTrigger.setAttribute('aria-expanded', 'true');
        }

        positionPopup(anchor, controller.popup);
        renderMonths(controller);
        controller.popup.classList.add('is-open');
        focusFirstDay(controller.popup);
    }

    function positionPopup(anchor, popup) {
        popup.style.position = 'fixed';
        popup.style.left = '0px';
        popup.style.top = '0px';
        popup.style.right = 'auto';
        popup.style.bottom = 'auto';
        popup.style.maxHeight = 'calc(100vh - 16px)';
        popup.style.overflowY = 'auto';

        var prevDisplay = popup.style.display;
        popup.style.display = 'block';
        popup.style.visibility = 'hidden';
        var pr = popup.getBoundingClientRect();
        var ar = anchor.getBoundingClientRect();
        popup.style.visibility = '';
        popup.style.display = prevDisplay;

        var margin = 8;
        var left = Math.min(ar.left, window.innerWidth - pr.width - margin);
        left = Math.max(margin, left);
        var top = ar.bottom + margin;
        if (top + pr.height > window.innerHeight - margin && ar.top - pr.height - margin >= margin) {
            top = ar.top - pr.height - margin;
        } else if (top + pr.height > window.innerHeight - margin) {
            top = Math.max(margin, window.innerHeight - pr.height - margin);
        }
        popup.style.left = left + 'px';
        popup.style.top = top + 'px';
    }

    function focusFirstDay(popup) {
        var firstEnabled = popup.querySelector('.adp-day:not(:disabled):not(.is-empty)');
        if (firstEnabled) firstEnabled.focus();
    }

    function closePopup(controller) {
        if (!controller.popup) return;
        controller.popup.classList.remove('is-open');
        if (controller.openedBy) {
            var trigger = controller.openedBy.querySelector('.adp-trigger');
            if (trigger) trigger.setAttribute('aria-expanded', 'false');
        }
        controller.openedBy = null;
    }

    function keydownHandler(event) {
        var controller = openController;
        if (!controller || !controller.popup || !controller.popup.classList.contains('is-open')) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            closePopup(controller);
            return;
        }
        if (event.key === 'Enter' || event.key === ' ') {
            var focused = document.activeElement;
            if (focused && focused.classList.contains('adp-day') && !focused.disabled) {
                event.preventDefault();
                selectDate(controller, focused.dataset.dayiso);
            }
        }
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight' ||
                event.key === 'ArrowUp' || event.key === 'ArrowDown') {
            var days = Array.prototype.slice.call(
                controller.popup.querySelectorAll('.adp-day:not(:disabled):not(.is-empty)'));
            if (!days.length) return;
            var idx = days.indexOf(document.activeElement);
            var current = idx === -1 ? 0 : idx;
            var cols = 7;
            if (event.key === 'ArrowLeft') current = current - 1;
            else if (event.key === 'ArrowRight') current = current + 1;
            else if (event.key === 'ArrowUp') current = current - cols;
            else if (event.key === 'ArrowDown') current = current + cols;
            current = Math.max(0, Math.min(days.length - 1, current));
            event.preventDefault();
            days[current].focus();
        }
    }


    var openController = null;

    function repositionOpenPopup(event) {
        var controller = openController;
        if (!controller || !controller.popup || !controller.openedBy) return;
        if (event && controller.popup.contains(event.target)) return;
        positionPopup(controller.openedBy, controller.popup);
    }

    document.addEventListener('scroll', repositionOpenPopup, true);
    window.addEventListener('resize', repositionOpenPopup);

    document.addEventListener('atp:opening', function () {
        if (openController) closePopup(openController);
    });

    function syncEnhanced(input) {
        var anchor = input.closest('.adp-anchor');
        if (!anchor) return;
        var trigger = anchor.querySelector('.adp-trigger');
        if (trigger) trigger.disabled = !!input.disabled;
        renderTrigger(input, input.value ? formatShort(parseISO(input.value)) : '');
    }

    function enhance(input) {
        if (input.dataset.adpEnhanced || input.classList.contains('adp-native')) return;
        if (input.hasAttribute('data-adp-native')) return;
        if (input.closest('.adp-anchor')) return;
        input.dataset.adpEnhanced = '1';
        input.classList.add('adp-native');
        input.style.cssText = 'position:absolute!important;left:-9999px!important;top:auto!important;' +
            'width:1px!important;height:1px!important;margin:0!important;padding:0!important;' +
            'border:0!important;opacity:0!important;pointer-events:none!important;user-select:none!important;';
        input.setAttribute('aria-hidden', 'true');
        input.tabIndex = -1;

        var controller = createController(input, findRangePair(input));
        CONTROLLERS.set(input, controller);

        var anchor = document.createElement('span');
        anchor.className = 'adp-anchor';

        var trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'adp-trigger';
        trigger.setAttribute('aria-haspopup', 'dialog');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.disabled = !!input.disabled;

        var value = document.createElement('span');
        value.className = 'adp-trigger-value';
        var placeholder = document.createElement('span');
        placeholder.className = 'adp-trigger-placeholder';
        placeholder.textContent = input.getAttribute('placeholder') ||
            (controller.range ? 'Select dates' : 'Select date');

        var icon = document.createElement('span');
        icon.className = 'adp-trigger-icon';
        icon.innerHTML = '<i class="fas fa-calendar-days"></i>';

        trigger.appendChild(value);
        trigger.appendChild(placeholder);
        trigger.appendChild(icon);

        input.parentNode.insertBefore(anchor, input);
        anchor.appendChild(input);
        anchor.appendChild(trigger);

        trigger.addEventListener('click', function (e) {
            e.stopPropagation();
            if (controller.popup && controller.popup.classList.contains('is-open') && controller.openedBy === anchor) {
                closePopup(controller);
                return;
            }
            document.dispatchEvent(new CustomEvent('adp:opening'));
            if (openController && openController !== controller) closePopup(openController);
            openController = controller;
            openPopup(controller, anchor);
        });

        anchor.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && controller.popup.classList.contains('is-open')) {
                e.preventDefault();
                closePopup(controller);
            }
        });

        renderTrigger(input, input.value ? formatShort(parseISO(input.value)) : '');
        controller.enhanced = true;
        controller.anchor = anchor;
        input.addEventListener('invalid', function (e) {
            e.preventDefault();
            var t = anchor.querySelector('.adp-trigger');
            if (t) t.classList.add('adp-invalid');
            showValidityMessage(anchor, input.validationMessage || 'Select a date.');
        });
        input.addEventListener('input', function () {
            var t = anchor.querySelector('.adp-trigger');
            if (t) t.classList.remove('adp-invalid');
            clearValidityMessage(anchor);
        });
        input.addEventListener('change', function () {
            syncEnhanced(input);
        });
        return controller;
    }

    document.addEventListener('click', function (e) {
        if (!openController) return;
        var target = e.target;
        if (target.closest && target.closest('.adp-popup')) return;
        if (target.closest && target.closest('.adp-anchor')) return;
        closePopup(openController);
    });

    document.addEventListener('keydown', keydownHandler);

    function showValidityMessage(anchor, message) {
        var el = anchor.querySelector('.adp-error');
        if (!el) {
            el = document.createElement('div');
            el.className = 'adp-error';
            anchor.appendChild(el);
        }
        el.textContent = message;
        el.hidden = false;
    }

    function clearValidityMessage(anchor) {
        var el = anchor.querySelector('.adp-error');
        if (el) el.hidden = true;
    }

    function scan(root) {
        root.querySelectorAll('input[type="date"]').forEach(enhance);
    }

    function handleAttributeMutation(target) {
        if (!target || !target.matches || !target.matches('input.adp-native, input[type="date"].adp-native')) return;
        syncEnhanced(target);
        var ctrl = CONTROLLERS.get(target);
        if (!ctrl) return;
        var wasOpen = ctrl.popup && ctrl.popup.classList.contains('is-open');
        refreshControllerState(ctrl);
        if (wasOpen) renderMonths(ctrl);
    }

    function init() {
        scan(document);
        if (window.MutationObserver) {
            var observer = new MutationObserver(function (mutations) {
                mutations.forEach(function (mutation) {
                    if (mutation.type === 'attributes') {
                        handleAttributeMutation(mutation.target);
                        return;
                    }
                    if (mutation.type !== 'childList') return;
                    Array.prototype.forEach.call(mutation.addedNodes, function (node) {
                        if (node.nodeType !== 1) return;
                        if (node.matches && node.matches('input[type="date"]')) {
                            enhance(node);
                        }
                        if (node.querySelectorAll) {
                            scan(node);
                        }
                    });
                });
            });
            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['disabled', 'value', 'min', 'max', 'data-adp-disabled']
            });
        }
    }

    /* ---- public API for dynamic availability (turnover, closures, ...) ---- */

    window.ATRUE_DATE_PICKER = {
        get: function (input) {
            return input && input.closest ? CONTROLLERS.get(input) : null;
        },
        refresh: function (input) {
            var c = input && input.closest ? CONTROLLERS.get(input) : null;
            if (!c) return;
            var wasOpen = c.popup && c.popup.classList.contains('is-open');
            refreshControllerState(c);
            if (wasOpen) renderMonths(c);
            syncEnhanced(c.input);
        },
        setDisabled: function (input, list) {
            if (!input) return;
            input.setAttribute('data-adp-disabled', (list || []).join(','));
            this.refresh(input);
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();