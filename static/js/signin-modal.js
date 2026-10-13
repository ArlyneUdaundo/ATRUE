(function () {
    'use strict';
    var modal = document.getElementById('landingSignInModal');
    var form = document.getElementById('landingSignInForm');
    if (!modal || !form) return;
    var errorBox = document.getElementById('landingSignInError');
    var submit = document.getElementById('landingSignInSubmit');
    var username = form.querySelector('input[name="username"]');
    var previousFocus = null;

    function openModal(event) {
        if (event) event.preventDefault();
        previousFocus = document.activeElement;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        window.setTimeout(function () { username.focus(); }, 20);
    }
    function closeModal() {
        modal.hidden = true;
        document.body.style.overflow = '';
        if (previousFocus && previousFocus.focus) previousFocus.focus();
    }

    document.querySelectorAll('[data-signin-open]').forEach(function (button) {
        button.addEventListener('click', openModal);
    });
    modal.querySelectorAll('[data-signin-close]').forEach(function (button) {
        button.addEventListener('click', closeModal);
    });
    modal.addEventListener('click', function (event) {
        if (event.target === modal) closeModal();
    });
    document.addEventListener('keydown', function (event) {
        if (!modal.hidden && event.key === 'Escape') closeModal();
    });

    form.addEventListener('submit', function (event) {
        event.preventDefault();
        errorBox.hidden = true;
        errorBox.textContent = '';
        submit.disabled = true;
        submit.textContent = 'Signing in?';
        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-ATRUE-LOGIN-MODAL': '1' },
            credentials: 'same-origin'
        }).then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok || !data.ok) throw data;
                var destination = new URL(data.redirect, window.location.origin);
                if (window.ATRUE_CTX) destination.searchParams.set('ctx', window.ATRUE_CTX);
                window.location.assign(destination.pathname + destination.search + destination.hash);
            });
        }).catch(function (data) {
            var messages = [];
            if (data && data.errors) {
                Object.keys(data.errors).forEach(function (key) {
                    messages = messages.concat(data.errors[key] || []);
                });
            }
            errorBox.textContent = messages.join(' ') || 'Sign in failed. Please check your details and try again.';
            errorBox.hidden = false;
            submit.disabled = false;
            submit.innerHTML = 'Log In &rarr;';
            form.querySelector('input[name="password"]').value = '';
        });
    });
})();
