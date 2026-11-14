(function () {
    'use strict';

    var trigger = document.querySelector('[data-announcement-modal-open]');
    var dialog = document.querySelector('[data-announcement-dialog]');
    if (!trigger || !dialog || !dialog.showModal) return;

    var content = dialog.querySelector('[data-announcement-modal-content]');
    var endpoint = trigger.href + '?modal=1';

    function close() {
        if (dialog.open) dialog.close();
    }

    function showError(message) {
        content.innerHTML = '<p class="sim-announcement-dialog__error" role="alert"></p>';
        content.querySelector('[role="alert"]').textContent = message;
    }

    trigger.addEventListener('click', function (event) {
        event.preventDefault();
        content.innerHTML = '<p>Loading announcement form…</p>';
        dialog.showModal();
        fetch(endpoint, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (response) {
                if (!response.ok) throw new Error('The announcement form could not be loaded.');
                return response.text();
            })
            .then(function (html) {
                content.innerHTML = html;
                var firstInput = content.querySelector('select, input, textarea');
                if (firstInput) firstInput.focus();
            })
            .catch(function (error) { showError(error.message); });
    });

    dialog.addEventListener('click', function (event) {
        if (event.target.closest('[data-announcement-modal-close]')) close();
        if (event.target === dialog) close();
    });

    dialog.addEventListener('submit', function (event) {
        var form = event.target.closest('[data-announcement-modal-form]');
        if (!form) return;
        event.preventDefault();
        var submit = form.querySelector('[type="submit"]');
        if (submit) submit.disabled = true;
        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (response) {
            var contentType = response.headers.get('content-type') || '';
            if (contentType.indexOf('application/json') !== -1) {
                return response.json().then(function (data) {
                    if (!response.ok) throw new Error(data.error || 'The announcement could not be sent.');
                    window.location.assign(data.redirect);
                });
            }
            return response.text().then(function (html) {
                content.innerHTML = html;
                var alert = content.querySelector('[role="alert"]');
                if (alert) alert.focus();
            });
        }).catch(function (error) {
            showError(error.message);
        });
    });

    dialog.addEventListener('close', function () { trigger.focus(); });
})();
