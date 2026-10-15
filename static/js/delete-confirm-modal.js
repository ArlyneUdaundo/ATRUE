(function () {
    'use strict';

    var overlay = null;
    var titleNode = null;
    var messageNode = null;
    var cancelButton = null;
    var confirmButton = null;
    var pendingAction = null;
    var pendingCancel = null;
    var returnFocus = null;

    function ensureModal() {
        if (overlay) return;
        overlay = document.createElement('dialog');
        overlay.className = 'delete-confirm-modal';
        overlay.setAttribute('aria-labelledby', 'deleteConfirmTitle');
        overlay.setAttribute('aria-describedby', 'deleteConfirmMessage');
        overlay.hidden = true;
        overlay.innerHTML = '<div class="delete-confirm-modal__panel">' +
            '<div class="delete-confirm-modal__icon"><i class="fas fa-trash-alt" aria-hidden="true"></i></div>' +
            '<h2 id="deleteConfirmTitle">Are you sure you want to remove this?</h2>' +
            '<p id="deleteConfirmMessage">Are you sure you want to delete this?</p>' +
            '<div class="delete-confirm-modal__actions"><button type="button" class="delete-confirm-modal__cancel">Cancel</button>' +
            '<button type="button" class="delete-confirm-modal__confirm">Delete</button></div></div>';
        document.body.appendChild(overlay);
        titleNode = overlay.querySelector('#deleteConfirmTitle');
        messageNode = overlay.querySelector('#deleteConfirmMessage');
        cancelButton = overlay.querySelector('.delete-confirm-modal__cancel');
        confirmButton = overlay.querySelector('.delete-confirm-modal__confirm');
        cancelButton.addEventListener('click', function () { closeModal(true); });
        overlay.addEventListener('click', function (event) {
            if (event.target === overlay) closeModal(true);
        });
        confirmButton.addEventListener('click', function () {
            if (!pendingAction) return;
            var action = pendingAction;
            pendingAction = null;
            pendingCancel = null;
            confirmButton.disabled = true;
            confirmButton.textContent = 'Processing…';
            closeModal(false);
            action();
        });
        overlay.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                event.preventDefault();
                closeModal(true);
                return;
            }
            if (event.key === 'Tab') {
                var focusable = [cancelButton, confirmButton];
                var index = focusable.indexOf(document.activeElement);
                if (event.shiftKey && index <= 0) {
                    event.preventDefault();
                    confirmButton.focus();
                } else if (!event.shiftKey && index === focusable.length - 1) {
                    event.preventDefault();
                    cancelButton.focus();
                }
            }
        });
    }

    function closeModal(cancelled) {
        if (!overlay || overlay.hidden) return;
        var cancelAction = cancelled ? pendingCancel : null;
        if (overlay.open) overlay.close();
        overlay.hidden = true;
        document.body.classList.remove('delete-confirm-open');
        pendingAction = null;
        pendingCancel = null;
        confirmButton.disabled = false;
        confirmButton.textContent = 'Yes, Delete';
        if (cancelAction) cancelAction();
        if (returnFocus && returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
        returnFocus = null;
    }

    function askForDelete(message, action, trigger, options) {
        options = options || {};
        ensureModal();
        returnFocus = trigger || document.activeElement;
        messageNode.textContent = message || 'Are you sure you want to remove this?';
        titleNode.textContent = options.title || 'Are you sure you want to remove this?';
        confirmButton.textContent = options.confirmLabel || 'Yes, Delete';
        overlay.hidden = false;
        if (typeof overlay.showModal === 'function' && !overlay.open) overlay.showModal();
        document.body.classList.add('delete-confirm-open');
        pendingAction = action;
        pendingCancel = options.onCancel || null;
        cancelButton.focus({ preventScroll: true });
    }

    function hasSelectedRemoval(form) {
        return selectedRemovalInputs(form).length > 0;
    }

    function hasRemoveAction(form) {
        if (!(form instanceof HTMLFormElement)) return false;
        return Array.prototype.some.call(form.querySelectorAll('[name="action"], [data-action]'), function (control) {
            var value = control.value || control.dataset.action || '';
            return /^(delete|remove)$/i.test(String(value).trim());
        });
    }

    function selectedRemovalInputs(form) {
        return Array.prototype.slice.call(form.querySelectorAll('input[type="checkbox"]:checked'))
            .filter(function (input) { return /delete|remove/i.test(input.name || ''); });
    }

    function isPhotoRemoval(inputs) {
        return inputs.some(function (input) { return /photo|image|logo/i.test(input.name || ''); });
    }

    function updatePendingRemovalStatus(form) {
        if (!(form instanceof HTMLFormElement)) return;
        var status = form.querySelector('[data-delete-pending-status]');
        if (!status) {
            status = document.createElement('p');
            status.className = 'delete-confirm-pending-status';
            status.setAttribute('data-delete-pending-status', '');
            status.setAttribute('role', 'status');
            status.hidden = true;
            var firstRemoval = form.querySelector('input[type="checkbox"][name*="delete" i], input[type="checkbox"][name*="remove" i]');
            var section = firstRemoval && (firstRemoval.closest('.form-group') || firstRemoval.closest('.form-section'));
            if (section) section.appendChild(status);
            else {
                var submit = form.querySelector('button[type="submit"], input[type="submit"]');
                if (submit && submit.parentNode) submit.parentNode.insertBefore(status, submit);
                else form.appendChild(status);
            }
        }
        var selected = selectedRemovalInputs(form);
        status.hidden = selected.length === 0;
        if (selected.length) {
            var noun = isPhotoRemoval(selected) ? (selected.length === 1 ? 'photo' : 'photos') : (selected.length === 1 ? 'item' : 'items');
            status.textContent = selected.length + ' ' + noun + ' marked for removal. Save or update the form, then confirm to remove ' + (selected.length === 1 ? 'it' : 'them') + '.';
        }
    }

    function isDeleteConfirmation(element, submitter) {
        if (!element) return false;
        if (element.dataset && element.dataset.confirm) return true;
        var isForm = element instanceof HTMLFormElement;
        var action = element.getAttribute && element.getAttribute('action');
        var label = [
            element.dataset && element.dataset.confirm,
            action,
            element.getAttribute && element.getAttribute('href'),
            element.getAttribute && element.getAttribute('aria-label'),
            element.getAttribute && element.getAttribute('name'),
            element.getAttribute && element.getAttribute('value'),
            submitter && submitter.getAttribute && submitter.getAttribute('aria-label'),
            submitter && submitter.name,
            submitter && submitter.value,
            submitter && submitter.textContent
        ].filter(Boolean).join(' ');
        if (!isForm) label += ' ' + (element.textContent || '');
        if (isForm && (hasSelectedRemoval(element) || hasRemoveAction(element))) return true;
        var actionUrl = element.getAttribute && (element.getAttribute('action') || element.getAttribute('href')) || '';
        if (/\/(delete|remove)(\/|\?|$)|\b(delete|remove)_/i.test(actionUrl)) return true;
        if (element.dataset && element.dataset.confirm) return true;
        if (isForm && /delete|remove/i.test(label) && (element.method || '').toLowerCase() === 'post') return true;
        if (submitter && submitter.type === 'submit' && /delete|remove/i.test(label) &&
                submitter.closest && submitter.closest('form') && (submitter.closest('form').method || '').toLowerCase() === 'post') return true;
        return (element instanceof HTMLAnchorElement || element instanceof HTMLButtonElement || element instanceof HTMLInputElement) && /delete|remove/i.test(label);
    }

    function confirmationMessage(element, submitter) {
        var explicit = element && element.dataset && element.dataset.confirm;
        if (explicit) return explicit;
        if (element instanceof HTMLFormElement && hasSelectedRemoval(element)) {
            var selections = selectedRemovalInputs(element);
            var count = selections.length;
            var noun = isPhotoRemoval(selections) ? (count === 1 ? 'photo' : 'photos') : (count === 1 ? 'item' : 'items');
            return 'Are you sure you want to remove ' + count + ' selected ' + noun + '? This action cannot be undone.';
        }
        var actionLabel = [element && element.textContent, submitter && submitter.textContent,
            submitter && submitter.value, submitter && submitter.name].filter(Boolean).join(' ');
        if (/remove|delete/i.test(actionLabel) && /photo|image|logo/i.test(actionLabel)) {
            return 'Are you sure you want to remove this photo? This action cannot be undone.';
        }
        return 'Are you sure you want to remove this?';
    }

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement) || !isDeleteConfirmation(form, event.submitter)) return;
        if (form.dataset.deleteConfirmed === '1') {
            delete form.dataset.deleteConfirmed;
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        var submitter = event.submitter || null;
        var pendingRemovals = selectedRemovalInputs(form);
        var photoRemoval = pendingRemovals.length > 0 && isPhotoRemoval(pendingRemovals);
        var photoAction = photoRemoval || (/remove|delete/i.test([form.action, submitter && submitter.textContent, submitter && submitter.value].filter(Boolean).join(' ')) && /photo|image|logo/i.test([form.action, submitter && submitter.textContent, submitter && submitter.value].filter(Boolean).join(' ')));
        var message = confirmationMessage(form, submitter);
        var confirmLabel = 'Confirm';
        if (photoAction) confirmLabel = photoRemoval && pendingRemovals.length > 1 ? 'Yes, Remove Photos' : 'Yes, Remove Photo';
        else if (/cancel/i.test(message)) confirmLabel = 'Yes, Cancel';
        else if (/remove/i.test(message)) confirmLabel = 'Yes, Remove';
        else if (/delete/i.test(message)) confirmLabel = 'Yes, Delete';
        askForDelete(confirmationMessage(form, submitter), function () {
            form.dataset.deleteConfirmed = '1';
            if (typeof form.requestSubmit === 'function') {
                if (submitter && submitter.isConnected) form.requestSubmit(submitter);
                else form.requestSubmit();
            } else {
                form.submit();
            }
        }, submitter || form.querySelector('[type="submit"]'), {
            title: photoRemoval ? 'Remove selected photos?' : (photoAction ? 'Remove this photo?' : (/cancel/i.test(message) ? 'Confirm cancellation?' : undefined)),
            confirmLabel: confirmLabel,
            onCancel: pendingRemovals.length ? function () {
                pendingRemovals.forEach(function (input) { input.checked = false; });
                updatePendingRemovalStatus(form);
            } : null
        });
    }, true);

    document.addEventListener('change', function (event) {
        var input = event.target;
        if (!(input instanceof HTMLInputElement) || input.type !== 'checkbox' ||
                !/delete|remove/i.test(input.name || '') || !input.form) return;
        updatePendingRemovalStatus(input.form);
    }, true);

    document.addEventListener('click', function (event) {
        var target = event.target instanceof Element ? event.target.closest('a, button, input[type="submit"], input[type="button"]') : null;
        if (!target || target.dataset.deleteConfirmed === '1') return;
        if (target.matches('[data-count-change], [data-gd-minus], [data-rstep-minus], [data-remove-segment], [data-remove-room], [data-remove-item], .guest-remove, .bk-remove') ||
                (target.type === 'button' && target.hasAttribute('onclick') && /\.remove\(\)/.test(target.getAttribute('onclick')))) return;
        if (!isDeleteConfirmation(target)) return;
        var form = target.form || target.closest('form');
        if (form && form.matches('form[data-confirm]')) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        var targetMessage = confirmationMessage(target);
        askForDelete(targetMessage, function () {
            if (target instanceof HTMLAnchorElement) {
                window.location.assign(target.href);
            } else if (form && target.type === 'submit') {
                form.dataset.deleteConfirmed = '1';
                if (typeof form.requestSubmit === 'function') form.requestSubmit(target);
                else form.submit();
            } else {
                target.dataset.deleteConfirmed = '1';
                target.click();
                delete target.dataset.deleteConfirmed;
            }
        }, target, {
            title: /cancel/i.test(targetMessage) ? 'Confirm cancellation?' : undefined,
            confirmLabel: /cancel/i.test(targetMessage) ? 'Yes, Cancel' : (/remove/i.test(targetMessage) ? 'Yes, Remove' : (/delete/i.test(targetMessage) ? 'Yes, Delete' : 'Confirm'))
        });
    }, true);
})();
