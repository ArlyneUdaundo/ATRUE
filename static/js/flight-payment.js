(function () {
    'use strict';

    var form = document.querySelector('[data-payment-form]');
    if (!form) return;

    var methodInputs = Array.prototype.slice.call(form.querySelectorAll('input[name="payment_choice"]'));
    var methodCards = Array.prototype.slice.call(form.querySelectorAll('[data-method-card]'));
    var panels = Array.prototype.slice.call(form.querySelectorAll('[data-payment-panel]'));
    var errorBox = form.querySelector('[data-payment-error]');
    var payButton = form.querySelector('[data-pay-now]');
    var billingToggle = form.querySelector('[data-billing-toggle]');
    var billingContent = form.querySelector('#fp-billing-fields');
    var allowSubmit = false;

    var navBurger = document.querySelector('[data-fs-nav-toggle]');
    var navLinks = document.getElementById('fsNavLinks');
    if (navBurger && navLinks) {
        navBurger.addEventListener('click', function () {
            var open = navBurger.getAttribute('aria-expanded') !== 'true';
            navBurger.setAttribute('aria-expanded', open ? 'true' : 'false');
            navLinks.classList.toggle('fp-nav-open', open);
        });
    }
    document.querySelectorAll('[data-fs-pop-toggle]').forEach(function (button) {
        button.addEventListener('click', function () {
            var panel = button.parentElement.querySelector('[data-fs-pop-panel]');
            if (!panel) return;
            panel.hidden = !panel.hidden;
            button.setAttribute('aria-expanded', panel.hidden ? 'false' : 'true');
        });
    });

    function selectedMethod() {
        var input = methodInputs.find(function (item) { return item.checked; });
        return input ? input.value : 'card';
    }

    function syncMethod() {
        var method = selectedMethod();
        methodCards.forEach(function (card) {
            var input = card.querySelector('input[name="payment_choice"]');
            card.classList.toggle('is-selected', Boolean(input && input.checked));
        });
        panels.forEach(function (panel) {
            panel.hidden = panel.getAttribute('data-payment-panel') !== method;
        });
        if (errorBox) errorBox.hidden = true;
    }

    methodInputs.forEach(function (input) { input.addEventListener('change', syncMethod); });
    syncMethod();

    if (billingToggle && billingContent) {
        billingToggle.addEventListener('click', function () {
            var open = billingToggle.getAttribute('aria-expanded') !== 'true';
            billingToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            billingContent.hidden = !open;
        });
    }

    var bankSelect = form.querySelector('[data-bank]');
    if (bankSelect) {
        bankSelect.addEventListener('change', function () {
            bankSelect.removeAttribute('aria-invalid');
            var bankError = form.querySelector('[data-error="bank"]');
            if (bankError) bankError.textContent = '';
        });
    }

    var numberInput = form.querySelector('[data-card-number]');
    if (numberInput) {
        numberInput.addEventListener('input', function () {
            var digits = numberInput.value.replace(/\D/g, '').slice(0, 19);
            numberInput.value = digits.replace(/(.{4})/g, '$1 ').trim();
            clearFieldError('cardNumber');
        });
    }

    var expiryInput = form.querySelector('[data-expiry]');
    if (expiryInput) {
        expiryInput.addEventListener('input', function () {
            var digits = expiryInput.value.replace(/\D/g, '').slice(0, 4);
            expiryInput.value = digits.length > 2 ? digits.slice(0, 2) + ' / ' + digits.slice(2) : digits;
            clearFieldError('expiry');
        });
    }

    var cvvInput = form.querySelector('[data-cvv]');
    if (cvvInput) {
        cvvInput.addEventListener('input', function () {
            cvvInput.value = cvvInput.value.replace(/\D/g, '').slice(0, 4);
            clearFieldError('cvv');
        });
    }

    function setFieldError(key, message) {
        var target = form.querySelector('[data-error="' + key + '"]');
        if (target) target.textContent = message;
        var field = form.querySelector('[data-' + (key === 'cardholder' ? 'cardholder' : key === 'cardNumber' ? 'card-number' : key) + ']');
        if (field && field.setAttribute) field.setAttribute('aria-invalid', 'true');
    }

    function clearFieldError(key) {
        var target = form.querySelector('[data-error="' + key + '"]');
        if (target) target.textContent = '';
        var selector = key === 'cardholder' ? '[data-cardholder]' : key === 'cardNumber' ? '[data-card-number]' : key === 'expiry' ? '[data-expiry]' : key === 'cvv' ? '[data-cvv]' : null;
        var field = selector ? form.querySelector(selector) : null;
        if (field) field.removeAttribute('aria-invalid');
    }

    function validateCard() {
        var valid = true;
        var holder = form.querySelector('[data-cardholder]');
        var number = numberInput ? numberInput.value.replace(/\D/g, '') : '';
        var expiry = expiryInput ? expiryInput.value.replace(/\D/g, '') : '';
        var cvv = cvvInput ? cvvInput.value.replace(/\D/g, '') : '';
        ['cardholder', 'cardNumber', 'expiry', 'cvv'].forEach(clearFieldError);

        if (!holder || holder.value.trim().length < 2) {
            setFieldError('cardholder', 'Enter the name shown on the card.'); valid = false;
        }
        if (number.length < 13 || number.length > 19) {
            setFieldError('cardNumber', 'Enter a valid card number.'); valid = false;
        }
        var month = Number(expiry.slice(0, 2));
        var year = Number(expiry.slice(2));
        var today = new Date();
        var currentYear = today.getFullYear() % 100;
        if (expiry.length !== 4 || month < 1 || month > 12 || year < currentYear || (year === currentYear && month < today.getMonth() + 1)) {
            setFieldError('expiry', 'Enter a valid, unexpired date.'); valid = false;
        }
        if (cvv.length < 3 || cvv.length > 4) {
            setFieldError('cvv', 'Enter a 3 or 4 digit security code.'); valid = false;
        }
        return valid;
    }

    function validateBilling() {
        var fields = Array.prototype.slice.call(form.querySelectorAll('[data-billing-field]'));
        if (!fields.length || billingContent.hidden) return true;
        var anyFilled = fields.some(function (field) { return field.value.trim(); });
        var error = form.querySelector('[data-error="billing"]');
        if (error) error.textContent = '';
        fields.forEach(function (field) { field.removeAttribute('aria-invalid'); });
        if (!anyFilled) return true;
        var missing = fields.some(function (field) {
            var empty = !field.value.trim();
            if (empty) field.setAttribute('aria-invalid', 'true');
            return empty;
        });
        if (missing && error) error.textContent = 'Complete the billing address or leave all fields blank.';
        return !missing;
    }

    form.addEventListener('submit', function (event) {
        if (allowSubmit) return;
        event.preventDefault();
        if (errorBox) { errorBox.hidden = true; errorBox.textContent = ''; }

        var valid = true;
        if (selectedMethod() === 'card') valid = validateCard() && valid;
        if (selectedMethod() === 'bank') {
            var bank = form.querySelector('[data-bank]');
            var bankError = form.querySelector('[data-error="bank"]');
            if (!bank || !bank.value) {
                if (bankError) bankError.textContent = 'Choose a bank to continue.';
                if (bank) bank.setAttribute('aria-invalid', 'true');
                valid = false;
            } else if (bankError) bankError.textContent = '';
        }
        valid = validateBilling() && valid;
        if (!valid) {
            if (errorBox) { errorBox.textContent = 'Check the highlighted fields and try again.'; errorBox.hidden = false; }
            var firstInvalid = form.querySelector('[aria-invalid="true"]');
            if (firstInvalid) firstInvalid.focus();
            return;
        }

        if (payButton) {
            payButton.disabled = true;
            payButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Processing simulated payment…</span>';
        }
        var validatedField = form.querySelector('[data-payment-validated]');
        if (validatedField) validatedField.value = '1';
        window.setTimeout(function () {
            allowSubmit = true;
            form.requestSubmit();
        }, 450);
    });
}());
