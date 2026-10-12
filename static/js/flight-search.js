(function () {
    'use strict';

    function selectedTripType(form) {
        var selected = form.querySelector('input[name="trip_type"]:checked');
        if (selected) return selected.value;
        var select = form.querySelector('select[name="trip_type"]');
        return select ? select.value : 'ONE_WAY';
    }

    function renderAirport(wrap) {
        var hidden = wrap.querySelector('[data-airport-value]');
        var text = wrap.querySelector('.atrue-airport-text');
        if (!hidden || !text) return;
        var code = hidden.dataset.airportCode || '';
        var city = hidden.dataset.airportCity || '';
        var country = hidden.dataset.airportCountry || '';
        text.textContent = hidden.value
            ? (code ? code + ' — ' : '') + [city, country].filter(Boolean).join(', ')
            : '';
        wrap.classList.toggle('has-apt', Boolean(hidden.value));
    }

    function swapAirports(form) {
        var origin = form.querySelector('[data-flight-origin] [data-airport-value]');
        var destination = form.querySelector('[data-flight-destination] [data-airport-value]');
        if (!origin || !destination) return;
        var keys = ['value', 'airportCode', 'airportCity', 'airportCountry'];
        var originState = keys.map(function (key) {
            return key === 'value' ? origin.value : origin.dataset[key];
        });
        keys.forEach(function (key, index) {
            if (key === 'value') origin.value = destination.value;
            else origin.dataset[key] = destination.dataset[key] || '';
            if (key === 'value') destination.value = originState[index];
            else destination.dataset[key] = originState[index] || '';
        });
        renderAirport(origin.closest('[data-airport-picker]'));
        renderAirport(destination.closest('[data-airport-picker]'));
    }

    function initForm(form) {
        var departure = form.querySelector('[data-flight-departure]');
        var returnField = form.querySelector('[data-flight-return-field]');
        var returnInput = form.querySelector('[data-flight-return]');
        var message = form.querySelector('[data-flight-validation-message]');
        var homeTab = form.querySelector('input[name="tab"]');

        function isFlightSearch() {
            return !homeTab || (form.querySelector('input[name="tab"]:checked') || {}).value === 'flights';
        }

        function refreshDates() {
            if (!isFlightSearch()) {
                departure?.setCustomValidity('');
                returnInput?.setCustomValidity('');
                return;
            }
            var roundTrip = selectedTripType(form) === 'ROUND_TRIP';
            if (departure) {
                departure.setCustomValidity(
                    departure.value ? '' : 'Select a departure date.'
                );
            }
            if (returnField) returnField.style.display = roundTrip ? '' : 'none';
            if (returnInput) {
                returnInput.disabled = !roundTrip;
                returnInput.required = roundTrip;
                returnInput.min = departure && departure.value
                    ? departure.value
                    : (departure ? departure.min : '');
                returnInput.setCustomValidity(
                    !roundTrip || returnInput.value
                        ? (
                            roundTrip
                            && departure
                            && departure.value
                            && returnInput.value < departure.value
                                ? 'Return date cannot be earlier than departure.'
                                : ''
                        )
                        : 'Select a return date.'
                );
            }
        }

        function setMessage(text) {
            if (!message) return;
            message.textContent = text;
            message.hidden = !text;
        }

        function validate(event) {
            if (!isFlightSearch()) return;
            setMessage('');
            var origin = form.querySelector('[data-flight-origin] [data-airport-value]');
            var destination = form.querySelector('[data-flight-destination] [data-airport-value]');
            if (origin && !origin.value) {
                event.preventDefault();
                setMessage('Select a flying-from airport.');
                form.querySelector('[data-flight-origin] [data-airport-toggle]')?.focus();
                return;
            }
            if (destination && !destination.value) {
                event.preventDefault();
                setMessage('Select a flying-to airport.');
                form.querySelector('[data-flight-destination] [data-airport-toggle]')?.focus();
                return;
            }
            if (departure && !departure.value) {
                event.preventDefault();
                setMessage('Select a departure date.');
                departure.focus();
                return;
            }
            if (
                selectedTripType(form) === 'ROUND_TRIP'
                && returnInput
                && !returnInput.value
            ) {
                event.preventDefault();
                setMessage('Select a return date.');
                returnInput.focus();
                return;
            }
            if (
                selectedTripType(form) === 'ROUND_TRIP'
                && departure
                && returnInput
                && returnInput.value < departure.value
            ) {
                event.preventDefault();
                setMessage('Return date cannot be earlier than departure.');
                returnInput.focus();
            }
        }

        form.querySelectorAll('input[name="trip_type"], select[name="trip_type"]')
            .forEach(function (input) {
                input.addEventListener('change', function () {
                    setMessage('');
                    refreshDates();
                });
            });
        form.querySelector('input[name="tab"]')?.addEventListener('change', refreshDates);
        departure?.addEventListener('change', refreshDates);
        returnInput?.addEventListener('change', refreshDates);
        form.querySelector('[data-flight-swap]')?.addEventListener('click', function () {
            swapAirports(form);
        });
        form.addEventListener('submit', validate);
        refreshDates();
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('form[data-flight-search]').forEach(initForm);
    });
})();
