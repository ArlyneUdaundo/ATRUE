(function () {
    'use strict';

    var overlay = null;
    var messageNode = null;
    var cancelButton = null;
    var confirmButton = null;
    var pendingAction = null;
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
            '<h2 id="deleteConfirmTitle">Are you sure?</h2>' +
            '<p id="deleteConfirmMessage">Are you sure you want to delete this?</p>' +
            '<div class="delete-confirm-modal__actions"><button type="button" class="delete-confirm-modal__cancel">Cancel</button>' +
            '<button type="button" class="delete-confirm-modal__confirm">Delete</button></div></div>';
        document.body.appendChild(overlay);
        messageNode = overlay.querySelector('#deleteConfirmMessage');
        cancelButton = overlay.querySelector('.delete-confirm-modal__cancel');
        confirmButton = overlay.querySelector('.delete-confirm-modal__confirm');
        cancelButton.addEventListener('click', closeModal);
        overlay.addEventListener('click', function (event) {
            if (event.target === overlay) closeModal();
        });
        confirmButton.addEventListener('click', function () {
            var action = pendingAction;
            closeModal();
            if (action) action();
        });
        overlay.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                event.preventDefault();
                closeModal();
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

    function closeModal() {
        if (!overlay || overlay.hidden) return;
        if (overlay.open) overlay.close();
        overlay.hidden = true;
        document.body.classList.remove('delete-confirm-open');
        pendingAction = null;
        if (returnFocus && returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
        returnFocus = null;
    }

    function askForDelete(message, action, trigger) {
        ensureModal();
        returnFocus = trigger || document.activeElement;
        messageNode.textContent = message || 'Are you sure you want to remove this?';
        confirmButton.textContent = /delete/i.test(messageNode.textContent) ? 'Delete' :
            (/remove/i.test(messageNode.textContent) ? 'Remove' : 'Confirm');
        overlay.hidden = false;
        if (typeof overlay.showModal === 'function' && !overlay.open) overlay.showModal();
        document.body.classList.add('delete-confirm-open');
        pendingAction = action;
        cancelButton.focus({ preventScroll: true });
    }

    function hasSelectedRemoval(form) {
        return !!form.querySelector('input[type="checkbox"]:checked[name*="delete" i], input[type="checkbox"]:checked[name*="remove" i]');
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
        return /delete|remove/i.test(label) || (isForm && hasSelectedRemoval(element));
    }

    function confirmationMessage(element, submitter) {
        var explicit = element && element.dataset && element.dataset.confirm;
        if (explicit) return explicit;
        if (element instanceof HTMLFormElement && hasSelectedRemoval(element)) {
            return 'Are you sure you want to remove the selected photo(s)?';
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
        askForDelete(confirmationMessage(form, submitter), function () {
            form.dataset.deleteConfirmed = '1';
            if (typeof form.requestSubmit === 'function') {
                if (submitter && submitter.isConnected) form.requestSubmit(submitter);
                else form.requestSubmit();
            } else {
                form.submit();
            }
        }, submitter || form.querySelector('[type="submit"]'));
    }, true);

    document.addEventListener('click', function (event) {
        var removalCheckbox = event.target instanceof Element
            ? event.target.closest('input[type="checkbox"][name*="delete" i], input[type="checkbox"][name*="remove" i]')
            : null;
        if (removalCheckbox && removalCheckbox.checked) {
            event.preventDefault();
            event.stopImmediatePropagation();
            askForDelete('Are you sure you want to remove this photo?', function () {
                removalCheckbox.checked = true;
                if (removalCheckbox.form) removalCheckbox.form.dataset.deleteConfirmed = '1';
            }, removalCheckbox);
            return;
        }
        var target = event.target instanceof Element ? event.target.closest('a, button, input[type="submit"], input[type="button"]') : null;
        if (!target || target.dataset.deleteConfirmed === '1' || !isDeleteConfirmation(target)) return;
        if (target.matches('[data-count-change], [data-gd-minus], [data-rstep-minus]')) return;
        var form = target.form || target.closest('form');
        if (form && form.matches('form[data-confirm]')) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        askForDelete(confirmationMessage(target), function () {
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
        }, target);
    }, true);
})();
