(function () {
    'use strict';
    var modal = document.getElementById('passwordResetModal');
    var form = document.getElementById('passwordResetForm');
    if (!modal || !form) return;
    var message = document.getElementById('passwordResetMessage');
    var success = document.getElementById('passwordResetSuccess');
    var submit = document.getElementById('passwordResetSubmit');
    var prior = null;
    var previousModal = null;
    var submitting = false;

    function resetState() {
        submitting = false;
        form.hidden = false;
        success.hidden = true;
        message.hidden = true;
        message.textContent = '';
        form.reset();
        submit.disabled = false;
        submit.textContent = 'Send reset instructions';
    }
    function open(event) {
        if (event) event.preventDefault();
        resetState();
        prior = document.activeElement;
        previousModal = document.getElementById('landingSignInModal');
        if (previousModal && !previousModal.hidden) previousModal.hidden = true;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        window.setTimeout(function () { document.getElementById('passwordResetEmail').focus(); }, 20);
    }
    function close(restoreFocus) {
        modal.hidden = true;
        document.body.style.overflow = '';
        resetState();
        if (previousModal && previousModal.hidden) previousModal.hidden = false;
        if (restoreFocus !== false && prior && prior.focus) prior.focus();
    }
    document.addEventListener('click', function (event) {
        var target = event.target;
        if (!(target instanceof Element)) return;
        var trigger = target.closest('[data-password-reset-open]');
        if (trigger) open(event);
        if (target.closest('[data-password-reset-close]')) close();
        if (target.closest('[data-password-reset-back]')) close();
        if (target === modal) close();
    });
    document.addEventListener('keydown', function (event) {
        if (!modal.hidden && event.key === 'Escape') close();
    });
    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        if (submitting) return;
        submitting = true;
        submit.disabled = true;
        submit.textContent = 'Sending…';
        message.hidden = true;
        try {
            var response = await fetch(form.action, {
                method: 'POST', body: new FormData(form), credentials: 'same-origin',
                headers: {'X-ATRUE-RESET-MODAL': '1'}
            });
            var result = await response.json();
            if (!response.ok || !result.ok) throw new Error('We could not process your request. Please try again.');
            form.hidden = true;
            success.hidden = false;
            success.querySelector('p').textContent = result.message;
            success.querySelector('[data-password-reset-back]').focus();
        } catch (error) {
            message.textContent = error.message || 'We could not process your request. Please try again.';
            message.hidden = false;
            submitting = false;
            submit.disabled = false;
            submit.textContent = 'Try again';
            message.focus();
        }
    });

    var query = new URLSearchParams(window.location.search);
    if (query.get('reset') === '1') {
        open();
        if (query.get('reset_sent') === '1') {
            form.hidden = true;
            success.hidden = false;
            success.querySelector('p').textContent = 'If an account matches that email, password reset instructions will be sent shortly.';
            success.querySelector('[data-password-reset-back]').focus();
        }
    }
})();
