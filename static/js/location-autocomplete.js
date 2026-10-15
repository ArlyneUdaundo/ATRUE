(function () {
    'use strict';
    function init() {
        document.querySelectorAll('[data-location-autocomplete]').forEach(function (wrap) {
            if (wrap.dataset.locationReady) return;
            wrap.dataset.locationReady = '1';
            var input = wrap.querySelector('[data-location-input]') || wrap.querySelector('input[type="text"]');
            var list = wrap.querySelector('.atrue-location-options');
            if (!input || !list) return;
            var timer, request, options = [], active = -1;
            input.setAttribute('role', 'combobox');
            input.setAttribute('aria-expanded', 'false');
            if (!list.id) list.id = 'location-options-' + Math.random().toString(36).slice(2, 10);
            list.setAttribute('role', 'listbox');
            input.setAttribute('aria-controls', list.id);
            function close() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1; }
            function render(rows) {
                options = rows || []; active = -1; list.replaceChildren();
                if (!options.length) {
                    var empty = document.createElement('div'); empty.className = 'atrue-location-empty';
                    empty.textContent = 'No locations found'; list.appendChild(empty);
                } else options.forEach(function (place, index) {
                    var button = document.createElement('button'); button.type = 'button';
                    button.className = 'atrue-location-option'; button.setAttribute('role', 'option');
                    button.setAttribute('aria-selected', 'false'); button.dataset.index = index;
                    var name = document.createElement('strong'); name.textContent = place.name || '';
                    var sub = document.createElement('small');
                    sub.textContent = [place.level, place.municipality, place.province, place.country].filter(Boolean).join(' · ');
                    button.append(name, sub);
                    button.addEventListener('mousedown', function (event) { event.preventDefault(); input.value = place.name || ''; input.dispatchEvent(new Event('change', { bubbles: true })); close(); });
                    list.appendChild(button);
                });
                list.hidden = false; input.setAttribute('aria-expanded', 'true');
            }
            input.addEventListener('input', function () {
                clearTimeout(timer); if (request) request.abort();
                var q = input.value.trim(); if (q.length < 2) { close(); return; }
                timer = setTimeout(function () {
                    request = new XMLHttpRequest(); request.open('GET', '/locations/api/search/?q=' + encodeURIComponent(q), true);
                    request.onload = function () { if (request.status !== 200) { render([]); return; } try { render(JSON.parse(request.responseText).results); } catch (_) { render([]); } };
                    request.onerror = function () { render([]); }; request.send();
                }, 160);
            });
            input.addEventListener('keydown', function (event) {
                if (list.hidden) return;
                if (event.key === 'Escape') { close(); return; }
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault(); active = (active + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
                    list.querySelectorAll('[role="option"]').forEach(function (node, index) { node.setAttribute('aria-selected', String(index === active)); });
                } else if (event.key === 'Enter' && active >= 0 && options[active]) {
                    event.preventDefault(); input.value = options[active].name || ''; input.dispatchEvent(new Event('change', { bubbles: true })); close();
                }
            });
            document.addEventListener('click', function (event) { if (!wrap.contains(event.target)) close(); });
        });
    }
    document.addEventListener('DOMContentLoaded', init);
    window.ATRUELocationAutocomplete = { init: init };
})();
