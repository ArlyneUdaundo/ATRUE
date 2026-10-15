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
        var sourceForm = parsed.querySelector('form.establishment-form-card') ||
            parsed.querySelector('.content form[method="post"]') ||
            parsed.querySelector('main form[method="post"]') ||
            parsed.querySelector('form[method="post"]');
        var content = sourceForm && (sourceForm.closest('.content') || parsed.querySelector('main') || parsed.body);
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
        if (window.ATRUELocationAutocomplete) window.ATRUELocationAutocomplete.init();
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
            if (form.matches('[data-staycation-form]') && response.headers.get('content-type', '').includes('application/json')) {
                var staycationResult = await response.json();
                if (!response.ok || !staycationResult.ok) {
                    var staycationError = body.querySelector('.staycation-edit-error');
                    if (!staycationError) {
                        staycationError = document.createElement('div');
                        staycationError.className = 'alert alert-error staycation-edit-error';
                        form.prepend(staycationError);
                    }
                    staycationError.textContent = staycationResult.error || 'Could not save this staycation.';
                    return;
                }
                var detailValue = function (selector, value) {
                    var node = document.querySelector(selector);
                    if (node) node.textContent = value;
                };
                detailValue('[data-staycation-detail-name]', staycationResult.name);
                detailValue('[data-staycation-detail-location]', staycationResult.location);
                detailValue('[data-staycation-detail-capacity]', staycationResult.capacity_adults + 'A / ' + staycationResult.capacity_children + 'C · up to ' + staycationResult.capacity + ' guests');
                detailValue('[data-staycation-detail-contact]', staycationResult.contact_number || '—');
                detailValue('[data-staycation-detail-email]', staycationResult.email || '—');
                detailValue('[data-staycation-detail-rate]', staycationResult.rate);
                var statusBadge = document.querySelector('[data-staycation-detail-status]');
                if (statusBadge) {
                    statusBadge.textContent = staycationResult.status_display;
                    statusBadge.classList.toggle('badge-green', staycationResult.status === 'ACTIVE');
                    statusBadge.classList.toggle('badge-red', staycationResult.status === 'SUSPENDED');
                    statusBadge.classList.toggle('badge-blue', !['ACTIVE', 'SUSPENDED'].includes(staycationResult.status));
                }
                var gallery = document.querySelector('[data-staycation-detail-gallery]');
                if (gallery) {
                    var updatedGallery;
                    if (staycationResult.photos.length) {
                        updatedGallery = document.createElement('div');
                        updatedGallery.className = 'hotel-gallery';
                        updatedGallery.style.cssText = 'display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px;margin-bottom:18px';
                        staycationResult.photos.forEach(function (url, index) {
                            var image = document.createElement('img');
                            image.src = url;
                            image.alt = staycationResult.name + ' photo ' + (index + 1);
                            image.loading = 'lazy';
                            image.decoding = 'async';
                            image.style.cssText = 'width:100%;height:230px;object-fit:cover;border-radius:14px';
                            updatedGallery.appendChild(image);
                        });
                    } else {
                        updatedGallery = document.createElement('div');
                        updatedGallery.id = 'staycation-gallery-fallback';
                        updatedGallery.className = 'hotel-gallery-fallback';
                        updatedGallery.style.marginBottom = '18px';
                        var placeholder = document.createElement('img');
                        placeholder.src = gallery.dataset.staycationPlaceholder;
                        placeholder.alt = staycationResult.name;
                        placeholder.style.cssText = 'width:100%;height:300px;object-fit:cover;border-radius:14px';
                        updatedGallery.appendChild(placeholder);
                    }
                    updatedGallery.setAttribute('data-staycation-detail-gallery', '');
                    updatedGallery.dataset.staycationPlaceholder = gallery.dataset.staycationPlaceholder;
                    gallery.replaceWith(updatedGallery);
                }
                closeModal();
                var notice = document.createElement('div');
                notice.className = 'alert alert-success';
                notice.setAttribute('role', 'status');
                notice.textContent = 'Staycation updated successfully.';
                document.querySelector('.content')?.prepend(notice);
                return;
            }
            if (form.matches('[data-landmark-form]') && response.headers.get('content-type', '').includes('application/json')) {
                var result = await response.json();
                if (!response.ok || !result.ok) {
                    var error = body.querySelector('.attraction-edit-error');
                    if (!error) {
                        error = document.createElement('div');
                        error.className = 'alert alert-error attraction-edit-error';
                        form.prepend(error);
                    }
                    error.textContent = (result.errors || ['Could not save the attraction.']).join(' ');
                    return;
                }
                var card = document.querySelector('[data-attraction-card][data-attraction-id="' + result.id + '"]');
                if (card) {
                    card.querySelector('[data-attraction-name]').textContent = result.name;
                    card.querySelector('[data-attraction-location]').textContent = result.location;
                    var badge = card.querySelector('[data-attraction-status]');
                    badge.textContent = result.status_display;
                    badge.classList.toggle('badge-green', result.status === 'ACTIVE');
                    badge.classList.toggle('badge-blue', result.status !== 'ACTIVE');
                    var image = card.querySelector('[data-attraction-photo]');
                    var placeholder = card.querySelector('[data-attraction-placeholder]');
                    if (result.image_url) {
                        if (!image) {
                            image = document.createElement('img');
                            image.setAttribute('data-attraction-photo', '');
                            image.alt = result.name;
                            image.loading = 'lazy';
                            image.style.cssText = 'width:96px;height:72px;object-fit:cover;border-radius:12px;flex:none';
                            if (placeholder) placeholder.replaceWith(image);
                            else card.querySelector('div[style*="display:flex"]').prepend(image);
                        }
                        image.src = result.image_url;
                        image.alt = result.name;
                    } else if (image) {
                        var empty = document.createElement('span');
                        empty.setAttribute('data-attraction-placeholder', '');
                        empty.className = 'scard-ico ico-blue';
                        empty.innerHTML = '<i class="fas fa-landmark"></i>';
                        image.replaceWith(empty);
                    }
                }
                closeModal();
                var notice = document.createElement('div');
                notice.className = 'alert alert-success';
                notice.setAttribute('role', 'status');
                notice.textContent = 'Attraction updated successfully.';
                document.querySelector('.content')?.prepend(notice);
                return;
            }
            var html = await response.text();
            if (response.redirected) {
                closeModal();
                // Keep the user on the page where Update/Edit was opened.
                // The redirect target is often a module list page, which would
                // defeat the modal flow after a successful save.
                window.location.reload();
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
        if (!link && target) {
            var candidate = target.closest('a[href]');
            if (candidate) {
                var label = (candidate.textContent || '').trim();
                var path = new URL(candidate.href, window.location.href).pathname;
                if (/\b(update|edit|manage)\b/i.test(label) && /\/(update|edit)(\/|$)/i.test(path)) {
                    link = candidate;
                }
            }
        }
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
                body.innerHTML = '<div class="alert alert-error">Hindi maipakita sa modal ang form (HTTP ' + response.status + '). <a href="' + url.href + '">Buksan ang form</a>.</div>';
            }
        } catch (error) {
            body.innerHTML = '<div class="alert alert-error">Hindi makuha ang form sa modal. <a href="' + url.href + '">Buksan ang form</a>.</div>';
        }
    }, true);

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal && !modal.hidden) closeModal();
    });
})();

