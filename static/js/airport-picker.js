(function () {
    'use strict';

    var API_SRC = '/flights/api/airports/';

    function init() {
        document.querySelectorAll('.atrue-airport-wrap[data-airport-picker]').forEach(function (wrap) {
            if (wrap.dataset.airportReady) return;
            wrap.dataset.airportReady = '1';
            var hidden = wrap.querySelector('[data-airport-value]');
            var input = wrap.querySelector('[data-airport-input]');
            var list = wrap.querySelector('[data-airport-list]');
            var empty = wrap.querySelector('[data-airport-empty]');
            var text = wrap.querySelector('.atrue-airport-text');
            if (!input || !list || !empty) return;

            if (!list.id) list.id = 'airport-options-' + Math.random().toString(36).slice(2, 10);
            list.setAttribute('role', 'listbox');
            input.setAttribute('role', 'combobox');
            input.setAttribute('aria-autocomplete', 'list');
            input.setAttribute('aria-expanded', 'false');
            input.setAttribute('aria-controls', list.id);

            var timer;
            var request;
            var active = -1;

            function close() {
                list.hidden = true;
                empty.hidden = true;
                input.setAttribute('aria-expanded', 'false');
                wrap.classList.remove('is-open');
                active = -1;
            }

            function show() {
                list.hidden = false;
                input.setAttribute('aria-expanded', 'true');
                wrap.classList.add('is-open');
            }

            function renderValue() {
                if (!hidden || !hidden.value) return;
                var name = hidden.dataset.airportName || '';
                var code = hidden.dataset.airportCode || '';
                var city = hidden.dataset.airportCity || '';
                var country = hidden.dataset.airportCountry || '';
                input.value = [name, code ? '(' + code + ')' : '', city, country].filter(Boolean).join(' ');
                if (text) text.textContent = input.value;
                wrap.classList.add('has-apt');
            }

            function render(results, message) {
                list.innerHTML = '';
                active = -1;
                if (!results.length) {
                    empty.textContent = message || 'No airports found. Try a name, IATA code, city, address, or country.';
                    empty.hidden = false;
                    return;
                }
                empty.hidden = true;
                results.forEach(function (airport) {
                    var item = document.createElement('li');
                    var button = document.createElement('button');
                    var name = document.createElement('span');
                    var details = document.createElement('span');
                    var code = airport.iata || airport.icao || '';
                    button.type = 'button';
                    button.className = 'atrue-airport-item';
                    button.setAttribute('role', 'option');
                    button.setAttribute('aria-selected', 'false');
                    name.className = 'atrue-airport-item-name';
                    name.textContent = airport.name || '';
                    details.className = 'atrue-airport-item-sub';
                    details.textContent = [code, airport.city, airport.address, airport.region, airport.country].filter(Boolean).join(' · ');
                    button.appendChild(name);
                    button.appendChild(details);
                    button.addEventListener('click', function () {
                        if (hidden) {
                            hidden.value = airport.id;
                            hidden.dataset.airportName = airport.name || '';
                            hidden.dataset.airportAddress = airport.address || '';
                            hidden.dataset.airportCode = airport.code || code;
                            hidden.dataset.airportCity = airport.city || '';
                            hidden.dataset.airportCountry = airport.country || '';
                            hidden.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        input.value = [airport.name, code ? '(' + code + ')' : '', airport.city].filter(Boolean).join(' ');
                        if (text) text.textContent = input.value;
                        wrap.classList.add('has-apt');
                        close();
                    });
                    item.appendChild(button);
                    list.appendChild(item);
                });
            }

            function search(query) {
                if (request) request.abort();
                request = new XMLHttpRequest();
                var xhr = request;
                xhr.open('GET', API_SRC + '?q=' + encodeURIComponent(query), true);
                xhr.onload = function () {
                    if (request !== xhr) return;
                    request = null;
                    if (xhr.status !== 200) {
                        render([], 'Airport suggestions are unavailable. Please try again.');
                        return;
                    }
                    try { render(JSON.parse(xhr.responseText).results || []); }
                    catch (error) { render([], 'Airport suggestions could not be read.'); }
                };
                xhr.onerror = function () {
                    if (request !== xhr) return;
                    request = null;
                    render([], 'Airport suggestions are unavailable. Check your connection.');
                };
                xhr.send();
            }

            input.addEventListener('input', function () {
                if (hidden && hidden.value) {
                    hidden.value = '';
                    hidden.dataset.airportCode = '';
                    hidden.dataset.airportName = '';
                    hidden.dataset.airportAddress = '';
                    hidden.dataset.airportCity = '';
                    hidden.dataset.airportCountry = '';
                    hidden.dispatchEvent(new Event('change', { bubbles: true }));
                }
                wrap.classList.remove('has-apt');
                show();
                clearTimeout(timer);
                if (request) request.abort();
                var query = input.value.trim();
                if (!query) {
                    list.innerHTML = '';
                    empty.hidden = true;
                    return;
                }
                list.innerHTML = '<li class="atrue-airport-loading">Searching airports…</li>';
                timer = setTimeout(function () { search(query); }, 180);
            });

            input.addEventListener('focus', function () {
                if (input.value.trim()) {
                    show();
                    if (!list.children.length) search(input.value.trim());
                }
            });

            input.addEventListener('keydown', function (event) {
                var options = Array.prototype.slice.call(list.querySelectorAll('[role="option"]'));
                if (event.key === 'Escape') { close(); return; }
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    if (!options.length) return;
                    event.preventDefault();
                    active = (active + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
                    options.forEach(function (option, index) {
                        option.setAttribute('aria-selected', String(index === active));
                        if (index === active) option.scrollIntoView({ block: 'nearest' });
                    });
                } else if (event.key === 'Enter' && active >= 0 && options[active]) {
                    event.preventDefault();
                    options[active].click();
                }
            });

            document.addEventListener('click', function (event) {
                if (!wrap.contains(event.target)) close();
            });

            if (hidden && hidden.value) renderValue();
        });
    }

    document.addEventListener('DOMContentLoaded', init);
    window.AirportPicker = { init: init };
})();
