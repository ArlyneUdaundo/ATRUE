(function () {
  'use strict';

  const methods = [
    { value: 'GCASH', label: 'GCash', image: 'gcash.svg' },
    { value: 'MAYA', label: 'Maya', image: 'maya.svg' },
    { value: 'BANK_TRANSFER', label: 'Bank Transfer', image: 'bank-transfer.svg' },
    { value: 'CREDIT_CARD', label: 'Credit Card', image: 'credit-card.svg' },
    { value: 'DEBIT_CARD', label: 'Debit Card', image: 'debit-card.svg' },
    { value: 'PAYPAL', label: 'PayPal', image: 'paypal.svg' },
    { value: 'QR_PH', label: 'QR Ph', image: 'qr-ph.svg' }
  ];

  function iconNode(method) {
    const icon = document.createElement('span');
    icon.className = 'payment-method-icon';
    const image = document.createElement('img');
    image.src = '/static/img/payment-methods/' + method.image;
    image.alt = '';
    image.loading = 'lazy';
    image.decoding = 'async';
    image.setAttribute('aria-hidden', 'true');
    icon.appendChild(image);
    return icon;
  }
  function enhance(select) {
    if (select.dataset.paymentEnhanced === 'true') return;
    const oldValue = select.value;
    const supported = methods.some(method => method.value === oldValue);
    const chosen = supported ? oldValue : (select.required ? 'GCASH' : '');
    select.replaceChildren(...(select.required ? [] : [new Option('All methods', '')]),
      ...methods.map(method => new Option(method.label, method.value)));
    if (chosen) select.value = chosen;
    select.dataset.paymentEnhanced = 'true';
    select.classList.add('payment-method-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');

    const wrapper = document.createElement('div');
    wrapper.className = 'payment-method-control';
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'payment-method-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const icon = document.createElement('span');
    const label = document.createElement('span');
    label.className = 'payment-method-label';
    const caret = document.createElement('i');
    caret.className = 'fas fa-chevron-down payment-method-caret';
    caret.setAttribute('aria-hidden', 'true');
    trigger.append(icon, label, caret);

    const menu = document.createElement('div');
    menu.className = 'payment-method-menu';
    menu.hidden = true;
    menu.id = 'payment-method-list-' + Math.random().toString(36).slice(2, 10);
    menu.setAttribute('role', 'listbox');
    trigger.setAttribute('aria-controls', menu.id);
    const buttons = methods.map(method => {
      const option = document.createElement('button');
      option.type = 'button';
      option.className = 'payment-method-option';
      option.setAttribute('role', 'option');
      option.dataset.value = method.value;
      option.append(iconNode(method), document.createTextNode(method.label));
      const check = document.createElement('i');
      check.className = 'fas fa-check payment-method-check';
      check.setAttribute('aria-hidden', 'true');
      option.appendChild(check);
      option.addEventListener('click', () => {
        select.value = method.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        syncSelection();
        closeMenu(false);
        trigger.focus();
      });
      return option;
    });
    menu.append(...buttons);

    select.parentNode.insertBefore(wrapper, select);
    wrapper.append(select, trigger, menu);

    function syncSelection() {
      trigger.disabled = select.disabled;
      const selected = methods.find(method => method.value === select.value);
      icon.replaceChildren();
      if (selected) {
        icon.appendChild(iconNode(selected));
        label.textContent = selected.label;
      } else {
        label.textContent = select.options[select.selectedIndex]?.text || 'Choose a payment method';
      }
      buttons.forEach(option => option.setAttribute('aria-selected', String(option.dataset.value === select.value)));
      const fieldLabel = select.id
        ? document.querySelector('label[for="' + CSS.escape(select.id) + '"]')
        : null;
      const nearbyLabel = select.closest('.form-group, .form-field')?.querySelector('label')
        || select.parentElement?.querySelector('label');
      trigger.setAttribute('aria-label', ((fieldLabel || nearbyLabel)?.textContent.trim() || 'Payment method')
        + ': ' + label.textContent);
    }

    function closeMenu(returnFocus) {
      wrapper.classList.remove('is-open');
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (returnFocus) trigger.focus();
    }
    function openMenu() {
      menu.hidden = false;
      wrapper.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
      const active = buttons.find(option => option.dataset.value === select.value) || buttons[0];
      active.focus();
    }

    trigger.addEventListener('click', () => menu.hidden ? openMenu() : closeMenu(false));
    trigger.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openMenu();
      }
    });
    menu.addEventListener('keydown', event => {
      const current = buttons.indexOf(document.activeElement);
      if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); }
      else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        buttons[(current + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length].focus();
      } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        buttons[event.key === 'Home' ? 0 : buttons.length - 1].focus();
      }
    });
    document.addEventListener('click', event => {
      if (!wrapper.contains(event.target) && !menu.hidden) closeMenu(false);
    });
    select.addEventListener('change', syncSelection);
    syncSelection();
  }

  function initialize() {
    document.querySelectorAll('select[name="payment_method"], select[name="method"], select[name="mode_of_payment"]')
      .forEach(enhance);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
})();
