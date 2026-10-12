/* ============================================================
   ATRUE Time Picker — single reusable time component.
   Auto-enhances every <input type="time"> (native input remains
   in the form as the value store so backend contracts are kept).
   12-hour UI ("HH : MM AM/PM"): Hour column, Minute column,
   AM/PM toggle, disabled times muted, dynamic availability
   hooks (min/max + data-atp-disabled + programmatic API).
   ============================================================ */
(function () {
    'use strict';

    var STEP_DEFAULT = 1;
    var CONTROLLERS = new WeakMap();

    function pad2(n) {
        return n < 10 ? '0' + n : '' + n;
    }

    function toHM(h, m) {
        return pad2(h) + ':' + pad2(m);
    }

    function parseHM(text) {
        if (!text) return null;
        var parts = /^(\d{1,2}):(\d{1,2})$/.exec(String(text).trim());
        if (!parts) return null;
        var h = parseInt(parts[1], 10);
        var m = parseInt(parts[2], 10);
        if (h < 0 || h > 23 || m < 0 || m > 59) return null;
        return { h: h, m: m };
    }

    function timeNum(t) {
        return t ? t.h * 60 + t.m : null;
    }

    function toHour12(h) {
        var r = (h % 24) % 12;
        return r === 0 ? 12 : r;
    }

    function meridiemOf(h) {
        return h < 12 ? 'AM' : 'PM';
    }

    function to24(h12, mer) {
        var h = h12 % 12;
        return mer === 'PM' ? h + 12 : h;
    }

    /* ---- constraints (dynamic availability hooks) ---- */

    function stepMinutes(input) {
        var attr = input.getAttribute('data-atp-step');
        if (attr) {
            var n = parseInt(attr, 10);
            if (!isNaN(n) && n > 0 && n <= 60) return n;
        }
        var nativeStep = input.getAttribute('step');
        if (nativeStep) {
            var secs = parseInt(nativeStep, 10);
            if (!isNaN(secs) && secs > 0 && secs <= 3600 && secs % 60 === 0) return secs / 60;
        }
        return STEP_DEFAULT;
    }

    function constraintValues(input) {
        var disabled = [];
        var raw = input.getAttribute('data-atp-disabled');
        if (raw) {
            String(raw).split(',').forEach(function (token) {
                var t = parseHM(token);
                if (t) disabled.push(timeNum(t));
            });
        }
        return {
            min: timeNum(parseHM(input.getAttribute('min'))),
            max: timeNum(parseHM(input.getAttribute('max'))),
            disabled: disabled,
            step: stepMinutes(input)
        };
    }

    function isEnabled(constraints, h, m) {
        if (h === null || m === null) return false;
        var num = h * 60 + m;
        if (constraints.min !== null && num < constraints.min) return false;
        if (constraints.max !== null && num > constraints.max) return false;
        if (constraints.disabled.indexOf(num) !== -1) return false;
        return true;
    }

    function firstEnabled(constraints) {
        var start = constraints.min === null ? 0 : constraints.min;
        var end = constraints.max === null ? 1439 : constraints.max;
        if (start > end) return null;
        for (var num = start; num <= end; num += constraints.step) {
            var h = Math.floor(num / 60);
            var m = num % 60;
            if (isEnabled(constraints, h, m)) return { h: h, m: m };
        }
        return null;
    }

    /* ---- trigger rendering ---- */

    function formatValue(val) {
        if (!val) return null;
        return { hour12: toHour12(val.h), m: val.m, mer: meridiemOf(val.h) };
    }

    function renderTrigger(controller) {
        var anchor = controller.anchor;
        if (!anchor) return;
        var triggerValue = anchor.querySelector('.atp-trigger-value');
        var placeholder = anchor.querySelector('.atp-trigger-placeholder');
        if (!triggerValue || !placeholder) return;
        var val = parseHM(controller.input.value);
        if (val) {
            var f = formatValue(val);
            placeholder.style.display = 'none';
            triggerValue.textContent = pad2(f.hour12) + ' : ' + pad2(f.m) + ' ' + f.mer;
            triggerValue.style.display = '';
            anchor.classList.add('has-value');
        } else {
            placeholder.style.display = '';
            triggerValue.style.display = 'none';
            anchor.classList.remove('has-value');
        }
        var trigger = anchor.querySelector('.atp-trigger');
        if (trigger) trigger.disabled = !!controller.input.disabled;
    }

    /* ---- popup build ---- */

    function columnGroup(label, cls) {
        var wrap = document.createElement('div');
        wrap.className = 'atp-col-group';
        var title = document.createElement('div');
        title.className = 'atp-col-label';
        title.textContent = label;
        var col = document.createElement('div');
        col.className = 'atp-col ' + cls;
        col.setAttribute('aria-label', label);
        wrap.appendChild(title);
        wrap.appendChild(col);
        return wrap;
    }

    function buildPopup(controller) {
        var popup = document.createElement('div');
        popup.className = 'atp-popup';
        popup.setAttribute('role', 'dialog');
        popup.setAttribute('aria-modal', 'false');
        popup.setAttribute('aria-label', 'Select time');

        var head = document.createElement('div');
        head.className = 'atp-head';

        var title = document.createElement('span');
        title.className = 'atp-title';
        title.innerHTML = '<i class="fas fa-clock"></i> Select time';

        var x = document.createElement('button');
        x.type = 'button';
        x.className = 'atp-x';
        x.setAttribute('aria-label', 'Close time picker');
        x.innerHTML = '<i class="fas fa-xmark"></i>';
        x.addEventListener('click', function () {
            closePopup(controller);
        });

        head.appendChild(title);
        head.appendChild(x);

        var display = document.createElement('div');
        display.className = 'atp-display';

        var displayTime = document.createElement('span');
        displayTime.className = 'atp-display-time';

        var dh = document.createElement('span');
        dh.className = 'atp-display-hour';
        var colon = document.createElement('span');
        colon.className = 'atp-display-colon';
        colon.textContent = ':';
        var dm = document.createElement('span');
        dm.className = 'atp-display-min';
        var dmer = document.createElement('span');
        dmer.className = 'atp-display-mer';

        displayTime.appendChild(dh);
        displayTime.appendChild(colon);
        displayTime.appendChild(dm);
        display.appendChild(displayTime);
        display.appendChild(dmer);

        var body = document.createElement('div');
        body.className = 'atp-body';

        var hourGroup = columnGroup('Hour', 'atp-col-hour');
        var minuteGroup = columnGroup('Minute', 'atp-col-minute');

        var merCol = document.createElement('div');
        merCol.className = 'atp-meridiem';
        merCol.setAttribute('aria-label', 'AM / PM');

        body.appendChild(hourGroup);
        body.appendChild(minuteGroup);
        body.appendChild(merCol);

        var foot = document.createElement('div');
        foot.className = 'atp-foot';

        var done = document.createElement('button');
        done.type = 'button';
        done.className = 'atp-done';
        done.textContent = 'Done';
        done.disabled = true;
        done.addEventListener('click', function () {
            commit(controller);
        });
        foot.appendChild(done);

        popup.appendChild(head);
        popup.appendChild(display);
        popup.appendChild(body);
        popup.appendChild(foot);

        var hourCol = hourGroup.querySelector('.atp-col');
        var minuteCol = minuteGroup.querySelector('.atp-col');

        for (var h = 1; h <= 12; h++) {
            var opt = document.createElement('button');
            opt.type = 'button';
            opt.className = 'atp-opt';
            opt.dataset.hour = h;
            opt.textContent = pad2(h);
            opt.setAttribute('aria-label', 'Hour ' + h);
            opt.addEventListener('click', function () {
                controller.hour12 = parseInt(this.dataset.hour, 10);
                if (controller.m === null) controller.m = latestMinute(controller);
                refreshPopup(controller);
            });
            hourCol.appendChild(opt);
        }

        var step = controller.constraints.step;
        for (var m = 0; m < 60; m += step) {
            var mopt = document.createElement('button');
            mopt.type = 'button';
            mopt.className = 'atp-opt';
            mopt.dataset.minute = m;
            mopt.textContent = pad2(m);
            mopt.setAttribute('aria-label', 'Minute ' + m);
            mopt.addEventListener('click', function () {
                controller.m = parseInt(this.dataset.minute, 10);
                if (controller.hour12 === null) controller.hour12 = 12;
                refreshPopup(controller);
            });
            minuteCol.appendChild(mopt);
        }

        ['AM', 'PM'].forEach(function (merLabel) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'atp-mer';
            btn.dataset.atpMer = merLabel;
            btn.textContent = merLabel;
            btn.addEventListener('click', function () {
                controller.mer = merLabel;
                if (controller.hour12 === null) controller.hour12 = 12;
                if (controller.m === null) controller.m = latestMinute(controller);
                refreshPopup(controller);
            });
            merCol.appendChild(btn);
        });

        controller.popup = popup;
        controller.hourColumn = hourCol;
        controller.minuteColumn = minuteCol;
        return popup;
    }

    function latestMinute(controller) {
        var opts = controller.minuteColumn
            ? Array.prototype.slice.call(controller.minuteColumn.querySelectorAll('.atp-opt'))
            : [];
        var selected = opts.filter(function (o) { return o.classList.contains('is-sel'); })[0];
        if (selected) return parseInt(selected.dataset.minute, 10);
        return 0;
    }

    /* ---- popup render ---- */

    function refreshPopup(controller) {
        var popup = controller.popup;
        if (!popup || !popup.classList.contains('is-open')) return;

        var dh = popup.querySelector('.atp-display-hour');
        var dm = popup.querySelector('.atp-display-min');
        var dmer = popup.querySelector('.atp-display-mer');
        var done = popup.querySelector('.atp-done');
        if (controller.hour12 !== null && controller.m !== null) {
            dh.textContent = pad2(controller.hour12);
            dm.textContent = pad2(controller.m);
            dmer.textContent = controller.mer;
            done.disabled = false;
        } else {
            dh.textContent = '—';
            dm.textContent = '—';
            dmer.textContent = 'AM';
            done.disabled = true;
        }

        // Hour options
        Array.prototype.forEach.call(
            popup.querySelectorAll('.atp-col-hour .atp-opt'),
            function (btn) {
                var h = parseInt(btn.dataset.hour, 10);
                btn.disabled = !isEnabled(controller.constraints, h, controller.m);
                btn.classList.toggle('is-sel', controller.hour12 !== null && h === controller.hour12);
            });

        // Minute options
        var h24 = controller.hour12 === null ? null : to24(controller.hour12, controller.mer);
        Array.prototype.forEach.call(
            popup.querySelectorAll('.atp-col-minute .atp-opt'),
            function (btn) {
                var m = parseInt(btn.dataset.minute, 10);
                btn.disabled = !isEnabled(controller.constraints, h24, m);
                btn.classList.toggle('is-sel', controller.m !== null && m === controller.m);
            });

        // AM / PM
        Array.prototype.forEach.call(
            popup.querySelectorAll('.atp-mer'),
            function (btn) {
                var mer = btn.dataset.atpMer;
                var m = controller.m === null ? 0 : controller.m;
                var hourBase = mer === 'AM' ? 0 : 12;
                var anyEnabled = false;
                for (var h12 = 1; h12 <= 12; h12++) {
                    var hw = hourBase + (h12 % 12);
                    if (isEnabled(controller.constraints, hw, m)) { anyEnabled = true; break; }
                }
                btn.classList.toggle('is-sel', controller.mer === mer);
                btn.disabled = !anyEnabled;
            });

        scrollSelectedIntoView(popup);
    }

    function scrollSelectedIntoView(popup) {
        var sel = popup.querySelector('.atp-opt.is-sel');
        if (sel && sel.scrollIntoView) {
            sel.scrollIntoView({ block: 'nearest' });
        }
    }

    /* ---- open / close / commit ---- */

    function openPopup(controller, anchor) {
        controller.constraints = constraintValues(controller.input);
        var val = parseHM(controller.input.value);
        var start = val && isEnabled(controller.constraints, val.h, val.m)
            ? val
            : firstEnabled(controller.constraints);

        if (start) {
            controller.hour12 = toHour12(start.h);
            controller.m = start.m;
            controller.mer = meridiemOf(start.h);
        } else {
            controller.hour12 = null;
            controller.m = null;
            controller.mer = 'AM';
        }

        if (!controller.popup) {
            controller.popup = buildPopup(controller);
        }

        if (controller.popup.parentNode) {
            controller.popup.parentNode.removeChild(controller.popup);
        }
        document.body.appendChild(controller.popup);
        controller.openedBy = anchor;

        positionPopup(anchor, controller.popup);
        controller.popup.classList.add('is-open');
        refreshPopup(controller);

        var trigger = anchor.querySelector('.atp-trigger');
        if (trigger) trigger.setAttribute('aria-expanded', 'true');
        openController = controller;
        focusFirstOption(popupFirst(controller));
    }

    function popupFirst(controller) {
        return controller.popup.querySelector('.atp-opt:not(:disabled).is-sel') ||
            controller.popup.querySelector('.atp-opt:not(:disabled), .atp-mer:not(:disabled)');
    }

    function focusFirstOption(el) {
        if (el && el.focus) el.focus();
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

    function closePopup(controller) {
        if (!controller || !controller.popup) return;
        controller.popup.classList.remove('is-open');
        if (controller.openedBy) {
            var trigger = controller.openedBy.querySelector('.atp-trigger');
            if (trigger) trigger.setAttribute('aria-expanded', 'false');
        }
        controller.openedBy = null;
        if (openController === controller) openController = null;
    }

    function commit(controller) {
        if (controller.hour12 === null || controller.m === null) return;
        var h24 = to24(controller.hour12, controller.mer);
        setInputValue(controller.input, toHM(h24, controller.m));
        closePopup(controller);
    }

    function setInputValue(input, hm) {
        input.value = hm;
        var c = input && input.closest ? CONTROLLERS.get(input) : null;
        if (c) {
            renderTrigger(c);
            var t = c.anchor ? c.anchor.querySelector('.atp-trigger') : null;
            if (t) t.classList.remove('atp-invalid');
            clearValidityMessage(c.anchor);
        }
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    /* ---- global keyboard + outside-click handling ---- */


    var openController = null;

    function repositionOpenPopup(event) {
        var controller = openController;
        if (!controller || !controller.popup || !controller.openedBy) return;
        if (event && controller.popup.contains(event.target)) return;
        positionPopup(controller.openedBy, controller.popup);
    }

    document.addEventListener('scroll', repositionOpenPopup, true);
    window.addEventListener('resize', repositionOpenPopup);

    document.addEventListener('adp:opening', function () {
        if (openController) closePopup(openController);
    });

    document.addEventListener('click', function (e) {
        if (!openController) return;
        var target = e.target;
        if (target.closest && target.closest('.atp-popup')) return;
        if (target.closest && target.closest('.atp-anchor')) return;
        closePopup(openController);
    });

    document.addEventListener('keydown', function (e) {
        var controller = openController;
        if (!controller || !controller.popup || !controller.popup.classList.contains('is-open')) return;
        if (e.key === 'Escape') {
            e.preventDefault();
            closePopup(controller);
            return;
        }
        if (e.key === 'Enter' || e.key === ' ') {
            var focused = document.activeElement;
            if (focused && focused.classList.contains('atp-opt') && !focused.disabled) {
                e.preventDefault();
                focused.click();
            } else if (focused && focused.classList.contains('atp-mer') && !focused.disabled) {
                e.preventDefault();
                focused.click();
            }
        }
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            var options = Array.prototype.slice.call(
                controller.popup.querySelectorAll('.atp-opt:not(:disabled), .atp-mer:not(:disabled)'));
            if (!options.length) return;
            var idx = options.indexOf(document.activeElement);
            var current = idx === -1 ? 0 : idx;
            current += e.key === 'ArrowUp' ? -1 : 1;
            current = (current + options.length) % options.length;
            e.preventDefault();
            options[current].focus();
        }
    });

    /* ---- validity message (native input is off-screen) ---- */

    function showValidityMessage(anchor, message) {
        var el = anchor.querySelector('.atp-error');
        if (!el) {
            el = document.createElement('div');
            el.className = 'atp-error';
            anchor.appendChild(el);
        }
        el.textContent = message;
        el.hidden = false;
    }

    function clearValidityMessage(anchor) {
        var el = anchor.querySelector('.atp-error');
        if (el) el.hidden = true;
    }

    /* ---- enhance native input ---- */

    function enhance(input) {
        if (input.dataset.atpEnhanced || input.classList.contains('atp-native')) return;
        if (input.hasAttribute('data-atp-native')) return;
        if (input.closest('.atp-anchor')) return;

        input.dataset.atpEnhanced = '1';
        input.classList.add('atp-native');
        input.style.cssText = 'position:absolute!important;left:-9999px!important;top:auto!important;' +
            'width:1px!important;height:1px!important;margin:0!important;padding:0!important;' +
            'border:0!important;opacity:0!important;pointer-events:none!important;user-select:none!important;';
        input.setAttribute('aria-hidden', 'true');
        input.tabIndex = -1;

        var controller = {
            input: input,
            constraints: constraintValues(input),
            hour12: null,
            m: null,
            mer: 'AM',
            popup: null,
            anchor: null,
            openedBy: null
        };
        CONTROLLERS.set(input, controller);

        var anchor = document.createElement('span');
        anchor.className = 'atp-anchor';

        var trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'atp-trigger';
        trigger.setAttribute('aria-haspopup', 'dialog');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.disabled = !!input.disabled;

        var value = document.createElement('span');
        value.className = 'atp-trigger-value';
        var placeholder = document.createElement('span');
        placeholder.className = 'atp-trigger-placeholder';
        placeholder.textContent = input.getAttribute('placeholder') || 'Select time';

        var icon = document.createElement('span');
        icon.className = 'atp-trigger-icon';
        icon.innerHTML = '<i class="fas fa-clock"></i>';

        trigger.appendChild(value);
        trigger.appendChild(placeholder);
        trigger.appendChild(icon);

        input.parentNode.insertBefore(anchor, input);
        anchor.appendChild(input);
        anchor.appendChild(trigger);

        controller.anchor = anchor;

        trigger.addEventListener('click', function (e) {
            e.stopPropagation();
            if (controller.popup && controller.popup.classList.contains('is-open') && controller.openedBy === anchor) {
                closePopup(controller);
                return;
            }
            document.dispatchEvent(new CustomEvent('atp:opening'));
            if (openController && openController !== controller) closePopup(openController);
            openPopup(controller, anchor);
        });

        anchor.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && controller.popup && controller.popup.classList.contains('is-open')) {
                e.preventDefault();
                closePopup(controller);
            }
        });

        input.addEventListener('invalid', function (e) {
            e.preventDefault();
            var t = anchor.querySelector('.atp-trigger');
            if (t) t.classList.add('atp-invalid');
            showValidityMessage(anchor, input.validationMessage || 'Select a time.');
        });
        input.addEventListener('input', function () {
            var t = anchor.querySelector('.atp-trigger');
            if (t) t.classList.remove('atp-invalid');
            clearValidityMessage(anchor);
            renderTrigger(controller);
        });
        input.addEventListener('change', function () {
            renderTrigger(controller);
        });

        renderTrigger(controller);
    }

    /* ---- scan / observer ---- */

    function scan(root) {
        root.querySelectorAll('input[type="time"]').forEach(enhance);
    }

    function init() {
        scan(document);
        if (window.MutationObserver) {
            var observer = new MutationObserver(function (mutations) {
                mutations.forEach(function (mutation) {
                    if (mutation.type === 'attributes') {
                        var target = mutation.target;
                        if (target && target.matches &&
                                target.matches('input.atp-native, input[type="time"].atp-native')) {
                            var c = CONTROLLERS.get(target);
                            if (c) renderTrigger(c);
                        }
                        return;
                    }
                    if (mutation.type !== 'childList') return;
                    Array.prototype.forEach.call(mutation.addedNodes, function (node) {
                        if (node.nodeType !== 1) return;
                        if (node.matches && node.matches('input[type="time"]')) {
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
                attributeFilter: ['disabled', 'value', 'min', 'max', 'data-atp-disabled', 'data-atp-step']
            });
        }
    }

    /* ---- public API for dynamic availability (turnover, closures, ...) ---- */

    window.ATRUE_TIME_PICKER = {
        get: function (input) {
            return input && input.closest ? CONTROLLERS.get(input) : null;
        },
        refresh: function (input) {
            var c = input && input.closest ? CONTROLLERS.get(input) : null;
            if (!c) return;
            c.constraints = constraintValues(c.input);
            if (c.popup && c.popup.classList.contains('is-open')) {
                refreshPopup(c);
            }
            renderTrigger(c);
        },
        setDisabled: function (input, list) {
            if (!input) return;
            input.setAttribute('data-atp-disabled', (list || []).join(','));
            this.refresh(input);
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();