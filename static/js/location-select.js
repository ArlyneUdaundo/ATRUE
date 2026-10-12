/* ATRUE searchable location dropdown (combobox).
   Enhances any `input[data-loc-select]` into a searchable dropdown while keeping the
   real input as the form field (same name/value, required validation preserved).

   Data sources (data-loc-source):
     - "countries" -> window.ATRUE_COUNTRIES  (full world list)
     - "regions"   -> window.ATRUE_PH.regions
     - "provinces" -> window.ATRUE_PH.provinces
     - "cities"    -> window.ATRUE_PH.cities
     - "#datalistId" -> options gathered from an existing <datalist>

   Behavior: click / focus opens the list, typing filters it, arrow keys navigate,
   Enter selects (or keeps the typed value), Esc / outside click closes. Custom
   free-text values are always allowed so existing data and workflows are unaffected.
*/
(function () {
    'use strict';

    var OPEN_CLASS = 'open';

    function sourceValues(input) {
        var src = (input.getAttribute('data-loc-source') || '').trim();
        if (!src) return [];
        if (src.charAt(0) === '#') {
            var dl = document.getElementById(src.slice(1));
            if (!dl) return [];
            return Array.prototype.map.call(dl.options, function (o) { return o.value; });
        }
        if (src === 'countries') return window.ATRUE_COUNTRIES || [];
        if (src === 'regions') return (window.ATRUE_PH && window.ATRUE_PH.regions) || [];
        if (src === 'provinces') return (window.ATRUE_PH && window.ATRUE_PH.provinces) || [];
        if (src === 'cities') return (window.ATRUE_PH && window.ATRUE_PH.cities) || [];
        return [];
    }

    function norm(s) { return (s || '').trim().toLowerCase(); }

    function build(input) {
        if (input.dataset.locSelectBuilt) return;
        input.dataset.locSelectBuilt = '1';

        var values = sourceValues(input).slice().sort(function (a, b) {
            return a.localeCompare(b, 'en');
        });

        input.autocomplete = 'off';
        input.classList.add('loc-select-input');

        var wrap = document.createElement('div');
        wrap.className = 'loc-select';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        var arrow = document.createElement('button');
        arrow.type = 'button';
        arrow.className = 'loc-select-arrow';
        arrow.setAttribute('aria-label', 'Open location list');
        arrow.setAttribute('tabindex', '-1');
        arrow.innerHTML = '<i class="fa-solid fa-chevron-down" aria-hidden="true"></i>';
        wrap.appendChild(arrow);

        var panel = document.createElement('div');
        panel.className = 'loc-select-panel';
        panel.setAttribute('role', 'listbox');
        var list = document.createElement('ul');
        list.className = 'loc-select-list';
        panel.appendChild(list);
        wrap.appendChild(panel);

        var empty = document.createElement('li');
        empty.className = 'loc-select-empty';
        empty.textContent = 'No options found. Keep typing to enter a custom value.';

        var state = { open: false, index: -1 };

        function render() {
            var q = norm(input.value);
            var shown = values.slice();
            if (q) shown = shown.filter(function (v) { return norm(v).indexOf(q) !== -1; });
            list.innerHTML = '';
            state.index = -1;
            if (!shown.length) {
                list.appendChild(empty.cloneNode(true));
                return;
            }
            var selectedPos = -1;
            shown.forEach(function (v, i) {
                var li = document.createElement('li');
                li.className = 'loc-option';
                li.setAttribute('role', 'option');
                li.textContent = v;
                if (norm(v) === q) {
                    li.classList.add('active');
                    selectedPos = i;
                }
                li.addEventListener('mousedown', function (e) { e.preventDefault(); choose(v); });
                list.appendChild(li);
            });
            if (selectedPos >= 0) {
                state.index = selectedPos;
                list.children[selectedPos].classList.add('keyed');
                if (list.children[selectedPos].scrollIntoView) {
                    list.children[selectedPos].scrollIntoView({ block: 'nearest' });
                }
            }
        }

        function placePanel() {
            var rect = input.getBoundingClientRect();
            var bottom = (rect && typeof rect.bottom === 'number') ? rect.bottom : window.innerHeight;
            wrap.classList.toggle('up', bottom + 280 > window.innerHeight);
        }

        function open() {
            if (state.open) return;
            state.open = true;
            render();
            placePanel();
            panel.classList.add(OPEN_CLASS);
            wrap.classList.add(OPEN_CLASS);
            arrow.classList.add(OPEN_CLASS);
            input.focus();
        }

        function close() {
            if (!state.open) return;
            state.open = false;
            panel.classList.remove(OPEN_CLASS);
            wrap.classList.remove(OPEN_CLASS);
            arrow.classList.remove(OPEN_CLASS);
        }

        function choose(value) {
            input.value = value;
            close();
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.focus();
        }

        function navigate(dir) {
            var opts = list.querySelectorAll('.loc-option');
            if (!opts.length) return;
            if (state.index < 0) { state.index = dir > 0 ? 0 : opts.length - 1; }
            else { state.index = (state.index + dir + opts.length) % opts.length; }
            opts.forEach(function (o, i) { o.classList.toggle('keyed', i === state.index); });
            if (opts[state.index].scrollIntoView) {
                opts[state.index].scrollIntoView({ block: 'nearest' });
            }
        }

        function keyedValue() {
            var el = list.querySelector('.loc-option.keyed');
            return el ? el.textContent : '';
        }

        input.addEventListener('mousedown', function (e) {
            if (e.button !== 0) return;
            // Keep focus in the field so typing filters the list.
            e.preventDefault();
        });
        input.addEventListener('click', function () { if (!state.open) open(); });
        input.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown') { e.preventDefault(); if (!state.open) open(); else navigate(1); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); if (!state.open) open(); else navigate(-1); }
            else if (e.key === 'Enter') {
                if (state.open) {
                    e.preventDefault();
                    var picked = keyedValue();
                    if (picked) { choose(picked); return; }
                    close();
                } else {
                    open();
                }
            }
            else if (e.key === 'Escape') { if (state.open) { e.preventDefault(); e.stopPropagation(); close(); } }
            else if (e.key === 'Tab') { close(); }
        });
        input.addEventListener('input', function () { if (state.open) render(); });
        input.addEventListener('blur', function () {
            setTimeout(function () {
                if (state.open && !wrap.contains(document.activeElement)) close();
            }, 120);
        });
        arrow.addEventListener('click', function () {
            if (state.open) { close(); } else { open(); }
        });
        document.addEventListener('click', function (e) {
            if (state.open && !wrap.contains(e.target)) close();
        });
    }

    function init(root) {
        (root || document).querySelectorAll('input[data-loc-select]').forEach(build);
    }

    document.addEventListener('DOMContentLoaded', function () { init(document); });

    // Auto-enhance rows added dynamically (e.g. additional-guest country pickers).
    if (window.MutationObserver) {
        var mo = new MutationObserver(function (muts) {
            muts.forEach(function (m) {
                m.addedNodes.forEach(function (n) {
                    if (n.nodeType !== 1) return;
                    if (n.matches && n.matches('input[data-loc-select]')) build(n);
                    if (n.querySelectorAll) n.querySelectorAll('input[data-loc-select]').forEach(build);
                });
            });
        });
        document.addEventListener('DOMContentLoaded', function () {
            mo.observe(document.body, { childList: true, subtree: true });
        });
    }

    window.atrueLocationSelect = { init: init };
})();