(function () {
    'use strict';

    var form = document.querySelector('[data-payment-form]');
    if (!form) return;

    var fieldsHost = form.querySelector('[data-payment-fields]');
    var hint = form.querySelector('#fp-method-hint');
    var methodInputs = Array.prototype.slice.call(form.querySelectorAll('input[name="payment_choice"]'));
    var methodCards = Array.prototype.slice.call(form.querySelectorAll('[data-method-card]'));
    var validatedInput = form.querySelector('[data-payment-validated]');
    var payButton = form.querySelector('[data-pay-now]');

    var methods = {
        gcash: {
            hint: 'Use training information only. No wallet account details are submitted.',
            fields: [['Account Holder Name', 'text', 'Demo Account Holder', true], ['GCash Mobile Number', 'tel', '09XX XXX XXXX', true], ['Reference Number', 'text', 'Optional for this simulation', false]]
        },
        maya: {
            hint: 'Use training information only. No wallet account details are submitted.',
            fields: [['Account Holder Name', 'text', 'Demo Account Holder', true], ['Maya Mobile Number', 'tel', '09XX XXX XXXX', true], ['Reference Number', 'text', 'Optional for this simulation', false]]
        },
        bank_transfer: {
            hint: 'Training transfer details are for display only and are never stored.',
            fields: [['Account Holder Name', 'text', 'Demo Account Holder', true], ['Bank Name', 'text', 'Training Bank', true], ['Reference Number', 'text', 'Optional for this simulation', false]]
        },
        credit_card: {
            hint: 'Demo card only. Real card numbers and security codes are never collected.',
            fields: [['Cardholder Name', 'text', 'Demo Account Holder', true], ['Reference Number', 'text', 'Optional for this simulation', false]]
        },
        debit_card: {
            hint: 'Demo card only. Real card numbers and security codes are never collected.',
            fields: [['Cardholder Name', 'text', 'Demo Account Holder', true], ['Reference Number', 'text', 'Optional for this simulation', false]]
        },
        paypal: {
            hint: 'Simulation only. Never enter a PayPal password.',
            fields: [['PayPal Account Holder Name', 'text', 'Demo Account Holder', true], ['PayPal Email Address', 'email', 'name@example.test', true], ['Reference Number', 'text', 'Optional for this simulation', false]]
        },
        qr_ph: {
            hint: 'Use the simulated QR Ph instruction below; no external payment is made.',
            fields: [['Transaction Reference Number', 'text', 'Optional for this simulation', false]],
            qr: true
        }
    };

    function renderField(field, index) {
        var id = 'fpPayerField' + index;
        var required = field[3] ? ' required aria-required="true"' : '';
        return '<label class="fp-checkout-field" for="' + id + '"><span>' + field[0] +
            (field[3] ? ' <b aria-hidden="true">*</b>' : '') + '</span><input id="' + id +
            '" type="' + field[1] + '" placeholder="' + field[2] + '"' + required +
            ' autocomplete="off"></label>';
    }

    function renderFields() {
        var selected = form.querySelector('input[name="payment_choice"]:checked');
        var method = selected ? selected.value : 'gcash';
        var definition = methods[method] || methods.gcash;

        methodCards.forEach(function (card) {
            var input = card.querySelector('input[name="payment_choice"]');
            card.classList.toggle('is-selected', Boolean(input && input.checked));
        });
        hint.textContent = definition.hint;

        var html = '';
        if (definition.qr) {
            html += '<div class="fp-checkout-qr"><span aria-hidden="true"><i class="fas fa-qrcode"></i></span>' +
                '<div><b>QR Ph training payment</b><small>Simulation only. No bank or wallet is contacted.</small></div></div>';
        }
        html += '<div class="fp-checkout-field-grid">' + definition.fields.map(renderField).join('') + '</div>';
        fieldsHost.innerHTML = html;
    }

    methodInputs.forEach(function (input) {
        input.addEventListener('change', renderFields);
    });

    form.addEventListener('submit', function (event) {
        if (!form.reportValidity()) {
            event.preventDefault();
            return;
        }
        if (form.dataset.submitting === 'true') {
            event.preventDefault();
            return;
        }
        if (validatedInput) validatedInput.value = '1';
        form.dataset.submitting = 'true';
        if (payButton) {
            payButton.disabled = true;
            payButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Processing…</span>';
        }
    });

    renderFields();
}());
