(function () {
    'use strict';

    const q = (selector, root = document) => root.querySelector(selector);
    const qa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    const cardsRoot = q('[data-fs-cards]');
    if (!cardsRoot) {
        return;
    }

    const number = new Intl.NumberFormat('en-PH', { maximumFractionDigits: 0 });
    const peso = (value) => '\u20b1' + number.format(Math.round(value));

    const prettyDate = (value) => {
        if (!value) {
            return '';
        }
        const parsed = new Date(value + 'T00:00:00');
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }
        return parsed.toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
        });
    };

    let airports = {};
    const airportData = document.getElementById('fsAirports');
    if (airportData) {
        try {
            JSON.parse(airportData.textContent).forEach(([code, city, name, country]) => {
                airports[code] = { city: city, name: name, country: country || '' };
            });
        } catch (error) {
            airports = {};
        }
    }
    const cityOf = (code) => (airports[code] && airports[code].city) || code;
    const airportOf = (code) => (airports[code] && airports[code].name) || (cityOf(code) + ' Airport');
    const countryOf = (code) => (airports[code] && airports[code].country) || '';
    const labelOf = (code) => cityOf(code)
        + (countryOf(code) ? ', ' + countryOf(code) : '') + ' (' + code + ')';

    // Airports chosen from the database may not be in the static list, so the
    // live picker value (which carries city and airport name) is preferred.
    const rememberAirport = (record) => {
        if (record && record.code) {
            airports[record.code] = {
                city: record.city || record.code,
                name: record.name || ((record.city || record.code) + ' Airport'),
                country: record.country || '',
            };
        }
    };

    const searchForm = q('[data-fs-search]');
    const swapButton = q('[data-fs-swap]');
    const tripInput = q('[data-fs-trip-input]');
    const flightTypeInput = q('[data-fs-flighttype-input]');
    const returnField = q('[data-fs-return-field]');
    const departInput = q('[data-fs-depart]');
    const returnInput = q('[data-fs-return]');
    const departLabel = q('[data-fs-depart-label]');
    const returnLabel = q('[data-fs-return-label]');
    const multiPanel = q('[data-fs-multi]');
    const legsRoot = q('[data-fs-legs]');
    const legsAdd = q('[data-fs-legs-add]');
    const searchError = q('[data-fs-search-error]');
    const formCountry = (searchForm && searchForm.dataset.fsCountry) || 'Philippines';

    const paxField = q('[data-fs-pax]');
    const paxPanel = q('[data-fs-pax-panel]');
    const paxToggle = q('[data-fs-pax-toggle]');
    const paxInput = q('[data-fs-pax-input]');
    const paxSummary = q('[data-fs-pax-summary]');
    const paxState = {
        adults: Math.max(1, Number((paxInput && paxInput.value) || 1)),
        children: 0,
        infants: 0,
    };

    const cardsElement = cardsRoot;
    let cards = qa('[data-fs-card]', cardsRoot);
    const countElement = q('[data-fs-count]');
    const emptyElement = q('[data-fs-empty]');
    const sortSelect = q('[data-fs-sort-select]');
    const filters = q('[data-fs-filters]');
    const filtersToggle = q('[data-fs-filters-toggle]');
    const minInput = q('[data-fs-price-min]');
    const maxInput = q('[data-fs-price-max]');
    const minLabel = q('[data-fs-price-min-label]');
    const maxLabel = q('[data-fs-price-max-label]');
    const rangeFill = q('[data-fs-range-fill]');
    const priceMin = Number(minInput.value);
    const priceMax = Number(maxInput.value);
    const priceStep = Number(minInput.step) || 500;

    const selection = q('[data-fs-selection]');
    const selectionPicked = q('[data-fs-selection-step="picked"]');
    const selectionConfirmed = q('[data-fs-selection-step="confirmed"]');
    const selectionTitle = q('[data-fs-selection-title]');
    const selectionMeta = q('[data-fs-selection-meta]');
    const selectionConfirmMeta = q('[data-fs-selection-confirm-meta]');
    const selectionClose = q('[data-fs-selection-close]');
    let selected = null;
    let selectionReturnFocus = null;

    // Keep the dialog outside the results layout so transformed/overflowing
    // ancestors cannot turn its fixed overlay into an inline panel.
    if (selection && selection.parentElement !== document.body) {
        document.body.appendChild(selection);
    }

    const closePops = () => {
        qa('.fs-pop').forEach((pop) => {
            const panel = q('[data-fs-pop-panel]', pop);
            const button = q('[data-fs-pop-toggle]', pop);
            if (panel) {
                panel.hidden = true;
            }
            if (button) {
                button.setAttribute('aria-expanded', 'false');
            }
        });
    };

    const closePax = () => {
        if (!paxPanel) {
            return;
        }
        paxPanel.hidden = true;
        paxToggle.setAttribute('aria-expanded', 'false');
    };

    const closeNav = () => {
        const links = q('#fsNavLinks');
        const burger = q('[data-fs-nav-toggle]');
        if (links) {
            links.classList.remove('is-open');
        }
        if (burger) {
            burger.setAttribute('aria-expanded', 'false');
        }
    };

    qa('[data-fs-pop-toggle]').forEach((button) => {
        button.addEventListener('click', (event) => {
            event.stopPropagation();
            const pop = button.closest('.fs-pop');
            const panel = q('[data-fs-pop-panel]', pop);
            const opening = panel.hidden;
            closePops();
            panel.hidden = !opening;
            button.setAttribute('aria-expanded', opening ? 'true' : 'false');
        });
    });

    const burger = q('[data-fs-nav-toggle]');
    if (burger) {
        burger.addEventListener('click', (event) => {
            event.stopPropagation();
            const links = q('#fsNavLinks');
            const open = !links.classList.contains('is-open');
            links.classList.toggle('is-open', open);
            burger.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.fs-pop')) {
            closePops();
        }
        if (!event.target.closest('[data-fs-pax]')) {
            closePax();
        }
        if (!event.target.closest('.fs-nav')) {
            closeNav();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') {
            return;
        }
        closePops();
        closePax();
        closeNav();
    });

    const travelers = () => paxState.adults + paxState.children + paxState.infants;

    const paxText = () => {
        if (paxState.children === 0 && paxState.infants === 0) {
            return paxState.adults + (paxState.adults === 1 ? ' Adult' : ' Adults');
        }
        return travelers() + (travelers() === 1 ? ' Traveler' : ' Travelers');
    };

    const renderPax = () => {
        const limits = {
            adults: [1, 9],
            children: [0, 8],
            infants: [0, Math.max(0, paxState.adults)],
        };
        Object.keys(limits).forEach((key) => {
            paxState.infants = Math.min(paxState.infants, paxState.adults);
            const [low, high] = limits[key];
            const display = q('[data-fs-pax-count="' + key + '"]');
            if (display) {
                display.textContent = paxState[key];
            }
            qa('[data-fs-pax-step="' + key + '"]').forEach((button) => {
                const delta = Number(button.dataset.delta);
                button.disabled = delta < 0
                    ? paxState[key] <= low
                    : paxState[key] >= high || travelers() >= 9;
            });
        });
        if (paxSummary) {
            paxSummary.textContent = paxText();
        }
        if (paxInput) {
            paxInput.value = travelers();
        }
        updateSummary();
    };

    qa('[data-fs-pax-step]').forEach((button) => {
        button.addEventListener('click', () => {
            const key = button.dataset.fsPaxStep;
            const delta = Number(button.dataset.delta);
            const next = paxState[key] + delta;
            const limits = {
                adults: [1, 9],
                children: [0, 8],
                infants: [0, paxState.adults],
            };
            const [low, high] = limits[key];
            paxState[key] = Math.min(high, Math.max(low, next));
            renderPax();
        });
    });

    if (paxToggle) {
        paxToggle.addEventListener('click', (event) => {
            event.stopPropagation();
            const opening = paxPanel.hidden;
            closePax();
            paxPanel.hidden = !opening;
            paxToggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
        });
    }

    const paxDone = q('[data-fs-pax-done]');
    if (paxDone) {
        paxDone.addEventListener('click', () => {
            closePax();
            paxToggle.focus();
        });
    }

    const tripType = () => (tripInput ? tripInput.value : 'oneway');
    const flightType = () => (flightTypeInput ? flightTypeInput.value : 'DOMESTIC');

    const paintTags = () => {
        const typeText = q('[data-fs-tag-type-text]');
        const typeIcon = q('[data-fs-tag-type] i');
        const tripText = q('[data-fs-tag-trip-text]');
        const wanted = flightType();
        if (typeText) {
            typeText.textContent = wanted === 'INTERNATIONAL' ? 'International' : 'Domestic';
        }
        if (typeIcon) {
            typeIcon.className = wanted === 'INTERNATIONAL'
                ? 'fas fa-earth-asia' : 'fas fa-map-location-dot';
        }
        if (tripText) {
            tripText.textContent = tripType() === 'multicity'
                ? 'Multi-City' : tripType() === 'oneway' ? 'One Way' : 'Round Trip';
        }
    };

    const airportWraps = () => ({
        from: q('[data-field="from"] [data-airport-picker]'),
        to: q('[data-field="to"] [data-airport-picker]'),
    });

    const readAirport = (wrap) => {
        const hidden = wrap && q('[data-airport-value]', wrap);
        if (!hidden || !hidden.value) {
            return null;
        }
        const record = {
            id: hidden.value,
            code: (hidden.dataset.airportCode || '').toUpperCase(),
            city: hidden.dataset.airportCity || '',
            country: hidden.dataset.airportCountry || '',
            countryCode: (hidden.dataset.airportCountryCode || '').toUpperCase(),
            address: hidden.dataset.airportAddress || '',
            name: hidden.dataset.airportName || '',
        };
        rememberAirport(record);
        return record;
    };

    const writeAirport = (wrap, record) => {
        if (!wrap) {
            return;
        }
        const hidden = q('[data-airport-value]', wrap);
        const input = q('[data-airport-input]', wrap);
        if (!hidden) {
            return;
        }
        hidden.value = record ? record.id : '';
        hidden.dataset.airportCode = record ? (record.code || '') : '';
        hidden.dataset.airportName = record ? (record.name || '') : '';
        hidden.dataset.airportCity = record ? (record.city || '') : '';
        hidden.dataset.airportCountry = record ? (record.country || '') : '';
        hidden.dataset.airportCountryCode = record ? (record.countryCode || '') : '';
        hidden.dataset.airportAddress = record ? (record.address || '') : '';
        if (input) {
            input.value = record
                ? [record.name, record.code ? '(' + record.code + ')' : ''].filter(Boolean).join(' ')
                : '';
        }
        hidden.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const currentRoute = () => {
        const wraps = airportWraps();
        return { from: readAirport(wraps.from), to: readAirport(wraps.to) };
    };

    const isDomesticPair = (origin, destination) => {
        if (!origin || !destination) {
            return null;
        }
        if (origin.countryCode && destination.countryCode) {
            return origin.countryCode === destination.countryCode;
        }
        if (origin.country && destination.country) {
            return origin.country.toLowerCase() === destination.country.toLowerCase();
        }
        return null;
    };

    const showSearchError = (message) => {
        if (!searchError) {
            return;
        }
        searchError.textContent = message || '';
        searchError.hidden = !message;
    };

    const validateRoute = (silent) => {
        if (!tripType()) {
            showSearchError(silent ? '' : 'Choose One Way, Round Trip or Multi-City.');
            return false;
        }
        if (tripType() === 'multicity') {
            return true;
        }
        const { from, to } = currentRoute();
        if (!from || !to) {
            showSearchError(silent ? '' : 'Select both a flying-from and flying-to airport.');
            return false;
        }
        if (from.id === to.id) {
            showSearchError(silent ? '' : 'Flying-from and flying-to airports must be different.');
            return false;
        }
        const domestic = isDomesticPair(from, to);
        const wanted = flightType();
        if (domestic !== null
            && ((wanted === 'DOMESTIC') !== domestic)) {
            showSearchError(
                from.city + ' (' + from.code + ') to ' + to.city + ' (' + to.code + ') is '
                + (domestic ? 'a domestic' : 'an international') + ' route, which does not match '
                + 'the ' + wanted.charAt(0) + wanted.slice(1).toLowerCase() + ' flight type. '
                + 'Choose ' + (domestic ? 'Domestic' : 'International') + ' or pick other airports.');
            return false;
        }
        showSearchError('');
        return true;
    };

    const validateDates = (silent) => {
        if (tripType() === 'multicity') {
            return true;
        }
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const departure = departInput && departInput.value
            ? new Date(departInput.value + 'T00:00:00') : null;
        const returning = returnInput && returnInput.value
            ? new Date(returnInput.value + 'T00:00:00') : null;
        if (!departure || Number.isNaN(departure.getTime())) {
            showSearchError(silent ? '' : 'Select a valid departure date.');
            return false;
        }
        if (departure < today) {
            showSearchError(silent ? '' : 'Departure date cannot be in the past.');
            return false;
        }
        if (tripType() === 'round') {
            if (!returning || Number.isNaN(returning.getTime())) {
                showSearchError(silent ? '' : 'Select a valid return date.');
                return false;
            }
            if (returning < departure) {
                showSearchError(silent ? '' : 'Return date cannot be before departure.');
                return false;
            }
        }
        return true;
    };

    const validateMultiCity = (silent) => {
        if (tripType() !== 'multicity') {
            return true;
        }
        const rows = legRows();
        if (rows.length < 2) {
            showSearchError(silent ? '' : 'A multi-city trip needs at least two flight segments.');
            return false;
        }
        for (let index = 0; index < rows.length; index += 1) {
            const row = rows[index];
            const origin = readAirport(q('[data-fs-leg-origin] [data-airport-picker]', row));
            const destination = readAirport(q('[data-fs-leg-destination] [data-airport-picker]', row));
            const dateInput = q('[data-fs-leg-depart]', row);
            if (!origin || !destination) {
                showSearchError(silent ? '' : 'Select both airports for segment ' + (index + 1) + '.');
                return false;
            }
            if (origin.id === destination.id) {
                showSearchError(silent ? '' : 'Segment ' + (index + 1) + ' must use different airports.');
                return false;
            }
            const domestic = isDomesticPair(origin, destination);
            if (domestic !== null && ((flightType() === 'DOMESTIC') !== domestic)) {
                showSearchError(
                    silent ? '' : 'Segment ' + (index + 1) + ' does not match the selected '
                    + flightType().toLowerCase() + ' flight type.'
                );
                return false;
            }
            if (!dateInput || !dateInput.value) {
                showSearchError(silent ? '' : 'Select a departure date for segment ' + (index + 1) + '.');
                return false;
            }
        }
        return true;
    };

    const updateCountryScope = () => {
        const wraps = airportWraps();
        const wanted = flightType();
        Object.values(wraps).forEach((wrap) => {
            if (!wrap) {
                return;
            }
            if (wanted === 'DOMESTIC' && formCountry) {
                wrap.dataset.airportCountry = formCountry;
            } else {
                delete wrap.dataset.airportCountry;
            }
        });
    };

    const updateSummary = () => {
        const route = q('[data-fs-summary-route]');
        const dates = q('[data-fs-summary-dates]');
        const pax = q('[data-fs-summary-pax]');
        const subtitle = q('[data-fs-results-sub]');
        const { from, to } = currentRoute();
        if (route) {
            route.textContent = (from ? labelOf(from.code) : 'Origin')
                + ' \u2192 ' + (to ? labelOf(to.code) : 'Destination');
        }
        if (dates) {
            const out = prettyDate(departInput.value);
            dates.textContent = tripType() === 'round'
                ? out + ' \u2013 ' + prettyDate(returnInput.value)
                : tripType() === 'multicity'
                    ? multiCityDatesText()
                    : out;
        }
        if (pax) {
            pax.textContent = travelers() + (travelers() === 1 ? ' Traveler' : ' Travelers');
        }
        if (subtitle) {
            const out = prettyDate(departInput.value);
            const datesText = tripType() === 'round'
                ? out + ' \u2013 ' + prettyDate(returnInput.value)
                : tripType() === 'multicity'
                    ? multiCityDatesText()
                    : out;
            subtitle.textContent = datesText + ' \u00b7 ' + travelers()
                + (travelers() === 1 ? ' traveler' : ' travelers');
        }
    };

    const legRows = () => qa('[data-fs-leg]', legsRoot || document);

    const renumberLegs = () => {
        legRows().forEach((row, index) => {
            const num = q('[data-fs-leg-num]', row);
            if (num) {
                num.textContent = index + 1;
            }
        });
        const rows = legRows();
        if (legsAdd) {
            legsAdd.disabled = rows.length >= 6;
        }
    };

    const multiCityDatesText = () => {
        const dates = legRows()
            .map((row) => prettyDate((q('[data-fs-leg-depart]', row) || {}).value))
            .filter(Boolean);
        if (!dates.length) {
            return 'Select segment dates';
        }
        if (dates.length === 1) {
            return dates[0];
        }
        return dates[0] + ' \u2013 ' + dates[dates.length - 1]
            + ' \u00b7 ' + dates.length + ' segments';
    };

    const syncLegDateLabels = (row) => {
        const label = q('[data-fs-leg-date-label]', row);
        const input = q('[data-fs-leg-depart]', row);
        if (label && input) {
            label.textContent = input.value ? prettyDate(input.value) : 'Select date';
        }
    };

    const bindLegRow = (row) => {
        qa('[data-airport-picker]', row).forEach((wrap) => {
            wrap.dataset.airportCountry = flightType() === 'DOMESTIC' && formCountry
                ? formCountry : '';
            if (!wrap.dataset.airportCountry) {
                delete wrap.dataset.airportCountry;
            }
            if (window.AirportPicker) {
                window.AirportPicker.init();
            }
        });
        const dateInput = q('[data-fs-leg-depart]', row);
        if (dateInput) {
            dateInput.addEventListener('change', () => {
                syncLegDateLabels(row);
                updateSummary();
            });
        }
        const remove = q('[data-fs-leg-remove]', row);
        if (remove) {
            remove.addEventListener('click', () => {
                if (legRows().length <= 2) {
                    showSearchError('A multi-city trip needs at least two segments.');
                    return;
                }
                row.remove();
                renumberLegs();
                updateSummary();
            });
        }
        syncLegDateLabels(row);
    };

    const bindRouteValidation = () => {
        const wraps = airportWraps();
        Object.values(wraps).forEach((wrap) => {
            const hidden = wrap && q('[data-airport-value]', wrap);
            if (!hidden) {
                return;
            }
            hidden.addEventListener('change', () => {
                validateRoute();
                updateSummary();
            });
        });
    };

    const addLegRow = () => {
        if (!legsRoot || legRows().length >= 6) {
            return;
        }
        const template = legsRoot.querySelector('[data-fs-leg]');
        if (!template) {
            return;
        }
        const clone = template.cloneNode(true);
        qa('[data-airport-input]', clone).forEach((input) => {
            input.value = '';
        });
        qa('[data-airport-value]', clone).forEach((hidden) => {
            hidden.value = '';
            hidden.dataset.airportCode = '';
            hidden.dataset.airportName = '';
            hidden.dataset.airportCity = '';
            hidden.dataset.airportCountry = '';
            hidden.dataset.airportCountryCode = '';
        });
        qa('[data-airport-picker]', clone).forEach((wrap) => {
            delete wrap.dataset.airportReady;
            wrap.classList.remove('has-apt', 'is-open');
            const list = q('[data-airport-list]', wrap);
            if (list) {
                list.innerHTML = '';
                list.hidden = true;
            }
            if (formCountry) {
                wrap.dataset.airportCountry = flightType() === 'DOMESTIC' ? formCountry : '';
            }
        });
        const dateInput = q('[data-fs-leg-depart]', clone);
        if (dateInput) {
            dateInput.value = '';
            dateInput.id = 'fsLegDate' + (legRows().length + 1);
        }
        legsRoot.appendChild(clone);
        bindLegRow(clone);
        renumberLegs();
        updateSummary();
    };

    const setTrip = (trip) => {
        qa('[data-fs-trip]').forEach((tab) => {
            const active = tab.dataset.fsTrip === trip;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (tripInput) {
            tripInput.value = trip;
        }
        if (returnField) {
            returnField.hidden = trip !== 'round';
        }
        if (returnInput) {
            const roundTrip = trip === 'round';
            returnInput.disabled = !roundTrip;
            returnInput.required = roundTrip;
            if (roundTrip && departInput) {
                returnInput.min = departInput.value || departInput.min;
            }
            if (window.ATRUE_DATE_PICKER) {
                window.ATRUE_DATE_PICKER.refresh(returnInput);
            }
        }
        if (multiPanel) {
            multiPanel.hidden = trip !== 'multicity';
        }
        const grid = q('[data-fs-grid]');
        if (grid) {
            grid.classList.toggle('is-multicity', trip === 'multicity');
        }
        paintTags();
        updateSummary();
    };

    const setFlightType = (value) => {
        if (!value) {
            return;
        }
        qa('[data-fs-flighttype]').forEach((tab) => {
            const active = tab.dataset.fsFlighttype === value.toLowerCase();
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (flightTypeInput) {
            flightTypeInput.value = value.toUpperCase();
        }
        updateCountryScope();
        legRows().forEach((row) => {
            qa('[data-airport-picker]', row).forEach((wrap) => {
                if (value.toUpperCase() === 'DOMESTIC' && formCountry) {
                    wrap.dataset.airportCountry = formCountry;
                } else {
                    delete wrap.dataset.airportCountry;
                }
            });
        });
        if (searchForm) {
            searchForm.dataset.fsFlightType = value.toLowerCase();
        }
        paintTags();
        validateRoute(true);
    };

    qa('[data-fs-trip]').forEach((tab) => {
        tab.addEventListener('click', () => setTrip(tab.dataset.fsTrip));
    });

    qa('[data-fs-flighttype]').forEach((tab) => {
        tab.addEventListener('click', () => setFlightType(tab.dataset.fsFlighttype));
    });

    if (legsAdd) {
        legsAdd.addEventListener('click', addLegRow);
    }

    if (swapButton) {
        swapButton.addEventListener('click', () => {
            const wraps = airportWraps();
            const from = readAirport(wraps.from);
            const to = readAirport(wraps.to);
            writeAirport(wraps.from, to);
            writeAirport(wraps.to, from);
            swapButton.classList.toggle('is-flipped');
            validateRoute();
            updateSummary();
        });
    }

    const syncDateLabels = () => {
        if (departInput && returnInput) {
            returnInput.min = departInput.value || departInput.min;
            if (returnInput.value && departInput.value
                    && returnInput.value < departInput.value) {
                returnInput.value = departInput.value;
                if (window.ATRUE_DATE_PICKER) {
                    window.ATRUE_DATE_PICKER.refresh(returnInput);
                }
            }
        }
        if (departLabel) {
            departLabel.textContent = prettyDate(departInput.value);
        }
        if (returnLabel) {
            returnLabel.textContent = prettyDate(returnInput.value);
        }
        updateSummary();
    };

    departInput.addEventListener('change', syncDateLabels);
    returnInput.addEventListener('change', () => {
        if (returnInput.value && departInput.value && returnInput.value < departInput.value) {
            returnInput.value = departInput.value;
        }
        syncDateLabels();
    });

    const syncRange = () => {
        let low = Number(minInput.value);
        let high = Number(maxInput.value);
        if (low > high - priceStep) {
            low = high - priceStep;
        }
        if (low < priceMin) {
            low = priceMin;
        }
        const left = ((low - priceMin) / (priceMax - priceMin)) * 100;
        const right = ((high - priceMin) / (priceMax - priceMin)) * 100;
        if (rangeFill) {
            rangeFill.style.left = left + '%';
            rangeFill.style.width = (right - left) + '%';
        }
        if (minLabel) {
            minLabel.textContent = peso(low);
        }
        if (maxLabel) {
            maxLabel.textContent = high >= priceMax ? peso(priceMax) + '+' : peso(high);
        }
    };

    minInput.addEventListener('input', () => {
        if (Number(minInput.value) > Number(maxInput.value) - priceStep) {
            minInput.value = Math.max(priceMin, Number(maxInput.value) - priceStep);
        }
        syncRange();
        applyFilters();
    });

    maxInput.addEventListener('input', () => {
        if (Number(maxInput.value) < Number(minInput.value) + priceStep) {
            maxInput.value = Math.min(priceMax, Number(minInput.value) + priceStep);
        }
        syncRange();
        applyFilters();
    });

    const checkedFilters = () => {
        const result = { stops: new Set(), airline: new Set(), band: new Set(), duration: new Set() };
        qa('[data-fs-filter]').forEach((input) => {
            if (input.checked) {
                result[input.dataset.fsFilter].add(input.value);
            }
        });
        return result;
    };

    const cardValue = (card, key) => {
        if (key === 'duration') {
            return card.dataset.durationBucket;
        }
        return card.dataset[key];
    };

    const matchesPrice = (card) => {
        const price = Number(card.dataset.price);
        return price >= Number(minInput.value) && price <= Number(maxInput.value);
    };

    const matchesOtherGroups = (card, checked, skip) => Object.keys(checked).every((key) => {
        if (key === skip) {
            return true;
        }
        const values = checked[key];
        return values.size === 0 || values.has(cardValue(card, key));
    });

    const refreshFacetCounts = (checked) => {
        qa('[data-fs-facet]').forEach((element) => {
            const parts = element.dataset.fsFacet.split(':');
            const group = parts[0];
            const value = parts[1];
            const total = cards.filter((card) => matchesPrice(card)
                && matchesOtherGroups(card, checked, group)
                && cardValue(card, group) === value).length;
            element.textContent = total;
            const row = element.closest('.fs-check');
            if (row) {
                row.classList.toggle('is-zero', total === 0);
            }
        });
    };

    const applyFilters = () => {
        const checked = checkedFilters();
        let visible = 0;
        cards.forEach((card) => {
            const show = matchesPrice(card) && matchesOtherGroups(card, checked, null);
            card.hidden = !show;
            if (show) {
                visible += 1;
            } else if (card.classList.contains('is-expanded')) {
                collapseCard(card);
            }
        });
        if (countElement) {
            countElement.textContent = 'Showing ' + visible + (visible === 1 ? ' result' : ' results');
        }
        if (emptyElement) {
            emptyElement.hidden = visible !== 0;
        }
        if (cardsElement) {
            cardsElement.hidden = visible === 0;
        }
        refreshFacetCounts(checked);
    };

    const clearFilters = () => {
        qa('[data-fs-filter]').forEach((input) => {
            input.checked = false;
        });
        minInput.value = priceMin;
        maxInput.value = priceMax;
        syncRange();
        applyFilters();
    };

    qa('[data-fs-clear], [data-fs-clear-all]').forEach((button) => {
        button.addEventListener('click', clearFilters);
    });

    qa('[data-fs-filter]').forEach((input) => {
        input.addEventListener('change', applyFilters);
    });

    qa('[data-fs-all]').forEach((button) => {
        button.addEventListener('click', () => {
            const group = button.dataset.fsAll;
            const inputs = qa('[data-fs-filter="' + group + '"]');
            const allChecked = inputs.every((input) => input.checked);
            inputs.forEach((input) => {
                input.checked = !allChecked;
            });
            button.textContent = allChecked ? 'Select all' : 'Clear';
            applyFilters();
        });
    });

    const sorters = {
        best: (a, b) => Number(a.dataset.rank.slice(2)) - Number(b.dataset.rank.slice(2)),
        'price-asc': (a, b) => Number(a.dataset.price) - Number(b.dataset.price)
            || Number(a.dataset.duration) - Number(b.dataset.duration),
        'price-desc': (a, b) => Number(b.dataset.price) - Number(a.dataset.price),
        'duration-asc': (a, b) => Number(a.dataset.duration) - Number(b.dataset.duration)
            || Number(a.dataset.price) - Number(b.dataset.price),
        'depart-asc': (a, b) => Number(a.dataset.depart) - Number(b.dataset.depart),
        'depart-desc': (a, b) => Number(b.dataset.depart) - Number(a.dataset.depart),
        'emissions-asc': (a, b) => Number(a.dataset.emissions) - Number(b.dataset.emissions),
    };

    const sortCards = (key) => {
        const sorter = sorters[key] || sorters['price-asc'];
        cards = cards.slice().sort(sorter);
        const fragment = document.createDocumentFragment();
        cards.forEach((card) => fragment.appendChild(card));
        cardsElement.appendChild(fragment);
    };

    const tabForSort = {
        'price-asc': 'price-asc',
        'price-desc': 'price-desc',
        'depart-asc': 'depart-asc',
        'depart-desc': 'depart-desc',
    };
    const sortForTab = {
        'price-asc': 'price-asc',
        'price-desc': 'price-desc',
        'depart-asc': 'depart-asc',
        'depart-desc': 'depart-desc',
    };

    const activateTab = (tabKey) => {
        qa('[data-fs-sort]').forEach((tab) => {
            const active = tabKey !== null && tab.dataset.fsSort === tabKey;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
    };

    qa('[data-fs-sort]').forEach((tab) => {
        tab.addEventListener('click', () => {
            activateTab(tab.dataset.fsSort);
            if (sortSelect && sortForTab[tab.dataset.fsSort]) {
                sortSelect.value = sortForTab[tab.dataset.fsSort];
            }
            sortCards(sortSelect ? sortSelect.value : 'price-asc');
        });
    });

    if (sortSelect) {
        sortSelect.addEventListener('change', () => {
            activateTab(tabForSort[sortSelect.value] || null);
            sortCards(sortSelect.value);
        });
    }

    const collapseCard = (card) => {
        const details = q('[data-fs-details]', card);
        const toggle = q('[data-fs-toggle]', card);
        card.classList.remove('is-expanded');
        if (details) {
            details.hidden = true;
        }
        if (toggle) {
            toggle.setAttribute('aria-expanded', 'false');
            toggle.setAttribute('aria-label', 'Show flight details for ' + (card.dataset.flight || 'this flight'));
        }
    };

    const toggleCard = (card, expand) => {
        const details = q('[data-fs-details]', card);
        const toggle = q('[data-fs-toggle]', card);
        const open = typeof expand === 'boolean' ? expand : details.hidden;
        cards.forEach((other) => {
            if (other !== card) {
                collapseCard(other);
            }
        });
        if (!details) {
            return;
        }
        details.hidden = !open;
        card.classList.toggle('is-expanded', open);
        if (toggle) {
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            toggle.setAttribute('aria-label', (open ? 'Hide' : 'Show') + ' flight details for ' + (card.dataset.flight || 'this flight'));
        }
    };

    cards.forEach((card) => {
        const toggle = q('[data-fs-toggle]', card);
        if (toggle) {
            toggle.addEventListener('click', () => toggleCard(card));
        }
        qa('[data-fs-disc]', card).forEach((button) => {
            button.addEventListener('click', () => {
                const panel = document.getElementById(button.getAttribute('aria-controls'));
                if (!panel) {
                    return;
                }
                const open = panel.hidden;
                panel.hidden = !open;
                button.setAttribute('aria-expanded', open ? 'true' : 'false');
            });
        });
        const selectButton = q('[data-fs-select]', card);
        if (selectButton) {
            selectButton.addEventListener('click', () => chooseFlight(card));
        }
    });

    const routeText = () => {
        if (selected && selected.origin && selected.destination) {
            return selected.origin + ' \u2192 ' + selected.destination;
        }
        const { from, to } = currentRoute();
        if (!from || !to) {
            return '';
        }
        return from.code + ' \u2192 ' + to.code;
    };

    const joinMeta = (parts) => parts.filter(Boolean).join(' \u00b7 ');

    const chooseFlight = (card) => {
        if (!selection) {
            return;
        }
        cards.forEach((other) => other.classList.remove('is-selected'));
        card.classList.add('is-selected');
        selected = {
            card: card,
            id: card.dataset.id,
            flight: card.dataset.flight,
            airline: card.dataset.airlineName,
            price: Number(card.dataset.price),
            origin: card.dataset.origin,
            destination: card.dataset.destination,
        };
        const total = selected.price * travelers();
        const datesText = tripType() === 'round'
            ? prettyDate(departInput.value) + ' \u2013 ' + prettyDate(returnInput.value)
            : prettyDate(departInput.value);
        selectionTitle.textContent = 'Flight selected';
        selectionMeta.textContent = joinMeta([
            selected.airline + ' ' + selected.flight,
            routeText(),
            datesText,
            peso(total) + ' total for ' + travelers()
                + (travelers() === 1 ? ' traveler' : ' travelers'),
        ]);
        selectionPicked.hidden = false;
        selectionConfirmed.hidden = true;
        selectionReturnFocus = document.activeElement;
        selection.hidden = false;
        document.body.classList.add('fs-selection-open');
        if (selectionClose) {
            selectionClose.focus();
        }
    };

    const closeSelectionModal = () => {
        if (!selection || selection.hidden) {
            return;
        }
        selection.hidden = true;
        document.body.classList.remove('fs-selection-open');
        const focusTarget = selected && selected.card
            ? q('[data-fs-select]', selected.card) : selectionReturnFocus;
        if (focusTarget && typeof focusTarget.focus === 'function') {
            focusTarget.focus();
        }
    };

    const resetSelection = () => {
        if (selected) {
            selected.card.classList.remove('is-selected');
        }
        selected = null;
        if (selection) {
            selection.hidden = true;
        }
        document.body.classList.remove('fs-selection-open');
    };

    if (selectionClose) {
        selectionClose.addEventListener('click', closeSelectionModal);
    }
    if (selection) {
        selection.addEventListener('click', (event) => {
            if (event.target === selection) {
                closeSelectionModal();
            }
        });
    }
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && selection && !selection.hidden) {
            closeSelectionModal();
        }
    });

    const changeSelection = q('[data-fs-selection-change]');
    if (changeSelection) {
        changeSelection.addEventListener('click', resetSelection);
    }

    const confirmSelection = q('[data-fs-selection-continue]');
    if (confirmSelection) {
        confirmSelection.addEventListener('click', () => {
            if (!selected) {
                return;
            }
            const total = selected.price * travelers();
            selectionConfirmMeta.textContent = joinMeta([
                selected.airline + ' ' + selected.flight,
                routeText(),
                peso(total) + ' total for ' + travelers()
                    + (travelers() === 1 ? ' traveler' : ' travelers'),
            ]);
            const passengerLink = q('[data-fs-selection-passenger]');
            if (passengerLink) {
                const { from, to } = currentRoute();
                const params = new URLSearchParams();
                const origin = selected.origin || (from && from.code);
                const destination = selected.destination || (to && to.code);
                if (origin) { params.set('origin', origin); }
                if (destination) { params.set('destination', destination); }
                const match = /(\d+)$/.exec(selected.id || '');
                if (match) { params.set('index', String(Number(match[1]) - 1)); }
                params.set('trip_type', tripType());
                params.set('passengers', 'adult:' + paxState.adults
                    + ',child:' + paxState.children
                    + ',infant:' + paxState.infants);
                if (departInput.value) { params.set('departure_date', departInput.value); }
                if (tripType() === 'round' && returnInput.value) {
                    params.set('return_date', returnInput.value);
                }
                passengerLink.href = passengerLink.getAttribute('href').split('?')[0]
                    + '?' + params.toString();
            }
            selectionPicked.hidden = true;
            selectionConfirmed.hidden = false;
        });
    }

    const backToResults = q('[data-fs-selection-back]');
    if (backToResults) {
        backToResults.addEventListener('click', () => {
            closeSelectionModal();
            if (selected) {
                selected.card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        });
    }

    const paintRoute = () => {
        // Every preview card has its own sample route; changing the search
        // form must not overwrite all cards with one route.
        updateSummary();
    };

    const scrollToResults = () => {
        const results = q('#fsResults');
        if (!results) {
            return;
        }
        const top = results.getBoundingClientRect().top + window.scrollY - 82;
        window.scrollTo({ top: top, behavior: 'smooth' });
    };

    if (searchForm) {
        searchForm.addEventListener('submit', (event) => {
            if (!validateRoute() || !validateDates() || !validateMultiCity()) {
                event.preventDefault();
                if (searchError) {
                    searchError.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                return;
            }
            if (returnInput.value && departInput.value && returnInput.value < departInput.value) {
                returnInput.value = departInput.value;
            }
            syncDateLabels();
            const tripValue = tripType() === 'oneway'
                ? 'ONE_WAY' : tripType() === 'round' ? 'ROUND_TRIP' : 'MULTI_CITY';
            tripInput.value = tripValue;
        });
    }

    const focusSearch = () => {
        if (!searchForm) {
            return;
        }
        searchForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
        searchForm.classList.add('is-highlight');
        window.setTimeout(() => {
            searchForm.classList.remove('is-highlight');
            const wraps = airportWraps();
            const input = wraps.from && q('[data-airport-input]', wraps.from);
            if (input) {
                input.focus({ preventScroll: true });
            }
        }, 420);
    };

    qa('[data-fs-focus-search], [data-fs-edit-search]').forEach((button) => {
        button.addEventListener('click', focusSearch);
    });

    if (filtersToggle && filters) {
        filtersToggle.addEventListener('click', () => {
            const open = filters.classList.toggle('is-open');
            filtersToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }

    const focusCard = (direction) => {
        const visible = cards.filter((card) => !card.hidden);
        if (!visible.length) {
            return;
        }
        const current = document.activeElement && document.activeElement.closest('[data-fs-card]');
        const index = current ? visible.indexOf(current) : -1;
        const next = visible[(index + direction + visible.length) % visible.length];
        const toggle = q('[data-fs-toggle]', next);
        if (toggle) {
            toggle.focus();
        }
    };

    document.addEventListener('keydown', (event) => {
        if (event.altKey && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            event.preventDefault();
            focusCard(event.key === 'ArrowDown' ? 1 : -1);
        }
    });

    renderPax();
    syncRange();
    syncDateLabels();
    bindRouteValidation();
    legRows().forEach(bindLegRow);
    renumberLegs();
    updateCountryScope();
    if (flightTypeInput && !flightTypeInput.value) {
        setFlightType('domestic');
    } else {
        setFlightType(flightTypeInput.value || 'domestic');
    }
    paintTags();
    sortCards('price-asc');
    applyFilters();
})();
