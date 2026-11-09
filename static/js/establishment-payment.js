(function () {
  'use strict';

  var form = document.getElementById('establishmentPaymentForm');
  var fieldHost = document.getElementById('epDynamicFields');
  var hint = document.getElementById('epMethodHint');
  var payLater = document.getElementById('epPayLater');
  var confirmButton = document.getElementById('epConfirm');
  if (!form || !fieldHost || !hint || !payLater || !confirmButton) return;

  var total = form.dataset.total || '';
  var definitions = {
    GCASH: { hint: 'Use training information only. No wallet account details are submitted.', fields: [['Account Holder Name', 'text', 'Demo Account Holder', true], ['GCash Mobile Number', 'tel', '09XX XXX XXXX', true], ['Reference Number', 'text', 'Optional for this simulation', false]] },
    MAYA: { hint: 'Use training information only. No wallet account details are submitted.', fields: [['Account Holder Name', 'text', 'Demo Account Holder', true], ['Maya Mobile Number', 'tel', '09XX XXX XXXX', true], ['Reference Number', 'text', 'Optional for this simulation', false]] },
    BANK_TRANSFER: { hint: 'Training transfer details are for display only and are never stored.', fields: [['Bank Name', 'text', 'Training Bank', true], ['Account Holder Name', 'text', 'Demo Account Holder', true], ['Account Number', 'text', 'Dummy account number only', true], ['Transaction Reference Number', 'text', 'Enter a demo reference', true]] },
    CREDIT_CARD: { hint: 'Demo card only. Real card numbers and security codes are never collected.', card: true },
    DEBIT_CARD: { hint: 'Demo card only. Real card numbers and security codes are never collected.', card: true },
    PAYPAL: { hint: 'Simulation only. Never enter a PayPal password.', fields: [['PayPal Account Holder Name', 'text', 'Demo Account Holder', true], ['PayPal Email Address', 'email', 'name@example.test', true], ['Transaction Reference Number', 'text', 'Optional for this simulation', false]] },
    QR_PH: { hint: 'Use the simulated QR Ph instruction below; no external payment is made.', qr: true, fields: [['Transaction Reference Number', 'text', 'Enter a demo reference', true]] }
  };

  function renderField(field, index) {
    var id = 'epField' + index;
    var required = field[3] ? ' required aria-required="true"' : '';
    var inputMode = field[1] === 'tel' ? 'tel' : 'text';
    return '<label class="ep-field" for="' + id + '"><span>' + field[0] + (field[3] ? ' <b aria-hidden="true">*</b>' : '') + '</span>' +
      '<input id="' + id + '" type="' + field[1] + '" placeholder="' + field[2] + '"' + required + ' autocomplete="off" inputmode="' + inputMode + '"></label>';
  }

  function render() {
    var selected = form.querySelector('input[name="payment_method"]:checked');
    var method = selected ? selected.value : 'GCASH';
    var definition = definitions[method] || definitions.GCASH;
    form.querySelectorAll('.ep-method').forEach(function (label) {
      label.classList.toggle('is-selected', label.querySelector('input').checked);
    });
    hint.textContent = definition.hint;

    var html = '';
    if (definition.card) {
      html = '<div class="ep-demo-fields"><div><span>Cardholder Name</span><b>TRAINING USER</b></div>' +
        '<div><span>Card Number</span><b>•••• •••• •••• 4242</b></div><div><span>Expiration Date</span><b>12/30</b></div>' +
        '<div><span>CVV / Security Code</span><b>Not collected</b></div></div>' +
        '<p class="ep-security-note"><i class="fas fa-lock"></i> These are fixed demo values. No real card information or security code is requested or stored.</p>';
    } else if (definition.qr) {
      html = '<div class="ep-qr-panel"><div class="ep-qr-mark" aria-hidden="true"><i class="fas fa-qrcode"></i></div>' +
        '<div><b>QR Ph Training Payment</b><p>Scan simulation only. No bank or wallet is contacted.</p><span>Demo reference: QRPH-TRAINING</span></div></div>';
    }
    if (definition.fields) html += '<div class="ep-fields-grid">' + definition.fields.map(renderField).join('') + '</div>';
    fieldHost.innerHTML = html;
  }

  form.querySelectorAll('input[name="payment_method"]').forEach(function (radio) {
    radio.addEventListener('change', render);
  });
  payLater.addEventListener('change', function () {
    confirmButton.querySelector('span').textContent = payLater.checked
      ? 'Save Booking · ' + total
      : 'Confirm Payment · ' + total;
  });
  form.addEventListener('submit', function (event) {
    if (event.submitter && event.submitter.name === 'clear_selection') return;
    if (!form.reportValidity()) {
      event.preventDefault();
      return;
    }
    if (form.dataset.submitting === 'true') {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    confirmButton.disabled = true;
    confirmButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Processing…</span>';
  });
  render();
}());
