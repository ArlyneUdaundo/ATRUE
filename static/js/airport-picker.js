/* ============================================================
   ATRUE worldwide airport picker
   ------------------------------------------------
   Turns each `[data-airport-picker]` wrapper into a searchable
   dropdown backed by /flights/api/airports/?q=... (airports,
   IATA/ICAO codes, cities and countries all search server-side,
   so nothing is hard-coded into the page).

   A selected airport is stored as the Airport id in the hidden
   input named by the partial (`origin_airport`, `destination_airport`, ...).
   ============================================================ */
(function () {
    'use strict';

    var API_SRC = '/flights/api/airports/';
    var openPicker = null;

    function el(tag, className, html) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (html !== undefined) node.innerHTML = html;
        return node;
    }

    function init() {
        document.querySelectorAll('.atrue-airport-wrap[data-airport-picker]').forEach(function (wrap) {
            if (wrap.dataset.airportReady) return;
            wrap.dataset.airportReady = '1';
            var hidden = wrap.querySelector('[data-airport-value]');
            var trigger = wrap.querySelector('[data-airport-toggle]');
            var panel = wrap.querySelector('[data-airport-panel]');
            var input = wrap.querySelector('[data-airport-input]');
            var list = wrap.querySelector('[data-airport-list]');
            var empty = wrap.querySelector('[data-airport-empty]');
            var clearBtn = wrap.querySelector('[data-airport-clear]');
            var text = wrap.querySelector('.atrue-airport-text');
            if (trigger) { trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-haspopup', 'listbox'); }
            if (panel) panel.setAttribute('role', 'listbox');
            if (input) input.setAttribute('aria-label', 'Search airports by name, code, city, or country');
            var timer = null;
            var searchRequest = null;

            function renderValue() {
                if (hidden && hidden.value) {
                    var code = hidden.dataset.airportCode || '';
                    var city = hidden.dataset.airportCity || '';
                    var country = hidden.dataset.airportCountry || '';
                    text.textContent = code
                        ? code + ' — ' + [city, country].filter(Boolean).join(', ')
                        : [city, country].filter(Boolean).join(', ');
                    wrap.classList.add('has-apt');
                } else {
                    text.textContent = '';
                    wrap.classList.remove('has-apt');
                }
            }

            function close() {
                panel.hidden = true;
                wrap.classList.remove('is-open');
                trigger.setAttribute('aria-expanded', 'false');
                openPicker = null;
            }

            function open() {
                if (openPicker && openPicker !== wrap) {
                    var previousPanel = openPicker.querySelector('[data-airport-panel]');
                    if (previousPanel) previousPanel.hidden = true;
                    openPicker.classList.remove('is-open');
                    var previousTrigger = openPicker.querySelector('[data-airport-toggle]');
                    if (previousTrigger) previousTrigger.setAttribute('aria-expanded', 'false');
                }
                panel.hidden = false;
                wrap.classList.add('is-open');
                trigger.setAttribute('aria-expanded', 'true');
                openPicker = wrap;
                input.focus();
            }

            function fetchResults(query, cb) {
                var url = API_SRC + '?q=' + encodeURIComponent(query || '');
                var xhr = new XMLHttpRequest();
                if (searchRequest) searchRequest.abort();
                searchRequest = xhr;
                xhr.open('GET', url, true);
                xhr.onload = function () {
                    if (searchRequest !== xhr) return;
                    searchRequest = null;
                    if (xhr.status !== 200) {
                        cb([], 'Airport suggestions are unavailable. Please try again.');
                        return;
                    }
                    try { cb(JSON.parse(xhr.responseText).results || []); }
                    catch (e) {
                        cb([], 'Airport suggestions could not be read. Please try again.');
                    }
                };
                xhr.onerror = function () {
                    if (searchRequest !== xhr) return;
                    searchRequest = null;
                    cb([], 'Airport suggestions are unavailable. Check your connection and try again.');
                };
                xhr.send();
            }

            function render(results, errorMessage) {
                list.innerHTML = '';
                if (!results.length) {
                    empty.hidden = false;
                    empty.textContent = errorMessage || 'No airports found. Try the IATA code or a city / country.';
                    return;
                }
                empty.hidden = true;
                results.forEach(function (r) {
                    var li = el('li');
                    var code = r.iata || r.icao || '—';
                    var selected = hidden && String(hidden.value) === String(r.id);
                    var btn = el('button', 'atrue-airport-item' + (selected ? ' is-selected' : ''));
                    btn.setAttribute('role', 'option');
                    btn.setAttribute('aria-selected', String(!!selected));
                    var sub = [r.city, r.country].filter(Boolean).join(', ');
                    btn.innerHTML =
                        '<span class="atrue-airport-item-ico"><i class="fas fa-plane-departure"></i></span>' +
                        '<span class="atrue-airport-item-txt">' +
                        '<span class="atrue-airport-item-name"></span>' +
                        '<span class="atrue-airport-item-sub"></span>' +
                        '</span>' +
                        '<span class="atrue-airport-item-code"></span>' +
                        '<i class="fas fa-check atrue-airport-item-check" aria-hidden="true"></i>';
                    btn.querySelector('.atrue-airport-item-name').textContent = r.name;
                    btn.querySelector('.atrue-airport-item-sub').textContent =
                        (code === '–' ? '' : code + ' — ') + sub;
                    btn.querySelector('.atrue-airport-item-code').textContent = code;
                    btn.type = 'button';
                    btn.addEventListener('click', function () {
                        if (hidden) {
                            hidden.value = r.id;
                            hidden.dataset.airportCode = r.code || '';
                            hidden.dataset.airportCity = r.city || '';
                            hidden.dataset.airportCountry = r.country || '';
                            hidden.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        renderValue();
                        close();
                    });
                    li.appendChild(btn);
                    list.appendChild(li);
                });
            }

            function loading() {
                list.innerHTML = '';
                if (empty) empty.hidden = true;
                var li = el('li', 'atrue-airport-loading');
                li.textContent = 'Searching worldwide airports…';
                list.appendChild(li);
            }

            trigger.addEventListener('click', function () {
                if (panel.hidden) {
                    open();
                    loading();
                    fetchResults('', render);
                } else {
                    close();
                }
            });

            input.addEventListener('input', function () {
                clearTimeout(timer);
                timer = setTimeout(function () {
                    loading();
                    fetchResults(input.value, render);
                }, 180);
            });

            input.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') { close(); e.preventDefault(); }
                if (e.key === 'Enter') { e.preventDefault(); return; }
            });

            if (clearBtn) {
                clearBtn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    if (hidden) {
                        hidden.value = '';
                        hidden.dataset.airportCode = '';
                        hidden.dataset.airportCity = '';
                        hidden.dataset.airportCountry = '';
                        hidden.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    input.value = '';
                    renderValue();
                    close();
                });
            }

            document.addEventListener('click', function (e) {
                if (openPicker === wrap && !wrap.contains(e.target)) close();
            });

            renderValue();
        });
    }

    document.addEventListener('DOMContentLoaded', init);
    window.AirportPicker = { init: init };
})();