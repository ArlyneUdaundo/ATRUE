(function () {
    'use strict';

    var modal = null;
    var body = null;
    var activeLink = null;

    function ensureModal() {
        if (modal) return modal;
        modal = document.createElement('div');
        modal.className = 'establishment-modal';
        modal.hidden = true;
        modal.innerHTML = '<div class="establishment-modal__panel" role="dialog" aria-modal="true" aria-labelledby="establishmentModalTitle">' +
            '<div class="establishment-modal__top"><div class="establishment-modal__title"><span data-establishment-modal-logo></span><h2 id="establishmentModalTitle">Add establishment</h2></div>' +
            '<button type="button" class="establishment-modal__close" aria-label="Close"><i class="fas fa-xmark"></i></button></div>' +
            '<div class="establishment-modal__body"><div class="establishment-modal__loading"><i class="fas fa-spinner fa-spin"></i> Loading form...</div></div></div>';
        document.body.appendChild(modal);
        body = modal.querySelector('.establishment-modal__body');
        modal.querySelector('.establishment-modal__close').addEventListener('click', closeModal);
        modal.addEventListener('click', function (event) {
            if (event.target === modal) closeModal();
        });
        return modal;
    }

    function closeModal() {
        if (!modal) return;
        modal.hidden = true;
        document.body.classList.remove('establishment-modal-open');
        if (activeLink) activeLink.focus();
        activeLink = null;
    }

    function setLoading(message) {
        body.innerHTML = '<div class="establishment-modal__loading"><i class="fas fa-spinner fa-spin"></i> ' + message + '</div>';
    }

    function prepareForm(form, url) {
        form.action = url.href;
        form.addEventListener('submit', submitForm);
        form.addEventListener('change', async function (event) {
            if (!form.matches('[data-flight-form]') || !event.target.matches('[data-airline]')) return;
            var nextUrl = new URL(form.action, window.location.href);
            nextUrl.searchParams.set('airline', event.target.value);
            var trip = form.querySelector('[data-trip-type-sync]');
            var selectedType = form.querySelector('[data-flight-type]:checked');
            nextUrl.searchParams.set('trip_type', trip ? trip.value : 'ONE_WAY');
            nextUrl.searchParams.set('flight_type', selectedType && selectedType.value === 'CONNECTING' ? 'CONNECTING' : 'DIRECT');
            setLoading('Updating airline and aircraft options...');
            try {
                var response = await fetch(nextUrl.href, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
                var html = await response.text();
                if (!response.ok || !renderFormPage(html, nextUrl)) throw new Error('Could not update flight options.');
            } catch (error) {
                body.innerHTML = '<div class="alert alert-error">Hindi na-update ang airline options. Pakisubukan ulit.</div>';
            }
        });
        form.addEventListener('click', function (event) {
            var cancel = event.target.closest('a.btn-outline');
            if (cancel && /cancel/i.test(cancel.textContent)) {
                event.preventDefault();
                closeModal();
            }
        });
    }

    function renderFormPage(html, url) {
        var parsed = new DOMParser().parseFromString(html, 'text/html');
        var sourceForm = parsed.querySelector('form.establishment-form-card');
        var content = sourceForm && sourceForm.closest('.content');
        if (!sourceForm) return false;

        body.replaceChildren();
        var heading = content.querySelector('.page-head');
        if (heading && !sourceForm.matches('[data-flight-form], [data-agency-form], [data-account-create-form], [data-tour-package-form], [data-service-form], [data-amenity-form], [data-resort-form], [data-staycation-form], [data-restaurant-form], [data-landmark-form], [data-activity-form]') && !heading.classList.contains('room-form-page-head') && !heading.classList.contains('unit-form-page-head') && !heading.classList.contains('hotel-form-page-head') && !heading.classList.contains('session-form-page-head')) body.appendChild(heading.cloneNode(true));
        var form = sourceForm.cloneNode(true);
        body.appendChild(form);
        var title = sourceForm.dataset.modalTitle || (heading && heading.querySelector('h1') && heading.querySelector('h1').textContent.trim());
        if (title) modal.querySelector('#establishmentModalTitle').textContent = title;
        var modalLogo = modal.querySelector('[data-establishment-modal-logo]');
        if (modalLogo) {
            modalLogo.replaceChildren();
            if (form.matches('[data-flight-form]')) {
                var airlineLogo = sourceForm.querySelector('.airline-logo');
                var logoUrl = airlineLogo && airlineLogo.querySelector('img') && airlineLogo.querySelector('img').getAttribute('src');
                var airlineSelect = sourceForm.querySelector('[data-airline]');
                if (!logoUrl && airlineSelect && airlineSelect.selectedOptions.length) {
                    logoUrl = airlineSelect.selectedOptions[0].getAttribute('data-logo');
                }
                if (logoUrl) {
                    var logo = document.createElement('span');
                    logo.className = 'airline-logo';
                    var image = document.createElement('img');
                    image.src = logoUrl;
                    image.alt = (airlineLogo && airlineLogo.getAttribute('aria-label')) || 'Airline logo';
                    logo.appendChild(image);
                    modalLogo.appendChild(logo);
                } else if (airlineLogo) {
                    modalLogo.appendChild(airlineLogo.cloneNode(true));
                }
            }
        }
        prepareForm(form, url);
        if (window.AirportPicker) window.AirportPicker.init();
        parsed.querySelectorAll('script[data-establishment-modal-init]').forEach(function (source) {
            var initializer = document.createElement('script');
            initializer.textContent = source.textContent;
            body.appendChild(initializer);
            initializer.remove();
        });
        if (window.atrueLocationCascade) window.atrueLocationCascade.init(body);
        if (window.atrueLocationSelect) window.atrueLocationSelect.init(body);
        form.querySelector('input:not([type="hidden"]), select, textarea')?.focus({ preventScroll: true });
        return true;
    }

    function fillCombinedLocation(form) {
        [
            ['restaurant-location', ['barangay', 'municipality', 'province']],
            ['provider-location', ['barangay', 'municipality', 'province']]
        ].forEach(function (entry) {
            var hidden = form.querySelector('#' + entry[0]);
            if (!hidden) return;
            hidden.value = entry[1].map(function (key) {
                var field = form.querySelector('[data-cascade="' + key + '"], [data-cascade="' + key + '-text"]');
                return field && !field.disabled ? field.value.trim() : '';
            }).filter(Boolean).join(', ');
        });
    }

    async function submitForm(event) {
        event.preventDefault();
        var form = event.currentTarget;
        var button = event.submitter || form.querySelector('button[type="submit"]');
        var original = button ? button.innerHTML : '';
        fillCombinedLocation(form);
        if (button) {
            button.disabled = true;
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
        }
        try {
            var response = await fetch(form.action, {
                method: 'POST',
                body: new FormData(form),
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            var html = await response.text();
            if (response.redirected) {
                closeModal();
                window.location.assign(response.url);
                return;
            }
            if (response.ok && renderFormPage(html, new URL(form.action, window.location.href))) return;
            body.innerHTML = '<div class="alert alert-error">Hindi na-save ang establishment. Pakisubukan ulit.</div>';
        } catch (error) {
            body.innerHTML = '<div class="alert alert-error">Hindi makakonekta sa server. Pakisubukan ulit.</div>';
        } finally {
            if (button && button.isConnected) {
                button.disabled = false;
                button.innerHTML = original;
            }
        }
    }

    document.addEventListener('click', async function (event) {
        var target = event.target instanceof Element ? event.target : event.target.parentElement;
        var link = target && target.closest('[data-establishment-create]');
        if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        ensureModal();
        activeLink = link;
        modal.hidden = false;
        document.body.classList.add('establishment-modal-open');
        setLoading('Loading form...');
        var url = new URL(link.href, window.location.href);
        try {
            var response = await fetch(url.href, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            var html = await response.text();
            if (!response.ok || !renderFormPage(html, url)) {
                body.innerHTML = '<div class="alert alert-error">Hindi na-load ang form sa modal. Pakisubukan ulit.</div>';
            }
        } catch (error) {
            body.innerHTML = '<div class="alert alert-error">Hindi na-load ang form sa modal. Pakisubukan ulit.</div>';
        }
    }, true);

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal && !modal.hidden) closeModal();
    });
})();

