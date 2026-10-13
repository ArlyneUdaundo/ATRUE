(function () {
    'use strict';
    var modal = document.getElementById('passwordResetModal');
    var form = document.getElementById('passwordResetForm');
    if (!modal || !form) return;
    var message = document.getElementById('passwordResetMessage');
    var submit = document.getElementById('passwordResetSubmit');
    var prior = null;
    var previousModal = null;
    function open(event) {
        if (event) event.preventDefault();
        prior = document.activeElement;
        previousModal = document.getElementById('landingSignInModal');
        if (previousModal && !previousModal.hidden) previousModal.hidden = true;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        window.setTimeout(function () { document.getElementById('passwordResetEmail').focus(); }, 20);
    }
    function close() {
        modal.hidden = true;
        document.body.style.overflow = '';
        if (previousModal && previousModal.hidden) previousModal.hidden = false;
        if (prior && prior.focus) prior.focus();
    }
    document.addEventListener('click', function (event) {
        var trigger = event.target.closest('[data-password-reset-open]');
        if (trigger) open(event);
        if (event.target.closest('[data-password-reset-close]')) close();
        if (event.target === modal) close();
    });
    document.addEventListener('keydown', function (event) {
        if (!modal.hidden && event.key === 'Escape') close();
    });
    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        submit.disabled = true;
        message.hidden = true;
        try {
            var response = await fetch(form.action, {
                method: 'POST', body: new FormData(form), credentials: 'same-origin',
                headers: {'X-ATRUE-RESET-MODAL': '1'}
            });
            var result = await response.json();
            if (!response.ok || !result.ok) throw new Error('Could not submit the reset request. Try again.');
            message.classList.remove('hm-signin-error');
            message.classList.add('alert', 'alert-success');
            message.textContent = result.message;
            message.hidden = false;
            form.reset();
        } catch (error) {
            message.classList.remove('alert', 'alert-success');
            message.classList.add('hm-signin-error');
            message.textContent = error.message || 'Could not submit the reset request. Try again.';
            message.hidden = false;
        } finally {
            submit.disabled = false;
        }
    });
})();