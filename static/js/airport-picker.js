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
    var lockedPageY = 0;
    var pageScrollLocked = false;

    function lockPageScroll() {
        if (pageScrollLocked) return;
        lockedPageY = window.scrollY || document.documentElement.scrollTop || 0;
        document.documentElement.classList.add('airport-picker-open');
        document.body.classList.add('airport-picker-open');
        document.body.style.position = 'fixed';
        document.body.style.top = '-' + lockedPageY + 'px';
        document.body.style.left = '0';
        document.body.style.right = '0';
        document.body.style.width = '100%';
        pageScrollLocked = true;
    }

    function unlockPageScroll() {
        if (!pageScrollLocked) return;
        document.documentElement.classList.remove('airport-picker-open');
        document.body.classList.remove('airport-picker-open');
        document.body.style.position = '';
        document.body.style.top = '';
        document.body.style.left = '';
        document.body.style.right = '';
        document.body.style.width = '';
        pageScrollLocked = false;
        window.scrollTo(0, lockedPageY);
    }

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
            if (panel) {
                wrap._airportPanel = panel;
                document.body.appendChild(panel);
            }
            if (list) {
                if (!list.id) list.id = 'airport-options-' + Math.random().toString(36).slice(2, 10);
                list.setAttribute('role', 'listbox');
            }
            if (input) {
                input.setAttribute('aria-label', 'Search airports by name, code, city, or country');
                input.setAttribute('role', 'combobox');
                input.setAttribute('aria-autocomplete', 'list');
                input.setAttribute('aria-expanded', 'false');
                if (list) input.setAttribute('aria-controls', list.id);
            }
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

            function positionPanel() {
                var rect = trigger.getBoundingClientRect();
                var mobile = window.innerWidth <= 640;
                var viewport = window.visualViewport;
                var viewportWidth = viewport ? viewport.width : window.innerWidth;
                var viewportHeight = viewport ? viewport.height : window.innerHeight;
                var viewportLeft = viewport ? viewport.offsetLeft : 0;
                var viewportTop = viewport ? viewport.offsetTop : 0;
                var width = mobile ? Math.min(viewportWidth - 32, 650) : rect.width;
                var left = mobile
                    ? viewportLeft + Math.max(16, (viewportWidth - width) / 2)
                    : Math.min(Math.max(12, rect.left), window.innerWidth - width - 12);
                var maxHeight = Math.min(viewportHeight * (mobile ? 0.60 : 0.46), mobile ? 520 : 360);
                var top;
                if (mobile) {
                    // Keep the picker as a compact bottom sheet within the visible
                    // viewport (including when the on-screen keyboard is open).
                    var sheetHeight = Math.min(maxHeight, Math.max(0, viewportHeight - 24));
                    top = viewportTop + viewportHeight - sheetHeight - 12;
                    panel.style.height = sheetHeight + 'px';
                } else {
                    var maxTop = viewportTop + viewportHeight - maxHeight - 8;
                    top = Math.min(rect.bottom + 6, maxTop);
                    panel.style.height = '';
                }
                panel.style.position = 'fixed';
                panel.style.left = left + 'px';
                panel.style.right = 'auto';
                panel.style.width = width + 'px';
                panel.style.minWidth = '0';
                panel.style.maxWidth = mobile ? 'calc(100vw - 32px)' : 'min(650px, calc(100vw - 24px))';
                panel.style.maxHeight = Math.max(0, maxHeight) + 'px';
                panel.style.top = Math.max(viewportTop + 8, top) + 'px';
                panel.style.bottom = 'auto';
            }

            function close() {
                panel.hidden = true;
                wrap.classList.remove('is-open');
                trigger.setAttribute('aria-expanded', 'false');
                if (input) input.setAttribute('aria-expanded', 'false');
                openPicker = null;
                unlockPageScroll();
            }

            function open() {
                if (openPicker && openPicker !== wrap) {
                    var previousPanel = openPicker._airportPanel;
                    if (previousPanel) previousPanel.hidden = true;
                    openPicker.classList.remove('is-open');
                    var previousTrigger = openPicker.querySelector('[data-airport-toggle]');
                    if (previousTrigger) previousTrigger.setAttribute('aria-expanded', 'false');
                }
                if (window.innerWidth <= 640) lockPageScroll();
                panel.hidden = false;
                positionPanel();
                wrap.classList.add('is-open');
                trigger.setAttribute('aria-expanded', 'true');
                if (input) input.setAttribute('aria-expanded', 'true');
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
                if (openPicker === wrap && !wrap.contains(e.target) && !panel.contains(e.target)) close();
            });
            window.addEventListener('resize', function () {
                if (openPicker !== wrap) return;
                if (window.innerWidth <= 640) lockPageScroll();
                else unlockPageScroll();
                positionPanel();
            });
            window.addEventListener('scroll', function () {
                if (openPicker === wrap) positionPanel();
            }, true);
            if (window.visualViewport) {
                window.visualViewport.addEventListener('resize', function () {
                    if (openPicker === wrap) positionPanel();
                });
                window.visualViewport.addEventListener('scroll', function () {
                    if (openPicker === wrap) positionPanel();
                });
            }

            renderValue();
        });
    }

    document.addEventListener('DOMContentLoaded', init);
    window.AirportPicker = { init: init };
})();
